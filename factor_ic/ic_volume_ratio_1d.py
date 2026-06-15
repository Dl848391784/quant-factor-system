#!/usr/bin/env python3
"""
量比因子 IC 计算器 - 使用公共模块主入口

遵循 PROJECT.md 公共模块强制复用规范：
- 主流程使用 run_simple_factor_ic()（禁止手写三模式分支）
- 无需自定义因子计算（量比因子 volume_ratio_5 已在缓存中）

代码量：~165行（CLI 入口 + 结果摘要 + 异常处理），因子计算使用公共模块 run_simple_factor_ic。

因子定义：
- volume_ratio_5 = 当日成交量 / 过去5日平均成交量
- 含义：量比（成交量相对强度）
  - > 1 → 成交量放大（高于历史平均）
  - < 1 → 成交量萎缩（低于历史平均）
  - = 1 → 成交量正常

边界处理：
- 过去5日成交量不足时设为 NaN
- 成交量为 0 时设为 NaN

作者: 云瑶
创建日期: 2026-05-08
重构日期: 2026-05-23（v2：使用 run_simple_factor_ic）
版本历史:
  v1.0 (2026-05-08): 初始版本，独立实现量比因子 IC 计算（253行）
  v2.0 (2026-05-23): 重构，使用 run_simple_factor_ic 公共模块（代码量降至~60行）
  v2.1 (2026-06-01):
    - argparse 导入移至文件顶部（遵循 PEP 8）
    - 删除启动日志（公共模块已有等效日志）
    - 删除历史遗留注释（"问题2修复"、"问题3修复"）
    - 删除重复的 ic_metrics 赋值（第74行冗余）
    - 新增 result 为 None 保底处理
    - 新增 ic_distribution_consistency 字段读取（对齐 MODULE.md 第56行）
    - positive_ratio 取值位置修正（从 ic_distribution 取而非 result）
    - N/A 日志信息补充原因（ic_std/icir/positive_ratio）
    - 异常告警层级补充（ic_mean/ic_std/icir/positive_ratio warning）
    - 完成日志移至结果摘要后（语义更清晰）
    - 异常处理简化（删除 RuntimeError 分支）
    - 代码量注释更新（~165行，反映实际行数）
  v2.2 (2026-06-08):
    - 新增启动参数日志（便于追溯 CLI 入参）
    - 新增自定义异常类 FactorCalcError（区分业务失败与非预期 RuntimeError）
    - 补全四字段 warning（ic_mean/ic_std/icir/positive_ratio 为 None 时告警）
    - 结果摘要合并为单条日志输出
    - 修正注释原子性表述（删除"并发场景下日志原子性"误导性描述）
    - 保底处理改为抛出 FactorCalcError（遵循异常处理规范）
"""

import argparse
import sys
from pathlib import Path


# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent.parent))

# 导入公共模块主入口（遵循 PROJECT.md 强制复用规范）
from factor_ic.common.cli_helpers import DEFAULT_MIN_STOCKS
from factor_ic.common.exceptions import FactorCalcError
from factor_ic.common.factor_ic_runner import run_simple_factor_ic
from factor_ic.common.logger_config import get_logger


logger = get_logger(__name__)
# ============================================================================
# CLI 入口
# ============================================================================


def main():
    """CLI 主入口"""
    parser = argparse.ArgumentParser(description="量比因子 IC 计算器")
    parser.add_argument("--force-full", action="store_true", help="强制全量计算")
    parser.add_argument("--min-stocks", type=int, default=DEFAULT_MIN_STOCKS, help="最小股票数")

    args = parser.parse_args()

    # 启动参数日志（便于追溯本次运行配置）
    logger.info(
        "启动量比因子IC计算: min_stocks=%s, force_full=%s",
        args.min_stocks,
        args.force_full,
    )

    # 使用公共模块主入口（遵循 PROJECT.md 强制复用规范）
    # 注意：run_simple_factor_ic 只需 factor_col，公共模块自动加载该列
    result = run_simple_factor_ic(
        factor_name="volume_ratio",
        factor_col="volume_ratio_5",
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
    # 字段名 ic_distribution_consistency 来源于 MODULE.md 第56行输出结构
    # 语义：正比例与方向一致/矛盾判断（MODULE.md 第77行），非单纯分布统计
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
        f"日期范围: {period.get('start', 'N/A')} ~ {period.get('end', 'N/A')}",
        f"有效天数: {sample_stats.get('valid_days', 0)} 天",
        "--- IC指标 ---",
        f"IC 均值: {ic_mean_str}",
        f"IC 标准差: {ic_std_str}",
        f"ICIR: {icir_str}",
        f"IC>0 占比: {positive_ratio_str}",
    ]
    logger.info("\n%s", "\n".join(summary_lines))

    # 异常状态告警（运维巡检用，遵循版本历史四字段告警约定）
    if ic_mean is None:
        logger.warning("本次计算 IC 均值为空，请检查数据源")
    if ic_std is None:
        logger.warning("IC 标准差无法计算，请检查因子数据分布")
    if icir is None:
        logger.warning("ICIR 无法计算，请检查因子数据分布")
    if positive_ratio is None:
        logger.warning("IC>0 占比无法获取，请检查公共模块输出结构")

    # 确认结果处理完成后才输出"计算完成"日志（避免中途失败造成误导）
    logger.info("量比因子IC计算完成")

    return result


if __name__ == "__main__":
    try:
        main()
    except FactorCalcError as e:
        # 已知业务异常，使用 error()（不打印完整堆栈，但保留错误内容）
        logger.error("量比因子IC计算失败: %s", e)
        sys.exit(1)
    except Exception:
        # 未预期异常（含非预期 RuntimeError），使用 exception()（自动打印完整堆栈）
        logger.exception("未预期的错误")
        sys.exit(1)
