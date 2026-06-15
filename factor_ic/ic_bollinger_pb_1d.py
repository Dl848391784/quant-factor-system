#!/usr/bin/env python3
"""
布林带%B 因子 IC 计算器 - 使用公共模块主入口

遵循 PROJECT.md 公共模块强制复用规范：
- 主流程使用 run_factor_ic()（禁止手写三模式分支）
- 因子计算逻辑复用 data_fetchers.factor_calculator（遵循 MODULE.md 约束 #3）

代码量：~60行（仅 CLI 入口），因子计算逻辑已统一到 factor_calculator.py。

因子定义：
- Middle Band = SMA(Close, N)
- Upper Band = Middle Band + K × StdDev(Close, N)
- Lower Band = Middle Band - K × StdDev(Close, N)
- %B = (Close - Lower Band) / (Upper Band - Lower Band)

参数：
- N = 20（移动平均周期）
- K = 2.0（标差倍数）

作者: 云瑶
重构日期: 2026-05-27（因子计算逻辑迁移到 factor_calculator.py）
原版作者: 云舟
原版日期: 2026-04-07
版本历史:
  v1.0 (2026-04-07): 初始版本，独立实现布林带%B 因子 IC 计算
  v2.0 (2026-05-27): 重构，使用 run_factor_ic 公共模块
  v2.1 (2026-06-15):
    - 完善 None 字段 warning 为四字段汇总单条（仅在有缺失字段时输出，避免与摘要 N/A 重复）
    - 在 main() docstring 显式声明异常契约与返回值，消除函数签名歧义
  v2.2 (2026-06-15):
    - CLI 入口业务异常 FactorCalcError 改用 logger.error 携带消息即可，
      不打印堆栈（堆栈对可预期业务失败是噪音）；仅未预期 Exception 保留 logger.exception
      （遵循 MODULE.md M22 按异常类别分类的更新版规则）
"""

import argparse
import sys
from pathlib import Path


# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent.parent))


# 导入公共模块主入口（遵循 PROJECT.md 强制复用规范）
from data_fetchers.factor_calculator import (  # isort: skip
    DEFAULT_BOLLINGER_K as DEFAULT_K,
    DEFAULT_BOLLINGER_N as DEFAULT_N,
    calculate_bollinger_pb,
)
from factor_ic.common.cli_helpers import DEFAULT_MIN_STOCKS
from factor_ic.common.data_columns import JOIN_KEYS
from factor_ic.common.exceptions import FactorCalcError
from factor_ic.common.factor_ic_runner import run_factor_ic
from factor_ic.common.factor_spec import FactorSpec, register_factor
from factor_ic.common.logger_config import get_logger


logger = get_logger(__name__)

# ============================================================================
# FactorSpec 声明式注册（遵循 factor_cols_literal_constant_design.md §4.1）
# required_columns: JOIN_KEYS + close（close 为布林带计算输入）
# ============================================================================

SPEC = register_factor(
    FactorSpec(
        factor_name="bollinger_pb",
        factor_col="bollinger_pb",
        required_columns=JOIN_KEYS + ("close",),
        calculation=calculate_bollinger_pb,
        calc_params_fn=(_params_fn := lambda a: {"n": a.n, "k": a.k}),
        extra_log_params_fn=_params_fn,
    )
)
# ============================================================================
# CLI 入口
# ============================================================================


def main():
    """布林带%B 因子 IC 计算 CLI 主入口

    Returns
    -------
    dict
        run_factor_ic 的完整结果字典（成功路径下保证非 None）。

    Raises
    ------
    FactorCalcError
        result 为 None 时抛出，表示数据加载或公共模块计算失败（业务异常）。
        作为函数被外部模块导入调用时，调用方需自行处理本异常；
        作为脚本（``python ic_bollinger_pb_1d.py``）运行时，由 ``__main__`` 块捕获并 ``sys.exit(1)``。
    Exception
        其他未预期异常会原样向上传播，不在本函数内吞掉。
    """
    parser = argparse.ArgumentParser(description="布林带%B IC 计算器")
    parser.add_argument("--force-full", action="store_true", help="强制全量计算")
    parser.add_argument("--n", type=int, default=DEFAULT_N, help="移动平均周期")
    parser.add_argument("--k", type=float, default=DEFAULT_K, help="标差倍数")
    parser.add_argument("--min-stocks", type=int, default=DEFAULT_MIN_STOCKS, help="最小股票数")

    args = parser.parse_args()

    # 启动横幅由公共模块 factor_ic_runner 统一打印（含 min_stocks/force_full + extra_log_params）
    # 使用 FactorSpec 驱动入口（遵循 factor_cols_literal_constant_design.md §4.1）
    result = run_factor_ic(
        spec=SPEC,
        args=args,
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
    ic_distribution_consistency = result.get("ic_distribution_consistency") or {}

    # 构建结果摘要（单次输出保证并发场景下日志原子性）
    ic_mean = ic_metrics.get("ic_mean")
    ic_std = ic_metrics.get("ic_std")
    icir = ic_metrics.get("icir")
    positive_ratio = ic_distribution_consistency.get("positive_ratio")

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
        f"计算参数: n={args.n}, k={args.k}",
        f"日期范围: {period.get('start', 'N/A')} ~ {period.get('end', 'N/A')}",
        f"有效天数: {sample_stats.get('valid_days', 'N/A')} 天",
        "--- IC指标 ---",
        f"IC 均值: {ic_mean_str}",
        f"IC 标准差: {ic_std_str}",
        f"ICIR: {icir_str}",
        f"IC>0 占比: {positive_ratio_str}",
    ]
    logger.info("\n%s", "\n".join(summary_lines))

    # 异常状态告警（运维巡检用）：摘要中已用 N/A 显式呈现，此处仅在存在缺失字段时输出一条汇总，避免与摘要逐字段重复
    missing_fields = [
        name
        for name, value in (
            ("ic_mean", ic_mean),
            ("ic_std", ic_std),
            ("icir", icir),
            ("positive_ratio", positive_ratio),
        )
        if value is None
    ]
    if missing_fields:
        logger.warning(
            "本次计算存在空值字段: %s，请检查数据源 / 因子分布 / 公共模块输出结构",
            ", ".join(missing_fields),
        )

    # 确认结果处理完成后才输出"计算完成"日志（避免中途失败造成误导）
    logger.info("布林带%B因子IC计算完成")

    return result


if __name__ == "__main__":
    try:
        main()
    except FactorCalcError as e:
        # 业务异常：消息已足够定位，堆栈是噪音（MODULE.md M22 业务异常子类规则）
        logger.error("布林带%B因子IC计算失败: %s", e)
        sys.exit(1)
    except Exception:
        # 未预期异常：必须打印堆栈以便定位
        logger.exception("未预期的错误")
        sys.exit(1)
