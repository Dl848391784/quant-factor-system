# ic_tail_price_volume_intensity.py 流程文档

> 版本: v1.0
> 创建时间: 2026-06-02
> 更新时间: 2026-06-02 16:00 北京时间

---

## 概述

**脚本用途：** 计算尾盘量价强度因子的 IC（信息系数），评估因子对次日收益的预测能力。

**因子定义：**
- 尾盘涨跌幅 = (prices[-1] - prices[0]) / prices[0]
- 尾盘量比 = sum(volumes) / volume（尾盘成交量 / 全天成交量）
- 尾盘量价强度 = 尾盘涨跌幅 × 尾盘量比

**含义：**
- 正值 → 尾盘上涨且成交量放大（资金流入）
- 负值 → 尾盘下跌且成交量放大（资金流出）
- 绝对值大 → 尾盘量价异动显著

**核心策略：**
1. 使用公共模块 `run_complex_factor_ic()`（遵循 PROJECT.md 强制复用规范）
2. 因子计算逻辑独立实现（`calculate_tail_price_volume_intensity`）
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
│ data()               │  │ volume_intensity()   │
│ 加载 date/asset/     │  │ 合并尾盘数据         │
│ volume 列            │  │ 计算因子值           │
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
parser = argparse.ArgumentParser(description='尾盘量价强度因子 IC 计算器')
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
    factor_name='tail_price_volume_intensity',
    factor_col='tail_price_volume_intensity',
    factor_cols=['date', 'asset', 'volume'],  # 需要 volume 字段
    custom_factor_calculation=calculate_tail_price_volume_intensity,
    min_stocks=args.min_stocks,
    force_full=args.force_full,
    _logger=logger
)
```

**关键参数：**
- `factor_cols=['date', 'asset', 'volume']`: 需要全天成交量 volume
- `custom_factor_calculation`: 自定义因子计算函数

---

### Step 3: 合并尾盘数据

```python
def calculate_tail_price_volume_intensity(factor_df):
    factor_df = factor_df.copy()
    tail_df = load_tail_trading_data()
    
    # 日期格式统一
    factor_df['date'] = pd.to_datetime(factor_df['date']).dt.strftime('%Y-%m-%d')
    tail_df['date'] = pd.to_datetime(tail_df['date']).dt.strftime('%Y-%m-%d')
    
    # 合并尾盘数据（按 date, asset）
    merged_df = factor_df.merge(
        tail_df[['date', 'asset', 'prices', 'volumes']],
        on=['date', 'asset'],
        how='left'
    )
```

**数据来源：**
- `factor_df`: 来自 factor_ic_data.json.gz（date, asset, volume）
- `tail_df`: 来自 tail_trading_data.json.gz（date, asset, prices, volumes）

---

### Step 4: 计算因子值

```python
# 计算尾盘涨跌幅
def calc_price_change(prices):
    if not isinstance(prices, list):
        return np.nan
    if len(prices) < 13:
        return np.nan
    first_price = prices[0]
    last_price = prices[-1]
    if abs(first_price) < EPSILON:
        return np.nan
    return (last_price - first_price) / first_price

merged_df['tail_price_change'] = merged_df['prices'].apply(calc_price_change)

# 计算尾盘量比
def calc_volume_ratio(volumes, total_volume):
    if not isinstance(volumes, list):
        return np.nan
    if len(volumes) < 13:
        return np.nan
    if total_volume is None or pd.isna(total_volume) or abs(total_volume) < EPSILON:
        return np.nan
    tail_volume = sum(volumes)
    return tail_volume / total_volume

merged_df['tail_volume_ratio'] = merged_df.apply(
    lambda row: calc_volume_ratio(row['volumes'], row['volume']),
    axis=1
)

# 计算尾盘量价强度
merged_df['tail_price_volume_intensity'] = (
    merged_df['tail_price_change'] * merged_df['tail_volume_ratio']
)
```

**边界处理：**
- `prices[0]` 接近零时设为 NaN（除零防护）
- `volume` 接近零时设为 NaN（除零防护）
- `volumes` 数组长度不足 13 时设为 NaN（数据不完整）

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
  "factor_name": "tail_price_volume_intensity",
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

|| 数据文件 | 字段 | 来源模块 |
||---------|------|----------|
|| factor_ic_data.json.gz | date, asset, volume | data_fetchers/fetch_factor_cache.py |
|| tail_trading_data.json.gz | date, asset, prices, volumes | data_fetchers/fetch_tail_trading.py |

**tail_trading_data.json.gz 结构：**
```json
{
  "data": [
    {
      "date": "2026-06-01",
      "asset": "000001",
      "prices": [10.0, 10.1, ..., 11.0],  // 13根5分钟K线收盘价
      "volumes": [10000, 10000, ..., 10000]  // 13根5分钟K线成交量
    }
  ]
}
```

---

## 配置参数

|| 参数 | 默认值 | 说明 |
||------|--------|------|
|| DEFAULT_MIN_STOCKS | 10 | 每日最小股票数阈值 |
|| EPSILON | 1e-10 | 除零防护阈值 |

---

## 输出位置

- **输出文件：** `factor_ic/result/ic_tail_price_volume_intensity_1d_analysis_result.json`
- **输出目录：** 遵循 PROJECT.md H2 规则（`<模块>/result/`）

---

## 测试覆盖

- **测试文件：** `factor_ic/test_cases/test_ic_tail_price_volume_intensity.py`
- **覆盖场景：**
  - 正常计算
  - 除零防护（prices[0] = 0）
  - 除零防护（volume = 0）
  - 数据不完整防护（volumes 长度不足）
  - 文件不存在异常

---

## 版本历史

1. v1.0 (2026-06-02): 初始版本，创建流程文档