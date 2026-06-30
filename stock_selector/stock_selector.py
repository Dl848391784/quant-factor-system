"""
股票选股脚本

功能:
1. 加载最优权重配置（从 weight_selection_result.json）
2. 加载因子数据（从 factor_ic_data.json.gz）
3. 使用最优权重方法计算综合因子值
4. 排序选出 Top N 股票

流程:
Step 1-5: 单因子分析 → 因子筛选 → 标准化 → 加权计算 → 分层回测
Step 6: 权重方式选择 (comprehensive_factor/composite_weight_selector.py)
Step 7: 股票选股 (stock_selector.py) ← 本脚本

版本历史:
- v1.0 (2026-06-03): 初始版本，实现股票选股功能
- v1.1 (2026-06-03): 添加版本历史、模块级 logger、完善类型注解
- v1.2 (2026-06-03): 修复两个问题：
  1. top_n 默认值从 10 改为 3（用户需求）
  2. 因子列表从 composite 结果读取，而非硬编码 rsi/volume_ratio
     遵循数据层架构原则：因子筛选结果由 comprehensive_factor 决定
- v1.3 (2026-06-04): 10项修复（EPSILON判断错误+assert守卫失效+类型不一致+N/A字符串+config就地修改+validate必填检查+_std后缀依赖+factor_cols参数+CLI缺参数+日志冗余）
- v1.4 (2026-06-04): 6项修复（composite_score兜底+get_latest_date格式+__post_init__路径校验+日志冗余+datetime.now时区+索引契约防御校验）
- v1.5 (2026-06-04): 4项修复（CLI过滤None参数+删除空__post_init__+删除重复import+修正注释）
- v1.6 (2026-06-04): 3项修复（调用validate+删除dead config字段+改进日期错误信息）
- v1.7 (2026-06-04): 2项修复（available_dates类型一致性+total_stocks语义精确）
- v1.8 (2026-06-04): 1项修复（mask过滤避免引入临时列污染上游对象）
- v1.9 (2026-06-10): 新增 Step 7.5 方向统一化（遵循 MODULE.md M56）：正向因子 ic_mean>0 标准化值取反，统一负向语义；从 composite 结果读取 direction_map 或回退从 ic_results 计算
- v1.10 (2026-06-11): 3项修复（issue 2/4/1）：
  1. 传 short_sample_factors 给 weight_engine（短样本ICIR惩罚从未执行→已修复）
  2. sort_and_select 新增因子覆盖率过滤（v1.10: 70%门槛；v1.17: 降至50%安全网，配合中性填充策略）
  3. build_result 新增 direction_map/flipped_factors 输出（报告可展示overnight_ret取反说明）
- v1.11 (2026-06-11): 2项修复（issue 1/2重修）：
  1. 覆盖率计算 fallback：weights 为空时使用等权(1/n)计算覆盖率（修复Rolling ICIR last_day_weights为空→覆盖率100%的假象）
  2. composite_runner 回退ICIR静态权重作为 last_day_weights（Rolling ICIR 中间列不保留在调用方 factor_df）
- v1.17 (2026-06-11): 覆盖率门槛 70%→50%（配合 weight_engine v1.17 中性填充策略：缺失因子 z=0 不放大，天然趋中惩罚，70%不再必要，50%仅作安全网）
- v1.3b (2026-06-11): 新增 factor_values_std 字段（标准化 z-score，Winsorize ±3σ 截断），解决报告显示原始值误导问题（momentum_strength 原始=-9.08→z=-2.65）
- v1.12 (2026-06-11): 2项改动：1. 新增 min_amplitude 参数（默认0.01=1%，排除不可交易的一字板涨停股）；2. top_n 默认值从3改为10，扩大选股范围
- v1.21 (2026-06-20): 修复维度权重不生效 bug——从 composite 结果读取 dimension_weight_method 传给 WeightEngine（之前 stock_selector 自建 WeightEngine 时缺 dimension_weight_method/factor_categories 参数，导致选股排序用不带维度权重的综合因子值，维度分组工作无效）
- v3.7 (2026-06-24): 废除 stock_selection_result.json 单文件, 改用 Parquet 分区数据集 stock_selection_history/ 作为单一信源 (designs/feat_stock_selection_history_parquet.md). 含 Stage 1/2/3 Top 30 三段, 按 selection_date 分区, file-level metadata 存 excluded_by_* 统计. apply_stage2_resort 写回 stage2_sort_value 字段.
- v3.12 (2026-06-26): 纯重构——拆分为 4 个文件: stock_selector_config.py (配置+常量+数据加载), stock_selector_lr.py (LR过滤训练/应用/训练数据保存), stock_selector_history.py (Parquet选股历史写入), stock_selector.py (门面: re-export + 核心选股逻辑 + CLI). 所有 `from stock_selector.stock_selector import X` 路径不变. 行为零变化.
- v3.14 (2026-06-26): select_stocks 内部重构——521 行"上帝函数"提取为 6 个内部辅助函数 (_load_weight_and_factors / _load_and_filter_factor_data / _standardize_and_align_direction / _compute_composite_factor / _run_selection_pipeline / _build_and_write_outputs). select_stocks 缩至 100 行编排目录. 纯重构, 行为零变化.

作者: 云瑶
创建日期: 2026-06-03
"""

import copy
import json
import logging
import sys
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, cast

import numpy as np
import pandas as pd


# sys.path 处理（遵循 MODULE.md M49）
PROJECT_ROOT = Path(__file__).parent.parent.resolve()
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))  # noqa: E402

# 当本文件作为脚本直接运行时，Python 会把脚本所在目录（stock_selector/）加入
# sys.path[0]。这导致 `import stock_selector` 找到的是 stock_selector.py 文件
# 而非 stock_selector/ 包目录，后续 `from stock_selector.xxx import` 会失败。
# 移除脚本目录以避免此冲突。
_script_dir = str(Path(__file__).parent.resolve())
while _script_dir in sys.path:
    sys.path.remove(_script_dir)

# ============================================================================
# Re-exports: 保持所有 `from stock_selector.stock_selector import X` 向后兼容
# ============================================================================

# 从 config 模块 re-export
from comprehensive_factor.common.convert_types import convert_to_native_types  # noqa: E402, F401
from comprehensive_factor.common.factor_loader import (  # noqa: E402, F401
    load_factor_values,
    load_ic_daily,
    load_ic_results,
    standardize_factors,
)
from comprehensive_factor.common.weight_engine import WeightEngine  # noqa: E402, F401
from comprehensive_factor.composite_decision_card import build_decision_cards  # noqa: E402, F401

# 保持原有 re-export（factor_definitions / factor_loader）
from factor_definitions import FACTOR_CATEGORIES, FACTOR_COL_TO_NAME_MAP  # noqa: E402, F401
from stock_selector.stock_selector_config import (  # noqa: E402, F401
    ALL_WEIGHT_METHODS,
    DEFAULT_DATA_SOURCE,
    DEFAULT_FACTOR_COLS,
    DEFAULT_FACTOR_LIST,
    DEFAULT_IC_RESULT_DIR,
    DEFAULT_OUTPUT_DIR,
    DEFAULT_WEIGHT_RESULT_PATH,
    EPSILON,
    PROJECT_ROOT,
    StockSelectorConfig,
    get_latest_date,
    load_selected_factors_from_composite,
    load_weight_config,
)

# 从 history 模块 re-export
from stock_selector.stock_selector_history import write_selection_history  # noqa: E402, F401

# 从 lr 模块 re-export
from stock_selector.stock_selector_lr import (  # noqa: E402, F401
    apply_lr_filter,
    backfill_forward_return_1d,
    calibrate_lr_filter,
    save_lr_training_data,
)


# 版本号（遵循 PROJECT.md 规范）
__version__ = "3.12"

# logger 实例（遵循 PROJECT.md 第380-500行日志规范）
_logger = logging.getLogger("stock_selector.selector")


# ============================================================================
# 核心选股函数
# ============================================================================


def apply_secondary_sort(
    stage1_stocks: list[dict[str, Any]],
    factor_df: pd.DataFrame,
    config: "StockSelectorConfig",
    selection_date: str,
    logger: logging.Logger | None = None,
) -> list[dict[str, Any]]:
    """v3.16: 小股票池二次排序（通用因子加权框架）.

    对 Stage 1 候选池的全部股票, 用 config.secondary_sort_factor_weights
    指定的因子做加权二次排序.

    v3.16 调整: 从 (composite×0.5 + turnover×0.3 + market_cap×0.2) 改为
    (composite×0.1 + price_position_flip×0.4 + tail_price_slope_flip×0.3 + positive_day×0.2).
    实证依据: 6管线1166只股票统一分析——composite IC 3/6天为负值,
    price_position 5/6天优于全量(+10.4pp), turnover/market_cap p>0.05.

    仅当 enable_secondary_sort=True 且股票池 ≤ secondary_sort_pool_threshold 时生效.
    当前活跃子集管线: ob_quality（~75K 行 → 候选池 <400 只），default 全市场不启用.

    Args:
        stage1_stocks: Stage 1 候选池 (sort_and_select 返回)
        factor_df: 因子 DataFrame (含各因子列)
        config: 选股配置
        selection_date: 选股日期
        logger: 日志

    Returns:
        二次排序后的股票列表 (rank 重新分配)
    """
    if logger is None:
        logger = _logger

    # 条件检查: 开关 + 股票池大小
    if not config.enable_secondary_sort:
        return stage1_stocks

    if len(stage1_stocks) > config.secondary_sort_pool_threshold:
        logger.info(
            "二次排序跳过: 股票池 %d > 阈值 %d",
            len(stage1_stocks),
            config.secondary_sort_pool_threshold,
        )
        return stage1_stocks

    if len(stage1_stocks) == 0:
        return stage1_stocks

    # 构建 DataFrame
    df = pd.DataFrame(stage1_stocks).copy()
    df["code"] = df["code"].astype(str)

    factor_weights = config.secondary_sort_factor_weights
    flip_factors = config.secondary_sort_flip_factors

    # 加载完整因子数据 (factor_df 可能只含少数列)
    full_factor_path = config.data_source
    factor_map: dict[str, dict[str, float]] = {}  # code → {factor_name: value}

    try:
        if full_factor_path.exists():
            # 读取 Parquet schema 获取可用列名
            import pyarrow.parquet as pq

            schema = pq.read_schema(full_factor_path)
            available_cols = [f.name for f in schema]
            load_cols = ["date", "asset"] + [f for f in factor_weights if f != "composite" and f in available_cols]
            full_df = pd.read_parquet(full_factor_path, columns=load_cols)
            day_df = full_df[full_df["date"].astype(str) == selection_date]
            # 构建 code → factor_value 映射
            for factor_name in factor_weights:
                if factor_name == "composite" or factor_name not in day_df.columns:
                    continue
                series = day_df.set_index("asset")[factor_name]
                for code, val in series.items():
                    if code not in factor_map:
                        factor_map[code] = {}
                    factor_map[code][factor_name] = float(val)
    except Exception as exc:
        logger.warning("二次排序: 因子数据加载失败 (%s)", exc)

    # 计算各因子 z-score
    z_scores: dict[str, pd.Series] = {}

    for factor_name, weight in factor_weights.items():
        if factor_name == "composite":
            # composite 已在 stage1_stocks 中
            vals = df["composite_value"].copy()
        else:
            # 从 factor_map 获取
            vals = df["code"].map(lambda c, fn=factor_name: factor_map.get(c, {}).get(fn, np.nan))

        # z-score 标准化 (截面)
        mean = vals.mean()
        std = vals.std()
        z = pd.Series(0.0, index=df.index) if std < 1e-10 else (vals - mean) / std

        # 方向翻转: flip_factors 中的因子乘 -1 (选低值股)
        if factor_name in flip_factors:
            z = -z

        z = z.fillna(0.0)
        z_scores[factor_name] = z

        # 记录因子值到 df (供输出展示)
        df[f"_ss_{factor_name}"] = vals

    # 加权求和
    secondary_score = pd.Series(0.0, index=df.index)
    weight_parts = []
    for factor_name, weight in factor_weights.items():
        secondary_score += z_scores[factor_name] * weight
        if factor_name in flip_factors:
            weight_parts.append(f"{factor_name}_flip×{weight}")
        else:
            weight_parts.append(f"{factor_name}×{weight}")

    df["secondary_score"] = secondary_score

    # 按 secondary_score 降序排列
    df = df.sort_values("secondary_score", ascending=False).reset_index(drop=True)

    # 重新分配 rank
    df["rank"] = range(1, len(df) + 1)
    df["secondary_rank"] = df["rank"]

    # 构建输出 (保留原始 factor_values, 添加二次排序信息)
    result = []
    for _, row in df.iterrows():
        stock = {
            "rank": int(row["rank"]),
            "code": row["code"],
            "composite_value": float(row["composite_value"]),
            "factor_values": row.get("factor_values", {}),
            "factor_values_std": row.get("factor_values_std", {}),
            "weight_coverage": float(row["weight_coverage"]) if pd.notna(row.get("weight_coverage")) else None,
            "secondary_score": round(float(row["secondary_score"]), 6),
            "secondary_rank": int(row["secondary_rank"]),
        }
        # 添加各因子原始值 (供报告展示)
        for factor_name in factor_weights:
            val = row.get(f"_ss_{factor_name}", np.nan)
            if pd.notna(val):
                stock[f"ss_{factor_name}"] = round(float(val), 4)
        result.append(stock)

    logger.info(
        "二次排序完成: %d 只股票 (%s)",
        len(result),
        " + ".join(weight_parts),
    )

    return result


def sort_and_select(
    composite_factor: pd.Series,
    factor_df: pd.DataFrame,
    top_n: int,
    factor_direction: str,
    factor_cols: list[str],  # 问题 7 修复：显式传入，去掉对 "_std" 后缀的猜测
    weights: dict[str, float] | None = None,  # v1.10: 因子权重（用于覆盖率过滤）
    min_weight_coverage: float = 0.5,  # v1.10→v1.17: 最低因子权重覆盖率（50%安全网，不再需要70%因为v1.17中性填充已天然惩罚缺失因子）
    min_amplitude: float = 0.01,  # v1.12: 最低振幅阈值（排除不可交易的一字板涨停股）
    max_exposure: float = 0.7,  # v2.20: 单因子最大贡献占比（超限按比例缩减综合因子值）
    enable_liquidity_filter: bool = False,  # v2.41 (R1): 默认关闭——已前置到 factor_generator
    min_amount_percentile: float = 0.05,  # v2.40: 底部 5% 成交额排除（百分位自适应）
    logger: logging.Logger | None = None,
) -> tuple[list[dict[str, Any]], int, int, int]:
    """排序并选出 Top N 股票

    Args:
        composite_factor: 综合因子值 Series（索引与 factor_df 一致）
        factor_df: 因子 DataFrame（包含 asset 列）
        top_n: 选股数量
        factor_direction: 因子方向 ('positive' 或 'negative')
        factor_cols: 因子列名列表
        weights: 因子权重字典（v1.10: 用于覆盖率过滤）
        min_weight_coverage: 最低因子权重覆盖率阈值（默认0.5=50%安全网）
        min_amplitude: 最低振幅阈值（v1.12: 默认0.01=1%，排除一字板涨停股）
        max_exposure: 单因子最大贡献占比（v2.20: 默认0.7=70%）
        enable_liquidity_filter: v2.41 (R1): 紧急开关（默认 False）.
            R1 已将流动性过滤前置到 factor_generator (_mark_low_liquidity, 截面 P5),
            上游加载器 (factor_loader / data_loader / layered_backtest_runner) 自动过滤.
            此开关仅在需二次兜底时手动启用, 默认关闭以避免重复过滤.
        min_amount_percentile: v2.40: 最低成交额分位（默认0.05=排除底部5%）
        logger: 日志对象（默认使用模块级 _logger）

    Returns:
        Tuple[选股结果列表, 振幅过滤排除数, 覆盖率过滤排除数, 流动性过滤排除数]
        选股结果列表结构：
        [
            {"rank": 1, "code": "000001", "composite_value": -2.35, "factor_values": {...}},
            ...
        ]
        振幅过滤排除数：因振幅不足阈值被排除的股票数量

    Note:
        - positive（正向）: 降序排序，值越大越好
        - negative（反向）: 升序排序，值越小越好
        - 缺失值（NaN）不参与排序，排在最后
        - v1.10: 新增因子覆盖率过滤——缺失因子权重之和超过阈值则排除

        v2.40 流动性过滤设计：
        - amount = volume × close（元，实际成交额）
        - 截面分位自适应：排除每天成交额最低的 5%（min_amount_percentile）
        - 不使用硬编码阈值（如 500 万），因为牛市/熊市的成交额量级差异大
        - 核心思想：切除尾部流动性最差的股票，避免价格扭曲
        - 需要 volume + close 列同时存在时才启用

    Contract:
        - 问题 6 修复：composite_factor.index 必须与 factor_df.index 对齐
          否则 result_df["composite_factor"] = composite_factor 会大面积 NaN
        - WeightEngine.calculate 返回的 Series 已保证索引对齐

    Raises:
        ValueError: composite_factor 索引与 factor_df 不对齐
    """
    if logger is None:
        logger = _logger

    # 问题 6 修复：防御性校验索引对齐
    if not composite_factor.index.equals(factor_df.index):
        raise ValueError(
            "composite_factor 索引与 factor_df 不对齐\n"
            f"composite_factor.index: {composite_factor.index[:5].tolist()}...\n"
            f"factor_df.index: {factor_df.index[:5].tolist()}...\n"
            "请检查 WeightEngine.calculate 返回值契约"
        )

    # 构建 DataFrame（包含综合因子值）
    result_df = factor_df.copy()
    result_df["composite_factor"] = composite_factor

    # 过滤有效值（非 NaN）
    valid_mask = result_df["composite_factor"].notna()
    valid_count = valid_mask.sum()
    logger.info("有效综合因子值: %d 条（总计 %d 条）", valid_count, len(result_df))

    if valid_count == 0:
        raise ValueError(
            "综合因子值全部为 NaN，无法排序选股\n可能原因:\n  1. 所有因子值缺失\n  2. 标准化计算异常\n  3. 权重计算异常"
        )

    # v1.10→v1.17: 因子覆盖率过滤（安全网）
    # v1.17 中性填充策略：缺失因子 z=0 填充，综合因子值天然趋中，不再虚高
    # 此过滤仅作安全网：排除缺失超过一半因子的极端股票（覆盖率<50%）
    # 正常缺失1-2个因子的股票（覆盖率≥50%）由中性填充自然惩罚，无需显式排除
    total_weight = sum(abs(w) for w in weights.values()) if weights else 0.0
    # v1.11: fallback — Rolling ICIR 的 last_day_weights 可能为空，使用等权替代
    coverage_weights = weights if weights and total_weight > 0 else dict.fromkeys(factor_cols, 1.0 / len(factor_cols))
    coverage_total = sum(abs(w) for w in coverage_weights.values())

    excluded_by_coverage = 0  # v1.15: 初始化，供返回值使用
    if coverage_weights and min_weight_coverage > 0 and coverage_total > 0:
        # 计算每只股票的因子覆盖率
        # coverage = (该股票非NaN因子权重之和) / coverage_total
        stock_coverage = pd.Series(1.0, index=result_df.index)
        for col, w in coverage_weights.items():  # v1.11: 使用 coverage_weights（含 fallback）
            # v1.14: 用 _std 列判断可用性（综合因子用 std 计算，std=NaN 则该因子不贡献）
            std_col = f"{col}_std"
            if std_col in result_df.columns and coverage_total > 0:
                factor_weight_ratio = abs(w) / coverage_total
                is_available = result_df[std_col].notna()
                stock_coverage = stock_coverage.where(is_available, stock_coverage - factor_weight_ratio)

        coverage_mask = stock_coverage >= min_weight_coverage
        excluded_by_coverage = int(valid_mask.sum() - (valid_mask & coverage_mask).sum())

        if excluded_by_coverage > 0:
            logger.info(
                "因子覆盖率过滤: 排除 %d 只股票（覆盖率 < %.0f%%，缺失高权重因子导致综合因子值不可信）",
                excluded_by_coverage,
                min_weight_coverage * 100,
            )
        # 合覆盖率过滤到 valid_mask
        valid_mask = valid_mask & coverage_mask

    # v1.12→v1.17: 振幅过滤已移除，不可交易股票（涨停类）由 factor_loader 在数据加载层过滤
    # is_untradeable 列（T 日涨停=1）在 load_full_data 阶段已排除，此处无需重复
    excluded_by_amplitude = 0

    # v2.20: 单因子暴露限制——任一因子贡献占比超 max_exposure 时按比例缩减综合因子值
    # 效果：降低单因子主导股票的排名，让多元化信号更强的股票上升
    if max_exposure > 0 and weights:
        contrib_cols = []
        for col, w in weights.items():
            std_col = f"{col}_std"
            if std_col in result_df.columns and abs(w) > 0:
                result_df[f"_contrib_{col}"] = result_df[std_col].fillna(0) * w
                contrib_cols.append(f"_contrib_{col}")
        if contrib_cols:
            max_contrib = result_df[contrib_cols].abs().max(axis=1)
            abs_composite = composite_factor.abs()
            # dominance = max(|contrib|) / |composite|，仅对非零综合因子计算
            dominance = max_contrib / abs_composite.where(abs_composite > 1e-12, np.nan)
            over_limit = dominance > max_exposure
            if over_limit.any():
                # 按比例缩减：scale = max_exposure / dominance
                scale = pd.Series(1.0, index=composite_factor.index)
                scale[over_limit] = max_exposure / dominance[over_limit]
                composite_factor = composite_factor * scale
                result_df["composite_factor"] = composite_factor
                logger.info(
                    "单因子暴露限制: %d 只股票被降权（单因子贡献占比 > %.0f%%）",
                    int(over_limit.sum()),
                    max_exposure * 100,
                )
            # 清理临时列
            result_df.drop(columns=contrib_cols, inplace=True)

    # v2.40: 流动性过滤（截面分位自适应，design.md §3.3）
    # 切除尾部成交额最低的 min_amount_percentile（默认 5%）股票
    # 数据：amount = volume × close（元）；不使用硬编码阈值
    excluded_by_liquidity = 0
    if enable_liquidity_filter:
        has_volume = "volume" in result_df.columns
        has_close = "close" in result_df.columns
        if has_volume and has_close:
            amount = result_df["volume"].astype(float) * result_df["close"].astype(float)
            # 仅对 valid（综合因子非 NaN）股票计算阈值
            valid_amount = amount[valid_mask & amount.notna() & (amount > 0)]
            if len(valid_amount) > 0:
                threshold = valid_amount.quantile(min_amount_percentile)
                liquidity_mask = (amount >= threshold) & amount.notna()
                excluded_by_liquidity = int(valid_mask.sum() - (valid_mask & liquidity_mask).sum())
                if excluded_by_liquidity > 0:
                    logger.info(
                        "流动性过滤: P%d=%.0f 万元, 排除 %d 只股票（成交额过低，IC 关系失效区域）",
                        int(min_amount_percentile * 100),
                        threshold / 1e4,
                        excluded_by_liquidity,
                    )
                valid_mask = valid_mask & liquidity_mask
            else:
                logger.warning("流动性过滤跳过: 无有效 amount 数据")
        else:
            logger.warning(
                "流动性过滤跳过: factor_df 缺少 volume/close 列 (has_volume=%s, has_close=%s)",
                has_volume,
                has_close,
            )

    # 排序（根据因子方向）
    # ascending=True 升序（反向因子：值越小越好）
    # ascending=False 降序（正向因子：值越大越好）
    ascending: bool = factor_direction == "negative"

    # 先过滤有效值，再排序
    sorted_df = result_df[valid_mask].sort_values(by="composite_factor", ascending=ascending)

    # 取 Top N
    # 如果 top_n > 有效股票数，返回所有有效股票
    actual_n = min(top_n, len(sorted_df))
    top_stocks = sorted_df.head(actual_n)

    logger.info(
        "选出 Top %d 股票（排序方向: %s，实际有效股票: %d）",
        actual_n,
        "升序" if ascending else "降序",
        len(sorted_df),
    )

    # 构建结果列表
    result_list = []
    for rank_idx, (_, row) in enumerate(top_stocks.iterrows(), start=1):
        # 提取因子值（问题 7 修复：只输出显式列名集合）
        # v1.3 新增：标准化因子值（z-score，经 Winsorize ±3σ 截断）
        # 报告应显示标准化值而非原始值，避免比率型因子原始极端值误导用户
        # 如 momentum_strength 原始值=-9.08 看似极端，但标准化 z=-2.65，有效贡献仅 2%×-2.65
        # v1.4: factor_values/factor_values_std 的 key 统一用逻辑名（与 weight_config.factor_list 一致），
        #   通过 FACTOR_COL_TO_NAME_MAP 反向映射列名→逻辑名，避免 rsi_6 vs rsi 不一致
        factor_values = {}
        factor_values_std = {}
        for col in factor_cols:
            logic_name = FACTOR_COL_TO_NAME_MAP.get(col, col)
            if col in row:
                val = row[col]
                # 问题 1 修复：只判 pd.isna，EPSILON 不该用于数值合法性判断
                if pd.isna(val):
                    factor_values[logic_name] = None
                else:
                    factor_values[logic_name] = convert_to_native_types(val)
            # 标准化值（_std 列由 standardize_factors 生成，经 Winsorize ±3σ 截断）
            std_col = f"{col}_std"
            if std_col in row:
                std_val = row[std_col]
                if pd.isna(std_val):
                    factor_values_std[logic_name] = None
                else:
                    factor_values_std[logic_name] = round(convert_to_native_types(std_val), 4)

        # v1.10→v1.11: 计算该股票的因子覆盖率（使用 coverage_weights 含 fallback）
        # v1.14: 用 _std 列判断可用性（综合因子用 std 计算，std=NaN 则该因子不贡献）
        if coverage_weights and coverage_total > 0:
            available_weight = sum(
                abs(w)
                for col, w in coverage_weights.items()
                if col in factor_cols and (f"{col}_std" in row and pd.notna(row[f"{col}_std"]))
            )
            weight_coverage = available_weight / coverage_total
        else:
            weight_coverage = 1.0

        result_list.append(
            {
                "rank": rank_idx,
                "code": row["asset"],
                "composite_value": convert_to_native_types(row["composite_factor"]),
                "factor_values": factor_values,
                "factor_values_std": factor_values_std,  # v1.3: 标准化值（z-score，Winsorize ±3σ）
                "weight_coverage": round(weight_coverage, 4),  # v1.10: 因子覆盖率
            }
        )

    return result_list, excluded_by_amplitude, excluded_by_coverage, excluded_by_liquidity


def apply_filter_role_factors(
    candidates_df: pd.DataFrame,
    logger: logging.Logger | None = None,
) -> tuple[pd.DataFrame, dict[str, int]]:
    """filter 角色因子硬过滤 (R3, designs/feat_filter_role_fundamental_breakdown.md §3.3)

    在 composite 计算之前应用基本面恶化硬过滤, 排除已发生恶化的股票.
    filter 角色因子 = 客观事实 (非概率信号), 用经济意义阈值做硬约束.

    当前阈值 (v1.0, 单一过滤器):
    - cum_return_5d_breakdown: return_5d < -0.10 → 排除

    Args:
        candidates_df: 候选股票 DataFrame (含 return_5d 等列).
        logger: 日志对象.

    Returns:
        (filtered_df, exclusion_counts): 过滤后 DataFrame + 各过滤器排除数 dict.
    """
    if logger is None:
        logger = _logger

    exclusion_counts: dict[str, int] = {}
    df = candidates_df.copy()

    # cum_return_5d_breakdown: return_5d < -10%
    if "return_5d" in df.columns:
        breakdown_mask = df["return_5d"].notna() & (df["return_5d"] < -0.10)
        n_excluded = int(breakdown_mask.sum())
        exclusion_counts["cum_return_5d_breakdown"] = n_excluded
        if n_excluded > 0:
            df = df[~breakdown_mask].reset_index(drop=True)
            logger.info(
                "filter[cum_return_5d_breakdown]: 排除 %d 只 (return_5d < -10%%)",
                n_excluded,
            )
    else:
        logger.warning("filter[cum_return_5d_breakdown]: 缺 return_5d 列, 跳过过滤")
        exclusion_counts["cum_return_5d_breakdown"] = 0

    return df, exclusion_counts


def apply_stage2_resort(
    stage1_stocks: list[dict[str, Any]],
    factor_df: pd.DataFrame,
    target_n: int,
    sort_col: str,
    ascending: bool,
    logger: logging.Logger | None = None,
) -> list[dict[str, Any]]:
    """Stage 2 重排 (v2.44): 在 Stage 1 候选内按 sort_col 排序取 target_n.

    设计依据: designs/feat_two_stage_stock_selector_v244.md
    第一性原理:
        composite 是 17 个因子的线性加权, IC 是截面均值——能保证 layer_1 整体优于 layer_5,
        但不保证 layer_1 内最极值的 30 只仍优于中间分位 (线性尾部失效).
        Stage 2 用次级变量 (默认 turnover_rate 升序) 在 Stage 1 池子内重排, 避开尾部失效区间.

    OOS 验证 (后 30% 日历, 163 日, designs/feat_two_stage_stock_selector_v244.md §2):
        - turnover 升序: IS=14.10% → OOS=10.43%, 衰减仅 4pp (最稳健)
        - 经济意义: composite 主方向 negative, Top 端 = 最弱势股. 升序 = 未被游资关注的
          冷门弱势股. 高 turnover 弱势股 = 游资爆炒后被洗 = T+1 大概率继续抛.

    Args:
        stage1_stocks: Stage 1 候选 (来自 sort_and_select, 长度 = stage1_pool_size)
        factor_df: 当日 factor DataFrame, 必须含 'asset' 和 sort_col 列
        target_n: Stage 2 输出数量 (= top_n × 2, 留给企稳过滤递补)
        sort_col: Stage 2 排序列 (默认 'turnover_rate')
        ascending: True 升序 (低值优先), False 降序
        logger: 日志对象

    Returns:
        Stage 2 重排后的 stocks (长度 ≤ target_n), 每只新增 'stage1_rank' 字段保留 Stage 1 名次.
    """
    if logger is None:
        logger = _logger

    if not stage1_stocks:
        return stage1_stocks

    if sort_col not in factor_df.columns:
        logger.warning(
            "Stage 2 排序列 %s 不存在于 factor_df, 跳过 Stage 2 重排, 直接截取 Stage 1 前 %d 只",
            sort_col,
            target_n,
        )
        return stage1_stocks[:target_n]

    if "asset" not in factor_df.columns:
        logger.warning("factor_df 缺 asset 列, 跳过 Stage 2 重排")
        return stage1_stocks[:target_n]

    # 构建 asset → sort_col 值映射
    asset_to_val: dict[str, float] = factor_df.set_index("asset")[sort_col].to_dict()

    # NaN / 缺失值排到末尾 (升序时 +inf, 降序时 -inf)
    sentinel = float("inf") if ascending else float("-inf")

    def _sort_key(stock: dict[str, Any]) -> float:
        val = asset_to_val.get(stock["code"], sentinel)
        if isinstance(val, float) and np.isnan(val):
            return sentinel
        return float(val)

    sorted_stocks = sorted(stage1_stocks, key=_sort_key, reverse=not ascending)

    # 统计有效值
    n_with_val = sum(
        1
        for s in stage1_stocks
        if s["code"] in asset_to_val
        and not (isinstance(asset_to_val[s["code"]], float) and np.isnan(asset_to_val[s["code"]]))
    )
    logger.info(
        "Stage 2 重排: 输入 %d 只, 排序 %s (%s), 有效 %s 值 %d 只, 输出 %d 只",
        len(stage1_stocks),
        sort_col,
        "升序" if ascending else "降序",
        sort_col,
        n_with_val,
        min(target_n, len(sorted_stocks)),
    )

    # 保留 Stage 1 rank, 重新编号 rank 为 Stage 2 名次
    # v3.7: 同时把排序值 sort_col 写回 stock['stage2_sort_value'], 供 Parquet 归档 (design §2.2)
    result = sorted_stocks[:target_n]
    for idx, stock in enumerate(result, start=1):
        stock["stage1_rank"] = stock.get("rank", idx)  # 保留 Stage 1 名次
        stock["rank"] = idx  # Stage 2 后的临时 rank (企稳过滤后会再次重编号)
        raw_val = asset_to_val.get(stock["code"])
        if raw_val is not None and not (isinstance(raw_val, float) and np.isnan(raw_val)):
            stock["stage2_sort_value"] = float(raw_val)
        else:
            stock["stage2_sort_value"] = None

    return result


def apply_stabilization_filter(
    top_stocks: list[dict[str, Any]],
    factor_df: pd.DataFrame,
    top_n: int,
    logger: logging.Logger | None = None,
) -> tuple[list[dict[str, Any]], int]:
    """P6 企稳确认过滤器（v2.35）

    在选股排序后，检查候选股票是否有企稳信号。
    排除没有企稳信号的股票（如放量下跌无承接），从后续排名递补。

    公理4推论4: 只有"跌了多少"无"是否企稳"，无法区分错杀vs基本面恶化。
    本过滤器用 P5 新增的确认信号因子判断"是否企稳"。

    企稳条件（任一满足即通过）:
    - volume_shrink_rate < 1.0（缩量，卖盘衰竭）
    - price_volume_divergence > 0（价跌量缩背离，止跌信号）
    - lower_shadow_ratio > 0.3（下影线承接）

    如果确认信号因子列不存在或值为 NaN，跳过过滤（不排除）。

    Args:
        top_stocks: sort_and_select 返回的候选股票列表（应 ≥ top_n）
        factor_df: 单日因子 DataFrame（包含 asset 列）
        top_n: 最终选股数量
        logger: 日志对象

    Returns:
        (filtered_stocks, excluded_count)
    """
    if logger is None:
        logger = _logger

    confirmation_cols = ["volume_shrink_rate", "price_volume_divergence", "lower_shadow_ratio"]
    available_cols = [c for c in confirmation_cols if c in factor_df.columns]

    if not available_cols:
        logger.info("企稳确认过滤: 确认信号因子不可用，跳过过滤")
        return top_stocks[:top_n], 0

    # 构建 asset → row 索引（单日数据，asset 唯一）
    asset_index = factor_df.set_index("asset") if "asset" in factor_df.columns else factor_df

    filtered: list[dict[str, Any]] = []
    excluded = 0
    for stock in top_stocks:
        if len(filtered) >= top_n:
            break

        code = stock["code"]
        row = asset_index.loc[code] if code in asset_index.index else None
        if row is None:
            filtered.append(stock)
            continue

        vol_shrink = row.get("volume_shrink_rate", np.nan)
        pv_div = row.get("price_volume_divergence", np.nan)
        lower_shadow = row.get("lower_shadow_ratio", np.nan)

        # 全部 NaN → 数据不可用，跳过过滤
        if pd.isna(vol_shrink) and pd.isna(pv_div) and pd.isna(lower_shadow):
            filtered.append(stock)
            continue

        # 企稳条件（任一满足即通过）
        is_stabilizing = (
            (not pd.isna(vol_shrink) and vol_shrink < 1.0)
            or (not pd.isna(pv_div) and pv_div > 0)
            or (not pd.isna(lower_shadow) and lower_shadow > 0.3)
        )

        if is_stabilizing:
            filtered.append(stock)
        else:
            excluded += 1
            logger.debug(
                "企稳过滤排除: %s (缩量率=%.3f, 背离=%.4f, 下影线=%.3f)",
                code,
                vol_shrink,
                pv_div,
                lower_shadow,
            )

    # 不足 top_n 时用被排除的股票递补（向后兼容）
    if len(filtered) < top_n:
        filtered_codes = {s["code"] for s in filtered}
        for stock in top_stocks:
            if len(filtered) >= top_n:
                break
            if stock["code"] not in filtered_codes:
                stock["stabilization_warning"] = True
                filtered.append(stock)

    # 重新编号 rank
    for idx, stock in enumerate(filtered[:top_n], start=1):
        stock["rank"] = idx

    logger.info(
        "企稳确认过滤: 候选 %d → 通过 %d, 排除 %d",
        len(top_stocks),
        min(len(filtered), top_n),
        excluded,
    )

    return filtered[:top_n], excluded


def build_result(
    top_stocks: list[dict[str, Any]],
    config: StockSelectorConfig,
    weight_config: dict[str, Any],
    stocks_on_date: int,  # 问题 2 修复：选股日期当天股票数
    factor_list: list[str],  # 问题 5 修复：运行时变量
    factor_cols: list[str],  # 问题 5 修复：运行时变量
    selection_date: str,  # 问题 5 修复：运行时变量
    direction_map: dict[str, str] | None = None,  # v1.10: 方向映射（报告展示需要）
    flipped_factors: list[str] | None = None,  # v1.10: 取反因子列表（报告展示需要）
    excluded_by_amplitude: int = 0,  # v1.12: 振幅过滤排除数
    excluded_by_coverage: int = 0,  # v1.15: 覆盖率过滤排除数
    excluded_by_liquidity: int = 0,  # v2.40: 流动性过滤排除数
    excluded_by_confirmation: int = 0,  # v2.35: P6 企稳确认过滤排除数 (v3.9: 恒为 0)
    excluded_by_overheat: int = 0,  # v3.9: Bottom30 过热过滤排除数
    excluded_by_filter: dict[str, int] | None = None,  # v2.41 (R3): filter 角色排除数
    min_weight_coverage: float = 0.5,  # v1.15: 覆盖率阈值
    secondary_sorted_stocks: list[dict[str, Any]] | None = None,  # v3.15: 二次排序结果
    logger: logging.Logger | None = None,
) -> dict[str, Any]:
    """构建输出结果

    Args:
        top_stocks: 选股结果列表
        config: 配置对象
        weight_config: 权重配置
        stocks_on_date: 选股日期当天股票数（问题 2 修复：语义精确）
        factor_list: 因子列表
        factor_cols: 因子列名列表
        selection_date: 选股日期
        logger: 日志对象（默认使用模块级 _logger）

    Returns:
        输出结果字典，结构见输出模板
    """
    if logger is None:
        logger = _logger

    best_selection = weight_config["best_selection"]

    result = {
        "meta": {
            "selection_date": selection_date,
            "weight_method": best_selection["method"],
            # 问题 1 修复：直接访问，与 load_weight_config 契约对齐
            "composite_score": best_selection["composite_score"],
            "factor_direction": config.factor_direction,
            "top_n": config.top_n,
            # v2.44: 两阶段选股元数据 (designs/feat_two_stage_stock_selector_v244.md)
            "two_stage_selection": {
                "enabled": config.enable_two_stage,
                "stage1_pool_size": config.stage1_pool_size if config.enable_two_stage else None,
                "stage2_sort_col": config.stage2_sort_col if config.enable_two_stage else None,
                "stage2_ascending": config.stage2_ascending if config.enable_two_stage else None,
            },
            # 问题 2 修复：字段名改为 stocks_on_date，语义精确
            "stocks_on_date": stocks_on_date,
            "valid_stocks": len(top_stocks),
            # 问题 5 修复：显式带时区，跨机部署时间戳更稳
            "created_at": datetime.now(timezone.utc).isoformat(),
            # v1.10: 方向处理信息（报告展示需要）
            "direction_map": direction_map or {},
            "flipped_factors": flipped_factors or [],
            # v1.12: 振幅过滤信息（报告展示需要）
            "min_amplitude": config.min_amplitude,
            "excluded_by_amplitude": excluded_by_amplitude,
            # v1.15: 覆盖率过滤信息（报告展示需要）
            "excluded_by_coverage": excluded_by_coverage,
            "min_weight_coverage": min_weight_coverage,
            # v2.40: 流动性过滤信息（成交额截面分位过滤）
            "excluded_by_liquidity": excluded_by_liquidity,
            # v2.35: P6 企稳确认过滤信息 (v3.9: 恒为 0)
            "excluded_by_confirmation": excluded_by_confirmation,
            # v3.9: Bottom30 过热过滤信息
            "excluded_by_overheat": excluded_by_overheat,
            # v2.41 (R3): filter 角色硬过滤信息
            "excluded_by_filter": excluded_by_filter or {},
            # v3.15: 二次排序信息
            "secondary_sort": {
                "enabled": config.enable_secondary_sort,
                "pool_threshold": config.secondary_sort_pool_threshold,
                "factor_weights": config.secondary_sort_factor_weights,
                "flip_factors": config.secondary_sort_flip_factors,
                "count": len(secondary_sorted_stocks) if secondary_sorted_stocks else 0,
            },
        },
        "top_stocks": top_stocks,
        "secondary_sorted_stocks": secondary_sorted_stocks or [],
        "weight_config": {
            "method": best_selection["method"],
            "window": config.rolling_window if best_selection["method"] == "rolling_icir_weight" else None,
            "factor_list": factor_list,
            "factor_cols": factor_cols,
        },
    }

    logger.info("结果构建完成: 选股日期=%s，Top N=%d", selection_date, len(top_stocks))

    return result


def _compute_composite_for_method(
    method: str,
    factor_df_orig: pd.DataFrame,
    composite_data: dict[str, Any],
    config: "StockSelectorConfig",
    logger: logging.Logger,
) -> tuple[pd.Series, list[str], list[str]] | None:
    """v3.11: 对单个 weight_method 计算 composite_factor.

    从 composite_<method>_1d.json 读取 factor_list/factor_cols/direction_map,
    执行 standardize + direction_flip + weight_engine.calculate.

    Args:
        method: 权重方式名 (equal_weight/icir_weight/ic_weight/rolling_icir_weight)
        factor_df_orig: 原始因子 DataFrame (不修改, 内部 copy)
        composite_data: composite_<method>_1d.json 的完整 dict
        config: StockSelectorConfig
        logger: 日志对象

    Returns:
        (composite_factor, factor_list, factor_cols) 或 None (计算失败)
    """
    meta = composite_data.get("meta", {})
    factor_list = meta.get("factor_list", [])
    factor_cols = meta.get("factor_cols", [])
    if not factor_cols:
        logger.warning("[v3.11] %s: factor_cols 为空, 跳过", method)
        return None

    # 检查 factor_cols 是否都在 factor_df 中
    missing_cols = [c for c in factor_cols if c not in factor_df_orig.columns]
    if missing_cols:
        logger.warning("[v3.11] %s: %d 个因子列缺失: %s", method, len(missing_cols), missing_cols[:5])
        return None

    # copy 避免标准化的 _std 列污染其他方式
    factor_df = factor_df_orig.copy()

    # Step 7: 标准化
    factor_df = standardize_factors(factor_df, factor_cols, logger)

    # Step 7.5: 方向统一化
    direction_map = composite_data.get("config", {}).get("direction_map", {})

    if direction_map:
        for i, col in enumerate(factor_cols):
            factor_name = factor_list[i] if i < len(factor_list) else col
            direction = direction_map.get(factor_name, "unknown")
            std_col = f"{col}_std"
            if direction == "negative" and std_col in factor_df.columns:
                factor_df[std_col] = -factor_df[std_col]
    else:
        # 回退: 从 ic_results 计算方向
        logger.debug("[v3.11] %s: direction_map 为空, 从 ic_results 计算", method)
        ic_results_dir, _ = load_ic_results(factor_list, config.ic_result_dir, config.return_period, logger)
        for i, col in enumerate(factor_cols):
            factor_name = factor_list[i] if i < len(factor_list) else col
            ic_info = ic_results_dir.get(factor_name, {})
            ic_mean_val = ic_info.get("ic_mean")
            std_col = f"{col}_std"
            if ic_mean_val is not None and ic_mean_val < 0 and std_col in factor_df.columns:
                factor_df[std_col] = -factor_df[std_col]

    # Step 8: 加载 IC 数据
    ic_results = None
    ic_daily_data = None
    if method == "rolling_icir_weight":
        ic_daily_data = load_ic_daily(factor_list, config.ic_result_dir, config.return_period, logger)
    elif method in ("icir_weight", "ic_weight"):
        ic_results, _ = load_ic_results(factor_list, config.ic_result_dir, config.return_period, logger)

    # Step 9: 计算综合因子
    short_sample_factors = meta.get("selection_result", {}).get("short_sample_factors")
    dimension_weight_method = meta.get("weight_meta", {}).get("dimension_weight_method")
    enable_role_weights = meta.get("weight_meta", {}).get("enable_role_weights", True)

    weight_engine = WeightEngine(
        weight_method=method,
        window=config.rolling_window,
        logger=logger,
        dimension_weight_method=dimension_weight_method,
        factor_categories=FACTOR_CATEGORIES if dimension_weight_method else None,
        enable_role_weights=enable_role_weights,
    )
    composite_factor = weight_engine.calculate(factor_df, factor_cols, ic_results, ic_daily_data, short_sample_factors)

    logger.info("[v3.11] %s composite_factor: %d valid", method, composite_factor.notna().sum())
    return composite_factor, factor_list, factor_cols


def _load_weight_and_factors(
    config: StockSelectorConfig,
    logger: logging.Logger,
) -> tuple[dict[str, Any], str, list[str], list[str]]:
    """Step 0-3: 加载权重配置 + 因子列表 + 校验.

    Returns:
        (weight_config, best_method, factor_list, factor_cols)
    """
    # Step 0: v3.10 补写前一天 lr_training_data 的 forward_return_1d (T+1 收益)
    backfill_forward_return_1d(config.data_source, logger=logger)

    # Step 1: 加载最优权重配置（优先获取因子列表）
    weight_config = load_weight_config(config.weight_result_path, logger)
    best_method = weight_config["best_selection"]["method"]

    # Step 2: 从最优权重 composite 结果中读取选中的因子列表
    factor_list, factor_cols = load_selected_factors_from_composite(
        weight_config, config.output_dir, config.return_period, logger
    )

    # Step 3: 校验因子列表（运行时校验）
    if not factor_list or not factor_cols:
        raise ValueError("从 composite 结果读取的因子列表为空")
    if len(factor_list) != len(factor_cols):
        raise ValueError(f"factor_list ({len(factor_list)}) 与 factor_cols ({len(factor_cols)}) 数量不一致")

    return weight_config, best_method, factor_list, factor_cols


def _load_and_filter_factor_data(
    config: StockSelectorConfig,
    factor_cols: list[str],
    logger: logging.Logger,
) -> tuple[pd.DataFrame, str, int]:
    """Step 4-6: 加载因子数据 + 流动性 + 日期过滤.

    Returns:
        (factor_df, selection_date, stocks_on_date)
    """
    # Step 4: 加载因子数据
    logger.info("加载因子数据...")
    factor_df_raw = load_factor_values(factor_cols, config.data_source, logger)
    factor_df = cast(pd.DataFrame, factor_df_raw)

    # v2.40: 独立加载流动性列（volume + close），不污染 standardize_factors 工作流
    if config.enable_liquidity_filter:
        logger.info("加载流动性数据（volume + close）...")
        try:
            liquidity_df_raw = load_factor_values(["volume", "close"], config.data_source, logger)
            liquidity_df = cast(pd.DataFrame, liquidity_df_raw)
            logger.info("流动性数据加载完成: %d 条", len(liquidity_df))
        except Exception:
            logger.exception("流动性数据加载失败，将跳过流动性过滤")
            liquidity_df = None
    else:
        liquidity_df = None

    # Step 5: 确定选股日期
    selection_date = config.selection_date
    if selection_date is None:
        selection_date = get_latest_date(factor_df, logger)

    # Step 6: 过滤数据（只保留选股日期）
    available_dates = sorted({pd.Timestamp(d).strftime("%Y-%m-%d") for d in factor_df["date"].unique()})
    if selection_date not in available_dates:
        raise ValueError(
            f"选股日期 {selection_date} 无数据\n"
            f"可用日期范围: {available_dates[0]} ~ {available_dates[-1]}\n"
            f"共 {len(available_dates)} 个日期"
        )

    logger.info("过滤选股日期: %s", selection_date)
    mask = factor_df["date"].apply(lambda d: pd.Timestamp(d).strftime("%Y-%m-%d")) == selection_date
    factor_df = factor_df[mask].copy()

    # v2.40: 单日 factor_df 上 merge volume/close（仅 ~3000 行，开销极小）
    if liquidity_df is not None:
        liq_mask = liquidity_df["date"].apply(lambda d: pd.Timestamp(d).strftime("%Y-%m-%d")) == selection_date
        liquidity_day = liquidity_df[liq_mask][["asset", "volume", "close"]].copy()
        before_n = len(factor_df)
        factor_df = factor_df.merge(liquidity_day, on="asset", how="left")
        logger.info(
            "流动性列已 merge 到 factor_df: %d 行 → %d 行（volume/close 覆盖率 %.2f%%）",
            before_n,
            len(factor_df),
            factor_df["volume"].notna().mean() * 100,
        )

    stocks_on_date = len(factor_df)
    logger.info("选股日期股票数: %d", stocks_on_date)

    return factor_df, selection_date, stocks_on_date


def _standardize_and_align_direction(
    factor_df: pd.DataFrame,
    factor_list: list[str],
    factor_cols: list[str],
    weight_config: dict[str, Any],
    best_method: str,
    config: StockSelectorConfig,
    logger: logging.Logger,
) -> tuple[pd.DataFrame, dict[str, str], list[str]]:
    """Step 7-7.5: 标准化因子 + 方向统一化.

    Returns:
        (factor_df, direction_map, flipped_factors)
    """
    # Step 7: 标准化因子（截面标准化）
    logger.info("标准化因子...")
    factor_df = standardize_factors(factor_df, factor_cols, logger)

    # Step 7.5: 方向统一化（遵循 MODULE.md M56）
    direction_map: dict[str, str] = {}
    flipped_factors: list[str] = []

    # 从 composite 结果读取方向映射（已由 composite_runner 计算）
    best_method_name = weight_config["best_selection"]["method"]
    composite_file = config.output_dir / f"composite_{best_method_name}_{config.return_period}.json"

    if composite_file.exists():
        logger.info("从 composite 结果读取方向映射: %s", composite_file)
        try:
            with open(composite_file, encoding="utf-8") as f:
                composite_data = json.load(f)
            direction_map = composite_data.get("config", {}).get("direction_map", {})
            flipped_factors = composite_data.get("config", {}).get("flipped_factors", [])
        except json.JSONDecodeError as e:
            logger.warning("composite 结果 JSON 解析失败，将回退到从 ic_results 计算: %s", e)

    # 如果 direction_map 为空，从 ic_results 自行计算（回退方案）
    if not direction_map:
        logger.info("direction_map 为空，从 ic_results 自行计算方向统一化...")
        ic_results_for_direction, _ = load_ic_results(factor_list, config.ic_result_dir, config.return_period, logger)

        for i, col in enumerate(factor_cols):
            factor_name = factor_list[i] if i < len(factor_list) else col
            ic_info = ic_results_for_direction.get(factor_name, {})
            ic_mean_val = ic_info.get("ic_mean", None)

            if ic_mean_val is None:
                direction_map[factor_name] = "unknown"
                continue

            std_col = f"{col}_std"
            if ic_mean_val < 0:
                direction_map[factor_name] = "negative"
                factor_df[std_col] = -factor_df[std_col]
                flipped_factors.append(factor_name)
                logger.info(
                    "因子 %s ic_mean=%.4f<0（反向因子），标准化值已取反以对齐正向语义",
                    factor_name,
                    ic_mean_val,
                )
            else:
                direction_map[factor_name] = "positive"
    else:
        # 使用从 composite 读取的 direction_map 执行取反
        for i, col in enumerate(factor_cols):
            factor_name = factor_list[i] if i < len(factor_list) else col
            direction = direction_map.get(factor_name, "unknown")

            std_col = f"{col}_std"
            if direction == "negative":
                factor_df[std_col] = -factor_df[std_col]
                logger.info(
                    "因子 %s（反向因子），标准化值已取反以对齐正向语义",
                    factor_name,
                )

    if flipped_factors:
        logger.info(
            "方向统一化完成: %d 个正向因子已取反 (%s)，所有因子统一为负向语义",
            len(flipped_factors),
            flipped_factors,
        )

    return factor_df, direction_map, flipped_factors


def _compute_composite_factor(
    factor_df: pd.DataFrame,
    factor_list: list[str],
    factor_cols: list[str],
    best_method: str,
    config: StockSelectorConfig,
    logger: logging.Logger,
) -> tuple[pd.Series, dict[str, Any] | None, str | None, str | None, pd.DataFrame, dict[str, int]]:
    """Step 8-9: 加载 IC 数据 + 计算综合因子.

    Returns:
        (composite_factor, selection_weights, dimension_weight_method, short_sample_factors, factor_df, filter_exclusions)
        factor_df 可能被 apply_filter_role_factors 修改 (R3 过滤).
    """
    # Step 8: 加载 IC 数据（根据权重方法）
    ic_results = None
    ic_daily_data = None

    if best_method == "rolling_icir_weight":
        logger.info("加载 IC 每日序列（滚动 ICIR 需要）...")
        ic_daily_data = load_ic_daily(factor_list, config.ic_result_dir, config.return_period, logger)
    elif best_method in ("icir_weight", "ic_weight"):
        logger.info("加载 IC 统计结果（静态权重需要）...")
        ic_results, _ = load_ic_results(factor_list, config.ic_result_dir, config.return_period, logger)

    # Step 9: 计算综合因子
    short_sample_factors = None
    dimension_weight_method = None
    composite_file = config.output_dir / f"composite_{best_method}_{config.return_period}.json"
    if composite_file.exists():
        try:
            with open(composite_file, encoding="utf-8") as f:
                composite_data_for_ss = json.load(f)
            short_sample_factors = (
                composite_data_for_ss.get("meta", {}).get("selection_result", {}).get("short_sample_factors")
            )
            if short_sample_factors:
                logger.info(
                    "短样本因子ICIR权重惩罚: %s",
                    {k: f"×{v}/30={v / 30:.2f}" for k, v in short_sample_factors.items()},
                )
            dimension_weight_method = (
                composite_data_for_ss.get("meta", {}).get("weight_meta", {}).get("dimension_weight_method")
            )
            if dimension_weight_method:
                logger.info("维度权重方法: %s", dimension_weight_method)
        except (json.JSONDecodeError, KeyError):
            logger.warning("无法从 composite 结果读取 short_sample_factors，跳过惩罚")

    # R3: filter 角色硬过滤 (在 composite 计算之前, 避免基本面恶化股污染权重)
    factor_df, filter_exclusions = apply_filter_role_factors(factor_df, logger)

    logger.info("计算综合因子（权重方法: %s）...", best_method)
    weight_engine = WeightEngine(
        weight_method=best_method,
        window=config.rolling_window,
        logger=logger,
        dimension_weight_method=dimension_weight_method,
        factor_categories=FACTOR_CATEGORIES if dimension_weight_method else None,
    )
    composite_factor = weight_engine.calculate(factor_df, factor_cols, ic_results, ic_daily_data, short_sample_factors)

    # 获取权重用于覆盖率过滤
    selection_weights = None
    if composite_file.exists():
        try:
            with open(composite_file, encoding="utf-8") as f:
                composite_data_for_weights = json.load(f)
            selection_weights = composite_data_for_weights.get("meta", {}).get("weights")
            if not selection_weights:
                wm = composite_data_for_weights.get("meta", {}).get("weight_meta", {})
                selection_weights = wm.get("last_day_weights")
        except (json.JSONDecodeError, KeyError):
            logger.warning("无法从 composite 结果读取权重，跳过覆盖率过滤")

    # v1.13: 映射权重键名：因子名 → 列名
    if selection_weights and factor_list and factor_cols:
        name_to_col = dict(zip(factor_list, factor_cols))
        selection_weights = {name_to_col.get(k, k): v for k, v in selection_weights.items()}

    return (
        composite_factor,
        selection_weights,
        dimension_weight_method,
        short_sample_factors,
        factor_df,
        filter_exclusions,
    )


def _run_selection_pipeline(
    composite_factor: pd.Series,
    factor_df: pd.DataFrame,
    config: StockSelectorConfig,
    best_method: str,
    selection_date: str,
    selection_weights: dict[str, float] | None,
    factor_cols: list[str],
    logger: logging.Logger,
) -> tuple[
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
    int,
    int,
    int,
    int,
    int,
    list[dict[str, Any]],
]:
    """Step 10: Stage 1 候选池 + Bottom90 + LR 过滤.

    Returns:
        (top_stocks, stage1_top_snapshot, stage2_top_snapshot,
         stage1_bottom_snapshot,
         excluded_by_amplitude, excluded_by_coverage, excluded_by_liquidity,
         excluded_by_confirmation, excluded_by_overheat,
         secondary_sorted_stocks)
    """
    # Stage 1: composite Top stage1_pool_size (候选池, 保留基础设施)
    stage1_n = config.stage1_pool_size
    logger.info("Stage 1: composite Top %d (候选池)", stage1_n)
    stage1_stocks, excluded_by_amplitude, excluded_by_coverage, excluded_by_liquidity = sort_and_select(
        composite_factor,
        factor_df,
        stage1_n,
        config.factor_direction,
        factor_cols=factor_cols,
        weights=selection_weights,
        min_amplitude=config.min_amplitude,
        enable_liquidity_filter=config.enable_liquidity_filter,
        min_amount_percentile=config.min_amount_percentile,
        logger=logger,
    )

    # v3.15: 小股票池二次排序（换手率 + 市值）
    secondary_sorted_stocks = apply_secondary_sort(
        stage1_stocks,
        factor_df,
        config,
        selection_date,
        logger=logger,
    )

    stage1_top_snapshot = [copy.deepcopy(s) for s in secondary_sorted_stocks[: config.top_n]]

    stage2_top_snapshot: list[dict[str, Any]] = []  # v3.9: 不再使用, 保留为空
    stage1_bottom_snapshot: list[dict[str, Any]] = []
    excluded_by_confirmation = 0  # v3.9: 企稳过滤废弃, 恒为 0
    excluded_by_overheat = 0  # v3.9: 过热过滤排除数

    # v3.10: Bottom90 候选池
    valid_cf = composite_factor.dropna()
    if len(valid_cf) > 0:
        bottom_candidates = valid_cf.nsmallest(config.lr_bottom_pool_size)
        full_ranked = valid_cf.sort_values(ascending=False)
        rank_map = {idx: i + 1 for i, idx in enumerate(full_ranked.index)}
        bottom_pool = [
            {
                "rank": rank_map[idx],
                "code": factor_df.loc[idx, "asset"],
                "composite_value": convert_to_native_types(val),
            }
            for idx, val in bottom_candidates.items()
        ]
        stage1_bottom_snapshot = [copy.deepcopy(s) for s in bottom_pool[: config.top_n]]

        # v3.10: LR 数据驱动过滤
        if config.enable_overheat_filter:
            from paths import LR_TRAINING_DATA_DIR

            lr_model, lr_scaler, lr_features, lr_auc = calibrate_lr_filter(
                LR_TRAINING_DATA_DIR,
                weight_method=best_method,
                top_n=config.top_n,
                n_features=config.lr_top_features,
                train_window=config.lr_train_window,
                min_oos_auc=config.lr_min_oos_auc,
                min_training_days=config.lr_min_training_days,
                filter_quantile=config.lr_filter_quantile,
                logger=logger,
            )
            if lr_model is not None:
                assert lr_scaler is not None  # noqa: S101  # 模型存在则 scaler 必存在
                logger.info(
                    "Bottom90 LR 打分 (v3.13) | %d 特征, OOS AUC=%.3f, 全部输出不截断",
                    len(lr_features),
                    lr_auc,
                )
                top_stocks, excluded_by_overheat = apply_lr_filter(
                    bottom_pool,
                    config.data_source,
                    selection_date,
                    config.top_n,
                    lr_model,
                    lr_scaler,
                    lr_features,
                    config.lr_filter_quantile,
                    logger=logger,
                )
            else:
                logger.warning("LR 打分: 模型不可用 (OOS AUC 不足或数据缺失), 返回原始排序")
                top_stocks = bottom_pool
        else:
            top_stocks = bottom_pool
    else:
        top_stocks = []

    return (
        top_stocks,
        stage1_top_snapshot,
        stage2_top_snapshot,
        stage1_bottom_snapshot,
        excluded_by_amplitude,
        excluded_by_coverage,
        excluded_by_liquidity,
        excluded_by_confirmation,
        excluded_by_overheat,
        secondary_sorted_stocks,
    )


def _build_and_write_outputs(
    top_stocks: list[dict[str, Any]],
    factor_df: pd.DataFrame,
    config: StockSelectorConfig,
    weight_config: dict[str, Any],
    selection_date: str,
    stocks_on_date: int,
    factor_list: list[str],
    factor_cols: list[str],
    direction_map: dict[str, str],
    flipped_factors: list[str],
    stage1_top_snapshot: list[dict[str, Any]],
    stage2_top_snapshot: list[dict[str, Any]],
    stage1_bottom_snapshot: list[dict[str, Any]],
    excluded_by_amplitude: int,
    excluded_by_coverage: int,
    excluded_by_liquidity: int,
    excluded_by_confirmation: int,
    excluded_by_overheat: int,
    filter_exclusions: dict[str, int],
    logger: logging.Logger,
    secondary_sorted_stocks: list[dict[str, Any]] | None = None,
) -> tuple[dict[str, Any], Path]:
    """Step 10.6-13: 决策卡片 + 结果构建 + Parquet 写入 + LR 训练数据保存.

    Returns:
        (result_dict, partition_dir)
    """
    # Step 10.6: 决策卡片 (v2.43)
    card_aux_cols = [
        "amplitude",
        "close",
        "high",
        "low",
        "return_5d",
        "turnover_rate",
        "volume_ratio_5",
        "near_high_ratio_5",
        "bollinger_pb",
        "rsi_6",
        "volume",  # for amount = close * volume
    ]
    missing_aux = [c for c in card_aux_cols if c not in factor_df.columns]
    factor_df_for_cards = factor_df
    if missing_aux:
        logger.info("decision_card: 加载辅助列 %s", missing_aux)
        try:
            aux_df_raw = load_factor_values(missing_aux, config.data_source, logger)
            aux_df = cast(pd.DataFrame, aux_df_raw)
            if "date" in aux_df.columns:
                aux_df = aux_df[aux_df["date"] == selection_date].copy()
            merge_cols = ["asset"] + [c for c in missing_aux if c in aux_df.columns]
            factor_df_for_cards = factor_df.merge(cast(pd.DataFrame, aux_df[merge_cols]), on="asset", how="left")
        except (FileNotFoundError, KeyError, ValueError) as e:
            logger.warning("decision_card: 辅助列加载失败 (%s), 部分字段将为 n/a", e)
    # 派生 amount = close × volume (parquet 无 amount 列, 用成交额代理)
    if "close" in factor_df_for_cards.columns and "volume" in factor_df_for_cards.columns:
        factor_df_for_cards = factor_df_for_cards.assign(
            amount=factor_df_for_cards["close"] * factor_df_for_cards["volume"]
        )
    top_stocks = build_decision_cards(top_stocks, factor_df_for_cards, logger=logger)

    # Step 11: 构建结果
    result = build_result(
        top_stocks,
        config,
        weight_config,
        stocks_on_date,
        factor_list,
        factor_cols,
        selection_date,
        direction_map=direction_map,
        flipped_factors=flipped_factors,
        excluded_by_amplitude=excluded_by_amplitude,
        excluded_by_coverage=excluded_by_coverage,
        excluded_by_liquidity=excluded_by_liquidity,
        excluded_by_confirmation=excluded_by_confirmation,
        excluded_by_overheat=excluded_by_overheat,
        excluded_by_filter=filter_exclusions,
        secondary_sorted_stocks=secondary_sorted_stocks,
        logger=logger,
    )

    # Step 12: 写入 Parquet 选股历史
    exclusion_stats = {
        "excluded_by_amplitude": excluded_by_amplitude,
        "excluded_by_coverage": excluded_by_coverage,
        "excluded_by_liquidity": excluded_by_liquidity,
        "excluded_by_confirmation": excluded_by_confirmation,
        "excluded_by_overheat": excluded_by_overheat,
        "excluded_by_filter": filter_exclusions,
        "min_weight_coverage": 0.5,
        # v3.15: 二次排序配置 (写入 Parquet metadata, 供报告读取)
        "secondary_sort_enabled": config.enable_secondary_sort,
        "secondary_sort_pool_threshold": config.secondary_sort_pool_threshold,
        "secondary_sort_factor_weights": config.secondary_sort_factor_weights,
        "secondary_sort_flip_factors": config.secondary_sort_flip_factors,
    }
    partition_dir = write_selection_history(
        stage1_top=stage1_top_snapshot,
        stage2_top=stage2_top_snapshot,
        stage3_top=top_stocks,
        config=config,
        weight_config=weight_config,
        selection_date=selection_date,
        stocks_on_date=stocks_on_date,
        factor_list=factor_list,
        factor_cols=factor_cols,
        direction_map=direction_map,
        flipped_factors=flipped_factors,
        exclusion_stats=exclusion_stats,
        output_dir=config.output_dir,
        stage1_bottom=stage1_bottom_snapshot,
        logger=logger,
    )

    # Step 13: v3.11 保存四种权重方式的 LR 训练数据
    for train_method in ALL_WEIGHT_METHODS:
        composite_file_m = config.output_dir / f"composite_{train_method}_{config.return_period}.json"
        if not composite_file_m.exists():
            logger.warning("[v3.11] 跳过 %s: composite 文件不存在", train_method)
            continue

        try:
            with open(composite_file_m, encoding="utf-8") as f:
                composite_data_m = json.load(f)
        except json.JSONDecodeError as e:
            logger.warning("[v3.11] %s: composite JSON 解析失败: %s", train_method, e)
            continue

        result_m = _compute_composite_for_method(
            method=train_method,
            factor_df_orig=factor_df,
            composite_data=composite_data_m,
            config=config,
            logger=logger,
        )
        if result_m is None:
            continue

        composite_factor_m, _, _ = result_m
        valid_cf_m = composite_factor_m.dropna()
        if len(valid_cf_m) == 0:
            logger.warning("[v3.11] %s: composite_factor 全 NaN, 跳过", train_method)
            continue

        bottom_candidates_m = valid_cf_m.nsmallest(config.lr_bottom_pool_size)
        full_ranked_m = valid_cf_m.sort_values(ascending=False)
        rank_map_m = {idx: i + 1 for i, idx in enumerate(full_ranked_m.index)}
        bottom_stocks_m = [
            {
                "rank": rank_map_m[idx],
                "code": factor_df.loc[idx, "asset"],
                "composite_value": convert_to_native_types(val),
            }
            for idx, val in bottom_candidates_m.items()
        ]

        save_lr_training_data(
            bottom_stocks=bottom_stocks_m[: config.lr_bottom_pool_size],
            factor_df=factor_df,
            weight_config=composite_data_m,
            config=config,
            selection_date=selection_date,
            logger=logger,
        )

    return result, partition_dir


def select_stocks(
    config: StockSelectorConfig,
    logger: logging.Logger | None = None,
) -> tuple[dict[str, Any], Path]:
    """股票选股主函数

    流程:
    1. 加载最优权重配置
    2. 加载因子数据
    3. 确定选股日期
    4. 过滤数据（只保留选股日期）
    5. 标准化因子
    6. 加载 IC 数据（根据权重方法）
    7. 计算综合因子
    8. 排序选出 Top N
    9. 构建结果
    10. 保存结果

    Args:
        config: 配置对象
        logger: 日志对象（默认使用模块级 _logger）

    Returns:
        Tuple[result_dict, output_path]
            - result_dict: build_result 返回的内存字典（含 meta/top_stocks/weight_config）
            - output_path: write_selection_history 返回的 Parquet 分区目录

    Raises:
        ValueError: 数据异常
        FileNotFoundError: 文件不存在
    """
    if logger is None:
        logger = _logger

    logger.info("股票选股流程启动")
    config.validate()

    # Step 0-3: 加载权重配置 + 因子列表
    weight_config, best_method, factor_list, factor_cols = _load_weight_and_factors(config, logger)

    # Step 4-6: 加载因子数据 + 日期过滤
    factor_df, selection_date, stocks_on_date = _load_and_filter_factor_data(config, factor_cols, logger)

    # Step 7-7.5: 标准化 + 方向统一化
    factor_df, direction_map, flipped_factors = _standardize_and_align_direction(
        factor_df, factor_list, factor_cols, weight_config, best_method, config, logger
    )

    # Step 8-9: IC 数据 + 综合因子计算
    composite_factor, selection_weights, _, _, factor_df, filter_exclusions = _compute_composite_factor(
        factor_df, factor_list, factor_cols, best_method, config, logger
    )

    # Step 10: 排序选股 + LR 过滤
    (
        top_stocks,
        stage1_top_snapshot,
        stage2_top_snapshot,
        stage1_bottom_snapshot,
        excluded_by_amplitude,
        excluded_by_coverage,
        excluded_by_liquidity,
        excluded_by_confirmation,
        excluded_by_overheat,
        secondary_sorted_stocks,
    ) = _run_selection_pipeline(
        composite_factor,
        factor_df,
        config,
        best_method,
        selection_date,
        selection_weights,
        factor_cols,
        logger,
    )

    # Step 10.6-13: 决策卡片 + 结果构建 + Parquet 写入 + LR 训练数据保存
    result, partition_dir = _build_and_write_outputs(
        top_stocks,
        factor_df,
        config,
        weight_config,
        selection_date,
        stocks_on_date,
        factor_list,
        factor_cols,
        direction_map,
        flipped_factors,
        stage1_top_snapshot,
        stage2_top_snapshot,
        stage1_bottom_snapshot,
        excluded_by_amplitude,
        excluded_by_coverage,
        excluded_by_liquidity,
        excluded_by_confirmation,
        excluded_by_overheat,
        filter_exclusions,
        logger,
        secondary_sorted_stocks=secondary_sorted_stocks,
    )

    return result, partition_dir


# ============================================================================
# CLI 入口
# ============================================================================


def create_cli_entrypoint(config_class: type[StockSelectorConfig]) -> Callable[[], int]:
    """创建 CLI 入口（遵循 MODULE.md M41-45）

    遵循规范:
    - 退出码：成功 0，失败 1
    - 异常处理：保留堆栈信息
    - logger 传递：公共函数接收 logger 参数
    - 最小导入：CLI 入口只导入必需模块

    Args:
        config_class: 配置类

    Returns:
        CLI 入口函数
    """
    import argparse

    def main() -> int:
        """CLI 主函数"""
        logger = _logger

        parser = argparse.ArgumentParser(description="股票选股脚本 - 使用最优权重方法计算综合因子并选出 Top N 股票")

        # 选股参数
        parser.add_argument(
            "--top_n",
            type=int,
            default=30,  # v2.42: 短名单扩展, 与 StockSelectorConfig.top_n 同步
            help="选出前 N 只股票（默认: 30，短名单, designs/feat_shortlist_top30_v1.md）",
        )

        parser.add_argument(
            "--selection_date",
            type=str,
            default=None,
            help="选股日期（YYYY-MM-DD，默认取最新日期）",
        )

        parser.add_argument(
            "--factor_direction",
            type=str,
            choices=["positive", "negative"],
            default="positive",
            help="因子方向（v2.47: 默认 positive，对齐到正向语义，值大=好）",
        )

        parser.add_argument(
            "--rolling_window",
            type=int,
            default=60,
            help="滚动 ICIR 窗口（默认: 60）",
        )

        # 问题 9 修复：添加 --return_period 参数
        parser.add_argument(
            "--return_period",
            type=str,
            default="1d",
            help="收益周期（默认: 1d）",
        )

        # v1.12: 新增 --min_amplitude 参数（排除不可交易的一字板涨停股）
        parser.add_argument(
            "--min_amplitude",
            type=float,
            default=0.01,
            help="最低振幅阈值（默认: 0.01=1%%，排除不可交易的一字板涨停股）",
        )

        # 数据路径
        parser.add_argument(
            "--data_source",
            type=str,
            default=None,
            help="统一数据源路径（默认: data_fetchers/result/factor_ic_data.json.gz）",
        )

        parser.add_argument(
            "--ic_result_dir",
            type=str,
            default=None,
            help="IC 结果目录（默认: factor_ic/result）",
        )

        parser.add_argument(
            "--weight_result_path",
            type=str,
            default=None,
            help="权重选择结果路径（默认: comprehensive_factor/result/weight_selection_result.json）",
        )

        parser.add_argument(
            "--output_dir",
            type=str,
            default=None,
            help="输出目录（默认: comprehensive_factor/result）",
        )

        args = parser.parse_args()

        # 构建配置（问题 1 修复：过滤 None 参数，让 default_factory 生效）
        candidate_kwargs = {
            "top_n": args.top_n,
            "selection_date": args.selection_date,
            "factor_direction": args.factor_direction,
            "rolling_window": args.rolling_window,
            "return_period": args.return_period,
            "min_amplitude": args.min_amplitude,  # v1.12: 振幅阈值
            "data_source": args.data_source,
            "ic_result_dir": args.ic_result_dir,
            "weight_result_path": args.weight_result_path,
            "output_dir": args.output_dir,
        }
        # 过滤 None，让 default_factory 在省略参数时生效
        kwargs = {k: v for k, v in candidate_kwargs.items() if v is not None}
        config = config_class(**kwargs)

        # 执行选股
        try:
            result, output_path = select_stocks(config, logger)
            logger.info("选股成功！输出路径: %s", output_path)
            return 0
        except Exception:
            logger.exception("选股失败")
            return 1

    return main


# 创建 CLI 入口
main = create_cli_entrypoint(StockSelectorConfig)


if __name__ == "__main__":
    exit_code = main()
    sys.exit(exit_code)
