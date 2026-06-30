"""segment_win_db 模块单元测试."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pandas as pd
import pytest
from summary.report.segment_win_db import (
    SEGMENT_WIN_COLUMNS,
    _read_existing,
    load_segment_win_rates,
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


class TestSaveAndLoad:
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

            for d in ("0615", "0616", "0617"):
                sel = f"2026-06-{d[2:]}"
                trade = f"2026-06-{int(d[2:]) + 1:02d}"
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


class TestReadExisting:
    """_read_existing 测试."""

    def test_nonexistent(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            fp = Path(tmpdir) / "nope.parquet"
            df = _read_existing(fp)
            assert df.empty
            assert list(df.columns) == SEGMENT_WIN_COLUMNS

    def test_valid_parquet(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            fp = Path(tmpdir) / "test.parquet"
            seg_stats = _sample_seg_stats(3)
            save_segment_win_rates("test", "2026-06-30", "2026-07-01", "wr", 3, 100, seg_stats, file_path=fp)
            df = _read_existing(fp)
            assert not df.empty
            assert len(df) == 3
