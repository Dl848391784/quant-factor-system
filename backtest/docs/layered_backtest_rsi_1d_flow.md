# RSI 分层回测流程文档

> 生成时间: 2026-05-08
> 审阅版本: v1.2
> 最后更新: 2026-06-13

## 更新历史

| 日期 | 版本 | 改动 |
|------|------|------|
| 2026-05-08 | v1.0 | 初始流程文档 |
| 2026-06-13 | v1.1 | 数据加载改用 ijson 流式 + 列过滤（`backtest/common/layered_backtest_runner.py::load_factor_return_data` v2.8）。**动机**：`factor_ic_data.json.gz` 解压后 2.17GB，原 `json.load` 全量加载在 7.3GB 内存机器上触发 OOM（anon-rss 4.2GB 被杀）。**实现**：用 `ijson.items(f, 'data.item')` 逐条 yield，按 `required_factor_cols + index + return_cols` 白名单过滤，最终 `pd.DataFrame(list)` 一次构造。**效果**：内存峰值降低 ~10x（44 列 → 6 列保留），RSS 从 4.2GB → 数百 MB。**对脚本影响**：函数签名/返回值不变，对所有 74 个分层回测脚本透明。 |
| 2026-06-13 | v1.2 | **OOM 修复二阶段**：v1.1 仅修了 list-of-dict 装箱问题，但完整脚本仍 OOM 在 4.16 GB。根因定位至两处：①`load_factor_return_data` 的"顶层 'data' key 校验"步骤用 `ijson.kvitems(f, "")`，yajl2_c 后端在 yield "data" key 之前会完整解析其 value（1.5M 条 list），等价于 `json.load`；②`calculate_rsi_df` 用 `df.groupby(asset).transform(calc_rsi)`，pandas 中间索引膨胀至 4 GB+。**修复**：①移除顶层校验（`load_factor_return_data` v2.9），改为 `ijson.items(f, "data.item")` 直接流式遍历，零记录时用 `ValueError("'data' 字段为空")` 兜底；②`calculate_rsi_df` 重写为 numpy 边界切片实现：sort + reset_index → numpy 找 asset 边界 → 逐 asset 切 close Series 调 `calculate_rsi` → 回填预分配 ndarray。新版与旧版位级一致（单测 TC04 保证），内存增量约 36 MB（vs transform 几 GB）。**实测**：完整 RSI 分层回测脚本 RSS 从 OOM(4.16 GB) → 901 MB（降 78%），耗时 2:59，输出文件正常生成。 |

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
│  输出: backtest/result/rsi_layered_backtest.json                     │
│        backtest/result/rsi_layered_backtest_daily.json.gz            │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 🔍 详细流程步骤

### Step 1: 配置初始化

```
RSILayerConfig 类定义
    │
    ├── 分层模式 (percentile 5层)
        │   │   每层约20%分位，实际边界由数据分布决定
        │   │   layer_names = ('oversold', 'low', 'normal', 'high', 'overbought')
        │   │   └───────────────────────────────────────────────
        │   │   | Layer | 分位范围     | 描述                |
        │   │   |-------|-------------|---------------------|
        │   │   | 1     | 0-20%       | 极低层(RSI极低)     |
        │   │   | 2     | 20-40%      | 偏低层(RSI偏低)     |
        │   │   | 3     | 40-60%      | 正常层(RSI适中)     |
        │   │   | 4     | 60-80%      | 高层(RSI偏高)     |
        │   │   | 5     | 80-100%     | 极高层(RSI极高)     |
        │   │   └───────────────────────────────────────────────
    │
    ├── 因子方向
    │   FACTOR_DIRECTION = 'negative'  # RSI是反向因子
    │   解释: RSI低 → 反转预期高
        │         RSI高 → 反转预期低
        │
        ├── 多空组合 (反向因子特点)
        │   LONG_LAYERS = [1, 2]   # 多头: 极低层+偏低层 (反转预期高)
        │   SHORT_LAYERS = [4, 5]  # 空头: 高层+极高层 (反转预期低)
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
    │   └── data_fetchers/result/factor_data.json.gz
    │       ├── 解压 gzip → JSON
    │       ├── 转为 DataFrame
    │       ├── 提取列: [date, asset, rsi_6]
    │       └── 限制天数: 最近 n_days 天
    │
    ├── 加载收益数据
    │   │
    │   └── data_fetchers/result/factor_ic_data.json.gz
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
       │   ├── layer_method      = 'percentile' (分位分层)
       │   ├── n_layers          = 5
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
   │      │          │  percentile 分层算法:                         │ │
           │      │          │                                         │ │
           │      │          │  按 rsi 值排序，等分为5组               │ │
           │      │          │  layer_assignment = percentile分组      │ │
        │      │          │                                         │ │
   │      │          │  边界处理: NaN → 跳过                    │ │
           │      │          │                                         │ │
           │      │          └─────────────────────────────────────────┘ │
           │      │                                                       │
           │      ├── [收益] 计算各层收益
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
            "1": "极低层(RSI极低)",
            "2": "偏低层(RSI偏低)",
            "3": "正常层(RSI适中)",
            "4": "偏高层(RSI偏高)",
            "5": "极高层(RSI极高)"
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
| **多头收益** | Layer[1,2]组合收益 | 正值（低值层收益高） |
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

   ### percentile 分层说明

   RSI 因子采用 percentile 5层分层（每层约20%分位），与项目其他因子保持一致。
   实际分位边界由数据分布决定，而非固定阈值（如 RSI<30/70）。

   **选择 percentile 的原因**：
   - 与项目其他因子分层方式一致，便于横向比较
   - 避免固定阈值在 A 股市场可能不适用的假设
   - percentile 描述使用相对语义（极低/偏低/正常/偏高/极高）

   ### 反向因子处理

```
正向因子 (如 Volume_Ratio):
    高值 → 高收益预期
    多头 = Layer4, Layer5 (高值层)
    空头 = Layer1, Layer2 (低值层)

   反向因子 (如 RSI):
       低值 → 反转预期高 (RSI极低组)
       多头 = Layer1, Layer2 (低值层)
       空头 = Layer4, Layer5 (高值层)
```

---

## 📁 文件位置

| 文件 | 路径 |
|------|------|
| 入口脚本 | `backtest/rsi_layered_backtest.py` |
| 回测引擎 | `backtest/layered_backtest.py` |
| 输出结果 | `backtest/result/rsi_layered_backtest.json` |
| 每日明细 | `backtest/result/rsi_layered_backtest_daily.json.gz` |
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