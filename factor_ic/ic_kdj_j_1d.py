#!/usr/bin/env python3
"""
KDJ_J_1D IC 计算器（重构版） - 1日收益周期

使用公共模块实现数据加载和输出构建，保留 KDJ 计算逻辑。
代码量从 ~882行降至 ~200行（KDJ 计算保留）。

因子定义：
- RSV(N) = (Close_t - Low_N) / (High_N - Low_N) × 100
- K_t = K_{t-1} × (M1-1)/M1 + RSV_t × 1/M1
- D_t = D_{t-1} × (M2-1)/M2 + K_t × 1/M2
- J_t = 3 × K_t - 2 × D_t

参数：
- N = 9（RSV 计算周期）
- M1 = 3（K值平滑周期）
- M2 = 3（D值平滑周期）

作者: 云瑶
重构日期: 2026-05-22
原版作者: 云舟
原版日期: 2026-04-07
"""

import sys
from pathlib import Path
import json

# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent.parent))

import pandas as pd
import numpy as np

# 导入日志
from factor_ic.common.logger_config import get_logger
logger = get_logger(__name__)

# 导入公共模块
from factor_ic.common import (
    load_factor_return_data,
    calculate_ic_with_direction_verification,
    build_ic_result,
    incremental_update_ic,
    should_use_incremental
)
from factor_ic.common.data_completeness import get_ic_output_path, check_data_completeness

# ============================================================================
# 参数统一管理
# ============================================================================
DEFAULT_MIN_STOCKS = 10
EPSILON = 1e-10

# KDJ 默认参数
DEFAULT_N = 9      # RSV 计算周期
DEFAULT_M1 = 3     # K值平滑周期
DEFAULT_M2 = 3     # D值平滑周期


# ============================================================================
# KDJ 计算函数（保留原版逻辑）
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
    KDJ 公式：K[t] = (1/m1) * RSV[t] + (m1-1)/m1 * K[t-1]
    要匹配，alpha = 1/m1
    """
    if len(rsv_series) == 0:
        return rsv_series
    
    # 复制 Series，避免修改原始数据
    rsv_copy = rsv_series.copy()
    
    # 找到第一个有效 RSV 的位置
    first_valid_idx = rsv_series.first_valid_index()
    
    if first_valid_idx is None:
        return rsv_series
    
    # 预处理：将第一个有效 RSV 值设为 initial_k
    rsv_copy[first_valid_idx] = initial_k
    
    # 计算 ewm 递推
    k_series = rsv_copy.ewm(alpha=alpha_k, adjust=False, ignore_na=False).mean()
    
    return k_series


def _calculate_d_with_initial(
    k_series: pd.Series,
    alpha_d: float,
    initial_d: float
) -> pd.Series:
    """计算 D 值（正确处理 NaN 前缀版本）"""
    if len(k_series) == 0:
        return k_series
    
    k_copy = k_series.copy()
    first_valid_idx = k_series.first_valid_index()
    
    if first_valid_idx is None:
        return k_series
    
    k_copy[first_valid_idx] = initial_d
    d_series = k_copy.ewm(alpha=alpha_d, adjust=False, ignore_na=False).mean()
    
    return d_series


def calculate_kdj_j(
    factor_df: pd.DataFrame,
    n: int = DEFAULT_N,
    m1: int = DEFAULT_M1,
    m2: int = DEFAULT_M2
) -> pd.DataFrame:
    """
    计算 KDJ_J 因子
    
    参数:
        factor_df: 包含 close, high, low 列的 DataFrame
        n: RSV 计算周期
        m1: K值平滑周期
        m2: D值平滑周期
    
    返回:
        添加了 kdj_j 列的 DataFrame
    """
    # ewm alpha 参数：alpha = 1/m（KDJ 标准公式）
    alpha_k = 1 / m1
    alpha_d = 1 / m2
    
    # 计算 RSV
    low_min = factor_df.groupby('asset')['low'].transform(
        lambda x: x.rolling(n, min_periods=n).min()
    )
    high_max = factor_df.groupby('asset')['high'].transform(
        lambda x: x.rolling(n, min_periods=n).max()
    )
    
    # 避免除零（使用 EPSILON）
    denom = high_max - low_min
    rsv = np.where(
        np.abs(denom) < EPSILON,
        50.0,  # 价格无波动时，RSV 设为 50
        (factor_df['close'] - low_min) / denom * 100
    )
    factor_df['rsv'] = rsv
    
    # 计算 K 和 D（按股票分组）
    factor_df['k'] = factor_df.groupby('asset')['rsv'].transform(
        lambda x: _calculate_k_with_initial(x, alpha_k, 50.0)
    )
    factor_df['d'] = factor_df.groupby('asset')['k'].transform(
        lambda x: _calculate_d_with_initial(x, alpha_d, 50.0)
    )
    
    # 计算 J
    factor_df['kdj_j'] = 3 * factor_df['k'] - 2 * factor_df['d']
    
    return factor_df


# ============================================================================
# 主函数
# ============================================================================

def generate_kdj_j_ic_data(
    output_file: Path | str | None = None,
    force_full: bool = False,
    n: int = DEFAULT_N,
    m1: int = DEFAULT_M1,
    m2: int = DEFAULT_M2,
    min_stocks: int = DEFAULT_MIN_STOCKS
) -> dict:
    """
    从缓存数据计算 KDJ_J IC
    
    参数:
        output_file: 输出文件路径
        force_full: 强制全量计算
        n: RSV 计算周期
        m1: K值平滑周期
        m2: D值平滑周期
        min_stocks: 最小股票数阈值
    
    返回:
        IC 数据字典
    """
    # 统一转换为 Path 对象
    if output_file is None:
        output_file = get_ic_output_path('kdj_j_1d')
    else:
        output_file = Path(output_file)
    
    # 增量判断（除非强制全量）
    if not force_full:
        mode, missing_dates, info = check_data_completeness('kdj_j_1d')
        
        if mode == 'skip':
            logger.info("数据完备，无需更新")
            try:
                with open(output_file, 'r', encoding='utf-8') as f:
                    cached_data = json.load(f)
                    cached_data['update_mode'] = 'skip'
                    return cached_data
            except FileNotFoundError:
                logger.info("[诊断] 缓存文件不存在，执行全量计算")
            except json.JSONDecodeError as e:
                raise RuntimeError(f"缓存文件损坏: {output_file}\n{e}") from e
    
    # 全量计算逻辑
    logger.info("=" * 60)
    logger.info(f"KDJ_J_1D IC 计算器（重构版） - 1日收益周期")
    logger.info(f"参数: N={n}, M1={m1}, M2={m2}")
    logger.info("=" * 60)
    
    # ========== Step 1: 加载数据 ==========
    logger.info("[1/3] 从缓存加载因子和收益数据...")
    try:
        # 加载原始列（close, high, low）
        factor_df, return_df, raw_metadata = load_factor_return_data(
            factor_cols=['close', 'high', 'low'],
            logger=logger
        )
        logger.info("✓ 加载成功")
        logger.info(f"原始日期范围: {raw_metadata['period_start']} ~ {raw_metadata['period_end']}")
        
    except FileNotFoundError as e:
        raise RuntimeError(f"缓存文件不存在: {e}") from e
    
    # ========== Step 2: 计算 KDJ_J ==========
    logger.info("[2/3] 计算 KDJ_J 因子...")
    factor_df = calculate_kdj_j(factor_df, n=n, m1=m1, m2=m2)
    logger.info("✓ KDJ_J 计算完成")
    
    # ========== Step 3: 计算 IC ==========
    logger.info("[3/3] 计算 IC...")
    ic_result = calculate_ic_with_direction_verification(
        factor_df=factor_df,
        return_df=return_df,
        factor_col='kdj_j',
return_col='forward_return_1d',
        min_stocks=min_stocks,
        logger=logger
    )
    
    logger.info(f"IC 均值: {ic_result['ic_mean']:.4f}")
    logger.info(f"ICIR: {ic_result['icir']:.2f}")
    logger.info(f"正比例: {ic_result['positive_ratio']:.1%}")
    
    # ========== Step 4: 构建输出 ==========
    result = build_ic_result(
        ic_result=ic_result,
        raw_metadata=raw_metadata,
        factor_name='kdj_j_1d',
        data_source='cache/factor_data/factor_data.json.gz',
        factor_col='kdj_j'
    )
    
    # 添加 KDJ 参数信息
    result['params'] = {
        'n': n,
        'm1': m1,
        'm2': m2,
        'factor_col': 'kdj_j'
    }
    
    # 保存结果
    logger.info(f"保存数据到: {output_file}")
    output_file.parent.mkdir(parents=True, exist_ok=True)
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    
    logger.info("=" * 60)
    logger.info(f"完成！共计算 {result['sample_stats']['valid_days']} 天有效 IC 数据")
    logger.info("=" * 60)
    
    return result


if __name__ == '__main__':
    import argparse
    
    parser = argparse.ArgumentParser(description='KDJ_J_1D IC 计算器（重构版）')
    parser.add_argument('--force-full', action='store_true', help='强制全量计算')
    parser.add_argument('--output', type=str, help='输出文件路径')
    parser.add_argument('--n', type=int, default=DEFAULT_N, help='RSV 计算周期')
    parser.add_argument('--m1', type=int, default=DEFAULT_M1, help='K值平滑周期')
    parser.add_argument('--m2', type=int, default=DEFAULT_M2, help='D值平滑周期')
    
    args = parser.parse_args()
    
    result = generate_kdj_j_ic_data(
        output_file=args.output,
        force_full=args.force_full,
        n=args.n,
        m1=args.m1,
        m2=args.m2
    )
    
    logger.info("结果摘要:")
    logger.info(f"因子名称: {result['factor_name']}")
    logger.info(f"IC 均值: {result['ic_metrics']['ic_mean']:.4f}")
    logger.info(f"ICIR: {result['ic_metrics']['icir']:.2f}")