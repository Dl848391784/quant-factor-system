#!/usr/bin/env python3
"""测试增量缓存更新逻辑"""

import os
import sys
import json
import gzip
import time
from datetime import datetime, timedelta

# 添加父目录到路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from real_data_loader import RealDataLoader

def test_incremental_cache():
    """测试增量缓存逻辑"""
    
    print("=" * 60)
    print("测试增量缓存更新逻辑")
    print("=" * 60)
    
    cache_dir = os.path.expanduser('~/.openclaw/workspace/yunzhou/factor_ic_analyzer/cache/factor_data')
    factor_cache_path = os.path.join(cache_dir, 'factor_data.json.gz')
    return_cache_path = os.path.join(cache_dir, 'return_data.json.gz')
    
    # 清理旧缓存（如果有）
    for f in [factor_cache_path, return_cache_path]:
        if os.path.exists(f):
            os.remove(f)
            print(f"删除旧缓存: {f}")
    
    # ========== 测试 1: 首次运行（全量拉取） ==========
    print("\n" + "=" * 60)
    print("测试 1: 首次运行（全量拉取）")
    print("=" * 60)
    
    loader = RealDataLoader(enable_cache=True)
    
    start_time = time.time()
    factor_df, return_df = loader.load_data_multithreaded(
        n_days=100,  # 测试用 100 天
        max_stocks=0,  # max_stocks=0 才会触发缓存保存
        enable_complement=False  # 测试时禁用补全
    )
    elapsed_time = time.time() - start_time
    
    print(f"\n首次运行耗时: {elapsed_time:.2f} 秒")
    print(f"因子数据: {len(factor_df)} 条")
    print(f"收益数据: {len(return_df)} 条")
    
    # 检查缓存是否生成
    if os.path.exists(factor_cache_path):
        factor_cache_data = loader._load_cache_gzip(factor_cache_path)
        meta = factor_cache_data.get('meta', {})
        print(f"\n缓存信息:")
        print(f"  日期范围: {meta.get('date_range', {}).get('start')} ~ {meta.get('date_range', {}).get('end')}")
        print(f"  交易日数: {meta.get('n_days')}")
        print(f"  股票数量: {meta.get('n_assets')}")
        print(f"  版本: {meta.get('version')}")
    else:
        print("✗ 缓存未生成")
        return False
    
    # ========== 测试 2: 同一天再次运行（使用缓存） ==========
    print("\n" + "=" * 60)
    print("测试 2: 同一天再次运行（应该直接使用缓存）")
    print("=" * 60)
    
    loader2 = RealDataLoader(enable_cache=True)
    
    start_time = time.time()
    factor_df2, return_df2 = loader2.load_data_multithreaded(
        n_days=100,
        max_stocks=0,  # 注意：max_stocks=0 才会触发缓存检查
        enable_complement=False
    )
    elapsed_time2 = time.time() - start_time
    
    print(f"\n二次运行耗时: {elapsed_time2:.2f} 秒")
    
    # 检查是否使用了缓存（耗时应该很短）
    if elapsed_time2 < 5:
        print("✓ 使用了缓存（耗时 < 5 秒）")
    else:
        print("✗ 可能未使用缓存（耗时 > 5 秒）")
    
    # 验收标准
    print("\n" + "=" * 60)
    print("验收结果")
    print("=" * 60)
    
    # 标准 1: 首次运行生成了缓存
    if os.path.exists(factor_cache_path) and os.path.exists(return_cache_path):
        print("✓ 标准 1: 首次运行生成了缓存文件")
    else:
        print("✗ 标准 1: 缓存文件未生成")
        return False
    
    # 标准 2: 二次运行直接使用缓存
    if elapsed_time2 < 5:
        print("✓ 标准 2: 二次运行直接使用缓存（耗时 < 5 秒）")
    else:
        print("✗ 标准 2: 二次运行可能未使用缓存")
        return False
    
    # 标准 3: 数据一致性
    if len(factor_df2) == len(factor_df):
        print("✓ 标准 3: 数据记录数一致")
    else:
        print(f"✗ 标准 3: 数据记录数不一致 ({len(factor_df2)} vs {len(factor_df)})")
    
    print("\n测试完成！")
    return True


if __name__ == '__main__':
    test_incremental_cache()