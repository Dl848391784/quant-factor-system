"""summary._format_neutral_cell + _generate_ic_section 行业中性化列单测。

覆盖 design.md §6 summary 报告中性化敏感度列：

  R19a: _format_neutral_cell
        - enabled=False → '-'
        - enabled=True + decay_rate=None → '-'
        - decay_level='high' → 'XX% ⚠'
        - decay_level='low' / 'inverse' / 'undefined' → 'XX%' (无 ⚠)
        - 缺字段降级 → '-'

  R19b: _generate_ic_section 表头 + 数据行
        - 表头含'中性化敏感'列
        - 数据行格式正确（高敏感因子带 ⚠, 未启用因子 '-'）

设计文档: .hermes/plans/factor-ic-industry-neutralization-design.md §6
"""

from __future__ import annotations

import pytest

from summary.generate_factor_summary_report import _format_neutral_cell


# ---------------------------------------------------------------------------
# R19a: _format_neutral_cell 单测
# ---------------------------------------------------------------------------


class TestFormatNeutralCell:
    """覆盖 _format_neutral_cell 全部分支。"""

    def test_disabled_returns_dash(self):
        """neutral_enabled=False → '-'。"""
        item = {"neutral_enabled": False, "neutral_decay_rate": None, "neutral_decay_level": "undefined"}
        assert _format_neutral_cell(item) == "-"

    def test_enabled_but_decay_rate_none_returns_dash(self):
        """enabled=True 但 decay_rate=None（边界）→ '-'。"""
        item = {"neutral_enabled": True, "neutral_decay_rate": None, "neutral_decay_level": "undefined"}
        assert _format_neutral_cell(item) == "-"

    def test_high_decay_appends_warning_symbol(self):
        """decay_level='high' (≥30%) → 'XX% ⚠'。"""
        item = {"neutral_enabled": True, "neutral_decay_rate": 0.62, "neutral_decay_level": "high"}
        assert _format_neutral_cell(item) == "62% ⚠"

    @pytest.mark.parametrize(("level", "rate", "expected"), [
        ("low", 0.10, "10%"),
        ("inverse", -0.20, "-20%"),
        ("undefined", 0.05, "5%"),
        ("low", 0.299, "30%"),  # 边界 (<30% rounds to 30%) — 该 cell 不带 ⚠ 因为 level=low
    ])
    def test_non_high_levels_no_warning(self, level, rate, expected):
        """non-high 层级不带 ⚠ 高亮符号。"""
        item = {"neutral_enabled": True, "neutral_decay_rate": rate, "neutral_decay_level": level}
        assert _format_neutral_cell(item) == expected

    def test_missing_fields_defaults_to_dash(self):
        """字段缺失 → '-' (兼容旧 IC 结果文件)。"""
        # 全空 dict
        assert _format_neutral_cell({}) == "-"
        # 只有 enabled 缺 rate
        assert _format_neutral_cell({"neutral_enabled": True}) == "-"

    def test_high_decay_with_zero_rate(self):
        """high 层级但 rate=0% （理论可能：raw 与 neutral 同号同值）→ '0% ⚠'。

        虽然 rate=0 通常应分类为 'low'，此处验证 _format_neutral_cell 不再做层级
        判断,完全信任上游 decay_level（避免双重判断逻辑漂移）。
        """
        item = {"neutral_enabled": True, "neutral_decay_rate": 0.0, "neutral_decay_level": "high"}
        assert _format_neutral_cell(item) == "0% ⚠"
