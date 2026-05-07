"""
适应度函数模块
以IC（Information Coefficient）为核心目标
"""

import numpy as np
import pandas as pd
from scipy.stats import spearmanr, pearsonr
from typing import Callable, Tuple, Optional, Dict, Any
import warnings

# gplearn fitness
try:
    from gplearn.fitness import make_fitness
    GPLEARN_AVAILABLE = True
except ImportError:
    GPLEARN_AVAILABLE = False
    warnings.warn("gplearn not installed. Run: pip install gplearn")


def ic_fitness(y: np.ndarray, y_pred: np.ndarray) -> float:
    """
    以IC作为适应度函数
    
    计算预测因子与目标收益的Spearman秩相关系数
    
    Args:
        y: 目标变量（未来收益）
        y_pred: 预测值（因子值）
        
    Returns:
        IC值 (-1 到 1)，越高越好
    """
    # 处理无效值
    valid_mask = ~(np.isnan(y_pred) | np.isnan(y) | np.isinf(y_pred) | np.isinf(y))
    
    if valid_mask.sum() < 5:
        return -np.inf
    
    y_valid = y[valid_mask]
    y_pred_valid = y_pred[valid_mask]
    
    # 检查方差
    if np.std(y_pred_valid) < 1e-10:
        return -np.inf
    
    # 计算Rank IC (Spearman相关系数)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        ic, _ = spearmanr(y_pred_valid, y_valid)
    
    if np.isnan(ic):
        return -np.inf
    
    return ic


def rank_ic_fitness(y: np.ndarray, y_pred: np.ndarray) -> float:
    """
    Rank IC适应度（别名）
    """
    return ic_fitness(y, y_pred)


def normalized_ic_fitness(y: np.ndarray, y_pred: np.ndarray) -> float:
    """
    归一化IC适应度
    
    将IC映射到正值区间，便于优化
    """
    ic = ic_fitness(y, y_pred)
    
    if np.isinf(ic):
        return 0.0
    
    # 将 [-1, 1] 映射到 [0, 1]
    return (ic + 1) / 2


def ic_ir_fitness(y: np.ndarray, y_pred: np.ndarray, w: Optional[np.ndarray] = None) -> float:
    """
    IC_IR适应度
    
    考虑IC的稳定性，IC_IR = IC_mean / IC_std
    这里简化处理，返回单次IC
    
    Args:
        y: 目标变量
        y_pred: 预测值
        w: 权重（可选）
        
    Returns:
        IC值
    """
    return ic_fitness(y, y_pred)


def weighted_ic_fitness(y: np.ndarray, y_pred: np.ndarray, sample_weight: Optional[np.ndarray] = None) -> float:
    """
    加权IC适应度
    
    Args:
        y: 目标变量
        y_pred: 预测值
        sample_weight: 样本权重
        
    Returns:
        加权IC值
    """
    valid_mask = ~(np.isnan(y_pred) | np.isnan(y) | np.isinf(y_pred) | np.isinf(y))
    
    if valid_mask.sum() < 5:
        return -np.inf
    
    y_valid = y[valid_mask]
    y_pred_valid = y_pred[valid_mask]
    
    if sample_weight is not None:
        weights = sample_weight[valid_mask]
        # 加权秩
        ranks = np.argsort(np.argsort(y_pred_valid))
        weighted_ranks = ranks * weights
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            ic, _ = spearmanr(weighted_ranks, y_valid)
    else:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            ic, _ = spearmanr(y_pred_valid, y_valid)
    
    return ic if not np.isnan(ic) else -np.inf


def ic_abs_fitness(y: np.ndarray, y_pred: np.ndarray) -> float:
    """
    绝对值IC适应度
    
    同时考虑正负IC，取绝对值
    """
    ic = ic_fitness(y, y_pred)
    return abs(ic) if not np.isinf(ic) else 0.0


def directional_ic_fitness(y: np.ndarray, y_pred: np.ndarray) -> float:
    """
    方向性IC适应度
    
    惩罚方向不一致的情况
    """
    ic = ic_fitness(y, y_pred)
    
    if np.isinf(ic):
        return -np.inf
    
    # 方向一致性奖励
    valid_mask = ~(np.isnan(y_pred) | np.isnan(y))
    if valid_mask.sum() < 5:
        return -np.inf
    
    y_valid = y[valid_mask]
    y_pred_valid = y_pred[valid_mask]
    
    # 检查方向一致性
    y_sign = np.sign(y_valid)
    pred_sign = np.sign(y_pred_valid)
    direction_match = np.mean(y_sign == pred_sign)
    
    # 综合IC和方向一致性
    return ic * 0.7 + (direction_match - 0.5) * 0.3


def monotonic_ic_fitness(y: np.ndarray, y_pred: np.ndarray, n_bins: int = 10) -> float:
    """
    单调性增强IC适应度
    
    检查因子值与收益的单调关系
    
    Args:
        y: 目标变量
        y_pred: 预测值
        n_bins: 分组数
        
    Returns:
        单调性增强的IC值
    """
    valid_mask = ~(np.isnan(y_pred) | np.isnan(y) | np.isinf(y_pred) | np.isinf(y))
    
    if valid_mask.sum() < n_bins * 5:
        return ic_fitness(y, y_pred)
    
    y_valid = y[valid_mask]
    y_pred_valid = y_pred[valid_mask]
    
    # 计算基础IC
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        ic, _ = spearmanr(y_pred_valid, y_valid)
    
    if np.isnan(ic):
        return -np.inf
    
    # 分组检查单调性
    try:
        bins = pd.qcut(y_pred_valid, n_bins, labels=False, duplicates='drop')
        bin_returns = pd.Series(y_valid).groupby(bins).mean()
        
        # 单调性得分：相邻组收益差的一致性
        diffs = bin_returns.diff().dropna()
        if len(diffs) > 0:
            # 计算单调性（同向差值的比例）
            monotonicity = max(
                (diffs > 0).mean(),  # 递增比例
                (diffs < 0).mean()   # 递减比例
            )
            # 综合得分
            return ic * 0.6 + (monotonicity - 0.5) * 0.4
    except:
        pass
    
    return ic


def make_fitness_metric(
    metric_name: str = 'ic',
    greater_is_better: bool = True,
    wrap_for_gplearn: bool = True
) -> Callable:
    """
    创建适应度度量函数
    
    Args:
        metric_name: 度量名称 ('ic', 'rank_ic', 'normalized_ic', 'ic_abs', 'directional', 'monotonic')
        greater_is_better: 是否越大越好
        wrap_for_gplearn: 是否包装为gplearn格式
        
    Returns:
        适应度函数
    """
    metrics = {
        'ic': ic_fitness,
        'rank_ic': rank_ic_fitness,
        'normalized_ic': normalized_ic_fitness,
        'ic_abs': ic_abs_fitness,
        'directional': directional_ic_fitness,
        'monotonic': monotonic_ic_fitness,
    }
    
    if metric_name not in metrics:
        raise ValueError(f"Unknown metric: {metric_name}. Available: {list(metrics.keys())}")
    
    base_func = metrics[metric_name]
    
    if not wrap_for_gplearn or not GPLEARN_AVAILABLE:
        return base_func
    
    # 包装为gplearn格式
    @make_fitness(function=base_func, greater_is_better=greater_is_better)
    def wrapped_fitness(y, y_pred, sample_weight=None):
        if sample_weight is not None:
            return weighted_ic_fitness(y, y_pred, sample_weight)
        return base_func(y, y_pred)
    
    return wrapped_fitness


class FitnessEvaluator:
    """适应度评估器"""
    
    def __init__(self, metric: str = 'ic'):
        """
        初始化评估器
        
        Args:
            metric: 评估指标名称
        """
        self.metric = metric
        self.fitness_func = make_fitness_metric(metric, wrap_for_gplearn=False)
    
    def evaluate(
        self,
        y_true: np.ndarray,
        y_pred: np.ndarray
    ) -> Dict[str, float]:
        """
        评估预测结果
        
        Args:
            y_true: 真实值
            y_pred: 预测值
            
        Returns:
            评估结果字典
        """
        valid_mask = ~(np.isnan(y_pred) | np.isnan(y_true) | np.isinf(y_pred) | np.isinf(y_true))
        y_valid = y_true[valid_mask]
        pred_valid = y_pred[valid_mask]
        
        n_valid = len(y_valid)
        
        if n_valid < 5:
            return {
                'ic': np.nan,
                'ic_pvalue': np.nan,
                'pearson_r': np.nan,
                'n_valid': n_valid,
                'fitness': -np.inf
            }
        
        # 计算各种指标
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            ic, ic_pvalue = spearmanr(pred_valid, y_valid)
            pearson_r, _ = pearsonr(pred_valid, y_valid)
        
        fitness = self.fitness_func(y_true, y_pred)
        
        return {
            'ic': ic,
            'ic_pvalue': ic_pvalue,
            'pearson_r': pearson_r,
            'n_valid': n_valid,
            'fitness': fitness
        }
    
    def batch_evaluate(
        self,
        y_true: np.ndarray,
        y_pred_matrix: np.ndarray,
        top_n: int = 10
    ) -> pd.DataFrame:
        """
        批量评估多个预测结果
        
        Args:
            y_true: 真实值
            y_pred_matrix: 预测矩阵 (n_samples, n_predictions)
            top_n: 返回前N个结果
            
        Returns:
            评估结果DataFrame
        """
        results = []
        
        for i in range(y_pred_matrix.shape[1]):
            y_pred = y_pred_matrix[:, i]
            eval_result = self.evaluate(y_true, y_pred)
            eval_result['index'] = i
            results.append(eval_result)
        
        df = pd.DataFrame(results)
        df = df.sort_values('ic', ascending=False, key=abs)
        
        return df.head(top_n).reset_index(drop=True)


# 为gplearn预定义的适应度函数
def _ic_fitness_wrapper(y, y_pred, w):
    """gplearn需要的3参数包装器"""
    return ic_fitness(y, y_pred)

def _ic_abs_fitness_wrapper(y, y_pred, w):
    """gplearn需要的3参数包装器"""
    return ic_abs_fitness(y, y_pred)

if GPLEARN_AVAILABLE:
    # 标准IC适应度
    ic_fitness_gplearn = make_fitness(
        function=_ic_fitness_wrapper,
        greater_is_better=True
    )
    
    # 绝对值IC适应度
    ic_abs_fitness_gplearn = make_fitness(
        function=_ic_abs_fitness_wrapper,
        greater_is_better=True
    )