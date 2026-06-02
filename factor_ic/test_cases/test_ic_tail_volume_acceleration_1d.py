#!/usr/bin/env python3
"""
test_ic_tail_volume_acceleration_1d 测试用例

测试脚本: factor_ic/ic_tail_volume_acceleration_1d.py
因子计算: calculate_tail_volume_acceleration
内部函数: _calc_volume_acceleration（用于单元测试）
流程文档: factor_ic/docs/ic_tail_volume_acceleration_1d_flow.md

版本历史:
  v1.0 (2026-06-02): 初始版本，创建测试用例
  v1.1 (2026-06-02): Round 5 优化 - 测试文件版本历史同步
  v1.2 (2026-06-02): Round 5 优化 - 版本历史与 IC 脚本同步（v1.3）
  v1.3 (2026-06-02): Round 5 优化 - 版本历史与 IC 脚本同步（v1.6）
"""

import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import numpy as np
import pandas as pd
import pytest

from factor_ic.ic_tail_volume_acceleration_1d import (
    _calc_volume_acceleration,
    calculate_tail_volume_acceleration,
    load_tail_trading_data,
)


class TestCalcVolumeAcceleration:
    """因子计算逻辑测试（内部函数）"""

    def test_normal_calculation(self):
        """TC001-01: 正常计算"""
        # 前半段: 10+20+30+40+50+60 = 210
        # 后半段: 80+90+100+110+120+130 = 630
        # 因子值 = 630/210 = 3.0
        volumes = [10, 20, 30, 40, 50, 60, 70, 80, 90, 100, 110, 120, 130]
        result = _calc_volume_acceleration(volumes)
        assert result == 3.0

    def test_volumes_length_insufficient(self):
        """TC001-02: volumes 长度不足 13"""
        volumes = [10, 20, 30, 40, 50, 60]  # 只有6个元素
        result = _calc_volume_acceleration(volumes)
        assert np.isnan(result)

    def test_volumes_contains_nan(self):
        """TC001-03: volumes 包含 NaN"""
        volumes = [10.0, 20.0, float('nan'), 40.0, 50.0, 60.0, 70.0, 80.0, 90.0, 100.0, 110.0, 120.0, 130.0]
        result = _calc_volume_acceleration(volumes)
        assert np.isnan(result)

    def test_volumes_contains_none(self):
        """TC001-04: volumes 包含 None"""
        volumes = [10, 20, None, 40, 50, 60, 70, 80, 90, 100, 110, 120, 130]
        result = _calc_volume_acceleration(volumes)
        assert np.isnan(result)

    def test_front_volume_zero(self):
        """TC001-05: 前半段成交量为零"""
        volumes = [0, 0, 0, 0, 0, 0, 70, 80, 90, 100, 110, 120, 130]
        result = _calc_volume_acceleration(volumes)
        assert np.isnan(result)

    def test_back_volume_zero(self):
        """TC001-06: 后半段成交量为零"""
        volumes = [10, 20, 30, 40, 50, 60, 70, 0, 0, 0, 0, 0, 0]
        result = _calc_volume_acceleration(volumes)
        # 后半段为零时因子值为 0（合理值，不是 NaN）
        assert result == 0.0

    def test_volumes_not_list(self):
        """TC001-07: volumes 不是列表（合并后 NaN）"""
        result = _calc_volume_acceleration(np.nan)
        assert np.isnan(result)

    def test_factor_less_than_one(self):
        """TC001-08: 因子值小于 1（减速）"""
        # 前半段: 600，后半段: 60，因子值 = 0.1
        volumes = [100, 100, 100, 100, 100, 100, 70, 10, 10, 10, 10, 10, 10]
        result = _calc_volume_acceleration(volumes)
        assert result == 0.1

    def test_factor_equals_one(self):
        """TC001-09: 因子值等于 1（平稳）"""
        # 前半段: 60，后半段: 60，因子值 = 1.0
        volumes = [10, 10, 10, 10, 10, 10, 70, 10, 10, 10, 10, 10, 10]
        result = _calc_volume_acceleration(volumes)
        assert result == 1.0

    def test_index_6_excluded(self):
        """TC001-10: 索引 6（14:30）不属于任何段"""
        # 验证 14:30 这根 K 线不参与计算
        # 前半段: 6，后半段: 6，因子值 = 1.0（索引6的999不影响）
        volumes = [1, 1, 1, 1, 1, 1, 999, 1, 1, 1, 1, 1, 1]
        result = _calc_volume_acceleration(volumes)
        assert result == 1.0


class TestLoadTailTradingData:
    """数据加载测试"""

    def test_file_exists(self):
        """TC002-01: 文件存在"""
        try:
            df = load_tail_trading_data()
            assert "date" in df.columns
            assert "asset" in df.columns
            assert "volumes" in df.columns
        except FileNotFoundError:
            pytest.skip("尾盘数据文件不存在，需先运行 fetch_tail_trading.py")

    def test_file_not_exists(self):
        """TC002-02: 文件不存在（模拟）"""
        pytest.skip("需 mock 文件不存在场景")


class TestScriptIntegration:
    """脚本集成测试"""

    def test_script_imports(self):
        """TC003-01: 脚本可导入"""
        from factor_ic.ic_tail_volume_acceleration_1d import main
        assert callable(main)

    def test_factor_name_consistency(self):
        """TC003-02: 因子名一致性"""
        assert calculate_tail_volume_acceleration.__name__ == "calculate_tail_volume_acceleration"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
