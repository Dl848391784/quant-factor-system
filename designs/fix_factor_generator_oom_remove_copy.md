# Design: factor_generator 去除 32 处整表 .copy() 修复 OOM

## 问题

factor_generator 在 7.3GB 系统上被 OOM killer SIGKILL（anon-rss 4.99GB）。
根因：32 处 `df = factor_df.copy()` 整表拷贝，每次复制 149~1055 MB，
累计分配压力 ~13.4 GB，堆碎片化导致 RSS 不回落。

## 根因（第一性原理）

### 数据规模
- 1,503,487 行 × 65→92 列（Step 3.5→14 过程中列数膨胀）
- 纯数据量：Step 3.5 = 149 MB → Step 14 = 1055 MB
- 每次 .copy() 峰值：Step 3.5 = 298 MB → Step 14 = 2111 MB（old+new 同时存在）

### 调用链安全分析

```
generate_all_factors()
  └─ factor_df = _load_and_merge_data(...)     # factor_df 唯一引用
     └─ factor_df, _ = _run_factor_pipeline(factor_df, logger)
        └─ for step in _FACTOR_PIPELINE_STEPS:
              factor_df, _ = _run_pipeline_step(factor_df, step, logger)
                 └─ factor_df = factor_func(factor_df, ...)  # 旧引用丢弃
```

**关键事实**：`_run_pipeline_step` 做 `factor_df = factor_func(factor_df, ...)` 重新赋值，
调用方不再持有旧引用。因此 factor_func 内部"修改输入 df 加列"不会产生副作用。

### 32 处 .copy() 分类

全部 32 处都是 **SAFE 模式**（只添加新列，不修改已有列）：

| 文件 | .copy() 数 | 函数 |
|------|-----------|------|
| momentum.py | 10 | price_position, amplitude, past_return_1d, return_3d, return_5d, momentum_strength, overnight_return, rsi_slope_3d, ma5_slope, lower_shadow_ratio |
| basic.py | 4 | bollinger_pb, kdj_j, turnover_surge, rsi_df |
| volume_price.py | 6 | volume_price_strength, positive_day_ratio_5, ma5_deviation, near_high_ratio_5, volume_shrink_rate, price_volume_divergence |
| industry.py | 3 | industry_momentum_5d, industry_turnover_trend, industry_amplitude_trend |
| industry_financial.py | 4 | industry_roe_trend, industry_earnings_growth, industry_pe_trend, industry_financial_block |
| fund_flow.py | 3 | capital_flow_ratio_trend, capital_flow_intensity, capital_flow_block |
| intraday.py | 1 | intraday_intensity |
| _common.py | 1 | _calculate_delta |

### 已有的"不 copy"先例

代码中已有 2 个函数用 `sort_values(inplace=False)` 替代 `.copy()`：
- `calculate_return_acceleration_5d` (L832)
- `calculate_downside_deceleration` (L875)

sort_values 返回新对象，加列安全。这证明了"不 copy 直接加列"在项目中是可行且已验证的模式。

## 修复方案

### 策略：按函数是否需要 sort_values 分两类

**类型 A：不需要排序的函数（直接加列）**
```python
# Before:
df = factor_df.copy()
df["new_col"] = ...
return df

# After:
factor_df["new_col"] = ...
return factor_df
```

**类型 B：需要 sort_values 的函数**
```python
# Before:
df = factor_df.copy()
df = df.sort_values(["asset", "date"])
df["new_col"] = ...
return df

# After (sort_values 已返回新对象，无需 copy):
df = factor_df.sort_values(["asset", "date"])
df["new_col"] = ...
return df
```

**类型 C：使用临时列的函数（如 momentum_strength）**
```python
# Before:
df = factor_df.copy()
df = df.sort_values(...)
df["_temp1"] = ...
df["_temp2"] = ...
df["new_col"] = ...
del df["_temp1"]
del df["_temp2"]
return df

# After:
df = factor_df.sort_values(...)
df["_temp1"] = ...
df["_temp2"] = ...
df["new_col"] = ...
del df["_temp1"]
del df["_temp2"]
return df
```

### 同步更新

1. **MODULE.md L1111**：将"函数入口必须 `.copy()` 避免副作用"改为：
   "函数入口**禁止** `.copy()` 整表拷贝（OOM 根因）；直接在输入 df 上加列，
   因为 `_run_pipeline_step` 重新赋值后旧引用立即丢弃"

2. **函数 docstring**：删除"函数入口必须先 .copy()"注释

### 不修改的文件

- `_calculate_interaction_variant` (momentum.py L946) -- 已用 `assign()` 不 copy，是正确模式
- `calculate_return_acceleration_5d` / `calculate_downside_deceleration` -- 已用 sort_values 替代 copy

## 执行计划（3 轮）

### Round 1: momentum.py (10 处) + basic.py (4 处) = 14 处
- 修改 14 个函数：去除 `df = factor_df.copy()`，按类型 A/B/C 改
- ruff + pytest
- git commit

### Round 2: volume_price.py (6 处) + industry.py (3 处) + intraday.py (1 处) = 10 处
- 修改 10 个函数
- ruff + pytest
- git commit

### Round 3: industry_financial.py (4 处) + fund_flow.py (3 处) + _common.py (1 处) = 8 处
- 修改 8 个函数
- MODULE.md L1111 规范同步更新
- ruff + pytest
- git commit

### 验证
- 每轮 ruff check + ruff format + pytest
- 最终：手动运行 factor_generator 确认无 OOM
- 确认 parquet 末日期更新到 2026-07-13

## 风险评估

### 低风险
- 32 处全部是 SAFE 模式（只加列，不改已有列）
- 已有 2 个不 copy 的先例函数验证可行
- `_run_pipeline_step` 调用链确保旧引用立即丢弃

### 测试覆盖
- 现有 test_cases 中有 interaction 测试 + 各 factor_calculator 测试
- pytest 覆盖率 >70% 要求可验证回归
