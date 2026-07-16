"""web_ui Flask 入口（v0.4.8 简化版）

定位: web_ui 是 summary 的前端分支——复用 summary/report/data_loaders.py 读取 ob_quality 管线数据。
Jinja2 模板渲染 HTML，与 summary 的 txt 输出共用数据契约。

v0.4.8 简化（伴随 v0.4.7 严格回退 + PROJECT.md H1.1 边界铁律）:
- web_ui 只展示 ob_quality 管线（去掉 default/ob_quality tab 切换）
- 启动时自动设 PIPELINE_ALIAS=ob_quality（避免运行时 reload）
- 数据契约: 复用 summary/report/data_loaders.py 已有接口 (只读, 不扩)
- LR 训练状态: web_ui 内部实现 (web_ui/common/lr_training_status.py)
- 字段补完: web_ui 读 ob_quality txt 报告 (web_ui/common/txt_parser.py, R4 实施)

详见:
- web_ui/MODULE.md (v0.4.7, 边界强约束)
- designs/feat_web_ui_obq_parity_v0.4.8.md (R1-R4 规划)
- PROJECT.md §硬规则 H1 / H1.1
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path


# v0.4.8 简化: web_ui 只展示 ob_quality, 启动时强制设 PIPELINE_ALIAS
# 必须在 import paths 之前执行 (paths.py line 43 PIPELINE_ALIAS = os.environ.get(...))
os.environ.setdefault("PIPELINE_ALIAS", "ob_quality")

# PROJECT_ROOT 加入 sys.path（让 from summary.report.data_loaders 可用）
PROJECT_ROOT = Path(__file__).parent.parent.resolve()
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from flask import Flask, abort, redirect, render_template, request  # noqa: E402

# 复用 summary 数据加载器（web_ui 不直接读 Parquet）
# v0.4.8: H1.1 严守, 只调 data_loaders 已有接口, 不修改 data_loaders
# 注: load_stock_selection_result 不支持 date 参数 (R12 已知 issue)
#   v0.4.8 R12 用 web_ui.common.stock_selection.load_stock_selection_for_date
#   但此 view 同时保留旧调用作为 fallback (txt_parser 仍需 latest_date 数据)
from summary.report.data_loaders import (  # noqa: E402
    load_backtest_results,
    load_composite_results,
    load_decile_stats,
    load_ic_results,
    load_intraday_strategy,
    load_stock_name_map,
    load_stock_selection_result,
    load_weight_selection_result,
)

# v0.4.8 R7: 数据完整性检查 (H1.1 严守: 从 freshness_check.py 调, 不改 data_loaders)
from summary.report.freshness_check import (  # noqa: E402
    check_data_freshness,
    check_derived_data_freshness,
)

# v0.4.8 R44 (Stage 6 新组件): 30 段每日复合资产值 trend (geom compound over pl_ratio_trend)
from web_ui.common.asset_value_db import load_asset_value_trend  # noqa: E402, F401
from web_ui.common.day1_filter import load_day1_filter  # noqa: E402

# v0.4.8 R2a: web_ui 内部实现的辅助模块 (H1.1 严守: 不修改 data_loaders)
from web_ui.common.lr_training_status import load_status as load_lr_status  # noqa: E402

# v0.4.8 R39a (Stage 6 算法重设计): 30 段每日合并收益率 (seg_return = mean(forward_return_1d))
# R39 原算法 wins.mean/|losses.mean| (盈亏比) 用户反馈方向错, 改为简单算术平均收益率
# H1.1 严守 + §18 fork pattern: web_ui 内部读 parquet, 不修改 data_loaders / summary 模块
from web_ui.common.pl_ratio_db import load_pl_ratio_trend  # 函数名保留 (R39a 内部已重写算法)  # noqa: E402
from web_ui.common.segment_ai_db import load_segment_ai_decisions  # noqa: E402, F401  # v0.4.8 R49

# v0.4.8 R38 (Stage 6): 30 段合并胜率趋势概览 (从 segment_win_rates.parquet 算 cumsum)
# H1.1 严守 + §18 fork pattern: web_ui 内部读 parquet, 不修改 summary 模块
from web_ui.common.segment_win_db import load_merged_win_trend  # noqa: E402

# v0.4.8 R12: 接受 date 参数的 stock_selection_result (H1.1 严守: 不修改 data_loaders)
from web_ui.common.stock_selection import load_stock_selection_for_date  # noqa: E402
from web_ui.common.streak_tracker import load_streak_tracker  # noqa: E402

# v0.4.8 R4: 解析 ob_quality txt 报告 (H1.1 严守: txt 是 summary 已生成产物)
from web_ui.common.txt_parser import (  # noqa: E402
    parse_obq_correlation as parse_obq_corr,
    parse_obq_filter as parse_obq_filt,
    parse_obq_intraday_fallback as parse_obq_intraday,
    parse_obq_section_8_meta as parse_obq_s8,
    parse_obq_section_9_matrix as parse_obq_s9,
    parse_obq_section_10_segments as parse_obq_s10,
)

# v0.4.9: 从 parquet 直接读取四种 weight_method 的胜率+候选明细 (替代 txt_parser 单一 wm 限制)
from web_ui.common.weight_method_data import (  # noqa: E402
    ALL_WEIGHT_METHODS,
    WEIGHT_METHOD_DISPLAY,
    get_best_weight_method,
    load_candidates as load_parq_candidates,
    load_win_matrix as load_parq_win_matrix,
)


logger = logging.getLogger("web_ui")

app = Flask(__name__)


@app.route("/")
def index():
    """首页: 302 → /report/latest"""
    return redirect("/report/latest")


def _render_report(date: str):
    """v0.4.8 R46: 渲染 ob_quality 报告页 (内部 helper, 抽离 /report/<date> 与 /report/latest 共用)

    v0.4.9: 接受 ?wm=xxx query param 切换 weight_method (Section 9/10 页签)

    Args:
        date: YYYY-MM-DD 报告日期 (调用方已保证格式合法)
    """
    # 简化的日期格式校验 (内部 helper 防御性 double-check)
    if len(date) != 10 or date[4] != "-" or date[7] != "-":
        abort(400, description=f"日期格式必须为 YYYY-MM-DD，收到: {date}")

    # v0.4.9: weight_method 页签 (?wm=xxx)
    best_wm = get_best_weight_method(logger=logger)
    requested_wm = request.args.get("wm", "").strip()
    current_wm = requested_wm if requested_wm and requested_wm in ALL_WEIGHT_METHODS else best_wm

    # v0.4.8 R12: 优先用 date-aware load_stock_selection_for_date(date)
    # 失败 / 不存在 时 fallback 到 data_loaders.load_stock_selection_result (取 max)
    try:
        result = load_stock_selection_for_date(date, logger=logger)
    except Exception as e:
        logger.warning("load_stock_selection_for_date(%s) 失败: %s, fallback to data_loaders", date, e)
        result = None
    if result is None:
        result = load_stock_selection_result(logger=logger)
    stock_name_map = load_stock_name_map(logger=logger) or {}

    # v0.4.8 R2a: LR 训练数据状态 (web_ui 内部实现, H1.1 严守)
    try:
        lr_status = load_lr_status(logger=logger) or []
    except Exception as e:
        logger.warning("load_lr_status 失败: %s", e)
        lr_status = []

    # v0.4.8 R3: ob_quality 专属 — 30 分段胜率 + 日内操作建议
    # 注意: load_intraday_strategy pipeline 参数固定 'ob_quality', 已在 data_loaders 内部校验
    intraday_rows: list[dict] = []
    decile_stats: dict | None = None
    selection_date = result.get("meta", {}).get("selection_date") if result else None
    weight_method = (
        result.get("meta", {}).get("weight_method", "rolling_icir_weight") if result else "rolling_icir_weight"
    )
    if selection_date:
        try:
            intraday_rows = load_intraday_strategy("ob_quality", weight_method, selection_date, logger=logger) or []
        except Exception as e:
            logger.warning("load_intraday_strategy 失败: %s", e)
            intraday_rows = []
        try:
            decile_stats = load_decile_stats(weight_method, selection_date, logger=logger)
        except Exception as e:
            logger.warning("load_decile_stats 失败: %s", e)
            decile_stats = None

    # v0.4.8 R4: 解析 ob_quality txt 报告补全字段 (H1.1 严守: 不改 data_loaders)
    # 修复: 传入 date 参数让 txt_parser 优先读取该日期的报告 (原: 始终读最新)
    txt_s8_meta: dict = {}
    txt_s9_matrix: dict | None = None
    txt_s10_segments: dict | None = None
    intraday_fallback: dict = {}
    try:
        txt_s8_meta = parse_obq_s8(logger=logger, date=date) or {}
    except Exception as e:
        logger.warning("parse_obq_s8 失败: %s", e)
    try:
        txt_s9_matrix = parse_obq_s9(logger=logger, date=date)
    except Exception as e:
        logger.warning("parse_obq_s9 失败: %s", e)
    # v0.4.8 R16: 第十节 30 分段候选明细 (txt 来源, S1~S30)
    try:
        txt_s10_segments = parse_obq_s10(logger=logger, date=date)
    except Exception as e:
        logger.warning("parse_obq_s10 失败: %s", e)
        txt_s10_segments = None
    # v0.4.8 R6: 解析操作规则 + 历史胜率
    try:
        intraday_fallback = parse_obq_intraday(logger=logger, date=date) or {}
    except Exception as e:
        logger.warning("parse_obq_intraday 失败: %s", e)
        intraday_fallback = {}
    # v0.4.8 R9: 因子相关性 (三) + 筛选 (四)
    txt_correlation: dict | None = None
    txt_filter: dict | None = None
    try:
        txt_correlation = parse_obq_corr(logger=logger, date=date)
    except Exception as e:
        logger.warning("parse_obq_corr 失败: %s", e)
    try:
        txt_filter = parse_obq_filt(logger=logger, date=date)
    except Exception as e:
        logger.warning("parse_obq_filt 失败: %s", e)

    # v0.4.8 R38 (Stage 6): 30 段合并胜率趋势 (从 segment_win_rates.parquet 算 cumsum)
    # v0.4.9: 用 current_wm 替代硬编码 rolling_icir_weight
    merged_win_trend: dict | None = None
    try:
        merged_win_trend = load_merged_win_trend(weight_method=current_wm, logger=logger)
    except Exception as e:
        logger.warning("load_merged_win_trend 失败: %s", e)

    # v0.4.8 R39a (Stage 6 算法重设计): 30 段每日合并收益率 (字段名沿用 pl_ratio_trend 兼容 R39 mock)
    # v0.4.9: 用 current_wm 替代硬编码 rolling_icir_weight
    pl_ratio_trend: dict | None = None
    try:
        pl_ratio_trend = load_pl_ratio_trend(weight_method=current_wm, logger=logger)
    except Exception as e:
        logger.warning("load_pl_ratio_trend 失败: %s", e)

    # v0.4.8 R44 (Stage 6 新组件): 30 段每日复合资产值 trend (geom compound over pl_ratio_trend)
    asset_value_trend: dict | None = None
    try:
        asset_value_trend = load_asset_value_trend(logger=logger)
    except Exception as e:
        logger.warning("load_asset_value_trend 失败: %s", e)

    # v0.4.8 R49 (用户原话 2026-07-08 "web_ui 资产值图组件下方展示"):
    # 30 段 AI 客观分析师角色 LLM 决策 + 反思. 失败 fallback to None (R38 模式)
    segment_ai_decisions: dict | None = None
    try:
        segment_ai_decisions = load_segment_ai_decisions(
            pipeline="ob_quality",
            weight_method="rolling_icir_weight",
            logger=logger,
        )
    except Exception as e:
        logger.warning("load_segment_ai_decisions 失败: %s", e)

    # v0.4.8 R7: 数据完整性检查 (零·)
    data_results: list[dict] = []
    derived_results: list[dict] = []
    # v0.4.8 R7: 单因子 IC (一·)
    ic_results: list[dict] = []
    # v0.4.8 R8: 二/五/七 section
    backtest_results: list[dict] = []
    composite_results: list[dict] = []
    weight_selection: dict | None = None
    try:
        data_results = check_data_freshness(selection_date or date, logger=logger) or []
    except Exception as e:
        logger.warning("check_data_freshness 失败: %s", e)
    try:
        derived_results = check_derived_data_freshness(selection_date or date, logger=logger) or []
    except Exception as e:
        logger.warning("check_derived_data_freshness 失败: %s", e)
    try:
        ic_results = load_ic_results(logger=logger) or []
    except Exception as e:
        logger.warning("load_ic_results 失败: %s", e)
        ic_results = []
    try:
        backtest_results = load_backtest_results(logger=logger) or []
    except Exception as e:
        logger.warning("load_backtest_results 失败: %s", e)
        backtest_results = []
    try:
        composite_results = load_composite_results(logger=logger) or []
    except Exception as e:
        logger.warning("load_composite_results 失败: %s", e)
        composite_results = []
    try:
        weight_selection = load_weight_selection_result(logger=logger)
    except Exception as e:
        logger.warning("load_weight_selection_result 失败: %s", e)
        weight_selection = None

    # v0.4.8 R1: meta 派生字段 (H1.1 不改 data_loaders, 用 result.get 兼容)
    # 注意: result 是 dict, 必须用 item 访问 result["meta"] 而非 result.meta
    expected_data_date = (
        "T-1 (见 summary 实际输出)" if result is None else result.get("meta", {}).get("selection_date", "未知")
    )

    # v0.4.9: 从 parquet 直接读取四种 weight_method 的胜率矩阵 + 候选明细
    # 替代 txt_parser (txt 只有"最优" weight_method 的数据, 切 wm 时历史断层)
    parq_s9_matrix: dict | None = None
    parq_s10_segments: dict | None = None
    try:
        parq_s9_matrix = load_parq_win_matrix(current_wm, logger=logger)
    except Exception as e:
        logger.warning("load_parq_win_matrix(%s) 失败: %s", current_wm, e)
    try:
        parq_s10_segments = load_parq_candidates(current_wm, stock_name_map=stock_name_map, logger=logger)
    except Exception as e:
        logger.warning("load_parq_candidates(%s) 失败: %s", current_wm, e)

    # v0.4.9 R50: 连续入选追踪 (连选 2~4 天 + 分段跳跃型)
    streak_data: dict | None = None
    try:
        streak_data = load_streak_tracker(current_wm, stock_name_map=stock_name_map, logger=logger)
    except Exception as e:
        logger.warning("load_streak_tracker(%s) 失败: %s", current_wm, e)

    # v0.4.9 R51: Day 1 三层过滤 (breadth>=80 + past_ret<0 + turnover>=10%)
    day1_data: dict | None = None
    try:
        day1_data = load_day1_filter(current_wm, stock_name_map=stock_name_map, logger=logger)
    except Exception as e:
        logger.warning("load_day1_filter(%s) 失败: %s", current_wm, e)

    # v0.4.9: 页签数据 (所有 weight_method 的显示名 + 是否有数据)
    wm_tabs = [
        {
            "key": wm,
            "label": WEIGHT_METHOD_DISPLAY.get(wm, wm),
            "is_best": wm == best_wm,
            "is_current": wm == current_wm,
        }
        for wm in ALL_WEIGHT_METHODS
    ]

    return render_template(
        "report.html",
        report_date=date,
        expected_data_date=expected_data_date,
        result=result,
        stock_name_map=stock_name_map,
        lr_status=lr_status,
        decile_stats=decile_stats,
        intraday_rows=intraday_rows,
        txt_s8_meta=txt_s8_meta,
        txt_s9_matrix=parq_s9_matrix if parq_s9_matrix else txt_s9_matrix,
        txt_s10_segments=parq_s10_segments if parq_s10_segments else txt_s10_segments,
        merged_win_trend=merged_win_trend,
        pl_ratio_trend=pl_ratio_trend,
        asset_value_trend=asset_value_trend,  # v0.4.8 R44
        segment_ai_decisions=segment_ai_decisions,  # v0.4.8 R49 (Round 1 "web_ui 资产值图组件下方展示")
        intraday_fallback=intraday_fallback,
        data_results=data_results,
        derived_results=derived_results,
        ic_results=ic_results,
        backtest_results=backtest_results,
        composite_results=composite_results,
        weight_selection=weight_selection,
        correlation=txt_correlation,
        filter_result=txt_filter,
        # v0.4.8 R10: 选中单因子从 txt_filter.selected_factors 拿 (六·对比 模板用)
        selected_factors=(txt_filter or {}).get("selected_factors", []),
        # v0.4.9: weight_method 页签
        wm_tabs=wm_tabs,
        current_wm=current_wm,
        current_wm_label=WEIGHT_METHOD_DISPLAY.get(current_wm, current_wm),
        # v0.4.9 R50: 连续入选追踪
        streak_data=streak_data,
        # v0.4.9 R51: Day 1 三层过滤
        day1_data=day1_data,
    )


@app.route("/report/<date>")
def show_report(date: str):
    """v0.4.8 R46: 展示 ob_quality 报告页 (固定 pipeline, 不再 ?pipeline= 切换)

    Args:
        date: YYYY-MM-DD 报告日期
    """
    return _render_report(date)


@app.route("/report/latest")
def show_report_latest():
    """v0.4.8 R46: 直接 200 渲染最新可用报告 (用户原话: /report/latest 就是最近报告就好)

    历史行为: 302 重定向到 /report/<date>, 浏览器每次跟随 302 -> URL 变化 -> 书签/分享的
    "latest" URL 实际上指向特定日期, 重启服务器或换天后需要重新发链接。
    新行为: 直接 200 渲染, URL 始终是 /report/latest 不变, 永远拿当前最新日期报告。

    修复: 原代码用 stock_selection_result.meta.selection_date (选股日, T-1) 作为
    "最新报告日期", 但 txt 报告在 T+1 生成 (文件名日期 = 报告生成日), 导致选股日
    比 txt 最新文件名日期早一天, txt_parser 读到的是前一天的报告. 改为直接取
    最新 txt 报告文件的日期作为 date 参数.
    """
    # 优先: 从最新 txt 报告文件名取日期 (报告生成日, 与 txt 内容一致)
    from web_ui.common.txt_parser import _find_latest_txt

    latest_txt = _find_latest_txt()
    if latest_txt is not None:
        # 文件名格式: factor_summary_report_YYYY-MM-DD.txt
        date = latest_txt.stem.replace("factor_summary_report_", "")
        return _render_report(date)

    # fallback: txt 不存在时用 stock_selection_result.selection_date (旧行为)
    result = load_stock_selection_result(logger=logger)
    if result is None or not result.get("meta", {}).get("selection_date"):
        logger.error("无法定位最新报告日期")
        abort(404)
    latest_date = result["meta"]["selection_date"]
    return _render_report(latest_date)


@app.after_request
def _add_cache_control(response):
    """R33 (perf, Stage 2.3): /report/<date> 缓存 5 分钟让浏览器走 304 重访命中"""
    if request.path.startswith("/report/"):
        response.headers["Cache-Control"] = "private, max-age=300"
    return response


if __name__ == "__main__":
    # v1 启动方式: python web_ui/app.py
    logger.setLevel(logging.INFO)
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s"))
    logger.addHandler(handler)
    logger.info("web_ui 启动: PIPELINE_ALIAS=%s (v0.4.8 固定 ob_quality)", os.environ.get("PIPELINE_ALIAS"))
    app.run(host="0.0.0.0", port=9001, debug=False)
