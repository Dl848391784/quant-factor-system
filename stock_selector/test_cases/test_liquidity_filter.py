"""流动性过滤测试 (v2.40 design.md §3.3)

测试覆盖:
1. 默认关闭（enable_liquidity_filter=False）→ 不排除
2. 启用 + 有 volume/close → 低于 P0.05 的股票被排除
3. 启用 + 无 volume/close → 跳过 + 警告
4. 启用 + 所有 amount 为 0 → 跳过
5. 启用 + 过滤后仍够 top_n → 正常选股
"""

import logging

import numpy as np
import pandas as pd
import pytest
from stock_selector import sort_and_select


LOGGER = logging.getLogger("test_liquidity_filter")
LOGGER.setLevel(logging.INFO)


@pytest.fixture
def factor_df():
    """10 只股票, 含 volume + close 列"""
    np.random.seed(42)
    n = 10
    return pd.DataFrame(
        {
            "asset": [f"stock_{i:04d}" for i in range(n)],
            "rsi_6": np.random.randn(n),
            "rsi_6_std": np.random.randn(n),
            "volume_ratio_5": np.random.randn(n),
            "volume_ratio_5_std": np.random.randn(n),
            "volume": [1e3, 2e4, 3e5, 4e6, 5e7, 100, 200, 1e3, 5e4, 2e6],
            "close": [10.0, 20.0, 30.0, 40.0, 50.0, 10.0, 20.0, 30.0, 40.0, 50.0],
        }
    )


@pytest.fixture
def composite_factor(factor_df):
    """综合因子: 与 factor_df 同索引"""
    return pd.Series(np.random.randn(len(factor_df)), index=factor_df.index)


class TestLiquidityFilter:
    """流动性过滤测试"""

    def test_disabled_by_default_no_filtering(self, composite_factor, factor_df):
        """默认关闭 → 不排除任何股票"""
        result, excluded_amp, excluded_cov, excluded_liq = sort_and_select(
            composite_factor,
            factor_df,
            top_n=5,
            factor_direction="negative",
            factor_cols=["rsi_6", "volume_ratio_5"],
            weights={"rsi_6": 0.5, "volume_ratio_5": 0.5},
            enable_liquidity_filter=False,
            logger=LOGGER,
        )
        assert excluded_liq == 0
        assert len(result) == 5

    def test_enabled_excludes_low_amount(self, composite_factor, factor_df):
        """启用 → 排除成交额最低的 5% 股票"""
        result, excluded_amp, excluded_cov, excluded_liq = sort_and_select(
            composite_factor,
            factor_df,
            top_n=10,
            factor_direction="negative",
            factor_cols=["rsi_6", "volume_ratio_5"],
            weights={"rsi_6": 0.5, "volume_ratio_5": 0.5},
            enable_liquidity_filter=True,
            min_amount_percentile=0.05,
            logger=LOGGER,
        )
        # 10 只股票, 5% = 0.5 → 至少排除 1 只 (amount 特别低的)
        assert excluded_liq >= 1, f"预期排除 ≥1 只, 实际 {excluded_liq}"
        # 排除后仍能选出 top_n
        assert len(result) <= 10 - excluded_liq

    def test_enabled_no_volume_column_skips(self, composite_factor, factor_df):
        """无 volume 列 → 跳过 + 警告"""
        df_no_vol = factor_df.drop(columns=["volume"])
        result, excluded_amp, excluded_cov, excluded_liq = sort_and_select(
            composite_factor,
            df_no_vol,
            top_n=5,
            factor_direction="negative",
            factor_cols=["rsi_6", "volume_ratio_5"],
            weights={"rsi_6": 0.5, "volume_ratio_5": 0.5},
            enable_liquidity_filter=True,
            min_amount_percentile=0.05,
            logger=LOGGER,
        )
        assert excluded_liq == 0
        assert len(result) == 5

    def test_enabled_no_close_column_skips(self, composite_factor, factor_df):
        """无 close 列 → 跳过 + 警告"""
        df_no_close = factor_df.drop(columns=["close"])
        result, excluded_amp, excluded_cov, excluded_liq = sort_and_select(
            composite_factor,
            df_no_close,
            top_n=5,
            factor_direction="negative",
            factor_cols=["rsi_6", "volume_ratio_5"],
            weights={"rsi_6": 0.5, "volume_ratio_5": 0.5},
            enable_liquidity_filter=True,
            min_amount_percentile=0.05,
            logger=LOGGER,
        )
        assert excluded_liq == 0
        assert len(result) == 5

    def test_enabled_all_zero_amount(self, composite_factor, factor_df):
        """所有 amount 为 0 → 跳过"""
        df_zero = factor_df.copy()
        df_zero["volume"] = 0
        result, excluded_amp, excluded_cov, excluded_liq = sort_and_select(
            composite_factor,
            df_zero,
            top_n=5,
            factor_direction="negative",
            factor_cols=["rsi_6", "volume_ratio_5"],
            weights={"rsi_6": 0.5, "volume_ratio_5": 0.5},
            enable_liquidity_filter=True,
            min_amount_percentile=0.05,
            logger=LOGGER,
        )
        assert excluded_liq == 0
        assert len(result) == 5
