#!/usr/bin/env python3
"""
行业5日动量因子 IC 计算器 - 使用公共模块主入口

遵循 PROJECT.md 公共模块强制复用规范：
- 主流程使用 run_complex_factor_ic()（禁止手写三模式分支）
- 因子计算逻辑复用 data_fetchers.factor_calculator（遵循 MODULE.md 约束 #3）

因子定义：
- industry_momentum_5d = 按(行业,日期)分组 → mean(past_return_1d) → 5日滚动均值
- 含义：行业整体5日趋势方向，方向性因子
- 遵循 H5: IC方向不预判，由数据决定
- 实测结论: 行业层面IC=+0.026（正值），方向性信号存在于行业而非个股

边界处理：
- industry 未知 → 赋 '其他' 行业
- 行业股票数 < 5 → 该日期该行业因子值 NaN
- past_return_1d 为 NaN → 行业均值自动跳过

作者: 云瑶
创建日期: 2026-06-12
版本历史:
  v1.0 (2026-06-12): 初始版本，复用 factor_calculator.calculate_industry_momentum_5d
"""

import argparse
import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).parent.parent))  # noqa: E402

from data_fetchers.factor_calculator import calculate_industry_momentum_5d  # noqa: E402
from factor_ic.common.cli_helpers import DEFAULT_MIN_STOCKS  # noqa: E402
from factor_ic.common.exceptions import FactorCalcError  # noqa: E402
from factor_ic.common.factor_ic_runner import run_complex_factor_ic  # noqa: E402
from factor_ic.common.factor_summary_logger import log_factor_summary  # noqa: E402
from factor_ic.common.logger_config import get_logger  # noqa: E402


logger = get_logger(__name__)


def main():
    """CLI 主入口"""
    parser = argparse.ArgumentParser(description="行业5日动量因子 IC 计算器")
    parser.add_argument("--force-full", action="store_true", help="强制全量计算")
    parser.add_argument("--min-stocks", type=int, default=DEFAULT_MIN_STOCKS, help="最小股票数")
    args = parser.parse_args()

    logger.info(
        "启动行业5日动量因子IC计算: min_stocks=%s, force_full=%s",
        args.min_stocks,
        args.force_full,
    )

    result = run_complex_factor_ic(
        factor_name="industry_momentum_5d",
        factor_col="industry_momentum_5d",
        factor_cols=["date", "asset", "close"],
        custom_factor_calculation=calculate_industry_momentum_5d,
        min_stocks=args.min_stocks,
        force_full=args.force_full,
        _logger=logger,
    )

    if result is None:
        raise FactorCalcError("run_complex_factor_ic 返回 None，数据加载或计算可能失败")

    # 输出 IC 摘要 + None 状态整合告警（公共模块,M3.1）
    log_factor_summary(result, "行业5日动量因子", logger)

    logger.info("行业5日动量因子IC计算完成")
    return result


if __name__ == "__main__":
    try:
        main()
    except FactorCalcError as e:
        logger.error("行业5日动量因子IC计算失败: %s", e)
        sys.exit(1)
    except Exception:
        logger.exception("未预期的错误")
        sys.exit(1)
