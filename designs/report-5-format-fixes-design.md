# Design: 报告5项格式问题修复

**日期**: 2026-06-19  
**版本**: generate_factor_summary_report.py v2.21→v2.22, stock_selector.py v1.14→v1.15  
**涉及文件**: 3 文件（+ 测试 2 文件 + 流程文档 1 文件 = 6 文件）

---

## 问题清单

| # | 问题 | 严重度 | 位置 |
|---|------|--------|------|
| 1 | Section 5 volume_ratio 缩写不一致（vol vs vr） | 轻微 | format_weights L1030-1062 |
| 2 | Section 5 momentum_strength 权重显示 0% | 轻微 | format_weights L1060 |
| 3 | Section 3 相关性矩阵列头截断（tail_pri ×3） | 轻微 | generate_correlation_section L1174 |
| 4 | Section 4 剔除因子列表超长截断 | 轻微 | get_factor_selection_info L1381 |
| 5 | Section 8 缺少覆盖率过滤信息 | 轻微 | stock_selector + _generate_stock_selection_section |

---

## 修复方案

### Fix1: format_weights 缩写统一

**根因**: `factor_abbr` 字典键是因子名（`volume_ratio`），但 IC/ICIR/等权 的 weights 字典键是列名（`volume_ratio_5`）。列名未命中字典 → 回退 `factor[:3]` → `vol`；因子名命中 → `vr`。

**方案**: 将 `FACTOR_ABBR` 提取为模块级常量 + `_get_factor_abbr(name)` 辅助函数。`format_weights` 先用 `COL_TO_FACTOR_NAME_MAP` 归一化键再查缩写。

```python
# 模块级常量
FACTOR_ABBR = {
    "volume_ratio": "vr",
    "tail_price_position": "tp_pos",
    ...
}

def _get_factor_abbr(factor_name: str) -> str:
    """获取因子缩写，未命中时取前3字符"""
    return FACTOR_ABBR.get(factor_name, factor_name[:3])

def format_weights(weights: dict) -> str:
    parts = []
    for factor, weight in weights.items():
        factor_name = COL_TO_FACTOR_NAME_MAP.get(factor, factor)  # 列名→因子名
        abbr = _get_factor_abbr(factor_name)
        ...
```

**影响**: Section 5 所有4种权重方法统一显示 `vr`。Section 3 也复用此函数（Fix3）。

### Fix2: 权重 <0.5% 显示1位小数

**根因**: `:.0f` 将 0.44% 截断为 0%。

**方案**: 条件格式化
```python
pct = weight * 100
if pct < 0.5:
    parts.append(f"{abbr}:{pct:.1f}%")
else:
    parts.append(f"{abbr}:{pct:.0f}%")
```

### Fix3: 相关性矩阵列头用缩写

**根因**: `name[:8]` 截断为8字符，`tail_price_position` / `tail_price_volume_intensity` / `tail_price_position_delta` 都截断为 `tail_pri`。

**方案**: 列头用 `_get_factor_abbr(name)` 替代 `name[:8]`。行名保持完整（已有 `<12` 对齐）。

```python
# L1174: 修改前
header += f"{name[:8]:>10}"
# 修改后
abbr = _get_factor_abbr(name)
header += f"{abbr:>10}"
```

### Fix4: 剔除因子列表拆多行

**根因**: L1381 将所有剔除因子拼为一行，25个因子导致超长截断。

**方案**: 每行一个因子，带缩进
```python
# 修改前
lines.append(f"  - 剔除因子: {', '.join(excluded_info)}")
# 修改后
lines.append("  - 剔除因子:")
for info in excluded_info:
    lines.append(f"    · {info}")
```

### Fix5: 覆盖率过滤信息

**根因**: `sort_and_select` L420 计算 `excluded_by_coverage` 但仅用于日志，未返回。`build_result` 不接收此值，meta 不包含。

**方案** (3处改动):

1. **sort_and_select** (stock_selector.py):
   - 返回值从 `tuple[list, int]` 改为 `tuple[list, int, int]`（增加 `excluded_by_coverage`）
   - L544: `return result_list, excluded_by_amplitude, excluded_by_coverage`

2. **build_result** (stock_selector.py):
   - 新增参数 `excluded_by_coverage: int = 0` 和 `min_weight_coverage: float = 0.5`
   - meta 新增 `"excluded_by_coverage": excluded_by_coverage, "min_weight_coverage": min_weight_coverage`

3. **调用点** (stock_selector.py L876):
   - `top_stocks, excluded_by_amplitude, excluded_by_coverage = sort_and_select(...)`
   - 传入 `excluded_by_coverage` 和 `config.min_weight_coverage`（需确认 config 字段名）

4. **报告脚本** (_generate_stock_selection_section L1881-1887):
   - 读取 `meta.get("excluded_by_coverage", 0)` 和 `meta.get("min_weight_coverage", 0)`
   - 在振幅过滤行后追加覆盖率过滤行

---

## 测试计划

| Fix | 测试 | 文件 |
|-----|------|------|
| 1 | test_format_weights: 列名键→正确缩写 | test_generate_factor_summary_report.py |
| 2 | test_format_weights: 权重<0.5%→1位小数 | 同上 |
| 3 | test_generate_correlation_section: 列头用缩写 | 同上 |
| 4 | test_get_factor_selection_info: 剔除因子多行 | 同上 |
| 5 | test_sort_and_select: 返回3元组 | test_stock_selector.py |
| 5 | test_build_result: meta含coverage字段 | 同上 |
| 5 | test_stock_selection_section: 显示覆盖率过滤 | test_generate_factor_summary_report.py |

---

## 风险评估

- Fix1-4 仅影响显示，不改数据流，风险极低
- Fix5 改变 `sort_and_select` 返回值签名，需检查所有调用点（仅1处 L876）
- 版本号: report v2.21→v2.22, stock_selector v1.14→v1.15
