"""综合因子每日明细 parquet 输出测试用例

遵循 designs/composite_daily_parquet_migration_design.md v2.36 改动：
- daily 明细从 json.gz 迁移到 parquet
- 列裁剪：60+ 列 → 3 列（date/asset/composite_factor）
- 移除 v2.24 流式分块写入逻辑

测试目标:
1. 文件确实写到 parquet（路径后缀 .parquet）
2. 列严格为 ["date", "asset", "composite_factor"]（核心约束：防止后续误把 factor_cols 加回 output_cols）
3. composite_factor dtype 为 float64
4. 行数与输入一致（无 silent drop）
5. 读取后内容与写入一致
6. 缺少必需列时抛 ValueError
7. 输入含额外列（factor_cols）时被裁剪掉

创建日期: 2026-06-23
"""

import logging

import numpy as np
import pandas as pd
import pytest
from comprehensive_factor.common.composite_runner import _save_composite_daily


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def sample_factor_df() -> pd.DataFrame:
    """构造最小 factor_df：3 天 × 2 股票 × 4 列（其中 1 列应被裁剪）"""
    return pd.DataFrame(
        {
            "date": ["2026-01-01", "2026-01-01", "2026-01-02", "2026-01-02", "2026-01-03", "2026-01-03"],
            "asset": ["600519.SH", "000001.SZ"] * 3,
            "composite_factor": [0.1, 0.2, 0.3, 0.4, 0.5, 0.6],
            "rsi_6_std": [1.0] * 6,  # 额外列，必须被裁剪掉
        }
    )


@pytest.fixture
def logger() -> logging.Logger:
    return logging.getLogger("test_composite_daily_parquet")


# ============================================================================
# 正向用例
# ============================================================================


def test_daily_file_uses_parquet_extension(tmp_path, sample_factor_df, logger):
    """文件后缀必须是 .parquet（v2.36 核心契约）。"""
    daily_file = _save_composite_daily(
        sample_factor_df, tmp_path, weight_method="icir", return_period="1d", logger=logger
    )

    assert daily_file.suffix == ".parquet"
    assert daily_file.name == "composite_icir_1d_daily.parquet"
    assert daily_file.exists()


def test_daily_columns_strictly_three(tmp_path, sample_factor_df, logger):
    """列严格为 [date, asset, composite_factor]：防止后续误把 factor_cols 加回 output_cols。"""
    daily_file = _save_composite_daily(
        sample_factor_df, tmp_path, weight_method="icir", return_period="1d", logger=logger
    )

    loaded = pd.read_parquet(daily_file)
    assert list(loaded.columns) == ["date", "asset", "composite_factor"]
    # 确认 rsi_6_std 被裁剪
    assert "rsi_6_std" not in loaded.columns


def test_daily_composite_factor_is_float64(tmp_path, sample_factor_df, logger):
    """composite_factor dtype 必须是 float64（不能被 parquet 编码意外降级）。"""
    daily_file = _save_composite_daily(
        sample_factor_df, tmp_path, weight_method="ic", return_period="1d", logger=logger
    )

    loaded = pd.read_parquet(daily_file)
    assert loaded["composite_factor"].dtype == np.float64


def test_daily_row_count_preserved(tmp_path, sample_factor_df, logger):
    """行数必须与输入一致（无 silent drop）。"""
    daily_file = _save_composite_daily(
        sample_factor_df, tmp_path, weight_method="equal", return_period="1d", logger=logger
    )

    loaded = pd.read_parquet(daily_file)
    assert len(loaded) == len(sample_factor_df)


def test_daily_content_round_trip(tmp_path, sample_factor_df, logger):
    """写入后读取的数据与输入（裁剪后）一致。"""
    daily_file = _save_composite_daily(
        sample_factor_df, tmp_path, weight_method="rolling_icir", return_period="1d", logger=logger
    )

    loaded = pd.read_parquet(daily_file)
    expected = sample_factor_df[["date", "asset", "composite_factor"]].reset_index(drop=True)
    pd.testing.assert_frame_equal(loaded, expected)


def test_daily_filename_uses_weight_method_and_return_period(tmp_path, sample_factor_df, logger):
    """文件名格式：composite_{weight_method}_{return_period}_daily.parquet"""
    daily_file = _save_composite_daily(
        sample_factor_df, tmp_path, weight_method="rolling_icir", return_period="5d", logger=logger
    )

    assert daily_file.name == "composite_rolling_icir_5d_daily.parquet"


# ============================================================================
# 反向用例
# ============================================================================


def test_missing_composite_factor_raises(tmp_path, logger):
    """缺 composite_factor 列必须抛 ValueError，错误信息含缺失列名 + 当前列列表。"""
    df = pd.DataFrame(
        {
            "date": ["2026-01-01"],
            "asset": ["600519.SH"],
            # 故意缺 composite_factor
        }
    )

    with pytest.raises(ValueError, match="缺少 daily 输出必需列"):
        _save_composite_daily(df, tmp_path, weight_method="icir", return_period="1d", logger=logger)


def test_missing_date_raises(tmp_path, logger):
    """缺 date 列也必须抛 ValueError。"""
    df = pd.DataFrame(
        {
            "asset": ["600519.SH"],
            "composite_factor": [0.1],
        }
    )

    with pytest.raises(ValueError, match="缺少 daily 输出必需列"):
        _save_composite_daily(df, tmp_path, weight_method="icir", return_period="1d", logger=logger)


def test_missing_asset_raises(tmp_path, logger):
    """缺 asset 列也必须抛 ValueError。"""
    df = pd.DataFrame(
        {
            "date": ["2026-01-01"],
            "composite_factor": [0.1],
        }
    )

    with pytest.raises(ValueError, match="缺少 daily 输出必需列"):
        _save_composite_daily(df, tmp_path, weight_method="icir", return_period="1d", logger=logger)
