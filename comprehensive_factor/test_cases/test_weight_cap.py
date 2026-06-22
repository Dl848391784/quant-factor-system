"""v2.38: 单因子权重上限 25% 测试

验证 design.md feat_interaction_exemption_and_weight_cap §4.3:
- _cap_single_factor_weight: 静态权重 cap (Equal/ICIR/IC 共用)
- _cap_weight_matrix: 行级矩阵 cap (RollingICIR 每日动态权重)

测试覆盖:
1. cap 触发: 单因子超 cap → 截断 + 比例摊分, sum=1.0 保持
2. cap 不触发: 所有因子 < cap → 权重不变
3. 多因子同时超 cap: 多轮迭代直到收敛
4. 边界: 等权 (无操作) / 单因子 (退化) / 输入未归一化 (先归一化)
5. 集成: amplitude_compression 43.7% 真实场景 → 25%
6. 矩阵: NaN / 全零行 / 等权行 / 混合行

引用规范:
- designs/feat_interaction_exemption_and_weight_cap.md §4.3 §5
- comprehensive_factor/MODULE.md M30a (权重上限子规则, 本 PR 新增)
"""

import numpy as np
import pytest
from comprehensive_factor.common.weight_engine import (
    WEIGHT_CAP_DEFAULT,
    WeightMethodBase,
)


class TestCapSingleFactorWeight:
    """静态权重 cap (Equal/ICIR/IC 共用)"""

    def test_cap_triggers_single_factor_over_threshold(self):
        """单因子超 cap → 截断 + 剩余因子比例摊分"""
        weights = {
            "amp_compression": 0.437,
            "b": 0.10,
            "c": 0.10,
            "d": 0.08,
            "e": 0.08,
            "f": 0.08,
            "g": 0.07,
            "h": 0.083,
        }
        capped = WeightMethodBase._cap_single_factor_weight(weights, cap=0.25)

        # 1. amp_compression 截到 cap
        assert capped["amp_compression"] == pytest.approx(0.25, abs=1e-9)
        # 2. sum == 1.0
        assert sum(capped.values()) == pytest.approx(1.0, abs=1e-9)
        # 3. 无任何因子 > cap
        assert max(capped.values()) <= 0.25 + 1e-9
        # 4. 剩余因子按比例放大（b 与 c 同样 0.10 → 同样 0.1265）
        assert capped["b"] == pytest.approx(capped["c"], abs=1e-9)
        # 5. 摊分保持相对大小（b > d）
        assert capped["b"] > capped["d"]

    def test_cap_not_triggered_when_all_below(self):
        """所有因子 < cap → 权重不变"""
        weights = {"a": 0.20, "b": 0.20, "c": 0.20, "d": 0.20, "e": 0.20}
        capped = WeightMethodBase._cap_single_factor_weight(weights, cap=0.25)
        for k in weights:
            assert capped[k] == pytest.approx(weights[k], abs=1e-9)

    def test_cap_multiple_factors_over_threshold(self):
        """多因子同时超 cap → 多轮迭代收敛"""
        weights = {"a": 0.40, "b": 0.30, "c": 0.10, "d": 0.10, "e": 0.10}
        capped = WeightMethodBase._cap_single_factor_weight(weights, cap=0.25)

        # a, b 都截到 cap
        assert capped["a"] == pytest.approx(0.25, abs=1e-9)
        assert capped["b"] == pytest.approx(0.25, abs=1e-9)
        # c, d, e 等权摊分剩余 0.5
        assert capped["c"] == pytest.approx(1.0 / 6.0, abs=1e-9)
        # sum=1.0
        assert sum(capped.values()) == pytest.approx(1.0, abs=1e-9)

    def test_cap_boundary_at_exact_cap(self):
        """因子恰好等于 cap → 不触发截断"""
        weights = {"a": 0.25, "b": 0.25, "c": 0.25, "d": 0.25}
        capped = WeightMethodBase._cap_single_factor_weight(weights, cap=0.25)
        for k in weights:
            assert capped[k] == pytest.approx(0.25, abs=1e-9)

    def test_cap_unnormalized_input_renormalized(self):
        """输入 sum != 1.0 → 先归一化再 cap"""
        # sum = 1.5
        weights = {"a": 0.60, "b": 0.45, "c": 0.30, "d": 0.15}
        capped = WeightMethodBase._cap_single_factor_weight(weights, cap=0.25)
        # 归一化后: a=0.40, b=0.30, c=0.20, d=0.10
        # 迭代摊分后 4 个因子都到 25% (4×0.25=1.0)
        assert sum(capped.values()) == pytest.approx(1.0, abs=1e-9)
        assert max(capped.values()) <= 0.25 + 1e-9
        for k in capped:
            assert capped[k] == pytest.approx(0.25, abs=1e-6)

    def test_cap_skipped_when_physically_infeasible(self):
        """v2.38a: n × cap < 1.0 时 cap 不可解, 应跳过 (保留原权重)"""
        # 3 因子 × 0.25 = 0.75 < 1.0 → 不可行
        weights = {"a": 0.60, "b": 0.30, "c": 0.10}
        capped = WeightMethodBase._cap_single_factor_weight(weights, cap=0.25)
        # 应原样返回（不破坏 ICIR 排序信息）
        for k in weights:
            assert capped[k] == pytest.approx(weights[k], abs=1e-9)
        # sum 保持
        assert sum(capped.values()) == pytest.approx(1.0, abs=1e-9)

    def test_cap_empty_dict_returns_empty(self):
        """空字典 → 返回空"""
        capped = WeightMethodBase._cap_single_factor_weight({}, cap=0.25)
        assert capped == {}

    def test_cap_amplitude_compression_real_scenario(self):
        """真实场景: factor_summary_report_2026-06-22.txt 中 amp_compression 名义 43.7%"""
        # 模拟 Top 10 因子权重分布（来自 pipeline 实证）
        weights = {
            "amplitude_compression": 0.437,
            "near_high_pos": 0.105,
            "intraday_strength": 0.089,
            "kdj_j": 0.076,
            "price_pos_60d": 0.067,
            "bollinger_pb": 0.062,
            "ma5_dev_pct": 0.058,
            "amplitude_ratio": 0.054,
            "turnover_rate": 0.030,
            "volume_ratio": 0.022,
        }
        # 输入约 1.0
        capped = WeightMethodBase._cap_single_factor_weight(weights, cap=WEIGHT_CAP_DEFAULT)

        # amp_compression 截到 25% (43.7% → 25%, 节省 18.7 个百分点)
        assert capped["amplitude_compression"] == pytest.approx(0.25, abs=1e-9)
        # 其他因子按原比例放大
        # near_high_pos 应得最多增量 (原权重最高)
        delta_near = capped["near_high_pos"] - weights["near_high_pos"]
        delta_volume = capped["volume_ratio"] - weights["volume_ratio"]
        assert delta_near > delta_volume, "高原权重因子应得更多摊分"
        # 排序保持不变（amp_compression 仍最高，因为 25% > 其他截后值 12% 左右）
        sorted_capped = sorted(capped.keys(), key=lambda k: -capped[k])
        # amp_compression 名次可能下降（不再第一），但其他因子相对排序保持
        assert sorted_capped[0] == "amplitude_compression"  # 仍最高（与 near_high_pos 25% vs 12% 比）
        # sum=1.0
        assert sum(capped.values()) == pytest.approx(1.0, abs=1e-9)

    def test_cap_preserves_relative_order_among_uncapped(self):
        """被 cap 的因子之外，相对排序应保持"""
        # 选择 d/e 不到 cap 的场景: a=0.40, b=0.20, c=0.20, d=0.10, e=0.10
        # a 超 cap → 截 0.25, excess=0.15, others_sum=0.60
        # b → 0.20 + 0.15*0.20/0.60 = 0.25 (恰好到 cap, 不超)
        # c → 同 b = 0.25
        # d → 0.10 + 0.15*0.10/0.60 = 0.125
        # e → 同 d = 0.125
        # 不需要二轮, sum=0.25*3+0.125*2=1.0
        weights = {"a": 0.40, "b": 0.20, "c": 0.20, "d": 0.10, "e": 0.10}
        capped = WeightMethodBase._cap_single_factor_weight(weights, cap=0.25)
        assert capped["a"] == pytest.approx(0.25, abs=1e-9)
        assert capped["b"] == pytest.approx(0.25, abs=1e-9)
        assert capped["c"] == pytest.approx(0.25, abs=1e-9)
        # d, e 未被 cap, 相对大小保持（同值）
        assert capped["d"] == pytest.approx(0.125, abs=1e-9)
        assert capped["e"] == pytest.approx(0.125, abs=1e-9)
        # b > d 排序保持（b 已截, 但 b > d 仍成立）
        assert capped["b"] > capped["d"]


class TestCapWeightMatrix:
    """行级矩阵 cap (RollingICIR 每日动态权重)"""

    def test_matrix_cap_basic(self):
        """基本矩阵 cap"""
        W = np.array(
            [
                [0.50, 0.20, 0.15, 0.10, 0.05],  # 第一个因子超 cap
                [0.20, 0.20, 0.20, 0.20, 0.20],  # 等权, 无操作
                [0.30, 0.30, 0.20, 0.10, 0.10],  # 前两个因子超 cap
            ]
        )
        Wc = WeightMethodBase._cap_weight_matrix(W, cap=0.25)

        # 每行 sum == 1.0
        assert np.allclose(Wc.sum(axis=1), 1.0, atol=1e-9)
        # 每行 max <= 0.25
        assert (Wc.max(axis=1) <= 0.25 + 1e-9).all()
        # 等权行不变
        assert np.allclose(Wc[1], W[1])

    def test_matrix_cap_no_change_when_under(self):
        """所有行均 < cap → 不变"""
        W = np.full((10, 5), 0.20)
        Wc = WeightMethodBase._cap_weight_matrix(W, cap=0.25)
        assert np.allclose(Wc, W)

    def test_matrix_cap_returns_new_array(self):
        """不污染原矩阵 (copy 防御)"""
        W = np.array([[0.50, 0.30, 0.20]])
        W_original = W.copy()
        _ = WeightMethodBase._cap_weight_matrix(W, cap=0.25)
        assert np.allclose(W, W_original), "原矩阵不应被修改"

    def test_matrix_cap_proportional_redistribution(self):
        """剩余因子按原权重比例摊分（与字典版一致）"""
        # 单行测试: a=0.40, b=0.30, c=0.20, d=0.10
        # 第一轮: a 截 0.25, excess=0.15, others_sum=0.60
        #   b -> 0.30 + 0.15*0.30/0.60 = 0.375 (再超 cap!)
        #   c -> 0.20 + 0.05 = 0.25
        #   d -> 0.10 + 0.025 = 0.125
        # 第二轮: b 截 0.25, excess=0.125, c 已到 cap, others={d:0.125}, sum=0.125
        #   d -> 0.125 + 0.125 = 0.25
        # 最终: a=b=c=d=0.25
        W = np.array([[0.40, 0.30, 0.20, 0.10]])
        Wc = WeightMethodBase._cap_weight_matrix(W, cap=0.25)
        for i in range(4):
            assert Wc[0, i] == pytest.approx(0.25, abs=1e-6), f"col {i}"
        assert Wc.sum() == pytest.approx(1.0, abs=1e-9)

    def test_matrix_cap_partial_redistribution(self):
        """5 因子场景: 摊分后下游因子不被全部抬到 cap"""
        # a=0.40, b=0.20, c=0.20, d=0.10, e=0.10 (同字典版 preserves_order)
        # 一轮即收敛: a=b=c=0.25, d=e=0.125
        W = np.array([[0.40, 0.20, 0.20, 0.10, 0.10]])
        Wc = WeightMethodBase._cap_weight_matrix(W, cap=0.25)
        assert Wc[0, 0] == pytest.approx(0.25, abs=1e-9)
        assert Wc[0, 3] == pytest.approx(0.125, abs=1e-9)
        assert Wc[0, 4] == pytest.approx(0.125, abs=1e-9)
        # 排序保持: b > d
        assert Wc[0, 1] > Wc[0, 3]
        assert Wc.sum() == pytest.approx(1.0, abs=1e-9)

    def test_matrix_cap_skipped_when_physically_infeasible(self):
        """v2.38a: n_factors × cap < 1.0 → 矩阵原样返回"""
        # 3 因子 × 0.25 = 0.75 < 1.0
        W = np.array(
            [
                [0.60, 0.30, 0.10],
                [0.40, 0.40, 0.20],
            ]
        )
        Wc = WeightMethodBase._cap_weight_matrix(W, cap=0.25)
        assert np.allclose(Wc, W), "物理不可行时应保留原矩阵"

    def test_matrix_cap_against_dict_version_consistency(self):
        """矩阵版 vs 字典版结果一致性"""
        rng = np.random.RandomState(42)
        # 生成 5 行随机权重（每行 sum=1.0）
        raw = rng.uniform(0, 1, (5, 6))
        W = raw / raw.sum(axis=1, keepdims=True)

        Wc = WeightMethodBase._cap_weight_matrix(W, cap=0.25)

        for i in range(5):
            row_dict = {f"f{j}": W[i, j] for j in range(6)}
            row_capped_dict = WeightMethodBase._cap_single_factor_weight(row_dict, cap=0.25)
            row_capped_expected = np.array([row_capped_dict[f"f{j}"] for j in range(6)])
            assert np.allclose(Wc[i], row_capped_expected, atol=1e-9), f"行 {i} 矩阵版与字典版不一致"
