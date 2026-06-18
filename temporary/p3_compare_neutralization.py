"""P3.4 衰减对比报告：raw vs industry-only vs industry+log_market_cap。

design.md §10.2 P3.4 — P3→P4 硬门禁。

用法:
    python temporary/p3_compare_neutralization.py

输出:
    temporary/p3_decay_comparison.txt  对比表
    temporary/p3_decay_comparison.json  机器可读

逻辑:
    1. 从 p1_baseline_ic.json 读 raw IC + industry-only neutral IC（P0/P1 基线）
    2. 对每个因子调 run_simple_factor_ic（默认 specs=["industry","log_market_cap"]）
    3. 从新 result JSON 读 ic_neutralized.ic_mean / decay_rate
    4. 输出三组对比表 + 增量衰减 > 10% 标红
"""

from __future__ import annotations

import json
import sys
import traceback
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
BASELINE_PATH = REPO_ROOT / "factor_ic" / "test_cases" / "snapshots" / "p1_baseline_ic.json"
RESULT_DIR = REPO_ROOT / "factor_ic" / "result"
OUTPUT_TXT = REPO_ROOT / "temporary" / "p3_decay_comparison.txt"
OUTPUT_JSON = REPO_ROOT / "temporary" / "p3_decay_comparison.json"


def load_baseline() -> dict:
    return json.loads(BASELINE_PATH.read_text())


def extract_factor_info() -> dict[str, str]:
    """从现有 result JSON 读 factor_name → factor_col 映射。"""
    info = {}
    for f in sorted(RESULT_DIR.glob("ic_*_1d_analysis_result.json")):
        data = json.loads(f.read_text())
        name = data.get("factor_name", "")
        col = data.get("factor_col", "")
        if name and col:
            info[name] = col
    return info


def run_combined_neutralization(factor_name_full: str, factor_col: str) -> dict | None:
    """跑联合中性化，返回 ic_neutralized payload。"""
    from factor_ic.common.factor_ic_runner import run_simple_factor_ic

    factor_name = factor_name_full.replace("_1d", "")
    result = run_simple_factor_ic(
        factor_name=factor_name,
        factor_col=factor_col,
        return_period="1d",
        force_full=True,
    )
    return result.get("ic_neutralized")


def main() -> None:
    baseline = load_baseline()
    factor_info = extract_factor_info()

    rows = []
    for factor_name_full in sorted(baseline.keys()):
        base = baseline[factor_name_full]
        raw_ic = base.get("raw", {}).get("ic_mean")
        neu_base = base.get("neutral", {})
        ind_enabled = neu_base.get("enabled", False)
        ind_ic = neu_base.get("ic_mean") if ind_enabled else None
        ind_decay = neu_base.get("decay_rate") if ind_enabled else None

        factor_col = factor_info.get(factor_name_full)
        if not factor_col:
            rows.append({
                "factor": factor_name_full,
                "raw_ic": raw_ic,
                "ind_ic": ind_ic,
                "ind_decay": ind_decay,
                "combined_ic": None,
                "combined_decay": None,
                "delta_decay": None,
                "status": "no_factor_col",
            })
            continue

        try:
            neu = run_combined_neutralization(factor_name_full, factor_col)
            if neu and neu.get("enabled"):
                combined_ic = neu.get("ic_mean")
                combined_decay = neu.get("decay_rate")
                controls = neu.get("controls_used", [])
                excluded = neu.get("excluded_specs", [])
            else:
                combined_ic = None
                combined_decay = None
                controls = neu.get("controls_used", []) if neu else []
                excluded = neu.get("excluded_specs", []) if neu else []

            delta = None
            if ind_decay is not None and combined_decay is not None:
                delta = round(combined_decay - ind_decay, 6)

            status = "ok"
            if excluded:
                status = f"excluded:{','.join(excluded)}"

            rows.append({
                "factor": factor_name_full,
                "raw_ic": raw_ic,
                "ind_ic": ind_ic,
                "ind_decay": ind_decay,
                "combined_ic": combined_ic,
                "combined_decay": combined_decay,
                "delta_decay": delta,
                "status": status,
                "controls": controls,
            })
        except Exception as e:
            rows.append({
                "factor": factor_name_full,
                "raw_ic": raw_ic,
                "ind_ic": ind_ic,
                "ind_decay": ind_decay,
                "combined_ic": None,
                "combined_decay": None,
                "delta_decay": None,
                "status": f"error:{e}",
            })

    # 输出 JSON
    OUTPUT_JSON.write_text(json.dumps(rows, indent=2, ensure_ascii=False))

    # 输出对比表
    lines = []
    lines.append("=" * 120)
    lines.append("P3 衰减对比报告：raw vs industry-only vs industry+log_market_cap")
    lines.append("=" * 120)
    lines.append("")
    lines.append(
        f"{'因子':<40} {'raw_IC':>10} {'ind_IC':>10} {'ind+cap_IC':>10} "
        f"{'ind_decay':>10} {'ind+cap_decay':>14} {'增量衰减':>10} {'状态':<15}"
    )
    lines.append("-" * 120)

    n_significant = 0
    for r in rows:
        raw_s = f"{r['raw_ic']:.6f}" if r["raw_ic"] is not None else "-"
        ind_s = f"{r['ind_ic']:.6f}" if r["ind_ic"] is not None else "-"
        comb_s = f"{r['combined_ic']:.6f}" if r["combined_ic"] is not None else "-"
        ind_d_s = f"{r['ind_decay']:.4f}" if r["ind_decay"] is not None else "-"
        comb_d_s = f"{r['combined_decay']:.4f}" if r["combined_decay"] is not None else "-"
        delta_s = f"{r['delta_decay']:.4f}" if r["delta_decay"] is not None else "-"

        # 增量衰减 > 10% 标红
        marker = ""
        if r["delta_decay"] is not None and r["delta_decay"] > 0.10:
            marker = " ⚠"
            n_significant += 1

        lines.append(
            f"{r['factor']:<40} {raw_s:>10} {ind_s:>10} {comb_s:>10} "
            f"{ind_d_s:>10} {comb_d_s:>14} {delta_s:>10}{marker:<5} {r['status']:<15}"
        )

    lines.append("-" * 120)
    lines.append(f"总因子数: {len(rows)}")
    lines.append(f"增量衰减 > 10% (市值中性化必要): {n_significant}")
    lines.append(f"增量衰减 ≤ 10% (市值中性化影响小): {len(rows) - n_significant}")
    lines.append("")

    # 按增量衰减降序列出 top 10
    sorted_rows = sorted(
        [r for r in rows if r["delta_decay"] is not None],
        key=lambda x: x["delta_decay"],
        reverse=True,
    )
    lines.append("Top 10 增量衰减（市值中性化影响最大的因子）:")
    for i, r in enumerate(sorted_rows[:10], 1):
        lines.append(
            f"  {i}. {r['factor']:<40} delta_decay={r['delta_decay']:.4f} "
            f"(ind={r['ind_decay']:.4f} → ind+cap={r['combined_decay']:.4f})"
        )

    lines.append("")
    lines.append("结论:")
    lines.append(f"  - {n_significant}/{len(rows)} 因子增量衰减 > 10%，说明市值中性化对这些因子有显著影响")
    lines.append(f"  - {len(rows) - n_significant}/{len(rows)} 因子增量衰减 ≤ 10%，市值中性化影响较小")
    lines.append("  - 增量衰减 > 10% 的因子原 IC 含显著市值溢价，联合中性化必要")

    OUTPUT_TXT.write_text("\n".join(lines))
    print("\n".join(lines[-20:]))
    print(f"\n报告已保存: {OUTPUT_TXT}")


if __name__ == "__main__":
    main()
