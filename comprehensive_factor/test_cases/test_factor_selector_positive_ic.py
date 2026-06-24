"""测试 require_positive_ic 硬门槛（v2.45）

设计文档: designs/factor_selector_positive_ic_only.md
注入点: validate_factor (factor_selector.py L416 后)

测试覆盖:
1. 默认行为不变 (require_positive_ic=False)
2. 启用后剔除 ic_mean<0 因子
3. 启用后不可被反向豁免绕过
4. 启用后保留 ic_mean>0 因子
5. ic_mean=0 边界（不剔除，因为 0 不算负）
6. ic_mean is None 时不触发（与现有 None 处理一致）
"""

from __future__ import annotations

import sys
from pathlib import Path


# 把项目根目录加入路径
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from comprehensive_factor.common.factor_selector import (  # noqa: E402
    DEFAULT_THRESHOLDS,
    validate_factor,
)


def _make_factor_data(
    ic_mean: float | None,
    icir: float = 0.3,
    sharpe: float = 0.5,
    mono: float = 0.5,
    p: float = 0.01,
    long_ret: float = 0.05,
    valid_days: int = 500,
    l1_ret: float = 0.05,
    l1_sharpe: float = 0.5,
):
    """构造一个 factor_data 字典"""
    return {
        "ic_metrics": {"ic_mean": ic_mean, "icir": icir, "p_value": p},
        "sample_stats": {"valid_days": valid_days},
        "backtest": {
            "long_short": {"long_short_sharpe": sharpe},
            "monotonicity": {"correlation": mono},
            "long_only": {"long_return": long_ret, "sharpe": l1_sharpe},
            "layer_returns": {"layer_1_annual": l1_ret, "layer_1_sharpe": l1_sharpe},
        },
    }


class TestDefaultBehaviorRequirePositiveIc:
    """v2.45: require_positive_ic 默认 True — 启用动量风格硬门槛"""

    def test_default_thresholds_has_require_positive_ic_true(self):
        """DEFAULT_THRESHOLDS 默认 require_positive_ic=True（v2.45 启用）"""
        assert "require_positive_ic" in DEFAULT_THRESHOLDS
        assert DEFAULT_THRESHOLDS["require_positive_ic"] is True

    def test_negative_ic_factor_passes_when_explicitly_disabled(self):
        """显式 require_positive_ic=False 时, ic_mean<0 但其他指标都过的因子 → valid"""
        t = dict(DEFAULT_THRESHOLDS)
        t["require_positive_ic"] = False
        # 强反向因子：ic_mean<0 但 |ic_mean|>0.03 + |icir|>0.15 + 高夏普高单调
        factor_data = _make_factor_data(ic_mean=-0.05, icir=-0.3, sharpe=2.0, mono=0.6)
        is_valid, reasons, _ = validate_factor("rsi", factor_data, thresholds=t)
        # 显式关闭后应通过（|ic_mean|=0.05>0.03, |icir|=0.3>0.15）
        assert is_valid, f"显式关闭 require_positive_ic 后应通过, 但 invalid, reasons={reasons}"


class TestRequirePositiveIcEnforced:
    """require_positive_ic=True 时硬门槛生效"""

    def _enabled_thresholds(self):
        t = dict(DEFAULT_THRESHOLDS)
        t["require_positive_ic"] = True
        return t

    def test_negative_ic_factor_rejected(self):
        """启用后, ic_mean<0 即使其他指标全 OK 也会被剔除"""
        factor_data = _make_factor_data(ic_mean=-0.05, icir=-0.3, sharpe=2.0, mono=0.6)
        is_valid, reasons, _ = validate_factor("rsi", factor_data, thresholds=self._enabled_thresholds())
        assert not is_valid, "启用 require_positive_ic 后 IC 负应剔除"
        # 必须有专门的剔除原因
        assert any("require_positive_ic" in r for r in reasons), (
            f"reasons 应含 require_positive_ic 字样, 实际: {reasons}"
        )

    def test_negative_ic_not_exempted_by_strong_backtest(self):
        """启用后, 即使触发反向因子豁免, 也会被 require_positive_ic 二次剔除（不可豁免）"""
        # 构造一个会触发反向因子豁免的因子: |ic_mean|<0.03 但夏普>1.5+单调>0.5
        factor_data = _make_factor_data(ic_mean=-0.008, icir=0.2, sharpe=2.5, mono=0.6)
        is_valid, reasons, _ = validate_factor("rsi", factor_data, thresholds=self._enabled_thresholds())
        # 即使 ic_mean 通过反向豁免, require_positive_ic 也会再剔除一次
        assert not is_valid, "启用 require_positive_ic 后, 反向豁免不应绕过该硬门槛"
        assert any("require_positive_ic" in r for r in reasons)

    def test_positive_ic_factor_passes(self):
        """启用后, ic_mean>0 的因子正常通过其他门槛即可"""
        factor_data = _make_factor_data(ic_mean=+0.05, icir=0.3, sharpe=1.0, mono=0.5)
        is_valid, reasons, _ = validate_factor("rsi", factor_data, thresholds=self._enabled_thresholds())
        assert is_valid, f"启用 require_positive_ic 后 IC 正应通过, reasons={reasons}"

    def test_zero_ic_not_rejected(self):
        """ic_mean=0 不算负, 不被 require_positive_ic 剔除（但会被 |ic_mean|<0.03 剔除）"""
        factor_data = _make_factor_data(ic_mean=0.0, icir=0.3, sharpe=1.0, mono=0.5)
        is_valid, reasons, _ = validate_factor("rsi", factor_data, thresholds=self._enabled_thresholds())
        # 因为 |ic_mean|=0<0.03 会被普通门槛剔除
        assert not is_valid
        # 但剔除原因里不应包含 require_positive_ic 字样
        assert not any("require_positive_ic" in r for r in reasons), (
            f"ic_mean=0 不应触发 require_positive_ic 剔除, reasons={reasons}"
        )

    def test_none_ic_not_rejected_by_positive_ic(self):
        """ic_mean=None 不触发 require_positive_ic（与现有 None 处理一致）"""
        factor_data = _make_factor_data(ic_mean=None)
        is_valid, reasons, _ = validate_factor("rsi", factor_data, thresholds=self._enabled_thresholds())
        # None 会被普通门槛剔除, 但不应被 require_positive_ic 剔除
        assert not is_valid
        assert not any("require_positive_ic" in r for r in reasons)


class TestInteractionFactorAlsoAffected:
    """交互因子族 merge 时继承主 dict 的 require_positive_ic"""

    def test_interaction_factor_negative_ic_rejected_when_enabled(self):
        """启用后, interaction_xxx 因子 ic_mean<0 也会被剔除"""
        t = dict(DEFAULT_THRESHOLDS)
        t["require_positive_ic"] = True
        # 交互因子的典型负 IC（ic_mean<0 但 |ic_mean|>0.005）
        factor_data = _make_factor_data(ic_mean=-0.015, icir=-0.1, sharpe=0.5, mono=0.4)
        is_valid, reasons, _ = validate_factor("interaction_bollinger__ret5d_neg", factor_data, thresholds=t)
        assert not is_valid
        assert any("require_positive_ic" in r for r in reasons), (
            f"交互因子也应被 require_positive_ic 剔除, reasons={reasons}"
        )
