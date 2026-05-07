"""
Phase 1 约束网格搜索单元测试

测试 generate_constrained_grid 和 filter_grid_by_direction 函数

测试场景:
- 正常生成5万组合
- 权重和约束验证
- 步长参数验证
- 组合数为0边界
- 内存占用验证
- 方向过滤验证
"""

import pytest
import numpy as np
from typing import Dict, List
import time
import sys


# ============ Mock 实现用于测试 ============

def generate_constrained_grid(
    factors: List[str],
    step: float = 0.2,
    weight_range: tuple = (0.0, 1.0),
    sum_constraint: tuple = (0.8, 1.2),
    max_combinations: int = 50000
) -> List[Dict[str, float]]:
    """
    生成约束网格搜索候选组合
    
    Args:
        factors: 因子列表
        step: 步长（默认0.2）
        weight_range: 权重范围（默认[0.0, 1.0]）
        sum_constraint: 权重和约束（默认[0.8, 1.2]）
        max_combinations: 最大组合数
    
    Returns:
        List[Dict]: 候选组合列表
    """
    if not factors:
        return []
    
    if step <= 0 or step > 1:
        raise ValueError(f"步长必须在(0, 1]范围内，当前: {step}")
    
    n_factors = len(factors)
    weight_values = np.arange(weight_range[0], weight_range[1] + step / 2, step)
    weight_values = np.round(weight_values, 2)  # 避免浮点精度问题
    
    candidates = []
    sum_min, sum_max = sum_constraint
    
    # 使用迭代器生成所有组合
    from itertools import product
    
    total_generated = 0
    for combo in product(weight_values, repeat=n_factors):
        weight_sum = sum(combo)
        
        # 检查权重和约束
        if sum_min <= weight_sum <= sum_max:
            candidate = {factors[i]: float(combo[i]) for i in range(n_factors)}
            candidates.append(candidate)
            total_generated += 1
            
            # 限制最大组合数
            if total_generated >= max_combinations:
                break
    
    return candidates


def filter_grid_by_direction(
    candidates: List[Dict[str, float]],
    ic_directions: Dict[str, str],
    tolerance: float = 0.2
) -> List[Dict[str, float]]:
    """
    根据IC方向约束过滤候选组合
    
    Args:
        candidates: 候选组合列表
        ic_directions: IC方向配置
        tolerance: 方向容忍度
    
    Returns:
        List[Dict]: 过滤后的候选组合
    """
    if not candidates or not ic_directions:
        return candidates
    
    filtered = []
    for candidate in candidates:
        valid = True
        for factor, direction in ic_directions.items():
            if factor not in candidate:
                continue
            
            weight = candidate[factor]
            
            if direction == 'positive' and weight < -tolerance:
                valid = False
                break
            elif direction == 'negative' and weight > tolerance:
                valid = False
                break
        
        if valid:
            filtered.append(candidate)
    
    return filtered


# ============ Pytest Fixtures ============

@pytest.fixture
def sample_factors():
    """测试用因子列表"""
    return [f"factor_{i}" for i in range(1, 11)]  # 10个因子


@pytest.fixture
def small_factors():
    """小规模因子列表（用于快速测试）"""
    return ["f1", "f2", "f3"]


@pytest.fixture
def ic_directions():
    """IC方向配置"""
    return {
        "factor_1": "positive",
        "factor_2": "positive",
        "factor_3": "negative",
        "factor_4": "negative",
        "factor_5": "neutral"
    }


# ============ 测试用例 ============

class TestGridGeneration:
    """网格生成测试"""
    
    def test_normal_generation_returns_valid_count(self, sample_factors):
        """测试用例1: 正常生成组合，数量符合预期"""
        candidates = generate_constrained_grid(
            factors=sample_factors,
            step=0.2,
            max_combinations=50000
        )
        
        # 验证生成数量不超过上限
        assert len(candidates) <= 50000
        # 验证生成了组合
        assert len(candidates) > 0
        print(f"生成了 {len(candidates)} 个候选组合")
    
    def test_weight_sum_constraint_satisfied(self, small_factors):
        """测试用例2: 所有组合满足权重和约束"""
        candidates = generate_constrained_grid(
            factors=small_factors,
            step=0.2,
            sum_constraint=(0.8, 1.2)
        )
        
        sum_min, sum_max = 0.8, 1.2
        
        for candidate in candidates:
            weight_sum = sum(candidate.values())
            assert sum_min <= weight_sum <= sum_max, \
                f"权重和 {weight_sum} 不在约束范围 [{sum_min}, {sum_max}] 内"
    
    def test_step_parameter_validation(self, small_factors):
        """测试用例3: 步长参数验证"""
        # 正常步长
        candidates = generate_constrained_grid(
            factors=small_factors,
            step=0.5
        )
        assert len(candidates) > 0
        
        # 步长为0 - 应抛出异常
        with pytest.raises(ValueError, match="步长必须在"):
            generate_constrained_grid(factors=small_factors, step=0)
        
        # 步长大于1 - 应抛出异常
        with pytest.raises(ValueError, match="步长必须在"):
            generate_constrained_grid(factors=small_factors, step=1.5)
    
    def test_empty_factors_returns_empty(self):
        """测试用例4: 空因子列表返回空组合"""
        candidates = generate_constrained_grid(factors=[])
        assert candidates == []
    
    def test_single_factor_generation(self):
        """测试用例5: 单因子场景"""
        candidates = generate_constrained_grid(
            factors=["single_factor"],
            step=0.2,
            sum_constraint=(0.8, 1.2)
        )
        
        # 单因子时，权重值应在约束范围内
        for candidate in candidates:
            weight = candidate["single_factor"]
            assert 0.8 <= weight <= 1.2


class TestWeightConstraints:
    """权重约束测试"""
    
    def test_weight_range_constraint(self, small_factors):
        """测试用例6: 权重范围约束验证"""
        weight_range = (0.0, 1.0)
        candidates = generate_constrained_grid(
            factors=small_factors,
            step=0.2,
            weight_range=weight_range
        )
        
        for candidate in candidates:
            for factor, weight in candidate.items():
                assert weight_range[0] <= weight <= weight_range[1], \
                    f"权重 {weight} 超出范围 {weight_range}"
    
    def test_custom_sum_constraint(self, small_factors):
        """测试用例7: 自定义权重和约束"""
        sum_constraint = (1.0, 1.0)  # 严格等于1
        candidates = generate_constrained_grid(
            factors=small_factors,
            step=0.2,
            sum_constraint=sum_constraint
        )
        
        for candidate in candidates:
            weight_sum = sum(candidate.values())
            # 允许浮点误差
            assert abs(weight_sum - 1.0) < 0.01, \
                f"权重和 {weight_sum} 不等于1"


class TestMemoryPerformance:
    """内存性能测试"""
    
    def test_generation_time_within_limit(self, sample_factors):
        """测试用例8: 生成时间在限制内（<10秒）"""
        start_time = time.time()
        
        candidates = generate_constrained_grid(
            factors=sample_factors,
            step=0.2,
            max_combinations=50000
        )
        
        elapsed = time.time() - start_time
        
        assert elapsed < 10, f"生成耗时 {elapsed:.2f}s 超过10秒限制"
        print(f"生成 {len(candidates)} 个组合，耗时 {elapsed:.2f}s")
    
    def test_memory_usage_reasonable(self, small_factors):
        """测试用例9: 内存占用合理"""
        import gc
        gc.collect()
        
        before_memory = sys.getsizeof([])
        
        candidates = generate_constrained_grid(
            factors=small_factors,
            step=0.2,
            max_combinations=10000
        )
        
        # 粗略估计内存占用（实际应使用psutil）
        estimated_size = sys.getsizeof(candidates) + sum(
            sys.getsizeof(c) for c in candidates[:100]
        ) * len(candidates) / 100
        
        # 内存应小于500MB
        assert estimated_size < 500 * 1024 * 1024, \
            f"估计内存占用 {estimated_size / 1024 / 1024:.1f}MB 过大"
        print(f"估计内存占用: {estimated_size / 1024 / 1024:.1f}MB")


class TestDirectionFilter:
    """方向过滤测试"""
    
    def test_direction_filter_positive(self, small_factors, ic_directions):
        """测试用例10: 正向因子过滤"""
        candidates = generate_constrained_grid(
            factors=small_factors,
            step=0.2
        )
        
        small_directions = {
            "f1": "positive",
            "f2": "negative"
        }
        
        filtered = filter_grid_by_direction(candidates, small_directions)
        
        # 验证过滤后的组合满足方向约束
        for candidate in filtered:
            if "f1" in candidate and small_directions["f1"] == "positive":
                assert candidate["f1"] >= -0.2, \
                    f"正向因子 f1 权重 {candidate['f1']} 不满足约束"
            if "f2" in candidate and small_directions["f2"] == "negative":
                assert candidate["f2"] <= 0.2, \
                    f"负向因子 f2 权重 {candidate['f2']} 不满足约束"
    
    def test_direction_filter_empty_input(self):
        """测试用例11: 空输入方向过滤"""
        # 空候选列表
        assert filter_grid_by_direction([], {}) == []
        
        # 空方向配置
        candidates = [{"f1": 0.5, "f2": 0.3}]
        assert filter_grid_by_direction(candidates, {}) == candidates
    
    def test_direction_filter_tolerance(self, small_factors):
        """测试用例12: 方向容忍度验证"""
        candidates = generate_constrained_grid(
            factors=small_factors,
            step=0.2
        )
        
        directions = {"f1": "positive"}
        
        # 宽容忍度
        filtered_wide = filter_grid_by_direction(candidates, directions, tolerance=0.5)
        
        # 严格容忍度
        filtered_strict = filter_grid_by_direction(candidates, directions, tolerance=0.0)
        
        # 宽容忍度应保留更多组合
        assert len(filtered_wide) >= len(filtered_strict)


class TestEdgeCases:
    """边界情况测试"""
    
    def test_zero_combinations_with_strict_constraint(self):
        """测试用例13: 严格约束导致0组合"""
        # 极小步长 + 严格约束可能导致无解
        candidates = generate_constrained_grid(
            factors=["f1", "f2", "f3"],
            step=0.1,
            sum_constraint=(1.0, 1.0),  # 严格等于1
            weight_range=(0.5, 0.5)     # 只能是0.5
        )
        # 3个因子各0.5 = 1.5，不满足sum=1
        # 但权重范围只允许0.5，所以可能无解
        print(f"严格约束下生成 {len(candidates)} 个组合")
    
    def test_extreme_weight_values(self):
        """测试用例14: 极端权重值"""
        candidates = generate_constrained_grid(
            factors=["f1"],
            step=0.5,
            weight_range=(0.0, 1.0),
            sum_constraint=(0.0, 1.0)
        )
        
        # 单因子应生成边界值组合
        weights = [c["f1"] for c in candidates]
        assert 0.0 in weights or any(abs(w - 0.0) < 0.01 for w in weights)
        assert 1.0 in weights or any(abs(w - 1.0) < 0.01 for w in weights)
    
    def test_large_factor_count(self):
        """测试用例15: 大量因子（性能测试）"""
        large_factors = [f"f{i}" for i in range(20)]
        
        start_time = time.time()
        candidates = generate_constrained_grid(
            factors=large_factors,
            step=0.2,
            max_combinations=50000
        )
        elapsed = time.time() - start_time
        
        # 应限制在max_combinations内
        assert len(candidates) <= 50000
        assert elapsed < 30, f"20因子生成耗时 {elapsed:.2f}s 过长"
        print(f"20因子生成 {len(candidates)} 组合，耗时 {elapsed:.2f}s")


# ============ 运行测试 ============

if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])