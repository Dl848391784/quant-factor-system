#!/usr/bin/env python3
"""
过去1日涨幅因子 IC 计算器 - 使用公共模块主入口

遵循 PROJECT.md 公共模块强制复用规范：
- 主流程使用 run_simple_factor_ic()（预计算因子，直接读取）
- 因子数据已在 factor_generator.py 预计算，存储于 factor_ic_data.json.gz

代码量：~169行（CLI 入口 + 结果摘要 + 异常处理）。

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
  v1.3 (2026-06-08):
    - 新增自定义异常类 FactorCalcError（区分业务失败与非预期 RuntimeError）
    - 新增 __main__ 块 try/except 异常处理
    - 新增启动参数日志（便于追溯 CLI 入参）
    - result 判空改为 if result is None（避免空字典误判）
    - 结果摘要合并为单条日志输出，补充日期范围/有效天数/IC标准差/IC>0占比
    - positive_ratio 从 ic_distribution_consistency 子字典取值
    - 补全四字段 warning（ic_mean/ic_std/icir/positive_ratio 为 None 时告警）
    - 新增"计算完成"日志
    - 代码量注释更新（~169行，反映实际行数）
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
# 自定义异常类
# ============================================================================


class FactorCalcError(Exception):
    """因子计算业务异常（用于区分已知业务失败和未预期 RuntimeError）"""

    pass


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

    # 启动参数日志（便于追溯本次运行配置）
    logger.info(f"启动过去1日涨幅因子IC计算: min_stocks={args.min_stocks}, force_full={args.force_full}")

    # 使用公共模块主入口（遵循 PROJECT.md 强制复用规范）
    # 因子数据已在 factor_generator.py 预计算，使用 run_simple_factor_ic 直接读取
    result = run_simple_factor_ic(
        factor_name="past_return_1d",
        factor_col="past_return_1d",
        min_stocks=args.min_stocks,
        force_full=args.force_full,
        _logger=logger,
    )

    # 防御性检查：result 为 None 时抛出业务异常（遵循 PROJECT.md 异常处理规范）
    if result is None:
        raise FactorCalcError("run_simple_factor_ic 返回 None，数据加载或计算可能失败")

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
    factor_direction = result.get("factor_direction", "unknown")

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
        f"因子方向: {factor_direction}",
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
    logger.info("过去1日涨幅因子IC计算完成")

    return result


if __name__ == "__main__":
    try:
        main()
    except FactorCalcError as e:
        # 已知业务异常，使用 error()（不打印完整堆栈，但保留错误内容）
        logger.error(f"过去1日涨幅因子IC计算失败: {e}")
        sys.exit(1)
    except Exception:
        # 未预期异常（含非预期 RuntimeError），使用 exception()（自动打印完整堆栈）
        logger.exception("未预期的错误")
        sys.exit(1)
