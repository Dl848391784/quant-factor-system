#!/usr/bin/env python3
"""
通用数据加载模块 - factor_ic 公共模块

功能：
1. 加载缓存数据（gzip + JSON）
2. 日期类型统一转换（YYYY-MM-DD）
3. 列存在验证（显示可用列）
4. dropna 前记录 raw_metadata
5. dropna 过滤缺失值
6. 日期对齐验证（可选）

作者: 云瑶
日期: 2026-05-22
"""

import gzip
import json
import pandas as pd
from pathlib import Path
from typing import Tuple, List, Optional, Dict


# 默认缓存路径
DEFAULT_CACHE_DIR = Path(__file__).parent.parent.parent / 'cache' / 'factor_data'
DEFAULT_FACTOR_CACHE = DEFAULT_CACHE_DIR / 'factor_data.json.gz'
DEFAULT_RETURN_CACHE = DEFAULT_CACHE_DIR / 'return_data.json.gz'


def load_factor_return_data(
    factor_cols: List[str],
    return_col: str = 'forward_return_1d',
    factor_cache_path: Optional[Path] = None,
    return_cache_path: Optional[Path] = None,
    dropna_cols: Optional[List[str]] = None,
    validate_date_alignment: bool = True,
    additional_factor_files: Optional[Dict[str, Path]] = None
) -> Tuple[pd.DataFrame, pd.DataFrame, Dict]:
    """
    从缓存加载因子数据和收益数据
    
    参数:
        factor_cols: 需加载的因子列（如 ['rsi_6'] 或 ['close', 'high', 'low']）
            - 必须包含 'date' 和 'asset' 列（自动添加）
        return_col: 收益列名，默认 'forward_return_1d'
        factor_cache_path: 因子缓存路径（默认使用 DEFAULT_FACTOR_CACHE）
        return_cache_path: 收益缓存路径（默认使用 DEFAULT_RETURN_CACHE）
        dropna_cols: dropna 过滤列（默认 = factor_cols，不含 date/asset）
        validate_date_alignment: 是否验证日期对齐（默认 True）
        additional_factor_files: 额外因子文件（如换手率数据）
            - 格式: {'turnover_rate': Path(...)}
            - 会合并到主因子数据
    
    返回:
        (factor_df, return_df, raw_metadata)
        - factor_df: 过滤后的因子数据 DataFrame
        - return_df: 过滤后的收益数据 DataFrame
        - raw_metadata: 原始数据元信息字典
            - period_start: 原始缓存最小日期
            - period_end: 原始缓存最大日期
            - total_days: 原始缓存日期数
            - avg_stocks_per_day: 原始平均每日股票数
    
    规范:
        period 和 total_days 基于 dropna 前的原始缓存数据
        （遵循 PROJECT.md 输出字段语义规范）
    
    示例:
        # RSI 因子（直接用缓存列）
        factor_df, return_df, raw_metadata = load_factor_return_data(
            factor_cols=['rsi_6']
        )
        
        # KDJ 因子（需要 close, high, low）
        factor_df, return_df, raw_metadata = load_factor_return_data(
            factor_cols=['close', 'high', 'low']
        )
        
        # 换手率突增（需要额外文件）
        factor_df, return_df, raw_metadata = load_factor_return_data(
            factor_cols=['close'],
            additional_factor_files={
                'turnover_rate': DEFAULT_CACHE_DIR / 'turnover_rate_data.json.gz'
            }
        )
    """
    print("\n[数据加载] 从缓存读取数据...")
    
    # 确定缓存路径
    factor_cache_path = factor_cache_path or DEFAULT_FACTOR_CACHE
    return_cache_path = return_cache_path or DEFAULT_RETURN_CACHE
    
    # ========== 加载因子数据 ==========
    if not factor_cache_path.exists():
        raise FileNotFoundError(f"因子缓存不存在: {factor_cache_path}")
    
    with gzip.open(factor_cache_path, 'rt', encoding='utf-8') as f:
        factor_data = json.load(f)
    
    factor_df = pd.DataFrame(factor_data['data'])
    print(f"  - 因子数据: {len(factor_df)} 行, {factor_df['asset'].nunique()} 只股票")
    
    # ========== 加载收益数据 ==========
    if not return_cache_path.exists():
        raise FileNotFoundError(f"收益缓存不存在: {return_cache_path}")
    
    with gzip.open(return_cache_path, 'rt', encoding='utf-8') as f:
        return_data = json.load(f)
    
    return_df = pd.DataFrame(return_data['data'])
    print(f"  - 收益数据: {len(return_df)} 行, {return_df['asset'].nunique()} 只股票")
    
    # ========== 日期类型统一转换 ==========
    # 从 JSON 加载后，日期可能是多种格式（字符串、datetime、timestamp）
    # 统一转换为字符串格式 "YYYY-MM-DD"，确保 isin 操作类型匹配
    factor_df = _convert_date_column(factor_df, '因子')
    return_df = _convert_date_column(return_df, '收益')
    
    # ========== 在所有 merge 前，快照原始数据范围 ==========
    # raw_metadata 应基于原始缓存数据，而非 inner join 后的数据
    raw_period_start = str(factor_df['date'].min())
    raw_period_end = str(factor_df['date'].max())
    raw_total_days = factor_df['date'].nunique()
    raw_avg_stocks_per_day = round(factor_df.groupby('date').size().mean(), 1)
    
    print(f"  - 原始数据范围: {raw_period_start} ~ {raw_period_end}, {raw_total_days} 个交易日")
    print(f"  - 原始平均每日股票数: {raw_avg_stocks_per_day}")
    
    # ========== 加载额外因子文件（如有） ==========
    # 在修改因子列列表之前，创建 factor_cols 的副本（防止引用污染）
    # 使用 list() 创建新列表对象，确保后续操作不影响调用方传入的原始列表
    default_dropna_cols = list(factor_cols)
    
    all_factor_cols = list(factor_cols)  # 真正的副本，不污染调用方
    
    if additional_factor_files:
        for col_name, file_path in additional_factor_files.items():
            if not file_path.exists():
                raise FileNotFoundError(f"额外因子缓存不存在: {file_path}")
            
            with gzip.open(file_path, 'rt', encoding='utf-8') as f:
                additional_data = json.load(f)
            
            additional_df = pd.DataFrame(additional_data['data'])
            additional_df = _convert_date_column(additional_df, f'额外因子({col_name})')
            
            # 类型转换
            if col_name in additional_df.columns:
                additional_df[col_name] = pd.to_numeric(additional_df[col_name], errors='coerce')
            else:
                # 列不存在时提供友好错误信息
                available_cols = sorted([c for c in additional_df.columns if c not in ['date', 'asset']])
                raise KeyError(
                    f"额外因子文件 '{file_path}' 缺少指定列: '{col_name}'\n"
                    f"可用列: {available_cols}"
                )
            
            # 合并到主因子数据
            rows_before = len(factor_df)
            factor_df = pd.merge(
                factor_df,
                additional_df[['date', 'asset', col_name]],
                on=['date', 'asset'],
                how='inner'
            )
            rows_after = len(factor_df)
            rows_lost = rows_before - rows_after
            
            # 打印合并结果，告知用户数据丢失情况
            if rows_lost > 0:
                print(f"  - 合并 {col_name} 后: {rows_after} 行（丢失 {rows_lost} 行，{rows_lost/rows_before*100:.1f}%）")
            else:
                print(f"  - 合并 {col_name} 后: {rows_after} 行（无数据丢失）")
        
        # 更新因子列列表（包含额外列）
        # 使用独立变量，保持顺序：先 factor_cols，再追加不在 factor_cols 的额外列
        all_factor_cols = factor_cols + [k for k in additional_factor_files.keys() if k not in factor_cols]
    
    # ========== 列存在验证 ==========
    # 必须包含 date 和 asset
    required_base_cols = ['date', 'asset']
    for col in required_base_cols:
        if col not in factor_df.columns:
            raise KeyError(f"因子数据缺少必需列: '{col}'")
    
    # 验证因子列
    missing_factor_cols = [col for col in all_factor_cols if col not in factor_df.columns]
    if missing_factor_cols:
        available_cols = sorted([c for c in factor_df.columns if c not in ['date', 'asset']])
        raise KeyError(
            f"因子数据缺少必需列: {missing_factor_cols}\n"
            f"可用因子列: {available_cols}"
        )
    
    # 验证收益列
    if return_col not in return_df.columns:
        available_cols = sorted([c for c in return_df.columns if c not in ['date', 'asset']])
        raise KeyError(
            f"收益列 '{return_col}' 不存在于缓存数据中\n"
            f"可用收益列: {available_cols}"
        )
    
    # ========== 选择需要的列 ==========
    # 去重并保持顺序：防止用户传入 factor_cols=['date', 'rsi_6'] 导致重复列
    select_cols = list(dict.fromkeys(['date', 'asset'] + all_factor_cols))
    factor_df = factor_df[select_cols].copy()
    
    # 重命名收益列（统一为 forward_return）
    return_df = return_df[['date', 'asset', return_col]].copy()
    return_df = return_df.rename(columns={return_col: 'forward_return'})
    
    # ========== 过滤缺失值 ==========
    # dropna_cols 默认为原始 factor_cols（不含额外列）
    # 若用户需要过滤额外列，需显式传入 dropna_cols 参数
    if dropna_cols is None:
        dropna_cols = default_dropna_cols
    
    factor_df = factor_df.dropna(subset=dropna_cols).reset_index(drop=True)
    return_df = return_df.dropna(subset=['forward_return']).reset_index(drop=True)
    
    print(f"  - 过滤缺失值后: 因子 {len(factor_df)} 行（过滤列: {dropna_cols}），收益 {len(return_df)} 行")
    
    # ========== 日期对齐验证（可选） ==========
    if validate_date_alignment:
        factor_dates = set(factor_df['date'].unique())
        return_dates = set(return_df['date'].unique())
        
        if factor_dates != return_dates:
            missing_in_return = factor_dates - return_dates
            missing_in_factor = return_dates - factor_dates
            
            print(f"  [警告] 因子数据和收益数据日期不对齐")
            print(f"    因子数据日期数: {len(factor_dates)}")
            print(f"    收益数据日期数: {len(return_dates)}")
            print(f"    因子数据缺失日期数: {len(missing_in_factor)}")
            print(f"    收益数据缺失日期数: {len(missing_in_return)}")
            
            # 选择交集日期（保证数据对齐）
            common_dates = factor_dates & return_dates
            factor_df = factor_df[factor_df['date'].isin(common_dates)].reset_index(drop=True)
            return_df = return_df[return_df['date'].isin(common_dates)].reset_index(drop=True)
            print(f"    对齐后日期数: {len(common_dates)}")
    
    # ========== 返回结果 ==========
    return factor_df, return_df, {
        'period_start': raw_period_start,
        'period_end': raw_period_end,
        'total_days': raw_total_days,
        'avg_stocks_per_day': raw_avg_stocks_per_day
    }


def _convert_date_column(df: pd.DataFrame, name: str) -> pd.DataFrame:
    """
    日期类型统一转换（YYYY-MM-DD）
    
    参数:
        df: DataFrame
        name: 数据名称（用于错误消息）
    
    返回:
        转换后的 DataFrame
    
    异常:
        ValueError: 日期格式无效
    """
    if 'date' not in df.columns:
        return df
    
    # 使用 .copy() 创建副本，确保不修改原始 DataFrame（遵循最小惊讶原则）
    df = df.copy()
    
    date_series = pd.to_datetime(df['date'], errors='coerce')
    nat_count = date_series.isna().sum()
    
    if nat_count > 0:
        invalid_samples = df['date'][date_series.isna()].head(5).tolist()
        raise ValueError(
            f"{name}数据中存在 {nat_count} 个无效日期格式\n"
            f"无效日期示例: {invalid_samples}\n"
            f"请检查缓存数据源是否包含脏数据"
        )
    
    df['date'] = date_series.dt.strftime('%Y-%m-%d')
    return df


def get_cache_dir() -> Path:
    """获取缓存目录路径"""
    return DEFAULT_CACHE_DIR


def get_factor_cache_path() -> Path:
    """获取因子缓存文件路径"""
    return DEFAULT_FACTOR_CACHE


def get_return_cache_path() -> Path:
    """获取收益缓存文件路径"""
    return DEFAULT_RETURN_CACHE