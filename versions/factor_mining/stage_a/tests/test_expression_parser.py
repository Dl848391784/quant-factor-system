"""
测试表达式解析器的新功能
"""
import numpy as np
import pandas as pd
import sys
import os

# 设置正确的导入路径
sys.path.insert(0, '/home/admin/.openclaw/workspace/yunzhou/factor_ic_analyzer/versions/factor_mining')

from stage_a.factor_combiner import FactorCombiner
from stage_a.safe_math import SafeMath

def setup_data():
    """设置测试数据"""
    np.random.seed(42)
    n = 100
    return {
        'rsi': pd.Series(np.random.uniform(20, 80, n)),
        'kdj_j': pd.Series(np.random.uniform(-20, 120, n)),
        'volume_ratio': pd.Series(np.random.uniform(0.5, 3.0, n)),
    }

def test_max_expression():
    """测试 max 表达式"""
    print("测试 max 表达式...")
    data = setup_data()
    combiner = FactorCombiner()
    
    result = combiner.compute_expression('rsi max kdj_j', data)
    expected = np.maximum(data['rsi'], data['kdj_j'])
    pd.testing.assert_series_equal(result, expected, check_names=False)
    print("  ✓ max 表达式解析正确")

def test_min_expression():
    """测试 min 表达式"""
    print("测试 min 表达式...")
    data = setup_data()
    combiner = FactorCombiner()
    
    result = combiner.compute_expression('rsi min kdj_j', data)
    expected = np.minimum(data['rsi'], data['kdj_j'])
    pd.testing.assert_series_equal(result, expected, check_names=False)
    print("  ✓ min 表达式解析正确")

def test_ratio_expression():
    """测试 ratio(f1, f2) 表达式"""
    print("测试 ratio(f1, f2) 表达式...")
    data = setup_data()
    combiner = FactorCombiner()
    
    result = combiner.compute_expression('ratio(rsi, volume_ratio)', data)
    # ratio(a, b) = a / b (安全除法)
    expected = SafeMath.safe_divide(data['rsi'], data['volume_ratio'])
    pd.testing.assert_series_equal(result, expected, check_names=False)
    print("  ✓ ratio 表达式解析正确")

def test_nested_binary_expression():
    """测试嵌套二元表达式 rank(rsi) + rank(kdj_j)"""
    print("测试嵌套二元表达式 rank(rsi) + rank(kdj_j)...")
    data = setup_data()
    combiner = FactorCombiner()
    
    result = combiner.compute_expression('rank(rsi) + rank(kdj_j)', data)
    expected = SafeMath.safe_rank(data['rsi']) + SafeMath.safe_rank(data['kdj_j'])
    pd.testing.assert_series_equal(result, expected, check_names=False)
    print("  ✓ 嵌套二元表达式解析正确")

def test_parenthesized_binary():
    """测试括号包裹的二元表达式 (rsi + kdj_j)"""
    print("测试括号包裹的二元表达式...")
    data = setup_data()
    combiner = FactorCombiner()
    
    result = combiner.compute_expression('(rsi + kdj_j)', data)
    expected = data['rsi'] + data['kdj_j']
    pd.testing.assert_series_equal(result, expected, check_names=False)
    print("  ✓ 括号表达式解析正确")

def test_nested_unary():
    """测试嵌套一元表达式 log(rsi * kdj_j)"""
    print("测试嵌套一元表达式 log(rsi * kdj_j)...")
    data = setup_data()
    combiner = FactorCombiner()
    
    result = combiner.compute_expression('log(rsi * kdj_j)', data)
    expected = SafeMath.safe_log(data['rsi'] * data['kdj_j'])
    pd.testing.assert_series_equal(result, expected, check_names=False)
    print("  ✓ 嵌套一元表达式解析正确")

def test_complex_expression():
    """测试复杂表达式"""
    print("测试复杂表达式...")
    data = setup_data()
    combiner = FactorCombiner()
    
    # 测试 rank(rsi) - rank(volume_ratio)
    result = combiner.compute_expression('rank(rsi) - rank(volume_ratio)', data)
    expected = SafeMath.safe_rank(data['rsi']) - SafeMath.safe_rank(data['volume_ratio'])
    pd.testing.assert_series_equal(result, expected, check_names=False)
    print("  ✓ 复杂表达式解析正确")

def test_all_operators():
    """测试所有操作符"""
    print("\n测试所有二元操作符...")
    data = setup_data()
    combiner = FactorCombiner()
    
    operators = {
        '+': lambda a, b: a + b,
        '-': lambda a, b: a - b,
        '*': lambda a, b: a * b,
        '/': lambda a, b: a / b,
        'max': lambda a, b: np.maximum(a, b),
        'min': lambda a, b: np.minimum(a, b),
    }
    
    for op, op_func in operators.items():
        expr = f'rsi {op} kdj_j'
        result = combiner.compute_expression(expr, data)
        expected = op_func(data['rsi'], data['kdj_j'])
        pd.testing.assert_series_equal(result, expected, check_names=False)
        print(f"  ✓ '{op}' 操作符正确")

if __name__ == '__main__':
    print("=" * 60)
    print("测试表达式解析器新功能")
    print("=" * 60)
    
    try:
        test_all_operators()
        test_ratio_expression()
        test_nested_binary_expression()
        test_parenthesized_binary()
        test_nested_unary()
        test_complex_expression()
        
        print("\n" + "=" * 60)
        print("所有测试通过! ✓")
        print("=" * 60)
    except Exception as e:
        print(f"\n测试失败: {e}")
        import traceback
        traceback.print_exc()
        exit(1)