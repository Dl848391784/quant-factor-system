"""
Top N 短名单 T+1 实战回测脚本.

回答的核心问题:
    阴跌问题是"量化问题"(短名单 T+1 持仓真亏) 还是"体感问题"(看着跌但实际赚)?

设计原则 (PROJECT.md):
    - T+1 持仓: T-1 日数据 → T 日 09:25 算 → T 日尾盘买 → T+1 日卖
    - 评估指标: 只用 forward_return_1d (持仓 1 日就卖)
    - 含成本: 0.1% 双边 (一买一卖, 实战交易成本)
    - 过滤不可交易: is_untradeable=1 (T 日涨停无法买入)

输入:
    comprehensive_factor/result/composite_*_1d_daily.parquet  (composite 因子值)
    data_fetchers/result/factor_ic_data.parquet               (forward_return_1d + is_untradeable)

输出:
    每日 Top N 等权组合的实战指标 (年化 / sharpe / 胜率 / 最大回撤)
    分日明细 + 累计净值曲线

用法:
    python scripts/backtest_top_n_realworld.py
    python scripts/backtest_top_n_realworld.py --top-n 30 --cost 0.001
    python scripts/backtest_top_n_realworld.py --top-n 5 10 30 --weighting equal
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)-8s | %(message)s")
logger = logging.getLogger("backtest_top_n_realworld")


def load_data(composite_file: Path) -> pd.DataFrame:
    """合并 composite 因子值 + forward_return_1d + is_untradeable."""
    logger.info("加载 composite: %s", composite_file.name)
    comp = pd.read_parquet(composite_file)
    # 列名: date, asset, composite_factor
    logger.info("  composite shape: %s, 日期数: %d", comp.shape, comp["date"].nunique())

    logger.info("加载 factor_ic_data.parquet (forward_return_1d + is_untradeable)")
    fd_path = PROJECT_ROOT / "data_fetchers" / "result" / "factor_ic_data.parquet"
    cols = ["date", "asset", "forward_return_1d", "is_untradeable"]
    fd = pd.read_parquet(fd_path, columns=cols)
    logger.info("  factor_ic_data shape: %s", fd.shape)

    df = comp.merge(fd, on=["date", "asset"], how="left")
    logger.info("  merge 后 shape: %s", df.shape)

    # 缺 forward_return_1d 的最后一天 (T 日选股, T+1 收益还没出)
    last_n_missing = df[df["forward_return_1d"].isna()]["date"].nunique()
    logger.info("  缺 forward_return_1d 的日期数: %d (含最后 1 日)", last_n_missing)
    return df


def select_top_n_daily(df: pd.DataFrame, top_n: int) -> pd.DataFrame:
    """每日按 composite_factor 升序 (越小越好) 取 Top N.

    分层算法: 与 backtest/common/layered_backtest.py 一致 (rank(pct=True, method='first')),
        避免 cumcount/n_per_day 在边界处的取整偏差.

    过滤:
        - is_untradeable=1 (T 日涨停, T 日尾盘无法买入)
        - is_low_liquidity=1 (与 composite_runner factor_loader 一致)
        - forward_return_1d 缺失 (最后 1 日)
        - composite_factor 缺失 (IC 滚动 padding 期或个别股票)

    Returns:
        DataFrame[date, asset, composite_factor, forward_return_1d]
    """
    # 过滤不可交易
    untradeable_mask = df["is_untradeable"].fillna(0).astype(int) == 1
    n_untradeable = int(untradeable_mask.sum())

    # 过滤低流动性 (composite_runner factor_loader 同步逻辑)
    low_liq_mask = (
        df["is_low_liquidity"].fillna(0).astype(int) == 1
        if "is_low_liquidity" in df.columns
        else pd.Series(False, index=df.index)
    )
    n_low_liq = int(low_liq_mask.sum())

    # 过滤缺收益数据 / 缺 composite_factor
    missing_ret_mask = df["forward_return_1d"].isna()
    missing_comp_mask = df["composite_factor"].isna()
    n_missing_ret = int(missing_ret_mask.sum())
    n_missing_comp = int(missing_comp_mask.sum())

    valid = df[
        ~untradeable_mask & ~low_liq_mask & ~missing_ret_mask & ~missing_comp_mask
    ].copy()
    logger.info(
        "  过滤: 不可交易 %d, 低流动性 %d, 缺收益 %d, 缺 composite %d, 剩余 %d",
        n_untradeable,
        n_low_liq,
        n_missing_ret,
        n_missing_comp,
        len(valid),
    )

    # 用 rank(pct=True, method='first') 而非排序+head, 保证与 layered_backtest 分层一致
    # Top N 实际是 rank_pct <= N/n_today 的子集
    valid["rank_pct"] = valid.groupby("date")["composite_factor"].rank(
        pct=True, method="first"
    )
    # 按 rank 升序取每日前 N
    valid = valid.sort_values(["date", "rank_pct"])
    top_n_df = valid.groupby("date", as_index=False).head(top_n).reset_index(drop=True)
    return top_n_df


def compute_daily_returns(top_n_df: pd.DataFrame, cost_per_side: float) -> pd.DataFrame:
    """计算每日 Top N 等权组合 T+1 收益.

    成本模型: 假设每日全部换仓 → 双边成本 = 2 × cost_per_side
        (实战可能部分留仓, 这里取保守上界)

    Returns:
        DataFrame[date, gross_return, net_return, n_stocks, win_rate]
    """
    cost = 2 * cost_per_side  # 双边
    daily = (
        top_n_df.groupby("date")
        .agg(
            gross_return=("forward_return_1d", "mean"),
            n_stocks=("asset", "count"),
            win_rate=("forward_return_1d", lambda s: (s > 0).mean()),
        )
        .reset_index()
    )
    daily["net_return"] = daily["gross_return"] - cost
    return daily


def compute_metrics(daily: pd.DataFrame, label: str) -> dict[str, float]:
    """计算回测核心指标."""
    n = len(daily)
    if n == 0:
        return {"label": label, "n_days": 0}

    gross = daily["gross_return"]
    net = daily["net_return"]

    # 年化 (252 交易日)
    gross_annual = (1 + gross).prod() ** (252 / n) - 1
    net_annual = (1 + net).prod() ** (252 / n) - 1

    # 夏普 (无风险利率假设 0)
    gross_sharpe = gross.mean() / gross.std() * np.sqrt(252) if gross.std() > 0 else 0.0
    net_sharpe = net.mean() / net.std() * np.sqrt(252) if net.std() > 0 else 0.0

    # 累计净值 + 最大回撤
    net_curve = (1 + net).cumprod()
    running_max = net_curve.cummax()
    drawdown = (net_curve - running_max) / running_max
    max_dd = drawdown.min()

    # 胜率 / 持仓 1d 平均
    win_rate_daily = (net > 0).mean()
    avg_n_stocks = daily["n_stocks"].mean()
    avg_stock_win_rate = daily["win_rate"].mean()

    return {
        "label": label,
        "n_days": n,
        "gross_daily_mean": gross.mean(),
        "net_daily_mean": net.mean(),
        "gross_annual": gross_annual,
        "net_annual": net_annual,
        "gross_sharpe": gross_sharpe,
        "net_sharpe": net_sharpe,
        "max_drawdown": max_dd,
        "win_rate_daily": win_rate_daily,
        "avg_n_stocks": avg_n_stocks,
        "avg_stock_win_rate": avg_stock_win_rate,
        "final_nav": net_curve.iloc[-1],
    }


def print_metrics(metrics_list: list[dict]) -> None:
    """格式化打印多组对比."""
    print()
    print("=" * 100)
    print(f"{'指标':<28} " + " ".join(f"{m['label']:>14}" for m in metrics_list))
    print("=" * 100)
    rows = [
        ("交易日数", "n_days", "{:.0f}"),
        ("平均日组合规模", "avg_n_stocks", "{:.1f}"),
        ("毛日收益均值", "gross_daily_mean", "{:.4%}"),
        ("净日收益均值 (扣成本)", "net_daily_mean", "{:.4%}"),
        ("毛年化收益", "gross_annual", "{:.2%}"),
        ("【净年化收益】", "net_annual", "{:.2%}"),
        ("毛夏普", "gross_sharpe", "{:.3f}"),
        ("【净夏普】", "net_sharpe", "{:.3f}"),
        ("最大回撤", "max_drawdown", "{:.2%}"),
        ("日胜率 (组合 > 0)", "win_rate_daily", "{:.2%}"),
        ("平均个股胜率", "avg_stock_win_rate", "{:.2%}"),
        ("最终净值", "final_nav", "{:.3f}"),
    ]
    for label, key, fmt in rows:
        vals = [fmt.format(m.get(key, 0)) if m.get(key) is not None else "n/a" for m in metrics_list]
        print(f"  {label:<26} " + " ".join(f"{v:>14}" for v in vals))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--composite",
        default="composite_rolling_icir_weight_1d",
        help="composite 文件 stem (默认 rolling_icir)",
    )
    parser.add_argument(
        "--top-n",
        type=int,
        nargs="+",
        default=[5, 10, 30],
        help="Top N 列表 (默认 5 10 30)",
    )
    parser.add_argument(
        "--cost",
        type=float,
        default=0.001,
        help="单边交易成本 (默认 0.001=0.1%%, 双边为 0.2%%)",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=PROJECT_ROOT / "scripts" / "result",
        help="输出目录",
    )
    args = parser.parse_args()

    args.output_dir.mkdir(parents=True, exist_ok=True)

    logger.info("=" * 80)
    logger.info("Top N 短名单 T+1 实战回测 (持仓 1 日, 含成本 %.2f%%)", args.cost * 200)
    logger.info("=" * 80)

    composite_file = (
        PROJECT_ROOT / "comprehensive_factor" / "result" / f"{args.composite}_daily.parquet"
    )
    if not composite_file.exists():
        logger.error("composite 文件不存在: %s", composite_file)
        return 1

    df = load_data(composite_file)

    # 多 Top N 对比
    all_metrics: list[dict] = []
    all_daily: dict[int, pd.DataFrame] = {}
    for top_n in args.top_n:
        logger.info("")
        logger.info("--- Top %d ---", top_n)
        top_n_df = select_top_n_daily(df, top_n)
        daily = compute_daily_returns(top_n_df, args.cost)
        all_daily[top_n] = daily
        metrics = compute_metrics(daily, label=f"Top {top_n}")
        all_metrics.append(metrics)

    # 基准: 全市场等权 (扣同等成本)
    logger.info("")
    logger.info("--- 基准: 全市场等权 ---")
    untradeable_mask = df["is_untradeable"].fillna(0).astype(int) == 1
    missing_ret_mask = df["forward_return_1d"].isna()
    valid = df[~untradeable_mask & ~missing_ret_mask]
    bench_daily = compute_daily_returns(
        valid.assign(asset_id=valid["asset"])[["date", "asset", "forward_return_1d"]],
        args.cost,
    )
    bench_metrics = compute_metrics(bench_daily, label="全市场等权")
    all_metrics.append(bench_metrics)

    print_metrics(all_metrics)

    # 保存明细
    out_file = args.output_dir / f"top_n_realworld_backtest_{args.composite}.csv"
    rows = []
    for top_n, daily in all_daily.items():
        d = daily.copy()
        d["top_n"] = top_n
        rows.append(d)
    bench_daily["top_n"] = "benchmark"
    rows.append(bench_daily)
    pd.concat(rows, ignore_index=True).to_csv(out_file, index=False)
    logger.info("")
    logger.info("明细已保存: %s", out_file)

    # 关键结论 (诚实陈述)
    print()
    print("=" * 100)
    print("【关键结论 (事实陈述)】")
    print("=" * 100)
    top30_m = next((m for m in all_metrics if m["label"] == "Top 30"), None)
    bench_m = next((m for m in all_metrics if m["label"] == "全市场等权"), None)
    if top30_m and bench_m:
        excess = top30_m["net_annual"] - bench_m["net_annual"]
        excess_sharpe = top30_m["net_sharpe"] - bench_m["net_sharpe"]
        print(f"  Top 30 净年化: {top30_m['net_annual']:.2%}")
        print(f"  全市场等权:    {bench_m['net_annual']:.2%}")
        print(f"  超额年化:      {excess:+.2%}")
        print(f"  超额夏普:      {excess_sharpe:+.3f}")
        print()
        if top30_m["net_annual"] > 0 and top30_m["net_sharpe"] > 1.0:
            print("  → 结论倾向: Top 30 在 T+1 实战层面 ✅ 赚钱, '阴跌问题' 偏向【体感问题】")
        elif top30_m["net_annual"] < 0:
            print("  → 结论倾向: Top 30 在 T+1 实战层面 ❌ 亏钱, '阴跌问题' 是真【量化问题】")
        else:
            print("  → 结论倾向: Top 30 边际 (年化>0 但夏普<1.0), 需进一步看胜率 / 回撤判定")

    return 0


if __name__ == "__main__":
    sys.exit(main())
