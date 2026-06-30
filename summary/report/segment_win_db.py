"""30 分段胜率 + 股票明细持久化模块 — Parquet 存储.

两张表:
  segment_stock_details.parquet  — T 日 ob_quality 管线写 (30 段 × N 只股票)
  segment_win_rates.parquet      — T+1 日读到 forward_return_1d 后算胜率写入

数据流:
  ob_quality* 管线 report 阶段:
    → save_segment_stock_details()   写 stock_details (不等收益)
    → compute_and_save_win_rates()   读 stock_details → 有 forward_return_1d 就算胜率 → 写 win_rates

  主管线 Section 9:
    → load_segment_win_rates() 纯读 win_rates 渲染
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
from paths import PROJECT_ROOT


logger = logging.getLogger(__name__)

# ── 路径 ──────────────────────────────────────────────────────────────
_RESULT_DIR = PROJECT_ROOT / "summary" / "result"
_WIN_RATES_PATH = _RESULT_DIR / "segment_win_rates.parquet"
_STOCK_DETAILS_PATH = _RESULT_DIR / "segment_stock_details.parquet"

# ── 列定义 ────────────────────────────────────────────────────────────
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

SEGMENT_STOCK_COLUMNS = [
    "pipeline",
    "weight_method",
    "selection_date",
    "segment_label",
    "asset",
    "composite_value",
    "rank",
    "created_at",
]

# 旧数据迁移: 无 weight_method 列时补的默认值
_LEGACY_DEFAULT_WEIGHT_METHOD = "rolling_icir_weight"

# ══════════════════════════════════════════════════════════════════════
# segment_stock_details — T 日写入, 不等收益
# ══════════════════════════════════════════════════════════════════════


def save_segment_stock_details(
    pipeline: str,
    weight_method: str,
    selection_date: str,
    seg_stocks: dict[str, list[dict[str, Any]]],
    file_path: Path | None = None,
) -> None:
    """写入某日的 30 段股票明细 (不等收益).

    Args:
        pipeline: 'ob_quality'
        weight_method: 'rolling_icir_weight'
        selection_date: '2026-06-29'
        seg_stocks: {seg_label: [{asset, composite_value, rank}, ...]}
    """
    fp = file_path or _STOCK_DETAILS_PATH
    now = datetime.now(timezone.utc).isoformat()

    rows = []
    for seg_label, stocks in seg_stocks.items():
        for s in stocks:
            rows.append(
                {
                    "pipeline": pipeline,
                    "weight_method": weight_method,
                    "selection_date": selection_date,
                    "segment_label": seg_label,
                    "asset": str(s["asset"]),
                    "composite_value": float(s["composite_value"]),
                    "rank": int(s["rank"]),
                    "created_at": now,
                }
            )

    new_df = pd.DataFrame(rows, columns=SEGMENT_STOCK_COLUMNS)

    existing = _read_parquet(fp, SEGMENT_STOCK_COLUMNS)
    if not existing.empty:
        mask = (
            (existing["pipeline"] == pipeline)
            & (existing["weight_method"] == weight_method)
            & (existing["selection_date"] == selection_date)
        )
        existing = existing[~mask]

    combined = pd.concat([existing, new_df], ignore_index=True)
    combined.to_parquet(fp, index=False)
    logger.info(
        "segment_stock_details: %s/%s/%s 写入 %d 只 → %s (累计 %d 行)",
        pipeline,
        weight_method,
        selection_date,
        len(rows),
        fp.name,
        len(combined),
    )


def load_segment_stock_details(
    pipeline: str,
    selection_date: str | None = None,
    weight_method: str | None = None,
    file_path: Path | None = None,
) -> pd.DataFrame:
    """读取股票明细.

    Args:
        pipeline: 'ob_quality'
        selection_date: 指定日期, None 返回全部
        weight_method: 指定权重方法, None 返回全部
    Returns:
        DataFrame with SEGMENT_STOCK_COLUMNS
    """
    fp = file_path or _STOCK_DETAILS_PATH
    df = _read_parquet(fp, SEGMENT_STOCK_COLUMNS)
    if df.empty:
        return df
    df = df[df["pipeline"] == pipeline]
    if selection_date:
        df = df[df["selection_date"] == selection_date]
    if weight_method:
        df = df[df["weight_method"] == weight_method]
    return df


# ══════════════════════════════════════════════════════════════════════
# segment_win_rates — T+1 算完胜率写入
# ══════════════════════════════════════════════════════════════════════


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

    去重策略: 写入前删除同 (pipeline, selection_date, weight_method) 旧行.
    """
    fp = file_path or _WIN_RATES_PATH
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

    existing = _read_parquet(fp, SEGMENT_WIN_COLUMNS)
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
        [{selection_date, trade_date, n_total, seg_stats: {seg_label: {wins, total, wr}}}]
    """
    fp = file_path or _WIN_RATES_PATH
    df = _read_parquet(fp, SEGMENT_WIN_COLUMNS)
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


# ══════════════════════════════════════════════════════════════════════
# 内部工具
# ══════════════════════════════════════════════════════════════════════


def _read_parquet(file_path: Path, columns: list[str]) -> pd.DataFrame:
    """读取 Parquet，不存在或出错返回空 DataFrame.

    旧数据迁移: 若文件缺少 weight_method 列（SEGMENT_STOCK_COLUMNS 场景），
    补默认值 _LEGACY_DEFAULT_WEIGHT_METHOD，保证向后兼容。
    """
    if not file_path.exists():
        return pd.DataFrame(columns=columns)
    try:
        df = pd.read_parquet(file_path)
    except Exception:
        logger.warning("读取 %s 失败，视为空表", file_path, exc_info=True)
        return pd.DataFrame(columns=columns)

    # 旧数据迁移: stock_details 缺 weight_method 列时补默认值
    if "weight_method" in columns and "weight_method" not in df.columns:
        logger.info("旧数据迁移: %s 缺 weight_method 列, 补默认值 %s", file_path.name, _LEGACY_DEFAULT_WEIGHT_METHOD)
        df["weight_method"] = _LEGACY_DEFAULT_WEIGHT_METHOD

    return df
