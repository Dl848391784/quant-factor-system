"""
维度感知因子去重测试用例

遵循 MODULE.md M57 规则：
- 同维度因子对, |corr|>0.7 → 合并去重（维度内冗余）
- 跨维度因子对 → 不合并（经济含义不同，统计高相关 ≠ 经济冗余）

测试范围：
1. 同维度高相关因子被合并去重
2. 跨维度高相关因子(包括 >0.9)不被合并
3. 无分类时退化为原逻辑（向后兼容）
4. FACTOR_CATEGORIES 覆盖所有因子
5. _compute_dimension_coverage 输出正确

创建日期: 2026-06-20
更新日期: 2026-06-20 (v2: 移除跨维度兜底合并)
"""

import logging

import pandas as pd
import pytest
from comprehensive_factor.common.factor_selector import (
    DEFAULT_THRESHOLDS,
    _compute_dimension_coverage,
    identify_high_corr_groups,
)
from factor_definitions import (
    CATEGORY_DIMENSIONS,
    FACTOR_CATEGORIES,
    FACTOR_NAME_TO_COL_MAP,
)


# ============================================================================
# 辅助函数
# ============================================================================


def _make_valid_factors(names: list[str], icir_values: list[float]) -> dict[str, dict]:
    """构建 valid_factors 字典

    Args:
        names: 因子名列表
        icir_values: 对应的 ICIR 值列表

    Returns:
        {name: {"ic_metrics": {"icir": value}}}
    """
    return {name: {"ic_metrics": {"icir": icir}} for name, icir in zip(names, icir_values, strict=True)}


def _make_corr_matrix(names: list[str], pairs: dict[tuple[str, str], float]) -> pd.DataFrame:
    """构建相关性矩阵

    Args:
        names: 因子名列表（矩阵索引）
        pairs: {(name_a, name_b): corr_value}

    Returns:
        对角线为 1.0 的相关性矩阵
    """
    n = len(names)
    data = pd.DataFrame(0.0, index=names, columns=names)
    for i in range(n):
        data.loc[names[i], names[i]] = 1.0
    for (a, b), corr in pairs.items():
        data.loc[a, b] = corr
        data.loc[b, a] = corr
    return data


# ============================================================================
# 测试用例
# ============================================================================


class TestSameDimensionDedup:
    """同维度高相关因子应被合并去重"""

    def test_same_dimension_merged(self):
        """同维度(momentum)因子对 corr=0.8 > 0.7 → 合并"""
        factors = ["rsi", "kdj_j"]
        valid = _make_valid_factors(factors, [0.30, 0.25])
        corr = _make_corr_matrix(factors, {("rsi", "kdj_j"): 0.8})
        categories = {"rsi": "momentum", "kdj_j": "momentum"}

        groups, pairs = identify_high_corr_groups(
            valid_factors=valid,
            corr_matrix=corr,
            threshold=0.7,
            factor_categories=categories,
        )

        # 应产生 1 个高相关组（合并）
        assert len(groups) == 1
        assert set(groups[0]) == {"rsi", "kdj_j"}
        assert len(pairs) == 1
        assert pairs[0][0] in factors and pairs[0][1] in factors

    def test_same_dimension_below_threshold_not_merged(self):
        """同维度因子对 corr=0.6 < 0.7 → 不合并"""
        factors = ["rsi", "kdj_j"]
        valid = _make_valid_factors(factors, [0.30, 0.25])
        corr = _make_corr_matrix(factors, {("rsi", "kdj_j"): 0.6})
        categories = {"rsi": "momentum", "kdj_j": "momentum"}

        groups, pairs = identify_high_corr_groups(
            valid_factors=valid,
            corr_matrix=corr,
            threshold=0.7,
            factor_categories=categories,
        )

        assert len(groups) == 0
        assert len(pairs) == 0


class TestCrossDimensionPreserved:
    """跨维度高相关因子不应被合并（无论相关性多高）"""

    def test_cross_dimension_0_75_not_merged(self):
        """跨维度因子对 corr=0.75 > 0.7 → 保留（维度不同）"""
        factors = ["rsi", "bollinger_pb"]
        valid = _make_valid_factors(factors, [0.30, 0.34])
        corr = _make_corr_matrix(factors, {("rsi", "bollinger_pb"): 0.75})
        categories = {"rsi": "momentum", "bollinger_pb": "price_position"}

        groups, pairs = identify_high_corr_groups(
            valid_factors=valid,
            corr_matrix=corr,
            threshold=0.7,
            factor_categories=categories,
        )

        # 跨维度 → 不合并
        assert len(groups) == 0
        assert len(pairs) == 0

    def test_cross_dimension_0_89_not_merged(self):
        """跨维度因子对 corr=0.89 → 保留（维度不同）"""
        factors = ["rsi", "bollinger_pb"]
        valid = _make_valid_factors(factors, [0.30, 0.34])
        corr = _make_corr_matrix(factors, {("rsi", "bollinger_pb"): 0.89})
        categories = {"rsi": "momentum", "bollinger_pb": "price_position"}

        groups, pairs = identify_high_corr_groups(
            valid_factors=valid,
            corr_matrix=corr,
            threshold=0.7,
            factor_categories=categories,
        )

        assert len(groups) == 0
        assert len(pairs) == 0

    def test_cross_dimension_0_95_not_merged(self):
        """跨维度因子对 corr=0.95 > 0.9 → 仍保留（v2.7: 跨维度一律不合并）"""
        factors = ["rsi", "bollinger_pb"]
        valid = _make_valid_factors(factors, [0.30, 0.34])
        corr = _make_corr_matrix(factors, {("rsi", "bollinger_pb"): 0.95})
        categories = {"rsi": "momentum", "bollinger_pb": "price_position"}

        groups, pairs = identify_high_corr_groups(
            valid_factors=valid,
            corr_matrix=corr,
            threshold=0.7,
            factor_categories=categories,
        )

        # v2.7: 跨维度不合并，即使 corr=0.95
        assert len(groups) == 0
        assert len(pairs) == 0

    def test_cross_dimension_mixed_scenario(self):
        """混合场景：同维度合并 + 跨维度保留"""
        factors = ["rsi", "kdj_j", "bollinger_pb"]
        # rsi-kdj_j: 同维度(momentum), corr=0.8 > 0.7 → 合并
        # rsi-bollinger_pb: 跨维度, corr=0.75 → 保留
        # kdj_j-bollinger_pb: 跨维度, corr=0.72 → 保留
        valid = _make_valid_factors(factors, [0.30, 0.25, 0.34])
        corr = _make_corr_matrix(
            factors,
            {("rsi", "kdj_j"): 0.8, ("rsi", "bollinger_pb"): 0.75, ("kdj_j", "bollinger_pb"): 0.72},
        )
        categories = {
            "rsi": "momentum",
            "kdj_j": "momentum",
            "bollinger_pb": "price_position",
        }

        groups, pairs = identify_high_corr_groups(
            valid_factors=valid,
            corr_matrix=corr,
            threshold=0.7,
            factor_categories=categories,
        )

        # 只 rsi-kdj_j 合并（同维度），bollinger_pb 独立
        assert len(groups) == 1
        assert set(groups[0]) == {"rsi", "kdj_j"}
        # 只 1 个高相关对（同维度的）
        assert len(pairs) == 1

    def test_cross_dimension_no_bridge_contamination(self):
        """v2.7 回归测试：跨维度高相关不再通过桥接消灭整个维度

        场景：rsi[momentum]↔bollinger_pb[price_position] corr=0.92,
              return_3d[momentum]↔rsi[momentum] corr=0.85
        v1.8(旧): rsi-bollinger_pb >0.9 合并 → return_3d 通过 rsi 被拉入同组 → 被淘汰
        v2.7(新): 跨维度不合并 → rsi/return_3d 同维度合并, bollinger_pb 独立
        """
        factors = ["rsi", "bollinger_pb", "return_3d"]
        valid = _make_valid_factors(factors, [0.32, 0.34, 0.28])
        corr = _make_corr_matrix(
            factors,
            {("rsi", "bollinger_pb"): 0.92, ("rsi", "return_3d"): 0.85, ("return_3d", "bollinger_pb"): 0.80},
        )
        categories = {
            "rsi": "momentum",
            "bollinger_pb": "price_position",
            "return_3d": "momentum",
        }

        groups, pairs = identify_high_corr_groups(
            valid_factors=valid,
            corr_matrix=corr,
            threshold=0.7,
            factor_categories=categories,
        )

        # rsi-return_3d 同维度合并；bollinger_pb 跨维度独立
        assert len(groups) == 1
        assert set(groups[0]) == {"rsi", "return_3d"}
        assert len(pairs) == 1  # 只有同维度的 1 对


class TestNoCategoriesBackwardCompat:
    """无分类信息时退化为原始逻辑（向后兼容）"""

    def test_no_categories_all_pairs_merged(self):
        """factor_categories=None 时，所有 >0.7 的因子对都合并"""
        factors = ["rsi", "bollinger_pb"]
        valid = _make_valid_factors(factors, [0.30, 0.34])
        corr = _make_corr_matrix(factors, {("rsi", "bollinger_pb"): 0.75})

        groups, pairs = identify_high_corr_groups(
            valid_factors=valid,
            corr_matrix=corr,
            threshold=0.7,
            factor_categories=None,  # 无分类
        )

        # 无分类 → 原始逻辑：0.75 > 0.7 → 合并
        assert len(groups) == 1
        assert set(groups[0]) == {"rsi", "bollinger_pb"}
        assert len(pairs) == 1


class TestCategoriesComplete:
    """FACTOR_CATEGORIES 覆盖所有因子"""

    def test_categories_match_factor_map(self):
        """FACTOR_CATEGORIES 的 key 与 FACTOR_NAME_TO_COL_MAP 完全一致"""
        cat_keys = set(FACTOR_CATEGORIES.keys())
        map_keys = set(FACTOR_NAME_TO_COL_MAP.keys())
        assert cat_keys == map_keys, (
            f"Missing in CATEGORIES: {map_keys - cat_keys}, Extra in CATEGORIES: {cat_keys - map_keys}"
        )

    def test_all_categories_in_dimensions(self):
        """所有分类值都在 CATEGORY_DIMENSIONS 中"""
        cats_used = set(FACTOR_CATEGORIES.values())
        dims = set(CATEGORY_DIMENSIONS)
        assert cats_used == dims, f"Missing in DIMENSIONS: {cats_used - dims}, Extra in DIMENSIONS: {dims - cats_used}"

    def test_categories_count(self):
        """FACTOR_CATEGORIES 有 34 个因子"""
        assert len(FACTOR_CATEGORIES) == 39  # v2.35: P5 新增5个因子 34→39

    def test_dimensions_count(self):
        """CATEGORY_DIMENSIONS 有 8 个维度"""
        assert len(CATEGORY_DIMENSIONS) == 8


class TestDimensionCoverage:
    """_compute_dimension_coverage 输出正确"""

    def test_all_dimensions_covered(self):
        """所有维度都有选中因子"""
        valid = {
            "rsi": {"ic_metrics": {"icir": 0.3}},
            "bollinger_pb": {"ic_metrics": {"icir": 0.34}},
        }
        selected = ["rsi", "bollinger_pb"]

        result = _compute_dimension_coverage(selected, valid)

        assert "momentum" in result["covered"]
        assert "price_position" in result["covered"]
        assert len(result["missing"]) == 0
        assert result["selected_by_dimension"]["momentum"] == ["rsi"]
        assert result["selected_by_dimension"]["price_position"] == ["bollinger_pb"]

    def test_missing_dimension(self):
        """一个维度缺失"""
        valid = {
            "rsi": {"ic_metrics": {"icir": 0.3}},
            "amplitude": {"ic_metrics": {"icir": 0.2}},
        }
        selected = ["rsi"]  # amplitude 未选中

        result = _compute_dimension_coverage(selected, valid)

        assert "momentum" in result["covered"]
        assert "volatility" in result["missing"]
        assert "amplitude" not in result["selected_by_dimension"]

    def test_empty_selected(self):
        """无选中因子"""
        valid = {"rsi": {"ic_metrics": {"icir": 0.3}}}
        selected = []

        result = _compute_dimension_coverage(selected, valid)

        assert len(result["covered"]) == 0
        assert "momentum" in result["missing"]


class TestDefaultThresholds:
    """DEFAULT_THRESHOLDS 配置正确"""

    def test_high_corr_threshold(self):
        """DEFAULT_THRESHOLDS 包含 high_corr_threshold=0.7"""
        assert "high_corr_threshold" in DEFAULT_THRESHOLDS
        assert DEFAULT_THRESHOLDS["high_corr_threshold"] == 0.7

    def test_no_cross_dimension_threshold(self):
        """v2.7: DEFAULT_THRESHOLDS 不再包含 cross_dimension_corr_threshold"""
        assert "cross_dimension_corr_threshold" not in DEFAULT_THRESHOLDS


class TestTransitiveGroupCorrDisplay:
    """v2.9: 传递性归组时 corr 从 corr_matrix 补全，不显示为空"""

    def test_transitive_corr_from_matrix(self):
        """传递性归组因子对的 corr 从 corr_matrix 补全，不显示为空。

        场景: A-B 0.80(直接), B-C 0.75(直接), A-C 0.50(间接)
        Union-Find 将 A-B-C 归为同组，best=A(ICIR最高)
        C 被淘汰时 corr_lookup 无 (C,A) 配对 → 从 corr_matrix 补全 0.50
        """
        from comprehensive_factor.common.factor_selector import select_best_from_groups

        valid_factors = {
            "factor_a": {"ic_metrics": {"icir": 0.30}},
            "factor_b": {"ic_metrics": {"icir": 0.20}},
            "factor_c": {"ic_metrics": {"icir": 0.10}},
        }

        high_corr_pairs = [
            ("factor_a", "factor_b", 0.80),
            ("factor_b", "factor_c", 0.75),
        ]

        corr_matrix = pd.DataFrame(
            {
                "factor_a": [1.0, 0.80, 0.50],
                "factor_b": [0.80, 1.0, 0.75],
                "factor_c": [0.50, 0.75, 1.0],
            },
            index=["factor_a", "factor_b", "factor_c"],
        )

        groups = [["factor_a", "factor_b", "factor_c"]]

        selected, dropped = select_best_from_groups(
            high_corr_groups=groups,
            high_corr_pairs=high_corr_pairs,
            valid_factors=valid_factors,
            corr_matrix=corr_matrix,
        )

        assert "factor_a" in selected
        assert "factor_b" in dropped
        assert "corr=0.80" in dropped["factor_b"]
        # factor_c 间接归组，corr 从 corr_matrix 补全
        assert "factor_c" in dropped
        assert "corr=0.50" in dropped["factor_c"]
        assert "传递性归组" not in dropped["factor_c"]

    def test_transitive_corr_no_matrix_fallback(self):
        """corr_matrix 为 None 时，间接归组因子对显示'传递性归组'。"""
        from comprehensive_factor.common.factor_selector import select_best_from_groups

        valid_factors = {
            "factor_a": {"ic_metrics": {"icir": 0.30}},
            "factor_b": {"ic_metrics": {"icir": 0.20}},
            "factor_c": {"ic_metrics": {"icir": 0.10}},
        }

        high_corr_pairs = [
            ("factor_a", "factor_b", 0.80),
            ("factor_b", "factor_c", 0.75),
        ]

        groups = [["factor_a", "factor_b", "factor_c"]]

        selected, dropped = select_best_from_groups(
            high_corr_groups=groups,
            high_corr_pairs=high_corr_pairs,
            valid_factors=valid_factors,
            corr_matrix=None,
        )

        assert "factor_c" in dropped
        assert "传递性归组" in dropped["factor_c"]
