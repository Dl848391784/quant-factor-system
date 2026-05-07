#!/usr/bin/env python3
"""
东财换手率数据缓存拉取脚本
定时任务：周二至周六凌晨6点执行（在因子数据拉取之后）

拉取主板股票的换手率数据，增量更新到本地缓存。

主板股票定义：
- 沪市主板：60 开头
- 深市主板：00 开头
剔除：创业板(30)、科创板(688)、北交所(8/4开头)、ST股票

API 来源：东财千股千评
https://data.eastmoney.com/stockcomment/

缓存路径：cache/factor_data/turnover_rate_data.json.gz

作者: 云舟
日期: 2026-04-08
"""

import sys
import os
import gzip
import json
import time
import requests
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, List

# 缓存目录
CACHE_DIR = Path('/home/admin/.openclaw/workspace/yunzhou/factor_ic_analyzer/cache/factor_data')
CACHE_FILE = CACHE_DIR / 'turnover_rate_data.json.gz'

# 东财千股千评 API
EASTMONEY_API_URL = "https://datacenter-web.eastmoney.com/api/data/v1/get"

# API 参数
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

# 请求头
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Referer": "https://data.eastmoney.com/stockcomment/",
    "Accept": "*/*",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}


def is_main_board_stock(code: str, name: str) -> bool:
    """
    判断是否为主板股票
    
    沪市主板：60开头
    深市主板：00开头
    
    剔除：创业板(30)、科创板(688)、北交所(8/4开头)、ST股票
    """
    # 剔除创业板、科创板、北交所
    if code.startswith('30') or code.startswith('688') or code.startswith('8') or code.startswith('4'):
        return False
    
    # 剔除 ST 股票
    if 'ST' in name or '退市' in name or '*ST' in name:
        return False
    
    # 只保留主板：沪市60开头、深市00开头
    return code.startswith('60') or code.startswith('00')


def load_cache() -> Optional[Dict]:
    """
    加载现有缓存
    
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


def save_cache(data: Dict) -> None:
    """
    使用 gzip 压缩保存缓存文件
    """
    # 确保目录存在
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    
    # gzip 压缩写入
    with gzip.open(CACHE_FILE, 'wt', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    
    file_size = CACHE_FILE.stat().st_size
    size_mb = file_size / (1024 * 1024)
    print(f"[缓存] 已保存: {CACHE_FILE} ({size_mb:.2f} MB)")


def fetch_turnover_rate_data() -> List[Dict]:
    """
    从东财千股千评 API 拉取换手率数据
    
    Returns:
        换手率数据列表 [{'date': str, 'asset': str, 'turnover_rate': float, 'name': str}, ...]
    """
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
        
        # 重试机制
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
        
        # 解析数据
        if page == 1:
            total_pages = data_json.get("result", {}).get("pages", 0)
            total_count = data_json.get("result", {}).get("count", 0)
            print(f"  总页数: {total_pages}, 总股票数: {total_count}")
        
        result_data = data_json.get("result", {}).get("data", [])
        
        if not result_data:
            print(f"  第 {page} 页返回空数据，获取完成")
            break
        
        # 解析本页数据
        page_added = 0
        for item in result_data:
            # API字段映射：
            # SECUCODE: 股票代码.市场 (如 "600000.SH")
            # SECURITY_CODE: 股票代码 (如 "600000")
            # SECURITY_NAME_ABBR: 股票名称简称
            # TRADE_DATE: 交易日期
            # TURNOVERRATE: 换手率 (对应 quoteColumns 的 f8)
            
            code = item.get("SECURITY_CODE", "")
            name = item.get("SECURITY_NAME_ABBR", "")
            trade_date = item.get("TRADE_DATE", "")
            turnover_rate = item.get("TURNOVERRATE")
            
            # 筛选主板股票
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
        
        # 判断是否最后一页
        if page >= total_pages:
            break
        
        page += 1
        time.sleep(0.1)  # 页间延迟
    
    print(f"\n  ✓ 共获取 {len(all_records)} 条主板股票换手率数据")
    
    return all_records


def merge_and_dedupe(existing_data: Optional[Dict], new_records: List[Dict]) -> Dict:
    """
    合并现有数据和新数据，同一股票同一日期只保留最新
    
    Args:
        existing_data: 现有缓存数据
        new_records: 新拉取的数据
        
    Returns:
        合并后的数据字典
    """
    print("\n[合并去重] 合并现有数据和新数据...")
    
    # 提取现有数据
    existing_records = []
    if existing_data:
        existing_records = existing_data.get('data', [])
        print(f"  现有数据: {len(existing_records)} 条")
    
    print(f"  新数据: {len(new_records)} 条")
    
    # 合并数据
    all_records = existing_records + new_records
    
    # 去重：同一股票同一日期只保留最新
    # 使用 (date, asset) 作为 key，保留最后一条（最新数据）
    record_map = {}
    for record in all_records:
        key = (record['date'], record['asset'])
        record_map[key] = record
    
    merged_records = list(record_map.values())
    
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
            'source': 'eastmoney_api',
            'n_days': len(unique_dates),
            'n_assets': len(unique_assets),
            'date_range': {
                'start': unique_dates[0] if unique_dates else None,
                'end': unique_dates[-1] if unique_dates else None
            },
            'last_updated': now.strftime('%Y-%m-%d %H:%M:%S'),
            'version': '1.0',
            'description': '主板股票换手率数据（东财千股千评）'
        },
        'data': merged_records
    }
    
    return cache_data


def main():
    """
    主函数：加载缓存 → 拉取新数据 → 合并去重 → 保存
    """
    print("=" * 60)
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 开始拉取换手率数据")
    print("=" * 60)
    print("数据源: 东财千股千评 API")
    print("股票范围: 主板股票（60/00开头，剔除创业板/科创板/北交所/ST）")
    print(f"缓存路径: {CACHE_FILE}")
    
    # Step 1: 加载现有缓存
    existing_data = load_cache()
    
    # Step 2: 拉取新数据
    new_records = fetch_turnover_rate_data()
    
    if not new_records:
        print("\n❌ 未获取到任何数据")
        return False
    
    # Step 3: 合并去重
    merged_data = merge_and_dedupe(existing_data, new_records)
    
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


# ============================================================
# Cron 配置说明
# ============================================================
"""
定时任务配置：

建议执行时间：周二至周六凌晨6:00执行（在因子数据拉取之后）

因子数据拉取时间：凌晨4:00
换手率数据拉取时间：凌晨6:00

配置步骤：
1. 编辑 crontab
   crontab -e

2. 添加定时任务（在现有因子数据拉取任务之后添加）
   
   # 因子数据拉取（凌晨4:00）
   0 4 * * 2-6 cd /home/admin/.openclaw/workspace/yunzhou/factor_ic_analyzer && /usr/bin/python3 fetch_factor_data.py >> logs/fetch_factor.log 2>&1
   
   # 换手率数据拉取（凌晨6:00）
   0 6 * * 2-6 cd /home/admin/.openclaw/workspace/yunzhou/factor_ic_analyzer && /usr/bin/python3 fetch_turnover_rate.py >> logs/fetch_turnover.log 2>&1

3. 验证定时任务
   crontab -l

注意：
- 使用系统 Python (/usr/bin/python3)，已包含 requests 等依赖
- 日志文件保存在 logs/ 目录
- 周二至周六执行（对应交易日）
"""

if __name__ == '__main__':
    success = main()
    sys.exit(0 if success else 1)