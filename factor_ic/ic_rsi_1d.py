#!/usr/bin/env python3
"""
RSI_1D IC 计算器（重构版 v2） - 1日收益周期

使用公共模块主入口 run_simple_factor_ic，代码量从 254 行降至 ~60 行。

功能：
1. 从缓存数据计算 RSI(6) 因子的 IC
2. 支持全量计算、增量更新和跳过三种模式
3. 五维度独立判断（统计显著性、因子方向、经济显著性、ICIR稳定性、IC分布一致性）

实现方式：
- 使用 run_simple_factor_ic() 公共模块主入口
- 无需自定义因子计算（RSI 已在缓存中）

遵循 PROJECT.md 公共模块强制复用规范：
- 主流程使用 run_simple_factor_ic()（禁止手写三模式分支）
- 仅实现因子特有参数配置

作者: 云瑶
重构日期: 2026-05-23（v2：使用 run_simple_factor_ic）
原版作者: 云舟
原版日期: 2026-05-07
"""

import sys
from pathlib import Path

# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent.parent))

# 导入公共模块主入口（遵循 PROJECT.md 强制复用规范）
from factor_ic.common.factor_ic_runner import run_simple_factor_ic
from factor_ic.common.logger_config import get_logger

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
    
    parser = argparse.ArgumentParser(description='RSI_1D IC 计算器（重构版 v2）')
    parser.add_argument('--force-full', action='store_true', help='强制全量计算')
    parser.add_argument('--min-stocks', type=int, default=DEFAULT_MIN_STOCKS, help='最小股票数')
    
    args = parser.parse_args()
    
    # 使用公共模块主入口（遵循 PROJECT.md 强制复用规范）
    result = run_simple_factor_ic(
        factor_name='rsi',
        factor_col='rsi_6',
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
        logger.exception("计算失败")  # 使用 .exception() 保留完整堆栈
        sys.exit(1)
    except Exception as e:
        logger.exception("未预期的错误")  # 使用 .exception() 保留完整堆栈
        sys.exit(1)