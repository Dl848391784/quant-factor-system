# ic_tail_price_position.py 流程文档

> 版本: v1.0
> 创建时间: 2026-06-02
> 更新时间: 2026-06-02 16:30 北京时间

---

## 概述

**脚本用途：** 计算尾盘价格位置因子的 IC（信息系数），评估因子对次日收益的预测能力。

**因子定义：**
- 收盘价 = prices[-1]（尾盘最后一根K线收盘价，即15:00收盘价）
- 尾盘最高价 = tail_high（14:00-15:00期间的最高价）
- 尾盘最低价 = tail_low（14:00-15:00期间的最低价）
- 尾盘价格位置 = (收盘价 - 尾盘最低价) / (尾盘最高价 - 尾盘最低价)

**含义：**
- 值 = 0 → 收盘价等于尾盘最低价（尾盘弱势，收盘在区间底部）
- 值 = 1 → 收盘价等于尾盘最高价（尾盘强势，收盘在区间顶部）
- 值 = 0.5 → 收盘价在尾盘价格区间中间
- 值 > 0.5 → 收盘偏向高位（尾盘向上收敛）
- 值 < 0.5 → 收盘偏向低位（尾盘向下收敛）

**核心策略：**
1. 使用公共模块 `run_complex_factor_ic()`（遵循 PROJECT.md 强制复用规范）
2. 因子计算逻辑独立实现（`calculate_tail_price_position`）
3. 合并尾盘分钟级数据（tail_trading_data.json.gz）
4. 使用预计算的 tail_high 和 tail_low 字段

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
│ data()               │  │ position()           │
│ 加载 date/asset      │  │ 合并尾盘数据         │
│ 列                   │  │ 计算因子值           │
└──────────────────────┘  └──────────────────────┘
                                │
                                ▼
                        ┌──────────────────────┐
                        │ load_tail_trading_   │
                        │ data()               │
                        │ 加载尾盘分钟K线      │
                        │ 含 tail_high/tail_low│
                        └──────────────────────┘
```

---

## 流程步骤

### Step 1: CLI 参数解析

```python
parser = argparse.ArgumentParser(description='尾盘价格位置因子 IC 计算器')
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
    factor_name='tail_price_position',
    factor_col='tail_price_position',
    factor_cols=['date', 'asset'],  # 不需要 volume
    custom_factor_calculation=calculate_tail_price_position,
    min_stocks=args.min_stocks,
    force_full=args.force_full,
    _logger=logger
)
```

**关键参数：**
- `factor_cols=['date', 'asset']`: 只需要日期和资产代码
- `custom_factor_calculation`: 自定义因子计算函数

---

### Step 3: 合并尾盘数据

```python
def calculate_tail_price_position(factor_df):
    factor_df = factor_df.copy()
    tail_df = load_tail_trading_data()
    
    # 日期格式统一
    factor_df['date'] = pd.to_datetime(factor_df['date']).dt.strftime('%Y-%m-%d')
    tail_df['date'] = pd.to_datetime(tail_df['date']).dt.strftime('%Y-%m-%d')
    
    # 合并尾盘数据（按 date, asset）
    merged_df = factor_df.merge(
        tail_df[['date', 'asset', 'prices', 'tail_high', 'tail_low']],
        on=['date', 'asset'],
        how='left'
    )
```

**数据来源：**
- `factor_df`: 来自 factor_ic_data.json.gz（date, asset）
- `tail_df`: 来自 tail_trading_data.json.gz（date, asset, prices, tail_high, tail_low）

---

### Step 4: 计算因子值

```python
# 获取收盘价（prices[-1]）
def get_close_price(prices):
    if not isinstance(prices, list):
        return np.nan
    if len(prices) < 13:
        return np.nan
    return prices[-1]

merged_df['tail_close'] = merged_df['prices'].apply(get_close_price)

# 计算尾盘价格位置
def calc_price_position(close_price, tail_high, tail_low):
    if pd.isna(close_price) or pd.isna(tail_high) or pd.isna(tail_low):
        return np.nan
    price_range = tail_high - tail_low
    if abs(price_range) < EPSILON:
        return np.nan  # 价格区间为零，无位置意义
    return (close_price - tail_low) / price_range

merged_df['tail_price_position'] = merged_df.apply(
    lambda row: calc_price_position(row['tail_close'], row['tail_high'], row['tail_low']),
    axis=1
)
```

**边界处理：**
- `tail_high == tail_low` 时设为 NaN（价格区间为零）
- `prices` 数组长度不足 13 时设为 NaN（数据不完整）
- 理论范围：[0, 1]

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

## 数据依赖

|| 数据文件 | 字段 | 来源模块 |
||---------|------|----------|
|| factor_ic_data.json.gz | date, asset | data_fetchers/fetch_factor_cache.py |
|| tail_trading_data.json.gz | date, asset, prices, tail_high, tail_low | data_fetchers/fetch_tail_trading.py |

**tail_trading_data.json.gz 结构：**
```json
{
  "data": [
    {
      "date": "2026-06-01",
      "asset": "000001",
      "prices": [10.0, 10.1, ..., 11.0],  // 13根5分钟K线收盘价
      "volumes": [10000, 10000, ..., 10000],
      "tail_high": 11.2,  // 尾盘最高价
      "tail_low": 9.8     // 尾盘最低价
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

- **输出文件：** `factor_ic/result/ic_tail_price_position_1d_analysis_result.json`
- **输出目录：** 遵循 PROJECT.md H2 规则（`<模块>/result/`）

---

## IC 分析结果（2026-06-02）

| 指标 | 值 | 结论 |
|------|-----|------|
| ic_mean | -0.0613 | 反向因子 |
| ic_std | 0.0346 | - |
| ICIR | 1.77 | 优秀（>=1.0） |
| p_value | - | 统计显著 |
| 经济显著性 | 强 | |ic_mean|>=0.05 |
| 正比例 | 0.00% | IC 全部为负 |

---

## 版本历史

1. v1.0 (2026-06-02): 初始版本，创建流程文档
2. v1.1 (2026-06-02): 优化 - lint修复、测试文件创建（5个测试用例）
3. v1.2 (2026-06-02): 优化 - 抽取独立函数(get_close_price/calc_price_position)、公共模块复用(tail_data_loader)、异常处理注释补充、测试补充至13个