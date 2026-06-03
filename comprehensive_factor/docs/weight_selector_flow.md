# weight_selector.py 流程文档

> 版本: v1.0
> 最后更新: 2026-06-03
> 对应脚本版本: v1.4

---

## 概述

权重选择器从4种权重方式（equal_weight, ic_weight, icir_weight, rolling_icir_weight）中选择最优方案。

---

## 流程图

```
┌─────────────────────────────────────────────────────────────────┐
│                    weight_selector.py 流程                        │
├─────────────────────────────────────────────────────────────────┤
│                                                                   │
│  Step 1: 加载综合因子结果                                          │
│  ├─ 输入: result_dir, weight_methods, return_period              │
│  ├─ 文件: composite_{method}_{return_period}.json                │
│  ├─ 处理: 验证目录存在 → 遍历文件 → JSON解析                        │
│  └─ 输出: Dict[method, result_data]                              │
│                                                                   │
│  Step 2: 提取评价指标                                              │
│  ├─ 输入: composite 结果                                          │
│  ├─ 提取路径:                                                      │
│  │   ├─ long_short_return_annual ← backtest_result.long_short    │
│  │   ├─ long_short_sharpe ← backtest_result.long_short           │
│  │   ├─ long_return_annual ← layer_1/layer_2 annual_return 均值  │
│  │   ├─ long_sharpe ← layer_1/layer_2 sharpe_ratio 均值          │
│  │   ├─ monotonicity_abs ← abs(monotonicity.correlation)         │
│  │   ├─ long_short_net_daily ← trading_cost_analysis             │
│  │   ├─ turnover_long_avg ← long_short                           │
│  │   ├─ turnover_short_avg ← long_short                          │
│  │   ├─ max_drawdown ← max(layer_1, layer_2 max_drawdown)        │
│  └─ 输出: Dict[method, Dict[metric, value]] (9个指标)            │
│                                                                   │
│  Step 3: Min-Max归一化                                            │
│  ├─ 输入: metrics_data, metric_configs                            │
│  ├─ 处理:                                                         │
│  │   ├─ 计算每个指标的 min/max                                     │
│  │   ├─ 处理除零（diff < EPSILON → 全给1.0）                       │
│  │   ├─ higher_better: (val - min) / diff                        │
│  │   ├─ lower_better: (max - val) / diff                         │
│  └─ 输出: Dict[method, Dict[metric, normalized_score]] [0,1]     │
│                                                                   │
│  Step 4: 计算综合得分                                              │
│  ├─ 输入: normalized_scores, metric_configs                       │
│  ├─ 处理: 等权平均（weight=1.0）                                   │
│  ├─ 公式: score = Σ(score_i * weight_i) / Σ(weight_i)            │
│  └─ 输出: Dict[method, final_score]                               │
│                                                                   │
│  Step 5: 选择最优方法                                              │
│  ├─ 输入: final_scores                                            │
│  ├─ 防御性检查: if not final_scores → ValueError                  │
│  ├─ 处理: sorted降序 → 取第一个                                    │
│  └─ 输出: (best_method, best_score, ranked_list)                 │
│                                                                   │
│  Step 6: 输出结果                                                  │
│  ├─ 输入: metrics_data, normalized_scores, final_scores, etc.    │
│  ├─ 构建: meta + best_selection + ranking + metric_configs       │
│  ├─ 保存: weight_selection_result.json                           │
│  └─ 日志: 排名表输出                                               │
│                                                                   │
└─────────────────────────────────────────────────────────────────┘
```

---

## 指标配置表

| 指标 | 方向 | 权重 | 说明 |
|------|------|------|------|
| long_short_return_annual | higher_better | 1.0 | 多空年化收益 |
| long_short_sharpe | higher_better | 1.0 | 多空夏普比率 |
| long_return_annual | higher_better | 1.0 | 多头年化收益 |
| long_sharpe | higher_better | 1.0 | 多头夏普比率 |
| monotonicity_abs | higher_better | 1.0 | 单调性相关性绝对值 |
| long_short_net_daily | higher_better | 1.0 | 成本后日收益 |
| turnover_long_avg | lower_better | 1.0 | 多头换手率 |
| turnover_short_avg | lower_better | 1.0 | 空头换手率 |
| max_drawdown | lower_better | 1.0 | 最大回撤 |

---

## 输出结构

```json
{
  "meta": {
    "created_at": "2026-06-03T...",
    "total_methods": 4,
    "total_metrics": 9,
    "normalization_method": "min-max",
    "weight_strategy": "equal-weight"
  },
  "best_selection": {
    "method": "icir_weight",
    "composite_score": 0.7273,
    "selection_reason": "综合得分最高"
  },
  "ranking": [
    {
      "rank": 1,
      "method": "icir_weight",
      "composite_score": 0.7273,
      "metric_scores": {...},
      "raw_values": {...}
    },
    ...
  ],
  "metric_configs": {
    "long_short_return_annual": {
      "direction": "higher_better",
      "weight": 1.0,
      "description": "多空年化收益"
    },
    ...
  }
}
```

---

## 边界处理

| 场景 | 处理方式 | 位置 |
|------|---------|------|
| 结果目录不存在 | FileNotFoundError | load_composite_results |
| 单个文件不存在 | warning + skip | load_composite_results |
| JSON解析失败 | error + skip | load_composite_results |
| 无结果文件 | error + return | main() |
| final_scores为空 | ValueError | select_best_method |
| 归一化除零 | EPSILON容差 → 全给1.0 | normalize_minmax |

---

## CLI 使用

```bash
python weight_selector.py \
    --result-dir comprehensive_factor/result \
    --output comprehensive_factor/result/weight_selection_result.json \
    --return-period 1d
```

---

## 数据依赖

| 输入文件 | 来源模块 | 内容 |
|---------|---------|------|
| composite_*.json | comprehensive_factor | 综合因子回测结果 |

---

*创建时间: 2026-06-03*