#!/usr/bin/env python3
"""
KDJ_J 因子 IC 计算器 - 使用公共模块主入口

遵循 PROJECT.md 公共模块强制复用规范：
- 主流程使用 run_complex_factor_ic()（禁止手写三模式分支）
- 因子计算逻辑复用 data_fetchers.factor_calculator（遵循 MODULE.md 约束 #3）

代码量：~186行（CLI 入口 + 结果摘要 + 异常处理），因子计算使用公共模块 run_complex_factor_ic。

因子定义：
- RSV(N) = (Close_t - Low_N) / (High_N - Low_N) × 100
- K_t = K_{t-1} × (M1-1)/M1 + RSV_t × 1/M1
- D_t = D_{t-1} × (M2-1)/M2 + K_t × 1/M2
- J_t = 3 × K_t - 2 × D_t

参数：
- N = 9（RSV 计算周期）
- M1 = 3（K值平滑周期）
- M2 = 3（D值平滑周期）

作者: 云瑶
重构日期: 2026-05-27（因子计算逻辑迁移到 factor_calculator.py）
原版作者: 云舟
原版日期: 2026-04-07
版本历史:
  v1.0 (2026-04-07): 初始版本，独立实现 KDJ_J 因子 IC 计算
  v2.0 (2026-05-27): 重构，使用 run_complex_factor_ic 公共模块
  v2.1 (2026-06-08):
    - 新增自定义异常类 FactorCalcError（区分业务失败与非预期 RuntimeError）
    - 新增 result 为 None 防御性检查
    - 修正 positive_ratio 取值位置（从 ic_distribution_consistency 子字典）
    - 结果摘要合并为单条日志输出
    - 补全四字段 warning（ic_mean/ic_std/icir/positive_ratio 为 None 时告警）
    - "计算完成"日志移至结果处理末尾
    - argparse 导入移至文件顶部（遵循 PEP 8）
    - 代码量注释更新（~186行，反映实际行数）
"""

import argparse
import sys
from pathlib import Path


# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent.parent))


# 导入公共模块主入口（遵循 PROJECT.md 强制复用规范）
from data_fetchers.factor_calculator import (
    DEFAULT_KDJ_M1 as DEFAULT_M1,  # K值平滑周期
)
from data_fetchers.factor_calculator import (
    DEFAULT_KDJ_M2 as DEFAULT_M2,  # D值平滑周期
)
from data_fetchers.factor_calculator import (
    DEFAULT_KDJ_N as DEFAULT_N,  # RSV 计算周期
)

# 重构后：从 factor_calculator 导入因子计算函数（遵循 MODULE.md 约束 #3）
from data_fetchers.factor_calculator import (
    calculate_kdj_j,
)
from factor_ic.common.factor_ic_runner import run_complex_factor_ic
from factor_ic.common.logger_config import get_logger


logger = get_logger(__name__)

# ============================================================================
# 自定义异常类
# ============================================================================


class FactorCalcError(Exception):
    """因子计算业务异常（用于区分已知业务失败和未预期 RuntimeError）"""

    pass


# ============================================================================
# 参数统一管理（部分从 factor_calculator 导入）
# ============================================================================
DEFAULT_MIN_STOCKS = 10


# ============================================================================
# CLI 入口
# ============================================================================


def main():
    """CLI 主入口"""
    parser = argparse.ArgumentParser(description="KDJ_J IC 计算器")
    parser.add_argument("--force-full", action="store_true", help="强制全量计算")
    parser.add_argument("--n", type=int, default=DEFAULT_N, help="RSV 计算周期")
    parser.add_argument("--m1", type=int, default=DEFAULT_M1, help="K值平滑周期")
    parser.add_argument("--m2", type=int, default=DEFAULT_M2, help="D值平滑周期")
    parser.add_argument("--min-stocks", type=int, default=DEFAULT_MIN_STOCKS, help="最小股票数")

    args = parser.parse_args()

    # 调用前日志
    logger.info(
        f"启动KDJ_J因子IC计算: n={args.n}, m1={args.m1}, m2={args.m2}, min_stocks={args.min_stocks}, force_full={args.force_full}"
    )

    # 使用公共模块主入口（遵循 PROJECT.md 强制复用规范）
    result = run_complex_factor_ic(
        factor_name="kdj_j",
        factor_col="kdj_j",
        factor_cols=["close", "high", "low"],
        custom_factor_calculation=calculate_kdj_j,
        custom_factor_calculation_params={"n": args.n, "m1": args.m1, "m2": args.m2},
        min_stocks=args.min_stocks,
        force_full=args.force_full,
        _logger=logger,
    )

    # 防御性检查：result 为 None 时抛出业务异常（遵循 PROJECT.md 异常处理规范）
    if result is None:
        raise FactorCalcError("run_complex_factor_ic 返回 None，数据加载或计算可能失败")

    # 使用 .get() + or {} 防御性访问结果（避免 None 导致格式化失败）
    ic_metrics = result.get("ic_metrics") or {}
    sample_stats = result.get("sample_stats") or {}
    period = result.get("period") or {}
    # 字段名来源于 MODULE.md 第56行输出结构模板
    ic_distribution = result.get("ic_distribution_consistency") or {}

    # 构建结果摘要（合并为单条日志便于阅读）
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
        f"计算参数: n={args.n}, m1={args.m1}, m2={args.m2}",
        f"日期范围: {period.get('start', 'N/A')} ~ {period.get('end', 'N/A')}",
        f"有效天数: {sample_stats.get('valid_days', 0)} 天",
        "--- IC指标 ---",
        f"IC 均值: {ic_mean_str}",
        f"IC 标准差: {ic_std_str}",
        f"ICIR: {icir_str}",
        f"IC>0 占比: {positive_ratio_str}",
    ]
    logger.info("\n" + "\n".join(summary_lines))

    # 异常状态告警（运维巡检用，四字段均需告警）
    if ic_mean is None:
        logger.warning("本次计算 IC 均值为空，请检查数据源")
    if ic_std is None:
        logger.warning("IC 标准差无法计算，请检查因子数据分布")
    if icir is None:
        logger.warning("ICIR 无法计算，请检查因子数据分布")
    if positive_ratio is None:
        logger.warning("IC>0 占比无法获取，请检查公共模块输出结构")

    # 确认结果处理完成后才输出"计算完成"日志
    logger.info("KDJ_J因子IC计算完成")

    return result


if __name__ == "__main__":
    try:
        main()
    except FactorCalcError as e:
        # 已知业务异常，使用 error()（不打印完整堆栈，但保留错误内容）
        logger.error(f"KDJ_J因子IC计算失败: {e}")
        sys.exit(1)
    except Exception:
        # 未预期异常（含非预期 RuntimeError），使用 exception()（自动打印完整堆栈）
        logger.exception("未预期的错误")
        sys.exit(1)
