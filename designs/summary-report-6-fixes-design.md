# Summary 报告 6 项问题修复

> 版本: v2.21
> 日期: 2026-06-19
> 状态: approved

## 问题清单与修复方案

### Fix 1: volume_ratio 权重矛盾（严重）

**根因**: `last_day_weights` 键用因子名(`volume_ratio`)，但 Section 4/6 代码经 `FACTOR_NAME_TO_COL_MAP` 映射到列名(`volume_ratio_5`)后查找→返回 0。Section 5 直接遍历 dict 不经映射→显示正确 6%。

**修复**: 3 处权重查找增加因子名回退：
```python
# Before
weight = comp_weights.get(factor_col, 0)
# After
weight = comp_weights.get(factor_col, comp_weights.get(factor_name, 0))
```
位置: L1280(`get_factor_selection_info`), L2037(`_detect_weight_rank_anomalies`), L2182(`_generate_comparison_section`)

### Fix 2: "其他因子均为负"事实错误

**根因**: L1525 只检查前5个因子 IC 方向(`other_ic_means[:5]`)，但 L1530 文本说"其他因子均为负"。`industry_roe_trend` IC=+0.0045 也是正值但不在前5。

**修复**: L1530 改为"其他主要因子均为负"。

### Fix 3: Section 6 编号跳过 2.

**根因**: L2247-2267 编号硬编码 1/2/3，条件 `composite_best_return < min_long_return` 为 False 时跳过 "2."，但 "3." 始终输出。

**修复**: 改为动态编号，用 `note_idx` 递增。

### Fix 4: intraday_intensity 命名不一致

**根因**: `load_backtest_results` L664-667 从 JSON 读 `factor_name` 时不剥离 `_1d`，导致 `intraday_intensity_1d` 与 IC 节的 `intraday_intensity` 不一致。IC 节 `load_ic_results` L614-615 会剥离。回测排序用 `factor_order_map` 查不到 `intraday_intensity_1d`→默认 999→排到末尾。

**修复**: `load_backtest_results` 读取 JSON `factor_name` 后，若结尾 `_1d` 且剥离后在 `FACTOR_DEFINITIONS` 中→剥离。避免误剥 `past_return_1d`（剥离后 `past_return` 不在 FD 中）。

### Fix 5: 夏普/单调性精度过高

**根因**: L1528-1529 直接用原始 float，15 位小数。

**修复**: 用 `format_float(..., 2)` 格式化。

### Fix 6: z-score 列 "≈0(真实)" 格式不统一

**根因**: L1927-1935 当 z-score≈0 且原始值≈0 时显示 `≈0(真实)`，含义不明确。

**修复**: z-score 列统一显示数值。z-score 为 None→`缺失(NaN)`，z-score≈0→`0.00`，移除 `≈0(真实)` 分支。

## 影响文件

| 文件 | 改动 |
|------|------|
| `summary/generate_factor_summary_report.py` | 6 处修复，版本 v2.20→v2.21 |
| `summary/test_cases/test_generate_factor_summary_report.py` | 新增 TestWeightLookupFallback、TestBacktestFactorNameStripping |
| `summary/docs/generate_factor_summary_report_flow.md` | 版本同步、changelog |

## 验证

```bash
ruff check --fix summary/generate_factor_summary_report.py summary/test_cases/
ruff format summary/generate_factor_summary_report.py summary/test_cases/
ruff check summary/generate_factor_summary_report.py summary/test_cases/
pytest summary/test_cases/test_generate_factor_summary_report.py -q
```
