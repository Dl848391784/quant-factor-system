"""
IC 计算模块
计算因子的 Rank IC 和统计指标
"""

import numpy as np
import pandas as pd
from scipy.stats import spearmanr
from typing import Dict, List, Optional, Tuple
import warnings


class ICCalculator:
    """IC计算器 - 计算因子的Rank IC及相关统计指标"""
    
    def __init__(self, factor_data: pd.DataFrame, return_data: pd.DataFrame):
        """
        初始化IC计算器
        
        Args:
            factor_data: 因子数据 (MultiIndex: date, stock)
            return_data: 收益数据 (MultiIndex: date, stock)
        """
        self.factor_data = factor_data
        self.return_data = return_data
        self.ic_results = {}  # 存储各因子的IC结果
        
    def calc_rank_ic(
        self,
        factor_series: pd.Series,
        return_series: pd.Series
    ) -> float:
        """
        计算单个时间点的 Rank IC (Spearman秩相关系数)
        
        Args:
            factor_series: 因子值序列 (index: 股票代码)
            return_series: 收益率序列 (index: 股票代码)
            
        Returns:
            Rank IC值 (-1 到 1)
        """
        # 对齐股票
        common_stocks = factor_series.index.intersection(return_series.index)
        
        if len(common_stocks) < 5:
            # 样本太少，无法计算有效IC
            return np.nan
        
        factor_values = factor_series[common_stocks].values
        return_values = return_series[common_stocks].values
        
        # 剔除NaN
        valid_mask = ~(np.isnan(factor_values) | np.isnan(return_values))
        if valid_mask.sum() < 5:
            return np.nan
            
        factor_valid = factor_values[valid_mask]
        return_valid = return_values[valid_mask]
        
        # 计算Spearman秩相关系数
        # 修复: 添加异常处理，捕获特定异常类型
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                ic, p_value = spearmanr(factor_valid, return_valid)
        except (ValueError, RuntimeError) as e:
            # 当样本量过小或数据全为常数时可能抛出异常
            return 0.0
        
        return ic if not np.isnan(ic) else 0.0
    
    def calc_factor_daily_ic(
        self,
        factor_name: str,
        return_col: str = 'return_5d'
    ) -> pd.Series:
        """
        计算某个因子的每日IC序列
        
        Args:
            factor_name: 因子名称
            return_col: 收益率列名
            
        Returns:
            Series, index为日期, value为IC值
        """
        # 获取所有交易日
        dates = self.factor_data.index.get_level_values('date').unique()
        
        ic_series = []
        
        print(f"\n计算因子 '{factor_name}' 的每日IC...")
        
        for date in dates:
            # 获取当日因子值
            try:
                factor_series = self.factor_data.xs(date, level='date')[factor_name]
                return_series = self.return_data.xs(date, level='date')[return_col]
            except KeyError:
                ic_series.append(np.nan)
                continue
            
            # 计算IC
            ic = self.calc_rank_ic(factor_series, return_series)
            ic_series.append(ic)
        
        ic_series = pd.Series(ic_series, index=dates)
        ic_series.name = f'{factor_name}_IC'
        
        # 存储结果
        self.ic_results[factor_name] = {
            'ic_series': ic_series,
            'statistics': None  # 稍后计算
        }
        
        print(f"✓ 完成，共 {len(ic_series)} 个交易日")
        
        return ic_series
    
    def calc_statistics(self, ic_series: pd.Series) -> Dict[str, float]:
        """
        计算IC的统计指标
        
        Args:
            ic_series: IC序列
            
        Returns:
            统计指标字典
        """
        # 剔除NaN
        ic_valid = ic_series.dropna()
        n = len(ic_valid)
        
        if n == 0:
            return {
                'ic_mean': np.nan,
                'ic_std': np.nan,
                'icir': np.nan,
                't_stat': np.nan,
                'ic_positive_ratio': np.nan,
                'sample_count': 0
            }
        
        # IC均值
        ic_mean = ic_valid.mean()
        
        # IC标准差
        ic_std = ic_valid.std()
        
        # ICIR (Information Ratio) = IC均值 / IC标准差
        icir = ic_mean / ic_std if ic_std != 0 else np.nan
        
        # t统计量 = IC均值 / (IC标准差 / sqrt(n))
        t_stat = ic_mean / (ic_std / np.sqrt(n)) if ic_std != 0 else np.nan
        
        # IC > 0 占比
        ic_positive_ratio = (ic_valid > 0).sum() / n
        
        return {
            'ic_mean': ic_mean,
            'ic_std': ic_std,
            'icir': icir,
            't_stat': t_stat,
            'ic_positive_ratio': ic_positive_ratio,
            'sample_count': n
        }
    
    def analyze_factor(
        self,
        factor_name: str,
        return_col: str = 'return_5d'
    ) -> Tuple[pd.Series, Dict[str, float]]:
        """
        完整分析单个因子：计算IC序列 + 统计指标
        
        Args:
            factor_name: 因子名称
            return_col: 收益率列名
            
        Returns:
            (IC序列, 统计指标字典)
        """
        # 计算每日IC
        ic_series = self.calc_factor_daily_ic(factor_name, return_col)
        
        # 计算统计指标
        statistics = self.calc_statistics(ic_series)
        
        # 存储统计结果
        self.ic_results[factor_name]['statistics'] = statistics
        
        return ic_series, statistics
    
    def analyze_all_factors(
        self,
        factor_names: Optional[List[str]] = None,
        return_col: str = 'return_5d'
    ) -> Dict[str, Dict]:
        """
        分析所有因子
        
        Args:
            factor_names: 因子名称列表，如果为None则分析所有因子
            return_col: 收益率列名
            
        Returns:
            因子分析结果字典
        """
        if factor_names is None:
            # 自动识别因子列（排除原始值列）
            all_cols = self.factor_data.columns.tolist()
            # 布尔因子通常不以 'value' 或 'ratio' 结尾（原始值列）
            factor_names = [col for col in all_cols 
                          if not col.endswith('_value') and col != 'volume_ratio']
        
        print(f"\n{'='*60}")
        print(f"开始分析 {len(factor_names)} 个因子")
        print(f"{'='*60}")
        
        for factor_name in factor_names:
            self.analyze_factor(factor_name, return_col)
        
        return self.ic_results
    
    def get_summary(self) -> pd.DataFrame:
        """
        获取所有因子的统计摘要
        
        Returns:
            DataFrame, 每行一个因子，列为各项统计指标
        """
        summary_data = []
        
        for factor_name, result in self.ic_results.items():
            stats = result['statistics']
            if stats:
                summary_data.append({
                    'factor': factor_name,
                    'IC均值': stats['ic_mean'],
                    'IC标准差': stats['ic_std'],
                    'ICIR': stats['icir'],
                    't统计量': stats['t_stat'],
                    'IC>0占比': stats['ic_positive_ratio'],
                    '样本数': stats['sample_count']
                })
        
        return pd.DataFrame(summary_data)
    
    def print_report(self):
        """打印分析报告"""
        print(f"\n{'='*60}")
        print("因子IC分析报告")
        print(f"{'='*60}\n")
        
        for factor_name, result in self.ic_results.items():
            stats = result['statistics']
            if stats is None:
                continue
                
            print(f"【{factor_name}】")
            print(f"  IC均值:     {stats['ic_mean']:.4f}")
            print(f"  IC标准差:   {stats['ic_std']:.4f}")
            print(f"  ICIR:       {stats['icir']:.4f}")
            print(f"  t统计量:    {stats['t_stat']:.4f}")
            print(f"  IC>0占比:   {stats['ic_positive_ratio']:.2%}")
            print(f"  样本数:     {stats['sample_count']}个交易日")
            
            # 简单评级
            icir = abs(stats['icir']) if not np.isnan(stats['icir']) else 0
            if icir > 1.0:
                grade = "A级 (优秀)"
            elif icir > 0.5:
                grade = "B级 (良好)"
            elif icir > 0.3:
                grade = "C级 (一般)"
            else:
                grade = "D级 (较弱)"
            
            print(f"  因子评级:   {grade}")
            print()