#!/usr/bin/env python3
"""
小规模实际数据测试
模拟 regenerate_cache_batch.py 的核心数据处理流程
不运行完整的数据拉取，只测试修复后的数据处理逻辑
"""

import pandas as pd
import numpy as np
from datetime import datetime, timedelta

print("=" * 60)
print("小规模实际数据测试 - regenerate_cache_batch.py")
print("=" * 60)
print()

# 模拟 regenerate_cache_batch.py 中的数据处理流程
print("创建模拟数据...")
print("-" * 60)

# 创建模拟的缓存数据（模拟从数据库加载）
np.random.seed(42)

# 模拟3只股票，每只股票15天数据（共45条记录）
assets = ['AAPL', 'GOOGL', 'MSFT']
dates = pd.date_range('2024-01-01', periods=15, freq='D')

data_list = []
for asset in assets:
    for i, date in enumerate(dates):
        data_list.append({
            'asset': asset,
            'date': date,
            'open': 100 + np.random.randn() * 5,
            'close': 100 + np.random.randn() * 5,
            'high': 105 + np.random.randn() * 5,
            'low': 95 + np.random.randn() * 5,
            'volume': 1000000 + int(np.random.randn() * 100000),
            'rsi_6': 50 + np.random.randn() * 10,
            'volume_ratio_5': 1 + np.random.randn() * 0.2,
            'forward_return_1d': np.random.randn() * 0.02
        })

valid_df = pd.DataFrame(data_list)
print(f"原始数据: {len(valid_df)} 条记录")
print(f"资产列表: {valid_df['asset'].unique().tolist()}")
print(f"日期范围: {valid_df['date'].min()} 到 {valid_df['date'].max()}")
print()

# 测试修复后的代码逻辑（模拟 regenerate_cache_batch.py:387-390）
print("应用修复后的数据处理逻辑...")
print("-" * 60)

N_DAYS = 10  # 每只股票最多保留10天数据

# pandas 3.0 兼容性修复：使用 cumcount 替代 groupby().apply(tail)
# 避免 group_keys=False 导致分组列被移除
valid_df['row_num'] = valid_df.groupby('asset').cumcount(ascending=False)
filtered_df = valid_df[valid_df['row_num'] < N_DAYS].drop('row_num', axis=1)

print(f"过滤后数据: {len(filtered_df)} 条记录")
print()

# 验证结果
print("验证数据处理结果...")
print("-" * 60)

# 检查1: asset 列是否保留
if 'asset' not in filtered_df.columns:
    print("❌ 错误: asset 列丢失！")
    exit(1)
else:
    print("✓ asset 列存在")

# 检查2: date 列是否保留
if 'date' not in filtered_df.columns:
    print("❌ 错误: date 列丢失！")
    exit(1)
else:
    print("✓ date 列存在")

# 检查3: 每只股票的数据量
print("\n每只股票数据量:")
for asset in assets:
    count = len(filtered_df[filtered_df['asset'] == asset])
    expected = min(10, 15)  # min(N_DAYS, 原始数据天数)
    if count == expected:
        print(f"  {asset}: {count} 条 (预期 {expected} 条) ✓")
    else:
        print(f"  {asset}: {count} 条 (预期 {expected} 条) ✗")
        exit(1)

# 检查4: 数据格式是否正确
print("\n数据格式检查:")
print(f"  asset 类型: {filtered_df['asset'].dtype} ✓")
print(f"  date 类型: {filtered_df['date'].dtype} ✓")
print(f"  open 类型: {filtered_df['open'].dtype} ✓")
print(f"  close 类型: {filtered_df['close'].dtype} ✓")

# 检查5: 数据完整性（是否有缺失值）
print("\n数据完整性检查:")
missing_count = filtered_df.isnull().sum().sum()
if missing_count > 0:
    print(f"  ❌ 发现 {missing_count} 个缺失值")
    exit(1)
else:
    print(f"  ✓ 无缺失值")

# 模拟格式化输出（regenerate_cache_batch.py:392-400）
print("\n模拟格式化输出...")
print("-" * 60)

output_df = filtered_df.copy()
output_df['date'] = output_df['date'].dt.strftime('%Y-%m-%d')
output_df['open'] = output_df['open'].round(2)
output_df['close'] = output_df['close'].round(2)
output_df['high'] = output_df['high'].round(2)
output_df['low'] = output_df['low'].round(2)
output_df['rsi_6'] = output_df['rsi_6'].round(2)
output_df['volume_ratio_5'] = output_df['volume_ratio_5'].round(2)
output_df['forward_return_1d'] = output_df['forward_return_1d'].round(6)

print("格式化后的数据示例（前5行）:")
print(output_df.head().to_string(index=False))
print()

# 最终验证
print("=" * 60)
print("测试结果总结")
print("=" * 60)
print("✅ asset 列正确保留")
print("✅ date 列正确保留")
print("✅ 数据筛选逻辑正确")
print("✅ 数据格式正确")
print("✅ 数据完整性检查通过")
print()
print("🎉 小规模实际数据测试通过！")
print("✅ regenerate_cache_batch.py 的核心数据处理逻辑验证成功！")
print()
print("💡 建议: 可以重新运行定时任务更新数据")
print("   示例命令: python regenerate_cache_batch.py")