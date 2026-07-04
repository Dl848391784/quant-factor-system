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
    # R2 已实施, 不应再有 R2 占位
    assert "v0.4.8 R2 待实施" not in body
    # R3 占位仍存在
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


# ============================================================
# v0.4.8 R2: ob_quality 第八节分阶段 (全量 + Stage1 + Stage1 Bottom + Stage 3 LR)
# ============================================================


@pytest.fixture
def mock_obq_full_result():
    """v0.4.8 R2: ob_quality 完整 mock (含 all_composite_stocks + stage1_top + stage1_bottom + top_stocks)"""
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
        ],
        "stage1_top": [
            {"code": "600857", "composite_value": -1.5167, "rank": 1},
            {"code": "002025", "composite_value": 0.0032, "rank": 2},
        ],
        "stage1_bottom": [
            {"code": "000566", "composite_value": -2.6520, "rank": 56},
            {"code": "605178", "composite_value": -2.6520, "rank": 57},
        ],
        "all_composite_stocks": [
            {"code": "002687", "composite_value": 1.392, "rank": 1},
            {"code": "000520", "composite_value": 1.189, "rank": 2},
            {"code": "002437", "composite_value": 0.945, "rank": 3},
        ],
    }


def test_obq_section_renders_full_obq_layout(client, mock_obq_full_result):
    """v0.4.8 R2: ob_quality 第八节渲染 4 段表格 (全量 + Stage1 Top + Stage1 Bottom + Stage 3 LR)"""
    with (
        patch("web_ui.app.load_stock_selection_result", return_value=mock_obq_full_result),
        patch("web_ui.app.load_stock_name_map", return_value={"002687": "乔治白", "000520": "凤凰航运"}),
    ):
        resp = client.get("/report/2026-07-03")
    assert resp.status_code == 200
    body = resp.data.decode("utf-8")
    # 4 个 ob_quality 标题
    assert "全量展示" in body
    assert "Stage 1: composite 降序" in body
    assert "Stage 1 Bottom" in body
    assert "Stage 3: LR 短名单" in body
    # 真实股票 + 名称
    assert "乔治白" in body
    assert "002687" in body
    # meta-box 6 字段 (R4 字段补完时继续扩展)
    assert "0.5714" in body  # composite_score
    assert "rolling_icir_weight" in body
    assert "61" in body  # stocks_on_date


def test_obq_section_handles_missing_optional_fields(client, mock_obq_result):
    """v0.4.8 R2: mock 没 all_composite_stocks / stage1_bottom 时优雅降级, 不 500"""
    with (
        patch("web_ui.app.load_stock_selection_result", return_value=mock_obq_result),
        patch("web_ui.app.load_stock_name_map", return_value={}),
    ):
        resp = client.get("/report/2026-07-03")
    assert resp.status_code == 200
    body = resp.data.decode("utf-8")
    # mock_obq_result 没 all_composite_stocks / stage1_bottom, 应不渲染这些标题
    assert "全量展示" not in body
    assert "Stage 1 Bottom" not in body
    # 至少 Stage 3 表格有渲染
    assert "Stage 3: LR 短名单" in body
    # mock 股票: top_stocks 有 3 个, 但 stage1_top/stage1_bottom/all_composite_stocks 都是 []
    assert "002687" in body
    assert "000520" in body

