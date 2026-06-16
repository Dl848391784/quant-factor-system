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

    def test_partial_match_equivalence(self, small_factor_df, tail_data_file, test_logger):
        """部分行有尾盘数据时，匹配行=有效值，未匹配行=NaN（mask 路径核心）。

        构造：tail 数据只覆盖 asset A 的 2 条记录，B/C 共 4 行无尾盘数据。
        预期：A 的 2 行 5 个因子均非 NaN；B/C 的 4 行 5 个因子均为 NaN。
        """
        # 仅 A 有尾盘数据
        records = [
            _make_tail_record("2026-01-01", "A"),
            _make_tail_record("2026-01-02", "A"),
        ]
        tail_data_file(records)

        result = calculate_tail_factors(small_factor_df.copy(), logger_arg=test_logger)

        # 行数不变
        assert len(result) == len(small_factor_df)

        # A 的 2 行全部有值
        a_rows = result[result["asset"] == "A"]
        assert len(a_rows) == 2
        for col in _TAIL_FACTOR_COLS:
            nan_count = a_rows[col].isna().sum()
            assert nan_count == 0, f"asset A 行 {col} 不应有 NaN，实际 {nan_count}"

        # B/C 的 4 行全部为 NaN
        non_a_rows = result[result["asset"] != "A"]
        assert len(non_a_rows) == 4
        for col in _TAIL_FACTOR_COLS:
            nan_count = non_a_rows[col].isna().sum()
            assert nan_count == 4, f"asset B/C 行 {col} 应全部 NaN，实际 {nan_count} 个 NaN"

    def test_zero_match(self, small_factor_df, tail_data_file, test_logger):
        """tail_df 与 factor_df 完全无交集时，5 个因子均为 NaN，函数不抛异常。

        构造：tail 数据用不在 small_factor_df 里的 asset (Z) 和 date。
        """
        records = [
            _make_tail_record("2025-12-31", "Z"),  # date 和 asset 都对不上
        ]
        tail_data_file(records)

        result = calculate_tail_factors(small_factor_df.copy(), logger_arg=test_logger)

        # 行数不变
        assert len(result) == len(small_factor_df)
        # 5 个因子全部 NaN
        for col in _TAIL_FACTOR_COLS:
            nan_count = result[col].isna().sum()
            assert nan_count == len(small_factor_df), (
                f"{col} 在零匹配下应全部 NaN，实际 {nan_count}/{len(small_factor_df)}"
            )

    def test_row_order_preserved(self, small_factor_df, tail_data_file, test_logger):
        """factor_df 行序乱序时，mask 写回保持原顺序对齐。

        构造：shuffle 后的 factor_df，仅 (A, 2026-01-02) 和 (C, 2026-01-01) 有尾盘数据。
        预期：result 的 date/asset 列与 shuffled 输入一致；这两行因子有值，其余 NaN。
        """
        # shuffle (固定随机种子保证可重复)
        shuffled = small_factor_df.sample(frac=1, random_state=42).reset_index(drop=True)

        records = [
            _make_tail_record("2026-01-02", "A"),
            _make_tail_record("2026-01-01", "C"),
        ]
        tail_data_file(records)

        result = calculate_tail_factors(shuffled.copy(), logger_arg=test_logger)

        # date / asset 列与 shuffled 输入完全一致（行序保留）
        pd.testing.assert_series_equal(
            result["date"].reset_index(drop=True),
            shuffled["date"].reset_index(drop=True),
            check_names=False,
        )
        pd.testing.assert_series_equal(
            result["asset"].reset_index(drop=True),
            shuffled["asset"].reset_index(drop=True),
            check_names=False,
        )

        # 命中行：5 因子非 NaN；未命中行：5 因子 NaN
        matched_mask = ((result["date"] == "2026-01-02") & (result["asset"] == "A")) | (
            (result["date"] == "2026-01-01") & (result["asset"] == "C")
        )
        assert matched_mask.sum() == 2

        for col in _TAIL_FACTOR_COLS:
            matched_nan = result.loc[matched_mask, col].isna().sum()
            assert matched_nan == 0, f"匹配行 {col} 不应有 NaN，实际 {matched_nan}"
            unmatched_nan = result.loc[~matched_mask, col].isna().sum()
            assert unmatched_nan == 4, f"未匹配 4 行 {col} 应全部 NaN，实际 {unmatched_nan}"

    def test_limit_up_branch(self, small_factor_df, tail_data_file, test_logger):
        """涨跌停分支（v1.39）：tail_high == tail_low 时根据日线 close/high/low 判断。

        构造 3 个 asset：
        - A 的 2026-01-01：尾盘零波动 + daily close == daily high → 涨停 → position=1.0
        - B 的 2026-01-01：尾盘零波动 + daily close == daily low → 跌停 → position=0.0
        - C 的 2026-01-01：尾盘零波动 + daily close 介于 high/low 之间 → 中性 → position=0.5
        """
        # 修改 small_factor_df：让 A 涨停（close=high）、B 跌停（close=low）、C 中性
        df = small_factor_df.copy()
        # A / 2026-01-01：涨停（close == high）
        df.loc[(df["date"] == "2026-01-01") & (df["asset"] == "A"), "close"] = 10.3
        df.loc[(df["date"] == "2026-01-01") & (df["asset"] == "A"), "high"] = 10.3
        # B / 2026-01-01：跌停（close == low）
        df.loc[(df["date"] == "2026-01-01") & (df["asset"] == "B"), "close"] = 19.8
        df.loc[(df["date"] == "2026-01-01") & (df["asset"] == "B"), "low"] = 19.8
        # C / 2026-01-01：保持 close=30.0 介于 high=30.3 / low=29.8 之间 → 中性

        # 构造尾盘 13 根 K 线全相同（tail_high == tail_low，零波动）
        flat_prices_a = [10.3] * 13  # A 涨停
        flat_prices_b = [19.8] * 13  # B 跌停
        flat_prices_c = [30.0] * 13  # C 零波动但非涨跌停
        records = [
            _make_tail_record("2026-01-01", "A", prices=flat_prices_a, tail_high=10.3, tail_low=10.3),
            _make_tail_record("2026-01-01", "B", prices=flat_prices_b, tail_high=19.8, tail_low=19.8),
            _make_tail_record("2026-01-01", "C", prices=flat_prices_c, tail_high=30.0, tail_low=30.0),
        ]
        tail_data_file(records)

        result = calculate_tail_factors(df.copy(), logger_arg=test_logger)

        # 取 2026-01-01 三个 asset 的 tail_price_position
        pos = result.set_index(["date", "asset"])["tail_price_position"]
        assert pos[("2026-01-01", "A")] == pytest.approx(1.0), "A 涨停应为 1.0"
        assert pos[("2026-01-01", "B")] == pytest.approx(0.0), "B 跌停应为 0.0"
        assert pos[("2026-01-01", "C")] == pytest.approx(0.5), "C 零波动非涨跌停应为 0.5"

        # 验证零波动下 tail_price_slope = 0（mean_price=10.3, slope=0）
        slope = result.set_index(["date", "asset"])["tail_price_slope"]
        assert slope[("2026-01-01", "A")] == pytest.approx(0.0)
        assert slope[("2026-01-01", "B")] == pytest.approx(0.0)
        assert slope[("2026-01-01", "C")] == pytest.approx(0.0)
