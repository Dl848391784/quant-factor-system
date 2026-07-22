"""web_ui/common/segment_win_db.py

v0.4.8 R38 (Stage 6): 从 segment_win_rates.parquet 算"30 段合并胜率趋势"
H1.1 严守 + §18 fork pattern: web_ui 内部读 parquet, 不直接 import summary 模块
不修改 summary/report/segment_win_db.py (公共数据加载层, 由 summary 维护)

数据源: summary/result/segment_win_rates.parquet
  schema: pipeline, selection_date, trade_date, weight_method, n_segments, n_total,
          segment_label, wins (int), total (int), win_rate (float), created_at
  写入: summary/report/segment_win_db.py:save_segment_win_rates() 在 T+1 日读到
        forward_return_1d 后算胜率写入

数据契约 (与 txt_s9_matrix 对齐, v0.4.8 R4 已存在):
  返回 dict 含 dates/segments[]/source 字段, segments[].merged_running 数组
  长度 = dates 长度 (逐日累计合并胜率)

算法 (验证见 .hermes/plans/feature-30-segments-merged-win-trend-design.md §1.3):
  merged_running[i] = cumsum(wins[0..i+1]) / cumsum(total[0..i+1]) * 100
  末日 merged_running[-1] = strict sum(wins)/sum(total)*100
  = txt 报告第九节"合并"列 (0/30 段偏差 > 0.5%, max diff 0.05%)
"""

from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd
from paths import PROJECT_ROOT


# 路径: 复用 paths 模块定义 (PROJECT.md H7 路径导入)
_PARQUET_PATH: Path = PROJECT_ROOT / "summary" / "result" / "segment_win_rates.parquet"


def load_merged_win_trend(
    pipeline: str = "ob_quality",
    weight_method: str = "rolling_icir_weight",
    logger: logging.Logger | None = None,
) -> dict | None:
    """读 segment_win_rates.parquet, 算截至每日的累计合并胜率曲线.

    Args:
        pipeline: 管线名 (默认 ob_quality)
        weight_method: 权重方法 (默认 rolling_icir_weight)
        logger: 日志记录器 (可选)

    Returns:
        {
            "dates": ["06-15", "06-16", ...],  # mm-dd 格式, 与 txt 第九节一致
            "segments": [
                {
                    "label": "S1",
                    "merged_running": [46.30, 47.73, ...],  # 截至每日的累计合并胜率
                    "merged_final": 46.30,  # 末日累计合并胜率 (与 txt merged 列对得上)
                },
                ...
            ],
            "source": "parquet",
        }
        None: parquet 不存在 / 读失败 / 数据为空
    """
    if not _PARQUET_PATH.exists():
        if logger:
            logger.warning("segment_win_rates.parquet 不存在: %s", _PARQUET_PATH)
        return None

    try:
        df = pd.read_parquet(_PARQUET_PATH)
    except Exception as e:
        if logger:
            logger.warning("读 segment_win_rates.parquet 失败: %s (%s)", _PARQUET_PATH, e)
        return None

    df = df.loc[(df["pipeline"] == pipeline) & (df["weight_method"] == weight_method)]
    if df.empty:
        if logger:
            logger.warning("segment_win_rates 无 %s/%s 数据", pipeline, weight_method)
        return None

    df = df.sort_values(["segment_label", "selection_date"])
    df["cum_wins"] = df.groupby("segment_label")["wins"].cumsum()
    df["cum_total"] = df.groupby("segment_label")["total"].cumsum()
    df["merged_running"] = df["cum_wins"] / df["cum_total"] * 100

    all_dates = sorted(df["selection_date"].unique())
    dates_mmdd = [d[5:] for d in all_dates]

    # 修复: 原代码直接用 groupby 后每段的 merged_running.tolist(), 但某些段在
    # 某些日期无数据 (如 S7 缺 07-08), 导致段数组长度 < dates 长度, Chart.js
    # 从缺失日期起数据左移. 改为 reindex 到完整日期列表, 缺失日期填 None.
    segments = []
    for _label, g in df.groupby("segment_label"):
        # reindex: 将该段数据按完整日期对齐, 缺失日期的 merged_running = None
        g_indexed = g.set_index("selection_date").reindex(all_dates)
        merged_running = g_indexed["merged_running"].tolist()
        # forward fill cumsum 值: 缺失日期的胜率沿用前一天的累计值 (合理:
        # 该日无交易则胜率不变), 但如果该段从第 N 天才开始有数据, 前面的填 None
        last_valid = None
        filled_running: list[float | None] = []
        for v in merged_running:
            if v is not None and not (isinstance(v, float) and v != v):  # not NaN
                last_valid = round(v, 2)
                filled_running.append(last_valid)
            else:
                filled_running.append(last_valid)  # None if no prior data, else carry forward

        segments.append(
            {
                "label": str(g["segment_label"].iloc[0]),
                "merged_running": filled_running,
                "merged_final": round(merged_running[-1], 2) if merged_running else 0.0,
            }
        )

    segments.sort(key=lambda s: int(s["label"][1:]))

    if logger:
        logger.info(
            "merged_win_trend 加载完成: %d 段 × %d 选股日 (来源=%s/%s)",
            len(segments),
            len(dates_mmdd),
            pipeline,
            weight_method,
        )

    return {
        "dates": dates_mmdd,
        "segments": segments,
        "source": "parquet",
    }
