"""web_ui/common/pl_ratio_db.py

v0.4.8 R39 (Stage 6 功能扩展): 从 master parquet + composite daily parquet 算"每段每日 pl_ratio"
H1.1 严守 + §18 fork pattern: web_ui 内部读 parquet, 不直接 import summary 模块
不修改 data_loaders / summary 模块

数据源:
- comprehensive_factor/result/ob_quality/composite_<weight_method>_1d_daily.parquet
  (含 date / asset / composite_factor, 506 个日期)
- data_fetchers/result/ob_quality/factor_ic_data.parquet
  (含 date / asset / forward_return_1d, master parquet)

算法 (复 data_loaders.py:786-820 L 段的 load_decile_stats):
  1. 取 selection_date 当日 composite_daily.day_df (按 composite 降序)
  2. merge forward_return_1d (T+1 交易日)
  3. qcut 30 段 (按 composite rank)
  4. 每段算 wins.mean() / |losses.mean()| = pl_ratio
  5. 加粗黑虚线 = 30 段 pl_ratio 算术平均 (按用户 R39-B 选项)

数据契约:
{
    "dates": ["06-15", ...],                # mm-dd 格式
    "segments": [
        {
            "label": "S1",
            "pl_ratios": [1.23, 0.98, ...],  # 每选股日的 pl_ratio
            "avg_pl_ratio": 1.05,            # 末日累计 30 段平均 (用于排序/参考)
        },
        ...
    ],
    "avg_line": [1.20, 1.15, ...],           # 30 段当日算术平均 (粗黑虚线)
    "source": "parquet",
}
"""

from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd
from paths import PROJECT_ROOT


# 路径: 复用 paths 模块定义 (AGENTS.md §硬规则 #11)
_COMPOSITE_DAILY_PATH: Path = (
    PROJECT_ROOT / "comprehensive_factor" / "result" / "ob_quality" / "composite_rolling_icir_weight_1d_daily.parquet"
)
_MASTER_PARQUET_PATH: Path = PROJECT_ROOT / "data_fetchers" / "result" / "ob_quality" / "factor_ic_data.parquet"
_N_SEGMENTS = 30


def _compute_segment_pl_ratio(
    composite_daily: pd.DataFrame,
    forward_returns: pd.DataFrame,
    selection_date: str,
    n_segments: int = _N_SEGMENTS,
) -> dict | None:
    """对单个选股日, 算 30 段每段的 pl_ratio.

    Returns:
        {seg_label: pl_ratio} 或 None (数据不足 / qcut 失败)
    """
    day_df = composite_daily[composite_daily["date"] == selection_date].copy()
    if day_df.empty:
        return None

    merged = pd.merge(
        day_df[["asset", "composite_factor"]],
        forward_returns[["asset", "forward_return_1d"]],
        on="asset",
        how="inner",
    )
    if merged.empty:
        return None

    merged["rank"] = merged["composite_factor"].rank(ascending=False)
    try:
        merged["segment"] = pd.qcut(merged["rank"], n_segments, labels=[f"S{i + 1}" for i in range(n_segments)])
    except ValueError:
        # qcut 失败 (重复边界, 资产数不足)
        return None

    result: dict[str, float] = {}
    # v0.4.8 R39a 算法重设计: 每段当天 seg_return = mean(forward_return_1d) * 100
    # 用户原话: "等权买入 1:1:1, 3 只股票 +5%/+1%/-8% → 合并收益率 = (5+1-8)/3 = -0.67%"
    # 不是 wins.mean()/|losses.mean()| (盈亏比) — 是简单算术平均 (收益率)
    # 公式统一: 涨含跌一起平均, 不分 wins/losses
    for seg_label in [f"S{i + 1}" for i in range(n_segments)]:
        subset = merged[merged["segment"] == seg_label]
        ret = subset["forward_return_1d"].dropna()
        seg_return_pct = round(float(ret.mean() * 100), 2) if len(ret) > 0 else 0.0
        result[seg_label] = seg_return_pct
    return result


def load_pl_ratio_trend(
    n_recent_dates: int = 12,
    weight_method: str = "rolling_icir_weight",
    logger: logging.Logger | None = None,
) -> dict | None:
    """读 composite_daily + master parquet, 算最近 N 选股日 × 30 段 pl_ratio.

    Args:
        n_recent_dates: 取最近多少个选股日 (默认 12 与 txt 第九节对齐)
        weight_method: 权重方法 (默认 rolling_icir_weight)
        logger: 日志

    Returns:
        {
            "dates": ["06-15", ...],
            "segments": [{"label": "S1", "pl_ratios": [...], "avg_pl_ratio": float}, ...],
            "avg_line": [float, ...],   # 30 段当日算术平均 (粗黑虚线)
            "source": "parquet",
        }
        None: 数据缺失
    """
    # 路径根据 weight_method 动态 (R39 兼容 ic_weight / equal_weight)
    composite_path = (
        PROJECT_ROOT / "comprehensive_factor" / "result" / "ob_quality" / f"composite_{weight_method}_1d_daily.parquet"
    )
    if not composite_path.exists():
        if logger:
            logger.warning("composite daily parquet 不存在: %s", composite_path)
        return None
    if not _MASTER_PARQUET_PATH.exists():
        if logger:
            logger.warning("master parquet 不存在: %s", _MASTER_PARQUET_PATH)
        return None

    try:
        composite_daily = pd.read_parquet(composite_path, columns=["date", "asset", "composite_factor"])
        forward_returns = pd.read_parquet(_MASTER_PARQUET_PATH, columns=["date", "asset", "forward_return_1d"])
    except Exception as e:
        if logger:
            logger.warning("读 parquet 失败: %s", e)
        return None

    # 取最近 n_recent_dates 个有足够资产 (>= 30 只) 的选股日
    # qcut 30 段要求 >= 30 只 (实际 R38 实战每段 2-3 只). 早期日期 (< 06-15) pipeline 没跑资产 < 30
    # R38 segment_win_rates.parquet 的 12 天从 06-15 开始 (txt 第九节对齐), 这里也取 12 天
    asset_counts = composite_daily.groupby("date").size()
    eligible = asset_counts[asset_counts >= 30].sort_index()
    if eligible.empty:
        if logger:
            logger.warning("composite daily parquet 中无资产数 >= 30 的日期")
        return None
    # 取最后 n_recent_dates 个 (允许未来日期不足, 后面逐日处理)
    recent_dates = sorted(eligible.index.tolist())
    # 跳过最后 1 天 (T+2 master parquet 经常没到, 06-17 实战)
    # 然后取最近 n_recent_dates 个 (与 txt 第九节 12 天对齐)
    if len(recent_dates) > 1:
        recent_dates = recent_dates[:-1]
    if len(recent_dates) > n_recent_dates:
        recent_dates = recent_dates[-n_recent_dates:]

    # 对每个选股日算 pl_ratio
    seg_pl_ratios: dict[str, list[float]] = {f"S{i + 1}": [] for i in range(_N_SEGMENTS)}
    avg_line: list[float] = []
    valid_dates_mmdd: list[str] = []

    for selection_date in recent_dates:
        # 取 T+1 收益 (master parquet 里 date=trade_date)
        # data_loaders.py:770 用 next trading day, 但此处每天独立算 pl_ratio,
        # 简化: 假设 master parquet 里 forward_return_1d 已经按 date 对齐 trade_date
        # (即 composite daily.date = trade_date - 1, master parquet.date = trade_date)
        # 所以 merge 时 selection_date + 1 天 = master 的 date
        # 实战 60-100 只复 R38 用同一套 master parquet, 直接按 composite daily.date 算
        # (因为 summary 第九节 txt 显示 selection_date=06-15 → forward 是 06-16)
        # 安全起见: 取 master parquet 中 date > selection_date 的最小日期作为 trade_date
        future = forward_returns[forward_returns["date"] > selection_date]
        if future.empty:
            continue
        trade_date = sorted(future["date"].unique().tolist())[0]
        trade_rets = forward_returns[forward_returns["date"] == trade_date]

        # 复用 _compute_segment_pl_ratio 但传 trade_rets 而不是全部 forward_returns
        day_pl = _compute_segment_pl_ratio(composite_daily, trade_rets, selection_date)
        if day_pl is None:
            continue

        for seg_label, plr in day_pl.items():
            # cast np.float64 → float (避免 json.dumps 报错)
            seg_pl_ratios[seg_label].append(float(plr))
        avg_line.append(float(round(sum(day_pl.values()) / len(day_pl), 2)))
        valid_dates_mmdd.append(selection_date[5:])  # mm-dd

    if not valid_dates_mmdd:
        if logger:
            logger.warning("pl_ratio_trend 有效日期 0")
        return None

    segments = []
    for seg_label in [f"S{i + 1}" for i in range(_N_SEGMENTS)]:
        plr_list = seg_pl_ratios[seg_label]
        segments.append(
            {
                "label": seg_label,
                "pl_ratios": [float(v) for v in plr_list],
                "avg_pl_ratio": float(round(sum(plr_list) / len(plr_list), 2)) if plr_list else 0.0,
            }
        )

    if logger:
        logger.info(
            "pl_ratio_trend 加载完成: %d 段 × %d 选股日 (来源=%s)",
            len(segments),
            len(valid_dates_mmdd),
            weight_method,
        )

    return {
        "dates": valid_dates_mmdd,
        "segments": segments,
        "avg_line": [float(v) for v in avg_line],
        "source": "parquet",
    }
