"""
数据加载路径定义

backtest 模块专用数据路径配置。
"""

from pathlib import Path

# 默认缓存目录（backtest 模块使用项目级缓存）
DEFAULT_CACHE_DIR = Path(__file__).parent.parent.parent / 'cache' / 'factor_data'