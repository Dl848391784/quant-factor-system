# 可演化因子实现清单

> 创建日期：2026-06-04
> 状态标记：[ ] = 未完成，[x] = 已完成
> 数据来源：基于现有数据演化，无需新增数据源

---

## 清单说明

- **因子名**：因子唯一标识，用于代码列名
- **公式**：计算公式定义
- **数据依赖**：需要的数据字段
- **状态**：实现进度标记
- **纳入版本**：实现后填写的版本号

---

## 一、价格动量/反转类（3个）

|| 序号 | 因子名 | 公式 | 数据依赖 | 状态 | 纳入版本 |
||------|--------|------|----------|------|----------|
|| 1 | past_return_1d | (close_t - close_{t-1}) / close_{t-1} | close序列 | [x] | v1.3 |
|| 2 | momentum_strength | return_5d / std(return_1d, 5日) | close序列 | [x] | v1.38 |
|| 3 | price_acceleration | return_5d - return_3d | close序列 | [ ] | — |

---

## 二、波动率类（6个）

| 序号 | 因子名 | 公式 | 数据依赖 | 状态 | 纳入版本 |
|------|--------|------|----------|------|----------|
| 5 | volatility_5d | std(return_1d, 5日) × sqrt(250) | close序列 | [ ] | — |
| 6 | volatility_10d | std(return_1d, 10日) × sqrt(250) | close序列 | [ ] | — |
| 7 | volatility_20d | std(return_1d, 20日) × sqrt(250) | close序列 | [ ] | — |
| 8 | volatility_ratio | volatility_5d / volatility_20d | close序列 | [ ] | — |
| 9 | high_low_volatility | mean((high-low)/close, 5日) | high, low, close | [ ] | — |
| 10 | gap_volatility | std(overnight_ret, 10日) | overnight_ret序列 | [ ] | — |

---

## 三、成交量类（4个）

| 序号 | 因子名 | 公式 | 数据依赖 | 状态 | 纳入版本 |
|------|--------|------|----------|------|----------|
| 11 | volume_trend | (volume_t - mean(volume_{t-5:t-1})) / mean(volume_{t-5:t-1}) | volume序列 | [ ] | — |
| 12 | volume_std_ratio | std(volume, 5日) / mean(volume, 5日) | volume序列 | [ ] | — |
| 13 | volume_price_corr | corr(volume, return_1d, 5日) | volume, close序列 | [ ] | — |
| 14 | volume_acceleration | volume_t / volume_{t-3} - 1 | volume序列 | [ ] | — |

---

## 四、换手率衍生类（5个）

| 序号 | 因子名 | 公式 | 数据依赖 | 状态 | 纳入版本 |
|------|--------|------|----------|------|----------|
| 15 | turnover_trend | turnover_t / mean(turnover_{t-5:t-1}) - 1 | turnover_rate序列 | [ ] | — |
| 16 | turnover_std | std(turnover_rate, 10日) / mean(turnover_rate, 10日) | turnover_rate序列 | [ ] | — |
| 17 | turnover_acceleration | turnover_t / turnover_{t-3} - 1 | turnover_rate序列 | [ ] | — |
| 18 | turnover_momentum | mean(turnover_{t-5:t}) / mean(turnover_{t-20:t-5}) | turnover_rate序列 | [ ] | — |
| 19 | turnover_price_corr | corr(turnover_rate, return_1d, 10日) | turnover_rate, close序列 | [ ] | — |

---

## 五、尾盘数据衍生类（7个）

| 序号 | 因子名 | 公式 | 数据依赖 | 状态 | 纳入版本 |
|------|--------|------|----------|------|----------|
| 20 | tail_return | (prices[-1] - prices[0]) / prices[0] | prices[13] | [ ] | — |
| 21 | tail_high_retracement | (tail_high - prices[-1]) / (tail_high - tail_low) | prices, tail_high, tail_low | [ ] | — |
| 22 | tail_volume_concentration | max(volumes) / sum(volumes) | volumes[13] | [ ] | — |
| 23 | tail_volume_first_last | volumes[-1] / volumes[0] | volumes[13] | [ ] | — |
| 24 | tail_price_variability | std(prices) / mean(prices) | prices[13] | [ ] | — |
| 25 | tail_kline_count_ratio | count(prices上涨K线) / 13 | prices[13] | [ ] | — |
| 26 | tail_final_push | (prices[-1] - prices[-3]) / prices[-3] | prices[13] | [ ] | — |

---

## 六、技术指标衍生类（6个）

| 序号 | 因子名 | 公式 | 数据依赖 | 状态 | 纳入版本 |
|------|--------|------|----------|------|----------|
| 27 | rsi_deviation | (rsi_6 - 50) / 50 | rsi_6 | [ ] | — |
| 28 | rsi_trend | rsi_t - rsi_{t-5} | rsi_6序列 | [ ] | — |
| 29 | kdj_j_extreme | kdj_j > 100 ? 1 : kdj_j < 0 ? -1 : 0 | kdj_j | [ ] | — |
| 30 | bollinger_width | (上轨 - 下轨) / 中轨 | close, bollinger_pb | [ ] | — |
| 31 | bollinger_position | abs(bollinger_pb - 0.5) | bollinger_pb | [ ] | — |
| 32 | amplitude_trend | amplitude_t / mean(amplitude_{t-5:t-1}) | amplitude序列 | [ ] | — |

---

## 七、行业/板块类（5个）

| 序号 | 因子名 | 公式 | 数据依赖 | 状态 | 纳入版本 |
|------|--------|------|----------|------|----------|
| 33 | industry_momentum | 行业内股票return_5d均值 | industry, close序列 | [ ] | — |
| 34 | industry_volatility | 行业内股票volatility_5d均值 | industry, close序列 | [ ] | — |
| 35 | industry_turnover | 行业内股票turnover_rate均值 | industry, turnover_rate | [ ] | — |
| 36 | relative_turnover | turnover_rate / industry_turnover | industry, turnover_rate | [ ] | — |
| 37 | relative_volatility | volatility_5d / industry_volatility | industry, close序列 | [ ] | — |

---

## 八、开盘/跳空类（4个）

| 序号 | 因子名 | 公式 | 数据依赖 | 状态 | 纳入版本 |
|------|--------|------|----------|------|----------|
| 38 | open_position | (open - low_{t-1}) / (high_{t-1} - low_{t-1}) | open, high_{t-1}, low_{t-1} | [ ] | — |
| 39 | gap_direction | overnight_ret > 0 ? 1 : overnight_ret < 0 ? -1 : 0 | overnight_ret | [ ] | — |
| 40 | gap_magnitude | abs(overnight_ret) | overnight_ret | [ ] | — |
| 41 | gap_fill_ratio | (close - open) / (open - close_{t-1}) | open, close序列 | [ ] | — |

---

## 九、日内形态类（6个）

| 序号 | 因子名 | 公式 | 数据依赖 | 状态 | 纳入版本 |
|------|--------|------|----------|------|----------|
| 42 | upper_shadow | (high - max(open, close)) / (high - low) | high, low, open, close | [ ] | — |
| 43 | lower_shadow | (min(open, close) - low) / (high - low) | high, low, open, close | [ ] | — |
| 44 | body_ratio | abs(close - open) / (high - low) | high, low, open, close | [ ] | — |
| 45 | doji_signal | body_ratio < 0.1 ? 1 : 0 | high, low, open, close | [ ] | — |
| 46 | marubozu_signal | body_ratio > 0.9 ? 1 : 0 | high, low, open, close | [ ] | — |
| 47 | intraday_reversal | (close < open) & (close > close_{t-1}) ? 1 : 0 | open, close序列 | [ ] | — |

---

## 统计汇总

|| 类别 | 因子数 | 已完成 | 未完成 ||
||------|--------|--------|--------||
|| 价格动量/反转 | 3 | 2 | 1 ||
|| 波动率类 | 6 | 0 | 6 ||
|| 成交量类 | 4 | 0 | 4 ||
|| 换手率衍生 | 5 | 0 | 5 ||
|| 尾盘衍生 | 7 | 0 | 7 ||
|| 技术指标衍生 | 6 | 0 | 6 ||
|| 行业/板块 | 5 | 0 | 5 ||
|| 开盘/跳空 | 4 | 0 | 4 ||
|| 日内形态 | 6 | 0 | 6 ||
|| **总计** | **46** | **2** | **44** ||

---

## 更新记录

|| 日期 | 更新内容 | 更新人 ||
||------|----------|--------||
|| 2026-06-04 | 创建清单，初始状态全部标记未完成 | 云瑶 ||
|| 2026-06-05 | 标记 past_return_1d 已完成（序号1） | 云瑶 ||
|| 2026-06-05 | 删除 return_3d/5d/10d/20d（数据源缺失），重新编号 | 云瑶 ||
|| 2026-06-05 | 标记 momentum_strength 已完成（序号2），删除 reversal_signal（冗余），重新编号 | 云瑶 ||

---

*最后更新：2026-06-05*