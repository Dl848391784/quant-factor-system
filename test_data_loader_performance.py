#!/usr/bin/env python3
"""
数据加载器性能测试

测试向量化因子计算的性能提升
"""

import time
import pandas as pd
import numpy as np

def test_factor_calculation_performance():
    """测试因子计算性能"""
    print("="*60)
    print("因子计算性能测试")
    print("="*60)
    
    from real_data_loader import RealDataLoader
    
    loader = RealDataLoader(use_mock=False, use_local=False, enable_cache=True)
    
    # 测试不同规模的数据
    test_cases = [
        (100, 30, "小规模 (100股×30天)"),
        (500, 73, "中规模 (500股×73天)"),
        (1000, 73, "大规模 (1000股×73天)"),
    ]
    
    for n_stocks, n_days, desc in test_cases:
        print(f"\n{'='*60}")
        print(f"测试: {desc}")
        print(f"{'='*60}")
        
        start_time = time.time()
        
        try:
            factor_df, return_df = loader.load_data(
                n_days=n_days,
                max_stocks=n_stocks,
                enable_complement=False  # 禁用补全以加快测试
            )
            
            elapsed = time.time() - start_time
            
            print(f"\n结果:")
            print(f"  因子数据: {len(factor_df)} 条")
            print(f"  收益数据: {len(return_df)} 条")
            print(f"  股票数量: {factor_df['asset'].nunique()}")
            print(f"  交易日数: {factor_df['date'].nunique()}")
            print(f"  总耗时: {elapsed:.2f} 秒")
            
        except Exception as e:
            print(f"  错误: {e}")
            import traceback
            traceback.print_exc()
    
    print("\n" + "="*60)
    print("测试完成")
    print("="*60)


if __name__ == '__main__':
    test_factor_calculation_performance()