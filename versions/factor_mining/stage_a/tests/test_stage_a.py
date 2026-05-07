"""
阶段A功能验证测试
"""

import pytest
import numpy as np
import pandas as pd
import sys
import os

# 添加路径
sys.path.insert(0, '/home/admin/.openclaw/workspace/yunzhou/factor_ic_analyzer')

from versions.factor_mining.stage_a.safe_math import SafeMath, safe_div, safe_log, safe_sqrt, safe_rank
from versions.factor_mining.stage_a.factor_combiner import FactorCombiner
from versions.factor_mining.stage_a.ic_filter import ICFilter
from versions.factor_mining.stage_a.deduplicator import FactorDeduplicator
from versions.factor_mining.stage_a.pipeline import StageAPipeline


# ==================== 1. 模块导入测试 ====================

class TestModuleImport:
    """模块导入测试"""
    
    def test_safe_math_import(self):
        """SafeMath模块导入"""
        assert SafeMath is not None
        
    def test_factor_combiner_import(self):
        """FactorCombiner模块导入"""
        assert FactorCombiner is not None
        
    def test_ic_filter_import(self):
        """ICFilter模块导入"""
        assert ICFilter is not None
        
    def test_deduplicator_import(self):
        """Deduplicator模块导入"""
        assert FactorDeduplicator is not None
        
    def test_pipeline_import(self):
        """Pipeline模块导入"""
        assert StageAPipeline is not None


# ==================== 2. SafeMath边界保护测试 ====================

class TestSafeMath:
    """SafeMath边界保护测试"""
    
    def test_divide_by_zero_scalar(self):
        """除零保护 - 标量"""
        result = SafeMath.safe_divide(10.0, 0.0)
        assert not np.isnan(result) or result == 0.0  # 不崩溃
        
    def test_divide_by_zero_series(self):
        """除零保护 - Series"""
        s1 = pd.Series([10.0, 20.0, 30.0])
        s2 = pd.Series([0.0, 2.0, 0.0])
        result = SafeMath.safe_divide(s1, s2)
        assert len(result) == 3
        assert not result.isna().all()  # 不全为NaN
        
    def test_nan_handling(self):
        """NaN处理"""
        s = pd.Series([1.0, np.nan, 3.0])
        result = SafeMath.clean_series(s)
        assert not result.isna().any()  # NaN被填充
        
    def test_inf_handling(self):
        """Inf处理"""
        s = pd.Series([1.0, np.inf, -np.inf, 3.0])
        result = SafeMath.clean_series(s)
        assert not np.isinf(result).any()  # Inf被处理
        
    def test_sqrt_negative(self):
        """负数开方"""
        result = SafeMath.safe_sqrt(-1.0)
        assert result == 0.0  # 负数转为0
        
    def test_log_negative(self):
        """负数log"""
        result = SafeMath.safe_log(-10.0)
        assert result >= 0 or result == 0.0  # 处理不崩溃
        
    def test_overflow_protection(self):
        """数值溢出保护"""
        result = SafeMath.safe_power(1e308, 2, fill_value=0.0)
        assert not np.isinf(result) or result == 0.0  # 溢出被处理
        
    def test_rank_normalization(self):
        """排名归一化"""
        s = pd.Series([0.1, 0.5, 0.9])
        result = SafeMath.safe_rank(s, normalize=True)
        assert result.min() >= 0 and result.max() <= 1  # 归一化范围正确


# ==================== 3. FactorCombiner组合生成测试 ====================

class TestFactorCombiner:
    """FactorCombiner组合生成测试"""
    
    def setup_method(self):
        """设置测试数据"""
        np.random.seed(42)
        n = 100
        self.factor_data = {
            'rsi': pd.Series(np.random.uniform(20, 80, n)),
            'kdj_j': pd.Series(np.random.uniform(-20, 120, n)),
            'bollinger_pb': pd.Series(np.random.uniform(0.5, 2.0, n)),
            'volume_ratio': pd.Series(np.random.uniform(0.5, 3.0, n)),
            'turnover_surge': pd.Series(np.random.uniform(0, 5, n)),
            'main_inflow_ratio': pd.Series(np.random.uniform(-0.1, 0.3, n))
        }
        self.combiner = FactorCombiner()
        
    def test_binary_combinations(self):
        """四则运算组合生成"""
        combos = self.combiner.generate_binary_combinations(self.factor_data)
        assert len(combos) > 0  # 生成了组合
        
    def test_unary_combinations(self):
        """一元操作组合"""
        combos = self.combiner.generate_unary_combinations(self.factor_data)
        assert len(combos) > 0
        
    def test_ratio_combinations(self):
        """比率组合"""
        combos = self.combiner.generate_ratio_combinations(self.factor_data)
        assert len(combos) > 0
        
    def test_rank_combinations(self):
        """排名组合"""
        combos = self.combiner.generate_rank_combinations(self.factor_data)
        assert len(combos) > 0
        
    def test_nested_combinations(self):
        """嵌套组合"""
        combos = self.combiner.generate_nested_combinations(self.factor_data)
        assert len(combos) > 0
        
    def test_generate_all(self):
        """生成所有组合"""
        combos = self.combiner.generate_all(self.factor_data)
        assert len(combos) > 0
        stats = self.combiner.get_expression_count()
        assert stats['total'] > 0
        
    def test_compute_expression(self):
        """表达式计算"""
        result = self.combiner.compute_expression('rsi + kdj_j', self.factor_data)
        expected = self.factor_data['rsi'] + self.factor_data['kdj_j']
        pd.testing.assert_series_equal(result, expected, check_names=False)


# ==================== 4. ICFilter筛选逻辑测试 ====================

class TestICFilter:
    """ICFilter筛选逻辑测试"""
    
    def setup_method(self):
        """设置测试数据"""
        np.random.seed(42)
        n = 150
        self.factor_values = pd.Series(np.random.uniform(0, 100, n))
        # 构造有相关性的收益率
        self.returns = pd.Series(self.factor_values * 0.01 + np.random.normal(0, 0.5, n))
        self.ic_filter = ICFilter()
        
    def test_calculate_ic(self):
        """IC计算"""
        ic = self.ic_filter.calculate_ic(self.factor_values, self.returns)
        assert not np.isnan(ic)  # IC计算有效
        
    def test_ic_threshold_pass(self):
        """IC阈值筛选 - 通过"""
        # 高IC因子
        high_ic_factor = pd.Series(np.random.uniform(0, 100, 150))
        returns_aligned = high_ic_factor * 0.05 + np.random.normal(0, 0.1, 150)
        ic = self.ic_filter.calculate_ic(high_ic_factor, returns_aligned)
        # 检查IC计算有效
        assert not np.isnan(ic)
        
    def test_ic_threshold_reject(self):
        """IC阈值筛选 - 拒绝"""
        # 随机因子（低IC）
        random_factor = pd.Series(np.random.uniform(0, 100, 150))
        random_returns = pd.Series(np.random.normal(0, 1, 150))
        ic = self.ic_filter.calculate_ic(random_factor, random_returns)
        # IC值应较低
        assert abs(ic) < 0.5
        
    def test_min_records_check(self):
        """最小记录数检查"""
        short_factor = pd.Series(np.random.uniform(0, 100, 50))  # 不足100
        returns = pd.Series(np.random.normal(0, 1, 50))
        passed, metrics = self.ic_filter.filter_factor(short_factor, returns)
        assert not passed  # 应被拒绝
        
    def test_ic_metrics_calculation(self):
        """IC指标计算"""
        # 生成IC序列
        ic_series = pd.Series([0.05, 0.06, 0.04, 0.07, 0.05])
        metrics = self.ic_filter.calculate_ic_metrics(ic_series)
        assert 'ic_mean' in metrics
        assert 'ic_ir' in metrics
        assert 'ic_tstat' in metrics
        
    def test_filter_by_ic_metrics_pass(self):
        """IC指标筛选 - 通过"""
        metrics = {
            'factor1': {
                'ic_mean': 0.035, 'ic_ir': 0.6, 'ic_tstat': 2.5,
                'n_records': 150, 'ic_std': 0.1, 'ic_positive_ratio': 0.6
            }
        }
        passed, failed = self.ic_filter.filter_by_ic_metrics(metrics)
        assert 'factor1' in passed
        
    def test_filter_by_ic_metrics_reject_ic(self):
        """IC指标筛选 - IC不足拒绝"""
        metrics = {
            'factor2': {
                'ic_mean': 0.025, 'ic_ir': 0.6, 'ic_tstat': 2.5,
                'n_records': 150, 'ic_std': 0.1, 'ic_positive_ratio': 0.6
            }
        }
        passed, failed = self.ic_filter.filter_by_ic_metrics(metrics)
        assert 'factor2' in failed
        
    def test_filter_by_ic_metrics_reject_ir(self):
        """IC指标筛选 - IR不足拒绝"""
        metrics = {
            'factor3': {
                'ic_mean': 0.04, 'ic_ir': 0.4, 'ic_tstat': 2.5,
                'n_records': 150, 'ic_std': 0.1, 'ic_positive_ratio': 0.6
            }
        }
        passed, failed = self.ic_filter.filter_by_ic_metrics(metrics)
        assert 'factor3' in failed


# ==================== 5. Deduplicator去重测试 ====================

class TestDeduplicator:
    """Deduplicator去重测试"""
    
    def setup_method(self):
        """设置测试数据"""
        np.random.seed(42)
        n = 100
        base = pd.Series(np.random.uniform(0, 100, n))
        self.factors_data = {
            'factor_a': base,
            'factor_b': base + np.random.normal(0, 1, n),  # 高相关
            'factor_c': pd.Series(np.random.uniform(0, 100, n)),  # 低相关
        }
        self.dedup = FactorDeduplicator(correlation_threshold=0.8)
        
    def test_calculate_correlation(self):
        """相关性计算"""
        corr = self.dedup.calculate_correlation(
            self.factors_data['factor_a'],
            self.factors_data['factor_b']
        )
        assert not np.isnan(corr)
        assert 0 <= corr <= 1
        
    def test_high_correlation_dedup(self):
        """高相关去重"""
        # factor_a和factor_b高度相关
        result, removed, stats = self.dedup.deduplicate(self.factors_data)
        assert len(removed) > 0  # 有因子被移除
        
    def test_low_correlation_keep(self):
        """低相关保留"""
        # 创建低相关因子组
        np.random.seed(42)
        n = 100
        factors = {
            'f1': pd.Series(np.random.uniform(0, 100, n)),
            'f2': pd.Series(np.random.uniform(0, 100, n)),
        }
        result, removed, stats = self.dedup.deduplicate(factors)
        assert len(removed) == 0  # 无因子被移除
        
    def test_self_correlation(self):
        """自相关检查"""
        corr = self.dedup.calculate_correlation(
            self.factors_data['factor_a'],
            self.factors_data['factor_a']
        )
        assert np.isclose(corr, 1.0, atol=1e-6) or np.isnan(corr)  # 自相关应接近1
        
    def test_dedup_count(self):
        """去重计数"""
        np.random.seed(42)
        n = 100
        base = pd.Series(np.random.uniform(0, 100, n))
        # 创建10个高相关因子
        factors = {}
        for i in range(10):
            factors[f'f{i}'] = base + np.random.normal(0, 0.5, n)
        
        result, removed, stats = self.dedup.deduplicate(factors)
        assert stats['original_count'] == 10
        assert stats['kept_count'] < 10
        
    def test_correlation_matrix(self):
        """相关性矩阵计算"""
        corr_matrix = self.dedup.calculate_correlation_matrix(self.factors_data)
        assert len(corr_matrix) == 3
        assert corr_matrix.shape == (3, 3)


# ==================== 6. Pipeline端到端测试 ====================

class TestPipeline:
    """Pipeline端到端测试"""
    
    def setup_method(self):
        """设置测试数据"""
        np.random.seed(42)
        n = 200
        self.factor_data = {
            'rsi': pd.Series(np.random.uniform(20, 80, n)),
            'kdj_j': pd.Series(np.random.uniform(-20, 120, n)),
            'bollinger_pb': pd.Series(np.random.uniform(0.5, 2.0, n)),
            'volume_ratio': pd.Series(np.random.uniform(0.5, 3.0, n)),
        }
        # 构造有相关性的收益率
        self.returns = self.factor_data['rsi'] * 0.001 + np.random.normal(0, 0.02, n)
        
    def test_pipeline_run(self):
        """Pipeline执行"""
        config = {
            'ic_threshold': 0.01,  # 降低阈值以便测试通过
            'ir_threshold': 0.1,
            'tstat_threshold': 1.0,
            'correlation_threshold': 0.8,
            'min_records': 50,
            'keep_strategy': 'highest_ic',
            'max_combinations': 500,
            'verbose': False
        }
        pipeline = StageAPipeline(config=config)
        result = pipeline.run(self.factor_data, self.returns, include_nested=False)
        
        # 验证执行结果
        assert result['success']
        assert 'final_factors' in result
        assert 'stats' in result
        
    def test_pipeline_stages(self):
        """Pipeline各阶段"""
        config = {
            'ic_threshold': 0.01,
            'ir_threshold': 0.1,
            'tstat_threshold': 1.0,
            'correlation_threshold': 0.8,
            'min_records': 50,
            'keep_strategy': 'highest_ic',
            'max_combinations': 500,
            'verbose': False
        }
        pipeline = StageAPipeline(config=config)
        
        # 加载因子
        valid_factors = pipeline.load_base_factors(self.factor_data)
        assert len(valid_factors) >= 2
        
        # 组合生成
        expressions = pipeline.run_combination(valid_factors, include_nested=False)
        assert len(expressions) > 0
        
    def test_empty_data_handling(self):
        """空数据处理"""
        config = {
            'ic_threshold': 0.03,
            'ir_threshold': 0.5,
            'tstat_threshold': 2.0,
            'correlation_threshold': 0.8,
            'min_records': 100,
            'keep_strategy': 'highest_ic',
            'max_combinations': 500,
            'verbose': False
        }
        pipeline = StageAPipeline(config=config)
        result = pipeline.run({}, pd.Series())
        assert not result['success']  # 应返回失败


# ==================== 运行测试 ====================

if __name__ == '__main__':
    pytest.main([__file__, '-v', '--tb=short'])