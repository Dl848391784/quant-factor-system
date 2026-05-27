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

作者: 云瑶
创建日期: 2026-05-27
"""

import pandas as pd
import numpy as np
from typing import Any

# ============================================================================
# 模块级常量
# ============================================================================
EPSILON = 1e-10  # 避免除零阈值

# 默认参数
DEFAULT_RSI_PERIOD = 6
DEFAULT_BOLLINGER_N = 20
DEFAULT_BOLLINGER_K = 2.0
DEFAULT_KDJ_N = 9
DEFAULT_KDJ_M1 = 3
DEFAULT_KDJ_M2 = 3
DEFAULT_SURGE_WINDOW = 5


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
    period: int = DEFAULT_RSI_PERIOD
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
    rsi.loc[only_zero_loss_mask] = 100
    rsi.loc[both_zero_mask] = 50
    
    # 缺失值填充为中性值
    rsi = rsi.fillna(50)
    rsi = rsi.clip(0, 100)
    
    return rsi


# ============================================================================
# Volume Ratio 计算（量比）
# ============================================================================

def calculate_volume_ratio(
    volume: pd.Series,
    window: int = 5
) -> pd.Series:
    """
    计算量比因子
    
    量比 = 当日成交量 / 过去 window 日成交量均值
    
    Args:
        volume: 成交量序列
        window: 计算窗口
    
    Returns:
        量比值序列
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
    shift: int = 1
) -> pd.Series:
    """
    计算前瞻收益率
    
    forward_return = (close_{t+shift} - close_t) / close_t
    
    Args:
        close_prices: 收盘价序列
        shift: 前瞻天数
    
    Returns:
        前瞻收益率序列
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
    n: int = DEFAULT_BOLLINGER_N,
    k: float = DEFAULT_BOLLINGER_K,
    logger: Any = None
) -> pd.DataFrame:
    """
    计算布林带 %B 因子
    
    参数:
        factor_df: 包含 close、date、asset 列的 DataFrame（面板数据长格式）
        n: 移动平均周期
        k: 标差倍数
    
    返回:
        添加 bollinger_pb 列的 DataFrame
    
    注意:
        1. 函数入口必须先 .copy()，避免修改原始数据
        2. 布林带是单只股票的时序指标，必须按 asset 分组后再做 rolling
    """
    _logger = logger
    
    # 入口：创建副本避免副作用
    factor_df = factor_df.copy()
    
    # 按 asset 分组计算滚动统计
    factor_df = factor_df.sort_values(['asset', 'date'])
    
    middle = factor_df.groupby('asset', group_keys=False)['close'].transform(
        lambda x: x.rolling(window=n).mean()
    )
    std_dev = factor_df.groupby('asset', group_keys=False)['close'].transform(
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
    bollinger_pb = (factor_df['close'] - lower) / safe_band_width
    
    # 异常处理
    bollinger_pb = bollinger_pb.where(~narrow_band_mask, 0.5)
    bollinger_pb = bollinger_pb.where(~abnormal_mask, np.nan)
    
    if _logger:
        abnormal_count = abnormal_mask.sum()
        if abnormal_count > 0:
            _logger.warning(f"检测到 {abnormal_count} 个异常布林带宽度（负值），已标记为 np.nan")
        narrow_count = narrow_band_mask.sum()
        if narrow_count > 0:
            _logger.warning(f"检测到 {narrow_count} 个过窄布林带宽度（< {EPSILON}），已置为中性值 0.5")
    
    factor_df['bollinger_pb'] = bollinger_pb
    
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
    n: int = DEFAULT_KDJ_N,
    m1: int = DEFAULT_KDJ_M1,
    m2: int = DEFAULT_KDJ_M2,
    logger: Any = None
) -> pd.DataFrame:
    """
    计算 KDJ_J 因子
    
    参数:
        factor_df: 包含 close, high, low, date, asset 列的 DataFrame
        n: RSV 计算周期
        m1: K值平滑周期
        m2: D值平滑周期
    
    返回:
        添加了 kdj_j 列的 DataFrame
    
    规范:
        - 函数入口必须先 .copy()，避免修改原始数据
        - KDJ 是单股票时序指标，必须按 asset 分组后再做 rolling/ewm
    """
    _logger = logger
    
    # 函数入口必须先 copy
    factor_df = factor_df.copy()
    
    # 按 asset+date 排序
    factor_df = factor_df.sort_values(['asset', 'date'])
    
    # ewm alpha 参数
    alpha_k = 1 / m1
    alpha_d = 1 / m2
    
    # 计算 RSV
    low_min = factor_df.groupby('asset', group_keys=False)['low'].transform(
        lambda x: x.rolling(n, min_periods=n).min()
    )
    high_max = factor_df.groupby('asset', group_keys=False)['high'].transform(
        lambda x: x.rolling(n, min_periods=n).max()
    )
    
    denom = high_max - low_min
    
    narrow_range_mask = denom < EPSILON
    safe_denom = denom.where(~narrow_range_mask, EPSILON)
    rsv = (factor_df['close'] - low_min) / safe_denom * 100
    
    # 异常位置设为 50
    rsv = rsv.where(~narrow_range_mask, 50.0)
    
    if _logger:
        narrow_count = narrow_range_mask.sum()
        if narrow_count > 0:
            _logger.warning(f"检测到 {narrow_count} 个高低价区间过窄（< {EPSILON}），RSV已置为中性值 50")
    
    # 计算 K 和 D
    k = rsv.groupby(factor_df['asset']).transform(
        lambda x: _calculate_ewm_with_initial(x, alpha_k, 50.0)
    )
    
    d = k.groupby(factor_df['asset']).transform(
        lambda x: _calculate_ewm_with_initial(x, alpha_d, 50.0)
    )
    
    # 计算 J
    factor_df['kdj_j'] = 3 * k - 2 * d
    
    return factor_df


# ============================================================================
# Turnover Surge 计算（换手率突增）
# ============================================================================

def calculate_turnover_surge(
    factor_df: pd.DataFrame,
    surge_window: int = DEFAULT_SURGE_WINDOW,
    logger: Any = None
) -> pd.DataFrame:
    """
    计算换手率突增因子
    
    参数:
        factor_df: 包含 turnover_rate, close 列的 DataFrame
        surge_window: 换手率均值计算窗口
    
    返回:
        添加了 turnover_surge 列的 DataFrame
    
    规范:
        - 函数入口必须先 .copy()，避免修改原始数据
        - 异常检测而非静默修正
    """
    _logger = logger
    
    # 函数入口必须先 copy
    factor_df = factor_df.copy()
    
    # 计算换手率均值（不含当日）
    avg_turnover = factor_df.groupby('asset')['turnover_rate'].transform(
        lambda x: x.shift(1).rolling(surge_window, min_periods=surge_window).mean()
    )
    
    # 检测 avg_turnover 异常值
    zero_avg_mask = (avg_turnover.notna()) & (avg_turnover.abs() < EPSILON)
    
    if _logger:
        zero_avg_count = zero_avg_mask.sum()
        if zero_avg_count > 0:
            _logger.warning(f"检测到 {zero_avg_count} 个 avg_turnover 接近零，已标记为 np.nan")
    
    safe_avg_turnover = avg_turnover.where(~zero_avg_mask, np.nan)
    turnover_surge = factor_df['turnover_rate'] / safe_avg_turnover
    
    # 异常负值检测
    abnormal_mask = turnover_surge < 0
    if _logger:
        abnormal_count = abnormal_mask.sum()
        if abnormal_count > 0:
            _logger.warning(f"检测到 {abnormal_count} 个异常换手率突增（负值），已标记为 np.nan")
    turnover_surge = turnover_surge.where(~abnormal_mask, np.nan)
    
    # 计算涨跌幅
    prev_close = factor_df.groupby('asset')['close'].transform(lambda x: x.shift(1))
    
    abnormal_prev_close_mask = (prev_close.notna()) & (prev_close <= EPSILON)
    if _logger:
        abnormal_prev_close_count = abnormal_prev_close_mask.sum()
        if abnormal_prev_close_count > 0:
            _logger.warning(f"检测到 {abnormal_prev_close_count} 个异常前收盘价，已标记为 np.nan")
    
    safe_prev_close = prev_close.mask(prev_close.isna() | (prev_close <= EPSILON))
    daily_return = (factor_df['close'] - safe_prev_close) / safe_prev_close
    
    # 应用业务筛选条件
    condition = (turnover_surge > 1) & (daily_return > 0)
    
    if _logger:
        valid_count = condition.sum()
        valid_ratio = valid_count / len(factor_df) if len(factor_df) > 0 else 0
        _logger.info(f"业务筛选: 满足条件(surge>1 & return>0)的记录 {valid_count} 行 ({valid_ratio:.2%})")
    
    # 不满足条件的股票因子值设为 NaN
    turnover_surge = turnover_surge.where(condition, np.nan)
    
    factor_df['turnover_surge'] = turnover_surge
    
    return factor_df


# ============================================================================
# 模块导出
# ============================================================================
__all__ = [
    'EPSILON',
    'calculate_rsi',
    'calculate_volume_ratio',
    'calculate_forward_return',
    'calculate_bollinger_pb',
    'calculate_kdj_j',
    'calculate_turnover_surge',
    '_wilder_smoothing_rsi',
    '_calculate_ewm_with_initial',
]