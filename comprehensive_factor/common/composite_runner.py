"""
综合因子公共入口模块

功能:
1. 加载因子数据和IC结果
2. 标准化因子值
3. 计算综合因子（调用 weight_engine）
4. 调用 backtest 分层回测（复用 run_layered_backtest）
5. 保存结果

设计参考:
- factor_ic/common/factor_ic_runner.py
- backtest/common/layered_backtest_runner.py

作者: 云瑶
创建日期: 2026-05-24

版本历史:
    v2.7: 2026-05-27 移除 cache_dir 参数，改为统一数据源 data_source
    v2.8: 2026-05-28 新增 --auto_select 参数，支持自动因子筛选
    v2.9: 2026-05-28 新增 selection_result 字段保存筛选详细原因（解决"原因未知"问题）
    v2.15: 2026-06-11 Rolling ICIR last_day_weights 回退 ICIR 静态权重（修复空字典→覆盖率100%假象）
    v2.16: 2026-06-11 Rolling ICIR last_day_weights 修复 Pitfall #45：方案A/B均返回等权→改用 _last_day_weights 属性读取真实权重
    v2.17: 2026-06-13 单一映射来源（方案 B）
        - 删除 select_factors.__globals__.get(...) 反射调用
        - 改为显式 from factor_definitions import FACTOR_NAME_TO_COL_MAP, FACTOR_COL_TO_NAME_MAP
        - 详见 designs/factor_name_col_map_unification_design.md §3.4
"""

import gzip
import json
import logging
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import ClassVar, Optional

import pandas as pd
from comprehensive_factor.common.factor_loader import (
    calc_factor_correlation,
    load_full_data,
    load_ic_daily,
    load_ic_results,
    standardize_factors,
)

# 导入公共模块
from comprehensive_factor.common.logger_config import get_logger
from comprehensive_factor.common.weight_engine import ICIRWeightMethod, RollingICIRWeightMethod, WeightEngine

# v2.17: 单一映射来源（方案 B）
# factor_definitions 位于项目根（与 factor_selector / weight_engine 同模式：
# 调用方已在 sys.path 中包含项目根），故可在 sys.path 注入之前 import
from factor_definitions import FACTOR_CATEGORIES, FACTOR_COL_TO_NAME_MAP, FACTOR_NAME_TO_COL_MAP


# 导入 backtest 公共模块（跨模块调用，但通过函数接口）
# 修复：添加重复插入检查，避免多次 import 时路径重复污染
# 注：backtest 不在常规 sys.path（comprehensive_factor 包外），需先注入项目根
_project_root = str(Path(__file__).parent.parent.parent)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

# E402 noqa: 必须延后到 sys.path 注入之后（运行时依赖动态路径）
from backtest.common.convert_types import convert_to_native_types as backtest_convert  # noqa: E402
from backtest.common.layered_backtest import LayeredBacktestEngine  # noqa: E402
from backtest.common.layered_backtest_runner import LayerConfigBase  # noqa: E402


# ============================================================================
# Config 基类
# ============================================================================


@dataclass
class CompositeLayerConfig(LayerConfigBase):
    """综合因子分层配置

    综合因子默认为反向因子（低值预期高收益），
    因为低相关性组合中流动性因子（缩量）+ 技术指标（超卖）都指向反向逻辑。

    扩展参数：
    - factor_list: 因子名称列表
    - factor_cols: 因子列名列表
    - rolling_window: 滚动ICIR窗口

    注意：
    - 子类必须声明 factor_name ClassVar（继承自 LayerConfigBase 的要求）
    - factor_name 用于日志和结果文件命名
    - 综合因子不加载单独 IC 文件，factor_direction 固定为 'negative'
    """

    # === 因子元数据（子类必须声明，满足 LayerConfigBase 要求） ===
    factor_name: ClassVar[str] = "composite"  # 子类应覆盖，如 'ic_weight_composite'
    factor_col: ClassVar[str] = ""  # 综合因子无单列，由 weight_method 决定
    layer_names: ClassVar[Sequence[str]] = ("lowest", "lower", "normal", "higher", "highest")
    layer_descriptions: ClassVar[Sequence[str]] = (
        "极低层(综合因子值最小)",
        "偏低层(综合因子值偏小)",
        "正常层(综合因子值中等)",
        "偏高层(综合因子值偏大)",
        "极高层(综合因子值最大)",
    )

    # v2.12: 因子组合参数默认值改为 None，由 auto_select 筛选决定
    # 旧值 ['rsi', 'volume_ratio'] 是测试配置，不适合生产使用
    # 当 auto_select=True 时，select_factors() 决定因子列表
    # 当 auto_select=False 时，必须手动指定 factor_list（否则 ValueError）
    factor_list: list[str] | None = None
    factor_cols: list[str] | None = None
    rolling_window: int = 60

    def __post_init__(self):
        """综合因子特殊处理：跳过 IC 文件加载，固定 factor_direction"""
        # 1. 校验 factor_name
        if not self.factor_name:
            raise ValueError(f"子类必须声明 factor_name ClassVar，当前类: {self.__class__.__name__}")

        # 2. 综合因子不加载 IC 文件，factor_direction 固定为 'negative'
        self.factor_direction = "negative"
        self.ic_source_resolved = ""  # 综合因子无单独 IC 文件

        # 3. 派生 factor_col_resolved
        cls_factor_col = self.__class__.factor_col
        self.factor_col_resolved = cls_factor_col if cls_factor_col else self.factor_name

        # 4. 校验 layer_names
        n = len(self.layer_names)
        if n < 2:
            raise ValueError(f"layer_names 至少需要 2 层，当前: {n}")
        self.n_layers = n

        # 5. 生成 layer_names_dict
        descriptions = self.__class__.layer_descriptions
        if descriptions and len(descriptions) == n:
            self.layer_names_dict = {str(i + 1): desc for i, desc in enumerate(descriptions)}
        else:
            self.layer_names_dict = {str(i + 1): name for i, name in enumerate(self.layer_names)}

        # 6. 派生多空组合
        if self.long_layers is None or self.short_layers is None:
            # 综合因子默认反向：低值做多，高值做空
            self.long_layers = [1, 2]
            self.short_layers = [4, 5]

    def validate(self) -> None:
        """校验配置完整性

        v2.12: factor_list/factor_cols 允许为 None（由 auto_select 筛选决定），
        仅当两者都有值时校验数量一致性。
        """
        super().validate()  # 调用父类校验

        # v2.12: factor_list/factor_cols 允许为 None（由 auto_select 筛选决定）
        if self.factor_list is None and self.factor_cols is None:
            return  # auto_select 模式，因子列表由筛选决定

        if not self.factor_list:
            raise ValueError("factor_list 不能为空（非 auto_select 模式需手动指定）")

        if not self.factor_cols:
            raise ValueError("factor_cols 不能为空（非 auto_select 模式需手动指定）")

        if len(self.factor_list) != len(self.factor_cols):
            raise ValueError(
                f"factor_list ({len(self.factor_list)}) 与 factor_cols ({len(self.factor_cols)}) 数量不一致"
            )


# ============================================================================
# 公共入口函数
# ============================================================================


def run_composite_backtest(
    weight_method: str = "equal_weight",
    factor_list: list[str] | None = None,  # 可选，如为None则自动筛选
    factor_cols: list[str] | None = None,  # 可选，如为None则自动筛选
    config: Optional["CompositeLayerConfig"] = None,
    return_period: str = "1d",
    data_source: str | Path | None = None,
    ic_result_dir: str | None = None,
    backtest_result_dir: str | None = None,
    output_dir: str | Path | None = None,  # 修复：支持 str 或 Path，入口统一转换
    auto_select: bool = False,  # 是否自动筛选因子
    thresholds: dict | None = None,  # 筛选阈值配置
    dimension_weight_method: str | None = None,  # v1.20: 维度级别权重分配 (none/equal/icir)
    verbose: bool = True,
    logger: logging.Logger | None = None,
) -> dict:
    """综合因子分层回测公共入口

    Args:
        weight_method: 加权方式（equal_weight/icir_weight/ic_weight/rolling_icir_weight）
        factor_list: 因子名称列表（用于加载IC结果），如为None且auto_select=True则自动筛选
        factor_cols: 因子列名列表（用于加载因子值），如为None且auto_select=True则自动筛选
        config: 分层配置对象
        return_period: 收益周期
        data_source: 数据源文件路径（可选，默认使用 DEFAULT_DATA_SOURCE）
        ic_result_dir: IC结果目录
        backtest_result_dir: 回测结果目录
        output_dir: 输出目录（支持 str 或 Path，入口统一转换为 Path）
        auto_select: 是否自动筛选因子（Step 2自动化）
        thresholds: 筛选阈值配置（如未提供则使用默认值）
        verbose: 是否打印详细信息
        logger: 日志对象

    Returns:
        回测结果字典

    更新历史（2026-05-27）：
        - v2.7: 移除 cache_dir 参数，改为统一数据源 data_source
    """
    if logger is None:
        logger = get_logger(__name__)

    # 修复：入口统一转换类型，处理所有情况（包括 None）
    if output_dir is None:
        # 默认输出目录
        project_root = Path(__file__).parent.parent.parent
        output_dir = project_root / "comprehensive_factor" / "result"
    else:
        output_dir = Path(output_dir)

    # 创建默认配置（如果未传入）
    if config is None:
        config = CompositeLayerConfig()

    # 校验配置
    config.validate()

    logger.info("=" * 40)
    logger.info("综合因子分层回测 [%s]", weight_method)
    logger.info("=" * 40)

    # ====================================================================
    # Step 0: 一次性加载统一数据源（消除三次重复加载）
    # ====================================================================
    # v2.10: 原流程中 load_factor_values（Step 2）+ load_factor_values（Step 1）
    #        + load_factor_return_data（Step 8）各自独立读取 216MB gzip JSON，
    #        每次解析耗时 ~22s，三次共计 ~66s，是综合因子脚本超时失败的根因。
    #        修复：入口处一次性加载 full_df，后续步骤从中提取子集。
    full_df = load_full_data(data_source=data_source, logger=logger)

    # ====================================================================
    # Step 2: 自动筛选因子（如果启用）
    # ====================================================================
    # v2.12: auto_select=True 时 factor_list=None（由 CLI 入口决定），
    #   筛选直接决定 factor_list，无需"仅记录"分支。
    #   auto_select=False 时 factor_list 有值，跳过筛选。
    selection_result = None

    if auto_select:
        from comprehensive_factor.common.factor_selector import select_factors

        logger.info("启用自动因子筛选（筛选决定因子列表）...")

        # v2.8: 先加载所有因子数据用于计算相关性矩阵
        # 修复：select_factors 需要 corr_matrix 进行高相关筛选
        logger.info("加载所有因子数据用于相关性计算...")

        # v2.17: 单一映射来源（方案 B）—— 直接使用 factor_definitions 模块级常量
        # 历史反射 select_factors.__globals__.get(...) 已替换为显式 import
        all_factor_cols = list(FACTOR_NAME_TO_COL_MAP.values())

        # v2.10: 从 full_df 提取子集，不再独立调用 load_factor_values
        required_all_cols = ["date", "asset"] + [c for c in all_factor_cols if c in full_df.columns]
        missing_all_cols = [c for c in all_factor_cols if c not in full_df.columns]
        if missing_all_cols:
            logger.warning("全量因子列缺失（将从 full_df 跳过）: %s", missing_all_cols)
        all_factor_df = full_df[required_all_cols].copy()

        # v2.28b: 提前提取 return_df + 释放 full_df（OOM 修复第二轮）
        # 原代码 full_df 在 auto_select 阶段仍驻留 ~0.5GB，叠加 all_factor_df ~1GB = 1.5GB+
        # icir_weight 等脚本因系统可用内存更低（~2.1GB anon-rss）仍被 OOM Kill
        # 现在提取 return_df 后立即释放 full_df，auto_select 阶段峰值降至 ~1GB
        return_cols = ["date", "asset", "forward_return_1d", "forward_return_3d", "forward_return_5d"]
        for col in ["forward_return_1d", "forward_return_3d", "forward_return_5d"]:
            if col not in full_df.columns:
                raise ValueError(f"full_df 中缺少收益列 '{col}', 当前列: {list(full_df.columns)}")
        return_df = full_df[return_cols].copy()
        logger.info("收益数据（从 full_df 提取）: %d 条记录", len(return_df))

        del full_df
        import gc
        gc.collect()
        logger.info("full_df 已释放（v2.28b: auto_select 阶段提前释放）")

        # v2.28b: 因子列缺失过滤必须在 full_df 释放前执行
        # select_factors 返回的 factor_cols 可能包含不在数据中的列名（如 return_3d）
        if factor_cols is not None and factor_list is not None:
            # all_factor_df 此时仍持有，可从中检查列名
            # 但 factor_cols 是逻辑列名到数据列名的映射，检查数据列名是否在 all_factor_cols 中
            available_cols = all_factor_cols  # auto_select 可用的因子列
            missing_data_cols = [c for c in factor_cols if c not in available_cols]
            if missing_data_cols:
                kept_pairs = [(f, c) for f, c in zip(factor_list, factor_cols) if c in available_cols]
                skipped_factors = [f for f, c in zip(factor_list, factor_cols) if c not in available_cols]
                factor_list = [f for f, _ in kept_pairs]
                factor_cols = [c for _, c in kept_pairs]
                logger.warning("因子数据列缺失，从复合因子计算中跳过: %s", skipped_factors)

        # v2.23: 修复 pre-existing bug —— 缺失列被从 all_factor_df 过滤后，
        #   后续 standardize_factors / calc_factor_correlation 仍引用原 all_factor_cols
        #   会触发 KeyError。改为只对实际可用的因子列做下游处理。
        #   v2.28b: full_df 已释放，改用 all_factor_df.columns 替代 full_df.columns
        all_factor_cols = [c for c in all_factor_cols if c in all_factor_df.columns]

        # v2.8: 先标准化因子，再计算相关性
        logger.info("标准化所有因子值...")
        all_factor_df = standardize_factors(all_factor_df, all_factor_cols, logger, skip_point_mass=True)

        # 计算相关性矩阵
        logger.info("计算所有因子相关性矩阵...")
        all_corr_matrix = calc_factor_correlation(all_factor_df, all_factor_cols, logger)

        # v2.8: 转换相关性矩阵索引从列名到因子逻辑名
        # 原因：select_factors 的 valid_factors 使用因子逻辑名（如 'rsi'）
        #       corr_matrix 使用数据列名（如 'rsi_6'），需要映射
        # v2.17: 单一映射来源（方案 B）—— 直接使用 factor_definitions 反向映射
        col_to_name_map = FACTOR_COL_TO_NAME_MAP
        all_corr_matrix_renamed = all_corr_matrix.rename(index=col_to_name_map, columns=col_to_name_map)

        # 调用 select_factors（传入相关性矩阵）
        selection_result = select_factors(
            ic_result_dir=Path(ic_result_dir) if ic_result_dir else None,
            backtest_result_dir=Path(backtest_result_dir) if backtest_result_dir else None,
            corr_matrix=all_corr_matrix_renamed,  # v2.8: 传入重命名后的相关性矩阵
            thresholds=thresholds,
            logger=logger,
        )

        # 根据筛选结果设置 factor_list
        factor_list = selection_result["selected"]

        # 使用 select_factors 返回的 factor_cols 映射（已从 FACTOR_NAME_TO_COL_MAP 获取）
        # 修复：不再直接赋值 factor_cols = factor_list，避免列名不匹配
        factor_cols = selection_result.get("factor_cols", factor_list)

        # 检查未映射因子警告
        unmapped = selection_result.get("unmapped_factors", [])
        if unmapped:
            logger.warning("以下因子未找到列名映射，可能导致数据加载失败: %s", unmapped)

        logger.info("自动筛选完成: %s → %s", factor_list, factor_cols)

        # v2.28b: 从 all_factor_df 提取选中因子子集，再释放中间数据
        # 不再 del all_factor_df 后重新加载 full_df（full_df 已在 L287 释放）
        factor_selected_cols = ["date", "asset"] + factor_cols
        factor_df = all_factor_df[factor_selected_cols].copy()
        logger.info("选中因子数据已从 all_factor_df 提取: %d 列 → %d 条记录", len(factor_selected_cols), len(factor_df))

        # v2.28: 释放 auto_select 中间数据（OOM 修复）
        # all_factor_df(45因子×90列~1GB) 和 all_corr_matrix 在筛选完成后不再需要，
        # 立即释放避免叠加峰值。设计依据见 designs/composite_auto_select_memory_optimization_design.md §2.1 L1
        del all_factor_df
        if all_corr_matrix is not None:
            del all_corr_matrix
        if "all_corr_matrix_renamed" in dir():
            del all_corr_matrix_renamed
        import gc

        gc.collect()
        logger.info("auto_select 中间数据已释放（all_factor_df + corr_matrix）")

    # v2.26: 过滤数据中不存在的因子列（如 return_3d 有 IC 结果但不在 factor_ic_data 中）
    # v2.28b: auto_select=True 时此过滤已在 auto_select 内部完成
    #   auto_select=False 时 full_df 仍在，需要在此处过滤
    if not auto_select and factor_cols is not None and factor_list is not None and full_df is not None:
        missing_data_cols = [c for c in factor_cols if c not in full_df.columns]
        if missing_data_cols:
            kept_pairs = [(f, c) for f, c in zip(factor_list, factor_cols) if c in full_df.columns]
            skipped_factors = [f for f, c in zip(factor_list, factor_cols) if c not in full_df.columns]
            factor_list = [f for f, _ in kept_pairs]
            factor_cols = [c for _, c in kept_pairs]
            logger.warning("因子数据列缺失，从复合因子计算中跳过: %s", skipped_factors)

    # 如果仍未指定，使用默认配置
    if factor_list is None:
        raise ValueError("factor_list 未指定\n请设置 auto_select=True 启用自动筛选，或手动传入 factor_list")

    if factor_cols is None:
        factor_cols = factor_list

    if verbose:
        logger.info("配置信息:")
        logger.info("  加权方式: %s", weight_method)
        logger.info("  因子列表: %s", factor_list)
        logger.info("  因子方向: %s", config.factor_direction)
        logger.info("  分层数量: %d (percentile)", config.n_layers)
        logger.info("  多头组合: Layer %s", config.long_layers)
        logger.info("  空头组合: Layer %s", config.short_layers)
        if auto_select:
            logger.info("  自动筛选: 启用")

    # 1. 加载因子数据
    # v2.28b: auto_select=True 时 factor_df 和 return_df 已在 auto_select 内部提取，full_df 已释放
    #   auto_select=False 时需要从 full_df 提取 factor_df 和 return_df，然后释放 full_df
    if not auto_select:
        logger.info("提取因子数据（从已加载的 full_df）...")
        factor_required_cols = ["date", "asset"] + factor_cols
        factor_df = full_df[factor_required_cols].copy()

        # 提取 return_df + 释放 full_df
        return_cols = ["date", "asset", "forward_return_1d", "forward_return_3d", "forward_return_5d"]
        for col in ["forward_return_1d", "forward_return_3d", "forward_return_5d"]:
            if col not in full_df.columns:
                raise ValueError(f"full_df 中缺少收益列 '{col}', 当前列: {list(full_df.columns)}")
        return_df = full_df[return_cols].copy()
        logger.info("收益数据（从 full_df 提取）: %d 条记录", len(return_df))
        if len(return_df) == 0:
            raise ValueError(
                "return_df 为空 DataFrame（有列名但无数据），无法进行分层回测\n"
                "可能原因：\n"
                "  1. full_df 数据为空\n"
                "  2. 数据加载异常（检查 load_full_data()）\n"
                f"  当前列: {list(return_df.columns)}"
            )
        if "forward_return_1d" not in return_df.columns:
            raise ValueError(f"return_df 缺少 'forward_return_1d' 列，当前列: {list(return_df.columns)}")

        del full_df
        import gc
        gc.collect()
        logger.info("full_df 已释放（v2.28b: auto_select=False 分支释放）")
    else:
        logger.info("因子数据已从 auto_select 内部提取，无需重新加载")

    # 2. 加载 IC 结果
    logger.info("加载 IC 结果...")
    ic_results, missing_ic_factors = load_ic_results(
        factor_names=factor_list, ic_result_dir=ic_result_dir, return_period=return_period, logger=logger
    )

    # 修复：检查缺失因子，避免后续计算 KeyError
    if missing_ic_factors:
        logger.warning("部分因子 IC 结果缺失，权重计算将回退等权: %s", missing_ic_factors)

    # 3. 加载 IC 每日数据（滚动ICIR需要）
    ic_daily_data = None
    if weight_method == "rolling_icir_weight":
        logger.info("加载 IC 每日数据...")
        ic_daily_data = load_ic_daily(
            factor_names=factor_list, ic_result_dir=ic_result_dir, return_period=return_period, logger=logger
        )

    # 4. 标准化因子
    logger.info("标准化因子值...")
    factor_df = standardize_factors(factor_df, factor_cols, logger)

    # 修复：列校验前置，放在 standardize 之后、calculate 之前
    # 校验必需列存在性（防御性编程）
    required_cols = ["date", "asset"]
    for col in required_cols:
        if col not in factor_df.columns:
            raise ValueError(f"factor_df 缺少必需列 '{col}'，当前列: {list(factor_df.columns)}")

    # 校验因子列存在性
    for col in factor_cols:
        if col not in factor_df.columns:
            raise ValueError(f"factor_df 缺少因子列 '{col}'，当前列: {list(factor_df.columns)}")

    # 校验标准化因子列存在性（standardize_factors 生成 *_std 列）
    std_cols = [f"{col}_std" for col in factor_cols]
    for col in std_cols:
        if col not in factor_df.columns:
            raise ValueError(
                f"factor_df 缺少标准化因子列 '{col}'，当前列: {list(factor_df.columns)}\n"
                "可能原因：standardize_factors 未正确生成标准化列"
            )

    # 5. 因子方向统一化（正向因子取反，使所有因子统一为负向语义）
    # v2.13: 正向因子（ic_mean > 0）在负向因子组合中信号方向相反，
    #   直接加权会抵消信号。取反后所有因子统一为负向语义：
    #   标准化正值=差信号 → 综合因子低值=好信号 → factor_direction='negative'
    direction_map = {}  # {factor_name: 'negative'|'positive'|'unknown'}
    flipped_factors = []

    for i, col in enumerate(factor_cols):
        # 通过 factor_list[i] 查找对应的因子逻辑名
        factor_name = factor_list[i] if i < len(factor_list) else col

        # 从 ic_results 中读取 ic_mean 方向
        ic_info = ic_results.get(factor_name, {})
        ic_mean_val = ic_info.get("ic_mean", None)

        if ic_mean_val is None:
            # IC 数据缺失，无法判断方向
            direction_map[factor_name] = "unknown"
            logger.warning("因子 %s IC均值缺失，无法判断方向，保持原值", factor_name)
            continue

        std_col = f"{col}_std"
        if ic_mean_val > 0:
            # 正向因子：取反标准化值，使其统一为负向语义
            direction_map[factor_name] = "positive"
            factor_df[std_col] = -factor_df[std_col]
            flipped_factors.append(factor_name)
            logger.info("因子 %s ic_mean=%.4f>0（正向因子），标准化值已取反以统一负向语义", factor_name, ic_mean_val)
        else:
            # 负向因子：保持不变
            direction_map[factor_name] = "negative"

    if flipped_factors:
        logger.info(
            "方向统一化完成: %d 个正向因子已取反 (%s)，所有因子统一为负向语义", len(flipped_factors), flipped_factors
        )

    # 5b. 计算因子相关性（基于方向统一化后的数据）
    logger.info("计算因子相关性...")
    corr_matrix = calc_factor_correlation(factor_df, factor_cols, logger)

    # 检查高相关性因子
    high_corr_pairs = []
    nan_corr_pairs = []  # 新增：NaN相关性记录（缺失值过多导致的异常）

    for i in range(len(factor_cols)):
        for j in range(i + 1, len(factor_cols)):
            corr_val = corr_matrix.loc[factor_cols[i], factor_cols[j]]

            # 修复：显式处理 NaN（缺失值过多导致的异常相关性）
            if pd.isna(corr_val):
                nan_corr_pairs.append(
                    {
                        "factor_a": factor_cols[i],
                        "factor_b": factor_cols[j],
                        "reason": "NaN（缺失值过多导致相关性无法计算）",
                    }
                )
                logger.warning(
                    "相关性 NaN 警告: %s vs %s，缺失值过多导致相关性无法计算", factor_cols[i], factor_cols[j]
                )
                continue  # 跳过 NaN，不判断高相关性

            # 正常相关性判断
            if abs(corr_val) > 0.7:
                high_corr_pairs.append(
                    {
                        "factor_a": factor_cols[i],
                        "factor_b": factor_cols[j],
                        "corr": float(corr_val),  # 显式转为 float，避免 numpy 类型
                    }
                )
                logger.warning(
                    "高相关因子警告: %s vs %s, corr=%.2f，建议只选其一", factor_cols[i], factor_cols[j], corr_val
                )

    # 6. 计算综合因子
    logger.info("计算综合因子 [%s]...", weight_method)

    # v2.14: 提取 short_sample_factors（从 selection_result 或 auto_select 流程获取）
    # 短样本因子 ICIR 权重惩罚：18天因子惩罚系数=18/30=0.6，权重从27.1%降至约16.3%
    # 修复：原代码未传递 short_sample_factors，导致 weight_engine v1.15 惩罚代码从未执行
    short_sample_factors = None
    if selection_result is not None:
        short_sample_factors = selection_result.get("short_sample_factors", {})

    if short_sample_factors:
        logger.info(
            "短样本因子ICIR权重惩罚: %s（惩罚系数=valid_days/30）",
            {k: f"×{v}/30={v / 30:.2f}" for k, v in short_sample_factors.items()},
        )

    # v1.20: 透传维度权重分配参数
    weight_engine = WeightEngine(
        weight_method=weight_method,
        window=config.rolling_window,
        logger=logger,
        dimension_weight_method=dimension_weight_method,
        factor_categories=FACTOR_CATEGORIES if dimension_weight_method else None,
    )

    composite_factor = weight_engine.calculate(
        factor_df=factor_df,
        factor_cols=factor_cols,
        ic_results=ic_results,
        ic_daily_data=ic_daily_data,
        short_sample_factors=short_sample_factors,  # v2.14: 传入短样本因子信息
    )

    # 添加综合因子到 factor_df
    factor_df["composite_factor"] = composite_factor

    # 修复：检查 composite_factor 全为 NaN 的情况
    valid_composite_count = factor_df["composite_factor"].notna().sum()
    if valid_composite_count == 0:
        raise ValueError(
            "composite_factor 全为 NaN，无法进行分层回测\n"
            "可能原因：\n"
            "  1. 所有因子值缺失（检查 factor_cols 是否正确）\n"
            "  2. 标准化后全为 NaN（检查原始数据覆盖率）\n"
            "  3. 加权计算异常（检查 weight_engine.calculate()）"
        )

    # 7. 获取权重（修复：元信息与权重数据分离）
    # 区分静态权重和动态权重
    if weight_method == "rolling_icir_weight":
        # 滚动ICIR权重是每日动态计算的，无法用固定字典表达
        weights = {}  # 权重字典为空（动态权重不保存静态值）

        # v2.10→v2.16: 从 RollingICIRWeightMethod._last_day_weights 读取最新日期权重
        # v2.15 的方案A/B 均有 Bug（Pitfall #45）：
        #   方案A：factor_df 无 rolling_icir 列（calculate 内部 copy 不保留）→ 永远跳过
        #   方案B：调用 weight_engine.get_weights() → 但 weight_method=rolling_icir_weight
        #     → 调用 RollingICIRWeightMethod.get_weights() → 返回等权 1/n（不是真实权重）
        #   导致报告显示所有因子各占 12.5%，与等权完全一致。
        # v2.16 修复：RollingICIRWeightMethod.calculate()（weight_engine v1.18）在内部
        #   提取最后一日真实权重存入 _last_day_weights 属性，此处直接读取。
        last_day_weights = {}

        if isinstance(weight_engine.method, RollingICIRWeightMethod) and weight_engine.method._last_day_weights:
            last_day_weights = weight_engine.method._last_day_weights
            logger.info(
                "Rolling ICIR: 读取 _last_day_weights（真实滚动ICIR权重）: %s",
                {k: f"{v:.2%}" for k, v in last_day_weights.items()},
            )
        else:
            # 回退：使用 ICIR 静态权重（v2.15→v2.16：直接创建 ICIRWeightMethod）
            # v2.15 的 Bug：weight_engine.get_weights() 对 rolling_icir_weight 返回等权，
            #   不是 ICIR 静态权重。v2.16 修复：直接使用 ICIRWeightMethod。
            logger.info("Rolling ICIR: _last_day_weights 为空, 回退使用 ICIR 静态权重")
            icir_method = ICIRWeightMethod(logger=logger)
            icir_fallback = icir_method.get_weights(factor_cols, ic_results, short_sample_factors)
            if icir_fallback:
                last_day_weights = icir_fallback
                logger.info("ICIR 静态权重 fallback: %s", {k: f"{v:.2%}" for k, v in icir_fallback.items()})
            else:
                # 最终回退：等权
                for col in factor_cols:
                    last_day_weights[col] = 1.0 / len(factor_cols)
                logger.warning("ICIR 静态权重也为空，使用等权 fallback")

        weight_meta = {
            "is_dynamic": True,
            "method": "rolling_icir_weight",
            "window": config.rolling_window,
            "note": "权重每日动态计算，不保存静态值",
            "last_day_weights": last_day_weights,  # v2.16: 读取 calculate() 内的真实权重
            "dimension_weight_method": dimension_weight_method,  # v1.20: 维度权重分配方式
        }
        logger.info("滚动ICIR加权: 权重每日动态计算（窗口 %d 日），不保存静态权重", config.rolling_window)
        if last_day_weights:
            logger.info("最后一日权重: %s", {k: f"{v:.2%}" for k, v in last_day_weights.items()})
    else:
        # 静态权重方法（equal_weight、icir_weight、ic_weight）
        weights = weight_engine.get_weights(factor_cols, ic_results, short_sample_factors)  # v2.14: 传入短样本因子信息
        weight_meta = {"is_dynamic": False, "method": weight_method}
        logger.info("静态权重获取完成: %s", weights)

    if verbose:
        logger.info("因子权重:")
        if weight_meta["is_dynamic"]:
            logger.info("  %s（每日动态计算，窗口 %d 日）", weight_meta["method"], weight_meta["window"])
        else:
            for col, w in weights.items():
                logger.info("  %s: %.4f", col, w)

        logger.info("数据统计:")
        logger.info("  日期范围: %s ~ %s", factor_df["date"].min(), factor_df["date"].max())
        logger.info("  股票数量: %d", factor_df["asset"].nunique())
        valid_composite = factor_df["composite_factor"].dropna()
        if len(valid_composite) > 0:
            logger.info("  综合因子范围: %.2f ~ %.2f", valid_composite.min(), valid_composite.max())

    # 8. 调用 backtest 分层回测
    logger.info("调用 backtest 分层回测...")

    # v2.28: return_df 已在 Step 1 提取、full_df 已释放，此处直接使用已提取的 return_df

    # 创建回测引擎（直接传入已计算的综合因子）
    logger.info("创建回测引擎...")
    engine = LayeredBacktestEngine(
        factor_df=factor_df,
        return_df=return_df,
        factor_col="composite_factor",
        return_col="forward_return_1d",
        date_col="date",
        asset_col="asset",
    )

    # 执行分层回测
    logger.info("执行分层回测...")
    result = engine.run(
        layer_method="percentile",
        n_layers=config.n_layers,
        factor_direction=config.factor_direction,
        long_layers=config.long_layers,
        short_layers=config.short_layers,
        min_stocks_per_layer=config.min_stocks_per_layer,
        trade_cost_rate=config.trade_cost_rate,
    )

    # 添加元信息
    result["meta"]["factor_name"] = f"{weight_method}_composite"

    # 生成报告
    report = engine.generate_report(result)
    logger.info(report)

    # 9. 保存综合因子结果
    # output_dir 已在入口统一转换（包括 None 默认值），无需再次处理
    output_dir.mkdir(parents=True, exist_ok=True)

    output_file = output_dir / f"composite_{weight_method}_{return_period}.json"

    # 构建输出数据
    # v2.9: 新增 selection_result 字段，保存因子筛选的详细原因（invalid + high_corr_dropped）
    # 解决 generate_factor_summary_report.py 显示"原因未知"的问题
    output_data = {
        "meta": {
            "weight_method": weight_method,
            "return_period": return_period,
            "factor_list": factor_list,
            "factor_cols": factor_cols,
            "weights": weights,  # 权重数据（动态权重时为空字典）
            "weight_meta": weight_meta,  # 新增：权重元信息（与权重数据分离）
            "selection_result": selection_result,  # v2.12: 始终写入筛选结果（auto_select=True 时有值）
            "ic_results": {
                name: {
                    "ic_mean": ic_results.get(name, {}).get("ic_mean"),
                    "icir": ic_results.get(name, {}).get("icir"),
                    "ic_std": ic_results.get(name, {}).get("ic_std"),
                }
                for name in factor_list
            },
            "correlation_matrix": backtest_convert(corr_matrix.to_dict()),
            "high_corr_pairs": high_corr_pairs,  # 已改为字典列表格式
            "nan_corr_pairs": nan_corr_pairs,  # 新增：NaN相关性记录
            "n_factors": len(factor_cols),
            "n_days": result.get("meta", {}).get("n_days_total", 0),
        },
        "backtest_result": {
            "meta": result.get("meta", {}),
            "layer_stats": result.get("layer_stats", []),
            "long_short": result.get("long_short", {}),
            "monotonicity": result.get("monotonicity", {}),
            "trading_cost_analysis": result.get("trading_cost_analysis", {}),
        },
        "config": {
            "n_layers": config.n_layers,
            "factor_direction": config.factor_direction,
            "direction_map": direction_map,  # v2.13: 因子方向映射 {factor_name: 'negative'|'positive'|'unknown'}
            "flipped_factors": flipped_factors,  # v2.13: 方向已取反的因子列表
            "long_layers": config.long_layers,
            "short_layers": config.short_layers,
            "trade_cost_rate": config.trade_cost_rate,
            "min_stocks_per_layer": config.min_stocks_per_layer,
            "rolling_window": config.rolling_window,
        },
        "created_at": datetime.now().isoformat(),
    }

    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(backtest_convert(output_data), f, indent=2, ensure_ascii=False)

    logger.info("综合因子结果已保存: %s", output_file)

    # 10. 保存综合因子每日明细
    # v2.24: 流式分块写入，避免 to_dict("records") 一次性生成 1.5M dict 列表导致 OOM
    #   原实现: to_dict("records") → backtest_convert → json.dump(indent=2)
    #   三重内存峰值（dict 列表 ~750MB + 转换副本 ~750MB + JSON 字符串 ~1GB）在 7GB 系统 OOM
    #   修复: 分块处理（5000行/块），逐块转换+写入，峰值内存 ~5MB
    # 校验输出必需列（防御性编程）
    output_cols = ["date", "asset", "composite_factor"] + factor_cols
    missing_cols = [col for col in output_cols if col not in factor_df.columns]
    if missing_cols:
        raise ValueError(f"factor_df 缺少输出必需列: {missing_cols}, 当前列: {list(factor_df.columns)}")

    daily_file = output_dir / f"composite_{weight_method}_{return_period}_daily.json.gz"
    _DAILY_CHUNK_SIZE = 5000

    with gzip.open(daily_file, "wt", encoding="utf-8") as f:
        f.write('{"meta": ')
        json.dump(
            {"weight_method": weight_method, "columns": output_cols},
            f,
            ensure_ascii=False,
        )
        f.write(', "data": [')

        first_record = True
        for i in range(0, len(factor_df), _DAILY_CHUNK_SIZE):
            chunk = factor_df[output_cols].iloc[i : i + _DAILY_CHUNK_SIZE]
            records = backtest_convert(chunk.to_dict("records"))
            for record in records:
                if not first_record:
                    f.write(",")
                first_record = False
                json.dump(record, f, ensure_ascii=False)

        f.write("]}")

    logger.info("综合因子每日明细已保存: %s", daily_file)

    return output_data


# ============================================================================
# CLI 入口工厂函数
# ============================================================================


def create_cli_entrypoint(
    weight_method: str,
    config_class: type,  # v2.8: 移至前面（无默认值参数必须在前）
    factor_list: list[str] | None = None,  # v2.8: 改为 Optional，支持自动筛选
    factor_cols: list[str] | None = None,  # v2.8: 改为 Optional，支持自动筛选
    return_period: str = "1d",
    data_source: str | Path | None = None,
    ic_result_dir: str | None = None,
    backtest_result_dir: str | None = None,  # v2.8: 新增，自动筛选需要
) -> Callable[[], None]:
    """创建 CLI 入口函数

    Args:
        weight_method: 加权方式
        config_class: Config 类
        factor_list: 因子名称列表（可选，如为None则需启用 --auto_select）
        factor_cols: 因子列名列表（可选，如为None则需启用 --auto_select）
        return_period: 收益周期
        data_source: 数据源文件路径
        ic_result_dir: IC结果目录
        backtest_result_dir: 回测结果目录（自动筛选需要）

    Returns:
        CLI 入口函数

    更新历史：
        - v2.7: 移除 cache_dir 参数，改为统一数据源 data_source
        - v2.8: 新增 --auto_select 参数，支持自动因子筛选
    """

    def main():
        import argparse

        parser = argparse.ArgumentParser(description=f"综合因子分层回测 [{weight_method}]")
        parser.add_argument("--data_source", type=str, default=data_source, help="数据源文件路径")
        parser.add_argument("--ic_result_dir", type=str, default=ic_result_dir, help="IC结果目录路径")
        parser.add_argument(
            "--backtest_result_dir", type=str, default=backtest_result_dir, help="回测结果目录路径（自动筛选需要）"
        )
        parser.add_argument("--output_dir", type=str, default=None)
        parser.add_argument("--no_auto_select", action="store_true", help="禁用自动因子筛选（使用硬编码因子列表）")
        parser.add_argument(
            "--dimension_weight",
            type=str,
            default=None,
            choices=["none", "equal", "icir"],
            help="维度级别权重分配方式 (none=不启用/equal=维度等权/icir=维度ICIR加权)，默认 none",
        )
        parser.add_argument("--quiet", action="store_true")

        args = parser.parse_args()

        logger = get_logger(__name__)

        # v2.12: 默认 auto_select=True，--no_auto_select 禁用
        # 因子列表由筛选决定（factor_list=None → select_factors 决定因子）
        use_auto_select = not args.no_auto_select  # 默认启用筛选
        if use_auto_select:
            # auto_select=True，让筛选决定因子列表
            final_factor_list = None
            final_factor_cols = None
            logger.info("auto_select 启用，因子列表由筛选决定")
        else:
            # --no_auto_select，使用硬编码因子列表（需手动指定 factor_list）
            final_factor_list = factor_list
            final_factor_cols = factor_cols
            if not factor_list:
                logger.error("--no_auto_select 模式下必须指定 factor_list")
                sys.exit(1)

        try:
            result = run_composite_backtest(
                weight_method=weight_method,
                factor_list=final_factor_list,
                factor_cols=final_factor_cols,
                config=config_class(),
                return_period=return_period,
                data_source=args.data_source,
                ic_result_dir=args.ic_result_dir,
                backtest_result_dir=args.backtest_result_dir,
                output_dir=args.output_dir,
                auto_select=use_auto_select,
                dimension_weight_method=args.dimension_weight if args.dimension_weight != "none" else None,
                verbose=not args.quiet,
                logger=logger,
            )

            # 打印关键结果
            ls_stats = result.get("backtest_result", {}).get("long_short", {})
            logger.info("=" * 40)
            logger.info("综合因子回测结果")
            logger.info("=" * 40)
            logger.info("多空年化收益: %.2f%%", ls_stats.get("long_short_return_annual", 0) * 100)
            logger.info("多空夏普比率: %.2f", ls_stats.get("long_short_sharpe", 0))
            logger.info("回测完成，退出码 0")
            sys.exit(0)  # 显式设置成功退出码

        except Exception as e:
            # 修复：保留异常堆栈信息，便于排查
            import traceback

            logger.error("回测执行异常: %s", e)
            logger.error("异常堆栈:\n%s", traceback.format_exc())
            logger.error("退出码 1（异常终止）")
            sys.exit(1)  # 显式设置失败退出码

    return main
