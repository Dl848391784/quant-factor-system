#!/usr/bin/env python3
"""
换手率衰减因子 IC 计算器

遵循 PROJECT.md 公共模块强制复用规范：
- 主流程使用 run_factor_ic()（FactorSpec 驱动入口，禁止手写三模式分支）
- 因子计算逻辑复用 data_fetchers.factor_calculator 的 calculate_turnover_decay_rate

因子定义：
- turnover_decay_rate: turnover_rate / mean(turnover_rate, 5d)
- 含义: 当日换手率相对近期均值比值，<1=换手率下降
- v2.35: P5-补充因子（确认信号角色，企稳信号二阶维度）
- 预期IC方向: 反向（衰减→企稳，但衰减本身值小）

退出码：
- 0: 成功
- 1: 运行时错误
- 3: SummaryLogError（摘要日志异常）
- 4: DataSchemaError（数据列缺失/类型异常）
- 5: FactorCalcError（因子计算异常）
"""

import logging
import sys

from data_fetchers.factor_calculator import calculate_turnover_decay_rate
from factor_ic.common.cli_helpers import DEFAULT_MIN_STOCKS
from factor_ic.common.exceptions import (
    DataSchemaError,
    FactorCalcError,
    SummaryLogError,
)
from factor_ic.common.factor_ic_runner import run_factor_ic
from factor_ic.common.factor_spec import FactorSpec, register_factor
from factor_ic.common.factor_summary_logger import log_factor_summary


# ---------------------------------------------------------------------------
# FactorSpec 注册——calculation 参数让 FactorSpec 自动从 required_cols 派生
# required_columns
# ---------------------------------------------------------------------------
try:
    SPEC = register_factor(
        FactorSpec(
            factor_name="turnover_decay_rate",
            factor_col="turnover_decay_rate",
            calculation=calculate_turnover_decay_rate,
        )
    )
except Exception as e:
    raise type(e)("FactorSpec 注册失败: " + str(e)) from e


def main(args=None):  # noqa: C901
    """CLI 入口——args=None 支持 -m 调用"""
    # --help / --version 等由 factor_ic_runner 内部 argparse 处理
    if args is not None:
        sys.argv = [sys.argv[0]] + list(args)

    try:
        result = run_factor_ic(
            spec=SPEC,
            min_stocks=DEFAULT_MIN_STOCKS,
        )
    except SummaryLogError as exc:
        logging.exception("摘要日志异常: %s", exc)
        sys.exit(3)
    except DataSchemaError as exc:
        logging.exception("数据 Schema 异常: %s", exc)
        sys.exit(4)
    except FactorCalcError as exc:
        logging.exception("因子计算异常: %s", exc)
        sys.exit(5)
    except Exception as exc:
        logging.exception("未预期异常: %s", exc)
        sys.exit(1)

    log_factor_summary(result, factor_name="turnover_decay_rate")
    sys.exit(0)


if __name__ == "__main__":
    main()
