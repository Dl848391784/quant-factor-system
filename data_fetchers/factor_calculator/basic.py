"""data_fetchers.factor_calculator.basic：基础技术指标因子。

模块定位
========
经典量化技术指标，**纯计算、无外部 I/O**：RSI / Bollinger %B / KDJ_J /
量比 / 换手骤增 / 前瞻收益。这些因子是项目最早建立的一批，使用频率最高，
直接被 factor_generator、factor_ic、backtest 三个下游模块消费。

公共 API（design.md §5.2）
==========================
本模块按 design.md §5.2 提供 7 个公共因子函数，全部经包级
``__init__.py`` 重导出，外部以 ``from data_fetchers.factor_calculator import xxx``
访问，**不应**直接 import 本子模块：

- ``calculate_rsi(close_prices, period=6)``：单序列 RSI（Wilder 平滑）
- ``calculate_volume_ratio(volume, window=5)``：单序列量比
- ``calculate_forward_return(close_prices, shift=1)``：单序列前瞻收益（已弃用，
  保留兼容；行情数据中的 ``forward_return_*`` 由 factor_generator 写入）
- ``calculate_bollinger_pb(factor_df, ...)``：DataFrame 级 %B（按 asset 分组）
- ``calculate_kdj_j(factor_df, ...)``：DataFrame 级 KDJ_J（按 asset 分组）
- ``calculate_turnover_surge(factor_df, ...)``：DataFrame 级换手骤增比
- ``calculate_rsi_df(factor_df, ...)``：DataFrame 级 RSI（封装 calculate_rsi）

依赖
====
- ``_common``：常量、列名、默认参数、4 个半公开 helper、``get_module_logger``
- ``numpy`` / ``pandas`` / ``logging``：标准外部依赖

兼容性
======
本模块函数实现与原 ``factor_calculator.py`` v1.17 字节级一致；PR-2b
通过 ``temporary/factor_calculator_baseline_fingerprint.json`` 的 22 个
因子指纹验证（panel_hash=ecd3e754e9b348cd）。
"""

from __future__ import annotations

import logging

import numpy as np
import pandas as pd

from ._common import (
    _BOLLINGER_NEUTRAL_VALUE,
    _COL_ASSET,
    _COL_BOLLINGER_PB,
    _COL_CLOSE,
    _COL_DATE,
    _COL_HIGH,
    _COL_KDJ_J,
    _COL_LOW,
    _COL_TURNOVER_RATE,
    _COL_TURNOVER_SURGE,
    _DEFAULT_BOLLINGER_K,
    _DEFAULT_BOLLINGER_N,
    _DEFAULT_FORWARD_RETURN_SHIFT,
    _DEFAULT_KDJ_M1,
    _DEFAULT_KDJ_M2,
    _DEFAULT_KDJ_N,
    _DEFAULT_RSI_PERIOD,
    _DEFAULT_SURGE_WINDOW,
    _DEFAULT_VOLUME_RATIO_WINDOW,
    _EPSILON,
    _KD_NEUTRAL_VALUE,
    _RSI_MAX_VALUE,
    _RSI_NEUTRAL_VALUE,
    _calculate_ewm_with_initial,
    _per_asset_transform,
    _wilder_smoothing_rsi,
    get_module_logger,
)


# 本模块按 PROJECT.md "私有名称不出现在 __all__" 约束：所有公共 API 通过包级
# __init__.py 显式 re-export，本子模块 __all__ 留空。
__all__: list[str] = []


# ============================================================================
# RSI 计算（Wilder 标准，单序列）
# ============================================================================


def calculate_rsi(close_prices: pd.Series, period: int = _DEFAULT_RSI_PERIOD) -> pd.Series:
    """
    向量化计算 RSI 指标

    使用 Wilder 标准（前 period 天 SMA 种子，之后 EWM 递推）

    边界处理（遵循 Wilder 1978 标准）：
    1. avg_loss=0 且 avg_gain>0 → RSI=100（超买）
    2. avg_loss=0 且 avg_gain=0 → RSI=50（中性）
    3. avg_loss>0 → 正常计算 RS

    Args:
        close_prices: 收盘价序列
        period: RSI 计算周期

    Returns:
        RSI 值序列（0-100）

    Example:
        >>> import pandas as pd
        >>> close = pd.Series([100, 102, 101, 103, 105, 104, 106])
        >>> rsi = calculate_rsi(close, period=6)
        >>> # 前 period-1 天为 NaN（数据不足），从第 period 天起有有效值
        >>> # RSI 范围 0-100，具体值取决于价格序列
        >>> 0 <= rsi.dropna().max() <= 100
        True
    """
    # 入口：创建副本避免副作用（遵循模块规范）
    close_prices = close_prices.copy()

    delta = close_prices.diff()
    gain = delta.where(delta > 0, 0)
    loss = (-delta).where(delta < 0, 0)

    # Wilder 标准 RSI 计算
    avg_gain = _wilder_smoothing_rsi(gain, period)
    avg_loss = _wilder_smoothing_rsi(loss, period)

    # 边界处理：avg_loss 接近零时
    zero_loss_mask = avg_loss.notna() & (avg_loss.abs() < _EPSILON)
    zero_gain_mask = avg_gain.notna() & (avg_gain.abs() < _EPSILON)

    # 同时为零：avg_gain=0 且 avg_loss=0 → RSI=50（中性）
    both_zero_mask = zero_loss_mask & zero_gain_mask

    # 只有 avg_loss 接近零（avg_gain>0）→ RSI=100（超买）
    only_zero_loss_mask = zero_loss_mask & ~zero_gain_mask

    # RS 计算
    safe_avg_loss = avg_loss.where(avg_loss >= _EPSILON)
    rs = avg_gain / safe_avg_loss

    # RSI 计算
    rsi = 100 - (100 / (1 + rs))

    # 边界处理覆盖
    rsi.loc[only_zero_loss_mask] = _RSI_MAX_VALUE
    rsi.loc[both_zero_mask] = _RSI_NEUTRAL_VALUE

    # 保留前 period 天的 NaN，让调用方自行决定如何处理
    rsi = rsi.clip(0, _RSI_MAX_VALUE)

    return rsi


# ============================================================================
# Volume Ratio 计算（量比）
# ============================================================================


def calculate_volume_ratio(volume: pd.Series, window: int = _DEFAULT_VOLUME_RATIO_WINDOW) -> pd.Series:
    """
    计算量比因子

    量比 = 当日成交量 / 过去 window 日成交量均值

    Args:
        volume: 成交量序列
        window: 计算窗口

    Returns:
        量比值序列

    Example:
        >>> import pandas as pd
        >>> vol = pd.Series([1000, 1100, 900, 1200, 1000, 1500])
        >>> vr = calculate_volume_ratio(vol, window=5)
        >>> # 前 5 天为 NaN（需要 5 日历史均值）
        >>> vr.iloc[5]  # 第 6 天量比
        1.5
    """
    # 入口：创建副本避免副作用（遵循模块规范）
    volume = volume.copy()

    # 过去 window 日成交量均值（不含当日）
    avg_volume = volume.shift(1).rolling(window, min_periods=window).mean()

    # 防除零：avg_volume 接近零时标记为 NaN
    zero_avg_mask = avg_volume.notna() & (avg_volume.abs() < _EPSILON)
    safe_avg_volume = avg_volume.where(~zero_avg_mask, np.nan)

    volume_ratio = volume / safe_avg_volume

    # 异常负值检测
    abnormal_mask = volume_ratio < 0
    volume_ratio = volume_ratio.where(~abnormal_mask, np.nan)

    return volume_ratio


# ============================================================================
# Forward Return 计算（前瞻收益，单序列；行情数据 forward_return_* 由 factor_generator 写入）
# ============================================================================


def calculate_forward_return(close_prices: pd.Series, shift: int = _DEFAULT_FORWARD_RETURN_SHIFT) -> pd.Series:
    """
    计算前瞻收益率

    forward_return = (close_{t+shift} - close_t) / close_t

    Args:
        close_prices: 收盘价序列
        shift: 前瞻天数

    Returns:
        前瞻收益率序列

    Example:
        >>> import pandas as pd
        >>> close = pd.Series([100, 102, 105, 103])
        >>> fr = calculate_forward_return(close, shift=1)
        >>> fr.iloc[0]  # 第 0 天的次日收益
        0.02
        >>> fr.iloc[3]  # 最后一天无次日数据，为 NaN
        nan
    """
    # 入口：创建副本避免副作用（遵循模块规范）
    close_prices = close_prices.copy()

    future_close = close_prices.shift(-shift)

    # 防除零
    safe_close = close_prices.where(close_prices > _EPSILON, np.nan)

    forward_return = (future_close - close_prices) / safe_close

    return forward_return


# ============================================================================
# Bollinger %B 计算（布林带）
# ============================================================================


def calculate_bollinger_pb(
    factor_df: pd.DataFrame,
    n: int = _DEFAULT_BOLLINGER_N,
    k: float = _DEFAULT_BOLLINGER_K,
    logger_arg: logging.Logger | None = None,
) -> pd.DataFrame:
    """
    计算布林带 %B 因子

    参数:
        factor_df: 包含 close、date、asset 列的 DataFrame（面板数据长格式）
        n: 移动平均周期
        k: 标差倍数
        logger_arg: 调用方传入的 logger（遵循 MODULE.md 约束 77）

    返回:
        添加 bollinger_pb 列的 DataFrame

    注意:
        1. 函数入口必须先 .copy()，避免修改原始数据
        2. 布林带是单只股票的时序指标，必须按 asset 分组后再做 rolling

    Example:
        >>> import pandas as pd
        >>> df = pd.DataFrame(
        ...     {"date": ["2026-01-01", "2026-01-02", "2026-01-03"], "asset": ["A", "A", "A"], "close": [100, 102, 101]}
        ... )
        >>> result = calculate_bollinger_pb(df, n=20, k=2.0)
        >>> "bollinger_pb" in result.columns
        True
    """
    _logger = get_module_logger(logger_arg)

    # 入口：创建副本避免副作用
    factor_df = factor_df.copy()

    # 列存在性校验
    missing = [c for c in calculate_bollinger_pb.required_cols if c not in factor_df.columns]
    if missing:
        raise ValueError(f"calculate_bollinger_pb 缺少必要列: {missing}，请检查输入 DataFrame")

    # 保留 original_index 用于结果回填到原顺序
    original_index = factor_df.index

    # 按 asset 分组计算滚动统计
    factor_df = factor_df.sort_values([_COL_ASSET, _COL_DATE])

    # v1.x (2026-06-13): 用 _per_asset_transform 替代 groupby.transform，避免 OOM
    asset_arr = factor_df[_COL_ASSET].to_numpy()
    close_arr = factor_df[_COL_CLOSE].to_numpy()
    middle_arr = _per_asset_transform(asset_arr, close_arr, lambda s: s.rolling(window=n).mean())
    std_arr = _per_asset_transform(asset_arr, close_arr, lambda s: s.rolling(window=n).std())
    middle = pd.Series(middle_arr, index=factor_df.index)
    std_dev = pd.Series(std_arr, index=factor_df.index)

    # 计算布林带
    upper = middle + k * std_dev
    lower = middle - k * std_dev

    # 计算 %B
    band_width = upper - lower

    # 异常检测
    abnormal_mask = band_width < 0
    narrow_band_mask = (band_width >= 0) & (band_width < _EPSILON)

    # safe_band_width：异常值置为 NaN，正常值 clip 防除零
    safe_band_width = band_width.where(~abnormal_mask, np.nan).clip(lower=_EPSILON)
    bollinger_pb = (factor_df[_COL_CLOSE] - lower) / safe_band_width

    # safe_band_width 已将 abnormal 位置置为 NaN（clip 不影响 NaN），
    # bollinger_pb 继承 NaN 传播，无需再次 where(~abnormal_mask, np.nan)
    bollinger_pb = bollinger_pb.where(~narrow_band_mask, _BOLLINGER_NEUTRAL_VALUE)

    abnormal_count = abnormal_mask.sum()
    if abnormal_count > 0:
        _logger.warning("检测到 %s 个异常布林带宽度（负值），已标记为 np.nan", abnormal_count)
    narrow_count = narrow_band_mask.sum()
    if narrow_count > 0:
        _logger.warning(
            "检测到 %s 个过窄布林带宽度（< %s），已置为中性值 %s", narrow_count, _EPSILON, _BOLLINGER_NEUTRAL_VALUE
        )

    factor_df[_COL_BOLLINGER_PB] = bollinger_pb

    _logger.info(
        "bollinger_pb (n=%s, k=%s) 计算完成，共 %s 条记录, %s 个 asset",
        n,
        k,
        len(factor_df),
        factor_df[_COL_ASSET].nunique(),
    )

    # 恢复原始 index 顺序（保持函数对调用方透明）
    factor_df = factor_df.loc[original_index]

    return factor_df


calculate_bollinger_pb.required_cols = ["close"]  # type: ignore[attr-defined]


# ============================================================================
# KDJ J 计算（随机指标）
# 半公开 helper `_calculate_ewm_with_initial` 已迁移至 _common（PR-2a）
# ============================================================================


def calculate_kdj_j(
    factor_df: pd.DataFrame,
    n: int = _DEFAULT_KDJ_N,
    m1: int = _DEFAULT_KDJ_M1,
    m2: int = _DEFAULT_KDJ_M2,
    logger_arg: logging.Logger | None = None,
) -> pd.DataFrame:
    """
    计算 KDJ_J 因子

    参数:
        factor_df: 包含 close, high, low, date, asset 列的 DataFrame
        n: RSV 计算周期
        m1: K值平滑周期
        m2: D值平滑周期
        logger_arg: 调用方传入的 logger（遵循 MODULE.md 约束 77）

    返回:
        添加了 kdj_j 列的 DataFrame

    规范:
        - 函数入口必须先 .copy()，避免修改原始数据
        - KDJ 是单股票时序指标，必须按 asset 分组后再做 rolling/ewm

    Example:
        >>> import pandas as pd
        >>> df = pd.DataFrame(
        ...     {
        ...         "date": ["2026-01-01", "2026-01-02", "2026-01-03"],
        ...         "asset": ["A", "A", "A"],
        ...         "close": [100, 102, 101],
        ...         "high": [103, 104, 103],
        ...         "low": [99, 100, 99],
        ...     }
        ... )
        >>> result = calculate_kdj_j(df, n=9, m1=3, m2=3)
        >>> "kdj_j" in result.columns
        True
    """
    _logger = get_module_logger(logger_arg)

    # 函数入口必须先 copy
    factor_df = factor_df.copy()

    # 列存在性校验
    missing = [c for c in calculate_kdj_j.required_cols if c not in factor_df.columns]
    if missing:
        raise ValueError(f"calculate_kdj_j 缺少必要列: {missing}，请检查输入 DataFrame")

    # 保留 original_index 用于结果回填到原顺序
    original_index = factor_df.index

    # 按 asset+date 排序
    factor_df = factor_df.sort_values([_COL_ASSET, _COL_DATE])

    # ewm alpha 参数
    alpha_k = 1 / m1
    alpha_d = 1 / m2

    # 计算 RSV
    # v1.x (2026-06-13): 用 _per_asset_transform 替代 groupby.transform，避免 OOM
    asset_arr = factor_df[_COL_ASSET].to_numpy()
    low_arr = factor_df[_COL_LOW].to_numpy()
    high_arr = factor_df[_COL_HIGH].to_numpy()
    low_min_arr = _per_asset_transform(asset_arr, low_arr, lambda s: s.rolling(n, min_periods=n).min())
    high_max_arr = _per_asset_transform(asset_arr, high_arr, lambda s: s.rolling(n, min_periods=n).max())
    low_min = pd.Series(low_min_arr, index=factor_df.index)
    high_max = pd.Series(high_max_arr, index=factor_df.index)

    denom = high_max - low_min

    narrow_range_mask = denom < _EPSILON
    safe_denom = denom.where(~narrow_range_mask, _EPSILON)
    rsv = (factor_df[_COL_CLOSE] - low_min) / safe_denom * _RSI_MAX_VALUE

    # 异常位置设为中性值
    rsv = rsv.where(~narrow_range_mask, _KD_NEUTRAL_VALUE)

    narrow_count = narrow_range_mask.sum()
    if narrow_count > 0:
        _logger.warning(
            "检测到 %s 个高低价区间过窄（< %s），RSV已置为中性值 %s", narrow_count, _EPSILON, _KD_NEUTRAL_VALUE
        )

    # 计算 K 和 D（用 _per_asset_transform 替代 transform，避免 OOM）
    k_arr = _per_asset_transform(
        asset_arr,
        rsv.to_numpy(),
        lambda s: _calculate_ewm_with_initial(s, alpha_k, _KD_NEUTRAL_VALUE),
    )
    d_arr = _per_asset_transform(
        asset_arr,
        k_arr,
        lambda s: _calculate_ewm_with_initial(s, alpha_d, _KD_NEUTRAL_VALUE),
    )
    k = pd.Series(k_arr, index=factor_df.index)
    d = pd.Series(d_arr, index=factor_df.index)

    # 计算 J
    factor_df[_COL_KDJ_J] = 3 * k - 2 * d

    _logger.info(
        "kdj_j (n=%s, m1=%s, m2=%s) 计算完成，共 %s 条记录, %s 个 asset",
        n,
        m1,
        m2,
        len(factor_df),
        factor_df[_COL_ASSET].nunique(),
    )

    # 恢复原始 index 顺序（保持函数对调用方透明）
    factor_df = factor_df.loc[original_index]

    return factor_df


calculate_kdj_j.required_cols = ["close", "high", "low"]  # type: ignore[attr-defined]


# ============================================================================
# Turnover Surge 计算（换手率突增）
# ============================================================================


def calculate_turnover_surge(
    factor_df: pd.DataFrame, surge_window: int = _DEFAULT_SURGE_WINDOW, logger_arg: logging.Logger | None = None
) -> pd.DataFrame:
    """
    计算换手率突增因子

    参数:
        factor_df: 包含 turnover_rate, asset, date 列的 DataFrame
        surge_window: 换手率均值计算窗口
        logger_arg: 调用方传入的 logger（遵循 MODULE.md 约束 77）

    返回:
        添加了 turnover_surge 列的 DataFrame

    规范:
        - 函数入口必须先 .copy()，避免修改原始数据
        - 异常检测而非静默修正

    Example:
        >>> import pandas as pd
        >>> df = pd.DataFrame(
        ...     {
        ...         "date": ["2026-01-01", "2026-01-02", "2026-01-03"],
        ...         "asset": ["A", "A", "A"],
        ...         "turnover_rate": [0.01, 0.02, 0.03],
        ...         "close": [100, 102, 103],
        ...     }
        ... )
        >>> result = calculate_turnover_surge(df, surge_window=5)
        >>> "turnover_surge" in result.columns
        True
    """
    _logger = get_module_logger(logger_arg)

    # 函数入口必须先 copy
    factor_df = factor_df.copy()

    # 列存在性校验
    missing = [c for c in calculate_turnover_surge.required_cols if c not in factor_df.columns]
    if missing:
        raise ValueError(f"calculate_turnover_surge 缺少必要列: {missing}，请检查输入 DataFrame")

    # 排序保证 _per_asset_transform 同 asset 行连续
    # 保留 original_index 用于结果回填到原顺序
    original_index = factor_df.index
    factor_df = factor_df.sort_values([_COL_ASSET, _COL_DATE])

    # 计算换手率均值（不含当日）
    # v1.x (2026-06-13): 用 _per_asset_transform 替代 groupby.transform，避免 OOM
    avg_turnover_arr = _per_asset_transform(
        asset_arr=factor_df[_COL_ASSET].to_numpy(),
        value_arr=factor_df[_COL_TURNOVER_RATE].to_numpy(),
        fn=lambda s: s.shift(1).rolling(surge_window, min_periods=surge_window).mean(),
    )
    avg_turnover = pd.Series(avg_turnover_arr, index=factor_df.index)

    # 检测 avg_turnover 异常值
    zero_avg_mask = (avg_turnover.notna()) & (avg_turnover.abs() < _EPSILON)

    zero_avg_count = zero_avg_mask.sum()
    if zero_avg_count > 0:
        _logger.warning("检测到 %s 个 avg_turnover 接近零，已标记为 np.nan", zero_avg_count)

    safe_avg_turnover = avg_turnover.where(~zero_avg_mask, np.nan)
    turnover_surge = factor_df[_COL_TURNOVER_RATE] / safe_avg_turnover

    # 异常负值检测
    abnormal_mask = turnover_surge < 0
    abnormal_count = abnormal_mask.sum()
    if abnormal_count > 0:
        _logger.warning("检测到 %s 个异常换手率突增（负值），已标记为 np.nan", abnormal_count)
    turnover_surge = turnover_surge.where(~abnormal_mask, np.nan)

    factor_df[_COL_TURNOVER_SURGE] = turnover_surge

    _logger.info(
        "turnover_surge (surge_window=%s) 计算完成，共 %s 条记录, %s 个 asset",
        surge_window,
        len(factor_df),
        factor_df[_COL_ASSET].nunique(),
    )

    # 恢复原始 index 顺序（保持函数对调用方透明）
    factor_df = factor_df.loc[original_index]

    return factor_df


calculate_turnover_surge.required_cols = ["turnover_rate", "asset", "date"]  # type: ignore[attr-defined]


# ============================================================================
# RSI DataFrame 版本（用于分层回测）
# ============================================================================


def calculate_rsi_df(
    factor_df: pd.DataFrame, n: int = _DEFAULT_RSI_PERIOD, logger_arg: logging.Logger | None = None
) -> pd.DataFrame:
    """计算 RSI 因子（DataFrame 版本）

    参数:
        factor_df: 包含 close, asset, date 列的 DataFrame
        n: RSI 计算周期
        logger_arg: 调用方传入的 logger

    返回:
        添加 rsi 列的 DataFrame

    实现说明（v1.13 2026-06-13）:
        - 旧版用 ``df.groupby(asset).transform(calc_rsi)``，pandas 在 1.5M 行 ×
          5400+ 股票上中间索引膨胀至 4 GB+，触发 OOM。
        - 新版按 (asset, date) 排序后用 numpy 边界切片，逐 asset 切 close Series
          调用 ``calculate_rsi``，回填到预分配 ndarray。内存增量约 36 MB
          （3 × float64 × 1.5M）替代 transform 的几 GB。
        - 行为不变：单 asset 上 RSI 序列结果与旧实现位级一致（同一 ``calculate_rsi``
          函数处理同一 close 切片）。

    Example:
        >>> df = pd.DataFrame(
        ...     {
        ...         "asset": ["A", "A", "A", "A", "A", "A"],
        ...         "date": ["2026-01-01", "2026-01-02", ...],
        ...         "close": [100, 102, 101, 103, 105, 104],
        ...     }
        ... )
        >>> result = calculate_rsi_df(df, n=6)
        >>> "rsi" in result.columns
        True
    """
    _logger = get_module_logger(logger_arg)

    # 函数入口必须先 copy
    factor_df = factor_df.copy()

    # 列存在性校验
    missing = [c for c in calculate_rsi_df.required_cols if c not in factor_df.columns]
    if missing:
        raise ValueError(f"calculate_rsi_df 缺少必要列: {missing}，请检查输入 DataFrame")

    # 保留 original_index 用于结果回填到原顺序
    original_index = factor_df.index

    # 排序保证 _per_asset_transform 同 asset 行连续
    factor_df = factor_df.sort_values([_COL_ASSET, _COL_DATE])

    n_rows = len(factor_df)
    if n_rows == 0:
        factor_df["rsi"] = np.nan
        return factor_df

    # 用通用 helper 替代 transform，避免 OOM（详见 _per_asset_transform docstring）
    factor_df["rsi"] = _per_asset_transform(
        asset_arr=factor_df[_COL_ASSET].to_numpy(),
        value_arr=factor_df[_COL_CLOSE].to_numpy(),
        fn=lambda close_s: calculate_rsi(close_s, period=n),
    )

    n_assets = factor_df[_COL_ASSET].nunique()
    _logger.info("rsi (n=%s) 计算完成，共 %s 条记录, %s 个 asset", n, n_rows, n_assets)

    # 恢复原始 index 顺序（保持函数对调用方透明）
    factor_df = factor_df.loc[original_index]

    return factor_df


calculate_rsi_df.required_cols = ["close"]  # type: ignore[attr-defined]
