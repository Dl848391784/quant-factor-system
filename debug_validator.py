#!/usr/bin/env python3
"""
调试验证器数据加载问题
"""

import sys
import json
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent
sys.path.insert(0, str(PROJECT_ROOT))

print("=" * 80)
print("调试验证器数据加载")
print("=" * 80)

# 1. 检查验证器如何加载数据
print("\n1. 检查验证器加载路径...")
from versions.v2.optimizer.ic_directions_validator import _load_ic_analysis_results

ic_data = _load_ic_analysis_results('forward_return_1d')
print(f"\n加载的IC数据:")
for factor_id, data in ic_data.items():
    print(f"  {factor_id}:")
    print(f"    - ic_mean: {data.get('ic_mean')}")
    print(f"    - icir: {data.get('icir')}")

# 2. 直接读取IC分析结果文件
print("\n2. 直接读取IC分析结果文件...")

volume_ratio_file = PROJECT_ROOT / 'volume_ratio_analysis_result.json'
turnover_surge_file = PROJECT_ROOT / 'turnover_surge_analysis_result.json'

print(f"\nvolume_ratio文件路径: {volume_ratio_file}")
print(f"文件存在: {volume_ratio_file.exists()}")

print(f"\nturnover_surge文件路径: {turnover_surge_file}")
print(f"文件存在: {turnover_surge_file.exists()}")

if volume_ratio_file.exists():
    with open(volume_ratio_file, 'r') as f:
        data = json.load(f)
    print(f"\nvolume_ratio分析结果:")
    print(f"  - ic_mean: {data.get('ic_metrics', {}).get('ic_mean')}")
    print(f"  - icir: {data.get('ic_metrics', {}).get('icir')}")

if turnover_surge_file.exists():
    with open(turnover_surge_file, 'r') as f:
        data = json.load(f)
    print(f"\nturnover_surge分析结果:")
    print(f"  - ic_mean: {data.get('ic_metrics', {}).get('ic_mean')}")
    print(f"  - icir: {data.get('ic_metrics', {}).get('icir')}")

# 3. 检查验证器内部逻辑
print("\n3. 检查验证器内部路径计算...")
from versions.v2.optimizer import ic_directions_validator
import inspect

# 获取_load_ic_analysis_results函数源码中的ROOT_DIR
source = inspect.getsource(ic_directions_validator._load_ic_analysis_results)
print("\n验证器ROOT_DIR计算:")
print("  源码路径: Path(__file__).parent")
validator_file = Path(ic_directions_validator.__file__)
print(f"  验证器文件: {validator_file}")
print(f"  parent: {validator_file.parent}")
print(f"  parent.parent: {validator_file.parent.parent}")
print(f"  parent.parent.parent: {validator_file.parent.parent.parent}")
print(f"  parent.parent.parent.parent: {validator_file.parent.parent.parent.parent}")

# 检查验证器中的factor_files映射
print("\n验证器中的factor_files映射:")
print("  volume_ratio: volume_ratio_analysis_result.json")
print("  turnover_surge: turnover_surge_analysis_result.json")

# 预期的ROOT_DIR
expected_root = validator_file.parent.parent.parent.parent
print(f"\n预期ROOT_DIR: {expected_root}")
print(f"预期文件路径: {expected_root / 'volume_ratio_analysis_result.json'}")
print(f"预期文件存在: {(expected_root / 'volume_ratio_analysis_result.json').exists()}")

print("\n" + "=" * 80)