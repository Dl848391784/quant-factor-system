#!/usr/bin/env python3
"""
重新生成因子缓存数据（带异常股票剔除）- 使用真实数据
后台运行脚本
"""

import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

from real_data_loader import RealDataLoader
from datetime import datetime
import json

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
    
    # 初始化加载器（使用真实API）
    loader = RealDataLoader(enable_cache=True, use_mock=False)
    
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
    
    if ic_df is not None and len(ic_df) > 0:
        print(f"IC均值: {ic_df['ic'].mean():.4f}")
        print(f"ICIR: {ic_df['ic'].mean() / ic_df['ic'].std():.4f}")
    
    # 保存统计结果到文件
    stats = {
        'generated_at': datetime.now().isoformat(),
        'factor_records': len(factor_df),
        'return_records': len(return_df),
        'n_days': len(factor_df['date'].unique()),
        'n_stocks': len(factor_df['asset'].unique()),
        'date_range': {
            'start': sorted(factor_df['date'].unique())[0],
            'end': sorted(factor_df['date'].unique())[-1]
        }
    }
    
    if ic_df is not None and len(ic_df) > 0:
        stats['ic_mean'] = ic_df['ic'].mean()
        stats['ic_std'] = ic_df['ic'].std()
        stats['icir'] = ic_df['ic'].mean() / ic_df['ic'].std()
        stats['ic_positive_ratio'] = (ic_df['ic'] > 0).mean()
    
    stats_path = os.path.join(cache_dir, 'regenerate_stats.json')
    with open(stats_path, 'w', encoding='utf-8') as f:
        json.dump(stats, f, ensure_ascii=False, indent=2)
    print(f"统计结果已保存: {stats_path}")
    
    return factor_df, return_df, ic_df

if __name__ == '__main__':
    regenerate_cache()