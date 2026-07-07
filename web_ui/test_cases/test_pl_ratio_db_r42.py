"""v0.4.8 R42 v2 + R43 方向 A 单元测试: load_pl_ratio_trend() 在真实 parquet 上跑通.

§18.1f v1.5.12 实战锚点: 改算法 + 改数据源后, 必须用真实 parquet 跑一次
确认返回结构 + 数值合理. 不允许只 mock 测试.

R43 方向 A 改动: _MASTER_PARQUET_PATH 从 ob_quality alias (32 MB) 改到
FACTOR_IC_DATA_MASTER 全市场 (558 MB). 测试用真实 parquet 验证.

测试场景:
1. 真实 ssd + master parquet 跑通 → 返回非 None, 含 30 段 × N 选股日
2. ssd 不存在 → 返回 None
3. weight_method 不匹配 → 返回 None
"""

from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd
import pytest
from paths import PROJECT_ROOT
from web_ui.common.pl_ratio_db import (
    _MASTER_PARQUET_PATH,
    _SEGMENT_STOCK_DETAILS_PATH,
    load_pl_ratio_trend,
)


SSD_PATH = Path(_SEGMENT_STOCK_DETAILS_PATH)
MASTER_PATH = Path(_MASTER_PARQUET_PATH)


@pytest.mark.skipif(not SSD_PATH.exists(), reason="ssd parquet 不存在, 跳过实测")
@pytest.mark.skipif(not MASTER_PATH.exists(), reason="master parquet 不存在, 跳过实测")
def test_load_pl_ratio_trend_runs_on_real_parquet():
    """R42 v2 + R43 方向 A 主路径: 真实 parquet 上能跑通, 返回结构符合契约."""
    logger = logging.getLogger(__name__)
    result = load_pl_ratio_trend(n_recent_dates=12, weight_method="rolling_icir_weight", logger=logger)

    assert result is not None, "真实 parquet 都存在, 不应返回 None"
    assert set(result.keys()) >= {"dates", "segments", "avg_line", "source"}
    assert result["source"] == "summary_segment_stock_details_plus_master"  # R43 方向 A 标识

    # 段数 = 30
    assert len(result["segments"]) == 30, f"应 30 段, 实际 {len(result['segments'])}"

    # 段 label S1~S30
    labels = [s["label"] for s in result["segments"]]
    assert labels == [f"S{i}" for i in range(1, 31)], f"段 label 顺序错: {labels}"

    # 日期数 <= 12
    n_dates = len(result["dates"])
    assert 0 < n_dates <= 12, f"日期数应在 (0, 12], 实际 {n_dates}"

    # 每段 pl_ratios 长度 = 日期数
    for seg in result["segments"]:
        assert len(seg["pl_ratios"]) == n_dates, f"{seg['label']} pl_ratios 长度不匹配"

    # avg_line 长度 = 日期数
    assert len(result["avg_line"]) == n_dates, f"avg_line 长度不匹配, {len(result['avg_line'])} vs {n_dates}"

    # seg_return_pct 数值合理 (单位 %, 通常 -10 ~ +10)
    for seg in result["segments"]:
        for v in seg["pl_ratios"]:
            assert -20.0 <= v <= 20.0, f"{seg['label']} seg_return_pct={v} 异常"


def test_load_pl_ratio_trend_returns_none_when_ssd_missing(tmp_path, monkeypatch):
    """R42 v2: ssd parquet 不存在时返回 None (无 fallback)."""
    # monkeypatch 让 ssd 路径指向不存在的路径
    import web_ui.common.pl_ratio_db as mod

    monkeypatch.setattr(mod, "_SEGMENT_STOCK_DETAILS_PATH", tmp_path / "nonexistent.parquet")

    result = load_pl_ratio_trend(logger=logging.getLogger(__name__))
    assert result is None, "ssd 不存在应返回 None"


def test_load_pl_ratio_trend_returns_none_when_weight_method_mismatch():
    """R42 v2: weight_method 过滤无匹配 → 返回 None."""
    logger = logging.getLogger(__name__)
    result = load_pl_ratio_trend(
        n_recent_dates=12,
        weight_method="non_existent_weight_method",
        logger=logger,
    )
    assert result is None, "weight_method 不匹配应返回 None"
