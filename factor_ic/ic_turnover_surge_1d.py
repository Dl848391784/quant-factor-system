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
import gc
from typing import Tuple, Optional, Dict
from datetime import datetime
from scipy import stats
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
            raise FileNotFoundError(f"{name}缓存不存在: {path}")
    
    # 加载换手率数据
    print("  - 加载换手率数据...")
    with gzip.open(turnover_path, 'rt', encoding='utf-8') as f:
        turnover_data = json.load(f)
    
    turnover_df = pd.DataFrame(turnover_data['data'])
    turnover_df['turnover_rate'] = pd.to_numeric(turnover_df['turnover_rate'], errors='coerce')
    turnover_df = turnover_df.dropna(subset=['turnover_rate'])
    del turnover_data
    gc.collect()
    print(f"    换手率数据: {len(turnover_df)} 行")
    
    # 加载收盘价数据
    print("  - 加载收盘价数据...")
    with gzip.open(factor_path, 'rt', encoding='utf-8') as f:
        factor_data = json.load(f)
    
    close_df = pd.DataFrame(factor_data['data'])
    close_df = close_df[['date', 'asset', 'close']].copy()
    close_df['close'] = pd.to_numeric(close_df['close'], errors='coerce')
    del factor_data
    gc.collect()
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
    del return_data
    gc.collect()
    print(f"    收益数据: {len(return_df)} 行")
    
    # 合并换手率和收盘价
    print("  - 合并换手率和收盘价...")
    factor_df = pd.merge(
        turnover_df[['date', 'asset', 'turnover_rate']],
        close_df,
        on=['date', 'asset'],
        how='inner'
    )
    del turnover_df, close_df
    gc.collect()
    print(f"    合并后: {len(factor_df)} 行, {factor_df['asset'].nunique()} 只股票")
    
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
    
    filter_stats = {
        'total_records': len(factor_df),
        'turnover_surge_count': 0,
        'price_up_count': 0,
        'both_conditions_count': 0,
        'filtered_count': 0,
        'filter_ratio': 0.0
    }
    
    if factor_df.empty:
        print("  数据为空")
        return factor_df, filter_stats
    
    # Step 1: 计算换手率突增因子（当日换手率 / 过去5日均值）
    print("  计算换手率突增因子（窗口=5日）...")
    factor_df['date_str'] = factor_df['date'].astype(str)
    factor_df = factor_df.sort_values(['asset', 'date_str']).copy()
    
    factor_df['turnover_ma'] = factor_df.groupby('asset')['turnover_rate'].transform(
        lambda x: x.rolling(window=5, min_periods=5).mean()
    )
    factor_df['turnover_surge'] = factor_df['turnover_rate'] / factor_df['turnover_ma']
    
    # Step 2: 计算当日涨跌幅
    print("  计算当日涨跌幅...")
    factor_df['pct_change'] = factor_df.groupby('asset')['close'].transform(
        lambda x: x.pct_change()
    )
    
    factor_df = factor_df.drop(columns=['date_str'])
    
    # Step 3: 应用筛选条件
    print("  应用筛选条件（turnover_surge > 1 且 pct_change > 0）...")
    
    turnover_surge_cond = factor_df['turnover_surge'] > 1
    price_up = factor_df['pct_change'] > 0
    
    filter_stats['turnover_surge_count'] = int(turnover_surge_cond.sum())
    filter_stats['price_up_count'] = int(price_up.sum())
    
    both_conditions = turnover_surge_cond & price_up
    filter_stats['both_conditions_count'] = int(both_conditions.sum())
    
    # 不满足条件的股票因子值设为 None
    factor_df.loc[~both_conditions, 'turnover_surge'] = None
    
    valid_count = factor_df['turnover_surge'].notna().sum()
    filter_stats['filtered_count'] = int(valid_count)
    filter_stats['filter_ratio'] = valid_count / len(factor_df) if len(factor_df) > 0 else 0
    
    print(f"    总记录数:           {filter_stats['total_records']:,}")
    print(f"    换手率突增记录数:   {filter_stats['turnover_surge_count']:,}")
    print(f"    上涨记录数:         {filter_stats['price_up_count']:,}")
    print(f"    换手率突增+上涨:     {filter_stats['both_conditions_count']:,} ({filter_stats['filter_ratio']*100:.1f}%)")
    print(f"    有效因子记录数:     {valid_count:,}")
    
    # Step 4: 极端值处理（裁剪到 0.5-10）
    if factor_df['turnover_surge'].notna().any():
        mask = factor_df['turnover_surge'].notna()
        factor_df.loc[mask, 'turnover_surge'] = factor_df.loc[mask, 'turnover_surge'].clip(0.5, 10)
        
        valid_values = factor_df.loc[mask, 'turnover_surge']
        print(f"    因子范围（裁剪后）: [{valid_values.min():.2f}, {valid_values.max():.2f}]")
        print(f"    因子均值: {valid_values.mean():.2f}")
    
    gc.collect()
    
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
    
    # 准备数据
    factor_data = factor_df[['date', 'asset', 'turnover_surge']].dropna(subset=['turnover_surge']).copy()
    return_data = return_df[['date', 'asset', 'forward_return']].copy()
    
    # 统一 date 列类型
    factor_data['date'] = factor_data['date'].astype(str)
    return_data['date'] = return_data['date'].astype(str)
    
    if factor_data.empty:
        return {
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
                'avg_stocks_per_day': 0
            },
            'ic_series': None,
            'summary': '数据不足，无法计算IC'
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
                'avg_stocks_per_day': int(factor_data['asset'].nunique())
            },
            'ic_series': None,
            'summary': f'无法计算IC: {str(e)}'
        }
    
    # 获取日期范围
    period_start = raw_metadata.get('period_start', '') if raw_metadata else ''
    period_end = raw_metadata.get('period_end', '') if raw_metadata else ''
    
    # 提取 ic_series 用于 ic_series 输出字段
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
            'total_days': raw_metadata.get('total_days', 0) if raw_metadata else 0,
            'valid_days': result['n_days'],
            'avg_stocks_per_day': int(factor_data.groupby('date').size().mean())
        },
        
        # 五维度判断（遵循 PROJECT.md IC 计算规范）
        'statistical_significance': result['statistical_significance'],
        'factor_direction': result['factor_direction'],
        'economic_significance': result['economic_significance'],
        'icir_stability': result['icir_stability'],
        'ic_distribution_consistency': result['ic_distribution_consistency'],
        
        # ic_series 输出字段（遵循 PROJECT.md ic_series 结构规范）
        'dates': dates,
        'ic_values': ic_values,
        'rolling_ic_mean': rolling_ic_mean,
        
        # 额外字段（保留原有功能）
        'positive_ratio': round(result['positive_ratio'], 4),
        't_stat': result['t_stat'],
        'n_assets': factor_data['asset'].nunique(),
        'summary': result['summary']
    }


def generate_turnover_surge_ic_data(
    n_days: int = 500,
    output_file: str = None,
    force_full: bool = False
) -> Dict:
    """
    从缓存数据计算换手率突增因子 IC
    
    参数:
        n_days: 保留最近多少天的数据
        output_file: 输出文件路径
        force_full: 强制全量计算
        
    返回:
        IC 数据字典
    """
    FACTOR_NAME = 'turnover_surge_1d'
    
    if output_file is None:
        output_file = get_ic_output_path(FACTOR_NAME)
    
    # 增量判断（除非强制全量）
    if not force_full:
        mode, missing_dates, info = check_data_completeness(FACTOR_NAME)
        
        if mode == 'skip':
            print("\n数据完备，无需更新")
            try:
                with open(output_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception as e:
                print(f"读取缓存失败: {e}，将执行全量计算")
                # 显式 fallthrough 到全量计算（遵循 PROJECT.md 增量模式异常处理规范）
                pass  # except 块结束，代码继续向下执行全量计算
    
    # 全量计算
    print("=" * 60)
    print("换手率突增因子 IC 计算器（缓存版） - 1日收益周期")
    print("=" * 60)
    
    # 加载数据
    print("\n[1/3] 从缓存加载换手率和收益数据...")
    try:
        factor_df, return_df, raw_metadata = load_data_from_cache()
        
        if factor_df['asset'].nunique() < 10:
            raise ValueError(
                f"股票数量不足以计算有效的 IC\n"
                f"当前: {factor_df['asset'].nunique()} < 10"
            )
    except Exception as e:
        raise RuntimeError(f"数据加载失败: {e}")
    
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
    ic_data = calculate_turnover_surge_ic(factor_df, return_df, raw_metadata=raw_metadata)
    
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
        
        # ic_series 输出字段（遵循 PROJECT.md ic_series 结构规范）
        'ic_series': {
            'dates': ic_data['dates'],
            'ic_values': ic_data['ic_values'],
            'rolling_ic_mean': ic_data['rolling_ic_mean']
        },
        
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
    output_file = Path(output_file)
    output_file.parent.mkdir(parents=True, exist_ok=True)
    
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(result_json, f, ensure_ascii=False, indent=2)
    
    print(f"\n保存数据到: {output_file}")
    print("=" * 60)
    print(f"完成！共计算 {ic_data['sample_stats']['valid_days']} 天有效 IC 数据（原始数据 {ic_data['sample_stats']['total_days']} 天）")
    print("=" * 60)
    
    return result_json


if __name__ == '__main__':
    # 计算缓存全部日期的 IC 数据
    generate_turnover_surge_ic_data()