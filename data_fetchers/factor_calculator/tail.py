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

from ._common import get_module_logger


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


# ============================================================================
# row-level 因子计算（B3 轮，私有 helper）
# ============================================================================


def _calc_price_position(
    close_price: float,
    tail_high: float,
    tail_low: float,
    daily_close: float | None = None,
    daily_high: float | None = None,
    daily_low: float | None = None,
) -> float:
    """计算尾盘价格位置。

    公式:
    - 尾盘价格位置 = (收盘价 - 尾盘最低价) / (尾盘最高价 - 尾盘最低价)
    - 理论范围 [0, 1]

    涨跌停处理（v1.39）:
    - 当 tail_high == tail_low（零波动）时，公式分母为零 → 0/0 无定义
    - 涨停：尾盘价格锁定在涨停板，收盘价=区间最高点 → position = 1.0（最强信号）
    - 跌停：尾盘价格锁定在跌停板，收盘价=区间最低点 → position = 0.0（最弱信号）
    - 判断方法：close == daily_high → 涨停方向 → 1.0；close == daily_low → 跌停方向 → 0.0
    - 极端罕见无交易且非涨跌停 → 0.5（中性，无信号）

    Args:
        close_price: 尾盘收盘价
        tail_high: 尾盘最高价
        tail_low: 尾盘最低价
        daily_close: 日线收盘价（涨跌停判断需要，可选）
        daily_high: 日线最高价（涨跌停判断需要，可选）
        daily_low: 日线最低价（涨跌停判断需要，可选）

    Returns:
        尾盘价格位置，理论范围 [0, 1]，或 NaN（输入缺失）
    """
    if pd.isna(close_price) or pd.isna(tail_high) or pd.isna(tail_low):
        return np.nan
    price_range = tail_high - tail_low
    if abs(price_range) < _TAIL_EPSILON:
        # v1.39: 零波动不是缺失数据——涨跌停是极端明确的信号
        # 涨停：收盘价在区间最高点 → position = 1.0
        # 跌停：收盘价在区间最低点 → position = 0.0
        # 判断依据：日线 close 与 high/low 的关系
        if (
            daily_close is not None
            and not pd.isna(daily_close)
            and daily_high is not None
            and not pd.isna(daily_high)
            and daily_low is not None
            and not pd.isna(daily_low)
        ):
            if daily_close == daily_high:
                # 涨停（含一字涨停）：收盘价=日线最高 → 尾盘位置=1.0
                return 1.0
            if daily_close == daily_low:
                # 跌停（含一字跌停）：收盘价=日线最低 → 尾盘位置=0.0
                return 0.0
            # 极端罕见：零波动但非涨跌停（如尾盘无成交但日内有波动）
            # 中性填充：position = 0.5
            return 0.5
        # 日线数据缺失时无法判断方向，仍返回 NaN
        return np.nan
    return (close_price - tail_low) / price_range


def _calc_tail_price_slope(prices: list | None) -> float:
    """计算尾盘趋势斜率（百分比形式）。

    公式:
    - 线性回归：对 prices 数组做回归，得到 slope
    - 百分比斜率：factor_value = slope / mean_price

    Args:
        prices: 13 根 5 分钟 K 线收盘价列表

    Returns:
        百分比斜率，或 NaN（数据不完整 / 除零）
    """
    if not isinstance(prices, list):
        return np.nan
    if len(prices) < _TAIL_KLINE_COUNT:
        return np.nan

    Y = np.array(prices)
    if np.any(np.isnan(Y)):
        return np.nan

    X = np.arange(_TAIL_KLINE_COUNT)
    try:
        slope, _ = np.polyfit(X, Y, 1)
    except np.linalg.LinAlgError:
        return np.nan

    mean_price = np.mean(Y)
    if abs(mean_price) < _TAIL_EPSILON:
        return np.nan

    return slope / mean_price


def _calc_tail_price_volume_intensity(
    prices: list | None,
    volumes: list | None,
    total_volume: float | None,
) -> float:
    """计算尾盘量价强度。

    公式:
    - 尾盘涨跌幅 = (prices[-1] - prices[0]) / prices[0]
    - 尾盘量比 = sum(volumes) / volume
    - 尾盘量价强度 = 尾盘涨跌幅 × 尾盘量比

    Args:
        prices: 13 根 5 分钟 K 线收盘价列表
        volumes: 13 根 5 分钟 K 线成交量列表
        total_volume: 全天成交量

    Returns:
        尾盘量价强度，或 NaN（数据不完整 / 除零）
    """
    # 类型守卫：检查 None
    if prices is None or volumes is None or total_volume is None:
        return np.nan
    if not isinstance(prices, list) or not isinstance(volumes, list):
        return np.nan
    if len(prices) < _TAIL_KLINE_COUNT or len(volumes) < _TAIL_KLINE_COUNT:
        return np.nan
    # 类型守卫：total_volume 必须是数值
    if not isinstance(total_volume, (int, float)):
        return np.nan
    if abs(float(total_volume)) < _TAIL_EPSILON:
        return np.nan

    first_price = prices[0]
    last_price = prices[-1]
    if abs(first_price) < _TAIL_EPSILON:
        return np.nan

    price_change = (last_price - first_price) / first_price
    tail_volume = sum(volumes)
    volume_ratio = tail_volume / float(total_volume)

    return price_change * volume_ratio


def _calc_tail_volume_acceleration(volumes: list | None) -> float:
    """计算尾盘量能加速度（后半段/前半段成交量比）。

    公式:
    - 前半段成交量总和 = sum(volumes[0:6])  # 14:00-14:25
    - 后半段成交量总和 = sum(volumes[7:13])  # 14:35-15:00
    - 量能加速度 = 后半段 / 前半段

    Args:
        volumes: 13 根 5 分钟 K 线成交量列表

    Returns:
        量能加速度值，或 NaN（数据不完整 / 除零）

    Note:
        - 14:30（索引 6）不属于任何一段
        - 遵循 MODULE.md 约束 #5：类型守卫先用 isinstance 再用 pd.isna
    """
    # 类型守卫：检查 None / 非列表类型
    if volumes is None:
        return np.nan
    if not isinstance(volumes, list):
        return np.nan
    if len(volumes) < _TAIL_KLINE_COUNT:
        return np.nan
    # 检查是否包含 NaN / None
    if any(v is None or (isinstance(v, float) and np.isnan(v)) for v in volumes):
        return np.nan

    # 前半段成交量总和（索引 0-5）
    front_volume = sum(volumes[0:6])
    # 后半段成交量总和（索引 7-12）
    back_volume = sum(volumes[7:13])

    # 除零防护
    if front_volume < _TAIL_EPSILON:
        return np.nan

    return back_volume / front_volume


def _calc_tail_volume_shrink(
    volumes: list | None,
    total_volume: float | None,
) -> float:
    """计算尾盘缩量程度（尾盘成交量总和 / 全天成交量）。

    公式:
    - 尾盘缩量程度 = sum(volumes) / total_volume

    Args:
        volumes: 13 根 5 分钟 K 线成交量列表（14:00-15:00）
        total_volume: 全天成交量

    Returns:
        尾盘缩量程度值，理论范围 [0, 1]，或 NaN（数据不完整 / 除零）

    Note:
        - 数值越小表示尾盘缩量越明显
        - 遵循 MODULE.md 约束 #5：类型守卫先用 isinstance 再用 pd.isna
    """
    # 类型守卫：检查 None
    if volumes is None or total_volume is None:
        return np.nan
    if not isinstance(volumes, list):
        return np.nan
    if len(volumes) < _TAIL_KLINE_COUNT:
        return np.nan
    # 类型守卫：total_volume 必须是数值
    if not isinstance(total_volume, (int, float)):
        return np.nan
    if abs(float(total_volume)) < _TAIL_EPSILON:
        return np.nan

    # 检查 volumes 是否包含 NaN / None
    if any(v is None or (isinstance(v, float) and np.isnan(v)) for v in volumes):
        return np.nan

    tail_volume = sum(volumes)
    return tail_volume / float(total_volume)


# ============================================================================
# 公共编排 API（B4 轮）
# ============================================================================


# 5 个尾盘因子输出列（按依赖顺序固定列序，与原 factor_generator 一致）
_TAIL_FACTOR_COLS: tuple[str, ...] = (
    "tail_price_position",
    "tail_price_slope",
    "tail_price_volume_intensity",
    "tail_volume_acceleration",
    "tail_volume_shrink",
)


def calculate_tail_factors(
    factor_df: pd.DataFrame,
    *,
    logger_arg: logging.Logger | None = None,
) -> pd.DataFrame:
    """计算所有尾盘因子（合并计算，避免重复加载尾盘数据）。

    本函数为尾盘因子族的统一入口，一次加载尾盘数据后计算 5 个因子，
    避免每个因子重复 I/O。

    Args:
        factor_df: 包含 ``date`` / ``asset`` / ``volume`` 列的 DataFrame。
            若同时含 ``close`` / ``high`` / ``low``，则 ``tail_price_position``
            会启用 v1.39 涨跌停处理逻辑。
        logger_arg: 日志记录器（可选）

    Returns:
        新增以下列的 DataFrame：

        - ``tail_price_position``：尾盘价格位置 ``[0, 1]``
        - ``tail_price_slope``：尾盘趋势斜率（百分比）
        - ``tail_price_volume_intensity``：尾盘量价强度
        - ``tail_volume_acceleration``：尾盘量能加速度
        - ``tail_volume_shrink``：尾盘缩量程度 ``[0, 1]``

    Note:
        - 遵循 MODULE.md 约束 #4：函数入口先 ``copy()``
        - 尾盘数据不存在 / 损坏：5 个因子全部置 NaN
        - 尾盘数据缺 ``volumes`` 列：仅 ``tail_price_position`` /
          ``tail_price_slope`` 有值，其余 3 个置 NaN（warning）
    """
    _logger = get_module_logger(logger_arg)
    factor_df = factor_df.copy()

    # 加载尾盘数据
    tail_df = _load_tail_trading_data(_logger)
    if tail_df.empty:
        for col in _TAIL_FACTOR_COLS:
            factor_df[col] = np.nan
        return factor_df

    # 确保日期格式一致
    factor_df["date"] = pd.to_datetime(factor_df["date"]).dt.strftime("%Y-%m-%d")
    tail_df["date"] = pd.to_datetime(tail_df["date"]).dt.strftime("%Y-%m-%d")

    # 合并尾盘数据
    merge_cols = ["date", "asset", "prices", "tail_high", "tail_low"]
    if "volumes" in tail_df.columns:
        merge_cols.append("volumes")

    # ---- v1.43 内存优化：mask 子集 apply（design.md fix-tail-factors-oom.md §3）----
    # 原实现先 left-merge 出全表（1.49M 行）再 apply(axis=1)，95%+ 行未匹配 → NaN→NaN 空转，
    # 但仍构造含 list 列的 Series，单进程 RSS 峰值 3.27GB → OOM(-9)。
    # 新实现：仅在命中行子集（含 prices）上做 apply，未命中行直接置 NaN，
    # 行序保留、5 个因子值与原实现字节级一致（NaN 守卫见 _calc_* helper）。
    has_volumes = "volumes" in tail_df.columns

    # Step 1: 在 factor_df 上预初始化 5 个因子列为 NaN（覆盖未命中行）
    for col in _TAIL_FACTOR_COLS:
        factor_df[col] = np.nan

    # Step 2: mask 出有尾盘数据的行（用 tail_df 的 (date, asset) 作为索引集）
    tail_keys = pd.MultiIndex.from_arrays([tail_df["date"], tail_df["asset"]])
    factor_keys = pd.MultiIndex.from_arrays([factor_df["date"], factor_df["asset"]])
    mask = factor_keys.isin(tail_keys)
    matched_count = int(mask.sum())

    _logger.info(
        "尾盘数据合并完成: %d / %d 条匹配",
        matched_count,
        len(factor_df),
    )

    # Step 3: 仅当存在匹配行时才做 merge + apply
    if matched_count > 0:
        # MODULE.md R16: 中间对象用完即释放，降峰值
        # 仅取 apply 实际需要的列，避免 sub 携带其他基础因子（已 ~20 列）
        sub_cols = ["date", "asset", "volume"]
        for opt_col in ("close", "high", "low"):
            if opt_col in factor_df.columns:
                sub_cols.append(opt_col)
        sub = factor_df.loc[mask, sub_cols].copy()
        sub = sub.merge(tail_df[merge_cols], on=["date", "asset"], how="left")

        # 计算尾盘收盘价（仅子集）
        sub["tail_close"] = sub["prices"].apply(_get_close_price)

        # 计算尾盘价格位置（v1.39: 传入日线 close/high/low 用于涨跌停判断）
        sub["tail_price_position"] = sub.apply(
            lambda row: _calc_price_position(
                row["tail_close"],
                row["tail_high"],
                row["tail_low"],
                daily_close=row.get("close"),
                daily_high=row.get("high"),
                daily_low=row.get("low"),
            ),
            axis=1,
        )

        # 计算尾盘趋势斜率
        sub["tail_price_slope"] = sub["prices"].apply(_calc_tail_price_slope)

        # 计算尾盘量价强度 / 量能加速度 / 缩量程度（依赖 volumes）
        if has_volumes:
            sub["tail_price_volume_intensity"] = sub.apply(
                lambda row: _calc_tail_price_volume_intensity(row["prices"], row["volumes"], row["volume"]),
                axis=1,
            )
            sub["tail_volume_acceleration"] = sub["volumes"].apply(_calc_tail_volume_acceleration)
            sub["tail_volume_shrink"] = sub.apply(
                lambda row: _calc_tail_volume_shrink(row["volumes"], row["volume"]),
                axis=1,
            )
        # has_volumes=False 分支：3 列已在 Step 1 预置 NaN，下面 warning 即可

        # Step 4: 把 sub 的因子列写回 factor_df（按 mask 位置对齐）
        # sub 与 factor_df.loc[mask] 行序一致（loc[mask].copy() 保留原顺序，merge 不重排已存在键）
        for col in _TAIL_FACTOR_COLS:
            if col in sub.columns:
                factor_df.loc[mask, col] = sub[col].to_numpy()

        # MODULE.md R16: 大对象显式 del 释放
        del sub

    if not has_volumes:
        _logger.warning(
            "尾盘数据缺少 'volumes' 列，tail_price_volume_intensity/"
            "tail_volume_acceleration/tail_volume_shrink 将为 NaN"
        )

    # MODULE.md R16: tail_df 已用完
    del tail_df

    # 统计有效因子数量
    total_count = len(factor_df)
    for col in _TAIL_FACTOR_COLS:
        valid_count = factor_df[col].notna().sum()
        _logger.info(
            "%s 因子计算完成: %d / %d 有效 (%.1f%%)",
            col,
            valid_count,
            total_count,
            100 * valid_count / total_count if total_count > 0 else 0,
        )

    return factor_df


calculate_tail_factors.required_cols = ["date", "asset", "volume"]  # type: ignore[attr-defined]
