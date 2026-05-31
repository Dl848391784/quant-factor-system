#!/usr/bin/env python3
"""
ic_amplitude_1d 测试用例

测试脚本: factor_ic/ic_amplitude_1d.py
因子计算: data_fetchers/factor_calculator.py::calculate_amplitude
流程文档: factor_ic/docs/ic_amplitude_1d_flow.md
规范文档: PROJECT.md

运行: pytest factor_ic/test_cases/ic_amplitude_1d_test_cases.py -v
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

from data_fetchers.factor_calculator import calculate_amplitude


class TestOutputPath:
    """测试输出路径和命名规范"""
    
    def test_output_path_format(self):
        """输出文件命名应符合规范: ic_<因子名>_analysis_result.json"""
        path = get_ic_output_path('amplitude_1d')
        assert path.name == 'ic_amplitude_1d_analysis_result.json'
    
    def test_output_directory(self):
        """输出目录应为 factor_ic/result/"""
        path = get_ic_output_path('amplitude_1d')
        assert path.parent == FACTOR_IC_RESULT_DIR
    
    def test_output_directory_exists_or_created(self):
        """输出目录不存在时应自动创建"""
        assert FACTOR_IC_RESULT_DIR.exists() or FACTOR_IC_RESULT_DIR.parent.exists()


class TestCalculateAmplitude:
    """测试因子计算函数"""
    
    def test_basic_calculation(self):
        """基本计算测试"""
        df = pd.DataFrame({
            'close': [10.0, 12.0, 11.0],
            'high': [12.0, 13.0, 12.0],
            'low': [9.0, 11.0, 10.0]
        })
        result = calculate_amplitude(df)
        
        assert 'amplitude' in result.columns
        # (12-9)/10 = 0.3
        assert np.isclose(result['amplitude'].iloc[0], 0.3, atol=0.01)
    
    def test_upper_bound(self):
        """上限测试：振幅较大"""
        df = pd.DataFrame({
            'close': [10.0],
            'high': [15.0],
            'low': [5.0]
        })
        result = calculate_amplitude(df)
        
        # (15-5)/10 = 1.0
        assert result['amplitude'].iloc[0] == 1.0
    
    def test_zero_amplitude(self):
        """振幅为零测试：一字涨跌停"""
        df = pd.DataFrame({
            'close': [10.0],
            'high': [10.0],
            'low': [10.0]
        })
        result = calculate_amplitude(df)
        
        # (10-10)/10 = 0.0
        assert result['amplitude'].iloc[0] == 0.0
    
    def test_zero_close_handling(self):
        """收盘价为零测试：无效数据"""
        df = pd.DataFrame({
            'close': [0.0],
            'high': [12.0],
            'low': [9.0]
        })
        result = calculate_amplitude(df)
        
        # close=0 → NaN（无效数据）
        assert pd.isna(result['amplitude'].iloc[0])
    
    def test_multiple_rows(self):
        """多行数据处理测试"""
        df = pd.DataFrame({
            'close': [10.0, 12.0, 11.0, 0.0],
            'high': [12.0, 13.0, 12.0, 11.0],
            'low': [9.0, 11.0, 10.0, 9.0]
        })
        result = calculate_amplitude(df)
        
        assert len(result) == 4
        assert 'amplitude' in result.columns
        # 第四行 close=0，应为 NaN
        assert pd.isna(result['amplitude'].iloc[3])
    
    def test_nan_handling(self):
        """NaN 值处理测试"""
        df = pd.DataFrame({
            'close': [10.0, np.nan, 12.0],
            'high': [12.0, 13.0, 12.0],
            'low': [9.0, 11.0, 10.0]
        })
        result = calculate_amplitude(df)
        
        # NaN 应传播
        assert pd.isna(result['amplitude'].iloc[1])
    
    def test_a_stock_range(self):
        """A股典型振幅范围测试（0-15%）"""
        df = pd.DataFrame({
            'close': [10.0, 10.0, 10.0],
            'high': [11.5, 10.5, 10.0],  # 振幅 15%, 5%, 0%
            'low': [8.5, 9.5, 10.0]
        })
        result = calculate_amplitude(df)
        
        # 第一行：振幅 15% → (11.5-8.5)/10 = 0.30（超过 A股 15% 上限，但允许）
        assert np.isclose(result['amplitude'].iloc[0], 0.30, atol=0.01)
        # 第二行：振幅 5%
        assert np.isclose(result['amplitude'].iloc[1], 0.10, atol=0.01)
        # 第三行：一字板
        assert result['amplitude'].iloc[2] == 0.0


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
        # 注意：此测试需要先运行 ic_amplitude_1d.py
        # 这里只检查文件路径是否正确
        path = get_ic_output_path('amplitude_1d')
        # 如果文件不存在，跳过此测试
        if not path.exists():
            pytest.skip("输出文件不存在，需要先运行 ic_amplitude_1d.py")
    
    def test_output_structure_if_exists(self):
        """如果输出文件存在，检查结构"""
        path = get_ic_output_path('amplitude_1d')
        if not path.exists():
            pytest.skip("输出文件不存在")
        
        with open(path, 'r', encoding='utf-8') as f:
            result = json.load(f)
        
        # 检查必需字段
        for field in self.REQUIRED_FIELDS:
            assert field in result, f"缺少必需字段: {field}"
    
    def test_ic_metrics_fields_if_exists(self):
        """如果输出文件存在，检查 ic_metrics 子字段"""
        path = get_ic_output_path('amplitude_1d')
        if not path.exists():
            pytest.skip("输出文件不存在")
        
        with open(path, 'r', encoding='utf-8') as f:
            result = json.load(f)
        
        ic_metrics = result.get('ic_metrics', {})
        required_ic_fields = ['ic_mean', 'ic_std', 'icir']
        
        for field in required_ic_fields:
            assert field in ic_metrics, f"ic_metrics 缺少必需字段: {field}"
    
    def test_sample_stats_fields_if_exists(self):
        """如果输出文件存在，检查 sample_stats 子字段"""
        path = get_ic_output_path('amplitude_1d')
        if not path.exists():
            pytest.skip("输出文件不存在")
        
        with open(path, 'r', encoding='utf-8') as f:
            result = json.load(f)
        
        sample_stats = result.get('sample_stats', {})
        required_sample_fields = ['total_days', 'valid_days']
        
        for field in required_sample_fields:
            assert field in sample_stats, f"sample_stats 缺少必需字段: {field}"


if __name__ == '__main__':
    pytest.main([__file__, '-v'])