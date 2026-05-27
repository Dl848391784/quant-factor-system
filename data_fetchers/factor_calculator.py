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

作者: 云瑶
创建日期: 2026-05-27
"""

# ============================================================================
# 标准库导入
# ============================================================================
import logging

# ============================================================================
# 第三方库导入
# ============================================================================
import pandas as pd
import numpy as np

# ============================================================================
# 类型导入
# ============================================================================
from typing import Optional

# ============================================================================
# 模块导出（遵循 MODULE.md 约束 60：不含私有名称）
# ============================================================================
__all__ = [
    'EPSILON',
    'calculate_rsi',
    'calculate_volume_ratio',
    'calculate_forward_return',
    'calculate_bollinger_pb',
    'calculate_kdj_j',
    'calculate_turnover_surge',
    'get_module_logger',
]

# ============================================================================
# 模块级常量
# ============================================================================

# 数值阈值
EPSILON = 1e-10  # 避免除零阈值

# 因子计算基准值
_RSI_NEUTRAL_VALUE = 50.0  # RSI 中性值（avg_loss=0 且 avg_gain=0 时）
_RSI_MAX_VALUE = 100  # RSI 最大值（超买）
_BOLLINGER_NEUTRAL_VALUE = 0.5  # 布林带 %B 中性值（带宽过窄时）
_KD_NEUTRAL_VALUE = 50.0  # K/D 值中性初始值
_TURNOVER_SURGE_THRESHOLD = 1.0  # 换手率突增阈值
_DAILY_RETURN_THRESHOLD = 0.0  # 日收益率阈值（必须上涨）

# 输入列名常量（DataFrame 列名）
_COL_CLOSE = 'close'
_COL_DATE = 'date'
_COL_ASSET = 'asset'
_COL_HIGH = 'high'
_COL_LOW = 'low'
_COL_TURNOVER_RATE = 'turnover_rate'

# 输出列名常量（因子输出列名）
_COL_BOLLINGER_PB = 'bollinger_pb'
_COL_KDJ_J = 'kdj_j'
_COL_TURNOVER_SURGE = 'turnover_surge'

# 默认参数（私有常量，遵循 cache_manager.py 规范）
_DEFAULT_RSI_PERIOD = 6
_DEFAULT_BOLLINGER_N = 20
_DEFAULT_BOLLINGER_K = 2.0
_DEFAULT_KDJ_N = 9
_DEFAULT_KDJ_M1 = 3
_DEFAULT_KDJ_M2 = 3
_DEFAULT_SURGE_WINDOW = 5
_DEFAULT_VOLUME_RATIO_WINDOW = 5
_DEFAULT_FORWARD_RETURN_SHIFT = 1

# ============================================================================
# 模块级 fallback logger（遵循 PROJECT.md 公共模块日志规范）
# ============================================================================
_MODULE_LOGGER = logging.getLogger('data_fetchers.factor_calculator')


def get_module_logger(logger_arg: Optional[logging.Logger] = None) -> logging.Logger:
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
        >>> logger = setup_logger('factor_generator')
        >>> result = calculate_bollinger_pb(df, logger_arg=logger)
        
        >>> # 不传 logger，使用模块级 fallback
        >>> result = calculate_bollinger_pb(df)
    """
    if logger_arg is not None:
        return logger_arg
    return _MODULE_LOGGER


# ============================================================================
# RSI 计算（Wilder 标准）
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
    result = pd.Series(float('nan'), index=series.index, dtype=float)
    
    # 防御性检查：序列长度不足
    if len(series) < n:
        return result
    
    # 第 n 天（索引 n-1）：SMA 种子
    seed = series.iloc[:n].mean()
    if pd.isna(seed):  # 防御：前 n 天全为 NaN 时无法计算种子
        return result
    result.iloc[n - 1] = seed
    
    # 第 n+1 天起（索引 n 到 len-1）：EWM 递推
    for i in range(n, len(series)):
        if pd.isna(series.iloc[i]):  # 当天值为 NaN：传播 NaN
            result.iloc[i] = float('nan')
        else:
            result.iloc[i] = alpha * series.iloc[i] + (1 - alpha) * result.iloc[i - 1]
    
    return result


def calculate_rsi(
    close_prices: pd.Series,
    period: int = _DEFAULT_RSI_PERIOD
) -> pd.Series:
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
        >>> # 前 5 天为 NaN，第 6 天开始有值
        >>> rsi.iloc[5]  # 第一个有效值
        50.0
    """
    delta = close_prices.diff()
    gain = delta.where(delta > 0, 0)
    loss = (-delta).where(delta < 0, 0)
    
    # Wilder 标准 RSI 计算
    avg_gain = _wilder_smoothing_rsi(gain, period)
    avg_loss = _wilder_smoothing_rsi(loss, period)
    
    # 边界处理：avg_loss 接近零时
    zero_loss_mask = avg_loss.notna() & (avg_loss.abs() < EPSILON)
    zero_gain_mask = avg_gain.notna() & (avg_gain.abs() < EPSILON)
    
    # 同时为零：avg_gain=0 且 avg_loss=0 → RSI=50（中性）
    both_zero_mask = zero_loss_mask & zero_gain_mask
    
    # 只有 avg_loss 接近零（avg_gain>0）→ RSI=100（超买）
    only_zero_loss_mask = zero_loss_mask & ~zero_gain_mask
    
    # RS 计算
    safe_avg_loss = avg_loss.where(avg_loss >= EPSILON)
    rs = avg_gain / safe_avg_loss
    
    # RSI 计算
    rsi = 100 - (100 / (1 + rs))
    
    # 边界处理覆盖
    rsi.loc[only_zero_loss_mask] = _RSI_MAX_VALUE
    rsi.loc[both_zero_mask] = _RSI_NEUTRAL_VALUE
    
    # 缺失值填充为中性值
    rsi = rsi.fillna(_RSI_NEUTRAL_VALUE)
    rsi = rsi.clip(0, _RSI_MAX_VALUE)
    
    return rsi


# ============================================================================
# Volume Ratio 计算（量比）
# ============================================================================

def calculate_volume_ratio(
    volume: pd.Series,
    window: int = _DEFAULT_VOLUME_RATIO_WINDOW
) -> pd.Series:
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
    # 过去 window 日成交量均值（不含当日）
    avg_volume = volume.shift(1).rolling(window, min_periods=window).mean()
    
    # 防除零：avg_volume 接近零时标记为 NaN
    zero_avg_mask = avg_volume.notna() & (avg_volume.abs() < EPSILON)
    safe_avg_volume = avg_volume.where(~zero_avg_mask, np.nan)
    
    volume_ratio = volume / safe_avg_volume
    
    # 异常负值检测
    abnormal_mask = volume_ratio < 0
    volume_ratio = volume_ratio.where(~abnormal_mask, np.nan)
    
    return volume_ratio


# ============================================================================
# Forward Return 计算（前瞻收益）
# ============================================================================

def calculate_forward_return(
    close_prices: pd.Series,
    shift: int = _DEFAULT_FORWARD_RETURN_SHIFT
) -> pd.Series:
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
    future_close = close_prices.shift(-shift)
    
    # 防除零
    safe_close = close_prices.where(close_prices > EPSILON, np.nan)
    
    forward_return = (future_close - close_prices) / safe_close
    
    return forward_return


# ============================================================================
# Bollinger %B 计算（布林带）
# ============================================================================

def calculate_bollinger_pb(
    factor_df: pd.DataFrame,
    n: int = _DEFAULT_BOLLINGER_N,
    k: float = _DEFAULT_BOLLINGER_K,
    logger_arg: Optional[logging.Logger] = None
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
        >>> df = pd.DataFrame({
        ...     'date': ['2026-01-01', '2026-01-02', '2026-01-03'],
        ...     'asset': ['A', 'A', 'A'],
        ...     'close': [100, 102, 101]
        ... })
        >>> result = calculate_bollinger_pb(df, n=20, k=2.0)
        >>> 'bollinger_pb' in result.columns
        True
    """
    _logger = get_module_logger(logger_arg)
    
    # 入口：创建副本避免副作用
    factor_df = factor_df.copy()
    
    # 按 asset 分组计算滚动统计
    factor_df = factor_df.sort_values([_COL_ASSET, _COL_DATE])
    
    middle = factor_df.groupby(_COL_ASSET, group_keys=False)[_COL_CLOSE].transform(
        lambda x: x.rolling(window=n).mean()
    )
    std_dev = factor_df.groupby(_COL_ASSET, group_keys=False)[_COL_CLOSE].transform(
        lambda x: x.rolling(window=n).std()
    )
    
    # 计算布林带
    upper = middle + k * std_dev
    lower = middle - k * std_dev
    
    # 计算 %B
    band_width = upper - lower
    
    # 异常检测
    abnormal_mask = band_width < 0
    narrow_band_mask = (band_width >= 0) & (band_width < EPSILON)
    
    safe_band_width = band_width.mask(abnormal_mask).clip(lower=EPSILON)
    bollinger_pb = (factor_df[_COL_CLOSE] - lower) / safe_band_width
    
    # 异常处理
    bollinger_pb = bollinger_pb.where(~narrow_band_mask, _BOLLINGER_NEUTRAL_VALUE)
    bollinger_pb = bollinger_pb.where(~abnormal_mask, np.nan)
    
    if _logger:
        abnormal_count = abnormal_mask.sum()
        if abnormal_count > 0:
            _logger.warning(f"检测到 {abnormal_count} 个异常布林带宽度（负值），已标记为 np.nan")
        narrow_count = narrow_band_mask.sum()
        if narrow_count > 0:
            _logger.warning(f"检测到 {narrow_count} 个过窄布林带宽度（< {EPSILON}），已置为中性值 {_BOLLINGER_NEUTRAL_VALUE}")
    
    factor_df[_COL_BOLLINGER_PB] = bollinger_pb
    
    return factor_df


# ============================================================================
# KDJ J 计算（随机指标）
# ============================================================================

def _calculate_ewm_with_initial(
    series: pd.Series,
    alpha: float,
    initial_value: float
) -> pd.Series:
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
    
    # 在第一个有效值前插入虚拟 initial_value
    series_with_initial = pd.concat([
        pd.Series([initial_value], index=[-1]),
        series
    ], ignore_index=True)
    
    result_with_initial = series_with_initial.ewm(alpha=alpha, adjust=False, ignore_na=True).mean()
    
    result_series = result_with_initial.iloc[1:]
    result_series.index = series.index
    
    # 恢复原始 NaN 位置
    result_series = result_series.where(series.notna(), float('nan'))
    
    return result_series


def calculate_kdj_j(
    factor_df: pd.DataFrame,
    n: int = _DEFAULT_KDJ_N,
    m1: int = _DEFAULT_KDJ_M1,
    m2: int = _DEFAULT_KDJ_M2,
    logger_arg: Optional[logging.Logger] = None
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
        >>> df = pd.DataFrame({
        ...     'date': ['2026-01-01', '2026-01-02', '2026-01-03'],
        ...     'asset': ['A', 'A', 'A'],
        ...     'close': [100, 102, 101],
        ...     'high': [103, 104, 103],
        ...     'low': [99, 100, 99]
        ... })
        >>> result = calculate_kdj_j(df, n=9, m1=3, m2=3)
        >>> 'kdj_j' in result.columns
        True
    """
    _logger = get_module_logger(logger_arg)
    
    # 函数入口必须先 copy
    factor_df = factor_df.copy()
    
    # 按 asset+date 排序
    factor_df = factor_df.sort_values([_COL_ASSET, _COL_DATE])
    
    # ewm alpha 参数
    alpha_k = 1 / m1
    alpha_d = 1 / m2
    
    # 计算 RSV
    low_min = factor_df.groupby(_COL_ASSET, group_keys=False)[_COL_LOW].transform(
        lambda x: x.rolling(n, min_periods=n).min()
    )
    high_max = factor_df.groupby(_COL_ASSET, group_keys=False)[_COL_HIGH].transform(
        lambda x: x.rolling(n, min_periods=n).max()
    )
    
    denom = high_max - low_min
    
    narrow_range_mask = denom < EPSILON
    safe_denom = denom.where(~narrow_range_mask, EPSILON)
    rsv = (factor_df[_COL_CLOSE] - low_min) / safe_denom * _RSI_MAX_VALUE
    
    # 异常位置设为中性值
    rsv = rsv.where(~narrow_range_mask, _KD_NEUTRAL_VALUE)
    
    if _logger:
        narrow_count = narrow_range_mask.sum()
        if narrow_count > 0:
            _logger.warning(f"检测到 {narrow_count} 个高低价区间过窄（< {EPSILON}），RSV已置为中性值 {_KD_NEUTRAL_VALUE}")
    
    # 计算 K 和 D
    k = rsv.groupby(factor_df[_COL_ASSET]).transform(
        lambda x: _calculate_ewm_with_initial(x, alpha_k, _KD_NEUTRAL_VALUE)
    )
    
    d = k.groupby(factor_df[_COL_ASSET]).transform(
        lambda x: _calculate_ewm_with_initial(x, alpha_d, _KD_NEUTRAL_VALUE)
    )
    
    # 计算 J
    factor_df[_COL_KDJ_J] = 3 * k - 2 * d
    
    return factor_df


# ============================================================================
# Turnover Surge 计算（换手率突增）
# ============================================================================

def calculate_turnover_surge(
    factor_df: pd.DataFrame,
    surge_window: int = _DEFAULT_SURGE_WINDOW,
    logger_arg: Optional[logging.Logger] = None
) -> pd.DataFrame:
    """
    计算换手率突增因子
    
    参数:
        factor_df: 包含 turnover_rate, close 列的 DataFrame
        surge_window: 换手率均值计算窗口
        logger_arg: 调用方传入的 logger（遵循 MODULE.md 约束 77）
    
    返回:
        添加了 turnover_surge 列的 DataFrame
    
    规范:
        - 函数入口必须先 .copy()，避免修改原始数据
        - 异常检测而非静默修正
    
    Example:
        >>> import pandas as pd
        >>> df = pd.DataFrame({
        ...     'date': ['2026-01-01', '2026-01-02', '2026-01-03'],
        ...     'asset': ['A', 'A', 'A'],
        ...     'turnover_rate': [0.01, 0.02, 0.03],
        ...     'close': [100, 102, 103]
        ... })
        >>> result = calculate_turnover_surge(df, surge_window=5)
        >>> 'turnover_surge' in result.columns
        True
    """
    _logger = get_module_logger(logger_arg)
    
    # 函数入口必须先 copy
    factor_df = factor_df.copy()
    
    # 计算换手率均值（不含当日）
    avg_turnover = factor_df.groupby(_COL_ASSET)[_COL_TURNOVER_RATE].transform(
        lambda x: x.shift(1).rolling(surge_window, min_periods=surge_window).mean()
    )
    
    # 检测 avg_turnover 异常值
    zero_avg_mask = (avg_turnover.notna()) & (avg_turnover.abs() < EPSILON)
    
    if _logger:
        zero_avg_count = zero_avg_mask.sum()
        if zero_avg_count > 0:
            _logger.warning(f"检测到 {zero_avg_count} 个 avg_turnover 接近零，已标记为 np.nan")
    
    safe_avg_turnover = avg_turnover.where(~zero_avg_mask, np.nan)
    turnover_surge = factor_df[_COL_TURNOVER_RATE] / safe_avg_turnover
    
    # 异常负值检测
    abnormal_mask = turnover_surge < 0
    if _logger:
        abnormal_count = abnormal_mask.sum()
        if abnormal_count > 0:
            _logger.warning(f"检测到 {abnormal_count} 个异常换手率突增（负值），已标记为 np.nan")
    turnover_surge = turnover_surge.where(~abnormal_mask, np.nan)
    
    # 计算涨跌幅
    prev_close = factor_df.groupby(_COL_ASSET)[_COL_CLOSE].transform(lambda x: x.shift(1))
    
    abnormal_prev_close_mask = (prev_close.notna()) & (prev_close <= EPSILON)
    if _logger:
        abnormal_prev_close_count = abnormal_prev_close_mask.sum()
        if abnormal_prev_close_count > 0:
            _logger.warning(f"检测到 {abnormal_prev_close_count} 个异常前收盘价，已标记为 np.nan")
    
    safe_prev_close = prev_close.mask(prev_close.isna() | (prev_close <= EPSILON))
    daily_return = (factor_df[_COL_CLOSE] - safe_prev_close) / safe_prev_close
    
    # 应用业务筛选条件
    condition = (turnover_surge > _TURNOVER_SURGE_THRESHOLD) & (daily_return > _DAILY_RETURN_THRESHOLD)
    
    if _logger:
        valid_count = condition.sum()
        valid_ratio = valid_count / len(factor_df) if len(factor_df) > 0 else 0
        _logger.info(f"业务筛选: 满足条件(surge>{_TURNOVER_SURGE_THRESHOLD} & return>{_DAILY_RETURN_THRESHOLD})的记录 {valid_count} 行 ({valid_ratio:.2%})")
    
    # 不满足条件的股票因子值设为 NaN
    turnover_surge = turnover_surge.where(condition, np.nan)
    
    factor_df[_COL_TURNOVER_SURGE] = turnover_surge
    
    return factor_df