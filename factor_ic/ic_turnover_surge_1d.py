#!/usr/bin/env python3
"""
换手率突增因子 IC 计算器（重构版） - 1日收益周期

遵循 PROJECT.md 公共模块强制复用规范：
- 主流程使用 run_complex_factor_ic()（禁止手写三模式分支）
- 因子计算逻辑复用 data_fetchers.factor_calculator（遵循 MODULE.md 约束 #3）

代码量：~60行（仅 CLI 入口），因子计算逻辑已统一到 factor_calculator.py。

因子定义：
- 换手率突增 = 当日换手率 / 过去5日换手率均值
- 不再应用筛选条件（所有有效计算的因子值均保留）

作者: 云瑶
重构日期: 2026-05-27（因子计算逻辑迁移到 factor_calculator.py）
原版作者: 云舟
原版日期: 2026-05-08
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
    calculate_turnover_surge,
    DEFAULT_SURGE_WINDOW,
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
    
    parser = argparse.ArgumentParser(description='换手率突增 IC 计算器')
    parser.add_argument('--force-full', action='store_true', help='强制全量计算')
    parser.add_argument('--surge-window', type=int, default=DEFAULT_SURGE_WINDOW, help='换手率均值计算窗口')
    parser.add_argument('--min-stocks', type=int, default=DEFAULT_MIN_STOCKS, help='最小股票数')
    
    args = parser.parse_args()
    
    # 启动节点日志
    logger.info(f"换手率突增因子 IC 计算启动 [surge_window={args.surge_window}, min_stocks={args.min_stocks}, force_full={args.force_full}]")
    
    # 使用公共模块主入口（遵循 PROJECT.md 强制复用规范）
    result = run_complex_factor_ic(
        factor_name='turnover_surge',
        factor_col='turnover_surge',
        factor_cols=['close', 'turnover_rate'],
        custom_factor_calculation=calculate_turnover_surge,
        custom_factor_calculation_params={'surge_window': args.surge_window},
        min_stocks=args.min_stocks,
        force_full=args.force_full,
        _logger=logger
    )
    
    # 使用 .get() 防御性访问结果
    ic_metrics = result.get('ic_metrics', {})
    sample_stats = result.get('sample_stats', {})
    period = result.get('period', {})
    
    logger.info("=" * 60)
    logger.info("结果摘要")
    logger.info("=" * 60)
    logger.info(f"因子名称: {result.get('factor_name', 'unknown')}")
    logger.info(f"更新模式: {result.get('update_mode', 'unknown')}")
    logger.info(f"日期范围: {period.get('start', 'N/A')} ~ {period.get('end', 'N/A')}")
    logger.info(f"有效天数: {sample_stats.get('valid_days', 0)} 天")
    logger.info(f"IC 均值: {ic_metrics.get('ic_mean', 0):.4f}")
    logger.info(f"IC 标准差: {ic_metrics.get('ic_std', 0):.4f}")
    logger.info(f"ICIR: {ic_metrics.get('icir', 0):.2f}")
    logger.info(f"IC>0 占比: {result.get('positive_ratio', 0):.2%}")
    
    return result


if __name__ == '__main__':
    try:
        main()
    except RuntimeError:
        logger.exception("换手率突增因子 IC 计算失败")
        sys.exit(1)
    except Exception:
        logger.exception("换手率突增因子 IC 计算失败（未预期错误）")
        sys.exit(1)