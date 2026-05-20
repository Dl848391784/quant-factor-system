#!/usr/bin/env python3
"""
布林带%B 因子 IC 计算器（缓存版） - 1日收益周期

因子定义：
- Middle Band = SMA(Close, N)
- Upper Band = Middle Band + K × StdDev(Close, N)
- Lower Band = Middle Band - K × StdDev(Close, N)
- %B = (Close - Lower Band) / (Upper Band - Lower Band)

参数：
- N = 20（移动平均周期）
- K = 2.0（标准差倍数）

边界处理：
- %B > 1：价格突破上轨，超买信号
- %B = 1：价格在上轨
- 0 < %B < 1：价格在布林带内
- %B = 0：价格在下轨
- %B < 0：价格跌破下轨，超卖信号

因子逻辑：
- %B > 1：超买，预期回落
- %B < 0：超卖，预期反弹
- 使用反向排名（%B值高排名低）

作者: 云舟
日期: 2026-04-07
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

# 导入 IC 计算模块（支持方向验证 + 单日 IC 计算 + IC 统计指标计算）
from factor_ic.common.ic_calculator import (
    calculate_ic_with_direction_verification,
    calculate_single_day_ic,  # 用于增量计算
    calculate_ic_statistics   # 用于增量路径重新计算统计指标
)

# 导入数据完整性检查模块
from factor_ic.common.data_completeness import check_data_completeness, get_ic_output_path

# 导入类型转换模块
from factor_ic.common.convert_types import convert_to_native_types

# 缓存路径
CACHE_DIR = Path(__file__).parent.parent / 'cache' / 'factor_data'
FACTOR_CACHE = CACHE_DIR / 'factor_data.json.gz'
RETURN_CACHE = CACHE_DIR / 'return_data.json.gz'

# 默认参数（遵循 PROJECT.md 参数传递规范）
DEFAULT_MIN_STOCKS = 10  # 每日最少股票数阈值，统一管理


def load_data_from_cache(
    return_col: str = 'forward_return_1d'
) -> Tuple[pd.DataFrame, pd.DataFrame, dict]:
    """
    从缓存加载因子数据和收益数据
    
    参数:
        return_col: 收益列名
        
    返回:
        (factor_df, return_df, raw_metadata)
        - factor_df: 过滤后的因子数据 DataFrame（包含 date, asset, close）
        - return_df: 过滤后的收益数据 DataFrame
        - raw_metadata: 原始数据元信息字典
            - period_start: 原始缓存最小日期
            - period_end: 原始缓存最大日期
            - total_days: 原始缓存日期数
    
    规范:
        布林带因子必须使用 close 价格，这是布林带的数学定义
        因此固定加载和过滤 'close' 列，不接受 factor_col 参数
        （遵循 MODULE.md 布林带因子固定使用 close 列规范）
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
    # 统一转换为字符串格式 "YYYY-MM-DD"，确保 isin 操作类型匹配
    if 'date' in factor_df.columns:
        date_series = pd.to_datetime(factor_df['date'], errors='coerce')
        nat_count = date_series.isna().sum()
        if nat_count > 0:
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
    # 布林带因子固定使用 close 列，检查 close 列是否存在
    if 'close' not in factor_df.columns:
        available_cols = sorted([c for c in factor_df.columns if c not in ['date', 'asset']])
        raise KeyError(
            "布林带因子必须使用 'close' 列（布林带的数学定义）\n"
            f"但缓存数据中不存在 'close' 列\n"
            f"可用列: {available_cols}"
        )
    
    # 布林带因子固定加载 'close' 列（遵循 MODULE.md 布林带因子固定使用 close 列规范）
    # 布林带公式必须使用 close 价格：中轨 = SMA(close, N)
    factor_cols = ['date', 'asset', 'close']  # 固定列名，不接受参数
    factor_df = factor_df[factor_cols].copy()
    
    # 输入验证：检查收益列是否存在
    if return_col not in return_df.columns:
        available_cols = sorted([c for c in return_df.columns if c not in ['date', 'asset']])
        raise KeyError(
            f"收益列 '{return_col}' 不存在于缓存数据中\n"
            f"可用收益列: {available_cols}"
        )
    
    # 重命名收益列（统一为 forward_return）
    return_df = return_df[['date', 'asset', return_col]].copy()
    return_df = return_df.rename(columns={return_col: 'forward_return'})
    
    # 在 dropna 之前，计算原始数据范围（遵循 PROJECT.md 输出字段语义规范）
    raw_period_start = str(factor_df['date'].min())
    raw_period_end = str(factor_df['date'].max())
    raw_total_days = factor_df['date'].nunique()
    
    print(f"  - 原始数据范围: {raw_period_start} ~ {raw_period_end}, {raw_total_days} 个交易日")
    
    # 过滤缺失值（遵循 PROJECT.md 数据过滤后索引处理规范）
    # 布林带因子固定过滤 close 列的 NaN
    factor_df = factor_df.dropna(subset=['close']).reset_index(drop=True)
    return_df = return_df.dropna(subset=['forward_return']).reset_index(drop=True)
    
    print(f"  - 过滤缺失值后: 因子 {len(factor_df)} 行（过滤列: ['close']），收益 {len(return_df)} 行")
    
    # 返回过滤后的数据 + 原始数据元信息
    return factor_df, return_df, {
        'period_start': raw_period_start,
        'period_end': raw_period_end,
        'total_days': raw_total_days
    }


# ============================================================
# 布林带%B 因子计算函数（向量化版本）
# ============================================================

def calculate_bollinger_pb_1d_factor(
    factor_df: pd.DataFrame,
    n: int = 20,
    k: float = 2.0
) -> Tuple[pd.DataFrame, dict]:
    """
    计算所有股票的布林带%B 因子（向量化版本，高效）
    
    使用 pandas 分组操作和向量化计算。
    
    Args:
        factor_df: 包含 date, asset, close 的 DataFrame
        n: 移动平均周期（默认 20）
        k: 标准差倍数（默认 2.0）
        
    Returns:
        (处理后的 factor_df, 统计信息)
    """
    print(f"\n{'='*60}")
    print(f"[因子计算] 布林带%B_1D 因子 (N={n}, K={k})")
    print(f"{'='*60}")
    
    stats = {
        'total_records': len(factor_df),
        'valid_records': 0,
        'missing_price_count': 0,
        'n': n,
        'k': k
    }
    
    if factor_df.empty:
        print("  ✗ 数据为空")
        return factor_df, stats
    
    # 检查必要列
    required_cols = ['date', 'asset', 'close']
    missing_cols = [c for c in required_cols if c not in factor_df.columns]
    if missing_cols:
        print(f"  ✗ 缺少必要列: {missing_cols}")
        return factor_df, stats
    
    # 统计缺失数据
    missing_price_mask = factor_df['close'].isna()
    stats['missing_price_count'] = int(missing_price_mask.sum())
    
    print(f"  总记录数: {stats['total_records']:,}")
    print(f"  价格缺失数: {stats['missing_price_count']:,}")
    
    # 按股票分组计算布林带%B（使用向量化操作）
    print(f"\n[计算] 使用向量化计算布林带%B...")
    
    # 确保按日期排序（每个股票内部）
    factor_df = factor_df.sort_values(['asset', 'date']).copy()
    
    # ========== 向量化计算布林带 ==========
    print(f"  [Step 1] 计算中轨（SMA）...")
    
    # 按股票分组计算滚动窗口
    # min_periods=n：遵循布林带标准定义，满 N 个周期才计算
    # 前N-1个交易日的布林带值为 NaN（等待足够数据）
    factor_df['middle_band'] = factor_df.groupby('asset')['close'].transform(
        lambda x: x.rolling(window=n, min_periods=n).mean()
    )
    
    print(f"  [Step 2] 计算标准差（总体标准差，ddof=0）...")
    # 布林带标准定义使用总体标准差（Population Standard Deviation）
    # pandas rolling().std() 默认 ddof=1（样本标准差），需显式指定 ddof=0
    # 遵循 MODULE.md 技术指标参数规范
    factor_df['std_dev'] = factor_df.groupby('asset')['close'].transform(
        lambda x: x.rolling(window=n, min_periods=n).std(ddof=0)
    )
    
    print(f"  [Step 3] 计算上轨和下轨...")
    factor_df['upper_band'] = factor_df['middle_band'] + k * factor_df['std_dev']
    factor_df['lower_band'] = factor_df['middle_band'] - k * factor_df['std_dev']
    
    # ========== 计算 %B ==========
    print(f"  [Step 4] 计算 %B...")
    
# 处理除零和 NaN 情况（遵循 MODULE.md 布林带 %B 计算显式处理 NaN 规范）
    # 核心原则：显式处理 NaN，避免依赖 NaN 传播的隐式行为
    # 布林带预热期（前 N-1 日）：upper_band/lower_band 为 NaN → diff 为 NaN
    # 浮点数除零：diff ≈ 0（宽度为零）→ 定义 %B = 0.5
    
    diff = factor_df['upper_band'] - factor_df['lower_band']
    
    # 显式处理三种情况：
    # 1. diff 为 NaN（布林带预热期）→ %B = NaN
    # 2. diff ≈ 0（布林带宽度为零）→ %B = 0.5
    # 3. diff > 0（正常情况）→ %B = (close - lower) / diff
    
    factor_df['bollinger_pb_1d'] = np.where(
        pd.isna(diff),  # 显式检查 NaN（布林带预热期）
        np.nan,         # NaN → NaN（显式定义，而非依赖隐式传播）
        np.where(
            np.abs(diff) < 1e-10,  # 浮点数精度容差判断
            0.5,  # 布林带宽度为零时，%B 定义为 0.5（价格在中轨）
            (factor_df['close'] - factor_df['lower_band']) / diff  # 正常计算
        )
    )
    
    # 释放临时列
    factor_df.drop(columns=['middle_band', 'std_dev', 'upper_band', 'lower_band'], inplace=True)
    
    # 统计有效记录
    stats['valid_records'] = int(factor_df['bollinger_pb_1d'].notna().sum())
    
    # 输出统计
    print(f"\n  有效记录数: {stats['valid_records']:,}")
    
    # 输出因子统计
    valid_values = factor_df['bollinger_pb_1d'].dropna()
    if len(valid_values) > 0:
        print(f"\n  因子统计:")
        print(f"    均值:   {valid_values.mean():.4f}")
        print(f"    标准差: {valid_values.std():.4f}")
        print(f"    最小值: {valid_values.min():.4f}")
        print(f"    最大值: {valid_values.max():.4f}")
        print(f"    中位数: {valid_values.median():.4f}")
        
        # 超买超卖统计
        overbought = (valid_values > 1).sum()
        oversold = (valid_values < 0).sum()
        in_band = ((valid_values >= 0) & (valid_values <= 1)).sum()
        print(f"\n  超买(%B>1):  {overbought:,} ({overbought/len(valid_values)*100:.2f}%)")
        print(f"  超卖(%B<0):  {oversold:,} ({oversold/len(valid_values)*100:.2f}%)")
        print(f"  布林带内:   {in_band:,} ({in_band/len(valid_values)*100:.2f}%)")
    
    # 转换统计中的 numpy 类型
    stats = convert_to_native_types(stats)
    
    return factor_df, stats


def calculate_daily_ic_series(
    factor_df: pd.DataFrame,
    return_df: pd.DataFrame,
    raw_metadata: dict,
    min_stocks: int = 10
) -> dict:
    """
    计算每日的 IC 时间序列
    
    参数:
        factor_df: 因子数据（已过滤缺失值）
        return_df: 收益数据（已过滤缺失值）
        raw_metadata: 原始数据元信息（遵循 PROJECT.md period/total_days 数据源规范）
            - period_start: 原始缓存最小日期
            - period_end: 原始缓存最大日期
            - total_days: 原始缓存日期数
        min_stocks: 最小股票数阈值（遵循 PROJECT.md 参数传递规范）
    
    返回:
        dict: IC 计算结果（符合 PROJECT.md 五维度判断规范）
    
    注意:
        period.start/end 直接使用 raw_metadata，不从 factor_df 推断
        原因：raw_metadata 表示原始缓存范围（dropna 前），factor_df 表示过滤后范围
    """
    # 使用 IC 计算（支持因子方向验证）
    result = calculate_ic_with_direction_verification(
        factor_df=factor_df,
        return_df=return_df,
        factor_col='bollinger_pb_1d',
        return_col='forward_return',
        date_col='date',
        asset_col='asset',
        min_stocks=min_stocks  # 遵循 PROJECT.md 参数传递规范
    )
    
    # 函数返回值契约校验（遵循 MODULE.md 函数返回值契约规范）
    # 核心原则：p_value 是必需字段（回退逻辑依赖），p_value_display 是可选字段（可从 p_value 计算）
    required_fields = [
        'ic_series', 'ic_mean', 'ic_std', 'icir', 'p_value',  # p_value 必需
        'statistical_significance', 'factor_direction',
        'economic_significance', 'positive_ratio', 'summary'
    ]
    # p_value_display 是可选字段，不校验（可从 p_value 计算回退值）
    missing_fields = [f for f in required_fields if f not in result]
    if missing_fields:
        raise RuntimeError(
            f"calculate_ic_with_direction_verification 返回值缺少必需字段\n"
            f"缺失字段: {missing_fields}\n"
            f"问题定位: factor_ic/common/ic_calculator.py\n"
            f"期望字段: {required_fields}"
        )
    
    ic_series = result['ic_series']
    
    # ic_series 显式排序（遵循 MODULE.md ic_series 排序规范）
    ic_series = ic_series.sort_index()
    
    # 防御性校验：确保 dates 按升序排列
    dates_from_series = [str(d) for d in ic_series.index]
    if dates_from_series != sorted(dates_from_series):
        raise RuntimeError(
            f"ic_series.index 未按日期升序排列\n"
            f"问题定位: factor_ic/ic_bollinger_pb_1d.py calculate_daily_ic_series\n"
            f"请检查 calculate_ic_with_direction_verification 返回值"
        )
    
    # 获取日期范围（直接使用 raw_metadata，遵循 PROJECT.md 输出字段语义规范）
    period_start = raw_metadata['period_start']
    period_end = raw_metadata['period_end']
    
    # 转换为 JSON 友好格式
    dates = [str(d) for d in ic_series.index]
    ic_values = [round(v, 6) for v in ic_series.values]
    
    # 日期格式断言（遵循 PROJECT.md 日期字符串比较规范）
    # 核心原则：全量路径与增量路径保持一致的防御机制
    # 检查关键日期格式是否符合 YYYY-MM-DD 约定
    # 注意：dates 已定义，可以直接使用
    dates_to_check = [dates[0] if len(dates) > 0 else None, 
                      dates[-1] if len(dates) > 0 else None,
                      period_start, period_end]
    
    for d in dates_to_check:
        if d is not None and not re.match(r'^\d{4}-\d{2}-\d{2}$', str(d)):
            raise ValueError(
                f"日期格式不符合 YYYY-MM-DD 约定: {d}\n"
                f"位置: 全量路径 calculate_daily_ic_series\n"
                f"请检查因子数据或缓存数据的日期格式"
            )
    
    # 计算 20 日滚动均值（min_periods=10，至少需要10个有效值）
    rolling_mean = ic_series.rolling(window=20, min_periods=10).mean()
    
    # NaN → None 转换（遵循 MODULE.md NaN 处理规范）
    # 在数据生成阶段处理，而非延迟到 convert_to_native_types
    rolling_ic_mean = [
        round(v, 6) if not pd.isna(v) else None
        for v in rolling_mean.values
    ]
    
    # 符合 PROJECT.md 规范的数据结构（五维度判断）
    return {
        'factor_name': 'bollinger_pb_1d',
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
            # p_value_display 回退逻辑说明（遵循 MODULE.md 可选字段回退逻辑规范）
            # 核心原则：p_value_display 是可选字段，缺少时从 p_value 计算
            # p_value 是必需字段（已校验），回退逻辑可靠
            'p_value_display': result.get('p_value_display', str(round(result['p_value'], 6)))
        },
        'statistical_significance': {
            'is_significant': result['statistical_significance']['is_significant'],
            'p_value': result['statistical_significance']['p_value'],
            'p_value_display': result['statistical_significance']['p_value_display'],
            't_stat': result['statistical_significance']['t_stat'],
            'conclusion': result['statistical_significance']['conclusion']
        },
        'factor_direction': {
            'direction': result['factor_direction']['ic_mean_sign'],
            'ic_mean': result['factor_direction']['ic_mean'],
            'conclusion': result['factor_direction']['conclusion']
        },
        'economic_significance': {
            'ic_strength': result['economic_significance']['level'],
            'ic_mean_abs': result['economic_significance']['abs_ic_mean'],
            'conclusion': result['economic_significance']['conclusion']
        },
        'sample_stats': {
            # 语义定义（遵循 PROJECT.md 输出字段语义规范）：
            # - total_days: 因子缓存覆盖的日期数（包含无效日期）
            # - valid_days: 实际计算出 IC 的天数（每交易日股票数 >= min_stocks）
            # - avg_stocks_per_day: 当前因子缓存范围内的平均每日股票数
            #   - 口径范围见 avg_stocks_period 字段（遵循 PROJECT.md 输出字段口径规范）
            # - 差值含义: total_days - valid_days = 因股票不足或数据缺失跳过的交易日数
            'total_days': raw_metadata.get('total_days', factor_df['date'].nunique()),
            'valid_days': len(dates),
            'avg_stocks_per_day': int(factor_df.groupby('date').size().mean()),
            'avg_stocks_period': {
                'start': str(factor_df['date'].min()),
                'end': str(factor_df['date'].max()),
                'description': f"avg_stocks_per_day 反映 {factor_df['date'].min()} ~ {factor_df['date'].max()} 范围内的平均每日股票数"
            }
        },
        'dates': dates,
        'ic_values': ic_values,
        'rolling_ic_mean': rolling_ic_mean,
        'positive_ratio': round(result['positive_ratio'], 4),
        'n_assets': factor_df['asset'].nunique(),
        'summary': result['summary']
    }


def _full_recalculate(
    output_file: Path,
    n: int = 20,
    k: float = 2.0,
    min_stocks: int = DEFAULT_MIN_STOCKS
) -> dict:
    """
    全量重新计算布林带%B IC 数据
    
    参数:
        output_file: 输出文件路径
        n: 布林带移动平均周期
        k: 布林带标准差倍数
        min_stocks: 最小股票数阈值（遵循 PROJECT.md 参数传递规范）
        
    返回:
        IC 数据字典
    """
    print("=" * 60)
    print("布林带%B_1D IC 计算器（全量模式）")
    print("=" * 60)
    print(f"参数: N={n}, K={k}")
    
    # 从缓存加载数据
    # 布林带因子固定使用 close 列，load_data_from_cache 内部已硬编码
    # 不需要传 factor_col 参数（函数签名不接受该参数）
    print("\n[1/3] 从缓存加载因子和收益数据...")
    try:
        factor_df, return_df, raw_metadata = load_data_from_cache()
        
        # 检查数据量（遵循 PROJECT.md 参数传递规范）
        if factor_df['asset'].nunique() < min_stocks:
            raise ValueError(
                f"股票数量不足以计算有效的 IC\n"
                f"当前: {factor_df['asset'].nunique()} < {min_stocks}"
            )
            
    except FileNotFoundError as e:
        raise RuntimeError(f"缓存文件不存在，请检查缓存路径\n原始错误: {e}") from e
    except json.JSONDecodeError as e:
        raise RuntimeError(f"缓存文件 JSON 格式错误，请检查缓存文件\n原始错误: {e}") from e
    except KeyError as e:
        raise RuntimeError(f"缓存字段缺失，可能是缓存版本过期\n缺失字段: {e}") from e
    except ValueError as e:
        # 数据量不足：保留原始异常类型和完整堆栈信息
        # 使用裸 raise 保留 ValueError（不重新包装，不改变异常链）
        # 原因：ValueError 是业务逻辑主动抛出的，信息已足够，无需额外包装
        raise
    except Exception as e:
        raise RuntimeError(f"数据加载时发生未预期的异常\n异常类型: {type(e).__name__}\n原始错误: {e}") from e
    
    # 数据统计
    print(f"\n数据统计:")
    print(f"  - 原始日期范围: {raw_metadata['period_start']} ~ {raw_metadata['period_end']}")
    print(f"  - 原始交易日数: {raw_metadata['total_days']}")
    print(f"  - 过滤后交易日数: {factor_df['date'].nunique()}")
    print(f"  - 股票数量: {factor_df['asset'].nunique()}")
    
    # 计算布林带%B因子
    print(f"\n[2/3] 计算布林带%B 因子...")
    factor_df, factor_stats = calculate_bollinger_pb_1d_factor(factor_df, n=n, k=k)
    
    # 选择必要列（遵循 MODULE.md 数据传递规范）
    # 注意：不在此处合并数据，合并操作在 calculate_ic_with_direction_verification 内部完成
    # 原因：calculate_ic_with_direction_verification 接收未合并的 factor_df 和 return_df
    factor_df = factor_df[['date', 'asset', 'bollinger_pb_1d']].copy()
    
    # 计算 IC
    print(f"\n[3/3] 计算每日 IC...")
    ic_data = calculate_daily_ic_series(factor_df, return_df, raw_metadata, min_stocks=min_stocks)
    print(f"  - IC 均值: {ic_data['ic_metrics']['ic_mean']:.4f}")
    print(f"  - ICIR: {ic_data['ic_metrics']['icir']:.2f}")
    print(f"  - 正比例: {ic_data['positive_ratio']:.1%}")
    t_stat = ic_data['statistical_significance']['t_stat']
    is_sig = ic_data['statistical_significance']['is_significant']
    print(f"  - t 统计量: {t_stat:.2f} {'显著' if is_sig else '不显著'}")
    
    # 添加因子统计信息
    ic_data['factor_stats'] = factor_stats
    ic_data['update_mode'] = 'full'
    
    # 保存数据
    print(f"\n[保存] 保存数据到: {output_file}")
    output_file.parent.mkdir(parents=True, exist_ok=True)
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(convert_to_native_types(ic_data), f, ensure_ascii=False, indent=2)
    
    print("\n" + "=" * 60)
    print(f"完成！共计算 {ic_data['sample_stats']['valid_days']} 天有效 IC 数据（原始数据 {ic_data['sample_stats']['total_days']} 天）")
    print("=" * 60)
    
    return ic_data


def _incremental_update(
    missing_dates: list,
    output_file: Path,
    n: int = 20,
    k: float = 2.0,
    min_stocks: int = DEFAULT_MIN_STOCKS
) -> dict:
    """
    增量更新：只计算缺失日期的 IC，合并到现有缓存
    
    参数:
        missing_dates: 缺失日期列表
        output_file: 输出文件路径
        n: 布林带移动平均周期
        k: 布林带标准差倍数
        min_stocks: 最小股票数阈值（遵循 PROJECT.md 参数传递规范）
        
    返回:
        IC 数据字典
    """
    print("=" * 60)
    print("布林带%B_1D IC 计算器（增量模式）")
    print("=" * 60)
    print(f"[增量模式] 缺失 {len(missing_dates)} 天数据，执行增量更新")
    
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
        return _full_recalculate(output_file, n=n, k=k, min_stocks=min_stocks)
    
    # 加载全量缓存数据
    # 布林带计算说明（遵循 MODULE.md 增量路径布林带历史数据必要性规范）：
    # - 布林带使用 rolling(window=N) 计算 SMA 和 Std，每个目标日期需要前面 N-1 天历史数据
    # - 例如 N=20：计算 2024-01-20 的布林带，需要 2024-01-01 ~ 2024-01-19 的历史数据
    # - 因此必须加载全量数据计算布林带，再筛选缺失日期
    # - 这是必要的，不是浪费：缺失日期的布林带依赖历史数据作为滚动窗口
    print(f"\n[2/4] 加载全量数据计算布林带（缺失 {len(missing_dates)} 天）...")
    factor_df_full, return_df_full, raw_metadata = load_data_from_cache()
    
    # 边界检查：最小必需历史窗口（遵循 MODULE.md 增量路径最小必需历史窗口边界检查规范）
    # 布林带需要前 N-1 天数据，缺失日期如果靠近缓存起始点，可能因预热期不足而全为 NaN
    cache_start_date = raw_metadata['period_start']
    cache_start_dt = pd.to_datetime(cache_start_date)
    
    # 计算布林带预热期边界日期（缓存起始点后 N-1 天）
    warmup_boundary_date = (cache_start_dt + pd.Timedelta(days=n-1)).strftime('%Y-%m-%d')
    warmup_days_count = n - 1
    
    # 检查缺失日期是否在预热期内
    missing_dates_in_warmup = [d for d in missing_dates if d <= warmup_boundary_date]
    
    if missing_dates_in_warmup:
        print(f"  [边界检查] 缓存起始: {cache_start_date}")
        print(f"  [边界检查] 布林带预热期: 前 {warmup_days_count} 天（{cache_start_date} ~ {warmup_boundary_date}）")
        print(f"  [边界检查] {len(missing_dates_in_warmup)} 个缺失日期在预热期内，因子值可能全为 NaN")
        examples = sorted(missing_dates_in_warmup)[:5]
        print(f"  [边界检查] 示例日期: {examples}")
        if len(missing_dates_in_warmup) == len(missing_dates):
            print("  [边界检查] 所有缺失日期都在预热期内，无法计算有效 IC")
            print("  [建议] 延长缓存历史范围，或跳过这些日期")
            # 不直接返回缓存，继续计算以验证（可能部分股票有更多历史数据）
    
    # 计算布林带%B因子（全量数据，滚动窗口需要历史数据）
    factor_df_full, factor_stats = calculate_bollinger_pb_1d_factor(factor_df_full, n=n, k=k)
    factor_df_full = factor_df_full[['date', 'asset', 'bollinger_pb_1d']].copy()
    
    # 筛选缺失日期的数据
    missing_set = set(missing_dates)
    factor_df_new = factor_df_full[factor_df_full['date'].isin(missing_set)]
    return_df_new = return_df_full[return_df_full['date'].isin(missing_set)]
    
    # 诊断：检查缺失日期的数据覆盖情况
    dates_in_cache = set(factor_df_full['date'].unique())
    dates_not_in_cache = missing_set - dates_in_cache
    
    if dates_not_in_cache:
        print(f"  [警告] {len(dates_not_in_cache)} 个缺失日期不在当前因子缓存范围")
        examples = sorted(dates_not_in_cache)[:5]
        print(f"  [警告] 示例日期: {examples}")
    
    if factor_df_new.empty:
        print("  - 跳过增量计算，返回现有缓存")
        return existing_data
    
    # 检查因子值有效性（遵循 MODULE.md 增量路径因子值有效性检查规范）
    # 布林带需要前N-1日数据预热，缺失日期可能全为 NaN
    valid_factor_count = factor_df_new['bollinger_pb_1d'].notna().sum()
    total_factor_count = len(factor_df_new)
    
    if valid_factor_count == 0:
        print("  [诊断] 缺失日期的因子值全为 NaN（可能因布林带预热期）")
        print(f"  [诊断] 缺失日期: {sorted(factor_df_new['date'].unique())[:5]}")
        print("  [建议] 这些日期需要更多历史数据才能计算布林带，跳过增量计算")
        print("  - 返回现有缓存")
        return existing_data
    
    print(f"  - 筛选后: {len(factor_df_new)} 行，其中 {valid_factor_count} 行有效因子值")
    if total_factor_count - valid_factor_count > 0:
        print(f"  - {total_factor_count - valid_factor_count} 行因子值为 NaN（布林带预热期）")
    
    # 计算新日期的每日 IC（遵循 MODULE.md 增量路径向量化计算 IC 规范）
    # 核心原则：先整体 merge，再按日期 groupby 计算，避免逐行循环性能问题
    print("\n[3/4] 计算新日期 IC...")
    new_dates = sorted(factor_df_new['date'].unique())
    
    # 向量化处理：先整体 merge（一次操作）
    merged_new = factor_df_new.merge(return_df_new, on=['date', 'asset'], how='inner')
    
    # 检查 merge 后是否有数据
    if merged_new.empty:
        print("  [警告] merge 后无数据，所有日期因股票数不足跳过")
        new_ic_values = [None] * len(new_dates)
    else:
        # 按日期分组计算 IC（向量化）
        # 使用 groupby 避免逐行循环，提升性能约 N 倍（N 为 missing_dates 数）
        ic_results = {}
        for date, group in merged_new.groupby('date'):
            ic_value = calculate_single_day_ic(
                group, factor_col='bollinger_pb_1d', return_col='forward_return', min_stocks=min_stocks
            )
            ic_results[date] = round(ic_value, 6) if ic_value is not None else None
        
        # 按日期顺序填充 IC 值（缺失日期填充 None）
        new_ic_values = [ic_results.get(date) for date in new_dates]
    
    # 过滤 None 值
    valid_new_ic = [ic for ic in new_ic_values if ic is not None]
    skipped_new_ic = len(new_dates) - len(valid_new_ic)
    
    print(f"  - 计算完成: {len(new_dates)} 天，其中 {len(valid_new_ic)} 天有效 IC")
    if skipped_new_ic > 0:
        print(f"  - {skipped_new_ic} 天因股票数不足跳过")
    
    # 合并数据（遵循 MODULE.md 注释缩进一致性规范）
    print("\n[4/4] 合并数据并重新计算统计指标...")
    
    # 检查重叠
    existing_set = set(existing_dates)
    new_set = set(new_dates)
    overlap_dates = existing_set & new_set
    
    if overlap_dates:
        print(f"  [警告] 发现 {len(overlap_dates)} 个重叠日期，将使用新计算的 IC 值覆盖")
    
    # 使用字典去重（遵循 MODULE.md 增量路径 None 值保留规范）
    # 核心原则：保留所有日期（包括 None IC 值的日期），不过滤 None
    # 这样 total_days 与 valid_days 的差值才能正确反映"股票数不足跳过"的日期数
    date_ic_map = {}
    for date, ic in zip(existing_dates, existing_ic_values):
        date_ic_map[date] = ic  # 保留 None 值，不过滤
    for date, ic in zip(new_dates, new_ic_values):
        date_ic_map[date] = ic  # 保留 None 值，不过滤
    
    # 按日期排序（包含所有日期，包括 None IC 值的日期）
    all_dates = sorted(date_ic_map.keys())
    all_ic_values = [date_ic_map[d] for d in all_dates]  # 包含 None
    
    # 统计有效 IC 数（用于诊断信息）
    valid_ic_count = sum(1 for ic in all_ic_values if ic is not None)
    none_ic_count = len(all_ic_values) - valid_ic_count
    
    print(f"  - 合并后总计: {len(all_dates)} 天（去重后）")
    if none_ic_count > 0:
        print(f"  - 其中 {valid_ic_count} 天有效 IC，{none_ic_count} 天因股票数不足跳过（IC=None）")
    
    # 重新计算统计指标（遵循 MODULE.md 增量路径 rolling_ic_mean 规范）
    # 核心原则：rolling_ic_mean 必须基于 all_dates 计算，与 dates/ic_values 长度一致
    # calculate_ic_statistics 已在文件顶部导入（遵循 PEP8 import 规范）
    ic_series = pd.Series(all_ic_values, index=all_dates)
    result = calculate_ic_statistics(ic_series)
    
    # 添加滚动IC均值计算（基于 all_dates，与全量路径一致）
    rolling_ic_mean_series = ic_series.rolling(window=20, min_periods=10).mean()
    
    # NaN → None 转换（遵循 MODULE.md NaN 处理规范）
    # 在数据生成阶段处理，而非延迟到 convert_to_native_types
    rolling_ic_mean = [
        round(v, 6) if not pd.isna(v) else None
        for v in rolling_ic_mean_series.values
    ]
    
    # 日期格式断言（遵循 PROJECT.md 日期字符串比较规范)
    # 核心原则：all_dates 为空时跳过日期格式检查（避免 IndexError）
    if len(all_dates) == 0:
        print("  [警告] 合并后无有效日期，跳过日期格式检查")
        dates_to_check = [raw_metadata['period_start'], raw_metadata['period_end']]
    else:
        dates_to_check = [all_dates[0], all_dates[-1], raw_metadata['period_start'], raw_metadata['period_end']]
    
    for d in dates_to_check:
        if not re.match(r'^\d{4}-\d{2}-\d{2}$', str(d)):
            raise ValueError(f"日期格式不符合 YYYY-MM-DD 约定: {d}")
    
    # 构建合并后的数据结构
    merged_data = {
        'factor_name': 'bollinger_pb_1d',
        'calculation_date': datetime.now().strftime('%Y-%m-%d'),
        'period': {
            'start': raw_metadata['period_start'],  # 原始缓存范围（与全量路径一致）
            'end': raw_metadata['period_end']       # 原始缓存范围（与全量路径一致）
        },
        'ic_metrics': {
            'ic_mean': round(result['ic_mean'], 6),
            'ic_std': round(result['ic_std'], 6),
            'icir': round(result['icir'], 4),
            'p_value': round(result['p_value'], 6),  # ✓ 与全量路径一致
            'p_value_display': result.get('p_value_display', str(round(result['p_value'], 6)))  # 可选字段，缺少时从 p_value 计算
        },
        'sample_stats': {  # ✓ 8空格缩进，与上方字段对齐
            'total_days': raw_metadata.get('total_days', 0),  # 直接使用原始缓存天数（遵循 MODULE.md total_days 规范）
            'valid_days': len(all_dates),
            'avg_stocks_per_day': int(factor_df_full.groupby('date').size().mean()),
            'avg_stocks_period': {
                'start': str(factor_df_full['date'].min()),
                'end': str(factor_df_full['date'].max()),
                'description': f"avg_stocks_per_day 反映此范围内的平均每日股票数"
            }
        },
        'statistical_significance': result['statistical_significance'],  # ✓ 直接透传（字段名一致）
        'factor_direction': {  # ✓ 重映射字段名（与全量路径一致）
            'direction': result['factor_direction']['ic_mean_sign'],
            'ic_mean': result['factor_direction']['ic_mean'],
            'conclusion': result['factor_direction']['conclusion']
        },
        'economic_significance': {  # ✓ 重映射字段名（与全量路径一致）
            'ic_strength': result['economic_significance']['level'],
            'ic_mean_abs': result['economic_significance']['abs_ic_mean'],
            'conclusion': result['economic_significance']['conclusion']
        },
        'dates': all_dates,
        'ic_values': all_ic_values,
        'rolling_ic_mean': rolling_ic_mean,  # 添加滚动IC均值字段
        'positive_ratio': round(result['positive_ratio'], 4),
        'n_assets': factor_df_full['asset'].nunique(),
        'summary': result['summary'],
        'factor_stats': factor_stats,  # 因子统计信息（与全量路径一致）
        'update_mode': 'incremental',
        'incremental_days': len(new_dates)
    }
    
    # 保存
    print(f"\n保存数据到: {output_file}")
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(convert_to_native_types(merged_data), f, ensure_ascii=False, indent=2)
    
    print("\n" + "=" * 60)
    print(f"增量更新完成！新增 {len(new_dates)} 天，总计 {len(all_dates)} 天")
    print("=" * 60)
    
    return merged_data


def generate_bollinger_pb_1d_ic_data(
    output_file: Path | str | None = None,
    force_full: bool = False,
    n: int = 20,
    k: float = 2.0,
    min_stocks: int = DEFAULT_MIN_STOCKS
) -> dict:
    """
    从缓存数据计算布林带%B IC（主入口函数）
    
    参数:
        output_file: 输出文件路径
        force_full: 强制全量计算
        n: 布林带移动平均周期
        k: 布林带标准差倍数
        min_stocks: 最小股票数阈值
    
    返回:
        IC 数据字典
    """
    # 统一转换为 Path 对象
    if output_file is None:
        output_file = get_ic_output_path('bollinger_pb_1d')
    else:
        output_file = Path(output_file)
    
    # 强制全量计算
    if force_full:
        return _full_recalculate(output_file, n=n, k=k, min_stocks=min_stocks)
    
    # 增量判断
    mode, missing_dates, info = check_data_completeness('bollinger_pb_1d')
    
    if mode == 'skip':
        print("\n数据完备，无需更新")
        try:
            with open(output_file, 'r', encoding='utf-8') as f:
                cached_data = json.load(f)
                cached_data['update_mode'] = 'skip'
                return cached_data
        except FileNotFoundError:
            # 缓存文件不存在 → 可恢复错误，降级全量计算
            print("  [诊断] 缓存文件不存在，执行全量计算")
            return _full_recalculate(output_file, n=n, k=k, min_stocks=min_stocks)
        except json.JSONDecodeError as e:
            # JSON解析失败 → 严重错误（文件损坏），不应静默降级
            print("  [严重错误] 缓存文件损坏，JSON解析失败")
            print(f"  [详情] {e}")
            print(f"  [文件] {output_file}")
            print("  [建议] 请检查缓存文件是否损坏，或删除后重新生成")
            raise RuntimeError(
                f"缓存文件损坏，无法解析 JSON: {output_file}\n"
                f"错误详情: {e}\n"
                f"建议: 删除损坏的缓存文件后重新运行"
            ) from e
        except PermissionError as e:
            # 权限问题 → 严重错误，不应静默降级
            print("  [严重错误] 缓存文件权限不足")
            print(f"  [详情] {e}")
            print(f"  [文件] {output_file}")
            raise RuntimeError(
                f"缓存文件权限不足，无法读取: {output_file}\n"
                f"错误详情: {e}"
            ) from e
        except Exception as e:
            # 其他未预期的异常 → 提供详细诊断，不应静默降级
            print("  [未预期错误] 读取缓存失败")
            print(f"  [异常类型] {type(e).__name__}")
            print(f"  [详情] {e}")
            print(f"  [文件] {output_file}")
            raise RuntimeError(
                f"读取缓存失败（未预期异常）: {output_file}\n"
                f"异常类型: {type(e).__name__}\n"
                f"错误详情: {e}"
            ) from e
    
    elif mode == 'incremental':
        return _incremental_update(missing_dates, output_file, n=n, k=k, min_stocks=min_stocks)
    
    elif mode == 'full':
        return _full_recalculate(output_file, n=n, k=k, min_stocks=min_stocks)
    
    else:
        raise RuntimeError(f"未知的更新模式: {mode}，合法值: ['skip', 'incremental', 'full']")


if __name__ == '__main__':
    import argparse
    
    parser = argparse.ArgumentParser(description='布林带%B_1D IC 计算器')
    parser.add_argument('--force-full', action='store_true', 
                        help='强制全量计算（忽略增量判断）')
    parser.add_argument('--n', type=int, default=20,
                        help='布林带移动平均周期（默认: 20）')
    parser.add_argument('--k', type=float, default=2.0,
                        help='布林带标准差倍数（默认: 2.0）')
    
    args = parser.parse_args()
    
    generate_bollinger_pb_1d_ic_data(
        force_full=args.force_full,
        n=args.n,
        k=args.k
    )