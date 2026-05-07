#!/usr/bin/env python3
"""
方案C实施效果验证脚本
验证步骤：
1. 配置一致性验证
2. 自动验证功能验证
3. 实例级属性验证
4. 矛盾检测验证

作者: 云汐（测试工程师）
日期: 2026-05-06
"""

import sys
import json
from pathlib import Path

# 添加项目路径
PROJECT_ROOT = Path(__file__).parent
sys.path.insert(0, str(PROJECT_ROOT))

# 验证结果收集
verification_results = []

def add_result(test_item, expected, actual, passed):
    """添加验证结果"""
    verification_results.append({
        '验证项': test_item,
        '预期': expected,
        '实际': actual,
        '通过': '✅' if passed else '❌'
    })

print("=" * 80)
print("方案C实施效果验证报告")
print("=" * 80)

# ============================================================================
# 步骤1：配置一致性验证
# ============================================================================
print("\n【步骤1】配置一致性验证")
print("-" * 80)

# 1.1 检查 weight_optimizer.py 的 IC_DIRECTIONS
print("\n1.1 检查 weight_optimizer.py 的 IC_DIRECTIONS...")
try:
    from weight_optimizer import IC_DIRECTIONS as wo_ic_directions
    
    volume_ratio_dir = wo_ic_directions.get('volume_ratio', 'NOT_FOUND')
    turnover_surge_dir = wo_ic_directions.get('turnover_surge', 'NOT_FOUND')
    
    print(f"  volume_ratio: {volume_ratio_dir}")
    print(f"  turnover_surge: {turnover_surge_dir}")
    
    # 根据v2_scoring_engine.py的REVERSE_FACTORS注释，volume_ratio应该是negative
    expected_volume = 'negative'  # 因为IC=-0.0294
    expected_turnover = 'negative'  # 因为IC=-0.0475
    
    vol_passed = volume_ratio_dir == expected_volume
    turn_passed = turnover_surge_dir == expected_turnover
    
    add_result(
        'weight_optimizer.py IC_DIRECTIONS[volume_ratio]',
        expected_volume,
        volume_ratio_dir,
        vol_passed
    )
    add_result(
        'weight_optimizer.py IC_DIRECTIONS[turnover_surge]',
        expected_turnover,
        turnover_surge_dir,
        turn_passed
    )
    
except Exception as e:
    print(f"  ❌ 加载失败: {e}")
    add_result('weight_optimizer.py IC_DIRECTIONS', '加载成功', f'加载失败: {e}', False)

# 1.2 检查 precompute_optimizer_multi_period.py 的 IC_DIRECTIONS
print("\n1.2 检查 precompute_optimizer_multi_period.py 的 IC_DIRECTIONS...")
try:
    sys.path.insert(0, str(PROJECT_ROOT / 'versions' / 'v2' / 'scripts'))
    from precompute_optimizer_multi_period import IC_DIRECTIONS as po_ic_directions
    
    volume_ratio_dir = po_ic_directions.get('volume_ratio', 'NOT_FOUND')
    turnover_surge_dir = po_ic_directions.get('turnover_surge', 'NOT_FOUND')
    
    print(f"  volume_ratio: {volume_ratio_dir}")
    print(f"  turnover_surge: {turnover_surge_dir}")
    
    vol_passed = volume_ratio_dir == expected_volume
    turn_passed = turnover_surge_dir == expected_turnover
    
    add_result(
        'precompute_optimizer_multi_period.py IC_DIRECTIONS[volume_ratio]',
        expected_volume,
        volume_ratio_dir,
        vol_passed
    )
    add_result(
        'precompute_optimizer_multi_period.py IC_DIRECTIONS[turnover_surge]',
        expected_turnover,
        turnover_surge_dir,
        turn_passed
    )
    
except Exception as e:
    print(f"  ❌ 加载失败: {e}")
    add_result('precompute_optimizer_multi_period.py IC_DIRECTIONS', '加载成功', f'加载失败: {e}', False)

# 1.3 检查 v2_scoring_engine.py 的 REVERSE_FACTORS
print("\n1.3 检查 v2_scoring_engine.py 的 REVERSE_FACTORS...")
try:
    from v2_scoring_engine import V2ScoringEngine
    
    reverse_factors = V2ScoringEngine.REVERSE_FACTORS
    
    has_volume_ratio = 'volume_ratio' in reverse_factors
    has_turnover_surge = 'turnover_surge' in reverse_factors
    
    print(f"  volume_ratio in REVERSE_FACTORS: {has_volume_ratio}")
    print(f"  turnover_surge in REVERSE_FACTORS: {has_turnover_surge}")
    
    # 因为IC为负值，应该在REVERSE_FACTORS中
    add_result(
        'v2_scoring_engine.py REVERSE_FACTORS包含volume_ratio',
        'True',
        str(has_volume_ratio),
        has_volume_ratio
    )
    add_result(
        'v2_scoring_engine.py REVERSE_FACTORS包含turnover_surge',
        'True',
        str(has_turnover_surge),
        has_turnover_surge
    )
    
except Exception as e:
    print(f"  ❌ 加载失败: {e}")
    add_result('v2_scoring_engine.py REVERSE_FACTORS', '加载成功', f'加载失败: {e}', False)

# ============================================================================
# 步骤2：自动验证功能验证
# ============================================================================
print("\n【步骤2】自动验证功能验证")
print("-" * 80)

print("\n2.1 导入 ic_directions_validator 模块...")
try:
    from versions.v2.optimizer.ic_directions_validator import validate_ic_directions_config
    print("  ✅ 模块导入成功")
    add_result('ic_directions_validator模块导入', '成功', '成功', True)
except Exception as e:
    print(f"  ❌ 模块导入失败: {e}")
    add_result('ic_directions_validator模块导入', '成功', f'失败: {e}', False)
    validate_ic_directions_config = None

if validate_ic_directions_config:
    print("\n2.2 调用 validate_ic_directions_config 函数...")
    try:
        # 使用weight_optimizer的IC_DIRECTIONS进行验证
        result = validate_ic_directions_config(
            ic_directions=wo_ic_directions,
            return_col='forward_return_1d',
            auto_fix=True
        )
        
        print(f"\n  验证结果结构:")
        print(f"    - valid: {result.get('valid')}")
        print(f"    - conflicts: {len(result.get('conflicts', []))} 个矛盾")
        print(f"    - corrected: {result.get('corrected')}")
        print(f"    - warnings: {result.get('warnings')}")
        
        # 检查返回值结构
        has_valid = 'valid' in result
        has_conflicts = 'conflicts' in result
        has_corrected = 'corrected' in result
        has_warnings = 'warnings' in result
        
        structure_ok = all([has_valid, has_conflicts, has_corrected, has_warnings])
        
        print(f"\n  返回值结构完整性:")
        print(f"    - valid字段: {'✅' if has_valid else '❌'}")
        print(f"    - conflicts字段: {'✅' if has_conflicts else '❌'}")
        print(f"    - corrected字段: {'✅' if has_corrected else '❌'}")
        print(f"    - warnings字段: {'✅' if has_warnings else '❌'}")
        
        add_result(
            'validate_ic_directions_config返回值结构',
            '包含valid/conflicts/corrected/warnings',
            '完整' if structure_ok else '不完整',
            structure_ok
        )
        
        # 显示发现的矛盾
        if result.get('conflicts'):
            print(f"\n  发现的矛盾:")
            for conflict in result['conflicts']:
                print(f"    - {conflict['factor']}: 配置={conflict['config_direction']}, "
                      f"实际={conflict['actual_direction']}, IC={conflict['ic_mean']:.4f}")
        
    except Exception as e:
        print(f"  ❌ 函数调用失败: {e}")
        import traceback
        traceback.print_exc()
        add_result('validate_ic_directions_config函数调用', '成功', f'失败: {e}', False)

# ============================================================================
# 步骤3：实例级属性验证
# ============================================================================
print("\n【步骤3】实例级属性验证")
print("-" * 80)

print("\n3.1 创建 WeightOptimizer 实例...")
try:
    from weight_optimizer import WeightOptimizer
    
    optimizer = WeightOptimizer()
    print("  ✅ WeightOptimizer 实例创建成功")
    add_result('WeightOptimizer实例创建', '成功', '成功', True)
    
    print("\n3.2 检查 _ic_directions 属性...")
    if hasattr(optimizer, '_ic_directions'):
        ic_dirs = optimizer._ic_directions
        print(f"  ✅ _ic_directions 属性存在")
        print(f"  值: {ic_dirs}")
        
        # 检查是否为修正后的配置
        has_volume = 'volume_ratio' in ic_dirs
        has_turnover = 'turnover_surge' in ic_dirs
        
        add_result(
            'WeightOptimizer._ic_directions属性存在',
            '存在',
            '存在',
            True
        )
        add_result(
            'WeightOptimizer._ic_directions包含volume_ratio',
            'True',
            str(has_volume),
            has_volume
        )
        add_result(
            'WeightOptimizer._ic_directions包含turnover_surge',
            'True',
            str(has_turnover),
            has_turnover
        )
    else:
        print(f"  ❌ _ic_directions 属性不存在")
        add_result('WeightOptimizer._ic_directions属性', '存在', '不存在', False)
        
except Exception as e:
    print(f"  ❌ 创建实例失败: {e}")
    import traceback
    traceback.print_exc()
    add_result('WeightOptimizer实例创建', '成功', f'失败: {e}', False)

# ============================================================================
# 步骤4：矛盾检测验证
# ============================================================================
print("\n【步骤4】矛盾检测验证")
print("-" * 80)

if validate_ic_directions_config:
    print("\n4.1 模拟矛盾配置...")
    
    # 创建一个故意设置错误的IC_DIRECTIONS
    wrong_ic_directions = {
        'rsi': 'positive',
        'bollinger_pb': 'positive',
        'volume_ratio': 'positive',  # 故意设置错误（实际应该是negative）
        'turnover_surge': 'positive',  # 故意设置错误（实际应该是negative）
    }
    
    print(f"  模拟的矛盾配置: volume_ratio=positive, turnover_surge=positive")
    
    try:
        result = validate_ic_directions_config(
            ic_directions=wrong_ic_directions,
            return_col='forward_return_1d',
            auto_fix=True
        )
        
        print(f"\n  验证结果:")
        print(f"    - valid: {result.get('valid')}")
        print(f"    - conflicts数量: {len(result.get('conflicts', []))}")
        
        if result.get('conflicts'):
            print(f"    - 检测到的矛盾:")
            for conflict in result['conflicts']:
                print(f"      * {conflict['factor']}: 配置={conflict['config_direction']}, "
                      f"实际={conflict['actual_direction']}, IC={conflict['ic_mean']:.4f}")
        
        print(f"\n  修正后的配置:")
        print(f"    - volume_ratio: {result['corrected'].get('volume_ratio')}")
        print(f"    - turnover_surge: {result['corrected'].get('turnover_surge')}")
        
        # 验证检测和修正功能
        detected_conflicts = len(result.get('conflicts', [])) > 0
        fixed_volume = result['corrected'].get('volume_ratio') == 'negative'
        fixed_turnover = result['corrected'].get('turnover_surge') == 'negative'
        
        add_result(
            '矛盾检测功能',
            '检测到矛盾',
            f'检测到{len(result.get("conflicts", []))}个矛盾',
            detected_conflicts
        )
        add_result(
            '矛盾修正功能(volume_ratio)',
            'negative',
            result['corrected'].get('volume_ratio'),
            fixed_volume
        )
        add_result(
            '矛盾修正功能(turnover_surge)',
            'negative',
            result['corrected'].get('turnover_surge'),
            fixed_turnover
        )
        
    except Exception as e:
        print(f"  ❌ 矛盾检测验证失败: {e}")
        import traceback
        traceback.print_exc()
        add_result('矛盾检测验证', '成功', f'失败: {e}', False)

# ============================================================================
# 输出验证结果表格
# ============================================================================
print("\n" + "=" * 80)
print("验证结果汇总")
print("=" * 80)

# 输出表格
print("\n{:<60} {:<15} {:<20} {:<10}".format('验证项', '预期', '实际', '结果'))
print("-" * 110)

passed_count = 0
failed_count = 0

for result in verification_results:
    print("{:<60} {:<15} {:<20} {:<10}".format(
        result['验证项'][:58],
        str(result['预期'])[:13],
        str(result['实际'])[:18],
        result['通过']
    ))
    if result['通过'] == '✅':
        passed_count += 1
    else:
        failed_count += 1

print("-" * 110)
print(f"\n总计: {len(verification_results)} 项 | ✅ 通过: {passed_count} | ❌ 失败: {failed_count}")

# 总体评价
print("\n" + "=" * 80)
print("总体评价")
print("=" * 80)

if failed_count == 0:
    print("✅ 所有验证项均通过，方案C实施效果良好！")
elif failed_count <= 2:
    print("⚠️  大部分验证项通过，存在少量问题需要关注。")
else:
    print("❌ 多项验证失败，需要检查实施方案。")

# 详细问题列表
if failed_count > 0:
    print("\n失败项详情:")
    for result in verification_results:
        if result['通过'] == '❌':
            print(f"  - {result['验证项']}")
            print(f"    预期: {result['预期']}, 实际: {result['实际']}")

print("\n" + "=" * 80)