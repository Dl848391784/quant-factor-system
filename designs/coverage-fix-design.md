# Design: stock_selector 覆盖率计算修复

## 问题

Section 8 所有股票覆盖率恒为 94%，无论缺失因子数多少。

### 根因（双重）

1. **因子名≠列名**（已有未提交修复 L866-871）：`last_day_weights` 键=`volume_ratio`（因子名），`factor_cols`=`volume_ratio_5`（列名）→ 该因子永远被排除在覆盖率分子外
2. **覆盖率用 raw 值而非 std 值**（本次修复）：raw 值 0.0/-1.0 非 NaN 但 std=None → 缺失因子被误判为"可用"

### 修复方案

| 修复点 | 文件 | 行号 | 改动 |
|--------|------|------|------|
| Fix A: 因子名→列名映射 | stock_selector.py | L866-871 | 已有（未提交），保留 |
| Fix B: 覆盖率过滤用 _std 列 | stock_selector.py | L412-414 | `result_df[col]` → `result_df[f"{col}_std"]` |
| Fix C: 逐股覆盖率用 _std 列 | stock_selector.py | L523-524 | `row[col]` → `row[f"{col}_std"]` |
| Fix D: 测试更新 | test_stock_selector.py | L385 | 注入 NaN 到 `_std` 列而非 raw 列 |

### 为什么用 std 而非 raw

- 综合因子 = Σ(weight × std)，std=None → 因子不贡献 → 权重"浪费"
- 报告显示 z-score（std 值），"缺失(NaN)" = std=None
- 覆盖率应反映"多少权重实际贡献了综合因子"

### 影响评估

- 不改变选股结果（覆盖率过滤阈值 50%，修复后最低股票 ~61% > 50%）
- 覆盖率显示值变化：完整股票 94%→100%，缺失股票 94%→61-73%
