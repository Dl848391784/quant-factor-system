#!/usr/bin/env python3.10
"""
主力净流入占比因子计算模块（内存优化版）

因子定义：
- 主力净流入占比 = 主力净流入 / 流通市值
- 主力净流入 = 大单净流入 + 特大单净流入（东方财富定义）
- 流通市值 = 当前价格 × 流通股本

因子逻辑：
- 正值：主力资金净流入，表示资金看好，预期上涨
- 负值：主力资金净流出，表示资金看空，预期下跌
- 绝对值大小：流入/流出强度

内存优化策略：
1. 使用轻量级数据加载
2. 使用 category 类型优化内存
3. 分批处理大数据
4. 及时释放中间变量（gc.collect）
5. 参考 turnover_surge_factor.py 的实现

数据来源：
- 东方财富 API（main_inflow_data_fetcher.py 已实现）
- 或从历史缓存文件加载

作者: 云舟
日期: 2026-04-06
"""

import pandas as pd
import numpy as np
from pathlib import Path
import gzip
import json
import gc
from typing import Tuple, Optional, Dict, List
import warnings
warnings.filterwarnings('ignore')


def convert_to_native_types(obj):
    """
    递归转换 numpy 类型为 Python 原生类型
    解决 JSON 序列化问题
    """
    if isinstance(obj, dict):
        return {k: convert_to_native_types(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [convert_to_native_types(v) for v in obj]
    elif isinstance(obj, (np.integer, np.int64, np.int32)):
        return int(obj)
    elif isinstance(obj, (np.floating, np.float64, np.float32)):
        return float(obj)
    elif isinstance(obj, np.ndarray):
        return obj.tolist()
    elif isinstance(obj, pd.Series):
        return obj.tolist()
    elif pd.isna(obj):
        return None
    else:
        return obj


# ============================================================
# 配置常量
# ============================================================

BASE_DIR = Path(__file__).parent
CACHE_DIR = BASE_DIR / 'cache' / 'factor_data'
MAIN_INFLOW_CACHE_DIR = BASE_DIR / 'cache' / 'main_inflow'

# 历史缓存文件
HISTORY_FILE = MAIN_INFLOW_CACHE_DIR / 'main_inflow_history.json.gz'


# ============================================================
# 数据加载函数
# ============================================================

def load_main_inflow_history(
    max_days: int = 500,
    use_category: bool = True
) -> Tuple[Optional[pd.DataFrame], Optional[pd.DataFrame]]:
    """
    加载主力净流入历史数据（内存优化版）
    
    从缓存文件加载：
    - 主力净流入（main_net_inflow）
    - 流通市值（float_market_cap）
    - 计算主力净流入占比（main_inflow_ratio）
    
    同时加载对应的收益数据用于 IC 计算
    
    Args:
        max_days: 最大加载天数（默认 500）
        use_category: 是否使用 category 类型（默认 True）
        
    Returns:
        (factor_df, return_df) 或 (None, None)
    """
    print(f"\n{'='*60}")
    print("[主力净流入占比] 加载数据（内存优化模式）")
    print(f"{'='*60}")
    
    # ========== Step 1: 加载主力净流入历史数据 ==========
    if not HISTORY_FILE.exists():
        print(f"  ✗ 历史缓存文件不存在: {HISTORY_FILE}")
        print(f"  请先运行: python precompute_main_inflow.py")
        return None, None
    
    print(f"[Step 1] 加载主力净流入历史数据...")
    
    try:
        with gzip.open(HISTORY_FILE, 'rt', encoding='utf-8') as f:
            inflow_data = json.load(f)
    except Exception as e:
        print(f"  ✗ 加载失败: {e}")
        return None, None
    
    # 提取元数据
    meta = inflow_data.get('meta', {})
    all_dates = meta.get('dates', [])
    if not all_dates:
        all_dates = sorted(set(r.get('date') for r in inflow_data.get('data', [])))
    
    print(f"  缓存包含 {len(all_dates)} 天数据")
    
    # 只保留最近 max_days 天
    if len(all_dates) > max_days:
        recent_dates = set(all_dates[-max_days:])
        print(f"  只加载最近 {max_days} 天")
        records = [
            r for r in inflow_data.get('data', []) 
            if r.get('date') in recent_dates
        ]
    else:
        records = inflow_data.get('data', [])
    
    del inflow_data
    gc.collect()
    
    # 构建 DataFrame
    factor_df = pd.DataFrame(records)
    del records
    gc.collect()
    
    if factor_df.empty:
        print("  ✗ 数据为空")
        return None, None
    
    # 使用 category 类型优化内存
    if use_category:
        factor_df['date'] = factor_df['date'].astype('category')
        factor_df['asset'] = factor_df['asset'].astype('category')
    
    # 转换数值列
    numeric_cols = ['main_net_inflow', 'float_market_cap', 'main_inflow_ratio',
                    'super_net_inflow', 'big_net_inflow', 'medium_net_inflow', 'small_net_inflow']
    for col in numeric_cols:
        if col in factor_df.columns:
            factor_df[col] = pd.to_numeric(factor_df[col], errors='coerce')
    
    # 如果 main_inflow_ratio 不存在，计算它
    if 'main_inflow_ratio' not in factor_df.columns or factor_df['main_inflow_ratio'].isna().all():
        print("  计算 main_inflow_ratio...")
        mask = (factor_df['float_market_cap'] > 0) & (factor_df['main_net_inflow'].notna())
        factor_df.loc[mask, 'main_inflow_ratio'] = (
            factor_df.loc[mask, 'main_net_inflow'] / factor_df.loc[mask, 'float_market_cap']
        )
    
    factor_mem = factor_df.memory_usage(deep=True).sum() / 1024 / 1024
    print(f"  factor_df: {len(factor_df)} 行, {factor_mem:.2f} MB")
    
    # ========== Step 2: 加载收益数据 ==========
    print(f"[Step 2] 加载收益数据...")
    
    return_path = CACHE_DIR / 'return_data.json.gz'
    
    if not return_path.exists():
        print(f"  ✗ 收益数据文件不存在: {return_path}")
        return None, None
    
    try:
        with gzip.open(return_path, 'rt', encoding='utf-8') as f:
            return_data = json.load(f)
        
        # 获取因子数据的日期集合
        factor_dates = set(str(d) for d in factor_df['date'].unique())
        
        return_records = [
            {
                'date': r['date'], 
                'asset': r['asset'], 
                'forward_return_1d': r.get('forward_return_1d')
            }
            for r in return_data.get('data', [])
            if r.get('date') in factor_dates
        ]
        
        del return_data
        gc.collect()
        
        return_df = pd.DataFrame(return_records)
        del return_records
        gc.collect()
        
        if use_category:
            return_df['date'] = return_df['date'].astype('category')
            return_df['asset'] = return_df['asset'].astype('category')
        
        return_df['forward_return_1d'] = pd.to_numeric(return_df['forward_return_1d'], errors='coerce')
        
        # 兼容性映射
        if 'forward_return_1d' in return_df.columns and 'forward_return' not in return_df.columns:
            return_df['forward_return'] = return_df['forward_return_1d']
        
        return_mem = return_df.memory_usage(deep=True).sum() / 1024 / 1024
        print(f"  return_df: {len(return_df)} 行, {return_mem:.2f} MB")
        print(f"  总内存占用: {factor_mem + return_mem:.2f} MB")
        
        return factor_df, return_df
        
    except Exception as e:
        print(f"  ✗ 加载收益数据失败: {e}")
        return None, None


def calculate_main_inflow_ratio_factor(
    factor_df: pd.DataFrame,
    winsorize: bool = True
) -> Tuple[pd.DataFrame, Dict]:
    """
    计算主力净流入占比因子
    
    因子定义：
    - 主力净流入占比 = main_net_inflow / float_market_cap
    
    处理极端值：
    - 流通市值为 0 的情况：排除
    - 主力净流入为 NaN：排除
    - 极端值裁剪：[-0.5, 0.5]（即 ±50%）
    
    Args:
        factor_df: 包含主力净流入和流通市值的数据
        winsorize: 是否进行极端值裁剪（默认 True）
        
    Returns:
        (处理后的 factor_df, 统计信息)
    """
    print(f"\n{'='*60}")
    print("[因子计算] 主力净流入占比因子")
    print(f"{'='*60}")
    
    stats = {
        'total_records': len(factor_df),
        'valid_records': 0,
        'zero_cap_count': 0,
        'missing_inflow_count': 0,
        'winsorized_count': 0
    }
    
    if factor_df.empty:
        print("  ✗ 数据为空")
        return factor_df, stats
    
    # 检查必要列
    required_cols = ['main_net_inflow', 'float_market_cap']
    missing_cols = [c for c in required_cols if c not in factor_df.columns]
    if missing_cols:
        print(f"  ✗ 缺少必要列: {missing_cols}")
        return factor_df, stats
    
    # 计算主力净流入占比（如果不存在）
    if 'main_inflow_ratio' not in factor_df.columns:
        factor_df['main_inflow_ratio'] = np.nan
    
    # 统计无效数据
    zero_cap_mask = factor_df['float_market_cap'] <= 0
    missing_inflow_mask = factor_df['main_net_inflow'].isna()
    
    stats['zero_cap_count'] = zero_cap_mask.sum()
    stats['missing_inflow_count'] = missing_inflow_mask.sum()
    
    # 计算因子值
    valid_mask = ~zero_cap_mask & ~missing_inflow_mask
    factor_df.loc[valid_mask, 'main_inflow_ratio'] = (
        factor_df.loc[valid_mask, 'main_net_inflow'] / 
        factor_df.loc[valid_mask, 'float_market_cap']
    )
    
    stats['valid_records'] = valid_mask.sum()
    
    # 极端值裁剪
    if winsorize:
        # 裁剪范围：[-0.5, 0.5]（即 ±50%）
        # 主力净流入占流通市值比例一般不会超过这个范围
        lower_bound = -0.5
        upper_bound = 0.5
        
        # 统计被裁剪的数量
        winsorize_mask = (
            (factor_df['main_inflow_ratio'].notna()) & 
            ((factor_df['main_inflow_ratio'] < lower_bound) | 
             (factor_df['main_inflow_ratio'] > upper_bound))
        )
        stats['winsorized_count'] = winsorize_mask.sum()
        
        # 执行裁剪
        factor_df['main_inflow_ratio'] = factor_df['main_inflow_ratio'].clip(lower_bound, upper_bound)
        
        print(f"  极端值裁剪: [{lower_bound}, {upper_bound}]")
        print(f"  裁剪记录数: {stats['winsorized_count']}")
    
    # 输出统计
    print(f"\n  总记录数:         {stats['total_records']:,}")
    print(f"  有效记录数:       {stats['valid_records']:,}")
    print(f"  流通市值为0:      {stats['zero_cap_count']:,}")
    print(f"  主力净流入缺失:   {stats['missing_inflow_count']:,}")
    
    # 输出因子统计
    valid_values = factor_df['main_inflow_ratio'].dropna()
    if len(valid_values) > 0:
        print(f"\n  因子统计:")
        print(f"    均值:   {valid_values.mean():.6f}")
        print(f"    标准差: {valid_values.std():.6f}")
        print(f"    最小值: {valid_values.min():.6f}")
        print(f"    最大值: {valid_values.max():.6f}")
        print(f"    中位数: {valid_values.median():.6f}")
    
    # 转换统计中的 numpy 类型
    stats = convert_to_native_types(stats)
    
    return factor_df, stats


def calculate_main_inflow_ratio_ic(
    factor_df: pd.DataFrame,
    return_df: pd.DataFrame,
    factor_col: str = 'main_inflow_ratio',
    return_col: str = 'forward_return'
) -> Dict:
    """
    计算主力净流入占比因子的 Rank IC
    
    注意：主力净流入占比是正向因子
    - 正值表示主力资金流入，预期上涨
    - 负值表示主力资金流出，预期下跌
    - 因此使用正向排名（不反向）
    
    Args:
        factor_df: 包含 date, asset, main_inflow_ratio 的 DataFrame
        return_df: 包含 date, asset, forward_return 的 DataFrame
        factor_col: 因子列名
        return_col: 收益列名
        
    Returns:
        IC 计算结果字典
    """
    print(f"\n{'='*60}")
    print("[IC计算] 主力净流入占比因子 Rank IC")
    print(f"{'='*60}")
    
    # 准备数据
    factor_cols = ['date', 'asset', factor_col]
    return_cols = ['date', 'asset', return_col]
    
    factor_data = factor_df[factor_cols].dropna(subset=[factor_col]).copy()
    return_data = return_df[return_cols].copy()
    
    # 统一 date 列类型
    if factor_data['date'].dtype.name == 'category':
        factor_data['date'] = factor_data['date'].astype('datetime64[ns]')
    if return_data['date'].dtype.name == 'category':
        return_data['date'] = return_data['date'].astype('datetime64[ns]')
    
    merged = pd.merge(
        factor_data,
        return_data,
        on=['date', 'asset'],
        how='inner'
    )
    
    del factor_data, return_data
    gc.collect()
    
    print(f"  合并后记录数: {len(merged):,}")
    
    if merged.empty:
        print("  ✗ 合并后数据为空")
        return {
            'ic_series': None,
            'ic_mean': 0,
            'ic_std': 0,
            'icir': 0,
            't_stat': 0,
            'p_value': 1,
            'positive_ratio': 0,
            'n_days': 0,
            'n_assets': 0,
            'summary': '数据不足，无法计算IC'
        }
    
    # 计算 IC（使用正向排名，因为主力净流入占比是正向因子）
    try:
        ic_results = []
        
        if merged['date'].dtype.name == 'category':
            merged['date'] = merged['date'].astype(str)
        
        for date, group in merged.groupby('date'):
            if len(group) < 10:
                continue
            
            if group[factor_col].nunique() == 1 or group[return_col].nunique() == 1:
                continue
            
            # 正向排名：因子值越高排名越高
            factor_rank = group[factor_col].rank(pct=True, ascending=True, method='average')
            return_rank = group[return_col].rank(pct=True, ascending=True, method='average')
            
            ic_value = factor_rank.corr(return_rank, method='spearman')
            
            if pd.notna(ic_value):
                ic_results.append({'date': date, 'ic': ic_value})
        
        if not ic_results:
            print("  ✗ 无法计算 IC")
            return {
                'ic_series': None,
                'ic_mean': 0,
                'ic_std': 0,
                'icir': 0,
                't_stat': 0,
                'p_value': 1,
                'positive_ratio': 0,
                'n_days': 0,
                'n_assets': merged['asset'].nunique(),
                'summary': '无法计算IC'
            }
        
        ic_df = pd.DataFrame(ic_results)
        ic_series = ic_df.set_index('date')['ic']
        
        # 计算统计量
        ic_mean = ic_series.mean()
        ic_std = ic_series.std()
        icir = ic_mean / ic_std if ic_std > 0 else 0
        positive_ratio = (ic_series > 0).mean()
        
        # t 统计量
        import math
        n = len(ic_series)
        t_stat = ic_mean / (ic_std / math.sqrt(n)) if ic_std > 0 else 0
        
        # p 值
        from scipy import stats
        p_value = 2 * (1 - stats.t.cdf(abs(t_stat), df=n-1)) if n > 1 else 1
        
        # 显著性标注
        abs_t = abs(t_stat)
        if abs_t > 3.29:
            significance = '***'
        elif abs_t > 2.58:
            significance = '**'
        elif abs_t > 1.96:
            significance = '*'
        else:
            significance = ''
        
        # 生成摘要
        if ic_mean > 0.03:
            effectiveness = "因子有效"
        elif ic_mean < -0.03:
            effectiveness = "因子反向有效"
        else:
            effectiveness = "因子预测能力较弱"
        
        summary = f"IC均值={ic_mean:.4f}, ICIR={icir:.2f}, 正比例={positive_ratio:.1%}, {effectiveness}"
        
        print(f"  IC 均值: {ic_mean:.4f}")
        print(f"  IC 标准差: {ic_std:.4f}")
        print(f"  ICIR: {icir:.2f}")
        print(f"  t 统计量: {t_stat:.4f}{significance}")
        print(f"  正 IC 比例: {positive_ratio:.1%}")
        
        return {
            'ic_series': ic_series,
            'ic_mean': ic_mean,
            'ic_std': ic_std,
            'icir': icir,
            't_stat': round(t_stat, 4),
            'p_value': round(p_value, 6),
            'positive_ratio': positive_ratio,
            'n_days': n,
            'n_assets': merged['asset'].nunique(),
            'significance': significance,
            'summary': summary
        }
        
    except Exception as e:
        print(f"  ✗ IC 计算失败: {e}")
        import traceback
        traceback.print_exc()
        return {
            'ic_series': None,
            'ic_mean': 0,
            'ic_std': 0,
            'icir': 0,
            't_stat': 0,
            'p_value': 1,
            'positive_ratio': 0,
            'n_days': 0,
            'n_assets': 0,
            'summary': f'IC计算失败: {str(e)}'
        }


def run_main_inflow_ratio_analysis(
    n_days: int = 500,
    num_layers: int = 10,
    winsorize: bool = True
) -> Dict:
    """
    执行完整的主力净流入占比因子分析
    
    步骤：
    1. 加载数据（内存优化）
    2. 计算因子
    3. 计算 IC
    4. 执行分层回测
    5. 返回完整结果
    
    Args:
        n_days: 交易日数量
        num_layers: 分层数量（默认10层）
        winsorize: 是否进行极端值裁剪
        
    Returns:
        完整分析结果字典
    """
    from datetime import datetime
    from layered_backtest import LayeredBacktest
    
    print(f"\n{'='*80}")
    print("主力净流入占比因子分析（内存优化版）")
    print(f"{'='*80}")
    print(f"  开始时间: {datetime.now().isoformat()}")
    
    # 内存监控
    try:
        import psutil
        process = psutil.Process()
        initial_mem = process.memory_info().rss / 1024 / 1024
        print(f"  初始内存: {initial_mem:.2f} MB")
        has_psutil = True
    except ImportError:
        has_psutil = False
    
    # ========== Step 1: 加载数据 ==========
    factor_df, return_df = load_main_inflow_history(max_days=n_days)
    
    if factor_df is None or return_df is None:
        return {
            'success': False,
            'error': '数据加载失败，请先运行 precompute_main_inflow.py'
        }
    
    if has_psutil:
        current_mem = process.memory_info().rss / 1024 / 1024
        print(f"  数据加载后内存: {current_mem:.2f} MB")
    
    # ========== Step 2: 计算因子 ==========
    factor_df, factor_stats = calculate_main_inflow_ratio_factor(factor_df, winsorize=winsorize)
    
    if has_psutil:
        current_mem = process.memory_info().rss / 1024 / 1024
        print(f"  因子计算后内存: {current_mem:.2f} MB")
    
    # ========== Step 3: 计算 IC ==========
    ic_result = calculate_main_inflow_ratio_ic(factor_df, return_df)
    
    if has_psutil:
        current_mem = process.memory_info().rss / 1024 / 1024
        print(f"  IC计算后内存: {current_mem:.2f} MB")
    
    # ========== Step 4: 分层回测 ==========
    print(f"\n[分层回测] 开始执行...")
    
    # 准备分层回测数据
    backtest_factor_df = factor_df[['date', 'asset', 'main_inflow_ratio']].copy()
    backtest_return_df = return_df[['date', 'asset', 'forward_return']].copy()
    
    # 释放原始数据
    del factor_df, return_df
    gc.collect()
    
    # 执行分层回测
    try:
        backtest = LayeredBacktest(num_layers=num_layers)
        layered_result = backtest.run(
            backtest_factor_df, 
            backtest_return_df, 
            factor_col='main_inflow_ratio',
            return_col='forward_return'
        )
    except Exception as e:
        print(f"  ✗ 分层回测失败: {e}")
        import traceback
        traceback.print_exc()
        layered_result = None
    
    if has_psutil:
        current_mem = process.memory_info().rss / 1024 / 1024
        print(f"  分层回测后内存: {current_mem:.2f} MB")
    
    # ========== Step 5: 构建结果 ==========
    print(f"\n[构建结果] 整理分析结果...")
    
    # IC 指标
    ic_metrics = {
        'ic_mean': ic_result.get('ic_mean', 0),
        'ic_std': ic_result.get('ic_std', 0),
        'icir': ic_result.get('icir', 0),
        't_stat': ic_result.get('t_stat', 0),
        'p_value': ic_result.get('p_value', 1),
        'positive_ratio': ic_result.get('positive_ratio', 0),
        'n_days': ic_result.get('n_days', 0),
        'n_assets': ic_result.get('n_assets', 0),
        'significance': ic_result.get('significance', ''),
        'summary': ic_result.get('summary', '')
    }
    
    # IC 时间序列
    ic_series = ic_result.get('ic_series')
    if ic_series is not None:
        rolling_mean = ic_series.rolling(window=20, min_periods=1).mean()
        ic_series_data = {
            'dates': [str(d) for d in ic_series.index],
            'ic_values': [round(v, 6) for v in ic_series.values],
            'rolling_ic_mean': [round(v, 6) for v in rolling_mean.values]
        }
    else:
        ic_series_data = {
            'dates': [],
            'ic_values': [],
            'rolling_ic_mean': []
        }
    
    # 分层回测结果
    if layered_result is not None:
        # 转换函数
        def convert_df_dates(df_dict):
            converted = []
            for row in df_dict:
                new_row = {}
                for k, v in row.items():
                    if k in ('date', 'trade_date'):
                        if hasattr(v, 'strftime'):
                            new_row[k] = v.strftime('%Y-%m-%d')
                        else:
                            new_row[k] = str(v)
                    else:
                        new_row[k] = v
                converted.append(new_row)
            return converted
        
        # 最大回撤
        def calculate_max_drawdown(nav_series):
            peak = nav_series.expanding(min_periods=1).max()
            drawdown = (nav_series / peak) - 1
            return round(drawdown.min(), 4)
        
        # 单调性检验（主力净流入占比是正向因子：预期 Layer 1 收益低，Layer N 收益高）
        def calculate_monotonicity(statistics_df):
            layer_returns = []
            for i in range(1, num_layers + 1):
                layer_key = f'layer_{i}'
                if layer_key in statistics_df.index:
                    layer_returns.append(statistics_df.loc[layer_key, 'annual_return'])
            
            # 正向因子预期收益递增
            for i in range(len(layer_returns) - 1):
                if layer_returns[i] > layer_returns[i + 1]:
                    return False
            return True
        
        # 提取多空统计信息（带异常处理，防止分层回测数据不足）
        try:
            if 'long_short' in layered_result.statistics.index:
                long_short_stats = layered_result.statistics.loc['long_short']
                summary = {
                    'long_short_annual_return': round(float(long_short_stats['annual_return']), 4),
                    'long_short_sharpe': round(float(long_short_stats['sharpe']), 4),
                    'long_short_max_drawdown': calculate_max_drawdown(layered_result.long_short['cumulative_nav']),
                    'monotonicity_passed': calculate_monotonicity(layered_result.statistics)
                }
                long_short_data = convert_df_dates(layered_result.long_short.reset_index().to_dict(orient='records'))
            else:
                print("  ⚠️ 分层回测未生成 long_short 数据（数据不足）")
                summary = {
                    'long_short_annual_return': 0,
                    'long_short_sharpe': 0,
                    'long_short_max_drawdown': 0,
                    'monotonicity_passed': False
                }
                long_short_data = []
        except Exception as e:
            print(f"  ✗ 提取多空统计失败: {e}")
            summary = {
                'long_short_annual_return': 0,
                'long_short_sharpe': 0,
                'long_short_max_drawdown': 0,
                'monotonicity_passed': False
            }
            long_short_data = []
        
        layered_result_json = {
            'layer_returns': convert_df_dates(layered_result.layer_returns.reset_index().to_dict(orient='records')),
            'cumulative_returns': convert_df_dates(layered_result.cumulative_returns.reset_index().to_dict(orient='records')),
            'statistics': layered_result.statistics.reset_index().to_dict(orient='records'),
            'long_short': long_short_data,
            'num_layers': num_layers,
            'n_days': len(layered_result.layer_returns),
            'n_stocks': ic_metrics['n_assets'],
            'summary': summary
        }
    else:
        layered_result_json = {
            'layer_returns': [],
            'cumulative_returns': [],
            'statistics': [],
            'long_short': [],
            'num_layers': num_layers,
            'n_days': 0,
            'n_stocks': 0,
            'summary': {
                'long_short_annual_return': 0,
                'long_short_sharpe': 0,
                'long_short_max_drawdown': 0,
                'monotonicity_passed': False
            }
        }
    
    # 构建完整结果
    result = {
        'success': True,
        'ic_metrics': ic_metrics,
        'ic_series': ic_series_data,
        'layered_result': layered_result_json,
        'factor_stats': factor_stats,
        'params': {
            'n_days': n_days,
            'max_stocks': 0,
            'num_layers': num_layers,
            'factor_col': 'main_inflow_ratio',
            'winsorize': winsorize
        },
        'generated_at': datetime.now().isoformat()
    }
    
    # 转换 numpy 类型
    result = convert_to_native_types(result)
    
    if has_psutil:
        final_mem = process.memory_info().rss / 1024 / 1024
        print(f"  最终内存: {final_mem:.2f} MB (增量: {final_mem - initial_mem:.2f} MB)")
    
    print(f"  完成时间: {datetime.now().isoformat()}")
    print(f"{'='*80}")
    
    return result


if __name__ == '__main__':
    """测试主力净流入占比因子分析"""
    from datetime import datetime
    
    result = run_main_inflow_ratio_analysis(n_days=500, num_layers=10)
    
    if result.get('success'):
        print("\n测试成功！")
        print(f"IC均值: {result['ic_metrics']['ic_mean']:.4f}")
        print(f"ICIR: {result['ic_metrics']['icir']:.2f}")
        print(f"多空收益: {result['layered_result']['summary']['long_short_annual_return']:.2%}")
        
        # 保存 IC 结果到缓存文件
        ic_cache_path = Path(__file__).parent.parent / 'cache' / 'factor_ic' / 'main_inflow_ratio_ic.json'
        ic_cache_path.parent.mkdir(parents=True, exist_ok=True)
        
        ic_data = {
            'factor_name': 'main_inflow_ratio',
            'ic_mean': result['ic_metrics']['ic_mean'],
            'icir': result['ic_metrics']['icir'],
            'dates': result['ic_series']['dates'],
            'ic_values': result['ic_series']['ic_values'],
            'calculated_at': datetime.now().isoformat()
        }
        
        with open(ic_cache_path, 'w', encoding='utf-8') as f:
            json.dump(ic_data, f, ensure_ascii=False, indent=2)
        
        print(f"\nIC数据已保存到: {ic_cache_path}")
    else:
        print(f"\n测试失败: {result.get('error')}")