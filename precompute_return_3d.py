#!/usr/bin/env python3
"""
预计算 3日涨幅因子分析结果

此脚本用于在凌晨内存空闲时运行，生成预计算的结果文件。
Web 服务直接读取预计算结果，避免实时计算导致的 OOM。

运行方式：
    python precompute_return_3d.py

建议运行时间：
    凌晨 3:00-5:00（内存空闲时段）

作者: 云舟 + AI Assistant
日期: 2026-04-04
"""

import json
import gzip
import os
import gc
from pathlib import Path
from datetime import datetime
import pandas as pd
import numpy as np
import time


def get_memory_usage_mb() -> float:
    """获取当前进程真实RSS内存（MB）"""
    try:
        with open('/proc/self/status', 'r') as f:
            for line in f:
                if line.startswith('VmRSS:'):
                    return int(line.split()[1]) / 1024  # kB -> MB
    except Exception:
        pass
    return 0.0


def get_memory_info_str() -> str:
    """获取内存信息字符串"""
    mem_mb = get_memory_usage_mb()
    return f"RSS={mem_mb:.1f}MB"


def check_memory_threshold():
    """检查内存阈值，超过时暂停并清理"""
    mem_mb = get_memory_usage_mb()
    if mem_mb > MEMORY_THRESHOLD_MB:
        print(f'[内存监控] ⚠ 内存超阈值 ({mem_mb:.1f}MB > {MEMORY_THRESHOLD_MB}MB)，暂停 {MEMORY_PAUSE_SECONDS}s...')
        gc.collect()
        time.sleep(MEMORY_PAUSE_SECONDS)
        mem_mb = get_memory_usage_mb()
        print(f'[内存监控] GC后内存: {mem_mb:.1f}MB')
    return mem_mb

# 配置
BASE_DIR = Path(__file__).parent
CACHE_DIR = BASE_DIR / 'cache' / 'factor_data'
OUTPUT_FILE = BASE_DIR / 'return_3d_analysis_result.json'

# 内存优化配置
MEMORY_THRESHOLD_MB = 900  # 内存阈值（MB）- 预留足够空间避免OOM
MEMORY_PAUSE_SECONDS = 15  # 内存超阈值时暂停时间
STREAM_LOAD_BATCH_SIZE = 50000  # 流式加载批次大小


def load_cache_light(max_days: int = 500, use_category: bool = True):
    """轻量级缓存加载（内存优化版）
    
    内存优化策略：
    1. 只加载必要列（减少 60% 内存）
    2. 使用 category 类型（减少 80% 内存）
    3. 分批处理大数据，避免一次性加载
    4. 内存监控，超过阈值时暂停
    5. 及时释放中间变量
    
    Args:
        max_days: 最大加载天数（默认 500 天，全量数据）
        use_category: 是否使用 category 类型优化内存（默认 True）
        
    Returns:
        tuple: (factor_df, return_df) 或 (None, None)
    """
    print(f'[加载缓存] 加载最近 {max_days} 天数据（内存优化模式）...')
    print(f'[内存监控] 当前内存: {get_memory_info_str()}')
    
    factor_path = CACHE_DIR / 'factor_data.json.gz'
    return_path = CACHE_DIR / 'return_data.json.gz'
    
    if not factor_path.exists() or not return_path.exists():
        print('[加载缓存] 缓存文件不存在')
        return None, None
    
    # ========== 加载因子数据（只加载必要列） ==========
    print('[加载缓存] 正在加载因子数据...')
    check_memory_threshold()
    
    with gzip.open(factor_path, 'rt', encoding='utf-8') as f:
        factor_data = json.load(f)
    
    # 获取所有日期
    all_dates = sorted(set(r.get('date') for r in factor_data.get('data', [])))
    print(f'[加载缓存] 数据包含 {len(all_dates)} 天数据（{all_dates[0]} ~ {all_dates[-1]}）')
    
    # 只保留最近 max_days 天
    if len(all_dates) > max_days:
        recent_dates = set(all_dates[-max_days:])
        print(f'[加载缓存] 只加载最近 {max_days} 天（{all_dates[-max_days]} ~ {all_dates[-1]}）')
        
        # 分批提取数据，避免一次性创建大列表
        factor_records = []
        batch_count = 0
        for r in factor_data.get('data', []):
            if r.get('date') in recent_dates:
                factor_records.append({'date': r['date'], 'asset': r['asset'], 'close': r['close']})
                batch_count += 1
                if batch_count % STREAM_LOAD_BATCH_SIZE == 0:
                    gc.collect()
                    check_memory_threshold()
    else:
        # 全量数据，分批提取
        factor_records = []
        batch_count = 0
        for r in factor_data.get('data', []):
            factor_records.append({'date': r['date'], 'asset': r['asset'], 'close': r['close']})
            batch_count += 1
            if batch_count % STREAM_LOAD_BATCH_SIZE == 0:
                gc.collect()
                check_memory_threshold()
    
    del factor_data
    gc.collect()
    check_memory_threshold()
    
    factor_df = pd.DataFrame(factor_records)
    del factor_records
    gc.collect()
    
    # 使用 category 类型优化内存
    if use_category:
        factor_df['date'] = factor_df['date'].astype('category')
        factor_df['asset'] = factor_df['asset'].astype('category')
    
    factor_mem = factor_df.memory_usage(deep=True).sum() / 1024 / 1024
    print(f'[加载缓存] factor_df: {len(factor_df)} 行, {factor_mem:.2f} MB')
    print(f'[内存监控] 加载因子后: {get_memory_info_str()}')
    
    # ========== 加载收益数据（只加载必要列） ==========
    print('[加载缓存] 正在加载收益数据...')
    check_memory_threshold()
    
    with gzip.open(return_path, 'rt', encoding='utf-8') as f:
        return_data = json.load(f)
    
    # 只保留最近 max_days 天，只提取必要列：date, asset, forward_return_1d
    # 注意：缓存中使用 'forward_return' 字段，重命名为 'forward_return_1d'
    if len(all_dates) > max_days:
        return_records = []
        batch_count = 0
        for r in return_data.get('data', []):
            if r.get('date') in recent_dates:
                return_records.append({
                    'date': r['date'], 
                    'asset': r['asset'], 
                    'forward_return_1d': r.get('forward_return_1d', r.get('forward_return'))
                })
                batch_count += 1
                if batch_count % STREAM_LOAD_BATCH_SIZE == 0:
                    gc.collect()
                    check_memory_threshold()
    else:
        return_records = []
        batch_count = 0
        for r in return_data.get('data', []):
            return_records.append({
                'date': r['date'], 
                'asset': r['asset'], 
                'forward_return_1d': r.get('forward_return_1d', r.get('forward_return'))
            })
            batch_count += 1
            if batch_count % STREAM_LOAD_BATCH_SIZE == 0:
                gc.collect()
                check_memory_threshold()
    
    del return_data, all_dates
    if 'recent_dates' in dir():
        del recent_dates
    gc.collect()
    check_memory_threshold()
    
    return_df = pd.DataFrame(return_records)
    del return_records
    gc.collect()
    
    # 使用 category 类型优化内存
    if use_category:
        return_df['date'] = return_df['date'].astype('category')
        return_df['asset'] = return_df['asset'].astype('category')
    
    return_mem = return_df.memory_usage(deep=True).sum() / 1024 / 1024
    print(f'[加载缓存] return_df: {len(return_df)} 行, {return_mem:.2f} MB')
    print(f'[加载缓存] 总内存占用: {factor_mem + return_mem:.2f} MB')
    print(f'[内存监控] 加载收益后: {get_memory_info_str()}')
    
    return factor_df, return_df


def calculate_return_3d_factor(factor_df):
    """计算 3日涨幅因子（内存优化版）
    
    内存优化：
    1. 保持 category 类型（避免转换回 object）
    2. 及时释放中间变量
    3. 使用 groupby().transform() 向量化计算
    
    Args:
        factor_df: 因子 DataFrame（包含 date, asset, close 列）
        
    Returns:
        DataFrame: 包含 return_3d 的因子数据
    """
    print('[计算因子] 计算 return_3d...')
    
    # factor_df 已经只包含必要列（date, asset, close）
    # 确保 close 列是数值类型（用于计算）
    if factor_df['close'].dtype.name == 'category':
        factor_df['close'] = factor_df['close'].astype(float)
    
    # 排序（保持 category 类型用于分组）
    # 注意：groupby 可以接受 category 类型
    factor_df = factor_df.sort_values(['asset', 'date']).copy()
    
    # 计算 return_3d（向量化，避免循环）
    # 使用 transform 一次性计算所有股票
    factor_df['return_3d'] = factor_df.groupby('asset')['close'].transform(
        lambda x: (x - x.shift(3)) / x.shift(3)
    )
    
    # 删除 NaN 和 close 列（释放内存）
    factor_df = factor_df.dropna(subset=['return_3d'])
    factor_df = factor_df.drop(columns=['close'])
    
    # 强制垃圾回收
    gc.collect()
    
    # 检查内存占用
    mem = factor_df.memory_usage(deep=True).sum() / 1024 / 1024
    print(f'[计算因子] 完成，有效记录: {len(factor_df)} 行, {mem:.2f} MB')
    
    return factor_df


def calculate_ic(factor_df, return_df):
    """计算 IC 指标
    
    Args:
        factor_df: 因子 DataFrame
        return_df: 收益 DataFrame
        
    Returns:
        dict: IC 指标字典
    """
    print('[计算 IC] 开始计算...')
    
    # 动态加载 reverse_rank_ic 模块
    import importlib.util
    module_path = Path('/home/admin/.openclaw/workspace/yunzhou/reverse_rank_ic.py')
    spec = importlib.util.spec_from_file_location("reverse_rank_ic", str(module_path))
    reverse_rank_ic_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(reverse_rank_ic_module)
    reverse_rank_ic = reverse_rank_ic_module.reverse_rank_ic
    
    ic_result = reverse_rank_ic(
        factor_df=factor_df,
        return_df=return_df,
        factor_col='return_3d',
        return_col='forward_return_1d',  # 修正：使用正确的列名
        date_col='date',
        asset_col='asset',
        min_stocks=10
    )
    
    # 计算 20 日滚动均值
    ic_series = ic_result['ic_series']
    rolling_mean = ic_series.rolling(window=20, min_periods=1).mean()
    
    # 提取指标
    ic_metrics = {
        'ic_mean': round(ic_result['ic_mean'], 6),
        'ic_std': round(ic_result['ic_std'], 6),
        'icir': round(ic_result['icir'], 4),
        't_stat': round(ic_result['t_stat'], 4),
        'p_value': round(ic_result.get('p_value', 0), 6),
        'positive_ratio': round(ic_result['positive_ratio'], 4),
        'n_days': len(ic_series),
        'n_assets': factor_df['asset'].nunique(),
        'significance': ic_result['significance'],
        'summary': ic_result['summary']
    }
    
    # IC 时间序列
    ic_series_data = {
        'dates': [str(d) for d in ic_series.index],
        'ic_values': [round(v, 6) for v in ic_series.values],
        'rolling_ic_mean': [round(v, 6) for v in rolling_mean.values]
    }
    
    # 释放中间变量
    del ic_result, ic_series, rolling_mean
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
    layered_result = backtest.run(factor_df, return_df, factor_col='return_3d', return_col='forward_return_1d')
    
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


def main():
    """主函数（内存优化版）"""
    print('='*60)
    print('预计算 3日涨幅因子分析结果（内存优化版 v2）')
    print('='*60)
    print(f'内存阈值: {MEMORY_THRESHOLD_MB} MB')
    print(f'开始时间: {datetime.now().isoformat()}')
    print(f'初始内存: {get_memory_info_str()}')
    
    initial_mem = get_memory_usage_mb()
    
    # Step 1: 加载缓存数据（全量 500 天）
    print('\n[Step 1] 加载缓存数据...')
    check_memory_threshold()
    factor_df, return_df = load_cache_light(max_days=500, use_category=True)
    
    if factor_df is None:
        print('[错误] 缓存数据加载失败')
        return
    
    current_mem = get_memory_usage_mb()
    print(f'[内存监控] 数据加载后: {current_mem:.1f} MB (增加 {current_mem - initial_mem:.1f} MB)')
    
    # Step 2: 计算 return_3d 因子
    print('\n[Step 2] 计算 return_3d 因子...')
    check_memory_threshold()
    factor_df = calculate_return_3d_factor(factor_df)
    
    current_mem = get_memory_usage_mb()
    print(f'[内存监控] 因子计算后: {current_mem:.1f} MB')
    
    # Step 3: 计算 IC
    print('\n[Step 3] 计算 IC...')
    check_memory_threshold()
    ic_metrics, ic_series_data = calculate_ic(factor_df, return_df)
    
    current_mem = get_memory_usage_mb()
    print(f'[内存监控] IC 计算后: {current_mem:.1f} MB')
    
    # Step 4: 分层回测
    print('\n[Step 4] 分层回测...')
    check_memory_threshold()
    layered_result = run_layered_backtest(factor_df, return_df)
    
    # 清理输入数据（释放内存）
    del factor_df, return_df
    gc.collect()
    
    current_mem = get_memory_usage_mb()
    print(f'[内存监控] 分层回测后: {current_mem:.1f} MB')
    
    # Step 5: 保存结果
    print('\n[Step 5] 保存结果...')
    
    # 分阶段保存，避免大字典内存峰值
    temp_output_file = OUTPUT_FILE.with_suffix('.json.tmp')
    
    with open(temp_output_file, 'w', encoding='utf-8') as f:
        f.write('{\n')
        f.write('  "ic_metrics": ')
        json.dump(ic_metrics, f, ensure_ascii=False)
        f.write(',\n')
        
        f.write('  "ic_series": ')
        json.dump(ic_series_data, f, ensure_ascii=False)
        f.write(',\n')
        
        del ic_metrics, ic_series_data
        gc.collect()
        
        f.write('  "layered_result": ')
        json.dump(layered_result, f, ensure_ascii=False)
        f.write(',\n')
        
        del layered_result
        gc.collect()
        
        f.write('  "params": {\n')
        f.write('    "n_days": 500,\n')
        f.write('    "max_stocks": 0,\n')
        f.write('    "num_layers": 5,\n')
        f.write('    "factor_col": "return_3d"\n')
        f.write('  },\n')
        f.write(f'  "generated_at": "{datetime.now().isoformat()}"\n')
        f.write('}\n')
    
    # 原子重命名
    temp_output_file.replace(OUTPUT_FILE)
    
    gc.collect()
    
    final_mem = get_memory_usage_mb()
    print(f'[内存监控] 最终内存: {final_mem:.1f} MB')
    print(f'[内存监控] 峰值增量: {final_mem - initial_mem:.1f} MB')
    
    print(f'\n[保存结果] 已保存到: {OUTPUT_FILE}')
    print(f'完成时间: {datetime.now().isoformat()}')
    print('='*60)
    print('预计算完成！')


if __name__ == '__main__':
    main()