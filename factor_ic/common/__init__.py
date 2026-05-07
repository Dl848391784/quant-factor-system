#!/usr/bin/env python3
"""公共模块"""
from .data_completeness import check_data_completeness, check_incremental_update
__all__ = ['check_data_completeness', 'check_incremental_update']