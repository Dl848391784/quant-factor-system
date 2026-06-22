"""选股暴露限制测试：sort_and_select 中 max_exposure 参数。

测试场景：
1. 单因子贡献超 50% → 综合因子值被缩减，排名下降
2. 多因子均衡贡献 → 不受影响
3. max_exposure=0 → 禁用暴露限制
4. 缩减后该因子贡献占比 ≤ max_exposure
"""

import logging

import numpy as np
import pandas as pd
import pytest
from comprehensive_factor.stock_selector import sort_and_select


class TestMaxExposure:
    """单因子暴露限制测试。"""

    @staticmethod
    def _build_inputs(
        factor_a_z: np.ndarray,
        factor_b_z: np.ndarray,
        weights: dict[str, float] | None = None,
    ) -> tuple[pd.Series, pd.DataFrame, dict[str, float], list[str]]:
        """构造 sort_and_select 输入。"""
        n = len(factor_a_z)
        factor_cols = ["factor_a", "factor_b"]
        if weights is None:
            weights = {"factor_a": 0.5, "factor_b": 0.5}

        factor_df = pd.DataFrame(
            {
                "date": ["2026-06-18"] * n,
                "asset": [f"stock_{i:04d}" for i in range(n)],
                "factor_a": np.random.RandomState(42).uniform(0, 1, n),
                "factor_b": np.random.RandomState(43).uniform(0, 1, n),
                "factor_a_std": factor_a_z,
                "factor_b_std": factor_b_z,
                "amplitude": [0.05] * n,  # 确保通过振幅过滤
            }
        )

        # 综合因子 = Σ(w_i × z_i)，方向 negative（越小越好）
        composite = pd.Series(
            weights["factor_a"] * factor_a_z + weights["factor_b"] * factor_b_z,
            index=factor_df.index,
        )
        return composite, factor_df, weights, factor_cols

    def test_dominant_factor_penalized(self):
        """单因子贡献超 50% → 该股票综合因子值被缩减。"""
        # stock_0: factor_a z=-3.0, factor_b z=0.0 → composite=-1.5, factor_a 贡献=1.5, 占比 100%
        # stock_1: factor_a z=-1.0, factor_b z=-1.0 → composite=-1.0, 各占 50%，不触发
        factor_a = np.array([-3.0, -1.0])
        factor_b = np.array([0.0, -1.0])
        composite, factor_df, weights, factor_cols = self._build_inputs(factor_a, factor_b)

        # 无暴露限制：stock_0 排名第 1（composite=-1.5 < -1.0）
        result_no_limit, _, _, _ = sort_and_select(
            composite.copy(),
            factor_df.copy(),
            top_n=2,
            factor_direction="negative",
            factor_cols=factor_cols,
            weights=weights,
            max_exposure=0.0,  # 禁用
            logger=logging.getLogger("test"),
        )
        assert result_no_limit[0]["code"] == "stock_0000"

        # 有暴露限制（50%）：stock_0 被缩减 → 排名下降
        result_with_limit, _, _, _ = sort_and_select(
            composite.copy(),
            factor_df.copy(),
            top_n=2,
            factor_direction="negative",
            factor_cols=factor_cols,
            weights=weights,
            max_exposure=0.5,
            logger=logging.getLogger("test"),
        )
        # stock_0 缩减后 composite 应大于 stock_1 的 -1.0
        assert result_with_limit[0]["code"] == "stock_0001"

    def test_balanced_factors_not_affected(self):
        """多因子均衡贡献 → 不受暴露限制影响。"""
        # 两因子贡献各 50%，不触发
        factor_a = np.array([-2.0, -1.0, 0.0])
        factor_b = np.array([-2.0, -1.0, 0.0])
        composite, factor_df, weights, factor_cols = self._build_inputs(factor_a, factor_b)

        result, _, _, _ = sort_and_select(
            composite.copy(),
            factor_df.copy(),
            top_n=3,
            factor_direction="negative",
            factor_cols=factor_cols,
            weights=weights,
            max_exposure=0.5,
            logger=logging.getLogger("test"),
        )
        # 排序不变
        assert result[0]["code"] == "stock_0000"
        assert result[1]["code"] == "stock_0001"

    def test_max_exposure_zero_disables(self):
        """max_exposure=0 → 禁用暴露限制，等同于原行为。"""
        factor_a = np.array([-3.0, -1.0])
        factor_b = np.array([0.0, -1.0])
        composite, factor_df, weights, factor_cols = self._build_inputs(factor_a, factor_b)

        result, _, _, _ = sort_and_select(
            composite.copy(),
            factor_df.copy(),
            top_n=2,
            factor_direction="negative",
            factor_cols=factor_cols,
            weights=weights,
            max_exposure=0.0,
            logger=logging.getLogger("test"),
        )
        # stock_0 排名第 1（未被缩减）
        assert result[0]["code"] == "stock_0000"
        assert result[0]["composite_value"] == pytest.approx(-1.5, abs=1e-6)

    def test_scaled_contribution_within_limit(self):
        """缩减后最大因子贡献占比 ≤ max_exposure。"""
        # 单因子主导：factor_a z=-3.0, factor_b z=0.1
        # composite = 0.5*(-3.0) + 0.5*0.1 = -1.45
        # factor_a 贡献 = 1.5, 占比 = 1.5/1.45 = 103% > 50%
        factor_a = np.array([-3.0])
        factor_b = np.array([0.1])
        composite, factor_df, weights, factor_cols = self._build_inputs(factor_a, factor_b)

        result, _, _, _ = sort_and_select(
            composite.copy(),
            factor_df.copy(),
            top_n=1,
            factor_direction="negative",
            factor_cols=factor_cols,
            weights=weights,
            max_exposure=0.5,
            logger=logging.getLogger("test"),
        )
        # 缩减后 composite_value 应小于原始 -1.45（绝对值变小）
        assert abs(result[0]["composite_value"]) < 1.45


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
