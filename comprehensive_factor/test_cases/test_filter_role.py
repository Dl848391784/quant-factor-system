"""test_filter_role: R3 filter 角色因子硬过滤单元测试

测试目标:
- apply_filter_role_factors 按 return_5d < -10% 硬过滤
- 缺 return_5d 列时跳过 + warning
- NaN return_5d 不排除 (无法判断)
- 阈值边界: -10% 等于阈值 → 不排除 (严格 <)
- 排除计数正确

设计依据: designs/feat_filter_role_fundamental_breakdown.md §3.4
"""

import logging

import numpy as np
import pandas as pd
import pytest
from comprehensive_factor.stock_selector import apply_filter_role_factors


@pytest.fixture
def base_df():
    """构造含 return_5d 列的候选 DataFrame."""
    return pd.DataFrame(
        {
            "asset": ["000001", "000002", "000003", "000004", "000005"],
            "return_5d": [0.05, -0.05, -0.12, -0.10, np.nan],
            "composite_factor": [1.0, 0.5, -2.0, 0.3, 0.1],
        }
    )


class TestFilterRoleFactors:
    """apply_filter_role_factors 单元测试."""

    def test_breakdown_excluded(self, base_df):
        """return_5d=-12% 的股票被排除."""
        result, exclusions = apply_filter_role_factors(base_df)
        assert "000003" not in result["asset"].values, "return_5d=-12% 应被排除"
        assert exclusions["cum_return_5d_breakdown"] == 1

    def test_breakdown_kept_at_threshold(self, base_df):
        """return_5d=-10% 等于阈值 → 不排除 (严格 <)."""
        result, _ = apply_filter_role_factors(base_df)
        assert "000004" in result["asset"].values, "return_5d=-10% 不应被排除 (严格 <)"

    def test_nan_return_5d_kept(self, base_df):
        """return_5d=NaN → 不排除 (无法判断)."""
        result, _ = apply_filter_role_factors(base_df)
        assert "000005" in result["asset"].values, "NaN return_5d 不应被排除"

    def test_normal_stocks_kept(self, base_df):
        """return_5d > -10% 的股票保留."""
        result, _ = apply_filter_role_factors(base_df)
        assert "000001" in result["asset"].values
        assert "000002" in result["asset"].values

    def test_missing_column_skipped(self):
        """无 return_5d 列 → 跳过过滤 + warning, 不报错."""
        df = pd.DataFrame({"asset": ["000001"], "close": [10.0]})
        result, exclusions = apply_filter_role_factors(df)
        assert len(result) == 1, "无 return_5d 列时不过滤"
        assert exclusions["cum_return_5d_breakdown"] == 0

    def test_exclusion_count_correct(self):
        """多只股票触发过滤, 计数正确."""
        df = pd.DataFrame(
            {
                "asset": ["A", "B", "C", "D"],
                "return_5d": [-0.15, -0.20, 0.03, -0.08],
            }
        )
        _, exclusions = apply_filter_role_factors(df)
        assert exclusions["cum_return_5d_breakdown"] == 2, "A(-15%) + B(-20%) = 2 只"

    def test_input_not_mutated(self, base_df):
        """原 DataFrame 不被修改."""
        original_len = len(base_df)
        apply_filter_role_factors(base_df)
        assert len(base_df) == original_len, "原 DataFrame 不应被修改"

    def test_empty_df(self):
        """空 DataFrame → 返回空 + 0 排除."""
        df = pd.DataFrame({"asset": [], "return_5d": []})
        result, exclusions = apply_filter_role_factors(df)
        assert len(result) == 0
        assert exclusions["cum_return_5d_breakdown"] == 0

    def test_all_breakdown(self):
        """全部触发过滤 → 返回空 DataFrame."""
        df = pd.DataFrame(
            {
                "asset": ["A", "B"],
                "return_5d": [-0.15, -0.20],
            }
        )
        result, exclusions = apply_filter_role_factors(df)
        assert len(result) == 0, "全部触发过滤 → 空"
        assert exclusions["cum_return_5d_breakdown"] == 2
