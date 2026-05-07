#!/usr/bin/env python3
"""
测试动态过滤异常股票逻辑（修改后版本）

验证：
1. 数据缓存保留完整数据（不剔除异常股票）
2. IC 计算时动态过滤异常股票
3. 分层回测时动态过滤异常股票
"""

import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

from real_data_loader import RealDataLoader
from layered_backtest_optimized import LayeredBacktest, filter_abnormal_stocks
import pandas as pd
import numpy as np
import json
from datetime import datetime, timedelta

def test_dynamic_filter():
    """测试动态过滤逻辑"""
    print(f"\n{'='*60}")
    print(f"测试动态过滤异常股票逻辑")
    print(f"{'='*60}")
    
    # 创建测试数据（模拟真实场景）
    dates = pd.date_range(end=datetime.now(), periods=10, freq='B').strftime('%Y-%m-%d')
    assets = ['600000', '600001', '600002', '000001', '000002', '600003']
    
    # 模拟因子和收益数据
    factor_data = []
    return_data = []
    for date in dates:
        for asset in assets:
            factor_data.append({
                'date': date, 
                'asset': asset, 
                'rsi_6': np.random.uniform(30, 70)
            })
            return_data.append({
                'date': date, 
                'asset': asset, 
                'forward_return': np.random.uniform(-0.05, 0.05)
            })
    
    factor_df = pd.DataFrame(factor_data)
    return_df = pd.DataFrame(return_data)
    
    # 模拟状态缓存（设计不同状态）
    status_data = []
    for date in dates:
        for asset in assets:
            # 设计不同的状态
            if asset == '600000':
                # 正常股票
                volume = 1000000
                close = 10.0
                prev_close = 10.0
            elif asset == '600001':
                # ST股票
                volume = 1000000
                close = 10.0
                prev_close = 10.0
            elif asset == '600002':
                # 停牌股票
                volume = 0
                close = 10.0
                prev_close = 10.0
            elif asset == '000001':
                # 正常股票
                volume = 1000000
                close = 10.0
                prev_close = 10.0
            elif asset == '000002':
                # 涨停股票
                volume = 1000000
                close = 11.0  # 11.0 > 10.0 * 1.10 * 0.998 = 10.978
                prev_close = 10.0
            elif asset == '600003':
                # 跌停股票
                volume = 1000000
                close = 9.0  # 9.0 < 10.0 * 0.90 * 1.002 = 9.018
                prev_close = 10.0
            
            status_data.append({
                'date': date,
                'asset': asset,
                'volume': volume,
                'close': close,
                'prev_close': prev_close,
                'limit_up_price': prev_close * 1.10,
                'limit_down_price': prev_close * 0.90
            })
    
    status_cache = {'meta': {'version': '1.0'}, 'data': status_data}
    
    # 模拟股票名称映射
    code_to_name = {
        '600000': '浦发银行',      # 正常
        '600001': 'ST某某',        # ST股票
        '600002': '某某银行',      # 停牌
        '000001': '平安银行',      # 正常
        '000002': '万科A',         # 涨停
        '600003': '某某股份'       # 跌停
    }
    
    print(f"\\n测试数据:")
    print(f"  factor_df: {len(factor_df)} 条")
    print(f"  return_df: {len(return_df)} 条")
    print(f"  股票数: {len(assets)} 只")
    print(f"  日期数: {len(dates)} 天")
    
    # 测试动态过滤函数
    print(f"\\n{'='*60}")
    print(f"测试 RealDataLoader.filter_abnormal_stocks_dynamic")
    print(f"{'='*60}")
    
    loader = RealDataLoader(enable_cache=False)
    filtered_factor, filtered_return, stats = loader.filter_abnormal_stocks_dynamic(
        factor_df, return_df,
        status_cache=status_cache,
        code_to_name=code_to_name
    )
    
    print(f"\\n过滤结果验证:")
    print(f"  过滤后 factor_df: {len(filtered_factor)} 条")
    print(f"  过滤后 return_df: {len(filtered_return)} 条")
    
    # 验证过滤逻辑正确
    expected_removed = 10 * 4  # 每天过滤4只异常股票（ST、停牌、涨停、跌停）
    expected_remaining = 10 * 2  # 每天保留2只正常股票
    
    if stats['suspended'] == 10:  # 600002 每天1条 = 10天
        print(f"  ✓ 停牌股票过滤正确: {stats['suspended']} 条")
    else:
        print(f"  ! 停牌股票过滤异常: {stats['suspended']} 条（预期 10）")
    
    if stats['st_stocks'] == 10:  # 600001 每天1条 = 10天
        print(f"  ✓ ST股票过滤正确: {stats['st_stocks']} 条")
    else:
        print(f"  ! ST股票过滤异常: {stats['st_stocks']} 条（预期 10）")
    
    if stats['limit_up'] >= 10:  # 000002 每天1条 = 10天
        print(f"  ✓ 涨停股票过滤正确: {stats['limit_up']} 条")
    else:
        print(f"  ! 涨停股票过滤异常: {stats['limit_up']} 条（预期 >=10）")
    
    if stats['limit_down'] >= 10:  # 600003 每天1条 = 10天
        print(f"  ✓ 跌停股票过滤正确: {stats['limit_down']} 条")
    else:
        print(f"  ! 跌停股票过滤异常: {stats['limit_down']} 条（预期 >=10）")
    
    # 测试分层回测动态过滤
    print(f"\\n{'='*60}")
    print(f"测试 LayeredBacktest 动态过滤")
    print(f"{'='*60}")
    
    merged = pd.merge(factor_df, return_df, on=['date', 'asset'], how='inner')
    filtered_merged, bt_stats = filter_abnormal_stocks(
        merged,
        status_cache=status_cache,
        code_to_name=code_to_name
    )
    
    print(f"  分层回测过滤后: {len(filtered_merged)} 条")
    
    # 验证一致性
    if len(filtered_factor) == len(filtered_merged):
        print(f"  ✓ IC计算和分层回测过滤结果一致")
    else:
        print(f"  ! 过滤结果不一致: IC={len(filtered_factor)}, 分层={len(filtered_merged)}")
    
    print(f"\\n{'='*60}")
    print(f"测试完成！")
    print(f"{'='*60}")
    
    return filtered_factor, filtered_return, stats

if __name__ == '__main__':
    test_dynamic_filter()