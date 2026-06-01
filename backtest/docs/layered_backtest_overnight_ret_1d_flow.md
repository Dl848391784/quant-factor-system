# 隔夜收益率因子分层回测流程文档

**创建日期**: 2026-06-01
**因子名称**: overnight_ret_1d
**因子方向**: 正向因子（ic_mean = 0.0212）

---

## 1. 因子概述

### 1.1 因子定义

隔夜收益率因子衡量非交易时段的价格变化：

```
overnight_ret = (今日开盘 - 昨日收盘) / 昨日收盘
```

其中：
- 今日开盘：当日开盘价
- 昨日收盘：前一日收盘价
- 因子值范围：[-0.1, 0.1]（A股涨跌幅限制）

### 1.2 因子特性

| 特性 | 描述 |
|------|------|
| 理论范围 | [-0.1, 0.1] |
| 含义 | 非交易时段价格变化 |
| 正值含义 | 隔夜上涨（开盘高于昨收） |
| 负值含义 | 隔夜下跌（开盘低于昨收） |
| 极端值 | 接近 ±10% 表示重大消息影响 |

### 1.3 IC 分析结果（2026-05-28）

来源：`factor_ic/result/ic_overnight_ret_1d_analysis_result.json`

```json
{
  "ic_mean": 0.021187,
  "ic_std": 0.100613,
  "icir": 0.2106,
  "p_value": 7.87e-07,
  "factor_direction": "正向因子：分层回测时做多高值组、做空低值组"
}
```

**结论**: IC 绝对值 < 0.03，预测能力较弱，但统计显著（p < 0.05）。

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
| 1 | 0-20% | 极低层 | 隔夜跌幅最大 |
| 2 | 20-40% | 偏低层 | 隔夜小幅下跌 |
| 3 | 40-60% | 正常层 | 隔夜变化不大 |
| 4 | 60-80% | 偏高层 | 隔夜小幅上涨 |
| 5 | 80-100% | 极高层 | 隔夜涨幅最大 |

### 2.2 多空组合

```python
factor_direction = 'positive'  # 正向因子
long_layers = [4, 5]   # 做多高值组（隔夜上涨）
short_layers = [1, 2]  # 做空低值组（隔夜下跌）
```

**策略逻辑**: 
- 正向因子，做多隔夜上涨组，做空隔夜下跌组
- IC 为正说明隔夜上涨预期未来收益高（利好延续效应）

### 2.3 其他参数

| 参数 | 值 | 说明 |
|------|-----|------|
| trade_cost_rate | 0.003 | 交易成本 0.3% |
| min_stocks_per_layer | 10 | 每层最小股票数 |

---

## 3. 数据加载

### 3.1 数据来源

隔夜收益率需要实时计算，数据来源：

| 数据源 | 文件 | 必需字段 |
|--------|------|---------|
| 行情数据 | factor_ic_data.json.gz | date, asset, open, close |
| 收益数据 | factor_ic_data.json.gz | date, asset, forward_return_1d |

**因子计算**: 使用 `data_fetchers.factor_calculator.calculate_overnight_return`

---

## 4. 脚本实现

### 4.1 文件位置

```
backtest/layered_backtest_overnight_ret_1d.py
```

### 4.2 核心特点

- **实时因子计算**: 需调用 calculate_overnight_return
- **正向因子配置**: factor_direction='positive'
- **简洁实现**: ~70 行（使用 factor_cli_main 公共入口）

---

## 5. 输出结果

### 5.1 输出文件

遵循 PROJECT.md 输出目录规范，结果输出到 `backtest/result/`：

| 文件 | 路径 |
|------|------|
| 回测结果 | `backtest/result/overnight_ret_layered_backtest.json` |
| 每日明细 | `backtest/result/overnight_ret_layered_backtest_daily.json.gz` |

---

## 6. 规范遵循

### 6.1 命名规范

遵循 `backtest/MODULE.md`:
- 脚本命名: `layered_backtest_<因子名>_<收益周期>.py`
- 输出命名: `<因子名>_layered_backtest.json`

### 6.2 输出目录规范

遵循 `PROJECT.md`:
- 结果输出到 `backtest/result/` 目录

### 6.3 公共模块复用

遵循 `MODULE.md` 公共模块复用规范:
- 使用 factor_cli_main 公共入口
- 使用 LayerConfigBase 基类
- 使用 calculate_overnight_return 因子计算函数

---

## 7. 注意事项

### 7.1 因子方向

IC 结果显示为正向因子（ic_mean=0.021187 > 0）。遵循 PROJECT.md 规范：因子方向不可预判，必须根据实际 IC 测试结果确定。

### 7.2 因子计算时机

隔夜收益率需要实时计算，不在缓存中预计算。

---

## 8. 变更历史

| 日期 | 版本 | 变更内容 |
|------|------|----------|
| 2026-06-01 | v1.0 | 创建流程文档 |
| 2026-06-01 | v2.1 | 修正 factor_direction 为 'positive'（遵循 IC 分析结果） |