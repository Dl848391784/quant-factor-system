"""web_ui/common/streak_tracker.py

连续入选追踪器: 从 segment_stock_details.parquet 计算每只股票的连选天数、
分段轨迹、分段跨度、连选期间累计收益。

数据源:
  - summary/result/segment_stock_details.parquet (选股历史)
  - data_fetchers/result/factor_ic_data.parquet (forward_return_1d 用于收益计算)

H1.1 严守: 只读已有产物, 不修改其他模块。
"""

from __future__ import annotations

import logging

import pandas as pd
from paths import DATA_FETCHERS_RESULT, PROJECT_ROOT


_STOCK_DETAILS_PATH = PROJECT_ROOT / "summary" / "result" / "segment_stock_details.parquet"
_FACTOR_IC_DATA_PATH = DATA_FETCHERS_RESULT / "factor_ic_data.parquet"

# 连选筛选阈值
_MIN_STREAK = 2  # 至少连选 2 天
_MAX_STREAK = 4  # 不超过 4 天 (排除 5 天以上)
_MIN_SEG_RANGE = 2  # 分段跨度至少 2 (跳跃型)


def _compute_streaks(
    dates_list: list[pd.Timestamp],
    all_dates: list[pd.Timestamp],
) -> list[list[pd.Timestamp]]:
    """找出连续交易日子序列 (长度 >= 2)。

    Args:
        dates_list: 某只股票出现过的选股日 (已排序)
        all_dates: 全部选股日 (已排序, 用于判断连续性)

    Returns:
        连续子序列列表, 每个子序列长度 >= 2
    """
    if len(dates_list) <= 1:
        return []
    date_idx = {d: i for i, d in enumerate(all_dates)}
    streaks: list[list[pd.Timestamp]] = []
    curr = [dates_list[0]]
    for i in range(1, len(dates_list)):
        prev_i = date_idx.get(dates_list[i - 1])
        curr_i = date_idx.get(dates_list[i])
        if curr_i is not None and prev_i is not None and curr_i == prev_i + 1:
            curr.append(dates_list[i])
        else:
            if len(curr) >= 2:
                streaks.append(curr)
            curr = [dates_list[i]]
    if len(curr) >= 2:
        streaks.append(curr)
    return streaks


def load_streak_tracker(
    weight_method: str,
    stock_name_map: dict[str, str] | None = None,
    logger: logging.Logger | None = None,
) -> dict | None:
    """计算今日选中股票的连选追踪数据。

    筛选逻辑:
      1. 取今日选中的全部股票
      2. 对每只股票, 从历史数据中找连续入选 streak
      3. 筛选: 当前 streak 长度 2~4 天 + 分段跨度 >= 2 (跳跃型)

    Args:
        weight_method: 权重方法 (如 rolling_icir_weight)
        stock_name_map: 代码 -> 名称映射
        logger: 日志记录器

    Returns:
        {
            "selection_date": str,
            "total_today": int,           # 今日选中股票总数
            "tracked_count": int,          # 符合筛选条件的股票数
            "stocks": [                    # 按连选天数降序
                {
                    "code": str,
                    "name": str,
                    "streak_len": int,      # 当前连选天数
                    "segments": [str, ...],  # 连选期间所在分段 (如 ["S14","S11","S11"])
                    "seg_range": int,        # 分段跨度 (max - min)
                    "daily_returns": [float, ...],  # 每日 forward_return_1d
                    "cum_return": float,     # 连选期间累计收益
                    "ranks": [int, ...],     # 每日排名
                    "streak_start": str,     # 开始日期 MM-DD
                    "streak_end": str,       # 结束日期 MM-DD
                },
            ],
        }
        None: 数据不足
    """
    if not _STOCK_DETAILS_PATH.exists():
        if logger:
            logger.warning("segment_stock_details.parquet 不存在")
        return None

    try:
        df = pd.read_parquet(_STOCK_DETAILS_PATH)
    except Exception as e:
        if logger:
            logger.warning("读 segment_stock_details.parquet 失败: %s", e)
        return None

    df = df[(df["pipeline"] == "ob_quality") & (df["weight_method"] == weight_method)]
    if df.empty:
        if logger:
            logger.info("segment_stock_details 无 ob_quality/%s 数据", weight_method)
        return None

    df["selection_date"] = pd.to_datetime(df["selection_date"])
    all_dates = sorted(df["selection_date"].unique())
    latest = all_dates[-1]
    today_codes = set(df[df["selection_date"] == latest]["asset"].unique())

    # 加载 forward_return_1d
    fwd_map: dict[tuple[str, pd.Timestamp], float] = {}
    if _FACTOR_IC_DATA_PATH.exists():
        try:
            ret_df = pd.read_parquet(
                _FACTOR_IC_DATA_PATH,
                columns=["date", "asset", "forward_return_1d"],
            )
            ret_df["date"] = pd.to_datetime(ret_df["date"])
            for _, row in ret_df[ret_df["asset"].isin(today_codes)].iterrows():
                fwd_map[(row["asset"], row["date"])] = row["forward_return_1d"]
        except Exception as e:
            if logger:
                logger.warning("读 factor_ic_data.parquet 失败: %s, 收益数据将为空", e)

    # 对每只今日选中的股票, 计算连选 streak
    results: list[dict] = []
    for code in today_codes:
        stock_df = df[df["asset"] == code].sort_values("selection_date")
        stock_dates = sorted(stock_df["selection_date"].unique())

        streaks = _compute_streaks(stock_dates, all_dates)
        if not streaks:
            continue

        # 取包含今日的 streak (最后一个 streak)
        current_streak = streaks[-1]
        if current_streak[-1] != latest:
            continue  # 今日不在 streak 中

        streak_len = len(current_streak)
        if streak_len < _MIN_STREAK or streak_len > _MAX_STREAK:
            continue

        # 取 streak 期间的数据
        streak_data = stock_df[stock_df["selection_date"].isin(current_streak)].sort_values("selection_date")
        segments = streak_data["segment_label"].tolist()
        seg_nums = [int(s[1:]) for s in segments]
        seg_range = max(seg_nums) - min(seg_nums)
        if seg_range < _MIN_SEG_RANGE:
            continue

        ranks = streak_data["rank"].tolist()
        daily_returns = []
        for _, row in streak_data.iterrows():
            r = fwd_map.get((code, row["selection_date"]))
            if r is not None and pd.notna(r):
                daily_returns.append(round(float(r), 4))
            else:
                daily_returns.append(None)

        # 累计收益 (复乘法, 跳过 None)
        cum = 1.0
        for r in daily_returns:
            if r is not None:
                cum *= 1 + r
        cum_ret = round(cum - 1, 4)

        name = ""
        if stock_name_map:
            name = stock_name_map.get(code, "")

        results.append(
            {
                "code": code,
                "name": name,
                "streak_len": streak_len,
                "segments": segments,
                "seg_range": seg_range,
                "daily_returns": daily_returns,
                "cum_return": cum_ret,
                "ranks": ranks,
                "streak_start": current_streak[0].strftime("%m-%d"),
                "streak_end": current_streak[-1].strftime("%m-%d"),
            }
        )

    # 按连选天数降序, 再按累计收益降序
    results.sort(key=lambda x: (-x["streak_len"], -(x["cum_return"] if x["cum_return"] is not None else 0)))

    if logger:
        logger.info(
            "streak_tracker(%s): 今日 %d 只, 符合条件 %d 只 (streak %d-%d, seg_range>=%d)",
            weight_method,
            len(today_codes),
            len(results),
            _MIN_STREAK,
            _MAX_STREAK,
            _MIN_SEG_RANGE,
        )

    return {
        "selection_date": str(latest.strftime("%Y-%m-%d")),
        "total_today": len(today_codes),
        "tracked_count": len(results),
        "stocks": results,
    }
