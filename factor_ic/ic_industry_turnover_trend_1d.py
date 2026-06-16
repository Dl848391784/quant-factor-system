#!/usr/bin/env python3
"""
行业换手率趋势因子 IC 计算器 - 使用公共模块主入口

遵循 PROJECT.md 公共模块强制复用规范：
- 主流程使用 run_complex_factor_ic()（禁止手写三模式分支）
- 因子计算逻辑复用 data_fetchers.factor_calculator（遵循 MODULE.md 约束 #3）

因子定义：
- industry_turnover_trend = turnover_avg(t) / turnover_avg(t-1) - 1
- 含义：行业换手率变化趋势，方向性因子
- 遵循 H5: IC方向不预判，由数据决定

边界处理：
- industry 未知 → 赋 '其他'
- turnover_avg(t-1) 极小 → clip(lower=0.001) 避免极端比值（遵循 Pitfall #47）

作者: 云瑶
创建日期: 2026-06-12
版本历史:
  v1.0 (2026-06-12): 初始版本，复用 factor_calculator.calculate_industry_turnover_trend
"""

import argparse
import sys

from data_fetchers.factor_calculator import calculate_industry_turnover_trend
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
# 注册失败 raise 中断模块加载（不会进入未绑定状态，无需 None 初值）。
try:
    SPEC = register_factor(
        FactorSpec(
            factor_name="industry_turnover_trend",
            factor_col="industry_turnover_trend",
            calculation=calculate_industry_turnover_trend,
        )
    )
except (ValueError, TypeError) as e:
    # 模块顶层注册失败兜底（R17 同步迁移）：
    # - register_factor 抛 ValueError（factor_spec.py:117-119：重复注册、列名非法等）
    # - TypeError 防御 FactorSpec dataclass 构造期类型错误
    # - R17 改为 logger.critical + raise（详见 PROJECT.md H12 R16 修正版）：
    #   importlib.import_module 在 test_factor_spec_consistency.py 中扫描所有 ic_*.py
    #   触发 SPEC 注册，sys.exit 会杀掉 pytest 宿主；raise 让调用方决定行为。
    err_msg = str(e)[:200]  # 截断避免超长异常淹没单行日志
    logger.critical(
        "FactorSpec 注册失败 (factor=industry_turnover_trend): %s (%s)",
        err_msg,
        type(e).__name__,
    )
    raise


def main():
    """CLI 主入口"""
    parser = argparse.ArgumentParser(description="行业换手率趋势因子 IC 计算器")
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
    log_factor_summary(result, "行业换手率趋势因子", logger)


if __name__ == "__main__":
    # 异常分支顺序依据（exceptions.py L27/L46 已确认）：
    # - DataSchemaError(Exception) 与 FactorCalcError(Exception) 均直接继承 Exception，
    #   两者是【平级关系，无父子继承】（exceptions.py L60 注释也明确"与 FactorCalcError 并列"）。
    # - 因此 DataSchemaError ↔ FactorCalcError 的捕获顺序在异常匹配上等价，无主次之分。
    # - 当前先 DataSchemaError 后 FactorCalcError 的顺序仅为可读性约定（按错误来源远近排序：
    #   schema 失败发生在数据加载阶段（最早），因子计算失败发生在加载之后），
    #   未来调整顺序不会改变捕获语义。
    # - 通用 Exception 必须放最后，作为非业务异常的兜底（程序 bug → CRITICAL 告警语义）。
    try:
        main()
    except DataSchemaError as e:
        # run_factor_ic 文档（factor_ic_runner.py L460-461）声明 required_columns 与
        # 数据源列不匹配时抛 DataSchemaError；单独捕获以保留 schema 失败的明确语义，
        # 避免落入通用 Exception 分支后丢失"列依赖不匹配"这一关键上下文。
        logger.error("行业换手率趋势因子IC计算失败 (数据列依赖不匹配): %s", e)
        sys.exit(1)
    except FactorCalcError as e:
        logger.error("行业换手率趋势因子IC计算失败: %s", e)
        sys.exit(1)
    except Exception:
        logger.exception("未预期的错误")
        sys.exit(1)
