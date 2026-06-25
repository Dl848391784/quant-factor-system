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
from typing import TYPE_CHECKING, Any, cast

import numpy as np
import pandas as pd


if TYPE_CHECKING:
    from sklearn.linear_model import LogisticRegression
    from sklearn.preprocessing import StandardScaler


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
__version__ = "3.11"

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

    # v3.10: LR 数据驱动过滤 (designs/feat_lr_training_data.md)
    #   方案: 每日保存 Bottom90 训练数据 → 积累 90 天后训练 LR → walk-forward OOS 验证 → 打分过滤
    #   关键: 训练样本 = 实际选股目标 (composite Bottom90), 训练分布 = 应用分布 (第一性原理)
    #   v3.9.2 的 return_5d 代理已废弃 (训练分布 ≠ 应用分布, 重叠率 0%)
    enable_overheat_filter: bool = False  # v3.13: 关闭 LR 过滤, 短名单按 composite 排序直接取 30
    lr_min_training_days: int = 90  # 最小训练天数, 不足则 calibrate_lr_filter 返回 None
    lr_top_features: int = 10  # Cohen's d 排序取 top N 特征
    lr_train_window: int = 120  # walk-forward 训练窗口 (天)
    lr_min_oos_auc: float = 0.55  # OOS AUC 门槛, 低于此值跳过过滤
    lr_filter_quantile: float = 0.3  # Bottom30 中打分最低 30% 排除
    lr_bottom_pool_size: int = 90  # 训练数据保存的 Bottom 数量 (Bottom90)

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

        # v3.10: LR 过滤参数校验
        if self.enable_overheat_filter:
            if self.lr_min_training_days < 30:
                raise ValueError(f"lr_min_training_days 至少 30, 当前: {self.lr_min_training_days}")
            if self.lr_top_features < 3:
                raise ValueError(f"lr_top_features 至少 3, 当前: {self.lr_top_features}")
            if self.lr_train_window < 30:
                raise ValueError(f"lr_train_window 至少 30 天, 当前: {self.lr_train_window}")
            if not 0.5 <= self.lr_min_oos_auc <= 1.0:
                raise ValueError(f"lr_min_oos_auc 必须在 [0.5, 1.0], 当前: {self.lr_min_oos_auc}")
            if not 0 < self.lr_filter_quantile < 1:
                raise ValueError(f"lr_filter_quantile 必须在 (0, 1), 当前: {self.lr_filter_quantile}")
        # v3.10: lr_bottom_pool_size 校验 (不论是否启用过滤)
        if self.lr_bottom_pool_size < self.top_n:
            raise ValueError(f"lr_bottom_pool_size ({self.lr_bottom_pool_size}) 必须 >= top_n ({self.top_n})")


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


def _discover_features(
    bottom_df: pd.DataFrame,
    feature_cols: list[str],
    top_n: int,
    logger: logging.Logger,
) -> list[str]:
    """v3.12: 数据驱动特征发现——Cohen's d 选 top N + 同族去重.

    在 Bottom90 历史样本上, 按 T+1 涨跌分组, 计算每个特征的 Cohen's d 效应量.
    按 |d| 降序贪心选取, 每次选入前检查与已选特征的 Pearson |r|,
    若 |r| > 0.7 则跳过 (同族共线性特征, 避免多变量系数翻转).

    根因: 原始特征 (factor_xxx) 与标准化特征 (factor_xxx_std) 高度相关
    (|r| ≈ 0.78~0.85) 但方向相反, 同时入选会导致 LR 多变量系数翻转.
    """
    up_mask = bottom_df["forward_return_1d"] > 0
    down_mask = bottom_df["forward_return_1d"] < 0

    scores: list[tuple[str, float]] = []
    for col in feature_cols:
        up_vals = bottom_df.loc[up_mask, col].dropna()
        down_vals = bottom_df.loc[down_mask, col].dropna()
        if len(up_vals) < 30 or len(down_vals) < 30:
            continue
        pooled_std = float(
            np.sqrt(
                ((len(up_vals) - 1) * up_vals.var() + (len(down_vals) - 1) * down_vals.var())
                / (len(up_vals) + len(down_vals) - 2)
            )
        )
        if pooled_std <= 0:
            continue
        d = float((up_vals.mean() - down_vals.mean()) / pooled_std)
        scores.append((col, abs(d)))

    scores.sort(key=lambda x: x[1], reverse=True)

    # v3.12: 同族去重 — 贪心选取, |r| > 0.7 视为同族, 跳过
    correlation_threshold = 0.7
    selected: list[str] = []
    skipped_due_to_correlation: list[tuple[str, str, float]] = []

    for feat_name, feat_d in scores:
        if len(selected) >= top_n:
            break
        if not selected:
            selected.append(feat_name)
            continue

        # 计算与已选特征的相关性
        feat_vals = bottom_df[feat_name].dropna()
        is_redundant = False
        for sel_feat in selected:
            sel_vals = bottom_df[sel_feat]
            # 对齐索引
            common_idx = feat_vals.index.intersection(sel_vals.dropna().index)
            if len(common_idx) < 30:
                continue
            r = float(feat_vals.loc[common_idx].corr(sel_vals.loc[common_idx]))
            if abs(r) > correlation_threshold:
                skipped_due_to_correlation.append((feat_name, sel_feat, r))
                is_redundant = True
                break

        if not is_redundant:
            selected.append(feat_name)

    logger.info(
        "特征发现: 扫描 %d 个特征, 选 top %d: %s",
        len(feature_cols),
        len(selected),
        ", ".join(f"{s[0]}({s[1]:.3f})" for s in scores if s[0] in selected),
    )
    if skipped_due_to_correlation:
        logger.debug(
            "特征去重: 跳过 %d 个同族特征 (|r| > %.1f): %s",
            len(skipped_due_to_correlation),
            correlation_threshold,
            ", ".join(f"{f}↔{s}(r={r:.2f})" for f, s, r in skipped_due_to_correlation[:5]),
        )
    return selected


def calibrate_lr_filter(
    training_data_dir: str | Path,
    weight_method: str,
    top_n: int = 30,
    n_features: int = 10,
    train_window: int = 120,
    min_oos_auc: float = 0.55,
    min_training_days: int = 90,
    filter_quantile: float = 0.3,
    logger: logging.Logger | None = None,
) -> tuple["LogisticRegression | None", "StandardScaler | None", list[str], float]:
    """v3.10: 从 lr_training_data 读取训练样本, 训练 LR 模型.

    与 v3.9.2 的根本区别:
    - 训练样本来自 lr_training_data (真实 Bottom90), 不再用 return_5d 代理
    - 训练分布 = 应用分布 (第一性原理)
    - 需要检查训练天数 ≥ min_training_days, 不足则返回 None
    - forward_return_1d 为 null 的行跳过 (T+1 未补写)

    流程:
    1. 从 training_data_dir 读取 weight_method 分区下所有 selection_date
    2. 过滤 forward_return_1d 非 null 的行
    3. 检查有效天数 ≥ min_training_days
    4. _discover_features: Cohen's d 选 top N (样本来自真实 Bottom90)
    5. Walk-forward OOS 验证
    6. 全样本训练最终模型

    Args:
        training_data_dir: lr_training_data 根目录.
        weight_method: 权重方式 (如 'equal_weight').
        top_n: Bottom N (用于日志, 默认 30).
        n_features: top N 特征数 (Cohen's d 排序).
        train_window: walk-forward 训练窗口天数.
        min_oos_auc: OOS AUC 门槛.
        min_training_days: 最小训练天数, 不足返回 None.
        filter_quantile: 排除底 N% (用于日志).
        logger: 日志对象.

    Returns:
        (model, scaler, selected_features, oos_auc).
        如果训练数据不足或 OOS 验证不通过, 返回 (None, None, [], 0.0).
    """
    if logger is None:
        logger = _logger

    from sklearn.linear_model import LogisticRegression
    from sklearn.metrics import roc_auc_score
    from sklearn.preprocessing import StandardScaler

    # 1) 从 lr_training_data 读取训练样本
    wm_dir = Path(training_data_dir) / f"weight_method={weight_method}"
    if not wm_dir.exists():
        logger.info("LR 校准: 训练数据目录不存在 (%s), 跳过过滤", wm_dir)
        return None, None, [], 0.0

    # 逐个 selection_date 分区读取 (避免 ds.dataset schema merge 冲突)
    import os

    parts: list[pd.DataFrame] = []
    for date_dir_name in sorted(os.listdir(wm_dir)):
        if not date_dir_name.startswith("selection_date="):
            continue
        date_str = date_dir_name.replace("selection_date=", "")
        parquet_path = wm_dir / date_dir_name / "part-0.parquet"
        if not parquet_path.exists():
            continue
        try:
            part_df = pd.read_parquet(parquet_path)
            part_df["selection_date"] = date_str  # 显式注入分区键
            parts.append(part_df)
        except Exception as e:
            logger.debug("LR 校准: 读取 %s 失败: %s", parquet_path, e)
            continue

    if not parts:
        logger.info("LR 校准: 训练数据为空 (%s), 跳过过滤", weight_method)
        return None, None, [], 0.0

    bottom_df = pd.concat(parts, ignore_index=True)

    # 过滤 forward_return_1d 非 null 的行 (T+1 已补写)
    bottom_df = bottom_df.dropna(subset=["forward_return_1d"]).copy()

    if bottom_df.empty:
        logger.info("LR 校准: 无已补写 forward_return_1d 的样本, 跳过过滤")
        return None, None, [], 0.0

    # 检查训练天数
    if "selection_date" not in bottom_df.columns:
        logger.warning("LR 校准: 训练数据缺少 selection_date 列, 跳过过滤")
        return None, None, [], 0.0

    dates = sorted(bottom_df["selection_date"].unique())
    n_valid_days = len(dates)

    if n_valid_days < min_training_days:
        logger.info(
            "LR 校准: 训练天数 %d < 门槛 %d, 跳过过滤 (积累中)",
            n_valid_days,
            min_training_days,
        )
        return None, None, [], 0.0

    logger.info(
        "LR 校准: %d 天训练数据, %d 条记录, weight_method=%s",
        n_valid_days,
        len(bottom_df),
        weight_method,
    )

    # 确定特征列 (factor_ 前缀的列, 排除非数值如 factor_direction)
    feature_cols = [
        c
        for c in bottom_df.columns
        if c.startswith("factor_") and bottom_df[c].dtype in ("float64", "float32", "int64", "int32")
    ]
    if not feature_cols:
        logger.warning("LR 校准: 训练数据无 factor_ 前缀列, 跳过过滤")
        return None, None, [], 0.0

    # 2) 数据驱动特征发现
    selected_features = _discover_features(bottom_df, feature_cols, n_features, logger)

    if len(selected_features) < 3:
        logger.warning("LR 校准: 有效特征不足 (%d < 3), 跳过过滤", len(selected_features))
        return None, None, [], 0.0

    # 3) Walk-forward OOS 验证
    date_to_data = {d: bottom_df[bottom_df["selection_date"] == d] for d in dates}
    oos_aucs: list[float] = []

    for i in range(train_window, len(dates)):
        train_dates = dates[i - train_window : i]
        test_date = dates[i]

        train_data = pd.concat([date_to_data[d] for d in train_dates], ignore_index=True)
        test_data = date_to_data[test_date]

        X_train = train_data[selected_features]
        y_train = (train_data["forward_return_1d"] > 0).astype(int)
        X_test = test_data[selected_features]
        y_test = (test_data["forward_return_1d"] > 0).astype(int)

        train_valid = X_train.notna().all(axis=1)
        test_valid = X_test.notna().all(axis=1)
        X_train = X_train[train_valid]
        y_train = y_train[train_valid]
        X_test = X_test[test_valid]
        y_test = y_test[test_valid]

        if len(X_train) < 100 or len(X_test) < 5:
            continue
        if y_train.nunique() < 2 or y_test.nunique() < 2:
            continue

        scaler = StandardScaler()
        model = LogisticRegression(max_iter=1000, random_state=42)
        try:
            model.fit(scaler.fit_transform(X_train), y_train)
            y_pred = model.predict_proba(scaler.transform(X_test))[:, 1]
            oos_aucs.append(float(roc_auc_score(y_test, y_pred)))
        except (ValueError, np.linalg.LinAlgError) as e:
            logger.debug("LR walk-forward 窗口 %s 失败: %s", test_date, e)
            continue

    if not oos_aucs:
        logger.warning("LR 校准: walk-forward 无有效窗口, 跳过过滤")
        return None, None, [], 0.0

    mean_auc = float(np.mean(oos_aucs))
    median_auc = float(np.median(oos_aucs))
    pct_above = float(np.mean(np.array(oos_aucs) > min_oos_auc) * 100)
    logger.info(
        "LR walk-forward OOS: AUC=%.3f±%.3f (中位 %.3f), >%.2f: %.0f%%, 窗口数=%d",
        mean_auc,
        float(np.std(oos_aucs)),
        median_auc,
        min_oos_auc,
        pct_above,
        len(oos_aucs),
    )

    if mean_auc < min_oos_auc:
        logger.warning(
            "LR 校准: OOS AUC %.3f < 门槛 %.2f, 跳过过滤",
            mean_auc,
            min_oos_auc,
        )
        return None, None, selected_features, mean_auc

    # 4) 用全样本训练最终模型
    X_full = bottom_df[selected_features]
    y_full = (bottom_df["forward_return_1d"] > 0).astype(int)
    full_valid = X_full.notna().all(axis=1)
    X_full = X_full[full_valid]
    y_full = y_full[full_valid]

    final_scaler = StandardScaler()
    final_model = LogisticRegression(max_iter=1000, random_state=42)
    final_model.fit(final_scaler.fit_transform(X_full), y_full)

    logger.info(
        "LR 校准完成: %d 特征, OOS AUC=%.3f, 过滤底 %.0f%%",
        len(selected_features),
        mean_auc,
        filter_quantile * 100,
    )
    return final_model, final_scaler, selected_features, mean_auc


def apply_lr_filter(
    bottom_stocks: list[dict[str, Any]],
    data_source: str | Path,
    selection_date: str,
    top_n: int,
    model: "LogisticRegression",
    scaler: "StandardScaler",
    selected_features: list[str],
    filter_quantile: float,
    logger: logging.Logger | None = None,
) -> tuple[list[dict[str, Any]], int]:
    """v3.9.2: 用 LR 模型对 Bottom30 打分, 排除预测 T+1 跌概率最高的.

    从 data_source 加载当日特征数据 (selected_features 列), 不依赖调用方 factor_df.
    模型输出 proba_up = P(T+1 > 0). 打分最低的 filter_quantile 比例排除,
    不足 top_n 时从被排除的股票递补 (标记 lr_warning=True).
    """
    if logger is None:
        logger = _logger

    if model is None or scaler is None or not selected_features:
        logger.info("LR 过滤: 模型不可用, 跳过过滤")
        return bottom_stocks[:top_n], 0

    # v3.11 修复: 训练特征名 (factor_xxx / factor_xxx_std) → parquet 原始列名 (xxx) 映射
    # lr_training_data 中列名带 factor_ 前缀和 _std 后缀, 但 parquet 中是原始列名
    def _map_feat_to_parquet(feat: str) -> str:
        base = feat
        if base.startswith("factor_"):
            base = base[7:]
        if base.endswith("_std"):
            base = base[:-4]
        return base

    # 建立 训练特征 → parquet列名 映射, 去重加载 parquet 列
    feat_to_parquet = {f: _map_feat_to_parquet(f) for f in selected_features}
    unique_parquet_feats = list(dict.fromkeys(feat_to_parquet.values()))

    # 加载当日特征数据 (仅 unique_parquet_feats 列, 开销极小)
    day_df = load_factor_values(unique_parquet_feats, data_source, logger)
    day_df = day_df[day_df["date"].apply(lambda d: pd.Timestamp(d).strftime("%Y-%m-%d")) == selection_date].copy()
    asset_index = day_df.set_index("asset") if "asset" in day_df.columns else day_df

    # v3.12: 检测当天全 NaN 的特征列, 用 0 填充 (scaler 之后均值=0, 等价于中性贡献)
    # 根因: 部分因子 (如 capital_flow_ratio_trend) 在最新一天可能全 NaN (增量采集延迟),
    # 任何一个特征 NaN 会导致整只股票被判 "特征缺失" → 90/90 全中性概率 → LR 过滤无效
    all_nan_feats = [f for f in unique_parquet_feats if day_df[f].isna().all()]
    if all_nan_feats:
        logger.warning(
            "LR 过滤: 当天全 NaN 特征 %d 个, 用 0 填充: %s",
            len(all_nan_feats),
            ", ".join(all_nan_feats[:5]),
        )
        day_df[all_nan_feats] = 0.0
        asset_index = day_df.set_index("asset") if "asset" in day_df.columns else day_df

    # 收集每只股票的特征和模型打分
    scored: list[tuple[dict[str, Any], float]] = []
    missing_features = 0  # 不在数据源中的股票数
    for stock in bottom_stocks:
        code = stock["code"]
        if code not in asset_index.index:
            missing_features += 1
            scored.append((stock, 0.5))  # 数据不可用 → 中性概率
            continue

        row = asset_index.loc[code]
        if isinstance(row, pd.DataFrame):
            row = row.iloc[0]

        # 按 selected_features 顺序构建特征向量 (重复的 parquet 列会读到同一个值)
        # v3.12: 个别股票的 NaN 特征用 0 填充 (scaler 之后均值=0, 中性贡献)
        feature_vals = []
        for feat in selected_features:
            parquet_col = feat_to_parquet[feat]
            val = row.get(parquet_col, np.nan)
            if isinstance(val, pd.Series):
                val = val.iloc[0]
            if pd.isna(val):
                val = 0.0
            feature_vals.append(float(val))

        X = pd.DataFrame([feature_vals], columns=selected_features)
        proba_up = float(model.predict_proba(scaler.transform(X))[0, 1])
        scored.append((stock, proba_up))

    if missing_features > 0:
        logger.info(
            "LR 过滤: %d/%d 只股票不在数据源中, 使用中性概率 0.5",
            missing_features,
            len(scored),
        )

    # 按 proba_up 降序排 (概率高的 = 预测涨的 = 保留)
    scored.sort(key=lambda x: x[1], reverse=True)

    # 打分最低的 filter_quantile 比例排除
    n_exclude = int(len(scored) * filter_quantile)
    n_exclude = min(n_exclude, len(scored) - top_n)  # 确保留够 top_n
    if n_exclude <= 0:
        logger.info("LR 过滤: 候选不足, 无需排除")
        return bottom_stocks[:top_n], 0

    kept = scored[: len(scored) - n_exclude]
    excluded = scored[len(scored) - n_exclude :]

    # 不足 top_n 时用被排除的递补 (标记 lr_warning)
    if len(kept) < top_n:
        for stock, proba in excluded:
            if len(kept) >= top_n:
                break
            stock["lr_warning"] = True
            stock["lr_proba_up"] = round(proba, 4)
            kept.append((stock, proba))

    # 重新编号 rank
    filtered = []
    for idx, (stock, proba) in enumerate(kept[:top_n], start=1):
        stock["rank"] = idx
        stock["lr_proba_up"] = round(proba, 4)
        filtered.append(stock)

    logger.info(
        "LR 过滤: %d 只候选 → 排除 %d (底 %.0f%%), 保留 %d",
        len(scored),
        n_exclude,
        filter_quantile * 100,
        len(filtered),
    )

    return filtered, n_exclude


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


def save_lr_training_data(
    bottom_stocks: list[dict[str, Any]],
    factor_df: pd.DataFrame,
    weight_config: dict[str, Any],
    config: "StockSelectorConfig",
    selection_date: str,
    logger: logging.Logger | None = None,
) -> Path | None:
    """v3.10: 持久化 Bottom90 训练数据到 Parquet 双分区数据集.

    分区布局:
        lr_training_data/weight_method=<method>/selection_date=YYYY-MM-DD/part-0.parquet

    每天每个 weight_method 写 90 行, 含因子权重 + 因子原始值 + composite 得分.
    forward_return_1d 当天为 null, 次日由 backfill_forward_return_1d() 补写.
    同日重跑覆盖该分区.

    Args:
        bottom_stocks: Bottom90 股票列表 (composite 升序最低 90 只).
        factor_df: 当日全特征数据 (含因子列, index 对齐 bottom_stocks).
        weight_config: 权重配置 (含 best_selection.method, meta.weight_meta.last_day_weights).
        config: 选股配置.
        selection_date: 选股日期 'YYYY-MM-DD'.
        logger: 日志.

    Returns:
        分区目录路径, 失败返回 None.
    """
    if logger is None:
        logger = _logger

    import pyarrow as pa
    import pyarrow.parquet as pq
    from paths import LR_TRAINING_DATA_DIR

    if not bottom_stocks:
        logger.warning("save_lr_training_data: bottom_stocks 为空, 跳过")
        return None

    # v3.11: weight_method 从 meta.weight_method 读取 (composite JSON 结构)
    #   之前从 best_selection.method 读取, 但 v3.11 循环传入的是 composite JSON (无 best_selection)
    meta = weight_config.get("meta", {})
    weight_method = meta.get("weight_method", "equal_weight")
    composite_score = float(weight_config.get("best_selection", {}).get("composite_score", 0.0))

    # 确定因子列 (从 factor_df 中排除非因子列, 提前到权重处理之前)
    exclude = {
        "date",
        "asset",
        "forward_return_1d",
        "forward_return_3d",
        "forward_return_5d",
        "past_return_1d",
        "return_3d",
        "return_5d",
        "return_acceleration_5d",
        "close",
        "high",
        "low",
        "open",
        "volume",
        "amount",
        "turnover_rate",
    }
    factor_cols = [
        c
        for c in factor_df.columns
        if c not in exclude
        and c.startswith(
            (
                "amplitude",
                "bollinger",
                "capital",
                "downside",
                "industry",
                "interaction",
                "ma",
                "momentum",
                "near",
                "price",
                "rsi",
                "tail",
                "turnover",
                "volume",
                "amplitude_",
            )
        )
    ]

    # 因子权重 (从 weight_meta.last_day_weights 或 meta.weights 读取, 等权方式自动生成 1/n)
    weight_meta = meta.get("weight_meta", {})
    last_day_weights = weight_meta.get("last_day_weights", {})
    if not last_day_weights:
        # v3.11: icir_weight/ic_weight 的权重存在 meta.weights 中 (非 weight_meta.last_day_weights)
        last_day_weights = meta.get("weights", {})
    if not last_day_weights:
        # equal_weight / icir_weight / ic_weight 无显式权重 → 等权 1/n
        n_factors = len(factor_cols) if factor_cols else 1
        last_day_weights = dict.fromkeys(factor_cols, 1.0 / n_factors)
        logger.info(
            "save_lr_training_data: 无显式权重 (weight_method=%s), 生成等权 1/%d",
            weight_method,
            n_factors,
        )

    # 映射因子逻辑名→列名
    name_to_col = {v: k for k, v in FACTOR_COL_TO_NAME_MAP.items()}
    weights_col_map = {name_to_col.get(k, k): v for k, v in last_day_weights.items()}

    # 股票名称映射
    stock_name_map = _load_stock_name_map()

    # 构建行数据
    run_id = str(uuid.uuid4())
    created_at = datetime.now(timezone.utc)

    rows: list[dict[str, Any]] = []
    for stock in bottom_stocks:
        code = stock["code"]
        composite_value = float(stock["composite_value"])
        rank = int(stock.get("rank", 0))

        row: dict[str, Any] = {
            "rank": rank,
            "code": code,
            "stock_name": stock_name_map.get(code, ""),
            "composite_value": composite_value,
            "composite_score": composite_score,
            "factor_direction": config.factor_direction,
            # weight_method 是 Hive 分区键, 不写入 body (与 selection_date 同理)
            "forward_return_1d": None,  # 次日补写
            "created_at": created_at,
            "run_id": run_id,
        }

        # 因子权重列 (weight_<factor_col>)
        for fcol, w_val in weights_col_map.items():
            row[f"weight_{fcol}"] = float(w_val)

        # 因子原始值列 (factor_<factor_col>)
        if code in factor_df["asset"].values:
            stock_row = factor_df[factor_df["asset"] == code].iloc[0]
            for fcol in factor_cols:
                val = stock_row.get(fcol)
                row[f"factor_{fcol}"] = float(val) if pd.notna(val) else None
        else:
            for fcol in factor_cols:
                row[f"factor_{fcol}"] = None

        rows.append(row)

    df = pd.DataFrame(rows)

    # 显式 schema
    schema_fields = [
        pa.field("rank", pa.int16(), nullable=False),
        pa.field("code", pa.string(), nullable=False),
        pa.field("stock_name", pa.string(), nullable=True),
        pa.field("composite_value", pa.float64(), nullable=False),
        pa.field("composite_score", pa.float64(), nullable=False),
        pa.field("factor_direction", pa.string(), nullable=False),
        # weight_method 是 Hive 分区键, 不在 schema 中 (pyarrow 读取时自动注入)
        pa.field("forward_return_1d", pa.float64(), nullable=True),
        pa.field("created_at", pa.timestamp("us", tz="UTC"), nullable=False),
        pa.field("run_id", pa.string(), nullable=False),
    ]
    # 动态添加权重列和因子列
    weight_col_names = [f"weight_{c}" for c in weights_col_map]
    factor_col_names = [f"factor_{c}" for c in factor_cols]
    for cn in weight_col_names:
        schema_fields.append(pa.field(cn, pa.float64(), nullable=True))
    for cn in factor_col_names:
        schema_fields.append(pa.field(cn, pa.float64(), nullable=True))

    schema = pa.schema(schema_fields)

    # 写入: 双分区 weight_method/selection_date
    dataset_root = Path(LR_TRAINING_DATA_DIR)
    partition_dir = dataset_root / f"weight_method={weight_method}" / f"selection_date={selection_date}"

    try:
        table = pa.Table.from_pandas(df, schema=schema, preserve_index=False)
    except (pa.ArrowException, ValueError, TypeError) as e:
        logger.exception("save_lr_training_data: DataFrame → Arrow Table 转换失败")
        raise RuntimeError(f"save_lr_training_data: schema 转换失败: {type(e).__name__}: {e}") from e

    # file-level metadata
    existing_meta = table.schema.metadata or {}
    table = table.replace_schema_metadata(
        {
            **existing_meta,
            b"weight_method": weight_method.encode("utf-8"),
            b"selection_date": selection_date.encode("utf-8"),
            b"n_stocks": str(len(rows)).encode("utf-8"),
            b"factor_cols_json": json.dumps(factor_cols, ensure_ascii=False).encode("utf-8"),
            b"weight_cols_json": json.dumps(weight_col_names, ensure_ascii=False).encode("utf-8"),
            b"generated_at": created_at.strftime("%Y-%m-%dT%H:%M:%S%z").encode("utf-8"),
        }
    )

    try:
        partition_dir.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        logger.exception("save_lr_training_data: 创建分区目录失败: %s", partition_dir)
        raise RuntimeError(f"save_lr_training_data: 创建目录失败: {partition_dir}") from e

    target_path = partition_dir / "part-0.parquet"
    temp_path = partition_dir / "part-0.parquet.tmp"
    replaced = False
    try:
        pq.write_table(table, temp_path, compression="snappy")
        os.replace(temp_path, target_path)
        replaced = True
    except (pa.ArrowException, OSError) as e:
        logger.exception("save_lr_training_data: Parquet 写入失败: %s", target_path)
        raise RuntimeError(f"save_lr_training_data: 写入失败: {target_path}") from e
    finally:
        if not replaced:
            temp_path.unlink(missing_ok=True)

    logger.info(
        "LR 训练数据已写入: %s (n=%d, 权重列=%d, 因子列=%d, 大小=%.2f KB)",
        partition_dir,
        len(rows),
        len(weight_col_names),
        len(factor_col_names),
        target_path.stat().st_size / 1024,
    )
    return partition_dir


def backfill_forward_return_1d(
    data_source: str | Path,
    logger: logging.Logger | None = None,
) -> int:
    """v3.10: 补写 lr_training_data 中 forward_return_1d 为 null 的分区.

    流程:
    1. 扫描 lr_training_data 下所有 weight_method/selection_date 分区
    2. 找到 forward_return_1d 为 null 的分区
    3. 从 data_source 读取次日 forward_return_1d
    4. 原子覆盖回写

    Returns:
        补写的行数
    """
    if logger is None:
        logger = _logger

    import pyarrow as pa
    import pyarrow.parquet as pq
    from paths import LR_TRAINING_DATA_DIR

    dataset_root = Path(LR_TRAINING_DATA_DIR)
    if not dataset_root.exists():
        logger.info("backfill: lr_training_data 目录不存在, 跳过")
        return 0

    # 扫描所有分区
    total_backfilled = 0
    for wm_dir in sorted(dataset_root.iterdir()):
        if not wm_dir.is_dir() or not wm_dir.name.startswith("weight_method="):
            continue
        weight_method = wm_dir.name.replace("weight_method=", "")

        for date_dir in sorted(wm_dir.iterdir()):
            if not date_dir.is_dir() or not date_dir.name.startswith("selection_date="):
                continue
            selection_date = date_dir.name.replace("selection_date=", "")
            parquet_path = date_dir / "part-0.parquet"
            if not parquet_path.exists():
                continue

            # 读取现有数据
            try:
                table = pq.read_table(parquet_path)
                df = table.to_pandas()
            except (OSError, ValueError) as e:
                logger.warning("backfill: 读取 %s 失败: %s", parquet_path, e)
                continue

            # 检查是否需要补写
            if "forward_return_1d" not in df.columns:
                continue
            null_mask = df["forward_return_1d"].isna()
            if not null_mask.any():
                continue  # 已补写

            # 从 data_source 读取次日 forward_return_1d
            try:
                full_df = pd.read_parquet(
                    data_source,
                    columns=["date", "asset", "forward_return_1d"],
                )
                # 次日数据: selection_date 的 forward_return_1d 就是 T+1 收益
                next_day_data = full_df[
                    full_df["date"].apply(lambda d: pd.Timestamp(d).strftime("%Y-%m-%d")) == selection_date
                ]
                code_to_ret = dict(zip(next_day_data["asset"], next_day_data["forward_return_1d"], strict=True))

                # 补写
                for idx in df[null_mask].index:
                    code = df.loc[idx, "code"]
                    if code in code_to_ret:
                        ret = code_to_ret[code]
                        df.loc[idx, "forward_return_1d"] = float(ret) if pd.notna(ret) else None

                # 仍为 null 的说明次日数据不可用 (可能是最新一天, 还没 T+1)
                still_null = df["forward_return_1d"].isna().sum()
                if still_null == len(df):
                    logger.debug("backfill: %s/%s 次日数据不可用, 跳过", weight_method, selection_date)
                    continue

                # 原子覆盖回写
                schema = table.schema
                new_table = pa.Table.from_pandas(df, schema=schema, preserve_index=False)
                temp_path = parquet_path.parent / "part-0.parquet.tmp"
                pq.write_table(new_table, temp_path, compression="snappy")
                os.replace(temp_path, parquet_path)

                backfilled = int(len(df) - still_null - (~null_mask).sum())
                total_backfilled += backfilled
                logger.info(
                    "backfill: %s/%s 补写 %d 行 (剩余 %d 行无次日数据)",
                    weight_method,
                    selection_date,
                    backfilled,
                    still_null,
                )
            except (OSError, ValueError, KeyError) as e:
                logger.warning("backfill: %s/%s 失败: %s", weight_method, selection_date, e)
                continue

    if total_backfilled > 0:
        logger.info("backfill: 共补写 %d 行 forward_return_1d", total_backfilled)
    return total_backfilled


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

    # Step 0: v3.10 补写前一天 lr_training_data 的 forward_return_1d (T+1 收益)
    backfill_forward_return_1d(config.data_source, logger=logger)

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

    # v3.10: Bottom90 候选池 (composite 升序最低 90 只, 留递补 + 训练数据)
    #   v3.9 用 top_n*2=60, v3.10 改为 lr_bottom_pool_size=90 (训练数据需要更多样本)
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
        # 原始快照 (过滤前, 前 top_n 只)
        stage1_bottom_snapshot = [copy.deepcopy(s) for s in bottom_pool[: config.top_n]]

        # v3.10: LR 数据驱动过滤 (从 lr_training_data 读取训练样本, 非代理)
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
                    "Bottom30 LR 过滤 (v3.9.2) | %d 特征, OOS AUC=%.3f, 过滤底 %.0f%% → Top %d",
                    len(lr_features),
                    lr_auc,
                    config.lr_filter_quantile * 100,
                    config.top_n,
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
                logger.warning("LR 过滤: 模型不可用 (OOS AUC 不足或数据缺失), 跳过过滤")
                top_stocks = bottom_pool[: config.top_n]
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

    # Step 13: v3.11 保存四种权重方式的 LR 训练数据 (各 Bottom90 + 因子权重 + 因子值)
    # 次日 backfill_forward_return_1d 补写 T+1 收益
    # 训练分布 = 应用分布 (第一性原理, designs/feat_lr_training_data.md)
    # v3.11: 不再只存 best_method, 每天对四种方式各存一份 (designs/feat_multi_weight_lr_training.md)
    #   - best_method 切换时不冷启动
    #   - summary 可对比四种方式的 OOS AUC
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
