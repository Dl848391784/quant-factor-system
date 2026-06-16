#!/usr/bin/env python3
"""
振幅差分因子 IC 计算器 - 使用公共模块主入口

遵循 PROJECT.md 公共模块强制复用规范：
- 主流程使用 run_factor_ic()（禁止手写三模式分支）
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

# 导入公共模块主入口（遵循 PROJECT.md 强制复用规范）
# 从 factor_calculator 导入因子计算函数（遵循 MODULE.md 约束 #3）
from data_fetchers.factor_calculator import calculate_amplitude_delta
from factor_ic.common.cli_helpers import DEFAULT_MIN_STOCKS
from factor_ic.common.exceptions import FactorCalcError
from factor_ic.common.factor_ic_runner import run_factor_ic
from factor_ic.common.factor_spec import FactorSpec, register_factor
from factor_ic.common.factor_summary_logger import log_factor_summary
from factor_ic.common.logger_config import get_logger


logger = get_logger(__name__)

# ============================================================================
# FactorSpec 声明式注册（遵循 factor_cols_literal_constant_design.md §4.1）
# required_columns: JOIN_KEYS + 上游因子列（amplitude 来自 factor_generator _EXTENDED_FACTOR_COLS）
# ============================================================================

SPEC = register_factor(
    FactorSpec(
        factor_name="amplitude_delta",
        factor_col="amplitude_delta",
        calculation=calculate_amplitude_delta,
    )
)

# ============================================================================
# CLI 入口
# ============================================================================


def main():
    """CLI 主入口"""

    parser = argparse.ArgumentParser(description="振幅差分因子 IC 计算器")
    parser.add_argument("--force-full", action="store_true", help="强制全量计算")
    parser.add_argument("--min-stocks", type=int, default=DEFAULT_MIN_STOCKS, help="最小股票数")

    args = parser.parse_args()

    # 启动横幅由公共模块 factor_ic_runner 统一打印（含 min_stocks/force_full）
    # 使用 FactorSpec 驱动入口（遵循 factor_cols_literal_constant_design.md §4.1）
    result = run_factor_ic(
        spec=SPEC,
        min_stocks=args.min_stocks,
        force_full=args.force_full,
        _logger=logger,
    )

    # 防御性检查：result 为 None 时抛出业务异常（遵循 PROJECT.md 异常处理规范）
    # 不在此处 logger.error，由底部 except FactorCalcError 统一打印，避免双重日志
    if result is None:
        raise FactorCalcError("run_factor_ic 返回 None，数据加载或计算可能失败")

    # 包裹 log_factor_summary：摘要层失败 → sys.exit(3) 显式辅助层失败信号
    # （PROJECT.md H12 R17）。因子计算 result 已成功生成，主结果产物可用，下游
    # backtest/comprehensive/summary 可正常消费；仅旁路日志摘要失败时返回 exit 3，
    # 与业务失败（exit 1）和 import-time 注册失败（exit 2）严格区分。
    try:
        log_factor_summary(result, "振幅差分因子", logger)
    except Exception:
        logger.exception(
            "log_factor_summary 摘要输出阶段失败（因子计算 result 已成功生成；"
            "故障源 = 摘要日志层而非 run_factor_ic 业务路径）"
        )
        sys.exit(3)  # H12 R17：辅助层失败专用退出码

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
