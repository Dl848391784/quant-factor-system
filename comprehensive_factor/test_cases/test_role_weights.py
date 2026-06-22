"""test_role_weights: R2 角色固定权重（主 75% + 确认 25%）单元测试

测试目标:
- _apply_role_weights_static 按角色分桶重新分配权重
- primary 总额 75%, confirmation 总额 25% (自适应因子数量)
- filter 角色 → 权重 0
- enable_role_weights=False → 不改变原权重
- 权重总和 = 1.0

设计依据: designs/feat_role_based_fixed_weight_75_25.md §3.6
第一性原理: PRIMARY_WEIGHT_TOTAL=0.75 为锚, 非按 per-factor 固定值
"""

import logging
from unittest.mock import patch

import pytest
from comprehensive_factor.common.weight_engine import EqualWeightMethod, ICIRWeightMethod
from factor_definitions import FACTOR_ROLES, PRIMARY_WEIGHT_TOTAL


@pytest.fixture
def method_enabled():
    """启用 role_weights 的 EqualWeightMethod."""
    return EqualWeightMethod(enable_role_weights=True)


@pytest.fixture
def method_disabled():
    """禁用 role_weights 的 EqualWeightMethod (默认)."""
    return EqualWeightMethod()


# === 因子列名 (与 FACTOR_ROLES key 一致) ===
PRIMARY_COLS = ["momentum_strength", "return_3d", "rsi_6"]
CONFIRMATION_COLS = ["rsi_slope_3d", "ma5_slope", "lower_shadow_ratio"]


class TestRoleWeights:
    """_apply_role_weights_static 单元测试."""

    def test_disabled_by_default_no_change(self, method_disabled):
        """enable_role_weights=False → 权重不变."""
        weights = {"rsi_6": 0.5, "momentum_strength": 0.3, "rsi_slope_3d": 0.2}
        result = method_disabled._apply_role_weights_static(weights, list(weights.keys()))
        assert result == weights, "禁用时不应改变权重"

    def test_only_primary_degrades_to_normalized(self, method_enabled):
        """全 primary → role_weights 退化为原权重归一化."""
        weights = {"momentum_strength": 0.4, "return_3d": 0.3, "rsi_6": 0.3}
        result = method_enabled._apply_role_weights_static(weights, list(weights.keys()))
        # 无 confirmation → primary 按原比例分配 75%... 但 primary_total=0.75
        # 实际: confirmation_total=0, primary_total=0.75
        # primary_orig_sum = 1.0, 所以每个 = orig/1.0 * 0.75
        # 然后归一化: sum=0.75 → 归一化到 1.0
        # 最终 = orig/1.0 * 0.75 / 0.75 = orig
        assert abs(sum(result.values()) - 1.0) < 1e-9
        for col in weights:
            assert abs(result[col] - weights[col]) < 1e-9, f"{col} 权重不应改变"

    def test_primary_plus_confirmation_ratio(self, method_enabled):
        """3 primary + 2 confirmation → confirmation 各 12.5%, primary 共 75%."""
        cols = PRIMARY_COLS[:3] + CONFIRMATION_COLS[:2]
        # 原始权重: primary 各 0.25, confirmation 各 0.125 (总和 1.0)
        weights = {
            "momentum_strength": 0.25,
            "return_3d": 0.25,
            "rsi_6": 0.25,
            "rsi_slope_3d": 0.125,
            "ma5_slope": 0.125,
        }
        result = method_enabled._apply_role_weights_static(weights, cols)

        # confirmation: 每个 = 0.25 / 2 = 0.125
        assert abs(result["rsi_slope_3d"] - 0.125) < 1e-9
        assert abs(result["ma5_slope"] - 0.125) < 1e-9

        # primary: 共 0.75, 按原比例 0.25:0.25:0.25 = 1:1:1
        primary_sum = result["momentum_strength"] + result["return_3d"] + result["rsi_6"]
        assert abs(primary_sum - 0.75) < 1e-9
        # 每个应该均等 0.25
        assert abs(result["momentum_strength"] - 0.25) < 1e-9

    def test_confirmation_count_adaptive(self, method_enabled):
        """confirmation 因子数量变化时, 每个 confirmation 权重自适应."""
        all_confirm = [k for k, v in FACTOR_ROLES.items() if v == "confirmation"]
        cols_3 = PRIMARY_COLS[:1] + all_confirm[:3]
        cols_10 = PRIMARY_COLS[:1] + all_confirm[:10]

        weights_3 = dict.fromkeys(cols_3, 1.0 / len(cols_3))
        result_3 = method_enabled._apply_role_weights_static(weights_3, cols_3)
        per_factor_3 = 0.25 / 3
        for col in all_confirm[:3]:
            assert abs(result_3[col] - per_factor_3) < 1e-9, (
                f"3 confirmation: {col} 应为 {per_factor_3}"
            )

        weights_10 = dict.fromkeys(cols_10, 1.0 / len(cols_10))
        result_10 = method_enabled._apply_role_weights_static(weights_10, cols_10)
        per_factor_10 = 0.25 / 10
        for col in all_confirm[:10]:
            assert abs(result_10[col] - per_factor_10) < 1e-9, (
                f"10 confirmation: {col} 应为 {per_factor_10} (非 0.05)"
            )

    def test_sum_equals_one(self, method_enabled):
        """各种组合, 权重和 = 1.0 (1e-9 精度)."""
        all_confirm = [k for k, v in FACTOR_ROLES.items() if v == "confirmation"]
        test_cases = [
            PRIMARY_COLS[:1] + all_confirm[:1],
            PRIMARY_COLS[:3] + all_confirm[:3],
            PRIMARY_COLS[:1] + all_confirm[:10],
            PRIMARY_COLS[:5] + all_confirm[:16],
        ]
        for cols in test_cases:
            weights = dict.fromkeys(cols, 1.0 / len(cols))
            result = method_enabled._apply_role_weights_static(weights, cols)
            total = sum(result.values())
            assert abs(total - 1.0) < 1e-9, f"权重和={total} ≠ 1.0, cols={cols}"

    def test_no_primary_confirmation_100pct(self, method_enabled, caplog):
        """无 primary, 仅 confirmation → warning + confirmation 占 100%."""
        all_confirm = [k for k, v in FACTOR_ROLES.items() if v == "confirmation"]
        cols = all_confirm[:3]
        weights = dict.fromkeys(cols, 1.0 / 3)
        with caplog.at_level(logging.WARNING):
            result = method_enabled._apply_role_weights_static(weights, cols)
        # confirmation 应占 100%
        assert abs(sum(result.values()) - 1.0) < 1e-9
        # 每个 = 1/3 (0.25/3 归一化到 1.0)
        per_factor = 1.0 / 3
        for col in cols:
            assert abs(result[col] - per_factor) < 1e-9

    def test_primary_zero_weights_fallback(self, method_enabled, caplog):
        """primary 原权重全 0 → 等权降级."""
        cols = PRIMARY_COLS[:3] + CONFIRMATION_COLS[:2]
        # primary 权重全 0, confirmation 有权重
        weights = {
            "momentum_strength": 0.0,
            "return_3d": 0.0,
            "rsi_6": 0.0,
            "rsi_slope_3d": 0.5,
            "ma5_slope": 0.5,
        }
        with caplog.at_level(logging.WARNING):
            result = method_enabled._apply_role_weights_static(weights, cols)
        # primary 等权: 0.75/3 = 0.25 each
        for col in PRIMARY_COLS[:3]:
            assert abs(result[col] - 0.25) < 1e-9
        # confirmation: 0.25/2 = 0.125 each
        assert abs(result["rsi_slope_3d"] - 0.125) < 1e-9
        assert abs(result["ma5_slope"] - 0.125) < 1e-9

    def test_filter_factor_zeroed(self, method_enabled):
        """filter 角色因子权重 = 0 (不进 composite)."""
        # 临时 mock FACTOR_ROLES 加入 filter 角色
        import comprehensive_factor.common.weight_engine as we

        mock_roles = dict(FACTOR_ROLES)
        mock_roles["momentum_strength"] = "filter"  # 临时改为 filter

        with patch.object(we, "_MODULE_FACTOR_ROLES", mock_roles):
            cols = ["momentum_strength", "return_3d"] + CONFIRMATION_COLS[:2]
            weights = dict.fromkeys(cols, 0.25)
            result = method_enabled._apply_role_weights_static(weights, cols)

        assert result["momentum_strength"] == 0.0, "filter 因子权重应为 0"
        assert abs(sum(result.values()) - 1.0) < 1e-9

    def test_not_05_per_confirmation(self, method_enabled):
        """关键: 16 个 confirmation 时每个 ≠ 0.05 (design bug 修正验证)."""
        all_confirm = [k for k, v in FACTOR_ROLES.items() if v == "confirmation"]
        n = len(all_confirm)
        cols = PRIMARY_COLS[:1] + all_confirm
        weights = dict.fromkeys(cols, 1.0 / len(cols))
        result = method_enabled._apply_role_weights_static(weights, cols)

        per_factor = 0.25 / n
        assert per_factor != 0.05, f"0.25/{n} 不应等于 0.05"
        for col in all_confirm:
            assert abs(result[col] - per_factor) < 1e-9
            assert result[col] < 0.05, f"{col} 权重应 < 0.05 (16 因子时)"

    def test_icir_method_also_supported(self):
        """ICIRWeightMethod 也支持 enable_role_weights."""
        method = ICIRWeightMethod(enable_role_weights=True)
        cols = PRIMARY_COLS[:3] + CONFIRMATION_COLS[:2]
        weights = {
            "momentum_strength": 0.4,
            "return_3d": 0.3,
            "rsi_6": 0.2,
            "rsi_slope_3d": 0.05,
            "ma5_slope": 0.05,
        }
        result = method._apply_role_weights_static(weights, cols)
        assert abs(sum(result.values()) - 1.0) < 1e-9
        # confirmation 各 12.5%
        assert abs(result["rsi_slope_3d"] - 0.125) < 1e-9
        assert abs(result["ma5_slope"] - 0.125) < 1e-9
