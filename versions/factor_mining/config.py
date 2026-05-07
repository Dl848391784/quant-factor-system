"""
因子挖掘系统全局配置

定义各阶段的阈值参数、并行参数等配置项
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional
import os


@dataclass
class StageAConfig:
    """阶段A配置 - 因子组合与IC筛选"""
    
    # IC筛选参数
    ic_threshold: float = 0.03  # IC绝对值阈值
    ir_threshold: float = 0.5   # IR阈值
    tstat_threshold: float = 2.0  # t统计量阈值
    
    # 去重参数
    correlation_threshold: float = 0.8  # 相关性阈值
    keep_strategy: str = 'highest_ic'  # 去重保留策略
    
    # 组合参数
    max_combination_depth: int = 2  # 最大组合深度
    include_unary: bool = True  # 是否包含单目运算
    include_nested: bool = True  # 是否包含嵌套组合
    max_combinations: int = 500  # 最大组合数量
    
    # 数据参数
    min_records: int = 100  # 最小有效记录数
    
    # 真实数据参数（新增）
    use_real_data: bool = True  # 默认使用真实数据
    real_data_factors: List[str] = field(default_factory=lambda: [
        'rsi_6', 'volume_ratio_5', 'kdj_j', 'bollinger_pb', 'turnover_rate'
    ])
    target_return: str = 'forward_return_1d'  # 目标收益率类型
    
    # 输出参数
    verbose: bool = True


@dataclass
class StageBConfig:
    """阶段B配置 - 技术指标挖掘"""
    
    # 数据参数
    use_mock_data: bool = False  # 默认使用真实数据
    n_days: int = 500
    n_stocks: int = 100
    start_date: str = '2024-01-01'
    
    # 指标类别
    categories: List[str] = field(default_factory=lambda: [
        'trend', 'volatility', 'momentum', 'volume'
    ])
    
    # IC筛选参数
    ic_threshold: float = 0.03
    ir_threshold: float = 0.5
    tstat_threshold: float = 2.0
    correlation_threshold: float = 0.8
    
    # 数据参数
    min_records: int = 100
    keep_strategy: str = 'highest_ic'
    
    # 输出参数
    verbose: bool = True


@dataclass
class StageCConfig:
    """阶段C配置 - 遗传规划因子挖掘"""
    
    # 遗传规划参数
    population_size: int = 1000  # 种群大小
    generations: int = 20  # 迭代代数
    tournament_size: int = 20  # 锦标赛大小
    stopping_criteria: float = 0.05  # 停止准则
    random_state: int = 42  # 随机种子
    n_jobs: int = 1  # 并行数（1=单线程，避免OOM）
    
    # 交叉验证参数
    cv_n_splits: int = 5  # CV折数
    cv_decay_threshold: float = 0.03  # IC衰减阈值
    cv_min_test_ic: float = 0.02  # 最小测试集IC
    
    # IC筛选参数
    ic_threshold: float = 0.03
    ic_ir_threshold: float = 0.5
    
    # 真实数据参数（新增）
    use_real_data: bool = True  # 默认使用真实数据
    include_derived_factors: bool = True  # 是否包含阶段A的衍生因子
    
    # 输出参数
    output_top_n: int = 20  # 输出前N个因子
    save_intermediate: bool = True  # 保存中间结果
    
    # 早停参数
    early_stop_generations: int = 5
    early_stop_threshold: float = 0.001


@dataclass
class QuickModeConfig:
    """快速模式配置 - 用于小数据量验证"""
    
    # 阶段A快速参数
    stage_a_max_combinations: int = 50
    
    # 阶段B快速参数
    stage_b_n_days: int = 100
    stage_b_n_stocks: int = 20
    
    # 阶段C快速参数
    stage_c_population_size: int = 100
    stage_c_generations: int = 5
    stage_c_cv_n_splits: int = 3


@dataclass
class GlobalConfig:
    """
    全局配置
    
    包含所有阶段配置和运行参数
    """
    
    # 各阶段配置
    stage_a: StageAConfig = field(default_factory=StageAConfig)
    stage_b: StageBConfig = field(default_factory=StageBConfig)
    stage_c: StageCConfig = field(default_factory=StageCConfig)
    
    # 快速模式配置
    quick_mode: QuickModeConfig = field(default_factory=QuickModeConfig)
    
    # 全局参数
    output_dir: str = './output'  # 输出目录
    log_level: str = 'INFO'  # 日志级别
    
    # 数据模式
    use_mock_data: bool = False  # 默认使用真实数据
    
    # 并行参数
    parallel_enabled: bool = True
    max_workers: int = 4
    
    # 数据源配置
    data_source: str = 'mock'  # mock / cache / api
    
    def get_stage_config(self, stage: str, quick: bool = False) -> Dict:
        """
        获取指定阶段的配置
        
        Args:
            stage: 阶段名称 (A/B/C)
            quick: 是否使用快速模式
            
        Returns:
            配置字典
        """
        stage_lower = stage.lower()
        
        if stage_lower == 'a':
            base_config = self.stage_a
            quick_overrides = {
                'max_combinations': self.quick_mode.stage_a_max_combinations,
                'verbose': True
            }
        elif stage_lower == 'b':
            base_config = self.stage_b
            quick_overrides = {
                'n_days': self.quick_mode.stage_b_n_days,
                'n_stocks': self.quick_mode.stage_b_n_stocks,
                'use_mock_data': True,
                'verbose': True
            }
        elif stage_lower == 'c':
            base_config = self.stage_c
            quick_overrides = {
                'population_size': self.quick_mode.stage_c_population_size,
                'generations': self.quick_mode.stage_c_generations,
                'cv_n_splits': self.quick_mode.stage_c_cv_n_splits,
                'save_intermediate': False
            }
        else:
            raise ValueError(f"未知阶段: {stage}")
        
        # 基础配置转字典
        config_dict = {
            k: v for k, v in base_config.__dict__.items()
            if not k.startswith('_')
        }
        
        # 快速模式覆盖
        if quick:
            config_dict.update(quick_overrides)
        
        return config_dict
    
    def get_output_path(self, filename: str) -> str:
        """
        获取输出文件完整路径
        
        Args:
            filename: 文件名
            
        Returns:
            完整路径
        """
        os.makedirs(self.output_dir, exist_ok=True)
        return os.path.join(self.output_dir, filename)


# 默认配置实例
DEFAULT_CONFIG = GlobalConfig()


def load_config(config_path: Optional[str] = None) -> GlobalConfig:
    """
    加载配置
    
    Args:
        config_path: 配置文件路径（可选）
        
    Returns:
        GlobalConfig实例
    """
    if config_path is None:
        return DEFAULT_CONFIG
    
    # TODO: 支持从配置文件加载
    # 目前返回默认配置
    return DEFAULT_CONFIG


def get_quick_config() -> GlobalConfig:
    """
    获取快速模式配置
    
    Returns:
        快速模式配置实例
    """
    config = GlobalConfig()
    
    # 应用快速模式参数
    config.stage_a.max_combinations = config.quick_mode.stage_a_max_combinations
    config.stage_b.n_days = config.quick_mode.stage_b_n_days
    config.stage_b.n_stocks = config.quick_mode.stage_b_n_stocks
    config.stage_c.population_size = config.quick_mode.stage_c_population_size
    config.stage_c.generations = config.quick_mode.stage_c_generations
    
    return config