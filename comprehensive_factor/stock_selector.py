"""
股票选股脚本

功能:
1. 加载最优权重配置（从 weight_selection_result.json）
2. 加载因子数据（从 factor_ic_data.json.gz）
3. 使用最优权重方法计算综合因子值
4. 排序选出 Top N 股票

流程:
Step 1-5: 单因子分析 → 因子筛选 → 标准化 → 加权计算 → 分层回测
Step 6: 权重方式选择 (weight_selector.py)
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

作者: 云瑶
创建日期: 2026-06-03
"""

import copy
import json
import logging
import os
import sys
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, cast

import numpy as np
import pandas as pd


# sys.path 处理（遵循 MODULE.md M49）
PROJECT_ROOT = Path(__file__).parent.parent.resolve()
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))  # noqa: E402

# 导入公共模块（遵循 MODULE.md M2）
from comprehensive_factor.common.convert_types import convert_to_native_types  # noqa: E402
from comprehensive_factor.common.factor_loader import (  # noqa: E402
    load_factor_values,
    load_ic_daily,
    load_ic_results,
    standardize_factors,
)
from comprehensive_factor.common.logger_config import get_logger  # noqa: E402
from comprehensive_factor.common.weight_engine import WeightEngine  # noqa: E402
from comprehensive_factor.decision_card import build_decision_cards  # noqa: E402
from factor_definitions import FACTOR_CATEGORIES, FACTOR_COL_TO_NAME_MAP  # noqa: E402


# ============================================================================
# 模块级常量
# ============================================================================

# 版本号（遵循 PROJECT.md 规范）
__version__ = "3.7"

# logger 实例（遵循 PROJECT.md 第380-500行日志规范）
_logger = get_logger(__name__)


# ============================================================================
# 配置类
# ============================================================================

DEFAULT_DATA_SOURCE = PROJECT_ROOT / "data_fetchers" / "result" / "factor_ic_data.parquet"
DEFAULT_IC_RESULT_DIR = PROJECT_ROOT / "factor_ic" / "result"
DEFAULT_WEIGHT_RESULT_PATH = PROJECT_ROOT / "comprehensive_factor" / "result" / "weight_selection_result.json"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "comprehensive_factor" / "result"

# 默认因子列表（fallback，优先从 composite 结果读取）
DEFAULT_FACTOR_LIST: list[str] = []

DEFAULT_FACTOR_COLS: list[str] = []


@dataclass
class StockSelectorConfig:
    """股票选股配置

    遵循 MODULE.md M46-48 规范：
    - 继承公共配置模式
    - 单一数据源

    Note:
        - factor_direction 固定为 'positive'（v2.47: 综合因子对齐到正向语义）
        - 参考 MODULE.md M56 v2.47: 综合因子高值预期高收益
    """

    # 问题 2 修复：删除 factor_list/factor_cols 字段
    # 运行时从 composite 结果读取，是 dead config

    # === 选股参数 ===
    # v2.42: 短名单扩展 10 → 30
    # 设计依据: designs/feat_shortlist_top30_v1.md §1.2
    # 第一性原理: √N 降噪 (N=10→30 降噪 1.73x), 退出极端尾部 (0.36% → 1.1%)
    # 战略目标 (AGENTS.md): Layer 1 (549) → 短名单 30~50 → 人工决断 3~5
    top_n: int = 30  # v2.42: 短名单扩展, 从 10 改为 30
    factor_direction: str = "positive"  # v2.47: 综合因子方向（对齐到正向语义，值大=好）
    rolling_window: int = 60  # 滚动 ICIR 窗口
    min_amplitude: float = 0.01  # 最低振幅阈值（排除不可交易的一字板涨停股，振幅<1%无法买入）
    # v2.40: 流动性过滤参数（design.md feat_family_weight_cap_and_liquidity_filter §3.3）
    enable_liquidity_filter: bool = False  # v2.41 (R1): 默认关闭——已前置到 factor_generator (_mark_low_liquidity)
    min_amount_percentile: float = 0.05  # 截面分位（默认 5%，自适应每日成交额分布）

    # v2.44: 两阶段选股 (designs/feat_two_stage_stock_selector_v244.md)
    # Stage 1: composite 取 Top stage1_pool_size (alpha 仍有效的子池)
    # Stage 2/3: v3.9 废弃——不再对 Top30 做 Stage 2 turnover 重排 + Stage 3 企稳过滤
    #   原因: 企稳信号在 Layer 5 内部方向反了 (有企稳→T+1 更低), 见 designs/feat_bottom30_overheat_filter.md
    enable_two_stage: bool = True  # v3.9: Stage 1 候选池逻辑保留
    stage1_pool_size: int = 200  # OOS 最优 (vs Top60 +2.31pp, vs Top300 优于 +10pp)
    stage2_sort_col: str = "turnover_rate"  # 保留字段, v3.9 不再调用 apply_stage2_resort
    stage2_ascending: bool = True  # 保留字段, v3.9 不再使用

    # v3.9: Bottom30 过热过滤 (designs/feat_bottom30_overheat_filter.md)
    # v3.9.1: 彻底数据驱动——每次运行时用全历史数据校准最优分位阈值
    #   校准逻辑: 扫描 turnover_percentile × volume_ratio_percentile 网格,
    #   在 Bottom30 历史样本上找 T+1 差异最大且 p<0.05 的组合.
    enable_overheat_filter: bool = True
    overheat_calibrate_min_pvalue: float = 0.05  # 统计显著性门槛
    overheat_calibrate_grid: tuple[float, ...] = (0.5, 0.6, 0.7, 0.8, 0.9)  # 分位搜索网格
    # v3.9 校准结果 (运行时填充, 非硬编码)
    overheat_turnover_percentile: float = 0.7  # fallback: 校准失败时用
    overheat_volume_ratio_percentile: float = 0.7  # v3.9.1: 从固定 1.5 改为截面分位

    # === 数据路径 ===（问题 4 修复：default_factory 保证延迟求值）
    data_source: Path = field(default_factory=lambda: DEFAULT_DATA_SOURCE)
    ic_result_dir: Path = field(default_factory=lambda: DEFAULT_IC_RESULT_DIR)
    weight_result_path: Path = field(default_factory=lambda: DEFAULT_WEIGHT_RESULT_PATH)
    output_dir: Path = field(default_factory=lambda: DEFAULT_OUTPUT_DIR)

    # === 时间参数 ===
    selection_date: str | None = None  # 选股日期（默认取最新日期）

    # === 其他 ===
    return_period: str = "1d"  # 收益周期

    # 问题 2 修复：删除空 __post_init__，dataclass 不需要

    def validate(self) -> None:
        """校验配置完整性（遵循 MODULE.md H 规则）

        Note:
            - factor_list/factor_cols 是运行时变量（从 composite 结果读取）
            - 问题 6 修复：移除必填检查，由 select_stocks 显式校验
        """
        # factor_list/factor_cols 移除必填检查（运行时填充）
        if self.top_n <= 0:
            raise ValueError(f"top_n 必须大于 0，当前: {self.top_n}")

        if self.factor_direction not in ("positive", "negative"):
            raise ValueError(f"factor_direction 必须为 'positive' 或 'negative'，当前: {self.factor_direction}")

        # v2.44: Stage 1 候选池校验 (v3.9: Stage 2/3 废弃, 仅保留 Stage 1)
        if self.enable_two_stage and self.stage1_pool_size <= self.top_n * 2:
            raise ValueError(
                f"stage1_pool_size ({self.stage1_pool_size}) 必须 > top_n*2 ({self.top_n * 2})，否则候选池过小"
            )

        # v3.9: 过热过滤参数校验
        if self.enable_overheat_filter:
            if not 0 < self.overheat_calibrate_min_pvalue < 1:
                raise ValueError(
                    f"overheat_calibrate_min_pvalue 必须在 (0, 1) 区间, 当前: {self.overheat_calibrate_min_pvalue}"
                )
            if not self.overheat_calibrate_grid:
                raise ValueError("overheat_calibrate_grid 不能为空")
            if not all(0 < p < 1 for p in self.overheat_calibrate_grid):
                raise ValueError(
                    f"overheat_calibrate_grid 所有值必须在 (0, 1) 区间, 当前: {self.overheat_calibrate_grid}"
                )


# ============================================================================
# 核心函数
# ============================================================================

# 浮点精度容差（遵循 MODULE.md M54）
EPSILON = 1e-10


def load_weight_config(
    weight_result_path: Path | str,
    logger: logging.Logger | None = None,
) -> dict[str, Any]:
    """加载权重选择结果

    Args:
        weight_result_path: 权重选择结果文件路径（Path 或 str）
        logger: 日志对象（默认使用模块级 _logger）

    Returns:
        权重配置字典，结构：
        {
            "best_selection": {"method": str, "composite_score": float, ...},
            ...
        }

    Raises:
        FileNotFoundError: 权重配置文件不存在
        ValueError: JSON 结构不完整
    """
    if logger is None:
        logger = _logger

    weight_result_path = Path(weight_result_path)

    if not weight_result_path.exists():
        raise FileNotFoundError(
            f"权重选择结果文件不存在: {weight_result_path}\n请先运行 weight_selector.py 生成最优权重配置"
        )

    logger.info("加载权重选择结果: %s", weight_result_path)

    try:
        with open(weight_result_path, encoding="utf-8") as f:
            weight_config = json.load(f)
    except json.JSONDecodeError as e:
        raise ValueError(f"权重配置文件 JSON 解析失败: {weight_result_path}\n错误位置: {e.pos}") from e

    # 校验必需字段
    required_fields = ["best_selection"]
    for field_name in required_fields:
        if field_name not in weight_config:
            raise ValueError(f"权重配置文件缺失必需字段 '{field_name}'\n当前字段: {list(weight_config.keys())}")

    # 校验 best_selection 结构
    best_selection = weight_config["best_selection"]
    if "method" not in best_selection:
        raise ValueError(f"best_selection 缺失 'method' 字段\n当前字段: {list(best_selection.keys())}")

    # 问题 4 修复：composite_score 纳入 required_fields，走严格契约
    if "composite_score" not in best_selection:
        raise ValueError(f"best_selection 缺失 'composite_score' 字段\n当前字段: {list(best_selection.keys())}")

    logger.info(
        "最优权重方法: %s，综合得分: %.4f",
        best_selection["method"],
        best_selection["composite_score"],
    )

    return weight_config


def load_selected_factors_from_composite(
    weight_config: dict[str, Any],
    output_dir: Path | str,
    return_period: str = "1d",
    logger: logging.Logger | None = None,
) -> tuple[list[str], list[str]]:
    """从最优权重方法的 composite 结果中读取选中的因子列表

    Args:
        weight_config: 权重配置字典（含 best_selection.method）
        output_dir: composite 结果目录（Path 或 str）
        return_period: 收益周期（默认 1d）
        logger: 日志对象（默认使用模块级 _logger）

    Returns:
        Tuple[factor_list, factor_cols] 选中的因子列表和列名

    Raises:
        FileNotFoundError: composite 结果文件不存在
        ValueError: JSON 结构不完整

    Note:
        - 遵循数据层架构原则：因子筛选结果由 comprehensive_factor 模块决定
        - stock_selector 只读取筛选结果，不做独立的因子选择
    """
    if logger is None:
        logger = _logger

    output_dir = Path(output_dir)
    best_method = weight_config["best_selection"]["method"]

    # 构建 composite 结果文件名
    # 文件名格式: composite_{method}_{return_period}.json
    # 注意：method 已包含 "_weight" 后缀，如 "icir_weight"
    composite_file = output_dir / f"composite_{best_method}_{return_period}.json"

    if not composite_file.exists():
        raise FileNotFoundError(
            f"最优权重方法的 composite 结果不存在: {composite_file}\n"
            f"请先运行 comprehensive_factor 脚本（Stage 4）生成筛选结果"
        )

    logger.info("加载最优权重 composite 结果: %s", composite_file)

    try:
        with open(composite_file, encoding="utf-8") as f:
            composite_result = json.load(f)
    except json.JSONDecodeError as e:
        raise ValueError(f"composite 结果 JSON 解析失败: {composite_file}\n错误位置: {e.pos}") from e

    # 提取因子列表
    meta = composite_result.get("meta", {})
    factor_list = meta.get("factor_list", [])
    factor_cols = meta.get("factor_cols", [])

    if not factor_list or not factor_cols:
        raise ValueError(
            f"composite 结果缺失因子列表\nmeta.factor_list: {factor_list}\nmeta.factor_cols: {factor_cols}"
        )

    logger.info("选中因子: %s → 列名: %s", factor_list, factor_cols)

    return factor_list, factor_cols


def get_latest_date(factor_df: pd.DataFrame, logger: logging.Logger | None = None) -> str:
    """获取最新日期

    Args:
        factor_df: 因子 DataFrame（包含 date 列）
        logger: 日志对象（默认使用模块级 _logger）

    Returns:
        最新日期字符串（YYYY-MM-DD 格式）

    Raises:
        ValueError: date 列为空或数据为空
    """
    if logger is None:
        logger = _logger

    if len(factor_df) == 0:
        raise ValueError("factor_df 为空，无法获取最新日期")

    if "date" not in factor_df.columns:
        raise ValueError(f"factor_df 缺少 'date' 列，当前列: {list(factor_df.columns)}")

    # 获取唯一日期并排序
    dates = factor_df["date"].unique()
    dates_sorted = sorted(dates)
    latest_date = dates_sorted[-1]

    # 问题 2 修复：显式控制输出格式为 YYYY-MM-DD
    # 避免 Timestamp 输出 "2024-01-15 00:00:00" 带时间
    # 问题 3 修复：删除函数内重复 import（文件顶部已导入）
    latest_date_str = pd.Timestamp(latest_date).strftime("%Y-%m-%d")

    logger.info("数据最新日期: %s（共 %d 个日期）", latest_date_str, len(dates_sorted))

    return latest_date_str


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


def calibrate_overheat_thresholds(
    factor_df: pd.DataFrame,
    composite_factor: pd.Series,
    top_n: int,
    grid: tuple[float, ...],
    min_pvalue: float,
    logger: logging.Logger | None = None,
) -> tuple[float, float]:
    """v3.9.1: 每次运行时用全历史数据校准过热过滤最优分位阈值.

    在全历史 Bottom30 样本上, 扫描 turnover_percentile × volume_ratio_percentile 网格,
    对每组阈值将 Bottom30 分为"过热/未过热"两组, 计算 T+1 均值差异和 Welch t 检验 p 值.
    选择 |T+1 差异| 最大且 p < min_pvalue 的组合.

    Args:
        factor_df: 全样本 DataFrame (含 date, asset, turnover_rate, volume_ratio_5, forward_return_1d).
        composite_factor: 综合因子值 Series (索引与 factor_df 对齐).
        top_n: Bottom N (与选股逻辑一致, 默认 30).
        grid: 分位搜索网格, 如 (0.5, 0.6, 0.7, 0.8, 0.9).
        min_pvalue: 统计显著性门槛 (默认 0.05).
        logger: 日志对象.

    Returns:
        (turnover_percentile, volume_ratio_percentile) 最优分位组合.
        如果无组合通过 p 值门槛, 返回 (0.7, 0.7) fallback.
    """
    if logger is None:
        logger = _logger

    from scipy import stats as sp_stats

    required = {"date", "asset", "turnover_rate", "volume_ratio_5", "forward_return_1d"}
    missing = required - set(factor_df.columns)
    if missing:
        logger.warning("过热校准: 缺少列 %s, 使用 fallback 阈值 (0.7, 0.7)", missing)
        return 0.7, 0.7

    # 全历史 Bottom30 样本
    df = factor_df.copy()
    df["composite"] = composite_factor.reindex(df.index)
    df = df.dropna(subset=["composite", "turnover_rate", "volume_ratio_5", "forward_return_1d"])

    # 每日截面: composite 升序取最低 top_n 只 (Bottom30, 强势股端)
    bottom_samples = []
    for _date, group in df.groupby("date"):
        if len(group) >= top_n:
            bottom = group.nsmallest(top_n, "composite")
            bottom_samples.append(bottom)

    if not bottom_samples:
        logger.warning("过热校准: 无有效 Bottom30 历史样本, 使用 fallback 阈值 (0.7, 0.7)")
        return 0.7, 0.7

    bottom_df = pd.concat(bottom_samples, ignore_index=True)
    total_samples = len(bottom_df)
    logger.info("过热校准: %d 天 Bottom30 样本, %d 条记录", len(bottom_samples), total_samples)

    best_diff = 0.0
    best_p = 1.0
    best_combo = (0.7, 0.7)

    for t_pct in grid:
        for v_pct in grid:
            # 每日截面分位阈值
            t_thresholds = bottom_df.groupby("date")["turnover_rate"].quantile(t_pct)
            v_thresholds = bottom_df.groupby("date")["volume_ratio_5"].quantile(v_pct)

            # 合并回 bottom_df
            t_map = t_thresholds.to_dict()
            v_map = v_thresholds.to_dict()
            t_thr = bottom_df["date"].map(t_map)
            v_thr = bottom_df["date"].map(v_map)

            overheat_mask = (bottom_df["turnover_rate"] > t_thr) & (bottom_df["volume_ratio_5"] > v_thr)
            overheat_ret = bottom_df.loc[overheat_mask, "forward_return_1d"]
            normal_ret = bottom_df.loc[~overheat_mask, "forward_return_1d"]

            n_oh = len(overheat_ret)
            n_norm = len(normal_ret)
            if n_oh < 10 or n_norm < 10:
                continue

            diff = float(normal_ret.mean() - overheat_ret.mean())
            if diff <= 0:
                continue  # 只看"过热→T+1 更低"的方向

            t_stat, p_value = sp_stats.ttest_ind(normal_ret, overheat_ret, equal_var=False)

            if p_value < min_pvalue and diff > best_diff:
                best_diff = diff
                best_p = p_value
                best_combo = (t_pct, v_pct)

    if best_diff > 0:
        logger.info(
            "过热校准: 最优 turnover=%.0f%% volume_ratio=%.0f%%, T+1 差异=%.4f%%/天, p=%.2e, 过热N=%d, 未过热N=%d",
            best_combo[0] * 100,
            best_combo[1] * 100,
            best_diff * 100,
            best_p,
            n_oh,
            n_norm,
        )
    else:
        logger.warning("过热校准: 无组合通过 p<%.2f 门槛, 使用 fallback (0.7, 0.7)", min_pvalue)

    return best_combo


def apply_overheat_filter(
    bottom_stocks: list[dict[str, Any]],
    factor_df: pd.DataFrame,
    top_n: int,
    turnover_percentile: float = 0.7,
    volume_ratio_percentile: float = 0.7,
    logger: logging.Logger | None = None,
) -> tuple[list[dict[str, Any]], int]:
    """Bottom30 过热过滤 (v3.9.1, designs/feat_bottom30_overheat_filter.md)

    在 Bottom30（强势股, composite 最低端）中排除"过热"股票。
    过热 = 高换手率(截面分位) AND 放量(volume_ratio_5 截面分位)。
    被排除的股票从 Bottom31+ 递补, 保持 top_n 数量。

    v3.9.1: 两个阈值都改为截面分位 (由 calibrate_overheat_thresholds 校准),
    不再使用固定绝对值。

    Args:
        bottom_stocks: composite 升序最低 N 只 (含 code 字段)
        factor_df: 当日因子+行情 DataFrame (含 asset, turnover_rate, volume_ratio_5 列)
        top_n: 最终输出数量
        turnover_percentile: 换手率截面分位阈值 (校准后, 如 0.7)
        volume_ratio_percentile: volume_ratio_5 截面分位阈值 (校准后, 如 0.7)
        logger: 日志对象

    Returns:
        (filtered_stocks, excluded_count)
    """
    if logger is None:
        logger = _logger

    required_cols = ["turnover_rate", "volume_ratio_5"]
    available_cols = [c for c in required_cols if c in factor_df.columns]

    if len(available_cols) < 2:
        logger.info(
            "过热过滤: turnover_rate/volume_ratio_5 不可用 (%s), 跳过过滤",
            available_cols,
        )
        return bottom_stocks[:top_n], 0

    asset_index = factor_df.set_index("asset") if "asset" in factor_df.columns else factor_df

    # v3.9.1: 两个阈值都从当日截面分位动态计算
    turnover_series = factor_df["turnover_rate"].dropna()
    vol_ratio_series = factor_df["volume_ratio_5"].dropna()
    if len(turnover_series) == 0 or len(vol_ratio_series) == 0:
        logger.info("过热过滤: turnover_rate/volume_ratio_5 全部为 NaN, 跳过过滤")
        return bottom_stocks[:top_n], 0

    turnover_threshold = float(turnover_series.quantile(turnover_percentile))
    vol_ratio_threshold = float(vol_ratio_series.quantile(volume_ratio_percentile))
    logger.info(
        "过热过滤: 换手率 %.0f%% 分位阈值=%.4f, volume_ratio_5 %.0f%% 分位阈值=%.4f",
        turnover_percentile * 100,
        turnover_threshold,
        volume_ratio_percentile * 100,
        vol_ratio_threshold,
    )

    filtered: list[dict[str, Any]] = []
    excluded = 0
    for stock in bottom_stocks:
        if len(filtered) >= top_n:
            break

        code = stock["code"]
        row = asset_index.loc[code] if code in asset_index.index else None
        if row is None:
            filtered.append(stock)
            continue

        # 处理同 code 多行边界（理论上单日唯一, 但保险）
        if isinstance(row, pd.DataFrame):
            row = row.iloc[0]

        turnover = float(row.get("turnover_rate", np.nan))
        vol_ratio = float(row.get("volume_ratio_5", np.nan))

        # 数据不可用 → 不过滤
        if pd.isna(turnover) or pd.isna(vol_ratio):
            filtered.append(stock)
            continue

        # v3.9.1: 过热条件——两个截面分位阈值都改为动态计算
        is_overheated = float(turnover) > turnover_threshold and float(vol_ratio) > vol_ratio_threshold

        if is_overheated:
            excluded += 1
            logger.debug(
                "过热过滤排除: %s (换手率=%.4f > %.4f, vol_ratio_5=%.2f > %.4f)",
                code,
                float(turnover),
                turnover_threshold,
                float(vol_ratio),
                vol_ratio_threshold,
            )
        else:
            filtered.append(stock)

    # 不足 top_n 时用被排除的股票递补 (与 apply_stabilization_filter 一致)
    if len(filtered) < top_n:
        filtered_codes = {s["code"] for s in filtered}
        for stock in bottom_stocks:
            if len(filtered) >= top_n:
                break
            if stock["code"] not in filtered_codes:
                stock["overheat_warning"] = True
                filtered.append(stock)

    # 重新编号 rank
    for idx, stock in enumerate(filtered[:top_n], start=1):
        stock["rank"] = idx

    logger.info(
        "过热过滤: 候选 %d → 通过 %d, 排除 %d",
        len(bottom_stocks),
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
        },
        "top_stocks": top_stocks,
        "weight_config": {
            "method": best_selection["method"],
            "window": config.rolling_window if best_selection["method"] == "rolling_icir_weight" else None,
            "factor_list": factor_list,
            "factor_cols": factor_cols,
        },
    }

    logger.info("结果构建完成: 选股日期=%s，Top N=%d", selection_date, len(top_stocks))

    return result


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

    # 问题 10 修复：合并流程启停日志为单条 INFO
    logger.info("股票选股流程启动")

    # 问题 1 修复：调用 validate() 校验配置完整性
    config.validate()

    # Step 1: 加载最优权重配置（优先获取因子列表）
    # 问题 3 修复：__post_init__ 已处理路径默认值，无需运行时校验
    weight_config = load_weight_config(config.weight_result_path, logger)
    best_method = weight_config["best_selection"]["method"]

    # Step 2: 从最优权重 composite 结果中读取选中的因子列表
    # 遵循数据层架构原则：因子筛选结果由 comprehensive_factor 模块决定
    # 问题 3+5 修复：__post_init__ 已处理路径默认值，无需运行时校验
    factor_list, factor_cols = load_selected_factors_from_composite(
        weight_config, config.output_dir, config.return_period, logger
    )

    # Step 3: 校验因子列表（运行时校验）
    if not factor_list or not factor_cols:
        raise ValueError("从 composite 结果读取的因子列表为空")
    if len(factor_list) != len(factor_cols):
        raise ValueError(f"factor_list ({len(factor_list)}) 与 factor_cols ({len(factor_cols)}) 数量不一致")

    # Step 4: 加载因子数据
    # 不可交易股票（涨停类）由 factor_loader 在 load_full_data 阶段过滤
    logger.info("加载因子数据...")
    factor_df_raw = load_factor_values(factor_cols, config.data_source, logger)
    # 类型转换：load_factor_values 返回 DataFrame（pandas DataFrame 构造返回类型不稳定）
    factor_df = cast(pd.DataFrame, factor_df_raw)

    # v2.40: 独立加载流动性列（volume + close），不污染 standardize_factors 工作流
    # 设计依据：composite_runner OOM 修复 — 把 liquidity 与因子标准化解耦
    # stock_selector 阶段 factor_df 已被 selection_date 过滤为单日，merge 成本极低
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
    selection_date = config.selection_date  # 问题 5 修复：用局部变量持有
    if selection_date is None:
        selection_date = get_latest_date(factor_df, logger)

    # Step 6: 过滤数据（只保留选股日期）
    # 问题 1 修复：available_dates 归一化为 str，与 selection_date 同格式比较
    available_dates = sorted({pd.Timestamp(d).strftime("%Y-%m-%d") for d in factor_df["date"].unique()})
    if selection_date not in available_dates:
        raise ValueError(
            f"选股日期 {selection_date} 无数据\n"
            f"可用日期范围: {available_dates[0]} ~ {available_dates[-1]}\n"
            f"共 {len(available_dates)} 个日期"
        )

    logger.info("过滤选股日期: %s", selection_date)
    # 问题 1 修复：合并为一行 mask 过滤，避免引入临时列污染上游对象
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

    # 问题 2 修复：变量名改为 stocks_on_date，避免误解为"全部股票数"
    stocks_on_date = len(factor_df)
    logger.info("选股日期股票数: %d", stocks_on_date)

    # Step 7: 标准化因子（截面标准化）
    # 注意：单日数据标准化时，每日截面就是当日所有股票
    logger.info("标准化因子...")
    factor_df = standardize_factors(factor_df, factor_cols, logger)

    # Step 7.5: 方向统一化（遵循 MODULE.md M56）
    # v2.47: 按 sign(IC) 对齐到正向语义 —— 反向因子 (ic_mean<0) 标准化值取反
    # 与 composite_runner Step 5 保持一致，确保综合因子值与回测时相同
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
        # 加载 IC 结果（静态权重方法需要）
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

    # Step 8: 加载 IC 数据（根据权重方法）
    ic_results = None
    ic_daily_data = None

    if best_method == "rolling_icir_weight":
        # 滚动 ICIR 需要历史 IC 序列
        logger.info("加载 IC 每日序列（滚动 ICIR 需要）...")
        # 问题 3 修复：__post_init__ 已处理路径默认值，无需运行时校验
        ic_daily_data = load_ic_daily(factor_list, config.ic_result_dir, config.return_period, logger)
    elif best_method in ("icir_weight", "ic_weight"):
        # 静态权重需要 IC 统计结果
        logger.info("加载 IC 统计结果（静态权重需要）...")
        # 问题 3 修复：__post_init__ 已处理路径默认值，无需运行时校验
        ic_results, _ = load_ic_results(factor_list, config.ic_result_dir, config.return_period, logger)

    # Step 9: 计算综合因子
    # v1.10: 从 composite 结果读取 short_sample_factors，传给 weight_engine 进行 ICIR 惩罚
    short_sample_factors = None
    dimension_weight_method = None  # v1.21: 维度权重方法（从 composite 结果读取）
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
            # v1.21: 读取维度权重方法，传给 WeightEngine（修复维度权重不生效 bug）
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

    # Step 10: 排序选出 Top N
    logger.info("排序选股（Top N: %d，方向: %s）...", config.top_n, config.factor_direction)

    # v1.10: 获取权重用于覆盖率过滤
    # 从 composite 结果读取权重，或从 weight_engine 计算获取
    selection_weights = None
    if composite_file.exists():
        try:
            with open(composite_file, encoding="utf-8") as f:
                composite_data_for_weights = json.load(f)
            # 尝试从 meta.weights 读取（ICIR/IC 等静态权重）
            selection_weights = composite_data_for_weights.get("meta", {}).get("weights")
            if not selection_weights:
                # 尝试从 weight_meta.last_day_weights 读取（滚动ICIR）
                wm = composite_data_for_weights.get("meta", {}).get("weight_meta", {})
                selection_weights = wm.get("last_day_weights")
        except (json.JSONDecodeError, KeyError):
            logger.warning("无法从 composite 结果读取权重，跳过覆盖率过滤")

    # v1.13: 映射权重键名：因子名 → 列名
    # last_day_weights 键为因子名(如 volume_ratio)，factor_cols 为列名(如 volume_ratio_5)
    # 不映射会导致覆盖率计算中 col in factor_cols 永远 False，覆盖率恒为 1-volume_ratio_weight
    if selection_weights and factor_list and factor_cols:
        name_to_col = dict(zip(factor_list, factor_cols))
        selection_weights = {name_to_col.get(k, k): v for k, v in selection_weights.items()}

    # v3.9: Bottom30 过热过滤 (designs/feat_bottom30_overheat_filter.md)
    #   Stage 1: composite Top stage1_pool_size (保留, 候选池基础设施)
    #   Stage 2/3: 废弃——不再对 Top30 做 turnover 重排 + 企稳过滤
    #   Bottom30: composite 升序取最低 top_n*2 → 过热过滤 → top_n (最终短名单)
    stage1_top_snapshot: list[dict[str, Any]] = []
    stage2_top_snapshot: list[dict[str, Any]] = []  # v3.9: 不再使用, 保留为空
    stage1_bottom_snapshot: list[dict[str, Any]] = []
    excluded_by_confirmation = 0  # v3.9: 企稳过滤废弃, 恒为 0
    excluded_by_overheat = 0  # v3.9: 过热过滤排除数

    # Stage 1: composite Top stage1_pool_size (候选池, 保留基础设施)
    stage1_n = config.stage1_pool_size
    logger.info("Stage 1: composite Top %d (候选池)", stage1_n)
    stage1_stocks, excluded_by_amplitude, excluded_by_coverage, excluded_by_liquidity = sort_and_select(
        composite_factor,
        factor_df,
        stage1_n,
        config.factor_direction,
        factor_cols,
        weights=selection_weights,
        min_amplitude=config.min_amplitude,
        enable_liquidity_filter=config.enable_liquidity_filter,
        min_amount_percentile=config.min_amount_percentile,
        logger=logger,
    )
    stage1_top_snapshot = [copy.deepcopy(s) for s in stage1_stocks[: config.top_n]]

    # v3.9: Bottom30 过热过滤候选池 (composite 升序 top_n*2, 留递补空间)
    valid_cf = composite_factor.dropna()
    if len(valid_cf) > 0:
        bottom_candidates = valid_cf.nsmallest(config.top_n * 2)
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
        # 原始快照 (过滤前, 前 top_n 只)
        stage1_bottom_snapshot = [copy.deepcopy(s) for s in bottom_pool[: config.top_n]]

        # v3.9: 加载过热过滤所需列 (turnover_rate, volume_ratio_5)
        overheat_aux_cols = ["turnover_rate", "volume_ratio_5"]
        missing_oh = [c for c in overheat_aux_cols if c not in factor_df.columns]
        factor_df_for_overheat = factor_df
        if missing_oh:
            logger.info("过热过滤: 加载辅助列 %s", missing_oh)
            try:
                aux_df_raw = load_factor_values(missing_oh, config.data_source, logger)
                aux_df = cast(pd.DataFrame, aux_df_raw)
                if "date" in aux_df.columns:
                    aux_df = aux_df[aux_df["date"] == selection_date].copy()
                merge_cols = ["asset"] + [c for c in missing_oh if c in aux_df.columns]
                factor_df_for_overheat = factor_df.merge(cast(pd.DataFrame, aux_df[merge_cols]), on="asset", how="left")
                logger.info(
                    "过热过滤: %d 只股票获得 turnover_rate/volume_ratio_5 值",
                    factor_df_for_overheat["turnover_rate"].notna().sum(),
                )
            except (FileNotFoundError, KeyError, ValueError) as e:
                logger.warning("过热过滤: 辅助列加载失败 (%s), 跳过过滤", e)

        # v3.9.1: 过热过滤 (彻底数据驱动——每次运行时校准阈值)
        if config.enable_overheat_filter:
            # 1) 用全历史数据校准最优分位阈值
            t_pct, v_pct = calibrate_overheat_thresholds(
                factor_df,
                composite_factor,
                config.top_n,
                config.overheat_calibrate_grid,
                config.overheat_calibrate_min_pvalue,
                logger=logger,
            )
            logger.info(
                "Bottom30 过热过滤 (v3.9.1) | 校准阈值: turnover=%.0f%%, volume_ratio=%.0f%% → Top %d",
                t_pct * 100,
                v_pct * 100,
                config.top_n,
            )
            # 2) 用校准后的阈值执行过滤
            top_stocks, excluded_by_overheat = apply_overheat_filter(
                bottom_pool,
                factor_df_for_overheat,
                config.top_n,
                turnover_percentile=t_pct,
                volume_ratio_percentile=v_pct,
                logger=logger,
            )
        else:
            top_stocks = bottom_pool[: config.top_n]

        # v3.9: top_stocks 即过热过滤后最终短名单 (与 write_selection_history 的 stage3_top 对应)
    else:
        top_stocks = []

    # Step 10.6: 决策卡片 (v2.43, designs/feat_decision_card_v1.md)
    # 在短名单上叠加 5 维客观字段, 辅助人工决断 (3~5 只持仓)
    # 战略目标 (AGENTS.md): 量化辅助 + 人工决断
    # v3.9: 决策卡片辅助列 — 从企稳信号改为过热/趋势确认信号
    # D1: amplitude, close, high, low, return_5d (涨跌幅/振幅/区间位置)
    # D2: turnover_rate, volume_ratio_5, amplitude (过热风险)
    # D3: near_high_ratio_5, bollinger_pb, rsi_6 (趋势确认)
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
            # 过滤到 selection_date (与 factor_df 对齐)
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

    # Step 11: 构建结果（仅作为函数返回供 CLI/调用方查看, 不再写 JSON 落盘——v3.7 改用 Parquet）
    # 问题 2 修复：total_stocks → stocks_on_date
    # v1.10: 传入 direction_map 和 flipped_factors
    # v1.12: 传入 excluded_by_amplitude
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
        excluded_by_amplitude=excluded_by_amplitude,  # v1.12: 振幅过滤排除数
        excluded_by_coverage=excluded_by_coverage,  # v1.15: 覆盖率过滤排除数
        excluded_by_liquidity=excluded_by_liquidity,  # v2.40: 流动性过滤排除数
        excluded_by_confirmation=excluded_by_confirmation,  # v2.35: P6 企稳过滤排除数 (v3.9: 恒为 0)
        excluded_by_overheat=excluded_by_overheat,  # v3.9: Bottom30 过热过滤排除数
        excluded_by_filter=filter_exclusions,  # v2.41 (R3): filter 角色排除数
        logger=logger,
    )

    # Step 12: 写入 Parquet 选股历史 (v3.7, designs/feat_stock_selection_history_parquet.md)
    # 取代 v3.6 之前的 save_result JSON 单文件——Parquet 单一信源, 失败抛异常无兜底
    # 单阶段模式 (enable_two_stage=False) 时 stage1/stage2 快照为 [], 只归档 stage3
    # v3.9: exclusion_stats 新增 excluded_by_overheat
    exclusion_stats = {
        "excluded_by_amplitude": excluded_by_amplitude,
        "excluded_by_coverage": excluded_by_coverage,
        "excluded_by_liquidity": excluded_by_liquidity,
        "excluded_by_confirmation": excluded_by_confirmation,  # v3.9: 恒为 0
        "excluded_by_overheat": excluded_by_overheat,  # v3.9: 过热过滤排除数
        "excluded_by_filter": filter_exclusions,
        "min_weight_coverage": 0.5,  # v1.15 阈值, 与 build_result 默认一致
    }
    # v3.9: stage3_top 不再使用 (Top30 企稳过滤废弃), 改传 bottom_filtered
    partition_dir = write_selection_history(
        stage1_top=stage1_top_snapshot,
        stage2_top=stage2_top_snapshot,  # v3.9: 空
        stage3_top=top_stocks,  # v3.9: bottom_filtered 过热过滤后短名单
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
        stage1_bottom=stage1_bottom_snapshot,  # v3.8: Bottom 30 原始快照 (过滤前)
        logger=logger,
    )

    # 问题 4 修复：删除流程完成日志，让 CLI 层的成功日志兼任收尾
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
