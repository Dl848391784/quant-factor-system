#!/usr/bin/env python3
"""
价格区间收敛因子 IC 计算器

遵循 PROJECT.md 公共模块强制复用规范：
- 主流程使用 run_factor_ic()（FactorSpec 驱动入口，禁止手写三模式分支）
- 因子计算逻辑复用 data_fetchers.factor_calculator（遵循 MODULE.md 约束 #3）

因子定义：
- range_compression = (rolling_high_5d - rolling_low_5d) / (rolling_high_10d - rolling_low_10d)
- 含义: <1=价格区间收敛（企稳特征）
- 遵循 H5: IC方向不预判，由数据决定

退出码语义（遵循 PROJECT.md H12）：
  0 = 成功
  1 = 未预期错误（程序 bug；R20 main() 体内禁 sys.exit）
  3 = 辅助层失败（计算成功，但日志摘要/监控输出失败；R17）
  4 = DataSchemaError（数据 schema 不匹配，需检查上游列契约；R18）
  5 = FactorCalcError（因子计算失败或数据加载失败，需检查计算代码或上游数据；R19）

v2.35: P5-补充 新增因子（确认信号角色，二阶导数企稳信号）
"""

import argparse
import sys

from data_fetchers.factor_calculator import calculate_range_compression
from factor_ic.common.cli_helpers import DEFAULT_MIN_STOCKS
from factor_ic.common.exceptions import DataSchemaError, FactorCalcError, SummaryLogError
from factor_ic.common.factor_ic_runner import run_factor_ic
from factor_ic.common.factor_spec import FactorSpec, SpecRegistrationError, register_factor
from factor_ic.common.factor_summary_logger import log_factor_summary
from factor_ic.common.logger_config import get_logger


logger = get_logger(__name__)

_MAX_ERR_LEN = 200

try:
    SPEC = register_factor(
        FactorSpec(
            factor_name="range_compression",
            factor_col="range_compression",
            calculation=calculate_range_compression,
        )
    )
except SpecRegistrationError as e:
    logger.critical(
        "FactorSpec 注册失败 (factor=range_compression): %s (%s) (truncated to <=%d chars)",
        str(e)[:_MAX_ERR_LEN],
        type(e).__name__,
        _MAX_ERR_LEN,
    )
    raise


def _build_parser():
    """构建 CLI 参数解析器（main() 与 __main__ 共享，消除重复定义）。"""  # noqa: E501
    parser = argparse.ArgumentParser(description="价格区间收敛因子 IC 计算器")
    parser.add_argument("--force-full", action="store_true", help="强制全量计算")
    parser.add_argument("--min-stocks", type=int, default=DEFAULT_MIN_STOCKS, help="最小股票数")
    return parser


def _default_args():
    """构造库函数调用默认参数（避免 args=None 时解析 sys.argv）。"""  # noqa: E501
    return argparse.Namespace(min_stocks=DEFAULT_MIN_STOCKS, force_full=False)


def main(args=None):
    """CLI 主入口"""
    if args is None:
        args = _default_args()

    logger.info(
        "入口参数: min_stocks=%s, force_full=%s",
        args.min_stocks,
        args.force_full,
    )

    mode_label = "强制全量计算" if args.force_full else "增量更新"
    logger.info("模式判断: %s", mode_label)
    logger.info("============================================================")

    result = run_factor_ic(SPEC, args)

    period = result.get("period") or {}
    logger.info(
        "run_factor_ic 完成: 日期范围=%s~%s, 更新模式=%s",
        period.get("start", "N/A"),
        period.get("end", "N/A"),
        result.get("update_mode", "N/A"),
    )

    try:
        log_factor_summary(result, "价格区间收敛因子", logger)
    except Exception as e:
        raise SummaryLogError(
            "log_factor_summary 摘要输出阶段失败（因子计算 result 已成功生成；"
            "故障源 = 摘要日志层而非 run_factor_ic 业务路径）"
        ) from e

    ic_metrics = result.get("ic_metrics") or {}
    ic_mean = ic_metrics.get("ic_mean")
    icir = ic_metrics.get("icir")
    ic_mean_str = f"{ic_mean:.4f}" if ic_mean is not None else "N/A"
    icir_str = f"{icir:.2f}" if icir is not None else "N/A"
    logger.info(
        "价格区间收敛因子 IC计算完成: IC均值=%s, ICIR=%s",
        ic_mean_str,
        icir_str,
    )
    return result


if __name__ == "__main__":
    _cli_args = _build_parser().parse_args()

    try:
        result = main(args=_cli_args)
    except DataSchemaError as e:
        logger.error(
            "数据 Schema 校验失败 (factor=%s): %s",
            getattr(e, "factor_name", "unknown"),
            e,
        )
        sys.exit(4)
    except SummaryLogError as e:
        logger.error(
            "摘要输出阶段失败（因子计算 result 已成功生成；故障源 = 摘要日志层；原因: %s）",
            e.__cause__ or e,
        )
        sys.exit(3)
    except FactorCalcError as e:
        logger.error(
            "价格区间收敛因子 IC计算失败 (factor=%s, min_stocks=%s, force_full=%s): %s",
            SPEC.factor_name,
            _cli_args.min_stocks,
            _cli_args.force_full,
            e,
        )
        sys.exit(5)
    except Exception:
        logger.exception("未预期的错误")
        sys.exit(1)
