# 覆盖率计算修复设计

## 问题

Section 8 选股结果中所有股票覆盖率恒为 94%，无论缺失因子数多少。

## 根因

1. **因子名/列名不匹配**（L866-871 已有未提交修复）：`last_day_weights` 键为因子名 `volume_ratio`，`factor_cols` 为列名 `volume_ratio_5`
2. **覆盖率用 raw 值判断而非 std 值**（本次修复）：raw 值 0.0/-1.0 非 NaN 但 std=None，覆盖率误判因子"可用"

## 修复方案

| 位置 | 修改 |
|------|------|
| L412-414（覆盖率过滤） | `result_df[col].notna()` → `result_df[f"{col}_std"].notna()` |
| L523-524（per-stock 覆盖率） | `pd.notna(row[col])` → `pd.notna(row[f"{col}_std"])` |
| test L385 | `df.loc[0, "rsi_6"] = np.nan` → `df.loc[0, "rsi_6_std"] = np.nan` |
| test 新增 | 测试 raw 非 NaN 但 std=None 的场景 |

## 影响评估

- 覆盖率过滤阈值 50%：修复后最低股票 600579 覆盖率≈61% > 50%，不影响选股结果
- 综合因子值不变（用 std 计算，覆盖率仅用于显示和过滤）
