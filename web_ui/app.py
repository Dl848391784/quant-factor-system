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

from flask import Flask, abort, redirect, render_template  # noqa: E402

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

# v0.4.8 R2a: web_ui 内部实现的辅助模块 (H1.1 严守: 不修改 data_loaders)
from web_ui.common.lr_training_status import load_status as load_lr_status  # noqa: E402

# v0.4.8 R12: 接受 date 参数的 stock_selection_result (H1.1 严守: 不修改 data_loaders)
from web_ui.common.stock_selection import load_stock_selection_for_date  # noqa: E402

# v0.4.8 R4: 解析 ob_quality txt 报告 (H1.1 严守: txt 是 summary 已生成产物)
from web_ui.common.txt_parser import (  # noqa: E402
    parse_obq_correlation as parse_obq_corr,
    parse_obq_filter as parse_obq_filt,
    parse_obq_intraday_fallback as parse_obq_intraday,
    parse_obq_section_8_meta as parse_obq_s8,
    parse_obq_section_9_matrix as parse_obq_s9,
)


logger = logging.getLogger("web_ui")

app = Flask(__name__)


@app.route("/")
def index():
    """首页: 302 → /report/latest"""
    return redirect("/report/latest")


@app.route("/report/<date>")
def show_report(date: str):
    """v0.4.8: 展示 ob_quality 报告页 (固定 pipeline, 不再 ?pipeline= 切换)

    Args:
        date: YYYY-MM-DD 报告日期
    """
    # 简化的日期格式校验
    if len(date) != 10 or date[4] != "-" or date[7] != "-":
        abort(400, description=f"日期格式必须为 YYYY-MM-DD，收到: {date}")

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
        result.get("meta", {}).get("weight_method", "rolling_icir_weight")
        if result else "rolling_icir_weight"
    )
    if selection_date:
        try:
            intraday_rows = load_intraday_strategy(
                "ob_quality", weight_method, selection_date, logger=logger
            ) or []
        except Exception as e:
            logger.warning("load_intraday_strategy 失败: %s", e)
            intraday_rows = []
        try:
            decile_stats = load_decile_stats(weight_method, selection_date, logger=logger)
        except Exception as e:
            logger.warning("load_decile_stats 失败: %s", e)
            decile_stats = None

    # v0.4.8 R4: 解析 ob_quality txt 报告补全字段 (H1.1 严守: 不改 data_loaders)
    txt_s8_meta: dict = {}
    txt_s9_matrix: dict | None = None
    intraday_fallback: dict = {}
    try:
        txt_s8_meta = parse_obq_s8(logger=logger) or {}
    except Exception as e:
        logger.warning("parse_obq_s8 失败: %s", e)
    try:
        txt_s9_matrix = parse_obq_s9(logger=logger)
    except Exception as e:
        logger.warning("parse_obq_s9 失败: %s", e)
    # v0.4.8 R6: 解析操作规则 + 历史胜率
    try:
        intraday_fallback = parse_obq_intraday(logger=logger) or {}
    except Exception as e:
        logger.warning("parse_obq_intraday 失败: %s", e)
        intraday_fallback = {}
    # v0.4.8 R9: 因子相关性 (三) + 筛选 (四)
    txt_correlation: dict | None = None
    txt_filter: dict | None = None
    try:
        txt_correlation = parse_obq_corr(logger=logger)
    except Exception as e:
        logger.warning("parse_obq_corr 失败: %s", e)
    try:
        txt_filter = parse_obq_filt(logger=logger)
    except Exception as e:
        logger.warning("parse_obq_filt 失败: %s", e)

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
        "T-1 (见 summary 实际输出)"
        if result is None
        else result.get("meta", {}).get("selection_date", "未知")
    )

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
        txt_s9_matrix=txt_s9_matrix,
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
    )


@app.route("/report/latest")
def show_report_latest():
    """v0.4.8: 重定向到最新可用报告日期"""
    result = load_stock_selection_result(logger=logger)
    if result is None or not result.get("meta", {}).get("selection_date"):
        logger.error("无法定位最新报告日期")
        abort(404)
    return redirect(f"/report/{result['meta']['selection_date']}")


if __name__ == "__main__":
    # v1 启动方式: python web_ui/app.py
    logger.setLevel(logging.INFO)
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s"))
    logger.addHandler(handler)
    logger.info("web_ui 启动: PIPELINE_ALIAS=%s (v0.4.8 固定 ob_quality)", os.environ.get("PIPELINE_ALIAS"))
    app.run(host="0.0.0.0", port=9001, debug=False)
