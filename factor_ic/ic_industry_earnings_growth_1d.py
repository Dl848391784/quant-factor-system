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
            factor_name="industry_earnings_growth",
            factor_col="industry_earnings_growth",
            calculation=calculate_industry_earnings_growth,
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
    # - 该 trade-off 见 ic_industry_earnings_growth_main_cleanup_design.md §11。
    # - 截断策略（消除中间变量 + 固定截断标记，对齐 ic_industry_momentum_5d_1d.py R3 范式）：
    #   str(e)[:200] 直接内联到 logger 实参，格式串中固定追加
    #   "(truncated to <=200 chars)" 显式告知阅读者本字段可能被截断。
    logger.critical(
        "FactorSpec 注册失败 (factor=industry_earnings_growth): %s (%s) (truncated to <=200 chars)",
        str(e)[:200],
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
        logger=logger,
    )

    # 包裹 log_factor_summary：摘要层失败 → sys.exit(3) 显式辅助层失败信号
    # （PROJECT.md H12 R17）。因子计算 result 已成功生成，主结果产物可用，下游
    # backtest/comprehensive/summary 可正常消费；仅旁路日志摘要失败时返回 exit 3，
    # 与业务失败（exit 1）和 import-time 注册失败（exit 2）严格区分。
    try:
        log_factor_summary(result, "行业盈利增长因子", logger)
    except Exception:
        logger.exception(
            "log_factor_summary 摘要输出阶段失败（因子计算 result 已成功生成；"
            "故障源 = 摘要日志层而非 run_factor_ic 业务路径）"
        )
        sys.exit(3)  # H12 R17：辅助层失败专用退出码

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
