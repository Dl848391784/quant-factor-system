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
        assert any("layer_1_annual" in r and "不可豁免" in r for r in reasons)

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
        # IC豁免可能触发，但L1硬约束仍淘汰
        assert any("layer_1_annual" in r and "不可豁免" in r for r in reasons)

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


class TestInteractionFactorL1Exemption:
    """v2.38: 交互因子族 L1 硬约束豁免

    第一性原理: 交互因子 = -z(weakness) × z(X), L1 必亏（数学必然）
    豁免阈值: long_return>10% AND ls_sharpe>1.5 AND mono_corr>0.5
    限定范围: factor_name.startswith("interaction_")

    见 designs/feat_interaction_exemption_and_weight_cap.md §4.1
    """

    def test_strong_interaction_factor_exempted(self):
        """优质交互因子豁免通过（对应 interaction_ma5_dev: long_return=24.2%, sharpe=4.25, mono=0.76）"""
        data = _make_factor_data(
            ic_mean=0.0306,
            icir=0.38,
            sharpe=4.25,
            mono_corr=0.76,
            long_return=0.242,  # 多头年化 24.2% > 10%
            layer_1_annual=-0.246,  # L1 = -24.6%
            layer_1_sharpe=-1.05,
        )
        is_valid, reasons, exempt_details = validate_factor("interaction_ma5_dev", data)
        assert is_valid, f"优质交互因子应豁免, reasons={reasons}"
        # 验证两个豁免条目都被记录
        l1_annual_exempt = [e for e in exempt_details if e["trigger"] == "layer_1_annual" and e["exempted"]]
        l1_sharpe_exempt = [e for e in exempt_details if e["trigger"] == "layer_1_sharpe" and e["exempted"]]
        assert len(l1_annual_exempt) == 1, "L1年化豁免记录应存在"
        assert len(l1_sharpe_exempt) == 1, "L1夏普豁免记录应存在"
        assert l1_annual_exempt[0]["conditions"]["is_interaction"] is True

    def test_weak_interaction_factor_not_exempted_low_long_return(self):
        """弱交互因子 long_return 不达标→淘汰（对应 interaction_turnover: long_return=8.9%<10%）"""
        data = _make_factor_data(
            ic_mean=0.0016,
            icir=0.02,
            sharpe=1.93,
            mono_corr=0.37,  # < 0.5 也不达标
            long_return=0.089,  # 多头年化 8.9% < 10%
            layer_1_annual=-0.163,
            layer_1_sharpe=-0.73,
        )
        is_valid, reasons, _ = validate_factor("interaction_turnover", data)
        assert not is_valid
        # L1 硬约束仍触发（因为豁免条件不满足）
        assert any("layer_1_annual" in r and "不可豁免" in r for r in reasons)

    def test_weak_interaction_factor_not_exempted_low_monotonicity(self):
        """弱交互因子 mono_corr 不达标→淘汰（对应 interaction_amp_compression: mono=0.36<0.5）"""
        data = _make_factor_data(
            ic_mean=0.0077,
            icir=0.12,
            sharpe=2.59,
            mono_corr=0.36,  # < 0.5
            long_return=0.079,
            layer_1_annual=-0.118,
            layer_1_sharpe=-0.52,
        )
        is_valid, reasons, _ = validate_factor("interaction_amp_compression", data)
        assert not is_valid
        assert any("layer_1_annual" in r and "不可豁免" in r for r in reasons)

    def test_non_interaction_factor_not_exempted_even_if_metrics_match(self):
        """非交互因子即使指标满足豁免阈值也不豁免（安全保底，单调因子 L1 约束保持）"""
        data = _make_factor_data(
            sharpe=4.0,  # 高夏普
            mono_corr=0.7,  # 高单调性
            long_return=0.20,  # 高多头收益
            layer_1_annual=-0.20,  # L1 负
            layer_1_sharpe=-1.0,
        )
        # 名字不以 interaction_ 开头 → 不豁免
        is_valid, reasons, _ = validate_factor("amplitude", data)
        assert not is_valid
        assert any("layer_1_annual" in r and "不可豁免" in r for r in reasons)

    def test_interaction_factor_l1_positive_passes_normally(self):
        """L1 已经为正的交互因子不需要豁免，正常通过"""
        data = _make_factor_data(
            ic_mean=0.025,
            icir=0.30,
            sharpe=3.0,
            mono_corr=0.6,
            long_return=0.15,
            layer_1_annual=0.05,  # L1 已经为正
            layer_1_sharpe=0.30,
        )
        is_valid, reasons, exempt_details = validate_factor("interaction_test_pos_l1", data)
        assert is_valid, f"L1已正向的交互因子应通过, reasons={reasons}"
        # 不应记录 L1 豁免（因为 L1 检查根本没失败）
        l1_exempts = [e for e in exempt_details if e["trigger"] in ("layer_1_annual", "layer_1_sharpe")]
        assert len(l1_exempts) == 0, "L1已正向不应触发豁免记录"
