"""web_ui/common/day1_filter.py

Day 1 三层过滤: 从 segment_stock_details + factor_ic_data 筛选当日入场候选。

三层过滤逻辑 (基于 21 天历史数据实证):
  P0 (必须): 候选池 >= 80 只 -- 市场信号充足, <80 直接不做
  P1 (必须): 昨日收益 < 0     -- 回调买入, 排除追高
  P2 (加分): 换手率 >= 10%     -- 流动性支撑, 软条件

实证数据 (06-15~07-14, 21 天):
  三条件全满足: n=51, avg=+1.95%, win=64.7%
  Leave-one-out: 无一天翻负, 最低 +1.09%

数据源:
  - summary/result/segment_stock_details.parquet (选股历史)
  - data_fetchers/result/factor_ic_data.parquet (past_return_1d, turnover_rate)

H1.1 严守: 只读已有产物, 不修改其他模块。
"""

from __future__ import annotations

import logging

import pandas as pd
from paths import DATA_FETCHERS_RESULT, PROJECT_ROOT


_STOCK_DETAILS_PATH = PROJECT_ROOT / "summary" / "result" / "segment_stock_details.parquet"
_FACTOR_IC_DATA_PATH = DATA_FETCHERS_RESULT / "factor_ic_data.parquet"

# 三层过滤阈值 (基于实证数据)
_MIN_BREADTH = 80  # P0: 候选池最小值
_SOFT_TURNOVER = 10.0  # P2: 换手率软门槛


def load_day1_filter(
    weight_method: str,
    stock_name_map: dict[str, str] | None = None,
    logger: logging.Logger | None = None,
) -> dict | None:
    """计算今日 Day 1 三层过滤结果。

    筛选逻辑:
      1. 取今日选中的全部股票 (Day 1 入场视角)
      2. P0: 检查候选池总数 >= 80 (一票否决)
      3. P1: 昨日收益 < 0 (past_return_1d < 0)
      4. P2: 换手率 >= 10% (软条件, 标记但不排除)

    Args:
        weight_method: 权重方法 (如 rolling_icir_weight)
        stock_name_map: 代码 -> 名称映射
        logger: 日志记录器

    Returns:
        {
            "selection_date": str,
            "breadth": int,              # 今日候选池总数
            "breadth_pass": bool,         # P0: 候选池 >= 80
            "filtered_count": int,        # 通过 P0+P1 的股票数
            "total_today": int,           # 今日选中股票总数
            "stocks": [                  # 通过 P0+P1 的股票 (按 past_return 升序)
                {
                    "code": str,
                    "name": str,
                    "segment_label": str,
                    "rank": int,
                    "past_return_1d": float,   # 昨日收益
                    "turnover_rate": float,      # 换手率
                    "turnover_pass": bool,        # P2: 换手率 >= 10%
                    "composite_value": float,
                },
            ],
            "all_stocks": [              # 全部今日股票 (含未通过, 供参考)
                {
                    "code": str,
                    "name": str,
                    "segment_label": str,
                    "past_return_1d": float,
                    "turnover_rate": float,
                    "pass_p1": bool,    # past_ret < 0
                    "pass_p2": bool,    # turnover >= 10
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

    today_df = df[df["selection_date"] == latest].copy()
    today_codes = today_df["asset"].unique().tolist()
    breadth = len(today_codes)
    breadth_pass = breadth >= _MIN_BREADTH

    # 找昨日的选股日期 (用于排除连选股: Day 1 = 昨天不在名单)
    prev_dates = [d for d in all_dates if d < latest]
    prev_date = prev_dates[-1] if prev_dates else None
    prev_codes: set[str] = set()
    if prev_date is not None:
        prev_codes = set(df[df["selection_date"] == prev_date]["asset"].unique())

    # 加载 past_return_1d, turnover_rate
    feat_map: dict[str, dict] = {}
    if _FACTOR_IC_DATA_PATH.exists():
        try:
            ret_df = pd.read_parquet(
                _FACTOR_IC_DATA_PATH,
                columns=["date", "asset", "past_return_1d", "turnover_rate"],
            )
            ret_df["date"] = pd.to_datetime(ret_df["date"])
            today_set = set(today_codes)
            sub = ret_df[(ret_df["date"] == latest) & (ret_df["asset"].isin(today_set))]
            for _, row in sub.iterrows():
                feat_map[row["asset"]] = {
                    "past_return_1d": float(row["past_return_1d"]) if pd.notna(row["past_return_1d"]) else None,
                    "turnover_rate": float(row["turnover_rate"]) if pd.notna(row["turnover_rate"]) else None,
                }
        except Exception as e:
            if logger:
                logger.warning("读 factor_ic_data.parquet 失败: %s, 特征数据将为空", e)

    # 构建全部股票列表
    all_stocks: list[dict] = []
    filtered_stocks: list[dict] = []

    for _, row in today_df.iterrows():
        code = row["asset"]
        feat = feat_map.get(code, {})
        past_ret = feat.get("past_return_1d")
        turnover = feat.get("turnover_rate")

        # P0: 候选池 >= 80 (已在外层判断)
        # P1: 昨日收益 < 0 且昨天不在选股名单 (Day 1 = 首次入选)
        is_new_today = code not in prev_codes
        pass_p1 = is_new_today and past_ret is not None and past_ret < 0
        pass_p2 = turnover is not None and turnover >= _SOFT_TURNOVER

        name = stock_name_map.get(code, "") if stock_name_map else ""

        all_stocks.append(
            {
                "code": code,
                "name": name,
                "segment_label": row["segment_label"],
                "past_return_1d": round(past_ret, 4) if past_ret is not None else None,
                "turnover_rate": round(turnover, 2) if turnover is not None else None,
                "pass_p1": pass_p1,
                "pass_p2": pass_p2,
                "is_new_today": is_new_today,
            }
        )

        # 通过 P0(已检查) + P1
        if pass_p1:
            filtered_stocks.append(
                {
                    "code": code,
                    "name": name,
                    "segment_label": row["segment_label"],
                    "rank": int(row["rank"]),
                    "past_return_1d": round(past_ret, 4),
                    "turnover_rate": round(turnover, 2) if turnover is not None else None,
                    "turnover_pass": pass_p2,
                    "composite_value": float(row["composite_value"]) if pd.notna(row["composite_value"]) else None,
                }
            )

    # 按 past_return_1d 升序 (跌得多的排前面)
    filtered_stocks.sort(key=lambda x: x["past_return_1d"])

    if logger:
        today_set = set(today_codes)
        n_continued = len(today_set & prev_codes) if prev_codes else 0
        logger.info(
            "day1_filter(%s): 今日 %d 只 (连选 %d, 新入选 %d), 候选池%s80 (%d), P1通过 %d 只",
            weight_method,
            len(today_codes),
            n_continued,
            len(today_codes) - n_continued,
            ">=" if breadth_pass else "<",
            breadth,
            len(filtered_stocks),
        )

    return {
        "selection_date": str(latest.strftime("%Y-%m-%d")),
        "breadth": breadth,
        "breadth_pass": breadth_pass,
        "filtered_count": len(filtered_stocks),
        "total_today": len(today_codes),
        "stocks": filtered_stocks,
        "all_stocks": all_stocks,
    }
