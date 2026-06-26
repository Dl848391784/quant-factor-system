"""
stock_selector_history.py — Parquet 选股历史写入

从 stock_selector.py v3.12 拆分 (2026-06-26).
行为不变, 纯机械提取.

版本历史见 stock_selector.py 头注释.
"""

import json
import logging
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd


# sys.path 处理（遵循 MODULE.md M49）
PROJECT_ROOT = Path(__file__).parent.parent.resolve()
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))  # noqa: E402

from stock_selector.common.logger_config import get_logger  # noqa: E402
from stock_selector.stock_selector_config import PROJECT_ROOT, StockSelectorConfig  # noqa: E402


_logger = get_logger(__name__)


def write_selection_history(
    stage1_top: list[dict[str, Any]],
    stage2_top: list[dict[str, Any]],
    stage3_top: list[dict[str, Any]],
    config: StockSelectorConfig,
    weight_config: dict[str, Any],
    selection_date: str,
    stocks_on_date: int,
    factor_list: list[str],
    factor_cols: list[str],
    direction_map: dict[str, str] | None,
    flipped_factors: list[str] | None,
    exclusion_stats: dict[str, Any],
    output_dir: Path | str,
    stage1_bottom: list[dict[str, Any]] | None = None,  # v3.8: Bottom 30 快照
    logger: logging.Logger | None = None,
) -> Path:
    """写入选股历史到 Parquet 分区数据集（单一信源, designs/feat_stock_selection_history_parquet.md）.

    数据集布局 (Hive-style partitioning):
        <output_dir>/stock_selection_history/selection_date=YYYY-MM-DD/part-0.parquet

    每天一个分区, 含 Stage 1/2/3 Top 30 共 ~90 行. 同日重跑覆盖该分区, 其他分区不动.

    Args:
        stage1_top: Stage 1 (composite 降序) Top 30. 调用方需切片好.
        stage2_top: Stage 2 (按 stage2_sort_col 重排) Top 30. 调用方需切片好.
                    enable_two_stage=False 时传 [].
        stage3_top: Stage 3 (企稳过滤后) 最终 Top N. 含 factor_values/decision_card.
        config: 选股配置.
        weight_config: 权重配置 (含 best_selection.method/composite_score).
        selection_date: 选股日期 'YYYY-MM-DD'.
        stocks_on_date: 该日全市场股票数.
        factor_list: 因子逻辑名列表.
        factor_cols: 因子列名列表.
        direction_map: 因子方向映射 (logic_name -> 'positive'/'negative').
        flipped_factors: 标准化时取反的因子列表.
        exclusion_stats: dict 含 excluded_by_amplitude/coverage/liquidity/confirmation/filter (写入 file metadata).
        output_dir: 输出根目录 (函数内自动拼接 'stock_selection_history').
        logger: 日志.

    Returns:
        分区目录路径 (selection_date=YYYY-MM-DD).

    Raises:
        RuntimeError: 写入失败 (按 design §3.2: 无 JSON 兜底, 失败即 pipeline 失败).
        ValueError: 输入数据契约违反.
    """
    if logger is None:
        logger = _logger

    import pyarrow as pa
    import pyarrow.parquet as pq

    output_dir = Path(output_dir)
    dataset_root = output_dir / "stock_selection_history"
    partition_dir = dataset_root / f"selection_date={selection_date}"

    # 构造行集合
    best_selection = weight_config["best_selection"]
    run_id = str(uuid.uuid4())
    created_at = datetime.now(timezone.utc)
    weight_method = best_selection["method"]
    composite_score = float(best_selection["composite_score"])
    direction_map_json_str = json.dumps(direction_map or {}, ensure_ascii=False, sort_keys=True)
    flipped_factors_json_str = json.dumps(flipped_factors or [], ensure_ascii=False)

    # Stage3 codes 集合 (用于标记 Stage 2 中被淘汰的股票)
    stage3_codes = {s["code"] for s in stage3_top}

    def _row(stage: int, stock: dict[str, Any]) -> dict[str, Any]:
        """构造一行 Parquet 记录"""
        code = stock["code"]
        composite_value = float(stock["composite_value"])
        weight_coverage = stock.get("weight_coverage")
        weight_coverage_f = float(weight_coverage) if weight_coverage is not None else None

        stage1_rank: int | None
        if stage == 1:
            stage1_rank = int(stock["rank"])
        else:
            sr = stock.get("stage1_rank")
            stage1_rank = int(sr) if sr is not None else None

        stage2_sort_value: float | None = None
        if stage == 2 and config.enable_two_stage and config.stage2_sort_col:
            # apply_stage2_resort 没把排序值塞回 stock dict, 留 None;
            # 调用方若想填值需扩展 apply_stage2_resort. 本期接受 None (留作未来扩展).
            stage2_sort_value = stock.get("stage2_sort_value")
            if stage2_sort_value is not None:
                stage2_sort_value = float(stage2_sort_value)

        excluded_at_stage3: str | None = None
        if stage == 2 and code not in stage3_codes:
            excluded_at_stage3 = "stabilization"

        factor_values_json_str: str | None = None
        factor_values_std_json_str: str | None = None
        decision_card_json_str: str | None = None
        if stage == 3:
            fv = stock.get("factor_values")
            if fv is not None:
                factor_values_json_str = json.dumps(fv, ensure_ascii=False, sort_keys=True)
            fvs = stock.get("factor_values_std")
            if fvs is not None:
                factor_values_std_json_str = json.dumps(fvs, ensure_ascii=False, sort_keys=True)
            dc = stock.get("decision_card")
            if dc is not None:
                decision_card_json_str = json.dumps(dc, ensure_ascii=False, sort_keys=True)

        return {
            # 注: selection_date 是 Hive 分区键, 不写入 Parquet body (Hive 分区天然把目录名当虚拟列,
            # 写入列会与分区键冲突: ArrowTypeError 'string vs dictionary<values=string>'.
            # 通过 pads.dataset(partitioning='hive') 读取时 selection_date 列会自动出现).
            "stage": stage,
            "rank": int(stock["rank"]),
            "code": code,
            "composite_value": composite_value,
            "weight_coverage": weight_coverage_f,
            "stage1_rank": stage1_rank,
            "stage2_sort_value": stage2_sort_value,
            "excluded_at_stage3": excluded_at_stage3,
            "weight_method": weight_method,
            "factor_direction": config.factor_direction,
            "top_n": int(config.top_n),
            "stage1_pool_size": int(config.stage1_pool_size) if config.enable_two_stage else None,
            "stage2_sort_col": config.stage2_sort_col if config.enable_two_stage else None,
            "stage2_ascending": bool(config.stage2_ascending) if config.enable_two_stage else None,
            "direction_map_json": direction_map_json_str,
            "flipped_factors_json": flipped_factors_json_str,
            "composite_score": composite_score,
            "created_at": created_at,
            "run_id": run_id,
            "factor_values_json": factor_values_json_str,
            "factor_values_std_json": factor_values_std_json_str,
            "decision_card_json": decision_card_json_str,
            "lr_proba_up": float(stock["lr_proba_up"]) if stock.get("lr_proba_up") is not None else None,
        }

    rows: list[dict[str, Any]] = []
    for s in stage1_top:
        rows.append(_row(1, s))
    for s in stage2_top:
        rows.append(_row(2, s))
    for s in stage3_top:
        rows.append(_row(3, s))
    # v3.8: Stage 1 Bottom 30 (stage=4), composite 最低的 30 只
    if stage1_bottom:
        for s in stage1_bottom:
            rows.append(_row(4, s))

    if not rows:
        raise ValueError(
            f"write_selection_history: 没有行可写 (selection_date={selection_date}). "
            "stage1/stage2/stage3 三组均为空, 请检查上游流水线."
        )

    df = pd.DataFrame(rows)

    # 显式 schema (design §2.2): 保证跨日 schema 稳定, 不被 pandas 类型推断打乱
    # 注: selection_date 不在 schema 中——它是 Hive 分区键, pyarrow 读取时自动注入虚拟列
    schema = pa.schema(
        [
            pa.field("stage", pa.int8(), nullable=False),
            pa.field("rank", pa.int16(), nullable=False),
            pa.field("code", pa.string(), nullable=False),
            pa.field("composite_value", pa.float64(), nullable=False),
            pa.field("weight_coverage", pa.float64(), nullable=True),
            pa.field("stage1_rank", pa.int16(), nullable=True),
            pa.field("stage2_sort_value", pa.float64(), nullable=True),
            pa.field("excluded_at_stage3", pa.string(), nullable=True),
            pa.field("weight_method", pa.string(), nullable=False),
            pa.field("factor_direction", pa.string(), nullable=False),
            pa.field("top_n", pa.int16(), nullable=False),
            pa.field("stage1_pool_size", pa.int16(), nullable=True),
            pa.field("stage2_sort_col", pa.string(), nullable=True),
            pa.field("stage2_ascending", pa.bool_(), nullable=True),
            pa.field("direction_map_json", pa.string(), nullable=False),
            pa.field("flipped_factors_json", pa.string(), nullable=False),
            pa.field("composite_score", pa.float64(), nullable=False),
            pa.field("created_at", pa.timestamp("us", tz="UTC"), nullable=False),
            pa.field("run_id", pa.string(), nullable=False),
            pa.field("factor_values_json", pa.string(), nullable=True),
            pa.field("factor_values_std_json", pa.string(), nullable=True),
            pa.field("decision_card_json", pa.string(), nullable=True),
            pa.field("lr_proba_up", pa.float64(), nullable=True),  # v3.13: LR 打分 P(T+1>0)
        ]
    )

    try:
        table = pa.Table.from_pandas(df, schema=schema, preserve_index=False)
    except (pa.ArrowException, ValueError, TypeError) as e:
        logger.exception("write_selection_history: DataFrame → Arrow Table 转换失败, schema 不匹配")
        raise RuntimeError(f"write_selection_history: DataFrame → Arrow Table 转换失败: {type(e).__name__}: {e}") from e

    # file-level metadata (统计字段, 不参与查询)
    exclusion_meta = {
        b"excluded_by_amplitude": str(exclusion_stats.get("excluded_by_amplitude", 0)).encode("utf-8"),
        b"excluded_by_coverage": str(exclusion_stats.get("excluded_by_coverage", 0)).encode("utf-8"),
        b"excluded_by_liquidity": str(exclusion_stats.get("excluded_by_liquidity", 0)).encode("utf-8"),
        b"excluded_by_confirmation": str(exclusion_stats.get("excluded_by_confirmation", 0)).encode("utf-8"),
        b"excluded_by_overheat": str(exclusion_stats.get("excluded_by_overheat", 0)).encode("utf-8"),  # v3.9
        b"excluded_by_filter": json.dumps(exclusion_stats.get("excluded_by_filter") or {}, ensure_ascii=False).encode(
            "utf-8"
        ),
        b"min_amplitude": str(config.min_amplitude).encode("utf-8"),
        b"min_weight_coverage": str(exclusion_stats.get("min_weight_coverage", 0.5)).encode("utf-8"),
        b"stocks_on_date": str(stocks_on_date).encode("utf-8"),
        b"factor_list_json": json.dumps(factor_list, ensure_ascii=False).encode("utf-8"),
        b"factor_cols_json": json.dumps(factor_cols, ensure_ascii=False).encode("utf-8"),
        b"generated_at": created_at.strftime("%Y-%m-%dT%H:%M:%S%z").encode("utf-8"),
    }
    existing_meta = table.schema.metadata or {}
    table = table.replace_schema_metadata({**existing_meta, **exclusion_meta})

    # 写入: 临时文件 + os.replace 原子覆盖 (项目 v3.6 同 pattern)
    try:
        partition_dir.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        logger.exception("write_selection_history: 创建分区目录失败: %s", partition_dir)
        raise RuntimeError(
            f"write_selection_history: 创建分区目录失败: {partition_dir}, {type(e).__name__}: {e}"
        ) from e

    target_path = partition_dir / "part-0.parquet"
    temp_path = partition_dir / "part-0.parquet.tmp"
    replaced = False
    try:
        pq.write_table(table, temp_path, compression="snappy")
        os.replace(temp_path, target_path)
        replaced = True
    except (pa.ArrowException, OSError) as e:
        logger.exception("write_selection_history: Parquet 写入失败: %s", target_path)
        raise RuntimeError(f"write_selection_history: Parquet 写入失败: {target_path}, {type(e).__name__}: {e}") from e
    finally:
        if not replaced:
            temp_path.unlink(missing_ok=True)

    logger.info(
        "选股历史已写入 Parquet 分区: %s (stage1=%d, stage2=%d, stage3=%d, 大小=%.2f KB)",
        partition_dir,
        len(stage1_top),
        len(stage2_top),
        len(stage3_top),
        target_path.stat().st_size / 1024,
    )

    return partition_dir


# ============================================================================
# v3.10: LR 训练数据持久化 (designs/feat_lr_training_data.md)
# ============================================================================


def _load_stock_name_map() -> dict[str, str]:
    """加载 code → name 映射 (从 STOCK_LIST_DATA)."""
    from paths import STOCK_LIST_DATA

    if not STOCK_LIST_DATA.exists():
        return {}
    try:
        with open(STOCK_LIST_DATA, encoding="utf-8") as f:
            stock_list = json.load(f)
        if isinstance(stock_list, dict):
            return stock_list
        if isinstance(stock_list, list):
            return {item.get("code", ""): item.get("name", "") for item in stock_list if isinstance(item, dict)}
    except (OSError, json.JSONDecodeError):
        pass
    return {}


# v3.11: 四种权重方式各计算 composite_factor
ALL_WEIGHT_METHODS = ("equal_weight", "icir_weight", "ic_weight", "rolling_icir_weight")
