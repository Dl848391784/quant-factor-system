"""30 分段胜率持久化模块 — Parquet 存储.

数据流:
  _render_cross_pipeline_summary 扫描 ob_quality_06XX 目录算胜率
  → save_segment_win_rates() 落库 (去重 append)
  → load_segment_win_rates() 读库渲染 Section 9
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
from paths import PROJECT_ROOT


logger = logging.getLogger(__name__)

# 默认存储路径: summary/result/segment_win_rates.parquet
_DEFAULT_PATH = PROJECT_ROOT / "summary" / "result" / "segment_win_rates.parquet"

SEGMENT_WIN_COLUMNS = [
    "pipeline",
    "selection_date",
    "trade_date",
    "weight_method",
    "n_segments",
    "n_total",
    "segment_label",
    "wins",
    "total",
    "win_rate",
    "created_at",
]


def _read_existing(file_path: Path | None = None) -> pd.DataFrame:
    """读取已有数据，不存在则返回空 DataFrame."""
    fp = file_path or _DEFAULT_PATH
    if not fp.exists():
        return pd.DataFrame(columns=SEGMENT_WIN_COLUMNS)
    try:
        return pd.read_parquet(fp)
    except Exception:
        logger.warning("读取 %s 失败，视为空表", fp, exc_info=True)
        return pd.DataFrame(columns=SEGMENT_WIN_COLUMNS)


def save_segment_win_rates(
    pipeline: str,
    selection_date: str,
    trade_date: str,
    weight_method: str,
    n_segments: int,
    n_total: int,
    seg_stats: dict[str, dict[str, Any]],
    file_path: Path | None = None,
) -> None:
    """将某个 selection_date 的 30 段胜率写入 Parquet.

    去重策略: 写入前删除同 (pipeline, selection_date, weight_method) 的旧行，
    然后 append 新行。保证同一日期重跑时覆盖而非重复。

    Args:
        pipeline: 管线名称 ('ob_quality')
        selection_date: 选股日 ('2026-06-24')
        trade_date: T+1 交易日 ('2026-06-25')
        weight_method: 权重方法 ('rolling_icir_weight')
        n_segments: 分段数 (30)
        n_total: 当日股票总数
        seg_stats: {seg_label: {wins, total, wr}} dict
        file_path: 可选自定义路径
    """
    fp = file_path or _DEFAULT_PATH
    now = datetime.now(timezone.utc).isoformat()

    rows = []
    for seg_label, stats in sorted(seg_stats.items()):
        rows.append(
            {
                "pipeline": pipeline,
                "selection_date": selection_date,
                "trade_date": trade_date,
                "weight_method": weight_method,
                "n_segments": n_segments,
                "n_total": n_total,
                "segment_label": seg_label,
                "wins": int(stats.get("wins", 0)),
                "total": int(stats.get("total", 0)),
                "win_rate": float(stats.get("wr", 0)),
                "created_at": now,
            }
        )

    new_df = pd.DataFrame(rows, columns=SEGMENT_WIN_COLUMNS)

    existing = _read_existing(fp)

    # 去重: 删除同 pipeline/selection_date/weight_method 的旧行
    if not existing.empty:
        mask = (
            (existing["pipeline"] == pipeline)
            & (existing["selection_date"] == selection_date)
            & (existing["weight_method"] == weight_method)
        )
        existing = existing[~mask]

    combined = pd.concat([existing, new_df], ignore_index=True)
    combined.to_parquet(fp, index=False)
    logger.info(
        "segment_win_rates: %s/%s 写入 %d 段 → %s (累计 %d 行)",
        pipeline,
        selection_date,
        len(rows),
        fp.name,
        len(combined),
    )


def load_segment_win_rates(
    pipeline: str,
    weight_method: str,
    file_path: Path | None = None,
) -> list[dict[str, Any]]:
    """读取指定 pipeline + weight_method 的所有分段胜率.

    Returns:
        [(selection_date, trade_date, n_total, {seg_label: {wins, total, wr}}), ...]
        按 selection_date 升序排列。
    """
    fp = file_path or _DEFAULT_PATH
    df = _read_existing(fp)
    if df.empty:
        return []

    mask = (df["pipeline"] == pipeline) & (df["weight_method"] == weight_method)
    df = df[mask]
    if df.empty:
        return []

    results = []
    for selection_date in sorted(df["selection_date"].unique()):
        day_df = df[df["selection_date"] == selection_date]
        trade_date = day_df["trade_date"].iloc[0]
        n_total = int(day_df["n_total"].iloc[0])
        seg_stats: dict[str, dict[str, Any]] = {}
        for _, row in day_df.iterrows():
            seg_stats[row["segment_label"]] = {
                "wins": int(row["wins"]),
                "total": int(row["total"]),
                "wr": float(row["win_rate"]),
            }
        results.append(
            {
                "selection_date": str(selection_date),
                "trade_date": str(trade_date),
                "n_total": n_total,
                "seg_stats": seg_stats,
            }
        )

    return results
