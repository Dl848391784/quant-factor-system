"""
动量类技术指标模块

包含：
- CCI (Commodity Channel Index)
- Williams %R
- ROC (Rate of Change)
- RSI (Relative Strength Index)
"""

import numpy as np
import pandas as pd
from typing import Dict, List, Optional, Tuple, Union
import warnings

warnings.filterwarnings('ignore')


def calc_cci(
    high: Union[pd.Series, np.ndarray],
    low: Union[pd.Series, np.ndarray],
    close: Union[pd.Series, np.ndarray],
    period: int = 20
) -> np.ndarray:
    """
    计算CCI指标 (Commodity Channel Index)
    
    TP = (High + Low + Close) / 3
    CCI = (TP - SMA(TP)) / (0.015 * MD(TP))
    MD = Mean Deviation
    
    Args:
        high: 最高价序列
        low: 最低价序列
        close: 收盘价序列
        period: 周期
        
    Returns:
        CCI值数组
    """
    high = np.asarray(high, dtype=float)
    low = np.asarray(low, dtype=float)
    close = np.asarray(close, dtype=float)
    n = len(close)
    
    if n < period:
        return np.full(n, np.nan)
    
    # Typical Price
    tp = (high + low + close) / 3
    
    result = np.full(n, np.nan)
    
    for i in range(period - 1, n):
        tp_window = tp[i - period + 1:i + 1]
        sma = np.mean(tp_window)
        
        # Mean Deviation
        md = np.mean(np.abs(tp_window - sma))
        
        if md > 0:
            result[i] = (tp[i] - sma) / (0.015 * md)
        else:
            result[i] = 0
    
    return result


def calc_williams_r(
    high: Union[pd.Series, np.ndarray],
    low: Union[pd.Series, np.ndarray],
    close: Union[pd.Series, np.ndarray],
    period: int = 14
) -> np.ndarray:
    """
    计算Williams %R
    
    %R = (Highest_High - Close) / (Highest_High - Lowest_Low) * (-100)
    
    Range: -100 to 0
    Overbought: > -20
    Oversold: < -80
    
    Args:
        high: 最高价序列
        low: 最低价序列
        close: 收盘价序列
        period: 周期
        
    Returns:
        Williams %R值数组
    """
    high = np.asarray(high, dtype=float)
    low = np.asarray(low, dtype=float)
    close = np.asarray(close, dtype=float)
    n = len(close)
    
    if n < period:
        return np.full(n, np.nan)
    
    result = np.full(n, np.nan)
    
    for i in range(period - 1, n):
        highest = np.max(high[i - period + 1:i + 1])
        lowest = np.min(low[i - period + 1:i + 1])
        
        if highest > lowest:
            result[i] = (highest - close[i]) / (highest - lowest) * (-100)
        else:
            result[i] = -50  # 中间值
    
    return result


def calc_roc(
    close: Union[pd.Series, np.ndarray],
    period: int = 12
) -> np.ndarray:
    """
    计算ROC指标 (Rate of Change)
    
    ROC = (Close - prev_Close) / prev_Close * 100
    
    Args:
        close: 收盘价序列
        period: 周期
        
    Returns:
        ROC值数组
    """
    close = np.asarray(close, dtype=float)
    n = len(close)
    
    if n < period:
        return np.full(n, np.nan)
    
    result = np.full(n, np.nan)
    
    for i in range(period, n):
        if close[i - period] > 0:
            result[i] = (close[i] - close[i - period]) / close[i - period] * 100
    
    return result


def calc_rsi(
    close: Union[pd.Series, np.ndarray],
    period: int = 14
) -> np.ndarray:
    """
    计算RSI指标 (Relative Strength Index)
    
    RSI = 100 - 100 / (1 + RS)
    RS = Average Gain / Average Loss
    
    使用Wilder平滑方法
    
    Args:
        close: 收盘价序列
        period: 周期
        
    Returns:
        RSI值数组
    """
    close = np.asarray(close, dtype=float)
    n = len(close)
    
    if n < period + 1:
        return np.full(n, np.nan)
    
    # 计算价格变动
    delta = np.diff(close)
    delta = np.concatenate([[0], delta])
    
    # 分离涨跌
    gains = np.where(delta > 0, delta, 0)
    losses = np.where(delta < 0, -delta, 0)
    
    result = np.full(n, np.nan)
    
    # 初始平均
    avg_gain = np.mean(gains[1:period + 1])
    avg_loss = np.mean(losses[1:period + 1])
    
    # 计算第一个RSI
    if avg_loss > 0:
        rs = avg_gain / avg_loss
        result[period] = 100 - 100 / (1 + rs)
    else:
        result[period] = 100
    
    # Wilder平滑递推
    for i in range(period + 1, n):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
        
        if avg_loss > 0:
            rs = avg_gain / avg_loss
            result[i] = 100 - 100 / (1 + rs)
        else:
            result[i] = 100
    
    return result


def calc_momentum(
    close: Union[pd.Series, np.ndarray],
    period: int = 10
) -> np.ndarray:
    """
    计算动量指标
    
    Momentum = Close - prev_Close
    
    Args:
        close: 收盘价序列
        period: 周期
        
    Returns:
        动量值数组
    """
    close = np.asarray(close, dtype=float)
    n = len(close)
    
    if n < period:
        return np.full(n, np.nan)
    
    result = np.full(n, np.nan)
    
    for i in range(period, n):
        result[i] = close[i] - close[i - period]
    
    return result


def calc_stoch(
    high: Union[pd.Series, np.ndarray],
    low: Union[pd.Series, np.ndarray],
    close: Union[pd.Series, np.ndarray],
    k_period: int = 14,
    d_period: int = 3
) -> Tuple[np.ndarray, np.ndarray]:
    """
    计算Stochastic指标
    
    %K = (Close - Lowest_Low) / (Highest_High - Lowest_Low) * 100
    %D = SMA(%K, d_period)
    
    Args:
        high: 最高价序列
        low: 最低价序列
        close: 收盘价序列
        k_period: K线周期
        d_period: D线周期
        
    Returns:
        (%K, %D)
    """
    high = np.asarray(high, dtype=float)
    low = np.asarray(low, dtype=float)
    close = np.asarray(close, dtype=float)
    n = len(close)
    
    if n < k_period:
        return np.full(n, np.nan), np.full(n, np.nan)
    
    k = np.full(n, np.nan)
    
    for i in range(k_period - 1, n):
        highest = np.max(high[i - k_period + 1:i + 1])
        lowest = np.min(low[i - k_period + 1:i + 1])
        
        if highest > lowest:
            k[i] = (close[i] - lowest) / (highest - lowest) * 100
        else:
            k[i] = 50
    
    # %D = SMA of %K
    d = np.full(n, np.nan)
    for i in range(k_period + d_period - 2, n):
        d[i] = np.mean(k[i - d_period + 1:i + 1])
    
    return k, d


def generate_momentum_indicators(
    high: Union[pd.Series, np.ndarray],
    low: Union[pd.Series, np.ndarray],
    close: Union[pd.Series, np.ndarray],
    cci_period: int = 20,
    williams_r_period: int = 14,
    roc_period: int = 12,
    rsi_periods: List[int] = [6, 12, 24],
    momentum_period: int = 10,
    stoch_params: Tuple[int, int] = (14, 3)
) -> Dict[str, np.ndarray]:
    """
    批量生成动量类指标
    
    Args:
        high: 最高价序列
        low: 最低价序列
        close: 收盘价序列
        cci_period: CCI周期
        williams_r_period: Williams %R周期
        roc_period: ROC周期
        rsi_periods: RSI周期列表
        momentum_period: 动量周期
        stoch_params: Stochastic参数 (k_period, d_period)
        
    Returns:
        指标字典 {指标名: 值数组}
    """
    indicators = {}
    
    # CCI
    indicators[f'cci_{cci_period}'] = calc_cci(high, low, close, cci_period)
    
    # CCI信号
    cci = indicators[f'cci_{cci_period}']
    indicators['cci_overbought'] = np.where(cci > 100, 1, 0)
    indicators['cci_oversold'] = np.where(cci < -100, 1, 0)
    
    # Williams %R
    indicators[f'williams_r_{williams_r_period}'] = calc_williams_r(high, low, close, williams_r_period)
    
    # Williams %R信号
    wr = indicators[f'williams_r_{williams_r_period}']
    indicators['wr_overbought'] = np.where(wr > -20, 1, 0)
    indicators['wr_oversold'] = np.where(wr < -80, 1, 0)
    
    # ROC
    indicators[f'roc_{roc_period}'] = calc_roc(close, roc_period)
    
    # ROC方向信号
    roc = indicators[f'roc_{roc_period}']
    indicators['roc_direction'] = np.sign(roc)
    
    # RSI系列
    for p in rsi_periods:
        indicators[f'rsi_{p}'] = calc_rsi(close, p)
    
    # RSI信号 (用默认周期)
    default_rsi = indicators.get(f'rsi_{rsi_periods[0]}')
    if default_rsi is not None:
        indicators['rsi_overbought'] = np.where(default_rsi > 70, 1, 0)
        indicators['rsi_oversold'] = np.where(default_rsi < 30, 1, 0)
        indicators['rsi_signal'] = np.where(default_rsi > 50, 1, np.where(default_rsi < 50, -1, 0))
    
    # RSI差值 (短期RSI - 长期RSI)
    if len(rsi_periods) >= 2:
        short_rsi = indicators[f'rsi_{rsi_periods[0]}']
        long_rsi = indicators[f'rsi_{rsi_periods[-1]}']
        indicators['rsi_diff'] = short_rsi - long_rsi
    
    # Momentum
    indicators[f'momentum_{momentum_period}'] = calc_momentum(close, momentum_period)
    
    # Stochastic
    k_period, d_period = stoch_params
    k, d = calc_stoch(high, low, close, k_period, d_period)
    indicators[f'stoch_k_{k_period}'] = k
    indicators[f'stoch_d_{k_period}'] = d
    
    # Stochastic信号
    indicators['stoch_cross'] = np.sign(k - d)
    indicators['stoch_overbought'] = np.where(k > 80, 1, 0)
    indicators['stoch_oversold'] = np.where(k < 20, 1, 0)
    
    # 综合动量信号
    # 结合RSI和CCI的超买超卖
    if default_rsi is not None:
        combined_signal = np.where(
            (default_rsi > 70) & (cci > 100), 1,  # 强超买
            np.where(
                (default_rsi < 30) & (cci < -100), -1,  # 强超卖
                0
            )
        )
        indicators['momentum_extreme'] = combined_signal
    
    return indicators