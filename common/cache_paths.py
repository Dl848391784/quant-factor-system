#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
缓存路径配置模块
统一管理所有缓存目录路径，避免硬编码路径散落在各模块中
"""

from pathlib import Path

# 项目根目录
ROOT_DIR = Path(__file__).parent.parent.resolve()

# 数据缓存目录（存放 factor_data 等）
DATA_CACHE_DIR = ROOT_DIR / 'cache'

# 主要缓存路径
FACTOR_DATA_DIR = DATA_CACHE_DIR / 'factor_data'
BOLLINGER_PB_DIR = DATA_CACHE_DIR / 'bollinger_pb'
KDJ_J_DIR = DATA_CACHE_DIR / 'kdj_j'
MAIN_INFLOW_DIR = DATA_CACHE_DIR / 'main_inflow'

# 版本缓存目录
VERSIONS_DIR = ROOT_DIR / 'versions'
VERSION_CACHE_DIR = VERSIONS_DIR / 'cache'

def get_factor_data_path() -> Path:
    """获取因子数据文件路径"""
    return FACTOR_DATA_DIR / 'factor_data.json.gz'

def get_bollinger_pb_path() -> Path:
    """获取布林带 %B 数据文件路径"""
    return BOLLINGER_PB_DIR / 'bollinger_pb_history.json.gz'

def get_version_cache_dir(version: str) -> Path:
    """获取指定版本的缓存目录"""
    return VERSIONS_DIR / version / 'cache'