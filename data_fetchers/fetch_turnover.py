#!/usr/bin/env python3
"""
换手率数据拉取脚本

包含两个数据源：
1. 东财千股千评 API（fetch_turnover_rate_eastmoney）- 实时数据
2. baostock 数据源（fetch_turnover_rate_baostock）- 历史数据

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
import requests

# 缓存目录
PROJECT_ROOT = Path(__file__).parent.parent
CACHE_DIR = PROJECT_ROOT / 'cache'
FACTOR_DATA_DIR = CACHE_DIR / 'factor_data'
CACHE_FILE = FACTOR_DATA_DIR / 'turnover_rate_data.json.gz'
STOCK_LIST_FILE = CACHE_DIR / 'stock_list.json'

# ============================================================
# 东财千股千评 API 版本
# ============================================================

EASTMONEY_API_URL = "https://datacenter-web.eastmoney.com/api/data/v1/get"

API_PARAMS = {
    "sortColumns": "SECURITY_CODE",
    "sortTypes": "1",
    "pageSize": "500",
    "pageNumber": "1",
    "reportName": "RPT_DMSK_TS_STOCKNEW",
    "quoteColumns": "f2~01~SECURITY_CODE~CLOSE_PRICE,f8~01~SECURITY_CODE~TURNOVERRATE,"
                    "f3~01~SECURITY_CODE~CHANGE_RATE,f9~01~SECURITY_CODE~PE_DYNAMIC",
    "columns": "ALL",
    "filter": "",
    "token": "894050c76af8597a853f5b408b759f5d",
}

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Referer": "https://data.eastmoney.com/stockcomment/",
    "Accept": "*/*",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}


def is_main_board_stock(code: str, name: str) -> bool:
    """判断是否为主板股票"""
    if code.startswith('30') or code.startswith('688') or code.startswith('8') or code.startswith('4'):
        return False
    if 'ST' in name or '退市' in name or '*ST' in name:
        return False
    return code.startswith('60') or code.startswith('00')


def fetch_turnover_rate_eastmoney() -> List[Dict]:
    """从东财千股千评 API 拉取换手率数据"""
    print("\n[API拉取] 从东财千股千评获取换手率数据...")
    
    all_records = []
    page = 1
    total_pages = 0
    retries = 3
    
    session = requests.Session()
    session.headers.update(HEADERS)
    
    while True:
        params = API_PARAMS.copy()
        params["pageNumber"] = page
        
        for attempt in range(retries):
            try:
                response = session.get(EASTMONEY_API_URL, params=params, timeout=30)
                response.raise_for_status()
                data_json = response.json()
                break
            except Exception as e:
                if attempt < retries - 1:
                    wait_time = 2 + attempt * 2
                    print(f"  重试 {attempt + 1}/{retries}，等待 {wait_time}秒...")
                    time.sleep(wait_time)
                else:
                    print(f"  ✗ API请求失败: {e}")
                    raise RuntimeError(f"API请求失败: {e}")
        
        if page == 1:
            total_pages = data_json.get("result", {}).get("pages", 0)
            total_count = data_json.get("result", {}).get("count", 0)
            print(f"  总页数: {total_pages}, 总股票数: {total_count}")
        
        result_data = data_json.get("result", {}).get("data", [])
        
        if not result_data:
            print(f"  第 {page} 页返回空数据，获取完成")
            break
        
        page_added = 0
        for item in result_data:
            code = item.get("SECURITY_CODE", "")
            name = item.get("SECURITY_NAME_ABBR", "")
            trade_date = item.get("TRADE_DATE", "")
            turnover_rate = item.get("TURNOVERRATE")
            
            if is_main_board_stock(code, name):
                if turnover_rate is not None and turnover_rate != "-":
                    try:
                        turnover_rate_float = float(turnover_rate)
                        all_records.append({
                            'date': trade_date,
                            'asset': code,
                            'turnover_rate': turnover_rate_float,
                            'name': name
                        })
                        page_added += 1
                    except (ValueError, TypeError):
                        pass
        
        print(f"  第 {page}/{total_pages} 页: 获取 {len(result_data)} 条，新增主板 {page_added} 只")
        
        if page >= total_pages:
            break
        
        page += 1
        time.sleep(0.1)
    
    print(f"\n  ✓ 共获取 {len(all_records)} 条主板股票换手率数据")
    return all_records


# ============================================================
# baostock 版本
# ============================================================

DEFAULT_N_DAYS = 500
DEFAULT_DELAY = 0.1
DEFAULT_MAX_RETRIES = 3

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


def fetch_turnover_rate_baostock(n_days: int = DEFAULT_N_DAYS, max_stocks: int = 0, full: bool = False) -> bool:
    """使用 baostock 拉取历史换手率数据"""
    import baostock as bs
    
    print("=" * 70)
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 开始拉取历史换手率数据（baostock）")
    print("=" * 70)
    
    # 登录 baostock
    print("\n[Step 0] 登录 baostock...")
    lg = bs.login()
    if lg.error_code != '0':
        print(f"  ✗ 登录失败: {lg.error_msg}")
        return False
    print("  ✓ 登录成功")
    
    try:
        # 加载股票列表
        print("\n[Step 1] 加载主板股票列表...")
        all_stocks = load_stock_list()
        print(f"  主板股票总数: {len(all_stocks)}")
        
        if max_stocks > 0:
            all_stocks = all_stocks[:max_stocks]
            print(f"  限制拉取数量: {max_stocks}")
        
        # 加载现有缓存
        print("\n[Step 2] 加载现有缓存...")
        cache_data = load_cache() if not full else None
        existing_stocks = get_existing_stocks(cache_data)
        print(f"  已有数据的股票数: {len(existing_stocks)}")
        
        # 计算日期范围
        end_date = datetime.now()
        start_date = end_date - timedelta(days=n_days * 1.5)
        start_date_str = start_date.strftime('%Y-%m-%d')
        end_date_str = end_date.strftime('%Y-%m-%d')
        print(f"\n[Step 3] 日期范围: {start_date_str} ~ {end_date_str}")
        
        # 串行拉取
        print(f"\n[Step 4] 开始串行拉取...")
        
        all_new_records = []
        success_count = 0
        failed_stocks = []
        consecutive_failures = 0
        
        total = len(all_stocks)
        start_time = time.time()
        
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
            
            if code in existing_stocks and not full:
                continue
            
            records, success = fetch_stock_history_baostock(code, start_date_str, end_date_str)
            
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
                
                if consecutive_failures >= CONSECUTIVE_FAILURE_THRESHOLD:
                    print(f"\n  ⚠ 连续失败{consecutive_failures}只，暂停{CONSECUTIVE_FAILURE_PAUSE}秒...")
                    time.sleep(CONSECUTIVE_FAILURE_PAUSE)
                    consecutive_failures = 0
            
            if idx < total:
                time.sleep(DEFAULT_DELAY)
        
        print()
        
        # 合并并保存
        print(f"\n[Step 5] 合并数据并保存...")
        merged_data = merge_records(cache_data, all_new_records)
        save_cache(merged_data)
        
        total_time = time.time() - start_time
        meta = merged_data['meta']
        
        print("\n" + "=" * 70)
        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 拉取完成")
        print("=" * 70)
        print(f"总股票数:   {total}")
        print(f"成功数:     {success_count}")
        print(f"失败数:     {len(failed_stocks)}")
        print(f"日期范围:   {meta['date_range']['start']} ~ {meta['date_range']['end']}")
        print(f"交易日数:   {meta['n_days']}")
        print(f"耗时:       {format_time(total_time)}")
        
        return len(failed_stocks) == 0
    
    finally:
        print("\n[清理] 登出 baostock...")
        bs.logout()
        print("  ✓ 已登出")


def get_baostock_code(stock_code: str) -> str:
    """根据股票代码转换为 baostock 格式"""
    if stock_code.startswith('6'):
        return f'sh.{stock_code}'
    else:
        return f'sz.{stock_code}'


def fetch_stock_history_baostock(stock_code: str, start_date: str, end_date: str,
                                   retries: int = DEFAULT_MAX_RETRIES) -> Tuple[Optional[List[Dict]], bool]:
    """使用 baostock 拉取单只股票的历史换手率数据"""
    import baostock as bs
    
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
                time.sleep(wait_time)
            else:
                return (None, False)
    
    return (None, False)


# ============================================================
# 公共函数
# ============================================================

def load_cache() -> Optional[Dict]:
    """加载现有缓存"""
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
    """保存缓存文件"""
    FACTOR_DATA_DIR.mkdir(parents=True, exist_ok=True)
    
    temp_file = CACHE_FILE.with_suffix('.json.gz.tmp')
    with gzip.open(temp_file, 'wt', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    
    temp_file.replace(CACHE_FILE)
    
    file_size = CACHE_FILE.stat().st_size
    size_mb = file_size / (1024 * 1024)
    print(f"[缓存] 已保存: {CACHE_FILE} ({size_mb:.2f} MB)")


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
            'source': 'mixed',
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


# ============================================================
# 主函数
# ============================================================

def main():
    """主函数：东财版本"""
    print("=" * 60)
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 开始拉取换手率数据")
    print("=" * 60)
    print("数据源: 东财千股千评 API")
    print("股票范围: 主板股票（60/00开头，剔除创业板/科创板/北交所/ST）")
    print(f"缓存路径: {CACHE_FILE}")
    
    # Step 1: 加载现有缓存
    existing_data = load_cache()
    
    # Step 2: 拉取新数据
    new_records = fetch_turnover_rate_eastmoney()
    
    if not new_records:
        print("\n❌ 未获取到任何数据")
        return False
    
    # Step 3: 合并去重
    merged_data = merge_records(existing_data, new_records)
    
    # Step 4: 保存缓存
    save_cache(merged_data)
    
    # 输出统计
    meta = merged_data['meta']
    print("\n" + "=" * 60)
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 换手率数据拉取完成")
    print("=" * 60)
    print(f"日期范围: {meta['date_range']['start']} ~ {meta['date_range']['end']}")
    print(f"交易日数: {meta['n_days']}")
    print(f"股票数量: {meta['n_assets']}")
    print(f"总记录数: {len(merged_data['data'])}")
    
    return True


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='换手率数据拉取脚本')
    parser.add_argument('--source', choices=['eastmoney', 'baostock'], default='eastmoney',
                       help='数据源选择')
    parser.add_argument('--n_days', type=int, default=500, help='历史天数（baostock）')
    parser.add_argument('--max_stocks', type=int, default=0, help='最大股票数（baostock）')
    parser.add_argument('--full', action='store_true', help='全量拉取（baostock）')
    args = parser.parse_args()
    
    if args.source == 'eastmoney':
        success = main()
    else:
        success = fetch_turnover_rate_baostock(args.n_days, args.max_stocks, args.full)
    
    sys.exit(0 if success else 1)