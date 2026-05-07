"""
因子去重模块

基于相关性进行因子去重，移除高度相似的因子
"""

import numpy as np
import pandas as pd
from scipy import stats
from typing import Dict, List, Tuple, Optional, Set
import warnings

warnings.filterwarnings('ignore')


class FactorDeduplicator:
    """
    因子去重器
    
    基于相关性阈值移除高度相似的因子
    默认阈值：相关性 > 0.8 视为重复
    """
    
    # 默认配置
    DEFAULT_CORRELATION_THRESHOLD = 0.8
    DEFAULT_KEEP_STRATEGY = 'first'  # 保留策略: first, highest_ic, shortest
    
    def __init__(
        self,
        correlation_threshold: float = 0.8,
        keep_strategy: str = 'first',
        method: str = 'spearman'
    ):
        """
        初始化去重器
        
        Args:
            correlation_threshold: 相关性阈值
            keep_strategy: 保留策略
                - 'first': 保留先遇到的
                - 'highest_ic': 保留IC最高的
                - 'shortest': 保留表达式最短的
            method: 相关性计算方法 ('spearman', 'pearson')
        """
        self.threshold = correlation_threshold
        self.keep_strategy = keep_strategy
        self.method = method
    
    def calculate_correlation(
        self,
        factor1: pd.Series,
        factor2: pd.Series
    ) -> float:
        """
        计算两个因子之间的相关性
        
        Args:
            factor1: 第一个因子
            factor2: 第二个因子
            
        Returns:
            相关系数（绝对值）
        """
        # 对齐索引
        aligned = pd.concat([factor1, factor2], axis=1, join='inner')
        aligned = aligned.dropna()
        
        if len(aligned) < 30:  # 样本太少
            return np.nan
        
        if self.method == 'spearman':
            corr, _ = stats.spearmanr(aligned.iloc[:, 0], aligned.iloc[:, 1])
        else:
            corr, _ = stats.pearsonr(aligned.iloc[:, 0], aligned.iloc[:, 1])
        
        # 返回绝对值（正负相关性都视为相似）
        return abs(corr)
    
    def calculate_correlation_matrix(
        self,
        factors_data: Dict[str, pd.Series],
        verbose: bool = False
    ) -> pd.DataFrame:
        """
        计算因子相关性矩阵
        
        Args:
            factors_data: 因子数据字典
            verbose: 是否打印进度
            
        Returns:
            相关性矩阵DataFrame
        """
        factor_names = list(factors_data.keys())
        n = len(factor_names)
        
        if n == 0:
            return pd.DataFrame()
        
        # 初始化矩阵
        corr_matrix = pd.DataFrame(
            np.eye(n),  # 对角线为1
            index=factor_names,
            columns=factor_names
        )
        
        # 计算两两相关性
        for i in range(n):
            for j in range(i + 1, n):
                f1_name = factor_names[i]
                f2_name = factor_names[j]
                
                try:
                    corr = self.calculate_correlation(
                        factors_data[f1_name],
                        factors_data[f2_name]
                    )
                    corr_matrix.loc[f1_name, f2_name] = corr
                    corr_matrix.loc[f2_name, f1_name] = corr
                except Exception as e:
                    corr_matrix.loc[f1_name, f2_name] = np.nan
                    corr_matrix.loc[f2_name, f1_name] = np.nan
                
                if verbose and (i * n + j) % 100 == 0:
                    print(f"计算进度: {i * n + j}/{n * n // 2}")
        
        return corr_matrix
    
    def find_duplicate_groups(
        self,
        corr_matrix: pd.DataFrame
    ) -> List[Set[str]]:
        """
        找出重复因子组
        
        使用聚类方法找出相关性超过阈值的因子组
        
        Args:
            corr_matrix: 相关性矩阵
            
        Returns:
            重复因子组列表
        """
        if corr_matrix.empty:
            return []
        
        factor_names = list(corr_matrix.index)
        visited = set()
        groups = []
        
        for factor in factor_names:
            if factor in visited:
                continue
            
            # 找出与当前因子高度相关的所有因子
            group = {factor}
            
            # 遍历所有因子
            for other in factor_names:
                if other in visited or other == factor:
                    continue
                
                corr = corr_matrix.loc[factor, other]
                if not np.isnan(corr) and corr > self.threshold:
                    group.add(other)
            
            if len(group) > 1:
                groups.append(group)
                visited.update(group)
            else:
                visited.add(factor)
        
        return groups
    
    def select_representative(
        self,
        group: Set[str],
        factors_data: Dict[str, pd.Series],
        ic_values: Optional[Dict[str, float]] = None,
        expressions: Optional[Dict[str, str]] = None
    ) -> str:
        """
        从重复组中选择代表性因子
        
        Args:
            group: 重复因子组
            factors_data: 因子数据
            ic_values: IC值字典（可选）
            expressions: 表达式字典（可选）
            
        Returns:
            代表性因子名称
        """
        if len(group) == 1:
            return list(group)[0]
        
        if self.keep_strategy == 'first':
            return sorted(group)[0]  # 按名称排序取第一个
        
        elif self.keep_strategy == 'highest_ic':
            if ic_values:
                # 选择IC最高的
                best = max(group, key=lambda x: ic_values.get(x, 0))
                return best
            else:
                return sorted(group)[0]
        
        elif self.keep_strategy == 'shortest':
            if expressions:
                # 选择表达式最短的
                shortest = min(group, key=lambda x: len(expressions.get(x, '')))
                return shortest
            else:
                return sorted(group)[0]
        
        return sorted(group)[0]
    
    def deduplicate(
        self,
        factors_data: Dict[str, pd.Series],
        ic_values: Optional[Dict[str, float]] = None,
        expressions: Optional[Dict[str, str]] = None,
        verbose: bool = False
    ) -> Tuple[Dict[str, pd.Series], List[str], Dict]:
        """
        执行去重
        
        Args:
            factors_data: 因子数据字典
            ic_values: IC值字典
            expressions: 表达式字典
            verbose: 是否打印详细信息
            
        Returns:
            (去重后的因子数据, 移除的因子列表, 统计信息)
        """
        if not factors_data:
            return {}, [], {}
        
        # 计算相关性矩阵
        if verbose:
            print("计算相关性矩阵...")
        corr_matrix = self.calculate_correlation_matrix(factors_data, verbose)
        
        # 找出重复组
        if verbose:
            print("查找重复因子组...")
        duplicate_groups = self.find_duplicate_groups(corr_matrix)
        
        # 选择保留因子
        kept_factors = set(factors_data.keys())
        removed_factors = []
        
        for group in duplicate_groups:
            # 选择代表性因子
            representative = self.select_representative(
                group, factors_data, ic_values, expressions
            )
            
            # 移除组内其他因子
            for factor in group:
                if factor != representative:
                    kept_factors.discard(factor)
                    removed_factors.append(factor)
                    
                    if verbose:
                        corr_with_rep = corr_matrix.loc[representative, factor]
                        print(f"移除 {factor} (与 {representative} 相关性: {corr_with_rep:.3f})")
        
        # 构建去重后的数据
        deduplicated_data = {
            name: factors_data[name]
            for name in kept_factors
        }
        
        # 统计信息
        stats = {
            'original_count': len(factors_data),
            'duplicate_groups': len(duplicate_groups),
            'removed_count': len(removed_factors),
            'kept_count': len(kept_factors),
            'correlation_threshold': self.threshold,
            'keep_strategy': self.keep_strategy
        }
        
        if verbose:
            print(f"\n去重完成: {stats['original_count']} -> {stats['kept_count']}")
        
        return deduplicated_data, removed_factors, stats
    
    def deduplicate_by_correlation_matrix(
        self,
        corr_matrix: pd.DataFrame,
        ic_values: Optional[Dict[str, float]] = None,
        expressions: Optional[Dict[str, str]] = None,
        verbose: bool = False
    ) -> Tuple[List[str], List[str], Dict]:
        """
        基于已有的相关性矩阵执行去重
        
        Args:
            corr_matrix: 相关性矩阵
            ic_values: IC值字典
            expressions: 表达式字典
            verbose: 是否打印详细信息
            
        Returns:
            (保留因子列表, 移除因子列表, 统计信息)
        """
        if corr_matrix.empty:
            return [], [], {}
        
        # 找出重复组
        duplicate_groups = self.find_duplicate_groups(corr_matrix)
        
        # 选择保留因子
        kept_factors = set(corr_matrix.index)
        removed_factors = []
        
        for group in duplicate_groups:
            representative = self.select_representative(
                group, {}, ic_values, expressions
            )
            
            for factor in group:
                if factor != representative:
                    kept_factors.discard(factor)
                    removed_factors.append(factor)
        
        stats = {
            'original_count': len(corr_matrix.index),
            'duplicate_groups': len(duplicate_groups),
            'removed_count': len(removed_factors),
            'kept_count': len(kept_factors)
        }
        
        return list(kept_factors), removed_factors, stats
    
    def get_correlation_pairs(
        self,
        corr_matrix: pd.DataFrame,
        threshold: Optional[float] = None
    ) -> List[Tuple[str, str, float]]:
        """
        获取高相关性因子对
        
        Args:
            corr_matrix: 相关性矩阵
            threshold: 阈值（可选，使用默认值）
            
        Returns:
            高相关性因子对列表 [(factor1, factor2, correlation), ...]
        """
        threshold = threshold or self.threshold
        
        high_corr_pairs = []
        factor_names = list(corr_matrix.index)
        
        for i in range(len(factor_names)):
            for j in range(i + 1, len(factor_names)):
                f1 = factor_names[i]
                f2 = factor_names[j]
                corr = corr_matrix.loc[f1, f2]
                
                if not np.isnan(corr) and corr > threshold:
                    high_corr_pairs.append((f1, f2, corr))
        
        # 按相关性降序排序
        high_corr_pairs.sort(key=lambda x: x[2], reverse=True)
        
        return high_corr_pairs
    
    def generate_report(
        self,
        corr_matrix: pd.DataFrame,
        removed_factors: List[str]
    ) -> Dict:
        """
        生成去重报告
        
        Args:
            corr_matrix: 相关性矩阵
            removed_factors: 移除的因子列表
            
        Returns:
            报告字典
        """
        duplicate_groups = self.find_duplicate_groups(corr_matrix)
        high_corr_pairs = self.get_correlation_pairs(corr_matrix)
        
        report = {
            'summary': {
                'total_factors': len(corr_matrix.index),
                'duplicate_groups_found': len(duplicate_groups),
                'removed_factors': len(removed_factors),
                'high_correlation_pairs': len(high_corr_pairs),
                'threshold': self.threshold
            },
            'duplicate_groups': [
                {
                    'size': len(group),
                    'factors': sorted(list(group))
                }
                for group in duplicate_groups
            ],
            'high_correlation_pairs': [
                {
                    'factor1': pair[0],
                    'factor2': pair[1],
                    'correlation': round(pair[2], 4)
                }
                for pair in high_corr_pairs[:20]  # 只显示前20对
            ],
            'removed_factors': removed_factors
        }
        
        return report


def quick_deduplicate(
    factors_data: Dict[str, pd.Series],
    threshold: float = 0.8,
    keep_strategy: str = 'first'
) -> Tuple[Dict[str, pd.Series], List[str]]:
    """
    快速去重
    
    Args:
        factors_data: 因子数据字典
        threshold: 相关性阈值
        keep_strategy: 保留策略
        
    Returns:
        (去重后数据, 移除因子列表)
    """
    dedup = FactorDeduplicator(
        correlation_threshold=threshold,
        keep_strategy=keep_strategy
    )
    
    result, removed, stats = dedup.deduplicate(factors_data)
    return result, removed