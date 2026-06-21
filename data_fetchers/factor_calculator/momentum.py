"""data_fetchers.factor_calculator.momentum：价格 / 动量族因子。

模块定位
========
基于个股价格序列的动量类因子，**纯计算、无外部 I/O**：全天价格位置 /
振幅 / 1d/3d/5d 收益 / 动量强度 / 隔夜收益。这些因子由 factor_generator
在数据生成阶段调用，写入统一数据源 ``factor_ic_data.json.gz``。

公共 API（design.md §5.3）
==========================
本模块按 design.md §5.3 提供 7 个公共因子函数，全部经包级
``__init__.py`` 重导出：

- ``calculate_price_position(factor_df, ...)``：``(close - low) / (high - low)``
- ``calculate_amplitude(factor_df, ...)``：``(high - low) / close``
- ``calculate_past_return_1d(factor_df, ...)``：1 日收益率（按资产分组）
- ``calculate_return_3d(factor_df, ...)``：3 日累计涨幅（按资产分组）
- ``calculate_return_5d(factor_df, ...)``：5 日累计涨幅（按资产分组）
- ``calculate_momentum_strength(factor_df, ...)``：``return_5d / std(return_1d, 5d)``
- ``calculate_overnight_return(factor_df, ...)``：``(open - prev_close) / prev_close``

依赖
====
- ``_common``：列名、默认参数（含 PR-2c 新增的 ``_COL_OPEN`` /
  ``_COL_OVERNIGHT_RET`` / ``_COL_MOMENTUM_STRENGTH`` /
  ``_DEFAULT_MOMENTUM_STRENGTH_WINDOW`` / ``_MOMENTUM_STRENGTH_STD_MIN``）、
  ``_per_asset_transform``、``get_module_logger``
- ``numpy`` / ``pandas`` / ``logging``：标准外部依赖

兼容性
======
本模块函数实现与原 ``factor_calculator.py`` v1.17 字节级一致；PR-2c
通过 ``temporary/factor_calculator_baseline_fingerprint.json`` 的 22 个
因子指纹验证（panel_hash=ecd3e754e9b348cd 不变）。
"""

from __future__ import annotations

import logging

import numpy as np
import pandas as pd

from ._common import (
    _COL_AMPLITUDE,
    _COL_ASSET,
    _COL_CLOSE,
    _COL_DATE,
    _COL_HIGH,
    _COL_INTERACTION_AMP_COMPRESSION,
    _COL_INTERACTION_AMPLITUDE,
    _COL_INTERACTION_TURNOVER,
    _COL_LOW,
    _COL_MOMENTUM_STRENGTH,
    _COL_OPEN,
    _COL_OVERNIGHT_RET,
    _COL_PAST_RETURN_1D,
    _COL_PRICE_POSITION,
    _COL_RETURN_3D,
    _COL_RETURN_5D,
    _COL_TURNOVER_RATE,
    _DEFAULT_AMPLITUDE_EPSILON,
    _DEFAULT_MOMENTUM_STRENGTH_WINDOW,
    _DEFAULT_PAST_RETURN_1D_WINDOW,
    _DEFAULT_PRICE_POSITION_EPSILON,
    _DEFAULT_RETURN_3D_WINDOW,
    _DEFAULT_RETURN_5D_WINDOW,
    _EPSILON,
    _MOMENTUM_STRENGTH_STD_MIN,
    _cross_section_zscore,
    _per_asset_transform,
    get_module_logger,
)


# 本模块按 PROJECT.md "私有名称不出现在 __all__" 约束：所有公共 API 通过包级
# __init__.py 显式 re-export，本子模块 __all__ 留空。
__all__: list[str] = []


# ============================================================================
# 全天价格位置因子
# ============================================================================


def calculate_price_position(factor_df: pd.DataFrame, logger_arg: logging.Logger | None = None) -> pd.DataFrame:
    """
    计算全天价格位置因子

    公式: Price Position = (Close - Low) / (High - Low)

    含义: 收盘价在全天振幅中的相对位置
    - 0 = 收盘价等于最低价（全天最低收盘）
    - 1 = 收盘价等于最高价（全天最高收盘）
    - 0.5 = 收盘价在振幅中位

    Args:
        factor_df: 包含 close, high, low 列的 DataFrame
        logger_arg: 日志记录器（可选，默认使用模块 logger）

    Returns:
        添加 price_position 列的 DataFrame

    边界处理:
        - High - Low = 0 时，使用 epsilon 防止除零，设为 0.5（中位）
        - 正常结果值在 [0, 1] 范围

    Example:
        >>> df = pd.DataFrame({"close": [10.0, 12.0, 11.0], "high": [12.0, 13.0, 11.0], "low": [9.0, 11.0, 11.0]})
        >>> result = calculate_price_position(df)
        >>> "price_position" in result.columns
        True
        >>> result["price_position"].iloc[0]  # (10-9)/(12-9) = 0.333
        0.333...
    """
    _logger = get_module_logger(logger_arg)

    # 入口 copy（遵循 MODULE.md 约束）
    df = factor_df.copy()

    # 计算振幅
    range_val = df[_COL_HIGH] - df[_COL_LOW]

    # 防止除零
    zero_range_mask = np.abs(range_val) < _DEFAULT_PRICE_POSITION_EPSILON

    if zero_range_mask.any():
        zero_count = zero_range_mask.sum()
        _logger.warning("检测到 %s 个振幅为零的记录（high=low），price_position 设为 0.5（中位）", zero_count)

    # 计算价格位置
    df[_COL_PRICE_POSITION] = np.where(
        zero_range_mask,
        0.5,  # 振幅为零时设为中位
        (df[_COL_CLOSE] - df[_COL_LOW]) / range_val,
    )

    _logger.info("price_position 计算完成，共 %s 条记录", len(df))

    return df


calculate_price_position.required_cols = ["close", "high", "low"]  # type: ignore[attr-defined]


# ============================================================================
# 振幅因子计算
# ============================================================================


def calculate_amplitude(factor_df: pd.DataFrame, logger_arg: logging.Logger | None = None) -> pd.DataFrame:
    """
    计算振幅因子

    公式: amplitude = (high - low) / close

    含义: 当日振幅相对于收盘价的比率，反映价格波动强度
    - 值越大 → 波动越剧烈
    - 值越小 → 波动平稳
    - 范围: 理论 [0, +∞)，实际通常 [0, 0.15]（A股振幅上限15%）

    Args:
        factor_df: 包含 high, low, close 列的 DataFrame
        logger_arg: 日志记录器（可选，默认使用模块 logger）

    Returns:
        添加 amplitude 列的 DataFrame

    边界处理:
        - close = 0 时，设为 NaN（无效数据）
        - high = low 时，振幅为 0（一字涨停/跌停）

    Example:
        >>> df = pd.DataFrame({"close": [10.0, 12.0, 0.0], "high": [12.0, 13.0, 11.0], "low": [9.0, 11.0, 9.0]})
        >>> result = calculate_amplitude(df)
        >>> "amplitude" in result.columns
        True
        >>> result["amplitude"].iloc[0]  # (12-9)/10 = 0.3
        0.3
        >>> pd.isna(result["amplitude"].iloc[2])  # close=0 → NaN
        True
    """
    _logger = get_module_logger(logger_arg)

    # 入口 copy（遵循 MODULE.md 约束）
    df = factor_df.copy()

    # 计算振幅
    range_val = df[_COL_HIGH] - df[_COL_LOW]

    # 检查 close 为零的情况
    zero_close_mask = np.abs(df[_COL_CLOSE]) < _DEFAULT_AMPLITUDE_EPSILON

    if zero_close_mask.any():
        zero_count = zero_close_mask.sum()
        _logger.warning("检测到 %s 个收盘价为零的记录，amplitude 设为 NaN（无效数据）", zero_count)

    # 计算振幅因子
    # close=0 → NaN，否则计算 (high - low) / close
    df[_COL_AMPLITUDE] = np.where(
        zero_close_mask,
        np.nan,  # 收盘价为零设为 NaN
        range_val / df[_COL_CLOSE],
    )

    _logger.info("amplitude 计算完成，共 %s 条记录", len(df))

    return df


calculate_amplitude.required_cols = ["close", "high", "low"]  # type: ignore[attr-defined]


# ============================================================================
# 1日涨幅因子计算
# ============================================================================


def calculate_past_return_1d(
    factor_df: pd.DataFrame, window: int = None, logger_arg: logging.Logger | None = None
) -> pd.DataFrame:
    """
    计算 N 日涨幅因子（默认1日）

    公式: past_return_1d = close[t] / close[t-1] - 1

    含义: 当日涨跌幅（相对于昨日收盘价）
    - 正值 → 上涨
    - 负值 → 下跌
    - 0 → 无变化
    - 范围: 理论 [-∞, +∞)，A股日涨跌幅±10%

    Args:
        factor_df: 包含 close, asset, date 列的 DataFrame
        window: 计算窗口（默认1日）
        logger_arg: 日志记录器（可选，默认使用模块 logger）

    Returns:
        添加 past_return_1d 列的 DataFrame

    边界处理:
        - 第一日数据设为 NaN（无昨日收盘价）
        - close[t-1] = 0 时设为 NaN（无效数据）

    规范:
        - 函数入口必须先 .copy()，避免修改原始数据
        - 必须按 asset 分组后再做 shift（单股票时序指标）

    Example:
        >>> df = pd.DataFrame({
        ...     'date': ['2026-01-01', '2026-01-02', '2026-01-03'],
        ...     'asset': ['A', 'A', 'A'],
        ...     'close': [100.0, 102.0, 101.0]
               ... })
               >>> result = calculate_past_return_1d(df, window=1)
               >>> "past_return_1d" in result.columns
               True
               >>> pd.isna(result["past_return_1d"].iloc[0])  # 第一日无数据
               True
               >>> result["past_return_1d"].iloc[1]  # (102/100 - 1) = 0.02
               0.02
               >>> result["past_return_1d"].iloc[2]  # (101/102 - 1) = -0.0098...
               -0.00980392156862745
    """
    _logger = get_module_logger(logger_arg)

    if window is None:
        window = _DEFAULT_PAST_RETURN_1D_WINDOW

    # 入口 copy（遵循 MODULE.md 约束）
    df = factor_df.copy()

    # 按 asset+date 排序
    df = df.sort_values([_COL_ASSET, _COL_DATE])

    # 按 asset 分组，shift(1) 获取昨日收盘价
    close_shifted = df.groupby(_COL_ASSET, group_keys=False)[_COL_CLOSE].shift(window)

    # 计算 1 日涨幅: close[t] / close[t-1] - 1
    # close_shifted 为 NaN 或 0 时，结果设为 NaN
    invalid_mask = close_shifted.isna() | (close_shifted.abs() < _EPSILON)

    df[_COL_PAST_RETURN_1D] = np.where(invalid_mask, np.nan, df[_COL_CLOSE] / close_shifted - 1)

    _logger.info("past_return_1d (window=%s) 计算完成，共 %s 条记录", window, len(df))

    return df


calculate_past_return_1d.required_cols = ["close", "asset", "date"]  # type: ignore[attr-defined]


# ============================================================================
# 3日累计涨幅因子计算
# ============================================================================


def calculate_return_3d(
    factor_df: pd.DataFrame, window: int = None, logger_arg: logging.Logger | None = None
) -> pd.DataFrame:
    """
    计算 N 日累计涨幅因子（默认3日）

    公式: return_Nd = close[t] / close[t-N] - 1

    含义: 过去 N 日累计涨跌幅
    - 正值 → 上涨
    - 负值 → 下跌
    - 0 → 无变化
    - 范围: 理论 [-∞, +∞)，A股日涨跌幅±10%，3日累计约±30%

    Args:
        factor_df: 包含 close, asset, date 列的 DataFrame
        window: 计算窗口（默认3日）
        logger_arg: 日志记录器（可选，默认使用模块 logger）

    Returns:
        添加 return_3d 列的 DataFrame

    边界处理:
        - 前N日数据设为 NaN（历史数据不足）
        - close[t-N] = 0 时设为 NaN（无效数据）

    规范:
        - 函数入口必须先 .copy()，避免修改原始数据
        - 必须按 asset 分组后再做 shift（单股票时序指标）

    Example:
        >>> df = pd.DataFrame(
        ...     {
        ...         "date": ["2026-01-01", "2026-01-02", "2026-01-03", "2026-01-04"],
        ...         "asset": ["A", "A", "A", "A"],
        ...         "close": [100.0, 102.0, 101.0, 105.0],
        ...     }
        ... )
        >>> result = calculate_return_3d(df, window=3)
        >>> "return_3d" in result.columns
        True
        >>> pd.isna(result["return_3d"].iloc[0])  # 前3日无数据
        True
        >>> result["return_3d"].iloc[3]  # (105/100 - 1) = 0.05
        0.05
    """
    _logger = get_module_logger(logger_arg)

    if window is None:
        window = _DEFAULT_RETURN_3D_WINDOW

    # 入口 copy（遵循 MODULE.md 约束）
    df = factor_df.copy()

    # 按 asset+date 排序
    df = df.sort_values([_COL_ASSET, _COL_DATE])

    # 按 asset 分组，shift(window) 获取历史收盘价
    close_shifted = df.groupby(_COL_ASSET, group_keys=False)[_COL_CLOSE].shift(window)

    # 计算 N 日累计涨幅: close[t] / close[t-N] - 1
    # close_shifted 为 NaN 或 0 时，结果设为 NaN
    invalid_mask = close_shifted.isna() | (close_shifted.abs() < _EPSILON)

    df[_COL_RETURN_3D] = np.where(invalid_mask, np.nan, df[_COL_CLOSE] / close_shifted - 1)

    _logger.info("return_3d (window=%s) 计算完成，共 %s 条记录", window, len(df))

    return df


calculate_return_3d.required_cols = ["close", "asset", "date"]  # type: ignore[attr-defined]


# ============================================================================
# 5日累计涨幅因子计算
# ============================================================================


def calculate_return_5d(
    factor_df: pd.DataFrame, window: int = None, logger_arg: logging.Logger | None = None
) -> pd.DataFrame:
    """
    计算 N 日累计涨幅因子（默认5日）

    公式: return_Nd = close[t] / close[t-N] - 1

    含义: 过去 N 日累计涨跌幅
    - 正值 → 上涨
    - 负值 → 下跌
    - 0 → 无变化
    - 范围: 理论 [-∞, +∞)，A股日涨跌幅±10%，5日累计约±50%

    Args:
        factor_df: 包含 close, asset, date 列的 DataFrame
        window: 计算窗口（默认5日）
        logger_arg: 日志记录器（可选，默认使用模块 logger）

    Returns:
        添加 return_5d 列的 DataFrame

    边界处理:
        - 前N日数据设为 NaN（历史数据不足）
        - close[t-N] = 0 时设为 NaN（无效数据）

    规范:
        - 函数入口必须先 .copy()，避免修改原始数据
        - 必须按 asset 分组后再做 shift（单股票时序指标）

    Example:
        >>> df = pd.DataFrame(
        ...     {
        ...         "date": ["2026-01-01", "2026-01-02", "2026-01-03", "2026-01-04", "2026-01-05", "2026-01-06"],
        ...         "asset": ["A", "A", "A", "A", "A", "A"],
        ...         "close": [100.0, 102.0, 101.0, 103.0, 105.0, 108.0],
        ...     }
        ... )
        >>> result = calculate_return_5d(df, window=5)
        >>> "return_5d" in result.columns
        True
        >>> pd.isna(result["return_5d"].iloc[0])  # 前5日无数据
        True
        >>> result["return_5d"].iloc[5]  # (108/100 - 1) = 0.08
        0.08
    """
    _logger = get_module_logger(logger_arg)

    if window is None:
        window = _DEFAULT_RETURN_5D_WINDOW

    # 入口 copy（遵循 MODULE.md 约束）
    df = factor_df.copy()

    # 按 asset+date 排序
    df = df.sort_values([_COL_ASSET, _COL_DATE])

    # 按 asset 分组，shift(window) 获取历史收盘价
    close_shifted = df.groupby(_COL_ASSET, group_keys=False)[_COL_CLOSE].shift(window)

    # 计算 N 日累计涨幅: close[t] / close[t-N] - 1
    # close_shifted 为 NaN 或 0 时，结果设为 NaN
    invalid_mask = close_shifted.isna() | (close_shifted.abs() < _EPSILON)

    df[_COL_RETURN_5D] = np.where(invalid_mask, np.nan, df[_COL_CLOSE] / close_shifted - 1)

    _logger.info("return_5d (window=%s) 计算完成，共 %s 条记录", window, len(df))

    return df


calculate_return_5d.required_cols = ["close", "asset", "date"]  # type: ignore[attr-defined]


# ============================================================================
# 动量强度因子计算（v1.10 新增）
# ============================================================================


def calculate_momentum_strength(
    factor_df: pd.DataFrame, window: int | None = None, logger_arg: logging.Logger | None = None
) -> pd.DataFrame:
    """
    计算动量强度因子

    公式: momentum_strength = return_5d / std(return_1d, window)

    含义: 衡量5日累计涨幅相对于日收益率波动率的比率
    - 高值 → 持续上涨趋势（动量强，波动小）
    - 低值 → 震荡或下跌（动量弱，波动大）
    - 范围: 理论 [-∞, +∞)，极端值需关注

    Args:
        factor_df: 包含 close, return_5d, asset, date 列的 DataFrame
        window: 滚动标准差窗口（默认5日）
        logger_arg: 日志记录器（可选，默认使用模块 logger）

    Returns:
        添加 momentum_strength 列的 DataFrame

    边界处理:
        - std = 0 时设为 NaN（除零保护）
        - return_5d = NaN 时结果为 NaN（历史不足）
        - 前 window 日数据设为 NaN（rolling window 不足）

    规范:
        - 函数入口必须先 .copy()，避免修改原始数据（遵循 MODULE.md 约束 M11）
        - 必须按 asset 分组后再做 rolling（单股票时序指标）

    Example:
        >>> df = pd.DataFrame(
        ...     {
        ...         "date": ["2026-01-01", "2026-01-02", "2026-01-03", "2026-01-04", "2026-01-05", "2026-01-06"],
        ...         "asset": ["A", "A", "A", "A", "A", "A"],
        ...         "close": [100.0, 102.0, 101.0, 103.0, 105.0, 108.0],
        ...         "return_5d": [np.nan, np.nan, np.nan, np.nan, np.nan, 0.08],
        ...     }
        ... )
        >>> result = calculate_momentum_strength(df, window=5)
        >>> "momentum_strength" in result.columns
        True
        >>> pd.isna(result["momentum_strength"].iloc[0])  # 前5日无数据
        True
    """
    _logger = get_module_logger(logger_arg)

    if window is None:
        window = _DEFAULT_MOMENTUM_STRENGTH_WINDOW

    # 入口 copy（遵循 MODULE.md 约束 M11）
    df = factor_df.copy()

    # 按 asset+date 排序
    df = df.sort_values([_COL_ASSET, _COL_DATE])

    # 计算日收益率 return_1d（临时列）
    # 公式: close[t] / close[t-1] - 1
    close_shifted = df.groupby(_COL_ASSET, group_keys=False)[_COL_CLOSE].shift(1)
    invalid_close_mask = close_shifted.isna() | (close_shifted.abs() < _EPSILON)
    df["_return_1d_temp"] = np.where(invalid_close_mask, np.nan, df[_COL_CLOSE] / close_shifted - 1)

    # 计算 5 日滚动标准差（按 asset 分组）
    # v1.x (2026-06-13): 用 _per_asset_transform 替代 groupby.transform，避免 OOM
    df["_return_1d_std_5"] = _per_asset_transform(
        asset_arr=df[_COL_ASSET].to_numpy(),
        value_arr=df["_return_1d_temp"].to_numpy(),
        fn=lambda s: s.rolling(window=window, min_periods=window).std(),
    )

    # 计算动量强度: return_5d / std(return_1d, 5)
    # v1.38 修复：分母下限保护（防止均匀涨跌时比值爆炸）
    # std 为 NaN 时设 NaN（历史不足）；std=0 时也设 NaN（完全无波动）
    # std 极小但非零时 clip 到下限而非设 NaN
    # 理由：连续5天均匀涨/跌 → std≈0.003 → return_5d/std ≈ ±50，极端异常
    #   clip 到 0.01 后 → ±15 范围内，保留信号方向但限制极端幅度
    invalid_std_mask = df["_return_1d_std_5"].isna() | (df["_return_1d_std_5"] < _EPSILON)
    invalid_return_mask = df["return_5d"].isna()

    # 对有效 std 做 clip（下限 _MOMENTUM_STRENGTH_STD_MIN=0.01）
    # std=0 或 NaN 的行已被 invalid_std_mask 排除，clip 只作用于有效极小值
    df["_return_1d_std_5_safe"] = df["_return_1d_std_5"].clip(lower=_MOMENTUM_STRENGTH_STD_MIN)

    df[_COL_MOMENTUM_STRENGTH] = np.where(
        invalid_std_mask | invalid_return_mask, np.nan, df["return_5d"] / df["_return_1d_std_5_safe"]
    )

    # 清理临时列
    del df["_return_1d_temp"]
    del df["_return_1d_std_5"]
    del df["_return_1d_std_5_safe"]

    _logger.info("momentum_strength (window=%s) 计算完成，共 %s 条记录", window, len(df))

    return df


calculate_momentum_strength.required_cols = ["close", "return_5d", "asset", "date"]  # type: ignore[attr-defined]


# ============================================================================
# 隔夜收益率因子计算
# ============================================================================


def calculate_overnight_return(factor_df: pd.DataFrame, logger_arg: logging.Logger | None = None) -> pd.DataFrame:
    """计算隔夜收益率因子

    公式: overnight_ret = (今日开盘价 - 昨日收盘价) / 昨日收盘价

    参数:
        factor_df: 包含 open, close, asset, date 列的 DataFrame
        logger_arg: 调用方传入的 logger

    返回:
        添加 overnight_ret 列的 DataFrame

    边界处理:
        - 第一天数据为 NaN（无昨日收盘价）
        - prev_close < EPSILON 时设为 NaN（除零防护）

    Example:
        >>> df = pd.DataFrame(
        ...     {"asset": ["A", "A"], "date": ["2026-05-01", "2026-05-02"], "open": [10.0, 10.5], "close": [10.2, 10.8]}
        ... )
        >>> result = calculate_overnight_return(df)
        >>> pd.isna(result["overnight_ret"].iloc[0])  # 第一天无昨日收盘价
        True
        >>> result["overnight_ret"].iloc[1]  # (10.5-10.2)/10.2
        0.0294...
    """
    _logger = get_module_logger(logger_arg)

    df = factor_df.copy()
    df = df.sort_values([_COL_ASSET, _COL_DATE])

    # 按资产分组计算昨日收盘价
    prev_close = df.groupby(_COL_ASSET)[_COL_CLOSE].shift(1)

    # 除零防护：先检查 prev_close 是否接近零，再计算
    invalid_mask = prev_close.abs() < _EPSILON
    df[_COL_OVERNIGHT_RET] = np.where(invalid_mask, np.nan, (df[_COL_OPEN] - prev_close) / prev_close)

    # 记录异常情况
    if invalid_mask.any():
        _logger.warning("发现 %s 个异常收盘价（<%s），已设为 NaN", invalid_mask.sum(), _EPSILON)

    _logger.info("overnight_ret 计算完成，共 %s 条记录", len(df))

    return df


calculate_overnight_return.required_cols = ["open", "close"]  # type: ignore[attr-defined]


# ============================================================================
# v2.35: P5 补齐信息维度——趋势变化/K线形态因子（design.md §2.5）
# ============================================================================

_COL_RSI_6 = "rsi_6"
_COL_RSI_SLOPE_3D = "rsi_slope_3d"
_COL_MA5_SLOPE = "ma5_slope"
_COL_LOWER_SHADOW_RATIO = "lower_shadow_ratio"

_RSI_SLOPE_WINDOW = 3
_MA5_WINDOW = 5
_MA5_SLOPE_WINDOW = 3
_LOWER_SHADOW_EPSILON = 1e-10


def calculate_rsi_slope_3d(
    factor_df: pd.DataFrame,
    *,
    logger_arg: logging.Logger | None = None,
) -> pd.DataFrame:
    """计算 RSI 3日斜率因子

    公式: rsi_slope_3d = RSI(6, today) - RSI(6, today-3)

    含义: RSI 从超卖区回升=卖压减弱，正值=动量向上拐头。
    与现有 rsi（测量状态）互补：rsi 量"当前强弱"，rsi_slope_3d 量"强弱变化方向"。

    边界处理:
        - 前3天无完整窗口 → NaN
        - rsi_6 为 NaN 时结果为 NaN

    遵循 H5: IC方向不预判
    """
    _logger = get_module_logger(logger_arg)
    _logger.debug("  输入 %s: %d 行", "calculate_rsi_slope_3d", len(factor_df))

    df = factor_df.copy()
    df = df.sort_values([_COL_ASSET, _COL_DATE])

    rsi = df.groupby(_COL_ASSET)[_COL_RSI_6]
    df[_COL_RSI_SLOPE_3D] = rsi.transform(lambda x: x - x.shift(_RSI_SLOPE_WINDOW))

    valid_count = int(df[_COL_RSI_SLOPE_3D].notna().sum())
    _logger.info(
        "  有效 %s: %d (%.2f%%)，NaN %d 行",
        _COL_RSI_SLOPE_3D,
        valid_count,
        valid_count / len(df) * 100 if len(df) > 0 else 0,
        len(df) - valid_count,
    )

    return df


calculate_rsi_slope_3d.required_cols = ["date", "asset", "rsi_6"]  # type: ignore[attr-defined]


def calculate_ma5_slope(
    factor_df: pd.DataFrame,
    *,
    logger_arg: logging.Logger | None = None,
) -> pd.DataFrame:
    """计算 MA5 3日斜率因子

    公式: ma5 = rolling(close, 5).mean()
          ma5_slope = (ma5_today - ma5_{today-3}) / ma5_{today-3}

    含义: 均线走平/回升=下跌趋势可能结束，正值=中期趋势向上拐头。
    与现有 ma5_deviation（测量偏离度）互补：ma5_deviation 量"价格离均线多远"，
    ma5_slope 量"均线本身往哪走"。

    边界处理:
        - 前7天无完整窗口（5日均线 + 3日差分）→ NaN
        - ma5_{today-3} = 0 → NaN（A 股 close 不为负，零值由 replace 排除）
    """
    _logger = get_module_logger(logger_arg)
    _logger.debug("  输入 %s: %d 行", "calculate_ma5_slope", len(factor_df))

    df = factor_df.copy()
    df = df.sort_values([_COL_ASSET, _COL_DATE])

    ma5 = (
        df.groupby(_COL_ASSET)[_COL_CLOSE]
        .rolling(_MA5_WINDOW, min_periods=_MA5_WINDOW)
        .mean()
        .reset_index(level=0, drop=True)
    )
    ma5_prev = (
        df.groupby(_COL_ASSET)[_COL_CLOSE]
        .rolling(_MA5_WINDOW, min_periods=_MA5_WINDOW)
        .mean()
        .shift(_MA5_SLOPE_WINDOW)
        .reset_index(level=0, drop=True)
    )

    ma5_prev_safe = ma5_prev.replace(0, np.nan)
    df[_COL_MA5_SLOPE] = (ma5 - ma5_prev_safe) / ma5_prev_safe

    valid_count = int(df[_COL_MA5_SLOPE].notna().sum())
    _logger.info(
        "  有效 %s: %d (%.2f%%)，NaN %d 行",
        _COL_MA5_SLOPE,
        valid_count,
        valid_count / len(df) * 100 if len(df) > 0 else 0,
        len(df) - valid_count,
    )

    return df


calculate_ma5_slope.required_cols = ["date", "asset", "close"]  # type: ignore[attr-defined]


def calculate_lower_shadow_ratio(
    factor_df: pd.DataFrame,
    *,
    logger_arg: logging.Logger | None = None,
) -> pd.DataFrame:
    """计算下影线比因子

    公式: lower_shadow = max(0, min(open, close) - low)
          total_range = high - low
          lower_shadow_ratio = lower_shadow / total_range

    含义: 下影线长=低位有承接买盘，值大=空方抛压被买盘吸收。
    与现有 price_position（收盘价位置）互补：price_position 量"收盘在哪"，
    lower_shadow_ratio 量"盘中有无承接"。

    边界处理:
        - high - low = 0 时（一字板），设为 0.5（中位，无信息）
        - 正常结果值在 [0, 1] 范围
    """
    _logger = get_module_logger(logger_arg)
    _logger.debug("  输入 %s: %d 行", "calculate_lower_shadow_ratio", len(factor_df))

    df = factor_df.copy()

    body_bottom = np.minimum(df[_COL_OPEN], df[_COL_CLOSE])
    lower_shadow = np.maximum(0.0, body_bottom - df[_COL_LOW])
    total_range = df[_COL_HIGH] - df[_COL_LOW]

    zero_range_mask = np.abs(total_range) < _LOWER_SHADOW_EPSILON
    df[_COL_LOWER_SHADOW_RATIO] = np.where(
        zero_range_mask,
        0.5,
        lower_shadow / total_range,
    )

    valid_count = int(df[_COL_LOWER_SHADOW_RATIO].notna().sum())
    _logger.info(
        "  有效 %s: %d (%.2f%%)，NaN %d 行",
        _COL_LOWER_SHADOW_RATIO,
        valid_count,
        valid_count / len(df) * 100 if len(df) > 0 else 0,
        len(df) - valid_count,
    )

    return df


calculate_lower_shadow_ratio.required_cols = ["open", "close", "high", "low"]  # type: ignore[attr-defined]


# ============================================================================
# v2.35: P5-补充——价格加速度因子（二阶导数：企稳信号）
# 公理4: 需要"是否企稳"信号 = 下跌速度在放缓 = 二阶导数为正
# ============================================================================

_COL_RETURN_ACCEL_5D = "return_acceleration_5d"
_COL_DOWNSIDE_DECEL = "downside_deceleration"
_RETURN_ACCEL_LAG = 5


def calculate_return_acceleration_5d(
    factor_df: pd.DataFrame,
    *,
    logger_arg: logging.Logger | None = None,
) -> pd.DataFrame:
    """计算 5日收益率加速度（二阶导数：跌幅收窄信号）

    公式: return_acceleration_5d = return_5d(t) - return_5d(t-5)
    物理含义: 5日收益率的变化量（加速度）
    企稳信号: 正值 = 跌幅收窄/涨幅扩大
    预期IC方向: 正向（跌幅收窄 → 后续收益高）

    Args:
        factor_df: 包含 date, asset, return_5d 列的 DataFrame
        logger_arg: 日志器

    Returns:
        添加了 return_acceleration_5d 列的 DataFrame
    """
    log = logger_arg or logging.getLogger(__name__)
    # sort_values(inplace=False) 返回独立 buffer 的新对象，无需额外 .copy()
    # （设计依据: designs/fix_factor_generator_step13_oom.md §4.3 等价性证明）
    df = factor_df.sort_values([_COL_ASSET, _COL_DATE])

    df[_COL_RETURN_ACCEL_5D] = df.groupby(_COL_ASSET)[_COL_RETURN_5D].transform(
        lambda x: x - x.shift(_RETURN_ACCEL_LAG)
    )

    valid_count = int(df[_COL_RETURN_ACCEL_5D].notna().sum())
    log.info(
        "  return_acceleration_5d: valid=%d (%.2f%%), NaN=%d",
        valid_count,
        valid_count / len(df) * 100 if len(df) > 0 else 0,
        len(df) - valid_count,
    )

    return df


calculate_return_acceleration_5d.required_cols = ["date", "asset", "return_5d"]  # type: ignore[attr-defined]


def calculate_downside_deceleration(
    factor_df: pd.DataFrame,
    *,
    logger_arg: logging.Logger | None = None,
) -> pd.DataFrame:
    """计算 下跌减速因子（仅对前期下跌的股票计算跌幅收窄幅度）

    公式: downside_deceleration = max(0, return_5d(t) - return_5d(t-5))
           仅当 return_5d(t-5) < 0（前期下跌）时计算，否则为 0
    物理含义: 下跌股票的跌幅收窄幅度
    企稳信号: 正值 = 之前在跌，现在跌幅收窄了
    预期IC方向: 正向

    Args:
        factor_df: 包含 date, asset, return_5d 列的 DataFrame
        logger_arg: 日志器

    Returns:
        添加了 downside_deceleration 列的 DataFrame
    """
    log = logger_arg or logging.getLogger(__name__)
    # sort_values(inplace=False) 返回独立 buffer 的新对象，无需额外 .copy()
    # （设计依据: designs/fix_factor_generator_step13_oom.md §4.3 等价性证明）
    df = factor_df.sort_values([_COL_ASSET, _COL_DATE])

    prev_ret5d = df.groupby(_COL_ASSET)[_COL_RETURN_5D].shift(_RETURN_ACCEL_LAG)
    accel = df[_COL_RETURN_5D] - prev_ret5d
    # 仅对前期下跌(prev_ret5d < 0)的股票计算，取非负值
    df[_COL_DOWNSIDE_DECEL] = np.where(prev_ret5d < 0, np.maximum(0, accel), 0)

    valid_count = int(df[_COL_DOWNSIDE_DECEL].notna().sum())
    positive_count = int((df[_COL_DOWNSIDE_DECEL] > 0).sum())
    log.info(
        "  downside_deceleration: valid=%d (%.2f%%), 跌幅收窄(>0)=%d",
        valid_count,
        valid_count / len(df) * 100 if len(df) > 0 else 0,
        positive_count,
    )

    return df


calculate_downside_deceleration.required_cols = ["date", "asset", "return_5d"]  # type: ignore[attr-defined]


# ============================================================================
# 交互因子族（v2.36, 2026-06-22）—— 条件因子方向方案 B
# ============================================================================
# 设计依据：design.md feat_interaction_factors。
#
# 第一性原理：IC = corr(因子值, 未来收益) 是无条件相关系数，假设"因子-收益
# 关系在所有条件下相同"。实证发现 amplitude/turnover_rate 等因子在弱势子样本
# 中 IC 翻正（弱势股 IC=+0.083 vs 全样本 -0.022），即因子方向是条件依赖的。
# 交互因子 = -z_cs(return_3d) × z_cs(factor) 用乘法捕捉这种条件方向，
# 把"弱势×高振幅=反弹"信号提取到无条件 IC 上（实测全样本 IC≈+0.020 翻正）。
#
# 实证数据来源：skill factor-development ref conditional-ic-analysis.md §3-4。
# weakness 源于 return_3d 是因为它在 4 个候选 weakness 信号中 IC 表现最佳。


def _build_weakness(df: pd.DataFrame, logger: logging.Logger) -> pd.Series:
    """构建 weakness 信号：-z_cs(return_3d)。

    跌得越多越弱势，z-score 越高 → 与因子 z-score 相乘后捕捉"弱势 × 高因子值"组合。
    使用 ``_cross_section_zscore``（带 ±3σ clip），见 ``_common.py``。

    Args:
        df: 必须包含 _COL_DATE / _COL_RETURN_3D 列
        logger: 日志器

    Returns:
        weakness Series（与 df 同 index）
    """
    if _COL_RETURN_3D not in df.columns:
        raise ValueError(f"交互因子缺失依赖列: {_COL_RETURN_3D}")
    nan_count = int(df[_COL_RETURN_3D].isna().sum())
    if nan_count > 0:
        logger.debug("  weakness 构建: return_3d NaN=%d (会传播到交互因子)", nan_count)
    return -_cross_section_zscore(df[_COL_RETURN_3D], df[_COL_DATE])


def calculate_interaction_amplitude(
    factor_df: pd.DataFrame,
    *,
    logger_arg: logging.Logger | None = None,
) -> pd.DataFrame:
    """计算交互因子 interaction_amplitude = -z_cs(return_3d) × z_cs(amplitude)。

    含义: 捕捉"弱势(跌得多)股票中高振幅=反弹信号"的条件效应。
    实证全样本 IC≈+0.020（方向="positive"，选高值=反弹型）。

    Args:
        factor_df: 必须包含 date / asset / return_3d / amplitude 列
        logger_arg: 日志器

    Returns:
        添加 ``interaction_amplitude`` 列的 DataFrame（不改原 df）

    边界处理:
        - return_3d 或 amplitude 缺失 → 交互值为 NaN（乘法自然传播）
        - 截面 std=0 → 加 1e-10 防除零（_cross_section_zscore 内部处理）
        - 极端值 clip 到 ±3σ × ±3σ = ±9（实际 IC 验证范围内）
    """
    _logger = get_module_logger(logger_arg)
    df = factor_df.copy()

    required = [_COL_DATE, _COL_RETURN_3D, _COL_AMPLITUDE]
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise ValueError(f"interaction_amplitude 缺失必需列: {missing}")

    weakness = _build_weakness(df, _logger)
    amp_z = _cross_section_zscore(df[_COL_AMPLITUDE], df[_COL_DATE])
    df[_COL_INTERACTION_AMPLITUDE] = weakness * amp_z

    valid_count = int(df[_COL_INTERACTION_AMPLITUDE].notna().sum())
    _logger.info(
        "  interaction_amplitude: valid=%d (%.2f%%)",
        valid_count,
        valid_count / len(df) * 100 if len(df) > 0 else 0.0,
    )
    return df


calculate_interaction_amplitude.required_cols = ["date", "asset", "return_3d", "amplitude"]  # type: ignore[attr-defined]


def calculate_interaction_turnover(
    factor_df: pd.DataFrame,
    *,
    logger_arg: logging.Logger | None = None,
) -> pd.DataFrame:
    """计算交互因子 interaction_turnover = -z_cs(return_3d) × z_cs(turnover_rate)。

    含义: 捕捉"弱势股票中高换手=反弹信号"的条件效应。
    实证全样本 IC≈+0.016（方向="positive"）。

    Args:
        factor_df: 必须包含 date / asset / return_3d / turnover_rate 列
        logger_arg: 日志器

    Returns:
        添加 ``interaction_turnover`` 列的 DataFrame

    边界处理:
        - return_3d 或 turnover_rate 缺失 → 交互值 NaN
        - 截面 std=0 → 加 1e-10 防除零
        - clip ±3σ × ±3σ
    """
    _logger = get_module_logger(logger_arg)
    df = factor_df.copy()

    required = [_COL_DATE, _COL_RETURN_3D, _COL_TURNOVER_RATE]
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise ValueError(f"interaction_turnover 缺失必需列: {missing}")

    weakness = _build_weakness(df, _logger)
    turnover_z = _cross_section_zscore(df[_COL_TURNOVER_RATE], df[_COL_DATE])
    df[_COL_INTERACTION_TURNOVER] = weakness * turnover_z

    valid_count = int(df[_COL_INTERACTION_TURNOVER].notna().sum())
    _logger.info(
        "  interaction_turnover: valid=%d (%.2f%%)",
        valid_count,
        valid_count / len(df) * 100 if len(df) > 0 else 0.0,
    )
    return df


calculate_interaction_turnover.required_cols = ["date", "asset", "return_3d", "turnover_rate"]  # type: ignore[attr-defined]


def calculate_interaction_amp_compression(
    factor_df: pd.DataFrame,
    *,
    logger_arg: logging.Logger | None = None,
) -> pd.DataFrame:
    """计算交互因子 interaction_amp_compression = -z_cs(return_3d) × z_cs(amplitude_compression)。

    含义: 捕捉"弱势股票中振幅收敛=反弹信号"的条件效应。
    实证全样本 IC≈+0.008（方向="positive"，弱信号但维度独立）。

    Args:
        factor_df: 必须包含 date / asset / return_3d / amplitude_compression 列
        logger_arg: 日志器

    Returns:
        添加 ``interaction_amp_compression`` 列的 DataFrame

    边界处理:
        - return_3d 或 amplitude_compression 缺失 → 交互值 NaN
        - 截面 std=0 → 加 1e-10 防除零
        - clip ±3σ × ±3σ

    Note:
        ``amplitude_compression`` 列字符串字面量为 "amplitude_compression"，
        其常量 ``_COL_AMP_COMPRESSION`` 定义在 ``volume_price.py``。本模块
        通过字符串字面量引用，避免反向 import 同包子模块。
    """
    _logger = get_module_logger(logger_arg)
    df = factor_df.copy()

    amp_compression_col = "amplitude_compression"
    required = [_COL_DATE, _COL_RETURN_3D, amp_compression_col]
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise ValueError(f"interaction_amp_compression 缺失必需列: {missing}")

    weakness = _build_weakness(df, _logger)
    amp_comp_z = _cross_section_zscore(df[amp_compression_col], df[_COL_DATE])
    df[_COL_INTERACTION_AMP_COMPRESSION] = weakness * amp_comp_z

    valid_count = int(df[_COL_INTERACTION_AMP_COMPRESSION].notna().sum())
    _logger.info(
        "  interaction_amp_compression: valid=%d (%.2f%%)",
        valid_count,
        valid_count / len(df) * 100 if len(df) > 0 else 0.0,
    )
    return df


calculate_interaction_amp_compression.required_cols = [  # type: ignore[attr-defined]
    "date",
    "asset",
    "return_3d",
    "amplitude_compression",
]
