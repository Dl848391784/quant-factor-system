#!/usr/bin/env python3
"""
KDJ_J 因子 IC 计算器 - 使用公共模块主入口

遵循 PROJECT.md 公共模块强制复用规范：
- 主流程使用 run_complex_factor_ic()（禁止手写三模式分支）
- 仅实现因子特有计算逻辑（KDJ 公式）

代码量：~120行（仅KDJ计算），而非 ~360行手写主流程。

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

# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent.parent))

import numpy as np
import pandas as pd

# 导入公共模块主入口（遵循 PROJECT.md 强制复用规范）
from factor_ic.common.factor_ic_runner import run_complex_factor_ic
from factor_ic.common.logger_config import get_logger

logger = get_logger(__name__)

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
# KDJ 计算函数（因子特有逻辑）
# ============================================================================

def _calculate_k_with_initial(
    rsv_series: pd.Series,
    alpha_k: float,
    initial_k: float
) -> pd.Series:
    """计算 K 值（正确处理 NaN 前缀版本）
    
    核心逻辑：
    1. RSV 前 N-1 期为 NaN（rolling window min_periods=n）
    2. ewm(ignore_na=True) 使 NaN 不参与计算，但输出中 NaN 位置被填充
    3. 在第一个有效 RSV **前**插入虚拟 initial_k，作为 K_{t-1} 初始条件
    4. 计算后恢复原始 NaN 位置
    
    EWM 递推公式：K[t] = alpha * RSV[t] + (1-alpha) * K[t-1]
    初始条件：K[t-1] = initial_k（第一期之前的虚拟 K 值）
    alpha = 1/m1（KDJ 标准参数）
    
    关键：initial_k 是 K_{t-1} 的初始值，不是 RSV 输入的覆盖值！
    """
    if len(rsv_series) == 0:
        return rsv_series
    
    # 找到第一个有效 RSV 的位置
    first_valid_idx = rsv_series.first_valid_index()
    
    if first_valid_idx is None:
        return rsv_series
    
    # 正确实现：在第一个有效 RSV **前**插入虚拟 initial_k
    # 使用 pd.concat 拼接（用临时整数索引，避免时间索引减法问题）
    rsv_with_initial = pd.concat([
        pd.Series([initial_k], index=[-1]),  # 虚拟初始值（临时索引）
        rsv_series
    ], ignore_index=True)  # 重置索引为整数位置
    
    # 计算 ewm 递推（使用 ignore_na=True，让初始值正确传播）
    k_with_initial = rsv_with_initial.ewm(alpha=alpha_k, adjust=False, ignore_na=True).mean()
    
    # 移除虚拟初始值，恢复原始索引
    k_series = k_with_initial.iloc[1:]
    k_series.index = rsv_series.index
    
    # 恢复原始 NaN 位置（ewm 会填充 NaN 位置为初始值）
    k_series = k_series.where(rsv_series.notna(), float('nan'))
    
    return k_series


def _calculate_d_with_initial(
    k_series: pd.Series,
    alpha_d: float,
    initial_d: float
) -> pd.Series:
    """计算 D 值（正确处理 NaN 前缀版本）
    
    核心逻辑：
    1. K 前 N-1 期为 NaN（与 RSV 前缀一致）
    2. ewm(ignore_na=True) 使 NaN 不参与计算，但输出中 NaN 位置被填充
    3. 在第一个有效 K **前**插入虚拟 initial_d，作为 D_{t-1} 初始条件
    4. 计算后恢复原始 NaN 位置
    
    EWM 递推公式：D[t] = alpha * K[t] + (1-alpha) * D[t-1]
    初始条件：D[t-1] = initial_d（第一期之前的虚拟 D 值）
    alpha = 1/m2（KDJ 标准参数）
    
    关键：initial_d 是 D_{t-1} 的初始值，不是 K 输入的覆盖值！
    """
    if len(k_series) == 0:
        return k_series
    
    # 找到第一个有效 K 的位置
    first_valid_idx = k_series.first_valid_index()
    
    if first_valid_idx is None:
        return k_series
    
    # 正确实现：在第一个有效 K **前**插入虚拟 initial_d
    # 使用 pd.concat 拼接（用临时整数索引，避免时间索引减法问题）
    k_with_initial = pd.concat([
        pd.Series([initial_d], index=[-1]),  # 虚拟初始值（临时索引）
        k_series
    ], ignore_index=True)  # 重置索引为整数位置
    
    # 计算 ewm 递推（使用 ignore_na=True，让初始值正确传播）
    d_with_initial = k_with_initial.ewm(alpha=alpha_d, adjust=False, ignore_na=True).mean()
    
    # 移除虚拟初始值，恢复原始索引
    d_series = d_with_initial.iloc[1:]
    d_series.index = k_series.index
    
    # 恢复原始 NaN 位置（ewm 会填充 NaN 位置为初始值）
    d_series = d_series.where(k_series.notna(), float('nan'))
    
    return d_series


def calculate_kdj_j(
    factor_df: pd.DataFrame,
    n: int = DEFAULT_N,
    m1: int = DEFAULT_M1,
    m2: int = DEFAULT_M2
) -> pd.DataFrame:
    """
    计算 KDJ_J 因子（因子特有逻辑）
    
    参数:
        factor_df: 包含 close, high, low 列的 DataFrame
        n: RSV 计算周期
        m1: K值平滑周期
        m2: D值平滑周期
    
    返回:
        添加了 kdj_j 列的 DataFrame
    
    规范:
        - 函数入口必须先 .copy()，避免修改原始数据（MODULE.md DataFrame参数副本规范）
        - 使用 pandas 语义，避免 np.where 混用
    """
    # 函数入口必须先 copy，避免副作用
    factor_df = factor_df.copy()
    
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
    
    # 避免除零：denom = high_max - low_min 理论上恒 >= 0
    denom = high_max - low_min
    
    # 先判断异常位置（过窄带宽，无法有效计算 RSV）
    # denom 理论上恒 >= 0，无需 .abs()
    narrow_range_mask = denom < EPSILON
    
    # 先排除异常再计算（遵循 MODULE.md "因子计算异常排除时机规范"）
    # 异常位置用 EPSILON 防止除零崩溃，但计算结果无意义会被后续覆盖
    safe_denom = denom.where(~narrow_range_mask, EPSILON)
    rsv = (factor_df['close'] - low_min) / safe_denom * 100
    
    # 异常位置设为 50（中性值，KDJ 标准处理）
    rsv = rsv.where(~narrow_range_mask, 50.0)
    
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
# CLI 入口
# ============================================================================

def main():
    """CLI 主入口"""
    import argparse
    
    parser = argparse.ArgumentParser(description='KDJ_J IC 计算器')
    parser.add_argument('--force-full', action='store_true', help='强制全量计算')
    parser.add_argument('--n', type=int, default=DEFAULT_N, help='RSV 计算周期')
    parser.add_argument('--m1', type=int, default=DEFAULT_M1, help='K值平滑周期')
    parser.add_argument('--m2', type=int, default=DEFAULT_M2, help='D值平滑周期')
    parser.add_argument('--min-stocks', type=int, default=DEFAULT_MIN_STOCKS, help='最小股票数')
    
    args = parser.parse_args()
    
    # 使用公共模块主入口（遵循 PROJECT.md 强制复用规范）
    result = run_complex_factor_ic(
        factor_name='kdj_j',
        factor_col='kdj_j',
        factor_cols=['close', 'high', 'low'],
        custom_factor_calculation=calculate_kdj_j,
        custom_factor_calculation_params={'n': args.n, 'm1': args.m1, 'm2': args.m2},
        min_stocks=args.min_stocks,
        force_full=args.force_full,
        _logger=logger
    )
    
    # 使用 .get() 防御性访问结果（遵循 MODULE.md 日志访问规范）
    ic_metrics = result.get('ic_metrics', {})
    logger.info("=" * 60)
    logger.info("结果摘要:")
    logger.info(f"因子名称: {result.get('factor_name', 'unknown')}")
    logger.info(f"更新模式: {result.get('update_mode', 'unknown')}")
    logger.info(f"IC 均值: {ic_metrics.get('ic_mean', 0):.4f}")
    logger.info(f"ICIR: {ic_metrics.get('icir', 0):.2f}")
    logger.info("=" * 60)
    
    return result


if __name__ == '__main__':
    try:
        main()
    except RuntimeError as e:
        logger.error(f"计算失败: {e}")
        sys.exit(1)
    except Exception as e:
        logger.error(f"未预期的错误: {e}")
        sys.exit(1)