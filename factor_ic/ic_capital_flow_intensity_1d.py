#!/usr/bin/env python3
"""
资金流强度因子 IC 计算器 - 使用公共模块主入口

遵循 PROJECT.md 公共模块强制复用规范：
- 主流程使用 run_complex_factor_ic()（禁止手写三模式分支）
- 因子计算逻辑复用 data_fetchers.factor_calculator（遵循 MODULE.md 约束 #3）

因子定义：
- capital_flow_intensity = 行业主力流入绝对额占比赋个股（|main_inflow_amount| / total_volume，行业聚合赋给同行业每只股票）
- 含义：行业主力资金活跃度，方向性因子
- 遵循 H5: IC方向不预判，由数据决定

⚠️ 数据覆盖限制: 每只股票约120交易日（API限制），超过此范围的日期 → NaN
- 因子覆盖率约26%（仅近6个月有数据）
- 比率型因子: 分母 total_volume 可能为零 → NaN 处理

边界处理：
- industry 未知 → 赋 '其他' 行业
- total_volume = 0 或 NaN → intensity = NaN（除零保护）
- 资金流数据缺失 → intensity 为 NaN

作者: 云瑶
创建日期: 2026-06-12
版本历史:
  v1.0 (2026-06-12): 初始版本，复用 factor_calculator.calculate_capital_flow_intensity
"""

import argparse
import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).parent.parent))  # noqa: E402

from data_fetchers.factor_calculator import calculate_capital_flow_intensity  # noqa: E402
from factor_ic.common.cli_helpers import DEFAULT_MIN_STOCKS  # noqa: E402
from factor_ic.common.exceptions import FactorCalcError  # noqa: E402
from factor_ic.common.factor_ic_runner import run_complex_factor_ic  # noqa: E402
from factor_ic.common.factor_summary_logger import log_factor_summary  # noqa: E402
from factor_ic.common.logger_config import get_logger  # noqa: E402


logger = get_logger(__name__)


def main():
    """CLI 主入口"""
    parser = argparse.ArgumentParser(description="资金流强度因子 IC 计算器")
    parser.add_argument("--force-full", action="store_true", help="强制全量计算")
    parser.add_argument("--min-stocks", type=int, default=DEFAULT_MIN_STOCKS, help="最小股票数")
    args = parser.parse_args()

    logger.info(
        "启动资金流强度因子IC计算: min_stocks=%s, force_full=%s",
        args.min_stocks,
        args.force_full,
    )

    result = run_complex_factor_ic(
        factor_name="capital_flow_intensity",
        factor_col="capital_flow_intensity",
        factor_cols=["date", "asset"],
        custom_factor_calculation=calculate_capital_flow_intensity,
        min_stocks=args.min_stocks,
        force_full=args.force_full,
        _logger=logger,
    )

    if result is None:
        raise FactorCalcError("run_complex_factor_ic 返回 None，数据加载或计算可能失败")

    # 输出 IC 摘要 + None 状态整合告警（公共模块,M3.1）
    log_factor_summary(result, "资金流强度因子", logger)

    logger.info("资金流强度因子IC计算完成")
    return result


if __name__ == "__main__":
    try:
        main()
    except FactorCalcError as e:
        logger.error("资金流强度因子IC计算失败: %s", e)
        sys.exit(1)
    except Exception:
        logger.exception("未预期的错误")
        sys.exit(1)
