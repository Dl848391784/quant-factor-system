# fetch_market_cap 流程文档

> 版本: v1.0
> 创建时间: 2026-06-18 12:30 北京时间
> 更新时间: 2026-06-18 12:30 北京时间

---

## 概述

A 股日频市值数据拉取脚本。基于 akshare `ak.stock_value_em` 接口，按股票批量拉取覆盖目标
区间的日频市值快照（流通市值、总市值、PE/PB/PS/PEG 等 12 列），输出独立面板供后续市值
中性化（`ln(circ_market_cap)` 截面回归残差法）使用。

- **缓存路径**：`data_fetchers/result/market_cap_data.json.gz`
- **目标区间**：默认从 `factor_data.json.gz` 的 `meta.date_range` 推断（与因子面板对齐）
- **数据量级**：3026 stocks × ~545 days × 12 cols ≈ 1.65M rows，gzip 后预估 ~150 MB
- **运行时长**：BATCH_SIZE=250，13 批，max_workers=4，预计 30-50 分钟

---

## 目录

1. [数据结构](#数据结构)
2. [核心流程](#核心流程)
3. [函数接口](#函数接口)
4. [CLI 参数](#cli-参数)
5. [错误处理](#错误处理)
6. [验证方法](#验证方法)
7. [版本历史](#版本历史)

---

## 数据结构

### 输出文件 schema

```json
{
  "meta": {
    "version": "1.0",
    "source": "akshare.stock_value_em",
    "generated_at": "2026-06-18T12:30:00",
    "n_days": 545,
    "n_assets": 3026,
    "n_records": 1649170,
    "date_range": {
      "start": "2024-03-18",
      "end": "2026-06-17",
      "target_start": "2024-03-18",
      "target_end": "2026-06-17"
    },
    "fetch_stats": {
      "total_success": 3020,
      "total_fail": 6,
      "fail_rate": 0.002,
      "elapsed_seconds": 1842.35,
      "total_batches": 13
    },
    "field_units": {
      "total_market_cap": "元",
      "circ_market_cap": "元",
      "total_shares": "股",
      "circ_shares": "股"
    },
    "circ_market_cap_non_null_rate": 0.9994
  },
  "data": [
    {
      "date": "2024-03-18",
      "asset": "000001",
      "total_market_cap": 1.0e10,
      "circ_market_cap": 8.0e9,
      "total_shares": 1.0e9,
      "circ_shares": 8.0e8,
      "pe_ttm": 12.5,
      "pe_lyr": 13.0,
      "pb": 1.5,
      "peg": 0.8,
      "pcf_ttm": 9.5,
      "ps_ttm": 2.5
    }
  ]
}
```

### 字段定义（12 列输出）

| 列名 | 类型 | 单位 | 来源（akshare 中文列） | 说明 |
|---|---|---|---|---|
| date | str | YYYY-MM-DD | 数据日期 | ISO 日期 |
| asset | str | — | （由 symbol 注入） | 6 位股票代码 |
| total_market_cap | float | 元 | 总市值 | 当日总市值 |
| circ_market_cap | float | 元 | 流通市值 | **市值中性化主用字段** |
| total_shares | float | 股 | 总股本 | 总股本（含限售） |
| circ_shares | float | 股 | 流通股本 | 流通股本 |
| pe_ttm | float | 倍 | PE(TTM) | TTM 市盈率 |
| pe_lyr | float | 倍 | PE(静) | 静态市盈率 |
| pb | float | 倍 | 市净率 | 市净率 |
| peg | float | 倍 | PEG值 | PEG 值 |
| pcf_ttm | float | 倍 | 市现率 | TTM 市现率 |
| ps_ttm | float | 倍 | 市销率 | TTM 市销率 |

> **删除字段**：原 13 列中的"当日收盘价"和"当日涨跌幅"已存在于 `factor_data.json.gz`，
> 不在本面板冗余保存（详见 design.md §6.3）。

---

## 核心流程

### 顶层编排（main）

```
                ┌──────────────────────────────────────┐
                │ 1. _read_factor_data_date_range()    │
                │    从 factor_data.json.gz 读 meta    │
                │    → target_date_range = (s, e)      │
                └────────────────┬─────────────────────┘
                                 │
                ┌────────────────▼─────────────────────┐
                │ 2. load_target_assets()               │
                │    读 stock_list.json，过滤 ST 前缀   │
                │    → symbols: list[str] (3026)        │
                └────────────────┬─────────────────────┘
                                 │
                ┌────────────────▼─────────────────────┐
                │ 3. 切批 BATCH_SIZE=250 → 13 批       │
                └────────────────┬─────────────────────┘
                                 │
                ┌────────────────▼─────────────────────┐
                │ 4. for each batch:                    │
                │      fetch_batch (4 并发)             │
                │       └─ fetch_one_stock × 250        │
                │           ├─ ak.stock_value_em()      │
                │           ├─ _normalize_fields()      │
                │           └─ _clip_to_target_range()  │
                │      save_batch_cache(.partN.json.gz) │
                └────────────────┬─────────────────────┘
                                 │
                ┌────────────────▼─────────────────────┐
                │ 5. merge_and_emit_final()             │
                │    glob batch_*.json.gz → concat      │
                │    去重 (date, asset) → 计算 meta     │
                │    原子写 market_cap_data.json.gz     │
                │    清理批次缓存                       │
                └────────────────┬─────────────────────┘
                                 │
                ┌────────────────▼─────────────────────┐
                │ 6. validate_final_data() V1-V7        │
                │    覆盖率/非空率/数值类型 sanity      │
                └────────────────┬─────────────────────┘
                                 │
                ┌────────────────▼─────────────────────┐
                │ 7. 总失败率 > 5% → exit 1             │
                │    其它情况 exit 0                    │
                └──────────────────────────────────────┘
```

### 关键控制点

| 阶段 | 控制点 | 阈值 / 决策 |
|---|---|---|
| fetch_one_stock | 重试 | 网络异常指数退避 ≤ 3 次；ValueError 直接上抛（数据契约错） |
| fetch_batch | 单批失败率 | > 50% 标记批次失败（df=None），但**继续**后续批次 |
| merge | 去重策略 | 按 (date, asset) 保留首条，记 warning |
| validate | V5 覆盖率 | ≥ 95%（按 stock_list 计） |
| validate | V6 非空率 | circ_market_cap ≥ 99% |
| main | 总失败率 | > 5% 退出 1 |

---

## 函数接口

### 公开 API（`__all__`）

| 函数 | 类型 | 用途 |
|---|---|---|
| `main` | 顶层编排 | CLI 入口，返回退出码 0/1 |
| `load_target_assets` | 数据加载 | 读 stock_list.json 过滤 ST |
| `fetch_one_stock` | 网络层 | 拉单股 + 归一化 + 区间裁剪，含重试 |
| `fetch_batch` | 并发层 | ThreadPool 拉一批，返回 (df, success, fail) |
| `save_batch_cache` | IO 层 | 单批落盘（原子写） |
| `merge_and_emit_final` | IO 层 | N 批合并 + meta 计算 + 原子写最终文件 |
| `validate_final_data` | 校验层 | V1-V7 数据质量校验 |

### 关键签名

```python
def fetch_one_stock(
    symbol: str,
    target_date_range: tuple[str, str],
    max_retries: int = MAX_RETRIES,
    logger_arg: logging.Logger | None = None,
) -> pd.DataFrame | None: ...

def fetch_batch(
    symbols: list[str],
    batch_idx: int,
    total_batches: int,
    target_date_range: tuple[str, str],
    max_workers: int = 4,
    logger_arg: logging.Logger | None = None,
) -> tuple[pd.DataFrame | None, int, int]: ...

def merge_and_emit_final(
    total_batches: int,
    target_date_range: tuple[str, str],
    total_success: int,
    total_fail: int,
    elapsed_seconds: float,
    result_dir: Path | None = None,
    logger_arg: logging.Logger | None = None,
) -> int: ...

def validate_final_data(
    output_file: Path | None = None,
    logger_arg: logging.Logger | None = None,
) -> tuple[bool, int, int, int]: ...
```

---

## CLI 参数

```bash
python data_fetchers/fetch_market_cap.py [--start YYYY-MM-DD --end YYYY-MM-DD]
```

| 参数 | 必填 | 默认 | 说明 |
|---|---|---|---|
| `--start` | 否 | None | 起始日期；不传则从 factor_data.json.gz 读取 |
| `--end` | 否 | None | 结束日期；不传则从 factor_data.json.gz 读取 |

> `--start` 与 `--end` 必须**同时**提供或同时不提供，否则参数错误退出。

### 模块级常量

| 常量 | 值 | 说明 |
|---|---|---|
| `BATCH_SIZE` | 250 | 单批股票数 |
| `MAX_WORKERS` | 4 | ThreadPoolExecutor 并发数 |
| `MAX_RETRIES` | 3 | 单股最大重试次数 |
| `RETRY_BACKOFF_BASE` | 1.0s | 指数退避基数 |
| `REQUEST_INTERVAL` | 0.1s | 单请求间隔（节流） |
| `BATCH_FAIL_RATE_THRESHOLD` | 0.5 | 单批失败率阈值 |
| `TOTAL_FAIL_RATE_THRESHOLD` | 0.05 | 总失败率阈值 |
| `MIN_STOCK_COVERAGE` | 0.95 | 验证：股票覆盖率下限 |
| `MIN_KEY_FIELD_NON_NULL_RATE` | 0.99 | 验证：circ_market_cap 非空率下限 |

---

## 错误处理

### 异常分类与处理矩阵

| 异常类型 | 来源 | 处理 |
|---|---|---|
| `ConnectionError` / `Timeout` | akshare 网络层 | 指数退避重试 ≤ 3 次，仍失败则 skip + warning |
| `ValueError` (缺列 / 区间逆序) | `_normalize_fields` / `_clip_to_target_range` | **不重试**，直接上抛；fetch_batch 捕获并记 fail |
| `FileNotFoundError` (factor_data) | `_read_factor_data_date_range` | main 捕获 → 返回 1 |
| `FileNotFoundError` (stock_list) | `load_target_assets` | main 捕获 → 返回 1 |
| `KeyError` (meta.date_range) | `_read_factor_data_date_range` | main 捕获 → 返回 1 |
| 单批失败率 > 50% | `fetch_batch` | 返回 (None, succ, fail)；main 记录但**继续**下一批 |
| 总失败率 > 5% | `main` 末尾 | 校验仍跑完，最终退出 1 |
| V1-V7 任一失败 | `validate_final_data` | 返回 1 |

### 退出码（遵循 AGENTS.md 规则 #6）

| 码 | 含义 | 触发条件 |
|---|---|---|
| 0 | 成功 | 全部校验通过且总失败率 ≤ 5% |
| 1 | 运行时错误 | 上游文件缺失 / 总失败率超阈 / V1-V7 失败 |
| 2 | 配置或导入错误 | import 失败 / paths 常量缺失（外层捕获） |

---

## 验证方法

### 内置 V1-V7（validate_final_data）

| 项 | 校验内容 | 阈值/规则 |
|---|---|---|
| V1 | 文件存在 + gzip+json 解析成功 | — |
| V2 | 顶层 keys 含 meta + data 且 data 非空 | — |
| V3 | 12 列字段齐全 | _OUTPUT_COLUMNS |
| V4 | (date, asset) 唯一 | dup_count == 0 |
| V5 | 股票覆盖率 | ≥ 95%（stock_list 缺失时降级 warning 跳过） |
| V6 | circ_market_cap 非空率 | ≥ 99% |
| V7 | 市值/股本字段 > 0 | 非 NaN 数值不应 ≤ 0 |

### 手工命令行抽查

```bash
# 总记录数 + 字段
zcat data_fetchers/result/market_cap_data.json.gz \
  | python -c "import json,sys; d=json.load(sys.stdin); \
    print('n_records:', d['meta']['n_records']); \
    print('n_assets:', d['meta']['n_assets']); \
    print('n_days:', d['meta']['n_days']); \
    print('cols:', list(d['data'][0].keys()))"

# 单股切片
zcat data_fetchers/result/market_cap_data.json.gz \
  | python -c "import json,sys,pandas as pd; d=json.load(sys.stdin); \
    df=pd.DataFrame(d['data']); print(df[df['asset']=='000001'].head())"
```

### 单元测试

```bash
python -m pytest data_fetchers/test_cases/test_fetch_market_cap.py -v
# 34 passed
```

测试覆盖：
- 9.2 Unit (18 项基线 + 16 项扩展) = 34
- 9.3 Integration（标 `@pytest.mark.network`） — 暂未实现
- 9.4 Validation（数据采集后跑） — 暂未实现

---

## 版本历史

| 版本 | 日期 | 修改人 | 变更 |
|---|---|---|---|
| v1.0 | 2026-06-18 | 云瑶 | 初始版本：完整实现 9 个函数 + 34 单测；批 250 + 并发 4 + 失败率 5% 阈值 |
