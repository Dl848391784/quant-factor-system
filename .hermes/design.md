# design.md: Rolling ICIR T-1 NaN 权重回退策略修复

# 遵循 PROJECT.md Design-First 流程

## 问题

选股日 T-1 没有次日收益 → 无法计算 IC → rolling ICIR 为 NaN → fillna(1/n) 篏因子等权。
导致 momentum_strength 权重从 ICIR 的 2.2% 膨胀到 12.5%（+568%），使近期大跌股排名虚高。

## 修复方案

**改动范围**: `weight_engine.py` 第 508 行附近 + `stock_selector.py` 无改动

**修复逻辑**: 对 rolling ICIR NaN 做分层填充：
1. **有足够 IC 数据的因子**（长样本因子如 amplitude/momentum_strength/turnover_surge/overnight_ret）：
   - map 后仅 T-1 为 NaN → `ffill()` 用 T-2 的有效值向前填充
2. **IC 数据不足的因子**（短样本 tail_* 系列，18天 < 60日窗口）：
   - map 后整段时间全 NaN → `ffill()` 无法填充 → 仍 NaN → `fillna(1/n)` 兜底

代码改动位置: `weight_engine.py` 第 508-510 行之后，插入 ffill() 和分层的 fillna()

```python
# 当前代码（line 508-510）:
factor_df[f"{col}_rolling_icir"] = factor_df["date_sorted"].map(rolling_icir_series_dt)
# ... else:
factor_df[f"{col}_rolling_icir"] = np.nan

# 修复后:
factor_df[f"{col}_rolling_icir"] = factor_df["date_sorted"].map(rolling_icir_series_dt)
# T-1 无 IC 数据 → map 返回 NaN → ffill() 用最近有效值填充
# 短样本因子(全 NaN) → ffill 无法填充 → 仍然 NaN → 下面 fillna(1/n) 兜底
factor_df[f"{col}_rolling_icir"] = factor_df[f"{col}_rolling_icir"].ffill()
```

line 531 保持不变（`fillna(1/n)` 作为最终兜底，处理 ffill 无法填充的全 NaN 因子）

## 验证方案

1. 运行 stock_selector.py → 600779/002351 不再出现在 Top 3
2. 检查报告权重与选股权重一致性
3. pytest 稡拟 T-1 NaN → ffill 场景

## 涉及文件数: 1（weight_engine.py），行数约 2 行

## 规范引用
- 遵循 MODULE.md M7（滚动 ICIR 时间轴计算）
- 遵循 MODULE.md M40（滚动 ICIR 时间轴）
- 遵循 AGENTS.md 陷阱 2（无冗余向后兼容假设）