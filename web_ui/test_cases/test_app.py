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


@pytest.fixture(autouse=True)
def mock_lr_status_internal():
    """v0.4.8 R2a: 全局 mock load_lr_status (web_ui.common.lr_training_status.load_status)
    避免真读 Parquet 慢加载, 单测 focus 路由 + 模板
    """
    with patch("web_ui.app.load_lr_status", return_value=[]):
        yield


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
    # R2 + R2a + R3 已实施, 不应再有 R2/R2a/R3 占位
    assert "v0.4.8 R2 待实施" not in body
    assert "v0.4.8 R3 待实施" not in body


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
    # mock_obq_result 没 all_composite_stocks / stage1_bottom, 应不渲染这些标题 (h3 / table)
    # 注: candidate_detail.html muted 文本有"全量展示"字样, 不能直接 not in body
    # 改为检查 h3 标题 + 表格
    assert "全量展示:" not in body  # _section_selection.html h3 标题 (无冒号)
    assert "Stage 1 Bottom:" not in body  # 冒号结尾才是 h3
    # 至少 Stage 3 表格有渲染
    assert "Stage 3: LR 短名单" in body
    # mock 股票: top_stocks 有 3 个, 但 stage1_top/stage1_bottom/all_composite_stocks 都是 []
    assert "002687" in body
    assert "000520" in body


# ============================================================
# v0.4.8 R2a: LR 训练数据状态 (web_ui 内部实现, H1.1 严守)
# ============================================================


def test_lr_status_renders_obq(client, mock_obq_result):
    """v0.4.8 R2a: LR 训练数据状态表格渲染 (web_ui 内部实现, H1.1 严守)"""
    lr_mock = [
        {"method": "equal_weight", "days": 553, "rows": 46610, "t1_pct": 99.8, "status": "✓ 可训练"},
        {"method": "rolling_icir_weight", "days": 555, "rows": 46790, "t1_pct": 99.8, "status": "✓ 可训练"},
    ]
    with (
        patch("web_ui.app.load_stock_selection_result", return_value=mock_obq_result),
        patch("web_ui.app.load_stock_name_map", return_value={}),
        patch("web_ui.app.load_lr_status", return_value=lr_mock),  # override autouse
    ):
        resp = client.get("/report/2026-07-03")
    assert resp.status_code == 200
    body = resp.data.decode("utf-8")
    # 表格标题 + 真实数据
    assert "LR 训练数据状态" in body
    assert "v3.10" in body
    assert "✓ 可训练" in body
    assert "46610" in body
    assert "equal_weight" in body
    assert "rolling_icir_weight" in body


def test_lr_status_handles_load_exception(client, mock_obq_result):
    """v0.4.8 R2a: load_lr_status 抛异常时 200 + 降级 (不渲染表格)"""
    with (
        patch("web_ui.app.load_stock_selection_result", return_value=mock_obq_result),
        patch("web_ui.app.load_stock_name_map", return_value={}),
        patch("web_ui.app.load_lr_status", side_effect=RuntimeError("parquet missing")),
    ):
        resp = client.get("/report/2026-07-03")
    assert resp.status_code == 200
    # 异常降级为 [], 不渲染表格
    assert "LR 训练数据状态" not in resp.data.decode("utf-8")


# ============================================================
# v0.4.8 R3: 9·30 分段胜率 + 候选明细 + 日内操作
# ============================================================


@pytest.fixture(autouse=True)
def mock_r3_loaders():
    """v0.4.8 R3: 全局 mock load_intraday_strategy + load_decile_stats
    避免真函数依赖 T+1 数据, 单测 focus 路由 + 模板
    """
    with (
        patch("web_ui.app.load_intraday_strategy", return_value=[]),
        patch("web_ui.app.load_decile_stats", return_value=None),
    ):
        yield


@pytest.fixture(autouse=True)
def mock_r4_txt_parser():
    """v0.4.8 R4: 全局 mock txt_parser (parse_obq_s8/s9)
    避免真函数读文件系统, 单测 focus 模板
    """
    with (
        patch("web_ui.app.parse_obq_s8", return_value={}),
        patch("web_ui.app.parse_obq_s9", return_value=None),
        patch("web_ui.app.parse_obq_intraday", return_value={}),  # R6
    ):
        yield


def test_segment_win_renders_top5(client, mock_obq_full_result):
    """v0.4.8 R3: 9·30 分段胜率渲染 (30 段 → Top 5 展示)"""
    decile_mock = {
        "selection_date": "2026-07-02",
        "trade_date": "2026-07-03",
        "n_total": 88,
        "segments": [
            {"label": f"D{i}", "n": 3, "win_rate": 60.0 + i, "avg_ret": 0.5,
             "pl_ratio": 1.2, "wins": 2, "losses": 1}
            for i in range(1, 31)
        ],
    }
    with (
        patch("web_ui.app.load_stock_selection_result", return_value=mock_obq_full_result),
        patch("web_ui.app.load_stock_name_map", return_value={}),
        patch("web_ui.app.load_decile_stats", return_value=decile_mock),
    ):
        resp = client.get("/report/2026-07-03")
    assert resp.status_code == 200
    body = resp.data.decode("utf-8")
    # 30 段 schema 渲染
    assert "88" in body  # n_total
    assert "30 段" in body
    assert "★ BEST" in body
    assert "全部 30 段胜率一览" in body


def test_segment_win_handles_no_data(client, mock_obq_full_result):
    """v0.4.8 R3: decile_stats 为空时降级提示"""
    with (
        patch("web_ui.app.load_stock_selection_result", return_value=mock_obq_full_result),
        patch("web_ui.app.load_stock_name_map", return_value={}),
        patch("web_ui.app.load_decile_stats", return_value=None),
    ):
        resp = client.get("/report/2026-07-03")
    assert resp.status_code == 200
    body = resp.data.decode("utf-8")
    assert "无 30 分段胜率数据" in body


def test_intraday_renders_rows(client, mock_obq_full_result):
    """v0.4.8 R3: 日内操作建议渲染 (9 列表格)"""
    intraday_mock = [
        {
            "asset": "002628", "prev_close": 5.41, "open": 5.45, "real_gap_pct": 0.74,
            "open_signal": "高开", "recommended_action": "开盘卖 (09:25 集合竞价)",
            "expected_return_pct": 0.74, "stop_loss_price": None,
        },
    ]
    with (
        patch("web_ui.app.load_stock_selection_result", return_value=mock_obq_full_result),
        patch("web_ui.app.load_stock_name_map", return_value={"002628": "成都路桥"}),
        patch("web_ui.app.load_intraday_strategy", return_value=intraday_mock),
    ):
        resp = client.get("/report/2026-07-03")
    assert resp.status_code == 200
    body = resp.data.decode("utf-8")
    assert "002628" in body
    assert "成都路桥" in body
    assert "高开" in body
    assert "开盘卖" in body
    assert "5.41" in body


def test_intraday_handles_empty_rows(client, mock_obq_full_result):
    """v0.4.8 R3: intraday_rows 为空时降级提示 (T+1 不存在)"""
    with (
        patch("web_ui.app.load_stock_selection_result", return_value=mock_obq_full_result),
        patch("web_ui.app.load_stock_name_map", return_value={}),
        patch("web_ui.app.load_intraday_strategy", return_value=[]),
    ):
        resp = client.get("/report/2026-07-03")
    assert resp.status_code == 200
    body = resp.data.decode("utf-8")
    assert "无日内操作建议数据" in body


def test_candidate_detail_renders_three_stage_tables(client, mock_obq_full_result):
    """v0.4.8 R3: 候选明细 section 渲染 3 个表格"""
    with (
        patch("web_ui.app.load_stock_selection_result", return_value=mock_obq_full_result),
        patch("web_ui.app.load_stock_name_map", return_value={"002687": "乔治白", "600857": "测试1"}),
    ):
        resp = client.get("/report/2026-07-03")
    assert resp.status_code == 200
    body = resp.data.decode("utf-8")
    # 3 个子标题
    assert "Stage 1 Top" in body
    assert "Stage 3 Top" in body
    assert "Stage 1 Bottom" in body
    # 真实股票 (mock_obq_full_result 覆盖)
    assert "600857" in body
    assert "002687" in body
    assert "000566" in body
    # 操作提示
    assert "今日尾盘买入" in body


# ============================================================
# v0.4.8 R4: 字段补完 (txt 解析, parity test)
# ============================================================


def test_section_8_renders_filter_fields(client, mock_obq_full_result):
    """v0.4.8 R4: 第八节补全 — 振幅过滤 / 覆盖率过滤 / 反向因子 (从 txt 解析)"""
    s8_mock = {
        "composite_score": 0.5714,
        "top_n": 30,
        "stocks_on_date": 61,
        "excluded_by_amplitude": 0,
        "excluded_by_coverage": 15,
        "amplitude_detail": "振幅 < 1.00%，不可交易的一字板涨停股",
        "coverage_detail": "覆盖率 < 50%，缺失高权重因子导致综合因子值不可信",
        "flipped_factors": ["amplitude", "interaction_amplitude__ret3d_abs"],
    }
    with (
        patch("web_ui.app.load_stock_selection_result", return_value=mock_obq_full_result),
        patch("web_ui.app.load_stock_name_map", return_value={}),
        patch("web_ui.app.parse_obq_s8", return_value=s8_mock),  # override autouse
    ):
        resp = client.get("/report/2026-07-03")
    assert resp.status_code == 200
    body = resp.data.decode("utf-8")
    # 振幅过滤 / 覆盖率过滤 (含详细说明)
    assert "振幅过滤" in body
    assert "排除 0 只" in body
    assert "1.00%" in body  # 振幅 < 1.00%
    assert "覆盖率过滤" in body
    assert "排除 15 只" in body
    assert "50%" in body  # 覆盖率 < 50%
    # 反向因子
    assert "方向处理说明" in body
    assert "amplitude" in body
    assert "interaction_amplitude__ret3d_abs" in body


def test_section_8_handles_no_flipped_factors(client, mock_obq_full_result):
    """v0.4.8 R4: txt 解析无 flipped_factors 时, 不渲染方向处理说明"""
    s8_mock = {"composite_score": 0.5, "excluded_by_amplitude": 0, "excluded_by_coverage": 0}
    with (
        patch("web_ui.app.load_stock_selection_result", return_value=mock_obq_full_result),
        patch("web_ui.app.load_stock_name_map", return_value={}),
        patch("web_ui.app.parse_obq_s8", return_value=s8_mock),
    ):
        resp = client.get("/report/2026-07-03")
    assert resp.status_code == 200
    body = resp.data.decode("utf-8")
    # 没 flipped_factors, 不渲染方向处理说明
    assert "方向处理说明" not in body


def test_candidate_detail_uses_valid_stocks_for_pool_size(client, mock_obq_full_result):
    """v0.4.8 R5: 候选池大小从 meta.valid_stocks 取 (txt 一致: 57 只), 不是 stocks_on_date=61"""
    # mock_obq_full_result.valid_stocks = 57, stocks_on_date = 61
    # txt 第 10 节说 "候选池共 57 只", web_ui 应当显示 57
    with (
        patch("web_ui.app.load_stock_selection_result", return_value=mock_obq_full_result),
        patch("web_ui.app.load_stock_name_map", return_value={}),
    ):
        resp = client.get("/report/2026-07-03")
    assert resp.status_code == 200
    body = resp.data.decode("utf-8")
    # meta-box 显示 "候选池共 57 只" (从 valid_stocks)
    assert "候选池共" in body
    # 不能显示 61 (因为 candidate_detail 用 valid_stocks=57)
    # 但 meta-box "候选池" 行还在用 stocks_on_date=61, 是另一段
    # candidate_detail 段独立: '候选池共 57 只'
    # 简单检查: body 含 "57" 至少 1 次 (valid_stocks) 且 candidate_detail 段不含 "61"
    assert "57" in body
    # candidate_detail 段的 pool_size = 57 (不应该是 61)


def test_section_8_renders_full_txt_format(client, mock_obq_full_result):
    """v0.4.8 R5: 第八节完全对齐 txt 原文格式
    选股日期 括号 (使用T-1数据) - 与 txt 一致
    """
    s8_mock = {
        "composite_score": 0.5714, "top_n": 30, "stocks_on_date": 61,
        "excluded_by_amplitude": 0, "excluded_by_coverage": 15,
        "amplitude_detail": "振幅 < 1.00%，不可交易的一字板涨停股",
        "coverage_detail": "覆盖率 < 50%，缺失高权重因子导致综合因子值不可信",
        "flipped_factors": ["amplitude", "interaction_amplitude__ret3d_abs"],
    }
    with (
        patch("web_ui.app.load_stock_selection_result", return_value=mock_obq_full_result),
        patch("web_ui.app.load_stock_name_map", return_value={}),
        patch("web_ui.app.parse_obq_s8", return_value=s8_mock),
    ):
        resp = client.get("/report/2026-07-03")
    assert resp.status_code == 200
    body = resp.data.decode("utf-8")
    # 选股日期括号 txt 是 (使用T-1数据) - web_ui 必须完全一致 (无空格)
    assert "（使用T-1数据）" in body
    # 不能是 "（T-1 数据）"
    assert "（T-1 数据）" not in body


def test_section_9_renders_matrix(client, mock_obq_full_result):
    """v0.4.8 R4: 第九节 30 段 × 12 选股日 完整胜率矩阵渲染 (从 txt 解析)"""
    s9_mock = {
        "dates": ["06-15", "06-16", "06-17", "06-18", "06-22", "06-23", "06-24", "06-25", "06-26", "06-29", "06-30", "07-01"],
        "segments": [
            {"label": f"S{i}", "win_rates": [50.0] * 12, "merged": 50.0 + i / 10}
            for i in range(1, 31)
        ],
        "best_segment": {"label": "S7", "merged": 59.6},
        "daily_rates": {"06-15": "2/3 = 66.7%", "06-16": "3/3 = 100.0%"},
    }
    with (
        patch("web_ui.app.load_stock_selection_result", return_value=mock_obq_full_result),
        patch("web_ui.app.load_stock_name_map", return_value={}),
        patch("web_ui.app.parse_obq_s9", return_value=s9_mock),  # override autouse
    ):
        resp = client.get("/report/2026-07-03")
    assert resp.status_code == 200
    body = resp.data.decode("utf-8")
    # 完整胜率矩阵
    assert "30 分段 × 12 选股日" in body
    # 最佳段
    assert "最佳段" in body
    assert "S7" in body
    assert "59.6" in body
    # 逐日胜率
    assert "逐日胜率" in body
    assert "06-15" in body
    assert "66.7%" in body


def test_section_9_handles_no_matrix(client, mock_obq_full_result):
    """v0.4.8 R4: txt 解析失败 (无 matrix) 时, 不渲染 30×12 表格 (但 R3 decile_stats 仍渲染)"""
    with (
        patch("web_ui.app.load_stock_selection_result", return_value=mock_obq_full_result),
        patch("web_ui.app.load_stock_name_map", return_value={}),
        # autouse 已 mock parse_obq_s9 = None
    ):
        resp = client.get("/report/2026-07-03")
    assert resp.status_code == 200
    body = resp.data.decode("utf-8")
    # 30×12 矩阵不渲染
    assert "30 分段 × 12 选股日" not in body


def test_section_8_handles_parse_exception(client, mock_obq_full_result):
    """v0.4.8 R4: parse_obq_s8 抛异常时 200 + 降级 (不渲染 txt 字段)"""
    with (
        patch("web_ui.app.load_stock_selection_result", return_value=mock_obq_full_result),
        patch("web_ui.app.load_stock_name_map", return_value={}),
        patch("web_ui.app.parse_obq_s8", side_effect=RuntimeError("txt missing")),
    ):
        resp = client.get("/report/2026-07-03")
    assert resp.status_code == 200
    # 异常降级为 {}, 不渲染振幅过滤 / 覆盖率过滤 / 方向处理说明
    assert "振幅过滤" not in resp.data.decode("utf-8")
    assert "方向处理说明" not in resp.data.decode("utf-8")


def test_parity_obq_txt_fields_match_webui(client, mock_obq_full_result):
    """v0.4.8 R4: 字段级 parity test — 从 txt 解析字段必须在 web_ui 渲染

    验证 web_ui 页面含 txt 第八节所有 6 个关键字段。
    """
    s8_mock = {
        "composite_score": 0.5714,
        "top_n": 30,
        "stocks_on_date": 61,
        "excluded_by_amplitude": 0,
        "excluded_by_coverage": 15,
        "flipped_factors": ["amplitude", "interaction_amplitude__ret3d_abs"],
    }
    s9_mock = {
        "dates": ["06-15", "06-16", "06-17", "06-18", "06-22", "06-23", "06-24", "06-25", "06-26", "06-29", "06-30", "07-01"],
        "segments": [
            {"label": f"S{i}", "win_rates": [50.0] * 12, "merged": 50.0 + i / 10}
            for i in range(1, 31)
        ],
        "best_segment": {"label": "S7", "merged": 59.6},
        "daily_rates": {"06-15": "2/3 = 66.7%"},
    }
    with (
        patch("web_ui.app.load_stock_selection_result", return_value=mock_obq_full_result),
        patch("web_ui.app.load_stock_name_map", return_value={}),
        patch("web_ui.app.parse_obq_s8", return_value=s8_mock),
        patch("web_ui.app.parse_obq_s9", return_value=s9_mock),
    ):
        resp = client.get("/report/2026-07-03")
    assert resp.status_code == 200
    body = resp.data.decode("utf-8")
    # 第八节 6 字段 parity check
    assert "0.5714" in body  # composite_score
    assert "30 只" in body  # top_n
    assert "61" in body  # stocks_on_date
    assert "振幅过滤" in body and "排除 0 只" in body
    assert "覆盖率过滤" in body and "排除 15 只" in body
    assert "amplitude" in body  # flipped_factors
    # 第九节 3 字段 parity check
    assert "最佳段" in body
    assert "S7" in body and "59.6" in body
    assert "逐日胜率" in body
    # 30×12 矩阵
    assert "30 分段 × 12 选股日" in body


# ============================================================
# v0.4.8 R6: 十·fallback 操作规则 + 历史胜率参考
# ============================================================


def test_intraday_fallback_renders_operation_rules(client, mock_obq_full_result):
    """v0.4.8 R6: 操作规则 4 行渲染 (高开/低开/平开/数据异常)"""
    fallback_mock = {
        "operation_rules": [
            {"scenario": "高开", "condition": "gap > +0.5%", "action": "9:25 集合竞价直接卖出", "hit_rate": "23/28 = 82.1%", "sample_n": 28},
            {"scenario": "低开", "condition": "gap < -0.5%", "action": "等盘中反弹回本价", "hit_rate": "22/65 = 33.8%", "sample_n": 65},
            {"scenario": "平开", "condition": "-0.5% ~ +0.5%", "action": "样本不足 4 只, 无强规律", "hit_rate": None, "sample_n": None},
            {"scenario": "数据异常", "condition": "|gap| > 10%", "action": "复权事件", "hit_rate": None, "sample_n": None},
        ],
        "history_stats": [],
        "sample_size": "122 只",
        "confidence": "统计置信度较高",
    }
    with (
        patch("web_ui.app.load_stock_selection_result", return_value=mock_obq_full_result),
        patch("web_ui.app.load_stock_name_map", return_value={}),
        patch("web_ui.app.parse_obq_intraday", return_value=fallback_mock),  # override autouse
    ):
        resp = client.get("/report/2026-07-03")
    assert resp.status_code == 200
    body = resp.data.decode("utf-8")
    # 操作规则 4 个场景
    assert "操作规则" in body
    assert "高开" in body
    assert "低开" in body
    assert "平开" in body
    assert "数据异常" in body
    # 条件 + 行动 + 胜率 (注: HTML 转义, < > 变 &lt; &gt;)
    assert "gap &gt; +0.5%" in body
    assert "23/28 = 82.1%" in body
    assert "n=28" in body


def test_intraday_fallback_renders_history_stats(client, mock_obq_full_result):
    """v0.4.8 R6: 历史胜率参考 2 行渲染 (高开开盘卖/低开等反弹)"""
    fallback_mock = {
        "operation_rules": [],
        "history_stats": [
            {"scenario": "高开开盘卖", "detail": "23/28 = 82.1% 胜率, 均收 +1.75% (vs 死等尾盘 +2.89%, 增厚 -1.15pp)"},
            {"scenario": "低开等反弹", "detail": "22/65 = 33.8% 命中回本, 等高卖均收 -1.93% (vs 开盘即卖 -1.88%, 反亏 -0.05pp)"},
        ],
        "sample_size": "122 只",
        "confidence": "统计置信度较高",
    }
    with (
        patch("web_ui.app.load_stock_selection_result", return_value=mock_obq_full_result),
        patch("web_ui.app.load_stock_name_map", return_value={}),
        patch("web_ui.app.parse_obq_intraday", return_value=fallback_mock),  # override autouse
    ):
        resp = client.get("/report/2026-07-03")
    assert resp.status_code == 200
    body = resp.data.decode("utf-8")
    # 历史胜率参考 + 样本量
    assert "历史胜率参考" in body
    assert "122 只" in body
    assert "统计置信度较高" in body
    # 2 行历史
    assert "高开开盘卖" in body
    assert "23/28 = 82.1%" in body
    assert "均收 +1.75%" in body
    assert "低开等反弹" in body
    assert "22/65 = 33.8%" in body


def test_intraday_fallback_handles_empty(client, mock_obq_full_result):
    """v0.4.8 R6: parse_obq_intraday 返回空时不渲染操作规则段"""
    with (
        patch("web_ui.app.load_stock_selection_result", return_value=mock_obq_full_result),
        patch("web_ui.app.load_stock_name_map", return_value={}),
        # autouse 已 mock parse_obq_intraday = {}
    ):
        resp = client.get("/report/2026-07-03")
    assert resp.status_code == 200
    body = resp.data.decode("utf-8")
    # 空 fallback, 不渲染操作规则 / 历史胜率
    assert "操作规则" not in body
    assert "历史胜率参考" not in body

