"""数据加载器。

从 generate_factor_summary_report.py 迁移（v3.8 拆分重构）。
加载 IC 结果、回测结果、综合因子结果、权重选择、股票选股结果等。
"""

import json
import logging
import time
from pathlib import Path

import pandas as pd
from factor_definitions import FACTOR_COL_TO_NAME_MAP, FACTOR_DEFINITIONS
from summary.report.constants import (
    DATA_PATHS,
    MAX_STOCKS_SAMPLE,
    STOCK_LIST_DATA,
)
from summary.report.formatters import (
    convert_return_to_percentage,
    format_weights,
    get_monotonicity_symbol,
    get_weight_method_display,
)


def load_json_file(path: Path, logger: logging.Logger) -> dict | None:
    """加载 JSON 文件

    Args:
        path: JSON 文件路径
        logger: 日志记录器

    Returns:
        JSON 数据字典，或 None（文件不存在或解析失败）
    """
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        logger.debug("文件不存在: %s", path)
        return None
    except json.JSONDecodeError as e:
        logger.warning("JSON 解析错误: %s, 位置 %s, 原因: %s", path, e.pos, e.msg)
        return None
    except (PermissionError, IsADirectoryError, OSError) as e:
        logger.warning("文件读取错误: %s, 类型 %s, 原因: %s", path, type(e).__name__, e)
        return None


def _select_neutral_payload(data: dict) -> tuple[dict, str]:
    """选择 summary 使用的中性化 payload（P4: 仅读 ic_neutralized）。

    返回 (payload, method)。method 用于汇总报告"中性化方式"列：
        - enabled=True 且 controls_used 非空：按注册顺序拼接，如 "industry+log_market_cap"
        - enabled=False：显示 "skipped"（具体原因在 skipped_reason 中）
        - 无 ic_neutralized 字段：显示 "-"（需重跑因子）
    """
    neutralized = data.get("ic_neutralized")
    if isinstance(neutralized, dict) and neutralized:
        if neutralized.get("enabled") is not True:
            return neutralized, "skipped"
        controls_used = neutralized.get("controls_used") or []
        method = "+".join(str(control) for control in controls_used) if controls_used else "neutralized"
        return neutralized, method

    return {}, "-"


def load_ic_results(logger: logging.Logger) -> list[dict]:
    """加载所有单因子 IC 分析结果

    Args:
        logger: 日志记录器

    Returns:
        IC 结果列表，按 ICIR 降序排序
    """
    ic_dir = Path(DATA_PATHS["ic_result"])
    results = []

    file_count = 0
    for file in ic_dir.glob("ic_*_analysis_result.json"):
        data = load_json_file(file, logger)
        if data:
            factor_name = data.get("factor_name", "")
            # 只移除末尾的 _1d 后缀（避免误删中间的 _1d）
            if factor_name.endswith("_1d"):
                factor_name = factor_name[:-3]
            ic_metrics = data.get("ic_metrics", {})
            sample_stats = data.get("sample_stats", {})

            # P3 中性化字段：新字段优先，旧字段兜底（design.md §10.2 P3.3）
            # 只读取摘要列需要的字段：enabled / decay_rate / decay_level / controls_used
            neutral, neutral_method = _select_neutral_payload(data)

            results.append(
                {
                    "factor_name": factor_name,
                    "ic_mean": ic_metrics.get("ic_mean", 0),
                    "icir": ic_metrics.get("icir", 0),
                    "ic_std": ic_metrics.get("ic_std", 0),
                    "valid_days": sample_stats.get("valid_days", 0),
                    "neutral_enabled": neutral.get("enabled", False),
                    "neutral_decay_rate": neutral.get("decay_rate"),  # None 时摘要列显示 '-'
                    "neutral_decay_level": neutral.get("decay_level", "undefined"),
                    "neutral_method": neutral_method,
                }
            )
            file_count += 1

    # 按 ICIR 降序排序
    results.sort(key=lambda x: x["icir"], reverse=True)
    logger.info("加载 IC 结果: %s 个因子", file_count)
    return results


def load_backtest_results(logger: logging.Logger) -> list[dict]:
    """加载所有单因子分层回测结果

    Args:
        logger: 日志记录器

    Returns:
        回测结果列表
    """
    backtest_dir = Path(DATA_PATHS["backtest_result"])
    results = []

    file_count = 0
    for file in backtest_dir.glob("*_layered_backtest.json"):
        data = load_json_file(file, logger)
        if data:
            # v2.11: 修复 past_return_1d 被错误剥离为 past_return 的问题
            # 根因：从文件 stem 剥离 _1d 会误删因子名中的 _1d（如 past_return_1d）
            # 修复：优先从 JSON 数据读取 factor_name，回退时才从文件 stem 提取
            # 注意：部分回测文件 factor_name 在 meta 子对象中（如 past_return_1d_layered_backtest.json）
            factor_name_from_json = data.get("factor_name", "") or data.get("meta", {}).get("factor_name", "")
            if factor_name_from_json:
                factor_name = factor_name_from_json
                # v2.21: 与 load_ic_results 保持一致——剥离 return_period 后缀 _1d
                # 但需避免误剥 past_return_1d（其因子名本身含 _1d）
                # 策略：剥离后检查 FACTOR_DEFINITIONS，仅当剥离结果在定义表中才剥离
                if factor_name.endswith("_1d"):
                    stripped = factor_name[:-3]
                    if stripped in FACTOR_DEFINITIONS:
                        factor_name = stripped
            else:
                # 回退：从文件 stem 提取（兼容无 factor_name 字段的旧文件）
                factor_name = file.stem.replace("_layered_backtest", "")
                # 旧文件中 stem 可能包含数据周期后缀 _1d，需剥离
                if factor_name.endswith("_1d"):
                    factor_name = factor_name[:-3]
            long_short = data.get("long_short", {})
            monotonicity = data.get("monotonicity", {})

            # 单调性质量判定
            quality = monotonicity.get("quality", "unknown")
            quality_symbol = get_monotonicity_symbol(quality)

            results.append(
                {
                    "factor_name": factor_name,
                    "long_short_return_annual": convert_return_to_percentage(
                        long_short.get("long_short_return_annual", 0)
                    ),
                    "long_short_sharpe": long_short.get("long_short_sharpe", 0),
                    "monotonicity_correlation": monotonicity.get("correlation", 0),
                    "monotonicity_quality": quality,
                    "monotonicity_symbol": quality_symbol,
                }
            )
            file_count += 1

    logger.info("加载回测结果: %s 个因子", file_count)
    return results


def calculate_factor_correlation(logger: logging.Logger, force_full: bool = False) -> pd.DataFrame | None:
    """计算所有因子之间的相关性矩阵

    尝试从综合因子结果文件中读取相关性数据。
    如果 force_full=True 或综合因子结果中没有相关性数据，则从因子数据文件中实时计算。

    Args:
        logger: 日志记录器
        force_full: 是否强制计算所有因子之间的相关性（忽略缓存）

    Returns:
        因子相关性矩阵 DataFrame，或 None
    """
    # 如果不强制全量计算，优先从综合因子结果文件读取
    if not force_full:
        comp_file = Path(DATA_PATHS["comprehensive_result"]) / "composite_icir_weight_1d.json"
        data = load_json_file(comp_file, logger)

        if data and "meta" in data:
            meta = data["meta"]
            if "correlation_matrix" in meta:
                # 从 JSON 转换为 DataFrame
                corr_dict = meta["correlation_matrix"]
                corr_df = pd.DataFrame(corr_dict)

                # 确保对角线为1（数值精度问题）
                for col in corr_df.columns:
                    corr_df.loc[col, col] = 1.0

                # 映射数据列名到因子逻辑名（遵循 FACTOR_COL_TO_NAME_MAP）
                # 解决 volume_ratio_5 vs volume_ratio 命名不一致问题
                factor_names = [FACTOR_COL_TO_NAME_MAP.get(c, c) for c in corr_df.columns]
                corr_df.index = factor_names
                corr_df.columns = factor_names

                logger.info("从综合因子结果文件读取相关性数据（仅选中因子）")
                return corr_df

    # 如果综合因子结果中没有相关性数据，尝试从原始数据计算
    factor_data_path = Path(DATA_PATHS["factor_data"]) / "factor_ic_data.parquet"

    if not factor_data_path.exists():
        logger.warning("因子数据文件不存在，无法计算相关性")
        return None

    logger.info("从 Parquet 读取因子数据计算相关性（列投影）...")
    start_time = time.time()

    factor_cols = list(FACTOR_COL_TO_NAME_MAP.keys())
    read_cols = ["date", "asset"] + factor_cols
    corr_df_raw = pd.read_parquet(factor_data_path, columns=read_cols)

    # 采样：取前 MAX_STOCKS_SAMPLE 只股票
    unique_assets = corr_df_raw["asset"].unique()
    sampled_assets = unique_assets[:MAX_STOCKS_SAMPLE]
    corr_df_raw = corr_df_raw[corr_df_raw["asset"].isin(sampled_assets)]

    # 提取因子列
    available_factor_cols = [c for c in factor_cols if c in corr_df_raw.columns]
    factor_df = corr_df_raw[["date", "asset"] + available_factor_cols].copy()
    del corr_df_raw

    # 计算相关性
    corr_matrix = factor_df[available_factor_cols].corr()

    # 重命名
    factor_names = [FACTOR_COL_TO_NAME_MAP.get(c, c) for c in corr_matrix.columns]
    corr_df = corr_matrix.copy()
    corr_df.index = factor_names
    corr_df.columns = factor_names

    elapsed = time.time() - start_time
    logger.info(
        "因子相关性计算完成(Parquet)，耗时: %.2f秒（采样%s只股票）",
        elapsed,
        len(sampled_assets),
    )

    return corr_df


def load_composite_results(logger: logging.Logger) -> list[dict]:
    """加载综合因子四种权重回测结果

    Args:
        logger: 日志记录器

    Returns:
        综合因子回测结果列表
    """
    comp_dir = Path(DATA_PATHS["comprehensive_result"])
    results = []

    weight_methods = ["ic_weight", "icir_weight", "rolling_icir_weight", "equal_weight"]
    file_count = 0

    for method in weight_methods:
        file = comp_dir / f"composite_{method}_1d.json"
        data = load_json_file(file, logger)
        if data:
            meta = data.get("meta", {})
            backtest = data.get("backtest_result", {})
            long_short = backtest.get("long_short", {})
            monotonicity = backtest.get("monotonicity", {})
            weights = meta.get("weights", {})

            # 格式化权重字符串
            if method == "rolling_icir_weight":
                # 从 meta.weight_meta 读取实际窗口参数（而非硬编码）
                weight_meta = meta.get("weight_meta", {})
                rolling_window = weight_meta.get("window", 60)  # 默认60日
                # v2.10: 读取最后一日权重并展示
                last_day_weights = weight_meta.get("last_day_weights", {})
                if last_day_weights:
                    weight_str = format_weights(last_day_weights) + f" (最新,{rolling_window}日滚动)"
                else:
                    weight_str = f"动态权重({rolling_window}日)"
            else:
                weight_str = format_weights(weights)

            # 单调性质量判定
            quality = monotonicity.get("quality", "unknown")
            quality_symbol = get_monotonicity_symbol(quality)

            results.append(
                {
                    "weight_method": method,
                    "weight_method_display": get_weight_method_display(method),
                    "long_short_return_annual": convert_return_to_percentage(
                        long_short.get("long_short_return_annual", 0)
                    ),
                    "long_short_sharpe": long_short.get("long_short_sharpe", 0),
                    "monotonicity_correlation": monotonicity.get("correlation", 0),
                    "monotonicity_quality": quality,
                    "monotonicity_symbol": quality_symbol,
                    "weight_str": weight_str,
                    "factor_list": meta.get("factor_list", []),
                    "weights": weights,
                    "weight_meta": meta.get("weight_meta", {}),  # v2.18: Rolling ICIR 动态权重元信息
                    "selection_result": meta.get("selection_result"),  # v1.7: 筛选详细结果
                    "direction_map": data.get("config", {}).get("direction_map", {}),  # v2.12: 方向映射
                    "flipped_factors": data.get("config", {}).get("flipped_factors", []),  # v2.12: 取反因子
                }
            )
            file_count += 1

    logger.info("加载综合因子结果: %s 种权重方法", file_count)
    return results


def load_weight_selection_result(logger: logging.Logger) -> dict | None:
    """加载权重选择结果

    v2.2 (2026-06-03): 新增权重选择结果加载

    Args:
        logger: 日志记录器

    Returns:
        权重选择结果字典，结构：
        {
            "best_selection": {"method": str, "composite_score": float, ...},
            "all_methods": [...],
            "scoring_metrics": [...],
            ...
        }
        或 None（文件不存在）
    """
    weight_file = Path(DATA_PATHS["weight_selection"])

    if not weight_file.exists():
        logger.debug("权重选择结果文件不存在: %s", weight_file)
        return None

    data = load_json_file(weight_file, logger)
    if data:
        logger.info(
            "加载权重选择结果: 最优方法=%s, 综合得分=%.4f",
            data.get("best_selection", {}).get("method", "N/A"),
            data.get("best_selection", {}).get("composite_score", 0),
        )
    return data


def _load_all_composite_stocks(
    weight_method: str,
    selection_date: str,
    logger: logging.Logger,
) -> list[dict]:
    """从 composite daily parquet 加载选股日全部股票的 composite 值（按降序排列）.

    v3.14 (2026-06-27): 新增. 当股票池 ≤400 只时, 报告全量展示所有股票.
    v3.15: 新增二次排序 (composite + turnover + market_cap), 返回两套排序结果.
    数据源: comprehensive_factor/result/<pipeline>/composite_{weight_method}_1d_daily.parquet

    Args:
        weight_method: 权重方法名称 (如 "rolling_icir_weight")
        selection_date: 选股日期 (YYYY-MM-DD)
        logger: 日志记录器

    Returns:
        按 composite_value 降序排列的股票列表 [{rank, code, composite_value}, ...];
        数据不可用时返回空列表 (调用方回退到 Stage 1 + Bottom 展示).
    """
    comp_dir = Path(DATA_PATHS["comprehensive_result"])
    daily_path = comp_dir / f"composite_{weight_method}_1d_daily.parquet"
    if not daily_path.exists():
        logger.debug("composite daily parquet 不存在: %s", daily_path)
        return []

    try:
        df = pd.read_parquet(daily_path, columns=["date", "asset", "composite_factor"])
    except Exception:
        logger.exception("读取 composite daily parquet 失败: %s", daily_path)
        return []

    day_df = df[df["date"].astype(str) == selection_date]
    if day_df.empty:
        logger.warning("composite daily parquet 中无 %s 的数据", selection_date)
        return []

    day_df = day_df.sort_values("composite_factor", ascending=False).reset_index(drop=True)

    # v3.15: 加载 turnover_rate (从 factor_ic_data.parquet)
    turnover_map: dict[str, float] = {}
    try:
        factor_path = Path(DATA_PATHS["factor_ic_data"])
        if factor_path.exists():
            factor_df = pd.read_parquet(
                factor_path,
                columns=["date", "asset", "turnover_rate"],
            )
            day_factor = factor_df[factor_df["date"].astype(str) == selection_date]
            turnover_map = day_factor.set_index("asset")["turnover_rate"].to_dict()
    except Exception:
        logger.debug("turnover_rate 加载失败, 二次排序忽略此维度")

    # v3.15: 加载 market_cap (从 market_cap_data.json.gz)
    market_cap_map: dict[str, float] = {}
    try:
        from paths import MARKET_CAP_DATA

        if MARKET_CAP_DATA.exists():
            import gzip

            with gzip.open(MARKET_CAP_DATA, "rt") as f:
                mc_data = json.load(f)
            for record in mc_data.get("data", []):
                if record.get("date") == selection_date:
                    code = str(record.get("asset", ""))
                    cap = record.get("total_market_cap")
                    if cap is not None:
                        market_cap_map[code] = float(cap)
    except Exception:
        logger.debug("market_cap 加载失败, 二次排序忽略此维度")

    stocks: list[dict] = []
    for i, row in day_df.iterrows():
        cv = row["composite_factor"]
        code = str(row["asset"])
        stocks.append(
            {
                "rank": i + 1,
                "code": code,
                "composite_value": float(cv) if pd.notna(cv) else None,
                "turnover_rate": turnover_map.get(code),
                "market_cap": market_cap_map.get(code),
            }
        )
    logger.info("加载全量 composite 股票: %s, %d 只", selection_date, len(stocks))
    return stocks


def load_stock_selection_result(logger: logging.Logger) -> dict | None:
    """加载股票选股结果 (v3.7: 从 Parquet 分区数据集读取最新一日).

    v3.7 (2026-06-24): 数据源切换 JSON → Parquet 分区数据集.
    路径: comprehensive_factor/result/stock_selection_history/selection_date=YYYY-MM-DD/part-0.parquet
    每天分区含 Stage 1/2/3 Top N 行 (默认 ~90 行); 取最新 selection_date 分区,
    按 stage 拆为三段, 渲染段可分别展示 (设计依据: designs/feat_stock_selection_history_parquet.md §3).

    v2.2 (2026-06-03): 新增股票选股结果加载

    Args:
        logger: 日志记录器

    Returns:
        股票选股结果字典 (向后兼容旧 schema + 新增 stage1/2 段):
        {
            "meta": {"selection_date": str, "weight_method": str, "top_n": int,
                     "min_amplitude": float, "excluded_by_amplitude": int,
                     "stocks_on_date": int, "direction_map": dict,
                     "flipped_factors": list, ...},
            "top_stocks": [{"rank": int, "code": str, "composite_value": float,
                            "factor_values": dict, "factor_values_std": dict,
                            "decision_card": dict | None, ...}, ...],   # Stage 3 短名单
            "stage1_top": [{...}],   # 新增 v3.7: Stage 1 composite 降序 Top N
            "stage2_top": [{...}],   # 新增 v3.7: Stage 2 turnover 升序 Top N
            "weight_config": {...},
        }
        或 None (数据集不存在 / 空).
    """
    import contextlib
    import json as _json

    import pyarrow.compute as pc
    import pyarrow.dataset as pads
    import pyarrow.parquet as pq

    history_root = Path(DATA_PATHS["stock_selection"])

    if not history_root.exists():
        logger.debug("股票选股 Parquet 数据集不存在: %s", history_root)
        return None

    try:
        dataset = pads.dataset(str(history_root), partitioning="hive")
    except Exception:
        logger.exception("读取股票选股 Parquet 数据集失败: %s", history_root)
        return None

    # 取最新 selection_date 分区
    dates_table = dataset.to_table(columns=["selection_date"])
    if dates_table.num_rows == 0:
        logger.warning("股票选股 Parquet 数据集为空: %s", history_root)
        return None

    dates = dates_table.column("selection_date").to_pylist()
    latest_date = max(dates)

    df = dataset.to_table(filter=pc.field("selection_date") == latest_date).to_pandas()
    if df.empty:
        logger.warning("最新分区 %s 无行", latest_date)
        return None

    # 找该日 part-0.parquet 用于读 file-level metadata
    partition_dir = history_root / f"selection_date={latest_date}"
    part_files = sorted(partition_dir.glob("*.parquet"))
    file_meta_raw: dict[bytes, bytes] = {}
    if part_files:
        try:
            pq_meta = pq.read_metadata(str(part_files[0]))
            if pq_meta.metadata:
                file_meta_raw = dict(pq_meta.metadata)
        except Exception:
            logger.exception("读 Parquet file-level metadata 失败: %s", part_files[0])

    def _meta_str(key: str, default: str = "") -> str:
        v = file_meta_raw.get(key.encode())
        return v.decode() if v else default

    def _meta_int(key: str, default: int = 0) -> int:
        s = _meta_str(key)
        try:
            return int(s) if s else default
        except (ValueError, TypeError):
            return default

    def _meta_float(key: str, default: float = 0.0) -> float:
        s = _meta_str(key)
        try:
            return float(s) if s else default
        except (ValueError, TypeError):
            return default

    def _meta_json(key: str, default):
        s = _meta_str(key)
        if not s:
            return default
        try:
            return _json.loads(s)
        except (ValueError, TypeError):
            return default

    # 行 → 渲染兼容字典 (旧 schema "top_stocks" 项的结构)
    def _row_to_stock_dict(row: pd.Series) -> dict:
        out: dict = {
            "rank": int(row["rank"]),
            "code": str(row["code"]),
            "composite_value": (float(row["composite_value"]) if pd.notna(row["composite_value"]) else None),
        }
        if pd.notna(row.get("weight_coverage")):
            out["weight_coverage"] = float(row["weight_coverage"])
        if pd.notna(row.get("stage1_rank")):
            out["stage1_rank"] = int(row["stage1_rank"])
        if pd.notna(row.get("stage2_sort_value")):
            out["stage2_sort_value"] = float(row["stage2_sort_value"])
        if pd.notna(row.get("excluded_at_stage3")) and row["excluded_at_stage3"]:
            out["excluded_at_stage3"] = str(row["excluded_at_stage3"])
        # 嵌套 JSON 串解析回 dict
        fv = row.get("factor_values_json")
        if isinstance(fv, str) and fv:
            with contextlib.suppress(ValueError, TypeError):
                out["factor_values"] = _json.loads(fv)
        fvs = row.get("factor_values_std_json")
        if isinstance(fvs, str) and fvs:
            with contextlib.suppress(ValueError, TypeError):
                out["factor_values_std"] = _json.loads(fvs)
        dc = row.get("decision_card_json")
        if isinstance(dc, str) and dc:
            with contextlib.suppress(ValueError, TypeError):
                out["decision_card"] = _json.loads(dc)
        # v3.13: LR 打分 proba_up
        if "lr_proba_up" in row.index and pd.notna(row.get("lr_proba_up")):
            out["lr_proba_up"] = float(row["lr_proba_up"])
        return out

    df_sorted = df.sort_values(["stage", "rank"])
    stage1_rows = df_sorted[df_sorted["stage"] == 1]
    stage2_rows = df_sorted[df_sorted["stage"] == 2]
    stage3_rows = df_sorted[df_sorted["stage"] == 3]
    # v3.8: Stage 1 Bottom 30 (stage=4)
    stage1_bottom_rows = df_sorted[df_sorted["stage"] == 4]

    stage1_top = [_row_to_stock_dict(r) for _, r in stage1_rows.iterrows()]
    stage2_top = [_row_to_stock_dict(r) for _, r in stage2_rows.iterrows()]
    stage3_top = [_row_to_stock_dict(r) for _, r in stage3_rows.iterrows()]
    stage1_bottom = [_row_to_stock_dict(r) for _, r in stage1_bottom_rows.iterrows()]

    # meta 重建: 从 stage3 首行 (若空则 stage1) + file metadata
    ref_row = (
        stage3_rows.iloc[0]
        if not stage3_rows.empty
        else (stage1_rows.iloc[0] if not stage1_rows.empty else df_sorted.iloc[0])
    )
    direction_map = {}
    dm_raw = ref_row.get("direction_map_json")
    if isinstance(dm_raw, str) and dm_raw:
        with contextlib.suppress(ValueError, TypeError):
            direction_map = _json.loads(dm_raw)
    flipped_factors: list = []
    ff_raw = ref_row.get("flipped_factors_json")
    if isinstance(ff_raw, str) and ff_raw:
        with contextlib.suppress(ValueError, TypeError):
            flipped_factors = _json.loads(ff_raw)

    meta = {
        "selection_date": str(latest_date),
        "weight_method": str(ref_row["weight_method"]),
        "factor_direction": str(ref_row["factor_direction"]),
        "top_n": int(ref_row["top_n"]),
        "composite_score": float(ref_row["composite_score"]) if pd.notna(ref_row.get("composite_score")) else 0.0,
        "direction_map": direction_map,
        "flipped_factors": flipped_factors,
        "stocks_on_date": _meta_int("stocks_on_date"),
        "min_amplitude": _meta_float("min_amplitude"),
        "min_weight_coverage": _meta_float("min_weight_coverage"),
        "excluded_by_amplitude": _meta_int("excluded_by_amplitude"),
        "excluded_by_coverage": _meta_int("excluded_by_coverage"),
        "excluded_by_liquidity": _meta_int("excluded_by_liquidity"),
        "excluded_by_confirmation": _meta_int("excluded_by_confirmation"),
        "excluded_by_overheat": _meta_int("excluded_by_overheat"),  # v3.9
        "excluded_by_filter": _meta_json("excluded_by_filter", {}),
        "stage1_pool_size": int(ref_row["stage1_pool_size"]) if pd.notna(ref_row.get("stage1_pool_size")) else None,
        "stage2_sort_col": str(ref_row["stage2_sort_col"]) if pd.notna(ref_row.get("stage2_sort_col")) else None,
        "stage2_ascending": bool(ref_row["stage2_ascending"]) if pd.notna(ref_row.get("stage2_ascending")) else None,
        "valid_stocks": len(stage3_top),
        # v3.15: 二次排序配置 (从 Parquet metadata 读取)
        "secondary_sort": {
            "enabled": _meta_float("secondary_sort_enabled", 0) > 0,
            "pool_threshold": int(_meta_float("secondary_sort_pool_threshold", 400)),
            "composite_weight": _meta_float("secondary_sort_composite_weight", 0.5),
            "turnover_weight": _meta_float("secondary_sort_turnover_weight", 0.3),
            "market_cap_weight": _meta_float("secondary_sort_market_cap_weight", 0.2),
        },
    }

    weight_config = {
        "method": meta["weight_method"],
        "factor_list": _meta_json("factor_list_json", []),
        "factor_cols": _meta_json("factor_cols_json", []),
    }

    result = {
        "meta": meta,
        "top_stocks": stage3_top,  # 向后兼容: 默认仍指 Stage 3 短名单
        "stage1_top": stage1_top,
        "stage2_top": stage2_top,
        "stage3_top": stage3_top,
        "stage1_bottom": stage1_bottom,  # v3.8: Bottom 30
        "weight_config": weight_config,
    }

    # v3.14: 加载全量 composite 股票 (≤400 只时报告全量展示)
    result["all_composite_stocks"] = _load_all_composite_stocks(
        meta["weight_method"],
        meta["selection_date"],
        logger,
    )

    logger.info(
        "加载股票选股结果 (Parquet): 选股日期=%s, Top N=%d, 最优权重=%s, "
        "Stage1=%d/Stage2=%d/Stage3=%d, 振幅阈值=%.2f%%, 振幅排除=%d只",
        meta["selection_date"],
        meta["top_n"],
        meta["weight_method"],
        len(stage1_top),
        len(stage2_top),
        len(stage3_top),
        meta["min_amplitude"] * 100,
        meta["excluded_by_amplitude"],
    )
    return result


def load_stock_name_map(logger: logging.Logger) -> dict[str, str]:
    """加载股票代码 → 股票名称映射

    v2.26 (2026-06-23): 新增——summary 第八节"股票选股结果"在股票代码后展示名称。

    数据源：paths.STOCK_LIST_DATA (data_fetchers/result/stock_list.json)
            由 fetch_stock_list.py 维护，结构 {"stocks": [{"code", "name", ...}, ...]}。

    Args:
        logger: 日志记录器

    Returns:
        {code: name} 字典。文件不存在或解析失败时返回空 dict（降级为不展示名称，
        而非抛错——名称仅是展示辅助，不应阻塞主报告生成）。
    """
    stock_file = STOCK_LIST_DATA
    if not stock_file.exists():
        logger.warning("股票列表文件不存在: %s（短名单将不展示股票名称）", stock_file)
        return {}

    try:
        data = load_json_file(stock_file, logger)
    except Exception as e:
        logger.warning("加载股票列表失败: %s（短名单将不展示股票名称）", e)
        return {}

    if not data:
        return {}

    stocks = data.get("stocks", [])
    name_map: dict[str, str] = {}
    for s in stocks:
        code = s.get("code")
        name = s.get("name")
        if code and name:
            # 清洗名称内的全角空格（如 "万 科Ａ" → "万科Ａ"），便于对齐表格列宽
            name_map[str(code)] = str(name).replace(" ", "").replace("\u3000", "")
    logger.info("加载股票名称映射: %d 只", len(name_map))
    return name_map


def merge_factor_data(ic_results: list[dict], backtest_results: list[dict]) -> list[dict]:
    """合并 IC 和回测数据

    Args:
        ic_results: IC 结果列表
        backtest_results: 回测结果列表

    Returns:
        合并后的数据列表
    """
    merged = []

    for ic_item in ic_results:
        factor_name = ic_item["factor_name"]
        backtest_item = next((b for b in backtest_results if b["factor_name"] == factor_name), {})
        merged.append({**ic_item, **backtest_item})

    return merged
