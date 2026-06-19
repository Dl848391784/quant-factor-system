#!/usr/bin/env python3
"""backtest load_factor_return_data 不可交易股票过滤测试。"""

import gzip
import json
import sys
from pathlib import Path

import pytest


sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from backtest.common.layered_backtest_runner import load_factor_return_data


def _write_test_data(path: Path, records: list[dict]) -> None:
    with gzip.open(path, "wt", encoding="utf-8") as f:
        json.dump({"data": records, "meta": {}}, f)


@pytest.fixture
def test_data_with_untradeable(tmp_path: Path) -> Path:
    data_path = tmp_path / "test_bt_data.json.gz"
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
    data_path = tmp_path / "test_bt_data_old.json.gz"
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


def test_untradeable_rows_filtered(test_data_with_untradeable):
    """is_untradeable=1 的行应被过滤。"""
    import logging

    logger = logging.getLogger("test_bt_untradeable")
    factor_df, return_df = load_factor_return_data(
        data_source=test_data_with_untradeable,
        required_factor_cols=["rsi_6"],
        logger=logger,
    )

    # 原始 4 行, 过滤 1 行 is_untradeable=1 → 3 行
    assert len(factor_df) == 3
    assert len(return_df) == 3

    # 000002 在 2024-01-01 被标记为不可交易
    mask = (factor_df["asset"] == "000002") & (factor_df["date"] == "2024-01-01")
    assert mask.sum() == 0


def test_backward_compatible_without_untradeable(test_data_without_untradeable):
    """旧数据无 is_untradeable 列时不过滤。"""
    import logging

    logger = logging.getLogger("test_bt_backward")
    factor_df, return_df = load_factor_return_data(
        data_source=test_data_without_untradeable,
        required_factor_cols=["rsi_6"],
        logger=logger,
    )

    assert len(factor_df) == 1
    assert len(return_df) == 1
