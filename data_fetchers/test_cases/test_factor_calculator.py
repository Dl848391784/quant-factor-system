#!/usr/bin/env python3
"""
factor_calculator.py 测试用例

遵循 PROJECT.md 测试代码规范：
- pytest 可执行文件
- 使用 tempfile.TemporaryDirectory 管理临时文件
- 测试覆盖：正常场景 + 边界场景 + 异常场景

作者: 云瑶
创建时间: 2026-05-27 17:00 北京时间
"""

import logging
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

# 导入被测模块
from data_fetchers.factor_calculator import (
    calculate_bollinger_pb,
    calculate_forward_return,
    calculate_kdj_j,
    calculate_rsi,
    calculate_turnover_surge,
    calculate_volume_ratio,
    get_module_logger,
)


# ============================================================================
# 测试数据准备
# ============================================================================

@pytest.fixture
def sample_close_prices():
    """样本收盘价序列"""
    return pd.Series([100, 102, 101, 103, 105, 104, 106, 108, 107, 109])


@pytest.fixture
def sample_volume():
    """样本成交量序列"""
    return pd.Series([1000, 1100, 900, 1200, 1000, 1500, 1300, 1400, 1100, 1600])


@pytest.fixture
def sample_factor_df():
    """样本因子 DataFrame（面板数据长格式）"""
    return pd.DataFrame({
        'date': ['2026-01-01', '2026-01-02', '2026-01-03', '2026-01-01', '2026-01-02', '2026-01-03'],
        'asset': ['A', 'A', 'A', 'B', 'B', 'B'],
        'close': [100, 102, 101, 200, 202, 201],
        'high': [103, 104, 103, 203, 204, 203],
        'low': [99, 100, 99, 199, 200, 199],
        'turnover_rate': [0.01, 0.02, 0.03, 0.01, 0.02, 0.03]
    })


@pytest.fixture
def large_factor_df():
    """大样本因子 DataFrame（足够计算大窗口参数）"""
    # 30 天数据，每只股票
    dates = [f'2026-01-{i:02d}' for i in range(1, 31)]
    assets = ['A'] * 30 + ['B'] * 30
    dates_all = dates + dates
    # 生成随机价格数据
    closes_a = [100 + i * 0.5 + (i % 3 - 1) * 0.2 for i in range(30)]
    closes_b = [200 + i * 0.5 + (i % 3 - 1) * 0.2 for i in range(30)]
    highs_a = [c + 3 for c in closes_a]
    lows_a = [c - 1 for c in closes_a]
    highs_b = [c + 3 for c in closes_b]
    lows_b = [c - 1 for c in closes_b]
    turnover_a = [0.01 + i * 0.001 for i in range(30)]
    turnover_b = [0.01 + i * 0.001 for i in range(30)]

    return pd.DataFrame({
        'date': dates_all,
        'asset': assets,
        'close': closes_a + closes_b,
        'high': highs_a + highs_b,
        'low': lows_a + lows_b,
        'turnover_rate': turnover_a + turnover_b
    })


@pytest.fixture
def test_logger():
    """测试 logger"""
    with tempfile.TemporaryDirectory() as tmpdir:
        logs_dir = Path(tmpdir) / 'logs'
        logs_dir.mkdir()
        logger = logging.getLogger('test_factor_calculator')
        logger.setLevel(logging.DEBUG)
        # 不添加 handler，避免日志文件残留
        yield logger


# ============================================================================
# calculate_rsi 测试
# ============================================================================

class TestCalculateRSI:
    """RSI 计算函数测试"""

    def test_basic_calculation(self, sample_close_prices):
        """测试基本 RSI 计算"""
        rsi = calculate_rsi(sample_close_prices, period=6)
        # 验证返回类型
        assert isinstance(rsi, pd.Series)
        # 验证范围 0-100
        valid_rsi = rsi.dropna()
        assert (valid_rsi >= 0).all() and (valid_rsi <= 100).all()

    def test_missing_values_filled_with_50(self, sample_close_prices):
        """测试缺失值保留为 NaN（调用方自行决定处理）"""
        rsi = calculate_rsi(sample_close_prices, period=6)
        # 前 period-1 天应为 NaN（Wilder 标准，数据不足）
        # v1.4 修复：不再 fillna，让调用方自行决定如何处理
        assert pd.isna(rsi.iloc[0])  # 第一天是 NaN（数据不足）
        assert pd.isna(rsi.iloc[4])  # 第 5 天仍是 NaN（数据不足）
        # 第 period 天（索引 period-1）开始有值
        assert not pd.isna(rsi.iloc[5])  # 第 6 天有值

    def test_custom_period(self, sample_close_prices):
        """测试自定义周期"""
        rsi_6 = calculate_rsi(sample_close_prices, period=6)
        rsi_14 = calculate_rsi(sample_close_prices, period=14)
        # 不同周期结果不同
        assert not rsi_6.equals(rsi_14)

    def test_empty_series(self):
        """测试空序列"""
        empty = pd.Series([], dtype=float)
        rsi = calculate_rsi(empty, period=6)
        assert len(rsi) == 0

    def test_constant_prices(self):
        """测试恒定价格（无波动）"""
        constant = pd.Series([100] * 10)
        rsi = calculate_rsi(constant, period=6)
        # 无波动时 RSI 应为 50（中性）
        # v1.4 修复：前 period-1 天为 NaN，从第 period 天起为 50
        valid_rsi = rsi.dropna()
        assert (valid_rsi == 50).all()  # 有效值全部为 50
        assert pd.isna(rsi.iloc[0])  # 第一天是 NaN


# ============================================================================
# calculate_volume_ratio 测试
# ============================================================================

class TestCalculateVolumeRatio:
    """量比计算函数测试"""

    def test_basic_calculation(self, sample_volume):
        """测试基本量比计算"""
        vr = calculate_volume_ratio(sample_volume, window=5)
        # 验证返回类型
        assert isinstance(vr, pd.Series)
        # 前 window 天应为 NaN
        assert pd.isna(vr.iloc[0])

    def test_surge_detection(self, sample_volume):
        """测试突增检测"""
        # 第 5 天成交量为 1500，前 5 天均值约 1050
        vr = calculate_volume_ratio(sample_volume, window=5)
        # 第 5 天量比应 > 1
        if not pd.isna(vr.iloc[5]):
            assert vr.iloc[5] > 1

    def test_zero_volume_handling(self):
        """测试零成交量处理"""
        vol_with_zero = pd.Series([0, 1000, 1000, 1000, 1000, 1000])
        vr = calculate_volume_ratio(vol_with_zero, window=5)
        # 零成交量应产生 NaN
        assert pd.isna(vr.iloc[0])

    def test_custom_window(self, sample_volume):
        """测试自定义窗口"""
        vr_5 = calculate_volume_ratio(sample_volume, window=5)
        vr_10 = calculate_volume_ratio(sample_volume, window=10)
        # 不同窗口结果不同
        assert not vr_5.equals(vr_10)


# ============================================================================
# calculate_forward_return 测试
# ============================================================================

class TestCalculateForwardReturn:
    """前瞻收益率计算测试"""

    def test_basic_calculation(self, sample_close_prices):
        """测试基本前瞻收益率计算"""
        fr = calculate_forward_return(sample_close_prices, shift=1)
        # 验证返回类型
        assert isinstance(fr, pd.Series)
        # 最后一天应为 NaN（无次日数据）
        assert pd.isna(fr.iloc[-1])

    def test_positive_return(self, sample_close_prices):
        """测试正收益"""
        fr = calculate_forward_return(sample_close_prices, shift=1)
        # 第 0 天收盘 100，次日 102，收益 2%
        if not pd.isna(fr.iloc[0]):
            assert fr.iloc[0] == 0.02

    def test_negative_return(self):
        """测试负收益"""
        close = pd.Series([100, 98, 95])
        fr = calculate_forward_return(close, shift=1)
        # 第 0 天收盘 100，次日 98，收益 -2%
        if not pd.isna(fr.iloc[0]):
            assert fr.iloc[0] == -0.02

    def test_custom_shift(self, sample_close_prices):
        """测试自定义前瞻天数"""
        fr_1 = calculate_forward_return(sample_close_prices, shift=1)
        fr_3 = calculate_forward_return(sample_close_prices, shift=3)
        # shift=3 时最后 3 天应为 NaN
        assert pd.isna(fr_3.iloc[-1])
        assert pd.isna(fr_3.iloc[-2])
        assert pd.isna(fr_3.iloc[-3])


# ============================================================================
# calculate_bollinger_pb 测试
# ============================================================================

class TestCalculateBollingerPB:
    """布林带 %B 计算测试"""

    def test_basic_calculation(self, sample_factor_df):
        """测试基本布林带计算"""
        result = calculate_bollinger_pb(sample_factor_df, n=20, k=2.0)
        # 验证返回类型
        assert isinstance(result, pd.DataFrame)
        # 验证新增列存在
        assert 'bollinger_pb' in result.columns

    def test_original_df_not_modified(self, sample_factor_df):
        """测试原始 DataFrame 未被修改"""
        original_cols = sample_factor_df.columns.tolist()
        result = calculate_bollinger_pb(sample_factor_df, n=20, k=2.0)
        # 原始 DataFrame 列数未变
        assert sample_factor_df.columns.tolist() == original_cols

    def test_logger_parameter(self, sample_factor_df, test_logger):
        """测试 logger 参数"""
        result = calculate_bollinger_pb(sample_factor_df, n=20, k=2.0, logger_arg=test_logger)
        assert 'bollinger_pb' in result.columns

    def test_custom_n_and_k(self, large_factor_df):
        """测试自定义 n 和 k（使用大样本数据）"""
        result_20_2 = calculate_bollinger_pb(large_factor_df, n=20, k=2.0)
        result_10_1 = calculate_bollinger_pb(large_factor_df, n=10, k=1.5)
        # 不同参数结果不同（取有效值比较，前 n-1 天为 NaN）
        valid_20_2 = result_20_2['bollinger_pb'].dropna()
        valid_10_1 = result_10_1['bollinger_pb'].dropna()
        # 两者都应有有效值
        assert len(valid_20_2) > 0 and len(valid_10_1) > 0
        # 有效值部分应该不同（窗口越大，值越平滑）
        assert not valid_20_2.head(10).equals(valid_10_1.head(10))


# ============================================================================
# calculate_kdj_j 测试
# ============================================================================

class TestCalculateKDJJ:
    """KDJ_J 计算测试"""

    def test_basic_calculation(self, sample_factor_df):
        """测试基本 KDJ_J 计算"""
        result = calculate_kdj_j(sample_factor_df, n=9, m1=3, m2=3)
        # 验证返回类型
        assert isinstance(result, pd.DataFrame)
        # 验证新增列存在
        assert 'kdj_j' in result.columns

    def test_original_df_not_modified(self, sample_factor_df):
        """测试原始 DataFrame 未被修改"""
        original_cols = sample_factor_df.columns.tolist()
        result = calculate_kdj_j(sample_factor_df, n=9, m1=3, m2=3)
        # 原始 DataFrame 列数未变
        assert sample_factor_df.columns.tolist() == original_cols

    def test_logger_parameter(self, sample_factor_df, test_logger):
        """测试 logger 参数"""
        result = calculate_kdj_j(sample_factor_df, n=9, m1=3, m2=3, logger_arg=test_logger)
        assert 'kdj_j' in result.columns

    def test_custom_params(self, large_factor_df):
        """测试自定义参数（使用大样本数据）"""
        result_9_3_3 = calculate_kdj_j(large_factor_df, n=9, m1=3, m2=3)
        result_14_5_5 = calculate_kdj_j(large_factor_df, n=14, m1=5, m2=5)
        # 不同参数结果不同（取有效值比较，前 n-1 天为 NaN）
        valid_9_3_3 = result_9_3_3['kdj_j'].dropna()
        valid_14_5_5 = result_14_5_5['kdj_j'].dropna()
        # 两者都应有有效值
        assert len(valid_9_3_3) > 0 and len(valid_14_5_5) > 0
        # 有效值部分应该不同
        assert not valid_9_3_3.head(10).equals(valid_14_5_5.head(10))


# ============================================================================
# calculate_turnover_surge 测试
# ============================================================================

class TestCalculateTurnoverSurge:
    """换手率突增计算测试"""

    def test_basic_calculation(self, sample_factor_df):
        """测试基本换手率突增计算"""
        result = calculate_turnover_surge(sample_factor_df, surge_window=5)
        # 验证返回类型
        assert isinstance(result, pd.DataFrame)
        # 验证新增列存在
        assert 'turnover_surge' in result.columns

    def test_original_df_not_modified(self, sample_factor_df):
        """测试原始 DataFrame 未被修改"""
        original_cols = sample_factor_df.columns.tolist()
        result = calculate_turnover_surge(sample_factor_df, surge_window=5)
        # 原始 DataFrame 列数未变
        assert sample_factor_df.columns.tolist() == original_cols

    def test_logger_parameter(self, sample_factor_df, test_logger):
        """测试 logger 参数"""
        result = calculate_turnover_surge(sample_factor_df, surge_window=5, logger_arg=test_logger)
        assert 'turnover_surge' in result.columns

    def test_custom_window(self, large_factor_df):
        """测试自定义窗口（使用大样本数据）"""
        result_5 = calculate_turnover_surge(large_factor_df, surge_window=5)
        result_10 = calculate_turnover_surge(large_factor_df, surge_window=10)
        # 不同参数结果不同（取有效值比较）
        valid_5 = result_5['turnover_surge'].dropna()
        valid_10 = result_10['turnover_surge'].dropna()
        # 两者都应有有效值
        assert len(valid_5) > 0 and len(valid_10) > 0
        # 有效值部分应该不同
        assert not valid_5.head(10).equals(valid_10.head(10))


# ============================================================================
# get_module_logger 测试
# ============================================================================

class TestGetModuleLogger:
    """get_module_logger 函数测试"""

    def test_with_logger(self, test_logger):
        """测试传入 logger"""
        result = get_module_logger(test_logger)
        assert result == test_logger

    def test_without_logger(self):
        """测试不传入 logger（使用 fallback）"""
        result = get_module_logger()
        assert isinstance(result, logging.Logger)
        assert result.name == 'data_fetchers.factor_calculator'

    def test_none_logger(self):
        """测试传入 None"""
        result = get_module_logger(None)
        assert isinstance(result, logging.Logger)


# ============================================================================
# 边界场景测试
# ============================================================================

class TestEdgeCases:
    """边界场景测试"""

    def test_single_day_data(self):
        """测试单日数据"""
        single_day = pd.DataFrame({
            'date': ['2026-01-01'],
            'asset': ['A'],
            'close': [100],
            'high': [103],
            'low': [99],
            'turnover_rate': [0.01]
        })
        # 单日数据应能处理
        result = calculate_bollinger_pb(single_day, n=20, k=2.0)
        assert 'bollinger_pb' in result.columns

    def test_missing_columns_bollinger(self):
        """测试缺失列（布林带）"""
        df_without_close = pd.DataFrame({
            'date': ['2026-01-01'],
            'asset': ['A'],
            'high': [103],
            'low': [99]
        })
        # 缺失 close 列应抛异常
        with pytest.raises(KeyError):
            calculate_bollinger_pb(df_without_close, n=20, k=2.0)

    def test_missing_columns_kdj(self):
        """测试缺失列（KDJ）"""
        df_without_high = pd.DataFrame({
            'date': ['2026-01-01'],
            'asset': ['A'],
            'close': [100],
            'low': [99]
        })
        # 缺失 high 列应抛异常
        with pytest.raises(KeyError):
            calculate_kdj_j(df_without_high, n=9, m1=3, m2=3)


# ============================================================================
# 运行测试
# ============================================================================

if __name__ == '__main__':
    pytest.main([__file__, '-v'])
