#!/usr/bin/env python3
"""
test_layered_backtest_turnover_surge_1d 测试用例

测试脚本: backtest/layered_backtest_turnover_surge_1d.py
因子计算: data_fetchers/factor_calculator.py::calculate_turnover_surge
"""

import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from typing import Literal, get_args

import pytest

from backtest.layered_backtest_turnover_surge_1d import TurnoverSurgeLayerConfig


class TestTurnoverSurgeLayerConfig:
    """配置类属性验证"""

    def test_factor_name_classvar(self):
        """TC001-01: factor_name 类属性"""
        assert TurnoverSurgeLayerConfig.factor_name == "turnover_surge"

    def test_layer_names_classvar(self):
        """TC001-02: layer_names 类属性为纯标签"""
        assert len(TurnoverSurgeLayerConfig.layer_names) == 5
        assert TurnoverSurgeLayerConfig.layer_names[0] == "lowest"

    def test_layer_descriptions_classvar(self):
        """TC001-03: layer_descriptions 含中文描述"""
        assert len(TurnoverSurgeLayerConfig.layer_descriptions) == 5
        assert "突增" in TurnoverSurgeLayerConfig.layer_descriptions[0]

    def test_ic_source_default(self):
        """TC001-04: ic_source 默认路径"""
        config = TurnoverSurgeLayerConfig()
        assert config.ic_source_resolved.endswith("ic_turnover_surge_1d_analysis_result.json")

    def test_factor_col_resolved(self):
        """TC001-05: factor_col_resolved 默认=factor_name"""
        config = TurnoverSurgeLayerConfig()
        assert config.factor_col_resolved == "turnover_surge"

    def test_n_layers_derived(self):
        """TC001-06: n_layers 由 len(layer_names) 派生"""
        config = TurnoverSurgeLayerConfig()
        assert config.n_layers == len(TurnoverSurgeLayerConfig.layer_names)

    def test_layer_names_dict_generated(self):
        """TC001-07: layer_names_dict 使用 layer_descriptions"""
        config = TurnoverSurgeLayerConfig()
        assert "1" in config.layer_names_dict
        assert "5" in config.layer_names_dict

    def test_layer_names_semantic(self):
        """TC001-08: layer_descriptions 语义描述"""
        for desc in TurnoverSurgeLayerConfig.layer_descriptions:
            assert "突增" in desc or "无" in desc

    def test_layer_names_no_fixed_threshold(self):
        """TC001-09: layer_names 纯标签无固定阈值"""
        for name in TurnoverSurgeLayerConfig.layer_names:
            assert not any(c.isdigit() for c in name)


class TestTurnoverSurgeCalculator:
    """因子计算函数验证"""

    def test_required_cols(self):
        """TC002-01: calculate_turnover_surge.required_cols"""
        from data_fetchers.factor_calculator import calculate_turnover_surge

        required_cols = getattr(calculate_turnover_surge, "required_cols", None)
        assert required_cols is not None


class TestLayeredBacktestExecution:
    """执行集成验证"""

    def test_config_integration(self):
        """TC003-01: 配置类可实例化"""
        config = TurnoverSurgeLayerConfig()
        assert config.n_layers == 5

    def test_factor_direction_literal_type(self):
        """TC003-02: factor_direction 类型约束"""
        valid_values = get_args(Literal["positive", "negative"])
        config = TurnoverSurgeLayerConfig()
        assert config.factor_direction in valid_values


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
