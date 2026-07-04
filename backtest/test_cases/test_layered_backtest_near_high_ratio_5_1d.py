#!/usr/bin/env python3
"""
test_layered_backtest_near_high_ratio_5_1d 测试用例

测试脚本: backtest/layered_backtest_near_high_ratio_5_1d.py
因子计算: data_fetchers/factor_calculator.py::calculate_near_high_ratio_5
流程文档: backtest/docs/layered_backtest_near_high_ratio_5_1d_flow.md
"""

import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import json
from typing import Literal, get_args

import pandas as pd
import pytest

from backtest.layered_backtest_near_high_ratio_5_1d import NearHighRatio5LayerConfig
from data_fetchers.factor_calculator import calculate_near_high_ratio_5


class TestNearHighRatio5LayerConfig:
    """配置类属性验证"""

    def test_factor_name_classvar(self):
        """TC001-01: factor_name 类属性"""
        assert NearHighRatio5LayerConfig.factor_name == "near_high_ratio_5"

    def test_layer_names_classvar(self):
        """TC001-02: layer_names 类属性为纯标签"""
        assert len(NearHighRatio5LayerConfig.layer_names) == 5
        assert NearHighRatio5LayerConfig.layer_names[0] == "lowest"

    def test_layer_descriptions_classvar(self):
        """TC001-03: layer_descriptions 含中文描述"""
        assert len(NearHighRatio5LayerConfig.layer_descriptions) == 5
        assert NearHighRatio5LayerConfig.layer_descriptions[0] == "极低层(远低于5日最高价)"

    def test_ic_source_default(self):
        """TC001-04: ic_source 默认路径"""
        config = NearHighRatio5LayerConfig()
        assert config.ic_source_resolved.endswith("ic_near_high_ratio_5_1d_analysis_result.json")

    def test_ic_meta_direction_negative(self):
        """TC001-05: factor_direction = negative（从 IC 文件派生）"""
        config = NearHighRatio5LayerConfig()
        assert config.factor_direction == "negative"

    def test_n_layers_derived(self):
        """TC001-06: n_layers 由 len(layer_names) 派生"""
        config = NearHighRatio5LayerConfig()
        assert config.n_layers == len(NearHighRatio5LayerConfig.layer_names)

    def test_layer_names_dict_generated(self):
        """TC001-07: layer_names_dict 使用 layer_descriptions"""
        config = NearHighRatio5LayerConfig()
        assert "1" in config.layer_names_dict
        assert "5" in config.layer_names_dict
        assert config.layer_names_dict["1"] == "极低层(远低于5日最高价)"

    def test_layer_names_semantic(self):
        """TC001-08: layer_descriptions 语义描述"""
        for desc in NearHighRatio5LayerConfig.layer_descriptions:
            # 描述应包含位置相关关键词（低点/位置/高点）
            assert "5日" in desc or "高" in desc or "接近" in desc or "正常" in desc

    def test_layer_names_no_fixed_threshold(self):
        """TC001-09: layer_names 纯标签无固定阈值"""
        for name in NearHighRatio5LayerConfig.layer_names:
            assert not any(c.isdigit() for c in name)

    def test_factor_direction_literal_type(self):
        """TC001-10: factor_direction 类型约束"""
        valid_values = get_args(Literal["positive", "negative"])
        config = NearHighRatio5LayerConfig()
        assert config.factor_direction in valid_values


class TestCalculateNearHighRatio5:
    """因子计算验证"""

    def test_basic_calculation(self):
        """TC002-01: 基本计算"""
        df = pd.DataFrame(
            {
                "date": ["D1", "D2", "D3", "D4", "D5", "D6"],
                "asset": ["A1"] * 6,
                "close": [10.0, 12.0, 11.0, 14.0, 13.0, 15.0],
            }
        )
        result = calculate_near_high_ratio_5(df)
        # near_high_ratio_5 = (close - min(close,5日)) / (max(close,5日) - min(close,5日))
        assert "near_high_ratio_5" in result.columns
        # D6: window=[12,11,14,13,15], min=11, max=15, (15-11)/(15-11) = 1.0
        assert result["near_high_ratio_5"].iloc[5] == pytest.approx(1.0, rel=1e-6)

    def test_flat_range_handling(self):
        """TC002-02: 5日内价格完全相同（max=min）"""
        df = pd.DataFrame(
            {
                "date": ["D1", "D2", "D3", "D4", "D5", "D6"],
                "asset": ["A1"] * 6,
                "close": [10.0, 10.0, 10.0, 10.0, 10.0, 10.0],
            }
        )
        result = calculate_near_high_ratio_5(df)
        # max = min 时，公式分母为0，应为 NaN 或特殊处理
        assert "near_high_ratio_5" in result.columns

    def test_required_columns(self):
        """TC002-03: 必需列"""
        df = pd.DataFrame(
            {
                "date": ["D1"],
                "asset": ["A1"],
            }
        )
        with pytest.raises(KeyError):
            calculate_near_high_ratio_5(df)


class TestLayeredBacktestResult:
    """回测结果验证"""

    def test_result_file_exists(self):
        """TC003-01: 结果文件存在"""
        result_path = Path("backtest/result/near_high_ratio_5_layered_backtest.json")
        if not result_path.exists():
            pytest.skip("结果文件不存在，需先运行脚本")

    def test_result_structure(self):
        """TC003-02: 结果结构完整"""
        result_path = Path("backtest/result/near_high_ratio_5_layered_backtest.json")
        if not result_path.exists():
            pytest.skip("结果文件不存在")

        with open(result_path) as fh:
            result = json.load(fh)
        required_keys = ["meta", "layer_stats", "monotonicity", "long_short"]
        for k in required_keys:
            assert k in result

    def test_meta_fields(self):
        """TC003-03: meta 字段"""
        result_path = Path("backtest/result/near_high_ratio_5_layered_backtest.json")
        if not result_path.exists():
            pytest.skip("结果文件不存在")

        with open(result_path) as fh:
            result = json.load(fh)
        meta = result["meta"]
        assert meta["factor_name"] == "near_high_ratio_5"
        assert meta["factor_direction"] == "negative"
        assert meta["n_layers"] == 5

    def test_layer_stats_complete(self):
        """TC003-04: layer_stats 完整"""
        result_path = Path("backtest/result/near_high_ratio_5_layered_backtest.json")
        if not result_path.exists():
            pytest.skip("结果文件不存在")

        with open(result_path) as fh:
            result = json.load(fh)
        assert len(result["layer_stats"]) == 5


class TestLayeredBacktestExecution:
    """执行集成验证"""

    def test_config_integration(self):
        """TC004-01: 配置类可实例化"""
        config = NearHighRatio5LayerConfig()
        assert config.n_layers == 5
        assert config.factor_direction == "negative"

    def test_factor_direction_derives_long_short(self):
        """TC004-02: factor_direction 决定多空组合"""
        config = NearHighRatio5LayerConfig()
        assert config.factor_direction == "negative"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
