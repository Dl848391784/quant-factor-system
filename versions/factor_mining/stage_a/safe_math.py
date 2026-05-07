"""
安全数学运算模块

提供边界保护的数学运算，防止除零、NaN、Inf等问题
"""

import numpy as np
import pandas as pd
from typing import Union, Optional
import warnings

warnings.filterwarnings('ignore')


class SafeMath:
    """
    安全数学运算类
    
    提供带有边界保护的数学运算，确保结果有效
    """
    
    # 默认配置
    EPSILON = 1e-10  # 防止除零的小量
    FILL_VALUE = 0.0  # 无效值填充
    
    @staticmethod
    def safe_divide(
        numerator: Union[np.ndarray, pd.Series, float],
        denominator: Union[np.ndarray, pd.Series, float],
        fill_value: float = 0.0,
        epsilon: float = 1e-10
    ) -> Union[np.ndarray, pd.Series]:
        """
        安全除法，防止除零
        
        Args:
            numerator: 分子
            denominator: 分母
            fill_value: 除零时的填充值
            epsilon: 防止除零的小量
            
        Returns:
            安全的除法结果
        """
        if isinstance(denominator, pd.Series):
            safe_denom = denominator.copy()
            safe_denom = safe_denom.replace(0, np.nan)
            safe_denom = safe_denom.abs().fillna(epsilon) * np.sign(safe_denom.fillna(1))
            result = numerator / safe_denom
        elif isinstance(denominator, np.ndarray):
            safe_denom = np.where(denominator == 0, epsilon, denominator)
            result = np.divide(numerator, safe_denom)
        else:
            if denominator == 0:
                return fill_value
            result = numerator / denominator
            
        # 处理无效值
        if isinstance(result, pd.Series):
            result = result.replace([np.inf, -np.inf], fill_value)
            result = result.fillna(fill_value)
        else:
            result = np.where(np.isinf(result) | np.isnan(result), fill_value, result)
            
        return result
    
    @staticmethod
    def safe_log(
        x: Union[np.ndarray, pd.Series, float],
        fill_value: float = 0.0,
        epsilon: float = 1e-10
    ) -> Union[np.ndarray, pd.Series]:
        """
        安全对数运算，处理负数和零
        
        Args:
            x: 输入值
            fill_value: 无效值填充
            epsilon: 防止log(0)的小量
            
        Returns:
            安全的对数结果
        """
        if isinstance(x, pd.Series):
            safe_x = x.copy()
            safe_x = safe_x.abs() + epsilon
            result = np.log(safe_x)
            result = result.replace([np.inf, -np.inf], fill_value)
            result = result.fillna(fill_value)
        elif isinstance(x, np.ndarray):
            safe_x = np.abs(x) + epsilon
            result = np.log(safe_x)
            result = np.where(np.isinf(result) | np.isnan(result), fill_value, result)
        else:
            if x <= 0:
                return fill_value
            result = np.log(abs(x) + epsilon)
            
        return result
    
    @staticmethod
    def safe_sqrt(
        x: Union[np.ndarray, pd.Series, float],
        fill_value: float = 0.0
    ) -> Union[np.ndarray, pd.Series]:
        """
        安全平方根，处理负数
        
        Args:
            x: 输入值
            fill_value: 无效值填充
            
        Returns:
            安全的平方根结果
        """
        if isinstance(x, pd.Series):
            safe_x = x.copy()
            safe_x = safe_x.clip(lower=0)  # 负数转为0
            result = np.sqrt(safe_x)
            result = result.replace([np.inf, -np.inf], fill_value)
            result = result.fillna(fill_value)
        elif isinstance(x, np.ndarray):
            safe_x = np.clip(x, 0, None)
            result = np.sqrt(safe_x)
            result = np.where(np.isinf(result) | np.isnan(result), fill_value, result)
        else:
            if x < 0:
                return fill_value
            result = np.sqrt(x)
            
        return result
    
    @staticmethod
    def safe_power(
        base: Union[np.ndarray, pd.Series, float],
        exponent: Union[np.ndarray, pd.Series, float],
        fill_value: float = 0.0
    ) -> Union[np.ndarray, pd.Series]:
        """
        安全幂运算，防止数值溢出
        
        Args:
            base: 底数
            exponent: 指数
            fill_value: 无效值填充
            
        Returns:
            安全的幂运算结果
        """
        if isinstance(base, pd.Series):
            # 限制底数范围，防止溢出
            safe_base = base.clip(lower=-1e10, upper=1e10)
            result = np.power(safe_base.abs(), exponent) * np.sign(safe_base)
            result = result.replace([np.inf, -np.inf], fill_value)
            result = result.fillna(fill_value)
        elif isinstance(base, np.ndarray):
            safe_base = np.clip(base, -1e10, 1e10)
            result = np.power(np.abs(safe_base), exponent) * np.sign(safe_base)
            result = np.where(np.isinf(result) | np.isnan(result), fill_value, result)
        else:
            try:
                result = np.power(abs(base), exponent) * np.sign(base)
                if np.isinf(result) or np.isnan(result):
                    result = fill_value
            except:
                result = fill_value
                
        return result
    
    @staticmethod
    def safe_rank(
        x: Union[np.ndarray, pd.Series],
        method: str = 'average',
        normalize: bool = True
    ) -> Union[np.ndarray, pd.Series]:
        """
        安全排名运算
        
        Args:
            x: 输入值
            method: 排名方法 ('average', 'min', 'max', 'dense')
            normalize: 是否归一化到[0, 1]
            
        Returns:
            排名结果
        """
        if isinstance(x, pd.Series):
            # 记录原始dtype，统一转为float64进行计算
            original_dtype = x.dtype
            valid_mask = ~x.isna()
            
            # 转换为float64进行计算，避免LossySetitemError
            result = x.astype(np.float64)
            
            if valid_mask.sum() > 0:
                ranks = x[valid_mask].rank(method=method)
                if normalize:
                    ranks = (ranks - 1) / (len(ranks) - 1) if len(ranks) > 1 else 0.5
                result[valid_mask] = ranks
                result[~valid_mask] = 0.5  # NaN填充为中间值
            else:
                result[:] = 0.5
            
            # 如果原始是float32，转回float32
            if original_dtype == np.float32:
                result = result.astype(np.float32)
            
            return result
        else:
            # numpy数组
            if len(x) == 0:
                return np.array([])
            
            # 记录原始dtype
            original_dtype = x.dtype if hasattr(x, 'dtype') else None
            valid_mask = ~np.isnan(x)
            
            # 使用float64进行计算
            result = np.full_like(x, 0.5, dtype=np.float64)
            
            if valid_mask.sum() > 0:
                valid_x = x[valid_mask]
                ranks = pd.Series(valid_x).rank(method=method).values
                if normalize:
                    ranks = (ranks - 1) / (len(ranks) - 1) if len(ranks) > 1 else 0.5
                result[valid_mask] = ranks
            
            # 如果原始是float32，转回float32
            if original_dtype == np.float32:
                result = result.astype(np.float32)
                
            return result
    
    @staticmethod
    def safe_zscore(
        x: Union[np.ndarray, pd.Series],
        fill_value: float = 0.0
    ) -> Union[np.ndarray, pd.Series]:
        """
        安全Z-Score标准化
        
        Args:
            x: 输入值
            fill_value: 标准差为0时的填充值
            
        Returns:
            Z-Score结果
        """
        if isinstance(x, pd.Series):
            # 记录原始dtype
            original_dtype = x.dtype
            
            # 转换为float64进行计算
            x_f64 = x.astype(np.float64)
            mean = x_f64.mean()
            std = x_f64.std()
            
            if pd.isna(std) or std < 1e-10:
                result = pd.Series([fill_value] * len(x), index=x.index, dtype=np.float64)
            else:
                result = (x_f64 - mean) / std
                result = result.replace([np.inf, -np.inf], fill_value)
                result = result.fillna(fill_value)
            
            # 如果原始是float32，转回float32
            if original_dtype == np.float32:
                result = result.astype(np.float32)
            
            return result
        else:
            # numpy数组
            if len(x) == 0:
                return np.array([])
            
            # 记录原始dtype
            original_dtype = x.dtype if hasattr(x, 'dtype') else None
            
            # 使用float64进行计算
            x_f64 = x.astype(np.float64)
            mean = np.nanmean(x_f64)
            std = np.nanstd(x_f64)
            
            if np.isnan(std) or std < 1e-10:
                result = np.full_like(x_f64, fill_value, dtype=np.float64)
            else:
                result = (x_f64 - mean) / std
                result = np.where(np.isinf(result) | np.isnan(result), fill_value, result)
            
            # 如果原始是float32，转回float32
            if original_dtype == np.float32:
                result = result.astype(np.float32)
            
            return result
    
    @staticmethod
    def safe_delta(
        x: Union[np.ndarray, pd.Series],
        period: int = 1,
        fill_value: float = 0.0
    ) -> Union[np.ndarray, pd.Series]:
        """
        安全差分运算
        
        Args:
            x: 输入值
            period: 差分周期
            fill_value: 填充值
            
        Returns:
            差分结果
        """
        if isinstance(x, pd.Series):
            result = x.diff(period)
            result = result.fillna(fill_value)
            result = result.replace([np.inf, -np.inf], fill_value)
            return result
        else:
            result = np.full_like(x, fill_value, dtype=float)
            if len(x) > period:
                result[period:] = x[period:] - x[:-period]
            return result
    
    @staticmethod
    def safe_ratio(
        numerator: Union[np.ndarray, pd.Series, float],
        denominator: Union[np.ndarray, pd.Series, float],
        fill_value: float = 0.0
    ) -> Union[np.ndarray, pd.Series]:
        """
        安全比率计算（除法的别名）
        
        Args:
            numerator: 分子
            denominator: 分母
            fill_value: 填充值
            
        Returns:
            比率结果
        """
        return SafeMath.safe_divide(numerator, denominator, fill_value)
    
    @staticmethod
    def clean_series(
        x: Union[np.ndarray, pd.Series],
        fill_value: float = 0.0,
        clip_value: Optional[float] = None
    ) -> Union[np.ndarray, pd.Series]:
        """
        清理序列中的无效值
        
        Args:
            x: 输入值
            fill_value: NaN填充值
            clip_value: 裁剪边界值（对称）
            
        Returns:
            清理后的序列
        """
        if isinstance(x, pd.Series):
            result = x.copy()
            result = result.replace([np.inf, -np.inf], fill_value)
            result = result.fillna(fill_value)
            
            if clip_value is not None:
                result = result.clip(lower=-clip_value, upper=clip_value)
                
            return result
        else:
            result = np.where(np.isinf(x) | np.isnan(x), fill_value, x)
            
            if clip_value is not None:
                result = np.clip(result, -clip_value, clip_value)
                
            return result
    
    @staticmethod
    def is_valid(
        x: Union[np.ndarray, pd.Series, float]
    ) -> Union[np.ndarray, pd.Series, bool]:
        """
        检查值是否有效（非NaN、非Inf）
        
        Args:
            x: 输入值
            
        Returns:
            有效性掩码或布尔值
        """
        if isinstance(x, pd.Series):
            return ~(x.isna() | np.isinf(x))
        elif isinstance(x, np.ndarray):
            return ~(np.isnan(x) | np.isinf(x))
        else:
            return not (np.isnan(x) or np.isinf(x))


# 便捷函数
def safe_div(a, b, fill=0.0):
    """安全除法快捷函数"""
    return SafeMath.safe_divide(a, b, fill)

def safe_log(x, fill=0.0):
    """安全对数快捷函数"""
    return SafeMath.safe_log(x, fill)

def safe_sqrt(x, fill=0.0):
    """安全平方根快捷函数"""
    return SafeMath.safe_sqrt(x, fill)

def safe_rank(x, normalize=True):
    """安全排名快捷函数"""
    return SafeMath.safe_rank(x, normalize=normalize)

def safe_zscore(x, fill=0.0):
    """安全Z-Score快捷函数"""
    return SafeMath.safe_zscore(x, fill)