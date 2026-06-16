"""factor_calculator 包通用底座（_common）。

集中存放：
- 模块级私有常量（`_COL_*`、`_DEFAULT_*`、`_EPSILON`、基准值常量）
- 公共常量别名（`DEFAULT_*`，被 `factor_ic` 多个脚本直接 import）
- 模块 logger 与 ``get_module_logger`` 半公开 helper
- 4 个跨子模块复用的纯计算 helper：
  ``_wilder_smoothing_rsi`` / ``_per_asset_transform`` /
  ``_calculate_ewm_with_initial`` / ``_calculate_delta``

约束（design.md §5.1）：
- ``__all__ = []``：本模块**不导出公共 API**；外部需要的半公开符号统一由
  ``data_fetchers/factor_calculator/__init__.py`` 显式 re-export。
- 仅依赖标准库 + numpy + pandas + logging（依赖图根节点，不得反向依赖任何兄弟子模块）。
- 内容与原 ``factor_calculator.py``（已重命名为 ``_legacy.py``）逐字对齐，禁止重写公式或调整边界处理（设计 §3.2 N1）。
- ``_add_industry_column`` 已于 R2（2026-06-16）迁出至 ``_industry_helpers.py``，
  以保持本模块作为依赖图根节点的纯净度（不反向依赖 ``fetch_industry``）。

历史：
- v1.20 (2026-06-15) PR-2a：从 ``_legacy.py`` 行 100-234 / 267-313 / 470-525 /
  618-651 / 1452-1503 抽取至本模块，``_legacy.py`` 改为 ``from ._common import *`` 兼容。
- v1.21 (2026-06-16) R2：``_add_industry_column`` 迁出至 ``_industry_helpers.py``
  （消除 §5.1 反向依赖违规，原始问题清单 #1）；同步修复
  ``_per_asset_transform`` 排序契约校验（#3）、``_calculate_ewm_with_initial``
  哨兵索引（#4）、``_wilder_smoothing_rsi`` 前值 NaN 可观测性（#5）、
  ``_calculate_delta`` 文档与日志级别（#6/#8）、EPSILON 重复定义（#7）、
  ``get_module_logger`` 文档示例（#10）。
"""

from __future__ import annotations

import logging
from collections.abc import Callable  # noqa: F401  used in stringified type hints (PEP 563)

import numpy as np
import pandas as pd


# 本模块不导出公共 API：通过包级 __init__.py 显式 re-export 半公开符号
__all__: list[str] = []


# ============================================================================
# 数值阈值与因子计算基准值（私有常量，非公共 API）
# ============================================================================

_EPSILON = 1e-10  # 避免除零阈值

# 因子计算基准值
_RSI_NEUTRAL_VALUE = 50.0  # RSI 中性值（avg_loss=0 且 avg_gain=0 时）
_RSI_MAX_VALUE = 100  # RSI 最大值（超买）
_BOLLINGER_NEUTRAL_VALUE = 0.5  # 布林带 %B 中性值（带宽过窄时）
_KD_NEUTRAL_VALUE = 50.0  # K/D 值中性初始值


# ============================================================================
# 输入列名常量（DataFrame 列名）
# ============================================================================

_COL_CLOSE = "close"
_COL_DATE = "date"
_COL_ASSET = "asset"
_COL_HIGH = "high"
_COL_LOW = "low"
_COL_TURNOVER_RATE = "turnover_rate"


# ============================================================================
# 输出列名常量（因子输出列名）
# ============================================================================

_COL_BOLLINGER_PB = "bollinger_pb"
_COL_KDJ_J = "kdj_j"
_COL_TURNOVER_SURGE = "turnover_surge"
_COL_PRICE_POSITION = "price_position"
_COL_AMPLITUDE = "amplitude"
_COL_PAST_RETURN_1D = "past_return_1d"
_COL_RETURN_3D = "return_3d"
_COL_RETURN_5D = "return_5d"
_COL_AMPLITUDE_DELTA = "amplitude_delta"
_COL_TURNOVER_SURGE_DELTA = "turnover_surge_delta"
_COL_TAIL_PRICE_POSITION_DELTA = "tail_price_position_delta"
_COL_TAIL_VOLUME_SHRINK_DELTA = "tail_volume_shrink_delta"
_COL_VOLUME_PRICE_STRENGTH = "volume_price_strength"
_COL_POSITIVE_DAY_RATIO_5 = "positive_day_ratio_5"
_COL_MA5_DEVIATION = "ma5_deviation"
_COL_NEAR_HIGH_RATIO_5 = "near_high_ratio_5"
_COL_INDUSTRY_MOMENTUM_5D = "industry_momentum_5d"
_COL_INDUSTRY_TURNOVER_TREND = "industry_turnover_trend"
_COL_INDUSTRY_AMPLITUDE_TREND = "industry_amplitude_trend"
_COL_INDUSTRY_ROE_TREND = "industry_roe_trend"  # v1.16 新增：行业ROE趋势因子
_COL_INDUSTRY_EARNINGS_GROWTH = "industry_earnings_growth"  # v1.16 新增：行业盈利增长因子
_COL_INDUSTRY_PE_TREND = "industry_pe_trend"  # v1.16 新增：行业PE趋势因子

# 动量族（PR-2c）
_COL_OPEN = "open"
_COL_OVERNIGHT_RET = "overnight_ret"
_COL_MOMENTUM_STRENGTH = "momentum_strength"

# 资金流族（PR-4b）
_COL_CAPITAL_FLOW_RATIO_TREND = "capital_flow_ratio_trend"
_COL_CAPITAL_FLOW_INTENSITY = "capital_flow_intensity"


# ============================================================================
# 行业因子默认参数（私有常量）
# ============================================================================

_DEFAULT_INDUSTRY_WINDOW = 5  # 行业5日动量窗口
_DEFAULT_MIN_INDUSTRY_STOCKS = 5  # 行业最少股票数阈值
_DEFAULT_TREND_DENOMINATOR_MIN = 0.001  # 比率型因子分母下限
_DEFAULT_AMPLITUDE_TREND_DENOMINATOR_MIN = 0.01  # 振幅趋势分母下限


# ============================================================================
# 默认参数（私有常量，遵循 cache_manager.py 规范）
# ============================================================================

_DEFAULT_RSI_PERIOD = 6
_DEFAULT_BOLLINGER_N = 20
_DEFAULT_BOLLINGER_K = 2.0
_DEFAULT_KDJ_N = 9
_DEFAULT_KDJ_M1 = 3
_DEFAULT_KDJ_M2 = 3
_DEFAULT_SURGE_WINDOW = 5
_DEFAULT_VOLUME_RATIO_WINDOW = 5
_DEFAULT_FORWARD_RETURN_SHIFT = 1
# 价格位置 / 振幅族因子的除零保护 epsilon。语义与 ``_EPSILON`` 等价，
# 显式引用而非重新定义，避免后续维护时三处 1e-10 不同步（PROJECT.md 死代码 #14 同源原则）。
# 命名保留是为了被 momentum.py 按"业务族"语义 import；外部别名（_DEFAULT_*）做语义层、_EPSILON 做物理层。
_DEFAULT_PRICE_POSITION_EPSILON = _EPSILON
_DEFAULT_AMPLITUDE_EPSILON = _EPSILON
_DEFAULT_PAST_RETURN_1D_WINDOW = 1  # 1日涨幅窗口
_DEFAULT_RETURN_3D_WINDOW = 3  # 3日累计涨幅窗口
_DEFAULT_RETURN_5D_WINDOW = 5  # 5日累计涨幅窗口
_DEFAULT_MOMENTUM_STRENGTH_WINDOW = 5  # 5日滚动窗口（动量强度日收益标准差窗口）
_MOMENTUM_STRENGTH_STD_MIN = 0.01  # 日收益率标准差下限（防止均匀涨跌时比值爆炸）


# ============================================================================
# 公共常量别名（向下兼容 ic_kdj_j / ic_rsi 等脚本的导入；写入 __all__ via __init__.py）
# ============================================================================

DEFAULT_RSI_PERIOD = _DEFAULT_RSI_PERIOD
DEFAULT_BOLLINGER_N = _DEFAULT_BOLLINGER_N
DEFAULT_BOLLINGER_K = _DEFAULT_BOLLINGER_K
DEFAULT_KDJ_N = _DEFAULT_KDJ_N
DEFAULT_KDJ_M1 = _DEFAULT_KDJ_M1
DEFAULT_KDJ_M2 = _DEFAULT_KDJ_M2
DEFAULT_SURGE_WINDOW = _DEFAULT_SURGE_WINDOW
DEFAULT_VOLUME_RATIO_WINDOW = _DEFAULT_VOLUME_RATIO_WINDOW
DEFAULT_FORWARD_RETURN_SHIFT = _DEFAULT_FORWARD_RETURN_SHIFT


# ============================================================================
# 模块级 fallback logger（遵循 PROJECT.md 公共模块日志规范）
# ============================================================================

_MODULE_LOGGER = logging.getLogger("data_fetchers.factor_calculator")


def get_module_logger(logger_arg: logging.Logger | None = None) -> logging.Logger:
    """
    获取 logger，遵循 PROJECT.md 公共模块日志规范

    公共模块接收 logger 参数，调用方传入以追溯调用方。
    不传 logger 时使用模块级 fallback logger（模块加载时已初始化）。

    Args:
        logger_arg: 调用方传入的 logger（可选）

    Returns:
        Logger 对象

    Example:
        >>> # 调用方传入 logger
        >>> from data_fetchers.common.logger_config import setup_logger
        >>> logger = setup_logger("factor_generator")
        >>> result = _calculate_delta(df, "amplitude", "amplitude_delta", logger_arg=logger)

        >>> # 不传 logger，使用模块级 fallback
        >>> result = _calculate_delta(df, "amplitude", "amplitude_delta")
    """
    if logger_arg is not None:
        return logger_arg
    return _MODULE_LOGGER


# ============================================================================
# RSI Wilder 平滑（半公开私有 helper）
# ============================================================================


def _wilder_smoothing_rsi(series: pd.Series, n: int) -> pd.Series:
    """Wilder 平滑：前 n-1 天 NaN，第 n 天 SMA 种子，第 n+1 天起 EWM 递推

    Args:
        series: 单资产的序列（gain 或 loss）
        n: 窗口期

    Returns:
        Wilder 平滑均值序列

    Note:
        Wilder (1978) 标准实现：
        1. 前 n-1 天为 NaN（数据不足以计算 SMA）
        2. 第 n 天（索引 n-1）使用 SMA 值作为 EWM 种子
           - SMA = series.iloc[:n].mean()
        3. 第 n+1 天及之后使用 EWM 递推
           - 公式：avg_t = alpha * val_t + (1-alpha) * avg_{t-1}
           - alpha = 1/n
           - NaN 传播：若当天输入为 NaN，结果也为 NaN

        与 pandas ewm(adjust=False) 的差异：
        - pandas ewm(adjust=False) 从第 1 个观测值就开始计算
        - Wilder 标准要求前 n-1 天为 NaN，第 n 天用 SMA
    """
    alpha = 1.0 / n

    # 初始化全 NaN 序列
    result = pd.Series(float("nan"), index=series.index, dtype=float)

    # 防御性检查：序列长度不足
    if len(series) < n:
        return result

    # 第 n 天（索引 n-1）：SMA 种子
    seed = series.iloc[:n].mean()
    if pd.isna(seed):  # 防御：前 n 天全为 NaN 时无法计算种子
        return result
    result.iloc[n - 1] = seed

    # 第 n+1 天起（索引 n 到 len-1）：EWM 递推
    # 边界行为：若 result.iloc[i-1] 已为 NaN（例如外部把已计算结果某段置 NaN
    # 或 SMA 种子位之后又出现 NaN 输入），递推链将不可恢复地全部 NaN。
    # 这是 Wilder 标准 NaN 传播语义（不在此处兜底），仅在首次发生时记录 debug
    # 日志，便于上游定位"为什么后续全 NaN"。
    nan_break_logged = False
    for i in range(n, len(series)):
        prev = result.iloc[i - 1]
        if pd.isna(series.iloc[i]):  # 当天值为 NaN：传播 NaN
            result.iloc[i] = float("nan")
        elif pd.isna(prev):  # 前值 NaN：递推链中断，从此全 NaN
            result.iloc[i] = float("nan")
            if not nan_break_logged:
                _MODULE_LOGGER.debug(
                    "_wilder_smoothing_rsi: 递推链于索引 %d 中断（前值为 NaN），后续值将全部为 NaN",
                    i,
                )
                nan_break_logged = True
        else:
            result.iloc[i] = alpha * series.iloc[i] + (1 - alpha) * prev

    return result


# ============================================================================
# 通用工具：按 asset 分组的低内存 transform 替代
# ============================================================================


def _per_asset_transform(
    asset_arr: np.ndarray,
    value_arr: np.ndarray,
    fn: Callable[[pd.Series], pd.Series],
) -> np.ndarray:
    """按 asset 分组对单列数值序列应用 fn，返回回填的 ndarray。

    替代 ``df.groupby(asset, group_keys=False)[col].transform(fn)``。
    pandas 的 ``groupby.transform`` 在大规模数据 (>1M 行 × >1k group) 上会因
    内部索引重建产生 4 GB+ 内存峰值并触发 OOM（详见 backtest/MODULE.md M54）。

    本 helper 假设 ``asset_arr`` 已**按 asset 排序**（同 asset 行连续），
    用 numpy 边界切片逐 asset 调 ``fn``，回填到预分配 ndarray。

    Args:
        asset_arr: asset 列 ndarray（必须已按 asset 排序）
        value_arr: 数值列 ndarray
        fn: 接收单 asset 的 ``pd.Series``，返回同长度 ``pd.Series``

    Returns:
        回填后的 float64 ndarray（NaN 为缺失），长度与输入一致

    Raises:
        ValueError: asset_arr 与 value_arr 长度不一致，或 asset_arr 未按 asset 排序
            （同一 asset 在数组中不连续 → 切片段数与唯一 asset 数不等）

    实现说明:
        - 单 asset 切片足够小，``fn`` 内部的 rolling/ewm/diff 操作内存友好
        - 预分配 ndarray 避免 transform 的中间索引膨胀
        - 内存增量约 ``len * 8B``（一份 float64），而非 transform 的几 GB

    Example:
        >>> import numpy as np, pandas as pd
        >>> assets = np.array(["A", "A", "A", "B", "B"])
        >>> values = np.array([1.0, 2.0, 3.0, 10.0, 20.0])
        >>> result = _per_asset_transform(assets, values, lambda s: s.cumsum())
        >>> result.tolist()
        [1.0, 3.0, 6.0, 10.0, 30.0]
    """
    n_rows = len(asset_arr)
    if len(value_arr) != n_rows:
        raise ValueError(f"asset_arr 与 value_arr 长度不一致: {n_rows} vs {len(value_arr)}")
    if n_rows == 0:
        return np.array([], dtype=np.float64)

    # 找 asset 边界（同 asset 行连续，asset 变化处即新组起点）
    boundaries = np.flatnonzero(asset_arr[1:] != asset_arr[:-1]) + 1
    # 排序契约校验：boundaries 给出的每个 asset 段必须只出现一次。
    # 若调用方未按 asset 排序（同一 asset 被切成多段），unique_groups < n_groups。
    # 静默错误代价高（fn 看到的不是完整 asset 切片），用 ValueError 显式抛出，
    # 比 docstring "必须已按 asset 排序" 的口头约束可靠（PROJECT.md 规则 #5 同源）。
    n_groups = len(boundaries) + 1
    n_unique_assets = len(np.unique(asset_arr))
    if n_groups != n_unique_assets:
        raise ValueError(
            f"_per_asset_transform: asset_arr 未按 asset 排序，"
            f"切片得到 {n_groups} 段但只有 {n_unique_assets} 个唯一 asset，"
            f"调用方需先按 asset 排序后再传入"
        )
    boundaries = np.concatenate([[0], boundaries, [n_rows]])

    out = np.full(n_rows, np.nan, dtype=np.float64)
    n_assets = len(boundaries) - 1
    for i in range(n_assets):
        start, end = boundaries[i], boundaries[i + 1]
        slice_series = pd.Series(value_arr[start:end])
        result_series = fn(slice_series)
        out[start:end] = result_series.to_numpy(dtype=np.float64)
    return out


# ============================================================================
# EWM 递推 helper（KDJ 子模块复用，半公开私有）
# ============================================================================


def _calculate_ewm_with_initial(series: pd.Series, alpha: float, initial_value: float) -> pd.Series:
    """计算 EWM 递推值（正确处理 NaN 前缀版本）

    公共函数：统一处理 K 值和 D 值的 EWM 递推计算

    Args:
        series: 输入序列（RSV 或 K 值）
        alpha: EWM 衰减因子（1/m，m 为平滑周期）
        initial_value: 初始值（K/D 使用 50.0 作为中性值）

    Returns:
        EWM 递推结果序列

    Note:
        - 在第一个有效值前插入虚拟 initial_value 作为 EWM 种子
        - 使用 ewm(adjust=False, ignore_na=True) 确保正确传播 NaN
        - 恢复原始 NaN 位置，避免虚拟初始值污染结果
    """
    if len(series) == 0 or series.isna().all():
        return series

    # 在第一个有效值前插入虚拟 initial_value（保留原始索引）。
    # 哨兵索引使用字符串 "__ewm_initial_sentinel__"：
    # - 业务索引为日期（datetime）/ 整数序号 / asset+date 复合，绝不会与该字符串相等
    # - 旧实现用 -1，业务侧若直接传 RangeIndex 起点为 -1 / 自定义负向 index 会冲突
    _SENTINEL_INDEX = "__ewm_initial_sentinel__"
    series_with_initial = pd.concat([pd.Series([initial_value], index=[_SENTINEL_INDEX]), series])

    result_with_initial = series_with_initial.ewm(alpha=alpha, adjust=False, ignore_na=True).mean()

    # 取除虚拟初始值外的结果（iloc[1:] 跳过哨兵索引位的虚拟值）
    result_series = result_with_initial.iloc[1:]
    result_series.index = series.index

    # 恢复原始 NaN 位置
    result_series = result_series.where(series.notna(), float("nan"))

    return result_series


# ============================================================================
# 通用差分 helper（delta 子模块复用，半公开私有）
# 遵循 H5: 因子方向不预判，IC方向由数据决定
# ============================================================================


def _calculate_delta(
    factor_df: pd.DataFrame,
    base_col: str,
    delta_col: str,
    logger_arg: logging.Logger | None = None,
) -> pd.DataFrame:
    """通用差分计算：base_col(T) - base_col(T-1)，按asset分组shift

    参数:
        factor_df: 含 date, asset, base_col 的 DataFrame
        base_col: 原始因子列名（如 'amplitude'）
        delta_col: 差分因子列名（如 'amplitude_delta'）
        logger_arg: 可选 logger

    返回:
        factor_df 新增 delta_col 列。
        **行顺序契约**：返回 DataFrame 已按 ``[asset, date]`` 升序排序，与输入行顺序
        可能不同；调用方若依赖原始顺序需自行 ``reindex`` 或保存原索引后还原。

    边界处理:
        - 第一日无前值 → NaN（自然排除，不做填充）
        - 原始因子为 NaN → delta 也为 NaN（传播而非填充）
        - 按asset分组shift(1)，不跨股票

    Example:
        >>> df = pd.DataFrame({"asset": ["A", "A", "A"], "date": ["d1", "d2", "d3"], "amplitude": [0.04, 0.03, 0.05]})
        >>> result = _calculate_delta(df, "amplitude", "amplitude_delta")
        >>> pd.isna(result["amplitude_delta"].iloc[0])  # 第一日无前值
        True
        >>> result["amplitude_delta"].iloc[2]  # 0.05 - 0.03
        0.02
    """
    _logger = get_module_logger(logger_arg)

    df = factor_df.copy()  # M11: DataFrame参数先copy
    df = df.sort_values([_COL_ASSET, _COL_DATE])

    # 按asset分组，获取前一日值
    prev_value = df.groupby(_COL_ASSET)[base_col].shift(1)

    # 差分计算：NaN传播（base_col或prev_value为NaN → delta为NaN）
    df[delta_col] = df[base_col] - prev_value

    valid_count = int(df[delta_col].notna().sum())
    total_count = len(df)
    # 高频批量调用场景下（factor_generator 一次跑数十个因子），INFO 日志会刷屏。
    # 降为 DEBUG：调试期可通过日志级别开关查看，生产期保持安静。
    _logger.debug(
        "差分因子 %s: 有效=%d (%.2f%%), base_col=%s",
        delta_col,
        valid_count,
        valid_count / max(total_count, 1) * 100,
        base_col,
    )

    return df


# ============================================================================
# 行业列注入 helper：已迁出至 ._industry_helpers（R2，2026-06-16）
# ----------------------------------------------------------------------------
# 原因：``_add_industry_column`` 反向依赖 ``data_fetchers.fetch_industry``，
# 让 ``_common.py`` 不再是依赖图根节点，违反本文件 §5.1 约束（仅依赖
# stdlib + numpy + pandas + logging）。迁移到 ``_industry_helpers.py`` 后，
# ``_common.py`` 重新成为纯净根节点。调用方需改用：
#     from data_fetchers.factor_calculator._industry_helpers import _add_industry_column
# ============================================================================
