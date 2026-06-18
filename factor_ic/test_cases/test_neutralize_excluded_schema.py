"""NEUTRALIZE_EXCLUDED 二维结构与 is_excluded 解析器测试（P1.5）。

测试目标:
    - dict 主结构含 'industry' key + 8 个原行业聚合因子
    - 别名 INDUSTRY_NEUTRALIZE_EXCLUDED 与 NEUTRALIZE_EXCLUDED["industry"] 同对象
    - is_excluded 对未知 control_name 返回 False（不抛错，未来扩展安全）
    - 决策函数 _resolve_neutralize_decision 路径不变（用 is_excluded 走新 dict）

参考: designs/feat_neutralization_framework.md §4.1, §14.1（P1.5）
"""

from __future__ import annotations

from factor_ic.common.factor_ic_runner import (
    INDUSTRY_NEUTRALIZE_EXCLUDED,
    NEUTRALIZE_EXCLUDED,
    NEUTRALIZE_SKIP_REASON_EXCLUDED,
    _resolve_neutralize_decision,
    is_excluded,
)


# ============================================================
# 数据结构契约
# ============================================================


class TestNeutralizeExcludedSchema:
    def test_dict_has_industry_key(self):
        assert "industry" in NEUTRALIZE_EXCLUDED
        assert isinstance(NEUTRALIZE_EXCLUDED["industry"], frozenset)

    def test_industry_set_contents(self):
        """8 个原行业聚合因子全部进入 NEUTRALIZE_EXCLUDED['industry']。"""
        expected = {
            "industry_momentum_5d",
            "industry_turnover_trend",
            "industry_amplitude_trend",
            "industry_roe_trend",
            "industry_earnings_growth",
            "industry_pe_trend",
            "capital_flow_intensity",
            "capital_flow_ratio_trend",
        }
        assert set(NEUTRALIZE_EXCLUDED["industry"]) == expected

    def test_legacy_alias_points_to_same_set(self):
        """旧名 INDUSTRY_NEUTRALIZE_EXCLUDED 必须与 NEUTRALIZE_EXCLUDED['industry'] 等价。"""
        assert NEUTRALIZE_EXCLUDED["industry"] == INDUSTRY_NEUTRALIZE_EXCLUDED


# ============================================================
# is_excluded 解析器
# ============================================================


class TestIsExcluded:
    def test_industry_aggregated_factor_excluded(self):
        assert is_excluded("industry_momentum_5d", "industry") is True
        assert is_excluded("capital_flow_intensity", "industry") is True

    def test_normal_factor_not_excluded(self):
        assert is_excluded("rsi", "industry") is False
        assert is_excluded("volume_ratio", "industry") is False

    def test_unregistered_control_returns_false(self):
        """未注册 control_name 不抛错，返回 False（design.md §4.1 演进路径）。"""
        assert is_excluded("rsi", "log_market_cap") is False
        assert is_excluded("industry_momentum_5d", "future_beta_neutralize") is False


# ============================================================
# 决策函数路径不变
# ============================================================


class TestResolveNeutralizeDecisionAfterUpgrade:
    def test_excluded_factor_returns_skip(self):
        """P1.5 升级后, 8 个 excluded 因子仍全部走 skipped_reason 路径。"""
        for factor in NEUTRALIZE_EXCLUDED["industry"]:
            enabled, reason = _resolve_neutralize_decision(factor, neutralize=True, mode="full")
            assert enabled is False, f"{factor} 应被排除"
            assert reason == NEUTRALIZE_SKIP_REASON_EXCLUDED

    def test_normal_factor_full_mode_enabled(self):
        enabled, reason = _resolve_neutralize_decision("rsi", neutralize=True, mode="full")
        assert enabled is True and reason is None

    def test_user_disabled_overrides_full_mode(self):
        enabled, reason = _resolve_neutralize_decision("rsi", neutralize=False, mode="full")
        assert enabled is False
        # 应是 user disabled 而非 excluded
        assert reason != NEUTRALIZE_SKIP_REASON_EXCLUDED
