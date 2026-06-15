"""data_fetchers.factor_calculator.delta：止跌信号差分族因子（v1.13）。

模块定位
========
v1.13 (2026-06-11) 新增的 4 个差分因子，统一用于"止跌信号"维度：把
连续型源因子（amplitude / turnover_surge / tail_price_position /
tail_volume_shrink）通过 ``_calculate_delta`` 转换为差分形式，捕捉转折信号。

公共 API（design.md §5.4）
==========================
- ``calculate_amplitude_delta(factor_df, ...)``：``amplitude`` 一阶差分
- ``calculate_turnover_surge_delta(factor_df, ...)``：``turnover_surge`` 一阶差分
- ``calculate_tail_price_position_delta(factor_df, ...)``：``tail_price_position`` 一阶差分
- ``calculate_tail_volume_shrink_delta(factor_df, ...)``：``tail_volume_shrink`` 一阶差分

依赖
====
- ``_common``：列名、``_calculate_delta`` 半公开 helper、``get_module_logger``
- 4 个函数都是 ``_calculate_delta`` 的薄包装；``_calculate_delta`` 仍住
  ``_common.py``（被多个子模块复用）

输入数据来源
============
- ``amplitude`` / ``turnover_surge``：本包 ``calculate_amplitude`` /
  ``calculate_turnover_surge`` 的输出（已搬到 ``momentum.py`` / ``basic.py``）
- ``tail_price_position`` / ``tail_volume_shrink``：``data_fetchers
  /fetch_tail_trading.py`` 的输出列，**不是** ``factor_calculator`` 的产出；
  ``delta.py`` 只读取这些列做差分

兼容性
======
本模块函数实现与原 ``factor_calculator.py`` v1.17 字节级一致；PR-3 通过
``temporary/factor_calculator_baseline_fingerprint.json`` 的 22 个因子
指纹验证（panel_hash=ecd3e754e9b348cd 不变）。
"""

from __future__ import annotations

import logging

import pandas as pd

from ._common import (
    _COL_AMPLITUDE,
    _COL_AMPLITUDE_DELTA,
    _COL_TAIL_PRICE_POSITION_DELTA,
    _COL_TAIL_VOLUME_SHRINK_DELTA,
    _COL_TURNOVER_SURGE,
    _COL_TURNOVER_SURGE_DELTA,
    _calculate_delta,
)


__all__: list[str] = []


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


calculate_amplitude_delta.required_cols = ["amplitude"]  # type: ignore[attr-defined]


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


calculate_turnover_surge_delta.required_cols = ["turnover_surge"]  # type: ignore[attr-defined]


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


calculate_tail_price_position_delta.required_cols = ["tail_price_position"]  # type: ignore[attr-defined]


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


calculate_tail_volume_shrink_delta.required_cols = ["tail_volume_shrink"]  # type: ignore[attr-defined]
