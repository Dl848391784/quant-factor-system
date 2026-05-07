#!/usr/bin/env python3
"""
版本动态适配模块 - quick_backtest wrapper
根据 versions/current_version.json 动态导入对应版本模块
"""

import json
import sys
from pathlib import Path
import importlib

# 获取当前版本
def get_current_version():
    """获取当前激活版本"""
    version_file = Path(__file__).parent / 'versions' / 'current_version.json'
    if version_file.exists():
        with open(version_file, 'r', encoding='utf-8') as f:
            return json.load(f).get('current_version', 'v1')
    return 'v1'

# 添加versions目录到sys.path
ROOT_DIR = Path(__file__).parent
sys.path.insert(0, str(ROOT_DIR))
sys.path.insert(0, str(ROOT_DIR / 'versions'))

# 动态导入版本模块
_current_version = get_current_version()
_version_module = importlib.import_module(f'{_current_version}.optimizer.quick_backtest')

# 导出所有函数和变量
QuickBacktestValidator = _version_module.QuickBacktestValidator
parallel_backtest_batch = _version_module.parallel_backtest_batch

# 导出其他可能的函数
__all__ = [name for name in dir(_version_module) if not name.startswith('_')]