"""data_fetchers.factor_calculator.tail：尾盘 5 分钟 K 线族因子。

模块定位
========
基于尾盘 5 分钟 K 线数据（14:00-15:00 共 13 根 K 线）的因子族，
反映尾盘价格、量能、量价关系等多维度信号。

公共 API（B4 轮注入）
=====================
- ``calculate_tail_factors(factor_df, ...)``：一次性计算 5 个尾盘因子
  （编排 + I/O，避免重复加载尾盘数据）

输出列：
- ``tail_price_position``：尾盘价格位置 ``[0, 1]``
- ``tail_price_slope``：尾盘趋势斜率（百分比形式）
- ``tail_price_volume_intensity``：尾盘量价强度
- ``tail_volume_acceleration``：尾盘量能加速度（后半段/前半段）
- ``tail_volume_shrink``：尾盘缩量程度 ``[0, 1]``

依赖
====
- 数据源：``data_fetchers/result/tail_trading_data.json.gz``
  （由 ``fetch_tail_trading.py`` 输出）
- ``_common``：``get_module_logger``
- ``numpy`` / ``pandas`` / ``logging`` / ``gzip`` / ``json``

兼容性
======
本模块函数实现与原 ``data_fetchers/factor_generator.py`` v1.42 行为字节级一致。
B 步搬迁拆分：B2（本轮，I/O + 骨架） / B3（5 个 row-level） / B4（编排）。
"""

from __future__ import annotations

import gzip
import json
import logging
from pathlib import Path

import numpy as np
import pandas as pd


__all__: list[str] = []


# ============================================================================
# 尾盘因子常量（私有）
# ============================================================================

# 尾盘数据路径：data_fetchers/result/tail_trading_data.json.gz
# 子包路径计算：__file__ = data_fetchers/factor_calculator/tail.py
# parent.parent = data_fetchers/，与 factor_generator._DEFAULT_RESULT_DIR 等价
_TAIL_TRADING_DATA_PATH = Path(__file__).parent.parent / "result" / "tail_trading_data.json.gz"

# 尾盘 5 分钟 K 线数量：14:00-15:00 共 13 根（含 14:30 / 15:00）
_TAIL_KLINE_COUNT = 13

# 除零阈值：尾盘因子族公用（与原 factor_generator.EPSILON 同值）
_TAIL_EPSILON = 1e-10


# ============================================================================
# 数据加载与基础访问 helper（B2 轮）
# ============================================================================


def _load_tail_trading_data(logger: logging.Logger) -> pd.DataFrame:
    """加载尾盘 5 分钟 K 线数据。

    Args:
        logger: 日志记录器

    Returns:
        包含 ``date`` / ``asset`` / ``prices`` / ``volumes`` / ``tail_high`` /
        ``tail_low`` 列的 DataFrame；文件不存在或损坏时返回空 DataFrame
        （而非抛异常）。

    Note:
        - 文件不存在：warning 日志 + 返回空 DataFrame
        - gzip 损坏 / JSON 解析失败 / 缺 ``data`` 字段：error 日志 + 返回空 DataFrame
        - 上层 ``calculate_tail_factors`` 收到空 DataFrame 时把所有尾盘因子置 NaN
    """
    if not _TAIL_TRADING_DATA_PATH.exists():
        logger.warning("尾盘数据文件不存在: %s，尾盘因子将为 NaN", _TAIL_TRADING_DATA_PATH)
        return pd.DataFrame()

    try:
        with gzip.open(_TAIL_TRADING_DATA_PATH, "rt", encoding="utf-8") as f:
            data = json.load(f)
    except gzip.BadGzipFile as e:
        logger.error("尾盘数据 gzip 文件损坏: %s, 原因: %s", _TAIL_TRADING_DATA_PATH, str(e))
        return pd.DataFrame()
    except json.JSONDecodeError as e:
        logger.error("尾盘数据 JSON 解析失败: %s, 行 %d, 列 %d", _TAIL_TRADING_DATA_PATH, e.lineno, e.colno)
        return pd.DataFrame()

    if "data" not in data:
        logger.error("尾盘数据缺少 'data' 字段: %s", _TAIL_TRADING_DATA_PATH)
        return pd.DataFrame()

    df = pd.DataFrame(data["data"])
    logger.info("尾盘数据加载完成: %d 条记录", len(df))
    return df


def _get_close_price(prices: list | None) -> float:
    """从尾盘 5 分钟 K 线价格列表中取尾盘收盘价（``prices[-1]``）。

    Args:
        prices: 13 根 5 分钟 K 线收盘价列表

    Returns:
        尾盘收盘价；非列表 / 长度不足 → ``np.nan``
    """
    if not isinstance(prices, list):
        return np.nan
    if len(prices) < _TAIL_KLINE_COUNT:
        return np.nan
    return prices[-1]
