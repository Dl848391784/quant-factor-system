#!/usr/bin/env python3
"""
统一因子生成模块

职责：生成所有因子数据到缓存，提供单一数据源

遵循 PROJECT.md 规范：
- 输出到 cache/factor_data/
- 模块边界：不依赖 factor_ic、backtest 模块

作者: 云瑶
创建日期: 2026-05-24
"""

import sys
from pathlib import Path

# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent.parent))

import json
import gzip
import pandas as pd
import numpy as np
from typing import Dict, Optional
from datetime import datetime

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
# 布林带 %B 计算（从 ic_bollinger_pb_1d.py 迁移）
# ============================================================================

def calculate_bollinger_pb(
    factor_df: pd.DataFrame,
    n: int = DEFAULT_N_BOLLINGER,
    k: float = DEFAULT_K_BOLLINGER
) -> pd.DataFrame:
    """
    计算布林带 %B 因子（从 ic_bollinger_pb_1d.py 迁移）
    
    使用 transform 方法避免索引不匹配问题
    """
    factor_df = factor_df.copy()
    factor_df = factor_df.sort_values(['asset', 'date'])
    
    # 使用 transform 方法计算滚动统计
    middle = factor_df.groupby('asset', group_keys=False)['close'].transform(
        lambda x: x.rolling(window=n).mean()
    )
    std_dev = factor_df.groupby('asset', group_keys=False)['close'].transform(
        lambda x: x.rolling(window=n).std()
    )
    
    # 计算布林带
    upper = middle + k * std_dev
    lower = middle - k * std_dev
    band_width = upper - lower
    
    # 异常检测
    abnormal_mask = band_width < 0
    narrow_band_mask = (band_width >= 0) & (band_width < EPSILON)
    
    # 安全带宽计算
    safe_band_width = band_width.mask(abnormal_mask).clip(lower=EPSILON)
    bollinger_pb = (factor_df['close'] - lower) / safe_band_width
    
    # 异常处理
    bollinger_pb = bollinger_pb.where(~narrow_band_mask, 0.5)
    bollinger_pb = bollinger_pb.where(~abnormal_mask, np.nan)
    
    abnormal_count = abnormal_mask.sum()
    if abnormal_count > 0:
        print(f"  [警告] 检测到 {abnormal_count} 个异常布林带宽度（负值）")
    
    factor_df['bollinger_pb'] = bollinger_pb
    
    return factor_df


# ============================================================================
# KDJ_J 计算（从 ic_kdj_j_1d.py 迁移）
# ============================================================================

def _calculate_ewm_with_initial(
    series: pd.Series,
    alpha: float,
    initial_value: float
) -> pd.Series:
    """计算 EWM 递推值（正确处理 NaN 前缀版本）
    
    公共函数：统一处理 K 值和 D 值的 EWM 递推计算
    
    参数:
        series: 输入序列（RSV 或 K）
        alpha: EWM alpha 参数
        initial_value: 初始值（KDJ 标准为 50.0）
    
    返回:
        EWM 递推结果序列
    """
    if len(series) == 0:
        return series
    
    if series.isna().all():
        return series
    
    # 在第一个有效值前插入虚拟初始值
    series_with_initial = pd.concat([
        pd.Series([initial_value], index=[-1]),
        series
    ], ignore_index=True)
    
    # 计算 ewm 递推
    ewm_result = series_with_initial.ewm(
        alpha=alpha,
        adjust=False,
        ignore_na=True
    ).mean()
    
    # 去除虚拟初始值，恢复原始索引
    result = ewm_result.iloc[1:].copy()
    result.index = series.index
    
    # 恢复原始 NaN
    original_na_mask = series.isna()
    result[original_na_mask] = np.nan
    
    return result


def calculate_kdj_j(
    factor_df: pd.DataFrame,
    n: int = DEFAULT_N_KDJ,
    m1: int = DEFAULT_M1_KDJ,
    m2: int = DEFAULT_M2_KDJ
) -> pd.DataFrame:
    """
    计算 KDJ_J 因子（从 ic_kdj_j_1d.py 迁移）
    
    参数:
        factor_df: 包含 close, high, low, date, asset 列的 DataFrame
        n: RSV 计算周期（默认 9）
        m1: K值平滑周期（默认 3）
        m2: D值平滑周期（默认 3）
    
    返回:
        添加 kdj_j 列的 DataFrame
    """
    factor_df = factor_df.copy()
    factor_df = factor_df.sort_values(['asset', 'date'])
    
    # ewm alpha 参数
    alpha_k = 1 / m1
    alpha_d = 1 / m2
    
    # 计算 RSV（使用 transform）
    low_min = factor_df.groupby('asset', group_keys=False)['low'].transform(
        lambda x: x.rolling(n, min_periods=n).min()
    )
    high_max = factor_df.groupby('asset', group_keys=False)['high'].transform(
        lambda x: x.rolling(n, min_periods=n).max()
    )
    
    # 避免除零
    denom = high_max - low_min
    narrow_range_mask = denom < EPSILON
    safe_denom = denom.where(~narrow_range_mask, EPSILON)
    rsv = (factor_df['close'] - low_min) / safe_denom * 100
    rsv = rsv.where(~narrow_range_mask, 50.0)
    
    # 计算 K 和 D
    k = rsv.groupby(factor_df['asset']).transform(
        lambda x: _calculate_ewm_with_initial(x, alpha_k, 50.0)
    )
    d = k.groupby(factor_df['asset']).transform(
        lambda x: _calculate_ewm_with_initial(x, alpha_d, 50.0)
    )
    
    # 计算 J
    factor_df['kdj_j'] = 3 * k - 2 * d
    
    return factor_df


# ============================================================================
# 换手率突增计算（从 ic_turnover_surge_1d.py 迁移）
# ============================================================================

def calculate_turnover_surge(
    factor_df: pd.DataFrame,
    surge_window: int = DEFAULT_SURGE_WINDOW
) -> pd.DataFrame:
    """
    计算换手率突增因子（从 ic_turnover_surge_1d.py 迁移）
    
    参数:
        factor_df: 包含 turnover_rate、close 列的 DataFrame【必需】
        surge_window: 换手率均值计算窗口（默认 5）
    
    返回:
        添加 turnover_surge 列的 DataFrame
    """
    factor_df = factor_df.copy()
    
    # 计算换手率均值（不含当日）
    avg_turnover = factor_df.groupby('asset')['turnover_rate'].transform(
        lambda x: x.shift(1).rolling(surge_window, min_periods=surge_window).mean()
    )
    
    # 检测 avg_turnover 异常值
    zero_avg_mask = (avg_turnover.notna()) & (avg_turnover.abs() < EPSILON)
    zero_avg_count = zero_avg_mask.sum()
    
    if zero_avg_count > 0:
        print(f"  [警告] 检测到 {zero_avg_count} 个 avg_turnover 接近零")
    
    safe_avg_turnover = avg_turnover.where(~zero_avg_mask, np.nan)
    turnover_surge = factor_df['turnover_rate'] / safe_avg_turnover
    
    # 异常检测（负值）
    abnormal_mask = turnover_surge < 0
    abnormal_count = abnormal_mask.sum()
    
    if abnormal_count > 0:
        print(f"  [警告] 检测到 {abnormal_count} 个异常换手率突增（负值）")
        turnover_surge = turnover_surge.where(~abnormal_mask, np.nan)
    
    # 计算涨跌幅
    prev_close = factor_df.groupby('asset')['close'].transform(lambda x: x.shift(1))
    
    # 异常检测（前收盘价 <= EPSILON）
    abnormal_prev_close_mask = (prev_close.notna()) & (prev_close <= EPSILON)
    abnormal_prev_close_count = abnormal_prev_close_mask.sum()
    
    if abnormal_prev_close_count > 0:
        print(f"  [警告] 检测到 {abnormal_prev_close_count} 个异常前收盘价")
    
    safe_prev_close = prev_close.mask(prev_close.isna() | (prev_close <= EPSILON))
    daily_return = (factor_df['close'] - safe_prev_close) / safe_prev_close
    
    # 应用业务筛选条件
    condition = (turnover_surge > 1) & (daily_return > 0)
    turnover_surge = turnover_surge.where(condition, np.nan)
    
    factor_df['turnover_surge'] = turnover_surge
    
    return factor_df


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