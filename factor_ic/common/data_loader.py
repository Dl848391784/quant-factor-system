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
    # is_untradeable: 不可交易标记列（v1.46+，涨停类股票标记为1，IC计算需排除）
    required_cols = ["date", "asset"] + factor_cols + [return_col]
    # forward_return_1d 是默认收益列，始终保留（即使 return_col 是 3d/5d）
    if return_col != "forward_return_1d" and "forward_return_1d" not in required_cols:
        required_cols.append("forward_return_1d")
    # is_untradeable 列（如存在则加载用于过滤）
    required_cols.append("is_untradeable")
    # 去重（保留首次出现顺序，避免下方 select_cols 中列重复）
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
            logger.error("数据读取失败 [%s] [%s]: %s", data_cache_path, type(e).__name__, e)
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

    logger.info("原始数据: %s 行, %s 只股票", len(df), df["asset"].nunique())

    # ========== 日期类型统一转换 ==========
    df = _convert_date_column(df, "统一数据源", logger=logger)

    # ========== 快照原始数据范围（dropna 前） ==========
    raw_period_start = str(df["date"].min())
    raw_period_end = str(df["date"].max())
    raw_total_days = df["date"].nunique()
    raw_avg_stocks_per_day = round(df.groupby("date").size().mean(), 1)

    logger.info("原始数据范围: %s ~ %s, %s 个交易日", raw_period_start, raw_period_end, raw_total_days)
    logger.info("原始平均每日股票数: %s", raw_avg_stocks_per_day)

    # ========== 数值列类型规范化（Decimal/str → float） ==========
    # 背景（2026-06-13）：统一数据源 factor_ic_data.json.gz 中 OHLC 等价格列以 Decimal
    #   字符串形式存储，pandas 读取后 dtype=object（Decimal 实例）或 str。
    #   下游复杂因子（calculate_kdj_j / calculate_bollinger_pb 等）在 IC 脚本运行期
    #   计算时会触发 `Decimal - float` 类型不兼容错误，导致 update_mode=failed。
    # 修复：在主数据加载完成后，对所有非键列（date/asset 除外）统一 pd.to_numeric，
    #   与下方 additional_factor_files 的处理逻辑（第 ~227 行）保持对称。
    #   对已是 numeric 的列是 no-op，安全；非数值字符串会被 coerce 为 NaN 由后续 dropna 过滤。
    numeric_candidate_cols = [c for c in df.columns if c not in ("date", "asset")]
    for col in numeric_candidate_cols:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    logger.info(
        "数值列类型规范化完成: 转换 %s 列（pd.to_numeric, Decimal/str → float）",
        len(numeric_candidate_cols),
    )

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
                logger.error("额外因子数据读取失败 [%s] [%s]: %s", file_path, type(e).__name__, e)
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
                    logger.info(
                        "合并 %s 后: %s 行（丢失 %s 行，%.1f%%）",
                        col_name,
                        rows_after,
                        rows_lost,
                        loss_pct,
                    )
                else:
                    logger.info("合并 %s 后: %s 行（丢失 %s 行，原始数据为空）", col_name, rows_after, rows_lost)
            else:
                logger.info("合并 %s 后: %s 行（无数据丢失）", col_name, rows_after)

        additional_cols = [k for k in additional_factor_files if k not in all_factor_cols]
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

    logger.info(
        "过滤缺失值后: 因子 %s 行（过滤列: %s），收益 %s 行",
        len(factor_df),
        dropna_cols,
        len(return_df),
    )

    # ========== 过滤不可交易股票（涨停类） ==========
    # is_untradeable=1 表示 T 日涨停（一字板/尾盘封板），无法在 T 日尾盘买入，
    # 其 forward_return 无法实际捕获，应从 IC 计算中排除。
    # 向后兼容: 旧数据无此列时跳过过滤。
    if "is_untradeable" in df.columns:
        untradeable_mask = df["is_untradeable"].fillna(0).astype(int) == 1
        untradeable_count = int(untradeable_mask.sum())
        if untradeable_count > 0:
            factor_df = factor_df[~untradeable_mask.loc[factor_df.index]].reset_index(drop=True)
            return_df = return_df[~untradeable_mask.loc[return_df.index]].reset_index(drop=True)
            logger.info(
                "过滤不可交易股票(涨停类): 排除 %d 行, 剩余因子 %s 行, 收益 %s 行",
                untradeable_count,
                len(factor_df),
                len(return_df),
            )
    else:
        logger.warning("数据缺少 is_untradeable 列，跳过不可交易股票过滤")

    # ========== 日期对齐（单文件内数据天然对齐） ==========
    # 取日期交集确保因子和收益数据对齐
    factor_dates = list(factor_df["date"].unique())
    return_dates = list(return_df["date"].unique())

    if set(factor_dates) != set(return_dates):
        logger.warning("因子数据和收益数据日期不对齐（单文件内）")
        common_dates = list(set(factor_dates) & set(return_dates))
        factor_df = factor_df[factor_df["date"].isin(common_dates)].reset_index(drop=True)
        return_df = return_df[return_df["date"].isin(common_dates)].reset_index(drop=True)
        logger.info(
            "对齐后: %s 个日期, 因子 %s 行, 收益 %s 行",
            len(common_dates),
            len(factor_df),
            len(return_df),
        )

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
        logger.error("[%s] 发现 %s 个无效日期格式，示例: %s", name, nat_count, invalid_samples)
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


def merge_industry_column(
    factor_df: pd.DataFrame,
    asset_col: str = "asset",
    out_col: str = "industry",
    logger=None,
) -> pd.DataFrame:
    """
    为 factor_df 添加申万一级行业列（行业中性化前置步骤）

    数据来源:
        data_fetchers.fetch_industry.get_industry_map() 提供的静态行业快照
        （详见 design.md §2.1 / §8.1 接口契约）

    参数:
        factor_df: 因子 DataFrame，必须含 asset_col 列
        asset_col: 股票代码列名，默认 'asset'
        out_col: 输出行业列名，默认 'industry'
        logger: 日志记录器（由调用方传入，默认使用模块 logger）

    返回:
        新 DataFrame（不修改入参），增加一列 out_col：
        - 已知 asset → 申万一级行业名（如 '电力设备'、'其他'）
        - 未知 asset → pandas NaN（design.md §8.2 协议）

    Note:
        '其他' 是 fetch_industry 已存在的合法行业值，本函数不做特殊处理；
        是否剔除由下游 (run_factor_ic_analysis) 按 design.md §3.3 决定。
    """
    if logger is None:
        logger = get_logger(__name__)

    if asset_col not in factor_df.columns:
        raise KeyError(f"factor_df 缺少 '{asset_col}' 列；可用列: {list(factor_df.columns)}")

    # 延迟导入：避免在 data_loader 顶层引入跨模块依赖（与现有 factor_calculator 复用模式一致）
    from data_fetchers.fetch_industry import get_industry_map

    industry_map = get_industry_map()
    asset_to_industry = {code: info.get("industry") for code, info in industry_map.items()}

    result = factor_df.copy()
    result[out_col] = result[asset_col].map(asset_to_industry)

    total = len(result)
    matched = int(result[out_col].notna().sum())
    unmatched = total - matched
    other_count = int((result[out_col] == "其他").sum())
    logger.info(
        "行业列合并: 总 %s 行 / 已匹配 %s 行 / 未匹配 %s 行 / '其他' %s 行",
        total,
        matched,
        unmatched,
        other_count,
    )

    return result
