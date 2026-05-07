#!/usr/bin/env python3
"""
重新生成因子缓存数据（带异常股票剔除）
"""

import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

from real_data_loader import RealDataLoader
from datetime import datetime

def regenerate_cache():
    """重新生成缓存"""
    print(f"\n{'='*60}")
    print(f"重新生成因子缓存数据（带异常股票剔除）")
    print(f"开始时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*60}")
    
    # 删除旧缓存
    cache_dir = 'cache/factor_data'
    factor_cache = os.path.join(cache_dir, 'factor_data.json.gz')
    return_cache = os.path.join(cache_dir, 'return_data.json.gz')
    
    if os.path.exists(factor_cache):
        os.remove(factor_cache)
        print(f"已删除旧因子缓存: {factor_cache}")
    
    if os.path.exists(return_cache):
        os.remove(return_cache)
        print(f"已删除旧收益缓存: {return_cache}")
    
    # 初始化加载器
    loader = RealDataLoader(enable_cache=True)
    
    # 加载数据（全量）
    print(f"\n开始加载数据...")
    factor_df, return_df = loader.load_data_multithreaded(
        n_days=250,  # 250个交易日
        max_stocks=0,  # 全部主板股票
        enable_complement=True
    )
    
    # 计算IC
    print(f"\n计算 Rank IC...")
    ic_df = loader.calculate_rank_ic(factor_df, return_df)
    
    # 输出统计
    print(f"\n{'='*60}")
    print(f"缓存生成完成")
    print(f"结束时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*60}")
    
    if ic_df is not None:
        print(f"IC均值: {ic_df['ic'].mean():.4f}")
        print(f"ICIR: {ic_df['ic'].mean() / ic_df['ic'].std():.4f}")
    
    return factor_df, return_df, ic_df

if __name__ == '__main__':
    regenerate_cache()