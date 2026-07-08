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

import pandas as pd


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
    _render_intraday_strategy_section,
)
from summary.report.segment_win_db import (  # noqa: E402
    compute_intraday_strategy,
    load_segment_stock_details,
    load_segment_win_rates,
    save_segment_stock_details,
    save_segment_win_rates,
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

    # ob_quality 管线: 精简报告, 去掉不需要的章节
    import os as _os2

    if _os2.environ.get("PIPELINE_ALIAS", "").startswith("ob_quality"):
        section_kw = [
            "二次排序",
            "因子标准化值(z-score)",  # v3.x: ob_quality 不需要因子 z-score 详细表
            "主导前 3 因子（贡献占比）",  # v3.x: ob_quality 不需要因子贡献简表
            "决策卡片",  # v3.x: 块级移除 D1/D2/D3/D4 质量明细表
            "D5 人工核查",  # v3.x: 块级移除 D5 人工核查清单
        ]  # 匹配到后整段移除(含后续行直到下一个【或空行)
        result = []
        skip = False
        for ln in stock_lines:
            stripped = ln.strip()
            if any(kw in stripped for kw in section_kw):
                skip = True
                continue
            if skip:
                # 遇到下一个章节标题或空行结束跳过
                if stripped.startswith("【") or stripped == "":
                    skip = False
                else:
                    continue
            # 也要过滤掉单行关键词 (冗余防护, 防块级跳过未触发时仍能过滤)
            if any(kw in stripped for kw in ["最终短名单", "Top 10 详表", "短名单 11"]):
                continue
            result.append(ln)
        stock_lines = result

    lines.extend(stock_lines)

    # v3.18: ob_quality 跨管线分段胜率汇总
    seg9_result = None  # 来自 §9 的返回 (新结构 dict)
    if stock_result and _os.environ.get("PIPELINE_ALIAS", "").startswith("ob_quality"):
        # All ob_quality* pipelines:
        #   1. Write today's stock details (no win rate yet)
        _save_today_segment_details(stock_result, logger)
        #   2. Compute win rates for pending dates (forward_return_1d now available)
        _compute_pending_win_rates(logger)

    if stock_result and _os.environ.get("PIPELINE_ALIAS", "") == "ob_quality":
        # Main pipeline only: render Section 9 from Parquet
        seg9_result = _render_cross_pipeline_summary(lines, stock_result, logger, stock_name_map)
        # 向后兼容: 解包 §9 返回值, 让 §10 段明细渲染仍可用 stats[seg_label]
        seg_merge_stats = seg9_result.get("merge_stats", {}) if isinstance(seg9_result, dict) else None
        # §9 best_seg 是 §10 要选的最高胜率段 (替代原来的硬写 S6)
        best_seg_from_sec9 = seg9_result.get("best_seg") if isinstance(seg9_result, dict) else None
        # v2.1: 按 pending dates 补跑 intraday_strategy (6-30 补 6-29, 7-01 补 6-30, ...)
        # 设计意图: D+1 日当晚跑批时, D 日 close + D+1 日 OHLC 已齐备,
        # 应在 §10 渲染前补齐历史 selection_date 的 intraday_strategy 行, 让 fallback
        # 时返回的 selection_date 是最新的一个, 而不是 6-26 这种 N 天前的快照.
        # 见 _compute_pending_intraday_strategy docstring 的设计意图段.
        if best_seg_from_sec9:
            weight_method_for_strategy = stock_result.get("meta", {}).get("weight_method", "rolling_icir_weight")
            _compute_pending_intraday_strategy(
                pipeline="ob_quality",
                weight_method=weight_method_for_strategy,
                segment_label=best_seg_from_sec9,
                logger=logger,
            )
    else:
        seg_merge_stats = None
        best_seg_from_sec9 = None

    # ob_quality: 展示今日三十分段候选明细
    if _is_obq and stock_result:
        _render_today_best_segment_candidates(lines, stock_result, stock_name_map, seg_merge_stats)

    # v2.3: 胜率最高段日内操作建议 (§10) — 段标签数据驱动, 默认 §9 算的合并胜率最高段
    if _is_obq and stock_result:
        try:
            from summary.report.data_loaders import load_intraday_strategy as _load_strategy

            weight_method = stock_result.get("meta", {}).get("weight_method", "rolling_icir_weight")
            # 段标签优先用 §9 算的合并胜率最高段; fallback = None (不限段, 适配 §9 数据不足)
            target_seg = best_seg_from_sec9
            target_date = date

            # 1. 计算 + 落盘 (idempotent: 同 key 旧行去重覆盖)
            compute_intraday_strategy(
                pipeline="ob_quality",
                weight_method=weight_method,
                selection_date=target_date,
                logger=logger,
                segment_label=target_seg if target_seg else "S6",
            )
            # 2. 读 + 渲染
            strategy_rows = _load_strategy(
                pipeline="ob_quality",
                weight_method=weight_method,
                selection_date=target_date,
                logger=logger,
                segment_label=target_seg,
            )
            used_fallback_date = None
            # Fallback: 当 T+1 数据未到位 (今天还在开盘 / 06:30 没数据), 用最近一个有 T+1 的日期
            if not strategy_rows:
                fallback_date = _find_latest_intraday_date(
                    pipeline="ob_quality",
                    weight_method=weight_method,
                    logger=logger,
                )
                if fallback_date and fallback_date != date:
                    used_fallback_date = fallback_date
                    logger.info(
                        "%s 无 T+1 OHLC, §10 fallback 到最近一日 %s",
                        date,
                        fallback_date,
                    )
                    # fallback 日也要用 §9 在该日算的最佳段 — 这里简化: 重跑当日 §9 收益汇总
                    fb_seg9 = _compute_best_seg_for_date(
                        pipeline="ob_quality",
                        weight_method=weight_method,
                        selection_date=fallback_date,
                        logger=logger,
                    )
                    compute_intraday_strategy(
                        pipeline="ob_quality",
                        weight_method=weight_method,
                        selection_date=fallback_date,
                        logger=logger,
                        segment_label=fb_seg9 or "S6",
                    )
                    target_seg = fb_seg9 or target_seg
                    strategy_rows = _load_strategy(
                        pipeline="ob_quality",
                        weight_method=weight_method,
                        selection_date=fallback_date,
                        logger=logger,
                        segment_label=target_seg,
                    )

            # 段标题展示 (如果 §9 数据不足, 段标签 fallback 到 S6, 加说明)
            sec9_note = None
            if not best_seg_from_sec9:
                sec9_note = "⚠️ §9 数据不足 (<2日), §10 暂用 S6 段默认值, 累计更多管线数据后会自动选胜率最高段"
                target_seg = target_seg or "S6"

            if strategy_rows:
                trade_date_hint = strategy_rows[0].get("trade_date") if strategy_rows else None
                # 数据驱动: 计算历史实战样本的高开/低开胜率 (用于 §10 底部展示)
                from summary.report.sections import _compute_intraday_historical_stats

                historical_stats = _compute_intraday_historical_stats(
                    pipeline="ob_quality",
                    weight_method=weight_method,
                )
                _render_intraday_strategy_section(
                    rows=strategy_rows,
                    lines=lines,
                    selection_date=used_fallback_date or date,
                    trade_date=trade_date_hint,
                    stock_name_map=stock_name_map,
                    is_fallback=used_fallback_date is not None,
                    segment_label=target_seg or "S6",
                    seg9_note=sec9_note,
                    historical_stats=historical_stats,
                )
        except Exception as e:
            logger.warning("§10 intraday strategy 渲染失败, 跳过: %s", str(e)[:200])

    return "\n".join(lines)


def _find_latest_intraday_date(
    pipeline: str,
    weight_method: str,
    logger: logging.Logger,
) -> str | None:
    """找到 parquet 中最新一个有 intraday_strategy 数据的 selection_date.

    当今天是没有 T+1 OHLC 的最新交易日时, 用这个 fallback 出最近一日.
    """
    try:
        from summary.report.segment_win_db import (
            _INTRADAY_STRATEGY_PATH,
        )

        df = pd.read_parquet(_INTRADAY_STRATEGY_PATH, columns=["selection_date"])
        mask = df["selection_date"].notna()
        df = df[mask]
        if df.empty:
            return None
        sub_series = df["selection_date"].astype("string")
        sub_filtered = sub_series[sub_series.str.match(r"^\d{4}-\d{2}-\d{2}$")]
        if sub_filtered.empty:
            return None
        # 取最大日期 (最近一日)
        latest = sorted(sub_filtered.unique().tolist())[-1]
        logger.debug("latest intraday date for %s/%s = %s", pipeline, weight_method, latest)
        return latest
    except Exception:
        logger.exception("找最近 intraday 日期失败")
        return None


def _compute_best_seg_for_date(
    pipeline: str,
    weight_method: str,
    selection_date: str,
    logger: logging.Logger,
) -> str | None:
    """从 segment_win_rates.parquet 找到指定日期所在批次的最佳段标签.

    用法: fallback 路径下, 我们想要 fallback 日所在的批次 (含该日的窗口)
    的合并胜率最高段, 而不是整个 parquet 的全局最高段 (因为那可能跨越不同
    市场环境).

    简化: 这里直接返回 _render_cross_pipeline_summary 算出的全局 best_seg
    (跨日期聚合), 因为设计原意就是用合并胜率, 而不是单日.
    """
    try:
        db_results = load_segment_win_rates(pipeline, weight_method)
        if len(db_results) < 2:
            return None
        # 跨日聚合, 复用 §9 的 max 逻辑
        merge_stats: dict[str, dict] = {}
        for r in db_results:
            for seg, ss in r["seg_stats"].items():
                if seg not in merge_stats:
                    merge_stats[seg] = {"wins": 0, "total": 0}
                merge_stats[seg]["wins"] += ss.get("wins", 0)
                merge_stats[seg]["total"] += ss.get("total", 0)
        best_seg = None
        best_wr = -1.0
        for seg, ss in merge_stats.items():
            n = ss["total"]
            if n == 0:
                continue
            wr = ss["wins"] / n
            if wr > best_wr:
                best_wr = wr
                best_seg = seg
        logger.debug("best seg for fallback date %s = %s (wr=%.3f)", selection_date, best_seg, best_wr)
        return best_seg
    except Exception:
        logger.exception("算 fallback 日期最佳段失败, fallback date=%s", selection_date)
        return None


def _save_today_segment_details(
    stock_result: dict,
    logger: logging.Logger,
) -> None:
    """T 日: 写当前管线的 30 段股票明细到 segment_stock_details.parquet.

    不等收益——只存选股结果。T+1 由 _compute_pending_win_rates 读取后算胜率.
    """
    import os

    import pandas as pd
    from paths import COMPREHENSIVE_FACTOR_RESULT

    alias = os.environ.get("PIPELINE_ALIAS", "")
    weight_method = (stock_result.get("meta", {}) or {}).get("weight_method", "rolling_icir_weight")
    daily_path = COMPREHENSIVE_FACTOR_RESULT / f"composite_{weight_method}_1d_daily.parquet"
    if not daily_path.exists():
        logger.debug("composite daily 不存在: %s (跳过落库)", daily_path)
        return

    try:
        comp_df = pd.read_parquet(daily_path, columns=["date", "asset", "composite_factor"])
    except Exception:
        logger.debug("读取 composite daily 失败: %s", daily_path, exc_info=True)
        return

    comp_dates = sorted(comp_df["date"].dropna().unique())
    if not comp_dates:
        return
    selection_date = str(comp_dates[-1])
    # R48 bugfix v1.5.18: dropna composite_factor 先, 防 NaN rank 让 qcut 抛 ValueError.
    # 历史上 5 个 NaN 让 46 行 → 41 行整数 rank 切 30 段 → bin edges 撞到 40.0 重复
    # → qcut ValueError → except: return 静默吞掉 → 报告 §10 用昨天的 dates[-1] 冒充今天.
    day_df = comp_df[comp_df["date"].astype(str) == selection_date].dropna(subset=["composite_factor"]).copy()
    if len(day_df) < 20:
        logger.debug(
            "composite daily %s NaN-dropped 后样本数 < 20 (raw=%d), 跳过落库",
            selection_date,
            len(comp_df[comp_df["date"].astype(str) == selection_date]),
        )
        return

    n_segments = 30
    day_df["rank"] = day_df["composite_factor"].rank(ascending=False, method="first")
    try:
        day_df["seg"] = pd.qcut(day_df["rank"], n_segments, labels=[f"S{i + 1}" for i in range(n_segments)])
    except ValueError:
        # R48 bugfix v1.5.18: 不能 silent return. 让异常对运维可见, 否则下一次
        # 类似 41 行切 30 段的 boundary 重复 case 还会被静默吞掉.
        logger.exception(
            "qcut 30 段失败 (selection_date=%s, %d 行有效 rank), 跳过落库. 详见 stock_result 完整性.",
            selection_date,
            len(day_df),
        )
        return

    # 按段分组
    seg_stocks: dict[str, list[dict]] = {}
    for seg_label in [f"S{i + 1}" for i in range(n_segments)]:
        subset = day_df[day_df["seg"] == seg_label].sort_values("rank")
        seg_stocks[seg_label] = [
            {"asset": row["asset"], "composite_value": float(row["composite_factor"]), "rank": int(row["rank"])}
            for _, row in subset.iterrows()
        ]

    try:
        save_segment_stock_details("ob_quality", weight_method, selection_date, seg_stocks)
        logger.info("stock_details 落库: %s (%s/%s) %d 只", alias, weight_method, selection_date, len(day_df))
    except Exception:
        logger.warning("stock_details 落库失败: %s/%s", alias, selection_date, exc_info=True)


def _compute_pending_win_rates(logger: logging.Logger) -> None:
    """T+1: 遍历 stock_details 中所有日期, 有 forward_return_1d 就算胜率.

    读取 segment_stock_details, 按 weight_method 分组,
    对比 segment_win_rates 中已有日期,
    对未计算胜率的日期尝试匹配 forward_return_1d → qcut → 写 win_rates.

    数据源: 必须读 master 全市场数据 (FACTOR_IC_DATA_MASTER),
    不能读 pipeline alias 切片 (FACTOR_IC_DATA, e.g. ob_quality/factor_ic_data.parquet).
    原因: alias 切片只含「股票池筛选通过」的股票. 若一只股票当天不满足
    pipeline filter (e.g. ob_quality 的 rsi_6 > 70 and turnover_rate > 5),
    alias 切片会剔除该股票, 但其 forward_return_1d 在 master 中依然真实存在.
    若胜率计算用 alias 切片, 会造成"非业务原因"的样本丢失, 例如 002861
    在 2026-06-30 换手率 4.92% < 5% 被 ob_quality 排除, 但胜率应基于
    master 的 +5.79% 计算. 设计意图 (与 compute_intraday_strategy 一致):
    胜率/价格 = master; 股票池筛选 = alias. 详见 MODULE.md §数据来源规范.
    """
    import pandas as pd
    from paths import FACTOR_IC_DATA_MASTER

    # 读取所有 stock_details 日期
    stock_df = load_segment_stock_details("ob_quality")
    if stock_df.empty:
        return

    # 按 weight_method 分组处理
    all_weight_methods = sorted(stock_df["weight_method"].unique())

    # 读取 master 全市场数据 (NOT alias 切片)
    try:
        master_dates = sorted(pd.read_parquet(FACTOR_IC_DATA_MASTER, columns=["date"])["date"].dropna().unique())
        master_ret = pd.read_parquet(FACTOR_IC_DATA_MASTER, columns=["date", "asset", "forward_return_1d"])
    except Exception:
        logger.debug("_compute_pending_win_rates: 无法读取 master 主数据源 %s", FACTOR_IC_DATA_MASTER)
        return

    n_segments = 30
    total_computed = 0
    for weight_method in all_weight_methods:
        wm_stock_df = stock_df[stock_df["weight_method"] == weight_method]
        all_dates = sorted(wm_stock_df["selection_date"].unique())

        # 读取已计算胜率的日期
        done_dates: set[str] = set()
        try:
            existing_wins = load_segment_win_rates("ob_quality", weight_method)
            done_dates = {r["selection_date"] for r in existing_wins}
        except Exception:
            pass

        pending = [d for d in all_dates if d not in done_dates]
        if not pending:
            continue

        computed = 0
        for selection_date in pending:
            # 找下一个交易日
            try:
                idx = master_dates.index(selection_date)
                trade_date = master_dates[idx + 1]
            except (ValueError, IndexError):
                logger.debug("_compute_pending: %s 无 T+1 交易日", selection_date)
                continue

            ret_df = master_ret[master_ret["date"] == trade_date]
            if ret_df.empty or ret_df["forward_return_1d"].dropna().empty:
                logger.debug("_compute_pending: %s forward_return_1d[%s] 全 NaN (等待数据)", selection_date, trade_date)
                continue

            # 取该日股票明细
            day_stocks = wm_stock_df[wm_stock_df["selection_date"] == selection_date]
            if day_stocks.empty:
                continue

            # merge 收益
            merged = pd.merge(
                day_stocks[["asset", "segment_label", "rank"]],
                ret_df[["asset", "forward_return_1d"]],
                on="asset",
                how="inner",
            )
            if len(merged) == 0:
                continue

            # qcut (按原 rank 排序)
            merged = merged.sort_values("rank")

            # 按 segment_label 分组算胜率
            seg_stats = {}
            for seg_label in sorted(day_stocks["segment_label"].unique()):
                sub = merged[merged["segment_label"] == seg_label]
                ret_vals = sub["forward_return_1d"].dropna()
                w = int((ret_vals > 0).sum())
                t = len(ret_vals)
                seg_stats[seg_label] = {"wins": w, "total": t, "wr": w / t * 100 if t > 0 else 0}

            try:
                save_segment_win_rates(
                    pipeline="ob_quality",
                    selection_date=selection_date,
                    trade_date=str(trade_date),
                    weight_method=weight_method,
                    n_segments=n_segments,
                    n_total=len(merged),
                    seg_stats=seg_stats,
                )
                computed += 1
            except Exception:
                logger.warning(
                    "_compute_pending: 写 win_rates 失败 %s/%s", weight_method, selection_date, exc_info=True
                )

        if computed:
            logger.info("_compute_pending_win_rates: %s 完成 %d 个新日期", weight_method, computed)
            total_computed += computed

    if total_computed:
        logger.info("_compute_pending_win_rates: 全部完成 %d 个新日期", total_computed)


def _compute_pending_intraday_strategy(
    pipeline: str,
    weight_method: str,
    segment_label: str,
    logger: logging.Logger,
) -> None:
    """T+1: 按 pending dates 补跑 intraday_strategy.

    设计意图（为什么这是这个模块的核心设计）:
      - D 日 9:30 开盘选股 → D 日尾盘买入 → D+1 早盘按 S9 段指引卖出
      - intraday_strategy 的数据需求: D 日 close (prev_close) + D+1 日 OHLC
      - 因此 D+1 日当晚 (即下一次 summary 脚本运行时), 既有的 stock_details
        + D+1 当日收盘价都已齐备, 可以完整补跑 D 日的 intraday_strategy 行
      - 当前 (修复前) §10 渲染时只在 schedule 里调用一次
        `compute_intraday_strategy(selection_date=today)` —— 这导致
        historical dates 的 intraday_strategy 行永远不会被写入, 后续的报告
        只能 fallback 到一份**很旧**的快照, 实战参考价值随时间衰减为零

    与 _compute_pending_win_rates 完全类比的设计:
      - pending = stock_details 中所有 selection_date, 减去
        segment_intraday_strategy.parquet 中已有 (selection_date, segment_label) 的 (sd, segment_label) 元组
      - 对每个 pending sd: 调用 compute_intraday_strategy(sd, segment_label=best_seg)
      - compute_intraday_strategy 内含 OHLC + segment_label + master date 完备检查, 失败时静默 skip

    Args:
        pipeline: 'ob_quality' (固定)
        weight_method: 权重方法
        segment_label: §9 算出的合并胜率最高段 (best_seg), 用于补跑
        logger: 日志记录器

    Returns:
        None
    """
    try:
        from summary.report.segment_win_db import (
            _INTRADAY_STRATEGY_PATH,
            INTRADAY_STRATEGY_COLUMNS,
            _read_parquet,
            compute_intraday_strategy,
            load_segment_stock_details,
        )
    except ImportError:
        logger.debug("_compute_pending_intraday_strategy: 模块不可用, 跳过")
        return

    try:
        # 读全部 stock_details (不限段, 因为 segment_label 只是 best_seg 一个)
        stock_df = load_segment_stock_details(pipeline, weight_method=weight_method)
    except Exception:
        logger.debug("_compute_pending_intraday_strategy: 读 stock_details 失败, 跳过")
        return
    if stock_df.empty:
        return

    all_dates = sorted(stock_df["selection_date"].unique())
    if not all_dates:
        return

    # 已有的 (selection_date, segment_label) 集合, 直接读 parquet 过滤
    done_pairs: set[tuple[str, str]] = set()
    try:
        df = _read_parquet(_INTRADAY_STRATEGY_PATH, INTRADAY_STRATEGY_COLUMNS)
        if not df.empty:
            mask = (df["pipeline"] == pipeline) & (df["weight_method"] == weight_method)
            df = df[mask]
            done_pairs = set(zip(df["selection_date"].astype(str), df["segment_label"].astype(str)))
    except Exception:
        logger.debug("_compute_pending_intraday_strategy: 读已有 intraday_strategy 失败")

    computed = 0
    for sd in all_dates:
        if (sd, segment_label) in done_pairs:
            continue
        try:
            out = compute_intraday_strategy(
                pipeline=pipeline,
                weight_method=weight_method,
                selection_date=sd,
                logger=logger,
                segment_label=segment_label,
            )
        except Exception:
            logger.warning("intraday_strategy 补跑失败 %s/%s/%s", pipeline, weight_method, sd, exc_info=True)
            continue
        if out is not None and not out.empty:
            computed += 1

    if computed:
        logger.info(
            "_compute_pending_intraday_strategy: %s/%s/段%s 完成 %d 个新日期",
            pipeline,
            weight_method,
            segment_label,
            computed,
        )


def _render_cross_pipeline_summary(
    lines: list[str],
    stock_result: dict,
    logger: logging.Logger,
    stock_name_map: dict[str, str] | None = None,
) -> dict | None:
    """ob_quality 主管线 Section 9: 从 Parquet 读全量 30 段胜率渲染.

    纯读 segment_win_rates.parquet, 不扫目录.

    Returns:
        {"merge_stats": {S1: {...}}, "best_seg": "S6", "best_wr": 65.5}
        或 None (< 2 日数据时)
    """
    weight_method = (stock_result.get("meta", {}) or {}).get("weight_method", "rolling_icir_weight")
    n_segments = 30

    db_results = load_segment_win_rates("ob_quality", weight_method)
    if len(db_results) < 2:
        logger.debug("segment_win_rates 数据不足 (%d 日), 跳过 Section 9", len(db_results))
        return None

    pipeline_results = [
        (r["selection_date"][5:], r["selection_date"], r["trade_date"], r["n_total"], r["seg_stats"])
        for r in db_results
    ]

    n_pipes = len(pipeline_results)
    lines.append("")
    lines.append("=" * 70)
    lines.append(f"九、ob_quality 全管线 {n_segments}分段胜率汇总 (每日独立选股)")
    lines.append("-" * 70)
    lines.append(f"  共 {n_pipes} 个选股日期, 每天独立按 composite 排名切 {n_segments} 段")
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

    # 每段一行, 同时收集合并统计用于第十部分
    best_overall_wr = 0
    best_overall_seg = ""
    merge_stats: dict[str, dict] = {}
    for seg_label in [f"S{i + 1}" for i in range(n_segments)]:
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
        merge_stats[seg_label] = {"wins": total_w, "total": total_n, "wr": overall_wr}
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

    return {
        "merge_stats": merge_stats,
        "best_seg": best_overall_seg,
        "best_wr": best_overall_wr,
    }


def _render_today_best_segment_candidates(
    lines: list,
    stock_result: dict,
    stock_name_map: dict | None,
    seg_merge_stats: dict[str, dict] | None = None,
) -> None:
    """展示今日三十分段候选明细.

    从 segment_stock_details.parquet 读取最新日期的股票明细（T 日已落库），
    每段展示股票明细 + 历史合并胜率.

    R48 bugfix v1.5.18: 引入 expected_date vs actual_date 区分.
    expected_date = stock_result 的 meta.select_xxx_date (T 日应有日期).
    actual_date = segment_stock_details 里实际最晚的日期.
    如果不等 (e.g. T 日落库没成功), 报告头标 [⚠️ fallback], 让 user 一眼能看到.
    之前 R47 silent fallback bug: dates[-1] = 07-06 冒充 07-07, 无任何标记.
    """
    weight_method = (stock_result.get("meta", {}) or {}).get("weight_method", "rolling_icir_weight")

    # 直接读 stock_details, 不再重复读 composite_daily + qcut
    stock_df = load_segment_stock_details("ob_quality", weight_method=weight_method)
    if stock_df.empty:
        return

    dates = sorted(stock_df["selection_date"].unique())
    latest = dates[-1]
    today = stock_df[stock_df["selection_date"] == latest].copy()
    n_stocks = len(today)
    if n_stocks == 0:
        return

    # R48: 检测 silent fallback. expected = selection_date (T-1 友好表达, 这里用 stock_result
    # 最近一次 selection_date; R47 root case 07-08 报告应有 selection_date=2026-07-07).
    # stock_result.get('meta') 没有 selection_date 字段, fallback 用 date 参数 (报告生成日) 或 today_str().
    # 设计意图: expected_date 不是用来强校验, 而是用来"今天应有日期 vs 实际最晚"对比.
    expected_date = stock_result.get("selection_date")
    if not expected_date:
        # 从 stock_result 取 weight_selection_result.json 里的 date
        try:
            wm_results = stock_result.get("weight_selection_results", [])
            for wm in wm_results:
                if wm.get("weight_method") == weight_method:
                    expected_date = wm.get("selection_date")
                    break
        except (AttributeError, TypeError):
            pass
    if not expected_date:
        # 最后保底: 用 stock_result 任意顶层 date 字段
        expected_date = stock_result.get("date") or stock_result.get("target_date") or stock_result.get("report_date")
    if not expected_date:
        expected_date = latest  # 实在拿不到就认命, 不强标 fallback

    is_fallback = str(expected_date) != str(latest)

    n_segments = 30
    name_map = stock_name_map or {}

    # R48 v1.5.18: 报告头加 expected_date 标注 + fallback 警示
    if is_fallback:
        fallback_note = (
            f"  [⚠️ fallback] 应有选股日 {expected_date} 在 segment_stock_details 缺失, "
            f"实际展示最晚一日 {latest} (数据回退, 不是今天)"
        )
    else:
        fallback_note = ""

    lines.append("")
    lines.append("十、今日三十分段候选明细")
    lines.append("-" * 70)
    lines.append(f"  选股日: {latest}, 候选池共 {n_stocks} 只, 切 {n_segments} 段")
    if fallback_note:
        lines.append(fallback_note)
    lines.append(f"  权重方法: {weight_method}")
    lines.append("  操作: 今日尾盘买入 -> 下一交易日卖出 (高开开盘锁利, 低开等反抽减亏)")
    lines.append("")

    for seg_label in [f"S{i + 1}" for i in range(n_segments)]:
        subset = today[today["segment_label"] == seg_label].sort_values("rank")
        if len(subset) == 0:
            continue

        # 获取合并胜率
        wr_str = ""
        if seg_merge_stats:
            ss = seg_merge_stats.get(seg_label, {})
            wr = ss.get("wr", 0)
            if ss.get("total", 0) > 0:
                wr_str = f" 合并胜率: {wr:.1f}%"

        lines.append(f"  [{seg_label}] {len(subset)} 只{wr_str}")
        lines.append(f"  {'排名':>4} {'代码':<10} {'名称':<8} {'composite':>10}")
        lines.append("  " + "-" * 38)
        for _, s in subset.iterrows():
            code = s["asset"]
            nm = name_map.get(code, "--")
            cv = s["composite_value"]
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
