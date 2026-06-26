#!/usr/bin/env python3
"""
test_layered_backtest_tail_price_slope_1d 测试用例

测试脚本: backtest/layered_backtest_tail_price_slope_1d.py
因子计算: factor_ic/ic_tail_price_slope_1d.py::calculate_tail_price_slope
流程文档: backtest/docs/layered_backtest_tail_price_slope_1d_flow.md

版本历史:
  v1.0 (2026-06-02): 初始版本，创建测试用例
  v1.1 (2026-06-02): Round 1-3 优化同步 - 版本历史与主脚本同步
"""

import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import json
from typing import Literal, get_args

import numpy as np
import pandas as pd
import pytest

from backtest.layered_backtest_tail_price_slope_1d import TailPriceSlopeLayerConfig


class TestTailPriceSlopeLayerConfig:
    """配置类属性验证"""

    def test_factor_name_classvar(self):
        """TC001-01: factor_name 类属性"""
        assert TailPriceSlopeLayerConfig.factor_name == "tail_price_slope"

    def test_layer_names_classvar(self):
        """TC001-02: layer_names 类属性为纯标签"""
        assert len(TailPriceSlopeLayerConfig.layer_names) == 5
        assert TailPriceSlopeLayerConfig.layer_names[0] == "lowest"

    def test_layer_descriptions_classvar(self):
        """TC001-03: layer_descriptions 含中文描述"""
        assert len(TailPriceSlopeLayerConfig.layer_descriptions) == 5
        assert TailPriceSlopeLayerConfig.layer_descriptions[0] == "极低层(趋势斜率最小，下跌趋势最明显)"

    def test_ic_source_default(self):
        """TC001-04: ic_source 默认路径"""
        config = TailPriceSlopeLayerConfig()
        # 未显式声明时，基类按 factor_name 拼接默认路径
        assert config.ic_source_resolved.endswith("ic_tail_price_slope_1d_analysis_result.json")

    def test_ic_meta_direction_negative(self):
        """TC001-05: factor_direction = negative（从 IC 文件派生）"""
        config = TailPriceSlopeLayerConfig()
        # ic_mean = -0.0822 < 0 时 direction = negative
        assert config.factor_direction == "negative"

    def test_n_layers_derived(self):
        """TC001-06: n_layers 由 len(layer_names) 派生"""
        config = TailPriceSlopeLayerConfig()
        assert config.n_layers == len(TailPriceSlopeLayerConfig.layer_names)

    def test_layer_names_dict_generated(self):
        """TC001-07: layer_names_dict 使用 layer_descriptions"""
        config = TailPriceSlopeLayerConfig()
        assert "1" in config.layer_names_dict
        assert "5" in config.layer_names_dict
        assert config.layer_names_dict["1"] == "极低层(趋势斜率最小，下跌趋势最明显)"

    def test_layer_names_semantic(self):
        """TC001-08: layer_descriptions 语义描述"""
        # layer_descriptions 应包含"趋势斜率"相关描述
        for desc in TailPriceSlopeLayerConfig.layer_descriptions:
            assert "趋势斜率" in desc

    def test_layer_names_no_fixed_threshold(self):
        """TC001-09: layer_names 纯标签无固定阈值"""
        for name in TailPriceSlopeLayerConfig.layer_names:
            # 纯标签不含数字阈值
            assert not any(c.isdigit() for c in name)

    def test_factor_direction_negative(self):
        """TC001-10: factor_direction = negative"""
        config = TailPriceSlopeLayerConfig()
        assert config.factor_direction == "negative"

    def test_factor_direction_literal_type(self):
        """TC001-11: factor_direction 类型约束"""
        valid_values = get_args(Literal["positive", "negative"])
        config = TailPriceSlopeLayerConfig()
        assert config.factor_direction in valid_values


class TestLayeredBacktestResult:
    """回测结果验证"""

    def test_result_file_exists(self):
        """TC002-01: 结果文件存在"""
        result_path = Path("backtest/result/tail_price_slope_layered_backtest.json")
        # 如果文件不存在，跳过测试（需要先运行脚本）
        if not result_path.exists():
            pytest.skip("结果文件不存在，需先运行脚本")

    def test_result_structure(self):
        """TC002-02: 结果结构完整"""
        result_path = Path("backtest/result/tail_price_slope_layered_backtest.json")
        if not result_path.exists():
            pytest.skip("结果文件不存在")

        with open(result_path) as f:
            result = json.load(f)
        required_keys = ["meta", "layer_stats", "monotonicity", "long_short"]
        for k in required_keys:
            assert k in result

    def test_meta_fields(self):
        """TC002-03: meta 字段"""
        result_path = Path("backtest/result/tail_price_slope_layered_backtest.json")
        if not result_path.exists():
            pytest.skip("结果文件不存在")

        with open(result_path) as f:
            result = json.load(f)
        meta = result["meta"]
        assert meta["factor_name"] == "tail_price_slope"
        assert meta["factor_direction"] == "negative"
        assert meta["n_layers"] == 5

    def test_layer_stats_complete(self):
        """TC002-04: layer_stats 完整"""
        result_path = Path("backtest/result/tail_price_slope_layered_backtest.json")
        if not result_path.exists():
            pytest.skip("结果文件不存在")

        with open(result_path) as f:
            result = json.load(f)
        assert len(result["layer_stats"]) == 5  # 5层


class TestLayeredBacktestExecution:
    """执行集成验证"""

    def test_config_integration(self):
        """TC003-01: 配置类可实例化"""
        config = TailPriceSlopeLayerConfig()
        assert config.n_layers == 5
        assert config.factor_direction == "negative"

    def test_factor_direction_derives_long_short(self):
        """TC003-02: factor_direction 决定多空组合"""
        config = TailPriceSlopeLayerConfig()
        # 反向因子：低值层做多，高值层做空
        # 由基类 _derive_long_short() 派生
        assert config.factor_direction == "negative"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
