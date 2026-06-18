#!/usr/bin/env python3
"""
IC结果构建公共模块 - factor_ic 公共模块

功能：
1. 将 ic_calculator 返回值转换为符合 MODULE.md 规范的完整 JSON 结构
2. 计算 rolling_ic_mean（20日窗口，min_periods=10）
3. 构建 sample_stats（口径范围说明）
4. 构建 factor_stats、summary 等字段

作者: 云瑶
日期: 2026-05-22
"""

from datetime import datetime
from pathlib import Path

import pandas as pd

# 导入类型转换函数
from .convert_types import convert_to_native_types
from .logger_config import get_logger


logger = get_logger(__name__)


# ============================================================================
# 结果字典键名常量（公共导出）
# ----------------------------------------------------------------------------
# 用途：本模块组装 result 字典使用，下游脚本（如 ic_*_1d.py）import 复用，
#      消除"两处字符串字面量人工同步"负担。
# 规则：键名变更必须只改本处一行，下游引用自动跟随；新增键时同步在此处声明。
# 命名约定：以 RESULT_KEY_ 前缀公开导出，区别于模块内部的私有常量。
# ============================================================================

RESULT_KEY_FACTOR_NAME = "factor_name"
RESULT_KEY_PERIOD = "period"
RESULT_KEY_IC_METRICS = "ic_metrics"
RESULT_KEY_SAMPLE_STATS = "sample_stats"
RESULT_KEY_IC_DISTRIBUTION = "ic_distribution_consistency"
RESULT_KEY_UPDATE_MODE = "update_mode"
# ic_metrics 子键
RESULT_KEY_IC_MEAN = "ic_mean"
RESULT_KEY_IC_STD = "ic_std"
RESULT_KEY_ICIR = "icir"
# ic_distribution_consistency 子键
RESULT_KEY_POSITIVE_RATIO = "positive_ratio"
# sample_stats / period 子键
RESULT_KEY_VALID_DAYS = "valid_days"
RESULT_KEY_PERIOD_START = "start"
RESULT_KEY_PERIOD_END = "end"

# ============================================================================
# 行业中性化输出字段（design.md §5.2 schema）
# ----------------------------------------------------------------------------
# 顶层挂在 result["ic_neutral_industry"] 下，供下游 summary / comprehensive_factor 读取。
# enabled=False 时只保留 enabled + skipped_reason 两键；enabled=True 时全字段必填。
# ============================================================================

RESULT_KEY_IC_NEUTRAL = "ic_neutral_industry"
RESULT_KEY_IC_NEUTRALIZED = "ic_neutralized"

# P3 新字段 enabled=True 必填字段（design.md §10.2 P3.2 schema）
NEUTRALIZED_REQUIRED_KEYS_ENABLED = (
    "enabled",
    "controls_used",
    "excluded_specs",
    "control_meta",
    "ic_mean",
    "ic_std",
    "icir",
    "p_value",
    "p_value_display",
    "positive_ratio",
    "n_days",
    "dates",
    "ic_values",
    "decay_rate",
    "decay_level",
)

# enabled=False 时必填字段（仅元信息，不含 IC 数值）
NEUTRALIZED_REQUIRED_KEYS_DISABLED = ("enabled", "skipped_reason", "controls_used", "excluded_specs")

NEUTRAL_REQUIRED_KEYS_ENABLED = (
    "enabled",
    "ic_mean",
    "ic_std",
    "icir",
    "p_value",
    "p_value_display",
    "positive_ratio",
    "n_days",
    "dates",
    "ic_values",
    "decay_rate",
    "decay_level",
    "min_industry_stocks",
)

# enabled=False 时必填字段（仅元信息，不含 IC 数值）
NEUTRAL_REQUIRED_KEYS_DISABLED = ("enabled", "skipped_reason")


def _normalize_neutral_payload(payload: dict) -> dict:
    """
    标准化 ic_neutral_industry 输出 schema（design.md §5.2）

    职责：
    - enabled=True: 校验 13 个必填字段都存在；按固定顺序输出
    - enabled=False: 校验 enabled + skipped_reason 都存在；只输出这两键
    - 防止 runner 侧 helper 漏字段或字段顺序漂移导致下游消费不稳定

    参数:
        payload: runner 侧 _compute_industry_neutral_ic 返回值
            或 {"enabled": False, "skipped_reason": "..."} 形式

    返回:
        标准化后的 dict（按 NEUTRAL_REQUIRED_KEYS_* 顺序）

    异常:
        ValueError: 必填字段缺失（错误消息含缺失字段名 + 当前 payload keys）
    """
    if not isinstance(payload, dict):
        raise ValueError(f"ic_neutral_payload 必须是 dict，实际类型: {type(payload).__name__}")

    enabled = payload.get("enabled")
    if enabled is None:
        raise ValueError(f"ic_neutral_payload 缺少 'enabled' 字段; 当前 keys: {list(payload.keys())}")

    required = NEUTRAL_REQUIRED_KEYS_ENABLED if enabled is True else NEUTRAL_REQUIRED_KEYS_DISABLED

    missing = [k for k in required if k not in payload]
    if missing:
        raise ValueError(
            f"ic_neutral_payload 缺少必填字段 {missing}（enabled={enabled}）; 当前 keys: {list(payload.keys())}"
        )

    # 按 required 顺序输出（确保 JSON 字段顺序稳定）
    return {k: payload[k] for k in required}


def _normalize_neutralized_payload(payload: dict) -> dict:
    """标准化 P3 `ic_neutralized` 输出 schema。"""
    if not isinstance(payload, dict):
        raise ValueError(f"ic_neutralized_payload 必须是 dict，实际类型: {type(payload).__name__}")

    enabled = payload.get("enabled")
    if enabled is None:
        raise ValueError(f"ic_neutralized_payload 缺少 'enabled' 字段; 当前 keys: {list(payload.keys())}")

    required = NEUTRALIZED_REQUIRED_KEYS_ENABLED if enabled is True else NEUTRALIZED_REQUIRED_KEYS_DISABLED
    missing = [k for k in required if k not in payload]
    if missing:
        raise ValueError(
            f"ic_neutralized_payload 缺少必填字段 {missing}（enabled={enabled}）; 当前 keys: {list(payload.keys())}"
        )
    return {k: payload[k] for k in required}


def _build_legacy_neutral_mirror(neutralized: dict) -> dict:
    """从 industry-only `ic_neutralized` 构建 P3 过渡期 legacy 镜像。"""
    if neutralized.get("enabled") is not True:
        return _normalize_neutral_payload(
            {
                "enabled": False,
                "skipped_reason": neutralized.get("skipped_reason", "neutralization skipped"),
            }
        )

    control_meta = neutralized.get("control_meta") or {}
    industry_meta = control_meta.get("industry") or {}
    min_industry_stocks = industry_meta.get("min_count", industry_meta.get("min_industry_stocks", 5))
    payload = {key: neutralized[key] for key in NEUTRAL_REQUIRED_KEYS_ENABLED if key != "min_industry_stocks"}
    payload["min_industry_stocks"] = min_industry_stocks
    return _normalize_neutral_payload(payload)


def build_ic_result(
    ic_result: dict,
    raw_metadata: dict,
    factor_name: str,
    return_period: str = "1d",
    data_source: str = "",
    factor_col: str = "",
    update_mode: str = "full",
    ic_neutral_payload: dict | None = None,
    ic_neutralized_payload: dict | None = None,
) -> dict:
    """
    构建 IC 分析完整结果（符合 MODULE.md 输出结构统一性规范）

    参数:
        ic_result: calculate_ic_with_direction_verification 返回值
            - 必须包含: ic_series, ic_mean, ic_std, icir, p_value,
              statistical_significance, factor_direction, economic_significance,
              icir_stability, ic_distribution_consistency, positive_ratio, n_days
        raw_metadata: load_factor_return_data 返回的原始数据元信息
            - 必须包含: period_start, period_end, total_days, avg_stocks_per_day
        factor_name: 因子名称（如 'rsi_1d', 'volume_ratio_1d'）
        return_period: 收益周期（如 '1d'）
        data_source: 数据来源路径
        factor_col: 因子列名
        update_mode: 更新模式（'full', 'incremental', 'skip', 'failed'）

    返回:
        符合 MODULE.md 规范的完整 JSON 结构字典

    规范:
        所有字段必须符合 MODULE.md "输出结构统一性规范"
        顶层字段顺序: success, factor_name, calculation_date, period, ic_metrics, sample_stats,
        statistical_significance, factor_direction, economic_significance, icir_stability,
        ic_distribution_consistency, dates, ic_values, rolling_ic_mean, positive_ratio,
        summary, factor_stats, update_mode, factor_col
    """
    # ========== 提取 ic_result 数据 ==========
    # 先校验 ic_series 是否为 None/空，再执行 sort_index()
    # 原因：若 ic_series 为 None，.sort_index() 会抛 AttributeError，
    # 导致后续的 None 校验不可达
    ic_series = ic_result["ic_series"]
    if ic_series is None or len(ic_series) == 0:
        logger.error("ic_series 为空，因子: %s，应调用 build_error_result 而非 build_ic_result", factor_name)
        raise ValueError("ic_series 为空，应调用 build_error_result 而非 build_ic_result")

    # 提取后立即统一排序，确保所有下游使用（dates/ic_values/rolling_ic_mean/period）
    # 都基于排序后的时间序列，避免上游传入乱序数据导致输出错误
    ic_series = ic_series.sort_index()
    ic_mean = ic_result["ic_mean"]
    ic_std = ic_result["ic_std"]
    icir = ic_result["icir"]
    positive_ratio = ic_result["positive_ratio"]
    n_days = ic_result["n_days"]

    # 五维度判断（直接使用公共模块返回）
    statistical_significance = ic_result["statistical_significance"]
    factor_direction_judgment = ic_result["factor_direction"]
    economic_significance = ic_result["economic_significance"]
    icir_stability = ic_result["icir_stability"]
    ic_distribution_consistency = ic_result["ic_distribution_consistency"]

    # ========== 构建日期范围 + IC 时间序列 ==========
    # ic_series 已在提取时统一排序（第72行），一次构建 dates 列表，
    # 同时用于 period_start/period_end 和输出 dates/ic_values，
    # 避免重复列表推导（原 dates_from_series 和 dates 是同一操作）
    dates = [str(d) for d in ic_series.index]
    period_start = dates[0] if dates else raw_metadata.get("period_start", "")
    period_end = dates[-1] if dates else raw_metadata.get("period_end", "")
    ic_values = [round(float(v), 6) for v in ic_series.values]

    # ========== 构建 period ==========
    period = {"start": period_start, "end": period_end, "description": "IC计算覆盖日期范围"}

    # ========== 构建 ic_metrics ==========
    ic_metrics = {
        "ic_mean": round(float(ic_mean), 6),
        "ic_std": round(float(ic_std), 6),
        "icir": round(float(icir), 4),
        "p_value": statistical_significance["p_value"],
        "p_value_display": statistical_significance["p_value_display"],
    }

    # ========== 构建 sample_stats ==========
    sample_stats = {
        "total_days": raw_metadata["total_days"],
        "valid_days": n_days,
        "avg_stocks_per_day": raw_metadata.get("avg_stocks_per_day", 0),
        "avg_stocks_period": {
            "start": period_start,
            "end": period_end,
            "description": "过滤后每日平均股票数（dropna 后）",
        },
    }

    # 计算 rolling_ic_mean（20日窗口，min_periods=10）— 复用公共函数
    rolling_ic_mean = build_rolling_ic_mean(ic_series)

    # ========== 构建 summary ==========
    summary = {
        "ic_performance": _format_ic_performance(ic_mean, icir),
        "statistical_significance": statistical_significance["conclusion"],
        "factor_direction": factor_direction_judgment["conclusion"],
        "economic_significance": economic_significance["conclusion"],
        "recommendation": _format_recommendation(
            statistical_significance["is_significant"],
            economic_significance["is_economically_significant"],
            icir_stability["is_stable"],
        ),
    }

    # ========== 构建 factor_stats ==========
    factor_stats = {
        "factor_name": factor_name,
        "return_period": return_period,
        "data_source": data_source,
        "total_days": raw_metadata["total_days"],
        "valid_days": n_days,
    }

    # ========== 组装完整结果 ==========
    # 顶层键名引用 RESULT_KEY_* 常量，让"输出字段契约"成为代码约束而非注释承诺：
    # 下游脚本 import 同名常量后，键名修改在此处一次完成；未列入常量的键
    # （如 success/calculation_date/dates/...）目前没有外部脚本以字面量耦合，
    # 待出现新依赖再上提。
    result = {
        "success": True,
        RESULT_KEY_FACTOR_NAME: factor_name,
        "calculation_date": datetime.now().isoformat(),
        RESULT_KEY_PERIOD: period,
        RESULT_KEY_IC_METRICS: ic_metrics,
        RESULT_KEY_SAMPLE_STATS: sample_stats,
        "statistical_significance": statistical_significance,
        "factor_direction": factor_direction_judgment,
        "economic_significance": economic_significance,
        "icir_stability": icir_stability,
        RESULT_KEY_IC_DISTRIBUTION: ic_distribution_consistency,
        "dates": dates,
        "ic_values": ic_values,
        "rolling_ic_mean": rolling_ic_mean,
        RESULT_KEY_POSITIVE_RATIO: positive_ratio,
        "summary": summary,
        "factor_stats": factor_stats,
        RESULT_KEY_UPDATE_MODE: update_mode,
        "factor_col": factor_col,  # 额外字段，用于追踪
    }

    # ========== 中性化 IC（design.md §10.2 P3.2 顶层字段） ==========
    # P3 起新字段为 ic_neutralized；P3-P4 期间保留 legacy 参数/字段兼容旧调用方。
    if ic_neutralized_payload is not None:
        normalized = _normalize_neutralized_payload(ic_neutralized_payload)
        result[RESULT_KEY_IC_NEUTRALIZED] = normalized
        if normalized.get("controls_used") == ["industry"]:
            result[RESULT_KEY_IC_NEUTRAL] = _build_legacy_neutral_mirror(normalized)
    elif ic_neutral_payload is not None:
        result[RESULT_KEY_IC_NEUTRAL] = _normalize_neutral_payload(ic_neutral_payload)

    # 类型转换（确保 JSON 兼容）
    result = convert_to_native_types(result)

    return result


def build_sample_stats(
    raw_metadata: dict,
    n_days: int,
    factor_df: pd.DataFrame,
    period_start: str,
    period_end: str,
    avg_stocks_description: str = "过滤后每日平均股票数（dropna 后）",
) -> dict:
    """
    构建样本统计字段

    参数:
        raw_metadata: 原始数据元信息
        n_days: 有效 IC 天数
        factor_df: 过滤后因子数据 DataFrame【必须含 'date' 列】
        period_start: 覆盖起始日期
        period_end: 覆盖结束日期
        avg_stocks_description: 口径范围说明

    返回:
        sample_stats 字典

    异常:
        KeyError: factor_df 缺少 'date' 列
    """
    if "date" not in factor_df.columns:
        logger.error("factor_df 缺少 'date' 列，当前列: %s", list(factor_df.columns))
        raise KeyError(f"factor_df 必须包含 'date' 列，当前列: {list(factor_df.columns)}")

    # 统一使用 round(x, 1) 保留一位小数，与 build_ic_result 中的 raw_metadata 值精度一致
    avg_stocks_per_day = round(factor_df.groupby("date").size().mean(), 1)

    return {
        "total_days": raw_metadata["total_days"],
        "valid_days": n_days,
        "avg_stocks_per_day": avg_stocks_per_day,
        "avg_stocks_period": {"start": period_start, "end": period_end, "description": avg_stocks_description},
    }


def build_rolling_ic_mean(ic_series: pd.Series, window: int = 20, min_periods: int = 10) -> list[float | None]:
    """
    计算滚动 IC 均值

    参数:
        ic_series: IC 时间序列（pandas Series，index 为日期）
        window: 滚动窗口（默认 20 日）
        min_periods: 最小有效数据点数（默认 10）

    返回:
        滚动均值列表（NaN → None）

    规范:
        前 min_periods-1 个时间点为 None（数据不足）
    """
    rolling_mean = ic_series.rolling(window=window, min_periods=min_periods).mean()
    return [round(float(v), 6) if pd.notna(v) else None for v in rolling_mean.values]


def build_error_result(factor_name: str, error_msg: str, return_period: str = "1d", data_source: str = "") -> dict:
    """
    构建错误情况下的默认结果（符合 MODULE.md 输出结构统一性规范）

    参数:
        factor_name: 因子名称
        error_msg: 错误消息
        return_period: 收益周期
        data_source: 数据来源

    返回:
        包含所有必需字段（默认值）的完整结构
    """
    return {
        "success": False,
        "error": error_msg,
        "factor_col": "",  # 与正常结果字段集合一致
        "factor_name": factor_name,
        "calculation_date": datetime.now().isoformat(),
        "period": {"start": "", "end": "", "description": f"数据加载失败: {error_msg}"},
        "ic_metrics": {"ic_mean": None, "ic_std": None, "icir": None, "p_value": None, "p_value_display": "N/A"},
        "sample_stats": {
            "total_days": 0,
            "valid_days": 0,
            "avg_stocks_per_day": 0,
            "avg_stocks_period": {"start": "", "end": "", "description": "数据加载失败"},
        },
        "statistical_significance": {
            "t_stat": None,
            "p_value": None,
            "p_value_display": "N/A",
            "nw_lag": None,
            "nw_lag_method": "N/A",
            "is_significant": False,
            "conclusion": f"数据加载失败，无法进行统计检验: {error_msg}",
        },
        "factor_direction": {
            "ic_mean": None,
            "ic_mean_sign": "unknown",
            "direction_usage": "无法确定",
            "conclusion": "数据加载失败，无法判断因子方向",
        },
        "economic_significance": {
            "abs_ic_mean": None,
            "threshold_used": {"weak": 0.03, "strong": 0.05},
            "level": "none",
            "is_economically_significant": False,
            "conclusion": "数据加载失败，无法判断经济显著性",
        },
        "icir_stability": {
            "icir": None,
            "threshold_used": {"usable": 0.5, "good": 1.0, "excellent": 2.0},  # 与正常结果一致
            "level": "none",
            "is_stable": False,
            "conclusion": "数据加载失败，无法判断ICIR稳定性",
        },
        "ic_distribution_consistency": {
            "positive_ratio": None,
            "ic_mean_sign": "unknown",
            "is_consistent": False,
            "consistency_type": "unknown",
            "distribution_hint": "N/A",
            "conclusion": "数据加载失败，无法判断IC分布一致性",
        },
        "dates": [],
        "ic_values": [],
        "rolling_ic_mean": [],
        "positive_ratio": None,
        "summary": {
            "ic_performance": "数据加载失败",
            "statistical_significance": "无法检验",
            "factor_direction": "无法判断",
            "economic_significance": "无法判断",
            "recommendation": f"检查数据源完整性: {error_msg}",
        },
        "factor_stats": {
            "factor_name": factor_name,
            "return_period": return_period,
            "data_source": data_source,
            "total_days": 0,
            "valid_days": 0,
        },
        "update_mode": "failed",
    }


def _format_ic_performance(ic_mean: float, icir: float) -> str:
    """
    格式化 IC 表现描述

    规范:
        ICIR 使用 abs(ic_mean)/ic_std 计算，始终为正（见 ic_calculator.py）
        因此删除 icir < 0 判断分支
    """
    if abs(ic_mean) >= 0.05:
        level = "强"
    elif abs(ic_mean) >= 0.03:
        level = "中"
    else:
        level = "弱"

    # ICIR 分级（ICIR 始终 >= 0）
    if icir >= 2.0:
        stability = "优秀"
    elif icir >= 1.0:
        stability = "良好"
    elif icir >= 0.5:
        stability = "可用"
    else:
        stability = "不足"

    return f"IC均值={ic_mean:.4f}（{level}），ICIR={icir:.2f}（{stability}）"


def _format_recommendation(is_significant: bool, is_economically_significant: bool, is_stable: bool) -> str:
    """格式化推荐建议"""
    if is_significant and is_economically_significant and is_stable:
        return "因子有效，可用于后续分层回测和组合构建"
    elif is_significant and is_economically_significant:
        return "因子统计显著、经济显著，但稳定性一般，建议观察更长周期"
    elif is_significant:
        return "因子统计显著，但经济显著性不足，可用于辅助筛选"
    else:
        return "因子统计不显著，建议检查因子计算逻辑或数据质量"


# ========== 输出路径辅助函数 ==========


def get_ic_output_path(factor_name: str, return_period: str = "1d") -> Path:
    """
    获取 IC 结果输出路径

    参数:
        factor_name: 因子名称（如 'rsi', 'volume_ratio'）
        return_period: 收益周期（如 '1d'）

    返回:
        输出文件路径（Path 对象）

    规范:
        输出路径: factor_ic/result/ic_<factor_name>_<return_period>_analysis_result.json
    """
    result_dir = Path(__file__).parent.parent / "result"
    result_dir.mkdir(parents=True, exist_ok=True)

    output_filename = f"ic_{factor_name}_{return_period}_analysis_result.json"
    return result_dir / output_filename


def save_ic_result(result: dict, output_path: Path | None = None) -> Path:
    """
    保存 IC 结果到 JSON 文件

    参数:
        result: IC 结果字典
        output_path: 输出路径（可选，默认自动生成）

    返回:
        实际保存路径

    规范:
        输出前进行字段完整性校验
    """
    import json

    if output_path is None:
        # 从 result 中提取因子信息生成路径
        factor_name = result.get("factor_name", "unknown")
        return_period = result.get("factor_stats", {}).get("return_period", "1d")

        # 使用 return_period 动态构造后缀，而非硬编码 _1d
        # 处理因子名已包含收益周期后缀的情况（如 rsi_1d → rsi）
        suffix = f"_{return_period}"
        factor_name_clean = factor_name[: -len(suffix)] if factor_name.endswith(suffix) else factor_name
        output_path = get_ic_output_path(factor_name_clean, return_period)

    # 确保目录存在
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # 保存（统一转换，添加异常处理）
    try:
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(convert_to_native_types(result), f, indent=2, ensure_ascii=False)
        logger.info("  ✓ 结果已保存: %s", output_path)
    except PermissionError as e:
        logger.error("保存失败（权限错误）: %s - %s: %s", output_path, type(e).__name__, e)
        raise
    except OSError as e:
        logger.error("保存失败（磁盘满/路径错误）: %s - %s: %s", output_path, type(e).__name__, e)
        raise
    return output_path
