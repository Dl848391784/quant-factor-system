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
from summary.generate_factor_summary_report import _format_neutral_cell, _generate_ic_section, _select_neutral_payload


# ---------------------------------------------------------------------------
# P3.3: neutral payload selector
# ---------------------------------------------------------------------------


class TestSelectNeutralPayload:
    def test_new_field_enabled_with_controls(self):
        new_payload = {"enabled": True, "controls_used": ["industry", "log_market_cap"], "decay_rate": 0.2}
        payload, method = _select_neutral_payload({"ic_neutralized": new_payload})
        assert payload is new_payload
        assert method == "industry+log_market_cap"

    def test_disabled_neutralized_marked_skipped(self):
        disabled = {
            "enabled": False,
            "skipped_reason": "factor_in_excluded_list",
            "controls_used": [],
            "excluded_specs": ["industry"],
        }
        payload, method = _select_neutral_payload({"ic_neutralized": disabled})
        assert payload is disabled
        assert method == "skipped"

    def test_missing_neutral_payload(self):
        payload, method = _select_neutral_payload({})
        assert payload == {}
        assert method == "-"


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

    @pytest.mark.parametrize(
        ("level", "rate", "expected"),
        [
            ("low", 0.10, "10%"),
            ("inverse", -0.20, "-20%"),
            ("undefined", 0.05, "5%"),
            ("low", 0.299, "30%"),  # 边界 (<30% rounds to 30%) — 该 cell 不带 ⚠ 因为 level=low
        ],
    )
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


# ---------------------------------------------------------------------------
# R19b: _generate_ic_section 表头 + 数据行单测
# ---------------------------------------------------------------------------


class TestGenerateIcSectionNeutralColumn:
    """覆盖 _generate_ic_section 中性化列的渲染逻辑（R18b 改造）。"""

    def _make_ic_results(self) -> list[dict]:
        """构造 3 个因子，覆盖 high/low/disabled 三种渲染情形。"""
        return [
            {
                "factor_name": "amplitude",
                "ic_mean": 0.05,
                "icir": 0.30,
                "ic_std": 0.16,
                "valid_days": 100,
                "neutral_enabled": True,
                "neutral_decay_rate": 0.62,
                "neutral_decay_level": "high",
                "neutral_method": "industry+log_market_cap",
            },
            {
                "factor_name": "rsi",
                "ic_mean": -0.03,
                "icir": -0.15,
                "ic_std": 0.20,
                "valid_days": 100,
                "neutral_enabled": True,
                "neutral_decay_rate": 0.10,
                "neutral_decay_level": "low",
            },
            {
                "factor_name": "industry_momentum_5d",
                "ic_mean": 0.04,
                "icir": 0.20,
                "ic_std": 0.20,
                "valid_days": 100,
                "neutral_enabled": False,
                "neutral_decay_rate": None,
                "neutral_decay_level": "undefined",
            },
        ]

    def test_header_contains_neutral_column(self):
        """IC 表表头必须含'中性化敏感'列名（design.md §6）。"""
        lines = _generate_ic_section(self._make_ic_results(), backtest_results=[])
        # 找到表头行（含'因子'+'IC均值'+'ICIR'）
        header_lines = [line for line in lines if "因子" in line and "ICIR" in line and "IC均值" in line]
        assert len(header_lines) >= 1, f"未找到表头行，前 5 行: {lines[:5]}"
        assert "中性化敏感" in header_lines[0], f"表头缺'中性化敏感'列: {header_lines[0]!r}"

    def test_high_factor_row_has_warning_symbol(self):
        """高敏感因子（amplitude, decay=62%）行末尾应含 '⚠'。"""
        lines = _generate_ic_section(self._make_ic_results(), backtest_results=[])
        amp_lines = [line for line in lines if line.startswith("amplitude")]
        assert len(amp_lines) == 1, f"未找到 amplitude 行: {amp_lines}"
        assert "⚠" in amp_lines[0], f"high 因子缺 ⚠ 高亮: {amp_lines[0]!r}"
        assert "62%" in amp_lines[0]

    def test_low_factor_row_no_warning_symbol(self):
        """低敏感因子（rsi, decay=10%）行不带 ⚠。"""
        lines = _generate_ic_section(self._make_ic_results(), backtest_results=[])
        rsi_lines = [line for line in lines if line.startswith("rsi")]
        assert len(rsi_lines) == 1
        assert "⚠" not in rsi_lines[0]
        assert "10%" in rsi_lines[0]

    def test_disabled_factor_row_shows_dash(self):
        """未启用的因子（industry_momentum_5d, enabled=False）行末尾显示 '-'。"""
        lines = _generate_ic_section(self._make_ic_results(), backtest_results=[])
        ind_lines = [line for line in lines if line.startswith("industry_momentum_5d")]
        assert len(ind_lines) == 1
        assert ind_lines[0].rstrip().endswith("-"), f"disabled 因子末尾应为 '-': {ind_lines[0]!r}"
        assert "⚠" not in ind_lines[0]
