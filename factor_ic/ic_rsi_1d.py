#!/usr/bin/env python3
"""
RSI_1D IC 计算器（重构版 v2） - 1日收益周期

使用公共模块主入口 run_simple_factor_ic，代码量从 254 行降至 ~60 行。

功能：
1. 从缓存数据计算 RSI(6) 因子的 IC
2. 支持全量计算、增量更新和跳过三种模式
3. 五维度独立判断（统计显著性、因子方向、经济显著性、ICIR稳定性、IC分布一致性）

实现方式：
- 使用 run_simple_factor_ic() 公共模块主入口
- 无需自定义因子计算（RSI 已在缓存中）

遵循 PROJECT.md 公共模块强制复用规范：
- 主流程使用 run_simple_factor_ic()（禁止手写三模式分支）
- 仅实现因子特有参数配置

作者: 云瑶
重构日期: 2026-05-23（v2：使用 run_simple_factor_ic）
原版作者: 云舟
原版日期: 2026-05-07
"""

import argparse
import sys

# 添加项目路径
# 导入公共模块主入口（遵循 PROJECT.md 强制复用规范）
from factor_ic.common.cli_helpers import DEFAULT_MIN_STOCKS
from factor_ic.common.data_columns import JOIN_KEYS
from factor_ic.common.exceptions import FactorCalcError
from factor_ic.common.factor_ic_runner import run_factor_ic
from factor_ic.common.factor_spec import FactorSpec, register_factor
from factor_ic.common.logger_config import get_logger


logger = get_logger(__name__)

# ============================================================================
# FactorSpec 声明式注册（遵循 factor_cols_literal_constant_design.md §4.1）
# required_columns: JOIN_KEYS + rsi_6（RSI 已在 factor_generator 预计算）
# ============================================================================

SPEC = register_factor(
    FactorSpec(
        factor_name="rsi",
        factor_col="rsi_6",
        required_columns=JOIN_KEYS + ("rsi_6",),
    )
)
# ============================================================================
# CLI 入口
# ============================================================================


def main():
    """CLI 主入口"""
    parser = argparse.ArgumentParser(description="RSI_1D IC 计算器（重构版 v2）")
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

    # 防御性检查：result 为 None 时抛出异常（遵循 PROJECT.md 异常处理规范）
    if result is None:
        raise FactorCalcError("run_factor_ic 返回 None，数据加载或计算可能失败")

    # 使用 .get() + or {} 防御性访问结果（避免 None 导致格式化失败）
    ic_metrics = result.get("ic_metrics") or {}
    sample_stats = result.get("sample_stats") or {}
    period = result.get("period") or {}
    ic_distribution = result.get("ic_distribution_consistency") or {}

    # 构建结果摘要（单次输出保证并发场景下日志原子性）
    ic_mean = ic_metrics.get("ic_mean")
    ic_std = ic_metrics.get("ic_std")
    icir = ic_metrics.get("icir")
    positive_ratio = ic_distribution.get("positive_ratio")

    # 格式化各字段（None 时显示 N/A）
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
    logger.info("\n%s", "\n".join(summary_lines))

    # ic_mean 为 None 时额外输出 warning，便于告警系统捕获异常运行
    if ic_mean is None:
        logger.warning("本次计算 IC 均值为空，请检查数据源")

    # 确认结果处理完成后才输出"计算完成"日志（避免中途失败造成误导）
    logger.info("RSI_1D 因子 IC 计算完成")

    return result


if __name__ == "__main__":
    try:
        main()
    except FactorCalcError:
        logger.exception("RSI_1D 因子 IC 计算失败")
        sys.exit(1)
    except Exception:
        logger.exception("RSI_1D 因子 IC 计算失败（未预期错误）")
        sys.exit(1)
