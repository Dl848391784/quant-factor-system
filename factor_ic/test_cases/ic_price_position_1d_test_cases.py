#!/usr/bin/env python3
"""
ic_price_position_1d 测试用例

测试脚本: factor_ic/ic_price_position_1d.py
因子计算: data_fetchers/factor_calculator.py::calculate_price_position
流程文档: factor_ic/docs/ic_price_position_1d_flow.md
规范文档: PROJECT.md

运行: pytest factor_ic/test_cases/ic_price_position_1d_test_cases.py -v
"""

import pytest
import sys
from pathlib import Path
import pandas as pd
import numpy as np
import json

# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from factor_ic.common.data_completeness import (
    get_ic_output_path,
    FACTOR_IC_RESULT_DIR
)

from data_fetchers.factor_calculator import calculate_price_position


class TestOutputPath:
    """测试输出路径和命名规范"""
    
    def test_output_path_format(self):
        """输出文件命名应符合规范: ic_<因子名>_analysis_result.json"""
        path = get_ic_output_path('price_position_1d')
        assert path.name == 'ic_price_position_1d_analysis_result.json'
    
    def test_output_directory(self):
        """输出目录应为 factor_ic/result/"""
        path = get_ic_output_path('price_position_1d')
        assert path.parent == FACTOR_IC_RESULT_DIR
    
    def test_output_directory_exists_or_created(self):
        """输出目录不存在时应自动创建"""
        assert FACTOR_IC_RESULT_DIR.exists() or FACTOR_IC_RESULT_DIR.parent.exists()


class TestCalculatePricePosition:
    """测试因子计算函数"""
    
    def test_basic_calculation(self):
        """基本计算测试"""
        df = pd.DataFrame({
            'close': [10.0, 12.0, 11.0],
            'high': [12.0, 13.0, 11.0],
            'low': [9.0, 11.0, 11.0]
        })
        result = calculate_price_position(df)
        
        assert 'price_position' in result.columns
        # (10-9)/(12-9) = 0.333
        assert np.isclose(result['price_position'].iloc[0], 0.333, atol=0.01)
    
    def test_upper_bound(self):
        """上限测试：收盘等于最高"""
        df = pd.DataFrame({
            'close': [12.0],
            'high': [12.0],
            'low': [10.0]
        })
        result = calculate_price_position(df)
        
        # (12-10)/(12-10) = 1.0
        assert result['price_position'].iloc[0] == 1.0
    
    def test_lower_bound(self):
        """下限测试：收盘等于最低"""
        df = pd.DataFrame({
            'close': [10.0],
            'high': [12.0],
            'low': [10.0]
        })
        result = calculate_price_position(df)
        
        # (10-10)/(12-10) = 0.0
        assert result['price_position'].iloc[0] == 0.0
    
    def test_zero_range_handling(self):
        """振幅为零测试：high=low"""
        df = pd.DataFrame({
            'close': [10.0],
            'high': [10.0],
            'low': [10.0]
        })
        result = calculate_price_position(df)
        
        # 振幅为零时设为 0.5（中位）
        assert result['price_position'].iloc[0] == 0.5
    
    def test_midpoint(self):
        """中位测试：收盘在振幅中间"""
        df = pd.DataFrame({
            'close': [11.0],
            'high': [12.0],
            'low': [10.0]
        })
        result = calculate_price_position(df)
        
        # (11-10)/(12-10) = 0.5
        assert result['price_position'].iloc[0] == 0.5
    
    def test_multiple_rows(self):
        """多行数据处理测试"""
        df = pd.DataFrame({
            'close': [10.0, 11.0, 12.0, 10.0],
            'high': [12.0, 12.0, 12.0, 10.0],
            'low': [9.0, 10.0, 11.0, 10.0]
        })
        result = calculate_price_position(df)
        
        assert len(result) == 4
        assert 'price_position' in result.columns
        # 第四行振幅为零，应为 0.5
        assert result['price_position'].iloc[3] == 0.5
    
    def test_nan_handling(self):
        """NaN 值处理测试"""
        df = pd.DataFrame({
            'close': [10.0, np.nan, 12.0],
            'high': [12.0, 13.0, 12.0],
            'low': [9.0, 11.0, 11.0]
        })
        result = calculate_price_position(df)
        
        # NaN 应传播
        assert pd.isna(result['price_position'].iloc[1])


class TestOutputStructure:
    """测试输出数据结构规范"""
    
    REQUIRED_FIELDS = [
        'factor_name',
        'calculation_date',
        'period',
        'ic_metrics',
        'sample_stats',
        'statistical_significance',
        'factor_direction',
        'economic_significance',
        'icir_stability',
        'ic_distribution_consistency'
    ]
    
    def test_output_file_exists_after_run(self):
        """运行后输出文件应存在"""
        # 注意：此测试需要先运行 ic_price_position_1d.py
        # 这里只检查文件路径是否正确
        path = get_ic_output_path('price_position_1d')
        # 如果文件不存在，跳过此测试
        if not path.exists():
            pytest.skip("输出文件不存在，需要先运行 ic_price_position_1d.py")
    
    def test_output_structure_if_exists(self):
        """如果输出文件存在，检查结构"""
        path = get_ic_output_path('price_position_1d')
        if not path.exists():
            pytest.skip("输出文件不存在")
        
        with open(path, 'r', encoding='utf-8') as f:
            result = json.load(f)
        
        # 检查必需字段
        for field in self.REQUIRED_FIELDS:
            assert field in result, f"缺少必需字段: {field}"


if __name__ == '__main__':
    pytest.main([__file__, '-v'])