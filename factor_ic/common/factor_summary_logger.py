"""
因子 IC 计算结果摘要日志工具。

职责:
  1. 输出标准 IC 摘要(5 行 --- IC指标 ---)
  2. 输出 None 状态告警(单条整合,运维巡检用)
  3. 支持入口脚本注入可选扩展字段(如"因子方向")

设计参考: factor_ic/MODULE.md M3.1(公共模块告警归属)。
设计文档: factor_ic/docs/plans/factor_ic_warning_unification_design.md
"""

from __future__ import annotations

import logging


def log_factor_summary(
    result: dict,
    factor_display_name: str,
    logger: logging.Logger,
    *,
    extra_summary_lines: list[str] | None = None,
) -> None:
    """打印因子 IC 计算结果摘要 + None 状态整合告警。

    Args:
        result: ``run_complex_factor_ic`` / ``run_factor_ic_analysis`` 返回值,
                必须包含 factor_name / update_mode / period / sample_stats /
                ic_metrics / ic_distribution_consistency 字段
                (build_error_result 兜底场景下 4 字段为 None,函数会自动识别并打告警)。
        factor_display_name: 因子中文显示名(如 "振幅差分因子"),仅用于告警消息。
        logger: 入口脚本传入的 logger(遵循 MODULE.md M3 logger 传递规范,强制必传)。
        extra_summary_lines: 可选附加摘要行,按顺序追加到 IC 指标摘要末尾
                             (例: ``["因子方向: positive"]``)。

    Returns:
        None。本函数只输出日志,不返回值,不抛异常。

    行为契约:
        - 正常路径(4 字段均为数值): 仅输出 1 条 INFO 摘要
        - 错误路径(build_error_result 触发): 输出 1 条 INFO 摘要(字段显示 N/A)
                                              + 1 条 WARNING 整合告警
        - 不抛异常、不调用 sys.exit、不影响调用方控制流
    """
    # ----- (1) 提取 ic_metrics / sample_stats / period / ic_distribution -----
    ic_metrics = result.get("ic_metrics") or {}
    sample_stats = result.get("sample_stats") or {}
    period = result.get("period") or {}
    ic_distribution = result.get("ic_distribution_consistency") or {}

    ic_mean = ic_metrics.get("ic_mean")
    ic_std = ic_metrics.get("ic_std")
    icir = ic_metrics.get("icir")
    positive_ratio = ic_distribution.get("positive_ratio")

    # ----- (2) 字段格式化(None → "N/A",与现状完全一致) -----
    ic_mean_str = f"{ic_mean:.4f}" if ic_mean is not None else "N/A"
    ic_std_str = f"{ic_std:.4f}" if ic_std is not None else "N/A"
    icir_str = f"{icir:.2f}" if icir is not None else "N/A"
    positive_ratio_str = f"{positive_ratio:.2%}" if positive_ratio is not None else "N/A"

    # ----- (3) 构建 summary_lines -----
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
    if extra_summary_lines:
        summary_lines.extend(extra_summary_lines)

    logger.info("\n%s", "\n".join(summary_lines))

    # ----- (4) None 状态整合告警(替代原 4 条 warning) -----
    none_fields = [
        name
        for name, value in (
            ("ic_mean", ic_mean),
            ("ic_std", ic_std),
            ("icir", icir),
            ("positive_ratio", positive_ratio),
        )
        if value is None
    ]
    if none_fields:
        logger.warning(
            "%s IC 指标异常字段: %s(数据加载可能失败,请检查上方 ERROR 日志或 build_error_result 触发条件)",
            factor_display_name,
            ", ".join(none_fields),
        )
