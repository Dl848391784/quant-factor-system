#!/usr/bin/env python3.10
"""
KDJ_J 因子增量更新脚本

只处理新增日期的数据，避免全量加载

作者: 云舟
日期: 2026-04-10
"""

import pandas as pd
import numpy as np
from pathlib import Path
import gzip
import json
import gc
from typing import Tuple, Optional, Dict, List
import warnings
warnings.filterwarnings('ignore')

# 导入计算函数（从主脚本）
import sys
sys.path.insert(0, str(Path(__file__).parent))

from kdj_j_factor import (
    calculate_kdj_j_factor,
    calculate_kdj_j_ic,
    save_kdj_j_history,
    get_memory_usage_mb,
    check_memory_threshold,
    convert_to_native_types,
    CACHE_DIR,
    KDJ_J_CACHE_DIR,
    HISTORY_FILE,
    OUTPUT_FILE,
    MEMORY_THRESHOLD_MB
)


def get_existing_latest_date() -> Optional[str]:
    """获取现有分析结果的最新日期"""
    if OUTPUT_FILE.exists():
        try:
            with open(OUTPUT_FILE) as f:
                result = json.load(f)
            ic_dates = result.get('ic_series', {}).get('dates', [])
            if ic_dates:
                # 格式可能是 "2026-04-03 00:00:00"
                latest = ic_dates[-1]
                return latest.split()[0] if ' ' in latest else latest
        except Exception as e:
            print(f"[警告] 读取现有结果失败: {e}")
    return None


def get_factor_data_dates() -> Tuple[List[str], str]:
    """获取 factor_data.json.gz 的日期列表和最新日期"""
    factor_path = CACHE_DIR / 'factor_data.json.gz'
    
    with gzip.open(factor_path, 'rt', encoding='utf-8') as f:
        data = json.load(f)
    
    meta = data.get('meta', {})
    dates = meta.get('dates', [])
    if not dates:
        dates = sorted(set(r.get('date') for r in data.get('data', [])))
    
    latest_date = dates[-1] if dates else None
    del data
    gc.collect()
    
    return dates, latest_date


def load_new_dates_data(
    new_dates: List[str],
    data_type: str = 'factor'
) -> Optional[pd.DataFrame]:
    """
    加载新日期的数据（内存优化版）
    
    只加载指定日期的数据，避免全量加载
    
    Args:
        new_dates: 新日期列表
        data_type: 'factor' 或 'return'
        
    Returns:
        DataFrame
    """
    target_dates = set(new_dates)
    
    if data_type == 'factor':
        file_path = CACHE_DIR / 'factor_data.json.gz'
        fields = ['date', 'asset', 'close', 'high', 'low']
    else:
        file_path = CACHE_DIR / 'return_data.json.gz'
        fields = ['date', 'asset', 'forward_return_1d']  # 使用 forward_return_1d
    
    print(f"  加载 {len(new_dates)} 天 {data_type} 数据...", flush=True)
    mem_before = get_memory_usage_mb()
    print(f"  当前内存: {mem_before:.1f}MB", flush=True)
    
    # 使用 json.load 加载（数据量小，内存安全）
    with gzip.open(file_path, 'rt', encoding='utf-8') as f:
        raw_data = json.load(f)
    
    # 提取目标日期数据
    records = []
    for r in raw_data.get('data', []):
        if r.get('date') in target_dates:
            record = {k: r.get(k) for k in fields if k in r}
            records.append(record)
    
    del raw_data, target_dates
    gc.collect()
    
    if not records:
        print(f"  ✗ 无数据", flush=True)
        return None
    
    df = pd.DataFrame(records)
    del records
    gc.collect()
    
    # 类型转换
    df['date'] = df['date'].astype('category')
    df['asset'] = df['asset'].astype('category')
    
    numeric_cols = ['close', 'high', 'low', 'forward_return_1d']
    for col in numeric_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors='coerce')
    
    # 兼容性映射：forward_return_1d -> forward_return
    if 'forward_return_1d' in df.columns:
        df['forward_return'] = df['forward_return_1d']
    
    mem_after = get_memory_usage_mb()
    print(f"  加载完成: {len(df)} 条，内存: {mem_after:.1f}MB (增加 {mem_after - mem_before:.1f}MB)", flush=True)
    
    return df


def run_incremental_update() -> Dict:
    """
    执行增量更新
    
    1. 检查现有结果最新日期
    2. 检查 factor_data 最新日期
    3. 计算新增日期列表
    4. 加载新增数据
    5. 计算 KDJ_J 因子
    6. 计算 IC
    7. 合并到现有结果
    """
    from datetime import datetime
    
    print(f"\n{'='*80}", flush=True)
    print("KDJ_J 因子增量更新", flush=True)
    print(f"{'='*80}", flush=True)
    
    # ========== Step 1: 检查日期范围 ==========
    print(f"\n[Step 1] 检查日期范围...", flush=True)
    
    existing_latest = get_existing_latest_date()
    all_dates, factor_latest = get_factor_data_dates()
    
    print(f"  现有结果最新日期: {existing_latest or '无'}", flush=True)
    print(f"  factor_data最新日期: {factor_latest}", flush=True)
    print(f"  factor_data总天数: {len(all_dates)}", flush=True)
    
    if not factor_latest:
        return {'success': False, 'error': '无法获取factor_data日期'}
    
    if existing_latest and existing_latest >= factor_latest:
        print(f"  ✓ 数据已是最新，无需更新", flush=True)
        return {'success': True, 'message': '数据已是最新'}
    
    # 计算新增日期
    if existing_latest:
        new_dates = [d for d in all_dates if d > existing_latest]
    else:
        # 没有现有结果，加载最近100天（首次运行）
        print(f"  首次运行，加载最近100天", flush=True)
        new_dates = all_dates[-100:]
    
    print(f"  新增日期: {len(new_dates)} 天", flush=True)
    if new_dates:
        print(f"    从 {new_dates[0]} 到 {new_dates[-1]}", flush=True)
    
    if not new_dates:
        return {'success': True, 'message': '无新增数据'}
    
    # ========== Step 2: 加载新增数据 ==========
    print(f"\n[Step 2] 加载新增数据...", flush=True)
    check_memory_threshold(force_print=True)
    
    factor_df = load_new_dates_data(new_dates, 'factor')
    if factor_df is None:
        return {'success': False, 'error': '因子数据加载失败'}
    
    return_df = load_new_dates_data(new_dates, 'return')
    if return_df is None:
        return {'success': False, 'error': '收益数据加载失败'}
    
    check_memory_threshold(force_print=True)
    
    # ========== Step 3: 计算 KDJ_J 因子 ==========
    print(f"\n[Step 3] 计算 KDJ_J 因子...", flush=True)
    check_memory_threshold(force_print=True)
    
    factor_df, factor_stats = calculate_kdj_j_factor(factor_df)
    
    check_memory_threshold(force_print=True)
    
    # ========== Step 4: 计算 IC ==========
    print(f"\n[Step 4] 计算 IC...", flush=True)
    check_memory_threshold(force_print=True)
    
    ic_result = calculate_kdj_j_ic(factor_df, return_df)
    
    check_memory_threshold(force_print=True)
    
    # ========== Step 5: 合并结果 ==========
    print(f"\n[Step 5] 合并结果...", flush=True)
    
    # 加载现有结果
    existing_result = None
    if OUTPUT_FILE.exists():
        try:
            with open(OUTPUT_FILE) as f:
                existing_result = json.load(f)
        except:
            pass
    
    # 合并 IC 时间序列
    new_ic_series = ic_result.get('ic_series')
    if new_ic_series is not None and len(new_ic_series) > 0:
        new_ic_data = {
            'dates': [str(d) for d in new_ic_series.index],
            'ic_values': [round(v, 6) for v in new_ic_series.values],
            'rolling_ic_mean': [round(v, 6) for v in new_ic_series.rolling(20, min_periods=1).mean().values]
        }
        
        if existing_result and 'ic_series' in existing_result:
            # 合并
            combined_dates = existing_result['ic_series']['dates'] + new_ic_data['dates']
            combined_ic = existing_result['ic_series']['ic_values'] + new_ic_data['ic_values']
            combined_rolling = existing_result['ic_series']['rolling_ic_mean'] + new_ic_data['rolling_ic_mean']
            
            ic_series_data = {
                'dates': combined_dates,
                'ic_values': combined_ic,
                'rolling_ic_mean': combined_rolling
            }
        else:
            ic_series_data = new_ic_data
    else:
        ic_series_data = existing_result.get('ic_series', {}) if existing_result else {}
    
    # 计算合并后的 IC 统计
    if ic_series_data.get('ic_values'):
        all_ic_values = ic_series_data['ic_values']
        ic_mean = np.mean(all_ic_values)
        ic_std = np.std(all_ic_values)
        icir = ic_mean / ic_std if ic_std > 0 else 0
        positive_ratio = sum(1 for v in all_ic_values if v > 0) / len(all_ic_values)
        
        ic_metrics = {
            'ic_mean': round(ic_mean, 6),
            'ic_std': round(ic_std, 6),
            'icir': round(icir, 4),
            'positive_ratio': round(positive_ratio, 4),
            'n_days': len(all_ic_values),
            'summary': f'IC均值={ic_mean:.4f}, ICIR={icir:.2f}, 正比例={positive_ratio:.1%}'
        }
    else:
        ic_metrics = existing_result.get('ic_metrics', {}) if existing_result else {}
    
    # 构建完整结果
    result = {
        'success': True,
        'ic_metrics': ic_metrics,
        'ic_series': ic_series_data,
        'layered_result': existing_result.get('layered_result', {}) if existing_result else {},
        'factor_stats': factor_stats,
        'params': {
            'new_dates_count': len(new_dates),
            'new_dates_range': f'{new_dates[0]} ~ {new_dates[-1]}',
            'factor_col': 'kdj_j'
        },
        'generated_at': datetime.now().isoformat()
    }
    
    # ========== Step 6: 保存结果 ==========
    print(f"\n[Step 6] 保存结果...", flush=True)
    
    result = convert_to_native_types(result)
    
    # 保存
    temp_file = OUTPUT_FILE.with_suffix('.json.tmp')
    with open(temp_file, 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    
    temp_file.replace(OUTPUT_FILE)
    
    print(f"  ✓ 已保存: {OUTPUT_FILE}", flush=True)
    
    # 保存因子历史
    save_kdj_j_history(factor_df, {'n': 9, 'm1': 3, 'm2': 3})
    
    gc.collect()
    final_mem = get_memory_usage_mb()
    print(f"\n[内存监控] 最终内存: {final_mem:.1f}MB", flush=True)
    
    print(f"\n{'='*80}", flush=True)
    print("增量更新完成！", flush=True)
    print(f"{'='*80}", flush=True)
    
    return result


if __name__ == '__main__':
    """执行增量更新"""
    result = run_incremental_update()
    
    if result.get('success'):
        print(f"\n更新成功！", flush=True)
        if result.get('params', {}).get('new_dates_count'):
            print(f"新增 {result['params']['new_dates_count']} 天数据", flush=True)
        print(f"IC均值: {result['ic_metrics'].get('ic_mean', 0):.4f}", flush=True)
        print(f"ICIR: {result['ic_metrics'].get('icir', 0):.2f}", flush=True)
    else:
        print(f"\n更新失败: {result.get('error') or result.get('message')}", flush=True)