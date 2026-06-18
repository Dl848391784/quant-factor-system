"""ic_result_builder._normalize_neutralized_payload + build_ic_result 中性化 schema 单测。

覆盖 design.md §10.2 P3 schema 校验：

  R17c: build_ic_result 接入
        - payload=None → 顶层不出现 ic_neutralized
        - payload=enabled=False → 顶层 ic_neutralized 仅含 4 字段
        - payload=enabled=True → 顶层 ic_neutralized 含全字段且顺序固定

  P3.2: ic_neutralized 字段
        - normalize 字段顺序 + controls_used 校验
        - build_ic_result 写入 ic_neutralized（不写 legacy 字段）

设计文档: designs/feat_neutralization_framework.md §10.2 P3.2
"""

from __future__ import annotations

import pandas as pd
import pytest

from factor_ic.common.ic_result_builder import (
    NEUTRALIZED_REQUIRED_KEYS_DISABLED,
    NEUTRALIZED_REQUIRED_KEYS_ENABLED,
    RESULT_KEY_IC_NEUTRALIZED,
    _normalize_neutralized_payload,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_full_neutralized_payload(controls_used: list[str] | None = None) -> dict:
    """构造完整 enabled=True neutralized payload（占位值，仅供 schema 校验）。"""
    return {
        "enabled": True,
        "controls_used": controls_used or ["industry", "log_market_cap"],
        "excluded_specs": [],
        "control_meta": {
            "industry": {"min_count": 5},
            "log_market_cap": {"winsorize_quantiles": [0.01, 0.99]},
        },
        "ic_mean": 0.02,
        "ic_std": 0.005,
        "icir": 4.0,
        "p_value": 0.05,
        "p_value_display": "0.05",
        "positive_ratio": 0.6,
        "n_days": 100,
        "dates": ["2026-01-01", "2026-01-02"],
        "ic_values": [0.02, 0.02],
        "decay_rate": 0.5,
        "decay_level": "high",
    }


def _make_minimal_ic_result_and_meta() -> tuple[dict, dict]:
    """构造满足 build_ic_result 必填的最小 ic_result + raw_metadata。"""
    ic_series = pd.Series([0.05, 0.03], index=["2026-01-01", "2026-01-02"])
    ic_result = {
        "ic_series": ic_series,
        "ic_mean": 0.04,
        "ic_std": 0.01,
        "icir": 4.0,
        "p_value": 0.001,
        "p_value_display": "< 0.01",
        "positive_ratio": 1.0,
        "n_days": 2,
        "statistical_significance": {
            "p_value": 0.001,
            "p_value_display": "< 0.01",
            "t_stat": 4.0,
            "is_significant": True,
            "conclusion": "Y",
        },
        "factor_direction": {"ic_mean": 0.04, "ic_mean_sign": "positive", "conclusion": "Y"},
        "economic_significance": {"is_economically_significant": True, "conclusion": "Y"},
        "icir_stability": {"is_stable": True, "conclusion": "Y"},
        "ic_distribution_consistency": {"conclusion": "Y"},
    }
    raw_metadata = {
        "period_start": "2026-01-01",
        "period_end": "2026-01-02",
        "total_days": 2,
        "avg_stocks_per_day": 100,
    }
    return ic_result, raw_metadata


# ---------------------------------------------------------------------------
# P3.2: _normalize_neutralized_payload
# ---------------------------------------------------------------------------


def test_p32_normalize_neutralized_enabled_complete_field_order():
    """enabled=True 完整字段 → 按 NEUTRALIZED_REQUIRED_KEYS_ENABLED 顺序输出。"""
    payload = _make_full_neutralized_payload()
    out = _normalize_neutralized_payload(payload)
    assert list(out.keys()) == list(NEUTRALIZED_REQUIRED_KEYS_ENABLED)
    assert out["controls_used"] == ["industry", "log_market_cap"]
    assert out["control_meta"]["industry"]["min_count"] == 5


def test_p32_normalize_neutralized_enabled_missing_controls_used_raises():
    """enabled=True 缺 controls_used → ValueError 含字段名。"""
    payload = _make_full_neutralized_payload()
    del payload["controls_used"]
    with pytest.raises(ValueError, match="controls_used"):
        _normalize_neutralized_payload(payload)


def test_p32_normalize_neutralized_disabled_complete():
    """enabled=False + skipped_reason → 标准化输出 4 必填字段。"""
    payload = {
        "enabled": False,
        "skipped_reason": "factor_in_excluded_list",
        "controls_used": [],
        "excluded_specs": ["industry"],
    }
    out = _normalize_neutralized_payload(payload)
    assert list(out.keys()) == list(NEUTRALIZED_REQUIRED_KEYS_DISABLED)
    assert out["enabled"] is False
    assert out["skipped_reason"] == "factor_in_excluded_list"


def test_p32_normalize_neutralized_disabled_missing_excluded_specs_raises():
    """enabled=False 缺 excluded_specs → ValueError。"""
    payload = {"enabled": False, "skipped_reason": "test", "controls_used": []}
    with pytest.raises(ValueError, match="excluded_specs"):
        _normalize_neutralized_payload(payload)


# ---------------------------------------------------------------------------
# R17c: build_ic_result 顶层接入
# ---------------------------------------------------------------------------


def test_r17c_build_ic_result_payload_none_no_neutral_field():
    """ic_neutralized_payload=None → 顶层结果不出现 ic_neutralized 字段。"""
    from factor_ic.common.ic_result_builder import build_ic_result

    ic_result, raw_meta = _make_minimal_ic_result_and_meta()
    result = build_ic_result(ic_result, raw_meta, factor_name="test_1d")
    assert RESULT_KEY_IC_NEUTRALIZED not in result


def test_r17c_build_ic_result_payload_disabled():
    """ic_neutralized_payload={enabled=False} → 顶层 ic_neutralized 仅 4 字段。"""
    from factor_ic.common.ic_result_builder import build_ic_result

    ic_result, raw_meta = _make_minimal_ic_result_and_meta()
    payload = {
        "enabled": False,
        "skipped_reason": "user disabled",
        "controls_used": [],
        "excluded_specs": [],
    }
    result = build_ic_result(
        ic_result, raw_meta, factor_name="test_1d", ic_neutralized_payload=payload
    )
    assert RESULT_KEY_IC_NEUTRALIZED in result
    neutral = result[RESULT_KEY_IC_NEUTRALIZED]
    assert list(neutral.keys()) == list(NEUTRALIZED_REQUIRED_KEYS_DISABLED)
    assert neutral["enabled"] is False
    assert neutral["skipped_reason"] == "user disabled"


def test_r17c_build_ic_result_payload_enabled_field_order():
    """ic_neutralized_payload={enabled=True 全字段} → 顶层字段按 schema 顺序输出。"""
    from factor_ic.common.ic_result_builder import build_ic_result

    ic_result, raw_meta = _make_minimal_ic_result_and_meta()
    payload = _make_full_neutralized_payload()
    result = build_ic_result(
        ic_result, raw_meta, factor_name="test_1d", ic_neutralized_payload=payload
    )
    neutral = result[RESULT_KEY_IC_NEUTRALIZED]
    assert list(neutral.keys()) == list(NEUTRALIZED_REQUIRED_KEYS_ENABLED)
    assert neutral["decay_level"] == "high"
    assert neutral["controls_used"] == ["industry", "log_market_cap"]


def test_r17c_build_ic_result_payload_invalid_raises():
    """ic_neutralized_payload 不合规 → ValueError 透传到调用方（runner）。"""
    from factor_ic.common.ic_result_builder import build_ic_result

    ic_result, raw_meta = _make_minimal_ic_result_and_meta()
    with pytest.raises(ValueError, match="controls_used"):
        build_ic_result(
            ic_result,
            raw_meta,
            factor_name="test_1d",
            ic_neutralized_payload={"enabled": True},  # 缺必填字段
        )


def test_p32_build_ic_result_writes_ic_neutralized_only():
    """build_ic_result 写 ic_neutralized，不写任何 legacy 字段。"""
    from factor_ic.common.ic_result_builder import build_ic_result

    ic_result, raw_meta = _make_minimal_ic_result_and_meta()
    result = build_ic_result(
        ic_result,
        raw_meta,
        factor_name="test_1d",
        ic_neutralized_payload=_make_full_neutralized_payload(["industry", "log_market_cap"]),
    )
    assert RESULT_KEY_IC_NEUTRALIZED in result
    assert "ic_neutral_industry" not in result
    assert result[RESULT_KEY_IC_NEUTRALIZED]["controls_used"] == ["industry", "log_market_cap"]
