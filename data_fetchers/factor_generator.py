#!/usr/bin/env python3
"""
统一因子生成模块

职责：生成所有因子数据到缓存，提供单一数据源

遵循 PROJECT.md 规范：
- 输出到 cache/factor_data/
- 复用公共模块计算函数（遵循强制复用规范）

作者: 云瑶
创建日期: 2026-05-24
"""
import sys
from pathlib import Path

# 添加项目根目录到 sys.path
project_root = Path(__file__).parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

import json
import gzip
import pandas as pd
import numpy as np
from typing import Dict, Optional
from datetime import datetime

# 复用公共模块计算函数（遵循 PROJECT.md 强制复用规范）
from factor_ic.ic_kdj_j_1d import calculate_kdj_j
from factor_ic.ic_bollinger_pb_1d import calculate_bollinger_pb
from factor_ic.ic_turnover_surge_1d import calculate_turnover_surge

# ============================================================================
# 参数统一管理
# ============================================================================

DEFAULT_N_BOLLINGER = 20     # 布林带移动平均周期
DEFAULT_K_BOLLINGER = 2.0    # 布林带标差倍数
DEFAULT_N_KDJ = 9            # KDJ RSV计算周期
DEFAULT_M1_KDJ = 3           # KDJ K值平滑周期
DEFAULT_M2_KDJ = 3           # KDJ D值平滑周期
DEFAULT_SURGE_WINDOW = 5     # 换手率突增均值计算窗口

EPSILON = 1e-10              # 避免除零阈值

DEFAULT_CACHE_DIR = Path(__file__).parent.parent / 'cache' / 'factor_data'


# ============================================================================
# 统一因子生成入口
# ============================================================================

def generate_all_factors(
    factor_data_path: Optional[Path] = None,
    turnover_data_path: Optional[Path] = None,
    output_path: Optional[Path] = None,
    verbose: bool = True
) -> Dict:
    """
    生成所有因子数据
    
    参数:
        factor_data_path: 基础因子数据路径（默认 factor_data.json.gz）
        turnover_data_path: 换手率数据路径（默认 turnover_rate_data.json.gz）
        output_path: 输出路径（默认 factor_data_extended.json.gz）
        verbose: 是否打印进度
    
    返回:
        元数据字典（包含生成时间、因子列表等）
    """
    # 默认路径
    factor_data_path = factor_data_path or DEFAULT_CACHE_DIR / 'factor_data.json.gz'
    turnover_data_path = turnover_data_path or DEFAULT_CACHE_DIR / 'turnover_rate_data.json.gz'
    output_path = output_path or DEFAULT_CACHE_DIR / 'factor_data_extended.json.gz'
    
    if verbose:
        print("=" * 60)
        print("统一因子生成模块")
        print("=" * 60)
    
    # ========== Step 1: 加载基础因子数据 ==========
    if verbose:
        print("Step 1: 加载基础因子数据...")
    
    with gzip.open(factor_data_path, 'rt') as f:
        base_data = json.load(f)
    
    factor_df = pd.DataFrame(base_data['data'])
    factor_df['date'] = pd.to_datetime(factor_df['date'])
    
    if verbose:
        print(f"  基础数据记录数: {len(factor_df)}")
        print(f"  基础因子列: rsi_6, volume_ratio_5")
    
    # ========== Step 2: 加载换手率数据 ==========
    if verbose:
        print("Step 2: 加载换手率数据...")
    
    with gzip.open(turnover_data_path, 'rt') as f:
        turnover_data = json.load(f)
    
    turnover_df = pd.DataFrame(turnover_data['data'])
    # 使用 format='mixed' 处理不同日期格式（有的带时间，有的不带）
    turnover_df['date'] = pd.to_datetime(turnover_df['date'], format='mixed')
    
    if verbose:
        print(f"  换手率数据记录数: {len(turnover_df)}")
    
    # 合并换手率
    factor_df = factor_df.merge(
        turnover_df[['date', 'asset', 'turnover_rate']],
        on=['date', 'asset'],
        how='left'
    )
    
    if verbose:
        print(f"  合并后记录数: {len(factor_df)}")
    
    # ========== Step 3: 计算 bollinger_pb ==========
    if verbose:
        print("Step 3: 计算布林带 %B 因子...")
    
    factor_df = calculate_bollinger_pb(factor_df)
    
    if verbose:
        valid_count = factor_df['bollinger_pb'].notna().sum()
        print(f"  有效 bollinger_pb: {valid_count}")
    
    # ========== Step 4: 计算 kdj_j ==========
    if verbose:
        print("Step 4: 计算 KDJ_J 因子...")
    
    factor_df = calculate_kdj_j(factor_df)
    
    if verbose:
        valid_count = factor_df['kdj_j'].notna().sum()
        print(f"  有效 kdj_j: {valid_count}")
    
    # ========== Step 5: 计算 turnover_surge ==========
    if verbose:
        print("Step 5: 计算换手率突增因子...")
    
    factor_df = calculate_turnover_surge(factor_df)
    
    if verbose:
        valid_count = factor_df['turnover_surge'].notna().sum()
        print(f"  有效 turnover_surge: {valid_count}")
    
    # ========== Step 6: 格式化输出 ==========
    if verbose:
        print("Step 6: 格式化输出...")
    
    factor_df['date'] = factor_df['date'].dt.strftime('%Y-%m-%d')
    
    # 保留所有因子列
    output_cols = [
        'date', 'asset', 'open', 'close', 'high', 'low',
        'rsi_6', 'volume_ratio_5',
        'bollinger_pb', 'kdj_j', 'turnover_surge'
    ]
    
    output_df = factor_df[output_cols].copy()
    
    # ========== Step 7: 保存输出 ==========
    if verbose:
        print("Step 7: 保存输出...")
    
    output_data = {
        'dates': sorted(factor_df['date'].unique().tolist()),
        'data': output_df.to_dict('records')
    }
    
    with gzip.open(output_path, 'wt') as f:
        json.dump(output_data, f)
    
    if verbose:
        print(f"  输出路径: {output_path}")
        print(f"  输出记录数: {len(output_df)}")
    
    # ========== Step 8: 返回元数据 ==========
    metadata = {
        'generated_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'total_records': len(output_df),
        'factor_columns': output_cols[6:],  # 因子列（不含基础列）
        'input_sources': {
            'factor_data': str(factor_data_path),
            'turnover_data': str(turnover_data_path)
        },
        'output_path': str(output_path)
    }
    
    if verbose:
        print("=" * 60)
        print("因子生成完成")
        print(f"生成时间: {metadata['generated_at']}")
        print(f"因子列: {metadata['factor_columns']}")
        print("=" * 60)
    
    return metadata


# ============================================================================
# CLI 入口
# ============================================================================

def main():
    """CLI 主入口"""
    import argparse
    
    parser = argparse.ArgumentParser(description='统一因子生成模块')
    parser.add_argument('--output', type=str, default=None, help='输出路径')
    parser.add_argument('--quiet', action='store_true', help='静默模式')
    
    args = parser.parse_args()
    
    output_path = Path(args.output) if args.output else None
    
    metadata = generate_all_factors(
        output_path=output_path,
        verbose=not args.quiet
    )
    
    return metadata


if __name__ == '__main__':
    main()