#!/usr/bin/env python3
"""
行业盈利增长因子 IC 计算器 - 使用公共模块主入口

遵循 PROJECT.md 公共模块强制复用规范：
- 主流程使用 run_complex_factor_ic()（禁止手写三模式分支）
- 因子计算逻辑复用 data_fetchers.factor_calculator（遵循 MODULE.md 约束 #3）

因子定义：
- industry_earnings_growth = 行业净利润增长率赋个股（季度数据前推填充，行业聚合赋给同行业每只股票）
- 含义：行业基本面盈利增长趋势，方向性因子
- 遵循 H5: IC方向不预判，由数据决定

边界处理：
- industry 未知 → 赋 '其他' 行业
- 净利润增长率缺失 → 因子值 NaN
- 季度财务数据前推填充对齐日频

作者: 云瑶
创建日期: 2026-06-12
版本历史:
  v1.0 (2026-06-12): 初始版本，复用 factor_calculator.calculate_industry_earnings_growth
"""

import argparse
import sys

from data_fetchers.factor_calculator import calculate_industry_earnings_growth
from factor_ic.common.cli_helpers import DEFAULT_MIN_STOCKS
from factor_ic.common.exceptions import DataSchemaError, FactorCalcError
from factor_ic.common.factor_ic_runner import run_factor_ic
from factor_ic.common.factor_spec import FactorSpec, register_factor
from factor_ic.common.factor_summary_logger import log_factor_summary
from factor_ic.common.logger_config import get_logger


logger = get_logger(__name__)

# ============================================================================
# FactorSpec 声明式注册（遵循 factor_cols_literal_constant_design.md §4.1）
# ============================================================================

SPEC: FactorSpec  # noqa: F842 — 仅类型注解；下方 try 块在 import-time 完成赋值，
# 注册失败会 raise 抛出异常中断模块加载（不会进入未绑定状态，故无需赋初值 None）。
try:
    SPEC = register_factor(
        FactorSpec(
            factor_name="industry_earnings_growth",
            factor_col="industry_earnings_growth",
            calculation=calculate_industry_earnings_growth,
        )
    )
except (ValueError, TypeError) as e:
    # 模块顶层注册失败兜底（fix #5 + R13 调整）：
    # - register_factor 文档声明 Raises: ValueError（factor_spec.py:117-119，含重复注册、
    #   required_columns 为空、列名非法、factor_col 不在 required_columns 中等）。
    # - TypeError 防御 FactorSpec dataclass 构造期的字段类型错误（虽属于代码 bug，
    #   仍以可观测方式记录后再抛出）。
    # - 行为变化（R13）：先前在此处 sys.exit(2) 退出，但
    #   factor_ic/common/test_factor_spec_consistency.py 通过 importlib.import_module
    #   扫描所有 ic_*.py 触发 SPEC 注册，sys.exit 会直接杀掉 pytest 宿主进程，
    #   与"测试通过 importlib 触发注册"路径自相矛盾。
    # - 现改为 logger.critical 后 raise：
    #   * 测试场景 → import_module 抛 ValueError/TypeError，测试可捕获/断言/skip；
    #   * CLI 场景（python ic_industry_earnings_growth_1d.py）→ Python 解释器
    #     打印 traceback 后默认 exit 1（不再是 exit 2，trade-off：放弃
    #     import-time/runtime 退出码区分 换取 测试可隔离性）。
    # - 该 trade-off 见 ic_industry_earnings_growth_main_cleanup_design.md §11。
    err_msg = str(e)[:200]  # 截断 200 字符：避免超长异常消息（如全量列名列表）淹没单行日志，
    # 与 logger_config 默认 console formatter 单行可读性边界一致。
    logger.critical(
        "FactorSpec 注册失败 (factor=industry_earnings_growth): %s (%s)",
        err_msg,
        type(e).__name__,
    )
    raise


def main():
    """CLI 主入口"""
    parser = argparse.ArgumentParser(description="行业盈利增长因子 IC 计算器")
    parser.add_argument("--force-full", action="store_true", help="强制全量计算")
    parser.add_argument("--min-stocks", type=int, default=DEFAULT_MIN_STOCKS, help="最小股票数")
    args = parser.parse_args()

    # 启动横幅由公共模块 factor_ic_runner 统一打印（含 min_stocks/force_full）
    result = run_factor_ic(
        spec=SPEC,
        min_stocks=args.min_stocks,
        force_full=args.force_full,
        _logger=logger,
    )

    # 输出 IC 摘要（公共模块,M3.1）
    # 注：run_factor_ic 失败路径走 build_error_result（返回 dict）或抛 DataSchemaError，
    # 永不返回 None；冗余的 result is None 兜底掩盖真实错误来源（违反 dead-code skill
    # 模式 E：防御 is None 兜底面对永不返回 None 的函数），已彻底移除。
    # log_factor_summary 自身契约（factor_summary_logger.py L40-44）：不抛异常、不调用
    # sys.exit、不影响调用方控制流；其内部对 dict 字段为 None 的异常情况输出整合告警
    # （L83-92），无需调用方额外守卫。
    log_factor_summary(result, "行业盈利增长因子", logger)

    # 流程完成标记（R15 补回）：
    # - 与 log_factor_summary 的【数据摘要】职责正交：本日志只标记 main() 正常走完，
    #   运维侧 grep '行业盈利增长因子IC计算完成' 可确认进程未在 log_factor_summary
    #   之后异常退出。
    # - 历史：上一轮 R1 曾以"与 log_factor_summary 重叠"为由删除，本轮认知修正：
    #   数据摘要 ≠ 流程完成标记。前者描述"算了什么"，后者描述"走到了哪一步"。
    logger.info("行业盈利增长因子IC计算完成")


if __name__ == "__main__":
    # 异常分支设计（R14 简化）：
    # - DataSchemaError 与 FactorCalcError 均直接继承 Exception（exceptions.py L27/L46/L60），
    #   平级无父子继承；先前拆为两个 except 分支但前缀+退出码完全相同，属结构冗余。
    # - 现合并为 except (DataSchemaError, FactorCalcError)，统一打印+退出，行号即语义来源。
    # - 通用 Exception 必须放最后，作为非业务异常的兜底（程序 bug → CRITICAL 告警语义）。
    try:
        main()
    except (DataSchemaError, FactorCalcError) as e:
        logger.error("行业盈利增长因子IC计算失败: %s (%s)", e, type(e).__name__)
        sys.exit(1)
    except Exception:
        logger.exception("未预期的错误")
        sys.exit(1)
