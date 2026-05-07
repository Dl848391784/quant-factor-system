#!/usr/bin/env python3
"""
分层回测性能测试脚本

对比原版和优化版的性能差异
"""

import time
import pandas as pd
import numpy as np

# 测试数据生成
def generate_test_data(n_stocks=100, n_days=30, seed=42):
    """生成测试数据"""
    np.random.seed(seed)
    
    dates = pd.date_range('2023-01-01', periods=n_days, freq='B')
    assets = [f'stock_{i:04d}' for i in range(n_stocks)]
    
    # 生成所有组合
    data = []
    for date in dates:
        for asset in assets:
            data.append({
                'date': date,
                'asset': asset,
                'rsi_6': np.random.uniform(10, 90),
                'forward_return': np.random.uniform(-0.05, 0.05)
            })
    
    df = pd.DataFrame(data)
    factor_df = df[['date', 'asset', 'rsi_6']]
    return_df = df[['date', 'asset', 'forward_return']]
    
    return factor_df, return_df


def test_original(factor_df, return_df):
    """测试原版"""
    from layered_backtest_original import LayeredBacktest
    
    print("\n[原版] 开始测试...")
    start_time = time.time()
    
    backtest = LayeredBacktest(num_layers=5)
    result = backtest.run(factor_df, return_df, 'rsi_6', 'forward_return')
    
    elapsed = time.time() - start_time
    print(f"[原版] 耗时: {elapsed:.4f} 秒")
    
    return elapsed, result


def test_optimized(factor_df, return_df):
    """测试优化版"""
    from layered_backtest_optimized import LayeredBacktest
    
    print("\n[优化版] 开始测试...")
    start_time = time.time()
    
    backtest = LayeredBacktest(num_layers=5)
    result = backtest.run(factor_df, return_df, 'rsi_6', 'forward_return')
    
    elapsed = time.time() - start_time
    print(f"[优化版] 耗时: {elapsed:.4f} 秒")
    
    return elapsed, result


def compare_results(result_original, result_optimized):
    """对比结果是否一致"""
    print("\n[结果对比]")
    
    # 对比各层收益
    layer_returns_diff = (result_original.layer_returns - result_optimized.layer_returns).abs().max().max()
    print(f"  各层收益最大差异: {layer_returns_diff:.6f}")
    
    # 对比统计指标
    stats_diff = (result_original.statistics - result_optimized.statistics).abs().max().max()
    print(f"  统计指标最大差异: {stats_diff:.6f}")
    
    # 对比多空组合
    ls_diff = (result_original.long_short['daily_return'] - result_optimized.long_short['daily_return']).abs().max()
    print(f"  多空组合最大差异: {ls_diff:.6f}")
    
    if layer_returns_diff < 1e-6:
        print("  ✅ 结果一致")
        return True
    else:
        print("  ⚠️ 结果存在差异（可能因分层方法略有不同）")
        return False


def run_performance_test():
    """运行性能测试"""
    print("="*60)
    print("分层回测性能测试")
    print("="*60)
    
    # 测试不同数据规模
    test_cases = [
        (100, 30, "小数据集 (100股×30天)"),
        (500, 50, "中数据集 (500股×50天)"),
        (1000, 73, "大数据集 (1000股×73天)"),
        (3000, 73, "真实规模 (3000股×73天)"),
    ]
    
    results = []
    
    for n_stocks, n_days, desc in test_cases:
        print(f"\n{'='*60}")
        print(f"测试: {desc}")
        print(f"{'='*60}")
        
        # 生成测试数据
        print(f"生成测试数据: {n_stocks} 只股票, {n_days} 个交易日")
        factor_df, return_df = generate_test_data(n_stocks, n_days)
        print(f"数据量: {len(factor_df)} 条")
        
        # 测试原版
        try:
            time_orig, result_orig = test_original(factor_df, return_df)
        except Exception as e:
            print(f"[原版] 错误: {e}")
            time_orig = None
            result_orig = None
        
        # 测试优化版
        try:
            time_opt, result_opt = test_optimized(factor_df, return_df)
        except Exception as e:
            print(f"[优化版] 错误: {e}")
            time_opt = None
            result_opt = None
        
        # 对比结果
        if result_orig and result_opt:
            compare_results(result_orig, result_opt)
        
        if time_orig and time_opt:
            speedup = time_orig / time_opt
            print(f"\n[性能提升] {speedup:.1f}x 倍")
        
        results.append({
            'test': desc,
            'stocks': n_stocks,
            'days': n_days,
            'time_original': time_orig,
            'time_optimized': time_opt,
        })
    
    # 汇总结果
    print(f"\n{'='*60}")
    print("性能测试汇总")
    print(f"{'='*60}")
    print(f"{'测试':<30} {'原版(秒)':<12} {'优化版(秒)':<12} {'提升':<10}")
    print("-" * 64)
    
    for r in results:
        if r['time_original'] and r['time_optimized']:
            speedup = r['time_original'] / r['time_optimized']
            print(f"{r['test']:<30} {r['time_original']:<12.4f} {r['time_optimized']:<12.4f} {speedup:.1f}x")
        else:
            print(f"{r['test']:<30} {'N/A':<12} {'N/A':<12} {'N/A':<10}")
    
    print("="*60)


if __name__ == '__main__':
    run_performance_test()