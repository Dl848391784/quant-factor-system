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
    FACTOR_NAME_TO_COL_MAP as _MODULE_NAME_TO_COL_MAP,
)


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
        """应用权重计算综合因子（向量化实现 + 缺失因子中性填充）

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
        """
        # 使用标准化因子列
        std_cols = [f"{col}_std" for col in factor_cols]

        # 校验列存在性
        missing_cols = [col for col in std_cols if col not in factor_df.columns]
        if missing_cols:
            raise ValueError(f"标准化因子列缺失: {missing_cols}")

        # 向量化加权求和
        # 构建权重向量
        weight_values = np.array([weights[col] for col in factor_cols])

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

        logger.info("%s完成: 权重 %s，NaN处理=中性填充(z=0)", method_name, weights)

        return composite

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

    def __init__(self, logger: logging.Logger | None = None):
        self.logger = logger or get_logger(__name__)

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
        """
        # 计算权重
        weights = self.get_weights(factor_cols, ic_results)

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

    def __init__(self, logger: logging.Logger | None = None):
        self.logger = logger or get_logger(__name__)

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
        """
        if ic_results is None:
            raise ValueError("ICIR加权需要 ic_results 参数")

        # 计算权重（v1.15: 传入短样本因子信息）
        weights = self.get_weights(factor_cols, ic_results, short_sample_factors)

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

    def __init__(self, logger: logging.Logger | None = None):
        self.logger = logger or get_logger(__name__)

    def calculate(
        self,
        factor_df: pd.DataFrame,
        factor_cols: list[str],
        ic_results: dict[str, dict] | None = None,
        ic_daily_data: dict[str, pd.DataFrame] | None = None,
    ) -> pd.Series:
        """IC均值加权计算

        v1.12 修复：删除重复校验（WeightEngine.calculate 已校验）
        """
        if ic_results is None:
            raise ValueError("IC加权需要 ic_results 参数")

        # 计算权重
        weights = self.get_weights(factor_cols, ic_results)

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
    ):
        self.window = window
        self.logger = logger or get_logger(__name__)
        self._last_day_weights: dict[str, float] = {}  # v1.18: calculate() 后填充
        # v1.20: 维度级别权重分配
        self.dimension_weight_method = dimension_weight_method
        self.factor_categories = factor_categories

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

        # 为每个因子列预分配 _dim_weight 列
        for col in factor_cols:
            factor_df[f"{col}_dim_weight"] = 0.0

        # 向量化实现：逐维度处理
        for dim, dim_cols in dimension_groups.items():
            dim_rolling_cols = [f"{c}_rolling_icir" for c in dim_cols]

            # 维度内 |ICIR| 绝对值
            dim_abs_icir = factor_df[dim_rolling_cols].abs()
            dim_icir_sum = dim_abs_icir.sum(axis=1)  # 每行的维度内 |ICIR| 之和

            # 第一阶段：维度内归一化
            dim_icir_sum_safe = dim_icir_sum.replace(0, np.nan)
            for col in dim_cols:
                rolling_col = f"{col}_rolling_icir"
                intra_weight = factor_df[rolling_col].abs() / dim_icir_sum_safe
                # 维度内全为 0 或 NaN 时回退等权
                intra_weight = intra_weight.fillna(1.0 / len(dim_cols))

                if self.dimension_weight_method == "equal":
                    # equal: 维度等权 1/n_dims
                    factor_df[f"{col}_dim_weight"] = intra_weight * (1.0 / n_dims)
                elif self.dimension_weight_method == "icir":
                    # icir: 维度权重 = 维度内平均|ICIR| / Σ_dim_avg
                    # 维度内平均 |ICIR| = dim_icir_sum / n_factors_in_dim
                    # 但需要所有维度的平均|ICIR| 才能归一化，暂存中间结果
                    factor_df[f"{col}_dim_weight"] = intra_weight
                else:
                    factor_df[f"{col}_dim_weight"] = intra_weight

        # icir 模式：第二阶段维度间归一化
        if self.dimension_weight_method == "icir":
            # 计算每个维度每个日期的"平均|ICIR|"
            dim_avg_icir_cols = {}
            for dim, dim_cols in dimension_groups.items():
                dim_rolling_cols = [f"{c}_rolling_icir" for c in dim_cols]
                dim_abs_icir = factor_df[dim_rolling_cols].abs()
                # 维度内平均 |ICIR|（skipna=True，忽略 NaN 因子）
                dim_avg_icir = dim_abs_icir.mean(axis=1, skipna=True)
                dim_avg_icir_cols[dim] = dim_avg_icir

            # 维度间归一化：dim_weight_d = avg_icir_d / Σ_avg_icir
            total_avg_icir = sum(dim_avg_icir_cols.values())
            total_avg_icir_safe = total_avg_icir.replace(0, np.nan)

            for dim, dim_cols in dimension_groups.items():
                dim_weight = dim_avg_icir_cols[dim] / total_avg_icir_safe
                # 全部维度 avg_icir 为 0 时回退等权
                dim_weight = dim_weight.fillna(1.0 / n_dims)

                for col in dim_cols:
                    # 最终权重 = 维度内权重 × 维度权重
                    factor_df[f"{col}_dim_weight"] = factor_df[f"{col}_dim_weight"] * dim_weight

        # 对所有因子列的 _dim_weight 做行级归一化（确保每日权重和=1）
        dim_weight_cols = [f"{c}_dim_weight" for c in factor_cols]
        total_weight = factor_df[dim_weight_cols].sum(axis=1)
        total_weight_safe = total_weight.replace(0, np.nan)
        for col in factor_cols:
            wcol = f"{col}_dim_weight"
            factor_df[wcol] = factor_df[wcol] / total_weight_safe
            # 全部为 0 时回退等权
            factor_df[wcol] = factor_df[wcol].fillna(1.0 / n_factors)

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
        factor_df = factor_df.copy()
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
        for col in factor_cols:
            if col in rolling_icir_dict and len(rolling_icir_dict[col]) > 0:
                rolling_icir_series = rolling_icir_dict[col]
                # v1.13 修复：索引类型转换（字符串 → datetime）
                rolling_icir_series_dt = rolling_icir_series.copy()
                rolling_icir_series_dt.index = pd.to_datetime(rolling_icir_series_dt.index)
                factor_df[f"{col}_rolling_icir"] = factor_df["date_sorted"].map(rolling_icir_series_dt)
            else:
                factor_df[f"{col}_rolling_icir"] = np.nan

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
            for col, rolling_col in zip(factor_cols, rolling_icir_cols):
                weight = factor_df[rolling_col].abs() / weight_sum_safe
                weight = weight.fillna(1.0 / len(factor_cols))
                factor_df[f"{col}_dim_weight"] = weight

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
            valid_rows = factor_df[factor_df[rolling_icir_cols].notna().any(axis=1)]
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
            )
        else:
            self.method = method_class(logger=self.logger)

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
