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

def _calculate_ewm_with_initial(
    series: pd.Series,
    alpha: float,
    initial_value: float
) -> pd.Series:
    """计算 EWM 递推值（正确处理 NaN 前缀版本）
    
    公共函数：统一处理 K 值和 D 值的 EWM 递推计算
    
    核心逻辑：
    1. 输入序列前 N-1 期可能为 NaN（rolling window min_periods=n）
    2. ewm(ignore_na=True) 使 NaN 不参与计算，但输出中 NaN 位置被填充
    3. 在第一个有效值**前**插入虚拟 initial_value，作为递推初始条件
    4. 计算后恢复原始 NaN 位置
    
    EWM 递推公式：output[t] = alpha * input[t] + (1-alpha) * output[t-1]
    初始条件：output[t-1] = initial_value（第一期之前的虚拟值）
    
    参数:
        series: 输入序列（RSV 或 K）
        alpha: EWM alpha 参数
        initial_value: 初始值（KDJ 标准为 50.0）
    
    返回:
        EWM 递推结果序列
    """
    # 空序列直接返回
    if len(series) == 0:
        return series
    
    # 全 NaN 序列直接返回（语义准确，替代 first_valid_idx 检查）
    if series.isna().all():
        return series
    
    # 在第一个有效值**前**插入虚拟 initial_value
    # 使用 pd.concat 拼接（用临时整数索引，避免时间索引减法问题）
    series_with_initial = pd.concat([
        pd.Series([initial_value], index=[-1]),  # 虚拟初始值（临时索引）
        series
    ], ignore_index=True)  # 重置索引为整数位置
    
    # 计算 ewm 递推（使用 ignore_na=True，让初始值正确传播）
    result_with_initial = series_with_initial.ewm(alpha=alpha, adjust=False, ignore_na=True).mean()
    
    # 移除虚拟初始值，恢复原始索引
    result_series = result_with_initial.iloc[1:]
    result_series.index = series.index
    
    # 恢复原始 NaN 位置（ewm 会填充 NaN 位置为初始值）
    result_series = result_series.where(series.notna(), float('nan'))
    
    return result_series


def calculate_kdj_j(
    factor_df: pd.DataFrame,
    n: int = DEFAULT_N,
    m1: int = DEFAULT_M1,
    m2: int = DEFAULT_M2
) -> pd.DataFrame:
    """
    计算 KDJ_J 因子（因子特有逻辑）
    
    参数:
        factor_df: 包含 close, high, low, date, asset 列的 DataFrame
        n: RSV 计算周期
        m1: K值平滑周期
        m2: D值平滑周期
    
    返回:
        添加了 kdj_j 列的 DataFrame
    
    规范:
        - 函数入口必须先 .copy()，避免修改原始数据（MODULE.md DataFrame参数副本规范）
        - 使用局部变量存储中间结果，避免污染输出 DataFrame
        - 使用 pandas 语义，避免 np.where 混用
        - KDJ 是单股票时序指标，必须按 asset 分组后再做 rolling/ewm
    
    注意:
        rolling/ewm 计算前必须先按 asset+date 排序，确保：
        1. 每只股票的数据在正确时序上排列
        2. groupby.transform 不会混合不同股票的数据
    """
    # 函数入口必须先 copy，避免副作用
    factor_df = factor_df.copy()
    
    # 先按 asset+date 排序，确保 rolling/ewm 在正确时序上计算
    factor_df = factor_df.sort_values(['asset', 'date'])
    
    # ewm alpha 参数：alpha = 1/m（KDJ 标准公式）
    alpha_k = 1 / m1
    alpha_d = 1 / m2
    
    # 计算 RSV（使用局部变量，避免污染输出）
    # 按 asset 分组后做 rolling（KDJ 是单股票时序指标）
    low_min = factor_df.groupby('asset', group_keys=False)['low'].transform(
        lambda x: x.rolling(n, min_periods=n).min()
    )
    high_max = factor_df.groupby('asset', group_keys=False)['high'].transform(
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
    
    # 计算 K 和 D（使用局部变量，避免污染输出）
    # 使用临时列名计算，最后只保留 kdj_j
    # 由于数据已按 asset+date 排序，groupby.transform 不会混合不同股票的数据
    k = rsv.groupby(factor_df['asset']).transform(
        lambda x: _calculate_ewm_with_initial(x, alpha_k, 50.0)
    )
    
    d = k.groupby(factor_df['asset']).transform(
        lambda x: _calculate_ewm_with_initial(x, alpha_d, 50.0)
    )
    
    # 计算 J（只写入最终因子列）
    factor_df['kdj_j'] = 3 * k - 2 * d
    
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
        logger.exception("计算失败")  # 使用 .exception() 保留完整堆栈
        sys.exit(1)
    except Exception as e:
        logger.exception("未预期的错误")  # 使用 .exception() 保留完整堆栈
        sys.exit(1)