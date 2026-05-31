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
版本历史:
  v1.0 (2026-05-29): 初始版本，复用 factor_calculator.calculate_amplitude
  v1.1 (2026-05-31): 优化日志字段名 + 防御性 None 处理 + 删除未使用导入
"""

import sys
from pathlib import Path

# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent.parent))

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
    except RuntimeError as e:
        logger.exception(f"振幅因子IC计算失败: {e}")
        sys.exit(1)
    except Exception as e:
        logger.exception(f"未预期的错误: {e}")
        sys.exit(1)