#!/usr/bin/env python3
"""
换手率突增因子 IC 计算器（缓存版） - 1日收益周期

从缓存数据计算换手率突增因子的正向排名 Rank IC。
不再实时拉取数据，直接读取 cache/factor_data/ 下的缓存。

因子定义：
- 换手率突增 = 当日换手率 / 过去5日换手率均值

筛选条件：
- 换手率突增 > 1（当日换手率高于近期均值）
- 当日涨跌幅 > 0（上涨）
- 不满足条件的股票因子值设为 None

作者: 云舟
日期: 2026-05-08
更新: 2026-05-10（优化符合 PROJECT.md 规范）
"""

import sys
from pathlib import Path

# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent.parent))

import pandas as pd
import numpy as np
import gzip
import json
from typing import Tuple, Optional, Dict
from datetime import datetime
import warnings
warnings.filterwarnings('ignore')

# 导入通用 IC 计算模块（支持方向验证）
from factor_ic.common.ic_calculator import (
    calculate_ic_with_direction_verification,
    calculate_single_day_ic,  # 用于增量计算
    calculate_ic_statistics   # 用于增量统计重算
)

# 导入数据完整性检查模块
from factor_ic.common.data_completeness import check_data_completeness, get_ic_output_path

# 导入类型转换模块
from factor_ic.common.convert_types import convert_to_native_types

# ============================================================================
# 参数统一管理（遵循 PROJECT.md 参数传递规范）
# ============================================================================
# 默认最小股票数：用于 IC 计算（单日股票数不足时返回 None）
# 注意：修改此值会影响所有 IC 计算逻辑，需同步更新相关注释
DEFAULT_MIN_STOCKS = 10

# 缓存路径
CACHE_DIR = Path(__file__).parent.parent / 'cache' / 'factor_data'


def load_data_from_cache() -> Tuple[pd.DataFrame, pd.DataFrame, dict]:
    """
    从缓存加载换手率突增因子所需数据
    
    需要:
    - turnover_rate_data.json.gz: 换手率数据
    - factor_data.json.gz: 收盘价数据
    - return_data.json.gz: 收益数据
    
    返回:
        (factor_df, return_df, raw_metadata)
        - factor_df: 过滤后的因子数据 DataFrame（含 turnover_rate, close）
        - return_df: 过滤后的收益数据 DataFrame
        - raw_metadata: 原始数据元信息字典
            - period_start: 原始缓存最小日期
            - period_end: 原始缓存最大日期
            - total_days: 原始缓存日期数
    
    规范:
        加载缓存全部日期数据，不截断
        period 和 total_days 基于 dropna 前的原始缓存数据
        （遵循 PROJECT.md 输出字段语义规范）
    """
    print("\n[数据加载] 从缓存读取数据...")
    
    turnover_path = CACHE_DIR / 'turnover_rate_data.json.gz'
    factor_path = CACHE_DIR / 'factor_data.json.gz'
    return_path = CACHE_DIR / 'return_data.json.gz'
    
    # 检查文件存在性
    for path, name in [(turnover_path, '换手率'), (factor_path, '因子'), (return_path, '收益')]:
        if not path.exists():
            # 底层抛出语义清晰的异常（遵循 MODULE.md 异常处理链规范）
            # 异常消息包含名称和路径，无需上层再次包装
            raise FileNotFoundError(f"{name}缓存不存在: {path}")
    
    # 加载换手率数据
    print("  - 加载换手率数据...")
    with gzip.open(turnover_path, 'rt', encoding='utf-8') as f:
        turnover_data = json.load(f)
    
    turnover_df = pd.DataFrame(turnover_data['data'])
    turnover_df['turnover_rate'] = pd.to_numeric(turnover_df['turnover_rate'], errors='coerce')
    turnover_df = turnover_df.dropna(subset=['turnover_rate'])
    print(f"    换手率数据: {len(turnover_df)} 行")
    
    # 加载收盘价数据
    print("  - 加载收盘价数据...")
    with gzip.open(factor_path, 'rt', encoding='utf-8') as f:
        factor_data = json.load(f)
    
    close_df = pd.DataFrame(factor_data['data'])
    close_df = close_df[['date', 'asset', 'close']].copy()
    close_df['close'] = pd.to_numeric(close_df['close'], errors='coerce')
    print(f"    收盘价数据: {len(close_df)} 行")
    
    # 加载收益数据
    print("  - 加载收益数据...")
    with gzip.open(return_path, 'rt', encoding='utf-8') as f:
        return_data = json.load(f)
    
    return_df = pd.DataFrame(return_data['data'])
    # 统一收益列名
    if 'forward_return_1d' in return_df.columns:
        return_df['forward_return'] = return_df['forward_return_1d']
    return_df = return_df[['date', 'asset', 'forward_return']].copy()
    return_df['forward_return'] = pd.to_numeric(return_df['forward_return'], errors='coerce')
    print(f"    收益数据: {len(return_df)} 行")
    
    # 合并换手率和收盘价
    print("  - 合并换手率和收盘价...")
    factor_df = pd.merge(
        turnover_df[['date', 'asset', 'turnover_rate']],
        close_df,
        on=['date', 'asset'],
        how='inner'
    )
    print(f"    合并后: {len(factor_df)} 行, {factor_df['asset'].nunique()} 只股票")
    
    # 验证日期对齐（遵循 MODULE.md 数据对齐验证规范）
    # 因子数据和收益数据的日期范围必须一致，否则 IC 计算会静默丢失不匹配的日期
    factor_dates = factor_df['date'].unique()
    return_dates = return_df['date'].unique()
    
    if set(factor_dates) != set(return_dates):
        missing_in_return = set(factor_dates) - set(return_dates)
        missing_in_factor = set(return_dates) - set(factor_dates)
        
        print(f"  警告：因子数据和收益数据日期不对齐")
        print(f"    因子数据日期数: {len(factor_dates)}")
        print(f"    收益数据日期数: {len(return_dates)}")
        print(f"    因子数据缺失日期数: {len(missing_in_factor)}")
        print(f"    收益数据缺失日期数: {len(missing_in_return)}")
        
        # 选择交集日期（保证数据对齐）
        common_dates = set(factor_dates) & set(return_dates)
        factor_df = factor_df[factor_df['date'].isin(common_dates)]
        return_df = return_df[return_df['date'].isin(common_dates)]
        print(f"    对齐后日期数: {len(common_dates)}")
    
    # 在进一步处理之前，计算原始数据范围（遵循 PROJECT.md 输出字段语义规范）
    raw_period_start = str(factor_df['date'].min())
    raw_period_end = str(factor_df['date'].max())
    raw_total_days = factor_df['date'].nunique()
    
    print(f"  - 原始数据范围: {raw_period_start} ~ {raw_period_end}, {raw_total_days} 个交易日")
    
    # 使用缓存全部日期（不截断）
    
    return factor_df, return_df, {
        'period_start': raw_period_start,
        'period_end': raw_period_end,
        'total_days': raw_total_days
    }


def calculate_turnover_surge_factor(factor_df: pd.DataFrame) -> Tuple[pd.DataFrame, Dict]:
    """
    计算换手率突增因子（带筛选条件）
    
    筛选条件:
    - 换手率突增：turnover_surge > 1
    - 上涨：当日涨跌幅 > 0
    - 不满足条件的股票因子值设为 None
    
    参数:
        factor_df: 包含 date, asset, close, turnover_rate 的 DataFrame
        
    返回:
        (处理后的 factor_df, 筛选统计)
    """
    print("\n[因子计算] 计算换手率突增因子...")
    
    # filter_stats 统计口径说明（遵循 MODULE.md filter_stats 统计口径规范）
    # total_records: 过滤前总记录数（原始数据总量）
    # 注意：后续不区分 rolling NaN 和条件过滤，因为本因子设计为：
    #   - rolling NaN（min_periods=5）+ 条件不满足 → 统一设为 None
    #   - 统计口径简化：只统计 total_records 和 valid_count（语义清晰：有效计数）
    filter_stats = {
        'total_records': len(factor_df),        # 过滤前总记录数
        'turnover_surge_count': 0,              # turnover_surge > 1 的记录数（不含 rolling NaN）
        'price_up_count': 0,                    # pct_change > 0 的记录数
        'both_conditions_count': 0,             # 两个条件同时满足的记录数
        'valid_count': 0,                       # 最终有效因子记录数（语义清晰：valid）
        'retention_ratio': 0.0                  # 保留比例 = valid_count / total_records（语义清晰：retention）
    }
    
    if factor_df.empty:
        print("  数据为空")
        return factor_df, filter_stats
    
    # Step 0: 创建副本（遵循 MODULE.md DataFrame 参数副本规范）
    # 避免修改调用方传入的 DataFrame，隔离副作用
    factor_df = factor_df.copy()
    
    # Step 1: 计算换手率突增因子（当日换手率 / 过去5日均值）
    print("  计算换手率突增因子（窗口=5日）...")
    factor_df['date_str'] = factor_df['date'].astype(str)
    factor_df = factor_df.sort_values(['asset', 'date_str'])
    
    # 滚动窗口参数业务决策说明（遵循 MODULE.md 滚动窗口参数规范）
    # window=5, min_periods=5 的设计决策：
    # 1. 业务含义：当日换手率 / 过去5日换手率均值，衡量相对突增程度
    # 2. min_periods=5 确保只有足够历史数据（≥5日）的股票才能计算因子
    # 3. 数据丢失影响：每只股票前4个交易日 turnover_ma 为 NaN → turnover_surge 为 NaN
    # 4. 对少量历史数据股票的影响：若股票历史 < 5日，全部记录的 turnover_surge 为 NaN
    # 5. 设计意图：保证因子质量，避免因历史数据不足导致的均值不稳定
    # 
    # 影响范围示例：
    # - 上市5天的股票：前4天 NaN，第5天有效
    # - 上市仅3天的股票：全部3条记录的 turnover_surge 均为 NaN
    factor_df['turnover_ma'] = factor_df.groupby('asset')['turnover_rate'].transform(
        lambda x: x.rolling(window=5, min_periods=5).mean()
    )
    factor_df['turnover_surge'] = factor_df['turnover_rate'] / factor_df['turnover_ma']
    
    # Step 2: 计算当日涨跌幅（遵循 MODULE.md 变量命名语义清晰原则规范）
    # price_pct_change 明确指示数据来源：收盘价涨跌幅（非换手率变化）
    print("  计算当日涨跌幅...")
    factor_df['price_pct_change'] = factor_df.groupby('asset')['close'].transform(
        lambda x: x.pct_change()
    )
    
    factor_df = factor_df.drop(columns=['date_str'])
    
    # Step 3: 应用筛选条件
    print("  应用筛选条件（turnover_surge > 1 且 price_pct_change > 0）...")
    
    turnover_surge_cond = factor_df['turnover_surge'] > 1
    price_up = factor_df['price_pct_change'] > 0
    
    filter_stats['turnover_surge_count'] = int(turnover_surge_cond.sum())
    filter_stats['price_up_count'] = int(price_up.sum())
    
    both_conditions = turnover_surge_cond & price_up
    filter_stats['both_conditions_count'] = int(both_conditions.sum())
    
    # 不满足条件的股票因子值设为 None
    factor_df.loc[~both_conditions, 'turnover_surge'] = None
    
    valid_count = factor_df['turnover_surge'].notna().sum()
    filter_stats['valid_count'] = int(valid_count)
    filter_stats['retention_ratio'] = valid_count / len(factor_df) if len(factor_df) > 0 else 0
    
    print(f"    总记录数:           {filter_stats['total_records']:,}")
    print(f"    换手率突增记录数:   {filter_stats['turnover_surge_count']:,}")
    print(f"    上涨记录数:         {filter_stats['price_up_count']:,}")
    print(f"    换手率突增+上涨:     {filter_stats['both_conditions_count']:,} ({filter_stats['retention_ratio']*100:.1f}%)")
    print(f"    有效因子记录数:     {valid_count:,}")
    
    # Step 4: 极端值处理（裁剪到 1.0-10，遵循 MODULE.md 极端值裁剪规范）
    # 裁剪下界 1.0 等于筛选条件下界（turnover_surge > 1），裁剪范围与筛选条件一致
    # 筛选条件已经过滤掉了 <= 1 的值，裁剪下界 0.5 永远不会生效
    if factor_df['turnover_surge'].notna().any():
        mask = factor_df['turnover_surge'].notna()
        factor_df.loc[mask, 'turnover_surge'] = factor_df.loc[mask, 'turnover_surge'].clip(1.0, 10)
        
        valid_values = factor_df.loc[mask, 'turnover_surge']
        print(f"    因子范围（裁剪后）: [{valid_values.min():.2f}, {valid_values.max():.2f}]")
        print(f"    因子均值: {valid_values.mean():.2f}")
    
    return factor_df, filter_stats


def calculate_turnover_surge_ic(
    factor_df: pd.DataFrame,
    return_df: pd.DataFrame,
    raw_metadata: dict = None,
    min_stocks: int = DEFAULT_MIN_STOCKS  # 遵循 PROJECT.md 参数传递规范
) -> Dict:
    """
    计算换手率突增因子的正向 Rank IC（使用公共模块）
    
    参数:
        factor_df: 包含 date, asset, turnover_surge 的 DataFrame
            - **参数预期（遵循 MODULE.md 隐式行为显式化原则）**：
            - turnover_surge 列可以包含 None/NaN 值（不满足筛选条件的股票）
            - 函数内部会执行 dropna(subset=['turnover_surge']) 过滤无效记录
            - 外部调用方无需预先过滤，但需理解 avg_stocks_per_day 基于 dropna 后数据
        return_df: 包含 date, asset, forward_return 的 DataFrame
        raw_metadata: 原始数据元信息（遵循 PROJECT.md period/total_days 数据源规范）
            - period_start: 原始缓存最小日期
            - period_end: 原始缓存最大日期
            - total_days: 原始缓存日期数
        min_stocks: 最小股票数阈值（遵循 PROJECT.md 参数传递规范）
        
    返回:
        IC 计算结果字典（符合 PROJECT.md 规范，含五维度判断）
    """
    print("\n[IC计算] 计算换手率突增因子 Rank IC（正向因子）...")
    
    # 准备数据（遵循 MODULE.md 隐式行为显式化原则）
    # dropna 过滤：turnover_surge=None/NaN 的记录（不满足筛选条件的股票）
    # 这是函数参数预期的隐式行为，外部调用方无需预先过滤
    # 口径影响：avg_stocks_per_day 基于 dropna 后数据（只统计有效因子记录）
    factor_data = factor_df[['date', 'asset', 'turnover_surge']].dropna(subset=['turnover_surge']).copy()
    return_data = return_df[['date', 'asset', 'forward_return']].copy()
    
    # 统一 date 列类型
    factor_data['date'] = factor_data['date'].astype(str)
    return_data['date'] = return_data['date'].astype(str)
    
    if factor_data.empty:
        return {
            # PROJECT.md 规范必需字段
            'factor_name': 'turnover_surge_1d',
            'calculation_date': datetime.now().strftime('%Y-%m-%d'),
            'period': {'start': '', 'end': ''},
            'ic_metrics': {
                'ic_mean': 0,
                'ic_std': 0,
                'icir': 0,
                'p_value': 1.0,
                'p_value_display': '1.0'
            },
            'sample_stats': {
                'total_days': raw_metadata.get('total_days', 0) if raw_metadata else 0,
                'valid_days': 0,
                'avg_stocks_per_day': 0,
                'avg_stocks_period': {
                    'start': '',
                    'end': '',
                    'description': '平均每日有效股票数统计范围'
                }
            },
            
            # 五维度判断（空数据默认值）
            'statistical_significance': {
                'is_significant': False,
                'p_value_threshold': 0.05,
                't_stat_threshold': 1.96,
                'description': '数据不足，无法判断统计显著性'
            },
            'factor_direction': {
                'ic_mean_sign': 'unknown',
                'ic_mean_sign_reason': '数据不足，无法确定因子方向',
                'ic_mean_abs': 0.0,
                'direction_threshold': 0.03,
                'description': '数据不足，无法确定因子方向'
            },
            'economic_significance': {
                'icir': 0.0,
                'icir_threshold': 0.5,
                'is_economically_significant': False,
                'description': '数据不足，无法判断经济显著性'
            },
            
            # 顶层输出字段（遵循 MODULE.md 输出结构统一性规范）
            'dates': [],
            'ic_values': [],
            'rolling_ic_mean': [],
            
            # 额外字段
            'positive_ratio': 0.0,
            'n_assets': 0,
            'summary': '数据不足，无法计算IC',
            'factor_stats': None,
            'update_mode': 'full'
        }
    
    # 使用公共模块计算 IC（含五维度判断）
    # 参数 min_stocks 通过函数签名传递，统一管理（遵循 PROJECT.md 参数传递规范）
    try:
        result = calculate_ic_with_direction_verification(
            factor_df=factor_data,
            return_df=return_data,
            factor_col='turnover_surge',
            return_col='forward_return',
            min_stocks=min_stocks
        )
    except ValueError as e:
        # 公共模块抛出 ValueError（如数据不足）
        return {
            # PROJECT.md 规范必需字段
            'factor_name': 'turnover_surge_1d',
            'calculation_date': datetime.now().strftime('%Y-%m-%d'),
            'period': {
                'start': raw_metadata.get('period_start', '') if raw_metadata else '',
                'end': raw_metadata.get('period_end', '') if raw_metadata else ''
            },
            'ic_metrics': {
                'ic_mean': 0,
                'ic_std': 0,
                'icir': 0,
                'p_value': 1.0,
                'p_value_display': '1.0'
            },
            'sample_stats': {
                'total_days': raw_metadata.get('total_days', 0) if raw_metadata else 0,
                'valid_days': 0,
                'avg_stocks_per_day': int(factor_data['asset'].nunique()),
                'avg_stocks_period': {
                    'start': raw_metadata.get('period_start', '') if raw_metadata else '',
                    'end': raw_metadata.get('period_end', '') if raw_metadata else '',
                    'description': '平均每日有效股票数统计范围'
                }
            },
            
            # 五维度判断（空数据默认值）
            'statistical_significance': {
                'is_significant': False,
                'p_value_threshold': 0.05,
                't_stat_threshold': 1.96,
                'description': f'无法判断统计显著性: {str(e)}'
            },
            'factor_direction': {
                'ic_mean_sign': 'unknown',
                'ic_mean_sign_reason': f'无法确定因子方向: {str(e)}',
                'ic_mean_abs': 0.0,
                'direction_threshold': 0.03,
                'description': f'无法确定因子方向: {str(e)}'
            },
            'economic_significance': {
                'icir': 0.0,
                'icir_threshold': 0.5,
                'is_economically_significant': False,
                'description': f'无法判断经济显著性: {str(e)}'
            },
            
            # 顶层输出字段（遵循 MODULE.md 输出结构统一性规范）
            'dates': [],
            'ic_values': [],
            'rolling_ic_mean': [],
            
            # 额外字段
            'positive_ratio': 0.0,
            'n_assets': int(factor_data['asset'].nunique()),
            'summary': f'无法计算IC: {str(e)}',
            'factor_stats': None,
            'update_mode': 'full'
        }
    
    # 获取日期范围
    period_start = raw_metadata.get('period_start', '') if raw_metadata else ''
    period_end = raw_metadata.get('period_end', '') if raw_metadata else ''
    
    # 提取 ic_series（内部变量，用于生成顶层输出字段 dates/ic_values/rolling_ic_mean）
    ic_series = result['ic_series']
    
    # 转换为 JSON 友好格式（遵循 PROJECT.md NaN 处理规范）
    dates = [str(d) for d in ic_series.index]
    ic_values = [round(v, 6) for v in ic_series.values]
    
    # 计算 20 日滚动均值（min_periods=10，至少需要10个有效值）
    # 遵循 PROJECT.md NaN 处理规范：在数据生成阶段将 NaN 转为 None
    rolling_mean = ic_series.rolling(window=20, min_periods=10).mean()
    rolling_ic_mean = [
        round(v, 6) if pd.notna(v) else None
        for v in rolling_mean.values
    ]
    
    print(f"  IC 均值: {result['ic_mean']:.4f}")
    print(f"  ICIR: {result['icir']:.2f}")
    print(f"  方向: {result['factor_direction']['ic_mean_sign']}")
    print(f"  统计显著: {result['statistical_significance']['is_significant']}")
    print(f"  正 IC 比例: {result['positive_ratio']:.1%}")
    
    return {
        # PROJECT.md 规范必需字段
        'factor_name': 'turnover_surge_1d',
        'calculation_date': datetime.now().strftime('%Y-%m-%d'),
        'period': {
            'start': period_start,
            'end': period_end
        },
        'ic_metrics': {
            'ic_mean': round(result['ic_mean'], 6),
            'ic_std': round(result['ic_std'], 6),
            'icir': round(result['icir'], 4),
            'p_value': round(result['p_value'], 6),
            'p_value_display': result['p_value_display']
        },
        'sample_stats': {
            # 统计口径说明（遵循 MODULE.md 第1870行规范）
            # avg_stocks_per_day 基于 dropna 后数据（只统计有效因子的每日股票数）
            # total_days 基于 dropna 前数据（原始缓存日期数）
            # 口径差异：factor_data 是 dropna(subset=['turnover_surge']) 后的数据
            'total_days': raw_metadata.get('total_days', 0) if raw_metadata else 0,
            'valid_days': result['n_days'],
            'avg_stocks_per_day': int(factor_data.groupby('date').size().mean()),
            'avg_stocks_period': {
                'start': period_start,
                'end': period_end,
                'description': '平均每日有效股票数统计范围'
            }
        },
        
        # 五维度判断（遵循 PROJECT.md IC 计算规范）
        'statistical_significance': result['statistical_significance'],
        'factor_direction': result['factor_direction'],
        'economic_significance': result['economic_significance'],
        'icir_stability': result['icir_stability'],
        'ic_distribution_consistency': result['ic_distribution_consistency'],
        
        # 顶层输出字段（遵循 MODULE.md 输出结构统一性规范）
        'dates': dates,
        'ic_values': ic_values,
        'rolling_ic_mean': rolling_ic_mean,
        
        # 额外字段（保留原有功能）
        'positive_ratio': round(result['positive_ratio'], 4),
        't_stat': result['t_stat'],
        'n_assets': factor_data['asset'].nunique(),
        'summary': result['summary']
    }


def _full_recalculate(
    output_file: Path,
    min_stocks: int = DEFAULT_MIN_STOCKS  # 遵循 PROJECT.md 参数传递规范
) -> dict:
    """
    全量计算换手率突增因子 IC
    
    参数:
        output_file: 输出文件路径
        min_stocks: 最小股票数阈值（遵循 PROJECT.md 参数传递规范）
        
    返回:
        IC 数据字典（遵循 PROJECT.md 输出结构规范）
    """
    FACTOR_NAME = 'turnover_surge_1d'
    
    # 全量计算
    print("=" * 60)
    print("换手率突增因子 IC 计算器（缓存版） - 1日收益周期")
    print("=" * 60)
    
    # 加载数据
    print("\n[1/3] 从缓存加载换手率和收益数据...")
    try:
        factor_df, return_df, raw_metadata = load_data_from_cache()
        
        if factor_df['asset'].nunique() < min_stocks:
            raise ValueError(
                f"股票数量不足以计算有效的 IC\n"
                f"当前: {factor_df['asset'].nunique()} < {min_stocks}"
            )
    except FileNotFoundError:
        # 中间层：裸 raise（遵循 MODULE.md 异常处理链规范）
        # 底层已抛出语义清晰的异常（包含名称和路径），无需再次包装
        # 让 FileNotFoundError 自然传播，保留原始类型和消息
        raise
    except ValueError as e:
        # 数据验证错误：裸 raise 保留原始类型（遵循 MODULE.md 异常链保留规范）
        # 原因：ValueError 表示股票数不足，是可预期错误，原始类型更易诊断
        raise  # 不包装
    except Exception as e:
        # 未预期异常：包装为 RuntimeError，保留异常链
        # 原因：未预期异常类型多变，包装为 RuntimeError 统一处理
        raise RuntimeError(f"数据加载失败: {e}") from e
    
    print(f"\n数据统计:")
    print(f"  - 原始日期范围: {raw_metadata['period_start']} ~ {raw_metadata['period_end']}")
    print(f"  - 原始交易日数: {raw_metadata['total_days']}")
    print(f"  - 过滤后交易日数: {factor_df['date'].nunique()}")
    print(f"  - 股票数量: {factor_df['asset'].nunique()}")
    
    # 计算因子
    print("\n[2/3] 计算换手率突增因子...")
    factor_df, filter_stats = calculate_turnover_surge_factor(factor_df)
    
    # 计算 IC
    print("\n[3/3] 计算 IC...")
    ic_data = calculate_turnover_surge_ic(factor_df, return_df, raw_metadata=raw_metadata, min_stocks=min_stocks)
    
    print(f"\nIC 统计:")
    print(f"  - IC 均值: {ic_data['ic_metrics']['ic_mean']:.4f}")
    print(f"  - ICIR: {ic_data['ic_metrics']['icir']:.2f}")
    print(f"  - 方向: {ic_data['factor_direction']['ic_mean_sign']}")
    print(f"  - 统计显著: {ic_data['statistical_significance']['is_significant']}")
    print(f"  - 正比例: {ic_data['positive_ratio']:.1%}")
    
    # 构建完整结果（遵循 PROJECT.md 输出结构规范）
    result_json = {
        'factor_name': FACTOR_NAME,
        'calculation_date': ic_data['calculation_date'],
        'period': ic_data['period'],
        'ic_metrics': ic_data['ic_metrics'],
        'sample_stats': ic_data['sample_stats'],
        
        # 五维度判断（遵循 PROJECT.md IC 计算规范）
        'statistical_significance': ic_data['statistical_significance'],
        'factor_direction': ic_data['factor_direction'],
        'economic_significance': ic_data['economic_significance'],
        'icir_stability': ic_data['icir_stability'],
        'ic_distribution_consistency': ic_data['ic_distribution_consistency'],
        
        # 顶层输出字段（遵循 MODULE.md 输出结构统一性规范）
        'dates': ic_data['dates'],
        'ic_values': ic_data['ic_values'],
        'rolling_ic_mean': ic_data['rolling_ic_mean'],
        
        # 额外字段（保留原有功能）
        'filter_stats': filter_stats,
        'positive_ratio': ic_data['positive_ratio'],
        't_stat': ic_data['t_stat'],
        'n_assets': ic_data['n_assets'],
        'summary': ic_data['summary'],
        
        # 更新模式标记（遵循 PROJECT.md 返回值标记规范）
        'update_mode': 'full'
    }
    
    # 转换类型
    result_json = convert_to_native_types(result_json)
    
    # 保存
    output_file.parent.mkdir(parents=True, exist_ok=True)
    
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(result_json, f, ensure_ascii=False, indent=2)
    
    print(f"\n保存数据到: {output_file}")
    print("=" * 60)
    print(f"完成！共计算 {ic_data['sample_stats']['valid_days']} 天有效 IC 数据（原始数据 {ic_data['sample_stats']['total_days']} 天）")
    print("=" * 60)
    
    return result_json


def generate_turnover_surge_ic_data(
    output_file: Path | str | None = None,
    force_full: bool = False,
    min_stocks: int = DEFAULT_MIN_STOCKS  # 遵循 PROJECT.md 参数传递规范
) -> dict:
    """
    从缓存数据计算换手率突增因子 IC
    
    参数:
        output_file: 输出文件路径（Path 或 str，内部统一转为 Path）
        force_full: 强制全量计算
        min_stocks: 最小股票数阈值（遵循 PROJECT.md 参数传递规范）
        
    返回:
        IC 数据字典
    
    规范:
        计算日期范围为缓存数据的全部日期，不截断
    """
    FACTOR_NAME = 'turnover_surge_1d'
    
    # 统一转换为 Path 对象（遵循 PROJECT.md 参数类型约定）
    if output_file is None:
        output_file = get_ic_output_path(FACTOR_NAME)
    else:
        output_file = Path(output_file)
    
    # 强制全量计算：直接调用全量计算函数
    # 参数 min_stocks 通过函数签名传递，统一管理（遵循 PROJECT.md 参数传递规范）
    if force_full:
        return _full_recalculate(output_file, min_stocks=min_stocks)
    
    # 增量判断
    mode, missing_dates, info = check_data_completeness(FACTOR_NAME)
    
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
            full_data['update_mode'] = 'full'  # 实际执行的模式
            full_data['fallback_event'] = {
                'original_mode': 'skip',
                'actual_mode': 'full',
                'trigger_reason': 'cache_read_failed',
                'error_message': str(e),
                'description': f"缓存读取失败，触发全量计算。原始错误: {e}"
            }
            return full_data
    
    elif mode == 'incremental':
        # 增量模式 fallback：换手率突增因子依赖5日窗口计算
        # 设计决策：为简化实现，暂用全量计算替代增量计算
        # 技术原因：增量计算需要额外历史数据（前5日换手率），实现复杂度高
        # 未来改进：实现真正的增量计算（仅计算缺失日期 + 窗口数据）
        print(f"\n[增量模式] 缺失 {len(missing_dates)} 天数据")
        print("  注意：换手率突增因子需要5日窗口计算，增量模式暂用全量计算替代")
        full_data = _full_recalculate(output_file, min_stocks=min_stocks)
        # 添加增量替代事件标记
        full_data['update_mode'] = 'full'
        full_data['incremental_fallback'] = {
            'original_mode': 'incremental',
            'actual_mode': 'full',
            'trigger_reason': 'factor_window_dependency',
            'missing_dates_count': len(missing_dates),
            'description': "换手率突增因子需要5日窗口计算，增量模式暂用全量计算替代"
        }
        return full_data
    
    elif mode == 'full':
        # 需要全量计算
        return _full_recalculate(output_file, min_stocks=min_stocks)
    
    else:
        # 未知模式：防御性处理（遵循 PROJECT.md 错误信息格式规范）
        raise RuntimeError(
            f"未知的计算模式: {mode}\n"
            f"合法值: ['skip', 'incremental', 'full']\n"
            f"请检查 check_data_completeness() 返回值是否正确"
        )


if __name__ == '__main__':
    # 计算缓存全部日期的 IC 数据
    generate_turnover_surge_ic_data()