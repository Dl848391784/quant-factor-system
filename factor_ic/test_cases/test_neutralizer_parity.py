"""neutralizer 引擎与 legacy industry_neutral_residual 的逐位一致性测试（P1.3 + P1.6 雏形）。

测试目标:
    在仅含 IndustryProvider 单 control 场景下（drop_first=False, fit_intercept=True），
    新引擎 neutralize() 与 legacy industry_neutral_residual() 产出**逐位一致**的残差因子。

逐位一致包括:
    - 行数 / 列名 / 列顺序
    - (date, asset) 元组集合相同
    - 同一 (date, asset) 的 neutral_factor 值 abs diff < 1e-9 (round(6) 后)

参考:
    designs/feat_neutralization_framework.md §5.3, §14.1（P1.3, P1.6）
    factor_ic/common/ic_calculator.py industry_neutral_residual (P0 参考实现)
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from factor_ic.common.control_providers import IndustryProvider
from factor_ic.common.ic_calculator import industry_neutral_residual
from factor_ic.common.neutralizer import neutralize


# ============================================================
# 数据生成 helpers
# ============================================================


def _make_factor_df(
    n_dates: int = 5,
    industries: tuple[str, ...] = ("银行", "医药", "电力设备", "食品饮料"),
    stocks_per_industry: int = 8,
    seed: int = 42,
) -> pd.DataFrame:
    """生成 factor_df，含 [date, asset, factor, industry] 列，已 dropna + 已剔'其他'。"""
    rng = np.random.default_rng(seed)
    dates = pd.date_range("2024-01-01", periods=n_dates, freq="B")

    rows = []
    asset_id = 0
    for industry in industries:
        for _ in range(stocks_per_industry):
            asset_code = f"{asset_id:06d}"
            asset_id += 1
            for date in dates:
                rows.append(
                    {
                        "date": date,
                        "asset": asset_code,
                        "factor": rng.normal(0, 1),
                        "industry": industry,
                    }
                )
    return pd.DataFrame(rows)


def _make_factor_df_with_small_industry(seed: int = 7) -> pd.DataFrame:
    """含一个股票数 < min_count 的小行业，用于触发 filter_invalid_rows。"""
    rng = np.random.default_rng(seed)
    dates = pd.date_range("2024-01-01", periods=3, freq="B")

    rows = []
    asset_id = 0
    # 大行业 8 只
    for industry, n_stocks in [("银行", 8), ("医药", 6), ("微行业", 2)]:
        for _ in range(n_stocks):
            asset_code = f"{asset_id:06d}"
            asset_id += 1
            for date in dates:
                rows.append(
                    {
                        "date": date,
                        "asset": asset_code,
                        "factor": rng.normal(0, 1),
                        "industry": industry,
                    }
                )
    return pd.DataFrame(rows)


# ============================================================
# 逐位一致性测试
# ============================================================


def _assert_residuals_identical(
    legacy: pd.DataFrame,
    engine: pd.DataFrame,
    *,
    tol: float = 1e-9,
) -> None:
    """断言两路残差 DataFrame 完全等价（行数 / (date, asset) 集合 / 数值）。"""
    assert list(legacy.columns) == list(engine.columns), (
        f"列不一致: legacy={list(legacy.columns)} engine={list(engine.columns)}"
    )
    assert len(legacy) == len(engine), f"行数不一致: legacy={len(legacy)} engine={len(engine)}"

    # 排序后逐行对比
    sort_cols = ["date", "asset"]
    legacy_sorted = legacy.sort_values(sort_cols).reset_index(drop=True)
    engine_sorted = engine.sort_values(sort_cols).reset_index(drop=True)

    pd.testing.assert_series_equal(legacy_sorted["date"], engine_sorted["date"], check_names=False)
    pd.testing.assert_series_equal(legacy_sorted["asset"], engine_sorted["asset"], check_names=False)

    diff = (legacy_sorted["neutral_factor"] - engine_sorted["neutral_factor"]).abs().max()
    assert diff < tol, f"residual abs diff {diff:.3e} 超出容差 {tol:.0e}"


class TestNeutralizerParity:
    """逐位对比: neutralize([IndustryProvider]) vs industry_neutral_residual。"""

    def test_basic_parity_balanced(self):
        """均衡数据（每行业 8 只 × 5 天）逐位一致。"""
        df = _make_factor_df(n_dates=5, stocks_per_industry=8)

        legacy = industry_neutral_residual(
            factor_df=df,
            factor_col="factor",
            min_industry_stocks=5,
        )
        engine = neutralize(
            df,
            providers=[IndustryProvider()],
            factor_col="factor",
            min_count=5,
        )
        _assert_residuals_identical(legacy, engine)

    def test_parity_with_small_industry_filter(self):
        """含 2 股小行业（被 filter_invalid_rows 剔除）也应逐位一致。"""
        df = _make_factor_df_with_small_industry()

        legacy = industry_neutral_residual(
            factor_df=df,
            factor_col="factor",
            min_industry_stocks=5,
        )
        engine = neutralize(
            df,
            providers=[IndustryProvider()],
            factor_col="factor",
            min_count=5,
        )
        _assert_residuals_identical(legacy, engine)

    def test_parity_diverse_seeds(self):
        """多 seed 抽查，覆盖不同数值分布。"""
        for seed in (1, 7, 13, 42, 99):
            df = _make_factor_df(n_dates=4, stocks_per_industry=6, seed=seed)
            legacy = industry_neutral_residual(factor_df=df, factor_col="factor", min_industry_stocks=5)
            engine = neutralize(df, providers=[IndustryProvider()], factor_col="factor", min_count=5)
            _assert_residuals_identical(legacy, engine)

    def test_parity_all_filtered_returns_empty(self):
        """所有日期都因小样本被过滤时，legacy 与 engine 均返回空 DataFrame（同列）。"""
        # 每行业仅 2 股票 → min_count=5 时全部过滤
        df = _make_factor_df(n_dates=3, stocks_per_industry=2)

        legacy = industry_neutral_residual(factor_df=df, factor_col="factor", min_industry_stocks=5)
        engine = neutralize(df, providers=[IndustryProvider()], factor_col="factor", min_count=5)
        assert legacy.empty and engine.empty
        assert list(legacy.columns) == list(engine.columns) == ["date", "asset", "neutral_factor"]


# ============================================================
# 引擎独立测试（不依赖 legacy）
# ============================================================


class TestNeutralizerEngine:
    def test_empty_providers_raises(self):
        df = _make_factor_df(n_dates=2, stocks_per_industry=6)
        with pytest.raises(ValueError, match="providers 不能为空"):
            neutralize(df, providers=[], factor_col="factor")

    def test_missing_required_column_raises(self):
        df = _make_factor_df(n_dates=2, stocks_per_industry=6)
        df_no_factor = df.drop(columns=["factor"])
        with pytest.raises(ValueError, match="缺少必需列"):
            neutralize(df_no_factor, providers=[IndustryProvider()], factor_col="factor")

    def test_residual_round_to_6_decimals(self):
        """残差应 round(6)（与 P0 一致, design.md §5.1）。"""
        df = _make_factor_df(n_dates=2, stocks_per_industry=6)
        result = neutralize(df, providers=[IndustryProvider()], factor_col="factor", min_count=5)
        # 所有值的小数位数 ≤ 6
        for v in result["neutral_factor"]:
            # 存在浮点表示误差，此处仅校验 round 后值差 < 0.5e-6
            assert abs(v - round(v, 6)) < 0.5e-6
