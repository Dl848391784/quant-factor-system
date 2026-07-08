"""v0.4.8 R49 单元测试 — 30 段 AI 角色.

3 个测试目标 (跟 R49a-1 plan 对齐):
  - LLM 客户端: endpoint/retry/fallback (R47 silent fallback + R44 测试设计)
  - 角色 prompt: 30 段同模板 + 不含性格关键字 (Round 3 字面)
  - 反思: 窗口不足 → [⚠️] 标记 (R47 v1.5.18)

测试设计来源:
  - R44 "真实 parquet + mock 上游" 双重验证 (v1.5.14 §18.1f)
  - R47 silent fallback 子类 (v1.5.18)
  - R48 5 个陷阱 (paths.py 字段陷阱, monkeypatch 位置)
  - R43 实施前 3 步复测法 (v1.5.13 §18.1f)
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest
from summary.report.llm_provider import (
    DEFAULT_BASE_URL,
    DEFAULT_MODEL,
    MinMaxClient,
    _load_api_key,
    _load_base_url,
    _parse_minimax_response,
)
from summary.report.segment_ai_db import (
    SEGMENT_AI_COLUMNS,
    _empty_fallback_row,
    compute_one_segment_decision,
    compute_reflection_for_segment,
    load_segment_ai_simulation,
    save_segment_ai_simulation,
)
from summary.report.segment_ai_prompts import (
    assert_no_personality_keywords,
    build_role_prompt,
)


# ════════════════════════════════════════════════════════════════════
# Fixtures
# ════════════════════════════════════════════════════════════════════


def _fake_minimax_ok_response(
    text: str = '{"decision":"operate","confidence":0.8,"reasoning":"客观: 当日胜率 60% > 50%, 收益 +1% > 0, 合并胜率 55% > 50%, 合并资产 1.05 > 1.00, 4 项信号全正","data_observations":["signal A","signal B"]}',
) -> dict:
    """Mock 1 个正常 Anthropic Messages API 响应."""
    return {
        "id": "msg_test_001",
        "type": "message",
        "role": "assistant",
        "content": [{"type": "text", "text": text}],
        "model": "MiniMax-M3",
        "stop_reason": "end_turn",
        "usage": {"input_tokens": 100, "output_tokens": 50},
    }


def _sample_daily_data() -> dict:
    return {
        "daily_win_rate": 60.00,
        "daily_wins": 3,
        "daily_total": 5,
        "daily_return_pct": 1.50,
        "cum_win_rate": 55.00,
        "cum_wins": 11,
        "cum_total": 20,
        "cum_asset_value": 1.0500,
    }


def _sample_history_data() -> dict:
    return {
        "history_win_rates": [50.0, 55.0, 60.0, 65.0, 60.0],
        "history_return_pcts": [0.5, -0.3, 1.2, 0.8, 0.5],
        "history_cum_win_rates": [50.0, 52.5, 55.0, 57.5, 58.0],
        "history_cum_asset_values": [1.005, 1.002, 1.014, 1.022, 1.027],
        "history_start": "2026-06-29",
        "history_end": "2026-07-03",
    }


# ════════════════════════════════════════════════════════════════════
# Test 1: MinMaxClient endpoint + retry + fallback (R47 silent fallback)
# ════════════════════════════════════════════════════════════════════


def test_minimax_client_calls_anthropic_endpoint_with_correct_headers():
    """mock requests.post, 验证 POST URL = base_url + /v1/messages + headers 含 x-api-key +
    x-anthropic-version + body 含 model=MiniMax-M3 + max_tokens + system + messages."""
    client = MinMaxClient(api_key="sk-test-key-xxx")

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = _fake_minimax_ok_response()
    mock_resp.raise_for_status = MagicMock()

    with patch("summary.report.llm_provider.requests.post", return_value=mock_resp) as mock_post:
        result = client.call(
            system="你是客观分析师",
            user="请决策",
            max_tokens=300,
        )

    # 验证 POST URL
    called_args = mock_post.call_args
    assert called_args is not None
    args, kwargs = called_args
    url = args[0] if args else kwargs["url"]
    assert url == f"{DEFAULT_BASE_URL}/v1/messages", f"POST URL wrong: {url}"

    # 验证 headers
    headers = kwargs.get("headers", {})
    assert headers.get("x-api-key") == "sk-test-key-xxx"
    assert headers.get("anthropic-version") == "2023-06-01"

    # 验证 body (json=payload)
    body = kwargs.get("json", {})
    assert body["model"] == DEFAULT_MODEL
    assert body["max_tokens"] == 300
    assert "system" in body
    assert "messages" in body

    # 验证返回值
    assert result["decision"] == "operate"
    assert result["confidence"] == 0.8
    assert "4 项信号全正" in result["reasoning"]


def test_minimax_client_retries_3_times_then_fallback_on_500():
    """mock 3 次连续 500, 验证 fallback dict 含 [⚠️] 标记 + decision=skip (R47 silent fallback)."""
    client = MinMaxClient(api_key="sk-test-key-xxx")

    mock_resp = MagicMock()
    mock_resp.status_code = 500
    mock_resp.text = "Internal Server Error"
    # raise_for_status 在 status != 2xx 时 raise HTTPError
    from requests import HTTPError

    mock_resp.raise_for_status.side_effect = HTTPError("500 Server Error")

    with (
        patch("summary.report.llm_provider.requests.post", return_value=mock_resp) as mock_post,
        patch("summary.report.llm_provider.time.sleep"),  # skip 重试 sleep
    ):
        result = client.call(system="sys", user="usr")

    # 3 次重试
    assert mock_post.call_count == 3
    # fallback dict 特征
    assert result["decision"] == "skip"
    assert result["confidence"] == 0.0
    assert "[⚠️" in result["reasoning"] or "[警告" in result["reasoning"] or "⚠️" in result["reasoning"]
    assert result["data_observations"] == []


def test_minimax_parse_response_invalid_decision_falls_back_to_skip():
    """response 里 decision 不在 (operate/skip) → fallback skip (防 LLM 自创)."""
    bad_response = _fake_minimax_ok_response(
        '{"decision":"BUY","confidence":0.5,"reasoning":"x","data_observations":[]}'
    )
    parsed = _parse_minimax_response(bad_response, model=DEFAULT_MODEL)
    assert parsed["decision"] == "skip"
    assert parsed["confidence"] == 0.5  # 没强制改 confidence


def test_minimax_parse_response_invalid_json_falls_back():
    """response 不是合法 JSON → fallback dict (R47 silent fallback)."""
    bad_response = _fake_minimax_ok_response("not json at all just text")
    parsed = _parse_minimax_response(bad_response, model=DEFAULT_MODEL)
    assert parsed["decision"] == "skip"
    assert "[⚠️" in parsed["reasoning"]


def test_minimax_parse_response_strips_markdown_code_fences():
    """实测 2026-07-08 MiniMax-M3 输出 ```json\\n{...}\\n``` markdown fence — parser 必须先 strip。

    R49 实战锚点: 实跑发现 markdown fence 不 strip → json.loads 失败 → fallback skip + confidence=0
    (vs 真实 confidence 0.55-0.72). 这是 R49 业务调用 100% 命中场景必须修的 bug.

    v1.5.19 v1.5.21 R47 实战: 真实 LLM call 前必有真实 API call 验证, 不凭印象答.
    """
    # 测试 3 种 markdown fence 格式 + 1 个裸 JSON (control case)
    markdown_responses = [
        # 形式 1: ```json \\n { ... } \\n```
        _fake_minimax_ok_response(
            '```json\n{"decision": "operate", "confidence": 0.62, "reasoning": "测试 markdown fence 1", "data_observations": []}\n```'
        ),
        # 形式 2: ``` \\n { ... } \\n``` (没 json 字眼)
        _fake_minimax_ok_response(
            '```\n{"decision": "skip", "confidence": 0.45, "reasoning": "测试 markdown fence 2", "data_observations": []}\n```'
        ),
        # 形式 3: ```json{...}``` (无空格直接 JSON)
        _fake_minimax_ok_response(
            '```json{"decision": "operate", "confidence": 0.78, "reasoning": "测试 markdown 3", "data_observations": []}```'
        ),
        # control case: 裸 JSON (之前一直 work)
        _fake_minimax_ok_response(
            '{"decision": "operate", "confidence": 0.91, "reasoning": "裸 JSON", "data_observations": []}'
        ),
    ]
    expected_decisions = ["operate", "skip", "operate", "operate"]
    expected_confidences = [0.62, 0.45, 0.78, 0.91]
    for resp, exp_d, exp_c in zip(markdown_responses, expected_decisions, expected_confidences):
        parsed = _parse_minimax_response(resp, model=DEFAULT_MODEL)
        assert parsed["decision"] == exp_d, f"markdown fence parse fail: got {parsed['decision']}"
        assert abs(parsed["confidence"] - exp_c) < 0.01, (
            f"markdown fence conf: got {parsed['confidence']}, expected {exp_c}"
        )
        assert "[⚠️" not in parsed["reasoning"], "markdown fence should not trigger fallback"


# Test 2: Role prompt Round 3 字面约束 — 30 段同模板 + 不含性格关键字
# ════════════════════════════════════════════════════════════════════


def test_role_prompt_no_personality_keywords_for_all_30_segments():
    """Round 3 字面: 30 段必须公正公平不带性格色彩.
    Loop S1~S30, 每个 prompt 必不包含激进/保守/中性/风险偏好等关键字."""
    for i in range(1, 31):
        seg_label = f"S{i}"
        prompt = build_role_prompt(
            segment_label=seg_label,
            selection_date="2026-07-06",
            trade_date="2026-07-07",
            daily_data=_sample_daily_data(),
            history_data=_sample_history_data(),
            history_window=5,
        )
        # Round 3 字面约束
        assert_no_personality_keywords(prompt)
        # 段号必须正确替换
        assert f"**{seg_label}**" in prompt, f"{seg_label} not in prompt header"


def test_role_prompt_past_decisions_serialization():
    """past_decisions list → JSON 字符串, 出现在 prompt 里."""
    past_decisions = [
        {"date": "2026-07-01", "decision": "operate", "actual_return": 0.01},
        {"date": "2026-07-02", "decision": "skip", "actual_return": -0.02},
    ]
    prompt = build_role_prompt(
        segment_label="S15",
        selection_date="2026-07-06",
        trade_date="2026-07-07",
        daily_data=_sample_daily_data(),
        history_data=_sample_history_data(),
        past_decisions=past_decisions,
        history_window=5,
    )
    assert '"operate"' in prompt
    assert '"skip"' in prompt
    assert "2026-07-01" in prompt
    assert "2026-07-02" in prompt


# ════════════════════════════════════════════════════════════════════
# Test 3: 反思窗口不足 → [⚠️] 标记 (R47 v1.5.18 silent fallback)
# ════════════════════════════════════════════════════════════════════


def test_compute_reflection_insufficient_window_marks_warning():
    """K=5 但只有 3 天 → reflection_text is None + warning_text 含 [⚠️] (R47 防御)."""
    past_decisions = [
        {"date": "2026-07-03", "decision": "operate", "actual_return": 0.01},
        {"date": "2026-07-04", "decision": "skip", "actual_return": 0.005},
        {"date": "2026-07-05", "decision": "operate", "actual_return": -0.01},
    ]
    reflection_text, warning_text = compute_reflection_for_segment(
        past_decisions_with_actual=past_decisions,
        k=5,
    )
    assert reflection_text is None  # NOT empty string
    assert warning_text is not None
    assert "[⚠️" in warning_text
    assert "3/5" in warning_text or "不足" in warning_text


def test_compute_reflection_sufficient_window_no_warning():
    """K=5 且有 5 天数据 → reflection_text 是非 None str + warning_text is None."""
    past_decisions = [
        {
            "date": f"2026-07-0{i + 1}",
            "decision": "operate" if i % 2 == 0 else "skip",
            "actual_return": 0.01 if i % 2 == 0 else -0.01,
        }
        for i in range(5)
    ]
    reflection_text, warning_text = compute_reflection_for_segment(
        past_decisions_with_actual=past_decisions,
        k=5,
    )
    assert reflection_text is not None
    assert "决策" in reflection_text
    assert warning_text is None


# ════════════════════════════════════════════════════════════════════
# Test 4: compute_one_segment_decision (mock LLM client)
# ════════════════════════════════════════════════════════════════════


def test_compute_one_segment_decision_returns_valid_row():
    """用 mock MinMaxClient, 验证返回 row schema + 字段全部存在."""
    mock_client = MagicMock()
    mock_client.call.return_value = {
        "decision": "operate",
        "confidence": 0.85,
        "reasoning": "4 项信号全正",
        "data_observations": ["obs1", "obs2"],
    }
    mock_client.base_url = DEFAULT_BASE_URL
    mock_client.model = DEFAULT_MODEL

    row = compute_one_segment_decision(
        segment_label="S7",
        selection_date="2026-07-06",
        trade_date="2026-07-07",
        daily_data=_sample_daily_data(),
        history_data=_sample_history_data(),
        client=mock_client,
    )

    # schema 必填字段
    for col in SEGMENT_AI_COLUMNS:
        assert col in row, f"missing column {col}"
    assert row["segment_label"] == "S7"
    assert row["decision"] == "operate"
    assert row["confidence"] == 0.85
    assert row["model_name"] == DEFAULT_MODEL


def test_compute_one_segment_decision_on_llm_failure_returns_skip_row():
    """LLM call 失败 → fallback dict → decision=skip (R47 silent fallback).
    这条 R48 修复实战要的关键: 当上游 LLM 抛错, 决策字段 graceful degrade."""
    mock_client = MagicMock()
    mock_client.call.return_value = {
        "decision": "skip",
        "confidence": 0.0,
        "reasoning": "[⚠️ LLM 调用失败 (HTTPError): 500 Internal Server Error]",
        "data_observations": [],
    }
    mock_client.base_url = DEFAULT_BASE_URL
    mock_client.model = DEFAULT_MODEL

    row = compute_one_segment_decision(
        segment_label="S20",
        selection_date="2026-07-06",
        trade_date="2026-07-07",
        daily_data=_sample_daily_data(),
        history_data=_sample_history_data(),
        client=mock_client,
    )
    assert row["decision"] == "skip"
    assert "[⚠️" in row["reasoning_text"]


# ════════════════════════════════════════════════════════════════════
# Test 5: save/load round-trip (真实 tempfile, 跟 R44 测试设计 "真实端到端" 同源)
# ════════════════════════════════════════════════════════════════════


def test_save_load_segment_ai_simulation_roundtrip(tmp_path: Path):
    """save → load → 一致; parquet schema 跟 SEGMENT_AI_COLUMNS 完全对齐.
    跟 R44 测试设计实战同源: 真实 parquet + 临时文件, **不**mock."""
    rows = [
        {
            "pipeline": "ob_quality",
            "selection_date": "2026-07-06",
            "trade_date": "2026-07-07",
            "weight_method": "rolling_icir_weight",
            "segment_label": f"S{i}",
            "decision": "operate" if i % 2 == 0 else "skip",
            "confidence": 0.5 + i * 0.01,
            "reasoning_text": f"seg{i} reasoning",
            "data_observations_json": '["obs"]',
            "history_window": 5,
            "past_decisions_json": None,
            "reflection_text": None,
            "reflection_k_days": 5,
            "model_name": DEFAULT_MODEL,
            "provider_endpoint": f"{DEFAULT_BASE_URL}/v1/messages",
            "created_at": "2026-07-06T10:00:00+00:00",
        }
        for i in range(1, 11)
    ]

    # patch _result_path to tmp_path
    with patch("summary.report.segment_ai_db._result_path") as mock_fp:
        mock_fp.return_value = tmp_path / "segment_ai_simulation.parquet"
        # 1. save
        fp = save_segment_ai_simulation(rows, weight_method="rolling_icir_weight")
        assert fp.exists()
        # 2. load
        df = load_segment_ai_simulation(
            pipeline="ob_quality",
            selection_date="2026-07-06",
            weight_method="rolling_icir_weight",
        )
        # 3. round-trip 一致
        assert len(df) == 10
        for col in SEGMENT_AI_COLUMNS:
            assert col in df.columns, f"missing column in loaded df: {col}"
        # 取第 1 行验字段值
        first = df.iloc[0]
        assert first["segment_label"] == "S1"
        assert first["decision"] == "skip"  # 1 % 2 == 1 → skip


def test_save_segment_ai_simulation_empty_rows_warns_but_not_raises(tmp_path: Path):
    """rows=[] → logger.warning 但不抛 (R47 silent fallback 防御: graceful degrade)."""
    with patch("summary.report.segment_ai_db._result_path") as mock_fp:
        mock_fp.return_value = tmp_path / "segment_ai_simulation.parquet"
        # 不抛 = 测试 pass
        fp = save_segment_ai_simulation([], weight_method="rolling_icir_weight")
        # parquet **不**被创建 (空 rows 跳过)
        assert not fp.exists()


# ════════════════════════════════════════════════════════════════════
# Test 6: Round 6 字面约束 — 落 .env + 不硬编码 key
# ════════════════════════════════════════════════════════════════════


def test_load_api_key_raises_when_no_env_and_no_file(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """Round 6: 启动期没 env + 没 .env → RuntimeError fail-fast (必查).

    Simulates 'shell env unset AND summary/.env path returns empty':
    1) clear shell env via monkeypatch.delenv
    2) patch env_path.exists to False + read_text to return empty
    → _load_api_key() MUST raise RuntimeError with 'MINIMAX_CN_API_KEY not found'
    """
    from summary.report import llm_provider

    monkeypatch.delenv("MINIMAX_CN_API_KEY", raising=False)

    # 通过 monkeypatch 替换 env_path 行为: 制造"找不到任何 key"的场景
    fake_env_path = MagicMock()
    fake_env_path.exists.return_value = False
    fake_env_path.read_text.side_effect = FileNotFoundError("mocked: no .env")

    with patch("summary.report.llm_provider.Path") as MockPath:
        # summary/report/llm_provider.py:Path(...) / parent.parent / ".env"
        # 任何 Path 创建都返回 fake_env_path (只关心 exists=True 的分支)
        MockPath.return_value.parent.parent.__truediv__.return_value = fake_env_path
        with pytest.raises(RuntimeError, match="MINIMAX_CN_API_KEY"):
            llm_provider._load_api_key()
