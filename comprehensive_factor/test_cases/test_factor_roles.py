"""P6-Step1: 角色化权重体系测试

验证 design.md P6（批次7）：
1. FACTOR_ROLES 定义正确（三角色: primary/confirmation/filter）
2. factor_selector 筛选结果包含 role 字段
3. 确认信号因子 IC 门槛降至 0.01（vs 主信号 0.03）

遵循 designs/strategy_systemic_overhaul.md §2.6。
"""

import pytest
from comprehensive_factor.common.factor_selector import DEFAULT_THRESHOLDS, validate_factor
from factor_definitions import (
    CONFIRMATION_WEIGHT_PER_FACTOR,
    FACTOR_CATEGORIES,
    FACTOR_ROLE_TYPES,
    FACTOR_ROLES,
    PRIMARY_WEIGHT_TOTAL,
)


@pytest.fixture(autouse=True)
def _disable_require_positive_ic(monkeypatch):
    """v2.45: 本测试文件测的是角色化 IC 门槛和反向因子豁免, 与 require_positive_ic 正交。
    显式关闭 require_positive_ic 让 ic_mean<0 的 fixture 数据保持原有断言意图。
    """
    monkeypatch.setitem(DEFAULT_THRESHOLDS, "require_positive_ic", False)


class TestFactorRolesDefinition:
    """FACTOR_ROLES 定义完整性"""

    def test_all_factors_have_role(self):
        """每个因子都有角色标记"""
        for f in FACTOR_CATEGORIES:
            assert f in FACTOR_ROLES, f"{f} 缺少角色标记"

    def test_role_values_valid(self):
        """角色值只允许 primary/confirmation/filter"""
        for f, role in FACTOR_ROLES.items():
            assert role in FACTOR_ROLE_TYPES, f"{f} 角色={role} 不在 {FACTOR_ROLE_TYPES}"

    def test_confirmation_factors_are_p5_new(self):
        """确认信号因子=P5新增5个 + P5-补充6个 + v2.36 交互因子3个 = 14"""
        confirmation = [f for f, r in FACTOR_ROLES.items() if r == "confirmation"]
        expected = {
            # P5 新增5个：趋势变化/量价背离
            "rsi_slope_3d",
            "ma5_slope",
            "lower_shadow_ratio",
            "volume_shrink_rate",
            "price_volume_divergence",
            # P5-补充6个：二阶导数企稳信号
            "return_acceleration_5d",
            "downside_deceleration",
            "amplitude_compression",
            "range_compression",
            "volume_decay_rate",
            "turnover_decay_rate",
            # v2.36: 交互因子族（IC≈+0.02 < 0.03 门槛, 走 confirmation 固定权重）
            "interaction_amplitude",
            "interaction_turnover",
            "interaction_amp_compression",
            # v2.37: 交互因子第二批 confirmation 角色
            "interaction_kdj",
            "interaction_bollinger",
        }
        assert set(confirmation) == expected

    def test_primary_count(self):
        """主信号因子=38个 (FACTOR_CATEGORIES 54 - confirmation 16)"""
        primary = [f for f, r in FACTOR_ROLES.items() if r == "primary"]
        assert len(primary) == 38

    def test_filter_role_has_cum_return_5d_breakdown(self):
        """filter 角色：R3 起新增 cum_return_5d_breakdown（首个 filter 因子）

        历史: 该测试原断言 `len(filters) == 0`（批次 8 才实现）。
              R3 启动后 (commit 98d6113, 2026-06-22) 提前到批次 1 上线。
        依据: designs/feat_filter_role_fundamental_breakdown.md §3.1-§3.2
              + designs/master_l1_l6_roadmap.md §2.3
        阈值: 5 日累计 -10% = 券商风控经验，A 股 ST 警示线邻近（绝对值边界，
              非百分位）。
        """
        filters = [f for f, r in FACTOR_ROLES.items() if r == "filter"]
        assert filters == ["cum_return_5d_breakdown"]

    def test_weight_constants(self):
        """权重常量正确（design.md §2.6 决策点2: 方案B）"""
        assert CONFIRMATION_WEIGHT_PER_FACTOR == 0.05
        assert PRIMARY_WEIGHT_TOTAL == 0.75


class TestValidateFactorRoleAware:
    """validate_factor 角色相关 IC 门槛"""

    def _make_factor_data(
        self,
        ic_mean: float = -0.015,
        icir: float = 0.3,
        layer_1_annual: float = 0.05,
        layer_1_sharpe: float = 1.0,
        valid_days: int = 100,
    ) -> dict:
        """构造因子数据（IC=0.015 在确认信号门槛0.01之上但主信号门槛0.03之下）"""
        return {
            "ic_metrics": {"ic_mean": ic_mean, "icir": icir},
            "backtest": {
                "layer_1_annual": layer_1_annual,
                "layer_1_sharpe": layer_1_sharpe,
                "long_return_annual": layer_1_annual,
                "long_short_sharpe": layer_1_sharpe,
                "monotonicity_corr": 0.6,
            },
            "sample_stats": {"valid_days": valid_days},
        }

    def test_confirmation_factor_passes_lower_ic_threshold(self):
        """确认信号因子 |IC|=0.015 > 0.01 → 通过（主信号门槛0.03会失败）"""
        factor_data = self._make_factor_data(ic_mean=-0.015)
        is_valid, reasons, _ = validate_factor("rsi_slope_3d", factor_data)
        assert is_valid, f"确认信号因子应通过低IC门槛, 失败原因: {reasons}"

    def test_primary_factor_fails_at_ic_015(self):
        """主信号因子 |IC|=0.015 < 0.03 → 失败（除非回测强劲豁免）"""
        factor_data = self._make_factor_data(ic_mean=-0.015)
        # 用一个 primary 角色的因子名
        is_valid, reasons, _ = validate_factor("rsi", factor_data)
        # |IC|=0.015 < 0.03, 且回测不强（sharpe=1.0<1.5），不豁免
        assert not is_valid, "主信号因子 |IC|=0.015<0.03 且回测不强，应失败"
        assert any("|ic_mean|" in r for r in reasons)

    def test_primary_factor_passes_at_ic_004(self):
        """主信号因子 |IC|=0.04 > 0.03 → 通过"""
        factor_data = self._make_factor_data(ic_mean=-0.04)
        is_valid, reasons, _ = validate_factor("rsi", factor_data)
        assert is_valid, f"主信号因子 |IC|=0.04>0.03 应通过, 失败原因: {reasons}"

    def test_confirmation_factor_fails_at_ic_0005(self):
        """确认信号因子 |IC|=0.005 < 0.01 → 失败"""
        factor_data = self._make_factor_data(ic_mean=-0.005)
        is_valid, reasons, _ = validate_factor("ma5_slope", factor_data)
        assert not is_valid, "确认信号因子 |IC|=0.005<0.01 应失败"
