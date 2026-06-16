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
from factor_ic.common.exceptions import FactorCalcError
from factor_ic.common.factor_ic_runner import run_factor_ic
from factor_ic.common.factor_spec import FactorSpec, register_factor
from factor_ic.common.factor_summary_logger import log_factor_summary
from factor_ic.common.logger_config import get_logger


logger = get_logger(__name__)

# ============================================================================
# FactorSpec 声明式注册（遵循 factor_cols_literal_constant_design.md §4.1）
# ============================================================================

SPEC: FactorSpec
try:
    SPEC = register_factor(
        FactorSpec(
            factor_name="industry_turnover_trend",
            factor_col="industry_turnover_trend",
            calculation=calculate_industry_turnover_trend,
        )
    )
except (ValueError, TypeError) as e:
    # 模块顶层注册失败兜底（fix #5）：详见
    # ic_industry_earnings_growth_main_cleanup_design.md §3 退出码约定 / §4 R3。
    # - register_factor 抛 ValueError（factor_spec.py:117-119：重复注册、列名非法等）
    # - TypeError 防御 FactorSpec dataclass 构造期类型错误
    # - 退出码 2：import-time 配置错误，与 main() 运行时错误（1）区分
    logger.critical(
        "FactorSpec 注册失败 (factor=industry_turnover_trend): %s (%s)",
        str(e)[:200],
        type(e).__name__,
    )
    sys.exit(2)


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

    if result is None:
        # 错误路径职责分离：直接 logger.error + sys.exit(1)，不借道异常。
        # 注：run_factor_ic 当前实现契约为永不返回 None（失败走 build_error_result
        # 返回 dict 或抛 DataSchemaError），此分支属于防御性守卫，触发即上游契约破坏，
        # error 级别记录便于排查（参考 dead-code skill Pitfall 1 v1.0o 守卫策略）。
        logger.error("run_factor_ic 返回 None，数据加载或计算可能失败 (factor=industry_turnover_trend)")
        sys.exit(1)

    # 输出 IC 摘要（公共模块,M3.1）
    # 职责约定：None 检查由 main() 调用方提前退出（见上方 result is None 分支），
    # log_factor_summary 只处理非 None 的合法 dict 结果，并对 dict 内字段为 None 的
    # 异常情况输出整合告警（factor_summary_logger.py L83-92）。
    log_factor_summary(result, "行业换手率趋势因子", logger)


if __name__ == "__main__":
    try:
        main()
    except FactorCalcError as e:
        logger.error("行业换手率趋势因子IC计算失败: %s", e)
        sys.exit(1)
    except Exception:
        logger.exception("未预期的错误")
        sys.exit(1)
