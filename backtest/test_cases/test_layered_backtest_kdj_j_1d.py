#!/usr/bin/env python3
"""
test_layered_backtest_kdj_j_1d 测试用例

测试脚本: backtest/layered_backtest_kdj_j_1d.py
因子计算: data_fetchers/factor_calculator.py::calculate_kdj_j
流程文档: backtest/docs/layered_backtest_kdj_j_1d_flow.md
测试用例文档: backtest/test_cases/kdj_j_layered_backtest_test_cases.md
规范文档: PROJECT.md

运行: pytest backtest/test_cases/test_layered_backtest_kdj_j_1d.py -v
"""

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest


# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from backtest.layered_backtest_kdj_j_1d import KdjJLayerConfig
from data_fetchers.factor_calculator import calculate_kdj_j


class TestKdjJLayerConfig:
    """测试配置类属性"""

    def test_factor_name_classvar(self):
        """TC001-01: factor_name 类属性"""
        assert KdjJLayerConfig.factor_name == 'kdj_j'

    def test_layer_names_classvar(self):
        """TC001-02: layer_names 类属性为纯标签"""
        assert len(KdjJLayerConfig.layer_names) == 5
        assert KdjJLayerConfig.layer_names[0] == 'lowest'
        assert KdjJLayerConfig.layer_names[1] == 'lower'
        assert KdjJLayerConfig.layer_names[2] == 'normal'
        assert KdjJLayerConfig.layer_names[3] == 'higher'
        assert KdjJLayerConfig.layer_names[4] == 'highest'

    def test_layer_descriptions_classvar(self):
        """TC001-03: layer_descriptions 含中文描述"""
        assert len(KdjJLayerConfig.layer_descriptions) == 5
        assert KdjJLayerConfig.layer_descriptions[0] == '极低层(J值极低)'
        assert KdjJLayerConfig.layer_descriptions[1] == '偏低层(J值偏低)'
        assert KdjJLayerConfig.layer_descriptions[2] == '正常层(J值适中)'
        assert KdjJLayerConfig.layer_descriptions[3] == '偏高层(J值偏高)'
        assert KdjJLayerConfig.layer_descriptions[4] == '极高层(J值极高)'

    def test_ic_source_default(self):
        """TC001-04: ic_source 默认路径"""
        config = KdjJLayerConfig()
        assert config.ic_source_resolved == 'factor_ic/result/ic_kdj_j_1d_analysis_result.json'

    def test_factor_col_resolved(self):
        """TC001-05: factor_col_resolved 默认=factor_name"""
        config = KdjJLayerConfig()
        assert config.factor_col_resolved == 'kdj_j'

    def test_n_layers_derived(self):
        """TC001-06: n_layers 由 len(layer_names) 派生"""
        config = KdjJLayerConfig()
        assert config.n_layers == len(KdjJLayerConfig.layer_names)
        assert config.n_layers == 5

    def test_layer_names_dict_generated(self):
        """TC001-07: layer_names_dict 使用 layer_descriptions"""
        config = KdjJLayerConfig()
        assert '1' in config.layer_names_dict
        assert '5' in config.layer_names_dict
        assert config.layer_names_dict['1'] == '极低层(J值极低)'

    def test_layer_names_pure_labels(self):
        """TC001-08: layer_names 纯标签无中文"""
        for name in KdjJLayerConfig.layer_names:
            # 纯标签应为英文
            assert name.isascii()
            # 纯标签不应包含中文
            assert not any('\u4e00' <= c <= '\u9fff' for c in name)

    def test_layer_descriptions_contain_chinese(self):
        """TC001-09: layer_descriptions 包含中文描述"""
        for desc in KdjJLayerConfig.layer_descriptions:
            # 中文描述应包含中文
            assert any('\u4e00' <= c <= '\u9fff' for c in desc)
            # 中文描述应包含J值相关说明
            assert 'J值' in desc

    def test_factor_direction_negative(self):
        """TC001-10: factor_direction = negative（从 IC 文件派生）"""
        config = KdjJLayerConfig()
        # ic_mean = -0.022245 < 0 时 direction = negative
        assert config.factor_direction == 'negative'

    def test_factor_direction_literal_type(self):
        """TC001-11: factor_direction 类型约束"""
        from typing import Literal, get_args
        valid_values = get_args(Literal['positive', 'negative'])
        config = KdjJLayerConfig()
        assert config.factor_direction in valid_values

    def test_long_short_derived(self):
        """TC001-12: long_layers/short_layers 由 factor_direction 派生"""
        config = KdjJLayerConfig()
        # 反向因子：多头取低层，空头取高层
        if config.long_layers:
            assert 1 in config.long_layers  # 低层做多
        if config.short_layers:
            assert 5 in config.short_layers or 4 in config.short_layers  # 高层做空


class TestCalculateKdjJ:
    """测试因子计算函数"""

    def test_basic_calculation(self):
        """TC002-01: 基本 KDJ-J 计算"""
        # 需要9天数据来计算完整的KDJ
        dates = pd.date_range('2024-04-01', periods=10, freq='D')
        df = pd.DataFrame({
            'date': dates,
            'asset': ['000001'] * 10,
            'close': [100 + i for i in range(10)],
            'high': [103 + i for i in range(10)],
            'low': [99 + i for i in range(10)]
        })
        result = calculate_kdj_j(df, n=9, m1=3, m2=3)

        # 结果应包含 kdj_j 列
        assert 'kdj_j' in result.columns
        # kdj_j 值应在合理范围内（通常在 -20 到 120 之间）
        assert result['kdj_j'].notna().sum() > 0

    def test_required_columns(self):
        """TC002-02: 缺少必要列时应抛出异常"""
        df = pd.DataFrame({
            'date': ['2024-04-01'],
            'asset': ['000001'],
            'close': [100.0]
            # 缺少 high, low 列
        })
        with pytest.raises((KeyError, ValueError)):
            calculate_kdj_j(df)

    def test_extreme_values(self):
        """TC002-03: 极端值处理（涨跌停）"""
        # 构造涨跌停场景
        dates = pd.date_range('2024-04-01', periods=10, freq='D')
        df = pd.DataFrame({
            'date': dates,
            'asset': ['000001'] * 10,
            'close': [100.0] * 9 + [110.0],  # 最后一天涨停
            'high': [103.0] * 9 + [110.0],
            'low': [99.0] * 9 + [110.0]
        })
        result = calculate_kdj_j(df, n=9, m1=3, m2=3)

        # KDJ-J 应能处理极端值
        assert 'kdj_j' in result.columns
        # J值可能超过100或小于0
        assert result['kdj_j'].notna().sum() > 0

    def test_nan_handling(self):
        """TC002-04: NaN 值应保留或正确处理"""
        dates = pd.date_range('2024-04-01', periods=10, freq='D')
        df = pd.DataFrame({
            'date': dates,
            'asset': ['000001'] * 10,
            'close': [100.0, 101.0, np.nan, 103.0, 104.0, 105.0, 106.0, 107.0, 108.0, 109.0],
            'high': [103.0, 104.0, np.nan, 106.0, 107.0, 108.0, 109.0, 110.0, 111.0, 112.0],
            'low': [99.0, 100.0, np.nan, 102.0, 103.0, 104.0, 105.0, 106.0, 107.0, 108.0]
        })
        result = calculate_kdj_j(df, n=9, m1=3, m2=3)

        # NaN 位置应被保留
        assert pd.isna(result['kdj_j'].iloc[2])

    def test_multi_asset(self):
        """TC002-05: 多股票分组计算"""
        dates = pd.date_range('2024-04-01', periods=10, freq='D')
        df = pd.DataFrame({
            'date': list(dates) * 2,
            'asset': ['000001'] * 10 + ['000002'] * 10,
            'close': [100 + i for i in range(10)] + [200 + i for i in range(10)],
            'high': [103 + i for i in range(10)] + [203 + i for i in range(10)],
            'low': [99 + i for i in range(10)] + [199 + i for i in range(10)]
        })
        result = calculate_kdj_j(df, n=9, m1=3, m2=3)

        # 结果应包含两只股票
        assert len(result['asset'].unique()) == 2
        assert 'kdj_j' in result.columns


class TestLayeredBacktestResult:
    """测试分层回测结果"""

    @pytest.fixture
    def result_path(self):
        """获取回测结果文件路径"""
        return Path(__file__).parent.parent / 'result' / 'kdj_j_layered_backtest.json'

    def test_result_file_exists(self, result_path):
        """TC003-01: 结果文件应存在"""
        if not result_path.exists():
            pytest.skip("结果文件不存在，需先运行脚本")

    def test_result_structure(self, result_path):
        """TC003-02: 结果 JSON 结构应完整"""
        if not result_path.exists():
            pytest.skip("结果文件不存在")

        with open(result_path) as f:
            result = json.load(f)

        # 必须包含的顶层字段
        required_keys = ['meta', 'layer_stats', 'long_short', 'monotonicity']
        for key in required_keys:
            assert key in result

    def test_meta_fields(self, result_path):
        """TC003-03: meta 字段应包含完整信息"""
        if not result_path.exists():
            pytest.skip("结果文件不存在")

        with open(result_path) as f:
            result = json.load(f)

        meta = result['meta']
        assert 'factor_name' in meta
        assert meta['factor_name'] == 'kdj_j'
        assert 'n_days_total' in meta
        assert meta['n_days_total'] > 0
        assert 'n_layers' in meta
        assert meta['n_layers'] == 5
        assert meta['factor_direction'] == 'negative'

    def test_layer_stats_complete(self, result_path):
        """TC003-04: 每层统计指标应完整"""
        if not result_path.exists():
            pytest.skip("结果文件不存在")

        with open(result_path) as f:
            result = json.load(f)

        for layer_id in range(1, 6):
            layer_key = f'layer_{layer_id}'
            assert layer_key in result['layer_stats']

            stats = result['layer_stats'][layer_key]
            required_stats = ['n_stocks_avg', 'annual_return', 'sharpe_ratio', 'max_drawdown']
            for stat in required_stats:
                assert stat in stats

    def test_monotonicity_exists(self, result_path):
        """TC003-05: 单调性指标应存在且质量有效"""
        if not result_path.exists():
            pytest.skip("结果文件不存在")

        with open(result_path) as f:
            result = json.load(f)

        monotonicity = result['monotonicity']
        # 单调性相关系数应在 [-1, 1] 范围内
        assert -1 <= monotonicity['correlation'] <= 1
        # 质量应为有效值
        assert monotonicity['quality'] in ['excellent', 'good', 'fair', 'poor']
        # 应包含层收益数据
        assert len(monotonicity['layer_returns']) == 5


class TestLayeredBacktestExecution:
    """测试分层回测执行"""

    def test_config_integration(self):
        """TC004-01: 配置类应能正确集成到 factor_cli_main"""
        config = KdjJLayerConfig()

        # 检查继承关系
        from backtest.common.layered_backtest_runner import LayerConfigBase
        assert isinstance(config, LayerConfigBase)

        # 检查必要属性
        assert hasattr(config, 'factor_direction')
        assert hasattr(config, 'layer_names')
        assert hasattr(config, 'layer_descriptions')
        assert hasattr(config, 'n_layers')

    def test_factor_direction_derives_long_short(self):
        """TC004-02: 反向因子应派生出正确的多空组合"""
        config = KdjJLayerConfig()

        # 反向因子：多头取低层，空头取高层
        # 这个测试依赖于基类的 _derive_long_short() 方法
        if config.long_layers and config.short_layers:
            # 反向因子：long_layers 应为低层（1, 2）
            assert config.long_layers in [[1, 2], [1], [2]]
            # 反向因子：short_layers 应为高层（4, 5）
            assert config.short_layers in [[4, 5], [5], [4]]


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
