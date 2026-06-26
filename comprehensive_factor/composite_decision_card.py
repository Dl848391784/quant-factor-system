"""
决策卡片模块（v1.0）

为 stock_selector 选出的 Top N 短名单生成 5 维客观字段, 辅助人工决断 (3~5 只持仓)。

设计依据: designs/feat_decision_card_v1.md
战略目标: AGENTS.md "战略目标：量化辅助 + 人工决断"
数据驱动原则: PROJECT.md "禁止给系统贴叙事标签" — 所有维度仅做客观陈述

5 维设计:
    D1 客观分类: 跌幅/振幅/区间位置 (纯阈值分桶, 不带叙事词)
    D2 风险标记: 深跌/低流动性/极端振幅 (布尔命中)
    D3 企稳信号: 缩量/价量背离/下影线 (复用 P5 确认信号因子)
    D4 历史画像: 历史进入 Top 30 频次与回报 (本期 null, 待历史归档机制)
    D5 人工核查清单: 公告/新闻/财报/股东 (固定模板, 不动态调整)

设计原则:
    - 决策卡片是辅助维度, 不做 ranking / 打分 / 排序
    - 量化不指导用户"看哪一项", 用户自主判断
    - 数据驱动: 无具体客观数据则字段为 None + 显式说明
"""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass, field
from typing import Any

import numpy as np
import pandas as pd


_logger = logging.getLogger(__name__)


# ============================================================================
# D5 人工核查清单（固定模板）
# ============================================================================

CHECKLIST_D5: list[str] = [
    "公告: 近 7 日有无重大事项 / 业绩预告 / 商誉减值 / 资产重组",
    "新闻: 行业事件 / 政策风险 / 监管问询 / 重大诉讼",
    "财报: 最近季度营收/净利同比 / 现金流 / 应收账款异常",
    "股东: 近期增减持 / 解禁 / 大宗交易 / 股权质押",
]


# ============================================================================
# 阈值常量（第一性原理：分布尾部用百分位, 统计显著性用固定值）
# ============================================================================

# D1 涨幅分桶（return_5d, 单位: 比例）— v3.9: 从跌幅改为涨幅 (面向强势股)
RETURN_5D_BUCKETS: list[tuple[float, str]] = [
    (0.00, "横盘(<0%)"),
    (0.03, "微涨(0~3%)"),
    (0.08, "中涨(3~8%)"),
    (0.15, "大涨(8~15%)"),
    (float("inf"), "暴涨(>15%)"),
]

# D1 振幅分桶（amplitude, 单位: 比例）
AMPLITUDE_BUCKETS: list[tuple[float, str]] = [
    (0.02, "极低(<2%)"),
    (0.04, "低(2~4%)"),
    (0.08, "中(4~8%)"),
    (float("inf"), "高(>8%)"),
]

# D2 过热风险阈值（v3.9: 从深跌/低流动性改为过热风险, 面向强势股）
OVERHEAT_TURNOVER_PERCENTILE = 0.7  # 换手率截面 70% 分位 → 高换手
OVERHEAT_VOLUME_RATIO_THRESHOLD = 1.5  # volume_ratio_5 > 1.5 → 放量
EXTREME_AMPLITUDE_HIGH = 0.12  # > 12% → 异常波动
EXTREME_AMPLITUDE_LOW = 0.01  # < 1% → 一字板涨跌停（不可交易）

# D3 趋势确认阈值 (v3.9: 面向强势股)
NEAR_HIGH_THRESHOLD = 0.95  # near_high_ratio_5 > 0.95 → 接近5日高点
BOLLINGER_UPPER_THRESHOLD = 1.0  # bollinger_pb > 1.0 → 突破布林上轨
RSI_OVERBOUGHT_THRESHOLD = 70  # rsi_6 > 70 → RSI 超买


# ============================================================================
# 5 维数据结构
# ============================================================================


@dataclass
class DimD1Classification:
    """D1 客观分类: 纯阈值分桶, 不带叙事词."""

    return_5d_bucket: str  # 跌幅档位
    return_5d_value: float | None  # 原始值
    amplitude_bucket: str  # 振幅档位
    amplitude_value: float | None
    close_position_5d: str  # "底部" | "中部" | "顶部" | "n/a"


@dataclass
class DimD2Risk:
    """D2 过热风险标记 (v3.9: 面向强势股). 布尔命中."""

    high_turnover: bool  # 换手率 > 截面 70% 分位
    high_volume_ratio: bool  # volume_ratio_5 > 1.5
    extreme_amplitude: bool
    warning_count: int


@dataclass
class DimD3TrendConfirmation:
    """D3 趋势确认信号 (v3.9: 从企稳信号改为趋势确认, 面向强势股).

    数据驱动: 近高比例/布林上轨/RSI 在 Bottom30 内是正向信号 (T+1 更高).
    """

    near_high: bool | None  # near_high_ratio_5 > 0.95
    bollinger_upper: bool | None  # bollinger_pb > 1.0
    rsi_overbought: bool | None  # rsi_6 > 70
    hit_count: int  # 命中数（0~3）
    raw_signals_available: bool


@dataclass
class DimD4History:
    """D4 历史画像: 本期 null, 待历史归档机制."""

    times_in_top30_last_60d: int | None = None
    avg_1d_return_when_in_top30: float | None = None
    note: str = "需历史归档机制（独立 design 待启动）"


@dataclass
class DecisionCard:
    """完整决策卡片 (5 维, D5 不放每股而放报告底部)."""

    d1_classification: DimD1Classification
    d2_risk: DimD2Risk
    d3_trend: DimD3TrendConfirmation  # v3.9: 从 d3_stabilization 改名
    d4_history: DimD4History = field(default_factory=DimD4History)


# ============================================================================
# 分桶辅助
# ============================================================================


def _bucket(value: float | None, buckets: list[tuple[float, str]]) -> str:
    """阈值分桶, value=None 或 NaN 返回 'n/a'."""
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return "n/a"
    for threshold, label in buckets:
        if value < threshold:
            return label
    return buckets[-1][1]


def _safe_float(value: Any) -> float | None:
    """提取标量并转 float, NaN/None 返回 None."""
    if value is None:
        return None
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    if np.isnan(v):
        return None
    return v


def _close_position_in_range(close: float | None, high_5d: float | None, low_5d: float | None) -> str:
    """收盘价在近 5 日 [low, high] 区间位置: 底部/中部/顶部/n/a.

    第一性原理: 区间相对位置 = (close - low) / (high - low),
        < 0.33 底部, < 0.67 中部, ≥ 0.67 顶部.
    """
    if close is None or high_5d is None or low_5d is None:
        return "n/a"
    span = high_5d - low_5d
    if span <= 0:
        return "n/a"
    ratio = (close - low_5d) / span
    if ratio < 0.33:
        return "底部"
    if ratio < 0.67:
        return "中部"
    return "顶部"


# ============================================================================
# 5 维计算
# ============================================================================


def _compute_d1(row: pd.Series) -> DimD1Classification:
    """D1 客观分类."""
    return_5d = _safe_float(row.get("return_5d"))
    amplitude = _safe_float(row.get("amplitude"))
    close = _safe_float(row.get("close"))
    # 近 5 日 high/low: factor_ic_data 单日行只有当日 high/low, 用 near_high_ratio_5
    # 作为代理: close_position 不可得时返回 "n/a"
    high = _safe_float(row.get("high"))
    low = _safe_float(row.get("low"))

    return DimD1Classification(
        return_5d_bucket=_bucket(return_5d, RETURN_5D_BUCKETS),
        return_5d_value=return_5d,
        amplitude_bucket=_bucket(amplitude, AMPLITUDE_BUCKETS),
        amplitude_value=amplitude,
        close_position_5d=_close_position_in_range(close, high, low),
    )


def _compute_d2(row: pd.Series, turnover_threshold: float | None) -> DimD2Risk:
    """D2 过热风险标记 (v3.9: 面向强势股).

    Args:
        row: 当日单股行
        turnover_threshold: 当日换手率截面 70% 分位阈值（None → 不判定 high_turnover）
    """
    turnover = _safe_float(row.get("turnover_rate"))
    vol_ratio = _safe_float(row.get("volume_ratio_5"))
    amplitude = _safe_float(row.get("amplitude"))

    high_to = turnover_threshold is not None and turnover is not None and turnover > turnover_threshold
    high_vr = vol_ratio is not None and vol_ratio > OVERHEAT_VOLUME_RATIO_THRESHOLD
    extreme_amp = amplitude is not None and (amplitude > EXTREME_AMPLITUDE_HIGH or amplitude < EXTREME_AMPLITUDE_LOW)

    return DimD2Risk(
        high_turnover=high_to,
        high_volume_ratio=high_vr,
        extreme_amplitude=extreme_amp,
        warning_count=int(high_to) + int(high_vr) + int(extreme_amp),
    )


def _compute_d3(row: pd.Series) -> DimD3TrendConfirmation:
    """D3 趋势确认信号 (v3.9: 从企稳信号改为趋势确认, 面向强势股).

    数据驱动: 近高比例/布林上轨/RSI 在 Bottom30 内是正向信号 (T+1 更高).
    """
    nh = _safe_float(row.get("near_high_ratio_5"))
    bp = _safe_float(row.get("bollinger_pb"))
    rsi = _safe_float(row.get("rsi_6"))

    raw_available = any(v is not None for v in (nh, bp, rsi))
    if not raw_available:
        return DimD3TrendConfirmation(
            near_high=None,
            bollinger_upper=None,
            rsi_overbought=None,
            hit_count=0,
            raw_signals_available=False,
        )

    near_high_hit = nh is not None and nh > NEAR_HIGH_THRESHOLD
    bollinger_hit = bp is not None and bp > BOLLINGER_UPPER_THRESHOLD
    rsi_hit = rsi is not None and rsi > RSI_OVERBOUGHT_THRESHOLD

    return DimD3TrendConfirmation(
        near_high=near_high_hit if nh is not None else None,
        bollinger_upper=bollinger_hit if bp is not None else None,
        rsi_overbought=rsi_hit if rsi is not None else None,
        hit_count=int(near_high_hit) + int(bollinger_hit) + int(rsi_hit),
        raw_signals_available=True,
    )


def _compute_d4() -> DimD4History:
    """D4 历史画像 — 本期占位."""
    return DimD4History()


# ============================================================================
# 主入口
# ============================================================================


def build_decision_cards(
    top_stocks: list[dict[str, Any]],
    factor_df: pd.DataFrame,
    logger: logging.Logger | None = None,
) -> list[dict[str, Any]]:
    """为短名单生成决策卡片.

    Args:
        top_stocks: stock_selector 选出的 Top N 项 (含 code 字段)
        factor_df: 当日因子+行情 DataFrame (含 asset 列)
        logger: 日志对象

    Returns:
        top_stocks 列表的副本, 每项追加 'decision_card' 字段 (dict 序列化).
    """
    if logger is None:
        logger = _logger

    if not top_stocks:
        return []

    if "asset" not in factor_df.columns:
        logger.warning("decision_card: factor_df 缺 asset 列, 跳过卡片生成")
        return [dict(s) for s in top_stocks]

    asset_index = factor_df.set_index("asset")

    # v3.9: 当日换手率 70% 分位（high_turnover 阈值）
    turnover_threshold: float | None = None
    if "turnover_rate" in factor_df.columns:
        valid_turnover = factor_df["turnover_rate"].dropna()
        if len(valid_turnover) > 0:
            turnover_threshold = float(valid_turnover.quantile(OVERHEAT_TURNOVER_PERCENTILE))  # type: ignore[arg-type]
            logger.info(
                "decision_card: high_turnover 阈值 (当日 %.0f%% 分位): %.4f",
                OVERHEAT_TURNOVER_PERCENTILE * 100,
                turnover_threshold,
            )
    else:
        logger.warning("decision_card: factor_df 缺 turnover_rate 列, D2 high_turnover 不判定")

    enriched: list[dict[str, Any]] = []
    skipped = 0
    for stock in top_stocks:
        item = dict(stock)
        code = item.get("code")
        if code is None or code not in asset_index.index:
            skipped += 1
            item["decision_card"] = None
            enriched.append(item)
            continue

        row = asset_index.loc[code]
        # 处理同 code 多行边界（理论上单日唯一, 但保险）
        if isinstance(row, pd.DataFrame):
            row = row.iloc[0]

        card = DecisionCard(
            d1_classification=_compute_d1(row),
            d2_risk=_compute_d2(row, turnover_threshold),
            d3_trend=_compute_d3(row),
            d4_history=_compute_d4(),
        )
        item["decision_card"] = asdict(card)
        enriched.append(item)

    logger.info(
        "decision_card: 生成 %d 张卡片 (跳过 %d 只, 未在 factor_df 中)",
        len(enriched) - skipped,
        skipped,
    )
    return enriched
