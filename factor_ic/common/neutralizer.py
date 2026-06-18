"""中性化引擎: 多控制变量截面回归（design.md §3.2, §5.1）。

职责:
    给定 factor_df (含 [date, asset, factor_col]) 与一组 ControlProvider，
    对每个交易日做 OLS 截面回归，返回残差因子（DataFrame[date, asset, neutral_factor]）。

设计要点:
    1. **三层分离**: runner (调度) → neutralizer (引擎) → providers (数据/预处理)
    2. **共线性自动决策**: 含 numerical Provider 时自动 fit_intercept=True + drop_first=True；
       纯 categorical（含本期 P1 IndustryProvider 单独使用）保留 fit_intercept=True +
       drop_first=False，与 P0 industry_neutral_residual 逐位一致（design.md §5.3 共线性护栏）
    3. **NaN 引擎统一处理**: factor_col + 各 control 列任一 NaN 即整行 dropna，
       避免 Provider 各自处理失控
    4. **小行业/小样本过滤**: 各 Provider 自报 filter_invalid_rows，引擎按 AND 收敛

P1 期间默认仅 IndustryProvider 入参，行为与 P0 industry_neutral_residual 完全一致；
P2 起 LogMarketCapProvider 注入后开启 has_numerical 分支。

参考:
    designs/feat_neutralization_framework.md §3.2, §5.1, §5.3
    factor_ic/common/ic_calculator.py industry_neutral_residual (P0 参考实现)
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from .control_providers.base import ControlProvider
from .logger_config import get_logger


def _build_design_matrix(
    day_df: pd.DataFrame,
    providers: list[ControlProvider],
    *,
    has_numerical: bool,
) -> pd.DataFrame:
    """拼接所有 Provider 的设计矩阵列。

    drop_first 策略 (design.md §5.3 共线性自动决策):
        has_numerical=True (含连续控制变量):
            - 引擎设 fit_intercept=True (调用方负责)
            - 各 categorical Provider 用 drop_first=True 避免哑变量陷阱
            - numerical Provider drop_first 不影响（单列）
        has_numerical=False (纯 categorical, 如 P1 单独 industry):
            - 引擎设 fit_intercept=True
            - 各 categorical Provider 用 drop_first=False 与 P0 逐位一致
              （sklearn pseudo-inverse 自动处理 N+1 列共线性）
    """
    parts = []
    for provider in providers:
        drop_first = has_numerical and provider.column_type == "categorical"
        cols = provider.to_design_columns(day_df, drop_first=drop_first)
        parts.append(cols)
    return pd.concat(parts, axis=1)


def neutralize(
    factor_df: pd.DataFrame,
    providers: list[ControlProvider],
    *,
    factor_col: str,
    date_col: str = "date",
    asset_col: str = "asset",
    min_count: int = 5,
    logger: Any = None,
) -> pd.DataFrame:
    """对 factor_df 按 providers 做截面 OLS 回归，返回残差因子。

    参数:
        factor_df: 必须含 [date_col, asset_col, factor_col] 列。
            上游应已合并所有 Provider 的派生列（categorical 静态列 / numerical 动态列）。
        providers: ControlProvider 实例列表（顺序仅影响 control_meta 输出顺序）
        factor_col: 因子值列名
        min_count: 单日截面最少样本数（同时也是 IndustryProvider 行业最少股票数）
        logger: 日志器

    返回:
        DataFrame[date_col, asset_col, 'neutral_factor']
        - round(6) 与 P0 industry_neutral_residual 一致
        - 行数 ≤ 输入；无效日期（小样本/全 NaN）整批跳过
        - 全部日期被过滤时返回空 DataFrame（保留契约列）

    异常:
        ValueError: providers 为空（裸 IC 应由调用方直接走 raw 路径，不应进 neutralize）
        ValueError: factor_df 缺少必要列（date/asset/factor_col 任一）
    """
    from sklearn.linear_model import LinearRegression

    if logger is None:
        logger = get_logger(__name__)

    if not providers:
        raise ValueError("neutralize: providers 不能为空 (空列表请直接走 raw IC 路径)")

    for required_col in (date_col, asset_col, factor_col):
        if required_col not in factor_df.columns:
            raise ValueError(f"neutralize: factor_df 缺少必需列 '{required_col}'; 当前列: {list(factor_df.columns)}")

    has_numerical = any(p.column_type == "numerical" for p in providers)
    fit_intercept = True  # P1 期间始终 True（与 P0 一致）；保留显式变量便于 P2+ 调整

    logger.info(
        "[neutralize] providers=%s, has_numerical=%s, fit_intercept=%s, min_count=%d",
        [p.name for p in providers],
        has_numerical,
        fit_intercept,
        min_count,
    )

    results: list[dict] = []
    skipped_days = 0

    for date, day_data in factor_df.groupby(date_col):
        # 各 Provider 串行过滤：min_count 同时作为单 Provider 的小桶门槛与
        # 总样本下限（与 P0 industry_neutral_residual 一致）
        filtered = day_data
        for provider in providers:
            filtered = provider.filter_invalid_rows(filtered, min_count=min_count, logger=logger)
            if len(filtered) < min_count:
                break

        if len(filtered) < min_count:
            skipped_days += 1
            continue

        # 设计矩阵 X
        x = _build_design_matrix(filtered, providers, has_numerical=has_numerical)
        y = filtered[factor_col]

        model = LinearRegression(fit_intercept=fit_intercept)
        model.fit(x, y)
        residual = y - model.predict(x)

        for asset, res in zip(filtered[asset_col].values, residual):
            results.append({date_col: date, asset_col: asset, "neutral_factor": round(float(res), 6)})

    if skipped_days:
        logger.info("[neutralize] %d 个日期因小样本被跳过", skipped_days)

    if not results:
        # 与 P0 一致：返回空 DataFrame 但保留契约列
        return pd.DataFrame(columns=[date_col, asset_col, "neutral_factor"])

    return pd.DataFrame(results)
