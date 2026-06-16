#!/usr/bin/env python3
"""
行业振幅趋势因子 IC 计算器 - 使用公共模块主入口

遵循 PROJECT.md 公共模块强制复用规范：
- 主流程使用 run_factor_ic()（FactorSpec 驱动入口，禁止手写三模式分支；
  factor_ic_runner.py L433 推荐入口，替代 run_simple_factor_ic / run_complex_factor_ic）
- 因子计算逻辑复用 data_fetchers.factor_calculator（遵循 MODULE.md 约束 #3）

因子定义：
- industry_amplitude_trend = amplitude_avg(t) / amplitude_avg(t-1) - 1
- 含义：行业振幅变化趋势，方向性因子
- 遵循 H5: IC方向不预判，由数据决定

边界处理：
- industry 未知 → 赋 '其他'
- amplitude_avg(t-1) 极小 → clip(lower=0.001) 避免极端比值（遵循 Pitfall #47）

作者: 云瑶
创建日期: 2026-06-12
版本历史:
  v1.0 (2026-06-12): 初始版本，复用 factor_calculator.calculate_industry_amplitude_trend
"""

import argparse
import sys

from data_fetchers.factor_calculator import calculate_industry_amplitude_trend
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

SPEC = register_factor(
    FactorSpec(
        factor_name="industry_amplitude_trend",
        factor_col="industry_amplitude_trend",
        # required_columns 缺省说明（遵循 factor_spec.py v1.1 §3.1 方案 3-A）：
        # 1. FactorSpec.required_columns 为可选字段（factor_spec.py L63: tuple[str, ...] | None = None）。
        # 2. 缺省时由 __post_init__ 自动派生：读取 calculation.required_cols 属性
        #    （factor_spec.py L72；本因子已验证 calculate_industry_amplitude_trend.required_cols
        #    = ['date', 'asset', 'amplitude']）。
        # 3. 因此本处省略 required_columns 是合规的，等价于显式声明
        #    required_columns=JOIN_KEYS + ("amplitude",)；产出列 industry_amplitude_trend
        #    不属于输入依赖（factor_spec.py L98-102: 有 calculation 时 factor_col 是计算产出）。
        calculation=calculate_industry_amplitude_trend,
    )
)


def main():
    """CLI 主入口"""
    parser = argparse.ArgumentParser(description="行业振幅趋势因子 IC 计算器")
    parser.add_argument("--force-full", action="store_true", help="强制全量计算")
    parser.add_argument("--min-stocks", type=int, default=DEFAULT_MIN_STOCKS, help="最小股票数")
    args = parser.parse_args()

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
        _logger=logger,
    )

    # 输出 IC 摘要 + None 状态整合告警（公共模块,M3.1）
    # 注：run_factor_ic 失败路径走 build_error_result（返回 dict）或抛 DataSchemaError，
    # 不会返回 None；冗余的 result is None 兜底掩盖真实错误来源，已移除。
    # log_factor_summary 作为流程终结的唯一日志出口，避免与其重复的"计算完成"语义。
    log_factor_summary(result, "行业振幅趋势因子", logger)

    return result


if __name__ == "__main__":
    try:
        main()
    except DataSchemaError as e:
        # run_factor_ic 文档（factor_ic_runner.py L460-461）声明 required_columns 与
        # 数据源列不匹配时抛 DataSchemaError；单独捕获以保留 schema 失败的明确语义，
        # 避免落入通用 Exception 分支后丢失"列依赖不匹配"这一关键上下文。
        logger.error("行业振幅趋势因子IC计算失败 (数据列依赖不匹配): %s", e)
        sys.exit(1)
    except FactorCalcError as e:
        logger.error("行业振幅趋势因子IC计算失败: %s", e)
        sys.exit(1)
    except Exception:
        logger.exception("未预期的错误")
        sys.exit(1)
