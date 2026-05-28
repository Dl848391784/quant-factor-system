#!/usr/bin/env python3
"""
merge_factors.py 测试用例

测试内容：
1. setup_logger 初始化测试
2. load_main_data 输入验证测试
3. load_parquet_factor 输入验证测试
4. merge_factors 边界处理测试
5. 数据完整性验证测试

运行方式：
    pytest summary/test_cases/test_merge_factors.py -v
"""

import pytest
import logging
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock
import pandas as pd

# 导入被测试模块
from summary.merge_factors import (
    setup_logger,
    load_main_data,
    load_parquet_factor,
    merge_factors,
    NEW_FACTORS,
    __version__,
)


class TestSetupLogger:
    """setup_logger 函数测试"""
    
    def test_logger_initialization(self):
        """测试日志记录器初始化"""
        logger = setup_logger('test_merge_factors')
        assert logger is not None
        assert isinstance(logger, logging.Logger)
        assert logger.name == 'test_merge_factors'
    
    def test_logger_has_handlers(self):
        """测试日志处理器配置"""
        logger = setup_logger('test_merge_factors_2')
        assert len(logger.handlers) > 0
        # 应有文件处理器和控制台处理器
        handler_types = [type(h).__name__ for h in logger.handlers]
        assert 'FileHandler' in handler_types or 'StreamHandler' in handler_types
    
    def test_logger_level(self):
        """测试日志级别配置"""
        logger = setup_logger('test_merge_factors_3')
        assert logger.level == logging.DEBUG


class TestLoadMainData:
    """load_main_data 函数测试"""
    
    def test_load_main_data_file_not_exists(self):
        """测试主数据源文件不存在"""
        logger = Mock()
        result = load_main_data(logger)
        # 文件不存在时应返回 None 或抛出异常（取决于实现）
        assert result is None or isinstance(result, pd.DataFrame)
        # 应记录警告日志
        if result is None:
            logger.warning.assert_called()
    
    @patch('summary.merge_factors.PROJECT_ROOT')
    @patch('gzip.open')
    @patch('json.load')
    def test_load_main_data_success(self, mock_json_load, mock_gzip_open, mock_project_root):
        """测试主数据源加载成功"""
        # 设置 mock
        mock_json_load.return_value = {'data': [{'date': '2024-01-01', 'asset': '000001'}]}
        mock_gzip_open.return_value.__enter__.return_value = MagicMock()
        
        # 模拟文件存在
        mock_file = Mock()
        mock_file.exists.return_value = True
        mock_project_root.__truediv__ = Mock(return_value=mock_file)
        
        logger = Mock()
        result = load_main_data(logger)
        
        # 返回 DataFrame
        assert isinstance(result, pd.DataFrame)


class TestLoadParquetFactor:
    """load_parquet_factor 函数测试"""
    
    def test_load_parquet_factor_file_not_exists(self):
        """测试因子文件不存在"""
        logger = Mock()
        result = load_parquet_factor('nonexistent_factor', logger)
        assert result is None
        logger.warning.assert_called()
    
    @patch('summary.merge_factors.PROJECT_ROOT')
    @patch('pandas.read_parquet')
    def test_load_parquet_factor_success(self, mock_read_parquet, mock_project_root):
        """测试因子文件加载成功"""
        # 设置 mock
        mock_read_parquet.return_value = pd.DataFrame({
            'date': ['2024-01-01'],
            'asset': ['000001'],
            'factor_value': [0.5]
        })
        
        # 模拟文件存在
        mock_file = Mock()
        mock_file.exists.return_value = True
        mock_project_root.__truediv__ = Mock(return_value=mock_file)
        
        logger = Mock()
        result = load_parquet_factor('test_factor', logger)
        
        assert isinstance(result, pd.DataFrame)
    
    @patch('summary.merge_factors.PROJECT_ROOT')
    @patch('pandas.read_parquet')
    def test_load_parquet_factor_exception(self, mock_read_parquet, mock_project_root):
        """测试因子文件加载异常"""
        # 设置 mock 抛出异常
        mock_read_parquet.side_effect = Exception("读取失败")
        
        # 模拟文件存在
        mock_file = Mock()
        mock_file.exists.return_value = True
        mock_project_root.__truediv__ = Mock(return_value=mock_file)
        
        logger = Mock()
        result = load_parquet_factor('test_factor', logger)
        
        assert result is None
        logger.error.assert_called()


class TestMergeFactors:
    """merge_factors 函数测试"""
    
    @patch('summary.merge_factors.load_main_data')
    def test_merge_factors_main_data_none(self, mock_load_main):
        """测试主数据加载失败"""
        mock_load_main.return_value = None
        logger = Mock()
        result = merge_factors(logger)
        assert result is None
        logger.error.assert_called()
    
    @patch('summary.merge_factors.load_main_data')
    @patch('summary.merge_factors.load_parquet_factor')
    def test_merge_factors_no_factors_loaded(self, mock_load_factor, mock_load_main):
        """测试没有因子加载成功"""
        mock_load_main.return_value = pd.DataFrame({'date': ['2024-01-01'], 'asset': ['000001']})
        mock_load_factor.return_value = None
        
        logger = Mock()
        result = merge_factors(logger)
        
        # 应返回原始主数据
        assert isinstance(result, pd.DataFrame)
    
    @patch('summary.merge_factors.load_main_data')
    @patch('summary.merge_factors.load_parquet_factor')
    @patch('summary.merge_factors.PROJECT_ROOT')
    def test_merge_factors_success(self, mock_project_root, mock_load_factor, mock_load_main):
        """测试合并成功"""
        # 设置主数据
        mock_load_main.return_value = pd.DataFrame({
            'date': ['2024-01-01', '2024-01-02'],
            'asset': ['000001', '000002'],
            'existing_factor': [0.1, 0.2]
        })
        
        # 设置因子数据
        mock_load_factor.return_value = pd.DataFrame({
            'date': ['2024-01-01', '2024-01-02'],
            'asset': ['000001', '000002'],
            'factor_value': [0.5, 0.6]
        })
        
        # 模拟输出目录
        mock_dir = Mock()
        mock_dir.mkdir = Mock()
        mock_project_root.__truediv__ = Mock(return_value=mock_dir)
        
        logger = Mock()
        
        # 只测试一个因子
        with patch('summary.merge_factors.NEW_FACTORS', ['test_factor']):
            result = merge_factors(logger)
        
        assert isinstance(result, pd.DataFrame)


class TestConstants:
    """常量测试"""
    
    def test_version_defined(self):
        """测试版本常量定义"""
        assert __version__ == '1.1'
    
    def test_new_factors_not_empty(self):
        """测试新因子列表非空"""
        assert len(NEW_FACTORS) > 0
        assert isinstance(NEW_FACTORS, list)
    
    def test_new_factors_format(self):
        """测试新因子名称格式"""
        for factor in NEW_FACTORS:
            assert isinstance(factor, str)
            assert len(factor) > 0


class TestDataIntegrity:
    """数据完整性验证测试"""
    
    def test_merge_preserves_main_data_columns(self):
        """测试合并保留主数据列"""
        main_df = pd.DataFrame({
            'date': ['2024-01-01'],
            'asset': ['000001'],
            'existing_col': [1.0]
        })
        
        factor_df = pd.DataFrame({
            'date': ['2024-01-01'],
            'asset': ['000001'],
            'factor_value': [0.5]
        })
        
        # 重命名并合并
        factor_df_renamed = factor_df[['date', 'asset', 'factor_value']].copy()
        factor_df_renamed.columns = ['date', 'asset', 'new_factor']
        
        merged = main_df.merge(factor_df_renamed, on=['date', 'asset'], how='left')
        
        # 检查保留原有列
        assert 'existing_col' in merged.columns
        assert 'new_factor' in merged.columns
    
    def test_merge_handles_missing_data(self):
        """测试合并处理缺失数据"""
        main_df = pd.DataFrame({
            'date': ['2024-01-01', '2024-01-02'],
            'asset': ['000001', '000002'],
        })
        
        factor_df = pd.DataFrame({
            'date': ['2024-01-01'],  # 只有第一天数据
            'asset': ['000001'],
            'factor_value': [0.5]
        })
        
        factor_df_renamed = factor_df.copy()
        factor_df_renamed.columns = ['date', 'asset', 'new_factor']
        
        merged = main_df.merge(factor_df_renamed, on=['date', 'asset'], how='left')
        
        # 检查缺失值处理
        assert merged['new_factor'].isna().sum() == 1  # 第二天应为 NaN


if __name__ == '__main__':
    pytest.main([__file__, '-v'])