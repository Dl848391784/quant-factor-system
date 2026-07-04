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
# segment_intraday_strategy — 每日 S6 段日内操作建议 (T+1 开盘时)
# ══════════════════════════════════════════════════════════════════════
#
# 数据流:
#   generate_factor_summary_report.py 主调度
#     → compute_intraday_strategy() 计算 + 落盘
#     → load_intraday_strategy_recommendation() 报告渲染时读
#     → _render_intraday_strategy_section() 输出 §10 表格
#
# 算法依据:
#   factor-development/references/t1-alignment-and-segment-winrate-analysis.md §7.7/§7.8
#   - gap > +0.5%  → sell_at_open (9:25 集合竞价卖, 历史 100%)
#   - gap < -0.5%  → wait_bounce (等盘中反弹回 D 日收盘价, 历史 92.3%)
#   - 复权异常股   → data_abnormal (强制 monitor, 不自动建议)
#
# 关键 fix (2026-06-30 user 抓出):
#   不要用 forward_return_1d 反推前收 (001339 类复权股会给出 -15% 假跳空).
#   一律用 T 日真实 close[T] 作为 prev_close.

# ── 路径 ──────────────────────────────────────────────────────────────
_INTRADAY_STRATEGY_PATH = _RESULT_DIR / "segment_intraday_strategy.parquet"

# ── 列定义 ────────────────────────────────────────────────────────────
INTRADAY_STRATEGY_COLUMNS = [
    "pipeline",
    "weight_method",
    "selection_date",
    "trade_date",
    "segment_label",
    "asset",
    "rank",
    "composite_value",
    "prev_close",
    "open",
    "high",
    "low",
    "close",
    "forward_return_1d",
    "real_gap_pct",
    "open_signal",
    "recommended_action",
    "expected_return_pct",
    "stop_loss_price",
    "adjustment_abnormal",
    "created_at",
]  # noqa: E501

# ── 阈值常量 (硬编码, 显式标注, 来源: §7.7/§7.8 历史 8 天 31 只验证) ──
_GAP_LOWER_THRESHOLD = -0.5  # gap < -0.5% 视为低开
_GAP_UPPER_THRESHOLD = 0.5  # gap > +0.5% 视为高开
_ADJUSTMENT_ABNORMAL_GAP = 10.0  # |gap| > 10% 视为复权异常 (001339 类)
_STOP_LOSS_PCT_FROM_COST = 0.02  # 反向突破成本价 2% 强制止损

# 历史期望收益 (N=18 低开 + N=10 高开 实测均值, 用于报告说明文字)
_HISTORICAL_LOW_EXPECTED_PCT = 2.18  # 等高卖均收
_HISTORICAL_HIGH_EXPECTED_PCT = 2.18  # 开盘卖均收
_HISTORICAL_WAIT_BOUNCE_HIT_RATE = 92.3  # 反抽率 (%)

# ══════════════════════════════════════════════════════════════════════


def compute_intraday_strategy(
    pipeline: str,
    weight_method: str,
    selection_date: str,
    logger: logging.Logger,
    segment_label: str = "S6",
    factor_data_path: Path | None = None,
    stock_details_path: Path | None = None,
) -> pd.DataFrame | None:
    """计算某日指定段的日内操作建议并写入 parquet.

    Args:
        pipeline: 'ob_quality' (固定)
        weight_method: 'rolling_icir_weight' / 'equal_weight' 等
        selection_date: 选股日 T (YYYY-MM-DD), 即 composite 计算日
        logger: 日志记录器
        segment_label: 段标签 (默认 "S6", 通常传 §9 算出的合并胜率最高段, 如 "S6" / "S7" / "S9")
        factor_data_path: 主数据源 (factor_ic_data.parquet), 默认从 paths 读
        stock_details_path: 段明细 parquet, 默认从 paths 读

    Returns:
        DataFrame (按 INTRADAY_STRATEGY_COLUMNS) or None if 数据缺失
    """
    from paths import FACTOR_IC_DATA_MASTER

    master_path = factor_data_path or FACTOR_IC_DATA_MASTER
    details_path = stock_details_path or _STOCK_DETAILS_PATH

    # 1. 读指定段明细
    details_df = _read_parquet(details_path, SEGMENT_STOCK_COLUMNS)
    if details_df.empty:
        logger.warning("segment_stock_details 为空, 跳过 intraday strategy")
        return None
    s6 = details_df.loc[
        (details_df["selection_date"] == selection_date)
        & (details_df["segment_label"] == segment_label)
        & (details_df["weight_method"] == weight_method),
        ["asset", "composite_value", "rank"],
    ].drop_duplicates()
    if s6.empty:
        logger.warning(
            "%s/%s/%s 无明细 (%s), 跳过 intraday strategy",
            pipeline,
            weight_method,
            segment_label,
            selection_date,
        )
        return None

    # 2. 读主数据源日期列, 计算 trade_date (T+1)
    try:
        all_dates = sorted(pd.read_parquet(master_path, columns=["date"])["date"].dropna().astype(str).unique())
    except Exception:
        logger.exception("读 master 日期列表失败, 跳过 intraday strategy")
        return None
    if selection_date not in all_dates:
        logger.warning("selection_date %s 不在主数据源, 跳过", selection_date)
        return None
    idx = all_dates.index(selection_date)
    if idx + 1 >= len(all_dates):
        logger.warning("selection_date %s 是最新日, 无 T+1, 跳过", selection_date)
        return None
    trade_date = all_dates[idx + 1]

    # 3. 读 T 日 close + T+1 日 OHLC (一次性只读必要列)
    try:
        ohlc = pd.read_parquet(
            master_path,
            columns=["date", "asset", "open", "high", "low", "close", "forward_return_1d"],
        )
    except Exception:
        logger.exception("读 master OHLC 失败, 跳过 intraday strategy")
        return None

    day_t = ohlc.loc[ohlc["date"].astype(str) == selection_date, ["asset", "close"]].rename(
        columns={"close": "prev_close"}
    )

    day_t1 = ohlc.loc[
        ohlc["date"].astype(str) == trade_date,
        ["asset", "open", "high", "low", "close", "forward_return_1d"],
    ]

    # 4. 合并: S6 段明细 ↔ D 日 prev_close ↔ D+1 日 OHLC
    merged = s6.merge(day_t, on="asset", how="left").merge(day_t1, on="asset", how="left")
    key_cols = ["prev_close", "open", "high", "low", "close"]
    na_mask = merged[key_cols].isna().any(axis=1)
    if bool(na_mask.any()):
        na_assets = merged.loc[na_mask, "asset"].tolist()
        logger.warning(
            "%s %s 段 %d 只缺 OHLC 数据 (%s...), 已剔除",
            selection_date,
            segment_label,
            len(na_assets),
            na_assets[:3],
        )
        merged = merged.dropna(subset=key_cols)

    if merged.empty:
        logger.warning("%s 合并后无有效股票, 跳过", selection_date)
        return None

    # 5. real_gap_pct = (open - prev_close) / prev_close * 100
    # 关键 fix: 用真实 close[T], 不用 forward_return_1d 反推 (会因复权失真)
    merged = merged.assign(
        real_gap_pct=lambda d: (d["open"] - d["prev_close"]) / d["prev_close"] * 100,
    )

    # 6. open_signal 分桶 + adjustment_abnormal 标记
    def classify(row: pd.Series) -> tuple[str, bool]:
        gap = float(row["real_gap_pct"])
        abnormal = abs(gap) > _ADJUSTMENT_ABNORMAL_GAP
        if abnormal:
            return ("abnormal", True)
        if gap > _GAP_UPPER_THRESHOLD:
            return ("high", False)
        if gap < _GAP_LOWER_THRESHOLD:
            return ("low", False)
        return ("flat", False)

    classes = merged.apply(classify, axis=1)
    signal_series = classes.apply(lambda x: x[0])
    abnormal_series = classes.apply(lambda x: bool(x[1]))
    merged = merged.assign(
        open_signal=signal_series,
        adjustment_abnormal=abnormal_series,
    )

    # 7. recommended_action + expected_return + stop_loss_price
    def recommend(row: pd.Series) -> tuple[str, float, float]:
        sig = str(row["open_signal"])
        if sig == "high":
            eret = (float(row["open"]) - float(row["prev_close"])) / float(row["prev_close"]) * 100
            return ("sell_at_open", float(eret), 0.0)
        if sig == "low":
            stop_loss = round(float(row["prev_close"]) * (1 - _STOP_LOSS_PCT_FROM_COST), 4)
            return ("wait_bounce", _HISTORICAL_LOW_EXPECTED_PCT, stop_loss)
        if sig == "abnormal":
            return ("monitor", 0.0, 0.0)
        # flat: 样本不足, 给中性期望 (告知用户无强规律)
        return ("monitor", 0.0, 0.0)

    recs = merged.apply(recommend, axis=1)
    merged = merged.assign(
        recommended_action=recs.apply(lambda x: x[0]),
        expected_return_pct=recs.apply(lambda x: float(x[1])),
        stop_loss_price=recs.apply(lambda x: float(x[2])),
    )

    # 8. 组装成 INTRADAY_STRATEGY_COLUMNS schema
    out = pd.DataFrame()
    now = datetime.now(timezone.utc).isoformat()
    out["pipeline"] = [pipeline] * len(merged)
    out["weight_method"] = [weight_method] * len(merged)
    out["selection_date"] = [selection_date] * len(merged)
    out["trade_date"] = [trade_date] * len(merged)
    out["segment_label"] = [segment_label] * len(merged)
    out["asset"] = merged["asset"].values
    out["rank"] = merged["rank"].values
    out["composite_value"] = merged["composite_value"].values
    out["prev_close"] = merged["prev_close"].values
    out["open"] = merged["open"].values
    out["high"] = merged["high"].values
    out["low"] = merged["low"].values
    out["close"] = merged["close"].values
    out["forward_return_1d"] = merged["forward_return_1d"].values
    out["real_gap_pct"] = merged["real_gap_pct"].values
    out["open_signal"] = merged["open_signal"].values
    out["recommended_action"] = merged["recommended_action"].values
    out["expected_return_pct"] = merged["expected_return_pct"].values
    out["stop_loss_price"] = merged["stop_loss_price"].values
    out["adjustment_abnormal"] = merged["adjustment_abnormal"].values
    out["created_at"] = [now] * len(merged)

    # 9. 落盘
    save_intraday_strategy_recommendation(
        pipeline=pipeline,
        weight_method=weight_method,
        selection_date=selection_date,
        segment_label=segment_label,
        df=out,
    )
    logger.info(
        "intraday_strategy: %s/%s/%s 段写入 %d 行",
        pipeline,
        weight_method,
        segment_label,
        len(out),
    )
    return out


def save_intraday_strategy_recommendation(
    pipeline: str,
    weight_method: str,
    selection_date: str,
    segment_label: str,
    df: pd.DataFrame,
    file_path: Path | None = None,
) -> None:
    """写入 intraday strategy 建议 (去重同 key 旧行).

    去重 key: (pipeline, weight_method, selection_date, segment_label)
    同一 (pipeline, weight_method, selection_date) 但不同段 (如 S6 -> S7)
    的旧行会保留, 因为段可能随时变化 (胜率最高段是数据驱动的).
    """
    fp = file_path or _INTRADAY_STRATEGY_PATH
    new_df = df.copy()
    for col in INTRADAY_STRATEGY_COLUMNS:
        if col not in new_df.columns:
            new_df[col] = None
    new_df = new_df[INTRADAY_STRATEGY_COLUMNS]

    existing = _read_parquet(fp, INTRADAY_STRATEGY_COLUMNS)
    if not existing.empty:
        mask = (
            (existing["pipeline"] == pipeline)
            & (existing["weight_method"] == weight_method)
            & (existing["selection_date"] == selection_date)
            & (existing["segment_label"] == segment_label)
        )
        existing = existing[~mask]

    combined = pd.concat([existing, new_df], ignore_index=True)
    combined.to_parquet(fp, index=False)
    logger.info(
        "segment_intraday_strategy: %s/%s/%s/%s 已写入 %s (累计 %d 行)",
        pipeline,
        weight_method,
        selection_date,
        segment_label,
        fp.name,
        len(combined),
    )


def load_intraday_strategy_recommendation(
    pipeline: str,
    weight_method: str,
    selection_date: str,
    segment_label: str | None = None,
    file_path: Path | None = None,
) -> list[dict[str, Any]]:
    """读取某日的指定段日内操作建议.

    Args:
        pipeline, weight_method, selection_date: 同 §10 调度
        segment_label: 段标签 (None = 不限段标签, 用于 fallback 查找)

    Returns:
        [{asset, prev_close, open, real_gap_pct, open_signal,
          recommended_action, expected_return_pct, stop_loss_price,
          adjustment_abnormal, ...}]
        若无数据返回 []
    """
    fp = file_path or _INTRADAY_STRATEGY_PATH
    df = _read_parquet(fp, INTRADAY_STRATEGY_COLUMNS)
    if df.empty:
        return []

    mask = (
        (df["pipeline"] == pipeline) & (df["weight_method"] == weight_method) & (df["selection_date"] == selection_date)
    )
    if segment_label is not None:
        mask = mask & (df["segment_label"] == segment_label)
    df = df[mask]
    if df.empty:
        return []

    return df.to_dict(orient="records")  # type: ignore[arg-type]  # noqa: TID251


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
