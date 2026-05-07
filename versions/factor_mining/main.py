"""
因子挖掘系统统一CLI入口

支持单阶段执行和全流程执行

使用方式:
    python main.py --stage A        # 执行阶段A
    python main.py --stage B        # 执行阶段B  
    python main.py --stage C        # 执行阶段C
    python main.py --stage all      # 执行全流程
    python main.py --stage A --quick  # 快速模式验证
"""

import argparse
import json
import os
import sys
import warnings
from datetime import datetime
from typing import Dict, List, Optional, Any

import numpy as np
import pandas as pd

# 添加项目路径
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from config import GlobalConfig, DEFAULT_CONFIG, get_quick_config

# 导入各阶段Pipeline（使用绝对导入兼容直接运行）
try:
    from stage_a.pipeline import StageAPipeline, run_stage_a
    HAS_STAGE_A = True
except ImportError as e:
    HAS_STAGE_A = False
    print(f"[警告] 无法导入阶段A: {e}")

try:
    from stage_b.pipeline import StageBPipeline
    HAS_STAGE_B = True
except ImportError as e:
    HAS_STAGE_B = False
    print(f"[警告] 无法导入阶段B: {e}")

try:
    from stage_c.pipeline import StageCPipeline, run_stage_c
    HAS_STAGE_C = True
except ImportError as e:
    HAS_STAGE_C = False
    print(f"[警告] 无法导入阶段C: {e}")

warnings.filterwarnings('ignore')


class FactorMiningPipeline:
    """
    因子挖掘统一Pipeline
    
    管理各阶段执行流程
    """
    
    def __init__(
        self,
        config: Optional[GlobalConfig] = None,
        output_dir: Optional[str] = None,
        quick_mode: bool = False
    ):
        """
        初始化统一Pipeline
        
        Args:
            config: 全局配置
            output_dir: 输出目录
            quick_mode: 是否快速模式
        """
        self.config = config or DEFAULT_CONFIG
        self.output_dir = output_dir or self.config.output_dir
        self.quick_mode = quick_mode
        
        # 确保输出目录存在
        os.makedirs(self.output_dir, exist_ok=True)
        
        # 各阶段结果
        self.stage_results: Dict[str, Any] = {}
        self.all_factors: List[Dict] = []
        
    def run_stage_a(
        self,
        factor_data: Optional[Dict[str, pd.Series]] = None,
        returns: Optional[pd.Series] = None
    ) -> Dict:
        """
        执行阶段A
        
        Args:
            factor_data: 基础因子数据（可选，未提供时根据配置使用真实或模拟数据）
            returns: 收益率数据（可选）
            
        Returns:
            执行结果
        """
        if not HAS_STAGE_A:
            return {'success': False, 'message': '阶段A模块未导入'}
        
        print("\n" + "=" * 60)
        print("执行阶段A: 因子组合与IC筛选")
        print("=" * 60)
        
        # 获取配置
        config = self.config.get_stage_config('A', self.quick_mode)
        
        # 数据加载逻辑
        use_real = config.get('use_real_data', True)
        
        if factor_data is None:
            if use_real:
                # 使用真实数据
                try:
                    from stage_a.data_loader import RealFactorLoader
                    
                    loader = RealFactorLoader()
                    factor_names = config.get('real_data_factors', [
                        'rsi_6', 'volume_ratio_5', 'kdj_j', 'bollinger_pb', 'turnover_rate'
                    ])
                    target_return = config.get('target_return', 'forward_return_1d')
                    
                    factor_data, returns = loader.prepare_panel_data(
                        factor_names=factor_names,
                        return_type=target_return,
                        align_dates=True,
                        verbose=True
                    )
                    
                    print(f"\n[阶段A] 使用真实数据: {len(factor_data)}因子, {len(returns)}样本")
                    
                    # 保存loader供阶段C使用
                    self._real_loader = loader
                    
                except Exception as e:
                    print(f"[警告] 真实数据加载失败: {e}")
                    print("[回退] 使用模拟数据")
                    factor_data, returns = self._generate_mock_data()
            else:
                # 使用模拟数据
                factor_data, returns = self._generate_mock_data()
                print(f"\n[阶段A] 使用模拟数据: {len(factor_data)}因子, {len(returns)}样本")
        
        # 执行
        pipeline = StageAPipeline(config=config, output_dir=self.output_dir)
        result = pipeline.run(factor_data, returns)
        
        self.stage_results['A'] = result
        
        if result['success']:
            self.all_factors.extend(result['final_factors'])
            print(f"\n阶段A完成，发现 {len(result['final_factors'])} 个因子")
        else:
            print(f"\n阶段A失败: {result['message']}")
        
        return result
    
    def run_stage_b(
        self,
        stock_data: Optional[Dict[str, pd.DataFrame]] = None,
        max_assets: Optional[int] = None
    ) -> Dict:
        """
        执行阶段B
        
        Args:
            stock_data: 股票OHLCV数据（可选）
            max_assets: 最大加载资产数（用于快速测试）
            
        Returns:
            执行结果
        """
        if not HAS_STAGE_B:
            return {'success': False, 'message': '阶段B模块未导入'}
        
        print("\n" + "=" * 60)
        print("执行阶段B: 技术指标挖掘")
        print("=" * 60)
        
        # 显示数据模式
        if self.config.stage_b.use_mock_data:
            print("[配置] 数据模式: 模拟数据")
        else:
            print("[配置] 数据模式: 真实数据")
            if max_assets:
                print(f"[配置] 最大资产数: {max_assets}")
        
        # 获取配置
        config = self.config.get_stage_config('B', self.quick_mode)
        
        # 执行
        pipeline = StageBPipeline(config=config, output_dir=self.output_dir)
        
        # 加载数据
        if stock_data is None:
            stock_data = pipeline.load_ohlcv_data(max_assets=max_assets)
        
        # 生成指标
        indicators_df = pipeline.generate_indicators(stock_data)
        
        # 格式化因子
        factors = pipeline.format_as_factors(indicators_df)
        
        # 计算收益
        returns_df = pipeline.generate_forward_returns(stock_data)
        
        # IC计算
        if pipeline.ic_filter:
            ic_stats = pipeline.calculate_ic(factors, returns_df)
            
            # 筛选
            filtered_factors = {
                k: v for k, v in factors.items()
                if k in ic_stats and abs(ic_stats[k]['ic_mean']) >= config['ic_threshold']
            }
            
            # 去重
            if pipeline.deduplicator and len(filtered_factors) > 1:
                deduplicated, removed, stats = pipeline.deduplicator.deduplicate(
                    filtered_factors,
                    ic_values={k: ic_stats[k]['ic_mean'] for k in filtered_factors}
                )
                filtered_factors = deduplicated
            
            # 构建结果
            final_factors = [
                {
                    'factor_id': f'B_{name}',
                    'expression': name,
                    'stage': 'B',
                    'ic': ic_stats[name]['ic_mean'],
                    'ic_ir': ic_stats[name]['ic_ir'],
                    'create_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                }
                for name in filtered_factors.keys()
            ]
            
            # 按IC排序
            final_factors.sort(key=lambda x: abs(x['ic']), reverse=True)
            
            result = {
                'success': True,
                'message': '执行成功',
                'final_factors': final_factors,
                'stats': {
                    'indicators_generated': len(factors),
                    'ic_filtered': len(filtered_factors),
                    'final': len(final_factors)
                }
            }
        else:
            # 无IC筛选能力
            final_factors = [
                {
                    'factor_id': f'B_{name}',
                    'expression': name,
                    'stage': 'B',
                    'ic': 0,
                    'create_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                }
                for name in factors.keys()
            ]
            
            result = {
                'success': True,
                'message': '执行成功（无IC筛选）',
                'final_factors': final_factors,
                'stats': {
                    'indicators_generated': len(factors),
                    'final': len(final_factors)
                }
            }
        
        self.stage_results['B'] = result
        
        if result['success']:
            self.all_factors.extend(result['final_factors'])
            print(f"\n阶段B完成，发现 {len(result['final_factors'])} 个因子")
        else:
            print(f"\n阶段B失败: {result['message']}")
        
        return result
    
    def run_stage_c(
        self,
        X: Optional[np.ndarray] = None,
        y: Optional[np.ndarray] = None,
        feature_names: Optional[List[str]] = None
    ) -> Dict:
        """
        执行阶段C
        
        Args:
            X: 特征矩阵（可选）
            y: 目标收益（可选）
            feature_names: 特征名称（可选）
            
        Returns:
            执行结果
        """
        if not HAS_STAGE_C:
            return {'success': False, 'message': '阶段C模块未导入'}
        
        print("\n" + "=" * 60)
        print("执行阶段C: 遗传规划因子挖掘")
        print("=" * 60)
        
        # 获取配置
        config_dict = self.config.get_stage_config('C', self.quick_mode)
        
        from stage_c.pipeline import StageCConfig
        
        config = StageCConfig(
            population_size=config_dict['population_size'],
            generations=config_dict['generations'],
            cv_n_splits=config_dict['cv_n_splits'],
            ic_threshold=config_dict['ic_threshold'],
            output_dir=self.output_dir,
            save_intermediate=config_dict['save_intermediate'],
            use_real_data=config_dict.get('use_real_data', True),
            include_derived_factors=config_dict.get('include_derived_factors', True)
        )
        
        # 数据加载逻辑
        use_real = config_dict.get('use_real_data', True)
        
        if X is None:
            if use_real:
                # 使用真实数据构建特征矩阵
                try:
                    from stage_c.feature_builder import FeatureMatrixBuilder
                    
                    # 使用已有的loader或创建新的
                    if hasattr(self, '_real_loader') and self._real_loader:
                        loader = self._real_loader
                    else:
                        from stage_a.data_loader import RealFactorLoader
                        loader = RealFactorLoader()
                    
                    builder = FeatureMatrixBuilder(loader)
                    
                    # 获取阶段A的衍生因子
                    derived_factors = self.stage_results.get('A', {}).get('final_factors', [])
                    if not config_dict.get('include_derived_factors', True):
                        derived_factors = []
                    
                    X, y, feature_names = builder.build_from_real_factors(
                        derived_factors=derived_factors,
                        verbose=True
                    )
                    
                    print(f"\n[阶段C] 使用真实特征矩阵: {X.shape}")
                    
                except Exception as e:
                    print(f"[警告] 真实数据构建失败: {e}")
                    print("[回退] 使用模拟数据")
                    X, y, feature_names = self._generate_mock_evolution_data()
            else:
                # 使用模拟数据
                X, y, feature_names = self._generate_mock_evolution_data()
                print(f"\n[阶段C] 使用模拟数据: {X.shape}")
        
        # 执行
        pipeline = StageCPipeline(config)
        result = pipeline.run(X, y, feature_names)
        
        # 构建结果
        if 'summary' in result:
            final_factors = []
            if len(pipeline.best_factors_) > 0:
                for _, row in pipeline.best_factors_.iterrows():
                    final_factors.append({
                        'factor_id': f'C_{row.get("id", "unknown")}',
                        'expression': row['expression'],
                        'stage': 'C',
                        'ic': row.get('ic', 0),
                        'cv_decay': row.get('cv_decay', None),
                        'create_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                    })
            
            result['final_factors'] = final_factors
            result['success'] = True
        
        self.stage_results['C'] = result
        
        if result.get('success'):
            self.all_factors.extend(result.get('final_factors', []))
            print(f"\n阶段C完成，发现 {len(result.get('final_factors', []))} 个因子")
        else:
            print(f"\n阶段C失败: {result.get('message', '未知错误')}")
        
        return result
    
    def run_all(self, max_assets: Optional[int] = None) -> Dict:
        """
        执行全流程
        
        Args:
            max_assets: 最大加载资产数（用于快速测试）
            
        Returns:
            全流程执行结果
        """
        print("\n" + "=" * 70)
        print("因子挖掘系统 - 全流程执行")
        print("=" * 70)
        print(f"执行时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"快速模式: {self.quick_mode}")
        print(f"输出目录: {self.output_dir}")
        
        # 显示数据模式
        if self.config.stage_b.use_mock_data:
            print("数据模式: 模拟数据")
        else:
            print("数据模式: 真实数据")
            if max_assets:
                print(f"最大资产数: {max_assets}")
        
        # 依次执行各阶段
        results = {}
        
        # 阶段A
        results['A'] = self.run_stage_a()
        
        # 阶段B
        results['B'] = self.run_stage_b(max_assets=max_assets)
        
        # 阶段C - 使用A和B的因子作为特征
        if HAS_STAGE_C:
            # 合合因子数据作为特征
            X, y, feature_names = self._prepare_evolution_input()
            results['C'] = self.run_stage_c(X, y, feature_names)
        
        # 合合结果
        self.stage_results = results
        
        # 输出最终结果
        output_path = self.save_final_factors()
        
        # 打印总结
        self.print_summary()
        
        return {
            'success': True,
            'stage_results': results,
            'all_factors': self.all_factors,
            'output_file': output_path
        }
    
    def save_final_factors(self) -> str:
        """
        保存最终因子到文件
        
        Returns:
            输出文件路径
        """
        output_path = os.path.join(self.output_dir, 'mined_factors.json')
        
        # 按IC排序
        sorted_factors = sorted(self.all_factors, key=lambda x: abs(x.get('ic', 0)), reverse=True)
        
        # 添加去重（跨阶段）
        deduplicated_factors = self._cross_stage_deduplicate(sorted_factors)
        
        output_data = {
            'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'quick_mode': self.quick_mode,
            'total_factors': len(deduplicated_factors),
            'stage_summary': {
                stage: len([f for f in deduplicated_factors if f['stage'] == stage])
                for stage in ['A', 'B', 'C']
            },
            'factors': deduplicated_factors
        }
        
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(output_data, f, ensure_ascii=False, indent=2)
        
        print(f"\n最终因子已保存: {output_path}")
        
        return output_path
    
    def print_summary(self):
        """打印执行总结"""
        print("\n" + "=" * 70)
        print("执行总结")
        print("=" * 70)
        
        for stage, result in self.stage_results.items():
            if result.get('success'):
                stats = result.get('stats', {})
                print(f"\n阶段{stage}:")
                for key, value in stats.items():
                    print(f"  - {key}: {value}")
            else:
                print(f"\n阶段{stage}: 失败 - {result.get('message', '未知')}")
        
        # 最终因子统计
        print(f"\n最终因子总数: {len(self.all_factors)}")
        print(f"  - 阶段A: {len([f for f in self.all_factors if f['stage'] == 'A'])}")
        print(f"  - 阶段B: {len([f for f in self.all_factors if f['stage'] == 'B'])}")
        print(f"  - 阶段C: {len([f for f in self.all_factors if f['stage'] == 'C'])}")
        
        # Top因子
        print("\nTop 10 因子:")
        sorted_factors = sorted(self.all_factors, key=lambda x: abs(x.get('ic', 0)), reverse=True)[:10]
        for i, f in enumerate(sorted_factors, 1):
            print(f"  {i}. [{f['stage']}] {f['expression'][:40]}... IC={f['ic']:.4f}")
        
        print("\n" + "=" * 70)
    
    def _generate_mock_data(
        self,
        n_samples: int = 500
    ) -> tuple:
        """生成模拟数据"""
        n_samples = n_samples if not self.quick_mode else 100
        
        np.random.seed(42)
        
        # 基础因子
        factor_data = {
            'rsi': pd.Series(np.random.uniform(20, 80, n_samples)),
            'kdj_j': pd.Series(np.random.uniform(-20, 120, n_samples)),
            'bollinger_pb': pd.Series(np.random.uniform(0.5, 2.0, n_samples)),
            'volume_ratio': pd.Series(np.random.uniform(0.5, 3.0, n_samples)),
            'turnover_surge': pd.Series(np.random.uniform(0, 5, n_samples)),
            'ma_bias_5': pd.Series(np.random.uniform(-10, 10, n_samples)),
            'price_volatility': pd.Series(np.random.uniform(0.01, 0.1, n_samples))
        }
        
        # 收益率
        returns = pd.Series(np.random.randn(n_samples) * 0.02)
        
        return factor_data, returns
    
    def _generate_mock_evolution_data(
        self,
        n_samples: int = 500,
        n_features: int = 10
    ) -> tuple:
        """生成遗传规划模拟数据"""
        n_samples = n_samples if not self.quick_mode else 100
        
        np.random.seed(42)
        
        X = np.random.randn(n_samples, n_features)
        y = np.random.randn(n_samples) * 0.02
        
        feature_names = [f'factor_{i}' for i in range(n_features)]
        
        return X, y, feature_names
    
    def _prepare_evolution_input(self) -> tuple:
        """准备遗传规划输入数据"""
        # 检查是否使用真实数据模式
        if not self.config.use_mock_data:
            try:
                from stage_c.feature_builder import FeatureMatrixBuilder
                from stage_a.data_loader import RealFactorLoader
                
                loader = RealFactorLoader()
                builder = FeatureMatrixBuilder(loader)
                
                # 获取阶段A和B的衍生因子
                derived_factors = self.stage_results.get('A', {}).get('final_factors', [])
                derived_factors.extend(self.stage_results.get('B', {}).get('final_factors', []))
                
                X, y, feature_names = builder.build_from_real_factors(
                    derived_factors=derived_factors[:10],  # 限制数量避免OOM
                    verbose=True
                )
                
                print(f"[阶段C] 使用真实特征矩阵: {X.shape}")
                return X, y, feature_names
                
            except Exception as e:
                print(f"[警告] 真实数据构建失败: {e}")
                print("[回退] 使用模拟数据")
        
        # 模拟数据模式或回退
        return self._generate_mock_evolution_data()
    
    def _cross_stage_deduplicate(
        self,
        factors: List[Dict],
        correlation_threshold: float = 0.7
    ) -> List[Dict]:
        """跨阶段去重"""
        # 简化处理：只保留各阶段Top因子
        stage_top = {}
        
        for f in factors:
            stage = f['stage']
            if stage not in stage_top:
                stage_top[stage] = []
            stage_top[stage].append(f)
        
        # 各阶段保留前20个
        result = []
        for stage, stage_factors in stage_top.items():
            result.extend(stage_factors[:20])
        
        return result


def main():
    """主函数"""
    parser = argparse.ArgumentParser(
        description='因子挖掘系统统一入口',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python main.py --stage A           执行阶段A
  python main.py --stage B           执行阶段B
  python main.py --stage C           执行阶段C
  python main.py --stage all         执行全流程
  python main.py --stage all --quick 快速模式验证
        """
    )
    
    parser.add_argument(
        '--stage',
        type=str,
        required=True,
        choices=['A', 'B', 'C', 'all'],
        help='执行阶段: A/B/C/all'
    )
    
    parser.add_argument(
        '--quick',
        action='store_true',
        help='快速模式（小数据量验证）'
    )
    
    parser.add_argument(
        '--output',
        type=str,
        default='./output',
        help='输出目录'
    )
    
    parser.add_argument(
        '--config',
        type=str,
        default=None,
        help='配置文件路径'
    )
    
    parser.add_argument(
        '--real-data',
        action='store_true',
        help='使用真实数据（从cache/factor_data加载）'
    )
    
    parser.add_argument(
        '--mock-data',
        action='store_true',
        help='使用模拟数据（测试用）'
    )
    
    parser.add_argument(
        '--max-assets',
        type=int,
        default=None,
        help='最大加载资产数（用于快速测试真实数据）'
    )
    
    args = parser.parse_args()
    
    # 加载配置
    config = get_quick_config() if args.quick else DEFAULT_CONFIG
    if args.config:
        from config import load_config
        config = load_config(args.config)
    
    # 处理数据源参数
    if args.real_data and args.mock_data:
        print("[警告] --real-data 和 --mock-data 同时指定，使用真实数据")
    if args.real_data:
        # 真实数据模式
        config.use_mock_data = False
        config.stage_a.use_real_data = True
        config.stage_b.use_mock_data = False
        config.stage_c.use_real_data = True
    elif args.mock_data:
        # 模拟数据模式
        config.use_mock_data = True
        config.stage_a.use_real_data = False
        config.stage_b.use_mock_data = True
        config.stage_c.use_real_data = False
    
    # 创建Pipeline
    pipeline = FactorMiningPipeline(
        config=config,
        output_dir=args.output,
        quick_mode=args.quick
    )
    
    # 执行
    if args.stage == 'all':
        result = pipeline.run_all(max_assets=args.max_assets)
    elif args.stage == 'A':
        result = pipeline.run_stage_a()
        pipeline.save_final_factors()
    elif args.stage == 'B':
        result = pipeline.run_stage_b(max_assets=args.max_assets)
        pipeline.save_final_factors()
    elif args.stage == 'C':
        result = pipeline.run_stage_c()
        pipeline.save_final_factors()
    
    # 返回状态
    if result.get('success'):
        print("\n✅ 执行成功")
        sys.exit(0)
    else:
        print("\n❌ 执行失败")
        sys.exit(1)


if __name__ == '__main__':
    main()