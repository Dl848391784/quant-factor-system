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

作者: 云瑶
创建日期: 2026-06-03
"""

import json
import logging
import sys
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


# ============================================================================
# 模块级常量
# ============================================================================

# 版本号（遵循 PROJECT.md 规范）
__version__ = "1.15"

# logger 实例（遵循 PROJECT.md 第380-500行日志规范）
_logger = get_logger(__name__)


# ============================================================================
# 配置类
# ============================================================================

DEFAULT_DATA_SOURCE = PROJECT_ROOT / "data_fetchers" / "result" / "factor_ic_data.json.gz"
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
        - factor_direction 固定为 'negative'（综合因子默认反向）
        - 参考 MODULE.md M79: 综合因子低值预期高收益
    """

    # 问题 2 修复：删除 factor_list/factor_cols 字段
    # 运行时从 composite 结果读取，是 dead config

    # === 选股参数 ===
    top_n: int = 10  # 选出前 N 只股票（v1.12: 从3改为10，扩大选股范围）
    factor_direction: str = "negative"  # 综合因子方向（反向）
    rolling_window: int = 60  # 滚动 ICIR 窗口
    min_amplitude: float = 0.01  # 最低振幅阈值（排除不可交易的一字板涨停股，振幅<1%无法买入）

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
    logger: logging.Logger | None = None,
) -> tuple[list[dict[str, Any]], int, int]:
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
        logger: 日志对象（默认使用模块级 _logger）

    Returns:
        Tuple[选股结果列表, 振幅过滤排除数, 覆盖率过滤排除数]
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

    # v1.12: 振幅过滤（排除不可交易的一字板涨停股）
    # 振幅 < min_amplitude 的股票实际无法买入（一字板封涨停），排除以提高选股可操作性
    excluded_by_amplitude = 0
    if min_amplitude > 0 and "amplitude" in result_df.columns:
        amplitude_mask = result_df["amplitude"] >= min_amplitude
        excluded_by_amplitude = int(valid_mask.sum() - (valid_mask & amplitude_mask).sum())

        if excluded_by_amplitude > 0:
            logger.info(
                "振幅过滤: 排除 %d 只股票（振幅 < %.2f%%，一字板或接近一字板涨停股不可买入）",
                excluded_by_amplitude,
                min_amplitude * 100,
            )
        valid_mask = valid_mask & amplitude_mask

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
        factor_values = {}
        # v1.3 新增：标准化因子值（z-score，经 Winsorize ±3σ 截断）
        # 报告应显示标准化值而非原始值，避免比率型因子原始极端值误导用户
        # 如 momentum_strength 原始值=-9.08 看似极端，但标准化 z=-2.65，有效贡献仅 2%×-2.65
        factor_values_std = {}
        for col in factor_cols:
            if col in row:
                val = row[col]
                # 问题 1 修复：只判 pd.isna，EPSILON 不该用于数值合法性判断
                if pd.isna(val):
                    factor_values[col] = None
                else:
                    factor_values[col] = convert_to_native_types(val)
            # 标准化值（_std 列由 standardize_factors 生成，经 Winsorize ±3σ 截断）
            std_col = f"{col}_std"
            if std_col in row:
                std_val = row[std_col]
                if pd.isna(std_val):
                    factor_values_std[col] = None
                else:
                    factor_values_std[col] = round(convert_to_native_types(std_val), 4)

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

    return result_list, excluded_by_amplitude, excluded_by_coverage


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


def save_result(
    result: dict[str, Any],
    output_dir: Path | str,
    logger: logging.Logger | None = None,
) -> Path:
    """保存结果到 JSON 文件

    Args:
        result: 结果字典
        output_dir: 输出目录（Path 或 str）
        logger: 日志对象（默认使用模块级 _logger）

    Returns:
        输出文件路径

    Note:
        - 输出文件名: stock_selection_result.json
        - 遵循 MODULE.md M4: 输出到 comprehensive_factor/result/
    """
    if logger is None:
        logger = _logger

    # 转换为 Path
    output_dir = Path(output_dir)

    # 确保输出目录存在
    output_dir.mkdir(parents=True, exist_ok=True)

    # 输出文件名（固定）
    output_file = output_dir / "stock_selection_result.json"

    # 保存 JSON
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    logger.info("结果已保存: %s", output_file)

    return output_file


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
        Tuple[result_dict, output_file_path]

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
    logger.info("加载因子数据...")
    factor_df_raw = load_factor_values(factor_cols, config.data_source, logger)
    # 类型转换：load_factor_values 返回 DataFrame（pandas DataFrame 构造返回类型不稳定）
    factor_df = cast(pd.DataFrame, factor_df_raw)

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

    # 问题 2 修复：变量名改为 stocks_on_date，避免误解为"全部股票数"
    stocks_on_date = len(factor_df)
    logger.info("选股日期股票数: %d", stocks_on_date)

    # Step 7: 标准化因子（截面标准化）
    # 注意：单日数据标准化时，每日截面就是当日所有股票
    logger.info("标准化因子...")
    factor_df = standardize_factors(factor_df, factor_cols, logger)

    # Step 7.5: 方向统一化（遵循 MODULE.md M56）
    # 正向因子 (ic_mean>0) 标准化值取反，统一为负向语义
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
            if ic_mean_val > 0:
                direction_map[factor_name] = "positive"
                factor_df[std_col] = -factor_df[std_col]
                flipped_factors.append(factor_name)
                logger.info(
                    "因子 %s ic_mean=%.4f>0（正向因子），标准化值已取反以统一负向语义",
                    factor_name,
                    ic_mean_val,
                )
            else:
                direction_map[factor_name] = "negative"
    else:
        # 使用从 composite 读取的 direction_map 执行取反
        for i, col in enumerate(factor_cols):
            factor_name = factor_list[i] if i < len(factor_list) else col
            direction = direction_map.get(factor_name, "unknown")

            std_col = f"{col}_std"
            if direction == "positive":
                factor_df[std_col] = -factor_df[std_col]
                logger.info(
                    "因子 %s（正向因子），标准化值已取反以统一负向语义",
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
        except (json.JSONDecodeError, KeyError):
            logger.warning("无法从 composite 结果读取 short_sample_factors，跳过惩罚")

    logger.info("计算综合因子（权重方法: %s）...", best_method)
    weight_engine = WeightEngine(weight_method=best_method, window=config.rolling_window, logger=logger)
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

    top_stocks, excluded_by_amplitude, excluded_by_coverage = sort_and_select(
        composite_factor,
        factor_df,
        config.top_n,
        config.factor_direction,
        factor_cols,
        weights=selection_weights,  # v1.10: 传入权重用于覆盖率过滤
        min_amplitude=config.min_amplitude,  # v1.12: 传入振幅阈值
        logger=logger,
    )

    # Step 11: 构建结果（问题 5 修复：传递运行时变量）
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
        logger=logger,
    )

    # Step 12: 保存结果
    # 问题 3 修复：__post_init__ 已处理路径默认值，无需运行时校验
    output_file = save_result(result, config.output_dir, logger)

    # 问题 4 修复：删除流程完成日志，让 CLI 层的成功日志兼任收尾
    return result, output_file


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
            default=10,
            help="选出前 N 只股票（默认: 10）",
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
            default="negative",
            help="因子方向（默认: negative，反向因子）",
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
            result, output_file = select_stocks(config, logger)
            logger.info("选股成功！输出文件: %s", output_file)
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
