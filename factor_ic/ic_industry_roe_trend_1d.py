#!/usr/bin/env python3
"""
行业ROE趋势因子 IC 计算器 - 使用公共模块主入口

遵循 PROJECT.md 公共模块强制复用规范：
- 主流程使用 run_factor_ic()（FactorSpec 驱动入口，禁止手写三模式分支）
- 因子计算逻辑复用 data_fetchers.factor_calculator（遵循 MODULE.md 约束 #3）

因子定义：
- industry_roe_trend = 行业ΔROE赋个股（季度间ROE变化量，行业聚合赋给同行业每只股票）
- 含义：行业基本面盈利能力趋势，方向性因子
- 遵循 H5: IC方向不预判，由数据决定

退出码语义（遵循 PROJECT.md H12）：
  0 = 成功
  1 = 未预期错误（程序 bug；R20 main() 体内禁 sys.exit）
  3 = 辅助层失败（计算成功，但日志摘要/监控输出失败；R17）
  4 = DataSchemaError（数据 schema 不匹配，需检查上游列契约；R18）
  5 = FactorCalcError（因子计算内部失败，需检查计算代码；R19）

边界处理：
- industry 未知 → 赋 '其他' 行业
- ROE 数据缺失 → ΔROE 为 NaN
- 季度财务数据前推填充对齐日频

作者: 云瑶
创建日期: 2026-06-12
版本历史:
  v1.0 (2026-06-12): 初始版本，复用 factor_calculator.calculate_industry_roe_trend
  v1.1 (2026-06-16): 7项修复——result接收/None检查+warning/SummaryLogError/getattr防御/
                     SpecRegistrationError兜底/启动日志/完成日志补统计量
"""

import argparse
import sys

from data_fetchers.factor_calculator import calculate_industry_roe_trend
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

try:
    SPEC = register_factor(
        FactorSpec(
            factor_name="industry_roe_trend",
            factor_col="industry_roe_trend",
            calculation=calculate_industry_roe_trend,
        )
    )
except SpecRegistrationError as e:
    # 模块顶层注册失败兜底（R4-min 收紧版）：
    # - SpecRegistrationError = register_factor 包装层统一抛出的注册期异常
    #   （继承 ValueError，封装重复注册、required_columns 为空、列名非法、
    #   factor_col 不在 required_columns 中、FactorSpec dataclass 构造期 TypeError 等）。
    # - 行为变化（R13）：先前 sys.exit(2) 退出，但 test_factor_spec_consistency.py
    #   通过 importlib.import_module 扫描所有 ic_*.py 触发 SPEC 注册，sys.exit
    #   会直接杀掉 pytest 宿主进程，与"测试通过 importlib 触发注册"路径自相矛盾。
    # - 现改为 logger.critical 后 raise：
    #   * 测试场景 → import_module 抛 SpecRegistrationError，测试可捕获/断言/skip；
    #   * CLI 场景 → Python 解释器打印 traceback 后默认 exit 1（trade-off：放弃
    #     import-time/runtime 退出码区分 换取 测试可隔离性）。
    logger.critical(
        "FactorSpec 注册失败 (factor=industry_roe_trend): %s (%s) (truncated to <=200 chars)",
        str(e)[:200],
        type(e).__name__,
    )
    raise


def _build_parser():
    """构建 CLI 参数解析器（main() 与 __main__ 共享，消除重复定义）。"""
    parser = argparse.ArgumentParser(description="行业ROE趋势因子 IC 计算器")
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
    # 本地启动参数日志：补充模块日志流可追溯入参（与公共横幅互补）
    logger.info(
        "启动 run_factor_ic: factor=%s min_stocks=%d force_full=%s",
        SPEC.factor_name,
        args.min_stocks,
        args.force_full,
    )
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
    # 因子计算 result 已成功生成，主结果产物可用；仅旁路日志摘要失败
    try:
        log_factor_summary(result, "行业ROE趋势因子", logger)
    except Exception as e:
        # 结构化警告：因子产物已生成，仅摘要层失败（便于监控系统过滤）
        logger.warning(
            "因子产物已生成，仅摘要层失败（factor=%s）",
            SPEC.factor_name,
        )
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
        "行业ROE趋势因子IC计算完成: IC均值=%s, ICIR=%s",
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
        # getattr 防御：虽然 DataSchemaError.__init__ 强制传 factor_name，
        # 但子类化/反序列化/未来重构可能丢失该属性，防御性兜底避免 AttributeError
        # 导致落入通用 Exception 以 exit(1) 退出（非预期的 exit 4 路径）。
        logger.error(
            "数据 Schema 校验失败 (factor=%s): %s",
            getattr(e, "factor_name", "unknown"),
            e,
        )
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
            "行业ROE趋势因子IC计算失败 (factor=%s, min_stocks=%s, force_full=%s): %s",
            SPEC.factor_name,
            _cli_min_stocks,
            _cli_force_full,
            e,
        )
        sys.exit(5)  # H12 R19: 因子计算失败 → 检查计算代码
    except Exception:
        logger.exception("未预期的错误")
        sys.exit(1)
