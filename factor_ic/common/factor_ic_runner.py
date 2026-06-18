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

# 导入日志
from .logger_config import get_logger


logger = get_logger(__name__)

# 导入数据加载（单文件模式）

# 导入数据完整性检查
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


# ============================================================
# 行业中性化排除清单（design.md §3.1 + §5.3）
# ============================================================
# 行业聚合赋个股的因子：因子值在行业内全部相同 → 行业回归残差 ≡ 0 → IC ≡ 0
# 这类因子被强制跳过中性化（即使调用方传入 neutralize=True 也覆盖为 False）
# 详见 design.md §5.3.2 协议表与 §3.1 实证依据
INDUSTRY_NEUTRALIZE_EXCLUDED: frozenset[str] = frozenset(
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
)

# skipped_reason 文本常量（写入输出 JSON 的 ic_neutral_industry.skipped_reason）
NEUTRALIZE_SKIP_REASON_EXCLUDED = "factor in INDUSTRY_NEUTRALIZE_EXCLUDED (industry-aggregated factor)"
NEUTRALIZE_SKIP_REASON_USER_DISABLED = "user disabled via neutralize=False"
NEUTRALIZE_SKIP_REASON_INCREMENTAL = "incremental mode (industry neutralization v1 supports full mode only)"
NEUTRALIZE_SKIP_REASON_SKIP_MODE = "skip mode (cached result, neutralization not recomputed)"


def _resolve_neutralize_decision(
    factor_name: str,
    neutralize: bool,
    mode: str,
) -> tuple[bool, str | None]:
    """
    解析行业中性化的最终决策（design.md §5.3.2 协议表）

    协议优先级：排除清单 > 模式限制 > 用户参数
    - 排除清单内因子（残差≡0）→ 强制 skip（覆盖用户参数）
    - 非 full 模式（增量/skip）→ skip（v1 仅支持 full 模式重算）
    - 用户传 neutralize=False → skip
    - 否则启用

    参数:
        factor_name: 因子名（不含 _1d 后缀，与排除清单 key 一致）
        neutralize: 调用方传入的开关
        mode: 当前执行模式（'full' / 'incremental' / 'skip'）

    返回:
        (enabled, skipped_reason)
        - enabled=True: 应当计算 neutral IC, skipped_reason=None
        - enabled=False: 应跳过, skipped_reason 为协议表中的固定文本

    Note:
        本函数不调用 logger，纯函数便于单测；调用方负责日志记录。
    """
    if factor_name in INDUSTRY_NEUTRALIZE_EXCLUDED:
        return False, NEUTRALIZE_SKIP_REASON_EXCLUDED
    if mode == "incremental":
        return False, NEUTRALIZE_SKIP_REASON_INCREMENTAL
    if mode == "skip":
        return False, NEUTRALIZE_SKIP_REASON_SKIP_MODE
    if not neutralize:
        return False, NEUTRALIZE_SKIP_REASON_USER_DISABLED
    return True, None


def _classify_decay_level(decay_rate: float, threshold: float = 0.30) -> str:
    """
    根据衰减率分类（design.md §5.4 报告分级）

    decay_rate = (raw_ic_mean - neutral_ic_mean) / raw_ic_mean

    - decay_rate >= threshold (默认 30%): 'high' (高度行业 beta 驱动)
    - 0 <= decay_rate < threshold: 'low' (alpha 主导)
    - decay_rate < 0: 'inverse' (中性化后 |IC| 反而上升, 结构性增益)

    raw_ic_mean ≈ 0 时分母不稳定 → 'undefined'
    """
    import math

    if not math.isfinite(decay_rate):
        return "undefined"
    if decay_rate < 0:
        return "inverse"
    if decay_rate >= threshold:
        return "high"
    return "low"


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
    """
    计算行业中性化 IC（design.md §5.1 Step 4-7 实现）

    流程：
    1. 加载行业映射（fetch_industry.get_industry_map → dict）
    2. merge_industry_column 注入 'industry' 列（未知 asset 自然产生 NaN）
    3. industry_neutral_residual 求残差因子（'其他' + NaN + 行业内 <min 全过滤）
    4. 用残差因子重新调用 calculate_ic_with_direction_verification
    5. 计算 decay_rate + decay_level

    参数:
        factor_df / return_df: 已加载的因子/收益数据
        factor_col / return_col: 列名
        min_stocks: IC 计算的每日最少股票数
        neutralize_min_industry_stocks: 行业内最少股票数（默认 5）
        raw_ic_mean: raw IC 均值（用于计算 decay_rate）
        logger: 日志记录器

    返回:
        dict: {
            'ic_mean', 'ic_std', 'icir', 'p_value', 'p_value_display',
            'positive_ratio',
            'dates', 'ic_values',
            'decay_rate', 'decay_level',
            'min_industry_stocks',
        }
        若中间步骤过滤为空，抛 RuntimeError 让上层降级为 skipped_reason

    Note:
        merge_industry_column 内部已 import data_fetchers.fetch_industry，本函数不再重复。
        industry_neutral_residual 不支持 exclude_industries 参数，'其他'剔除在本函数显式做。
    """
    from .data_loader import merge_industry_column
    from .ic_calculator import calculate_ic_with_direction_verification, industry_neutral_residual

    # Step 1+2: 注入 industry 列（merge_industry_column 内部已加载行业映射, 未知 asset 自然 NaN）
    factor_df_with_industry = merge_industry_column(
        factor_df,
        asset_col="asset",
        out_col="industry",
        logger=logger,
    )

    # Step 2.5: 剔除 '其他' 行业（design.md §3.3 / D6 决策）
    #   - '其他' 是申万一级里的混杂桶（含申万二级码 220901/280203 等），不应作为独立行业回归
    #   - industry 列为 NaN（未匹配 asset）不需手动剔除：industry_neutral_residual 内部
    #     groupby(industry_col) 会跳过 NaN 分组（pandas 默认 dropna=True 行为）
    before = len(factor_df_with_industry)
    factor_df_filtered = factor_df_with_industry[factor_df_with_industry["industry"] != "其他"].copy()
    other_dropped = before - len(factor_df_filtered)
    logger.info("[neutralize] '其他' 行业剔除: %d 行（剩余 %d 行）", other_dropped, len(factor_df_filtered))

    # Step 2.6: 剔除 factor_col 为 NaN 的行（industry_neutralization_flow.md §5.3 follow-up 闭环 2026-06-18）
    #   - sklearn LinearRegression.fit 默认 force_all_finite=True，y 含 NaN 直接抛 ValueError，
    #     被外层 except 降级为 enabled=False / skipped_reason="computation failed: Input y contains NaN."
    #   - raw IC 路径在 ic_calculator.calculate_ic_with_direction_verification 内部已有 dropna 兜底，
    #     中性化路径必须显式 dropna 与之对齐，否则首日/停牌等天然 NaN 行会让中性化整体失败
    #   - 复杂因子（custom_factor_calculation 在 data_loader dropna 之后才生成 factor_col）尤其受影响：
    #     overnight_ret 首日 + |prev_close|<EPSILON / prev_close<0 防御场景实测产生 2225 NaN 行 / 58 个日期
    before_nan = len(factor_df_filtered)
    factor_df_filtered = factor_df_filtered.dropna(subset=[factor_col])
    nan_dropped = before_nan - len(factor_df_filtered)
    logger.info(
        "[neutralize] %s NaN 剔除: %d 行（剩余 %d 行）",
        factor_col,
        nan_dropped,
        len(factor_df_filtered),
    )

    # Step 3: 求残差因子
    residual_df = industry_neutral_residual(
        factor_df=factor_df_filtered,
        factor_col=factor_col,
        date_col="date",
        asset_col="asset",
        industry_col="industry",
        min_industry_stocks=neutralize_min_industry_stocks,
        logger=logger,
    )

    if residual_df.empty:
        raise RuntimeError("industry_neutral_residual 返回空 DataFrame（'其他'+NaN+小行业全部过滤）")

    logger.info(
        "[neutralize] 残差因子: %d 行（vs raw factor %d 行）",
        len(residual_df),
        len(factor_df_with_industry),
    )

    # Step 4: 用残差因子重新计算 IC（残差列名固定为 neutral_factor）
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

    # Step 5: 提取核心字段 + 计算衰减
    neutral_ic_mean = float(neutral_ic_result.get("ic_mean", 0.0))
    # decay_rate = (raw - neutral) / raw（用绝对值避免符号干扰）
    if abs(raw_ic_mean) < 1e-9:
        decay_rate = float("nan")
    else:
        decay_rate = (abs(raw_ic_mean) - abs(neutral_ic_mean)) / abs(raw_ic_mean)

    decay_level = _classify_decay_level(decay_rate)

    # 时序数据
    neutral_ic_series = neutral_ic_result["ic_series"]
    if neutral_ic_series is not None and len(neutral_ic_series) > 0:
        neutral_ic_series = neutral_ic_series.sort_index()
        neutral_dates = [str(d) for d in neutral_ic_series.index]
        neutral_ic_values = [round(float(v), 6) for v in neutral_ic_series.values]
    else:
        neutral_dates = []
        neutral_ic_values = []

    stats_sig = neutral_ic_result.get("statistical_significance") or {}

    return {
        "ic_mean": round(neutral_ic_mean, 6),
        "ic_std": round(float(neutral_ic_result.get("ic_std", 0.0)), 6),
        "icir": round(float(neutral_ic_result.get("icir", 0.0)), 4),
        "p_value": stats_sig.get("p_value"),
        "p_value_display": stats_sig.get("p_value_display"),
        "positive_ratio": neutral_ic_result.get("positive_ratio"),
        "n_days": neutral_ic_result.get("n_days"),
        "dates": neutral_dates,
        "ic_values": neutral_ic_values,
        "decay_rate": round(decay_rate, 6) if decay_rate == decay_rate else None,  # NaN→None
        "decay_level": decay_level,
        "min_industry_stocks": neutralize_min_industry_stocks,
    }


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

    # ========== 行业中性化 IC（design.md §5.1 Step 4-7） ==========
    # 协议解析：mode 已经是 'full'（增量分支已 return）
    neutral_enabled, neutral_skip_reason = _resolve_neutralize_decision(
        factor_name=factor_name,
        neutralize=neutralize,
        mode="full",
    )

    ic_neutral_payload: dict[str, Any] = {
        "enabled": neutral_enabled,
        "skipped_reason": neutral_skip_reason,
    }

    if neutral_enabled:
        try:
            neutral_payload = _compute_industry_neutral_ic(
                factor_df=factor_df,
                return_df=return_df,
                factor_col=factor_col,
                return_col=return_col,
                min_stocks=min_stocks,
                neutralize_min_industry_stocks=neutralize_min_industry_stocks,
                raw_ic_mean=float(ic_result.get("ic_mean", 0.0)),
                logger=logger,
            )
            ic_neutral_payload.update(neutral_payload)
            logger.info(
                "neutral IC 均值: %.4f / decay_rate: %.4f / decay_level: %s",
                neutral_payload.get("ic_mean", 0.0),
                neutral_payload.get("decay_rate", 0.0),
                neutral_payload.get("decay_level", "unknown"),
            )
        except Exception as e:
            # 不让中性化失败拖垮 raw IC 输出，降级为 enabled=false + 失败原因
            logger.warning("行业中性化 IC 计算失败，降级为 skipped: %s", e)
            ic_neutral_payload = {
                "enabled": False,
                "skipped_reason": f"computation failed: {e}",
            }
    else:
        logger.info("行业中性化 IC 跳过: %s", neutral_skip_reason)

    # 构建完整结果

    result = build_ic_result(
        ic_result=ic_result,
        raw_metadata=raw_metadata,
        factor_name=f"{factor_name}_{return_period}",
        return_period=return_period,
        data_source=data_source,
        factor_col=factor_col,
        update_mode="full",
        ic_neutral_payload=ic_neutral_payload,
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

    args = parser.parse_args()

    # CLI 使用模块级 logger
    result = run_simple_factor_ic(
        factor_name=args.factor,
        factor_col=args.col,
        return_period=args.period,
        min_stocks=args.min_stocks,
        force_full=args.force_full,
        logger=logger,  # 传入模块级 logger（参数名 logger，值是模块级 logger）
    )

    # 使用模块级 logger（明确标识）
    logger.info("[CLI] 结果: %s", result.get("update_mode", "unknown"))


if __name__ == "__main__":
    main()
