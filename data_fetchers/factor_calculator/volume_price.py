"""data_fetchers.factor_calculator.volume_price：量价合成族因子。

模块定位
========
同时使用价格 + 成交量 / 涨跌幅信号的复合因子。这些因子与 ``momentum.py``
同属"个股层因子"，但因为 **同时使用 price + volume** 或基于 5 日窗口聚合，
而独立成模，便于未来在此模块下扩展量价合成因子（如 OBV / A/D Line / MFI）。

公共 API（design.md §5.5）
==========================
- ``calculate_volume_price_strength(factor_df, ...)``：量价配合（成交量与
  涨跌方向一致性）
- ``calculate_positive_day_ratio_5(factor_df, ...)``：5 日内上涨天数比例
- ``calculate_ma5_deviation(factor_df, ...)``：``(close - ma5) / ma5``
- ``calculate_near_high_ratio_5(factor_df, ...)``：``(close - min5) / (max5 - min5)``
  （5 日新高接近度，基于收盘价 5 日窗口的相对位置）

依赖
====
- ``_common``：列名（含 ``_COL_OPEN`` / ``_COL_TURNOVER_SURGE`` 等）+
  ``get_module_logger``
- ``numpy`` / ``pandas`` / ``logging``

注意事项
========
- 4 个因子的窗口期硬编码为 5（与原 ``factor_calculator.py`` v1.17 一致）；
  本次 PR-3 不重构窗口参数化（design.md §3.2 N1：不重写公式）
- ``calculate_volume_price_strength`` 依赖 ``turnover_surge`` 列（由
  ``basic.calculate_turnover_surge`` 产出），符合 MODULE.md 因子计算依赖图

兼容性
======
原 ``factor_calculator.py`` v1.17 的字节级一致性已在 2026-06-16 修复中
**主动废弃**（修复 ``calculate_near_high_ratio_5`` 的跌停误标为强信号、
``calculate_ma5_deviation`` 的 ``clip(lower=0.01)`` 系统性偏差、
``calculate_positive_day_ratio_5`` 的首行 NaN 误计为阴线等行为缺陷）。
``temporary/factor_calculator_baseline_fingerprint.json`` 的旧指纹不再适用，
新基线由 ``data_fetchers/test_cases/test_factor_calculator.py`` 的单元测试守护。
"""

from __future__ import annotations

import logging

import numpy as np
import pandas as pd

from ._common import (
    _COL_ASSET,
    _COL_CLOSE,
    _COL_DATE,
    _COL_MA5_DEVIATION,
    _COL_NEAR_HIGH_RATIO_5,
    _COL_OPEN,
    _COL_POSITIVE_DAY_RATIO_5,
    _COL_TURNOVER_SURGE,
    _COL_VOLUME_PRICE_STRENGTH,
    get_module_logger,
)


__all__: list[str] = []


def calculate_volume_price_strength(
    factor_df: pd.DataFrame,
    *,
    logger_arg: logging.Logger | None = None,
) -> pd.DataFrame:
    """计算量价齐升强度因子

    公式: volume_price_strength = (close - open) / open × turnover_surge

    含义:
    - 高正值: 日内大幅上涨 + 高换手突增 = 放量上涨（强势）
    - 高负值: 日内大幅下跌 + 高换手突增 = 放量下跌（弱势）
    - 近零值: 小幅波动或低换手 = 无明确方向

    边界处理:
    - open = 0 → intraday_return = inf/NaN → 整行 NaN
    - turnover_surge = NaN → 结果 NaN（传播）

    遵循 H5: IC方向不预判
    """
    _logger = get_module_logger(logger_arg)
    _logger.debug("  输入 %s: %d 行", "calculate_volume_price_strength", len(factor_df))

    df = factor_df.copy()

    # 计算日内涨幅 (close - open) / open
    intraday_return = (df[_COL_CLOSE] - df[_COL_OPEN]) / df[_COL_OPEN]

    # 乘以换手突增系数
    df[_COL_VOLUME_PRICE_STRENGTH] = intraday_return * df[_COL_TURNOVER_SURGE]

    valid_count = int(df[_COL_VOLUME_PRICE_STRENGTH].notna().sum())
    nan_count = len(df) - valid_count
    _logger.info(
        "  有效 %s: %d (%.2f%%)",
        _COL_VOLUME_PRICE_STRENGTH,
        valid_count,
        valid_count / len(df) * 100 if len(df) > 0 else 0,
    )
    _logger.info("  NaN %s: %d 行", _COL_VOLUME_PRICE_STRENGTH, nan_count)

    return df


calculate_volume_price_strength.required_cols = ["open", "close", "turnover_surge"]  # type: ignore[attr-defined]


def calculate_positive_day_ratio_5(
    factor_df: pd.DataFrame,
    *,
    logger_arg: logging.Logger | None = None,
) -> pd.DataFrame:
    """计算近5日阳线比例因子

    公式: positive_day_ratio_5 = count(close > prev_close, 最近5日) / 5

    含义:
    - 值接近1.0: 近5日全部上涨 = 强上升趋势
    - 值接近0.0: 近5日全部下跌 = 强下降趋势
    - 值接近0.5: 上涨下跌交替 = 无明确趋势

    边界处理:
    - 每个 asset 前 5 天为 NaN（首行 diff 为 NaN，rolling(5) 至少需要 5 个
      非 NaN 样本，因此前 4 天 + 包含首行的第 5 天均为 NaN，第 6 天起才有值）
    - 全NaN组 → NaN

    遵循 H5: IC方向不预判
    """
    _logger = get_module_logger(logger_arg)
    _logger.debug("  输入 %s: %d 行", "calculate_positive_day_ratio_5", len(factor_df))

    df = factor_df.copy()
    df = df.sort_values([_COL_ASSET, _COL_DATE])

    # 按asset分组计算日收益率
    daily_return = df.groupby(_COL_ASSET)[_COL_CLOSE].diff()

    # 阳线标记（日收益率 > 0）
    # 首行 diff 为 NaN（每个 asset 第一个交易日无前日收盘可比），
    # 直接 (daily_return > 0).astype(float) 会把 NaN > 0 求值为 False = 0.0，
    # 让首行被误计为"阴线"参与 rolling 求和。用 .where(notna()) 保留 NaN，
    # rolling 在 min_periods=5 下自然把含 NaN 的窗口结果置为 NaN。
    positive_mask = daily_return.gt(0).astype(float).where(daily_return.notna())

    # rolling 5日窗口计算阳线比例，min_periods=5确保前4天为NaN
    ratio = positive_mask.groupby(df[_COL_ASSET]).rolling(5, min_periods=5).mean().reset_index(level=0, drop=True)

    df[_COL_POSITIVE_DAY_RATIO_5] = ratio

    valid_count = int(df[_COL_POSITIVE_DAY_RATIO_5].notna().sum())
    nan_count = len(df) - valid_count
    _logger.info(
        "  有效 %s: %d (%.2f%%)",
        _COL_POSITIVE_DAY_RATIO_5,
        valid_count,
        valid_count / len(df) * 100 if len(df) > 0 else 0,
    )
    _logger.info("  NaN %s: %d 行", _COL_POSITIVE_DAY_RATIO_5, nan_count)

    return df


calculate_positive_day_ratio_5.required_cols = ["date", "asset", "close"]  # type: ignore[attr-defined]


def calculate_ma5_deviation(
    factor_df: pd.DataFrame,
    *,
    logger_arg: logging.Logger | None = None,
) -> pd.DataFrame:
    """计算5日均线偏离度因子

    公式: ma5_deviation = (close - MA5) / MA5

    含义:
    - 正值: 收盘价在5日均线之上 = 多头区域（上升趋势）
    - 负值: 收盘价在5日均线之下 = 空头区域（下降趋势）
    - 近零值: 收盘价贴近均线 = 趋势不明

    边界处理:
    - 前4天无完整5日窗口 → NaN
    - MA5 = 0 → NaN（极少见，A股收盘价不为0）
    - 不再对极小正值做 clip 抬升：A 股 close 不为负，clip(lower=0.01) 会
      把 0.001~0.009 的 MA5 静默抬到 0.01，引入系统性偏差。零值已由
      replace(0, np.nan) 排除，其余分母让结果自然反映极小 MA5 的偏离度。

    遵循 H5: IC方向不预判
    """
    _logger = get_module_logger(logger_arg)
    _logger.debug("  输入 %s: %d 行", "calculate_ma5_deviation", len(factor_df))

    df = factor_df.copy()
    df = df.sort_values([_COL_ASSET, _COL_DATE])

    # 计算5日移动平均线
    ma5 = df.groupby(_COL_ASSET)[_COL_CLOSE].rolling(5, min_periods=5).mean().reset_index(level=0, drop=True)

    # MA5 = 0 时替换为 NaN（避免除零）；
    # 不再用 clip(lower=0.01) 抬升极小正值——会引入系统性偏差，且 A 股 close
    # 不为负，零值是唯一需要保护的退化情形。
    ma5_safe = ma5.replace(0, np.nan)

    # 计算偏离度
    df[_COL_MA5_DEVIATION] = (df[_COL_CLOSE] - ma5_safe) / ma5_safe

    valid_count = int(df[_COL_MA5_DEVIATION].notna().sum())
    nan_count = len(df) - valid_count
    _logger.info(
        "  有效 %s: %d (%.2f%%)",
        _COL_MA5_DEVIATION,
        valid_count,
        valid_count / len(df) * 100 if len(df) > 0 else 0,
    )
    _logger.info("  NaN %s: %d 行", _COL_MA5_DEVIATION, nan_count)

    return df


calculate_ma5_deviation.required_cols = ["date", "asset", "close"]  # type: ignore[attr-defined]


def calculate_near_high_ratio_5(
    factor_df: pd.DataFrame,
    *,
    logger_arg: logging.Logger | None = None,
) -> pd.DataFrame:
    """计算近5日高低位置因子

    公式: near_high_ratio_5 = (close - min(close,5日)) / (max(close,5日) - min(close,5日))

    含义:
    - 值接近1.0: 收盘价在近5日最高点附近 = 强势（接近高点）
    - 值接近0.0: 收盘价在近5日最低点附近 = 弱势（接近低点）
    - 值接近0.5: 在中间位置 = 趋势中性

    边界处理:
    - 前4天无完整5日窗口 → NaN
    - 涨跌停一字板 / 5 日内 close 完全无波动: max=min → diff=0 → NaN
      （此时无法区分位置强弱：close=min=max，强行返回 1.0 会让跌停被误标为
      最强信号；返回 NaN 交由后续截面标准化或 IC 计算自然剔除该极端样本）

    遵循 H5: IC方向不预判
    """
    _logger = get_module_logger(logger_arg)
    _logger.debug("  输入 %s: %d 行", "calculate_near_high_ratio_5", len(factor_df))

    df = factor_df.copy()
    df = df.sort_values([_COL_ASSET, _COL_DATE])

    # 计算5日滚动最高价和最低价
    roll_max = df.groupby(_COL_ASSET)[_COL_CLOSE].rolling(5, min_periods=5).max().reset_index(level=0, drop=True)
    roll_min = df.groupby(_COL_ASSET)[_COL_CLOSE].rolling(5, min_periods=5).min().reset_index(level=0, drop=True)

    # 计算高低价差
    diff = roll_max - roll_min

    # diff == 0（5 日内无波动 / 一字板）时返回 NaN：
    # 此时 close = min = max，无法判定相对强弱，强行赋 1.0 会让跌停一字板
    # 被错误地标为"最强信号"。返回 NaN 让后续截面处理自然剔除该极端样本。
    # 用 pd.Series 包装以保证索引与 df 对齐（np.where 返回 ndarray 不带索引）。
    position = pd.Series(
        np.where(
            diff == 0,
            np.nan,
            (df[_COL_CLOSE] - roll_min) / diff,
        ),
        index=df.index,
    )

    df[_COL_NEAR_HIGH_RATIO_5] = position

    valid_count = int(df[_COL_NEAR_HIGH_RATIO_5].notna().sum())
    nan_count = len(df) - valid_count
    _logger.info(
        "  有效 %s: %d (%.2f%%)",
        _COL_NEAR_HIGH_RATIO_5,
        valid_count,
        valid_count / len(df) * 100 if len(df) > 0 else 0,
    )
    _logger.info("  NaN %s: %d 行", _COL_NEAR_HIGH_RATIO_5, nan_count)

    return df


calculate_near_high_ratio_5.required_cols = ["date", "asset", "close"]  # type: ignore[attr-defined]
