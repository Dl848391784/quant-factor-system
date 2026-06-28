"""
stock_selector_config.py — 配置类 + 常量 + 数据加载

从 stock_selector.py v3.12 拆分 (2026-06-26).
行为不变, 纯机械提取.

版本历史见 stock_selector.py 头注释.
"""

import json
import logging
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd


# sys.path 处理（遵循 MODULE.md M49）
PROJECT_ROOT = Path(__file__).parent.parent.resolve()
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))  # noqa: E402

from stock_selector.common.logger_config import get_logger  # noqa: E402


# 模块级 logger
_logger = get_logger(__name__)

# ============================================================================
# 模块级常量
# ============================================================================

# Pipeline 感知路径（从 paths.py 导入）
from paths import (  # noqa: E402
    COMPREHENSIVE_FACTOR_RESULT,
    FACTOR_IC_DATA,
    FACTOR_IC_RESULT,
)


DEFAULT_DATA_SOURCE = FACTOR_IC_DATA
DEFAULT_IC_RESULT_DIR = FACTOR_IC_RESULT
DEFAULT_WEIGHT_RESULT_PATH = COMPREHENSIVE_FACTOR_RESULT / "weight_selection_result.json"
DEFAULT_OUTPUT_DIR = COMPREHENSIVE_FACTOR_RESULT

# 默认因子列表（fallback，优先从 composite 结果读取）
DEFAULT_FACTOR_LIST: list[str] = []

DEFAULT_FACTOR_COLS: list[str] = []

# v3.11: 四种权重方式各计算 composite_factor
ALL_WEIGHT_METHODS = ("equal_weight", "icir_weight", "ic_weight", "rolling_icir_weight")

# 浮点精度容差（遵循 MODULE.md M54）
EPSILON = 1e-10


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
    enable_overheat_filter: bool = True  # v3.13: LR 打分排序, 不截断, 全部输出到 report
    lr_min_training_days: int = 90  # 最小训练天数, 不足则 calibrate_lr_filter 返回 None
    lr_top_features: int = 10  # Cohen's d 排序取 top N 特征
    lr_train_window: int = 120  # walk-forward 训练窗口 (天)
    lr_min_oos_auc: float = 0.55  # OOS AUC 门槛, 低于此值跳过过滤
    lr_filter_quantile: float = 0.3  # Bottom30 中打分最低 30% 排除
    lr_bottom_pool_size: int = 90  # 训练数据保存的 Bottom 数量 (Bottom90)

    # v3.15: ob_pool 二次排序（换手率 + 市值, designs/feat_ob_pool_secondary_sort.md）
    #   实证依据: 跨 4 pipeline 840 只股票分析
    #   - 换手率 p=0.008 (上涨组 8.78% vs 下跌组 5.18%)
    #   - 市值 p≈0.05 (上涨组中位 197亿 vs 下跌组 85亿)
    #   仅对股票池 ≤400 只的 pipeline 生效 (ob_pool ~200 只), 全市场不启用
    enable_secondary_sort: bool = True
    secondary_sort_pool_threshold: int = 400  # 股票池超过此数不启用
    secondary_sort_composite_weight: float = 0.5  # composite 因子权重
    secondary_sort_turnover_weight: float = 0.3  # 换手率权重
    secondary_sort_market_cap_weight: float = 0.2  # 市值权重

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
            f"权重选择结果文件不存在: {weight_result_path}\n请先运行 composite_weight_selector.py 生成最优权重配置"
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
