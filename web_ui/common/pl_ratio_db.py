"""web_ui/common/pl_ratio_db.py

v0.4.8 R42 (Stage 6 算法重设计 + B1 主路径): 从 summary/result/segment_stock_details.parquet
读 30 段每日合并收益率 (seg_return = mean(forward_return_1d) * 100)。

R42 设计要点:
- 段号直接用 ssd.segment_label, 不再现场 qcut
- 段内资产 = summary alias 切片 (ob_quality 管线筛后 ~1-5 只/段), 与 R39a 全市场 composite 段位不同
- 无 fallback (用户 2026-07-07 拍板候选 A, 原话"以 ssd 为主")
- trade_date 复用 summary 算法: master_dates.index(selection_date); idx + 1

H1.1 严守:
- web_ui 只读 summary 产物 (R16 txt_parser 先例), 不修改 summary 模块
- 所有路径从 paths 模块导入 (AGENTS.md §硬规则 #11)

数据契约:
{
    "dates": ["06-15", ...],                # mm-dd 格式
    "segments": [
        {
            "label": "S1",
            "pl_ratios": [1.23, 0.98, ...],  # 每选股日的 seg_return (%)
            "avg_pl_ratio": 1.05,            # 末日累计 30 段平均 (用于排序/参考)
        },
        ...
    ],
    "avg_line": [1.20, 1.15, ...],           # 30 段当日算术平均 (粗黑虚线)
    "source": "summary_segment_stock_details",
}
"""

from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd
from paths import PROJECT_ROOT


# 路径: 复用 paths 模块定义 (AGENTS.md §硬规则 #11)
_SEGMENT_STOCK_DETAILS_PATH: Path = PROJECT_ROOT / "summary" / "result" / "segment_stock_details.parquet"
_MASTER_PARQUET_PATH: Path = PROJECT_ROOT / "data_fetchers" / "result" / "ob_quality" / "factor_ic_data.parquet"
_N_SEGMENTS = 30


def _compute_segment_return(
    day_stocks: pd.DataFrame,
    forward_returns: pd.DataFrame,
) -> dict[str, float] | None:
    """对单个选股日, 算 30 段每段的 seg_return (%).

    Args:
        day_stocks: 当日 ssd 明细 (列: asset, segment_label)
        forward_returns: T+1 trade_date forward_return_1d (列: asset, forward_return_1d)

    Returns:
        {seg_label: seg_return_pct} 或 None (merge 后空)
    """
    merged = pd.merge(
        day_stocks,
        forward_returns[["asset", "forward_return_1d"]],
        on="asset",
        how="inner",
    )
    if merged.empty:
        return None

    result: dict[str, float] = {}
    for seg_label in [f"S{i + 1}" for i in range(_N_SEGMENTS)]:
        subset = merged[merged["segment_label"] == seg_label]["forward_return_1d"].dropna()
        seg_return_pct = round(float(subset.mean() * 100), 2) if len(subset) > 0 else 0.0
        result[seg_label] = seg_return_pct
    return result


def load_pl_ratio_trend(
    n_recent_dates: int = 12,
    weight_method: str = "rolling_icir_weight",
    logger: logging.Logger | None = None,
) -> dict | None:
    """读 summary/result/segment_stock_details.parquet, 算最近 N 选股日 × 30 段 seg_return.

    Args:
        n_recent_dates: 取最近多少个选股日 (默认 12 与 txt 第九节对齐)
        weight_method: 权重方法 (默认 rolling_icir_weight)
        logger: 日志

    Returns:
        {
            "dates": ["06-15", ...],
            "segments": [{"label": "S1", "pl_ratios": [...], "avg_pl_ratio": float}, ...],
            "avg_line": [float, ...],
            "source": "summary_segment_stock_details",
        }
        None: 数据缺失 (ssd parquet 不存在 / 读失败 / 0 有效日期)
    """
    if not _SEGMENT_STOCK_DETAILS_PATH.exists():
        if logger:
            logger.warning("ssd parquet 不存在: %s", _SEGMENT_STOCK_DETAILS_PATH)
        return None
    if not _MASTER_PARQUET_PATH.exists():
        if logger:
            logger.warning("master parquet 不存在: %s", _MASTER_PARQUET_PATH)
        return None

    try:
        ssd = pd.read_parquet(
            _SEGMENT_STOCK_DETAILS_PATH,
            columns=["selection_date", "segment_label", "asset", "weight_method"],
        )
        ssd = ssd[ssd["weight_method"] == weight_method]
        if ssd.empty:
            if logger:
                logger.warning("ssd parquet 无 weight_method=%s 数据", weight_method)
            return None

        recent_dates = sorted(ssd["selection_date"].unique())
        if len(recent_dates) > n_recent_dates:
            recent_dates = recent_dates[-n_recent_dates:]

        master = pd.read_parquet(
            _MASTER_PARQUET_PATH,
            columns=["date", "asset", "forward_return_1d"],
        )
        master_dates = sorted(master["date"].dropna().unique())
    except Exception as e:
        if logger:
            logger.warning("读 parquet 失败: %s", e)
        return None

    seg_returns: dict[str, list[float]] = {f"S{i + 1}": [] for i in range(_N_SEGMENTS)}
    avg_line: list[float] = []
    valid_dates_mmdd: list[str] = []

    for selection_date in recent_dates:
        # 复用 summary 算法 (generate_factor_summary_report.py:629-633)
        try:
            idx = master_dates.index(selection_date)
            trade_date = master_dates[idx + 1]
        except (ValueError, IndexError):
            if logger:
                logger.debug("selection_date=%s 无 T+1 交易日, 跳过", selection_date)
            continue

        ret_df = master[(master["date"] == trade_date) & master["forward_return_1d"].notna()]
        if ret_df.empty:
            continue

        day_stocks = ssd[ssd["selection_date"] == selection_date][["asset", "segment_label"]]
        day_seg_return = _compute_segment_return(day_stocks, ret_df)
        if day_seg_return is None:
            continue

        for seg_label, seg_return_pct in day_seg_return.items():
            seg_returns[seg_label].append(float(seg_return_pct))
        avg_line.append(float(round(sum(day_seg_return.values()) / len(day_seg_return), 2)))
        valid_dates_mmdd.append(selection_date[5:])

    if not valid_dates_mmdd:
        if logger:
            logger.warning("pl_ratio_trend 有效日期 0")
        return None

    segments = []
    for seg_label in [f"S{i + 1}" for i in range(_N_SEGMENTS)]:
        plr_list = seg_returns[seg_label]
        segments.append(
            {
                "label": seg_label,
                "pl_ratios": [float(v) for v in plr_list],
                "avg_pl_ratio": float(round(sum(plr_list) / len(plr_list), 2)) if plr_list else 0.0,
            }
        )

    if logger:
        logger.info(
            "pl_ratio_trend 加载 (R42 B1 读 ssd): %d 段 × %d 选股日 (源=%s)",
            len(segments),
            len(valid_dates_mmdd),
            _SEGMENT_STOCK_DETAILS_PATH.name,
        )

    return {
        "dates": valid_dates_mmdd,
        "segments": segments,
        "avg_line": avg_line,
        "source": "summary_segment_stock_details",
    }
