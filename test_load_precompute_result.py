#!/usr/bin/env python3
"""
测试脚本：验证 load_precompute_result() 函数修复
作者: 云舟
日期: 2026-04-28

测试内容：
1. 验证函数能够正确读取v2路径
2. 验证period参数支持T1/T3/T5
3. 验证返回的数据结构正确
"""

import sys
import json
from pathlib import Path

# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent))

from portfolio_tracker import load_precompute_result

def test_load_precompute_result():
    """测试 load_precompute_result 函数"""
    
    print("=" * 60)
    print("测试 load_precompute_result() 函数")
    print("=" * 60)
    
    # 测试1: 验证T1数据
    print("\n【测试1】读取 T1 数据")
    opt_t1, stocks_t1 = load_precompute_result('T1')
    assert opt_t1 is not None, "T1数据读取失败"
    assert stocks_t1 is not None and len(stocks_t1) > 0, "T1股票列表为空"
    assert opt_t1.get('period') == 'T+1', f"T1 period错误: {opt_t1.get('period')}"
    assert 'weights_used' in opt_t1, "T1缺少weights_used字段"
    assert 'computed_at' in opt_t1, "T1缺少computed_at字段"
    print(f"✓ T1数据读取成功: {len(stocks_t1)}只股票")
    print(f"  - period: {opt_t1.get('period')}")
    print(f"  - computed_at: {opt_t1.get('computed_at')}")
    print(f"  - weights: {opt_t1.get('weights_used')}")
    
    # 测试2: 验证T3数据
    print("\n【测试2】读取 T3 数据")
    opt_t3, stocks_t3 = load_precompute_result('T3')
    assert opt_t3 is not None, "T3数据读取失败"
    assert stocks_t3 is not None and len(stocks_t3) > 0, "T3股票列表为空"
    assert opt_t3.get('period') == 'T+3', f"T3 period错误: {opt_t3.get('period')}"
    print(f"✓ T3数据读取成功: {len(stocks_t3)}只股票")
    print(f"  - period: {opt_t3.get('period')}")
    print(f"  - computed_at: {opt_t3.get('computed_at')}")
    
    # 测试3: 验证T5数据
    print("\n【测试3】读取 T5 数据")
    opt_t5, stocks_t5 = load_precompute_result('T5')
    assert opt_t5 is not None, "T5数据读取失败"
    assert stocks_t5 is not None and len(stocks_t5) > 0, "T5股票列表为空"
    assert opt_t5.get('period') == 'T+5', f"T5 period错误: {opt_t5.get('period')}"
    print(f"✓ T5数据读取成功: {len(stocks_t5)}只股票")
    print(f"  - period: {opt_t5.get('period')}")
    print(f"  - computed_at: {opt_t5.get('computed_at')}")
    
    # 测试4: 验证默认参数（应该是T1）
    print("\n【测试4】验证默认参数（应该是T1）")
    opt_default, stocks_default = load_precompute_result()
    assert opt_default is not None, "默认参数数据读取失败"
    assert opt_default.get('period') == 'T+1', f"默认period错误: {opt_default.get('period')}"
    print(f"✓ 默认参数正确，返回T1数据")
    
    # 测试5: 验证非法参数处理
    print("\n【测试5】验证非法参数处理")
    opt_invalid, stocks_invalid = load_precompute_result('T7')
    assert opt_invalid is not None, "非法参数应该降级到T1"
    assert opt_invalid.get('period') == 'T+1', "非法参数应该返回T1数据"
    print(f"✓ 非法参数正确降级到T1")
    
    # 测试6: 验证返回的数据结构
    print("\n【测试6】验证返回的数据结构")
    opt, stocks = load_precompute_result('T1')
    assert 'best_combination' in opt, "缺少best_combination字段"
    assert 'weights' in opt['best_combination'], "缺少weights字段"
    assert 'stocks' in stocks[0] or 'code' in stocks[0], "股票数据结构不正确"
    print(f"✓ 数据结构正确")
    print(f"  - best_combination: {opt['best_combination']}")
    print(f"  - 股票样例: {stocks[0] if stocks else '无'}")
    
    print("\n" + "=" * 60)
    print("所有测试通过！✓")
    print("=" * 60)
    
    return True

if __name__ == '__main__':
    try:
        test_load_precompute_result()
        sys.exit(0)
    except AssertionError as e:
        print(f"\n✗ 测试失败: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"\n✗ 测试异常: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)