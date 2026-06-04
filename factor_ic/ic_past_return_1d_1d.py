#!/usr/bin/env python3
"""
过去1日涨幅因子 IC 计算器 - 使用公共模块主入口

遵循 PROJECT.md 公共模块强制复用规范：
- 主流程使用 run_simple_factor_ic()（预计算因子，直接读取）
- 因子数据已在 factor_generator.py 预计算，存储于 factor_ic_data.json.gz

代码量：~120行（CLI 入口 + 结果摘要 + 异常处理）。

因子定义：
- past_return_1d = close[t] / close[t-1] - 1
- 含义：过去1日涨跌幅（相对于昨日收盘价）
  - 正值 → 上涨
  - 负值 → 下跌
  - 范围：理论 [-∞, +∞)，A股日涨跌幅±10%

命名说明：
- past_return_1d = 过去1日收益（历史因子，与 forward_return_1d 对称）
- forward_return_1d = 未来1日收益（预测目标）

边界处理：
- 第一日数据设为 NaN（无昨日收盘价）
- close[t-1] = 0 时设为 NaN（无效数据）

作者: 云瑶
创建日期: 2026-06-04
版本历史:
  v1.0 (2026-06-04): 初始版本，因子名 return_1d
  v1.1 (2026-06-04): 重命名为 past_return_1d，与 forward_return_1d 对称
  v1.2 (2026-06-04): 移除 custom_factor_calculation，改为使用 run_simple_factor_ic（遵循数据层架构原则）
"""

import argparse
import sys
from pathlib import Path


# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent.parent))

# 导入公共模块主入口（遵循 PROJECT.md 强制复用规范）
from factor_ic.common.factor_ic_runner import run_simple_factor_ic
from factor_ic.common.logger_config import get_logger


logger = get_logger(__name__)

# ============================================================================
# 参数统一管理
# ============================================================================
DEFAULT_MIN_STOCKS = 10


# ============================================================================
# CLI 入口
# ============================================================================


def main():
    """CLI 主入口"""
    parser = argparse.ArgumentParser(description="过去1日涨幅因子 IC 计算器")
    parser.add_argument("--force-full", action="store_true", help="强制全量计算")
    parser.add_argument("--min-stocks", type=int, default=DEFAULT_MIN_STOCKS, help="最小股票数")

    args = parser.parse_args()

    # 使用公共模块主入口（遵循 PROJECT.md 强制复用规范）
    # 因子数据已在 factor_generator.py 预计算，使用 run_simple_factor_ic 直接读取
    result = run_simple_factor_ic(
        factor_name="past_return_1d",
        factor_col="past_return_1d",
        min_stocks=args.min_stocks,
        force_full=args.force_full,
        _logger=logger,
    )

    # 打印结果摘要（因子方向 + IC统计）
    if result:
        ic_metrics = result.get("ic_metrics", {})
        ic_mean = ic_metrics.get("ic_mean")
        icir = ic_metrics.get("icir")
        t_stat = ic_metrics.get("t_stat")
        p_value = ic_metrics.get("p_value")

        factor_direction = result.get("factor_direction", "unknown")

        logger.info("=" * 40)
        logger.info(f"因子方向: {factor_direction}")
        ic_mean_val = ic_mean if ic_mean is not None else "N/A"
        icir_val = icir if icir is not None else "N/A"
        t_stat_val = t_stat if t_stat is not None else "N/A"
        p_value_val = p_value if p_value is not None else "N/A"
        logger.info(f"IC均值: {ic_mean_val}")
        logger.info(f"ICIR: {icir_val}")
        logger.info(f"t统计量: {t_stat_val}")
        logger.info(f"p值: {p_value_val}")
        logger.info("=" * 40)

        return 0
    else:
        logger.error("IC 计算失败")
        return 1


if __name__ == "__main__":
    sys.exit(main())
