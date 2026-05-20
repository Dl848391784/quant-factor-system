#!/usr/bin/env python3
"""
KDJ_J_1D IC 计算器（缓存版） - 1日收益周期

从缓存数据计算 KDJ_J 因子的反向排名 Rank IC。
不再实时拉取数据，直接读取 cache/factor_data/ 下的缓存。

因子定义：
- RSV(N) = (Close_t - Low_N) / (High_N - Low_N) × 100
- K_t = K_{t-1} × (M1-1)/M1 + RSV_t × 1/M1
- D_t = D_{t-1} × (M2-1)/M2 + K_t × 1/M2
- J_t = 3 × K_t - 2 × D_t

参数：
- N = 9（RSV 计算周期）
- M1 = 3（K值平滑周期）
- M2 = 3（D值平滑周期）

因子逻辑：
- J 值 > 100：超买，预期下跌
- J 值 < 0：超卖，预期反弹
- 使用反向排名（J值高排名低）

作者: 云舟
日期: 2026-04-07（重构: 2026-05-10）
"""

import sys
from pathlib import Path

# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent.parent))

import pandas as pd
import numpy as np
import gzip
import json
from typing import Tuple, Optional
from datetime import datetime

# 导入 IC 计算模块（支持方向验证）
from factor_ic.common.ic_calculator import calculate_ic_with_direction_verification

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

# 浮点数精度容差：用于浮点数等值比较（替代 == 0）
# 原因：浮点数运算结果直接 == 0 比较会漏判极小值（如 1e-15）
# 注意：修改此值会影响 RSV 计算等浮点数除零判断逻辑
EPSILON = 1e-10

# 缓存路径
CACHE_DIR = Path(__file__).parent.parent / 'cache' / 'factor_data'
FACTOR_CACHE = CACHE_DIR / 'factor_data.json.gz'
RETURN_CACHE = CACHE_DIR / 'return_data.json.gz'


# ============================================================================
# KDJ 辅助函数（模块级私有函数，显式传参，避免闭包耦合）
# 遵循 MODULE.md 函数设计规范：禁止闭包捕获外部变量，必须显式传参
# ============================================================================

def _calculate_k_with_initial(
    rsv_series: pd.Series,
    alpha_k: float,
    initial_k: float
) -> pd.Series:
    """计算 K 值（正确处理 NaN 前缀版本）
    
    核心逻辑：
    1. RSV 前 N-1 期为 NaN（rolling window min_periods=n）
    2. ewm(ignore_na=False) 使 NaN 传播，前 N-1 期 K 也为 NaN
    3. 第一个有效 RSV 位置设为 initial_k，使该期 K = initial_k
    
    ewm(alpha) 公式：y[t] = alpha * x[t] + (1-alpha) * y[t-1]
    KDJ 公式：K[t] = (1/m1) * K[t-1] + (1-1/m1) * RSV[t]
    要匹配，alpha = 1 - 1/m1 = (m1-1)/m1
    
    Args:
        rsv_series: RSV 序列（单只股票，前 N-1 期为 NaN）
        alpha_k: K 值 ewm 平滑系数（(m1-1)/m1）
        initial_k: K 初始值（标准值 50.0）
    
    Returns:
        K 值序列（前 N-1 期为 NaN）
    
    设计原则：
    - 找到第一个有效 RSV 位置（而非第一个元素）
    - 使用 ignore_na=False 使 NaN 传播
    - 遵循 MODULE.md 无副作用规范
    
    异常处理：捕获 groupby transform 内部异常，附加诊断信息
    """
    if len(rsv_series) == 0:
        return rsv_series
    
    try:
        # 复制 Series，避免修改原始数据
        rsv_copy = rsv_series.copy()
        
        # 找到第一个有效 RSV 的位置（而非第一个元素）
        # 前提：RSV 前 N-1 期为 NaN（rolling window min_periods=n）
        first_valid_idx = rsv_series.first_valid_index()
        
        if first_valid_idx is None:
            # 所有值都是 NaN，返回空序列
            return rsv_series
        
        # 预处理：将第一个有效 RSV 值设为 initial_k
        # ewm(adjust=False) 的第一个有效输出 = 第一个有效输入
        # 因此 ewm 后 K[first_valid_idx] = initial_k
        # 注意：使用索引值访问（rsv_copy[idx]），而非位置索引（rsv_copy.iloc[idx]）
        # 原因：groupby transform 后 Series 的索引是原始索引（如日期），而非位置索引（0, 1, 2...）
        rsv_copy[first_valid_idx] = initial_k
        
        # 计算 ewm 递推：使用 ignore_na=False 使 NaN 传播
        # 前缀 NaN → K[0:first_valid_idx] 为 NaN
        # 第一个有效值 → K[first_valid_idx] = initial_k
        # 后续值 → 标准递推
        k_series = rsv_copy.ewm(alpha=alpha_k, adjust=False, ignore_na=False).mean()
        
        return k_series
        
    except Exception as e:
        # 捕获异常并附加诊断信息（遵循 MODULE.md 异常处理规范）
        raise RuntimeError(
            f"K 值计算异常（groupby transform 内部）\n"
            f"原始异常: {type(e).__name__}: {e}\n"
            f"诊断信息:\n"
            f"  - Series 长度: {len(rsv_series)}\n"
            f"  - 第一个有效位置: {rsv_series.first_valid_index()}\n"
            f"  - 参数: alpha_k={alpha_k}, initial_k={initial_k}\n"
            f"建议: 检查对应股票的 RSV 数据是否存在异常"
        ) from e


def _calculate_d_with_initial(
    k_series: pd.Series,
    alpha_d: float,
    initial_d: float
) -> pd.Series:
    """计算 D 值（正确处理 NaN 前缀版本）
    
    核心逻辑：
    1. K 前 N-1 期为 NaN（因为 RSV 前 N-1 期为 NaN）
    2. ewm(ignore_na=False) 使 NaN 传播，前 N-1 期 D 也为 NaN
    3. 第一个有效 K 位置设为 initial_d，使该期 D = initial_d
    
    ewm(alpha) 公式：y[t] = alpha * x[t] + (1-alpha) * y[t-1]
    KDJ 公式：D[t] = (1/m2) * D[t-1] + (1-1/m2) * K[t]
    要匹配，alpha = 1 - 1/m2 = (m2-1)/m2
    
    Args:
        k_series: K 值序列（单只股票，前 N-1 期为 NaN）
        alpha_d: D 值 ewm 平滑系数（(m2-1)/m2）
        initial_d: D 初始值（标准值 50.0）
    
    Returns:
        D 值序列（前 N-1 期为 NaN）
    
    设计原则：
    - 找到第一个有效 K 位置（而非第一个元素）
    - 使用 ignore_na=False 使 NaN 传播
    - 遵循 MODULE.md 无副作用规范
    
    异常处理：捕获 groupby transform 内部异常，附加诊断信息
    """
    if len(k_series) == 0:
        return k_series
    
    try:
        # 复制 Series，避免修改原始数据
        k_copy = k_series.copy()
        
        # 找到第一个有效 K 的位置（而非第一个元素）
        # 前提：K 前 N-1 期为 NaN（因为 RSV 前 N-1 期为 NaN）
        first_valid_idx = k_series.first_valid_index()
        
        if first_valid_idx is None:
            # 所有值都是 NaN，返回空序列
            return k_series
        
        # 预处理：将第一个有效 K 值设为 initial_d
        # ewm(adjust=False) 的第一个有效输出 = 第一个有效输入
        # 因此 ewm 后 D[first_valid_idx] = initial_d
        # 注意：使用索引值访问（k_copy[idx]），而非位置索引（k_copy.iloc[idx]）
        # 原因：groupby transform 后 Series 的索引是原始索引（如日期），而非位置索引（0, 1, 2...）
        k_copy[first_valid_idx] = initial_d
        
        # 计算 ewm 递推：使用 ignore_na=False 使 NaN 传播
        # 前缀 NaN → D[0:first_valid_idx] 为 NaN
        # 第一个有效值 → D[first_valid_idx] = initial_d
        # 后续值 → 标准递推
        d_series = k_copy.ewm(alpha=alpha_d, adjust=False, ignore_na=False).mean()
        
        return d_series
        
    except Exception as e:
        # 捕获异常并附加诊断信息（遵循 MODULE.md 异常处理规范）
        raise RuntimeError(
            f"D 值计算异常（groupby transform 内部）\n"
            f"原始异常: {type(e).__name__}: {e}\n"
            f"诊断信息:\n"
            f"  - Series 长度: {len(k_series)}\n"
            f"  - 第一个有效位置: {k_series.first_valid_index()}\n"
            f"  - 参数: alpha_d={alpha_d}, initial_d={initial_d}\n"
            f"建议: 检查对应股票的 K 值数据是否存在异常"
        ) from e


# ============================================================
# KDJ_J 因子计算函数（实际被调用的主路径）
# ============================================================

def calculate_kdj_j_factor(
    factor_df: pd.DataFrame,
    n: int = 9,
    m1: int = 3,
    m2: int = 3
) -> Tuple[pd.DataFrame, dict]:
    """
    计算所有股票的 KDJ_J 因子（向量化版本）
    
    Args:
        factor_df: 包含 date, asset, close, high, low 的 DataFrame
        n: RSV 计算周期（默认 9）
        m1: K值平滑周期（默认 3）
        m2: D值平滑周期（默认 3）
        
    Returns:
        (处理后的 factor_df, 统计信息)
    """
    print(f"\n[因子计算] KDJ_J 因子 (N={n}, M1={m1}, M2={m2})")
    
    stats = {
        'total_records': len(factor_df),
        'valid_records': 0,
        'missing_price_count': 0,
        'n': n,
        'm1': m1,
        'm2': m2
    }
    
    if factor_df.empty:
        print("  ✗ 数据为空")
        return factor_df, stats
    
    # 检查必要列
    required_cols = ['date', 'asset', 'close', 'high', 'low']
    missing_cols = [c for c in required_cols if c not in factor_df.columns]
    if missing_cols:
        print(f"  ✗ 缺少必要列: {missing_cols}")
        return factor_df, stats
    
    # 统计缺失数据
    missing_price_mask = (
        factor_df['close'].isna() | 
        factor_df['high'].isna() | 
        factor_df['low'].isna()
    )
    stats['missing_price_count'] = int(missing_price_mask.sum())
    
    print(f"  总记录数: {stats['total_records']:,}")
    print(f"  价格缺失数: {stats['missing_price_count']:,}")
    
    # 确保按日期排序
    factor_df = factor_df.sort_values(['asset', 'date']).copy()
    
    # 向量化计算 RSV
    # 遵循标准 KDJ 定义：满 N 期才开始计算，前 N-1 期为 NaN
    # min_periods=n 确保使用完整窗口数据，避免前 N-1 天数据失真
    # 原因：min_periods=1 时，第1天只有1天数据，RSV 可能是 0 或 100（极端值）
    print("  [Step 1] 计算 RSV...")
    factor_df['rolling_high'] = factor_df.groupby('asset')['high'].transform(
        lambda x: x.rolling(window=n, min_periods=n).max()
    )
    factor_df['rolling_low'] = factor_df.groupby('asset')['low'].transform(
        lambda x: x.rolling(window=n, min_periods=n).min()
    )
    
    # 使用精度容差判断浮点数除零（遵循 PROJECT.md 浮点数等值比较规范）
    # 原因：diff 是浮点数运算结果，直接 == 0 比较会漏判极小值（如 1e-15）
    # 使用模块级常量 EPSILON，便于统一管理和复用
    diff = factor_df['rolling_high'] - factor_df['rolling_low']
    factor_df['rsv'] = np.where(
        np.abs(diff) < EPSILON,  # 精度容差判断（替代 diff == 0）
        50.0, 
        (factor_df['close'] - factor_df['rolling_low']) / diff * 100
    )
    
    # RSV 值域检查（遵循 MODULE.md 因子计算规范）
    # 理论上 RSV 应在 [0, 100]，但浮点运算可能产生微小偏差
    # NaN 传播正确（前 N-1 期为 NaN），此处只检查非 NaN 值
    rsv_valid = factor_df['rsv'].dropna()
    if len(rsv_valid) > 0:
        rsv_min = rsv_valid.min()
        rsv_max = rsv_valid.max()
        rsv_out_of_range = int(((rsv_valid < 0) | (rsv_valid > 100)).sum())
        
        # 值域统计日志（便于诊断）
        print(f"  RSV 值域统计:")
        print(f"    最小值: {rsv_min:.4f}")
        print(f"    最大值: {rsv_max:.4f}")
        
        # 异常值警告（超出理论范围）
        if rsv_out_of_range > 0:
            print(f"    ⚠ 超出 [0, 100] 范围: {rsv_out_of_range} 个 ({rsv_out_of_range/len(rsv_valid)*100:.2f}%)")
            print(f"    原因分析: 可能是 diff 极小（接近 EPSILON）导致的数值放大")
            print(f"    建议: 若异常值比例 > 1%，检查 EPSILON 阈值是否合适")
        
        # 调试断言（仅在开发期启用，生产环境可注释）
        # assert rsv_min >= -EPSILON * 100, f"RSV 下界溢出: {rsv_min}"
        # assert rsv_max <= 100 + EPSILON * 100, f"RSV 上界溢出: {rsv_max}"
    
    factor_df.drop(columns=['rolling_high', 'rolling_low'], inplace=True)
    
    # 计算 K（批量向量化）
    # ewm(adjust=False) 的第一个输出 = 第一个输入，即 K[0] = RSV[0]
    # 但标准 KDJ 定义：K[0] = initial_k = 50
    # 解决方案：在 ewm 前预处理每只股票的第一个 RSV 值
    # 遵循 MODULE.md KDJ 初始值规范
    
    print("  [Step 2] 计算 K...")
    # ewm(alpha) 公式：y[t] = alpha * x[t] + (1-alpha) * y[t-1]
    # KDJ 公式：K[t] = (1/m1) * K[t-1] + (1-1/m1) * RSV[t]
    # 要匹配，需要 alpha = 1 - 1/m1 = (m1-1)/m1
    # 注意：之前使用 alpha = 1/m1 是错误的，导致权重颠倒
    alpha_k = (m1 - 1) / m1
    initial_k = 50.0  # K 初始值
    
    # 使用模块级私有函数，显式传参（避免闭包耦合）
    # lambda 包装以适配 groupby transform 接口
    factor_df['k'] = factor_df.groupby('asset')['rsv'].transform(
        lambda rsv: _calculate_k_with_initial(rsv, alpha_k, initial_k)
    )
    
    # 计算 D（批量向量化）
    # ewm(adjust=False) 的第一个输出 = 第一个输入，即 D[0] = K[0]
    # 但标准 KDJ 定义：D[0] = initial_d = 50
    # 解决方案：在 ewm 前预处理每只股票的第一个 K 值
    # 遵循 MODULE.md KDJ 初始值规范
    
    print("  [Step 3] 计算 D...")
    # ewm(alpha) 公式：y[t] = alpha * x[t] + (1-alpha) * y[t-1]
    # KDJ 公式：D[t] = (1/m2) * D[t-1] + (1-1/m2) * K[t]
    # 要匹配，需要 alpha = 1 - 1/m2 = (m2-1)/m2
    alpha_d = (m2 - 1) / m2
    initial_d = 50.0  # D 初始值
    
    # 使用模块级私有函数，显式传参（避免闭包耦合）
    # lambda 包装以适配 groupby transform 接口
    factor_df['d'] = factor_df.groupby('asset')['k'].transform(
        lambda k: _calculate_d_with_initial(k, alpha_d, initial_d)
    )
    
    # 计算 J = 3K - 2D
    print("  [Step 4] 计算 J...")
    factor_df['kdj_j'] = 3 * factor_df['k'] - 2 * factor_df['d']
    
    stats['valid_records'] = int(factor_df['kdj_j'].notna().sum())
    print(f"\n  有效记录数: {stats['valid_records']:,}")
    
    # 输出因子统计
    valid_values = factor_df['kdj_j'].dropna()
    if len(valid_values) > 0:
        print(f"\n  因子统计:")
        print(f"    均值:   {valid_values.mean():.2f}")
        print(f"    标准差: {valid_values.std():.2f}")
        print(f"    最小值: {valid_values.min():.2f}")
        print(f"    最大值: {valid_values.max():.2f}")
        
        overbought = int((valid_values > 100).sum())
        oversold = int((valid_values < 0).sum())
        print(f"\n  超买(J>100): {overbought:,} ({overbought/len(valid_values)*100:.2f}%)")
        print(f"  超卖(J<0):   {oversold:,} ({oversold/len(valid_values)*100:.2f}%)")
    
    return factor_df, stats


def load_data_from_cache(
    n: int = 9,
    m1: int = 3,
    m2: int = 3
) -> Tuple[pd.DataFrame, pd.DataFrame, dict]:
    """
    从缓存加载因子数据和收益数据，并计算 KDJ_J 因子
    
    参数:
        n: RSV 计算周期
        m1: K值平滑周期
        m2: D值平滑周期
        
    返回:
        (factor_df, return_df, raw_metadata)
        - factor_df: 过滤后的因子数据 DataFrame（含 KDJ_J）
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
    # 使用 errors='coerce' 处理异常格式，转换后检查 NaT 数量
    
    if 'date' in factor_df.columns:
        date_series = pd.to_datetime(factor_df['date'], errors='coerce')
        nat_count = date_series.isna().sum()
        if nat_count > 0:
            # 获取无效日期样本（前 5 个）
            invalid_samples = factor_df['date'][date_series.isna()].iloc[:5].tolist()
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
            invalid_samples = return_df['date'][date_series.isna()].iloc[:5].tolist()
            raise ValueError(
                f"收益数据中存在 {nat_count} 个无效日期格式\n"
                f"无效日期示例: {invalid_samples}\n"
                f"请检查缓存数据源是否包含脏数据"
            )
        return_df['date'] = date_series.dt.strftime('%Y-%m-%d')
    
    # 选择必要的列（KDJ_J 需要 close, high, low）
    # 输入验证（遵循 PROJECT.md 输入验证规范）
    required_cols = ['date', 'asset', 'close', 'high', 'low']
    missing_cols = [c for c in required_cols if c not in factor_df.columns]
    if missing_cols:
        available_cols = sorted(factor_df.columns.tolist())
        raise KeyError(
            f"因子数据缺少必需列: {missing_cols}\n"
            f"可用列: {available_cols}"
        )
    factor_df = factor_df[required_cols].copy()
    
    # 在 dropna 之前，计算原始数据范围（遵循 PROJECT.md 输出字段语义规范）
    raw_period_start = str(factor_df['date'].min())
    raw_period_end = str(factor_df['date'].max())
    raw_total_days = factor_df['date'].nunique()
    # 计算原始数据的平均每日股票数（口径与 total_days 一致）
    raw_avg_stocks_per_day = int(factor_df.groupby('date').size().mean())
    
    print(f"  - 原始数据范围: {raw_period_start} ~ {raw_period_end}, {raw_total_days} 个交易日")
    print(f"  - 原始平均每日股票数: {raw_avg_stocks_per_day}")
    
    # 过滤缺失值
    factor_df = factor_df.dropna(subset=['close', 'high', 'low']).reset_index(drop=True)
    
    # 重命名收益列
    # 输入验证（遵循 PROJECT.md 输入验证规范）
    if 'forward_return_1d' not in return_df.columns:
        available_cols = sorted(return_df.columns.tolist())
        raise KeyError(
            f"收益列 'forward_return_1d' 不存在于缓存数据中\n"
            f"可用列: {available_cols}"
        )
    return_df = return_df[['date', 'asset', 'forward_return_1d']].copy()
    return_df = return_df.rename(columns={'forward_return_1d': 'forward_return'})
    
    return_df = return_df.dropna(subset=['forward_return']).reset_index(drop=True)
    
    print(f"  - 过滤缺失值后: 因子 {len(factor_df)} 行, 收益 {len(return_df)} 行")
    
    # 计算 KDJ_J 因子
    print("\n[因子计算] 计算 KDJ_J...")
    factor_df, factor_stats = calculate_kdj_j_factor(factor_df, n=n, m1=m1, m2=m2)
    
    # 选择输出列
    factor_df = factor_df[['date', 'asset', 'kdj_j']].copy()
    
    # 返回过滤后的数据 + 原始数据元信息
    return factor_df, return_df, {
        'period_start': raw_period_start,
        'period_end': raw_period_end,
        'total_days': raw_total_days,
        'avg_stocks_per_day': raw_avg_stocks_per_day  # 口径与 total_days 一致
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
        factor_col='kdj_j',
        return_col='forward_return',
        date_col='date',
        asset_col='asset',
        min_stocks=min_stocks  # 使用函数参数，遵循 PROJECT.md 参数传递规范
    )
    
    ic_series = result['ic_series']
    
    # 防御性校验：确保 result 包含必需字段
    # 遵循 PROJECT.md 函数返回值契约规范
    # 注意：p_value 在 ic_metrics 中直接访问，必须包含在校验列表中
    required_fields = [
        'ic_series', 'ic_mean', 'ic_std', 'icir', 'p_value',
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
    
    # 获取日期范围（遵循 PROJECT.md period 数据源规范）
    # 使用 raw_metadata 中的原始数据范围，而非过滤后的 factor_df
    if raw_metadata is None:
        raw_metadata = {}
    period_start = raw_metadata.get('period_start', str(factor_df['date'].min()))
    period_end = raw_metadata.get('period_end', str(factor_df['date'].max()))
    total_days = raw_metadata.get('total_days', factor_df['date'].nunique())
    
    # 转换为 JSON 友好格式
    dates = [str(d) for d in ic_series.index]
    
    # ic_series.values 不含 NaN 的原因（隐式行为说明）：
    # - ic_series 由 ic_calculator.py 构建，只有 ic_value is not None 的日期被添加
    # - 不满足 min_stocks 的日期不会被添加到 ic_series（而非添加 NaN）
    # - 因此 ic_series.values 中的 v 都是有效的 numpy.float64 值
    # - round(v, 6) 对有效值正常工作，无需 pd.isna(v) 检查
    # 防御性说明：若未来 ic_series 逻辑变化导致含 NaN，需改为：
    #   [round(v, 6) if not pd.isna(v) else None for v in ic_series.values]
    ic_values = [round(v, 6) for v in ic_series.values]
    
    # 边界条件检查：dates 为空时提前抛出异常（遵循 MODULE.md 边界条件规范）
    # 原因：若所有交易日股票数均不足 min_stocks，ic_series 为空，dates 也为空
    # 问题：返回"半空"结果字典难以诊断根本原因，valid_range.start/end 为 None
    # 解决：在生成结果前检查，抛出有意义的异常便于诊断
    if len(dates) == 0:
        # 诊断信息必须使用原始数据统计（遵循 MODULE.md 异常处理规范）
        # 原因：factor_df/return_df 是过滤后的数据，若 IC 为空可能本身已很小或为空
        # raw_metadata 包含原始数据统计（period_start/total_days/avg_stocks_per_day）
        
        # 防御性访问：避免 KeyError（遵循 MODULE.md 防御性异常处理规范）
        # 场景：factor_df/return_df 可能没有 'asset' 列（极端情况）
        # 处理：先检查列存在，不存在时 nunique=0
        factor_assets = factor_df['asset'].nunique() if 'asset' in factor_df.columns else 0
        return_assets = return_df['asset'].nunique() if 'asset' in return_df.columns else 0
        
        raise RuntimeError(
            f"IC 计算结果为空：所有交易日股票数均不足 min_stocks={min_stocks}\n"
            f"原始数据统计（来自 raw_metadata）:\n"
            f"  - 原始日期范围: {period_start} ~ {period_end}\n"
            f"  - 原始交易日数: {total_days}\n"
            f"  - 原始平均每日股票数: {raw_metadata.get('avg_stocks_per_day', 'N/A')}\n"
            f"过滤后数据统计（诊断用）:\n"
            f"  - 因子数据: {len(factor_df)} 行, {factor_assets} 只股票\n"
            f"  - 收益数据: {len(return_df)} 行, {return_assets} 只股票\n"
            f"建议: 降低 min_stocks 阈值或检查数据源股票覆盖率"
        )
    
    # 计算 20 日滚动均值（min_periods=10，至少需要10个有效值）
    rolling_mean = ic_series.rolling(window=20, min_periods=10).mean()
    
    # 遵循 PROJECT.md NaN 处理规范：在数据生成阶段将 NaN 转为 None
    # rolling 参数语义：window=20（窗口大小），min_periods=10（最小有效样本数）
    # 前 min_periods-1=9 个时间点不满足最小样本要求，返回 NaN
    # 第 min_periods=10 个时间点（index 9）起，窗口内至少有 10 个有效值
    # 注意：round(NaN, 6) 返回 Python float nan，而非 None
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
        'factor_name': 'kdj_j_1d',
        'calculation_date': datetime.now().strftime('%Y-%m-%d'),
        'period': {
            'start': period_start,
            'end': period_end
        },
        'ic_metrics': {
            # 字段去重化规范（遵循 MODULE.md 字段去重化规范）
            # - ic_metrics 只包含核心 IC 指标：ic_mean, ic_std, icir
            # - p_value, t_stat 等在 statistical_significance 中独立输出
            # - 避免字段重复出现导致数据结构冗余
            'ic_mean': round(result['ic_mean'], 6),
            'ic_std': round(result['ic_std'], 6),
            'icir': round(result['icir'], 4)
        },
        
        # 五维度判断（独立输出，遵循 PROJECT.md 规范）
        # 对齐 ic_rsi_1d.py 实现：直接传递完整 result 对象，而非手动拆分
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
        'summary': result['summary'],
        
        'sample_stats': {
            # 语义定义（遵循 PROJECT.md 输出字段语义规范）：
            # - total_days: 原始因子缓存覆盖的日期数（dropna 前的数据范围）
            # - valid_days: 实际计算出 IC 的天数（每交易日股票数 >= min_stocks）
            # - 差值含义: total_days - valid_days = 因股票不足或数据缺失跳过的交易日数
            'total_days': total_days,  # 使用 raw_metadata（dropna 前）
            'valid_days': len(dates),  # dates 来自 ic_series.index（有效IC日期）
            
            # 口径一致性规范（遵循 MODULE.md 统计口径规范）：
            # - raw_avg_stocks_per_day: 与 total_days 口径一致（原始数据范围）
            # - avg_stocks_per_day: 与 valid_days 口径一致（有效IC数据范围）
            'raw_avg_stocks_per_day': raw_metadata.get('avg_stocks_per_day', 0),
            'avg_stocks_per_day': int(factor_df.groupby('date').size().mean()),
            
            # 口径说明（明确差异，避免误导分析）
            'avg_stocks_period': {
                'raw_range': {
                    'start': period_start,
                    'end': period_end,
                    'description': 'raw_avg_stocks_per_day 统计范围（与 total_days 一致）'
                },
                'valid_range': {
                    'start': dates[0] if dates else None,
                    'end': dates[-1] if dates else None,
                    'description': 'avg_stocks_per_day 统计范围（与 valid_days 一致）'
                }
            }
        }
    }


def generate_kdj_j_ic_data(
    output_file: Path | str | None = None,
    force_full: bool = False,
    n: int = 9,
    m1: int = 3,
    m2: int = 3
) -> dict:
    """
    从缓存数据计算 KDJ_J IC
    
    参数:
        output_file: 输出文件路径（Path 或 str，内部统一转为 Path）
        force_full: 强制全量计算
        n: RSV 计算周期
        m1: K值平滑周期
        m2: D值平滑周期
    
    返回:
        IC 数据字典
    
    规范:
        使用缓存全部日期数据，不截断
    """
    # 统一转换为 Path 对象（遵循 PROJECT.md 参数类型约定）
    if output_file is None:
        output_file = get_ic_output_path('kdj_j_1d')
    else:
        output_file = Path(output_file)
    
    # 增量判断（除非强制全量）
    # 控制流语义（遵循 MODULE.md 控制流规范）：
    # - force_full=True → 直接执行全量计算
    # - force_full=False + mode='skip' + 成功读取 → 提前 return（退出函数）
    # - force_full=False + 其他情况（FileNotFoundError/incremental/full）→ 执行全量计算
    # 结论：只有 mode='skip' 且成功读取会提前退出，其他所有路径都执行全量计算
    
    if not force_full:
        mode, missing_dates, info = check_data_completeness('kdj_j_1d')
        
        if mode == 'skip':
            print("\n数据完备，无需更新")
            try:
                with open(output_file, 'r', encoding='utf-8') as f:
                    return json.load(f)  # 成功读取，提前退出
            except FileNotFoundError:
                # 可恢复错误：缓存文件不存在，降级全量计算
                print("  [诊断] 缓存文件不存在，执行全量计算")
                # 继续执行全量计算（无需标记，控制流自然到达）
            except json.JSONDecodeError as e:
                # 严重错误：缓存文件损坏，不静默降级
                raise RuntimeError(
                    f"缓存文件损坏，无法解析 JSON: {output_file}\n"
                    f"错误详情: {e}\n"
                    f"建议: 删除损坏的缓存文件后重新运行"
                ) from e
            except PermissionError as e:
                # 严重错误：权限问题，不静默降级
                raise RuntimeError(
                    f"缓存文件权限不足，无法读取: {output_file}\n"
                    f"错误详情: {e}"
                ) from e
            except Exception as e:
                # 未预期异常：抛出异常 + 详细诊断
                raise RuntimeError(
                    f"读取缓存失败（未预期异常）: {output_file}\n"
                    f"异常类型: {type(e).__name__}\n"
                    f"错误详情: {e}"
                ) from e
        
        elif mode == 'incremental':
            # 增量计算模式：只计算缺失日期的 IC（待实现）
            print(f"\n增量模式：需要计算 {len(missing_dates)} 个缺失日期")
            # 当前版本降级全量计算（增量待实现），继续执行全量计算逻辑
    
    # 全量计算逻辑
    print("=" * 60)
    print(f"KDJ_J_1D IC 计算器（缓存版） - 1日收益周期")
    print(f"参数: N={n}, M1={m1}, M2={m2}")
    print("=" * 60)
    
    # 从缓存加载数据并计算因子
    print("\n[1/3] 从缓存加载因子和收益数据...")
    try:
        factor_df, return_df, raw_metadata = load_data_from_cache(n=n, m1=m1, m2=m2)
        
        # 检查数据量（遵循 PROJECT.md 数据验证规范）
        if factor_df['asset'].nunique() < DEFAULT_MIN_STOCKS:
            raise ValueError(
                f"股票数量不足以计算有效的 IC\n"
                f"当前: {factor_df['asset'].nunique()} < {DEFAULT_MIN_STOCKS}"
            )
        
    except FileNotFoundError as e:
        # 基础设施错误：包装为 RuntimeError，添加缓存路径上下文
        # 原因：FileNotFoundError 原始信息不够详细，需要附加缓存路径
        # 使用 `from e` 保留异常链，便于调试
        raise RuntimeError(f"缓存文件不存在: {FACTOR_CACHE}") from e
    except KeyError as e:
        # 数据验证错误：裸 raise 保留原始类型
        # 原因：KeyError 表示数据缺少必需列，是可预期错误，原始类型更易诊断
        # 不包装，直接传播原始异常（遵循 PROJECT.md 异常类型保留规范）
        raise
    except ValueError as e:
        # 数据验证错误：裸 raise 保留原始类型
        # 原因：ValueError 表示数据格式错误（如无效日期），是可预期错误
        # 不包装，直接传播原始异常（遵循 PROJECT.md 异常类型保留规范）
        raise
    except Exception as e:
        # 未预期异常：包装为 RuntimeError，保留异常链
        # 原因：未预期异常类型多变，包装为 RuntimeError 统一处理
        # 使用 `from e` 保留异常链，确保原始异常信息不丢失
        raise RuntimeError(
            f"数据加载失败（未预期异常）\n"
            f"异常类型: {type(e).__name__}\n"
            f"错误详情: {e}"
        ) from e
    
    # 使用缓存全部日期（不截断）
    
    print(f"\n数据统计:")
    print(f"  - 原始日期范围: {raw_metadata['period_start']} ~ {raw_metadata['period_end']}")
    print(f"  - 原始交易日数: {raw_metadata['total_days']}")
    print(f"  - 过滤后交易日数: {factor_df['date'].nunique()}")
    print(f"  - 股票数量: {factor_df['asset'].nunique()}")
    
    # 计算 IC
    print("\n[2/3] 计算每日 IC...")
    ic_data = calculate_daily_ic_series(factor_df, return_df, raw_metadata=raw_metadata)
    print(f"  - IC 均值: {ic_data['ic_metrics']['ic_mean']:.4f}")
    print(f"  - ICIR: {ic_data['ic_metrics']['icir']:.2f}")
    print(f"  - 正比例: {ic_data['positive_ratio']:.1%}")
    t_stat = ic_data['statistical_significance']['t_stat']
    is_sig = ic_data['statistical_significance']['is_significant']
    sig_display = "显著" if is_sig else "不显著"
    print(f"  - t 统计量: {t_stat:.2f} ({sig_display})")
    
    # 保存数据
    print(f"\n[3/3] 保存数据到: {output_file}")
    output_file.parent.mkdir(parents=True, exist_ok=True)
    
    # 转换 numpy 类型
    ic_data = convert_to_native_types(ic_data)
    
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(ic_data, f, ensure_ascii=False, indent=2)
    
    print("\n" + "=" * 60)
    print(f"完成！共计算 {ic_data['sample_stats']['valid_days']} 天有效 IC 数据（原始数据 {ic_data['sample_stats']['total_days']} 天）")
    print("=" * 60)
    
    return ic_data


if __name__ == '__main__':
    # 计算缓存全部日期的 IC 数据
    generate_kdj_j_ic_data(n=9, m1=3, m2=3)