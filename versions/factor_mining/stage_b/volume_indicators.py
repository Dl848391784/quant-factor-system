"""
成交量类技术指标模块

包含：
- OBV (On Balance Volume)
- VWAP (Volume Weighted Average Price)
- MFI (Money Flow Index)
- Volume Oscillator
"""

import numpy as np
import pandas as pd
from typing import Dict, List, Optional, Tuple, Union
import warnings

warnings.filterwarnings('ignore')


def calc_obv(
    close: Union[pd.Series, np.ndarray],
    volume: Union[pd.Series, np.ndarray]
) -> np.ndarray:
    """
    计算OBV指标 (On Balance Volume)
    
    OBV = prev_OBV + sign(Price_change) * Volume
    
    Args:
        close: 收盘价序列
        volume: 成交量序列
        
    Returns:
        OBV值数组
    """
    close = np.asarray(close, dtype=float)
    volume = np.asarray(volume, dtype=float)
    n = len(close)
    
    if n < 2:
        return np.full(n, np.nan)
    
    result = np.zeros(n)
    
    for i in range(1, n):
        if close[i] > close[i - 1]:
            result[i] = result[i - 1] + volume[i]
        elif close[i] < close[i - 1]:
            result[i] = result[i - 1] - volume[i]
        else:
            result[i] = result[i - 1]
    
    return result


def calc_vwap(
    high: Union[pd.Series, np.ndarray],
    low: Union[pd.Series, np.ndarray],
    close: Union[pd.Series, np.ndarray],
    volume: Union[pd.Series, np.ndarray],
    period: Optional[int] = None
) -> np.ndarray:
    """
    计算VWAP指标 (Volume Weighted Average Price)
    
    VWAP = sum(TP * Volume) / sum(Volume)
    TP = (High + Low + Close) / 3
    
    Args:
        high: 最高价序列
        low: 最低价序列
        close: 收盘价序列
        volume: 成交量序列
        period: 滚动周期 (None表示累计VWAP)
        
    Returns:
        VWAP值数组
    """
    high = np.asarray(high, dtype=float)
    low = np.asarray(low, dtype=float)
    close = np.asarray(close, dtype=float)
    volume = np.asarray(volume, dtype=float)
    n = len(close)
    
    # Typical Price
    tp = (high + low + close) / 3
    
    result = np.full(n, np.nan)
    
    if period is None:
        # 累计VWAP
        cum_tp_vol = 0
        cum_vol = 0
        for i in range(n):
            cum_tp_vol += tp[i] * volume[i]
            cum_vol += volume[i]
            if cum_vol > 0:
                result[i] = cum_tp_vol / cum_vol
    else:
        # 滚动VWAP
        if n < period:
            return result
        
        for i in range(period - 1, n):
            tp_window = tp[i - period + 1:i + 1]
            vol_window = volume[i - period + 1:i + 1]
            vol_sum = np.sum(vol_window)
            if vol_sum > 0:
                result[i] = np.sum(tp_window * vol_window) / vol_sum
    
    return result


def calc_mfi(
    high: Union[pd.Series, np.ndarray],
    low: Union[pd.Series, np.ndarray],
    close: Union[pd.Series, np.ndarray],
    volume: Union[pd.Series, np.ndarray],
    period: int = 14
) -> np.ndarray:
    """
    计算MFI指标 (Money Flow Index)
    
    MFI = 100 - 100 / (1 + Money_Ratio)
    Money_Ratio = Positive_MF / Negative_MF
    MF = TP * Volume
    
    Args:
        high: 最高价序列
        low: 最低价序列
        close: 收盘价序列
        volume: 成交量序列
        period: 周期
        
    Returns:
        MFI值数组
    """
    high = np.asarray(high, dtype=float)
    low = np.asarray(low, dtype=float)
    close = np.asarray(close, dtype=float)
    volume = np.asarray(volume, dtype=float)
    n = len(close)
    
    if n < period + 1:
        return np.full(n, np.nan)
    
    # Typical Price
    tp = (high + low + close) / 3
    
    # Money Flow
    mf = tp * volume
    
    # 正负MF
    positive_mf = np.where(tp > np.roll(tp, 1), mf, 0)
    negative_mf = np.where(tp < np.roll(tp, 1), mf, 0)
    
    # 第一天设为0
    positive_mf[0] = 0
    negative_mf[0] = 0
    
    result = np.full(n, np.nan)
    
    for i in range(period, n):
        pos_sum = np.sum(positive_mf[i - period + 1:i + 1])
        neg_sum = np.sum(negative_mf[i - period + 1:i + 1])
        
        if neg_sum > 0:
            mr = pos_sum / neg_sum
            result[i] = 100 - 100 / (1 + mr)
        else:
            result[i] = 100
    
    return result


def calc_volume_oscillator(
    volume: Union[pd.Series, np.ndarray],
    fast_period: int = 5,
    slow_period: int = 10
) -> np.ndarray:
    """
    计算成交量震荡指标
    
    Volume Oscillator = Fast_MA - Slow_MA
    
    Args:
        volume: 成交量序列
        fast_period: 快线周期
        slow_period: 慢线周期
        
    Returns:
        成交量震荡值数组
    """
    from .trend_indicators import calc_ma
    
    volume = np.asarray(volume, dtype=float)
    
    fast_ma = calc_ma(volume, fast_period)
    slow_ma = calc_ma(volume, slow_period)
    
    osc = fast_ma - slow_ma
    
    return osc


def calc_volume_ratio(
    volume: Union[pd.Series, np.ndarray],
    period: int = 5
) -> np.ndarray:
    """
    计算量比
    
    Volume Ratio = Current Volume / MA(Volume, period)
    
    Args:
        volume: 成交量序列
        period: 周期
        
    Returns:
        量比值数组
    """
    from .trend_indicators import calc_ma
    
    volume = np.asarray(volume, dtype=float)
    n = len(volume)
    
    ma_vol = calc_ma(volume, period)
    
    ratio = np.where(
        ma_vol > 0,
        volume / ma_vol,
        np.nan
    )
    
    return ratio


def calc_volume_zscore(
    volume: Union[pd.Series, np.ndarray],
    period: int = 20
) -> np.ndarray:
    """
    计算成交量Z-Score
    
    Z-Score = (Volume - MA) / Std
    
    Args:
        volume: 成交量序列
        period: 周期
        
    Returns:
        成交量Z-Score数组
    """
    volume = np.asarray(volume, dtype=float)
    n = len(volume)
    
    from .trend_indicators import calc_ma
    
    mean = calc_ma(volume, period)
    
    std = np.full(n, np.nan)
    for i in range(period - 1, n):
        std[i] = np.std(volume[i - period + 1:i + 1], ddof=1)
    
    zscore = np.where(
        std > 0,
        (volume - mean) / std,
        np.nan
    )
    
    return zscore


def calc_accumulation_distribution(
    high: Union[pd.Series, np.ndarray],
    low: Union[pd.Series, np.ndarray],
    close: Union[pd.Series, np.ndarray],
    volume: Union[pd.Series, np.ndarray]
) -> np.ndarray:
    """
    计算累积/派发线 (Accumulation/Distribution Line)
    
    AD = prev_AD + MF_multiplier * Volume
    MF_multiplier = ((Close - Low) - (High - Close)) / (High - Low)
    
    Args:
        high: 最高价序列
        low: 最低价序列
        close: 收盘价序列
        volume: 成交量序列
        
    Returns:
        AD线数组
    """
    high = np.asarray(high, dtype=float)
    low = np.asarray(low, dtype=float)
    close = np.asarray(close, dtype=float)
    volume = np.asarray(volume, dtype=float)
    n = len(close)
    
    if n < 2:
        return np.full(n, np.nan)
    
    # Money Flow Multiplier
    mf_mult = np.where(
        (high - low) > 0,
        ((close - low) - (high - close)) / (high - low),
        0
    )
    
    result = np.zeros(n)
    
    for i in range(1, n):
        result[i] = result[i - 1] + mf_mult[i] * volume[i]
    
    return result


def generate_volume_indicators(
    high: Union[pd.Series, np.ndarray],
    low: Union[pd.Series, np.ndarray],
    close: Union[pd.Series, np.ndarray],
    volume: Union[pd.Series, np.ndarray],
    obv_period: Optional[int] = None,
    vwap_period: Optional[int] = None,
    mfi_period: int = 14,
    volume_ratio_period: int = 5,
    volume_osc_params: Tuple[int, int] = (5, 10),
    volume_zscore_period: int = 20
) -> Dict[str, np.ndarray]:
    """
    批量生成成交量类指标
    
    Args:
        high: 最高价序列
        low: 最低价序列
        close: 收盘价序列
        volume: 成交量序列
        obv_period: OBV滚动周期 (None表示累计)
        vwap_period: VWAP滚动周期 (None表示累计)
        mfi_period: MFI周期
        volume_ratio_period: 量比周期
        volume_osc_params: 成交量震荡参数 (fast, slow)
        volume_zscore_period: 成交量Z-Score周期
        
    Returns:
        指标字典 {指标名: 值数组}
    """
    indicators = {}
    
    # OBV
    obv = calc_obv(close, volume)
    indicators['obv'] = obv
    
    # OBV滚动变化率
    if obv_period is not None and len(obv) >= obv_period:
        obv_change = np.full(len(obv), np.nan)
        for i in range(obv_period, len(obv)):
            if obv[i - obv_period] != 0:
                obv_change[i] = (obv[i] - obv[i - obv_period]) / abs(obv[i - obv_period])
        indicators['obv_change'] = obv_change
    
    # OBV与价格趋势对比
    obv_ma = np.full(len(obv), np.nan)
    from .trend_indicators import calc_ma
    obv_ma = calc_ma(obv, 20)
    indicators['obv_trend'] = np.sign(obv - obv_ma)
    
    # VWAP
    indicators['vwap'] = calc_vwap(high, low, close, volume, vwap_period)
    
    # VWAP偏离度
    close_arr = np.asarray(close, dtype=float)
    vwap = indicators['vwap']
    indicators['vwap_deviation'] = np.where(
        vwap > 0,
        (close_arr - vwap) / vwap * 100,
        np.nan
    )
    
    # VWAP信号
    indicators['vwap_signal'] = np.sign(close_arr - vwap)
    
    # MFI
    indicators[f'mfi_{mfi_period}'] = calc_mfi(high, low, close, volume, mfi_period)
    
    # MFI信号
    mfi = indicators[f'mfi_{mfi_period}']
    indicators['mfi_overbought'] = np.where(mfi > 80, 1, 0)
    indicators['mfi_oversold'] = np.where(mfi < 20, 1, 0)
    
    # 量比
    indicators[f'volume_ratio_{volume_ratio_period}'] = calc_volume_ratio(volume, volume_ratio_period)
    
    # 量比信号
    vr = indicators[f'volume_ratio_{volume_ratio_period}']
    indicators['volume_surge'] = np.where(vr > 2, 1, 0)  # 量比>2为放量
    indicators['volume_dry'] = np.where(vr < 0.5, 1, 0)   # 量比<0.5为缩量
    
    # 成交量震荡
    fast, slow = volume_osc_params
    indicators['volume_oscillator'] = calc_volume_oscillator(volume, fast, slow)
    
    # 成交量震荡信号
    vo = indicators['volume_oscillator']
    indicators['volume_osc_signal'] = np.sign(vo)
    
    # 成交量Z-Score
    indicators[f'volume_zscore_{volume_zscore_period}'] = calc_volume_zscore(volume, volume_zscore_period)
    
    # 成交量Z-Score信号
    vz = indicators[f'volume_zscore_{volume_zscore_period}']
    indicators['volume_abnormal_high'] = np.where(vz > 2, 1, 0)
    indicators['volume_abnormal_low'] = np.where(vz < -2, 1, 0)
    
    # 累积/派发线
    indicators['ad_line'] = calc_accumulation_distribution(high, low, close, volume)
    
    # AD线趋势
    ad = indicators['ad_line']
    ad_ma = calc_ma(ad, 20)
    indicators['ad_trend'] = np.sign(ad - ad_ma)
    
    # 量价关系
    # 价格上涨 + 量增 = 健康上涨
    # 价格下跌 + 量缩 = 健康下跌
    close_arr = np.asarray(close, dtype=float)
    price_change = np.sign(np.diff(close_arr))
    price_change = np.concatenate([[0], price_change])
    
    vol_change = np.sign(np.diff(np.asarray(volume, dtype=float)))
    vol_change = np.concatenate([[0], vol_change])
    
    indicators['price_volume_sync'] = np.where(
        (price_change > 0) & (vol_change > 0), 1,  # 同步上涨
        np.where(
            (price_change < 0) & (vol_change < 0), -1,  # 同步下跌
            0  # 不同步
        )
    )
    
    # 成交量加权动量
    from .momentum_indicators import calc_momentum
    momentum = calc_momentum(close, 5)
    vol_ma = calc_ma(np.asarray(volume, dtype=float), 5)
    indicators['volume_weighted_momentum'] = np.where(
        vol_ma > 0,
        momentum * np.asarray(volume, dtype=float) / vol_ma,
        np.nan
    )
    
    return indicators