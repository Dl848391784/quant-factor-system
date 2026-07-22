"""web_ui/common/weight_method_data.py

从 Parquet 直接读取四种 weight_method 的胜率矩阵 + 候选明细,
替代 txt_parser 对 txt 报告的依赖 (txt 只有"最优" weight_method 的数据).

H1.1 严守: 只读 summary/comprehensive_factor 已有产物, 不修改其他模块.
数据源:
  - summary/result/segment_win_rates.parquet (Section 9 胜率矩阵)
  - summary/result/segment_stock_details.parquet (Section 10 候选明细)
  - comprehensive_factor/result/ob_quality/weight_selection_result.json (最优 weight_method)
"""

from __future__ import annotations

import json
import logging

import pandas as pd
from paths import PROJECT_ROOT


# 四种 weight_method (与 comprehensive_factor/common/weight_engine.py 注册的一致)
ALL_WEIGHT_METHODS: list[str] = [
    "equal_weight",
    "ic_weight",
    "icir_weight",
    "rolling_icir_weight",
]

# 显示名 (中文)
WEIGHT_METHOD_DISPLAY: dict[str, str] = {
    "equal_weight": "等权",
    "ic_weight": "IC 加权",
    "icir_weight": "ICIR 加权",
    "rolling_icir_weight": "滚动 ICIR",
}

_WIN_RATES_PATH = PROJECT_ROOT / "summary" / "result" / "segment_win_rates.parquet"
_STOCK_DETAILS_PATH = PROJECT_ROOT / "summary" / "result" / "segment_stock_details.parquet"
_WEIGHT_SELECTION_PATH = (
    PROJECT_ROOT / "comprehensive_factor" / "result" / "ob_quality" / "weight_selection_result.json"
)


def get_best_weight_method(logger: logging.Logger | None = None) -> str:
    """读 weight_selection_result.json, 返回当前最优 weight_method."""
    try:
        with open(_WEIGHT_SELECTION_PATH, encoding="utf-8") as f:
            data = json.load(f)
        best = data.get("best_selection", {}).get("method", "rolling_icir_weight")
        return best
    except Exception as e:
        if logger:
            logger.warning("读 weight_selection_result.json 失败: %s, fallback to rolling_icir_weight", e)
        return "rolling_icir_weight"


def load_win_matrix(
    weight_method: str,
    logger: logging.Logger | None = None,
) -> dict | None:
    """从 segment_win_rates.parquet 读取胜率矩阵, 返回与 txt_parser.parse_obq_section_9_matrix 同结构.

    Returns:
        {
            "dates": ["06-15", "06-16", ...],
            "segments": [{"label": "S1", "win_rates": [46.3, ...], "merged": 46.3}, ...],
            "best_segment": {"label": "S7", "merged": 59.6},
        }
        None: 数据不足
    """
    if not _WIN_RATES_PATH.exists():
        if logger:
            logger.warning("segment_win_rates.parquet 不存在")
        return None

    try:
        df = pd.read_parquet(_WIN_RATES_PATH)
    except Exception as e:
        if logger:
            logger.warning("读 segment_win_rates.parquet 失败: %s", e)
        return None

    df = df[(df["pipeline"] == "ob_quality") & (df["weight_method"] == weight_method)]
    if df.empty:
        if logger:
            logger.info("segment_win_rates 无 ob_quality/%s 数据", weight_method)
        return None

    all_dates = sorted(df["selection_date"].unique())
    dates_mmdd = [d[5:] for d in all_dates]

    segments = []
    best_segment = None
    for seg_label in [f"S{i + 1}" for i in range(30)]:
        seg_df = df[df["segment_label"] == seg_label].sort_values("selection_date")
        if seg_df.empty:
            segments.append({"label": seg_label, "win_rates": [None] * len(dates_mmdd), "merged": 0.0})
            continue

        # reindex 到完整日期, 缺失日期填 None
        seg_indexed = seg_df.set_index("selection_date").reindex(all_dates)
        win_rates = []
        for wr in seg_indexed["win_rate"]:
            if pd.isna(wr):
                win_rates.append(None)
            else:
                win_rates.append(round(float(wr), 1))

        total_wins = int(seg_df["wins"].sum())
        total_n = int(seg_df["total"].sum())
        merged = round(total_wins / total_n * 100, 1) if total_n > 0 else 0.0

        segments.append({"label": seg_label, "win_rates": win_rates, "merged": merged})

        if best_segment is None or merged > best_segment["merged"]:
            best_segment = {"label": seg_label, "merged": merged}

    if logger:
        logger.info(
            "load_win_matrix(%s): %d 段 × %d 日, 最佳段 %s",
            weight_method,
            len(segments),
            len(dates_mmdd),
            best_segment,
        )

    return {
        "dates": dates_mmdd,
        "segments": segments,
        "best_segment": best_segment,
    }


def load_candidates(
    weight_method: str,
    stock_name_map: dict[str, str] | None = None,
    logger: logging.Logger | None = None,
) -> dict | None:
    """从 segment_stock_details.parquet 读取今日候选明细, 返回与 txt_parser.parse_obq_section_10_segments 同结构.

    Returns:
        {
            "selection_date": str,
            "pool_size": int,
            "weight_method": str,
            "segments": [{"label": "S1", "n_stocks": 1, "win_rate": 42.0, "stocks": [...]}],
            "best_segment": {"label": "S7", "win_rate": 61.4},
        }
        None: 数据不足
    """
    if not _STOCK_DETAILS_PATH.exists():
        if logger:
            logger.warning("segment_stock_details.parquet 不存在")
        return None

    try:
        df = pd.read_parquet(_STOCK_DETAILS_PATH)
    except Exception as e:
        if logger:
            logger.warning("读 segment_stock_details.parquet 失败: %s", e)
        return None

    df = df[(df["pipeline"] == "ob_quality") & (df["weight_method"] == weight_method)]
    if df.empty:
        if logger:
            logger.info("segment_stock_details 无 ob_quality/%s 数据", weight_method)
        return None

    all_dates = sorted(df["selection_date"].unique())
    latest = all_dates[-1]
    today_df = df[df["selection_date"] == latest]
    pool_size = len(today_df)

    # 读 win_rates 取合并胜率 (best_segment)
    win_matrix = load_win_matrix(weight_method, logger=logger)
    seg_wr_map: dict[str, float] = {}
    if win_matrix and win_matrix.get("segments"):
        seg_wr_map = {s["label"]: s["merged"] for s in win_matrix["segments"]}

    best_segment = None
    segments = []
    for seg_label in [f"S{i + 1}" for i in range(30)]:
        seg_df = today_df[today_df["segment_label"] == seg_label].sort_values("rank")
        stocks = []
        for _, row in seg_df.iterrows():
            code = str(row.get("asset", ""))
            name = ""
            if stock_name_map:
                name = stock_name_map.get(code, "")
            stocks.append(
                {
                    "rank": int(row.get("rank", 0)),
                    "code": code,
                    "name": name,
                    "composite": float(row.get("composite_value", 0)),
                }
            )
        wr = seg_wr_map.get(seg_label, 0.0)
        segments.append(
            {
                "label": seg_label,
                "n_stocks": len(stocks),
                "win_rate": wr,
                "stocks": stocks,
            }
        )
        if best_segment is None or wr > best_segment["win_rate"]:
            best_segment = {"label": seg_label, "win_rate": wr}

    if logger:
        logger.info(
            "load_candidates(%s): %d 段, %d 只, 日期 %s",
            weight_method,
            len(segments),
            pool_size,
            latest,
        )

    return {
        "selection_date": str(latest),
        "pool_size": pool_size,
        "weight_method": weight_method,
        "operation": "今日尾盘买入 -> 下一交易日卖出 (高开开盘锁利, 低开等反抽减亏)",
        "segments": segments,
        "best_segment": best_segment,
    }
