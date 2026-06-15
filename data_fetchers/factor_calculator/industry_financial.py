"""data_fetchers.factor_calculator.industry_financial：行业基本面因子（含 parquet I/O）。

⚠️ I/O 边界声明
================
本模块 **明确包含 parquet 读取**，与 ``_common`` / ``basic`` / ``momentum`` /
``delta`` / ``volume_price`` / ``industry`` 的"纯计算"语义不同。这是把
"行业聚合纯计算"与"行业基本面 I/O"分离的关键意义所在 —— 未来若要 mock
financial 数据做测试，只需 mock ``_load_financial_data``，``industry.py``
完全不受影响。

公共 API（design.md §5.7）
==========================
- ``calculate_industry_roe_trend(factor_df, ...)``：行业 ROE 趋势（行业内
  ROE 中位数 5 日变化）
- ``calculate_industry_earnings_growth(factor_df, ...)``：行业利润同比增速
  （行业内 EPS 同比中位数）
- ``calculate_industry_pe_trend(factor_df, ...)``：行业 PE 趋势（行业内
  PE 中位数 5 日变化）

依赖
====
- ``_common``：列名、``_add_industry_column`` helper、``get_module_logger``
- ``data_fetchers.common.get_module_result_dir``：财务 parquet 路径解析（避免
  字符串字面量；遵循 AGENTS.md 规则 #11）
- ``numpy`` / ``pandas`` / ``logging`` / ``pathlib.Path``

注意事项
========
- 路径必须从 ``paths.py`` / ``common.get_module_result_dir`` 导入；禁止字符串
  字面量
- ``_load_financial_data`` 含失败重抛 ``FileNotFoundError``、schema 校验等
  防御逻辑，搬运时保持原样（design.md §3.2 N1：不重写）
- ``_PE_DENOMINATOR_MIN = 0.01`` 是本子模块独有常量（PE 比率型因子分母保护，
  遵循 Pitfall #47），随函数一起搬，不进 _common.py

兼容性
======
本模块函数实现与原 ``factor_calculator.py`` v1.17 字节级一致；PR-4b 通过
``temporary/factor_calculator_baseline_fingerprint.json`` 的 22 个因子
指纹验证。
"""

from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd

from ._common import (
    _COL_ASSET,
    _COL_CLOSE,
    _COL_DATE,
    _COL_INDUSTRY_EARNINGS_GROWTH,
    _COL_INDUSTRY_PE_TREND,
    _COL_INDUSTRY_ROE_TREND,
    _add_industry_column,
    get_module_logger,
)


# ============================================================================
# 模块私有常量
# ============================================================================

_FINANCIAL_DATA_PATH: str | None = None  # 默认 None，调用时从 paths.py 获取

# PE 比率型因子分母保护（遵循 Pitfall #47）
_PE_DENOMINATOR_MIN = 0.01  # EPS 年化值 clip 下限

__all__: list[str] = []


def _get_financial_data_path(logger_arg: logging.Logger | None = None) -> Path:
    """获取财务数据缓存路径（遵循 paths.py 单一来源）

    Returns:
        财务数据缓存文件路径
    """
    global _FINANCIAL_DATA_PATH
    if _FINANCIAL_DATA_PATH is not None:
        return Path(_FINANCIAL_DATA_PATH)
    try:
        from data_fetchers.common import get_module_result_dir
    except ImportError:
        from common import get_module_result_dir
    result_dir = get_module_result_dir()
    _FINANCIAL_DATA_PATH = str(result_dir / "financial_data.json.gz")
    return Path(_FINANCIAL_DATA_PATH)


def _load_financial_data(
    financial_data_path: Path | str | None = None,
    logger_arg: logging.Logger | None = None,
) -> pd.DataFrame:
    """加载财务数据缓存，返回 DataFrame（asset, report_date, roe, eps, ...）

    Args:
        financial_data_path: 财务数据缓存路径（None 时使用默认路径）
        logger_arg: 调用方传入的 logger（可选）

    Returns:
        财务数据 DataFrame，包含 asset, report_date, roe, basic_eps, annualized_eps 等列

    Raises:
        FileNotFoundError: 缓存文件不存在
        RuntimeError: 缓存数据为空或格式错误
    """
    _logger = get_module_logger(logger_arg)

    path = Path(financial_data_path) if financial_data_path else _get_financial_data_path(logger_arg)
    if not path.exists():
        raise FileNotFoundError(f"财务数据缓存不存在: {path}，请先运行 fetch_financial.py")

    import gzip
    import json

    with gzip.open(path, "rt") as f:
        raw_data = json.load(f)

    data_list = raw_data.get("data", [])
    if not data_list:
        raise RuntimeError(f"财务数据缓存为空: {path}")

    df = pd.DataFrame(data_list)

    # 确保关键列存在
    required_cols = ["asset", "report_date"]
    missing = [c for c in required_cols if c not in df.columns]
    if missing:
        raise RuntimeError(f"财务数据缺少必需列: {missing}")

    # 显式释放 JSON 原始数据（遵循 R16）
    del raw_data, data_list
    import gc

    gc.collect()

    _logger.info("加载财务数据: %d 条记录, %d 只股票", len(df), len(set(df["asset"])))
    return df


def _merge_asof_financial(
    factor_df: pd.DataFrame,
    financial_df: pd.DataFrame,
    value_col: str,
    output_col: str,
    logger_arg: logging.Logger | None = None,
) -> pd.Series:
    """前推填充对齐季度财务数据到日频（merge_asof 模式）

    Args:
        factor_df: 日频因子 DataFrame（含 date, asset 列）
        financial_df: 季度财务 DataFrame（含 asset, report_date, value_col 列）
        value_col: 财务数据中的值列名（如 'roe', 'basic_eps'）
        output_col: 输出到 factor_df 的列名（如 'roe_daily', 'eps_daily'）
        logger_arg: logger（可选）

    Returns:
        与 factor_df 行数对齐的 Series，前推填充的财务值

    Note: 使用 pd.merge_asof(direction='backward') 实现 point-forward fill
    """
    _logger = get_module_logger(logger_arg)

    # 准备合并所需的数据
    fin_subset = financial_df[["asset", "report_date", value_col]].copy()
    fin_subset = fin_subset.rename(columns={"report_date": "date"})
    fin_subset["date"] = pd.to_datetime(fin_subset["date"])

    # 确保 factor_df 的 date 列是 datetime 类型
    daily_dates = pd.to_datetime(factor_df[_COL_DATE])

    # merge_asof: 交易日取最近已发布的财报数据（前推填充）
    merged = pd.merge_asof(
        factor_df[[_COL_ASSET]].assign(date=daily_dates).sort_values("date"),
        fin_subset.sort_values("date"),
        by=_COL_ASSET,
        on="date",
        direction="backward",  # Point-forward: 取最近已发布的财报
    )

    return merged[value_col].rename(output_col)


def calculate_industry_roe_trend(
    factor_df: pd.DataFrame,
    *,
    financial_data_path: str | Path | None = None,
    logger_arg: logging.Logger | None = None,
) -> pd.DataFrame:
    """计算行业ROE趋势因子（行业ΔROE赋个股）

    公式:
      1. 加载季度财务数据 → ROE per (asset, report_date)
      2. Point-forward fill → 对齐日频 (merge_asof direction='backward')
      3. ΔROE = ROE(current_quarter) - ROE(previous_quarter)（按 asset 分组 shift）
      4. groupby(industry, date) → mean(ΔROE) → 赋给同行业每只个股

    含义:
      - 高正值: 行业盈利能力改善（ROE上升趋势）
      - 高负值: 行业盈利能力恶化（ROE下降趋势）
      - 近零值: 行业盈利能力稳定

    边界处理:
      - industry 未知 → 赋 '其他'
      - 财务数据缺失 → ΔROE 为 NaN（自然排除）
      - ROE 前推填充: 首日无前值 → NaN（不做填充）
      - ΔROE = NaN → 行业均值自动跳过（pandas mean NaN-safe）

    遵循 H5: IC方向不预判
    预期: 行业基本面改善 → IC正向（偏好盈利改善的行业）

    required_cols: ["date", "asset"]
    """
    _logger = get_module_logger(logger_arg)

    df = factor_df.copy()

    # Step 1: 加载财务数据
    _logger.info("  Step 1: 加载季度财务数据...")
    financial_df = _load_financial_data(financial_data_path, logger_arg)

    # Step 2: 前推填充对齐日频
    _logger.info("  Step 2: 前推填充ROE对齐日频...")
    roe_daily = _merge_asof_financial(df, financial_df, "roe", "roe_daily", logger_arg)
    # ⚠️ 类型修复: 同花顺 API 返回的 roe 可能是 Decimal 类型，必须转为 float
    df["roe_daily"] = pd.to_numeric(roe_daily, errors="coerce")

    # Step 3: 计算 ΔROE = ROE(current_quarter) - ROE(previous_quarter)
    _logger.info("  Step 3: 计算ΔROE（季度间变化）...")
    df = df.sort_values([_COL_ASSET, _COL_DATE])
    prev_roe = df.groupby(_COL_ASSET)["roe_daily"].shift(1)
    df["delta_roe"] = df["roe_daily"] - prev_roe
    # 首日无前值 → NaN（自然排除，不做填充）

    # Step 4: 添加 industry 列
    _logger.info("  Step 4: 添加行业分类列...")
    df = _add_industry_column(df, _logger)

    # Step 5: 行业聚合赋个股
    _logger.info("  Step 5: 行业ΔROE赋给个股...")
    industry_delta_roe = df.groupby(["industry", _COL_DATE])["delta_roe"].mean().reset_index()
    trend_map = industry_delta_roe.set_index(["industry", _COL_DATE])["delta_roe"]

    df[_COL_INDUSTRY_ROE_TREND] = df.set_index(["industry", _COL_DATE]).index.map(
        lambda idx: trend_map.get(idx, float("nan"))
    )

    # 删除中间列
    df = df.drop(columns=["roe_daily", "delta_roe"])

    valid_count = int(df[_COL_INDUSTRY_ROE_TREND].notna().sum())
    _logger.info(
        "  有效 %s: %d (%.2f%%)",
        _COL_INDUSTRY_ROE_TREND,
        valid_count,
        valid_count / len(df) * 100 if len(df) > 0 else 0,
    )

    return df


calculate_industry_roe_trend.required_cols = ["date", "asset"]  # type: ignore[attr-defined]


def calculate_industry_earnings_growth(
    factor_df: pd.DataFrame,
    *,
    financial_data_path: str | Path | None = None,
    logger_arg: logging.Logger | None = None,
) -> pd.DataFrame:
    """计算行业盈利增长因子（行业净利润增长率赋个股）

    公式:
      1. 加载季度财务数据 → net_profit_growth_yoy per (asset, report_date)
      2. Point-forward fill → 对齐日频 (merge_asof direction='backward')
      3. groupby(industry, date) → mean(net_profit_growth_yoy) → 赋给同行业每只个股

    含义:
      - 高正值: 行业盈利高增长（净利润同比增速大）
      - 高负值: 行业盈利下滑（净利润同比增速为负）
      - 近零值: 行业盈利平稳

    边界处理:
      - industry 未知 → 赋 '其他'
      - 财务数据缺失 → NaN（自然排除）
      - 银行/金融股净利润增长率可能为 NaN（会计差异，正常现象）

    遵循 H5: IC方向不预判

    required_cols: ["date", "asset"]
    """
    _logger = get_module_logger(logger_arg)

    df = factor_df.copy()

    # Step 1: 加载财务数据
    _logger.info("  Step 1: 加载季度财务数据...")
    financial_df = _load_financial_data(financial_data_path, logger_arg)

    # Step 2: 前推填充对齐日频
    _logger.info("  Step 2: 前推填充净利润增长率对齐日频...")
    growth_daily = _merge_asof_financial(df, financial_df, "net_profit_growth_yoy", "growth_daily", logger_arg)
    # ⚠️ 类型修复: 同花顺 API 返回的 net_profit_growth_yoy 可能是 Decimal 类型，必须转为 float
    df["growth_daily"] = pd.to_numeric(growth_daily, errors="coerce")

    # Step 3: 添加 industry 列
    _logger.info("  Step 3: 添加行业分类列...")
    df = _add_industry_column(df, _logger)

    # Step 4: 行业聚合赋个股
    _logger.info("  Step 4: 行业净利润增长率赋给个股...")
    industry_growth = df.groupby(["industry", _COL_DATE])["growth_daily"].mean().reset_index()
    trend_map = industry_growth.set_index(["industry", _COL_DATE])["growth_daily"]

    df[_COL_INDUSTRY_EARNINGS_GROWTH] = df.set_index(["industry", _COL_DATE]).index.map(
        lambda idx: trend_map.get(idx, float("nan"))
    )

    # 删除中间列
    df = df.drop(columns=["growth_daily"])

    valid_count = int(df[_COL_INDUSTRY_EARNINGS_GROWTH].notna().sum())
    _logger.info(
        "  有效 %s: %d (%.2f%%)",
        _COL_INDUSTRY_EARNINGS_GROWTH,
        valid_count,
        valid_count / len(df) * 100 if len(df) > 0 else 0,
    )

    return df


calculate_industry_earnings_growth.required_cols = ["date", "asset"]  # type: ignore[attr-defined]


def calculate_industry_pe_trend(
    factor_df: pd.DataFrame,
    *,
    financial_data_path: str | Path | None = None,
    logger_arg: logging.Logger | None = None,
) -> pd.DataFrame:
    """计算行业PE趋势因子（行业ΔPE赋个股）

    公式:
      1. 加载季度财务数据 → annualized_eps per (asset, report_date)
      2. Point-forward fill → 对齐日频 (merge_asof direction='backward')
      3. PE = close / annualized_eps（分母 clip 保护，遵循 Pitfall #47）
      4. ΔPE = PE(current_quarter) - PE(previous_quarter)（按 asset 分组 shift）
      5. groupby(industry, date) → mean(ΔPE) → 赋给同行业每只个股

    含义:
      - 高正值: 行业估值上升（PE上升趋势，市场给予更高估值）
      - 高负值: 行业估值下降（PE下降趋势，市场降低估值）
      - 近零值: 行业估值稳定

    边界处理:
      - industry 未知 → 赋 '其他'
      - annualized_eps 缺失 → PE = NaN
      - annualized_eps 极小 → clip(lower=0.01) 保护（遵循 Pitfall #47）
      - annualized_eps ≤ 0 → PE = NaN（亏损公司 PE 无意义）
      - PE 首日无前值 → ΔPE = NaN

    ⚠️ 比率型因子: 分母 annualized_eps 可能趋近零 → clip(lower=0.01) 保护
    ⚠️ 亏损公司（eps≤0）PE为负，趋势仍有意义但需特殊处理

    遵循 H5: IC方向不预判

    required_cols: ["date", "asset", "close"]
    """
    _logger = get_module_logger(logger_arg)

    df = factor_df.copy()

    # Step 1: 加载财务数据
    _logger.info("  Step 1: 加载季度财务数据...")
    financial_df = _load_financial_data(financial_data_path, logger_arg)

    # Step 2: 前推填充对齐日频
    _logger.info("  Step 2: 前推填充年化EPS对齐日频...")
    eps_daily = _merge_asof_financial(df, financial_df, "annualized_eps", "eps_daily", logger_arg)
    # ⚠️ 类型修复: 同花顺 API 返回的 annualized_eps 可能是 Decimal 类型
    # Decimal 除 float 会报 TypeError，必须先转为 float
    df["eps_daily"] = pd.to_numeric(eps_daily, errors="coerce")

    # Step 3: 计算 PE = close / annualized_eps
    _logger.info("  Step 3: 计算PE（比率型因子，分母clip保护）...")
    eps_safe = df["eps_daily"].clip(lower=_PE_DENOMINATOR_MIN)
    df["pe_daily"] = df[_COL_CLOSE] / eps_safe
    # annualized_eps ≤ 0（亏损公司）→ PE = NaN（负PE趋势意义存疑，排除）
    df.loc[df["eps_daily"] <= 0, "pe_daily"] = float("nan")
    # annualized_eps 原值为 NaN → PE = NaN
    df.loc[df["eps_daily"].isna(), "pe_daily"] = float("nan")

    # Step 4: 计算 ΔPE = PE(current) - PE(previous)
    _logger.info("  Step 4: 计算ΔPE（季度间变化）...")
    df = df.sort_values([_COL_ASSET, _COL_DATE])
    prev_pe = df.groupby(_COL_ASSET)["pe_daily"].shift(1)
    df["delta_pe"] = df["pe_daily"] - prev_pe

    # Step 5: 添加 industry 列
    _logger.info("  Step 5: 添加行业分类列...")
    df = _add_industry_column(df, _logger)

    # Step 6: 行业聚合赋个股
    _logger.info("  Step 6: 行业ΔPE赋给个股...")
    industry_delta_pe = df.groupby(["industry", _COL_DATE])["delta_pe"].mean().reset_index()
    trend_map = industry_delta_pe.set_index(["industry", _COL_DATE])["delta_pe"]

    df[_COL_INDUSTRY_PE_TREND] = df.set_index(["industry", _COL_DATE]).index.map(
        lambda idx: trend_map.get(idx, float("nan"))
    )

    # 删除中间列
    df = df.drop(columns=["eps_daily", "pe_daily", "delta_pe"])

    valid_count = int(df[_COL_INDUSTRY_PE_TREND].notna().sum())
    _logger.info(
        "  有效 %s: %d (%.2f%%)",
        _COL_INDUSTRY_PE_TREND,
        valid_count,
        valid_count / len(df) * 100 if len(df) > 0 else 0,
    )

    return df


calculate_industry_pe_trend.required_cols = ["date", "asset", "close"]  # type: ignore[attr-defined]
