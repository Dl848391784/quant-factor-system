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
    
    def _get_factor_name_from_col(self, col: str) -> str:
        """从因子列名提取因子名（用于 IC 结果匹配）
        
        Args:
            col: 因子列名（如 'volume_ratio_5'）
        
        Returns:
            因子名（如 'volume_ratio'）
        
        Priority:
            1. 使用反向映射（精确匹配）
            2. 回退：移除常见后缀模式
        """
        # 优先使用反向映射
        if col in self.COL_TO_FACTOR_NAME_MAP:
            return self.COL_TO_FACTOR_NAME_MAP[col]
        
        # 回退：移除数字后缀（如 '_5', '_6', '_9', '_20'）
        # 使用正则移除所有数字后缀，而非硬编码特定后缀
        import re
        match = re.match(r'(.+?)_\d+[a-z]?$', col)  # 支持 _5, _6, _1d 等
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
        """
        if not factor_cols or len(factor_cols) == 0:
            raise ValueError("因子列 factor_cols 为空，无法计算加权")
    
    def _apply_weights(
        self,
        factor_df: pd.DataFrame,
        factor_cols: List[str],
        weights: Dict[str, float],
        logger: logging.Logger,
        method_name: str = "加权"
    ) -> pd.Series:
        """应用权重计算综合因子（向量化实现）
        
        Args:
            factor_df: 因子 DataFrame
            factor_cols: 因子列名（原始列名）
            weights: 权重字典 {因子列: 权重}
            logger: 日志对象
            method_name: 加权方式名称（日志用）
        
        Returns:
            综合因子 Series
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
        
        # 向量化加权：DataFrame * 权重向量，然后按列求和
        composite = std_df.multiply(weight_values, axis=1).sum(axis=1)
        
        logger.info("%s完成: 权重 %s", method_name, weights)
        
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
        """等权加权计算"""
        # 修复：入口校验因子列非空
        self._validate_factor_cols(factor_cols, self.logger)
        
        # 计算权重
        weights = self.get_weights(factor_cols, ic_results)
        
        # 修复：使用基类公共方法（向量化实现）
        return self._apply_weights(factor_df, factor_cols, weights, self.logger, "等权加权")
    
    def get_weights(
        self,
        factor_cols: List[str],
        ic_results: Optional[Dict[str, Dict]] = None
    ) -> Dict[str, float]:
        """获取等权重"""
        # 修复：校验因子列非空
        if not factor_cols or len(factor_cols) == 0:
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
        """ICIR加权计算"""
        if ic_results is None:
            raise ValueError("ICIR加权需要 ic_results 参数")
        
        # 修复：入口校验因子列非空
        self._validate_factor_cols(factor_cols, self.logger)
        
        # 计算权重
        weights = self.get_weights(factor_cols, ic_results)
        
        # 修复：使用基类公共方法（向量化实现）
        return self._apply_weights(factor_df, factor_cols, weights, self.logger, "ICIR加权")
    
    def get_weights(
        self,
        factor_cols: List[str],
        ic_results: Dict[str, Dict]
    ) -> Dict[str, float]:
        """获取ICIR权重
        
        处理负ICIR：
        - 反向因子ICIR为负（如 volume_ratio ICIR ≈ -1.97）
        - 取绝对值后加权：|ICIR| 高的因子权重大
        """
        # 修复：校验因子列非空
        if not factor_cols or len(factor_cols) == 0:
            raise ValueError("因子列 factor_cols 为空，无法计算ICIR权重")
        
        # 提取 ICIR 值（取绝对值）
        icir_values = {}
        for col in factor_cols:
            # 修复：使用基类公共方法提取因子名（而非硬编码后缀）
            factor_name = self._get_factor_name_from_col(col)
            
            if factor_name in ic_results and 'icir' in ic_results[factor_name]:
                icir_values[col] = abs(ic_results[factor_name]['icir'])
            elif col in ic_results and 'icir' in ic_results[col]:
                icir_values[col] = abs(ic_results[col]['icir'])
            else:
                self.logger.warning("因子 %s 缺失 ICIR，使用等权默认值 1.0", col)
                icir_values[col] = 1.0  # 缺失时使用等权
        
        # 修复：除零保护 - total_icir 为 0 时回退等权
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
        """IC均值加权计算"""
        if ic_results is None:
            raise ValueError("IC加权需要 ic_results 参数")
        
        # 修复：入口校验因子列非空
        self._validate_factor_cols(factor_cols, self.logger)
        
        # 计算权重
        weights = self.get_weights(factor_cols, ic_results)
        
        # 修复：使用基类公共方法（向量化实现）
        return self._apply_weights(factor_df, factor_cols, weights, self.logger, "IC加权")
    
    def get_weights(
        self,
        factor_cols: List[str],
        ic_results: Dict[str, Dict]
    ) -> Dict[str, float]:
        """获取IC权重"""
        # 修复：校验因子列非空
        if not factor_cols or len(factor_cols) == 0:
            raise ValueError("因子列 factor_cols 为空，无法计算IC权重")
        
        # 提取 IC 均值（取绝对值）
        ic_values = {}
        for col in factor_cols:
            # 修复：使用基类公共方法提取因子名（而非硬编码后缀）
            factor_name = self._get_factor_name_from_col(col)
            
            if factor_name in ic_results and 'ic_mean' in ic_results[factor_name]:
                ic_values[col] = abs(ic_results[factor_name]['ic_mean'])
            elif col in ic_results and 'ic_mean' in ic_results[col]:
                ic_values[col] = abs(ic_results[col]['ic_mean'])
            else:
                self.logger.warning("因子 %s 缺失 IC 均值，使用等权默认值 1.0", col)
                ic_values[col] = 1.0
        
        # 修复：除零保护 - total_ic 为 0 时回退等权
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
        """滚动ICIR加权计算"""
        if ic_daily_data is None:
            raise ValueError("滚动ICIR加权需要 ic_daily_data 参数")
        
        # 修复：入口校验因子列非空
        self._validate_factor_cols(factor_cols, self.logger)
        
        # 获取唯一日期序列（用于时间轴滚动）
        dates = factor_df['date'].unique()
        dates_sorted = sorted(dates)
        
        # 构建每日 IC 数据（时间序列）
        # IC 是每日截面相关性，结构：{因子名: DataFrame(date, ic)}
        ic_series_dict = {}  # {因子列: IC时间序列}
        
        for col in factor_cols:
            # 修复：使用基类公共方法提取因子名
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
        
        # 修复：在时间轴上计算滚动 ICIR（而非按 asset 分组）
        # 滚动 ICIR = 滚动IC均值 / 滚动IC标准差
        rolling_icir_dict = {}  # {因子列: 滚动ICIR时间序列}
        
        for col, ic_series in ic_series_dict.items():
            if len(ic_series) > 0:
                # 时间轴滚动计算（每个因子一条 IC 时间序列）
                rolling_mean = ic_series.rolling(window=self.window, min_periods=self.window // 3).mean()
                rolling_std = ic_series.rolling(window=self.window, min_periods=self.window // 3).std()
                rolling_icir = rolling_mean / rolling_std.replace(0, np.nan)
                rolling_icir_dict[col] = rolling_icir
            else:
                # 缺失 IC 数据，使用 NaN
                rolling_icir_dict[col] = pd.Series(dtype=float)
        
        # 构建 factor_df 的日期索引
        factor_df = factor_df.copy()
        factor_df['date_sorted'] = pd.to_datetime(factor_df['date'])
        
        # 将滚动 ICIR 映射到 factor_df（每个日期的所有股票共享同一个滚动 ICIR）
        for col in factor_cols:
            if col in rolling_icir_dict and len(rolling_icir_dict[col]) > 0:
                # 按日期映射：同一天所有股票使用同一个滚动 ICIR
                rolling_icir_series = rolling_icir_dict[col]
                factor_df[f'{col}_rolling_icir'] = factor_df['date_sorted'].map(
                    lambda d: rolling_icir_series.get(pd.Timestamp(d), np.nan)
                )
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
        """滚动ICIR权重无法静态获取，返回等权作为默认"""
        # 修复：校验因子列非空
        if not factor_cols or len(factor_cols) == 0:
            raise ValueError("因子列 factor_cols 为空，无法计算权重")
        
        n_factors = len(factor_cols)
        return {col: 1.0 / n_factors for col in factor_cols}


class WeightEngine:
    """加权计算引擎
    
    根据加权方式选择对应的加权方法类。
    """
    
    METHOD_MAP = {
        'equal_weight': EqualWeightMethod,
        'icir_weight': ICIRWeightMethod,
        'ic_weight': ICWeightMethod,
        'rolling_icir_weight': RollingICIRWeightMethod
    }
    
    # v1.10 新增：window 参数适用的加权方式列表
    WINDOW_VALID_METHODS = ['rolling_icir_weight']
    
    def __init__(
        self,
        weight_method: str,
        window: int = 60,
        logger: Optional[logging.Logger] = None
    ):
        if weight_method not in self.METHOD_MAP:
            raise ValueError(f"不支持的加权方式: {weight_method}，支持: {list(self.METHOD_MAP.keys())}")
        
        self.logger = logger or get_logger(__name__)
        
        # 修复：window 参数仅对 rolling_icir_weight 有效，其他方式提示警告
        if window != 60 and weight_method not in self.WINDOW_VALID_METHODS:
            self.logger.warning(
                "window=%d 参数对 %s 加权方式无效，仅 rolling_icir_weight 支持窗口参数",
                window, weight_method
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