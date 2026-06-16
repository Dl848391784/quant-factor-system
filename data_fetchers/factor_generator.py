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


# ============================================================================
# 条件导入：包内导入优先；脚本直接运行时（无父包）回退到绝对导入 + sys.path 注入
# ============================================================================
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

# 扩展因子列名（元组防止意外修改）。新增因子时同步更新 _VALID_KEY_ORDER + _FACTOR_PIPELINE_STEPS。
_EXTENDED_FACTOR_COLS: tuple[str, ...] = (
    "past_return_1d",  # 当日涨跌幅（PROJECT.md 规则：因子计算在 data_fetchers 完成）
    "bollinger_pb",
    "kdj_j",
    "turnover_surge",
    "amplitude",
    "price_position",
    "return_5d",  # momentum_strength 的前置依赖
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

# 基础列：索引 + 行情 + 基础因子 + 换手率 + 成交量（尾盘量比依赖）
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

# 纯 OHLCV + 索引列（不含 rsi_6/volume_ratio_5 等基础因子）：Step 1 日志识别基础因子列用。
_OHLCV_INDEX_COLS: frozenset[str] = frozenset({"date", "asset", "open", "close", "high", "low", "volume"})

# 输出列 = _BASE_COLS + _EXTENDED_FACTOR_COLS + _RETURN_COLS（动态拼接，避免硬编码列数）
_OUTPUT_COLS: tuple[str, ...] = _BASE_COLS + _EXTENDED_FACTOR_COLS + _RETURN_COLS

# 列数清单（供日志、metadata、回归测试使用）
_ALL_COLS_COUNTS: dict[str, int] = {
    "base_cols": len(_BASE_COLS),
    "extended_factor_cols": len(_EXTENDED_FACTOR_COLS),
    "return_cols": len(_RETURN_COLS),
    "total": len(_OUTPUT_COLS),
}


# ============================================================================
# 因子管线表（D 步表驱动重构）
# ============================================================================
# generate_all_factors step 3.5~11.9 的元数据描述。每项 dict 字段：
#   step_label     str       段头日志（"" 表示沿用上一段头）
#   factor_func    Callable  factor_calculator 公共 API（df, *, logger_arg) -> df
#   output_cols    tuple     本因子写入的列（tail=5 列，其它=1 列）
#   emit_valid_log bool      是否逐列打印 "  有效 xxx: N (P%)"（详见 _run_pipeline_step docstring）
#
# _VALID_KEY_ORDER 与本表集合等价但顺序不同（表序按 step 段，metadata 序按历史累积顺序）。
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
        "step_label": "",
        "factor_func": calculate_turnover_surge_delta,
        "output_cols": ("turnover_surge_delta",),
        "emit_valid_log": True,
    },
    {
        "step_label": "",
        "factor_func": calculate_tail_price_position_delta,
        "output_cols": ("tail_price_position_delta",),
        "emit_valid_log": True,
    },
    {
        "step_label": "",
        "factor_func": calculate_tail_volume_shrink_delta,
        "output_cols": ("tail_volume_shrink_delta",),
        "emit_valid_log": True,
    },
    # --- Step 11.6: 方向性因子（v1.41）---
    {
        "step_label": "Step 11.6: 计算方向性因子...",
        "factor_func": calculate_volume_price_strength,
        "output_cols": ("volume_price_strength",),
        # 段头因子打印 valid 行：调试时至少能从日志判断本段数据质量
        # 同段后续 3 个因子保持 False 避免日志刷屏
        "emit_valid_log": True,
    },
    {
        "step_label": "",
        "factor_func": calculate_positive_day_ratio_5,
        "output_cols": ("positive_day_ratio_5",),
        "emit_valid_log": False,
    },
    {
        "step_label": "",
        "factor_func": calculate_ma5_deviation,
        "output_cols": ("ma5_deviation",),
        "emit_valid_log": False,
    },
    {
        "step_label": "",
        "factor_func": calculate_near_high_ratio_5,
        "output_cols": ("near_high_ratio_5",),
        "emit_valid_log": False,
    },
    # --- Step 11.7: 行业级别方向性因子（v1.42）---
    {
        "step_label": "Step 11.7: 计算行业级别方向性因子...",
        "factor_func": calculate_industry_momentum_5d,
        "output_cols": ("industry_momentum_5d",),
        # 段头因子打印 valid 行（同 Step 11.6 段头）
        "emit_valid_log": True,
    },
    {
        "step_label": "",
        "factor_func": calculate_industry_turnover_trend,
        "output_cols": ("industry_turnover_trend",),
        "emit_valid_log": False,
    },
    {
        "step_label": "",
        "factor_func": calculate_industry_amplitude_trend,
        "output_cols": ("industry_amplitude_trend",),
        "emit_valid_log": False,
    },
    # --- Step 11.8: 行业基本面动量因子（v1.43 方案B）---
    {
        "step_label": "Step 11.8: 计算行业基本面动量因子...",
        "factor_func": calculate_industry_roe_trend,
        "output_cols": ("industry_roe_trend",),
        # 段头因子打印 valid 行（同 Step 11.6 段头）
        "emit_valid_log": True,
    },
    {
        "step_label": "",
        "factor_func": calculate_industry_earnings_growth,
        "output_cols": ("industry_earnings_growth",),
        "emit_valid_log": False,
    },
    {
        "step_label": "",
        "factor_func": calculate_industry_pe_trend,
        "output_cols": ("industry_pe_trend",),
        "emit_valid_log": False,
    },
    # --- Step 11.9: 资金流因子（v1.44 方案C）---
    {
        "step_label": "Step 11.9: 计算资金流因子...",
        "factor_func": calculate_capital_flow_ratio_trend,
        "output_cols": ("capital_flow_ratio_trend",),
        # 段头因子打印 valid 行（同 Step 11.6 段头）
        "emit_valid_log": True,
    },
    {
        "step_label": "",
        "factor_func": calculate_capital_flow_intensity,
        "output_cols": ("capital_flow_intensity",),
        "emit_valid_log": False,
    },
)


# metadata.valid_records / valid_records_percent 的 key 顺序：保 JSON 输出 byte 级稳定（下游 diff 无噪声）。
# 与 _FACTOR_PIPELINE_STEPS 集合等价但顺序不同（表序按 step 段，metadata 序按历史 v1.0~v1.44 累积顺序）。
_VALID_KEY_ORDER: tuple[str, ...] = (
    # v1.0 起的 9 项 + intraday_intensity
    "bollinger_pb",
    "kdj_j",
    "turnover_surge",
    "amplitude",
    "price_position",
    "past_return_1d",
    "overnight_ret",
    "return_5d",
    "momentum_strength",
    "intraday_intensity",
    # tail 5 列
    "tail_price_position",
    "tail_price_slope",
    "tail_price_volume_intensity",
    "tail_volume_acceleration",
    "tail_volume_shrink",
    # v1.40 差分因子
    "amplitude_delta",
    "turnover_surge_delta",
    "tail_price_position_delta",
    "tail_volume_shrink_delta",
    # v1.41 方向性因子
    "volume_price_strength",
    "positive_day_ratio_5",
    "ma5_deviation",
    "near_high_ratio_5",
    # v1.42 行业方向性因子
    "industry_momentum_5d",
    "industry_turnover_trend",
    "industry_amplitude_trend",
    # v1.43 行业基本面因子（方案B）
    "industry_roe_trend",
    "industry_earnings_growth",
    "industry_pe_trend",
    # v1.44 资金流因子（方案C）
    "capital_flow_ratio_trend",
    "capital_flow_intensity",
)

# 启动期一致性校验：防御新增因子时漏改表 / 漏加 metadata key
_PIPELINE_OUTPUT_COLS_SET = frozenset(col for step in _FACTOR_PIPELINE_STEPS for col in step["output_cols"])
_VALID_KEY_SET = frozenset(_VALID_KEY_ORDER)
if _VALID_KEY_SET != _PIPELINE_OUTPUT_COLS_SET:
    _missing_in_metadata = _PIPELINE_OUTPUT_COLS_SET - _VALID_KEY_SET
    _missing_in_table = _VALID_KEY_SET - _PIPELINE_OUTPUT_COLS_SET
    raise RuntimeError(
        f"_FACTOR_PIPELINE_STEPS / _VALID_KEY_ORDER 集合不一致："
        f"表多出={sorted(_missing_in_metadata)}，metadata 多出={sorted(_missing_in_table)}"
    )


# ============================================================================
# 模块级私有辅助函数
# ============================================================================


def _calc_pct(count: int, total: int) -> float:
    """计算百分比（除零保护 + 非有限值保护）。

    Args:
        count: 分子（有效记录数 / 缺失记录数等），int 或兼容类型（numpy.int64 / float）。
        total: 分母。total 或结果非有限（NaN/±inf）时返回 0.0，
               避免 inf 输入伪装成空数据（count/inf*100=0.0）或返回 inf。

    Returns:
        百分比（0.0~100.0，保留 2 位小数）。

    Example:
        >>> _calc_pct(80, 100)
        80.0
        >>> _calc_pct(50, 0)
        0.0
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

    流程：
    1. step["step_label"] 非空 → 打印段头日志
    2. 调用 step["factor_func"](factor_df, logger_arg=logger)
    3. 对每个 output_col 计算 valid_count = int(notna().sum())
    4. step["emit_valid_log"] 为 True 时逐列打印 "  有效 xxx: N (P%)"

    Args:
        factor_df: 当前 DataFrame（in-place 与否由 factor_func 决定）。
        step: _FACTOR_PIPELINE_STEPS 中的一项。
        logger: 日志器，作为 logger_arg 传给 factor_func。

    Returns:
        (factor_df, {output_col: notna_count})，调用方累积入 metadata。

    Raises:
        KeyError: factor_func 未生成全部 output_cols 时抛出，错误消息含函数名 +
                  缺失列名 + 实际生成列，便于精确归因（否则下游 notna() 抛的
                  KeyError 仅含列名，无法定位漏写的 factor_func）。

    Note:
        emit_valid_log 与 step_label 正交：
        - step_label：是否打印段头（"" 表示沿用上一段头）
        - emit_valid_log：是否对 output_cols 逐列打印 valid 行
        当前取值约定：step 3.5~11.5 全 True；step 11.6~11.9 仅段头 True
        （兼顾调试可观测性 + 日志简洁度，同段后续因子 False 避免刷屏）。
        emit_valid_log=False 时 valid_count 仍计入 metadata，不影响元数据完整性。
        改 emit_valid_log 取值 = 改运行时日志规格，需走需求评审。
    """
    step_label = step["step_label"]
    if step_label:
        logger.info(step_label)

    factor_func = step["factor_func"]
    factor_df = factor_func(factor_df, logger_arg=logger)

    output_cols: tuple[str, ...] = step["output_cols"]
    emit_valid_log: bool = step["emit_valid_log"]
    total_records = len(factor_df)
    valid_counts: dict[str, int] = {}

    # 提前校验 factor_func 是否生成了所有预期列
    # 否则下方 factor_df[col].notna() 会抛 KeyError，错误信息只含列名，
    # 无法定位是哪个 factor_func 漏写。这里显式 raise 给出精确归因。
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

    return factor_df, valid_counts


def _drop_industry_column(factor_df: pd.DataFrame) -> pd.DataFrame:
    """
    删除 industry 临时列（D 步表驱动重构辅助）

    industry 列由 step 11.7/11.8/11.9 的因子函数添加用于行业聚合赋值，
    不属于 _OUTPUT_COLS，必须在 metadata/输出前清理。

    Args:
        factor_df: 已完成 step 11.9 的 DataFrame

    Returns:
        删除 industry 列后的 DataFrame（若不存在则原样返回）

    Note:
        - 与原代码（行 ~870）字符级等价
        - if 守卫存在因为：方案A/B/C 因子被禁用时 industry 可能不存在
    """
    if "industry" in factor_df.columns:
        factor_df = factor_df.drop(columns=["industry"])
    return factor_df


def _load_json_gz_data(
    path: Path,
    dataset_label: str,
    logger: logging.Logger,
) -> list[dict[str, Any]]:
    """加载 gzip 压缩的 JSON 数据文件并提取 'data' 字段。

    统一封装 Step 1/2/3 的加载逻辑：gzip 解压 + JSON 解析 + 'data' 字段校验。
    异常类型 / 消息格式与重构前字符级一致。

    Args:
        path: 数据文件路径
        dataset_label: 数据集中文标签（用于错误消息），例 "基础因子" / "换手率" / "收益"
        logger: 日志器（gzip / JSON 解析失败时记录 error 日志）

    Returns:
        records: list[dict]，对应 JSON 文件 "data" 字段值

    Raises:
        FileNotFoundError: 文件不存在
        ValueError: gzip 损坏 / JSON 解析失败 / 缺少 'data' 字段

    Note:
        - 日志策略：gzip.BadGzipFile 与 json.JSONDecodeError 同为解析失败，
          统一在 except 块内打 logger.error 后再 raise，便于运维定位故障来源。
        - 内存安全：JSONDecodeError 仅引用 path / lineno / colno / msg 等小字段，
          不引用 e.doc（可能持有整个 JSON 文本副本）。
    """
    try:
        with gzip.open(path, "rt", encoding="utf-8") as f:
            payload = json.load(f)
    except FileNotFoundError:
        raise FileNotFoundError(f"{dataset_label}数据文件不存在: {path}") from None
    except gzip.BadGzipFile as e:
        logger.error("gzip 文件损坏: %s, 原因: %s", path, str(e))
        raise ValueError(f"gzip 文件损坏: {path}") from e
    except json.JSONDecodeError as e:
        # 内存安全：仅引用 path / lineno / colno / msg，不引用 e.doc（避免内存翻倍）
        logger.error("JSON解析失败: %s, 行 %d, 列 %d, 信息: %s", path, e.lineno, e.colno, e.msg)
        raise ValueError(f"JSON解析失败: {path}, 行 {e.lineno}, 列 {e.colno}, 信息: {e.msg}") from e

    # 数据验证：检查 'data' 字段存在
    if "data" not in payload:
        raise ValueError(f"{dataset_label}数据缺少 'data' 字段: {path}")

    return payload["data"]


def _nan_to_null(obj: Any) -> Any:
    """递归将 float NaN/inf/-inf 转 None，确保 JSON 严格合规。

    json.dump 默认把 float NaN 输出为 "NaN"（非法 JSON 值）；
    pandas to_dict('records') 把 NaN 输出为 float('nan') 而非 None。
    唯一可靠方案：遍历每条记录，NaN/inf → None → JSON 输出为 null。

    类型兼容：
    - Python float：直接命中 isinstance(obj, float)
    - numpy.float64：在 64 位系统上是 float 子类（也命中第一支）
    - numpy.float32 / numpy.float16：不是 float 子类，需 np.floating 兜底
    - bool：不是 float 子类，不会误判
    """
    if isinstance(obj, (float, np.floating)) and (math.isnan(obj) or math.isinf(obj)):
        return None
    if isinstance(obj, dict):
        return {k: _nan_to_null(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_nan_to_null(item) for item in obj]
    return obj


def _atomic_write_json(payload: Any, path: Path, logger: logging.Logger) -> None:
    """原子写出小型 JSON 文件（< 1MB）。

    用于 Step 15 列名清单等小文件场景，与 _write_factor_json_gz 的流式批写互补：
    - _write_factor_json_gz：大文件（百 MB 级），流式批写避免 OOM，gzip 压缩
    - _atomic_write_json：小文件（KB 级），全量 json.dump，不压缩

    实现细节（与 _write_factor_json_gz 对齐）：
    1. 写临时文件 path + ".tmp"
    2. os.replace 原子替换目标文件（标记 replaced=True）
    3. finally 中：os.replace 失败 → 清理临时文件；成功 → 不动目标文件

    Args:
        payload: 任意可 json.dump 的 Python 对象
        path: 目标文件路径
        logger: 日志器（OSError 时 warning + raise）

    Raises:
        OSError: 写入或替换失败（调用方决定是否降级为 warn）

    Note:
        - 不复用 _write_factor_json_gz：流式批写场景与全量写场景的数据流形态不同
        - replaced 标志避免 finally 误删已原子替换成功的目标文件
        - encoding='utf-8' + ensure_ascii=False：支持中文 / 因子名直接可读
    """
    temp_path = path.parent / (path.name + ".tmp")
    replaced = False
    try:
        with open(temp_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        os.replace(temp_path, path)
        replaced = True
    finally:
        # os.replace 成功后 temp_path 已不存在；失败则需清理
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

    封装 Step 13 的写出逻辑：mkdir + 流式批写 + NaN→null + 临时文件原子替换。
    异常类型 / 消息 / 日志格式与重构前字符级一致。

    Args:
        output_df: 已对齐 _OUTPUT_COLS 的输出 DataFrame
        output_path: 目标输出路径
        logger: 日志器
        batch_size: 流式写入批次大小（默认 50000，约 200MB 内存峰值）

    Raises:
        RuntimeError: mkdir 失败 / 写入文件系统错误 / 未知错误（含原因 + 类型名）
    """
    # dates 字段：字符串排序对 YYYY-MM-DD 格式正确（字典序与日期序一致）
    dates_list = sorted(output_df["date"].unique().tolist())

    # 确保父目录存在（职责分离：mkdir 单独处理，异常信息更精确）
    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        logger.error("创建输出目录失败: %s, 原因: %s (%s)", output_path.parent, type(e).__name__, str(e))
        raise RuntimeError(f"创建输出目录失败: {output_path.parent}, {type(e).__name__}: {e}") from e

    # 使用临时文件 + os.replace 原子写入（遵循 PROJECT.md 文件写入规范）
    # ⚠️ 内存优化: 流式写入 JSON，避免 output_df.to_dict("records") 一次性创建4GB+字典
    # 旧方法: json.dump({"dates": ..., "data": output_df.to_dict("records")}, f) → OOM
    # 新方法: 分批写入 {"dates": ..., "data": [row1, row2, ...]} → 内存峰值仅每批行数
    temp_path = output_path.parent / (output_path.name + ".tmp")
    replaced = False
    try:
        with gzip.open(temp_path, "wt", encoding="utf-8") as f:
            # 写入 JSON 头部
            f.write('{"dates": ')
            json.dump(dates_list, f, ensure_ascii=False)
            f.write(', "data": [')

            # 分批写入数据行（避免一次性 to_dict("records") 导致 OOM）
            # ⚠️ 关键: 逐条输出每个记录，而不是 json.dump(batch_records)（输出整个数组）
            # 因为 json.dump(batch_records) 会把每批输出为 [...]，逗号连接后变成 [[batch1], [batch2], ...]
            # 正确格式应该是 [record1, record2, ...]，不能嵌套
            total_rows = len(output_df)
            first_record = True
            for batch_start in range(0, total_rows, batch_size):
                batch_end = min(batch_start + batch_size, total_rows)
                batch_df = output_df.iloc[batch_start:batch_end]
                batch_records = batch_df.to_dict("records")
                # NaN→null 转换（确保 JSON 严格合规）
                batch_records = _nan_to_null(batch_records)
                # 逐条输出每个记录，逗号 + 换行分隔
                for record in batch_records:
                    if not first_record:
                        f.write(",\n")
                    json.dump(record, f, ensure_ascii=False)
                    first_record = False
                # 显式释放批次数据
                del batch_df, batch_records

            # 写入 JSON 尾部
            f.write("]}")

        os.replace(temp_path, output_path)
        replaced = True
    except OSError as e:
        # 文件系统错误（磁盘/权限/IO，PermissionError 是 OSError 子类）
        logger.error("文件系统错误保存失败: %s, 原因: %s (%s)", output_path, type(e).__name__, str(e))
        raise RuntimeError(f"文件系统错误: {output_path}, {type(e).__name__}: {e}") from e
    except Exception as e:
        # 未知错误（兜底）
        logger.error("未知错误保存失败: %s, 原因: %s (%s)", output_path, type(e).__name__, str(e))
        raise RuntimeError(f"未知错误保存失败: {output_path}, {type(e).__name__}: {e}") from e
    finally:
        # 仅在 os.replace 未成功执行时才清理临时文件，
        # 避免 replace 后再抛异常时误删已原子替换成功的目标文件。
        # missing_ok=True：原子操作，消除 TOCTOU 竞争窗口。
        if not replaced:
            temp_path.unlink(missing_ok=True)


# ============================================================================
# logger 获取函数（遵循 PROJECT.md 公共模块日志规范）
# ============================================================================


def get_module_logger(logger: logging.Logger | None = None) -> logging.Logger:
    """
    获取模块 logger

    Args:
        logger: 调用方传入的 logger（可选）

    Returns:
        logging.Logger: 模块 logger

    Raises:
        TypeError: logger 参数不是 logging.Logger 类型

    Note:
        - 如果 logger 为 None，返回模块级 fallback logger
        - 公共模块接收 logger 参数，日志可追溯调用方

    Example:
        >>> logger = get_module_logger()
        >>> logger.name
        'data_fetchers.factor_generator'
        >>> custom_logger = get_module_logger(logging.getLogger("my_app"))
        >>> custom_logger.name
        'my_app'
    """
    if logger is None:
        return _MODULE_LOGGER
    if not isinstance(logger, logging.Logger):
        raise TypeError(f"logger 必须是 logging.Logger 类型，实际类型: {type(logger).__name__}")
    return logger


# ============================================================================
# 统一因子生成入口
# ============================================================================


def generate_all_factors(
    factor_data_path: Path | str | None = None,
    turnover_data_path: Path | str | None = None,
    return_data_path: Path | str | None = None,
    output_path: Path | str | None = None,
    logger: logging.Logger | None = None,
) -> dict[str, Any]:
    """
    生成所有因子数据（含收益数据）

    Args:
        factor_data_path: 基础因子数据路径（默认 factor_data.json.gz）
        turnover_data_path: 换手率数据路径（默认 turnover_rate_data.json.gz）
        return_data_path: 收益数据路径（默认 return_data.json.gz）
        output_path: 输出路径（默认 factor_ic_data.json.gz）
        logger: 调用方传入的 logger（可选）

    Returns:
        Dict[str, Any]: 元数据字典（包含生成时间、因子列表、运行耗时等）

    Raises:
        FileNotFoundError: 输入数据文件不存在
        ValueError: 数据格式不正确（缺少 'data' 字段）、JSON 解析失败、gzip 文件损坏
        KeyError: 必需字段不存在（输出列不存在）
        RuntimeError: 文件系统错误（磁盘/权限/IO）或未知保存错误

    Note:
        - 输出到 data_fetchers/result/factor_ic_data.json.gz
        - 复用 factor_calculator 计算函数（遵循强制复用规范）
        - 公共模块接收 logger 参数，日志可追溯调用方
        - 运行耗时统计方便性能分析
        - 空数据场景：所有百分比计算均有除零保护，返回 0.0
        - JSONDecodeError 已内部捕获并转换为 ValueError，调用方不会收到 JSONDecodeError

    Example:
        # 以下为示例用法，非实际运行（generate_all_factors 需要输入数据文件）
        >>> from data_fetchers.factor_generator import generate_all_factors
        >>> metadata = generate_all_factors()  # 需要 data_fetchers/result/*.json.gz
        >>> metadata["factor_columns"]  # 返回列表副本，防止外部修改
        ['bollinger_pb', 'kdj_j', 'turnover_surge']
        >>> isinstance(metadata["elapsed_seconds"], float)
        True
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

    # ========== Step 1: 加载基础因子数据 ==========
    logger.info("Step 1: 加载基础因子数据...")

    base_data_records = _load_json_gz_data(factor_data_path, "基础因子", logger)

    factor_df = pd.DataFrame(base_data_records)
    # 使用 format='mixed' 处理不同日期格式（与 Step 2/3 保持一致）
    factor_df["date"] = pd.to_datetime(factor_df["date"], format="mixed")

    # 显式释放 base_data_records 内存（JSON 加载的大对象）
    del base_data_records

    logger.info("  基础数据记录数: %d", len(factor_df))
    # 动态反映实际基础因子列：剔除 OHLCV + 索引列，剩下即基础因子
    # 历史上此处硬编码 'rsi_6, volume_ratio_5'，若上游 fetch_factor_cache
    # 新增/删除基础因子列，日志会产生误导。改为从 factor_df.columns 实时计算。
    base_factor_cols = [c for c in factor_df.columns if c not in _OHLCV_INDEX_COLS]
    logger.info("  基础因子列: %s", base_factor_cols)

    # ========== Step 2: 加载换手率数据 ==========
    logger.info("Step 2: 加载换手率数据...")

    turnover_records = _load_json_gz_data(turnover_data_path, "换手率", logger)

    turnover_df = pd.DataFrame(turnover_records)
    # 使用 format='mixed' 处理不同日期格式（有的带时间，有的不带）
    turnover_df["date"] = pd.to_datetime(turnover_df["date"], format="mixed")

    # 显式释放 turnover_records 内存（JSON 加载的大对象）
    del turnover_records

    logger.info("  换手率数据记录数: %d", len(turnover_df))

    # 合并换手率
    factor_df = factor_df.merge(turnover_df[["date", "asset", "turnover_rate"]], on=["date", "asset"], how="left")

    # 显式释放 turnover_df 内存（merge 完成后不再需要）
    del turnover_df

    # 检查换手率缺失情况
    turnover_missing = int(factor_df["turnover_rate"].isna().sum())
    if turnover_missing > 0:
        logger.warning("  换手率缺失记录数: %d (%.2f%%)", turnover_missing, _calc_pct(turnover_missing, len(factor_df)))

    logger.info("  合并后记录数: %d", len(factor_df))

    # ========== Step 3: 加载收益数据 ==========
    logger.info("Step 3: 加载收益数据...")

    return_records = _load_json_gz_data(return_data_path, "收益", logger)

    return_df = pd.DataFrame(return_records)
    return_df["date"] = pd.to_datetime(return_df["date"], format="mixed")

    # 显式释放 return_records 内存（JSON 加载的大对象）
    del return_records

    logger.info("  收益数据记录数: %d", len(return_df))

    # 合并收益数据
    factor_df = factor_df.merge(return_df[["date", "asset"] + list(_RETURN_COLS)], on=["date", "asset"], how="left")

    # 显式释放 return_df 内存（merge 完成后不再需要）
    del return_df

    # 检查收益数据缺失情况
    for col in _RETURN_COLS:
        return_missing = int(factor_df[col].isna().sum())
        if return_missing > 0:
            logger.warning(
                "  %s 缺失记录数: %d (%.2f%%)", col, return_missing, _calc_pct(return_missing, len(factor_df))
            )

    logger.info("  合并收益后记录数: %d", len(factor_df))

    # ========== Step 3.5 ~ 11.9: 计算所有因子（D 步表驱动重构）==========
    # 详情见 _FACTOR_PIPELINE_STEPS 表（27 个 step，31 个输出列）+ _run_pipeline_step helper。
    # step 数 ≠ 输出列数：tail 因子单 step 输出 5 列，其它 step 单 step 输出 1 列。
    # 日志格式与 D 步重构前字符级一致：
    #   - step_label 非空时打印 "Step xx.x: ..."
    #   - emit_valid_log=True 时逐列打印 "  有效 xxx: N (P%)"
    valid_counts: dict[str, int] = {}
    for step in _FACTOR_PIPELINE_STEPS:
        factor_df, step_valid_counts = _run_pipeline_step(factor_df, step, logger)
        valid_counts.update(step_valid_counts)

    # step 11.7/11.8/11.9 的因子函数会添加 industry 临时列（用于行业聚合赋个股），
    # 不属于 _OUTPUT_COLS，统一在此删除。
    factor_df = _drop_industry_column(factor_df)

    # ========== Step 12: 格式化输出 ==========
    logger.info("Step 12: 格式化输出...")

    # date 列可能在 Step 11 已转换为字符串，需检查类型
    if pd.api.types.is_datetime64_any_dtype(factor_df["date"]):
        factor_df["date"] = factor_df["date"].dt.strftime("%Y-%m-%d")

    # 检查列是否存在（直接使用模块级常量 _OUTPUT_COLS）
    missing_cols = [col for col in _OUTPUT_COLS if col not in factor_df.columns]
    if missing_cols:
        raise KeyError(f"输出列不存在: {missing_cols}，请检查因子计算函数的输出列名是否与 _EXTENDED_FACTOR_COLS 一致")

    # output_df 初始化为 None（None sentinel pattern）：
    # 替代 finally 中基于 locals() 的存在性守卫——
    # locals() 在 CPython 中并不可靠（尤其在异常退出帧时）且每次调用构造新 dict，
    # 显式 None 初始化让 finally 的清理条件语义明确：output_df is not None 即已成功创建。
    output_df: pd.DataFrame | None = None

    # ========== Step 13~15 包裹在 try/finally 中，确保异常路径同样释放 output_df ==========
    # 正常路径：return 后栈解开，output_df 由 GC 回收
    # 异常路径：若 _write_factor_json_gz 等抛出 RuntimeError，本 finally 显式去除引用，
    #          避免外层调用方栈帧持续持有 output_df（重试 / 后续任务场景下尤其重要）
    try:
        # cast：pandas 重载使列选择推断为 DataFrame | Series，运行时实为 DataFrame
        output_df = cast(pd.DataFrame, factor_df[list(_OUTPUT_COLS)].copy())  # 元组转列表，pandas 列选择需要列表

        # 显式释放 factor_df 内存（可能包含中间列，比 output_df 更多）
        del factor_df
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
        # metadata 字段说明：
        # - generated_at: 生成时间（格式 YYYY-MM-DD HH:MM:SS）
        # - elapsed_seconds: 运行耗时（秒，精度 .2f）
        # - total_records: 输出总记录数
        # - valid_records: 各因子有效记录数（绝对值）
        # - valid_records_percent: 各因子有效记录百分比（与日志输出一致，便于质量评估）
        # - factor_columns: 扩展因子列名（不含基础列和基础因子）
        # - return_columns: 收益数据列名
        # - input_sources: 输入数据源路径
        # - output_path: 输出文件路径

        metadata = {
            "generated_at": end_time.strftime("%Y-%m-%d %H:%M:%S"),
            "elapsed_seconds": round(elapsed_seconds, 2),
            "total_records": total_records,
            "valid_records": {key: valid_counts[key] for key in _VALID_KEY_ORDER},
            "valid_records_percent": {key: _calc_pct(valid_counts[key], total_records) for key in _VALID_KEY_ORDER},
            "factor_columns": list(_EXTENDED_FACTOR_COLS),  # 扩展因子列（返回副本，防止外部修改）
            "return_columns": list(_RETURN_COLS),  # 收益数据列（返回副本，防止外部修改）
            "input_sources": {
                "factor_data": str(factor_data_path),
                "turnover_data": str(turnover_data_path),
                "return_data": str(return_data_path),
            },
            "output_path": str(output_path),
        }

        logger.info("=" * 40)
        logger.info("因子生成完成")
        logger.info("生成时间: %s", metadata["generated_at"])
        logger.info("运行耗时: %.2f 秒", metadata["elapsed_seconds"])
        logger.info("因子列: %s", metadata["factor_columns"])
        logger.info("=" * 40)

        # ========== Step 15: 写出列名清单（消费者 schema 查询） ==========
        # 遵循 factor_cols_literal_constant_design.md §3.5：
        # 将 _OUTPUT_COLS 结构化输出为独立 JSON 文件，供 factor_ic 模块
        # 校验 required_columns 是否与数据源对齐（M4 合规：读数据产物 ≠ import 模块）
        # 使用 _atomic_write_json 保证原子性：避免下游读到半写入的文件
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
            # 列名清单写入失败不应阻塞主流程（降级为 warn）
            logger.warning("列名清单保存失败: %s, 原因: %s", columns_path, e)

        return metadata
    finally:
        # 防御性释放：异常路径下显式去除 output_df 引用
        # 正常路径下 return 后函数栈解开，GC 会回收 output_df
        # 此处保留 del 显式表达意图：即使 Step 13/14/15 抛出异常，
        # output_df（约 30% factor_df 体积）也能立即去除局部引用。
        # 用 None sentinel 而非 locals()："is not None" 语义明确，
        # 不依赖 CPython locals() 实现，且零开销。
        if output_df is not None:
            del output_df


# ============================================================================
# CLI 入口
# ============================================================================


def main() -> int:
    """CLI 主入口"""
    parser = argparse.ArgumentParser(description="统一因子生成模块（含收益数据）")
    parser.add_argument("--factor_data", type=str, default=None, help="基础因子数据路径")
    parser.add_argument("--turnover_data", type=str, default=None, help="换手率数据路径")
    parser.add_argument("--return_data", type=str, default=None, help="收益数据路径")
    parser.add_argument("--output", type=str, default=None, help="输出路径")
    parser.add_argument("--quiet", action="store_true", help="静默模式（只输出 ERROR 级别日志）")

    args = parser.parse_args()

    # 设置日志级别
    log_level = logging.ERROR if args.quiet else logging.INFO
    logger = setup_logger("factor_generator", level=log_level)

    # 参数路径转换
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
        # CLI 入口执行摘要（关键元数据）
        # quiet 模式下日志级别为 ERROR，logger.info 会被过滤；
        # 摘要 + 退出码是脚本调用方判定成功的最小信号，必须始终输出 →
        # 非 quiet：走 logger.info（与正常日志格式一致）
        # quiet：走 print(stdout)（绕过 logger 级别过滤，给上游 CI / shell 留可读取信号）
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
        # quiet 模式下 logger 级别 = ERROR，logger.exception 走 stderr 仍可达；
        # 但成功路径 quiet 走 print(stdout)，为保持两条路径"输出可见性"对称，
        # quiet 失败也补一行 print 到 stderr，给上游 CI / shell 提供
        # 与成功路径一致的可读取信号（且不污染 stdout，便于管道判断）。
        if args.quiet:
            print(f"执行失败: {type(e).__name__}: {e}", file=sys.stderr)
        return 1


# ============================================================================
# __main__ CLI 入口
# ============================================================================

if __name__ == "__main__":
    # CLI 入口：调用 main() 函数，测试代码已移至 test_cases/test_factor_generator.py
    # 注意：sys 已在顶部条件块导入，无需重复导入
    sys.exit(main())
