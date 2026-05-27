#!/usr/bin/env python3
"""
DataFrame 工具模块测试用例

测试 validate_dataframe_columns 函数的各种场景。

作者: 云瑶
创建日期: 2026-05-27
版本历史:
- v1.0 (2026-05-27): 首次创建，覆盖正常/异常/边界场景
- v1.1 (2026-05-27): 导入顺序PEP8规范化，测试日志命名合规化
"""

# 标准库导入
import logging

# 第三方库导入
import pytest
import pandas as pd

# 本地模块导入
from data_fetchers.common.dataframe_utils import validate_dataframe_columns


class TestValidateDataframeColumns:
    """validate_dataframe_columns 函数测试类"""
    
    def test_normal_case_all_columns_present(self):
        """TC001: 正常场景 - 所有必需列存在"""
        df = pd.DataFrame({
            'date': ['2024-01-01', '2024-01-02'],
            'close': [100.0, 101.0],
            'volume': [1000, 1100]
        })
        # 不应抛出异常
        validate_dataframe_columns(df, ['date', 'close', 'volume'], 'stock_data')
    
    def test_missing_columns_error_message(self):
        """TC002: 异常场景 - 缺少必需列，错误信息包含可用列"""
        df = pd.DataFrame({
            'date': ['2024-01-01'],
            'close': [100.0]
        })
        
        with pytest.raises(ValueError) as exc_info:
            validate_dataframe_columns(df, ['date', 'close', 'volume'], 'stock_data')
        
        error_msg = str(exc_info.value)
        # 验证错误信息包含缺失列和可用列
        assert "缺少必需列" in error_msg
        assert "volume" in error_msg
        assert "可用列" in error_msg
        assert "date" in error_msg
        assert "close" in error_msg
    
    def test_df_none_raises_type_error(self):
        """TC003: 边界场景 - df 参数为 None"""
        with pytest.raises(TypeError) as exc_info:
            validate_dataframe_columns(None, ['date', 'close'], 'stock_data')
        
        assert "不能为 None" in str(exc_info.value)
    
    def test_empty_required_cols_raises_value_error(self):
        """TC004: 边界场景 - required_cols 为空列表"""
        df = pd.DataFrame({'date': ['2024-01-01']})
        
        with pytest.raises(ValueError) as exc_info:
            validate_dataframe_columns(df, [], 'stock_data')
        
        assert "不能为空列表" in str(exc_info.value)
    
    def test_with_custom_logger(self):
        """TC005: 日志参数化 - 自定义 logger"""
        df = pd.DataFrame({'date': ['2024-01-01'], 'close': [100.0]})
        
        # 创建测试 logger（使用真实模块名，遵循 PROJECT.md 日志规范）
        test_logger = logging.getLogger('data_fetchers.common.dataframe_utils')
        
        # 不应抛出异常
        validate_dataframe_columns(df, ['date', 'close'], 'stock_data', logger=test_logger)
    
    def test_partial_columns_missing(self):
        """TC006: 部分缺失 - 多个必需列中部分缺失"""
        df = pd.DataFrame({
            'date': ['2024-01-01'],
            'close': [100.0]
        })
        
        with pytest.raises(ValueError) as exc_info:
            validate_dataframe_columns(df, ['date', 'close', 'volume', 'high'], 'stock_data')
        
        error_msg = str(exc_info.value)
        # 验证多个缺失列都出现在错误信息中
        assert "volume" in error_msg
        assert "high" in error_msg
    
    def test_empty_dataframe_with_columns(self):
        """TC007: 空DataFrame - 有列定义但无数据行"""
        df = pd.DataFrame(columns=['date', 'close'])  # 空数据但有列定义
        
        # 列名校验只检查列名是否存在，不检查数据行数
        validate_dataframe_columns(df, ['date', 'close'], 'empty_data')
    
    def test_extra_columns_not_required(self):
        """TC008: 多余列 - DataFrame 有非必需列，不影响校验"""
        df = pd.DataFrame({
            'date': ['2024-01-01'],
            'close': [100.0],
            'extra_col': ['extra_value']  # 非必需列
        })
        
        # 多余列不影响校验
        validate_dataframe_columns(df, ['date', 'close'], 'stock_data')


if __name__ == '__main__':
    pytest.main([__file__, '-v'])