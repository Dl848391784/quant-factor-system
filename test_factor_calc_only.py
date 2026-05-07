#!/usr/bin/env python3
"""
因子计算纯性能测试（使用模拟数据）

只测试因子计算部分的性能，避免网络请求
"""

import time
import pandas as pd
import numpy as np

def generate_mock_price_data(n_stocks=100, n_days=73):
    """生成模拟价格数据"""
    np.random.seed(42)
    
    dates = pd.date_range('2023-01-01', periods=n_days, freq='B')
    assets = [f'stock_{i:04d}' for i in range(n_stocks)]
    
    data = []
    for asset in assets:
        base_price = np.random.uniform(10, 100)
        current_price = base_price
        
        for date in dates:
            change = np.random.uniform(-0.05, 0.05)
            current_price = current_price * (1 + change)
            
            high = current_price * np.random.uniform(1.0, 1.03)
            low = current_price * np.random.uniform(0.97, 1.0)
            open_price = current_price * np.random.uniform(0.98, 1.02)
            volume = np.random.uniform(100000, 5000000)
            
            data.append({
                'date': date,
                'asset': asset,
                'open': round(open_price, 2),
                'high': round(high, 2),
                'low': round(low, 2),
                'close': round(current_price, 2),
                'volume': int(volume)
            })
    
    return pd.DataFrame(data)


def test_original_factor_calculation(combined):
    """测试原版因子计算（逐股票循环）"""
    print("\n[原版] 逐股票循环计算因子...")
    start_time = time.time()
    
    factor_rows = []
    return_rows = []
    
    assets = combined['asset'].unique()
    
    def calculate_rsi_original(close_prices, period=6):
        """原版 RSI 计算"""
        delta = close_prices.diff()
        gain = delta.where(delta > 0, 0)
        loss = (-delta).where(delta < 0, 0)
        
        avg_gain = gain.ewm(alpha=1/period, adjust=False).mean()
        avg_loss = loss.ewm(alpha=1/period, adjust=False).mean()
        
        rs = avg_gain / avg_loss
        rsi = 100 - (100 / (1 + rs))
        rsi = rsi.fillna(50).clip(0, 100)
        return rsi
    
    for asset in assets:
        stock_df = combined[combined['asset'] == asset].copy()
        stock_df = stock_df.sort_values('date')
        
        stock_df['rsi_6'] = calculate_rsi_original(stock_df['close'], period=6)
        stock_df['forward_return'] = stock_df['close'].pct_change().shift(-1)
        
        valid_df = stock_df.dropna(subset=['rsi_6', 'forward_return'])
        
        # 逐行迭代（最慢的部分）
        for _, row in valid_df.iterrows():
            factor_rows.append({
                'date': row['date'].strftime('%Y-%m-%d'),
                'asset': row['asset'],
                'rsi_6': round(row['rsi_6'], 2)
            })
            return_rows.append({
                'date': row['date'].strftime('%Y-%m-%d'),
                'asset': row['asset'],
                'forward_return': round(row['forward_return'], 6)
            })
    
    factor_df = pd.DataFrame(factor_rows)
    return_df = pd.DataFrame(return_rows)
    
    elapsed = time.time() - start_time
    print(f"[原版] 耗时: {elapsed:.4f} 秒")
    print(f"[原版] 结果: {len(factor_df)} 条因子数据")
    
    return elapsed, factor_df, return_df


def test_optimized_factor_calculation(combined):
    """测试优化版因子计算（向量化）"""
    print("\n[优化版] 向量化计算因子...")
    start_time = time.time()
    
    # 1. 按股票分组排序
    combined_sorted = combined.sort_values(['asset', 'date'])
    
    # 2. 向量化计算 RSI
    def calculate_rsi_vectorized(close_prices, period=6):
        delta = close_prices.diff()
        gain = delta.where(delta > 0, 0)
        loss = (-delta).where(delta < 0, 0)
        avg_gain = gain.ewm(alpha=1/period, adjust=False).mean()
        avg_loss = loss.ewm(alpha=1/period, adjust=False).mean()
        rs = avg_gain / avg_loss
        rsi = 100 - (100 / (1 + rs))
        return rsi.fillna(50).clip(0, 100)
    
    combined_sorted['rsi_6'] = combined_sorted.groupby('asset')['close'].transform(
        lambda x: calculate_rsi_vectorized(x, period=6)
    )
    
    # 3. 向量化计算 forward_return
    combined_sorted['forward_return'] = combined_sorted.groupby('asset')['close'].transform(
        lambda x: x.pct_change().shift(-1)
    )
    
    # 4. 去除缺失值
    valid_df = combined_sorted.dropna(subset=['rsi_6', 'forward_return'])
    
    # 5. 格式化输出（向量化）
    valid_df['date'] = valid_df['date'].dt.strftime('%Y-%m-%d')
    valid_df['rsi_6'] = valid_df['rsi_6'].round(2)
    valid_df['forward_return'] = valid_df['forward_return'].round(6)
    
    # 6. 构建因子和收益 DataFrame（直接切片）
    factor_df = valid_df[['date', 'asset', 'rsi_6']].copy()
    return_df = valid_df[['date', 'asset', 'forward_return']].copy()
    
    elapsed = time.time() - start_time
    print(f"[优化版] 耗时: {elapsed:.4f} 秒")
    print(f"[优化版] 结果: {len(factor_df)} 条因子数据")
    
    return elapsed, factor_df, return_df


def run_performance_test():
    """运行性能测试"""
    print("="*60)
    print("因子计算性能对比测试")
    print("="*60)
    
    # 测试不同规模
    test_cases = [
        (100, 30, "小规模 (100股×30天)"),
        (500, 73, "中规模 (500股×73天)"),
        (1000, 73, "大规模 (1000股×73天)"),
        (3000, 73, "真实规模 (3000股×73天)"),
    ]
    
    results = []
    
    for n_stocks, n_days, desc in test_cases:
        print(f"\n{'='*60}")
        print(f"测试: {desc}")
        print(f"{'='*60}")
        
        # 生成模拟数据
        print(f"生成模拟价格数据...")
        combined = generate_mock_price_data(n_stocks, n_days)
        print(f"数据量: {len(combined)} 条")
        
        # 测试原版
        try:
            time_orig, factor_orig, return_orig = test_original_factor_calculation(combined)
        except Exception as e:
            print(f"[原版] 错误: {e}")
            time_orig = None
        
        # 测试优化版
        try:
            time_opt, factor_opt, return_opt = test_optimized_factor_calculation(combined)
        except Exception as e:
            print(f"[优化版] 错误: {e}")
            time_opt = None
        
        # 对比结果
        if time_orig and time_opt:
            speedup = time_orig / time_opt
            print(f"\n[性能对比] 优化版比原版快 {speedup:.1f}x 倍")
            
            # 验证结果一致性
            if factor_orig is not None and factor_opt is not None:
                # 排序后对比
                factor_orig_sorted = factor_orig.sort_values(['date', 'asset']).reset_index(drop=True)
                factor_opt_sorted = factor_opt.sort_values(['date', 'asset']).reset_index(drop=True)
                
                if len(factor_orig_sorted) == len(factor_opt_sorted):
                    diff = (factor_orig_sorted['rsi_6'] - factor_opt_sorted['rsi_6']).abs().max()
                    print(f"[结果验证] RSI 最大差异: {diff:.6f}")
                    if diff < 0.01:
                        print(f"[结果验证] ✅ 结果一致")
                    else:
                        print(f"[结果验证] ⚠️ 存在差异")
        
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