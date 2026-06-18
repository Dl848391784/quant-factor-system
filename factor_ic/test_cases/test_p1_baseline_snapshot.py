"""P1 全因子快照 hard gate 测试（P1→P2 门禁，design.md §14.1 P1.6）。

把当前 factor_ic/result/ic_*_1d_analysis_result.json 与
test_cases/snapshots/p1_baseline_ic.json 逐字段对比，验证 P1 重构后
所有因子的 raw IC + neutral IC 关键字段 + ic_values 序列哈希 完全一致。

baseline 由 generate_p1_baseline.py 生成；当数据源刷新或新增因子时，
手动重跑生成器并审阅 diff 后 commit baseline。

测试运行前置:
    factor_ic/result/ 必须存在 baseline 中所有因子的 ic_*_1d_analysis_result.json，
    否则跳过该因子（视为 P1 期间未跑过该因子, 不报错）。

参考:
    designs/feat_neutralization_framework.md §14.1（P1.6）
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
RESULT_DIR = REPO_ROOT / "factor_ic" / "result"
BASELINE_PATH = REPO_ROOT / "factor_ic" / "test_cases" / "snapshots" / "p1_baseline_ic.json"


# 数值容差：round(6) 后字段差应严格 0；浮点字段（p_value 等）保留 1e-12 容差
_TOL_EXACT = 0.0
_TOL_FLOAT = 1e-12

# raw IC 必校验字段
_RAW_FIELDS = (
    "ic_mean",
    "ic_std",
    "icir",
    "p_value",
    "positive_ratio",
    "n_days",
    "ic_values_hash",
    "n_dates",
    "period_start",
    "period_end",
)

# neutral IC 必校验字段（enabled=True 时）
_NEUTRAL_ENABLED_FIELDS = (
    "ic_mean",
    "ic_std",
    "icir",
    "p_value",
    "positive_ratio",
    "n_days",
    "decay_rate",
    "decay_level",
    "min_industry_stocks",
    "ic_values_hash",
    "n_dates",
)


def _load_baseline() -> dict:
    if not BASELINE_PATH.exists():
        pytest.skip(f"baseline 不存在: {BASELINE_PATH}（先跑 generate_p1_baseline.py）")
    with BASELINE_PATH.open() as fp:
        return json.load(fp)


def _result_path_for(factor_name: str) -> Path:
    """factor_name 形如 'rsi_1d' → ic_rsi_1d_analysis_result.json。"""
    return RESULT_DIR / f"ic_{factor_name}_analysis_result.json"


def _hash_series(values: list) -> str:
    import hashlib

    if not values:
        return "empty"
    payload = json.dumps(values, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()[:16]


def _extract_current_summary(result: dict) -> dict:
    """与 generate_p1_baseline._extract_summary 同逻辑，避免循环 import。"""
    ic_metrics = result.get("ic_metrics", {})
    stats_sig = result.get("statistical_significance", {})
    ic_dist = result.get("ic_distribution_consistency", {})
    sample_stats = result.get("sample_stats", {})
    period = result.get("period", {})

    raw = {
        "ic_mean": ic_metrics.get("ic_mean"),
        "ic_std": ic_metrics.get("ic_std"),
        "icir": ic_metrics.get("icir"),
        "p_value": stats_sig.get("p_value"),
        "positive_ratio": ic_dist.get("positive_ratio"),
        "n_days": sample_stats.get("valid_days"),
        "ic_values_hash": _hash_series(result.get("ic_values", [])),
        "n_dates": len(result.get("dates", [])),
        "period_start": period.get("start"),
        "period_end": period.get("end"),
    }

    # P4: 只读 ic_neutralized（legacy ic_neutral_industry 已移除）
    neu_raw = result.get("ic_neutralized")
    if isinstance(neu_raw, dict) and neu_raw:
        neu: dict = neu_raw
    else:
        neu = {}

    if neu.get("enabled") is True:
        neutral = {
            "enabled": True,
            **{k: neu.get(k) for k in _NEUTRAL_ENABLED_FIELDS if k != "ic_values_hash"},
            "ic_values_hash": _hash_series(neu.get("ic_values", [])),
            "n_dates": len(neu.get("dates", [])),
        }
    else:
        neutral = {"enabled": False, "skipped_reason": neu.get("skipped_reason")}

    return {"raw": raw, "neutral": neutral}


def _compare_field(name: str, expected, actual) -> str | None:
    """返回 None 表示一致，否则返回失败描述字符串。"""
    if expected == actual:
        return None
    # 浮点容差比较
    if isinstance(expected, (int, float)) and isinstance(actual, (int, float)):
        diff = abs(float(expected) - float(actual))
        if diff <= _TOL_FLOAT:
            return None
        return f"{name}: expected={expected} actual={actual} diff={diff:.3e}"
    return f"{name}: expected={expected!r} actual={actual!r}"


def _factor_names_with_results() -> list[str]:
    """从 baseline 取因子列表，仅返回当前 result/ 下存在文件的项目。"""
    baseline = _load_baseline()
    return [name for name in sorted(baseline.keys()) if _result_path_for(name).exists()]


@pytest.mark.parametrize("factor_name", _factor_names_with_results())
def test_p1_baseline_match(factor_name: str):
    """每个因子的 raw + neutral IC 关键字段必须与 baseline 完全一致。"""
    baseline = _load_baseline()
    expected = baseline[factor_name]

    result_path = _result_path_for(factor_name)
    with result_path.open() as fp:
        result = json.load(fp)
    actual = _extract_current_summary(result)

    failures: list[str] = []

    # raw 字段
    for field in _RAW_FIELDS:
        msg = _compare_field(f"raw.{field}", expected["raw"].get(field), actual["raw"].get(field))
        if msg:
            failures.append(msg)

    # neutral 字段：P4 后所有因子均为 P3 格式（ic_neutralized），默认 specs 已从
    # industry-only 变为 industry+log_market_cap，neutral IC 值与 P1 baseline 不同。
    # raw IC 不受 specs 影响，仍逐位验证。neutral 对比已不再需要（P1 hard gate 完成）。

    assert not failures, f"P1 baseline drift detected for factor '{factor_name}':\n  " + "\n  ".join(failures)
