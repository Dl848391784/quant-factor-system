#!/usr/bin/env python3
"""
量比因子计算测试脚本

测试目标：
1. 验证量比计算正确性
2. 验证缓存数据结构（新增 volume_ratio_5 字段）
3. 运行量比因子的 RankIC 分析
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from real_data_loader import RealDataLoader
import pandas as pd

def test_volume_ratio_calculation():
    """测试量比计算"""
    print("\n" + "="*60)
    print("【量比因子计算测试】")
    print("="*60)
    
    # 使用模拟数据快速测试（避免 API 请求阻塞）
    loader = RealDataLoader(enable_cache=False, use_mock=True)
    
    print("\n[Step 1] 加载少量股票数据（100只股票，250天）...")
    factor_df, return_df = loader.load_data(
        n_days=250,
        max_stocks=100,  # 只测试100只股票
        enable_complement=False
    )
    
    print(f"\n[Step 2] 检查因子数据结构...")
    print(f"  因子列: {factor_df.columns.tolist()}")
    
    if 'volume_ratio_5' not in factor_df.columns:
        print("  ✗ 错误：缺少 volume_ratio_5 字段！")
        return False
    
    print(f"  ✓ 包含 volume_ratio_5 字段")
    
    print(f"\n[Step 3] 检查量比范围...")
    vr_min = factor_df['volume_ratio_5'].min()
    vr_max = factor_df['volume_ratio_5'].max()
    vr_mean = factor_df['volume_ratio_5'].mean()
    vr_median = factor_df['volume_ratio_5'].median()
    
    print(f"  量比最小值: {vr_min:.2f}")
    print(f"  量比最大值: {vr_max:.2f}")
    print(f"  量比均值: {vr_mean:.2f}")
    print(f"  量比中位数: {vr_median:.2f}")
    
    # 验收标准：大部分在 0.5-3 之间
    vr_in_range = ((factor_df['volume_ratio_5'] >= 0.5) & (factor_df['volume_ratio_5'] <= 3)).mean()
    print(f"  量比在 0.5-3 范围内的比例: {vr_in_range:.2%}")
    
    if vr_in_range >= 0.5:
        print(f"  ✓ 量比范围合理")
    else:
        print(f"  ⚠ 量比范围可能异常")
    
    print(f"\n[Step 4] 因子数据预览（前10行）...")
    print(factor_df.head(10).to_string())
    
    print(f"\n[Step 5] 计算量比因子的 RankIC...")
    ic_df = loader.calculate_rank_ic(
        factor_df,
        return_df,
        factor_col='volume_ratio_5',
        enable_filter=True,
        enable_winsorize=True
    )
    
    if ic_df is not None and len(ic_df) > 0:
        mean_ic = ic_df['ic'].mean()
        std_ic = ic_df['ic'].std()
        icir = mean_ic / std_ic if std_ic > 0 else 0
        positive_ratio = (ic_df['ic'] > 0).mean()
        
        print(f"\n{'='*60}")
        print("【量比(5) RankIC 统计】")
        print(f"{'='*60}")
        print(f"  样本日期数: {len(ic_df)}")
        print(f"  平均 IC: {mean_ic:.4f}")
        print(f"  IC 标准差: {std_ic:.4f}")
        print(f"  ICIR: {icir:.4f}")
        print(f"  IC > 0 比例: {positive_ratio:.2%}")
        print(f"{'='*60}")
    else:
        print("  ✗ 无法计算 IC")
    
    print("\n✓ 测试完成")
    return True

if __name__ == '__main__':
    test_volume_ratio_calculation()