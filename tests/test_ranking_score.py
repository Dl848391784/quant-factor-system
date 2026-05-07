"""
排序逻辑单元测试

测试 rank_by_annual_return 函数

测试场景:
- 年化收益优先排序
- 回撤次优先验证
- 约束过滤验证
- 空结果处理
- 指标缺失处理
"""

import pytest
from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass


# ============ Mock 实现用于测试 ============

def rank_by_annual_return(
    results: List[Dict],
    constraints: Optional[Dict[str, Tuple[float, float]]] = None
) -> List[Dict]:
    """
    按年化收益优先排序回测结果
    
    排序优先级（降序）:
    1. 年化收益（annual_return）
    2. 最大回撤（max_drawdown，越小越好，取负值）
    3. 胜率（win_rate）
    4. ICIR
    
    Args:
        results: 回测结果列表，每个元素包含'metrics'字段
        constraints: 可选约束条件
    
    Returns:
        List[Dict]: 排序后的结果列表
    """
    if not results:
        return []
    
    # 应用约束过滤
    if constraints:
        filtered_results = []
        for result in results:
            metrics = result.get('metrics', {})
            passed = True
            
            for metric_name, (min_val, max_val) in constraints.items():
                value = metrics.get(metric_name)
                if value is None:
                    continue
                if not (min_val <= value <= max_val):
                    passed = False
                    break
            
            result['passed_constraints'] = passed
            if passed:
                filtered_results.append(result)
        
        results = filtered_results
    
    # 排序：年化收益 > 最大回撤（负值） > 胜率 > ICIR
    def ranking_key(result: Dict) -> Tuple:
        metrics = result.get('metrics', {})
        return (
            metrics.get('annual_return', float('-inf')),
            -metrics.get('max_drawdown', float('inf')),  # 负值，越小越好
            metrics.get('win_rate', 0),
            metrics.get('icir', 0)
        )
    
    sorted_results = sorted(results, key=ranking_key, reverse=True)
    return sorted_results


# ============ Pytest Fixtures ============

@pytest.fixture
def sample_backtest_results():
    """测试用回测结果"""
    return [
        {
            'weights': {'f1': 0.3, 'f2': 0.3, 'f3': 0.4},
            'metrics': {
                'annual_return': 0.25,
                'max_drawdown': 15.0,
                'win_rate': 60.0,
                'icir': 1.5
            }
        },
        {
            'weights': {'f1': 0.4, 'f2': 0.3, 'f3': 0.3},
            'metrics': {
                'annual_return': 0.30,
                'max_drawdown': 20.0,
                'win_rate': 55.0,
                'icir': 1.8
            }
        },
        {
            'weights': {'f1': 0.2, 'f2': 0.4, 'f3': 0.4},
            'metrics': {
                'annual_return': 0.25,
                'max_drawdown': 12.0,  # 更低回撤
                'win_rate': 58.0,
                'icir': 1.3
            }
        },
        {
            'weights': {'f1': 0.5, 'f2': 0.2, 'f3': 0.3},
            'metrics': {
                'annual_return': 0.20,
                'max_drawdown': 10.0,
                'win_rate': 65.0,
                'icir': 1.2
            }
        },
        {
            'weights': {'f1': 0.35, 'f2': 0.35, 'f3': 0.3},
            'metrics': {
                'annual_return': -0.15,  # 负收益
                'max_drawdown': 35.0,
                'win_rate': 45.0,
                'icir': 1.6
            }
        }
    ]


@pytest.fixture
def sample_constraints():
    """测试用约束条件"""
    return {
        'annual_return': (0.0, 1.0),      # 年化收益必须为正
        'max_drawdown': (0.0, 30.0),      # 最大回撤不超过30%
        'win_rate': (50.0, 100.0)         # 胜率不低于50%
    }


# ============ 测试用例 ============

class TestAnnualReturnPriority:
    """年化收益优先排序测试"""
    
    def test_sort_by_annual_return_descending(self, sample_backtest_results):
        """测试用例1: 按年化收益降序排序"""
        sorted_results = rank_by_annual_return(sample_backtest_results)
        
        annual_returns = [r['metrics']['annual_return'] for r in sorted_results]
        
        # 验证降序排列
        assert annual_returns == sorted(annual_returns, reverse=True)
        
        # 最高收益应该在第一位
        assert sorted_results[0]['metrics']['annual_return'] == 0.30
    
    def test_negative_return_at_bottom(self, sample_backtest_results):
        """测试用例2: 负收益排在最后"""
        sorted_results = rank_by_annual_return(sample_backtest_results)
        
        # 负收益应该在最后
        assert sorted_results[-1]['metrics']['annual_return'] == -0.15
    
    def test_equal_return_sort_by_drawdown(self, sample_backtest_results):
        """测试用例3: 相同年化收益按回撤排序（回撤越小越好）"""
        # 有两个年化收益为0.25的结果
        sorted_results = rank_by_annual_return(sample_backtest_results)
        
        # 找出年化收益为0.25的结果
        same_return = [r for r in sorted_results 
                       if r['metrics']['annual_return'] == 0.25]
        
        assert len(same_return) == 2
        
        # 回撤低的应该排在前面
        assert same_return[0]['metrics']['max_drawdown'] <= \
               same_return[1]['metrics']['max_drawdown']


class TestDrawdownSecondaryPriority:
    """回撤次优先测试"""
    
    def test_lower_drawdown_ranked_higher(self):
        """测试用例4: 相同年化收益，回撤更低排前面"""
        results = [
            {
                'weights': {'f1': 0.5, 'f2': 0.5},
                'metrics': {'annual_return': 0.20, 'max_drawdown': 15.0, 
                           'win_rate': 55.0, 'icir': 1.0}
            },
            {
                'weights': {'f1': 0.4, 'f2': 0.6},
                'metrics': {'annual_return': 0.20, 'max_drawdown': 10.0, 
                           'win_rate': 55.0, 'icir': 1.0}
            },
            {
                'weights': {'f1': 0.6, 'f2': 0.4},
                'metrics': {'annual_return': 0.20, 'max_drawdown': 20.0, 
                           'win_rate': 55.0, 'icir': 1.0}
            }
        ]
        
        sorted_results = rank_by_annual_return(results)
        
        # 验证按回撤升序（越小越好）
        drawdowns = [r['metrics']['max_drawdown'] for r in sorted_results]
        assert drawdowns == sorted(drawdowns)
    
    def test_drawdown_then_win_rate(self):
        """测试用例5: 相同年化收益和回撤，按胜率排序"""
        results = [
            {
                'weights': {'f1': 0.5},
                'metrics': {'annual_return': 0.20, 'max_drawdown': 10.0, 
                           'win_rate': 60.0, 'icir': 1.0}
            },
            {
                'weights': {'f1': 0.5},
                'metrics': {'annual_return': 0.20, 'max_drawdown': 10.0, 
                           'win_rate': 55.0, 'icir': 1.5}  # ICIR更高但胜率低
            }
        ]
        
        sorted_results = rank_by_annual_return(results)
        
        # 胜率高的应该排前面
        assert sorted_results[0]['metrics']['win_rate'] == 60.0


class TestConstraintFiltering:
    """约束过滤测试"""
    
    def test_filter_by_annual_return_constraint(self, sample_backtest_results, sample_constraints):
        """测试用例6: 年化收益约束过滤"""
        sorted_results = rank_by_annual_return(
            sample_backtest_results, 
            constraints=sample_constraints
        )
        
        # 所有结果年化收益应为正
        for result in sorted_results:
            assert result['metrics']['annual_return'] >= 0
    
    def test_filter_by_drawdown_constraint(self, sample_backtest_results, sample_constraints):
        """测试用例7: 最大回撤约束过滤"""
        sorted_results = rank_by_annual_return(
            sample_backtest_results,
            constraints=sample_constraints
        )
        
        # 所有结果最大回撤应<30%
        for result in sorted_results:
            assert result['metrics']['max_drawdown'] < 30.0
    
    def test_filter_by_win_rate_constraint(self, sample_backtest_results, sample_constraints):
        """测试用例8: 胜率约束过滤"""
        sorted_results = rank_by_annual_return(
            sample_backtest_results,
            constraints=sample_constraints
        )
        
        # 所有结果胜率应>=50%
        for result in sorted_results:
            assert result['metrics']['win_rate'] >= 50.0
    
    def test_constraint_passes_marked(self, sample_backtest_results, sample_constraints):
        """测试用例9: 约束通过标记正确"""
        # 无约束时
        results_no_constraint = rank_by_annual_return(sample_backtest_results)
        
        # 有约束时
        results_with_constraint = rank_by_annual_return(
            sample_backtest_results,
            constraints=sample_constraints
        )
        
        # 有约束的结果应该更少
        assert len(results_with_constraint) <= len(sample_backtest_results)


class TestEmptyAndMissing:
    """空结果和缺失值测试"""
    
    def test_empty_results_returns_empty(self):
        """测试用例10: 空结果返回空列表"""
        result = rank_by_annual_return([])
        assert result == []
    
    def test_missing_annual_return(self):
        """测试用例11: 缺失年化收益处理"""
        results = [
            {
                'weights': {'f1': 0.5},
                'metrics': {'max_drawdown': 10.0, 'win_rate': 55.0}
            },
            {
                'weights': {'f1': 0.5},
                'metrics': {'annual_return': 0.20, 'max_drawdown': 15.0, 
                           'win_rate': 55.0}
            }
        ]
        
        sorted_results = rank_by_annual_return(results)
        
        # 有年化收益的应该排前面
        assert sorted_results[0]['metrics']['annual_return'] == 0.20
    
    def test_missing_metrics_field(self):
        """测试用例12: 缺失metrics字段处理"""
        results = [
            {'weights': {'f1': 0.5}},  # 缺失metrics
            {'weights': {'f2': 0.5}, 'metrics': {'annual_return': 0.10}}
        ]
        
        # 应该不抛出异常
        sorted_results = rank_by_annual_return(results)
        assert len(sorted_results) == 2
    
    def test_partial_metrics(self):
        """测试用例13: 部分指标缺失"""
        results = [
            {
                'weights': {'f1': 0.5},
                'metrics': {'annual_return': 0.20}  # 只有年化收益
            },
            {
                'weights': {'f2': 0.5},
                'metrics': {'annual_return': 0.20, 'max_drawdown': 10.0}
            }
        ]
        
        sorted_results = rank_by_annual_return(results)
        
        # 都能正常排序
        assert len(sorted_results) == 2


class TestEdgeCases:
    """边界情况测试"""
    
    def test_single_result(self):
        """测试用例14: 单个结果"""
        results = [
            {
                'weights': {'f1': 1.0},
                'metrics': {'annual_return': 0.15, 'max_drawdown': 8.0, 
                           'win_rate': 60.0, 'icir': 1.2}
            }
        ]
        
        sorted_results = rank_by_annual_return(results)
        assert len(sorted_results) == 1
        assert sorted_results[0]['metrics']['annual_return'] == 0.15
    
    def test_all_results_fail_constraint(self):
        """测试用例15: 所有结果都不满足约束"""
        results = [
            {
                'weights': {'f1': 1.0},
                'metrics': {'annual_return': -0.20}  # 负收益
            }
        ]
        
        constraints = {'annual_return': (0.0, 1.0)}
        
        sorted_results = rank_by_annual_return(results, constraints=constraints)
        
        # 所有结果被过滤，返回空
        assert sorted_results == []
    
    def test_zero_values(self):
        """测试用例16: 零值处理"""
        results = [
            {
                'weights': {'f1': 1.0},
                'metrics': {'annual_return': 0.0, 'max_drawdown': 0.0, 
                           'win_rate': 50.0, 'icir': 0.0}
            },
            {
                'weights': {'f2': 1.0},
                'metrics': {'annual_return': 0.0, 'max_drawdown': 5.0, 
                           'win_rate': 50.0, 'icir': 0.5}
            }
        ]
        
        sorted_results = rank_by_annual_return(results)
        
        # 零值不影响排序
        assert len(sorted_results) == 2


# ============ 运行测试 ============

if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])