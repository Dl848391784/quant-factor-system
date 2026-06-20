"""
维度感知因子去重测试用例

遵循 MODULE.md M17 规则：
- 同维度因子对, |corr|>0.7 → 合并去重（维度内冗余）
- 跨维度因子对, |corr|>0.9 → 合并去重（极端高相关兜底）
- 跨维度因子对, 0.7<|corr|≤0.9 → 保留（经济含义不同）

测试范围：
1. 同维度高相关因子被合并去重
2. 跨维度高相关因子(0.7-0.9)不被合并
3. 跨维度极端高相关(>0.9)被合并去重
4. 无分类时退化为原逻辑（向后兼容）
5. FACTOR_CATEGORIES 覆盖所有因子
6. _compute_dimension_coverage 输出正确

创建日期: 2026-06-20
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
            cross_dimension_threshold=0.9,
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
            cross_dimension_threshold=0.9,
        )

        assert len(groups) == 0
        assert len(pairs) == 0


class TestCrossDimensionPreserved:
    """跨维度高相关因子(0.7-0.9)不应被合并"""

    def test_cross_dimension_0_75_not_merged(self):
        """跨维度因子对 corr=0.75, 0.7 < 0.75 < 0.9 → 保留"""
        factors = ["rsi", "bollinger_pb"]
        valid = _make_valid_factors(factors, [0.30, 0.34])
        corr = _make_corr_matrix(factors, {("rsi", "bollinger_pb"): 0.75})
        categories = {"rsi": "momentum", "bollinger_pb": "price_position"}

        groups, pairs = identify_high_corr_groups(
            valid_factors=valid,
            corr_matrix=corr,
            threshold=0.7,
            factor_categories=categories,
            cross_dimension_threshold=0.9,
        )

        # 跨维度 0.75 < 0.9 → 不合并
        assert len(groups) == 0
        assert len(pairs) == 0

    def test_cross_dimension_0_89_not_merged(self):
        """跨维度因子对 corr=0.89 < 0.9 → 保留（边界值）"""
        factors = ["rsi", "bollinger_pb"]
        valid = _make_valid_factors(factors, [0.30, 0.34])
        corr = _make_corr_matrix(factors, {("rsi", "bollinger_pb"): 0.89})
        categories = {"rsi": "momentum", "bollinger_pb": "price_position"}

        groups, pairs = identify_high_corr_groups(
            valid_factors=valid,
            corr_matrix=corr,
            threshold=0.7,
            factor_categories=categories,
            cross_dimension_threshold=0.9,
        )

        assert len(groups) == 0
        assert len(pairs) == 0

    def test_cross_dimension_mixed_scenario(self):
        """混合场景：同维度合并 + 跨维度保留"""
        factors = ["rsi", "kdj_j", "bollinger_pb"]
        # rsi-kdj_j: 同维度(momentum), corr=0.8 > 0.7 → 合并
        # rsi-bollinger_pb: 跨维度, corr=0.75 < 0.9 → 保留
        # kdj_j-bollinger_pb: 跨维度, corr=0.72 < 0.9 → 保留
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
            cross_dimension_threshold=0.9,
        )

        # 只 rsi-kdj_j 合并（同维度），bollinger_pb 独立
        assert len(groups) == 1
        assert set(groups[0]) == {"rsi", "kdj_j"}
        # 只 1 个高相关对（同维度的）
        assert len(pairs) == 1


class TestCrossDimensionExtremeDedup:
    """跨维度极端高相关(>0.9)应被合并去重"""

    def test_cross_dimension_0_95_merged(self):
        """跨维度因子对 corr=0.95 > 0.9 → 合并（极端高相关兜底）"""
        factors = ["rsi", "bollinger_pb"]
        valid = _make_valid_factors(factors, [0.30, 0.34])
        corr = _make_corr_matrix(factors, {("rsi", "bollinger_pb"): 0.95})
        categories = {"rsi": "momentum", "bollinger_pb": "price_position"}

        groups, pairs = identify_high_corr_groups(
            valid_factors=valid,
            corr_matrix=corr,
            threshold=0.7,
            factor_categories=categories,
            cross_dimension_threshold=0.9,
        )

        # 跨维度 0.95 > 0.9 → 合并
        assert len(groups) == 1
        assert set(groups[0]) == {"rsi", "bollinger_pb"}
        assert len(pairs) == 1

    def test_cross_dimension_exactly_0_9_not_merged(self):
        """跨维度因子对 corr=0.9 = threshold → 不合并（严格大于）"""
        factors = ["rsi", "bollinger_pb"]
        valid = _make_valid_factors(factors, [0.30, 0.34])
        corr = _make_corr_matrix(factors, {("rsi", "bollinger_pb"): 0.9})
        categories = {"rsi": "momentum", "bollinger_pb": "price_position"}

        groups, pairs = identify_high_corr_groups(
            valid_factors=valid,
            corr_matrix=corr,
            threshold=0.7,
            factor_categories=categories,
            cross_dimension_threshold=0.9,
        )

        # 0.9 不 > 0.9 → 不合并
        assert len(groups) == 0
        assert len(pairs) == 0


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
            cross_dimension_threshold=0.9,
        )

        # 无分类 → 原始逻辑：0.75 > 0.7 → 合并
        assert len(groups) == 1
        assert set(groups[0]) == {"rsi", "bollinger_pb"}
        assert len(pairs) == 1

    def test_no_cross_dimension_threshold(self):
        """cross_dimension_threshold=None 时，跨维度不合并（保守）"""
        factors = ["rsi", "bollinger_pb"]
        valid = _make_valid_factors(factors, [0.30, 0.34])
        corr = _make_corr_matrix(factors, {("rsi", "bollinger_pb"): 0.95})
        categories = {"rsi": "momentum", "bollinger_pb": "price_position"}

        groups, pairs = identify_high_corr_groups(
            valid_factors=valid,
            corr_matrix=corr,
            threshold=0.7,
            factor_categories=categories,
            cross_dimension_threshold=None,  # 不设跨维度阈值
        )

        # cross_dimension_threshold=None → 跨维度永远不合并
        assert len(groups) == 0
        assert len(pairs) == 0


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
        assert len(FACTOR_CATEGORIES) == 34

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

    def test_default_thresholds_has_cross_dimension(self):
        """DEFAULT_THRESHOLDS 包含 cross_dimension_corr_threshold"""
        assert "cross_dimension_corr_threshold" in DEFAULT_THRESHOLDS
        assert DEFAULT_THRESHOLDS["cross_dimension_corr_threshold"] == 0.9
