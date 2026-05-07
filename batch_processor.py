#!/usr/bin/env python3
"""
分批数据处理脚本 - 解决内存不足问题

运行方式：
    python batch_processor.py --start 0 --end 500    # 处理第0-500只股票
    python batch_processor.py --start 500 --end 1000  # 处理第500-1000只股票
    ...
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import argparse
import pandas as pd
import json
import gzip
import time
from datetime import datetime, timedelta
from real_data_loader import RealDataLoader

def process_batch(start_idx, end_idx, n_days=500):
    """处理指定范围的股票"""
    
    print(f'\n=== 处理股票 {start_idx}-{end_idx} ===')
    print(f'开始时间: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}')
    
    # 加载股票列表（从缓存）
    stock_list_cache_path = 'cache/stock_list.json'
    if not os.path.exists(stock_list_cache_path):
        print('✗ 股票列表缓存不存在，先获取股票列表')
        loader = RealDataLoader(enable_cache=True)
        loader.get_main_board_stocks(max_stocks=0)
    
    with open(stock_list_cache_path, 'r') as f:
        stock_data = json.load(f)
    
    all_stocks = stock_data.get('stocks', [])
    
    # 获取指定范围的股票
    batch_stocks = all_stocks[start_idx:end_idx]
    print(f'股票数量: {len(batch_stocks)}')
    
    if len(batch_stocks) == 0:
        print('✗ 没有股票需要处理')
        return None
    
    # 创建loader
    loader = RealDataLoader(enable_cache=False)
    
    # 获取日期范围
    fetch_days = int(n_days * 1.5) + 30
    start_date = (datetime.now() - timedelta(days=fetch_days)).strftime('%Y-%m-%d')
    
    # 分批获取数据（每批100只）
    batch_size = 100
    total_stocks = len(batch_stocks)
    num_batches = (total_stocks + batch_size - 1) // batch_size
    
    all_data_dict = {}
    success_count = 0
    fail_count = 0
    
    start_time = time.time()
    
    for batch_idx in range(num_batches):
        b_start = batch_idx * batch_size
        b_end = min(b_start + batch_size, total_stocks)
        current_batch = batch_stocks[b_start:b_end]
        
        b_start_time = time.time()
        print(f'\n  [批次 {batch_idx + 1}/{num_batches}] 股票 {b_start + 1}-{b_end}')
        
        # 2线程并行获取
        thread_a = current_batch[:len(current_batch)//2]
        thread_b = current_batch[len(current_batch)//2:]
        
        results_a = loader._fetch_stock_batch(thread_a, fetch_days)
        results_b = loader._fetch_stock_batch(thread_b, fetch_days)
        
        for code, df in results_a + results_b:
            if df is not None and len(df) > 0:
                all_data_dict[code] = df
                success_count += 1
            else:
                fail_count += 1
        
        elapsed = time.time() - b_start_time
        print(f'    进度: {success_count}/{total_stocks} [耗时: {elapsed:.1f}s]')
        
        if batch_idx < num_batches - 1:
            time.sleep(2.0)
    
    print(f'\n  ✓ 数据获取完成，成功: {success_count}, 失败: {fail_count}')
    
    if len(all_data_dict) == 0:
        print('✗ 没有获取到任何数据')
        return None
    
    # 合并数据
    print('\n[数据处理] 合并数据...')
    all_data = list(all_data_dict.values())
    combined = pd.concat(all_data, ignore_index=True)
    
    # 日期筛选
    combined['date'] = pd.to_datetime(combined['date'])
    start_dt = pd.to_datetime(start_date)
    end_dt = pd.to_datetime('2026-04-03')
    combined = combined[(combined['date'] >= start_dt) & (combined['date'] <= end_dt)]
    combined = combined.sort_values(['asset', 'date'])
    print(f'  记录数: {len(combined)}')
    
    # 计算因子
    print('\n[因子计算]...')
    
    combined['prev_close'] = combined.groupby('asset')['close'].shift(1)
    
    # RSI
    combined['rsi_6'] = combined.groupby('asset')['close'].transform(
        lambda x: loader._calculate_rsi_vectorized(x, period=6)
    )
    
    # 量比
    combined['volume_ratio_5'] = combined.groupby('asset')['volume'].transform(
        lambda x: x / x.rolling(window=5).mean()
    )
    combined['volume_ratio_5'] = combined['volume_ratio_5'].fillna(1.0).clip(0.1, 10)
    
    # 前瞻收益
    combined['forward_return'] = combined.groupby('asset')['close'].transform(
        lambda x: x.pct_change().shift(-1)
    )
    
    # 去除缺失值
    valid_df = combined.dropna(subset=['rsi_6', 'volume_ratio_5', 'forward_return'])
    
    # 限制每只股票最多500天
    valid_df = valid_df.groupby('asset').tail(n_days).reset_index(drop=True)
    print(f'  有效记录数: {len(valid_df)}')
    
    # 格式化
    valid_df['date'] = valid_df['date'].dt.strftime('%Y-%m-%d')
    
    factor_df = valid_df[['date', 'asset', 'rsi_6', 'volume_ratio_5']].copy()
    return_df = valid_df[['date', 'asset', 'forward_return']].copy()
    
    # 保存
    batch_file = f'cache/factor_data/batch_{start_idx}_{end_idx}.json.gz'
    print(f'\n[保存] {batch_file}...')
    
    dates_list = sorted(factor_df['date'].unique())
    batch_data = {
        'meta': {
            'n_days': len(dates_list),
            'n_assets': len(factor_df['asset'].unique()),
            'start_idx': start_idx,
            'end_idx': end_idx,
            'date_range': {'start': dates_list[0], 'end': dates_list[-1]}
        },
        'factor_data': factor_df.to_dict('records'),
        'return_data': return_df.to_dict('records')
    }
    
    with gzip.open(batch_file, 'wt') as f:
        json.dump(batch_data, f)
    
    print(f'  ✓ 已保存: {len(factor_df)} 条记录')
    print(f'  ✓ 交易日数: {len(dates_list)}')
    print(f'  ✓ 日期范围: {dates_list[0]} ~ {dates_list[-1]}')
    print(f'结束时间: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}')
    
    return factor_df, return_df

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--start', type=int, default=0)
    parser.add_argument('--end', type=int, default=500)
    parser.add_argument('--n_days', type=int, default=500)
    
    args = parser.parse_args()
    
    process_batch(args.start, args.end, args.n_days)