#!/usr/bin/env python3
"""
因子IC计算主入口模板 - factor_ic 公共模块

功能：
1. 统一主入口逻辑（模式判断 → 分支调用 → 输出）
2. 封装全量/增量/跳过三种模式
3. 简化新增因子脚本的开发成本

模式判断流程（2026-05-23）：
1. 先调用 check_data_completeness 判断模式（不需要加载数据）
2. SKIP 模式：直接返回缓存数据（不加载全量数据，避免浪费）
3. FULL/INCREMENTAL 模式：再加载数据执行计算

增量模式职责划分（2026-05-23）：
- incremental_update_ic 负责保存结果（内部已调用 save_ic_result）
- factor_ic_runner 不再重复保存（避免双重写入）

作者: 云瑶
日期: 2026-05-22
最后修改: 2026-05-31（重构为单文件模式，删除双文件加载逻辑）
"""

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

# 导入数据加载（单文件模式）
# 导入数据完整性检查
from .control_providers import IndustryProvider, build_providers
from .control_providers.base import ControlProvider
from .data_completeness import check_data_completeness
from .data_loader import get_data_cache_path, load_factor_return_data

# 导入 FactorSpec（R3.3: run_factor_ic 新入口依赖）
from .factor_spec import FactorSpec

# 导入 IC 计算
from .ic_calculator import calculate_ic_with_direction_verification

# 导入结果构建
from .ic_result_builder import build_error_result, build_ic_result, get_ic_output_path, save_ic_result

# 导入增量引擎
from .incremental_engine import incremental_update_ic

# 导入日志
from .logger_config import get_logger


logger = get_logger(__name__)


# ============================================================
# 中性化排除清单（design.md §3.1, §4.1, §5.3）
# ============================================================
# 二维结构 NEUTRALIZE_EXCLUDED[control_name] -> frozenset[factor_name]：
# 每个控制变量独立维护一份 excluded 因子集合，原因类型可不同：
#   - "industry": 行业聚合赋个股的因子（行业内同值 → 残差≡0）
#   - "log_market_cap" (P2 起): 大/小盘强 beta 因子（待 P2 实证后补充）
#
# 兼容性: 旧名 INDUSTRY_NEUTRALIZE_EXCLUDED 作为 NEUTRALIZE_EXCLUDED["industry"]
# 的常量别名继续导出，下游测试与日志文本无需改动。
NEUTRALIZE_EXCLUDED: dict[str, frozenset[str]] = {
    "industry": frozenset(
        {
            "industry_momentum_5d",
            "industry_turnover_trend",
            "industry_amplitude_trend",
            "industry_roe_trend",
            "industry_earnings_growth",
            "industry_pe_trend",
            "capital_flow_intensity",
            "capital_flow_ratio_trend",
        }
    ),
    "log_market_cap": frozenset(
        {
            "log_market_cap",
        }
    ),
}

# 兼容别名（向后兼容；新代码请用 NEUTRALIZE_EXCLUDED["industry"]）
INDUSTRY_NEUTRALIZE_EXCLUDED: frozenset[str] = NEUTRALIZE_EXCLUDED["industry"]


def is_excluded(factor_name: str, control_name: str) -> bool:
    """因子 factor_name 是否被 control_name 控制变量的排除清单命中。

    未注册的 control_name 视为无排除规则（返回 False，不抛错），
    供未来新增 control 时无需先填表也能跑通。
    """
    return factor_name in NEUTRALIZE_EXCLUDED.get(control_name, frozenset())


DEFAULT_NEUTRALIZE_SPECS: list[str] = ["industry", "log_market_cap"]

# decay_rate 近零保护阈值（factor_ic_runner.py L274）
# |raw_ic_mean| < 0.001 时 IC 远低于经济显著性阈值(0.03)的 1/30,
# p-value 远超 0.05, 原始 IC 本身是噪声 → decay_rate 无统计意义, 置为 None
_DECAY_RATE_RAW_IC_FLOOR: float = 0.001


# skipped_reason 文本常量（写入输出 JSON 的 ic_neutralized.skipped_reason）
NEUTRALIZE_SKIP_REASON_EXCLUDED = "factor in INDUSTRY_NEUTRALIZE_EXCLUDED (industry-aggregated factor)"
NEUTRALIZE_SKIP_REASON_USER_DISABLED = "user disabled via neutralize=False"
NEUTRALIZE_SKIP_REASON_INCREMENTAL = "incremental mode (industry neutralization v1 supports full mode only)"
NEUTRALIZE_SKIP_REASON_SKIP_MODE = "skip mode (cached result, neutralization not recomputed)"


def _resolve_neutralize_specs(
    factor_name: str,
    neutralize: bool,
    mode: str,
    neutralize_specs: list[str] | None,
) -> tuple[list[str], str | None, list[str]]:
    """解析 P3 多 control 中性化 specs。

    返回 (effective_specs, skipped_reason, excluded_specs)。
    - neutralize=False / incremental / skip: 全局跳过，effective_specs=[]
    - full 且启用：默认 ["industry", "log_market_cap"]
    - 因子命中某 control 排除清单：只弹出该 control，其他 control 继续跑
    - 所有 control 都被弹出：返回 EXCLUDED skipped_reason
    """
    if mode == "incremental":
        return [], NEUTRALIZE_SKIP_REASON_INCREMENTAL, []
    if mode == "skip":
        return [], NEUTRALIZE_SKIP_REASON_SKIP_MODE, []
    if not neutralize:
        return [], NEUTRALIZE_SKIP_REASON_USER_DISABLED, []

    requested_specs = list(DEFAULT_NEUTRALIZE_SPECS if neutralize_specs is None else neutralize_specs)
    excluded_specs = [spec for spec in requested_specs if is_excluded(factor_name, spec)]
    effective_specs = [spec for spec in requested_specs if spec not in excluded_specs]
    if not effective_specs:
        return [], NEUTRALIZE_SKIP_REASON_EXCLUDED, excluded_specs
    return effective_specs, None, excluded_specs


def _resolve_neutralize_decision(
    factor_name: str,
    neutralize: bool,
    mode: str,
) -> tuple[bool, str | None]:
    """解析 legacy 行业中性化决策（保持 P1/P2 优先级：排除清单 > 模式 > 用户）。"""
    if is_excluded(factor_name, "industry"):
        return False, NEUTRALIZE_SKIP_REASON_EXCLUDED
    effective_specs, skipped_reason, _ = _resolve_neutralize_specs(
        factor_name=factor_name,
        neutralize=neutralize,
        mode=mode,
        neutralize_specs=["industry"],
    )
    return bool(effective_specs), skipped_reason


def _classify_decay_level(decay_rate: float, threshold: float = 0.30) -> str:
    """
    根据衰减率分类（design.md §5.4 报告分级）

    decay_rate = (raw_ic_mean - neutral_ic_mean) / raw_ic_mean

    - decay_rate >= threshold (默认 30%): 'high' (高度行业 beta 驱动)
    - 0 <= decay_rate < threshold: 'low' (alpha 主导)
    - decay_rate < 0: 'inverse' (中性化后 |IC| 反而上升, 结构性增益)

    raw_ic_mean ≈ 0 时分母不稳定 → 'undefined'
    （|raw_ic_mean| < _DECAY_RATE_RAW_IC_FLOOR 时视为近零, decay_rate=None）
    """
    import math

    if not math.isfinite(decay_rate):
        return "undefined"
    if decay_rate < 0:
        return "inverse"
    if decay_rate >= threshold:
        return "high"
    return "low"


def _merge_control_provider(
    factor_df,
    provider: ControlProvider,
    *,
    logger,
):
    """加载/预处理单个 provider，并按 join_keys 合并到 factor_df。"""
    dates = list(dict.fromkeys(factor_df["date"].astype(str).tolist()))
    assets = list(dict.fromkeys(factor_df["asset"].astype(str).tolist()))
    control_df = provider.load(dates=dates, assets=assets, logger=logger)
    control_df = provider.preprocess(control_df, logger=logger)
    missing_keys = [key for key in provider.join_keys if key not in control_df.columns]
    if missing_keys:
        raise ValueError(f"provider {provider.name} preprocess 后缺少 join_keys {missing_keys}")
    merged = factor_df.merge(control_df, on=provider.join_keys, how="left")
    logger.info(
        "[neutralize] provider=%s join_keys=%s merged_rows=%d",
        provider.name,
        provider.join_keys,
        len(merged),
    )
    return merged


def _compute_neutralized_ic(
    *,
    factor_df,
    return_df,
    factor_col: str,
    return_col: str,
    providers: list[ControlProvider],
    min_stocks: int,
    control_min_count: int,
    raw_ic_mean: float,
    logger,
    excluded_specs: list[str] | None = None,
) -> dict[str, Any]:
    """计算多 control 中性化 IC（P3 通用路径）。"""
    from .neutralizer import neutralize

    if logger is None:
        logger = get_logger(__name__)
    if not providers:
        raise ValueError("_compute_neutralized_ic: providers 不能为空")
    excluded_specs = list(excluded_specs or [])

    factor_df_neutral = factor_df.copy()
    for provider in providers:
        factor_df_neutral = _merge_control_provider(factor_df_neutral, provider, logger=logger)

    before_nan = len(factor_df_neutral)
    required_cols = [factor_col]
    for provider in providers:
        if provider.column_type == "categorical":
            required_cols.append(provider.name)
        else:
            required_cols.append(provider.name)
    factor_df_neutral = factor_df_neutral.dropna(subset=required_cols)
    nan_dropped = before_nan - len(factor_df_neutral)
    logger.info(
        "[neutralize] required=%s NaN 剔除: %d 行（剩余 %d 行）",
        required_cols,
        nan_dropped,
        len(factor_df_neutral),
    )

    residual_df = neutralize(
        factor_df_neutral,
        providers=providers,
        factor_col=factor_col,
        date_col="date",
        asset_col="asset",
        min_count=control_min_count,
        logger=logger,
    )
    if residual_df.empty:
        raise RuntimeError("neutralize 返回空 DataFrame（控制变量缺失/小样本全部过滤）")

    logger.info(
        "[neutralize] controls=%s 残差因子: %d 行（vs raw factor %d 行）",
        [provider.name for provider in providers],
        len(residual_df),
        len(factor_df),
    )

    neutral_ic_result = calculate_ic_with_direction_verification(
        factor_df=residual_df,
        return_df=return_df,
        factor_col="neutral_factor",
        return_col=return_col,
        date_col="date",
        asset_col="asset",
        min_stocks=min_stocks,
        logger=logger,
    )

    neutral_ic_mean = float(neutral_ic_result.get("ic_mean", 0.0))
    # |raw_ic_mean| < 0.001 时 IC 远低于经济显著性阈值(0.03)的 1/30,
    # p-value 远超 0.05, 原始 IC 本身是噪声 → decay_rate 无统计意义
    # 遵循硬规则 #14: 禁止对噪声分母做防御性兜底计算
    if abs(raw_ic_mean) < _DECAY_RATE_RAW_IC_FLOOR:
        decay_rate = float("nan")
    else:
        decay_rate = (abs(raw_ic_mean) - abs(neutral_ic_mean)) / abs(raw_ic_mean)
    decay_level = _classify_decay_level(decay_rate)

    neutral_ic_series = neutral_ic_result["ic_series"]
    if neutral_ic_series is not None and len(neutral_ic_series) > 0:
        neutral_ic_series = neutral_ic_series.sort_index()
        neutral_dates = [str(d) for d in neutral_ic_series.index]
        neutral_ic_values = [round(float(v), 6) for v in neutral_ic_series.values]
    else:
        neutral_dates = []
        neutral_ic_values = []

    stats_sig = neutral_ic_result.get("statistical_significance") or {}
    control_meta = {provider.name: provider.get_meta() for provider in providers}
    return {
        "enabled": True,
        "controls_used": [provider.name for provider in providers],
        "excluded_specs": excluded_specs,
        "control_meta": control_meta,
        "ic_mean": round(neutral_ic_mean, 6),
        "ic_std": round(float(neutral_ic_result.get("ic_std", 0.0)), 6),
        "icir": round(float(neutral_ic_result.get("icir", 0.0)), 4),
        "p_value": stats_sig.get("p_value"),
        "p_value_display": stats_sig.get("p_value_display"),
        "positive_ratio": neutral_ic_result.get("positive_ratio"),
        "n_days": neutral_ic_result.get("n_days"),
        "dates": neutral_dates,
        "ic_values": neutral_ic_values,
        "decay_rate": round(decay_rate, 6) if decay_rate == decay_rate else None,
        "decay_level": decay_level,
    }


def _compute_industry_neutral_ic(
    *,
    factor_df,
    return_df,
    factor_col: str,
    return_col: str,
    min_stocks: int,
    neutralize_min_industry_stocks: int,
    raw_ic_mean: float,
    logger,
) -> dict[str, Any]:
    """计算 legacy 行业中性化 IC（P3 前兼容包装）。"""
    provider = IndustryProvider()
    payload = _compute_neutralized_ic(
        factor_df=factor_df,
        return_df=return_df,
        factor_col=factor_col,
        return_col=return_col,
        providers=[provider],
        min_stocks=min_stocks,
        control_min_count=neutralize_min_industry_stocks,
        raw_ic_mean=raw_ic_mean,
        logger=logger,
    )
    legacy_payload = {
        k: v for k, v in payload.items() if k not in {"enabled", "controls_used", "excluded_specs", "control_meta"}
    }
    legacy_payload["min_industry_stocks"] = neutralize_min_industry_stocks
    return legacy_payload


def run_factor_ic_analysis(
    factor_name: str,
    factor_col: str,
    return_period: str = "1d",
    return_col: str | None = None,
    factor_cols: list[str] | None = None,
    min_stocks: int = 10,
    force_full: bool = False,
    output_path: Path | None = None,
    data_cache_path: Path | None = None,
    additional_factor_files: dict[str, Path] | None = None,
    custom_factor_calculation: Callable | None = None,
    custom_factor_calculation_params: dict[str, Any] | None = None,
    extra_log_params: dict[str, Any] | None = None,
    *,
    neutralize: bool = True,
    neutralize_specs: list[str] | None = None,
    neutralize_min_industry_stocks: int = 5,
    logger=None,
) -> dict[str, Any]:
    """
    因子 IC 分析统一主入口

    参数:
        factor_name: 因子名称（如 'rsi', 'volume_ratio'）
        factor_col: 主因子列名（如 'rsi_6', 'volume_ratio_5'）
        return_period: 收益周期（如 '1d'）
        return_col: 收益列名（缓存中）；None 时自动推导为 forward_return_{return_period}
        factor_cols: 需加载的因子列列表（默认 = [factor_col]）
        min_stocks: 最小股票数阈值
        force_full: 是否强制全量计算
        output_path: 输出文件路径（默认自动生成）
        data_cache_path: 数据缓存路径（默认使用 factor_ic_data.json.gz）
        additional_factor_files: 额外因子文件（如换手率数据）
        custom_factor_calculation: 自定义因子计算函数（可选）
            - 用于需要预处理因子值的场景（如 KDJ 计算）
            - 函数签名: (factor_df: pd.DataFrame) -> pd.DataFrame
        custom_factor_calculation_params: 自定义因子计算参数
        extra_log_params: 入口脚本传入的额外启动参数（非公共参数），用于在启动横幅中
            打印因子特有参数（如 KDJ 的 n/m1/m2、布林带的 n/k）。
            None / 空 dict 时不打印"扩展参数"行。
        logger: 日志记录器（由调用方传入，默认使用模块 logger）
            - 参数名与模块级 logger 同名，函数内覆盖模块级变量（调用方传入优先）

    返回:
        IC 分析结果字典（符合 MODULE.md 输出结构统一性规范）

    流程:
        1. 判断模式（全量/增量/跳过）- 使用 check_data_completeness，不需要加载数据
        2. SKIP 模式：直接返回缓存数据
        3. 加载数据（仅在 FULL/INCREMENTAL 模式）
        4. 执行计算
        5. 构建输出
        6. 保存结果

    示例:
        # RSI 因子（直接用缓存列）
        result = run_factor_ic_analysis(
            factor_name='rsi',
            factor_col='rsi_6'
        )

        # KDJ 因子（需要自定义计算）
        def calculate_kdj_j(factor_df):
            # ... KDJ 计算逻辑 ...
            return factor_df

        result = run_factor_ic_analysis(
            factor_name='kdj_j',
            factor_col='kdj_j',
            factor_cols=['close', 'high', 'low'],
            custom_factor_calculation=calculate_kdj_j
        )
    """
    # logger fallback 初始化（参数名与模块级同名，函数内覆盖模块级变量）
    if logger is None:
        logger = get_logger(__name__)

    # 自动推导 return_col：若未指定，从 return_period 推导列名
    # 消除隐式耦合：传 return_period='5d' 时自动使用 forward_return_5d，
    # 不会因默认值 forward_return_1d 导致静默错误
    if return_col is None:
        return_col = f"forward_return_{return_period}"

    logger.info("=" * 60)
    logger.info("因子 IC 分析: %s_%s", factor_name, return_period)
    logger.info("入口参数: min_stocks=%s, force_full=%s", min_stocks, force_full)
    if extra_log_params:
        # 扩展参数行：使用 % 惰性格式化（PROJECT.md 规则 #13），
        # 同时对 v 做 %s 安全转换以容忍 None / int / str / float / bool 等类型
        extra_str = ", ".join(f"{k}={v!s}" for k, v in extra_log_params.items())
        logger.info("扩展参数: %s", extra_str)
    logger.info("=" * 60)

    # ========== 确定路径 ==========
    if output_path is None:
        output_path = get_ic_output_path(factor_name, return_period)

    if data_cache_path is None:
        data_cache_path = get_data_cache_path()

    if factor_cols is None:
        factor_cols = [factor_col]
    else:
        # 参数校验：factor_col 必须在 factor_cols 中
        # **重要修正**：复杂因子（有 custom_factor_calculation）跳过此校验
        # 原因：factor_col 是计算后的因子列名，不存在于原始缓存数据中
        # 只有简单因子才需要校验（直接从缓存读取 factor_col）
        if custom_factor_calculation is None and factor_col not in factor_cols:
            logger.warning("factor_col '%s' 不在 factor_cols %s 中，自动添加以防止列缺失错误", factor_col, factor_cols)
            # 追加到末尾，保持原有顺序
            factor_cols = factor_cols + [factor_col]

    data_source = str(data_cache_path)

    # ========== 判断模式（不需要加载数据）==========
    # 使用 check_data_completeness 判断模式，避免 SKIP 模式也加载全量数据

    # force_full 强制全量模式
    if force_full:
        mode = "full"
        logger.info("模式判断: 强制全量计算")
    else:
        mode, _, _ = check_data_completeness(factor_name, logger=logger)
        logger.info("模式判断: %s", mode)

    # ========== SKIP 模式：直接返回缓存数据 ==========
    if mode == "skip":
        logger.info("[执行模式] 数据已最新，跳过计算")

        # 直接读取缓存数据返回
        if output_path.exists():
            try:
                with open(output_path, encoding="utf-8") as f:
                    cached_result = json.load(f)
                cached_result["update_mode"] = "skip"
                logger.info("✓ 返回缓存数据: %s 天", len(cached_result.get("dates", [])))
                return cached_result
            except (json.JSONDecodeError, OSError) as e:
                # 缓存文件损坏，转为全量重算
                logger.warning("缓存文件损坏 [%s]: %s，转为全量计算", output_path, e)
                mode = "full"
                # 继续执行下方的加载数据+全量计算逻辑
        else:
            # 缓存文件不存在（理论上不应该发生，因为 mode='skip' 需要缓存存在）
            # 统一策略：缓存不可用（不存在或损坏）均 fallback 全量重算，管道自愈而非中断
            logger.warning("缓存文件不存在 [%s]，转为全量计算", output_path)
            mode = "full"
            # 继续执行下方的加载数据+全量计算逻辑

    # ========== 加载数据（仅在 FULL/INCREMENTAL 模式）==========
    logger.info("[数据加载] 加载因子和收益数据...")

    try:
        factor_df, return_df, raw_metadata = load_factor_return_data(
            factor_cols=factor_cols,
            return_col=return_col,
            data_cache_path=data_cache_path,
            additional_factor_files=additional_factor_files,
            logger=logger,
        )
    except FileNotFoundError as e:
        # 缓存不存在：返回错误结构
        logger.error("数据加载失败: %s", e)
        return build_error_result(
            factor_name=f"{factor_name}_{return_period}",
            error_msg=str(e),
            return_period=return_period,
            data_source=data_source,
        )
    except Exception as e:
        # 其他异常：返回错误结构
        logger.error("数据加载异常: %s", e)
        return build_error_result(
            factor_name=f"{factor_name}_{return_period}",
            error_msg=str(e),
            return_period=return_period,
            data_source=data_source,
        )

    # ========== 增量模式处理 ==========
    # 标志位：追踪自定义因子计算是否已执行
    # 原因：增量路径 fallback 到全量时，若已在增量路径执行了 custom_factor_calculation，
    # 全量路径不应重复执行（数据已被变换，重复执行会导致错误）
    _custom_factor_done = False

    if mode == "incremental":
        logger.info("[执行模式] 增量更新...")

        # **重要修正**：复杂因子在增量模式也需要先执行自定义计算
        # 原因：factor_col 是计算后的因子列名，不存在于原始缓存数据中
        if custom_factor_calculation is not None:
            logger.info("[因子预处理] 执行自定义因子计算...")
            params = custom_factor_calculation_params or {}
            try:
                factor_df = custom_factor_calculation(factor_df, **params)
                logger.info("处理后数据: %s 行", len(factor_df))
                _custom_factor_done = True
            except Exception as e:
                logger.error("自定义因子计算失败: %s", e)
                return build_error_result(
                    factor_name=f"{factor_name}_{return_period}",
                    error_msg=f"自定义因子计算失败: {e}",
                    return_period=return_period,
                    data_source=data_source,
                )

        try:
            # 调用增量引擎（内部已保存结果）
            # 传入 factor_df.copy() 隔离：incremental_update_ic 可能就地修改 DataFrame，
            # fallback 到全量时不能使用被污染的数据
            result = incremental_update_ic(
                output_path=output_path,
                factor_df_full=factor_df.copy(),
                return_df_full=return_df.copy(),
                raw_metadata=raw_metadata,
                factor_name=f"{factor_name}_{return_period}",
                factor_col=factor_col,
                return_col=return_col,
                min_stocks=min_stocks,
            )

            # 增量引擎已返回完整结果（包含五维度判断）
            # incremental_update_ic 内部已调用 calculate_ic_statistics 计算五维度
            # 数据来源一致性：ic_values 和 dates 来自增量引擎合并后的全量数据
            valid_days = result.get("sample_stats", {}).get("valid_days", 0)
            total_days = len(result.get("dates", []))
            logger.info("✓ 增量更新完成！共 %s 天（%s 天有效 IC）", total_days, valid_days)
            return result

        except (RuntimeError, ValueError, KeyError) as e:
            # 缓存不存在/损坏或计算异常，转为全量计算
            logger.warning("%s，转为全量计算", e)
            mode = "full"
            # 继续执行下方的全量模式代码

    # ========== 全量模式 ==========
    # 注意：此分支也处理增量模式转全量模式的情况
    logger.info("[执行模式] 全量计算...")

    # 自定义因子计算（如有且未在增量路径执行过）
    if custom_factor_calculation is not None and not _custom_factor_done:
        logger.info("[因子预处理] 执行自定义因子计算...")
        params = custom_factor_calculation_params or {}
        try:
            factor_df = custom_factor_calculation(factor_df, **params)
            logger.info("处理后数据: %s 行", len(factor_df))
        except Exception as e:
            logger.error("自定义因子计算失败: %s", e)
            return build_error_result(
                factor_name=f"{factor_name}_{return_period}",
                error_msg=f"自定义因子计算失败: {e}",
                return_period=return_period,
                data_source=data_source,
            )

    # 计算 IC（五维度判断）
    logger.info("[IC 计算] 计算 IC（含五维度判断）...")

    try:
        ic_result = calculate_ic_with_direction_verification(
            factor_df=factor_df,
            return_df=return_df,
            factor_col=factor_col,
            return_col=return_col,
            date_col="date",
            asset_col="asset",
            min_stocks=min_stocks,
            logger=logger,
        )

        # 使用 .get() 防止 KeyError，保持与增量模式一致
        logger.info("IC 均值: %.4f", ic_result.get("ic_mean", 0.0))
        logger.info("ICIR: %.2f", ic_result.get("icir", 0.0))
        # 五维度字段嵌套访问需双重保护（get 默认 {}，或 None 时 fallback {}）
        stats_sig = ic_result.get("statistical_significance") or {}
        t_stat = stats_sig.get("t_stat", 0.0)
        logger.info("t 统计量: %.2f", t_stat)

    except Exception as e:
        logger.error("IC 计算失败: %s", e)
        return build_error_result(
            factor_name=f"{factor_name}_{return_period}",
            error_msg=f"IC 计算失败: {e}",
            return_period=return_period,
            data_source=data_source,
        )

    # ========== 中性化 IC（design.md §5.1 Step 4-7, P3: specs 路径） ==========
    # mode 已经是 'full'（增量分支已 return）
    effective_specs, neutral_skip_reason, excluded_specs = _resolve_neutralize_specs(
        factor_name=factor_name,
        neutralize=neutralize,
        mode="full",
        neutralize_specs=neutralize_specs,
    )

    ic_neutralized_payload: dict[str, Any] | None = None

    if not effective_specs:
        # 全局跳过（user disabled / incremental / skip / 全排除）
        ic_neutralized_payload = {
            "enabled": False,
            "skipped_reason": neutral_skip_reason,
            "controls_used": [],
            "excluded_specs": excluded_specs,
        }
        logger.info("中性化 IC 跳过: %s", neutral_skip_reason)
    else:
        try:
            providers = build_providers(effective_specs)
            ic_neutralized_payload = _compute_neutralized_ic(
                factor_df=factor_df,
                return_df=return_df,
                factor_col=factor_col,
                return_col=return_col,
                providers=providers,
                min_stocks=min_stocks,
                control_min_count=neutralize_min_industry_stocks,
                raw_ic_mean=float(ic_result.get("ic_mean", 0.0)),
                logger=logger,
                excluded_specs=excluded_specs,
            )
            # decay_rate 可能为 None（raw_ic_mean 近零保护 → NaN → None），
            # .get(default) 对值为 None 的 key 不生效，用 `or` 确保回退到 0.0
            _neu_ic_mean = ic_neutralized_payload.get("ic_mean") or 0.0
            _neu_decay_rate = ic_neutralized_payload.get("decay_rate") or 0.0
            _neu_decay_level = ic_neutralized_payload.get("decay_level") or "unknown"
            logger.info(
                "neutral IC 均值: %.4f / decay_rate: %.4f / decay_level: %s",
                _neu_ic_mean,
                _neu_decay_rate,
                _neu_decay_level,
            )
        except Exception as e:
            # 不让中性化失败拖垮 raw IC 输出，降级为 enabled=false + 失败原因
            logger.warning("中性化 IC 计算失败，降级为 skipped: %s", e)
            ic_neutralized_payload = {
                "enabled": False,
                "skipped_reason": f"computation failed: {e}",
                "controls_used": [],
                "excluded_specs": excluded_specs,
            }

    # 构建完整结果
    result = build_ic_result(
        ic_result=ic_result,
        raw_metadata=raw_metadata,
        factor_name=f"{factor_name}_{return_period}",
        return_period=return_period,
        data_source=data_source,
        factor_col=factor_col,
        update_mode="full",
        ic_neutralized_payload=ic_neutralized_payload,
    )

    # 保存
    save_ic_result(result, output_path)

    logger.info("=" * 60)
    # 使用 .get() 双重保护防止 KeyError（与日志访问规范一致）
    valid_days = result.get("sample_stats", {}).get("valid_days", 0)
    logger.info("完成！共计算 %s 天有效 IC", valid_days)
    logger.info("=" * 60)

    return result


# ========== 快捷函数 ==========


def run_simple_factor_ic(factor_name: str, factor_col: str, logger=None, **kwargs) -> dict[str, Any]:
    """
    快捷函数：简单因子 IC 分析

    适用于直接使用缓存列的因子（如 RSI、量比）

    参数:
        factor_name: 因子名称
        factor_col: 因子列名
        logger: 日志记录器（由调用方传入，默认使用模块 logger）
            - 参数名与模块级 logger 同名，函数内覆盖模块级变量（调用方传入优先）
        **kwargs: 其他参数（传递给 run_factor_ic_analysis）

    示例:
        result = run_simple_factor_ic('rsi', 'rsi_6')
        result = run_simple_factor_ic('volume_ratio', 'volume_ratio_5')
    """
    return run_factor_ic_analysis(
        factor_name=factor_name, factor_col=factor_col, factor_cols=[factor_col], logger=logger, **kwargs
    )


def run_complex_factor_ic(
    factor_name: str,
    factor_col: str,
    factor_cols: list[str],
    custom_factor_calculation: Callable,
    logger=None,
    **kwargs,
) -> dict[str, Any]:
    """
    快捷函数：复杂因子 IC 分析

    适用于需要预处理因子值的场景（如 KDJ、布林带）

    参数:
        factor_name: 因子名称
        factor_col: 最终因子列名
        factor_cols: 需加载的原始因子列
        custom_factor_calculation: 自定义因子计算函数（必须提供）
        logger: 日志记录器（由调用方传入，默认使用模块 logger）
            - 参数名与模块级 logger 同名，函数内覆盖模块级变量（调用方传入优先）
        **kwargs: 其他参数

    示例:
        def calculate_kdj_j(factor_df):
            # KDJ 计算逻辑
            ...
            return factor_df

        result = run_complex_factor_ic(
            factor_name='kdj_j',
            factor_col='kdj_j',
            factor_cols=['close', 'high', 'low'],
            custom_factor_calculation=calculate_kdj_j
        )
    """
    return run_factor_ic_analysis(
        factor_name=factor_name,
        factor_col=factor_col,
        factor_cols=factor_cols,
        custom_factor_calculation=custom_factor_calculation,
        logger=logger,
        **kwargs,
    )


def run_factor_ic(
    spec: FactorSpec,
    *,
    return_period: str = "1d",
    min_stocks: int = 10,
    force_full: bool = False,
    args: Any | None = None,
    logger=None,
    **kwargs,
) -> dict[str, Any]:
    """FactorSpec 驱动的 IC 分析入口（推荐，替代 run_simple/run_complex）。

    从 FactorSpec 提取 factor_name / factor_col / required_columns / calculation /
    calc_params / extra_log_params，然后委托给 run_factor_ic_analysis。

    Args:
        spec: FactorSpec 实例（由 register_factor 注册）
        return_period: 收益周期（默认 "1d"）
        min_stocks: 最小股票数（默认 10）
        force_full: 强制全量计算（默认 False）
        args: CLI argparse.Namespace，供 calc_params_fn / extra_log_params_fn 提取参数
        logger: 日志记录器（遵循 M3 由调用方传入）
        **kwargs: 其他参数（传递给 run_factor_ic_analysis）

    Returns:
        run_factor_ic_analysis 的完整结果字典

    Raises:
        DataSchemaError: required_columns 与数据源列不匹配时

    示例:
        SPEC = register_factor(FactorSpec(
            factor_name="kdj_j",
            factor_col="kdj_j",
            required_columns=JOIN_KEYS + ("close", "high", "low", "kdj_j"),
            calculation=calculate_kdj_j,
            calc_params_fn=lambda a: {"n": a.n, "m1": a.m1, "m2": a.m2},
            extra_log_params_fn=lambda a: {"n": a.n, "m1": a.m1, "m2": a.m2},
        ))

        result = run_factor_ic(spec=SPEC, args=args, logger=logger)
    """
    from factor_ic.common.data_columns import load_available_columns, validate_required_columns

    # L3 运行时 schema 预校验（可选：columns.json 存在时才校验）
    columns_info = load_available_columns()
    if columns_info and "all_cols" in columns_info:
        validate_required_columns(
            factor_name=spec.factor_name,
            required_columns=spec.required_columns,
            available_columns=columns_info["all_cols"],
        )

    # 从 spec + args 提取参数
    custom_factor_calculation = spec.calculation
    custom_factor_calculation_params = spec.calc_params_fn(args) if (spec.calc_params_fn and args) else None
    extra_log_params = spec.extra_log_params_fn(args) if (spec.extra_log_params_fn and args) else None

    return run_factor_ic_analysis(
        factor_name=spec.factor_name,
        factor_col=spec.factor_col,
        factor_cols=list(spec.required_columns),
        return_period=return_period,
        min_stocks=min_stocks,
        force_full=force_full,
        custom_factor_calculation=custom_factor_calculation,
        custom_factor_calculation_params=custom_factor_calculation_params,
        extra_log_params=extra_log_params,
        logger=logger,
        **kwargs,
    )


# ========== CLI 支持 ==========


def main():
    """
    CLI 主入口

    用法:
        python -m factor_ic.common.factor_ic_runner --factor rsi --col rsi_6
    """
    import argparse

    parser = argparse.ArgumentParser(description="因子 IC 分析")
    parser.add_argument("--factor", required=True, help="因子名称")
    parser.add_argument("--col", required=True, help="因子列名")
    parser.add_argument("--period", default="1d", help="收益周期")
    parser.add_argument("--min-stocks", type=int, default=10, help="最小股票数")
    parser.add_argument("--force-full", action="store_true", help="强制全量计算")
    parser.add_argument(
        "--data-source",
        type=str,
        default=None,
        dest="data_source",
        help="数据源文件路径（默认使用 factor_ic_data.json.gz）",
    )

    args = parser.parse_args()

    # CLI 使用模块级 logger
    result = run_simple_factor_ic(
        factor_name=args.factor,
        factor_col=args.col,
        return_period=args.period,
        min_stocks=args.min_stocks,
        force_full=args.force_full,
        data_cache_path=args.data_source,
        logger=logger,  # 传入模块级 logger（参数名 logger，值是模块级 logger）
    )

    # 使用模块级 logger（明确标识）
    logger.info("[CLI] 结果: %s", result.get("update_mode", "unknown"))


if __name__ == "__main__":
    main()
