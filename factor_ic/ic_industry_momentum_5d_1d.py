#!/usr/bin/env python3
"""
行业5日动量因子 IC 计算器 - 使用公共模块主入口

遵循 PROJECT.md 公共模块强制复用规范：
- 主流程使用 run_factor_ic()（FactorSpec 驱动统一入口，已替代 run_simple/run_complex；
  详见 factor_ic/MODULE.md：禁止继续使用 run_complex_factor_ic，全部脚本已迁移）
- 因子计算逻辑复用 data_fetchers.factor_calculator（遵循 MODULE.md 约束 #3）

因子定义：
- industry_momentum_5d = 按(行业,日期)分组 → mean(past_return_1d) → 5日滚动均值
- 含义：行业整体5日趋势方向，方向性因子
- 遵循 H5: IC方向不预判，由数据决定
- 实测结论: 行业层面IC=+0.026（正值），方向性信号存在于行业而非个股

边界处理：
- industry 未知 → 赋 '其他' 行业
- 行业股票数 < 5 → 该日期该行业因子值 NaN
- past_return_1d 为 NaN → 行业均值自动跳过

作者: 云瑶
创建日期: 2026-06-12
版本历史:
  v1.0 (2026-06-12): 初始版本，复用 factor_calculator.calculate_industry_momentum_5d
"""

import argparse
import sys

from data_fetchers.factor_calculator import calculate_industry_momentum_5d
from factor_ic.common.cli_helpers import DEFAULT_MIN_STOCKS
from factor_ic.common.exceptions import DataSchemaError, FactorCalcError, SummaryLogError
from factor_ic.common.factor_ic_runner import run_factor_ic
from factor_ic.common.factor_spec import FactorSpec, SpecRegistrationError, register_factor
from factor_ic.common.factor_summary_logger import log_factor_summary
from factor_ic.common.logger_config import get_logger


logger = get_logger(__name__)

# ============================================================================
# FactorSpec 声明式注册（遵循 factor_cols_literal_constant_design.md §4.1）
# ============================================================================

_FACTOR_NAME = "industry_momentum_5d"

try:
    SPEC = register_factor(
        FactorSpec(
            factor_name=_FACTOR_NAME,
            factor_col=_FACTOR_NAME,
            calculation=calculate_industry_momentum_5d,
        )
    )
except SpecRegistrationError as e:
    # 注册失败兜底：logger.critical 显式落盘 factor_name + raise，不 sys.exit
    # （sys.exit 会杀 pytest 宿主，raise 让调用方决定行为）。
    # 向上传播类型：SpecRegistrationError(ValueError)。
    logger.critical(
        "FactorSpec 注册失败: factor=%s 错误: %s (truncated to <=200 chars)",
        _FACTOR_NAME,
        str(e)[:200],
    )
    raise


def parse_args() -> argparse.Namespace:
    """CLI 参数解析（R20 拆分：与 main 编排逻辑解耦，便于 main(args) 单元测试调用）。"""
    parser = argparse.ArgumentParser(description="行业5日动量因子 IC 计算器")
    parser.add_argument("--force-full", action="store_true", help="强制全量计算")
    parser.add_argument("--min-stocks", type=int, default=DEFAULT_MIN_STOCKS, help="最小股票数")
    return parser.parse_args()


def main(args: argparse.Namespace) -> dict:
    """流程编排：抛异常但不退出（R20：禁 sys.exit，退出码由 __main__ 块统一处理）。

    raises:
        DataSchemaError: 数据列契约不匹配（→ __main__ 退出码 4，R18）
        FactorCalcError: 因子计算内部失败（→ __main__ 退出码 5，R19）
        SummaryLogError: 摘要日志层失败（→ __main__ 退出码 3，R17；result 已生成）
    """
    # 启动横幅由公共模块 factor_ic_runner 统一打印；此处冗余落盘 min_stocks/force_full
    # 到本模块日志，作为公共横幅被过滤或回归时的可观测性兜底。
    # min_stocks=%s 用 %s 而非 %d：兼容单元测试直传非 int 的 argparse.Namespace。
    logger.info(
        "启动 run_factor_ic: factor=%s min_stocks=%s force_full=%s",
        SPEC.factor_name,
        args.min_stocks,
        args.force_full,
    )
    result = run_factor_ic(
        spec=SPEC,
        min_stocks=args.min_stocks,
        force_full=args.force_full,
        _logger=logger,
    )

    # 输出 IC 摘要（公共模块）。防御性保留 try/except：warning 先落盘原始异常类型，
    # 再 raise SummaryLogError 让 __main__ 走 exit 3。main 不 sys.exit，便于 pytest 调用。
    try:
        log_factor_summary(result, "行业5日动量因子", logger)
    except Exception as e:
        # 落盘原始异常类型，避免 SummaryLogError 包装后调用方无法区分摘要层内部故障。
        logger.warning(
            "log_factor_summary 摘要输出失败，原始异常类型: %s",
            type(e).__name__,
        )
        raise SummaryLogError(
            "log_factor_summary 摘要输出阶段失败（因子计算 result 已成功生成；"
            "故障源 = 摘要日志层而非 run_factor_ic 业务路径）"
        ) from e

    return result


if __name__ == "__main__":
    # ⚠️ 契约耦合：公共模块新增异常 → 必须同步本捕获链 + 退出码映射，否则落入
    # except Exception 兜底以 exit 1 上报，业务失败被误判为程序 bug。
    #
    # 退出码档（H12 R17/R18/R19）：
    #   exit 4 (DataSchemaError) → 上游数据 / 別契约
    #   exit 5 (FactorCalcError) → 因子计算代码
    #   exit 3 (SummaryLogError) → 主结果可用，sidecar 失败
    #   exit 1 (Exception)       → 未预期错误（CRITICAL 立即响应）
    #
    # 日志分工：DataSchemaError/FactorCalcError → logger.exception（message 含错误摘要，
    # 自动附加异常链 traceback）；SummaryLogError → logger.error（原始类型已由 main()
    # 内 warning 落盘，不再重复堆栈）；Exception 兜底 → logger.exception。
    try:
        main(parse_args())
    except DataSchemaError as e:
        # message 字段独立可读 + logger.exception 自动附加堆栈与异常链。
        logger.exception("行业5日动量因子IC计算失败 (数据列依赖不匹配): %s", e)
        sys.exit(4)  # H12 R18: schema 失败 → 检查上游数据
    except FactorCalcError as e:
        logger.exception("行业5日动量因子IC计算失败: %s", e)
        sys.exit(5)  # H12 R19: 因子计算失败 → 检查计算代码
    except SummaryLogError as e:
        # 不用 logger.exception：原始异常类型已由 main() 内 logger.warning 单独落盘，
        # SummaryLogError.__str__ 自带定位信息，再附加堆栈会与 warning 重复记录同一次失败。
        logger.error("摘要日志层失败（主结果产物已生成，可用）: %s", e)
        sys.exit(3)  # H12 R17: 辅助层失败专用退出码
    except Exception:
        logger.exception("未预期的错误")
        sys.exit(1)
