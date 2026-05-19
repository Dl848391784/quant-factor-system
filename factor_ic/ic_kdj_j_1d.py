#!/usr/bin/env python3
"""
KDJ_J_1D IC 计算器（缓存版） - 1日收益周期

从缓存数据计算 KDJ_J 因子的反向排名 Rank IC。
不再实时拉取数据，直接读取 cache/factor_data/ 下的缓存。

因子定义：
- RSV(N) = (Close_t - Low_N) / (High_N - Low_N) × 100
- K_t = K_{t-1} × (M1-1)/M1 + RSV_t × 1/M1
- D_t = D_{t-1} × (M2-1)/M2 + K_t × 1/M2
- J_t = 3 × K_t - 2 × D_t

参数：
- N = 9（RSV 计算周期）
- M1 = 3（K值平滑周期）
- M2 = 3（D值平滑周期）

因子逻辑：
- J 值 > 100：超买，预期下跌
- J 值 < 0：超卖，预期反弹
- 使用反向排名（J值高排名低）

作者: 云舟
日期: 2026-04-07（重构: 2026-05-10）
"""

import sys
from pathlib import Path

# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent.parent))

import pandas as pd
import numpy as np
import gzip
import json
from typing import Tuple, Optional
from datetime import datetime

# 导入 IC 计算模块（支持方向验证）
from factor_ic.common.ic_calculator import calculate_ic_with_direction_verification

# 导入数据完整性检查模块
from factor_ic.common.data_completeness import check_data_completeness, get_ic_output_path

# 导入类型转换模块
from factor_ic.common.convert_types import convert_to_native_types

# 缓存路径
CACHE_DIR = Path(__file__).parent.parent / 'cache' / 'factor_data'
FACTOR_CACHE = CACHE_DIR / 'factor_data.json.gz'
RETURN_CACHE = CACHE_DIR / 'return_data.json.gz'


# ============================================================
# KDJ_J 因子计算函数
# ============================================================

def calculate_kdj_j_for_stock_vectorized(
    stock_data: pd.DataFrame,
    n: int = 9,
    m1: int = 3,
    m2: int = 3,
    initial_k: float = 50.0,
    initial_d: float = 50.0
) -> pd.DataFrame:
    """
    计算单只股票的 KDJ_J 因子（向量化版本，高效）
    
    使用 pandas 滚动窗口和 ewm 进行向量化计算，
    比逐行循环快 100 倍以上。
    
    Args:
        stock_data: 单只股票的历史数据，包含 close, high, low
        n: RSV 计算周期（默认 9）
        m1: K值平滑周期（默认 3）
        m2: D值平滑周期（默认 3）
        initial_k: K初始值（默认 50）
        initial_d: D初始值（默认 50）
        
    Returns:
        包含 rsv, k, d, j 列的 DataFrame
    """
    # 确保数据按日期排序
    stock_data = stock_data.sort_values('date').copy()
    
    # 计算 RSV（向量化）
    rolling_high = stock_data['high'].rolling(window=n, min_periods=1).max()
    rolling_low = stock_data['low'].rolling(window=n, min_periods=1).min()
    
    # RSV = (Close - Low_N) / (High_N - Low_N) * 100
    diff = rolling_high - rolling_low
    rsv = np.where(diff == 0, 50.0, (stock_data['close'] - rolling_low) / diff * 100)
    stock_data['rsv'] = rsv
    
    # 计算 K（使用 ewm）
    alpha_k = 1.0 / m1
    stock_data['k'] = stock_data['rsv'].ewm(alpha=alpha_k, adjust=False).mean()
    
    # 修正第一个 K 值
    if len(stock_data) > 0:
        stock_data.loc[stock_data.index[0], 'k'] = initial_k * (m1 - 1) / m1 + stock_data['rsv'].iloc[0] / m1
    
    # 计算 D
    alpha_d = 1.0 / m2
    stock_data['d'] = stock_data['k'].ewm(alpha=alpha_d, adjust=False).mean()
    
    # 修正第一个 D 值
    if len(stock_data) > 0:
        stock_data.loc[stock_data.index[0], 'd'] = initial_d * (m2 - 1) / m2 + stock_data['k'].iloc[0] / m2
    
    # 计算 J = 3K - 2D
    stock_data['j'] = 3 * stock_data['k'] - 2 * stock_data['d']
    
    return stock_data


def calculate_kdj_j_factor(
    factor_df: pd.DataFrame,
    n: int = 9,
    m1: int = 3,
    m2: int = 3
) -> Tuple[pd.DataFrame, dict]:
    """
    计算所有股票的 KDJ_J 因子（向量化版本）
    
    Args:
        factor_df: 包含 date, asset, close, high, low 的 DataFrame
        n: RSV 计算周期（默认 9）
        m1: K值平滑周期（默认 3）
        m2: D值平滑周期（默认 3）
        
    Returns:
        (处理后的 factor_df, 统计信息)
    """
    print(f"\n[因子计算] KDJ_J 因子 (N={n}, M1={m1}, M2={m2})")
    
    stats = {
        'total_records': len(factor_df),
        'valid_records': 0,
        'missing_price_count': 0,
        'n': n,
        'm1': m1,
        'm2': m2
    }
    
    if factor_df.empty:
        print("  ✗ 数据为空")
        return factor_df, stats
    
    # 检查必要列
    required_cols = ['date', 'asset', 'close', 'high', 'low']
    missing_cols = [c for c in required_cols if c not in factor_df.columns]
    if missing_cols:
        print(f"  ✗ 缺少必要列: {missing_cols}")
        return factor_df, stats
    
    # 统计缺失数据
    missing_price_mask = (
        factor_df['close'].isna() | 
        factor_df['high'].isna() | 
        factor_df['low'].isna()
    )
    stats['missing_price_count'] = int(missing_price_mask.sum())
    
    print(f"  总记录数: {stats['total_records']:,}")
    print(f"  价格缺失数: {stats['missing_price_count']:,}")
    
    # 确保按日期排序
    factor_df = factor_df.sort_values(['asset', 'date']).copy()
    
    # 向量化计算 RSV
    print("  [Step 1] 计算 RSV...")
    factor_df['rolling_high'] = factor_df.groupby('asset')['high'].transform(
        lambda x: x.rolling(window=n, min_periods=1).max()
    )
    factor_df['rolling_low'] = factor_df.groupby('asset')['low'].transform(
        lambda x: x.rolling(window=n, min_periods=1).min()
    )
    
    diff = factor_df['rolling_high'] - factor_df['rolling_low']
    factor_df['rsv'] = np.where(
        diff == 0, 
        50.0, 
        (factor_df['close'] - factor_df['rolling_low']) / diff * 100
    )
    
    factor_df.drop(columns=['rolling_high', 'rolling_low'], inplace=True)
    
    # 计算 K
    print("  [Step 2] 计算 K...")
    alpha_k = 1.0 / m1
    factor_df['k'] = factor_df.groupby('asset')['rsv'].transform(
        lambda x: x.ewm(alpha=alpha_k, adjust=False).mean()
    )
    
    # 计算 D
    print("  [Step 3] 计算 D...")
    alpha_d = 1.0 / m2
    factor_df['d'] = factor_df.groupby('asset')['k'].transform(
        lambda x: x.ewm(alpha=alpha_d, adjust=False).mean()
    )
    
    # 计算 J = 3K - 2D
    print("  [Step 4] 计算 J...")
    factor_df['kdj_j'] = 3 * factor_df['k'] - 2 * factor_df['d']
    
    stats['valid_records'] = int(factor_df['kdj_j'].notna().sum())
    print(f"\n  有效记录数: {stats['valid_records']:,}")
    
    # 输出因子统计
    valid_values = factor_df['kdj_j'].dropna()
    if len(valid_values) > 0:
        print(f"\n  因子统计:")
        print(f"    均值:   {valid_values.mean():.2f}")
        print(f"    标准差: {valid_values.std():.2f}")
        print(f"    最小值: {valid_values.min():.2f}")
        print(f"    最大值: {valid_values.max():.2f}")
        
        overbought = int((valid_values > 100).sum())
        oversold = int((valid_values < 0).sum())
        print(f"\n  超买(J>100): {overbought:,} ({overbought/len(valid_values)*100:.2f}%)")
        print(f"  超卖(J<0):   {oversold:,} ({oversold/len(valid_values)*100:.2f}%)")
    
    return factor_df, stats


def load_data_from_cache(
    n: int = 9,
    m1: int = 3,
    m2: int = 3
) -> Tuple[pd.DataFrame, pd.DataFrame, dict]:
    """
    从缓存加载因子数据和收益数据，并计算 KDJ_J 因子
    
    参数:
        n: RSV 计算周期
        m1: K值平滑周期
        m2: D值平滑周期
        
    返回:
        (factor_df, return_df, raw_metadata)
        - factor_df: 过滤后的因子数据 DataFrame（含 KDJ_J）
        - return_df: 过滤后的收益数据 DataFrame
        - raw_metadata: 原始数据元信息字典
            - period_start: 原始缓存最小日期
            - period_end: 原始缓存最大日期
            - total_days: 原始缓存日期数
    
    规范:
        period 和 total_days 基于 dropna 前的原始缓存数据
        （遵循 PROJECT.md 输出字段语义规范）
    """
    print("\n[数据加载] 从缓存读取数据...")
    
    # 加载因子数据
    if not FACTOR_CACHE.exists():
        raise FileNotFoundError(f"因子缓存不存在: {FACTOR_CACHE}")
    
    with gzip.open(FACTOR_CACHE, 'rt', encoding='utf-8') as f:
        factor_data = json.load(f)
    
    factor_df = pd.DataFrame(factor_data['data'])
    print(f"  - 因子数据: {len(factor_df)} 行, {factor_df['asset'].nunique()} 只股票")
    
    # 加载收益数据
    if not RETURN_CACHE.exists():
        raise FileNotFoundError(f"收益缓存不存在: {RETURN_CACHE}")
    
    with gzip.open(RETURN_CACHE, 'rt', encoding='utf-8') as f:
        return_data = json.load(f)
    
    return_df = pd.DataFrame(return_data['data'])
    print(f"  - 收益数据: {len(return_df)} 行, {return_df['asset'].nunique()} 只股票")
    
    # 选择必要的列（KDJ_J 需要 close, high, low）
    required_cols = ['date', 'asset', 'close', 'high', 'low']
    factor_df = factor_df[required_cols].copy()
    
    # 在 dropna 之前，计算原始数据范围（遵循 PROJECT.md 输出字段语义规范）
    raw_period_start = str(factor_df['date'].min())
    raw_period_end = str(factor_df['date'].max())
    raw_total_days = factor_df['date'].nunique()
    
    print(f"  - 原始数据范围: {raw_period_start} ~ {raw_period_end}, {raw_total_days} 个交易日")
    
    # 过滤缺失值
    factor_df = factor_df.dropna(subset=['close', 'high', 'low']).reset_index(drop=True)
    
    # 重命名收益列
    if 'forward_return_1d' in return_df.columns:
        return_df = return_df[['date', 'asset', 'forward_return_1d']].copy()
        return_df = return_df.rename(columns={'forward_return_1d': 'forward_return'})
    else:
        raise KeyError("收益列 'forward_return_1d' 不存在于缓存数据中")
    
    return_df = return_df.dropna(subset=['forward_return']).reset_index(drop=True)
    
    print(f"  - 过滤缺失值后: 因子 {len(factor_df)} 行, 收益 {len(return_df)} 行")
    
    # 计算 KDJ_J 因子
    print("\n[因子计算] 计算 KDJ_J...")
    factor_df, factor_stats = calculate_kdj_j_factor(factor_df, n=n, m1=m1, m2=m2)
    
    # 选择输出列
    factor_df = factor_df[['date', 'asset', 'kdj_j']].copy()
    
    # 返回过滤后的数据 + 原始数据元信息
    return factor_df, return_df, {
        'period_start': raw_period_start,
        'period_end': raw_period_end,
        'total_days': raw_total_days
    }


def calculate_daily_ic_series(
    factor_df: pd.DataFrame,
    return_df: pd.DataFrame,
    period_start: str = None,
    period_end: str = None
) -> dict:
    """
    计算每日的 IC 时间序列
    
    参数:
        factor_df: 因子数据
        return_df: 收益数据
        period_start: 数据起始日期
        period_end: 数据结束日期
    
    返回:
        dict: IC 计算结果（符合 PROJECT.md 五维度判断规范）
    """
    # 使用 IC 计算（支持因子方向验证）
    result = calculate_ic_with_direction_verification(
        factor_df=factor_df,
        return_df=return_df,
        factor_col='kdj_j',
        return_col='forward_return',
        date_col='date',
        asset_col='asset',
        min_stocks=10
    )
    
    ic_series = result['ic_series']
    
    # 获取日期范围
    if period_start is None:
        period_start = str(factor_df['date'].min())
    if period_end is None:
        period_end = str(factor_df['date'].max())
    
    # 转换为 JSON 友好格式
    dates = [str(d) for d in ic_series.index]
    ic_values = [round(v, 6) for v in ic_series.values]
    
    # 计算 20 日滚动均值
    # 计算 20 日滚动均值（min_periods=10，至少需要10个有效值）
    rolling_mean = ic_series.rolling(window=20, min_periods=10).mean()
    rolling_ic_mean = [round(v, 6) for v in rolling_mean.values]
    
    # 符合 PROJECT.md 规范的数据结构（五维度判断）
    return {
        'factor_name': 'kdj_j_1d',
        'calculation_date': datetime.now().strftime('%Y-%m-%d'),
        'period': {
            'start': period_start,
            'end': period_end
        },
        'ic_metrics': {
            'ic_mean': round(result['ic_mean'], 6),
            'ic_std': round(result['ic_std'], 6),
            'icir': round(result['icir'], 4),
            'p_value': round(result['p_value'], 6),
            'p_value_display': result.get('p_value_display', str(round(result['p_value'], 6)))
        },
        'statistical_significance': {
            'is_significant': result['statistical_significance']['is_significant'],
            'p_value': result['statistical_significance']['p_value'],
            'p_value_display': result['statistical_significance']['p_value_display'],
            't_stat': result['statistical_significance']['t_stat'],
            'conclusion': result['statistical_significance']['conclusion']
        },
        'factor_direction': {
            'direction': result['factor_direction']['ic_mean_sign'],
            'ic_mean': result['factor_direction']['ic_mean'],
            'conclusion': result['factor_direction']['conclusion']
        },
        'economic_significance': {
            'ic_strength': result['economic_significance']['level'],
            'ic_mean_abs': result['economic_significance']['abs_ic_mean'],
            'conclusion': result['economic_significance']['conclusion']
        },
        'sample_stats': {
            'total_days': len(dates),
            'valid_days': len(dates),
            'avg_stocks_per_day': int(factor_df.groupby('date').size().mean())
        },
        'dates': dates,
        'ic_values': ic_values,
        'rolling_ic_mean': rolling_ic_mean,
        'positive_ratio': round(result['positive_ratio'], 4),
        'n_assets': factor_df['asset'].nunique(),
        'summary': result['summary']
    }


def generate_kdj_j_ic_data(
    output_file: str = None,
    force_full: bool = False,
    n: int = 9,
    m1: int = 3,
    m2: int = 3
) -> dict:
    """
    从缓存数据计算 KDJ_J IC
    
    参数:
        output_file: 输出文件路径
        force_full: 强制全量计算
        n: RSV 计算周期
        m1: K值平滑周期
        m2: D值平滑周期
    
    返回:
        IC 数据字典
    
    规范:
        使用缓存全部日期数据，不截断
    """
    if output_file is None:
        output_file = get_ic_output_path('kdj_j_1d')
    
    # 增量判断（除非强制全量）
    if not force_full:
        mode, missing_dates, info = check_data_completeness('kdj_j_1d')
        
        if mode == 'skip':
            print("\n数据完备，无需更新")
            try:
                with open(output_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception as e:
                print(f"读取缓存失败: {e}，将执行全量计算")
                # 显式 fallthrough 到全量计算（遵循 PROJECT.md 增量模式异常处理规范）
                pass  # except 块结束，代码继续向下执行全量计算
    
    # 全量计算逻辑
    print("=" * 60)
    print(f"KDJ_J_1D IC 计算器（缓存版） - 1日收益周期")
    print(f"参数: N={n}, M1={m1}, M2={m2}")
    print("=" * 60)
    
    # 从缓存加载数据并计算因子
    print("\n[1/3] 从缓存加载因子和收益数据...")
    try:
        factor_df, return_df, raw_metadata = load_data_from_cache(n=n, m1=m1, m2=m2)
        
        # 检查数据量
        if factor_df['asset'].nunique() < 10:
            raise ValueError(
                f"股票数量不足以计算有效的 IC\n"
                f"当前: {factor_df['asset'].nunique()} < 10"
            )
            
    except Exception as e:
        raise RuntimeError(f"数据加载失败: {e}")
    
    # 使用缓存全部日期（不截断）
    
    print(f"\n数据统计:")
    print(f"  - 原始日期范围: {raw_metadata['period_start']} ~ {raw_metadata['period_end']}")
    print(f"  - 原始交易日数: {raw_metadata['total_days']}")
    print(f"  - 过滤后交易日数: {factor_df['date'].nunique()}")
    print(f"  - 股票数量: {factor_df['asset'].nunique()}")
    
    # 计算 IC
    print("\n[2/3] 计算每日 IC...")
    ic_data = calculate_daily_ic_series(factor_df, return_df)
    print(f"  - IC 均值: {ic_data['ic_metrics']['ic_mean']:.4f}")
    print(f"  - ICIR: {ic_data['ic_metrics']['icir']:.2f}")
    print(f"  - 正比例: {ic_data['positive_ratio']:.1%}")
    print(f"  - t 统计量: {ic_data['t_stat']:.2f} {ic_data['significance']}")
    
    # 保存数据
    print(f"\n[3/3] 保存数据到: {output_file}")
    output_file.parent.mkdir(parents=True, exist_ok=True)
    
    # 转换 numpy 类型
    ic_data = convert_to_native_types(ic_data)
    
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(ic_data, f, ensure_ascii=False, indent=2)
    
    print("\n" + "=" * 60)
    print(f"完成！共计算 {ic_data['sample_stats']['total_days']} 天 IC 数据")
    print("=" * 60)
    
    return ic_data


if __name__ == '__main__':
    # 计算缓存全部日期的 IC 数据
    generate_kdj_j_ic_data(n=9, m1=3, m2=3)