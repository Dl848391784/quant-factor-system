#!/usr/bin/env python3.10
"""
预计算主力净流入占比因子数据

此脚本用于每日凌晨运行，累积存储主力净流入和流通市值数据。

运行方式：
    python precompute_main_inflow.py

建议运行时间：
    凌晨 06:30（在换手率突增之后）

功能：
1. 每日凌晨拉取当日主力净流入 + 流通市值
2. 追加到历史缓存文件 main_inflow_history.json.gz
3. 数据格式：{date, asset, main_net_inflow, float_market_cap, main_inflow_ratio}
4. 内存优化：分批处理、category类型、gc.collect()

作者: 云舟
日期: 2026-04-06
"""

import json
import os
import gc
import gzip
import tempfile
import shutil
from pathlib import Path
from datetime import datetime, timedelta
import sys

# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent))

import pandas as pd
import numpy as np

# 导入数据获取模块
from main_inflow_data_fetcher import MainInflowDataFetcher, get_stock_codes_from_cache


# ============================================================
# 配置常量
# ============================================================

BASE_DIR = Path(__file__).parent
CACHE_DIR = BASE_DIR / 'cache' / 'factor_data'
MAIN_INFLOW_CACHE_DIR = BASE_DIR / 'cache' / 'main_inflow'

# 缓存文件路径
HISTORY_FILE = MAIN_INFLOW_CACHE_DIR / 'main_inflow_history.json.gz'
DAILY_FILE = MAIN_INFLOW_CACHE_DIR / 'main_inflow_daily.json.gz'

# 批量处理配置
BATCH_SIZE = 100  # 每批股票数量
MAX_WORKERS = 2   # 并发线程数


def atomic_write_gzip(filepath: Path, data: dict):
    """
    原子写入 gzip JSON 文件
    
    先写入临时文件，成功后再重命名，防止写入中断导致文件截断
    
    Args:
        filepath: 目标文件路径
        data: 要写入的数据
    """
    # 确保目录存在
    filepath.parent.mkdir(parents=True, exist_ok=True)
    
    # 创建临时文件（在同一目录下，确保同一文件系统，支持原子重命名）
    temp_fd, temp_path = tempfile.mkstemp(
        dir=filepath.parent,
        prefix='.tmp_',
        suffix='.json.gz'
    )
    
    try:
        # 写入临时文件
        with os.fdopen(temp_fd, 'wb') as f:
            with gzip.GzipFile(fileobj=f, mode='wb') as gz:
                gz.write(json.dumps(data, ensure_ascii=False, indent=2).encode('utf-8'))
        
        # 原子重命名（同一文件系统上的 rename 是原子操作）
        shutil.move(temp_path, str(filepath))
        
    except Exception as e:
        # 出错时清理临时文件
        if os.path.exists(temp_path):
            os.unlink(temp_path)
        raise e


def load_history_data() -> dict:
    """
    加载历史主力净流入数据
    
    Returns:
        历史数据字典，包含 meta 和 data 字段
    """
    if not HISTORY_FILE.exists():
        print(f"[历史数据] 文件不存在: {HISTORY_FILE}")
        return {'meta': {'version': '1.0'}, 'data': []}
    
    try:
        with gzip.open(HISTORY_FILE, 'rt', encoding='utf-8') as f:
            data = json.load(f)
        
        print(f"[历史数据] 加载成功: {len(data.get('data', []))} 条记录")
        return data
    except Exception as e:
        print(f"[历史数据] 加载失败: {e}")
        return {'meta': {'version': '1.0'}, 'data': []}


def get_existing_dates(history_data: dict) -> set:
    """
    从历史数据中提取已有日期
    
    Args:
        history_data: 历史数据字典
        
    Returns:
        已有日期集合
    """
    existing_dates = set()
    for record in history_data.get('data', []):
        if 'date' in record:
            existing_dates.add(record['date'])
    
    return existing_dates


def fetch_daily_main_inflow(
    fetcher: MainInflowDataFetcher,
    stock_codes: list,
    target_date: str = None,
    batch_size: int = BATCH_SIZE
) -> dict:
    """
    获取指定日期的主力净流入数据
    
    Args:
        fetcher: 数据获取器
        stock_codes: 股票代码列表
        target_date: 目标日期（默认昨天）
        batch_size: 批次大小
        
    Returns:
        当日数据字典 {meta, data}
    """
    if target_date is None:
        target_date = (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d')
    
    print(f"\n{'='*60}")
    print(f"[获取主力净流入数据] 日期: {target_date}")
    print(f"{'='*60}")
    print(f"  股票数量: {len(stock_codes)}")
    print(f"  批次大小: {batch_size}")
    
    # 批量获取
    batch_data = fetcher.batch_fetch_main_inflow(stock_codes, batch_size=batch_size)
    
    # 构建数据记录
    records = []
    success_count = 0
    
    for code, data in batch_data.items():
        if data is None:
            continue
        
        # 提取关键数据
        main_net_inflow = data.get('main_net_inflow', 0)
        float_market_cap = data.get('float_market_cap', 0)
        
        # 计算主力净流入占比
        main_inflow_ratio = None
        if float_market_cap > 0 and main_net_inflow is not None:
            main_inflow_ratio = main_net_inflow / float_market_cap
        
        records.append({
            'date': target_date,
            'asset': code,
            'main_net_inflow': main_net_inflow,
            'float_market_cap': float_market_cap,
            'main_inflow_ratio': main_inflow_ratio,
            'super_net_inflow': data.get('super_net_inflow', 0),
            'big_net_inflow': data.get('big_net_inflow', 0),
            'medium_net_inflow': data.get('medium_net_inflow', 0),
            'small_net_inflow': data.get('small_net_inflow', 0)
        })
        success_count += 1
    
    # 释放内存
    del batch_data
    gc.collect()
    
    print(f"\n  ✓ 成功获取: {success_count}/{len(stock_codes)} 只股票")
    
    return {
        'meta': {
            'date': target_date,
            'source': 'eastmoney_api',
            'total_count': success_count,
            'generated_at': datetime.now().isoformat()
        },
        'data': records
    }


def append_to_history(history_data: dict, daily_data: dict) -> dict:
    """
    将当日数据追加到历史数据
    
    Args:
        history_data: 历史数据
        daily_data: 当日数据
        
    Returns:
        更新后的历史数据
    """
    # 获取已有日期
    existing_dates = get_existing_dates(history_data)
    new_date = daily_data['meta']['date']
    
    if new_date in existing_dates:
        print(f"[追加数据] 日期 {new_date} 已存在，跳过追加")
        return history_data
    
    # 追加新数据
    history_data['data'].extend(daily_data['data'])
    
    # 更新元数据
    history_data['meta']['total_count'] = len(history_data['data'])
    history_data['meta']['last_updated'] = datetime.now().isoformat()
    history_data['meta']['dates'] = sorted(set(r['date'] for r in history_data['data']))
    
    print(f"[追加数据] 成功追加 {len(daily_data['data'])} 条记录，日期: {new_date}")
    
    return history_data


def run_precompute_main_inflow(
    days: int = 1,
    overwrite: bool = False
):
    """
    执行主力净流入数据预计算
    
    Args:
        days: 获取天数（默认1天，获取昨天数据）
        overwrite: 是否覆盖历史数据（默认False，追加模式）
    """
    print(f"\n{'='*80}")
    print("主力净流入占比因子数据预计算")
    print(f"{'='*80}")
    print(f"开始时间: {datetime.now().isoformat()}")
    
    # 内存监控
    try:
        import psutil
        process = psutil.Process()
        initial_mem = process.memory_info().rss / 1024 / 1024
        print(f"初始内存: {initial_mem:.2f} MB")
        has_psutil = True
    except ImportError:
        has_psutil = False
    
    # 确保缓存目录存在
    MAIN_INFLOW_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    
    # 加载股票代码
    stock_codes = get_stock_codes_from_cache()
    
    if not stock_codes:
        print("[错误] 未获取到股票代码，请先运行 stock_cache.py")
        return
    
    # 创建数据获取器
    fetcher = MainInflowDataFetcher(
        timeout=30,
        retries=3,
        enable_cache=True
    )
    
    # 加载历史数据
    if overwrite:
        history_data = {'meta': {'version': '1.0'}, 'data': []}
        print("[模式] 覆盖模式：重新获取所有数据")
    else:
        history_data = load_history_data()
        print("[模式] 追加模式：追加新数据到历史文件")
    
    # 获取指定天数的数据
    for i in range(days):
        target_date = (datetime.now() - timedelta(days=i+1)).strftime('%Y-%m-%d')
        
        # 检查是否已有该日期数据
        if not overwrite and target_date in get_existing_dates(history_data):
            print(f"\n[跳过] 日期 {target_date} 数据已存在")
            continue
        
        # 获取当日数据
        daily_data = fetch_daily_main_inflow(
            fetcher,
            stock_codes,
            target_date=target_date
        )
        
        # 追加到历史数据
        history_data = append_to_history(history_data, daily_data)
        
        # 清理内存
        del daily_data
        gc.collect()
    
    # 保存历史数据
    print(f"\n[保存] 写入历史文件: {HISTORY_FILE}")
    atomic_write_gzip(HISTORY_FILE, history_data)
    
    # 统计
    total_records = len(history_data['data'])
    unique_dates = len(history_data['meta'].get('dates', []))
    
    print(f"\n{'='*80}")
    print("预计算完成")
    print(f"{'='*80}")
    print(f"  总记录数: {total_records:,}")
    print(f"  日期数: {unique_dates}")
    print(f"  完成时间: {datetime.now().isoformat()}")
    
    if has_psutil:
        final_mem = process.memory_info().rss / 1024 / 1024
        print(f"  最终内存: {final_mem:.2f} MB (增量: {final_mem - initial_mem:.2f} MB)")
    
    # 释放内存
    del history_data, fetcher
    gc.collect()


def backfill_history_data(
    start_date: str,
    end_date: str,
    stock_codes: list = None
):
    """
    回填历史数据（补全缺失日期）
    
    Args:
        start_date: 开始日期 (YYYY-MM-DD)
        end_date: 结束日期 (YYYY-MM-DD)
        stock_codes: 股票代码列表（可选，默认从缓存获取）
    """
    print(f"\n{'='*80}")
    print("主力净流入历史数据回填")
    print(f"{'='*80}")
    print(f"  日期范围: {start_date} ~ {end_date}")
    
    # 加载股票代码
    if stock_codes is None:
        stock_codes = get_stock_codes_from_cache()
    
    if not stock_codes:
        print("[错误] 未获取到股票代码")
        return
    
    # 加载历史数据
    history_data = load_history_data()
    existing_dates = get_existing_dates(history_data)
    
    # 创建数据获取器
    fetcher = MainInflowDataFetcher(timeout=30, retries=3, enable_cache=True)
    
    # 计算需要回填的日期
    start_dt = datetime.strptime(start_date, '%Y-%m-%d')
    end_dt = datetime.strptime(end_date, '%Y-%m-%d')
    
    dates_to_fetch = []
    current_dt = start_dt
    while current_dt <= end_dt:
        date_str = current_dt.strftime('%Y-%m-%d')
        # 只获取工作日（跳过周末）
        if current_dt.weekday() < 5 and date_str not in existing_dates:
            dates_to_fetch.append(date_str)
        current_dt += timedelta(days=1)
    
    print(f"  需要回填日期数: {len(dates_to_fetch)}")
    
    if not dates_to_fetch:
        print("  无需回填，所有日期数据已存在")
        return
    
    # 批量获取历史数据（使用 AKShare 或东方财富 API）
    # 由于主力净流入数据获取较慢，建议分批处理
    for i, target_date in enumerate(dates_to_fetch):
        print(f"\n[{i+1}/{len(dates_to_fetch)}] 获取日期: {target_date}")
        
        # 获取当日数据
        daily_data = fetch_daily_main_inflow(
            fetcher,
            stock_codes,
            target_date=target_date,
            batch_size=100
        )
        
        # 追加到历史数据
        history_data = append_to_history(history_data, daily_data)
        
        # 每获取5天保存一次（防止数据丢失）
        if (i + 1) % 5 == 0:
            atomic_write_gzip(HISTORY_FILE, history_data)
            print(f"  [保存] 已保存中间结果")
        
        # 清理内存
        del daily_data
        gc.collect()
    
    # 最终保存
    atomic_write_gzip(HISTORY_FILE, history_data)
    
    print(f"\n{'='*80}")
    print("回填完成")
    print(f"{'='*80}")


if __name__ == '__main__':
    import argparse
    
    parser = argparse.ArgumentParser(description='主力净流入数据预计算')
    parser.add_argument('--days', type=int, default=1, help='获取天数（默认1天）')
    parser.add_argument('--overwrite', action='store_true', help='覆盖历史数据')
    parser.add_argument('--backfill', nargs=2, metavar=('START', 'END'), 
                        help='回填历史数据（指定日期范围）')
    
    args = parser.parse_args()
    
    if args.backfill:
        backfill_history_data(args.backfill[0], args.backfill[1])
    else:
        run_precompute_main_inflow(days=args.days, overwrite=args.overwrite)