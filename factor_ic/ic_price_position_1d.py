#!/usr/bin/env python3
"""
全天价格位置因子 IC 计算器 - 使用公共模块主入口

遵循 PROJECT.md 公共模块强制复用规范：
- 主流程使用 run_complex_factor_ic()（禁止手写三模式分支）
- 因子计算逻辑复用 data_fetchers.factor_calculator（遵循 MODULE.md 约束 #3）

代码量：~60行（仅 CLI 入口），因子计算逻辑已统一到 factor_calculator.py。

因子定义：
- Price Position = (Close - Low) / (High - Low)
- 含义：收盘价在全天振幅中的相对位置
  - 0 = 收盘价等于最低价（全天最低收盘）
  - 1 = 收盘价等于最高价（全天最高收盘）
  - 0.5 = 收盘价在振幅中位

边界处理：
- High - Low = 0 时，使用 epsilon 防止除零，设为 0.5（中位）

作者: 云瑶
创建日期: 2026-05-29
版本历史:
  v1.0 (2026-05-29): 初始版本，复用 factor_calculator.calculate_price_position
  v1.1 (2026-05-31): 优化日志字段名 + 防御性 None 处理 + 删除未使用导入 + 异常处理改进
"""

import argparse
import sys
from pathlib import Path


# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent.parent))

# 导入公共模块主入口（遵循 PROJECT.md 强制复用规范）
# 从 factor_calculator 导入因子计算函数（遵循 MODULE.md 约束 #3）
from data_fetchers.factor_calculator import calculate_price_position
from factor_ic.common.cli_helpers import DEFAULT_MIN_STOCKS
from factor_ic.common.exceptions import FactorCalcError
from factor_ic.common.factor_ic_runner import run_complex_factor_ic
from factor_ic.common.logger_config import get_logger


logger = get_logger(__name__)
# ============================================================================
# CLI 入口
# ============================================================================


def main():
    """CLI 主入口"""

    parser = argparse.ArgumentParser(description="全天价格位置因子 IC 计算器")
    parser.add_argument("--force-full", action="store_true", help="强制全量计算")
    parser.add_argument("--min-stocks", type=int, default=DEFAULT_MIN_STOCKS, help="最小股票数")

    args = parser.parse_args()

    # 调用前日志
    logger.info(
        "启动全天价格位置因子IC计算: min_stocks=%s, force_full=%s",
        args.min_stocks,
        args.force_full,
    )

    # 使用公共模块主入口（遵循 PROJECT.md 强制复用规范）
    result = run_complex_factor_ic(
        factor_name="price_position",
        factor_col="price_position",
        factor_cols=["high", "low", "close"],  # 需要三列进行计算
        custom_factor_calculation=calculate_price_position,
        # price_position 无额外参数（公共模块默认 params=None，内部会转为 {}）
        min_stocks=args.min_stocks,
        force_full=args.force_full,
        _logger=logger,
    )

    # 保底处理：公共模块异常返回 None 时抛出 RuntimeError
    if result is None:
        raise FactorCalcError("run_complex_factor_ic 返回 None")

    # 使用 .get() + or {} 防御性访问结果（避免 None 导致格式化失败）
    ic_metrics = result.get("ic_metrics") or {}
    sample_stats = result.get("sample_stats") or {}
    period = result.get("period") or {}
    # 字段名来源于 MODULE.md 第56行输出结构模板
    ic_distribution = result.get("ic_distribution_consistency") or {}

    logger.info("=" * 60)
    logger.info("结果摘要")
    logger.info("=" * 60)
    logger.info("因子名称: %s", result.get("factor_name", "unknown"))
    logger.info("更新模式: %s", result.get("update_mode", "unknown"))
    logger.info("日期范围: %s ~ %s", period.get("start", "N/A"), period.get("end", "N/A"))
    logger.info("有效天数: %s 天", sample_stats.get("valid_days", 0))
    logger.info("--- IC指标 ---")
    ic_mean = ic_metrics.get("ic_mean")
    if ic_mean is not None:
        logger.info("IC 均值: %.4f", ic_mean)
    else:
        logger.info("IC 均值: N/A（计算结果为空）")
    ic_std = ic_metrics.get("ic_std")
    if ic_std is not None:
        logger.info("IC 标准差: %.4f", ic_std)
    else:
        logger.info("IC 标准差: N/A")
    icir = ic_metrics.get("icir")
    if icir is not None:
        logger.info("ICIR: %.2f", icir)
    else:
        logger.info("ICIR: N/A")
    positive_ratio = ic_distribution.get("positive_ratio")
    if positive_ratio is not None:
        logger.info("IC>0 占比: %.2f%%", positive_ratio * 100)
    else:
        logger.info("IC>0 占比: N/A")

    # 异常状态整体感知日志（运维巡检用）
    if ic_mean is None:
        logger.warning("本次IC计算结果为空，请检查数据源或参数配置")

    # 确认结果处理完成后才输出"计算完成"日志
    logger.info("全天价格位置因子IC计算完成")

    return result


if __name__ == "__main__":
    try:
        main()
    except FactorCalcError as e:
        # 已知业务异常，使用 error()（不打印完整堆栈）
        logger.error("全天价格位置因子IC计算失败: %s", e)
        sys.exit(1)
    except Exception:
        # 未预期异常，使用 exception()（自动打印完整堆栈，无需重复传 e）
        logger.exception("未预期的错误")
        sys.exit(1)
