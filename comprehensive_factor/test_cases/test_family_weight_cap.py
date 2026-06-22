"""族级权重上限测试 (v2.40 design.md §3.2)

测试覆盖:
1. dict 版 _cap_family_weight 基本族级 cap
2. 单族无超限：无操作
3. 多族超限：按族内比例降权 + 摊分至 under 族
4. 与 _cap_single_factor_weight 协同：双 cap 同时生效
5. matrix 版 _cap_weight_matrix 族级 cap（用于 RollingICIR）
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

import numpy as np
import pytest


# 项目根加入 sys.path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from comprehensive_factor.common.weight_engine import (
    FAMILY_CAP_DEFAULT,
    WEIGHT_CAP_DEFAULT,
    WeightMethodBase,
)


@pytest.fixture
def logger():
    log = logging.getLogger("test_family_cap")
    log.setLevel(logging.INFO)
    return log


class TestCapFamilyWeightDict:
    """dict 版 _cap_family_weight"""

    def test_single_family_under_cap_no_change(self, logger):
        """单族 + 总权重 < cap → 不变"""
        weights = {"rsi_6": 0.5, "kdj_j_9": 0.5}
        # rsi + kdj_j 都属于 momentum_family，sum=1.0 > 0.30 但因为只有一个族，不可行
        result = WeightMethodBase._cap_family_weight(weights, list(weights), cap=0.30, logger=logger)
        # 物理不可行: 单族 cap=0.30 而 sum=1.0 → 函数自动跳过
        assert sum(result.values()) == pytest.approx(1.0, abs=1e-6)

    def test_two_families_one_over_cap(self, logger):
        """多族, 振幅族超 30%, 其余族 under

        cap=0.30 时 n_families ≥ 4 才物理可行 (4×0.30=1.20≥1.0)
        """
        weights = {
            "amplitude_compression_5": 0.40,  # amplitude_family (40%)
            "rsi_6": 0.20,  # momentum_family
            "momentum_strength": 0.20,  # momentum_family (动量 40%)
            "volume_decay_rate_5": 0.12,  # volume_family (12%)
            "overnight_ret_5": 0.08,  # overnight_family (8%)
        }
        result = WeightMethodBase._cap_family_weight(weights, list(weights), cap=0.30, logger=logger)
        # 验证 sum 不变
        assert sum(result.values()) == pytest.approx(1.0, abs=1e-6)
        # 验证振幅族降到 0.30
        amp_val = result["amplitude_compression_5"]
        assert amp_val == pytest.approx(0.30, abs=1e-3)
        # 验证动量族也降到 0.30（从 0.40）
        mom_total = result["rsi_6"] + result["momentum_strength"]
        assert mom_total == pytest.approx(0.30, abs=1e-3)
        # 验证 under 族增加（吸收 excess）
        assert result["volume_decay_rate_5"] > 0.12

    def test_family_cap_proportional_within_family(self, logger):
        """族内按原比例降权（需 ≥4 族保证 cap=0.30 物理可行）"""
        weights = {
            "amplitude_compression_5": 0.40,  # 振幅族 0.60, 原比例 2/3
            "interaction_amp_compression": 0.20,  # 振幅族, 原比例 1/3
            "rsi_6": 0.15,  # momentum
            "volume_decay_rate_5": 0.15,  # volume
            "overnight_ret_5": 0.10,  # overnight
        }
        result = WeightMethodBase._cap_family_weight(weights, list(weights), cap=0.30, logger=logger)
        # 振幅族降到 0.30 后, 2/3 → 0.20, 1/3 → 0.10
        assert result["amplitude_compression_5"] == pytest.approx(0.20, abs=1e-3)
        assert result["interaction_amp_compression"] == pytest.approx(0.10, abs=1e-3)
        assert sum(result.values()) == pytest.approx(1.0, abs=1e-6)

    def test_v2_39_realistic_scenario(self, logger):
        """v2.39 实测场景: 振幅族 38.75% → 应降到 30%"""
        weights = {
            "amplitude_compression_5": 0.25,
            "interaction_amp_compression": 0.1375,
            "volume_decay_rate_5": 0.10,
            "volume_ratio_5": 0.08,
            "price_position_5": 0.10,
            "bollinger_pb_20": 0.0433,
            "rsi_6": 0.05,
            "momentum_strength": 0.05,
            "overnight_ret_5": 0.05,
            "capital_flow_intensity_5": 0.0292,
            "tail_price_slope_5": 0.05,
        }
        original_sum = sum(weights.values())
        result = WeightMethodBase._cap_family_weight(weights, list(weights), cap=0.30, logger=logger)
        # sum 守恒
        assert sum(result.values()) == pytest.approx(original_sum, abs=1e-6)
        # 振幅族应降到 30%
        amp_total = result["amplitude_compression_5"] + result["interaction_amp_compression"]
        assert amp_total == pytest.approx(0.30, abs=1e-3)
        # 验证其他族增加
        assert result["volume_decay_rate_5"] > 0.10
        assert result["rsi_6"] > 0.05

    def test_empty_weights(self):
        """空权重直接返回"""
        result = WeightMethodBase._cap_family_weight({}, [], cap=0.30)
        assert result == {}

    def test_single_factor(self):
        """单因子直接返回"""
        weights = {"rsi_6": 1.0}
        result = WeightMethodBase._cap_family_weight(weights, ["rsi_6"], cap=0.30)
        assert result == weights


class TestCapWeightMatrixWithFamilies:
    """matrix 版 _cap_weight_matrix 族级 cap（用于 RollingICIR）"""

    def test_no_families_backward_compatible(self):
        """factor_families=None → 行为不变（向后兼容）

        cap=0.40, n=3 (3×0.40=1.20≥1.0 物理可行)
        """
        W = np.array([[0.50, 0.30, 0.20], [0.20, 0.50, 0.30]])
        result = WeightMethodBase._cap_weight_matrix(W, cap=0.40)
        # 单因子 cap=0.40 触发: 0.50 → ≤ 0.40
        assert (result <= 0.40 + 1e-9).all()
        # 每行 sum=1.0
        assert np.allclose(result.sum(axis=1), 1.0, atol=1e-6)

    def test_family_cap_with_groups(self):
        """4 因子, 前 2 个同族, 单因子 cap=0.50 + 族 cap=0.40

        n=4 因子, 单因子 0.50×4=2.0≥1.0 物理可行
        n_families=3, 族 cap 0.40×3=1.20≥1.0 物理可行
        """
        # 行 sum=1.0: [0.40, 0.30, 0.20, 0.10]
        # 族 0 (因子 0+1) = 0.70 超 0.40, 应降到 0.40
        W = np.array([[0.40, 0.30, 0.20, 0.10]])
        factor_families = [0, 0, 1, 2]
        result = WeightMethodBase._cap_weight_matrix(W, cap=0.50, factor_families=factor_families, family_cap=0.40)
        family_0_total = result[0, 0] + result[0, 1]
        assert family_0_total == pytest.approx(0.40, abs=1e-3)
        # 行 sum = 1
        assert result[0].sum() == pytest.approx(1.0, abs=1e-6)

    def test_family_cap_physical_infeasibility(self):
        """n_families × family_cap < 1.0 → 跳过族级 cap"""
        # 1 族, family_cap=0.30, 不可行
        W = np.array([[0.5, 0.5]])
        factor_families = [0, 0]
        result = WeightMethodBase._cap_weight_matrix(W, cap=0.50, factor_families=factor_families, family_cap=0.30)
        # 跳过族级 cap, 单因子 cap=0.50 也未触发, W 不变
        assert np.allclose(result, W, atol=1e-9)

    def test_multi_day_family_cap(self):
        """多日权重矩阵, 3 族 (3×0.40=1.20≥1.0 物理可行)"""
        # 3 因子, 3 族: [0, 1, 2]
        # 第 1 行: 族 0=0.30 合规, 族 1=0.50 超 0.40, 族 2=0.20
        # 第 2 行: 族 0=0.10 合规, 族 1=0.30 合规, 族 2=0.60 超 0.40
        W = np.array(
            [
                [0.30, 0.50, 0.20],  # 族 1 超限
                [0.10, 0.30, 0.60],  # 族 2 超限
            ]
        )
        factor_families = [0, 1, 2]
        result = WeightMethodBase._cap_weight_matrix(W, cap=0.50, factor_families=factor_families, family_cap=0.40)
        # 第 1 行: 族 1 应降到 0.40
        assert result[0, 1] == pytest.approx(0.40, abs=1e-3)
        # 族 0+2 增加吸收 excess
        assert result[0, 0] > 0.30
        # 第 2 行: 族 2 应降到 0.40
        assert result[1, 2] == pytest.approx(0.40, abs=1e-3)
        # 每行 sum=1
        assert np.allclose(result.sum(axis=1), 1.0, atol=1e-6)


class TestIntegrationWithSingleFactorCap:
    """族级 cap 与单因子 cap 协同测试"""

    def test_both_caps_active(self, logger):
        """单因子 cap=0.25 + 族 cap=0.30 同时生效 (≥4 族物理可行)"""
        # 输入: amplitude_compression 40% 超单因子 cap, 振幅族 0.50 超 0.30
        weights = {
            "amplitude_compression_5": 0.40,
            "interaction_amp_compression": 0.10,
            "rsi_6": 0.20,  # momentum
            "volume_decay_rate_5": 0.15,  # volume
            "overnight_ret_5": 0.10,  # overnight
            "tail_price_slope_5": 0.05,  # tail
        }
        # 第一步: 单因子 cap 25%
        capped_single = WeightMethodBase._cap_single_factor_weight(weights, cap=WEIGHT_CAP_DEFAULT, logger=logger)
        assert capped_single["amplitude_compression_5"] == pytest.approx(0.25, abs=1e-3)

        # 第二步: 族级 cap 30%
        capped_family = WeightMethodBase._cap_family_weight(
            capped_single, list(capped_single), cap=FAMILY_CAP_DEFAULT, logger=logger
        )
        # amplitude_family 应 ≤ 30%
        amp_total = capped_family["amplitude_compression_5"] + capped_family["interaction_amp_compression"]
        assert amp_total <= 0.30 + 1e-3
        # sum 守恒
        assert sum(capped_family.values()) == pytest.approx(1.0, abs=1e-6)
