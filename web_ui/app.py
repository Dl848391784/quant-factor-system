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
from summary.report.data_loaders import (  # noqa: E402
    load_decile_stats,
    load_intraday_strategy,
    load_stock_name_map,
    load_stock_selection_result,
)

# v0.4.8 R2a: web_ui 内部实现的辅助模块 (H1.1 严守: 不修改 data_loaders)
from web_ui.common.lr_training_status import load_status as load_lr_status  # noqa: E402

# v0.4.8 R4: 解析 ob_quality txt 报告 (H1.1 严守: txt 是 summary 已生成产物)
from web_ui.common.txt_parser import (  # noqa: E402
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
    try:
        txt_s8_meta = parse_obq_s8(logger=logger) or {}
    except Exception as e:
        logger.warning("parse_obq_s8 失败: %s", e)
    try:
        txt_s9_matrix = parse_obq_s9(logger=logger)
    except Exception as e:
        logger.warning("parse_obq_s9 失败: %s", e)

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
