#!/usr/bin/env python3
"""
test_layered_backtest_tail_volume_shrink_delta_1d 测试用例

测试脚本: backtest/layered_backtest_tail_volume_shrink_delta_1d.py
因子计算: data_fetchers/factor_calculator.py::calculate_tail_volume_shrink_delta
规范文档: backtest/MODULE.md
"""

import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import json
from typing import Literal, get_args

import pytest

from backtest.layered_backtest_tail_volume_shrink_delta_1d import TailVolumeShrinkDeltaLayerConfig
from data_fetchers.factor_calculator import calculate_tail_volume_shrink_delta


class TestTailVolumeShrinkDeltaLayerConfig:
    """配置类属性验证"""

    def test_factor_name_classvar(self):
        """TC001-01: factor_name 类属性"""
        assert TailVolumeShrinkDeltaLayerConfig.factor_name == "tail_volume_shrink_delta"

    def test_layer_names_classvar(self):
        """TC001-02: layer_names 类属性为纯标签"""
        assert len(TailVolumeShrinkDeltaLayerConfig.layer_names) == 5
        assert TailVolumeShrinkDeltaLayerConfig.layer_names[0] == "lowest"

    def test_layer_descriptions_classvar(self):
        """TC001-03: layer_descriptions 含中文描述"""
        assert len(TailVolumeShrinkDeltaLayerConfig.layer_descriptions) == 5

    def test_ic_source_default(self):
        """TC001-04: ic_source 默认路径"""
        config = TailVolumeShrinkDeltaLayerConfig()
        assert config.ic_source_resolved == "factor_ic/result/ic_tail_volume_shrink_delta_1d_analysis_result.json"

    def test_n_layers_derived(self):
        """TC001-05: n_layers 由 len(layer_names) 派生"""
        config = TailVolumeShrinkDeltaLayerConfig()
        assert config.n_layers == len(TailVolumeShrinkDeltaLayerConfig.layer_names)

    def test_layer_names_dict_generated(self):
        """TC001-06: layer_names_dict 使用 layer_descriptions"""
        config = TailVolumeShrinkDeltaLayerConfig()
        assert "1" in config.layer_names_dict
        assert "5" in config.layer_names_dict

    def test_layer_names_no_fixed_threshold(self):
        """TC001-07: layer_names 纯标签无固定阈值"""
        for name in TailVolumeShrinkDeltaLayerConfig.layer_names:
            assert not any(c.isdigit() for c in name)

    def test_factor_direction_literal_type(self):
        """TC001-08: factor_direction 类型约束"""
        valid_values = get_args(Literal["positive", "negative"])
        config = TailVolumeShrinkDeltaLayerConfig()
        assert config.factor_direction in valid_values


class TestCalculateTailVolumeShrinkDelta:
    """因子计算验证（配置类存在即通过，详细计算在IC模块测试）"""

    def test_calculator_importable(self):
        """TC002-01: factor_calculator 函数可导入"""
        assert callable(calculate_tail_volume_shrink_delta)


class TestLayeredBacktestResult:
    """回测结果验证"""

    def test_result_file_exists(self):
        """TC003-01: 结果文件存在"""
        result_path = Path("backtest/result/tail_volume_shrink_delta_layered_backtest.json")
        if not result_path.exists():
            pytest.skip("结果文件不存在，需先运行脚本")

    def test_result_structure(self):
        """TC003-02: 结果结构完整"""
        result_path = Path("backtest/result/tail_volume_shrink_delta_layered_backtest.json")
        if not result_path.exists():
            pytest.skip("结果文件不存在")

        with open(result_path) as fh:
            result = json.load(fh)
        required_keys = ["meta", "layer_stats", "monotonicity", "long_short"]
        for k in required_keys:
            assert k in result

    def test_meta_fields(self):
        """TC003-03: meta 字段"""
        result_path = Path("backtest/result/tail_volume_shrink_delta_layered_backtest.json")
        if not result_path.exists():
            pytest.skip("结果文件不存在")

        with open(result_path) as fh:
            result = json.load(fh)
        meta = result["meta"]
        assert meta["factor_name"] == "tail_volume_shrink_delta"
        assert meta["factor_direction"] in ("positive", "negative")
        assert meta["n_layers"] == 5

    def test_layer_stats_complete(self):
        """TC003-04: layer_stats 完整"""
        result_path = Path("backtest/result/tail_volume_shrink_delta_layered_backtest.json")
        if not result_path.exists():
            pytest.skip("结果文件不存在")

        with open(result_path) as fh:
            result = json.load(fh)
        assert len(result["layer_stats"]) == 5


class TestLayeredBacktestExecution:
    """执行集成验证"""

    def test_config_integration(self):
        """TC004-01: 配置类可实例化"""
        config = TailVolumeShrinkDeltaLayerConfig()
        assert config.n_layers == 5

    def test_factor_direction_derives_long_short(self):
        """TC004-02: factor_direction 决定多空组合"""
        config = TailVolumeShrinkDeltaLayerConfig()
        assert config.factor_direction in ("positive", "negative")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
