#!/usr/bin/env python3
"""
KDJ_J 因子 IC 计算器 - 使用公共模块主入口

遵循 PROJECT.md 公共模块强制复用规范：
- 主流程使用 run_complex_factor_ic()（禁止手写三模式分支）
- 因子计算逻辑复用 data_fetchers.factor_calculator（遵循 MODULE.md 约束 #3）

代码量：~60行（仅 CLI 入口），因子计算逻辑已统一到 factor_calculator.py。

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
重构日期: 2026-05-27（因子计算逻辑迁移到 factor_calculator.py）
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

# 重构后：从 factor_calculator 导入因子计算函数（遵循 MODULE.md 约束 #3）
from data_fetchers.factor_calculator import (
    calculate_kdj_j,
    DEFAULT_KDJ_N as DEFAULT_N,   # RSV 计算周期
    DEFAULT_KDJ_M1 as DEFAULT_M1, # K值平滑周期
    DEFAULT_KDJ_M2 as DEFAULT_M2, # D值平滑周期
)

logger = get_logger(__name__)

# ============================================================================
# 参数统一管理（部分从 factor_calculator 导入）
# ============================================================================
DEFAULT_MIN_STOCKS = 10


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
    
    # 调用前日志
    logger.info(f"启动KDJ_J因子IC计算: n={args.n}, m1={args.m1}, m2={args.m2}, min_stocks={args.min_stocks}, force_full={args.force_full}")
    
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
    
    # 调用完成日志
    logger.info("KDJ_J因子IC计算完成")
    
    # 使用 .get() 防御性访问结果
    ic_metrics = result.get('ic_metrics', {})
    
    # 完整指标输出
    logger.info("=" * 60 + " 结果摘要 " + "=" * 60)
    logger.info(f"因子名称: {result.get('factor_name', 'unknown')}")
    logger.info(f"更新模式: {result.get('update_mode', 'unknown')}")
    logger.info(f"计算参数: n={args.n}, m1={args.m1}, m2={args.m2}")
    logger.info("--- IC指标 ---")
    logger.info(f"IC 均值: {ic_metrics.get('ic_mean', 0):.4f}")
    logger.info(f"IC 标准差: {ic_metrics.get('ic_std', 0):.4f}")
    logger.info(f"ICIR: {ic_metrics.get('icir', 0):.2f}")
    logger.info(f"IC > 0 占比: {ic_metrics.get('ic_positive_ratio', 0):.2%}")
    logger.info("--- 数据范围 ---")
    logger.info(f"日期范围: {result.get('date_range', 'unknown')}")
    logger.info(f"处理股票数: {result.get('stock_count', 'unknown')}")
    logger.info(f"IC计算次数: {ic_metrics.get('ic_count', 0)}")
    logger.info("=" * 128)
    
    return result


if __name__ == '__main__':
    try:
        main()
    except RuntimeError:
        logger.exception("KDJ_J因子IC计算失败")
        sys.exit(1)
    except Exception:
        logger.exception("未预期的错误")
        sys.exit(1)