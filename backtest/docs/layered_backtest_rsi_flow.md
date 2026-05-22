# RSI 分层回测流程文档

> 生成时间: 2026-05-08
> 审阅版本: v1.0

---

## 📋 整体架构

```
┌─────────────────────────────────────────────────────────────────────┐
│              RSI分层回测系统架构                                      │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  rsi_layered_backtest.py (入口脚本)                                 │
│         │                                                           │
│         ├── RSILayerConfig (配置类)                                 │
│         │      ├── 分层阈值定义                                      │
│         │      ├── 因子方向设置                                      │
│         │      └── 多空组合定义                                      │
│         │                                                           │
│         ├── load_data_from_cache() (数据加载)                       │
│         │                                                           │
│         └── LayeredBacktestEngine.run() (回测引擎)                  │
│                │                                                    │
│                ├── 数据合并                                          │
│                ├── 每日分层                                          │
│                ├── 收益计算                                          │
│                ├── 换手率计算                                        │
│                └── 统计汇总                                          │
│                                                                     │
│  输出: cache/backtest/rsi_layered_backtest.json                     │
│        cache/backtest/rsi_layered_backtest_daily.json.gz            │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 🔍 详细流程步骤

### Step 1: 配置初始化

```
RSILayerConfig 类定义
    │
    ├── 分层阈值 (固定阈值法)
    │   LAYER_THRESHOLDS = [0, 20, 40, 60, 80, 100]
    │   └───────────────────────────────────────────────
    │   | Layer | RSI范围        | 含义              |
    │   |-------|---------------|-------------------|
    │   | 1     | RSI < 20      | 超卖层            |
    │   | 2     | 20 ≤ RSI < 40 | 弱势层            |
    │   | 3     | 40 ≤ RSI < 60 | 中性层            |
    │   | 4     | 60 ≤ RSI < 80 | 强势层            |
    │   | 5     | RSI ≥ 80      | 超买层            |
    │   └───────────────────────────────────────────────
    │
    ├── 因子方向
    │   FACTOR_DIRECTION = 'negative'  # RSI是反向因子
    │   解释: RSI低 → 超卖 → 预期收益高
    │         RSI高 → 超买 → 预期收益低
    │
    ├── 多空组合 (反向因子特点)
    │   LONG_LAYERS = [1, 2]   # 多头: 超卖层+弱势层 (预期收益高)
    │   SHORT_LAYERS = [4, 5]  # 空头: 强势层+超买层 (预期收益低)
    │
    └── 交易参数
        TRADE_COST_RATE = 0.003        # 单边千分之三
        MIN_STOCKS_PER_LAYER = 10      # 每层最少10只股票
```

---

### Step 2: 数据加载

```
load_data_from_cache()
    │
    ├── 加载因子数据
    │   │
    │   └── cache/factor_data/factor_data.json.gz
    │       ├── 解压 gzip → JSON
    │       ├── 转为 DataFrame
    │       ├── 提取列: [date, asset, rsi_6]
    │       └── 限制天数: 最近 n_days 天
    │
    ├── 加载收益数据
    │   │
    │   └── cache/factor_data/return_data.json.gz
    │       ├── 解压 gzip → JSON
    │       ├── 转为 DataFrame
    │       ├── 提取列: [date, asset, forward_return_1d]
    │       └── 限制天数: 最近 n_days 天
    │
    └── 返回 (factor_df, return_df)
```

**数据格式示例**：

```
factor_df:
| date       | asset   | rsi_6 |
|------------|---------|-------|
| 2026-01-01 | 000001  | 25.5  |
| 2026-01-01 | 000002  | 80.2  |
| ...        | ...     | ...   |

return_df:
| date       | asset   | forward_return_1d |
|------------|---------|-------------------|
| 2026-01-01 | 000001  | 0.05              |
| 2026-01-01 | 000002  | -0.02             |
| ...        | ...     | ...               |
```

---

### Step 3: 回测引擎初始化

```
LayeredBacktestEngine.__init__()
    │
    ├── 参数接收
    │   ├── factor_df    因子数据
    │   ├── return_df    收益数据
    │   ├── factor_col   = 'rsi_6'
    │   ├── return_col   = 'forward_return_1d'
    │   ├── date_col     = 'date'
    │   └── asset_col    = 'asset'
    │
    └── 数据合并 (_merge_data)
        │
        ├── 选择需要的列
        │   factor_cols = [date, asset, rsi_6]
        │   return_cols = [date, asset, forward_return_1d]
        │
        ├── 内连接合并
        │   merged_df = pd.merge(factor_df, return_df, on=[date, asset])
        │
        ├── 获取日期列表
        │   dates = sorted(merged_df[date].unique())
        │
        └── 内存优化
            ├── asset → category 类型
            ├── rsi_6 → float32 类型
            └── forward_return_1d → float32 类型
```

---

### Step 4: 分层回测执行（核心循环）

```
LayeredBacktestEngine.run()
    │
    ├── 参数配置
    │   ├── layer_method      = 'fixed_threshold' (固定阈值)
    │   ├── thresholds        = [0, 20, 40, 60, 80, 100]
    │   ├── factor_direction  = 'negative' (反向因子)
    │   ├── long_layers       = [1, 2]
    │   ├── short_layers      = [4, 5]
    │   └── trade_cost_rate   = 0.003
    │
    └── 每日循环处理
        │
        └──────────────────────────────────────────────────────────────┐
        │                                                              │
        │  for each date in dates:                                     │
        │      │                                                       │
        │      ├── [过滤] 获取当日数据                                   │
        │      │      day_data = merged_df[merged_df[date] == date]    │
        │      │                                                       │
        │      ├── [过滤] 去除因子NaN                                   │
        │      │      day_data = day_data[rsi_6.notna()]               │
        │      │                                                       │
        │      ├── [检查] 股票数 < MIN_STOCKS_PER_LAYER?               │
        │      │      → 跳过该日                                        │
        │      │                                                       │
        │      ├── [分层] 计算股票归属                                   │
        │      │      get_layer_assignment()                           │
        │      │          │                                            │
        │      │          └─────────────────────────────────────────┐ │
        │      │          │                                         │ │
        │      │          │  固定阈值分层算法:                         │ │
        │      │          │                                         │ │
        │      │          │  for i in [0, 1, 2, 3, 4]:               │ │
        │      │          │      lower = thresholds[i]               │ │
        │      │          │      upper = thresholds[i+1]             │ │
        │      │          │      mask = (rsi >= lower) & (rsi < upper)│ │
        │      │          │      layer_assignment[mask] = i + 1      │ │
        │      │          │                                         │ │
        │      │          │  边界处理:                                │ │
        │      │          │      rsi >= 100 → Layer5                 │ │
        │      │          │      rsi < 0   → Layer1                  │ │
        │      │          │                                         │ │
        │      │          └─────────────────────────────────────────┘ │
        │      │                                                       │
        │      ├── [收益] 计算各层收益                                   │
        │      │      calculate_layer_returns()                       │
        │      │          │                                            │
        │      │          │  for each layer_id:                        │
        │      │          │      layer_mask = (layer_assignment == layer_id)│
        │      │          │      layer_returns = returns[layer_mask]  │
        │      │          │      │                                    │
        │      │          │      股票数 < min_stocks? → return NaN      │
        │      │          │      │                                    │
        │      │          │      等权平均收益:                          │
        │      │          │          mean_return = layer_returns.mean()│
        │      │          │                                            │
        │      │                                                       │
        │      ├── [换手] 计算各层换手率                                 │
        │      │      calculate_turnover()                             │
        │      │          │                                            │
        │      │          │  换手率 = 新入股票数 / 层股票总数             │
        │      │          │      │                                    │
        │      │          │  curr_stocks = 当前层股票集合               │
        │      │          │  prev_stocks = 前期该层股票集合             │
        │      │          │  new_stocks = curr_stocks - prev_stocks    │
        │      │          │  turnover = len(new_stocks) / len(curr_stocks)│
        │      │          │                                            │
        │      │                                                       │
        │      ├── [记录] 保存每日结果                                   │
        │      │      for layer_id in [1, 2, 3, 4, 5]:                 │
        │      │          daily_records.append({                       │
        │      │              'date': date,                            │
        │      │              'layer': layer_id,                       │
        │      │              'n_stocks': 股票数,                       │
        │      │              'return': 层收益,                         │
        │      │              'turnover': 换手率                        │
        │      │          })                                           │
        │      │                                                       │
        │      └── [更新] prev_assignment = 当日分层结果                 │
        │                                                              │
        └──────────────────────────────────────────────────────────────┘
```

---

### Step 5: 统计汇总

```
_aggregate_results()
    │
    ├── [一] 各层统计
    │   │
    │   │  for layer_id in [1, 2, 3, 4, 5]:
    │   │      layer_data = daily_df[daily_df['layer'] == layer_id]
    │   │      │
    │   │      ├── 日均收益 = layer_data['return'].mean()
    │   │      ├── 日收益标准差 = layer_data['return'].std()
    │   │      ├── 累计收益 = (1 + returns).cumprod() - 1
    │   │      ├── 年化收益 = daily_return_mean * 252
    │   │      ├── 年化波动 = daily_return_std * sqrt(252)
    │   │      ├── 夏普比率 = annual_return / annual_volatility
    │   │      ├── 最大回撤 = max_drawdown 计算
    │   │      └── 平均换手率 = layer_data['turnover'].mean()
    │   │
    │   └── 输出: layer_stats = {layer_1: {...}, layer_2: {...}, ...}
    │
    ├── [二] 多空组合统计
    │   │
    │   │  for each date:
    │   │      ├── 多头收益 = Layer[1,2] 收益均值
    │   │      ├── 空头收益 = Layer[4,5] 收益均值
    │   │      └── 多空收益 = 多头收益 - 空头收益
    │   │
    │   │  汇总:
    │   │      ├── 多头日均收益
    │   │      ├── 多头年化收益
    │   │      ├── 空头日均收益
    │   │      ├── 空头年化收益
    │   │      ├── 多空日均收益
    │   │      ├── 多空年化收益
    │   │      ├── 多空夏普比率
    │   │      ├── 多头平均换手率
    │   │      └── 空头平均换手率
    │   │
    │   └── 输出: long_short = {...}
    │
    ├── [三] 单调性检验
    │   │
    │   │  _calculate_monotonicity()
    │   │      │
    │   │      ├── 提取各层日均收益: [r1, r2, r3, r4, r5]
    │   │      ├── layer_ids = [1, 2, 3, 4, 5]
    │   │      │
    │   │      ├── 计算相关系数:
    │   │      │   correlation = corrcoef(layer_ids, layer_returns)
    │   │      │
    │   │      ├── 反向因子判定:
    │   │      │   correlation < -0.5 → 'good' (单调性良好)
    │   │      │   correlation < 0    → 'moderate' (单调性一般)
    │   │      │   correlation >= 0   → 'poor' (单调性较差)
    │   │      │
    │   │      └── 期望: Layer1收益 > Layer5收益 (反向因子)
    │   │
    │   └── 输出: monotonicity = {correlation, quality, layer_returns}
    │
    └── [四] 交易成本分析
        │
        │  _calculate_trading_costs()
            │
            ├── 多头交易成本 = long_turnover * trade_cost_rate
            │   (单边成本)
            │
            ├── 空头交易成本 = short_turnover * trade_cost_rate * 2
            │   (双边成本，做空需借券)
            │
            ├── 多空毛收益 = long_return - short_return
            │
            ├── 多空净收益 = (long_return - long_cost) - (short_return - short_cost)
            │
            └── 输出: trading_cost_analysis = {...}
```

---

### Step 6: 输出结果

#### 输出文件结构

**主结果文件**: `rsi_layered_backtest.json`

```json
{
    "meta": {
        "n_layers": 5,
        "factor_name": "rsi_6",
        "factor_direction": "negative",
        "long_layers": [1, 2],
        "short_layers": [4, 5],
        "n_days_total": 500,
        "n_assets_total": 3500,
        "layer_names": {
            "1": "超卖层",
            "2": "弱势层",
            "3": "中性层",
            "4": "强势层",
            "5": "超买层"
        }
    },
    "layer_stats": {
        "layer_1": {
            "n_days": 500,
            "n_stocks_avg": 120,
            "daily_return_mean": 0.00085,
            "daily_return_std": 0.015,
            "cumulative_return": 0.52,
            "annual_return": 0.214,
            "annual_volatility": 0.238,
            "sharpe_ratio": 0.90,
            "max_drawdown": -0.18,
            "turnover_avg": 0.35
        },
        "layer_2": {...},
        "layer_3": {...},
        "layer_4": {...},
        "layer_5": {...}
    },
    "long_short": {
        "long_return_daily": 0.00072,
        "long_return_annual": 0.181,
        "short_return_daily": -0.00025,
        "short_return_annual": -0.063,
        "long_short_return_daily": 0.00097,
        "long_short_return_annual": 0.244,
        "long_short_sharpe": 1.25,
        "n_days": 500
    },
    "monotonicity": {
        "correlation": -0.82,
        "quality": "good",
        "layer_returns": [0.00085, 0.00045, 0.00020, -0.00015, -0.00035]
    },
    "trading_cost_analysis": {
        "cost_rate": 0.003,
        "long_turnover": 0.35,
        "short_turnover": 0.42,
        "long_daily_cost": 0.00105,
        "short_daily_cost": 0.00252,
        "long_short_gross_daily": 0.00097,
        "long_short_net_daily": 0.00035
    },
    "config": {
        "layer_thresholds": [0, 20, 40, 60, 80, 100],
        "factor_direction": "negative",
        "long_layers": [1, 2],
        "short_layers": [4, 5],
        "trade_cost_rate": 0.003
    }
}
```

**每日明细文件**: `rsi_layered_backtest_daily.json.gz` (压缩)

```json
{
    "meta": {
        "n_days": 500,
        "columns": ["date", "layer", "n_stocks", "return", "turnover"]
    },
    "data": [
        {"date": "2026-01-01", "layer": 1, "n_stocks": 118, "return": 0.0085, "turnover": 0.32},
        {"date": "2026-01-01", "layer": 2, "n_stocks": 245, "return": 0.0045, "turnover": 0.28},
        ...
    ]
}
```

---

## 📊 关键指标含义

### 各层统计指标

| 指标 | 含义 | 计算方式 |
|------|------|----------|
| **日均收益** | 该层每日平均收益 | returns.mean() |
| **年化收益** | 年化后的收益 | 日均收益 × 252 |
| **年化波动** | 年化后的波动率 | 日标准差 × sqrt(252) |
| **夏普比率** | 风险调整后收益 | 年化收益 / 年化波动 |
| **最大回撤** | 最大亏损幅度 | cumprod 回撤计算 |
| **换手率** | 每日股票变动比例 | 新入股票数 / 层股票数 |

### 多空组合指标

| 指标 | 含义 | RSI反向因子预期 |
|------|------|-----------------|
| **多头收益** | Layer[1,2]组合收益 | 正值（超卖层收益高） |
| **空头收益** | Layer[4,5]组合收益 | 负值或低正值 |
| **多空收益** | 多头 - 空头 | 正值（因子有效） |
| **多空夏普** | 多空组合夏普比率 | > 0.5 表示有效 |

### 单调性指标

| 相关系数 | 质量 | 说明 |
|----------|------|------|
| < -0.5 | good | Layer1收益明显高于Layer5 |
| < 0 | moderate | 有一定单调性 |
| >= 0 | poor | 无单调性，因子可能无效 |

---

## 🔧 RSI分层特点

### 固定阈值分层 vs 百分位分层

| 方法 | 特点 | 适用场景 |
|------|------|----------|
| **固定阈值** | 使用绝对值划分，如RSI<20 | RSI等有明确含义的因子 |
| **百分位** | 每层20%股票，相对划分 | 通用因子，无绝对含义 |

**RSI使用固定阈值的原因**：
- RSI有明确的超买/超卖含义（20/80是经典阈值）
- 固定阈值更符合技术分析直觉
- 不同市场环境下阈值含义稳定

### 反向因子处理

```
正向因子 (如 Volume_Ratio):
    高值 → 高收益预期
    多头 = Layer4, Layer5 (高值层)
    空头 = Layer1, Layer2 (低值层)

反向因子 (如 RSI):
    低值 → 高收益预期 (超卖反弹)
    多头 = Layer1, Layer2 (低值层)
    空头 = Layer4, Layer5 (高值层)
```

---

## 📁 文件位置

| 文件 | 路径 |
|------|------|
| 入口脚本 | `backtest/rsi_layered_backtest.py` |
| 回测引擎 | `backtest/layered_backtest.py` |
| 输出结果 | `cache/backtest/rsi_layered_backtest.json` |
| 每日明细 | `cache/backtest/rsi_layered_backtest_daily.json.gz` |
| 本文档 | `backtest/docs/rsi_layered_backtest_flow.md` |

---

## 🔄 与其他因子回测的关系

通用分层回测引擎 `LayeredBacktestEngine` 可用于多种因子：

| 因子 | 方向 | 分层方法 | 多头组合 |
|------|------|----------|----------|
| RSI | negative (反向) | fixed_threshold | Layer[1,2] |
| KDJ_J | negative (反向) | fixed_threshold | Layer[1,2] |
| Volume_Ratio | positive (正向) | percentile | Layer[4,5] |
| Turnover_Surge | positive (正向) | percentile | Layer[4,5] |
| Bollinger_PB | negative (反向) | fixed_threshold | Layer[1,2] |
| Main_Inflow | positive (正向) | percentile | Layer[4,5] |

---

## 🚀 使用方式

### 命令行运行

```bash
cd ~/.openclaw/workspace/yunzhou/factor_ic_analyzer

# 默认回测500天
python -m backtest.rsi_layered_backtest

# 指定回测天数
python -m backtest.rsi_layered_backtest --n_days 250

# 安静模式
python -m backtest.rsi_layered_backtest --quiet
```

### Python调用

```python
from backtest.rsi_layered_backtest import run_rsi_layered_backtest

result = run_rsi_layered_backtest(
    n_days=500,
    verbose=True
)

# 查看结果
print(result['long_short']['long_short_return_annual'])
print(result['monotonicity']['correlation'])
```

---

*文档结束*