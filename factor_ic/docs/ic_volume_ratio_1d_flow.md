# Volume_Ratio_1D IC 计算流程文档

> 生成时间: 2026-05-21 05:00 (北京时间)
> 审阅版本: v1.1
> 实测数据时间: 2026-05-15
> 更新内容:
>   1. [v1.1] 修复 p_value 计算错误：scipy.stats.stats.norm.cdf -> scipy.stats.norm.cdf
>   2. [v1.1] 修复 n_days 变量未定义：params['n_days'] 使用 ic_data['n_days']
>   3. [v1.1] 添加五维度判断字段：statistical_significance、factor_direction、economic_significance、icir_stability、ic_distribution_consistency（遵循 MODULE.md 输出结构统一性规范）
>   4. [v1.1] 修复 sample_stats['total_days'] 口径：使用 raw_metadata['total_days']（原始缓存日期数）
>   5. [v1.1] 添加 avg_stocks_period 字段：口径范围说明（遵循 MODULE.md 统计口径规范）
>   6. [v1.1] 添加 raw_metadata 字段：原始缓存元信息（遵循 MODULE.md 输出结构统一性规范）
>   7. [v1.1] 添加 update_mode 字段：更新模式标记（遵循 MODULE.md 输出结构统一性规范）
>   8. [v1.1] 删除 significance 星号标识字段：遗留字段清理（遵循 MODULE.md 输出结构统一性规范）
>   9. [v1.1] 添加主入口错误处理：try-except 块捕获 FileNotFoundError/ValueError/RuntimeError/Exception（遵循 MODULE.md 主入口错误处理规范）

---

## 概述

本文档描述量比因子（Volume Ratio 1D）IC 计算的完整流程。

**因子定义：**
- 量比 = 当日成交量 / 5日平均成交量
- 正向因子：高量比 → 高预期收益

---

## 流程图

```
┌─────────────────────────────────────────────────────────────┐
│                    ic_volume_ratio_1d.py                     │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│  Step 1: 加载缓存数据                                         │
│  ────────────────────────────────────────────────────────── │
│  load_data_from_cache()                                      │
│    - 加载 factor_data.json.gz                                │
│    - 加载 return_data.json.gz                                │
│    - 过滤缺失值                                               │
│    - 返回 raw_metadata（原始缓存元信息）                       │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│  Step 2: 计算每日 IC                                          │
│  ────────────────────────────────────────────────────────── │
│  calculate_daily_ic_series()                                 │
│    - 合并因子和收益数据                                        │
│    - 按日期分组计算 Spearman Rank IC                          │
│    - 计算 ICIR、t_stat、positive_ratio                        │
│    - 计算 20 日滚动均值                                        │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│  Step 3: 分层回测                                             │
│  ────────────────────────────────────────────────────────── │
│  LayeredBacktestEngine.run()                                 │
│    - 10 层等频分层                                            │
│    - 正向因子分层：低量比 → Layer1，高量比 → Layer10           │
│    - 多空组合：Layer10 - Layer1                               │
│    - 单调性检验                                               │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│  Step 4: 构建输出结果                                         │
│  ────────────────────────────────────────────────────────── │
│  五维度判断（遵循 MODULE.md 输出结构统一性规范）                │
│    - statistical_significance（统计显著性）                   │
│    - factor_direction（因子方向）                             │
│    - economic_significance（经济显著性）                      │
│    - icir_stability（ICIR 稳定性）                            │
│    - ic_distribution_consistency（IC 分布一致性）             │
│                                                              │
│  附加字段                                                     │
│    - raw_metadata（原始缓存元信息）                           │
│    - update_mode（更新模式标记）                              │
│    - avg_stocks_period（口径范围说明）                        │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
                        输出 JSON 文件
```

---

## 输出结构（遵循 MODULE.md 输出结构统一性规范）

```json
{
  "factor_name": "volume_ratio_1d",
  "calculation_date": "2026-05-21",
  "period": {
    "start": "2024-02-06",
    "end": "2026-05-15"
  },
  "ic_metrics": {
    "ic_mean": -0.0310,
    "ic_std": 0.1093,
    "icir": 0.31,
    "p_value": 0.000001,
    "positive_ratio": 0.348,
    "t_stat": -6.93
  },
  "sample_stats": {
    "total_days": 545,
    "valid_days": 514,
    "avg_stocks_per_day": 2720,
    "avg_stocks_period": {
      "start": "2024-02-06",
      "end": "2026-05-15",
      "description": "过滤后每日平均股票数（dropna 后）"
    }
  },
  "statistical_significance": {
    "t_stat": -6.93,
    "p_value": 0.000001,
    "is_significant": true,
    "threshold": 1.96,
    "description": "|t|=6.93 > 1.96，统计显著"
  },
  "factor_direction": {
    "ic_mean_sign": "negative",
    "ic_mean_abs": 0.0310,
    "direction_threshold": 0.03,
    "description": "IC均值=-0.0310，反向因子"
  },
  "economic_significance": {
    "icir": 0.31,
    "icir_threshold": 0.5,
    "is_economically_significant": false,
    "description": "ICIR=0.31 ≤ 0.5，不显著"
  },
  "icir_stability": {
    "is_stable": true,
    "rolling_icir_std": 0.1093,
    "stability_threshold": 0.15,
    "description": "IC_std=0.1093 < 0.15，稳定"
  },
  "ic_distribution_consistency": {
    "is_consistent": true,
    "positive_ratio": 0.348,
    "consistency_threshold": 0.55,
    "description": "正IC比例=34.8%，分布正常"
  },
  "ic_series": {
    "dates": ["2024-02-06", ...],
    "ic_values": [-0.031, ...],
    "rolling_ic_mean": [null, ...]
  },
  "layered_result": {
    "layer_stats": {...},
    "long_short": {...},
    "monotonicity": {...},
    "summary": {...}
  },
  "raw_metadata": {
    "period_start": "2024-02-06",
    "period_end": "2026-05-15",
    "total_days": 545
  },
  "update_mode": "full",
  "params": {
    "n_days": 514,
    "num_layers": 10,
    "factor_col": "volume_ratio_5",
    "return_col": "forward_return_1d",
    "factor_direction": "positive",
    "trade_cost_rate": 0.003,
    "min_stocks_per_layer": 10
  },
  "generated_at": "2026-05-21T05:00:00"
}
```

---

## 关键修复记录

| 问题 | 原代码 | 修复后 |
|------|--------|--------|
| p_value 计算错误 | `__import__('scipy.stats').stats.norm.cdf` | `scipy.stats.norm.cdf` |
| n_days 变量未定义 | `params['n_days'] = n_days` | `params['n_days'] = ic_data['n_days']` |
| total_days 口径错误 | `len(all_dates)` | `raw_metadata['total_days']` |
| 缺少五维度判断 | 无 | 5 个字段 |
| 缺少 raw_metadata | 无 | 原始缓存元信息 |
| 缺少 update_mode | 无 | 更新模式标记 |
| 缺少 avg_stocks_period | 无 | 口径范围说明 |
| significance 遗留字段 | `'significance': significance` | 删除 |

---

## 五维度判断规范

| 维度 | 字段名 | 判断条件 |
|------|--------|----------|
| 第1维 | statistical_significance | |t| > 1.96（p < 0.05） |
| 第2维 | factor_direction | |IC均值| > 0.03 |
| 第3维 | economic_significance | ICIR > 0.5 |
| 第4维 | icir_stability | IC_std < 0.15 |
| 第5维 | ic_distribution_consistency | 正IC比例与因子方向一致 |

---

## 注意事项

1. **因子方向判断阈值：** ±0.03（基于 PROJECT.md 规范）
2. **统计显著性阈值：** |t| > 1.96（等价于 p < 0.05）
3. **ICIR 使用绝对值：** `abs(ic_mean) / ic_std`（遵循 PROJECT.md 规范）
4. **分层回测超时：** 计算耗时较长，建议减少日期范围或调整参数

---

*最后更新: 2026-05-21 05:00 (v1.1)*