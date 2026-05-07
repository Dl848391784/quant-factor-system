"""
趋势类技术指标模块

包含：
- MA (移动平均线)
- EMA (指数移动平均)
- MACD (指数平滑异同移动平均线)
- DMI (动向指数)
- ADX (平均趋向指数)
"""

import numpy as np
import pandas as pd
from typing import Dict, List, Optional, Tuple, Union
import warnings

warnings.filterwarnings('ignore')


def calc_ma(
    close: Union[pd.Series, np.ndarray],
    period: int = 20
) -> np.ndarray:
    """
    计算简单移动平均线 (MA)
    
    Args:
        close: 收盘价序列
        period: 周期
        
    Returns:
        MA值数组
    """
    close = np.asarray(close, dtype=float)
    n = len(close)
    
    if n < period:
        return np.full(n, np.nan)
    
    result = np.full(n, np.nan)
    
    # 使用滚动窗口计算
    for i in range(period - 1, n):
        result[i] = np.mean(close[i - period + 1:i + 1])
    
    return result


def calc_ema(
    close: Union[pd.Series, np.ndarray],
    period: int = 20
) -> np.ndarray:
    """
    计算指数移动平均线 (EMA)
    
    EMA = α * Price + (1 - α) * prev_EMA
    α = 2 / (period + 1)
    
    Args:
        close: 收盘价序列
        period: 周期
        
    Returns:
        EMA值数组
    """
    close = np.asarray(close, dtype=float)
    n = len(close)
    
    if n < period:
        return np.full(n, np.nan)
    
    result = np.full(n, np.nan)
    
    # 初始值用SMA
    alpha = 2.0 / (period + 1)
    result[period - 1] = np.mean(close[:period])
    
    # 递推计算EMA
    for i in range(period, n):
        result[i] = alpha * close[i] + (1 - alpha) * result[i - 1]
    
    return result


def calc_macd(
    close: Union[pd.Series, np.ndarray],
    fast_period: int = 12,
    slow_period: int = 26,
    signal_period: int = 9
) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """
    计算MACD指标
    
    MACD = EMA(fast) - EMA(slow)
    Signal = EMA(MACD, signal_period)
    Histogram = MACD - Signal
    
    Args:
        close: 收盘价序列
        fast_period: 快线周期
        slow_period: 慢线周期
        signal_period: 信号线周期
        
    Returns:
        (MACD线, Signal线, Histogram柱)
    """
    close = np.asarray(close, dtype=float)
    n = len(close)
    
    ema_fast = calc_ema(close, fast_period)
    ema_slow = calc_ema(close, slow_period)
    
    macd_line = ema_fast - ema_slow
    signal_line = calc_ema(macd_line, signal_period)
    histogram = macd_line - signal_line
    
    return macd_line, signal_line, histogram


def calc_dmi(
    high: Union[pd.Series, np.ndarray],
    low: Union[pd.Series, np.ndarray],
    close: Union[pd.Series, np.ndarray],
    period: int = 14
) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """
    计算DMI指标 (Directional Movement Index)
    
    +DM = max(High - prev_High, 0) if High - prev_High > Low - prev_Low else 0
    -DM = max(prev_Low - Low, 0) if prev_Low - Low > High - prev_High else 0
    +DI = +DM_MA / TR_MA * 100
    -DI = -DM_MA / TR_MA * 100
    
    Args:
        high: 最高价序列
        low: 最低价序列
        close: 收盘价序列
        period: 周期
        
    Returns:
        (+DI, -DI, DX)
    """
    high = np.asarray(high, dtype=float)
    low = np.asarray(low, dtype=float)
    close = np.asarray(close, dtype=float)
    n = len(high)
    
    if n < period + 1:
        return np.full(n, np.nan), np.full(n, np.nan), np.full(n, np.nan)
    
    # 计算DM
    up_move = high[1:] - high[:-1]
    down_move = low[:-1] - low[1:]
    
    plus_dm = np.where(
        (up_move > down_move) & (up_move > 0),
        up_move,
        0.0
    )
    minus_dm = np.where(
        (down_move > up_move) & (down_move > 0),
        down_move,
        0.0
    )
    
    # 补齐第一天的值
    plus_dm = np.concatenate([[0], plus_dm])
    minus_dm = np.concatenate([[0], minus_dm])
    
    # 计算TR (True Range)
    tr = calc_tr(high, low, close)
    
    # 计算平滑值
    plus_dm_ma = calc_wilder_smoothing(plus_dm, period)
    minus_dm_ma = calc_wilder_smoothing(minus_dm, period)
    tr_ma = calc_wilder_smoothing(tr, period)
    
    # 计算DI
    plus_di = np.where(tr_ma > 0, plus_dm_ma / tr_ma * 100, 0)
    minus_di = np.where(tr_ma > 0, minus_dm_ma / tr_ma * 100, 0)
    
    # 计算DX
    di_sum = plus_di + minus_di
    dx = np.where(di_sum > 0, np.abs(plus_di - minus_di) / di_sum * 100, 0)
    
    return plus_di, minus_di, dx


def calc_adx(
    high: Union[pd.Series, np.ndarray],
    low: Union[pd.Series, np.ndarray],
    close: Union[pd.Series, np.ndarray],
    period: int = 14
) -> np.ndarray:
    """
    计算ADX指标 (Average Directional Index)
    
    ADX = Wilder平滑(DX)
    
    Args:
        high: 最高价序列
        low: 最低价序列
        close: 收盘价序列
        period: 周期
        
    Returns:
        ADX值数组
    """
    plus_di, minus_di, dx = calc_dmi(high, low, close, period)
    adx = calc_wilder_smoothing(dx, period)
    
    return adx


def calc_tr(
    high: Union[pd.Series, np.ndarray],
    low: Union[pd.Series, np.ndarray],
    close: Union[pd.Series, np.ndarray]
) -> np.ndarray:
    """
    计算True Range
    
    TR = max(H-L, H-prev_C, prev_C-L)
    
    Args:
        high: 最高价序列
        low: 最低价序列
        close: 收盘价序列
        
    Returns:
        TR值数组
    """
    high = np.asarray(high, dtype=float)
    low = np.asarray(low, dtype=float)
    close = np.asarray(close, dtype=float)
    n = len(high)
    
    if n < 2:
        return np.full(n, np.nan)
    
    tr = np.zeros(n)
    tr[0] = high[0] - low[0]
    
    for i in range(1, n):
        tr[i] = max(
            high[i] - low[i],
            abs(high[i] - close[i - 1]),
            abs(low[i] - close[i - 1])
        )
    
    return tr


def calc_wilder_smoothing(
    data: np.ndarray,
    period: int
) -> np.ndarray:
    """
    Wilder平滑方法 (用于DMI, ADX等)
    
    Wilder_MA = prev_MA + (1/period) * (new_value - prev_MA)
    
    Args:
        data: 数据序列
        period: 周期
        
    Returns:
        平滑后的数组
    """
    n = len(data)
    result = np.full(n, np.nan)
    
    if n < period:
        return result
    
    # 初始值用简单平均
    result[period - 1] = np.sum(data[:period])
    
    # Wilder递推
    for i in range(period, n):
        result[i] = result[i - 1] + (data[i] - result[i - 1]) / period
    
    return result


def generate_trend_indicators(
    high: Union[pd.Series, np.ndarray],
    low: Union[pd.Series, np.ndarray],
    close: Union[pd.Series, np.ndarray],
    ma_periods: List[int] = [5, 10, 20, 60],
    ema_periods: List[int] = [12, 26],
    macd_params: Tuple[int, int, int] = (12, 26, 9),
    dmi_period: int = 14,
    adx_period: int = 14
) -> Dict[str, np.ndarray]:
    """
    批量生成趋势类指标
    
    Args:
        high: 最高价序列
        low: 最低价序列
        close: 收盘价序列
        ma_periods: MA周期列表
        ema_periods: EMA周期列表
        macd_params: MACD参数 (fast, slow, signal)
        dmi_period: DMI周期
        adx_period: ADX周期
        
    Returns:
        指标字典 {指标名: 值数组}
    """
    indicators = {}
    
    # MA系列
    for p in ma_periods:
        indicators[f'ma_{p}'] = calc_ma(close, p)
    
    # EMA系列
    for p in ema_periods:
        indicators[f'ema_{p}'] = calc_ema(close, p)
    
    # MACD
    macd, signal, hist = calc_macd(close, macd_params[0], macd_params[1], macd_params[2])
    indicators['macd'] = macd
    indicators['macd_signal'] = signal
    indicators['macd_hist'] = hist
    
    # MACD信号：MACD与Signal交叉
    indicators['macd_cross'] = np.sign(macd - signal)
    
    # DMI
    plus_di, minus_di, dx = calc_dmi(high, low, close, dmi_period)
    indicators[f'plus_di_{dmi_period}'] = plus_di
    indicators[f'minus_di_{dmi_period}'] = minus_di
    
    # ADX
    indicators[f'adx_{adx_period}'] = calc_adx(high, low, close, adx_period)
    
    # 趋势强度：ADX越高趋势越强
    indicators['trend_strength'] = indicators[f'adx_{adx_period}']
    
    # MA趋势：短期MA与长期MA的关系
    if 5 in ma_periods and 20 in ma_periods:
        indicators['ma_5_20_ratio'] = indicators['ma_5'] / indicators['ma_20']
        indicators['ma_trend'] = np.sign(indicators['ma_5'] - indicators['ma_20'])
    
    return indicators