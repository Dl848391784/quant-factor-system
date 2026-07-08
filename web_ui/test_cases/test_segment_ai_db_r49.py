"""v0.4.8 R49 单元测试 (web_ui 渲染层) — 30 段 AI 客观分析师角色决策.

跟 v0.4.8 R38 (segment_win_db) / R44 (asset_value_db) 同样模式:
  - 真实 parquet 验证 (允许 skip if parquet 缺失)
  - mock upstream 验证 (R46/round-trip 风格)

测试场景:
  1. 真实 parquet (R49a-1 已写入): 加载 → 30 段 × N 选股日 → fallback warning 检查
  2. parquet 缺失: 返回 None (跟 asset_value_db / segment_win_db 一致)
  3. 数据为空 (有列没行): source='missing', fallback_warning 含 [⚠️ R49 AI 决策数据]
  4. row schema: decision/confidence/reasoning 字段都对齐 SEGMENT_AI_COLUMNS

实战锚点: H1.1 严守 + §18 fork pattern — web_ui 内部读 parquet, 不直接 import summary 模块.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

import pandas as pd
import pytest


# PROJECT_ROOT 加入 sys.path 让 from web_ui.common 可导入
PROJECT_ROOT = Path(__file__).parent.parent.parent.resolve()
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from web_ui.common.segment_ai_db import _PARQUET_PATH, load_segment_ai_decisions  # noqa: E402


@pytest.mark.skipif(
    not _PARQUET_PATH.exists(),
    reason="R49a-1 未跑过 (summary/result/.../segment_ai_simulation.parquet 不存在), 跳过实测",
)
def test_load_segment_ai_decisions_runs_on_real_parquet():
    """R49 主路径 (跟 R44 同模式): 真实 parquet 上能跑通.

    不依赖 LLM mock: R49a-2 main() 跑过一次才能 parquet 存在; 跳过条件已管.
    """
    logger = logging.getLogger(__name__)
    result = load_segment_ai_decisions(
        pipeline="ob_quality",
        weight_method="rolling_icir_weight",
        logger=logger,
    )
    assert result is not None, "真实 parquet 已存在, 不应返回 None"
    # 数据契约 4 个字段 (跟 R38 / R44 一致)
    assert set(result.keys()) >= {"dates", "segments", "source", "fallback_warning"}
    # 30 段 × N 日
    assert len(result["segments"]) == 30, f"应 30 段, 实际 {len(result['segments'])}"
    # 每段必含字段
    for seg in result["segments"]:
        assert "label" in seg
        assert "decisions" in seg
        assert "latest_decision" in seg
        assert "latest_confidence" in seg
        assert "latest_reasoning" in seg
        # decision 必 operate/skip
        for d in seg["decisions"]:
            assert d in ("operate", "skip"), f"未知决策 {d}"


def test_load_segment_ai_decisions_returns_none_when_parquet_missing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """R49 silent fallback (跟 R47 silent fallback 实战同源): parquet 不存在 → None.

    用 monkeypatch setattr 替换 _PARQUET_PATH (避免影响 module-level 常量).
    """
    from web_ui.common import segment_ai_db

    fake_nonexistent = tmp_path / "definitely_does_not_exist.parquet"
    monkeypatch.setattr(segment_ai_db, "_PARQUET_PATH", fake_nonexistent)

    result = load_segment_ai_decisions(logger=logging.getLogger(__name__))
    assert result is None


def test_load_segment_ai_decisions_source_missing_when_pipeline_filtered_out(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """R49 graceful degrade: parquet 存在但 pipeline/weight_method 不匹配 → source='missing'.

    跟 R47 实战 §10 silent fallback 同源模式: data 存在但**过滤后无匹配**, 加 [⚠️] 标记
    让用户**知道**数据缺失原因, **不**静默假装.
    """
    from web_ui.common import segment_ai_db

    # 1. 构造 1 个有效 parquet (含 dummy pipeline 'wrong_pipeline')
    fp = tmp_path / "segment_ai.parquet"
    df = pd.DataFrame(
        {
            "pipeline": ["wrong_pipeline"] * 3,
            "selection_date": ["2026-07-06", "2026-07-07", "2026-07-08"],
            "trade_date": ["2026-07-07", "2026-07-08", "2026-07-09"],
            "weight_method": ["rolling_icir_weight"] * 3,
            "segment_label": ["S1", "S2", "S3"],
            "decision": ["operate", "skip", "operate"],
            "confidence": [0.5, 0.5, 0.5],
            "reasoning_text": ["x", "y", "z"],
            "data_observations_json": ["[]", "[]", "[]"],
            "history_window": [5, 5, 5],
            "past_decisions_json": [None, None, None],
            "reflection_text": [None, None, None],
            "reflection_k_days": [5, 5, 5],
            "model_name": ["MiniMax-M3"] * 3,
            "provider_endpoint": ["https://api.minimaxi.com/anthropic/v1/messages"] * 3,
            "created_at": ["2026-07-06"] * 3,
        }
    )
    df.to_parquet(fp)

    monkeypatch.setattr(segment_ai_db, "_PARQUET_PATH", fp)

    result = load_segment_ai_decisions(
        pipeline="ob_quality",  # 跟 parquet 'wrong_pipeline' 不匹配 → 空 df
        logger=logging.getLogger(__name__),
    )

    assert result is not None
    assert result["source"] == "missing"
    assert result["fallback_warning"] is not None
    assert "[⚠️" in result["fallback_warning"]
    assert "R49" in result["fallback_warning"]
