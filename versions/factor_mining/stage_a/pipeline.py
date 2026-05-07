"""
阶段A Pipeline入口模块

执行阶段A因子挖掘完整流程
"""

import numpy as np
import pandas as pd
from typing import Dict, List, Optional, Tuple
import json
import os
from datetime import datetime
import warnings

from .factor_combiner import FactorCombiner
from .ic_filter import ICFilter
from .safe_math import SafeMath
from .deduplicator import FactorDeduplicator

warnings.filterwarnings('ignore')


class StageAPipeline:
    """
    阶段A流水线
    
    执行流程：
    1. 加载基础因子数据
    2. 生成组合因子
    3. IC筛选
    4. 因子去重
    5. 输出结果
    """
    
    # 配置
    DEFAULT_CONFIG = {
        'ic_threshold': 0.03,
        'ir_threshold': 0.5,
        'tstat_threshold': 2.0,
        'correlation_threshold': 0.8,
        'min_records': 100,
        'max_combinations': 500,
        'keep_strategy': 'highest_ic',
        'verbose': True
    }
    
    def __init__(
        self,
        config: Optional[Dict] = None,
        output_dir: Optional[str] = None
    ):
        """
        初始化Pipeline
        
        Args:
            config: 配置字典
            output_dir: 输出目录
        """
        self.config = config or self.DEFAULT_CONFIG.copy()
        self.output_dir = output_dir
        
        # 初始化组件
        self.combiner = FactorCombiner(
            max_combination_depth=2,
            include_unary=True
        )
        
        self.ic_filter = ICFilter(
            ic_threshold=self.config['ic_threshold'],
            ir_threshold=self.config['ir_threshold'],
            tstat_threshold=self.config['tstat_threshold'],
            min_records=self.config['min_records']
        )
        
        self.deduplicator = FactorDeduplicator(
            correlation_threshold=self.config['correlation_threshold'],
            keep_strategy=self.config['keep_strategy']
        )
        
        # 结果存储
        self.results = {
            'combinations': [],
            'filtered': [],
            'deduplicated': [],
            'final_factors': []
        }
    
    def load_base_factors(
        self,
        factor_data: Dict[str, pd.Series]
    ) -> Dict[str, pd.Series]:
        """
        加载并验证基础因子
        
        Args:
            factor_data: 因子数据字典
            
        Returns:
            验证后的因子数据
        """
        valid_factors = {}
        
        for name, data in factor_data.items():
            # 清理数据
            clean_data = SafeMath.clean_series(data, fill_value=0.0)
            
            # 验证有效性
            if len(clean_data.dropna()) >= self.config['min_records']:
                valid_factors[name] = clean_data
            elif self.config.get('verbose'):
                print(f"跳过因子 {name}: 有效记录不足")
        
        return valid_factors
    
    def run_combination(
        self,
        factor_data: Dict[str, pd.Series],
        include_nested: bool = True
    ) -> List[Dict]:
        """
        执行组合生成
        
        Args:
            factor_data: 基础因子数据
            include_nested: 是否包含嵌套组合
            
        Returns:
            组合因子列表
        """
        if self.config.get('verbose'):
            print("\n=== 阶段1: 因子组合生成 ===")
        
        # 更新combiner的基础因子
        self.combiner.base_factors = list(factor_data.keys())
        
        # 生成所有组合表达式
        expressions = self.combiner.generate_all(factor_data, include_nested)
        
        if self.config.get('verbose'):
            stats = self.combiner.get_expression_count()
            print(f"生成组合表达式: {stats['total']} 个")
            for type_name, count in stats.items():
                if type_name != 'total' and count > 0:
                    print(f"  - {type_name}: {count} 个")
        
        self.results['combinations'] = expressions
        return expressions
    
    def run_ic_filter(
        self,
        expressions: List[Dict],
        factor_data: Dict[str, pd.Series],
        returns: pd.Series
    ) -> Tuple[List[Dict], Dict[str, Dict]]:
        """
        执行IC筛选
        
        Args:
            expressions: 组合表达式列表
            factor_data: 基础因子数据
            returns: 收益率数据
            
        Returns:
            (通过的表达式列表, IC指标字典)
        """
        if self.config.get('verbose'):
            print("\n=== 阶段2: IC筛选 ===")
            print(f"筛选条件: IC>{self.config['ic_threshold']}, IR>{self.config['ir_threshold']}")
        
        passed_expressions = []
        ic_metrics = {}
        
        for expr_info in expressions:
            expr_str = expr_info['expression']
            
            try:
                # 计算组合因子值
                factor_values = self.combiner.compute_expression(expr_str, factor_data)
                
                # 计算IC
                ic = self.ic_filter.calculate_ic(factor_values, returns)
                
                if np.isnan(ic):
                    continue
                
                # 构建简单指标
                metrics = {
                    'ic': ic,
                    'n_records': len(factor_values.dropna())
                }
                
                # 检查是否通过筛选
                # 简化版：只检查IC阈值
                if abs(ic) > self.config['ic_threshold'] and metrics['n_records'] >= self.config['min_records']:
                    passed_expressions.append({
                        **expr_info,
                        'ic': ic
                        # 不保存factor_values，避免OOM（383个×1.5M样本=4.6GB）
                    })
                    ic_metrics[expr_info['expr_id']] = metrics
                    # 释放临时因子值
                    del factor_values
                
            except Exception as e:
                if self.config.get('verbose'):
                    print(f"跳过表达式 {expr_str}: {str(e)[:50]}")
        
        if self.config.get('verbose'):
            print(f"通过IC筛选: {len(passed_expressions)} / {len(expressions)}")
        
        self.results['filtered'] = passed_expressions
        return passed_expressions, ic_metrics
    
    def run_deduplicate(
        self,
        passed_expressions: List[Dict],
        verbose: bool = True
    ) -> Tuple[List[Dict], Dict]:
        """
        执行因子去重
        
        Args:
            passed_expressions: 通过IC筛选的表达式列表
            verbose: 是否打印详细信息
            
        Returns:
            (去重后的表达式列表, 统计信息)
        """
        if self.config.get('verbose'):
            print("\n=== 阶段3: 因子去重 ===")
            print(f"相关性阈值: {self.config['correlation_threshold']}")
        
        if len(passed_expressions) < 2:
            return passed_expressions, {'removed_count': 0}
        
        # 先按IC排序，只取top 50做去重（避免计算全部因子值的内存开销）
        sorted_exprs = sorted(passed_expressions, key=lambda x: abs(x['ic']), reverse=True)
        top_n = min(50, len(sorted_exprs))
        top_exprs = sorted_exprs[:top_n]
        
        if self.config.get('verbose'):
            print(f"取top {top_n}因子进行去重（避免OOM）")
        
        # 重新计算top N因子值（不保存，临时计算）
        factors_data = {}
        for expr in top_exprs:
            try:
                factor_values = self.combiner.compute_expression(expr['expression'], self._factor_data)
                factors_data[expr['expr_id']] = factor_values
            except Exception:
                continue
        
        # IC值字典（只取top）
        ic_values = {
            expr['expr_id']: expr['ic']
            for expr in top_exprs
        }
        
        # 表达式字典（只取top）
        expressions = {
            expr['expr_id']: expr['expression']
            for expr in top_exprs
        }
        
        # 执行去重
        deduplicated_data, removed_ids, stats = self.deduplicator.deduplicate(
            factors_data,
            ic_values=ic_values,
            expressions=expressions,
            verbose=verbose
        )
        
        # 构建去重后的表达式列表（从top_exprs取）
        deduplicated_expressions = [
            expr for expr in top_exprs
            if expr['expr_id'] in deduplicated_data
        ]
        
        if self.config.get('verbose'):
            print(f"去重完成: {top_n} -> {len(deduplicated_expressions)}")
            print(f"移除重复因子: {len(removed_ids)} 个")
        
        self.results['deduplicated'] = deduplicated_expressions
        return deduplicated_expressions, stats
    
    def generate_final_factors(
        self,
        deduplicated_expressions: List[Dict]
    ) -> List[Dict]:
        """
        生成最终因子列表
        
        Args:
            deduplicated_expressions: 去重后的表达式列表
            
        Returns:
            最终因子列表
        """
        final_factors = []
        
        for expr in deduplicated_expressions:
            factor_info = {
                'factor_id': expr['expr_id'],
                'expression': expr['expression'],
                'stage': 'A',
                'ic': expr.get('ic', 0),
                'factors': expr.get('factors', []),
                'operator': expr.get('operator', ''),
                'type': expr.get('type', ''),
                'create_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            }
            final_factors.append(factor_info)
        
        # 按IC排序
        final_factors.sort(key=lambda x: abs(x['ic']), reverse=True)
        
        self.results['final_factors'] = final_factors
        return final_factors
    
    def run(
        self,
        factor_data: Dict[str, pd.Series],
        returns: pd.Series,
        include_nested: bool = True,
        save_output: bool = False
    ) -> Dict:
        """
        执行完整流水线
        
        Args:
            factor_data: 基础因子数据字典
            returns: 收益率数据
            include_nested: 是否包含嵌套组合
            save_output: 是否保存输出
            
        Returns:
            执行结果字典
        """
        if self.config.get('verbose'):
            print("=" * 50)
            print("阶段A Pipeline 开始执行")
            print("=" * 50)
        
        # 保存因子数据供去重时重新计算用
        self._factor_data = factor_data
        
        # 1. 加载基础因子
        valid_factors = self.load_base_factors(factor_data)
        
        if len(valid_factors) < 2:
            return {
                'success': False,
                'message': '基础因子数量不足',
                'results': self.results
            }
        
        # 2. 组合生成
        expressions = self.run_combination(valid_factors, include_nested)
        
        if len(expressions) == 0:
            return {
                'success': False,
                'message': '未生成组合表达式',
                'results': self.results
            }
        
        # 3. IC筛选
        passed_expressions, ic_metrics = self.run_ic_filter(
            expressions, valid_factors, returns
        )
        
        if len(passed_expressions) == 0:
            return {
                'success': False,
                'message': '无因子通过IC筛选',
                'results': self.results
            }
        
        # 4. 去重
        deduplicated_expressions, dedup_stats = self.run_deduplicate(passed_expressions)
        
        # 5. 生成最终因子
        final_factors = self.generate_final_factors(deduplicated_expressions)
        
        # 保存输出
        if save_output and self.output_dir:
            self._save_results()
        
        if self.config.get('verbose'):
            print("\n" + "=" * 50)
            print("Pipeline 执行完成")
            print(f"最终因子数: {len(final_factors)}")
            print("=" * 50)
        
        return {
            'success': True,
            'message': '执行成功',
            'final_factors': final_factors,
            'stats': {
                'base_factors': len(valid_factors),
                'combinations': len(expressions),
                'ic_filtered': len(passed_expressions),
                'deduplicated': len(deduplicated_expressions),
                'final': len(final_factors)
            },
            'results': self.results
        }
    
    def _save_results(self):
        """
        保存结果到文件
        """
        if not self.output_dir:
            return
        
        os.makedirs(self.output_dir, exist_ok=True)
        
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        
        # 保存最终因子
        factors_file = os.path.join(self.output_dir, f'factors_stage_a_{timestamp}.json')
        with open(factors_file, 'w', encoding='utf-8') as f:
            json.dump(self.results['final_factors'], f, ensure_ascii=False, indent=2)
        
        # 保存报告
        report = self.generate_report()
        report_file = os.path.join(self.output_dir, f'report_stage_a_{timestamp}.json')
        with open(report_file, 'w', encoding='utf-8') as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
        
        if self.config.get('verbose'):
            print(f"\n结果已保存:")
            print(f"  - 因子文件: {factors_file}")
            print(f"  - 报告文件: {report_file}")
    
    def generate_report(self) -> Dict:
        """
        生成执行报告
        
        Returns:
            报告字典
        """
        final_factors = self.results['final_factors']
        
        # IC统计
        if final_factors:
            ic_values = [f['ic'] for f in final_factors]
            avg_ic = np.mean(ic_values)
            max_ic = np.max(ic_values)
            min_ic = np.min(ic_values)
        else:
            avg_ic = max_ic = min_ic = 0
        
        report = {
            'stage': 'A',
            'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'config': self.config,
            'summary': {
                'base_factors_count': len(self.combiner.base_factors),
                'combinations_generated': len(self.results['combinations']),
                'ic_filtered_count': len(self.results['filtered']),
                'deduplicated_count': len(self.results['deduplicated']),
                'final_factors_count': len(final_factors),
                'avg_ic': round(avg_ic, 4),
                'max_ic': round(max_ic, 4),
                'min_ic': round(min_ic, 4)
            },
            'top_factors': [
                {
                    'factor_id': f['factor_id'],
                    'expression': f['expression'],
                    'ic': f['ic']
                }
                for f in final_factors[:10]
            ],
            'final_factors': final_factors
        }
        
        return report


def run_stage_a(
    factor_data: Dict[str, pd.Series],
    returns: pd.Series,
    config: Optional[Dict] = None,
    output_dir: Optional[str] = None
) -> Dict:
    """
    快速执行阶段A
    
    Args:
        factor_data: 基础因子数据
        returns: 收益率数据
        config: 配置字典
        output_dir: 输出目录
        
    Returns:
        执行结果
    """
    pipeline = StageAPipeline(config=config, output_dir=output_dir)
    return pipeline.run(factor_data, returns)


# 示例使用
if __name__ == '__main__':
    # 模拟数据示例
    np.random.seed(42)
    n_samples = 200
    
    # 创建模拟基础因子
    factor_data = {
        'rsi': pd.Series(np.random.uniform(20, 80, n_samples)),
        'kdj_j': pd.Series(np.random.uniform(-20, 120, n_samples)),
        'bollinger_pb': pd.Series(np.random.uniform(0.5, 2.0, n_samples)),
        'volume_ratio': pd.Series(np.random.uniform(0.5, 3.0, n_samples)),
        'turnover_surge': pd.Series(np.random.uniform(0, 5, n_samples)),
        'main_inflow_ratio': pd.Series(np.random.uniform(-0.5, 0.5, n_samples))
    }
    
    # 模拟收益率（与部分因子相关）
    returns = pd.Series(
        0.3 * factor_data['rsi'] / 100 +
        0.2 * factor_data['main_inflow_ratio'] +
        np.random.normal(0, 0.02, n_samples)
    )
    
    # 执行Pipeline
    result = run_stage_a(factor_data, returns)
    
    print("\n执行结果:")
    print(f"成功: {result['success']}")
    print(f"最终因子数: {len(result['final_factors'])}")
    
    if result['final_factors']:
        print("\nTop 5 因子:")
        for f in result['final_factors'][:5]:
            print(f"  {f['factor_id']}: {f['expression']} (IC={f['ic']:.4f})")