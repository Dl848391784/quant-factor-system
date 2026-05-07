"""
波动类技术指标模块

包含：
- ATR (Average True Range)
- Bollinger宽度 (布林带宽)
- Keltner通道
"""

import numpy as np
import pandas as pd
from typing import Dict, List, Optional, Tuple, Union
import warnings

warnings.filterwarnings('ignore')


def calc_atr(
    high: Union[pd.Series, np.ndarray],
    low: Union[pd.Series, np.ndarray],
    close: Union[pd.Series, np.ndarray],
    period: int = 14
) -> np.ndarray:
    """
    计算ATR指标 (Average True Range)
    
    ATR = Wilder平滑(TR)
    
    Args:
        high: 最高价序列
        low: 最低价序列
        close: 收盘价序列
        period: 周期
        
    Returns:
        ATR值数组
    """
    from .trend_indicators import calc_tr, calc_wilder_smoothing
    
    high = np.asarray(high, dtype=float)
    low = np.asarray(low, dtype=float)
    close = np.asarray(close, dtype=float)
    
    tr = calc_tr(high, low, close)
    atr = calc_wilder_smoothing(tr, period)
    
    return atr


def calc_bollinger(
    close: Union[pd.Series, np.ndarray],
    period: int = 20,
    std_dev: float = 2.0
) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """
    计算Bollinger Bands
    
    Middle = MA(close, period)
    Upper = Middle + std_dev * Std(close, period)
    Lower = Middle - std_dev * Std(close, period)
    
    Args:
        close: 收盘价序列
        period: 周期
        std_dev: 标准差倍数
        
    Returns:
        (Upper, Middle, Lower)
    """
    from .trend_indicators import calc_ma
    
    close = np.asarray(close, dtype=float)
    n = len(close)
    
    middle = calc_ma(close, period)
    
    # 计算滚动标准差
    std = np.full(n, np.nan)
    for i in range(period - 1, n):
        std[i] = np.std(close[i - period + 1:i + 1], ddof=1)
    
    upper = middle + std_dev * std
    lower = middle - std_dev * std
    
    return upper, middle, lower


def calc_bollinger_width(
    close: Union[pd.Series, np.ndarray],
    period: int = 20,
    std_dev: float = 2.0
) -> np.ndarray:
    """
    计算Bollinger带宽
    
    Band Width = (Upper - Lower) / Middle
    
    Args:
        close: 收盘价序列
        period: 周期
        std_dev: 标准差倍数
        
    Returns:
        布林带宽值数组
    """
    upper, middle, lower = calc_bollinger(close, period, std_dev)
    
    width = np.where(
        middle > 0,
        (upper - lower) / middle * 100,
        np.nan
    )
    
    return width


def calc_bollinger_pb(
    close: Union[pd.Series, np.ndarray],
    period: int = 20,
    std_dev: float = 2.0
) -> np.ndarray:
    """
    计算Bollinger %B
    
    %B = (Price - Lower) / (Upper - Lower)
    
    Args:
        close: 收盘价序列
        period: 周期
        std_dev: 标准差倍数
        
    Returns:
        %B值数组
    """
    upper, middle, lower = calc_bollinger(close, period, std_dev)
    close = np.asarray(close, dtype=float)
    
    pb = np.where(
        (upper - lower) > 0,
        (close - lower) / (upper - lower),
        np.nan
    )
    
    return pb


def calc_keltner(
    high: Union[pd.Series, np.ndarray],
    low: Union[pd.Series, np.ndarray],
    close: Union[pd.Series, np.ndarray],
    period: int = 20,
    atr_mult: float = 2.0
) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """
    计算Keltner Channel
    
    Middle = EMA(close, period)
    Upper = Middle + atr_mult * ATR
    Lower = Middle - atr_mult * ATR
    
    Args:
        high: 最高价序列
        low: 最低价序列
        close: 收盘价序列
        period: 周期
        atr_mult: ATR倍数
        
    Returns:
        (Upper, Middle, Lower)
    """
    from .trend_indicators import calc_ema
    
    close = np.asarray(close, dtype=float)
    
    middle = calc_ema(close, period)
    atr = calc_atr(high, low, close, period)
    
    upper = middle + atr_mult * atr
    lower = middle - atr_mult * atr
    
    return upper, middle, lower


def calc_keltner_width(
    high: Union[pd.Series, np.ndarray],
    low: Union[pd.Series, np.ndarray],
    close: Union[pd.Series, np.ndarray],
    period: int = 20,
    atr_mult: float = 2.0
) -> np.ndarray:
    """
    计算Keltner带宽
    
    Width = (Upper - Lower) / Middle
    
    Args:
        high: 最高价序列
        low: 最低价序列
        close: 收盘价序列
        period: 周期
        atr_mult: ATR倍数
        
    Returns:
        Keltner带宽值数组
    """
    upper, middle, lower = calc_keltner(high, low, close, period, atr_mult)
    
    width = np.where(
        middle > 0,
        (upper - lower) / middle * 100,
        np.nan
    )
    
    return width


def calc_donchian(
    high: Union[pd.Series, np.ndarray],
    low: Union[pd.Series, np.ndarray],
    period: int = 20
) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """
    计算Donchian Channel
    
    Upper = max(High, period)
    Lower = min(Low, period)
    Middle = (Upper + Lower) / 2
    
    Args:
        high: 最高价序列
        low: 最低价序列
        period: 周期
        
    Returns:
        (Upper, Middle, Lower)
    """
    high = np.asarray(high, dtype=float)
    low = np.asarray(low, dtype=float)
    n = len(high)
    
    upper = np.full(n, np.nan)
    lower = np.full(n, np.nan)
    
    for i in range(period - 1, n):
        upper[i] = np.max(high[i - period + 1:i + 1])
        lower[i] = np.min(low[i - period + 1:i + 1])
    
    middle = (upper + lower) / 2
    
    return upper, middle, lower


def calc_volatility_ratio(
    high: Union[pd.Series, np.ndarray],
    low: Union[pd.Series, np.ndarray],
    close: Union[pd.Series, np.ndarray],
    period: int = 14
) -> np.ndarray:
    """
    计算波动率比率
    
    Volatility Ratio = Current TR / ATR
    
    用于衡量当前波动相对于历史平均波动的强度
    
    Args:
        high: 最高价序列
        low: 最低价序列
        close: 收盘价序列
        period: 周期
        
    Returns:
        波动率比率数组
    """
    from .trend_indicators import calc_tr
    
    high = np.asarray(high, dtype=float)
    low = np.asarray(low, dtype=float)
    close = np.asarray(close, dtype=float)
    
    tr = calc_tr(high, low, close)
    atr = calc_atr(high, low, close, period)
    
    ratio = np.where(
        atr > 0,
        tr / atr,
        np.nan
    )
    
    return ratio


def generate_volatility_indicators(
    high: Union[pd.Series, np.ndarray],
    low: Union[pd.Series, np.ndarray],
    close: Union[pd.Series, np.ndarray],
    atr_period: int = 14,
    bollinger_params: Tuple[int, float] = (20, 2.0),
    keltner_params: Tuple[int, float] = (20, 2.0),
    donchian_period: int = 20
) -> Dict[str, np.ndarray]:
    """
    批量生成波动类指标
    
    Args:
        high: 最高价序列
        low: 最低价序列
        close: 收盘价序列
        atr_period: ATR周期
        bollinger_params: Bollinger参数 (period, std_dev)
        keltner_params: Keltner参数 (period, atr_mult)
        donchian_period: Donchian周期
        
    Returns:
        指标字典 {指标名: 值数组}
    """
    indicators = {}
    
    close = np.asarray(close, dtype=float)
    
    # ATR
    indicators[f'atr_{atr_period}'] = calc_atr(high, low, close, atr_period)
    
    # ATR比率 (相对于收盘价)
    atr = indicators[f'atr_{atr_period}']
    indicators['atr_pct'] = np.where(close > 0, atr / close * 100, np.nan)
    
    # Bollinger
    b_period, b_std = bollinger_params
    upper_b, middle_b, lower_b = calc_bollinger(close, b_period, b_std)
    indicators[f'bollinger_upper_{b_period}'] = upper_b
    indicators[f'bollinger_middle_{b_period}'] = middle_b
    indicators[f'bollinger_lower_{b_period}'] = lower_b
    indicators[f'bollinger_width_{b_period}'] = calc_bollinger_width(close, b_period, b_std)
    indicators[f'bollinger_pb_{b_period}'] = calc_bollinger_pb(close, b_period, b_std)
    
    # Bollinger位置信号
    pb = indicators[f'bollinger_pb_{b_period}']
    indicators['bollinger_position'] = np.where(pb > 1, 1, np.where(pb < 0, -1, 0))
    
    # Keltner
    k_period, k_mult = keltner_params
    upper_k, middle_k, lower_k = calc_keltner(high, low, close, k_period, k_mult)
    indicators[f'keltner_upper_{k_period}'] = upper_k
    indicators[f'keltner_middle_{k_period}'] = middle_k
    indicators[f'keltner_lower_{k_period}'] = lower_k
    indicators[f'keltner_width_{k_period}'] = calc_keltner_width(high, low, close, k_period, k_mult)
    
    # Keltner位置信号
    k_pos = np.where(
        middle_k > 0,
        (close - middle_k) / (upper_k - lower_k) * 2,
        np.nan
    )
    indicators['keltner_position'] = np.where(k_pos > 1, 1, np.where(k_pos < -1, -1, 0))
    
    # Donchian
    upper_d, middle_d, lower_d = calc_donchian(high, low, donchian_period)
    indicators[f'donchian_upper_{donchian_period}'] = upper_d
    indicators[f'donchian_lower_{donchian_period}'] = lower_d
    indicators[f'donchian_width_{donchian_period}'] = np.where(
        middle_d > 0,
        (upper_d - lower_d) / middle_d * 100,
        np.nan
    )
    
    # Donchian位置信号
    indicators['donchian_breakout_up'] = np.where(close >= upper_d, 1, 0)
    indicators['donchian_breakout_down'] = np.where(close <= lower_d, 1, 0)
    
    # 波动率比率
    indicators['volatility_ratio'] = calc_volatility_ratio(high, low, close, atr_period)
    
    # Band宽度比率 (Bollinger vs Keltner - Squeeze指标)
    bw = indicators[f'bollinger_width_{b_period}']
    kw = indicators[f'keltner_width_{k_period}']
    indicators['squeeze_indicator'] = np.where(
        kw > 0,
        bw / kw,
        np.nan
    )
    
    return indicators