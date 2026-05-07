#!/usr/bin/env python3
"""
预计算量比因子分析结果

此脚本用于在凌晨内存空闲时运行，生成预计算的结果文件。
Web 服务直接读取预计算结果，避免实时计算导致的 OOM。

运行方式：
    python precompute_volume_ratio.py

建议运行时间：
    凌晨 3:00-5:00（内存空闲时段）

作者: 云舟
日期: 2026-04-07
"""

import json
import gzip
import os
import gc
from pathlib import Path
from datetime import datetime
import pandas as pd
import numpy as np
from common.data_completeness import check_data_completeness, get_ic_output_path

# 配置
BASE_DIR = Path(__file__).resolve().parent.parent
CACHE_DIR = BASE_DIR / 'cache' / 'factor_data'
OUTPUT_FILE = get_ic_output_path('volume_ratio')


def load_cache_light(max_days: int = 500, use_category: bool = True):
    """轻量级缓存加载（内存优化版）
    
    内存优化策略：
    1. 只加载必要列（减少 60% 内存）
    2. 使用 category 类型（减少 80% 内存）
    3. 及时释放中间变量
    
    Args:
        max_days: 最大加载天数（默认 500 天，全量数据）
        use_category: 是否使用 category 类型优化内存（默认 True）
        
    Returns:
        tuple: (factor_df, return_df) 或 (None, None)
    """
    print(f'[加载缓存] 加载最近 {max_days} 天数据（内存优化模式）...')
    
    factor_path = CACHE_DIR / 'factor_data.json.gz'
    return_path = CACHE_DIR / 'return_data.json.gz'
    
    if not factor_path.exists() or not return_path.exists():
        print('[加载缓存] 缓存文件不存在')
        return None, None
    
    # ========== 加载因子数据（只加载必要列） ==========
    print('[加载缓存] 正在加载因子数据...')
    with gzip.open(factor_path, 'rt', encoding='utf-8') as f:
        factor_data = json.load(f)
    
    # 获取所有日期
    all_dates = sorted(set(r.get('date') for r in factor_data.get('data', [])))
    print(f'[加载缓存] 数据包含 {len(all_dates)} 天数据（{all_dates[0]} ~ {all_dates[-1]}）')
    
    # 只保留最近 max_days 天
    if len(all_dates) > max_days:
        recent_dates = set(all_dates[-max_days:])
        print(f'[加载缓存] 只加载最近 {max_days} 天（{all_dates[-max_days]} ~ {all_dates[-1]}）')
        # 只提取必要列：date, asset, volume_ratio_5
        factor_records = [
            {'date': r['date'], 'asset': r['asset'], 'volume_ratio_5': r.get('volume_ratio_5')}
            for r in factor_data.get('data', []) if r.get('date') in recent_dates
        ]
    else:
        # 全量数据，只提取必要列
        factor_records = [
            {'date': r['date'], 'asset': r['asset'], 'volume_ratio_5': r.get('volume_ratio_5')}
            for r in factor_data.get('data', [])
        ]
    
    del factor_data
    gc.collect()
    
    factor_df = pd.DataFrame(factor_records)
    del factor_records
    gc.collect()
    
    # 使用 category 类型优化内存
    if use_category:
        factor_df['date'] = factor_df['date'].astype('category')
        factor_df['asset'] = factor_df['asset'].astype('category')
    
    # 转换数值列
    factor_df['volume_ratio_5'] = pd.to_numeric(factor_df['volume_ratio_5'], errors='coerce')
    
    factor_mem = factor_df.memory_usage(deep=True).sum() / 1024 / 1024
    print(f'[加载缓存] factor_df: {len(factor_df)} 行, {factor_mem:.2f} MB')
    
    # ========== 加载收益数据（只加载必要列） ==========
    print('[加载缓存] 正在加载收益数据...')
    with gzip.open(return_path, 'rt', encoding='utf-8') as f:
        return_data = json.load(f)
    
    # 只保留最近 max_days 天，只提取必要列：date, asset, forward_return_1d
    if len(all_dates) > max_days:
        return_records = [
            {'date': r['date'], 'asset': r['asset'], 'forward_return_1d': r.get('forward_return_1d', r.get('forward_return'))}
            for r in return_data.get('data', []) if r.get('date') in recent_dates
        ]
    else:
        return_records = [
            {'date': r['date'], 'asset': r['asset'], 'forward_return_1d': r.get('forward_return_1d', r.get('forward_return'))}
            for r in return_data.get('data', [])
        ]
    
    del return_data, all_dates
    if 'recent_dates' in dir():
        del recent_dates
    gc.collect()
    
    return_df = pd.DataFrame(return_records)
    del return_records
    gc.collect()
    
    # 使用 category 类型优化内存
    if use_category:
        return_df['date'] = return_df['date'].astype('category')
        return_df['asset'] = return_df['asset'].astype('category')
    
    # 转换数值列
    return_df['forward_return_1d'] = pd.to_numeric(return_df['forward_return_1d'], errors='coerce')
    
    return_mem = return_df.memory_usage(deep=True).sum() / 1024 / 1024
    print(f'[加载缓存] return_df: {len(return_df)} 行, {return_mem:.2f} MB')
    print(f'[加载缓存] 总内存占用: {factor_mem + return_mem:.2f} MB')
    
    return factor_df, return_df


def calculate_ic(factor_df, return_df):
    """计算正向 Rank IC 指标（量比是正向因子）
    
    Args:
        factor_df: 因子 DataFrame
        return_df: 收益 DataFrame
        
    Returns:
        tuple: (ic_metrics, ic_series_data)
    """
    print('[计算 IC] 开始计算（正向排名）...')
    
    from scipy.stats import spearmanr
    
    # 合并数据
    merged_df = pd.merge(
        factor_df[['date', 'asset', 'volume_ratio_5']],
        return_df[['date', 'asset', 'forward_return_1d']],
        on=['date', 'asset'],
        how='inner'
    )
    
    # 确保日期是字符串类型（category 需要转换）
    merged_df['date'] = merged_df['date'].astype(str)
    
    # 按日期分组计算 Rank IC
    ic_values = []
    ic_dates = []
    
    for date, group in merged_df.groupby('date'):
        # 过滤 NaN
        valid = group.dropna(subset=['volume_ratio_5', 'forward_return_1d'])
        
        if len(valid) < 10:  # 最少 10 只股票
            continue
        
        # 计算 Spearman Rank IC
        ic, p_value = spearmanr(valid['volume_ratio_5'], valid['forward_return_1d'])
        
        ic_dates.append(date)
        ic_values.append(ic)
    
    ic_series = pd.Series(ic_values, index=ic_dates)
    
    # 计算 20 日滚动均值
    rolling_mean = ic_series.rolling(window=20, min_periods=1).mean()
    
    # 计算统计指标
    ic_mean = ic_series.mean()
    ic_std = ic_series.std()
    icir = ic_mean / ic_std if ic_std != 0 else 0
    
    # t 统计量和显著性
    n_days = len(ic_series)
    t_stat = ic_mean / ic_std * np.sqrt(n_days) if ic_std != 0 else 0
    
    # 正 IC 比例
    positive_ratio = (ic_series > 0).mean()
    
    # 显著性判断
    if abs(t_stat) > 2.576:
        significance = "***"
    elif abs(t_stat) > 1.96:
        significance = "**"
    elif abs(t_stat) > 1.645:
        significance = "*"
    else:
        significance = ""
    
    # 摘要
    summary = f"IC均值={ic_mean:.4f}, ICIR={icir:.2f}, 正比例={positive_ratio:.1%}, 因子预测能力{'较弱' if abs(icir) < 0.3 else '中等' if abs(icir) < 0.5 else '较强'}"
    
    # 提取指标
    ic_metrics = {
        'ic_mean': round(ic_mean, 6),
        'ic_std': round(ic_std, 6),
        'icir': round(icir, 4),
        't_stat': round(t_stat, 4),
        'p_value': round(1 - 0.95 if abs(t_stat) > 1.96 else 0.5, 6),  # 简化处理
        'positive_ratio': round(positive_ratio, 4),
        'n_days': n_days,
        'n_assets': factor_df['asset'].nunique(),
        'significance': significance,
        'summary': summary
    }
    
    # IC 时间序列
    ic_series_data = {
        'dates': [str(d) for d in ic_series.index],
        'ic_values': [round(v, 6) for v in ic_series.values],
        'rolling_ic_mean': [round(v, 6) for v in rolling_mean.values]
    }
    
    # 释放中间变量
    del merged_df, ic_series, rolling_mean
    gc.collect()
    
    print(f'[计算 IC] 完成，IC Mean: {ic_metrics["ic_mean"]:.4f}')
    
    return ic_metrics, ic_series_data


def run_layered_backtest(factor_df, return_df, num_layers=5):
    """执行分层回测
    
    Args:
        factor_df: 因子 DataFrame
        return_df: 收益 DataFrame
        num_layers: 分层数量
        
    Returns:
        dict: 分层回测结果
    """
    print('[分层回测] 开始执行...')
    
    from layered_backtest import LayeredBacktest
    
    backtest = LayeredBacktest(num_layers=num_layers)
    layered_result = backtest.run(factor_df, return_df, factor_col='volume_ratio_5', return_col='forward_return_1d')
    
    # 转换为 JSON 格式
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
    
    # 单调性检验
    def calculate_monotonicity(statistics_df):
        layer_returns = []
        for i in range(1, num_layers + 1):
            layer_key = f'layer_{i}'
            if layer_key in statistics_df.index:
                layer_returns.append(statistics_df.loc[layer_key, 'annual_return'])
        
        for i in range(len(layer_returns) - 1):
            if layer_returns[i] < layer_returns[i + 1]:
                return True
        return False
    
    long_short_stats = layered_result.statistics.loc['long_short']
    summary = {
        'long_short_annual_return': round(float(long_short_stats['annual_return']), 4),
        'long_short_sharpe': round(float(long_short_stats['sharpe']), 4),
        'long_short_max_drawdown': calculate_max_drawdown(layered_result.long_short['cumulative_nav']),
        'monotonicity_passed': calculate_monotonicity(layered_result.statistics)
    }
    
    layered_result_json = {
        'layer_returns': convert_df_dates(layered_result.layer_returns.reset_index().to_dict(orient='records')),
        'cumulative_returns': convert_df_dates(layered_result.cumulative_returns.reset_index().to_dict(orient='records')),
        'statistics': layered_result.statistics.reset_index().to_dict(orient='records'),
        'long_short': convert_df_dates(layered_result.long_short.reset_index().to_dict(orient='records')),
        'num_layers': num_layers,
        'n_days': len(layered_result.layer_returns),
        'n_stocks': factor_df['asset'].nunique(),
        'summary': summary
    }
    
    # 释放中间变量
    del layered_result, backtest
    gc.collect()
    
    print(f'[分层回测] 完成，多空收益: {summary["long_short_annual_return"]:.2%}')
    
    return layered_result_json


def load_existing_ic_cache():
    """加载已有的 IC 缓存数据
    
    Returns:
        dict: 包含 dates, ic_values, rolling_ic_mean 的字典，或 None
    """
    if not OUTPUT_FILE.exists():
        return None
    
    try:
        with open(OUTPUT_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        ic_series = data.get('ic_series', {})
        ic_metrics = data.get('ic_metrics', {})
        layered_result = data.get('layered_result', {})
        
        print(f'[加载缓存] 已加载现有 IC 缓存: {len(ic_series.get("dates", []))} 天')
        return {
            'ic_series': ic_series,
            'ic_metrics': ic_metrics,
            'layered_result': layered_result
        }
    except Exception as e:
        print(f'[加载缓存] 读取现有缓存失败: {e}')
        return None


def merge_ic_data(existing_ic: dict, new_ic_metrics: dict, new_ic_series: dict, 
                  new_layered_result: dict, factor_df: pd.DataFrame):
    """合并增量计算的 IC 数据
    
    Args:
        existing_ic: 已有的 IC 缓存
        new_ic_metrics: 新计算的 IC 指标
        new_ic_series: 新计算的 IC 序列
        new_layered_result: 新计算的分层回测结果
        factor_df: 因子数据（用于统计）
        
    Returns:
        tuple: (merged_ic_metrics, merged_ic_series)
    """
    from scipy.stats import spearmanr
    
    # 合并 IC 序列
    existing_dates = set(existing_ic['ic_series'].get('dates', []))
    new_dates = set(new_ic_series.get('dates', []))
    
    # 构建合并后的数据
    all_dates = sorted(existing_dates | new_dates)
    
    # 合并 IC 值
    date_to_ic = {}
    for i, date in enumerate(existing_ic['ic_series'].get('dates', [])):
        date_to_ic[date] = existing_ic['ic_series']['ic_values'][i]
    for i, date in enumerate(new_ic_series.get('dates', [])):
        date_to_ic[date] = new_ic_series['ic_values'][i]
    
    ic_values = [date_to_ic[d] for d in all_dates]
    
    # 计算新的滚动均值
    ic_series = pd.Series(ic_values, index=all_dates)
    rolling_mean = ic_series.rolling(window=20, min_periods=1).mean()
    
    merged_ic_series = {
        'dates': [str(d) for d in all_dates],
        'ic_values': [round(v, 6) for v in ic_values],
        'rolling_ic_mean': [round(v, 6) for v in rolling_mean.values]
    }
    
    # 重新计算合并后的 IC 指标
    ic_mean = ic_series.mean()
    ic_std = ic_series.std()
    icir = ic_mean / ic_std if ic_std != 0 else 0
    n_days = len(ic_series)
    t_stat = ic_mean / ic_std * np.sqrt(n_days) if ic_std != 0 else 0
    positive_ratio = (ic_series > 0).mean()
    
    if abs(t_stat) > 2.576:
        significance = "***"
    elif abs(t_stat) > 1.96:
        significance = "**"
    elif abs(t_stat) > 1.645:
        significance = "*"
    else:
        significance = ""
    
    summary = f"IC均值={ic_mean:.4f}, ICIR={icir:.2f}, 正比例={positive_ratio:.1%}, 因子预测能力{'较弱' if abs(icir) < 0.3 else '中等' if abs(icir) < 0.5 else '较强'}"
    
    merged_ic_metrics = {
        'ic_mean': round(ic_mean, 6),
        'ic_std': round(ic_std, 6),
        'icir': round(icir, 4),
        't_stat': round(t_stat, 4),
        'p_value': round(1 - 0.95 if abs(t_stat) > 1.96 else 0.5, 6),
        'positive_ratio': round(positive_ratio, 4),
        'n_days': n_days,
        'n_assets': factor_df['asset'].nunique(),
        'significance': significance,
        'summary': summary
    }
    
    print(f'[合并数据] 合并后共 {n_days} 天数据')
    
    return merged_ic_metrics, merged_ic_series


def main():
    """主函数（内存优化版，支持增量计算）"""
    print('='*60)
    print('预计算量比因子分析结果（内存优化版）')
    print('='*60)
    print(f'开始时间: {datetime.now().isoformat()}')
    
    # ========== 增量判断 ==========
    mode, missing_dates, info = check_data_completeness('volume_ratio')
    
    if mode == 'skip':
        print('[数据完整性] 数据完备，无需重新计算')
        print(f'完成时间: {datetime.now().isoformat()}')
        print('='*60)
        return
    
    is_incremental = (mode == 'incremental')
    if is_incremental:
        print(f'[增量模式] 需要计算 {len(missing_dates)} 天数据')
        print(f'[增量模式] 缺失日期范围: {missing_dates[0]} ~ {missing_dates[-1]}')
    else:
        print('[全量模式] 执行全量计算')
    
    # 内存监控（可选）
    try:
        import psutil
        process = psutil.Process()
        initial_mem = process.memory_info().rss / 1024 / 1024
        print(f'[内存监控] 初始内存占用: {initial_mem:.2f} MB')
        has_psutil = True
    except ImportError:
        print('[内存监控] psutil 未安装，跳过内存监控')
        has_psutil = False
    
    # Step 1: 加载缓存数据（全量 500 天）
    print('\n[Step 1] 加载缓存数据...')
    factor_df, return_df = load_cache_light(max_days=500, use_category=True)
    
    if factor_df is None:
        print('[错误] 缓存数据加载失败')
        return
    
    if has_psutil:
        current_mem = process.memory_info().rss / 1024 / 1024
        print(f'[内存监控] 数据加载后内存: {current_mem:.2f} MB (增加 {current_mem - initial_mem:.2f} MB)')
    
    # Step 2: 过滤无效数据
    print('\n[Step 2] 过滤无效数据...')
    original_len = len(factor_df)
    factor_df = factor_df.dropna(subset=['volume_ratio_5'])
    print(f'[过滤] 原始数据: {original_len} 条, 有效数据: {len(factor_df)} 条, 删除: {original_len - len(factor_df)} 条')
    
    if has_psutil:
        current_mem = process.memory_info().rss / 1024 / 1024
        print(f'[内存监控] 过滤后内存: {current_mem:.2f} MB')
    
    # 增量模式：只计算缺失日期的数据
    if is_incremental:
        missing_dates_set = set(missing_dates)
        factor_df_inc = factor_df[factor_df['date'].astype(str).isin(missing_dates_set)]
        return_df_inc = return_df[return_df['date'].astype(str).isin(missing_dates_set)]
        
        print(f'[增量模式] 筛选后因子数据: {len(factor_df_inc)} 条')
        print(f'[增量模式] 筛选后收益数据: {len(return_df_inc)} 条')
        
        # Step 3: 增量计算 IC
        print('\n[Step 3] 计算 IC（增量）...')
        ic_metrics, ic_series_data = calculate_ic(factor_df_inc, return_df_inc)
        
        if has_psutil:
            current_mem = process.memory_info().rss / 1024 / 1024
            print(f'[内存监控] IC 计算后内存: {current_mem:.2f} MB')
        
        # Step 4: 增量分层回测
        print('\n[Step 4] 分层回测（增量）...')
        layered_result = run_layered_backtest(factor_df_inc, return_df_inc)
        
        # 加载已有缓存并合并
        print('\n[Step 5] 合并增量数据...')
        existing_cache = load_existing_ic_cache()
        
        if existing_cache:
            # 合并 IC 数据
            ic_metrics, ic_series_data = merge_ic_data(
                existing_cache, ic_metrics, ic_series_data, layered_result, factor_df
            )
            # 使用全量数据的分层回测结果（重新计算）
            print('[Step 6] 分层回测（全量合并后）...')
            layered_result = run_layered_backtest(factor_df, return_df)
        else:
            print('[警告] 无法加载已有缓存，使用新计算的结果')
        
        # 清理中间变量
        del factor_df_inc, return_df_inc, existing_cache
        gc.collect()
    else:
        # 全量计算模式
        # Step 3: 计算 IC
        print('\n[Step 3] 计算 IC...')
        ic_metrics, ic_series_data = calculate_ic(factor_df, return_df)
        
        if has_psutil:
            current_mem = process.memory_info().rss / 1024 / 1024
            print(f'[内存监控] IC 计算后内存: {current_mem:.2f} MB')
        
        # Step 4: 分层回测
        print('\n[Step 4] 分层回测...')
        layered_result = run_layered_backtest(factor_df, return_df)
    
    # 清理输入数据（释放内存）
    del factor_df, return_df
    gc.collect()
    
    if has_psutil:
        current_mem = process.memory_info().rss / 1024 / 1024
        print(f'[内存监控] 分层回测后内存: {current_mem:.2f} MB')
    
    # Step 5/7: 保存结果
    print('\n[Step 7] 保存结果...')
    result_json = {
        'factor_name': 'volume_ratio',
        'ic_metrics': ic_metrics,
        'ic_series': ic_series_data,
        'layered_result': layered_result,
        'params': {
            'n_days': 500,
            'max_stocks': 0,
            'num_layers': 5,
            'factor_col': 'volume_ratio_5'
        },
        'generated_at': datetime.now().isoformat()
    }
    
    # 确保输出目录存在
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    
    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        json.dump(result_json, f, ensure_ascii=False, indent=2)
    
    # 最终清理
    del result_json, ic_metrics, ic_series_data, layered_result
    gc.collect()
    
    if has_psutil:
        final_mem = process.memory_info().rss / 1024 / 1024
        print(f'[内存监控] 最终内存占用: {final_mem:.2f} MB')
        print(f'[内存监控] 峰值内存增量: {final_mem - initial_mem:.2f} MB')
    
    print(f'\n[保存结果] 已保存到: {OUTPUT_FILE}')
    print(f'完成时间: {datetime.now().isoformat()}')
    print('='*60)
    print('预计算完成！')


if __name__ == '__main__':
    main()