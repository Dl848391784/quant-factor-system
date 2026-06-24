# Design: Stock Selection History — Parquet Dataset (单一信源)

**版本**: v1.0
**作者**: 云瑶
**日期**: 2026-06-24
**状态**: Draft → 待审

---

## 0. 背景与触发

**用户问题（2026-06-24）**：
1. summary 报告"八、股票选股结果"只展示 Stage 3 最终 30 只，看不到 Stage 1/Stage 2 的中间结果；
2. Top 10 表面"未按 composite 降序排"——实际是 v2.44 两阶段选股 Stage 2 按 `turnover_rate` 升序重排所致，但报告未披露此排序逻辑。

**用户决策（2026-06-24）**：
- 把 Stage 1/Stage 2 的 Top 30 也展示出来；
- **持久化用列式存储（Parquet）**，加时间字段便于归档与扩展；
- **不要 JSON 兜底**——废除现有 `stock_selection_result.json`，Parquet 作为唯一产物信源。

---

## 1. 第一性原理：为什么 Parquet 分区数据集

| 备选 | 评估 |
|---|---|
| 单文件 JSON | 现状。无法跨日查询、无 schema 强约束、字段扩展靠约定。**不符合"加时间扩展"诉求**。 |
| 按日期分 JSON | "跨日某股票 stage1_rank 轨迹"需遍历 N 个文件。无 schema、无列裁剪。**没有数据库价值**。 |
| SQLite | 行存，分析查询不占优；引入新依赖（项目零数据库）；和现有 `factor_ic_data.parquet` 技术栈割裂。 |
| DuckDB | 引入新依赖；项目零先例。 |
| **Parquet 分区数据集（pyarrow）** | ✅ 列式、按 `selection_date` 分区天然时间归档；✅ 项目 v3.6 已用（pyarrow 是事实核心依赖）；✅ partition pruning 让单日查询 = 单分区读；✅ 跨日扫描走列式 + Arrow zero-copy。 |

**结论**：Parquet 分区数据集，方案与项目既有数据栈一致，零新依赖。

---

## 2. 数据集 Schema

### 2.1 物理布局（Hive-style partitioning）

```
comprehensive_factor/result/stock_selection_history/
├── selection_date=2026-06-23/
│   └── part-0.parquet
├── selection_date=2026-06-24/
│   └── part-0.parquet
└── ...
```

每个分区一个文件，文件名固定 `part-0.parquet`（单进程串行写入，无 part-N 需求）。

### 2.2 行结构（每天 90 行 = Stage 1 Top 30 + Stage 2 Top 30 + Stage 3 Top 30）

| 列名 | 类型 | 可空 | 说明 |
|---|---|---|---|
| `selection_date` | `string` | 否 | 分区键，`YYYY-MM-DD`（T-1 日期） |
| `stage` | `int8` | 否 | 1 / 2 / 3 |
| `rank` | `int16` | 否 | 当前 stage 内的名次（1-based） |
| `code` | `string` | 否 | 股票代码（6 位）|
| `composite_value` | `float64` | 否 | 综合因子值（同一只股票不同 stage 值相同） |
| `weight_coverage` | `float64` | 是 | 覆盖率（同 v2.x 现有语义）|
| `stage1_rank` | `int16` | 是 | stage>=2 时填该股在 stage1 内的名次；stage=1 时 = `rank` |
| `stage2_sort_value` | `float64` | 是 | stage>=2 时填（如 `turnover_rate` 实际值）；stage=1 时 null |
| `excluded_at_stage3` | `string` | 是 | stage=2 但未进 stage3 时填淘汰原因（如 `'stabilization'`）；其他场景 null |
| `weight_method` | `string` | 否 | `equal_weight` / `ic_weight` / `icir_weight` / `rolling_icir_weight`（同一次 run 所有行一致） |
| `factor_direction` | `string` | 否 | `positive` / `negative` |
| `top_n` | `int16` | 否 | 配置中的 top_n（通常 30） |
| `stage1_pool_size` | `int16` | 否 | 配置中的 stage1_pool_size（通常 200） |
| `stage2_sort_col` | `string` | 否 | 配置中的 stage2_sort_col（如 `turnover_rate`） |
| `stage2_ascending` | `bool` | 否 | 配置中的 stage2_ascending |
| `direction_map_json` | `string` | 否 | `direction_map` dict 的 JSON 序列化字符串（pyarrow 不支持 dict 列，序列化存） |
| `flipped_factors_json` | `string` | 否 | `flipped_factors` 列表的 JSON 字符串 |
| `composite_score` | `float64` | 否 | 当前权重方法的综合得分 |
| `created_at` | `timestamp[us, UTC]` | 否 | ISO 时间戳 |
| `run_id` | `string` | 否 | UUID4，同一次 pipeline run 所有行一致 |
| `factor_values_json` | `string` | 是 | `factor_values`（原始）JSON 字符串（stage=3 行才填，stage=1/2 时 null）|
| `factor_values_std_json` | `string` | 是 | `factor_values_std`（标准化）JSON 字符串（stage=3 行才填）|
| `decision_card_json` | `string` | 是 | 决策卡片 JSON 字符串（stage=3 行才填）|

**核心设计选择说明**：

- **同一只股票多 stage 多行**：避免宽表稀疏问题，stage 是行维度而非列维度。查询"stage1 Top 30" = `filter(stage=1)`，查询"某股票各 stage 轨迹" = `filter(code=X)`。
- **嵌套 dict/list 列序列化为 JSON 字符串**：`factor_values` 是 `dict[str, float]`（8 因子）、`decision_card` 是 `dict` 嵌套结构——Parquet 支持 struct 列，但跨日扩展时若因子集变化（不同日子因子数不同）会破坏 schema 兼容。**用 JSON 字符串列规避 schema 漂移**，下游需要时解析。
- **meta 字段每行冗余**：90 行 × ~10 字符串字段开销可忽略；换来"任意行可独立查询/导出"的便利，避免读两张表 JOIN。
- **file-level metadata**：`excluded_by_*` 统计字段（不参与查询、仅供报告展示）写入 Parquet file metadata（pyarrow `write_table(metadata=...)`），与 v3.6 `factor_ic_data.parquet` 存 `dates` 数组的 pattern 一致。

### 2.3 File-level metadata（Parquet KV）

```python
{
    b"excluded_by_amplitude": b"0",
    b"excluded_by_coverage": b"0",
    b"excluded_by_liquidity": b"0",
    b"excluded_by_confirmation": b"33",
    b"excluded_by_filter": b'{"cum_return_5d_breakdown": 0}',  # JSON
    b"min_amplitude": b"0.01",
    b"min_weight_coverage": b"0.5",
    b"stocks_on_date": b"2790",
}
```

读取时用 `pyarrow.parquet.read_metadata(path).metadata`，summary 模块用于渲染"过滤统计"区块。

---

## 3. 写入路径与失败语义

### 3.1 写入流程（`stock_selector.py`）

新增 helper：

```python
def write_selection_history(
    stage1_stocks: list[dict],
    stage2_stocks: list[dict],
    stage3_stocks: list[dict],
    config: StockSelectorConfig,
    weight_config: dict,
    selection_date: str,
    direction_map: dict[str, str],
    flipped_factors: list[str],
    exclusion_stats: dict[str, int | dict],  # excluded_by_*
    stocks_on_date: int,
    output_dir: Path,
    logger: logging.Logger,
) -> Path:
    """写入 Parquet 分区数据集。失败抛异常，无降级。"""
```

**调用点**：`select_stocks()` 内，替换原 `save_result()` 调用（行 1400）。

**Stage 数据流改造**：
- 行 1266 `stage1_stocks` (Top stage1_pool_size, ~200) → **切片 Top 30 喂给 history 写入**
- 行 1311 `top_stocks` (stage2 输出, 60) → **切片 Top 30 喂给 history 写入**
- 行 1337 `top_stocks` (stage3 输出, 30) → **直接喂给 history 写入**

### 3.2 失败语义

**Parquet 写失败 = pipeline 失败**，直接抛 `OSError`/`pa.ArrowException`，按 AGENTS.md 规则 #6 退出码 1。**不写 try/except 兜底**——这违反用户"不要兜底"的明确要求，也违反 AGENTS.md 硬规则 #14（禁止永不触发或刻意吞异常的防御性分支）。

**单阶段选股（`enable_two_stage=False`）**：
- 只有 stage3 一种产物 → 只写 stage=3 行，30 行/天
- meta 字段 `stage1_pool_size`/`stage2_sort_col`/`stage2_ascending` 填配置中的 None → Parquet 用 sentinel 值或显式 null（schema 必须 nullable 化这三列）。**矫正 2.2 表**：把这三列改为 nullable。

### 3.3 重跑当日的处理

若 `selection_date=2026-06-23/` 分区已存在（如同日重跑 pipeline），用 `pyarrow.dataset.write_dataset(..., existing_data_behavior="delete_matching")`，覆盖该分区。其他历史分区不动。

---

## 4. 读取路径（`summary/generate_factor_summary_report.py`）

### 4.1 替换 `load_stock_selection_result`

```python
def load_stock_selection_history(
    selection_date: str | None,  # None = 取最新分区
    logger: logging.Logger,
) -> dict | None:
    """
    从 Parquet 数据集读取选股历史。
    返回结构兼容现有调用方:
      {
        "meta": {...},
        "stage1_stocks": [{rank, code, composite_value, ...}, ...],  # Top 30
        "stage2_stocks": [{rank, code, composite_value, stage1_rank, stage2_sort_value, ...}, ...],
        "stage3_stocks": [{rank, code, composite_value, stage1_rank, factor_values, decision_card, ...}, ...],
        "weight_config": {...},
      }
    """
```

实现要点：
1. 用 `pyarrow.dataset.dataset(path, partitioning="hive")`
2. 若 `selection_date=None`：列出所有分区，取 max
3. `filter(selection_date=...)`，按 `stage` 分组拆三段
4. 读 file-level metadata 还原 `excluded_by_*`
5. JSON 字符串列反序列化为 dict（lazy，按 stage 需要）

### 4.2 渲染三个 Stage 表格

`_generate_stock_selection_section` 内：

```
【Stage 1: Composite 降序 Top 30（alpha 子池头部）】
  排名 股票代码 股票名称 综合因子值 覆盖率
  ...

【Stage 2: 换手率升序 Top 30（避开线性尾部失效）】
  排名 股票代码 股票名称 综合因子值 Stage1名次 换手率 覆盖率
  ...

【Stage 3: 最终 Top 30（企稳过滤后）】← 现有的 Top 10 详表 + 11~30 简表迁到这里
  ...
```

**v2.44 之前注释 fix**：行 2300 "Top 1~10 为 composite 极值区（高信号 + 高波动）"——v2.44 后已非 composite 极值，改为：
> "Stage 3 排序 = Stage 2 换手率升序 + Stage 3 企稳过滤后保留次序。Top 10 不是 composite 极值。"

### 4.3 测试 mock 改造

`summary/test_cases/test_generate_factor_summary_report.py:1104` 的 `make_mock_stock_selection_data` fixture 从 dict-then-json-dump 改为 dict-then-写-tmp-Parquet。提供 helper `_write_mock_history_parquet(tmp_path, data)`。

---

## 5. JSON ↔ Parquet 迁移路径

**用户决策**：废除 JSON，Parquet 单一信源。

| 文件 | 处理 |
|---|---|
| `comprehensive_factor/result/stock_selection_result.json`（已存在的当日产物） | **保留为只读历史快照**，下次运行 pipeline 时不再生成、也不删除。 |
| `comprehensive_factor/result/stock_selection_result.json` 写入逻辑 | **删除**（`stock_selector.py:save_result()` 和 `output_file = ...` 行） |
| `comprehensive_factor/schemas/stock_selection_result.schema.json` | **保留**作为历史档案 + 加注释标记 `[deprecated]`；新增 `stock_selection_history.schema.json`（描述 Parquet 列约束） |
| `temporary/analyze_top10.py` / `exp_positive_only_factors.py` / `compare_old_new.py` | 临时脚本，已知会失效。**不修复**（AGENTS.md 规则 #3：temporary/ 不算契约）。design 中显式记录。 |

---

## 6. Schema 演进硬约束

写入 `comprehensive_factor/MODULE.md`：

| 演进操作 | 是否允许 | 约束 |
|---|---|---|
| 新增列 | ✅ | 必须 `nullable=True`；老分区读取该列得 `null`，不破坏向后兼容 |
| 删除列 | ❌ | 须走独立 design + 全量重写所有分区 |
| 列重命名 | ❌ | 同上 |
| 列类型变更（如 int16→int32） | ⚠️ | 仅允许向上兼容扩容；窄→宽 OK；其他需重写 |
| 分区键变更 | ❌ | 须独立 design + 数据迁移脚本 |

---

## 7. 跨模块契约同步

按 AGENTS.md 陷阱 1（路径迁移未同步）+ 规则 #12，本次改动**必须**同步：

| 文件 | 改动 |
|---|---|
| `PROJECT.md §1 跨模块数据契约表` | comprehensive_factor 行：输出从 `stock_selection_result.json` 改为 `stock_selection_history/` 数据集 |
| `PROJECT.md §JSON Schema 治理表` | 新增 `stock_selection_history.schema.json`；旧 `stock_selection_result.schema.json` 标 `[deprecated]` |
| `PROJECT.md §版本历史` | 新增 v3.7 条目 |
| `comprehensive_factor/MODULE.md` | "输出"小节改写；新增 schema 演进硬约束小节 |
| `summary/MODULE.md` | "依赖"小节：依赖文件从 `stock_selection_result.json` 改为 `stock_selection_history/` |
| `AGENTS.md §1 跨模块数据路径表` | 同 PROJECT.md 同步 |
| `run_pipeline.py:121` 注释 | 输出路径同步 |
| 新增 `comprehensive_factor/schemas/stock_selection_history.schema.json` | 描述 Parquet 列约束（JSON Schema 形式，与项目其他 schema 风格一致） |

---

## 8. 测试方案

### 8.1 单元测试（comprehensive_factor）

新增 `comprehensive_factor/test_cases/test_selection_history_parquet.py`：

| 测试 | 校验 |
|---|---|
| `test_write_three_stages_basic` | 写入后用 pyarrow 读取，校验 stage=1/2/3 各 30 行 |
| `test_partition_key_correct` | 校验目录结构 `selection_date=YYYY-MM-DD/part-0.parquet` |
| `test_file_level_metadata_roundtrip` | excluded_by_* 写入后可读取还原 |
| `test_rerun_same_date_overwrites_partition` | 同日重跑覆盖该分区，其他分区不动 |
| `test_single_stage_mode_only_stage3` | enable_two_stage=False 时只有 stage=3 行 |
| `test_factor_direction_field` | 替代 `test_direction_unify.py` 现有的 JSON 读取断言 |
| `test_no_json_file_written` | 主流程不再产生 `stock_selection_result.json`（防回归） |

### 8.2 集成测试（summary）

修改 `test_generate_factor_summary_report.py`：

| 测试 | 校验 |
|---|---|
| `test_stock_selection_section_renders_three_stages` | 报告包含 "Stage 1: " / "Stage 2: " / "Stage 3: " 三个小标题 |
| `test_stage2_table_has_stage1_rank_column` | Stage 2 表格含 stage1_rank 列 |
| `test_stage1_top_value_higher_than_stage3_top` | （数据特征）Stage 1 第 1 名的 composite 通常 ≥ Stage 3 第 1 名 |

### 8.3 端到端（手工，但必做）

```bash
python run_pipeline.py --start-stage 6  # 重跑 composite → stock_selector → summary
ls comprehensive_factor/result/stock_selection_history/  # 确认分区创建
python -c "
import pyarrow.dataset as ds
d = ds.dataset('comprehensive_factor/result/stock_selection_history', partitioning='hive')
import pandas as pd
df = d.to_table().to_pandas()
print(df.groupby('stage').size())  # 期望 1:30, 2:30, 3:30
"
# 读 summary 实际报告（不是 pytest，按用户偏好"重跑后必读实际报告"）
less summary/result/factor_summary_report_$(date +%Y-%m-%d).txt
```

---

## 9. 风险与缓解

| 风险 | 概率 | 缓解 |
|---|---|---|
| pyarrow 写 Parquet 时 timestamp 时区丢失 | 中 | 用 `pa.timestamp("us", tz="UTC")` 显式指定；测试覆盖 roundtrip |
| 同日重跑时 `existing_data_behavior="delete_matching"` 误删其他分区 | 低 | 写入前显式 assert `selection_date` 字段值一致；测试 `test_rerun_same_date_overwrites_partition` 覆盖 |
| JSON 字符串列在跨日扫描中无法做 SQL filter | 接受 | 嵌套字段不参与跨日聚合查询；需 filter 时反序列化到 pandas |
| pyarrow 版本兼容 | 低 | 项目 v3.6 已用 pyarrow（间接经 pandas），不固定版本；测试在 CI 环境跑 |
| 写入失败导致 pipeline 中断 | 低 | 这是**预期行为**（无兜底）。失败后 pipeline 退出码 1，cron/CI 告警 |
| `temporary/` 临时脚本失效 | 接受 | AGENTS.md 规则 #3 明文 temporary 不算契约；design 已显式记录 |

---

## 10. 不在本期范围

- D4 历史画像（决策卡片"近 30 天回放"）—— 独立 design（依赖本期数据集就绪后才能做）
- DuckDB 直接 SQL 查询接口 —— 用户未要求，先用 pyarrow.dataset filter
- Web UI 展示历史轨迹 —— 不在范围
- 旧 JSON 数据回填 Parquet —— 1 天数据无价值，不做

---

## 11. 任务粒度拆分（AGENTS.md Design-First 任务粒度约束）

按"≤3 文件、≤200 行/任务"，拆为 4 个原子任务，分别 commit：

| 任务 | 涉及文件 | 估算行数 | 验收 |
|---|---|---|---|
| **T1** 写入侧 | `stock_selector.py` (改 build_result/save_result + 新增 write_selection_history) | ~180 行新增 + 30 行删除 | 新单测 7 个全绿 |
| **T2** Schema + 模块契约 | `comprehensive_factor/schemas/stock_selection_history.schema.json` (新) + `comprehensive_factor/MODULE.md` + 旧 schema 标 deprecated | ~100 行 | jsonschema 校验通过 |
| **T3** 读取侧 | `summary/generate_factor_summary_report.py` (改 load_xxx + 渲染三表) + 测试 fixture 改写 | ~200 行 | 报告渲染 3 stage 标题；集成测试绿 |
| **T4** 项目契约同步 + 端到端验证 | `PROJECT.md` + `AGENTS.md` + `run_pipeline.py` 注释 + 端到端跑 pipeline 读实际报告 | ~50 行 | 实际报告含 stage 1/2/3 三表；与 Parquet dataset 数据一致 |

每个任务结束：`ruff check . && ruff format . && pytest -x` → 即时 commit（引用 design 行号 + 规范号）。

---

## 12. 验收清单（design 评审通过后逐项核对）

- [ ] Parquet 数据集 `selection_date=2026-06-23/part-0.parquet` 生成，含 90 行（stage 1/2/3 各 30）
- [ ] file-level metadata 含 `excluded_by_*` 统计
- [ ] **不再生成** `stock_selection_result.json`（pipeline 验证）
- [ ] summary 报告"八、股票选股结果"含【Stage 1】【Stage 2】【Stage 3】三个子表
- [ ] Stage 2 表格含 stage1_rank 列、stage2_sort_value (turnover_rate) 列
- [ ] 行 2300 旧注释"composite 极值区"已修正
- [ ] PROJECT.md / AGENTS.md / 两个 MODULE.md 同步更新
- [ ] 新 schema 文件可被 `schemas/validate_schemas.py` 校验通过
- [ ] ruff/pytest/import-linter 全绿
- [ ] 每个任务 commit 引用 design 行号 + AGENTS.md 规则编号
- [ ] 本 design 最后追加"Execute 阶段完成回顾"小节（实际行数 vs 估算）
