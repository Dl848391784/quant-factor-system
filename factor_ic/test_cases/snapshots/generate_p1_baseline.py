"""生成 P1 全因子 IC 结果快照 baseline (P1.6 hard gate)。

用法:
    python factor_ic/test_cases/snapshots/generate_p1_baseline.py

输入: factor_ic/result/ic_*_1d_analysis_result.json
输出: factor_ic/test_cases/snapshots/p1_baseline_ic.json

每因子记录:
    raw IC: ic_mean / ic_std / icir / p_value / positive_ratio / n_days
    neutral IC: enabled + (ic_mean / ic_std / icir / p_value / positive_ratio / n_days /
                           decay_rate / decay_level) 或 skipped_reason
    ic_values 序列哈希（sha256 前 16 字符，验证序列稳定）
    dates 数量

不记录完整 ic_values 序列：避免 baseline 文件膨胀；序列变化通过 hash 检测。
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
RESULT_DIR = REPO_ROOT / "factor_ic" / "result"
OUTPUT_PATH = REPO_ROOT / "factor_ic" / "test_cases" / "snapshots" / "p1_baseline_ic.json"


def _hash_series(values: list) -> str:
    """对 ic_values 序列做 sha256，取前 16 字符作 stable hash。"""
    if not values:
        return "empty"
    payload = json.dumps(values, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()[:16]


def _extract_summary(result: dict) -> dict:
    """从单个 IC 结果文件提取关键摘要字段。"""
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

    neu = result.get("ic_neutralized") or {}
    if neu.get("enabled") is True:
        neutral = {
            "enabled": True,
            "ic_mean": neu.get("ic_mean"),
            "ic_std": neu.get("ic_std"),
            "icir": neu.get("icir"),
            "p_value": neu.get("p_value"),
            "positive_ratio": neu.get("positive_ratio"),
            "n_days": neu.get("n_days"),
            "decay_rate": neu.get("decay_rate"),
            "decay_level": neu.get("decay_level"),
            "min_industry_stocks": neu.get("min_industry_stocks"),
            "ic_values_hash": _hash_series(neu.get("ic_values", [])),
            "n_dates": len(neu.get("dates", [])),
        }
    else:
        neutral = {
            "enabled": False,
            "skipped_reason": neu.get("skipped_reason"),
        }

    return {"raw": raw, "neutral": neutral}


def main() -> int:
    if not RESULT_DIR.exists():
        print(f"ERROR: {RESULT_DIR} 不存在", file=sys.stderr)
        return 1

    files = sorted(RESULT_DIR.glob("ic_*_1d_analysis_result.json"))
    if not files:
        print(f"ERROR: {RESULT_DIR} 下无 ic_*_1d_analysis_result.json", file=sys.stderr)
        return 1

    snapshot: dict = {}
    for f in files:
        with f.open() as fp:
            result = json.load(fp)
        factor_name = result.get("factor_name") or f.stem.removeprefix("ic_").removesuffix("_analysis_result")
        snapshot[factor_name] = _extract_summary(result)

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT_PATH.open("w") as fp:
        json.dump(snapshot, fp, indent=2, ensure_ascii=False, sort_keys=True)

    enabled_count = sum(1 for v in snapshot.values() if v["neutral"].get("enabled") is True)
    skipped_count = len(snapshot) - enabled_count
    print(f"✓ 已生成 baseline: {OUTPUT_PATH}")
    print(f"  共 {len(snapshot)} 个因子 (neutralize enabled={enabled_count} skipped={skipped_count})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
