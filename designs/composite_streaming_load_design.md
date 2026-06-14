# Design：综合因子模块流式数据加载（OOM 修复，方案 C）

> 遵循 AGENTS.md Design-First 流程（涉及 ≥2 文件改动）
> 创建日期：2026-06-14
> 作者：云瑶
> 状态：待审

---

## 目录

- [1. 背景与目标](#1-背景与目标)
- [2. 方案设计](#2-方案设计)
- [3. 影响范围](#3-影响范围)
- [4. 数据流对比](#4-数据流对比)
- [5. 测试方案](#5-测试方案)
- [6. 风险与回滚](#6-风险与回滚)
- [7. 上线步骤](#7-上线步骤)
- [8. 验收标准](#8-验收标准)
- [9. 关联规范](#9-关联规范)

---

## 1. 背景与目标

### 1.1 痛点（实测 OOM）

**故障现象**（2026-06-14）：

`composite_equal_weight_1d.py` 通过 `run_pipeline.py` 触发执行，**两次连续被 SIGKILL（退出码 -9）**：

| 时间 | 事件 | dmesg 证据 |
|------|------|-----------|
| 15:27:15 | `Killed process 2187256 (python) anon-rss:4.17GB` | `oom-kill:constraint=CONSTRAINT_NONE,task_memcg=/user.slice/user-1000.slice/session-12225.scope` |
| 15:30:09 | 重试启动，日志只写到「加载统一数据源」510 字节即中断 | dmesg ring buffer 已截断，但内存模式与第一次一致 |

**历史 OOM 重复模式**（同一脚本 2026-06-13 22:00-22:04 连续 5 次 OOM Kill，均 ~4.1GB RSS）— 说明这是**确定性失败**，重试机制无法解决。

### 1.2 根因（已诊断确认）

`comprehensive_factor/common/factor_loader.py:73-79`：

```python
with gzip.open(data_source, "rt", encoding="utf-8") as f:
    data = json.load(f)              # ← Step 1: 一次性解压并解析 390MB gzip → ~2-3GB Python dict
full_df = pd.DataFrame(data["data"]) # ← Step 2: 再分配 ~2GB DataFrame
```

**内存峰值 = JSON dict + DataFrame 同时驻留 ≈ 4-5GB**

环境约束：
- 阿里云 ECS 总内存 7.3GB，swap 2GB
- 数据源 `factor_ic_data.json.gz` = **390MB 压缩**，含 44 列 × ~149 万行
- 当其他进程占 3GB 时（pipeline orchestrator + 后台脚本），可用 RAM < 4GB → 必 OOM

### 1.3 目标

1. **流式加载**：消除「整个 JSON 在内存中以 Python dict 形式驻留」这一中间态
2. **峰值降至 < 1GB**：参考 factor_ic v3 实测（4.2GB → <500MB）
3. **零行为变更**：返回的 DataFrame 在 schema、行数、值上与现有 `json.load` 版本完全一致
4. **可回退**：`ijson` ImportError 时自动 fallback 到 `json.load`（与 factor_ic v3 一致）
5. **统一公共函数**：`load_full_data()` + `load_factor_values()` 共享流式实现，避免双份维护

### 1.4 非目标

- ❌ 不改 4 个 `composite_*_weight_1d.py` 脚本（薄声明，仅通过 `composite_runner` 间接调用）
- ❌ 不改 `composite_runner.py` 业务逻辑（标准化、加权、回测流程不变）
- ❌ 不改 `factor_ic/common/data_loader.py`（已有 v3 实现，不在本次范围）
- ❌ 不改数据源 schema 或 JSON 文件格式
- ❌ 不引入其他流式库（如 `orjson`/`msgpack`），仅复用 `ijson 3.5.0`（已安装）

### 1.5 用户决策依据

用户 2026-06-14 选择方案 C（优化数据加载，根治）而非：
- 方案 A（释放内存重跑）：不解决根因
- 方案 B（脱离 pipeline 单独跑）：临时方案
- 方案 D（加 swap）：性能下降，治标

**核心理由**：OOM 是确定性失败，重试无法解决；下次 pipeline 仍会复发；且 `factor_ic` 模块已有验证过的 v3 模板可复用，工程风险低。

---

## 2. 方案设计

### 2.1 核心思路（直接复用 factor_ic v3 模板）

`factor_ic/common/data_loader.py:111-153` 已有完整的流式实现，2026-06-13 上线后稳定运行。本设计**照搬 v3 模式**到 `comprehensive_factor/common/factor_loader.py`，关键三点：

| 维度 | 旧实现（json.load） | 新实现（v3 模板） | 收益 |
|------|--------------------|-------------------|------|
| **解析** | `json.load(f)` 一次性载入完整 dict | `ijson.items(f, 'data.item')` 流式逐条 | 不持有完整 JSON dict |
| **累积** | `pd.DataFrame(data["data"])` 直接转 list[dict] | `dict[col, list]` 列式累积 | 省掉 N 个 dict 对象头开销 |
| **构建** | pandas 推断每列类型 | `pd.DataFrame(列式字典)` 直接列存 | 无中间拷贝 |

**为什么 v1/v2 失败但 v3 成功**（factor_ic 的演进经验，已嵌入注释）：

- **v1（list[dict]）**：149 万行 × 44 列的 dict 对象头本身占 ~600MB，加 DataFrame 共 ~2.6GB
- **v2（pd.concat）**：concat 时多块同时驻留 + 新 DataFrame 三份共存，峰值 ~4GB
- **v3（列式 dict）**：每列一个扁平 list[scalar]，149 万 × 44 列约 60MB，相比 list[dict] 降 10 倍

### 2.2 函数签名变更（向后兼容）

#### 2.2.1 `load_full_data()` —— 加入可选列过滤

```python
def load_full_data(
    data_source: str | Path | None = None,
    factor_cols: list[str] | None = None,  # 新增：可选列过滤
    logger: logging.Logger | None = None,
) -> pd.DataFrame:
    """流式加载统一数据源。

    Args:
        data_source: 数据源文件路径（默认 DEFAULT_DATA_SOURCE）
        factor_cols: 可选因子列过滤
            - None: 加载全部列（保持原有行为，composite_runner 入口走这条）
            - [...]: 只加载 date + asset + factor_cols + forward_return_*
        logger: 日志对象

    Returns:
        包含所需列的完整 DataFrame
    """
```

**关键点**：
- 默认 `factor_cols=None` 时**完全保持现有行为**，composite_runner 第 244 行调用无需改动
- 传入 `factor_cols` 时，自动追加 `date / asset / forward_return_1d / forward_return_3d / forward_return_5d`（5 个固定列），允许 `stock_selector` 等下游进一步降低内存

#### 2.2.2 `load_factor_values()` —— 委托给 `load_full_data`

```python
def load_factor_values(
    factor_cols: list[str],
    data_source: str | Path | None = None,
    logger: logging.Logger | None = None,
) -> pd.DataFrame:
    """从统一数据源加载因子原始值（含 date, asset, factor_cols 列）。

    实现：内部委托 load_full_data(factor_cols=factor_cols)，
         避免双份维护流式逻辑。
    """
    full_df = load_full_data(data_source=data_source, factor_cols=factor_cols, logger=logger)
    # 仅返回 date + asset + factor_cols（与现有签名兼容，不含 forward_return_*）
    return full_df[["date", "asset"] + factor_cols].copy()
```

`stock_selector.py:678` 调用方式无需任何改动。

### 2.3 核心实现（新版 `load_full_data`）

```python
def load_full_data(
    data_source: str | Path | None = None,
    factor_cols: list[str] | None = None,
    logger: logging.Logger | None = None,
) -> pd.DataFrame:
    if logger is None:
        from comprehensive_factor.common.logger_config import get_logger
        logger = get_logger(__name__)

    if data_source is None:
        data_source = DEFAULT_DATA_SOURCE
    data_source = Path(data_source)

    if not data_source.exists():
        raise FileNotFoundError(
            f"统一数据源文件不存在: {data_source}\n"
            "请先运行 data_fetchers/factor_generator.py 生成数据"
        )

    logger.info("流式加载统一数据源: %s", data_source)

    # === 决定需加载的列集合 ===
    # factor_cols=None: 不限制（peek 首条记录后取全部 keys）
    # factor_cols=[...]: 限制为 date + asset + factor_cols + 5 个收益列
    required_cols: list[str] | None
    if factor_cols is not None:
        return_cols = ["forward_return_1d", "forward_return_3d", "forward_return_5d"]
        required_cols = list(dict.fromkeys(["date", "asset"] + factor_cols + return_cols))
    else:
        required_cols = None  # peek 阶段决定

    # === 流式加载（v3 列式累积） ===
    df = None
    try:
        import ijson

        # peek 首条记录决定列集合（仅当 factor_cols=None 时）
        if required_cols is None:
            with gzip.open(data_source, "rb") as f:
                first_record = next(iter(ijson.items(f, "data.item")), None)
            if first_record is None:
                raise KeyError(f"数据源 JSON 'data' 数组为空: {data_source}")
            required_cols = list(first_record.keys())

        # 列式累积：每列预分配一个 list
        columns: dict[str, list] = {col: [] for col in required_cols}
        with gzip.open(data_source, "rb") as f:
            for record in ijson.items(f, "data.item"):
                for col in required_cols:
                    columns[col].append(record.get(col))

        if not columns.get("date"):
            raise KeyError(f"数据源 JSON 'data' 数组为空: {data_source}")

        # 一次性从列式字典构建 DataFrame
        df = pd.DataFrame(columns)
        del columns
        import gc
        gc.collect()
        logger.info("ijson 流式加载完成: %d 行 × %d 列", len(df), len(df.columns))

    except ImportError:
        # ijson 不可用 → 回退到 json.load（保留兼容性，与 factor_ic v3 一致）
        logger.warning("ijson 不可用，回退到 json.load（峰值 ~4GB，可能 OOM）")
        with gzip.open(data_source, "rt", encoding="utf-8") as f:
            data = json.load(f)
        if "data" not in data:
            raise KeyError(f"数据源 JSON 结构缺失 'data' 字段: {data_source}")
        df = pd.DataFrame(data["data"])
        del data
        import gc
        gc.collect()
        # fallback 路径下的列过滤
        if factor_cols is not None:
            df = df[required_cols].copy()

    # === 校验 date / asset 类型（保留现有逻辑） ===
    if len(df) > 0:
        first_date = df["date"].iloc[0]
        first_asset = df["asset"].iloc[0]

        if not isinstance(first_date, str):
            raise TypeError(
                f"date 列数据类型应为 str，实际为 {type(first_date).__name__}\n"
                f"首行 date 值: {first_date}\n"
                "可能原因：\n"
                "  1. JSON 文件中 date 字段为数字而非字符串\n"
                "  2. 数据生成脚本类型转换异常\n"
                "建议：检查 factor_ic_data.json.gz 生成逻辑"
            )

        if not isinstance(first_asset, str):
            raise TypeError(
                f"asset 列数据类型应为 str，实际为 {type(first_asset).__name__}\n"
                f"首行 asset 值: {first_asset}\n"
                "可能原因：\n"
                "  1. JSON 文件中 asset 字段为数字而非字符串\n"
                "  2. 数据生成脚本类型转换异常\n"
                "建议：检查 factor_ic_data.json.gz 生成逻辑"
            )

    logger.info("统一数据源: %d 条记录，类型校验通过", len(df))

    # === 数值列类型规范化（参考 factor_ic v3 第 200-203 行） ===
    # 背景：factor_ic_data.json.gz 中 OHLC 等价格列以 Decimal 字符串形式存储，
    #   pandas 读取后 dtype=object，下游计算触发 `Decimal - float` 类型不兼容。
    # 修复：对所有非键列统一 pd.to_numeric(errors="coerce")
    numeric_cols = [c for c in df.columns if c not in ("date", "asset")]
    for col in numeric_cols:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    logger.info("数值列类型规范化完成: %d 列（pd.to_numeric, Decimal/str → float）", len(numeric_cols))

    return df
```

### 2.4 设计决策记录

| 决策 | 选项 A | 选项 B（采用） | 理由 |
|------|--------|---------------|------|
| 流式库 | `orjson` 增量 / `simdjson` | `ijson 3.5.0`（已安装） | 与 factor_ic v3 一致，零新依赖 |
| 累积结构 | `list[dict]` (v1) / `pd.concat` (v2) | 列式 `dict[col, list]` (v3) | factor_ic 已实测 v1/v2 失败，v3 成功 |
| 列过滤时机 | 加载后 `df[cols]` | 累积时只 append 需要的列 | factor_cols 模式下提前过滤，省 ~80% 内存 |
| `load_factor_values` 实现 | 独立流式逻辑 | 委托 `load_full_data` | 避免双份维护，未来扩展只改一处 |
| Decimal 转换 | 留给调用方 | 加载时统一 `pd.to_numeric` | 与 factor_ic v3 对齐，消除下游 Decimal-float 错误 |
| ImportError 行为 | 抛错 | fallback 到 `json.load` + warning | 与 factor_ic v3 一致，保证 ijson 卸载时仍可运行（虽可能 OOM）|

---

## 3. 影响范围

### 3.1 文件改动清单

| # | 文件 | 类型 | 改动 | 估行数 |
|---|------|------|------|--------|
| 1 | `comprehensive_factor/common/factor_loader.py` | 重构 | `load_full_data` 改为流式 + 加 `factor_cols` 参数；`load_factor_values` 委托 | ~80 行（增加约 60，删除约 30） |
| 2 | `comprehensive_factor/MODULE.md` | 文档 | M21 数据来源章节 + L313 表格注明 ijson 流式；版本升 v2.23 | ~15 行 |
| 3 | `comprehensive_factor/test_cases/test_factor_loader_streaming.py` | 新建 | 一致性 / 列子集 / fallback / 必需列校验 4 个测试 | ~150 行 |
| 4 | `comprehensive_factor/docs/composite_runner_eliminate_duplicate_data_loading_design.md` | 文档同步 | 更新 v2.10 设计文档：新增 v2.23 流式说明附录 | ~20 行 |
| 5 | `designs/composite_streaming_load_design.md` | 新建 | 本文档 | — |

**改动总规模**：~265 行新增/修改，约 2 个核心文件 + 1 个测试文件 + 2 个文档。

### 3.2 调用链分析（间接受益方）

#### `load_full_data` 调用方

| 调用方 | 位置 | 调用形态 | 受益 |
|--------|------|---------|------|
| `composite_runner.py` | L244 | `load_full_data(data_source=..., logger=...)`（不传 factor_cols） | 全列加载，4-5GB → ~800MB |

→ 间接受益 4 个综合权重脚本（薄声明）：
- `composite_equal_weight_1d.py`
- `composite_ic_weight_1d.py`
- `composite_icir_weight_1d.py`
- `composite_rolling_icir_weight_1d.py`

#### `load_factor_values` 调用方

| 调用方 | 位置 | 调用形态 | 受益 |
|--------|------|---------|------|
| `stock_selector.py` | L678 | `load_factor_values(factor_cols, config.data_source, logger)` | 列子集加载，仅需 5-8 个因子 + 5 个固定列，峰值估 ~300MB |

### 3.3 不在改动范围（明确边界）

| 文件/模块 | 原因 |
|-----------|------|
| 4 个 `composite_*_weight_1d.py` 脚本 | 薄声明（80-90 行 Config + CLI），仅通过 `composite_runner` 间接调用，无需任何修改 |
| `composite_runner.py` | 仅 L244 调用 `load_full_data`，函数签名向后兼容，业务逻辑不动 |
| `factor_ic/common/data_loader.py` | 已有 v3 实现（本次复用其模式），不在范围 |
| 数据源 `factor_ic_data.json.gz` 生成逻辑 | 仅消费方优化，不动生产方 |
| `weight_engine.py` / `factor_selector.py` | 不接触数据加载层 |

### 3.4 数据契约不变性证明

新版 `load_full_data` 返回的 DataFrame 必须满足以下不变量（测试覆盖，见 §5）：

1. **列集合一致**：`set(new_df.columns) == set(old_df.columns)` 当 `factor_cols=None`
2. **行数一致**：`len(new_df) == len(old_df)`
3. **值一致**：每列 `new_df[col].equals(old_df[col])`（NaN 处理一致）
4. **dtype 一致**：除 Decimal 列已转 float64（这是新增的修复，与 factor_ic v3 一致），其余列 dtype 不变
5. **类型校验保留**：`date` / `asset` 必须是 `str`，否则抛 TypeError（保留现有规范）

---

## 4. 数据流对比

### 4.1 旧实现（json.load）内存时间线

```
Time →

  T0   gzip.open(file, "rt")
  T1   json.load(f)                                     ← 解压 + 解析
       ┌─────────────────────────────────────────┐
       │ Python dict (data["data"])  ~2.5GB     │      ← 149 万 dict 对象
       └─────────────────────────────────────────┘
  T2   pd.DataFrame(data["data"])                       ← 转 DataFrame
       ┌─────────────────────────────────────────┐
       │ Python dict   ~2.5GB                   │
       │ DataFrame     ~2.0GB                   │      ← 双份共存（峰值 4.5GB）
       └─────────────────────────────────────────┘     ★ OOM Killer 触发点
  T3   del data; gc.collect()
       ┌─────────────────────────────────────────┐
       │ DataFrame     ~2.0GB                   │
       └─────────────────────────────────────────┘
```

### 4.2 新实现（v3 流式 + 列式累积）内存时间线

```
Time →

  T0   gzip.open(file, "rb")
  T1   for record in ijson.items(f, "data.item"):       ← 流式逐条
         for col in required_cols:
           columns[col].append(record[col])
       ┌─────────────────────────────────────────┐
       │ columns: dict[col, list]  ~60MB        │      ← 列式累积（无 dict 对象头）
       │ ijson buffer              ~10MB        │
       └─────────────────────────────────────────┘
  T2   df = pd.DataFrame(columns)                       ← 一次性列存构建
       ┌─────────────────────────────────────────┐
       │ columns       ~60MB                    │
       │ DataFrame     ~700MB                   │      ← 峰值约 760MB
       └─────────────────────────────────────────┘
  T3   del columns; gc.collect()
       ┌─────────────────────────────────────────┐
       │ DataFrame     ~700MB                   │
       └─────────────────────────────────────────┘
```

**峰值对比**：4.5 GB → 760 MB（**降 ~83%**）

### 4.3 列子集模式（factor_cols=[...]）内存时间线

`stock_selector.py` 调用形态，仅需 5 个因子 + 5 个固定列：

```
required_cols = ["date", "asset", "rsi_6", "volume_ratio_5", "kdj_j",
                 "ma5_deviation", "near_high_ratio_5",
                 "forward_return_1d", "forward_return_3d", "forward_return_5d"]
                 # 共 10 列

  T1   columns: 10 列 × 149 万行 ≈ 15MB
  T2   DataFrame: 10 列 × 149 万行 ≈ 160MB
                 ─────────────────────
       峰值     ~175MB
```

**对比 stock_selector 旧实现**：通过 `load_factor_values` 旧路径，先 json.load 全 44 列（4.5GB 峰值）再切片 → 新路径直接 175MB。**降 ~96%**。

### 4.4 行为变更摘要表

| 项 | 旧 | 新 | 是否破坏性 |
|----|-----|-----|----------|
| `load_full_data()` 默认行为 | json.load 全列 | ijson 全列 | 否（输出一致） |
| `load_full_data(factor_cols=...)` | 不支持 | 流式仅加载指定列 | 否（新增能力） |
| `load_factor_values()` 默认行为 | 内部 json.load 全列再切片 | 内部委托 `load_full_data(factor_cols=...)` | 否（输出一致） |
| Decimal 列处理 | 调用方 `pd.to_numeric` | 加载时统一处理 | **轻微变更**：dtype 提前转 float64，与 factor_ic v3 对齐 |
| ijson ImportError 行为 | 不存在该路径 | 自动 fallback + warning | 否（无 ijson 时仍可运行） |
| date/asset 类型校验 | 抛 TypeError | 保留 | 否（不变） |

---

## 5. 测试方案

### 5.1 测试文件位置

`comprehensive_factor/test_cases/test_factor_loader_streaming.py`（新建）

遵循 AGENTS.md 规则 #7（测试位置 `<模块>/test_cases/`）+ 规则 #8（新建脚本必须配套测试）。

### 5.2 测试用例清单（4 个）

| # | 测试名 | 验证目标 | 数据来源 |
|---|--------|---------|---------|
| T1 | `test_full_load_consistent_with_json_load` | 新版 `load_full_data()` 与 `json.load` 输出一致（列集合 / 行数 / 每列值） | mini fixture（10 行） |
| T2 | `test_load_with_factor_cols_subset` | `load_full_data(factor_cols=[...])` 仅返回 date+asset+factor_cols+forward_return_* | mini fixture |
| T3 | `test_load_factor_values_delegates` | `load_factor_values` 输出含 date+asset+factor_cols 三类列且不含 forward_return_* | mini fixture |
| T4 | `test_ijson_unavailable_fallback` | mock `import ijson` 抛 ImportError，验证回退到 json.load 路径输出一致 | mini fixture |

### 5.3 共享 Fixture 设计

```python
@pytest.fixture
def mini_data_source(tmp_path):
    """构造 10 行 × 6 列的 mini factor_ic_data.json.gz。"""
    records = [
        {
            "date": f"2026-06-{day:02d}",
            "asset": "000001.SZ",
            "rsi_6": 50.0 + day,
            "volume_ratio_5": 1.0 + day * 0.1,
            "forward_return_1d": 0.001 * day,
            "forward_return_3d": 0.003 * day,
            "forward_return_5d": 0.005 * day,
        }
        for day in range(1, 11)
    ]
    payload = {"data": records, "metadata": {"source": "test"}}
    out = tmp_path / "mini_factor_ic_data.json.gz"
    with gzip.open(out, "wt", encoding="utf-8") as f:
        json.dump(payload, f)
    return out
```

**关键点**：
- 不依赖真实 389MB 数据源，CI 可秒级跑完
- 6 列覆盖 date/asset/2 个因子/3 个 forward_return，可同时验证全列与列子集模式

### 5.4 测试用例代码（T1 + T2）

```python
def test_full_load_consistent_with_json_load(mini_data_source):
    """T1: 新版流式与 json.load 行/列/值完全一致。"""
    # 新路径
    new_df = load_full_data(data_source=mini_data_source)

    # 参考路径（直接 json.load）
    with gzip.open(mini_data_source, "rt", encoding="utf-8") as f:
        payload = json.load(f)
    ref_df = pd.DataFrame(payload["data"])
    # 与新版一致：对数值列做 to_numeric
    for col in ref_df.columns:
        if col not in ("date", "asset"):
            ref_df[col] = pd.to_numeric(ref_df[col], errors="coerce")

    assert set(new_df.columns) == set(ref_df.columns)
    assert len(new_df) == len(ref_df) == 10
    for col in ref_df.columns:
        pd.testing.assert_series_equal(
            new_df[col].reset_index(drop=True),
            ref_df[col].reset_index(drop=True),
            check_names=False,
        )


def test_load_with_factor_cols_subset(mini_data_source):
    """T2: factor_cols 模式只加载指定列 + 5 个固定列。"""
    df = load_full_data(data_source=mini_data_source, factor_cols=["rsi_6"])

    # 必须包含: date, asset, rsi_6, forward_return_1d/3d/5d
    expected_cols = {"date", "asset", "rsi_6",
                     "forward_return_1d", "forward_return_3d", "forward_return_5d"}
    assert set(df.columns) == expected_cols
    # 不应包含未请求的因子列
    assert "volume_ratio_5" not in df.columns
    assert len(df) == 10
```

### 5.5 测试用例代码（T3 + T4）

```python
def test_load_factor_values_delegates(mini_data_source):
    """T3: load_factor_values 委托给 load_full_data，输出 date+asset+factor_cols。"""
    df = load_factor_values(
        factor_cols=["rsi_6", "volume_ratio_5"],
        data_source=mini_data_source,
    )

    # 仅含 date, asset, rsi_6, volume_ratio_5（不含 forward_return_*）
    assert set(df.columns) == {"date", "asset", "rsi_6", "volume_ratio_5"}
    assert "forward_return_1d" not in df.columns
    assert len(df) == 10
    # 数值列已 to_numeric
    assert df["rsi_6"].dtype == np.float64


def test_ijson_unavailable_fallback(mini_data_source, monkeypatch):
    """T4: ijson ImportError 时回退到 json.load 路径，输出仍一致。"""
    import builtins
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "ijson":
            raise ImportError("simulated ijson absence")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)

    # 仍能成功加载（走 json.load 分支 + warning）
    df = load_full_data(data_source=mini_data_source)
    assert len(df) == 10
    assert "rsi_6" in df.columns
    assert df["rsi_6"].dtype == np.float64
```

### 5.6 端到端验证（手动）

设计稿审过后、Execute 阶段还需补一次端到端冒烟（不进自动化测试套）：

```bash
# 真实数据 + 内存监控
python -c "
import tracemalloc
tracemalloc.start()
from comprehensive_factor.common.factor_loader import load_full_data
df = load_full_data()
peak = tracemalloc.get_traced_memory()[1] / 1024**2
print(f'rows={len(df)}, peak_mb={peak:.0f}')
assert peak < 1024, f'峰值超过 1GB: {peak}MB'
"

# 预期: rows=1490000+, peak_mb < 800
```

**通过门槛**：
- 峰值 < 1024 MB（设计目标 800 MB，留 25% 余量给 GC 抖动）
- 行数 ≥ 1,490,000（与旧路径一致）
- 无 OOM / 无 SIGKILL（exit code 0）

---

## 6. 风险与回滚

### 6.1 风险矩阵

| # | 风险 | 概率 | 影响 | 缓解措施 |
|---|------|------|------|---------|
| R1 | ijson 流式解析数值精度差异（如 Decimal → float） | 低 | 中 | 加载时统一 `pd.to_numeric(errors='coerce')`，与 factor_ic v3 对齐；测试 T1 验证逐列等值 |
| R2 | 列式累积时 `record.get(col)` 对缺失列返回 None，与旧 `pd.DataFrame(list[dict])` 行为不一致 | 低 | 低 | pandas 对 None 的处理与缺失键一致（都转 NaN）；T1 验证逐列等值 |
| R3 | factor_cols 模式遗漏关键列导致下游 KeyError | 中 | 中 | 强制追加 `date / asset / forward_return_1d/3d/5d` 5 列；测试 T2 验证 |
| R4 | ijson 解析速度比 json.load 慢，影响 pipeline 总耗时 | 中 | 低 | factor_ic v3 实测多约 5-8s（149 万行）；vs OOM 完全失败可接受；上线步骤记录耗时 |
| R5 | 真实数据峰值仍 > 800MB（估算偏差） | 低 | 高 | 设计目标留 25% 余量（< 1024MB 即通过）；fallback 阈值 1.5GB 仍远低于旧 4.5GB |
| R6 | `stock_selector.py:678` 隐式依赖 `load_factor_values` 返回不含 forward_return_* 列 | 低 | 中 | 委托后通过 `[["date","asset"]+factor_cols].copy()` 显式投影，行为不变；T3 验证 |
| R7 | 4 个 composite 脚本中有未识别的直接 `json.load` 调用绕过 factor_loader | 极低 | 中 | 已 grep 全项目，仅 composite_runner + stock_selector 两处入口 |

### 6.2 回滚方案

**触发条件**：上线后 2 小时内出现以下任一情况立即回滚：
- composite_*_weight_1d 任一脚本退出码非 0
- 端到端内存峰值 ≥ 1.5 GB
- pytest 失败
- factor_summary_report 与上一日数据偏差 > 1%（数值不一致风险）

**回滚步骤**（≤ 2 分钟）：

```bash
# 1. revert 提交
git log --oneline -5  # 找到本次 PR 的合并 commit
git revert <commit-sha> --no-edit
git push origin master

# 2. 验证回滚
python comprehensive_factor/composite_equal_weight_1d.py --quiet
echo "exit: $?"  # 期望 0

# 3. 通报
echo "[ROLLBACK] composite streaming load reverted at $(date)" >> rollback.log
```

### 6.3 灰度策略（可选，本次不采用）

由于改动收敛于公共加载函数 + 全测试覆盖 + 行为完全向后兼容，**不采用灰度**。直接全量上线。

如未来出现类似改动需要灰度，可考虑引入环境变量 `FACTOR_LOADER_MODE=streaming|legacy`，但本次不引入此复杂度。

---

## 7. 上线步骤

### 7.1 Execute 阶段任务拆解（superpowers-workflow bite-sized）

| 步骤 | 文件 | 工具 | 验证 | 预估耗时 |
|------|------|------|------|---------|
| S1 | `comprehensive_factor/common/factor_loader.py` | patch | `ruff check && ruff format` | 5 分钟 |
| S2 | `comprehensive_factor/test_cases/test_factor_loader_streaming.py` | write_file | `pytest -xvs comprehensive_factor/test_cases/test_factor_loader_streaming.py` | 5 分钟 |
| S3 | 端到端冒烟（§5.6） | terminal | tracemalloc 峰值 < 1024 MB | 2 分钟 |
| S4 | `comprehensive_factor/MODULE.md` 更新 M21 + L313 | patch | grep 验证 | 3 分钟 |
| S5 | `comprehensive_factor/docs/composite_runner_eliminate_duplicate_data_loading_design.md` 加 v2.23 附录 | patch | 人工审查 | 3 分钟 |
| S6 | 提交（含规范行号引用） | terminal git | `git log -1` | 2 分钟 |

**总耗时估**：~20 分钟。每步符合 superpowers-workflow "2-5 分钟 bite-sized" 原则。

### 7.2 上线时机

- 当前 OOM 是**确定性失败**（连续 6 次复现），需立即修复
- 无需等待维护窗口，因为：
  - 改动只影响离线 pipeline（非实时服务）
  - 行为完全向后兼容
  - 测试覆盖充分

### 7.3 上线 checklist（提交前模板，对应 AGENTS.md §5）

```
□ ruff check --fix .                                   [自动修复]
□ ruff format .                                        [格式化]
□ ruff check .                                         [无剩余 issue]
□ mypy comprehensive_factor/common/factor_loader.py    [类型检查]
□ pytest comprehensive_factor/test_cases/              [全测试通过]
□ python -c "tracemalloc + load_full_data" 峰值 < 1024MB [手动冒烟]
□ python comprehensive_factor/composite_equal_weight_1d.py --quiet 退出码 0  [E2E]
□ MODULE.md 版本号升级到 v2.23                          [文档同步]
□ git commit -m "..."（引用 AGENTS.md 规则 #1, PROJECT.md Design-First）  [取证]
```

### 7.4 提交消息模板

```
refactor(comprehensive_factor): factor_loader 改用 ijson 流式加载，根治 OOM

修复 composite_*_weight_1d.py 因 json.load 一次性加载 4.5GB 触发 OOM Kill
（exit code -9）的问题。复用 factor_ic v3 验证过的列式累积模板。

变更:
- factor_loader.load_full_data: 改 ijson 流式 + dict[col, list] 累积
- factor_loader.load_full_data: 新增可选 factor_cols 列过滤参数
- factor_loader.load_factor_values: 委托给 load_full_data（消除双份维护）
- 新增 test_factor_loader_streaming.py 4 个测试
- MODULE.md 升级到 v2.23

效果:
- 峰值内存 4.5GB → ~760MB（降 83%）
- stock_selector 调用峰值 → ~175MB（降 96%）
- ImportError 时 fallback json.load（保留向后兼容）

遵循:
- AGENTS.md 规则 #1（公共模块复用，不动 4 个 composite 脚本）
- AGENTS.md 规则 #7-#8（测试位置 + 配套测试）
- PROJECT.md Design-First（先写 designs/composite_streaming_load_design.md）
```

---

## 8. 验收标准

### 8.1 功能验收（必须全部通过）

| # | 验收项 | 验证方法 | 通过标准 |
|---|--------|---------|---------|
| F1 | composite_equal_weight_1d.py 不再 OOM | `python comprehensive_factor/composite_equal_weight_1d.py --quiet; echo $?` | 退出码 = 0 |
| F2 | 4 个 composite 权重脚本全部可运行 | 依次执行 4 个脚本 | 每个退出码 = 0 |
| F3 | stock_selector.py 输出与改动前一致 | diff 改动前后 `comprehensive_factor/result/selected_stocks_*.json` | 仅时间戳差异 |
| F4 | factor_summary_report 数值无变化 | diff 改动前后 `summary/result/factor_summary_report_*.txt` | 数值字段完全一致 |
| F5 | 全测试通过 | `pytest comprehensive_factor/test_cases/ -x` | 0 failed, 0 errored |

### 8.2 性能验收（必须全部通过）

| # | 指标 | 验证方法 | 通过标准 |
|---|------|---------|---------|
| P1 | load_full_data 峰值内存 | tracemalloc | < 1024 MB（目标 800 MB） |
| P2 | load_factor_values 峰值内存（列子集） | tracemalloc + 5 因子 | < 300 MB |
| P3 | composite_equal_weight_1d 端到端 RSS 峰值 | `/usr/bin/time -v` | < 1.5 GB |
| P4 | 加载耗时（149 万行） | logger 时间戳 | < 30 秒（factor_ic v3 实测 ~25s） |
| P5 | 总 pipeline 耗时回归 | 改动前后对比 | 增长 < 15% |

### 8.3 文档验收（必须全部通过）

| # | 文档 | 验证 |
|---|------|------|
| D1 | `comprehensive_factor/MODULE.md` 版本升至 v2.23 | grep `^版本.*v2.23` |
| D2 | M21 章节 `gzip.open + json.load` 注释改为 `ijson 流式` | grep 关键词替换 |
| D3 | L313 表格同步更新数据加载方式 | 人工审查 |
| D4 | `composite_runner_eliminate_duplicate_data_loading_design.md` 加 v2.23 附录 | grep `v2.23` |
| D5 | git commit 消息引用规范行号 | git log --format=%B |

### 8.4 综合通过条件

- F1-F5 + P1-P5 + D1-D5 **全部通过**才算 Execute 完成
- 任一项不通过 → 进入 Debug 阶段（加载 systematic-debugging skill）
- Debug 失败 3 次 → 触发 §6.2 回滚

---

## 9. 关联规范

### 9.1 项目级规范引用（AGENTS.md / PROJECT.md）

| 规范 | 位置 | 在本设计中的应用 |
|------|------|-----------------|
| AGENTS.md 规则 #1（公共模块复用） | AGENTS.md §2 | 只改 `comprehensive_factor/common/factor_loader.py`，不动 4 个 composite 脚本 |
| AGENTS.md 规则 #2（输出位置） | AGENTS.md §2 | 不涉及输出路径变更 |
| AGENTS.md 规则 #7（测试位置） | AGENTS.md §2 | 测试放在 `comprehensive_factor/test_cases/test_factor_loader_streaming.py` |
| AGENTS.md 规则 #8（配套文件） | AGENTS.md §2 | 新建 `factor_loader.py` 改动 → 配套测试 + flow doc 更新 |
| AGENTS.md 规则 #9（日志格式） | AGENTS.md §2 | 使用 `comprehensive_factor.common.logger_config.get_logger` |
| AGENTS.md 规则 #10（异常链） | AGENTS.md §2 | 保留 `raise ... from e` 模式（FileNotFoundError / KeyError / TypeError） |
| AGENTS.md 规则 #11（路径导入） | AGENTS.md §2 | `DEFAULT_DATA_SOURCE` 从 `paths.py` 导入，不用字面量 |
| AGENTS.md 规则 #12（Design-First） | AGENTS.md §2 | 本文件即 design.md，2+ 文件改动先提交设计稿审过 |
| PROJECT.md 跨模块数据契约 | AGENTS.md §1 | 数据源仍为 `data_fetchers/result/factor_ic_data.json.gz`，不变 |

### 9.2 模块级规范引用（comprehensive_factor/MODULE.md）

| 规范 | 章节 | 在本设计中的应用 |
|------|------|-----------------|
| M21 数据来源章节 | L860-900 | 第 869 行注释从 "gzip.open + json.load" → "ijson 流式 + 列式累积" |
| L313 表格 | L313 | 同样替换 "gzip.open + json.load" 描述 |
| 公共模块 factor_loader | M19/M20 章节 | `load_full_data` 签名扩展（向后兼容） |

### 9.3 流程级规范引用

| 文档 | 在本设计中的应用 |
|------|-----------------|
| `comprehensive_factor/docs/composite_runner_eliminate_duplicate_data_loading_design.md` | v2.10 设计文档（消除重复数据加载）→ 新增 v2.23 流式加载附录，记录本次升级演进 |
| `factor_ic/docs/factor_ic_data_loader_v3_streaming_design.md`（如存在） | 参考 factor_ic v3 的实施记录（2026-06-13 上线） |

### 9.4 已加载的 skill 引用

| Skill | 在本设计中的应用 |
|-------|-----------------|
| `superpowers-workflow` | 4 阶段流程（Plan→Execute→Review→Debug）；§7.1 任务粒度遵循 bite-sized（2-5 分钟） |
| `superpowers-workflow:references/pipeline-execution-troubleshooting-pattern.md` | 排查思路：先加载 skill + 查规范，再 improvise（用户偏好） |
| `factor-development`（备用） | 因子开发流程，本次未涉及新增因子 |

### 9.5 未来演进（预留）

如未来需进一步降低内存（如机器降级到 2GB RAM）：

1. **chunked DataFrame 构建**：每 N 行构建一次 DataFrame 后立即下游消费（streaming pipeline）
2. **Parquet 替换 JSON.gz**：列式存储原生支持列子集加载，无需 ijson
3. **DuckDB 直接查询 Parquet**：零拷贝，进一步降内存

但当前 760MB 已远低于机器内存余量（~3.9GB free），上述优化非必要，**不在本次范围内**。

---

## 10. 设计稿状态

| 字段 | 值 |
|------|-----|
| 状态 | **待审核** |
| 提交日期 | 2026-06-14 |
| 审核者 | 用户 |
| 审核通过后下一步 | 进入 Execute 阶段（按 §7.1 步骤 S1-S6 执行） |

**审核要点**：
1. §2 函数签名是否符合最小变更原则？
2. §3 影响范围是否完整？是否还有遗漏的调用方？
3. §5 测试覆盖是否充分？
4. §6 风险与回滚是否合理？
5. §8 验收标准的阈值是否合理？
6. §9 规范引用是否完整？

**通过即可进入 Execute。**
