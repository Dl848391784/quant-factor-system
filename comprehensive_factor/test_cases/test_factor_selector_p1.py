"""P1: 只做多对齐——筛选门槛测试

验证 design.md P1 改动：
1. L1年化<=0 的因子被硬约束淘汰（不可豁免，即使回测强劲）
2. L1夏普<=0 的因子被淘汰
3. min_sample_days=60（短样本24天不通过）
4. long_return（多头年化）替代 long_short_return（多空年化）
5. L1>0 的有效因子正常通过

遵循 designs/strategy_systemic_overhaul.md §2.1 决策。
"""

import pytest
from comprehensive_factor.common.factor_selector import (
    DEFAULT_THRESHOLDS,
    validate_factor,
)


def _make_factor_data(
    ic_mean: float | None = -0.04,
    icir: float | None = 0.30,
    sharpe: float | None = 2.0,
    mono_corr: float | None = 0.5,
    valid_days: int = 100,
    p_value: float | None = 0.01,
    long_return: float = 0.10,
    layer_1_annual: float | None = 0.15,
    layer_1_sharpe: float | None = 0.60,
    long_short_return: float = 0.20,
) -> dict:
    """构造测试用因子数据（含 layer_stats）

    默认值代表一个健康的反转因子：
    - IC=-0.04(通过0.03门槛), ICIR=0.30(通过0.15), 夏普=2.0, 单调性=0.5
    - L1年化=+15%, L1夏普=0.60, 多头年化=10%
    """
    return {
        "ic_metrics": {
            "ic_mean": ic_mean,
            "icir": icir,
            "p_value": p_value,
        },
        "sample_stats": {"valid_days": valid_days},
        "backtest": {
            "long_short": {
                "long_short_sharpe": sharpe,
                "long_short_return_annual": long_short_return,
                "long_return_annual": long_return,
            },
            "monotonicity": {"correlation": mono_corr},
            "layer_stats": {
                "layer_1": {
                    "annual_return": layer_1_annual,
                    "sharpe_ratio": layer_1_sharpe,
                },
                "layer_5": {
                    "annual_return": -0.20,
                    "sharpe_ratio": -0.80,
                },
            },
        },
    }


class TestLayer1HardConstraint:
    """L1>0 不可豁免硬约束"""

    def test_l1_positive_factor_passes(self):
        """L1年化>0 + L1夏普>0 的因子正常通过"""
        data = _make_factor_data(layer_1_annual=0.15, layer_1_sharpe=0.60)
        is_valid, reasons, _ = validate_factor("test_good", data)
        assert is_valid, f"L1>0因子应通过, reasons={reasons}"

    def test_l1_negative_factor_rejected(self):
        """L1年化<0 的因子被淘汰（如 tail_volume_acceleration L1=-117%）"""
        data = _make_factor_data(layer_1_annual=-0.57, layer_1_sharpe=-2.59)
        is_valid, reasons, _ = validate_factor("test_toxic", data)
        assert not is_valid
        assert any("layer_1_annual" in r and "硬约束" in r for r in reasons)

    def test_l1_zero_factor_rejected(self):
        """L1年化=0 的因子被淘汰（<=0 边界）"""
        data = _make_factor_data(layer_1_annual=0.0, layer_1_sharpe=0.0)
        is_valid, reasons, _ = validate_factor("test_zero_l1", data)
        assert not is_valid
        assert any("layer_1_annual" in r for r in reasons)

    def test_l1_negative_not_exempted_even_with_strong_backtest(self):
        """L1<0 即使回测强劲（高夏普+高单调性）也不可豁免"""
        data = _make_factor_data(
            layer_1_annual=-0.57,
            layer_1_sharpe=-2.59,
            sharpe=5.0,  # 回测夏普极高
            mono_corr=0.8,  # 单调性极强
            ic_mean=-0.06,  # IC很高
            icir=0.50,
        )
        is_valid, reasons, exempt_details = validate_factor("test_toxic_strong", data)
        assert not is_valid
        # IC豁免可能触发，但L1硬约束仍淘汰（v2.39: 线性因子走 default 0.0 阈值）
        assert any("layer_1_annual" in r and "硬约束" in r for r in reasons)

    def test_l1_sharpe_negative_rejected(self):
        """L1年化>0 但 L1夏普<0 的因子被淘汰"""
        data = _make_factor_data(layer_1_annual=0.05, layer_1_sharpe=-0.30)
        is_valid, reasons, _ = validate_factor("test_neg_sharpe", data)
        assert not is_valid
        assert any("layer_1_sharpe" in r for r in reasons)

    def test_l1_data_missing_skips_check(self):
        """L1数据缺失时不触发硬约束（跳过检查，由其他门槛判断）"""
        data = _make_factor_data()
        data["backtest"]["layer_stats"] = {}  # 清空 layer_stats
        is_valid, reasons, _ = validate_factor("test_no_l1", data)
        # 其他指标都通过，L1缺失不触发硬约束
        assert is_valid, f"L1缺失应跳过检查, reasons={reasons}"


class TestMinSampleDays:
    """min_sample_days=60 验证"""

    def test_60_days_passes(self):
        """60天样本通过"""
        data = _make_factor_data(valid_days=60)
        is_valid, reasons, _ = validate_factor("test_60d", data)
        assert is_valid, f"60天应通过, reasons={reasons}"

    def test_24_days_flagged_as_short(self):
        """24天样本被标记为短样本（但不直接剔除，由豁免/惩罚处理）"""
        data = _make_factor_data(valid_days=24, sharpe=0.5, mono_corr=0.3)
        # 24天不触发短样本豁免（需要夏普>3.0+单调性>0.6），但也不直接剔除
        is_valid, reasons, _ = validate_factor("test_24d", data)
        # 短样本本身不加入 reasons，但 ICIR/单调性等可能不达标
        # 这里主要验证 min_sample_days=60 被使用
        assert DEFAULT_THRESHOLDS["min_sample_days"] == 60


class TestLongReturnReplacesLongShort:
    """多头年化收益替代多空年化收益"""

    def test_low_long_return_rejected(self):
        """多头年化<3% 被淘汰"""
        data = _make_factor_data(long_return=0.01)  # 1% < 3%
        is_valid, reasons, _ = validate_factor("test_low_long_ret", data)
        assert not is_valid
        assert any("long_return" in r for r in reasons)

    def test_high_long_short_but_low_long_return_still_rejected(self):
        """多空年化高但多头年化低→仍被淘汰（只做多看多头）"""
        data = _make_factor_data(
            long_return=0.01,  # 多头1% < 3%
            long_short_return=0.30,  # 多空30%（高，但对只做多无意义）
        )
        is_valid, reasons, _ = validate_factor("test_ls_high_lr_low", data)
        assert not is_valid
        assert any("long_return" in r for r in reasons)

    def test_threshold_uses_long_return_not_long_short(self):
        """确认门槛字段是 long_return_min 而非 long_short_return_min"""
        assert "long_return_min" in DEFAULT_THRESHOLDS
        assert "long_short_return_min" not in DEFAULT_THRESHOLDS


class TestInteractionFactorL1Threshold:
    """v2.39: 交互因子族独立 L1 阈值

    第一性原理: 交互因子 = -z(weakness) × z(X), L1 必亏（数学必然）
    设计: INTERACTION_THRESHOLDS layer_1_return_min=-0.28 (v2.40), layer_1_sharpe_min=-1.50
    线性因子主 dict 阈值 0.0 / 0.0 不变

    取代 v2.38 的 L1 豁免分支（commit 4c845c0），v2.39 用独立门槛体系实现同等功能。
    v2.40 校准: 经验缓冲 (-25%) → 统计驱动 mean-2σ (-28%), 见 designs/feat_interaction_thresholds_v240.md
    """

    def test_interaction_factor_l1_negative_within_threshold_passes(self):
        """交互因子 L1=−0.20 > −0.25, 应通过（design.md §2.2 L1 阈值放宽）"""
        data = _make_factor_data(
            ic_mean=0.008,
            icir=0.10,
            sharpe=2.5,
            mono_corr=0.35,
            long_return=0.11,
            layer_1_annual=-0.20,
            layer_1_sharpe=-0.9,
        )
        is_valid, reasons, _ = validate_factor("interaction_test", data)
        assert is_valid, f"交互因子 L1=-0.20 在 -0.25 阈值内, 应通过, reasons={reasons}"

    def test_interaction_factor_l1_negative_beyond_threshold_rejected(self):
        """交互因子 L1=−0.30 < −0.25, 仍应淘汰（门槛是过滤器，不是收纳器）"""
        data = _make_factor_data(
            ic_mean=0.008,
            icir=0.10,
            sharpe=2.5,
            mono_corr=0.35,
            long_return=0.11,
            layer_1_annual=-0.30,
            layer_1_sharpe=-1.0,
        )
        is_valid, reasons, _ = validate_factor("interaction_test_xx", data)
        assert not is_valid
        assert any("layer_1_annual" in r for r in reasons)

    def test_non_interaction_factor_l1_negative_rejected_at_zero(self):
        """非交互因子 L1=−0.20 走 default 0.0 阈值, 仍应淘汰（线性因子主 dict 零修改）"""
        data = _make_factor_data(
            sharpe=4.0,
            mono_corr=0.7,
            long_return=0.20,
            layer_1_annual=-0.20,
            layer_1_sharpe=-1.0,
        )
        is_valid, reasons, _ = validate_factor("amplitude", data)
        assert not is_valid
        assert any("layer_1_annual" in r and "硬约束" in r for r in reasons)

    def test_interaction_factor_l1_positive_passes_normally(self):
        """L1 已经为正的交互因子正常通过"""
        data = _make_factor_data(
            ic_mean=0.025,
            icir=0.30,
            sharpe=3.0,
            mono_corr=0.6,
            long_return=0.15,
            layer_1_annual=0.05,
            layer_1_sharpe=0.30,
        )
        is_valid, reasons, _ = validate_factor("interaction_test_pos_l1", data)
        assert is_valid, f"L1已正向的交互因子应通过, reasons={reasons}"
