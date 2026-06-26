"""因子分析逻辑。

从 generate_factor_summary_report.py 迁移（v3.8 拆分重构）。
包含相关性分析、因子筛选、中性化敏感度、因子集中度等分析函数。
"""

import logging

import pandas as pd
from factor_definitions import (
    FACTOR_CATEGORIES,
    FACTOR_NAME_TO_COL_MAP,
)
from summary.report.constants import (
    COL_TO_FACTOR_NAME_MAP,
    CORR_MAX,
    CORR_THRESHOLD_HIGH,
    CORR_THRESHOLD_MEDIUM,
    ICIR_THRESHOLD,
    RETURN_THRESHOLD,
    _get_factor_abbr,
)
from summary.report.formatters import (
    format_float,
    get_weight_method_display,
)


def _extract_corr_pairs(
    corr_matrix: pd.DataFrame, factor_names: list[str], min_threshold: float, max_threshold: float
) -> list[tuple[str, str, float]]:
    """提取指定阈值范围内的因子相关性对

    Args:
        corr_matrix: 相关性矩阵
        factor_names: 因子名列表
        min_threshold: 最小阈值（|corr| > min_threshold）
        max_threshold: 最大阈值（|corr| <= max_threshold）

    Returns:
        因子对列表 [(factor1, factor2, corr_value), ...]
    """
    pairs = []
    for i, row_name in enumerate(factor_names):
        for j, col_name in enumerate(factor_names):
            if i < j:
                val = abs(corr_matrix.loc[row_name, col_name])
                if min_threshold < val <= max_threshold:
                    pairs.append((row_name, col_name, val))
    return pairs


def generate_correlation_section(
    corr_matrix: pd.DataFrame | None, ic_results: list[dict], selection_result: dict | None = None
) -> list[str]:
    """生成因子相关性部分

    v1.8 (2026-05-28): 新增 selection_result 参数（预留），添加选中因子说明

    Args:
        corr_matrix: 因子相关性矩阵（仅选中因子，可为 None）
        ic_results: IC 结果列表（用于排序因子名）
        selection_result: 筛选详细结果（预留，暂不使用）

    Returns:
        报告文本行列表
    """
    lines = []

    if corr_matrix is None:
        lines.append("")
        lines.append("三、因子相关性矩阵")
        lines.append("-" * 70)
        lines.append("因子相关性数据不可用（需要因子数据文件）")
        lines.append("-" * 70)
        return lines

    # 获取因子名（按 ICIR 排序）
    factor_names = [r["factor_name"] for r in ic_results if r["factor_name"] in corr_matrix.index]

    lines.append("")
    lines.append("三、因子相关性矩阵")
    lines.append("-" * 70)

    # 说明：此矩阵仅显示选中因子
    if factor_names:
        lines.append(f"（选中因子相关性矩阵，共 {len(factor_names)} 个因子）")

    # 表头
    header = f"{'因子':<12}"
    for name in factor_names:
        # v2.22: 用因子缩写替代 name[:8]，避免 tail_pri ×3 无法区分
        abbr = _get_factor_abbr(name)
        header += f"{abbr:>10}"
    lines.append(header)
    lines.append("-" * 70)

    # 矩阵内容
    for row_name in factor_names:
        row = f"{row_name:<12}"
        for col_name in factor_names:
            val = corr_matrix.loc[row_name, col_name]
            row += f"{format_float(val, 2):>10}"
        lines.append(row)

    lines.append("-" * 70)

    # v2.24: 缩写对照表——行名用全名、列名用缩写，需输出对照表供读者查阅
    if factor_names:
        abbr_pairs = [(name, _get_factor_abbr(name)) for name in factor_names]
        # 只在有缩写差异时才输出（避免全名=缩写时多余）
        diff_pairs = [(n, a) for n, a in abbr_pairs if n != a]
        if diff_pairs:
            lines.append("【缩写对照表】")
            for name, abbr in diff_pairs:
                lines.append(f"  {abbr:<10} = {name}")

    # v2.6: 问题8修复 - 展示剔除的高相关因子对
    if selection_result:
        high_corr_dropped = selection_result.get("high_corr_dropped", {})
        if high_corr_dropped:
            lines.append("")
            lines.append("【剔除的高相关因子对】")
            lines.append("以下因子因与选中因子高相关而被剔除：")
            for factor_name, reason in high_corr_dropped.items():
                # 解析剔除原因，提取相关系数
                lines.append(f"  - {factor_name}: {reason}")
            lines.append("-" * 70)

    # 选中因子之间的高相关因子对
    # v2.23 (2026-06-20): 维度感知展示——跨维度高相关标注"保留"，同维度才标"建议检查"
    high_corr_pairs = _extract_corr_pairs(corr_matrix, factor_names, CORR_THRESHOLD_HIGH, CORR_MAX)

    if high_corr_pairs:
        # 按维度分类: 跨维度保留 vs 同维度（应已被筛选去重）
        cross_dim_pairs: list[tuple[str, str, float]] = []
        same_dim_pairs: list[tuple[str, str, float]] = []
        for pair in high_corr_pairs:
            cat_i = FACTOR_CATEGORIES.get(pair[0])
            cat_j = FACTOR_CATEGORIES.get(pair[1])
            if cat_i and cat_j and cat_i != cat_j:
                cross_dim_pairs.append(pair)
            else:
                same_dim_pairs.append(pair)

        if cross_dim_pairs:
            lines.append(f"选中因子中跨维度高相关因子对（|corr| > {CORR_THRESHOLD_HIGH:.1f}，维度不同→保留，不去重）：")
            for pair in cross_dim_pairs:
                cat_i = FACTOR_CATEGORIES.get(pair[0], "?")
                cat_j = FACTOR_CATEGORIES.get(pair[1], "?")
                lines.append(f"  - {pair[0]}[{cat_i}] vs {pair[1]}[{cat_j}]: {format_float(pair[2], 2)}")

        if same_dim_pairs:
            lines.append(f"选中因子中同维度高相关因子对（|corr| > {CORR_THRESHOLD_HIGH:.1f}，建议检查筛选逻辑）：")
            for pair in same_dim_pairs:
                cat_i = FACTOR_CATEGORIES.get(pair[0], "?")
                lines.append(f"  - {pair[0]}[{cat_i}] vs {pair[1]}[{cat_i}]: {format_float(pair[2], 2)}")

        if not cross_dim_pairs and not same_dim_pairs:
            lines.append(f"选中因子中无高相关因子对（所有因子相关性 < {CORR_THRESHOLD_HIGH:.1f}）")
    else:
        lines.append(f"选中因子中无高相关因子对（所有因子相关性 < {CORR_THRESHOLD_HIGH:.1f}）")

    # 中等相关因子对
    med_corr_pairs = _extract_corr_pairs(corr_matrix, factor_names, CORR_THRESHOLD_MEDIUM, CORR_THRESHOLD_HIGH)

    if med_corr_pairs:
        lines.append("")
        lines.append(f"选中因子中中等相关因子对（{CORR_THRESHOLD_MEDIUM:.1f} < |corr| <= {CORR_THRESHOLD_HIGH:.1f}）：")
        for pair in med_corr_pairs:
            lines.append(f"  - {pair[0]} vs {pair[1]}: {format_float(pair[2], 2)}")

    lines.append("-" * 70)

    return lines


def _format_exempt_note(factor_name: str, exempted_factors_map: dict[str, list[dict]], is_selected: bool) -> str:
    """格式化豁免标注文本

    Args:
        factor_name: 因子名
        exempted_factors_map: {factor_name: [exempt_detail, ...]}
        is_selected: True=入选因子, False=被剔除因子

    Returns:
        豁免标注字符串（无豁免记录时返回空字符串）

    入选因子（豁免成功）:
        ",豁免:|ic_mean|=0.017<0.03,回测强劲(夏普=5.54>1.5,单调性=0.53>0.5)"
    被剔除因子（豁免失败）:
        "未满足豁免: 夏普=1.43<1.5"
    """
    details = exempted_factors_map.get(factor_name)
    if not details:
        return ""

    if is_selected:
        # 入选因子: 只展示豁免成功的记录
        success_details = [d for d in details if d["exempted"]]
        if not success_details:
            return ""
        parts = []
        for d in success_details:
            parts.append(f"|{d['trigger']}|={d['actual']:.3f}<{d['threshold']:.3f},{d['detail']}")
        return f",豁免:{';'.join(parts)}"
    else:
        # 被剔除因子: 展示豁免失败的记录
        fail_details = [d for d in details if not d["exempted"]]
        if not fail_details:
            return ""
        # v2.25: 去重——ic_mean 和 icir 两个条件可能触发相同的豁免失败说明
        parts = list(dict.fromkeys(d["detail"] for d in fail_details))
        return ";".join(parts)


def get_factor_selection_info(
    composite_results: list[dict],
    ic_results: list[dict],
    backtest_results: list[dict],
    logger: logging.Logger,
    best_weight_method: str = "icir_weight",
) -> str:
    """获取因子筛选信息

    v1.7 (2026-05-28): 优先读取 selection_result 中的真实筛选原因，
                       解决"原因未知"问题（需要 composite_runner.py v2.9 配合）

    Args:
        composite_results: 综合因子回测结果列表
        ic_results: IC 结果列表
        backtest_results: 回测结果列表
        logger: 日志记录器

    Returns:
        因子筛选信息文本
    """
    if not composite_results:
        return "未找到综合因子结果"

    lines = []
    lines.append("auto_select 模式结果:")

    # 直接使用传入的 composite_results 数据（已在 load_composite_results 加载）
    selected_factors = []
    weights = {}
    selection_result = None  # v1.7: 筛选详细结果
    weight_source_note = ""  # v2.16: 权重来源说明
    exempted_factors_map: dict[str, list[dict]] = {}  # v2.23: 豁免详情（从 selection_result 提取）

    # v2.16: 根据最优权重方法选择权重数据源
    #   之前硬编码取 icir_weight 的静态权重 → Rolling ICIR 为最优时展示静态权重 → 严重误导
    #   例：tail_price_position ICIR=0.80 → 静态权重18.4%，但 Rolling ICIR 最新日=8.3%（短样本NaN回退1/n）
    #   修复：优先取最优方法的权重，Rolling ICIR 取 last_day_weights，其他方法取 meta.weights
    best_method_item = next(
        (item for item in composite_results if item.get("weight_method") == best_weight_method), None
    )

    if best_method_item:
        # 从最优方法获取权重和因子列表
        selection_result_item = best_method_item.get("selection_result")
        if selection_result_item and selection_result_item.get("selected"):
            selected_factors = selection_result_item["selected"]
        else:
            selected_factors = best_method_item.get("factor_list", [])

        if best_weight_method == "rolling_icir_weight":
            # v2.16: Rolling ICIR 使用 last_day_weights（真实最后一日动态权重）
            weight_meta = best_method_item.get("weight_meta", {})
            last_day_weights = weight_meta.get("last_day_weights", {})
            if last_day_weights:
                weights = last_day_weights
                rolling_window = weight_meta.get("window", 60)
                weight_source_note = f"权重来自Rolling ICIR加权最新日({rolling_window}日滚动窗口)"
            else:
                weights = best_method_item.get("weights", {})
                weight_source_note = "权重来自Rolling ICIR加权(动态权重未保存,回退等权)"
        else:
            weights = best_method_item.get("weights", {})
            weight_source_note = f"权重来自{get_weight_method_display(best_weight_method)}"

        selection_result = selection_result_item
        # v2.23: 提取豁免详情
        if selection_result_item:
            exempted_factors_map = selection_result_item.get("exempted_factors", {})

        factor_info = []
        for f in selected_factors:
            factor_col = FACTOR_NAME_TO_COL_MAP.get(f, f)
            # v2.21: last_day_weights 键可能是因子名而非列名（如 volume_ratio vs volume_ratio_5），
            # 先查列名，再回退因子名，避免权重查找返回 0
            weight = weights.get(factor_col, weights.get(f, 0))
            ic_item = next((r for r in ic_results if r["factor_name"] == f), None)
            # v2.23: 追加豁免标注
            exempt_note = _format_exempt_note(f, exempted_factors_map, is_selected=True)
            if ic_item:
                factor_info.append(f"{f}(ICIR={ic_item['icir']:.2f},权重={weight * 100:.1f}%{exempt_note})")
            else:
                factor_info.append(f"{f}(权重={weight * 100:.1f}%{exempt_note})")

        lines.append(f"  - 选中因子: {', '.join(factor_info)}")
        lines.append(f"  - 注：{weight_source_note}")  # v2.16: 动态权重来源说明
    else:
        # 回退：最优方法无结果时仍取 icir_weight（兼容旧版）
        for item in composite_results:
            if item["weight_method"] == "icir_weight":
                selection_result_item = item.get("selection_result")
                if selection_result_item and selection_result_item.get("selected"):
                    selected_factors = selection_result_item["selected"]
                else:
                    selected_factors = item.get("factor_list", [])
                weights = item.get("weights", {})
                selection_result = selection_result_item
                # v2.23: 提取豁免详情
                if selection_result_item:
                    exempted_factors_map = selection_result_item.get("exempted_factors", {})

                factor_info = []
                for f in selected_factors:
                    factor_col = FACTOR_NAME_TO_COL_MAP.get(f, f)
                    weight = weights.get(factor_col, 0)
                    ic_item = next((r for r in ic_results if r["factor_name"] == f), None)
                    # v2.23: 追加豁免标注
                    exempt_note = _format_exempt_note(f, exempted_factors_map, is_selected=True)
                    if ic_item:
                        factor_info.append(f"{f}(ICIR={ic_item['icir']:.2f},权重={weight * 100:.1f}%{exempt_note})")
                    else:
                        factor_info.append(f"{f}(权重={weight * 100:.1f}%{exempt_note})")

                lines.append(f"  - 选中因子: {', '.join(factor_info)}")
                lines.append("  - 注：权重来自ICIR加权方法(最优方法结果缺失,回退)")
                break

    # v1.8: 显示筛选阈值
    if selection_result:
        thresholds = selection_result.get("thresholds", {})
        if thresholds:
            high_corr_threshold = thresholds.get("high_corr_threshold", 0.7)
            lines.append(f"  - 高相关阈值: {high_corr_threshold:.1f}")

    # v1.7: 优先使用 selection_result 中的真实原因
    all_factors = [r["factor_name"] for r in ic_results]
    excluded_factors = [f for f in all_factors if f not in selected_factors]

    # 构建剔除原因字典（从 selection_result 获取真实原因）
    exclude_reasons: dict[str, str] = {}

    if selection_result:
        # 从 invalid 字段获取无效因子原因
        invalid = selection_result.get("invalid", {})
        for factor_name, reasons in invalid.items():
            exclude_reasons[factor_name] = "; ".join(reasons) if isinstance(reasons, list) else str(reasons)

        # 从 high_corr_dropped 字段获取高相关剔除原因
        high_corr_dropped = selection_result.get("high_corr_dropped", {})
        for factor_name, reason in high_corr_dropped.items():
            exclude_reasons[factor_name] = str(reason)

        logger.debug("从 selection_result 读取真实筛选原因: %d 条", len(exclude_reasons))

    if excluded_factors:
        excluded_info = []

        # 对每个剔除因子查找原因
        for f in excluded_factors:
            if f in exclude_reasons:
                reason = exclude_reasons[f]
                logger.debug("因子 %s 剔除原因: %s", f, reason)
            else:
                ic_item = next((r for r in ic_results if r["factor_name"] == f), None)
                bt_item = next((r for r in backtest_results if r["factor_name"] == f), None)

                reason = ""
                if ic_item and ic_item["icir"] < ICIR_THRESHOLD:
                    reason = f"ICIR<{ICIR_THRESHOLD}"
                if bt_item and bt_item["long_short_return_annual"] < RETURN_THRESHOLD:
                    reason += (", " if reason else "") + f"多空收益<{RETURN_THRESHOLD}%"

                if not reason:
                    reason = "原因未知（selection_result 未记录）"
                    logger.warning("因子 %s 剔除原因未知，建议重新执行综合因子脚本", f)

            # v2.23: 追加豁免失败说明
            exempt_note = _format_exempt_note(f, exempted_factors_map, is_selected=False)
            if exempt_note:
                reason += f"; {exempt_note}"

            excluded_info.append(f"{f}({reason})")

        # v2.22: 剔除因子拆多行显示，避免单行超长截断
        lines.append("  - 剔除因子:")
        for info in excluded_info:
            lines.append(f"    · {info}")

    lines.append("-" * 70)
    lines.append(f"筛选后因子列表: {selected_factors}")

    return "\n".join(lines)


def _format_neutral_cell(ic_item: dict) -> str:
    """格式化"中性化敏感"列文本（design.md §6 / R18b）。

    显示规则：
    - enabled=False / decay_rate=None: '-' （未启用或被排除清单跳过）
    - decay_level='high' (≥30%): 'XX% ⚠' （alpha 主要来自行业 beta）
    - decay_level='low' / 'inverse' / 'undefined': 'XX%'

    Args:
        ic_item: load_ic_results 返回的单条记录, 含
            neutral_enabled / neutral_decay_rate / neutral_decay_level

    Returns:
        固定 ≤10 字符宽度的显示字符串（已含右侧高亮符号 ⚠ if any）
    """
    enabled = ic_item.get("neutral_enabled", False)
    decay_rate = ic_item.get("neutral_decay_rate")
    if not enabled or decay_rate is None:
        return "-"
    pct = f"{decay_rate * 100:.0f}%"
    level = ic_item.get("neutral_decay_level", "undefined")
    if level == "high":
        return f"{pct} ⚠"
    return pct


def _generate_neutralization_notes(ic_results: list[dict]) -> list[str]:
    """生成中性化敏感列的说明文本

    v2.24 (2026-06-20): 新增

    解释两类异常：
    1. 空值（-）：区分"未启用中性化"和"被排除清单跳过"
    2. 极端负值（|decay_rate| > 1.0，即>100%衰减）：中性化后IC方向反转

    Args:
        ic_results: IC 结果列表

    Returns:
        说明文本列表（为空则不输出说明段）
    """
    notes = []
    # 统计空值原因
    null_disabled = []  # 未启用
    null_excluded = []  # 被排除清单跳过
    extreme_negative = []  # 极端负值（方向反转）

    for item in ic_results:
        name = item.get("factor_name", "?")
        enabled = item.get("neutral_enabled", False)
        decay_rate = item.get("neutral_decay_rate")

        if not enabled or decay_rate is None:
            if not enabled:
                null_disabled.append(name)
            else:
                null_excluded.append(name)
        elif decay_rate < -1.0:
            # decay_rate < -1.0 表示中性化后IC方向反转且幅度超过原始IC
            extreme_negative.append((name, decay_rate))

    if null_disabled:
        notes.append(
            f"  '-': 中性化未启用或被排除清单跳过 — {', '.join(null_disabled[:5])}"
            + ("..." if len(null_disabled) > 5 else "")
        )

    if null_excluded:
        notes.append(
            f"  '-': 中性化已启用但 decay_rate 缺失（可能因有效天数不足无法计算） — {', '.join(null_excluded[:5])}"
            + ("..." if len(null_excluded) > 5 else "")
        )

    if extreme_negative:
        notes.append("  极端负值（<-100%）：中性化后IC方向反转，alpha可能来自行业beta而非个股alpha")
        for name, rate in extreme_negative:
            notes.append(f"    - {name}: {rate * 100:.0f}%")

    return notes


def _detect_duplicate_zscores(top_stocks: list[dict], min_duplicates: int = 3) -> list[str]:
    """检测 Top N 股票中同一因子 z-score 完全相同的情况

    v2.24 (2026-06-20): 新增

    相同 z-score 的原因：
    1. 原始值相同（如 tail_price_position=0.0=收盘最低价）→ z-score 相同（数学正确）
    2. Winsorize ±3σ 截断 → z=±3.00 多次出现

    Args:
        top_stocks: 选中的股票列表
        min_duplicates: 最少重复次数才报告（默认3次）

    Returns:
        说明文本列表，每项描述一个因子的重复情况
    """
    from collections import Counter

    # 收集每个因子的 z-score
    factor_zscores: dict[str, list[float]] = {}
    for stock in top_stocks:
        factor_values_std = stock.get("factor_values_std", {})
        for col, z_score in factor_values_std.items():
            if z_score is not None:
                factor_zscores.setdefault(col, []).append(round(z_score, 4))

    notes = []
    for col, scores in factor_zscores.items():
        score_counts = Counter(scores)
        for score, count in score_counts.items():
            if count >= min_duplicates:
                # 判断是否为截断值
                is_clipped = abs(score) >= 2.99
                reason = (
                    "Winsorize ±3σ 截断（多只股票极端值被截断为同一值）"
                    if is_clipped
                    else "原始值相同（如尾盘因子=0.0=收盘最低价，不同股票原始值一致→z-score一致）"
                )
                notes.append(f"{col}: z-score={score:.2f} 出现{count}次 — {reason}")

    return notes


def _compute_factor_concentration(
    top_stocks: list[dict],
    comp_weights: dict[str, float],
    *,
    concentration_threshold: float = 0.5,
    relative_ratio_threshold: float = 2.0,
) -> list[dict]:
    """检测 Top N 股票中因子贡献集中度过高的因子。

    双重检测条件（满足任一即报警）：
    1. 绝对集中度：因子平均绝对贡献占综合因子平均绝对值 > concentration_threshold（50%）
       → 表面多因子综合实际近乎单因子选股
    2. 相对集中度：实际贡献占比 / 名义权重 > relative_ratio_threshold（2.0x）
       → 因子实际影响力远超名义权重，z-score 极端化导致权重失真

    典型场景：tail_price_position 原始值=0.0（收盘=尾盘最低价）导致
    z-score≈-2.45，名义权重 19.8% 但实际贡献占比 41%（2.07x）。

    Args:
        top_stocks: 选中的股票列表，每项含 factor_values_std 和 composite_value
        comp_weights: {factor_col: weight} 权重字典
        concentration_threshold: 绝对贡献占比阈值，默认 0.5（50%）
        relative_ratio_threshold: 相对贡献倍数阈值，默认 2.0

    Returns:
        集中度异常因子列表（按集中度降序），每项含 factor_name /
        factor_col / weight / avg_abs_contribution / concentration_ratio /
        relative_ratio
    """
    if not top_stocks or not comp_weights:
        return []

    avg_abs_composite = sum(abs(s.get("composite_value", 0)) for s in top_stocks) / len(top_stocks)
    if avg_abs_composite < 1e-9:
        return []

    anomalies = []
    for factor_col, weight in comp_weights.items():
        abs_contributions = []
        for stock in top_stocks:
            std_val = stock.get("factor_values_std", {}).get(factor_col)
            if std_val is not None:
                abs_contributions.append(abs(weight * std_val))
        if not abs_contributions:
            continue
        avg_abs_contribution = sum(abs_contributions) / len(abs_contributions)
        concentration = avg_abs_contribution / avg_abs_composite
        relative_ratio = concentration / weight if weight > 1e-9 else float("inf")
        if concentration >= concentration_threshold or relative_ratio >= relative_ratio_threshold:
            anomalies.append(
                {
                    "factor_name": COL_TO_FACTOR_NAME_MAP.get(factor_col, factor_col),
                    "factor_col": factor_col,
                    "weight": weight,
                    "avg_abs_contribution": avg_abs_contribution,
                    "concentration_ratio": concentration,
                    "relative_ratio": relative_ratio,
                }
            )

    return sorted(anomalies, key=lambda x: x["concentration_ratio"], reverse=True)


def _detect_weight_rank_anomalies(
    selected_factors: list[str],
    factor_data: list[dict],
    comp_weights: dict[str, float],
    *,
    rank_drop_threshold: int | None = None,
) -> list[dict]:
    """检测 Rolling ICIR 权重排名与全样本 ICIR 排名显著不一致的因子。

    仅对 Rolling ICIR 加权有意义：全样本 ICIR 高但权重极低，
    说明该因子近 60 日 IC 表现急剧恶化（滚动 ICIR 动态降权）。
    rank_drop = weight_rank - icir_rank（正值表示权重排名低于 ICIR 排名）。

    Args:
        selected_factors: 选中因子名列表
        factor_data: 合并后的因子数据（含 icir 字段）
        comp_weights: {factor_col: weight} 权重字典
        rank_drop_threshold: 排名下降位数阈值，None 时按 max(2, N//3) 自适应

    Returns:
        异常因子列表，每项含 factor_name / icir / icir_rank /
        weight / weight_rank / rank_drop
    """
    n = len(selected_factors)
    if n < 3:
        return []

    if rank_drop_threshold is None:
        rank_drop_threshold = max(2, n // 4)

    # 收集每个因子的 ICIR 和权重
    factor_stats = []
    for factor_name in selected_factors:
        factor_item = next((f for f in factor_data if f["factor_name"] == factor_name), None)
        if not factor_item:
            continue
        icir = factor_item.get("icir", 0)
        factor_col = FACTOR_NAME_TO_COL_MAP.get(factor_name, factor_name)
        # v2.21: last_day_weights 键可能是因子名而非列名，先查列名再回退因子名
        weight = comp_weights.get(factor_col, comp_weights.get(factor_name, 0))
        factor_stats.append(
            {
                "factor_name": factor_name,
                "icir": icir,
                "weight": weight,
            }
        )

    if len(factor_stats) < 3:
        return []

    # 按 |ICIR| 降序排名（rank 1 = 最强 ICIR）
    by_icir = sorted(factor_stats, key=lambda x: abs(x["icir"]), reverse=True)
    for i, item in enumerate(by_icir):
        item["icir_rank"] = i + 1

    # 按权重降序排名（rank 1 = 最高权重）
    by_weight = sorted(factor_stats, key=lambda x: x["weight"], reverse=True)
    for i, item in enumerate(by_weight):
        item["weight_rank"] = i + 1

    # 检测排名下降（权重排名远低于 ICIR 排名）
    anomalies = []
    for item in factor_stats:
        rank_drop = item["weight_rank"] - item["icir_rank"]
        if rank_drop >= rank_drop_threshold:
            item["rank_drop"] = rank_drop
            anomalies.append(item)

    return anomalies
