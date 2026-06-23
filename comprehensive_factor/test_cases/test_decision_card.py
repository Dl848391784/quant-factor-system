"""
decision_card 模块测试 (v1.0).

遵循 AGENTS.md 规则 #8: 新建脚本同步创建 pytest.
设计依据: designs/feat_decision_card_v1.md §6
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest


sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from comprehensive_factor.decision_card import (  # noqa: E402
    AMPLITUDE_BUCKETS,
    CHECKLIST_D5,
    RETURN_5D_BUCKETS,
    _bucket,
    _close_position_in_range,
    _compute_d1,
    _compute_d2,
    _compute_d3,
    _compute_d4,
    _safe_float,
    build_decision_cards,
)


# ============================================================================
# 辅助函数测试
# ============================================================================


class TestBucket:
    """_bucket 边界值测试."""

    def test_return_5d_deep_decline(self):
        assert _bucket(-0.20, RETURN_5D_BUCKETS) == "深跌(<-15%)"

    def test_return_5d_boundary_negative_15(self):
        # -0.15 不 < -0.15, 应进入下一档
        assert _bucket(-0.15, RETURN_5D_BUCKETS) == "中跌(-15~-5%)"

    def test_return_5d_temperate(self):
        assert _bucket(-0.03, RETURN_5D_BUCKETS) == "温和(-5~0%)"

    def test_return_5d_uprising(self):
        assert _bucket(0.05, RETURN_5D_BUCKETS) == "上涨(>3%)"

    def test_amplitude_extreme_low(self):
        assert _bucket(0.005, AMPLITUDE_BUCKETS) == "极低(<2%)"

    def test_amplitude_high(self):
        assert _bucket(0.15, AMPLITUDE_BUCKETS) == "高(>8%)"

    def test_nan_returns_na(self):
        assert _bucket(float("nan"), RETURN_5D_BUCKETS) == "n/a"
        assert _bucket(None, RETURN_5D_BUCKETS) == "n/a"


class TestSafeFloat:
    def test_valid(self):
        assert _safe_float(1.5) == 1.5
        assert _safe_float("2.0") == 2.0

    def test_none(self):
        assert _safe_float(None) is None

    def test_nan(self):
        assert _safe_float(float("nan")) is None

    def test_invalid_string(self):
        assert _safe_float("abc") is None


class TestClosePosition:
    def test_bottom(self):
        assert _close_position_in_range(10.0, 20.0, 10.0) == "底部"

    def test_top(self):
        assert _close_position_in_range(19.5, 20.0, 10.0) == "顶部"

    def test_middle(self):
        assert _close_position_in_range(15.0, 20.0, 10.0) == "中部"

    def test_zero_span(self):
        assert _close_position_in_range(10.0, 10.0, 10.0) == "n/a"

    def test_missing_data(self):
        assert _close_position_in_range(None, 20.0, 10.0) == "n/a"


# ============================================================================
# D1~D4 计算测试
# ============================================================================


class TestComputeD1:
    def test_basic(self):
        row = pd.Series(
            {
                "return_5d": -0.08,
                "amplitude": 0.05,
                "close": 12.0,
                "high": 15.0,
                "low": 10.0,
            }
        )
        d1 = _compute_d1(row)
        assert d1.return_5d_bucket == "中跌(-15~-5%)"
        assert d1.amplitude_bucket == "中(4~8%)"
        assert d1.close_position_5d == "中部"

    def test_missing_fields(self):
        row = pd.Series({"return_5d": None})
        d1 = _compute_d1(row)
        assert d1.return_5d_bucket == "n/a"
        assert d1.amplitude_bucket == "n/a"
        assert d1.close_position_5d == "n/a"


class TestComputeD2:
    """D2 风险标记 warning_count 计数."""

    def test_no_warnings(self):
        row = pd.Series({"return_5d": -0.02, "amount": 1e8, "amplitude": 0.05})
        d2 = _compute_d2(row, low_liquidity_amount=1e7)
        assert d2.warning_count == 0
        assert not d2.deep_decline_5d
        assert not d2.low_liquidity
        assert not d2.extreme_amplitude

    def test_all_three_warnings(self):
        row = pd.Series({"return_5d": -0.20, "amount": 1e6, "amplitude": 0.15})
        d2 = _compute_d2(row, low_liquidity_amount=1e7)
        assert d2.warning_count == 3
        assert d2.deep_decline_5d
        assert d2.low_liquidity
        assert d2.extreme_amplitude

    def test_extreme_amplitude_too_low(self):
        """一字板涨停 (amplitude < 1%) 也算 extreme."""
        row = pd.Series({"return_5d": 0.0, "amount": 1e8, "amplitude": 0.005})
        d2 = _compute_d2(row, low_liquidity_amount=1e7)
        assert d2.extreme_amplitude

    def test_no_low_liq_threshold(self):
        """factor_df 缺 amount 时不判定 low_liquidity."""
        row = pd.Series({"return_5d": -0.02, "amplitude": 0.05})
        d2 = _compute_d2(row, low_liquidity_amount=None)
        assert not d2.low_liquidity


class TestComputeD3:
    def test_all_signals_hit(self):
        row = pd.Series(
            {
                "volume_shrink_rate": 0.8,
                "price_volume_divergence": 0.1,
                "lower_shadow_ratio": 0.5,
            }
        )
        d3 = _compute_d3(row)
        assert d3.hit_count == 3
        assert d3.raw_signals_available

    def test_all_nan_signals(self):
        row = pd.Series(
            {
                "volume_shrink_rate": np.nan,
                "price_volume_divergence": np.nan,
                "lower_shadow_ratio": np.nan,
            }
        )
        d3 = _compute_d3(row)
        assert d3.hit_count == 0
        assert not d3.raw_signals_available
        assert d3.volume_shrink is None
        assert d3.pv_divergence is None
        assert d3.lower_shadow is None

    def test_partial_nan(self):
        row = pd.Series(
            {
                "volume_shrink_rate": 0.8,
                "price_volume_divergence": np.nan,
                "lower_shadow_ratio": 0.5,
            }
        )
        d3 = _compute_d3(row)
        assert d3.hit_count == 2
        assert d3.volume_shrink is True
        assert d3.pv_divergence is None
        assert d3.lower_shadow is True
        assert d3.raw_signals_available


class TestComputeD4:
    def test_returns_null_with_note(self):
        d4 = _compute_d4()
        assert d4.times_in_top30_last_60d is None
        assert d4.avg_1d_return_when_in_top30 is None
        assert "历史归档" in d4.note


# ============================================================================
# build_decision_cards 集成测试
# ============================================================================


class TestBuildDecisionCards:
    @pytest.fixture
    def mock_factor_df(self) -> pd.DataFrame:
        return pd.DataFrame(
            {
                "asset": ["600377", "001210", "missing_in_top"],
                "return_5d": [-0.08, -0.20, 0.05],
                "amplitude": [0.05, 0.15, 0.03],
                "amount": [5e8, 1e6, 1e9],
                "close": [12.0, 5.0, 20.0],
                "high": [15.0, 10.0, 22.0],
                "low": [10.0, 4.0, 18.0],
                "volume_shrink_rate": [0.8, 1.2, 0.5],
                "price_volume_divergence": [0.1, -0.1, 0.2],
                "lower_shadow_ratio": [0.5, 0.1, 0.4],
            }
        )

    @pytest.fixture
    def mock_top_stocks(self) -> list[dict]:
        return [
            {"rank": 1, "code": "600377", "composite_value": -0.74},
            {"rank": 2, "code": "001210", "composite_value": -0.73},
        ]

    def test_card_attached_to_each_stock(self, mock_top_stocks, mock_factor_df):
        enriched = build_decision_cards(mock_top_stocks, mock_factor_df)
        assert len(enriched) == 2
        for item in enriched:
            assert "decision_card" in item
            card = item["decision_card"]
            assert card is not None
            assert "d1_classification" in card
            assert "d2_risk" in card
            assert "d3_stabilization" in card
            assert "d4_history" in card

    def test_code_not_in_factor_df_returns_null_card(self, mock_factor_df):
        stocks = [{"rank": 1, "code": "unknown_code"}]
        enriched = build_decision_cards(stocks, mock_factor_df)
        assert enriched[0]["decision_card"] is None

    def test_empty_top_stocks(self, mock_factor_df):
        assert build_decision_cards([], mock_factor_df) == []

    def test_missing_asset_column(self, mock_top_stocks):
        bad_df = pd.DataFrame({"code": ["600377"], "return_5d": [-0.08]})
        result = build_decision_cards(mock_top_stocks, bad_df)
        # 缺 asset 列时, 原 list 浅拷贝返回, decision_card 字段不存在
        assert len(result) == 2
        for item in result:
            assert "decision_card" not in item

    def test_low_liquidity_uses_5pct_quantile(self, mock_top_stocks, mock_factor_df):
        """股票 001210 的 amount=1e6 是当日最低, 应触发 low_liquidity."""
        enriched = build_decision_cards(mock_top_stocks, mock_factor_df)
        card_001210 = enriched[1]["decision_card"]
        assert card_001210["d2_risk"]["low_liquidity"] is True
        card_600377 = enriched[0]["decision_card"]
        # 600377 amount=5e8 不在底部 5%
        assert card_600377["d2_risk"]["low_liquidity"] is False

    def test_original_top_stocks_not_mutated(self, mock_top_stocks, mock_factor_df):
        """build_decision_cards 不应修改原 list."""
        build_decision_cards(mock_top_stocks, mock_factor_df)
        for item in mock_top_stocks:
            assert "decision_card" not in item


class TestChecklistD5:
    def test_checklist_is_static(self):
        """D5 是固定模板, 不动态调整."""
        assert len(CHECKLIST_D5) == 4
        assert all(isinstance(item, str) for item in CHECKLIST_D5)
        assert any("公告" in item for item in CHECKLIST_D5)
        assert any("新闻" in item for item in CHECKLIST_D5)
        assert any("财报" in item for item in CHECKLIST_D5)
        assert any("股东" in item for item in CHECKLIST_D5)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
