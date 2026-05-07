#!/usr/bin/env python3
"""
智能采样+分层搜索快速测试脚本
测试规模：10因子
"""
import sys
sys.path.insert(0, '/home/admin/.openclaw/workspace/yunzhou/factor_ic_analyzer')

import pandas as pd
import numpy as np
from datetime import datetime

print("=" * 60)
print("智能采样+分层搜索 快速验证测试")
print("=" * 60)
print(f"测试时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
print()

# ========== 测试1: 函数基础功能验证 ==========
print("【测试1】函数基础功能验证")
print("-" * 60)

try:
    from versions.v2.optimizer.smart_sampling import (
        smart_sample_combinations,
        genetic_algorithm_search,
        greedy_forward_selection,
        importance_weighted_sampling,
        check_memory_available
    )
    from versions.v2.optimizer.hierarchical_search import (
        hierarchical_layer_search,
        search_layer_original,
        search_layer_new_top,
        search_layer_mixed
    )
    print("✓ 所有函数导入成功")
except Exception as e:
    print(f"✗ 导入失败: {e}")
    sys.exit(1)

# ========== 测试2: 内存检查函数 ==========
print()
print("【测试2】内存检查函数")
print("-" * 60)

is_ok, available_gb = check_memory_available()
print(f"内存状态: {'充足' if is_ok else '不足'}")
print(f"可用内存: {available_gb:.2f} GB")
print(f"阈值: 1.0 GB")
print("✓ 内存检查函数正常" if is_ok else "⚠ 内存偏低但继续测试")

# ========== 测试3: 智能采样核心函数 ==========
print()
print("【测试3】智能采样核心函数测试（10因子）")
print("-" * 60)

# 构造测试数据
np.random.seed(42)
test_factors = [f"factor_{i:02d}" for i in range(10)]
test_ic_data = {
    f: {
        'icir': np.random.uniform(0.5, 2.0),
        'mean': np.random.uniform(0.02, 0.08),
        'std': np.random.uniform(0.01, 0.03)
    }
    for f in test_factors
}

print(f"测试因子数: {len(test_factors)}")
print(f"因子ICIR范围: {min(d['icir'] for d in test_ic_data.values()):.3f} - {max(d['icir'] for d in test_ic_data.values()):.3f}")

# 测试遗传算法
print("\n[3.1] 遗传算法搜索...")
try:
    ga_config = {
        'population_size': 20,
        'generations': 5,
        'mutation_rate': 0.1,
        'crossover_rate': 0.7,
        'elitism_rate': 0.1,
        'max_combinations': 50
    }
    ga_candidates = genetic_algorithm_search(
        factors=test_factors,
        ic_data=test_ic_data,
        config=ga_config
    )
    print(f"✓ 遗传算法生成候选数: {len(ga_candidates)}")
    if ga_candidates:
        print(f"  示例候选: ICIR={ga_candidates[0].get('icir', 0):.3f}, 因子数={len(ga_candidates[0].get('weights', {}))}")
except Exception as e:
    print(f"✗ 遗传算法失败: {e}")
    ga_candidates = []

# 测试贪心前向选择
print("\n[3.2] 贪心前向选择...")
try:
    greedy_config = {
        'max_factors': 5,
        'max_combinations': 30
    }
    greedy_candidates = greedy_forward_selection(
        factors=test_factors,
        ic_data=test_ic_data,
        config=greedy_config
    )
    print(f"✓ 贪心前向选择生成候选数: {len(greedy_candidates)}")
    if greedy_candidates:
        print(f"  示例候选: ICIR={greedy_candidates[0].get('icir', 0):.3f}, 因子数={len(greedy_candidates[0].get('weights', {}))}")
except Exception as e:
    print(f"✗ 贪心前向选择失败: {e}")
    greedy_candidates = []

# 测试加权采样
print("\n[3.3] 重要性加权采样...")
try:
    weighted_config = {
        'max_combinations': 30,
        'min_factors': 2,
        'max_factors': 6
    }
    weighted_candidates = importance_weighted_sampling(
        factors=test_factors,
        ic_data=test_ic_data,
        config=weighted_config
    )
    print(f"✓ 加权采样生成候选数: {len(weighted_candidates)}")
    if weighted_candidates:
        print(f"  示例候选: ICIR={weighted_candidates[0].get('icir', 0):.3f}, 因子数={len(weighted_candidates[0].get('weights', {}))}")
except Exception as e:
    print(f"✗ 加权采样失败: {e}")
    weighted_candidates = []

# 测试智能采样入口
print("\n[3.4] 智能采样组合入口...")
try:
    smart_config = {
        'ga_ratio': 0.4,
        'greedy_ratio': 0.3,
        'weighted_ratio': 0.3,
        'max_samples': 100,
        'ga': {'population_size': 15, 'generations': 3},
        'greedy': {'max_factors': 5},
        'weighted': {'min_factors': 2, 'max_factors': 5}
    }
    smart_candidates = smart_sample_combinations(
        factors=test_factors,
        ic_data=test_ic_data,
        max_samples=100,
        config=smart_config
    )
    print(f"✓ 智能采样生成候选数: {len(smart_candidates)}")
    if smart_candidates:
        sources = {}
        for c in smart_candidates:
            src = c.get('source', 'unknown')
            sources[src] = sources.get(src, 0) + 1
        print(f"  来源分布: {sources}")
except Exception as e:
    print(f"✗ 智能采样失败: {e}")
    import traceback
    traceback.print_exc()
    smart_candidates = []

# ========== 测试4: 分层搜索函数 ==========
print()
print("【测试4】分层搜索函数测试")
print("-" * 60)

# 设置原有因子（前5个）
original_indices = list(range(5))
original_factors = [test_factors[i] for i in original_indices]
new_factors = test_factors[5:]

print(f"原有因子 (5个): {original_factors}")
print(f"新增因子 (5个): {new_factors}")

# 测试 Layer 1
print("\n[4.1] Layer 1 - 原有因子组合搜索...")
try:
    layer1_candidates = search_layer_original(
        original_factors=original_factors,
        ic_data=test_ic_data,
        max_combinations=20
    )
    print(f"✓ Layer 1 生成候选数: {len(layer1_candidates)}")
except Exception as e:
    print(f"✗ Layer 1 失败: {e}")
    layer1_candidates = []

# 测试 Layer 2
print("\n[4.2] Layer 2 - 新增Top因子组合搜索...")
try:
    layer2_candidates = search_layer_new_top(
        new_factors=new_factors,
        ic_data=test_ic_data,
        top_n=3,
        max_combinations=30
    )
    print(f"✓ Layer 2 生成候选数: {len(layer2_candidates)}")
except Exception as e:
    print(f"✗ Layer 2 失败: {e}")
    layer2_candidates = []

# 测试 Layer 3
print("\n[4.3] Layer 3 - 混合组合搜索...")
try:
    layer3_candidates = search_layer_mixed(
        original_factors=original_factors,
        new_factors=new_factors,
        ic_data=test_ic_data,
        max_combinations=40
    )
    print(f"✓ Layer 3 生成候选数: {len(layer3_candidates)}")
    # 检查新增因子参与率
    if layer3_candidates:
        all_factors_in_layer3 = set()
        for c in layer3_candidates:
            all_factors_in_layer3.update(c.get('weights', {}).keys())
        new_factor_count = len(all_factors_in_layer3 & set(new_factors))
        participation_rate = new_factor_count / len(new_factors) * 100 if new_factors else 0
        print(f"  新增因子参与数: {new_factor_count}/{len(new_factors)}")
        print(f"  新增因子参与率: {participation_rate:.1f}%")
except Exception as e:
    print(f"✗ Layer 3 失败: {e}")
    layer3_candidates = []

# 测试分层搜索入口
print("\n[4.4] 分层搜索入口...")
try:
    hierarchical_config = {
        'layers': [
            {'max_combinations': 20},
            {'top_n': 3, 'max_combinations': 30},
            {'max_combinations': 40}
        ]
    }
    hierarchical_candidates = hierarchical_layer_search(
        factors=test_factors,
        ic_data=test_ic_data,
        config=hierarchical_config,
        original_indices=original_indices
    )
    print(f"✓ 分层搜索生成候选总数: {len(hierarchical_candidates)}")
    if hierarchical_candidates:
        layer_dist = {}
        for c in hierarchical_candidates:
            layer = c.get('layer', 'unknown')
            layer_dist[layer] = layer_dist.get(layer, 0) + 1
        print(f"  层级分布: {layer_dist}")
except Exception as e:
    print(f"✗ 分层搜索失败: {e}")
    import traceback
    traceback.print_exc()
    hierarchical_candidates = []

# ========== 测试总结 ==========
print()
print("=" * 60)
print("测试总结")
print("=" * 60)

tests = [
    ("函数导入", True),
    ("内存检查", is_ok),
    ("遗传算法", len(ga_candidates) > 0),
    ("贪心前向选择", len(greedy_candidates) > 0),
    ("加权采样", len(weighted_candidates) > 0),
    ("智能采样组合", len(smart_candidates) > 0),
    ("Layer 1 搜索", len(layer1_candidates) > 0),
    ("Layer 2 搜索", len(layer2_candidates) > 0),
    ("Layer 3 搜索", len(layer3_candidates) > 0),
    ("分层搜索入口", len(hierarchical_candidates) > 0)
]

passed = sum(1 for _, status in tests if status)
print(f"\n测试通过: {passed}/{len(tests)}")
for name, status in tests:
    print(f"  {'✓' if status else '✗'} {name}")

print()
print("=" * 60)
print(f"快速验证完成: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
print("=" * 60)