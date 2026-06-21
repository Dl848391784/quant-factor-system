#!/usr/bin/env python3
"""
5日收益率加速度因子 IC 计算器

遵循 PROJECT.md 公共模块强制复用规范：
- 主流程使用 run_factor_ic()（FactorSpec 驱动入口，禁止手写三模式分支）
- 因子计算逻辑复用 data_fetchers.factor_calculator（遵循 MODULE.md 约束 #3）

因子定义：
- return_acceleration_5d = return_5d(t) - return_5d(t-5)
- 含义: 5日收益率加速度，正值=跌幅收窄，二阶导数企稳信号
- 遵循 H5: IC方向不预判，由数据决定

退出码语义（遵循 PROJECT.md H12）：
  0 = 成功
  1 = 未预期错误（程序 bug；R20 main() 体内禁 sys.exit）
  3 = 辅助层失败（计算成功，但日志摘要/监控输出失败；R17）
  4 = DataSchemaError（数据 schema 不匹配，需检查上游列契约；R18）
  5 = FactorCalcError（因子计算失败或数据加载失败，需检查计算代码或上游数据；R19）

v2.35: P5-补充 二阶导数企稳信号因子
"""

import argparse
import sys

from data_fetchers.factor_calculator.momentum import calculate_return_acceleration_5d
from factor_ic.common.cli_helpers import DEFAULT_MIN_STOCKS
from factor_ic.common.exceptions import DataSchemaError, FactorCalcError, SummaryLogError
from factor_ic.common.factor_ic_runner import run_factor_ic
from factor_ic.common.factor_spec import FactorSpec, SpecRegistrationError, register_factor
from factor_ic.common.factor_summary_logger import log_factor_summary
from factor_ic.common.logger_config import get_logger


logger = get_logger(__name__)

_MAX_ERR_LEN = 200

# ============================================================================
# FactorSpec 声明式注册（遵循 M3.3）
# 预计算因子: 传 calculation，required_columns 从 calculation.required_cols 自动派生
# ============================================================================

try:
    SPEC = register_factor(
        FactorSpec(
            factor_name="return_acceleration_5d",
            factor_col="return_acceleration_5d",
            calculation=calculate_return_acceleration_5d,
        )
    )
except SpecRegistrationError as e:
    logger.critical(
        "FactorSpec 注册失败 (factor=return_acceleration_5d): %s (%s) (truncated to <=%d chars)",
        str(e)[:_MAX_ERR_LEN],
        type(e).__name__,
        _MAX_ERR_LEN,
    )
    raise


def main() -> None:
    parser = argparse.ArgumentParser(description="5日收益率加速度因子 IC 计算器")
    parser.add_argument(
        "--min_stocks",
        type=int,
        default=DEFAULT_MIN_STOCKS,
        help="截面最少股票数（低于此值跳过该日期）",
    )
    parser.add_argument(
        "--force-full",
        action="store_true",
        help="强制全量计算（跳过缓存检测）",
    )
    args = parser.parse_args()

    exit_code = 0

    try:
        ic_result = run_factor_ic(SPEC, min_stocks=args.min_stocks, force_full=args.force_full)

        ic_mean = ic_result.get("ic_mean")
        ic_std = ic_result.get("ic_std")
        icir = ic_result.get("icir")
        ic_positive_ratio = ic_result.get("ic_positive_ratio")
        logger.info(
            "收益率加速度因子 IC计算完成: IC均值=%.4f, ICIR=%.2f",
            ic_mean if ic_mean is not None else 0.0,
            icir if icir is not None else 0.0,
        )

        try:
            log_factor_summary(
                factor_name="return_acceleration_5d",
                ic_result=ic_result,
            )
        except (SummaryLogError, Exception) as e:
            logger.error(
                "日志摘要记录失败 (factor=return_acceleration_5d): %s (%s) (truncated to <=%d chars)",
                str(e)[:_MAX_ERR_LEN],
                type(e).__name__,
                _MAX_ERR_LEN,
            )
            if exit_code == 0:
                exit_code = 3

    except DataSchemaError as e:
        logger.critical(
            "数据 schema 不匹配 (factor=return_acceleration_5d): %s (%s)",
            str(e)[:_MAX_ERR_LEN],
            type(e).__name__,
        )
        exit_code = 4
    except (FactorCalcError, Exception) as e:
        logger.exception(
            "因子计算失败 (factor=return_acceleration_5d): %s (%s)",
            str(e)[:_MAX_ERR_LEN],
            type(e).__name__,
        )
        exit_code = 5

    sys.exit(exit_code)


if __name__ == "__main__":
    main()
