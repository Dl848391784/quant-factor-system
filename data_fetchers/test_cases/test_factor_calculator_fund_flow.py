"""资金流模块（fund_flow.py）等价性 / cache 单元测试

覆盖 v1.44 内存优化 Round 1 改动：
1. ``_load_fund_flow_data_cached``：默认路径下同 PID 第二次返回同一对象（id 相等）
2. ``_load_fund_flow_data(path)``：自定义路径不走 cache（每次新对象）
3. ``_merge_fund_flow_daily_multi``：多列一次返回 == 多次单列调用拼接（数值与行序）
4. ``_merge_fund_flow_daily``（thin wrapper）：与重构前等价（手算对照）

Note: 不依赖真实 fund_flow_data.json.gz，全部用临时文件 + monkeypatch。
"""

from __future__ import annotations

import gzip
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from data_fetchers.factor_calculator import fund_flow as ff_mod
from data_fetchers.factor_calculator.fund_flow import (
    _load_fund_flow_data,
    _load_fund_flow_data_cached,
    _merge_fund_flow_daily,
    _merge_fund_flow_daily_multi,
    calculate_capital_flow_block,
    calculate_capital_flow_intensity,
    calculate_capital_flow_ratio_trend,
)


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def fund_flow_records() -> list[dict]:
    """5 行资金流原始数据（asset × date × 三个值列）"""
    return [
        {
            "asset": "000001.SZ",
            "date": "2025-01-02",
            "main_inflow_ratio": 0.10,
            "main_inflow_amount": 1000.0,
            "total_volume": 5000.0,
        },
        {
            "asset": "000001.SZ",
            "date": "2025-01-03",
            "main_inflow_ratio": -0.05,
            "main_inflow_amount": -500.0,
            "total_volume": 4500.0,
        },
        {
            "asset": "000002.SZ",
            "date": "2025-01-02",
            "main_inflow_ratio": 0.20,
            "main_inflow_amount": 2000.0,
            "total_volume": 8000.0,
        },
        {
            "asset": "000002.SZ",
            "date": "2025-01-03",
            "main_inflow_ratio": 0.15,
            "main_inflow_amount": 1500.0,
            "total_volume": 7500.0,
        },
        {
            "asset": "000003.SZ",
            "date": "2025-01-02",
            "main_inflow_ratio": -0.10,
            "main_inflow_amount": -1000.0,
            "total_volume": 3000.0,
        },
    ]


@pytest.fixture
def fund_flow_df(fund_flow_records: list[dict]) -> pd.DataFrame:
    return pd.DataFrame(fund_flow_records)


@pytest.fixture
def factor_df() -> pd.DataFrame:
    """6 行因子表（含 1 行无匹配的资金流：000004.SZ）"""
    return pd.DataFrame(
        {
            "date": ["2025-01-02", "2025-01-02", "2025-01-03", "2025-01-03", "2025-01-02", "2025-01-02"],
            "asset": ["000001.SZ", "000002.SZ", "000001.SZ", "000002.SZ", "000003.SZ", "000004.SZ"],
            "close": [10.0, 20.0, 10.5, 20.5, 5.0, 8.0],
        }
    )


@pytest.fixture
def temp_fund_flow_path(tmp_path: Path, fund_flow_records: list[dict]) -> Path:
    """写一个 gzip JSON 临时文件，模拟真实 fund_flow_data.json.gz"""
    p = tmp_path / "fund_flow_data.json.gz"
    payload = {"data": fund_flow_records, "meta": {"source": "unit_test"}}
    with gzip.open(p, "wt") as f:
        json.dump(payload, f)
    return p


@pytest.fixture(autouse=True)
def _reset_cache():
    """每个 test 前后清 lru_cache，避免互相污染"""
    _load_fund_flow_data_cached.cache_clear()
    yield
    _load_fund_flow_data_cached.cache_clear()


# ============================================================================
# Tests: _load_fund_flow_data cache 行为
# ============================================================================


def test_load_default_path_returns_same_object(monkeypatch: pytest.MonkeyPatch, temp_fund_flow_path: Path) -> None:
    """默认路径下，同 PID 第二次调用返回同一 DataFrame 对象（lru_cache 生效）"""
    # 把模块的 _get_fund_flow_data_path 指向临时文件
    monkeypatch.setattr(ff_mod, "_get_fund_flow_data_path", lambda *_a, **_k: temp_fund_flow_path)

    df1 = _load_fund_flow_data()  # 默认路径 → cache miss
    df2 = _load_fund_flow_data()  # 默认路径 → cache hit
    assert df1 is df2, "默认路径第二次调用必须命中 cache，返回同一对象"

    info = _load_fund_flow_data_cached.cache_info()
    assert info.hits == 1
    assert info.misses == 1
    assert info.currsize == 1


def test_load_custom_path_bypasses_cache(temp_fund_flow_path: Path) -> None:
    """自定义路径不走 cache（每次新对象，便于测试隔离）"""
    df1 = _load_fund_flow_data(temp_fund_flow_path)
    df2 = _load_fund_flow_data(temp_fund_flow_path)
    assert df1 is not df2, "自定义路径每次必须返回新对象（绕过 cache）"
    pd.testing.assert_frame_equal(df1, df2)  # 数值仍相等

    info = _load_fund_flow_data_cached.cache_info()
    assert info.hits == 0
    assert info.misses == 0  # 自定义路径完全不进 cache


def test_load_missing_file_raises(tmp_path: Path) -> None:
    """文件不存在抛 FileNotFoundError"""
    with pytest.raises(FileNotFoundError, match="资金流数据缓存不存在"):
        _load_fund_flow_data(tmp_path / "no_such_file.json.gz")


# ============================================================================
# Tests: _merge_fund_flow_daily_multi vs _merge_fund_flow_daily 等价性
# ============================================================================


def test_multi_merge_equals_concat_of_single_merges(factor_df: pd.DataFrame, fund_flow_df: pd.DataFrame) -> None:
    """multi 一次取多列 == 多次单列调用结果按列拼接（数值 + 行序）"""
    value_cols = ["main_inflow_ratio", "main_inflow_amount", "total_volume"]

    # 新版：一次 merge 多列
    multi_out = _merge_fund_flow_daily_multi(factor_df, fund_flow_df, value_cols)

    # 老路径：3 次单列调用，逐列拼接
    single_outs = [
        _merge_fund_flow_daily(factor_df, fund_flow_df, col, col).reset_index(drop=True) for col in value_cols
    ]
    concat = pd.concat(single_outs, axis=1)
    concat.columns = value_cols  # type: ignore[assignment]

    # 列名一致 + 行数一致
    assert list(multi_out.columns) == value_cols
    assert len(multi_out) == len(factor_df)

    # 数值逐列严格相等（NaN 也要在同一行）
    for col in value_cols:
        pd.testing.assert_series_equal(
            multi_out[col].reset_index(drop=True),
            concat[col].reset_index(drop=True),
            check_names=False,
        )


def test_multi_merge_row_order_matches_factor_df(factor_df: pd.DataFrame, fund_flow_df: pd.DataFrame) -> None:
    """multi merge 行序必须与输入 factor_df 一致（不被 merge 重排）"""
    multi_out = _merge_fund_flow_daily_multi(factor_df, fund_flow_df, ["main_inflow_ratio"])
    assert len(multi_out) == len(factor_df)

    # 手算预期：按 factor_df 顺序匹配 fund_flow_df
    expected = [0.10, 0.20, -0.05, 0.15, -0.10, np.nan]  # 最后一行 000004.SZ 无匹配 → NaN
    actual = multi_out["main_inflow_ratio"].tolist()
    for exp, act in zip(expected, actual, strict=True):
        if np.isnan(exp):
            assert np.isnan(act)
        else:
            assert exp == act


def test_multi_merge_unmatched_rows_are_nan(factor_df: pd.DataFrame, fund_flow_df: pd.DataFrame) -> None:
    """factor_df 中无对应资金流的行，所有 value_cols 列均为 NaN"""
    multi_out = _merge_fund_flow_daily_multi(
        factor_df,
        fund_flow_df,
        ["main_inflow_ratio", "main_inflow_amount", "total_volume"],
    )
    # 最后一行 (000004.SZ, 2025-01-02) 在 fund_flow_df 中不存在
    last = multi_out.iloc[-1]
    assert all(pd.isna(last[col]) for col in ["main_inflow_ratio", "main_inflow_amount", "total_volume"])


def test_single_merge_thin_wrapper_returns_named_series(factor_df: pd.DataFrame, fund_flow_df: pd.DataFrame) -> None:
    """thin wrapper 返回 Series，name 为 output_col，长度对齐"""
    out = _merge_fund_flow_daily(factor_df, fund_flow_df, "main_inflow_amount", "amount_daily")
    assert isinstance(out, pd.Series)
    assert out.name == "amount_daily"
    assert len(out) == len(factor_df)
    # 未匹配行为 NaN
    assert pd.isna(out.iloc[-1])
    # 已匹配行数值正确
    assert out.iloc[0] == 1000.0  # 000001.SZ, 2025-01-02
    assert out.iloc[3] == 1500.0  # 000002.SZ, 2025-01-03


# ============================================================================
# Tests: calculate_capital_flow_block orchestrator 等价性
# ============================================================================


@pytest.fixture
def block_factor_df() -> pd.DataFrame:
    """带预填 industry 的 factor_df，跳过 _add_industry_column 的外部依赖。

    构造场景：
      - 同行业 2 只 (000001.SZ + 000002.SZ → 银行)，跨 3 天 → 行业聚合有信号
      - 独立行业 1 只 (000003.SZ → 地产)，2 天 → 单股聚合
      - 无资金流匹配 1 只 (000099.SZ → 银行)，2 天 → 测 NaN 传播
    """
    return pd.DataFrame(
        {
            "date": [
                "2025-01-02",
                "2025-01-03",
                "2025-01-06",
                "2025-01-02",
                "2025-01-03",
                "2025-01-06",
                "2025-01-02",
                "2025-01-03",
                "2025-01-02",
                "2025-01-03",
            ],
            "asset": [
                "000001.SZ",
                "000001.SZ",
                "000001.SZ",
                "000002.SZ",
                "000002.SZ",
                "000002.SZ",
                "000003.SZ",
                "000003.SZ",
                "000099.SZ",
                "000099.SZ",
            ],
            "industry": [
                "银行",
                "银行",
                "银行",
                "银行",
                "银行",
                "银行",
                "地产",
                "地产",
                "银行",
                "银行",
            ],
            "close": [10.0, 10.5, 11.0, 20.0, 20.5, 21.0, 5.0, 5.2, 8.0, 8.1],
        }
    )


@pytest.fixture
def block_fund_flow_records() -> list[dict]:
    """为 block_factor_df 提供资金流（覆盖 000001/000002/000003，缺 000099）"""
    return [
        # 000001.SZ 三天
        {
            "asset": "000001.SZ",
            "date": "2025-01-02",
            "main_inflow_ratio": 0.10,
            "main_inflow_amount": 1000.0,
            "total_volume": 5000.0,
        },
        {
            "asset": "000001.SZ",
            "date": "2025-01-03",
            "main_inflow_ratio": 0.05,
            "main_inflow_amount": 800.0,
            "total_volume": 4500.0,
        },
        {
            "asset": "000001.SZ",
            "date": "2025-01-06",
            "main_inflow_ratio": -0.02,
            "main_inflow_amount": -200.0,
            "total_volume": 4000.0,
        },
        # 000002.SZ 三天
        {
            "asset": "000002.SZ",
            "date": "2025-01-02",
            "main_inflow_ratio": 0.20,
            "main_inflow_amount": 2000.0,
            "total_volume": 8000.0,
        },
        {
            "asset": "000002.SZ",
            "date": "2025-01-03",
            "main_inflow_ratio": 0.15,
            "main_inflow_amount": 1500.0,
            "total_volume": 7500.0,
        },
        {
            "asset": "000002.SZ",
            "date": "2025-01-06",
            "main_inflow_ratio": 0.18,
            "main_inflow_amount": 1700.0,
            "total_volume": 7000.0,
        },
        # 000003.SZ 两天
        {
            "asset": "000003.SZ",
            "date": "2025-01-02",
            "main_inflow_ratio": -0.10,
            "main_inflow_amount": -1000.0,
            "total_volume": 3000.0,
        },
        {
            "asset": "000003.SZ",
            "date": "2025-01-03",
            "main_inflow_ratio": -0.08,
            "main_inflow_amount": -800.0,
            "total_volume": 2800.0,
        },
        # 注：故意不放 000099.SZ（测试 NaN 传播 + 行业聚合时 NaN 是否被 mean 跳过）
        # 注：故意 total_volume=0 边界 — 单独造一个 ts
        {
            "asset": "000003.SZ",
            "date": "2025-01-06",
            "main_inflow_ratio": 0.00,
            "main_inflow_amount": 0.0,
            "total_volume": 0.0,
        },
    ]


@pytest.fixture
def block_fund_flow_df(block_fund_flow_records: list[dict]) -> pd.DataFrame:
    return pd.DataFrame(block_fund_flow_records)


def _patch_load(monkeypatch: pytest.MonkeyPatch, fund_flow_df: pd.DataFrame) -> None:
    """让 _load_fund_flow_data 返回固定 DataFrame，绕过文件 IO。"""
    monkeypatch.setattr(ff_mod, "_load_fund_flow_data", lambda *_a, **_k: fund_flow_df.copy())


def test_block_ratio_trend_matches_legacy(
    monkeypatch: pytest.MonkeyPatch,
    block_factor_df: pd.DataFrame,
    block_fund_flow_df: pd.DataFrame,
) -> None:
    """orchestrator 的 capital_flow_ratio_trend ≡ calculate_capital_flow_ratio_trend"""
    _patch_load(monkeypatch, block_fund_flow_df)

    legacy = calculate_capital_flow_ratio_trend(block_factor_df)
    block = calculate_capital_flow_block(block_factor_df)

    # 两者对同一 (asset, date) 行的因子值必须一致
    legacy_indexed = legacy.set_index(["asset", "date"])["capital_flow_ratio_trend"].sort_index()
    block_indexed = block.set_index(["asset", "date"])["capital_flow_ratio_trend"].sort_index()

    pd.testing.assert_series_equal(legacy_indexed, block_indexed, check_names=False)


def test_block_intensity_matches_legacy(
    monkeypatch: pytest.MonkeyPatch,
    block_factor_df: pd.DataFrame,
    block_fund_flow_df: pd.DataFrame,
) -> None:
    """orchestrator 的 capital_flow_intensity ≡ calculate_capital_flow_intensity"""
    _patch_load(monkeypatch, block_fund_flow_df)

    legacy = calculate_capital_flow_intensity(block_factor_df)
    block = calculate_capital_flow_block(block_factor_df)

    legacy_indexed = legacy.set_index(["asset", "date"])["capital_flow_intensity"].sort_index()
    block_indexed = block.set_index(["asset", "date"])["capital_flow_intensity"].sort_index()

    pd.testing.assert_series_equal(legacy_indexed, block_indexed, check_names=False)


def test_block_outputs_both_factors(
    monkeypatch: pytest.MonkeyPatch,
    block_factor_df: pd.DataFrame,
    block_fund_flow_df: pd.DataFrame,
) -> None:
    """orchestrator 一次返回两列因子 + 不残留中间列"""
    _patch_load(monkeypatch, block_fund_flow_df)
    result = calculate_capital_flow_block(block_factor_df)

    # 含两个因子
    assert "capital_flow_ratio_trend" in result.columns
    assert "capital_flow_intensity" in result.columns
    # 不残留中间列
    for col in ("ratio_daily", "delta_ratio", "amount_daily", "volume_daily", "intensity"):
        assert col not in result.columns, f"中间列 {col} 未被清理"
    # 行数一致
    assert len(result) == len(block_factor_df)


def test_block_no_match_propagates_nan(
    monkeypatch: pytest.MonkeyPatch,
    block_factor_df: pd.DataFrame,
    block_fund_flow_df: pd.DataFrame,
) -> None:
    """无资金流匹配的股票（000099.SZ）所在行：
    - delta_ratio 中间值 NaN → 但同行业其他股票贡献使 industry mean 仍可计算
    - 因此 000099.SZ 的 capital_flow_ratio_trend 不一定 NaN（取决于行业其他成员）
    本测试只断言 vs legacy 的等价性（已经在 ratio_trend / intensity test 覆盖）；
    这里额外验证：行业聚合时未匹配股票不会污染同行业其他股票的因子值。
    """
    _patch_load(monkeypatch, block_fund_flow_df)
    block = calculate_capital_flow_block(block_factor_df).set_index(["asset", "date"])

    # 000001.SZ 的 ratio_trend 应该是 (000001 + 000002 同行业) Δratio 的均值
    # 2025-01-03: 000001 Δ = 0.05-0.10=-0.05; 000002 Δ = 0.15-0.20=-0.05
    # 000099.SZ Δ = NaN（无匹配）→ 行业 mean 跳过 NaN → -0.05
    val = block.loc[("000001.SZ", "2025-01-03"), "capital_flow_ratio_trend"]
    assert abs(float(val) - (-0.05)) < 1e-9, f"行业 mean 应为 -0.05, 实际 {val}"
