"""
遗传规划因子挖掘引擎
基于gplearn的SymbolicTransformer实现
"""

import numpy as np
import pandas as pd
from typing import Dict, List, Optional, Tuple, Any, Callable
from dataclasses import dataclass, field
import warnings
import logging

# gplearn imports
try:
    from gplearn.genetic import SymbolicTransformer, SymbolicRegressor
    from gplearn.functions import make_function
    GPLEARN_AVAILABLE = True
except ImportError:
    GPLEARN_AVAILABLE = False
    warnings.warn("gplearn not installed. Run: pip install gplearn")

# 项目内部导入
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))

from ic_calculator import ICCalculator

logger = logging.getLogger(__name__)


@dataclass
class GeneticOptimizerConfig:
    """遗传规划配置"""
    # 种群参数
    population_size: int = 1000
    generations: int = 20
    tournament_size: int = 20
    
    # 停止条件
    stopping_criteria: float = 0.05
    
    # 遗传操作概率
    p_crossover: float = 0.7
    p_subtree_mutation: float = 0.1
    p_hoist_mutation: float = 0.05
    p_point_mutation: float = 0.1
    
    # 其他参数
    max_samples: float = 0.9
    parsimony_coefficient: float = 0.001
    random_state: int = 42
    n_jobs: int = -1
    verbose: int = 1
    
    # 表达式复杂度限制
    init_depth: Tuple[int, int] = (2, 6)
    max_depth: int = 10
    const_range: Tuple[float, float] = (-1.0, 1.0)
    
    # 特征名称
    feature_names: Optional[List[str]] = None


class GeneticOptimizer:
    """
    遗传规划因子挖掘引擎
    
    使用gplearn.SymbolicTransformer自动发现因子表达式
    """
    
    def __init__(self, config: Optional[GeneticOptimizerConfig] = None):
        """
        初始化遗传规划引擎
        
        Args:
            config: 配置对象
        """
        if not GPLEARN_AVAILABLE:
            raise ImportError("gplearn is required. Install with: pip install gplearn")
        
        self.config = config or GeneticOptimizerConfig()
        self.model_: Optional[SymbolicTransformer] = None
        self.best_programs_: List[Any] = []
        self.history_: Dict[str, List] = {
            'generation': [],
            'best_fitness': [],
            'avg_fitness': [],
            'best_length': []
        }
        
    def _build_function_set(self) -> List:
        """构建函数集"""
        from .primitive_set import make_function_set
        return make_function_set()
    
    def fit(
        self,
        X: np.ndarray,
        y: np.ndarray,
        feature_names: Optional[List[str]] = None,
        sample_weight: Optional[np.ndarray] = None
    ) -> 'GeneticOptimizer':
        """
        训练遗传规划模型
        
        Args:
            X: 特征矩阵 (n_samples, n_features)
            y: 目标变量（未来收益）
            feature_names: 特征名称列表
            sample_weight: 样本权重
            
        Returns:
            self
        """
        logger.info(f"开始遗传规划训练: 种群大小={self.config.population_size}, "
                   f"迭代代数={self.config.generations}")
        
        # 构建函数集
        function_set = self._build_function_set()
        
        # 特征名称
        if feature_names is None:
            feature_names = [f'f{i}' for i in range(X.shape[1])]
        
        # 创建SymbolicTransformer
        # hall_of_fame 控制transform返回的列数，必须与best_programs_数量匹配
        hall_of_fame = min(self.config.population_size, 100)
        
        self.model_ = SymbolicTransformer(
            # 种群参数
            population_size=self.config.population_size,
            generations=self.config.generations,
            tournament_size=self.config.tournament_size,
            hall_of_fame=hall_of_fame,
            
            # 停止条件
            stopping_criteria=self.config.stopping_criteria,
            
            # 遗传操作概率
            p_crossover=self.config.p_crossover,
            p_subtree_mutation=self.config.p_subtree_mutation,
            p_hoist_mutation=self.config.p_hoist_mutation,
            p_point_mutation=self.config.p_point_mutation,
            
            # 其他参数
            max_samples=self.config.max_samples,
            parsimony_coefficient=self.config.parsimony_coefficient,
            random_state=self.config.random_state,
            n_jobs=self.config.n_jobs,
            verbose=self.config.verbose,
            
            # 表达式参数
            init_depth=self.config.init_depth,
            const_range=self.config.const_range,
            function_set=function_set,
            feature_names=feature_names
        )
        
        # 训练
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            self.model_.fit(X, y, sample_weight=sample_weight)
        
        # 提取最优程序
        self._extract_best_programs()
        
        logger.info(f"训练完成，发现 {len(self.best_programs_)} 个有效因子表达式")
        
        return self
    
    def _extract_best_programs(self):
        """提取最优程序"""
        self.best_programs_ = []
        
        if self.model_ is None:
            return
        
        # 获取hall_of_fame中的程序，数量由hall_of_fame参数控制
        hall_of_fame = self.model_.hall_of_fame
        for i, program in enumerate(self.model_._programs[-1][:hall_of_fame]):
            if program is not None:
                self.best_programs_.append({
                    'rank': i + 1,
                    'program': program,
                    'expression': str(program),
                    'fitness': program.raw_fitness_,
                    'length': program.length_
                })
        
        # 按fitness排序
        self.best_programs_.sort(key=lambda x: abs(x['fitness']), reverse=True)
    
    def transform(self, X: np.ndarray) -> np.ndarray:
        """
        使用发现的因子表达式转换数据
        
        Args:
            X: 特征矩阵
            
        Returns:
            转换后的因子值矩阵 (n_samples, n_best_programs)
        """
        if self.model_ is None:
            raise ValueError("Model not fitted. Call fit() first.")
        
        return self.model_.transform(X)
    
    def fit_transform(
        self,
        X: np.ndarray,
        y: np.ndarray,
        feature_names: Optional[List[str]] = None
    ) -> np.ndarray:
        """
        训练并转换
        
        Args:
            X: 特征矩阵
            y: 目标变量
            feature_names: 特征名称
            
        Returns:
            转换后的因子值矩阵
        """
        self.fit(X, y, feature_names)
        return self.transform(X)
    
    def get_best_expressions(self, top_n: int = 10) -> List[Dict]:
        """
        获取最优因子表达式
        
        Args:
            top_n: 返回前N个
            
        Returns:
            表达式列表
        """
        return self.best_programs_[:top_n]
    
    def get_expression_strings(self, top_n: int = 10) -> List[str]:
        """
        获取表达式字符串
        
        Args:
            top_n: 返回前N个
            
        Returns:
            表达式字符串列表
        """
        return [p['expression'] for p in self.best_programs_[:top_n]]
    
    def evaluate_expressions(
        self,
        X: np.ndarray,
        y: np.ndarray,
        feature_names: Optional[List[str]] = None
    ) -> pd.DataFrame:
        """
        评估所有发现的因子表达式
        
        Args:
            X: 特征矩阵
            y: 目标变量（未来收益）
            feature_names: 特征名称
            
        Returns:
            评估结果DataFrame
        """
        results = []
        
        from scipy.stats import spearmanr
        
        # 直接使用每个程序的execute方法获取因子值
        # 避免使用transform，因为transform内部有去重逻辑
        for i, prog_info in enumerate(self.best_programs_):
            program = prog_info['program']
            try:
                factor = program.execute(X)
            except Exception:
                # 如果执行失败，跳过该程序
                continue
            
            # 计算IC
            valid_mask = ~(np.isnan(factor) | np.isnan(y))
            if valid_mask.sum() > 10:
                ic, p_value = spearmanr(factor[valid_mask], y[valid_mask])
            else:
                ic, p_value = np.nan, np.nan
            
            results.append({
                'rank': prog_info['rank'],
                'expression': prog_info['expression'],
                'fitness': prog_info['fitness'],
                'length': prog_info['length'],
                'ic': ic,
                'ic_pvalue': p_value,
                'valid_samples': valid_mask.sum()
            })
        
        return pd.DataFrame(results)
    
    def save_results(self, filepath: str):
        """保存结果到文件"""
        import json
        
        results = {
            'config': {
                'population_size': self.config.population_size,
                'generations': self.config.generations,
                'tournament_size': self.config.tournament_size,
                'p_crossover': self.config.p_crossover,
                'p_subtree_mutation': self.config.p_subtree_mutation,
                'p_hoist_mutation': self.config.p_hoist_mutation,
                'p_point_mutation': self.config.p_point_mutation,
            },
            'best_programs': [
                {
                    'rank': p['rank'],
                    'expression': p['expression'],
                    'fitness': float(p['fitness']) if not np.isnan(p['fitness']) else None,
                    'length': p['length']
                }
                for p in self.best_programs_
            ]
        }
        
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(results, f, indent=2, ensure_ascii=False)
        
        logger.info(f"结果已保存到 {filepath}")
    
    def get_history(self) -> pd.DataFrame:
        """获取进化历史"""
        return pd.DataFrame(self.history_)
    
    @property
    def feature_importances_(self) -> np.ndarray:
        """特征重要性（基于使用频率）"""
        if not self.best_programs_:
            return None
        
        # 统计各特征在表达式中的使用频率
        feature_counts = {}
        for prog_info in self.best_programs_:
            expr = prog_info['expression']
            # 简单统计特征出现次数
            # TODO: 更精确的解析
            pass
        
        return None


def create_optimizer(
    population_size: int = 1000,
    generations: int = 20,
    random_state: int = 42,
    **kwargs
) -> GeneticOptimizer:
    """
    快捷函数：创建遗传规划优化器
    
    Args:
        population_size: 种群大小
        generations: 迭代代数
        random_state: 随机种子
        **kwargs: 其他配置参数
        
    Returns:
        GeneticOptimizer实例
    """
    config = GeneticOptimizerConfig(
        population_size=population_size,
        generations=generations,
        random_state=random_state,
        **kwargs
    )
    return GeneticOptimizer(config)