"""data_fetchers.factor_calculator.fund_flow：资金流因子（含 parquet I/O）。

⚠️ I/O 边界声明
================
本模块 **明确包含 parquet 读取**，与 ``industry_financial`` 同属"含 I/O 的
因子模块"，二者通过 ``_common.py`` 共享列名 / helper，互不依赖。

数据来源
========
``fund_flow`` 数据由 ``data_fetchers/fetch_fund_flow.py`` 拉取并写入
parquet 文件，本模块仅负责 **读取 + 计算因子**。未来若新增"北向资金流因子"，
建议在本模块下扩展，或独立建 ``northbound_flow.py``（视复杂度而定）。

公共 API（design.md §5.8）
==========================
- ``calculate_capital_flow_ratio_trend(factor_df, ...)``：主力资金净流入占比
  趋势（5 日均值）
- ``calculate_capital_flow_intensity(factor_df, ...)``：主力资金净流入强度
  （z-score）

依赖
====
- ``_common``：列名（含 ``_COL_CAPITAL_FLOW_*`` PR-4b 新增）、
  ``get_module_logger``
- ``data_fetchers.common.get_module_result_dir``：fund_flow parquet 路径
  解析（避免字符串字面量）
- ``numpy`` / ``pandas`` / ``logging`` / ``pathlib.Path``

注意事项
========
- 路径必须从 ``paths.py`` / ``common.get_module_result_dir`` 导入
- ``_load_fund_flow_data`` 含失败重抛 ``FileNotFoundError``、schema 校验等
  防御逻辑，搬运时保持原样

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
    _COL_CAPITAL_FLOW_INTENSITY,
    _COL_CAPITAL_FLOW_RATIO_TREND,
    _COL_DATE,
    _add_industry_column,
    get_module_logger,
)


# ============================================================================
# 模块私有常量
# ============================================================================

_FUND_FLOW_DATA_PATH: str | None = None  # 默认 None，调用时从 paths.py 获取

__all__: list[str] = []


def _get_fund_flow_data_path(logger_arg: logging.Logger | None = None) -> Path:
    """获取资金流数据缓存路径（遵循 paths.py 单一来源）"""
    global _FUND_FLOW_DATA_PATH
    if _FUND_FLOW_DATA_PATH is not None:
        return Path(_FUND_FLOW_DATA_PATH)
    try:
        from data_fetchers.common import get_module_result_dir
    except ImportError:
        from common import get_module_result_dir
    result_dir = get_module_result_dir()
    _FUND_FLOW_DATA_PATH = str(result_dir / "fund_flow_data.json.gz")
    return Path(_FUND_FLOW_DATA_PATH)


def _load_fund_flow_data(
    fund_flow_path: Path | str | None = None,
    logger_arg: logging.Logger | None = None,
) -> pd.DataFrame:
    """加载资金流数据缓存，返回 DataFrame

    Args:
        fund_flow_path: 资金流数据缓存路径（None 时使用默认路径）
        logger_arg: 调用方传入的 logger（可选）

    Returns:
        资金流 DataFrame，包含 asset, date, main_inflow_ratio, main_inflow_amount, total_volume 等列

    Raises:
        FileNotFoundError: 缓存文件不存在
        RuntimeError: 缓存数据为空或格式错误
    """
    _logger = get_module_logger(logger_arg)

    path = Path(fund_flow_path) if fund_flow_path else _get_fund_flow_data_path(logger_arg)
    if not path.exists():
        raise FileNotFoundError(f"资金流数据缓存不存在: {path}，请先运行 fetch_fund_flow.py")

    import gzip
    import json

    # 检测文件是否为 gzip 格式（支持 plain JSON 和 gzip 两种）
    is_gzip = True
    try:
        with gzip.open(path, "rt") as f:
            raw_data = json.load(f)
    except gzip.BadGzipFile:
        # plain JSON 格式（兼容早期写入版本）
        is_gzip = False
        with open(path) as f:
            raw_data = json.load(f)

    data_list = raw_data.get("data", [])
    if not data_list:
        raise RuntimeError(f"资金流数据缓存为空: {path}")

    df = pd.DataFrame(data_list)

    required_cols = ["asset", "date"]
    missing = [c for c in required_cols if c not in df.columns]
    if missing:
        raise RuntimeError(f"资金流数据缺少必需列: {missing}")

    del raw_data, data_list
    import gc

    gc.collect()

    _logger.info("加载资金流数据: %d 条记录, %d 只股票", len(df), len(set(df["asset"])))
    return df


def _merge_fund_flow_daily(
    factor_df: pd.DataFrame,
    fund_flow_df: pd.DataFrame,
    value_col: str,
    output_col: str,
    logger_arg: logging.Logger | None = None,
) -> pd.Series:
    """合并日频资金流数据到因子 DataFrame

    Args:
        factor_df: 日频因子 DataFrame（含 date, asset 列）
        fund_flow_df: 资金流 DataFrame（含 asset, date, value_col 列）
        value_col: 资金流数据中的值列名
        output_col: 输出列名
        logger_arg: logger（可选）

    Returns:
        与 factor_df 行数对齐的 Series
    """
    _logger = get_module_logger(logger_arg)

    # 日期格式对齐
    ff_subset = fund_flow_df[["asset", "date", value_col]].copy()
    ff_subset["date"] = ff_subset["date"].astype(str)

    # 精确匹配（资金流数据是日频，无需 merge_asof）
    merged = factor_df[[_COL_DATE, _COL_ASSET]].copy()
    merged[_COL_DATE] = merged[_COL_DATE].astype(str)

    result = merged.merge(
        ff_subset,
        left_on=[_COL_DATE, _COL_ASSET],
        right_on=["date", "asset"],
        how="left",
    )[value_col].rename(output_col)

    return result


def calculate_capital_flow_ratio_trend(
    factor_df: pd.DataFrame,
    *,
    fund_flow_path: str | Path | None = None,
    logger_arg: logging.Logger | None = None,
) -> pd.DataFrame:
    """计算资金流占比趋势因子（行业主力净流入占比Δ赋个股）

    公式:
      1. 加载资金流数据 → main_inflow_ratio per (asset, date)
      2. 精确匹配日频数据到 factor_df（资金流数据已是日频，无需前推填充）
      3. Δratio = main_inflow_ratio(current) - main_inflow_ratio(previous)（按 asset 分组 shift(1)）
      4. groupby(industry, date) → mean(Δratio) → 赋给同行业每只个股

    含义:
      - 高正值: 行业主力资金持续流入（净流入占比上升）
      - 高负值: 行业主力资金持续流出（净流入占比下降）
      - 近零值: 行业资金流向稳定

    边界处理:
      - industry 未知 → 赋 '其他'
      - 资金流数据缺失 → Δratio 为 NaN
      - 资金流数据约120交易日（API限制），超过此范围的日期 → NaN
      - Δratio 首日无前值 → NaN

    ⚠️ 数据覆盖限制: 每只股票约120交易日，早期日期必然缺失

    遵循 H5: IC方向不预判

    required_cols: ["date", "asset"]
    """
    _logger = get_module_logger(logger_arg)

    df = factor_df.copy()

    # Step 1: 加载资金流数据
    _logger.info("  Step 1: 加载资金流数据...")
    fund_flow_df = _load_fund_flow_data(fund_flow_path, logger_arg)

    # Step 2: 合并日频资金流数据
    _logger.info("  Step 2: 合并主力净流入占比到因子数据...")
    ratio_daily = _merge_fund_flow_daily(df, fund_flow_df, "main_inflow_ratio", "ratio_daily", logger_arg)
    df["ratio_daily"] = ratio_daily.values if len(ratio_daily) == len(df) else [float("nan")] * len(df)

    # Step 3: 计算 Δratio = ratio(current) - ratio(previous)
    _logger.info("  Step 3: 计算Δ主力净流入占比...")
    df = df.sort_values([_COL_ASSET, _COL_DATE])
    prev_ratio = df.groupby(_COL_ASSET)["ratio_daily"].shift(1)
    df["delta_ratio"] = df["ratio_daily"] - prev_ratio

    # Step 4: 添加 industry 列
    _logger.info("  Step 4: 添加行业分类列...")
    df = _add_industry_column(df, _logger)

    # Step 5: 行业聚合赋个股
    _logger.info("  Step 5: 行业Δ主力净流入占比赋给个股...")
    industry_delta_ratio = df.groupby(["industry", _COL_DATE])["delta_ratio"].mean().reset_index()
    trend_map = industry_delta_ratio.set_index(["industry", _COL_DATE])["delta_ratio"]

    df[_COL_CAPITAL_FLOW_RATIO_TREND] = df.set_index(["industry", _COL_DATE]).index.map(
        lambda idx: trend_map.get(idx, float("nan"))
    )

    # 删除中间列
    df = df.drop(columns=["ratio_daily", "delta_ratio"])

    valid_count = int(df[_COL_CAPITAL_FLOW_RATIO_TREND].notna().sum())
    _logger.info(
        "  有效 %s: %d (%.2f%%)",
        _COL_CAPITAL_FLOW_RATIO_TREND,
        valid_count,
        valid_count / len(df) * 100 if len(df) > 0 else 0,
    )

    return df


calculate_capital_flow_ratio_trend.required_cols = ["date", "asset"]  # type: ignore[attr-defined]


def calculate_capital_flow_intensity(
    factor_df: pd.DataFrame,
    *,
    fund_flow_path: str | Path | None = None,
    logger_arg: logging.Logger | None = None,
) -> pd.DataFrame:
    """计算资金流强度因子（行业主力流入绝对额占比赋个股）

    公式:
      1. 加载资金流数据 → main_inflow_amount, total_volume per (asset, date)
      2. intensity = |main_inflow_amount| / total_volume（主力流入占成交额的绝对比例）
      3. 精确匹配日频数据到 factor_df
      4. groupby(industry, date) → mean(intensity) → 赋给同行业每只个股

    含义:
      - 高值: 行业主力资金活跃度高（主力参与成交的比例大）
      - 低值: 行业主力资金活跃度低（散户主导，主力参与少）
      - 0值: 行业无主力资金流入流出

    边界处理:
      - industry 未知 → 赋 '其他'
      - total_volume = 0 或 NaN → intensity = NaN（除零保护）
      - 资金流数据约120交易日（API限制），超过此范围 → NaN

    ⚠️ 数据覆盖限制: 同 capital_flow_ratio_trend
    ⚠️ 比率型因子: 分母 total_volume 可能为零 → NaN 处理

    遵循 H5: IC方向不预判

    required_cols: ["date", "asset"]
    """
    _logger = get_module_logger(logger_arg)

    df = factor_df.copy()

    # Step 1: 加载资金流数据
    _logger.info("  Step 1: 加载资金流数据...")
    fund_flow_df = _load_fund_flow_data(fund_flow_path, logger_arg)

    # Step 2: 计算 intensity = |main_inflow_amount| / total_volume
    _logger.info("  Step 2: 计算资金流强度...")
    # 先合并 main_inflow_amount 和 total_volume
    amount_daily = _merge_fund_flow_daily(df, fund_flow_df, "main_inflow_amount", "amount_daily", logger_arg)
    volume_daily = _merge_fund_flow_daily(df, fund_flow_df, "total_volume", "volume_daily", logger_arg)
    df["amount_daily"] = amount_daily.values if len(amount_daily) == len(df) else [float("nan")] * len(df)
    df["volume_daily"] = volume_daily.values if len(volume_daily) == len(df) else [float("nan")] * len(df)

    # intensity = |main_inflow_amount| / total_volume
    df["intensity"] = df["amount_daily"].abs() / df["volume_daily"]
    # total_volume = 0 或 NaN → intensity = NaN
    df.loc[df["volume_daily"] == 0, "intensity"] = float("nan")
    df.loc[df["volume_daily"].isna(), "intensity"] = float("nan")
    df.loc[df["amount_daily"].isna(), "intensity"] = float("nan")

    # Step 3: 添加 industry 列
    _logger.info("  Step 3: 添加行业分类列...")
    df = _add_industry_column(df, _logger)

    # Step 4: 行业聚合赋个股
    _logger.info("  Step 4: 行业资金流强度赋给个股...")
    industry_intensity = df.groupby(["industry", _COL_DATE])["intensity"].mean().reset_index()
    trend_map = industry_intensity.set_index(["industry", _COL_DATE])["intensity"]

    df[_COL_CAPITAL_FLOW_INTENSITY] = df.set_index(["industry", _COL_DATE]).index.map(
        lambda idx: trend_map.get(idx, float("nan"))
    )

    # 删除中间列
    df = df.drop(columns=["amount_daily", "volume_daily", "intensity"])

    valid_count = int(df[_COL_CAPITAL_FLOW_INTENSITY].notna().sum())
    _logger.info(
        "  有效 %s: %d (%.2f%%)",
        _COL_CAPITAL_FLOW_INTENSITY,
        valid_count,
        valid_count / len(df) * 100 if len(df) > 0 else 0,
    )

    return df


calculate_capital_flow_intensity.required_cols = ["date", "asset"]  # type: ignore[attr-defined]
