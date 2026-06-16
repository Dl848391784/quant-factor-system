#!/usr/bin/env python3
"""统一因子生成模块：合并基础因子 + 换手率 + 收益数据，输出 factor_ic_data.json.gz。

输出: data_fetchers/result/factor_ic_data.json.gz（PROJECT.md 跨模块数据路径规范）。
"""

import argparse
import gzip
import json
import logging
import math
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, cast

import numpy as np
import pandas as pd


# --- 条件导入 ---
try:
    from .common.logger_config import setup_logger
    from .factor_calculator import (
        calculate_amplitude,
        calculate_amplitude_delta,
        calculate_bollinger_pb,
        calculate_capital_flow_intensity,
        calculate_capital_flow_ratio_trend,
        calculate_industry_amplitude_trend,
        calculate_industry_earnings_growth,
        calculate_industry_momentum_5d,
        calculate_industry_pe_trend,
        calculate_industry_roe_trend,
        calculate_industry_turnover_trend,
        calculate_intraday_intensity,
        calculate_kdj_j,
        calculate_ma5_deviation,
        calculate_momentum_strength,
        calculate_near_high_ratio_5,
        calculate_overnight_return,
        calculate_past_return_1d,
        calculate_positive_day_ratio_5,
        calculate_price_position,
        calculate_return_5d,
        calculate_tail_factors,
        calculate_tail_price_position_delta,
        calculate_tail_volume_shrink_delta,
        calculate_turnover_surge,
        calculate_turnover_surge_delta,
        calculate_volume_price_strength,
    )
except ImportError:
    # 脚本直接运行（无父包上下文）：将项目根注入 sys.path 后改用绝对导入
    project_root = Path(__file__).parent.parent
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))
    from data_fetchers.common.logger_config import setup_logger
    from data_fetchers.factor_calculator import (
        calculate_amplitude,
        calculate_amplitude_delta,
        calculate_bollinger_pb,
        calculate_capital_flow_intensity,
        calculate_capital_flow_ratio_trend,
        calculate_industry_amplitude_trend,
        calculate_industry_earnings_growth,
        calculate_industry_momentum_5d,
        calculate_industry_pe_trend,
        calculate_industry_roe_trend,
        calculate_industry_turnover_trend,
        calculate_intraday_intensity,
        calculate_kdj_j,
        calculate_ma5_deviation,
        calculate_momentum_strength,
        calculate_near_high_ratio_5,
        calculate_overnight_return,
        calculate_past_return_1d,
        calculate_positive_day_ratio_5,
        calculate_price_position,
        calculate_return_5d,
        calculate_tail_factors,
        calculate_tail_price_position_delta,
        calculate_tail_volume_shrink_delta,
        calculate_turnover_surge,
        calculate_turnover_surge_delta,
        calculate_volume_price_strength,
    )

# 模块级 fallback logger（PROJECT.md 公共模块日志规范）
_MODULE_LOGGER = logging.getLogger("data_fetchers.factor_generator")

__all__ = [
    "generate_all_factors",
    "get_module_logger",
]

# 输入输出根目录：data_fetchers/result/（输入输出共用，详见 PROJECT.md 跨模块数据路径规范）
_DEFAULT_RESULT_DIR = Path(__file__).parent / "result"

# 扩展因子列名。新增因子只需在 _FACTOR_PIPELINE_STEPS 插入一项，启动期校验自动检测同步。
_EXTENDED_FACTOR_COLS: tuple[str, ...] = (
    "past_return_1d",  # 当日涨跌幅
    "bollinger_pb",
    "kdj_j",
    "turnover_surge",
    "amplitude",
    "price_position",
    "return_5d",  # momentum_strength 前置依赖
    "momentum_strength",
    "overnight_ret",
    "intraday_intensity",
    "tail_price_position",
    "tail_price_slope",
    "tail_price_volume_intensity",
    "tail_volume_acceleration",
    "tail_volume_shrink",
    "amplitude_delta",
    "turnover_surge_delta",
    "tail_price_position_delta",
    "tail_volume_shrink_delta",
    "volume_price_strength",
    "positive_day_ratio_5",
    "ma5_deviation",
    "near_high_ratio_5",
    "industry_momentum_5d",
    "industry_turnover_trend",
    "industry_amplitude_trend",
    "industry_roe_trend",
    "industry_earnings_growth",
    "industry_pe_trend",
    "capital_flow_ratio_trend",
    "capital_flow_intensity",
)

# 收益数据列名
_RETURN_COLS: tuple[str, ...] = ("forward_return_1d", "forward_return_3d", "forward_return_5d")

# 基础列：索引 + 行情 + 基础因子 + 换手率 + 成交量
_BASE_COLS: tuple[str, ...] = (
    "date",
    "asset",
    "open",
    "close",
    "high",
    "low",
    "rsi_6",
    "volume_ratio_5",
    "turnover_rate",
    "volume",
)

# 纯 OHLCV + 索引列（Step 1 日志识别基础因子列用）
_OHLCV_INDEX_COLS: frozenset[str] = frozenset({"date", "asset", "open", "close", "high", "low", "volume"})

# 输出列 = _BASE_COLS + _EXTENDED_FACTOR_COLS + _RETURN_COLS
_OUTPUT_COLS: tuple[str, ...] = _BASE_COLS + _EXTENDED_FACTOR_COLS + _RETURN_COLS

# 列数清单（供日志、metadata、回归测试使用）
_ALL_COLS_COUNTS: dict[str, int] = {
    "base_cols": len(_BASE_COLS),
    "extended_factor_cols": len(_EXTENDED_FACTOR_COLS),
    "return_cols": len(_RETURN_COLS),
    "total": len(_OUTPUT_COLS),
}


# --- 因子管线表 ---
# generate_all_factors step 3.5~11.9 的元数据描述。每项 dict 字段：
#   step_label     str | None  段头日志（None=沿用上一段头）
#   factor_func    Callable    factor_calculator 公共 API（df, *, logger_arg) -> df
#   output_cols    tuple       本因子写入的列（tail=5 列，其它=1 列）
#   emit_valid_log bool        是否逐列打印 "  有效 xxx: N (P%)"（详见 _run_pipeline_step）
#
# _VALID_KEY_ORDER 由本表动态生成，新增因子只需在本表插入一项。
# ============================================================================
_FACTOR_PIPELINE_STEPS: tuple[dict[str, Any], ...] = (
    # --- Step 3.5: past_return_1d ---
    {
        "step_label": "Step 3.5: 计算当日涨跌幅因子...",
        "factor_func": calculate_past_return_1d,
        "output_cols": ("past_return_1d",),
        "emit_valid_log": True,
    },
    # --- Step 4: bollinger_pb ---
    {
        "step_label": "Step 4: 计算布林带 %B 因子...",
        "factor_func": calculate_bollinger_pb,
        "output_cols": ("bollinger_pb",),
        "emit_valid_log": True,
    },
    # --- Step 5: kdj_j ---
    {
        "step_label": "Step 5: 计算 KDJ_J 因子...",
        "factor_func": calculate_kdj_j,
        "output_cols": ("kdj_j",),
        "emit_valid_log": True,
    },
    # --- Step 6: turnover_surge ---
    {
        "step_label": "Step 6: 计算换手率突增因子...",
        "factor_func": calculate_turnover_surge,
        "output_cols": ("turnover_surge",),
        "emit_valid_log": True,
    },
    # --- Step 7: amplitude ---
    {
        "step_label": "Step 7: 计算振幅因子...",
        "factor_func": calculate_amplitude,
        "output_cols": ("amplitude",),
        "emit_valid_log": True,
    },
    # --- Step 8: price_position ---
    {
        "step_label": "Step 8: 计算价格位置因子...",
        "factor_func": calculate_price_position,
        "output_cols": ("price_position",),
        "emit_valid_log": True,
    },
    # --- Step 8.5: return_5d ---
    {
        "step_label": "Step 8.5: 计算5日累计涨幅因子...",
        "factor_func": calculate_return_5d,
        "output_cols": ("return_5d",),
        "emit_valid_log": True,
    },
    # --- Step 8.6: momentum_strength ---
    {
        "step_label": "Step 8.6: 计算动量强度因子...",
        "factor_func": calculate_momentum_strength,
        "output_cols": ("momentum_strength",),
        "emit_valid_log": True,
    },
    # --- Step 9: overnight_ret ---
    {
        "step_label": "Step 9: 计算隔夜收益率因子（跳空幅度）...",
        "factor_func": calculate_overnight_return,
        "output_cols": ("overnight_ret",),
        "emit_valid_log": True,
    },
    # --- Step 10: intraday_intensity ---
    {
        "step_label": "Step 10: 计算日内价格强度因子...",
        "factor_func": calculate_intraday_intensity,
        "output_cols": ("intraday_intensity",),
        "emit_valid_log": True,
    },
    # --- Step 11: tail (5 列输出) ---
    {
        "step_label": "Step 11: 计算尾盘因子...",
        "factor_func": calculate_tail_factors,
        "output_cols": (
            "tail_price_position",
            "tail_price_slope",
            "tail_price_volume_intensity",
            "tail_volume_acceleration",
            "tail_volume_shrink",
        ),
        "emit_valid_log": True,
    },
    # --- Step 11.5: 止跌信号差分因子（v1.40）---
    {
        "step_label": "Step 11.5: 计算止跌信号差分因子...",
        "factor_func": calculate_amplitude_delta,
        "output_cols": ("amplitude_delta",),
        "emit_valid_log": True,
    },
    {
        "step_label": None,
        "factor_func": calculate_turnover_surge_delta,
        "output_cols": ("turnover_surge_delta",),
        "emit_valid_log": True,
    },
    {
        "step_label": None,
        "factor_func": calculate_tail_price_position_delta,
        "output_cols": ("tail_price_position_delta",),
        "emit_valid_log": True,
    },
    {
        "step_label": None,
        "factor_func": calculate_tail_volume_shrink_delta,
        "output_cols": ("tail_volume_shrink_delta",),
        "emit_valid_log": True,
    },
    # --- Step 11.6: 方向性因子（v1.41）---
    {
        "step_label": "Step 11.6: 计算方向性因子...",
        "factor_func": calculate_volume_price_strength,
        "output_cols": ("volume_price_strength",),
        # 段头因子打印 valid 行；同段后续因子 False 避免日志刷屏
        "emit_valid_log": True,
    },
    {
        "step_label": None,
        "factor_func": calculate_positive_day_ratio_5,
        "output_cols": ("positive_day_ratio_5",),
        "emit_valid_log": False,
    },
    {
        "step_label": None,
        "factor_func": calculate_ma5_deviation,
        "output_cols": ("ma5_deviation",),
        "emit_valid_log": False,
    },
    {
        "step_label": None,
        "factor_func": calculate_near_high_ratio_5,
        "output_cols": ("near_high_ratio_5",),
        "emit_valid_log": False,
    },
    # --- Step 11.7: 行业级别方向性因子（v1.42）---
    {
        "step_label": "Step 11.7: 计算行业级别方向性因子...",
        "factor_func": calculate_industry_momentum_5d,
        "output_cols": ("industry_momentum_5d",),
        # 段头因子打印 valid 行
        "emit_valid_log": True,
    },
    {
        "step_label": None,
        "factor_func": calculate_industry_turnover_trend,
        "output_cols": ("industry_turnover_trend",),
        "emit_valid_log": False,
    },
    {
        "step_label": None,
        "factor_func": calculate_industry_amplitude_trend,
        "output_cols": ("industry_amplitude_trend",),
        "emit_valid_log": False,
    },
    # --- Step 11.8: 行业基本面动量因子（v1.43 方案B）---
    {
        "step_label": "Step 11.8: 计算行业基本面动量因子...",
        "factor_func": calculate_industry_roe_trend,
        "output_cols": ("industry_roe_trend",),
        # 段头因子打印 valid 行
        "emit_valid_log": True,
    },
    {
        "step_label": None,
        "factor_func": calculate_industry_earnings_growth,
        "output_cols": ("industry_earnings_growth",),
        "emit_valid_log": False,
    },
    {
        "step_label": None,
        "factor_func": calculate_industry_pe_trend,
        "output_cols": ("industry_pe_trend",),
        "emit_valid_log": False,
    },
    # --- Step 11.9: 资金流因子（v1.44 方案C）---
    {
        "step_label": "Step 11.9: 计算资金流因子...",
        "factor_func": calculate_capital_flow_ratio_trend,
        "output_cols": ("capital_flow_ratio_trend",),
        # 段头因子打印 valid 行
        "emit_valid_log": True,
    },
    {
        "step_label": None,
        "factor_func": calculate_capital_flow_intensity,
        "output_cols": ("capital_flow_intensity",),
        "emit_valid_log": False,
    },
)


# metadata key 顺序：保 JSON byte 级稳定（下游 diff 无噪声）。由 _FACTOR_PIPELINE_STEPS 动态生成。
_VALID_KEY_ORDER: tuple[str, ...] = tuple(col for step in _FACTOR_PIPELINE_STEPS for col in step["output_cols"])

# 启动期校验：_EXTENDED_FACTOR_COLS 与 _FACTOR_PIPELINE_STEPS 集合一致性
_PIPELINE_OUTPUT_COLS_SET = frozenset(col for step in _FACTOR_PIPELINE_STEPS for col in step["output_cols"])
_EXTENDED_FACTOR_COLS_SET = frozenset(_EXTENDED_FACTOR_COLS)
if _EXTENDED_FACTOR_COLS_SET != _PIPELINE_OUTPUT_COLS_SET:
    _missing_in_ext = _PIPELINE_OUTPUT_COLS_SET - _EXTENDED_FACTOR_COLS_SET
    _missing_in_pipeline = _EXTENDED_FACTOR_COLS_SET - _PIPELINE_OUTPUT_COLS_SET
    raise RuntimeError(
        f"_EXTENDED_FACTOR_COLS / _FACTOR_PIPELINE_STEPS 集合不一致："
        f"pipeline 多出={sorted(_missing_in_ext)}，_EXTENDED_FACTOR_COLS 多出={sorted(_missing_in_pipeline)}"
    )

# 启动期段首校验：每个 step_label=None 的 step 之前必须已有非 None step_label
# （否则该段整段无段头日志且无报错）。校验 [0] 只防首个，无法防中间段首误写 None。
_seen_non_none_label = False
for _i, _step in enumerate(_FACTOR_PIPELINE_STEPS):
    if _step["step_label"] is not None:
        _seen_non_none_label = True
    elif not _seen_non_none_label:
        raise RuntimeError(
            f"_FACTOR_PIPELINE_STEPS[{_i}]['step_label'] 为 None 但此前无任何非 None step_label："
            f"段首缺失会导致整段无段头日志"
        )


# --- 模块级私有辅助函数 ---


def _calc_pct(count: int, total: int) -> float:
    """计算百分比（除零 + 非有限值保护）。

    Args:
        count: 分子。
        total: 分母。total ≤ 0 或结果非有限时返回 0.0。

    Returns:
        百分比（0.0~100.0，保留 2 位小数）。
    """
    if not math.isfinite(total) or total <= 0:
        return 0.0
    result = count / total * 100
    if not math.isfinite(result):
        return 0.0
    return round(result, 2)


def _run_pipeline_step(
    factor_df: pd.DataFrame,
    step: dict[str, Any],
    logger: logging.Logger,
) -> tuple[pd.DataFrame, dict[str, int]]:
    """执行 _FACTOR_PIPELINE_STEPS 中的单个 step。

    1. step_label 非 None → 打印段头；None → 沿用上一段头
    2. 调用 factor_func(factor_df, logger_arg=logger)
    3. 计算每个 output_col 的 valid_count
    4. emit_valid_log=True 时逐列打印；False 时 logger.debug（R4）

    Returns:
        (factor_df, {output_col: notna_count})。

    Raises:
        KeyError: factor_func 未生成全部 output_cols（含函数名+缺失列，便于归因）。
    """
    step_label = step["step_label"]
    # R1: step_label None=沿用上一段头
    if step_label is not None:
        logger.info(step_label)

    factor_func = step["factor_func"]
    factor_df = factor_func(factor_df, logger_arg=logger)

    output_cols: tuple[str, ...] = step["output_cols"]
    emit_valid_log: bool = step["emit_valid_log"]
    total_records = len(factor_df)
    valid_counts: dict[str, int] = {}

    # 提前校验 factor_func 输出列，否则下游 notna() KeyError 无法归因
    missing = [c for c in output_cols if c not in factor_df.columns]
    if missing:
        raise KeyError(
            f"因子函数 {factor_func.__name__} 未生成预期列: {missing}, 实际生成列: {list(factor_df.columns)}"
        )

    for col in output_cols:
        valid_count = int(factor_df[col].notna().sum())
        valid_counts[col] = valid_count
        if emit_valid_log:
            logger.info(
                "  有效 %s: %d (%.2f%%)",
                col,
                valid_count,
                _calc_pct(valid_count, total_records),
            )
        else:
            # R4: debug 级别日志，生产不输出，DEBUG 时可观测静默失败
            logger.debug(
                "  有效 %s: %d (%.2f%%)",
                col,
                valid_count,
                _calc_pct(valid_count, total_records),
            )

    return factor_df, valid_counts


def _drop_industry_column(factor_df: pd.DataFrame) -> pd.DataFrame:
    """删除 industry 临时列（step 11.7~11.9 行业聚合赋值用，不属于 _OUTPUT_COLS）。"""
    if "industry" in factor_df.columns:
        factor_df = factor_df.drop(columns=["industry"])
    return factor_df


def _load_json_gz_data(
    path: Path,
    dataset_label: str,
    logger: logging.Logger,
) -> list[dict[str, Any]]:
    """加载 gzip 压缩的 JSON 文件，提取 'data' 字段。

    Args:
        path: 数据文件路径。
        dataset_label: 中文标签（错误消息用），如 "基础因子" / "换手率" / "收益"。
        logger: 日志器。

    Returns:
        list[dict]，对应 JSON 文件 "data" 字段值。

    Raises:
        FileNotFoundError: 文件不存在。
        ValueError: gzip 损坏 / 非 gzip 格式 / JSON 解析失败 / 缺少 'data' 字段。

    Note:
        JSONDecodeError 仅引用 path/lineno/colno/msg，不引用 e.doc（避免内存翻倍）。
        BadGzipFile (Py3.8+) 仅在魔数损坏时抛出；非 gzip 格式抛 OSError，合并捕获。
    """
    try:
        with gzip.open(path, "rt", encoding="utf-8") as f:
            payload = json.load(f)
    except FileNotFoundError:
        raise FileNotFoundError(f"{dataset_label}数据文件不存在: {path}") from None
    except (gzip.BadGzipFile, OSError) as e:
        # BadGzipFile 是 OSError 子类，isinstance 区分日志语义
        if isinstance(e, gzip.BadGzipFile):
            logger.error("gzip 文件损坏（魔数错误）: %s, 原因: %s", path, str(e))
            raise ValueError(f"gzip 文件损坏: {path}") from e
        logger.error("gzip 读取失败（非 gzip 格式或 IO 错误）: %s, 原因: %s", path, str(e))
        raise ValueError(f"gzip 读取失败: {path}") from e
    except json.JSONDecodeError as e:
        # 仅引用 path/lineno/colno/msg，不引用 e.doc（避免内存翻倍）
        logger.error("JSON解析失败: %s, 行 %d, 列 %d, 信息: %s", path, e.lineno, e.colno, e.msg)
        raise ValueError(f"JSON解析失败: {path}, 行 {e.lineno}, 列 {e.colno}, 信息: {e.msg}") from e

    # 数据验证
    if "data" not in payload:
        raise ValueError(f"{dataset_label}数据缺少 'data' 字段: {path}")

    return payload["data"]


def _nan_to_null(obj: Any) -> Any:
    """递归将 float NaN/inf/-inf 转 None，numpy 标量降级为 Python 原生类型。

    pandas to_dict('records') 输出含 float('nan')/np.int64/np.bool_，
    json.dump 不支持这些类型，需遍历净化。

    检查顺序：
      1. float/np.floating：NaN/inf → None
      2. np.bool_：先于 np.integer（np.bool_ 是其子类，走 int 会丢布尔语义）
      3. np.integer：降级为 int
      4. dict/list/tuple：递归；tuple 统一返回 list（JSON 无 tuple）
      5. 其他：原样返回
    """
    # 浮点 NaN/inf 优先
    if isinstance(obj, (float, np.floating)) and (math.isnan(obj) or math.isinf(obj)):
        return None
    # np.bool_ 先于 np.integer（np.bool_ 是其子类，走 int 丢布尔语义）
    if isinstance(obj, np.bool_):
        return bool(obj)
    if isinstance(obj, np.integer):
        return int(obj)
    # 容器递归
    if isinstance(obj, dict):
        return {k: _nan_to_null(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        # JSON 无 tuple，统一输出 list
        return [_nan_to_null(item) for item in obj]
    return obj


def _atomic_write_json(payload: Any, path: Path, logger: logging.Logger) -> None:
    """原子写出小型 JSON 文件（< 1MB）。

    写 path+\".tmp\" → os.replace 原子替换；finally 仅替换失败时清理临时文件。

    Raises:
        OSError: 写入或替换失败。
    """
    temp_path = path.parent / (path.name + ".tmp")
    replaced = False
    try:
        with open(temp_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        os.replace(temp_path, path)
        replaced = True
    finally:
        # os.replace 成功后 temp_path 已不存在；失败则清理
        if not replaced and temp_path.exists():
            try:
                temp_path.unlink(missing_ok=True)
            except OSError as cleanup_err:
                logger.warning("临时文件清理失败: %s, 原因: %s", temp_path, cleanup_err)


def _write_factor_json_gz(
    output_df: pd.DataFrame,
    output_path: Path,
    logger: logging.Logger,
    *,
    batch_size: int = 50000,
) -> None:
    """流式写出 factor_ic_data.json.gz（gzip + 临时文件 + 原子替换）。

    Args:
        output_df: 已对齐 _OUTPUT_COLS 的输出 DataFrame。
        output_path: 目标输出路径。
        logger: 日志器。
        batch_size: 流式写入批次大小（默认 50000）。

    Raises:
        RuntimeError: mkdir 失败 / 文件系统错误 / 未知错误。
    """
    # YYYY-MM-DD 字典序与日期序一致，直接字符串排序
    dates_list = sorted(output_df["date"].unique().tolist())

    # mkdir 单独 try：异常信息更精确
    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        logger.error("创建输出目录失败: %s, 原因: %s (%s)", output_path.parent, type(e).__name__, str(e))
        raise RuntimeError(f"创建输出目录失败: {output_path.parent}, {type(e).__name__}: {e}") from e

    # 临时文件 + os.replace 原子写入；流式分批避免 OOM
    temp_path = output_path.parent / (output_path.name + ".tmp")
    replaced = False
    try:
        with gzip.open(temp_path, "wt", encoding="utf-8") as f:
            f.write('{"dates": ')
            json.dump(dates_list, f, ensure_ascii=False)
            f.write(', "data": [')

            # 逐条写而非 json.dump(batch_records)：后者输出 [...] 拼接后嵌套
            total_rows = len(output_df)
            first_record = True
            for batch_start in range(0, total_rows, batch_size):
                batch_end = min(batch_start + batch_size, total_rows)
                batch_df = output_df.iloc[batch_start:batch_end]
                batch_records = batch_df.to_dict("records")
                batch_records = _nan_to_null(batch_records)
                for record in batch_records:
                    if not first_record:
                        f.write(",\n")
                    json.dump(record, f, ensure_ascii=False)
                    first_record = False
                del batch_df, batch_records

            f.write("]}")

        os.replace(temp_path, output_path)
        replaced = True
        # R5: 文件级完整性信号
        logger.info("  输出文件大小: %.2f MB", output_path.stat().st_size / 1024**2)
    except OSError as e:
        # PermissionError 是 OSError 子类
        logger.error("文件系统错误保存失败: %s, 原因: %s (%s)", output_path, type(e).__name__, str(e))
        raise RuntimeError(f"文件系统错误: {output_path}, {type(e).__name__}: {e}") from e
    except Exception as e:
        logger.error("未知错误保存失败: %s, 原因: %s (%s)", output_path, type(e).__name__, str(e))
        raise RuntimeError(f"未知错误保存失败: {output_path}, {type(e).__name__}: {e}") from e
    finally:
        # 仅 os.replace 未成功时清理
        if not replaced:
            temp_path.unlink(missing_ok=True)


# --- logger 获取 ---


def get_module_logger(logger: logging.Logger | None = None) -> logging.Logger:
    """获取模块 logger（None → 模块级 fallback；非 None → 透传调用方 logger）。

    Args:
        logger: 调用方传入的 logger（可选）。

    Returns:
        模块 logger 或调用方传入的 logger。

    Raises:
        TypeError: logger 参数不是 logging.Logger 类型。
    """
    if logger is None:
        return _MODULE_LOGGER
    if not isinstance(logger, logging.Logger):
        raise TypeError(f"logger 必须是 logging.Logger 类型，实际类型: {type(logger).__name__}")
    return logger


# --- 统一因子生成入口 ---


def _load_and_merge_data(
    factor_data_path: Path,
    turnover_data_path: Path,
    return_data_path: Path,
    logger: logging.Logger,
) -> pd.DataFrame:
    """Step 1~3：加载基础因子 + 换手率 + 收益数据，合并为 factor_df。

    Raises:
        FileNotFoundError: 输入数据文件不存在。
        ValueError: 数据格式不正确、JSON 解析失败、gzip 损坏。
    """
    # ========== Step 1: 加载基础因子数据 ==========
    logger.info("Step 1: 加载基础因子数据...")

    base_data_records = _load_json_gz_data(factor_data_path, "基础因子", logger)

    factor_df = pd.DataFrame(base_data_records)
    # format='mixed'：兼容上游不同日期格式
    factor_df["date"] = pd.to_datetime(factor_df["date"], format="mixed")

    del base_data_records

    logger.info("  基础数据记录数: %d", len(factor_df))
    # 动态识别基础因子列（剔除 OHLCV+索引列）
    base_factor_cols = [c for c in factor_df.columns if c not in _OHLCV_INDEX_COLS]
    logger.info("  基础因子列: %s", base_factor_cols)

    # ========== Step 2: 加载换手率数据 ==========
    logger.info("Step 2: 加载换手率数据...")

    turnover_records = _load_json_gz_data(turnover_data_path, "换手率", logger)

    turnover_df = pd.DataFrame(turnover_records)
    turnover_df["date"] = pd.to_datetime(turnover_df["date"], format="mixed")

    del turnover_records

    logger.info("  换手率数据记录数: %d", len(turnover_df))

    factor_df = factor_df.merge(turnover_df[["date", "asset", "turnover_rate"]], on=["date", "asset"], how="left")
    del turnover_df

    turnover_missing = int(factor_df["turnover_rate"].isna().sum())
    if turnover_missing > 0:
        logger.warning("  换手率缺失记录数: %d (%.2f%%)", turnover_missing, _calc_pct(turnover_missing, len(factor_df)))

    logger.info("  合并后记录数: %d", len(factor_df))

    # ========== Step 3: 加载收益数据 ==========
    logger.info("Step 3: 加载收益数据...")

    return_records = _load_json_gz_data(return_data_path, "收益", logger)

    return_df = pd.DataFrame(return_records)
    return_df["date"] = pd.to_datetime(return_df["date"], format="mixed")

    del return_records

    logger.info("  收益数据记录数: %d", len(return_df))

    factor_df = factor_df.merge(return_df[["date", "asset"] + list(_RETURN_COLS)], on=["date", "asset"], how="left")
    del return_df

    for col in _RETURN_COLS:
        # R4: col_missing 循环局部变量（原 return_missing 语义跨列混淆）
        col_missing = int(factor_df[col].isna().sum())
        if col_missing > 0:
            logger.warning("  %s 缺失记录数: %d (%.2f%%)", col, col_missing, _calc_pct(col_missing, len(factor_df)))

    logger.info("  合并收益后记录数: %d", len(factor_df))

    return factor_df


def _run_factor_pipeline(
    factor_df: pd.DataFrame,
    logger: logging.Logger,
) -> tuple[pd.DataFrame, dict[str, int]]:
    """Step 3.5~11.9：执行因子管线。

    详情见 _FACTOR_PIPELINE_STEPS 表（27 个 step，31 个输出列）。

    Returns:
        (factor_df, valid_counts)。
    """
    valid_counts: dict[str, int] = {}
    for step in _FACTOR_PIPELINE_STEPS:
        factor_df, step_valid_counts = _run_pipeline_step(factor_df, step, logger)
        valid_counts.update(step_valid_counts)

    # step 11.7~11.9 添加的 industry 临时列不属于 _OUTPUT_COLS
    factor_df = _drop_industry_column(factor_df)

    return factor_df, valid_counts


def _format_and_write_output(
    factor_df: pd.DataFrame,
    output_path: Path,
    start_time: datetime,
    logger: logging.Logger,
) -> dict[str, Any]:
    """Step 12~15：格式化输出 + 保存 + 返回元数据。

    input_sources 由调用方 generate_all_factors 写入 metadata。

    Raises:
        KeyError: 必需输出列不存在。
        RuntimeError: 文件系统错误。
    """
    # ========== Step 12: 格式化输出 ==========
    logger.info("Step 12: 格式化输出...")

    # date 列可能已转为字符串
    if pd.api.types.is_datetime64_any_dtype(factor_df["date"]):
        factor_df["date"] = factor_df["date"].dt.strftime("%Y-%m-%d")

    # 检查列是否存在
    missing_cols = [col for col in _OUTPUT_COLS if col not in factor_df.columns]
    if missing_cols:
        raise KeyError(f"输出列不存在: {missing_cols}，请检查因子计算函数的输出列名是否与 _EXTENDED_FACTOR_COLS 一致")

    # 提前切片 + del factor_df：missing_cols 已通过，列选择不会再抛 KeyError；
    # cast：pandas 列选择推断为 DataFrame | Series，运行时实为 DataFrame
    # sentinel：若 cast 本身异常，output_df 未赋值，finally 的 del 会抛 NameError
    output_df: pd.DataFrame | None = None
    try:
        output_df = cast(pd.DataFrame, factor_df[list(_OUTPUT_COLS)].copy())
    finally:
        # cast 成功：factor_df 立即释放；cast 失败：factor_df 随栈展开释放
        del factor_df

    # try/finally：异常路径也释放 output_df
    try:
        # ========== Step 13: 保存输出 ==========
        logger.info("Step 13: 保存输出...")

        total_records = len(output_df)
        _write_factor_json_gz(output_df, output_path, logger)

        logger.info("  输出路径: %s", output_path)
        logger.info("  输出记录数: %d", total_records)

        # 计算运行耗时
        end_time = datetime.now()
        elapsed_seconds = (end_time - start_time).total_seconds()

        # ========== Step 14: 返回元数据 ==========
        # metadata 字段顺序为契约：valid_records 按 _VALID_KEY_ORDER 排序

        metadata: dict[str, Any] = {
            "generated_at": end_time.strftime("%Y-%m-%d %H:%M:%S"),
            "elapsed_seconds": round(elapsed_seconds, 2),
            "total_records": total_records,
        }

        logger.info("=" * 40)
        logger.info("因子生成完成")
        logger.info("生成时间: %s", metadata["generated_at"])
        logger.info("运行耗时: %.2f 秒", metadata["elapsed_seconds"])
        logger.info("因子列: %s", list(_EXTENDED_FACTOR_COLS))
        logger.info("=" * 40)

        # ========== Step 15: 写出列名清单 ==========
        # 供 factor_ic 模块校验 required_columns；_atomic_write_json 保证原子性
        columns_path = output_path.parent / "factor_ic_data_columns.json"
        try:
            columns_manifest = {
                "base_cols": list(_BASE_COLS),
                "extended_factor_cols": list(_EXTENDED_FACTOR_COLS),
                "return_cols": list(_RETURN_COLS),
                "all_cols": list(_OUTPUT_COLS),
                "generated_at": metadata["generated_at"],
            }
            _atomic_write_json(columns_manifest, columns_path, logger)
            logger.info("列名清单已保存: %s", columns_path)
        except OSError as e:
            # 列名清单写入失败不阻塞主流程
            logger.warning("列名清单保存失败: %s, 原因: %s", columns_path, e)

        return metadata
    finally:
        # output_df sentinel：cast 失败时 output_df=None，跳过 del 防止 NameError
        if output_df is not None:
            del output_df


def generate_all_factors(
    factor_data_path: Path | str | None = None,
    turnover_data_path: Path | str | None = None,
    return_data_path: Path | str | None = None,
    output_path: Path | str | None = None,
    logger: logging.Logger | None = None,
) -> dict[str, Any]:
    """生成所有因子数据，输出 factor_ic_data.json.gz + factor_ic_data_columns.json。

    Args:
        factor_data_path: 基础因子数据路径（默认 factor_data.json.gz）。
        turnover_data_path: 换手率数据路径（默认 turnover_rate_data.json.gz）。
        return_data_path: 收益数据路径（默认 return_data.json.gz）。
        output_path: 输出路径（默认 factor_ic_data.json.gz）。
        logger: 调用方传入的 logger（可选）。

    Returns:
        元数据字典。

    Raises:
        FileNotFoundError: 输入数据文件不存在。
        ValueError: 数据格式不正确、JSON 解析失败、gzip 损坏。
        KeyError: 必需输出列不存在。
        RuntimeError: 文件系统错误或未知保存错误。
    """
    start_time = datetime.now()
    logger = get_module_logger(logger)

    # 默认路径
    factor_data_path = Path(factor_data_path) if factor_data_path else _DEFAULT_RESULT_DIR / "factor_data.json.gz"
    turnover_data_path = (
        Path(turnover_data_path) if turnover_data_path else _DEFAULT_RESULT_DIR / "turnover_rate_data.json.gz"
    )
    return_data_path = Path(return_data_path) if return_data_path else _DEFAULT_RESULT_DIR / "return_data.json.gz"
    output_path = Path(output_path) if output_path else _DEFAULT_RESULT_DIR / "factor_ic_data.json.gz"

    logger.info("=" * 40)
    logger.info("统一因子生成模块")
    logger.info("=" * 40)

    # Step 1~3：加载 + 合并
    factor_df = _load_and_merge_data(factor_data_path, turnover_data_path, return_data_path, logger)

    # Step 3.5~11.9：因子管线
    factor_df, valid_counts = _run_factor_pipeline(factor_df, logger)

    # Step 12~15：格式化 + 输出 + 元数据
    metadata = _format_and_write_output(
        factor_df, output_path, start_time, logger
    )

    # 补充 valid_counts 相关元数据
    total_records = metadata["total_records"]
    metadata["valid_records"] = {key: valid_counts[key] for key in _VALID_KEY_ORDER}
    metadata["valid_records_percent"] = {key: _calc_pct(valid_counts[key], total_records) for key in _VALID_KEY_ORDER}
    metadata["factor_columns"] = list(_EXTENDED_FACTOR_COLS)
    metadata["return_columns"] = list(_RETURN_COLS)
    metadata["input_sources"] = {
        "factor_data": str(factor_data_path),
        "turnover_data": str(turnover_data_path),
        "return_data": str(return_data_path),
    }
    metadata["output_path"] = str(output_path)

    return metadata


# --- CLI 入口 ---


def main() -> int:
    """CLI 主入口"""
    parser = argparse.ArgumentParser(description="统一因子生成模块（含收益数据）")
    parser.add_argument("--factor_data", type=str, default=None, help="基础因子数据路径")
    parser.add_argument("--turnover_data", type=str, default=None, help="换手率数据路径")
    parser.add_argument("--return_data", type=str, default=None, help="收益数据路径")
    parser.add_argument("--output", type=str, default=None, help="输出路径")
    parser.add_argument("--quiet", action="store_true", help="静默模式（只输出 ERROR 级别日志）")

    args = parser.parse_args()

    log_level = logging.ERROR if args.quiet else logging.INFO
    logger = setup_logger("factor_generator", level=log_level)

    factor_data_path = Path(args.factor_data) if args.factor_data else None
    turnover_data_path = Path(args.turnover_data) if args.turnover_data else None
    return_data_path = Path(args.return_data) if args.return_data else None
    output_path = Path(args.output) if args.output else None

    try:
        metadata = generate_all_factors(
            factor_data_path=factor_data_path,
            turnover_data_path=turnover_data_path,
            return_data_path=return_data_path,
            output_path=output_path,
            logger=logger,
        )
        # CLI 摘要：quiet 走 print（绕过 logger 级别过滤），非 quiet 走 logger
        summary_msg = (
            f"执行摘要: 总记录数={metadata['total_records']}, "
            f"耗时={metadata['elapsed_seconds']:.2f}秒, "
            f"输出路径={metadata['output_path']}"
        )
        success_msg = "执行成功，退出码: 0"
        if args.quiet:
            print(summary_msg)
            print(success_msg)
        else:
            logger.info(
                "执行摘要: 总记录数=%d, 耗时=%.2f秒, 输出路径=%s",
                metadata["total_records"],
                metadata["elapsed_seconds"],
                metadata["output_path"],
            )
            logger.info("执行成功，退出码: 0")
        return 0
    except Exception as e:
        # data_fetchers MODULE.md R10: 类型名 + logger.exception 自动附堆栈
        logger.exception("执行失败 [%s]", type(e).__name__)
        # quiet 失败补 print 到 stderr，与成功路径输出对称
        if args.quiet:
            print(f"执行失败: {type(e).__name__}: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
