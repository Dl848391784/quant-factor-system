#!/usr/bin/env python3
"""
行业ROE趋势因子 IC 计算器 - 使用公共模块主入口

遵循 PROJECT.md 公共模块强制复用规范：
- 主流程使用 run_complex_factor_ic()（禁止手写三模式分支）
- 因子计算逻辑复用 data_fetchers.factor_calculator（遵循 MODULE.md 约束 #3）

因子定义：
- industry_roe_trend = 行业ΔROE赋个股（季度间ROE变化量，行业聚合赋给同行业每只股票）
- 含义：行业基本面盈利能力趋势，方向性因子
- 遵循 H5: IC方向不预判，由数据决定

边界处理：
- industry 未知 → 赋 '其他' 行业
- ROE 数据缺失 → ΔROE 为 NaN
- 季度财务数据前推填充对齐日频

作者: 云瑶
创建日期: 2026-06-12
版本历史:
  v1.0 (2026-06-12): 初始版本，复用 factor_calculator.calculate_industry_roe_trend
"""

import argparse
import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).parent.parent))  # noqa: E402

from data_fetchers.factor_calculator import calculate_industry_roe_trend  # noqa: E402
from factor_ic.common.cli_helpers import DEFAULT_MIN_STOCKS  # noqa: E402
from factor_ic.common.exceptions import FactorCalcError  # noqa: E402
from factor_ic.common.factor_ic_runner import run_complex_factor_ic  # noqa: E402
from factor_ic.common.logger_config import get_logger  # noqa: E402


logger = get_logger(__name__)


def main():
    """CLI 主入口"""
    parser = argparse.ArgumentParser(description="行业ROE趋势因子 IC 计算器")
    parser.add_argument("--force-full", action="store_true", help="强制全量计算")
    parser.add_argument("--min-stocks", type=int, default=DEFAULT_MIN_STOCKS, help="最小股票数")
    args = parser.parse_args()

    logger.info(f"启动行业ROE趋势因子IC计算: min_stocks={args.min_stocks}, force_full={args.force_full}")

    result = run_complex_factor_ic(
        factor_name="industry_roe_trend",
        factor_col="industry_roe_trend",
        factor_cols=["date", "asset"],
        custom_factor_calculation=calculate_industry_roe_trend,
        min_stocks=args.min_stocks,
        force_full=args.force_full,
        _logger=logger,
    )

    if result is None:
        raise FactorCalcError("run_complex_factor_ic 返回 None，数据加载或计算可能失败")

    ic_metrics = result.get("ic_metrics") or {}
    sample_stats = result.get("sample_stats") or {}
    period = result.get("period") or {}
    ic_distribution = result.get("ic_distribution_consistency") or {}

    ic_mean = ic_metrics.get("ic_mean")
    ic_std = ic_metrics.get("ic_std")
    icir = ic_metrics.get("icir")
    positive_ratio = ic_distribution.get("positive_ratio")

    ic_mean_str = f"{ic_mean:.4f}" if ic_mean is not None else "N/A"
    ic_std_str = f"{ic_std:.4f}" if ic_std is not None else "N/A"
    icir_str = f"{icir:.2f}" if icir is not None else "N/A"
    positive_ratio_str = f"{positive_ratio:.2%}" if positive_ratio is not None else "N/A"

    summary_lines = [
        "=" * 60,
        "结果摘要",
        "=" * 60,
        f"因子名称: {result.get('factor_name', 'unknown')}",
        f"更新模式: {result.get('update_mode', 'unknown')}",
        f"日期范围: {period.get('start', 'N/A')} ~ {period.get('end', 'N/A')}",
        f"有效天数: {sample_stats.get('valid_days', 0)} 天",
        "--- IC指标 ---",
        f"IC 均值: {ic_mean_str}",
        f"IC 标准差: {ic_std_str}",
        f"ICIR: {icir_str}",
        f"IC>0 占比: {positive_ratio_str}",
    ]
    logger.info("\n" + "\n".join(summary_lines))

    if ic_mean is None:
        logger.warning("本次计算 IC 均值为空，请检查数据源")
    if ic_std is None:
        logger.warning("IC 标准差无法计算，请检查因子数据分布")
    if icir is None:
        logger.warning("ICIR 无法计算，请检查因子数据分布")
    if positive_ratio is None:
        logger.warning("IC>0 占比无法获取，请检查公共模块输出结构")

    logger.info("行业ROE趋势因子IC计算完成")
    return result


if __name__ == "__main__":
    try:
        main()
    except FactorCalcError as e:
        logger.error(f"行业ROE趋势因子IC计算失败: {e}")
        sys.exit(1)
    except Exception:
        logger.exception("未预期的错误")
        sys.exit(1)
