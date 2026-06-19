# Stock Selector 覆盖率计算修复

## 问题

Section 8 选股结果中所有股票覆盖率恒为 94%，无论缺失因子数多少。

### 根因

1. **因子名/列名不匹配**（已有未提交修复 L866-871）：`last_day_weights` 键为因子名 `volume_ratio`，`factor_cols` 为列名 `volume_ratio_5`，导致 `volume_ratio` 永远不匹配 → 权重 6.5% 被排除在分子外 → max coverage = 93.54%
2. **覆盖率用 raw 值而非 std 值判断可用性**：`tail_price_position` raw=0.0（非 NaN）但 std=None。覆盖率计为"可用"但报告显示"缺失(NaN)"，与综合因子实际使用的 std 值矛盾

### 修复方案

| 修复点 | 位置 | 改动 |
|--------|------|------|
| Fix A: 因子名→列名映射 | L866-871 | 已有未提交代码，保留 |
| Fix B: 覆盖率过滤改用 std 列 | L412-414 | `result_df[col].notna()` → `result_df[std_col].notna()` |
| Fix C: per-stock 覆盖率改用 std 列 | L523-524 | `pd.notna(row[col])` → `pd.notna(row[std_col])` |

### 影响评估

- 选股结果不变：覆盖率过滤阈值 50%，修复后最低覆盖率 ~61%（600579 缺失 2 因子权重 39%），仍通过过滤
- 覆盖率显示值变化：从全部 94% → 按实际 std 缺失情况区分（100%/73%/61% 等）

### 测试更新

- `test_coverage_varies_by_missing_factors`: NaN 注入从 raw 列改到 std 列
- 新增 `test_coverage_std_nan_raw_present`: raw 非 NaN 但 std=NaN 时覆盖率正确降低
