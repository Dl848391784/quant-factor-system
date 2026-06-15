"""data_fetchers.factor_calculator.industry：行业聚合（无外部 I/O）因子。

模块定位
========
基于个股因子向行业层聚合，**仅读取** ``factor_df`` 内既有列 +
``fetch_industry.get_industry_map()``（模块级缓存，行业代码→行业名称的
内存映射），不加载任何外部 parquet 文件。

公共 API（design.md §5.6）
==========================
- ``calculate_industry_momentum_5d(factor_df, ...)``：行业 5 日动量
  （行业内个股 ``return_5d`` 均值，再回填到个股层）
- ``calculate_industry_turnover_trend(factor_df, ...)``：行业换手率趋势
  （行业内 ``turnover_rate`` 5 日斜率）
- ``calculate_industry_amplitude_trend(factor_df, ...)``：行业振幅趋势
  （行业内 ``amplitude`` 5 日均值变化）

依赖
====
- ``_common``：列名、4 个行业相关默认常量、``_add_industry_column`` helper
  （PR-4a 从 _legacy.py 搬入 _common.py，被 industry / industry_financial /
  fund_flow 三个子模块共用）、``get_module_logger``
- ``numpy`` / ``pandas`` / ``logging``：标准外部依赖

注意事项
========
- 3 个 industry 因子都通过 ``_add_industry_column`` 把 industry 列合并到主
  factor_df 后再做 groupby 聚合
- **不依赖** ``industry_financial.py``（行业基本面）或 ``fund_flow.py``
  （资金流），是 industry 类因子中最"轻"的一组
- 不读取任何外部 parquet 文件；所有行业映射由 ``fetch_industry`` 模块缓存
  提供

兼容性
======
本模块函数实现与原 ``factor_calculator.py`` v1.17 字节级一致；PR-4a 通过
``temporary/factor_calculator_baseline_fingerprint.json`` 的 22 个因子
指纹验证。
"""

from __future__ import annotations

import logging

import pandas as pd

from ._common import (
    _COL_AMPLITUDE,
    _COL_ASSET,
    _COL_CLOSE,
    _COL_DATE,
    _COL_INDUSTRY_AMPLITUDE_TREND,
    _COL_INDUSTRY_MOMENTUM_5D,
    _COL_INDUSTRY_TURNOVER_TREND,
    _COL_TURNOVER_RATE,
    _DEFAULT_AMPLITUDE_TREND_DENOMINATOR_MIN,
    _DEFAULT_INDUSTRY_WINDOW,
    _DEFAULT_MIN_INDUSTRY_STOCKS,
    _DEFAULT_TREND_DENOMINATOR_MIN,
    _add_industry_column,
    get_module_logger,
)


__all__: list[str] = []


def calculate_industry_momentum_5d(
    factor_df: pd.DataFrame,
    *,
    logger_arg: logging.Logger | None = None,
) -> pd.DataFrame:
    """计算行业5日动量因子

    公式:
      1. 添加 industry 列（从行业映射）
      2. 计算个股 past_return_1d = close / prev_close - 1（按 asset 分组 shift）
      3. 按 (industry, date) 分组 → mean(past_return_1d) → 5日滚动均值
      4. 同行业所有股票赋相同行业动量值

    含义:
      - 高正值: 行业整体5日上涨趋势（行业配置偏向该行业）
      - 高负值: 行业整体5日下跌趋势（行业配置规避该行业）
      - 近零值: 行业整体横盘无趋势

    边界处理:
      - industry 未知 → 赋 '其他' 行业
      - 行业股票数 < 5 → 该日期该行业因子值 NaN（min_periods=5）
      - past_return_1d 为 NaN → 行业均值自动跳过（pandas mean NaN-safe）

    遵循 H5: IC方向不预判
    实测结论: 行业层面IC=+0.026（正值），方向性信号存在

    required_cols: ["date", "asset", "close"]
    """
    _logger = get_module_logger(logger_arg)

    df = factor_df.copy()

    # Step 1: 添加 industry 列
    _logger.info("  Step 1: 添加行业分类列...")
    df = _add_industry_column(df, _logger)

    # Step 2: 计算个股日收益率（按 asset 分组 shift）
    _logger.info("  Step 2: 计算个股日收益率...")
    df = df.sort_values([_COL_ASSET, _COL_DATE])
    prev_close = df.groupby(_COL_ASSET)[_COL_CLOSE].shift(1)
    df["past_return_1d_calc"] = (df[_COL_CLOSE] / prev_close) - 1  # 中间列，最终删除

    # Step 3: 按 (industry, date) 分组 → 5日滚动均值
    _logger.info("  Step 3: 按行业分组计算5日动量...")
    industry_daily_mean = df.groupby(["industry", _COL_DATE])["past_return_1d_calc"].mean().reset_index()
    industry_daily_mean = industry_daily_mean.sort_values(["industry", _COL_DATE])

    # 5日滚动均值（按行业分组）
    industry_daily_mean[_COL_INDUSTRY_MOMENTUM_5D] = (
        industry_daily_mean.groupby("industry")["past_return_1d_calc"]
        .rolling(_DEFAULT_INDUSTRY_WINDOW, min_periods=_DEFAULT_MIN_INDUSTRY_STOCKS)
        .mean()
        .reset_index(level=0, drop=True)
    )

    # Step 4: 行业动量值赋给每只个股
    _logger.info("  Step 4: 行业动量赋给个股...")
    # 创建 industry → (date → momentum) 映射
    momentum_map = industry_daily_mean.set_index(["industry", _COL_DATE])[_COL_INDUSTRY_MOMENTUM_5D]

    # 将行业动量值赋给原始 df
    df = df.sort_values([_COL_ASSET, _COL_DATE])  # 确保排序与原始一致
    df[_COL_INDUSTRY_MOMENTUM_5D] = df.set_index(["industry", _COL_DATE]).index.map(
        lambda idx: momentum_map.get(idx, float("nan"))
    )

    # 删除中间列
    df = df.drop(columns=["past_return_1d_calc"])

    valid_count = int(df[_COL_INDUSTRY_MOMENTUM_5D].notna().sum())
    _logger.info(
        "  有效 %s: %d (%.2f%%)",
        _COL_INDUSTRY_MOMENTUM_5D,
        valid_count,
        valid_count / len(df) * 100 if len(df) > 0 else 0,
    )

    return df


calculate_industry_momentum_5d.required_cols = ["date", "asset", "close"]  # type: ignore[attr-defined]


def calculate_industry_turnover_trend(
    factor_df: pd.DataFrame,
    *,
    logger_arg: logging.Logger | None = None,
) -> pd.DataFrame:
    """计算行业换手率趋势因子

    公式:
      1. 添加 industry 列
      2. 按 (industry, date) 分组 → mean(turnover_rate) → 行业日均换手率
      3. industry_turnover_trend = turnover_avg(t) / turnover_avg(t-1) - 1
      4. 同行业所有股票赋相同行业换手趋势值

    含义:
      - 高正值: 行业换手率显著上升（市场关注度增加）
      - 高负值: 行业换手率显著下降（市场关注度下降）
      - 近零值: 行业换手率平稳

    边界处理:
      - industry 未知 → 赋 '其他'
      - turnover_avg(t-1) 极小 → clip(lower=0.001) 避免极端比值（遵循 Pitfall #47）
      - 行业股票数 < 5 → NaN

    遵循 H5: IC方向不预判

    required_cols: ["date", "asset", "turnover_rate"]
    """
    _logger = get_module_logger(logger_arg)

    df = factor_df.copy()

    # Step 1: 添加 industry 列
    _logger.info("  Step 1: 添加行业分类列...")
    df = _add_industry_column(df, _logger)

    # Step 2: 按 (industry, date) 分组 → mean(turnover_rate)
    _logger.info("  Step 2: 按行业分组计算日均换手率...")
    industry_daily_turnover = df.groupby(["industry", _COL_DATE])[_COL_TURNOVER_RATE].mean().reset_index()
    industry_daily_turnover = industry_daily_turnover.sort_values(["industry", _COL_DATE])

    # Step 3: 计算换手率趋势 = today_avg / yesterday_avg - 1
    _logger.info("  Step 3: 计算换手率趋势（比率型因子）...")
    prev_avg = industry_daily_turnover.groupby("industry")[_COL_TURNOVER_RATE].shift(1)
    # 分母保护：clip 避免极端比值（遵循 Pitfall #47）
    prev_avg_safe = prev_avg.clip(lower=_DEFAULT_TREND_DENOMINATOR_MIN)
    industry_daily_turnover[_COL_INDUSTRY_TURNOVER_TREND] = (
        industry_daily_turnover[_COL_TURNOVER_RATE] / prev_avg_safe - 1
    )
    # 分母原值为0时，clip后仍会产生极端值 → 设NaN（无意义趋势）
    industry_daily_turnover.loc[prev_avg == 0, _COL_INDUSTRY_TURNOVER_TREND] = float("nan")

    # Step 4: 行业换手趋势赋给每只个股
    _logger.info("  Step 4: 行业换手趋势赋给个股...")
    trend_map = industry_daily_turnover.set_index(["industry", _COL_DATE])[_COL_INDUSTRY_TURNOVER_TREND]

    df[_COL_INDUSTRY_TURNOVER_TREND] = df.set_index(["industry", _COL_DATE]).index.map(
        lambda idx: trend_map.get(idx, float("nan"))
    )

    valid_count = int(df[_COL_INDUSTRY_TURNOVER_TREND].notna().sum())
    _logger.info(
        "  有效 %s: %d (%.2f%%)",
        _COL_INDUSTRY_TURNOVER_TREND,
        valid_count,
        valid_count / len(df) * 100 if len(df) > 0 else 0,
    )

    return df


calculate_industry_turnover_trend.required_cols = ["date", "asset", "turnover_rate"]  # type: ignore[attr-defined]


def calculate_industry_amplitude_trend(
    factor_df: pd.DataFrame,
    *,
    logger_arg: logging.Logger | None = None,
) -> pd.DataFrame:
    """计算行业振幅趋势因子

    公式:
      1. 添加 industry 列
      2. 按 (industry, date) 分组 → mean(amplitude) → 行业日均振幅
      3. industry_amplitude_trend = amplitude_avg(t) / amplitude_avg(t-1) - 1
      4. 同行业所有股票赋相同行业振幅趋势值

    含义:
      - 高正值: 行业振幅显著上升（波动性增加）
      - 高负值: 行业振幅显著下降（波动性收敛）
      - 近零值: 行业振幅平稳

    边界处理:
      - industry 未知 → 赋 '其他'
      - amplitude_avg(t-1) 极小 → clip(lower=0.01) 避免极端比值
      - amplitude_avg(t-1) = 0 → NaN（涨跌停无意义趋势）
      - 行业股票数 < 5 → NaN

    遵循 H5: IC方向不预判

    required_cols: ["date", "asset", "amplitude"]
    """
    _logger = get_module_logger(logger_arg)

    df = factor_df.copy()

    # Step 1: 添加 industry 列
    _logger.info("  Step 1: 添加行业分类列...")
    df = _add_industry_column(df, _logger)

    # Step 2: 按 (industry, date) 分组 → mean(amplitude)
    _logger.info("  Step 2: 按行业分组计算日均振幅...")
    industry_daily_amplitude = df.groupby(["industry", _COL_DATE])[_COL_AMPLITUDE].mean().reset_index()
    industry_daily_amplitude = industry_daily_amplitude.sort_values(["industry", _COL_DATE])

    # Step 3: 计算振幅趋势 = today_avg / yesterday_avg - 1
    _logger.info("  Step 3: 计算振幅趋势（比率型因子）...")
    prev_avg = industry_daily_amplitude.groupby("industry")[_COL_AMPLITUDE].shift(1)
    # 分母保护：振幅=0意味着涨跌停，clip 下限 0.01（遵循 Pitfall #47）
    prev_avg_safe = prev_avg.clip(lower=_DEFAULT_AMPLITUDE_TREND_DENOMINATOR_MIN)
    industry_daily_amplitude[_COL_INDUSTRY_AMPLITUDE_TREND] = (
        industry_daily_amplitude[_COL_AMPLITUDE] / prev_avg_safe - 1
    )
    # 分母原值为0时 → NaN（涨跌停场景趋势无意义）
    industry_daily_amplitude.loc[prev_avg == 0, _COL_INDUSTRY_AMPLITUDE_TREND] = float("nan")

    # Step 4: 行业振幅趋势赋给每只个股
    _logger.info("  Step 4: 行业振幅趋势赋给个股...")
    trend_map = industry_daily_amplitude.set_index(["industry", _COL_DATE])[_COL_INDUSTRY_AMPLITUDE_TREND]

    df[_COL_INDUSTRY_AMPLITUDE_TREND] = df.set_index(["industry", _COL_DATE]).index.map(
        lambda idx: trend_map.get(idx, float("nan"))
    )

    valid_count = int(df[_COL_INDUSTRY_AMPLITUDE_TREND].notna().sum())
    _logger.info(
        "  有效 %s: %d (%.2f%%)",
        _COL_INDUSTRY_AMPLITUDE_TREND,
        valid_count,
        valid_count / len(df) * 100 if len(df) > 0 else 0,
    )

    return df


calculate_industry_amplitude_trend.required_cols = ["date", "asset", "amplitude"]  # type: ignore[attr-defined]
