#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
数据完整性检查模块

用于判断因子 IC 计算的运行模式：
- skip: 数据完备，无需重新计算
- full: 需要全量计算
- incremental: 需要增量计算

作者: 云舟
日期: 2026-05-07
"""

import os
import json
import gzip
from pathlib import Path
from datetime import datetime, timedelta
from typing import Tuple, List, Dict, Optional

# 项目根目录
ROOT_DIR = Path(__file__).parent.parent.resolve()

# 缓存路径
FACTOR_DATA_DIR = ROOT_DIR / 'cache' / 'factor_data'
FACTOR_IC_DIR = ROOT_DIR / 'cache' / 'factor_ic'

# 因子对应的字段名映射
FACTOR_FIELDS = {
    'rsi': 'rsi_6',
    'volume_ratio': 'volume_ratio_5',
    'kdj_j': 'kdj_j',
    'bollinger_pb': 'bollinger_pb',
    'turnover_surge': 'turnover_surge',
}

# 因子对应的 IC 输出文件名
IC_OUTPUT_FILES = {
    'rsi': 'rsi_ic.json',
    'volume_ratio': 'volume_ratio_ic.json',
    'kdj_j': 'kdj_j_ic.json',
    'bollinger_pb': 'bollinger_pb_ic.json',
    'turnover_surge': 'turnover_surge_ic.json',
    'main_inflow_ratio': 'main_inflow_ratio_ic.json',
}

# 因子对应的数据源文件名（用于增量判断）
FACTOR_SOURCE_FILES = {
    'rsi': 'factor_data.json.gz',
    'volume_ratio': 'factor_data.json.gz',
    'kdj_j': 'factor_data.json.gz',
    'bollinger_pb': 'factor_data.json.gz',
    'turnover_surge': 'turnover_rate_data.json.gz',  # 特殊数据源
    'main_inflow_ratio': 'main_inflow_data.json.gz',  # 主力净流入数据源
}


def get_source_data_date_range(factor_name: str = None) -> Tuple[Optional[str], Optional[str], List[str]]:
    """
    获取源数据的日期范围
    
    Args:
        factor_name: 因子名称，用于选择数据源文件（可选）
    
    Returns:
        (start_date, end_date, all_dates): 日期范围和所有日期列表
    """
    # 根据因子名称选择数据源文件
    if factor_name and factor_name in FACTOR_SOURCE_FILES:
        source_file = FACTOR_SOURCE_FILES[factor_name]
    else:
        source_file = 'factor_data.json.gz'
    
    factor_path = FACTOR_DATA_DIR / source_file
    
    if not factor_path.exists():
        print(f"[数据完整性] 源数据文件不存在: {factor_path}")
        return None, None, []
    
    try:
        with gzip.open(factor_path, 'rt', encoding='utf-8') as f:
            data = json.load(f)
        
        meta = data.get('meta', {})
        date_range = meta.get('date_range', {})
        
        # 从元数据获取日期范围
        start_date = date_range.get('start')
        end_date = date_range.get('end')
        
        # 从实际数据提取所有日期
        all_dates = sorted(set(r.get('date') for r in data.get('data', []) if r.get('date')))
        
        if not start_date or not end_date:
            if all_dates:
                start_date = all_dates[0]
                end_date = all_dates[-1]
        
        print(f"[数据完整性] 源数据({source_file})日期范围: {start_date} ~ {end_date}, 共 {len(all_dates)} 天")
        return start_date, end_date, all_dates
        
    except Exception as e:
        print(f"[数据完整性] 读取源数据失败: {e}")
        return None, None, []


def get_ic_cache_dates(factor_name: str) -> Tuple[Optional[str], Optional[str], List[str]]:
    """
    获取 IC 缓存文件的日期范围
    
    Args:
        factor_name: 因子名称（rsi, volume_ratio, kdj_j, bollinger_pb）
        
    Returns:
        (start_date, end_date, all_dates): IC 缓存的日期范围
    """
    ic_file = FACTOR_IC_DIR / IC_OUTPUT_FILES.get(factor_name, f'{factor_name}_ic.json')
    
    if not ic_file.exists():
        print(f"[数据完整性] IC 缓存文件不存在: {ic_file}")
        return None, None, []
    
    try:
        with open(ic_file, 'r', encoding='utf-8') as f:
            ic_data = json.load(f)
        
        dates = ic_data.get('dates', [])
        
        if not dates:
            print(f"[数据完整性] IC 缓存无日期数据")
            return None, None, []
        
        start_date = dates[0]
        end_date = dates[-1]
        
        print(f"[数据完整性] IC 缓存日期范围: {start_date} ~ {end_date}, 共 {len(dates)} 天")
        return start_date, end_date, dates
        
    except Exception as e:
        print(f"[数据完整性] 读取 IC 缓存失败: {e}")
        return None, None, []


def check_data_completeness(factor_name: str) -> Tuple[str, List[str], Dict]:
    """
    检查数据完整性，判断运行模式
    
    Args:
        factor_name: 因子名称（rsi, volume_ratio, kdj_j, bollinger_pb, turnover_surge）
        
    Returns:
        (mode, missing_dates, info):
        - mode: 'skip' | 'full' | 'incremental'
        - missing_dates: 需要补充计算的日期列表
        - info: 额外信息字典
    """
    print(f"\n{'='*60}")
    print(f"[数据完整性检查] {factor_name}")
    print(f"{'='*60}")
    
    info = {
        'factor_name': factor_name,
        'checked_at': datetime.now().isoformat(),
    }
    
    # 获取源数据日期范围（传入因子名称以选择正确的数据源）
    src_start, src_end, src_dates = get_source_data_date_range(factor_name)
    
    if not src_start or not src_end:
        print("[数据完整性] 源数据不存在，无法计算")
        return 'skip', [], info
    
    info['source_start'] = src_start
    info['source_end'] = src_end
    info['source_days'] = len(src_dates)
    
    # 获取 IC 缓存日期范围
    ic_start, ic_end, ic_dates = get_ic_cache_dates(factor_name)
    
    if not ic_start or not ic_end:
        print("[数据完整性] IC 缓存不存在，需要全量计算")
        info['mode_reason'] = 'IC 缓存不存在'
        return 'full', src_dates, info
    
    info['ic_start'] = ic_start
    info['ic_end'] = ic_end
    info['ic_days'] = len(ic_dates)
    
    # 检查日期覆盖情况
    src_dates_set = set(src_dates)
    ic_dates_set = set(ic_dates)
    
    # 计算缺失日期
    missing_dates = sorted(src_dates_set - ic_dates_set)
    
    # 计算多余日期（IC 缓存中有但源数据中没有的）
    extra_dates = sorted(ic_dates_set - src_dates_set)
    
    info['missing_dates_count'] = len(missing_dates)
    info['extra_dates_count'] = len(extra_dates)
    
    # 判断运行模式
    if len(missing_dates) == 0 and len(extra_dates) == 0 and ic_end == src_end:
        print(f"[数据完整性] 数据完备，无需更新")
        print(f"  源数据: {src_start} ~ {src_end} ({len(src_dates)} 天)")
        print(f"  IC 缓存: {ic_start} ~ {ic_end} ({len(ic_dates)} 天)")
        info['mode_reason'] = '数据完备'
        return 'skip', [], info
    
    if ic_start != src_start or len(ic_dates) < len(src_dates) * 0.5:
        # IC 缓存日期范围与源数据差异过大，建议全量计算
        print(f"[数据完整性] IC 缓存日期范围差异过大，需要全量计算")
        print(f"  源数据: {src_start} ~ {src_end} ({len(src_dates)} 天)")
        print(f"  IC 缓存: {ic_start} ~ {ic_end} ({len(ic_dates)} 天)")
        info['mode_reason'] = '日期范围差异过大'
        return 'full', src_dates, info
    
    # IC 缓存存在，只需要增量补充
    if missing_dates:
        print(f"[数据完整性] 需要增量计算 {len(missing_dates)} 天")
        print(f"  缺失日期: {missing_dates[0]} ~ {missing_dates[-1]}")
        info['mode_reason'] = '增量补充'
        info['missing_dates_range'] = f"{missing_dates[0]} ~ {missing_dates[-1]}"
        return 'incremental', missing_dates, info
    
    # IC 缓存完整但有多余日期（可能是源数据删除了部分数据）
    print(f"[数据完整性] IC 缓存有多余数据，建议全量重算")
    info['mode_reason'] = 'IC 缓存有多余日期'
    return 'full', src_dates, info


def get_factor_field(factor_name: str) -> str:
    """
    获取因子对应的字段名
    
    Args:
        factor_name: 因子名称
        
    Returns:
        字段名
    """
    return FACTOR_FIELDS.get(factor_name, factor_name)


def get_ic_output_path(factor_name: str) -> Path:
    """
    获取 IC 输出文件路径
    
    Args:
        factor_name: 因子名称
        
    Returns:
        输出文件路径
    """
    return FACTOR_IC_DIR / IC_OUTPUT_FILES.get(factor_name, f'{factor_name}_ic.json')


if __name__ == '__main__':
    # 测试
    mode, missing_dates, info = check_data_completeness('rsi')
    print(f"\n结果: mode={mode}, missing_count={len(missing_dates)}")
    print(f"信息: {json.dumps(info, indent=2, ensure_ascii=False)}")