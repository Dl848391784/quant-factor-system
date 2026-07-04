"""web_ui/test_cases/test_app.py

测试 web_ui Flask 路由（v0.4.8 R1）
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
def mock_obq_result():
    """v0.4.8: ob_quality mock (基于 v0.4.6.2 R2b 真实结构)"""
    return {
        "meta": {
            "selection_date": "2026-07-03",
            "weight_method": "rolling_icir_weight",
            "factor_direction": "positive",
            "top_n": 30,
            "composite_score": 0.5714,
            "stocks_on_date": 61,
            "valid_stocks": 57,
            "stage1_pool_size": 30,
        },
        "top_stocks": [
            {"code": "002687", "composite_value": 1.392, "rank": 1},
            {"code": "000520", "composite_value": 1.189, "rank": 2},
            {"code": "002437", "composite_value": 0.945, "rank": 3},
        ],
    }


# ============================================================
# v0.4.8 R1: /report/<date> 路由 (固定 ob_quality, 无 ?pipeline= 切换)
# ============================================================


def test_index_redirects_to_report_latest(client):
    """v0.4.8: GET / 302 → /report/latest"""
    resp = client.get("/", follow_redirects=False)
    assert resp.status_code == 302
    assert resp.headers["Location"] == "/report/latest"


def test_report_latest_redirects_to_date(client, mock_obq_result):
    """v0.4.8: GET /report/latest 302 → /report/<selection_date>"""
    with patch("web_ui.app.load_stock_selection_result", return_value=mock_obq_result):
        resp = client.get("/report/latest", follow_redirects=False)
    assert resp.status_code == 302
    assert "/report/2026-07-03" in resp.headers["Location"]


def test_report_latest_404_when_no_data(client):
    """load_stock_selection_result 返回 None 时 /report/latest 404"""
    with patch("web_ui.app.load_stock_selection_result", return_value=None):
        resp = client.get("/report/latest")
    assert resp.status_code == 404


def test_report_renders_obq_page(client, mock_obq_result):
    """v0.4.8 R1: GET /report/<date> 200 + 12 section 锚点 + 8/9/10 占位"""
    with patch("web_ui.app.load_stock_selection_result", return_value=mock_obq_result):
        resp = client.get("/report/2026-07-03")
    assert resp.status_code == 200
    body = resp.data.decode("utf-8")
    # 12 个 section 锚点 (零~十·fallback)
    sections = [
        "section-freshness", "section-ic", "section-backtest", "section-corr",
        "section-filter", "section-comp", "section-compare", "section-weights",
        "section-selection", "section-segment-win", "section-candidate-detail",
        "section-intraday",
    ]
    for sec in sections:
        assert f'id="{sec}"' in body, f"missing anchor: {sec}"
    # ob_quality pipeline 标识
    assert "ob_quality" in body
    assert "v0.4.8" in body
    # R1 不渲染 top_stocks (R2 才实施) - 仅 meta-box 显示 selection_date
    assert "2026-07-03" in body
    # R2-R4 占位标记
    assert "v0.4.8 R2 待实施" in body
    assert "v0.4.8 R3 待实施" in body


def test_report_invalid_date_returns_400(client):
    """v0.4.8: GET /report/<bad-date> 400 (日期格式校验)"""
    resp = client.get("/report/not-a-date")
    assert resp.status_code == 400


def test_report_handles_none_data(client):
    """load_stock_selection_result 返回 None 时 /report/<date> 仍 200 (result=None 渲染)"""
    with patch("web_ui.app.load_stock_selection_result", return_value=None):
        resp = client.get("/report/2026-07-03")
    assert resp.status_code == 200
    body = resp.data.decode("utf-8")
    # None 时 expected_data_date 显示 T-1 提示
    assert "T-1" in body
