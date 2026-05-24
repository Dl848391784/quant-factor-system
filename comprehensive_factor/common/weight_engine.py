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
"""

import numpy as np
import pandas as pd
import logging
import re  # v1.11 修复：移至文件顶部（PEP 8 规范）
from abc import ABC, abstractmethod
from typing import Dict, List, Optional
from comprehensive_factor.common.logger_config import get_logger


class WeightMethodBase(ABC):
    """加权方法基类"""
    
    # 因子名到数据列名的映射（反向映射用于 IC 结果匹配）
    # v1.10 新增：提取公共映射，避免硬编码后缀
    FACTOR_NAME_TO_COL_MAP = {
        'rsi': 'rsi_6',
        'volume_ratio': 'volume_ratio_5',
        'kdj_j': 'kdj_j_9',
        'bollinger_pb': 'bollinger_pb_20',
        'turnover_surge': 'turnover_surge_5',
        'main_inflow_ratio': 'main_inflow_ratio_1d'
    }
    
    # 反向映射：列名 → 因子名
    COL_TO_FACTOR_NAME_MAP = {v: k for k, v in FACTOR_NAME_TO_COL_MAP.items()}
    
    # v1.12 修复：正则预编译（贪婪匹配，避免错误截断）
    # 原正则 (.+?)_\d+[a-z]?$ 非贪婪，会错误截断 main_inflow_ratio_1d → main_inflow
    # 修复：贪婪匹配 (.+) 匹配最长前缀，正确截断 → main_inflow_ratio
    _FACTOR_SUFFIX_PATTERN = re.compile(r'(.+)_(?:\d+[a-z]?|\d+)$')  # 支持 _5, _6, _1d, _20 等
    
    def _get_factor_name_from_col(self, col: str) -> str:
        """从因子列名提取因子名（用于 IC 结果匹配）
        
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
    
    def _validate_factor_cols(self, factor_cols: List[str], logger: logging.Logger) -> None:
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
        factor_cols: List[str],
        weights: Dict[str, float],
        logger: logging.Logger,
        method_name: str = "加权"
    ) -> pd.Series:
        """应用权重计算综合因子（向量化实现 + NaN动态权重调整）
        
        Args:
            factor_df: 因子 DataFrame
            factor_cols: 因子列名（原始列名）
            weights: 权重字典 {因子列: 权重}
            logger: 日志对象
            method_name: 加权方式名称（日志用）
        
        Returns:
            综合因子 Series
        
        v1.11 修复：NaN 动态权重调整
        - 原实现：sum(axis=1) 将 NaN 计为 0，导致综合因子偏低
        - 修复：动态调整有效权重，使有效因子的权重之和始终为 1
        """
        # 使用标准化因子列
        std_cols = [f'{col}_std' for col in factor_cols]
        
        # 校验列存在性
        missing_cols = [col for col in std_cols if col not in factor_df.columns]
        if missing_cols:
            raise ValueError(f"标准化因子列缺失: {missing_cols}")
        
        # 向量化加权求和（而非循环）
        # 构建权重向量
        weight_values = np.array([weights[col] for col in factor_cols])
        
        # 构建 DataFrame（标准化因子列）
        std_df = factor_df[std_cols]
        
        # v1.11 修复：NaN 动态权重调整
        # 识别有效值（非 NaN）位置
        valid_mask = ~std_df.isna()
        
        # 计算每行的有效权重之和（用于归一化）
        # 每行有效权重 = weight_values * valid_mask，然后求和
        valid_weight_sum = (valid_mask.multiply(weight_values, axis=1)).sum(axis=1)
        
        # 构建 DataFrame：每列乘以权重，然后除以有效权重之和（归一化）
        weighted_df = std_df.multiply(weight_values, axis=1)
        
        # 归一化：weighted_df / valid_weight_sum（使权重之和为 1）
        # valid_weight_sum 为 0 时（全 NaN），保持 NaN
        composite = weighted_df.divide(valid_weight_sum.replace(0, np.nan), axis=0).sum(axis=1, skipna=False)
        
        # 全 NaN 行保持 NaN（而非 0）
        composite = composite.where(valid_weight_sum > 0, np.nan)
        
        logger.info("%s完成: 权重 %s，NaN处理=动态权重归一化", method_name, weights)
        
        return composite
    
    @abstractmethod
    def calculate(
        self,
        factor_df: pd.DataFrame,
        factor_cols: List[str],
        ic_results: Optional[Dict[str, Dict]] = None,
        ic_daily_data: Optional[Dict[str, pd.DataFrame]] = None
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
    def get_weights(
        self,
        factor_cols: List[str],
        ic_results: Optional[Dict[str, Dict]] = None
    ) -> Dict[str, float]:
        """获取权重字典
        
        Returns:
            Dict[因子列, 权重值]
        """
        pass


class EqualWeightMethod(WeightMethodBase):
    """等权加权
    
    weight = 1 / n_factors
    """
    
    def __init__(self, logger: Optional[logging.Logger] = None):
        self.logger = logger or get_logger(__name__)
    
    def calculate(
        self,
        factor_df: pd.DataFrame,
        factor_cols: List[str],
        ic_results: Optional[Dict[str, Dict]] = None,
        ic_daily_data: Optional[Dict[str, pd.DataFrame]] = None
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
    
    def get_weights(
        self,
        factor_cols: List[str],
        ic_results: Optional[Dict[str, Dict]] = None
    ) -> Dict[str, float]:
        """获取等权重
        
        v1.12 修复：删除冗余条件 or len(...) == 0
        """
        # v1.12 修复：not factor_cols 已涵盖空列表
        if not factor_cols:
            raise ValueError("因子列 factor_cols 为空，无法计算等权")
        
        n_factors = len(factor_cols)
        weight = 1.0 / n_factors
        return {col: weight for col in factor_cols}


class ICIRWeightMethod(WeightMethodBase):
    """ICIR加权（静态）
    
    weight_i = ICIR_i / sum(ICIR_j)
    
    注意：反向因子ICIR为负值，需要特殊处理。
    """
    
    def __init__(self, logger: Optional[logging.Logger] = None):
        self.logger = logger or get_logger(__name__)
    
    def calculate(
        self,
        factor_df: pd.DataFrame,
        factor_cols: List[str],
        ic_results: Optional[Dict[str, Dict]] = None,
        ic_daily_data: Optional[Dict[str, pd.DataFrame]] = None
    ) -> pd.Series:
        """ICIR加权计算
        
        v1.12 修复：删除重复校验（WeightEngine.calculate 已校验）
        """
        if ic_results is None:
            raise ValueError("ICIR加权需要 ic_results 参数")
        
        # 计算权重
        weights = self.get_weights(factor_cols, ic_results)
        
        # 使用基类公共方法（向量化实现）
        return self._apply_weights(factor_df, factor_cols, weights, self.logger, "ICIR加权")
    
    def get_weights(
        self,
        factor_cols: List[str],
        ic_results: Dict[str, Dict]
    ) -> Dict[str, float]:
        """获取ICIR权重
        
        处理负ICIR：
        - ICIR = IC均值/IC标准差，反映因子的预测稳定性
        - ICIR 绝对值越高，因子预测能力越稳定，权重越大
        
        实际 ICIR 值（见 factor_ic/result/*.json）：
        - volume_ratio: ICIR=0.3058（2024-03-27~2026-05-14）
        - rsi: ICIR=0.2519
        
        v1.12 修复：删除冗余条件 or len(...) == 0
        """
        # v1.12 修复：not factor_cols 已涵盖空列表
        if not factor_cols:
            raise ValueError("因子列 factor_cols 为空，无法计算ICIR权重")
        
        # 提取 ICIR 值（取绝对值）
        icir_values = {}
        for col in factor_cols:
            # 使用基类公共方法提取因子名（贪婪匹配）
            factor_name = self._get_factor_name_from_col(col)
            
            if factor_name in ic_results and 'icir' in ic_results[factor_name]:
                icir_values[col] = abs(ic_results[factor_name]['icir'])
            elif col in ic_results and 'icir' in ic_results[col]:
                icir_values[col] = abs(ic_results[col]['icir'])
            else:
                self.logger.warning("因子 %s 缺失 ICIR，使用等权默认值 1.0", col)
                icir_values[col] = 1.0  # 缺失时使用等权
        
        # 除零保护 - total_icir 为 0 时回退等权
        total_icir = sum(icir_values.values())
        if total_icir == 0:
            self.logger.warning("所有因子 ICIR 绝对值均为 0，回退等权")
            n_factors = len(factor_cols)
            return {col: 1.0 / n_factors for col in factor_cols}
        
        weights = {col: icir_values[col] / total_icir for col in factor_cols}
        
        return weights


class ICWeightMethod(WeightMethodBase):
    """IC均值加权（静态）
    
    weight_i = |ic_mean_i| / sum(|ic_mean_j|)
    
    使用绝对值：反向因子IC均值为负，取绝对值后加权。
    """
    
    def __init__(self, logger: Optional[logging.Logger] = None):
        self.logger = logger or get_logger(__name__)
    
    def calculate(
        self,
        factor_df: pd.DataFrame,
        factor_cols: List[str],
        ic_results: Optional[Dict[str, Dict]] = None,
        ic_daily_data: Optional[Dict[str, pd.DataFrame]] = None
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
    
    def get_weights(
        self,
        factor_cols: List[str],
        ic_results: Dict[str, Dict]
    ) -> Dict[str, float]:
        """获取IC权重
        
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
            
            if factor_name in ic_results and 'ic_mean' in ic_results[factor_name]:
                ic_values[col] = abs(ic_results[factor_name]['ic_mean'])
            elif col in ic_results and 'ic_mean' in ic_results[col]:
                ic_values[col] = abs(ic_results[col]['ic_mean'])
            else:
                self.logger.warning("因子 %s 缺失 IC 均值，使用等权默认值 1.0", col)
                ic_values[col] = 1.0
        
        # 除零保护 - total_ic 为 0 时回退等权
        total_ic = sum(ic_values.values())
        if total_ic == 0:
            self.logger.warning("所有因子 IC 均值绝对值均为 0，回退等权")
            n_factors = len(factor_cols)
            return {col: 1.0 / n_factors for col in factor_cols}
        
        weights = {col: ic_values[col] / total_ic for col in factor_cols}
        
        return weights


class RollingICIRWeightMethod(WeightMethodBase):
    """滚动ICIR加权（动态）
    
    每日计算滚动窗口内的 ICIR，动态调整权重。
    
    weight_i_t = |rolling_icir_i_t| / sum(|rolling_icir_j_t|)
    
    v1.10 修复：滚动 ICIR 应在时间轴上计算，而非按 asset 分组。
    IC 是每日截面相关性，同一日期所有股票的 IC 值相同。
    """
    
    def __init__(self, window: int = 60, logger: Optional[logging.Logger] = None):
        self.window = window
        self.logger = logger or get_logger(__name__)
    
    def calculate(
        self,
        factor_df: pd.DataFrame,
        factor_cols: List[str],
        ic_results: Optional[Dict[str, Dict]] = None,
        ic_daily_data: Optional[Dict[str, pd.DataFrame]] = None
    ) -> pd.Series:
        """滚动ICIR加权计算
        
        v1.12 修复：
        - 删除重复校验（WeightEngine.calculate 已校验）
        - rolling_std 使用 ddof=0（总体标准差），避免样本少时不稳定
        - min_periods 使用 max(1, window // 3)，避免 window=1 时 min_periods=0
        """
        if ic_daily_data is None:
            raise ValueError("滚动ICIR加权需要 ic_daily_data 参数")
        
        # 获取唯一日期序列（用于时间轴滚动）
        dates = factor_df['date'].unique()
        dates_sorted = sorted(dates)
        
        # 构建每日 IC 数据（时间序列）
        # IC 是每日截面相关性，结构：{因子名: DataFrame(date, ic)}
        ic_series_dict = {}  # {因子列: IC时间序列}
        
        for col in factor_cols:
            # 使用基类公共方法提取因子名（贪婪匹配）
            factor_name = self._get_factor_name_from_col(col)
            
            if factor_name in ic_daily_data:
                ic_df = ic_daily_data[factor_name]
                # 确保 ic_df 有 date 和 ic 列
                if 'date' in ic_df.columns and 'ic' in ic_df.columns:
                    ic_series_dict[col] = ic_df.set_index('date')['ic'].sort_index()
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
        factor_df['date_sorted'] = pd.to_datetime(factor_df['date'])
        
        # v1.11 修复：lambda 延迟绑定问题
        # 原实现：lambda 捕获循环变量 rolling_icir_series，循环结束后指向最后一个因子
        # 修复：使用 pandas.Series.map 直接映射（无需 lambda，无延迟绑定）
        
        # 将滚动 ICIR 映射到 factor_df（每个日期的所有股票共享同一个滚动 ICIR）
        for col in factor_cols:
            if col in rolling_icir_dict and len(rolling_icir_dict[col]) > 0:
                # 方法1：使用 pandas.Series.map 直接映射（无 lambda，无延迟绑定）
                rolling_icir_series = rolling_icir_dict[col]
                # Series.map(Series) 会用 date_sorted 的值在 rolling_icir_series 索引中查找
                factor_df[f'{col}_rolling_icir'] = factor_df['date_sorted'].map(rolling_icir_series)
            else:
                factor_df[f'{col}_rolling_icir'] = np.nan
        
        # 每日计算权重并加权
        rolling_icir_cols = [f'{col}_rolling_icir' for col in factor_cols]
        
        # 每日权重 = |rolling_icir| / sum(|rolling_icir|)
        factor_df['weight_sum'] = factor_df[rolling_icir_cols].abs().sum(axis=1)
        
        # 修复：除零保护 - weight_sum 为 0 时回退等权
        weight_sum_safe = factor_df['weight_sum'].replace(0, np.nan)
        
        # 使用基类公共方法计算加权（需要构建每日权重）
        std_cols = [f'{col}_std' for col in factor_cols]
        
        # 向量化加权：每日动态权重
        composite = pd.Series(0.0, index=factor_df.index)
        
        for col, std_col, rolling_col in zip(factor_cols, std_cols, rolling_icir_cols):
            # 每日权重 = |rolling_icir| / weight_sum（安全除零）
            weight = factor_df[rolling_col].abs() / weight_sum_safe
            weight = weight.fillna(1.0 / len(factor_cols))  # 除零或缺失时回退等权
            composite = composite + factor_df[std_col] * weight
        
        self.logger.info("滚动ICIR加权完成: 窗口 %d 日", self.window)
        
        return composite
    
    def get_weights(
        self,
        factor_cols: List[str],
        ic_results: Optional[Dict[str, Dict]] = None
    ) -> Dict[str, float]:
        """滚动ICIR权重无法静态获取，返回等权作为默认
        
        v1.12 修复：删除冗余条件 or len(...) == 0
        """
        # v1.12 修复：not factor_cols 已涵盖空列表
        if not factor_cols:
            raise ValueError("因子列 factor_cols 为空，无法计算权重")
        
        n_factors = len(factor_cols)
        return {col: 1.0 / n_factors for col in factor_cols}


class WeightEngine:
    """加权计算引擎
    
    根据加权方式选择对应的加权方法类。
    """
    
    # v1.12 修复：定义默认窗口常量，避免硬编码
    DEFAULT_WINDOW = 60
    
    METHOD_MAP = {
        'equal_weight': EqualWeightMethod,
        'icir_weight': ICIRWeightMethod,
        'ic_weight': ICWeightMethod,
        'rolling_icir_weight': RollingICIRWeightMethod
    }
    
    # window 参数适用的加权方式列表
    WINDOW_VALID_METHODS = ['rolling_icir_weight']
    
    def __init__(
        self,
        weight_method: str,
        window: int = DEFAULT_WINDOW,  # v1.12 修复：使用常量而非硬编码
        logger: Optional[logging.Logger] = None
    ):
        if weight_method not in self.METHOD_MAP:
            raise ValueError(f"不支持的加权方式: {weight_method}，支持: {list(self.METHOD_MAP.keys())}")
        
        self.logger = logger or get_logger(__name__)
        
        # v1.12 修复：window 参数仅对 rolling_icir_weight 有效，使用常量比较
        if window != self.DEFAULT_WINDOW and weight_method not in self.WINDOW_VALID_METHODS:
            self.logger.warning(
                "window=%d 参数对 %s 加权方式无效，仅 rolling_icir_weight 支持窗口参数（默认 %d）",
                window, weight_method, self.DEFAULT_WINDOW
            )
        
        # 创建加权方法实例
        method_class = self.METHOD_MAP[weight_method]
        if weight_method == 'rolling_icir_weight':
            self.method = method_class(window=window, logger=self.logger)
        else:
            self.method = method_class(logger=self.logger)
        
        self.weight_method = weight_method
        self.window = window
    
    def calculate(
        self,
        factor_df: pd.DataFrame,
        factor_cols: List[str],
        ic_results: Optional[Dict[str, Dict]] = None,
        ic_daily_data: Optional[Dict[str, pd.DataFrame]] = None
    ) -> pd.Series:
        """计算综合因子"""
        # 修复：入口校验因子列非空
        if not factor_cols or len(factor_cols) == 0:
            raise ValueError("因子列 factor_cols 为空，无法计算综合因子")
        
        return self.method.calculate(factor_df, factor_cols, ic_results, ic_daily_data)
    
    def get_weights(
        self,
        factor_cols: List[str],
        ic_results: Optional[Dict[str, Dict]] = None
    ) -> Dict[str, float]:
        """获取权重"""
        return self.method.get_weights(factor_cols, ic_results)