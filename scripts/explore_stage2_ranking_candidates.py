"""Stage 2 排序变量候选数据驱动测试.

问题: composite Top 300 毛年化 +5.57% 但 Top 30 毛年化 -8.43%, 信号在尾部失效.
方案: 两阶段 — Stage 1 取 composite Top 300, Stage 2 用次级变量切到 30/50.

本脚本测试 5 个 Stage 2 候选排序在 Top 300 池子内的有效性:
  - 基线: Stage 1 = Top 300, Stage 2 = composite_factor (退化到现有方案 = Top 30)
  - C1: 按 amplitude 升序（小振幅优先, 避开极端波动）
  - C2: 按 D3 hit_count 降序（企稳信号多优先）
  - C3: 按 D2 warning_count 升序（风险低优先）
  - C4: 按 amplitude × |composite| 排序（避免极端复合分）
  - C5: 按 turnover_rate 升序（避免流动性虚高炒作）

衡量: 在 Top 300 内取 Top 30 后的毛年化 / sharpe / 胜率.
"""

import numpy as np
import pandas as pd

# === 数据加载 ===
comp = pd.read_parquet(
    "comprehensive_factor/result/composite_rolling_icir_weight_1d_daily.parquet"
)
cols_needed = [
    "date",
    "asset",
    "forward_return_1d",
    "is_untradeable",
    "is_low_liquidity",
    "amplitude",
    "return_5d",
    "turnover_rate",
    "volume_ratio_5",
]
fd_all = pd.read_parquet("data_fetchers/result/factor_ic_data.parquet")
present = [c for c in cols_needed if c in fd_all.columns]
missing = [c for c in cols_needed if c not in fd_all.columns]
print(f"factor_ic_data 缺失列: {missing}")
fd = fd_all[present].copy()

fd = fd[
    (fd["is_untradeable"].fillna(0).astype(int) == 0)
    & (fd["is_low_liquidity"].fillna(0).astype(int) == 0)
]
df = comp.merge(fd.drop(columns=["is_untradeable", "is_low_liquidity"]), on=["date", "asset"], how="inner")
df = df.dropna(subset=["composite_factor", "forward_return_1d"]).copy()
print(f"有效样本: {len(df)}, 日期数: {df['date'].nunique()}")

# === Stage 1: 每日按 composite 取 Top 300 ===
df["rank_comp"] = df.groupby("date")["composite_factor"].rank(pct=True, method="first")
stage1 = df.sort_values(["date", "rank_comp"]).groupby("date").head(300).copy()
print(f"Stage 1 (Top 300) 总样本: {len(stage1)}, 平均每日: {len(stage1) / stage1['date'].nunique():.0f}")


def stage2_metrics(pool: pd.DataFrame, sort_col: str, ascending: bool, top_n: int, label: str) -> dict:
    """在 pool 内按 sort_col 排序取 top_n, 算 T+1 实战指标."""
    p = pool.dropna(subset=[sort_col])
    p = p.sort_values(["date", sort_col], ascending=[True, ascending])
    picked = p.groupby("date").head(top_n)
    daily = picked.groupby("date")["forward_return_1d"].mean()
    n_days = len(daily)
    if n_days < 100:
        return {"label": label, "n_days": n_days, "note": "样本不足"}
    annual = (1 + daily).prod() ** (252 / n_days) - 1
    sharpe = daily.mean() / daily.std() * np.sqrt(252) if daily.std() > 0 else 0
    win = (daily > 0).mean()
    avg_n = picked.groupby("date").size().mean()
    return {
        "label": label,
        "n_days": n_days,
        "annual_gross": annual,
        "sharpe_gross": sharpe,
        "win_daily": win,
        "avg_n_stocks": avg_n,
    }


# === 候选排序变量列表 ===
print()
print("=" * 100)
print(f"{'排序方案':<55} {'毛年化':>12} {'毛Sharpe':>10} {'日胜率':>8} {'avg N':>8}")
print("=" * 100)

# Stage 1 baseline: Top 300 全员
base = stage2_metrics(stage1, "composite_factor", True, 300, "[Baseline] Stage1 Top 300 全员")
print(f"  {base['label']:<53} {base.get('annual_gross', 0):>11.2%} {base.get('sharpe_gross', 0):>10.3f} {base.get('win_daily', 0):>8.2%} {base.get('avg_n_stocks', 0):>8.1f}")

# 退化: Stage 2 = composite_factor → Top 30 (= 现行方案)
m_degraded = stage2_metrics(stage1, "composite_factor", True, 30, "[退化] Stage2=composite_factor → Top 30 (现行方案)")
print(f"  {m_degraded['label']:<53} {m_degraded.get('annual_gross', 0):>11.2%} {m_degraded.get('sharpe_gross', 0):>10.3f} {m_degraded.get('win_daily', 0):>8.2%} {m_degraded.get('avg_n_stocks', 0):>8.1f}")

# 候选 C1: amplitude 升序
m_c1 = stage2_metrics(stage1, "amplitude", True, 30, "C1: amplitude 升序 (小振幅优先)")
print(f"  {m_c1['label']:<53} {m_c1.get('annual_gross', 0):>11.2%} {m_c1.get('sharpe_gross', 0):>10.3f} {m_c1.get('win_daily', 0):>8.2%} {m_c1.get('avg_n_stocks', 0):>8.1f}")

# 候选 C1': amplitude 降序 (对照, 看方向)
m_c1r = stage2_metrics(stage1, "amplitude", False, 30, "C1': amplitude 降序 (大振幅优先)")
print(f"  {m_c1r['label']:<53} {m_c1r.get('annual_gross', 0):>11.2%} {m_c1r.get('sharpe_gross', 0):>10.3f} {m_c1r.get('win_daily', 0):>8.2%} {m_c1r.get('avg_n_stocks', 0):>8.1f}")

# 候选 C3: turnover_rate 升序
m_c3 = stage2_metrics(stage1, "turnover_rate", True, 30, "C3: turnover_rate 升序 (低换手优先)")
print(f"  {m_c3['label']:<53} {m_c3.get('annual_gross', 0):>11.2%} {m_c3.get('sharpe_gross', 0):>10.3f} {m_c3.get('win_daily', 0):>8.2%} {m_c3.get('avg_n_stocks', 0):>8.1f}")

m_c3r = stage2_metrics(stage1, "turnover_rate", False, 30, "C3': turnover_rate 降序 (高换手优先)")
print(f"  {m_c3r['label']:<53} {m_c3r.get('annual_gross', 0):>11.2%} {m_c3r.get('sharpe_gross', 0):>10.3f} {m_c3r.get('win_daily', 0):>8.2%} {m_c3r.get('avg_n_stocks', 0):>8.1f}")

# 候选 C4: return_5d 升序 vs 降序 (浅跌 vs 深跌)
m_c4 = stage2_metrics(stage1, "return_5d", False, 30, "C4: return_5d 降序 (近期跌幅小优先)")
print(f"  {m_c4['label']:<53} {m_c4.get('annual_gross', 0):>11.2%} {m_c4.get('sharpe_gross', 0):>10.3f} {m_c4.get('win_daily', 0):>8.2%} {m_c4.get('avg_n_stocks', 0):>8.1f}")

m_c4r = stage2_metrics(stage1, "return_5d", True, 30, "C4': return_5d 升序 (近期跌幅大优先)")
print(f"  {m_c4r['label']:<53} {m_c4r.get('annual_gross', 0):>11.2%} {m_c4r.get('sharpe_gross', 0):>10.3f} {m_c4r.get('win_daily', 0):>8.2%} {m_c4r.get('avg_n_stocks', 0):>8.1f}")

# 候选 C5: amount 跳过 (数据未包含)

# 复合: amplitude × |composite|, |composite| 越大但 amplitude 越小越好
if "amplitude" in stage1.columns:
    s = stage1.copy()
    s["composite_neg_abs"] = -s["composite_factor"]  # composite 越负越大
    s["combo"] = s["composite_neg_abs"] / (s["amplitude"].abs() + 0.001)  # 越大越好
    m_combo = stage2_metrics(s, "combo", False, 30, "C6: |composite| / amplitude 降序")
    print(f"  {m_combo['label']:<53} {m_combo.get('annual_gross', 0):>11.2%} {m_combo.get('sharpe_gross', 0):>10.3f} {m_combo.get('win_daily', 0):>8.2%} {m_combo.get('avg_n_stocks', 0):>8.1f}")

# 复合: turnover_rate 距中位数距离 (避开极端两端, 因 C3 和 C3' 都正)
s = stage1.copy()
s["turnover_med"] = s.groupby("date")["turnover_rate"].transform("median")
s["turnover_abs_dev"] = (s["turnover_rate"] - s["turnover_med"]).abs()
m_t_center = stage2_metrics(s, "turnover_abs_dev", True, 30, "C7: turnover 距中位数升序 (取靠近中位)")
print(f"  {m_t_center['label']:<53} {m_t_center.get('annual_gross', 0):>11.2%} {m_t_center.get('sharpe_gross', 0):>10.3f} {m_t_center.get('win_daily', 0):>8.2%} {m_t_center.get('avg_n_stocks', 0):>8.1f}")

# 复合: turnover_rate z-score 绝对值 (相同含义不同实现)
s["turnover_z_abs"] = (
    s.groupby("date")["turnover_rate"].transform(lambda x: (x - x.mean()) / x.std()).abs()
)
m_t_z = stage2_metrics(s, "turnover_z_abs", True, 30, "C7': turnover z-score 绝对值升序")
print(f"  {m_t_z['label']:<53} {m_t_z.get('annual_gross', 0):>11.2%} {m_t_z.get('sharpe_gross', 0):>10.3f} {m_t_z.get('win_daily', 0):>8.2%} {m_t_z.get('avg_n_stocks', 0):>8.1f}")

# C8: 先过滤 turnover 极端两端 (掐头去尾 10%), 再用 composite 排序
s = stage1.copy()
s["t_pct"] = s.groupby("date")["turnover_rate"].rank(pct=True, method="first")
s_filtered = s[(s["t_pct"] >= 0.10) & (s["t_pct"] <= 0.90)].copy()
print(f"\n  C8 中间池: {len(s_filtered)} (~ {len(s_filtered) / s_filtered['date'].nunique():.0f}/日)")
m_c8 = stage2_metrics(s_filtered, "composite_factor", True, 30, "C8: 掐 turnover 头尾 10% 后 composite Top 30")
print(f"  {m_c8['label']:<53} {m_c8.get('annual_gross', 0):>11.2%} {m_c8.get('sharpe_gross', 0):>10.3f} {m_c8.get('win_daily', 0):>8.2%} {m_c8.get('avg_n_stocks', 0):>8.1f}")

# 不同 N 看每个 winning 候选的稳定性
print()
print("=" * 100)
print("最佳候选在不同 N 下的稳定性 (N=30/50/100):")
print("=" * 100)

# 按结果排序前 2 名再细分
candidates = {
    "amplitude 升序": ("amplitude", True),
    "turnover 升序": ("turnover_rate", True),
    "turnover 降序": ("turnover_rate", False),
    "return_5d 降序": ("return_5d", False),
}
for name, (col, asc) in candidates.items():
    print(f"\n  {name}:")
    for n in [30, 50, 100, 200]:
        m = stage2_metrics(stage1, col, asc, n, f"    Top {n}")
        if "annual_gross" in m:
            print(f"    Top {n:3d}: 年化={m['annual_gross']:+.2%}, sharpe={m['sharpe_gross']:+.3f}, 胜率={m['win_daily']:.2%}, avg={m['avg_n_stocks']:.1f}")

# === 对照: 直接从全市场用 composite 取 Top 30 (现行方案毛年化基线) ===
print()
df["rank_full"] = df.groupby("date")["composite_factor"].rank(pct=True, method="first")
direct = df.sort_values(["date", "rank_full"]).groupby("date").head(30)
direct_daily = direct.groupby("date")["forward_return_1d"].mean()
direct_annual = (1 + direct_daily).prod() ** (252 / len(direct_daily)) - 1
print(f"对照: 直接 Top 30 (跳过 Stage 1): 年化={direct_annual:+.2%}")
