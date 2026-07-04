#!/usr/bin/env python3
"""
数据获取模块

提供数据拉取和因子生成功能。

公共 API：
- generate_all_factors: 统一因子生成入口
- get_module_logger: 获取模块 logger

版本历史：
- v1.0 (2026-05-25): 初始导出
"""

__all__ = [
    "generate_all_factors",
    "get_module_logger",
]

from data_fetchers.factor_generator import (
    generate_all_factors,
    get_module_logger,
)
