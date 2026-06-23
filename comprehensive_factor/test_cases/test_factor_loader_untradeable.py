#!/usr/bin/env python3
"""factor_loader 不可交易股票过滤测试。"""

import sys
from pathlib import Path

import pandas as pd
import pytest


sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from comprehensive_factor.common.factor_loader import load_factor_values, load_full_data


def _write_test_data(path: Path, records: list[dict]) -> None:
    pd.DataFrame(records).to_parquet(path, engine="pyarrow")


@pytest.fixture
def test_data_with_untradeable(tmp_path: Path) -> Path:
    data_path = tmp_path / "test_cf_data.parquet"
    records = [
        {
            "date": "2024-01-01",
            "asset": "000001",
            "rsi_6": 50.0,
            "forward_return_1d": 0.01,
            "forward_return_3d": 0.02,
            "forward_return_5d": 0.03,
            "is_untradeable": 0,
        },
        {
            "date": "2024-01-02",
            "asset": "000001",
            "rsi_6": 55.0,
            "forward_return_1d": 0.02,
            "forward_return_3d": 0.03,
            "forward_return_5d": 0.04,
            "is_untradeable": 0,
        },
        {
            "date": "2024-01-01",
            "asset": "000002",
            "rsi_6": 60.0,
            "forward_return_1d": 0.03,
            "forward_return_3d": 0.04,
            "forward_return_5d": 0.05,
            "is_untradeable": 1,
        },
        {
            "date": "2024-01-02",
            "asset": "000002",
            "rsi_6": 80.0,
            "forward_return_1d": 0.10,
            "forward_return_3d": 0.11,
            "forward_return_5d": 0.12,
            "is_untradeable": 0,
        },
    ]
    _write_test_data(data_path, records)
    return data_path


@pytest.fixture
def test_data_without_untradeable(tmp_path: Path) -> Path:
    data_path = tmp_path / "test_cf_data_old.parquet"
    records = [
        {
            "date": "2024-01-01",
            "asset": "000001",
            "rsi_6": 50.0,
            "forward_return_1d": 0.01,
            "forward_return_3d": 0.02,
            "forward_return_5d": 0.03,
        },
    ]
    _write_test_data(data_path, records)
    return data_path


def test_load_full_data_filters_untradeable(test_data_with_untradeable):
    """load_full_data(factor_cols=[...]) 应过滤 is_untradeable=1 的行。"""
    import logging

    logger = logging.getLogger("test_cf_full")
    df = load_full_data(data_source=test_data_with_untradeable, factor_cols=["rsi_6"], logger=logger)

    # 原始 4 行, 过滤 1 行 → 3 行
    assert len(df) == 3
    # 000002 在 2024-01-01 被标记为不可交易
    mask = (df["asset"] == "000002") & (df["date"] == "2024-01-01")
    assert mask.sum() == 0


def test_load_full_data_all_cols_filters_untradeable(test_data_with_untradeable):
    """load_full_data(factor_cols=None) 应过滤 is_untradeable=1 的行。"""
    import logging

    logger = logging.getLogger("test_cf_all")
    df = load_full_data(data_source=test_data_with_untradeable, factor_cols=None, logger=logger)

    assert len(df) == 3
    mask = (df["asset"] == "000002") & (df["date"] == "2024-01-01")
    assert mask.sum() == 0


def test_load_factor_values_filters_untradeable(test_data_with_untradeable):
    """load_factor_values 应过滤 is_untradeable=1 的行。"""
    import logging

    logger = logging.getLogger("test_cf_values")
    df = load_factor_values(["rsi_6"], data_source=test_data_with_untradeable, logger=logger)

    assert len(df) == 3
    mask = (df["asset"] == "000002") & (df["date"] == "2024-01-01")
    assert mask.sum() == 0


def test_backward_compatible_without_untradeable(test_data_without_untradeable):
    """旧数据无 is_untradeable 列时不过滤。"""
    import logging

    logger = logging.getLogger("test_cf_compat")
    df = load_full_data(data_source=test_data_without_untradeable, factor_cols=["rsi_6"], logger=logger)

    assert len(df) == 1
