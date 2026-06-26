"""报告各 Section 渲染函数。

从 generate_factor_summary_report.py 迁移（v3.8 拆分重构）。
包含 IC、回测、综合因子、权重选择、选股结果、对比等 section 渲染。
"""

import pandas as pd
from comprehensive_factor.composite_decision_card import CHECKLIST_D5
from factor_definitions import FACTOR_DEFINITIONS, FACTOR_NAME_TO_COL_MAP
from summary.report.constants import (
    COL_TO_FACTOR_NAME_MAP,
    setup_logger,
)
from summary.report.factor_analysis import (
    _compute_factor_concentration,
    _detect_duplicate_zscores,
    _detect_weight_rank_anomalies,
    _format_neutral_cell,
    _generate_neutralization_notes,
)
from summary.report.formatters import (
    format_float,
    format_percentage,
    get_weight_method_display,
)


def _generate_ic_section(ic_results: list[dict], backtest_results: list[dict] | None = None) -> list[str]:
    """生成单因子 IC 数据汇总部分

    v2.0 (2026-06-02): 新增因子定义列展示
    v2.1 (2026-06-02): 调整列宽以完整展示定义

    Args:
        ic_results: IC 结果列表

    Returns:
        报告文本行列表
    """
    lines = []
    lines.append("")
    lines.append("一、单因子 IC 数据汇总")
    lines.append("-" * 150)
    lines.append(
        f"{'因子':<20} {'定义':<50} {'IC均值':>8} {'ICIR':>6} "
        f"{'IC标准差':>8} {'有效天数':>6} {'中性化敏感':>10} {'中性化方式':>14}"
    )
    lines.append("-" * 150)

    for item in ic_results:
        factor_name = item["factor_name"]
        # 获取因子定义（如果无定义则显示空）
        factor_def = FACTOR_DEFINITIONS.get(factor_name, "")
        # 截断定义以适应表格宽度（最多50字符）
        if len(factor_def) > 50:
            factor_def = factor_def[:47] + "..."

        # 中性化敏感度列（design.md §6 / R18b）
        # - enabled=False: '-' (未启用或被排除清单跳过)
        # - decay_rate=None: '-'
        # - high (≥30%): 'XX% ⚠' 高亮 (alpha 主要来自行业 beta)
        # - low/inverse/undefined: 'XX%'
        neutral_cell = _format_neutral_cell(item)
        neutral_method = item.get("neutral_method", "-")

        lines.append(
            f"{factor_name:<20} "
            f"{factor_def:<50} "
            f"{format_float(item['ic_mean']):>8} "
            f"{format_float(item['icir']):>6} "
            f"{format_float(item['ic_std']):>8} "
            f"{item['valid_days']:>6} "
            f"{neutral_cell:>10} "
            f"{neutral_method:>14}"
        )

    lines.append("-" * 150)
    ic_order = ", ".join([f"{r['factor_name']}({r['icir']:.2f})" for r in ic_results[:5]])
    lines.append(f"IC排序(ICIR降序): {ic_order}")

    # v2.6: 问题5修复 - 异常数据说明
    lines.append("")
    lines.append("【异常数据说明】")

    # v2.11: 短样本因子警告——有效天数 < 30 的因子年化收益不可信
    MIN_RELIABLE_DAYS = 30
    short_sample_factors = [r for r in ic_results if r["valid_days"] < MIN_RELIABLE_DAYS]
    if short_sample_factors:
        lines.append(f"⚠ 短样本因子警告（有效天数<{MIN_RELIABLE_DAYS}天，年化收益不可信）:")
        for item in short_sample_factors:
            lines.append(
                f"  - {item['factor_name']}: 有效天数={item['valid_days']}天，年化收益由极少交易日推算，极不稳定"
            )
        lines.append("  说明：年化收益 = (1+总收益)^(252/N) - 1，N很小时收益率被极端放大")

    # 检查 tail_volume_shrink 有效天数异常
    tvs_item = next((r for r in ic_results if r["factor_name"] == "tail_volume_shrink"), None)
    if tvs_item and tvs_item["valid_days"] < 14:
        lines.append(f"tail_volume_shrink 有效天数={tvs_item['valid_days']}天（其他尾盘因子均为14天），数据可能缺失")

    # v2.11: overnight_ret 方向异常深度分析（问题3修复）
    or_item = next((r for r in ic_results if r["factor_name"] == "overnight_ret"), None)
    if or_item and or_item["ic_mean"] > 0:
        other_ic_means = [
            r["ic_mean"] for r in ic_results if r["factor_name"] != "overnight_ret" and r["ic_mean"] is not None
        ]
        if other_ic_means and all(ic < 0 for ic in other_ic_means[:5]):  # 检查前5个因子IC方向
            # 查找 overnight_ret 的回测数据
            bt_or = next((b for b in (backtest_results or []) if b["factor_name"] == "overnight_ret"), None)
            # v2.21: 格式化精度，避免15位小数
            or_sharpe = format_float(bt_or["long_short_sharpe"], 2) if bt_or else "N/A"
            or_mono = format_float(bt_or["monotonicity_correlation"], 2) if bt_or else "N/A"
            lines.append(f"overnight_ret IC均值={or_item['ic_mean']:.4f}为正（其他主要因子均为负），方向异常")
            lines.append("  深度分析：IC方向为正表示隔夜收益大的股票次日收益也大（正向预测），")
            lines.append("           与多数因子（IC为负=因子值大的股票次日收益小）方向相反。")
            lines.append(f"           回测夏普={or_sharpe}, 单调性={or_mono}——可能是有效的反向因子。")
            lines.append("           v2.47: 反向因子标准化值取反对齐到正向语义（综合因子值越大→预期收益越高）。")

    # v2.24: 中性化敏感列说明——极端值和空值解释
    neutral_notes = _generate_neutralization_notes(ic_results)
    if neutral_notes:
        lines.append("")
        lines.append("【中性化敏感列说明】")
        for note in neutral_notes:
            lines.append(note)

    return lines


def _generate_backtest_section(ic_results: list[dict], backtest_results: list[dict]) -> list[str]:
    """生成单因子分层回测数据汇总部分

    v2.24 (2026-06-20): 短样本因子追加⚠标记

    Args:
        ic_results: IC 结果列表（用于排序 + valid_days 短样本标记）
        backtest_results: 回测结果列表

    Returns:
        报告文本行列表
    """
    lines = []
    lines.append("")
    lines.append("二、单因子分层回测数据汇总")
    lines.append("-" * 70)
    lines.append(f"{'因子':<18} {'多空年化收益':>12} {'夏普比率':>8} {'单调性系数':>10} {'单调性质量':>10}")
    lines.append("-" * 70)

    # v2.24: 构建 valid_days 映射，用于短样本标记
    valid_days_map = {r["factor_name"]: r.get("valid_days", 999) for r in ic_results}
    MIN_RELIABLE_DAYS = 30

    # 按 IC 结果顺序排序回测结果
    factor_order_map = {r["factor_name"]: i for i, r in enumerate(ic_results)}
    backtest_sorted = sorted(backtest_results, key=lambda x: factor_order_map.get(x["factor_name"], 999))

    for item in backtest_sorted:
        factor_name = item["factor_name"]
        # v2.24: 短样本因子追加⚠标记
        days = valid_days_map.get(factor_name, 999)
        mark = " ⚠短样本" if days < MIN_RELIABLE_DAYS else ""
        lines.append(
            f"{factor_name:<18} "
            f"{format_percentage(item['long_short_return_annual']):>12} "
            f"{format_float(item['long_short_sharpe'], 2):>8} "
            f"{format_float(item['monotonicity_correlation']):>10} "
            f"{item['monotonicity_symbol']:>10}{mark}"
        )

    lines.append("-" * 70)

    # v2.24: 短样本标记说明
    short_sample_in_table = [name for name, days in valid_days_map.items() if days < MIN_RELIABLE_DAYS]
    if short_sample_in_table:
        lines.append("⚠ 短样本标记: 年化收益由极少交易日推算，极不稳定（有效天数<30天）")

    return lines


def _generate_composite_section(composite_results: list[dict]) -> list[str]:
    """生成综合因子四种权重回测数据汇总部分

    Args:
        composite_results: 综合因子回测结果列表

    Returns:
        报告文本行列表
    """
    lines = []
    lines.append("")
    lines.append("五、综合因子四种权重回测数据汇总")
    lines.append("-" * 70)
    lines.append(
        f"{'权重方法':<20} {'多空年化收益':>12} {'夏普比率':>8} {'单调性系数':>10} {'单调性质量':>10} {'因子权重':<20}"
    )
    lines.append("-" * 70)

    for item in composite_results:
        lines.append(
            f"{item['weight_method_display']:<20} "
            f"{format_percentage(item['long_short_return_annual']):>12} "
            f"{format_float(item['long_short_sharpe'], 2):>8} "
            f"{format_float(item['monotonicity_correlation']):>10} "
            f"{item['monotonicity_symbol']:>10} "
            f"{item['weight_str']:<20}"
        )

    lines.append("-" * 70)

    # v2.12: 方向处理说明——overnight_ret 取反使用
    # 从第一个 composite_result 的 config 中读取 flipped_factors
    flipped_factors = []
    if composite_results:
        first_item = composite_results[0]
        flipped_factors = first_item.get("flipped_factors", [])

    if flipped_factors:
        lines.append("")
        lines.append("【方向处理说明】")
        lines.append(f"  反向因子（IC均值<0）标准化值已取反，对齐到正向语义：{flipped_factors}")
        for f in flipped_factors:
            lines.append(f"  - {f}: IC均值<0(反向因子)，综合因子计算时标准化值取反，做多因子值小的股票")
        lines.append("  说明：v2.47 综合因子方向=positive（正向），所有因子对齐后值大=好信号（高 composite=选中）")

    return lines


def _generate_weight_selection_section(weight_result: dict | None) -> list[str]:
    """生成权重选择结果展示部分

    v2.2 (2026-06-03): 新增权重选择结果展示

    Args:
        weight_result: 权重选择结果字典（可为 None）

    Returns:
        报告文本行列表
    """
    lines = []
    lines.append("")
    lines.append("七、权重选择结果")
    lines.append("-" * 70)

    if weight_result is None:
        lines.append("权重选择结果文件不存在，请先运行 composite_weight_selector.py")
        lines.append("-" * 70)
        return lines

    best_selection = weight_result.get("best_selection", {})
    all_methods = weight_result.get("all_methods", [])

    # 最优方法信息
    best_method = best_selection.get("method", "N/A")
    best_score = best_selection.get("composite_score", 0)

    lines.append(f"最优权重方法: {get_weight_method_display(best_method)}")
    lines.append(f"综合得分: {format_float(best_score, 4)}")
    lines.append(
        f"计算日期: {weight_result.get('meta', {}).get('created_at', 'N/A')[:10]}"
    )  # v2.6: 问题3修复 - 明确为计算日期

    # v2.7→v2.17: 评分说明重构——展示所有方法的完整评分明细，而非只对比IC vs ICIR
    #   旧逻辑：最优方法为Rolling ICIR时，评分说明只对比IC和ICIR的换手率 → 逻辑跳跃
    #   新逻辑：展示所有方法的各维度归一化得分表，让读者一目了然
    ranking = weight_result.get("ranking", [])
    metric_configs = weight_result.get("metric_configs", {})

    if ranking and metric_configs:
        lines.append("")
        lines.append("【评分明细】")
        lines.append("各方法各维度归一化得分（Min-Max归一化，逆向指标已反转）")
        # v2.24: 说明 Min-Max 归一化的放大效应
        lines.append("  注: Min-Max归一化将原始值映射到[0,1]，方法间微小差异可能被放大为较大得分差距")
        lines.append("       请结合括号内原始值判断实际差异，归一化得分仅反映相对排名")

        # 构建维度展示名称映射
        metric_display_names = {
            "long_short_return_annual": "多空年化收益",
            "long_short_sharpe": "多空夏普比率",
            "long_return_annual": "多头年化收益",
            "long_sharpe": "多头夏普比率",
            "monotonicity_abs": "单调性",
            "long_short_net_daily": "成本后日收益",
            "turnover_long_avg": "多头换手率(逆向)",
            "turnover_short_avg": "空头换手率(逆向)",
            "max_drawdown": "最大回撤(逆向)",
        }

        # 确定展示维度（按 metric_configs 的顺序）
        display_metrics = list(metric_configs.keys())
        # v2.17: 对每个维度添加方向说明
        metric_with_direction = []
        for m in display_metrics:
            direction = metric_configs[m].get("direction", "higher_better")
            display_name = metric_display_names.get(m, m)
            if direction == "lower_better":
                metric_with_direction.append(f"{display_name}↓")
            else:
                metric_with_direction.append(f"{display_name}")

        # 每个方法生成一行评分明细
        for item in sorted(ranking, key=lambda x: x.get("composite_score", 0), reverse=True):
            method_display = get_weight_method_display(item.get("method", "N/A"))
            composite_score = item.get("composite_score", 0)
            metric_scores = item.get("metric_scores", {})
            is_best = item.get("method") == best_method

            # 格式化各维度得分
            score_parts = []
            for m in display_metrics:
                score = metric_scores.get(m, 0)
                score_parts.append(f"{score:.2f}")

            best_marker = " ★最优" if is_best else ""
            lines.append(f"  {method_display:<20} 综合={composite_score:.4f}{best_marker}")
            # v2.17: 展示各维度得分明细
            for i, m in enumerate(display_metrics):
                score = metric_scores.get(m, 0)
                raw = item.get("raw_values", {}).get(m, None)
                direction = metric_configs[m].get("direction", "higher_better")
                display_name = metric_display_names.get(m, m)
                # v2.24: 成本后日收益值极小(~0.003)，4位小数不足以区分方法间差异，提升到6位
                raw_decimals = 6 if m == "long_short_net_daily" else 4
                raw_str = f"(原始值={raw:.{raw_decimals}f})" if raw is not None else ""
                best_star = " ★" if is_best and score >= 0.9 else ""
                lines.append(f"    - {display_name}: {score:.3f} {raw_str}{best_star}")

        # v2.17: 最优方法突出说明
        best_rank = next((r for r in ranking if r.get("method") == best_method), None)
        if best_rank and best_method == "rolling_icir_weight":
            best_ms = best_rank.get("metric_scores", {})
            best_rv = best_rank.get("raw_values", {})
            # Rolling ICIR 换手率得分较低时给出说明
            turnover_long = best_ms.get("turnover_long_avg", 0)
            turnover_short = best_ms.get("turnover_short_avg", 0)
            if turnover_long < 0.5 or turnover_short < 0.5:
                lines.append("")
                lines.append("  ★ Rolling ICIR加权换手率得分较低但综合得分最高：")
                # v2.24: 动态列举得分≥0.9的维度，避免硬编码错误（单调性0.6≠接近1.0）
                high_score_dims = []
                for m_key, m_score in best_ms.items():
                    if m_key in ("turnover_long_avg", "turnover_short_avg"):
                        continue  # 换手率已单独说明
                    if m_score >= 0.9:
                        high_score_dims.append(metric_display_names.get(m_key, m_key))
                high_score_str = "/".join(high_score_dims) if high_score_dims else "多数维度"
                lines.append(
                    f"    {high_score_str}得分接近1.0，换手率得分({turnover_long:.2f}/{turnover_short:.2f})虽低"
                )
                lines.append("    但9维度等权加权后综合得分仍最高，换手率惩罚不足以抵消其他维度优势")
                lines.append(
                    f"    原始多头换手率={best_rv.get('turnover_long_avg', 0):.4f}, 空头换手率={best_rv.get('turnover_short_avg', 0):.4f}"
                )

    lines.append("")

    # 各方法排名表格
    if all_methods:
        lines.append("【各权重方法排名】")
        lines.append(f"{'排名':>4} {'权重方法':<20} {'综合得分':>10}")
        lines.append("-" * 70)

        for i, item in enumerate(all_methods, 1):
            method_display = get_weight_method_display(item.get("method", "N/A"))
            score = item.get("composite_score", 0)
            lines.append(f"{i:>4} {method_display:<20} {format_float(score, 4):>10}")

        lines.append("-" * 70)

    # 评分指标说明
    scoring_metrics = weight_result.get("scoring_metrics", [])
    if scoring_metrics:
        lines.append("")
        lines.append("【评分指标】")
        lines.append(f"共 {len(scoring_metrics)} 个指标，Min-Max归一化后等权加权")
        lines.append("指标列表: " + ", ".join(scoring_metrics))

    lines.append("-" * 70)

    return lines


def _generate_lr_training_status() -> list[str]:
    """v3.10: 读取 lr_training_data 状态, 展示训练数据积累进度.

    展示内容:
    - 训练数据天数 / 目标 90 天
    - forward_return_1d 已补写比例
    - 各 weight_method 的天数分布
    - 如果 ≥90 天, 尝试运行 calibrate_lr_filter 并展示 OOS AUC
    """

    logger = setup_logger()
    lines: list[str] = []
    from paths import COMPREHENSIVE_FACTOR_RESULT

    lr_root = COMPREHENSIVE_FACTOR_RESULT / "lr_training_data"
    if not lr_root.exists():
        lines.append("【LR 训练数据状态】")
        lines.append("  训练数据: 尚未积累 (lr_training_data 目录不存在)")
        lines.append("  过滤状态: 未启用 (需积累 90 天)")
        return lines

    # 逐个 weight_method 目录读取 (避免 ds.dataset schema merge 冲突)
    wm_stats: dict[str, dict] = {}  # {wm: {n_days, n_rows, n_with_ret}}
    for wm_dir in sorted(lr_root.iterdir()):
        if not wm_dir.is_dir() or not wm_dir.name.startswith("weight_method="):
            continue
        wm = wm_dir.name.replace("weight_method=", "")
        n_days = 0
        n_rows = 0
        n_with_ret = 0
        for date_dir in sorted(wm_dir.iterdir()):
            if not date_dir.is_dir() or not date_dir.name.startswith("selection_date="):
                continue
            parquet_path = date_dir / "part-0.parquet"
            if not parquet_path.exists():
                continue
            try:
                df = pd.read_parquet(parquet_path, columns=["forward_return_1d"])
                n_days += 1
                n_rows += len(df)
                n_with_ret += int(df["forward_return_1d"].notna().sum())
            except Exception:
                continue
        wm_stats[wm] = {"n_days": n_days, "n_rows": n_rows, "n_with_ret": n_with_ret}

    if not wm_stats:
        lines.append("【LR 训练数据状态】")
        lines.append("  训练数据: 空")
        return lines

    lines.append("【LR 训练数据状态 (v3.10)】")

    # 按 weight_method 统计
    max_days = 0
    for wm, stats in sorted(wm_stats.items()):
        n_days = stats["n_days"]
        n_rows = stats["n_rows"]
        n_with_ret = stats["n_with_ret"]
        pct_ret = n_with_ret / n_rows * 100 if n_rows > 0 else 0
        max_days = max(max_days, n_days)

        status = "✓ 可训练" if n_days >= 90 else f"积累中 ({n_days}/90 天)"
        lines.append(f"  {wm}: {n_days} 天, {n_rows} 行, T+1 已补写 {pct_ret:.0f}% [{status}]")

    # 总体状态
    if max_days >= 90:
        lines.append("  过滤状态: ✓ 可启用 (set enable_overheat_filter=True)")
        # 尝试训练并展示 OOS AUC
        try:
            from stock_selector import StockSelectorConfig, calibrate_lr_filter

            config = StockSelectorConfig()
            for wm in sorted(wm_stats.keys()):
                model, scaler, features, auc = calibrate_lr_filter(
                    lr_root,
                    weight_method=wm,
                    top_n=config.top_n,
                    n_features=config.lr_top_features,
                    train_window=config.lr_train_window,
                    min_oos_auc=config.lr_min_oos_auc,
                    min_training_days=config.lr_min_training_days,
                    filter_quantile=config.lr_filter_quantile,
                    logger=logger,
                )
                if model is not None:
                    lines.append(f"  {wm} OOS AUC: {auc:.3f} ✓ (≥{config.lr_min_oos_auc}, {len(features)} 特征)")
                else:
                    lines.append(f"  {wm} OOS AUC: {auc:.3f} ✗ (< {config.lr_min_oos_auc}, 跳过过滤)")
        except Exception as e:
            lines.append(f"  (LR 训练验证失败: {e})")
    else:
        remaining = 90 - max_days
        lines.append(f"  过滤状态: 未启用 (还需 {remaining} 天)")

    return lines


def _generate_stock_selection_section(
    stock_result: dict | None,
    comp_weights: dict[str, float] | None = None,
    data_freshness: list[dict] | None = None,
    stock_name_map: dict[str, str] | None = None,
) -> list[str]:
    """生成股票选股结果展示部分

    v2.2 (2026-06-03): 新增股票选股结果展示
    v2.24 (2026-06-20): 新增 data_freshness 参数，动态标注选股数据日期
    v2.26 (2026-06-23): 新增 stock_name_map 参数，在股票代码后展示股票名称

    Args:
        stock_result: 股票选股结果字典（可为 None）
        comp_weights: 综合因子权重字典
        data_freshness: 数据完整性检查结果（来自 check_data_freshness）
        stock_name_map: {code: name} 映射（来自 load_stock_name_map）；
                        None 或缺失键时回退为"--"，不展示名称

    Returns:
        报告文本行列表
    """
    lines = []
    lines.append("")
    lines.append("八、股票选股结果")
    lines.append("-" * 70)

    if stock_result is None:
        lines.append("股票选股结果文件不存在，请先运行 stock_selector.py")
        lines.append("-" * 70)
        return lines

    meta = stock_result.get("meta", {})
    top_stocks = stock_result.get("top_stocks", [])

    # 元信息展示
    # v2.24: 动态标注数据日期——对比 expected_date(T-1) 与 actual_date 判断数据延迟
    selection_date = meta.get("selection_date", "N/A")
    data_date_note = "（使用T-1数据）"  # 默认标注
    if data_freshness:
        main_source = next((s for s in data_freshness if "factor_ic_data" in s.get("source", "")), None)
        if main_source:
            expected_date = main_source.get("expected_date", "")
            actual_date = main_source.get("actual_date", "")
            if expected_date and actual_date and actual_date != expected_date:
                data_date_note = f"（数据滞后，截至{actual_date}，T-1应为{expected_date}）"
            elif actual_date and actual_date == expected_date:
                data_date_note = "（使用T-1数据）"
    lines.append(f"选股日期: {selection_date}{data_date_note}")
    lines.append(f"最优权重方法: {get_weight_method_display(meta.get('weight_method', 'N/A'))}")
    lines.append(f"权重综合得分: {format_float(meta.get('composite_score', 0), 4)}")
    lines.append(
        f"因子方向: {meta.get('factor_direction', 'N/A')}（{'反向' if meta.get('factor_direction') == 'negative' else '正向'}）"
    )
    lines.append(f"选出股票数: {meta.get('top_n', 0)} 只（共 {meta.get('stocks_on_date', 0)} 只股票）")

    # v2.18: 振幅过滤信息展示
    min_amplitude = meta.get("min_amplitude", 0)
    excluded_by_amplitude = meta.get("excluded_by_amplitude", 0)
    if min_amplitude > 0:
        lines.append(
            f"振幅过滤: 排除 {excluded_by_amplitude} 只股票（振幅 < {min_amplitude * 100:.2f}%，不可交易的一字板涨停股）"
        )

    # v2.22: 覆盖率过滤信息展示
    excluded_by_coverage = meta.get("excluded_by_coverage", 0)
    min_weight_coverage = meta.get("min_weight_coverage", 0)
    if min_weight_coverage > 0:
        lines.append(
            f"覆盖率过滤: 排除 {excluded_by_coverage} 只股票（覆盖率 < {min_weight_coverage * 100:.0f}%，缺失高权重因子导致综合因子值不可信）"
        )

    # v2.12 / v2.47: 方向处理说明——展示取反因子（v2.47 含义反转：现在是 IC<0 因子被翻到正向）
    flipped_factors = meta.get("flipped_factors", [])
    if flipped_factors:
        lines.append("")
        lines.append("【方向处理说明】")
        lines.append(f"  反向因子标准化值已取反，对齐到正向语义：{flipped_factors}")
        for f in flipped_factors:
            lines.append(
                f"  - {f}: IC均值<0(反向因子)，综合因子计算时标准化值取反（做多因子值小的股票做空因子值大的股票）"
            )
        lines.append("  说明：v2.47 选股方向=positive（正向），因子值越大 → 综合因子越大 → 被选为Top股票")

    lines.append("")

    # === v3.10: Bottom90 选股轨迹展示 ===
    # v3.10: LR 过滤需积累 90 天训练数据, 当前冷启动阶段不过滤.
    # 展示: Stage 1 (composite 降序 Top 30, 候选池记录) + Bottom90 原始 + 最终短名单.
    stage1_top = stock_result.get("stage1_top", []) or []
    stage1_bottom = stock_result.get("stage1_bottom", []) or []

    # v3.10: LR 训练数据状态展示 (测试环境跳过, 避免触发真实 LR 训练)
    import sys as _sys

    if "pytest" not in _sys.modules:
        lr_status_lines = _generate_lr_training_status()
        if lr_status_lines:
            lines.extend(lr_status_lines)
            lines.append("")

    if stage1_top or stage1_bottom:
        lines.append("【选股轨迹 (v3.13: Bottom90 LR 打分排序, 不截断)】")
        lines.append(f"  Stage 1: 综合因子值降序取 Top {meta.get('stage1_pool_size', 200)} 作为候选池 (基础设施)")
        lines.append(
            f"  Bottom90: 综合因子值升序取最低 {meta.get('top_n', 0) * 3} → LR 模型打分 → 全部按 proba_up 降序输出 (不截断)"
        )
        lines.append("  说明: 最终短名单按 LR proba_up 降序 (预测 T+1 涨概率高=排前), 全部 90 只输出供人工决断.")
        lines.append("")

        # Stage 1 简表: composite 降序 Top 30 (弱势股端, 仅供记录)
        if stage1_top:
            lines.append(f"【Stage 1: 综合因子值 Top {len(stage1_top)} (composite 降序, 弱势股端)】")
            lines.append(f"{'排名':>4} {'股票代码':<10} {'股票名称':<8} {'综合因子值':>12}")
            lines.append("-" * 50)
            for item in stage1_top:
                rank = item.get("rank", 0)
                code = item.get("code", "N/A")
                name = (stock_name_map or {}).get(code, "--")
                cv = item.get("composite_value", 0)
                lines.append(f"{rank:>4} {code:<10} {name:<8} {format_float(cv, 3):>12}")
            lines.append("-" * 50)
            lines.append("")

        # Bottom90 原始简表 (composite 升序, LR 打分前)
        if stage1_bottom:
            lines.append(f"【Bottom {len(stage1_bottom)}: 综合因子值最低 (composite 升序, 弱势股端, LR 打分前)】")
            lines.append(f"{'排名':>4} {'股票代码':<10} {'股票名称':<8} {'综合因子值':>12}")
            lines.append("-" * 50)
            for item in stage1_bottom:
                rank = item.get("rank", 0)
                code = item.get("code", "N/A")
                name = (stock_name_map or {}).get(code, "--")
                cv = item.get("composite_value", 0)
                lines.append(f"{rank:>4} {code:<10} {name:<8} {format_float(cv, 3):>12}")
            lines.append("-" * 50)
            lines.append("")

        lines.append(f"【最终短名单 Top {len(top_stocks)} (Bottom90 LR 打分排序, 不截断)】")
        lines.append("")

    # Top N 股票表格 (v3.9: 即 Bottom30 过热过滤后短名单)
    # v2.42 (designs/feat_shortlist_top30_v1.md §2.2): 拆分 Top 10 详表 + 11~N 简表
    #   - Top 1~10: 详表, 展示全部因子 z-score (保留 v2.14 信息密度)
    #   - Top 11~N: 简表, 展示主导前 3 因子贡献占比 (避免 30 行 × 15 因子冗长)
    if top_stocks:
        DETAIL_LIMIT = 10  # v2.42: Top 10 详表边界
        detail_stocks = top_stocks[:DETAIL_LIMIT]
        brief_stocks = top_stocks[DETAIL_LIMIT:]

        # === Top 1~10 详表 ===
        detail_title = (
            f"【Top {len(detail_stocks)} 详表（重点观察）】" if brief_stocks else f"【Top {len(detail_stocks)} 股票】"
        )
        lines.append(detail_title)
        # v2.12: 增加覆盖率列
        # v2.14: 因子值详情改为显示标准化值(z-score)，而非原始值
        # v2.15 / v2.47: 反向因子取反后z-score加*标记，消除解读歧义
        header_note = "  * = 已取反对齐到正向语义" if flipped_factors else ""
        lines.append(
            f"{'排名':>4} {'股票代码':<10} {'股票名称':<8} {'综合因子值':>12} {'LR打分':>6} {'覆盖率':>6} {'因子标准化值(z-score)':<40}{header_note}"
        )
        lines.append("-" * 70)

        for item in detail_stocks:
            rank = item.get("rank", 0)
            code = item.get("code", "N/A")
            # v2.26: 股票名称从 stock_name_map 查找，缺失时回退"--"（不阻塞主报告）
            name = (stock_name_map or {}).get(code, "--")
            composite_value = item.get("composite_value", 0)
            weight_coverage = item.get("weight_coverage", 1.0)  # v2.12: 因子覆盖率

            # 因子值详情（全部显示）
            # v2.13: 区分"缺失(NaN)"和"真实≈0"——tail_price_volume_intensity等因子原始值为0是真实数据而非缺失
            # v2.14: 显示标准化值（z-score）而非原始值——原始值极端误导（如 momentum_strength=-9.08→z=-2.65）
            #   综合因子排名由标准化值驱动，原始值仅作参考
            factor_values = item.get("factor_values", {})
            factor_values_std = item.get("factor_values_std", {})  # v1.3b: 标准化值
            factor_str = ""
            if factor_values_std:
                # 优先显示标准化值（z-score），更准确反映排名驱动因素
                parts = []
                # v2.15: flipped_factors 集合用于标记取反因子
                flipped_set = set(flipped_factors) if flipped_factors else set()
                for k, v_std in factor_values_std.items():
                    factor_name = COL_TO_FACTOR_NAME_MAP.get(k, k)
                    # v2.15: 取反因子名后加*标记，消除解读歧义（z-score已取反≠原始z-score）
                    display_name = f"{factor_name}*" if factor_name in flipped_set else factor_name
                    if v_std is None:
                        # v2.21: z-score 缺失统一显示"缺失(NaN)"，不再区分原始值是否≈0
                        parts.append(f"{display_name}=缺失(NaN)")
                    elif abs(v_std) < 0.001:
                        # v2.21: z-score≈0 统一显示"0.00"，不再区分原始值是否≈0
                        parts.append(f"{display_name}=0.00")
                    else:
                        # 正常标准化值（z-score），保留2位小数
                        # Winsorize ±3σ 截断后范围 [-3.00, 3.00]
                        # v2.15: 取反因子用 display_name 带*标记
                        parts.append(f"{display_name}={format_float(v_std, 2)}")
                factor_str = ", ".join(parts)  # 显示全部因子标准化值
            elif factor_values:
                # 回退：无标准化值时显示原始值（兼容旧版 JSON）
                parts = []
                for k, v in factor_values.items():
                    factor_name = COL_TO_FACTOR_NAME_MAP.get(k, k)
                    if v is None:
                        parts.append(f"{factor_name}=缺失(NaN)")
                    elif abs(v) < 0.001:
                        # v2.21: 统一显示"0.00"，不再使用"≈0(真实)"标签
                        parts.append(f"{factor_name}=0.00")
                    else:
                        parts.append(f"{factor_name}={format_float(v, 2)}")
                factor_str = ", ".join(parts)
            else:
                factor_str = "无因子值"

            coverage_str = f"{weight_coverage * 100:.0f}%" if weight_coverage < 1 else "100%"
            lr_proba = item.get("lr_proba_up")
            lr_str = f"{lr_proba:.2f}" if lr_proba is not None else "  n/a"
            lines.append(
                f"{rank:>4} {code:<10} {name:<8} {format_float(composite_value, 3):>12} {lr_str:>6} {coverage_str:>6} {factor_str}"
            )

        lines.append("-" * 70)

        # === Top 11~N 简表 (v2.42: designs/feat_shortlist_top30_v1.md §2.2) ===
        # 主导前 3 因子: 按 |w × z| 贡献占比排序, 展示备选池信号来源
        if brief_stocks:
            lines.append("")
            lines.append(f"【短名单 11~{len(top_stocks)} 简表（备选池）】")
            lines.append(
                f"{'排名':>4} {'股票代码':<10} {'股票名称':<8} {'综合因子值':>12} {'LR打分':>6} {'覆盖率':>6} {'主导前 3 因子（贡献占比）':<40}"
            )
            lines.append("-" * 70)
            flipped_set = set(flipped_factors) if flipped_factors else set()
            for item in brief_stocks:
                rank = item.get("rank", 0)
                code = item.get("code", "N/A")
                # v2.26: 短名单简表展示股票名称
                name = (stock_name_map or {}).get(code, "--")
                composite_value = item.get("composite_value", 0)
                weight_coverage = item.get("weight_coverage", 1.0)
                factor_values_std = item.get("factor_values_std", {}) or {}

                # 计算主导前 3 因子: 按 |w × z| 占总贡献的比例
                dominant_str = "(无主导因子)"
                if comp_weights and factor_values_std:
                    contributions = {}
                    for col, w in comp_weights.items():
                        # comp_weights 用列名做 key, factor_values_std 也是列名 (v1.4)
                        z = factor_values_std.get(col)
                        if z is None or w is None:
                            continue
                        contributions[col] = abs(float(w) * float(z))
                    total = sum(contributions.values())
                    if total > 0:
                        ratios = sorted(
                            ((c, v / total) for c, v in contributions.items()),
                            key=lambda kv: -kv[1],
                        )[:3]
                        parts = []
                        for col, ratio in ratios:
                            factor_name = COL_TO_FACTOR_NAME_MAP.get(col, col)
                            display = f"{factor_name}*" if factor_name in flipped_set else factor_name
                            parts.append(f"{display}({ratio * 100:.0f}%)")
                        dominant_str = ", ".join(parts)

                coverage_str = f"{weight_coverage * 100:.0f}%" if weight_coverage < 1 else "100%"
                lr_proba = item.get("lr_proba_up")
                lr_str = f"{lr_proba:.2f}" if lr_proba is not None else "  n/a"
                lines.append(
                    f"{rank:>4} {code:<10} {name:<8} {format_float(composite_value, 3):>12} {lr_str:>6} {coverage_str:>6} {dominant_str}"
                )
            lines.append("-" * 70)
            lines.append(
                f"说明: Top 1~10 为 composite 极值区（高信号 + 高波动）, Top 11~{len(top_stocks)} 为短名单备选池。"
            )
            lines.append("最终持仓 3~5 只由人工决断（参考 PROJECT.md 战略目标：量化辅助 + 人工决断）。")

            # v2.43: 决策卡片块 (designs/feat_decision_card_v1.md)
            # 5 维客观字段叠加在短名单上, 辅助人工决断 3~5 只持仓
            has_card = any(s.get("decision_card") for s in top_stocks)
            if has_card:
                lines.append("")
                lines.append("【决策卡片 (人工决断辅助, 5 维客观字段)】")
                lines.append(
                    "  排名 股票代码  股票名称   D1 涨幅档/振幅档/区间位置          | D2 过热 | D3 趋势 | D4 历史"
                )
                lines.append("-" * 120)
                for s in top_stocks:
                    card = s.get("decision_card")
                    if not card:
                        continue
                    d1 = card.get("d1_classification", {})
                    d2 = card.get("d2_risk", {})
                    d3 = card.get("d3_trend", {})
                    d4 = card.get("d4_history", {})

                    d1_str = (
                        f"{d1.get('return_5d_bucket', 'n/a')} / "
                        f"{d1.get('amplitude_bucket', 'n/a')} / "
                        f"{d1.get('close_position_5d', 'n/a')}"
                    )
                    # D2 过热风险 (0~3), 命中详情标注
                    d2_flags = []
                    if d2.get("high_turnover"):
                        d2_flags.append("高换手")
                    if d2.get("high_volume_ratio"):
                        d2_flags.append("放量")
                    if d2.get("extreme_amplitude"):
                        d2_flags.append("极端振幅")
                    d2_str = f"{d2.get('warning_count', 0)}/3"
                    if d2_flags:
                        d2_str += f"({','.join(d2_flags)})"

                    # D3 趋势确认 (0~3), raw_signals_available=False 显示 n/a
                    d3_str = "n/a" if not d3.get("raw_signals_available", False) else f"{d3.get('hit_count', 0)}/3"

                    # D4 历史 — 本期 null
                    times = d4.get("times_in_top30_last_60d")
                    d4_str = "n/a" if times is None else f"{times}次"

                    lines.append(
                        f"  {s['rank']:>3} {s['code']:<8} {(stock_name_map or {}).get(s['code'], '--'):<8} {d1_str:<34}  | {d2_str:<14} | {d3_str:<6} | {d4_str}"
                    )
                lines.append("-" * 120)
                lines.append("说明:")
                lines.append("  D1 客观分类: 纯阈值分桶（涨幅/振幅/收盘价在近 5 日区间位置）, 不带叙事词。")
                lines.append("  D2 过热风险: 高换手(截面70%+) / 放量(volume_ratio_5>1.5) / 极端振幅(<1% 或 >12%)。")
                lines.append("  D3 趋势确认: 近高比例(>0.95) + 布林上轨(>1.0) + RSI超买(>70), 0~3 个命中。")
                lines.append("  D4 历史画像: 本期为 n/a (需历史归档机制, 独立 design 待启动)。")
                lines.append("")
                lines.append("【D5 人工核查清单 (固定模板, 适用每只候选股票)】")
                for i, item in enumerate(CHECKLIST_D5, 1):
                    lines.append(f"  {i}. {item}")

        # v2.19: 因子贡献集中度检测
        if comp_weights:
            concentration_anomalies = _compute_factor_concentration(top_stocks, comp_weights)
            if concentration_anomalies:
                lines.append("")
                lines.append("⚠ 因子贡献集中度警告:")
                for a in concentration_anomalies:
                    lines.append(
                        f"  - {a['factor_name']}: 名义权重={a['weight']:.1%}，"
                        f"实际贡献占比={a['concentration_ratio']:.1%}"
                        f"（{a['relative_ratio']:.1f}x名义权重）"
                    )
                lines.append(
                    "    说明: 该因子的实际贡献远超名义权重，"
                    "可能原因: 因子原始值集中在边界(如0.0)导致z-score极端化，"
                    "有效分散化不足"
                )

        # v2.24: 相同 z-score 检测——多只股票同一因子 z-score 完全相同
        # 原因：原始值相同（如尾盘因子=0.0=收盘最低价）→ z-score 相同（数学正确）
        # 或 Winsorize ±3σ 截断（z=-3.00 或 z=3.00 多次出现）
        dup_notes = _detect_duplicate_zscores(top_stocks)
        if dup_notes:
            lines.append("")
            lines.append("ℹ 相同z-score说明:")
            for note in dup_notes:
                lines.append(f"  - {note}")

    # 权重配置信息
    weight_config = stock_result.get("weight_config", {})
    if weight_config:
        lines.append("")
        lines.append("【权重配置】")
        lines.append(f"权重方法: {get_weight_method_display(weight_config.get('method', 'N/A'))}")
        if weight_config.get("method") == "rolling_icir_weight":
            lines.append(f"滚动窗口: {weight_config.get('window', 'N/A')} 日")
        factor_list = weight_config.get("factor_list", [])
        if factor_list:
            lines.append(f"因子列表: {', '.join(factor_list)}")

    lines.append("-" * 70)

    return lines


def _generate_comparison_section(
    factor_data: list[dict], composite_results: list[dict], best_weight_method: str = "icir_weight"
) -> list[str]:
    """生成综合因子与单因子对比部分

    展示四种权重方法的回测指标和选中单因子的回测指标，只做收集展示不做选择。

    Args:
        factor_data: 合并后的因子数据列表
        composite_results: 综合因子回测结果列表

    Returns:
        报告文本行列表
    """
    lines = []
    lines.append("")
    lines.append("六、综合因子与单因子对比")
    lines.append("-" * 70)

    # 边界保护：空列表时跳过对比
    if not composite_results:
        lines.append("综合因子数据不足，无法生成对比表")
        lines.append("-" * 70)
        return lines

    # ========================================
    # 第一部分：综合因子四种权重方法回测数据
    # ========================================
    lines.append("")
    lines.append("【综合因子四种权重方法回测数据】")
    lines.append("-" * 70)
    lines.append(f"{'权重方法':<20} {'多空年化收益':>12} {'夏普比率':>8} {'单调性系数':>10} {'单调性质量':>10}")
    lines.append("-" * 70)

    for item in composite_results:
        lines.append(
            f"{item['weight_method_display']:<20} "
            f"{format_percentage(item['long_short_return_annual']):>12} "
            f"{format_float(item['long_short_sharpe'], 2):>8} "
            f"{format_float(item['monotonicity_correlation']):>10} "
            f"{item['monotonicity_symbol']:>10}"
        )

    lines.append("-" * 70)

    # ========================================
    # 第二部分：选中单因子回测数据
    # ========================================
    lines.append("")
    lines.append("【选中单因子回测数据】")
    lines.append("-" * 70)

    # v2.16: 从最优方法获取选中因子列表和权重
    # 优先使用 selection_result.selected（反映实际筛选结果），回退到 factor_list
    selected_factors = []
    comp_weights = {}  # v2.16: 当前最优方法的权重字典

    best_item = next((item for item in composite_results if item.get("weight_method") == best_weight_method), None)

    if best_item:
        sel_res = best_item.get("selection_result")
        if sel_res and sel_res.get("selected"):
            selected_factors = sel_res["selected"]
        else:
            selected_factors = best_item.get("factor_list", [])

        # v2.16: Rolling ICIR 使用 last_day_weights，其他方法使用 meta.weights
        if best_weight_method == "rolling_icir_weight":
            weight_meta = best_item.get("weight_meta", {})
            last_day_weights = weight_meta.get("last_day_weights", {})
            comp_weights = last_day_weights if last_day_weights else best_item.get("weights", {})
        else:
            comp_weights = best_item.get("weights", {})
    else:
        # 回退：取 icir_weight
        for item in composite_results:
            if item["weight_method"] == "icir_weight":
                sel_res = item.get("selection_result")
                if sel_res and sel_res.get("selected"):
                    selected_factors = sel_res["selected"]
                else:
                    selected_factors = item.get("factor_list", [])
                comp_weights = item.get("weights", {})
                break

    if not selected_factors:
        lines.append("未找到选中因子列表")
        lines.append("-" * 70)
        return lines

    if not factor_data:
        lines.append("单因子数据不足，无法展示选中因子")
        lines.append("-" * 70)
        return lines

    # 表头
    lines.append(
        f"{'因子名':<18} {'多空年化收益':>12} {'夏普比率':>8} {'单调性系数':>10} {'单调性质量':>10} {'权重':>8}"
    )
    # v2.16: 权重来源说明——根据最优方法动态生成
    if best_weight_method == "rolling_icir_weight":
        lines.append("注：权重来自Rolling ICIR加权最新日（动态权重，每日变化）")
    else:
        lines.append(f"注：权重来自{get_weight_method_display(best_weight_method)}")
    lines.append("-" * 70)

    # 展示选中的单因子
    for factor_name in selected_factors:
        factor_item = next((f for f in factor_data if f["factor_name"] == factor_name), None)
        if factor_item:
            # v2.16: 从最优方法的权重获取（而非硬编码 icir_weight）
            factor_col = FACTOR_NAME_TO_COL_MAP.get(factor_name, factor_name)
            # v2.21: last_day_weights 键可能是因子名而非列名，先查列名再回退因子名
            weight = comp_weights.get(
                factor_col, comp_weights.get(factor_name, 0)
            )  # v2.16: comp_weights 已根据最优方法确定

            lines.append(
                f"{factor_name:<18} "
                f"{format_percentage(factor_item.get('long_short_return_annual', 0)):>12} "
                f"{format_float(factor_item.get('long_short_sharpe', 0), 2):>8} "
                f"{format_float(factor_item.get('monotonicity_correlation', 0)):>10} "
                f"{factor_item.get('monotonicity_symbol', ''):>10} "
                f"{weight * 100:>6.1f}%"  # 权重百分比，右对齐宽度6
            )
        else:
            lines.append(f"{factor_name:<18} 数据缺失")

    lines.append("-" * 70)

    # v2.18: Rolling ICIR 权重排名 vs 全样本 ICIR 排名异常检测
    if best_weight_method == "rolling_icir_weight" and selected_factors and comp_weights:
        anomalies = _detect_weight_rank_anomalies(selected_factors, factor_data, comp_weights)
        if anomalies:
            lines.append("")
            lines.append("⚠ Rolling ICIR 权重异常因子说明:")
            n_total = len(selected_factors)
            for a in anomalies:
                lines.append(
                    f"  - {a['factor_name']}: 全样本ICIR={a['icir']:.4f}"
                    f"(排名{a['icir_rank']}/{n_total}) → 权重={a['weight']:.1%}"
                    f"(排名{a['weight_rank']}/{n_total})"
                )
                lines.append(f"    权重排名显著低于ICIR排名(下降{a['rank_drop']}位)，表明该因子近60日IC表现急剧恶化")
            lines.append("    说明: Rolling ICIR使用60日滚动窗口动态加权，全样本ICIR高但近期失效的因子会被自动降权")

    # v2.11→v2.13: 综合因子收益低于单因子时的完整分析说明
    # 检查选中因子是否存在短样本因子（有效天数差异导致年化收益不可比）
    short_sample_selected = [
        f for f in factor_data if f["factor_name"] in selected_factors and f.get("valid_days", 999) < 30
    ]

    # v2.13: 综合收益低于所有入选单因子时（不仅是短样本），增加方向抵消分析
    composite_best_return = (
        max(c.get("long_short_return_annual", 0) for c in composite_results) if composite_results else 0
    )
    selected_long_returns = [
        f.get("long_short_return_annual", 0)
        for f in factor_data
        if f["factor_name"] in selected_factors and f.get("valid_days", 999) >= 30
    ]
    min_long_return = min(selected_long_returns) if selected_long_returns else 0

    if short_sample_selected or (composite_best_return < min_long_return and min_long_return > 0):
        lines.append("")
        lines.append("⚠ 综合因子收益低于短样本单因子分析:")

        # v2.21: 动态编号，避免条件不满足时编号跳过
        note_idx = 1

        if short_sample_selected:
            short_names = [f["factor_name"] for f in short_sample_selected]
            short_days = [str(f.get("valid_days", "N/A")) for f in short_sample_selected]
            long_names = [
                f["factor_name"]
                for f in factor_data
                if f["factor_name"] in selected_factors and f.get("valid_days", 999) >= 30
            ]
            long_days = [
                str(f.get("valid_days", "N/A"))
                for f in factor_data
                if f["factor_name"] in selected_factors and f.get("valid_days", 999) >= 30
            ]
            lines.append(
                f"  {note_idx}. 数据覆盖差异: 短样本因子({','.join(short_names)})仅{','.join(short_days)}天，年化收益极端放大"
            )
            lines.append(f"     长样本因子({','.join(long_names)})有{','.join(long_days)}天数据，收益更可靠")
            lines.append("     综合因子覆盖全周期，短样本因子仅少数日期有数据，其余日期由其他因子主导")
            note_idx += 1

        if composite_best_return < min_long_return and min_long_return > 0:
            lines.append(
                f"  {note_idx}. 方向抵消效应: 综合因子最优年化={composite_best_return:.1f}%，低于长样本单因子最低={min_long_return:.1f}%"
            )
            # v2.24: 不硬编码 overnight_ret，用实际 flipped_factors
            flipped_in_selected = []
            if composite_results:
                flipped_in_selected = [
                    f for f in (composite_results[0].get("flipped_factors", [])) if f in selected_factors
                ]
            if flipped_in_selected:
                lines.append(
                    f"     原因分析：反向因子({','.join(flipped_in_selected)})取反后与正向因子方向统一，但因子间相关性导致"
                )
            else:
                lines.append("     原因分析：因子间相关性导致部分信号重叠抵消")
            lines.append("     部分信号重叠抵消。综合因子年化低于最优单因子是正常的——组合分散降低了极端收益")
            lines.append("     同时也降低了极端风险（夏普比率可能更优）")
            note_idx += 1

        # v2.13→v2.24: overnight_ret方向处理说明——仅在overnight_ret入选时输出
        flipped_factors = []
        if composite_results:
            flipped_factors = composite_results[0].get("flipped_factors", [])
        # v2.24: 只在 overnight_ret 实际入选时才讨论其方向处理
        if flipped_factors and "overnight_ret" in selected_factors:
            lines.append(f"  {note_idx}. overnight_ret方向处理: 已取反标准化值({flipped_factors})，无二次反向风险")
            lines.append("     取反逻辑：IC均值>0 → 标准化值取反 → 与负向因子方向统一 → 做空因子值大的股票")
            note_idx += 1
        # overnight_ret 未入选时不输出方向处理说明（讨论不存在的场景无意义）

    return lines
