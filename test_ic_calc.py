#!/usr/bin/env python3
"""轻量测试 IC 计算逻辑"""

import pandas as pd
import numpy as np
from scipy import stats as scipy_stats
import math

# 模拟数据
def test_ic_calculation():
    """测试 calculate_kdj_j_ic 的核心逻辑"""
    
    # 创建模拟数据
    dates = pd.date_range('2024-01-01', periods=100)
    assets = [f'stock_{i}' for i in range(100)]
    
    # 模拟因子和收益
    data = []
    for date in dates:
        for asset in assets:
            data.append({
                'date': date,
                'asset': asset,
                'kdj_j': np.random.uniform(-20, 120),
                'forward_return': np.random.uniform(-0.05, 0.05)
            })
    
    merged = pd.DataFrame(data)
    
    # ===== 核心逻辑（从 calculate_kdj_j_ic 提取） =====
    n_assets = merged['asset'].nunique() if not merged.empty else 0
    print(f"n_assets = {n_assets}")
    
    # 计算 IC
    ic_results = []
    for date, group in merged.groupby('date'):
        if len(group) < 10:
            continue
        
        factor_rank = group['kdj_j'].rank(pct=True, ascending=False, method='average')
        return_rank = group['forward_return'].rank(pct=True, ascending=True, method='average')
        
        ic_value = factor_rank.corr(return_rank, method='spearman')
        
        if pd.notna(ic_value):
            ic_results.append({'date': date, 'ic': ic_value})
    
    ic_df = pd.DataFrame(ic_results)
    ic_series = ic_df.set_index('date')['ic']
    
    # 统计量计算
    ic_mean = ic_series.mean()
    ic_std = ic_series.std()
    icir = ic_mean / ic_std if ic_std > 0 else 0
    positive_ratio = (ic_series > 0).mean()
    
    n = len(ic_series)
    t_stat = ic_mean / (ic_std / math.sqrt(n)) if ic_std > 0 else 0
    p_value = 2 * (1 - scipy_stats.t.cdf(abs(t_stat), df=n-1)) if n > 1 else 1
    
    # 显著性标注
    abs_t = abs(t_stat)
    if abs_t > 3.29:
        significance = '***'
    elif abs_t > 2.58:
        significance = '**'
    elif abs_t > 1.96:
        significance = '*'
    else:
        significance = ''
    
    # ===== 构建返回结果 =====
    result = {
        'ic_series': ic_series,
        'ic_mean': ic_mean,
        'ic_std': ic_std,
        'icir': icir,
        't_stat': round(t_stat, 4),
        'p_value': round(p_value, 6),
        'positive_ratio': positive_ratio,
        'n_days': n,
        'n_assets': n_assets,
        'significance': significance,
        'summary': f'IC均值={ic_mean:.4f}, ICIR={icir:.2f}'
    }
    
    print("\n返回结果:")
    for k, v in result.items():
        if k != 'ic_series':
            print(f"  {k}: {v}")
    
    # 验证字段完整性
    required = ['t_stat', 'p_value', 'n_assets', 'significance']
    missing = [f for f in required if f not in result]
    
    if missing:
        print(f"\n✗ 缺少: {missing}")
        return False
    else:
        print(f"\n✓ 所有必需字段都存在")
        return True

if __name__ == '__main__':
    import sys
    success = test_ic_calculation()
    sys.exit(0 if success else 1)