"""
数据加载路径定义

comprehensive_factor 模块专用数据路径配置。
"""

from pathlib import Path

# 默认缓存目录（复用项目级缓存）
DEFAULT_CACHE_DIR = Path(__file__).parent.parent.parent / 'cache' / 'factor_data'

# 默认 IC 结果目录
DEFAULT_IC_RESULT_DIR = Path(__file__).parent.parent.parent / 'factor_ic' / 'result'