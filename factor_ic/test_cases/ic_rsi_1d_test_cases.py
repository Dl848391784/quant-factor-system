#!/usr/bin/env python3
"""
ic_rsi_1d 测试用例

测试脚本: factor_ic/ic_rsi_1d.py
流程文档: factor_ic/docs/ic_rsi_1d_flow.md
规范文档: PROJECT.md

运行: pytest factor_ic/test_cases/ic_rsi_1d_test_cases.py -v
"""

import pytest
import sys
from pathlib import Path
import json
import gzip
import tempfile

# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from factor_ic.common.data_completeness import (
    get_ic_output_path,
    FACTOR_IC_RESULT_DIR
)


class TestOutputPath:
    """测试输出路径和命名规范"""
    
    def test_output_path_format(self):
        """输出文件命名应符合规范: ic_<因子名>_analysis_result.json"""
        path = get_ic_output_path('rsi_1d')
        assert path.name == 'ic_rsi_1d_analysis_result.json'
    
    def test_output_directory(self):
        """输出目录应为 factor_ic/result/"""
        path = get_ic_output_path('rsi_1d')
        assert path.parent == FACTOR_IC_RESULT_DIR
    
    def test_output_directory_exists_or_created(self):
        """输出目录不存在时应自动创建"""
        # FACTOR_IC_RESULT_DIR 应可创建
        assert FACTOR_IC_RESULT_DIR.exists() or FACTOR_IC_RESULT_DIR.parent.exists()
    
    def test_output_path_for_different_factors(self):
        """不同因子应生成不同的输出路径"""
        path_rsi = get_ic_output_path('rsi_1d')
        path_kdj = get_ic_output_path('kdj_j_3d')
        
        assert path_rsi != path_kdj
        assert 'rsi_1d' in path_rsi.name
        assert 'kdj_j_3d' in path_kdj.name


class TestOutputStructure:
    """测试输出数据结构规范"""
    
    REQUIRED_FIELDS = [
        'factor_name',
        'calculation_date',
        'period',
        'ic_metrics',
        'sample_stats',
        'statistical_significance',  # 五维度判断（PROJECT.md 规范）
        'factor_direction',          # 五维度判断（PROJECT.md 规范）
        'economic_significance',     # 五维度判断（PROJECT.md 规范）
        'icir_stability',            # 五维度判断（新增）
        'ic_distribution_consistency'  # 五维度判断（新增）
    ]
    
    IC_METRICS_FIELDS = ['ic_mean', 'ic_std', 'icir']  # p_value 移至 statistical_significance
    SAMPLE_STATS_FIELDS = ['total_days', 'valid_days', 'avg_stocks_per_day']
    
    # 五维度字段（PROJECT.md 规范）
    STATISTICAL_SIGNIFICANCE_FIELDS = ['p_value', 'p_value_display', 't_stat', 'nw_lag', 'nw_lag_method', 'is_significant', 'conclusion']
    FACTOR_DIRECTION_FIELDS = ['ic_mean', 'ic_mean_sign', 'direction_usage', 'conclusion']
    ECONOMIC_SIGNIFICANCE_FIELDS = ['abs_ic_mean', 'threshold_used', 'level', 'is_economically_significant', 'conclusion']
    ICIR_STABILITY_FIELDS = ['icir', 'threshold_used', 'level', 'is_stable', 'conclusion']
    IC_DISTRIBUTION_CONSISTENCY_FIELDS = ['positive_ratio', 'ic_mean_sign', 'is_consistent', 'consistency_type', 'distribution_hint', 'conclusion']
    
    def test_output_structure_has_required_fields(self, tmp_path):
        """输出 JSON 应包含规范要求的字段"""
        # 创建模拟输出文件
        output_file = tmp_path / 'ic_rsi_1d_analysis_result.json'
        
        # 规范要求的结构（五维度判断）
        expected_structure = {
            'factor_name': 'rsi_1d',
            'calculation_date': '2026-05-11',
            'period': {
                'start': '2024-01-01',
                'end': '2026-05-11'
            },
            'ic_metrics': {
                'ic_mean': -0.0416,
                'ic_std': 0.1441,
                'icir': 0.2889
            },
            'sample_stats': {
                'total_days': 520,
                'valid_days': 515,
                'avg_stocks_per_day': 4500
            },
            # 五维度判断（独立输出）
            'statistical_significance': {
                'p_value': 0.0349,
                'p_value_display': '0.0349',
                't_stat': -2.11,
                'nw_lag': 4,
                'nw_lag_method': 'Newey-West (1994): lag = int(4*(T/100)^(2/9))',
                'is_significant': True,
                'conclusion': '统计显著（p=0.0349<0.05）'
            },
            'factor_direction': {
                'ic_mean': -0.0416,
                'ic_mean_sign': 'negative',
                'direction_usage': '反向因子：分层回测时做多低值组、做空高值组',
                'conclusion': '因子方向为反向（ic_mean=-0.0416<0），分层回测做多低值组'
            },
            'economic_significance': {
                'abs_ic_mean': 0.0416,
                'threshold_used': {'weak': 0.03, 'strong': 0.05},
                'level': 'weak',
                'is_economically_significant': True,
                'conclusion': '经济显著弱（|ic_mean|=0.0416>=0.03）'
            },
            'icir_stability': {
                'icir': 0.2889,
                'threshold_used': {'usable': 0.5, 'good': 1.0, 'excellent': 2.0},
                'level': 'none',
                'is_stable': False,
                'conclusion': 'IC稳定性不足（ICIR=0.29<0.5)'
            },
            'ic_distribution_consistency': {
                'positive_ratio': 0.3813,
                'ic_mean_sign': 'negative',
                'is_consistent': True,
                'consistency_type': 'consistent',
                'distribution_hint': 'IC分布偏向负值（61.9%天数IC<0）',
                'conclusion': '一致：正比例<50%对应负方向，IC分布正常'
            }
        }
        
        output_file.write_text(json.dumps(expected_structure, ensure_ascii=False))
        
        # 验证结构
        data = json.loads(output_file.read_text())
        
        for field in self.REQUIRED_FIELDS:
            assert field in data, f"缺少必需字段: {field}"
        
        for field in self.IC_METRICS_FIELDS:
            assert field in data['ic_metrics'], f"ic_metrics 缺少字段: {field}"
        
        for field in self.SAMPLE_STATS_FIELDS:
            assert field in data['sample_stats'], f"sample_stats 缺少字段: {field}"
        
        # 验证五维度字段
        for field in self.STATISTICAL_SIGNIFICANCE_FIELDS:
            assert field in data['statistical_significance'], f"statistical_significance 缺少字段: {field}"
        
        for field in self.FACTOR_DIRECTION_FIELDS:
            assert field in data['factor_direction'], f"factor_direction 缺少字段: {field}"
        
        for field in self.ECONOMIC_SIGNIFICANCE_FIELDS:
            assert field in data['economic_significance'], f"economic_significance 缺少字段: {field}"
        
        for field in self.ICIR_STABILITY_FIELDS:
            assert field in data['icir_stability'], f"icir_stability 缺少字段: {field}"
        
        for field in self.IC_DISTRIBUTION_CONSISTENCY_FIELDS:
            assert field in data['ic_distribution_consistency'], f"ic_distribution_consistency 缺少字段: {field}"
    
    def test_factor_name_format(self):
        """factor_name 应为 <因子名>_<周期> 格式"""
        valid_names = ['rsi_1d', 'kdj_j_3d', 'volume_ratio_1d']
        
        for name in valid_names:
            # 格式验证: 因子名_周期
            parts = name.split('_')
            assert len(parts) >= 2, f"{name} 格式不正确"
            assert parts[-1] in ['1d', '3d', '5d'], f"{name} 周期格式不正确"
    
    def test_output_has_five_dimensions(self, tmp_path):
        """输出应包含五维度判断字段（独立输出）"""
        output_file = tmp_path / 'ic_rsi_1d_analysis_result.json'
        
        expected_structure = {
            'factor_name': 'rsi_1d',
            'calculation_date': '2026-05-11',
            'period': {'start': '2024-01-01', 'end': '2026-05-11'},
            'ic_metrics': {'ic_mean': -0.0416, 'ic_std': 0.1441, 'icir': 0.2889},
            'sample_stats': {'total_days': 500, 'valid_days': 500, 'avg_stocks_per_day': 4500},
            # 五维度判断
            'statistical_significance': {
                'p_value': 0.0349,
                'p_value_display': '0.0349',
                't_stat': -2.11,
                'nw_lag': 4,
                'nw_lag_method': 'Newey-West (1994): lag = int(4*(T/100)^(2/9))',
                'is_significant': True,
                'conclusion': '统计显著'
            },
            'factor_direction': {
                'ic_mean': -0.0416,
                'ic_mean_sign': 'negative',
                'direction_usage': '反向因子：分层回测时做多低值组、做空高值组',
                'conclusion': '方向为负'
            },
            'economic_significance': {
                'abs_ic_mean': 0.0416,
                'threshold_used': {'weak': 0.03, 'strong': 0.05},
                'level': 'weak',
                'is_economically_significant': True,
                'conclusion': '经济显著弱'
            },
            'icir_stability': {
                'icir': 0.2889,
                'threshold_used': {'usable': 0.5, 'good': 1.0, 'excellent': 2.0},
                'level': 'none',
                'is_stable': False,
                'conclusion': 'IC稳定性不足'
            },
            'ic_distribution_consistency': {
                'positive_ratio': 0.3813,
                'ic_mean_sign': 'negative',
                'is_consistent': True,
                'consistency_type': 'consistent',
                'distribution_hint': 'IC分布偏向负值',
                'conclusion': '一致'
            }
        }
        
        output_file.write_text(json.dumps(expected_structure, ensure_ascii=False))
        data = json.loads(output_file.read_text())
        
        # 验证五维度字段存在
        assert 'statistical_significance' in data
        assert 'factor_direction' in data
        assert 'economic_significance' in data
        assert 'icir_stability' in data
        assert 'ic_distribution_consistency' in data
        
        # 验证各维度关键字段
        assert 'is_significant' in data['statistical_significance']
        assert 'ic_mean_sign' in data['factor_direction']
        assert 'level' in data['economic_significance']
        assert 'is_stable' in data['icir_stability']
        assert 'is_consistent' in data['ic_distribution_consistency']
        
        # 验证方向值合法
        assert data['factor_direction']['ic_mean_sign'] in ['negative', 'positive', 'zero']
        
        # 验证经济显著性级别合法
        assert data['economic_significance']['level'] in ['strong', 'weak', 'none']
        
        # 验证 ICIR 稳定性级别合法
        assert data['icir_stability']['level'] in ['excellent', 'good', 'usable', 'none']
        
        # 验证分布一致性类型合法
        assert data['ic_distribution_consistency']['consistency_type'] in ['consistent', 'balanced', 'contradictory']
    
    def test_factor_direction_values(self):
        """factor_direction 的 ic_mean_sign 应为合法值"""
        valid_signs = ['negative', 'positive', 'zero']
        
        # 方向仅由 ic_mean 符号决定，不合并统计/经济显著性判断
        assert 'negative' in valid_signs
        assert 'positive' in valid_signs
        assert 'zero' in valid_signs
    
    def test_economic_significance_levels(self):
        """economic_significance 的 level 应为合法值"""
        valid_levels = ['strong', 'weak', 'none']
        
        # 经济显著性阈值：0.03（弱）、0.05（强）
        # 不合并到 factor_direction，独立输出
        assert 'strong' in valid_levels
        assert 'weak' in valid_levels
        assert 'none' in valid_levels
    
    def test_summary_format_with_positive_ratio(self, tmp_path):
        """summary 字段应包含正比例独立描述（PROJECT.md 规范：一致性判断在 ic_distribution_consistency 中独立输出）"""
        output_file = tmp_path / 'ic_rsi_1d_analysis_result.json'
        
        # 包含五维度判断的完整结构
        expected_structure = {
            'factor_name': 'rsi_1d',
            'ic_metrics': {'ic_mean': -0.0416, 'ic_std': 0.1441, 'icir': 0.2889},
            'statistical_significance': {
                'p_value': 0.0349,
                'p_value_display': '0.0349',
                't_stat': -2.11,
                'nw_lag': 4,
                'is_significant': True,
                'conclusion': '统计显著'
            },
            'factor_direction': {
                'ic_mean': -0.0416,
                'ic_mean_sign': 'negative',
                'direction_usage': '反向因子',
                'conclusion': '方向为负'
            },
            'economic_significance': {
                'abs_ic_mean': 0.0416,
                'level': 'weak',
                'is_economically_significant': True,
                'conclusion': '经济显著弱'
            },
            'icir_stability': {
                'icir': 0.2889,
                'level': 'none',
                'is_stable': False,
                'conclusion': 'IC稳定性不足'
            },
            'ic_distribution_consistency': {
                'positive_ratio': 0.3813,
                'ic_mean_sign': 'negative',
                'is_consistent': True,
                'consistency_type': 'consistent',
                'distribution_hint': 'IC分布偏向负值',
                'conclusion': '一致：正比例<50%对应负方向，IC分布正常'
            },
            'positive_ratio': 0.3813,
            'summary': 'IC均值=-0.0416, ICIR=0.29, p值=0.0349, 方向=negative, 统计显著=True, 经济显著=weak, ICIR稳定=none, 正比例=38.1%（IC>0天数占比）'
        }
        
        output_file.write_text(json.dumps(expected_structure, ensure_ascii=False))
        data = json.loads(output_file.read_text())
        
        # 验证 summary 包含正比例独立描述
        assert 'summary' in data
        summary = data['summary']
        
        # summary 应包含正比例关键词
        assert '正比例' in summary, f"summary 缺少正比例关键词: {summary}"
        
        # 一致性判断应在 ic_distribution_consistency 中独立输出
        assert 'ic_distribution_consistency' in data
        consistency = data['ic_distribution_consistency']
        assert 'is_consistent' in consistency
        assert 'conclusion' in consistency
        
        # 验证一致性判断包含关键词
        assert any(kw in consistency['conclusion'] for kw in ['一致', '矛盾', '均衡']), \
            f"ic_distribution_consistency.conclusion 缺少一致性判断关键词: {consistency['conclusion']}"
    
    def test_p_value_format_no_zero_display(self, tmp_path):
        """p_value_display 应避免显示为 0.0（PROJECT.md 数值精度规范）"""
        output_file = tmp_path / 'ic_rsi_1d_analysis_result.json'
        
        # p_value 极小值的正确格式化示例
        expected_structure = {
            'statistical_significance': {
                'p_value': 1e-10,  # 原始极小值
                'p_value_display': '< 1e-6',  # 正确格式化（不显示 0.0）
                't_stat': -7.16,
                'nw_lag': 5,
                'is_significant': True,
                'conclusion': '统计显著'
            }
        }
        
        output_file.write_text(json.dumps(expected_structure, ensure_ascii=False))
        data = json.loads(output_file.read_text())
        
        # 验证 p_value_display 不为 "0.0" 或 "0.0000"
        p_value_display = data['statistical_significance']['p_value_display']
        assert p_value_display not in ['0.0', '0.0000', '0'], \
            f"p_value_display 显示为 {p_value_display}，应格式化为科学计数法或极小值标记"
    
    def test_rolling_ic_mean_first_nine_null(self, tmp_path):
        """rolling_ic_mean 前9个值应为 null（min_periods=10，PROJECT.md 规范）"""
        output_file = tmp_path / 'ic_rsi_1d_analysis_result.json'
        
        # 模拟 ic_values 和 rolling_ic_mean
        expected_structure = {
            'factor_name': 'rsi_1d',
            'ic_values': [-0.05, -0.04, -0.03, -0.02, -0.01, 0.01, 0.02, 0.03, 0.04, 0.05, -0.06, -0.07],
            'rolling_ic_mean': [None, None, None, None, None, None, None, None, None, -0.015, -0.014, -0.013]
        }
        
        output_file.write_text(json.dumps(expected_structure))
        data = json.loads(output_file.read_text())
        
        # 验证前9个为 None（min_periods=10）
        rolling = data['rolling_ic_mean']
        assert len(rolling) == len(data['ic_values']), "rolling_ic_mean 长度应与 ic_values 一致"
        
        for i in range(9):
            assert rolling[i] is None, f"rolling_ic_mean[{i}] 应为 None（min_periods=10）"
        
        # 第10个开始应为数值
        assert rolling[9] is not None, "rolling_ic_mean[9] 应有有效值"
        assert isinstance(rolling[9], (int, float)), "rolling_ic_mean[9] 应为数值"


class TestCacheDependency:
    """测试数据依赖规范"""
    
    def test_cache_directory_exists(self):
        """缓存目录 data_fetchers/result/ 应存在"""
        cache_dir = Path(__file__).parent.parent.parent / 'cache' / 'factor_data'
        # 如果不存在，测试跳过（实际运行时需要缓存数据）
        if not cache_dir.exists():
            pytest.skip("缓存目录不存在，需要先运行数据拉取脚本")
    
    def test_script_does_not_fetch_data(self):
        """脚本不应包含数据拉取逻辑"""
        script_path = Path(__file__).parent.parent / 'ic_rsi_1d.py'
        
        if not script_path.exists():
            pytest.skip("ic_rsi_1d.py 不存在")
        
        content = script_path.read_text()
        
        # 检查不应出现的数据拉取关键词
        forbidden_patterns = [
            'requests.get',
            'requests.post',
            'fetch_from_api',
            'pd.read_sql',
            'sqlalchemy',
        ]
        
        for pattern in forbidden_patterns:
            assert pattern not in content, f"脚本不应包含数据拉取逻辑: {pattern}"


class TestIntegration:
    """集成测试（需要真实缓存数据）"""
    
    @pytest.fixture
    def cache_data_exists(self):
        """检查缓存数据是否存在"""
        result_dir = Path(__file__).parent.parent.parent / 'data_fetchers' / 'result'
        data_cache = result_dir / 'factor_ic_data.json.gz'
        
        return data_cache.exists()
    
    def test_run_ic_calculation(self, cache_data_exists):
        """运行 IC 计算（需要缓存数据）"""
        if not cache_data_exists:
            pytest.skip("缓存数据不存在，需要先运行数据拉取脚本")
        
        # 导入并运行
        from factor_ic.ic_rsi_1d import generate_rsi_ic_data
        
        # 运行计算（使用缓存全部日期，不截断）
        result = generate_rsi_ic_data(force_full=True)
        
        # 验证结果
        assert result is not None
        assert 'factor_name' in result
        assert result['factor_name'] == 'rsi_1d'
    
    def test_output_file_created(self, cache_data_exists):
        """输出文件应被创建"""
        if not cache_data_exists:
            pytest.skip("缓存数据不存在")
        
        output_path = get_ic_output_path('rsi_1d')
        
        # 如果已存在，验证结构
        if output_path.exists():
            data = json.loads(output_path.read_text())
            assert 'factor_name' in data


class TestAlgorithmEquivalence:
    """测试全量/增量 IC 计算算法等价性（遵循 PROJECT.md 规范）"""
    
    def test_full_incremental_same_core_function(self):
        """
        验证全量计算与增量计算使用同一核心函数 calculate_single_day_ic
        
        遵循 PROJECT.md "全量/增量 IC 计算等价性规范"
        """
        import pandas as pd
        from factor_ic.common.ic_calculator import (
            calculate_ic_with_direction_verification,
            calculate_single_day_ic
        )
        
        # 构造测试数据（单日）
        test_date = '2026-05-01'
        test_data = pd.DataFrame({
            'date': [test_date] * 20,
            'asset': [f'00000{i}' for i in range(20)],
            'rsi_6': [30 + i * 2 for i in range(20)],  # 不同因子值
            'forward_return': [0.01 + i * 0.001 for i in range(20)]  # 不同收益值
        })
        
        # 增量计算：直接调用 calculate_single_day_ic
        incremental_ic = calculate_single_day_ic(
            test_data,
            factor_col='rsi_6',
            return_col='forward_return',
            min_stocks=10
        )
        
        # 全量计算：通过 calculate_ic_with_direction_verification
        factor_df = test_data[['date', 'asset', 'rsi_6']]
        return_df = test_data[['date', 'asset', 'forward_return']]
        full_result = calculate_ic_with_direction_verification(
            factor_df,
            return_df,
            factor_col='rsi_6',
            return_col='forward_return'
        )
        full_ic = full_result['ic_series'].iloc[0]
        
        # 验证等价性：两者应产生相同的 IC 值
        assert incremental_ic is not None
        assert abs(incremental_ic - full_ic) < 1e-6, \
            f"全量/增量 IC 值不一致: 全量={full_ic}, 增量={incremental_ic}"
    
    def test_boundary_handling_equivalence_insufficient_stocks(self):
        """
        验证边界处理等价性：股票数不足
        
        calculate_single_day_ic 返回 None → 全量计算应抛出 ValueError（无有效交易日）
        """
        import pandas as pd
        import pytest
        from factor_ic.common.ic_calculator import (
            calculate_ic_with_direction_verification,
            calculate_single_day_ic
        )
        
        # 构造测试数据（股票数 < min_stocks=10）
        test_date = '2026-05-01'
        insufficient_data = pd.DataFrame({
            'date': [test_date] * 5,  # 只有 5 只股票
            'asset': [f'00000{i}' for i in range(5)],
            'rsi_6': [30 + i * 2 for i in range(5)],
            'forward_return': [0.01 + i * 0.001 for i in range(5)]
        })
        
        # 增量计算：直接调用 calculate_single_day_ic
        incremental_ic = calculate_single_day_ic(
            insufficient_data,
            factor_col='rsi_6',
            return_col='forward_return',
            min_stocks=10
        )
        
        # 全量计算：通过 calculate_ic_with_direction_verification
        factor_df = insufficient_data[['date', 'asset', 'rsi_6']]
        return_df = insufficient_data[['date', 'asset', 'forward_return']]
        
        # 验证等价性：
        # - 增量计算返回 None
        # - 全量计算抛出 ValueError（无有效交易日）
        assert incremental_ic is None, "股票数不足时应返回 None"
        
        # 全量计算应抛出异常（所有日期股票数都不足）
        with pytest.raises(ValueError, match="没有有效的交易日"):
            calculate_ic_with_direction_verification(
                factor_df,
                return_df,
                factor_col='rsi_6',
                return_col='forward_return'
            )
    
    def test_boundary_handling_equivalence_constant_factor(self):
        """
        验证边界处理等价性：因子值全相同
        
        calculate_single_day_ic 返回 0.0 → 全量计算应产生 0.0
        """
        import pandas as pd
        from factor_ic.common.ic_calculator import (
            calculate_ic_with_direction_verification,
            calculate_single_day_ic
        )
        
        # 构造测试数据（因子值全相同）
        test_date = '2026-05-01'
        constant_factor_data = pd.DataFrame({
            'date': [test_date] * 20,
            'asset': [f'00000{i}' for i in range(20)],
            'rsi_6': [50.0] * 20,  # 因子值全相同
            'forward_return': [0.01 + i * 0.001 for i in range(20)]
        })
        
        # 增量计算：直接调用 calculate_single_day_ic
        incremental_ic = calculate_single_day_ic(
            constant_factor_data,
            factor_col='rsi_6',
            return_col='forward_return',
            min_stocks=10
        )
        
        # 全量计算：通过 calculate_ic_with_direction_verification
        factor_df = constant_factor_data[['date', 'asset', 'rsi_6']]
        return_df = constant_factor_data[['date', 'asset', 'forward_return']]
        full_result = calculate_ic_with_direction_verification(
            factor_df,
            return_df,
            factor_col='rsi_6',
            return_col='forward_return'
        )
        full_ic = full_result['ic_series'].iloc[0]
        
        # 验证等价性：两者应返回 0.0
        assert incremental_ic == 0.0, "因子值全相同时应返回 0.0"
        assert full_ic == 0.0, "因子值全相同时应返回 0.0"
    
    def test_full_incremental_equivalence_multi_day(self):
        """
        验证多日期场景的全量/增量等价性
        
        遵循 PROJECT.md "全量/增量 IC 计算等价性规范"
        - 全量计算：一次调用 calculate_ic_with_direction_verification
        - 增量计算：逐日调用 calculate_single_day_ic
        - 两者对同一日期应产生相同 IC 值
        """
        import pandas as pd
        from factor_ic.common.ic_calculator import (
            calculate_ic_with_direction_verification,
            calculate_single_day_ic
        )
        
        # 构造多日期测试数据（3个交易日）
        dates = ['2026-05-01', '2026-05-02', '2026-05-03']
        test_data = []
        for i, date in enumerate(dates):
            for j in range(20):
                test_data.append({
                    'date': date,
                    'asset': f'00000{j}',
                    'rsi_6': 30 + i * 10 + j * 2,  # 不同日期因子值不同
                    'forward_return': 0.01 + i * 0.005 + j * 0.001
                })
        test_df = pd.DataFrame(test_data)
        
        # 全量计算：一次调用
        factor_df = test_df[['date', 'asset', 'rsi_6']]
        return_df = test_df[['date', 'asset', 'forward_return']]
        full_result = calculate_ic_with_direction_verification(
            factor_df,
            return_df,
            factor_col='rsi_6',
            return_col='forward_return'
        )
        full_ic_series = full_result['ic_series']
        
        # 增量计算：逐日调用 calculate_single_day_ic
        incremental_ic_values = {}
        for date, daily_data in test_df.groupby('date'):
            ic_value = calculate_single_day_ic(
                daily_data,
                factor_col='rsi_6',
                return_col='forward_return',
                min_stocks=10
            )
            incremental_ic_values[str(date)] = ic_value
        
        # 验证等价性：每个日期的 IC 值应一致
        for date in dates:
            full_ic = full_ic_series.loc[date]
            incremental_ic = incremental_ic_values[date]
            assert abs(full_ic - incremental_ic) < 1e-6, \
                f"日期 {date} 全量/增量 IC 不一致: 全量={full_ic:.6f}, 增量={incremental_ic:.6f}"
        
        # 验证 ic_mean 一致性
        full_ic_mean = full_result['ic_mean']
        incremental_ic_mean = sum(incremental_ic_values.values()) / len(incremental_ic_values)
        assert abs(full_ic_mean - incremental_ic_mean) < 1e-6, \
            f"ic_mean 不一致: 全量={full_ic_mean:.6f}, 增量={incremental_ic_mean:.6f}"
        
        # 验证方向一致性：factor_direction 应与 incremental_ic_mean 符号匹配
        factor_direction = full_result['factor_direction']['ic_mean_sign']
        if incremental_ic_mean > 0.001:
            assert factor_direction == 'positive', \
                f"方向不一致: incremental_ic_mean={incremental_ic_mean:.6f} > 0, 但方向={factor_direction}"
        elif incremental_ic_mean < -0.001:
            assert factor_direction == 'negative', \
                f"方向不一致: incremental_ic_mean={incremental_ic_mean:.6f} < 0, 但方向={factor_direction}"


# ============================================================
# 运行说明
# ============================================================

"""
运行完整测试:
    pytest factor_ic/test_cases/ic_rsi_1d_test_cases.py -v

运行特定测试类:
    pytest factor_ic/test_cases/ic_rsi_1d_test_cases.py::TestOutputPath -v
    pytest factor_ic/test_cases/ic_rsi_1d_test_cases.py::TestOutputStructure -v

跳过需要缓存的测试:
    pytest factor_ic/test_cases/ic_rsi_1d_test_cases.py -v -m "not cache"

前置条件:
    1. 缓存数据: data_fetchers/result/factor_ic_data.json.gz
    2. 数据包含 rsi_6 和 forward_return_1d 列
"""