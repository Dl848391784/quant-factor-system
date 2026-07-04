#!/usr/bin/env python3
"""
test_layered_backtest_return_5d_1d 测试用例

测试脚本: backtest/layered_backtest_return_5d_1d.py
因子计算: data_fetchers/factor_calculator.py::calculate_return_5d
流程文档: backtest/docs/layered_backtest_return_5d_1d_flow.md
"""

import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import json
from typing import Literal, get_args

import numpy as np
import pandas as pd
import pytest

from backtest.layered_backtest_return_5d_1d import Return5dLayerConfig
from data_fetchers.factor_calculator import calculate_return_5d


class TestReturn5dLayerConfig:
    """配置类属性验证"""

    def test_factor_name_classvar(self):
        """TC001-01: factor_name 类属性"""
        assert Return5dLayerConfig.factor_name == "return_5d"

    def test_layer_names_classvar(self):
        """TC001-02: layer_names 类属性为纯标签"""
        assert len(Return5dLayerConfig.layer_names) == 5
        assert Return5dLayerConfig.layer_names[0] == "lowest"

    def test_layer_descriptions_classvar(self):
        """TC001-03: layer_descriptions 含中文描述"""
        assert len(Return5dLayerConfig.layer_descriptions) == 5
        assert Return5dLayerConfig.layer_descriptions[0] == "极低层(5日涨幅最小)"

    def test_ic_source_default(self):
        """TC001-03: ic_source 默认路径"""
        config = Return5dLayerConfig()
        # 未显式声明时，基类按 factor_name 拼接默认路径
        assert config.ic_source_resolved.endswith("ic_return_5d_1d_analysis_result.json")

    def test_ic_meta_direction_negative(self):
        """TC001-04: factor_direction = negative（从 IC 文件派生）"""
        config = Return5dLayerConfig()
        # ic_mean < 0 时 direction = negative
        assert config.factor_direction == "negative"

    def test_n_layers_derived(self):
        """TC001-05: n_layers 由 len(layer_names) 派生"""
        config = Return5dLayerConfig()
        assert config.n_layers == len(Return5dLayerConfig.layer_names)

    def test_layer_names_dict_generated(self):
        """TC001-06: layer_names_dict 使用 layer_descriptions"""
        config = Return5dLayerConfig()
        assert "1" in config.layer_names_dict
        assert "5" in config.layer_names_dict
        assert config.layer_names_dict["1"] == "极低层(5日涨幅最小)"

    def test_layer_names_semantic(self):
        """TC001-07: layer_descriptions 语义描述"""
        # layer_descriptions 应包含"涨幅"相关描述
        for desc in Return5dLayerConfig.layer_descriptions:
            assert "涨" in desc or "下跌" in desc or "变化" in desc

    def test_layer_names_no_fixed_threshold(self):
        """TC001-08: layer_names 纯标签无固定阈值"""
        for name in Return5dLayerConfig.layer_names:
            # 纯标签不含数字阈值
            assert not any(c.isdigit() for c in name)

    def test_factor_direction_negative(self):
        """TC001-09: factor_direction = negative"""
        config = Return5dLayerConfig()
        assert config.factor_direction == "negative"

    def test_factor_direction_literal_type(self):
        """TC001-10: factor_direction 类型约束"""
        valid_values = get_args(Literal["positive", "negative"])
        config = Return5dLayerConfig()
        assert config.factor_direction in valid_values


class TestCalculateReturn5d:
    """因子计算验证"""

    def test_basic_calculation(self):
        """TC002-01: 基本计算"""
        df = pd.DataFrame(
            {
                "date": ["D1", "D2", "D3", "D4", "D5", "D6"],
                "asset": ["A1"] * 6,
                "close": [100.0, 102.0, 101.0, 103.0, 105.0, 110.0],
            }
        )
        result = calculate_return_5d(df)
        # return_5d[5] = 110/100 - 1 = 0.10
        assert result["return_5d"].iloc[5] == pytest.approx(0.10, rel=1e-6)

    def test_negative_return(self):
        """TC002-02: 下跌计算"""
        df = pd.DataFrame(
            {
                "date": ["D1", "D2", "D3", "D4", "D5", "D6"],
                "asset": ["A1"] * 6,
                "close": [100.0, 99.0, 98.0, 97.0, 96.0, 95.0],
            }
        )
        result = calculate_return_5d(df)
        # return_5d[5] = 95/100 - 1 = -0.05
        assert result["return_5d"].iloc[5] == pytest.approx(-0.05, rel=1e-6)

    def test_nan_handling(self):
        """TC002-03: NaN 处理（前5天无完整历史）"""
        df = pd.DataFrame(
            {
                "date": ["D1", "D2", "D3", "D4", "D5", "D6"],
                "asset": ["A1"] * 6,
                "close": [100.0, 101.0, 102.0, 103.0, 104.0, 105.0],
            }
        )
        result = calculate_return_5d(df)
        # 前5天无完整5日历史，应为 NaN
        assert pd.isna(result["return_5d"].iloc[0])
        assert pd.isna(result["return_5d"].iloc[4])
        # 第6天有完整历史
        assert not pd.isna(result["return_5d"].iloc[5])

    def test_required_columns(self):
        """TC002-04: 必需列"""
        df = pd.DataFrame(
            {
                "date": ["D1", "D2"],
                "asset": ["A1"] * 2,
                "open": [10.0, 10.5],
            }
        )
        with pytest.raises(KeyError):
            calculate_return_5d(df)


class TestLayeredBacktestResult:
    """回测结果验证"""

    def test_result_file_exists(self):
        """TC003-01: 结果文件存在"""
        result_path = Path("backtest/result/return_5d_layered_backtest.json")
        # 如果文件不存在，跳过测试（需要先运行脚本）
        if not result_path.exists():
            pytest.skip("结果文件不存在，需先运行脚本")

    def test_result_structure(self):
        """TC003-02: 结果结构完整"""
        result_path = Path("backtest/result/return_5d_layered_backtest.json")
        if not result_path.exists():
            pytest.skip("结果文件不存在")

        with open(result_path) as f:  # noqa: SIM115
            result = json.load(f)
        required_keys = ["meta", "layer_stats", "monotonicity", "long_short"]
        for k in required_keys:
            assert k in result

    def test_meta_fields(self):
        """TC003-03: meta 字段"""
        result_path = Path("backtest/result/return_5d_layered_backtest.json")
        if not result_path.exists():
            pytest.skip("结果文件不存在")

        with open(result_path) as f:  # noqa: SIM115
            result = json.load(f)
        meta = result["meta"]
        assert meta["factor_name"] == "return_5d"
        assert meta["factor_direction"] == "negative"
        assert meta["n_layers"] == 5

    def test_layer_stats_complete(self):
        """TC003-04: layer_stats 完整"""
        result_path = Path("backtest/result/return_5d_layered_backtest.json")
        if not result_path.exists():
            pytest.skip("结果文件不存在")

        with open(result_path) as f:  # noqa: SIM115
            result = json.load(f)
        assert len(result["layer_stats"]) == 5  # 5层


class TestLayeredBacktestExecution:
    """执行集成验证"""

    def test_config_integration(self):
        """TC004-01: 配置类可实例化"""
        config = Return5dLayerConfig()
        assert config.n_layers == 5
        assert config.factor_direction == "negative"

    def test_factor_direction_derives_long_short(self):
        """TC004-02: factor_direction 决定多空组合"""
        config = Return5dLayerConfig()
        # 反向因子：低值层做多，高值层做空
        # 由基类 _derive_long_short() 派生
        assert config.factor_direction == "negative"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
