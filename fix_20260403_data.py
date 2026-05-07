#!/usr/bin/env python3.10
"""
修复 2026-04-03 主力净流入数据 - V2

使用东方财富 API 的 TRADE_DATE 过滤参数获取指定日期的数据。
优化：分页获取主力资金，小批次获取流通市值。

作者: 云舟
日期: 2026-04-07
"""

import gzip
import json
import os
import time
import gc
import tempfile
import shutil
from pathlib import Path
from datetime import datetime
from collections import defaultdict

import requests
import pandas as pd

# 配置
CACHE_FILE = Path('/home/admin/.openclaw/workspace/yunzhou/factor_ic_analyzer/cache/main_inflow/main_inflow_history.json.gz')
TARGET_DATE = '2026-04-03'

# 东方财富 API
EASTMONEY_MAIN_INFLOW_URL = 'https://datacenter-web.eastmoney.com/api/data/v1/get'
EASTMONEY_FLOAT_CAP_URL = 'https://datacenter-web.eastmoney.com/api/data/v1/get'

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
    'Referer': 'https://data.eastmoney.com/'
}


def fetch_main_inflow_by_date_all(target_date: str, page_size: int = 500):
    """
    分页获取指定日期的全部主力净流入数据
    
    Args:
        target_date: 目标日期 (YYYY-MM-DD)
        page_size: 每页数量
        
    Returns:
        所有记录列表
    """
    all_records = []
    page_number = 1
    
    while True:
        params = {
            'reportName': 'RPT_DMSK_TS_STOCKNEW',
            'columns': 'ALL',
            'pageSize': page_size,
            'pageNumber': page_number,
            'sortColumns': 'SECURITY_CODE',
            'sortTypes': '1',
            'filter': f"(TRADE_DATE='{target_date}')",
            'token': '894050c76af8597a853f5b408b759f5d',
            'source': 'WEB',
            'client': 'WEB'
        }
        
        print(f"  获取第 {page_number} 页...")
        
        for attempt in range(3):
            try:
                response = requests.get(
                    EASTMONEY_MAIN_INFLOW_URL, 
                    params=params, 
                    headers=HEADERS, 
                    timeout=30
                )
                response.raise_for_status()
                
                data = response.json()
                
                if not data or 'result' not in data:
                    print(f"    无结果数据")
                    break
                
                result = data['result']
                if not result or 'data' not in result:
                    print(f"    结果为空")
                    break
                
                records = result['data']
                all_records.extend(records)
                print(f"    获取 {len(records)} 条，累计 {len(all_records)} 条")
                
                # 检查是否还有更多数据
                count = result.get('count', 0)
                if len(all_records) >= count or len(records) < page_size:
                    print(f"  ✓ 共获取 {len(all_records)} 条")
                    return all_records
                
                page_number += 1
                time.sleep(0.3)
                break
                
            except Exception as e:
                print(f"    尝试 {attempt+1} 失败: {e}")
                time.sleep(1)
        
        if len(records) < page_size:
            break
    
    return all_records


def fetch_float_market_cap_single(stock_code: str):
    """
    单只股票获取流通市值
    
    Args:
        stock_code: 股票代码
        
    Returns:
        流通市值（元）
    """
    params = {
        'reportName': 'RPT_VALUEANALYSIS_DET',
        'columns': 'ALL',
        'pageSize': 5,
        'sortColumns': 'TRADE_DATE',
        'sortTypes': '-1',
        'filter': f'(SECURITY_CODE="{stock_code}")',
        'source': 'WEB',
        'client': 'WEB'
    }
    
    for attempt in range(3):
        try:
            response = requests.get(
                EASTMONEY_FLOAT_CAP_URL,
                params=params,
                headers=HEADERS,
                timeout=15
            )
            response.raise_for_status()
            
            data = response.json()
            
            if data and 'result' in data and data['result'] and 'data' in data['result']:
                record = data['result']['data'][0]
                cap = float(record.get('NOTLIMITED_MARKETCAP_A', 0) or 0)
                if cap > 0:
                    return cap
            
            return None
            
        except Exception as e:
            time.sleep(0.5)
    
    return None


def fetch_float_market_cap_batch_small(stock_codes: list, batch_size: int = 30):
    """
    小批次获取流通市值（避免 URL 过长）
    
    Args:
        stock_codes: 股票代码列表
        batch_size: 批次大小（建议 30 以内）
        
    Returns:
        {stock_code: float_market_cap} 字典
    """
    result = {}
    total = len(stock_codes)
    
    print(f"  共 {total} 只股票，批次大小 {batch_size}")
    
    for i in range(0, total, batch_size):
        batch = stock_codes[i:i+batch_size]
        print(f"  批次 [{i+1}-{min(i+batch_size, total)}/{total}]...")
        
        # 尝试批量获取
        code_filters = [f'(SECURITY_CODE="{code}")' for code in batch]
        filter_str = '(' + ' OR '.join(code_filters) + ')'
        
        params = {
            'reportName': 'RPT_VALUEANALYSIS_DET',
            'columns': 'ALL',
            'pageSize': batch_size * 3,
            'sortColumns': 'TRADE_DATE',
            'sortTypes': '-1',
            'filter': filter_str,
            'source': 'WEB',
            'client': 'WEB'
        }
        
        batch_success = False
        for attempt in range(2):
            try:
                response = requests.post(
                    EASTMONEY_FLOAT_CAP_URL,
                    data=params,
                    headers=HEADERS,
                    timeout=30
                )
                response.raise_for_status()
                
                data = response.json()
                
                if data and 'result' in data and data['result'] and 'data' in data['result']:
                    for record in data['result']['data']:
                        code = record.get('SECURITY_CODE', '')
                        cap = float(record.get('NOTLIMITED_MARKETCAP_A', 0) or 0)
                        if code and cap > 0 and code not in result:
                            result[code] = cap
                    batch_success = True
                    break
                    
            except Exception as e:
                # 如果批量失败，逐只获取
                pass
        
        # 如果批量失败，逐只获取
        if not batch_success:
            for code in batch:
                cap = fetch_float_market_cap_single(code)
                if cap and cap > 0:
                    result[code] = cap
                time.sleep(0.1)
        
        time.sleep(0.2)
    
    print(f"  ✓ 获取到 {len(result)} 只股票的流通市值")
    return result


def atomic_write_gzip(filepath: Path, data: dict):
    """原子写入 gzip JSON 文件"""
    filepath.parent.mkdir(parents=True, exist_ok=True)
    temp_fd, temp_path = tempfile.mkstemp(
        dir=filepath.parent,
        prefix='.tmp_',
        suffix='.json.gz'
    )
    try:
        with os.fdopen(temp_fd, 'wb') as f:
            with gzip.GzipFile(fileobj=f, mode='wb') as gz:
                gz.write(json.dumps(data, ensure_ascii=False, indent=2).encode('utf-8'))
        shutil.move(temp_path, str(filepath))
    except Exception as e:
        if os.path.exists(temp_path):
            os.unlink(temp_path)
        raise e


def main():
    print("="*60)
    print(f"修复主力净流入数据 - {TARGET_DATE} (V2)")
    print("="*60)
    
    # 1. 获取指定日期的全部主力资金数据
    print(f"\n[步骤1] 分页获取 {TARGET_DATE} 的主力资金数据...")
    records = fetch_main_inflow_by_date_all(TARGET_DATE)
    
    if not records:
        print("❌ 无法获取主力资金数据")
        return False
    
    # 2. 解析主力资金数据
    print(f"\n[步骤2] 解析主力资金数据...")
    parsed_data = []
    for r in records:
        try:
            code = r.get('SECURITY_CODE', '')
            if not code:
                continue
            
            # 主力净流入
            main_net_inflow = float(r.get('PRIME_INFLOW', 0) or 0)
            
            # 特大单和大单净流入
            super_in = float(r.get('SUPERDEAL_INFLOW', 0) or 0)
            super_out = float(r.get('SUPERDEAL_OUTFLOW', 0) or 0)
            big_in = float(r.get('BIGDEAL_INFLOW', 0) or 0)
            big_out = float(r.get('BIGDEAL_OUTFLOW', 0) or 0)
            
            super_net = super_in - super_out
            big_net = big_in - big_out
            
            parsed_data.append({
                'code': code,
                'main_net_inflow': main_net_inflow,
                'super_net_inflow': super_net,
                'big_net_inflow': big_net,
                'medium_net_inflow': 0,
                'small_net_inflow': 0
            })
        except Exception as e:
            continue
    
    print(f"  解析成功: {len(parsed_data)} 条")
    
    # 3. 小批次获取流通市值
    print(f"\n[步骤3] 小批次获取流通市值...")
    stock_codes = [d['code'] for d in parsed_data]
    float_cap_data = fetch_float_market_cap_batch_small(stock_codes, batch_size=30)
    
    # 4. 合并数据
    print(f"\n[步骤4] 合并数据...")
    final_records = []
    missing_cap_count = 0
    
    for d in parsed_data:
        code = d['code']
        float_cap = float_cap_data.get(code, 0)
        
        if float_cap <= 0:
            missing_cap_count += 1
        
        main_inflow_ratio = None
        if float_cap > 0 and d['main_net_inflow'] is not None:
            main_inflow_ratio = d['main_net_inflow'] / float_cap
        
        final_records.append({
            'date': TARGET_DATE,
            'asset': code,
            'main_net_inflow': d['main_net_inflow'],
            'float_market_cap': float_cap if float_cap > 0 else None,
            'main_inflow_ratio': main_inflow_ratio,
            'super_net_inflow': d['super_net_inflow'],
            'big_net_inflow': d['big_net_inflow'],
            'medium_net_inflow': d['medium_net_inflow'],
            'small_net_inflow': d['small_net_inflow']
        })
    
    print(f"  合并成功: {len(final_records)} 条")
    print(f"  有流通市值: {len(final_records) - missing_cap_count} 条")
    print(f"  缺少流通市值: {missing_cap_count} 条")
    
    # 5. 加载现有缓存并更新
    print(f"\n[步骤5] 更新缓存文件...")
    with gzip.open(CACHE_FILE, 'rt', encoding='utf-8') as f:
        cache_data = json.load(f)
    
    # 删除旧的 2026-04-03 数据
    original_count = len(cache_data['data'])
    cache_data['data'] = [r for r in cache_data['data'] if r.get('date') != TARGET_DATE]
    removed_count = original_count - len(cache_data['data'])
    print(f"  删除旧数据: {removed_count} 条")
    
    # 追加新数据
    cache_data['data'].extend(final_records)
    
    # 更新元数据
    cache_data['meta']['total_count'] = len(cache_data['data'])
    cache_data['meta']['dates'] = sorted(set(r['date'] for r in cache_data['data']))
    cache_data['meta']['last_updated'] = datetime.now().isoformat()
    
    print(f"  总数据条数: {len(cache_data['data'])}")
    
    # 6. 保存
    print(f"\n[步骤6] 保存缓存...")
    atomic_write_gzip(CACHE_FILE, cache_data)
    print("  ✓ 缓存文件已保存")
    
    # 7. 验证
    print(f"\n[验证]")
    with gzip.open(CACHE_FILE, 'rt', encoding='utf-8') as f:
        verify = json.load(f)
    
    date_counts = defaultdict(int)
    has_cap_count = 0
    for r in verify['data']:
        if 'date' in r:
            date_counts[r['date']] += 1
        if r.get('date') == TARGET_DATE and r.get('float_market_cap') is not None and r.get('float_market_cap') > 0:
            has_cap_count += 1
    
    print(f"  日期分布:")
    for d in sorted(date_counts.keys()):
        marker = " ← 修复" if d == TARGET_DATE else ""
        print(f"    {d}: {date_counts[d]}{marker}")
    
    print(f"\n  {TARGET_DATE} 数据验证:")
    print(f"    数据条数: {date_counts[TARGET_DATE]}")
    print(f"    有流通市值: {has_cap_count}")
    print(f"    流通市值覆盖率: {has_cap_count / date_counts[TARGET_DATE] * 100:.1f}%")
    
    # 显示样本
    samples = [r for r in verify['data'] if r.get('date') == TARGET_DATE][:3]
    print(f"\n  样本数据:")
    for s in samples:
        cap_str = f"{s.get('float_market_cap', 0):.2e}" if s.get('float_market_cap') else "None"
        ratio_str = f"{s.get('main_inflow_ratio', 0):.4f}" if s.get('main_inflow_ratio') else "None"
        print(f"    {s.get('asset')}: 主力净流入={s.get('main_net_inflow', 0):.2e}, 流通市值={cap_str}, 占比={ratio_str}")
    
    print("\n" + "="*60)
    print("修复完成！")
    print("="*60)
    
    return True


if __name__ == '__main__':
    main()