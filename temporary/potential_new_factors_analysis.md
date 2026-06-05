# 基于现有数据可演化的新因子分析

> 分析日期：2026-06-04
> 分析目的：梳理现有数据源能演化但目前未实现的因子

---

## 一、现有数据源汇总

| 数据源 | 数据字段 | 拉取脚本 |
|--------|----------|----------|
| 日K线数据 | open, close, high, low, volume | fetch_factor_cache.py |
| 基础因子 | rsi_6, volume_ratio_5 | fetch_factor_cache.py（预计算） |
| 换手率数据 | turnover_rate | fetch_turnover.py |
| 尾盘5分钟K线 | prices[13], volumes[13], tail_high, tail_low | fetch_tail_trading.py |
| 行业数据 | industry_code, industry_name | fetch_industry.py |
| 前瞻收益 | forward_return_1d, forward_return_3d, forward_return_5d | factor_generator.py（计算） |

---

## 二、现有因子池（14个）

| 类别 | 因子名 | 公式 |
|------|--------|------|
| 基础因子 | rsi_6 | Wilder标准6日RSI |
| 基础因子 | volume_ratio_5 | 当日volume / 过去5日volume均值 |
| 扩展因子 | bollinger_pb | (close - 下轨) / (上轨 - 下轨) |
| 扩展因子 | kdj_j | J = 3K - 2D |
| 扩展因子 | turnover_surge | 当日turnover_rate / 过去5日均值 |
| 扩展因子 | amplitude | (high - low) / close |
| 扩展因子 | price_position | (close - low) / (high - low) |
| 扩展因子 | overnight_ret | (今日open - 昨日close) / 昨日close |
| 扩展因子 | intraday_intensity | (close - open) / (high - low) |
| 尾盘因子 | tail_price_position | (尾盘末价 - tail_low) / (tail_high - tail_low) |
| 尾盘因子 | tail_price_slope | 尾盘价格序列线性回归斜率 / 均价 |
| 尾盘因子 | tail_price_volume_intensity | 尾盘涨跌幅 × 尾盘量比 |
| 尾盘因子 | tail_volume_acceleration | 后半段成交量 / 前半段成交量 |
| 尾盘因子 | tail_volume_shrink | 尾盘成交量总和 / 全天成交量 |

---

## 三、可演化但未实现的新因子

### 3.1 价格动量/反转类因子（基于日K线历史数据）

| 因子名 | 定义 | 公式 | 数据依赖 | 经济含义 |
|--------|------|------|----------|----------|
| **return_1d** | 1日收益率 | (今日close - 昨日close) / 昨日close | close序列 | 短期价格变化，捕捉日内动量 |
| **return_3d** | 3日累计收益率 | (close_t - close_{t-3}) / close_{t-3} | close序列 | 3日动量，已有计算函数但未纳入因子池 |
| **return_5d** | 5日累计收益率 | (close_t - close_{t-5}) / close_{t-5} | close序列 | 5日动量，已有计算函数但未纳入因子池 |
| **return_10d** | 10日累计收益率 | (close_t - close_{t-10}) / close_{t-10} | close序列 | 中期动量 |
| **return_20d** | 20日累计收益率 | (close_t - close_{t-20}) / close_{t-20} | close序列 | 月度动量 |
| **momentum_strength** | 动量强度 | return_5d / std(return_1d, 5日) | close序列 | 动量稳定性，高值表示稳定上涨 |
| **reversal_signal** | 反转信号 | -return_5d（负动量） | close序列 | 短期反转策略信号 |
| **price_acceleration** | 价格加速度 | return_5d - return_3d | close序列 | 收益变化率，加速上涨或下跌 |

### 3.2 波动率类因子（基于日K线历史数据）

| 因子名 | 定义 | 公式 | 数据依赖 | 经济含义 |
|--------|------|------|----------|----------|
| **volatility_5d** | 5日波动率 | std(return_1d, 5日) × sqrt(250) | close序列 | 短期波动率年化 |
| **volatility_10d** | 10日波动率 | std(return_1d, 10日) × sqrt(250) | close序列 | 中期波动率年化 |
| **volatility_20d** | 20日波动率 | std(return_1d, 20日) × sqrt(250) | close序列 | 月度波动率年化 |
| **volatility_ratio** | 波动率比值 | volatility_5d / volatility_20d | close序列 | 短期vs长期波动率，>1表示波动放大 |
| **high_low_volatility** | 高低波动 | mean((high-low)/close, 5日) | high, low, close | 基于振幅的波动率代理 |
| **gap_volatility** | 跳空波动 | std(overnight_ret, 10日) | open, close序列 | 隔夜跳空的不稳定性 |

### 3.3 成交量类因子（基于volume历史数据）

| 因子名 | 定义 | 公式 | 数据依赖 | 经济含义 |
|--------|------|------|----------|----------|
| **volume_trend** | 成交量趋势 | (volume_t - mean(volume_{t-5:t-1})) / mean(volume_{t-5:t-1}) | volume序列 | 成交量相对均值的变化 |
| **volume_std_ratio** | 成交量稳定性 | std(volume, 5日) / mean(volume, 5日) | volume序列 | 成交量波动程度 |
| **volume_price_corr** | 量价相关性 | corr(volume, return_1d, 5日) | volume, close | 量价协同程度 |
| **volume_acceleration** | 成交量加速度 | volume_t / volume_{t-3} - 1 | volume序列 | 成交量变化速率 |

### 3.4 换手率衍生因子（基于turnover_rate历史数据）

| 因子名 | 定义 | 公式 | 数据依赖 | 经济含义 |
|--------|------|------|----------|----------|
| **turnover_trend** | 换手率趋势 | turnover_t / mean(turnover_{t-5:t-1}) - 1 | turnover_rate序列 | 换手率变化方向 |
| **turnover_std** | 换手率稳定性 | std(turnover_rate, 10日) / mean(turnover_rate, 10日) | turnover_rate序列 | 换手率波动程度 |
| **turnover_acceleration** | 换手率加速度 | turnover_t / turnover_{t-3} - 1 | turnover_rate序列 | 换手率变化速率 |
| **turnover_momentum** | 换手率动量 | mean(turnover_{t-5:t}) / mean(turnover_{t-20:t-5}) | turnover_rate序列 | 长短期换手率比值 |
| **turnover_price_corr** | 换手率价格相关性 | corr(turnover_rate, return_1d, 10日) | turnover_rate, close | 换手率与收益的关系 |

### 3.5 尾盘数据衍生因子（基于尾盘5分钟K线）

| 因子名 | 定义 | 公式 | 数据依赖 | 经济含义 |
|--------|------|------|----------|----------|
| **tail_return** | 尾盘收益率 | (prices[-1] - prices[0]) / prices[0] | prices[13] | 尾盘一小时涨跌幅 |
| **tail_high_retracement** | 尾盘高位回撤 | (tail_high - prices[-1]) / (tail_high - tail_low) | prices, tail_high, tail_low | 从尾盘高点回落程度 |
| **tail_volume_concentration** | 尾盘量集中度 | max(volumes) / sum(volumes) | volumes[13] | 最大成交量占比 |
| **tail_volume_first_last** | 首尾成交量比 | volumes[-1] / volumes[0] | volumes[13] | 尾盘末vs首成交量比 |
| **tail_price_variability** | 尾盘价格变异 | std(prices) / mean(prices) | prices[13] | 尾盘价格波动程度 |
| **tail_kline_count_ratio** | 尾盘K线涨跌比 | count(prices上涨K线) / 13 | prices[13] | 尾盘上涨K线占比 |
| **tail_final_push** | 尾盘末段推力 | (prices[-1] - prices[-3]) / prices[-3] | prices[13] | 最后15分钟涨跌 |

### 3.6 技术指标衍生因子（基于现有因子组合）

| 因子名 | 定义 | 公式 | 数据依赖 | 经济含义 |
|--------|------|------|----------|----------|
| **rsi_deviation** | RSI偏离度 | (rsi_6 - 50) / 50 | rsi_6 | RSI偏离中性程度 |
| **rsi_trend** | RSI趋势 | rsi_t - rsi_{t-5} | rsi_6序列 | RSI变化方向 |
| **kdj_j_extreme** | KDJ极端值 | kdj_j > 100 ? 1 : kdj_j < 0 ? -1 : 0 | kdj_j | 超买超卖二元信号 |
| **bollinger_width** | 布林带宽 | (上轨 - 下轨) / 中轨 | close, bollinger_pb | 布林带宽度，波动率代理 |
| **bollinger_position** | 布林位置偏离 | abs(bollinger_pb - 0.5) | bollinger_pb | 价格偏离布林中轨程度 |
| **amplitude_trend** | 振幅趋势 | amplitude_t / mean(amplitude_{t-5:t-1}) | amplitude序列 | 波动放大或缩小 |

### 3.7 行业/板块类因子（基于行业数据）

| 因子名 | 定义 | 公式 | 数据依赖 | 经济含义 |
|--------|------|------|----------|----------|
| **industry_momentum** | 行业动量 | 行业内股票return_5d均值 | industry, close | 行业整体动量 |
| **industry_volatility** | 行业波动率 | 行业内股票volatility_5d均值 | industry, close | 行业整体波动水平 |
| **industry_turnover** | 行业换手率 | 行业内股票turnover_rate均值 | industry, turnover_rate | 行业活跃度 |
| **relative_turnover** | 相对换手率 | turnover_rate / industry_turnover | industry, turnover_rate | 相对行业的换手率 |
| **relative_volatility** | 相对波动率 | volatility_5d / industry_volatility | industry, close | 相对行业的波动率 |

### 3.8 开盘/跳空类因子（基于open数据）

| 因子名 | 定义 | 公式 | 数据依赖 | 经济含义 |
|--------|------|------|----------|----------|
| **open_position** | 开盘位置 | (open - low_{t-1}) / (high_{t-1} - low_{t-1}) | open, high_{t-1}, low_{t-1} | 开盘价相对于昨日振幅位置 |
| **gap_direction** | 跳空方向 | overnight_ret > 0 ? 1 : overnight_ret < 0 ? -1 : 0 | overnight_ret | 跳空方向二元信号 |
| **gap_magnitude** | 跳空幅度绝对值 | abs(overnight_ret) | overnight_ret | 跳空大小（不分方向） |
| **gap_fill_ratio** | 跳空回补比例 | (close - open) / (open - close_{t-1}) | open, close | 日内回补跳空程度 |

### 3.9 日内形态类因子（基于OHLC）

| 因子名 | 定义 | 公式 | 数据依赖 | 经济含义 |
|--------|------|------|----------|----------|
| **upper_shadow** | 上影线比例 | (high - max(open, close)) / (high - low) | high, low, open, close | 上影线占比，抛压信号 |
| **lower_shadow** | 下影线比例 | (min(open, close) - low) / (high - low) | high, low, open, close | 下影线占比，支撑信号 |
| **body_ratio** | 实体比例 | abs(close - open) / (high - low) | high, low, open, close | 实体占振幅比例 |
| **doji_signal** | 十字星信号 | body_ratio < 0.1 ? 1 : 0 | high, low, open, close | 十字星形态识别 |
| **marubozu_signal** | 光头光脚信号 | body_ratio > 0.9 ? 1 : 0 | high, low, open, close | 光头光脚形态识别 |
| **intraday_reversal** | 日内反转 | (close < open) & (close > close_{t-1}) ? 1 : 0 | open, close | 跌势收红形态 |

---

## 四、因子统计汇总

| 类别 | 可演化因子数 | 已实现因子数 | 覆盖率 |
|------|-------------|-------------|--------|
| 价格动量/反转 | 8 | 0（有计算函数但未纳入） | 0% |
| 波动率类 | 6 | 0 | 0% |
| 成交量类 | 4 | 1（volume_ratio_5） | 25% |
| 换手率衍生 | 5 | 1（turnover_surge） | 20% |
| 尾盘衍生 | 7 | 5 | 71% |
| 技术指标衍生 | 6 | 0 | 0% |
| 行业/板块类 | 5 | 0 | 0% |
| 开盘/跳空类 | 4 | 1（overnight_ret） | 25% |
| 日内形态类 | 6 | 1（intraday_intensity） | 17% |
| **总计** | **51** | **8** | **16%** |

---

## 五、优先级建议因子（Top 20）

基于数据可获取性、经济含义明确性、计算复杂度三个维度，推荐优先实现的因子：

| 序号 | 因子名 | 类别 | 优先级理由 |
|------|--------|------|------------|
| 1 | return_1d | 价格动量 | 最基础因子，计算简单，有计算函数但未纳入池 |
| 2 | volatility_5d | 波动率 | 波动率是核心风险指标，业界常用 |
| 3 | volume_price_corr | 成交量 | 量价关系是经典分析维度 |
| 4 | upper_shadow | 日内形态 | 上影线是抛压信号，预测性强 |
| 5 | lower_shadow | 日内形态 | 下影线是支撑信号，预测性强 |
| 6 | tail_return | 尾盘衍生 | 尾盘涨跌幅直接反映尾盘情绪 |
| 7 | turnover_momentum | 换手率衍生 | 换手率动量与价格动量交叉验证 |
| 8 | bollinger_width | 技术指标衍生 | 布林带宽是波动率代理 |
| 9 | rsi_deviation | 技术指标衍生 | RSI偏离度比RSI本身更直观 |
| 10 | price_acceleration | 价格动量 | 价格加速度捕捉加速/减速转折 |
| 11 | gap_fill_ratio | 开盘跳空 | 跳空回补是日内重要现象 |
| 12 | turnover_price_corr | 换手率衍生 | 量价相关性，学术研究常用 |
| 13 | volatility_ratio | 波动率 | 短期vs长期波动率比值 |
| 14 | tail_final_push | 尾盘衍生 | 最后15分钟是收盘关键时段 |
| 15 | momentum_strength | 价格动量 | 动量强度比单纯动量更稳定 |
| 16 | body_ratio | 日内形态 | 实体比例反映买卖力量对比 |
| 17 | relative_turnover | 行业类 | 相对行业换手率剔除行业效应 |
| 18 | turnover_acceleration | 换手率衍生 | 换手率加速度捕捉量能变化 |
| 19 | tail_volume_concentration | 尾盘衍生 | 尾盘量集中度反映尾盘砸盘/拉升 |
| 20 | doji_signal | 日内形态 | 十字星是经典反转信号 |

---

## 六、数据依赖说明

- **已完全具备数据**：open, close, high, low, volume, turnover_rate, prices[13], volumes[13], tail_high, tail_low, rsi_6, volume_ratio_5, overnight_ret, industry
- **需要历史序列计算**：return_1d/3d/5d/10d/20d, volatility, momentum, turnover_trend等需要rolling窗口计算
- **无额外数据拉取需求**：所有推荐因子均可从现有数据演化，无需新增数据源

---

*分析完成时间：2026-06-04*