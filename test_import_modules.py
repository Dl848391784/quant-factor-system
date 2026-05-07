#!/usr/bin/env python3
"""
实际代码文件导入测试
验证修复后的实际代码文件能否正常导入和运行
"""

import sys
import os

print("=" * 60)
print("实际代码文件导入测试")
print("=" * 60)
print()

# 切换到工作目录
os.chdir('/home/admin/.openclaw/workspace/yunzhou/factor_ic_analyzer')

# 测试结果
test_results = {
    "passed": 0,
    "failed": 0,
    "errors": []
}

# 测试1: 导入 regenerate_cache_batch
print("测试 1: 导入 regenerate_cache_batch.py")
print("-" * 60)
try:
    # 只导入，不执行主函数
    import regenerate_cache_batch
    print("✓ 成功导入 regenerate_cache_batch")
    print(f"  模块路径: {regenerate_cache_batch.__file__}")
    
    # 检查关键函数是否存在
    if hasattr(regenerate_cache_batch, 'regenerate_cache_for_stock'):
        print("  ✓ 函数 regenerate_cache_for_stock 存在")
    if hasattr(regenerate_cache_batch, 'main'):
        print("  ✓ 函数 main 存在")
    
    test_results["passed"] += 1
    print("✅ 测试1通过\n")
except Exception as e:
    print(f"❌ 测试1失败: {e}")
    test_results["failed"] += 1
    test_results["errors"].append(f"导入 regenerate_cache_batch 失败: {e}\n")
    import traceback
    traceback.print_exc()

# 测试2: 导入 real_data_loader
print("测试 2: 导入 real_data_loader.py")
print("-" * 60)
try:
    import real_data_loader
    print("✓ 成功导入 real_data_loader")
    print(f"  模块路径: {real_data_loader.__file__}")
    
    # 检查关键类/函数
    if hasattr(real_data_loader, 'RealDataLoader'):
        print("  ✓ 类 RealDataLoader 存在")
    
    test_results["passed"] += 1
    print("✅ 测试2通过\n")
except Exception as e:
    print(f"❌ 测试2失败: {e}")
    test_results["failed"] += 1
    test_results["errors"].append(f"导入 real_data_loader 失败: {e}\n")
    import traceback
    traceback.print_exc()

# 测试3: 导入 scoring_backtest_vectorized
print("测试 3: 导入 scoring_backtest_vectorized.py")
print("-" * 60)
try:
    import scoring_backtest_vectorized
    print("✓ 成功导入 scoring_backtest_vectorized")
    print(f"  模块路径: {scoring_backtest_vectorized.__file__}")
    
    # 检查关键类
    if hasattr(scoring_backtest_vectorized, 'ScoringBacktestVectorized'):
        print("  ✓ 类 ScoringBacktestVectorized 存在")
    
    test_results["passed"] += 1
    print("✅ 测试3通过\n")
except Exception as e:
    print(f"❌ 测试3失败: {e}")
    test_results["failed"] += 1
    test_results["errors"].append(f"导入 scoring_backtest_vectorized 失败: {e}\n")
    import traceback
    traceback.print_exc()

# 测试4: 导入 scoring_engine
print("测试 4: 导入 common/scoring_engine.py")
print("-" * 60)
try:
    # 将 common 目录添加到路径
    sys.path.insert(0, '/home/admin/.openclaw/workspace/yunzhou/factor_ic_analyzer/common')
    import scoring_engine
    print("✓ 成功导入 scoring_engine")
    print(f"  模块路径: {scoring_engine.__file__}")
    
    # 检查关键类
    if hasattr(scoring_engine, 'ScoringEngine'):
        print("  ✓ 类 ScoringEngine 存在")
    
    test_results["passed"] += 1
    print("✅ 测试4通过\n")
except Exception as e:
    print(f"❌ 测试4失败: {e}")
    test_results["failed"] += 1
    test_results["errors"].append(f"导入 scoring_engine 失败: {e}\n")
    import traceback
    traceback.print_exc()

# 测试总结
print("=" * 60)
print("导入测试总结")
print("=" * 60)
print(f"✅ 通过: {test_results['passed']}")
print(f"❌ 失败: {test_results['failed']}")
print()

if test_results['errors']:
    print("错误详情:")
    for error in test_results['errors']:
        print(f"  - {error}")
    print()

if test_results['failed'] == 0:
    print("🎉 所有模块成功导入！代码无语法错误和导入错误！")
    sys.exit(0)
else:
    print("⚠️ 部分模块导入失败，请检查代码")
    sys.exit(1)