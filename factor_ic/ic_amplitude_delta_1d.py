#!/usr/bin/env python3
"""
振幅差分因子 IC 计算器 - 使用公共模块主入口

遵循 PROJECT.md 公共模块强制复用规范：
- 主流程使用 run_complex_factor_ic()（禁止手写三模式分支）
- 因子计算逻辑复用 data_fetchers.factor_calculator（遵循 MODULE.md 约束 #3）

因子定义：
- amplitude_delta = amplitude(T) - amplitude(T-1)
- 含义：振幅从低开始回升 = 止跌放量信号；振幅继续下降 = 闷跌加剧
- 遵循 H5: IC方向不预判，由数据决定

边界处理：
- 第一日无前值 → NaN（自然排除）
- amplitude 为 NaN → delta 也为 NaN（传播）

作者: 云瑶
创建日期: 2026-06-11
版本历史:
  v1.0 (2026-06-11): 初始版本，复用 factor_calculator.calculate_amplitude_delta
"""

import argparse
import sys
from pathlib import Path


# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent.parent))  # noqa: E402

# 导入公共模块主入口（遵循 PROJECT.md 强制复用规范）
# 从 factor_calculator 导入因子计算函数（遵循 MODULE.md 约束 #3）
from data_fetchers.factor_calculator import calculate_amplitude_delta  # noqa: E402
from factor_ic.common.cli_helpers import DEFAULT_MIN_STOCKS  # noqa: E402
from factor_ic.common.exceptions import FactorCalcError  # noqa: E402
from factor_ic.common.factor_ic_runner import run_complex_factor_ic  # noqa: E402
from factor_ic.common.factor_summary_logger import log_factor_summary  # noqa: E402
from factor_ic.common.logger_config import get_logger  # noqa: E402


logger = get_logger(__name__)

# ============================================================================
# CLI 入口
# ============================================================================


def main():
    """CLI 主入口"""

    parser = argparse.ArgumentParser(description="振幅差分因子 IC 计算器")
    parser.add_argument("--force-full", action="store_true", help="强制全量计算")
    parser.add_argument("--min-stocks", type=int, default=DEFAULT_MIN_STOCKS, help="最小股票数")

    args = parser.parse_args()

    # 调用前日志
    logger.info(
        "启动振幅差分因子IC计算: min_stocks=%s, force_full=%s",
        args.min_stocks,
        args.force_full,
    )

    # 使用公共模块主入口（遵循 PROJECT.md 强制复用规范）
    result = run_complex_factor_ic(
        factor_name="amplitude_delta",
        factor_col="amplitude_delta",
        factor_cols=["date", "asset", "amplitude"],  # 需要原始因子列进行差分计算
        custom_factor_calculation=calculate_amplitude_delta,
        min_stocks=args.min_stocks,
        force_full=args.force_full,
        _logger=logger,
    )

    # 防御性检查：result 为 None 时抛出业务异常（遵循 PROJECT.md 异常处理规范）
    if result is None:
        raise FactorCalcError("run_complex_factor_ic 返回 None，数据加载或计算可能失败")

    # 输出 IC 摘要 + None 状态整合告警（公共模块,M3.1）
    log_factor_summary(result, "振幅差分因子", logger)

    # 确认结果处理完成后才输出"计算完成"日志
    logger.info("振幅差分因子IC计算完成")

    return result


if __name__ == "__main__":
    try:
        main()
    except FactorCalcError as e:
        # 已知业务异常，使用 error()（不打印完整堆栈，但保留错误内容）
        logger.error("振幅差分因子IC计算失败: %s", e)
        sys.exit(1)
    except Exception:
        # 未预期异常（含非预期 RuntimeError），使用 exception()（自动打印完整堆栈）
        logger.exception("未预期的错误")
        sys.exit(1)
