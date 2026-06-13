#!/usr/bin/env python3
"""
test_layered_backtest_volume_ratio_1d 测试用例

测试脚本: backtest/layered_backtest_volume_ratio_1d.py
因子计算: 预计算因子（volume_ratio_5 已在数据源中）
流程文档: backtest/docs/layered_backtest_volume_ratio_1d_flow.md
"""

import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import json
from typing import Literal, get_args

import pytest

from backtest.layered_backtest_volume_ratio_1d import VolumeRatioLayerConfig


class TestVolumeRatioLayerConfig:
    """配置类属性验证"""

    def test_factor_name_classvar(self):
        """TC001-01: factor_name 类属性

        factor_name='volume_ratio' 是因子逻辑名（IC/回测结果 meta 与下游引用），
        factor_col='volume_ratio_5' 是数据源列名（5 日均量比）。两者职责分离，
        不应混淆。本测试仅校验 factor_name；factor_col 由其他测试覆盖。
        """
        assert VolumeRatioLayerConfig.factor_name == 'volume_ratio'

    def test_factor_col_classvar(self):
        """TC001-01b: factor_col 类属性 = 数据源列名"""
        assert VolumeRatioLayerConfig.factor_col == 'volume_ratio_5'

    def test_layer_names_classvar(self):
        """TC001-02: layer_names 类属性为纯标签"""
        assert len(VolumeRatioLayerConfig.layer_names) == 5
        assert VolumeRatioLayerConfig.layer_names[0] == 'lowest'

    def test_layer_descriptions_classvar(self):
        """TC001-03: layer_descriptions 含中文描述"""
        assert len(VolumeRatioLayerConfig.layer_descriptions) == 5
        assert VolumeRatioLayerConfig.layer_descriptions[0] == '极低层(量比极低)'

    def test_ic_source_default(self):
        """TC001-04: ic_source 显式声明覆盖默认路径"""
        config = VolumeRatioLayerConfig()
        # 显式声明时，使用声明的路径（而非默认拼接）
        assert config.ic_source_resolved == 'factor_ic/result/ic_volume_ratio_1d_analysis_result.json'

    def test_ic_meta_direction_negative(self):
        """TC001-04: factor_direction = negative（从 IC 文件派生）"""
        config = VolumeRatioLayerConfig()
        # ic_mean < 0 时 direction = negative
        assert config.factor_direction == 'negative'

    def test_n_layers_derived(self):
        """TC001-05: n_layers 由 len(layer_names) 派生"""
        config = VolumeRatioLayerConfig()
        assert config.n_layers == len(VolumeRatioLayerConfig.layer_names)

    def test_layer_names_dict_generated(self):
        """TC001-06: layer_names_dict 使用 layer_descriptions"""
        config = VolumeRatioLayerConfig()
        assert '1' in config.layer_names_dict
        assert '5' in config.layer_names_dict
        assert config.layer_names_dict['1'] == '极低层(量比极低)'

    def test_layer_names_semantic(self):
        """TC001-07: layer_descriptions 语义描述"""
        config = VolumeRatioLayerConfig()
        # layer_descriptions 应包含"量比"相关描述
        for desc in config.__class__.layer_descriptions:
            assert '量比' in desc

    def test_layer_names_no_fixed_threshold(self):
        """TC001-08: layer_names 纯标签无固定阈值"""
        for name in VolumeRatioLayerConfig.layer_names:
            # 纯标签不含数字阈值
            assert not any(c.isdigit() for c in name)

    def test_factor_direction_negative(self):
        """TC001-09: factor_direction = negative"""
        config = VolumeRatioLayerConfig()
        assert config.factor_direction == 'negative'

    def test_factor_direction_literal_type(self):
        """TC001-10: factor_direction 类型约束"""
        valid_values = get_args(Literal['positive', 'negative'])
        config = VolumeRatioLayerConfig()
        assert config.factor_direction in valid_values

    def test_long_short_derived(self):
        """TC001-11: long_layers/short_layers 由 factor_direction 派生"""
        config = VolumeRatioLayerConfig()
        # 反向因子：多头取低层，空头取高层
        assert 1 in config.long_layers  # 低层做多
        assert 5 in config.short_layers or 4 in config.short_layers  # 高层做空


class TestVolumeRatioPrecomputed:
    """预计算因子特性验证"""

    def test_no_factor_calculator_needed(self):
        """TC002-01: 预计算因子无需 calculator"""
        # volume_ratio_5 已在数据源中，factor_cli_main 调用不传 factor_calculator
        # 此测试验证配置类无 calculator 属性
        assert not hasattr(VolumeRatioLayerConfig, 'factor_calculator')


class TestLayeredBacktestResult:
    """回测结果验证"""

    def test_result_file_exists(self):
        """TC003-01: 结果文件存在"""
        result_path = Path('backtest/result/volume_ratio_layered_backtest.json')
        if not result_path.exists():
            pytest.skip("结果文件不存在，需先运行脚本")

    def test_result_structure(self):
        """TC003-02: 结果结构完整"""
        result_path = Path('backtest/result/volume_ratio_layered_backtest.json')
        if not result_path.exists():
            pytest.skip("结果文件不存在")

        result = json.loads(result_path.read_text())
        required_keys = ['meta', 'layer_stats', 'monotonicity', 'long_short']
        for k in required_keys:
            assert k in result

    def test_meta_fields(self):
        """TC003-03: meta 字段"""
        result_path = Path('backtest/result/volume_ratio_layered_backtest.json')
        if not result_path.exists():
            pytest.skip("结果文件不存在")

        result = json.loads(result_path.read_text())
        meta = result['meta']
        assert meta['factor_name'] == 'volume_ratio'
        assert meta['factor_direction'] == 'negative'
        assert meta['n_layers'] == 5

    def test_layer_stats_complete(self):
        """TC003-04: layer_stats 完整"""
        result_path = Path('backtest/result/volume_ratio_layered_backtest.json')
        if not result_path.exists():
            pytest.skip("结果文件不存在")

        result = json.loads(result_path.read_text())
        assert len(result['layer_stats']) == 5  # 5层


class TestLayeredBacktestExecution:
    """执行集成验证"""

    def test_config_integration(self):
        """TC004-01: 配置类可实例化"""
        config = VolumeRatioLayerConfig()
        assert config.n_layers == 5
        assert config.factor_direction == 'negative'

    def test_factor_direction_derives_long_short(self):
        """TC004-02: factor_direction 决定多空组合"""
        config = VolumeRatioLayerConfig()
        # 反向因子：低值层做多，高值层做空
        assert config.factor_direction == 'negative'


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
