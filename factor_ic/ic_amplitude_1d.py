#!/usr/bin/env python3
"""
振幅因子 IC 计算器 - 使用公共模块主入口

遵循 PROJECT.md 公共模块强制复用规范：
- 主流程使用 run_complex_factor_ic()（禁止手写三模式分支）
- 因子计算逻辑复用 data_fetchers.factor_calculator（遵循 MODULE.md 约束 #3）

代码量：~60行（仅 CLI 入口），因子计算逻辑已统一到 factor_calculator.py。

因子定义：
- Amplitude = (High - Low) / Close
- 含义：当日振幅相对于收盘价的比率，反映价格波动强度
  - 值越大 → 波动越剧烈
  - 值越小 → 波动平稳
  - 范围：理论 [0, +∞)，实际通常 [0, 0.15]（A股振幅上限15%）

边界处理：
- Close = 0 时，设为 NaN（无效数据）
- High = Low 时，振幅为 0（一字涨停/跌停）

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
from data_fetchers.factor_calculator import calculate_amplitude

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
    
    parser = argparse.ArgumentParser(description='振幅因子 IC 计算器')
    parser.add_argument('--force-full', action='store_true', help='强制全量计算')
    parser.add_argument('--min-stocks', type=int, default=DEFAULT_MIN_STOCKS, help='最小股票数')
    
    args = parser.parse_args()
    
    # 调用前日志
    logger.info(f"启动振幅因子IC计算: min_stocks={args.min_stocks}, force_full={args.force_full}")
    
    # 使用公共模块主入口（遵循 PROJECT.md 强制复用规范）
    result = run_complex_factor_ic(
        factor_name='amplitude',
        factor_col='amplitude',
        factor_cols=['high', 'low', 'close'],  # 需要三列进行计算
        custom_factor_calculation=calculate_amplitude,
        custom_factor_calculation_params={},  # amplitude 无额外参数
        min_stocks=args.min_stocks,
        force_full=args.force_full,
        _logger=logger
    )
    
    # 调用后日志
    logger.info("振幅因子IC计算完成")
    
    # 使用 .get() 防御性访问结果
    ic_metrics = result.get('ic_metrics', {})
    
    # 完整指标输出
    logger.info("=" * 60 + " 结果摘要 " + "=" * 60)
    logger.info(f"因子名称: {result.get('factor_name', 'unknown')}")
    logger.info(f"更新模式: {result.get('update_mode', 'unknown')}")
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
        logger.exception("振幅因子IC计算失败")
        sys.exit(1)
    except Exception:
        logger.exception("未预期的错误")
        sys.exit(1)