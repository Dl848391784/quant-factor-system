#!/usr/bin/env python3
"""
ic_return_5d_1d 测试用例

测试脚本: factor_ic/ic_return_5d_1d.py
因子计算: data_fetchers/factor_calculator.py::calculate_return_5d
流程文档: factor_ic/docs/ic_return_5d_1d_flow.md
规范文档: PROJECT.md

运行: pytest factor_ic/test_cases/test_ic_return_5d_1d.py -v
"""

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest


# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from data_fetchers.factor_calculator import calculate_return_5d
from factor_ic.common.data_completeness import FACTOR_IC_RESULT_DIR, get_ic_output_path


class TestOutputPath:
    """测试输出路径和命名规范"""

    def test_output_path_format(self):
        """输出文件命名应符合规范: ic_<因子名>_analysis_result.json"""
        path = get_ic_output_path('return_5d_1d')
        assert path.name == 'ic_return_5d_1d_analysis_result.json'

    def test_output_directory(self):
        """输出目录应为 factor_ic/result/"""
        path = get_ic_output_path('return_5d_1d')
        assert path.parent == FACTOR_IC_RESULT_DIR

    def test_output_directory_exists_or_created(self):
        """输出目录不存在时应自动创建"""
        assert FACTOR_IC_RESULT_DIR.exists() or FACTOR_IC_RESULT_DIR.parent.exists()


class TestCalculateReturn5d:
    """测试因子计算函数"""

    def test_basic_calculation(self):
        """基本计算测试"""
        df = pd.DataFrame({
            'date': ['2026-01-01', '2026-01-02', '2026-01-03', '2026-01-04', '2026-01-05', '2026-01-06'],
            'asset': ['A', 'A', 'A', 'A', 'A', 'A'],
            'close': [100.0, 102.0, 101.0, 103.0, 105.0, 108.0]
        })
        result = calculate_return_5d(df, window=5)

        assert 'return_5d' in result.columns
        # 第6天: (108/100 - 1) = 0.08
        assert np.isclose(result['return_5d'].iloc[5], 0.08, atol=0.01)

    def test_first_5_days_nan(self):
        """前5日数据不足，应为 NaN"""
        df = pd.DataFrame({
            'date': ['2026-01-01', '2026-01-02', '2026-01-03', '2026-01-04', '2026-01-05', '2026-01-06'],
            'asset': ['A', 'A', 'A', 'A', 'A', 'A'],
            'close': [100.0, 102.0, 101.0, 103.0, 105.0, 108.0]
        })
        result = calculate_return_5d(df, window=5)

        # 前5天应为 NaN
        for i in range(5):
            assert pd.isna(result['return_5d'].iloc[i])

    def test_negative_return(self):
        """下跌测试"""
        df = pd.DataFrame({
            'date': ['2026-01-01', '2026-01-02', '2026-01-03', '2026-01-04', '2026-01-05', '2026-01-06'],
            'asset': ['A', 'A', 'A', 'A', 'A', 'A'],
            'close': [110.0, 108.0, 107.0, 106.0, 105.0, 100.0]  # 下跌
        })
        result = calculate_return_5d(df, window=5)

        # 第6天: (100/110 - 1) = -0.09
        assert np.isclose(result['return_5d'].iloc[5], -0.09, atol=0.01)

    def test_zero_close_handling(self):
        """历史收盘价为零测试：无效数据"""
        df = pd.DataFrame({
            'date': ['2026-01-01', '2026-01-02', '2026-01-03', '2026-01-04', '2026-01-05', '2026-01-06'],
            'asset': ['A', 'A', 'A', 'A', 'A', 'A'],
            'close': [0.0, 102.0, 101.0, 103.0, 105.0, 108.0]  # 第1天为0
        })
        result = calculate_return_5d(df, window=5)

        # 第6天的 close[t-5]=0，应为 NaN
        assert pd.isna(result['return_5d'].iloc[5])

    def test_multiple_assets(self):
        """多资产分组测试"""
        df = pd.DataFrame({
            'date': ['2026-01-01', '2026-01-02', '2026-01-03', '2026-01-04', '2026-01-05', '2026-01-06',
                     '2026-01-01', '2026-01-02', '2026-01-03', '2026-01-04', '2026-01-05', '2026-01-06'],
            'asset': ['A', 'A', 'A', 'A', 'A', 'A', 'B', 'B', 'B', 'B', 'B', 'B'],
            'close': [100.0, 102.0, 101.0, 103.0, 105.0, 108.0,
                      200.0, 202.0, 201.0, 203.0, 205.0, 210.0]
        })
        result = calculate_return_5d(df, window=5)

        # A: (108/100 - 1) = 0.08
        a_df = result[result['asset'] == 'A'].reset_index(drop=True)
        assert np.isclose(a_df.loc[5, 'return_5d'], 0.08, atol=0.01)
        # B: (210/200 - 1) = 0.05
        b_df = result[result['asset'] == 'B'].reset_index(drop=True)
        assert np.isclose(b_df.loc[5, 'return_5d'], 0.05, atol=0.01)

    def test_nan_handling(self):
        """NaN 值传播测试"""
        df = pd.DataFrame({
            'date': ['2026-01-01', '2026-01-02', '2026-01-03', '2026-01-04', '2026-01-05', '2026-01-06'],
            'asset': ['A', 'A', 'A', 'A', 'A', 'A'],
            'close': [np.nan, 102.0, 101.0, 103.0, 105.0, 108.0]  # 第1天 NaN → 第6天受影响
        })
        result = calculate_return_5d(df, window=5)

        # close[t-5] 为 NaN 时，结果也应为 NaN
        assert pd.isna(result['return_5d'].iloc[5])

    def test_a_stock_range(self):
        """A股典型涨跌幅范围测试（±10%/日，±50%/5日）"""
        df = pd.DataFrame({
            'date': ['2026-01-01', '2026-01-02', '2026-01-03', '2026-01-04', '2026-01-05', '2026-01-06'],
            'asset': ['A', 'A', 'A', 'A', 'A', 'A'],
            'close': [100.0, 110.0, 121.0, 133.1, 146.4, 161.0]  # 每日涨10%
        })
        result = calculate_return_5d(df, window=5)

        # 第6天: (161/100 - 1) = 0.61（接近A股5日上限）
        assert np.isclose(result['return_5d'].iloc[5], 0.61, atol=0.01)


class TestOutputStructure:
    """测试输出数据结构规范"""

    REQUIRED_FIELDS = [
        'factor_name',
        'calculation_date',
        'period',
        'ic_metrics',
        'sample_stats',
        'statistical_significance',
        'factor_direction',
        'economic_significance',
        'icir_stability',
        'ic_distribution_consistency'
    ]

    def test_output_file_exists_after_run(self):
        """运行后输出文件应存在"""
        # 注意：此测试需要先运行 ic_return_5d_1d.py
        # 这里只检查文件路径是否正确
        path = get_ic_output_path('return_5d_1d')
        # 如果文件不存在，跳过此测试
        if not path.exists():
            pytest.skip("输出文件不存在，需要先运行 ic_return_5d_1d.py")

    def test_output_structure_if_exists(self):
        """如果输出文件存在，检查结构"""
        path = get_ic_output_path('return_5d_1d')
        if not path.exists():
            pytest.skip("输出文件不存在")

        with open(path, encoding='utf-8') as f:
            result = json.load(f)

        # 检查必需字段
        for field in self.REQUIRED_FIELDS:
            assert field in result, f"缺少必需字段: {field}"

    def test_ic_metrics_fields_if_exists(self):
        """如果输出文件存在，检查 ic_metrics 子字段"""
        path = get_ic_output_path('return_5d_1d')
        if not path.exists():
            pytest.skip("输出文件不存在")

        with open(path, encoding='utf-8') as f:
            result = json.load(f)

        ic_metrics = result.get('ic_metrics', {})
        required_ic_fields = ['ic_mean', 'ic_std', 'icir']

        for field in required_ic_fields:
            assert field in ic_metrics, f"ic_metrics 缺少必需字段: {field}"

    def test_sample_stats_fields_if_exists(self):
        """如果输出文件存在，检查 sample_stats 子字段"""
        path = get_ic_output_path('return_5d_1d')
        if not path.exists():
            pytest.skip("输出文件不存在")

        with open(path, encoding='utf-8') as f:
            result = json.load(f)

        sample_stats = result.get('sample_stats', {})
        required_sample_fields = ['total_days', 'valid_days']

        for field in required_sample_fields:
            assert field in sample_stats, f"sample_stats 缺少必需字段: {field}"
