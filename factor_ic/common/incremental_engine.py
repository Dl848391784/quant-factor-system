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
import logging
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional, Tuple, Any
from enum import Enum

# 更新模式枚举（三值返回，语义清晰）
class UpdateMode(Enum):
    INCREMENTAL = 'incremental'  # 缓存滞后，增量更新
    FULL = 'full'                # 缓存不存在，全量计算
    SKIP = 'skip'                # 缓存已最新，无需计算

# 导入日志配置
from .logger_config import get_logger

# 导入 IC 计算核心函数
from .ic_calculator import (
    calculate_single_day_ic,
    calculate_ic_statistics
)

# 导入类型转换
from .convert_types import convert_to_native_types

# 导入日期标准化函数（复用公共逻辑，避免重复实现）
from .data_completeness import _normalize_dates

# 初始化 logger
logger = get_logger(__name__)


def get_cache_latest_date(cache_path: Path) -> Optional[str]:
    """
    获取缓存最新日期（复用 data_completeness 日期标准化逻辑）
    
    参数:
        cache_path: IC 结果缓存路径（直接传入 Path，而非因子名）
    
    返回:
        最新日期字符串（YYYY-MM-DD），若缓存不存在则返回 None
    
    设计说明:
        复用 _normalize_dates 函数，确保日期格式标准化（去重、排序）
        与 data_completeness.py 中同名函数职责不同（参数签名不同）
    """
    if not cache_path.exists():
        return None
    
    try:
        with open(cache_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        dates = data.get('dates', [])
        if not dates:
            return None
        
        # 使用公共函数标准化日期（确保 YYYY-MM-DD 格式，去重排序）
        dates = _normalize_dates(dates)
        
        return dates[-1] if dates else None
    
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
    logger.info(f"增量计算: 计算缺失日期 IC（{len(missing_dates)} 天）...")
    
    missing_set = set(missing_dates)
    factor_df_new = factor_df_full[factor_df_full['date'].isin(missing_set)]
    return_df_new = return_df_full[return_df_full['date'].isin(missing_set)]
    
    # 诊断信息：检查缺失日期是否在因子数据中存在
    # 注意：变量名应准确反映语义
    dates_in_factor_data = set(factor_df_full['date'].unique())  # 因子数据中的所有日期
    phantom_dates = missing_set - dates_in_factor_data  # 缺失日期中不在因子数据里的"幽灵日期"
    
    diagnostics = {
        'phantom_dates': sorted(phantom_dates)[:10],  # 幽灵日期示例
        'phantom_dates_count': len(phantom_dates),    # 幽灵日期数量
        'has_data': not factor_df_new.empty
    }
    
    if phantom_dates:
        logger.warning(f"{len(phantom_dates)} 个缺失日期不在因子数据中（幽灵日期）")
        examples = diagnostics['phantom_dates'][:5]
        logger.warning(f"示例日期: {examples}")
    
    if factor_df_new.empty:
        logger.debug("缺失日期无有效数据，跳过增量计算")
        return [], [], diagnostics
    
    logger.info(f"筛选后数据: {len(factor_df_new)} 行")
    
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
    
    logger.info(f"计算完成: {len(new_dates)} 天，{len([v for v in new_ic_values if v is not None])} 天有效 IC")
    if skipped_count > 0:
        logger.info(f"{skipped_count} 天因股票数不足跳过")
    
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
    logger.info("数据合并: 合并历史数据和新计算数据...")
    
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
        logger.warning(f"发现 {len(overlap_dates)} 个重叠日期，将使用新值覆盖")
        examples = merge_info['overlap_dates'][:5]
        logger.warning(f"示例: {examples}")
    
    # 使用字典去重（新值覆盖旧值）
    date_ic_map = {}
    
    # 先写入历史值（保留 None，维持日期与 IC 值的对应关系）
    for date, ic in zip(existing_dates, existing_ic_values):
        date_ic_map[date] = ic  # 保留 None
    
    # 再写入新值（覆盖旧值，保留 None）
    for date, ic in zip(new_dates, new_ic_values):
        date_ic_map[date] = ic  # 新值覆盖，保留 None
    
    # 按日期排序（包含全部日期）
    all_dates = sorted(date_ic_map.keys())
    all_ic_values = [date_ic_map[d] for d in all_dates]  # 包含 None
    
    # 统计有效 IC 数量（用于日志）
    valid_count = len([v for v in all_ic_values if v is not None])
    
    logger.info(f"合并后总计: {len(all_dates)} 天（{valid_count} 天有效 IC）")
    
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
    logger.info("统计重算: 重新计算统计指标...")
    
    # 过滤有效 IC 值
    valid_indices = [i for i, ic in enumerate(all_ic_values) if ic is not None]
    valid_indices_set = set(valid_indices)  # O(1) 成员检测，避免 O(n²)
    valid_dates = [all_dates[i] for i in valid_indices]
    valid_ic = [all_ic_values[i] for i in valid_indices]
    
    if not valid_ic:
        logger.warning("无有效 IC 值，返回空统计")
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
    
    logger.info(f"IC 均值: {result['ic_mean']:.4f}")
    logger.info(f"ICIR: {result['icir']:.2f}")
    logger.info(f"有效天数: {len(valid_ic)}")
    
    # 将 rolling_ic_mean 映射回 all_dates
    rolling_ic_mean_raw = result.get('rolling_ic_mean', [])
    rolling_ic_mean_aligned = []
    valid_idx = 0
    
    for i in range(len(all_dates)):
        if i in valid_indices_set:  # 使用 set 实现 O(1) 检测
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
    
    流程（6 步）:
        1. 读取现有缓存 [1/6]
        2. 确定缺失日期 [2/6]
        3. 计算缺失日期 IC [3/6]
        4. 合并数据 [4/6]
        5. 重算统计指标 [5/6]
        6. 构建输出并保存 [6/6]
    """
    logger.info("=" * 40)
    logger.info(f"增量更新: {factor_name}")
    logger.info("=" * 40)
    
    # 1. 读取现有缓存
    logger.info("[1/6] 读取现有缓存...")
    try:
        existing_data, existing_dates, existing_ic_values = read_existing_cache(output_path)
        logger.info(f"现有数据: {len(existing_dates)} 天")
    except json.JSONDecodeError as e:
        logger.error(f"缓存文件损坏: {e}")
        raise RuntimeError(f"缓存文件损坏，请删除后重算: {output_path}") from e
    
    if existing_data is None:
        logger.info("缓存不存在，需要全量计算")
        return {'update_mode': 'need_full', 'reason': 'cache_not_found'}
    
    # 2. 确定缺失日期
    logger.info("[2/6] 确定缺失日期...")
    cache_dates = set(existing_dates)
    all_factor_dates = set(factor_df_full['date'].unique())
    
    missing_dates = sorted(all_factor_dates - cache_dates)
    
    if not missing_dates:
        logger.info("无缺失日期，数据已完整")
        return existing_data  # 直接返回缓存
    
    logger.info(f"缺失日期: {len(missing_dates)} 天")
    logger.info(f"示例: {missing_dates[:5]}")
    
    # 3. 计算缺失日期 IC
    logger.info("[3/6] 计算缺失日期 IC...")
    new_dates, new_ic_values, diagnostics = calculate_missing_dates_ic(
        factor_df_full=factor_df_full,
        return_df_full=return_df_full,
        missing_dates=missing_dates,
        factor_col=factor_col,
        return_col=return_col,
        min_stocks=min_stocks
    )
    
    if not new_dates:
        logger.debug("无新数据可计算，返回现有缓存")
        return existing_data
    
    # 4. 合并数据
    logger.info("[4/6] 合并数据...")
    all_dates, all_ic_values, merge_info = merge_ic_data(
        existing_dates=existing_dates,
        existing_ic_values=existing_ic_values,
        new_dates=new_dates,
        new_ic_values=new_ic_values
    )
    
    # 5. 重算统计指标
    logger.info("[5/6] 重算统计指标...")
    stats = recalculate_statistics(all_dates, all_ic_values)
    
    # 6. 构建输出并保存
    # 使用 calculate_ic_statistics 返回的五维度判断结果
    valid_dates = [all_dates[i] for i in stats['valid_indices']]
    valid_ic = [all_ic_values[i] for i in stats['valid_indices'] if all_ic_values[i] is not None]
    ic_series = pd.Series(valid_ic, index=valid_dates)
    
    # 调用 calculate_ic_statistics 获取五维度判断（已在 recalculate_statistics 中调用）
    # stats 已包含 statistical_significance, factor_direction, economic_significance 等
    
    # 构建 ic_metrics（与 build_ic_result 结构一致）
    ic_metrics = {
        'ic_mean': stats['ic_mean'],
        'ic_std': stats['ic_std'],
        'icir': stats['icir'],
        'p_value': stats['p_value'],
        'p_value_display': stats.get('p_value_display', f"{stats['p_value']:.4f}")
    }
    
    # 构建 period
    period = {
        'start': all_dates[0] if all_dates else '',
        'end': all_dates[-1] if all_dates else '',
        'description': '增量更新合并后的日期范围'
    }
    
    # 构建 sample_stats
    sample_stats = {
        'total_days': raw_metadata.get('total_days', 0),
        'valid_days': stats['valid_days'],
        'avg_stocks_per_day': raw_metadata.get('avg_stocks_per_day', 0),
        'avg_stocks_period': {
            'start': all_dates[0] if all_dates else '',
            'end': all_dates[-1] if all_dates else '',
            'description': '过滤后每日平均股票数（dropna 后）'
        }
    }
    
    # 构建 summary（使用五维度判断结论）
    summary = {
        'ic_performance': stats.get('ic_performance', f"IC均值={stats['ic_mean']:.4f}, ICIR={stats['icir']:.2f}"),
        'statistical_significance': stats.get('statistical_significance', {}).get('conclusion', '未判断'),
        'factor_direction': stats.get('factor_direction', {}).get('conclusion', '未判断'),
        'economic_significance': stats.get('economic_significance', {}).get('conclusion', '未判断'),
        'recommendation': stats.get('recommendation', '请结合五维度判断综合评估')
    }
    
    # 组装完整结果（与 build_ic_result 结构一致）
    result = {
        'factor_name': factor_name,
        'calculation_date': datetime.now().isoformat(),
        'period': period,
        'ic_metrics': ic_metrics,
        'sample_stats': sample_stats,
        'statistical_significance': stats.get('statistical_significance', {}),
        'factor_direction': stats.get('factor_direction', {}),
        'economic_significance': stats.get('economic_significance', {}),
        'icir_stability': stats.get('icir_stability', {}),
        'ic_distribution_consistency': stats.get('ic_distribution_consistency', {}),
        'dates': all_dates,
        'ic_values': all_ic_values,
        'rolling_ic_mean': stats['rolling_ic_mean_aligned'],
        'positive_ratio': stats['positive_ratio'],
        'summary': summary,
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
    
    logger.info(f"✓ 增量更新完成！新增 {len(new_dates)} 天，总计 {len(all_dates)} 天")
    logger.info(f"✓ IC 均值: {stats['ic_mean']:.4f}")
    logger.info(f"✓ ICIR: {stats['icir']:.2f}")
    logger.info(f"✓ 结果已保存: {output_path}")
    
    return result


def should_use_incremental(
    output_path: Path,
    factor_df: pd.DataFrame,
    force_full: bool = False
) -> UpdateMode:
    """
    判断是否使用增量模式
    
    参数:
        output_path: 输出文件路径
        factor_df: 因子数据 DataFrame
        force_full: 是否强制全量
    
    返回:
        UpdateMode 枚举值：
        - INCREMENTAL: 缓存滞后，增量更新
        - FULL: 缓存不存在或损坏，全量计算
        - SKIP: 缓存已最新，无需计算
    
    判断逻辑:
        force_full = True → FULL
        缓存不存在 → FULL
        缓存存在 + 缓存日期 >= 因子日期 → SKIP
        缓存存在 + 缺失日期 > 0 → INCREMENTAL
    """
    if force_full:
        logger.info("模式判断: 强制全量计算")
        return UpdateMode.FULL
    
    if not output_path.exists():
        logger.info("模式判断: 缓存不存在，全量计算")
        return UpdateMode.FULL
    
    # 读取缓存最新日期
    cache_latest = get_cache_latest_date(output_path)
    if cache_latest is None:
        logger.info("模式判断: 缓存日期为空，全量计算")
        return UpdateMode.FULL
    
    # 因子数据最新日期（显式转换为日期字符串，确保格式一致）
    factor_latest = str(factor_df['date'].max())
    
    # 日期比较：显式转换为 YYYY-MM-DD 格式，避免格式不一致导致错误比较
    # 例如 '2026/05/22' 与 '2026-05-22' 字符串比较会出错
    cache_date_normalized = cache_latest.replace('/', '-')
    factor_date_normalized = factor_latest.replace('/', '-')
    
    if cache_date_normalized >= factor_date_normalized:
        logger.info(f"模式判断: 缓存已最新（{cache_latest} >= {factor_latest}），跳过更新")
        return UpdateMode.SKIP  # 缓存已最新，无需更新
    
    logger.info(f"模式判断: 缓存滞后（{cache_latest} < {factor_latest}），增量更新")
    return UpdateMode.INCREMENTAL