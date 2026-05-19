#!/usr/bin/env python3
"""
RSI_1D IC 计算器（缓存版） - 1日收益周期

从缓存数据计算 RSI(6) 因子的反向排名 Rank IC。
不再实时拉取数据，直接读取 cache/factor_data/ 下的缓存。

作者: 云舟
日期: 2026-05-07
"""

import sys
from pathlib import Path

# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent.parent))

import pandas as pd
import numpy as np
import gzip
import json
import re
from typing import Tuple, Optional
from datetime import datetime

# 导入通用 IC 计算模块（支持方向验证）
from factor_ic.common.ic_calculator import (
    calculate_ic_with_direction_verification,
    calculate_single_day_ic  # 用于增量计算
)

# ============================================================================
# 参数统一管理（遵循 PROJECT.md 参数传递规范）
# ============================================================================
# 默认最小股票数：用于 IC 计算（单日股票数不足时返回 None）
# 注意：修改此值会影响所有 IC 计算逻辑，需同步更新相关注释
DEFAULT_MIN_STOCKS = 10

# 导入数据完整性检查模块
from factor_ic.common.data_completeness import check_data_completeness, get_ic_output_path

# 导入类型转换模块
from factor_ic.common.convert_types import convert_to_native_types

# 缓存路径
CACHE_DIR = Path(__file__).parent.parent / 'cache' / 'factor_data'
FACTOR_CACHE = CACHE_DIR / 'factor_data.json.gz'
RETURN_CACHE = CACHE_DIR / 'return_data.json.gz'


def load_data_from_cache(
    factor_col: str = 'rsi_6',
    return_col: str = 'forward_return_1d'
) -> Tuple[pd.DataFrame, pd.DataFrame, dict]:
    """
    从缓存加载因子数据和收益数据
    
    参数:
        factor_col: 因子列名
        return_col: 收益列名
        
    返回:
        (factor_df, return_df, raw_metadata)
        - factor_df: 过滤后的因子数据 DataFrame
        - return_df: 过滤后的收益数据 DataFrame
        - raw_metadata: 原始数据元信息字典
            - period_start: 原始缓存最小日期
            - period_end: 原始缓存最大日期
            - total_days: 原始缓存日期数
    
    规范:
        period 和 total_days 基于 dropna 前的原始缓存数据
        （遵循 PROJECT.md 输出字段语义规范）
    """
    print("\n[数据加载] 从缓存读取数据...")
    
    # 加载因子数据
    if not FACTOR_CACHE.exists():
        raise FileNotFoundError(f"因子缓存不存在: {FACTOR_CACHE}")
    
    with gzip.open(FACTOR_CACHE, 'rt', encoding='utf-8') as f:
        factor_data = json.load(f)
    
    factor_df = pd.DataFrame(factor_data['data'])
    print(f"  - 因子数据: {len(factor_df)} 行, {factor_df['asset'].nunique()} 只股票")
    
    # 加载收益数据
    if not RETURN_CACHE.exists():
        raise FileNotFoundError(f"收益缓存不存在: {RETURN_CACHE}")
    
    with gzip.open(RETURN_CACHE, 'rt', encoding='utf-8') as f:
        return_data = json.load(f)
    
    return_df = pd.DataFrame(return_data['data'])
    print(f"  - 收益数据: {len(return_df)} 行, {return_df['asset'].nunique()} 只股票")
    
    # 日期类型统一转换（遵循 PROJECT.md 日期类型一致性规范）
    # 从 JSON 加载后，日期可能是多种格式（字符串、datetime、timestamp）
    # 统一转换为字符串格式 "YYYY-MM-DD"，确保 isin 操作类型匹配
    # 使用 errors='coerce' 处理异常格式，转换后检查 NaT 数量（遵循 PROJECT.md 日期转换异常处理规范）
    
    if 'date' in factor_df.columns:
        date_series = pd.to_datetime(factor_df['date'], errors='coerce')
        nat_count = date_series.isna().sum()
        if nat_count > 0:
            # 获取无效日期样本（前 5 个）
            invalid_samples = factor_df['date'][date_series.isna()].head(5).tolist()
            raise ValueError(
                f"因子数据中存在 {nat_count} 个无效日期格式\n"
                f"无效日期示例: {invalid_samples}\n"
                f"请检查缓存数据源是否包含脏数据"
            )
        factor_df['date'] = date_series.dt.strftime('%Y-%m-%d')
    
    if 'date' in return_df.columns:
        date_series = pd.to_datetime(return_df['date'], errors='coerce')
        nat_count = date_series.isna().sum()
        if nat_count > 0:
            invalid_samples = return_df['date'][date_series.isna()].head(5).tolist()
            raise ValueError(
                f"收益数据中存在 {nat_count} 个无效日期格式\n"
                f"无效日期示例: {invalid_samples}\n"
                f"请检查缓存数据源是否包含脏数据"
            )
        return_df['date'] = date_series.dt.strftime('%Y-%m-%d')
    
    # 输入验证（遵循 PROJECT.md 输入验证规范）
    # 提前检查列是否存在，提供友好的错误信息
    
    # 验证因子列
    if factor_col not in factor_df.columns:
        available_cols = sorted(factor_df.columns.tolist())
        raise KeyError(
            f"因子列 '{factor_col}' 不存在于缓存数据中\n"
            f"可用列: {available_cols}"
        )
    
    # 验证收益列
    if return_col not in return_df.columns:
        available_cols = sorted(return_df.columns.tolist())
        raise KeyError(
            f"收益列 '{return_col}' 不存在于缓存数据中\n"
            f"可用列: {available_cols}"
        )
    
    # 选择需要的列
    factor_df = factor_df[['date', 'asset', factor_col]].copy()
    
    # 重命名收益列（统一为 forward_return）
    return_df = return_df[['date', 'asset', return_col]].copy()
    return_df = return_df.rename(columns={return_col: 'forward_return'})
    
    # 在 dropna 之前，计算原始数据范围（遵循 PROJECT.md period/total_days 数据源规范）
    # period 和 total_days 应基于原始缓存数据，而非过滤后的数据
    # 原因：dropna 可能过滤掉某些日期的全部股票（如停牌、数据缺失）
    raw_period_start = str(factor_df['date'].min())
    raw_period_end = str(factor_df['date'].max())
    raw_total_days = factor_df['date'].nunique()
    
    print(f"  - 原始数据范围: {raw_period_start} ~ {raw_period_end}, {raw_total_days} 个交易日")
    
    # 过滤缺失值
    factor_df = factor_df.dropna(subset=[factor_col]).reset_index(drop=True)
    return_df = return_df.dropna(subset=['forward_return']).reset_index(drop=True)
    
    print(f"  - 过滤缺失值后: 因子 {len(factor_df)} 行, 收益 {len(return_df)} 行")
    
    # 返回过滤后的数据 + 原始数据元信息（遵循 PROJECT.md 输出字段语义规范）
    return factor_df, return_df, {
        'period_start': raw_period_start,
        'period_end': raw_period_end,
        'total_days': raw_total_days
    }


def calculate_daily_ic_series(
    factor_df: pd.DataFrame,
    return_df: pd.DataFrame,
    raw_metadata: dict = None,
    min_stocks: int = DEFAULT_MIN_STOCKS  # 遵循 PROJECT.md 参数传递规范
) -> dict:
    """
    计算每日的 IC 时间序列（带方向验证）
    
    参数:
        factor_df: 因子数据（已过滤缺失值）
        return_df: 收益数据（已过滤缺失值）
        raw_metadata: 原始数据元信息（遵循 PROJECT.md period/total_days 数据源规范）
            - period_start: 原始缓存最小日期
            - period_end: 原始缓存最大日期
            - total_days: 原始缓存日期数
        min_stocks: 最小股票数阈值（遵循 PROJECT.md 参数传递规范）
    
    返回:
        dict: IC 计算结果（符合 PROJECT.md 规范）
    """
    # 使用方向验证 IC 计算
    # 参数 min_stocks 通过函数签名传递，统一管理（遵循 PROJECT.md 参数传递规范）
    result = calculate_ic_with_direction_verification(
        factor_df=factor_df,
        return_df=return_df,
        factor_col='rsi_6',
        return_col='forward_return',
        date_col='date',
        asset_col='asset',
        min_stocks=min_stocks
    )
    
    # 防御性校验：确保 result 包含必需字段
    # 遵循 PROJECT.md 函数返回值契约规范
    required_fields = [
        'ic_series', 'ic_mean', 'ic_std', 'icir',
        'statistical_significance', 'factor_direction',
        'economic_significance', 'icir_stability',
        'ic_distribution_consistency', 'positive_ratio', 'summary'
    ]
    missing_fields = [f for f in required_fields if f not in result]
    if missing_fields:
        raise RuntimeError(
            f"calculate_ic_with_direction_verification 返回值缺少必需字段\n"
            f"缺失字段: {missing_fields}\n"
            f"问题定位: factor_ic/common/ic_calculator.py\n"
            f"期望字段: {required_fields}"
        )
    
    ic_series = result['ic_series']
    
    # 获取日期范围（遵循 PROJECT.md period 数据源规范）
    # 使用 raw_metadata 中的原始数据范围，而非过滤后的 factor_df
    if raw_metadata is None:
        raw_metadata = {}
    period_start = raw_metadata.get('period_start', str(factor_df['date'].min()))
    period_end = raw_metadata.get('period_end', str(factor_df['date'].max()))
    
    # 转换为 JSON 叏好格式
    dates = [str(d) for d in ic_series.index]
    ic_values = [round(v, 6) for v in ic_series.values]
    
    # 计算 20 日滚动均值（min_periods=10，至少需要10个有效值）
    rolling_mean = ic_series.rolling(window=20, min_periods=10).mean()
    
    # 遵循 PROJECT.md NaN 处理规范：在数据生成阶段将 NaN 转为 None
    # 原因：rolling 前 9 天不满 min_periods=10，返回 NaN
    #       round(NaN, 6) 返回 Python float nan，而非 None
    #       若延迟到 convert_to_native_types 处理，会导致：
    #       1. 中间数据语义不一致（nan vs None）
    #       2. 其他代码路径直接使用时可能出错
    rolling_ic_mean = [
        round(v, 6) if not pd.isna(v) else None
        for v in rolling_mean.values
    ]
    
    # 防御性校验：确保 dates、ic_values、rolling_ic_mean 长度一致
    # 遵循 PROJECT.md 输出字段长度一致性规范
    if len(dates) != len(ic_values):
        raise RuntimeError(
            f"dates 与 ic_values 长度不一致: "
            f"len(dates)={len(dates)} != len(ic_values)={len(ic_values)}"
        )
    if len(dates) != len(rolling_ic_mean):
        raise RuntimeError(
            f"dates 与 rolling_ic_mean 长度不一致: "
            f"len(dates)={len(dates)} != len(rolling_ic_mean)={len(rolling_ic_mean)}\n"
            f"理论上应相等（都来自 ic_series），若不一致可能是 pandas rolling 内部问题"
        )
    
    # 防御性校验：确保 dates 按升序排列
    # 遵循 PROJECT.md 规范：ic_series.index 必须按日期排序
    # 原因：rolling 计算按位置顺序，若 dates 乱序会导致 dates[i] 与 rolling_ic_mean[i] 对应错误
    if dates != sorted(dates):
        raise RuntimeError(
            f"dates 未按升序排列，可能导致 dates 与 rolling_ic_mean 对应错误\n"
            f"dates 前5个: {dates[:5]}\n"
            f"sorted 前5个: {sorted(dates)[:5]}"
        )
    
    # 符合 PROJECT.md 规范的数据结构（五维度判断）
    return {
        # 规范必需字段
        'factor_name': 'rsi_1d',
        'calculation_date': datetime.now().strftime('%Y-%m-%d'),
        'period': {
            # 语义定义（遵循 PROJECT.md 规范）：
            # - period 表示数据覆盖范围，与 sample_stats.total_days 对应
            # - period.start/end = 因子缓存的最小/最大日期
            # - 可能包含无有效 IC 的日期（股票数不足等原因）
            # - 与 dates[0]/dates[-1] 不同：dates 只含有效 IC 日期
            'start': period_start,
            'end': period_end
        },
        'ic_metrics': {
            'ic_mean': round(result['ic_mean'], 6),
            'ic_std': round(result['ic_std'], 6),
            'icir': round(result['icir'], 4)
        },
        'sample_stats': {
            # 语义定义（遵循 PROJECT.md 输出字段语义规范）：
            # - total_days: 原始因子缓存覆盖的日期数（dropna 前的数据范围）
            # - valid_days: 实际计算出 IC 的天数（每交易日股票数 >= min_stocks）
            # - 差值含义: total_days - valid_days = 因股票不足或数据缺失跳过的交易日数
            'total_days': raw_metadata.get('total_days', factor_df['date'].nunique()),  # 原始缓存日期数
            'valid_days': len(dates),                    # 有效 IC 天数
            'avg_stocks_per_day': int(factor_df.groupby('date').size().mean())
        },
        
        # 五维度判断（独立输出，遵循 PROJECT.md 规范）
        'statistical_significance': result['statistical_significance'],
        'factor_direction': result['factor_direction'],
        'economic_significance': result['economic_significance'],
        'icir_stability': result['icir_stability'],
        'ic_distribution_consistency': result['ic_distribution_consistency'],
        
        # IC 序列数据
        'dates': dates,
        'ic_values': ic_values,
        'rolling_ic_mean': rolling_ic_mean,
        
        # 其他统计（不与五维度判断重复）
        'positive_ratio': round(result['positive_ratio'], 4),
        'n_assets': factor_df['asset'].nunique(),
        'summary': result['summary']
    }


def _incremental_update(
    missing_dates: list,
    output_file: Path,
    min_stocks: int = DEFAULT_MIN_STOCKS  # 遵循 PROJECT.md 参数传递规范
) -> dict:
    """
    增量更新：只计算缺失日期的 IC，合并到现有缓存
    
    参数:
        missing_dates: 缺失日期列表
        output_file: 输出文件路径
        min_stocks: 最小股票数阈值（遵循 PROJECT.md 参数传递规范）
    
    返回:
        IC 数据字典
    """
    print("=" * 60)
    print("RSI_1D IC 计算器（增量模式）")
    print("=" * 60)
    
    # 读取现有缓存
    print("\n[1/4] 读取现有缓存...")
    try:
        with open(output_file, 'r', encoding='utf-8') as f:
            existing_data = json.load(f)
        existing_dates = existing_data.get('dates', [])
        existing_ic_values = existing_data.get('ic_values', [])
        print(f"  - 现有数据: {len(existing_dates)} 天")
    except Exception as e:
        print(f"  - 读取失败: {e}，切换到全量计算")
        # 直接调用全量计算函数（避免间接递归，遵循 PROJECT.md 规范）
        return _full_recalculate(output_file)
    
    # 加载全量缓存数据（用于筛选缺失日期 + 计算 sample_stats）
    print(f"\n[2/4] 加载缺失日期数据（{len(missing_dates)} 天）...")
    factor_df_full, return_df_full, raw_metadata = load_data_from_cache()
    
    # 筛选缺失日期的数据
    missing_set = set(missing_dates)
    factor_df_new = factor_df_full[factor_df_full['date'].isin(missing_set)]
    return_df_new = return_df_full[return_df_full['date'].isin(missing_set)]
    
    # 诊断：检查缺失日期的数据覆盖情况（遵循 PROJECT.md 增量更新诊断规范）
    dates_in_cache = set(factor_df_full['date'].unique())
    dates_not_in_cache = missing_set - dates_in_cache  # 缓存中完全没有的日期
    dates_in_cache_but_missing = missing_set & dates_in_cache  # 缓存中有但未被计算的日期
    
    if dates_not_in_cache:
        print(f"  [警告] {len(dates_not_in_cache)} 个缺失日期不在当前因子缓存范围")
        print(f"  [警告] 可能原因: 数据源未覆盖这些日期，或因子缓存已过期清理")
        examples = sorted(dates_not_in_cache)[:5]
        print(f"  [警告] 示例日期: {examples}{'...' if len(dates_not_in_cache) > 5 else ''}")
    
    if factor_df_new.empty:
        if dates_not_in_cache:
            print("  [诊断] 所有缺失日期均不在当前缓存范围，无法增量更新")
            print("  [建议] 检查数据源日期范围，或执行全量重算 (force_full=True)")
        else:
            # 缺失日期在缓存范围内，但筛选后无数据（可能是股票全被过滤）
            print(f"  [诊断] 缺失日期在缓存范围内，但筛选后无有效数据")
            print(f"  [诊断] 缓存范围: {factor_df_full['date'].min()} ~ {factor_df_full['date'].max()}")
            print(f"  [诊断] 缺失日期: {sorted(missing_dates)[:5]}")
        print("  - 跳过增量计算，返回现有缓存")
        return existing_data
    
    print(f"  - 筛选后: {len(factor_df_new)} 行")
    
    # 计算新日期的每日 IC
    print("\n[3/4] 计算新日期 IC...")
    new_dates = sorted(factor_df_new['date'].unique())
    new_ic_values = []
    
    for date in new_dates:
        day_factor = factor_df_new[factor_df_new['date'] == date]
        day_return = return_df_new[return_df_new['date'] == date]
        
        # 合并
        merged = day_factor.merge(day_return, on=['date', 'asset'], how='inner')
        
        # 使用核心函数计算单日 IC（遵循 PROJECT.md 规范）
        # 增量计算必须复用全量计算的核心函数，确保算法一致性
        # 参数 min_stocks 通过函数签名传递，统一管理（遵循 PROJECT.md 参数传递规范）
        ic_value = calculate_single_day_ic(
            merged, factor_col='rsi_6', return_col='forward_return', min_stocks=min_stocks
        )
        # ic_value 为 None 表示股票数不足，为 0.0 表示边界情况，为正/负数表示正常 IC
        new_ic_values.append(round(ic_value, 6) if ic_value is not None else None)
    
    # 过滤 None 值
    valid_new_ic = [ic for ic in new_ic_values if ic is not None]
    skipped_new_ic = len(new_dates) - len(valid_new_ic)
    
    # 遵循 PROJECT.md 增量计算进度显示规范：完整展示计算结果统计
    print(f"  - 计算完成: {len(new_dates)} 天，其中 {len(valid_new_ic)} 天有效 IC")
    if skipped_new_ic > 0:
        print(f"  - {skipped_new_ic} 天因股票数不足跳过（IC 值为 None）")
    
    # 合并数据（按日期排序，遵循 PROJECT.md 规范）
    print("\n[4/4] 合并数据并重新计算统计指标...")
    
    # 防御性检查：验证 existing_dates 与 new_dates 是否重叠
    existing_set = set(existing_dates)
    new_set = set(new_dates)
    overlap_dates = existing_set & new_set
    
    if overlap_dates:
        print(f"  [警告] 发现 {len(overlap_dates)} 个重叠日期，将使用新计算的 IC 值覆盖")
        overlap_sorted = sorted(overlap_dates)[:5]  # 只显示前5个
        print(f"  [警告] 重叠日期示例: {overlap_sorted}{'...' if len(overlap_dates) > 5 else ''}")
    
    # 使用字典去重：新值优先（后写入覆盖前写入）
    # 按 (existing + new) 顺序写入，确保新值覆盖旧值
    # 遵循 PROJECT.md 增量计算 None 处理规范：
    #   - 只写入有效 IC 值（过滤股票数不足的 None）
    #   - 兼容旧缓存（v1.32 之前版本可能包含 None）
    date_ic_map = {}
    for date, ic in zip(existing_dates, existing_ic_values):
        if ic is not None:  # 兼容旧缓存：过滤可能存在的 None（与 new 语义一致）
            date_ic_map[date] = ic
    for date, ic in zip(new_dates, new_ic_values):
        if ic is not None:  # 只写入有效 IC 值（与全量计算语义一致）
            date_ic_map[date] = ic  # 新值覆盖旧值
    
    # 按日期排序后解构
    all_dates = sorted(date_ic_map.keys())
    all_ic_values = [date_ic_map[d] for d in all_dates]
    
    print(f"  - 合并后总计: {len(all_dates)} 天（去重后）")
    
    # 过滤有效值（保留位置信息用于对齐）
    valid_indices = [i for i, ic in enumerate(all_ic_values) if ic is not None]
    valid_dates = [all_dates[i] for i in valid_indices]
    valid_ic = [all_ic_values[i] for i in valid_indices]
    
    # 创建带日期索引的 Series（用于滚动计算）
    # 注意：valid_dates 必须按日期升序排列，确保 rolling 计算顺序正确
    # （calculate_ic_statistics 输入约束：索引顺序决定输出顺序）
    ic_series = pd.Series(valid_ic, index=valid_dates)
    
    # 重新计算统计指标
    from factor_ic.common.ic_calculator import calculate_ic_statistics
    result = calculate_ic_statistics(ic_series)
    
    # 将 rolling_ic_mean 映射回 all_dates（None 日期填 None）
    rolling_ic_mean_raw = result.get('rolling_ic_mean', [])
    
    # 防御性验证：确保 rolling_ic_mean_raw 与 valid_ic 长度一致
    # 避免因 calculate_ic_statistics 内部过滤导致索引错位
    if len(rolling_ic_mean_raw) != len(valid_ic):
        raise RuntimeError(
            f"rolling_ic_mean 长度不匹配: "
            f"len(rolling_ic_mean_raw)={len(rolling_ic_mean_raw)} "
            f"!= len(valid_ic)={len(valid_ic)}\n"
            f"可能原因：\n"
            f"  1. calculate_ic_statistics 内部对 ic_series 做了过滤（不应发生，请检查函数实现）\n"
            f"  2. ic_series 输入包含 NaN（调用方应在创建 Series 前过滤）\n"
            f"  3. 旧缓存兼容性问题（v1.32 之前版本 ic_values 可能包含 None）\n"
            f"诊断建议：检查 ic_series 是否包含 NaN，检查 calculate_ic_statistics 输入约束"
        )
    
    # 使用 set 优化查找性能（O(n) → O(1)）
    valid_indices_set = set(valid_indices)
    rolling_ic_mean_aligned = []
    valid_idx = 0
    for i in range(len(all_dates)):
        if i in valid_indices_set:
            rolling_ic_mean_aligned.append(rolling_ic_mean_raw[valid_idx])
            valid_idx += 1
        else:
            rolling_ic_mean_aligned.append(None)
    
    # 防御性断言：确保日期格式为 YYYY-MM-DD（遵循 PROJECT.md 日期字符串比较规范）
    # 字典序比较依赖格式约定：年位 > 月位 > 日位
    # 若格式不一致，min/max 会产生错误结果且不报错
    dates_to_compare = [all_dates[0], all_dates[-1], raw_metadata['period_start'], raw_metadata['period_end']]
    for d in dates_to_compare:
        if not re.match(r'^\d{4}-\d{2}-\d{2}$', str(d)):
            raise ValueError(
                f"日期格式不符合 YYYY-MM-DD 约定: {d}\n"
                f"位置: period 比较操作（增量模式）\n"
                f"请检查数据加载函数是否正确执行了日期转换"
            )
    
    # 构建合并后的数据结构
    merged_data = {
        'factor_name': 'rsi_1d',
        'calculation_date': datetime.now().strftime('%Y-%m-%d'),
        'period': {
            # 语义定义（遵循 PROJECT.md 输出字段语义规范）：
            # - period 表示最终输出数据的覆盖范围（合并后）
            # - 增量模式：覆盖 all_dates 范围（包含历史缓存 + 新计算数据）
            # - period.start = min(all_dates[0], raw_metadata['period_start'])
            # - period.end = max(all_dates[-1], raw_metadata['period_end'])
            # - 可能包含无有效 IC 的日期（股票数不足、数据缺失等原因）
            # - 与 dates[0]/dates[-1] 不同：dates 只含有效 IC 日期
            'start': min(all_dates[0], raw_metadata['period_start']),
            'end': max(all_dates[-1], raw_metadata['period_end'])
        },
        'ic_metrics': {
            'ic_mean': round(result['ic_mean'], 6),
            'ic_std': round(result['ic_std'], 6),
            'icir': round(result['icir'], 4)
        },
        'sample_stats': {
            # 语义定义（遵循 PROJECT.md 输出字段语义规范）：
            # - total_days: 因子缓存覆盖的日期数（包含无效日期）
            # - 增量模式：max(raw_metadata['total_days'], factor_df_full['date'].nunique())
            #   - raw_metadata['total_days']：历史缓存的原始日期数（可能包含已不在当前缓存中的日期）
            #   - factor_df_full['date'].nunique()：当前因子缓存的日期数
            #   - 取最大值确保：total_days >= valid_days，语义自洽
            # - valid_days: 实际计算出 IC 的天数（每交易日股票数 >= min_stocks）
            # - avg_stocks_per_day: 当前因子缓存范围内的平均每日股票数
            #   - 增量模式语义限制：不含历史缓存中已不在当前数据源的日期
            #   - 口径范围见 avg_stocks_period 字段（遵循 PROJECT.md 输出字段口径规范）
            # - avg_stocks_period: avg_stocks_per_day 的口径范围（遵循 PROJECT.md 输出字段口径规范）
            #   - 用户可明确知道 avg_stocks_per_day 反映哪个时间段的股票数
            #   - 即使 period 覆盖历史缓存，avg_stocks_period 也标注了当前数据源的口径
            # - 差值含义: total_days - valid_days = 因股票不足或数据缺失跳过的交易日数
            'total_days': max(
                raw_metadata.get('total_days', 0),
                factor_df_full['date'].nunique()
            ),
            'valid_days': len(valid_ic),   # 有效 IC 天数
            'avg_stocks_per_day': int(factor_df_full.groupby('date').size().mean()),
            'avg_stocks_period': {
                'start': str(factor_df_full['date'].min()),
                'end': str(factor_df_full['date'].max()),
                'description': f"avg_stocks_per_day 反映 {factor_df_full['date'].min()} ~ {factor_df_full['date'].max()} 范围内的平均每日股票数"
            }
        },
        
        # 五维度判断（独立输出，遵循 PROJECT.md 规范）
        'statistical_significance': result['statistical_significance'],
        'factor_direction': result['factor_direction'],
        'economic_significance': result['economic_significance'],
        'icir_stability': result['icir_stability'],
        'ic_distribution_consistency': result['ic_distribution_consistency'],
        
        # IC 序列（长度一致，遵循 PROJECT.md 规范）
        'dates': all_dates,
        'ic_values': all_ic_values,
        'rolling_ic_mean': rolling_ic_mean_aligned,  # 与 dates/ic_values 对齐
        
        # 其他统计（不与五维度判断重复）
        'positive_ratio': round(result['positive_ratio'], 4),
        'n_assets': factor_df_full['asset'].nunique(),
        'summary': result['summary'],
        
        # 增量更新标记（遵循 PROJECT.md 增量更新事件记录规范）
        'update_mode': 'incremental',
        'incremental_days': len(new_dates),
        'incremental_events': {
            # 重叠覆盖事件：重要事件必须记录到返回数据和 JSON 文件
            # 便于上游调用方感知，且下次可复现问题
            'overwritten_dates': sorted(overlap_dates) if overlap_dates else [],
            'overwritten_count': len(overlap_dates),
            'description': f"发现 {len(overlap_dates)} 个重叠日期，使用新计算的 IC 值覆盖" if overlap_dates else "无重叠日期"
        }
    }
    
    # 保存
    print(f"\n保存数据到: {output_file}")
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(convert_to_native_types(merged_data), f, ensure_ascii=False, indent=2)
    
    print("\n" + "=" * 60)
    print(f"增量更新完成！新增 {len(new_dates)} 天，总计 {len(all_dates)} 天")
    print("=" * 60)
    
    return merged_data


def _full_recalculate(
    output_file: Path,
    min_stocks: int = DEFAULT_MIN_STOCKS  # 遵循 PROJECT.md 参数传递规范
) -> dict:
    """
    全量重新计算 RSI IC 数据
    
    参数:
        output_file: 输出文件路径
        min_stocks: 最小股票数阈值（遵循 PROJECT.md 参数传递规范）
        
    返回:
        IC 数据字典
    """
    print("=" * 60)
    print("RSI_1D IC 计算器（缓存版） - 1日收益周期")
    print("=" * 60)
    
    # 从缓存加载数据
    print("\n[1/3] 从缓存加载因子和收益数据...")
    try:
        factor_df, return_df, raw_metadata = load_data_from_cache()
        
        # 检查数据量（遵循 PROJECT.md 参数传递规范）
        # 使用函数签名传递的 min_stocks 参数，统一管理阈值
        if factor_df['asset'].nunique() < min_stocks:
            raise ValueError(
                f"股票数量不足以计算有效的 IC\n"
                f"当前: {factor_df['asset'].nunique()} < {min_stocks}"
            )
            
    except FileNotFoundError as e:
        # 缓存文件不存在：提示用户检查缓存路径或重新生成
        raise RuntimeError(
            f"缓存文件不存在，请检查缓存路径或执行全量计算\n"
            f"原始错误: {e}"
        ) from e
    except json.JSONDecodeError as e:
        # 缓存 JSON 格式错误：提示用户检查缓存文件格式或重新生成
        raise RuntimeError(
            f"缓存文件 JSON 格式错误，请检查缓存文件或重新生成\n"
            f"原始错误: {e}"
        ) from e
    except KeyError as e:
        # 缓存字段缺失：提示用户检查缓存版本或重新生成
        raise RuntimeError(
            f"缓存字段缺失，可能是缓存版本过期，请重新生成\n"
            f"缺失字段: {e}"
        ) from e
    except ValueError as e:
        # 数据量不足：直接传递，保留原始异常类型（遵循 PROJECT.md 异常处理类型保留规范）
        # 数据验证错误应保留原始类型，让调用方区分处理
        raise
    except Exception as e:
        # 未预期的异常：保留原始错误信息和堆栈，方便排查
        raise RuntimeError(
            f"数据加载时发生未预期的异常\n"
            f"异常类型: {type(e).__name__}\n"
            f"原始错误: {e}"
        ) from e
    
    # 使用缓存全部日期（不截断）
    
    print(f"\n数据统计:")
    print(f"  - 原始日期范围: {raw_metadata['period_start']} ~ {raw_metadata['period_end']}")
    print(f"  - 原始交易日数: {raw_metadata['total_days']}")
    print(f"  - 过滤后交易日数: {factor_df['date'].nunique()}")
    print(f"  - 股票数量: {factor_df['asset'].nunique()}")
    
    # 计算 IC
    print("\n[2/3] 计算每日 IC...")
    # 参数 min_stocks 通过函数签名传递，统一管理（遵循 PROJECT.md 参数传递规范）
    ic_data = calculate_daily_ic_series(factor_df, return_df, raw_metadata, min_stocks=min_stocks)
    print(f"  - IC 均值: {ic_data['ic_metrics']['ic_mean']:.4f}")
    print(f"  - ICIR: {ic_data['ic_metrics']['icir']:.2f}")
    print(f"  - 正比例: {ic_data['positive_ratio']:.1%}")
    t_stat = ic_data['statistical_significance']['t_stat']
    is_sig = ic_data['statistical_significance']['is_significant']
    print(f"  - t 统计量: {t_stat:.2f} {'显著' if is_sig else '不显著'}")
    
    # 保存数据
    print(f"\n[3/3] 保存数据到: {output_file}")
    output_file.parent.mkdir(parents=True, exist_ok=True)
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(convert_to_native_types(ic_data), f, ensure_ascii=False, indent=2)
    
    print("\n" + "=" * 60)
    print(f"完成！共计算 {ic_data['sample_stats']['valid_days']} 天有效 IC 数据（原始数据 {ic_data['sample_stats']['total_days']} 天）")
    print("=" * 60)
    
    return ic_data


def generate_rsi_ic_data(
    output_file: Path | str | None = None,
    force_full: bool = False,
    min_stocks: int = DEFAULT_MIN_STOCKS  # 遵循 PROJECT.md 参数传递规范
) -> dict:
    """
    从缓存数据计算 RSI IC
    
    参数:
        output_file: 输出文件路径（Path 或 str，内部统一转为 Path）
        force_full: 强制全量计算
        min_stocks: 最小股票数阈值（遵循 PROJECT.md 参数传递规范）
    
    返回:
        IC 数据字典
    
    规范:
        计算日期范围为缓存数据的全部日期，不截断
    """
    # 统一转换为 Path 对象（遵循 PROJECT.md 参数类型约定）
    if output_file is None:
        output_file = get_ic_output_path('rsi_1d')
    else:
        output_file = Path(output_file)
    
    # 强制全量计算：直接调用全量计算函数
    # 参数 min_stocks 通过函数签名传递，统一管理（遵循 PROJECT.md 参数传递规范）
    if force_full:
        return _full_recalculate(output_file, min_stocks=min_stocks)
    
    # 增量判断
    mode, missing_dates, info = check_data_completeness('rsi_1d')
    
    # 显式控制流架构：每个分支都有明确的 return，不存在隐式 fallthrough
    if mode == 'skip':
        # 数据完备，无需计算
        print("\n数据完备，无需更新")
        try:
            with open(output_file, 'r', encoding='utf-8') as f:
                cached_data = json.load(f)
                # 添加更新模式标记（遵循 PROJECT.md 返回值标记规范）
                cached_data['update_mode'] = 'skip'
                return cached_data  # 成功：返回缓存数据（带 skip 标记）
        except Exception as e:
            # 失败：显式调用全量计算（遵循 PROJECT.md 增量模式异常处理规范）
            print(f"读取缓存失败: {e}，将执行全量计算")
            full_data = _full_recalculate(output_file, min_stocks=min_stocks)
            # 添加 fallback 事件标记（遵循 PROJECT.md 返回值标记规范）
            # 调用方可通过 fallback_event 字段感知实际执行了全量计算
            full_data['update_mode'] = 'full'  # 实际执行的模式
            full_data['fallback_event'] = {
                'original_mode': 'skip',              # 原本期望的模式
                'actual_mode': 'full',                # 实际执行的模式
                'trigger_reason': 'cache_read_failed', # 触发原因
                'error_message': str(e),              # 原始错误信息
                'description': f"缓存读取失败，触发全量计算。原始错误: {e}"
            }
            return full_data
    
    elif mode == 'incremental':
        # 缺失数据，执行增量更新
        print("\n[增量模式] 缺失 {} 天数据，执行增量更新".format(len(missing_dates)))
        return _incremental_update(missing_dates, output_file, min_stocks=min_stocks)
    
    elif mode == 'full':
        # 需要全量计算
        return _full_recalculate(output_file, min_stocks=min_stocks)
    
    else:
        # 未知模式：防御性处理（遵循 PROJECT.md 错误信息格式规范）
        # 错误信息必须包含合法值列表，帮助用户理解正确用法
        raise RuntimeError(
            f"未知的计算模式: {mode}\n"
            f"合法值: ['skip', 'incremental', 'full']\n"
            f"请检查 check_data_completeness() 返回值是否正确"
        )


if __name__ == '__main__':
    # 计算缓存全部日期的 IC 数据
    generate_rsi_ic_data()