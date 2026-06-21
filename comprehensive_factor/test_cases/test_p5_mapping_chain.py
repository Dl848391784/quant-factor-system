"""P5-Step2: 新因子映射链完整性测试

验证 design.md P5-Step2（批次6）：
5个新因子在整条映射链中不丢失、维度归属正确。

映射链:
  factor_definitions.FACTOR_CATEGORIES
    → factor_selector (筛选时维度分组)
    → composite_runner (传给 WeightEngine)
    → stock_selector (传给 WeightEngine)
    → weight_engine (_apply_dimension_weights_static 维度再分配)

遵循 designs/strategy_systemic_overhaul.md §2.5（批次6）。
"""

import pytest
from factor_definitions import (
    FACTOR_CATEGORIES,
    FACTOR_COL_TO_NAME_MAP,
    FACTOR_DEFINITIONS,
    FACTOR_NAME_TO_COL_MAP,
)


# 5个 P5 新增因子
NEW_FACTORS = [
    "rsi_slope_3d",
    "ma5_slope",
    "lower_shadow_ratio",
    "volume_shrink_rate",
    "price_volume_divergence",
]

# 预期维度归属
EXPECTED_DIMENSIONS = {
    "rsi_slope_3d": "momentum",
    "ma5_slope": "momentum",
    "lower_shadow_ratio": "price_position",
    "volume_shrink_rate": "volume",
    "price_volume_divergence": "volume",
}


class TestNewFactorDefinitions:
    """新因子在 factor_definitions 四张表中注册完整"""

    def test_all_in_factor_definitions(self):
        """5个新因子都在 FACTOR_DEFINITIONS 中有描述"""
        for f in NEW_FACTORS:
            assert f in FACTOR_DEFINITIONS, f"{f} 不在 FACTOR_DEFINITIONS"

    def test_all_in_name_to_col_map(self):
        """5个新因子都在 FACTOR_NAME_TO_COL_MAP 中有列名映射"""
        for f in NEW_FACTORS:
            assert f in FACTOR_NAME_TO_COL_MAP, f"{f} 不在 FACTOR_NAME_TO_COL_MAP"

    def test_all_in_col_to_name_map(self):
        """5个新因子的列名都在 FACTOR_COL_TO_NAME_MAP 中有反向映射"""
        for f in NEW_FACTORS:
            col = FACTOR_NAME_TO_COL_MAP[f]
            assert col in FACTOR_COL_TO_NAME_MAP, f"列名 {col} 不在 FACTOR_COL_TO_NAME_MAP"
            assert FACTOR_COL_TO_NAME_MAP[col] == f, f"反向映射不一致: {col} → {FACTOR_COL_TO_NAME_MAP[col]} (期望 {f})"

    def test_all_in_factor_categories(self):
        """5个新因子都在 FACTOR_CATEGORIES 中有维度归属"""
        for f in NEW_FACTORS:
            assert f in FACTOR_CATEGORIES, f"{f} 不在 FACTOR_CATEGORIES"

    def test_dimensions_correct(self):
        """5个新因子维度归属正确"""
        for f, expected_dim in EXPECTED_DIMENSIONS.items():
            actual_dim = FACTOR_CATEGORIES[f]
            assert actual_dim == expected_dim, f"{f} 维度={actual_dim}, 期望={expected_dim}"

    def test_name_equals_col(self):
        """5个新因子列名=因子名（无后缀）"""
        for f in NEW_FACTORS:
            assert FACTOR_NAME_TO_COL_MAP[f] == f, f"{f} 列名={FACTOR_NAME_TO_COL_MAP[f]} (期望={f})"


class TestMappingChainIntegrity:
    """映射链完整性：factor_selector / weight_engine / composite_runner / stock_selector
    全部从 factor_definitions 导入，不丢失新因子"""

    def test_factor_selector_imports_categories(self):
        """factor_selector 从 factor_definitions 导入 FACTOR_CATEGORIES"""
        from comprehensive_factor.common import factor_selector

        assert hasattr(factor_selector, "FACTOR_CATEGORIES"), "factor_selector 未导入 FACTOR_CATEGORIES"
        for f in NEW_FACTORS:
            assert f in factor_selector.FACTOR_CATEGORIES, f"{f} 未通过 factor_selector.FACTOR_CATEGORIES 传播"

    def test_weight_engine_has_name_to_col_map(self):
        """weight_engine WeightMethodBase.FACTOR_NAME_TO_COL_MAP 包含新因子"""
        from comprehensive_factor.common.weight_engine import WeightMethodBase

        for f in NEW_FACTORS:
            assert f in WeightMethodBase.FACTOR_NAME_TO_COL_MAP, (
                f"{f} 未通过 WeightMethodBase.FACTOR_NAME_TO_COL_MAP 传播"
            )

    def test_composite_runner_imports_categories(self):
        """composite_runner 从 factor_definitions 导入 FACTOR_CATEGORIES"""
        from comprehensive_factor.common import composite_runner

        assert hasattr(composite_runner, "FACTOR_CATEGORIES"), "composite_runner 未导入 FACTOR_CATEGORIES"
        for f in NEW_FACTORS:
            assert f in composite_runner.FACTOR_CATEGORIES, f"{f} 未通过 composite_runner.FACTOR_CATEGORIES 传播"

    def test_stock_selector_imports_categories(self):
        """stock_selector 从 factor_definitions 导入 FACTOR_CATEGORIES"""
        from comprehensive_factor.stock_selector import FACTOR_CATEGORIES as ss_categories

        for f in NEW_FACTORS:
            assert f in ss_categories, f"{f} 未通过 stock_selector.FACTOR_CATEGORIES 传播"

    def test_no_orphan_factors(self):
        """无孤儿因子：FACTOR_CATEGORIES 中的因子都在 FACTOR_NAME_TO_COL_MAP 中"""
        for f in FACTOR_CATEGORIES:
            assert f in FACTOR_NAME_TO_COL_MAP, f"{f} 在 FACTOR_CATEGORIES 但不在 FACTOR_NAME_TO_COL_MAP（孤儿因子）"


class TestDimensionWeightAllocation:
    """维度权重再分配：新因子加入后维度组正确"""

    def test_new_factors_belong_to_3_existing_dimensions(self):
        """5个新因子分属3个已有维度（momentum/price_position/volume），无新维度"""
        new_dims = {FACTOR_CATEGORIES[f] for f in NEW_FACTORS}
        assert new_dims == {"momentum", "price_position", "volume"}, (
            f"新因子维度集合={new_dims}, 期望={{momentum, price_position, volume}}"
        )

    def test_momentum_dimension_has_2_new_factors(self):
        """momentum 维度新增2个因子（rsi_slope_3d + ma5_slope）"""
        momentum_new = [f for f in NEW_FACTORS if FACTOR_CATEGORIES[f] == "momentum"]
        assert len(momentum_new) == 2
        assert set(momentum_new) == {"rsi_slope_3d", "ma5_slope"}

    def test_volume_dimension_has_2_new_factors(self):
        """volume 维度新增2个因子（volume_shrink_rate + price_volume_divergence）"""
        volume_new = [f for f in NEW_FACTORS if FACTOR_CATEGORIES[f] == "volume"]
        assert len(volume_new) == 2
        assert set(volume_new) == {"volume_shrink_rate", "price_volume_divergence"}

    def test_price_position_dimension_has_1_new_factor(self):
        """price_position 维度新增1个因子（lower_shadow_ratio）"""
        pp_new = [f for f in NEW_FACTORS if FACTOR_CATEGORIES[f] == "price_position"]
        assert len(pp_new) == 1
        assert pp_new[0] == "lower_shadow_ratio"
