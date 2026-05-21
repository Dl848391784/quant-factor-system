# 量比因子 IC 分析流程文档

> 版本: v1.9
> 生成时间: 2026-05-23 22:45 北京时间
> 实测数据时间: 2026-05-23 22:45 北京时间（运行验证通过）
> 脚本: ic_volume_ratio_1d.py（236行）
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
>   6. v1.6 Newey-West 重构（2026-05-21 02:25）：
>      - 改用公共模块 ic_calculator.py（Newey-West 标准）
>      - statistical_significance 结构升级：添加 nw_lag, nw_lag_method, conclusion 字段
>      - 五维度判断全部使用公共模块标准结构（与 ic_kdj_j_1d.py 对齐）
>      - 空数据分支同步更新五维度结构
>      - 实测结果：IC=-0.031, ICIR=0.31, t_stat=-7.13（NW调整）, nw_lag=5
>   7. v1.7 废弃代码清理（2026-05-21 02:31）：
>      - 删除废弃函数 calculate_daily_ic_series（已改用公共模块）
>      - 删除废弃导入：spearmanr, scipy_stats_norm（公共模块已包含）
>      - 删除废弃变量：scipy_stats_norm_cdf（不再使用）
>      - 代码行数减少：776行 → 690行（精简86行）
>      - 运行验证通过：IC=-0.031, ICIR=0.31
>   8. v1.8 文档架构图更新（2026-05-21 02:35）：
>      - 架构图更新：calculate_daily_ic_series → calculate_ic_with_direction_verification（公共模块）
>      - 测试用例同步更新：nw_lag字段、五维度结构对齐、预期日志格式
>      - 三文件版本同步：脚本v1.7、流程文档v1.8、测试用例v1.7
>   9. v1.9 SKIP模式修复+异常处理优化（2026-05-23 22:45）：
>      - SKIP模式不修改缓存对象（遵循 MODULE.md v3.7 规范）
>      - 新增内部函数 do_full_recalculate() 处理 SKIP fallback
>      - 数据加载异常分开处理（FileNotFoundError/JSONDecodeError/PermissionError/KeyError/Exception）
>      - 步骤编号统一为 [N/4]
>      - 日志取值路径统一使用 result['ic_metrics']
>      - 代码行数：271行 → 236行（精简35行）
>      - 运行验证通过（SKIP模式正常工作）

---

## 整体架构

```
┌─────────────────┐
│  数据加载层      │
│ load_factor_     │
│ return_data()    │（公共模块）
└─────────────────┘
         │
         ▼
┌─────────────────┐
│  模式判断层      │
│ should_use_      │
│ incremental()    │（公共模块）
└─────────────────┘
         │
    ┌────┴────┐
    │  三模式  │
    ▼    ▼    ▼
┌────┐ ┌────┐ ┌────┐
│SKIP│ │INCR│ │FULL│
└────┘ └────┘ └────┘
    │    │    │
    │    │    ▼
    │    │  ┌─────────────────┐
    │    │  │ do_full_        │
    │    │  │ recalculate()   │（内部函数）
    │    │  └─────────────────┘
    │    │         │
    │    ▼         ▼
    │  ┌─────────────────┐
    │  │ incremental_    │
    │  │ update_ic()     │（公共模块）
    │  └─────────────────┘
    │         │
    ▼    ▼    ▼
┌─────────────────┐
│  结果输出层      │
│ build_ic_result │（公共模块）
│ save_ic_result  │
└─────────────────┘
```

---

## 详细流程步骤

### Step 1: 数据加载（[1/4]）

**函数:** `load_factor_return_data()`（公共模块）

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

6. 异常处理（分开处理多种类型）
   ┌───────────────────────────────────┐
   │ FileNotFoundError → 数据源缺失     │
   │ JSONDecodeError → 缓存损坏        │
   │ PermissionError → 权限错误        │
   │ KeyError → 数据结构错误           │
   │ Exception → 未预期错误            │
   └───────────────────────────────────┘

7. 返回过滤后数据 + raw_metadata
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

### Step 2: 模式判断

**函数:** `should_use_incremental()`（公共模块）

**判断逻辑:**

```
缓存不存在 → FULL（全量计算）
缓存存在 → 读取 existing_dates
比较 existing_dates vs factor_dates:
  existing_dates ⊇ factor_dates → SKIP（跳过）
  factor_dates 有缺失 → INCREMENTAL（增量）
```

---

### Step 3: SKIP 模式处理（新增规范）

**核心原则:** SKIP 模式不修改缓存对象，直接返回原数据。

**处理逻辑:**

```
┌─────────────────────────────────────┐
│ if mode == UpdateMode.SKIP:         │
│   cached_data = json.load(cache)    │
│   # 不修改 cached_data              │
│   return cached_data                │
│                                     │
│   except FileNotFoundError:         │
│     # fallback 到全量计算            │
│     return do_full_recalculate()    │
└─────────────────────────────────────┘
```

**为何不修改缓存对象:**

| 原因 | 说明 |
|------|------|
| 内存文件一致性 | 修改后不持久化，调用方数据与文件不同步 |
| 行为可预测 | 下次读取时缓存内容不变，行为一致 |
| 遵循最小修改原则 | SKIP 模式语义是"跳过"，不应有任何修改 |

---

### Step 4: INCREMENTAL 模式处理

**函数:** `incremental_update_ic()`（公共模块）

**步骤:**

```
[2/4] 因子已在缓存中，跳过因子计算
[3/4] 执行增量 IC 计算
      ┌─────────────────────────────────┐
      │ 读取现有缓存                     │
      │ 确定缺失日期                     │
      │ 计算缺失日期 IC（复用核心函数）   │
      │ 合并数据（去重）                 │
      │ 重算统计指标                     │
      └─────────────────────────────────┘
```

---

### Step 5: FULL 模式处理

**内部函数:** `do_full_recalculate()`

**步骤:**

```
[3/4] 计算每日 IC
      ┌─────────────────────────────────┐
      │ calculate_ic_with_direction_    │
      │ verification()（公共模块）       │
      └─────────────────────────────────┘

[4/4] 构建输出并保存
      ┌─────────────────────────────────┐
      │ build_ic_result()               │
      │ convert_to_native_types()       │
      │ save_ic_result()                │
      └─────────────────────────────────┘
```

---

### Step 6: 结果输出

**输出结构:**

```json
{
  "factor_name": "volume_ratio_1d",
  "calculation_date": "2026-05-23",
  "period": {
    "start": "2024-02-06",
    "end": "2026-05-15"
  },
  "ic_metrics": {
    "ic_mean": -0.031,
    "ic_std": 0.10,
    "icir": 0.31,
    "p_value": 9.86e-13,
    "p_value_display": "9.86e-13"
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
    "t_stat": -7.13,
    "p_value": 9.86e-13,
    "p_value_display": "9.86e-13",
    "nw_lag": 5,
    "nw_lag_method": "newey_west",
    "is_significant": true,
    "conclusion": "|t|=7.13 > 1.96，统计显著"
  },
  "factor_direction": {
    "ic_mean": -0.031,
    "ic_mean_sign": "negative",
    "direction_usage": "反向因子",
    "conclusion": "IC均值=-0.031<0，反向因子"
  },
  "economic_significance": {
    "abs_ic_mean": 0.031,
    "level": "weak",
    "is_economically_significant": true,
    "conclusion": "|IC|=0.031 >= 0.03，弱显著"
  },
  "icir_stability": {
    "icir": 0.31,
    "level": "unusable",
    "is_stable": true,
    "conclusion": "ICIR=0.31 < 0.5，不显著"
  },
  "ic_distribution_consistency": {
    "positive_ratio": 0.35,
    "ic_mean_sign": "negative",
    "consistency_type": "consistent_with_negative",
    "is_consistent": true,
    "conclusion": "正IC比例=35%，分布正常（反向因子）"
  },
  "dates": ["..."],
  "ic_values": ["..."],
  "rolling_ic_mean": ["..."],
  "positive_ratio": 0.35,
  "n_assets": 2720,
  "summary": {
    "ic_performance": "IC均值=-0.031, ICIR=0.31",
    "statistical_significance": "|t|=7.13 > 1.96，统计显著",
    "factor_direction": "IC均值=-0.031<0，反向因子",
    "economic_significance": "|IC|=0.031 >= 0.03，弱显著",
    "recommendation": "请结合五维度判断综合评估"
  },
  "factor_stats": {
    "factor_name": "volume_ratio_1d",
    "return_period": "1d",
    "data_source": "cache/factor_data/factor_data.json.gz",
    "total_days": 545,
    "valid_days": 514
  },
  "factor_col": "volume_ratio_5",
  "update_mode": "full"
}
```

---

## 关键指标说明

### 五维度判断（MODULE.md 规范）

| 维度 | 指标 | 判断规则 | 说明 |
|------|------|---------|------|
| **第1维：统计显著性** | t_stat, p_value | |t| > 1.96 ↔ p < 0.05 | 统计检验是否显著 |
| **第2维：因子方向** | ic_mean符号 | ic_mean < -0.03 → 反向因子 | IC均值确定因子方向 |
| **第3维：经济显著性** | |ic_mean| | |IC| >= 0.03 → 弱显著 | 因子预测能力强度 |
| **第4维：ICIR稳定性** | ICIR | ICIR >= 0.5 → 可用 | IC信息比强度 |
| **第5维：IC分布一致性** | positive_ratio | 反向因子：< 45% 正IC → 分布正常 | IC方向一致性 |

---

## 因子特性说明

**量比因子（volume_ratio_5）：**

| 特性 | 说明 |
|------|------|
| **因子定义** | 当日成交量 / 5日平均成交量 |
| **因子类型** | 反向因子（实测 ic_mean = -0.031） |
| **分层逻辑** | 高量比 → Layer 1（反向因子分层） |

**注意：** 因子方向必须根据实际 IC 测试结果确定，不能预设。

---

## 常见问题

### Q1: SKIP 模式为何不修改缓存对象？

**原因：**
- 修改 `cached_data['update_mode'] = 'skip'` 后不持久化
- 内存数据与文件不一致，下次读取行为不可预测
- SKIP 模式语义是"跳过"，不应有任何修改

### Q2: 为什么 valid_days < total_days？

**原因：**
- 因子数据缺失导致部分日期无法计算 IC
- 股票数不足（< 10 只）导致日期被跳过
- 收益数据等待（次日收益未收盘）

### Q3: 如何判断因子有效性？

**判断标准：**
1. **统计显著：** |t| > 1.96（p < 0.05）
2. **经济显著：** |ic_mean| > 0.03
3. **ICIR可用：** ICIR > 0.5
4. **稳定性：** IC_std < 0.15
5. **一致性：** 正 IC 比例与 IC 方向一致

---

## 参考规范

- PROJECT.md: SKIP 模式缓存对象处理规范（第319-360行）
- PROJECT.md: 主函数数据加载异常处理规范（第100-113行）
- MODULE.md: 输出结构统一性规范
- MODULE.md: 五维度判断规范
- MODULE.md: 数据对齐验证规范