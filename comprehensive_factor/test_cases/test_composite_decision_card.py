"""
decision_card 模块测试 (v3.9: Bottom30 过热过滤).

遵循 PROJECT.md §S2 配套文件同步创建: 新建脚本同步创建 pytest.
设计依据: designs/feat_decision_card_v1.md §6, designs/feat_bottom30_overheat_filter.md
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest


sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from comprehensive_factor.composite_decision_card import (  # noqa: E402
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
    """_bucket 边界值测试 (v3.9: 涨幅分桶)."""

    def test_return_5d_flat(self):
        assert _bucket(-0.01, RETURN_5D_BUCKETS) == "横盘(<0%)"

    def test_return_5d_boundary_zero(self):
        # 0.00 不 < 0.00, 应进入下一档
        assert _bucket(0.00, RETURN_5D_BUCKETS) == "微涨(0~3%)"

    def test_return_5d_slight_rise(self):
        assert _bucket(0.02, RETURN_5D_BUCKETS) == "微涨(0~3%)"

    def test_return_5d_big_rise(self):
        assert _bucket(0.20, RETURN_5D_BUCKETS) == "暴涨(>15%)"

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
                "return_5d": 0.05,
                "amplitude": 0.05,
                "close": 12.0,
                "high": 15.0,
                "low": 10.0,
            }
        )
        d1 = _compute_d1(row)
        assert d1.return_5d_bucket == "中涨(3~8%)"
        assert d1.amplitude_bucket == "中(4~8%)"
        assert d1.close_position_5d == "中部"

    def test_missing_fields(self):
        row = pd.Series({"return_5d": None})
        d1 = _compute_d1(row)
        assert d1.return_5d_bucket == "n/a"
        assert d1.amplitude_bucket == "n/a"
        assert d1.close_position_5d == "n/a"


class TestComputeD2:
    """D2 过热风险标记 (v3.9) warning_count 计数."""

    def test_no_warnings(self):
        row = pd.Series({"turnover_rate": 0.01, "volume_ratio_5": 1.0, "amplitude": 0.05})
        d2 = _compute_d2(row, turnover_threshold=0.05)
        assert d2.warning_count == 0
        assert not d2.high_turnover
        assert not d2.high_volume_ratio
        assert not d2.extreme_amplitude

    def test_all_three_warnings(self):
        row = pd.Series({"turnover_rate": 0.10, "volume_ratio_5": 2.0, "amplitude": 0.15})
        d2 = _compute_d2(row, turnover_threshold=0.05)
        assert d2.warning_count == 3
        assert d2.high_turnover
        assert d2.high_volume_ratio
        assert d2.extreme_amplitude

    def test_extreme_amplitude_too_low(self):
        """一字板涨停 (amplitude < 1%) 也算 extreme."""
        row = pd.Series({"turnover_rate": 0.01, "volume_ratio_5": 1.0, "amplitude": 0.005})
        d2 = _compute_d2(row, turnover_threshold=0.05)
        assert d2.extreme_amplitude

    def test_no_turnover_threshold(self):
        """turnover_threshold=None 时不判定 high_turnover."""
        row = pd.Series({"turnover_rate": 0.01, "volume_ratio_5": 1.0, "amplitude": 0.05})
        d2 = _compute_d2(row, turnover_threshold=None)
        assert not d2.high_turnover


class TestComputeD3:
    """D3 趋势确认信号 (v3.9)."""

    def test_all_signals_hit(self):
        row = pd.Series(
            {
                "near_high_ratio_5": 0.98,
                "bollinger_pb": 1.2,
                "rsi_6": 75,
            }
        )
        d3 = _compute_d3(row)
        assert d3.hit_count == 3
        assert d3.raw_signals_available

    def test_all_nan_signals(self):
        row = pd.Series(
            {
                "near_high_ratio_5": np.nan,
                "bollinger_pb": np.nan,
                "rsi_6": np.nan,
            }
        )
        d3 = _compute_d3(row)
        assert d3.hit_count == 0
        assert not d3.raw_signals_available
        assert d3.near_high is None
        assert d3.bollinger_upper is None
        assert d3.rsi_overbought is None

    def test_partial_nan(self):
        row = pd.Series(
            {
                "near_high_ratio_5": 0.98,
                "bollinger_pb": np.nan,
                "rsi_6": 75,
            }
        )
        d3 = _compute_d3(row)
        assert d3.hit_count == 2
        assert d3.near_high is True
        assert d3.bollinger_upper is None
        assert d3.rsi_overbought is True
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
                "return_5d": [0.05, 0.20, -0.02],
                "amplitude": [0.05, 0.15, 0.03],
                "turnover_rate": [0.01, 0.10, 0.03],
                "volume_ratio_5": [1.0, 2.0, 1.2],
                "close": [12.0, 5.0, 20.0],
                "high": [15.0, 10.0, 22.0],
                "low": [10.0, 4.0, 18.0],
                "near_high_ratio_5": [0.85, 0.98, 0.90],
                "bollinger_pb": [0.8, 1.2, 1.0],
                "rsi_6": [55, 75, 65],
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
            assert "d3_trend" in card
            assert "d4_history" in card

    def test_code_not_in_factor_df_returns_null_card(self, mock_factor_df):
        stocks = [{"rank": 1, "code": "unknown_code"}]
        enriched = build_decision_cards(stocks, mock_factor_df)
        assert enriched[0]["decision_card"] is None

    def test_empty_top_stocks(self, mock_factor_df):
        assert build_decision_cards([], mock_factor_df) == []

    def test_missing_asset_column(self, mock_top_stocks):
        bad_df = pd.DataFrame({"code": ["600377"], "return_5d": [0.05]})
        result = build_decision_cards(mock_top_stocks, bad_df)
        # 缺 asset 列时, 原 list 浅拷贝返回, decision_card 字段不存在
        assert len(result) == 2
        for item in result:
            assert "decision_card" not in item

    def test_high_turnover_uses_70pct_quantile(self, mock_top_stocks, mock_factor_df):
        """股票 001210 的 turnover_rate=0.10 是当日最高, 应触发 high_turnover."""
        enriched = build_decision_cards(mock_top_stocks, mock_factor_df)
        card_001210 = enriched[1]["decision_card"]
        assert card_001210["d2_risk"]["high_turnover"] is True
        card_600377 = enriched[0]["decision_card"]
        # 600377 turnover_rate=0.01 不在 70% 分位以上
        assert card_600377["d2_risk"]["high_turnover"] is False

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
