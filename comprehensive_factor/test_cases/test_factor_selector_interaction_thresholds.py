"""v2.39: 交互因子族独立门槛体系测试

验证 INTERACTION_THRESHOLDS 与 DEFAULT_THRESHOLDS 的派发逻辑及独立门槛是否生效。
遵循 design.md feat_interaction_thresholds_v239.md。

测试覆盖:
1. 派发函数 _get_thresholds_for_factor: 因子名前缀 → 派发结果
2. 线性因子主 dict 零修改保证（核心承诺）
3. 交互因子走独立门槛: ic_mean/icir/mono/long_return/L1 全部使用 INTERACTION_THRESHOLDS
4. p_value 在交互因子下仍然检查（v2.39 Post-Mortem 修正后）
5. L1 阈值放宽: 交互因子 L1 = −20% 可以通过（DEFAULT 下应被淘汰）
6. exempt_details 含 threshold_source 字段（审计可见性）
7. confirmation 角色 ic_threshold override（INTERACTION 覆盖 confirmation）
8. 三因子实测真值场景: amp_compression 通过, amplitude/turnover 淘汰
"""

import pytest
from comprehensive_factor.common.factor_selector import (
    DEFAULT_THRESHOLDS,
    INTERACTION_THRESHOLDS,
    _get_thresholds_for_factor,
    validate_factor,
)


def _make_factor_data(
    ic_mean: float | None,
    icir: float | None,
    sharpe: float | None,
    mono_corr: float | None,
    valid_days: int = 200,
    p_value: float | None = 0.01,
    long_return: float = 0.10,
    layer_1_annual: float | None = 0.05,
    layer_1_sharpe: float | None = 0.5,
) -> dict:
    """构造测试用因子数据（含 layer_1 字段）"""
    return {
        "ic_metrics": {"ic_mean": ic_mean, "icir": icir, "p_value": p_value},
        "sample_stats": {"valid_days": valid_days},
        "backtest": {
            "long_short": {
                "long_short_sharpe": sharpe,
                "long_return_annual": long_return,
            },
            "monotonicity": {"correlation": mono_corr},
            "layer_stats": {
                "layer_1": {
                    "annual_return": layer_1_annual,
                    "sharpe_ratio": layer_1_sharpe,
                }
            },
        },
    }


class TestThresholdDispatch:
    """派发函数 _get_thresholds_for_factor 测试"""

    def test_linear_factor_uses_default(self):
        """线性因子（不以 interaction_ 开头）使用 DEFAULT_THRESHOLDS"""
        for fn in ["rsi", "bollinger_pb", "kdj_j", "ma5_dev"]:
            t, src = _get_thresholds_for_factor(fn, DEFAULT_THRESHOLDS)
            assert src == "default", f"{fn} 应走 default 门槛"
            assert t["ic_mean_abs_min"] == 0.03
            assert t["mono_corr_abs_min" if False else "monotonicity_corr_abs_min"] == 0.4
            assert t["layer_1_return_min"] == 0.0

    def test_interaction_factor_uses_interaction(self):
        """interaction_ 前缀因子走 INTERACTION_THRESHOLDS"""
        for fn in [
            "interaction_amplitude",
            "interaction_turnover",
            "interaction_amp_compression",
            "interaction_kdj",
        ]:
            t, src = _get_thresholds_for_factor(fn, DEFAULT_THRESHOLDS)
            assert src == "interaction", f"{fn} 应走 interaction 门槛"
            assert t["ic_mean_abs_min"] == 0.005
            assert t["monotonicity_corr_abs_min"] == 0.30
            assert t["layer_1_return_min"] == -0.28  # v2.40: 见 designs/feat_interaction_thresholds_v240.md

    def test_default_thresholds_unchanged_by_dispatch(self):
        """关键: 派发不能修改主 dict（线性因子主 dict 零修改承诺）"""
        original = dict(DEFAULT_THRESHOLDS)
        _, _ = _get_thresholds_for_factor("interaction_x", DEFAULT_THRESHOLDS)
        assert original == DEFAULT_THRESHOLDS, "派发后 DEFAULT_THRESHOLDS 被污染"

    def test_interaction_merges_not_replaces(self):
        """INTERACTION_THRESHOLDS merge 而非完全替换（防止漏字段 KeyError）"""
        t, _ = _get_thresholds_for_factor("interaction_x", DEFAULT_THRESHOLDS)
        # 主 dict 有但 INTERACTION 没显式定义的字段也得在
        for k in DEFAULT_THRESHOLDS:
            assert k in t, f"merge 后丢失字段: {k}"


class TestInteractionThresholdsBehavior:
    """交互因子门槛行为测试"""

    def test_interaction_ic_mean_005_passes(self):
        """交互因子 ic_mean=0.006 > 0.005 应过（DEFAULT 下 0.006 < 0.03 会卡）"""
        data = _make_factor_data(
            ic_mean=0.006,
            icir=0.10,
            sharpe=2.0,
            mono_corr=0.35,
            p_value=0.02,
            long_return=0.10,
            layer_1_annual=-0.10,
        )
        is_valid, reasons, _ = validate_factor("interaction_test", data)
        assert is_valid, f"交互因子 ic_mean=0.006 应过, 实际淘汰: {reasons}"

    def test_linear_ic_mean_005_rejected(self):
        """线性因子同样 ic_mean=0.006 应被淘汰（主 dict 0.03 卡, 且不触发 reverse 豁免）"""
        # sharpe=1.0 < 1.5, 不触发 reverse 豁免
        data = _make_factor_data(
            ic_mean=0.006,
            icir=0.30,
            sharpe=1.0,
            mono_corr=0.6,
            p_value=0.02,
            long_return=0.10,
            layer_1_annual=0.05,
        )
        is_valid, reasons, _ = validate_factor("linear_test", data)
        assert not is_valid, "线性因子 ic_mean=0.006 应淘汰"
        assert any("|ic_mean|" in r for r in reasons)

    def test_interaction_l1_negative_allowed(self):
        """交互因子 L1=−0.20 应过（DEFAULT 下 0.0 硬约束会淘汰）"""
        data = _make_factor_data(
            ic_mean=0.008,
            icir=0.08,
            sharpe=2.5,
            mono_corr=0.35,
            p_value=0.03,
            long_return=0.11,
            layer_1_annual=-0.20,
            layer_1_sharpe=-0.9,
        )
        is_valid, reasons, _ = validate_factor("interaction_amp", data)
        assert is_valid, f"交互因子 L1=−0.20 应过, 实际: {reasons}"

    def test_interaction_l1_below_threshold_rejected(self):
        """交互因子 L1=−0.30 < −0.28 (v2.40) 仍应被淘汰（门槛是过滤器）"""
        data = _make_factor_data(
            ic_mean=0.008,
            icir=0.08,
            sharpe=2.5,
            mono_corr=0.35,
            p_value=0.03,
            long_return=0.11,
            layer_1_annual=-0.30,
            layer_1_sharpe=-1.0,
        )
        is_valid, reasons, _ = validate_factor("interaction_x", data)
        assert not is_valid
        assert any("layer_1_annual" in r for r in reasons)

    def test_interaction_p_value_still_checked(self):
        """v2.39 Post-Mortem 修正: 交互因子 p_value 仍然检查"""
        # p_value=0.6 远大于 0.05, 应被淘汰
        data = _make_factor_data(
            ic_mean=0.008,
            icir=0.08,
            sharpe=2.0,
            mono_corr=0.35,
            p_value=0.6,
            long_return=0.11,
            layer_1_annual=-0.10,
        )
        is_valid, reasons, _ = validate_factor("interaction_noise", data)
        assert not is_valid
        assert any("p_value" in r for r in reasons), f"reasons={reasons}"

    def test_interaction_mono_030_passes(self):
        """交互因子 mono=0.32 > 0.30 应过（DEFAULT 下 0.4 会卡）"""
        data = _make_factor_data(
            ic_mean=0.008,
            icir=0.08,
            sharpe=2.5,
            mono_corr=0.32,
            p_value=0.03,
            long_return=0.11,
            layer_1_annual=-0.10,
        )
        is_valid, reasons, _ = validate_factor("interaction_amp", data)
        assert is_valid, f"实际: {reasons}"


class TestThresholdSourceField:
    """exempt_details 含 threshold_source 字段（审计可见性）"""

    def test_threshold_source_interaction(self):
        """交互因子触发豁免时, threshold_source='interaction'"""
        # ic_mean 触发豁免: 交互因子 ic_mean=0.004 < 0.005 + reverse 豁免
        data = _make_factor_data(
            ic_mean=-0.004,
            icir=0.08,
            sharpe=2.0,
            mono_corr=-0.55,
            p_value=0.04,
            long_return=0.10,
            layer_1_annual=-0.10,
        )
        _, _, exempt_details = validate_factor("interaction_x", data)
        for e in exempt_details:
            assert e.get("threshold_source") == "interaction", f"exempt missing threshold_source=interaction: {e}"

    def test_threshold_source_default(self):
        """线性因子触发豁免时, threshold_source='default'"""
        data = _make_factor_data(
            ic_mean=-0.017,
            icir=0.33,
            sharpe=5.54,
            mono_corr=-0.53,
            valid_days=24,
        )
        _, _, exempt_details = validate_factor("rsi", data)
        assert len(exempt_details) >= 1
        for e in exempt_details:
            assert e.get("threshold_source") == "default", f"exempt missing threshold_source=default: {e}"


class TestRealWorldThreeFactors:
    """v2.36 三因子实测真值场景（design §7.2）"""

    def test_amp_compression_passes(self):
        """interaction_amp_compression: ic=0.0077 / icir=0.120 / mono=0.357 / p=0.012 → 进池"""
        data = _make_factor_data(
            ic_mean=0.007729,
            icir=0.1197,
            sharpe=2.59,
            mono_corr=0.357,
            p_value=0.0122,
            long_return=0.1015,
            layer_1_annual=-0.1176,
            layer_1_sharpe=-0.52,
        )
        is_valid, reasons, _ = validate_factor("interaction_amp_compression", data)
        assert is_valid, f"amp_compression 应通过, 实际: {reasons}"

    def test_amplitude_rejected_by_p_value(self):
        """interaction_amplitude: ic=0.0048 / p=0.113 → 淘汰（ic_mean+p_value 卡）"""
        data = _make_factor_data(
            ic_mean=0.004779,
            icir=0.0766,
            sharpe=3.0,
            mono_corr=0.418,
            p_value=0.1126,
            long_return=0.1161,
            layer_1_annual=-0.2064,
            layer_1_sharpe=-0.92,
        )
        is_valid, reasons, _ = validate_factor("interaction_amplitude", data)
        assert not is_valid
        # 主要应被 ic_mean 或 p_value 卡
        assert any("ic_mean" in r or "p_value" in r for r in reasons), reasons

    def test_turnover_rejected_multiple(self):
        """interaction_turnover: ic=0.0016 / icir=0.024 / p=0.611 → 淘汰"""
        data = _make_factor_data(
            ic_mean=0.001648,
            icir=0.0236,
            sharpe=1.93,
            mono_corr=0.374,
            p_value=0.6107,
            long_return=0.1127,
            layer_1_annual=-0.1633,
            layer_1_sharpe=-0.73,
        )
        is_valid, reasons, _ = validate_factor("interaction_turnover", data)
        assert not is_valid
        # 至少 ic_mean / icir / p_value 三条卡
        n_blocked = sum(1 for r in reasons if any(k in r for k in ["ic_mean", "icir", "p_value"]))
        assert n_blocked >= 2, f"turnover 应被多条门槛卡, 实际 reasons={reasons}"


class TestConfirmationRoleOverride:
    """confirmation 角色 ic_threshold override 测试

    v2.36 三因子的 FACTOR_ROLES 是 'confirmation' (ic_threshold=0.01)。
    v2.39 修正: 交互因子族 INTERACTION_THRESHOLDS[ic_mean_abs_min]=0.005 应覆盖 confirmation 0.01。
    """

    def test_interaction_overrides_confirmation(self):
        """interaction_amp_compression 是 confirmation 角色, 但 ic=0.0077 应过 0.005"""
        # 实测精确值: ic=0.0077, 0.005 < 0.0077 < 0.01 (confirmation)
        # 若没有 override, 走 confirmation 0.01 会卡; 走 interaction 0.005 才能过
        data = _make_factor_data(
            ic_mean=0.0077,
            icir=0.12,
            sharpe=2.59,
            mono_corr=0.36,
            p_value=0.012,
            long_return=0.10,
            layer_1_annual=-0.12,
        )
        is_valid, reasons, _ = validate_factor("interaction_amp_compression", data)
        assert is_valid, f"interaction override confirmation 失败, reasons={reasons}"
