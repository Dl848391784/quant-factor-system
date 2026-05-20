#!/usr/bin/env python3
"""
流通市值数据拉取脚本（使用东财 API）

功能：
- 支持全量历史拉取（--n_days N）
- 支持每日增量拉取（--daily）
- 拉取流通市值和总市值
- 自动重试、限流处理
- 增量更新缓存

数据来源：东财 API

使用方式：
    python3 fetch_float_mv.py --n_days 500      # 全量历史拉取
    python3 fetch_float_mv.py --daily            # 每日增量（T-1交易日）
    python3 fetch_float_mv.py --n_days 5 --full  # 强制全量拉取

缓存路径：cache/factor_data/float_mv_data.json.gz

作者: 云舟
日期: 2026-04-08
"""

import sys
import os
import gzip
import json
import time
import re
import argparse
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Dict, List, Set, Tuple
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# 缓存目录
CACHE_DIR = Path('/home/admin/projects/factor_ic_analyzer/cache')
FACTOR_DATA_DIR = CACHE_DIR / 'factor_data'
CACHE_FILE = FACTOR_DATA_DIR / 'float_mv_data.json.gz'
STOCK_LIST_FILE = CACHE_DIR / 'stock_list.json'

# 东财市值 API
EASTMONEY_STOCK_INFO_URL = "https://push2.eastmoney.com/api/qt/stock/get"

# 请求头
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Referer": "https://quote.eastmoney.com/",
    "Accept": "*/*",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Connection": "keep-alive",
}

# 请求间隔（秒）
REQUEST_DELAY = 0.3
MAX_RETRIES = 3

# 限速控制
CONSECUTIVE_FAILURE_THRESHOLD = 5
CONSECUTIVE_FAILURE_PAUSE = 30
INTERMEDIATE_SAVE_INTERVAL = 100


def create_session() -> requests.Session:
    """创建带重试机制的 Session"""
    session = requests.Session()
    session.headers.update(HEADERS)
    
    try:
        retry_strategy = Retry(
            total=3,
            backoff_factor=1,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["GET"],
        )
    except TypeError:
        retry_strategy = Retry(
            total=3,
            backoff_factor=1,
            status_forcelist=[429, 500, 502, 503, 504],
            method_whitelist=["GET"],
        )
    
    adapter = HTTPAdapter(max_retries=retry_strategy, pool_connections=10, pool_maxsize=10)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    
    return session


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
        # 排除创业板(30)、科创板(688)、北交所(8/4开头)、ST股票
        if code.startswith('30') or code.startswith('688') or code.startswith('8') or code.startswith('4'):
            continue
        if 'ST' in name or '退市' in name or '*ST' in name:
            continue
        # 只保留主板：沪市60、深市00
        if code.startswith('60') or code.startswith('00'):
            main_board_stocks.append(stock)
    return main_board_stocks


def load_cache() -> Optional[Dict]:
    """加载现有流通市值缓存"""
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


def get_existing_data(cache_data: Optional[Dict]) -> Dict[str, Set[str]]:
    """
    从缓存中获取已有数据
    返回: {日期: {股票代码集合}}
    """
    if not cache_data:
        return {}
    
    data = cache_data.get('data', [])
    result = {}
    
    for record in data:
        date = record.get('date')
        asset = record.get('asset')
        if date and asset:
            if date not in result:
                result[date] = set()
            result[date].add(asset)
    
    return result


def save_cache(data: Dict) -> None:
    """保存缓存文件"""
    FACTOR_DATA_DIR.mkdir(parents=True, exist_ok=True)
    
    # 使用临时文件 + 原子重命名
    import tempfile
    import shutil
    
    temp_fd, temp_path = tempfile.mkstemp(
        dir=FACTOR_DATA_DIR,
        prefix='.tmp_float_mv_',
        suffix='.json.gz'
    )
    
    try:
        with os.fdopen(temp_fd, 'wb') as f:
            with gzip.GzipFile(fileobj=f, mode='wb') as gz:
                gz.write(json.dumps(data, ensure_ascii=False, indent=2).encode('utf-8'))
        
        shutil.move(temp_path, str(CACHE_FILE))
        
        file_size = CACHE_FILE.stat().st_size
        size_mb = file_size / (1024 * 1024)
        print(f"[缓存] 已保存: {CACHE_FILE} ({size_mb:.2f} MB)")
        
    except Exception as e:
        if os.path.exists(temp_path):
            os.unlink(temp_path)
        raise e


def get_market_code(stock_code: str) -> str:
    """根据股票代码获取市场代码"""
    return '1' if stock_code.startswith('6') else '0'


def fetch_stock_market_value(
    stock_code: str,
    session: requests.Session
) -> Tuple[Optional[Dict], bool]:
    """
    使用东财 API 拉取单只股票的流通市值和总市值
    
    API 字段说明：
    - f84: 流通市值（元）
    - f85: 流通市值（元，备用）
    - f116: 总市值（元）
    - f117: 总市值（元，备用）
    
    Returns:
        (市值数据字典, 是否成功)
        数据格式: {
            'asset': str,
            'float_mv': float,  # 流通市值（元）
            'total_mv': float   # 总市值（元）
        }
    """
    market = get_market_code(stock_code)
    secid = f"{market}.{stock_code}"
    
    # 请求参数
    params = {
        "cb": "jQuery",
        "secid": secid,
        "fields": "f84,f85,f116,f117",
        "ut": "b2884a393a59ad64002292a3e90d46a5",
        "_": str(int(time.time() * 1000))
    }
    
    for attempt in range(MAX_RETRIES):
        try:
            response = session.get(
                EASTMONEY_STOCK_INFO_URL,
                params=params,
                timeout=(10, 30),
            )
            response.raise_for_status()
            
            # 解析 JSONP 响应
            text = response.text
            match = re.search(r'jQuery\((.*)\);?', text, re.DOTALL)
            if not match:
                return (None, True)  # 空数据
            
            json_str = match.group(1)
            data = json.loads(json_str)
            
            # 提取市值数据
            if 'data' not in data or data['data'] is None:
                return (None, True)  # 无数据
            
            stock_data = data['data']
            
            # 流通市值（元）
            float_mv = stock_data.get('f84') or stock_data.get('f85')
            # 总市值（元）
            total_mv = stock_data.get('f116') or stock_data.get('f117')
            
            if float_mv is None or total_mv is None:
                return (None, True)  # 数据不完整
            
            result = {
                'asset': stock_code,
                'float_mv': float(float_mv),
                'total_mv': float(total_mv)
            }
            
            return (result, True)
            
        except Exception as e:
            if attempt < MAX_RETRIES - 1:
                wait_time = 2 ** attempt
                print(f"\n    ⚠ {stock_code} 请求失败，等待{wait_time}秒后重试...")
                time.sleep(wait_time)
            else:
                return (None, False)
    
    return (None, False)


def merge_records(existing_data: Optional[Dict], new_records: List[Dict], target_date: str) -> Dict:
    """合并现有数据和新数据"""
    existing_records = []
    if existing_data:
        existing_records = existing_data.get('data', [])
    
    # 移除目标日期的旧数据
    filtered_records = [r for r in existing_records if r.get('date') != target_date]
    
    # 添加新数据
    new_records_with_date = [{'date': target_date, **r} for r in new_records]
    all_records = filtered_records + new_records_with_date
    
    # 按日期和股票代码排序
    all_records.sort(key=lambda x: (x['date'], x['asset']))
    
    unique_dates = sorted(set(r['date'] for r in all_records))
    unique_assets = sorted(set(r['asset'] for r in all_records))
    
    now = datetime.now()
    
    return {
        'meta': {
            'generated_at': now.isoformat(),
            'source': 'eastmoney_api',
            'n_days': len(unique_dates),
            'n_assets': len(unique_assets),
            'date_range': {
                'start': unique_dates[0] if unique_dates else None,
                'end': unique_dates[-1] if unique_dates else None
            },
            'last_updated': now.strftime('%Y-%m-%d %H:%M:%S'),
            'version': '1.0',
            'description': '主板股票流通市值数据（东财API）'
        },
        'data': all_records
    }


def format_time(seconds: float) -> str:
    """格式化时间为 HH:MM:SS"""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


def get_previous_trading_day() -> str:
    """获取最近的交易日（简单实现：上一个工作日）"""
    now = datetime.now()
    delta = timedelta(days=1)
    target_date = now - delta
    
    # 跳过周末
    while target_date.weekday() >= 5:
        target_date -= delta
    
    return target_date.strftime('%Y-%m-%d')


def fetch_full_history(args) -> bool:
    """全量历史数据拉取（按日期逐日拉取）"""
    print("=" * 70)
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 开始拉取历史流通市值数据")
    print("=" * 70)
    print(f"数据源: 东财 API")
    print(f"参数: n_days={args.n_days}")
    print()
    
    session = create_session()
    
    try:
        # Step 1: 加载股票列表
        print("[Step 1] 加载主板股票列表...")
        all_stocks = load_stock_list()
        print(f"  主板股票总数: {len(all_stocks)}")
        
        if args.max_stocks > 0:
            all_stocks = all_stocks[:args.max_stocks]
            print(f"  限制拉取数量: {args.max_stocks}")
        
        # Step 2: 加载现有缓存
        print("\n[Step 2] 加载现有缓存...")
        cache_data = load_cache() if not args.full else None
        existing_data_map = get_existing_data(cache_data)
        print(f"  已有数据的日期数: {len(existing_data_map)}")
        
        # Step 3: 计算日期范围
        end_date = datetime.now()
        start_date = end_date - timedelta(days=args.n_days * 1.5)
        
        # 生成交易日列表（简单实现：跳过周末）
        date_list = []
        current = start_date
        while current <= end_date:
            if current.weekday() < 5:  # 周一到周五
                date_list.append(current.strftime('%Y-%m-%d'))
            current += timedelta(days=1)
        
        date_list = date_list[-args.n_days:]  # 只保留最近 N 天
        
        print(f"\n[Step 3] 日期范围: {date_list[0]} ~ {date_list[-1]} ({len(date_list)}个交易日)")
        
        # Step 4: 按日期拉取
        print(f"\n[Step 4] 开始拉取市值数据...")
        
        all_new_records = []
        total_success = 0
        total_failed = []
        
        start_time = time.time()
        
        for date_idx, target_date in enumerate(date_list, 1):
            print(f"\n[日期 {date_idx}/{len(date_list)}] {target_date}")
            
            # 检查是否已有该日期数据
            if target_date in existing_data_map and not args.full:
                existing_stocks = existing_data_map[target_date]
                print(f"  已有 {len(existing_stocks)} 只股票数据，跳过")
                continue
            
            # 拉取该日期所有股票的市值
            success_count = 0
            fail_count = 0
            date_records = []
            consecutive_failures = 0
            
            for idx, stock in enumerate(all_stocks, 1):
                code = stock['code']
                name = stock['name']
                
                elapsed = time.time() - start_time
                print(f"\r  [{idx}/{len(all_stocks)}] {code} {name:8s} | 成功: {success_count} 失败: {fail_count}", end='', flush=True)
                
                mv_data, success = fetch_stock_market_value(code, session)
                
                if success and mv_data:
                    date_records.append(mv_data)
                    success_count += 1
                    consecutive_failures = 0
                elif success:
                    consecutive_failures = 0
                else:
                    fail_count += 1
                    total_failed.append(code)
                    consecutive_failures += 1
                    
                    if consecutive_failures >= CONSECUTIVE_FAILURE_THRESHOLD:
                        print(f"\n  ⚠ 连续失败{consecutive_failures}只，暂停{CONSECUTIVE_FAILURE_PAUSE}秒...")
                        time.sleep(CONSECUTIVE_FAILURE_PAUSE)
                        consecutive_failures = 0
                
                if idx < len(all_stocks):
                    time.sleep(REQUEST_DELAY)
            
            print()
            
            # 为该日期的记录添加日期字段
            for record in date_records:
                record['date'] = target_date
            
            all_new_records.extend(date_records)
            total_success += success_count
            
            # 合并并保存
            if date_records:
                cache_data = merge_records(cache_data, date_records, target_date)
                if date_idx % 10 == 0 or date_idx == len(date_list):
                    save_cache(cache_data)
            
            print(f"  本日成功: {success_count}, 失败: {fail_count}")
        
        # 最终保存
        print(f"\n[Step 5] 最终保存...")
        if cache_data:
            save_cache(cache_data)
        
        # 输出统计
        total_time = time.time() - start_time
        meta = cache_data.get('meta', {}) if cache_data else {}
        
        print("\n" + "=" * 70)
        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 拉取完成")
        print("=" * 70)
        print(f"日期数:     {len(date_list)}")
        print(f"成功记录:   {total_success}")
        print(f"失败股票:   {len(set(total_failed))}")
        print(f"\n日期范围:   {meta.get('date_range', {}).get('start')} ~ {meta.get('date_range', {}).get('end')}")
        print(f"交易日数:   {meta.get('n_days', 0)}")
        print(f"股票数:     {meta.get('n_assets', 0)}")
        print(f"总记录数:   {len(cache_data.get('data', [])) if cache_data else 0}")
        print(f"耗时:       {format_time(total_time)}")
        
        return len(set(total_failed)) < len(all_stocks) * 0.1  # 失败率 < 10% 算成功
    
    finally:
        session.close()


def fetch_daily_increment(args) -> bool:
    """每日增量数据拉取"""
    print("=" * 70)
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 流通市值数据每日增量更新")
    print("=" * 70)
    
    # 确定目标日期
    if args.date:
        target_date = args.date
    else:
        target_date = get_previous_trading_day()
    
    print(f"[目标日期] {target_date}")
    
    session = create_session()
    
    try:
        # Step 1: 加载现有缓存
        print("\n[Step 1] 加载现有缓存...")
        cache_data = load_cache()
        existing_data_map = get_existing_data(cache_data)
        
        if target_date in existing_data_map:
            existing_stocks = existing_data_map[target_date]
            print(f"  已有 {target_date} 数据的股票数: {len(existing_stocks)}")
        else:
            existing_stocks = set()
            print(f"  {target_date} 数据不存在")
        
        # Step 2: 加载股票列表
        print("\n[Step 2] 加载主板股票列表...")
        all_stocks = load_stock_list()
        print(f"  主板股票总数: {len(all_stocks)}")
        
        if args.max_stocks > 0:
            all_stocks = all_stocks[:args.max_stocks]
            print(f"  限制拉取数量: {args.max_stocks}")
        
        # Step 3: 过滤需要拉取的股票
        stocks_to_fetch = [s for s in all_stocks if s['code'] not in existing_stocks]
        print(f"  需要拉取的股票数: {len(stocks_to_fetch)}")
        
        if not stocks_to_fetch:
            print("\n所有股票数据已存在，无需更新。")
            return True
        
        # Step 4: 拉取数据
        print(f"\n[Step 3] 拉取 {target_date} 的市值数据...")
        
        all_new_records = []
        success_count = 0
        fail_count = 0
        no_data_count = 0
        consecutive_failures = 0
        
        start_time = time.time()
        
        for idx, stock in enumerate(stocks_to_fetch, 1):
            code = stock['code']
            name = stock['name']
            
            print(f"\r  [{idx}/{len(stocks_to_fetch)}] {code} {name:8s} | 成功: {success_count} 无数据: {no_data_count} 失败: {fail_count}", end='', flush=True)
            
            mv_data, success = fetch_stock_market_value(code, session)
            
            if success and mv_data:
                all_new_records.append(mv_data)
                success_count += 1
                consecutive_failures = 0
            elif success:
                no_data_count += 1
                consecutive_failures = 0
            else:
                fail_count += 1
                consecutive_failures += 1
                
                if consecutive_failures >= CONSECUTIVE_FAILURE_THRESHOLD:
                    print(f"\n  ⚠ 连续失败{consecutive_failures}只，暂停{CONSECUTIVE_FAILURE_PAUSE}秒...")
                    time.sleep(CONSECUTIVE_FAILURE_PAUSE)
                    consecutive_failures = 0
            
            if idx < len(stocks_to_fetch):
                time.sleep(REQUEST_DELAY)
        
        print()
        
        # Step 5: 合并并保存
        print(f"\n[Step 4] 合并数据并保存...")
        
        if all_new_records:
            merged_data = merge_records(cache_data, all_new_records, target_date)
            save_cache(merged_data)
        else:
            print("  ⚠ 没有新数据")
        
        # 输出统计
        total_time = time.time() - start_time
        
        print("\n" + "=" * 70)
        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 更新完成")
        print("=" * 70)
        print(f"目标日期:   {target_date}")
        print(f"股票总数:   {len(stocks_to_fetch)}")
        print(f"成功拉取:   {success_count}")
        print(f"无数据:     {no_data_count}")
        print(f"失败:       {fail_count}")
        print(f"新增数据:   {len(all_new_records)} 条")
        print(f"耗时:       {int(total_time // 60)}分{int(total_time % 60)}秒")
        
        return fail_count < len(stocks_to_fetch) * 0.1
    
    finally:
        session.close()


def main():
    """主函数"""
    parser = argparse.ArgumentParser(description='拉取流通市值数据（东财API）')
    parser.add_argument('--n_days', type=int, default=500,
                        help='历史天数 (默认: 500)')
    parser.add_argument('--daily', action='store_true',
                        help='每日增量模式（拉取T-1交易日）')
    parser.add_argument('--date', type=str, default=None,
                        help='指定日期 (YYYY-MM-DD)')
    parser.add_argument('--max_stocks', type=int, default=0,
                        help='最大股票数，0表示全部')
    parser.add_argument('--full', action='store_true',
                        help='全量拉取（忽略已有缓存）')
    args = parser.parse_args()
    
    if args.daily:
        return fetch_daily_increment(args)
    else:
        return fetch_full_history(args)


if __name__ == '__main__':
    success = main()
    sys.exit(0 if success else 1)