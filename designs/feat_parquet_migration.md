# Design: 统一数据源 JSON.gz → Parquet 列式存储迁移

> 创建: 2026-06-22  
> 状态: [experimental]  
> 规范引用: PROJECT.md 跨模块数据路径表（AGENTS.md §1）、规则 #2 输出位置、规则 #11 路径导入

---

## §1 背景与问题

### 1.1 现状

| 指标 | 数值 |
|------|------|
| `factor_ic_data.json.gz` 压缩大小 | 705MB |
| 解压后大小 | 2.17GB |
| 数据行数 | ~149万行 × 65 列 |
| IC 脚本数 | 54 |
| Backtest 脚本数 | 54 |
| 每次 pipeline 总加载次数 | 108 次 × 705MB JSON 文本解析 |
| 机器可用内存 | ~3.8GB |

### 1.2 问题根因

**JSON 是文本序列化格式**：每个值存储为文本字符，读取时需逐字符解析 + 类型转换。  
即使已用 ijson 流式解析避免 OOM，108 个脚本各自做一遍文本解析仍然极慢。

**两层 OOM**：
- 加载层：`json.load` 全量加载 4+GB → 已用 ijson 缓解（但仍慢）
- 计算层：`groupby.transform` / `df.copy()` → 已用 3 个 OOM 模式修复

**换存储格式解决的是加载层**——列式二进制格式让"只读需要的列"成为物理级别的操作，而非代码层面的字段过滤。

### 1.3 第一性原理

| 原理 | JSON.gz | Parquet | SQLite/PostgreSQL |
|------|---------|---------|-------------------|
| 存储模型 | 行式文本 | **列式二进制** | 行式（读列仍读全行） |
| 列投影 | ❌ 解析全部字段后代码过滤 | ✅ 物理只读目标列的数据块 | ❌ 行式存储无列投影 |
| 类型系统 | 文本→运行时转换 | 原生 float64/int/bool | 需 SQL 类型映射 |
| 内存峰值 | ~500MB（ijson 列式累积） | **~50-150MB**（仅目标列） | ~500MB+（行式加载） |
| Server 开销 | 无 | 无 | PostgreSQL 需常驻进程争 7.3GB 内存 |

**结论**：108 个脚本各自需要不同列子集的访问模式 → 列式存储是第一性原理推导的正确解。

---

## §2 方案对比

### 方案 A：一次性迁移（激进）

所有读写点同时切换到 Parquet，删除 JSON.gz。

| 维度 | 评价 |
|------|------|
| 速度 | 快，一次改完 |
| 风险 | **高**——15+ 文件同时改，任何遗漏导致 pipeline 断裂 |
| 回退 | 需 git revert 全部改动 |
| 合规 | 违反 AGENTS.md 任务粒度约束（≤3 文件 ≤200 行） |

### 方案 B：分阶段迁移（推荐）✅

分 5 个 Phase，每个 Phase ≤3 文件 ≤200 行，每个 Phase 独立可验证。

| Phase | 内容 | 文件数 | 预计行数 |
|-------|------|--------|---------|
| L1 | 写出层：factor_generator 输出 Parquet（保留 JSON.gz dual-write） | 2 | ~80 |
| L2 | 读取核心：factor_ic + backtest common data_loader 切换 Parquet | 2 | ~60 |
| L3 | 读取扩展：comprehensive_factor + data_completeness + data_columns | 3 | ~100 |
| L4 | 读取辅助：summary 新鲜度检查 + reverse_discovery data_splitter | 2 | ~80 |
| L5 | 清理：移除 JSON.gz dual-write + 路径常量统一 + 测试更新 + 文档 | 3 | ~120 |

**决策：方案 B**。理由：AGENTS.md 任务粒度约束 + 每个 Phase 可独立 ruff/pytest 验证。

---

## §3 详细设计

### 3.1 存储格式

| 项 | 值 | 来源 |
|----|-----|------|
| 文件格式 | Parquet | 列式二进制，pandas 原生支持 |
| 压缩 | Snappy | 读写速度最优，压缩率适中（vs gzip/zstd） |
| 引擎 | pyarrow | `pd.read_parquet` / `df.to_parquet` 默认引擎 |
| 依赖 | `pyarrow>=14.0` | 需新增到 pyproject.toml |

**DuckDB 暂不引入**：当前 108 脚本通过 common 层 `pd.read_parquet()` 即可获得全部收益。DuckDB 在后续有 SQL 查询需求时增量加一行 `duckdb.sql(...)` 即可。

### 3.2 文件路径

| 变量 | 路径 | 定义位置 |
|------|------|---------|
| `FACTOR_IC_DATA_PARQUET` | `data_fetchers/result/factor_ic_data.parquet` | paths.py（新增） |
| `FACTOR_IC_DATA` | `data_fetchers/result/factor_ic_data.json.gz` | paths.py（L5 阶段移除） |

L1~L4 阶段 dual-write：factor_generator 同时输出 `.parquet` 和 `.json.gz`。  
L5 阶段移除 `.json.gz`，`FACTOR_IC_DATA` 指向 `.parquet`。

### 3.3 dates 数组处理

**现状**：JSON 顶层 `{"dates": [...], "data": [...]}`，dates 是独立数组。  
**Parquet 方案**：dates 存入 Parquet 文件级自定义 metadata。

```python
# 写入
import pyarrow as pa
import pyarrow.parquet as pq

table = pa.Table.from_pandas(output_df)
# dates 数组存入 file-level metadata
table = table.replace_schema_metadata({
    **(table.schema.metadata or {}),
    b"dates": json.dumps(sorted(output_df["date"].unique().tolist())).encode()
})
pq.write_table(table, path, compression="snappy")

# 读取 dates（仅读 metadata，不读数据）
schema = pq.read_schema(path)
dates = json.loads(schema.metadata[b"dates"])
```

**fallback**：若 metadata 缺失，读 date 列 `pd.read_parquet(path, columns=["date"])["date"].unique()`。

| 方案 | 读取速度 | 内存 | 复杂度 |
|------|---------|------|--------|
| Parquet metadata（选） | ~0ms（仅读 footer） | ~0 | 低 |
| 读 date 列 fallback | ~0.5s | ~12MB | 极低 |

### 3.4 列类型映射

| JSON 中的类型 | Parquet 类型 | 处理 |
|--------------|-------------|------|
| date (str "YYYY-MM-DD") | string | 原样保留 |
| asset (str "000001") | string | 原样保留 |
| open/close/high/low (Decimal→float) | double | Parquet 原生 float64，无需 `_json_safe_value` |
| 因子列 (float/NaN) | double | NaN 是 Parquet 原生支持，无需转 None |
| is_untradeable/is_low_liquidity (int 0/1) | int8 | 节省空间 |
| volume (float) | double | — |

**关键简化**：`_json_safe_value` / `_nan_to_null` 函数在 Parquet 写入路径中**不再需要**——Parquet 原生支持 NaN 和 numpy 类型。仅在 L5 移除 JSON.gz 时删除这些函数。

### 3.5 companion file（factor_ic_data_columns.json）

**现状**：factor_generator 写出 `factor_ic_data_columns.json`，`factor_ic/common/data_columns.py` 读取它做列存在性检查。  
**Parquet 方案**：Parquet 自带 schema（列名 + 类型），companion file 冗余。

| 阶段 | 处理 |
|------|------|
| L1~L4 | 保留 companion file（从 Parquet schema 生成，保持兼容） |
| L5 | `data_columns.py` 改为从 Parquet schema 读取，移除 companion file |

---

## §4 改动清单（按 Phase）

### L1: 写出层（2 文件）

| 文件 | 改动 | 预计行数 |
|------|------|---------|
| `paths.py` | 新增 `FACTOR_IC_DATA_PARQUET` 常量 | ~3 行 |
| `data_fetchers/factor_generator.py` | 新增 `_write_factor_parquet()` 函数；Step 13 调用 dual-write | ~70 行 |

**验证**：运行 factor_generator，确认 `.parquet` 文件生成且可 `pd.read_parquet()` 读取。

### L2: 读取核心层（2 文件）

| 文件 | 改动 | 预计行数 |
|------|------|---------|
| `factor_ic/common/data_loader.py` | `load_factor_return_data()` ijson → `pd.read_parquet(columns=...)` | ~30 行 |
| `backtest/common/layered_backtest_runner.py` | `load_factor_return_data()` ijson → `pd.read_parquet(columns=...)` | ~30 行 |

**验证**：运行 2 个 IC 脚本 + 2 个 backtest 脚本，对比 IC 值和回测结果与 JSON.gz 一致。

### L3: 读取扩展层（3 文件）

| 文件 | 改动 | 预计行数 |
|------|------|---------|
| `comprehensive_factor/common/factor_loader.py` | ijson → `pd.read_parquet(columns=...)` | ~30 行 |
| `factor_ic/common/data_completeness.py` | ijson dates 读取 → Parquet metadata | ~25 行 |
| `factor_ic/common/data_columns.py` | 从 Parquet schema 读取列名（保留 companion file fallback） | ~30 行 |

**验证**：运行 comprehensive_factor pipeline + data_completeness 检查。

### L4: 读取辅助层（2 文件）

| 文件 | 改动 | 预计行数 |
|------|------|---------|
| `summary/generate_factor_summary_report.py` | 新鲜度检查 gzip 头部解析 → Parquet metadata；相关性计算 → `pd.read_parquet` | ~50 行 |
| `reverse_discovery/data_splitter.py` | ijson 读取 → `pd.read_parquet`；子集写出 → `to_parquet` | ~30 行 |

**验证**：运行 summary 报告生成 + data_splitter 切分。

### L5: 清理（3 文件）

| 文件 | 改动 | 预计行数 |
|------|------|---------|
| `paths.py` | `FACTOR_IC_DATA` 指向 `.parquet`；移除旧常量 | ~5 行 |
| `data_fetchers/factor_generator.py` | 移除 `_write_factor_json_gz` + `_json_safe_value` + `_nan_to_null` + companion file 写出 | ~40 行 |
| `backtest/common/data_loader.py` + `comprehensive_factor/common/data_loader.py` + `comprehensive_factor/stock_selector.py` | 路径常量指向 `.parquet` | ~15 行 |

**测试更新**（8 文件，机械替换）：
- `backtest/test_cases/test_layered_backtest_runner_data_loader.py`
- `comprehensive_factor/test_cases/test_factor_loader_streaming.py`
- `data_fetchers/test_cases/test_factor_generator_helpers.py`
- `factor_ic/test_cases/test_data_columns.py`
- `factor_ic/test_cases/test_data_loader_decimal_coerce.py`
- `factor_ic/test_cases/ic_rsi_1d_test_cases.py`
- `reverse_discovery/test_cases/test_data_splitter.py`
- `summary/test_cases/test_generate_factor_summary_report.py`

**文档更新**：AGENTS.md §1 跨模块数据路径表、run_pipeline.py Stage 1 注释、各 MODULE.md。

**验证**：完整 `run_pipeline` 全流程 + 全部 pytest。

---

## §5 预期收益

| 指标 | 现状（JSON.gz + ijson） | 迁移后（Parquet） | 改善 |
|------|----------------------|-------------------|------|
| 单脚本加载时间 | ~30s | ~0.5-2s | **15-60x** |
| 单脚本内存峰值 | ~500MB | ~50-150MB | **3-10x** |
| pipeline 加载总耗时 | ~54 分钟 | ~2.7 分钟 | **20x** |
| 文件大小 | 705MB | ~200-300MB | **2-3x** |
| 并行可行性 | ❌ 4 并发 = 2GB+ OOM | ✅ 4 并发 = ~600MB | 可并行 |

---

## §6 风险与缓解

| 风险 | 概率 | 影响 | 缓解 |
|------|------|------|------|
| Parquet Decimal 精度丢失 | 低 | 中 | factor_generator 写入前 `df[col] = df[col].astype(np.float64)` |
| dates metadata 丢失 | 低 | 低 | fallback 读 date 列 |
| pyarrow 安装失败 | 中 | 高 | `pip install pyarrow` 或 `conda install pyarrow`；如失败回退 JSON.gz |
| 测试中 mock 数据格式不兼容 | 中 | 低 | 测试改用 `df.to_parquet()` 生成 mock 文件 |
| data_splitter 子集文件格式变更 | 中 | 中 | L4 同步改写出格式为 Parquet |

---

## §7 不改动的部分

| 项 | 理由 |
|----|------|
| 108 个 IC/backtest 脚本 | 它们调 common 层 `load_factor_return_data()`，改 common 层即全改 |
| 其他 JSON.gz 数据文件 | `factor_data.json.gz` / `turnover_rate_data.json.gz` 等是输入文件，由 fetch 脚本产生，单独评估 |
| DuckDB | 后续按需引入，当前 `pd.read_parquet()` 足够 |

---

## §8 验证方案

每个 Phase 完成后执行：

```
□ ruff check --fix . && ruff format . && ruff check .
□ pytest <对应模块>/test_cases/ -v
□ 运行 1 个 IC 脚本 + 1 个 backtest 脚本，对比结果与基线一致
□ git commit -m "feat: L{n} parquet migration <描述> (遵循 PROJECT.md §1)"
```

L5 完成后执行完整验证：

```
□ 完整 run_pipeline 全流程
□ pytest --cov-fail-under=70
□ 文件大小对比：ls -lh factor_ic_data.parquet vs factor_ic_data.json.gz
□ 加载速度对比：/usr/bin/time -v python -c "pd.read_parquet(...)"
```
