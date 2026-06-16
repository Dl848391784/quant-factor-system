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
from factor_ic.common.exceptions import FactorCalcError
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
        factor_name="industry_earnings_growth",
        factor_col="industry_earnings_growth",
        calculation=calculate_industry_earnings_growth,
    )
)


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

    if result is None:
        raise FactorCalcError("run_factor_ic 返回 None，数据加载或计算可能失败")

    # 输出 IC 摘要 + None 状态整合告警（公共模块,M3.1）
    log_factor_summary(result, "行业盈利增长因子", logger)

    logger.info("行业盈利增长因子IC计算完成")
    return result


if __name__ == "__main__":
    try:
        main()
    except FactorCalcError as e:
        logger.error("行业盈利增长因子IC计算失败: %s", e)
        sys.exit(1)
    except Exception:
        logger.exception("未预期的错误")
        sys.exit(1)
