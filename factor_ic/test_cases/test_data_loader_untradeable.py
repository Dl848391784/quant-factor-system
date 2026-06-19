#!/usr/bin/env python3
"""data_loader 不可交易股票过滤测试。

测试 load_factor_return_data 在加载含 is_untradeable 列的数据时，
正确过滤 is_untradeable=1 的行。
"""

import gzip
import json
import sys
from pathlib import Path

import pandas as pd
import pytest


sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from factor_ic.common.data_loader import load_factor_return_data


def _write_test_data(path: Path, records: list[dict]) -> None:
    """写入测试用的 gzip JSON 数据文件。"""
    with gzip.open(path, "wt", encoding="utf-8") as f:
        json.dump({"data": records, "meta": {"date_range": {"start": "2024-01-01", "end": "2024-01-02"}}}, f)


@pytest.fixture
def test_data_with_untradeable(tmp_path: Path) -> Path:
    """构造含 is_untradeable 列的测试数据。"""
    data_path = tmp_path / "test_data.json.gz"
    records = [
        # 000001: T-1 正常, T 正常
        {"date": "2024-01-01", "asset": "000001", "rsi_6": 50.0, "forward_return_1d": 0.01, "is_untradeable": 0},
        {"date": "2024-01-02", "asset": "000001", "rsi_6": 55.0, "forward_return_1d": 0.02, "is_untradeable": 0},
        # 000002: T-1 正常, T 涨停不可交易
        {"date": "2024-01-01", "asset": "000002", "rsi_6": 60.0, "forward_return_1d": 0.03, "is_untradeable": 0},
        {"date": "2024-01-02", "asset": "000002", "rsi_6": 80.0, "forward_return_1d": 0.10, "is_untradeable": 1},
        # 000003: T-1 涨停不可交易, T 正常
        {"date": "2024-01-01", "asset": "000003", "rsi_6": 90.0, "forward_return_1d": 0.05, "is_untradeable": 1},
        {"date": "2024-01-02", "asset": "000003", "rsi_6": 45.0, "forward_return_1d": -0.01, "is_untradeable": 0},
    ]
    _write_test_data(data_path, records)
    return data_path


@pytest.fixture
def test_data_without_untradeable(tmp_path: Path) -> Path:
    """构造不含 is_untradeable 列的旧数据（向后兼容测试）。"""
    data_path = tmp_path / "test_data_old.json.gz"
    records = [
        {"date": "2024-01-01", "asset": "000001", "rsi_6": 50.0, "forward_return_1d": 0.01},
        {"date": "2024-01-02", "asset": "000001", "rsi_6": 55.0, "forward_return_1d": 0.02},
    ]
    _write_test_data(data_path, records)
    return data_path


def test_untradeable_rows_filtered(test_data_with_untradeable, caplog):
    """is_untradeable=1 的行应被过滤。"""
    import logging

    logger = logging.getLogger("test_untradeable_filter")
    factor_df, return_df, _ = load_factor_return_data(
        factor_cols=["rsi_6"],
        data_cache_path=test_data_with_untradeable,
        logger=logger,
    )

    # 原始 6 行, 过滤 2 行 is_untradeable=1 → 4 行
    assert len(factor_df) == 4
    assert len(return_df) == 4

    # 确认被过滤的行不在结果中
    # 000002 在 2024-01-02 被标记为不可交易
    mask = (factor_df["asset"] == "000002") & (factor_df["date"] == "2024-01-02")
    assert mask.sum() == 0

    # 000003 在 2024-01-01 被标记为不可交易
    mask = (factor_df["asset"] == "000003") & (factor_df["date"] == "2024-01-01")
    assert mask.sum() == 0


def test_backward_compatible_without_untradeable(test_data_without_untradeable, caplog):
    """旧数据无 is_untradeable 列时不过滤，输出 warning。"""
    import logging

    logger = logging.getLogger("test_backward_compat")
    factor_df, return_df, _ = load_factor_return_data(
        factor_cols=["rsi_6"],
        data_cache_path=test_data_without_untradeable,
        logger=logger,
    )

    # 旧数据 2 行, 不过滤
    assert len(factor_df) == 2
    assert len(return_df) == 2
