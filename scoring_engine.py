#!/usr/bin/env python3
"""
版本动态适配模块 - scoring_engine wrapper
从 common.scoring_engine 导入基础模块
"""

import sys
from pathlib import Path
import importlib

# 确保common目录在路径中
ROOT_DIR = Path(__file__).parent
sys.path.insert(0, str(ROOT_DIR))

# 从common导入
_common_module = importlib.import_module('common.scoring_engine')

# 导出所有函数和变量
ScoringEngine = _common_module.ScoringEngine
get_cached_engine = _common_module.get_cached_engine
load_factor_ic_data = _common_module.load_factor_ic_data
preload_engine_data = _common_module.preload_engine_data
get_smart_weight_generator = _common_module.get_smart_weight_generator

# 导出其他可能的函数
__all__ = [name for name in dir(_common_module) if not name.startswith('_')]