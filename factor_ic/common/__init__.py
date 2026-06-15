#!/usr/bin/env python3
"""公共模块"""

# CLI 辅助（safe_dict / format_finite / DEFAULT_MIN_STOCKS）
from .cli_helpers import DEFAULT_MIN_STOCKS, format_finite, safe_dict

# 数据完整性检查
from .data_completeness import check_data_completeness, check_incremental_update

# 数据加载（单文件模式）
from .data_loader import get_data_cache_path, get_data_dir, load_factor_return_data

# 主入口
from .factor_ic_runner import run_complex_factor_ic, run_factor_ic_analysis, run_simple_factor_ic

# IC 计算
from .ic_calculator import calculate_ic_statistics, calculate_ic_with_direction_verification, calculate_single_day_ic

# IC 结果构建
from .ic_result_builder import build_error_result, build_ic_result, get_ic_output_path, save_ic_result

# 增量引擎
from .incremental_engine import incremental_update_ic, should_use_incremental


__all__ = [
    'DEFAULT_MIN_STOCKS',
    'safe_dict',
    'format_finite',
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
