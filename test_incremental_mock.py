#!/usr/bin/env python3
"""快速测试增量缓存逻辑（使用模拟数据）"""

import os
import sys
import json
import gzip
import time
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from real_data_loader import RealDataLoader

def test_with_mock_data():
    """使用模拟数据快速测试缓存逻辑"""
    
    print("=" * 60)
    print("快速测试增量缓存逻辑（模拟数据）")
    print("=" * 60)
    
    cache_dir = os.path.expanduser('~/.openclaw/workspace/yunzhou/factor_ic_analyzer/cache/factor_data')
    factor_cache_path = os.path.join(cache_dir, 'factor_data.json.gz')
    return_cache_path = os.path.join(cache_dir, 'return_data.json.gz')
    
    # 清理旧缓存
    for f in [factor_cache_path, return_cache_path]:
        if os.path.exists(f):
            os.remove(f)
            print(f"删除旧缓存: {f}")
    
    # ========== 测试 1: 首次运行 ==========
    print("\n[测试 1] 首次运行（全量）")
    
    loader = RealDataLoader(enable_cache=True, use_mock=True)
    
    start = time.time()
    factor_df, return_df = loader.load_data_multithreaded(
        n_days=100,
        max_stocks=0,  # 触发缓存
        enable_complement=False
    )
    elapsed1 = time.time() - start
    
    print(f"耗时: {elapsed1:.2f} 秒")
    print(f"因子: {len(factor_df)} 条")
    print(f"收益: {len(return_df)} 条")
    
    # 检查缓存
    assert os.path.exists(factor_cache_path), "缓存未生成"
    
    with gzip.open(factor_cache_path, 'rt') as f:
        cache_data = json.load(f)
    
    meta = cache_data['meta']
    print(f"\n缓存元数据:")
    print(f"  版本: {meta.get('version')}")
    print(f"  日期范围: {meta['date_range']['start']} ~ {meta['date_range']['end']}")
    print(f"  交易日数: {meta['n_days']}")
    print(f"  股票数量: {meta['n_assets']}")
    print(f"  最后更新: {meta.get('last_updated')}")
    
    # ========== 测试 2: 同一天再次运行 ==========
    print("\n[测试 2] 同一天再次运行")
    
    loader2 = RealDataLoader(enable_cache=True, use_mock=True)
    
    start = time.time()
    factor_df2, return_df2 = loader2.load_data_multithreaded(
        n_days=100,
        max_stocks=0,
        enable_complement=False
    )
    elapsed2 = time.time() - start
    
    print(f"耗时: {elapsed2:.2f} 秒")
    
    assert elapsed2 < 5, f"应该使用缓存，耗时应 < 5 秒，实际 {elapsed2:.2f} 秒"
    assert len(factor_df2) == len(factor_df), f"数据应一致，{len(factor_df2)} vs {len(factor_df)}"
    
    print("✓ 正确使用缓存")
    
    # ========== 测试 3: 模拟第二天运行（修改缓存日期） ==========
    print("\n[测试 3] 模拟第二天运行")
    
    # 修改缓存日期，模拟昨天的缓存
    yesterday = datetime.now() - timedelta(days=1)
    yesterday_str = yesterday.strftime('%Y-%m-%d')
    
    # 修改缓存元数据，让日期范围停在昨天
    cache_data['meta']['date_range']['end'] = yesterday_str
    cache_data['meta']['last_updated'] = yesterday.strftime('%Y-%m-%d %H:%M:%S')
    
    # 只保留昨天的数据（模拟）
    cache_data['data'] = [d for d in cache_data['data'] if d['date'] <= yesterday_str]
    cache_data['meta']['n_days'] = len(set(d['date'] for d in cache_data['data']))
    
    # 重新保存
    with gzip.open(factor_cache_path, 'wt') as f:
        json.dump(cache_data, f)
    
    print(f"模拟缓存日期: {yesterday_str}")
    print(f"缓存记录数: {len(cache_data['data'])}")
    
    # 同样修改收益缓存
    with gzip.open(return_cache_path, 'rt') as f:
        return_cache = json.load(f)
    
    return_cache['meta']['date_range']['end'] = yesterday_str
    return_cache['meta']['last_updated'] = yesterday.strftime('%Y-%m-%d %H:%M:%S')
    return_cache['data'] = [d for d in return_cache['data'] if d['date'] <= yesterday_str]
    return_cache['meta']['n_days'] = len(set(d['date'] for d in return_cache['data']))
    
    with gzip.open(return_cache_path, 'wt') as f:
        json.dump(return_cache, f)
    
    # 再次运行
    loader3 = RealDataLoader(enable_cache=True, use_mock=True)
    
    start = time.time()
    factor_df3, return_df3 = loader3.load_data_multithreaded(
        n_days=100,
        max_stocks=0,
        enable_complement=False
    )
    elapsed3 = time.time() - start
    
    print(f"耗时: {elapsed3:.2f} 秒")
    print(f"因子记录数: {len(factor_df3)}")
    
    # 检查合并后的缓存
    with gzip.open(factor_cache_path, 'rt') as f:
        merged_cache = json.load(f)
    
    merged_meta = merged_cache['meta']
    print(f"\n合并后缓存:")
    print(f"  日期范围: {merged_meta['date_range']['start']} ~ {merged_meta['date_range']['end']}")
    print(f"  交易日数: {merged_meta['n_days']}")
    print(f"  最后更新: {merged_meta['last_updated']}")
    
    # 验收
    today = datetime.now().strftime('%Y-%m-%d')
    assert merged_meta['date_range']['end'] == today, f"日期范围应更新到今天"
    
    print("\n" + "=" * 60)
    print("✓ 所有测试通过！")
    print("=" * 60)
    print("\n验收标准:")
    print("  ✓ 首次运行：生成缓存")
    print(f"  ✓ 二次运行（同一天）：直接用缓存，耗时 {elapsed2:.2f}s < 5s")
    print(f"  ✓ 第二天运行：增量拉取，合并后日期更新到今天")


if __name__ == '__main__':
    test_with_mock_data()