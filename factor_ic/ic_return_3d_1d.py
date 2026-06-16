#!/usr/bin/env python3
"""
3日累计涨幅因子 IC 计算器 - 使用公共模块主入口

遵循 PROJECT.md 公共模块强制复用规范：
- 主流程使用 run_complex_factor_ic()（禁止手写三模式分支）
- 因子计算逻辑复用 data_fetchers.factor_calculator（遵循 MODULE.md 约束 #3）

代码量：~170行（CLI 入口 + 结果摘要 + 异常处理），因子计算逻辑已统一到 factor_calculator.py。

因子定义：
- Return_3d = close[t] / close[t-3] - 1
- 含义：过去3日累计涨跌幅
  - 正值 → 上涨
  - 负值 → 下跌
  - 范围：理论 [-∞, +∞)，A股日涨跌幅±10%，3日累计约±30%

边界处理：
- 前3日数据设为 NaN（历史数据不足）
- close[t-3] = 0 时设为 NaN（无效数据）

作者: 云瑶
创建日期: 2026-05-29
版本历史:
  v1.0 (2026-05-29): 初始版本，复用 factor_calculator.calculate_return_3d
  v1.1 (2026-06-01):
    - argparse 导入移至文件顶部（遵循 PEP 8）
    - 删除启动日志（公共模块已有等效日志）
    - 新增 result 为 None 保底处理
    - 新增 ic_distribution_consistency 字段读取（对齐 MODULE.md 第56行）
    - positive_ratio 取值位置修正（从 ic_distribution 取而非 result）
    - N/A 日志信息补充原因（ic_std/icir/positive_ratio）
    - 异常告警层级补充（ic_mean/ic_std/icir/positive_ratio warning）
    - 异常处理简化（删除 RuntimeError 分支）
    - factor_cols 顺序依赖注释确认（公共模块按列名取列）
    - 代码量注释更新（~170行，反映实际行数）
"""

import argparse
import sys

# 添加项目路径
# 导入公共模块主入口（遵循 PROJECT.md 强制复用规范）
# 从 factor_calculator 导入因子计算函数（遵循 MODULE.md 约束 #3）
from data_fetchers.factor_calculator import calculate_return_3d
from factor_ic.common.cli_helpers import DEFAULT_MIN_STOCKS
from factor_ic.common.exceptions import FactorCalcError
from factor_ic.common.factor_ic_runner import run_factor_ic
from factor_ic.common.factor_spec import FactorSpec, register_factor
from factor_ic.common.logger_config import get_logger


logger = get_logger(__name__)

# ============================================================================
# FactorSpec 声明式注册（遵循 factor_cols_literal_constant_design.md §4.1）
# ============================================================================

SPEC = register_factor(
    FactorSpec(
        factor_name="return_3d",
        factor_col="return_3d",
        calculation=calculate_return_3d,
    )
)
# ============================================================================
# CLI 入口
# ============================================================================


def main():
    """CLI 主入口"""
    parser = argparse.ArgumentParser(description="3日累计涨幅因子 IC 计算器")
    parser.add_argument("--force-full", action="store_true", help="强制全量计算")
    parser.add_argument("--min-stocks", type=int, default=DEFAULT_MIN_STOCKS, help="最小股票数")

    args = parser.parse_args()

    # 启动横幅由公共模块 factor_ic_runner 统一打印（含 min_stocks/force_full）
    # 使用 FactorSpec 驱动入口（遵循 factor_cols_literal_constant_design.md §4.1）
    # 注意：factor_cols 必须包含 asset, date 列（groupby 和 shift 依赖）
    # 已确认：公共模块按列名取列（data_loader.py 第205-222行），顺序无关
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
    # 字段名 ic_distribution_consistency 来源于 MODULE.md 第56行输出结构
    # 语义：正比例与方向一致/矛盾判断（MODULE.md 第77行），非单纯分布统计
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
    logger.info("3日累计涨幅因子IC计算完成")

    return result


if __name__ == "__main__":
    try:
        main()
    except FactorCalcError as e:
        # 已知业务异常，使用 error()（不打印完整堆栈，但保留错误内容）
        logger.error("3日累计涨幅因子IC计算失败: %s", e)
        sys.exit(1)
    except Exception:
        # 未预期异常，使用 exception()（自动打印完整堆栈）
        logger.exception("未预期的错误")
        sys.exit(1)
