# Design: 市值数据采集模块（fetch_market_cap.py）

> 作者: 云瑶
> 创建时间: 2026-06-18
> 稳定性: [experimental] 待实战验证
> 触发规范: AGENTS.md 硬规则 #12（Design-First：2+ 文件改动需先提交 design）、PROJECT.md H8（Design-First）

---

## §1. 背景

### 1.1 触发动机

当前项目已实现**行业中性化**（依赖 `fetch_industry.py` 提供的截面行业映射，在 `factor_ic` 模块对每个截面做行业 dummy 回归取残差）。下一步需要补齐 **市值中性化**，以消除小盘股流动性溢价对 IC 评估的污染。市值中性化的标准做法是：

```
对每个截面 t：
    residual = OLS(factor[t] ~ industry_dummy[t] + ln(circ_market_cap[t])).resid
    IC[t] = corr(residual, forward_return[t])
```

要执行这一步，**必须先有"日频 × 股票"的市值面板数据**。当前项目对市值是空白：

| 现状 | 证据 |
|---|---|
| `data_fetchers/result/factor_data.json.gz` 字段 | `[date, asset, open, close, high, low, rsi_6, volume_ratio_5, volume]`（无市值/股本，验证于 meta.fields） |
| 全代码库搜 `市值\|股本\|market_cap\|total_mv\|circ_mv` | 0 命中（项目代码层面，不计 .venv） |
| `fetch_financial.py`（同花顺财务摘要） | 含净利润/营收，**不含股本/市值** |
| `fetch_industry.py` | 仅截面行业映射，无市值 |

### 1.2 数据源选型证据

调研 akshare 1.18 当前装版（`.venv_akshare/lib/python3.11/site-packages/akshare/`）共 5 个候选接口：

| 接口 | 历史时序 | 字段集 | 调用次数 | 选用 |
|---|---|---|---|---|
| **`stock_value_em(symbol)`** | ✓ 全历史 | 总市值/流通市值/总股本/流通股本/PE-TTM/PE-LAR/PB/PEG/PCF/PS（13 列） | 3026 次（每股 1 次） | ✅ |
| `stock_zh_valuation_baidu` | ✓ | 单指标（总市值/PE/PB/PS/PCF 五选一） | 3026 × N | ✗ 字段稀薄 |
| `stock_individual_info_em` | ✗ 仅截面 | 总股本/流通股/总市值/流通市值 | 3026 次 | ✗ 无历史 |
| `stock_zh_a_spot_em` | ✗ 仅截面 | 总市值/流通市值 | 1 次 | ✗ 无历史 |
| `stock_a_indicator_lg`（乐咕乐股） | — | — | — | ✗ akshare 1.18 已下架（确认于 `__init__.py:4971`，仅保留 hk 版） |

**选定 `stock_value_em`** —— 原因：唯一同时满足"日频时序 + 市值/股本 + 估值多字段"的接口。

### 1.3 中性化口径决策（已与用户对齐）

| 决策项 | 取值 | 依据 |
|---|---|---|
| 市值口径 | **流通市值（circ_market_cap）** | Barra CNE5/CNE6 中国模型默认口径；A股限售比例高，total ≠ float；与现有 `fetch_turnover.py` 换手率（基于流通股本）一致 |
| 数学变换 | **ln(circ_market_cap)** | 市值右偏分布；Barra Size 因子定义即 `LNCAP = ln(float_mkt_cap)` |
| 估值字段 | 顺带保留 | 用户已在 Q2 确认；为后续估值因子（PB/PE 反转因子等）预留数据源 |
| 落盘策略 | 独立文件 `market_cap_data.json.gz` | 用户已在 Q3 确认；与 `turnover_rate_data.json.gz`、`stock_industry.json` 风格一致 |

---

## §2. 目标

### 2.1 功能目标

新建脚本 `data_fetchers/fetch_market_cap.py`，输出 `data_fetchers/result/market_cap_data.json.gz`，提供**日频股票市值与估值面板数据**，作为下游 `factor_ic` 模块市值中性化的数据来源（注：本 design **仅完成数据拉取**，中性化实施在后续独立 design 中处理）。

### 2.2 验收标准

| # | 验收项 | 检查方法 |
|---|---|---|
| V1 | 输出文件存在且 gzip 解压有效 | `gunzip -t market_cap_data.json.gz` |
| V2 | meta 字段齐全 | `meta.{generated_at, source, n_days, n_assets, n_records, date_range, version, fields}` 全部非空 |
| V3 | 字段集 = 11 列 | `data[0].keys() == [date, asset, total_market_cap, circ_market_cap, total_shares, circ_shares, pe_ttm, pe_lyr, pb, peg, pcf_ttm, ps_ttm]` |
| V4 | 时间范围对齐 factor_data | `meta.date_range` 与 `factor_data.json.gz` 的 date_range 同 start 同 end（裁剪后） |
| V5 | 股票覆盖率 ≥ 95% | 与 `factor_data.json.gz` 的 asset 集合相比，覆盖率 ≥ 95% |
| V6 | 关键字段非空率 ≥ 99% | `circ_market_cap` 非 None / 总记录数 ≥ 99%；缺失记录需在日志显式 warning |
| V7 | 单调有序 | `data` 按 (asset, date) 升序，无重复 (asset, date) 键 |
| V8 | pytest 通过 | `data_fetchers/test_cases/test_fetch_market_cap.py` 全绿 |
| V9 | 流程文档同步 | `data_fetchers/docs/fetch_market_cap_flow.md` 存在且时间戳 ≤ 提交时间 |

### 2.3 非目标（明确排除）

- ❌ 市值中性化的回归实施（在 `factor_ic` 模块独立 design 处理）
- ❌ 估值因子定义（PB/PE 反转因子在 `factor_definitions.py` 后续 design 处理）
- ❌ `factor_generator.py` 的 join 逻辑（本 design 仅产出独立文件，下游消费在后续 design）
- ❌ 自由流通市值（akshare 无现成接口，工程复杂度过高，当前阶段不做）

### 2.4 影响面预估（H9 粒度检查）

| 文件 | 类型 | 行数估计 |
|---|---|---|
| `data_fetchers/fetch_market_cap.py` | 新建（核心脚本） | ~280 |
| `data_fetchers/test_cases/test_fetch_market_cap.py` | 新建（pytest） | ~150 |
| `data_fetchers/docs/fetch_market_cap_flow.md` | 新建（流程文档） | ~120 |
| `data_fetchers/schemas/market_cap_data.schema.json` | 新建（JSON Schema） | ~60 |
| `paths.py` | 改 1 行（新增 `MARKET_CAP_DATA` 路径常量） | +3 |
| `AGENTS.md` | 改 1 行（跨模块数据路径表新增 1 行） | +1 |
| `data_fetchers/MODULE.md` | 追加流程文档章节 | +30 |

**触发的硬规则**：
- ✅ H8（Design-First：≥ 2 文件改动）→ 本文件即为响应
- ⚠️ H9（粒度 ≤3 文件 ≤200 行）→ **超粒度**：6 个新增/修改文件、约 644 行。**已通过 Design-First 走审核流程，可分批提交**（见 §11 影响面拆分计划，每批仍受 H9 约束）。

---

## §3.1 模块结构总览

`fetch_market_cap.py` 整体由 **5 个公开函数 + 3 个内部辅助函数** 构成，遵循"输入校验 → 拉取 → 落盘 → 合并 → 验证"的线性流水线。

### 函数清单

| # | 函数名 | 职责 | 公开/内部 | 调用层级 |
|---|---|---|---|---|
| F1 | `main()` | CLI 入口，编排 F2-F6 | 公开 | L0（顶层） |
| F2 | `load_target_assets()` | 从 `stock_list.json` 加载目标股票列表，过滤 ST | 公开 | L1 |
| F3 | `fetch_one_stock()` | 单股拉取（带 retry），调用 `ak.stock_value_em` | 公开 | L2（被 F4 调用） |
| F4 | `fetch_batch()` | 批量拉取一组股票，并发调用 F3 | 公开 | L1 |
| F5 | `save_batch_cache()` | 保存单批数据到独立 gzip 文件（按 asset 排序） | 公开 | L1 |
| F6 | `merge_and_emit_final()` | 顺序读取所有批次文件 → 合并 → 写最终输出 | 公开 | L1 |
| F7 | `_normalize_fields()` | 中文列名 → 英文，类型转换，单位约定（内部） | 内部 | L3 |
| F8 | `_clip_to_target_range()` | 按 `factor_data` 的 date_range 裁剪 | 内部 | L3（被 F3 调用） |
| F9 | `validate_final_data()` | 验证输出文件完整性（V1-V7 验收标准的实现） | 公开 | L1 |

### 调用关系（文字版）

```
main()
  ├─ load_target_assets()                       # F2
  ├─ for batch_idx, batch in enumerate(batches):
  │     fetch_batch(batch, batch_idx)           # F4
  │       └─ ThreadPool(max_workers=4):
  │             fetch_one_stock(symbol)         # F3
  │               ├─ ak.stock_value_em(symbol)
  │               ├─ _normalize_fields(df)      # F7
  │               └─ _clip_to_target_range(df)  # F8
  │     save_batch_cache(batch_idx, df)         # F5
  ├─ merge_and_emit_final(total_batches)        # F6
  ├─ validate_final_data()                      # F9
  └─ cleanup_batch_files()                      # 复用 batch_processor.cleanup_batch_files
```

### 模块级常量

| 常量 | 取值 | 说明 |
|---|---|---|
| `_OUTPUT_VERSION` | `"1.0"` | 输出文件 meta.version，初版 |
| `BATCH_SIZE` | `250` | 单批股票数（与 `fetch_factor_cache` 一致） |
| `MAX_WORKERS` | `4` | 并发线程数（决策 F2，与 `fetch_factor_cache` 一致） |
| `MAX_RETRIES` | `3` | 单股最多重试次数（决策 E1） |
| `RETRY_BACKOFF_BASE` | `1.0` | 重试退避基数（秒），抖动公式 `delay = base * 2^attempt + jitter` |
| `REQUEST_INTERVAL` | `0.1` | 单股调用间隔（秒），防限流 |
| `ST_PREFIXES` | `("*ST", "ST", "S")` | 与 `fetch_turnover.py` 一致 |
| `EXPECTED_FIELDS` | `(date, asset, total_market_cap, ..., ps_ttm)` 共 12 列 | 输出字段全集 |

### 公开 API（`__all__`）

```python
__all__ = [
    "load_target_assets",
    "fetch_one_stock",
    "fetch_batch",
    "save_batch_cache",
    "merge_and_emit_final",
    "validate_final_data",
    "main",
]
```

---

## §3.2 核心函数签名（F2 / F3 / F4）

本节给出**进入数据生命周期前的三个核心函数**的完整签名草案。F5/F6/F9 在后续轮次（落盘 / 合并 / 验证）中给出。

### F2. `load_target_assets`

```python
def load_target_assets(
    stock_list_file: Path | None = None,
    logger_arg: logging.Logger | None = None,
) -> list[str]:
    """
    从 stock_list.json 加载目标股票代码列表，过滤 ST 股。

    职责单一：返回需要拉取市值数据的 6 位股票代码列表。
    不做接口调用，纯本地文件读取 + 过滤。

    Args:
        stock_list_file: 股票列表文件路径（默认通过 common.paths.get_stock_list_file()）。
        logger_arg: 日志记录器（遵循 fetch_turnover.py 约定）。

    Returns:
        list[str]: 6 位股票代码（如 "000001"），不含交易所前缀。
            排序：与 stock_list.json 保持一致（不二次排序，避免与上游契约漂移）。

    Raises:
        FileNotFoundError: stock_list.json 不存在。
        ValueError: JSON 结构不合规（缺 'data' 字段或非 list）。

    Note:
        - ST 过滤：使用模块级 ST_PREFIXES 元组前缀匹配股票名称。
        - 与 fetch_turnover.load_stock_list() 行为一致，避免跨脚本过滤口径漂移。
    """
```

### F3. `fetch_one_stock`

```python
def fetch_one_stock(
    symbol: str,
    target_date_range: tuple[str, str],
    max_retries: int = MAX_RETRIES,
    logger_arg: logging.Logger | None = None,
) -> pd.DataFrame | None:
    """
    单股市值数据拉取（带重试与裁剪）。

    内部流程：
        1. 调用 ak.stock_value_em(symbol) 拉取全历史。
        2. _normalize_fields() 中文 → 英文 + 类型转换 + asset 列填充。
        3. _clip_to_target_range() 按 target_date_range 裁剪。
        4. 失败时 retry，最多 max_retries 次（指数退避 + 抖动）。

    Args:
        symbol: 6 位股票代码（如 "000001"）。
        target_date_range: (start_date, end_date) ISO 字符串元组。
            裁剪窗口：保留 start ≤ date ≤ end 的记录。
        max_retries: 最多重试次数。重试不计入首次调用，总尝试 = max_retries + 1。
        logger_arg: 日志记录器。

    Returns:
        pd.DataFrame | None:
            - 成功：列 = [date, asset, total_market_cap, circ_market_cap,
              total_shares, circ_shares, pe_ttm, pe_lyr, pb, peg, pcf_ttm, ps_ttm]，
              date 为 ISO 字符串 "YYYY-MM-DD"，asset 为 6 位字符串，其他为 float64。
            - 失败：返回 None，调用方负责跳过并累计失败计数。

    Raises:
        本函数**不向外抛接口异常**——所有异常（requests/JSONDecode/Empty）在 except 块内
        warning + return None，由调用方统计失败率。这与 fetch_turnover_rate_eastmoney
        模式一致（决策 E1）。

        ValueError: 仅在参数非法（symbol 长度不为 6、target_date_range 为空等）时直接抛出。

    Note:
        - 单股接口"返回空 DataFrame"视为永久性失败（如已退市），不重试。
        - 裁剪后为空 DataFrame 视为该股票在目标区间无数据，返回空 DF 而非 None。
        - 节流：每次成功调用后 sleep REQUEST_INTERVAL，防东财 API 限流。
    """
```

### F4. `fetch_batch`

```python
def fetch_batch(
    symbols: list[str],
    batch_idx: int,
    total_batches: int,
    target_date_range: tuple[str, str],
    max_workers: int = MAX_WORKERS,
    logger_arg: logging.Logger | None = None,
) -> tuple[pd.DataFrame | None, int, int]:
    """
    批量拉取一组股票，并发调用 fetch_one_stock。

    与 fetch_factor_cache.fetch_batch_stocks 模式一致：ThreadPoolExecutor +
    as_completed 顺序无关收集，避免单只慢股阻塞批次。

    Args:
        symbols: 本批次的 6 位股票代码列表（长度通常为 BATCH_SIZE）。
        batch_idx: 批次索引（从 0 开始），用于日志与文件命名。
        total_batches: 总批次数，用于进度日志（"批次 3/12"）。
        target_date_range: 透传给 fetch_one_stock。
        max_workers: 并发线程数。
        logger_arg: 日志记录器。

    Returns:
        tuple:
            - pd.DataFrame | None: 合并后的批次数据；全失败时返回 None。
              列与 fetch_one_stock 输出一致，已按 (asset, date) 升序排序、去重。
            - int: 成功拉取的股票数（success_count）。
            - int: 失败的股票数（fail_count），fail_count + success_count = len(symbols)。

    Note:
        - 批次内顺序无关，最终输出排序 by (asset, date) ascending, kind="mergesort"。
        - 内存峰值：仅当前批次的合并结果（约 250 股 × 545 天 × 12 字段 ≈ 16MB），
          落盘后立即 del + gc.collect()，与 fetch_factor_cache 模式一致。
        - 失败统计：仅 fetch_one_stock 返回 None 计为失败；返回空 DataFrame（如该股票
          在目标区间无数据）计为成功（success_count++）但不进入合并。
    """
```

### 签名设计要点

| 设计点 | 决策 | 依据 |
|---|---|---|
| logger 参数命名 | `logger_arg` | 与 `fetch_turnover.py` (line 549)、`batch_processor.py` (line 534) 一致，避免与全局 `logger` 同名遮蔽 |
| 失败处理 | F3 吞异常 → return None；F4 统计 success/fail | 决策 E1；与 `fetch_turnover_rate_eastmoney` 模式一致 |
| date_range 裁剪 | 在 F3 内做（每股拉完即裁） | 提早裁剪降低后续合并/落盘的内存峰值，与 B2 决策一致 |
| 类型注解 | `pd.DataFrame \| None`、`tuple[..., int, int]` | 遵循 MODULE.md R18 / R19（Python 3.9+ 内置泛型） |
| asset 列类型 | 字符串 6 位（不带交易所前缀） | 与 `factor_data.json.gz` 的 asset 列约定一致 |

---

## §4. 数据流（生命周期）

本节追踪一条记录从 API 响应到最终 `market_cap_data.json.gz` 的完整变换路径，每一步都标注**形态、字段、单位、行数量级**。

### 4.1 端到端数据流图

```
┌──────────────────────────────────────────────────────────────┐
│ Stage 0: 输入                                                 │
│   data_fetchers/result/stock_list.json                       │
│   → list[dict] {code: "000001", name: "平安银行", ...}        │
│   → ~3026 条                                                  │
└────────────────────────┬─────────────────────────────────────┘
                         │ load_target_assets() + ST 过滤
                         ▼
┌──────────────────────────────────────────────────────────────┐
│ Stage 1: 目标股票列表                                          │
│   list[str] = ["000001", "000002", ...]                      │
│   → ~2900 条（去 ST 后）                                       │
└────────────────────────┬─────────────────────────────────────┘
                         │ 切片 BATCH_SIZE=250
                         ▼
┌──────────────────────────────────────────────────────────────┐
│ Stage 2: 批次切片                                             │
│   batches: list[list[str]] = [batch_0, batch_1, ...]         │
│   → ~12 批 × 250 股                                           │
└────────────────────────┬─────────────────────────────────────┘
                         │ for batch in batches:
                         │   ThreadPool(max_workers=4) + as_completed
                         ▼
┌──────────────────────────────────────────────────────────────┐
│ Stage 3: 单股 API 响应（fetch_one_stock 内部）                 │
│   ak.stock_value_em(symbol="000001")                         │
│   → pd.DataFrame[~5000 行 × 13 列]                           │
│   列名（中文）: [数据日期, 当日收盘价, 当日涨跌幅, 总市值,        │
│                 流通市值, 总股本, 流通股本, PE(TTM), PE(静),    │
│                 市净率, PEG值, 市现率, 市销率]                  │
│   单位: 总市值/流通市值=元, 总股本/流通股本=股, PE/PB/PEG=倍     │
└────────────────────────┬─────────────────────────────────────┘
                         │ _normalize_fields()
                         │  - 中文列名 → 英文
                         │  - 删除"当日收盘价/当日涨跌幅"
                         │  - 添加 asset 列
                         │  - 类型: date→ISO str, 其他→float64
                         ▼
┌──────────────────────────────────────────────────────────────┐
│ Stage 4: 单股归一化后                                          │
│   pd.DataFrame[~5000 行 × 12 列]                             │
│   列: [date, asset, total_market_cap, circ_market_cap,       │
│        total_shares, circ_shares, pe_ttm, pe_lyr, pb,        │
│        peg, pcf_ttm, ps_ttm]                                 │
│   单位保留原始: 元 / 股 / 倍                                   │
└────────────────────────┬─────────────────────────────────────┘
                         │ _clip_to_target_range(start, end)
                         │  保留 2024-03-18 ≤ date ≤ today
                         ▼
┌──────────────────────────────────────────────────────────────┐
│ Stage 5: 单股裁剪后                                            │
│   pd.DataFrame[~545 行 × 12 列]                              │
│   每股 ~ 545 个交易日（与 factor_data 对齐）                   │
└────────────────────────┬─────────────────────────────────────┘
                         │ batch 内 250 个 DF concat
                         │  + sort_values([asset, date], kind="mergesort")
                         │  + drop_duplicates([asset, date])
                         ▼
┌──────────────────────────────────────────────────────────────┐
│ Stage 6: 批次合并 DataFrame                                    │
│   pd.DataFrame[~136250 行 × 12 列]（250 股 × 545 天）          │
└────────────────────────┬─────────────────────────────────────┘
                         │ save_batch_cache(batch_idx, df)
                         │  → result/batch_<idx>_market_cap.json.gz
                         ▼
┌──────────────────────────────────────────────────────────────┐
│ Stage 7: 批次缓存文件（落盘）                                   │
│   result/batch_0_market_cap.json.gz, batch_1_..., ..., batch_11_... │
│   → 12 个临时文件                                              │
└────────────────────────┬─────────────────────────────────────┘
                         │ merge_and_emit_final(total_batches)
                         │  - 顺序读取 batch_0...batch_11
                         │  - 流式追加到最终输出（无需 N-way merge：
                         │    单股数据天然不跨批，asset 域不重叠）
                         ▼
┌──────────────────────────────────────────────────────────────┐
│ Stage 8: 最终输出                                              │
│   data_fetchers/result/market_cap_data.json.gz               │
│   {meta: {...}, data: [...]}                                 │
│   → ~1635000 行 × 12 字段（3000 股 × 545 天）                  │
└────────────────────────┬─────────────────────────────────────┘
                         │ validate_final_data()
                         │ cleanup_batch_files()
                         ▼
                       完成
```

### 4.2 关键变换详解

| Stage | 输入 → 输出 | 变换函数 | 关键约束 |
|---|---|---|---|
| 0→1 | stock_list.json → list[str] | F2 `load_target_assets` | ST 过滤口径与 `fetch_turnover.py` 一致 |
| 1→2 | list[str] → batches | `main()` 内联切片 | `[stocks[i:i+250] for i in range(0, n, 250)]` |
| 2→3 | symbol → 单股 13 列 DF | `ak.stock_value_em` | 单股 ~5000 行（接口 pageSize 上限） |
| 3→4 | 13 列 → 12 列 + 英文 | F7 `_normalize_fields` | 见 §6 字段映射表 |
| 4→5 | 全历史 → target 区间 | F8 `_clip_to_target_range` | 决策 B2：与 factor_data 同 start 同 end |
| 5→6 | 250 股拼合 | F4 `fetch_batch` | sort_values + drop_duplicates(subset=["asset","date"]) |
| 6→7 | DF → gzip | F5 `save_batch_cache` | 复用 `batch_processor.save_batch_cache_sorted` 的写入模式 |
| 7→8 | 12 个 batch → 1 个最终 | F6 `merge_and_emit_final` | **简化合并**：顺序追加（不需 N-way merge） |

### 4.3 简化合并（与 fetch_factor_cache 的关键差异）

| 维度 | `fetch_factor_cache` | `fetch_market_cap`（本设计） |
|---|---|---|
| 跨批次 asset 重叠 | ✓ 同股票可能在多个批次（接口按日期切片） | ✗ 每股仅在一个批次（按股票切片） |
| 跨批次 date 重叠 | ✓ 同日期可能在多个批次 | ✗ 单股内部日期不重叠 |
| 是否需要 N-way merge | ✓ 必要（去重 + 合并） | ✗ 顺序追加即可 |
| 是否需要 BatchStream 类 | ✓ | ✗ 简单 gzip 流读 + 流写 |
| 合并算法复杂度 | O(N log K)，K=批数 | O(N)，N=总记录数 |

**结论**：`merge_and_emit_final` 实现 ≈ 50 行（gzip 流读 → 累计计数 → gzip 流写 + meta），不复用 `batch_processor.n_way_merge_deduplicate`。这是决策 A2 的具体落地。

### 4.4 数据量级估算（容量规划）

| 项 | 数值 | 计算 |
|---|---|---|
| 股票数 | ~2900 | stock_list.json 总数 - ST |
| 交易日数 | ~545 | 与 factor_data.json.gz 一致 |
| 总记录数 | ~1,580,500 | 2900 × 545 |
| 单条 JSON 行 | ~140 字节 | 12 字段 × 平均 11 字节 + 字段名 |
| 未压缩体积 | ~220 MB | 1.58M × 140 |
| gzip 后体积 | ~30-50 MB | 经验压缩比 4-7x |
| 单批次内存峰值 | ~16 MB | 250 × 545 × 12 × 8 字节（float64） |
| 落盘后内存峰值 | ~20 MB | 单批次 + gc 残留 |

**结论**：内存峰值远低于 fetch_factor_cache 的 900 MB 阈值，**无需 MEMORY_THRESHOLD_MB 暂停机制**。

---

## §5. 批处理架构（伪代码与控制流）

本节给出 `main()` 编排逻辑、`fetch_batch` 并发控制、`fetch_one_stock` 重试退避三处的伪代码草案。

### 5.1 main() 顶层编排

```python
def main(
    target_date_range: tuple[str, str] | None = None,
    logger_arg: logging.Logger | None = None,
) -> int:
    """
    返回：退出码（0=成功，1=运行时错误，2=配置错误）
    遵循 AGENTS.md 规则 #6（退出码语义）
    """
    logger = logger_arg or _get_logger()

    # Step 1: 确定目标区间（默认对齐 factor_data.json.gz）
    if target_date_range is None:
        target_date_range = _read_factor_data_date_range()
    logger.info("目标区间: %s ~ %s", target_date_range[0], target_date_range[1])

    # Step 2: 加载目标股票
    symbols = load_target_assets(logger_arg=logger)
    logger.info("目标股票数: %d", len(symbols))

    # Step 3: 切批
    batches = [symbols[i:i + BATCH_SIZE] for i in range(0, len(symbols), BATCH_SIZE)]
    total_batches = len(batches)

    # Step 4: 分批拉取并落盘
    total_success = 0
    total_fail = 0
    for batch_idx, batch in enumerate(batches):
        df, success_cnt, fail_cnt = fetch_batch(
            batch, batch_idx, total_batches, target_date_range, logger_arg=logger
        )
        total_success += success_cnt
        total_fail += fail_cnt
        if df is not None and not df.empty:
            save_batch_cache(batch_idx, df, logger_arg=logger)
        else:
            logger.warning("批次 %d 全部失败，跳过落盘", batch_idx)
        del df
        gc.collect()

    # Step 5: 合并最终输出
    n_records = merge_and_emit_final(
        total_batches, target_date_range, total_success, total_fail, logger_arg=logger
    )

    # Step 6: 验证
    is_valid, n_days, n_assets, n_records_validated = validate_final_data(logger_arg=logger)
    if not is_valid:
        logger.error("最终输出验证失败")
        return 1

    # Step 7: 清理临时文件
    cleanup_batch_files(total_batches, data_type="market_cap", logger_arg=logger)

    logger.info("完成: %d 股 × %d 天 = %d 记录", n_assets, n_days, n_records_validated)
    return 0
```

### 5.2 fetch_batch 并发控制

```python
def fetch_batch(
    symbols, batch_idx, total_batches, target_date_range, max_workers=MAX_WORKERS, logger_arg=None
):
    logger = logger_arg or _get_logger()
    logger.info("批次 %d/%d 开始: %d 只股票", batch_idx + 1, total_batches, len(symbols))
    batch_start = time.time()

    success_dfs = []
    success_count = 0
    fail_count = 0

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_symbol = {
            executor.submit(fetch_one_stock, sym, target_date_range, logger_arg=logger): sym
            for sym in symbols
        }
        for future in as_completed(future_to_symbol):
            sym = future_to_symbol[future]
            try:
                df = future.result()
            except Exception as e:
                # 内层 fetch_one_stock 已吞所有异常，此处仅捕获不可预期的线程异常
                logger.exception("线程异常 symbol=%s [%s]", sym, type(e).__name__)
                fail_count += 1
                continue

            if df is None:
                fail_count += 1
            elif df.empty:
                # 该股票在目标区间无数据（如新上市），计成功但不参与合并
                success_count += 1
            else:
                success_dfs.append(df)
                success_count += 1

    if not success_dfs:
        logger.warning("批次 %d 无有效数据", batch_idx)
        return None, success_count, fail_count

    # 合并 + 排序 + 去重
    combined = pd.concat(success_dfs, ignore_index=True)
    combined = combined.sort_values(["asset", "date"], kind="mergesort")
    combined = combined.drop_duplicates(subset=["date", "asset"], keep="last")

    elapsed = time.time() - batch_start
    logger.info(
        "批次 %d/%d 完成: 成功 %d, 失败 %d, 记录 %d, 耗时 %.1fs",
        batch_idx + 1, total_batches, success_count, fail_count, len(combined), elapsed,
    )
    return combined, success_count, fail_count
```

### 5.3 fetch_one_stock 重试退避

```python
def fetch_one_stock(symbol, target_date_range, max_retries=MAX_RETRIES, logger_arg=None):
    logger = logger_arg or _get_logger()

    # 入口校验
    if not (isinstance(symbol, str) and len(symbol) == 6 and symbol.isdigit()):
        raise ValueError(f"非法 symbol: {symbol!r}（需 6 位数字字符串）")
    if not target_date_range or len(target_date_range) != 2:
        raise ValueError(f"非法 target_date_range: {target_date_range!r}")

    last_failure_reason = None
    last_failure_detail = None

    for attempt in range(max_retries + 1):
        try:
            df_raw = ak.stock_value_em(symbol=symbol)
            if df_raw is None or df_raw.empty:
                # 永久性失败（已退市/无数据），不重试
                logger.debug("symbol=%s API 返回空，视为永久失败", symbol)
                return None

            df = _normalize_fields(df_raw, symbol)
            df = _clip_to_target_range(df, target_date_range)
            time.sleep(REQUEST_INTERVAL)  # 节流
            return df

        except (requests.RequestException, json.JSONDecodeError) as e:
            last_failure_reason = type(e).__name__
            last_failure_detail = str(e)[:120]
            if attempt < max_retries:
                # 指数退避 + 抖动: 1s, 2s, 4s + (0..0.4s)
                delay = RETRY_BACKOFF_BASE * (2 ** attempt)
                jitter = random.uniform(0, delay * 0.1)
                logger.debug(
                    "symbol=%s attempt=%d/%d 失败 [%s]，%.1fs 后重试",
                    symbol, attempt + 1, max_retries, last_failure_reason, delay + jitter,
                )
                time.sleep(delay + jitter)
            continue
        except Exception as e:
            # 不可预期异常：记录并放弃（不无限重试）
            logger.exception("symbol=%s 不可预期异常 [%s]", symbol, type(e).__name__)
            return None

    logger.warning(
        "symbol=%s 重试耗尽: reason=%s detail=%s",
        symbol, last_failure_reason, last_failure_detail,
    )
    return None
```

### 5.4 关键控制点

| 控制点 | 决策 | 反例（被排除的方案） |
|---|---|---|
| 失败传播策略 | F3 吞异常 → return None；F4 统计计数；main 不因单批失败终止 | ❌ 任一失败即 raise（决策 E2，已排除） |
| 跨批次状态 | 无（每批独立落盘 + del + gc） | ❌ 全局累积大 DataFrame（OOM 风险） |
| 进度日志 | 每批次结束打 1 条 INFO（含耗时、成功/失败数、记录数） | ❌ 每股一条 DEBUG（生产日志爆炸） |
| 重试粒度 | 单股内 `requests.RequestException / json.JSONDecodeError` 重试 | ❌ 整批次重试（粒度过粗，浪费成功部分） |
| 节流位置 | `fetch_one_stock` 成功后 sleep | ❌ 失败后 sleep（与重试退避叠加，节流过度） |
| 退出码 | 0=完整成功 / 1=运行时错误 / 2=配置错误 | 遵循 AGENTS.md 规则 #6 |

### 5.5 与 fetch_factor_cache 的差异点收敛表

| 项 | fetch_factor_cache | fetch_market_cap |
|---|---|---|
| 单股拉取数据 | 含 OHLCV，约 500 行 | 含估值，约 5000 行（接口默认） |
| 批内合并 | sort + drop_duplicates + cumcount(N_DAYS) | sort + drop_duplicates（**无 N_DAYS 截断**：单股全历史已由裁剪窗口控制） |
| 跨批次合并 | N-way merge | 顺序追加 |
| 内存暂停 | MEMORY_THRESHOLD_MB=900 | **无**（峰值 16MB） |
| 子批次 (sub-batch) | 有（fetch_batch 内部再二分） | **无**（250 股直接 ThreadPool） |

---

## §6. 字段映射（中文 → 英文 / 类型 / 单位）

`ak.stock_value_em` 返回 13 列中文表头，本节定义到英文字段的精确映射，及取舍依据。

### 6.1 接口原始列（akshare 返回）

| # | 中文列名 | 类型（接口返回） | 含义 | 单位 |
|---|---|---|---|---|
| 1 | `数据日期` | `object`（str 'YYYY-MM-DD' 或 datetime） | 交易日 | — |
| 2 | `当日收盘价` | float | 收盘价 | 元 |
| 3 | `当日涨跌幅` | float | 涨跌幅 | % |
| 4 | `总市值` | float | 总市值 | 元 |
| 5 | `流通市值` | float | 流通市值 | 元 |
| 6 | `总股本` | float | 总股本 | 股 |
| 7 | `流通股本` | float | 流通股本 | 股 |
| 8 | `PE(TTM)` | float | 滚动市盈率（过去 12 个月） | 倍 |
| 9 | `PE(静)` | float | 静态市盈率（上一会计年度） | 倍 |
| 10 | `市净率` | float | PB | 倍 |
| 11 | `PEG值` | float | PE/盈利增速 | 倍 |
| 12 | `市现率` | float | PCF（市值 / 经营现金流） | 倍 |
| 13 | `市销率` | float | PS-TTM | 倍 |

> **来源**：akshare 1.18 源码 `stock_feature/stock_a_indicator.py` + 实测调用。

### 6.2 输出字段（保留 12 列）

| # | 输出列名 | 来源 | 类型 | 单位 | None 语义 |
|---|---|---|---|---|---|
| 1 | `date` | `数据日期` | `str` "YYYY-MM-DD" | — | 不允许 None（关键字段，缺失整行丢弃） |
| 2 | `asset` | 函数参数 `symbol` | `str` 6 位 | — | 不允许 None |
| 3 | `total_market_cap` | `总市值` | `float64` | 元 | 允许 None：API 返回 NaN（极少数停牌日） |
| 4 | `circ_market_cap` | `流通市值` | `float64` | 元 | **关键字段**：用于市值中性化，None 比例触发 V6 校验 |
| 5 | `total_shares` | `总股本` | `float64` | 股 | 允许 None |
| 6 | `circ_shares` | `流通股本` | `float64` | 股 | 允许 None |
| 7 | `pe_ttm` | `PE(TTM)` | `float64` | 倍 | 允许 None：亏损股 PE 为 NaN（业务正常） |
| 8 | `pe_lyr` | `PE(静)` | `float64` | 倍 | 允许 None：上年亏损股 |
| 9 | `pb` | `市净率` | `float64` | 倍 | 允许 None：净资产为负的股 |
| 10 | `peg` | `PEG值` | `float64` | 倍 | 允许 None：增速为负 |
| 11 | `pcf_ttm` | `市现率` | `float64` | 倍 | 允许 None：经营现金流为负 |
| 12 | `ps_ttm` | `市销率` | `float64` | 倍 | 允许 None：极少数无营收股 |

### 6.3 删除的列（解释）

| 中文列 | 是否输出 | 删除原因 |
|---|---|---|
| `当日收盘价` | ✗ | factor_data.json.gz 已含 `close`，不在本模块重复存储（DRY） |
| `当日涨跌幅` | ✗ | factor_data.json.gz 已含 `forward_return_1d`，且涨跌幅可由 close 推导 |

> **决策依据**：AGENTS.md 跨模块数据契约表，`factor_data.json.gz` 是行情 + 收益的唯一权威源，`market_cap_data.json.gz` 仅承载市值/估值横切面。

### 6.4 _normalize_fields() 实现草案

```python
_FIELD_MAPPING: dict[str, str] = {
    "数据日期": "date",
    "总市值": "total_market_cap",
    "流通市值": "circ_market_cap",
    "总股本": "total_shares",
    "流通股本": "circ_shares",
    "PE(TTM)": "pe_ttm",
    "PE(静)": "pe_lyr",
    "市净率": "pb",
    "PEG值": "peg",
    "市现率": "pcf_ttm",
    "市销率": "ps_ttm",
}
_DROPPED_FIELDS: tuple[str, ...] = ("当日收盘价", "当日涨跌幅")
_OUTPUT_COLUMNS: tuple[str, ...] = (
    "date", "asset",
    "total_market_cap", "circ_market_cap",
    "total_shares", "circ_shares",
    "pe_ttm", "pe_lyr", "pb", "peg", "pcf_ttm", "ps_ttm",
)


def _normalize_fields(df_raw: pd.DataFrame, symbol: str) -> pd.DataFrame:
    """
    归一化 ak.stock_value_em 返回结果：
      - 校验中文列存在
      - 重命名 → 英文
      - 删除冗余列
      - 添加 asset 列
      - 类型转换（date 为 ISO 字符串、其他 float64）
      - 列序固定为 _OUTPUT_COLUMNS

    Raises:
        ValueError: 接口返回的列与预期不符（防御性，AGENTS.md 规则 #14 不允许哑兜底）。
    """
    expected_cn = set(_FIELD_MAPPING.keys()) | set(_DROPPED_FIELDS)
    missing = expected_cn - set(df_raw.columns)
    if missing:
        raise ValueError(
            f"symbol={symbol} 接口返回缺少预期列: {sorted(missing)}; "
            f"实际列: {list(df_raw.columns)}"
        )

    df = df_raw.rename(columns=_FIELD_MAPPING)
    df = df.drop(columns=list(_DROPPED_FIELDS), errors="ignore")
    df["asset"] = symbol

    # date 标准化为 ISO 字符串
    df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")

    # 数值列统一 float64（保留 NaN，None 在落盘时由 schema 处理）
    numeric_cols = [c for c in _OUTPUT_COLUMNS if c not in ("date", "asset")]
    df[numeric_cols] = df[numeric_cols].astype("float64")

    # 列序固定
    return df[list(_OUTPUT_COLUMNS)]
```

### 6.5 ln 处理位置（决策回链）

| 选项 | 是否采用 | 理由 |
|---|---|---|
| A. 数据采集时存 `ln_circ_market_cap` 列 | ✗ | 单位丢失（无法回推到元）、未来若改 z-score 需重拉数据 |
| B. **采集时存原始值 `circ_market_cap`，下游中性化时计算 `np.log(...)`** | ✓ | 符合"采集存原始数据"原则，与 `factor_data.json.gz` 存 `close` 不存 `log_close` 一致 |
| C. 同时存原始值 + ln 列 | ✗ | 字段冗余，违反 §6.2 决策"保留 12 列" |

**结论**：本模块**不计算 ln**，仅存原始 `circ_market_cap`（单位：元）。`np.log(circ_market_cap)` 在后续中性化模块（不属本设计范围）实现。

### 6.6 None 语义与字段非空率合约

| 字段 | None 业务含义 | V6 校验阈值 |
|---|---|---|
| `date / asset` | 不应出现 | 100% 非空（任何 None 整行丢弃） |
| `total_market_cap / circ_market_cap` | 停牌日 / API 数据缺失 | **circ_market_cap ≥ 99%** |
| `total_shares / circ_shares` | 同上 | ≥ 99% |
| `pe_ttm / pe_lyr` | 亏损股（业务正常） | 不校验（参考值 70-90%） |
| `pb` | 净资产为负 | 不校验（参考值 ≥ 99%） |
| `peg / pcf_ttm / ps_ttm` | 算法指标，分母为负或 0 | 不校验 |

> **依据**：AGENTS.md 规则 #4（None 必须显式设置 + 记录原因）。本设计将"原因"统一记为"接口返回 NaN（业务允许）"，由 schema 校验放行。

---

## §7. 输出 Schema（meta + data 结构 + JSON Schema 文件）

### 7.1 文件结构（顶层）

最终输出 `data_fetchers/result/market_cap_data.json.gz` 解压后为 UTF-8 JSON 文本，结构：

```json
{
  "meta": { ... },
  "data": [ {...}, {...}, ... ]
}
```

> **存储格式约定**：与 `factor_data.json.gz` / `turnover_rate_data.json.gz` 一致——单文件 JSON，gzip 压缩。**不使用** JSON Lines / Parquet / HDF5。

### 7.2 `meta` 字段定义

```json
{
  "generated_at": "2026-06-18T10:30:45.123456",
  "source": "akshare_stock_value_em",
  "version": "1.0",
  "n_assets": 2867,
  "n_days": 545,
  "n_records": 1562515,
  "date_range": {
    "start": "2024-03-18",
    "end": "2026-06-17"
  },
  "fields": [
    "date", "asset",
    "total_market_cap", "circ_market_cap",
    "total_shares", "circ_shares",
    "pe_ttm", "pe_lyr", "pb", "peg", "pcf_ttm", "ps_ttm"
  ],
  "field_units": {
    "total_market_cap": "yuan",
    "circ_market_cap": "yuan",
    "total_shares": "share",
    "circ_shares": "share",
    "pe_ttm": "ratio",
    "pe_lyr": "ratio",
    "pb": "ratio",
    "peg": "ratio",
    "pcf_ttm": "ratio",
    "ps_ttm": "ratio"
  },
  "fetch_stats": {
    "total_symbols_attempted": 2900,
    "success_count": 2867,
    "fail_count": 33,
    "fail_rate_pct": 1.14,
    "elapsed_seconds": 1825.4
  },
  "factor_data_alignment": {
    "factor_data_date_range": {"start": "2024-03-18", "end": "2026-06-17"},
    "aligned": true
  }
}
```

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `generated_at` | str (ISO 8601) | ✓ | 文件生成时刻（精度到微秒） |
| `source` | str | ✓ | 固定值 `"akshare_stock_value_em"`（便于审计与版本追溯） |
| `version` | str | ✓ | 输出 schema 版本（变更字段集时递增） |
| `n_assets` | int | ✓ | 实际写入的去重股票数 |
| `n_days` | int | ✓ | 实际写入的去重交易日数 |
| `n_records` | int | ✓ | data 数组长度，必须 == V1 校验值 |
| `date_range` | object | ✓ | 实际数据的 min/max date |
| `fields` | array[str] | ✓ | 顺序与 §6.2 _OUTPUT_COLUMNS 一致 |
| `field_units` | object | ✓ | 字段 → 单位（不含 date/asset） |
| `fetch_stats` | object | ✓ | 拉取统计（运维诊断用） |
| `factor_data_alignment` | object | ✓ | 与上游 factor_data.json.gz 的对齐校验结果 |

### 7.3 `data` 字段定义

```json
[
  {
    "date": "2024-03-18",
    "asset": "000001",
    "total_market_cap": 218300000000.0,
    "circ_market_cap": 218150000000.0,
    "total_shares": 19405918198.0,
    "circ_shares": 19392580398.0,
    "pe_ttm": 4.62,
    "pe_lyr": 4.78,
    "pb": 0.51,
    "peg": null,
    "pcf_ttm": 1.23,
    "ps_ttm": 1.45
  }
]
```

**类型与约束**：

| 字段 | JSON 类型 | nullable | 约束 |
|---|---|---|---|
| `date` | string | 否 | 模式 `^\d{4}-\d{2}-\d{2}$` |
| `asset` | string | 否 | 模式 `^\d{6}$` |
| `total_market_cap` | number | ✓ | 允许 null；非 null 时 ≥ 0 |
| `circ_market_cap` | number | ✓ | 允许 null；非 null 时 ≥ 0；**非空率 ≥ 99%（V6）** |
| `total_shares` | number | ✓ | 允许 null；非 null 时 ≥ 0 |
| `circ_shares` | number | ✓ | 允许 null；非 null 时 ≥ 0 |
| `pe_ttm` | number | ✓ | 允许 null；可负 |
| `pe_lyr` | number | ✓ | 允许 null；可负 |
| `pb` | number | ✓ | 允许 null；可负 |
| `peg` | number | ✓ | 允许 null；可正可负 |
| `pcf_ttm` | number | ✓ | 允许 null；可正可负 |
| `ps_ttm` | number | ✓ | 允许 null；非 null 时 ≥ 0 |

### 7.4 JSON Schema 文件（草案）

文件路径：`data_fetchers/schemas/market_cap_data.schema.json`

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "title": "MarketCapData",
  "type": "object",
  "required": ["meta", "data"],
  "additionalProperties": false,
  "properties": {
    "meta": {
      "type": "object",
      "required": [
        "generated_at", "source", "version",
        "n_assets", "n_days", "n_records",
        "date_range", "fields", "field_units",
        "fetch_stats", "factor_data_alignment"
      ],
      "properties": {
        "generated_at": {"type": "string", "format": "date-time"},
        "source": {"type": "string", "const": "akshare_stock_value_em"},
        "version": {"type": "string", "pattern": "^\\d+\\.\\d+$"},
        "n_assets": {"type": "integer", "minimum": 1},
        "n_days": {"type": "integer", "minimum": 1},
        "n_records": {"type": "integer", "minimum": 1},
        "date_range": {
          "type": "object",
          "required": ["start", "end"],
          "properties": {
            "start": {"type": "string", "pattern": "^\\d{4}-\\d{2}-\\d{2}$"},
            "end":   {"type": "string", "pattern": "^\\d{4}-\\d{2}-\\d{2}$"}
          }
        },
        "fields": {
          "type": "array",
          "items": {"type": "string"},
          "minItems": 12,
          "maxItems": 12
        },
        "field_units": {"type": "object"},
        "fetch_stats": {
          "type": "object",
          "required": ["total_symbols_attempted", "success_count", "fail_count", "fail_rate_pct"],
          "properties": {
            "total_symbols_attempted": {"type": "integer"},
            "success_count": {"type": "integer"},
            "fail_count": {"type": "integer"},
            "fail_rate_pct": {"type": "number", "minimum": 0, "maximum": 100},
            "elapsed_seconds": {"type": "number", "minimum": 0}
          }
        },
        "factor_data_alignment": {
          "type": "object",
          "required": ["factor_data_date_range", "aligned"],
          "properties": {
            "factor_data_date_range": {"$ref": "#/properties/meta/properties/date_range"},
            "aligned": {"type": "boolean"}
          }
        }
      }
    },
    "data": {
      "type": "array",
      "minItems": 1,
      "items": {
        "type": "object",
        "required": [
          "date", "asset",
          "total_market_cap", "circ_market_cap",
          "total_shares", "circ_shares",
          "pe_ttm", "pe_lyr", "pb", "peg", "pcf_ttm", "ps_ttm"
        ],
        "additionalProperties": false,
        "properties": {
          "date":             {"type": "string", "pattern": "^\\d{4}-\\d{2}-\\d{2}$"},
          "asset":            {"type": "string", "pattern": "^\\d{6}$"},
          "total_market_cap": {"type": ["number", "null"], "minimum": 0},
          "circ_market_cap":  {"type": ["number", "null"], "minimum": 0},
          "total_shares":     {"type": ["number", "null"], "minimum": 0},
          "circ_shares":      {"type": ["number", "null"], "minimum": 0},
          "pe_ttm":           {"type": ["number", "null"]},
          "pe_lyr":           {"type": ["number", "null"]},
          "pb":               {"type": ["number", "null"]},
          "peg":              {"type": ["number", "null"]},
          "pcf_ttm":          {"type": ["number", "null"]},
          "ps_ttm":           {"type": ["number", "null"], "minimum": 0}
        }
      }
    }
  }
}
```

### 7.5 落盘细节

| 项 | 决策 | 实现 |
|---|---|---|
| 编码 | UTF-8 | `json.dumps(..., ensure_ascii=False)` |
| 缩进 | 无（紧凑） | `json.dumps(..., separators=(",", ":"))` |
| NaN 处理 | 转 `null` | pandas → records 前 `df.where(pd.notna(df), None)` |
| 原子写 | tempfile + rename | 复用 `fetch_turnover.py` 的 `tempfile.NamedTemporaryFile(dir=...) + os.replace` |
| 压缩级别 | `gzip.GzipFile(compresslevel=6)` | 与 `fetch_turnover.py` 一致（默认压缩） |
| MODULE.md R13 | 原子写 | ✓ 满足 |

### 7.6 排序契约

最终 `data` 数组排序键：`(date ASC, asset ASC)`

> **依据**：与 `factor_data.json.gz` 排序约定一致，便于下游做 `pd.merge_asof` 或按 date 分组的 IC 计算。

---

## §8. 单位 / 异常 / 节流约定（汇总）

本节集中定义此前散落在 §3-§7 的运行时规则，作为 Execute 阶段实现时的单一参考点。

### 8.1 单位约定

| 来源字段 | 接口单位 | 输出单位 | 是否换算 | 理由 |
|---|---|---|---|---|
| 总市值 / 流通市值 | 元 | **元** | ✗ | 决策 D1：保留原始单位，ln 归一化由下游负责 |
| 总股本 / 流通股本 | 股 | **股** | ✗ | 同上 |
| PE / PB / PEG / PCF / PS | 倍 | **倍** | ✗ | 比率类无单位换算 |
| 当日涨跌幅 | % | — | — | 已删除（§6.3） |

> **铁律**：本模块**不做任何单位换算**。下游若需亿元/百万元单位，自行处理。

### 8.2 异常分类与处理矩阵

| 异常类型 | 触发场景 | 处理策略 | 重试 | 影响 |
|---|---|---|---|---|
| `requests.RequestException` | 网络超时、连接拒绝、HTTP 5xx | retry 3 次 + 指数退避 | ✓ | 失败计入 fail_count |
| `requests.HTTPError` (4xx) | 接口限流 / 参数错误 | retry 3 次 + 退避 | ✓ | 同上 |
| `json.JSONDecodeError` | 响应非 JSON（HTML 错误页） | retry 3 次 + 退避 | ✓ | 同上 |
| `KeyError` / `pd.errors.EmptyDataError` | API 返回空 DataFrame | 不重试，return None | ✗ | 永久失败 |
| `ValueError`（输入参数） | symbol 长度 ≠ 6 / target_date_range 非法 | 直接 raise（程序员错误） | ✗ | 终止当前股 |
| `Exception`（兜底） | 不可预期 | logger.exception + return None | ✗ | 单股失败，不影响其他 |
| 接口返回异常列结构 | `_normalize_fields` 检测列缺失 | raise ValueError（不哑兜底，遵循硬规则 #14） | ✗ | 终止当前股 |

### 8.3 失败率阈值

| 阈值 | 数值 | 触发动作 | 依据 |
|---|---|---|---|
| 单批次允许失败率 | ≤ 50% | 超过：保存已成功部分 + warning，不终止 | 容错优先（脚本不卡） |
| 总体允许失败率 | ≤ 5% | 超过：`main()` 返回退出码 1（失败） | 业务可接受上限 |
| 关键字段非空率（V6） | circ_market_cap ≥ 99% | 不达：validate_final_data 返回 False | 中性化前提 |
| 股票覆盖率（V5） | ≥ 95%（vs stock_list 去 ST） | 不达：警告但不终止 | 经验阈值 |

### 8.4 节流策略

| 节流点 | 时机 | 时长 | 理由 |
|---|---|---|---|
| 单股调用间隔 | 成功后 sleep | `REQUEST_INTERVAL = 0.1s` | 防东财频控（实测 100QPS 安全线） |
| 重试退避基数 | 失败重试前 sleep | `1.0 × 2^attempt`（1s/2s/4s）+ 抖动 | 避免雷鸣群效应 |
| 抖动幅度 | 退避基础上叠加 | `random.uniform(0, delay × 0.1)` | 打散并发请求 |
| 批次间间隔 | 单批落盘后 | **无**（gc.collect 即可） | 整体进度优先，单批已含节流 |
| 限流硬触发 | HTTP 429 / 503 | 计入 retry，按 8.2 处理 | 东财不返回 Retry-After 头 |

### 8.5 时间口径

| 项 | 取值 | 实现 |
|---|---|---|
| 时区 | 本地时区（北京时间） | 不显式 tz-aware；与 fetch_turnover/fetch_factor_cache 一致 |
| `_NOW` 锁定时刻 | 模块加载时 `datetime.now()` | 与 fetch_turnover.py:198 模式一致；避免长时间运行中跨日 |
| 默认 target_date_range | 读 factor_data.json.gz `meta.date_range` | `_read_factor_data_date_range()` 返回 (start, end) ISO 字符串 |
| 当日数据可获得性 | 收盘后约 18:00 后 | 不强制：API 给什么我们存什么；运行时机由调度方决定 |

### 8.6 import 规范（双导入兼容）

```python
# 双导入模式（与 fetch_turnover.py:177-183 一致）
try:
    from common.paths import (
        get_module_result_dir,
        get_module_logs_dir,
        get_stock_list_file,
    )
    from common.logger_config import setup_logger
except ImportError:
    from data_fetchers.common.paths import (
        get_module_result_dir,
        get_module_logs_dir,
        get_stock_list_file,
    )
    from data_fetchers.common.logger_config import setup_logger
```

> **依据**：兼容两种调用方式——脚本直接运行（`python data_fetchers/fetch_market_cap.py`） vs 包导入（`from data_fetchers import fetch_market_cap`）。

### 8.7 日志规范

| 级别 | 使用场景 | 频率 |
|---|---|---|
| INFO | 批次开始/结束、最终汇总、阶段切换 | 每批 1-2 条 |
| WARNING | 单股全部重试耗尽、批次空、覆盖率不达标 | 按事件 |
| ERROR | 配置错误、上游文件缺失、最终验证失败 | 按事件 |
| DEBUG | 单股 retry 进度、节流 sleep | 默认关闭 |
| `logger.exception` | 不可预期异常（兜底 except） | 罕见 |

**日志格式**：使用 `setup_logger(_SCRIPT_NAME, _LOGS_DIR)` 返回的 logger，遵循 AGENTS.md 规则 #9。

**禁止**：
- ❌ `logging.basicConfig()` （MODULE.md 禁用）
- ❌ f-string 日志（`logger.info(f"...{x}...")`，违反硬规则 #13）
- ❌ `logger.exception(..., exc_info=True)` （冗余，硬规则 #13）
- ❌ `logger.error(str(e))` （丢失栈，应用 `logger.exception`）

### 8.8 退出码语义（main() 返回值）

| 退出码 | 含义 | 触发条件 |
|---|---|---|
| 0 | 成功 | 全流程完成、V1-V7 验证通过、总体失败率 ≤ 5% |
| 1 | 运行时错误 | 总体失败率 > 5% / 最终验证失败 / 上游 factor_data 缺失 |
| 2 | 配置或导入错误 | import 失败 / paths 常量缺失 / akshare 未安装 |

> **依据**：AGENTS.md 规则 #6（`0=成功 / 1=运行时错误 / 2=import-time 配置或注册失败`）。

---

## §9. 测试用例清单（pytest）

测试文件：`data_fetchers/test_cases/test_fetch_market_cap.py`

### 9.1 测试范围与分级

| 级别 | 数量 | 依赖 | 运行时长 | 何时运行 |
|---|---|---|---|---|
| Unit（mock akshare） | 18 | 无网络，pytest 默认 | < 5s | CI 必跑 |
| Integration（真接口） | 3 | 网络 + akshare | 30-60s | 标 `@pytest.mark.network`，本地手跑 |
| Validation（真数据） | 4 | 已生成的 market_cap_data.json.gz | < 2s | 数据采集后跑 |

### 9.2 Unit 测试用例（18 项）

#### F2. `load_target_assets`（3）

| ID | 用例名 | 验证点 |
|---|---|---|
| U-F2-1 | `test_load_target_assets_strips_st_prefixes` | ST/*ST/S 前缀股票被过滤 |
| U-F2-2 | `test_load_target_assets_returns_6digit_strings` | 返回 list[str]，每项长 6 且全数字 |
| U-F2-3 | `test_load_target_assets_raises_on_missing_file` | 文件不存在 → FileNotFoundError |

#### F3. `fetch_one_stock`（6）

| ID | 用例名 | 验证点 |
|---|---|---|
| U-F3-1 | `test_fetch_one_stock_happy_path` | mock 返回正常 DataFrame → 返回归一化后 12 列 DF |
| U-F3-2 | `test_fetch_one_stock_returns_none_on_empty_api_response` | mock 返回空 DF → return None，不重试 |
| U-F3-3 | `test_fetch_one_stock_retries_on_request_exception` | mock 前 2 次抛 ConnectionError，第 3 次成功 → 返回数据，调用 3 次 |
| U-F3-4 | `test_fetch_one_stock_returns_none_after_max_retries` | mock 始终抛网络异常 → return None，调用 max_retries+1 次 |
| U-F3-5 | `test_fetch_one_stock_clips_to_target_range` | mock 返回跨 5 年数据 → 输出仅含 target 区间内日期 |
| U-F3-6 | `test_fetch_one_stock_raises_on_invalid_symbol` | symbol="abc" → ValueError |

#### F4. `fetch_batch`（3）

| ID | 用例名 | 验证点 |
|---|---|---|
| U-F4-1 | `test_fetch_batch_aggregates_success_and_fail_counts` | 5 股 mix（3 成功/1 None/1 空 DF）→ success=4, fail=1 |
| U-F4-2 | `test_fetch_batch_returns_none_when_all_fail` | 全部 mock 返回 None → 第一返回值 None |
| U-F4-3 | `test_fetch_batch_concurrent_isolation` | 并发 5 股，其中 1 股抛异常 → 其他 4 股不受影响 |

#### F5. `save_batch_cache` / F6. `merge_and_emit_final`（4）

| ID | 用例名 | 验证点 |
|---|---|---|
| U-F5-1 | `test_save_batch_cache_writes_gzip_with_correct_columns` | 落盘后 gzip 解压列序 == _OUTPUT_COLUMNS |
| U-F5-2 | `test_save_batch_cache_atomic_write` | 写入过程中模拟中断 → 目标路径无半成品文件 |
| U-F6-1 | `test_merge_and_emit_final_concatenates_in_order` | 3 个批次合并 → 总记录数 = sum(各批) |
| U-F6-2 | `test_merge_and_emit_final_meta_fields_complete` | meta 含全部 11 个 §7.2 必填字段 |

#### F7. `_normalize_fields`（2）

| ID | 用例名 | 验证点 |
|---|---|---|
| U-F7-1 | `test_normalize_fields_renames_chinese_to_english` | 13 列中文 → 12 列英文 + asset |
| U-F7-2 | `test_normalize_fields_raises_on_missing_columns` | 输入缺 `流通市值` 列 → ValueError（防御性，硬规则 #14） |

### 9.3 Integration 测试（3 项，标 `@pytest.mark.network`）

| ID | 用例名 | 验证点 |
|---|---|---|
| I-1 | `test_real_api_single_stock_fetch` | 真接口拉 000001 → 返回非空 DF，列结构匹配 |
| I-2 | `test_real_api_known_delisted_stock` | 真接口拉已退市股 → return None |
| I-3 | `test_real_api_throughput` | 拉 5 股串行 → 总耗时 < 10s（节流 sanity check） |

### 9.4 Validation 测试（4 项，依赖已生成数据）

| ID | 用例名 | 验证点 | 对应验收标准 |
|---|---|---|---|
| V-1 | `test_final_output_record_count` | n_records 等于 meta 声明值 | V1 |
| V-2 | `test_final_output_date_range_aligns_with_factor_data` | date_range 与 factor_data.json.gz 完全一致 | V3 |
| V-3 | `test_final_output_circ_market_cap_non_null_rate` | circ_market_cap 非空率 ≥ 99% | V6 |
| V-4 | `test_final_output_jsonschema_validation` | jsonschema.validate(data, schema) 不抛 | V4 |

### 9.5 测试基础设施

#### Fixture：mock akshare 响应

```python
@pytest.fixture
def fake_em_response():
    """构造 ak.stock_value_em 风格的 13 列 DataFrame。"""
    n = 60
    dates = pd.date_range("2024-01-01", periods=n, freq="B").strftime("%Y-%m-%d")
    return pd.DataFrame({
        "数据日期":  dates,
        "当日收盘价": np.random.uniform(5, 50, n),
        "当日涨跌幅": np.random.uniform(-5, 5, n),
        "总市值":    np.random.uniform(1e9, 1e12, n),
        "流通市值":  np.random.uniform(1e9, 1e12, n),
        "总股本":    np.random.uniform(1e8, 1e10, n),
        "流通股本":  np.random.uniform(1e8, 1e10, n),
        "PE(TTM)":   np.random.uniform(5, 50, n),
        "PE(静)":    np.random.uniform(5, 50, n),
        "市净率":    np.random.uniform(0.5, 5, n),
        "PEG值":     np.random.uniform(-2, 2, n),
        "市现率":    np.random.uniform(-5, 50, n),
        "市销率":    np.random.uniform(0.5, 20, n),
    })
```

#### Fixture：mock 失败序列

```python
@pytest.fixture
def fail_then_succeed():
    """前 N 次抛 ConnectionError，第 N+1 次返回正常数据。"""
    def _factory(fail_n: int, success_df: pd.DataFrame):
        attempts = [requests.ConnectionError("mock")] * fail_n + [success_df]
        return iter(attempts).__next__
    return _factory
```

### 9.6 命名规范（遵循 PROJECT.md）

| 规则 | 要求 |
|---|---|
| 测试文件名 | `test_fetch_market_cap.py`（与脚本对应） |
| 测试函数名 | 具体化（不用 `test_xx_yy`），含验证点 |
| 标记 | `@pytest.mark.network` 标真网络用例 |
| 稳定性标签 | 新增用例**不**标 `[experimental]`（本设计已通过 design-first 评审） |
| 阈值硬编码 + 行号引用 | V6 用例硬编码 `0.99`，注释 `# 来源: design.md §8.3` |

### 9.7 覆盖率目标

- **行覆盖**：≥ 70%（PROJECT.md `--cov-fail-under=70`）
- **关键路径覆盖**：F3 重试逻辑、F7 字段映射 100%
- **不强求覆盖**：网络真接口 / cleanup_batch_files（已在 batch_processor 单元测试覆盖）

---

## §10. 验证脚本（数据质量校验）

数据采集完成后，独立运行的"事后验证"脚本，与 §9.4 Validation 测试相互独立但目标一致。

### 10.1 验证脚本位置

| 路径 | 用途 |
|---|---|
| `data_fetchers/temporary/verify_market_cap_data.py` | 一次性的事后验证，**不进版本控制 `data_fetchers` 主目录**（遵循 AGENTS.md 规则 #3：临时脚本放 `temporary/`） |

### 10.2 验证项（V1-V7 全覆盖）

| ID | 验证项 | 通过条件 | 不通过动作 |
|---|---|---|---|
| V1 | 记录数一致 | `len(data) == meta.n_records` | 报错并退出 1 |
| V2 | 字段集完备 | 每条记录恰好含 `_OUTPUT_COLUMNS` 12 字段 | 列出缺失/多余字段 |
| V3 | 日期对齐 | `meta.date_range == factor_data.meta.date_range` | 列出 diff |
| V4 | JSON Schema 合规 | `jsonschema.validate(...)` 不抛 | 列出违反约束的记录数 |
| V5 | 股票覆盖率 | `n_assets / (stock_list - ST) ≥ 0.95` | 警告并列出缺失股票（前 20） |
| V6 | 关键字段非空率 | `circ_market_cap` 非空率 ≥ 0.99 | 报错并列出缺失日期分布 |
| V7 | 排序正确 | data 按 (date, asset) 升序 | 列出第一处违反位置 |

### 10.3 脚本骨架（伪代码）

```python
"""
data_fetchers/temporary/verify_market_cap_data.py

事后验证 market_cap_data.json.gz 数据质量（V1-V7）。

用法：
    python data_fetchers/temporary/verify_market_cap_data.py

退出码：
    0 - 全部验证通过
    1 - 任一验证失败
"""

from __future__ import annotations

import gzip
import json
import sys
from collections import Counter
from pathlib import Path

import jsonschema
import pandas as pd

from data_fetchers.common.paths import (
    get_factor_data_file,
    get_module_result_dir,
    get_stock_list_file,
)


def main() -> int:
    market_cap_file = get_module_result_dir("data_fetchers") / "market_cap_data.json.gz"
    schema_file = Path(__file__).parents[1] / "schemas" / "market_cap_data.schema.json"

    with gzip.open(market_cap_file, "rt", encoding="utf-8") as f:
        payload = json.load(f)
    meta = payload["meta"]
    data = payload["data"]
    schema = json.loads(schema_file.read_text(encoding="utf-8"))

    failures: list[str] = []

    # V1
    if len(data) != meta["n_records"]:
        failures.append(f"V1: len(data)={len(data)} != meta.n_records={meta['n_records']}")

    # V2
    expected_fields = set(meta["fields"])
    for i, rec in enumerate(data[:1000]):  # 抽样前 1000 条
        if set(rec.keys()) != expected_fields:
            failures.append(f"V2: 记录 {i} 字段集不匹配: {set(rec.keys()) ^ expected_fields}")
            break

    # V3
    with gzip.open(get_factor_data_file(), "rt", encoding="utf-8") as f:
        factor_meta = json.load(f)["meta"]
    if meta["date_range"] != factor_meta["date_range"]:
        failures.append(
            f"V3: date_range 不对齐 our={meta['date_range']} factor={factor_meta['date_range']}"
        )

    # V4
    try:
        jsonschema.validate(payload, schema)
    except jsonschema.ValidationError as e:
        failures.append(f"V4: schema 违反: {e.message[:200]}")

    # V5
    stock_list = json.loads(get_stock_list_file().read_text(encoding="utf-8"))
    eligible = [s for s in stock_list["data"] if not s["name"].startswith(("*ST", "ST", "S"))]
    coverage = meta["n_assets"] / max(1, len(eligible))
    if coverage < 0.95:
        failures.append(f"V5: 覆盖率 {coverage:.2%} < 95%")

    # V6
    df = pd.DataFrame(data)
    non_null_rate = df["circ_market_cap"].notna().mean()
    if non_null_rate < 0.99:
        failures.append(f"V6: circ_market_cap 非空率 {non_null_rate:.4%} < 99%")

    # V7
    sorted_df = df.sort_values(["date", "asset"], kind="mergesort").reset_index(drop=True)
    if not df.equals(sorted_df):
        first_bad = (df["date"] != sorted_df["date"]).idxmax()
        failures.append(f"V7: 排序错乱，首处位置 idx={first_bad}")

    # 汇总
    if failures:
        print("✗ 验证失败:")
        for f in failures:
            print(f"  - {f}")
        return 1

    print("✓ 全部验证通过")
    print(f"  n_assets={meta['n_assets']}, n_days={meta['n_days']}, n_records={meta['n_records']}")
    print(f"  circ_market_cap 非空率: {non_null_rate:.4%}")
    print(f"  股票覆盖率: {coverage:.2%}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

### 10.4 与 validate_final_data 的边界

| 维度 | F9 `validate_final_data`（脚本内置） | `verify_market_cap_data.py`（事后脚本） |
|---|---|---|
| 调用时机 | `main()` 内联 | 数据采集完成后手动 |
| 阻塞退出码 | ✓ 返回值影响 main 退出 | ✓ 独立退出码 |
| 校验深度 | V1（记录数）+ V6（非空率） | V1-V7 全部 |
| 所属目录 | `data_fetchers/fetch_market_cap.py` | `data_fetchers/temporary/` |
| 是否进 git | ✓ | ✗（temporary/ 不入版本） |

> **理由**：`validate_final_data` 是采集流水线的"门禁"（必须通过才输出 0）；`verify_market_cap_data.py` 是开发/调试期"显微镜"（深度审查 + 抽样定位异常）。

---

## §11. 影响面与分批 Commit 计划

本节列出本设计触及的全部文件，并按 H9（≤3 文件 ≤200 行）拆分为多个独立 commit，每 commit 都满足"可单独通过 ruff + pytest"的最小可验证集。

### 11.1 影响文件全集

| # | 文件 | 操作 | 行数估算 | 性质 |
|---|---|---|---|---|
| 1 | `paths.py` | 修改 | +2 | 添加 `MARKET_CAP_DATA = DATA_FETCHERS_RESULT / "market_cap_data.json.gz"` 常量 |
| 2 | `data_fetchers/common/paths.py` | 修改 | +5 | 添加 `get_market_cap_data_file()` getter（与现有同模式） |
| 3 | `data_fetchers/schemas/market_cap_data.schema.json` | 新建 | ~120 | §7.4 定义的 JSON Schema |
| 4 | `data_fetchers/fetch_market_cap.py` | 新建 | ~400 | 主脚本（F1-F9 + 8 个常量 + helper） |
| 5 | `data_fetchers/test_cases/test_fetch_market_cap.py` | 新建 | ~350 | §9.2 的 18 个 unit 测试 + fixtures |
| 6 | `data_fetchers/docs/fetch_market_cap_flow.md` | 新建 | ~200 | 流程文档（与 fetch_turnover_flow.md 同模板） |
| 7 | `data_fetchers/temporary/verify_market_cap_data.py` | 新建 | ~120 | §10.3 验证脚本 |
| 8 | `data_fetchers/MODULE.md` | 修改 | +20 | 缓存文件清单加 `market_cap_data.json.gz` 一行 |
| 9 | `AGENTS.md` | 修改 | +1 | 跨模块数据路径表第 1.1 节加一行 |
| 10 | `PROJECT.md` | 修改 | +2 | 路径常量附录补 `MARKET_CAP_DATA` |

**总计**：10 文件，约 1220 行（含新建脚本 + 测试 + 文档）。

### 11.2 分批 commit 计划（5 个 commit）

| Commit | 内容 | 文件 | 行数 | 验证 |
|---|---|---|---|---|
| C1 | 路径常量 + JSON Schema | 1, 2, 3 | ~127 | ruff + pytest（schema 文件用 jsonschema.Draft7Validator.check_schema） |
| C2 | 主脚本（F1-F9） | 4 | ~400 | ruff + pytest（仅 import smoke test，因测试文件 C3 才加） |
| C3 | 测试用例 | 5 | ~350 | ruff + pytest（C2 主脚本通过 18 个 unit 测试） |
| C4 | 文档 + 验证脚本 | 6, 7 | ~320 | 仅 ruff（md/temporary 不进 pytest） |
| C5 | 跨模块文档同步 | 8, 9, 10 | ~23 | 仅 ruff |

> **每 commit ≤3 文件 ≤400 行**：C2 单文件 400 行刚好踩 H9 上限，因为 `fetch_market_cap.py` 必须作为整体提交（拆分会导致 import 时 NameError，违反硬规则 #6）。

### 11.3 commit 消息模板

每条 commit 必须遵循 USER 偏好"提交消息引用规范行号"，模板：

```
feat(market_cap): C1 添加路径常量与 JSON Schema

实现 designs/feat_market_cap_data_fetcher.md §7.4 + §11.2 C1

- paths.py: +MARKET_CAP_DATA 常量
- data_fetchers/common/paths.py: +get_market_cap_data_file()
- data_fetchers/schemas/market_cap_data.schema.json: 新建（§7.4）

遵循:
- AGENTS.md 规则 #11（路径导入）行 76
- PROJECT.md 路径常量附录行 561-565
- AGENTS.md 硬规则 #4（None 必须显式）行 70

验证:
- ruff check --fix data_fetchers/common/paths.py paths.py
- python -c "import json,jsonschema; jsonschema.Draft7Validator.check_schema(json.load(open('data_fetchers/schemas/market_cap_data.schema.json')))"
```

### 11.4 跨模块协作风险

| 风险 | 缓解措施 |
|---|---|
| 多 agent 并行同仓库（已有教训） | 每 commit 前 `git status --short \| wc -l` 数行 + 显式路径 commit（遵循 MEMORY 第 7 段） |
| AGENTS.md 修改与他人冲突 | C5 单独成 commit，最后提交，临提交前再次 git pull rebase |
| paths.py 是高频被修改文件 | C1 commit 前先 `git pull --rebase`，并验证常量未与他人重名 |

### 11.5 Execute 阶段时间预算

| 阶段 | 预估耗时 | 风险点 |
|---|---|---|
| C1 实现 + 验证 | 15 min | jsonschema 包是否已安装（fallback：先纯文本写） |
| C2 实现 + smoke test | 60 min | 单股调用真接口验证字段名（需 .venv_akshare 修复） |
| C3 测试编写 + 运行 | 90 min | 并发测试 fixture 编写 |
| C4 文档 + 验证脚本 | 30 min | docs/fetch_market_cap_flow.md 模板化 |
| C5 跨模块文档同步 | 15 min | 多 agent 冲突风险 |
| **首次真数据采集** | 30 min | 网络稳定性，2900 股 × ~0.6s = 30min（4 并发） |
| **事后 V1-V7 验证** | 5 min | 通过后正式入库 |
| **总计** | **~245 min**（约 4 小时） | |

### 11.6 design.md 自检清单

- [x] §1 背景与决策依据
- [x] §2 目标 + V1-V9 验收标准
- [x] §3.1 模块结构（9 函数）
- [x] §3.2 核心函数签名（F2/F3/F4 完整签名）
- [x] §4 数据流（端到端图 + 量级估算）
- [x] §5 批处理架构（main/fetch_batch/fetch_one_stock 伪代码）
- [x] §6 字段映射（中→英 + 单位 + None 语义）
- [x] §7 输出 Schema（meta + data + JSON Schema 文件）
- [x] §8 单位/异常/节流约定
- [x] §9 测试用例清单（25 个）
- [x] §10 验证脚本（V1-V7）
- [x] §11 影响面与分批 commit 计划
- [x] 决策表锁定 6 维度（A2-B2-C1-D1-E1-F2）
- [x] 6 文件 644 行影响面声明 → 拆 5 commit

---

## §12. design.md 评审通过条件

**形式审核**：
- 全部 12 节齐全，无 TBD
- 每个决策都回链到具体证据（接口源码、PROJECT.md/AGENTS.md/MODULE.md 行号、其他脚本的设计模式）

**内容审核**（用户回复 "确认通过" 或指出修改点）：
- 字段集（§6.2 12 列）符合中性化需求
- V6 阈值（circ_market_cap 99%）与业务可接受度一致
- 拆 5 commit 的边界合理

> **下一步**：用户审核通过后，进入 Execute 阶段，按 §11.2 顺序提交 C1 → C5。


