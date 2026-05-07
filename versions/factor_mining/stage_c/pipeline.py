"""
阶段C入口脚本
遗传规划因子挖掘流水线
"""

import numpy as np
import pandas as pd
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass, field
import logging
import json
import os
from datetime import datetime
import warnings

# 内部模块导入
from .genetic_optimizer import GeneticOptimizer, GeneticOptimizerConfig, create_optimizer
from .fitness_functions import ic_fitness, FitnessEvaluator, make_fitness_metric
from .primitive_set import make_function_set, get_full_function_set
from .cv_validator import CrossValidationValidator, CrossValidationConfig, quick_cv_check

logger = logging.getLogger(__name__)


@dataclass
class StageCConfig:
    """阶段C配置"""
    # 遗传规划参数
    population_size: int = 1000
    generations: int = 20
    tournament_size: int = 20
    stopping_criteria: float = 0.05
    random_state: int = 42
    n_jobs: int = -1
    
    # 交叉验证参数
    cv_n_splits: int = 5
    cv_decay_threshold: float = 0.03
    cv_min_test_ic: float = 0.02
    
    # IC筛选参数
    ic_threshold: float = 0.03
    ic_ir_threshold: float = 0.5
    
    # 真实数据参数
    use_real_data: bool = True
    include_derived_factors: bool = True
    
    # 输出参数
    output_top_n: int = 20
    output_dir: str = './output/factors'
    save_intermediate: bool = True
    
    # 早停参数
    early_stop_generations: int = 5
    early_stop_threshold: float = 0.001


class StageCPipeline:
    """
    阶段C：遗传规划因子挖掘流水线
    
    执行流程：
    1. 数据准备
    2. 遗传规划进化
    3. IC评估
    4. 交叉验证防过拟合
    5. 结果输出
    """
    
    def __init__(self, config: Optional[StageCConfig] = None):
        """
        初始化流水线
        
        Args:
            config: 配置对象
        """
        self.config = config or StageCConfig()
        
        # 组件
        self.optimizer: Optional[GeneticOptimizer] = None
        self.cv_validator: Optional[CrossValidationValidator] = None
        self.fitness_evaluator: FitnessEvaluator = FitnessEvaluator()
        
        # 结果存储
        self.results_: Dict[str, Any] = {}
        self.best_factors_: pd.DataFrame = pd.DataFrame()
        
    def prepare_data(
        self,
        X: np.ndarray,
        y: np.ndarray,
        feature_names: Optional[List[str]] = None,
        dates: Optional[pd.DatetimeIndex] = None
    ) -> Dict[str, Any]:
        """
        准备数据
        
        Args:
            X: 特征矩阵
            y: 目标收益
            feature_names: 特征名称
            dates: 日期索引
            
        Returns:
            数据准备结果
        """
        logger.info(f"准备数据: {X.shape[0]} 样本, {X.shape[1]} 特征")
        
        # 检查数据有效性
        valid_mask = ~(np.isnan(X).any(axis=1) | np.isnan(y) | np.isinf(X).any(axis=1) | np.isinf(y))
        
        X_clean = X[valid_mask]
        y_clean = y[valid_mask]
        
        if dates is not None:
            dates_clean = dates[valid_mask]
        else:
            dates_clean = None
        
        logger.info(f"有效样本: {len(X_clean)}/{len(X)}")
        
        # 特征名称
        if feature_names is None:
            feature_names = [f'f{i}' for i in range(X.shape[1])]
        
        self.data_info_ = {
            'X': X_clean,
            'y': y_clean,
            'feature_names': feature_names,
            'dates': dates_clean,
            'n_valid_samples': len(X_clean),
            'n_features': len(feature_names)
        }
        
        return self.data_info_
    
    def run_evolution(self) -> GeneticOptimizer:
        """
        执行遗传规划进化
        
        Returns:
            训练后的优化器
        """
        if not hasattr(self, 'data_info_'):
            raise ValueError("请先调用 prepare_data()")
        
        logger.info("开始遗传规划进化...")
        
        # 创建优化器
        optimizer_config = GeneticOptimizerConfig(
            population_size=self.config.population_size,
            generations=self.config.generations,
            tournament_size=self.config.tournament_size,
            stopping_criteria=self.config.stopping_criteria,
            random_state=self.config.random_state,
            n_jobs=self.config.n_jobs,
            feature_names=self.data_info_['feature_names']
        )
        
        self.optimizer = GeneticOptimizer(optimizer_config)
        
        # 训练
        self.optimizer.fit(
            self.data_info_['X'],
            self.data_info_['y'],
            self.data_info_['feature_names']
        )
        
        logger.info(f"进化完成，发现 {len(self.optimizer.best_programs_)} 个因子表达式")
        
        return self.optimizer
    
    def evaluate_factors(self) -> pd.DataFrame:
        """
        评估所有发现的因子
        
        Returns:
            评估结果DataFrame
        """
        if self.optimizer is None:
            raise ValueError("请先调用 run_evolution()")
        
        logger.info("评估因子...")
        
        # 获取因子值
        factor_values = self.optimizer.transform(self.data_info_['X'])
        
        # 评估
        eval_df = self.optimizer.evaluate_expressions(
            self.data_info_['X'],
            self.data_info_['y'],
            self.data_info_['feature_names']
        )
        
        self.eval_results_ = eval_df
        
        logger.info(f"评估完成，有效因子: {len(eval_df[abs(eval_df['ic']) >= self.config.ic_threshold])}")
        
        return eval_df
    
    def cross_validate(self) -> pd.DataFrame:
        """
        执行交叉验证防过拟合
        
        Returns:
            验证结果DataFrame
        """
        if self.optimizer is None:
            raise ValueError("请先调用 run_evolution()")
        
        logger.info("执行交叉验证...")
        
        # 创建验证器
        cv_config = CrossValidationConfig(
            n_splits=self.config.cv_n_splits,
            use_time_series_split=self.data_info_['dates'] is not None
        )
        self.cv_validator = CrossValidationValidator(cv_config)
        
        # 直接使用每个程序的execute方法获取因子值
        # 避免使用transform，因为transform内部有去重逻辑
        factor_list = []
        factor_info_list = []  # 保存对应的expression信息
        for prog_info in self.optimizer.best_programs_:
            program = prog_info['program']
            try:
                factor = program.execute(self.data_info_['X'])
                factor_list.append(factor)
                factor_info_list.append({
                    'expression': prog_info['expression'],
                    'fitness': prog_info['fitness'],
                    'length': prog_info['length']
                })
            except Exception:
                continue
        
        if len(factor_list) == 0:
            logger.warning("没有有效的因子可用于交叉验证")
            self.filtered_factors_ = np.array([])
            self.filtered_results_ = pd.DataFrame()
            return pd.DataFrame()
        
        factor_values = np.column_stack(factor_list)
        
        # 批量验证
        cv_df = self.cv_validator.validate_batch(
            factor_values,
            self.data_info_['y'],
            self.data_info_['dates'],
            top_n=len(factor_list)
        )
        
        # 将 expression 信息添加到 cv_df
        cv_df = cv_df.copy()
        for i, info in enumerate(factor_info_list):
            if i in cv_df['factor_index'].values:
                idx = cv_df[cv_df['factor_index'] == i].index
                cv_df.loc[idx, 'expression'] = info['expression']
                cv_df.loc[idx, 'fitness'] = info['fitness']
                cv_df.loc[idx, 'length'] = info['length']
        
        # 合合评估结果
        self.cv_results_ = cv_df
        
        # 过滤过拟合因子
        filtered_factors, filtered_results = self.cv_validator.filter_overfitting(
            factor_values,
            self.data_info_['y'],
            self.data_info_['dates'],
            max_decay_threshold=self.config.cv_decay_threshold,
            min_test_ic=self.config.cv_min_test_ic
        )
        
        # 将 expression 信息添加到 filtered_results
        filtered_results = filtered_results.copy()
        for i, info in enumerate(factor_info_list):
            if i in filtered_results['factor_index'].values:
                idx = filtered_results[filtered_results['factor_index'] == i].index
                filtered_results.loc[idx, 'expression'] = info['expression']
                filtered_results.loc[idx, 'fitness'] = info['fitness']
                filtered_results.loc[idx, 'length'] = info['length']
        
        logger.info(f"交叉验证完成，筛选后因子: {len(filtered_results)}")
        
        self.filtered_factors_ = filtered_factors
        self.filtered_results_ = filtered_results
        
        return filtered_results
    
    def select_best_factors(self) -> pd.DataFrame:
        """
        选择最优因子
        
        Returns:
            最优因子DataFrame
        """
        if not hasattr(self, 'filtered_results_'):
            # 如果没有进行交叉验证，使用评估结果
            eval_df = self.eval_results_
            eval_df = eval_df[abs(eval_df['ic']) >= self.config.ic_threshold]
            selected = eval_df.head(self.config.output_top_n)
        else:
            # 使用交叉验证筛选结果
            # filtered_results_ 使用 test_ic_mean 作为 IC 值
            selected = self.filtered_results_.copy()
            # 统一列名，添加 'ic' 列
            if 'ic' not in selected.columns and 'test_ic_mean' in selected.columns:
                selected['ic'] = selected['test_ic_mean']
            selected = selected.head(self.config.output_top_n)
        
        # 添加更多信息
        selected = selected.copy()
        selected['create_time'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        selected['stage'] = 'C'
        
        self.best_factors_ = selected
        
        logger.info(f"选择最优因子: {len(selected)} 个")
        
        return selected
    
    def save_results(self, output_path: Optional[str] = None) -> str:
        """
        保存结果
        
        Args:
            output_path: 输出路径
            
        Returns:
            保存的文件路径
        """
        if output_path is None:
            output_path = self.config.output_dir
        
        os.makedirs(output_path, exist_ok=True)
        
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        
        # 保存因子表达式
        factor_file = os.path.join(output_path, f'stage_c_factors_{timestamp}.json')
        
        factor_data = {
            'config': {
                'population_size': self.config.population_size,
                'generations': self.config.generations,
                'cv_n_splits': self.config.cv_n_splits,
                'ic_threshold': self.config.ic_threshold
            },
            'data_info': {
                'n_samples': self.data_info_['n_valid_samples'],
                'n_features': self.data_info_['n_features'],
                'feature_names': self.data_info_['feature_names']
            },
            'best_factors': self.best_factors_.to_dict('records') if len(self.best_factors_) > 0 else [],
            'timestamp': timestamp
        }
        
        with open(factor_file, 'w', encoding='utf-8') as f:
            json.dump(factor_data, f, indent=2, ensure_ascii=False)
        
        logger.info(f"结果已保存到: {factor_file}")
        
        # 如果设置了保存中间结果
        if self.config.save_intermediate:
            intermediate_file = os.path.join(output_path, f'stage_c_intermediate_{timestamp}.json')
            
            # 获取程序信息但排除不可序列化的 program 对象
            all_programs = []
            if self.optimizer:
                for p in self.optimizer.get_best_expressions(self.config.output_top_n * 2):
                    all_programs.append({
                        'expression': p.get('expression', ''),
                        'fitness': p.get('fitness'),
                        'length': p.get('length'),
                        'rank': p.get('rank')
                    })
            
            intermediate_data = {
                'eval_results': self.eval_results_.to_dict('records') if hasattr(self, 'eval_results_') else [],
                'cv_results': self.cv_results_.to_dict('records') if hasattr(self, 'cv_results_') else [],
                'all_programs': all_programs
            }
            
            with open(intermediate_file, 'w', encoding='utf-8') as f:
                json.dump(intermediate_data, f, indent=2, ensure_ascii=False)
        
        self.results_['output_file'] = factor_file
        
        return factor_file
    
    def run(
        self,
        X: np.ndarray,
        y: np.ndarray,
        feature_names: Optional[List[str]] = None,
        dates: Optional[pd.DatetimeIndex] = None,
        save_output: bool = True
    ) -> Dict[str, Any]:
        """
        执行完整流水线
        
        Args:
            X: 特征矩阵
            y: 目标收益
            feature_names: 特征名称
            dates: 日期索引
            save_output: 是否保存输出
            
        Returns:
            执行结果
        """
        logger.info("="*60)
        logger.info("开始阶段C：遗传规划因子挖掘")
        logger.info("="*60)
        
        # 1. 数据准备
        self.prepare_data(X, y, feature_names, dates)
        
        # 2. 遗传规划进化
        self.run_evolution()
        
        # 3. 因子评估
        self.evaluate_factors()
        
        # 4. 交叉验证
        self.cross_validate()
        
        # 5. 选择最优因子
        self.select_best_factors()
        
        # 6. 保存结果
        if save_output:
            self.save_results()
        
        # 返回结果摘要
        summary = {
            'n_input_features': self.data_info_['n_features'],
            'n_generated_factors': len(self.optimizer.best_programs_),
            'n_ic_filtered': len(self.eval_results_[abs(self.eval_results_['ic']) >= self.config.ic_threshold]),
            'n_cv_filtered': len(self.filtered_results_) if hasattr(self, 'filtered_results_') else 0,
            'n_final_factors': len(self.best_factors_),
            'best_ic': self.best_factors_['ic'].max() if len(self.best_factors_) > 0 else None,
            'output_file': self.results_.get('output_file')
        }
        
        logger.info("="*60)
        logger.info(f"阶段C完成: 发现 {summary['n_final_factors']} 个有效因子")
        logger.info("="*60)
        
        self.results_['summary'] = summary
        
        return self.results_
    
    def get_best_expressions(self, n: int = 10) -> List[str]:
        """
        获取最优表达式字符串
        
        Args:
            n: 返回数量
            
        Returns:
            表达式列表
        """
        if self.optimizer is None:
            return []
        
        return self.optimizer.get_expression_strings(n)
    
    def get_report(self) -> str:
        """
        获取执行报告
        
        Returns:
            报告文本
        """
        report_lines = [
            "# 阶段C：遗传规划因子挖掘报告",
            "",
            f"执行时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            "",
            "## 配置参数",
            f"- 种群大小: {self.config.population_size}",
            f"- 迭代代数: {self.config.generations}",
            f"- 交叉验证折数: {self.config.cv_n_splits}",
            f"- IC阈值: {self.config.ic_threshold}",
            "",
            "## 执行结果",
            f"- 输入特征数: {self.data_info_['n_features']}",
            f"- 有效样本数: {self.data_info_['n_valid_samples']}",
            f"- 生成因子数: {len(self.optimizer.best_programs_)}",
            f"- IC筛选通过: {len(self.eval_results_[abs(self.eval_results_['ic']) >= self.config.ic_threshold])}",
            f"- CV筛选通过: {len(self.filtered_results_) if hasattr(self, 'filtered_results_') else 0}",
            f"- 最终因子数: {len(self.best_factors_)}",
            "",
            "## 最优因子表达式",
        ]
        
        for i, row in self.best_factors_.head(10).iterrows():
            report_lines.append(f"{i+1}. {row['expression']} - IC: {row['ic']:.4f}")
        
        report_lines.append("")
        report_lines.append("---")
        report_lines.append("报告生成完成")
        
        return "\n".join(report_lines)


# ============ 快捷函数 ============

def run_stage_c(
    X: np.ndarray,
    y: np.ndarray,
    feature_names: Optional[List[str]] = None,
    population_size: int = 1000,
    generations: int = 20,
    cv_n_splits: int = 5,
    ic_threshold: float = 0.03,
    output_dir: str = './output/factors'
) -> Dict[str, Any]:
    """
    快捷函数：运行阶段C
    
    Args:
        X: 特征矩阵
        y: 目标收益
        feature_names: 特征名称
        population_size: 种群大小
        generations: 迭代代数
        cv_n_splits: 交叉验证折数
        ic_threshold: IC阈值
        output_dir: 输出目录
        
    Returns:
        执行结果
    """
    config = StageCConfig(
        population_size=population_size,
        generations=generations,
        cv_n_splits=cv_n_splits,
        ic_threshold=ic_threshold,
        output_dir=output_dir
    )
    
    pipeline = StageCPipeline(config)
    return pipeline.run(X, y, feature_names)


def quick_evolve(
    X: np.ndarray,
    y: np.ndarray,
    generations: int = 10
) -> List[str]:
    """
    快捷函数：快速进化
    
    Args:
        X: 特征矩阵
        y: 目标收益
        generations: 迭代代数
        
    Returns:
        表达式列表
    """
    optimizer = create_optimizer(population_size=500, generations=generations)
    optimizer.fit(X, y)
    
    return optimizer.get_expression_strings(10)


# ============ 主函数 ============

def main():
    """主函数示例"""
    # 示例数据
    np.random.seed(42)
    n_samples = 1000
    n_features = 6
    
    X = np.random.randn(n_samples, n_features)
    y = np.random.randn(n_samples) * 0.1 + X[:, 0] * 0.05  # 与第一个特征相关
    
    feature_names = ['rsi', 'kdj_j', 'bollinger_pb', 'volume_ratio', 'turnover_surge', 'main_inflow_ratio']
    
    # 运行流水线
    config = StageCConfig(
        population_size=500,  # 演示用较小种群
        generations=5,        # 演示用较少代数
        output_top_n=10
    )
    
    pipeline = StageCPipeline(config)
    results = pipeline.run(X, y, feature_names)
    
    # 输出报告
    print(pipeline.get_report())


if __name__ == "__main__":
    main()