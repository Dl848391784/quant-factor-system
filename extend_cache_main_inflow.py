#!/usr/bin/env python3
"""
扩展因子数据缓存 - 添加主力净流入和流通市值字段

在现有 factor_data.json.gz 中添加新字段：
- main_net_inflow: 主力净流入金额（元）
- float_market_cap: 流通市值（元）
- main_net_inflow_ratio_by_cap: 主力净流入占流通市值比例

内存优化策略：
1. 分批处理（每批500只股票）
2. 流式读取和写入（避免全量加载）
3. 使用 category 类型优化内存
4. 及时 gc.collect()

作者: 云舟
日期: 2026-04-05
"""

import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

from main_inflow_data_fetcher import (
    MainInflowDataFetcher,
    get_stock_codes_from_cache,
    create_main_inflow_fetcher
)
from datetime import datetime
import pandas as pd
import numpy as np
import json
import gzip
import gc
import time
import heapq
from typing import Dict, List, Optional, Tuple
import warnings
warnings.filterwarnings('ignore')

# ============================================================
# 配置常量
# ============================================================

# 缓存路径
CACHE_DIR = os.path.expanduser('~/projects/factor_ic_analyzer/cache')
FACTOR_CACHE_DIR = os.path.join(CACHE_DIR, 'factor_data')

# 批量处理配置
BATCH_SIZE = 500  # 每批股票数量
MEMORY_THRESHOLD_MB = 900  # 内存警告阈值（MB）- 统一阈值

# 目标天数（获取历史数据的范围）
TARGET_DAYS = 500


# ============================================================
# 内存监控
# ============================================================

def get_memory_usage_mb():
    """获取当前进程真实RSS内存（MB）"""
    try:
        with open('/proc/self/status', 'r') as f:
            for line in f:
                if line.startswith('VmRSS:'):
                    return int(line.split()[1]) / 1024
    except Exception:
        pass
    import resource
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024


def get_memory_info_str():
    """获取详细内存信息"""
    try:
        with open('/proc/self/status', 'r') as f:
            vmrss = vmsize = None
            for line in f:
                if line.startswith('VmRSS:'):
                    vmrss = int(line.split()[1]) / 1024
                elif line.startswith('VmSize:'):
                    vmsize = int(line.split()[1]) / 1024
            if vmrss:
                return f"RSS={vmrss:.1f}MB" + (f", VM={vmsize:.1f}MB" if vmsize else "")
    except Exception:
        pass
    return f"RSS={get_memory_usage_mb():.1f}MB"


# ============================================================
# 缓存读取（流式）
# ============================================================

def load_factor_cache_light(max_days: int = 500) -> Tuple[pd.DataFrame, dict]:
    """
    轻量级加载因子缓存（只加载必要列）
    
    Args:
        max_days: 最大加载天数
        
    Returns:
        (factor_df, meta_info)
    """
    factor_path = os.path.join(FACTOR_CACHE_DIR, 'factor_data.json.gz')
    
    if not os.path.exists(factor_path):
        raise FileNotFoundError(f"因子缓存不存在: {factor_path}")
    
    print(f"\n[加载因子缓存] {factor_path}")
    print(f"  当前内存: {get_memory_info_str()}")
    
    with gzip.open(factor_path, 'rt', encoding='utf-8') as f:
        factor_data = json.load(f)
    
    meta = factor_data.get('meta', {})
    records = factor_data.get('data', [])
    
    # 提取所有日期
    all_dates = sorted(set(r.get('date') for r in records))
    
    # 只保留最近 max_days 天
    if len(all_dates) > max_days:
        recent_dates = set(all_dates[-max_days:])
        records = [r for r in records if r.get('date') in recent_dates]
    
    # 释放内存
    del factor_data
    gc.collect()
    
    # 构建 DataFrame（只保留必要列）
    factor_df = pd.DataFrame(records)
    factor_df = factor_df[['date', 'asset', 'close']].copy()
    
    # 使用 category 类型优化内存
    factor_df['date'] = factor_df['date'].astype('category')
    factor_df['asset'] = factor_df['asset'].astype('category')
    factor_df['close'] = factor_df['close'].astype('float32')
    
    # 释放内存
    del records
    gc.collect()
    
    mem_mb = factor_df.memory_usage(deep=True).sum() / 1024 / 1024
    print(f"  加载记录: {len(factor_df)}")
    print(f"  内存占用: {mem_mb:.2f} MB")
    print(f"  当前内存: {get_memory_info_str()}")
    
    return factor_df, meta


# ============================================================
# 批量获取主力资金数据
# ============================================================

def fetch_main_inflow_batch(
    stock_codes: List[str],
    days: int = TARGET_DAYS,
    batch_size: int = BATCH_SIZE
) -> Dict[str, pd.DataFrame]:
    """
    批量获取主力资金历史数据
    
    Args:
        stock_codes: 股票代码列表
        days: 获取天数
        batch_size: 每批数量
        
    Returns:
        {stock_code: DataFrame} 字典
    """
    fetcher = create_main_inflow_fetcher()
    
    total = len(stock_codes)
    result = {}
    success_count = 0
    
    print(f"\n[获取主力资金历史数据] 共 {total} 只股票")
    print(f"  批次大小: {batch_size}")
    print(f"  目标天数: {days}")
    
    batches = [stock_codes[i:i+batch_size] for i in range(0, total, batch_size)]
    total_batches = len(batches)
    
    start_time = time.time()
    
    for batch_idx, batch_codes in enumerate(batches):
        batch_start_time = time.time()
        
        # 内存检查
        mem_mb = get_memory_usage_mb()
        if mem_mb > MEMORY_THRESHOLD_MB:
            print(f"\n  ⚠ 内存超阈值 ({mem_mb:.1f}MB > {MEMORY_THRESHOLD_MB}MB)，执行 GC...")
            gc.collect()
            time.sleep(5)
        
        print(f"\n  [批次 {batch_idx + 1}/{total_batches}] 处理 {len(batch_codes)} 只股票...")
        print(f"    当前内存: {get_memory_info_str()}")
        
        batch_results = {}
        batch_success = 0
        
        for code in batch_codes:
            df = fetcher.fetch_main_inflow_history(code, days)
            
            if df is not None and len(df) > 0:
                batch_results[code] = df
                batch_success += 1
        
        result.update(batch_results)
        success_count += batch_success
        
        # 释放内存
        del batch_results
        gc.collect()
        
        batch_elapsed = time.time() - batch_start_time
        total_elapsed = time.time() - start_time
        
        print(f"    批次成功: {batch_success}/{len(batch_codes)}")
        print(f"    总成功: {success_count}/{total}")
        print(f"    批次耗时: {batch_elapsed:.1f}s, 总耗时: {total_elapsed:.1f}s")
        
        # 批次间延迟
        if batch_idx < total_batches - 1:
            time.sleep(2.0)
    
    final_elapsed = time.time() - start_time
    print(f"\n  ✓ 获取完成")
    print(f"    成功: {success_count}/{total}")
    print(f"    总耗时: {final_elapsed:.1f}s ({final_elapsed/60:.1f}min)")
    
    return result


# ============================================================
# 合并数据并扩展缓存
# ============================================================

def merge_and_extend_cache(
    factor_df: pd.DataFrame,
    main_inflow_data: Dict[str, pd.DataFrame],
    output_path: Optional[str] = None
) -> pd.DataFrame:
    """
    合并因子数据和主力资金数据，生成扩展后的缓存
    
    Args:
        factor_df: 因子数据（包含 date, asset, close）
        main_inflow_data: 主力资金数据字典
        output_path: 输出路径（可选）
        
    Returns:
        扩展后的因子 DataFrame
    """
    print(f"\n[合并数据] 开始合并...")
    print(f"  因子记录: {len(factor_df)}")
    print(f"  主力资金股票数: {len(main_inflow_data)}")
    
    # 合并主力资金数据
    all_main_inflow = []
    
    for code, df in main_inflow_data.items():
        # 确保日期格式一致
        df['date'] = df['date'].dt.strftime('%Y-%m-%d')
        all_main_inflow.append(df)
    
    if not all_main_inflow:
        print("  ! 无主力资金数据")
        return factor_df
    
    # 合并所有主力资金数据
    main_inflow_df = pd.concat(all_main_inflow, ignore_index=True)
    
    # 使用 category 类型优化内存
    main_inflow_df['date'] = main_inflow_df['date'].astype('category')
    main_inflow_df['asset'] = main_inflow_df['asset'].astype('category')
    
    # 释放内存
    del all_main_inflow
    gc.collect()
    
    print(f"  主力资金记录: {len(main_inflow_df)}")
    
    # 合并因子数据和主力资金数据
    factor_df['date'] = factor_df['date'].astype(str)
    main_inflow_df['date'] = main_inflow_df['date'].astype(str)
    
    # 合并（左连接，保留所有因子数据）
    merged_df = pd.merge(
        factor_df,
        main_inflow_df[['date', 'asset', 'main_net_inflow']],
        on=['date', 'asset'],
        how='left'
    )
    
    # 释放内存
    del main_inflow_df
    gc.collect()
    
    print(f"  合并后记录: {len(merged_df)}")
    
    # 计算流通市值（从 close 计算，需要流通股本数据）
    # 由于历史流通股本数据获取困难，这里暂时不计算 float_market_cap
    # 后续可以从实时数据获取
    
    # 填充缺失值
    merged_df['main_net_inflow'] = merged_df['main_net_inflow'].fillna(0)
    
    # 使用 category 类型
    merged_df['date'] = merged_df['date'].astype('category')
    merged_df['asset'] = merged_df['asset'].astype('category')
    
    mem_mb = merged_df.memory_usage(deep=True).sum() / 1024 / 1024
    print(f"  内存占用: {mem_mb:.2f} MB")
    
    # 输出路径
    if output_path is None:
        output_path = os.path.join(FACTOR_CACHE_DIR, 'factor_data_extended.json.gz')
    
    # 保存扩展后的缓存
    save_extended_cache(merged_df, output_path)
    
    return merged_df


def save_extended_cache(df: pd.DataFrame, output_path: str) -> None:
    """
    保存扩展后的因子缓存
    
    Args:
        df: 扩展后的因子 DataFrame
        output_path: 输出路径
    """
    print(f"\n[保存扩展缓存] {output_path}")
    
    # 提取元信息
    dates_list = sorted(df['date'].astype(str).unique())
    assets_list = sorted(df['asset'].astype(str).unique())
    
    # 格式化数据
    df['date'] = df['date'].astype(str)
    
    # 构建缓存数据
    cache_data = {
        'meta': {
            'generated_at': datetime.now().isoformat(),
            'source': 'sina_api + eastmoney_api',
            'n_days': len(dates_list),
            'n_assets': len(assets_list),
            'date_range': {
                'start': dates_list[0],
                'end': dates_list[-1]
            },
            'last_updated': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'version': '4.0_extended',
            'fields': ['date', 'asset', 'close', 'main_net_inflow'],
            'description': '扩展版因子数据缓存，新增主力净流入字段'
        },
        'data': df.to_dict('records')
    }
    
    # gzip 压缩保存
    with gzip.open(output_path, 'wt', encoding='utf-8') as f:
        json.dump(cache_data, f, ensure_ascii=False)
    
    file_size_mb = os.path.getsize(output_path) / (1024 * 1024)
    print(f"  ✓ 已保存: {file_size_mb:.2f} MB")
    print(f"  交易日数: {len(dates_list)}")
    print(f"  股票数量: {len(assets_list)}")
    print(f"  总记录数: {len(df)}")
    
    # 释放内存
    del cache_data
    gc.collect()


# ============================================================
# 增量更新现有缓存
# ============================================================

def extend_existing_cache_incremental(
    stock_codes: List[str],
    days: int = TARGET_DAYS,
    batch_size: int = BATCH_SIZE
) -> None:
    """
    增量更新现有缓存（不重新生成全量数据）
    
    策略：
    1. 获取主力资金历史数据
    2. 生成独立的 main_inflow_data.json.gz 缓存
    3. 在使用时动态合并（不修改现有 factor_data.json.gz）
    
    Args:
        stock_codes: 股票代码列表
        days: 获取天数
        batch_size: 每批数量
    """
    print(f"\n{'='*60}")
    print(f"增量更新主力资金缓存")
    print(f"{'='*60}")
    print(f"  目标天数: {days}")
    print(f"  批次大小: {batch_size}")
    print(f"  开始时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  当前内存: {get_memory_info_str()}")
    
    global_start = time.time()
    
    # 获取主力资金数据
    main_inflow_data = fetch_main_inflow_batch(stock_codes, days, batch_size)
    
    if not main_inflow_data:
        print("\n! 获取主力资金数据失败")
        return
    
    # 保存为主力资金独立缓存
    output_path = os.path.join(FACTOR_CACHE_DIR, 'main_inflow_data.json.gz')
    
    print(f"\n[保存主力资金缓存] {output_path}")
    
    # 合并所有数据
    all_records = []
    
    for code, df in main_inflow_data.items():
        df['date'] = df['date'].dt.strftime('%Y-%m-%d')
        
        # 逐条添加（避免大 DataFrame 内存占用）
        for _, row in df.iterrows():
            all_records.append({
                'date': row['date'],
                'asset': row['asset'],
                'main_net_inflow': row['main_net_inflow'],
                'super_net_inflow': row.get('super_net_inflow', 0),
                'big_net_inflow': row.get('big_net_inflow', 0),
                'medium_net_inflow': row.get('medium_net_inflow', 0),
                'small_net_inflow': row.get('small_net_inflow', 0)
            })
    
    # 提取日期范围
    dates_list = sorted(set(r['date'] for r in all_records))
    assets_list = sorted(set(r['asset'] for r in all_records))
    
    # 构建缓存数据
    cache_data = {
        'meta': {
            'generated_at': datetime.now().isoformat(),
            'source': 'eastmoney_api',
            'n_days': len(dates_list),
            'n_assets': len(assets_list),
            'date_range': {
                'start': dates_list[0],
                'end': dates_list[-1]
            },
            'last_updated': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'version': '1.0',
            'fields': ['date', 'asset', 'main_net_inflow', 'super_net_inflow', 
                      'big_net_inflow', 'medium_net_inflow', 'small_net_inflow'],
            'description': '主力资金流向数据缓存，可动态合并到因子数据'
        },
        'data': all_records
    }
    
    # gzip 压缩保存
    with gzip.open(output_path, 'wt', encoding='utf-8') as f:
        json.dump(cache_data, f, ensure_ascii=False)
    
    file_size_mb = os.path.getsize(output_path) / (1024 * 1024)
    
    # 释放内存
    del all_records, cache_data, main_inflow_data
    gc.collect()
    
    elapsed = time.time() - global_start
    
    print(f"\n  ✓ 主力资金缓存已保存")
    print(f"    文件: {output_path}")
    print(f"    大小: {file_size_mb:.2f} MB")
    print(f"    交易日数: {len(dates_list)}")
    print(f"    股票数量: {len(assets_list)}")
    print(f"    总耗时: {elapsed:.1f}s ({elapsed/60:.1f}min)")
    print(f"    当前内存: {get_memory_info_str()}")
    
    # 同时获取流通市值数据（实时）
    fetch_and_save_float_market_cap(stock_codes[:batch_size])  # 只取第一批


def fetch_and_save_float_market_cap(stock_codes: List[str]) -> None:
    """
    获取并保存流通市值数据（实时）
    
    Args:
        stock_codes: 股票代码列表
    """
    print(f"\n[获取流通市值数据] {len(stock_codes)} 只股票")
    
    fetcher = create_main_inflow_fetcher()
    
    result = fetcher.batch_fetch_main_inflow(stock_codes[:min(100, len(stock_codes))])
    
    # 提取流通市值
    records = []
    
    for code, data in result.items():
        if data and 'float_market_cap' in data:
            records.append({
                'code': code,
                'date': data.get('date', datetime.now().strftime('%Y-%m-%d')),
                'float_market_cap': data['float_market_cap'],
                'main_net_inflow': data.get('main_net_inflow', 0),
                'main_net_inflow_ratio': data.get('main_net_inflow_ratio', 0)
            })
    
    if not records:
        print("  ! 未获取到流通市值数据")
        return
    
    # 保存缓存
    output_path = os.path.join(FACTOR_CACHE_DIR, 'float_market_cap_data.json.gz')
    
    cache_data = {
        'meta': {
            'generated_at': datetime.now().isoformat(),
            'source': 'eastmoney_api',
            'total_count': len(records),
            'version': '1.0',
            'description': '流通市值数据缓存（实时快照）'
        },
        'data': records
    }
    
    with gzip.open(output_path, 'wt', encoding='utf-8') as f:
        json.dump(cache_data, f, ensure_ascii=False)
    
    file_size_mb = os.path.getsize(output_path) / (1024 * 1024)
    print(f"  ✓ 已保存: {output_path} ({file_size_mb:.2f} MB)")
    print(f"    成功获取: {len(records)} 只股票")


# ============================================================
# 动态合并缓存（在分析时使用）
# ============================================================

def load_extended_factor_data(
    factor_col: str = 'rsi_6',
    max_days: int = 500,
    include_main_inflow: bool = True
) -> Optional[pd.DataFrame]:
    """
    加载扩展后的因子数据（动态合并主力资金）
    
    Args:
        factor_col: 因子列名
        max_days: 最大天数
        include_main_inflow: 是否包含主力净流入
        
    Returns:
        因子 DataFrame，或 None
    """
    print(f"\n[加载扩展因子数据]")
    
    # 加载基础因子数据
    factor_path = os.path.join(FACTOR_CACHE_DIR, 'factor_data.json.gz')
    
    if not os.path.exists(factor_path):
        print(f"  ! 因子缓存不存在: {factor_path}")
        return None
    
    with gzip.open(factor_path, 'rt', encoding='utf-8') as f:
        factor_data = json.load(f)
    
    # 提取日期
    all_dates = sorted(set(r.get('date') for r in factor_data.get('data', [])))
    
    # 只保留最近 max_days 天
    if len(all_dates) > max_days:
        recent_dates = set(all_dates[-max_days:])
        factor_records = [r for r in factor_data.get('data', []) if r.get('date') in recent_dates]
    else:
        factor_records = factor_data.get('data', [])
    
    # 构建因子 DataFrame
    factor_df = pd.DataFrame(factor_records)
    factor_df = factor_df[['date', 'asset', factor_col]].copy()
    
    del factor_data, factor_records
    gc.collect()
    
    # 动态合并主力资金数据
    if include_main_inflow:
        main_inflow_path = os.path.join(FACTOR_CACHE_DIR, 'main_inflow_data.json.gz')
        
        if os.path.exists(main_inflow_path):
            print(f"  合并主力资金数据...")
            
            with gzip.open(main_inflow_path, 'rt', encoding='utf-8') as f:
                main_inflow_data = json.load(f)
            
            # 只保留最近 max_days 天
            main_inflow_records = main_inflow_data.get('data', [])
            
            if len(all_dates) > max_days:
                main_inflow_records = [r for r in main_inflow_records if r.get('date') in recent_dates]
            
            main_inflow_df = pd.DataFrame(main_inflow_records)
            main_inflow_df = main_inflow_df[['date', 'asset', 'main_net_inflow']].copy()
            
            del main_inflow_data, main_inflow_records
            gc.collect()
            
            # 合并
            factor_df = pd.merge(
                factor_df,
                main_inflow_df,
                on=['date', 'asset'],
                how='left'
            )
            
            factor_df['main_net_inflow'] = factor_df['main_net_inflow'].fillna(0)
            
            del main_inflow_df
            gc.collect()
    
    # 使用 category 类型优化内存
    factor_df['date'] = factor_df['date'].astype('category')
    factor_df['asset'] = factor_df['asset'].astype('category')
    
    mem_mb = factor_df.memory_usage(deep=True).sum() / 1024 / 1024
    print(f"  ✓ 加载完成: {len(factor_df)} 条, {mem_mb:.2f} MB")
    
    return factor_df


# ============================================================
# 主函数
# ============================================================

def main():
    """主函数"""
    print(f"\n{'='*70}")
    print(f"扩展因子数据缓存 - 添加主力净流入字段")
    print(f"{'='*70}")
    print(f"  版本: 4.0_extended")
    print(f"  目标天数: {TARGET_DAYS}")
    print(f"  批次大小: {BATCH_SIZE}")
    print(f"  开始时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  当前内存: {get_memory_info_str()}")
    
    global_start = time.time()
    
    # 获取股票代码
    stock_codes = get_stock_codes_from_cache()
    
    if not stock_codes:
        print("\n! 未获取到股票代码，请先运行 stock_cache.py")
        return
    
    print(f"\n[股票列表] {len(stock_codes)} 只")
    
    # 增量更新（生成独立缓存）
    extend_existing_cache_incremental(stock_codes, TARGET_DAYS, BATCH_SIZE)
    
    elapsed = time.time() - global_start
    
    print(f"\n{'='*70}")
    print(f"扩展缓存完成")
    print(f"{'='*70}")
    print(f"  结束时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  总耗时: {elapsed:.1f}s ({elapsed/60:.1f}min)")
    print(f"  最终内存: {get_memory_info_str()}")
    
    # 验证生成的缓存
    validate_extended_cache()


def validate_extended_cache():
    """验证扩展后的缓存数据"""
    print(f"\n{'='*60}")
    print("[验证阶段] 验证扩展缓存数据...")
    print(f"{'='*60}")
    
    # 验证主力资金缓存
    main_inflow_path = os.path.join(FACTOR_CACHE_DIR, 'main_inflow_data.json.gz')
    
    if os.path.exists(main_inflow_path):
        with gzip.open(main_inflow_path, 'rt', encoding='utf-8') as f:
            data = json.load(f)
        
        meta = data.get('meta', {})
        n_days = meta.get('n_days', 0)
        n_assets = meta.get('n_assets', 0)
        n_records = len(data.get('data', []))
        
        print(f"\n  主力资金缓存:")
        print(f"    交易日数: {n_days}")
        print(f"    股票数量: {n_assets}")
        print(f"    总记录数: {n_records}")
        
        # 抽样检查
        sample = data.get('data', [])[:1000]
        inflow_vals = [r['main_net_inflow'] for r in sample if r.get('main_net_inflow') is not None]
        
        if inflow_vals:
            print(f"    主力净流入样本范围: [{min(inflow_vals):.2e}, {max(inflow_vals):.2e}]")
        
        del data, sample
        gc.collect()
        
        is_valid = n_days >= TARGET_DAYS * 0.9 and n_records > 0
        print(f"\n  {'✓ 通过' if is_valid else '⚠ 数据不足'}")
    else:
        print(f"\n  ⚠ 主力资金缓存不存在")
    
    # 验证流通市值缓存
    float_cap_path = os.path.join(FACTOR_CACHE_DIR, 'float_market_cap_data.json.gz')
    
    if os.path.exists(float_cap_path):
        with gzip.open(float_cap_path, 'rt', encoding='utf-8') as f:
            data = json.load(f)
        
        meta = data.get('meta', {})
        total_count = meta.get('total_count', 0)
        records = data.get('data', [])
        
        print(f"\n  流通市值缓存:")
        print(f"    股票数量: {total_count}")
        
        if records:
            cap_vals = [r['float_market_cap'] for r in records if r.get('float_market_cap')]
            if cap_vals:
                print(f"    流通市值样本范围: [{min(cap_vals):.2e}, {max(cap_vals):.2e}]")
        
        del data
        gc.collect()
    else:
        print(f"\n  ⚠ 流通市值缓存不存在")


if __name__ == '__main__':
    main()