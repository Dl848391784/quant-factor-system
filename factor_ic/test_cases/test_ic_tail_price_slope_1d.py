#!/usr/bin/env python3
"""
尾盘价格趋势斜率因子 IC 计算器测试用例

测试覆盖：
- 因子计算逻辑（calculate_tail_price_slope）
- 边界处理（除零、数据不完整、数据污染）
- 数据合并逻辑

版本历史:
  v1.0 (2026-06-02): 初始版本，创建测试用例
  v1.3 (2026-06-02): 同步脚本优化 - 版本历史记录
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest


# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from factor_ic.ic_tail_price_slope_1d import EPSILON, calculate_tail_price_slope, load_tail_trading_data


class TestCalculateTailPriceSlope:
    """因子计算函数测试"""

    def test_normal_calculation_uptrend(self):
        """正常计算场景：上涨趋势"""
        # 构造测试数据
        factor_df = pd.DataFrame({"date": ["2026-06-01", "2026-06-01"], "asset": ["000001", "000002"]})

        # Mock 尾盘数据：上涨趋势
        # prices: [10.0, 10.1, 10.2, ..., 11.0]（线性上涨）
        mock_tail_df = pd.DataFrame(
            {
                "date": ["2026-06-01", "2026-06-01"],
                "asset": ["000001", "000002"],
                "prices": [
                    [10.0, 10.1, 10.2, 10.3, 10.4, 10.5, 10.6, 10.7, 10.8, 10.9, 11.0, 11.0, 11.0],
                    [20.0, 20.1, 20.2, 20.3, 20.4, 20.5, 20.6, 20.7, 20.8, 20.9, 21.0, 21.0, 21.0],
                ],
            }
        )

        # 临时替换尾盘数据路径
        import factor_ic.ic_tail_price_slope_1d as module

        original_path = module.TAIL_TRADING_DATA_PATH

        # 写入临时文件
        import gzip
        import json
        import tempfile

        with tempfile.NamedTemporaryFile(suffix=".json.gz", delete=False) as f:
            temp_path = Path(f.name)
            with gzip.open(temp_path, "wt", encoding="utf-8") as gz:
                json.dump({"data": mock_tail_df.to_dict("records")}, gz)

        module.TAIL_TRADING_DATA_PATH = temp_path

        try:
            result_df = calculate_tail_price_slope(factor_df)

            # 验证结果
            assert "tail_price_slope" in result_df.columns
            assert result_df["tail_price_slope"].notna().sum() == 2

            # 验证计算逻辑
            # asset 000001: prices = [10.0, 10.1, ..., 11.0]
            # 线性回归斜率 ≈ 0.1/根K线（近似）
            # 均价 ≈ 10.5
            # 百分比斜率 ≈ 0.1/10.5 ≈ 0.0095
            # 由于前11根线性上涨，后2根持平，斜率会略小

            # 验证上涨趋势（正值）
            assert result_df.loc[result_df["asset"] == "000001", "tail_price_slope"].values[0] > 0

        finally:
            module.TAIL_TRADING_DATA_PATH = original_path
            temp_path.unlink()

    def test_normal_calculation_downtrend(self):
        """正常计算场景：下跌趋势"""
        factor_df = pd.DataFrame({"date": ["2026-06-01"], "asset": ["000001"]})

        # Mock 尾盘数据：下跌趋势
        # prices: [11.0, 10.9, 10.8, ..., 10.0]（线性下跌）
        mock_tail_df = pd.DataFrame(
            {
                "date": ["2026-06-01"],
                "asset": ["000001"],
                "prices": [[11.0, 10.9, 10.8, 10.7, 10.6, 10.5, 10.4, 10.3, 10.2, 10.1, 10.0, 10.0, 10.0]],
            }
        )

        import factor_ic.ic_tail_price_slope_1d as module

        original_path = module.TAIL_TRADING_DATA_PATH

        import gzip
        import json
        import tempfile

        with tempfile.NamedTemporaryFile(suffix=".json.gz", delete=False) as f:
            temp_path = Path(f.name)
            with gzip.open(temp_path, "wt", encoding="utf-8") as gz:
                json.dump({"data": mock_tail_df.to_dict("records")}, gz)

        module.TAIL_TRADING_DATA_PATH = temp_path

        try:
            result_df = calculate_tail_price_slope(factor_df)

            # 验证下跌趋势（负值）
            assert result_df["tail_price_slope"].values[0] < 0

        finally:
            module.TAIL_TRADING_DATA_PATH = original_path
            temp_path.unlink()

    def test_zero_mean_price_protection(self):
        """除零防护：mean_price 接近零"""
        factor_df = pd.DataFrame({"date": ["2026-06-01"], "asset": ["000001"]})

        # Mock 尾盘数据：均价接近零
        mock_tail_df = pd.DataFrame(
            {
                "date": ["2026-06-01"],
                "asset": ["000001"],
                "prices": [[0.0] * 13],  # 全零价格
            }
        )

        import factor_ic.ic_tail_price_slope_1d as module

        original_path = module.TAIL_TRADING_DATA_PATH

        import gzip
        import json
        import tempfile

        with tempfile.NamedTemporaryFile(suffix=".json.gz", delete=False) as f:
            temp_path = Path(f.name)
            with gzip.open(temp_path, "wt", encoding="utf-8") as gz:
                json.dump({"data": mock_tail_df.to_dict("records")}, gz)

        module.TAIL_TRADING_DATA_PATH = temp_path

        try:
            result_df = calculate_tail_price_slope(factor_df)

            # 均价接近零时应返回 NaN
            assert pd.isna(result_df["tail_price_slope"].values[0])

        finally:
            module.TAIL_TRADING_DATA_PATH = original_path
            temp_path.unlink()

    def test_incomplete_data_protection(self):
        """数据不完整防护：prices 数组长度不足"""
        factor_df = pd.DataFrame({"date": ["2026-06-01"], "asset": ["000001"]})

        # Mock 尾盘数据：只有2个价格点
        mock_tail_df = pd.DataFrame(
            {
                "date": ["2026-06-01"],
                "asset": ["000001"],
                "prices": [[10.0, 10.1]],  # 只有2个元素
            }
        )

        import factor_ic.ic_tail_price_slope_1d as module

        original_path = module.TAIL_TRADING_DATA_PATH

        import gzip
        import json
        import tempfile

        with tempfile.NamedTemporaryFile(suffix=".json.gz", delete=False) as f:
            temp_path = Path(f.name)
            with gzip.open(temp_path, "wt", encoding="utf-8") as gz:
                json.dump({"data": mock_tail_df.to_dict("records")}, gz)

        module.TAIL_TRADING_DATA_PATH = temp_path

        try:
            result_df = calculate_tail_price_slope(factor_df)

            # 数据不完整时应返回 NaN
            assert pd.isna(result_df["tail_price_slope"].values[0])

        finally:
            module.TAIL_TRADING_DATA_PATH = original_path
            temp_path.unlink()

    def test_nan_data_protection(self):
        """数据污染防护：prices 包含 NaN"""
        factor_df = pd.DataFrame({"date": ["2026-06-01"], "asset": ["000001"]})

        # Mock 尾盘数据：包含 NaN 值
        mock_tail_df = pd.DataFrame(
            {
                "date": ["2026-06-01"],
                "asset": ["000001"],
                "prices": [[10.0, 10.1, np.nan, 10.3, 10.4, 10.5, 10.6, 10.7, 10.8, 10.9, 11.0, 11.0, 11.0]],
            }
        )

        import factor_ic.ic_tail_price_slope_1d as module

        original_path = module.TAIL_TRADING_DATA_PATH

        import gzip
        import json
        import tempfile

        with tempfile.NamedTemporaryFile(suffix=".json.gz", delete=False) as f:
            temp_path = Path(f.name)
            with gzip.open(temp_path, "wt", encoding="utf-8") as gz:
                json.dump({"data": mock_tail_df.to_dict("records")}, gz)

        module.TAIL_TRADING_DATA_PATH = temp_path

        try:
            result_df = calculate_tail_price_slope(factor_df)

            # 数据污染时应返回 NaN
            assert pd.isna(result_df["tail_price_slope"].values[0])

        finally:
            module.TAIL_TRADING_DATA_PATH = original_path
            temp_path.unlink()


class TestLoadTailTradingData:
    """数据加载测试"""

    def test_file_not_found(self):
        """文件不存在时抛出异常"""
        import factor_ic.ic_tail_price_slope_1d as module

        original_path = module.TAIL_TRADING_DATA_PATH
        module.TAIL_TRADING_DATA_PATH = Path("/nonexistent/path.json.gz")

        try:
            with pytest.raises(FileNotFoundError):
                load_tail_trading_data()
        finally:
            module.TAIL_TRADING_DATA_PATH = original_path
