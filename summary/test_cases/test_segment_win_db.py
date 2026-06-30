"""segment_win_db 模块单元测试."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pandas as pd
import pytest
from summary.report.segment_win_db import (
    SEGMENT_STOCK_COLUMNS,
    SEGMENT_WIN_COLUMNS,
    _read_parquet,
    load_segment_stock_details,
    load_segment_win_rates,
    save_segment_stock_details,
    save_segment_win_rates,
)


def _sample_seg_stats(n_segments: int = 30) -> dict:
    """生成示例分段胜率 dict."""
    import random

    rng = random.Random(42)
    stats = {}
    for i in range(1, n_segments + 1):
        label = f"S{i}"
        total = rng.randint(3, 10)
        wins = rng.randint(0, total)
        stats[label] = {"wins": wins, "total": total, "wr": wins / total * 100 if total > 0 else 0}
    return stats


def _sample_seg_stocks(n_segments: int = 5, stocks_per_seg: int = 3) -> dict:
    """生成示例分段股票明细 dict."""
    stocks = {}
    for i in range(1, n_segments + 1):
        label = f"S{i}"
        stocks[label] = [
            {
                "asset": f"00000{i}{j:02d}",
                "composite_value": 0.5 - i * 0.1 + j * 0.01,
                "rank": (i - 1) * stocks_per_seg + j,
            }
            for j in range(1, stocks_per_seg + 1)
        ]
    return stocks


class TestSaveAndLoadWinRates:
    """save_segment_win_rates + load_segment_win_rates 端到端测试."""

    def test_save_and_load_basic(self):
        """基本写入→读取验证."""
        with tempfile.TemporaryDirectory() as tmpdir:
            fp = Path(tmpdir) / "test.parquet"

            seg_stats = _sample_seg_stats(5)
            save_segment_win_rates(
                pipeline="ob_quality",
                selection_date="2026-06-24",
                trade_date="2026-06-25",
                weight_method="rolling_icir_weight",
                n_segments=5,
                n_total=200,
                seg_stats=seg_stats,
                file_path=fp,
            )

            results = load_segment_win_rates("ob_quality", "rolling_icir_weight", file_path=fp)
            assert len(results) == 1
            r = results[0]
            assert r["selection_date"] == "2026-06-24"
            assert r["trade_date"] == "2026-06-25"
            assert r["n_total"] == 200
            assert len(r["seg_stats"]) == 5
            assert r["seg_stats"]["S1"]["total"] > 0

    def test_dedup_overwrite(self):
        """同日期重写→去重覆盖，不重复行."""
        with tempfile.TemporaryDirectory() as tmpdir:
            fp = Path(tmpdir) / "test.parquet"

            seg_stats_a = _sample_seg_stats(5)
            save_segment_win_rates("ob_quality", "2026-06-24", "2026-06-25", "wr", 5, 200, seg_stats_a, file_path=fp)
            save_segment_win_rates("ob_quality", "2026-06-24", "2026-06-25", "wr", 5, 200, seg_stats_a, file_path=fp)

            df = pd.read_parquet(fp)
            mask = (df["pipeline"] == "ob_quality") & (df["selection_date"] == "2026-06-24")
            assert len(df[mask]) == 5, f"Expected 5 rows (deduped), got {len(df[mask])}"

    def test_multi_date(self):
        """多日期写入→全部可读."""
        with tempfile.TemporaryDirectory() as tmpdir:
            fp = Path(tmpdir) / "test.parquet"

            for d in (15, 16, 17):
                sel = f"2026-06-{d:02d}"
                trade = f"2026-06-{d + 1:02d}"
                seg_stats = _sample_seg_stats(30)
                save_segment_win_rates("ob_quality", sel, trade, "wr", 30, 250, seg_stats, file_path=fp)

            results = load_segment_win_rates("ob_quality", "wr", file_path=fp)
            assert len(results) == 3
            assert results[0]["selection_date"] == "2026-06-15"
            assert results[2]["selection_date"] == "2026-06-17"

    def test_filter_by_pipeline(self):
        """按 pipeline 过滤."""
        with tempfile.TemporaryDirectory() as tmpdir:
            fp = Path(tmpdir) / "test.parquet"

            seg_stats = _sample_seg_stats(5)
            save_segment_win_rates("ob_quality", "2026-06-24", "2026-06-25", "wr", 5, 200, seg_stats, file_path=fp)
            save_segment_win_rates("other", "2026-06-24", "2026-06-25", "wr", 5, 200, seg_stats, file_path=fp)

            r_ob = load_segment_win_rates("ob_quality", "wr", file_path=fp)
            r_other = load_segment_win_rates("other", "wr", file_path=fp)
            assert len(r_ob) == 1
            assert len(r_other) == 1

            r_none = load_segment_win_rates("nonexistent", "wr", file_path=fp)
            assert len(r_none) == 0

    def test_empty_read(self):
        """空文件/不存在→返回空列表."""
        with tempfile.TemporaryDirectory() as tmpdir:
            fp = Path(tmpdir) / "nonexistent.parquet"
            results = load_segment_win_rates("ob_quality", "wr", file_path=fp)
            assert results == []

    def test_multi_weight_method_coexist(self):
        """同日不同 weight_method 并存，互不覆盖."""
        with tempfile.TemporaryDirectory() as tmpdir:
            fp = Path(tmpdir) / "test.parquet"

            seg_stats = _sample_seg_stats(5)
            save_segment_win_rates(
                "ob_quality", "2026-06-24", "2026-06-25", "rolling_icir_weight", 5, 200, seg_stats, file_path=fp
            )
            save_segment_win_rates(
                "ob_quality", "2026-06-24", "2026-06-25", "ic_weight", 5, 200, seg_stats, file_path=fp
            )

            r_rolling = load_segment_win_rates("ob_quality", "rolling_icir_weight", file_path=fp)
            r_ic = load_segment_win_rates("ob_quality", "ic_weight", file_path=fp)
            assert len(r_rolling) == 1
            assert len(r_ic) == 1
            assert r_rolling[0]["selection_date"] == "2026-06-24"
            assert r_ic[0]["selection_date"] == "2026-06-24"


class TestSaveAndLoadStockDetails:
    """save_segment_stock_details + load_segment_stock_details 端到端测试."""

    def test_save_and_load_basic(self):
        """基本写入→读取验证 (带 weight_method)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            fp = Path(tmpdir) / "test.parquet"

            seg_stocks = _sample_seg_stocks(5, 3)
            save_segment_stock_details(
                pipeline="ob_quality",
                weight_method="rolling_icir_weight",
                selection_date="2026-06-24",
                seg_stocks=seg_stocks,
                file_path=fp,
            )

            df = load_segment_stock_details("ob_quality", file_path=fp)
            assert len(df) == 15  # 5 segments * 3 stocks
            assert "weight_method" in df.columns
            assert (df["weight_method"] == "rolling_icir_weight").all()
            assert (df["selection_date"] == "2026-06-24").all()

    def test_multi_weight_coexist(self):
        """同日不同 weight_method 并存，互不覆盖."""
        with tempfile.TemporaryDirectory() as tmpdir:
            fp = Path(tmpdir) / "test.parquet"

            seg_stocks = _sample_seg_stocks(5, 3)
            save_segment_stock_details("ob_quality", "rolling_icir_weight", "2026-06-24", seg_stocks, file_path=fp)
            save_segment_stock_details("ob_quality", "ic_weight", "2026-06-24", seg_stocks, file_path=fp)

            # 两种权重各 15 行
            df_all = load_segment_stock_details("ob_quality", file_path=fp)
            assert len(df_all) == 30

            df_rolling = load_segment_stock_details("ob_quality", weight_method="rolling_icir_weight", file_path=fp)
            assert len(df_rolling) == 15
            assert (df_rolling["weight_method"] == "rolling_icir_weight").all()

            df_ic = load_segment_stock_details("ob_quality", weight_method="ic_weight", file_path=fp)
            assert len(df_ic) == 15
            assert (df_ic["weight_method"] == "ic_weight").all()

    def test_dedup_same_weight_overwrite(self):
        """同日同 weight_method 重写→去重覆盖."""
        with tempfile.TemporaryDirectory() as tmpdir:
            fp = Path(tmpdir) / "test.parquet"

            seg_stocks = _sample_seg_stocks(5, 3)
            save_segment_stock_details("ob_quality", "rolling_icir_weight", "2026-06-24", seg_stocks, file_path=fp)
            save_segment_stock_details("ob_quality", "rolling_icir_weight", "2026-06-24", seg_stocks, file_path=fp)

            df = load_segment_stock_details("ob_quality", file_path=fp)
            assert len(df) == 15  # 去重后仍为 15

    def test_load_by_date(self):
        """按 selection_date 过滤读取."""
        with tempfile.TemporaryDirectory() as tmpdir:
            fp = Path(tmpdir) / "test.parquet"

            seg_stocks = _sample_seg_stocks(5, 3)
            save_segment_stock_details("ob_quality", "rolling_icir_weight", "2026-06-24", seg_stocks, file_path=fp)
            save_segment_stock_details("ob_quality", "rolling_icir_weight", "2026-06-25", seg_stocks, file_path=fp)

            df_24 = load_segment_stock_details("ob_quality", selection_date="2026-06-24", file_path=fp)
            assert len(df_24) == 15
            assert (df_24["selection_date"] == "2026-06-24").all()

    def test_legacy_migration_no_weight_method_column(self):
        """旧数据 (无 weight_method 列) 读取时自动补默认值."""
        with tempfile.TemporaryDirectory() as tmpdir:
            fp = Path(tmpdir) / "test.parquet"

            # 写入不含 weight_method 列的旧格式数据
            legacy_df = pd.DataFrame(
                {
                    "pipeline": ["ob_quality"] * 5,
                    "selection_date": ["2026-06-24"] * 5,
                    "segment_label": ["S1", "S2", "S3", "S4", "S5"],
                    "asset": ["000001", "000002", "000003", "000004", "000005"],
                    "composite_value": [0.1, 0.2, 0.3, 0.4, 0.5],
                    "rank": [1, 2, 3, 4, 5],
                    "created_at": ["2026-06-24T00:00:00+00:00"] * 5,
                }
            )
            legacy_df.to_parquet(fp, index=False)

            # 通过 _read_parquet 读取, 应自动补 weight_method 列
            df = _read_parquet(fp, SEGMENT_STOCK_COLUMNS)
            assert "weight_method" in df.columns
            assert (df["weight_method"] == "rolling_icir_weight").all()
            assert len(df) == 5


class TestReadExisting:
    """_read_parquet 测试."""

    def test_nonexistent(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            fp = Path(tmpdir) / "nope.parquet"
            df = _read_parquet(fp, SEGMENT_WIN_COLUMNS)
            assert df.empty
            assert list(df.columns) == SEGMENT_WIN_COLUMNS

    def test_valid_parquet(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            fp = Path(tmpdir) / "test.parquet"
            seg_stats = _sample_seg_stats(3)
            save_segment_win_rates("test", "2026-06-30", "2026-07-01", "wr", 3, 100, seg_stats, file_path=fp)
            df = _read_parquet(fp, SEGMENT_WIN_COLUMNS)
            assert not df.empty
            assert len(df) == 3
