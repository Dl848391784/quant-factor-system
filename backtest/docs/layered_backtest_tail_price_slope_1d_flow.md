# 尾盘价格趋势斜率因子分层回测流程文档

**创建日期**: 2026-06-02
**因子名称**: tail_price_slope_1d
**因子方向**: 从 IC 文件派生（反向因子，ic_mean=-0.0822）

---

## 1. 因子概述

### 1.1 因子定义

尾盘价格趋势斜率因子衡量尾盘（14:00-15:00）价格线性趋势：

```
prices = 13根5分钟K线收盘价
X = np.arange(13)  # 时间索引: 0, 1, 2, ..., 12
Y = np.array(prices)

slope, _ = np.polyfit(X, Y, 1)  # 线性回归斜率
mean_price = np.mean(prices)
factor_value = slope / mean_price  # 百分比斜率
```

其中：
- prices: 13根5分钟K线收盘价（14:00-15:00）
- slope: 线性回归斜率（价格随时间变化率）
- mean_price: 均价（归一化基准）

### 1.2 因子特性

| 特性 | 描述 |
|------|------|
| 理论范围 | 无界（可正可负） |
| 含义 | 尾盘价格趋势方向与强度 |
| 正值含义 | 尾盘价格上涨趋势 |
| 负值含义 | 尾盘价格下跌趋势 |
| 绝对值大含义 | 尾盘趋势强劲 |

### 1.3 IC 分析结果

来源：`factor_ic/result/ic_tail_price_slope_1d_analysis_result.json`

| 指标 | 值 | 结论 |
|------|-----|------|
| ic_mean | -0.0822 | 反向因子 |
| ic_std | 0.1631 | - |
| ICIR | 0.5038 | 可用（>=0.5） |
| p_value | - | 统计显著 |
| 经济显著性 | 弱 | |ic_mean|>=0.03 |

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
| 1 | 0-20% | 极低层 | 趋势斜率最小，下跌趋势最明显 |
| 2 | 20-40% | 偏低层 | 趋势斜率较小，下跌趋势较明显 |
| 3 | 40-60% | 正常层 | 趋势斜率适中 |
| 4 | 60-80% | 偏高层 | 趋势斜率较大，上涨趋势较明显 |
| 5 | 80-100% | 极高层 | 趋势斜率最大，上涨趋势最明显 |

### 2.2 多空组合

因子方向为反向（ic_mean=-0.0822<0），多空组合由基类自动派生：

- **做多**: 极低层 + 偏低层（趋势下跌最明显）
- **做空**: 极高层 + 偏高层（趋势上涨最明显）

逻辑：尾盘下跌趋势股票次日表现更好（反向因子）。

### 2.3 其他参数

| 参数 | 默认值 | 说明 |
|------|--------|------|
| return_col | forward_return_1d | 次日收益 |
| return_period | 1d | 收益周期 |

---

## 3. 数据依赖

| 数据文件 | 路径 | 说明 |
|---------|------|------|
| 因子主数据 | factor_ic_data.json.gz | 含 date/asset/forward_return_1d |
| 尾盘K线数据 | tail_trading_data.json.gz | 含 prices（13根5分钟收盘价） |

---

## 4. 运行方式

### 4.1 CLI 命令

```bash
# 分层回测（默认）
python backtest/layered_backtest_tail_price_slope_1d.py

# 强制全量计算
python backtest/layered_backtest_tail_price_slope_1d.py --force-full

# 指定最小股票数
python backtest/layered_backtest_tail_price_slope_1d.py --min-stocks 50
```

### 4.2 输出位置

- **结果文件**: `backtest/result/tail_price_slope_layered_backtest.json`

---

## 5. 输出结构

```json
{
  "meta": {
    "factor_name": "tail_price_slope",
    "factor_direction": "negative",
    "n_layers": 5,
    "layer_method": "percentile"
  },
  "layer_stats": [
    {
      "layer": 1,
      "name": "极低层(趋势斜率最小，下跌趋势最明显)",
      "avg_return": <float>,
      "std_return": <float>,
      "n_days": <int>
    },
    ...
  ],
  "monotonicity": {
    "slope": <float>,
    "is_monotonic": <bool>
  },
  "long_short": {
    "long_layers": [1, 2],
    "short_layers": [4, 5],
    "avg_spread": <float>
  }
}
```

---

## 6. 测试覆盖

- **测试文件**: `backtest/test_cases/test_layered_backtest_tail_price_slope_1d.py`
- **覆盖场景**:
  - 配置类属性验证（factor_name、layer_names）
  - 因子方向派生验证（negative）
  - 多空组合派生验证
  - 结果结构完整性

---

## 7. 版本历史

1. v1.0 (2026-06-02): 初始版本，创建分层回测脚本与配套文档