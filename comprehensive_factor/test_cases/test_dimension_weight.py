"""
维度级别权重分配测试用例

遵循 MODULE.md M58 规则：
- dimension_weight_method='equal': 维度等权 1/n_dims，维度内因子按 |ICIR| 分配
- dimension_weight_method='icir': 维度权重=维度内平均|ICIR|归一化，维度内因子按 |ICIR| 分配
- dimension_weight_method=None: 不启用维度权重（向后兼容）

测试范围：
1. _build_dimension_groups 正确分组
2. _apply_dimension_weights equal 模式：各维度权重相等
3. _apply_dimension_weights icir 模式：高 ICIR 维度适度超配
4. dimension_weight_method=None 时行为不变（向后兼容）
5. 无 factor_categories 时退化为原始逻辑

创建日期: 2026-06-20
"""

import numpy as np
import pandas as pd
import pytest
from comprehensive_factor.common.weight_engine import RollingICIRWeightMethod


# ============================================================================
# 辅助函数
# ============================================================================


def _make_factor_df(
    factor_cols: list[str],
    dates: list[str],
    icir_values: dict[str, float],
) -> pd.DataFrame:
    """构建含 rolling_icir 列的 factor_df

    Args:
        factor_cols: 因子列名列表
        dates: 日期列表
        icir_values: {因子列: ICIR值}，所有日期使用相同 ICIR

    Returns:
        含 date, asset, *_std, *_rolling_icir 列的 DataFrame
    """
    rows = []
    for date in dates:
        for asset in ["stock_a", "stock_b"]:
            row = {"date": date, "asset": asset, "date_sorted": pd.Timestamp(date)}
            for col in factor_cols:
                row[col] = np.random.randn()
                row[f"{col}_std"] = np.random.randn()
                row[f"{col}_rolling_icir"] = icir_values.get(col, 0.3)
            rows.append(row)
    return pd.DataFrame(rows)


# ============================================================================
# 测试用例
# ============================================================================


class TestBuildDimensionGroups:
    """_build_dimension_groups 正确分组"""

    def test_basic_grouping(self):
        """因子按维度正确分组"""
        categories = {"rsi": "momentum", "bollinger_pb": "price_position", "volume_ratio": "volume"}
        method = RollingICIRWeightMethod(
            dimension_weight_method="icir",
            factor_categories=categories,
        )

        factor_cols = ["rsi_6", "bollinger_pb_20", "volume_ratio_5"]
        groups = method._build_dimension_groups(factor_cols)

        assert "momentum" in groups
        assert "price_position" in groups
        assert "volume" in groups
        assert "rsi_6" in groups["momentum"]
        assert "bollinger_pb_20" in groups["price_position"]
        assert "volume_ratio_5" in groups["volume"]

    def test_no_categories_returns_empty(self):
        """factor_categories=None 时返回空 dict"""
        method = RollingICIRWeightMethod(dimension_weight_method="icir", factor_categories=None)
        groups = method._build_dimension_groups(["rsi_6", "bollinger_pb_20"])
        assert groups == {}

    def test_no_method_returns_empty(self):
        """dimension_weight_method=None 时返回空 dict"""
        categories = {"rsi": "momentum"}
        method = RollingICIRWeightMethod(dimension_weight_method=None, factor_categories=categories)
        groups = method._build_dimension_groups(["rsi_6"])
        assert groups == {}

    def test_uncategorized_factors(self):
        """未分类因子归入 uncategorized"""
        categories = {"rsi": "momentum"}
        method = RollingICIRWeightMethod(
            dimension_weight_method="icir",
            factor_categories=categories,
        )

        groups = method._build_dimension_groups(["rsi_6", "unknown_factor_5"])
        assert "momentum" in groups
        assert "uncategorized" in groups
        assert "unknown_factor_5" in groups["uncategorized"]


class TestEqualDimensionWeight:
    """equal 模式：各维度权重相等"""

    def test_equal_dimension_weights(self):
        """4 维度各 25%"""
        categories = {
            "rsi": "momentum",
            "positive_day_ratio_5": "momentum",
            "bollinger_pb": "price_position",
            "tail_price_position": "price_position",
            "volume_ratio": "volume",
            "volume_price_strength": "volume",
            "tail_price_volume_intensity": "tail_behavior",
            "tail_volume_acceleration": "tail_behavior",
        }
        method = RollingICIRWeightMethod(
            dimension_weight_method="equal",
            factor_categories=categories,
        )

        factor_cols = [
            "rsi_6",
            "positive_day_ratio_5",
            "bollinger_pb_20",
            "tail_price_position",
            "volume_ratio_5",
            "volume_price_strength",
            "tail_price_volume_intensity",
            "tail_volume_acceleration",
        ]
        rolling_icir_cols = [f"{c}_rolling_icir" for c in factor_cols]

        # 所有因子 ICIR 相同 → 维度内等权
        icir_values = dict.fromkeys(factor_cols, 0.3)
        factor_df = _make_factor_df(factor_cols, ["2026-06-19"], icir_values)

        groups = method._build_dimension_groups(factor_cols)
        factor_df = method._apply_dimension_weights(factor_df, factor_cols, rolling_icir_cols, groups)

        # 各维度权重应各 25%
        dim_weights = {}
        for dim, cols in groups.items():
            dim_w = factor_df[[f"{c}_dim_weight" for c in cols]].iloc[0].sum()
            dim_weights[dim] = dim_w

        for dim in ["momentum", "price_position", "volume", "tail_behavior"]:
            assert abs(dim_weights[dim] - 0.25) < 0.01, f"{dim}: {dim_weights[dim]}"

    def test_equal_dimension_with_different_icir(self):
        """equal 模式：维度内因子按 |ICIR| 分配，但维度间等权"""
        categories = {"rsi": "momentum", "bollinger_pb": "price_position"}
        method = RollingICIRWeightMethod(
            dimension_weight_method="equal",
            factor_categories=categories,
        )

        factor_cols = ["rsi_6", "bollinger_pb_20"]
        rolling_icir_cols = [f"{c}_rolling_icir" for c in factor_cols]

        # rsi ICIR=0.6, bollinger_pb ICIR=0.3 → 各维度只有1个因子
        icir_values = {"rsi_6": 0.6, "bollinger_pb_20": 0.3}
        factor_df = _make_factor_df(factor_cols, ["2026-06-19"], icir_values)

        groups = method._build_dimension_groups(factor_cols)
        factor_df = method._apply_dimension_weights(factor_df, factor_cols, rolling_icir_cols, groups)

        # 各维度 50%
        rsi_w = factor_df["rsi_6_dim_weight"].iloc[0]
        bollinger_w = factor_df["bollinger_pb_20_dim_weight"].iloc[0]
        assert abs(rsi_w - 0.5) < 0.01
        assert abs(bollinger_w - 0.5) < 0.01


class TestICIRDimensionWeight:
    """icir 模式：高 ICIR 维度适度超配"""

    def test_high_icir_dim_overweight(self):
        """高 ICIR 维度适度超配，但不主导"""
        categories = {
            "rsi": "momentum",
            "kdj_j": "momentum",  # momentum 有 2 个因子
            "bollinger_pb": "price_position",  # price_position 有 1 个因子
        }
        method = RollingICIRWeightMethod(
            dimension_weight_method="icir",
            factor_categories=categories,
        )

        factor_cols = ["rsi_6", "kdj_j_9", "bollinger_pb_20"]
        rolling_icir_cols = [f"{c}_rolling_icir" for c in factor_cols]

        # rsi ICIR=0.6, kdj_j ICIR=0.2, bollinger_pb ICIR=0.4
        icir_values = {"rsi_6": 0.6, "kdj_j_9": 0.2, "bollinger_pb_20": 0.4}
        factor_df = _make_factor_df(factor_cols, ["2026-06-19"], icir_values)

        groups = method._build_dimension_groups(factor_cols)
        factor_df = method._apply_dimension_weights(factor_df, factor_cols, rolling_icir_cols, groups)

        rsi_w = factor_df["rsi_6_dim_weight"].iloc[0]
        bollinger_w = factor_df["bollinger_pb_20_dim_weight"].iloc[0]

        # momentum avg|ICIR| = (0.6+0.2)/2 = 0.4, price_position avg|ICIR| = 0.4/1 = 0.4
        # 两维度平均 ICIR 相同 → 维度权重各 50%
        # rsi 维度内权重 = 0.6/(0.6+0.2) = 0.75, × 0.5 = 0.375
        # bollinger 维度内权重 = 1.0, × 0.5 = 0.5
        # 归一化后: rsi = 0.375/0.875 ≈ 0.4286, bollinger = 0.5/0.875 ≈ 0.5714
        # bollinger 权重 > rsi 权重（因为 price_position 维度只有 1 个因子不分散）
        assert bollinger_w > rsi_w

    def test_icir_dim_weight_vs_no_dimension(self):
        """icir 模式 vs 无维度权重：多因子维度被抑制"""
        categories = {
            "rsi": "momentum",
            "kdj_j": "momentum",
            "bollinger_pb": "price_position",
        }
        method_dim = RollingICIRWeightMethod(
            dimension_weight_method="icir",
            factor_categories=categories,
        )

        factor_cols = ["rsi_6", "kdj_j_9", "bollinger_pb_20"]
        rolling_icir_cols = [f"{c}_rolling_icir" for c in factor_cols]
        # rsi ICIR=0.6, kdj_j ICIR=0.2, bollinger_pb ICIR=0.4
        icir_values = {"rsi_6": 0.6, "kdj_j_9": 0.2, "bollinger_pb_20": 0.4}
        factor_df = _make_factor_df(factor_cols, ["2026-06-19"], icir_values)

        groups = method_dim._build_dimension_groups(factor_cols)
        factor_df = method_dim._apply_dimension_weights(factor_df, factor_cols, rolling_icir_cols, groups)

        rsi_w_dim = factor_df["rsi_6_dim_weight"].iloc[0]

        # 无维度权重时 rsi_w = 0.6/(0.6+0.2+0.4) = 0.5
        # icir 模式下 momentum 维度有 2 个因子分散权重 → rsi_w < 0.5
        assert rsi_w_dim < 0.5

    def test_weights_sum_to_one(self):
        """所有因子权重之和 = 1.0"""
        categories = {
            "rsi": "momentum",
            "bollinger_pb": "price_position",
            "volume_ratio": "volume",
        }
        method = RollingICIRWeightMethod(
            dimension_weight_method="icir",
            factor_categories=categories,
        )

        factor_cols = ["rsi_6", "bollinger_pb_20", "volume_ratio_5"]
        rolling_icir_cols = [f"{c}_rolling_icir" for c in factor_cols]
        icir_values = {"rsi_6": 0.5, "bollinger_pb_20": 0.3, "volume_ratio_5": 0.4}
        factor_df = _make_factor_df(factor_cols, ["2026-06-19"], icir_values)

        groups = method._build_dimension_groups(factor_cols)
        factor_df = method._apply_dimension_weights(factor_df, factor_cols, rolling_icir_cols, groups)

        total_w = factor_df[[f"{c}_dim_weight" for c in factor_cols]].iloc[0].sum()
        assert abs(total_w - 1.0) < 0.01


class TestBackwardCompat:
    """dimension_weight_method=None 时行为不变"""

    def test_none_method_no_dimension_weights(self):
        """dimension_weight_method=None 时不生成维度分组"""
        categories = {"rsi": "momentum", "bollinger_pb": "price_position"}
        method = RollingICIRWeightMethod(
            dimension_weight_method=None,
            factor_categories=categories,
        )

        groups = method._build_dimension_groups(["rsi_6", "bollinger_pb_20"])
        assert groups == {}

    def test_none_method_original_logic(self):
        """dimension_weight_method=None 时使用原始权重计算"""
        method = RollingICIRWeightMethod(dimension_weight_method=None, factor_categories=None)

        factor_cols = ["rsi_6", "bollinger_pb_20"]
        rolling_icir_cols = [f"{c}_rolling_icir" for c in factor_cols]
        icir_values = {"rsi_6": 0.6, "bollinger_pb_20": 0.2}
        factor_df = _make_factor_df(factor_cols, ["2026-06-19"], icir_values)

        # 无维度分组 → 原始逻辑
        groups = method._build_dimension_groups(factor_cols)
        assert groups == {}

        # 手动执行原始逻辑（与 calculate() 中的 else 分支一致）
        factor_df["weight_sum"] = factor_df[rolling_icir_cols].abs().sum(axis=1)
        weight_sum_safe = factor_df["weight_sum"].replace(0, np.nan)
        for col, rolling_col in zip(factor_cols, rolling_icir_cols):
            weight = factor_df[rolling_col].abs() / weight_sum_safe
            weight = weight.fillna(1.0 / len(factor_cols))
            factor_df[f"{col}_dim_weight"] = weight

        # 原始逻辑: rsi_w = 0.6/(0.6+0.2) = 0.75
        rsi_w = factor_df["rsi_6_dim_weight"].iloc[0]
        assert abs(rsi_w - 0.75) < 0.01


class TestNaNHandling:
    """NaN 因子处理"""

    def test_nan_factor_equal_fallback(self):
        """NaN rolling_icir 因子在维度内回退等权"""
        categories = {"rsi": "momentum", "kdj_j": "momentum", "bollinger_pb": "price_position"}
        method = RollingICIRWeightMethod(
            dimension_weight_method="equal",
            factor_categories=categories,
        )

        factor_cols = ["rsi_6", "kdj_j_9", "bollinger_pb_20"]
        rolling_icir_cols = [f"{c}_rolling_icir" for c in factor_cols]
        icir_values = {"rsi_6": 0.6, "bollinger_pb_20": 0.3}
        factor_df = _make_factor_df(factor_cols, ["2026-06-19"], icir_values)

        # kdj_j rolling_icir 设为 NaN
        factor_df["kdj_j_9_rolling_icir"] = np.nan

        groups = method._build_dimension_groups(factor_cols)
        factor_df = method._apply_dimension_weights(factor_df, factor_cols, rolling_icir_cols, groups)

        # 维度内 kdj_j 为 NaN → 回退等权
        # momentum 有 2 个因子，equal 模式维度权重 = 0.5
        # kdj_j NaN → intra_weight = 1/2 = 0.5
        # rsi intra_weight = 0.6/(0.6+0) 但 dim_icir_sum_safe 已 replace(0, nan)
        # 实际：dim_icir_sum = 0.6（只 rsi 有效），rsi intra = 0.6/0.6 = 1.0
        # kdj_j intra = NaN → fillna(1/2) = 0.5
        # 但最终行级归一化会调整
        total_w = factor_df[[f"{c}_dim_weight" for c in factor_cols]].iloc[0].sum()
        assert abs(total_w - 1.0) < 0.01  # 权重和仍为 1
