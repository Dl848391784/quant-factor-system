"""
交叉验证防过拟合模块
"""

import numpy as np
import pandas as pd
from typing import Dict, List, Optional, Tuple, Any, Callable
from dataclasses import dataclass
from sklearn.model_selection import TimeSeriesSplit, KFold
from scipy.stats import spearmanr
import warnings
import logging

logger = logging.getLogger(__name__)


@dataclass
class CrossValidationConfig:
    """交叉验证配置"""
    n_splits: int = 5
    min_train_size: int = 100
    min_test_size: int = 20
    gap: int = 0  # 训练和测试之间的间隔（防止数据泄露）
    random_state: Optional[int] = None
    use_time_series_split: bool = True  # 是否使用时序分割


class CrossValidationValidator:
    """
    交叉验证防过拟合
    
    用于评估遗传规划生成的因子是否过拟合
    """
    
    def __init__(self, config: Optional[CrossValidationConfig] = None):
        """
        初始化交叉验证器
        
        Args:
            config: 配置对象
        """
        self.config = config or CrossValidationConfig()
        self.cv_results_: Dict[str, Any] = {}
        
    def create_splits(
        self,
        n_samples: int,
        dates: Optional[pd.DatetimeIndex] = None
    ) -> List[Tuple[np.ndarray, np.ndarray]]:
        """
        创建交叉验证分割
        
        Args:
            n_samples: 总样本数
            dates: 日期索引（用于时序分割）
            
        Returns:
            (train_indices, test_indices) 列表
        """
        if self.config.use_time_series_split and dates is not None:
            # 使用时序分割
            cv = TimeSeriesSplit(
                n_splits=self.config.n_splits,
                max_train_size=self.config.min_train_size,
                test_size=self.config.min_test_size
            )
            splits = list(cv.split(np.arange(n_samples)))
        else:
            # 使用普通KFold
            cv = KFold(
                n_splits=self.config.n_splits,
                shuffle=self.config.random_state is not None,
                random_state=self.config.random_state
            )
            splits = list(cv.split(np.arange(n_samples)))
        
        return splits
    
    def validate_factor(
        self,
        factor_values: np.ndarray,
        target_returns: np.ndarray,
        dates: Optional[pd.DatetimeIndex] = None
    ) -> Dict[str, Any]:
        """
        验证单个因子
        
        Args:
            factor_values: 因子值序列
            target_returns: 目标收益序列
            dates: 日期索引
            
        Returns:
            验证结果字典
        """
        n_samples = len(factor_values)
        splits = self.create_splits(n_samples, dates)
        
        cv_ics = []
        cv_statistics = []
        
        for i, (train_idx, test_idx) in enumerate(splits):
            train_factor = factor_values[train_idx]
            train_returns = target_returns[train_idx]
            test_factor = factor_values[test_idx]
            test_returns = target_returns[test_idx]
            
            # 计算训练集IC
            train_ic = self._calc_ic(train_factor, train_returns)
            
            # 计算测试集IC
            test_ic = self._calc_ic(test_factor, test_returns)
            
            cv_ics.append({
                'fold': i + 1,
                'train_size': len(train_idx),
                'test_size': len(test_idx),
                'train_ic': train_ic,
                'test_ic': test_ic,
                'ic_decay': train_ic - test_ic  # IC衰减程度
            })
        
        # 计算综合指标
        train_ics = [x['train_ic'] for x in cv_ics]
        test_ics = [x['test_ic'] for x in cv_ics]
        
        train_ic_mean = np.nanmean(train_ics)
        test_ic_mean = np.nanmean(test_ics)
        ic_decay_mean = train_ic_mean - test_ic_mean
        ic_decay_std = np.nanstd([x['ic_decay'] for x in cv_ics])
        
        # 过拟合判断
        is_overfitting = self._detect_overfitting(train_ics, test_ics)
        
        result = {
            'n_splits': self.config.n_splits,
            'cv_folds': cv_ics,
            'train_ic_mean': train_ic_mean,
            'test_ic_mean': test_ic_mean,
            'ic_decay_mean': ic_decay_mean,
            'ic_decay_std': ic_decay_std,
            'ic_stability': test_ic_mean / (train_ic_mean + 1e-10),  # IC稳定性
            'is_overfitting': is_overfitting,
            'overfitting_score': self._calc_overfitting_score(train_ics, test_ics)
        }
        
        return result
    
    def _calc_ic(self, factor: np.ndarray, returns: np.ndarray) -> float:
        """计算IC"""
        valid_mask = ~(np.isnan(factor) | np.isnan(returns) | np.isinf(factor) | np.isinf(returns))
        
        if valid_mask.sum() < 10:
            return np.nan
        
        factor_valid = factor[valid_mask]
        returns_valid = returns[valid_mask]
        
        if np.std(factor_valid) < 1e-10 or np.std(returns_valid) < 1e-10:
            return np.nan
        
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            ic, _ = spearmanr(factor_valid, returns_valid)
        
        return ic
    
    def _detect_overfitting(
        self,
        train_ics: List[float],
        test_ics: List[float]
    ) -> bool:
        """
        判断是否过拟合
        
        过拟合的标志：
        1. 训练集IC明显高于测试集IC
        2. 测试集IC不稳定（方差大）
        3. 测试集IC有负值出现
        """
        train_mean = np.nanmean(train_ics)
        test_mean = np.nanmean(test_ics)
        test_std = np.nanstd(test_ics)
        
        # 判断条件
        ic_decay_threshold = 0.02  # IC衰减阈值
        ic_stability_threshold = 0.5  # IC稳定性阈值
        
        conditions = [
            # IC衰减过大
            train_mean - test_mean > ic_decay_threshold,
            # 测试集IC不稳定
            test_std > abs(test_mean) * 0.5,
            # 测试集IC均值过低
            abs(test_mean) < abs(train_mean) * ic_stability_threshold,
            # 测试集出现负IC
            any(ic < -0.01 for ic in test_ics if not np.isnan(ic))
        ]
        
        return any(conditions)
    
    def _calc_overfitting_score(
        self,
        train_ics: List[float],
        test_ics: List[float]
    ) -> float:
        """
        计算过拟合分数（0-1，越高表示过拟合越严重）
        """
        train_mean = abs(np.nanmean(train_ics))
        test_mean = abs(np.nanmean(test_ics))
        
        if train_mean < 1e-10:
            return 0.0
        
        # 基于IC衰减计算分数
        decay_ratio = (train_mean - test_mean) / train_mean
        
        # 归一化到[0, 1]
        overfit_score = max(0, min(1, decay_ratio * 2))
        
        return overfit_score
    
    def validate_batch(
        self,
        factor_matrix: np.ndarray,
        target_returns: np.ndarray,
        dates: Optional[pd.DatetimeIndex] = None,
        top_n: int = 10
    ) -> pd.DataFrame:
        """
        批量验证多个因子
        
        Args:
            factor_matrix: 因子矩阵 (n_samples, n_factors)
            target_returns: 目标收益
            dates: 日期索引
            top_n: 返回前N个验证结果
            
        Returns:
            验证结果DataFrame
        """
        results = []
        
        for i in range(factor_matrix.shape[1]):
            factor = factor_matrix[:, i]
            cv_result = self.validate_factor(factor, target_returns, dates)
            
            results.append({
                'factor_index': i,
                'train_ic_mean': cv_result['train_ic_mean'],
                'test_ic_mean': cv_result['test_ic_mean'],
                'ic_decay_mean': cv_result['ic_decay_mean'],
                'ic_stability': cv_result['ic_stability'],
                'is_overfitting': cv_result['is_overfitting'],
                'overfitting_score': cv_result['overfitting_score']
            })
        
        df = pd.DataFrame(results)
        
        # 排序：优先非过拟合且测试IC高
        df = df.sort_values(
            by=['is_overfitting', 'test_ic_mean'],
            ascending=[True, False],
            key=lambda x: x if x.name == 'test_ic_mean' else x
        )
        
        return df.head(top_n)
    
    def filter_overfitting(
        self,
        factor_matrix: np.ndarray,
        target_returns: np.ndarray,
        dates: Optional[pd.DatetimeIndex] = None,
        max_decay_threshold: float = 0.03,
        min_test_ic: float = 0.02
    ) -> Tuple[np.ndarray, pd.DataFrame]:
        """
        过滤过拟合因子
        
        Args:
            factor_matrix: 因子矩阵
            target_returns: 目标收益
            dates: 日期索引
            max_decay_threshold: 最大允许IC衰减
            min_test_ic: 最小测试集IC
            
        Returns:
            (过滤后的因子矩阵, 验证结果DataFrame)
        """
        validation_df = self.validate_batch(
            factor_matrix, target_returns, dates,
            top_n=factor_matrix.shape[1]
        )
        
        # 筛选条件
        valid_mask = (
            ~validation_df['is_overfitting'] &
            (validation_df['ic_decay_mean'] <= max_decay_threshold) &
            (abs(validation_df['test_ic_mean']) >= min_test_ic)
        )
        
        valid_indices = validation_df[valid_mask]['factor_index'].values
        
        if len(valid_indices) == 0:
            logger.warning("没有因子通过交叉验证筛选")
            return np.array([]), validation_df
        
        filtered_factors = factor_matrix[:, valid_indices]
        filtered_results = validation_df[valid_mask]
        
        logger.info(f"交叉验证筛选：{len(valid_indices)}/{factor_matrix.shape[1]} 因子通过")
        
        return filtered_factors, filtered_results
    
    def get_stability_score(
        self,
        factor_values: np.ndarray,
        target_returns: np.ndarray
    ) -> float:
        """
        计算因子稳定性分数
        
        Returns:
            稳定性分数 (0-1, 越高越稳定)
        """
        cv_result = self.validate_factor(factor_values, target_returns)
        
        # 稳定性分数 = 测试IC / 训练IC
        stability = cv_result['ic_stability']
        
        # 考虑IC衰减
        decay_penalty = cv_result['ic_decay_mean'] * 10
        
        # 最终分数
        score = max(0, stability - decay_penalty)
        
        return min(1, max(0, score))


class OverfittingDetector:
    """
    过拟合检测器
    
    专门用于检测遗传规划结果是否过拟合
    """
    
    def __init__(
        self,
        cv_n_splits: int = 5,
        decay_threshold: float = 0.05,
        stability_threshold: float = 0.3
    ):
        """
        初始化检测器
        
        Args:
            cv_n_splits: 交叉验证折数
            decay_threshold: IC衰减阈值
            stability_threshold: 稳定性阈值
        """
        self.cv_config = CrossValidationConfig(n_splits=cv_n_splits)
        self.decay_threshold = decay_threshold
        self.stability_threshold = stability_threshold
        
    def detect(
        self,
        factor_values: np.ndarray,
        target_returns: np.ndarray,
        expression_complexity: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        检测过拟合
        
        Args:
            factor_values: 因子值
            target_returns: 目标收益
            expression_complexity: 表达式复杂度
            
        Returns:
            检测结果
        """
        validator = CrossValidationValidator(self.cv_config)
        cv_result = validator.validate_factor(factor_values, target_returns)
        
        # 综合判断
        is_overfit = cv_result['is_overfitting']
        severity = cv_result['overfitting_score']
        
        # 复杂度惩罚
        if expression_complexity is not None:
            complexity_penalty = expression_complexity / 50.0  # 简化的复杂度惩罚
            severity += complexity_penalty * 0.2
        
        result = {
            'is_overfitting': is_overfit,
            'severity': severity,
            'train_ic_mean': cv_result['train_ic_mean'],
            'test_ic_mean': cv_result['test_ic_mean'],
            'ic_decay': cv_result['ic_decay_mean'],
            'recommendation': self._get_recommendation(severity)
        }
        
        return result
    
    def _get_recommendation(self, severity: float) -> str:
        """获取建议"""
        if severity < 0.2:
            return "因子稳定，可用于回测"
        elif severity < 0.4:
            return "因子略有衰减，建议监控"
        elif severity < 0.6:
            return "因子可能过拟合，谨慎使用"
        else:
            return "因子严重过拟合，建议排除"


# ============ 辅助函数 ============

def quick_cv_check(
    factor_values: np.ndarray,
    target_returns: np.ndarray,
    n_splits: int = 5
) -> Dict[str, float]:
    """
    快速交叉验证检查
    
    Args:
        factor_values: 因子值
        target_returns: 目标收益
        n_splits: 折数
        
    Returns:
        简化的检查结果
    """
    config = CrossValidationConfig(n_splits=n_splits)
    validator = CrossValidationValidator(config)
    
    result = validator.validate_factor(factor_values, target_returns)
    
    return {
        'train_ic': result['train_ic_mean'],
        'test_ic': result['test_ic_mean'],
        'decay': result['ic_decay_mean'],
        'is_overfit': result['is_overfitting']
    }