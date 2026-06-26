#!/usr/bin/env python3
"""
test_layered_backtest_past_return_1d_1d 测试用例

测试脚本: backtest/layered_backtest_past_return_1d_1d.py
因子计算: data_fetchers/factor_calculator.py::calculate_past_return_1d
IC文件: factor_ic/result/ic_past_return_1d_1d_analysis_result.json
"""

import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from typing import Literal, get_args

import numpy as np
import pandas as pd
import pytest

from backtest.layered_backtest_past_return_1d_1d import PastReturn1dLayerConfig
from data_fetchers.factor_calculator import calculate_past_return_1d


class TestPastReturn1dLayerConfig:
    """配置类属性验证"""

    def test_factor_name_classvar(self):
        """TC001-01: factor_name 类属性"""
        assert PastReturn1dLayerConfig.factor_name == "past_return_1d"

    def test_layer_names_classvar(self):
        """TC001-02: layer_names 类属性为纯标签"""
        assert len(PastReturn1dLayerConfig.layer_names) == 5
        assert PastReturn1dLayerConfig.layer_names[0] == "lowest"

    def test_layer_descriptions_classvar(self):
        """TC001-03: layer_descriptions 含中文描述"""
        assert len(PastReturn1dLayerConfig.layer_descriptions) == 5
        assert PastReturn1dLayerConfig.layer_descriptions[0] == "极低层(当日跌幅最大)"

    def test_ic_source_default(self):
        """TC001-04: ic_source 默认路径"""
        config = PastReturn1dLayerConfig()
        # 未显式声明时，基类按 factor_name 拼接默认路径
        assert config.ic_source_resolved.endswith("ic_past_return_1d_1d_analysis_result.json")

    def test_n_layers_derived(self):
        """TC001-05: n_layers 由 len(layer_names) 派生"""
        config = PastReturn1dLayerConfig()
        assert config.n_layers == len(PastReturn1dLayerConfig.layer_names)

    def test_layer_names_dict_generated(self):
        """TC001-06: layer_names_dict 使用 layer_descriptions"""
        config = PastReturn1dLayerConfig()
        assert "1" in config.layer_names_dict
        assert "5" in config.layer_names_dict
        assert config.layer_names_dict["1"] == "极低层(当日跌幅最大)"

    def test_layer_names_semantic(self):
        """TC001-07: layer_descriptions 语义描述"""
        # layer_descriptions 应包含"跌幅"或"涨幅"相关描述
        for desc in PastReturn1dLayerConfig.layer_descriptions:
            assert "跌" in desc or "涨" in desc or "变化" in desc

    def test_layer_names_no_fixed_threshold(self):
        """TC001-08: layer_names 纯标签无固定阈值"""
        for name in PastReturn1dLayerConfig.layer_names:
            # 纯标签不含数字阈值
            assert not any(c.isdigit() for c in name)


class TestCalculatePastReturn1d:
    """因子计算验证"""

    def test_basic_calculation(self):
        """TC002-01: 基本计算"""
        df = pd.DataFrame(
            {
                "date": ["D1", "D2", "D3"],
                "asset": ["A1"] * 3,
                "close": [100.0, 102.0, 101.0],
            }
        )
        result = calculate_past_return_1d(df)

        assert "past_return_1d" in result.columns
        # 第2天: (102/100 - 1) = 0.02
        assert np.isclose(result["past_return_1d"].iloc[1], 0.02, atol=0.001)

    def test_first_day_nan(self):
        """TC002-02: 第一日为 NaN"""
        df = pd.DataFrame(
            {
                "date": ["D1", "D2", "D3"],
                "asset": ["A1"] * 3,
                "close": [100.0, 102.0, 101.0],
            }
        )
        result = calculate_past_return_1d(df)

        assert pd.isna(result["past_return_1d"].iloc[0])

    def test_negative_return(self):
        """TC002-03: 下跌场景"""
        df = pd.DataFrame(
            {
                "date": ["D1", "D2", "D3"],
                "asset": ["A1"] * 3,
                "close": [100.0, 95.0, 90.0],  # 下跌
            }
        )
        result = calculate_past_return_1d(df)

        # 第2天: (95/100 - 1) = -0.05
        assert np.isclose(result["past_return_1d"].iloc[1], -0.05, atol=0.001)

    def test_zero_close_handling(self):
        """TC002-04: 零收盘价处理"""
        df = pd.DataFrame(
            {
                "date": ["D1", "D2", "D3"],
                "asset": ["A1"] * 3,
                "close": [0.0, 102.0, 101.0],
            }
        )
        result = calculate_past_return_1d(df)

        # 第2天因 close[t-1]=0 应为 NaN
        assert pd.isna(result["past_return_1d"].iloc[1])

    def test_multiple_assets(self):
        """TC002-05: 多资产分组"""
        df = pd.DataFrame(
            {
                "date": ["D1", "D2", "D3", "D1", "D2", "D3"],
                "asset": ["A1", "A1", "A1", "B1", "B1", "B1"],
                "close": [100.0, 102.0, 101.0, 200.0, 202.0, 201.0],
            }
        )
        result = calculate_past_return_1d(df)

        # A1: (102/100 - 1) = 0.02
        a1_df = result[result["asset"] == "A1"].reset_index(drop=True)
        assert np.isclose(a1_df.loc[1, "past_return_1d"], 0.02, atol=0.001)

        # B1: (202/200 - 1) = 0.01
        b1_df = result[result["asset"] == "B1"].reset_index(drop=True)
        assert np.isclose(b1_df.loc[1, "past_return_1d"], 0.01, atol=0.001)


class TestFactorDirection:
    """因子方向验证（依赖 IC 文件）"""

    def test_factor_direction_from_ic(self):
        """TC003-01: factor_direction 从 IC 文件派生"""
        config = PastReturn1dLayerConfig()
        # factor_direction 应为 'positive' 或 'negative'
        valid_values = get_args(Literal["positive", "negative"])
        # 如果 IC 文件不存在，跳过此测试
        try:
            assert config.factor_direction in valid_values
        except FileNotFoundError:
            pytest.skip("IC 文件不存在，需要先运行 ic_past_return_1d_1d.py")
