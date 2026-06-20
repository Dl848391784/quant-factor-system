"""豁免信息传递链测试

验证 validate_factor → filter_invalid_factors → select_factors 的豁免详情传递。
遵循 MODULE.md M57/M58。

测试场景:
1. 豁免成功: |ic_mean|<0.03 但回测强劲(夏普>1.5, 单调性>0.5, |ic_mean|>=0.005) → 入选 + exempted=True
2. 豁免失败: |ic_mean|<0.03 且回测不足(夏普<1.5) → 剔除 + exempted=False
3. 无豁免触发: |ic_mean|>=0.03 → 正常通过, exempt_details=[]
4. ICIR豁免: |icir|<0.15 但回测强劲 → 豁免成功
5. ICIR豁免失败: |icir|<0.15 且回测不足 → 剔除 + exempted=False
6. 双豁免: |ic_mean|<0.03 且 |icir|<0.15, 回测强劲 → 两条豁免记录
7. filter_invalid_factors 结果含 exempted_factors 字段
"""

import pytest
from comprehensive_factor.common.factor_selector import (
    DEFAULT_THRESHOLDS,
    filter_invalid_factors,
    validate_factor,
)


def _make_factor_data(
    ic_mean: float | None,
    icir: float | None,
    sharpe: float | None,
    mono_corr: float | None,
    valid_days: int = 100,
    p_value: float | None = 0.01,
    ls_return: float = 0.10,
) -> dict:
    """构造测试用因子数据"""
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
                "long_short_return_annual": ls_return,
            },
            "monotonicity": {"correlation": mono_corr},
        },
    }


class TestExemptionSuccess:
    """豁免成功场景"""

    def test_ic_mean_exempted_success(self):
        """|ic_mean|=0.017<0.03, 夏普=5.54>1.5, 单调性=0.53>0.5 → 豁免入选"""
        data = _make_factor_data(
            ic_mean=-0.017,
            icir=0.33,
            sharpe=5.54,
            mono_corr=-0.53,
            valid_days=24,
        )
        is_valid, reasons, exempt_details = validate_factor("test_factor", data)

        assert is_valid is True
        assert len(reasons) == 0
        assert len(exempt_details) == 1
        assert exempt_details[0]["trigger"] == "ic_mean"
        assert exempt_details[0]["exempted"] is True
        assert exempt_details[0]["actual"] == pytest.approx(0.017)
        assert exempt_details[0]["conditions"]["sharpe"] == 5.54

    def test_icir_exempted_success(self):
        """|icir|=0.12<0.15, 夏普=2.0>1.5, 单调性=0.6>0.5 → ICIR豁免成功"""
        data = _make_factor_data(
            ic_mean=-0.05,
            icir=0.12,
            sharpe=2.0,
            mono_corr=-0.6,
        )
        is_valid, reasons, exempt_details = validate_factor("test_factor", data)

        assert is_valid is True
        assert len(reasons) == 0
        # ic_mean=-0.05 > 0.03, 不触发ic_mean豁免; icir=0.12<0.15 触发icir豁免
        assert len(exempt_details) == 1
        assert exempt_details[0]["trigger"] == "icir"
        assert exempt_details[0]["exempted"] is True


class TestExemptionFailure:
    """豁免失败场景"""

    def test_ic_mean_exempted_failure_low_sharpe(self):
        """|ic_mean|=0.013<0.03, 夏普=1.43<1.5 → 豁免失败, 剔除"""
        data = _make_factor_data(
            ic_mean=-0.013,
            icir=0.25,
            sharpe=1.43,
            mono_corr=-0.62,
            valid_days=23,
        )
        is_valid, reasons, exempt_details = validate_factor("test_factor", data)

        assert is_valid is False
        assert any("|ic_mean|" in r for r in reasons)
        assert len(exempt_details) == 1
        assert exempt_details[0]["trigger"] == "ic_mean"
        assert exempt_details[0]["exempted"] is False
        assert "夏普" in exempt_details[0]["detail"]

    def test_ic_mean_exempted_failure_low_mono(self):
        """|ic_mean|=0.013<0.03, 夏普=2.0>1.5, 单调性=0.3<0.5 → 豁免失败"""
        data = _make_factor_data(
            ic_mean=-0.013,
            icir=0.25,
            sharpe=2.0,
            mono_corr=0.3,
        )
        is_valid, reasons, exempt_details = validate_factor("test_factor", data)

        assert is_valid is False
        assert len(exempt_details) == 1
        assert exempt_details[0]["exempted"] is False
        assert "单调性" in exempt_details[0]["detail"]

    def test_icir_exempted_failure(self):
        """|icir|=0.10<0.15, 夏普=1.0<1.5 → ICIR豁免失败"""
        data = _make_factor_data(
            ic_mean=-0.05,
            icir=0.10,
            sharpe=1.0,
            mono_corr=0.6,
        )
        is_valid, reasons, exempt_details = validate_factor("test_factor", data)

        assert is_valid is False
        assert any("|icir|" in r for r in reasons)
        assert len(exempt_details) == 1
        assert exempt_details[0]["trigger"] == "icir"
        assert exempt_details[0]["exempted"] is False


class TestNoExemptionTriggered:
    """无豁免触发场景"""

    def test_normal_pass(self):
        """|ic_mean|=0.05>0.03, |icir|=0.30>0.15 → 正常通过, 无豁免"""
        data = _make_factor_data(
            ic_mean=-0.05,
            icir=0.30,
            sharpe=2.0,
            mono_corr=-0.7,
        )
        is_valid, reasons, exempt_details = validate_factor("test_factor", data)

        assert is_valid is True
        assert len(reasons) == 0
        assert len(exempt_details) == 0

    def test_missing_ic_mean(self):
        """ic_mean 缺失 → 无效, 无豁免"""
        data = _make_factor_data(
            ic_mean=None,
            icir=0.30,
            sharpe=2.0,
            mono_corr=-0.7,
        )
        is_valid, reasons, exempt_details = validate_factor("test_factor", data)

        assert is_valid is False
        assert any("ic_mean 缺失" in r for r in reasons)
        assert len(exempt_details) == 0


class TestDualExemption:
    """双豁免场景: ic_mean 和 icir 同时触发"""

    def test_dual_exempted_success(self):
        """|ic_mean|=0.01<0.03 且 |icir|=0.10<0.15, 回测强劲 → 两条豁免记录"""
        data = _make_factor_data(
            ic_mean=-0.01,
            icir=0.10,
            sharpe=3.0,
            mono_corr=-0.7,
        )
        is_valid, reasons, exempt_details = validate_factor("test_factor", data)

        assert is_valid is True
        assert len(reasons) == 0
        assert len(exempt_details) == 2
        triggers = {d["trigger"] for d in exempt_details}
        assert triggers == {"ic_mean", "icir"}
        assert all(d["exempted"] is True for d in exempt_details)

    def test_dual_exempted_mixed(self):
        """|ic_mean|=0.01<0.03 豁免成功, |icir|=0.10<0.15 豁免也成功 → 入选"""
        # 豁免条件相同, 要么都成功要么都失败
        data = _make_factor_data(
            ic_mean=-0.01,
            icir=0.10,
            sharpe=2.5,
            mono_corr=-0.6,
        )
        is_valid, reasons, exempt_details = validate_factor("test_factor", data)

        assert is_valid is True
        assert len(exempt_details) == 2
        assert all(d["exempted"] is True for d in exempt_details)


class TestFilterInvalidFactorsExemption:
    """filter_invalid_factors 结果含 exempted_factors 字段"""

    def test_filter_result_has_exempted_factors_field(self):
        """filter_invalid_factors 返回值含 exempted_factors 字段"""
        all_factors = {
            "exempt_success": _make_factor_data(ic_mean=-0.017, icir=0.33, sharpe=5.54, mono_corr=-0.53, valid_days=24),
            "exempt_fail": _make_factor_data(ic_mean=-0.013, icir=0.25, sharpe=1.43, mono_corr=-0.62, valid_days=23),
            "normal_pass": _make_factor_data(ic_mean=-0.05, icir=0.30, sharpe=2.0, mono_corr=-0.7),
        }
        result = filter_invalid_factors(all_factors=all_factors)

        assert "exempted_factors" in result
        exempted = result["exempted_factors"]
        # exempt_success: 豁免成功(入选但有豁免记录)
        assert "exempt_success" in exempted
        assert exempted["exempt_success"][0]["exempted"] is True
        # exempt_fail: 豁免失败(被剔除但有豁免记录)
        assert "exempt_fail" in exempted
        assert exempted["exempt_fail"][0]["exempted"] is False
        # normal_pass: 无豁免触发
        assert "normal_pass" not in exempted

    def test_exempted_factors_contains_both_valid_and_invalid(self):
        """exempted_factors 同时包含入选(豁免成功)和剔除(豁免失败)的因子"""
        all_factors = {
            "exempt_valid": _make_factor_data(ic_mean=-0.02, icir=0.33, sharpe=3.0, mono_corr=-0.6),
            "exempt_invalid": _make_factor_data(ic_mean=-0.02, icir=0.10, sharpe=1.0, mono_corr=0.3),
        }
        result = filter_invalid_factors(all_factors=all_factors)

        assert "exempt_valid" in result["valid"]
        assert "exempt_invalid" in result["invalid"]
        assert "exempt_valid" in result["exempted_factors"]
        assert "exempt_invalid" in result["exempted_factors"]
