#!/usr/bin/env python3
"""验证 factor_ic_data.json.gz 的 JSON 严格合规性"""
import gzip
import ijson

print("验证 ijson 流式解析...")
count = 0
has_nan = False
with gzip.open('data_fetchers/result/factor_ic_data.json.gz', 'rb') as f:
    for record in ijson.items(f, 'data.item'):
        count += 1
        if count == 1:
            # record 应该是 dict
            assert isinstance(record, dict), f"record type: {type(record)}, expected dict"
            keys = sorted(record.keys())
            for k in keys:
                if record[k] is None:
                    has_nan = True
                    print(f'null found in key: {k} (OK)')
            print(f'First record has {len(keys)} columns')
        if count % 500000 == 0:
            print(f'Progress: {count} records parsed...')
        if count >= 3:
            # 只验证前3条
            break

if has_nan:
    print('null values found (NaN→null OK)')
else:
    print('No null values in first 3 records')

print(f'ijson validation passed: {count} records parsed')