"""
阶段A：统计组合因子模块

基于现有6因子进行数学组合生成新因子
"""

from .factor_combiner import FactorCombiner
from .ic_filter import ICFilter
from .safe_math import SafeMath
from .deduplicator import FactorDeduplicator
from .pipeline import StageAPipeline
from .data_loader import RealFactorLoader

__all__ = [
    'FactorCombiner',
    'ICFilter', 
    'SafeMath',
    'FactorDeduplicator',
    'StageAPipeline',
    'RealFactorLoader'
]