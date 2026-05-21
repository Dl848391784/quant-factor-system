#!/usr/bin/env python3
"""
布林带%B 因子 IC 计算器 - 使用公共模块主入口

遵循 PROJECT.md 公共模块强制复用规范：
- 主流程使用 run_complex_factor_ic()（禁止手写三模式分支）
- 仅实现因子特有计算逻辑（布林带公式）

代码量：~80行（仅布林带计算），而非 ~300行手写主流程。

因子定义：
- Middle Band = SMA(Close, N)
- Upper Band = Middle Band + K × StdDev(Close, N)
- Lower Band = Middle Band - K × StdDev(Close, N)
- %B = (Close - Lower Band) / (Upper Band - Lower Band) × 100%

参数：
- N = 20（移动平均周期）
- K = 2.0（标差倍数）

作者: 云瑶
重构日期: 2026-05-22
原版作者: 云舟
原版日期: 2026-04-07
"""

import sys
from pathlib import Path

# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent.parent))

import pandas as pd

# 导入公共模块主入口（遵循 PROJECT.md 强制复用规范）
from factor_ic.common.factor_ic_runner import run_complex_factor_ic
from factor_ic.common.logger_config import get_logger

logger = get_logger(__name__)

# ============================================================================
# 参数统一管理
# ============================================================================
DEFAULT_MIN_STOCKS = 10
DEFAULT_N = 20     # 移动平均周期
DEFAULT_K = 2.0    # 标差倍数


# ============================================================================
# 布林带 %B 计算（因子特有逻辑）
# ============================================================================

def calculate_bollinger_pb(
    factor_df: pd.DataFrame,
    n: int = DEFAULT_N,
    k: float = DEFAULT_K
) -> pd.DataFrame:
    """
    计算布林带 %B 因子（因子特有逻辑）
    
    参数:
        factor_df: 包含 close 列的 DataFrame
        n: 移动平均周期
        k: 标差倍数
    
    返回:
        添加 bollinger_pb 列的 DataFrame
    
    注意:
        函数入口必须先 .copy()，避免修改原始数据
    """
    # 入口：创建副本避免副作用
    factor_df = factor_df.copy()
    
    # 计算移动平均和标准差
    middle = factor_df['close'].rolling(window=n).mean()
    std_dev = factor_df['close'].rolling(window=n).std()
    
    # 计算布林带
    upper = middle + k * std_dev
    lower = middle - k * std_dev
    
    # 计算 %B
    # 边界处理：布林带宽度理论上恒 >= 0（upper - lower = 2 * k * std_dev）
    band_width = upper - lower
    
    # 避免除零（使用 EPSILON）
    EPSILON = 1e-10
    
    # 检测异常：band_width < 0 说明 std 计算异常（数据质量问题）
    # 正确做法：标记异常为 NaN，而非静默修正
    abnormal_mask = band_width < 0  # 异常带宽（负值）
    narrow_band_mask = band_width < EPSILON  # 过窄带宽（接近零）
    
    # 正常情况：band_width >= EPSILON
    safe_band_width = band_width.clip(lower=EPSILON)
    bollinger_pb = (factor_df['close'] - lower) / safe_band_width
    
    # 异常处理：按优先级顺序处理，先低后高，高优先级覆盖低优先级
    # 优先级1（低）：band_width < EPSILON（过窄带宽）→ 0.5（中性值）
    # 优先级2（高）：band_width < 0（异常负值）→ NaN（覆盖上一步）
    bollinger_pb = bollinger_pb.where(~narrow_band_mask, 0.5)  # 过窄 → 0.5
    bollinger_pb = bollinger_pb.where(~abnormal_mask, None)    # 异常负值 → NaN（覆盖）
    
    # 异常统计日志
    abnormal_count = abnormal_mask.sum()
    if abnormal_count > 0:
        logger.warning(f"检测到 {abnormal_count} 个异常布林带宽度（负值），已标记为 NaN")
    
    factor_df['bollinger_pb'] = bollinger_pb
    
    return factor_df


# ============================================================================
# CLI 入口
# ============================================================================

def main():
    """CLI 主入口"""
    import argparse
    
    parser = argparse.ArgumentParser(description='布林带%B IC 计算器')
    parser.add_argument('--force-full', action='store_true', help='强制全量计算')
    parser.add_argument('--n', type=int, default=DEFAULT_N, help='移动平均周期')
    parser.add_argument('--k', type=float, default=DEFAULT_K, help='标差倍数')
    parser.add_argument('--min-stocks', type=int, default=DEFAULT_MIN_STOCKS, help='最小股票数')
    
    args = parser.parse_args()
    
    # 使用公共模块主入口（遵循 PROJECT.md 强制复用规范）
    result = run_complex_factor_ic(
        factor_name='bollinger_pb',
        factor_col='bollinger_pb',
        factor_cols=['close'],
        custom_factor_calculation=calculate_bollinger_pb,
        custom_factor_calculation_params={'n': args.n, 'k': args.k},
        min_stocks=args.min_stocks,
        force_full=args.force_full,
        _logger=logger
    )
    
    # 使用 .get() 防御性访问结果
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