"""
加权计算引擎

功能:
1. 等权（Equal Weight）
2. ICIR加权（静态）
3. 滚动ICIR加权（动态）
4. IC均值加权（静态）

设计模式:
- 每种加权方式继承 WeightMethodBase
- 统一接口 calculate(factor_df, ic_results) -> composite_factor

作者: 云瑶
创建日期: 2026-05-24

版本历史:
    v1.13 (2026-06-13): 单一映射来源（方案 B）
        - 删除类内 FACTOR_NAME_TO_COL_MAP / COL_TO_FACTOR_NAME_MAP 字段
        - 改为 class-level alias 引用 factor_definitions 模块级常量
        - 修正历史 4 个错列名：kdj_j_9→kdj_j、bollinger_pb_20→bollinger_pb、
          turnover_surge_5→turnover_surge；删除死条目 main_inflow_ratio_1d
        - 正则后缀回退兜底保留
        - 详见 designs/factor_name_col_map_unification_design.md §3.3
"""

import gc
import logging
import re  # v1.11 修复：移至文件顶部（PEP 8 规范）
from abc import ABC, abstractmethod

import numpy as np
import pandas as pd
from comprehensive_factor.common.logger_config import get_logger

# v1.13: 单一映射来源（方案 B）
# 调用方（composite_runner / run_pipeline 等）已将项目根加入 sys.path
from factor_definitions import (
    FACTOR_COL_TO_NAME_MAP as _MODULE_COL_TO_NAME_MAP,
    FACTOR_FAMILIES as _MODULE_FACTOR_FAMILIES,  # v2.40: 经济同源族（用于族级 cap）
    FACTOR_NAME_TO_COL_MAP as _MODULE_NAME_TO_COL_MAP,
    FACTOR_ROLES as _MODULE_FACTOR_ROLES,  # v2.41 (R2): 角色固定权重
    PRIMARY_WEIGHT_TOTAL as _MODULE_PRIMARY_WEIGHT_TOTAL,  # v2.41 (R2): 主信号总权重锚
)


# v2.38: 单因子权重上限默认值 (design.md feat_interaction_exemption_and_weight_cap §4.3)
# 业界依据: Asness (2013) "Value and Momentum Everywhere", AQR 多因子产品经验值
# 防垄断: factor_summary_report_2026-06-22.txt 显示 amplitude_compression
#   名义 43.7% / 实际贡献 64% → 综合因子退化为单因子, 失去分散化优势
# 选择 0.25 而非 0.30: 0.30 仍允许 amplitude_compression 占 30% (design.md §8)
WEIGHT_CAP_DEFAULT = 0.25

# v2.40: 经济同源族权重上限 (design.md feat_family_weight_cap_and_liquidity_filter §3.2)
# 业界依据: AQR 多因子产品任一策略 ≤ 33%（Asness 2013）；本项目 8 族经济同源聚合
# 防族级垄断: v2.39 实测 amplitude_family (amplitude_compression 25% +
#   interaction_amp_compression 13.75%) = 38.75%，绕过维度权重再分配
# (v2.48 重构后该旧名已替换为 interaction_amp_compression__ret3d_{pos,neg,abs} 三变体)
# 选择 0.30 而非 0.25: 0.30 允许 1 个族支配但不主导，剩余 70% 分配 6-8 族
FAMILY_CAP_DEFAULT = 0.30


class WeightMethodBase(ABC):
    """加权方法基类"""

    # v1.13: 单一映射来源（方案 B）
    # FACTOR_NAME_TO_COL_MAP / COL_TO_FACTOR_NAME_MAP 已迁移至 factor_definitions
    # 这里保留 class-level alias 兼容子类/外部引用 self.FACTOR_NAME_TO_COL_MAP
    # 历史 4 个错列名（kdj_j_9 / bollinger_pb_20 / turnover_surge_5 / main_inflow_ratio_1d）
    # 已修正/删除；详见 designs/factor_name_col_map_unification_design.md §3.3
    FACTOR_NAME_TO_COL_MAP = _MODULE_NAME_TO_COL_MAP
    COL_TO_FACTOR_NAME_MAP = _MODULE_COL_TO_NAME_MAP

    # v1.12 修复：正则预编译（贪婪匹配，避免错误截断）
    # 原正则 (.+?)_\d+[a-z]?$ 非贪婪，会错误截断 main_inflow_ratio_1d → main_inflow
    # 修复：贪婪匹配 (.+) 匹配最长前缀，正确截断 → main_inflow_ratio
    _FACTOR_SUFFIX_PATTERN = re.compile(r"(.+)_(?:\d+[a-z]?|\d+)$")  # 支持 _5, _6, _1d, _20 等

    def _get_factor_name_from_col(self, col: str) -> str:
        r"""从因子列名提取因子名（用于 IC 结果匹配）

        Args:
            col: 因子列名（如 'volume_ratio_5', 'main_inflow_ratio_1d'）

        Returns:
            因子名（如 'volume_ratio', 'main_inflow_ratio')

        Priority:
            1. 使用反向映射（精确匹配）
            2. 回退：贪婪匹配移除最后一个数字后缀

        v1.12 修复：
        - 原正则 (.+?)_\d+[a-z]?$ 非贪婪，会错误截断 main_inflow_ratio_1d → main_inflow
        - 修复：贪婪匹配 (.+) 匹配最长前缀，正确截断 → main_inflow_ratio
        """
        # 优先使用反向映射
        if col in self.COL_TO_FACTOR_NAME_MAP:
            return self.COL_TO_FACTOR_NAME_MAP[col]

        # 回退：使用预编译正则（贪婪匹配）
        match = self._FACTOR_SUFFIX_PATTERN.match(col)
        if match:
            return match.group(1)

        # 最终回退：原列名
        return col

    def _validate_factor_cols(self, factor_cols: list[str], logger: logging.Logger) -> None:
        """校验因子列非空

        Args:
            factor_cols: 因子列列表
            logger: 日志对象

        Raises:
            ValueError: 因子列为空时

        v1.12 修复：删除冗余条件 or len(factor_cols) == 0
        - not factor_cols 已涵盖空列表（空列表布尔值为 False）
        """
        # v1.12 修复：not factor_cols 已涵盖空列表，无需 or len(...) == 0
        if not factor_cols:
            raise ValueError("因子列 factor_cols 为空，无法计算加权")

    def _apply_weights(
        self,
        factor_df: pd.DataFrame,
        factor_cols: list[str],
        weights: dict[str, float],
        logger: logging.Logger,
        method_name: str = "加权",
    ) -> pd.Series:
        """应用权重计算综合因子（向量化实现 + 缺失因子中性填充 + 单因子权重上限）

        Args:
            factor_df: 因子 DataFrame
            factor_cols: 因子列名（原始列名）
            weights: 权重字典 {因子列: 权重}
            logger: 日志对象
            method_name: 加权方式名称（日志用）

        Returns:
            综合因子 Series

        v1.11→v1.17: 缺失因子处理策略
        - v1.11: NaN 动态权重归一化（缺失因子后放大剩余因子 → 排名虚高）
        - v1.14: fillna(0) 加权值 + divide 归一化（同样放大）
        - v1.17: 缺失因子 z-score 用 0 填充（= 全市场平均）+ 不归一化
          原理：z-score=0 是统计均值，缺失=无信号=中性，既不放大也不惩罚
          效果：缺失因子视为"该因子处于平均水平"，综合因子值自然趋中

        v2.38: 单因子权重上限 25% (design.md feat_interaction_exemption_and_weight_cap §4.3)
        - 应用 _cap_single_factor_weight: 任何单因子名义权重不得超过 25%
        - 业界依据: Asness (2013), AQR 多因子产品经验上限
        - 防垄断: factor_summary_report_2026-06-22.txt 显示
          amplitude_compression 名义 43.7% / 实际贡献 64% → 综合因子退化为单因子

        v2.40: 经济同源族权重上限 30% (design.md feat_family_weight_cap_and_liquidity_filter §3.2)
        - 应用 _cap_family_weight: 同源信号族总权重不得超过 30%
        - 防族级垄断: v2.39 实测 amplitude_family (amplitude_compression 25% +
          interaction_amp_compression 13.75%) = 38.75%，绕过 _cap_single_factor_weight
        """
        # 使用标准化因子列
        std_cols = [f"{col}_std" for col in factor_cols]

        # 校验列存在性
        missing_cols = [col for col in std_cols if col not in factor_df.columns]
        if missing_cols:
            raise ValueError(f"标准化因子列缺失: {missing_cols}")

        # v2.38: 应用单因子权重上限（25% 软上限，迭代摊分）
        capped_weights = self._cap_single_factor_weight(weights, cap=WEIGHT_CAP_DEFAULT, logger=logger)

        # v2.40: 应用族级权重上限（30% 软上限，按族内原权重比例分配）
        capped_weights = self._cap_family_weight(capped_weights, factor_cols, cap=FAMILY_CAP_DEFAULT, logger=logger)

        # 向量化加权求和
        # 构建权重向量
        weight_values = np.array([capped_weights[col] for col in factor_cols])

        # 构建 DataFrame（标准化因子列）
        std_df = factor_df[std_cols]

        # v1.17: 缺失因子 z-score 用 0 填充（缺失=全市场平均=无信号）
        # z-score 标准化后均值=0，缺失因子视为"平均水平"是最保守客观的假设
        # 不做动态归一化：权重之和恒为 1.0，缺失因子贡献 0×weight=0
        # 对比旧方案：旧方案 divide(valid_weight_sum) 放大剩余因子权重，
        #   导致缺失高ICIR因子后综合因子值更极端、排名虚高
        std_df_filled = std_df.fillna(0)

        # 加权求和（无需归一化，权重之和恒为 1.0）
        weighted_df = std_df_filled.multiply(weight_values, axis=1)
        composite = weighted_df.sum(axis=1)

        # 全 NaN 行保持 NaN（而非 0）
        # fillna(0) 将全 NaN 行变为 0，综合因子=0 误导（伪装成"平均水平"）
        # 实际上该股票无任何因子信号，应标记为 NaN
        all_nan_mask = std_df.isna().all(axis=1)
        composite = composite.where(~all_nan_mask, np.nan)

        logger.info("%s完成: 权重 %s，NaN处理=中性填充(z=0)", method_name, capped_weights)

        return composite

    @staticmethod
    def _cap_single_factor_weight(
        weights: dict[str, float],
        cap: float = 0.25,
        logger: logging.Logger | None = None,
        max_iter: int = 20,
    ) -> dict[str, float]:
        """单因子权重软上限（迭代摊分算法）

        Args:
            weights: 原始权重 {factor_col: weight}, 假定 sum == 1.0
            cap: 单因子最大权重（默认 25%, 业界 AQR/Asness 2013 经验值）
            logger: 日志对象（可选, 记录截断事件）
            max_iter: 迭代上限（防御性, 实测多 1-2 轮即收敛）

        Returns:
            capped weights, sum == 1.0 (1e-9 精度内)

        Algorithm (软上限, 保留 ICIR 排序信息):
            while any(w > cap):
                excess = sum(max(0, w - cap) for w in weights)  # 超额总和
                超额因子截至 cap; 剩余因子按其原权重比例分摊 excess
            理论上最多 floor(1/cap)-1 个因子可达 cap (4 个 25%=100%)

        Edge cases:
            - 空字典: 直接返回
            - 单因子: 必为 100%, 远超 cap → 退化为 {f: 1.0} (无可分摊对象)
            - 全部到 cap: 总权重 < 1.0 时, 按"剩余因子已耗尽"等权拉回

        v2.38: design.md feat_interaction_exemption_and_weight_cap §4.3
        v2.38a: 物理可行性约束 - n_factors * cap < 1.0 时跳过 cap (不可解, 避免等权回退破坏权重信息)
        """
        if not weights:
            return weights

        # v2.38a: 物理可行性检查 - cap 必须可达成 (n × cap >= 1.0)
        # 例: 3 因子 × 0.25 = 0.75 < 1.0 → cap 无解, 跳过 (保留原权重)
        n = len(weights)
        if n * cap < 1.0 - 1e-9:
            if logger is not None:
                logger.debug(
                    "_cap_single_factor_weight skipped: n=%d * cap=%.2f = %.2f < 1.0 (cap 物理不可行)",
                    n,
                    cap,
                    n * cap,
                )
            return dict(weights)

        # 防御性: 检查输入 sum
        original_sum = sum(weights.values())
        if abs(original_sum - 1.0) > 1e-6:
            if logger is not None:
                logger.warning(
                    "_cap_single_factor_weight 输入权重总和=%.6f != 1.0, 先归一化",
                    original_sum,
                )
            if original_sum == 0:
                # 退化为等权
                n = len(weights)
                return dict.fromkeys(weights, 1.0 / n)
            weights = {f: w / original_sum for f, w in weights.items()}

        capped = dict(weights)
        truncated_factors: list[str] = []

        for _ in range(max_iter):
            # 找出超过 cap 的因子
            over_cap = {f: w for f, w in capped.items() if w > cap + 1e-12}
            if not over_cap:
                break

            # 超额总和
            excess = sum(w - cap for w in over_cap.values())

            # 截断到 cap
            for f in over_cap:
                capped[f] = cap
                if f not in truncated_factors:
                    truncated_factors.append(f)

            # 剩余因子 (权重 < cap) 的原权重总和
            others = {f: w for f, w in capped.items() if w < cap - 1e-12}
            others_sum = sum(others.values())

            if others_sum < 1e-12:
                # 所有因子都到顶: 剩余 excess 无处可分, 等权拉回
                # (此情况只在 n * cap < 1.0 时出现, 例如 3 因子 × cap=0.30 = 0.90)
                n = len(capped)
                for f in capped:
                    capped[f] = 1.0 / n
                break

            # 按 others 原权重比例摊分 excess
            for f in others:
                capped[f] += excess * (others[f] / others_sum)

        if logger is not None and truncated_factors:
            logger.info(
                "_cap_single_factor_weight cap=%.2f: 截断 %d 个因子 %s, 摊分至剩余",
                cap,
                len(truncated_factors),
                truncated_factors,
            )

        return capped

    @staticmethod
    def _cap_family_weight(
        weights: dict[str, float],
        factor_cols: list[str],
        cap: float = 0.30,
        max_iter: int = 20,
        logger: logging.Logger | None = None,
    ) -> dict[str, float]:
        """族级权重上限（迭代摊分，与 _cap_single_factor_weight 同构）

        v2.40 design.md §3.2:
        - 把因子按 FACTOR_FAMILIES 聚合到经济同源族
        - 任一族总权重不得超过 cap (默认 30%)
        - 超过的族按族内原权重比例降权
        - 超出部分按其他族原权重比例摊分

        Args:
            weights: 因子列名→权重（已经过单因子 cap）
            factor_cols: 因子列名列表（用于反查因子名→族）
            cap: 族级权重上限（默认 0.30）
            max_iter: 最大迭代次数（防极端 NaN）
            logger: 日志对象

        Returns:
            族级 cap 后的权重 dict（sum 仍 = 1.0）

        Note:
            - FACTOR_FAMILIES 为空 / 因子未归族 → 归 'uncategorized_family' 不参与 cap
            - 若所有族都 ≤ cap → 直接返回
            - 物理可行性: n_active_families × cap ≥ 1.0 时方程有解
              (例如 4 族各 cap=30% = 120% ≥ 100% ✓)
        """
        # 容错: weights 为空或单因子
        if not weights or len(weights) == 1:
            return dict(weights)

        # Step 1: 因子列名 → 族名（通过 _get_factor_name_from_col 反查）
        # 使用临时实例方法（_get_factor_name_from_col 是 instance method）
        # 为支持 staticmethod 调用，这里复制核心逻辑
        col_to_family: dict[str, str] = {}
        for col in factor_cols:
            if col not in weights:
                continue
            # 优先反向映射
            factor_name = _MODULE_COL_TO_NAME_MAP.get(col)
            if factor_name is None:
                # 回退：贪婪截断数字后缀
                m = re.match(r"(.+)_(?:\d+[a-z]?|\d+)$", col)
                factor_name = m.group(1) if m else col
            family = _MODULE_FACTOR_FAMILIES.get(factor_name, "uncategorized_family")
            col_to_family[col] = family

        # Step 2: 按族聚合权重
        capped = dict(weights)

        for _ in range(max_iter):
            family_totals: dict[str, float] = {}
            for col, w in capped.items():
                fam = col_to_family.get(col, "uncategorized_family")
                family_totals[fam] = family_totals.get(fam, 0.0) + abs(w)

            # 找出超限的族
            over_families = {f: t for f, t in family_totals.items() if t > cap + 1e-9}
            if not over_families:
                break

            # 收集 under 族（含恰好 = cap 的）
            under_families = {f: t for f, t in family_totals.items() if t <= cap + 1e-9}
            under_sum = sum(under_families.values())
            if under_sum <= 1e-12:
                # 所有族都 over: n × cap < 1.0 即无解，但当前 cap=0.30 + ≥4 族实际不可能
                if logger is not None:
                    logger.warning("_cap_family_weight: 所有族均超 cap=%.2f, 物理不可行, 跳过本轮", cap)
                break

            # Step 3: 对超限族按族内原权重比例降权至 cap
            total_excess = 0.0
            for fam, total in over_families.items():
                scale = cap / total
                fam_cols = [c for c, f in col_to_family.items() if f == fam]
                for c in fam_cols:
                    new_w = capped[c] * scale
                    total_excess += abs(capped[c]) - abs(new_w)
                    capped[c] = new_w

            # Step 4: 把 excess 按 under 族当前 capped 权重比例摊分
            # 修复 bug: 必须用 capped (而非 weights), 否则摊分比例与族总和不一致导致 sum 漂移
            under_factor_total = sum(abs(capped[c]) for c, f in col_to_family.items() if f in under_families)
            if under_factor_total > 1e-12:
                for c, f in col_to_family.items():
                    if f in under_families:
                        share = abs(capped[c]) / under_factor_total
                        sign = 1 if capped[c] >= 0 else -1
                        capped[c] += total_excess * share * sign

        # Step 5: 计算最终族分布，记录日志
        if logger is not None:
            final_totals: dict[str, float] = {}
            for c, w in capped.items():
                fam = col_to_family.get(c, "uncategorized_family")
                final_totals[fam] = final_totals.get(fam, 0.0) + abs(w)
            capped_families = [f for f, t in final_totals.items() if t > cap - 1e-3]
            if capped_families:
                logger.info(
                    "_cap_family_weight cap=%.2f: 触达上限族 %s, 族分布 %s",
                    cap,
                    capped_families,
                    {f: round(t, 4) for f, t in sorted(final_totals.items(), key=lambda x: -x[1])},
                )

        return capped

    @staticmethod
    def _cap_weight_matrix(
        W: np.ndarray,
        cap: float = 0.25,
        max_iter: int = 20,
        factor_families: list[int] | None = None,  # v2.40: 族索引，启用族级 cap
        family_cap: float = 0.30,  # v2.40: 族级上限
    ) -> np.ndarray:
        """权重矩阵行级软上限（向量化版本, 用于 RollingICIR 每日动态权重）

        v2.40: 增加 family_cap 族级限制
        - factor_families: 每列对应的族 ID（int），None 时跳过族级 cap
        - family_cap: 族级上限（默认 0.30）

        Args:
            W: shape (n_days, n_factors), 每行 sum == 1.0 (假定已归一化)
            cap: 单因子最大权重
            max_iter: 迭代上限
            factor_families: 每列对应的族 ID（可选，启用族级 cap）
            family_cap: 族级权重上限（默认 0.30）

        Returns:
            capped W, 每行 sum == 1.0

        Algorithm (与 _cap_single_factor_weight 同构, numpy 向量化):
            for _ in range(max_iter):
                over = W > cap                   # bool mask
                if not over.any(): break
                excess = (W - cap).clip(0).sum(axis=1)   # 每行超额
                W[over] = cap                    # 截断
                under = W < cap - 1e-12          # 剩余可摊分因子 mask
                under_sum = (W * under).sum(axis=1)
                # 按比例摊分: W += excess * (W * under) / under_sum (行广播)
                ...

        v2.38: design.md §4.3, 用于 RollingICIRWeightMethod 每日 _dim_weight 行
        v2.38a: 物理可行性约束 - n_factors * cap < 1.0 时直接返回 (跳过 cap)
        """
        # v2.38a: 物理可行性检查
        n_factors = W.shape[1]
        if n_factors * cap < 1.0 - 1e-9:
            return W.copy()  # 不可解, 保留原权重

        W = W.copy()  # 防御性: 不污染原矩阵
        EPS = 1e-12

        for _ in range(max_iter):
            over_mask = cap + EPS < W
            if not over_mask.any():
                break

            # 每行超额总和
            excess_per_row = np.where(over_mask, W - cap, 0.0).sum(axis=1)  # (n_days,)

            # 截断到 cap
            W = np.where(over_mask, cap, W)

            # 剩余可摊分因子 mask
            under_mask = cap - EPS > W

            # 每行剩余因子原权重总和
            under_sum_per_row = np.where(under_mask, W, 0.0).sum(axis=1)  # (n_days,)

            # 行 1: 所有因子到顶 (under_sum=0) → 等权拉回 (避免除零)
            all_capped_rows = under_sum_per_row < EPS
            if all_capped_rows.any():
                W[all_capped_rows, :] = 1.0 / n_factors

            # 行 2: 正常摊分
            normal_rows = ~all_capped_rows
            if normal_rows.any():
                # ratio[d, f] = W[d, f] / under_sum[d] if under_mask else 0
                under_w = np.where(under_mask, W, 0.0)
                # 除零保护: under_sum_per_row 已知非零（normal_rows 上）
                ratio = np.zeros_like(W)
                ratio[normal_rows] = under_w[normal_rows] / under_sum_per_row[normal_rows, None]
                # 摊分: W += excess[d] × ratio[d, f]
                addend = excess_per_row[:, None] * ratio
                W[normal_rows] = W[normal_rows] + addend[normal_rows]

        # v2.40: 族级 cap（在单因子 cap 之后再约束族级总权重）
        if factor_families is not None:
            fam_arr = np.asarray(factor_families, dtype=int)
            unique_fams = np.unique(fam_arr)
            n_active_families = len(unique_fams)
            # 物理可行性: n_families × family_cap ≥ 1.0
            if n_active_families * family_cap >= 1.0 - 1e-9:
                # 构建 (n_families, n_factors) 选择矩阵 S，S[k, f]=1 表示因子 f 属于族 k
                S = np.zeros((n_active_families, W.shape[1]), dtype=float)
                for k, fam_id in enumerate(unique_fams):
                    S[k, fam_arr == fam_id] = 1.0

                for _ in range(max_iter):
                    # 族总权重: F = W @ S.T → shape (n_days, n_families)
                    F = W @ S.T
                    over_fam_mask = family_cap + EPS < F
                    if not over_fam_mask.any():
                        break

                    # 每行超额（按族汇总）
                    family_excess = np.where(over_fam_mask, F - family_cap, 0.0).sum(axis=1)

                    # 超限族内按比例降权: scale[d, k] = family_cap / F[d, k] if over
                    scale_factor = np.where(over_fam_mask, family_cap / np.maximum(F, EPS), 1.0)
                    # 把 scale 映射到因子级: factor_scale[d, f] = scale_factor[d, fam[f]]
                    factor_scale = scale_factor[:, fam_arr]
                    W = W * factor_scale

                    # under 族总权重和（用于摊分）
                    under_fam_mask = ~over_fam_mask
                    under_fam_sum = np.where(under_fam_mask, F, 0.0).sum(axis=1)

                    # 摊分: 在 under 族内按各因子原权重比例分摊 excess
                    safe_under_sum = np.where(under_fam_sum > EPS, under_fam_sum, 1.0)
                    # under_fam[d, k]=1 if family k under cap
                    under_factor_mask = under_fam_mask[:, fam_arr]  # (n_days, n_factors)
                    under_factor_w = np.where(under_factor_mask, W, 0.0)
                    addend = family_excess[:, None] * (under_factor_w / safe_under_sum[:, None])
                    W = W + addend

        return W

    # v2.35: P2 维度权重全方法支持——静态权重维度再分配（通用方法，所有子类可调用）
    # M58(MODULE.md L1966): 维度权重是WeightEngine通用能力，不限于rolling_icir
    # 设计决策(design.md §2.2): 维度权重是"后处理"层，不改变核心计算逻辑
    dimension_weight_method: str | None = None
    factor_categories: dict[str, str] | None = None
    enable_role_weights: bool = False  # v2.41 (R2): 角色固定权重，r2b 由 composite_runner 启用

    def _apply_dimension_weights_static(
        self,
        weights: dict[str, float],
        factor_cols: list[str],
    ) -> dict[str, float]:
        """静态权重维度两阶段再分配（后处理）

        与 RollingICIRWeightMethod._apply_dimension_weights 的区别：
        - 滚动方法: 对 DataFrame 列操作（权重每日动态）
        - 静态方法: 对 weights dict 操作（权重固定）

        两阶段:
        1. 维度内归一化: 各因子在维度内按原始权重比例分配
        2. 维度间归一化:
           - equal: 1/n_dims（维度等权）
           - icir: 维度权重 = 维度内平均|权重| 归一化

        Args:
            weights: 原始权重字典 {因子列: 权重值}
            factor_cols: 因子列名列表

        Returns:
            维度再分配后的权重字典（权重和=1）
        """
        if not self.dimension_weight_method or not self.factor_categories:
            return weights

        # 构建维度分组
        groups: dict[str, list[str]] = {}
        for col in factor_cols:
            factor_name = self._get_factor_name_from_col(col)
            dim = self.factor_categories.get(factor_name, "uncategorized")
            groups.setdefault(dim, []).append(col)

        n_dims = len(groups)
        n_factors = len(factor_cols)
        new_weights: dict[str, float] = {}

        if self.dimension_weight_method == "equal":
            # 维度等权: 1/n_dims，维度内按原权重比例
            for dim, dim_cols in groups.items():
                dim_total = sum(abs(weights[c]) for c in dim_cols)
                for col in dim_cols:
                    if dim_total > 0:
                        new_weights[col] = weights[col] / dim_total * (1.0 / n_dims)
                    else:
                        new_weights[col] = 1.0 / n_factors
        elif self.dimension_weight_method == "icir":
            # icir: 维度权重 = 维度内平均|权重| 归一化
            dim_avg: dict[str, float] = {}
            for dim, dim_cols in groups.items():
                dim_avg[dim] = sum(abs(weights[c]) for c in dim_cols) / len(dim_cols)
            total_avg = sum(dim_avg.values())

            for dim, dim_cols in groups.items():
                dim_total = sum(abs(weights[c]) for c in dim_cols)
                dim_weight = dim_avg[dim] / total_avg if total_avg > 0 else 1.0 / n_dims
                for col in dim_cols:
                    if dim_total > 0:
                        new_weights[col] = (weights[col] / dim_total) * dim_weight
                    else:
                        new_weights[col] = 1.0 / n_factors
        else:
            new_weights = weights

        # 行级归一化（确保权重和=1）
        total = sum(new_weights.values())
        if total > 0:
            new_weights = {k: v / total for k, v in new_weights.items()}

        logger = getattr(self, "logger", None) or get_logger(__name__)
        logger.info(
            "维度权重再分配(%s): %d维度 %d因子 → %s",
            self.dimension_weight_method,
            n_dims,
            n_factors,
            {k: f"{v:.4f}" for k, v in new_weights.items()},
        )

        return new_weights

    # v2.41 (R2): 角色固定权重后处理（主 75% + 确认 25%）
    # 设计依据: designs/feat_role_based_fixed_weight_75_25.md §3.1
    # 第一性原理: PRIMARY_WEIGHT_TOTAL=0.75 为锚, confirmation 总额=1-0.75=0.25
    #   每个 confirmation = 0.25 / n_confirmation (自适应因子数量)
    #   注意: CONFIRMATION_WEIGHT_PER_FACTOR=0.05 是 5 因子假设下的旧常量,
    #   实际 16 个 confirmation 因子 → 0.05×16=0.80 会反转 75/25, 故不使用.
    def _apply_role_weights_static(
        self,
        weights: dict[str, float],
        factor_cols: list[str],
    ) -> dict[str, float]:
        """角色后处理: primary 75% + confirmation 25% 平摊 + filter 排除.

        第一性原理 (designs/feat_role_based_fixed_weight_75_25.md §5):
            - primary (反转触发): 高 IC, 单独可形成多头收益
            - confirmation (企稳确认): 低 IC 但低相关, 固定份额保证发言权
            - filter: 基本面/累计跌幅, stock_selector 硬过滤, 不进 composite
            - 业界依据: Asness 2013, AQR 核心+卫星 70-80/20-30

        Args:
            weights: 上游 (dimension_weights 后) 权重字典.
            factor_cols: 因子列名列表.

        Returns:
            角色处理后的权重字典, sum=1.0 (filter 因子权重=0).

        豁免: 无 confirmation 因子 → 退化为原权重归一化.
        """
        if not getattr(self, "enable_role_weights", False):
            return weights

        logger = getattr(self, "logger", None)
        if logger is None:
            from comprehensive_factor.common.logger_config import get_logger

            logger = get_logger(__name__)

        # 1) 按角色分桶
        primary_cols: list[str] = []
        confirmation_cols: list[str] = []
        filter_cols: list[str] = []
        for col in factor_cols:
            factor_name = self._get_factor_name_from_col(col)
            role = _MODULE_FACTOR_ROLES.get(factor_name, "primary")
            if role == "primary":
                primary_cols.append(col)
            elif role == "confirmation":
                confirmation_cols.append(col)
            elif role == "filter":
                filter_cols.append(col)

        # 2) filter 角色: 权重置 0 (由 stock_selector 硬过滤)
        new_weights: dict[str, float] = dict.fromkeys(filter_cols, 0.0)

        # 3) confirmation 角色: 总额 25%, 均分
        if confirmation_cols:
            confirmation_total = 1.0 - _MODULE_PRIMARY_WEIGHT_TOTAL  # 0.25
            per_confirmation = confirmation_total / len(confirmation_cols)
            for col in confirmation_cols:
                new_weights[col] = per_confirmation
        else:
            confirmation_total = 0.0

        # 4) primary 角色: 总额 75%, 按原权重比例分配
        primary_total_target = _MODULE_PRIMARY_WEIGHT_TOTAL  # 0.75
        if primary_cols:
            primary_orig_sum = sum(weights.get(c, 0.0) for c in primary_cols)
            if primary_orig_sum > 0:
                for col in primary_cols:
                    new_weights[col] = weights.get(col, 0.0) / primary_orig_sum * primary_total_target
            else:
                # primary 原权重全 0 → 等权降级
                logger.warning("_apply_role_weights: primary 原权重全 0, 降级为等权")
                for col in primary_cols:
                    new_weights[col] = primary_total_target / len(primary_cols)
        else:
            # 无 primary, confirmation 单独承担 100%
            logger.warning("_apply_role_weights: 无 primary 因子, confirmation 占 100%%")
            if confirmation_cols and confirmation_total > 0:
                scale = 1.0 / confirmation_total
                for col in confirmation_cols:
                    new_weights[col] *= scale

        # 5) 归一化校验
        total = sum(new_weights.values())
        if total > 0 and abs(total - 1.0) > 1e-6:
            new_weights = {k: v / total for k, v in new_weights.items()}

        logger.info(
            "角色权重: primary=%d (%.0f%%) + confirmation=%d (%.0f%%) + filter=%d (排除)",
            len(primary_cols),
            primary_total_target * 100,
            len(confirmation_cols),
            confirmation_total * 100,
            len(filter_cols),
        )
        return new_weights

    # v2.41 (r2c): 角色固定权重后处理（矩阵版, 用于 RollingICIR 每日动态权重）
    # 设计依据: designs/feat_r2c_role_weights_for_rolling_icir.md
    # 与 _apply_role_weights_static 同构, 向量化逐行处理.
    def _apply_role_weights_matrix(
        self,
        W: np.ndarray,
        factor_cols: list[str],
    ) -> np.ndarray:
        """角色后处理 (矩阵版): primary 75% + confirmation 25% 均分 + filter 排除.

        与 _apply_role_weights_static (dict 版) 数值同构, 但对 (n_days, n_factors)
        矩阵每行独立完成角色分桶 → 归一化, 用于 RollingICIRWeightMethod 每日动态权重.

        Args:
            W: shape (n_days, n_factors), 每行 sum 假定 ≈ 1.0
            factor_cols: 因子列名列表, 对应 W 的列顺序.

        Returns:
            重新分配权重后的 W (拷贝), 每行 sum == 1.0.
            filter 列权重 = 0; confirmation 列均分 25%; primary 列按原行内比例分配 75%.

        豁免: enable_role_weights=False → 直接返回 W.copy() (向后兼容).
        """
        if not getattr(self, "enable_role_weights", False):
            return W.copy()

        # 1) 角色分桶 (factor_cols 静态决定, 所有行共享 mask)
        primary_mask = np.array(
            [_MODULE_FACTOR_ROLES.get(self._get_factor_name_from_col(c), "primary") == "primary" for c in factor_cols],
            dtype=bool,
        )
        conf_mask = np.array(
            [
                _MODULE_FACTOR_ROLES.get(self._get_factor_name_from_col(c), "primary") == "confirmation"
                for c in factor_cols
            ],
            dtype=bool,
        )
        filter_mask = np.array(
            [_MODULE_FACTOR_ROLES.get(self._get_factor_name_from_col(c), "primary") == "filter" for c in factor_cols],
            dtype=bool,
        )

        n_primary = int(primary_mask.sum())
        n_conf = int(conf_mask.sum())
        confirmation_total = 1.0 - _MODULE_PRIMARY_WEIGHT_TOTAL  # 0.25
        primary_target = _MODULE_PRIMARY_WEIGHT_TOTAL  # 0.75

        W_new = W.copy()

        # 2) filter 桶: 置 0 (硬过滤由 stock_selector 处理)
        if filter_mask.any():
            W_new[:, filter_mask] = 0.0

        # 3) confirmation 桶: 均分 25% (无 confirmation 时 primary 独占 100%)
        if n_conf > 0:
            W_new[:, conf_mask] = confirmation_total / n_conf
            primary_pool = primary_target
        else:
            primary_pool = 1.0  # 无 confirmation → primary 独占 100%

        # 4) primary 桶: 按原行内权重比例分配 primary_pool
        if n_primary > 0:
            primary_sum_per_row = W[:, primary_mask].sum(axis=1, keepdims=True)  # (n_days, 1)
            # 防御性: primary 原权重全 0 行 → 等权降级
            zero_rows = (primary_sum_per_row < 1e-12).flatten()
            safe_sum = np.where(primary_sum_per_row < 1e-12, 1.0, primary_sum_per_row)
            W_new[:, primary_mask] = W[:, primary_mask] / safe_sum * primary_pool
            if zero_rows.any():
                # 等权降级: zero_rows 上的 primary 列改写为 primary_pool / n_primary
                W_new[np.ix_(zero_rows, primary_mask)] = primary_pool / n_primary
        elif n_conf > 0:
            # 无 primary, confirmation 单独承担 100%
            W_new[:, conf_mask] = 1.0 / n_conf

        # 5) 行归一化兜底 (防浮点累积误差)
        row_sum = W_new.sum(axis=1, keepdims=True)
        W_new = W_new / np.where(row_sum > 1e-12, row_sum, 1.0)

        return W_new

    @abstractmethod
    def calculate(
        self,
        factor_df: pd.DataFrame,
        factor_cols: list[str],
        ic_results: dict[str, dict] | None = None,
        ic_daily_data: dict[str, pd.DataFrame] | None = None,
    ) -> pd.Series:
        """计算综合因子

        Args:
            factor_df: 因子 DataFrame（包含标准化因子列）
            factor_cols: 因子列名（原始列名，会自动转换为 _std 列）
            ic_results: IC统计结果（可选，部分加权方式需要）
            ic_daily_data: IC每日序列（可选，滚动ICIR需要）

        Returns:
            综合因子值 Series
        """
        pass

    @abstractmethod
    def get_weights(self, factor_cols: list[str], ic_results: dict[str, dict] | None = None) -> dict[str, float]:
        """获取权重字典

        Returns:
            Dict[因子列, 权重值]
        """
        pass


class EqualWeightMethod(WeightMethodBase):
    """等权加权

    weight = 1 / n_factors
    """

    def __init__(
        self,
        logger: logging.Logger | None = None,
        dimension_weight_method: str | None = None,
        factor_categories: dict[str, str] | None = None,
        enable_role_weights: bool = False,  # v2.41 (R2)
    ):
        self.logger = logger or get_logger(__name__)
        self.dimension_weight_method = dimension_weight_method  # v2.35: P2 维度权重全方法
        self.factor_categories = factor_categories
        self.enable_role_weights = enable_role_weights  # v2.41 (R2)

    def calculate(
        self,
        factor_df: pd.DataFrame,
        factor_cols: list[str],
        ic_results: dict[str, dict] | None = None,
        ic_daily_data: dict[str, pd.DataFrame] | None = None,
    ) -> pd.Series:
        """等权加权计算

        v1.12 修复：删除重复校验
        - WeightEngine.calculate 已校验 factor_cols 非空
        - 子类 calculate 信任调用方已完成校验
        v2.35: P2 维度权重后处理
        """
        # 计算权重
        weights = self.get_weights(factor_cols, ic_results)

        # v2.35: P2 维度权重再分配（后处理）
        weights = self._apply_dimension_weights_static(weights, factor_cols)
        # v2.41 (R2): 角色固定权重后处理（主 75% + 确认 25%）
        weights = self._apply_role_weights_static(weights, factor_cols)

        # 使用基类公共方法（向量化实现）
        return self._apply_weights(factor_df, factor_cols, weights, self.logger, "等权加权")

    def get_weights(self, factor_cols: list[str], ic_results: dict[str, dict] | None = None) -> dict[str, float]:
        """获取等权重

        v1.12 修复：删除冗余条件 or len(...) == 0
        """
        # v1.12 修复：not factor_cols 已涵盖空列表
        if not factor_cols:
            raise ValueError("因子列 factor_cols 为空，无法计算等权")

        n_factors = len(factor_cols)
        weight = 1.0 / n_factors
        return dict.fromkeys(factor_cols, weight)


class ICIRWeightMethod(WeightMethodBase):
    """ICIR加权（静态）

    weight_i = ICIR_i / sum(ICIR_j)

    注意：反向因子ICIR为负值，需要特殊处理。
    """

    def __init__(
        self,
        logger: logging.Logger | None = None,
        dimension_weight_method: str | None = None,
        factor_categories: dict[str, str] | None = None,
        enable_role_weights: bool = False,  # v2.41 (R2)
    ):
        self.logger = logger or get_logger(__name__)
        self.dimension_weight_method = dimension_weight_method  # v2.35: P2 维度权重全方法
        self.factor_categories = factor_categories
        self.enable_role_weights = enable_role_weights  # v2.41 (R2)

    def calculate(
        self,
        factor_df: pd.DataFrame,
        factor_cols: list[str],
        ic_results: dict[str, dict] | None = None,
        ic_daily_data: dict[str, pd.DataFrame] | None = None,
        short_sample_factors: dict[str, int] | None = None,  # v1.15: 短样本因子ICIR惩罚
    ) -> pd.Series:
        """ICIR加权计算

        v1.12 修复：删除重复校验（WeightEngine.calculate 已校验）
        v1.15: 新增 short_sample_factors 参数，短样本因子ICIR权重惩罚
        v2.35: P2 维度权重后处理
        """
        if ic_results is None:
            raise ValueError("ICIR加权需要 ic_results 参数")

        # 计算权重（v1.15: 传入短样本因子信息）
        weights = self.get_weights(factor_cols, ic_results, short_sample_factors)

        # v2.35: P2 维度权重再分配（后处理）
        weights = self._apply_dimension_weights_static(weights, factor_cols)
        # v2.41 (R2): 角色固定权重后处理（主 75% + 确认 25%）
        weights = self._apply_role_weights_static(weights, factor_cols)

        # 使用基类公共方法（向量化实现）
        return self._apply_weights(factor_df, factor_cols, weights, self.logger, "ICIR加权")

    @staticmethod
    def _extract_effective_icir(entry: dict) -> float | None:
        """Plan D: 优先 neutralized_icir，fallback raw icir（design.md §2）

        neutralized_enabled=True 且 neutralized_icir 非 None → 用中性化值
        否则 → 用 raw icir（向后兼容旧版 IC 结果）
        """
        if entry.get("neutralized_enabled") and entry.get("neutralized_icir") is not None:
            return abs(entry["neutralized_icir"])
        if entry.get("icir") is not None:
            return abs(entry["icir"])
        return None

    def get_weights(
        self, factor_cols: list[str], ic_results: dict[str, dict], short_sample_factors: dict[str, int] | None = None
    ) -> dict[str, float]:
        """获取ICIR权重

        处理负ICIR：
        - ICIR = IC均值/IC标准差，反映因子的预测稳定性
        - ICIR 绝对值越高，因子预测能力越稳定，权重越大

        v1.15: 短样本因子ICIR权重惩罚
        - 短样本因子(valid_days < min_sample_days)的ICIR权重乘以惩罚系数
        - 惩罚系数 = sqrt(valid_days / min_sample_days)
        - 理由：18天数据的高ICIR统计不显著，惩罚后权重更合理
        - 例如：18天因子惩罚系数 = sqrt(18/30) ≈ 0.77，ICIR从0.80降至0.62

        Plan D (2026-06-18): 优先使用中性化 ICIR
        - neutralized_enabled=True 时取 neutralized_icir（纯 alpha 贡献）
        - fallback raw icir（含行业/市值 beta）
        - short_sample 惩罚在取值后叠加（两者正交，design.md §2.4）

        v1.12 修复：删除冗余条件 or len(...) == 0
        """
        # v1.12 修复：not factor_cols 已涵盖空列表
        if not factor_cols:
            raise ValueError("因子列 factor_cols 为空，无法计算ICIR权重")

        MIN_SAMPLE_DAYS = 30  # v1.15→v1.16: 统计学大样本近似门槛
        # v1.16: 惩罚系数从 linear (valid_days/MIN) 改为 1.5 次方 (valid_days/MIN)^1.5
        # 理由：18天因子的 linear 惩罚=0.6，ICIR从0.80降至0.48，权重仍偏高
        #   1.5次方惩罚=(0.6)^1.5≈0.465，ICIR从0.80降至0.37，权重显著降低
        #   统计学依据：30天以下样本的ICIR t检验 p-value > 0.05，18天ICIR极不显著

        # 提取 ICIR 值（取绝对值）
        icir_values = {}
        for col in factor_cols:
            # 使用基类公共方法提取因子名（贪婪匹配）
            factor_name = self._get_factor_name_from_col(col)

            # Plan D: 优先 neutralized_icir，fallback raw icir
            if factor_name in ic_results:
                icir_abs = self._extract_effective_icir(ic_results[factor_name])
            elif col in ic_results:
                icir_abs = self._extract_effective_icir(ic_results[col])
            else:
                icir_abs = None

            if icir_abs is not None:
                # v1.15→v1.16: 短样本因子ICIR权重惩罚（1.5次方）
                penalty_key = factor_name if factor_name in (short_sample_factors or {}) else col
                if short_sample_factors and penalty_key in short_sample_factors:
                    valid_days = short_sample_factors[penalty_key]
                    ratio = valid_days / MIN_SAMPLE_DAYS
                    penalty = ratio**1.5  # v1.16: 从 linear 改为 1.5 次方
                    self.logger.info(
                        "短样本因子 %s: ICIR惩罚 %.3f→%.3f (×%d/%d=%.2f)",
                        penalty_key,
                        icir_abs,
                        icir_abs * penalty,
                        valid_days,
                        MIN_SAMPLE_DAYS,
                        penalty,
                    )
                    icir_abs *= penalty
                icir_values[col] = icir_abs
            else:
                self.logger.warning("因子 %s 缺失 ICIR，使用等权默认值 1.0", col)
                icir_values[col] = 1.0  # 缺失时使用等权

        # 除零保护 - total_icir 为 0 时回退等权
        total_icir = sum(icir_values.values())
        if total_icir == 0:
            self.logger.warning("所有因子 ICIR 绝对值均为 0，回退等权")
            n_factors = len(factor_cols)
            return dict.fromkeys(factor_cols, 1.0 / n_factors)

        weights = {col: icir_values[col] / total_icir for col in factor_cols}

        return weights


class ICWeightMethod(WeightMethodBase):
    """IC均值加权（静态）

    weight_i = |ic_mean_i| / sum(|ic_mean_j|)

    使用绝对值：反向因子IC均值为负，取绝对值后加权。
    """

    def __init__(
        self,
        logger: logging.Logger | None = None,
        dimension_weight_method: str | None = None,
        factor_categories: dict[str, str] | None = None,
        enable_role_weights: bool = False,  # v2.41 (R2)
    ):
        self.logger = logger or get_logger(__name__)
        self.dimension_weight_method = dimension_weight_method  # v2.35: P2 维度权重全方法
        self.factor_categories = factor_categories
        self.enable_role_weights = enable_role_weights  # v2.41 (R2)

    def calculate(
        self,
        factor_df: pd.DataFrame,
        factor_cols: list[str],
        ic_results: dict[str, dict] | None = None,
        ic_daily_data: dict[str, pd.DataFrame] | None = None,
    ) -> pd.Series:
        """IC均值加权计算

        v1.12 修复：删除重复校验（WeightEngine.calculate 已校验）
        v2.35: P2 维度权重后处理
        """
        if ic_results is None:
            raise ValueError("IC加权需要 ic_results 参数")

        # 计算权重
        weights = self.get_weights(factor_cols, ic_results)

        # v2.35: P2 维度权重再分配（后处理）
        weights = self._apply_dimension_weights_static(weights, factor_cols)
        # v2.41 (R2): 角色固定权重后处理（主 75% + 确认 25%）
        weights = self._apply_role_weights_static(weights, factor_cols)

        # 使用基类公共方法（向量化实现）
        return self._apply_weights(factor_df, factor_cols, weights, self.logger, "IC加权")

    @staticmethod
    def _extract_effective_ic_mean(entry: dict) -> float | None:
        """Plan D: 优先 neutralized_ic_mean，fallback raw ic_mean（design.md §2）"""
        if entry.get("neutralized_enabled") and entry.get("neutralized_ic_mean") is not None:
            return abs(entry["neutralized_ic_mean"])
        if entry.get("ic_mean") is not None:
            return abs(entry["ic_mean"])
        return None

    def get_weights(self, factor_cols: list[str], ic_results: dict[str, dict]) -> dict[str, float]:
        """获取IC权重

        Plan D (2026-06-18): 优先使用中性化 IC 均值（design.md §2）

        v1.12 修复：删除冗余条件 or len(...) == 0
        """
        # v1.12 修复：not factor_cols 已涵盖空列表
        if not factor_cols:
            raise ValueError("因子列 factor_cols 为空，无法计算IC权重")

        # 提取 IC 均值（取绝对值）
        ic_values = {}
        for col in factor_cols:
            # 使用基类公共方法提取因子名（贪婪匹配）
            factor_name = self._get_factor_name_from_col(col)

            # Plan D: 优先 neutralized_ic_mean，fallback raw ic_mean
            if factor_name in ic_results:
                ic_abs = self._extract_effective_ic_mean(ic_results[factor_name])
            elif col in ic_results:
                ic_abs = self._extract_effective_ic_mean(ic_results[col])
            else:
                ic_abs = None

            if ic_abs is not None:
                ic_values[col] = ic_abs
            else:
                self.logger.warning("因子 %s 缺失 IC 均值，使用等权默认值 1.0", col)
                ic_values[col] = 1.0

        # 除零保护 - total_ic 为 0 时回退等权
        total_ic = sum(ic_values.values())
        if total_ic == 0:
            self.logger.warning("所有因子 IC 均值绝对值均为 0，回退等权")
            n_factors = len(factor_cols)
            return dict.fromkeys(factor_cols, 1.0 / n_factors)

        weights = {col: ic_values[col] / total_ic for col in factor_cols}

        return weights


class RollingICIRWeightMethod(WeightMethodBase):
    """滚动ICIR加权（动态）

    每日计算滚动窗口内的 ICIR，动态调整权重。

    weight_i_t = |rolling_icir_i_t| / sum(|rolling_icir_j_t|)

    v1.10 修复：滚动 ICIR 应在时间轴上计算，而非按 asset 分组。
    IC 是每日截面相关性，同一日期所有股票的 IC 值相同。

    v1.20 (2026-06-20): 维度级别权重分配（方案 B）
        - dimension_weight_method='icir': 维度权重=维度内平均|ICIR|归一化，
          维度内因子按 |ICIR| 分配 → 高 ICIR 维度适度超配但不主导
        - dimension_weight_method='equal': 维度等权 1/n_dims
        - dimension_weight_method=None: 当前行为（向后兼容）
    """

    def __init__(
        self,
        window: int = 60,
        logger: logging.Logger | None = None,
        dimension_weight_method: str | None = None,
        factor_categories: dict[str, str] | None = None,
        enable_role_weights: bool = False,  # v2.41 (r2c): 已接通到 _apply_role_weights_matrix
    ):
        self.window = window
        self.logger = logger or get_logger(__name__)
        self._last_day_weights: dict[str, float] = {}  # v1.18: calculate() 后填充
        # v1.20: 维度级别权重分配
        self.dimension_weight_method = dimension_weight_method
        self.factor_categories = factor_categories
        self.enable_role_weights = enable_role_weights  # v2.41 (r2c): 已接通

    def _build_dimension_groups(self, factor_cols: list[str]) -> dict[str, list[str]]:
        """构建维度→因子列名分组

        v1.20: 将 factor_cols 按维度分组，用于两阶段权重计算。
        因子列名通过 _get_factor_name_from_col 映射到因子名后查 FACTOR_CATEGORIES。

        Returns:
            {dimension: [col1, col2, ...]}，无分类信息时返回空 dict
        """
        if not self.factor_categories or not self.dimension_weight_method:
            return {}

        groups: dict[str, list[str]] = {}
        for col in factor_cols:
            factor_name = self._get_factor_name_from_col(col)
            dim = self.factor_categories.get(factor_name)
            if dim is None:
                # 未分类因子归入 "uncategorized" 维度
                dim = "uncategorized"
            groups.setdefault(dim, []).append(col)

        return groups

    def _apply_dimension_weights(
        self,
        factor_df: pd.DataFrame,
        factor_cols: list[str],
        rolling_icir_cols: list[str],
        dimension_groups: dict[str, list[str]],
    ) -> pd.DataFrame:
        """两阶段维度感知权重计算

        v1.20 方案 B:
        - equal: 维度等权 1/n_dims，维度内因子按 |ICIR| 分配
        - icir: 维度权重 = 维度内平均|ICIR| 归一化，维度内因子按 |ICIR| 分配

        对每个日期独立计算（rolling_icir 是每日动态的）。
        """
        n_dims = len(dimension_groups)
        n_factors = len(factor_cols)

        # v2.53 (OOM fix, 模式9): 预计算一次 abs_icir 矩阵，两个循环复用
        # 原实现循环1 (L1222) 和循环2 (L1250) 各自调用 factor_df[dim_rolling_cols].abs()
        # 每次分配 35列×1.39M=390MB，两次=780MB 冗余分配
        # 修复：预计算全部 rolling_icir 列的绝对值为 numpy 矩阵，两个循环按列索引复用
        # 数学等价性：|x| 是纯函数，预计算不改变值；pandas/numpy .abs() 对 NaN 一致
        col_to_idx = {c: i for i, c in enumerate(factor_cols)}
        abs_icir_matrix = factor_df[rolling_icir_cols].to_numpy(dtype=float).copy()
        np.abs(abs_icir_matrix, out=abs_icir_matrix)  # 原地取绝对值

        # v2.50 (OOM fix): 不再逐列预分配 _dim_weight，改为 dict 收集后批量 concat
        dim_weight_data: dict[str, pd.Series] = {}

        # 维度内列索引预计算（避免循环内重复构建 dim_rolling_cols）
        dim_col_indices: dict[str, list[int]] = {}
        for dim, dim_cols in dimension_groups.items():
            dim_col_indices[dim] = [col_to_idx[c] for c in dim_cols]

        # 第一阶段：维度内归一化
        for dim, dim_cols in dimension_groups.items():
            indices = dim_col_indices[dim]
            dim_abs = abs_icir_matrix[:, indices]  # view，无 copy
            dim_icir_sum = pd.Series(dim_abs.sum(axis=1), index=factor_df.index)
            dim_icir_sum_safe = dim_icir_sum.replace(0, np.nan)

            for i, col in enumerate(dim_cols):
                # 复用预计算的 abs_icir_matrix 列，无需再次 .abs()
                intra_weight = pd.Series(
                    abs_icir_matrix[:, col_to_idx[col]] / dim_icir_sum_safe.to_numpy(),
                    index=factor_df.index,
                )
                # 维度内全为 0 或 NaN 时回退等权
                intra_weight = intra_weight.fillna(1.0 / len(dim_cols))

                if self.dimension_weight_method == "equal":
                    dim_weight_data[f"{col}_dim_weight"] = intra_weight * (1.0 / n_dims)
                elif self.dimension_weight_method == "icir":
                    dim_weight_data[f"{col}_dim_weight"] = intra_weight
                else:
                    dim_weight_data[f"{col}_dim_weight"] = intra_weight

        # icir 模式：第二阶段维度间归一化
        if self.dimension_weight_method == "icir":
            dim_avg_icir_cols = {}
            for dim, dim_cols in dimension_groups.items():
                indices = dim_col_indices[dim]
                dim_abs = abs_icir_matrix[:, indices]  # 复用，无重复分配
                # 维度内平均 |ICIR|（skipna=True，忽略 NaN 因子）
                dim_avg_icir = pd.Series(
                    np.nanmean(dim_abs, axis=1),  # nanmean 等价 skipna=True
                    index=factor_df.index,
                )
                dim_avg_icir_cols[dim] = dim_avg_icir

            del abs_icir_matrix  # 释放预计算矩阵（390MB）
            gc.collect()

            # 维度间归一化：dim_weight_d = avg_icir_d / Σ_avg_icir
            total_avg_icir = sum(dim_avg_icir_cols.values())
            total_avg_icir_safe = total_avg_icir.replace(0, np.nan)

            for dim, dim_cols in dimension_groups.items():
                dim_weight = dim_avg_icir_cols[dim] / total_avg_icir_safe
                # 全部维度 avg_icir 为 0 时回退等权
                dim_weight = dim_weight.fillna(1.0 / n_dims)

                for col in dim_cols:
                    # 最终权重 = 维度内权重 × 维度权重
                    dim_weight_data[f"{col}_dim_weight"] = dim_weight_data[f"{col}_dim_weight"] * dim_weight
        else:
            del abs_icir_matrix
            gc.collect()

        # v2.50: 批量 concat 添加所有 _dim_weight 列（无碎片化）
        factor_df = pd.concat([factor_df, pd.DataFrame(dim_weight_data, index=factor_df.index)], axis=1)

        # 对所有因子列的 _dim_weight 做行级归一化（确保每日权重和=1）
        # v2.52 (OOM 炸弹7, 模式3c): 向量化归一化替代逐列更新
        # 原实现 for col: factor_df[wcol] = factor_df[wcol] / total → 35 次 inplace update
        # 每次 update 让 BlockManager 创建新 Block → 碎片化 → 6.1GB OOM
        # 修复：矩阵化操作，一次性更新所有列
        dim_weight_cols = [f"{c}_dim_weight" for c in factor_cols]
        total_weight = factor_df[dim_weight_cols].sum(axis=1)
        total_weight_safe = total_weight.replace(0, np.nan)
        W = factor_df[dim_weight_cols].to_numpy(dtype=float)
        W = W / total_weight_safe.to_numpy(dtype=float)[:, None]
        # 全部为 0 时回退等权
        W = np.where(np.isnan(W), 1.0 / n_factors, W)
        # 一次性写回
        factor_df[dim_weight_cols] = W

        # 清理临时列
        if "weight_sum" in factor_df.columns:
            factor_df.drop(columns=["weight_sum"], inplace=True, errors="ignore")

        return factor_df

    def calculate(
        self,
        factor_df: pd.DataFrame,
        factor_cols: list[str],
        ic_results: dict[str, dict] | None = None,
        ic_daily_data: dict[str, pd.DataFrame] | None = None,
    ) -> pd.Series:
        """滚动ICIR加权计算

        v1.12 修复：
        - 删除重复校验（WeightEngine.calculate 已校验）
        - rolling_std 使用 ddof=0（总体标准差），避免样本少时不稳定
        - min_periods 使用 max(1, window // 3)，避免 window=1 时 min_periods=0
        """
        if ic_daily_data is None:
            raise ValueError("滚动ICIR加权需要 ic_daily_data 参数")

        # 构建每日 IC 数据（时间序列）
        # IC 是每日截面相关性，结构：{因子名: DataFrame(date, ic)}
        ic_series_dict = {}  # {因子列: IC时间序列}

        for col in factor_cols:
            # 使用基类公共方法提取因子名（贪婪匹配）
            factor_name = self._get_factor_name_from_col(col)

            if factor_name in ic_daily_data:
                ic_df = ic_daily_data[factor_name]
                # 确保 ic_df 有 date 和 ic 列
                if "date" in ic_df.columns and "ic" in ic_df.columns:
                    ic_series_dict[col] = ic_df.set_index("date")["ic"].sort_index()
                else:
                    self.logger.warning("因子 %s IC 数据缺少 date 或 ic 列", col)
                    ic_series_dict[col] = pd.Series(dtype=float)
            else:
                self.logger.warning("因子 %s 缺失 IC 每日数据", col)
                ic_series_dict[col] = pd.Series(dtype=float)

        # v1.12 修复：在时间轴上计算滚动 ICIR（而非按 asset 分组）
        # 滚动 ICIR = 滚动IC均值 / 滚动IC标准差
        rolling_icir_dict = {}  # {因子列: 滚动ICIR时间序列}

        # v1.12 修复：min_periods 使用 max(1, window // 3)，避免 window=1 时 min_periods=0
        min_periods = max(1, self.window // 3)

        for col, ic_series in ic_series_dict.items():
            if len(ic_series) > 0:
                # 时间轴滚动计算（每个因子一条 IC 时间序列）
                # v1.12 修复：使用 ddof=0（总体标准差），避免样本少时不稳定
                rolling_mean = ic_series.rolling(window=self.window, min_periods=min_periods).mean()
                rolling_std = ic_series.rolling(window=self.window, min_periods=min_periods).std(ddof=0)
                rolling_icir = rolling_mean / rolling_std.replace(0, np.nan)
                rolling_icir_dict[col] = rolling_icir
            else:
                # 缺失 IC 数据，使用 NaN
                rolling_icir_dict[col] = pd.Series(dtype=float)

        # 构建 factor_df 的日期索引
        # v2.49 (OOM fix): 提取精简工作 DataFrame，避免在 72 列宽表上 copy + 逐列 insert 导致碎片化
        # 原代码 factor_df = factor_df.copy() 复制了 72 列 × 1.39M 行 ≈ 766MB 完整宽表，
        # 随后逐列 insert 72 个中间列（_rolling_icir×35 + _dim_weight×35 + weight_sum + date_sorted），
        # pandas BlockManager 重度碎片化使实际内存膨胀到理论值 ~3x → 6.48GB OOM。
        # 修复：只提取 calculate 实际需要的列（date + _std），在精简 DataFrame 上操作。
        # 预计峰值从 ~6.48GB 降至 ~2.8GB（省 copy 766MB + 减少碎片化 ~1.5GB + 减少列数）。
        # 后续代码访问的原始列仅有 date 和 _std 列（已验证 L1341-1577 所有访问点）。
        std_cols = [f"{col}_std" for col in factor_cols]
        work_cols = ["date"] + [c for c in std_cols if c in factor_df.columns]
        factor_df = factor_df[work_cols].copy()
        factor_df["date_sorted"] = pd.to_datetime(factor_df["date"])

        # v1.11 修复：lambda 延迟绑定问题
        # 原实现：lambda 捕获循环变量 rolling_icir_series，循环结束后指向最后一个因子
        # 修复：使用 pandas.Series.map 直接映射（无需 lambda，无延迟绑定）

        # 将滚动 ICIR 映射到 factor_df（每个日期的所有股票共享同一个滚动 ICIR）
        # v1.13 修复：日期类型不匹配 bug
        # - rolling_icir_dict[col] 的索引是字符串日期（如 '2024-03-27'）
        # - factor_df['date_sorted'] 是 datetime 类型
        # - datetime 与字符串无法匹配，导致 map 返回 NaN，回退等权
        # - 修复：将 rolling_icir_series 索引也转换为 datetime 类型
        # v2.50 (OOM fix): 批量构建 _rolling_icir 列，用 pd.concat 一次性添加
        # 原实现逐列 factor_df[col] = ... 导致 BlockManager 碎片化（35 因子 × 72 次 insert）
        # 碎片化使实际内存膨胀到理论值 ~2.5x → 6.3GB OOM (require_positive_ic=False, 35 因子)
        # 修复：先在 dict 中收集所有新列，最后 pd.concat 一次添加，无碎片化
        # designs/feat_report_bottom30.md (同源 OOM 修复)
        new_cols: dict[str, pd.Series] = {}

        for col in factor_cols:
            if col in rolling_icir_dict and len(rolling_icir_dict[col]) > 0:
                rolling_icir_series = rolling_icir_dict[col]
                # v1.13 修复：索引类型转换（字符串 → datetime）
                rolling_icir_series_dt = rolling_icir_series.copy()
                rolling_icir_series_dt.index = pd.to_datetime(rolling_icir_series_dt.index)
                new_cols[f"{col}_rolling_icir"] = factor_df["date_sorted"].map(rolling_icir_series_dt)
            else:
                new_cols[f"{col}_rolling_icir"] = pd.Series(np.nan, index=factor_df.index)

        # 一次性 concat 添加所有 _rolling_icir 列（无碎片化）
        factor_df = pd.concat([factor_df, pd.DataFrame(new_cols, index=factor_df.index)], axis=1)
        del new_cols
        gc.collect()

        # v1.19 修复：T-1 rolling ICIR NaN 权重回退策略（遵循 design.md）
        # 问题: 选股日 T-1 无次日收益 → IC 无法计算 → rolling ICIR 全 NaN → fillna(1/n) 等权
        # 导致 momentum_strength 权重从 ICIR 的 2.2% 膨胀到 12.5%（+568%），使近期大跌股排名虚高
        # 修复: 对有 IC 序列的因子，用该序列最后一个有效值填充 T-1 NaN；
        #   对无 IC 序列的因子（短样本全 NaN），保留 NaN → fillna(1/n) 兜底
        # 注意: 不使用 ffill()，因为 factor_df 不保证按日期排序， ffill() 可能按行序而非时间序填充
        # 规范引用: MODULE.md M7/M40（滚动 ICIR 时间轴）
        for col in factor_cols:
            rolling_col = f"{col}_rolling_icir"
            # 对有 IC 序列的因子：用序列最后一个有效值填充 T-1 NaN
            if col in rolling_icir_dict and len(rolling_icir_dict[col]) > 0:
                # rolling_icir_dict[col] 的最后有效值 = 最近日期的 rolling ICIR（通常是 T-2）
                ic_series = rolling_icir_dict[col]
                last_valid_icir = ic_series.dropna().iloc[-1] if len(ic_series.dropna()) > 0 else None
                if last_valid_icir is not None:
                    # T-1 的 map 结果为 NaN → 用 last_valid_icir 匉日期条件填充
                    is_t1_nan = factor_df[rolling_col].isna() & (
                        factor_df["date_sorted"] == factor_df["date_sorted"].max()
                    )
                    factor_df.loc[is_t1_nan, rolling_col] = abs(last_valid_icir)

        # 每日计算权重并加权
        rolling_icir_cols = [f"{col}_rolling_icir" for col in factor_cols]

        # v1.20: 维度级别权重分配
        # 当 dimension_weight_method 非空且 factor_categories 可用时，
        # 将单阶段 |icir|/Σ_all 改为两阶段：维度内归一化 → 维度间归一化
        dimension_groups = self._build_dimension_groups(factor_cols)

        if dimension_groups and self.dimension_weight_method:
            # 两阶段权重：每个日期的每个因子计算维度感知权重
            factor_df = self._apply_dimension_weights(factor_df, factor_cols, rolling_icir_cols, dimension_groups)
        else:
            # 原始逻辑：每日权重 = |rolling_icir| / sum(|rolling_icir|)
            factor_df["weight_sum"] = factor_df[rolling_icir_cols].abs().sum(axis=1)
            weight_sum_safe = factor_df["weight_sum"].replace(0, np.nan)
            # v2.50 (OOM fix): 批量构建 _dim_weight 列，避免逐列 insert 碎片化
            dim_weight_new_cols: dict[str, pd.Series] = {}
            for col, rolling_col in zip(factor_cols, rolling_icir_cols):
                weight = factor_df[rolling_col].abs() / weight_sum_safe
                weight = weight.fillna(1.0 / len(factor_cols))
                dim_weight_new_cols[f"{col}_dim_weight"] = weight
            factor_df = pd.concat([factor_df, pd.DataFrame(dim_weight_new_cols, index=factor_df.index)], axis=1)
            del dim_weight_new_cols

        # v2.53 (OOM fix, 模式3e 列清理): _dim_weight 列已计算完毕，
        # _rolling_icir 列（35列×1.39M=390MB）不再被后续加权循环使用。
        # 预计算 valid_mask（用于 _last_day_weights 查找次新有效日期）后立即释放。
        # 依赖点分析：
        #   1. _extract_weights_from_row 回退分支：无影响——_dim_weight 列已存在，
        #      L1547 has_dim_weights=True 永远不走 _rolling_icir 回退
        #   2. valid_rows 查找：预计算 boolean mask 替代列引用，语义一致
        valid_mask = factor_df[rolling_icir_cols].notna().any(axis=1)
        factor_df = factor_df.drop(columns=rolling_icir_cols)
        gc.collect()

        # v2.38: 行级单因子权重上限（design.md feat_interaction_exemption_and_weight_cap §4.3）
        # RollingICIR 每日动态权重 _dim_weight 可能某日某因子占比过高（如 amplitude_compression 43.7%）
        # 用 _cap_weight_matrix 对每行做 25% 截断+剩余比例摊分, 保持每行 sum=1.0

        # v2.40: 构建族索引（用于族级 cap）
        # 因子列名 → 族名 → 整数 ID
        family_id_map: dict[str, int] = {}
        family_indices: list[int] = []
        for col in factor_cols:
            factor_name = self._get_factor_name_from_col(col)
            family = _MODULE_FACTOR_FAMILIES.get(factor_name, "uncategorized_family")
            if family not in family_id_map:
                family_id_map[family] = len(family_id_map)
            family_indices.append(family_id_map[family])

        dim_weight_cols = [f"{col}_dim_weight" for col in factor_cols]
        W = factor_df[dim_weight_cols].to_numpy(dtype=float)
        # 仅对有效行（非全 NaN）进行 cap; NaN 会被 fillna(1/n) 保护
        W_capped = self._cap_weight_matrix(
            W,
            cap=WEIGHT_CAP_DEFAULT,
            factor_families=family_indices,
            family_cap=FAMILY_CAP_DEFAULT,
        )

        # v2.41 (r2c): 角色固定权重后处理 (与静态版 dict 实现同构)
        # 设计依据: designs/feat_r2c_role_weights_for_rolling_icir.md
        # 接通点: cap 之后, 写回 _dim_weight 列之前 (此时 W_capped 每行 sum=1.0, 干净入口)
        if getattr(self, "enable_role_weights", False):
            W_capped = self._apply_role_weights_matrix(W_capped, factor_cols)
            self.logger.info("RollingICIR 角色权重: primary 75%% + confirmation 25%% 均分 + filter 排除（每日动态）")

        # v2.52 (OOM 炸弹7, 模式3c): 批量写回 _dim_weight 列，避免逐列 insert 碎片化
        dim_weight_cols = [f"{col}_dim_weight" for col in factor_cols]
        factor_df[dim_weight_cols] = W_capped
        # 截断事件记录（统计层面）
        any_capped_mask = (W > WEIGHT_CAP_DEFAULT + 1e-12).any(axis=1)
        n_capped_rows = int(any_capped_mask.sum())
        if n_capped_rows > 0:
            self.logger.info(
                "RollingICIR 行级 cap=%.2f: %d/%d 行触发截断, 已摊分至剩余因子",
                WEIGHT_CAP_DEFAULT,
                n_capped_rows,
                len(W),
            )

        std_cols = [f"{col}_std" for col in factor_cols]

        # 向量化加权：每日动态权重
        composite = pd.Series(0.0, index=factor_df.index)
        valid_weight_per_row = pd.Series(0.0, index=factor_df.index)

        for col, std_col, rolling_col in zip(factor_cols, std_cols, rolling_icir_cols):
            # v1.20: 使用维度感知权重（_dim_weight 列由两阶段或原始逻辑统一生成）
            weight = factor_df[f"{col}_dim_weight"]

            # v1.14 修复：NaN 因子不传播到综合因子（与 _apply_weights 同逻辑）
            # 原实现：factor_df[std_col] * weight → NaN * weight = NaN → composite + NaN = NaN
            # 修复：NaN 加权值置为 0，同时累积有效权重用于行级归一化
            weighted_value = (factor_df[std_col] * weight).fillna(0)
            is_valid = factor_df[std_col].notna()
            composite = composite + weighted_value
            valid_weight_per_row = valid_weight_per_row + weight.where(is_valid, 0)

        # 行级归一化：有效加权值之和 / 有效权重之和（与 M29 规范一致）
        composite = composite / valid_weight_per_row.replace(0, np.nan)

        # v1.18: 提取最后一日滚动ICIR权重，供 composite_runner 展示使用
        # 修复（Pitfall #45）：
        #   RollingICIRWeightMethod.calculate() 在内部 copy 上计算 rolling_icir 列，
        #   但这些列不保留在调用方的 factor_df 中。
        #   composite_runner 方案A 检查 rolling_icir 列 → 不存在 → 跳过；
        #   方案B 调用 weight_engine.get_weights() → 但 weight_method=rolling_icir_weight
        #   → RollingICIRWeightMethod.get_weights() → 返回等权 1/n（不是真实权重）。
        #   修复方案：在 calculate() 内部直接从 factor_df copy 提取最后一日权重，
        #   存入 _last_day_weights 属性，composite_runner 直接读取。
        #
        # v1.18b: 修复日期对齐问题
        #   factor_df 最新日期 = T-1（有因子数据但无次日收益）
        #   IC 数据最新日期 = T-2（需要次日收益才能算 IC）
        #   → T-1 日期的 rolling_icir = NaN（map 时索引不存在）
        #   → _last_day_weights 全0 → 报告显示等权
        #   修复：查找 rolling_icir 非空的最晚日期（= T-2），而非 factor_df 的最大日期
        #
        # v1.18c: 修复 NaN→0% 问题（Pitfall #46）
        #   增量因子原则：不能因覆盖率低排除因子，有数据日期正常参与。
        #   calculate() line 531 对 NaN rolling_icir 回退 fillna(1/n)，
        #   但 _last_day_weights 提取时 NaN → 0.0 → 归一化后 0%，
        #   导致4个 tail 系因子显示0%而实际计算中是12.5%等权回退。
        #   修复：复用 calculate() 的权重计算逻辑，
        #   NaN 因子使用 1/n 回退（与 line 531 一致），再统一归一化。

        def _extract_weights_from_row(row, factor_cols_list):
            """从指定行提取有效权重

            v1.20: 优先使用 _dim_weight 列（维度感知权重已由
            _apply_dimension_weights 或原始逻辑计算好）。
            无 _dim_weight 列时回退到原始计算逻辑。
            """
            n_factors = len(factor_cols_list)

            # v1.20: 优先从 _dim_weight 列读取（两阶段或原始逻辑统一生成）
            dim_weight_cols = [f"{c}_dim_weight" for c in factor_cols_list]
            has_dim_weights = all(c in row.index for c in dim_weight_cols)

            if has_dim_weights:
                raw_weights = {}
                weight_sum = 0.0
                for col in factor_cols_list:
                    wcol = f"{col}_dim_weight"
                    raw_val = row.get(wcol)
                    factor_name = self._get_factor_name_from_col(col)
                    if pd.notna(raw_val) and float(raw_val) != 0.0:
                        raw_weights[factor_name] = float(raw_val)
                        weight_sum += float(raw_val)
                    else:
                        raw_weights[factor_name] = 0.0

                if weight_sum == 0:
                    return None

                # 归一化（确保总和=1.0）
                return {name: w / weight_sum for name, w in raw_weights.items()}

            # 回退：原始逻辑（无 _dim_weight 列时）
            weight_sum = 0.0
            for col in factor_cols_list:
                rolling_col = f"{col}_rolling_icir"
                raw_val = row.get(rolling_col)
                if pd.notna(raw_val):
                    weight_sum += abs(float(raw_val))

            if weight_sum == 0:
                return None

            raw_weights = {}
            for col in factor_cols_list:
                rolling_col = f"{col}_rolling_icir"
                raw_val = row.get(rolling_col)
                factor_name = self._get_factor_name_from_col(col)
                if pd.notna(raw_val):
                    raw_weights[factor_name] = abs(float(raw_val)) / weight_sum
                else:
                    raw_weights[factor_name] = 1.0 / n_factors

            total_raw = sum(raw_weights.values())
            return {name: w / total_raw for name, w in raw_weights.items()}

        # 查找目标日期：优先 factor_df 最大日期，其次 rolling_icir 非空的次新日期
        latest_date_sorted = factor_df["date_sorted"].max()
        latest_rows = factor_df[factor_df["date_sorted"] == latest_date_sorted]

        # 先尝试 factor_df 最大日期
        self._last_day_weights = {}
        if len(latest_rows) > 0:
            self._last_day_weights = _extract_weights_from_row(latest_rows.iloc[0], factor_cols) or {}

        # 最大日期无有效权重时（T-1 无 IC 数据），回退查找次新日期
        if not self._last_day_weights:
            # v2.53: valid_mask 在删除 _rolling_icir 列前预计算（L1457）
            valid_rows = factor_df[valid_mask]
            if len(valid_rows) > 0:
                last_valid_date = valid_rows["date_sorted"].max()
                last_valid_row = valid_rows[valid_rows["date_sorted"] == last_valid_date].iloc[0]
                self._last_day_weights = _extract_weights_from_row(last_valid_row, factor_cols) or {}
                if self._last_day_weights:
                    self.logger.info(
                        "最后一日无有效IC数据，使用次新有效日期 %s 的权重",
                        last_valid_date,
                    )
                else:
                    self.logger.warning("次新日期 %s 也无有效权重, last_day_weights 为空", last_valid_date)
            else:
                self.logger.warning("无任何日期有有效滚动ICIR数据, last_day_weights 为空")

        self.logger.info(
            "最后一日真实权重: %s",
            {k: f"{v:.2%}" for k, v in self._last_day_weights.items()},
        )

        return composite

    def get_weights(self, factor_cols: list[str], ic_results: dict[str, dict] | None = None) -> dict[str, float]:
        """滚动ICIR权重无法静态获取，返回等权作为默认

        v1.12 修复：删除冗余条件 or len(...) == 0
        """
        # v1.12 修复：not factor_cols 已涵盖空列表
        if not factor_cols:
            raise ValueError("因子列 factor_cols 为空，无法计算权重")

        n_factors = len(factor_cols)
        return dict.fromkeys(factor_cols, 1.0 / n_factors)


class WeightEngine:
    """加权计算引擎

    根据加权方式选择对应的加权方法类。
    """

    # v1.12 修复：定义默认窗口常量，避免硬编码
    DEFAULT_WINDOW = 60

    METHOD_MAP = {
        "equal_weight": EqualWeightMethod,
        "icir_weight": ICIRWeightMethod,
        "ic_weight": ICWeightMethod,
        "rolling_icir_weight": RollingICIRWeightMethod,
    }

    # window 参数适用的加权方式列表
    WINDOW_VALID_METHODS = ["rolling_icir_weight"]

    def __init__(
        self,
        weight_method: str,
        window: int = DEFAULT_WINDOW,  # v1.12 修复：使用常量而非硬编码
        logger: logging.Logger | None = None,
        dimension_weight_method: str | None = None,  # v1.20: 维度级别权重分配
        factor_categories: dict[str, str] | None = None,  # v1.20: 因子维度分类
        enable_role_weights: bool = True,  # v2.41 (R2): 角色固定权重
    ):
        if weight_method not in self.METHOD_MAP:
            raise ValueError(f"不支持的加权方式: {weight_method}，支持: {list(self.METHOD_MAP.keys())}")

        self.logger = logger or get_logger(__name__)

        # v1.12 修复：window 参数仅对 rolling_icir_weight 有效，使用常量比较
        if window != self.DEFAULT_WINDOW and weight_method not in self.WINDOW_VALID_METHODS:
            self.logger.warning(
                "window=%d 参数对 %s 加权方式无效，仅 rolling_icir_weight 支持窗口参数（默认 %d）",
                window,
                weight_method,
                self.DEFAULT_WINDOW,
            )

        # 创建加权方法实例
        method_class = self.METHOD_MAP[weight_method]
        if weight_method == "rolling_icir_weight":
            # v1.20: 透传维度权重参数
            self.method = method_class(
                window=window,
                logger=self.logger,
                dimension_weight_method=dimension_weight_method,
                factor_categories=factor_categories,
                enable_role_weights=enable_role_weights,  # v2.41 (R2)
            )
        else:
            # v2.35: P2 维度权重全方法支持——消除 rolling_icir 独享
            # M58(MODULE.md L1966): 维度权重是 WeightEngine 通用能力
            self.method = method_class(
                logger=self.logger,
                dimension_weight_method=dimension_weight_method,
                factor_categories=factor_categories,
                enable_role_weights=enable_role_weights,  # v2.41 (R2)
            )

        self.weight_method = weight_method
        self.window = window
        self.dimension_weight_method = dimension_weight_method  # v1.20

    def calculate(
        self,
        factor_df: pd.DataFrame,
        factor_cols: list[str],
        ic_results: dict[str, dict] | None = None,
        ic_daily_data: dict[str, pd.DataFrame] | None = None,
        short_sample_factors: dict[str, int] | None = None,  # v1.15: 短样本因子ICIR惩罚
    ) -> pd.Series:
        """计算综合因子

        v1.15: 新增 short_sample_factors 参数，传递给ICIR加权方法用于权重惩罚
        """
        # 修复：入口校验因子列非空
        if not factor_cols or len(factor_cols) == 0:
            raise ValueError("因子列 factor_cols 为空，无法计算综合因子")

        # v1.15: ICIR加权方法需要 short_sample_factors，其他方法忽略该参数
        if isinstance(self.method, ICIRWeightMethod) and short_sample_factors:
            return self.method.calculate(factor_df, factor_cols, ic_results, ic_daily_data, short_sample_factors)
        return self.method.calculate(factor_df, factor_cols, ic_results, ic_daily_data)

    def get_weights(
        self,
        factor_cols: list[str],
        ic_results: dict[str, dict] | None = None,
        short_sample_factors: dict[str, int] | None = None,
    ) -> dict[str, float]:
        """获取权重"""
        if isinstance(self.method, ICIRWeightMethod) and short_sample_factors:
            return self.method.get_weights(factor_cols, ic_results, short_sample_factors)
        return self.method.get_weights(factor_cols, ic_results)
