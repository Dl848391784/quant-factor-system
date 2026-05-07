#!/usr/bin/env python3
"""
全量缓存更新脚本 - 包含 RSI(6) 和量比(5) 因子

运行方式：
    python regenerate_cache_volume_ratio.py

预计耗时：20-30 分钟（获取约 3000+ 只主板股票数据）
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from real_data_loader import RealDataLoader
import time

def regenerate_cache():
    """全量更新缓存"""
    print("\n" + "="*60)
    print("【全量缓存更新 - RSI(6) + 量比(5)】")
    print("="*60)
    print(f"  开始时间: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  目标：获取约 3000+ 只主板股票数据")
    print(f"  因子：RSI(6), 量比(5)")
    print(f"  预计耗时：20-30 分钟")
    print("="*60)
    
    # 清除旧缓存
    print("\n[清除旧缓存]...")
    cache_files = [
        'cache/factor_data/factor_data.json.gz',
        'cache/factor_data/return_data.json.gz',
        'cache/factor_data/stock_status.json.gz'
    ]
    
    for f in cache_files:
        if os.path.exists(f):
            os.remove(f)
            print(f"  ✓ 已删除: {f}")
        else:
            print(f"  - 不存在: {f}")
    
    # 全量拉取
    print("\n[全量拉取数据]...")
    loader = RealDataLoader(enable_cache=True)
    
    factor_df, return_df = loader.load_data(
        n_days=500,
        max_stocks=0,  # 获取全部主板股票
        enable_complement=False  # 跳过补全机制，减少内存使用
    )
    
    # 验证结果
    print("\n[验证结果]...")
    print(f"  因子列: {factor_df.columns.tolist()}")
    
    if 'volume_ratio_5' not in factor_df.columns:
        print("  ✗ 错误：缺少 volume_ratio_5 字段！")
        return False
    
    print(f"  ✓ 包含 volume_ratio_5 字段")
    
    vr_min = factor_df['volume_ratio_5'].min()
    vr_max = factor_df['volume_ratio_5'].max()
    vr_mean = factor_df['volume_ratio_5'].mean()
    
    print(f"  量比范围: [{vr_min:.2f}, {vr_max:.2f}]")
    print(f"  量比均值: {vr_mean:.2f}")
    
    # IC 分析
    print("\n[量比 RankIC 分析]...")
    ic_df = loader.calculate_rank_ic(
        factor_df,
        return_df,
        factor_col='volume_ratio_5',
        enable_filter=True,
        enable_winsorize=True
    )
    
    if ic_df is not None and len(ic_df) > 0:
        mean_ic = ic_df['ic'].mean()
        icir = mean_ic / ic_df['ic'].std() if ic_df['ic'].std() > 0 else 0
        print(f"  平均 IC: {mean_ic:.4f}")
        print(f"  ICIR: {icir:.4f}")
    
    print("\n" + "="*60)
    print("【全量缓存更新完成】")
    print("="*60)
    print(f"  结束时间: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  缓存文件: cache/factor_data/factor_data.json.gz")
    print("="*60)
    
    return True

if __name__ == '__main__':
    regenerate_cache()