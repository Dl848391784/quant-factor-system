#!/usr/bin/env python3
"""
尾盘价格位置因子 IC 计算器测试用例

测试覆盖：
- 因子计算逻辑（calculate_tail_price_position）
- 边界处理（除零、数据不完整）
- 数据合并逻辑
"""

import gzip
import json
import sys
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd
import pytest


# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from factor_ic.common.tail_data_loader import (
    TAIL_TRADING_DATA_PATH,
    load_tail_trading_data,
)
from factor_ic.ic_tail_price_position import (
    EPSILON,
    calc_price_position,
    calculate_tail_price_position,
    get_close_price,
)


class TestGetClosePrice:
    """收盘价获取函数测试"""

    def test_normal_list(self):
        """正常列表场景"""
        prices = [10.0, 10.1, 10.2, 10.3, 10.4, 10.5, 10.6, 10.7, 10.8, 10.9, 11.0, 11.0, 11.0]
        result = get_close_price(prices)
        assert result == 11.0

    def test_short_list(self):
        """列表长度不足"""
        prices = [10.0, 10.1]
        result = get_close_price(prices)
        assert pd.isna(result)

    def test_not_list(self):
        """非列表类型"""
        result = get_close_price(None)
        assert pd.isna(result)


class TestCalcPricePosition:
    """价格位置计算函数测试"""

    def test_normal_calculation(self):
        """正常计算"""
        result = calc_price_position(10.5, 11.0, 10.0)
        expected = 0.5
        assert abs(result - expected) < 0.001

    def test_top_position(self):
        """顶部位置"""
        result = calc_price_position(11.0, 11.0, 10.0)
        expected = 1.0
        assert abs(result - expected) < 0.001

    def test_bottom_position(self):
        """底部位置"""
        result = calc_price_position(10.0, 11.0, 10.0)
        expected = 0.0
        assert abs(result - expected) < 0.001

    def test_zero_range(self):
        """除零防护"""
        result = calc_price_position(10.0, 10.0, 10.0)
        assert pd.isna(result)

    def test_nan_input(self):
        """NaN 输入"""
        result = calc_price_position(np.nan, 11.0, 10.0)
        assert pd.isna(result)


class TestCalculateTailPricePosition:
    """因子计算函数测试"""

    def test_normal_calculation(self):
        """正常计算场景"""
        factor_df = pd.DataFrame({
            "date": ["2026-06-01", "2026-06-01"],
            "asset": ["000001", "000002"],
        })

        mock_tail_df = pd.DataFrame({
            "date": ["2026-06-01", "2026-06-01"],
            "asset": ["000001", "000002"],
            "prices": [
                [10.0, 10.1, 10.2, 10.3, 10.4, 10.5, 10.6, 10.7, 10.8, 10.9, 11.0, 11.0, 11.0],
                [20.0, 20.1, 20.2, 20.3, 20.4, 20.5, 20.6, 20.7, 20.8, 20.9, 21.0, 21.0, 21.0],
            ],
            "tail_high": [11.0, 21.0],
            "tail_low": [10.0, 20.0],
        })

        # 临时替换公共模块路径
        import factor_ic.common.tail_data_loader as loader_module
        original_path = loader_module.TAIL_TRADING_DATA_PATH

        with tempfile.NamedTemporaryFile(suffix=".json.gz", delete=False) as f:
            temp_path = Path(f.name)
            with gzip.open(temp_path, "wt", encoding="utf-8") as gz:
                json.dump({"data": mock_tail_df.to_dict("records")}, gz)

        loader_module.TAIL_TRADING_DATA_PATH = temp_path

        try:
            result_df = calculate_tail_price_position(factor_df)

            assert "tail_price_position" in result_df.columns
            assert result_df["tail_price_position"].notna().sum() == 2

            # asset 000001: 位置 = (11.0 - 10.0) / (11.0 - 10.0) = 1.0
            expected_000001 = 1.0
            assert abs(
                result_df.loc[result_df["asset"] == "000001", "tail_price_position"].values[0]
                - expected_000001
            ) < 0.001

        finally:
            loader_module.TAIL_TRADING_DATA_PATH = original_path
            temp_path.unlink()

    def test_mid_position(self):
        """中间位置场景"""
        factor_df = pd.DataFrame({
            "date": ["2026-06-01"],
            "asset": ["000001"],
        })

        mock_tail_df = pd.DataFrame({
            "date": ["2026-06-01"],
            "asset": ["000001"],
            "prices": [[10.0, 10.1, 10.2, 10.3, 10.4, 10.5, 10.6, 10.7, 10.8, 10.9, 11.0, 11.0, 10.5]],
            "tail_high": [11.0],
            "tail_low": [10.0],
        })

        import factor_ic.common.tail_data_loader as loader_module
        original_path = loader_module.TAIL_TRADING_DATA_PATH

        with tempfile.NamedTemporaryFile(suffix=".json.gz", delete=False) as f:
            temp_path = Path(f.name)
            with gzip.open(temp_path, "wt", encoding="utf-8") as gz:
                json.dump({"data": mock_tail_df.to_dict("records")}, gz)

        loader_module.TAIL_TRADING_DATA_PATH = temp_path

        try:
            result_df = calculate_tail_price_position(factor_df)
            expected = 0.5
            assert abs(result_df["tail_price_position"].values[0] - expected) < 0.001

        finally:
            loader_module.TAIL_TRADING_DATA_PATH = original_path
            temp_path.unlink()

    def test_zero_range_protection(self):
        """除零防护"""
        factor_df = pd.DataFrame({
            "date": ["2026-06-01"],
            "asset": ["000001"],
        })

        mock_tail_df = pd.DataFrame({
            "date": ["2026-06-01"],
            "asset": ["000001"],
            "prices": [[10.0] * 13],
            "tail_high": [10.0],
            "tail_low": [10.0],
        })

        import factor_ic.common.tail_data_loader as loader_module
        original_path = loader_module.TAIL_TRADING_DATA_PATH

        with tempfile.NamedTemporaryFile(suffix=".json.gz", delete=False) as f:
            temp_path = Path(f.name)
            with gzip.open(temp_path, "wt", encoding="utf-8") as gz:
                json.dump({"data": mock_tail_df.to_dict("records")}, gz)

        loader_module.TAIL_TRADING_DATA_PATH = temp_path

        try:
            result_df = calculate_tail_price_position(factor_df)
            assert pd.isna(result_df["tail_price_position"].values[0])

        finally:
            loader_module.TAIL_TRADING_DATA_PATH = original_path
            temp_path.unlink()


class TestLoadTailTradingData:
    """数据加载测试"""

    def test_file_not_found(self):
        """文件不存在时抛出异常"""
        import factor_ic.common.tail_data_loader as loader_module
        original_path = loader_module.TAIL_TRADING_DATA_PATH
        loader_module.TAIL_TRADING_DATA_PATH = Path("/nonexistent/path.json.gz")

        try:
            with pytest.raises(FileNotFoundError):
                load_tail_trading_data()
        finally:
            loader_module.TAIL_TRADING_DATA_PATH = original_path

    def test_invalid_format(self):
        """数据格式错误时抛出异常"""
        import factor_ic.common.tail_data_loader as loader_module
        original_path = loader_module.TAIL_TRADING_DATA_PATH

        # 写入格式错误的临时文件（缺少 data 字段）
        with tempfile.NamedTemporaryFile(suffix=".json.gz", delete=False) as f:
            temp_path = Path(f.name)
            with gzip.open(temp_path, "wt", encoding="utf-8") as gz:
                json.dump({"meta": {"version": "1.0"}}, gz)  # 缺少 data 字段

        loader_module.TAIL_TRADING_DATA_PATH = temp_path

        try:
            with pytest.raises(ValueError, match="缺少 'data' 字段"):
                load_tail_trading_data()
        finally:
            loader_module.TAIL_TRADING_DATA_PATH = original_path
            temp_path.unlink()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
