#!/usr/bin/env python3
"""
量比因子 IC 计算器（缓存版） - 1日收益周期

从缓存数据计算量比因子的正向排名 Rank IC。
不再实时拉取数据，直接读取 cache/factor_data/ 下的缓存。

新增功能：分层回测（正向因子逻辑）
- 使用 LayeredBacktestEngine 类
- 10层等频分层
- 正向因子分层：低量比→Layer1，高量比→Layer10
- 多空组合：Layer 10 - Layer 1

作者: 云舟
日期: 2026-05-08
修订: 2026-05-09（添加分层回测功能）
"""

import sys
import traceback
from pathlib import Path

# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent.parent))

import pandas as pd
import numpy as np
import gzip
import json
from typing import Tuple, Dict
from scipy.stats import spearmanr, norm as scipy_stats_norm
from datetime import datetime

# scipy.stats.norm.cdf 辅助函数
scipy_stats_norm_cdf = scipy_stats_norm.cdf

# 导入数据完整性检查模块
from factor_ic.common.data_completeness import get_ic_output_path

# 导入类型转换模块
from factor_ic.common.convert_types import convert_to_native_types

# 导入分层回测引擎
from backtest.layered_backtest import LayeredBacktestEngine

# 默认常量（遵循 MODULE.md 代码质量规范）
DEFAULT_MIN_STOCKS = 10  # 每日最少股票数阈值（用于IC计算和分层回测）

# 缓存路径
CACHE_DIR = Path(__file__).parent.parent / 'cache' / 'factor_data'
FACTOR_CACHE = CACHE_DIR / 'factor_data.json.gz'
RETURN_CACHE = CACHE_DIR / 'return_data.json.gz'
OUTPUT_FILE = get_ic_output_path('volume_ratio_1d')


def load_data_from_cache(
    factor_col: str = 'volume_ratio_5',
    return_col: str = 'forward_return_1d'
) -> Tuple[pd.DataFrame, pd.DataFrame, dict]:
    """
    从缓存加载因子数据和收益数据
    
    参数:
        factor_col: 因子列名
        return_col: 收益列名
        
    返回:
        (factor_df, return_df, raw_metadata)
        - factor_df: 过滤后的因子数据 DataFrame
        - return_df: 过滤后的收益数据 DataFrame
        - raw_metadata: 原始数据元信息字典
            - period_start: 原始缓存最小日期
            - period_end: 原始缓存最大日期
            - total_days: 原始缓存日期数
    
    规范:
        加载缓存全部日期数据，不截断
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
    
    # 选择需要的列
    factor_df = factor_df[['date', 'asset', factor_col]].copy()
    
    # 重命名收益列（统一为 forward_return）
    if return_col in return_df.columns:
        return_df = return_df[['date', 'asset', return_col]].copy()
        return_df = return_df.rename(columns={return_col: 'forward_return'})
    else:
        raise KeyError(f"收益列 '{return_col}' 不存在于缓存数据中")
    
    # 在 dropna 之前，计算原始数据范围（遵循 PROJECT.md 输出字段语义规范）
    # period 和 total_days 应基于原始缓存数据，而非过滤后的数据
    # 原因：dropna 可能过滤掉某些日期的全部股票（如停牌、数据缺失）
    raw_period_start = str(factor_df['date'].min())
    raw_period_end = str(factor_df['date'].max())
    raw_total_days = factor_df['date'].nunique()
    
    print(f"  - 原始数据范围: {raw_period_start} ~ {raw_period_end}, {raw_total_days} 个交易日")
    
    # 过滤缺失值
    factor_df = factor_df.dropna(subset=[factor_col]).reset_index(drop=True)
    return_df = return_df.dropna(subset=['forward_return']).reset_index(drop=True)
    
    print(f"  - 过滤缺失值后: 因子 {len(factor_df)} 行, 收益 {len(return_df)} 行")
    
    # 验证日期对齐（遵循 MODULE.md 数据对齐验证规范）
    factor_dates = set(factor_df['date'].unique())
    return_dates = set(return_df['date'].unique())
    
    if factor_dates != return_dates:
        missing_in_return = factor_dates - return_dates
        missing_in_factor = return_dates - factor_dates
        
        print(f"  [警告] 因子数据和收益数据日期不对齐")
        print(f"    因子数据日期数: {len(factor_dates)}")
        print(f"    收益数据日期数: {len(return_dates)}")
        print(f"    因子数据缺失日期数: {len(missing_in_factor)}")
        print(f"    收益数据缺失日期数: {len(missing_in_return)}")
        
        # 选择交集日期（保证数据对齐）
        common_dates = factor_dates & return_dates
        factor_df = factor_df[factor_df['date'].isin(common_dates)]
        return_df = return_df[return_df['date'].isin(common_dates)]
        print(f"    对齐后日期数: {len(common_dates)}")
    
    # 使用缓存全部日期（不截断）
    
    # 返回过滤后的数据 + 原始数据元信息（遵循 PROJECT.md 输出字段语义规范）
    return factor_df, return_df, {
        'period_start': raw_period_start,
        'period_end': raw_period_end,
        'total_days': raw_total_days
    }


def calculate_daily_ic_series(
    factor_df: pd.DataFrame,
    return_df: pd.DataFrame,
    min_stocks: int = DEFAULT_MIN_STOCKS
) -> dict:
    """
    计算每日的 IC 时间序列（量比是正向因子）
    
    参数:
        factor_df: 因子数据
        return_df: 收益数据
        min_stocks: 每日最少股票数阈值（遵循 MODULE.md 代码质量规范）
        
    返回:
        dict: IC 计算结果
    """
    print(f"\n[计算 IC] 开始计算（正向排名，min_stocks={min_stocks}）...")
    
    # 合并数据
    merged_df = pd.merge(
        factor_df[['date', 'asset', 'volume_ratio_5']],
        return_df[['date', 'asset', 'forward_return']],
        on=['date', 'asset'],
        how='inner'
    )
    
    # 确保日期是字符串类型
    merged_df['date'] = merged_df['date'].astype(str)
    
    # 按日期分组计算 Rank IC
    ic_values = []
    ic_dates = []
    
    for date, group in merged_df.groupby('date'):
        # 过滤 NaN
        valid = group.dropna(subset=['volume_ratio_5', 'forward_return'])
        
        if len(valid) < min_stocks:  # 遵循 MODULE.md 代码质量规范（使用参数而非硬编码）
            continue
        
        # 计算 Spearman Rank IC
        ic, p_value = spearmanr(valid['volume_ratio_5'], valid['forward_return'])
        
        ic_dates.append(date)
        ic_values.append(ic)
    
    ic_series = pd.Series(ic_values, index=ic_dates)
    
    # 计算 20 日滚动均值
    # 计算 20 日滚动均值（min_periods=10，至少需要10个有效值）
    rolling_mean = ic_series.rolling(window=20, min_periods=10).mean()
    
    # 计算统计指标
    ic_mean = ic_series.mean()
    ic_std = ic_series.std()
    icir = abs(ic_mean) / ic_std if ic_std != 0 else 0  # 使用绝对值（PROJECT.md 规范）
    
    # t 统计量和显著性
    n_days = len(ic_series)
    t_stat = ic_mean / ic_std * np.sqrt(n_days) if ic_std != 0 else 0
    
    # 正 IC 比例
    positive_ratio = (ic_series > 0).mean()
    
    # 摘要（遵循 MODULE.md 输出结构统一性规范，不使用星号标识）
    summary = f"IC均值={ic_mean:.4f}, ICIR={icir:.2f}, 正比例={positive_ratio:.1%}, 因子预测能力{'较弱' if abs(icir) < 0.3 else '中等' if abs(icir) < 0.5 else '较强'}"
    
    print(f"[计算 IC] 完成，IC Mean: {ic_mean:.4f}")
    
    return {
        'factor_name': 'volume_ratio_1d',
        'dates': [str(d) for d in ic_series.index],
        'ic_values': [round(v, 6) for v in ic_values],
        'rolling_ic_mean': [round(v, 6) if pd.notna(v) else None for v in rolling_mean.values],  # NaN处理（遵循MODULE.md代码质量规范）
        'ic_mean': round(ic_mean, 6),
        'ic_std': round(ic_std, 6),
        'icir': round(icir, 4),
        'positive_ratio': round(positive_ratio, 4),
        't_stat': round(t_stat, 4),
        'n_days': n_days,
        'n_assets': factor_df['asset'].nunique(),
        'summary': summary
    }


def check_positive_monotonicity(layer_stats: Dict, n_layers: int = 10) -> Dict:
    """
    检验正向因子分层单调性
    
    正向因子预期：Layer 1 收益 < Layer 2 收益 < ... < Layer N 收益
    
    Args:
        layer_stats: 各层统计指标字典（从 LayeredBacktestEngine 结果中提取）
        n_layers: 分层数量
        
    Returns:
        {
            'is_monotonic': bool,  # 是否严格单调递增
            'correlation': float,  # Layer ID 与收益的相关系数
            'quality': str,        # 单调性质量评估（good/moderate/poor）
            'layer_returns': list  # 各层年化收益列表
        }
    """
    # 提取各层年化收益
    layer_returns = []
    for i in range(1, n_layers + 1):
        layer_key = f'layer_{i}'
        if layer_key in layer_stats:
            annual_return = layer_stats[layer_key].get('annual_return')
            if annual_return is not None and not np.isnan(annual_return):
                layer_returns.append(float(annual_return))
            else:
                layer_returns.append(np.nan)
        else:
            layer_returns.append(np.nan)
    
    # 过滤有效值
    valid_idx = [i for i, r in enumerate(layer_returns) if not np.isnan(r)]
    
    if len(valid_idx) < 2:
        return {
            'is_monotonic': False,
            'correlation': None,
            'quality': 'insufficient_data',
            'layer_returns': [round(r, 4) if not np.isnan(r) else None for r in layer_returns]
        }
    
    # 计算相关系数（Layer ID vs 收益）
    layer_ids = np.array([i + 1 for i in valid_idx])
    returns = np.array([layer_returns[i] for i in valid_idx])
    
    correlation = np.corrcoef(layer_ids, returns)[0, 1]
    
    # 单调性检验（正向因子期望正相关，即收益随 Layer ID 递增）
    is_monotonic = True
    for i in range(len(returns) - 1):
        if returns[i] > returns[i + 1]:
            is_monotonic = False
            break
    
    # 质量评估（正向因子期望正相关）
    if correlation > 0.5:
        quality = 'good'
    elif correlation > 0:
        quality = 'moderate'
    else:
        quality = 'poor'
    
    return {
        'is_monotonic': is_monotonic,
        'correlation': round(float(correlation), 4),
        'quality': quality,
        'layer_returns': [round(r, 4) if not np.isnan(r) else None for r in layer_returns]
    }


def run_volume_ratio_analysis(
    num_layers: int = 10,
    trade_cost_rate: float = 0.003,
    min_stocks_per_layer: int = 10
) -> Dict:
    """
    执行完整的量比因子分析（IC + 分层回测）
    
    步骤：
    1. 加载数据
    2. 计算 IC
    3. 执行分层回测（使用 LayeredBacktestEngine）
    4. 单调性检验
    5. 返回完整结果
    
    Args:
        num_layers: 分层数量（默认10层）
        trade_cost_rate: 单边交易成本率
        min_stocks_per_layer: 每层最少股票数
        
    Returns:
        完整分析结果字典，包含：
        - ic_metrics: IC 指标
        - ic_series: IC 时间序列
        - layered_result: 分层回测结果
        - params: 参数配置
        - generated_at: 生成时间
    
    规范:
        使用缓存全部日期数据，不截断
    """
    print(f"\n{'='*80}")
    print("量比因子完整分析（IC + 分层回测）")
    print(f"{'='*80}")
    print(f"  开始时间: {datetime.now().isoformat()}")
    print(f"  参数: num_layers={num_layers}")
    
    # ========== Step 1: 加载数据 ==========
    print("\n[1/4] 从缓存加载因子和收益数据...")
    try:
        factor_df, return_df, raw_metadata = load_data_from_cache()
        
        # 检查数据量
        n_assets = factor_df['asset'].nunique()
        if n_assets < min_stocks_per_layer * num_layers:
            print(f"  ⚠️ 股票数量较少: {n_assets} < {min_stocks_per_layer * num_layers}")
            print(f"  建议: 减少分层数或降低 min_stocks_per_layer")
        
    except Exception as e:
        # 数据加载失败分支：必须返回完整的五维度字段结构（遵循MODULE.md输出结构统一性规范）
        error_msg = f'数据加载失败: {e}'
        print(f"  ✗ {error_msg}")
        return {
            'success': False,
            'error': error_msg,
            # MODULE.md 必需字段（默认值）
            'factor_name': 'volume_ratio_1d',
            'calculation_date': datetime.now().strftime('%Y-%m-%d'),
            'period': {'start': '', 'end': '', 'description': '数据加载失败，无有效日期范围'},
            'ic_metrics': {
                'ic_mean': None,
                'ic_std': None,
                'icir': None,
                'p_value': None,
                'p_value_display': 'N/A'
            },
            'sample_stats': {
                'total_days': 0,
                'valid_days': 0,
                'avg_stocks_per_day': 0,
                'avg_stocks_period': {'start': '', 'end': '', 'description': '数据加载失败'}
            },
            # 五维度判断（默认值）
            'statistical_significance': {
                't_stat': None,
                'p_value': None,
                'p_value_display': 'N/A',
                'is_significant': False,
                'threshold': 1.96,
                'description': '数据加载失败，无法进行统计检验'
            },
            'factor_direction': {
                'ic_mean_sign': 'unknown',
                'ic_mean_abs': 0,
                'direction_threshold': 0.03,
                'description': '数据加载失败，无法判断因子方向'
            },
            'economic_significance': {
                'icir': None,
                'icir_threshold': 0.5,
                'is_economically_significant': False,
                'description': '数据加载失败，无法判断经济显著性'
            },
            'icir_stability': {
                'is_stable': False,
                'rolling_icir_std': None,
                'stability_threshold': 0.15,
                'description': '数据加载失败，无法判断ICIR稳定性'
            },
            'ic_distribution_consistency': {
                'is_consistent': False,
                'positive_ratio': None,
                'consistency_threshold': 0.55,
                'description': '数据加载失败，无法判断IC分布一致性'
            },
            # IC时间序列（空数组）
            'dates': [],
            'ic_values': [],
            'rolling_ic_mean': [],
            'positive_ratio': None,
            'n_assets': 0,
            'summary': {
                'ic_performance': '数据加载失败',
                'statistical_significance': '无法检验',
                'factor_direction': '无法判断',
                'economic_significance': '无法判断',
                'recommendation': '检查数据源完整性，确保缓存文件存在且格式正确'
            },
            'factor_stats': {
                'factor_name': 'volume_ratio_1d',
                'return_period': '1d',
                'data_source': str(FACTOR_CACHE),
                'total_days': 0,
                'valid_days': 0
            },
            'layered_result': {},
            'raw_metadata': {'period_start': '', 'period_end': '', 'total_days': 0},
            'update_mode': 'failed',
            'params': {
                'n_days': 0,
                'num_layers': num_layers,
                'factor_col': 'volume_ratio_5',
                'return_col': 'forward_return_1d',
                'factor_direction': 'positive',
                'trade_cost_rate': trade_cost_rate,
                'min_stocks_per_layer': min_stocks_per_layer
            },
            'generated_at': datetime.now().isoformat()
        }
    
    print(f"\n数据统计:")
    print(f"  - 原始日期范围: {raw_metadata['period_start']} ~ {raw_metadata['period_end']}")
    print(f"  - 原始交易日数: {raw_metadata['total_days']}")
    print(f"  - 过滤后交易日数: {factor_df['date'].nunique()}")
    print(f"  - 股票数量: {n_assets}")
    
    # ========== Step 2: 计算 IC ==========
    print("\n[2/4] 计算每日 IC...")
    ic_data = calculate_daily_ic_series(factor_df, return_df, min_stocks=min_stocks_per_layer)  # 传递参数（遵循MODULE.md代码质量规范）
    print(f"  - IC 均值: {ic_data['ic_mean']:.4f}")
    print(f"  - ICIR: {ic_data['icir']:.2f}")
    print(f"  - 正比例: {ic_data['positive_ratio']:.1%}")
    print(f"  - t 统计量: {ic_data['t_stat']:.2f}{' ***' if abs(ic_data['t_stat']) > 3.29 else ' **' if abs(ic_data['t_stat']) > 2.58 else ' *' if abs(ic_data['t_stat']) > 1.96 else ''}")
    
    # ========== Step 3: 分层回测 ==========
    print(f"\n[3/4] 执行分层回测...")
    
    # 准备分层回测数据
    backtest_factor_df = factor_df[['date', 'asset', 'volume_ratio_5']].copy()
    backtest_return_df = return_df[['date', 'asset', 'forward_return']].copy()
    
    try:
        # 初始化引擎
        engine = LayeredBacktestEngine(
            factor_df=backtest_factor_df,
            return_df=backtest_return_df,
            factor_col='volume_ratio_5',
            return_col='forward_return',
            date_col='date',
            asset_col='asset'
        )
        
        # 执行分层回测（正向因子）
        layered_result = engine.run(
            layer_method='percentile',
            n_layers=num_layers,
            factor_direction='positive',  # 量比是正向因子
            min_stocks_per_layer=min_stocks_per_layer,
            trade_cost_rate=trade_cost_rate
        )
        
        print(f"  ✓ 分层回测完成")
        print(f"  - 回测天数: {layered_result['meta']['n_days_total']}")
        print(f"  - 多空年化收益: {layered_result.get('long_short', {}).get('long_short_return_annual', 0):.2%}")
        
    except Exception as e:
        print(f"  ✗ 分层回测失败: {e}")
        traceback.print_exc()
        layered_result = None
    
    # ========== Step 4: 构建结果 ==========
    print(f"\n[4/4] 整理分析结果...")
    
    # 获取日期范围
    all_dates = sorted(factor_df['date'].unique())
    period_start = str(all_dates[0]) if all_dates else ''
    period_end = str(all_dates[-1]) if all_dates else ''
    
    # IC 指标（遵循 MODULE.md 输出结构统一性规范）
    # ic_metrics 只包含核心 IC 指标，positive_ratio 和 t_stat 在其他位置输出
    p_value_raw = round(float(2 * (1 - scipy_stats_norm_cdf(abs(ic_data['t_stat'])))), 6) if ic_data['t_stat'] else None
    ic_metrics = {
        'ic_mean': ic_data['ic_mean'],
        'ic_std': ic_data['ic_std'],
        'icir': ic_data['icir'],
        'p_value': p_value_raw,
        'p_value_display': str(round(p_value_raw, 4)) if p_value_raw is not None else 'N/A'  # MODULE.md 必需字段
    }
    
    # 样本统计（遵循 MODULE.md 输出结构统一性规范）
    sample_stats = {
        'total_days': raw_metadata['total_days'],  # 原始缓存日期数（dropna 前）
        'valid_days': ic_data['n_days'],           # 实际计算出 IC 的天数（有效天数）
        'avg_stocks_per_day': int(factor_df.groupby('date').size().mean()),  # 过滤后每日平均股票数
        'avg_stocks_period': {  # 口径范围说明（遵循 MODULE.md 统计口径规范）
            'start': period_start,
            'end': period_end,
            'description': '过滤后每日平均股票数（dropna 后）'
        }
    }
    
    # 五维度判断（遵循 MODULE.md 输出结构统一性规范）
    # 第1维：统计显著性（t检验）
    statistical_significance = {
        't_stat': ic_data['t_stat'],
        'p_value': round(float(2 * (1 - scipy_stats_norm_cdf(abs(ic_data['t_stat'])))), 6) if ic_data['t_stat'] else None,
        'is_significant': abs(ic_data['t_stat']) > 1.96,  # p < 0.05 等价于 |t| > 1.96
        'threshold': 1.96,
        'description': f"|t|={abs(ic_data['t_stat']):.2f} {'>' if abs(ic_data['t_stat']) > 1.96 else '≤'} 1.96，{'统计显著' if abs(ic_data['t_stat']) > 1.96 else '不显著'}"
    }
    
    # 第2维：因子方向（IC均值符号）
    factor_direction_judgment = {
        'ic_mean_sign': 'negative' if ic_data['ic_mean'] < -0.03 else 'positive' if ic_data['ic_mean'] > 0.03 else 'neutral',
        'ic_mean_abs': abs(ic_data['ic_mean']),
        'direction_threshold': 0.03,
        'description': f"IC均值={ic_data['ic_mean']:.4f}，{'反向因子' if ic_data['ic_mean'] < -0.03 else '正向因子' if ic_data['ic_mean'] > 0.03 else '方向不明确'}"
    }
    
    # 第3维：经济显著性（ICIR）
    economic_significance = {
        'icir': ic_data['icir'],
        'icir_threshold': 0.5,
        'is_economically_significant': ic_data['icir'] > 0.5,
        'description': f"ICIR={ic_data['icir']:.2f} {'>' if ic_data['icir'] > 0.5 else '≤'} 0.5，{'经济显著' if ic_data['icir'] > 0.5 else '不显著'}"
    }
    
    # 第4维：ICIR 稳定性（滚动 ICIR 标准差）
    # 简化实现：使用 IC 时间序列的标准差作为稳定性代理
    icir_stability = {
        'is_stable': ic_data['ic_std'] < 0.15,  # IC 标准差小于阈值表示稳定
        'rolling_icir_std': ic_data['ic_std'],  # 使用 IC 标准差作为稳定性代理
        'stability_threshold': 0.15,
        'description': f"IC_std={ic_data['ic_std']:.4f} {'<' if ic_data['ic_std'] < 0.15 else '≥'} 0.15，{'稳定' if ic_data['ic_std'] < 0.15 else '不稳定'}"
    }
    
    # 第5维：IC 分布一致性（正 IC 比例）
    ic_distribution_consistency = {
        'is_consistent': ic_data['positive_ratio'] > 0.55 if ic_data['ic_mean'] > 0 else ic_data['positive_ratio'] < 0.45,
        'positive_ratio': ic_data['positive_ratio'],
        'consistency_threshold': 0.55,
        'description': f"正IC比例={ic_data['positive_ratio']:.1%}，{'分布正常' if (ic_data['ic_mean'] > 0 and ic_data['positive_ratio'] > 0.55) or (ic_data['ic_mean'] < 0 and ic_data['positive_ratio'] < 0.45) else '分布异常'}"
    }
    
    # IC 时间序列
    ic_series = {
        'dates': ic_data['dates'],
        'ic_values': ic_data['ic_values'],
        'rolling_ic_mean': ic_data['rolling_ic_mean']
    }
    
    # 分层回测结果
    if layered_result is not None:
        # 单调性检验
        monotonicity_result = check_positive_monotonicity(
            layered_result['layer_stats'],
            num_layers
        )
        
        # 提取多空统计
        long_short_stats = layered_result.get('long_short', {})
        
        # 构建 summary
        summary = {
            'long_short_annual_return': round(float(long_short_stats.get('long_short_return_annual', 0)), 4),
            'long_short_sharpe': round(float(long_short_stats.get('long_short_sharpe', 0)), 4),
            'long_short_volatility': round(float(long_short_stats.get('long_short_volatility', 0)), 4),
            'monotonicity_passed': monotonicity_result['is_monotonic'],
            'monotonicity_correlation': monotonicity_result['correlation'],
            'monotonicity_quality': monotonicity_result['quality']
        }
        
        # 使用公共模块转换 daily_records
        layered_result_json = {
            'layer_stats': convert_to_native_types(layered_result['layer_stats']),
            'long_short': convert_to_native_types(long_short_stats),
            'monotonicity': monotonicity_result,
            'trading_cost_analysis': convert_to_native_types(layered_result.get('trading_cost_analysis', {})),
            'daily_records': convert_to_native_types(layered_result.get('daily_records', [])),
            'meta': convert_to_native_types(layered_result['meta']),
            'num_layers': num_layers,
            'n_days': layered_result['meta']['n_days_total'],
            'n_stocks': layered_result['meta']['n_assets_total'],
            'summary': summary
        }
    else:
        layered_result_json = {
            'layer_stats': {},
            'long_short': {},
            'monotonicity': {},
            'trading_cost_analysis': {},
            'daily_records': [],
            'meta': {},
            'num_layers': num_layers,
            'n_days': 0,
            'n_stocks': 0,
            'summary': {
                'long_short_annual_return': 0,
                'long_short_sharpe': 0,
                'long_short_volatility': 0,
                'monotonicity_passed': False,
                'monotonicity_correlation': None,
                'monotonicity_quality': 'failed'
            }
        }
    
    # 构建完整结果（遵循 MODULE.md 输出结构统一性规范）
    # IC 相关的 summary（五维度综合判断）
    ic_summary = {
        'ic_performance': f"IC均值={ic_data['ic_mean']:.4f}, ICIR={ic_data['icir']:.2f}, 因子预测能力{'较弱' if abs(ic_data['icir']) < 0.3 else '中等' if abs(ic_data['icir']) < 0.5 else '较强'}",
        'statistical_significance': statistical_significance['description'],
        'factor_direction': factor_direction_judgment['description'],
        'economic_significance': economic_significance['description'],
        'recommendation': f"{'可用于分层回测' if statistical_significance['is_significant'] and abs(ic_data['icir']) > 0.2 else '建议进一步验证或优化因子'}"
    }
    
    # factor_stats（MODULE.md 必需字段）
    factor_stats = {
        'factor_name': 'volume_ratio_1d',
        'return_period': '1d',
        'data_source': str(FACTOR_CACHE),
        'total_days': raw_metadata['total_days'],
        'valid_days': ic_data['n_days']
    }
    
    result = {
        # MODULE.md 必需字段
        'factor_name': 'volume_ratio_1d',
        'calculation_date': datetime.now().strftime('%Y-%m-%d'),
        'period': {
            'start': period_start,
            'end': period_end
        },
        'ic_metrics': ic_metrics,
        'sample_stats': sample_stats,
        
        # 五维度判断（遵循 MODULE.md 输出结构统一性规范）
        'statistical_significance': statistical_significance,
        'factor_direction': factor_direction_judgment,
        'economic_significance': economic_significance,
        'icir_stability': icir_stability,
        'ic_distribution_consistency': ic_distribution_consistency,
        
        # IC 时间序列（顶层字段，遵循 MODULE.md 输出结构统一性规范）
        'dates': ic_data['dates'],
        'ic_values': ic_data['ic_values'],
        'rolling_ic_mean': ic_data['rolling_ic_mean'],
        'positive_ratio': ic_data['positive_ratio'],
        'n_assets': ic_data['n_assets'],
        'summary': ic_summary,
        'factor_stats': factor_stats,
        
        # 扩展字段（分层回测等）
        'ic_series': ic_series,  # 保留嵌套结构供兼容
        'layered_result': layered_result_json,
        'raw_metadata': {  # 原始缓存元信息（遵循 MODULE.md 输出结构统一性规范）
            'period_start': raw_metadata['period_start'],
            'period_end': raw_metadata['period_end'],
            'total_days': raw_metadata['total_days']
        },
        'update_mode': 'full',  # 更新模式标记（遵循 MODULE.md 输出结构统一性规范）
        'params': {
            'n_days': ic_data['n_days'],  # 使用 ic_data['n_days']，而非未定义的 n_days 变量
            'num_layers': num_layers,
            'factor_col': 'volume_ratio_5',
            'return_col': 'forward_return_1d',
            'factor_direction': 'positive',
            'trade_cost_rate': trade_cost_rate,
            'min_stocks_per_layer': min_stocks_per_layer
        },
        'generated_at': datetime.now().isoformat()
    }
    
    # 转换为原生类型
    result = convert_to_native_types(result)
    
    print(f"  ✓ 结果整理完成")
    print(f"{'='*80}")
    
    return result


def main():
    """主函数 - 执行完整分析（IC + 分层回测）"""
    print("=" * 80)
    print("量比因子完整分析（缓存版）")
    print("=" * 80)
    print(f"开始时间: {datetime.now().isoformat()}")
    
    # 执行完整分析（使用缓存全部日期）
    result = run_volume_ratio_analysis(num_layers=10)
    
    # 保存结果
    print(f"\n保存数据到: {OUTPUT_FILE}")
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    
    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    
    print("\n" + "=" * 60)
    print(f"完成！共计算 {result['sample_stats']['valid_days']} 天有效 IC 数据（原始数据 {result['sample_stats']['total_days']} 天）")
    print("=" * 60)
    print(f"输出文件: {OUTPUT_FILE}")
    
    # 打印关键指标
    print("\n关键指标摘要:")
    print(f"  IC 均值: {result['ic_metrics']['ic_mean']:.4f}")
    print(f"  ICIR: {result['ic_metrics']['icir']:.2f}")
    print(f"  多空年化收益: {result['layered_result']['summary']['long_short_annual_return']:.2%}")
    print(f"  多空夏普: {result['layered_result']['summary']['long_short_sharpe']:.2f}")
    print(f"  单调性相关系数: {result['layered_result']['summary']['monotonicity_correlation']:.4f}")
    print(f"  单调性质量: {result['layered_result']['summary']['monotonicity_quality']}")
    
    print(f"\n完成时间: {datetime.now().isoformat()}")
    print("=" * 80)


if __name__ == '__main__':
    # 主入口错误处理（遵循 MODULE.md 主入口错误处理规范）
    try:
        main()
    except FileNotFoundError as e:
        print(f"\n[错误] 缓存文件不存在: {e}")
        print("  请先运行数据缓存脚本生成数据")
        sys.exit(1)
    except ValueError as e:
        print(f"\n[错误] 数据验证失败: {e}")
        print("  请检查缓存数据完整性")
        sys.exit(1)
    except RuntimeError as e:
        print(f"\n[错误] 计算过程失败: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"\n[错误] 未预期的异常: {e}")
        traceback.print_exc()  # 使用顶部导入的traceback（遵循MODULE.md代码质量规范）
        sys.exit(1)