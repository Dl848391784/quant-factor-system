#!/usr/bin/env python3
"""
换手突增差分因子 IC 计算器 - 使用公共模块主入口

遵循 PROJECT.md 公共模块强制复用规范：
- 主流程使用 run_complex_factor_ic()（禁止手写三模式分支）
- 因子计算逻辑复用 data_fetchers.factor_calculator（遵循 MODULE.md 约束 #3）

因子定义：
- turnover_surge_delta = turnover_surge(T) - turnover_surge(T-1)
- 含义：换手从低开始增加 = 市场关注回升；继续下降 = 无人关注
- 遵循 H5: IC方向不预判，由数据决定

边界处理：
- 第一日无前值 → NaN（自然排除）
- turnover_surge 为 NaN → delta 也为 NaN（传播）

作者: 云瑶
创建日期: 2026-06-11
版本历史:
  v1.0 (2026-06-11): 初始版本，复用 factor_calculator.calculate_turnover_surge_delta
"""

import argparse
import sys

# 添加项目路径
# 导入公共模块主入口（遵循 PROJECT.md 强制复用规范）
from data_fetchers.factor_calculator import calculate_turnover_surge_delta
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
        factor_name="turnover_surge_delta",
        factor_col="turnover_surge_delta",
        calculation=calculate_turnover_surge_delta,
    )
)

# ============================================================================
# 自定义异常类
# ============================================================================
# ============================================================================
# CLI 入口
# ============================================================================


def main():
    """CLI 主入口"""

    parser = argparse.ArgumentParser(description="换手突增差分因子 IC 计算器")
    parser.add_argument("--force-full", action="store_true", help="强制全量计算")
    parser.add_argument("--min-stocks", type=int, default=DEFAULT_MIN_STOCKS, help="最小股票数")

    args = parser.parse_args()

    # 启动横幅由公共模块 factor_ic_runner 统一打印（含 min_stocks/force_full）
    # 使用 FactorSpec 驱动入口（遵循 factor_cols_literal_constant_design.md §4.1）
    result = run_factor_ic(
        spec=SPEC,
        min_stocks=args.min_stocks,
        force_full=args.force_full,
        _logger=logger,
    )

    # 防御性检查：result 为 None 时抛出业务异常
    if result is None:
        raise FactorCalcError("run_factor_ic 返回 None，数据加载或计算可能失败")

    # 输出 IC 摘要 + None 状态整合告警（公共模块,M3.1）
    log_factor_summary(result, "换手突增差分因子", logger)

    logger.info("换手突增差分因子IC计算完成")

    return result


if __name__ == "__main__":
    try:
        main()
    except FactorCalcError as e:
        logger.error("换手突增差分因子IC计算失败: %s", e)
        sys.exit(1)
    except Exception:
        logger.exception("未预期的错误")
        sys.exit(1)
