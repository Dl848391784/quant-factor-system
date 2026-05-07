#!/usr/bin/env python3
"""
换手率数据每日增量更新脚本（使用 baostock 数据源）

功能：
- 每日凌晨拉取 T-1 交易日的换手率数据
- 合并到历史缓存 turnover_rate_data.json.gz
- 同一股票同一日期只保留最新数据

运行时间：建议在因子数据拉取之后（如 4:30）

使用方式：
    python3 fetch_turnover_rate_daily.py
    python3 fetch_turnover_rate_daily.py --date 2026-04-07  # 指定日期

作者: 云舟
日期: 2026-04-08
更新: 2026-04-09 (数据源改为 baostock)
"""

import sys
import os
import gzip
import json
import time
import gc
import argparse
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Dict, List, Set, Tuple
import requests

# 缓存目录
CACHE_DIR = Path('/home/admin/.openclaw/workspace/yunzhou/factor_ic_analyzer/cache')
FACTOR_DATA_DIR = CACHE_DIR / 'factor_data'
CACHE_FILE = FACTOR_DATA_DIR / 'turnover_rate_data.json.gz'
STOCK_LIST_FILE = CACHE_DIR / 'stock_list.json'

# 请求参数
REQUEST_DELAY = 0.1  # baostock 可以使用更短的延迟
MAX_RETRIES = 3

# 限流控制参数
CONSECUTIVE_FAILURE_THRESHOLD = 5
CONSECUTIVE_FAILURE_PAUSE = 30  # 秒
INTERMEDIATE_SAVE_INTERVAL = 500  # 每500只股票保存一次
MEMORY_THRESHOLD_MB = 900  # 内存阈值（MB）- 缓存加载后约700MB，留200MB缓冲
MEMORY_PAUSE_SECONDS = 20  # 内存超阈值时暂停时间


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
    return f"{mem_mb:.1f}MB"


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


def save_cache(data: Dict) -> None:
    """
    使用 gzip 压缩保存缓存文件
    
    使用临时文件 + 原子重命名，避免写入中断导致文件损坏。
    """
    FACTOR_DATA_DIR.mkdir(parents=True, exist_ok=True)
    
    # 先写入临时文件
    temp_file = CACHE_FILE.with_suffix('.json.gz.tmp')
    with gzip.open(temp_file, 'wt', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    
    # 原子重命名
    temp_file.replace(CACHE_FILE)
    
    file_size = CACHE_FILE.stat().st_size
    size_mb = file_size / (1024 * 1024)
    print(f"[缓存] 已保存: {CACHE_FILE} ({size_mb:.2f} MB)")


def get_market_code(stock_code: str) -> str:
    """根据股票代码获取东财市场代码"""
    return '1' if stock_code.startswith('6') else '0'


def get_latest_date_from_cache(cache_data: Optional[Dict]) -> Optional[str]:
    """从缓存获取最新日期"""
    if not cache_data:
        return None
    
    meta = cache_data.get('meta', {})
    date_range = meta.get('date_range', {})
    end_date = date_range.get('end')
    
    if end_date:
        # 截取日期部分，避免带时间格式（如 "2026-04-22 00:00:00"）
        return end_date.split()[0] if end_date else None
    
    # 从数据中计算
    data = cache_data.get('data', [])
    if not data:
        return None
    
    all_dates = set(r.get('date') for r in data)
    if all_dates:
        latest = max(all_dates)
        # 截取日期部分，避免带时间格式
        return latest.split()[0] if latest else None
    
    return None


def get_stocks_with_date_data(cache_data: Optional[Dict], target_date: str) -> Set[str]:
    """
    返回已有该日期数据的股票集合
    
    Args:
        cache_data: 缓存数据
        target_date: 目标日期 (YYYY-MM-DD)
        
    Returns:
        已有数据的股票代码集合
    """
    if not cache_data:
        return set()
    
    data = cache_data.get('data', [])
    stocks_with_data = set()
    
    for record in data:
        if record.get('date') == target_date:
            stocks_with_data.add(record.get('asset'))
    
    return stocks_with_data


def get_missing_stocks(all_stocks: List[Dict], existing_stocks: Set[str]) -> List[Dict]:
    """
    返回缺失数据的股票列表
    
    Args:
        all_stocks: 全部股票列表
        existing_stocks: 已有数据的股票代码集合
        
    Returns:
        缺失数据的股票列表
    """
    missing_stocks = []
    for stock in all_stocks:
        if stock.get('code') not in existing_stocks:
            missing_stocks.append(stock)
    return missing_stocks


# 东财千股千评 API 配置
EASTMONEY_API_URL = "https://datacenter-web.eastmoney.com/api/data/v1/get"
API_PARAMS = {
    "sortColumns": "SECURITY_CODE",
    "sortTypes": "1",
    "pageSize": "500",
    "pageNumber": "1",
    "reportName": "RPT_DMSK_TS_STOCKNEW",
    "quoteColumns": "f2~01~SECURITY_CODE~CLOSE_PRICE,f8~01~SECURITY_CODE~TURNOVERRATE",
    "columns": "ALL",
    "filter": "",
    "token": "894050c76af8597a853f5b408b759f5d",
}
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Referer": "https://data.eastmoney.com/stockcomment/",
}


def is_main_board_stock(code: str, name: str) -> bool:
    """判断是否为主板股票（剔除创业板/科创板/北交所/ST）"""
    if code.startswith('30') or code.startswith('688') or code.startswith('8') or code.startswith('4'):
        return False
    if 'ST' in name or '退市' in name or '*ST' in name:
        return False
    return code.startswith('60') or code.startswith('00')


def fetch_turnover_by_date_eastmoney(
    target_date: str,
    session: requests.Session,
    retries: int = MAX_RETRIES
) -> Tuple[Optional[List[Dict]], bool]:
    """
    使用东财千股千评 API 拉取指定日期的换手率数据
    
    批量获取所有主板股票当日换手率
    
    Args:
        target_date: 目标日期 (YYYY-MM-DD)
        session: requests Session
        retries: 重试次数
        
    Returns:
        (换手率数据列表, 是否成功)
        换手率数据: [{'date': str, 'asset': str, 'turnover_rate': float}, ...]
    """
    all_records = []
    page = 1
    
    for attempt in range(retries):
        try:
            while True:
                params = API_PARAMS.copy()
                params["pageNumber"] = page
                # 尝试日期过滤（API可能不支持历史日期，仅当日）
                params["filter"] = f"(TRADE_DATE='{target_date}')"
                
                response = session.get(
                    EASTMONEY_API_URL,
                    params=params,
                    headers=HEADERS,
                    timeout=30
                )
                response.raise_for_status()
                data_json = response.json()
                
                # 解析数据
                if page == 1:
                    total_pages = data_json.get("result", {}).get("pages", 0)
                    if total_pages == 0:
                        return ([], True)  # 空数据
                
                result_data = data_json.get("result", {}).get("data", [])
                
                if not result_data:
                    break
                
                # 解析本页数据
                for item in result_data:
                    code = item.get("SECURITY_CODE", "")
                    name = item.get("SECURITY_NAME_ABBR", "")
                    # 东财API返回日期可能带时间（如"2026-04-22 00:00:00"），截取日期部分
                    trade_date_raw = item.get("TRADE_DATE", target_date)
                    trade_date = trade_date_raw.split()[0] if trade_date_raw else target_date
                    turnover_rate = item.get("TURNOVERRATE")
                    
                    # 筛选主板股票
                    if is_main_board_stock(code, name):
                        if turnover_rate is not None and turnover_rate != "-":
                            try:
                                turnover_rate_float = float(turnover_rate)
                                all_records.append({
                                    'date': trade_date,
                                    'asset': code,
                                    'turnover_rate': turnover_rate_float
                                })
                            except (ValueError, TypeError):
                                pass
                
                if page >= total_pages:
                    break
                
                page += 1
                time.sleep(0.1)  # 页间延迟
            
            return (all_records, True)
            
        except Exception as e:
            if attempt < retries - 1:
                wait_time = 2 ** attempt
                time.sleep(wait_time)
            else:
                return (None, False)
    
    return (None, False)


def merge_records(existing_data: Optional[Dict], new_records: List[Dict]) -> Dict:
    """
    合并现有数据和新数据
    
    同一股票同一日期只保留最新数据
    
    注意：此函数会产生内存峰值（约 4 倍数据大小），
    对于大数据量建议使用 merge_records_incremental
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
            'source': 'eastmoney_api',
            'n_days': len(unique_dates),
            'n_assets': len(unique_assets),
            'date_range': {
                'start': unique_dates[0] if unique_dates else None,
                'end': unique_dates[-1] if unique_dates else None
            },
            'last_updated': now.strftime('%Y-%m-%d %H:%M:%S'),
            'version': '2.1',
            'description': '主板股票历史换手率数据（东财API）'
        },
        'data': merged_records
    }
    
    return cache_data


def merge_records_incremental(
    existing_data: Dict,
    new_records_dict: Dict[Tuple[str, str], Dict]
) -> Dict:
    """
    增量合并 - 内存优化版本
    
    不复制现有数据，只追加新数据并去重。
    内存峰值：约 1.5 倍数据大小（而非 4 倍）
    
    Args:
        existing_data: 现有缓存数据（不会被修改）
        new_records_dict: 新数据的字典，key 为 (date, asset)
        
    Returns:
        合并后的缓存数据
    """
    print(f"\n[增量合并] 合并数据...")
    
    existing_records = existing_data.get('data', [])
    print(f"  现有数据: {len(existing_records)} 条")
    print(f"  新数据: {len(new_records_dict)} 条")
    
    # 遍历现有数据，覆盖同 key 的新数据（新数据优先）
    record_map = {}
    for record in existing_records:
        key = (record['date'], record['asset'])
        # 如果新数据中有同 key，用新数据（已去重）
        if key in new_records_dict:
            record_map[key] = new_records_dict[key]
            del new_records_dict[key]  # 从新数据中移除，减少后续处理
        else:
            record_map[key] = record
    
    # 剩余的新数据直接加入
    for key, record in new_records_dict.items():
        record_map[key] = record
    
    # 转换为列表并排序
    merged_records = list(record_map.values())
    merged_records.sort(key=lambda x: (x['date'], x['asset']))
    
    # 释放临时字典内存
    del record_map
    
    # 统计
    unique_dates = sorted(set(r['date'] for r in merged_records))
    unique_assets = sorted(set(r['asset'] for r in merged_records))
    
    print(f"  合并后数据: {len(merged_records)} 条")
    print(f"  日期范围: {unique_dates[0]} ~ {unique_dates[-1]}")
    print(f"  日期数: {len(unique_dates)}")
    print(f"  股票数: {len(unique_assets)}")
    
    # 构建缓存数据结构
    now = datetime.now()
    existing_meta = existing_data.get('meta', {})
    
    cache_data = {
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
            'version': '2.2',
            'description': '主板股票历史换手率数据（东财API，增量合并）'
        },
        'data': merged_records
    }
    
    return cache_data


def get_previous_trading_day(reference_date: Optional[str] = None) -> str:
    """
    获取最近的交易日（通常是 T-1）
    
    简单实现：返回上一个工作日
    真实实现应该查询交易日历或因子数据缓存
    """
    if reference_date:
        base_date = datetime.strptime(reference_date, '%Y-%m-%d')
    else:
        base_date = datetime.now()
    
    # 往前找最近的工作日
    delta = timedelta(days=1)
    target_date = base_date - delta
    
    # 跳过周末
    while target_date.weekday() >= 5:  # 5=Saturday, 6=Sunday
        target_date -= delta
    
    return target_date.strftime('%Y-%m-%d')


def get_trading_date_from_factor_cache() -> Optional[str]:
    """
    从因子数据缓存获取最新的交易日期
    """
    factor_cache_file = FACTOR_DATA_DIR / 'factor_data.json.gz'
    
    if not factor_cache_file.exists():
        return None
    
    try:
        with gzip.open(factor_cache_file, 'rt', encoding='utf-8') as f:
            data = json.load(f)
        
        # 获取最新日期
        all_dates = set(r.get('date') for r in data.get('data', []))
        if all_dates:
            return max(all_dates)
        
        return None
    except Exception as e:
        print(f"[警告] 读取因子数据缓存失败: {e}")
        return None


def format_time(seconds: float) -> str:
    """格式化时间为 HH:MM:SS"""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


def main():
    """主函数"""
    parser = argparse.ArgumentParser(description='换手率数据每日增量更新（东财API）')
    parser.add_argument('--date', type=str, default=None,
                        help='指定日期 (YYYY-MM-DD)，默认为 T-1 交易日')
    parser.add_argument('--delay', type=float, default=REQUEST_DELAY,
                        help=f'请求间隔秒数 (默认: {REQUEST_DELAY})')
    parser.add_argument('--max_stocks', type=int, default=0,
                        help='最大股票数，0表示全部 (默认: 0)')
    parser.add_argument('--full', action='store_true',
                        help='全量拉取，忽略现有缓存')
    args = parser.parse_args()
    
    print("=" * 70)
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 换手率数据每日增量更新（东财API）")
    print("=" * 70)
    
    # Step 0: 创建 Session（东财API无需登录）
    print("\n[Step 0] 创建 requests Session...")
    session = requests.Session()
    session.headers.update(HEADERS)
    print("  ✓ Session 创建成功")
    
    # Step 1: 确定目标日期范围
    print("\n[Step 1] 确定目标日期范围...")
    
    if args.full:
        # 全量拉取：默认最近500个交易日
        start_date_str = (datetime.now() - timedelta(days=500 * 1.5)).strftime('%Y-%m-%d')
        end_date_str = datetime.now().strftime('%Y-%m-%d')
        print(f"  全量拉取模式")
    else:
        # 增量拉取：从缓存的最新日期开始
        cache_data = load_cache()
        latest_date = get_latest_date_from_cache(cache_data)
        
        if latest_date:
            # 从最新日期的下一天开始
            # 兜底：截取日期部分，避免带时间格式（如 "2026-04-22 00:00:00"）
            latest_date_clean = latest_date.split()[0] if latest_date else None
            if latest_date_clean:
                next_day = datetime.strptime(latest_date_clean, '%Y-%m-%d') + timedelta(days=1)
            else:
                print(f"  ⚠ 无效的日期格式: {latest_date}")
                next_day = datetime.now()
            start_date_str = next_day.strftime('%Y-%m-%d')
            print(f"  缓存最新日期: {latest_date}")
        else:
            # 没有缓存，默认拉取最近500个交易日
            start_date_str = (datetime.now() - timedelta(days=500 * 1.5)).strftime('%Y-%m-%d')
            print(f"  无缓存，从头开始")
        
        # 结束日期
        if args.date:
            end_date_str = args.date
        else:
            # 优先从因子数据缓存获取最新交易日
            latest_factor_date = get_trading_date_from_factor_cache()
            if latest_factor_date:
                end_date_str = latest_factor_date
                print(f"  使用因子数据缓存的最新日期: {end_date_str}")
            else:
                end_date_str = get_previous_trading_day()
                print(f"  使用 T-1 工作日: {end_date_str}")
    
    print(f"  拉取日期范围: {start_date_str} ~ {end_date_str}")
    
    # Step 2: 加载现有缓存（增量模式）
    if not args.full:
        print("\n[Step 2] 加载现有缓存...")
        cache_data = load_cache()
        if cache_data:
            meta = cache_data.get('meta', {})
            existing_dates = set(r.get('date') for r in cache_data.get('data', []))
            print(f"  现有日期范围: {meta.get('date_range', {}).get('start')} ~ {meta.get('date_range', {}).get('end')}")
            print(f"  现有交易日数: {len(existing_dates)}")
        else:
            print("  现有缓存不存在，将创建新缓存")
            cache_data = None
    else:
        cache_data = None
    
    # Step 3: 加载股票列表
    print("\n[Step 3] 加载主板股票列表...")
    try:
        stocks = load_stock_list()
        print(f"  主板股票总数: {len(stocks)}")
    except Exception as e:
        print(f"  ✗ 加载股票列表失败: {e}")
        return False
    
    # 检查目标日期的数据完整性
    if not args.full and start_date_str > end_date_str:
        print(f"\n[检查] 缓存日期已覆盖目标日期，检查数据完整性...")
        stocks_with_data = get_stocks_with_date_data(cache_data, end_date_str)
        total_stocks = len(stocks)
        existing_count = len(stocks_with_data)
        
        print(f"  目标日期: {end_date_str}")
        print(f"  主板股票数: {total_stocks}")
        print(f"  已有数据: {existing_count} 只")
        
        if existing_count == total_stocks:
            print(f"\n[完成] 数据已完整，无需更新")
            return True
        else:
            missing_count = total_stocks - existing_count
            print(f"  缺失数据: {missing_count} 只股票")
            
            # 只拉取缺失的股票
            stocks = get_missing_stocks(stocks, stocks_with_data)
            start_date_str = end_date_str  # 只拉取目标日期
            print(f"  将补齐 {len(stocks)} 只缺失股票的数据")
            
            # 如果没有缺失股票（异常情况），直接返回
            if not stocks:
                print(f"\n[完成] 无缺失股票，无需更新")
                return True
    
    # 限制股票数量（测试用）
    if args.max_stocks > 0:
        stocks = stocks[:args.max_stocks]
        print(f"  限制拉取数量: {args.max_stocks}")
    
    # Step 4: 拉取换手率数据（东财API批量获取）
    print(f"\n[Step 4] 开始拉取换手率数据...")
    print(f"  使用东财千股千评 API 批量获取")
    
    # 东财API批量获取目标日期的所有主板股票数据
    new_records_dict = {}
    success_count = 0
    fail_count = 0
    no_data_count = 0
    
    start_time = time.time()
    
    # 批量拉取目标日期的换手率数据
    records, success = fetch_turnover_by_date_eastmoney(end_date_str, session)
    
    if success:
        if records:
            # 直接存入字典，自动去重
            for record in records:
                key = (record['date'], record['asset'])
                new_records_dict[key] = record
            success_count = len(records)
            print(f"\n  ✓ 成功获取 {success_count} 条换手率数据")
        else:
            no_data_count = len(stocks)
            print(f"\n  ⚠ 该日期无数据（可能是非交易日）")
    else:
        fail_count = len(stocks)
        print(f"\n  ✗ 拉取失败")
    
    # Step 5: 合并并保存
    print(f"\n[Step 5] 合并数据并保存...")
    
    if new_records_dict:
        if cache_data is not None:
            # 使用增量合并
            merged_data = merge_records_incremental(cache_data, new_records_dict)
        else:
            # 无历史数据，直接转换
            merged_data = merge_records(None, list(new_records_dict.values()))
        save_cache(merged_data)
    else:
        print("  ⚠ 没有新数据，不更新缓存")
    
    # Step 6: 输出统计
    total_time = time.time() - start_time
    
    print("\n" + "=" * 70)
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 更新完成")
    print("=" * 70)
    print(f"目标日期:   {end_date_str}")
    print(f"成功拉取:   {success_count} 条数据")
    print(f"无数据:     {no_data_count}")
    print(f"失败:       {fail_count}")
    print(f"新增数据:   {len(new_records_dict)} 条")
    print(f"耗时:       {format_time(total_time)}")
    
    # Step 7: 关闭 Session
    print("\n[Step 7] 关闭 Session...")
    session.close()
    print("  ✓ Session 已关闭")
    
    return fail_count == 0


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

   # 换手率数据每日增量更新（凌晨 4:30）
   30 4 * * 2-6 cd /home/admin/.openclaw/workspace/yunzhou/factor_ic_analyzer && /usr/bin/python3 fetch_turnover_rate_daily.py >> logs/fetch_turnover_daily.log 2>&1

3. 验证定时任务
   crontab -l

执行命令示例：
# 默认拉取增量数据
python3 fetch_turnover_rate_daily.py

# 指定日期
python3 fetch_turnover_rate_daily.py --date 2026-04-07

# 全量拉取
python3 fetch_turnover_rate_daily.py --full

注意事项：
- 数据源为东财千股千评 API，实时数据
- 支持增量更新，只拉取缓存最新日期之后的数据
- 请求间隔默认 0.1 秒，避免限流
"""

if __name__ == '__main__':
    success = main()
    sys.exit(0 if success else 1)