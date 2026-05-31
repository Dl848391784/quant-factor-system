#!/usr/bin/env python3
"""
5日累计涨幅因子 IC 计算器 - 使用公共模块主入口

遵循 PROJECT.md 公共模块强制复用规范：
- 主流程使用 run_complex_factor_ic()（禁止手写三模式分支）
- 因子计算逻辑复用 data_fetchers.factor_calculator（遵循 MODULE.md 约束 #3）

代码量：~60行（仅 CLI 入口），因子计算逻辑已统一到 factor_calculator.py。

因子定义：
- Return_5d = close[t] / close[t-5] - 1
- 含义：过去5日累计涨跌幅
  - 正值 → 上涨
  - 负值 → 下跌
  - 范围：理论 [-∞, +∞)，A股日涨跌幅±10%，5日累计约±50%

边界处理：
- 前5日数据设为 NaN（历史数据不足）
- close[t-5] = 0 时设为 NaN（无效数据）

作者: 云瑶
创建日期: 2026-05-29
"""

import sys
from pathlib import Path

# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent.parent))

import pandas as pd

# 导入公共模块主入口（遵循 PROJECT.md 强制复用规范）
from factor_ic.common.factor_ic_runner import run_complex_factor_ic
from factor_ic.common.logger_config import get_logger

# 从 factor_calculator 导入因子计算函数（遵循 MODULE.md 约束 #3）
from data_fetchers.factor_calculator import calculate_return_5d

logger = get_logger(__name__)

# ============================================================================
# 参数统一管理
# ============================================================================
DEFAULT_MIN_STOCKS = 10


# ============================================================================
# CLI 入口
# ============================================================================

def main():
    """CLI 主入口"""
    import argparse
    
    parser = argparse.ArgumentParser(description='5日累计涨幅因子 IC 计算器')
    parser.add_argument('--force-full', action='store_true', help='强制全量计算')
    parser.add_argument('--min-stocks', type=int, default=DEFAULT_MIN_STOCKS, help='最小股票数')
    
    args = parser.parse_args()
    
    # 调用前日志
    logger.info(f"启动5日累计涨幅因子IC计算: min_stocks={args.min_stocks}, force_full={args.force_full}")
    
    # 使用公共模块主入口（遵循 PROJECT.md 强制复用规范）
    result = run_complex_factor_ic(
        factor_name='return_5d',
        factor_col='return_5d',
        factor_cols=['close', 'asset', 'date'],  # 需要三列进行计算
        custom_factor_calculation=calculate_return_5d,
        custom_factor_calculation_params={},  # return_5d 无额外参数
        min_stocks=args.min_stocks,
        force_full=args.force_full,
        _logger=logger
    )
    
    # 调用后日志
    logger.info("5日累计涨幅因子IC计算完成")
    
    # 使用 .get() + or {} 防御性访问结果（避免 None 导致格式化失败）
    ic_metrics = result.get('ic_metrics') or {}
    sample_stats = result.get('sample_stats') or {}
    period = result.get('period') or {}
    
    logger.info("=" * 60)
    logger.info("结果摘要")
    logger.info("=" * 60)
    logger.info(f"因子名称: {result.get('factor_name', 'unknown')}")
    logger.info(f"更新模式: {result.get('update_mode', 'unknown')}")
    logger.info(f"日期范围: {period.get('start', 'N/A')} ~ {period.get('end', 'N/A')}")
    logger.info(f"有效天数: {sample_stats.get('valid_days', 0)} 天")
    logger.info("--- IC指标 ---")
    ic_mean = ic_metrics.get('ic_mean')
    if ic_mean is not None:
        logger.info(f"IC 均值: {ic_mean:.4f}")
    else:
        logger.info("IC 均值: N/A（数据加载失败）")
    ic_std = ic_metrics.get('ic_std')
    if ic_std is not None:
        logger.info(f"IC 标准差: {ic_std:.4f}")
    else:
        logger.info("IC 标准差: N/A")
    icir = ic_metrics.get('icir')
    if icir is not None:
        logger.info(f"ICIR: {icir:.2f}")
    else:
        logger.info("ICIR: N/A")
    positive_ratio = result.get('positive_ratio')
    if positive_ratio is not None:
        logger.info(f"IC>0 占比: {positive_ratio:.2%}")
    else:
        logger.info("IC>0 占比: N/A")
    
    return result


if __name__ == '__main__':
    try:
        main()
    except RuntimeError:
        logger.exception("5日累计涨幅因子IC计算失败")
        sys.exit(1)
    except Exception:
        logger.exception("未预期的错误")
        sys.exit(1)