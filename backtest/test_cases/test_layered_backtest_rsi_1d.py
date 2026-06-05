#!/usr/bin/env python3
"""
test_layered_backtest_rsi_1d 测试用例

测试脚本: backtest/layered_backtest_rsi_1d.py
因子计算: calculate_rsi_df
流程文档: backtest/docs/layered_backtest_rsi_1d_flow.md
"""

import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import json
from typing import Literal, get_args

import pytest

from backtest.layered_backtest_rsi_1d import RsiLayerConfig


class TestRsiLayerConfig:
    """配置类属性验证"""

    def test_factor_name_classvar(self):
        """TC001-01: factor_name 类属性"""
        assert RsiLayerConfig.factor_name == 'rsi'

    def test_layer_names_classvar(self):
        """TC001-02: layer_names 类属性为纯标签"""
        assert len(RsiLayerConfig.layer_names) == 4
        assert RsiLayerConfig.layer_names[0] == 'oversold'
        assert RsiLayerConfig.layer_names[1] == 'low'
        assert RsiLayerConfig.layer_names[2] == 'normal'
        assert RsiLayerConfig.layer_names[3] == 'high'

    def test_layer_descriptions_classvar(self):
        """TC001-03: layer_descriptions 含中文描述"""
        assert len(RsiLayerConfig.layer_descriptions) == 4
        assert RsiLayerConfig.layer_descriptions[0] == '超卖层(RSI<30)'
        assert RsiLayerConfig.layer_descriptions[1] == '偏低层(RSI 30-40)'
        assert RsiLayerConfig.layer_descriptions[2] == '中性层(RSI 40-60)'
        assert RsiLayerConfig.layer_descriptions[3] == '偏高层(RSI 60-70)'

    def test_ic_source_default(self):
        """TC001-04: ic_source 默认路径"""
        config = RsiLayerConfig()
        assert config.ic_source_resolved == 'factor_ic/result/ic_rsi_1d_analysis_result.json'

    def test_ic_meta_direction_negative(self):
        """TC001-05: factor_direction = negative（从 IC 文件派生）"""
        config = RsiLayerConfig()
        # ic_mean < 0 时 direction = negative
        assert config.factor_direction == 'negative'

    def test_n_layers_derived(self):
        """TC001-06: n_layers 由 len(layer_names) 派生"""
        config = RsiLayerConfig()
        assert config.n_layers == len(RsiLayerConfig.layer_names)
        assert config.n_layers == 4

    def test_layer_names_dict_generated(self):
        """TC001-07: layer_names_dict 使用 layer_descriptions"""
        config = RsiLayerConfig()
        assert '1' in config.layer_names_dict
        assert '4' in config.layer_names_dict
        assert config.layer_names_dict['1'] == '超卖层(RSI<30)'
        assert config.layer_names_dict['4'] == '偏高层(RSI 60-70)'

    def test_layer_names_semantic(self):
        """TC001-08: layer_descriptions 语义描述"""
        config = RsiLayerConfig()
        # layer_descriptions 应包含"RSI"相关描述
        for desc in config.__class__.layer_descriptions:
            assert 'RSI' in desc or 'rsi' in desc.lower()

    def test_layer_names_no_fixed_threshold(self):
        """TC001-09: layer_names 纯标签无固定阈值"""
        for name in RsiLayerConfig.layer_names:
            # 纯标签不含数字阈值
            assert not any(c.isdigit() for c in name)

    def test_factor_direction_negative(self):
        """TC001-10: factor_direction = negative"""
        config = RsiLayerConfig()
        assert config.factor_direction == 'negative'

    def test_factor_direction_literal_type(self):
        """TC001-11: factor_direction 类型约束"""
        valid_values = get_args(Literal['positive', 'negative'])
        config = RsiLayerConfig()
        assert config.factor_direction in valid_values

    def test_long_short_derived(self):
        """TC001-12: long_layers/short_layers 由 factor_direction 派生"""
        config = RsiLayerConfig()
        # 反向因子：多头取低层，空头取高层
        assert config.long_layers is not None
        assert config.short_layers is not None
        assert 1 in config.long_layers  # 低层做多
        assert 4 in config.short_layers  # 高层做空


class TestRsiCalculator:
    """因子计算器验证"""

    def test_factor_calculator_exists(self):
        """TC002-01: 因子计算器存在"""
        from data_fetchers.factor_calculator import calculate_rsi_df
        assert callable(calculate_rsi_df)


class TestLayeredBacktestResult:
    """回测结果验证"""

    def test_result_file_exists(self):
        """TC003-01: 结果文件存在"""
        result_path = Path('backtest/result/rsi_layered_backtest.json')
        if not result_path.exists():
            pytest.skip("结果文件不存在，需先运行脚本")

    def test_result_structure(self):
        """TC003-02: 结果结构完整"""
        result_path = Path('backtest/result/rsi_layered_backtest.json')
        if not result_path.exists():
            pytest.skip("结果文件不存在")

        result = json.load(open(result_path))
        required_keys = ['meta', 'layer_stats', 'monotonicity', 'long_short']
        for k in required_keys:
            assert k in result

    def test_meta_fields(self):
        """TC003-03: meta 字段"""
        result_path = Path('backtest/result/rsi_layered_backtest.json')
        if not result_path.exists():
            pytest.skip("结果文件不存在")

        result = json.load(open(result_path))
        meta = result['meta']
        assert meta['factor_name'] == 'rsi'
        assert meta['factor_direction'] == 'negative'
        assert meta['n_layers'] == 4

    def test_layer_stats_complete(self):
        """TC003-04: layer_stats 完整"""
        result_path = Path('backtest/result/rsi_layered_backtest.json')
        if not result_path.exists():
            pytest.skip("结果文件不存在")

        result = json.load(open(result_path))
        assert len(result['layer_stats']) == 4  # 4层


class TestLayeredBacktestExecution:
    """执行集成验证"""

    def test_config_integration(self):
        """TC004-01: 配置类可实例化"""
        config = RsiLayerConfig()
        assert config.n_layers == 4
        assert config.factor_direction == 'negative'

    def test_factor_direction_derives_long_short(self):
        """TC004-02: factor_direction 决定多空组合"""
        config = RsiLayerConfig()
        # 反向因子：低值层做多，高值层做空
        assert config.factor_direction == 'negative'
        assert config.long_layers is not None
        assert config.short_layers is not None
        assert 1 in config.long_layers
        assert 4 in config.short_layers


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
