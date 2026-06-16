"""data_fetchers.factor_calculator.intraday：日内强度族因子。

模块定位
========
基于单日 OHLC 数据的 row-level 因子，反映日内多空力量对比。

公共 API
========
- ``calculate_intraday_intensity(factor_df, ...)``：日内价格强度
  ``(close - open) / (high - low)``，值域 ``[-1, 1]``

依赖
====
- ``_common``：``_COL_OPEN`` / ``_COL_HIGH`` / ``_COL_LOW`` / ``_COL_CLOSE``
  + ``get_module_logger``
- ``numpy`` / ``pandas`` / ``logging``

兼容性
======
本模块函数实现与原 ``data_fetchers/factor_generator.py`` v1.42 行为字节级一致：
- row-level 类型守卫（None / 非数值 → NaN）
- 振幅 < EPSILON（1e-10） → NaN（一字涨跌停在本因子中视为无信号）
"""

from __future__ import annotations

import logging

import numpy as np
import pandas as pd

from ._common import (
    _COL_CLOSE,
    _COL_HIGH,
    _COL_LOW,
    _COL_OPEN,
    get_module_logger,
)


__all__: list[str] = []

# 日内因子专用常量（私有）
_COL_INTRADAY_INTENSITY = "intraday_intensity"
_INTRADAY_EPSILON = 1e-10  # 防止除零（振幅极小时视为无效）


def _calc_intraday_intensity_row(
    open_price: float | None,
    close_price: float | None,
    high: float | None,
    low: float | None,
) -> float:
    """row-level 计算：(close - open) / (high - low)。

    类型守卫先 ``is None`` 再 ``isinstance``，遵循 MODULE.md 约束 #5。
    输入缺失或振幅 < EPSILON → NaN。
    """
    if open_price is None or close_price is None or high is None or low is None:
        return np.nan
    if not all(isinstance(p, (int, float)) for p in (open_price, close_price, high, low)):
        return np.nan

    price_range = high - low
    if abs(price_range) < _INTRADAY_EPSILON:
        return np.nan

    return (close_price - open_price) / price_range


def calculate_intraday_intensity(
    factor_df: pd.DataFrame,
    *,
    logger_arg: logging.Logger | None = None,
) -> pd.DataFrame:
    """计算日内价格强度因子。

    公式: intraday_intensity = (close - open) / (high - low)

    含义:
    - 正值 → 收盘价高于开盘价（上涨）
    - 负值 → 收盘价低于开盘价（下跌）
    - 数值绝对值越大，单边强度越强
    - 理论值域 ``[-1, 1]``

    Args:
        factor_df: 包含 ``open`` / ``close`` / ``high`` / ``low`` 列的 DataFrame
        logger_arg: 日志记录器（可选）

    Returns:
        添加 ``intraday_intensity`` 列的 DataFrame（入口 .copy()）

    边界处理:
        - 任一价格列为 None / 非数值 → NaN
        - high == low（一字涨跌停）→ NaN（本因子视为无信号；
          涨跌停的明确方向信号由 ``tail_price_position`` 因子承载）

    Example:
        >>> df = pd.DataFrame(
        ...     {
        ...         "open": [10.0, 12.0],
        ...         "close": [11.5, 11.5],
        ...         "high": [12.0, 12.0],
        ...         "low": [10.0, 11.0],
        ...     }
        ... )
        >>> result = calculate_intraday_intensity(df)
        >>> "intraday_intensity" in result.columns
        True
    """
    _logger = get_module_logger(logger_arg)
    df = factor_df.copy()

    df[_COL_INTRADAY_INTENSITY] = df.apply(
        lambda row: _calc_intraday_intensity_row(row[_COL_OPEN], row[_COL_CLOSE], row[_COL_HIGH], row[_COL_LOW]),
        axis=1,
    )

    valid_count = int(df[_COL_INTRADAY_INTENSITY].notna().sum())
    _logger.info("intraday_intensity 计算完成，共 %s 条记录，有效 %s", len(df), valid_count)

    return df


calculate_intraday_intensity.required_cols = ["open", "close", "high", "low"]  # type: ignore[attr-defined]
