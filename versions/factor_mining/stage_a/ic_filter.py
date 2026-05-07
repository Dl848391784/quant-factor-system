"""
IC筛选器模块

对因子进行IC筛选，保留有效因子
"""

import numpy as np
import pandas as pd
from scipy import stats
from typing import Dict, List, Optional, Tuple
import warnings

warnings.filterwarnings('ignore')


class ICFilter:
    """
    IC筛选器
    
    筛选条件：
    - IC均值 > 阈值 (默认0.03)
    - IC_IR > 阈值 (默认0.5)
    - IC显著性 t统计量 > 阈值 (默认2.0)
    - 记录数 >= 最小值 (默认100)
    """
    
    # 默认阈值配置
    DEFAULT_THRESHOLDS = {
        'ic_mean': 0.03,
        'ic_ir': 0.5,
        'ic_tstat': 2.0,
        'min_records': 100,
        'max_ic_std': 0.5,  # IC标准差上限
        'min_ic_positive_ratio': 0.5  # IC正值比例下限
    }
    
    def __init__(
        self,
        ic_threshold: float = 0.03,
        ir_threshold: float = 0.5,
        tstat_threshold: float = 2.0,
        min_records: int = 100,
        max_ic_std: float = 0.5,
        min_ic_positive_ratio: float = 0.5
    ):
        """
        初始化IC筛选器
        
        Args:
            ic_threshold: IC均值阈值
            ir_threshold: IC_IR阈值 (IC均值/IC标准差)
            tstat_threshold: t统计量阈值
            min_records: 最小记录数
            max_ic_std: IC标准差上限
            min_ic_positive_ratio: IC正值比例下限
        """
        self.thresholds = {
            'ic_mean': ic_threshold,
            'ic_ir': ir_threshold,
            'ic_tstat': tstat_threshold,
            'min_records': min_records,
            'max_ic_std': max_ic_std,
            'min_ic_positive_ratio': min_ic_positive_ratio
        }
    
    def calculate_ic(
        self,
        factor_values: pd.Series,
        returns: pd.Series,
        method: str = 'spearman'
    ) -> float:
        """
        计算单期IC (Information Coefficient)
        
        Args:
            factor_values: 因子值序列
            returns: 收益率序列
            method: 相关系数方法 ('spearman' 或 'pearson')
            
        Returns:
            IC值
        """
        # 对齐索引
        aligned = pd.concat([factor_values, returns], axis=1, join='inner')
        if len(aligned) < 10:  # 样本太少
            return np.nan
        
        factor_col = aligned.columns[0]
        return_col = aligned.columns[1]
        
        # 移除NaN
        aligned = aligned.dropna()
        if len(aligned) < 10:
            return np.nan
        
        # 计算相关系数
        if method == 'spearman':
            ic, _ = stats.spearmanr(aligned[factor_col], aligned[return_col])
        else:
            ic, _ = stats.pearsonr(aligned[factor_col], aligned[return_col])
        
        return ic
    
    def calculate_ic_series(
        self,
        factor_values: pd.DataFrame,
        returns: pd.Series,
        method: str = 'spearman'
    ) -> pd.Series:
        """
        计算IC时间序列
        
        Args:
            factor_values: 因子值DataFrame (index: date, columns: stock_codes)
            returns: 收益率Series (MultiIndex: date, stock_code)
            method: 相关系数方法
            
        Returns:
            IC时间序列
        """
        ic_series = []
        dates = factor_values.index.unique()
        
        for date in dates:
            try:
                # 获取当期因子值
                day_factors = factor_values.loc[date]
                
                # 获取当期收益率
                if isinstance(returns.index, pd.MultiIndex):
                    day_returns = returns.loc[date]
                else:
                    day_returns = returns
                
                # 计算IC
                ic = self.calculate_ic(day_factors, day_returns, method)
                ic_series.append({'date': date, 'ic': ic})
            except Exception as e:
                ic_series.append({'date': date, 'ic': np.nan})
        
        return pd.DataFrame(ic_series).set_index('date')['ic']
    
    def calculate_ic_metrics(
        self,
        ic_series: pd.Series
    ) -> Dict[str, float]:
        """
        计算IC相关指标
        
        Args:
            ic_series: IC时间序列
            
        Returns:
            指标字典
        """
        # 移除NaN
        valid_ic = ic_series.dropna()
        n = len(valid_ic)
        
        if n < 10:
            return {
                'ic_mean': np.nan,
                'ic_std': np.nan,
                'ic_ir': np.nan,
                'ic_tstat': np.nan,
                'ic_positive_ratio': np.nan,
                'ic_significant_ratio': np.nan,
                'n_records': n
            }
        
        # 计算各项指标
        ic_mean = valid_ic.mean()
        ic_std = valid_ic.std()
        ic_ir = ic_mean / ic_std if ic_std > 0 else 0
        
        # t统计量
        ic_tstat = ic_mean * np.sqrt(n) / ic_std if ic_std > 0 else 0
        
        # IC正值比例
        ic_positive_ratio = (valid_ic > 0).sum() / n
        
        # 显著性比例 (|IC| > 0.05)
        ic_significant_ratio = (valid_ic.abs() > 0.05).sum() / n
        
        return {
            'ic_mean': ic_mean,
            'ic_std': ic_std,
            'ic_ir': ic_ir,
            'ic_tstat': ic_tstat,
            'ic_positive_ratio': ic_positive_ratio,
            'ic_significant_ratio': ic_significant_ratio,
            'n_records': n
        }
    
    def filter_factor(
        self,
        factor_values: pd.Series,
        returns: pd.Series,
        method: str = 'spearman'
    ) -> Tuple[bool, Dict]:
        """
        筛选单个因子
        
        Args:
            factor_values: 因子值
            returns: 收益率
            method: 相关系数方法
            
        Returns:
            (是否通过, 指标字典)
        """
        # 计算IC
        ic = self.calculate_ic(factor_values, returns, method)
        
        if np.isnan(ic):
            return False, {'ic': np.nan, 'reason': '无法计算IC'}
        
        # 构建指标
        metrics = {
            'ic': ic,
            'n_records': len(factor_values.dropna())
        }
        
        # 检查条件
        passed = True
        reasons = []
        
        # 记录数检查
        if metrics['n_records'] < self.thresholds['min_records']:
            passed = False
            reasons.append(f"记录数不足: {metrics['n_records']} < {self.thresholds['min_records']}")
        
        # IC均值检查 (单期无法检查，保留接口)
        
        metrics['passed'] = passed
        if reasons:
            metrics['reason'] = '; '.join(reasons)
        
        return passed, metrics
    
    def filter_factors(
        self,
        factors_data: Dict[str, pd.Series],
        returns: pd.Series,
        method: str = 'spearman',
        verbose: bool = False
    ) -> Tuple[List[Dict], List[Dict]]:
        """
        批量筛选因子
        
        Args:
            factors_data: 因子数据字典 {factor_name: series}
            returns: 收益率
            method: 相关系数方法
            verbose: 是否打印详细信息
            
        Returns:
            (通过列表, 未通过列表)
        """
        passed_list = []
        failed_list = []
        
        for factor_name, factor_values in factors_data.items():
            passed, metrics = self.filter_factor(factor_values, returns, method)
            
            result = {
                'factor_name': factor_name,
                **metrics
            }
            
            if passed:
                passed_list.append(result)
                if verbose:
                    print(f"✓ {factor_name}: IC={metrics['ic']:.4f}")
            else:
                failed_list.append(result)
                if verbose:
                    reason = metrics.get('reason', '未知原因')
                    print(f"✗ {factor_name}: {reason}")
        
        return passed_list, failed_list
    
    def filter_by_ic_metrics(
        self,
        factors_ic_metrics: Dict[str, Dict],
        strict: bool = True
    ) -> Tuple[List[str], List[str]]:
        """
        根据IC指标筛选因子
        
        Args:
            factors_ic_metrics: 因子IC指标字典 {factor_name: metrics_dict}
            strict: 是否严格模式（满足所有条件）
            
        Returns:
            (通过因子名列表, 未通过因子名列表)
        """
        passed = []
        failed = []
        
        for factor_name, metrics in factors_ic_metrics.items():
            # 检查各项条件
            conditions = {
                'ic_mean': metrics.get('ic_mean', -np.inf) > self.thresholds['ic_mean'],
                'ic_ir': metrics.get('ic_ir', -np.inf) > self.thresholds['ic_ir'],
                'ic_tstat': metrics.get('ic_tstat', -np.inf) > self.thresholds['ic_tstat'],
                'n_records': metrics.get('n_records', 0) >= self.thresholds['min_records'],
                'ic_std': metrics.get('ic_std', np.inf) < self.thresholds['max_ic_std'],
                'ic_positive_ratio': metrics.get('ic_positive_ratio', 0) >= self.thresholds['min_ic_positive_ratio']
            }
            
            # 判断是否通过
            if strict:
                is_passed = all(conditions.values())
            else:
                # 宽松模式：至少满足IC均值、IC_IR、记录数
                is_passed = conditions['ic_mean'] and conditions['ic_ir'] and conditions['n_records']
            
            if is_passed:
                passed.append(factor_name)
            else:
                failed.append(factor_name)
        
        return passed, failed
    
    def rank_factors(
        self,
        factors_ic_metrics: Dict[str, Dict],
        top_n: int = 10,
        rank_by: str = 'ic_ir'
    ) -> List[Tuple[str, float]]:
        """
        按指标排名因子
        
        Args:
            factors_ic_metrics: 因子IC指标字典
            top_n: 返回前N个
            rank_by: 排名依据 ('ic_mean', 'ic_ir', 'ic_tstat')
            
        Returns:
            排名列表 [(factor_name, score), ...]
        """
        scores = []
        
        for factor_name, metrics in factors_ic_metrics.items():
            score = metrics.get(rank_by, -np.inf)
            if not np.isnan(score):
                scores.append((factor_name, score))
        
        # 降序排列
        scores.sort(key=lambda x: x[1], reverse=True)
        
        return scores[:top_n]
    
    def generate_report(
        self,
        factors_ic_metrics: Dict[str, Dict],
        output_format: str = 'dict'
    ) -> Dict:
        """
        生成筛选报告
        
        Args:
            factors_ic_metrics: 因子IC指标字典
            output_format: 输出格式 ('dict', 'dataframe')
            
        Returns:
            报告字典或DataFrame
        """
        passed_names, failed_names = self.filter_by_ic_metrics(factors_ic_metrics)
        
        # 统计信息
        total = len(factors_ic_metrics)
        passed_count = len(passed_names)
        
        report = {
            'summary': {
                'total_factors': total,
                'passed_factors': passed_count,
                'failed_factors': total - passed_count,
                'pass_rate': passed_count / total if total > 0 else 0,
                'thresholds': self.thresholds.copy()
            },
            'passed_factors': [
                {
                    'name': name,
                    **factors_ic_metrics.get(name, {})
                }
                for name in passed_names
            ],
            'failed_factors': [
                {
                    'name': name,
                    **factors_ic_metrics.get(name, {})
                }
                for name in failed_names
            ],
            'top_by_ic': self.rank_factors(factors_ic_metrics, top_n=10, rank_by='ic_mean'),
            'top_by_ir': self.rank_factors(factors_ic_metrics, top_n=10, rank_by='ic_ir')
        }
        
        if output_format == 'dataframe':
            report['passed_df'] = pd.DataFrame(report['passed_factors'])
            report['failed_df'] = pd.DataFrame(report['failed_factors'])
        
        return report


def quick_ic_analysis(
    factor: pd.Series,
    returns: pd.Series,
    method: str = 'spearman'
) -> Dict:
    """
    快速IC分析
    
    Args:
        factor: 因子值
        returns: 收益率
        method: 相关系数方法
        
    Returns:
        分析结果字典
    """
    filter_obj = ICFilter()
    ic = filter_obj.calculate_ic(factor, returns, method)
    passed, metrics = filter_obj.filter_factor(factor, returns, method)
    
    return {
        'ic': ic,
        'passed': passed,
        'metrics': metrics
    }