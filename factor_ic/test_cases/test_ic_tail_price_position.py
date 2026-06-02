#!/usr/bin/env python3
"""
尾盘价格位置因子 IC 计算器测试用例

测试覆盖：
- 因子计算逻辑（calculate_tail_price_position）
- 边界处理（除零、数据不完整）
- 数据合并逻辑
"""

import pytest
import numpy as np
import pandas as pd
from pathlib import Path
import sys
import gzip
import json
import tempfile

# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from factor_ic.ic_tail_price_position import (
    calculate_tail_price_position,
    load_tail_trading_data,
    EPSILON,
)


class TestCalculateTailPricePosition:
    """因子计算函数测试"""

    def test_normal_calculation(self):
        """正常计算场景"""
        # 构造测试数据
        factor_df = pd.DataFrame({
            "date": ["2026-06-01", "2026-06-01"],
            "asset": ["000001", "000002"],
        })

        # Mock 尾盘数据
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

        # 临时替换尾盘数据路径
        import factor_ic.ic_tail_price_position as module
        original_path = module.TAIL_TRADING_DATA_PATH

        # 写入临时文件
        with tempfile.NamedTemporaryFile(suffix=".json.gz", delete=False) as f:
            temp_path = Path(f.name)
            with gzip.open(temp_path, "wt", encoding="utf-8") as gz:
                json.dump({"data": mock_tail_df.to_dict("records")}, gz)

        module.TAIL_TRADING_DATA_PATH = temp_path

        try:
            result_df = calculate_tail_price_position(factor_df)

            # 验证结果
            assert "tail_price_position" in result_df.columns
            assert result_df["tail_price_position"].notna().sum() == 2

            # 验证计算逻辑
            # asset 000001: 收盘价=11.0, tail_high=11.0, tail_low=10.0
            # 位置 = (11.0 - 10.0) / (11.0 - 10.0) = 1.0（收盘在最高位）
            expected_000001 = 1.0
            assert abs(
                result_df.loc[result_df["asset"] == "000001", "tail_price_position"].values[0]
                - expected_000001
            ) < 0.001

            # asset 000002: 收盘价=21.0, tail_high=21.0, tail_low=20.0
            # 位置 = (21.0 - 20.0) / (21.0 - 20.0) = 1.0（收盘在最高位）
            expected_000002 = 1.0
            assert abs(
                result_df.loc[result_df["asset"] == "000002", "tail_price_position"].values[0]
                - expected_000002
            ) < 0.001

        finally:
            module.TAIL_TRADING_DATA_PATH = original_path
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

        import factor_ic.ic_tail_price_position as module
        original_path = module.TAIL_TRADING_DATA_PATH

        with tempfile.NamedTemporaryFile(suffix=".json.gz", delete=False) as f:
            temp_path = Path(f.name)
            with gzip.open(temp_path, "wt", encoding="utf-8") as gz:
                json.dump({"data": mock_tail_df.to_dict("records")}, gz)

        module.TAIL_TRADING_DATA_PATH = temp_path

        try:
            result_df = calculate_tail_price_position(factor_df)

            # 收盘价=10.5（最后一个），位置 = (10.5 - 10.0) / (11.0 - 10.0) = 0.5
            expected = 0.5
            assert abs(result_df["tail_price_position"].values[0] - expected) < 0.001

        finally:
            module.TAIL_TRADING_DATA_PATH = original_path
            temp_path.unlink()

    def test_zero_range_protection(self):
        """除零防护：tail_high == tail_low"""
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

        import factor_ic.ic_tail_price_position as module
        original_path = module.TAIL_TRADING_DATA_PATH

        with tempfile.NamedTemporaryFile(suffix=".json.gz", delete=False) as f:
            temp_path = Path(f.name)
            with gzip.open(temp_path, "wt", encoding="utf-8") as gz:
                json.dump({"data": mock_tail_df.to_dict("records")}, gz)

        module.TAIL_TRADING_DATA_PATH = temp_path

        try:
            result_df = calculate_tail_price_position(factor_df)

            # tail_high == tail_low 时应返回 NaN
            assert pd.isna(result_df["tail_price_position"].values[0])

        finally:
            module.TAIL_TRADING_DATA_PATH = original_path
            temp_path.unlink()

    def test_incomplete_data_protection(self):
        """数据不完整防护：prices 数组长度不足"""
        factor_df = pd.DataFrame({
            "date": ["2026-06-01"],
            "asset": ["000001"],
        })

        mock_tail_df = pd.DataFrame({
            "date": ["2026-06-01"],
            "asset": ["000001"],
            "prices": [[10.0, 10.1]],  # 只有2个元素
            "tail_high": [11.0],
            "tail_low": [10.0],
        })

        import factor_ic.ic_tail_price_position as module
        original_path = module.TAIL_TRADING_DATA_PATH

        with tempfile.NamedTemporaryFile(suffix=".json.gz", delete=False) as f:
            temp_path = Path(f.name)
            with gzip.open(temp_path, "wt", encoding="utf-8") as gz:
                json.dump({"data": mock_tail_df.to_dict("records")}, gz)

        module.TAIL_TRADING_DATA_PATH = temp_path

        try:
            result_df = calculate_tail_price_position(factor_df)

            # 数据不完整时应返回 NaN
            assert pd.isna(result_df["tail_price_position"].values[0])

        finally:
            module.TAIL_TRADING_DATA_PATH = original_path
            temp_path.unlink()


class TestLoadTailTradingData:
    """数据加载测试"""

    def test_file_not_found(self):
        """文件不存在时抛出异常"""
        import factor_ic.ic_tail_price_position as module
        original_path = module.TAIL_TRADING_DATA_PATH
        module.TAIL_TRADING_DATA_PATH = Path("/nonexistent/path.json.gz")

        try:
            with pytest.raises(FileNotFoundError):
                load_tail_trading_data()
        finally:
            module.TAIL_TRADING_DATA_PATH = original_path


if __name__ == "__main__":
    pytest.main([__file__, "-v"])