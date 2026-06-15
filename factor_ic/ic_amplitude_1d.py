#!/usr/bin/env python3
"""
振幅因子 IC 计算器 - 使用公共模块主入口

遵循 PROJECT.md 公共模块强制复用规范：
- 主流程使用 run_complex_factor_ic()（禁止手写三模式分支）
- 因子计算逻辑复用 data_fetchers.factor_calculator（遵循 MODULE.md 约束 #3）

代码量：~163行（CLI 入口 + 结果摘要 + 异常处理），因子计算使用公共模块 run_complex_factor_ic。

因子定义：
- Amplitude = (High - Low) / Close
- 含义：当日振幅相对于收盘价的比率，反映价格波动强度
  - 值越大 → 波动越剧烈
  - 值越小 → 波动平稳
  - 范围：理论 [0, +∞)，实际通常 [0, 0.15]（A股振幅上限15%）

边界处理：
- Close = 0 时，设为 NaN（无效数据）
- High = Low 时，振幅为 0（一字涨停/跌停）

作者: 云瑶
创建日期: 2026-05-29
版本历史:
  v1.0 (2026-05-29): 初始版本，复用 factor_calculator.calculate_amplitude
  v1.1 (2026-05-31): 优化日志字段名 + 防御性 None 处理 + 删除未使用导入
  v1.2 (2026-06-08):
    - 引入外部自定义异常类 FactorCalcError（区分业务失败与非预期 RuntimeError，定义在 factor_ic.common.exceptions）
    - 补全四字段 warning（ic_mean/ic_std/icir/positive_ratio 为 None 时告警）
    - 结果摘要合并为单条日志输出
    - 保底处理改为抛出 FactorCalcError（遵循异常处理规范）
    - 代码量注释更新（~163行，反映实际行数）
  v1.3 (2026-06-15):
    - 删除冗余空注释块（自定义异常类分隔块本无内容）
    - 删除调用方内部细节行内注释（公共模块 params 转换为 {} 属于公共模块文档职责）
    - 去除 ic_distribution 注释中硬编码的 MODULE.md 行号（改引用语义）
    - 合并四条 None 告警为单条汇总 warning（消除与结果摘要 N/A 的信息重复）
    - 在 main() docstring 显式声明异常契约与返回值，消除函数签名歧义
"""

import argparse
import sys
from pathlib import Path


# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent.parent))

# 导入公共模块主入口（遵循 PROJECT.md 强制复用规范）
# 从 factor_calculator 导入因子计算函数（遵循 MODULE.md 约束 #3）
from data_fetchers.factor_calculator import calculate_amplitude
from factor_ic.common.cli_helpers import DEFAULT_MIN_STOCKS
from factor_ic.common.exceptions import FactorCalcError
from factor_ic.common.factor_ic_runner import run_complex_factor_ic
from factor_ic.common.logger_config import get_logger


logger = get_logger(__name__)

# ============================================================================
# CLI 入口
# ============================================================================


def main():
    """振幅因子 IC 计算 CLI 主入口

    Returns
    -------
    dict
        run_complex_factor_ic 的完整结果字典（成功路径下保证非 None）。

    Raises
    ------
    FactorCalcError
        result 为 None 时抛出，表示数据加载或公共模块计算失败（业务异常）。
        作为函数被外部模块导入调用时，调用方需自行处理本异常；
        作为脚本（``python ic_amplitude_1d.py``）运行时，由 ``__main__`` 块捕获并 ``sys.exit(1)``。
    Exception
        其他未预期异常会原样向上传播，不在本函数内吞掉。
    """

    parser = argparse.ArgumentParser(description="振幅因子 IC 计算器")
    parser.add_argument("--force-full", action="store_true", help="强制全量计算")
    parser.add_argument("--min-stocks", type=int, default=DEFAULT_MIN_STOCKS, help="最小股票数")

    args = parser.parse_args()

    # 调用前日志
    logger.info(
        "启动振幅因子IC计算: min_stocks=%s, force_full=%s",
        args.min_stocks,
        args.force_full,
    )

    # 使用公共模块主入口（遵循 PROJECT.md 强制复用规范）
    result = run_complex_factor_ic(
        factor_name="amplitude",
        factor_col="amplitude",
        factor_cols=["high", "low", "close"],  # 需要三列进行计算
        custom_factor_calculation=calculate_amplitude,
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
    # 字段名来源于 MODULE.md 输出结构模板章节（ic_distribution_consistency）
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

    # 确认结果处理完成后才输出"计算完成"日志
    logger.info("振幅因子IC计算完成")

    return result


if __name__ == "__main__":
    try:
        main()
    except FactorCalcError as e:
        # 已知业务异常，使用 error()（不打印完整堆栈，但保留错误内容）
        logger.error("振幅因子IC计算失败: %s", e)
        sys.exit(1)
    except Exception:
        # 未预期异常（含非预期 RuntimeError），使用 exception()（自动打印完整堆栈）
        logger.exception("未预期的错误")
        sys.exit(1)
