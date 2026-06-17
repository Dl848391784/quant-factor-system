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

import functools
import logging
from pathlib import Path

import pandas as pd

from ._common import (
    _COL_ASSET,
    _COL_CAPITAL_FLOW_INTENSITY,
    _COL_CAPITAL_FLOW_RATIO_TREND,
    _COL_DATE,
    get_module_logger,
)
from ._industry_helpers import _add_industry_column


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

    Note (v1.44 内存优化):
        - 默认路径（fund_flow_path=None）走 process-local cache，同一进程内
          重复调用直接返回同一 DataFrame 对象（id 相等），消除 Step 11.9 内的
          重复 gzip 解压 + json.load + DataFrame 构造（1.49M 行级浪费）。
        - 自定义路径（fund_flow_path 非 None）不走 cache，保持外部测试可控性。
        - 进程结束 / 显式调用 ``_load_fund_flow_data_cached.cache_clear()`` 释放。
    """
    if fund_flow_path is None:
        # 默认路径：走 cache（同 PID 内文件不变）
        return _load_fund_flow_data_cached()
    # 自定义路径：不走 cache（外部测试 / 历史回放可指定不同文件）
    return _load_fund_flow_data_uncached(Path(fund_flow_path), logger_arg)


@functools.lru_cache(maxsize=1)
def _load_fund_flow_data_cached() -> pd.DataFrame:
    """默认路径下的 process-local cache 包装（v1.44 内存优化）。

    cache key 为空（无参），同 PID 内首次加载后所有后续调用直接返回缓存对象。
    pipeline 末尾应调用 ``_load_fund_flow_data_cached.cache_clear()`` 释放内存。
    """
    return _load_fund_flow_data_uncached(_get_fund_flow_data_path(), None)


def _load_fund_flow_data_uncached(
    path: Path,
    logger_arg: logging.Logger | None,
) -> pd.DataFrame:
    """实际的 gzip + json + DataFrame 加载逻辑（无 cache 包装）。"""
    _logger = get_module_logger(logger_arg)

    if not path.exists():
        raise FileNotFoundError(f"资金流数据缓存不存在: {path}，请先运行 fetch_fund_flow.py")

    import gzip
    import json

    # 检测文件是否为 gzip 格式（支持 plain JSON 和 gzip 两种）
    try:
        with gzip.open(path, "rt") as f:
            raw_data = json.load(f)
    except gzip.BadGzipFile:
        # plain JSON 格式（兼容早期写入版本）
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


def _merge_fund_flow_daily_multi(
    factor_df: pd.DataFrame,
    fund_flow_df: pd.DataFrame,
    value_cols: list[str],
    logger_arg: logging.Logger | None = None,
) -> pd.DataFrame:
    """合并日频资金流数据到因子 DataFrame（一次返回多列）。

    v1.44 内存优化：将原先 N 次单列 merge（每次 1.49M 行 left_merge）合并为
    单次多列 merge，减少中间表构造次数。

    Args:
        factor_df: 日频因子 DataFrame（含 date, asset 列）
        fund_flow_df: 资金流 DataFrame（含 asset, date, value_cols 列）
        value_cols: 资金流数据中的值列名列表（一次取多列）
        logger_arg: logger（可选）

    Returns:
        与 factor_df 行数对齐的 DataFrame，包含 value_cols 中所有列。
        未匹配行所有 value_cols 列均为 NaN。

    Note:
        - 行序与 factor_df 严格一致（merge how="left"，single-key match 不重排）
        - 输出 DataFrame 不含 date / asset 列，仅包含 value_cols
    """
    _logger = get_module_logger(logger_arg)

    # 一次性取出所有需要的值列 + 合并键
    ff_subset = fund_flow_df[["asset", "date", *value_cols]].copy()
    ff_subset["date"] = ff_subset["date"].astype(str)

    merged = factor_df[[_COL_DATE, _COL_ASSET]].copy()
    merged[_COL_DATE] = merged[_COL_DATE].astype(str)

    # 单次 left_merge 同时拿到所有 value_cols
    merged_full = merged.merge(
        ff_subset,
        left_on=[_COL_DATE, _COL_ASSET],
        right_on=["date", "asset"],
        how="left",
    )
    # value_cols 是 list[str]，索引必返回 DataFrame；显式构造避开 Pyright 联合类型推断
    result = pd.DataFrame(merged_full[value_cols])

    _logger.debug(
        "_merge_fund_flow_daily_multi: rows=%d, value_cols=%s",
        len(result),
        value_cols,
    )
    return result


def _merge_fund_flow_daily(
    factor_df: pd.DataFrame,
    fund_flow_df: pd.DataFrame,
    value_col: str,
    output_col: str,
    logger_arg: logging.Logger | None = None,
) -> pd.Series:
    """合并日频资金流数据到因子 DataFrame（单列版，thin wrapper 维持外部 API）。

    Args:
        factor_df: 日频因子 DataFrame（含 date, asset 列）
        fund_flow_df: 资金流 DataFrame（含 asset, date, value_col 列）
        value_col: 资金流数据中的值列名
        output_col: 输出列名
        logger_arg: logger（可选）

    Returns:
        与 factor_df 行数对齐的 Series

    Note (v1.44):
        本函数现在是 ``_merge_fund_flow_daily_multi`` 的单列 thin wrapper，
        保持原签名以维持外部测试 / 历史调用方的兼容性。新代码应直接调用
        multi 版以批量合并多列。
    """
    multi_result = _merge_fund_flow_daily_multi(factor_df, fund_flow_df, [value_col], logger_arg)
    # multi_result 单列 DataFrame；取出 Series 后改名（Pyright 友好的 iloc 写法）
    series = multi_result.iloc[:, 0]
    series.name = output_col
    return series


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


# ============================================================================
# v1.44 内存优化：pipeline 专用 orchestrator
# ============================================================================


def calculate_capital_flow_block(
    factor_df: pd.DataFrame,
    *,
    fund_flow_path: str | Path | None = None,
    logger_arg: logging.Logger | None = None,
) -> pd.DataFrame:
    """资金流双因子合并 orchestrator（pipeline 专用，v1.44 OOM 治理）。

    一次性产出 ``capital_flow_ratio_trend`` + ``capital_flow_intensity`` 两个因子。
    与依次调用 ``calculate_capital_flow_ratio_trend`` + ``calculate_capital_flow_intensity``
    数值等价，但内存占用大幅下降：

    优化点（对比两次独立调用）：
      1. fund_flow 数据只 load 一次（lru_cache 命中 + 单次 multi-merge 取 3 列）
      2. industry 列只添加一次（_add_industry_column 已 idempotent）
      3. 行业聚合用 vectorized merge 替代 ``set_index().index.map(lambda)``
         （消除 1.49M 次 python lambda dict lookup）
      4. 中间列 (ratio_daily/delta_ratio/amount_daily/volume_daily/intensity)
         在 block 内完成生命周期，return 前 del + 不污染 factor_df

    数学等价性：
      - capital_flow_ratio_trend：步骤与 calculate_capital_flow_ratio_trend 一致
        （shift(1) → groupby(industry,date).mean）
      - capital_flow_intensity：步骤与 calculate_capital_flow_intensity 一致
        （|amount|/volume 含三重 NaN 守卫 → groupby(industry,date).mean）

    Args:
        factor_df: 因子表（含 date, asset 列）
        fund_flow_path: 资金流缓存路径（None=默认走 lru_cache）
        logger_arg: logger（可选）

    Returns:
        factor_df + ``capital_flow_ratio_trend`` + ``capital_flow_intensity`` 两列。

    required_cols: ``[\"date\", \"asset\"]``
    """
    _logger = get_module_logger(logger_arg)

    df = factor_df.copy()

    # Step 1: 加载资金流数据（默认路径走 lru_cache）
    _logger.info("  Step 1: 加载资金流数据 (orchestrator)...")
    fund_flow_df = _load_fund_flow_data(fund_flow_path, logger_arg)

    # Step 2: 单次 multi-merge 取 3 列（替代 3 次单列 left_merge）
    _logger.info("  Step 2: 单次 multi-merge 主力净流入占比/金额 + 总成交额...")
    merged_cols = _merge_fund_flow_daily_multi(
        df,
        fund_flow_df,
        ["main_inflow_ratio", "main_inflow_amount", "total_volume"],
        logger_arg,
    )
    df["ratio_daily"] = merged_cols["main_inflow_ratio"].to_numpy()
    df["amount_daily"] = merged_cols["main_inflow_amount"].to_numpy()
    df["volume_daily"] = merged_cols["total_volume"].to_numpy()
    del merged_cols  # 大对象立即释放（MODULE.md R16）

    # Step 3: 添加 industry 列（idempotent，只跑一次）
    _logger.info("  Step 3: 添加行业分类列...")
    df = _add_industry_column(df, _logger)

    # Step 4: 计算 Δratio = ratio(current) - ratio(previous)（按 asset 排序后 shift）
    _logger.info("  Step 4: 计算 Δ主力净流入占比 + intensity...")
    df = df.sort_values([_COL_ASSET, _COL_DATE])
    df["delta_ratio"] = df["ratio_daily"] - df.groupby(_COL_ASSET)["ratio_daily"].shift(1)

    # Step 5: 计算 intensity = |amount| / volume（含三重 NaN 守卫）
    df["intensity"] = df["amount_daily"].abs() / df["volume_daily"]
    df.loc[df["volume_daily"] == 0, "intensity"] = float("nan")
    df.loc[df["volume_daily"].isna(), "intensity"] = float("nan")
    df.loc[df["amount_daily"].isna(), "intensity"] = float("nan")

    # Step 6: 行业聚合 — 一次 groupby 同时算两因子（vectorized merge 赋回个股）
    _logger.info("  Step 6: 行业聚合（vectorized merge 赋个股）...")
    industry_agg = (
        df.groupby(["industry", _COL_DATE])
        .agg(
            **{
                _COL_CAPITAL_FLOW_RATIO_TREND: ("delta_ratio", "mean"),
                _COL_CAPITAL_FLOW_INTENSITY: ("intensity", "mean"),
            }
        )
        .reset_index()
    )

    # 用 left_merge 替代 set_index().index.map(lambda)（消除 1.49M python lookup）
    df = df.merge(industry_agg, on=["industry", _COL_DATE], how="left")
    del industry_agg

    # Step 7: 清理中间列（保两个最终因子）
    df = df.drop(columns=["ratio_daily", "delta_ratio", "amount_daily", "volume_daily", "intensity"])

    # 日志：两因子有效率
    n = len(df)
    for col in (_COL_CAPITAL_FLOW_RATIO_TREND, _COL_CAPITAL_FLOW_INTENSITY):
        col_series = df.loc[:, col]
        valid = int(col_series.notna().sum())
        _logger.info("  有效 %s: %d (%.2f%%)", col, valid, valid / n * 100 if n > 0 else 0.0)

    return df


calculate_capital_flow_block.required_cols = ["date", "asset"]  # type: ignore[attr-defined]
