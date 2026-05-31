#!/usr/bin/env python3
"""
量比因子 IC 计算器（重构版 v2） - 1日收益周期

使用公共模块主入口 run_simple_factor_ic，代码量从 253 行降至 ~60 行。

功能：
1. 从缓存数据计算量比因子(volume_ratio_5)的 IC
2. 支持全量计算、增量更新和跳过三种模式
3. 五维度独立判断（统计显著性、因子方向、经济显著性、ICIR稳定性、IC分布一致性）

实现方式：
- 使用 run_simple_factor_ic() 公共模块主入口
- 无需自定义因子计算（量比已在缓存中）

遵循 PROJECT.md 公共模块强制复用规范：
- 主流程使用 run_simple_factor_ic()（禁止手写三模式分支）
- 仅实现因子特有参数配置

作者: 云瑶
重构日期: 2026-05-23（v2：使用 run_simple_factor_ic）
原版作者: 云舟
原版日期: 2026-05-08
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
    
    parser = argparse.ArgumentParser(description='量比因子 IC 计算器（重构版 v2）')
    parser.add_argument('--force-full', action='store_true', help='强制全量计算')
    parser.add_argument('--min-stocks', type=int, default=DEFAULT_MIN_STOCKS, help='最小股票数')
    
    args = parser.parse_args()
    
    # 问题2修复：调用前日志，记录启动参数
    logger.info(f"启动量比因子IC计算: min_stocks={args.min_stocks}, force_full={args.force_full}")
    
    # 使用公共模块主入口（遵循 PROJECT.md 强制复用规范）
    result = run_simple_factor_ic(
        factor_name='volume_ratio',
        factor_col='volume_ratio_5',
        min_stocks=args.min_stocks,
        force_full=args.force_full,
        _logger=logger
    )
    
    # 调用完成日志
    logger.info("量比因子IC计算完成")
    
    # 使用 .get() 防御性访问结果
    ic_metrics = result.get('ic_metrics', {})
    
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
        # 问题3修复：改为具体错误描述
        logger.exception("量比因子IC计算失败")
        sys.exit(1)
    except Exception:
        logger.exception("未预期的错误")
        sys.exit(1)