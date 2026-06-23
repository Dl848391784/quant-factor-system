"""
交互因子 INTERACTION_THRESHOLDS 阈值校准调研脚本.

目的: 对当前所有交互因子的 L1 年化、L1 夏普、IC、ICIR、多头年化做分布统计,
      输出数据驱动的推荐阈值 (P5 / mean - 2σ), 供人工 review.

设计原则 (PROJECT.md "数据驱动" + "禁止调参式修复"):
  - 只输出推荐, 不自动改 comprehensive_factor/common/factor_selector.py 的常量
  - 阈值改动必须走 design.md + commit, 引用本脚本输出
  - 触发条件: 新增 >=2 个交互因子 / 季度健康检查 / 边界案例

用法:
    python scripts/calibrate_interaction_thresholds.py
    python scripts/calibrate_interaction_thresholds.py --period 1d  (默认)
    python scripts/calibrate_interaction_thresholds.py --output result.json
"""

from __future__ import annotations

import argparse
import json
import logging
import statistics
import sys
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# 直接复用 INTERACTION_THRESHOLDS 常量, 避免硬编码漂移
from comprehensive_factor.common.factor_selector import (  # noqa: E402
    INTERACTION_THRESHOLDS,
)


logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)-8s | %(message)s")
logger = logging.getLogger("calibrate_interaction_thresholds")


# ============================================================================
# 数据加载
# ============================================================================


def load_ic_records(period: str = "1d") -> dict[str, dict[str, Any]]:
    """加载所有 factor_ic/result/ic_<factor>_<period>_analysis_result.json.

    Returns:
        {factor_name: {ic_mean, icir, p_value, n_days}}

    Note: long_return_annual / monotonicity_corr 在 backtest 文件中, 不在 IC 文件.
    """
    ic_dir = PROJECT_ROOT / "factor_ic" / "result"
    suffix = f"_{period}_analysis_result.json"
    records: dict[str, dict[str, Any]] = {}
    for f in sorted(ic_dir.glob(f"ic_*{suffix}")):
        name = f.name.removeprefix("ic_").removesuffix(suffix)
        try:
            d = json.loads(f.read_text())
            records[name] = {
                "ic_mean": d.get("ic_metrics", {}).get("ic_mean"),
                "icir": d.get("ic_metrics", {}).get("icir"),
                "p_value": d.get("statistical_significance", {}).get("p_value"),
                "n_days": d.get("sample_stats", {}).get("valid_days"),
            }
        except (json.JSONDecodeError, KeyError) as e:
            logger.warning("跳过 %s: %s", f.name, e)
    return records


def load_layer_stats(period: str = "1d") -> dict[str, dict[str, float]]:
    """加载所有 backtest/result/<factor>_layered_backtest.json 的 L1 / 多头 / 单调性统计.

    Returns:
        {factor_name: {layer_1_annual, layer_1_sharpe, long_return_annual, monotonicity_corr}}
    """
    bt_dir = PROJECT_ROOT / "backtest" / "result"
    records: dict[str, dict[str, float]] = {}
    for f in sorted(bt_dir.glob("*_layered_backtest.json")):
        name = f.name.removesuffix("_layered_backtest.json")
        try:
            d = json.loads(f.read_text())
            cfg = d.get("config", {})
            if cfg.get("return_period") and cfg["return_period"] != period:
                continue
            l1 = d.get("layer_stats", {}).get("layer_1", {})
            ls = d.get("long_short", {})
            mono = d.get("monotonicity", {})
            records[name] = {
                "layer_1_annual": l1.get("annual_return"),
                "layer_1_sharpe": l1.get("sharpe_ratio"),
                "long_return_annual": ls.get("long_return_annual"),
                "monotonicity_corr": mono.get("correlation"),
            }
        except (json.JSONDecodeError, KeyError) as e:
            logger.warning("跳过 %s: %s", f.name, e)
    return records


# ============================================================================
# 闸门判定
# ============================================================================


def passes_ic_gates(
    ic_rec: dict[str, Any],
    bt_rec: dict[str, Any] | None,
    thresholds: dict[str, float],
) -> tuple[bool, list[str]]:
    """检查除 L1 外的所有闸门 (IC + 多头年化 + 单调性).

    L1 闸门单独评估 → 不在这里检查.
    """
    reasons: list[str] = []
    ic = ic_rec.get("ic_mean")
    icir = ic_rec.get("icir")
    p = ic_rec.get("p_value")
    long_ret = (bt_rec or {}).get("long_return_annual")
    mono = (bt_rec or {}).get("monotonicity_corr")

    if ic is None or abs(ic) < thresholds["ic_mean_abs_min"]:
        reasons.append(f"|IC|<{thresholds['ic_mean_abs_min']}")
    if icir is None or abs(icir) < thresholds["icir_abs_min"]:
        reasons.append(f"|ICIR|<{thresholds['icir_abs_min']}")
    if p is None or p > thresholds["p_value_max"]:
        reasons.append(f"p>{thresholds['p_value_max']}")
    if long_ret is None or long_ret < thresholds["long_return_min"]:
        reasons.append(f"long_return<{thresholds['long_return_min']}")
    if mono is None or abs(mono) < thresholds["monotonicity_corr_abs_min"]:
        reasons.append(f"|monotonicity|<{thresholds['monotonicity_corr_abs_min']}")
    return (not reasons), reasons


# ============================================================================
# 分布统计 → 推荐阈值
# ============================================================================


def recommend_threshold(values: list[float], policy: str = "p5") -> float | None:
    """从分布给出推荐阈值.

    policy:
        'p5': 5% 分位 (保守, 排除最差 5%)
        'mean_2sigma': mean - 2σ (95.4% 置信下边界)
        'p10': 10% 分位 (中等)
    """
    if not values:
        return None
    n = len(values)
    if policy == "p5":
        # statistics.quantiles 返回 4 个分位点 (Q1, Q2, Q3) 或 n-1 个 n-quantiles
        # P5 = quantiles(n=20)[0]
        if n < 5:
            return min(values)
        return statistics.quantiles(values, n=20)[0]
    if policy == "p10":
        if n < 4:
            return min(values)
        return statistics.quantiles(values, n=10)[0]
    if policy == "mean_2sigma":
        if n < 2:
            return min(values)
        mu = statistics.mean(values)
        sigma = statistics.stdev(values)
        return mu - 2 * sigma
    raise ValueError(f"未知 policy: {policy}")


# ============================================================================
# 主流程
# ============================================================================


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--period", default="1d", help="持仓周期 (默认 1d)")
    parser.add_argument("--output", type=Path, help="输出 JSON 路径 (可选)")
    parser.add_argument(
        "--family-prefix",
        default="interaction_",
        help="因子族前缀 (默认 interaction_)",
    )
    args = parser.parse_args()

    logger.info("=" * 80)
    logger.info("INTERACTION_THRESHOLDS 阈值校准调研 (period=%s)", args.period)
    logger.info("=" * 80)

    # Step 1: 加载数据
    ic_records = load_ic_records(args.period)
    bt_records = load_layer_stats(args.period)
    logger.info("加载: IC 因子 %d, backtest 因子 %d", len(ic_records), len(bt_records))

    # Step 2: 筛选交互因子族
    family_factors = [n for n in ic_records if n.startswith(args.family_prefix)]
    logger.info("交互因子族 '%s*' 总数: %d", args.family_prefix, len(family_factors))

    # Step 3: 分类统计 — 哪些过了 IC 闸门, 待 L1 判定
    thresholds = INTERACTION_THRESHOLDS
    candidates: list[dict[str, Any]] = []  # 过 IC 闸门, 有 backtest 数据
    failed_ic: list[dict[str, Any]] = []  # 未过 IC 闸门
    missing_bt: list[str] = []  # 缺 backtest 数据

    for name in family_factors:
        ic_rec = ic_records[name]
        bt_rec = bt_records.get(name)
        ok, reasons = passes_ic_gates(ic_rec, bt_rec, thresholds)
        if not ok:
            failed_ic.append(
                {
                    "factor": name,
                    "reasons": reasons,
                    "ic": ic_rec.get("ic_mean"),
                    "icir": ic_rec.get("icir"),
                }
            )
            continue
        if bt_rec is None or bt_rec.get("layer_1_annual") is None:
            missing_bt.append(name)
            continue
        candidates.append(
            {
                "factor": name,
                "ic_mean": ic_rec.get("ic_mean"),
                "icir": ic_rec.get("icir"),
                "long_return_annual": bt_rec.get("long_return_annual"),
                "layer_1_annual": bt_rec.get("layer_1_annual"),
                "layer_1_sharpe": bt_rec.get("layer_1_sharpe"),
            }
        )

    candidates.sort(key=lambda r: r["layer_1_annual"])

    # Step 4: L1 年化分布统计
    l1_annuals = [c["layer_1_annual"] for c in candidates if c["layer_1_annual"] is not None]

    print()
    print("=" * 90)
    print("【交互因子分类】")
    print("=" * 90)
    print(f"  通过所有 IC 闸门, 待 L1 判定:  {len(candidates)} 只")
    print(f"  未通过 IC 闸门 (与 L1 无关):     {len(failed_ic)} 只")
    print(f"  缺 backtest 数据:                {len(missing_bt)} 只")

    if failed_ic:
        print()
        print("  未过 IC 闸门的因子 (供参考):")
        for r in failed_ic[:10]:
            print(f"    {r['factor']:<40} ic={r['ic']:.4f} icir={r['icir']:.4f} | {', '.join(r['reasons'])}")

    if missing_bt:
        print()
        print(f"  缺 backtest: {missing_bt}")

    if not candidates:
        print()
        print("⚠ 没有候选因子可供校准, 退出.")
        return 0

    print()
    print("=" * 90)
    print(f"【候选因子 L1 分布】 (n = {len(candidates)})")
    print("=" * 90)
    print(f"  {'factor':<42} {'IC':>8} {'ICIR':>8} {'long_ret':>9} {'L1_annual':>10} {'L1_sharpe':>10}")
    print("-" * 90)
    for c in candidates:
        print(
            f"  {c['factor']:<42} "
            f"{c['ic_mean']:>8.4f} {c['icir']:>8.4f} "
            f"{c['long_return_annual']:>9.4f} "
            f"{c['layer_1_annual']:>10.4f} {c['layer_1_sharpe']:>10.4f}"
        )

    # Step 5: 分布统计
    print()
    print("=" * 90)
    print("【L1 年化分布统计】")
    print("=" * 90)
    print(f"  样本数 n          : {len(l1_annuals)}")
    print(f"  min               : {min(l1_annuals):.4f}")
    print(f"  max               : {max(l1_annuals):.4f}")
    print(f"  mean              : {statistics.mean(l1_annuals):.4f}")
    if len(l1_annuals) >= 2:
        print(f"  stdev             : {statistics.stdev(l1_annuals):.4f}")
    print(f"  median            : {statistics.median(l1_annuals):.4f}")

    # Step 6: 推荐阈值
    print()
    print("=" * 90)
    print("【推荐阈值 (L1 年化)】")
    print("=" * 90)
    rec_p5 = recommend_threshold(l1_annuals, "p5")
    rec_p10 = recommend_threshold(l1_annuals, "p10")
    rec_2sigma = recommend_threshold(l1_annuals, "mean_2sigma")
    current = thresholds["layer_1_return_min"]

    print(f"  现阈值 (代码常量)      : {current:.4f}  ({current * 100:.1f}%)")
    if rec_p5 is not None:
        print(f"  推荐 P5 (排除最差 5%)  : {rec_p5:.4f}  ({rec_p5 * 100:.1f}%)")
    if rec_p10 is not None:
        print(f"  推荐 P10 (排除最差 10%): {rec_p10:.4f}  ({rec_p10 * 100:.1f}%)")
    if rec_2sigma is not None:
        print(f"  推荐 mean - 2σ         : {rec_2sigma:.4f}  ({rec_2sigma * 100:.1f}%)")

    # Step 7: 边界案例 — 在现阈值下被排除但接近的因子
    print()
    print("=" * 90)
    print("【边界案例】 (现阈值附近 ±5pp)")
    print("=" * 90)
    boundary = [c for c in candidates if abs(c["layer_1_annual"] - current) < 0.05]
    if boundary:
        for c in boundary:
            status = "✅ 通过" if c["layer_1_annual"] > current else "❌ 排除"
            delta = (c["layer_1_annual"] - current) * 100
            print(f"  {c['factor']:<42} L1_annual={c['layer_1_annual']:.4f} ({delta:+.2f}pp vs 现阈值)  {status}")
    else:
        print("  无 (没有因子落在现阈值 ±5pp 范围内)")

    # Step 8: 在三个推荐阈值下分别命中多少
    print()
    print("=" * 90)
    print("【不同阈值下的通过/排除情况】")
    print("=" * 90)
    for label, thr in [
        ("现阈值", current),
        ("P5", rec_p5),
        ("P10", rec_p10),
        ("mean-2σ", rec_2sigma),
    ]:
        if thr is None:
            continue
        passed = [c for c in candidates if c["layer_1_annual"] > thr]
        rejected = [c for c in candidates if c["layer_1_annual"] <= thr]
        print(f"  {label:<10} (≥{thr:.4f}): 通过 {len(passed)}, 排除 {len(rejected)}")
        if rejected:
            for r in rejected:
                print(f"      ❌ {r['factor']:<40} L1_annual={r['layer_1_annual']:.4f}")

    # Step 9: 写文件
    output = {
        "period": args.period,
        "family_prefix": args.family_prefix,
        "current_thresholds": dict(thresholds),
        "candidates": candidates,
        "failed_ic_gates": failed_ic,
        "missing_backtest": missing_bt,
        "l1_distribution": {
            "n": len(l1_annuals),
            "min": min(l1_annuals) if l1_annuals else None,
            "max": max(l1_annuals) if l1_annuals else None,
            "mean": statistics.mean(l1_annuals) if l1_annuals else None,
            "stdev": statistics.stdev(l1_annuals) if len(l1_annuals) >= 2 else None,
            "median": statistics.median(l1_annuals) if l1_annuals else None,
        },
        "recommendations": {
            "current": current,
            "p5": rec_p5,
            "p10": rec_p10,
            "mean_2sigma": rec_2sigma,
        },
    }
    if args.output:
        args.output.write_text(json.dumps(output, indent=2, ensure_ascii=False))
        print()
        print(f"  结果已写入: {args.output}")

    print()
    print("=" * 90)
    print("【决策提示】")
    print("=" * 90)
    print("  - 本脚本仅输出推荐, 不自动改 INTERACTION_THRESHOLDS 常量")
    print("  - 阈值改动需走 design.md + commit, 引用本脚本输出")
    print("  - 触发条件: 新增 >=2 个交互因子 / 季度健康检查 / 边界案例")
    return 0


if __name__ == "__main__":
    sys.exit(main())
