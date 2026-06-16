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
  v1.2 (2026-06-16): None返回补warning/SummaryLogError改error+cause/or{}改is not None/日志去冗余/FactorCalcError补上下文
  v1.3 (2026-06-16): 抽取_build_parser消除重复解析/删除__main__重复日志/ic_metrics风格统一/去重复result.get
  v1.4 (2026-06-16): args类型放宽namespace-like/检查点debug→info去重/_cli_args提取为独立变量
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


def _build_parser():
    """构建 CLI 参数解析器（main() 与 __main__ 共享，消除重复定义）。"""
    parser = argparse.ArgumentParser(description="行业PE趋势因子 IC 计算器")
    parser.add_argument("--force-full", action="store_true", help="强制全量计算")
    parser.add_argument("--min-stocks", type=int, default=DEFAULT_MIN_STOCKS, help="最小股票数")
    return parser


def main(args=None):
    """CLI 主入口

    Parameters
    ----------
    args : namespace-like | None
        CLI 参数。None 时内部解析 sys.argv（仅 CLI 调用场景）。
        库函数调用方可传入任何含 ``min_stocks`` 和 ``force_full``
        属性的对象（如 ``argparse.Namespace`` 或自定义 dataclass），
        不限于 ``argparse.Namespace``。

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

    if args is None:
        args = _build_parser().parse_args()

    # 启动横幅由公共模块 factor_ic_runner 统一打印（含 min_stocks/force_full）
    result = run_factor_ic(
        spec=SPEC,
        min_stocks=args.min_stocks,
        force_full=args.force_full,
        logger=logger,
    )

    # None 检查：记录上下文后返回 None，由调用方（__main__ 块或库函数调用方）决定处理方式
    # （R20: main() 作为库函数不应抛业务异常泄露，但需留痕便于库调用场景排查）
    if result is None:
        logger.warning(
            "run_factor_ic 返回 None（factor=%s, min_stocks=%s, force_full=%s），数据加载或计算可能失败",
            SPEC.factor_name,
            args.min_stocks,
            args.force_full,
        )
        return None

    # 计算完成检查点日志：保留 log_factor_summary 未覆盖的维度信息（日期范围、更新模式）
    # 使用中间变量避免同一 key 重复调用 result.get()
    _period = result.get("period")
    period = _period if _period is not None else {}
    logger.info(
        "run_factor_ic 完成: 日期范围=%s~%s, 更新模式=%s",
        period.get("start", "N/A"),
        period.get("end", "N/A"),
        result.get("update_mode", "N/A"),
    )

    # log_factor_summary 失败时 raise SummaryLogError 而非 sys.exit(3)
    # （R20: main() 体内禁 sys.exit，必须 raise 让 __main__ 块统一处理退出码）
    try:
        log_factor_summary(result, "行业PE趋势因子", logger)
    except Exception as e:
        raise SummaryLogError(
            "log_factor_summary 摘要输出阶段失败（因子计算 result 已成功生成；"
            "故障源 = 摘要日志层而非 run_factor_ic 业务路径）"
        ) from e

    # 替换冗余的"计算完成"日志为包含关键指标的有效信息
    _ic_metrics = result.get("ic_metrics")
    ic_metrics = _ic_metrics if _ic_metrics is not None else {}
    ic_mean = ic_metrics.get("ic_mean")
    icir = ic_metrics.get("icir")
    ic_mean_str = f"{ic_mean:.4f}" if ic_mean is not None else "N/A"
    icir_str = f"{icir:.2f}" if icir is not None else "N/A"
    logger.info(
        "行业PE趋势因子IC计算完成: IC均值=%s, ICIR=%s",
        ic_mean_str,
        icir_str,
    )
    return result


if __name__ == "__main__":
    # 共享 _build_parser()，sys.argv 只解析一次，结果传入 main()
    _cli_args = _build_parser().parse_args()
    # 在 try 块前提取上下文字段，except 块不依赖 _cli_args 作用域位置
    _cli_min_stocks = _cli_args.min_stocks
    _cli_force_full = _cli_args.force_full

    try:
        result = main(args=_cli_args)
        # main() 内已打 warning 留痕，此处仅负责退出码映射
        if result is None:
            sys.exit(5)
    except DataSchemaError as e:
        # 数据 Schema 校验失败（公共模块 validate_required_columns 抛出）：
        # H12 R18 → exit 4 与因子计算失败（exit 5）严格区分。
        # MODULE.md M22：业务异常用 logger.error 不打堆栈。
        logger.error("数据 Schema 校验失败 (factor=%s): %s", e.factor_name, e)
        sys.exit(4)  # H12 R18: schema 失败 → 检查上游数据
    except SummaryLogError as e:
        # 辅助层失败（R17），因子计算 result 已成功生成
        # 主结果产物可用，下游 backtest/comprehensive/summary 可正常消费；
        # 仅旁路日志摘要失败时返回 exit 3
        # M22: 业务异常子类不打完整堆栈，只打印核心原因（e.__cause__）
        cause_msg = str(e.__cause__) if e.__cause__ else "未知原因"
        logger.error(
            "摘要输出阶段失败（因子计算 result 已成功生成；故障源 = 摘要日志层；原因: %s）",
            cause_msg,
        )
        sys.exit(3)  # H12 R17：辅助层失败专用退出码
    except FactorCalcError as e:
        logger.error(
            "行业PE趋势因子IC计算失败 (factor=%s, min_stocks=%s, force_full=%s): %s",
            SPEC.factor_name,
            _cli_min_stocks,
            _cli_force_full,
            e,
        )
        sys.exit(5)  # H12 R19: 因子计算失败 → 检查计算代码
    except Exception:
        logger.exception("未预期的错误")
        sys.exit(1)
