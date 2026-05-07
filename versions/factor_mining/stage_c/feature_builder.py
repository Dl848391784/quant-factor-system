"""
阶段C真实特征矩阵构建器

从阶段A/B筛选的因子构建遗传规划输入矩阵
"""

import numpy as np
import pandas as pd
from typing import Dict, List, Tuple, Optional, Any
import logging

logger = logging.getLogger(__name__)


class FeatureMatrixBuilder:
    """特征矩阵构建器"""
    
    def __init__(self, data_loader: Any):
        """
        初始化构建器
        
        Args:
            data_loader: RealFactorLoader实例
        """
        self.data_loader = data_loader
        self._feature_cache: Dict[str, pd.Series] = {}
    
    def build_from_real_factors(
        self,
        base_factors: Optional[List[str]] = None,
        derived_factors: Optional[List[Dict]] = None,
        target_return: str = 'forward_return_1d',
        max_samples: Optional[int] = None,
        verbose: bool = True
    ) -> Tuple[np.ndarray, np.ndarray, List[str]]:
        """
        从真实因子构建特征矩阵
        
        Args:
            base_factors: 基础因子名列表
            derived_factors: 阶段A筛选出的组合因子列表
            target_return: 目标收益率类型
            max_samples: 最大样本数（用于快速测试）
            verbose: 是否打印详细信息
            
        Returns:
            X: 特征矩阵 (n_samples, n_features)
            y: 目标收益 (n_samples,)
            feature_names: 特征名列表
        """
        # 1. 加载基础因子
        if base_factors is None:
            base_factors = ['rsi_6', 'volume_ratio_5', 'kdj_j', 'bollinger_pb', 'turnover_rate']
        
        factor_data, returns = self.data_loader.prepare_panel_data(
            factor_names=base_factors,
            return_type=target_return,
            align_dates=True,
            verbose=verbose
        )
        
        self._feature_cache = factor_data.copy()
        
        # 2. 计算衍生因子（如果有阶段A输出）
        if derived_factors and len(derived_factors) > 0:
            try:
                from stage_a.factor_combiner import FactorCombiner
                combiner = FactorCombiner()
                
                for f in derived_factors:
                    expr = f.get('expression', '')
                    factor_id = f.get('factor_id', '')
                    try:
                        derived_values = combiner.compute_expression(expr, factor_data)
                        if derived_values is not None and len(derived_values) > 0:
                            factor_data[factor_id] = derived_values
                            if verbose:
                                logger.info(f"[衍生因子] {factor_id}: {expr[:30]}...")
                    except Exception as e:
                        if verbose:
                            logger.warning(f"[跳过衍生因子] {factor_id}: {str(e)[:50]}")
            except ImportError:
                if verbose:
                    logger.warning("无法导入FactorCombiner，跳过衍生因子")
        
        # 3. 构建DataFrame矩阵
        # 将因子字典转为DataFrame
        factor_df = pd.DataFrame(factor_data)
        
        # 确保returns对齐
        if len(returns) > 0:
            returns = returns.loc[factor_df.index]
        
        # 清理缺失值
        factor_df = factor_df.dropna()
        returns = returns.loc[factor_df.index]
        
        # 样本数限制
        if max_samples and len(factor_df) > max_samples:
            # 随机采样
            sample_idx = factor_df.sample(n=max_samples, random_state=42).index
            factor_df = factor_df.loc[sample_idx]
            returns = returns.loc[sample_idx]
            if verbose:
                logger.info(f"[样本限制] 从{len(returns)}样本中采样{max_samples}")
        
        # 转为numpy数组
        X = factor_df.values
        y = returns.values
        feature_names = list(factor_df.columns)
        
        if verbose:
            print(f"[特征矩阵] 构建完成:")
            print(f"  - 样本数: {X.shape[0]}")
            print(f"  - 特征数: {X.shape[1]}")
            print(f"  - 特征列表: {feature_names[:10]}{'...' if len(feature_names) > 10 else ''}")
        
        return X, y, feature_names
    
    def build_cross_sectional(
        self,
        date: str,
        factor_names: Optional[List[str]] = None
    ) -> Tuple[np.ndarray, np.ndarray, List[str]]:
        """
        构建单日截面特征矩阵
        
        Args:
            date: 日期字符串
            factor_names: 因子列表
            
        Returns:
            X: (n_assets, n_features)
            y: (n_assets,) 当日收益率
            feature_names: 特征名
        """
        if factor_names is None:
            factor_names = ['rsi_6', 'volume_ratio_5', 'kdj_j', 'bollinger_pb', 'turnover_rate']
        
        # 加载因子
        factor_data, returns = self.data_loader.prepare_panel_data(factor_names)
        
        # 筛选特定日期
        date_ts = pd.to_datetime(date)
        
        X_list = []
        y_list = []
        assets = []
        
        for asset in returns.index.get_level_values('asset').unique():
            try:
                idx = (date_ts, asset)
                X_row = [factor_data[f].get(idx, np.nan) for f in factor_names]
                y_val = returns.get(idx, np.nan)
                
                if not any(np.isnan(X_row)) and not np.isnan(y_val):
                    X_list.append(X_row)
                    y_list.append(y_val)
                    assets.append(asset)
            except KeyError:
                continue
        
        X = np.array(X_list)
        y = np.array(y_list)
        
        logger.info(f"[截面数据] {date}: {len(assets)}只股票")
        
        return X, y, factor_names
    
    def build_time_series_window(
        self,
        factor_names: Optional[List[str]] = None,
        window_size: int = 5,
        sample_ratio: float = 0.1
    ) -> Tuple[np.ndarray, np.ndarray, List[str]]:
        """
        构建时序窗口特征矩阵
        
        Args:
            factor_names: 因子列表
            window_size: 窗口大小
            sample_ratio: 采样比例
            
        Returns:
            X: (n_samples, n_features * window_size)
            y: (n_samples,) 目标收益
            feature_names: 扩展后的特征名
        """
        if factor_names is None:
            factor_names = ['rsi_6', 'volume_ratio_5', 'kdj_j', 'bollinger_pb', 'turnover_rate']
        
        factor_data, returns = self.data_loader.prepare_panel_data(factor_names)
        
        # 按日期排序
        dates = sorted(factor_data[factor_names[0]].index.get_level_values('date').unique())
        
        # 采样日期
        if sample_ratio < 1.0:
            n_dates = int(len(dates) * sample_ratio)
            dates = dates[-n_dates:]  # 取最近的日期
        
        X_list = []
        y_list = []
        expanded_names = []
        
        # 构建扩展特征名
        for f in factor_names:
            for w in range(window_size):
                expanded_names.append(f"{f}_lag{w}")
        
        # 构建窗口数据
        for i in range(window_size, len(dates)):
            current_date = dates[i]
            
            # 收集窗口内所有因子值
            window_dates = dates[i-window_size:i]
            
            for asset in returns.index.get_level_values('asset').unique():
                try:
                    # 目标收益率
                    y_val = returns.get((current_date, asset), np.nan)
                    if np.isnan(y_val):
                        continue
                    
                    # 窗口因子值
                    X_row = []
                    valid = True
                    for f in factor_names:
                        for wd in window_dates:
                            val = factor_data[f].get((wd, asset), np.nan)
                            if np.isnan(val):
                                valid = False
                                break
                            X_row.append(val)
                        if not valid:
                            break
                    
                    if valid:
                        X_list.append(X_row)
                        y_list.append(y_val)
                        
                except KeyError:
                    continue
        
        X = np.array(X_list)
        y = np.array(y_list)
        
        logger.info(f"[时序窗口] 窗口={window_size}, 样本数={len(y)}")
        
        return X, y, expanded_names
    
    def get_factor_stats(self) -> Dict[str, Dict]:
        """
        获取因子统计信息
        
        Returns:
            各因子统计信息字典
        """
        stats = {}
        for name, series in self._feature_cache.items():
            stats[name] = {
                'count': len(series),
                'mean': series.mean(),
                'std': series.std(),
                'min': series.min(),
                'max': series.max(),
                'nan_count': series.isna().sum()
            }
        return stats


# 快速测试
def test_feature_builder():
    """测试特征矩阵构建"""
    from stage_a.data_loader import RealFactorLoader
    
    loader = RealFactorLoader()
    builder = FeatureMatrixBuilder(loader)
    
    # 测试基础构建
    print("测试基础特征矩阵构建...")
    X, y, names = builder.build_from_real_factors(verbose=True)
    
    print(f"\n矩阵形状: X={X.shape}, y={y.shape}")
    print(f"特征名: {names}")
    
    return X, y, names


if __name__ == '__main__':
    test_feature_builder()