#!/usr/bin/env python3
"""
尾盘量价强度因子 IC 计算器测试用例

测试覆盖：
- 因子计算逻辑（calculate_tail_price_volume_intensity）
- 边界处理（除零、数据不完整）
- 数据合并逻辑
"""

import pytest
import numpy as np
import pandas as pd
from pathlib import Path
import sys

# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from factor_ic.ic_tail_price_volume_intensity import (
    calculate_tail_price_volume_intensity,
    load_tail_trading_data,
    EPSILON
)


class TestCalculateTailPriceVolumeIntensity:
    """因子计算函数测试"""
    
    def test_normal_calculation(self):
        """正常计算场景"""
        # 构造测试数据
        factor_df = pd.DataFrame({
            'date': ['2026-06-01', '2026-06-01'],
            'asset': ['000001', '000002'],
            'volume': [1000000, 2000000]  # 全天成交量
        })
        
        # Mock 尾盘数据
        mock_tail_df = pd.DataFrame({
            'date': ['2026-06-01', '2026-06-01'],
            'asset': ['000001', '000002'],
            'prices': [[10.0, 10.1, 10.2, 10.3, 10.4, 10.5, 10.6, 10.7, 10.8, 10.9, 11.0, 11.0, 11.0],
                       [20.0, 20.1, 20.2, 20.3, 20.4, 20.5, 20.6, 20.7, 20.8, 20.9, 21.0, 21.0, 21.0]],
            'volumes': [[10000, 10000, 10000, 10000, 10000, 10000, 10000, 10000, 10000, 10000, 10000, 10000, 10000],
                        [20000, 20000, 20000, 20000, 20000, 20000, 20000, 20000, 20000, 20000, 20000, 20000, 20000]]
        })
        
        # 临时替换尾盘数据路径
        import factor_ic.ic_tail_price_volume_intensity as module
        original_path = module.TAIL_TRADING_DATA_PATH
        
        # 写入临时文件
        import gzip
        import json
        import tempfile
        with tempfile.NamedTemporaryFile(suffix='.json.gz', delete=False) as f:
            temp_path = Path(f.name)
            with gzip.open(temp_path, 'wt', encoding='utf-8') as gz:
                json.dump({'data': mock_tail_df.to_dict('records')}, gz)
        
        module.TAIL_TRADING_DATA_PATH = temp_path
        
        try:
            result_df = calculate_tail_price_volume_intensity(factor_df)
            
            # 验证结果
            assert 'tail_price_volume_intensity' in result_df.columns
            assert result_df['tail_price_volume_intensity'].notna().sum() == 2
            
            # 验证计算逻辑
            # asset 000001: 尾盘涨跌幅 = (11.0 - 10.0) / 10.0 = 0.1
            # 尾盘量比 = 130000 / 1000000 = 0.13
            # 尾盘量价强度 = 0.1 * 0.13 = 0.013
            expected_000001 = 0.1 * 0.13
            assert abs(result_df.loc[result_df['asset'] == '000001', 'tail_price_volume_intensity'].values[0] - expected_000001) < 0.001
            
        finally:
            module.TAIL_TRADING_DATA_PATH = original_path
            temp_path.unlink()
    
    def test_zero_price_protection(self):
        """除零防护：prices[0] 接近零"""
        factor_df = pd.DataFrame({
            'date': ['2026-06-01'],
            'asset': ['000001'],
            'volume': [1000000]
        })
        
        mock_tail_df = pd.DataFrame({
            'date': ['2026-06-01'],
            'asset': ['000001'],
            'prices': [[0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0, 1.0, 1.0]],
            'volumes': [[10000] * 13]
        })
        
        import factor_ic.ic_tail_price_volume_intensity as module
        original_path = module.TAIL_TRADING_DATA_PATH
        
        import gzip
        import json
        import tempfile
        with tempfile.NamedTemporaryFile(suffix='.json.gz', delete=False) as f:
            temp_path = Path(f.name)
            with gzip.open(temp_path, 'wt', encoding='utf-8') as gz:
                json.dump({'data': mock_tail_df.to_dict('records')}, gz)
        
        module.TAIL_TRADING_DATA_PATH = temp_path
        
        try:
            result_df = calculate_tail_price_volume_intensity(factor_df)
            
            # prices[0] = 0 时应返回 NaN
            assert pd.isna(result_df['tail_price_volume_intensity'].values[0])
            
        finally:
            module.TAIL_TRADING_DATA_PATH = original_path
            temp_path.unlink()
    
    def test_zero_volume_protection(self):
        """除零防护：volume 接近零"""
        factor_df = pd.DataFrame({
            'date': ['2026-06-01'],
            'asset': ['000001'],
            'volume': [0]  # 全天成交量为零
        })
        
        mock_tail_df = pd.DataFrame({
            'date': ['2026-06-01'],
            'asset': ['000001'],
            'prices': [[10.0] * 13],
            'volumes': [[10000] * 13]
        })
        
        import factor_ic.ic_tail_price_volume_intensity as module
        original_path = module.TAIL_TRADING_DATA_PATH
        
        import gzip
        import json
        import tempfile
        with tempfile.NamedTemporaryFile(suffix='.json.gz', delete=False) as f:
            temp_path = Path(f.name)
            with gzip.open(temp_path, 'wt', encoding='utf-8') as gz:
                json.dump({'data': mock_tail_df.to_dict('records')}, gz)
        
        module.TAIL_TRADING_DATA_PATH = temp_path
        
        try:
            result_df = calculate_tail_price_volume_intensity(factor_df)
            
            # volume = 0 时应返回 NaN
            assert pd.isna(result_df['tail_price_volume_intensity'].values[0])
            
        finally:
            module.TAIL_TRADING_DATA_PATH = original_path
            temp_path.unlink()
    
    def test_incomplete_data_protection(self):
        """数据不完整防护：volumes 数组长度不足"""
        factor_df = pd.DataFrame({
            'date': ['2026-06-01'],
            'asset': ['000001'],
            'volume': [1000000]
        })
        
        mock_tail_df = pd.DataFrame({
            'date': ['2026-06-01'],
            'asset': ['000001'],
            'prices': [[10.0, 10.1]],  # 只有2个元素
            'volumes': [[10000, 10000]]
        })
        
        import factor_ic.ic_tail_price_volume_intensity as module
        original_path = module.TAIL_TRADING_DATA_PATH
        
        import gzip
        import json
        import tempfile
        with tempfile.NamedTemporaryFile(suffix='.json.gz', delete=False) as f:
            temp_path = Path(f.name)
            with gzip.open(temp_path, 'wt', encoding='utf-8') as gz:
                json.dump({'data': mock_tail_df.to_dict('records')}, gz)
        
        module.TAIL_TRADING_DATA_PATH = temp_path
        
        try:
            result_df = calculate_tail_price_volume_intensity(factor_df)
            
            # 数据不完整时应返回 NaN
            assert pd.isna(result_df['tail_price_volume_intensity'].values[0])
            
        finally:
            module.TAIL_TRADING_DATA_PATH = original_path
            temp_path.unlink()


class TestLoadTailTradingData:
    """数据加载测试"""
    
    def test_file_not_found(self):
        """文件不存在时抛出异常"""
        import factor_ic.ic_tail_price_volume_intensity as module
        original_path = module.TAIL_TRADING_DATA_PATH
        module.TAIL_TRADING_DATA_PATH = Path('/nonexistent/path.json.gz')
        
        try:
            with pytest.raises(FileNotFoundError):
                load_tail_trading_data()
        finally:
            module.TAIL_TRADING_DATA_PATH = original_path