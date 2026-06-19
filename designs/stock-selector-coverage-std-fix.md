# Design: 修复 stock_selector 覆盖率计算 Bug

## 问题

Section 8 选股结果中所有 10 只股票覆盖率恒为 94%，无论缺失因子数多少。

### 根因（双重）

1. **因子名/列名不匹配**（已有未提交修复 L866-871）：
   - `last_day_weights` 键 = 因子名 `volume_ratio`
   - `factor_cols` = 列名 `volume_ratio_5`
   - 覆盖率计算 `col in factor_cols` = False → `volume_ratio` 永远被排除
   - max coverage = 1 - 0.0646 = 0.9354 = 94%

2. **覆盖率用 raw 值而非 std 值判断**（本次修复）：
   - `tail_price_position` raw=0.0（非NaN）但 std=None（NaN）
   - 覆盖率用 `pd.notna(row[col])` 检查 raw → 0.0 非 NaN → 计为"可用"
   - 报告显示用 std → 显示"缺失(NaN)"
   - 结果：即使 std=None 的因子也被计为可用 → 覆盖率虚高

### 修复方案

**覆盖率计算改用 `_std` 列**：综合因子使用 std 值加权计算，若 std=None 则该因子不贡献（中性填充 z=0），覆盖率应反映 std 的缺失情况。

| 位置 | 修改前 | 修改后 |
|------|--------|--------|
| L412-414（过滤） | `result_df[col].notna()` | `result_df[std_col].notna()` |
| L523-524（per-stock） | `pd.notna(row[col])` | `pd.notna(row[std_col])` |

### 影响评估

- 选股结果不变：覆盖率过滤阈值 50%，最低 coverage 约 61%（>50%）
- 覆盖率显示更准确：无缺失=100%，缺失高权重因子→覆盖率下降
- 测试需更新：`test_coverage_varies_by_missing_factors` 注入 NaN 从 raw 列改到 std 列

### 修复后预期覆盖率

| 股票 | 缺失因子(std=None) | 预期覆盖率 |
|------|---------------------|-----------|
| 603020 | 无 | 100% |
| 001216 | tail_price_position(27%) | 73% |
| 600579 | tail_price_position(27%) + tail_price_position_delta(12%) | 61% |
