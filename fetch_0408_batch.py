#!/usr/bin/env python3
"""分批拉取 2026-04-08 换手率数据"""

import gzip
import json
import time
import os
from datetime import datetime
from pathlib import Path
import baostock as bs

CACHE_FILE = Path('cache/factor_data/turnover_rate_data.json.gz')
STOCK_LIST_FILE = Path('cache/stock_list.json')
LOCK_FILE = Path('cache/factor_data/fetch_0408.lock')
LOG_FILE = Path('logs/fetch_0408_batch.log')
TARGET_DATE = '2026-04-08'

Path('logs').mkdir(exist_ok=True)

def log(msg):
    ts = datetime.now().strftime('%H:%M:%S')
    line = f'[{ts}] {msg}'
    print(line, flush=True)
    with open(LOG_FILE, 'a') as f:
        f.write(line + '\n')

# 创建锁文件
with open(LOCK_FILE, 'w') as f:
    f.write(f'started: {datetime.now().isoformat()}\n')

log(f'开始拉取 {TARGET_DATE}')

# 加载股票
with open(STOCK_LIST_FILE, 'r', encoding='utf-8') as f:
    stocks = json.load(f).get('stocks', [])

main_board = [s for s in stocks if (s['code'].startswith('60') or s['code'].startswith('00')) 
               and not s['code'].startswith('30') and not s['code'].startswith('688')
               and 'ST' not in s.get('name', '') and '退市' not in s.get('name', '')]

log(f'主板股票: {len(main_board)} 只')

# 登录
bs.login()
log('已登录')

new_records = []
success, fail, no_data = 0, 0, 0

for idx, stock in enumerate(main_board, 1):
    code = stock['code']
    bs_code = f'sh.{code}' if code.startswith('6') else f'sz.{code}'
    
    if idx % 500 == 0:
        log(f'进度: [{idx}/{len(main_board)}] 成功:{success} 无数据:{no_data} 失败:{fail}')
        # 更新锁文件进度
        with open(LOCK_FILE, 'w') as f:
            f.write(f'progress: {idx}/{len(main_board)}\nsuccess: {success}\n')
    
    try:
        rs = bs.query_history_k_data_plus(bs_code, 'date,code,turn',
            start_date=TARGET_DATE, end_date=TARGET_DATE, frequency='d', adjustflag='3')
        
        if rs.error_code == '0':
            data = []
            while rs.next():
                data.append(rs.get_row_data())
            if data and data[0][2]:
                new_records.append({'date': TARGET_DATE, 'asset': code, 'turnover_rate': float(data[0][2])})
                success += 1
            else:
                no_data += 1
        else:
            fail += 1
    except:
        fail += 1
    
    time.sleep(0.02)  # 缩短延迟

log(f'拉取完成: 成功 {success}, 无数据 {no_data}, 失败 {fail}')
log(f'新增记录: {len(new_records)}')

# 合并保存
with gzip.open(CACHE_FILE, 'rt', encoding='utf-8') as f:
    cache = json.load(f)

old_records = [r for r in cache['data'] if r['date'] != TARGET_DATE]
log(f'移除旧数据: {len(cache["data"]) - len(old_records)} 条')

all_records = old_records + new_records
record_map = {}
for r in all_records:
    record_map[(r['date'], r['asset'])] = r
merged = list(record_map.values())
merged.sort(key=lambda x: (x['date'], x['asset']))

dates = sorted(set(r['date'] for r in merged))
assets = sorted(set(r['asset'] for r in merged))

cache['data'] = merged
cache['meta'] = {
    'generated_at': datetime.now().isoformat(),
    'source': 'baostock', 'n_days': len(dates), 'n_assets': len(assets),
    'date_range': {'start': dates[0], 'end': dates[-1]},
    'last_updated': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
    'version': '2.1', 'description': '主板股票历史换手率数据（baostock）'
}

with gzip.open(CACHE_FILE, 'wt', encoding='utf-8') as f:
    json.dump(cache, f, ensure_ascii=False, indent=2)

log(f'保存完成: {len(merged):,} 条')
log(f'{TARGET_DATE} 数据: {sum(1 for r in merged if r["date"]==TARGET_DATE):,} 条')

bs.logout()

# 完成，删除锁文件
LOCK_FILE.unlink(missing_ok=True)
log('完成!')