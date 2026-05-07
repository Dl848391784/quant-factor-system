#!/usr/bin/env python3
"""
内存优化策略测试
"""
import gzip
import json
import gc
import pandas as pd
from pathlib import Path

cache_dir = Path('cache/factor_data')

print('=== 优化策略测试：使用 category 类型 ===')

# 加载 factor_data
factor_path = cache_dir / 'factor_data.json.gz'
with gzip.open(factor_path, 'rt', encoding='utf-8') as f:
    factor_data = json.load(f)

factor_records = factor_data.get('data', [])
del factor_data
gc.collect()

factor_df = pd.DataFrame(factor_records)
del factor_records
gc.collect()

print(f'\n原始 factor_df 内存: {factor_df.memory_usage(deep=True).sum() / 1024 / 1024:.2f} MB')

# 优化：转换为 category 类型
factor_df['date'] = factor_df['date'].astype('category')
factor_df['asset'] = factor_df['asset'].astype('category')

print(f'优化后 factor_df 内存: {factor_df.memory_usage(deep=True).sum() / 1024 / 1024:.2f} MB')
print(f'节省: {(222.37 - factor_df.memory_usage(deep=True).sum() / 1024 / 1024):.2f} MB')

# 加载 return_data
return_path = cache_dir / 'return_data.json.gz'
with gzip.open(return_path, 'rt', encoding='utf-8') as f:
    return_data = json.load(f)

return_records = return_data.get('data', [])
del return_data
gc.collect()

return_df = pd.DataFrame(return_records)
del return_records
gc.collect()

print(f'\n原始 return_df 内存: {return_df.memory_usage(deep=True).sum() / 1024 / 1024:.2f} MB')

# 优化：转换为 category 类型
return_df['date'] = return_df['date'].astype('category')
return_df['asset'] = return_df['asset'].astype('category')

print(f'优化后 return_df 内存: {return_df.memory_usage(deep=True).sum() / 1024 / 1024:.2f} MB')
print(f'节省: {(222.37 - return_df.memory_usage(deep=True).sum() / 1024 / 1024):.2f} MB')

# 总节省
total_saved = (444.75 - (factor_df.memory_usage(deep=True).sum() + return_df.memory_usage(deep=True).sum()) / 1024 / 1024)
print(f'\n总节省内存: {total_saved:.2f} MB ({total_saved / 444.75 * 100:.1f}%)')

# 清理
del factor_df, return_df
gc.collect()

print('\n=== 优化策略测试：只加载必要列 ===')

# 只加载 factor_data 的必要列
with gzip.open(factor_path, 'rt', encoding='utf-8') as f:
    factor_data = json.load(f)

# 只提取需要的字段：date, asset, close
factor_records_light = [
    {'date': r['date'], 'asset': r['asset'], 'close': r['close']}
    for r in factor_data.get('data', [])
]
del factor_data
gc.collect()

factor_df_light = pd.DataFrame(factor_records_light)
del factor_records_light
gc.collect()

# 转换为 category
factor_df_light['date'] = factor_df_light['date'].astype('category')
factor_df_light['asset'] = factor_df_light['asset'].astype('category')

print(f'轻量 factor_df (只有 date, asset, close): {factor_df_light.memory_usage(deep=True).sum() / 1024 / 1024:.2f} MB')

# 只加载 return_data 的必要列
with gzip.open(return_path, 'rt', encoding='utf-8') as f:
    return_data = json.load(f)

# 只提取需要的字段：date, asset, forward_return_1d
return_records_light = [
    {'date': r['date'], 'asset': r['asset'], 'forward_return_1d': r['forward_return_1d']}
    for r in return_data.get('data', [])
]
del return_data
gc.collect()

return_df_light = pd.DataFrame(return_records_light)
del return_records_light
gc.collect()

return_df_light['date'] = return_df_light['date'].astype('category')
return_df_light['asset'] = return_df_light['asset'].astype('category')

print(f'轻量 return_df (只有 date, asset, forward_return_1d): {return_df_light.memory_usage(deep=True).sum() / 1024 / 1024:.2f} MB')

total_light = (factor_df_light.memory_usage(deep=True).sum() + return_df_light.memory_usage(deep=True).sum()) / 1024 / 1024
print(f'\n总内存占用（轻量模式）: {total_light:.2f} MB')
print(f'相比原始节省: {444.75 - total_light:.2f} MB ({(444.75 - total_light) / 444.75 * 100:.1f}%)')

del factor_df_light, return_df_light
gc.collect()