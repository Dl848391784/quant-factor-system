#!/usr/bin/env python3
"""
补拉缺失的换手率数据（仅2026-04-08）
"""

import json
import gzip
import time
import baostock as bs
from pathlib import Path
from datetime import datetime

CACHE_DIR = Path('/home/admin/.openclaw/workspace/yunzhou/factor_ic_analyzer/cache')
CACHE_FILE = CACHE_DIR / 'factor_data' / 'turnover_rate_data.json.gz'
MISSING_FILE = CACHE_DIR / 'missing_stocks_0408.json'
INTERMEDIATE_SAVE_INTERVAL = 100

def get_baostock_code(stock_code: str) -> str:
    if stock_code.startswith('6'):
        return f'sh.{stock_code}'
    else:
        return f'sz.{stock_code}'

def fetch_stock_turnover(stock_code: str, date: str):
    bs_code = get_baostock_code(stock_code)
    
    for attempt in range(3):
        try:
            rs = bs.query_history_k_data_plus(
                bs_code,
                'date,code,turn',
                start_date=date,
                end_date=date,
                frequency='d',
                adjustflag='3'
            )
            
            if rs.error_code != '0':
                if attempt < 2:
                    time.sleep(2 ** attempt)
                    continue
                return (None, False)
            
            data_list = []
            while rs.next():
                data_list.append(rs.get_row_data())
            
            if not data_list:
                return ([], True)
            
            for row in data_list:
                turn_str = row[2]
                try:
                    turnover_rate = float(turn_str)
                    return ([{'date': date, 'asset': stock_code, 'turnover_rate': turnover_rate}], True)
                except (ValueError, TypeError):
                    continue
            
            return ([], True)
            
        except Exception as e:
            if attempt < 2:
                time.sleep(2 ** attempt)
            else:
                return (None, False)
    
    return (None, False)

def format_time(seconds: float) -> str:
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"

def main():
    print("=" * 70)
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 补拉缺失换手率数据（2026-04-08）")
    print("=" * 70)
    
    # 登录 baostock
    print("\n[登录 baostock...")
    lg = bs.login()
    if lg.error_code != '0':
        print(f"登录失败: {lg.error_msg}")
        return False
    print("登录成功")
    
    try:
        # 加载缺失股票列表
        print("\n[加载缺失股票列表...")
        with open(MISSING_FILE, 'r', encoding='utf-8') as f:
            missing_data = json.load(f)
        
        stocks = missing_data.get('stocks', [])
        print(f"缺失股票数: {len(stocks)}")
        
        # 加载现有缓存
        print("\n[加载现有缓存...")
        with gzip.open(CACHE_FILE, 'rt', encoding='utf-8') as f:
            cache_data = json.load(f)
        
        existing_records = cache_data.get('data', [])
        print(f"现有记录数: {len(existing_records)}")
        
        # 拉取数据
        print(f"\n[开始拉取...")
        all_new_records = []
        success_count = 0
        fail_count = 0
        no_data_count = 0
        
        start_time = time.time()
        total = len(stocks)
        date = '2026-04-08'
        
        for idx, stock in enumerate(stocks, 1):
            code = stock['code']
            name = stock['name']
            
            elapsed = time.time() - start_time
            if idx > 1:
                avg_time = elapsed / (idx - 1)
                remaining = (total - idx + 1) * avg_time
            else:
                remaining = 0
            
            print(f"\r  [{idx}/{total}] {code} {name:8s} | 成功: {success_count} 无数据: {no_data_count} 失败: {fail_count} | 剩余: {format_time(remaining)}  ", end='', flush=True)
            
            records, success = fetch_stock_turnover(code, date)
            
            if success:
                if records:
                    all_new_records.extend(records)
                    success_count += 1
                else:
                    no_data_count += 1
            else:
                fail_count += 1
                print(f"\n    ✗ {code} 拉取失败")
            
            # 中间保存
            if success_count > 0 and success_count % INTERMEDIATE_SAVE_INTERVAL == 0:
                print(f"\n  💾 中间保存: {success_count} 只股票...")
                merged_records = existing_records + all_new_records
                record_map = {}
                for r in merged_records:
                    key = (r['date'], r['asset'])
                    record_map[key] = r
                merged_records = list(record_map.values())
                merged_records.sort(key=lambda x: (x['date'], x['asset']))
                
                unique_dates = sorted(set(r['date'] for r in merged_records))
                unique_assets = sorted(set(r['asset'] for r in merged_records))
                
                cache_data['data'] = merged_records
                cache_data['meta']['n_days'] = len(unique_dates)
                cache_data['meta']['n_assets'] = len(unique_assets)
                cache_data['meta']['date_range'] = {'start': unique_dates[0], 'end': unique_dates[-1]}
                cache_data['meta']['last_updated'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                
                with gzip.open(CACHE_FILE, 'wt', encoding='utf-8') as f:
                    json.dump(cache_data, f, ensure_ascii=False, indent=2)
                
                existing_records = merged_records
                print(f"    已保存: {len(unique_dates)} 天, {len(unique_assets)} 只股票")
            
            time.sleep(0.1)
        
        print()
        
        # 最终合并保存
        print(f"\n[最终合并保存...")
        merged_records = existing_records + all_new_records
        record_map = {}
        for r in merged_records:
            key = (r['date'], r['asset'])
            record_map[key] = r
        merged_records = list(record_map.values())
        merged_records.sort(key=lambda x: (x['date'], x['asset']))
        
        unique_dates = sorted(set(r['date'] for r in merged_records))
        unique_assets = sorted(set(r['asset'] for r in merged_records))
        
        cache_data['data'] = merged_records
        cache_data['meta']['n_days'] = len(unique_dates)
        cache_data['meta']['n_assets'] = len(unique_assets)
        cache_data['meta']['date_range'] = {'start': unique_dates[0], 'end': unique_dates[-1]}
        cache_data['meta']['last_updated'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        
        with gzip.open(CACHE_FILE, 'wt', encoding='utf-8') as f:
            json.dump(cache_data, f, ensure_ascii=False, indent=2)
        
        total_time = time.time() - start_time
        
        print("\n" + "=" * 70)
        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 完成")
        print("=" * 70)
        print(f"日期:       {date}")
        print(f"总股票数:   {total}")
        print(f"成功拉取:   {success_count}")
        print(f"无数据:     {no_data_count}")
        print(f"失败:       {fail_count}")
        print(f"新增记录:   {len(all_new_records)}")
        print(f"总记录数:   {len(merged_records)}")
        print(f"交易日数:   {len(unique_dates)}")
        print(f"股票数:     {len(unique_assets)}")
        print(f"耗时:       {format_time(total_time)}")
        
        return fail_count == 0
    
    finally:
        print("\n[登出 baostock...")
        bs.logout()
        print("已登出")

if __name__ == '__main__':
    main()