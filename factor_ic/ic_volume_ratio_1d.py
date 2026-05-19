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
from pathlib import Path

# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent.parent))

import pandas as pd
import numpy as np
import gzip
import json
from typing import Tuple, Dict, Any
from scipy.stats import spearmanr
from datetime import datetime

# 导入数据完整性检查模块
from factor_ic.common.data_completeness import get_ic_output_path

# 导入类型转换模块
from factor_ic.common.convert_types import convert_to_native_types

# 导入分层回测引擎
from backtest.layered_backtest import LayeredBacktestEngine

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
    
    # 使用缓存全部日期（不截断）
    
    # 返回过滤后的数据 + 原始数据元信息（遵循 PROJECT.md 输出字段语义规范）
    return factor_df, return_df, {
        'period_start': raw_period_start,
        'period_end': raw_period_end,
        'total_days': raw_total_days
    }


def calculate_daily_ic_series(
    factor_df: pd.DataFrame,
    return_df: pd.DataFrame
) -> dict:
    """
    计算每日的 IC 时间序列（量比是正向因子）
    
    参数:
        factor_df: 因子数据
        return_df: 收益数据
        
    返回:
        dict: IC 计算结果
    """
    print("\n[计算 IC] 开始计算（正向排名）...")
    
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
        
        if len(valid) < 10:  # 最少 10 只股票
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
    
    # 显著性判断（统一标准阈值）
    # |t|>3.29 → "***" (p<0.001, 99.9%置信度)
    # |t|>2.58 → "**" (p<0.01, 99%置信度)
    # |t|>1.96 → "*" (p<0.05, 95%置信度)
    if abs(t_stat) > 3.29:
        significance = "***"
    elif abs(t_stat) > 2.58:
        significance = "**"
    elif abs(t_stat) > 1.96:
        significance = "*"
    else:
        significance = ""
    
    # 摘要
    summary = f"IC均值={ic_mean:.4f}, ICIR={icir:.2f}, 正比例={positive_ratio:.1%}, 因子预测能力{'较弱' if abs(icir) < 0.3 else '中等' if abs(icir) < 0.5 else '较强'}"
    
    print(f"[计算 IC] 完成，IC Mean: {ic_mean:.4f}")
    
    return {
        'factor_name': 'volume_ratio_1d',
        'dates': [str(d) for d in ic_series.index],
        'ic_values': [round(v, 6) for v in ic_values],
        'rolling_ic_mean': [round(v, 6) for v in rolling_mean.values],
        'ic_mean': round(ic_mean, 6),
        'ic_std': round(ic_std, 6),
        'icir': round(icir, 4),
        'positive_ratio': round(positive_ratio, 4),
        't_stat': round(t_stat, 4),
        'significance': significance,
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
        return {
            'success': False,
            'error': f'数据加载失败: {e}',
            'generated_at': datetime.now().isoformat()
        }
    
    print(f"\n数据统计:")
    print(f"  - 原始日期范围: {raw_metadata['period_start']} ~ {raw_metadata['period_end']}")
    print(f"  - 原始交易日数: {raw_metadata['total_days']}")
    print(f"  - 过滤后交易日数: {factor_df['date'].nunique()}")
    print(f"  - 股票数量: {n_assets}")
    
    # ========== Step 2: 计算 IC ==========
    print("\n[2/4] 计算每日 IC...")
    ic_data = calculate_daily_ic_series(factor_df, return_df)
    print(f"  - IC 均值: {ic_data['ic_mean']:.4f}")
    print(f"  - ICIR: {ic_data['icir']:.2f}")
    print(f"  - 正比例: {ic_data['positive_ratio']:.1%}")
    print(f"  - t 统计量: {ic_data['t_stat']:.2f} {ic_data['significance']}")
    
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
        import traceback
        traceback.print_exc()
        layered_result = None
    
    # ========== Step 4: 构建结果 ==========
    print(f"\n[4/4] 整理分析结果...")
    
    # 获取日期范围
    all_dates = sorted(factor_df['date'].unique())
    period_start = str(all_dates[0]) if all_dates else ''
    period_end = str(all_dates[-1]) if all_dates else ''
    
    # IC 指标（符合 PROJECT.md 规范）
    ic_metrics = {
        'ic_mean': ic_data['ic_mean'],
        'ic_std': ic_data['ic_std'],
        'icir': ic_data['icir'],
        'p_value': round(2 * (1 - __import__('scipy.stats', fromlist=['stats']).stats.norm.cdf(abs(ic_data['t_stat']))), 6) if ic_data['t_stat'] else None,
        # 额外保留字段（便于分析）
        'positive_ratio': ic_data['positive_ratio'],
        't_stat': ic_data['t_stat'],
        'significance': ic_data['significance']
    }
    
    # 样本统计（符合 PROJECT.md 规范）
    sample_stats = {
        'total_days': len(all_dates),           # 数据范围内所有日期（遵循 PROJECT.md 规范）
        'valid_days': ic_data['n_days'],        # 实际计算出 IC 的天数（有效天数）
        'avg_stocks_per_day': int(factor_df.groupby('date').size().mean())
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
    
    # 构建完整结果（符合 PROJECT.md 规范）
    result = {
        # PROJECT.md 必需字段
        'factor_name': 'volume_ratio_1d',
        'calculation_date': datetime.now().strftime('%Y-%m-%d'),
        'period': {
            'start': period_start,
            'end': period_end
        },
        'ic_metrics': ic_metrics,
        'sample_stats': sample_stats,
        
        # 扩展字段（分层回测等）
        'ic_series': ic_series,
        'layered_result': layered_result_json,
        'params': {
            'n_days': n_days,
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
    main()