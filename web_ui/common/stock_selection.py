"""web_ui/common/stock_selection.py

v0.4.8 R12: 接受 date 参数的 stock_selection_result 内部实现
H1.1 严守: 不改 data_loaders, web_ui 内部实现按 date 过滤 Parquet

背景: data_loaders.load_stock_selection_result() 内部固定取 max(selection_date),
忽略 URL <date> 参数。R12 在 web_ui 内部 fork 一个接受 date 参数的版本,
使 /report/<date>?pipeline=ob_quality 能正确显示指定日期的数据。

数据源: comprehensive_factor/result/ob_quality/stock_selection_history/selection_date=YYYY-MM-DD/part-0.parquet
"""

from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd
from paths import COMPREHENSIVE_FACTOR_RESULT


def _get_history_root() -> Path:
    """v0.4.8: ob_quality 固定 (web_ui 简化, 单 pipeline)"""
    return COMPREHENSIVE_FACTOR_RESULT / "stock_selection_history"


def _row_to_stock_dict(row: pd.Series) -> dict:
    """v0.4.8 R12: row → 渲染兼容字典 (与 data_loaders 行为一致)"""
    out: dict = {
        "rank": int(row["rank"]),
        "code": str(row["code"]),
        "composite_value": (float(row["composite_value"]) if pd.notna(row["composite_value"]) else None),
    }
    if pd.notna(row.get("weight_coverage")):
        out["weight_coverage"] = float(row["weight_coverage"])
    if pd.notna(row.get("stage1_rank")):
        out["stage1_rank"] = int(row["stage1_rank"])
    if pd.notna(row.get("stage2_sort_value")):
        out["stage2_sort_value"] = float(row["stage2_sort_value"])
    return out


def load_stock_selection_for_date(date: str, logger: logging.Logger) -> dict | None:
    """v0.4.8 R12: 接受 date 参数的 stock_selection_result (H1.1 严守内部版)

    Args:
        date: YYYY-MM-DD 选股日 (T-1)
        logger: 日志记录器

    Returns:
        股票选股结果字典, schema 与 data_loaders.load_stock_selection_result() 一致
        解析失败 / 数据不存在 → None
    """
    history_root = _get_history_root()
    if not history_root.exists():
        logger.debug("股票选股 Parquet 数据集不存在: %s", history_root)
        return None

    partition_dir = history_root / f"selection_date={date}"
    if not partition_dir.exists():
        logger.debug("选股日 %s 分区不存在: %s", date, partition_dir)
        return None

    part_files = sorted(partition_dir.glob("*.parquet"))
    if not part_files:
        logger.warning("选股日 %s 无 parquet 文件", date)
        return None

    try:
        df = pd.read_parquet(part_files[0])
    except Exception:
        logger.exception("读 %s 失败", part_files[0])
        return None
    if df.empty:
        logger.warning("选股日 %s 无行", date)
        return None

    # 按 stage 拆解 (注: selection_date 是分区 column, 不在 row 中)
    df_sorted = df.sort_values(["stage", "rank"])
    stage1_rows = df_sorted[df_sorted["stage"] == 1]
    stage2_rows = df_sorted[df_sorted["stage"] == 2]
    stage3_rows = df_sorted[df_sorted["stage"] == 3]
    stage1_bottom_rows = df_sorted[df_sorted["stage"] == 4]  # v3.8: stage=4 = Bottom 30

    stage1_top = [_row_to_stock_dict(r) for _, r in stage1_rows.iterrows()]
    stage2_top = [_row_to_stock_dict(r) for _, r in stage2_rows.iterrows()]
    stage3_top = [_row_to_stock_dict(r) for _, r in stage3_rows.iterrows()]
    stage1_bottom = [_row_to_stock_dict(r) for _, r in stage1_bottom_rows.iterrows()]

    # meta 从 row 字段 (data_loaders 用 file-level metadata, 这里用 row 字段)
    # 用 stage1 第一行 (含 top_n / weight_method / factor_direction / composite_score)
    ref_row = stage1_rows.iloc[0] if not stage1_rows.empty else df.iloc[0]
    meta: dict = {
        "selection_date": date,  # 参数决定, 不从 row 读
        "weight_method": str(ref_row.get("weight_method", "rolling_icir_weight")),
        "factor_direction": str(ref_row.get("factor_direction", "positive")),
        "top_n": int(ref_row.get("top_n", len(stage3_top))),
        "composite_score": float(ref_row.get("composite_score", 0.0)),
        "min_amplitude": 0.01,  # data_loaders 默认
        "excluded_by_amplitude": 0,  # 注: 这两个字段 txt_parser 已从 txt 解析
        "excluded_by_coverage": 0,
        "stage1_pool_size": int(ref_row.get("stage1_pool_size", len(stage1_top))),
        "stocks_on_date": int(ref_row.get("stage1_pool_size", len(stage1_top))),
        "valid_stocks": len(stage3_top),
    }

    # weight_config
    weight_config = {
        "method": meta["weight_method"],
        "factor_list": [],
        "factor_cols": [],
    }

    result = {
        "meta": meta,
        "top_stocks": stage3_top,  # 向后兼容
        "stage1_top": stage1_top,
        "stage2_top": stage2_top,
        "stage3_top": stage3_top,
        "stage1_bottom": stage1_bottom,
        "weight_config": weight_config,
    }

    # all_composite_stocks (从 composite daily parquet 读)
    try:
        from summary.report.data_loaders import _load_all_composite_stocks

        result["all_composite_stocks"] = _load_all_composite_stocks(
            meta["weight_method"],
            date,
            logger,
            secondary_meta=None,
        )
    except Exception as e:
        logger.warning("all_composite_stocks 加载失败: %s", e)
        result["all_composite_stocks"] = []

    logger.info(
        "加载股票选股结果 (web_ui 内部 R12): 选股日=%s, Top N=%d, 最优权重=%s, Stage1=%d/Stage2=%d/Stage3=%d",
        meta["selection_date"],
        meta["top_n"],
        meta["weight_method"],
        len(stage1_top),
        len(stage2_top),
        len(stage3_top),
    )
    return result
