#!/usr/bin/env python3
"""
增量更新引擎 - factor_ic 公共模块

功能：
1. 读取现有缓存
2. 筛选缺失日期
3. 逐日计算 IC（复用 ic_calculator.calculate_single_day_ic）
4. 合并去重（新值覆盖旧值）
5. 重算统计指标（复用 ic_calculator.calculate_ic_statistics）

作者: 云瑶
日期: 2026-05-22
"""

import json
import pandas as pd
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional, Tuple, Any

# 导入 IC 计算核心函数
from .ic_calculator import (
    calculate_single_day_ic,
    calculate_ic_statistics
)

# 导入类型转换
from .convert_types import convert_to_native_types


def get_cache_latest_date(cache_path: Path) -> Optional[str]:
    """
    获取缓存最新日期
    
    参数:
        cache_path: IC 结果缓存路径
    
    返回:
        最新日期字符串（YYYY-MM-DD），若缓存不存在则返回 None
    """
    if not cache_path.exists():
        return None
    
    try:
        with open(cache_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        dates = data.get('dates', [])
        if not dates:
            return None
        
        return dates[-1]  # 返回最后一个日期（已排序）
    
    except Exception:
        return None


def read_existing_cache(cache_path: Path) -> Tuple[Optional[Dict], List[str], List[Optional[float]]]:
    """
    读取现有缓存数据
    
    参数:
        cache_path: IC 结果缓存路径
    
    返回:
        (existing_data, existing_dates, existing_ic_values)
        - existing_data: 完整缓存数据（None 表示不存在）
        - existing_dates: 已有日期列表
        - existing_ic_values: 已有 IC 值列表
    
    异常:
        FileNotFoundError: 缓存不存在（外部处理）
        JSONDecodeError: 缓存损坏（严重错误）
    """
    if not cache_path.exists():
        return None, [], []
    
    with open(cache_path, 'r', encoding='utf-8') as f:
        existing_data = json.load(f)
    
    existing_dates = existing_data.get('dates', [])
    existing_ic_values = existing_data.get('ic_values', [])
    
    return existing_data, existing_dates, existing_ic_values


def calculate_missing_dates_ic(
    factor_df_full: pd.DataFrame,
    return_df_full: pd.DataFrame,
    missing_dates: List[str],
    factor_col: str,
    return_col: str = 'forward_return',
    min_stocks: int = 10
) -> Tuple[List[str], List[Optional[float]], Dict]:
    """
    计算缺失日期的 IC
    
    参数:
        factor_df_full: 全量因子数据
        return_df_full: 全量收益数据
        missing_dates: 缺失日期列表
        factor_col: 因子列名
        return_col: 收益列名
        min_stocks: 最小股票数
    
    返回:
        (new_dates, new_ic_values, diagnostics)
        - new_dates: 实际计算日期列表（有数据的日期）
        - new_ic_values: 新计算的 IC 值列表
        - diagnostics: 诊断信息字典
    
    规范:
        增量计算必须复用 calculate_single_day_ic，确保算法一致性
    """
    print(f"\n[增量计算] 计算缺失日期 IC（{len(missing_dates)} 天）...")
    
    missing_set = set(missing_dates)
    factor_df_new = factor_df_full[factor_df_full['date'].isin(missing_set)]
    return_df_new = return_df_full[return_df_full['date'].isin(missing_set)]
    
    # 诊断信息
    dates_in_cache = set(factor_df_full['date'].unique())
    dates_not_in_cache = missing_set - dates_in_cache
    
    diagnostics = {
        'dates_not_in_cache': sorted(dates_not_in_cache)[:10],
        'dates_not_in_cache_count': len(dates_not_in_cache),
        'has_data': not factor_df_new.empty
    }
    
    if dates_not_in_cache:
        print(f"  [警告] {len(dates_not_in_cache)} 个缺失日期不在当前缓存范围")
        examples = diagnostics['dates_not_in_cache'][:5]
        print(f"  [警告] 示例日期: {examples}")
    
    if factor_df_new.empty:
        print("  [诊断] 缺失日期无有效数据，跳过增量计算")
        return [], [], diagnostics
    
    print(f"  - 筛选后数据: {len(factor_df_new)} 行")
    
    # 逐日计算 IC
    new_dates = sorted(factor_df_new['date'].unique())
    new_ic_values = []
    skipped_count = 0
    
    for date in new_dates:
        day_factor = factor_df_new[factor_df_new['date'] == date]
        day_return = return_df_new[return_df_new['date'] == date]
        
        # 合并
        merged = day_factor.merge(day_return, on=['date', 'asset'], how='inner')
        
        # 使用核心函数计算单日 IC（确保算法一致性）
        ic_value = calculate_single_day_ic(
            merged,
            factor_col=factor_col,
            return_col=return_col,
            min_stocks=min_stocks
        )
        
        if ic_value is not None:
            new_ic_values.append(round(ic_value, 6))
        else:
            new_ic_values.append(None)
            skipped_count += 1
    
    print(f"  - 计算完成: {len(new_dates)} 天，{len([v for v in new_ic_values if v is not None])} 天有效 IC")
    if skipped_count > 0:
        print(f"  - {skipped_count} 天因股票数不足跳过")
    
    return new_dates, new_ic_values, diagnostics


def merge_ic_data(
    existing_dates: List[str],
    existing_ic_values: List[Optional[float]],
    new_dates: List[str],
    new_ic_values: List[Optional[float]]
) -> Tuple[List[str], List[Optional[float]], Dict]:
    """
    合并 IC 数据（去重，新值覆盖旧值）
    
    参数:
        existing_dates: 已有日期列表
        existing_ic_values: 已有 IC 值列表
        new_dates: 新计算日期列表
        new_ic_values: 新计算 IC 值列表
    
    返回:
        (all_dates, all_ic_values, merge_info)
        - all_dates: 合并后日期列表（已排序）
        - all_ic_values: 合并后 IC 值列表
        - merge_info: 合并信息（重叠日期等）
    
    规范:
        使用字典去重，新值优先（后写入覆盖前写入）
    """
    print("\n[数据合并] 合并历史数据和新计算数据...")
    
    # 检查重叠
    existing_set = set(existing_dates)
    new_set = set(new_dates)
    overlap_dates = existing_set & new_set
    
    merge_info = {
        'overlap_dates': sorted(overlap_dates),
        'overlap_count': len(overlap_dates),
        'existing_count': len(existing_dates),
        'new_count': len(new_dates)
    }
    
    if overlap_dates:
        print(f"  [警告] 发现 {len(overlap_dates)} 个重叠日期，将使用新值覆盖")
        examples = merge_info['overlap_dates'][:5]
        print(f"  [警告] 示例: {examples}")
    
    # 使用字典去重（新值覆盖旧值）
    date_ic_map = {}
    
    # 先写入历史值（过滤 None）
    for date, ic in zip(existing_dates, existing_ic_values):
        if ic is not None:
            date_ic_map[date] = ic
    
    # 再写入新值（覆盖旧值）
    for date, ic in zip(new_dates, new_ic_values):
        if ic is not None:
            date_ic_map[date] = ic
    
    # 按日期排序
    all_dates = sorted(date_ic_map.keys())
    all_ic_values = [date_ic_map[d] for d in all_dates]
    
    print(f"  - 合并后总计: {len(all_dates)} 天")
    
    return all_dates, all_ic_values, merge_info


def recalculate_statistics(
    all_dates: List[str],
    all_ic_values: List[Optional[float]],
    rolling_window: int = 20,
    rolling_min_periods: int = 10
) -> Dict:
    """
    重新计算统计指标
    
    参数:
        all_dates: 合并后日期列表
        all_ic_values: 合并后 IC 值列表
        rolling_window: 滚动窗口
        rolling_min_periods: 滚动最小数据点
    
    返回:
        统计指标字典（ic_mean, ic_std, icir, positive_ratio, rolling_ic_mean 等）
    
    规范:
        增量模式必须使用 calculate_ic_statistics 重算统计（不手工构建）
    """
    print("\n[统计重算] 重新计算统计指标...")
    
    # 过滤有效 IC 值
    valid_indices = [i for i, ic in enumerate(all_ic_values) if ic is not None]
    valid_dates = [all_dates[i] for i in valid_indices]
    valid_ic = [all_ic_values[i] for i in valid_indices]
    
    if not valid_ic:
        print("  [警告] 无有效 IC 值，返回空统计")
        return {
            'ic_mean': 0.0,
            'ic_std': 0.0,
            'icir': 0.0,
            'positive_ratio': 0.0,
            'rolling_ic_mean': [],
            'valid_days': 0
        }
    
    # 创建带日期索引的 Series
    ic_series = pd.Series(valid_ic, index=valid_dates)
    
    # 使用核心函数计算统计指标
    result = calculate_ic_statistics(ic_series)
    
    print(f"  - IC 均值: {result['ic_mean']:.4f}")
    print(f"  - ICIR: {result['icir']:.2f}")
    print(f"  - 有效天数: {len(valid_ic)}")
    
    # 将 rolling_ic_mean 映射回 all_dates
    rolling_ic_mean_raw = result.get('rolling_ic_mean', [])
    rolling_ic_mean_aligned = []
    valid_idx = 0
    
    for i in range(len(all_dates)):
        if i in valid_indices:
            rolling_ic_mean_aligned.append(rolling_ic_mean_raw[valid_idx])
            valid_idx += 1
        else:
            rolling_ic_mean_aligned.append(None)
    
    result['rolling_ic_mean_aligned'] = rolling_ic_mean_aligned
    result['valid_indices'] = valid_indices
    result['valid_days'] = len(valid_ic)
    
    return result


def incremental_update_ic(
    output_path: Path,
    factor_df_full: pd.DataFrame,
    return_df_full: pd.DataFrame,
    raw_metadata: Dict,
    factor_name: str,
    factor_col: str,
    return_col: str = 'forward_return',
    min_stocks: int = 10
) -> Dict:
    """
    执行增量更新
    
    参数:
        output_path: 输出文件路径
        factor_df_full: 全量因子数据
        return_df_full: 全量收益数据
        raw_metadata: 原始数据元信息
        factor_name: 因子名称
        factor_col: 因子列名
        return_col: 收益列名
        min_stocks: 最小股票数
    
    返回:
        增量更新结果字典
    
    流程:
        1. 读取现有缓存
        2. 确定缺失日期
        3. 计算缺失日期 IC
        4. 合并数据
        5. 重算统计
        6. 构建输出
    """
    print("=" * 60)
    print(f"增量更新: {factor_name}")
    print("=" * 60)
    
    # 1. 读取现有缓存
    print("\n[1/5] 读取现有缓存...")
    try:
        existing_data, existing_dates, existing_ic_values = read_existing_cache(output_path)
        print(f"  - 现有数据: {len(existing_dates)} 天")
    except json.JSONDecodeError as e:
        print(f"  [严重] 缓存文件损坏: {e}")
        raise RuntimeError(f"缓存文件损坏，请删除后重算: {output_path}") from e
    
    if existing_data is None:
        print("  - 缓存不存在，需要全量计算")
        return {'update_mode': 'need_full', 'reason': 'cache_not_found'}
    
    # 2. 确定缺失日期
    print("\n[2/5] 确定缺失日期...")
    cache_dates = set(existing_dates)
    all_factor_dates = set(factor_df_full['date'].unique())
    
    missing_dates = sorted(all_factor_dates - cache_dates)
    
    if not missing_dates:
        print("  - 无缺失日期，数据已完整")
        return existing_data  # 直接返回缓存
    
    print(f"  - 缺失日期: {len(missing_dates)} 天")
    print(f"  - 示例: {missing_dates[:5]}")
    
    # 3. 计算缺失日期 IC
    new_dates, new_ic_values, diagnostics = calculate_missing_dates_ic(
        factor_df_full=factor_df_full,
        return_df_full=return_df_full,
        missing_dates=missing_dates,
        factor_col=factor_col,
        return_col=return_col,
        min_stocks=min_stocks
    )
    
    if not new_dates:
        print("  [诊断] 无新数据可计算，返回现有缓存")
        return existing_data
    
    # 4. 合并数据
    all_dates, all_ic_values, merge_info = merge_ic_data(
        existing_dates=existing_dates,
        existing_ic_values=existing_ic_values,
        new_dates=new_dates,
        new_ic_values=new_ic_values
    )
    
    # 5. 重算统计
    stats = recalculate_statistics(all_dates, all_ic_values)
    
    # 6. 构建输出（简化版，不含五维度判断）
    # 注意：这里只返回增量合并后的数据，五维度判断需要外部调用 calculate_ic_with_direction_verification
    result = {
        'factor_name': factor_name,
        'calculation_date': datetime.now().isoformat(),
        'dates': all_dates,
        'ic_values': all_ic_values,
        'rolling_ic_mean': stats['rolling_ic_mean_aligned'],
        'ic_mean': stats['ic_mean'],
        'ic_std': stats['ic_std'],
        'icir': stats['icir'],
        'positive_ratio': stats['positive_ratio'],
        'sample_stats': {
            'total_days': raw_metadata['total_days'],
            'valid_days': stats['valid_days'],
            'avg_stocks_per_day': raw_metadata['avg_stocks_per_day'],
            'avg_stocks_period': {
                'start': all_dates[0],
                'end': all_dates[-1],
                'description': '增量更新合并后的日期范围'
            }
        },
        'update_mode': 'incremental',
        'incremental_info': {
            'new_dates_count': len(new_dates),
            'overlap_count': merge_info['overlap_count'],
            'diagnostics': diagnostics
        }
    }
    
    # 保存
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(convert_to_native_types(result), f, ensure_ascii=False, indent=2)
    
    print(f"\n✓ 增量更新完成！新增 {len(new_dates)} 天，总计 {len(all_dates)} 天")
    print(f"✓ 结果已保存: {output_path}")
    
    return result


def should_use_incremental(
    output_path: Path,
    factor_df: pd.DataFrame,
    force_full: bool = False
) -> bool:
    """
    判断是否使用增量模式
    
    参数:
        output_path: 输出文件路径
        factor_df: 因子数据 DataFrame
        force_full: 是否强制全量
    
    返回:
        True = 使用增量模式，False = 使用全量模式
    
    判断逻辑:
        force_full = True → 全量
        缓存不存在 → 全量
        缓存存在 + 缓存日期 >= 因子日期 → skip（无需更新）
        缓存存在 + 缓存日期 < 因子日期 → 增量
    """
    if force_full:
        print("  [模式判断] 强制全量计算")
        return False
    
    if not output_path.exists():
        print("  [模式判断] 缓存不存在，全量计算")
        return False
    
    # 读取缓存最新日期
    cache_latest = get_cache_latest_date(output_path)
    if cache_latest is None:
        print("  [模式判断] 缓存日期为空，全量计算")
        return False
    
    # 因子数据最新日期
    factor_latest = str(factor_df['date'].max())
    
    if cache_latest >= factor_latest:
        print(f"  [模式判断] 缓存已最新（{cache_latest} >= {factor_latest}），跳过更新")
        return False  # 缓存已最新，无需更新
    
    print(f"  [模式判断] 缓存滞后（{cache_latest} < {factor_latest}），增量更新")
    return True