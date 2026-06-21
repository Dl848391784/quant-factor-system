#!/usr/bin/env python3
"""交互因子 IC 计算器：interaction_near_high（v2.37, 2026-06-22）

设计依据: designs/feat_interaction_factors_batch2.md
因子定义: -z_cs(ret3d) × z_cs(near_high_ratio_5)
实证全样本 IC≈+0.0425

作者: 云瑶
创建日期: 2026-06-22
"""

import argparse
import sys

from data_fetchers.factor_calculator import calculate_interaction_near_high
from factor_ic.common.cli_helpers import DEFAULT_MIN_STOCKS
from factor_ic.common.exceptions import DataSchemaError, FactorCalcError
from factor_ic.common.factor_ic_runner import run_factor_ic
from factor_ic.common.factor_spec import FactorSpec, register_factor
from factor_ic.common.logger_config import get_logger


logger = get_logger(__name__)

SPEC = register_factor(
    FactorSpec(
        factor_name="interaction_near_high",
        factor_col="interaction_near_high",
        calculation=calculate_interaction_near_high,
    )
)


def main():
    parser = argparse.ArgumentParser(description="interaction_near_high 交互因子 IC 计算器")
    parser.add_argument("--force-full", action="store_true", help="强制全量计算")
    parser.add_argument("--min-stocks", type=int, default=DEFAULT_MIN_STOCKS, help="最小股票数")
    args = parser.parse_args()

    result = run_factor_ic(spec=SPEC, min_stocks=args.min_stocks, force_full=args.force_full, logger=logger)
    if result is None:
        raise FactorCalcError("run_factor_ic 返回 None")

    ic_metrics = result.get("ic_metrics") or {}
    ic_mean = ic_metrics.get("ic_mean")
    icir = ic_metrics.get("icir")
    logger.info(
        "==== 结果摘要 ==== %s IC=%s ICIR=%s",
        result.get("factor_name", "?"),
        f"{ic_mean:.4f}" if ic_mean is not None else "N/A",
        f"{icir:.2f}" if icir is not None else "N/A",
    )
    return result


if __name__ == "__main__":
    try:
        main()
    except DataSchemaError as e:
        logger.error("数据 Schema 校验失败 (factor=%s): %s", e.factor_name, e)
        sys.exit(4)
    except FactorCalcError as e:
        logger.error("interaction_near_high 因子IC计算失败: %s", e)
        sys.exit(5)
    except Exception:
        logger.exception("未预期的错误")
        sys.exit(1)
