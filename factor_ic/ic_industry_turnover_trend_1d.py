#!/usr/bin/env python3
"""
行业换手率趋势因子 IC 计算器 - 使用公共模块主入口

遵循 PROJECT.md 公共模块强制复用规范：
- 主流程使用 run_factor_ic()（FactorSpec 驱动统一入口，已替代 run_simple/run_complex；
  详见 factor_ic/MODULE.md：禁止继续使用 run_complex_factor_ic，全部脚本已迁移）
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
from factor_ic.common.factor_spec import FactorSpec, SpecRegistrationError, register_factor
from factor_ic.common.factor_summary_logger import log_factor_summary
from factor_ic.common.logger_config import get_logger


logger = get_logger(__name__)

# ============================================================================
# FactorSpec 声明式注册（遵循 factor_cols_literal_constant_design.md §4.1）
# ============================================================================

SPEC = None  # 防止注册失败 raise 传播期间 SPEC 处于未定义状态导致 NameError

try:
    SPEC = register_factor(
        FactorSpec(
            factor_name="industry_turnover_trend",
            factor_col="industry_turnover_trend",
            calculation=calculate_industry_turnover_trend,
        )
    )
except SpecRegistrationError as e:
    # 模块顶层注册失败兜底（R4-min 收紧版，对齐 ic_industry_momentum_5d_1d.py R3 范式）：
    # - SpecRegistrationError = register_factor 包装层统一抛出的注册期异常
    #   （继承 ValueError，封装重复注册、列名非法、FactorSpec dataclass 构造期 TypeError 等）。
    # - importlib.import_module 在 test_factor_spec_consistency.py 中扫描所有 ic_*.py
    #   触发 SPEC 注册，sys.exit 会杀掉 pytest 宿主；改 raise 让调用方决定行为。
    # - str(e)[:200] 截断策略：防止单条日志过长；截断标记仅在注释中说明，
    #   不混入日志消息体以免污染结构化解析。
    logger.critical(
        "FactorSpec 注册失败 (factor=industry_turnover_trend): %s (%s)",
        str(e)[:200],
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
        logger=logger,
    )

    # 包裹 log_factor_summary：摘要层失败 → sys.exit(3)
    # （H12 R17 要求：辅助层失败用退出码 3，与业务失败 exit 1 / 注册失败 exit 2 区分）。
    # 因子计算 result 已成功生成，主结果产物可用，下游可正常消费。
    try:
        log_factor_summary(result, "行业换手率趋势因子", logger)
    except Exception:
        logger.exception(
            "log_factor_summary 摘要输出阶段失败（因子计算 result 已成功生成；"
            "故障源 = 摘要日志层而非 run_factor_ic 业务路径）"
        )
        sys.exit(3)


if __name__ == "__main__":
    # DataSchemaError 与 FactorCalcError 平级（均直接继承 Exception），捕获顺序等价
    try:
        main()
    except DataSchemaError:
        logger.exception("行业换手率趋势因子IC计算失败 (数据列依赖不匹配)")
        sys.exit(4)  # schema 失败，退出码 4 供 shell 脚本区分数据问题
    except FactorCalcError:
        logger.exception("行业换手率趋势因子IC计算失败")
        sys.exit(5)  # 因子计算失败，退出码 5 供 shell 脚本区分计算逻辑问题
    except Exception:
        logger.exception("未预期的错误")
        sys.exit(1)
