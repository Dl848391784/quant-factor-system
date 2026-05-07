#!/usr/bin/env python3
"""
历史换手率数据拉取脚本（串行按股票拉取）

使用东财 K 线 API，按股票串行拉取历史换手率数据。
支持增量更新、失败重试、进度显示。

API: https://push2his.eastmoney.com/api/qt/stock/kline/get
返回字段包含：日期, 开盘, 收盘, 最高, 最低, 成交量, 成交额, 振幅, 涨跌幅, 涨跌额, 换手率

缓存路径：cache/factor_data/turnover_rate_data.json.gz

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
import random
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Dict, List, Set, Tuple
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# 缓存目录
CACHE_DIR = Path('/home/admin/.openclaw/workspace/yunzhou/factor_ic_analyzer/cache')
FACTOR_DATA_DIR = CACHE_DIR / 'factor_data'
CACHE_FILE = FACTOR_DATA_DIR / 'turnover_rate_data.json.gz'
STOCK_LIST_FILE = CACHE_DIR / 'stock_list.json'

# 东财 K 线 API
EASTMONEY_KLINE_URL = "https://push2his.eastmoney.com/api/qt/stock/kline/get"

# 默认参数
DEFAULT_N_DAYS = 500
DEFAULT_DELAY = 1.0  # 增加默认延迟到1秒，避免API限速
DEFAULT_MAX_RETRIES = 3

# 限速控制参数
CONSECUTIVE_FAILURE_THRESHOLD = 5  # 连续失败阈值，触发暂停
CONSECUTIVE_FAILURE_PAUSE = 30      # 连续失败后的暂停秒数
INTERMEDIATE_SAVE_INTERVAL = 100     # 每拉取多少只股票保存一次中间结果

# 请求头
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Referer": "https://quote.eastmoney.com/",
    "Accept": "*/*",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
}


def create_session() -> requests.Session:
    """
    创建带有重试机制的 requests Session
    
    Returns:
        配置好的 Session 对象
    """
    session = requests.Session()
    session.headers.update(HEADERS)
    
    # 配置重试策略
    retry_strategy = Retry(
        total=3,  # 总重试次数
        backoff_factor=1,  # 退避因子
        status_forcelist=[429, 500, 502, 503, 504],  # 需要重试的状态码
        allowed_methods=["GET"],  # 只对 GET 请求重试
    )
    
    adapter = HTTPAdapter(
        max_retries=retry_strategy,
        pool_connections=10,
        pool_maxsize=10,
    )
    
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    
    return session


def load_stock_list() -> List[Dict]:
    """
    从缓存加载主板股票列表
    
    Returns:
        股票列表 [{'code': str, 'name': str, 'market': str}, ...]
    """
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
        
        # 只保留主板：沪市60开头、深市00开头
        if code.startswith('60') or code.startswith('00'):
            main_board_stocks.append(stock)
    
    return main_board_stocks


def load_cache() -> Optional[Dict]:
    """
    加载现有换手率缓存
    
    Returns:
        缓存数据字典，不存在返回 None
    """
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
    """
    从缓存中获取已有数据的股票代码集合
    
    Args:
        cache_data: 缓存数据
        
    Returns:
        股票代码集合
    """
    if not cache_data:
        return set()
    
    data = cache_data.get('data', [])
    return set(record['asset'] for record in data)


def save_cache(data: Dict) -> None:
    """
    使用 gzip 压缩保存缓存文件
    """
    # 确保目录存在
    FACTOR_DATA_DIR.mkdir(parents=True, exist_ok=True)
    
    # gzip 压缩写入
    with gzip.open(CACHE_FILE, 'wt', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    
    file_size = CACHE_FILE.stat().st_size
    size_mb = file_size / (1024 * 1024)
    print(f"[缓存] 已保存: {CACHE_FILE} ({size_mb:.2f} MB)")


def get_market_code(stock_code: str) -> str:
    """
    根据股票代码获取市场代码
    
    Args:
        stock_code: 股票代码
        
    Returns:
        市场代码：1=沪市, 0=深市
    """
    if stock_code.startswith('6'):
        return '1'  # 沪市
    else:
        return '0'  # 深市


def fetch_stock_history(stock_code: str, start_date: str, end_date: str,
                        retries: int = DEFAULT_MAX_RETRIES,
                        base_delay: float = 1.0,
                        session: Optional[requests.Session] = None) -> Tuple[Optional[List[Dict]], bool]:
    """
    拉取单只股票的历史换手率数据
    
    使用东财 K 线 API:
    https://push2his.eastmoney.com/api/qt/stock/kline/get
    
    Args:
        stock_code: 股票代码
        start_date: 开始日期 (YYYYMMDD)
        end_date: 结束日期 (YYYYMMDD)
        retries: 重试次数
        base_delay: 基础延迟秒数（用于指数退避）
        session: 可选的 requests Session
        
    Returns:
        (换手率数据列表, 是否成功)
        换手率数据列表 [{'date': str, 'asset': str, 'turnover_rate': float}, ...]
        失败返回 (None, False)
    """
    market = get_market_code(stock_code)
    secid = f"{market}.{stock_code}"
    
    params = {
        "cb": "jQuery",  # JSONP 回调函数名
        "secid": secid,
        "fields1": "f1,f2,f3,f4,f5,f6",
        "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
        "klt": "101",  # 日K线
        "fqt": "0",    # 不复权
        "beg": start_date,
        "end": end_date,
        "ut": "fa5fd1943c7b386f172d6893dbfba10b",
        "_": str(int(time.time() * 1000))
    }
    
    # 使用传入的 session 或创建新的
    req_session = session or create_session()
    
    for attempt in range(retries):
        try:
            response = req_session.get(
                EASTMONEY_KLINE_URL,
                params=params,
                timeout=(10, 30),  # (连接超时, 读取超时)
            )
            response.raise_for_status()
            
            # 解析 JSONP 响应
            text = response.text
            # jQuery({...});
            match = re.search(r'jQuery\((.*)\);?', text, re.DOTALL)
            if not match:
                # JSONP 解析失败，可能是限速或空响应
                if attempt < retries - 1:
                    # 指数退避：1秒 -> 2秒 -> 4秒
                    wait_time = base_delay * (2 ** attempt)
                    print(f"\n    ⚠ {stock_code} JSONP解析失败，等待{wait_time:.1f}秒后重试...")
                    time.sleep(wait_time)
                    continue
                return ([], True)  # 空数据但不是失败
            
            json_str = match.group(1)
            data = json.loads(json_str)
            
            # 解析 K 线数据
            # 数据格式：日期,开盘,收盘,最高,最低,成交量,成交额,振幅,涨跌幅,涨跌额,换手率
            klines = data.get('data', {}).get('klines', [])
            
            if not klines:
                return ([], True)  # 空数据但不是失败
            
            records = []
            for kline in klines:
                parts = kline.split(',')
                if len(parts) < 11:
                    continue
                
                date_str = parts[0]  # 格式：2024-01-02
                turnover_str = parts[10]  # 换手率
                
                try:
                    turnover_rate = float(turnover_str)
                    records.append({
                        'date': date_str,
                        'asset': stock_code,
                        'turnover_rate': turnover_rate
                    })
                except (ValueError, TypeError):
                    continue
            
            return (records, True)
            
        except requests.exceptions.ConnectionError as e:
            if attempt < retries - 1:
                # 连接错误，使用更长的退避时间
                wait_time = base_delay * (2 ** attempt) + random.uniform(1, 3)
                print(f"\n    ⚠ {stock_code} 连接错误，等待{wait_time:.1f}秒后重试...")
                time.sleep(wait_time)
            else:
                return (None, False)
                
        except requests.exceptions.Timeout as e:
            if attempt < retries - 1:
                wait_time = base_delay * (2 ** attempt)
                print(f"\n    ⚠ {stock_code} 请求超时，等待{wait_time:.1f}秒后重试...")
                time.sleep(wait_time)
            else:
                return (None, False)
                
        except requests.exceptions.HTTPError as e:
            if attempt < retries - 1:
                wait_time = base_delay * (2 ** attempt) + random.uniform(0, 2)
                print(f"\n    ⚠ {stock_code} HTTP错误({e.response.status_code})，等待{wait_time:.1f}秒后重试...")
                time.sleep(wait_time)
            else:
                return (None, False)
                
        except Exception as e:
            if attempt < retries - 1:
                # 指数退避：1秒 -> 2秒 -> 4秒
                wait_time = base_delay * (2 ** attempt)
                print(f"\n    ⚠ {stock_code} 请求失败({str(e)[:30]})，等待{wait_time:.1f}秒后重试...")
                time.sleep(wait_time)
            else:
                return (None, False)
    
    return (None, False)


def merge_records(existing_data: Optional[Dict], new_records: List[Dict]) -> Dict:
    """
    合并现有数据和新数据，同一股票同一日期只保留最新
    
    Args:
        existing_data: 现有缓存数据
        new_records: 新拉取的数据
        
    Returns:
        合并后的数据字典
    """
    print("\n[合并] 合并数据...")
    
    # 提取现有数据
    existing_records = []
    if existing_data:
        existing_records = existing_data.get('data', [])
        print(f"  现有数据: {len(existing_records)} 条")
    
    print(f"  新数据: {len(new_records)} 条")
    
    # 合并数据
    all_records = existing_records + new_records
    
    # 去重：同一股票同一日期只保留最后一条（最新数据）
    record_map = {}
    for record in all_records:
        key = (record['date'], record['asset'])
        record_map[key] = record
    
    merged_records = list(record_map.values())
    
    # 按日期、股票代码排序
    merged_records.sort(key=lambda x: (x['date'], x['asset']))
    
    # 统计信息
    unique_dates = sorted(set(r['date'] for r in merged_records))
    unique_assets = sorted(set(r['asset'] for r in merged_records))
    
    print(f"  合并后数据: {len(merged_records)} 条")
    print(f"  日期数: {len(unique_dates)}")
    print(f"  股票数: {len(unique_assets)}")
    
    # 构建 cache 数据结构
    now = datetime.now()
    
    cache_data = {
        'meta': {
            'generated_at': now.isoformat(),
            'source': 'eastmoney_kline_api',
            'n_days': len(unique_dates),
            'n_assets': len(unique_assets),
            'date_range': {
                'start': unique_dates[0] if unique_dates else None,
                'end': unique_dates[-1] if unique_dates else None
            },
            'last_updated': now.strftime('%Y-%m-%d %H:%M:%S'),
            'version': '1.0',
            'description': '主板股票历史换手率数据（东财K线API）'
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


def main():
    """
    主函数
    """
    parser = argparse.ArgumentParser(description='拉取历史换手率数据')
    parser.add_argument('--n_days', type=int, default=DEFAULT_N_DAYS,
                        help=f'拉取天数 (默认: {DEFAULT_N_DAYS})')
    parser.add_argument('--max_stocks', type=int, default=0,
                        help='最大股票数，0表示全部 (默认: 0)')
    parser.add_argument('--delay', type=float, default=DEFAULT_DELAY,
                        help=f'请求间隔秒数 (默认: {DEFAULT_DELAY})')
    parser.add_argument('--retries', type=int, default=DEFAULT_MAX_RETRIES,
                        help=f'失败重试次数 (默认: {DEFAULT_MAX_RETRIES})')
    parser.add_argument('--full', action='store_true',
                        help='全量拉取（忽略现有缓存）')
    args = parser.parse_args()
    
    print("=" * 70)
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 开始拉取历史换手率数据")
    print("=" * 70)
    print(f"参数: n_days={args.n_days}, max_stocks={args.max_stocks}, delay={args.delay}s, retries={args.retries}")
    print(f"缓存: {CACHE_FILE}")
    print()
    
    # Step 1: 加载股票列表
    print("[Step 1] 加载主板股票列表...")
    try:
        all_stocks = load_stock_list()
        print(f"  主板股票总数: {len(all_stocks)}")
    except Exception as e:
        print(f"  ✗ 加载股票列表失败: {e}")
        return False
    
    # 限制股票数量（测试用）
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
    start_date = end_date - timedelta(days=args.n_days * 1.5)  # 多预留一些日历日
    start_date_str = start_date.strftime('%Y%m%d')
    end_date_str = end_date.strftime('%Y%m%d')
    
    print(f"\n[Step 3] 日期范围: {start_date.strftime('%Y-%m-%d')} ~ {end_date.strftime('%Y-%m-%d')}")
    
    # Step 4: 串行拉取（带限速检测和中间保存）
    print(f"\n[Step 4] 开始串行拉取...")
    print(f"  限速策略: 连续{CONSECUTIVE_FAILURE_THRESHOLD}只失败暂停{CONSECUTIVE_FAILURE_PAUSE}秒")
    print(f"  中间保存: 每{INTERMEDIATE_SAVE_INTERVAL}只股票保存一次")
    
    all_new_records = []
    success_count = 0
    failed_stocks = []
    
    # 限速控制
    consecutive_failures = 0  # 连续失败计数
    
    total = len(all_stocks)
    start_time = time.time()
    last_save_count = 0  # 上次保存时的成功数量
    
    # 创建带重试机制的 Session
    session = create_session()
    
    for idx, stock in enumerate(all_stocks, 1):
        code = stock['code']
        name = stock['name']
        
        # 计算进度和预估时间
        elapsed = time.time() - start_time
        if idx > 1:
            avg_time = elapsed / (idx - 1)
            remaining = (total - idx + 1) * avg_time
        else:
            remaining = 0
        
        print(f"\r  [{idx}/{total}] {code} {name:8s} | 成功: {success_count} 失败: {len(failed_stocks)} | 预计剩余: {format_time(remaining)}  ", end='', flush=True)
        
        # 检查是否已有数据，决定是全量拉取还是增量
        if code in existing_stocks and not args.full:
            # 已有数据，拉取最近30天增量
            inc_start = end_date - timedelta(days=30)
            inc_start_str = inc_start.strftime('%Y%m%d')
            records, success = fetch_stock_history(code, inc_start_str, end_date_str, args.retries, args.delay, session)
        else:
            # 新股票或全量模式，拉取完整历史
            records, success = fetch_stock_history(code, start_date_str, end_date_str, args.retries, args.delay, session)
        
        if success and records is not None:
            all_new_records.extend(records)
            success_count += 1
            consecutive_failures = 0  # 重置连续失败计数
        elif success:
            # 空数据但成功
            success_count += 1
            consecutive_failures = 0
        else:
            failed_stocks.append(code)
            consecutive_failures += 1
            print(f"\n    ✗ {code} 拉取失败 (连续失败: {consecutive_failures})")
            
            # 限速检测：连续失败达到阈值
            if consecutive_failures >= CONSECUTIVE_FAILURE_THRESHOLD:
                print(f"\n  ⚠ 连续失败{consecutive_failures}只，暂停{CONSECUTIVE_FAILURE_PAUSE}秒避免API封禁...")
                time.sleep(CONSECUTIVE_FAILURE_PAUSE)
                consecutive_failures = 0  # 重置计数
        
        # 中间保存：每拉取100只成功股票保存一次
        if success_count > 0 and success_count % INTERMEDIATE_SAVE_INTERVAL == 0 and success_count > last_save_count:
            print(f"\n  💾 中间保存: 已成功拉取{success_count}只股票，保存缓存...")
            merged_data = merge_records(cache_data, all_new_records)
            save_cache(merged_data)
            last_save_count = success_count
            # 更新 cache_data 以便后续合并
            cache_data = merged_data
        
        # 延迟
        if idx < total:
            time.sleep(args.delay)
    
    print()  # 换行
    
    # Step 5: 对失败股票再尝试一次
    if failed_stocks:
        print(f"\n[Step 5] 对 {len(failed_stocks)} 只失败股票进行最终重试...")
        final_failed = []
        
        for i, code in enumerate(failed_stocks, 1):
            print(f"  [{i}/{len(failed_stocks)}] 重试 {code}...")
            records, success = fetch_stock_history(code, start_date_str, end_date_str, retries=1, base_delay=args.delay, session=session)
            
            if success and records is not None:
                all_new_records.extend(records)
                success_count += 1
                print(f"    ✓ {code} 重试成功")
            elif success:
                print(f"    ✓ {code} 重试成功（无数据）")
                success_count += 1
            else:
                final_failed.append(code)
                print(f"    ✗ {code} 最终失败")
            
            # 重试间隔
            if i < len(failed_stocks):
                time.sleep(args.delay * 2)  # 重试时使用更长延迟
        
        failed_stocks = final_failed
    
    # Step 6: 合并并保存
    print(f"\n[Step 6] 合并数据并保存...")
    merged_data = merge_records(cache_data, all_new_records)
    save_cache(merged_data)
    
    # Step 7: 输出统计
    total_time = time.time() - start_time
    meta = merged_data['meta']
    
    print("\n" + "=" * 70)
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 拉取完成")
    print("=" * 70)
    print(f"总股票数:   {total}")
    print(f"成功数:     {success_count}")
    print(f"失败数:     {len(failed_stocks)}")
    
    if failed_stocks:
        print(f"失败股票:   {', '.join(failed_stocks)}")
    
    print(f"\n日期范围:   {meta['date_range']['start']} ~ {meta['date_range']['end']}")
    print(f"交易日数:   {meta['n_days']}")
    print(f"股票数:     {meta['n_assets']}")
    print(f"总记录数:   {len(merged_data['data'])}")
    print(f"耗时:       {format_time(total_time)}")
    
    return len(failed_stocks) == 0


# ============================================================
# Cron 配置说明
# ============================================================
"""
定时任务配置：

建议执行时间：每周日凌晨执行一次全量更新
（历史数据变化较少，每周更新一次即可）

配置步骤：
1. 编辑 crontab
   crontab -e

2. 添加定时任务（周日凌晨3:00执行）
   
   # 历史换手率数据全量拉取（周日凌晨3:00）
   0 3 * * 0 cd /home/admin/.openclaw/workspace/yunzhou/factor_ic_analyzer && /usr/bin/python3 fetch_turnover_rate_history.py --full >> logs/fetch_turnover_history.log 2>&1

3. 验证定时任务
   crontab -l

执行命令示例：
# 全量拉取（忽略现有缓存）
python3 fetch_turnover_rate_history.py --full

# 增量拉取（只拉取缓存中没有的股票）
python3 fetch_turnover_rate_history.py

# 测试拉取（只拉取前10只股票）
python3 fetch_turnover_rate_history.py --max_stocks 10

# 自定义参数
python3 fetch_turnover_rate_history.py --n_days 300 --delay 0.3 --max_stocks 100

预估耗时：
- 3000只股票 × 0.5秒间隔 = 约25分钟
- 建议在凌晨低峰期执行

注意事项：
- 使用系统 Python 3，已包含 requests 库
- 日志保存在 logs/ 目录
- 失败股票会自动重试3次，最后再统一重试一次
"""

if __name__ == '__main__':
    success = main()
    sys.exit(0 if success else 1)