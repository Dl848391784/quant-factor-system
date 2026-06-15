#!/usr/bin/env python3
"""
因子计算模块 - 统一因子计算逻辑

整合所有因子计算函数，提供单一数据源：
- RSI（Wilder 标准）
- Volume Ratio（量比）
- Bollinger %B（布林带）
- KDJ J（随机指标）
- Turnover Surge（换手率突增）

遵循 PROJECT.md 规范：
- 使用 Python 标准库 logging 模块
- 公共模块函数接收 logger 参数
- 函数入口必须先 .copy()，避免修改原始数据

版本历史：
- v1.0 (2026-05-27): 初始版本
  - 导入分组规范化（标准库/第三方库/类型导入）
  - logger 参数化（使用 logger_arg 命名）
  - __all__ 修复（移除私有函数）
  - docstring Example 补全（6个公共函数）
  - 流程文档创建 docs/factor_calculator_flow.md
  - 测试文件创建 test_cases/test_factor_calculator.py
- v1.1 (2026-05-27): 第二轮深度优化
  - 版本历史添加（参考 cache_manager.py）
  - 常量命名私有化 DEFAULT_* → _DEFAULT_*
  - __all__ 移到导入后位置（遵循 cache_manager.py 规范）
- v1.2 (2026-05-27): 第三轮深度优化
  - 内部函数 `_calculate_ewm_with_initial` docstring 补全（Args/Returns/Note）
  - 新增私有常量 `_DEFAULT_VOLUME_RATIO_WINDOW`、`_DEFAULT_FORWARD_RETURN_SHIFT`
  - 消除硬编码默认值（window=5、shift=1）
- v1.3 (2026-05-27): 第四轮深度优化
  - 提取输入列名常量（`_COL_CLOSE`、`_COL_DATE`、`_COL_ASSET`、`_COL_HIGH`、`_COL_LOW`、`_COL_TURNOVER_RATE`）
  - 提取输出列名常量（`_COL_BOLLINGER_PB`、`_COL_KDJ_J`、`_COL_TURNOVER_SURGE`）
  - 提取魔法数字常量（`_RSI_NEUTRAL_VALUE`、`_RSI_MAX_VALUE`、`_BOLLINGER_NEUTRAL_VALUE`、`_KD_NEUTRAL_VALUE`）
  - 提取业务阈值常量（`_TURNOVER_SURGE_THRESHOLD`、`_DAILY_RETURN_THRESHOLD`）
  - 消除所有硬编码字符串和魔法数字
- v1.4 (2026-05-27): 第五轮深度优化（8个问题修复）
  - 问题1（已不存在）：if _logger: 无效判断在当前代码中不存在
  - 问题2：删除 calculate_rsi 末尾 fillna，保留前 period 天 NaN 让调用方自行处理
  - 问题3：calculate_rsi/volume_ratio/forward_return 三个 Series 函数入口添加 .copy()
  - 问题4：_calculate_ewm_with_initial 删除 ignore_index=True，保留原始索引
  - 问题5：EPSILON → _EPSILON 私有化并从 __all__ 移除
  - 问题6：calculate_bollinger_pb safe_band_width 计算改用 where+clip（mask 对 NaN 无效）
  - 问题7：calculate_bollinger_pb 异常处理顺序调整（先 abnormal 后 narrow）
  - 问题8：calculate_turnover_surge 业务筛选日志改为 debug 级别（非异常统计）
- v1.5 (2026-05-27): 删除换手率突增筛选条件
  - 移除 `_TURNOVER_SURGE_THRESHOLD` 和 `_DAILY_RETURN_THRESHOLD` 常量
  - 移除涨跌幅计算和业务筛选逻辑（surge>1 且 return>0）
  - 所有有效计算的因子值均保留，不再筛选
- v1.6 (2026-05-29): 新增全天价格位置因子
  - 添加 `calculate_price_position()` 函数
  - 添加 `_COL_PRICE_POSITION` 和 `_DEFAULT_PRICE_POSITION_EPSILON` 常量
  - 边界处理：振幅为零时设为 0.5（中位）
v1.7 (2026-05-29): 新增振幅因子
  - 添加 `calculate_amplitude()` 函数
  - 添加 `_COL_AMPLITUDE` 和 `_DEFAULT_AMPLITUDE_EPSILON` 常量
  - 边界处理：close=0 时设为 NaN（无效数据）
v1.8 (2026-05-29): 新增3日累计涨幅因子
  - 添加 `calculate_return_3d()` 函数
  - 添加 `_COL_RETURN_3D` 和 `_DEFAULT_RETURN_3D_WINDOW` 常量
  - 边界处理：前3日数据设为 NaN（历史不足）
v1.9 (2026-05-29): 新增5日累计涨幅因子
  - 添加 `calculate_return_5d()` 函数
  - 添加 `_COL_RETURN_5D` 和 `_DEFAULT_RETURN_5D_WINDOW` 常量
  - 边界处理：前5日数据设为 NaN（历史不足）
v1.10 (2026-06-05): 新增动量强度因子
  - 添加 `calculate_momentum_strength()` 函数
  - 添加 `_COL_MOMENTUM_STRENGTH` 和 `_DEFAULT_MOMENTUM_STRENGTH_WINDOW` 常量
  - 公式：momentum_strength = return_5d / std(return_1d, 5日)
  - 边界处理：std=0 → NaN（除零保护），前5日 → NaN（rolling window 不足）
v1.13 (2026-06-11): 新增止跌信号差分因子（4个）
  - 添加 `_calculate_delta()` 通用差分辅助函数
  - 添加 `calculate_amplitude_delta()` 振幅差分因子
  - 添加 `calculate_turnover_surge_delta()` 换手突增差分因子
  - 添加 `calculate_tail_price_position_delta()` 尾盘位置差分因子
  - 添加 `calculate_tail_volume_shrink_delta()` 尾盘缩量差分因子
  - 添加4个输出列名常量（_COL_*_DELTA）
  - 遵循 H5: IC方向不预判，由数据决定

作者: 云瑶
创建日期: 2026-05-27
"""

# ============================================================================
# 标准库导入
# ============================================================================
import logging
from pathlib import Path

# ============================================================================
# 类型导入
# ============================================================================
import numpy as np

# ============================================================================
# 第三方库导入
# ============================================================================
import pandas as pd

# ============================================================================
# 包内底座 import（PR-2a：常量、logger、半公开 helper 已抽至 _common）
# ============================================================================
from ._common import (  # noqa: F401  允许此模块 re-export 这些符号
    _BOLLINGER_NEUTRAL_VALUE,
    _COL_AMPLITUDE,
    _COL_AMPLITUDE_DELTA,
    _COL_ASSET,
    _COL_BOLLINGER_PB,
    _COL_CLOSE,
    _COL_DATE,
    _COL_HIGH,
    _COL_INDUSTRY_AMPLITUDE_TREND,
    _COL_INDUSTRY_EARNINGS_GROWTH,
    _COL_INDUSTRY_MOMENTUM_5D,
    _COL_INDUSTRY_PE_TREND,
    _COL_INDUSTRY_ROE_TREND,
    _COL_INDUSTRY_TURNOVER_TREND,
    _COL_KDJ_J,
    _COL_LOW,
    _COL_MA5_DEVIATION,
    _COL_NEAR_HIGH_RATIO_5,
    _COL_PAST_RETURN_1D,
    _COL_POSITIVE_DAY_RATIO_5,
    _COL_PRICE_POSITION,
    _COL_RETURN_3D,
    _COL_RETURN_5D,
    _COL_TAIL_PRICE_POSITION_DELTA,
    _COL_TAIL_VOLUME_SHRINK_DELTA,
    _COL_TURNOVER_RATE,
    _COL_TURNOVER_SURGE,
    _COL_TURNOVER_SURGE_DELTA,
    _COL_VOLUME_PRICE_STRENGTH,
    _DEFAULT_AMPLITUDE_EPSILON,
    _DEFAULT_AMPLITUDE_TREND_DENOMINATOR_MIN,
    _DEFAULT_BOLLINGER_K,
    _DEFAULT_BOLLINGER_N,
    _DEFAULT_FORWARD_RETURN_SHIFT,
    _DEFAULT_INDUSTRY_WINDOW,
    _DEFAULT_KDJ_M1,
    _DEFAULT_KDJ_M2,
    _DEFAULT_KDJ_N,
    _DEFAULT_MIN_INDUSTRY_STOCKS,
    _DEFAULT_PAST_RETURN_1D_WINDOW,
    _DEFAULT_PRICE_POSITION_EPSILON,
    _DEFAULT_RETURN_3D_WINDOW,
    _DEFAULT_RETURN_5D_WINDOW,
    _DEFAULT_RSI_PERIOD,
    _DEFAULT_SURGE_WINDOW,
    _DEFAULT_TREND_DENOMINATOR_MIN,
    _DEFAULT_VOLUME_RATIO_WINDOW,
    _EPSILON,
    _KD_NEUTRAL_VALUE,
    _MODULE_LOGGER,
    _RSI_MAX_VALUE,
    _RSI_NEUTRAL_VALUE,
    DEFAULT_BOLLINGER_K,
    DEFAULT_BOLLINGER_N,
    DEFAULT_FORWARD_RETURN_SHIFT,
    DEFAULT_KDJ_M1,
    DEFAULT_KDJ_M2,
    DEFAULT_KDJ_N,
    DEFAULT_RSI_PERIOD,
    DEFAULT_SURGE_WINDOW,
    DEFAULT_VOLUME_RATIO_WINDOW,
    _calculate_delta,
    _calculate_ewm_with_initial,
    _per_asset_transform,
    _wilder_smoothing_rsi,
    get_module_logger,
)

# ============================================================================
# 子模块 basic re-import（PR-2b：basic 因子已搬到 .basic，本文件 re-export 维持
# `from ._legacy import *` 通配兼容 + __all__ 中 7 个 calculate_* 名称仍有效）
# ============================================================================
from .basic import (  # noqa: F401
    calculate_bollinger_pb,
    calculate_forward_return,
    calculate_kdj_j,
    calculate_rsi,
    calculate_rsi_df,
    calculate_turnover_surge,
    calculate_volume_ratio,
)


# ============================================================================
# 模块导出（遵循 MODULE.md 约束 60：不含私有名称）
# ============================================================================
__all__ = [
    "calculate_rsi",
    "calculate_volume_ratio",
    "calculate_forward_return",
    "calculate_bollinger_pb",
    "calculate_kdj_j",
    "calculate_turnover_surge",
    "calculate_price_position",  # v1.6 新增
    "calculate_amplitude",  # v1.7 新增
    "calculate_past_return_1d",  # v1.10 新增
    "calculate_return_3d",  # v1.8 新增
    "calculate_return_5d",  # v1.9 新增
    "calculate_momentum_strength",  # v1.10 新增
    "calculate_overnight_return",  # v1.11 新增
    "calculate_rsi_df",  # v1.12 新增
    "calculate_amplitude_delta",  # v1.13 新增
    "calculate_turnover_surge_delta",  # v1.13 新增
    "calculate_tail_price_position_delta",  # v1.13 新增
    "calculate_tail_volume_shrink_delta",  # v1.13 新增
    "calculate_volume_price_strength",  # v1.14 新增：量价齐升因子
    "calculate_positive_day_ratio_5",  # v1.14 新增：5日阳线比例因子
    "calculate_ma5_deviation",  # v1.14 新增：5日均线偏离度因子
    "calculate_near_high_ratio_5",  # v1.14 新增：近5日高低位置因子
    "calculate_industry_momentum_5d",  # v1.15 新增：行业5日动量因子
    "calculate_industry_turnover_trend",  # v1.15 新增：行业换手率趋势因子
    "calculate_industry_amplitude_trend",  # v1.15 新增：行业振幅趋势因子
    "calculate_industry_roe_trend",  # v1.16 新增：行业ROE趋势因子
    "calculate_industry_earnings_growth",  # v1.16 新增：行业盈利增长因子
    "calculate_industry_pe_trend",  # v1.16 新增：行业PE趋势因子
    "calculate_capital_flow_ratio_trend",  # v1.17 新增：资金流占比趋势因子（方案C）
    "calculate_capital_flow_intensity",  # v1.17 新增：资金流强度因子（方案C）
    # 公共常量别名（向下兼容 ic_kdj_j 等脚本的导入）
    "DEFAULT_RSI_PERIOD",
    "DEFAULT_BOLLINGER_N",
    "DEFAULT_BOLLINGER_K",
    "DEFAULT_KDJ_N",
    "DEFAULT_KDJ_M1",
    "DEFAULT_KDJ_M2",
    "DEFAULT_SURGE_WINDOW",
    "DEFAULT_VOLUME_RATIO_WINDOW",
    "DEFAULT_FORWARD_RETURN_SHIFT",
]

# ============================================================================
# 模块级常量、fallback logger 与 get_module_logger 已迁移至 _common（PR-2a，design.md §5.1）
# 本文件通过顶部 `from ._common import (...)` re-bind，原定义已删除
# ============================================================================


# ============================================================================
# RSI 计算（Wilder 标准）
# 半公开 helper `_wilder_smoothing_rsi` 已迁移至 _common（PR-2a）
# ============================================================================


# (PR-2b) calculate_rsi: 已迁移至 .basic 子模块（design.md §5.2）；
# 由本文件顶部 `from .basic import calculate_rsi` 维持向后兼容。


# ============================================================================
# Volume Ratio 计算（量比）
# ============================================================================


# (PR-2b) calculate_volume_ratio: 已迁移至 .basic 子模块（design.md §5.2）；
# 由本文件顶部 `from .basic import calculate_volume_ratio` 维持向后兼容。


# ============================================================================
# Forward Return 计算（前瞻收益）
# ============================================================================


# (PR-2b) calculate_forward_return: 已迁移至 .basic 子模块（design.md §5.2）；
# 由本文件顶部 `from .basic import calculate_forward_return` 维持向后兼容。


# ============================================================================
# 通用工具：按 asset 分组的低内存 transform 替代
# 半公开 helper `_per_asset_transform` 已迁移至 _common（PR-2a）
# ============================================================================


# ============================================================================
# Bollinger %B 计算（布林带）
# ============================================================================


# (PR-2b) calculate_bollinger_pb: 已迁移至 .basic 子模块（design.md §5.2）；
# 由本文件顶部 `from .basic import calculate_bollinger_pb` 维持向后兼容。


# ============================================================================
# KDJ J 计算（随机指标）
# 半公开 helper `_calculate_ewm_with_initial` 已迁移至 _common（PR-2a）
# ============================================================================


# (PR-2b) calculate_kdj_j: 已迁移至 .basic 子模块（design.md §5.2）；
# 由本文件顶部 `from .basic import calculate_kdj_j` 维持向后兼容。


# ============================================================================
# Turnover Surge 计算（换手率突增）
# ============================================================================


# (PR-2b) calculate_turnover_surge: 已迁移至 .basic 子模块（design.md §5.2）；
# 由本文件顶部 `from .basic import calculate_turnover_surge` 维持向后兼容。


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
        _logger.warning(f"检测到 {zero_count} 个振幅为零的记录（high=low），price_position 设为 0.5（中位）")

    # 计算价格位置
    df[_COL_PRICE_POSITION] = np.where(
        zero_range_mask,
        0.5,  # 振幅为零时设为中位
        (df[_COL_CLOSE] - df[_COL_LOW]) / range_val,
    )

    _logger.info(f"price_position 计算完成，共 {len(df)} 条记录")

    return df


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
        _logger.warning(f"检测到 {zero_count} 个收盘价为零的记录，amplitude 设为 NaN（无效数据）")

    # 计算振幅因子
    # close=0 → NaN，否则计算 (high - low) / close
    df[_COL_AMPLITUDE] = np.where(
        zero_close_mask,
        np.nan,  # 收盘价为零设为 NaN
        range_val / df[_COL_CLOSE],
    )

    _logger.info(f"amplitude 计算完成，共 {len(df)} 条记录")

    return df


# 振幅因子所需输入列（供调用方读取，避免硬编码耦合）
# pyright: ignore[reportFunctionMemberAccess]
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

    _logger.info(f"past_return_1d (window={window}) 计算完成，共 {len(df)} 条记录")

    return df


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

    _logger.info(f"return_3d (window={window}) 计算完成，共 {len(df)} 条记录")

    return df


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

    _logger.info(f"return_5d (window={window}) 计算完成，共 {len(df)} 条记录")

    return df


# ============================================================================
# 因子所需输入列（供调用方读取，避免硬编码耦合）
# ============================================================================

# 已添加：calculate_amplitude.required_cols = ['close', 'high', 'low']

calculate_price_position.required_cols = ["close", "high", "low"]  # type: ignore[attr-defined]

calculate_past_return_1d.required_cols = ["close", "asset", "date"]  # type: ignore[attr-defined]

calculate_return_3d.required_cols = ["close", "asset", "date"]  # type: ignore[attr-defined]

calculate_return_5d.required_cols = ["close", "asset", "date"]  # type: ignore[attr-defined]


# ============================================================================
# 动量强度因子计算（v1.10 新增）
# ============================================================================

_COL_MOMENTUM_STRENGTH = "momentum_strength"
_DEFAULT_MOMENTUM_STRENGTH_WINDOW = 5  # 5日滚动窗口
_MOMENTUM_STRENGTH_STD_MIN = 0.01  # 日收益率标准差下限（防止均匀涨跌时比值爆炸）


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

    _logger.info(f"momentum_strength (window={window}) 计算完成，共 {len(df)} 条记录")

    return df


calculate_momentum_strength.required_cols = ["close", "return_5d", "asset", "date"]  # type: ignore[attr-defined]


# ============================================================================
# 隔夜收益率因子计算
# ============================================================================

_COL_OPEN = "open"
_COL_OVERNIGHT_RET = "overnight_ret"


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
        _logger.warning(f"发现 {invalid_mask.sum()} 个异常收盘价（<{_EPSILON}），已设为 NaN")

    _logger.info(f"overnight_ret 计算完成，共 {len(df)} 条记录")

    return df


calculate_overnight_return.required_cols = ["open", "close"]  # type: ignore[attr-defined]


# ============================================================================
# RSI DataFrame 版本（用于分层回测）
# ============================================================================


# (PR-2b) calculate_rsi_df: 已迁移至 .basic 子模块（design.md §5.2）；
# 由本文件顶部 `from .basic import calculate_rsi_df` 维持向后兼容。


# ============================================================================
# 止跌信号差分因子（Reversal Delta Factors）
# v1.13 (2026-06-11): 新增4个差分因子
#   - amplitude_delta: 振幅变化（止跌放量信号）
#   - turnover_surge_delta: 换手突增变化（关注回升信号）
#   - tail_price_position_delta: 尾盘位置变化（买盘进场信号）
#   - tail_volume_shrink_delta: 尾盘缩量变化（资金介入信号）
#
# 通用计算模式：base_col(T) - base_col(T-1)，按asset分组shift(1)
# 遵循 H5: 因子方向不预判，IC方向由数据决定
# 半公开 helper `_calculate_delta` 已迁移至 _common（PR-2a）
# ============================================================================


def calculate_amplitude_delta(factor_df: pd.DataFrame, logger_arg: logging.Logger | None = None) -> pd.DataFrame:
    """振幅差分因子：amplitude(T) - amplitude(T-1)

    含义：振幅从低开始回升 = 止跌放量信号；振幅继续下降 = 闷跌加剧。

    参数:
        factor_df: 包含 date, asset, amplitude 列的 DataFrame
        logger_arg: 调用方传入的 logger

    返回:
        添加 amplitude_delta 列的 DataFrame

    边界处理:
        - 第一日无前值 → NaN（自然排除）
        - amplitude 为 NaN → delta 也为 NaN（传播）

    Example:
        >>> df = pd.DataFrame({"asset": ["A", "A"], "date": ["d1", "d2"], "amplitude": [0.04, 0.06]})
        >>> result = calculate_amplitude_delta(df)
        >>> pd.isna(result["amplitude_delta"].iloc[0])
        True
        >>> result["amplitude_delta"].iloc[1]  # 0.06 - 0.04
        0.02
    """
    return _calculate_delta(factor_df, _COL_AMPLITUDE, _COL_AMPLITUDE_DELTA, logger_arg)


def calculate_turnover_surge_delta(factor_df: pd.DataFrame, logger_arg: logging.Logger | None = None) -> pd.DataFrame:
    """换手突增差分因子：turnover_surge(T) - turnover_surge(T-1)

    含义：换手从低开始增加 = 市场关注回升；继续下降 = 无人关注。

    参数:
        factor_df: 包含 date, asset, turnover_surge 列的 DataFrame
        logger_arg: 调用方传入的 logger

    返回:
        添加 turnover_surge_delta 列的 DataFrame

    边界处理:
        - 第一日无前值 → NaN（自然排除）
        - turnover_surge 为 NaN → delta 也为 NaN（传播）

    Example:
        >>> df = pd.DataFrame({"asset": ["A", "A"], "date": ["d1", "d2"], "turnover_surge": [0.5, 0.8]})
        >>> result = calculate_turnover_surge_delta(df)
        >>> result["turnover_surge_delta"].iloc[1]  # 0.8 - 0.5
        0.3
    """
    return _calculate_delta(factor_df, _COL_TURNOVER_SURGE, _COL_TURNOVER_SURGE_DELTA, logger_arg)


def calculate_tail_price_position_delta(
    factor_df: pd.DataFrame, logger_arg: logging.Logger | None = None
) -> pd.DataFrame:
    """尾盘位置差分因子：tail_price_position(T) - tail_price_position(T-1)

    含义：尾盘从最低价回升 = 买盘开始进场；继续走低 = 卖方主导。

    参数:
        factor_df: 包含 date, asset, tail_price_position 列的 DataFrame
        logger_arg: 调用方传入的 logger

    返回:
        添加 tail_price_position_delta 列的 DataFrame

    边界处理:
        - 第一日无前值 → NaN（自然排除）
        - tail_price_position 为 NaN → delta 也为 NaN（传播）

    Example:
        >>> df = pd.DataFrame({"asset": ["A", "A"], "date": ["d1", "d2"], "tail_price_position": [0.0, 0.5]})
        >>> result = calculate_tail_price_position_delta(df)
        >>> result["tail_price_position_delta"].iloc[1]  # 0.5 - 0.0
        0.5
    """
    return _calculate_delta(factor_df, "tail_price_position", _COL_TAIL_PRICE_POSITION_DELTA, logger_arg)


def calculate_tail_volume_shrink_delta(
    factor_df: pd.DataFrame, logger_arg: logging.Logger | None = None
) -> pd.DataFrame:
    """尾盘缩量差分因子：tail_volume_shrink(T) - tail_volume_shrink(T-1)

    含义：尾盘从缩量转放量 = 资金开始介入；继续缩量 = 冷清。

    参数:
        factor_df: 包含 date, asset, tail_volume_shrink 列的 DataFrame
        logger_arg: 调用方传入的 logger

    返回:
        添加 tail_volume_shrink_delta 列的 DataFrame

    边界处理:
        - 第一日无前值 → NaN（自然排除）
        - tail_volume_shrink 为 NaN → delta 也为 NaN（传播）

    Example:
        >>> df = pd.DataFrame({"asset": ["A", "A"], "date": ["d1", "d2"], "tail_volume_shrink": [0.2, 0.3]})
        >>> result = calculate_tail_volume_shrink_delta(df)
        >>> result["tail_volume_shrink_delta"].iloc[1]  # 0.3 - 0.2
        0.1
    """
    return _calculate_delta(factor_df, "tail_volume_shrink", _COL_TAIL_VOLUME_SHRINK_DELTA, logger_arg)


calculate_amplitude_delta.required_cols = ["amplitude"]  # type: ignore[attr-defined]
calculate_turnover_surge_delta.required_cols = ["turnover_surge"]  # type: ignore[attr-defined]
calculate_tail_price_position_delta.required_cols = ["tail_price_position"]  # type: ignore[attr-defined]
calculate_tail_volume_shrink_delta.required_cols = ["tail_volume_shrink"]  # type: ignore[attr-defined]

# ============================================================================
# 方向性因子（Directional Factors）
# v1.14 (2026-06-11): 新增4个方向性因子
#   - volume_price_strength: 量价齐升强度（上涨+放量=强势）
#   - positive_day_ratio_5: 近5日阳线比例（趋势连续性）
#   - ma5_deviation: 5日均线偏离度（趋势位置）
#   - near_high_ratio_5: 近5日高低位置（相对强弱）
#
# 设计目的：与现有均值回归因子（IC负向偏好弱势股）形成维度互补
# 遵循 H5: IC方向不预判，由数据决定
# ============================================================================


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

    df = factor_df.copy()

    # 计算日内涨幅 (close - open) / open
    intraday_return = (df[_COL_CLOSE] - df[_COL_OPEN]) / df[_COL_OPEN]

    # 乘以换手突增系数
    df[_COL_VOLUME_PRICE_STRENGTH] = intraday_return * df["turnover_surge"]

    valid_count = int(df[_COL_VOLUME_PRICE_STRENGTH].notna().sum())
    _logger.info(
        "  有效 %s: %d (%.2f%%)",
        _COL_VOLUME_PRICE_STRENGTH,
        valid_count,
        valid_count / len(df) * 100 if len(df) > 0 else 0,
    )

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
    - 前4天无完整5日窗口 → NaN（自然排除）
    - 全NaN组 → NaN

    遵循 H5: IC方向不预判
    """
    _logger = get_module_logger(logger_arg)

    df = factor_df.copy()
    df = df.sort_values([_COL_ASSET, _COL_DATE])

    # 按asset分组计算日收益率
    daily_return = df.groupby(_COL_ASSET)[_COL_CLOSE].diff()

    # 阳线标记（日收益率 > 0）
    positive_mask = (daily_return > 0).astype(float)

    # rolling 5日窗口计算阳线比例，min_periods=5确保前4天为NaN
    ratio = positive_mask.groupby(df[_COL_ASSET]).rolling(5, min_periods=5).mean().reset_index(level=0, drop=True)

    df[_COL_POSITIVE_DAY_RATIO_5] = ratio

    valid_count = int(df[_COL_POSITIVE_DAY_RATIO_5].notna().sum())
    _logger.info(
        "  有效 %s: %d (%.2f%%)",
        _COL_POSITIVE_DAY_RATIO_5,
        valid_count,
        valid_count / len(df) * 100 if len(df) > 0 else 0,
    )

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
    - 比率型因子分母趋近零 → clip(lower=0.01)保护（遵循 Pitfall #47）

    遵循 H5: IC方向不预判
    """
    _logger = get_module_logger(logger_arg)

    df = factor_df.copy()
    df = df.sort_values([_COL_ASSET, _COL_DATE])

    # 计算5日移动平均线
    ma5 = df.groupby(_COL_ASSET)[_COL_CLOSE].rolling(5, min_periods=5).mean().reset_index(level=0, drop=True)

    # MA5 = 0 时替换为 NaN（避免除零）
    ma5_safe = ma5.replace(0, np.nan)

    # 比率型因子分母趋近零保护（遵循 Pitfall #47）
    ma5_safe = ma5_safe.clip(lower=0.01)

    # 计算偏离度
    df[_COL_MA5_DEVIATION] = (df[_COL_CLOSE] - ma5_safe) / ma5_safe

    valid_count = int(df[_COL_MA5_DEVIATION].notna().sum())
    _logger.info(
        "  有效 %s: %d (%.2f%%)",
        _COL_MA5_DEVIATION,
        valid_count,
        valid_count / len(df) * 100 if len(df) > 0 else 0,
    )

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
    - 涨跌停一字板: max=min → diff=0 → position=1.0（遵循 Pitfall #45）
      涨停: 收盘价=近5日最高=最强信号 → 1.0
      跌停: 收盘价=近5日最低=最弱信号 → 但此时close=min, diff=0 → 也返回1.0
      注意: 与price_position不同，这里5日窗口的涨跌停处理需进一步验证

    遵循 H5: IC方向不预判
    """
    _logger = get_module_logger(logger_arg)

    df = factor_df.copy()
    df = df.sort_values([_COL_ASSET, _COL_DATE])

    # 计算5日滚动最高价和最低价
    roll_max = df.groupby(_COL_ASSET)[_COL_CLOSE].rolling(5, min_periods=5).max().reset_index(level=0, drop=True)
    roll_min = df.groupby(_COL_ASSET)[_COL_CLOSE].rolling(5, min_periods=5).min().reset_index(level=0, drop=True)

    # 计算高低价差
    diff = roll_max - roll_min

    # 涨跌停一字板处理：diff=0时，收盘价在区间最高点 → position=1.0（遵循 Pitfall #45）
    position = np.where(
        diff == 0,
        1.0,  # 涨跌停：收盘价锁定在极端位置 → 最强信号
        (df[_COL_CLOSE] - roll_min) / diff,
    )

    df[_COL_NEAR_HIGH_RATIO_5] = position

    valid_count = int(df[_COL_NEAR_HIGH_RATIO_5].notna().sum())
    _logger.info(
        "  有效 %s: %d (%.2f%%)",
        _COL_NEAR_HIGH_RATIO_5,
        valid_count,
        valid_count / len(df) * 100 if len(df) > 0 else 0,
    )

    return df


calculate_near_high_ratio_5.required_cols = ["date", "asset", "close"]  # type: ignore[attr-defined]


# ============================================================================
# 行业级别方向性因子（Pattern 14: Industry-Level Directional Factor）
# ============================================================================
#
# 核心认知：方向性信号在行业层面而非个股层面。
# 因子值 = 行业聚合值赋给该行业每只个股（同行业股票因子值相同）。
# 遵循 H5：IC方向不预判，即使IC为负仍有维度互补价值。
# 比率型因子分母保护：遵循 Pitfall #47（clip下限避免极端值）。
# ============================================================================


def _add_industry_column(
    df: pd.DataFrame,
    _logger: logging.Logger,
) -> pd.DataFrame:
    """为 DataFrame 添加 industry 列（从 fetch_industry 映射）

    Args:
        df: 包含 asset 列的 DataFrame
        _logger: 日志记录器

    Returns:
        DataFrame 新增 industry 列，未知股票赋 '其他'

    Note:
        使用 fetch_industry.get_industry_map() 获取行业映射，
        避免重复加载（模块级缓存+线程安全）。
        如果 industry 列已存在则跳过添加（避免重复添加）。
    """
    # 如果 industry 列已存在则跳过
    if "industry" in df.columns:
        return df

    try:
        from data_fetchers.fetch_industry import get_industry_map
    except ImportError:
        from fetch_industry import get_industry_map  # noqa: E402

    industry_map = get_industry_map()

    # 映射：asset → industry
    df["industry"] = df[_COL_ASSET].map(lambda code: industry_map.get(str(code), {}).get("industry", "其他"))

    unknown_count = int((df["industry"] == "其他").sum())
    if unknown_count > 0:
        _logger.warning(
            "  行业未知股票数: %d (%.2f%%)",
            unknown_count,
            unknown_count / len(df) * 100 if len(df) > 0 else 0,
        )

    return df


def calculate_industry_momentum_5d(
    factor_df: pd.DataFrame,
    *,
    logger_arg: logging.Logger | None = None,
) -> pd.DataFrame:
    """计算行业5日动量因子

    公式:
      1. 添加 industry 列（从行业映射）
      2. 计算个股 past_return_1d = close / prev_close - 1（按 asset 分组 shift）
      3. 按 (industry, date) 分组 → mean(past_return_1d) → 5日滚动均值
      4. 同行业所有股票赋相同行业动量值

    含义:
      - 高正值: 行业整体5日上涨趋势（行业配置偏向该行业）
      - 高负值: 行业整体5日下跌趋势（行业配置规避该行业）
      - 近零值: 行业整体横盘无趋势

    边界处理:
      - industry 未知 → 赋 '其他' 行业
      - 行业股票数 < 5 → 该日期该行业因子值 NaN（min_periods=5）
      - past_return_1d 为 NaN → 行业均值自动跳过（pandas mean NaN-safe）

    遵循 H5: IC方向不预判
    实测结论: 行业层面IC=+0.026（正值），方向性信号存在

    required_cols: ["date", "asset", "close"]
    """
    _logger = get_module_logger(logger_arg)

    df = factor_df.copy()

    # Step 1: 添加 industry 列
    _logger.info("  Step 1: 添加行业分类列...")
    df = _add_industry_column(df, _logger)

    # Step 2: 计算个股日收益率（按 asset 分组 shift）
    _logger.info("  Step 2: 计算个股日收益率...")
    df = df.sort_values([_COL_ASSET, _COL_DATE])
    prev_close = df.groupby(_COL_ASSET)[_COL_CLOSE].shift(1)
    df["past_return_1d_calc"] = (df[_COL_CLOSE] / prev_close) - 1  # 中间列，最终删除

    # Step 3: 按 (industry, date) 分组 → 5日滚动均值
    _logger.info("  Step 3: 按行业分组计算5日动量...")
    industry_daily_mean = df.groupby(["industry", _COL_DATE])["past_return_1d_calc"].mean().reset_index()
    industry_daily_mean = industry_daily_mean.sort_values(["industry", _COL_DATE])

    # 5日滚动均值（按行业分组）
    industry_daily_mean[_COL_INDUSTRY_MOMENTUM_5D] = (
        industry_daily_mean.groupby("industry")["past_return_1d_calc"]
        .rolling(_DEFAULT_INDUSTRY_WINDOW, min_periods=_DEFAULT_MIN_INDUSTRY_STOCKS)
        .mean()
        .reset_index(level=0, drop=True)
    )

    # Step 4: 行业动量值赋给每只个股
    _logger.info("  Step 4: 行业动量赋给个股...")
    # 创建 industry → (date → momentum) 映射
    momentum_map = industry_daily_mean.set_index(["industry", _COL_DATE])[_COL_INDUSTRY_MOMENTUM_5D]

    # 将行业动量值赋给原始 df
    df = df.sort_values([_COL_ASSET, _COL_DATE])  # 确保排序与原始一致
    df[_COL_INDUSTRY_MOMENTUM_5D] = df.set_index(["industry", _COL_DATE]).index.map(
        lambda idx: momentum_map.get(idx, float("nan"))
    )

    # 删除中间列
    df = df.drop(columns=["past_return_1d_calc"])

    valid_count = int(df[_COL_INDUSTRY_MOMENTUM_5D].notna().sum())
    _logger.info(
        "  有效 %s: %d (%.2f%%)",
        _COL_INDUSTRY_MOMENTUM_5D,
        valid_count,
        valid_count / len(df) * 100 if len(df) > 0 else 0,
    )

    return df


calculate_industry_momentum_5d.required_cols = ["date", "asset", "close"]  # type: ignore[attr-defined]


def calculate_industry_turnover_trend(
    factor_df: pd.DataFrame,
    *,
    logger_arg: logging.Logger | None = None,
) -> pd.DataFrame:
    """计算行业换手率趋势因子

    公式:
      1. 添加 industry 列
      2. 按 (industry, date) 分组 → mean(turnover_rate) → 行业日均换手率
      3. industry_turnover_trend = turnover_avg(t) / turnover_avg(t-1) - 1
      4. 同行业所有股票赋相同行业换手趋势值

    含义:
      - 高正值: 行业换手率显著上升（市场关注度增加）
      - 高负值: 行业换手率显著下降（市场关注度下降）
      - 近零值: 行业换手率平稳

    边界处理:
      - industry 未知 → 赋 '其他'
      - turnover_avg(t-1) 极小 → clip(lower=0.001) 避免极端比值（遵循 Pitfall #47）
      - 行业股票数 < 5 → NaN

    遵循 H5: IC方向不预判

    required_cols: ["date", "asset", "turnover_rate"]
    """
    _logger = get_module_logger(logger_arg)

    df = factor_df.copy()

    # Step 1: 添加 industry 列
    _logger.info("  Step 1: 添加行业分类列...")
    df = _add_industry_column(df, _logger)

    # Step 2: 按 (industry, date) 分组 → mean(turnover_rate)
    _logger.info("  Step 2: 按行业分组计算日均换手率...")
    industry_daily_turnover = df.groupby(["industry", _COL_DATE])[_COL_TURNOVER_RATE].mean().reset_index()
    industry_daily_turnover = industry_daily_turnover.sort_values(["industry", _COL_DATE])

    # Step 3: 计算换手率趋势 = today_avg / yesterday_avg - 1
    _logger.info("  Step 3: 计算换手率趋势（比率型因子）...")
    prev_avg = industry_daily_turnover.groupby("industry")[_COL_TURNOVER_RATE].shift(1)
    # 分母保护：clip 避免极端比值（遵循 Pitfall #47）
    prev_avg_safe = prev_avg.clip(lower=_DEFAULT_TREND_DENOMINATOR_MIN)
    industry_daily_turnover[_COL_INDUSTRY_TURNOVER_TREND] = (
        industry_daily_turnover[_COL_TURNOVER_RATE] / prev_avg_safe - 1
    )
    # 分母原值为0时，clip后仍会产生极端值 → 设NaN（无意义趋势）
    industry_daily_turnover.loc[prev_avg == 0, _COL_INDUSTRY_TURNOVER_TREND] = float("nan")

    # Step 4: 行业换手趋势赋给每只个股
    _logger.info("  Step 4: 行业换手趋势赋给个股...")
    trend_map = industry_daily_turnover.set_index(["industry", _COL_DATE])[_COL_INDUSTRY_TURNOVER_TREND]

    df[_COL_INDUSTRY_TURNOVER_TREND] = df.set_index(["industry", _COL_DATE]).index.map(
        lambda idx: trend_map.get(idx, float("nan"))
    )

    valid_count = int(df[_COL_INDUSTRY_TURNOVER_TREND].notna().sum())
    _logger.info(
        "  有效 %s: %d (%.2f%%)",
        _COL_INDUSTRY_TURNOVER_TREND,
        valid_count,
        valid_count / len(df) * 100 if len(df) > 0 else 0,
    )

    return df


calculate_industry_turnover_trend.required_cols = ["date", "asset", "turnover_rate"]  # type: ignore[attr-defined]


def calculate_industry_amplitude_trend(
    factor_df: pd.DataFrame,
    *,
    logger_arg: logging.Logger | None = None,
) -> pd.DataFrame:
    """计算行业振幅趋势因子

    公式:
      1. 添加 industry 列
      2. 按 (industry, date) 分组 → mean(amplitude) → 行业日均振幅
      3. industry_amplitude_trend = amplitude_avg(t) / amplitude_avg(t-1) - 1
      4. 同行业所有股票赋相同行业振幅趋势值

    含义:
      - 高正值: 行业振幅显著上升（波动性增加）
      - 高负值: 行业振幅显著下降（波动性收敛）
      - 近零值: 行业振幅平稳

    边界处理:
      - industry 未知 → 赋 '其他'
      - amplitude_avg(t-1) 极小 → clip(lower=0.01) 避免极端比值
      - amplitude_avg(t-1) = 0 → NaN（涨跌停无意义趋势）
      - 行业股票数 < 5 → NaN

    遵循 H5: IC方向不预判

    required_cols: ["date", "asset", "amplitude"]
    """
    _logger = get_module_logger(logger_arg)

    df = factor_df.copy()

    # Step 1: 添加 industry 列
    _logger.info("  Step 1: 添加行业分类列...")
    df = _add_industry_column(df, _logger)

    # Step 2: 按 (industry, date) 分组 → mean(amplitude)
    _logger.info("  Step 2: 按行业分组计算日均振幅...")
    industry_daily_amplitude = df.groupby(["industry", _COL_DATE])[_COL_AMPLITUDE].mean().reset_index()
    industry_daily_amplitude = industry_daily_amplitude.sort_values(["industry", _COL_DATE])

    # Step 3: 计算振幅趋势 = today_avg / yesterday_avg - 1
    _logger.info("  Step 3: 计算振幅趋势（比率型因子）...")
    prev_avg = industry_daily_amplitude.groupby("industry")[_COL_AMPLITUDE].shift(1)
    # 分母保护：振幅=0意味着涨跌停，clip 下限 0.01（遵循 Pitfall #47）
    prev_avg_safe = prev_avg.clip(lower=_DEFAULT_AMPLITUDE_TREND_DENOMINATOR_MIN)
    industry_daily_amplitude[_COL_INDUSTRY_AMPLITUDE_TREND] = (
        industry_daily_amplitude[_COL_AMPLITUDE] / prev_avg_safe - 1
    )
    # 分母原值为0时 → NaN（涨跌停场景趋势无意义）
    industry_daily_amplitude.loc[prev_avg == 0, _COL_INDUSTRY_AMPLITUDE_TREND] = float("nan")

    # Step 4: 行业振幅趋势赋给每只个股
    _logger.info("  Step 4: 行业振幅趋势赋给个股...")
    trend_map = industry_daily_amplitude.set_index(["industry", _COL_DATE])[_COL_INDUSTRY_AMPLITUDE_TREND]

    df[_COL_INDUSTRY_AMPLITUDE_TREND] = df.set_index(["industry", _COL_DATE]).index.map(
        lambda idx: trend_map.get(idx, float("nan"))
    )

    valid_count = int(df[_COL_INDUSTRY_AMPLITUDE_TREND].notna().sum())
    _logger.info(
        "  有效 %s: %d (%.2f%%)",
        _COL_INDUSTRY_AMPLITUDE_TREND,
        valid_count,
        valid_count / len(df) * 100 if len(df) > 0 else 0,
    )

    return df


calculate_industry_amplitude_trend.required_cols = ["date", "asset", "amplitude"]  # type: ignore[attr-defined]


# ============================================================================
# 行业基本面动量因子（Pattern 14 + 基本面维度，v1.16 2026-06-12）
# 数据来源: financial_data.json.gz（akshare stock_financial_abstract_ths）
# 季度数据 → merge_asof 前推填充对齐日频 → 行业聚合赋个股
# ============================================================================

# 行业财务因子列名常量已迁移至 _common（PR-2a，design.md §5.1）：
#   _COL_INDUSTRY_ROE_TREND / _COL_INDUSTRY_EARNINGS_GROWTH / _COL_INDUSTRY_PE_TREND

# 财务数据缓存路径（遵循 paths.py 单一来源）
_FINANCIAL_DATA_PATH: str | None = None  # 默认 None，调用时从 paths.py 获取

# PE 比率型因子分母保护（遵循 Pitfall #47）
_PE_DENOMINATOR_MIN = 0.01  # EPS 年化值 clip 下限


def _get_financial_data_path(logger_arg: logging.Logger | None = None) -> Path:
    """获取财务数据缓存路径（遵循 paths.py 单一来源）

    Returns:
        财务数据缓存文件路径
    """
    global _FINANCIAL_DATA_PATH
    if _FINANCIAL_DATA_PATH is not None:
        return Path(_FINANCIAL_DATA_PATH)
    try:
        from data_fetchers.common import get_module_result_dir
    except ImportError:
        from common import get_module_result_dir
    result_dir = get_module_result_dir()
    _FINANCIAL_DATA_PATH = str(result_dir / "financial_data.json.gz")
    return Path(_FINANCIAL_DATA_PATH)


def _load_financial_data(
    financial_data_path: Path | str | None = None,
    logger_arg: logging.Logger | None = None,
) -> pd.DataFrame:
    """加载财务数据缓存，返回 DataFrame（asset, report_date, roe, eps, ...）

    Args:
        financial_data_path: 财务数据缓存路径（None 时使用默认路径）
        logger_arg: 调用方传入的 logger（可选）

    Returns:
        财务数据 DataFrame，包含 asset, report_date, roe, basic_eps, annualized_eps 等列

    Raises:
        FileNotFoundError: 缓存文件不存在
        RuntimeError: 缓存数据为空或格式错误
    """
    _logger = get_module_logger(logger_arg)

    path = Path(financial_data_path) if financial_data_path else _get_financial_data_path(logger_arg)
    if not path.exists():
        raise FileNotFoundError(f"财务数据缓存不存在: {path}，请先运行 fetch_financial.py")

    import gzip
    import json

    with gzip.open(path, "rt") as f:
        raw_data = json.load(f)

    data_list = raw_data.get("data", [])
    if not data_list:
        raise RuntimeError(f"财务数据缓存为空: {path}")

    df = pd.DataFrame(data_list)

    # 确保关键列存在
    required_cols = ["asset", "report_date"]
    missing = [c for c in required_cols if c not in df.columns]
    if missing:
        raise RuntimeError(f"财务数据缺少必需列: {missing}")

    # 显式释放 JSON 原始数据（遵循 R16）
    del raw_data, data_list
    import gc

    gc.collect()

    _logger.info("加载财务数据: %d 条记录, %d 只股票", len(df), len(set(df["asset"])))
    return df


def _merge_asof_financial(
    factor_df: pd.DataFrame,
    financial_df: pd.DataFrame,
    value_col: str,
    output_col: str,
    logger_arg: logging.Logger | None = None,
) -> pd.Series:
    """前推填充对齐季度财务数据到日频（merge_asof 模式）

    Args:
        factor_df: 日频因子 DataFrame（含 date, asset 列）
        financial_df: 季度财务 DataFrame（含 asset, report_date, value_col 列）
        value_col: 财务数据中的值列名（如 'roe', 'basic_eps'）
        output_col: 输出到 factor_df 的列名（如 'roe_daily', 'eps_daily'）
        logger_arg: logger（可选）

    Returns:
        与 factor_df 行数对齐的 Series，前推填充的财务值

    Note: 使用 pd.merge_asof(direction='backward') 实现 point-forward fill
    """
    _logger = get_module_logger(logger_arg)

    # 准备合并所需的数据
    fin_subset = financial_df[["asset", "report_date", value_col]].copy()
    fin_subset = fin_subset.rename(columns={"report_date": "date"})
    fin_subset["date"] = pd.to_datetime(fin_subset["date"])

    # 确保 factor_df 的 date 列是 datetime 类型
    daily_dates = pd.to_datetime(factor_df[_COL_DATE])

    # merge_asof: 交易日取最近已发布的财报数据（前推填充）
    merged = pd.merge_asof(
        factor_df[[_COL_ASSET]].assign(date=daily_dates).sort_values("date"),
        fin_subset.sort_values("date"),
        by=_COL_ASSET,
        on="date",
        direction="backward",  # Point-forward: 取最近已发布的财报
    )

    return merged[value_col].rename(output_col)


def calculate_industry_roe_trend(
    factor_df: pd.DataFrame,
    *,
    financial_data_path: str | Path | None = None,
    logger_arg: logging.Logger | None = None,
) -> pd.DataFrame:
    """计算行业ROE趋势因子（行业ΔROE赋个股）

    公式:
      1. 加载季度财务数据 → ROE per (asset, report_date)
      2. Point-forward fill → 对齐日频 (merge_asof direction='backward')
      3. ΔROE = ROE(current_quarter) - ROE(previous_quarter)（按 asset 分组 shift）
      4. groupby(industry, date) → mean(ΔROE) → 赋给同行业每只个股

    含义:
      - 高正值: 行业盈利能力改善（ROE上升趋势）
      - 高负值: 行业盈利能力恶化（ROE下降趋势）
      - 近零值: 行业盈利能力稳定

    边界处理:
      - industry 未知 → 赋 '其他'
      - 财务数据缺失 → ΔROE 为 NaN（自然排除）
      - ROE 前推填充: 首日无前值 → NaN（不做填充）
      - ΔROE = NaN → 行业均值自动跳过（pandas mean NaN-safe）

    遵循 H5: IC方向不预判
    预期: 行业基本面改善 → IC正向（偏好盈利改善的行业）

    required_cols: ["date", "asset"]
    """
    _logger = get_module_logger(logger_arg)

    df = factor_df.copy()

    # Step 1: 加载财务数据
    _logger.info("  Step 1: 加载季度财务数据...")
    financial_df = _load_financial_data(financial_data_path, logger_arg)

    # Step 2: 前推填充对齐日频
    _logger.info("  Step 2: 前推填充ROE对齐日频...")
    roe_daily = _merge_asof_financial(df, financial_df, "roe", "roe_daily", logger_arg)
    # ⚠️ 类型修复: 同花顺 API 返回的 roe 可能是 Decimal 类型，必须转为 float
    df["roe_daily"] = pd.to_numeric(roe_daily, errors="coerce")

    # Step 3: 计算 ΔROE = ROE(current_quarter) - ROE(previous_quarter)
    _logger.info("  Step 3: 计算ΔROE（季度间变化）...")
    df = df.sort_values([_COL_ASSET, _COL_DATE])
    prev_roe = df.groupby(_COL_ASSET)["roe_daily"].shift(1)
    df["delta_roe"] = df["roe_daily"] - prev_roe
    # 首日无前值 → NaN（自然排除，不做填充）

    # Step 4: 添加 industry 列
    _logger.info("  Step 4: 添加行业分类列...")
    df = _add_industry_column(df, _logger)

    # Step 5: 行业聚合赋个股
    _logger.info("  Step 5: 行业ΔROE赋给个股...")
    industry_delta_roe = df.groupby(["industry", _COL_DATE])["delta_roe"].mean().reset_index()
    trend_map = industry_delta_roe.set_index(["industry", _COL_DATE])["delta_roe"]

    df[_COL_INDUSTRY_ROE_TREND] = df.set_index(["industry", _COL_DATE]).index.map(
        lambda idx: trend_map.get(idx, float("nan"))
    )

    # 删除中间列
    df = df.drop(columns=["roe_daily", "delta_roe"])

    valid_count = int(df[_COL_INDUSTRY_ROE_TREND].notna().sum())
    _logger.info(
        "  有效 %s: %d (%.2f%%)",
        _COL_INDUSTRY_ROE_TREND,
        valid_count,
        valid_count / len(df) * 100 if len(df) > 0 else 0,
    )

    return df


calculate_industry_roe_trend.required_cols = ["date", "asset"]  # type: ignore[attr-defined]


def calculate_industry_earnings_growth(
    factor_df: pd.DataFrame,
    *,
    financial_data_path: str | Path | None = None,
    logger_arg: logging.Logger | None = None,
) -> pd.DataFrame:
    """计算行业盈利增长因子（行业净利润增长率赋个股）

    公式:
      1. 加载季度财务数据 → net_profit_growth_yoy per (asset, report_date)
      2. Point-forward fill → 对齐日频 (merge_asof direction='backward')
      3. groupby(industry, date) → mean(net_profit_growth_yoy) → 赋给同行业每只个股

    含义:
      - 高正值: 行业盈利高增长（净利润同比增速大）
      - 高负值: 行业盈利下滑（净利润同比增速为负）
      - 近零值: 行业盈利平稳

    边界处理:
      - industry 未知 → 赋 '其他'
      - 财务数据缺失 → NaN（自然排除）
      - 银行/金融股净利润增长率可能为 NaN（会计差异，正常现象）

    遵循 H5: IC方向不预判

    required_cols: ["date", "asset"]
    """
    _logger = get_module_logger(logger_arg)

    df = factor_df.copy()

    # Step 1: 加载财务数据
    _logger.info("  Step 1: 加载季度财务数据...")
    financial_df = _load_financial_data(financial_data_path, logger_arg)

    # Step 2: 前推填充对齐日频
    _logger.info("  Step 2: 前推填充净利润增长率对齐日频...")
    growth_daily = _merge_asof_financial(df, financial_df, "net_profit_growth_yoy", "growth_daily", logger_arg)
    # ⚠️ 类型修复: 同花顺 API 返回的 net_profit_growth_yoy 可能是 Decimal 类型，必须转为 float
    df["growth_daily"] = pd.to_numeric(growth_daily, errors="coerce")

    # Step 3: 添加 industry 列
    _logger.info("  Step 3: 添加行业分类列...")
    df = _add_industry_column(df, _logger)

    # Step 4: 行业聚合赋个股
    _logger.info("  Step 4: 行业净利润增长率赋给个股...")
    industry_growth = df.groupby(["industry", _COL_DATE])["growth_daily"].mean().reset_index()
    trend_map = industry_growth.set_index(["industry", _COL_DATE])["growth_daily"]

    df[_COL_INDUSTRY_EARNINGS_GROWTH] = df.set_index(["industry", _COL_DATE]).index.map(
        lambda idx: trend_map.get(idx, float("nan"))
    )

    # 删除中间列
    df = df.drop(columns=["growth_daily"])

    valid_count = int(df[_COL_INDUSTRY_EARNINGS_GROWTH].notna().sum())
    _logger.info(
        "  有效 %s: %d (%.2f%%)",
        _COL_INDUSTRY_EARNINGS_GROWTH,
        valid_count,
        valid_count / len(df) * 100 if len(df) > 0 else 0,
    )

    return df


calculate_industry_earnings_growth.required_cols = ["date", "asset"]  # type: ignore[attr-defined]


def calculate_industry_pe_trend(
    factor_df: pd.DataFrame,
    *,
    financial_data_path: str | Path | None = None,
    logger_arg: logging.Logger | None = None,
) -> pd.DataFrame:
    """计算行业PE趋势因子（行业ΔPE赋个股）

    公式:
      1. 加载季度财务数据 → annualized_eps per (asset, report_date)
      2. Point-forward fill → 对齐日频 (merge_asof direction='backward')
      3. PE = close / annualized_eps（分母 clip 保护，遵循 Pitfall #47）
      4. ΔPE = PE(current_quarter) - PE(previous_quarter)（按 asset 分组 shift）
      5. groupby(industry, date) → mean(ΔPE) → 赋给同行业每只个股

    含义:
      - 高正值: 行业估值上升（PE上升趋势，市场给予更高估值）
      - 高负值: 行业估值下降（PE下降趋势，市场降低估值）
      - 近零值: 行业估值稳定

    边界处理:
      - industry 未知 → 赋 '其他'
      - annualized_eps 缺失 → PE = NaN
      - annualized_eps 极小 → clip(lower=0.01) 保护（遵循 Pitfall #47）
      - annualized_eps ≤ 0 → PE = NaN（亏损公司 PE 无意义）
      - PE 首日无前值 → ΔPE = NaN

    ⚠️ 比率型因子: 分母 annualized_eps 可能趋近零 → clip(lower=0.01) 保护
    ⚠️ 亏损公司（eps≤0）PE为负，趋势仍有意义但需特殊处理

    遵循 H5: IC方向不预判

    required_cols: ["date", "asset", "close"]
    """
    _logger = get_module_logger(logger_arg)

    df = factor_df.copy()

    # Step 1: 加载财务数据
    _logger.info("  Step 1: 加载季度财务数据...")
    financial_df = _load_financial_data(financial_data_path, logger_arg)

    # Step 2: 前推填充对齐日频
    _logger.info("  Step 2: 前推填充年化EPS对齐日频...")
    eps_daily = _merge_asof_financial(df, financial_df, "annualized_eps", "eps_daily", logger_arg)
    # ⚠️ 类型修复: 同花顺 API 返回的 annualized_eps 可能是 Decimal 类型
    # Decimal 除 float 会报 TypeError，必须先转为 float
    df["eps_daily"] = pd.to_numeric(eps_daily, errors="coerce")

    # Step 3: 计算 PE = close / annualized_eps
    _logger.info("  Step 3: 计算PE（比率型因子，分母clip保护）...")
    eps_safe = df["eps_daily"].clip(lower=_PE_DENOMINATOR_MIN)
    df["pe_daily"] = df[_COL_CLOSE] / eps_safe
    # annualized_eps ≤ 0（亏损公司）→ PE = NaN（负PE趋势意义存疑，排除）
    df.loc[df["eps_daily"] <= 0, "pe_daily"] = float("nan")
    # annualized_eps 原值为 NaN → PE = NaN
    df.loc[df["eps_daily"].isna(), "pe_daily"] = float("nan")

    # Step 4: 计算 ΔPE = PE(current) - PE(previous)
    _logger.info("  Step 4: 计算ΔPE（季度间变化）...")
    df = df.sort_values([_COL_ASSET, _COL_DATE])
    prev_pe = df.groupby(_COL_ASSET)["pe_daily"].shift(1)
    df["delta_pe"] = df["pe_daily"] - prev_pe

    # Step 5: 添加 industry 列
    _logger.info("  Step 5: 添加行业分类列...")
    df = _add_industry_column(df, _logger)

    # Step 6: 行业聚合赋个股
    _logger.info("  Step 6: 行业ΔPE赋给个股...")
    industry_delta_pe = df.groupby(["industry", _COL_DATE])["delta_pe"].mean().reset_index()
    trend_map = industry_delta_pe.set_index(["industry", _COL_DATE])["delta_pe"]

    df[_COL_INDUSTRY_PE_TREND] = df.set_index(["industry", _COL_DATE]).index.map(
        lambda idx: trend_map.get(idx, float("nan"))
    )

    # 删除中间列
    df = df.drop(columns=["eps_daily", "pe_daily", "delta_pe"])

    valid_count = int(df[_COL_INDUSTRY_PE_TREND].notna().sum())
    _logger.info(
        "  有效 %s: %d (%.2f%%)",
        _COL_INDUSTRY_PE_TREND,
        valid_count,
        valid_count / len(df) * 100 if len(df) > 0 else 0,
    )

    return df


calculate_industry_pe_trend.required_cols = ["date", "asset", "close"]  # type: ignore[attr-defined]


# ============================================================================
# 资金流因子（方案C，v1.17 2026-06-12）
# 数据来源: fund_flow_data.json.gz（akshare stock_individual_fund_flow）
# 每只股票约120交易日数据（API限制），日频数据直接可用无需前推填充
# ============================================================================

# 新增列名常量
_COL_CAPITAL_FLOW_RATIO_TREND = "capital_flow_ratio_trend"
_COL_CAPITAL_FLOW_INTENSITY = "capital_flow_intensity"

# 资金流数据缓存路径
_FUND_FLOW_DATA_PATH: str | None = None


def _get_fund_flow_data_path(logger_arg: logging.Logger | None = None) -> Path:
    """获取资金流数据缓存路径（遵循 paths.py 单一来源）"""
    global _FUND_FLOW_DATA_PATH
    if _FUND_FLOW_DATA_PATH is not None:
        return Path(_FUND_FLOW_DATA_PATH)
    try:
        from data_fetchers.common import get_module_result_dir
    except ImportError:
        from common import get_module_result_dir
    result_dir = get_module_result_dir()
    _FUND_FLOW_DATA_PATH = str(result_dir / "fund_flow_data.json.gz")
    return Path(_FUND_FLOW_DATA_PATH)


def _load_fund_flow_data(
    fund_flow_path: Path | str | None = None,
    logger_arg: logging.Logger | None = None,
) -> pd.DataFrame:
    """加载资金流数据缓存，返回 DataFrame

    Args:
        fund_flow_path: 资金流数据缓存路径（None 时使用默认路径）
        logger_arg: 调用方传入的 logger（可选）

    Returns:
        资金流 DataFrame，包含 asset, date, main_inflow_ratio, main_inflow_amount, total_volume 等列

    Raises:
        FileNotFoundError: 缓存文件不存在
        RuntimeError: 缓存数据为空或格式错误
    """
    _logger = get_module_logger(logger_arg)

    path = Path(fund_flow_path) if fund_flow_path else _get_fund_flow_data_path(logger_arg)
    if not path.exists():
        raise FileNotFoundError(f"资金流数据缓存不存在: {path}，请先运行 fetch_fund_flow.py")

    import gzip
    import json

    # 检测文件是否为 gzip 格式（支持 plain JSON 和 gzip 两种）
    is_gzip = True
    try:
        with gzip.open(path, "rt") as f:
            raw_data = json.load(f)
    except gzip.BadGzipFile:
        # plain JSON 格式（兼容早期写入版本）
        is_gzip = False
        with open(path) as f:
            raw_data = json.load(f)

    data_list = raw_data.get("data", [])
    if not data_list:
        raise RuntimeError(f"资金流数据缓存为空: {path}")

    df = pd.DataFrame(data_list)

    required_cols = ["asset", "date"]
    missing = [c for c in required_cols if c not in df.columns]
    if missing:
        raise RuntimeError(f"资金流数据缺少必需列: {missing}")

    del raw_data, data_list
    import gc

    gc.collect()

    _logger.info("加载资金流数据: %d 条记录, %d 只股票", len(df), len(set(df["asset"])))
    return df


def _merge_fund_flow_daily(
    factor_df: pd.DataFrame,
    fund_flow_df: pd.DataFrame,
    value_col: str,
    output_col: str,
    logger_arg: logging.Logger | None = None,
) -> pd.Series:
    """合并日频资金流数据到因子 DataFrame

    Args:
        factor_df: 日频因子 DataFrame（含 date, asset 列）
        fund_flow_df: 资金流 DataFrame（含 asset, date, value_col 列）
        value_col: 资金流数据中的值列名
        output_col: 输出列名
        logger_arg: logger（可选）

    Returns:
        与 factor_df 行数对齐的 Series
    """
    _logger = get_module_logger(logger_arg)

    # 日期格式对齐
    ff_subset = fund_flow_df[["asset", "date", value_col]].copy()
    ff_subset["date"] = ff_subset["date"].astype(str)

    # 精确匹配（资金流数据是日频，无需 merge_asof）
    merged = factor_df[[_COL_DATE, _COL_ASSET]].copy()
    merged[_COL_DATE] = merged[_COL_DATE].astype(str)

    result = merged.merge(
        ff_subset,
        left_on=[_COL_DATE, _COL_ASSET],
        right_on=["date", "asset"],
        how="left",
    )[value_col].rename(output_col)

    return result


def calculate_capital_flow_ratio_trend(
    factor_df: pd.DataFrame,
    *,
    fund_flow_path: str | Path | None = None,
    logger_arg: logging.Logger | None = None,
) -> pd.DataFrame:
    """计算资金流占比趋势因子（行业主力净流入占比Δ赋个股）

    公式:
      1. 加载资金流数据 → main_inflow_ratio per (asset, date)
      2. 精确匹配日频数据到 factor_df（资金流数据已是日频，无需前推填充）
      3. Δratio = main_inflow_ratio(current) - main_inflow_ratio(previous)（按 asset 分组 shift(1)）
      4. groupby(industry, date) → mean(Δratio) → 赋给同行业每只个股

    含义:
      - 高正值: 行业主力资金持续流入（净流入占比上升）
      - 高负值: 行业主力资金持续流出（净流入占比下降）
      - 近零值: 行业资金流向稳定

    边界处理:
      - industry 未知 → 赋 '其他'
      - 资金流数据缺失 → Δratio 为 NaN
      - 资金流数据约120交易日（API限制），超过此范围的日期 → NaN
      - Δratio 首日无前值 → NaN

    ⚠️ 数据覆盖限制: 每只股票约120交易日，早期日期必然缺失

    遵循 H5: IC方向不预判

    required_cols: ["date", "asset"]
    """
    _logger = get_module_logger(logger_arg)

    df = factor_df.copy()

    # Step 1: 加载资金流数据
    _logger.info("  Step 1: 加载资金流数据...")
    fund_flow_df = _load_fund_flow_data(fund_flow_path, logger_arg)

    # Step 2: 合并日频资金流数据
    _logger.info("  Step 2: 合并主力净流入占比到因子数据...")
    ratio_daily = _merge_fund_flow_daily(df, fund_flow_df, "main_inflow_ratio", "ratio_daily", logger_arg)
    df["ratio_daily"] = ratio_daily.values if len(ratio_daily) == len(df) else [float("nan")] * len(df)

    # Step 3: 计算 Δratio = ratio(current) - ratio(previous)
    _logger.info("  Step 3: 计算Δ主力净流入占比...")
    df = df.sort_values([_COL_ASSET, _COL_DATE])
    prev_ratio = df.groupby(_COL_ASSET)["ratio_daily"].shift(1)
    df["delta_ratio"] = df["ratio_daily"] - prev_ratio

    # Step 4: 添加 industry 列
    _logger.info("  Step 4: 添加行业分类列...")
    df = _add_industry_column(df, _logger)

    # Step 5: 行业聚合赋个股
    _logger.info("  Step 5: 行业Δ主力净流入占比赋给个股...")
    industry_delta_ratio = df.groupby(["industry", _COL_DATE])["delta_ratio"].mean().reset_index()
    trend_map = industry_delta_ratio.set_index(["industry", _COL_DATE])["delta_ratio"]

    df[_COL_CAPITAL_FLOW_RATIO_TREND] = df.set_index(["industry", _COL_DATE]).index.map(
        lambda idx: trend_map.get(idx, float("nan"))
    )

    # 删除中间列
    df = df.drop(columns=["ratio_daily", "delta_ratio"])

    valid_count = int(df[_COL_CAPITAL_FLOW_RATIO_TREND].notna().sum())
    _logger.info(
        "  有效 %s: %d (%.2f%%)",
        _COL_CAPITAL_FLOW_RATIO_TREND,
        valid_count,
        valid_count / len(df) * 100 if len(df) > 0 else 0,
    )

    return df


calculate_capital_flow_ratio_trend.required_cols = ["date", "asset"]  # type: ignore[attr-defined]


def calculate_capital_flow_intensity(
    factor_df: pd.DataFrame,
    *,
    fund_flow_path: str | Path | None = None,
    logger_arg: logging.Logger | None = None,
) -> pd.DataFrame:
    """计算资金流强度因子（行业主力流入绝对额占比赋个股）

    公式:
      1. 加载资金流数据 → main_inflow_amount, total_volume per (asset, date)
      2. intensity = |main_inflow_amount| / total_volume（主力流入占成交额的绝对比例）
      3. 精确匹配日频数据到 factor_df
      4. groupby(industry, date) → mean(intensity) → 赋给同行业每只个股

    含义:
      - 高值: 行业主力资金活跃度高（主力参与成交的比例大）
      - 低值: 行业主力资金活跃度低（散户主导，主力参与少）
      - 0值: 行业无主力资金流入流出

    边界处理:
      - industry 未知 → 赋 '其他'
      - total_volume = 0 或 NaN → intensity = NaN（除零保护）
      - 资金流数据约120交易日（API限制），超过此范围 → NaN

    ⚠️ 数据覆盖限制: 同 capital_flow_ratio_trend
    ⚠️ 比率型因子: 分母 total_volume 可能为零 → NaN 处理

    遵循 H5: IC方向不预判

    required_cols: ["date", "asset"]
    """
    _logger = get_module_logger(logger_arg)

    df = factor_df.copy()

    # Step 1: 加载资金流数据
    _logger.info("  Step 1: 加载资金流数据...")
    fund_flow_df = _load_fund_flow_data(fund_flow_path, logger_arg)

    # Step 2: 计算 intensity = |main_inflow_amount| / total_volume
    _logger.info("  Step 2: 计算资金流强度...")
    # 先合并 main_inflow_amount 和 total_volume
    amount_daily = _merge_fund_flow_daily(df, fund_flow_df, "main_inflow_amount", "amount_daily", logger_arg)
    volume_daily = _merge_fund_flow_daily(df, fund_flow_df, "total_volume", "volume_daily", logger_arg)
    df["amount_daily"] = amount_daily.values if len(amount_daily) == len(df) else [float("nan")] * len(df)
    df["volume_daily"] = volume_daily.values if len(volume_daily) == len(df) else [float("nan")] * len(df)

    # intensity = |main_inflow_amount| / total_volume
    df["intensity"] = df["amount_daily"].abs() / df["volume_daily"]
    # total_volume = 0 或 NaN → intensity = NaN
    df.loc[df["volume_daily"] == 0, "intensity"] = float("nan")
    df.loc[df["volume_daily"].isna(), "intensity"] = float("nan")
    df.loc[df["amount_daily"].isna(), "intensity"] = float("nan")

    # Step 3: 添加 industry 列
    _logger.info("  Step 3: 添加行业分类列...")
    df = _add_industry_column(df, _logger)

    # Step 4: 行业聚合赋个股
    _logger.info("  Step 4: 行业资金流强度赋给个股...")
    industry_intensity = df.groupby(["industry", _COL_DATE])["intensity"].mean().reset_index()
    trend_map = industry_intensity.set_index(["industry", _COL_DATE])["intensity"]

    df[_COL_CAPITAL_FLOW_INTENSITY] = df.set_index(["industry", _COL_DATE]).index.map(
        lambda idx: trend_map.get(idx, float("nan"))
    )

    # 删除中间列
    df = df.drop(columns=["amount_daily", "volume_daily", "intensity"])

    valid_count = int(df[_COL_CAPITAL_FLOW_INTENSITY].notna().sum())
    _logger.info(
        "  有效 %s: %d (%.2f%%)",
        _COL_CAPITAL_FLOW_INTENSITY,
        valid_count,
        valid_count / len(df) * 100 if len(df) > 0 else 0,
    )

    return df


calculate_capital_flow_intensity.required_cols = ["date", "asset"]  # type: ignore[attr-defined]
