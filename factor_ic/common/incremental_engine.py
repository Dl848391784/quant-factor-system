#!/usr/bin/env python3
"""
增量更新引擎 - factor_ic 公共模块

功能：
1. 读取现有缓存
2. 筛选缺失日期
3. 逐日计算 IC（复用 ic_calculator.calculate_single_day_ic）
4. 合并去重（新值覆盖旧值）
5. 重算统计指标（复用 ic_calculator.calculate_ic_statistics）

作者: 云瑶
日期: 2026-05-22
"""

import json
from datetime import datetime
from enum import Enum
from pathlib import Path

import pandas as pd

from .convert_types import convert_to_native_types
from .data_completeness import _normalize_dates
from .ic_calculator import calculate_ic_statistics, calculate_single_day_ic
from .logger_config import get_logger


# 初始化 logger
logger = get_logger(__name__)


def _to_date_str(d) -> str:
    """将任意日期值统一标准化为 YYYY-MM-DD 字符串格式。

    处理以下类型：
    - datetime64 / Timestamp → 截断时间部分
    - str "2026-05-22 00:00:00" → 截断时间部分
    - str "2026/05/22" → 替换分隔符
    - NaT / None / NaN / 字面量 "NaT" / "nat" / "None" → 返回空字符串

    设计理由：日期标准化逻辑在代码中多处重复（5+处），违反 DRY；
    统一提取确保格式行为一致，避免一处修改遗漏其他位置。
    """
    if pd.isna(d):
        return ""
    result = str(d).split(" ")[0].replace("/", "-")
    # 兜底拦截：object 列可能含字面量字符串 "NaT"/"nat"/"None"，
    # pd.isna("NaT") 返回 False 导致其被当作有效日期
    if not result or result.lower() in ("nat", "none"):
        return ""
    return result


# 更新模式枚举（三值返回，语义清晰）
class UpdateMode(Enum):
    INCREMENTAL = "incremental"  # 缓存滞后，增量更新
    FULL = "full"  # 缓存不存在，全量计算
    SKIP = "skip"  # 缓存已最新，无需计算


def get_cache_latest_date(cache_path: Path) -> str | None:
    """
    获取缓存最新日期（复用 data_completeness 日期标准化逻辑）

    参数:
        cache_path: IC 结果缓存路径（直接传入 Path，而非因子名）

    返回:
        最新日期字符串（YYYY-MM-DD），若缓存不存在则返回 None

    设计说明:
        复用 _normalize_dates 函数，确保日期格式标准化（去重、排序）
        与 data_completeness.py 中同名函数职责不同（参数签名不同）
    """
    if not cache_path.exists():
        return None

    try:
        with open(cache_path, encoding="utf-8") as f:
            data = json.load(f)

        dates = data.get("dates", [])
        if not dates:
            return None

        # 使用公共函数标准化日期（确保 YYYY-MM-DD 格式，去重排序）
        dates = _normalize_dates(dates)

        return dates[-1] if dates else None

    except Exception as e:
        logger.warning("读取缓存最新日期失败 [%s] [%s]: %s", cache_path, type(e).__name__, e)
        return None


def _normalize_existing_data(existing_data: dict) -> dict:
    """
    对现有缓存数据做结构标准化，确保返回的字段与最新输出结构一致。

    防止旧版缓存缺少新增字段（如 statistical_significance、icir_stability 等）
    导致下游 KeyError 或语义不一致。

    规范:
        所有增量模式返回值必须经过标准化，绕过标准化直接返回原始缓存是违规行为
        （遵循 MODULE.md 规则 M30: 三模式输出结构等价）
    """
    # 浅拷贝：避免 mutate 传入的原字典（调用方可能还持有引用）
    existing_data = existing_data.copy()

    # 日期格式标准化：只截断时间部分和替换分隔符
    # 原因：缓存数据理应已去重排序，若 _normalize_dates 去重排序会导致
    # dates 和 ic_values 长度/顺序不一致（错位）
    # 但需要记录原始长度，以便同步裁剪 ic_values 等对齐字段
    original_dates = existing_data.get("dates", [])
    dates = [_to_date_str(d) for d in original_dates]

    # 同步裁剪：若日期标准化后存在空字符串条目（原始空日期或无效格式），
    # 需要同步裁剪 ic_values 和 rolling_ic_mean 对应位置的元素
    original_len = len(original_dates)
    kept_indices = [i for i, d in enumerate(dates) if d]  # 非空日期的位置
    if len(kept_indices) < original_len:
        dates = [dates[i] for i in kept_indices]

        # 同步裁剪 ic_values（若长度与原始 dates 一致）
        ic_values = existing_data.get("ic_values", [])
        if len(ic_values) == original_len:
            existing_data["ic_values"] = [ic_values[i] for i in kept_indices]

        # 同步裁剪 rolling_ic_mean（若长度与原始 dates 一致）
        rolling_ic_mean = existing_data.get("rolling_ic_mean", [])
        if len(rolling_ic_mean) == original_len:
            existing_data["rolling_ic_mean"] = [rolling_ic_mean[i] for i in kept_indices]

        # 同步裁剪 rolling_ic_mean_aligned（若存在且长度一致）
        rolling_ic_mean_aligned = existing_data.get("rolling_ic_mean_aligned", [])
        if len(rolling_ic_mean_aligned) == original_len:
            existing_data["rolling_ic_mean_aligned"] = [rolling_ic_mean_aligned[i] for i in kept_indices]

    # 统计指标字段：缺失时填充默认值（而非 None，避免下游 if 检查）
    existing_data.setdefault("ic_mean", 0.0)
    existing_data.setdefault("ic_std", 0.0)
    existing_data.setdefault("icir", 0.0)
    existing_data.setdefault("positive_ratio", 0.0)
    existing_data.setdefault("p_value", 1.0)
    existing_data.setdefault("p_value_display", "1.0000")
    existing_data.setdefault("rolling_ic_mean", [])
    existing_data.setdefault("valid_days", 0)

    # 五维度判断字段：缺失时填充空结构
    for key in (
        "statistical_significance",
        "factor_direction",
        "economic_significance",
        "icir_stability",
        "ic_distribution_consistency",
    ):
        existing_data.setdefault(key, {})

    # summary 字段：缺失时填充默认
    if "summary" not in existing_data:
        existing_data["summary"] = {
            "ic_performance": "未知",
            "statistical_significance": "未判断",
            "factor_direction": "未判断",
            "economic_significance": "未判断",
            "recommendation": "请结合五维度判断综合评估",
        }

    # 确保增量模式标识
    existing_data["update_mode"] = "skip"

    # 写回标准化后的 dates
    existing_data["dates"] = dates

    return existing_data


def read_existing_cache(cache_path: Path) -> tuple[dict | None, list[str], list[float | None]]:
    """
    读取现有缓存数据

    参数:
        cache_path: IC 结果缓存路径

    返回:
        (existing_data, existing_dates, existing_ic_values)
        - existing_data: 完整缓存数据（None 表示不存在）
        - existing_dates: 已有日期列表
        - existing_ic_values: 已有 IC 值列表

    异常:
        JSONDecodeError: 缓存损坏（严重错误，需调用方处理）
        OSError: 文件读取失败（严重错误）
    """
    if not cache_path.exists():
        return None, [], []

    try:
        with open(cache_path, encoding="utf-8") as f:
            existing_data = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        logger.error("读取现有缓存失败 [%s] [%s]: %s", cache_path, type(e).__name__, e)
        raise

    existing_dates = existing_data.get("dates", [])
    existing_ic_values = existing_data.get("ic_values", [])

    return existing_data, existing_dates, existing_ic_values


def calculate_missing_dates_ic(
    factor_df_full: pd.DataFrame,
    return_df_full: pd.DataFrame,
    missing_dates: list[str],
    factor_col: str,
    return_col: str = "forward_return",
    min_stocks: int = 10,
) -> tuple[list[str], list[float | None], dict]:
    """
        计算缺失日期的 IC

        参数:
            factor_df_full: 全量因子数据
            return_df_full: 全量收益数据
            missing_dates: 缺失日期列表
            factor_col: 因子列名
            return_col: 收益列名
            min_stocks: 最小股票数

        返回:
            (new_dates, new_ic_values, diagnostics)
            - new_dates: 实际计算日期列表（有数据的日期）
            - new_ic_values: 新计算的 IC 值列表
            - diagnostics: 诊断信息字典
    规范:
            增量计算必须复用 calculate_single_day_ic，确保算法一致性
    """
    missing_set = set(missing_dates)

    # 统一日期格式：先对 unique() 值构建映射字典，再用 .map() 向量化替换，
    # 避免 .apply() 逐行 Python 调用（百万行级 DataFrame 很慢）
    _factor_date_mapping = {d: _to_date_str(d) for d in factor_df_full["date"].unique()}
    factor_date_str = factor_df_full["date"].map(_factor_date_mapping)
    factor_df_new = factor_df_full[factor_date_str.isin(missing_set)].copy()
    factor_df_new["date"] = factor_date_str[factor_df_new.index]

    _return_date_mapping = {d: _to_date_str(d) for d in return_df_full["date"].unique()}
    return_date_str = return_df_full["date"].map(_return_date_mapping)
    return_df_new = return_df_full[return_date_str.isin(missing_set)].copy()
    return_df_new["date"] = return_date_str[return_df_new.index]

    # 诊断信息：检查缺失日期是否在因子数据中存在
    # 直接从 _factor_date_mapping.values() 构建标准化日期 set，
    # 避免重复遍历全量数据（mapping 已包含所有 unique 值的标准化结果）
    all_factor_dates_str = set(_factor_date_mapping.values())
    # 过滤掉空字符串（无效日期）
    all_factor_dates_str.discard("")
    phantom_dates = missing_set - all_factor_dates_str

    diagnostics = {
        "phantom_dates": sorted(phantom_dates)[:10],  # 幽灵日期示例
        "phantom_dates_count": len(phantom_dates),  # 幽灵日期数量
        "has_data": not factor_df_new.empty,
    }

    if phantom_dates:
        logger.warning("%s 个缺失日期不在因子数据中（幽灵日期）", len(phantom_dates))
        examples = diagnostics["phantom_dates"][:5]
        logger.warning("示例日期: %s", examples)

    if factor_df_new.empty:
        logger.debug("缺失日期无有效数据，跳过增量计算")
        return [], [], diagnostics

    logger.info("筛选后数据: %s 行", len(factor_df_new))

    # 逐日计算 IC（预分组避免重复全表扫描）
    factor_groups = dict(iter(factor_df_new.groupby("date")))
    return_groups = dict(iter(return_df_new.groupby("date")))
    new_dates = sorted(str(d) for d in factor_groups)
    new_ic_values = []
    skipped_count = 0

    for date in new_dates:
        day_factor = factor_groups[date]
        day_return = return_groups.get(date, pd.DataFrame())

        # 合并
        merged = day_factor.merge(day_return, on=["date", "asset"], how="inner")

        # 区分"无收益数据"与"股票数不足"
        if merged.empty and day_return.empty:
            logger.debug("日期 %s: 因子有数据但无收益数据，跳过", date)

        # 使用核心函数计算单日 IC（确保算法一致性）
        ic_value = calculate_single_day_ic(merged, factor_col=factor_col, return_col=return_col, min_stocks=min_stocks)

        if ic_value is not None:
            new_ic_values.append(round(ic_value, 6))
        else:
            new_ic_values.append(None)
            skipped_count += 1

    logger.info(
        "计算完成: %s 天，%s 天有效 IC",
        len(new_dates),
        len([v for v in new_ic_values if v is not None]),
    )
    if skipped_count > 0:
        logger.info("%s 天因股票数不足跳过", skipped_count)

    return new_dates, new_ic_values, diagnostics


def merge_ic_data(
    existing_dates: list[str],
    existing_ic_values: list[float | None],
    new_dates: list[str],
    new_ic_values: list[float | None],
) -> tuple[list[str], list[float | None], dict]:
    """
    合并 IC 数据（去重，新值覆盖旧值）

    参数:
        existing_dates: 已有日期列表
        existing_ic_values: 已有 IC 值列表
        new_dates: 新计算日期列表
        new_ic_values: 新计算 IC 值列表

    返回:
        (all_dates, all_ic_values, merge_info)
        - all_dates: 合并后日期列表（已排序）
        - all_ic_values: 合并后 IC 值列表
        - merge_info: 合并信息（重叠日期等）

    规范:
        使用字典去重，新值优先（后写入覆盖前写入）
    """
    # 检查重叠
    existing_set = set(existing_dates)
    new_set = set(new_dates)
    overlap_dates = existing_set & new_set

    merge_info = {
        "overlap_dates": sorted(overlap_dates),
        "overlap_count": len(overlap_dates),
        "existing_count": len(existing_dates),
        "new_count": len(new_dates),
    }

    if overlap_dates:
        examples = sorted(overlap_dates)[:5]
        logger.warning("发现 %s 个重叠日期，将使用新值覆盖，示例: %s", len(overlap_dates), examples)

    # 使用字典去重（新值覆盖旧值）
    date_ic_map = {}

    # 先写入历史值（保留 None，维持日期与 IC 值的对应关系）
    for date, ic in zip(existing_dates, existing_ic_values):
        date_ic_map[date] = ic  # 保留 None

    # 再写入新值（覆盖旧值，保留 None）
    for date, ic in zip(new_dates, new_ic_values):
        date_ic_map[date] = ic  # 新值覆盖，保留 None

    # 按日期排序（包含全部日期）
    all_dates = sorted(date_ic_map.keys())
    all_ic_values = [date_ic_map[d] for d in all_dates]  # 包含 None

    # 统计有效 IC 数量（用于日志）
    valid_count = len([v for v in all_ic_values if v is not None])

    logger.info("合并后总计: %s 天（%s 天有效 IC）", len(all_dates), valid_count)

    return all_dates, all_ic_values, merge_info


def recalculate_statistics(all_dates: list[str], all_ic_values: list[float | None]) -> dict:
    """
    重新计算统计指标

    参数:
        all_dates: 合并后日期列表
        all_ic_values: 合并后 IC 值列表

    返回:
        统计指标字典（ic_mean, ic_std, icir, positive_ratio, rolling_ic_mean 等）

    规范:
        增量模式必须使用 calculate_ic_statistics 重算统计（不手工构建）
        注意: 滚动参数由 calculate_ic_statistics 内部默认值决定（window=20, min_periods=10）
    """
    logger.info("统计重算: 重新计算统计指标...")

    # 过滤有效 IC 值
    valid_indices = [i for i, ic in enumerate(all_ic_values) if ic is not None]
    valid_indices_set = set(valid_indices)  # O(1) 成员检测，避免 O(n²)
    valid_dates = [all_dates[i] for i in valid_indices]
    valid_ic = [all_ic_values[i] for i in valid_indices]

    if not valid_ic:
        none_count = len([v for v in all_ic_values if v is None])
        logger.warning(
            "无有效 IC 值，返回空统计（总数据量: %s，None 值: %s）",
            len(all_ic_values),
            none_count,
        )
        return {
            "ic_mean": None,
            "ic_std": None,
            "icir": None,
            "positive_ratio": None,
            "p_value": None,
            "p_value_display": "N/A",
            "rolling_ic_mean": [],
            "rolling_ic_mean_aligned": [],
            "valid_indices": [],
            "valid_days": 0,
        }

    # 创建带日期索引的 Series
    ic_series = pd.Series(valid_ic, index=valid_dates)

    # 使用核心函数计算统计指标
    result = calculate_ic_statistics(ic_series)

    # 将 rolling_ic_mean 映射回 all_dates
    rolling_ic_mean_raw = result.get("rolling_ic_mean", [])

    # 长度校验：rolling_ic_mean 长度必须等于 valid_ic 长度
    # 若 calculate_ic_statistics 内部做了裁剪（如去 NaN），长度可能不匹配
    if len(rolling_ic_mean_raw) != len(valid_ic):
        logger.warning(
            "rolling_ic_mean 长度不匹配（期望 %s，实际 %s），使用 None 填充对齐位置",
            len(valid_ic),
            len(rolling_ic_mean_raw),
        )
        # fallback：长度不匹配时全部用 None 填充对齐位
        rolling_ic_mean_aligned = [None] * len(all_dates)
    else:
        rolling_ic_mean_aligned = []
        valid_idx = 0
        for i in range(len(all_dates)):
            if i in valid_indices_set:  # 使用 set 实现 O(1) 检测
                rolling_ic_mean_aligned.append(rolling_ic_mean_raw[valid_idx])
                valid_idx += 1
            else:
                rolling_ic_mean_aligned.append(None)

    result["rolling_ic_mean_aligned"] = rolling_ic_mean_aligned
    result["valid_indices"] = valid_indices
    result["valid_days"] = len(valid_ic)

    return result


def incremental_update_ic(
    output_path: Path,
    factor_df_full: pd.DataFrame,
    return_df_full: pd.DataFrame,
    raw_metadata: dict,
    factor_name: str,
    factor_col: str,
    return_col: str = "forward_return",
    min_stocks: int = 10,
    cache_data: dict | None = None,
) -> dict:
    """
    执行增量更新

    参数:
        output_path: 输出文件路径
        factor_df_full: 全量因子数据
        return_df_full: 全量收益数据
        raw_metadata: 原始数据元信息
        factor_name: 因子名称
        factor_col: 因子列名
        return_col: 收益列名
        min_stocks: 最小股票数
        cache_data: 已读缓存数据（可选，避免重复读文件）
            若提供，则跳过 read_existing_cache 直接使用此数据

    返回:
        增量更新结果字典

    异常:
        RuntimeError: 缓存不存在时抛出（调用方应转全量计算）

    流程（6 步）:
        1. 读取现有缓存 [1/6]
        2. 确定缺失日期 [2/6]
        3. 计算缺失日期 IC [3/6]
        4. 合并数据 [4/6]
        5. 重算统计指标 [5/6]
        6. 构建输出并保存 [6/6]
    """
    logger.info("=" * 40)
    logger.info("增量更新: %s", factor_name)
    logger.info("=" * 40)

    # 1. 读取现有缓存（优先使用已读缓存数据，避免重复读文件）
    logger.info("[1/6] 读取现有缓存...")
    if cache_data is not None:
        existing_data = cache_data
        existing_dates = existing_data.get("dates", [])
        existing_ic_values = existing_data.get("ic_values", [])
        logger.info("使用已读缓存数据: %s 天", len(existing_dates))
    else:
        try:
            existing_data, existing_dates, existing_ic_values = read_existing_cache(output_path)
            logger.info("现有数据: %s 天", len(existing_dates))
        except (json.JSONDecodeError, OSError) as e:
            logger.error("缓存文件读取失败: %s", e)
            raise RuntimeError(f"缓存文件读取失败，请删除后重算: {output_path}") from e

    if existing_data is None:
        logger.info("缓存不存在，需要全量计算")
        raise RuntimeError("缓存不存在，需要全量计算") from None

    # 2. 确定缺失日期
    logger.info("[2/6] 确定缺失日期...")

    # 标准化 existing_dates：缓存日期可能是旧格式（如 "2026/05/22"），
    # 未标准化直接参与 set 差集会导致与标准化后的 factor 日期无法匹配，
    # merge 时同一天以两种格式存在产生数据重复
    existing_dates_raw = existing_dates
    existing_dates = [_to_date_str(d) for d in existing_dates_raw]

    # 同步裁剪 existing_ic_values：若标准化过滤掉了空/无效日期条目，
    # 需同步裁剪对应位置的 ic_values（与 _normalize_existing_data 中逻辑一致）
    raw_len = len(existing_dates_raw)
    kept_indices = [i for i, d in enumerate(existing_dates) if d]
    if len(kept_indices) < raw_len:
        existing_dates = [existing_dates[i] for i in kept_indices]
        if len(existing_ic_values) == raw_len:
            existing_ic_values = [existing_ic_values[i] for i in kept_indices]

    cache_dates = set(existing_dates)
    # 统一日期格式：factor_df_full["date"] 可能是 datetime64/Timestamp 类型，
    # 与 cache_dates（str 类型）做 set 差集时类型不匹配会导致所有日期被误判为"缺失"
    all_factor_dates = {_to_date_str(d) for d in factor_df_full["date"].unique()}

    missing_dates = sorted(all_factor_dates - cache_dates)

    # 过滤掉空字符串（NaT 日期标准化后为 ""），防止被当作"缺失日期"传入计算流程
    missing_dates = [d for d in missing_dates if d]

    if not missing_dates:
        logger.info("无缺失日期，数据已完整")
        return _normalize_existing_data(existing_data)

    logger.info("缺失日期: %s 天", len(missing_dates))
    logger.debug("示例: %s", missing_dates[:5])

    # 3. 计算缺失日期 IC
    logger.info("[3/6] 计算缺失日期 IC...")
    new_dates, new_ic_values, diagnostics = calculate_missing_dates_ic(
        factor_df_full=factor_df_full,
        return_df_full=return_df_full,
        missing_dates=missing_dates,
        factor_col=factor_col,
        return_col=return_col,
        min_stocks=min_stocks,
    )

    if not new_dates:
        logger.debug("无新数据可计算，返回标准化后的现有缓存")
        return _normalize_existing_data(existing_data)

    # 4. 合并数据
    logger.info("[4/6] 合并数据...")
    all_dates, all_ic_values, merge_info = merge_ic_data(
        existing_dates=existing_dates,
        existing_ic_values=existing_ic_values,
        new_dates=new_dates,
        new_ic_values=new_ic_values,
    )

    # 5. 重算统计指标
    logger.info("[5/6] 重算统计指标...")
    stats = recalculate_statistics(all_dates, all_ic_values)

    # 6. 构建输出并保存
    # stats 已包含五维度判断结果,无需重复构建

    # 构建 ic_metrics（与 build_ic_result 结构一致）
    # None 值兜底：stats 值可能为 None（无有效 IC 时），f-string 需要安全格式化
    stats_ic_mean = stats["ic_mean"]
    stats_ic_std = stats["ic_std"]
    stats_icir = stats["icir"]
    stats_p_value = stats["p_value"]
    ic_metrics = {
        "ic_mean": stats_ic_mean,
        "ic_std": stats_ic_std,
        "icir": stats_icir,
        "p_value": stats_p_value,
        "p_value_display": stats.get(
            "p_value_display",
            f"{stats_p_value:.4f}" if stats_p_value is not None else "N/A",
        ),
    }

    # 构建 period
    period = {
        "start": all_dates[0] if all_dates else "",
        "end": all_dates[-1] if all_dates else "",
        "description": "增量更新合并后的日期范围",
    }

    # 构建 sample_stats
    sample_stats = {
        "total_days": raw_metadata.get("total_days", 0),
        "valid_days": stats["valid_days"],
        "avg_stocks_per_day": raw_metadata.get("avg_stocks_per_day", 0),
        "avg_stocks_period": {
            "start": all_dates[0] if all_dates else "",
            "end": all_dates[-1] if all_dates else "",
            "description": "过滤后每日平均股票数（dropna 后）",
        },
    }

    # 构建 summary（使用五维度判断结论）
    # 使用 (stats.get(...) or {}) 防御 None 值：若五维度字段为 None，.get() 会 AttributeError
    summary = {
        "ic_performance": stats.get(
            "ic_performance",
            f"IC均值={stats_ic_mean:.4f}, ICIR={stats_icir:.2f}"
            if stats_ic_mean is not None and stats_icir is not None
            else "无有效数据",
        ),
        "statistical_significance": (stats.get("statistical_significance") or {}).get("conclusion", "未判断"),
        "factor_direction": (stats.get("factor_direction") or {}).get("conclusion", "未判断"),
        "economic_significance": (stats.get("economic_significance") or {}).get("conclusion", "未判断"),
        "recommendation": stats.get("recommendation", "请结合五维度判断综合评估"),
    }

    # 组装完整结果（与 build_ic_result 结构一致）
    result = {
        "success": True,
        "factor_name": factor_name,
        "calculation_date": datetime.now().isoformat(),
        "period": period,
        "ic_metrics": ic_metrics,
        "sample_stats": sample_stats,
        "statistical_significance": stats.get("statistical_significance", {}),
        "factor_direction": stats.get("factor_direction", {}),
        "economic_significance": stats.get("economic_significance", {}),
        "icir_stability": stats.get("icir_stability", {}),
        "ic_distribution_consistency": stats.get("ic_distribution_consistency", {}),
        "dates": all_dates,
        "ic_values": all_ic_values,
        "rolling_ic_mean": stats["rolling_ic_mean_aligned"],
        "positive_ratio": stats.get("positive_ratio", 0.0),
        "summary": summary,
        "update_mode": "incremental",
        "incremental_info": {
            "new_dates_count": len(new_dates),
            "overlap_count": merge_info["overlap_count"],
            "diagnostics": diagnostics,
        },
    }

    # 保存
    output_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(convert_to_native_types(result), f, ensure_ascii=False, indent=2)
    except OSError as e:
        logger.error("保存增量更新结果失败 [%s] [%s]: %s", output_path, type(e).__name__, e)
        raise

    if stats_ic_mean is not None and stats_icir is not None:
        logger.info(
            "✓ 增量更新完成！新增 %s 天，总计 %s 天，IC均值=%.4f，ICIR=%.2f",
            len(new_dates),
            len(all_dates),
            stats_ic_mean,
            stats_icir,
        )
    elif stats_ic_mean is not None:
        logger.info(
            "✓ 增量更新完成！新增 %s 天，总计 %s 天，IC均值=%.4f，ICIR=无数据",
            len(new_dates),
            len(all_dates),
            stats_ic_mean,
        )
    else:
        logger.info(
            "✓ 增量更新完成！新增 %s 天，总计 %s 天，无有效 IC 数据",
            len(new_dates),
            len(all_dates),
        )
    logger.info("✓ 结果已保存: %s", output_path)

    return result


def should_use_incremental(
    output_path: Path,
    factor_df: pd.DataFrame,
    force_full: bool = False,
    cache_data: dict | None = None,
) -> UpdateMode:
    """
    判断是否使用增量模式

    参数:
        output_path: 输出文件路径
        factor_df: 因子数据 DataFrame
        force_full: 是否强制全量
        cache_data: 已读缓存数据（可选，避免重复读文件）
            若提供，则不再调用 get_cache_latest_date 读文件，
            直接从 cache_data 中提取最新日期

    返回:
        UpdateMode 枚举值：
        - INCREMENTAL: 缓存滞后，增量更新
        - FULL: 缓存不存在或损坏，全量计算
        - SKIP: 缓存已最新，无需计算

    判断逻辑:
        force_full = True → FULL
        缓存不存在 → FULL
        缓存存在 + 缓存日期 >= 因子日期 → SKIP
        缓存存在 + 缺失日期 > 0 → INCREMENTAL
    """
    if force_full:
        logger.info("模式判断: 强制全量计算")
        return UpdateMode.FULL

    if not output_path.exists():
        logger.info("模式判断: 缓存不存在，全量计算")
        return UpdateMode.FULL

    # 读取缓存最新日期（优先使用已读缓存数据，避免重复读文件）
    if cache_data is not None:
        dates = cache_data.get("dates", [])
        dates = _normalize_dates(dates)
        cache_latest = dates[-1] if dates else None
    else:
        cache_latest = get_cache_latest_date(output_path)
    if cache_latest is None:
        logger.info("模式判断: 缓存日期为空，全量计算")
        return UpdateMode.FULL

    # 因子数据最新日期（使用 pd.Timestamp 确保输出 YYYY-MM-DD 格式）
    # str(datetime64) 输出为 "2026-05-22 00:00:00" 而非 "2026-05-22"，后续比较会出错
    max_date_val = factor_df["date"].max()
    factor_latest = pd.Timestamp(str(max_date_val)).strftime("%Y-%m-%d") if not pd.isna(max_date_val) else ""

    # factor_latest 为空串时：因子数据无有效日期，需全量重算
    if not factor_latest:
        logger.warning("模式判断: 因子数据无有效日期，全量计算")
        return UpdateMode.FULL

    # 日期比较：显式转换为 YYYY-MM-DD 格式，避免格式不一致导致错误比较
    # 例如 '2026/05/22' 与 '2026-05-22' 字符串比较会出错
    cache_date_normalized = cache_latest.replace("/", "-")
    factor_date_normalized = factor_latest.replace("/", "-")

    if cache_date_normalized >= factor_date_normalized:
        logger.info("模式判断: 缓存已最新（%s >= %s），跳过更新", cache_latest, factor_latest)
        return UpdateMode.SKIP  # 缓存已最新，无需更新

    logger.info("模式判断: 缓存滞后（%s < %s），增量更新", cache_latest, factor_latest)
    return UpdateMode.INCREMENTAL
