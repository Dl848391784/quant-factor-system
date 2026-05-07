#!/usr/bin/env python3
"""
主力净流入数据拉取脚本

功能：
- 支持全量历史拉取（--n_days N）
- 支持每日增量拉取（--daily）
- 拉取主力净流入、主力净流入占比、超大单/大单/中单/小单净流入
- 自动重试、限流处理
- 增量更新缓存
- 支持随机延迟规避限流（--random_delay）
- 支持断点续传（记录已完成股票）

数据来源：东财资金流向 API

使用方式：
    python3 fetch_main_inflow.py --n_days 5         # 拉取最近5天数据
    python3 fetch_main_inflow.py --daily            # 每日增量（T-1交易日）
    python3 fetch_main_inflow.py --n_days 5 --full  # 强制全量拉取
    python3 fetch_main_inflow.py --n_days 5 --random_delay  # 随机延迟(20-40秒)
    python3 fetch_main_inflow.py --n_days 5 --random_delay --delay_min 20 --delay_max 40  # 自定义延迟

缓存路径：cache/factor_data/main_inflow_data.json.gz
已完成记录：cache/factor_data/main_inflow_completed.json

作者: 云舟
日期: 2026-04-08
"""

import sys
import os
import gzip
import json
import time
import re
import random
import argparse
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Dict, List, Set, Tuple
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# 缓存目录
CACHE_DIR = Path('/home/admin/.openclaw/workspace/yunzhou/factor_ic_analyzer/cache')
FACTOR_DATA_DIR = CACHE_DIR / 'factor_data'
CACHE_FILE = FACTOR_DATA_DIR / 'main_inflow_data.json.gz'
STOCK_LIST_FILE = CACHE_DIR / 'stock_list.json'
COMPLETED_FILE = FACTOR_DATA_DIR / 'main_inflow_completed.json'  # 已完成股票记录

# 东财资金流向 API（历史数据）
EASTMONEY_FUND_FLOW_URL = "https://push2his.eastmoney.com/api/qt/stock/fflow/daykline/get"

# 请求头
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Referer": "https://quote.eastmoney.com/",
    "Accept": "*/*",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    # 不指定 Accept-Encoding，让 requests 自动处理解压
    "Connection": "keep-alive",
}

# 请求间隔（秒）
REQUEST_DELAY = 0.4
REQUEST_DELAY_MIN = 20  # 随机延迟最小值
REQUEST_DELAY_MAX = 40  # 随机延迟最大值
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
    """加载主板股票列表"""
    if not STOCK_LIST_FILE.exists():
        raise FileNotFoundError(f"股票列表缓存不存在: {STOCK_LIST_FILE}")
    
    with open(STOCK_LIST_FILE, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    stocks = data.get('stocks', [])
    
    # 筛选主板股票：沪市60开头、深市00开头
    # 剔除创业板(30)、科创板(688)、北交所(8/4开头)、ST股票
    main_board_stocks = []
    for stock in stocks:
        code = stock.get('code', '')
        name = stock.get('name', '')
        
        # 剔除创业板、科创板、北交所
        if code.startswith('30') or code.startswith('688') or code.startswith('8') or code.startswith('4'):
            continue
        
        # 剔除 ST 股票
        if 'ST' in name or '退市' in name or '*ST' in name:
            continue
        
        # 只保留主板
        if code.startswith('60') or code.startswith('00'):
            main_board_stocks.append(stock)
    
    return main_board_stocks


def load_cache() -> Optional[Dict]:
    """加载现有主力净流入缓存"""
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


def load_completed() -> Set[str]:
    """加载已成功拉取的股票代码集合"""
    if not COMPLETED_FILE.exists():
        return set()
    
    try:
        with open(COMPLETED_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
        completed = set(data.get('completed', []))
        print(f"[断点续传] 已加载 {len(completed)} 只已完成的股票")
        return completed
    except Exception as e:
        print(f"[断点续传] 读取失败: {e}")
        return set()


def save_completed(completed: Set[str]) -> None:
    """保存已成功拉取的股票代码"""
    FACTOR_DATA_DIR.mkdir(parents=True, exist_ok=True)
    
    data = {
        'completed': sorted(list(completed)),
        'updated_at': datetime.now().isoformat()
    }
    
    with open(COMPLETED_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    
    print(f"[断点续传] 已保存 {len(completed)} 只完成的股票")


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
        prefix='.tmp_main_inflow_',
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


def fetch_stock_fund_flow(
    stock_code: str,
    start_date: str,
    end_date: str,
    session: requests.Session
) -> Tuple[Optional[List[Dict]], bool]:
    """
    拉取单只股票的资金流向数据
    
    Args:
        stock_code: 股票代码
        start_date: 开始日期 (YYYY-MM-DD)
        end_date: 结束日期 (YYYY-MM-DD)
        session: requests Session
        
    Returns:
        (记录列表, 是否成功)
        记录格式: {
            'date': str,
            'asset': str,
            'main_net_inflow': float,        # 主力净流入（元）
            'main_inflow_ratio': float,      # 主力净流入占比（小数）
            'super_net_inflow': float,       # 超大单净流入（元）
            'big_net_inflow': float,         # 大单净流入（元）
            'medium_net_inflow': float,      # 中单净流入（元）
            'small_net_inflow': float        # 小单净流入（元）
        }
        
    API 返回字段（15个）：
    [0] = 日期
    [1] = 主力净流入（元）
    [2] = 超大单净流入（元）
    [3] = 大单净流入（元）
    [4] = 中单净流入（元）
    [5] = 小单净流入（元）
    [6] = 主力净流入占比（%）
    [7] = 超大单净流入占比（%）
    [8] = 大单净流入占比（%）
    [9] = 中单净流入占比（%）
    [10] = 小单净流入占比（%）
    [11] = 收盘价
    [12] = 涨跌幅（%）
    [13-14] = 其他
    """
    market = get_market_code(stock_code)
    secid = f"{market}.{stock_code}"
    
    params = {
        "cb": "jQuery",
        "lmt": "0",  # 0表示全部
        "klt": "101",  # 日K线
        "secid": secid,
        "fields1": "f1,f2,f3,f4,f5,f6,f7,f8",
        "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61,f62,f63,f64,f65,f66,f67",
        "ut": "b2884a393a59ad64002292a3e90d46a5",
        "_": str(int(time.time() * 1000))
    }
    
    for attempt in range(MAX_RETRIES):
        try:
            response = session.get(
                EASTMONEY_FUND_FLOW_URL,
                params=params,
                timeout=(10, 30),
            )
            response.raise_for_status()
            
            # 解析 JSONP 响应
            text = response.text
            match = re.search(r'jQuery\((.*)\);?', text, re.DOTALL)
            if not match:
                return ([], True)  # 空数据
            
            json_str = match.group(1)
            data = json.loads(json_str)
            
            # 解析资金流向数据
            klines = data.get('data', {}).get('klines', [])
            
            if not klines:
                return ([], True)  # 空数据（非交易日或停牌）
            
            records = []
            for kline in klines:
                # 数据格式（15个字段）：
                # 日期,主力净流入,超大单净流入,大单净流入,中单净流入,小单净流入,
                # 主力占比,超大单占比,大单占比,中单占比,小单占比,收盘价,涨跌幅,...
                parts = kline.split(',')
                if len(parts) < 6:
                    continue
                
                try:
                    date_str = parts[0]  # YYYY-MM-DD
                    
                    # 过滤日期范围
                    if start_date and date_str < start_date:
                        continue
                    if end_date and date_str > end_date:
                        continue
                    
                    # 主力净流入（元）
                    main_net_inflow = float(parts[1]) if parts[1] else 0
                    
                    # 超大单净流入（元）
                    super_net_inflow = float(parts[2]) if parts[2] else 0
                    
                    # 大单净流入（元）
                    big_net_inflow = float(parts[3]) if parts[3] else 0
                    
                    # 中单净流入（元）
                    medium_net_inflow = float(parts[4]) if parts[4] else 0
                    
                    # 小单净流入（元）
                    small_net_inflow = float(parts[5]) if parts[5] else 0
                    
                    # 主力净流入占比（百分比转小数）
                    main_inflow_ratio = float(parts[6]) / 100 if len(parts) > 6 and parts[6] else 0
                    
                    record = {
                        'date': date_str,
                        'asset': stock_code,
                        'main_net_inflow': main_net_inflow,
                        'main_inflow_ratio': main_inflow_ratio,
                        'super_net_inflow': super_net_inflow,
                        'big_net_inflow': big_net_inflow,
                        'medium_net_inflow': medium_net_inflow,
                        'small_net_inflow': small_net_inflow
                    }
                    records.append(record)
                    
                except (ValueError, TypeError, IndexError) as e:
                    continue
            
            return (records, True)
            
        except requests.exceptions.RequestException as e:
            if attempt < MAX_RETRIES - 1:
                wait_time = 1.0 * (2 ** attempt)
                time.sleep(wait_time)
            else:
                return (None, False)
        except Exception as e:
            return (None, False)
    
    return (None, False)


def merge_records(existing_data: Optional[Dict], new_records: List[Dict]) -> Dict:
    """
    合并现有数据和新数据
    
    同一股票同一日期只保留最新数据
    """
    print(f"\n[合并] 合并数据...")
    
    existing_records = []
    if existing_data:
        existing_records = existing_data.get('data', [])
        print(f"  现有数据: {len(existing_records)} 条")
    
    print(f"  新数据: {len(new_records)} 条")
    
    # 合并并去重
    all_records = existing_records + new_records
    
    record_map = {}
    for record in all_records:
        key = (record['date'], record['asset'])
        record_map[key] = record
    
    merged_records = list(record_map.values())
    merged_records.sort(key=lambda x: (x['date'], x['asset']))
    
    # 统计
    unique_dates = sorted(set(r['date'] for r in merged_records))
    unique_assets = sorted(set(r['asset'] for r in merged_records))
    
    print(f"  合并后数据: {len(merged_records)} 条")
    print(f"  日期范围: {unique_dates[0]} ~ {unique_dates[-1]}")
    print(f"  日期数: {len(unique_dates)}")
    print(f"  股票数: {len(unique_assets)}")
    
    # 构建缓存数据结构
    now = datetime.now()
    
    cache_data = {
        'meta': {
            'generated_at': now.isoformat(),
            'source': 'eastmoney_fund_flow_api',
            'n_days': len(unique_dates),
            'n_assets': len(unique_assets),
            'date_range': {
                'start': unique_dates[0] if unique_dates else None,
                'end': unique_dates[-1] if unique_dates else None
            },
            'last_updated': now.strftime('%Y-%m-%d %H:%M:%S'),
            'version': '1.0',
            'description': '主板股票主力净流入数据（东财资金流向API）',
            'fields': {
                'main_net_inflow': '主力净流入（元）',
                'main_inflow_ratio': '主力净流入占比（小数）',
                'super_net_inflow': '超大单净流入（元）',
                'big_net_inflow': '大单净流入（元）',
                'medium_net_inflow': '中单净流入（元）',
                'small_net_inflow': '小单净流入（元）'
            }
        },
        'data': merged_records
    }
    
    return cache_data


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


def get_trading_date_from_factor_cache() -> Optional[str]:
    """从因子数据缓存获取最新的交易日期"""
    factor_cache_file = FACTOR_DATA_DIR / 'factor_data.json.gz'
    
    if not factor_cache_file.exists():
        return None
    
    try:
        with gzip.open(factor_cache_file, 'rt', encoding='utf-8') as f:
            data = json.load(f)
        
        all_dates = set(r.get('date') for r in data.get('data', []))
        if all_dates:
            return max(all_dates)
        
        return None
    except Exception as e:
        print(f"[警告] 读取因子数据缓存失败: {e}")
        return None


def fetch_full_history(args) -> bool:
    """全量历史数据拉取"""
    print("=" * 70)
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 开始拉取历史主力净流入数据")
    print("=" * 70)
    print(f"数据源: 东财资金流向 API")
    print(f"参数: n_days={args.n_days}, delay={args.delay}s")
    if args.random_delay:
        print(f"随机延迟: {args.delay_min}s ~ {args.delay_max}s")
    print()
    
    session = create_session()
    
    # Step 1: 加载股票列表
    print("[Step 1] 加载主板股票列表...")
    try:
        stocks = load_stock_list()
        print(f"  主板股票总数: {len(stocks)}")
    except Exception as e:
        print(f"  ✗ 加载股票列表失败: {e}")
        return False
    
    if args.max_stocks > 0:
        stocks = stocks[:args.max_stocks]
        print(f"  限制拉取数量: {args.max_stocks}")
    
    # Step 2: 加载现有缓存
    print("\n[Step 2] 加载现有缓存...")
    cache_data = load_cache() if not args.full else None
    existing_data = get_existing_data(cache_data)
    
    if cache_data:
        meta = cache_data.get('meta', {})
        print(f"  现有日期范围: {meta.get('date_range', {}).get('start')} ~ {meta.get('date_range', {}).get('end')}")
        print(f"  已有数据日期数: {len(existing_data)}")
    
    # 加载已完成股票记录（断点续传）
    print("\n[Step 2.5] 加载断点续传记录...")
    completed_stocks = load_completed() if not args.full else set()
    if completed_stocks:
        print(f"  已完成股票数: {len(completed_stocks)}")
    
    # Step 3: 计算日期范围
    end_date = datetime.now()
    start_date = end_date - timedelta(days=args.n_days * 1.5)
    start_date_str = start_date.strftime('%Y-%m-%d')
    end_date_str = end_date.strftime('%Y-%m-%d')
    print(f"\n[Step 3] 日期范围: {start_date_str} ~ {end_date_str}")
    
    # Step 4: 拉取数据
    print(f"\n[Step 4] 开始拉取数据...")
    
    all_new_records = []
    success_count = 0
    fail_count = 0
    no_data_count = 0
    skip_count = 0
    consecutive_failures = 0
    success_stocks = []  # 成功的股票列表
    failed_stocks = []   # 失败的股票列表
    
    total = len(stocks)
    start_time = time.time()
    last_save_count = 0
    
    for idx, stock in enumerate(stocks, 1):
        code = stock['code']
        name = stock['name']
        
        elapsed = time.time() - start_time
        if idx > 1:
            avg_time = elapsed / (idx - 1)
            remaining = (total - idx + 1) * avg_time
        else:
            remaining = 0
        
        print(f"\r  [{idx}/{total}] {code} {name:8s} | 成功: {success_count} 跳过: {skip_count} 无数据: {no_data_count} 失败: {fail_count} | 预计剩余: {format_time(remaining)}  ", end='', flush=True)
        
        # 检查是否已在已完成列表中（断点续传）
        if not args.full and code in completed_stocks:
            skip_count += 1
            continue
        
        # 检查是否已有该股票在所有目标日期的数据
        skip_data_count = 0
        if not args.full:
            for date in existing_data:
                if date >= start_date_str and code in existing_data[date]:
                    skip_data_count += 1
            # 如果所有日期都有数据，则跳过
            if skip_data_count >= args.n_days:
                skip_count += 1
                completed_stocks.add(code)  # 记录到已完成
                continue
        
        records, success = fetch_stock_fund_flow(code, start_date_str, end_date_str, session)
        
        if success and records is not None:
            if records:
                all_new_records.extend(records)
            success_count += 1
            success_stocks.append(code)
            completed_stocks.add(code)  # 记录到已完成
            consecutive_failures = 0
        elif success:
            no_data_count += 1
            completed_stocks.add(code)  # 无数据也算完成
            consecutive_failures = 0
        else:
            fail_count += 1
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
            save_completed(completed_stocks)  # 同时保存进度
            last_save_count = success_count
            cache_data = merged_data
        
        # 请求间隔
        if idx < total:
            if args.random_delay:
                delay = random.uniform(args.delay_min, args.delay_max)
            else:
                delay = args.delay
            time.sleep(delay)
    
    print()
    
    # Step 5: 合并并保存
    print(f"\n[Step 5] 合并数据并保存...")
    
    if all_new_records:
        merged_data = merge_records(cache_data, all_new_records)
        save_cache(merged_data)
    else:
        print("  ⚠ 没有新数据")
        merged_data = cache_data
    
    # 保存已完成股票记录
    save_completed(completed_stocks)
    
    # 输出统计
    total_time = time.time() - start_time
    
    print("\n" + "=" * 70)
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 拉取完成")
    print("=" * 70)
    print(f"股票总数:   {total}")
    print(f"成功拉取:   {success_count}")
    print(f"跳过(已完成): {skip_count}")
    print(f"无数据:     {no_data_count}")
    print(f"失败:       {fail_count}")
    
    if merged_data:
        meta = merged_data.get('meta', {})
        print(f"\n日期范围:   {meta.get('date_range', {}).get('start')} ~ {meta.get('date_range', {}).get('end')}")
        print(f"交易日数:   {meta.get('n_days', 0)}")
        print(f"股票数:     {meta.get('n_assets', 0)}")
        print(f"总记录数:   {len(merged_data.get('data', []))}")
    
    print(f"\n耗时:       {format_time(total_time)}")
    if success_count + no_data_count > 0:
        print(f"速度:       {total_time/max(success_count+no_data_count,1):.2f} 秒/只")
    
    # 输出成功/失败股票列表
    if success_stocks:
        print(f"\n成功股票列表 ({len(success_stocks)}只):")
        print(f"  {', '.join(success_stocks[:20])}" + ("..." if len(success_stocks) > 20 else ""))
    
    if failed_stocks:
        print(f"\n失败股票列表 ({len(failed_stocks)}只):")
        print(f"  {', '.join(failed_stocks)}")
    
    return fail_count == 0


def fetch_daily_increment(args) -> bool:
    """每日增量数据拉取"""
    print("=" * 70)
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 主力净流入数据每日增量更新")
    print("=" * 70)
    
    # 确定目标日期
    if args.date:
        target_date = args.date
    else:
        # 优先从因子数据缓存获取最新交易日
        latest_factor_date = get_trading_date_from_factor_cache()
        if latest_factor_date:
            target_date = latest_factor_date
            print(f"[日期] 使用因子数据缓存的最新日期: {target_date}")
        else:
            target_date = get_previous_trading_day()
            print(f"[日期] 使用 T-1 工作日: {target_date}")
    
    print(f"[目标日期] {target_date}")
    
    session = create_session()
    
    # Step 1: 加载现有缓存
    print("\n[Step 1] 加载现有缓存...")
    cache_data = load_cache()
    existing_data = get_existing_data(cache_data)
    
    if cache_data:
        meta = cache_data.get('meta', {})
        print(f"  现有日期范围: {meta.get('date_range', {}).get('start')} ~ {meta.get('date_range', {}).get('end')}")
    
    # 检查目标日期是否已存在
    existing_stocks_for_date = existing_data.get(target_date, set())
    print(f"  已有 {target_date} 数据的股票数: {len(existing_stocks_for_date)}")
    
    # Step 2: 加载股票列表
    print("\n[Step 2] 加载主板股票列表...")
    try:
        stocks = load_stock_list()
        print(f"  主板股票总数: {len(stocks)}")
    except Exception as e:
        print(f"  ✗ 加载股票列表失败: {e}")
        return False
    
    if args.max_stocks > 0:
        stocks = stocks[:args.max_stocks]
        print(f"  限制拉取数量: {args.max_stocks}")
    
    # Step 3: 过滤需要拉取的股票
    stocks_to_fetch = [s for s in stocks if s['code'] not in existing_stocks_for_date]
    print(f"  需要拉取的股票数: {len(stocks_to_fetch)}")
    
    if not stocks_to_fetch:
        print("\n所有股票数据已存在，无需更新。")
        return True
    
    # Step 4: 拉取数据
    print(f"\n[Step 3] 拉取 {target_date} 的资金流向数据...")
    
    new_records = []
    success_count = 0
    fail_count = 0
    no_data_count = 0
    
    start_time = time.time()
    
    for idx, stock in enumerate(stocks_to_fetch, 1):
        code = stock['code']
        name = stock['name']
        
        print(f"\r  [{idx}/{len(stocks_to_fetch)}] {code} {name:8s} | 成功: {success_count} 无数据: {no_data_count} 失败: {fail_count}", end='', flush=True)
        
        records, success = fetch_stock_fund_flow(code, target_date, target_date, session)
        
        if success and records is not None:
            if records:
                new_records.extend(records)
            success_count += 1
        elif success:
            no_data_count += 1
        else:
            fail_count += 1
            print(f"\n    ✗ {code} 拉取失败")
        
        # 请求间隔
        if idx < len(stocks_to_fetch):
            time.sleep(args.delay)
    
    print()
    
    # Step 5: 合并并保存
    print(f"\n[Step 4] 合并数据并保存...")
    
    if new_records:
        merged_data = merge_records(cache_data, new_records)
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
    print(f"新增数据:   {len(new_records)} 条")
    print(f"耗时:       {int(total_time // 60)}分{int(total_time % 60)}秒")
    
    return fail_count == 0


def main():
    """主函数"""
    parser = argparse.ArgumentParser(description='拉取主力净流入数据')
    parser.add_argument('--n_days', type=int, default=5,
                        help='历史天数 (默认: 5)')
    parser.add_argument('--daily', action='store_true',
                        help='每日增量模式（拉取T-1交易日）')
    parser.add_argument('--date', type=str, default=None,
                        help='指定日期 (YYYY-MM-DD)')
    parser.add_argument('--max_stocks', type=int, default=0,
                        help='最大股票数，0表示全部')
    parser.add_argument('--delay', type=float, default=REQUEST_DELAY,
                        help=f'请求间隔秒数 (默认: {REQUEST_DELAY})')
    parser.add_argument('--random_delay', action='store_true',
                        help='使用随机延迟规避限流')
    parser.add_argument('--delay_min', type=float, default=REQUEST_DELAY_MIN,
                        help=f'随机延迟最小值 (默认: {REQUEST_DELAY_MIN})')
    parser.add_argument('--delay_max', type=float, default=REQUEST_DELAY_MAX,
                        help=f'随机延迟最大值 (默认: {REQUEST_DELAY_MAX})')
    parser.add_argument('--full', action='store_true',
                        help='全量拉取（忽略已有缓存）')
    args = parser.parse_args()
    
    # 验证随机延迟参数
    if args.random_delay:
        if args.delay_min >= args.delay_max:
            print(f"错误: delay_min ({args.delay_min}) 必须小于 delay_max ({args.delay_max})")
            return False
        print(f"[随机延迟] 启用，范围: {args.delay_min:.1f}s ~ {args.delay_max:.1f}s")
    
    if args.daily:
        return fetch_daily_increment(args)
    else:
        return fetch_full_history(args)


# ============================================================
# Cron 配置说明
# ============================================================
"""
定时任务配置：

建议执行时间：每日凌晨 4:30（在因子数据拉取之后）

配置步骤：
1. 编辑 crontab
   crontab -e

2. 添加定时任务

   # 主力净流入数据每日增量更新（凌晨 4:35）
   35 4 * * 2-6 cd /home/admin/.openclaw/workspace/yunzhou/factor_ic_analyzer && /usr/bin/python3 fetch_main_inflow.py --daily >> logs/fetch_main_inflow_daily.log 2>&1

3. 验证定时任务
   crontab -l

执行命令示例：
# 默认拉取最近5天数据
python3 fetch_main_inflow.py --n_days 5

# 每日增量更新（T-1交易日）
python3 fetch_main_inflow.py --daily

# 指定日期
python3 fetch_main_inflow.py --daily --date 2026-04-07

# 测试模式（只拉取前10只股票）
python3 fetch_main_inflow.py --n_days 5 --max_stocks 10

注意事项：
- 建议在因子数据拉取之后执行，确保日期一致
- 请求间隔默认 0.4 秒，避免 API 限速
- 数据来源：东财资金流向 API
"""

if __name__ == '__main__':
    success = main()
    sys.exit(0 if success else 1)