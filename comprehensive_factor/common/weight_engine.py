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
        n_factors = len(factor_cols)
        weight = 1.0 / n_factors
        
        # 使用标准化因子列
        std_cols = [f'{col}_std' for col in factor_cols]
        
        # 加权求和
        composite = factor_df[std_cols[0]] * weight
        for col in std_cols[1:]:
            composite = composite + factor_df[col] * weight
        
        self.logger.info("等权加权完成: %d 个因子，权重 %.4f", n_factors, weight)
        
        return composite
    
    def get_weights(
        self,
        factor_cols: List[str],
        ic_results: Optional[Dict[str, Dict]] = None
    ) -> Dict[str, float]:
        """获取等权重"""
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
        
        # 计算权重
        weights = self.get_weights(factor_cols, ic_results)
        
        # 使用标准化因子列
        std_cols = [f'{col}_std' for col in factor_cols]
        
        # 加权求和
        composite = factor_df[std_cols[0]] * weights[factor_cols[0]]
        for col, std_col in zip(factor_cols[1:], std_cols[1:]):
            composite = composite + factor_df[std_col] * weights[col]
        
        self.logger.info("ICIR加权完成: 权重 %s", weights)
        
        return composite
    
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
        # 提取 ICIR 值（取绝对值）
        icir_values = {}
        for col in factor_cols:
            # 因子列名可能与 IC 文件名不同（如 volume_ratio_5 vs volume_ratio）
            # 尝试多种匹配方式
            factor_name = col.replace('_5', '').replace('_6', '')  # 移除周期后缀
            
            if factor_name in ic_results and 'icir' in ic_results[factor_name]:
                icir_values[col] = abs(ic_results[factor_name]['icir'])
            elif col in ic_results and 'icir' in ic_results[col]:
                icir_values[col] = abs(ic_results[col]['icir'])
            else:
                self.logger.warning("因子 %s 缺失 ICIR，使用等权", col)
                icir_values[col] = 1.0  # 缺失时使用等权
        
        # 计算权重
        total_icir = sum(icir_values.values())
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
        
        # 计算权重
        weights = self.get_weights(factor_cols, ic_results)
        
        # 使用标准化因子列
        std_cols = [f'{col}_std' for col in factor_cols]
        
        # 加权求和
        composite = factor_df[std_cols[0]] * weights[factor_cols[0]]
        for col, std_col in zip(factor_cols[1:], std_cols[1:]):
            composite = composite + factor_df[std_col] * weights[col]
        
        self.logger.info("IC加权完成: 权重 %s", weights)
        
        return composite
    
    def get_weights(
        self,
        factor_cols: List[str],
        ic_results: Dict[str, Dict]
    ) -> Dict[str, float]:
        """获取IC权重"""
        # 提取 IC 均值（取绝对值）
        ic_values = {}
        for col in factor_cols:
            factor_name = col.replace('_5', '').replace('_6', '')
            
            if factor_name in ic_results and 'ic_mean' in ic_results[factor_name]:
                ic_values[col] = abs(ic_results[factor_name]['ic_mean'])
            elif col in ic_results and 'ic_mean' in ic_results[col]:
                ic_values[col] = abs(ic_results[col]['ic_mean'])
            else:
                self.logger.warning("因子 %s 缺失 IC 均值，使用等权", col)
                ic_values[col] = 1.0
        
        # 计算权重
        total_ic = sum(ic_values.values())
        weights = {col: ic_values[col] / total_ic for col in factor_cols}
        
        return weights


class RollingICIRWeightMethod(WeightMethodBase):
    """滚动ICIR加权（动态）
    
    每日计算滚动窗口内的 ICIR，动态调整权重。
    
    weight_i_t = |rolling_icir_i_t| / sum(|rolling_icir_j_t|)
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
        
        # 合并 IC 每日数据到 factor_df
        factor_df = factor_df.copy()
        
        for col in factor_cols:
            factor_name = col.replace('_5', '').replace('_6', '')
            
            if factor_name in ic_daily_data:
                ic_df = ic_daily_data[factor_name]
                # 重命名 ic 列
                ic_df = ic_df.rename(columns={'ic': f'{col}_ic'})
                factor_df = factor_df.merge(ic_df[['date', f'{col}_ic']], on='date', how='left')
            else:
                self.logger.warning("因子 %s 缺失 IC 每日数据", col)
                factor_df[f'{col}_ic'] = np.nan
        
        # 每日计算滚动 ICIR
        for col in factor_cols:
            ic_col = f'{col}_ic'
            
            # 滚动 ICIR = 滚动IC均值 / 滚动IC标准差
            factor_df[f'{col}_rolling_icir'] = factor_df.groupby('asset')[ic_col].transform(
                lambda x: x.rolling(window=self.window, min_periods=self.window // 3).mean() /
                          x.rolling(window=self.window, min_periods=self.window // 3).std()
            )
        
        # 每日计算权重并加权
        std_cols = [f'{col}_std' for col in factor_cols]
        rolling_icir_cols = [f'{col}_rolling_icir' for col in factor_cols]
        
        # 每日权重 = |rolling_icir| / sum(|rolling_icir|)
        factor_df['weight_sum'] = factor_df[rolling_icir_cols].abs().sum(axis=1)
        
        composite = pd.Series(0.0, index=factor_df.index)
        for std_col, rolling_col, col in zip(std_cols, rolling_icir_cols, factor_cols):
            # 权重 = |rolling_icir| / sum，避免除零
            weight = factor_df[rolling_col].abs() / factor_df['weight_sum'].replace(0, np.nan)
            weight = weight.fillna(1.0 / len(factor_cols))  # 除零时回退等权
            composite = composite + factor_df[std_col] * weight
        
        self.logger.info("滚动ICIR加权完成: 窗口 %d 日", self.window)
        
        return composite
    
    def get_weights(
        self,
        factor_cols: List[str],
        ic_results: Optional[Dict[str, Dict]] = None
    ) -> Dict[str, float]:
        """滚动ICIR权重无法静态获取，返回等权作为默认"""
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
    
    def __init__(
        self,
        weight_method: str,
        window: int = 60,
        logger: Optional[logging.Logger] = None
    ):
        if weight_method not in self.METHOD_MAP:
            raise ValueError(f"不支持的加权方式: {weight_method}，支持: {list(self.METHOD_MAP.keys())}")
        
        self.logger = logger or get_logger(__name__)
        
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
        return self.method.calculate(factor_df, factor_cols, ic_results, ic_daily_data)
    
    def get_weights(
        self,
        factor_cols: List[str],
        ic_results: Optional[Dict[str, Dict]] = None
    ) -> Dict[str, float]:
        """获取权重"""
        return self.method.get_weights(factor_cols, ic_results)