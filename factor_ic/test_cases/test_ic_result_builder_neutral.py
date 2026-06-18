"""ic_result_builder._normalize_neutral_payload + build_ic_result 行业中性化 schema 单测。

覆盖 design.md §5.2 schema 校验：

  R17a: enabled=False 路径
        - 完整 (enabled, skipped_reason) → 标准化输出 2 字段
        - 缺 skipped_reason → ValueError
        - skipped_reason 为字符串原样保留
  R17b: enabled=True 路径
        - 完整 13 字段 → 字段顺序固定
        - 缺任意必填字段 → ValueError 含字段名
        - 多余字段（如 skipped_reason=None）被丢弃
  R17c: build_ic_result 接入
        - payload=None → 顶层不出现 ic_neutral_industry
        - payload=enabled=False → 顶层 ic_neutral_industry 仅含 2 字段
        - payload=enabled=True → 顶层 ic_neutral_industry 含 13 字段且顺序固定

设计文档: .hermes/plans/factor-ic-industry-neutralization-design.md §5.2
"""

from __future__ import annotations

import pandas as pd
import pytest

from factor_ic.common.ic_result_builder import (
    NEUTRAL_REQUIRED_KEYS_DISABLED,
    NEUTRAL_REQUIRED_KEYS_ENABLED,
    RESULT_KEY_IC_NEUTRAL,
    _normalize_neutral_payload,
)


# ---------------------------------------------------------------------------
# R17a: enabled=False 路径
# ---------------------------------------------------------------------------


def test_r17a_normalize_disabled_complete():
    """enabled=False + skipped_reason 完整 → 标准化输出 2 字段，原样保留 reason。"""
    payload = {"enabled": False, "skipped_reason": "user disabled"}
    out = _normalize_neutral_payload(payload)
    assert list(out.keys()) == list(NEUTRAL_REQUIRED_KEYS_DISABLED)
    assert out["enabled"] is False
    assert out["skipped_reason"] == "user disabled"


def test_r17a_normalize_disabled_missing_reason():
    """enabled=False 缺 skipped_reason → ValueError 含字段名。"""
    with pytest.raises(ValueError, match="skipped_reason"):
        _normalize_neutral_payload({"enabled": False})


def test_r17a_normalize_disabled_extra_fields_dropped():
    """enabled=False + 残留 ic_mean 等字段 → 标准化只保留 2 必填。

    防止 runner 侧 .update(neutral_payload) 后 enabled=False 路径残留旧字段。
    """
    payload = {"enabled": False, "skipped_reason": "test", "ic_mean": 0.99, "extra": "noise"}
    out = _normalize_neutral_payload(payload)
    assert list(out.keys()) == ["enabled", "skipped_reason"]
    assert "ic_mean" not in out
    assert "extra" not in out


# ---------------------------------------------------------------------------
# R17b: enabled=True 路径
# ---------------------------------------------------------------------------


def _make_full_enabled_payload() -> dict:
    """构造完整 13 字段 enabled=True payload（占位值，仅供 schema 校验）。"""
    return {
        "enabled": True,
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
        "min_industry_stocks": 5,
    }


def test_r17b_normalize_enabled_complete_field_order():
    """enabled=True 完整 13 字段 → 字段按 NEUTRAL_REQUIRED_KEYS_ENABLED 顺序输出。"""
    payload = _make_full_enabled_payload()
    out = _normalize_neutral_payload(payload)
    assert list(out.keys()) == list(NEUTRAL_REQUIRED_KEYS_ENABLED)
    # 数值原样保留
    assert out["ic_mean"] == 0.02
    assert out["decay_level"] == "high"


@pytest.mark.parametrize("missing_field", [
    "ic_mean", "ic_std", "icir", "p_value", "p_value_display",
    "positive_ratio", "n_days", "dates", "ic_values",
    "decay_rate", "decay_level", "min_industry_stocks",
])
def test_r17b_normalize_enabled_missing_required_field_raises(missing_field):
    """enabled=True 缺任意必填字段 → ValueError 错误消息含该字段名。"""
    payload = _make_full_enabled_payload()
    del payload[missing_field]
    with pytest.raises(ValueError, match=missing_field):
        _normalize_neutral_payload(payload)


def test_r17b_normalize_enabled_drops_skipped_reason_residual():
    """enabled=True 残留 skipped_reason=None（runner .update 后） → 标准化丢弃。

    runner 侧先建 {enabled, skipped_reason: None}, 再 .update(payload)；
    enabled=True 时 skipped_reason 残留为 None,标准化必须丢弃。
    """
    payload = _make_full_enabled_payload()
    payload["skipped_reason"] = None  # runner 残留
    payload["another_extra"] = "noise"
    out = _normalize_neutral_payload(payload)
    assert "skipped_reason" not in out
    assert "another_extra" not in out
    assert list(out.keys()) == list(NEUTRAL_REQUIRED_KEYS_ENABLED)


# ---------------------------------------------------------------------------
# R17c: build_ic_result 顶层接入
# ---------------------------------------------------------------------------


def _make_minimal_ic_result_and_meta():
    """构造满足 build_ic_result 必填的最小 ic_result + raw_metadata。"""
    ic_series = pd.Series([0.05, 0.03], index=["2026-01-01", "2026-01-02"])
    ic_result = {
        "ic_series": ic_series, "ic_mean": 0.04, "ic_std": 0.01, "icir": 4.0,
        "p_value": 0.001, "p_value_display": "< 0.01", "positive_ratio": 1.0, "n_days": 2,
        "statistical_significance": {
            "p_value": 0.001, "p_value_display": "< 0.01", "t_stat": 4.0,
            "is_significant": True, "conclusion": "Y",
        },
        "factor_direction": {"ic_mean": 0.04, "ic_mean_sign": "positive", "conclusion": "Y"},
        "economic_significance": {"is_economically_significant": True, "conclusion": "Y"},
        "icir_stability": {"is_stable": True, "conclusion": "Y"},
        "ic_distribution_consistency": {"conclusion": "Y"},
    }
    raw_metadata = {
        "period_start": "2026-01-01", "period_end": "2026-01-02",
        "total_days": 2, "avg_stocks_per_day": 100,
    }
    return ic_result, raw_metadata


def test_r17c_build_ic_result_payload_none_no_neutral_field():
    """ic_neutral_payload=None → 顶层结果不出现 ic_neutral_industry 字段（向后兼容）。"""
    from factor_ic.common.ic_result_builder import build_ic_result

    ic_result, raw_meta = _make_minimal_ic_result_and_meta()
    result = build_ic_result(ic_result, raw_meta, factor_name="test_1d")
    assert RESULT_KEY_IC_NEUTRAL not in result


def test_r17c_build_ic_result_payload_disabled():
    """ic_neutral_payload={enabled=False} → 顶层 ic_neutral_industry 仅 2 字段。"""
    from factor_ic.common.ic_result_builder import build_ic_result

    ic_result, raw_meta = _make_minimal_ic_result_and_meta()
    payload = {"enabled": False, "skipped_reason": "user disabled"}
    result = build_ic_result(ic_result, raw_meta, factor_name="test_1d", ic_neutral_payload=payload)
    assert RESULT_KEY_IC_NEUTRAL in result
    neutral = result[RESULT_KEY_IC_NEUTRAL]
    assert list(neutral.keys()) == list(NEUTRAL_REQUIRED_KEYS_DISABLED)
    assert neutral["enabled"] is False
    assert neutral["skipped_reason"] == "user disabled"


def test_r17c_build_ic_result_payload_enabled_field_order():
    """ic_neutral_payload={enabled=True 13 字段} → 顶层字段按 schema 顺序输出。"""
    from factor_ic.common.ic_result_builder import build_ic_result

    ic_result, raw_meta = _make_minimal_ic_result_and_meta()
    payload = _make_full_enabled_payload()
    result = build_ic_result(ic_result, raw_meta, factor_name="test_1d", ic_neutral_payload=payload)
    neutral = result[RESULT_KEY_IC_NEUTRAL]
    assert list(neutral.keys()) == list(NEUTRAL_REQUIRED_KEYS_ENABLED)
    assert neutral["decay_level"] == "high"


def test_r17c_build_ic_result_payload_invalid_raises():
    """ic_neutral_payload 不合规 → ValueError 透传到调用方（runner）。"""
    from factor_ic.common.ic_result_builder import build_ic_result

    ic_result, raw_meta = _make_minimal_ic_result_and_meta()
    with pytest.raises(ValueError, match="ic_mean"):
        build_ic_result(
            ic_result, raw_meta, factor_name="test_1d",
            ic_neutral_payload={"enabled": True},  # 缺 12 字段
        )
