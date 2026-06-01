#!/usr/bin/env python3
"""
test_layered_backtest_overnight_ret_1d 测试用例

测试脚本: backtest/layered_backtest_overnight_ret_1d.py
因子计算: data_fetchers/factor_calculator.py::calculate_overnight_return
流程文档: backtest/docs/layered_backtest_overnight_ret_1d_flow.md
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import pytest
import json
import pandas as pd
import numpy as np
from typing import get_args, Literal

from backtest.layered_backtest_overnight_ret_1d import OvernightRetLayerConfig
from data_fetchers.factor_calculator import calculate_overnight_return


class TestOvernightRetLayerConfig:
    """配置类属性验证"""

    def test_factor_name_classvar(self):
        """TC001-01: factor_name 类属性"""
        assert OvernightRetLayerConfig.factor_name == 'overnight_ret'

    def test_layer_names_classvar(self):
        """TC001-02: layer_names 类属性为纯标签"""
        assert len(OvernightRetLayerConfig.layer_names) == 5
        assert OvernightRetLayerConfig.layer_names[0] == 'lowest'
        assert OvernightRetLayerConfig.layer_names[4] == 'highest'

    def test_layer_descriptions_classvar(self):
        """TC001-03: layer_descriptions 含中文描述"""
        assert len(OvernightRetLayerConfig.layer_descriptions) == 5
        assert OvernightRetLayerConfig.layer_descriptions[0] == '极低层(隔夜跌幅最大)'
        assert OvernightRetLayerConfig.layer_descriptions[4] == '极高层(隔夜涨幅最大)'

    def test_ic_source_default(self):
        """TC001-04: ic_source 默认路径"""
        config = OvernightRetLayerConfig()
        assert config.ic_source_resolved == 'factor_ic/result/ic_overnight_ret_1d_analysis_result.json'

    def test_ic_meta_direction_positive(self):
        """TC001-05: factor_direction = positive（从 IC 文件派生）"""
        config = OvernightRetLayerConfig()
        assert config.factor_direction == 'positive'

    def test_n_layers_derived(self):
        """TC001-06: n_layers 由 len(layer_names) 派生"""
        config = OvernightRetLayerConfig()
        assert config.n_layers == len(OvernightRetLayerConfig.layer_names)

    def test_layer_names_dict_generated(self):
        """TC001-07: layer_names_dict 使用 layer_descriptions"""
        config = OvernightRetLayerConfig()
        assert '1' in config.layer_names_dict
        assert '5' in config.layer_names_dict
        assert config.layer_names_dict['1'] == '极低层(隔夜跌幅最大)'
        assert config.layer_names_dict['5'] == '极高层(隔夜涨幅最大)'

    def test_layer_names_semantic(self):
        """TC001-08: layer_descriptions 语义描述"""
        for desc in OvernightRetLayerConfig.layer_descriptions:
            assert '跌' in desc or '涨' in desc or '变化' in desc

    def test_layer_names_no_fixed_threshold(self):
        """TC001-09: layer_names 纯标签无固定阈值"""
        for name in OvernightRetLayerConfig.layer_names:
            # 纯标签不含数字阈值
            assert not any(c.isdigit() for c in name)

    def test_factor_direction_literal_type(self):
        """TC001-10: factor_direction 类型约束"""
        valid_values = get_args(Literal['positive', 'negative'])
        config = OvernightRetLayerConfig()
        assert config.factor_direction in valid_values


class TestCalculateOvernightReturn:
    """测试因子计算函数"""
    
    def test_basic_calculation(self):
        """基本计算: overnight_ret = (open - close_prev) / close_prev"""
        # 需要 2 天数据：第一天无昨日收盘（NaN），第二天才有值
        df = pd.DataFrame({
            'date': ['2024-04-11', '2024-04-12'],
            'asset': ['000001', '000001'],
            'open': [10.0, 10.5],
            'close': [10.0, 10.2]
        })
        result = calculate_overnight_return(df)
        # 第一天应为 NaN（无昨日收盘）
        assert pd.isna(result['overnight_ret'].iloc[0])
        # 第二天: overnight_ret = (10.5 - 10.0) / 10.0 = 0.05
        assert result['overnight_ret'].iloc[1] == pytest.approx(0.05, rel=1e-3)
    
    def test_negative_return(self):
        """隔夜下跌: overnight_ret < 0"""
        # 需要 2 天数据
        df = pd.DataFrame({
            'date': ['2024-04-11', '2024-04-12'],
            'asset': ['000001', '000001'],
            'open': [10.0, 9.5],
            'close': [10.0, 10.0]
        })
        result = calculate_overnight_return(df)
        # 第一天应为 NaN
        assert pd.isna(result['overnight_ret'].iloc[0])
        # 第二天: overnight_ret = (9.5 - 10.0) / 10.0 = -0.05
        assert result['overnight_ret'].iloc[1] == pytest.approx(-0.05, rel=1e-3)
    
    def test_extreme_positive(self):
        """极端正值: 隔夜涨停（open ≈ close_prev * 1.1）"""
        # 需要 2 天数据
        df = pd.DataFrame({
            'date': ['2024-04-11', '2024-04-12'],
            'asset': ['000001', '000001'],
            'open': [10.0, 11.0],
            'close': [10.0, 11.0]
        })
        result = calculate_overnight_return(df)
        # 第一天应为 NaN
        assert pd.isna(result['overnight_ret'].iloc[0])
        # 第二天: overnight_ret = (11.0 - 10.0) / 10.0 = 0.1（涨停）
        assert result['overnight_ret'].iloc[1] == pytest.approx(0.1, rel=1e-3)
    
    def test_extreme_negative(self):
        """极端负值: 隔夜跌停（open ≈ close_prev * 0.9）"""
        # 需要 2 天数据
        df = pd.DataFrame({
            'date': ['2024-04-11', '2024-04-12'],
            'asset': ['000001', '000001'],
            'open': [10.0, 9.0],
            'close': [10.0, 9.0]
        })
        result = calculate_overnight_return(df)
        # 第一天应为 NaN
        assert pd.isna(result['overnight_ret'].iloc[0])
        # 第二天: overnight_ret = (9.0 - 10.0) / 10.0 = -0.1（跌停）
        assert result['overnight_ret'].iloc[1] == pytest.approx(-0.1, rel=1e-3)
    
    def test_required_columns(self):
        """缺少必要列时应抛出异常"""
        df = pd.DataFrame({
            'date': ['2024-04-12'],
            'asset': ['000001'],
            'open': [10.5]
            # 缺少 close 列
        })
        with pytest.raises((KeyError, ValueError)):
            calculate_overnight_return(df)
    
    def test_nan_handling(self):
        """NaN 值应保留或过滤"""
        df = pd.DataFrame({
            'date': ['2024-04-12', '2024-04-13'],
            'asset': ['000001', '000002'],
            'open': [10.5, np.nan],
            'close': [10.0, 11.0]
        })
        result = calculate_overnight_return(df)
        # NaN 应保留（不填充）
        assert pd.isna(result['overnight_ret'].iloc[1])

    def test_zero_prev_close(self):
        """边界值测试：昨日收盘=0 应返回 NaN（除零防护）"""
        # 需要 2 天数据，第一天收盘=0
        df = pd.DataFrame({
            'date': ['2024-04-11', '2024-04-12'],
            'asset': ['000001', '000001'],
            'open': [0.0, 10.5],
            'close': [0.0, 10.0]
        })
        result = calculate_overnight_return(df)
        # 第一天：昨日收盘=0，overnight_ret 应为 NaN（除零防护）
        assert pd.isna(result['overnight_ret'].iloc[0])
        # 第二天：昨日收盘=0.0，overnight_ret 应为 NaN（除零防护）
        assert pd.isna(result['overnight_ret'].iloc[1])


class TestLayeredBacktestResult:
    """测试分层回测结果"""
    
    @pytest.fixture
    def result_path(self):
        """获取回测结果文件路径"""
        return Path(__file__).parent.parent / 'result' / 'overnight_ret_layered_backtest.json'
    
    def test_result_file_exists(self, result_path):
        """结果文件应存在"""
        assert result_path.exists()
    
    def test_result_structure(self, result_path):
        """结果 JSON 结构应完整"""
        with open(result_path) as f:
            result = json.load(f)
        
        # 必须包含的顶层字段
        required_keys = ['meta', 'layer_stats', 'long_short', 'monotonicity']
        for key in required_keys:
            assert key in result
    
    def test_meta_fields(self, result_path):
        """meta 字段应包含完整信息"""
        with open(result_path) as f:
            result = json.load(f)
        
        meta = result['meta']
        assert 'factor_name' in meta
        assert meta['factor_name'] == 'overnight_ret'
        assert 'n_days_total' in meta
        assert meta['n_days_total'] > 0
        assert 'n_layers' in meta
        assert meta['n_layers'] == 5
    
    def test_layer_stats_complete(self, result_path):
        """每层统计指标应完整"""
        with open(result_path) as f:
            result = json.load(f)
        
        for layer_id in range(1, 6):
            layer_key = f'layer_{layer_id}'
            assert layer_key in result['layer_stats']
            
            stats = result['layer_stats'][layer_key]
            required_stats = ['n_stocks_avg', 'annual_return', 'sharpe_ratio', 'max_drawdown']
            for stat in required_stats:
                assert stat in stats
    
    def test_monotonicity_positive_factor(self, result_path):
        """正向因子单调性相关系数应为正"""
        with open(result_path) as f:
            result = json.load(f)
        
        monotonicity = result['monotonicity']
        # 正向因子：Layer1→5 收益应递增
        assert monotonicity['correlation'] > 0
        assert monotonicity['quality'] in ['excellent', 'good', 'fair', 'poor']


class TestLayeredBacktestExecution:
    """测试分层回测执行"""
    
    def test_config_integration(self):
        """配置类应能正确集成到 factor_cli_main"""
        config = OvernightRetLayerConfig()
        
        # 检查继承关系
        from backtest.common.layered_backtest_runner import LayerConfigBase
        assert isinstance(config, LayerConfigBase)
        
        # 检查必要属性
        assert hasattr(config, 'factor_direction')
        assert hasattr(config, 'layer_names')
    
    def test_factor_direction_derives_long_short(self):
        """正向因子应派生出正确的多空组合"""
        config = OvernightRetLayerConfig()
        
        # 正向因子：多头取高层，空头取低层
        # 这个测试依赖于基类的 _derive_long_short() 方法
        # 如果基类实现了自动派生，这里验证结果
        if hasattr(config, 'long_layers') and hasattr(config, 'short_layers'):
            # 正向因子：long_layers 应为高层（4, 5）
            assert config.long_layers in [[4, 5], [5], [4]]
            # 正向因子：short_layers 应为低层（1, 2）
            assert config.short_layers in [[1, 2], [1], [2]]


if __name__ == '__main__':
    pytest.main([__file__, '-v'])