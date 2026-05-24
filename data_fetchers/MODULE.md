# data_fetchers 模块规范

> 版本: v2.1
> 创建时间: 2026-05-19
> 更新时间: 2026-05-24
> 重构时间: 2026-05-24（补充目录结构+命名规则+公共模块规范+公共模块实现）

---

## 快速参考

### 必须遵守的约束

**遵循 PROJECT.md"输出数据规范"章节的跨模块通用原则：**
- 输出结构必须统一
- 字段值不可为 None
- 结果输出到 result 目录

**本模块特定约束（8条）：**

| # | 约束 | 说明 |
|---|------|------|
| 1 | 脚本命名：`fetch_<数据源>.py` | 如 fetch_turnover.py、fetch_main_inflow.py |
| 2 | 输出到 cache 目录 | 不输出到脚本同级目录 |
| 3 | 因子生成使用 factor_generator.py | 单一数据源，不分散 |
| 4 | 公共模块必须复用 | 禁止脚本自行实现已有功能 |
| 5 | pandas 3.0 使用 transform | 避免 rolling 返回 MultiIndex |
| 6 | 函数入口 DataFrame 先 copy() | 防止副作用 |
| 7 | 日志输出到 logs 目录 | 不散落在项目根目录 |
| 8 | 流程文档配套 | docs/<脚本名>_flow.md |

### 关键函数签名

| 函数 | 文件 | 用途 |
|------|------|------|
| `generate_all_factors(verbose)` | factor_generator.py | 生成所有因子数据 |
| `fetch_ohlcv_data(start_date, end_date)` | fetch_ohlcv.py（待创建） | 拉取 OHLCV 数据 |
| `fetch_turnover_data()` | fetch_turnover.py | 拉取换手率数据 |
| `fetch_main_inflow_data()` | fetch_main_inflow.py | 拉取主力资金流数据 |

---

## 目录结构

```
data_fetchers/
├── MODULE.md           # 本文件（模块规范）
├── common/             # 公共函数
│   ├── __init__.py
│   └── data_source_base.py  # 数据源基类（待创建）
│
├── docs/               # 流程文档
│   ├── factor_generator_flow.md
│   └── fetch_<数据源>_flow.md
│
├── result/             # 数据拉取结果输出（元信息）
│   └── .gitkeep
│
├── logs/               # 日志目录
│   └── .gitkeep
│
├── test_cases/         # 测试用例
│   ├── __init__.py
│   └── <脚本名>_test_cases.md
│
├── factor_generator.py # 统一因子生成入口
├── fetch_turnover.py   # 换手率数据拉取
├── fetch_main_inflow.py # 主力资金流数据拉取
├── fetch_stock_list.py # 股票列表拉取
├── fetch_float_mv.py   # 流通市值拉取
├── fetch_industry.py   # 行业分类拉取
└── fetch_factor_cache.py # 因子缓存管理
```

---

## 更新记录

1. v1.0（2026-05-19）：首次创建模块规范
2. v1.1（2026-05-24 15:22）：
   - 新增"统一因子生成模块"章节
   - 新增 factor_generator.py 规范
   - 新增 pandas 3.0 兼容性规范
3. v2.0（2026-05-24 17:59）：
   - **目录结构规范化**：创建 common/、docs/、result/、logs/、test_cases/
   - **补充快速参考表格**：8条约束 + 关键函数签名
   - **补充脚本命名规则**：`fetch_<数据源>.py`
   - **补充公共模块架构**：common/ 目录规范
   - **补充公共模块强制复用规范**
   - **补充输出目录规范**：result/、logs/ 目录职责
   - **补充版本历史**：记录每次变更
4. v2.1（2026-05-24 18:05）：
   - **创建公共模块**：paths.py、cache_manager.py、http_client.py、stock_utils.py
   - **公共模块架构更新**：从"待创建"状态改为"已实现"
   - **新增 common/README.md**：公共模块使用文档
5. v2.2（2026-05-24 20:35）：
   - **cache_manager.py 优化**：接收 logger 参数（遵循 PROJECT.md 第783-857行规范）
   - **新增 cache_manager.py 日志参数规范**：使用方式、参数类型、禁止行为
   - **JSON 解析异常处理**：避免内存翻倍（参考 backtest-module-optimization-patterns.md）
   - **参数类型支持**：`path` 支持 `Path | str`
6. v2.3（2026-05-24 21:10）：
   - **函数命名修复**：`_get_logger` → `get_module_logger`（遵循命名规范）
   - **get_cache_file_info 日志使用**：添加 DEBUG/WARNING 日志输出
   - **流程文档创建**：docs/cache_manager_flow.md
   - **测试用例创建**：test_cases/cache_manager_test_cases.md
7. v2.4（2026-05-24 21:40）：
   - **代码重复消除**：新增 `_read_cache_impl`、`_write_cache_impl` 公共函数
   - **文件类型判断优化**：新增 `_is_gzip_file` 函数统一判断
   - **重构读写函数**：read_gzip_cache/read_json_cache/write_gzip_cache/write_json_cache 调用公共实现
   - **append_to_cache 重构**：使用 `_is_gzip_file` 和公共实现函数
   - **代码行数减少**：从 322行 → 272行（减少 50行）
   - **流程文档更新**：版本历史 v1.2，架构图新增公共函数

---

## 概述

data_fetchers 模块负责：
1. 从外部数据源拉取因子数据、收益数据等
2. 统一因子生成（新增）
3. 存储到 cache 目录

**模块定位：**
- 输入：外部数据源（API、数据库等）+ 基础因子数据
- 输出：cache/factor_data/ 缓存文件

---

## 数据流程

```
外部数据源 → data_fetchers/ → cache/factor_data/ → factor_ic/
                   ↑
                   │
           factor_generator.py（统一因子生成）
```

**关键原则：**
- factor_ic 不自行拉取数据，只使用 cache
- data_fetchers 负责数据质量和格式转换
- **factor_generator.py 作为单一因子数据源（2026-05-24 新增）**

---

## 脚本命名规则

### 数据拉取脚本

**命名格式：** `fetch_<数据源名>.py`

| 脚本名 | 数据源 | 说明 |
|--------|--------|------|
| fetch_turnover.py | 换手率 | 拉取换手率数据 |
| fetch_main_inflow.py | 主力资金流 | 拉取主力流入流出数据 |
| fetch_stock_list.py | 股票列表 | 拉取 A 股股票列表 |
| fetch_float_mv.py | 流通市值 | 拉取流通市值数据 |
| fetch_industry.py | 行业分类 | 拉取行业分类数据 |

### 因子生成脚本

**命名格式：** `factor_generator.py`（统一入口）

---

## 公共模块架构

**目录规范：data_fetchers 下的公共模块放在 `data_fetchers/common/` 目录。**

禁止在脚本中重复实现已有公共功能，应复用 common 模块。

### 模块清单

| 模块 | 功能 | 核心函数 |
|------|------|----------|
| `paths.py` | 路径管理 | `get_cache_dir()`, `get_factor_data_dir()`, `get_stock_list_file()` |
| `cache_manager.py` | 缓存读写 | `read_gzip_cache()`, `write_gzip_cache()` |
| `http_client.py` | HTTP 客户端 | `create_retry_session()`, `create_eastmoney_session()` |
| `stock_utils.py` | 股票筛选 | `is_main_board_stock()`, `load_main_board_stock_list()` |

详细规范见 `data_fetchers/common/README.md`。

### 使用方式

```python
from data_fetchers.common import (
    get_cache_dir,
    read_gzip_cache,
    create_eastmoney_session,
    load_main_board_stock_list,
)

# 获取路径
cache_dir = get_cache_dir()

# 读取缓存
data = read_gzip_cache(cache_dir / 'factor_data/data.json.gz')

# 创建 HTTP Session
session = create_eastmoney_session()

# 加载主板股票列表
stocks = load_main_board_stock_list()
```

---

## 公共模块使用规范

### cache_manager.py 日志参数规范（2026-05-24 新增）

**遵循 PROJECT.md 第783-857行规范，公共模块接收 logger 参数。**

**使用方式：**
```python
from data_fetchers.common import read_gzip_cache
import logging

# 调用方传入 logger（推荐）
logger = logging.getLogger('factor_ic.ic_rsi_1d')
data = read_gzip_cache(cache_file, logger=logger)

# 不传 logger 时使用默认 logger（fallback）
data = read_gzip_cache(cache_file)  # 自动创建模块级 logger
```

**参数类型：**
- `path`: 支持 `Path | str`，内部统一转换为 Path
- `logger`: 可选，传入调用方的 logger 以追溯调用方

**禁止：**
```python
# ❌ 公共模块独立创建 logger（旧方式，已废弃）
# logger = logging.getLogger(__name__)  # 无法追溯调用方
```

**为何必须传入 logger：**
1. 日志可追溯调用方，便于定位问题
2. 符合 PROJECT.md 公共模块日志规范
3. 模块级 fallback logger 作为兼容方案

**JSON 解析异常处理：**
- 抛出 `ValueError` 而非 `json.JSONDecodeError`
- 避免传递完整 JSON 文档导致内存翻倍
- 参考 `references/backtest-module-optimization-patterns.md Section 1.2`

### paths.py 使用规范

### 强制规则

```
❌ 目录下有 common/ 公共模块，脚本仍手写相同逻辑
❌ 公共模块已封装缓存读写，脚本自行实现 gzip 解压 + JSON 加载
❌ 公共模块已封装 API 调用，脚本自行实现 requests 请求
```

### 正确做法

```
✅ 开发前先检查 common/ 是否有可复用函数
✅ 公共模块已封装的逻辑，直接调用，不重复实现
✅ 仅实现数据源特有的逻辑（API 参数、数据转换）
```

---

## 输出目录规范

### 缓存输出

**所有数据拉取结果输出到 cache 目录，不输出到脚本同级目录。**

| 数据类型 | 输出目录 | 文件格式 |
|----------|---------|----------|
| 因子数据 | `cache/factor_data/` | `factor_data_extended.json.gz` |
| 换手率数据 | `cache/` | `turnover_rate_data.json.gz` |
| 主力资金流 | `cache/` | `main_inflow_data.json.gz` |

**禁止：**
```
❌ 输出到脚本同级目录（散乱，难管理）
❌ 输出到 data_fetchers/result/（临时元信息才用）
```

### result 目录用途

`data_fetchers/result/` 用于存储：
- 数据拉取元信息（拉取时间、数据范围、行数）
- 数据质量报告（缺失字段统计、异常值检测）

### logs 目录用途

`data_fetchers/logs/` 用于存储：
- 数据拉取日志（API 调用记录、错误日志）
- 因子生成日志（计算进度、耗时统计）

**禁止：**
```
❌ 日志输出到项目根目录的 logs/（应输出到模块级 logs/）
❌ 日志文件与脚本同级（散乱，难管理）
```

---

## 统一因子生成模块

### factor_generator.py

**职责：** 生成所有因子数据到缓存，提供单一数据源。

**位置：** `data_fetchers/factor_generator.py`

**输出：** `cache/factor_data/factor_data_extended.json.gz`

### 支持的因子

| 因子 | 列名 | 参数 | 数据依赖 |
|------|------|------|---------|
| RSI | rsi_6 | period=6 | close |
| Volume_Ratio | volume_ratio_5 | window=5 | volume |
| Bollinger_PB | bollinger_pb | n=20, k=2.0 | close |
| KDJ_J | kdj_j | n=9, m1=3, m2=3 | close, high, low |
| Turnover_Surge | turnover_surge | window=5 | turnover_rate, close |

### 输出结构

```json
{
  "dates": ["2024-04-19", "2024-04-20", ...],
  "data": [
    {
      "date": "2024-04-19",
      "asset": "000001",
      "open": 10.71,
      "close": 10.69,
      "high": 10.82,
      "low": 10.66,
      "rsi_6": 64.42,
      "volume_ratio_5": 0.74,
      "bollinger_pb": null,
      "kdj_j": null,
      "turnover_surge": null
    },
    ...
  ]
}
```

### 使用方式

**CLI：**
```bash
python data_fetchers/factor_generator.py
```

**Python：**
```python
from data_fetchers.factor_generator import generate_all_factors

metadata = generate_all_factors(
    verbose=True  # 打印进度
)
```

### 数据一致性验证

factor_generator.py 的因子计算逻辑从 IC 脚本迁移：
- `calculate_bollinger_pb()` ← `ic_bollinger_pb_1d.py`
- `calculate_kdj_j()` ← `ic_kdj_j_1d.py`
- `calculate_turnover_surge()` ← `ic_turnover_surge_1d.py`

**验证结果（2026-05-24）：**
- 均值差异 < 0.000001
- 有效数据数一致
- 因子计算逻辑完全一致

---

## 缓存格式

### factor_data.json.gz（基础因子）

**结构：**
```json
{
  "dates": ["2024-04-19", ...],
  "data": [
    {
      "date": "2024-04-19",
      "asset": "000001",
      "open": 10.71,
      "close": 10.69,
      "high": 10.82,
      "low": 10.66,
      "rsi_6": 64.42,
      "volume_ratio_5": 0.74
    },
    ...
  ]
}
```

### factor_data_extended.json.gz（扩展因子）

包含所有 5 个因子（见上方输出结构）。

### turnover_rate_data.json.gz

**结构：**
```json
{
  "data": [
    {
      "date": "2024-03-19",
      "asset": "000001",
      "turnover_rate": 0.6664
    },
    ...
  ]
}
```

---

## 因子计算参数规范

### 参数默认值

| 因子 | 参数 | 默认值 | 说明 |
|------|------|--------|------|
| RSI | period | 6 | RSI 计算周期 |
| Volume_Ratio | window | 5 | 成交量均值窗口 |
| Bollinger_PB | n | 20 | 移动平均周期 |
| Bollinger_PB | k | 2.0 | 标差倍数 |
| KDJ_J | n | 9 | RSV 计算周期 |
| KDJ_J | m1 | 3 | K 值平滑周期 |
| KDJ_J | m2 | 3 | D 值平滑周期 |
| Turnover_Surge | window | 5 | 换手率均值窗口 |

### 计算规范

**遵循 PROJECT.md 规范：**
- 函数入口必须 `.copy()` 避免副作用
- 使用 `transform` 方法避免 pandas 3.0 索引问题
- 异常检测而非静默修正
- 使用 EPSILON 避免除零

---

## pandas 3.0 兼容性规范（2026-05-24 新增）

**问题：**
```python
# ❌ 错误：pandas 3.0 返回 MultiIndex Series
middle = factor_df.groupby('asset', group_keys=False)['close'].rolling(window=n).mean()
factor_df['middle'] = middle  # TypeError: incompatible index
```

**解决方案：**
```python
# ✓ 正确：使用 transform 返回 RangeIndex Series
middle = factor_df.groupby('asset', group_keys=False)['close'].transform(
    lambda x: x.rolling(window=n).mean()
)
factor_df['middle'] = middle  # 成功赋值
```

**原因：**
- pandas 3.0 中，`groupby(group_keys=False).rolling()` 返回 MultiIndex Series
- 即使 `group_keys=False`，索引仍是 MultiIndex
- `transform` 返回与原 DataFrame 一致的 RangeIndex

---

## 模块边界规范

**遵循 PROJECT.md 模块边界规范：**

```
✓ factor_generator.py 独立运行（不依赖 factor_ic、backtest）
✓ 输出到 cache/factor_data/
✓ 被 factor_ic 模块读取
```

**禁止：**
```
❌ factor_generator.py 导入 factor_ic.common.*
❌ factor_generator.py 导入 backtest.common.*
```

---

## 流程文档配套规范

**遵循 PROJECT.md"脚本配套文件规范"章节：**

| 文件类型 | 位置 | 命名规则 | 示例 |
|---------|------|---------|------|
| 流程文档 | `data_fetchers/docs/` | `<脚本名>_flow.md` | `factor_generator_flow.md` |
| 测试用例 | `data_fetchers/test_cases/` | `<脚本名>_test_cases.md` | `factor_generator_test_cases.md` |

**新建脚本时：**
```
□ 创建脚本文件（如 fetch_xxx.py）
□ 同步创建流程文档（docs/fetch_xxx_flow.md）
□ 同步创建测试用例（test_cases/fetch_xxx_test_cases.md）
```

---

## 待补充内容

```
□ 各脚本流程文档（docs/fetch_xxx_flow.md）
□ 各脚本测试用例（test_cases/fetch_xxx_test_cases.md）
□ 日期处理模块（common/date_utils.py，交易日判断、日期范围计算）
□ 数据验证模块（common/data_validator.py，字段完整性检查）
□ 增量更新策略规范
□ 数据质量检查自动化
□ 因子计算性能优化（大数据量测试）

✓ 公共模块实现（paths.py、cache_manager.py、http_client.py、stock_utils.py）- 已完成 2026-05-24
```

---

*最后更新: 2026-05-24 21:40*