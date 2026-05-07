#!/usr/bin/env python3
"""
历史换手率数据拉取脚本（使用 baostock 数据源）- 优化版

优化：只登录一次 baostock，查询所有股票后再登出，速度提升约8倍。

缓存路径：cache/factor_data/turnover_rate_data.json.gz

作者: 云舟
日期: 2026-04-08
"""

import sys
import os
import gzip
import json
import time
import argparse
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Dict, List, Set, Tuple
import baostock as bs

# 缓存目录
CACHE_DIR = Path('/home/admin/.openclaw/workspace/yunzhou/factor_ic_analyzer/cache')
FACTOR_DATA_DIR = CACHE_DIR / 'factor_data'
CACHE_FILE = FACTOR_DATA_DIR / 'turnover_rate_data.json.gz'
STOCK_LIST_FILE = CACHE_DIR / 'stock_list.json'

# 默认参数
DEFAULT_N_DAYS = 500
DEFAULT_DELAY = 0.1  # 优化后可使用更短的延迟
DEFAULT_MAX_RETRIES = 3

# 限速控制参数
CONSECUTIVE_FAILURE_THRESHOLD = 5
CONSECUTIVE_FAILURE_PAUSE = 30
INTERMEDIATE_SAVE_INTERVAL = 100


def load_stock_list() -> List[Dict]:
    """从缓存加载主板股票列表"""
    if not STOCK_LIST_FILE.exists():
        raise FileNotFoundError(f"股票列表缓存不存在: {STOCK_LIST_FILE}")
    
    with open(STOCK_LIST_FILE, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    stocks = data.get('stocks', [])
    main_board_stocks = []
    for stock in stocks:
        code = stock.get('code', '')
        name = stock.get('name', '')
        if code.startswith('30') or code.startswith('688') or code.startswith('8') or code.startswith('4'):
            continue
        if 'ST' in name or '退市' in name or '*ST' in name:
            continue
        if code.startswith('60') or code.startswith('00'):
            main_board_stocks.append(stock)
    return main_board_stocks


def load_cache() -> Optional[Dict]:
    """加载现有换手率缓存"""
    if not CACHE_FILE.exists():
        return None
    try:
        with gzip.open(CACHE_FILE, 'rt', encoding='utf-8') as f:
            data = json.load(f)
        file_size = CACHE_FILE.stat().st_size
        size_mb = file_size / (1024 * 1024)
        print(f"[缓存] 已读取: {CACHE_FILE} ({size_mb:.2f} MB)")
        return data
    except Exception as e:
        print(f"[缓存] 读取失败: {e}")
        return None


def get_existing_stocks(cache_data: Optional[Dict]) -> Set[str]:
    """从缓存中获取已有数据的股票代码集合"""
    if not cache_data:
        return set()
    data = cache_data.get('data', [])
    return set(record['asset'] for record in data)


def save_cache(data: Dict) -> None:
    """
    使用 gzip 压缩保存缓存文件
    
    先写入临时文件，确保写入完成后再移动到目标文件，避免写入中断导致文件损坏。
    """
    FACTOR_DATA_DIR.mkdir(parents=True, exist_ok=True)
    
    # 先写入临时文件
    temp_file = CACHE_FILE.with_suffix('.json.gz.tmp')
    with gzip.open(temp_file, 'wt', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    
    # 确保写入完成后再移动
    temp_file.replace(CACHE_FILE)
    
    file_size = CACHE_FILE.stat().st_size
    size_mb = file_size / (1024 * 1024)
    print(f"[缓存] 已保存: {CACHE_FILE} ({size_mb:.2f} MB)")


def get_baostock_code(stock_code: str) -> str:
    """根据股票代码转换为 baostock 格式"""
    if stock_code.startswith('6'):
        return f'sh.{stock_code}'
    else:
        return f'sz.{stock_code}'


def fetch_stock_history_baostock(stock_code: str, start_date: str, end_date: str,
                                   retries: int = DEFAULT_MAX_RETRIES) -> Tuple[Optional[List[Dict]], bool]:
    """
    使用 baostock 拉取单只股票的历史换手率数据
    注意：此函数假设 baostock 已经登录
    """
    bs_code = get_baostock_code(stock_code)
    
    for attempt in range(retries):
        try:
            rs = bs.query_history_k_data_plus(
                bs_code,
                'date,code,turn',
                start_date=start_date,
                end_date=end_date,
                frequency='d',
                adjustflag='3'
            )
            
            if rs.error_code != '0':
                if attempt < retries - 1:
                    time.sleep(2 ** attempt)
                    continue
                return (None, False)
            
            data_list = []
            while rs.next():
                data_list.append(rs.get_row_data())
            
            if not data_list:
                return ([], True)
            
            records = []
            for row in data_list:
                date_str = row[0]
                turn_str = row[2]
                try:
                    turnover_rate = float(turn_str)
                    records.append({
                        'date': date_str,
                        'asset': stock_code,
                        'turnover_rate': turnover_rate
                    })
                except (ValueError, TypeError):
                    continue
            
            return (records, True)
            
        except Exception as e:
            if attempt < retries - 1:
                wait_time = 2 ** attempt
                print(f"\n    ⚠ {stock_code} 请求失败，等待{wait_time}秒后重试...")
                time.sleep(wait_time)
            else:
                return (None, False)
    
    return (None, False)


def merge_records(existing_data: Optional[Dict], new_records: List[Dict]) -> Dict:
    """合并现有数据和新数据"""
    existing_records = []
    if existing_data:
        existing_records = existing_data.get('data', [])
    
    all_records = existing_records + new_records
    
    record_map = {}
    for record in all_records:
        key = (record['date'], record['asset'])
        record_map[key] = record
    
    merged_records = list(record_map.values())
    merged_records.sort(key=lambda x: (x['date'], x['asset']))
    
    unique_dates = sorted(set(r['date'] for r in merged_records))
    unique_assets = sorted(set(r['asset'] for r in merged_records))
    
    now = datetime.now()
    
    return {
        'meta': {
            'generated_at': now.isoformat(),
            'source': 'baostock',
            'n_days': len(unique_dates),
            'n_assets': len(unique_assets),
            'date_range': {
                'start': unique_dates[0] if unique_dates else None,
                'end': unique_dates[-1] if unique_dates else None
            },
            'last_updated': now.strftime('%Y-%m-%d %H:%M:%S'),
            'version': '1.2'
        },
        'data': merged_records
    }


def format_time(seconds: float) -> str:
    """格式化时间为 HH:MM:SS"""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


def main():
    """主函数"""
    parser = argparse.ArgumentParser(description='拉取历史换手率数据（baostock优化版）')
    parser.add_argument('--n_days', type=int, default=DEFAULT_N_DAYS)
    parser.add_argument('--max_stocks', type=int, default=0)
    parser.add_argument('--delay', type=float, default=DEFAULT_DELAY)
    parser.add_argument('--retries', type=int, default=DEFAULT_MAX_RETRIES)
    parser.add_argument('--full', action='store_true')
    args = parser.parse_args()
    
    print("=" * 70)
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 开始拉取历史换手率数据（优化版）")
    print("=" * 70)
    print(f"数据源: baostock (已优化：只登录一次)")
    print(f"参数: n_days={args.n_days}, delay={args.delay}s")
    print()
    
    # Step 0: 登录 baostock（只登录一次）
    print("[Step 0] 登录 baostock...")
    lg = bs.login()
    if lg.error_code != '0':
        print(f"  ✗ 登录失败: {lg.error_msg}")
        return False
    print("  ✓ 登录成功")
    
    try:
        # Step 1: 加载股票列表
        print("\n[Step 1] 加载主板股票列表...")
        all_stocks = load_stock_list()
        print(f"  主板股票总数: {len(all_stocks)}")
        
        if args.max_stocks > 0:
            all_stocks = all_stocks[:args.max_stocks]
            print(f"  限制拉取数量: {args.max_stocks}")
        
        # Step 2: 加载现有缓存
        print("\n[Step 2] 加载现有缓存...")
        cache_data = load_cache() if not args.full else None
        existing_stocks = get_existing_stocks(cache_data)
        print(f"  已有数据的股票数: {len(existing_stocks)}")
        
        # Step 3: 计算日期范围
        end_date = datetime.now()
        start_date = end_date - timedelta(days=args.n_days * 1.5)
        start_date_str = start_date.strftime('%Y-%m-%d')
        end_date_str = end_date.strftime('%Y-%m-%d')
        print(f"\n[Step 3] 日期范围: {start_date_str} ~ {end_date_str}")
        
        # Step 4: 串行拉取
        print(f"\n[Step 4] 开始串行拉取...")
        
        all_new_records = []
        success_count = 0
        failed_stocks = []
        consecutive_failures = 0
        
        total = len(all_stocks)
        start_time = time.time()
        last_save_count = 0
        
        for idx, stock in enumerate(all_stocks, 1):
            code = stock['code']
            name = stock['name']
            
            elapsed = time.time() - start_time
            if idx > 1:
                avg_time = elapsed / (idx - 1)
                remaining = (total - idx + 1) * avg_time
            else:
                remaining = 0
            
            print(f"\r  [{idx}/{total}] {code} {name:8s} | 成功: {success_count} 失败: {len(failed_stocks)} | 预计剩余: {format_time(remaining)}  ", end='', flush=True)
            
            # 跳过已有数据的股票（增量模式）
            if code in existing_stocks and not args.full:
                continue
            
            records, success = fetch_stock_history_baostock(code, start_date_str, end_date_str, args.retries)
            
            if success and records is not None:
                all_new_records.extend(records)
                success_count += 1
                consecutive_failures = 0
            elif success:
                success_count += 1
                consecutive_failures = 0
            else:
                failed_stocks.append(code)
                consecutive_failures += 1
                print(f"\n    ✗ {code} 拉取失败")
                
                if consecutive_failures >= CONSECUTIVE_FAILURE_THRESHOLD:
                    print(f"\n  ⚠ 连续失败{consecutive_failures}只，暂停{CONSECUTIVE_FAILURE_PAUSE}秒...")
                    time.sleep(CONSECUTIVE_FAILURE_PAUSE)
                    consecutive_failures = 0
            
            # 中间保存
            if success_count > 0 and success_count % INTERMEDIATE_SAVE_INTERVAL == 0 and success_count > last_save_count:
                print(f"\n  💾 中间保存: 已成功拉取{success_count}只股票...")
                merged_data = merge_records(cache_data, all_new_records)
                save_cache(merged_data)
                last_save_count = success_count
                cache_data = merged_data
            
            if idx < total:
                time.sleep(args.delay)
        
        print()
        
        # Step 5: 重试失败股票
        if failed_stocks:
            print(f"\n[Step 5] 重试 {len(failed_stocks)} 只失败股票...")
            final_failed = []
            for code in failed_stocks:
                records, success = fetch_stock_history_baostock(code, start_date_str, end_date_str, retries=1)
                if success and records is not None:
                    all_new_records.extend(records)
                    success_count += 1
                    print(f"    ✓ {code} 重试成功")
                else:
                    final_failed.append(code)
                    print(f"    ✗ {code} 最终失败")
            failed_stocks = final_failed
        
        # Step 6: 合并并保存
        print(f"\n[Step 6] 合并数据并保存...")
        merged_data = merge_records(cache_data, all_new_records)
        save_cache(merged_data)
        
        # 输出统计
        total_time = time.time() - start_time
        meta = merged_data['meta']
        
        print("\n" + "=" * 70)
        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 拉取完成")
        print("=" * 70)
        print(f"总股票数:   {total}")
        print(f"成功数:     {success_count}")
        print(f"失败数:     {len(failed_stocks)}")
        if failed_stocks:
            print(f"失败股票:   {', '.join(failed_stocks[:10])}{'...' if len(failed_stocks) > 10 else ''}")
        print(f"\n日期范围:   {meta['date_range']['start']} ~ {meta['date_range']['end']}")
        print(f"交易日数:   {meta['n_days']}")
        print(f"股票数:     {meta['n_assets']}")
        print(f"总记录数:   {len(merged_data['data'])}")
        print(f"耗时:       {format_time(total_time)}")
        print(f"速度:       {total_time/max(success_count,1):.2f} 秒/只")
        
        return len(failed_stocks) == 0
    
    finally:
        # 确保登出 baostock
        print("\n[清理] 登出 baostock...")
        bs.logout()
        print("  ✓ 已登出")


if __name__ == '__main__':
    success = main()
    sys.exit(0 if success else 1)