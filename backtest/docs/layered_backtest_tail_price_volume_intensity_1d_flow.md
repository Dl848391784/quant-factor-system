# 尾盘量价强度因子分层回测流程文档

**创建日期**: 2026-06-02
**因子名称**: tail_price_volume_intensity_1d
**因子方向**: 从 IC 文件派生（反向因子，ic_mean=-0.0918）

---

## 1. 因子概述

### 1.1 因子定义

尾盘量价强度因子衡量尾盘（14:00-15:00）价格变化与成交量关系：

```
尾盘涨跌幅 = (prices[-1] - prices[0]) / prices[0]
尾盘量比 = sum(volumes) / volume（尾盘成交量 / 全天成交量）
尾盘量价强度 = 尾盘涨跌幅 × 尾盘量比
```

其中：
- prices: 13根5分钟K线收盘价（14:00-15:00）
- volumes: 13根5分钟K线成交量
- volume: 全天成交量

### 1.2 因子特性

| 特性 | 描述 |
|------|------|
| 理论范围 | 无界（可正可负） |
| 含义 | 尾盘资金流向强度 |
| 正值含义 | 尾盘上涨+放量（资金流入） |
| 负值含义 | 尾盘下跌+放量（资金流出） |
| 绝对值大含义 | 尾盘量价异动显著 |

### 1.3 IC 分析结果

来源：`factor_ic/result/ic_tail_price_volume_intensity_1d_analysis_result.json`

| 指标 | 值 | 结论 |
|------|-----|------|
| ic_mean | -0.0918 | 反向因子 |
| ic_std | 0.128 | - |
| ICIR | 0.72 | 可用（>=0.5） |
| p_value | 0.0094 | 统计显著（<0.05） |
| 经济显著性 | 强 | |ic_mean|>=0.05 |

**结论**: 反向因子，分层回测做多低值组、做空高值组。

---

## 2. 分层配置

### 2.1 分层方式

```python
layer_method = 'percentile'  # percentile 分层
n_layers = 5                 # 5层（每层20%）
```

**分层定义**:

| Layer | 百分位范围 | 名称 | 含义 |
|-------|-----------|------|------|
| 1 | 0-20% | 极低层 | 量价强度最小 |
| 2 | 20-40% | 偏低层 | 量价强度较小 |
| 3 | 40-60% | 正常层 | 量价强度适中 |
| 4 | 60-80% | 偏高层 | 量价强度较大 |
| 5 | 80-100% | 极高层 | 量价强度最大 |

### 2.2 多空组合

因子方向为反向（ic_mean=-0.0918<0），多空组合由基类自动派生：

- **做多**: 极低层（量价强度最小）
- **做空**: 极高层（量价强度最大）

逻辑：低量价强度股票（尾盘无异动）表现更好。

### 2.3 其他参数

| 参数 | 值 | 说明 |
|------|-----|------|
| trade_cost_rate | 0.003 | 交易成本 0.3% |
| min_stocks_per_layer | 10 | 每层最小股票数 |

---

## 3. 数据加载

### 3.1 数据来源

| 数据文件 | 字段 | 来源模块 |
|---------|------|----------|
| factor_ic_data.json.gz | date, asset, volume, forward_return_1d | data_fetchers/fetch_factor_cache.py |
| tail_trading_data.json.gz | date, asset, prices, volumes | data_fetchers/fetch_tail_trading.py |

### 3.2 因子计算

使用 `factor_ic.ic_tail_price_volume_intensity.calculate_tail_price_volume_intensity` 函数：

```python
# 合并尾盘数据
merged_df = factor_df.merge(
    tail_df[['date', 'asset', 'prices', 'volumes']],
    on=['date', 'asset'],
    how='left'
)

# 计算尾盘涨跌幅
tail_price_change = (prices[-1] - prices[0]) / prices[0]

# 计算尾盘量比
tail_volume_ratio = sum(volumes) / volume

# 计算量价强度
tail_price_volume_intensity = tail_price_change * tail_volume_ratio
```

---

## 4. 回测流程

### 4.1 整体架构

```
┌─────────────────────────────────────────────────────────────┐
│                    factor_cli_main()                         │
│  1. CLI 参数解析                                             │
│  2. 调用 run_layered_backtest                                │
│  3. 输出结果摘要                                             │
└─────────────────────────────────────────────────────────────┘
        │
        ▼
┌─────────────────────────────────────────────────────────────┐
│              run_layered_backtest()                          │
│  1. 加载因子数据 + 计算因子值                                 │
│  2. 分层（percentile 5层）                                    │
│  3. 计算每层收益                                             │
│  4. 计算多空组合收益                                         │
│  5. 保存结果                                                 │
└─────────────────────────────────────────────────────────────┘
```

### 4.2 CLI 入口

```bash
python backtest/layered_backtest_tail_price_volume_intensity_1d.py
```

可选参数：
- `--force-full`: 强制全量计算（跳过缓存）
- `--min-stocks`: 每层最小股票数（默认10）

---

## 5. 输出结构

### 5.1 输出文件

- **输出路径**: `backtest/result/layered_backtest_tail_price_volume_intensity_1d_result.json`

### 5.2 输出字段

```json
{
  "factor_name": "tail_price_volume_intensity_1d",
  "layer_stats": {
    "lowest": {"annual_return": "...", "sharpe": "..."},
    "lower": {...},
    "normal": {...},
    "higher": {...},
    "highest": {...}
  },
  "long_short": {
    "annual_return": "...",
    "sharpe": "..."
  },
  "period": {"start": "...", "end": "..."}
}
```

---

## 6. 版本历史

1. v1.0 (2026-06-02): 初始版本，创建流程文档