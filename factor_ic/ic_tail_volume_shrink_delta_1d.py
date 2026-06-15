#!/usr/bin/env python3
"""
尾盘缩量差分因子 IC 计算器 - 使用公共模块主入口

遵循 PROJECT.md 公共模块强制复用规范：
- 主流程使用 run_complex_factor_ic()（禁止手写三模式分支）
- 因子计算逻辑复用 data_fetchers.factor_calculator（遵循 MODULE.md 约束 #3）

因子定义：
- tail_volume_shrink_delta = tail_volume_shrink(T) - tail_volume_shrink(T-1)
- 含义：尾盘从缩量转放量 = 资金开始介入；继续缩量 = 冷清
- 遵循 H5: IC方向不预判，由数据决定

边界处理：
- 第一日无前值 → NaN（自然排除）
- tail_volume_shrink 为 NaN → delta 也为 NaN（传播）
- 尾盘因子只有18天有效数据，差分有效天数约17天

作者: 云瑶
创建日期: 2026-06-11
版本历史:
  v1.0 (2026-06-11): 初始版本，复用 factor_calculator.calculate_tail_volume_shrink_delta
"""

import argparse
import sys
from pathlib import Path


# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent.parent))  # noqa: E402

# 导入公共模块主入口（遵循 PROJECT.md 强制复用规范）
from data_fetchers.factor_calculator import calculate_tail_volume_shrink_delta  # noqa: E402
from factor_ic.common.cli_helpers import DEFAULT_MIN_STOCKS  # noqa: E402
from factor_ic.common.exceptions import FactorCalcError  # noqa: E402
from factor_ic.common.factor_ic_runner import run_complex_factor_ic  # noqa: E402
from factor_ic.common.logger_config import get_logger  # noqa: E402


logger = get_logger(__name__)

# ============================================================================
# 自定义异常类
# ============================================================================
# ============================================================================
# CLI 入口
# ============================================================================


def main():
    """CLI 主入口"""

    parser = argparse.ArgumentParser(description="尾盘缩量差分因子 IC 计算器")
    parser.add_argument("--force-full", action="store_true", help="强制全量计算")
    parser.add_argument("--min-stocks", type=int, default=DEFAULT_MIN_STOCKS, help="最小股票数")

    args = parser.parse_args()

    # 调用前日志
    logger.info(
        "启动尾盘缩量差分因子IC计算: min_stocks=%s, force_full=%s",
        args.min_stocks,
        args.force_full,
    )

    # 使用公共模块主入口（遵循 PROJECT.md 强制复用规范）
    result = run_complex_factor_ic(
        factor_name="tail_volume_shrink_delta",
        factor_col="tail_volume_shrink_delta",
        factor_cols=["date", "asset", "tail_volume_shrink"],  # 需要原始因子列进行差分计算
        custom_factor_calculation=calculate_tail_volume_shrink_delta,
        min_stocks=args.min_stocks,
        force_full=args.force_full,
        _logger=logger,
    )

    # 防御性检查：result 为 None 时抛出业务异常
    if result is None:
        raise FactorCalcError("run_complex_factor_ic 返回 None，数据加载或计算可能失败")

    # 使用 .get() + or {} 防御性访问结果
    ic_metrics = result.get("ic_metrics") or {}
    sample_stats = result.get("sample_stats") or {}
    period = result.get("period") or {}
    ic_distribution = result.get("ic_distribution_consistency") or {}

    # 构建结果摘要
    ic_mean = ic_metrics.get("ic_mean")
    ic_std = ic_metrics.get("ic_std")
    icir = ic_metrics.get("icir")
    positive_ratio = ic_distribution.get("positive_ratio")

    ic_mean_str = f"{ic_mean:.4f}" if ic_mean is not None else "N/A"
    ic_std_str = f"{ic_std:.4f}" if ic_std is not None else "N/A"
    icir_str = f"{icir:.2f}" if icir is not None else "N/A"
    positive_ratio_str = f"{positive_ratio:.2%}" if positive_ratio is None else f"{positive_ratio:.2%}"

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
    logger.info("\n%s", "\n".join(summary_lines))

    # 四字段告警
    if ic_mean is None:
        logger.warning("本次计算 IC 均值为空，请检查数据源")
    if ic_std is None:
        logger.warning("IC 标准差无法计算，请检查因子数据分布")
    if icir is None:
        logger.warning("ICIR 无法计算，请检查因子数据分布")
    if positive_ratio is None:
        logger.warning("IC>0 占比无法获取，请检查公共模块输出结构")

    logger.info("尾盘缩量差分因子IC计算完成")

    return result


if __name__ == "__main__":
    try:
        main()
    except FactorCalcError as e:
        logger.error("尾盘缩量差分因子IC计算失败: %s", e)
        sys.exit(1)
    except Exception:
        logger.exception("未预期的错误")
        sys.exit(1)
