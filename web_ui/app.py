"""web_ui Flask 入口（v0.3 v1 MVP）

定位: web_ui 是 summary 的前端分支——复用 summary/report/data_loaders.py 读取数据，
Jinja2 模板渲染 HTML，与 summary 的 txt 输出共用数据契约。

详见:
- web_ui/MODULE.md（本模块规范）
- designs/feat_web_ui_module.md（v0.3 design）
- PROJECT.md §"前端模块豁免条款"
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

from flask import Flask, abort, render_template

# 复用 summary 数据加载器（web_ui 不直接读 Parquet）
from summary.report.data_loaders import load_stock_selection_result


# PROJECT_ROOT 加入 sys.path（让 from summary.report.data_loaders 可用）
PROJECT_ROOT = Path(__file__).parent.parent.resolve()
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

logger = logging.getLogger("web_ui")

app = Flask(__name__)


@app.route("/")
def index():
    """首页: 重定向到 /selection 展示最新一日 stock_selection"""
    return render_template("selection.html", result=None)


@app.route("/selection")
def show_selection():
    """展示最新一日 stock_selection (复用 load_stock_selection_result)"""
    result = load_stock_selection_result(logger=logger)
    if result is None:
        logger.error("stock_selection_result 数据不可用")
        abort(404)
    return render_template("selection.html", result=result)


if __name__ == "__main__":
    # v1 启动方式: python web_ui/app.py
    logger.setLevel(logging.INFO)
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s"))
    logger.addHandler(handler)
    app.run(host="127.0.0.1", port=5000, debug=False)
