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
from factor_ic.common.ic_result_builder import (
    RESULT_KEY_FACTOR_NAME as _KEY_FACTOR_NAME,
    RESULT_KEY_IC_DISTRIBUTION as _KEY_IC_DISTRIBUTION,
    RESULT_KEY_IC_MEAN as _KEY_IC_MEAN,
    RESULT_KEY_IC_METRICS as _KEY_IC_METRICS,
    RESULT_KEY_IC_STD as _KEY_IC_STD,
    RESULT_KEY_ICIR as _KEY_ICIR,
    RESULT_KEY_PERIOD as _KEY_PERIOD,
    RESULT_KEY_PERIOD_END as _KEY_PERIOD_END,
    RESULT_KEY_PERIOD_START as _KEY_PERIOD_START,
    RESULT_KEY_POSITIVE_RATIO as _KEY_POSITIVE_RATIO,
    RESULT_KEY_SAMPLE_STATS as _KEY_SAMPLE_STATS,
    RESULT_KEY_UPDATE_MODE as _KEY_UPDATE_MODE,
    RESULT_KEY_VALID_DAYS as _KEY_VALID_DAYS,
)
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
# 结果字典键名常量
# ----------------------------------------------------------------------------
# 全部从 factor_ic.common.ic_result_builder 导入并以 _KEY_* 私名 alias 局部使用：
# 键名变更只需改 ic_result_builder.RESULT_KEY_*，本文件无需同步——
# 让"键名对齐"从注释承诺升级为代码约束（import 失败即 import-time 报错）。
# ============================================================================


def _safe_dict(result: dict, key: str) -> dict:
    """从 result 安全提取 dict 类型子字段。

    与原 `result.get(key) or {}` 模式的差异：
      - 原模式：值为 falsy（0、""、[]、None、{}）一律替换为 {}，掩盖上游返回错误类型。
      - 本函数：仅当值为 dict 时透传；缺失/None 静默返回 {}（兼容字段尚未生成的情况）；
        其他非 dict 类型记录 warning 暴露上游结构异常，再返回 {} 保证下游格式化不崩。

    设计说明：
        本函数定位为"展示层防御"，不抛异常——_log_summary 的职责是尽力打印摘要，
        即使部分字段类型异常也不应阻断整体日志。类型不一致由 warning 通道暴露给运维。
    """
    value = result.get(key)
    if isinstance(value, dict):
        return value
    if value is not None:
        logger.warning("结果字段 %r 类型异常，期望 dict，实际 %s（值已忽略）", key, type(value).__name__)
    return {}


def _log_summary(result: dict) -> None:
    """格式化并打印 IC 计算结果摘要 + 空值告警。

    职责（与 main 解耦）：
      1. 从 result 提取 ic_metrics / sample_stats / period / ic_distribution 字段；
      2. 先发出空值 warning（顺序在摘要之前，避免读者先看到 N/A 再看到原因）；
      3. 打印结果摘要 INFO 日志。

    参数:
        result: run_factor_ic 返回的结果字典（结构由 ic_result_builder.build_ic_result 定义）。

    设计说明:
        本函数仅负责"展示"，不做任何业务决策、不抛业务异常；result 为 None 的判断
        由调用方 main() 在执行流程编排阶段完成。
    """
    ic_metrics = _safe_dict(result, _KEY_IC_METRICS)
    sample_stats = _safe_dict(result, _KEY_SAMPLE_STATS)
    period = _safe_dict(result, _KEY_PERIOD)
    ic_distribution = _safe_dict(result, _KEY_IC_DISTRIBUTION)

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


def main():
    """CLI 主入口

    职责（单一）：
      1. 解析命令行参数；
      2. 编排流程：调用 run_factor_ic → 校验非空 → 委托 _log_summary 展示。

    格式化与日志展示已委托给 _log_summary，main 不再关心字段提取与摘要拼接。
    """
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

    _log_summary(result)
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
