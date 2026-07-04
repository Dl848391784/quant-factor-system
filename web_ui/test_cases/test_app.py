"""web_ui/test_cases/test_app.py

测试 web_ui Flask 路由（v0.3 v1）
mock load_stock_selection_result 以隔离测试（避免依赖真实 Parquet 数据）
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest


# PROJECT_ROOT 加入 sys.path 让 from web_ui.app 可导入
PROJECT_ROOT = Path(__file__).parent.parent.parent.resolve()
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from web_ui.app import app  # noqa: E402


@pytest.fixture
def client():
    """Flask test client"""
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


@pytest.fixture
def mock_selection_result():
    """mock load_stock_selection_result 返回值（基于真实结构）"""
    return {
        "meta": {
            "selection_date": "2026-07-03",
            "weight_method": "rolling_icir_weight",
            "factor_direction": "positive",
            "top_n": 30,
            "composite_score": 0.7766,
            "stocks_on_date": 2794,
            "valid_stocks": 90,
            "stage1_pool_size": 200,
        },
        "top_stocks": [
            {"code": "000739", "composite_value": -1.3469, "rank": 2705},
            {"code": "603682", "composite_value": -0.5521, "rank": 2706},
            {"code": "002739", "composite_value": 0.1234, "rank": 2707},
        ],
        "stage1_top": [],
        "stage2_top": [],
        "stage3_top": [],
    }


def test_index_renders_empty(client):
    """GET / 返回 200 + 空模板（提示访问 /selection）"""
    resp = client.get("/")
    assert resp.status_code == 200
    assert b"\xe6\x9c\x80\xe6\x96\xb0" in resp.data  # "最新" 中文 UTF-8


def test_selection_returns_html_with_data(client, mock_selection_result):
    """GET /selection 返回 200 + 表格含 3 只 mock 股票"""
    with patch("web_ui.app.load_stock_selection_result", return_value=mock_selection_result):
        resp = client.get("/selection")
    assert resp.status_code == 200
    body = resp.data.decode("utf-8")
    # meta 关键字段
    assert "2026-07-03" in body
    assert "rolling_icir_weight" in body
    # 表格 3 只股票代码
    assert "000739" in body
    assert "603682" in body
    assert "002739" in body
    # 表格行数：1 表头 + 3 数据
    assert body.count("<tr>") == 4


def test_selection_returns_404_when_data_unavailable(client):
    """load_stock_selection_result 返回 None 时 /selection 返回 404"""
    with patch("web_ui.app.load_stock_selection_result", return_value=None):
        resp = client.get("/selection")
    assert resp.status_code == 404


def test_selection_logs_error_on_missing_data(client, caplog):
    """load_stock_selection_result 返回 None 时 logger 记录 error"""
    import logging

    with (
        caplog.at_level(logging.ERROR, logger="web_ui"),
        patch("web_ui.app.load_stock_selection_result", return_value=None),
    ):
        client.get("/selection")
    assert any("stock_selection_result" in rec.message for rec in caplog.records)
