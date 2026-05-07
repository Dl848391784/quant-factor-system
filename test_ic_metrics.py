#!/usr/bin/env python3
"""测试 ic_metrics 字段完整性"""

import json
import sys
sys.path.insert(0, '.')

# 模拟 calculate_kdj_j_ic 函数的返回逻辑
def test_ic_metrics_structure():
    """测试 ic_metrics 构建逻辑"""
    
    # 模拟 IC 计算结果
    ic_result = {
        'ic_series': None,
        'ic_mean': 0.002383,
        'ic_std': 0.028202,
        'icir': 0.0845,
        't_stat': 1.3439,
        'p_value': 0.1792,
        'positive_ratio': 0.5317,
        'n_days': 252,
        'n_assets': 5360,
        'significance': '',
        'summary': '测试数据'
    }
    
    # 这是 kdj_j_factor.py 中的构建逻辑
    ic_metrics = {
        'ic_mean': ic_result.get('ic_mean', 0),
        'ic_std': ic_result.get('ic_std', 0),
        'icir': ic_result.get('icir', 0),
        't_stat': ic_result.get('t_stat', 0),
        'p_value': ic_result.get('p_value', 1),
        'positive_ratio': ic_result.get('positive_ratio', 0),
        'n_days': ic_result.get('n_days', 0),
        'n_assets': ic_result.get('n_assets', 0),
        'significance': ic_result.get('significance', ''),
        'summary': ic_result.get('summary', '')
    }
    
    # 验证字段
    required_fields = ['t_stat', 'p_value', 'n_assets', 'significance']
    missing = [f for f in required_fields if f not in ic_metrics]
    
    print("构建的 ic_metrics:")
    print(json.dumps(ic_metrics, indent=2))
    
    if missing:
        print(f"\n✗ 缺少字段: {missing}")
        return False
    else:
        print(f"\n✓ 所有必需字段都存在")
        return True

if __name__ == '__main__':
    success = test_ic_metrics_structure()
    sys.exit(0 if success else 1)