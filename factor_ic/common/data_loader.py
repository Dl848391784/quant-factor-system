#!/usr/bin/env python3
"""
通用数据加载模块 - factor_ic 公共模块

功能：
1. 加载缓存数据（gzip + JSON）
2. 日期类型统一转换（YYYY-MM-DD）
3. 列存在验证（显示可用列）
4. dropna 前记录 raw_metadata
5. dropna 过滤缺失值
6. 从单文件提取收益数据

数据来源（2026-05-31重构，单文件模式）：
- 统一数据源：data_fetchers/result/factor_ic_data.json.gz
- 包含：行情数据 + 基础因子 + 扩展因子 + 收益数据（forward_return_1d/3d/5d）
- 删除冗余文件：return_data.json.gz（收益已内置于 factor_ic_data.json.gz）

日志精确化规范（2026-05-28）：
- gzip.open + json.load 添加 try/except 捕获 BadGzipFile/JSONDecodeError/OSError
- _convert_date_column 无效日期时补充 logger.error 记录数据名称和示例

作者: 云瑶
日期: 2026-05-22
最后修改: 2026-05-31（重构为单文件模式，删除双文件加载逻辑）
"""

import gzip
import json
from pathlib import Path

import pandas as pd

from .logger_config import get_logger


# ============================================================================
# 默认路径配置（遵循 PROJECT.md 跨模块数据路径规范）
# ============================================================================
# 统一数据源：data_fetchers/result/factor_ic_data.json.gz
# 包含：行情数据 + 基础因子 + 扩展因子 + 收益数据（forward_return_1d/3d/5d）
DEFAULT_DATA_DIR = Path(__file__).parent.parent.parent / "data_fetchers" / "result"
DEFAULT_DATA_CACHE = DEFAULT_DATA_DIR / "factor_ic_data.json.gz"


def load_factor_return_data(
    factor_cols: list[str],
    return_col: str = "forward_return_1d",
    data_cache_path: Path | None = None,
    dropna_cols: list[str] | None = None,
    additional_factor_files: dict[str, Path] | None = None,
    logger=None,
) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    """
    从统一数据源加载因子数据和收益数据（单文件模式）

    参数:
        factor_cols: 需加载的因子列（如 ['rsi_6'] 或 ['close', 'high', 'low']）
            - 必须包含 'date' 和 'asset' 列（自动添加）
        return_col: 收益列名，默认 'forward_return_1d'
            - 可选: 'forward_return_1d', 'forward_return_3d', 'forward_return_5d'
        data_cache_path: 数据缓存路径（默认使用 DEFAULT_DATA_CACHE）
        dropna_cols: dropna 过滤列（默认 = factor_cols，不含 date/asset）
        additional_factor_files: 额外因子文件（如换手率数据）
            - 格式: {'turnover_rate': Path(...)}
            - 会合并到主因子数据
        logger: 日志记录器（由调用方传入，默认使用模块 logger）

    返回:
        (factor_df, return_df, raw_metadata)
        - factor_df: 过滤后的因子数据 DataFrame
        - return_df: 过滤后的收益数据 DataFrame（仅含 date/asset/return_col）
        - raw_metadata: 原始数据元信息字典
            - period_start: 原始缓存最小日期
            - period_end: 原始缓存最大日期
            - total_days: 原始缓存日期数
            - avg_stocks_per_day: 原始平均每日股票数

    规范:
        period 和 total_days 基于 dropna 前的原始缓存数据
        （遵循 PROJECT.md 输出字段语义规范）

    示例:
        # RSI 因子（直接用缓存列）
        factor_df, return_df, raw_metadata = load_factor_return_data(
            factor_cols=['rsi_6']
        )

        # KDJ 因子（需要 close, high, low）
        factor_df, return_df, raw_metadata = load_factor_return_data(
            factor_cols=['close', 'high', 'low']
        )

        # 5日收益周期
        factor_df, return_df, raw_metadata = load_factor_return_data(
            factor_cols=['rsi_6'],
            return_col='forward_return_5d'
        )
    """
    if logger is None:
        logger = get_logger(__name__)

    logger.info("[数据加载] 从统一数据源读取数据...")

    # 确定缓存路径
    data_cache_path = data_cache_path or DEFAULT_DATA_CACHE

    # ========== 加载统一数据源 ==========
    if not data_cache_path.exists():
        raise FileNotFoundError(f"数据缓存不存在: {data_cache_path}")

    # ⚠️ 内存优化: ijson 流式读取 + 列式累积构建 DataFrame
    # v1（2026-06-12）: ijson 逐条解析 → 全量累积到 list[dict] → pd.DataFrame
    #   问题: list[dict] 与最终 DataFrame 双份共存，扩展因子加入后峰值仍达 4.2GB → OOM
    # v2（2026-06-13 16:48）: ijson 分块累积 dict → 每块转 DataFrame → pd.concat
    #   问题: pd.concat 时所有块共存，峰值 ~4GB 未改善（实测仍 OOM）
    # v3（2026-06-13 17:00）: ijson 流式 → 列式 dict[col, list] 累积 → 一次性建 DataFrame
    #   原理: 列式累积只为每列存一个 list[scalar]，省掉 N 个 dict 的对象头开销
    #         149万行 × 4 列约 60MB，相比 list[dict] 的 ~600MB 降低 10 倍
    #   预期: 内存峰值 4.2GB → <500MB
    # 需要的列集合: date + asset + factor_cols + return_col + forward_return_1d (默认)
    required_cols = ["date", "asset"] + factor_cols + [return_col]
    # forward_return_1d 是默认收益列，始终保留（即使 return_col 是 3d/5d）
    if return_col != "forward_return_1d" and "forward_return_1d" not in required_cols:
        required_cols.append("forward_return_1d")
    # 去重（保留首次出现顺序，避免下游 select_cols 中列重复）
    required_cols = list(dict.fromkeys(required_cols))

    import gc

    dates_set: set[str] = set()
    df = None  # 初始化为 None，ijson 路径会通过 columns 构建，json.load 路径直接赋值
    try:
        import ijson

        # 列式累积：每列预分配一个 list，避免 list[dict] 的 dict 对象头开销
        columns: dict[str, list] = {col: [] for col in required_cols}
        with gzip.open(data_cache_path, "rb") as f:
            # ijson.items 流式解析 JSON 的 "data" 数组
            for record in ijson.items(f, "data.item"):
                # 按列追加（缺失列追加 None，pandas 会处理为 NaN）
                for col in required_cols:
                    columns[col].append(record.get(col))
                date_val = record.get("date")
                if date_val is not None:
                    dates_set.add(str(date_val))

        if not columns["date"]:
            raise KeyError(f"数据缓存文件 '{data_cache_path}' 数据为空或格式错误")

        # 一次性从列式字典构建 DataFrame（pandas 内部直接转 numpy 列存，避免重复拷贝）
        df = pd.DataFrame(columns)
        del columns
        gc.collect()
    except ImportError:
        # ijson 不可用时回退到 json.load（老方法，可能OOM）
        logger.warning("ijson 不可用，回退到 json.load（内存峰值约4.4GB，可能OOM）")
        try:
            with gzip.open(data_cache_path, "rt", encoding="utf-8") as f:
                data = json.load(f)
        except (gzip.BadGzipFile, json.JSONDecodeError, OSError) as e:
            logger.error(f"数据读取失败 [{data_cache_path}] [{type(e).__name__}]: {e}")
            raise

        if "data" not in data:
            raise KeyError(f"数据缓存文件 '{data_cache_path}' 缺少 'data' 键\nJSON 结构: {list(data.keys())}") from None

        df = pd.DataFrame(data["data"])
        del data["data"]
        del data
        gc.collect()
        dates_set = set(df["date"].astype(str).unique())

    # ========== 基础列验证（加载后立即验证） ==========
    for col in ["date", "asset"]:
        if col not in df.columns:
            raise KeyError(f"数据缺少必需列: '{col}'，无法继续处理")

    logger.info(f"原始数据: {len(df)} 行, {df['asset'].nunique()} 只股票")

    # ========== 日期类型统一转换 ==========
    df = _convert_date_column(df, "统一数据源", logger=logger)

    # ========== 快照原始数据范围（dropna 前） ==========
    raw_period_start = str(df["date"].min())
    raw_period_end = str(df["date"].max())
    raw_total_days = df["date"].nunique()
    raw_avg_stocks_per_day = round(df.groupby("date").size().mean(), 1)

    logger.info(f"原始数据范围: {raw_period_start} ~ {raw_period_end}, {raw_total_days} 个交易日")
    logger.info(f"原始平均每日股票数: {raw_avg_stocks_per_day}")

    # ========== 加载额外因子文件（如有） ==========
    all_factor_cols = list(factor_cols)  # 创建副本，防止引用污染

    if additional_factor_files:
        for col_name, file_path in additional_factor_files.items():
            if not file_path.exists():
                raise FileNotFoundError(f"额外因子缓存不存在: {file_path}")

            try:
                with gzip.open(file_path, "rt", encoding="utf-8") as f:
                    additional_data = json.load(f)
            except (gzip.BadGzipFile, json.JSONDecodeError, OSError) as e:
                logger.error(f"额外因子数据读取失败 [{file_path}] [{type(e).__name__}]: {e}")
                raise

            if "data" not in additional_data:
                raise KeyError(f"额外因子文件 '{file_path}' 缺少 'data' 键\nJSON 结构: {list(additional_data.keys())}")

            additional_df = pd.DataFrame(additional_data["data"])
            additional_df = _convert_date_column(additional_df, f"额外因子({col_name})", logger=logger)

            if col_name in additional_df.columns:
                additional_df[col_name] = pd.to_numeric(additional_df[col_name], errors="coerce")
            else:
                available_cols = sorted([c for c in additional_df.columns if c not in ["date", "asset"]])
                raise KeyError(f"额外因子文件 '{file_path}' 缺少指定列: '{col_name}'\n可用列: {available_cols}")

            rows_before = len(df)
            df = pd.merge(df, additional_df[["date", "asset", col_name]], on=["date", "asset"], how="inner")
            rows_after = len(df)
            rows_lost = rows_before - rows_after

            if rows_lost > 0:
                if rows_before > 0:
                    loss_pct = rows_lost / rows_before * 100
                    logger.info(f"合并 {col_name} 后: {rows_after} 行（丢失 {rows_lost} 行，{loss_pct:.1f}%）")
                else:
                    logger.info(f"合并 {col_name} 后: {rows_after} 行（丢失 {rows_lost} 行，原始数据为空）")
            else:
                logger.info(f"合并 {col_name} 后: {rows_after} 行（无数据丢失）")

        additional_cols = [k for k in additional_factor_files.keys() if k not in all_factor_cols]
        all_factor_cols.extend(additional_cols)

    # ========== 列存在验证 ==========
    for col in ["date", "asset"]:
        if col not in df.columns:
            raise KeyError(f"数据缺少必需列: '{col}'")

    missing_factor_cols = [col for col in all_factor_cols if col not in df.columns]
    if missing_factor_cols:
        available_cols = sorted([c for c in df.columns if c not in ["date", "asset"]])
        raise KeyError(f"数据缺少必需列: {missing_factor_cols}\n可用因子列: {available_cols}")

    if return_col not in df.columns:
        available_return_cols = [c for c in df.columns if "forward_return" in c]
        raise KeyError(f"收益列 '{return_col}' 不存在于数据中\n可用收益列: {available_return_cols}")

    # ========== 分离因子和收益数据 ==========
    select_cols = list(dict.fromkeys(["date", "asset"] + all_factor_cols))
    factor_df = df[select_cols].copy()
    return_df = df[["date", "asset", return_col]].copy()

    # ========== 过滤缺失值 ==========
    if dropna_cols is None:
        dropna_cols = [c for c in factor_cols if c not in ["date", "asset"]]

    missing_dropna_cols = [col for col in dropna_cols if col not in factor_df.columns]
    if missing_dropna_cols:
        available_cols = sorted([c for c in factor_df.columns if c not in ["date", "asset"]])
        raise KeyError(f"dropna_cols 包含不存在的列: {missing_dropna_cols}\n可用列: {available_cols}")

    factor_df = factor_df.dropna(subset=dropna_cols).reset_index(drop=True)
    return_df = return_df.dropna(subset=[return_col]).reset_index(drop=True)

    logger.info(f"过滤缺失值后: 因子 {len(factor_df)} 行（过滤列: {dropna_cols}），收益 {len(return_df)} 行")

    # ========== 日期对齐（单文件内数据天然对齐） ==========
    # 取日期交集确保因子和收益数据对齐
    factor_dates = list(factor_df["date"].unique())
    return_dates = list(return_df["date"].unique())

    if set(factor_dates) != set(return_dates):
        logger.warning("因子数据和收益数据日期不对齐（单文件内）")
        common_dates = list(set(factor_dates) & set(return_dates))
        factor_df = factor_df[factor_df["date"].isin(common_dates)].reset_index(drop=True)
        return_df = return_df[return_df["date"].isin(common_dates)].reset_index(drop=True)
        logger.info(f"对齐后: {len(common_dates)} 个日期, 因子 {len(factor_df)} 行, 收益 {len(return_df)} 行")

    # ========== 返回结果 ==========
    return (
        factor_df,
        return_df,
        {
            "period_start": raw_period_start,
            "period_end": raw_period_end,
            "total_days": raw_total_days,
            "avg_stocks_per_day": raw_avg_stocks_per_day,
        },
    )


def _convert_date_column(df: pd.DataFrame, name: str, logger=None) -> pd.DataFrame:
    """
    日期类型统一转换（YYYY-MM-DD）

    参数:
        df: DataFrame
        name: 数据名称（用于错误消息）
        logger: 日志记录器（由调用方传入，默认使用模块 logger）

    返回:
        转换后的 DataFrame

    异常:
        ValueError: 日期格式无效
    """
    if logger is None:
        logger = get_logger(__name__)

    if "date" not in df.columns:
        return df

    df = df.copy()

    date_series = pd.to_datetime(df["date"], errors="coerce")
    nat_count = date_series.isna().sum()

    if nat_count > 0:
        invalid_samples = df["date"][date_series.isna()].head(5).tolist()
        logger.error(f"[{name}] 发现 {nat_count} 个无效日期格式，示例: {invalid_samples}")
        raise ValueError(
            f"{name}中存在 {nat_count} 个无效日期格式\n无效日期示例: {invalid_samples}\n请检查缓存数据源是否包含脏数据"
        )

    df["date"] = date_series.dt.strftime("%Y-%m-%d")
    return df


def get_data_cache_path() -> Path:
    """获取统一数据源缓存路径"""
    return DEFAULT_DATA_CACHE


def get_data_dir() -> Path:
    """获取数据目录路径"""
    return DEFAULT_DATA_DIR
