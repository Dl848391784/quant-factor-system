#!/usr/bin/env python3
"""
因子分析数据汇总报告生成脚本

功能：
1. 读取单因子 IC 分析结果
2. 读取单因子分层回测结果
3. 计算因子相关性矩阵
4. 读取综合因子四种权重回测结果
5. 生成完整的汇总报告表格

使用方法：
    python summary/generate_factor_summary_report.py [--date YYYY-MM-DD] [--output report.txt]

参数：
    --date: 指定日期（默认当天）
    --output: 指定输出文件路径（默认 summary/result/factor_summary_report_YYYY-MM-DD.txt）
    --full-correlation: 强制计算所有因子之间的相关性（可能较慢）

版本历史：
    v1.0~v2.26: 见 git log（单文件演进，3207 行）
    v3.8 (2026-06-26): 拆分重构——单文件拆为 summary/report/ 子包
        - report/constants.py: 常量 + 配置 + setup_logger
        - report/formatters.py: 格式化工具函数
        - report/freshness_check.py: 数据新鲜度检查
        - report/data_loaders.py: 数据加载器
        - report/factor_analysis.py: 因子分析逻辑
        - report/sections.py: 12 个 section 渲染函数
        - 主文件保留 main() + generate_report() + re-export（~250 行）
        - 详见 designs/report_refactor_design.md
"""

__version__ = "3.8"  # v3.8 (2026-06-26): 拆分重构
__author__ = "factor_ic_analyzer"

# 标准库导入
import argparse
import logging
import sys
import time
from pathlib import Path


# 项目根目录（用于 sys.path 和路径常量）
PROJECT_ROOT = Path(__file__).parent.parent.resolve()

# 添加项目根目录到 sys.path（支持根目录模块导入）
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# ── 从 report 子包 re-export（测试兼容性） ──────────────────────────
# 测试文件通过 from summary.generate_factor_summary_report import X 导入，
# 此处 re-export 保持接口不变。

from summary.report.constants import (  # noqa: E402,F401
    COL_TO_FACTOR_NAME_MAP,
    CORR_MAX,
    CORR_THRESHOLD_HIGH,
    CORR_THRESHOLD_MEDIUM,
    DATA_CHECK_SOURCES,
    DATA_FRESHNESS_HEAD_CHARS,
    DATA_PATHS,
    FACTOR_ABBR,
    FACTOR_CATEGORIES,
    FACTOR_COL_TO_NAME_MAP,
    FACTOR_DEFINITIONS,
    FACTOR_NAME_TO_COL_MAP,
    ICIR_THRESHOLD,
    MAX_STOCKS_SAMPLE,
    PROJECT_ROOT,
    RETURN_DATA_IS_DECIMAL,
    RETURN_THRESHOLD,
    STOCK_LIST_DATA,
    _get_factor_abbr,
    setup_logger,
)
from summary.report.data_loaders import (  # noqa: E402,F401
    _select_neutral_payload,
    calculate_factor_correlation,
    load_backtest_results,
    load_composite_results,
    load_decile_stats,
    load_ic_results,
    load_json_file,
    load_stock_name_map,
    load_stock_selection_result,
    load_weight_selection_result,
    merge_factor_data,
)
from summary.report.factor_analysis import (  # noqa: E402,F401
    _compute_factor_concentration,
    _detect_duplicate_zscores,
    _detect_weight_rank_anomalies,
    _extract_corr_pairs,
    _format_exempt_note,
    _format_neutral_cell,
    _generate_neutralization_notes,
    generate_correlation_section,
    get_factor_selection_info,
)
from summary.report.formatters import (  # noqa: E402,F401
    convert_return_to_percentage,
    format_float,
    format_percentage,
    format_weights,
    get_date_str,
    get_monotonicity_symbol,
    get_weight_method_display,
)
from summary.report.freshness_check import (  # noqa: E402,F401
    _extract_date_from_json_content,
    _generate_data_check_section,
    _get_nested_field,
    check_data_freshness,
    check_derived_data_freshness,
    get_expected_t_minus_1,
    get_expected_t_minus_2,
)
from summary.report.sections import (  # noqa: E402,F401
    _generate_backtest_section,
    _generate_comparison_section,
    _generate_composite_section,
    _generate_ic_section,
    _generate_lr_training_status,
    _generate_stock_selection_section,
    _generate_weight_selection_section,
)


def generate_report(date: str, logger: logging.Logger, force_full_correlation: bool = False) -> str:
    """生成完整的汇总报告

    v2.2 (2026-06-03): 新增权重选择和股票选股结果展示

    Args:
        date: 日期字符串
        logger: 日志记录器
        force_full_correlation: 是否强制全量计算因子相关性

    Returns:
        汇总报告文本
    """
    lines = []

    # v1.9: 首先进行数据完整性检查
    logger.info("执行数据完整性检查...")
    data_results = check_data_freshness(date, logger)
    derived_results = check_derived_data_freshness(date, logger)

    # 加载所有数据
    logger.info("加载 IC 结果...")
    ic_results = load_ic_results(logger)

    logger.info("加载回测结果...")
    backtest_results = load_backtest_results(logger)

    logger.info("加载综合因子结果...")
    composite_results = load_composite_results(logger)

    # v2.2: 加载权重选择和股票选股结果
    logger.info("加载权重选择结果...")
    weight_result = load_weight_selection_result(logger)

    logger.info("加载股票选股结果...")
    stock_result = load_stock_selection_result(logger)

    # v2.26: 加载股票名称映射（短名单展示用）
    stock_name_map = load_stock_name_map(logger)

    # 数据加载失败保护：关键数据为空时抛出明确错误
    if not ic_results:
        logger.error("IC 结果数据为空，无法生成报告")
        raise ValueError("IC 结果数据为空，请检查 factor_ic/result 目录是否有数据文件")
    if not backtest_results:
        logger.error("回测结果数据为空，无法生成报告")
        raise ValueError("回测结果数据为空，请检查 backtest/result 目录是否有数据文件")

    logger.info(
        "数据加载完成: IC结果 %d 个, 回测结果 %d 个, 综合因子 %d 种权重方法",
        len(ic_results),
        len(backtest_results),
        len(composite_results),
    )
    corr_matrix = calculate_factor_correlation(logger, force_full=force_full_correlation)

    # 合并 IC 和回测数据
    factor_data = merge_factor_data(ic_results, backtest_results)

    # 报告标题
    lines.append("=" * 70)
    lines.append(f"                    因子分析数据汇总报告 ({date})")
    lines.append("=" * 70)

    # v1.9: 第零部分：数据完整性检查（新增）
    lines.extend(_generate_data_check_section(data_results, derived_results))

    # 第一部分：单因子 IC 数据汇总
    lines.extend(_generate_ic_section(ic_results, backtest_results))

    # 第二部分：单因子分层回测数据汇总
    lines.extend(_generate_backtest_section(ic_results, backtest_results))

    # 第三部分：因子相关性矩阵
    # v1.8: 从 composite_results 提取 selection_result
    selection_result = None
    if composite_results:
        for item in composite_results:
            if item.get("weight_method") == "icir_weight":
                selection_result = item.get("selection_result")
                break
    lines.extend(generate_correlation_section(corr_matrix, ic_results, selection_result))

    # v2.16: 确定最优权重方法（从 weight_result 或 composite_results 推断）
    best_weight_method = "icir_weight"  # 默认回退
    if weight_result and weight_result.get("best_selection"):
        best_weight_method = weight_result["best_selection"].get("method", "icir_weight")

    # 第四部分：因子筛选结果
    lines.append("")
    lines.append("四、因子筛选结果")
    lines.append("-" * 70)
    selection_info = get_factor_selection_info(
        composite_results, ic_results, backtest_results, logger, best_weight_method
    )
    lines.append(selection_info)

    # 第五部分：综合因子四种权重回测数据汇总
    lines.extend(_generate_composite_section(composite_results))

    # 第六部分：综合因子 vs 单因子对比
    lines.extend(_generate_comparison_section(factor_data, composite_results, best_weight_method))

    # v2.2: 第七部分：权重选择结果（新增）
    lines.extend(_generate_weight_selection_section(weight_result))

    # v2.2: 第八部分：股票选股结果（新增）
    # v2.19: 提取 comp_weights 传入选股 section，用于因子贡献集中度检测
    stock_comp_weights: dict[str, float] = {}
    best_item = next(
        (item for item in composite_results if item.get("weight_method") == best_weight_method),
        None,
    )
    if best_item:
        if best_weight_method == "rolling_icir_weight":
            weight_meta = best_item.get("weight_meta", {})
            last_day_weights = weight_meta.get("last_day_weights", {})
            stock_comp_weights = last_day_weights if last_day_weights else best_item.get("weights", {})
        else:
            stock_comp_weights = best_item.get("weights", {})

    # v3.17: 分段胜率 (非 ob_quality, 需 T+1 数据; ob_quality 走跨管线汇总)
    import os as _os
    _is_obq = _os.environ.get("PIPELINE_ALIAS", "").startswith("ob_quality")
    if stock_result and not _is_obq:
        stock_meta = stock_result.get("meta", {})
        stock_result["decile_stats"] = load_decile_stats(
            stock_meta.get("weight_method", best_weight_method),
            stock_meta.get("selection_date", date),
            logger,
        )

    stock_lines = _generate_stock_selection_section(stock_result, stock_comp_weights, data_results, stock_name_map)

    # ob_quality 管线: 去掉最终短名单和决策卡片 (LR未训练, 分段分析已替代)
    import os as _os
    if _os.environ.get("PIPELINE_ALIAS", "").startswith("ob_quality"):
        stock_lines = [
            ln for ln in stock_lines
            if "最终短名单" not in ln and "决策卡片" not in ln and "D5 人工核查" not in ln
        ]

    lines.extend(stock_lines)

    # v3.18: ob_quality 跨管线分段胜率汇总
    if stock_result:
        _render_cross_pipeline_summary(lines, stock_result, logger, stock_name_map)

    # ob_quality: 展示今日在历史最佳段(S6/S7)的候选
    if _is_obq and stock_result:
        _render_today_best_segment_candidates(lines, stock_result, stock_name_map)

    return "\n".join(lines)


def _render_cross_pipeline_summary(
    lines: list[str],
    stock_result: dict,
    logger: logging.Logger,
    stock_name_map: dict[str, str] | None = None,
) -> None:
    """ob_quality 全管线每日独立30分段胜率汇总.

    遍历 ob_quality_0615 ~ ob_quality_0624 的 composite daily,
    每日独立 qcut 为 30 段, 计算各段胜率, 输出矩阵表格.
    仅在 ob_quality pipeline 且非临时管线时输出.
    """
    import os

    import pandas as pd
    from paths import COMPREHENSIVE_FACTOR_RESULT

    alias = os.environ.get("PIPELINE_ALIAS", "")
    # 只在 ob_quality 主管线输出 (跳过 ob_quality_0615 等时间递减管线)
    if alias != "ob_quality":
        return

    weight_method = (stock_result.get("meta", {}) or {}).get("weight_method", "rolling_icir_weight")
    daily_filename = f"composite_{weight_method}_1d_daily.parquet"

    # 收集所有 ob_quality_06XX 管线
    parent_dir = COMPREHENSIVE_FACTOR_RESULT.parent  # comprehensive_factor/result/
    pipeline_dirs = sorted(
        [d for d in parent_dir.iterdir() if d.is_dir() and d.name.startswith("ob_quality_")],
        key=lambda d: d.name,
    )

    if len(pipeline_dirs) < 2:
        return

    n_segments = 30
    master_path = Path(DATA_PATHS.get("master_parquet", str(PROJECT_ROOT / "data_fetchers/result/factor_ic_data.parquet")))

    try:
        master_dates = sorted(pd.read_parquet(master_path, columns=["date"])["date"].dropna().unique())
        master_ret = pd.read_parquet(master_path, columns=["date", "asset", "forward_return_1d"])
    except Exception:
        logger.debug("跨管线汇总: 无法读取主数据源, 跳过")
        return

    # 收集每管线的30分段结果
    pipeline_results = []  # [(label, comp_date, trade_date, n_total, seg_stats)]
    for pipe_dir in pipeline_dirs:
        daily_path = pipe_dir / daily_filename
        if not daily_path.exists():
            continue
        try:
            comp_df = pd.read_parquet(daily_path, columns=["date", "asset", "composite_factor"])
        except Exception:
            continue

        # 取最新选股日
        comp_dates = sorted(comp_df["date"].dropna().unique())
        if not comp_dates:
            continue
        selection_date = comp_dates[-1]
        day_df = comp_df[comp_df["date"].astype(str) == selection_date]
        if len(day_df) < 20:
            continue

        # 找下一个交易日
        try:
            idx = master_dates.index(selection_date)
            trade_date = master_dates[idx + 1]
        except (ValueError, IndexError):
            continue

        ret_df = master_ret[master_ret["date"] == trade_date]
        merged = pd.merge(day_df, ret_df[["asset", "forward_return_1d"]], on="asset", how="inner")
        if len(merged) == 0:
            continue

        merged["rank"] = merged["composite_factor"].rank(ascending=False)
        try:
            merged["seg"] = pd.qcut(merged["rank"], n_segments, labels=[f"S{i+1}" for i in range(n_segments)])
        except ValueError:
            continue

        seg_stats = {}
        for seg_label in [f"S{i+1}" for i in range(n_segments)]:
            sub = merged[merged["seg"] == seg_label]
            ret_vals = sub["forward_return_1d"].dropna()
            w = (ret_vals > 0).sum()
            t = len(ret_vals)
            seg_stats[seg_label] = {"wins": w, "total": t, "wr": w / t * 100 if t > 0 else 0}

        label = pipe_dir.name.replace("ob_quality_", "")
        pipeline_results.append((label, selection_date, trade_date, len(merged), seg_stats))

    if len(pipeline_results) < 2:
        return

    n_pipes = len(pipeline_results)
    lines.append("")
    lines.append("=" * 70)
    lines.append(f"九、ob_quality 全管线 {n_segments}分段胜率汇总 (每日独立选股)")
    lines.append("-" * 70)
    lines.append(f"  共 {n_pipes} 条时间递减管线, 每天独立按 composite 排名切 {n_segments} 段")
    lines.append("  选股日 → T+1交易日 (T-1 对齐), 统计 forward_return_1d")
    lines.append("")

    # 表头: 段 | date1 date2 ... | 合并
    header = f"  {'段':<6}"
    date_labels = [r[0] for r in pipeline_results]
    for dl in date_labels:
        header += f" {dl:>6}"
    header += f" {'合并':>8}"
    lines.append(header)
    lines.append("  " + "-" * (8 + 8 * n_pipes + 10))

    # 每段一行
    best_overall_wr = 0
    best_overall_seg = ""
    for seg_label in [f"S{i+1}" for i in range(n_segments)]:
        row = f"  {seg_label:<6}"
        total_w = 0
        total_n = 0
        for _, _, _, _, seg_stats in pipeline_results:
            ss = seg_stats.get(seg_label, {"wins": 0, "total": 0})
            wr = ss["wr"]
            total_w += ss["wins"]
            total_n += ss["total"]
            if ss["total"] > 0:
                row += f" {wr:>5.0f}% "
            else:
                row += f" {'--':>5} "
        overall_wr = total_w / total_n * 100 if total_n > 0 else 0
        row += f" {overall_wr:>7.1f}%"
        if overall_wr > best_overall_wr:
            best_overall_wr = overall_wr
            best_overall_seg = seg_label
        lines.append(row)

    lines.append("  " + "-" * (8 + 8 * n_pipes + 10))
    lines.append(f"  最佳段: {best_overall_seg} (合并胜率 {best_overall_wr:.1f}%)")
    lines.append("")

    # 最佳段逐日
    lines.append(f"  {best_overall_seg} 逐日胜率:")
    for label, _, _, _, seg_stats in pipeline_results:
        ss = seg_stats.get(best_overall_seg, {"wins": 0, "total": 0, "wr": 0})
        lines.append(f"    {label:>6}: {ss['wins']}/{ss['total']} = {ss['wr']:.1f}%")
    lines.append("")

def _render_today_best_segment_candidates(
    lines: list,
    stock_result: dict,
    stock_name_map: dict | None,
) -> None:
    """展示今日落在历史最佳段(S6/S7)的候选股票."""
    import pandas as pd
    from paths import COMPREHENSIVE_FACTOR_RESULT

    weight_method = (stock_result.get("meta", {}) or {}).get("weight_method", "rolling_icir_weight")
    daily_path = COMPREHENSIVE_FACTOR_RESULT / f"composite_{weight_method}_1d_daily.parquet"
    if not daily_path.exists():
        return

    comp = pd.read_parquet(daily_path, columns=["date", "asset", "composite_factor"])
    dates = sorted(comp["date"].dropna().unique())
    if not dates:
        return
    latest = dates[-1]
    today = comp[comp["date"] == latest].copy()
    today["rank"] = today["composite_factor"].rank(ascending=False)
    n_stocks = len(today)

    seg_ranges = [("S6 (rank 21-25)", 21, 25), ("S7 (rank 26-30)", 26, 30)]
    name_map = stock_name_map or {}

    lines.append("")
    lines.append("十、今日历史最佳段候选")
    lines.append("-" * 70)
    lines.append(f"  选股日: {latest}, 候选池共 {n_stocks} 只")
    lines.append(f"  历史验证: S6合并胜率 69.2%, S7合并胜率 65.5%")
    lines.append(f"  操作: 今日尾盘买入 -> 下一交易日卖出 (高开开盘锁利, 低开等反抽减亏)")
    lines.append("")

    for seg_name, rmin, rmax in seg_ranges:
        subset = today[(today["rank"] >= rmin) & (today["rank"] <= rmax)].sort_values("rank")
        if len(subset) == 0:
            continue
        lines.append(f"  [{seg_name}] {len(subset)} 只")
        lines.append(f"  {'排名':>4} {'代码':<10} {'名称':<8} {'composite':>10}")
        lines.append("  " + "-" * 38)
        for _, s in subset.iterrows():
            code = s["asset"]
            nm = name_map.get(code, "--")
            cv = s["composite_factor"]
            rk = int(s["rank"])
            lines.append(f"  {rk:>4} {code:<10} {nm:<8} {cv:>10.3f}")
        lines.append("  " + "-" * 38)
        lines.append("")


def main():
    """主函数"""
    # 初始化日志记录器
    logger = setup_logger("generate_factor_summary_report")

    # 记录开始时间（用于计算总耗时）
    start_time = time.time()
    logger.info("开始生成汇总报告 (版本 %s)", __version__)

    parser = argparse.ArgumentParser(description="生成因子分析数据汇总报告")
    parser.add_argument("--date", type=str, help="指定日期 (YYYY-MM-DD)，默认当天")
    parser.add_argument(
        "--output", type=str, help="输出文件路径，默认 summary/result/factor_summary_report_YYYY-MM-DD.txt"
    )
    parser.add_argument("--full-correlation", action="store_true", help="强制计算所有因子之间的相关性（可能较慢）")

    args = parser.parse_args()

    date = get_date_str(args.date)
    report = generate_report(date, logger, force_full_correlation=args.full_correlation)

    # 默认输出到 summary/result/<alias>/ 目录（pipeline 感知）
    if args.output:
        output_path = Path(args.output)
    else:
        from paths import SUMMARY_RESULT

        result_dir = SUMMARY_RESULT
        result_dir.mkdir(parents=True, exist_ok=True)
        output_path = result_dir / f"factor_summary_report_{date}.txt"

    # 文件写入异常处理
    try:
        output_path.write_text(report, encoding="utf-8")
        logger.info("报告已保存到: %s", output_path)
    except OSError as e:
        logger.error("文件写入失败: %s, 原因: %s", output_path, e)
        sys.exit(1)

    # 记录总耗时
    elapsed = time.time() - start_time
    logger.info("报告生成完成，总耗时: %.2f秒", elapsed)


if __name__ == "__main__":
    main()
