"""web_ui/common/asset_value_db.py

v0.4.8 R44 (Stage 6 新组件): 30 段每日复合资产值 trend (geom compound).
基于 R43 seg_return trend, 每段独立复合:
  asset[0] = 1.00 (起点, ssd 第一天 selection_date 投入)
  asset[i+1] = asset[i] * (1 + seg_return[i+1]/100)
  Y 轴 = 资产值 (1.00 = 本金, >1 赚, <1 亏)

R44 用户决策 (2026-07-07):
- Q1: 30 段各算各 (30 条曲线)
- Q2: 起点 = ssd[0] (selection_date 最早一天)
- Q3: 实战几何复合版 (链式乘法)
- Q4: Y 轴 = 资产值 (不是 %)

H1.1 严守:
- 复用 R43 pl_ratio_db.load_pl_ratio_trend() (已是 R43 commit 08a2881 主路径)
- 不修改其他模块 (paths.py / summary / data_fetchers)
- 所有路径从 paths 模块导入

数据契约:
{
    "dates": ["06-15", ...],                # mm-dd 格式 (与 R43 dates 同)
    "start_date": "2026-06-15",             # 第一天 selection_date (起点)
    "segments": [
        {
            "label": "S1",
            "asset_values": [1.00, 0.98, 1.01, ...],  # 长度 = len(dates) + 1 (含起点)
            "final_value": 0.94,             # 末日资产值
            "total_return_pct": -6.0,        # 末日累计收益率 %
        },
        ...
    ],
    "source": "summary_segment_stock_details_plus_master",
}
"""

from __future__ import annotations

import logging

from web_ui.common.pl_ratio_db import load_pl_ratio_trend


def load_asset_value_trend(
    n_recent_dates: int = 12,
    weight_method: str = "rolling_icir_weight",
    initial_asset: float = 1.0,
    logger: logging.Logger | None = None,
) -> dict | None:
    """基于 R43 seg_return trend, 算 30 段每日几何复合资产值 trend.

    Args:
        n_recent_dates: 取最近多少个选股日 (与 R43 对齐)
        weight_method: 权重方法 (与 R43 对齐)
        initial_asset: 起始资产值, 默认 1.00 (R44 Q2: 第一天 = ssd[0])
        logger: 日志

    Returns:
        {
            "dates": ["06-15", ...],
            "start_date": "2026-06-15",
            "segments": [{"label": "S1", "asset_values": [...], "final_value": float, "total_return_pct": float}, ...],
            "source": "summary_segment_stock_details_plus_master",
        }
        None: R43 失败时返回 None (继承 R43 失败语义)
    """
    seg_return_trend = load_pl_ratio_trend(
        n_recent_dates=n_recent_dates,
        weight_method=weight_method,
        logger=logger,
    )
    if seg_return_trend is None:
        if logger:
            logger.warning("asset_value_trend: 依赖 R43 pl_ratio_trend 失败, 跳过")
        return None

    dates = seg_return_trend["dates"]
    seg_returns = seg_return_trend["segments"]

    segments_out = []
    for seg in seg_returns:
        label = seg["label"]
        rets = seg["pl_ratios"]  # 单位 %, e.g. [-2.18, 3.63, ...]
        # Q3: 实战几何复合 (链式乘法)
        # asset[0] = initial_asset (R44 Q2 起点)
        # asset[i+1] = asset[i] * (1 + rets[i] / 100)
        asset_values = [float(initial_asset)]
        for r in rets:
            asset_values.append(round(asset_values[-1] * (1 + r / 100), 6))
        final_value = asset_values[-1]
        total_return_pct = round((final_value - initial_asset) * 100, 2)
        segments_out.append(
            {
                "label": label,
                "asset_values": asset_values,
                "final_value": float(round(final_value, 6)),
                "total_return_pct": total_return_pct,
            }
        )

    if logger:
        logger.info(
            "asset_value_trend 加载 (R44 geom compound): %d 段 × %d 选股日 (起点=%s, 初始=%.2f)",
            len(segments_out),
            len(dates),
            dates[0] if dates else "N/A",
            initial_asset,
        )

    return {
        "dates": dates,
        "start_date": dates[0] if dates else None,
        "segments": segments_out,
        "source": "summary_segment_stock_details_plus_master",
    }
