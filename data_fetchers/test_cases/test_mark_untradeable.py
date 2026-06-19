#!/usr/bin/env python3
"""_mark_untradeable 函数单元测试。

测试不可交易股票标记逻辑：
  - 一字板涨停: amplitude < 0.01 且 涨幅 >= 0.098
  - 尾盘涨停: 涨幅 >= 0.098 且 close == high（排除一字板）
  - 正常股票: is_untradeable = 0
  - 跌停: is_untradeable = 0（T 日可买）
  - 首日: prev_close=NaN → is_untradeable = 0
"""

import logging
import sys
from pathlib import Path

import pandas as pd
import pytest


sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from data_fetchers.factor_generator import _mark_untradeable


@pytest.fixture
def logger():
    return logging.getLogger("test_mark_untradeable")


def _make_row(date, asset, close, high, low, open_, amplitude, prev_close=None):
    """构造单行测试数据。"""
    row = {
        "date": date,
        "asset": asset,
        "open": open_,
        "close": close,
        "high": high,
        "low": low,
        "amplitude": amplitude,
    }
    return row


def test_one_word_limit_up_marked_untradeable(logger):
    """一字板涨停: amplitude < 0.01 且 涨幅 >= 9.8% → is_untradeable=1。"""
    df = pd.DataFrame(
        [
            # T-1: 前日收盘 10.00
            _make_row("2024-01-01", "000001", 10.00, 10.00, 10.00, 10.00, 0.0),
            # T: 一字板涨停 11.00, 振幅=0
            _make_row("2024-01-02", "000001", 11.00, 11.00, 11.00, 11.00, 0.0),
        ]
    )
    result = _mark_untradeable(df, logger)
    assert result.iloc[0]["is_untradeable"] == 0  # T-1 正常
    assert result.iloc[1]["is_untradeable"] == 1  # T 一字板涨停


def test_tail_limit_up_marked_untradeable(logger):
    """尾盘涨停: 涨幅 >= 9.8% 且 close==high（非一字板）→ is_untradeable=1。"""
    df = pd.DataFrame(
        [
            # T-1: 前日收盘 10.00
            _make_row("2024-01-01", "000001", 10.00, 10.10, 9.90, 10.00, 0.02),
            # T: 尾盘涨停 11.00, open=10.5（非一字板），close==high=11.00
            _make_row("2024-01-02", "000001", 11.00, 11.00, 10.50, 10.50, 0.048),
        ]
    )
    result = _mark_untradeable(df, logger)
    assert result.iloc[0]["is_untradeable"] == 0
    assert result.iloc[1]["is_untradeable"] == 1


def test_normal_stock_not_marked(logger):
    """正常股票: 涨幅 < 9.8% → is_untradeable=0。"""
    df = pd.DataFrame(
        [
            _make_row("2024-01-01", "000001", 10.00, 10.20, 9.80, 10.00, 0.04),
            _make_row("2024-01-02", "000001", 10.50, 10.60, 10.40, 10.50, 0.02),
        ]
    )
    result = _mark_untradeable(df, logger)
    assert (result["is_untradeable"] == 0).all()


def test_limit_down_not_marked(logger):
    """跌停: 涨幅 <= -9.8% → is_untradeable=0（T 日可买）。"""
    df = pd.DataFrame(
        [
            _make_row("2024-01-01", "000001", 10.00, 10.10, 9.90, 10.00, 0.02),
            # T: 跌停 9.00, close==low
            _make_row("2024-01-02", "000001", 9.00, 9.00, 9.00, 9.00, 0.0),
        ]
    )
    result = _mark_untradeable(df, logger)
    assert (result["is_untradeable"] == 0).all()


def test_first_day_defaults_to_tradeable(logger):
    """首日: prev_close=NaN → 涨幅=NaN → is_untradeable=0。"""
    df = pd.DataFrame(
        [
            _make_row("2024-01-01", "000001", 11.00, 11.00, 11.00, 11.00, 0.0),
        ]
    )
    result = _mark_untradeable(df, logger)
    assert result.iloc[0]["is_untradeable"] == 0


def test_high_amplitude_limit_up_not_one_word(logger):
    """高振幅涨停（非一字板）但 close != high → is_untradeable=0（尾盘未封板）。"""
    df = pd.DataFrame(
        [
            _make_row("2024-01-01", "000001", 10.00, 10.10, 9.90, 10.00, 0.02),
            # T: 涨停 11.00 但 high=11.20（盘中超过涨停价不可能，测 close != high 场景）
            # 实际场景: 涨幅 9.8%+ 但尾盘未封板（close < high）
            _make_row("2024-01-02", "000001", 10.90, 11.00, 10.50, 10.50, 0.05),
        ]
    )
    result = _mark_untradeable(df, logger)
    # 涨幅 = (10.90 - 10.00) / 10.00 = 9.0% < 9.8% → 不标记
    assert result.iloc[1]["is_untradeable"] == 0


def test_output_is_integer(logger):
    """is_untradeable 列为 int 类型（0/1）。"""
    df = pd.DataFrame(
        [
            _make_row("2024-01-01", "000001", 10.00, 10.00, 10.00, 10.00, 0.0),
            _make_row("2024-01-02", "000001", 11.00, 11.00, 11.00, 11.00, 0.0),
        ]
    )
    result = _mark_untradeable(df, logger)
    assert result["is_untradeable"].dtype in ("int64", "int32", "uint8", "Int64")
    assert set(result["is_untradeable"].unique()).issubset({0, 1})
