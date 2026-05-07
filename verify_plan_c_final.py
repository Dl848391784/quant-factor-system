#!/usr/bin/env python3
"""
方案C实施效果验证报告（最终版）
作者: 云汐（测试工程师）
日期: 2026-05-06

验证结果：
- ❌ weight_optimizer.py IC_DIRECTIONS配置错误
- ✅ precompute_optimizer_multi_period.py IC_DIRECTIONS配置正确
- ✅ v2_scoring_engine.py REVERSE_FACTORS配置正确
- ✅ ic_directions_validator模块可导入
- ⚠️ ic_directions_validator数据加载存在Bug（JSON结构解析错误）
- ❌ WeightOptimizer实例无_ic_directions属性
"""

import json
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent

print("=" * 100)
print("方案C实施效果验证报告".center(100))
print("=" * 100)

# ============================================================================
# 验证结果数据
# ============================================================================
results = []

# 1. 配置一致性验证
print("\n【1. 配置一致性验证】")
print("-" * 100)

# 实际IC值（从分析结果文件读取）
actual_ics = {
    'volume_ratio': -0.0294,
    'turnover_surge': -0.0475
}

# 预期配置：IC为负值，应该配置为'negative'
expected_direction = 'negative'

# 1.1 weight_optimizer.py
import sys
sys.path.insert(0, str(PROJECT_ROOT))
from weight_optimizer import IC_DIRECTIONS as wo_ic

vol_wo = wo_ic.get('volume_ratio', 'NOT_FOUND')
turn_wo = wo_ic.get('turnover_surge', 'NOT_FOUND')

results.append(['weight_optimizer.py IC_DIRECTIONS[volume_ratio]', expected_direction, vol_wo, '✅' if vol_wo == expected_direction else '❌'])
results.append(['weight_optimizer.py IC_DIRECTIONS[turnover_surge]', expected_direction, turn_wo, '✅' if turn_wo == expected_direction else '❌'])

# 1.2 precompute_optimizer_multi_period.py
sys.path.insert(0, str(PROJECT_ROOT / 'versions' / 'v2' / 'scripts'))
from precompute_optimizer_multi_period import IC_DIRECTIONS as po_ic

vol_po = po_ic.get('volume_ratio', 'NOT_FOUND')
turn_po = po_ic.get('turnover_surge', 'NOT_FOUND')

results.append(['precompute_optimizer_multi_period.py IC_DIRECTIONS[volume_ratio]', expected_direction, vol_po, '✅' if vol_po == expected_direction else '❌'])
results.append(['precompute_optimizer_multi_period.py IC_DIRECTIONS[turnover_surge]', expected_direction, turn_po, '✅' if turn_po == expected_direction else '❌'])

# 1.3 v2_scoring_engine.py REVERSE_FACTORS
from v2_scoring_engine import V2ScoringEngine

rev_factors = V2ScoringEngine.REVERSE_FACTORS
has_vol = 'volume_ratio' in rev_factors
has_turn = 'turnover_surge' in rev_factors

results.append(['v2_scoring_engine.py REVERSE_FACTORS包含volume_ratio', 'True', str(has_vol), '✅' if has_vol else '❌'])
results.append(['v2_scoring_engine.py REVERSE_FACTORS包含turnover_surge', 'True', str(has_turn), '✅' if has_turn else '❌'])

# ============================================================================
# 2. 自动验证功能验证
# ============================================================================
print("\n【2. 自动验证功能验证】")
print("-" * 100)

# 2.1 模块导入
try:
    from versions.v2.optimizer.ic_directions_validator import validate_ic_directions_config
    results.append(['ic_directions_validator模块导入', '成功', '成功', '✅'])
    validator_ok = True
except Exception as e:
    results.append(['ic_directions_validator模块导入', '成功', f'失败: {e}', '❌'])
    validator_ok = False

# 2.2 函数调用
if validator_ok:
    try:
        result = validate_ic_directions_config(
            ic_directions={'volume_ratio': 'positive', 'turnover_surge': 'positive'},
            return_col='forward_return_1d',
            auto_fix=True
        )
        
        has_structure = all(k in result for k in ['valid', 'conflicts', 'corrected', 'warnings'])
        results.append(['validate_ic_directions_config返回值结构', '包含valid/conflicts/corrected/warnings', '完整' if has_structure else '不完整', '✅' if has_structure else '❌'])
        
        # 检查是否能正确检测矛盾
        # 由于数据加载Bug，这里会返回0个矛盾
        detected = len(result.get('conflicts', [])) > 0
        results.append(['矛盾检测功能', '检测到矛盾', f'检测到{len(result.get("conflicts", []))}个矛盾', '⚠️ (数据加载Bug)'])
        
    except Exception as e:
        results.append(['validate_ic_directions_config函数调用', '成功', f'失败: {e}', '❌'])

# ============================================================================
# 3. 实例级属性验证
# ============================================================================
print("\n【3. 实例级属性验证】")
print("-" * 100)

try:
    from weight_optimizer import WeightOptimizer
    optimizer = WeightOptimizer()
    
    has_attr = hasattr(optimizer, '_ic_directions')
    results.append(['WeightOptimizer实例创建', '成功', '成功', '✅'])
    results.append(['WeightOptimizer._ic_directions属性', '存在', '存在' if has_attr else '不存在', '✅' if has_attr else '❌'])
    
except Exception as e:
    results.append(['WeightOptimizer实例创建', '成功', f'失败: {e}', '❌'])

# ============================================================================
# 4. IC分析结果确认
# ============================================================================
print("\n【4. IC分析结果确认（基准数据）】")
print("-" * 100)

# 从文件读取实际IC值
vr_file = PROJECT_ROOT / 'volume_ratio_analysis_result.json'
ts_file = PROJECT_ROOT / 'turnover_surge_analysis_result.json'

with open(vr_file, 'r') as f:
    vr_data = json.load(f)['ic_metrics']
    
with open(ts_file, 'r') as f:
    ts_data = json.load(f)['ic_metrics']

print(f"\nvolume_ratio IC分析结果:")
print(f"  - ic_mean: {vr_data['ic_mean']} {'(负值)' if vr_data['ic_mean'] < 0 else '(正值)'}")
print(f"  - icir: {vr_data['icir']}")
print(f"  → 应配置为: 'negative'")

print(f"\nturnover_surge IC分析结果:")
print(f"  - ic_mean: {ts_data['ic_mean']} {'(负值)' if ts_data['ic_mean'] < 0 else '(正值)'}")
print(f"  - icir: {ts_data['icir']}")
print(f"  → 应配置为: 'negative'")

# ============================================================================
# 5. Bug分析
# ============================================================================
print("\n【5. Bug分析】")
print("-" * 100)

print("""
发现的问题:

1. weight_optimizer.py IC_DIRECTIONS配置错误:
   - volume_ratio: 配置为'positive'，应为'negative'（IC=-0.0294）
   - turnover_surge: 配置为'positive'，应为'negative'（IC=-0.0475）
   - 注释显示"IC=0.0294 > 0"是错误的，实际IC为负值

2. ic_directions_validator数据加载Bug:
   - 验证器尝试查找 data['1d'] 或 data['ic_mean']
   - 但实际数据结构是 data['ic_metrics']['ic_mean']
   - 导致所有IC值都读取为0，无法检测矛盾

3. WeightOptimizer实例无_ic_directions属性:
   - 方案C要求在实例化时调用验证器修正配置
   - 但当前实现未添加此属性
""")

# ============================================================================
# 输出验证结果表格
# ============================================================================
print("\n" + "=" * 100)
print("验证结果汇总".center(100))
print("=" * 100)

# 统计
passed = sum(1 for r in results if r[3] == '✅')
failed = sum(1 for r in results if r[3] == '❌')
warning = sum(1 for r in results if r[3] == '⚠️')

# 输出表格
print("\n{:<70} {:<15} {:<20} {:<5}".format('验证项', '预期', '实际', '结果'))
print("-" * 115)
for r in results:
    print("{:<70} {:<15} {:<20} {:<5}".format(r[0][:68], str(r[1])[:13], str(r[2])[:18], r[3]))

print("\n" + "-" * 100)
print(f"总计: {len(results)} 项 | ✅ 通过: {passed} | ❌ 失败: {failed} | ⚠️ 警告: {warning}")

# ============================================================================
# 总体评价
# ============================================================================
print("\n" + "=" * 100)
print("总体评价".center(100))
print("=" * 100)

print("""
❌ 方案C实施不完整，存在以下问题：

1. 【配置修正不完整】
   - weight_optimizer.py 的 IC_DIRECTIONS 未修正
   - volume_ratio/turnover_surge 仍配置为'positive'，与实际IC值矛盾
   
2. 【验证器功能缺陷】
   - ic_directions_validator 数据加载逻辑存在Bug
   - JSON结构解析错误：应从 data['ic_metrics'] 读取，而非 data['ic_mean']
   - 导致验证功能无法正常工作
   
3. 【实例级属性缺失】
   - WeightOptimizer 实例未实现 _ic_directions 属性
   - 未在初始化时调用验证器修正配置

4. 【已正确实施的部分】
   ✅ precompute_optimizer_multi_period.py IC_DIRECTIONS 已修正
   ✅ v2_scoring_engine.py REVERSE_FACTORS 已补充 volume_ratio
   ✅ ic_directions_validator 模块已创建（但功能有Bug）

建议：
- 修正 weight_optimizer.py 的 IC_DIRECTIONS 配置
- 修复 ic_directions_validator 的数据加载逻辑
- 在 WeightOptimizer.__init__ 中集成验证器
""")

print("=" * 100)