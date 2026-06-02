# ic_tail_price_slope_1d.py 流程文档

> 版本: v1.3
> 创建时间: 2026-06-02
> 更新时间: 2026-06-02 17:30 北京时间

---

## 概述

**脚本用途：** 计算尾盘价格趋势斜率因子的 IC（信息系数），评估因子对次日收益的预测能力。

**因子定义：**
- 线性回归：对 prices 数组（13根5分钟K线收盘价）做回归
- 百分比斜率：factor_value = slope / mean_price

**公式：**
```python
import numpy as np

prices = [10.0, 10.1, ..., 11.0]  # 13根K线收盘价
X = np.arange(13)  # 时间索引: 0, 1, 2, ..., 12
Y = np.array(prices)

slope, intercept = np.polyfit(X, Y, 1)
mean_price = np.mean(prices)
factor_value = slope / mean_price  # 百分比斜率
```

**含义：**
- tail_price_slope > 0：尾盘价格上涨趋势
- tail_price_slope < 0：尾盘价格下跌趋势
- |tail_price_slope| 越大：趋势越强劲

**归一化处理：**
- 使用百分比斜率（slope / mean_price）
- 消除高价股和低价股的量纲差异
- 与 forward_return（百分比形式）可比

**核心策略：**
1. 使用公共模块 `run_complex_factor_ic()`（遵循 PROJECT.md 强制复用规范）
2. 因子计算逻辑独立实现（`calculate_tail_price_slope`）
3. 合并尾盘分钟级数据（tail_trading_data.json.gz）

---

## 整体架构

```
┌─────────────────────────────────────────────────────────────┐
│                      main()                                  │
│  1. CLI 参数解析                                             │
│  2. 调用公共模块主入口                                        │
│  3. 输出结果摘要                                             │
└─────────────────────────────────────────────────────────────┘
        │
        ▼
┌─────────────────────────────────────────────────────────────┐
│              run_complex_factor_ic()                         │
│  1. 判断模式（全量/增量/跳过）                                │
│  2. 加载因子数据（factor_ic_data.json.gz）                   │
│  3. 执行自定义因子计算                                        │
│  4. 计算 IC + 五维度判断                                      │
│  5. 构建输出结构                                             │
│  6. 保存结果                                                 │
└─────────────────────────────────────────────────────────────┘
        │                    │
        ▼                    ▼
┌──────────────────────┐  ┌──────────────────────┐
│ load_factor_return_  │  │ calculate_tail_price_│
│ data()               │  │ slope()              │
│ 加载 date/asset      │  │ 合并尾盘数据         │
│ 列                   │  │ 计算线性回归斜率     │
└──────────────────────┘  └──────────────────────┘
                                │
                                ▼
                        ┌──────────────────────┐
                        │ load_tail_trading_   │
                        │ data()               │
                        │ 加载尾盘分钟K线      │
                        └──────────────────────┘
```

---

## 流程步骤

### Step 1: CLI 参数解析

```python
parser = argparse.ArgumentParser(description='尾盘价格趋势斜率因子 IC 计算器')
parser.add_argument('--force-full', action='store_true', help='强制全量计算')
parser.add_argument('--min-stocks', type=int, default=DEFAULT_MIN_STOCKS, help='最小股票数')
```

**参数说明：**
- `--force-full`: 强制全量计算（跳过增量模式）
- `--min-stocks`: 每日最小股票数阈值（默认 10）

---

### Step 2: 加载因子数据

```python
result = run_complex_factor_ic(
    factor_name='tail_price_slope',
    factor_col='tail_price_slope',
    factor_cols=['date', 'asset'],  # 只需要基础列
    custom_factor_calculation=calculate_tail_price_slope,
    min_stocks=args.min_stocks,
    force_full=args.force_full,
    _logger=logger
)
```

**关键参数：**
- `factor_cols=['date', 'asset']`: 只需要基础列，不需要 volume
- `custom_factor_calculation`: 自定义因子计算函数

---

### Step 3: 合并尾盘数据

```python
def calculate_tail_price_slope(factor_df):
    factor_df = factor_df.copy()
    tail_df = load_tail_trading_data()
    
    # 日期格式统一
    factor_df['date'] = pd.to_datetime(factor_df['date']).dt.strftime('%Y-%m-%d')
    tail_df['date'] = pd.to_datetime(tail_df['date']).dt.strftime('%Y-%m-%d')
    
    # 合并尾盘数据（按 date, asset）
    merged_df = factor_df.merge(
        tail_df[['date', 'asset', 'prices']],
        on=['date', 'asset'],
        how='left'
    )
```

**数据来源：**
- `factor_df`: 来自 factor_ic_data.json.gz（date, asset）
- `tail_df`: 来自 tail_trading_data.json.gz（date, asset, prices）

---

### Step 4: 计算因子值

```python
def calc_slope(prices):
    """计算百分比斜率"""
    # 处理 NaN/None
    if not isinstance(prices, list):
        return np.nan
    if len(prices) < 13:
        return np.nan
    
    # 转换为 numpy 数组
    Y = np.array(prices)
    
    # 检查数据污染
    if np.any(np.isnan(Y)):
        return np.nan
    
    # 时间索引
    X = np.arange(13)
    
    # 线性回归
    slope, intercept = np.polyfit(X, Y, 1)
    
    # 计算均价
    mean_price = np.mean(Y)
    
    # 除零防护
    if abs(mean_price) < EPSILON:
        return np.nan
    
    # 百分比斜率
    factor_value = slope / mean_price
    return factor_value

merged_df['tail_price_slope'] = merged_df['prices'].apply(calc_slope)
```

**边界处理：**
- `prices` 数组长度不足 13 时设为 NaN（数据不完整）
- `mean_price` 接近零时设为 NaN（除零防护）
- `prices` 包含 NaN 值时返回 NaN（数据污染）

---

### Step 5: 计算 IC + 五维度判断

由公共模块 `ic_calculator.py` 自动执行：
1. 计算 IC 序列（逐日 Spearman 相关性）
2. 统计显著性判断（Newey-West t检验）
3. 因子方向判断（IC 均值符号）
4. 经济显著性判断（|IC均值| >= 0.03/0.05）
5. ICIR 稳定性判断（|ICIR| >= 0.5/1.0/2.0）
6. IC 分布一致性判断（正比例与方向关系）

---

### Step 6: 构建输出结构

由公共模块 `ic_result_builder.py` 自动构建，输出结构符合 MODULE.md 规范：

```json
{
  "factor_name": "tail_price_slope",
  "calculation_date": "<ISO时间>",
  "period": {"start": "<str>", "end": "<str>", "description": "<str>"},
  "ic_metrics": {"ic_mean": <float>, "ic_std": <float>, "icir": <float>, ...},
  "sample_stats": {"total_days": <int>, "valid_days": <int>, ...},
  "statistical_significance": {...},
  "factor_direction": {...},
  "economic_significance": {...},
  "icir_stability": {...},
  "ic_distribution_consistency": {...},
  "dates": ["<日期列表>"],
  "ic_values": [<IC值列表>],
  "rolling_ic_mean": [<滚动均值列表>],
  ...
}
```

---

## 数据依赖

| 数据文件 | 字段 | 来源模块 |
|---------|------|----------|
| factor_ic_data.json.gz | date, asset | data_fetchers/fetch_factor_cache.py |
| tail_trading_data.json.gz | date, asset, prices | data_fetchers/fetch_tail_trading.py |

**tail_trading_data.json.gz 结构：**
```json
{
  "data": [
    {
      "date": "2026-06-01",
      "asset": "000001",
      "prices": [10.0, 10.1, ..., 11.0]  // 13根5分钟K线收盘价（14:00-15:00）
    }
  ]
}
```

---

## 配置参数

| 参数 | 默认值 | 说明 |
|------|--------|------|
| DEFAULT_MIN_STOCKS | 10 | 每日最小股票数阈值 |
| EPSILON | 1e-10 | 除零防护阈值 |

---

## 输出位置

- **输出文件：** `factor_ic/result/ic_tail_price_slope_1d_analysis_result.json`
- **输出目录：** 遵循 PROJECT.md H2 规则（`<模块>/result/`）

---

## 测试覆盖

- **测试文件：** `factor_ic/test_cases/test_ic_tail_price_slope_1d.py`
- **覆盖场景：**
  - 正常计算（上涨趋势）
  - 正常计算（下跌趋势）
  - 除零防护（mean_price = 0）
  - 数据不完整防护（prices 长度不足）
  - 数据污染防护（prices 包含 NaN）
  - 文件不存在异常

---

## 版本历史

1. v1.0 (2026-06-02): 初始版本，创建流程文档
2. v1.1 (2026-06-02): Round 1 优化 - 导入分组注释、main()返回值、版本历史完善
3. v1.2 (2026-06-02): Round 2 优化 - 内部函数类型注解、未使用变量清理、docstring Example 完善
4. v1.3 (2026-06-02): Round 3 优化 - 线性回归异常捕获精细化（LinAlgError/ValueError）