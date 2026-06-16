#!/usr/bin/env python3
"""
行业PE趋势因子 IC 计算器 - 使用公共模块主入口

遵循 PROJECT.md 公共模块强制复用规范：
- 主流程使用 run_complex_factor_ic()（禁止手写三模式分支）
- 因子计算逻辑复用 data_fetchers.factor_calculator（遵循 MODULE.md 约束 #3）

因子定义：
- industry_pe_trend = 行业ΔPE赋个股（PE季度间变化量，行业聚合赋给同行业每只股票）
- PE = close / annualized_eps（分母clip保护，遵循 Pitfall #47）
- 含义：行业估值趋势变化，方向性因子
- 遵循 H5: IC方向不预判，由数据决定

退出码语义（遵循 PROJECT.md H12）：
  0 = 成功
  1 = 未预期错误（程序 bug；R20 main() 体内禁 sys.exit）
  3 = 辅助层失败（计算成功，但日志摘要/监控输出失败；R17）
  4 = DataSchemaError（数据 schema 不匹配，需检查上游列契约；R18）
  5 = FactorCalcError（因子计算内部失败，需检查计算代码；R19）

边界处理：
- industry 未知 → 赋 '其他' 行业
- eps ≤ 0 → PE = NaN（分母保护）
- 季度财务数据前推填充对齐日频

作者: 云瑶
创建日期: 2026-06-12
版本历史:
  v1.0 (2026-06-12): 初始版本，复用 factor_calculator.calculate_industry_pe_trend
  v1.1 (2026-06-16): 修复退出码表/None检查/sys.exit/参数命名/日志问题
"""

import argparse
import sys

from data_fetchers.factor_calculator import calculate_industry_pe_trend
from factor_ic.common.cli_helpers import DEFAULT_MIN_STOCKS
from factor_ic.common.exceptions import DataSchemaError, FactorCalcError, SummaryLogError
from factor_ic.common.factor_ic_runner import run_factor_ic
from factor_ic.common.factor_spec import FactorSpec, register_factor
from factor_ic.common.factor_summary_logger import log_factor_summary
from factor_ic.common.logger_config import get_logger


logger = get_logger(__name__)

# ============================================================================
# FactorSpec 声明式注册（遵循 factor_cols_literal_constant_design.md §4.1）
# ============================================================================

SPEC = register_factor(
    FactorSpec(
        factor_name="industry_pe_trend",
        factor_col="industry_pe_trend",
        calculation=calculate_industry_pe_trend,
    )
)


def main():
    """CLI 主入口

    Returns
    -------
    dict | None
        run_factor_ic 的完整结果字典。None 表示数据加载或计算失败，
        由调用方（__main__ 块或库函数调用方）检查并处理。

    Raises
    ------
    SummaryLogError
        log_factor_summary 摘要输出阶段失败（因子计算 result 可能已成功生成）。
        由 __main__ 块捕获并映射为 exit 3（R17 辅助层失败）。
    DataSchemaError
        数据 schema 校验失败，由 __main__ 块映射为 exit 4（R18）。
    Exception
        其他未预期异常原样传播。
    """

    parser = argparse.ArgumentParser(description="行业PE趋势因子 IC 计算器")
    parser.add_argument("--force-full", action="store_true", help="强制全量计算")
    parser.add_argument("--min-stocks", type=int, default=DEFAULT_MIN_STOCKS, help="最小股票数")
    args = parser.parse_args()

    # 启动横幅由公共模块 factor_ic_runner 统一打印（含 min_stocks/force_full）
    result = run_factor_ic(
        spec=SPEC,
        min_stocks=args.min_stocks,
        force_full=args.force_full,
        logger=logger,
    )

    # #2 修复：None 检查移入 __main__ 块（R20: main() 作为库函数不应抛业务异常泄露）
    # 此处仅返回 result（可能为 None），由调用方决定如何处理
    if result is None:
        return None

    # #6 修复：计算完成检查点日志（含 result 基本维度，便于生产排查）
    sample_stats = result.get("sample_stats") or {}
    period = result.get("period") or {}
    logger.debug(
        "run_factor_ic 完成: 有效天数=%s, 日期范围=%s~%s, 更新模式=%s",
        sample_stats.get("valid_days", "N/A"),
        period.get("start", "N/A"),
        period.get("end", "N/A"),
        result.get("update_mode", "N/A"),
    )

    # #3 修复：log_factor_summary 失败时 raise SummaryLogError 而非 sys.exit(3)
    # （R20: main() 体内禁 sys.exit，必须 raise 让 __main__ 块统一处理退出码）
    try:
        log_factor_summary(result, "行业PE趋势因子", logger)
    except Exception as e:
        raise SummaryLogError(
            "log_factor_summary 摘要输出阶段失败（因子计算 result 已成功生成；"
            "故障源 = 摘要日志层而非 run_factor_ic 业务路径）"
        ) from e

    # #5 修复：替换冗余的"计算完成"日志为包含关键指标的有效信息
    ic_metrics = result.get("ic_metrics") or {}
    ic_mean = ic_metrics.get("ic_mean")
    icir = ic_metrics.get("icir")
    ic_mean_str = f"{ic_mean:.4f}" if ic_mean is not None else "N/A"
    icir_str = f"{icir:.2f}" if icir is not None else "N/A"
    logger.info(
        "行业PE趋势因子IC计算完成: IC均值=%s, ICIR=%s, 有效天数=%s",
        ic_mean_str,
        icir_str,
        sample_stats.get("valid_days", "N/A"),
    )
    return result


if __name__ == "__main__":
    try:
        result = main()
        # #2 修复：None 检查从 main() 移至此处，映射为 exit 5（R19 因子计算失败）
        if result is None:
            logger.error("run_factor_ic 返回 None，数据加载或计算可能失败")
            sys.exit(5)
    except DataSchemaError as e:
        # 数据 Schema 校验失败（公共模块 validate_required_columns 抛出）：
        # H12 R18 → exit 4 与因子计算失败（exit 5）严格区分。
        # MODULE.md M22：业务异常用 logger.error 不打堆栈。
        logger.error("数据 Schema 校验失败 (factor=%s): %s", e.factor_name, e)
        sys.exit(4)  # H12 R18: schema 失败 → 检查上游数据
    except SummaryLogError:
        # #3 修复：辅助层失败（R17），因子计算 result 已成功生成
        # 主结果产物可用，下游 backtest/comprehensive/summary 可正常消费；
        # 仅旁路日志摘要失败时返回 exit 3
        logger.exception(
            "摘要输出阶段失败（因子计算 result 已成功生成；故障源 = 摘要日志层而非 run_factor_ic 业务路径）"
        )
        sys.exit(3)  # H12 R17：辅助层失败专用退出码
    except FactorCalcError as e:
        logger.error("行业PE趋势因子IC计算失败: %s", e)
        sys.exit(5)  # H12 R19: 因子计算失败 → 检查计算代码
    except Exception:
        logger.exception("未预期的错误")
        sys.exit(1)
