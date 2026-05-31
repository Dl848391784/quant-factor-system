#!/usr/bin/env python3
"""公共模块"""

# 数据完整性检查
from .data_completeness import check_data_completeness, check_incremental_update

# 数据加载（单文件模式）
from .data_loader import load_factor_return_data, get_data_cache_path, get_data_dir

# IC 计算
from .ic_calculator import calculate_ic_with_direction_verification, calculate_single_day_ic, calculate_ic_statistics

# IC 结果构建
from .ic_result_builder import build_ic_result, build_error_result, save_ic_result, get_ic_output_path

# 增量引擎
from .incremental_engine import incremental_update_ic, should_use_incremental

# 主入口
from .factor_ic_runner import run_factor_ic_analysis, run_simple_factor_ic, run_complex_factor_ic

__all__ = [
    'check_data_completeness',
    'check_incremental_update',
    'load_factor_return_data',
    'get_data_cache_path',
    'get_data_dir',
    'calculate_ic_with_direction_verification',
    'calculate_single_day_ic',
    'calculate_ic_statistics',
    'build_ic_result',
    'build_error_result',
    'save_ic_result',
    'get_ic_output_path',
    'incremental_update_ic',
    'should_use_incremental',
    'run_factor_ic_analysis',
    'run_simple_factor_ic',
    'run_complex_factor_ic'
]