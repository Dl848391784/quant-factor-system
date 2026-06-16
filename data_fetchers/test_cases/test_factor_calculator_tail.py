#!/usr/bin/env python3
"""data_fetchers.factor_calculator.tail.calculate_tail_factors 测试用例。

针对 v1.43 内存优化重构（mask 子集 apply）的等价性 + 行为保护。

设计文档: .hermes/plans/fix-tail-factors-oom.md
遵循 PROJECT.md 测试代码规范：pytest + tempfile.TemporaryDirectory

作者: 云瑶
创建时间: 2026-06-16 北京时间
"""

from __future__ import annotations

import gzip
import json
import logging
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from data_fetchers.factor_calculator import tail as tail_mod
from data_fetchers.factor_calculator.tail import calculate_tail_factors


# ============================================================================
# fixtures
# ============================================================================


@pytest.fixture
def test_logger():
    """测试 logger（无 file handler，避免日志残留）"""
    logger = logging.getLogger("test_factor_calculator_tail")
    logger.setLevel(logging.DEBUG)
    return logger


def _make_tail_record(date: str, asset: str, *, prices=None, volumes=None, tail_high=None, tail_low=None):
    """构造一条尾盘 K 线记录（13 根 5 分钟线）。"""
    if prices is None:
        prices = [10.0 + i * 0.01 for i in range(13)]
    if volumes is None:
        volumes = [1000 + i * 100 for i in range(13)]
    if tail_high is None:
        tail_high = max(prices)
    if tail_low is None:
        tail_low = min(prices)
    return {
        "date": date,
        "asset": asset,
        "prices": prices,
        "volumes": volumes,
        "tail_high": tail_high,
        "tail_low": tail_low,
    }


@pytest.fixture
def tail_data_file(monkeypatch):
    """工厂 fixture：写入临时 tail_trading_data.json.gz 并 monkeypatch 路径。

    返回一个函数 ``write(records)``，接受 record list，写完后路径已生效。
    """
    tmpdir = tempfile.TemporaryDirectory()

    def _write(records: list[dict]) -> Path:
        path = Path(tmpdir.name) / "tail_trading_data.json.gz"
        payload = {"meta": {"source": "test"}, "data": records}
        with gzip.open(path, "wt", encoding="utf-8") as f:
            json.dump(payload, f)
        # 同时 patch 模块级常量（_load_tail_trading_data 闭包内引用的是模块属性）
        monkeypatch.setattr(tail_mod, "_TAIL_TRADING_DATA_PATH", path)
        return path

    yield _write
    tmpdir.cleanup()


@pytest.fixture
def small_factor_df():
    """3 asset × 2 date = 6 行的小 factor_df，含 close/high/low/volume。"""
    return pd.DataFrame(
        {
            "date": ["2026-01-01", "2026-01-02", "2026-01-01", "2026-01-02", "2026-01-01", "2026-01-02"],
            "asset": ["A", "A", "B", "B", "C", "C"],
            "close": [10.0, 10.5, 20.0, 20.5, 30.0, 30.5],
            "high": [10.3, 10.7, 20.3, 20.7, 30.3, 30.7],
            "low": [9.8, 10.2, 19.8, 20.2, 29.8, 30.2],
            "volume": [100000.0, 110000.0, 200000.0, 210000.0, 300000.0, 310000.0],
        }
    )


_TAIL_FACTOR_COLS = (
    "tail_price_position",
    "tail_price_slope",
    "tail_price_volume_intensity",
    "tail_volume_acceleration",
    "tail_volume_shrink",
)


# ============================================================================
# 等价性测试（v1.43 重构 vs 期望行为）
# ============================================================================


class TestCalculateTailFactorsEquivalence:
    """5 个等价性测试，确保 mask 子集 apply 重构与原行为一致。"""

    def test_full_match_equivalence(self, small_factor_df, tail_data_file, test_logger):
        """所有 (date, asset) 都有尾盘数据时，5 个因子均为有效值，无 NaN。"""
        # 构造 6 条尾盘记录，与 small_factor_df 全匹配
        records = []
        for _, row in small_factor_df.iterrows():
            records.append(_make_tail_record(row["date"], row["asset"]))
        tail_data_file(records)

        result = calculate_tail_factors(small_factor_df.copy(), logger_arg=test_logger)

        # 形状不变：行数 = 原 factor_df 行数
        assert len(result) == len(small_factor_df), "行数应保持不变"
        # 5 个因子列全部存在
        for col in _TAIL_FACTOR_COLS:
            assert col in result.columns, f"缺少因子列 {col}"
        # 全匹配 → 5 个因子均无 NaN
        for col in _TAIL_FACTOR_COLS:
            nan_count = result[col].isna().sum()
            assert nan_count == 0, f"{col} 全匹配下不应有 NaN，实际 {nan_count} 个"
        # 原始列保留
        for col in ["date", "asset", "close", "high", "low", "volume"]:
            assert col in result.columns
            pd.testing.assert_series_equal(
                result[col].reset_index(drop=True),
                small_factor_df[col].reset_index(drop=True),
                check_names=False,
            )
