#!/usr/bin/env python3
"""
5日均线偏离度因子 IC 计算器

遵循 PROJECT.md 公共模块强制复用规范。
因子定义：ma5_deviation = (close - MA5) / MA5
含义：在均线之上=多头区域（上升趋势），方向性因子。遵循 H5: IC方向不预判。
边界：前4天→NaN；MA5=0→NaN；分母clip(lower=0.01)保护（遵循 Pitfall #47）。

作者: 云瑶
创建日期: 2026-06-11
版本历史:
  v1.0 (2026-06-11): 初始版本，复用 factor_calculator.calculate_ma5_deviation
"""

import argparse
import sys

from data_fetchers.factor_calculator import calculate_ma5_deviation
from factor_ic.common.cli_helpers import DEFAULT_MIN_STOCKS
from factor_ic.common.exceptions import DataSchemaError, FactorCalcError
from factor_ic.common.factor_ic_runner import run_factor_ic
from factor_ic.common.factor_spec import FactorSpec, register_factor
from factor_ic.common.logger_config import get_logger


logger = get_logger(__name__)

# ============================================================================
# FactorSpec 声明式注册（遵循 factor_cols_literal_constant_design.md §4.1）
# ============================================================================

SPEC = register_factor(
    FactorSpec(
        factor_name="ma5_deviation",
        factor_col="ma5_deviation",
        calculation=calculate_ma5_deviation,
    )
)

# ============================================================================
# 结果字典键名常量（与 factor_ic.common.ic_result_builder.build_ic_result 输出严格对齐）
# ----------------------------------------------------------------------------
# 引入原因：避免散落字符串字面量；run_factor_ic 返回结构变更时由静态检查/grep 一次定位。
# ============================================================================

_KEY_IC_METRICS = "ic_metrics"
_KEY_SAMPLE_STATS = "sample_stats"
_KEY_PERIOD = "period"
_KEY_IC_DISTRIBUTION = "ic_distribution_consistency"
_KEY_FACTOR_NAME = "factor_name"
_KEY_UPDATE_MODE = "update_mode"
# ic_metrics 子键
_KEY_IC_MEAN = "ic_mean"
_KEY_IC_STD = "ic_std"
_KEY_ICIR = "icir"
# ic_distribution_consistency 子键
_KEY_POSITIVE_RATIO = "positive_ratio"
# sample_stats / period 子键
_KEY_VALID_DAYS = "valid_days"
_KEY_PERIOD_START = "start"
_KEY_PERIOD_END = "end"


def main():
    """CLI 主入口"""
    parser = argparse.ArgumentParser(description="5日均线偏离度因子 IC 计算器")
    parser.add_argument("--force-full", action="store_true", help="强制全量计算")
    parser.add_argument("--min-stocks", type=int, default=DEFAULT_MIN_STOCKS, help="最小股票数")
    args = parser.parse_args()

    # 启动横幅由公共模块 factor_ic_runner 统一打印（含 min_stocks/force_full）
    # 此处补充 debug 入参审计：若公共横幅未覆盖某参数，调试时可从 DEBUG 日志确认入参实际值
    logger.debug("启动参数: force_full=%s, min_stocks=%s", args.force_full, args.min_stocks)

    result = run_factor_ic(
        spec=SPEC,
        min_stocks=args.min_stocks,
        force_full=args.force_full,
        logger=logger,
    )

    if result is None:
        raise FactorCalcError("run_factor_ic 返回 None，因子计算未产生有效结果，请检查数据或配置")

    ic_metrics = result.get(_KEY_IC_METRICS) or {}
    sample_stats = result.get(_KEY_SAMPLE_STATS) or {}
    period = result.get(_KEY_PERIOD) or {}
    ic_distribution = result.get(_KEY_IC_DISTRIBUTION) or {}

    ic_mean = ic_metrics.get(_KEY_IC_MEAN)
    ic_std = ic_metrics.get(_KEY_IC_STD)
    icir = ic_metrics.get(_KEY_ICIR)
    positive_ratio = ic_distribution.get(_KEY_POSITIVE_RATIO)

    ic_mean_str = f"{ic_mean:.4f}" if ic_mean is not None else "N/A"
    ic_std_str = f"{ic_std:.4f}" if ic_std is not None else "N/A"
    icir_str = f"{icir:.2f}" if icir is not None else "N/A"
    positive_ratio_str = f"{positive_ratio:.2%}" if positive_ratio is not None else "N/A"

    summary_lines = [
        "=" * 60,
        "结果摘要",
        "=" * 60,
        f"因子名称: {result.get(_KEY_FACTOR_NAME, 'unknown')}",
        f"更新模式: {result.get(_KEY_UPDATE_MODE, 'unknown')}",
        f"日期范围: {period.get(_KEY_PERIOD_START, 'N/A')} ~ {period.get(_KEY_PERIOD_END, 'N/A')}",
        f"有效天数: {sample_stats.get(_KEY_VALID_DAYS, 0)} 天",
        "--- IC指标 ---",
        f"IC 均值: {ic_mean_str}",
        f"IC 标准差: {ic_std_str}",
        f"ICIR: {icir_str}",
        f"IC>0 占比: {positive_ratio_str}",
    ]

    # 空值检测必须在摘要打印之前，避免读者先看到 N/A 后看到 warning 解释（日志语义颠倒）
    for field, name in [(ic_mean, "IC 均值"), (ic_std, "IC 标准差"), (icir, "ICIR"), (positive_ratio, "IC>0 占比")]:
        if field is None:
            logger.warning("%s为空", name)

    logger.info("\n%s", "\n".join(summary_lines))

    return result


if __name__ == "__main__":
    try:
        main()
    except DataSchemaError as e:
        # 数据 Schema 校验失败（公共模块 validate_required_columns 抛出）：
        # H12 R18 → exit 4 与因子计算失败（exit 5）严格区分。
        # MODULE.md M22：业务异常用 logger.error 不打堆栈。
        logger.error("数据 Schema 校验失败 (factor=%s): %s", e.factor_name, e)
        sys.exit(4)  # H12 R18: schema 失败 → 检查上游数据
    except FactorCalcError as e:
        logger.error("5日均线偏离度因子IC计算失败: %s", e)
        sys.exit(5)  # H12 R19: 因子计算失败 → 检查计算代码
    except Exception:
        logger.exception("未预期的错误")
        sys.exit(1)
