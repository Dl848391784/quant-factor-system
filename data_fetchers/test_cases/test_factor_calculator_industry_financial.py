"""行业财务模块（industry_financial.py）multi-merge / block 等价性测试。

覆盖 v1.45 内存优化：
1. ``_merge_asof_financial_multi`` 与三次单列 ``_merge_asof_financial`` 等价。
2. ``calculate_industry_financial_block`` 与旧三个公共函数串行调用等价。

Note: 不依赖真实 financial_data.json.gz；全部用 monkeypatch 固定 DataFrame。
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from data_fetchers.factor_calculator import industry_financial as fin_mod
from data_fetchers.factor_calculator.industry_financial import (
    _merge_asof_financial,
    _merge_asof_financial_multi,
    calculate_industry_earnings_growth,
    calculate_industry_financial_block,
    calculate_industry_pe_trend,
    calculate_industry_roe_trend,
)


@pytest.fixture
def financial_df() -> pd.DataFrame:
    """季度财务数据，覆盖 EPS 正值 / 负值 / NaN 与 growth NaN。"""
    return pd.DataFrame(
        {
            "asset": [
                "000001.SZ",
                "000001.SZ",
                "000002.SZ",
                "000002.SZ",
                "000003.SZ",
                "000003.SZ",
            ],
            "report_date": [
                "2024-12-31",
                "2025-03-31",
                "2024-12-31",
                "2025-03-31",
                "2024-12-31",
                "2025-03-31",
            ],
            "roe": [0.10, 0.12, 0.08, 0.09, 0.05, 0.04],
            "net_profit_growth_yoy": [0.20, 0.30, 0.10, np.nan, -0.10, -0.20],
            "annualized_eps": [1.0, 1.2, 2.0, -0.5, np.nan, 0.8],
        }
    )


@pytest.fixture
def factor_df() -> pd.DataFrame:
    """日频因子表，预填 industry 以跳过外部行业映射依赖。"""
    return pd.DataFrame(
        {
            "date": [
                "2025-01-02",
                "2025-04-01",
                "2025-01-02",
                "2025-04-01",
                "2025-01-02",
                "2025-04-01",
            ],
            "asset": [
                "000001.SZ",
                "000001.SZ",
                "000002.SZ",
                "000002.SZ",
                "000003.SZ",
                "000003.SZ",
            ],
            "industry": ["银行", "银行", "银行", "银行", "地产", "地产"],
            "close": [10.0, 12.0, 20.0, 21.0, 5.0, 5.2],
        }
    )


def _patch_load(monkeypatch: pytest.MonkeyPatch, financial_df: pd.DataFrame) -> None:
    """让 _load_financial_data 返回固定 DataFrame，绕过文件 IO。"""
    monkeypatch.setattr(fin_mod, "_load_financial_data", lambda *_a, **_k: financial_df.copy())


def test_multi_asof_equals_concat_of_single_asof(factor_df: pd.DataFrame, financial_df: pd.DataFrame) -> None:
    """multi asof 一次取三列 == 三次单列 asof 拼接。"""
    value_cols = ["roe", "net_profit_growth_yoy", "annualized_eps"]

    multi_out = _merge_asof_financial_multi(factor_df, financial_df, value_cols)
    single_outs = [
        _merge_asof_financial(factor_df, financial_df, col, col).reset_index(drop=True) for col in value_cols
    ]
    concat = pd.concat(single_outs, axis=1)
    concat.columns = value_cols  # type: ignore[assignment]

    assert list(multi_out.columns) == value_cols
    assert len(multi_out) == len(factor_df)
    for col in value_cols:
        pd.testing.assert_series_equal(
            multi_out[col].reset_index(drop=True),
            concat[col].reset_index(drop=True),
            check_names=False,
        )


def test_block_outputs_match_legacy_serial_calls(
    monkeypatch: pytest.MonkeyPatch,
    factor_df: pd.DataFrame,
    financial_df: pd.DataFrame,
) -> None:
    """orchestrator 三列输出 ≡ 旧三个公共函数串行调用。"""
    _patch_load(monkeypatch, financial_df)

    legacy = calculate_industry_pe_trend(calculate_industry_earnings_growth(calculate_industry_roe_trend(factor_df)))
    block = calculate_industry_financial_block(factor_df)

    output_cols = ["industry_roe_trend", "industry_earnings_growth", "industry_pe_trend"]
    legacy_indexed = legacy.set_index(["asset", "date"])[output_cols].sort_index()
    block_indexed = block.set_index(["asset", "date"])[output_cols].sort_index()

    pd.testing.assert_frame_equal(legacy_indexed, block_indexed)


def test_block_outputs_three_factors_and_cleans_intermediate_columns(
    monkeypatch: pytest.MonkeyPatch,
    factor_df: pd.DataFrame,
    financial_df: pd.DataFrame,
) -> None:
    """orchestrator 一次返回三列因子，且不残留中间列。"""
    _patch_load(monkeypatch, financial_df)

    result = calculate_industry_financial_block(factor_df)

    for col in ("industry_roe_trend", "industry_earnings_growth", "industry_pe_trend"):
        assert col in result.columns
    for col in ("roe_daily", "growth_daily", "eps_daily", "pe_daily", "delta_roe", "delta_pe"):
        assert col not in result.columns, f"中间列 {col} 未被清理"
    assert len(result) == len(factor_df)
    assert "industry_roe_trend" not in factor_df.columns


def test_block_eps_non_positive_and_nan_match_legacy(
    monkeypatch: pytest.MonkeyPatch,
    factor_df: pd.DataFrame,
    financial_df: pd.DataFrame,
) -> None:
    """EPS<=0 / EPS NaN 边界沿用旧函数语义。"""
    _patch_load(monkeypatch, financial_df)

    legacy = calculate_industry_pe_trend(factor_df).set_index(["asset", "date"])
    block = calculate_industry_financial_block(factor_df).set_index(["asset", "date"])

    pd.testing.assert_series_equal(
        legacy["industry_pe_trend"].sort_index(),
        block["industry_pe_trend"].sort_index(),
        check_names=False,
    )
