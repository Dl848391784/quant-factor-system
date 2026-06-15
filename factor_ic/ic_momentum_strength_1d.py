#!/usr/bin/env python3
"""
动量强度因子 IC 计算器 - 使用公共模块主入口

遵循 PROJECT.md 公共模块强制复用规范：
- 主流程使用 run_complex_factor_ic()（禁止手写三模式分支）
- 因子计算逻辑复用 data_fetchers.factor_calculator（遵循 MODULE.md 约束 #3）

代码量：~60行（仅 CLI 入口），因子计算逻辑已统一到 factor_calculator.py。

因子定义：
- Momentum_strength = return_5d / std(return_1d, 5日)
- 含义：衡量5日累计涨幅相对于日收益率波动率的比率
  - 高值 → 持续上涨趋势（动量强，波动小）
  - 低值 → 震荡或下跌（动量弱，波动大）
  - 范围：理论 [-∞, +∞)，极端值需关注

边界处理：
- std = 0 时，设为 NaN（除零保护）
- return_5d = NaN 时，结果为 NaN（历史不足）
- 前5日数据设为 NaN（rolling window 不足）

作者: 云瑶
创建日期: 2026-06-05
版本历史:
  v1.0 (2026-06-05): 初始版本，复用 factor_calculator.calculate_momentum_strength
  v1.1 (2026-06-05): 优化日志输出与异常处理：
    1. 添加 __main__ try/except 块（遵循 MODULE.md 异常处理规范）
    2. 修复 ic_std/icir 格式化陷阱（字符串 'N/A' 无法用 :.4f）
    3. 添加异常状态整体感知日志（ic_mean=None 时 warning）
    4. 导入分组注释规范化（本地模块分隔）
    5. 添加模块级 __version__ 常量 + _logger 模式
"""

import argparse
import sys
from pathlib import Path


# ============================================================================
# 本地模块导入
# ============================================================================

# 添加项目路径（遵循 PROJECT.md 根目录模块导入规范）
sys.path.insert(0, str(Path(__file__).parent.parent))

from data_fetchers.factor_calculator import calculate_momentum_strength
from factor_ic.common.cli_helpers import DEFAULT_MIN_STOCKS
from factor_ic.common.data_columns import JOIN_KEYS
from factor_ic.common.exceptions import FactorCalcError
from factor_ic.common.factor_ic_runner import run_factor_ic
from factor_ic.common.factor_spec import FactorSpec, register_factor
from factor_ic.common.logger_config import get_logger


# ============================================================================
# 模块级常量
# ============================================================================

__version__ = "1.1"

# 使用模块级 _logger 模式（遵循 superpowers-workflow 最佳实践）
_logger = get_logger(__name__)


# ============================================================================
# FactorSpec 声明式注册（遵循 factor_cols_literal_constant_design.md §4.1）
# ============================================================================

SPEC = register_factor(
    FactorSpec(
        factor_name="momentum_strength",
        factor_col="momentum_strength",
        required_columns=JOIN_KEYS + ("close", "return_5d", "momentum_strength"),
        calculation=calculate_momentum_strength,
    )
)
# ============================================================================
# CLI 入口
# ============================================================================


def main():
    """CLI 主入口"""

    parser = argparse.ArgumentParser(description="动量强度因子 IC 计算器")
    parser.add_argument("--force-full", action="store_true", help="强制全量计算")
    parser.add_argument("--min-stocks", type=int, default=DEFAULT_MIN_STOCKS, help="最小股票数")

    args = parser.parse_args()

    # 启动横幅由公共模块 factor_ic_runner 统一打印（含 min_stocks/force_full）
    # 使用 FactorSpec 驱动入口（遵循 factor_cols_literal_constant_design.md §4.1）
    # 注意：momentum_strength 需要 close（计算return_1d）和 return_5d
    result = run_factor_ic(
        spec=SPEC,
        min_stocks=args.min_stocks,
        force_full=args.force_full,
        _logger=_logger,
    )

    # 保底处理：公共模块异常返回 None 时抛出 RuntimeError
    if result is None:
        raise FactorCalcError("run_complex_factor_ic 返回 None")

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
        f"IC均值: {ic_mean_str}",
        f"IC标准差: {ic_std_str}",
        f"ICIR: {icir_str}",
        f"IC>0占比: {positive_ratio_str}",
    ]
    _logger.info("\n%s", "\n".join(summary_lines))

    # 异常状态整体感知日志（运维巡检用）
    if ic_mean is None:
        _logger.warning("本次IC计算结果为空，请检查数据源或参数配置")

    # 确认结果处理完成后才输出"计算完成"日志
    _logger.info("动量强度因子IC计算完成")

    return result


if __name__ == "__main__":
    try:
        main()
    except FactorCalcError as e:
        # 已知业务异常，使用 error()（不打印完整堆栈）
        _logger.error("动量强度因子IC计算失败: %s", e)
        sys.exit(1)
    except Exception:
        # 未预期异常，使用 exception()（自动打印完整堆栈，无需重复传 e）
        _logger.exception("未预期的错误")
        sys.exit(1)
