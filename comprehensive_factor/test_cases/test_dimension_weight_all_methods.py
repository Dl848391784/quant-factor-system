"""P2: 维度权重全方法支持测试

验证 design.md P2 改动：
1. 4种加权方式都接受 dimension_weight_method + factor_categories
2. 静态权重维度再分配正确性（equal 模式 + icir 模式）
3. dimension_weight_method=None 时向后兼容（不做再分配）
4. WeightEngine.__init__ else 分支传维度参数

遵循 designs/strategy_systemic_overhaul.md §2.2 决策。
"""

import numpy as np
import pandas as pd
import pytest
from comprehensive_factor.common.weight_engine import (
    EqualWeightMethod,
    ICIRWeightMethod,
    ICWeightMethod,
    WeightEngine,
    WeightMethodBase,
)


# 测试用维度分类（2维度，每维度2因子）
TEST_CATEGORIES = {
    "rsi": "momentum",
    "bollinger_pb": "price_position",
    "volume_ratio": "volume",
    "turnover_surge": "volume",
}


def _make_test_df(factor_cols: list[str], n_rows: int = 10) -> pd.DataFrame:
    """构造测试用因子 DataFrame（含 _std 标准化列）"""
    np.random.seed(42)
    df = pd.DataFrame()
    for col in factor_cols:
        df[col] = np.random.randn(n_rows)
        df[f"{col}_std"] = (df[col] - df[col].mean()) / (df[col].std() or 1.0)
    return df


def _make_ic_results(factor_cols: list[str]) -> dict[str, dict]:
    """构造测试用 IC 结果"""
    return {col: {"ic_mean": -0.04, "icir": 0.30, "p_value": 0.01} for col in factor_cols}


class TestDimensionWeightAllMethods:
    """4种加权方式都支持维度权重"""

    @pytest.mark.parametrize(
        "method_name,method_class",
        [
            ("equal_weight", EqualWeightMethod),
            ("icir_weight", ICIRWeightMethod),
            ("ic_weight", ICWeightMethod),
        ],
    )
    def test_static_method_accepts_dimension_params(self, method_name, method_class):
        """静态方法 __init__ 接受 dimension_weight_method + factor_categories"""
        method = method_class(
            dimension_weight_method="equal",
            factor_categories=TEST_CATEGORIES,
        )
        assert method.dimension_weight_method == "equal"
        assert method.factor_categories == TEST_CATEGORIES

    def test_weight_engine_passes_dimension_params_to_all_methods(self):
        """WeightEngine.__init__ 对所有4种方法都传维度参数"""
        for method_name in ["equal_weight", "icir_weight", "ic_weight"]:
            engine = WeightEngine(
                weight_method=method_name,
                dimension_weight_method="icir",
                factor_categories=TEST_CATEGORIES,
            )
            assert engine.method.dimension_weight_method == "icir"
            assert engine.method.factor_categories == TEST_CATEGORIES

    def test_rolling_icir_still_works(self):
        """rolling_icir_weight 维度权重仍然正常工作"""
        engine = WeightEngine(
            weight_method="rolling_icir_weight",
            dimension_weight_method="icir",
            factor_categories=TEST_CATEGORIES,
        )
        assert engine.method.dimension_weight_method == "icir"


class TestStaticDimensionWeightCorrectness:
    """静态权重维度再分配正确性"""

    def test_equal_mode_dimension_equal_weight(self):
        """equal 模式: 维度等权 1/n_dims，维度内按原权重比例"""
        factor_cols = ["rsi_6", "bollinger_pb_20", "volume_ratio_5", "turnover_surge_5"]
        method = EqualWeightMethod(
            dimension_weight_method="equal",
            factor_categories=TEST_CATEGORIES,
        )
        # 等权原始权重: 各 0.25
        weights = method.get_weights(factor_cols)
        new_weights = method._apply_dimension_weights_static(weights, factor_cols)

        # 3维度 → 每维度 1/3
        # momentum(rsi): 1因子 → 1/3
        # price_position(bollinger_pb): 1因子 → 1/3
        # volume(volume_ratio + turnover_surge): 2因子 → 各 1/6
        assert pytest.approx(new_weights["rsi_6"], abs=1e-6) == 1.0 / 3
        assert pytest.approx(new_weights["bollinger_pb_20"], abs=1e-6) == 1.0 / 3
        assert pytest.approx(new_weights["volume_ratio_5"], abs=1e-6) == 1.0 / 6
        assert pytest.approx(new_weights["turnover_surge_5"], abs=1e-6) == 1.0 / 6

    def test_icir_mode_dimension_icir_weight(self):
        """icir 模式: 维度权重 = 维度内平均|权重| 归一化"""
        factor_cols = ["rsi_6", "bollinger_pb_20", "volume_ratio_5", "turnover_surge_5"]
        # 构造非等权的 ICIR 结果
        ic_results = {
            "rsi_6": {"ic_mean": -0.04, "icir": 0.40, "p_value": 0.01},
            "bollinger_pb_20": {"ic_mean": -0.04, "icir": 0.20, "p_value": 0.01},
            "volume_ratio_5": {"ic_mean": -0.04, "icir": 0.30, "p_value": 0.01},
            "turnover_surge_5": {"ic_mean": -0.04, "icir": 0.30, "p_value": 0.01},
        }
        method = ICIRWeightMethod(
            dimension_weight_method="icir",
            factor_categories=TEST_CATEGORIES,
        )
        weights = method.get_weights(factor_cols, ic_results)
        new_weights = method._apply_dimension_weights_static(weights, factor_cols)

        # 原始 ICIR 权重: |ICIR| 归一化
        # rsi=0.40, bollinger=0.20, volume=0.30, turnover=0.30 → total=1.20
        # 原始: rsi=0.333, bollinger=0.167, volume=0.25, turnover=0.25
        # 维度 avg|ICIR|: momentum=0.40, price_position=0.20, volume=(0.30+0.30)/2=0.30
        # 维度权重: 0.40/0.90=0.444, 0.20/0.90=0.222, 0.30/0.90=0.333
        # 维度内归一化:
        # momentum: rsi 100% → 0.444
        # price_position: bollinger 100% → 0.222
        # volume: volume=0.5, turnover=0.5 → 各 0.333/2=0.167
        assert pytest.approx(new_weights["rsi_6"], abs=1e-3) == 0.444
        assert pytest.approx(new_weights["bollinger_pb_20"], abs=1e-3) == 0.222
        assert pytest.approx(new_weights["volume_ratio_5"], abs=1e-3) == 0.167
        assert pytest.approx(new_weights["turnover_surge_5"], abs=1e-3) == 0.167

        # 权重和 = 1
        assert pytest.approx(sum(new_weights.values()), abs=1e-6) == 1.0

    def test_none_dimension_weight_no_redistribution(self):
        """dimension_weight_method=None 时不做再分配（向后兼容）"""
        factor_cols = ["rsi_6", "bollinger_pb_20"]
        method = EqualWeightMethod()  # 不传维度参数
        weights = method.get_weights(factor_cols)
        new_weights = method._apply_dimension_weights_static(weights, factor_cols)
        # 权重不变
        assert new_weights == weights

    def test_no_categories_no_redistribution(self):
        """factor_categories=None 时不做再分配"""
        factor_cols = ["rsi_6", "bollinger_pb_20"]
        method = EqualWeightMethod(
            dimension_weight_method="icir",
            factor_categories=None,  # 无分类
        )
        weights = method.get_weights(factor_cols)
        new_weights = method._apply_dimension_weights_static(weights, factor_cols)
        assert new_weights == weights

    def test_weights_sum_to_one(self):
        """再分配后权重和 = 1"""
        factor_cols = ["rsi_6", "bollinger_pb_20", "volume_ratio_5", "turnover_surge_5"]
        for mode in ["equal", "icir"]:
            method = EqualWeightMethod(
                dimension_weight_method=mode,
                factor_categories=TEST_CATEGORIES,
            )
            weights = method.get_weights(factor_cols)
            new_weights = method._apply_dimension_weights_static(weights, factor_cols)
            assert pytest.approx(sum(new_weights.values()), abs=1e-6) == 1.0, f"{mode} 模式权重和≠1"
