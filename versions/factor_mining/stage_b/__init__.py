"""
阶段B：OHLCV衍生技术指标模块

从OHLCV基础数据衍生20+技术指标，生成因子候选池
"""

from .trend_indicators import (
    calc_ma, calc_ema, calc_macd, calc_dmi, calc_adx,
    generate_trend_indicators
)
from .volatility_indicators import (
    calc_atr, calc_bollinger_width, calc_keltner,
    generate_volatility_indicators
)
from .momentum_indicators import (
    calc_cci, calc_williams_r, calc_roc, calc_rsi,
    generate_momentum_indicators
)
from .volume_indicators import (
    calc_obv, calc_vwap, calc_mfi, calc_volume_oscillator,
    generate_volume_indicators
)
from .pipeline import StageBPipeline

__all__ = [
    # 趋势类
    'calc_ma', 'calc_ema', 'calc_macd', 'calc_dmi', 'calc_adx',
    'generate_trend_indicators',
    # 波动类
    'calc_atr', 'calc_bollinger_width', 'calc_keltner',
    'generate_volatility_indicators',
    # 动量类
    'calc_cci', 'calc_williams_r', 'calc_roc', 'calc_rsi',
    'generate_momentum_indicators',
    # 成交量类
    'calc_obv', 'calc_vwap', 'calc_mfi', 'calc_volume_oscillator',
    'generate_volume_indicators',
    # Pipeline
    'StageBPipeline'
]