# 量比因子 IC 分析流程文档

> 版本: v1.5
> 生成时间: 2026-05-21 02:15 北京时间
> 实测数据时间: 2026-05-21 02:15 北京时间（运行验证通过）
> 脚本: ic_volume_ratio_1d.py
> 更新内容:
>   1. v1.0 首次创建流程文档
>   2. v1.2 修复import位置、补充顶层字段、JSON序列化修复
>   3. v1.3 代码质量优化（DEFAULT_MIN_STOCKS常量、NaN处理、min_stocks参数）
>   4. v1.4 跨脚本一致性优化（2026-05-21）：
>      - 函数注释更新：ic_series → dates/ic_values/rolling_ic_mean（顶层字段）
>      - statistical_significance 添加 p_value_display 字段（跨脚本一致性）
>      - 空数据分支已有 p_value_display（无需修改）
>   5. v1.5 测试用例同步（2026-05-21 02:15）：
>      - TC001预期日志添加min_stocks参数
>      - nested_required字段添加p_value_display
>      - 版本和时间标注同步更新

---

## 整体架构

```
┌─────────────────┐
│  数据加载层      │
│ load_data_from_  │
│    cache()       │
└─────────────────┘
         │
         ▼
┌─────────────────┐
│  IC 计算层       │
│ calculate_daily_ │
│  ic_series()     │
└─────────────────┘
         │
         ▼
┌─────────────────┐
│  分层回测层      │
│ LayeredBacktest  │
│    Engine        │
└─────────────────┘
         │
         ▼
┌─────────────────┐
│  结果输出层      │
│ run_volume_      │
│ ratio_analysis() │
└─────────────────┘
```

---

## 详细流程步骤

### Step 1: 数据加载

**函数:** `load_data_from_cache()`

**输入:** 缓存文件路径
- `cache/factor_data/factor_data.json.gz`（因子数据）
- `cache/factor_data/return_data.json.gz`（收益数据）

**处理逻辑:**

```
1. 加载因子数据（gzip JSON）
   └───────────────────────────────────┐
   │ factor_df = pd.DataFrame(data)     │
   │ 列: date, asset, volume_ratio_5     │
   └───────────────────────────────────┘

2. 加载收益数据（gzip JSON）
   └───────────────────────────────────┐
   │ return_df = pd.DataFrame(data)     │
   │ 列: date, asset, forward_return_1d │
   └───────────────────────────────────┘

3. 记录原始数据范围（dropna 前）
   ┌───────────────────────────────────┐
   │ raw_period_start = min(date)       │
   │ raw_period_end = max(date)         │
   │ raw_total_days = nunique(date)     │
   └───────────────────────────────────┘

4. 过滤缺失值
   ┌───────────────────────────────────┐
   │ factor_df.dropna()                 │
   │ return_df.dropna()                 │
   └───────────────────────────────────┘

5. 验证日期对齐（MODULE.md 数据对齐验证规范）
   ┌───────────────────────────────────┐
   │ factor_dates vs return_dates       │
   │ 不对齐 → 选择交集日期              │
   │ 打印对齐信息                       │
   └───────────────────────────────────┘

6. 返回过滤后数据 + raw_metadata
```

**输出:**
```python
(factor_df, return_df, raw_metadata)
# raw_metadata = {
#   'period_start': str,
#   'period_end': str,
#   'total_days': int
# }
```

---

### Step 2: IC 计算

**函数:** `calculate_daily_ic_series()`

**输入:**
- `factor_df`：因子数据
- `return_df`：收益数据

**处理逻辑:**

```
1. 合并因子和收益数据
   ┌───────────────────────────────────────┐
   │ pd.merge(factor_df, return_df,         │
   │          on=['date', 'asset'],         │
   │          how='inner')                  │
   └───────────────────────────────────────┘

2. 按日期分组计算 Spearman Rank IC
   ┌───────────────────────────────────────┐
   │ for date, group in merged.groupby():  │
   │   if len(valid) < 10: continue        │
   │   ic = spearmanr(factor, return)      │
   └───────────────────────────────────────┘

3. 计算 20 日滚动均值
   ┌───────────────────────────────────────┐
   │ rolling_mean = ic_series.rolling(     │
   │   window=20, min_periods=10).mean()   │
   └───────────────────────────────────────┘

4. 计算统计指标
   ┌───────────────────────────────────────┐
   │ ic_mean, ic_std, icir, t_stat         │
   │ positive_ratio                        │
   └───────────────────────────────────────┘
```

**输出:**
```python
{
  'factor_name': 'volume_ratio_1d',
  'dates': list[str],
  'ic_values': list[float],
  'rolling_ic_mean': list[float],
  'ic_mean': float,
  'ic_std': float,
  'icir': float,
  'positive_ratio': float,
  't_stat': float,
  'n_days': int,
  'n_assets': int,
  'summary': str
}
```

---

### Step 3: 分层回测

**引擎:** `LayeredBacktestEngine`

**参数配置:**
```python
engine.run(
    layer_method='percentile',
    n_layers=10,
    factor_direction='positive',  # 量比是正向因子
    min_stocks_per_layer=10,
    trade_cost_rate=0.003
)
```

**处理逻辑:**

```
1. 初始化引擎
   ┌───────────────────────────────────────┐
   │ LayeredBacktestEngine(                │
   │   factor_df, return_df,               │
   │   factor_col='volume_ratio_5',        │
   │   return_col='forward_return')        │
   └───────────────────────────────────────┘

2. 执行分层回测
   ┌───────────────────────────────────────┐
   │ 正向因子：低值→Layer1，高值→Layer10   │
   │ 多空组合：Layer10 - Layer1            │
   └───────────────────────────────────────┘

3. 单调性检验
   ┌───────────────────────────────────────┐
   │ check_positive_monotonicity(          │
   │   layer_stats, n_layers=10)           │
   │ 期望：Layer收益随ID递增               │
   └───────────────────────────────────────┘
```

---

### Step 4: 结果输出

**函数:** `run_volume_ratio_analysis()`

**输出结构:**

```json
{
  "factor_name": "volume_ratio_1d",
  "calculation_date": "2026-05-21",
  "period": {
    "start": "YYYY-MM-DD",
    "end": "YYYY-MM-DD"
  },
  "ic_metrics": {
    "ic_mean": -0.03,
    "ic_std": 0.10,
    "icir": 0.30,
    "p_value": 0.0,
    "p_value_display": "0.0"
  },
  "sample_stats": {
    "total_days": 545,
    "valid_days": 514,
    "avg_stocks_per_day": 2720,
    "avg_stocks_period": {
      "start": "YYYY-MM-DD",
      "end": "YYYY-MM-DD",
      "description": "过滤后每日平均股票数（dropna 后）"
    }
  },
  "statistical_significance": {
    "t_stat": -6.93,
    "p_value": 0.0,
    "is_significant": true,
    "threshold": 1.96,
    "description": "|t|=6.93 > 1.96，统计显著"
  },
  "factor_direction": {
    "ic_mean_sign": "negative",
    "ic_mean_abs": 0.03,
    "direction_threshold": 0.03,
    "description": "IC均值=-0.0310，反向因子"
  },
  "economic_significance": {
    "icir": 0.30,
    "icir_threshold": 0.5,
    "is_economically_significant": false,
    "description": "ICIR=0.30 ≤ 0.5，不显著"
  },
  "icir_stability": {
    "is_stable": true,
    "rolling_icir_std": 0.10,
    "stability_threshold": 0.15,
    "description": "IC_std=0.10 < 0.15，稳定"
  },
  "ic_distribution_consistency": {
    "is_consistent": true,
    "positive_ratio": 0.35,
    "consistency_threshold": 0.55,
    "description": "正IC比例=34.8%，分布正常"
  },
  "layered_result": {
    "layer_stats": {...},
    "long_short": {...},
    "monotonicity": {...},
    "summary": {
      "long_short_annual_return": 0.05,
      "long_short_sharpe": 1.2,
      "monotonicity_passed": true,
      "monotonicity_correlation": 0.85,
      "monotonicity_quality": "good"
    }
  }
}
```

---

## 关键指标说明

### 五维度判断（MODULE.md 规范）

| 维度 | 指标 | 判断规则 | 说明 |
|------|------|---------|------|
| **第1维：统计显著性** | t_stat, p_value | |t| > 1.96 ↔ p < 0.05 | 统计检验是否显著 |
| **第2维：因子方向** | ic_mean符号 | ic_mean < -0.03 → 反向因子 | IC均值确定因子方向 |
| **第3维：经济显著性** | ICIR | ICIR > 0.5 → 经济显著 | 因子预测能力强度 |
| **第4维：ICIR稳定性** | IC_std | IC_std < 0.15 → 稳定 | IC波动程度 |
| **第5维：IC分布一致性** | positive_ratio | 正向因子：> 55% 正IC → 分布正常 | IC方向一致性 |

---

## 因子特性说明

**量比因子（volume_ratio_5）：**

| 特性 | 说明 |
|------|------|
| **因子定义** | 当日成交量 / 5日平均成交量 |
| **因子类型** | 正向因子（高量比 → 高收益预期） |
| **经济逻辑** | 成交量放大 → 市场关注度高 → 价格上涨 |
| **分层逻辑** | 低量比 → Layer 1，高量比 → Layer 10 |

**注意：** 因子方向必须根据实际 IC 测试结果确定，不能预设。

---

## 常见问题

### Q1: 为什么 valid_days < total_days？

**原因：**
- 因子数据缺失导致部分日期无法计算 IC
- 股票数不足（< 10 只）导致日期被跳过
- 收益数据等待（次日收益未收盘）

### Q2: 如何判断因子有效性？

**判断标准：**
1. **统计显著：** |t| > 1.96（p < 0.05）
2. **经济显著：** ICIR > 0.5
3. **方向明确：** |ic_mean| > 0.03
4. **稳定性：** IC_std < 0.15
5. **一致性：** 正 IC 比例与 IC 方向一致

### Q3: 正向因子与反向因子如何区分？

| 类型 | IC特征 | 分层逻辑 |
|------|--------|---------|
| **正向因子** | ic_mean > 0.03 | 低值→Layer1，高值→Layer10 |
| **反向因子** | ic_mean < -0.03 | 高值→Layer1，低值→Layer10 |

---

## 更新记录

| 版本 | 时间 | 更新内容 |
|------|------|---------|
| v1.0 | 2026-05-21 | 首次创建流程文档 |

---

## 参考规范

- PROJECT.md: 脚本配套文件规范
- MODULE.md: 输出结构统一性规范
- MODULE.md: 数据对齐验证规范
- MODULE.md: 五维度判断规范