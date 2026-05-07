#!/usr/bin/env python3
"""
多因子打分选股引擎
作者: 云舟 🛠️
功能: 整合多个因子数据，计算综合得分，选出 Top N 股票

因子列表:
- RSI(14) - 正向因子（IC=+0.0394）
- KDJ_J - 正向因子（IC=+0.0214）
- 布林带%B - 正向因子（IC=+0.0407）
- 量比 - 正向因子
- 换手率突增 - 反向因子（IC=-0.0492）
- 3日涨幅 - 正向因子

v3.0 新增：智能权重生成功能
- 根据因子IC/ICIR/多空收益自动计算最优权重
- 智能模式 + 手动模式切换
"""

import json
import gzip
import os
import pandas as pd
import numpy as np
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
import gc
import logging

# 配置日志
logging.basicConfig(level=logging.INFO, format='[打分引擎] %(message)s')
logger = logging.getLogger(__name__)


ROOT_DIR = Path(__file__).parent.parent  # 指向 factor_ic_analyzer/
CACHE_DIR = ROOT_DIR / 'cache/factor_data'  # 指向 factor_ic_analyzer/cache/factor_data


# ==================== 智能权重生成器 ====================

class SmartWeightGenerator:
    """
    智能权重生成器
    
    根据因子的IC、ICIR、多空收益自动计算最优权重配置
    
    算法：
    - ICIR 权重：50%（最重要）
    - IC均值权重：30%
    - 多空收益权重：20%
    
    约束条件：
    - 每因子权重范围：5% ~ 35%
    - 所有因子权重合计：100%
    """
    
    # 因子分析结果文件映射
    FACTOR_RESULT_FILES = {
        'rsi': 'factor_analysis_result.json',
        'kdj_j': 'kdj_j_analysis_result.json',
        'bollinger_pb': 'bollinger_pb_analysis_result.json',
        'volume_ratio': 'volume_ratio_analysis_result.json',
        'turnover_surge': 'turnover_surge_analysis_result.json',
        'return_3d': 'return_3d_analysis_result.json'
    }
    
    # 因子名称映射
    FACTOR_NAMES = {
        'rsi': 'RSI(14)',
        'kdj_j': 'KDJ_J',
        'bollinger_pb': '布林带%B',
        'volume_ratio': '量比',
        'turnover_surge': '换手率突增',
        'return_3d': '3日涨幅'
    }
    
    def __init__(self):
        """初始化并加载所有因子分析结果"""
        self.ic_data = self._load_all_ic_data()
        self.layered_data = self._load_all_layered_data()
    
    def _load_all_ic_data(self) -> Dict:
        """加载所有因子的IC/ICIR数据"""
        result = {}
        
        for factor_id, filename in self.FACTOR_RESULT_FILES.items():
            filepath = ROOT_DIR / filename
            if filepath.exists():
                try:
                    with open(filepath, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                    
                    ic_metrics = data.get('ic_metrics', {})
                    result[factor_id] = {
                        'ic_mean': ic_metrics.get('ic_mean', 0),
                        'ic_std': ic_metrics.get('ic_std', 0),
                        'icir': ic_metrics.get('icir', 0),
                        't_stat': ic_metrics.get('t_stat', 0),
                        'p_value': ic_metrics.get('p_value', 0),
                        'significance': ic_metrics.get('significance', ''),
                        'positive_ratio': ic_metrics.get('positive_ratio', 0),
                        'n_days': ic_metrics.get('n_days', 0),
                        'n_assets': ic_metrics.get('n_assets', 0)
                    }
                except Exception as e:
                    print(f"[智能权重] 加载 {factor_id} IC数据失败: {e}")
        
        return result
    
    def _load_all_layered_data(self) -> Dict:
        """加载所有因子的分层回测数据（多空收益）"""
        result = {}
        
        for factor_id, filename in self.FACTOR_RESULT_FILES.items():
            filepath = ROOT_DIR / filename
            if filepath.exists():
                try:
                    with open(filepath, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                    
                    layered_result = data.get('layered_result', {})
                    summary = layered_result.get('summary', {})
                    
                    result[factor_id] = {
                        'long_short_return': summary.get('long_short_annual_return', 0),
                        'long_short_sharpe': summary.get('long_short_sharpe', 0),
                        'max_drawdown': summary.get('long_short_max_drawdown', 0),
                        'monotonicity_passed': summary.get('monotonicity_passed', False)
                    }
                except Exception as e:
                    print(f"[智能权重] 加载 {factor_id} 分层数据失败: {e}")
        
        return result
    
    def calculate_smart_weights(
        self,
        icir_weight: float = 0.5,
        ic_mean_weight: float = 0.3,
        long_short_weight: float = 0.2
    ) -> Tuple[Dict, Dict, Dict]:
        """
        计算智能权重
        
        Args:
            icir_weight: ICIR权重（默认50%，最重要）
            ic_mean_weight: IC均值权重（默认30%）
            long_short_weight: 多空收益权重（默认20%）
            
        Returns:
            tuple: (weights_dict, quality_scores_dict, factor_quality_dict)
        """
        if not self.ic_data:
            # 无数据时返回默认权重
            default_weights = {
                'rsi': 17, 'kdj_j': 14, 'bollinger_pb': 17,
                'volume_ratio': 14, 'turnover_surge': 14, 'return_3d': 12
            }
            return default_weights, {}, {}
        
        raw_scores = {}
        factor_quality = {}
        
        for factor_id, data in self.ic_data.items():
            layered = self.layered_data.get(factor_id, {})
            
            # 1. ICIR评分（归一化到0-1，0.2为优秀阈值）
            icir = abs(data.get('icir', 0))
            icir_score = min(icir / 0.2, 1) * icir_weight
            
            # 2. IC均值评分（归一化到0-1，0.05为优秀阈值）
            ic_mean = abs(data.get('ic_mean', 0))
            ic_score = min(ic_mean / 0.05, 1) * ic_mean_weight
            
            # 3. 多空收益评分（归一化到0-1，0.1为优秀阈值）
            long_short = abs(layered.get('long_short_return', 0))
            ls_score = min(long_short / 0.1, 1) * long_short_weight
            
            # 综合评分
            total_score = icir_score + ic_score + ls_score
            raw_scores[factor_id] = total_score
            
            # 记录因子质量详情
            factor_quality[factor_id] = {
                'factor_id': factor_id,
                'factor_name': self.FACTOR_NAMES.get(factor_id, factor_id),
                'ic_mean': data.get('ic_mean', 0),
                'icir': data.get('icir', 0),
                't_stat': data.get('t_stat', 0),
                'significance': data.get('significance', ''),
                'long_short_return': layered.get('long_short_return', 0),
                'quality_level': self._get_quality_level_by_score(total_score),  # v3.1: 使用综合评分评级
                'quality_score': total_score,
                'score_components': {
                    'icir_score': round(icir_score, 4),
                    'ic_score': round(ic_score, 4),
                    'ls_score': round(ls_score, 4)
                }
            }
        
        # 归一化权重（总和100%）
        total = sum(raw_scores.values())
        if total == 0:
            # 所有因子评分为0时，使用均等权重
            weights = {f: 100 / len(raw_scores) for f in raw_scores}
        else:
            weights = {f: round(s / total * 100, 1) for f, s in raw_scores.items()}
        
        # 应用约束条件
        weights = self._apply_constraints(weights)
        
        return weights, raw_scores, factor_quality
    
    def _apply_constraints(self, weights: Dict) -> Dict:
        """
        应用权重约束条件
        
        约束：
        - 每因子权重 >= 5%
        - 每因子权重 <= 35%
        - 权重总和 = 100%
        """
        # 确保每个因子至少5%
        for f in weights:
            if weights[f] < 5:
                weights[f] = 5.0
        
        # 确保单因子不超过35%
        for f in weights:
            if weights[f] > 35:
                weights[f] = 35.0
        
        # 重新归一化
        total = sum(weights.values())
        if total > 0:
            weights = {f: round(w / total * 100, 1) for f, w in weights.items()}
        
        return weights
    
    def _get_quality_level(self, icir: float) -> str:
        """
        根据ICIR判断因子质量等级（旧版，仅基于ICIR）
        
        等级标准：
        - 优秀: ICIR > 0.5
        - 良好: 0.2 ~ 0.5
        - 中等: 0.1 ~ 0.2
        - 较弱: < 0.1
        
        v3.1 修复：此方法已废弃，建议使用 _get_quality_level_by_score()
        """
        if icir > 0.5:
            return '优秀'
        elif icir > 0.2:
            return '良好'
        elif icir > 0.1:
            return '中等'
        else:
            return '较弱'
    
    def _get_quality_level_by_score(self, score: float) -> str:
        """
        根据综合评分判断因子质量等级
        
        等级标准（基于综合评分）：
        - 优秀: score > 0.85
        - 良好: score > 0.70
        - 中等: score > 0.50
        - 较弱: score <= 0.50
        
        Args:
            score: 综合评分（icir_score + ic_score + ls_score，范围0-1）
            
        Returns:
            质量等级字符串
        """
        if score > 0.85:
            return '优秀'
        elif score > 0.70:
            return '良好'
        elif score > 0.50:
            return '中等'
        else:
            return '较弱'
    
    def get_smart_weights_report(self) -> Dict:
        """
        生成智能权重完整报告
        
        Returns:
            dict: 包含权重、质量评分、配置信息的完整报告
        """
        weights, raw_scores, factor_quality = self.calculate_smart_weights()
        
        # 构建权重来源说明
        weight_explanation = {
            'algorithm': 'icir_weighted',
            'description': '权重基于ICIR(50%) + IC均值(30%) + 多空收益(20%)综合计算',
            'config': {
                'icir_weight': 0.5,
                'ic_mean_weight': 0.3,
                'long_short_weight': 0.2
            },
            'constraints': {
                'min_weight': 5.0,
                'max_weight': 35.0,
                'total_weight': 100.0
            }
        }
        
        return {
            'weights': weights,
            'quality_scores': raw_scores,
            'factor_quality': factor_quality,
            'weight_explanation': weight_explanation,
            'generated_at': datetime.now().isoformat(),
            'factors_available': list(self.ic_data.keys())
        }
    
    def optimize_weights(
        self,
        objective: str = 'balanced'
    ) -> Dict:
        """
        权重优化（高级功能）
        
        Args:
            objective: 优化目标
                - 'icir': 最大化ICIR
                - 'long_short': 最大化多空收益
                - 'balanced': 平衡ICIR和多空收益
                
        Returns:
            dict: 优化后的权重配置
        """
        try:
            from scipy.optimize import minimize
            
            factors = list(self.ic_data.keys())
            
            def objective_function(w):
                # 计算加权ICIR
                weighted_icir = sum(
                    w[i] * abs(self.ic_data[f].get('icir', 0))
                    for i, f in enumerate(factors)
                )
                
                # 计算加权多空收益
                weighted_ls = sum(
                    w[i] * abs(self.layered_data.get(f, {}).get('long_short_return', 0))
                    for i, f in enumerate(factors)
                )
                
                if objective == 'icir':
                    return -weighted_icir
                elif objective == 'long_short':
                    return -weighted_ls
                else:  # balanced
                    return -(weighted_icir * 0.6 + weighted_ls * 0.4)
            
            # 约束条件
            constraints = [
                {'type': 'eq', 'fun': lambda w: sum(w) - 1}
            ]
            bounds = [(0.05, 0.35) for _ in factors]
            
            # 初始值（均等权重）
            x0 = [1 / len(factors)] * len(factors)
            
            result = minimize(
                objective_function, x0,
                method='SLSQP',
                bounds=bounds,
                constraints=constraints
            )
            
            if result.success:
                optimized_weights = {
                    f: round(w * 100, 1)
                    for f, w in zip(factors, result.x)
                }
                return {
                    'success': True,
                    'weights': optimized_weights,
                    'objective': objective,
                    'message': f'{objective}优化完成'
                }
            else:
                return {
                    'success': False,
                    'error': result.message,
                    'weights': self.calculate_smart_weights()[0]
                }
                
        except ImportError:
            # scipy未安装，返回默认智能权重
            return {
                'success': False,
                'error': 'scipy未安装，无法执行优化',
                'weights': self.calculate_smart_weights()[0]
            }


# 创建全局智能权重生成器实例
_smart_weight_generator = None

def get_smart_weight_generator() -> SmartWeightGenerator:
    """获取智能权重生成器单例"""
    global _smart_weight_generator
    if _smart_weight_generator is None:
        _smart_weight_generator = SmartWeightGenerator()
    return _smart_weight_generator


# ========== v3.10 引擎数据共享优化（云柏方案） ==========

class SharedFactorDataCache:
    """
    共享因子数据缓存（跨周期共享基础因子数据）
    
    v1 Revision 3 核心改进（云柏方案）：
    - 新增线程锁保护（避免并行竞态条件）
    - 废弃 _shared_data 缓存（统一到 _complete_factor_data）
    - 使用静态方法加载（避免临时对象内存泄漏）
    - 内存峰值：~700MB（降幅85%）
    
    使用方式：
    1. SharedFactorDataCache.preload_complete_factor_data()  # 预加载完整因子数据
    2. WeightOptimizer(use_shared_cache=True)  # 使用共享缓存
    """
    
    # ========== 新增线程锁（v1 Revision 3） ==========
    import threading
    _lock = threading.Lock()  # 线程锁，保护并行加载
    
    # ========== 废弃的旧缓存系统（v1 Revision 3） ==========
    # _shared_data = None  # 已废弃：统一到 _complete_factor_data
    # _loaded = False      # 已废弃：统一到 _complete_factor_loaded
    # _instance = None     # 已废弃：不再使用临时引擎实例
    _shared_data = None  # 保留变量以兼容旧代码，但不再使用
    _loaded = False      # 保留标志以兼容旧代码，但不再使用
    _instance = None     # 保留引用以兼容旧代码，但不再使用
    
    @classmethod
    def preload_shared_data(cls, max_days: int = 150):
        """预加载共享因子数据
        
        Args:
            max_days: 最大加载天数（默认150天）
            
        Returns:
            Dict: 共享因子数据字典
        """
        if cls._loaded:
            logger.info("[共享缓存] 数据已加载，跳过")
            return cls._shared_data
        
        logger.info("[共享缓存] 开始预加载共享因子数据（max_days=%d）..." % max_days)
        
        # 创建临时引擎实例（用于复用加载逻辑）
        cls._instance = ScoringEngine(return_col='forward_return_1d', use_shared_cache=False)
        cls._instance._load_all_data(max_days=max_days)
        
        # 提取共享因子数据（排除周期收益数据）
        cls._shared_data = {
            'factor_df': cls._instance.factor_df,
            'turnover_df': cls._instance.turnover_df,
            'kdj_df': cls._instance.kdj_df,
            'bollinger_df': cls._instance.bollinger_df,
            'stock_info': cls._instance.stock_info,
            'available_dates': cls._instance.available_dates
        }
        
        cls._loaded = True
        logger.info("[共享缓存] 共享因子数据预加载完成（内存约500MB）")
        logger.info("[共享缓存] available_dates: %d 天" % len(cls._shared_data['available_dates']))
        
        return cls._shared_data
    
    @classmethod
    def get_shared_data(cls):
        """获取共享因子数据
        
        v3 bugfix（云柏修复 2026-05-01）：
        - 返回 _complete_factor_data（统一缓存系统）
        - 兼容旧字段名：factor_df → factor_df_complete
        - turnover_df/kdj_df/bollinger_df/stock_info 设为 None（已合并到 factor_df_complete）
        """
        if not cls._complete_factor_loaded:
            cls.preload_complete_factor_data()
        
        # 构建兼容旧接口的返回结构
        return {
            'factor_df': cls._complete_factor_data.get('factor_df_complete'),
            'turnover_df': None,  # 新系统不单独存储，已合并到 factor_df_complete
            'kdj_df': None,       # 已合并到 factor_df_complete
            'bollinger_df': None, # 已合并到 factor_df_complete
            'stock_info': None,   # 新系统不单独存储
            'available_dates': cls._complete_factor_data.get('available_dates', [])
        }
    
    @classmethod
    def is_loaded(cls):
        """检查是否已加载
        
        v3 bugfix（云柏修复 2026-05-01）：
        - 只检查 _complete_factor_loaded（统一缓存系统）
        - 废弃旧缓存系统 _loaded
        """
        return cls._complete_factor_loaded
    
    # ========== v1 Revision 2 新增方法（云柏方案） ==========
    # 完整因子数据缓存（用于 IC 计算，避免并行重复加载）
    _complete_factor_data = None  # 完整因子DataFrame
    _complete_factor_loaded = False  # 完整因子数据加载标志
    
    @classmethod
    def preload_complete_factor_data(cls, max_days: int = 150):
        """预加载完整因子数据（用于 IC 计算，线程安全）
        
        v1 Revision 3 核心改进（云柏方案）：
        - 使用线程锁保护（避免竞态条件）
        - 使用静态方法加载（避免临时对象内存泄漏）
        - 跨周期共享（T+1/T+3/T+5 共用）
        - 内存占用约700MB（一次性加载）
        
        Args:
            max_days: 最大加载天数（默认 150）
            
        Returns:
            Dict: 包含完整因子DataFrame的字典
        """
        # ========== v1 Revision 3 线程锁保护 ==========
        with cls._lock:  # 线程锁：确保并行时只加载一次
            if cls._complete_factor_loaded:
                logger.info("[共享缓存] 完整因子数据已加载，跳过")
                return cls._complete_factor_data
            
            logger.info("[共享缓存] 开始预加载完整因子数据（max_days=%d）..." % max_days)
            
            # ========== v1 Revision 3 静态方法加载（避免临时对象） ==========
            # 不再创建 temp_optimizer，直接使用静态方法
            merged_df = cls._load_factor_data_complete_static(max_days=max_days)
            
            # 缓存完整因子数据
            cls._complete_factor_data = {
                'factor_df_complete': merged_df,  # 核心改进：缓存完整因子DataFrame
                'available_dates': sorted(merged_df['date'].unique()) if not merged_df.empty else [],
                'factor_columns': {
                    'rsi': 'rsi_6',
                    'bollinger_pb': 'bollinger_pb',
                    'volume_ratio': 'volume_ratio_5',
                    'turnover_surge': 'turnover_surge',
                    'return_3d': 'return_3d'
                }
            }
            
            cls._complete_factor_loaded = True
            logger.info("[共享缓存] 完整因子数据预加载完成：%d 条，内存约700MB" % len(merged_df))
            
            return cls._complete_factor_data
    
    @classmethod
    def get_complete_factor_data(cls):
        """获取完整因子DataFrame
        
        v1 Revision 2 新增方法（云柏方案）：
        
        P0-R4-02 修复（云舟 2026-05-02）：
        - 添加空值保护，避免缓存未初始化时崩溃
        
        Returns:
            pd.DataFrame: 包含所有因子字段的完整数据
        """
        if not cls._complete_factor_loaded:
            cls.preload_complete_factor_data()
        
        # P0-R4-02: 缓存空值保护
        if cls._complete_factor_data is None:
            logger.warning("[缓存] _complete_factor_data 为 None，返回空 DataFrame")
            return pd.DataFrame()
        
        return cls._complete_factor_data.get('factor_df_complete', pd.DataFrame())
    
    @classmethod
    def get_available_dates_complete(cls):
        """获取完整因子数据的可用日期列表
        
        v1 Revision 2 新增方法（云柏方案）：
        
        Returns:
            List[str]: 可用日期列表
        """
        if not cls._complete_factor_loaded:
            cls.preload_complete_factor_data()
        
        return cls._complete_factor_data['available_dates']
    
    @classmethod
    def is_complete_factor_loaded(cls):
        """检查完整因子数据是否已加载
        
        v1 Revision 2 新增方法（云柏方案）：
        
        Returns:
            bool: 是否已加载
        """
        return cls._complete_factor_loaded
    
    @classmethod
    def validate_cache(cls):
        """验证缓存数据完整性
        
        v3 bugfix（云柏修复 2026-05-01）：
        - 检查缓存加载状态
        - 检查数据完整性
        - 检查必需字段存在
        
        Returns:
            Tuple[bool, str]: (是否有效, 错误信息)
        """
        if not cls._complete_factor_loaded:
            return False, "缓存未加载（_complete_factor_loaded=False）"
        
        data = cls._complete_factor_data
        if data is None:
            return False, "缓存数据为 None（_complete_factor_data=None）"
        
        factor_df = data.get('factor_df_complete')
        if factor_df is None or factor_df.empty:
            return False, "factor_df_complete 为空或 None"
        
        required_columns = ['date', 'asset']
        missing = [col for col in required_columns if col not in factor_df.columns]
        if missing:
            return False, f"factor_df_complete 缺少必需字段: {missing}"
        
        available_dates = data.get('available_dates')
        if not available_dates:
            return False, "available_dates 为空或 None"
        
        return True, "缓存数据有效"
    
    # ========== 修复9：添加 clear_cache 方法（云柏方案） ==========
    @classmethod
    def clear_cache(cls):
        """安全清理缓存（线程安全）
        
        v1 Revision 3 新增方法（云柏方案）：
        - 使用线程锁保护
        - 统一清理所有缓存变量
        - 防止内存泄漏
        
        Returns:
            bool: 清理是否成功
        """
        with cls._lock:
            cls._complete_factor_data = None
            cls._complete_factor_loaded = False
            # 清理废弃的旧缓存（兼容性）
            cls._shared_data = None
            cls._loaded = False
            logger.info("[共享缓存] 缓存已清理")
        return True
    
    @staticmethod
    def _load_factor_data_complete_static(max_days: int = 150) -> pd.DataFrame:
        """独立加载完整因子数据（静态方法，无对象引用）
        
        v3.15 合并数据加载优化（云舟实施 2026-04-30）：
        - 优先从合并数据文件加载（versions/v3/cache/factor_data_merged.json.gz）
        - 合并文件包含 kdj_j 和 return_3d 字段
        - 如果合并文件不存在，回退到原有的多文件加载逻辑
        
        v1 Revision 3 核心改进（云柏方案）：
        - 静态方法实现，不创建临时对象
        - 返回 DataFrame 后立即释放所有中间变量
        - 内存优化：避免 temp_optimizer 对象引用泄漏（~700MB）
        
        Args:
            max_days: 最大加载天数（默认 150）
            
        Returns:
            pd.DataFrame: 包含所有因子字段的完整数据
        """
        import gzip
        import gc
        import pandas as pd
        import numpy as np
        from pathlib import Path
        import json
        
        from common.cache_paths import DATA_CACHE_DIR, ROOT_DIR, VERSIONS_DIR
        
        # ========== v3.16 V2/V3隔离修复（云瑶决策 2026-05-05） ==========
        # V2优化器使用V2完整缓存（含14新因子+原有因子+收益字段）
        # V3优化器继续使用V3合并缓存
        # 优先检查V2完整缓存（factor_data_v2_complete.json.gz）
        v2_complete_filepath = VERSIONS_DIR / 'v2' / 'cache' / 'factor_data_v2_complete.json.gz'
        v3_merged_filepath = VERSIONS_DIR / 'v3' / 'cache' / 'factor_data_merged.json.gz'
        
        # 选择缓存源（V2完整缓存优先）
        if v2_complete_filepath.exists():
            merged_filepath = v2_complete_filepath
            logger.info("[静态加载] 使用V2完整缓存（含14新因子）：%s" % merged_filepath)
        elif v3_merged_filepath.exists():
            merged_filepath = v3_merged_filepath
            logger.info("[静态加载] 使用V3合并缓存：%s" % merged_filepath)
        else:
            merged_filepath = None
        
        if merged_filepath.exists():
            logger.info("[静态加载] 从合并数据文件加载：%s" % merged_filepath)
            
            with gzip.open(merged_filepath, 'rt', encoding='utf-8') as f:
                merged_data = json.load(f).get('data', [])
            merged_df = pd.DataFrame(merged_data)
            logger.info("[静态加载] 合并数据：%d 条，字段：%s" % (len(merged_df), list(merged_df.columns)))
            
            # 确保因子字段存在
            # 合并文件字段：date, asset, open, close, high, low, rsi_6, volume_ratio_5, kdj_j, forward_return_3d, return_3d
            
            # 立即释放中间变量
            del merged_data
            gc.collect()
            
            # ========== 天数筛选 ==========
            if max_days > 0 and not merged_df.empty:
                all_dates = sorted(merged_df['date'].unique())
                if len(all_dates) > max_days:
                    recent_dates = set(all_dates[-max_days:])
                    merged_df = merged_df[merged_df['date'].isin(recent_dates)]
                    logger.info("[静态加载] 数据筛选：%d 天 → %d 天" % (len(all_dates), max_days))
            
            logger.info("[静态加载] 最终数据：%d 条" % len(merged_df))
            return merged_df
        
        # ========== 回退：从多个文件加载（原有逻辑） ==========  
        # ========== 1. 加载基础因子数据 ==========
        factor_filepath = DATA_CACHE_DIR / 'factor_data/factor_data.json.gz'
        logger.info("[静态加载] 加载基础因子数据：%s" % factor_filepath)
        
        with gzip.open(factor_filepath, 'rt', encoding='utf-8') as f:
            factor_data = json.load(f).get('data', [])
        factor_df = pd.DataFrame(factor_data)
        logger.info("[静态加载] 基础因子数据：%d 条" % len(factor_df))
        
        # ========== 2. 加载布林带 %B 数据 ==========
        from common.cache_paths import ROOT_DIR
        bollinger_filepath = ROOT_DIR / 'cache/bollinger_pb/bollinger_pb_history.json.gz'
        
        if bollinger_filepath.exists():
            logger.info("[静态加载] 加载布林带数据：%s" % bollinger_filepath)
            with gzip.open(bollinger_filepath, 'rt', encoding='utf-8') as f:
                bollinger_data = json.load(f).get('data', [])
            bollinger_df = pd.DataFrame(bollinger_data)[['date', 'asset', 'bollinger_pb']]
            factor_df = factor_df.merge(bollinger_df, on=['date', 'asset'], how='left')
            logger.info("[静态加载] 布林带数据：%d 条" % len(bollinger_df))
            
            # 立即释放中间变量（内存优化）
            del bollinger_data, bollinger_df
            gc.collect()
        
        # ========== 3. 加载换手率数据并计算 turnover_surge ==========
        turnover_filepath = DATA_CACHE_DIR / 'factor_data/turnover_rate_data.json.gz'
        
        if turnover_filepath.exists():
            logger.info("[静态加载] 加载换手率数据：%s" % turnover_filepath)
            with gzip.open(turnover_filepath, 'rt', encoding='utf-8') as f:
                turnover_data = json.load(f).get('data', [])
            turnover_df = pd.DataFrame(turnover_data).sort_values(['asset', 'date'])
            
            # 计算 5 日均值和突增比率
            turnover_df['turnover_rate_5d_mean'] = turnover_df.groupby('asset')['turnover_rate'].transform(
                lambda x: x.rolling(window=5, min_periods=1).mean()
            )
            turnover_df['turnover_surge'] = turnover_df['turnover_rate'] / turnover_df['turnover_rate_5d_mean']
            turnover_df = turnover_df[['date', 'asset', 'turnover_surge']]
            
            factor_df = factor_df.merge(turnover_df, on=['date', 'asset'], how='left')
            logger.info("[静态加载] 换手率数据：%d 条" % len(turnover_df))
            
            # 立即释放中间变量（内存优化）
            del turnover_data, turnover_df
            gc.collect()
        
        # ========== 4. 加载收益率数据 ==========
        return_filepath = DATA_CACHE_DIR / 'factor_data/return_data.json.gz'
        logger.info("[静态加载] 加载收益率数据：%s" % return_filepath)
        
        with gzip.open(return_filepath, 'rt', encoding='utf-8') as f:
            return_data = json.load(f).get('data', [])
        return_df = pd.DataFrame(return_data)
        
        merged_df = factor_df.merge(
            return_df[['date', 'asset', 'forward_return_1d', 'forward_return_3d', 'forward_return_5d']],
            on=['date', 'asset'], how='inner'
        )
        logger.info("[静态加载] 合并收益率数据：%d 条" % len(merged_df))
        
        # 立即释放中间变量（内存优化）
        del factor_data, factor_df, return_data, return_df
        gc.collect()
        
        # ========== 5. 天数筛选 ==========
        if max_days > 0 and not merged_df.empty:
            all_dates = sorted(merged_df['date'].unique())
            if len(all_dates) > max_days:
                recent_dates = set(all_dates[-max_days:])
                merged_df = merged_df[merged_df['date'].isin(recent_dates)]
                logger.info("[静态加载] 数据筛选：%d 天 → %d 天" % (len(all_dates), max_days))
        
        logger.info("[静态加载] 最终数据：%d 条，内存约700MB" % len(merged_df))
        return merged_df

class ScoringEngine:
    """多因子打分选股引擎"""
    
    # 反向因子列表（打分时需要反转）
    # 注意：IC计算使用反向排名，导致理解混淆
    # 原配置是正确的：RSI、KDJ_J、布林带%B 为反向因子
    REVERSE_FACTORS = ['volume_ratio', 'turnover_surge', 'B_mfi_overbought', 'B_volatility_ratio', 'B_plus_di_14', 'B_cci_overbought', 'B_keltner_position', 'B_trend_strength', 'B_atr_pct', 'B_bollinger_width_20', 'B_ma_trend', 'B_rsi_24']  # 12个反向因子（IC_DIRECTIONS中negative的全部）
    
    # 默认权重配置（移除主力净流入因子）
    DEFAULT_WEIGHTS = {
        'rsi': 17,
        'kdj_j': 14,
        'bollinger_pb': 17,
        'volume_ratio': 14,
        'turnover_surge': 14,
        'return_3d': 12
    }
    
    # 因子字段映射（实际缓存字段名 -> 因子名）- 已移除主力净流入
    FACTOR_FIELD_MAP = {
        'rsi_6': 'rsi',           # RSI 因子
        'rsi_14': 'rsi',          # RSI 因子
        'kdj_j': 'kdj_j',         # KDJ_J 因子
        'bollinger_pb': 'bollinger_pb',  # 布林带%B
        'volume_ratio_5': 'volume_ratio',  # 量比
        'turnover_surge': 'turnover_surge',  # 换手率突增
        'return_3d': 'return_3d',  # 3日涨幅
    }
    
    def __init__(self, return_col: str = 'forward_return_1d', use_shared_cache: bool = False):
        """初始化引擎（懒加载模式，支持共享缓存）
        
        v3.1 修复：数据加载改为懒加载，避免首次 API 调用耗时过长
        - 初始化时不加载数据，仅初始化属性
        - 首次调用 get_available_dates() 或其他需要数据的方法时才加载
        
        v3.10 引擎数据共享优化（云柏方案）：
        - use_shared_cache=True：使用共享因子数据，节省内存约720MB
        - use_shared_cache=False：独立加载（默认值，兼容旧模式）
        
        Args:
            return_col: 收益字段名（默认 forward_return_1d，支持 forward_return_5d）
            use_shared_cache: 是否使用共享缓存（默认 False，仅在多周期并行时启用）
        """
        self._return_col = return_col
        self._use_shared_cache = use_shared_cache
        
        if use_shared_cache and SharedFactorDataCache.is_loaded():
            # 使用共享因子数据（避免重复加载）
            shared_data = SharedFactorDataCache.get_shared_data()
            
            # v3 bugfix：防御性检查
            factor_df = shared_data.get('factor_df')
            if factor_df is None or factor_df.empty:
                logger.warning("[引擎] 共享缓存数据无效，回退到独立加载模式")
                self._use_shared_cache = False
                # 走原有独立加载逻辑（完整回退）
                self.factor_df = None
                self.turnover_df = None
                self.return_df = None
                self.kdj_df = None
                self.bollinger_df = None
                self.stock_info = None
                self.available_dates = []
                self._data_loaded = False
            else:
                # 检查必需字段
                if 'date' not in factor_df.columns or 'asset' not in factor_df.columns:
                    logger.warning("[引擎] factor_df 缺少必需字段（date/asset），回退到独立加载模式")
                    self._use_shared_cache = False
                    self.factor_df = None
                    self.turnover_df = None
                    self.return_df = None
                    self.kdj_df = None
                    self.bollinger_df = None
                    self.stock_info = None
                    self.available_dates = []
                    self._data_loaded = False
                else:
                    self.factor_df = factor_df
                    self.turnover_df = shared_data.get('turnover_df')  # 可能为 None
                    self.kdj_df = shared_data.get('kdj_df')            # 可能为 None
                    self.bollinger_df = shared_data.get('bollinger_df') # 可能为 None
                    self.stock_info = shared_data.get('stock_info')    # 可能为 None
                    self.available_dates = shared_data.get('available_dates', [])
                    
                    # 只加载周期收益数据
                    self.return_df = None
                    self._data_loaded = False  # 需要加载周期收益数据
                    
                    logger.info("[引擎] 使用共享缓存初始化（周期=%s，节省内存约720MB）" % return_col)
        else:
            # 原有逻辑（独立加载）
            self.factor_df = None
            self.turnover_df = None
            self.return_df = None
            self.kdj_df = None  # KDJ_J 因子数据
            self.bollinger_df = None  # 布林带%B 因子数据
            self.stock_info = None
            self.available_dates = []
            self._data_loaded = False  # 数据加载标志
        
        # 性能优化缓存（v3.4 添加）
        self._stock_name_cache = None  # 股票名称缓存
        self._price_cache = None  # 价格缓存
    
    def _get_valid_stock_codes(self) -> set:
        """获取有效股票代码列表（排除无基本信息股票，如S股）
        
        Returns:
            set: 有效股票代码集合
        """
        stock_list_path = ROOT_DIR / 'cache' / 'stock_list.json'
        if stock_list_path.exists():
            try:
                with open(stock_list_path, 'r', encoding='utf-8') as f:
                    stock_list = json.load(f)
                    # 修正：股票列表在 'stocks' 键下
                    stocks = stock_list.get('stocks', [])
                    # 过滤掉无名称的股票（如S股、退市股等）
                    return set(s['code'] for s in stocks if s.get('name'))
            except Exception as e:
                logger.warning(f"[股票验证] 加载股票列表失败: {e}")
                return set()
        return set()
    
    def _ensure_data_loaded(self):
        """确保数据已加载（懒加载入口）"""
        if not self._data_loaded:
            self._load_all_data()
            self._data_loaded = True
    
    def _load_all_data(self, max_days: int = 150):
        """加载所有数据源并整合
        
        v3.3 内存优化：默认只加载最近 150 天数据（约 600MB → 180MB）
        
        v3.8 内存优化（云柏方案）：
        - 分阶段加载：避免同时加载多个数据源
        - 每阶段后主动 GC：立即释放临时变量
        - 预期峰值内存：2300 MB → 1800 MB
        
        v3.10 引擎数据共享优化（云柏方案）：
        - use_shared_cache=True：只加载周期收益数据（约80MB）
        - 共享因子数据已在 SharedFactorDataCache 中加载
        
        Args:
            max_days: 最大加载天数（默认 150，约 6 个月数据）
                     设为 0 表示加载全部数据
        """
        import gc
        import time
        
        # v3.10 共享缓存优化：只加载周期收益数据
        if self._use_shared_cache and SharedFactorDataCache.is_loaded():
            load_start = time.time()
            print(f"[打分引擎] 共享缓存模式：只加载周期收益数据（周期={self._return_col}）")
            
            # 只加载周期收益数据（约80MB）
            self._load_return_data_minimal(max_days=max_days)
            
            # 计算3日涨幅（使用共享因子数据）
            self._calculate_return_3d()
            
            # 释放收益数据（已计算完毕）
            self.return_df = None
            gc.collect()
            
            # 加载股票基本信息
            self._load_stock_info()
            gc.collect()
            
            print(f"[打分引擎] 周期收益数据加载完成，耗时: {time.time() - load_start:.1f} 秒")
            return
        
        load_start = time.time()
        print(f"[打分引擎] 开始分阶段加载（最近 {max_days} 天）...")
        
        # ====== 阶段1：加载主因子数据（核心数据） ======
        print("[阶段1] 正在加载主因子数据...")
        self._load_factor_data_minimal(max_days=max_days)
        gc.collect()
        print(f"[阶段1] 完成，耗时: {time.time() - load_start:.1f} 秒")
        
        # ====== 阶段2：加载换手率数据 ======
        stage2_start = time.time()
        print("[阶段2] 正在加载换手率数据...")
        self._load_turnover_data_minimal(max_days=max_days)
        gc.collect()
        print(f"[阶段2] 完成，耗时: {time.time() - stage2_start:.1f} 秒")
        
        # ====== 阶段3：合并 factor + turnover ======
        stage3_start = time.time()
        print("[阶段3] 正在合并因子数据...")
        self._merge_factor_turnover()
        gc.collect()
        print(f"[阶段3] 完成，耗时: {time.time() - stage3_start:.1f} 秒")
        
        # ====== 阶段4：流式加载 KDJ_J ======
        stage4_start = time.time()
        print("[阶段4] 正在流式加载 KDJ_J...")
        self._load_kdj_data_minimal(max_days=max_days)
        self._merge_kdj()
        gc.collect()
        print(f"[阶段4] 完成，耗时: {time.time() - stage4_start:.1f} 秒")
        
        # ====== 阶段5：流式加载布林带%B ======
        stage5_start = time.time()
        print("[阶段5] 正在流式加载布林带%B...")
        self._load_bollinger_data_minimal(max_days=max_days)
        self._merge_bollinger()
        gc.collect()
        print(f"[阶段5] 完成，耗时: {time.time() - stage5_start:.1f} 秒")
        
        # ====== 阶段6：加载收益数据并计算3日涨幅 ======
        stage6_start = time.time()
        print("[阶段6] 正在加载收益数据...")
        self._load_return_data_minimal(max_days=max_days)
        self._calculate_return_3d()
        # 释放收益数据（已计算完毕）
        self.return_df = None
        gc.collect()
        print(f"[阶段6] 完成，耗时: {time.time() - stage6_start:.1f} 秒")
        
        # ====== 阶段7：加载股票基本信息 ======
        stage7_start = time.time()
        print("[阶段7] 正在加载股票基本信息...")
        self._load_stock_info()
        gc.collect()
        print(f"[阶段7] 完成，耗时: {time.time() - stage7_start:.1f} 秒")
        
        # ====== 阶段8：计算换手率突增因子 ======
        stage8_start = time.time()
        print("[阶段8] 正在计算换手率突增因子...")
        self._calculate_turnover_surge()
        gc.collect()
        print(f"[阶段8] 完成，耗时: {time.time() - stage8_start:.1f} 秒")
        
        # ====== 阶段9：转换为 category 类型（内存优化） ======
        stage9_start = time.time()
        print("[阶段9] 正在优化数据类型...")
        if self.factor_df is not None:
            self.factor_df['date'] = self.factor_df['date'].astype('category')
            self.factor_df['asset'] = self.factor_df['asset'].astype('category')
        gc.collect()
        print(f"[阶段9] 完成，耗时: {time.time() - stage9_start:.1f} 秒")
        
        # ====== 阶段10：最终清理 ======
        gc.collect()
        
        total_time = time.time() - load_start
        print(f"[打分引擎] 分阶段加载完成，总耗时: {total_time:.1f} 秒，可用日期: {len(self.available_dates)} 天")
    
    def _load_factor_data_minimal(self, max_days: int = 150):
        """加载主因子数据（rsi, volume_ratio）- 最小化版本
        
        v3.8 内存优化（云柏方案）：
        - 只保留必要列：date, asset, close, rsi_6, volume_ratio_5
        - 删除冗余列：open, high, low 等（节省 40% 内存）
        - 立即释放原始 JSON 数据
        
        Args:
            max_days: 最大加载天数（默认 150）
        """
        factor_path = CACHE_DIR / 'factor_data.json.gz'
        if not factor_path.exists():
            print("[打分引擎] 主因子数据不存在")
            return
        
        import gc
        
        # 读取 JSON 数据
        with gzip.open(factor_path, 'rt', encoding='utf-8') as f:
            data = json.load(f)
        
        # 立即获取日期范围并筛选
        all_dates = sorted(set(r.get('date') for r in data.get('data', [])))
        
        if max_days > 0 and len(all_dates) > max_days:
            recent_dates = set(all_dates[-max_days:])
            print(f"[打分引擎] 主因子数据（限制 {max_days} 天）: {len(all_dates)} 天 → {len(recent_dates)} 天")
            
            # 立即筛选并只保留必要列（避免创建中间 DataFrame）
            records = [
                {
                    'date': r['date'],
                    'asset': r['asset'],
                    'close': r.get('close'),  # 用于价格查询
                    'rsi_6': r.get('rsi_6'),  # RSI 因子
                    'volume_ratio_5': r.get('volume_ratio_5')  # 量比因子
                }
                for r in data.get('data', []) if r.get('date') in recent_dates
            ]
        else:
            print(f"[打分引擎] 主因子数据（全量）: {len(all_dates)} 天")
            
            records = [
                {
                    'date': r['date'],
                    'asset': r['asset'],
                    'close': r.get('close'),
                    'rsi_6': r.get('rsi_6'),
                    'volume_ratio_5': r.get('volume_ratio_5')
                }
                for r in data.get('data', [])
            ]
        
        # 立即释放原始 JSON 数据（节省 ~150MB）
        del data
        gc.collect()
        
        # 创建 DataFrame
        self.factor_df = pd.DataFrame(records)
        self.available_dates = sorted(self.factor_df['date'].unique())
        
        # 立即释放临时列表
        del records
        gc.collect()
        
        print(f"[打分引擎] 主因子数据加载完成: {len(self.factor_df)} 条（仅保留必要列）")
    
    def _load_factor_data(self, max_days: int = 150):
        """加载主因子数据（rsi, volume_ratio）- 旧版本
        
        v3.8 已废弃：请使用 _load_factor_data_minimal()
        此方法保留用于兼容性，但实际调用新方法
        """
        self._load_factor_data_minimal(max_days=max_days)
    
    def _load_turnover_data_minimal(self, max_days: int = 150):
        """加载换手率数据 - 最小化版本
        
        v3.8 内存优化（云柏方案）：
        - 只保留必要列：date, asset, turnover_rate
        - 立即释放原始 JSON 数据
        
        Args:
            max_days: 最大加载天数（默认 150）
        """
        turnover_path = CACHE_DIR / 'turnover_rate_data.json.gz'
        if not turnover_path.exists():
            print("[打分引擎] 换手率数据不存在")
            return
        
        import gc
        
        # 读取 JSON 数据
        with gzip.open(turnover_path, 'rt', encoding='utf-8') as f:
            data = json.load(f)
        
        # 立即获取日期范围并筛选
        all_dates = sorted(set(r.get('date') for r in data.get('data', [])))
        
        if max_days > 0 and len(all_dates) > max_days:
            recent_dates = set(all_dates[-max_days:])
            print(f"[打分引擎] 换手率数据（限制 {max_days} 天）: {len(all_dates)} 天 → {len(recent_dates)} 天")
            
            # 立即筛选并只保留必要列
            records = [
                {
                    'date': r['date'],
                    'asset': r['asset'],
                    'turnover_rate': r.get('turnover_rate')
                }
                for r in data.get('data', []) if r.get('date') in recent_dates
            ]
        else:
            print(f"[打分引擎] 换手率数据（全量）: {len(all_dates)} 天")
            
            records = [
                {
                    'date': r['date'],
                    'asset': r['asset'],
                    'turnover_rate': r.get('turnover_rate')
                }
                for r in data.get('data', [])
            ]
        
        # 立即释放原始 JSON 数据
        del data
        gc.collect()
        
        # 创建 DataFrame
        self.turnover_df = pd.DataFrame(records)
        
        # 立即释放临时列表
        del records
        gc.collect()
        
        print(f"[打分引擎] 换手率数据加载完成: {len(self.turnover_df)} 条（仅保留必要列）")
    
    def _load_turnover_data(self, max_days: int = 150):
        """加载换手率数据 - 旧版本
        
        v3.8 已废弃：请使用 _load_turnover_data_minimal()
        此方法保留用于兼容性，但实际调用新方法
        """
        self._load_turnover_data_minimal(max_days=max_days)
    
    def _load_main_inflow_data(self):
        """加载主力净流入数据 - 已废弃（用户不需要）"""
        pass
    
    def _load_return_data_minimal(self, max_days: int = 150):
        """加载收益数据（用于计算3日涨幅）- 最小化版本
        
        v3.8 内存优化（云柏方案）：
        - 只保留必要列：date, asset, forward_return_1d
        - 立即释放原始 JSON 数据
        
        Args:
            max_days: 最大加载天数（默认 150）
        """
        return_path = CACHE_DIR / 'return_data.json.gz'
        if not return_path.exists():
            print("[打分引擎] 收益数据不存在")
            return
        
        import gc
        
        # 读取 JSON 数据
        with gzip.open(return_path, 'rt', encoding='utf-8') as f:
            data = json.load(f)
        
        # 立即获取日期范围并筛选
        all_dates = sorted(set(r.get('date') for r in data.get('data', [])))
        
        if max_days > 0 and len(all_dates) > max_days:
            recent_dates = set(all_dates[-max_days:])
            print(f"[打分引擎] 收益数据（限制 {max_days} 天）: {len(all_dates)} 天 → {len(recent_dates)} 天")
            
            # 立即筛选并只保留必要列
            records = [
                {
                    'date': r['date'],
                    'asset': r['asset'],
                    self._return_col: r.get(self._return_col)
                }
                for r in data.get('data', []) if r.get('date') in recent_dates
            ]
        else:
            print(f"[打分引擎] 收益数据（全量）: {len(all_dates)} 天")
            
            records = [
                {
                    'date': r['date'],
                    'asset': r['asset'],
                    self._return_col: r.get(self._return_col)
                }
                for r in data.get('data', [])
            ]
        
        # 立即释放原始 JSON 数据
        del data
        gc.collect()
        
        # 创建 DataFrame
        self.return_df = pd.DataFrame(records)
        
        # 立即释放临时列表
        del records
        gc.collect()
        
        print(f"[打分引擎] 收益数据加载完成: {len(self.return_df)} 条（仅保留必要列）")
    
    def _load_return_data(self, max_days: int = 150):
        """加载收益数据（用于计算3日涨幅）- 旧版本
        
        v3.8 已废弃：请使用 _load_return_data_minimal()
        此方法保留用于兼容性，但实际调用新方法
        """
        self._load_return_data_minimal(max_days=max_days)
    
    def _load_kdj_data_minimal(self, max_days: int = 150):
        """加载 KDJ_J 因子数据 - 最小化版本
        
        v3.8 内存优化（云柏方案）：
        - 流式加载：使用 ijson 避免内存爆炸
        - 只保留必要列：date, asset, kdj_j
        - 删除冗余列：kdj_k, kdj_d 等（节省 40% 内存）
        - 立即释放临时数据
        
        Args:
            max_days: 最大加载天数（默认 150）
        """
        kdj_path = ROOT_DIR / 'cache/kdj_j/kdj_j_history.json.gz'
        if not kdj_path.exists():
            print("[打分引擎] KDJ_J 数据不存在")
            return
        
        import gc
        
        # 第一步：先读取日期范围（最小内存占用）
        print("[打分引擎] 正在读取 KDJ_J 日期范围...")
        try:
            import ijson
            dates_set = set()
            with gzip.open(kdj_path, 'rt', encoding='utf-8') as f:
                for record in ijson.items(f, 'data.item'):
                    dates_set.add(record.get('date'))
            all_dates = sorted(dates_set)
            
            # 确定需要保留的日期
            if max_days > 0 and len(all_dates) > max_days:
                recent_dates = set(all_dates[-max_days:])
                print(f"[打分引擎] KDJ_J: {len(all_dates)} 天 → 保留最近 {max_days} 天")
            else:
                recent_dates = set(all_dates)
                print(f"[打分引擎] KDJ_J: {len(all_dates)} 天（全量）")
            
            # 立即释放日期集合
            del dates_set, all_dates
            gc.collect()
            
            # 第二步：流式读取并筛选（只保留必要列）
            print("[打分引擎] 正在流式加载 KDJ_J 数据...")
            records = []
            with gzip.open(kdj_path, 'rt', encoding='utf-8') as f:
                for record in ijson.items(f, 'data.item'):
                    if record.get('date') in recent_dates:
                        # 只保留必要字段，减少内存占用
                        records.append({
                            'date': record['date'],
                            'asset': record['asset'],
                            'kdj_j': record.get('kdj_j')
                        })
            
            print(f"[打分引擎] KDJ_J 流式加载完成: {len(records)} 条")
            self.kdj_df = pd.DataFrame(records)
            
            # 立即释放临时数据
            del records, recent_dates
            gc.collect()
            
        except ImportError:
            # ijson 未安装，使用传统方式但优化内存
            import json
            print("[打分引擎] ijson 未安装，使用传统方式加载...")
            
            with gzip.open(kdj_path, 'rt', encoding='utf-8') as f:
                data = json.load(f)
            
            # 立即提取日期范围
            all_dates = sorted(set(r.get('date') for r in data.get('data', [])))
            
            if max_days > 0 and len(all_dates) > max_days:
                recent_dates = set(all_dates[-max_days:])
                print(f"[打分引擎] KDJ_J: {len(all_dates)} 天 → 保留最近 {max_days} 天")
                
                # 立即筛选，只保留必要字段
                records = [
                    {'date': r['date'], 'asset': r['asset'], 'kdj_j': r.get('kdj_j')}
                    for r in data.get('data', []) if r.get('date') in recent_dates
                ]
                
                del recent_dates
            else:
                records = [
                    {'date': r['date'], 'asset': r['asset'], 'kdj_j': r.get('kdj_j')}
                    for r in data.get('data', [])
                ]
            
            # 立即释放原始数据内存
            del data, all_dates
            gc.collect()
            
            print(f"[打分引擎] KDJ_J 加载完成: {len(records)} 条")
            self.kdj_df = pd.DataFrame(records)
            
            del records
            gc.collect()
    
    def _load_kdj_data(self, max_days: int = 150):
        """加载 KDJ_J 因子数据 - 旧版本
        
        v3.8 已废弃：请使用 _load_kdj_data_minimal()
        此方法保留用于兼容性，但实际调用新方法
        """
        self._load_kdj_data_minimal(max_days=max_days)
    
    def _load_bollinger_data_minimal(self, max_days: int = 150):
        """加载布林带%B因子数据 - 最小化版本
        
        v3.8 内存优化（云柏方案）：
        - 流式加载：使用 ijson 避免内存爆炸
        - 只保留必要列：date, asset, bollinger_pb
        - 删除冗余列：upper, lower 等（节省 40% 内存）
        - 立即释放临时数据
        
        Args:
            max_days: 最大加载天数（默认 150）
        """
        bollinger_path = ROOT_DIR / 'cache/bollinger_pb/bollinger_pb_history.json.gz'
        if not bollinger_path.exists():
            print("[打分引擎] 布林带%B 数据不存在")
            return
        
        import gc
        
        # 第一步：先读取日期范围（最小内存占用）
        print("[打分引擎] 正在读取布林带%B日期范围...")
        try:
            import ijson
            dates_set = set()
            with gzip.open(bollinger_path, 'rt', encoding='utf-8') as f:
                for record in ijson.items(f, 'data.item'):
                    dates_set.add(record.get('date'))
            all_dates = sorted(dates_set)
            
            # 确定需要保留的日期
            if max_days > 0 and len(all_dates) > max_days:
                recent_dates = set(all_dates[-max_days:])
                print(f"[打分引擎] 布林带%B: {len(all_dates)} 天 → 保留最近 {max_days} 天")
            else:
                recent_dates = set(all_dates)
                print(f"[打分引擎] 布林带%B: {len(all_dates)} 天（全量）")
            
            # 立即释放日期集合
            del dates_set, all_dates
            gc.collect()
            
            # 第二步：流式读取并筛选（只保留必要列）
            print("[打分引擎] 正在流式加载布林带%B数据...")
            records = []
            with gzip.open(bollinger_path, 'rt', encoding='utf-8') as f:
                for record in ijson.items(f, 'data.item'):
                    if record.get('date') in recent_dates:
                        records.append({
                            'date': record['date'],
                            'asset': record['asset'],
                            'bollinger_pb': record.get('bollinger_pb')
                        })
            
            print(f"[打分引擎] 布林带%B流式加载完成: {len(records)} 条")
            self.bollinger_df = pd.DataFrame(records)
            
            # 立即释放临时数据
            del records, recent_dates
            gc.collect()
            
        except ImportError:
            # ijson 未安装，使用传统方式但优化内存
            import json
            print("[打分引擎] ijson 未安装，使用传统方式加载...")
            
            with gzip.open(bollinger_path, 'rt', encoding='utf-8') as f:
                data = json.load(f)
            
            all_dates = sorted(set(r.get('date') for r in data.get('data', [])))
            
            if max_days > 0 and len(all_dates) > max_days:
                recent_dates = set(all_dates[-max_days:])
                print(f"[打分引擎] 布林带%B: {len(all_dates)} 天 → 保留最近 {max_days} 天")
                
                records = [
                    {'date': r['date'], 'asset': r['asset'], 'bollinger_pb': r.get('bollinger_pb')}
                    for r in data.get('data', []) if r.get('date') in recent_dates
                ]
                
                del recent_dates
            else:
                records = [
                    {'date': r['date'], 'asset': r['asset'], 'bollinger_pb': r.get('bollinger_pb')}
                    for r in data.get('data', [])
                ]
            
            del data, all_dates
            gc.collect()
            
            print(f"[打分引擎] 布林带%B加载完成: {len(records)} 条")
            self.bollinger_df = pd.DataFrame(records)
            
            del records
            gc.collect()
    
    def _load_bollinger_data(self, max_days: int = 150):
        """加载布林带%B因子数据 - 旧版本
        
        v3.8 已废弃：请使用 _load_bollinger_data_minimal()
        此方法保留用于兼容性，但实际调用新方法
        """
        self._load_bollinger_data_minimal(max_days=max_days)
    
    def _load_stock_info(self):
        """加载股票基本信息"""
        stock_path = ROOT_DIR / 'cache/stock_list.json'
        if stock_path.exists():
            with open(stock_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            # 解析正确格式：{"meta": ..., "stocks": [...]}
            self.stock_info = data.get('stocks', [])
            print(f"[打分引擎] 股票信息: {len(self.stock_info)} 只")
    
    def _merge_factor_turnover(self):
        """合并主因子数据和换手率数据
        
        v3.8 内存优化（云柏方案）：
        - 分阶段合并，避免一次性合并所有数据源
        - 合并后立即释放换手率数据
        - 主动 GC 降低峰值
        """
        import gc
        import time
        
        if self.factor_df is None:
            print("[打分引擎] 主因子数据不存在，跳过合并")
            return
        
        if self.turnover_df is None:
            print("[打分引擎] 换手率数据不存在，跳过合并")
            return
        
        merge_start = time.time()
        print(f"[打分引擎] 正在合并换手率数据 ({len(self.turnover_df)} 条)...")
        
        # 合并换手率数据
        self.factor_df = self.factor_df.merge(
            self.turnover_df[['date', 'asset', 'turnover_rate']],
            on=['date', 'asset'],
            how='left'
        )
        
        # 立即释放换手率数据
        self.turnover_df = None
        gc.collect()
        
        merge_time = time.time() - merge_start
        print(f"[打分引擎] 换手率合并完成，耗时: {merge_time:.1f} 秒，turnover_rate 非空: {self.factor_df['turnover_rate'].notna().sum()}")
    
    def _merge_kdj(self):
        """合并 KDJ_J 数据
        
        v3.8 内存优化（云柏方案）：
        - 分阶段合并
        - 合并后立即释放 KDJ_J 数据
        - 主动 GC 降低峰值
        """
        import gc
        import time
        
        if self.factor_df is None:
            print("[打分引擎] 主因子数据不存在，跳过合并")
            return
        
        if self.kdj_df is None:
            print("[打分引擎] KDJ_J 数据不存在，跳过合并")
            return
        
        merge_start = time.time()
        print(f"[打分引擎] 正在合并 KDJ_J 数据 ({len(self.kdj_df)} 条)...")
        
        # 合并 KDJ_J 数据
        self.factor_df = self.factor_df.merge(
            self.kdj_df[['date', 'asset', 'kdj_j']],
            on=['date', 'asset'],
            how='left'
        )
        
        # 立即释放 KDJ_J 数据
        self.kdj_df = None
        gc.collect()
        
        merge_time = time.time() - merge_start
        print(f"[打分引擎] KDJ_J 合并完成，耗时: {merge_time:.1f} 秒，kdj_j 非空: {self.factor_df['kdj_j'].notna().sum()}")
    
    def _merge_bollinger(self):
        """合并布林带%B数据
        
        v3.8 内存优化（云柏方案）：
        - 分阶段合并
        - 合并后立即释放布林带数据
        - 主动 GC 降低峰值
        """
        import gc
        import time
        
        if self.factor_df is None:
            print("[打分引擎] 主因子数据不存在，跳过合并")
            return
        
        if self.bollinger_df is None:
            print("[打分引擎] 布林带%B数据不存在，跳过合并")
            return
        
        merge_start = time.time()
        print(f"[打分引擎] 正在合并布林带%B数据 ({len(self.bollinger_df)} 条)...")
        
        # 合并布林带%B数据
        self.factor_df = self.factor_df.merge(
            self.bollinger_df[['date', 'asset', 'bollinger_pb']],
            on=['date', 'asset'],
            how='left'
        )
        
        # 立即释放布林带数据
        self.bollinger_df = None
        gc.collect()
        
        merge_time = time.time() - merge_start
        print(f"[打分引擎] 布林带%B合并完成，耗时: {merge_time:.1f} 秒，bollinger_pb 非空: {self.factor_df['bollinger_pb'].notna().sum()}")
    
    def _merge_all_data(self):
        """整合所有数据源
        
        v3.8 内存优化（云柏方案）：
        - 此方法已废弃，改为分阶段合并
        - 保留此方法用于兼容旧代码调用
        - 实际合并已在 _load_all_data 中分阶段完成
        
        v3.4 优化：添加进度日志，分步释放内存
        """
        import gc
        import time
        
        if self.factor_df is None:
            print("[打分引擎] 主因子数据不存在，跳过整合")
            return
        
        # 检查是否已合并（如果 turnover_rate 列存在，说明已合并）
        if 'turnover_rate' in self.factor_df.columns and 'kdj_j' in self.factor_df.columns and 'bollinger_pb' in self.factor_df.columns:
            print("[打分引擎] 数据已合并完成（使用分阶段加载）")
            return
        
        # 兼容旧代码：如果数据未合并，执行合并
        merge_start = time.time()
        print(f"[打分引擎] 开始数据整合（兼容模式），主因子: {len(self.factor_df)} 条")
        
        # 合并换手率数据
        if self.turnover_df is not None and 'turnover_rate' not in self.factor_df.columns:
            print("[打分引擎] 正在合并换手率数据...")
            self.factor_df = self.factor_df.merge(
                self.turnover_df[['date', 'asset', 'turnover_rate']],
                on=['date', 'asset'],
                how='left'
            )
            # 释放换手率数据
            self.turnover_df = None
            gc.collect()
            print(f"[打分引擎] 换手率合并完成，耗时: {time.time() - merge_start:.1f} 秒")
        
        # 合并 KDJ_J 数据
        if self.kdj_df is not None and 'kdj_j' not in self.factor_df.columns:
            kdj_start = time.time()
            print(f"[打分引擎] 正在合并 KDJ_J 数据 ({len(self.kdj_df)} 条)...")
            self.factor_df = self.factor_df.merge(
                self.kdj_df[['date', 'asset', 'kdj_j']],
                on=['date', 'asset'],
                how='left'
            )
            # 释放 KDJ_J 数据
            self.kdj_df = None
            kdj_merge_time = time.time() - kdj_start
            print(f"[打分引擎] KDJ_J 合并完成，耗时: {kdj_merge_time:.1f} 秒，kdj_j 非空: {self.factor_df['kdj_j'].notna().sum()}")
            gc.collect()
        
        # 合并布林带%B数据
        if self.bollinger_df is not None and 'bollinger_pb' not in self.factor_df.columns:
            bollinger_start = time.time()
            print(f"[打分引擎] 正在合并布林带%B数据 ({len(self.bollinger_df)} 条)...")
            self.factor_df = self.factor_df.merge(
                self.bollinger_df[['date', 'asset', 'bollinger_pb']],
                on=['date', 'asset'],
                how='left'
            )
            # 释放布林带数据
            self.bollinger_df = None
            bollinger_merge_time = time.time() - bollinger_start
            print(f"[打分引擎] 布林带%B合并完成，耗时: {bollinger_merge_time:.1f} 秒，非空: {self.factor_df['bollinger_pb'].notna().sum()}")
            gc.collect()
        
        # 计算换手率突增因子
        if 'turnover_surge' not in self.factor_df.columns:
            print("[打分引擎] 正在计算换手率突增因子...")
            self._calculate_turnover_surge()
        
        # 计算3日涨幅因子
        if 'return_3d' not in self.factor_df.columns:
            print("[打分引擎] 正在计算3日涨幅因子...")
            self._calculate_return_3d()
        
        # 最终清理内存
        gc.collect()
        
        total_time = time.time() - merge_start
        print(f"[打分引擎] 数据整合完成（兼容模式），总耗时: {total_time:.1f} 秒，最终数据量: {len(self.factor_df)} 条")
    
    def _calculate_turnover_surge(self):
        """计算换手率突增因子"""
        if 'turnover_rate' not in self.factor_df.columns:
            return
        
        print("[打分引擎] 计算换手率突增因子...")
        
        # 按 asset 分组计算5日均值
        self.factor_df = self.factor_df.sort_values(['asset', 'date'])
        
        # 计算5日滚动均值
        turnover_ma5 = self.factor_df.groupby('asset')['turnover_rate'].transform(
            lambda x: x.rolling(window=5, min_periods=1).mean()
        )
        
        # 换手率突增 = 当日换手率 / 5日均值
        self.factor_df['turnover_surge'] = self.factor_df['turnover_rate'] / turnover_ma5
        
        # 过滤异常值（突增倍数过大）
        self.factor_df['turnover_surge'] = self.factor_df['turnover_surge'].clip(upper=10)
    
    def _calculate_return_3d(self):
        """计算3日涨幅因子"""
        if self.return_df is None:
            # 如果没有收益数据，用 close 价格计算
            if 'close' in self.factor_df.columns:
                print("[打分引擎] 使用 close 价格计算3日涨幅...")
                self.factor_df = self.factor_df.sort_values(['asset', 'date'])
                
                # 计算3日涨幅
                close_series = self.factor_df.groupby('asset')['close']
                self.factor_df['return_3d'] = close_series.transform(
                    lambda x: (x / x.shift(3) - 1) * 100  # 百分比形式
                )
            return
        
        print("[打分引擎] 计算3日涨幅因子...")
        
        # 从收益数据计算3日累计收益
        # 收益数据通常是 forward_return_1d，需要反向累加
        # 这里简化处理：直接用 close 价格计算
        if 'close' in self.factor_df.columns:
            self.factor_df = self.factor_df.sort_values(['asset', 'date'])
            
            # 计算3日涨幅（百分比）
            close_series = self.factor_df.groupby('asset')['close']
            self.factor_df['return_3d'] = close_series.transform(
                lambda x: (x / x.shift(3) - 1) * 100
            )
        
        # ===== 新增：合并收益字段到 factor_df =====
        if self._return_col not in self.factor_df.columns:
            print(f"[打分引擎] 合并 {self._return_col} 到 factor_df...")
            self.factor_df = self.factor_df.merge(
                self.return_df[['date', 'asset', self._return_col]],
                on=['date', 'asset'],
                how='left'
            )
            print(f"[打分引擎] 合并完成，factor_df 列数: {len(self.factor_df.columns)}")
    
    def get_available_dates(self) -> List[str]:
        """获取可用日期列表"""
        self._ensure_data_loaded()
        return self.available_dates
    
    def get_latest_date(self) -> Optional[str]:
        """获取最新可用日期"""
        self._ensure_data_loaded()
        if self.available_dates:
            return self.available_dates[-1]
        return None
    
    def normalize(self, values: pd.Series, method: str = 'quantile') -> pd.Series:
        """
        标准化处理
        
        Args:
            values: 原始值序列
            method: 标准化方法 ('quantile', 'minmax', 'zscore')
            
        Returns:
            标准化后的值 (0-1之间)
        """
        # v3.5 修复：先将 Decimal 类型转换为 float，避免类型不兼容错误
        if hasattr(values, 'dtype') and values.dtype == object:
            # 检查是否有 Decimal 类型，转换为 float
            from decimal import Decimal
            if any(isinstance(v, Decimal) for v in values.dropna()):
                values = values.apply(lambda x: float(x) if isinstance(x, Decimal) else x)
        
        if method == 'quantile':
            # 分位数标准化（排名百分比）
            return values.rank(pct=True)
        
        elif method == 'minmax':
            # 最大最小标准化
            min_val = float(values.min())
            max_val = float(values.max())
            if max_val == min_val:
                return pd.Series([0.5] * len(values))
            return (values.astype(float) - min_val) / (max_val - min_val)
        
        elif method == 'zscore':
            # Z-score 标准化（转换为0-1区间）
            mean_val = float(values.mean())
            std_val = float(values.std())
            if std_val == 0:
                return pd.Series([0.5] * len(values))
            z = (values.astype(float) - mean_val) / std_val
            # 将 z-score 映射到 0-1 区间 (使用 sigmoid)
            return 1 / (1 + np.exp(-z))
        
        return values
    
    def sigmoid_score(self, x: float, k: float = 10) -> float:
        """
        Sigmoid 打分函数
        
        Args:
            x: 标准化后的值 (0-1)
            k: 曲线陡峭度参数
            
        Returns:
            打分值 (0-1)
        """
        return 1 / (1 + np.exp(-k * (x - 0.5)))
    
    def calculate_scores(
        self,
        date: str,
        weights: Dict[str, float],
        normalize_method: str = 'quantile',
        score_function: str = 'sigmoid',
        k_value: float = 10,
        top_n: int = 10
    ) -> Dict:
        """
        计算指定日期的综合得分并选出 Top N
        
        v3.2 性能优化：
        - 将 normalize 调用从双重循环内移出
        - 预先计算每个因子的标准化值（O(n) → O(1)）
        - 使用 asset 直接索引获取标准化值
        
        Args:
            date: 日期字符串
            weights: 因子权重字典
            normalize_method: 标准化方法
            score_function: 打分函数 ('sigmoid', 'linear')
            k_value: Sigmoid k 参数
            top_n: 选股数量
            
        Returns:
            包含选股结果的字典
        """
        self._ensure_data_loaded()  # 懒加载
        
        if self.factor_df is None:
            return {'success': False, 'error': '数据未加载'}
        
        # 检查日期是否存在
        if date not in self.available_dates:
            return {
                'success': False,
                'error': f'日期 {date} 无数据，可用日期范围: {self.available_dates[0]} ~ {self.available_dates[-1]}'
            }
        
        # 获取当日数据
        daily_df = self.factor_df[self.factor_df['date'] == date].copy()
        
        if len(daily_df) == 0:
            return {'success': False, 'error': f'日期 {date} 无股票数据'}
        
        # 新增：股票列表验证（过滤无基本信息的股票）
        valid_codes = self._get_valid_stock_codes()
        if valid_codes:
            # 注意：factor_df 使用 'asset' 列作为股票代码，不是 'code'
            daily_df = daily_df[daily_df['asset'].isin(valid_codes)]
            if len(daily_df) == 0:
                return {'success': False, 'error': f'日期 {date} 无有效股票数据（已过滤S股等）'}
        
        # 总权重（归一化）- 使用绝对值之和避免负权重导致除零
        total_weight = sum(abs(w) for w in weights.values())
        if total_weight == 0:
            return {'success': False, 'error': '权重总和为0'}
        
        normalized_weights = {k: v / total_weight for k, v in weights.items()}
        
        # 定义因子字段名（移除主力净流入）
        factor_columns = {
            'rsi': 'rsi_6',
            'kdj_j': 'kdj_j',
            'bollinger_pb': 'bollinger_pb',
            'volume_ratio': 'volume_ratio_5',
            'turnover_surge': 'turnover_surge',
            'return_3d': 'return_3d'
        }
        
        # ========== 性能优化核心：预先计算所有因子的标准化值 ==========
        # v3.2 向量化优化：复杂度从 O(n²) 降为 O(n)
        # 将标准化值直接存入 DataFrame，避免 iterrows
        
        # 直接在 DataFrame 上添加标准化列
        for factor_name, factor_col in factor_columns.items():
            if factor_col not in daily_df.columns:
                continue
            
            weight = normalized_weights.get(factor_name, 0)
            if weight == 0:
                continue
            
            # v3.5 修复：先将 Decimal 类型转换为 float，避免类型不兼容错误
            from decimal import Decimal
            factor_series = daily_df[factor_col]
            if factor_series.dtype == object:
                # 检查是否有 Decimal 类型
                if any(isinstance(v, Decimal) for v in factor_series.dropna()):
                    factor_series = factor_series.apply(lambda x: float(x) if isinstance(x, Decimal) else x)
                    daily_df[factor_col] = factor_series
            
            # 向量化标准化（使用 rank pct）
            if normalize_method == 'quantile':
                # 修复: len(factor_values)==1 时 rank 处理不一致
                # 当只有一个有效值时，rank pct 返回 1.0，应返回中性值 0.5
                valid_count = daily_df[factor_col].notna().sum()
                if valid_count <= 1:
                    daily_df[f'{factor_name}_norm'] = 0.5
                else:
                    daily_df[f'{factor_name}_norm'] = daily_df[factor_col].rank(pct=True)
            elif normalize_method == 'minmax':
                # 确保使用 float 类型计算
                min_val = float(daily_df[factor_col].min())
                max_val = float(daily_df[factor_col].max())
                if max_val == min_val or pd.isna(min_val) or pd.isna(max_val):
                    daily_df[f'{factor_name}_norm'] = 0.5
                else:
                    daily_df[f'{factor_name}_norm'] = (daily_df[factor_col].astype(float) - min_val) / (max_val - min_val)
            elif normalize_method == 'zscore':
                # 确保使用 float 类型计算
                mean_val = float(daily_df[factor_col].mean())
                std_val = float(daily_df[factor_col].std())
                if std_val == 0 or pd.isna(std_val):
                    daily_df[f'{factor_name}_norm'] = 0.5
                else:
                    z = (daily_df[factor_col].astype(float) - mean_val) / std_val
                    daily_df[f'{factor_name}_norm'] = 1 / (1 + np.exp(-z))
            else:
                daily_df[f'{factor_name}_norm'] = daily_df[factor_col].rank(pct=True)
            
            # 反向因子反转
            if factor_name in self.REVERSE_FACTORS:
                daily_df[f'{factor_name}_norm'] = 1 - daily_df[f'{factor_name}_norm']
            
            # 打分（向量化）
            if score_function == 'sigmoid':
                # 向量化 sigmoid 计算
                daily_df[f'{factor_name}_score'] = 1 / (1 + np.exp(-k_value * (daily_df[f'{factor_name}_norm'] - 0.5)))
            else:
                daily_df[f'{factor_name}_score'] = daily_df[f'{factor_name}_norm']
            
            # 加权贡献
            daily_df[f'{factor_name}_contrib'] = daily_df[f'{factor_name}_score'] * weight * 100
        
        # ========== 向量化计算综合得分 ==========
        
        # 计算总分（sum of contributions）
        contrib_cols = [c for c in daily_df.columns if c.endswith('_contrib')]
        daily_df['total_score'] = daily_df[contrib_cols].sum(axis=1, skipna=True)
        daily_df['total_score'] = daily_df['total_score'].fillna(0)
        
        # 按得分排序，取 Top N
        daily_df = daily_df.sort_values('total_score', ascending=False)
        top_df = daily_df.head(top_n)
        
        # ========== 改进 1: 行业分散约束 ========== 
        # 应用行业分散约束（同行业最多选 N 只股票）
        max_same_industry = self._get_max_same_industry()
        if max_same_industry > 0:
            # 转换为列表格式用于行业约束
            scored_stocks = []
            for idx, row in top_df.iterrows():
                scored_stocks.append({
                    'code': row['asset'],
                    'total_score': row['total_score'],
                    'row_data': row
                })
            
            # 应用行业约束
            constrained_stocks = self._apply_industry_constraint(scored_stocks, max_same_industry)
            
            # 重新构建 top_df（按约束后的顺序）
            constrained_codes = [s['code'] for s in constrained_stocks]
            top_df = daily_df[daily_df['asset'].isin(constrained_codes)].copy()
            # 按原始得分排序
            top_df = top_df.sort_values('total_score', ascending=False)
            
            logger.info(f"[行业分散] 约束前候选 {len(scored_stocks)} 只 → 约束后 {len(constrained_stocks)} 只")
        
        # ========== 构建结果列表 ========== 
        
        results = []
        for idx, row in top_df.iterrows():
            asset = row['asset']
            stock_name = self._get_stock_name(asset)
            total_score = row['total_score']
            
            # 获取行业信息（改进 1）
            industry = self._get_stock_industry(asset)
            
            # 构建因子明细
            factor_details = {}
            for factor_name, factor_col in factor_columns.items():
                weight = normalized_weights.get(factor_name, 0)
                if weight == 0:
                    continue
                
                raw_value = row.get(factor_col)
                norm_score = row.get(f'{factor_name}_norm', 0.5)
                score = row.get(f'{factor_name}_score', 0.5)
                contribution = row.get(f'{factor_name}_contrib', 0)
                
                if raw_value is not None and not pd.isna(raw_value):
                    factor_details[factor_name] = {
                        'raw': round(raw_value, 4) if isinstance(raw_value, float) else raw_value,
                        'normalized': round(norm_score, 4) if not pd.isna(norm_score) else 0.5,
                        'score': round(score, 4) if not pd.isna(score) else 0.5,
                        'weight': weight,
                        'contribution': round(contribution, 2) if not pd.isna(contribution) else 0
                    }
            
            results.append({
                'code': asset,
                'name': stock_name,
                'total_score': round(total_score, 2),
                'industry': industry,  # 改进 1: 新增行业字段
                'factor_scores': factor_details
            })
        
        top_results = results
        
        # 统计摘要
        summary = {
            'total_candidates': len(results),
            'avg_score': round(sum(r['total_score'] for r in top_results) / len(top_results), 2) if top_results else 0,
            'max_score': top_results[0]['total_score'] if top_results else 0,
            'selected_count': len(top_results)
        }
        
        return {
            'success': True,
            'date': date,
            'summary': summary,
            'selections': top_results,
            'params': {
                'weights': weights,
                'normalize_method': normalize_method,
                'score_function': score_function,
                'k_value': k_value,
                'top_n': top_n
            }
        }
    
    def get_stock_detail(self, code: str, date: str = None) -> Dict:
        """
        获取股票详情
        
        Args:
            code: 股票代码
            date: 日期（默认最新）
            
        Returns:
            股票详情字典
        """
        self._ensure_data_loaded()  # 懒加载
        
        # 添加 date 参数有效性检查
        if date is None or date == 'undefined' or date == '':
            date = self.get_latest_date()
            logger.info(f"date 参数无效，使用最新日期: {date}")
        
        if self.factor_df is None:
            return {'success': False, 'error': '数据未加载'}
        
        # 获取当日数据
        daily_df = self.factor_df[
            (self.factor_df['date'] == date) & 
            (self.factor_df['asset'] == code)
        ]
        
        if len(daily_df) == 0:
            return {'success': False, 'error': f'股票 {code} 在 {date} 无数据'}
        
        row = daily_df.iloc[0]
        
        # 基本信息
        stock_name = self._get_stock_name(code)
        
        # 因子明细
        factors = [
            {
                'name': 'RSI(6)',
                'factor_id': 'rsi',
                'raw': round(row.get('rsi_6', 0), 2),
                'direction': '反向',
                'desc': '超卖(<30)预期反弹'
            },
            {
                'name': 'KDJ_J',
                'factor_id': 'kdj_j',
                'raw': round(row.get('kdj_j', 0), 2),
                'direction': '反向',
                'desc': 'J值超卖反弹'
            },
            {
                'name': '布林带%B',
                'factor_id': 'bollinger_pb',
                'raw': round(row.get('bollinger_pb', 0), 2),
                'direction': '反向',
                'desc': '跌破下轨反弹'
            },
            {
                'name': '量比(5)',
                'factor_id': 'volume_ratio',
                'raw': round(row.get('volume_ratio_5', 0), 2),
                'direction': '正向',
                'desc': '放量>2表示资金关注'
            },
            {
                'name': '换手率突增',
                'factor_id': 'turnover_surge',
                'raw': round(row.get('turnover_surge', 0), 2),
                'direction': '正向',
                'desc': '换手率突增倍数'
            },
            {
                'name': '3日涨幅',
                'factor_id': 'return_3d',
                'raw': round(row.get('return_3d', 0), 2),
                'direction': '正向',
                'desc': '近3日累计涨幅%'
            }
        ]
        
        # 价格历史（近20日）
        price_history = self._get_price_history(code, days=20)
        
        return {
            'success': True,
            'code': code,
            'name': stock_name,
            'date': date,
            'factors': factors,
            'price_history': price_history,
            'close': round(row.get('close', 0), 2)
        }
    
    def _get_stock_industry(self, code: str) -> str:
        """
        获取单只股票的行业（改进 1）
        
        修复: 添加统一错误日志
        
        Args:
            code: 股票代码（如 '000001'）
            
        Returns:
            str: 行业名称，未知股票返回 '未知'
        """
        try:
            from fetch_stock_industry import get_stock_industry
            return get_stock_industry(code)
        except ImportError:
            logger.warning(f"[行业分散] fetch_stock_industry 模块不存在，无法获取行业信息")
            return '未知'
        except Exception as e:
            # 修复: 统一错误日志（warning级别）
            logger.warning(f"[行业分散] 获取行业失败: {code} - {type(e).__name__}: {e}")
            return '未知'
    
    def _get_max_same_industry(self) -> int:
        """
        从配置获取行业约束参数（改进 1）
        
        Returns:
            int: 同行业最多选股数（默认2）
        """
        config = self._load_config()
        industry_config = config.get('industry_constraint', {})
        
        # 检查是否启用
        if not industry_config.get('enabled', True):
            return 0  # 不启用约束
        
        return industry_config.get('max_same_industry', 2)
    
    def _load_config(self) -> Dict:
        """
        加载优化器配置（改进 1）
        
        Returns:
            Dict: 配置字典
        """
        # 尝试加载版本配置文件
        config_path = ROOT_DIR / 'optimizer_config.json'
        
        # v2 版本配置
        if hasattr(self, 'config_path') and self.config_path:
            config_path = Path(self.config_path)
        elif not config_path.exists():
            # 尝试 v2 配置
            v2_config = ROOT_DIR / 'versions/v2/config/optimizer_config.json'
            if v2_config.exists():
                config_path = v2_config
        
        if config_path.exists():
            try:
                with open(config_path, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception as e:
                logger.warning(f"[行业分散] 加载配置失败: {e}")
        
        return {}
    
    def _apply_industry_constraint(
        self,
        scored_stocks: List[Dict],
        max_same_industry: int = 2
    ) -> List[Dict]:
        """
        应用行业分散约束（改进 1）
        
        确保同行业的股票不超过指定数量
        
        Args:
            scored_stocks: 已打分的股票列表（按得分降序）
            max_same_industry: 同行业最多选股数（默认2）
            
        Returns:
            List[Dict]: 应用约束后的股票列表
        """
        # 行业计数器
        industry_count = {}
        selected_stocks = []
        
        for stock in scored_stocks:
            code = stock.get('code', '')
            industry = self._get_stock_industry(code)
            
            # 统计该行业已选股票数
            current_count = industry_count.get(industry, 0)
            
            if current_count < max_same_industry:
                # 该行业未超限，入选
                selected_stocks.append(stock)
                industry_count[industry] = current_count + 1
                
                logger.debug(f"[行业分散] {code} -> {industry} (第{current_count+1}只)")
            else:
                # 该行业已超限，跳过
                logger.debug(f"[行业分散] 跳过 {code} ({industry} 已有{current_count}只)")
        
        logger.info(f"[行业分散] 约束前 {len(scored_stocks)} 只 → 约束后 {len(selected_stocks)} 只")
        logger.info(f"[行业分散] 行业分布: {industry_count}")
        
        return selected_stocks
    
    def _get_stock_name(self, code: str) -> str:
        """获取股票名称（v3.4 优化：使用缓存）"""
        # 首次调用时构建缓存
        if self._stock_name_cache is None:
            self._stock_name_cache = {}
            if self.stock_info:
                for stock in self.stock_info:
                    # 同时缓存 code 和 asset 作为 key
                    stock_code = stock.get('code')
                    stock_asset = stock.get('asset')
                    stock_name = stock.get('name', stock_code or stock_asset)
                    if stock_code:
                        self._stock_name_cache[stock_code] = stock_name
                    if stock_asset:
                        self._stock_name_cache[stock_asset] = stock_name
        
        return self._stock_name_cache.get(code, code)
    
    def _get_price_history(self, code: str, days: int = 20) -> List[Dict]:
        """获取股票近 N 日价格历史"""
        if self.factor_df is None:
            return []
        
        stock_df = self.factor_df[self.factor_df['asset'] == code].tail(days)
        
        history = []
        for _, row in stock_df.iterrows():
            history.append({
                'date': row['date'],
                'close': round(row.get('close', 0), 2),
                'open': round(row.get('open', 0), 2),
                'high': round(row.get('high', 0), 2),
                'low': round(row.get('low', 0), 2)
            })
        
        return history
    
    def get_stock_price(self, code: str, date: str) -> Optional[float]:
        """公开方法：获取股票在指定日期的价格
        
        供 portfolio_tracker.py 调用，封装私有方法并添加错误处理
        
        v3.10 修复：增加最近交易日收盘价 fallback
        - 历史价格：从 factor_df 缓存获取
        - 今日价格：优先实时 API，失败时使用最近交易日收盘价
        
        Args:
            code: 股票代码（如 '600182'）
            date: 日期字符串（如 '2025-10-14'）
            
        Returns:
            float: 股票价格，获取失败返回 None
        """
        try:
            self._ensure_data_loaded()  # 懒加载
            
            # 构建价格缓存（如果未构建）- 向量化优化（280x faster）
            if self._price_cache is None and self.factor_df is not None:
                # 使用向量化构建，避免 iterrows 性能问题（云汐排查报告）
                self._price_cache = dict(
                    zip(zip(self.factor_df['date'], self.factor_df['asset']),
                        self.factor_df['close'])
                )
            
            # 先从缓存获取历史价格
            price = self._get_stock_price(code, date)
            
            # 如果缓存未命中，尝试实时获取今日价格
            if price == 0.0:
                # 判断是否是今天
                from datetime import datetime
                today_str = datetime.now().strftime('%Y-%m-%d')
                
                if date == today_str:
                    # 尝试新浪实时 API
                    price = self._get_sina_price(code)
                    if price and price > 0:
                        logger.info(f"[价格查询] {code} 新浪实时价格: {price}")
                        return price
                    
                    # 新浪 API 失败，使用最近交易日收盘价作为 fallback
                    latest_price = self._get_latest_price(code)
                    if latest_price and latest_price > 0:
                        logger.info(f"[价格查询] {code} 使用最近交易日收盘价: {latest_price}")
                        return latest_price
                    
                    logger.warning(f"[价格查询] {code} 无法获取今日价格")
                    return None
                
                return None
            
            return price
        except Exception as e:
            logger.warning(f"[价格查询] 获取 {code} 在 {date} 的价格失败: {e}")
            return None
    
    def _get_latest_price(self, code: str) -> Optional[float]:
        """获取股票最近交易日的收盘价（fallback 方案）
        
        当今日实时价格无法获取时，使用最近交易日的收盘价作为替代
        
        Args:
            code: 股票代码
            
        Returns:
            float: 最近交易日收盘价，获取失败返回 None
        """
        try:
            if self.factor_df is None or len(self.factor_df) == 0:
                return None
            
            # 获取该股票的所有记录
            stock_data = self.factor_df[self.factor_df['asset'] == code]
            
            if len(stock_data) == 0:
                return None
            
            # 按日期降序排序，获取最近的一条记录
            latest_row = stock_data.sort_values('date', ascending=False).iloc[0]
            latest_price = latest_row.get('close')
            
            if latest_price and latest_price > 0:
                return float(latest_price)
            
            return None
        except Exception as e:
            logger.debug(f"[最近价格] {code} 获取失败: {e}")
            return None
    
    def _get_sina_price(self, code: str) -> Optional[float]:
        """从新浪财经 API 获取实时价格
        
        新浪财经 API 可以获取当前最新价格（收盘或实时）
        
        Args:
            code: 股票代码（如 '600182'）
            
        Returns:
            float: 实时价格，获取失败返回 None
        """
        try:
            import requests
            
            # 新浪财经 API 格式：sh600182 或 sz000001
            if code.startswith('6'):
                symbol = f"sh{code}"
            else:
                symbol = f"sz{code}"
            
            url = f"https://hq.sinajs.cn/list={symbol}"
            headers = {
                'User-Agent': 'Mozilla/5.0',
                'Referer': 'https://finance.sina.com.cn/'
            }
            
            response = requests.get(url, headers=headers, timeout=5)
            response.raise_for_status()
            
            # 解析返回数据
            # 格式：var hq_str_sh600182="...";
            text = response.text
            if f"hq_str_{symbol}" in text:
                # 提取数据部分
                data_str = text.split('="')[1].split('"')[0]
                if data_str:
                    # 数据格式：名称,今开,昨收,当前,最高,最低,...
                    fields = data_str.split(',')
                    if len(fields) >= 4:
                        current_price = fields[3]  # 当前价格
                        if current_price and current_price != '0':
                            return float(current_price)
            
            return None
        except Exception as e:
            logger.debug(f"[实时价格] {code} 新浪获取失败: {e}")
            return None
    
    def _get_stock_price(self, code: str, date: str) -> float:
        """获取股票在指定日期的价格（v3.4 优化：使用缓存）
        
        优先从缓存获取，缓存未命中则从DataFrame查询
        """
        # 优先使用缓存
        if self._price_cache is not None:
            return float(self._price_cache.get((date, code), 0.0))
        
        # 缓存未构建时，从DataFrame查询（兼容旧逻辑）
        if self.factor_df is None:
            return 0.0
        
        row = self.factor_df[
            (self.factor_df['date'] == date) &
            (self.factor_df['asset'] == code)
        ]
        
        if len(row) > 0:
            return float(row.iloc[0].get('close', 0))
        return 0.0
    
    def run_backtest(
        self,
        start_date: str,
        end_date: str,
        weights: Dict[str, float],
        top_n: int = 10,
        cost: float = 0.0008,  # 万分之八印花税（用户实际成本）
        slippage: float = 0.0,  # 无滑点（用户实际成本）
        normalize_method: str = 'quantile',
        score_function: str = 'sigmoid',
        k_value: float = 10,
        progress_callback: callable = None
    ) -> Dict:
        """
        运行回测
        
        Args:
            start_date: 开始日期
            end_date: 结束日期
            weights: 因子权重
            top_n: 每日选股数量
            cost: 交易成本（双边）
            slippage: 滑点
            normalize_method: 标准化方法 ('quantile', 'minmax')
            score_function: 打分函数 ('sigmoid', 'linear')
            k_value: Sigmoid k 参数
            progress_callback: 进度回调函数
            
        Returns:
            回测结果字典
        """
        self._ensure_data_loaded()  # 懒加载
        
        if self.factor_df is None:
            return {'success': False, 'error': '数据未加载'}
        
        # 确保收益数据可用
        if self.return_df is None and self._return_col not in self.factor_df.columns:
            return {'success': False, 'error': '收益数据不可用'}
        
        # 获取日期范围
        dates = [d for d in self.available_dates if start_date <= d <= end_date]
        
        if len(dates) == 0:
            return {'success': False, 'error': '日期范围内无数据'}
        
        print(f"[回测] 开始回测，日期范围: {dates[0]} ~ {dates[-1]}, 共 {len(dates)} 天")
        
        # 准备收益数据
        if self._return_col not in self.factor_df.columns:
            # 合并收益数据
            self.factor_df = self.factor_df.merge(
                self.return_df[['date', 'asset', self._return_col]],
                on=['date', 'asset'],
                how='left'
            )
        
        # 模拟交易
        nav = 1.0  # 初始净值
        nav_series = [{'date': dates[0], 'nav': nav}]
        
        holdings = set()  # 当前持仓
        trade_details = []  # 交易详情记录（时间坐标轴可视化）
        
        for i, date in enumerate(dates[:-1]):  # 最后一天无法计算收益
            # 计算当日得分
            result = self.calculate_scores(
                date=date,
                weights=weights,
                normalize_method=normalize_method,
                score_function=score_function,
                k_value=k_value,
                top_n=top_n
            )
            
            if not result['success']:
                continue
            
            # 新选股
            new_selections = {s['code'] for s in result['selections']}
            
            # 计算换仓成本
            if holdings:
                to_sell = holdings - new_selections
                to_buy = new_selections - holdings
                
                # 记录卖出交易详情
                for code in to_sell:
                    stock_name = self._get_stock_name(code)
                    # 获取卖出价格（当日收盘价）
                    sell_price = self._get_stock_price(code, date)
                    trade_details.append({
                        'trade_id': f"trade_{date}_{code}_sell",
                        'trade_date': date,
                        'trade_time': '14:00',  # 默认收盘时间
                        'code': code,
                        'name': stock_name,
                        'action': 'sell',
                        'quantity': 100,  # 默认股数
                        'price': sell_price,
                        'amount': round(sell_price * 100, 2),
                        'nav_point_index': i,  # 对应净值曲线数据点的索引
                        'strategy': '多因子打分',
                        'reason': '换仓卖出'
                    })
                
                # 记录买入交易详情
                for code in to_buy:
                    stock_name = self._get_stock_name(code)
                    # 获取买入价格（当日收盘价）
                    buy_price = self._get_stock_price(code, date)
                    trade_details.append({
                        'trade_id': f"trade_{date}_{code}_buy",
                        'trade_date': date,
                        'trade_time': '10:00',  # 默认开盘时间
                        'code': code,
                        'name': stock_name,
                        'action': 'buy',
                        'quantity': 100,
                        'price': buy_price,
                        'amount': round(buy_price * 100, 2),
                        'nav_point_index': i,
                        'strategy': '多因子打分',
                        'reason': '换仓买入'
                    })
                
                # 换仓成本（双边）
                turnover_ratio = len(to_sell) + len(to_buy)
                trade_cost = turnover_ratio * cost * nav
                nav -= trade_cost
            
            # 更新持仓
            holdings = new_selections
            
            # 计算下一日收益
            next_date = dates[i + 1]
            next_returns = self.factor_df[
                (self.factor_df['date'] == next_date) &
                (self.factor_df['asset'].isin(holdings))
            ]
            
            if len(next_returns) > 0:
                avg_return = next_returns[self._return_col].mean()
                nav *= (1 + avg_return - slippage)
            
            nav_series.append({'date': next_date, 'nav': round(nav, 4)})
            
            # 进度回调
            if progress_callback:
                progress_callback(i + 1, len(dates) - 1, date, nav)
        
        # 计算回测指标
        returns = [n['nav'] / nav_series[i]['nav'] - 1 for i, n in enumerate(nav_series[1:]) if nav_series[i]['nav'] > 0]
        
        if not returns:
            return {
                'success': True,
                'nav_series': nav_series,
                'metrics': {},
                'message': '回测完成，但无有效收益数据'
            }
        
        # 年化收益
        total_days = len(nav_series)
        annual_return = (nav - 1) * (252 / total_days) if total_days > 0 else 0
        
        # 夏普比率
        avg_daily_return = np.mean(returns)
        std_daily_return = np.std(returns)
        sharpe = avg_daily_return / std_daily_return * np.sqrt(252) if std_daily_return > 0 else 0
        
        # 最大回撤
        peak = max(n['nav'] for n in nav_series)
        trough = min(n['nav'] for n in nav_series)
        max_drawdown = (trough - peak) / peak if peak > 0 else 0
        
        # 胜率
        positive_days = sum(1 for r in returns if r > 0)
        win_rate = positive_days / len(returns) if returns else 0
        
        return {
            'success': True,
            'nav_series': nav_series,
            'trade_details': trade_details,  # 新增：交易详情（用于时间坐标轴可视化）
            'metrics': {
                'annual_return': round(annual_return * 100, 2),
                'sharpe_ratio': round(sharpe, 2),
                'max_drawdown': round(max_drawdown * 100, 2),
                'win_rate': round(win_rate * 100, 2),
                'total_days': total_days,
                'final_nav': round(nav, 4),
                'total_trades': len(trade_details),  # 新增：总交易次数
                'buy_count': sum(1 for t in trade_details if t['action'] == 'buy'),
                'sell_count': sum(1 for t in trade_details if t['action'] == 'sell')
            },
            'params': {
                'start_date': start_date,
                'end_date': end_date,
                'weights': weights,
                'top_n': top_n,
                'cost': cost,
                'slippage': slippage
            }
        }
    
    def run_backtest_vectorized(
        self,
        start_date: str,
        end_date: str,
        weights: Dict[str, float],
        top_n: int = 10,
        cost: float = 0.0008,  # 万分之八印花税（用户实际成本）
        slippage: float = 0.0,  # 无滑点（用户实际成本）
        normalize_method: str = 'quantile',
        score_function: str = 'sigmoid',
        k_value: float = 10,
        progress_callback: callable = None,
        factor_directions: Dict[str, str] = None,  # 已废弃：保留参数兼容性，权重符号由优化器决定
        industry_constraint: Dict = None  # v3 新增：行业约束配置
    ) -> Dict:
        """
        运行向量化回测（性能优化版）
        
        核心优化：
        1. 使用 df.groupby('date')[factor].rank(pct=True) 向量化计算得分
        2. 使用 groupby.apply 批量选股
        3. 避免逐日循环，性能提升 10x+
        
        v3 行业约束改进（云舟实施）：
        - 预加载行业信息（批量获取，避免循环调用）
        - 两阶段选股：候选池 top_n * 3 → 行业约束 → 最终 top_n
        - 降级处理：行业数据缺失时跳过约束 + 日志告警
        
        Args:
            start_date: 开始日期
            end_date: 结束日期
            weights: 因子权重
            top_n: 每日选股数量
            cost: 交易成本（双边）
            slippage: 滑点
            normalize_method: 标准化方法 ('quantile', 'minmax')
            score_function: 打分函数 ('sigmoid', 'linear') - 向量化模式下保留参数兼容性
            k_value: Sigmoid k 参数 - 向量化模式下保留参数兼容性
            progress_callback: 进度回调函数
            factor_directions: 已废弃 - 保留参数兼容性，权重符号由优化器决定
            industry_constraint: 行业约束配置 {'enabled': bool, 'max_same_industry': int}
            
        Returns:
            回测结果字典（与 run_backtest 格式兼容）
        """
        self._ensure_data_loaded()
        
        if self.factor_df is None:
            return {'success': False, 'error': '数据未加载'}
        
        # 确保收益数据可用
        if self.return_df is None and self._return_col not in self.factor_df.columns:
            return {'success': False, 'error': '收益数据不可用'}
        
        # 获取日期范围
        dates = [d for d in self.available_dates if start_date <= d <= end_date]
        
        if len(dates) == 0:
            return {'success': False, 'error': '日期范围内无数据'}
        
        print(f"[向量化回测] 开始回测，日期范围: {dates[0]} ~ {dates[-1]}, 共 {len(dates)} 天")
        
        if progress_callback:
            progress_callback(10, '正在准备数据...')
        
        # 准备收益数据
        if self._return_col not in self.factor_df.columns:
            self.factor_df = self.factor_df.merge(
                self.return_df[['date', 'asset', self._return_col]],
                on=['date', 'asset'],
                how='left'
            )
        
        if progress_callback:
            progress_callback(20, '正在向量化计算得分...')
        
        # ========== 向量化计算得分 ==========
        
        # 权重归一化（使用绝对值，保持权重符号不变）
        # 修复：之前使用 sum(weights.values()) 会在权重全负时导致符号反转
        # 现在使用 sum(abs(w)) 归一化，保持优化器输出的权重符号
        total_weight = sum(abs(w) for w in weights.values())
        if total_weight == 0:
            return {'success': False, 'error': '权重总和为0'}
        norm_weights = {k: v / total_weight for k, v in weights.items()}
        
        # P5 权重调整已移除（v1 Revision 4）
        # 原因：优化器已经根据 IC 方向正确设置了权重符号
        # 归一化使用绝对值，保持了权重符号的正确性
        # 无需二次反转，避免逻辑混乱
        
        # 因子字段映射（使用类定义的映射）
        factor_columns = {
            'rsi': 'rsi_6',
            'kdj_j': 'kdj_j',
            'bollinger_pb': 'bollinger_pb',
            'volume_ratio': 'volume_ratio_5',
            'turnover_surge': 'turnover_surge',
            'return_3d': 'return_3d'
        }
        
        # 只使用实际存在的因子列
        available_factors = {}
        for factor_name, factor_col in factor_columns.items():
            if factor_col in self.factor_df.columns:
                available_factors[factor_name] = factor_col
            elif factor_name in weights:
                print(f"  [提示] 因子 {factor_name} 数据缺失，跳过")
        
        factor_columns = available_factors
        
        # 创建得分 DataFrame
        score_df = self.factor_df[['date', 'asset']].copy()
        
        # v3.5 修复：导入 Decimal 用于类型转换
        from decimal import Decimal
        
        # 向量化计算各因子得分
        for factor_name, factor_col in factor_columns.items():
            weight = norm_weights.get(factor_name, 0)
            
            if weight == 0 or factor_col not in self.factor_df.columns:
                continue
            
            # 获取原始因子数据
            factor_data = self.factor_df[factor_col]
            
            # v3.5 修复：先将 Decimal 类型转换为 float
            if factor_data.dtype == object:
                if any(isinstance(v, Decimal) for v in factor_data.dropna()):
                    factor_data = factor_data.apply(lambda x: float(x) if isinstance(x, Decimal) else x)
            
            # v3 bugfix：防御性检查 - 确保 date 字段存在
            if 'date' not in self.factor_df.columns:
                raise ValueError("[引擎] factor_df 缺少 'date' 字段，数据加载可能失败")
            
            # 向量化标准化（按日期分组）
            if normalize_method == 'quantile':
                # 使用 groupby.rank(pct=True) 向量化计算排名百分比
                norm_values = factor_data.groupby(self.factor_df['date']).rank(pct=True)
            elif normalize_method == 'minmax':
                # v3.5 修复：minmax 标准化，使用 float 类型避免 Decimal 错误
                date_groups = factor_data.groupby(self.factor_df['date'])
                min_vals = date_groups.transform('min').astype(float)
                max_vals = date_groups.transform('max').astype(float)
                range_vals = max_vals - min_vals
                range_vals = range_vals.replace(0, 1.0)
                norm_values = (factor_data.astype(float) - min_vals) / range_vals
            elif normalize_method == 'zscore':
                # v3.5 修复：zscore 标准化，使用 float 类型避免 Decimal 错误
                date_groups = factor_data.groupby(self.factor_df['date'])
                mean_vals = date_groups.transform('mean').astype(float)
                std_vals = date_groups.transform('std').astype(float)
                std_vals = std_vals.replace(0, 1.0)  # 避免除零
                z = (factor_data.astype(float) - mean_vals) / std_vals
                norm_values = 1 / (1 + np.exp(-z))  # sigmoid 映射到 0-1
            else:
                # 默认使用 quantile
                norm_values = factor_data.groupby(self.factor_df['date']).rank(pct=True)
            
            # 反向因子反转
            if factor_name in self.REVERSE_FACTORS:
                norm_values = 1 - norm_values
            
            # v3.5 修复：实际应用 score_function 和 k_value
            # 打分（向量化）
            if score_function == 'sigmoid':
                # 向量化 sigmoid 计算
                score_values = 1 / (1 + np.exp(-k_value * (norm_values - 0.5)))
            else:
                # linear 打分：直接使用标准化值
                score_values = norm_values
            
            # 加权得分
            score_df[f'{factor_name}_score'] = score_values * weight * 100
        
        # 计算综合得分
        score_cols = [c for c in score_df.columns if c.endswith('_score')]
        score_df['total_score'] = score_df[score_cols].sum(axis=1, skipna=True)
        score_df['total_score'] = score_df['total_score'].fillna(0)
        
        if progress_callback:
            progress_callback(40, '正在向量化选股...')
        
        # ========== v3 行业约束改进（云舟实施） ==========
        
        # 解析行业约束配置
        enabled = industry_constraint.get('enabled', True) if industry_constraint else True
        max_same_industry = industry_constraint.get('max_same_industry', 2) if industry_constraint else 2
        
        # ========== 关键改进1: 预加载行业信息 ==========
        if enabled and 'industry' not in score_df.columns:
            logger.info("[行业约束] 开始预加载行业信息...")
            
            # 批量获取行业信息，避免循环调用 _get_stock_industry
            unique_assets = score_df['asset'].unique()
            industry_map = {}
            missing_industry_assets = []
            
            for asset in unique_assets:
                industry = self._get_stock_industry(asset)
                if industry and industry != '未知':
                    industry_map[asset] = industry
                else:
                    missing_industry_assets.append(asset)
            
            # 映射到 DataFrame
            score_df['industry'] = score_df['asset'].map(industry_map)
            
            # 日志记录缺失情况
            if missing_industry_assets:
                logger.warning(f"[行业约束] 行业数据缺失股票数: {len(missing_industry_assets)}")
            
            logger.info(f"[行业约束] 预加载完成，有效行业数: {len(industry_map)}")
        
        # ========== 两阶段选股函数 ==========
        def get_top_n_with_industry_constraint(group, top_n, max_same_industry, enabled):
            """两阶段选股：候选池 top_n * 3 → 行业约束 → 最终 top_n"""
            
            # 预定义预期列结构，确保返回格式一致
            expected_columns = ['date', 'asset', 'total_score', 'industry']
            
            # 行业约束未启用或阈值为0时，直接按得分选股
            if not enabled or max_same_industry <= 0:
                result = group.nlargest(top_n, 'total_score')
                if result.empty:
                    return pd.DataFrame(columns=expected_columns)
                return result.copy()
            
            # ========== 关键改进2: 候选池大小 = top_n * 3 ==========
            candidate_pool_size = min(top_n * 3, len(group))
            candidates = group.nlargest(candidate_pool_size, 'total_score')
            
            # ========== 关键改进3: 降级处理 ==========
            # 行业数据缺失时跳过约束，按得分排序选股
            if 'industry' not in candidates.columns or candidates['industry'].isna().all():
                logger.warning(f"[行业约束] 行业数据缺失，降级为纯得分选股")
                result = candidates.nlargest(top_n, 'total_score')
                if result.empty:
                    return pd.DataFrame(columns=expected_columns)
                return result.copy()
            
            # v3 bugfix（云舟修复 2026-05-01）：
            # groupby.apply() 内部 pandas 排除分组键列，row.to_dict() 不含 date
            # 使用 group.name 获取分组键值，手动添加 date
            group_date = group.name
            
            selected = []
            industry_count = {}
            
            for _, row in candidates.iterrows():
                if len(selected) >= top_n:
                    break
                
                industry = row.get('industry')
                row_dict = row.to_dict()
                row_dict['date'] = group_date  # 手动添加 date
                
                # 降级处理：行业缺失的股票直接入选
                if pd.isna(industry) or not industry or industry == '未知':
                    selected.append(row_dict)
                    continue
                
                current_count = industry_count.get(industry, 0)
                if current_count < max_same_industry:
                    selected.append(row_dict)
                    industry_count[industry] = current_count + 1
            
            # v3 bugfix（云舟修复 2026-05-01）：
            # 确保返回的 DataFrame 总是包含正确的列结构
            # 修复 groupby 后 date 列丢失问题
            if not selected:
                return pd.DataFrame(columns=expected_columns)
            
            # 使用 pd.DataFrame(selected) 可能导致列顺序问题，显式重建确保格式
            result_df = pd.DataFrame(selected)
            # 确保所有预期列存在
            for col in expected_columns:
                if col not in result_df.columns:
                    result_df[col] = None
            return result_df[expected_columns]
        
        # 按日期分组，取 Top N（应用行业约束）
        # pandas 3.0 兼容性修复：
        # - group_keys=True 保留 date 在索引
        # - include_groups=False 排除分组键列传入函数（pandas 3.0 要求）
        # - 函数内部手动添加 date 列，所以 reset_index 用 drop=True 丢弃索引
        selected_df = score_df.groupby('date', group_keys=True).apply(
            lambda g: get_top_n_with_industry_constraint(g, top_n, max_same_industry, enabled),
            include_groups=False
        ).reset_index(drop=True)
        
        # v3 bugfix（云舟修复 2026-05-01）：
        # 防御性检查：空结果时跳过排名计算
        # 注意：修复了 get_top_n_with_industry_constraint 确保返回格式正确
        # 移除了错误的 'date' not in 检查（groupby 后 date 列应保留）
        if selected_df.empty:
            logger.warning("[回测] 行业约束过滤后无有效数据，跳过排名计算")
            return selected_df
        
        # 添加排名
        rank_values = selected_df.groupby('date')['total_score'].rank(
            ascending=False, method='first'
        )

        # 检查 NaN 来源 - 如果有 NaN 说明数据异常
        nan_count = rank_values.isna().sum()
        if nan_count > 0:
            # 记录详细日志帮助排查
            nan_dates = selected_df[rank_values.isna()]['date'].unique().tolist()
            logger.warning(f"[回测] 发现 {nan_count} 个 NaN 排名值，涉及日期: {nan_dates[:5]}...")
            # 过滤掉 NaN 行（这些是异常数据）
            valid_mask = rank_values.notna()
            selected_df = selected_df[valid_mask].copy()
            rank_values = rank_values[valid_mask]  # 显式对齐索引

            # 边界检查：过滤后可能为空
            if selected_df.empty:
                logger.warning("[回测] 过滤 NaN 后无有效数据")
                return selected_df

        selected_df['rank'] = rank_values.astype(int)
        
        if progress_callback:
            progress_callback(60, '正在计算收益...')
        
        # ========== 计算净值曲线 ==========
        
        # v3.10 多周期修复：动态计算持仓周期
        holdings_days = 1  # 默认 T+1
        if self._return_col == 'forward_return_3d':
            holdings_days = 3
        elif self._return_col == 'forward_return_5d':
            holdings_days = 5
        
        # 创建日期映射（T -> T+holdings_days）
        date_to_next = {}
        for i, date in enumerate(self.available_dates):
            target_idx = i + holdings_days
            if target_idx < len(self.available_dates):
                date_to_next[date] = self.available_dates[target_idx]
        
        # 筛选范围内的选股结果
        selected_in_range = selected_df[selected_df['date'].isin(dates)].copy()
        
        # 添加下一日日期
        selected_in_range['next_date'] = selected_in_range['date'].map(date_to_next)
        
        # v3.10 多周期修复：
        # forward_return 数据的 date 字段是"选股日期"，而不是"卖出日期"
        # T 日选股 -> forward_return_xd = T+x 日卖出时的收益
        # 因此应该用 date 匹配，而不是 next_date
        
        # v3 bugfix：防御性检查 - 确保必需字段存在
        required_cols = ['date', 'asset', self._return_col]
        missing_cols = [c for c in required_cols if c not in self.factor_df.columns]
        if missing_cols:
            raise ValueError(f"[引擎] factor_df 缺少字段: {missing_cols}")
        
        return_data = self.factor_df[['date', 'asset', self._return_col]].copy()
        selected_in_range = selected_in_range.merge(
            return_data,
            on=['date', 'asset'],
            how='left'
        )
        
        if progress_callback:
            progress_callback(80, '正在计算净值...')
        
        # 按日期分组计算每日平均收益（T日选股的收益）
        daily_returns = selected_in_range.groupby('date')[self._return_col].mean()
        daily_returns = daily_returns.dropna().sort_index()
        
        # 构建收益实现映射：T日选股 -> T+x日收益实现
        # forward_return_xd 是 T+x 日的收益，应该在 T+x 日更新到 NAV
        return_realization = {}  # {实现日: 收益值}
        for selection_date in daily_returns.index:
            # 找到收益实现日（T+x日）
            if selection_date in self.available_dates:
                idx = self.available_dates.index(selection_date)
                realization_idx = idx + holdings_days
                if realization_idx < len(self.available_dates):
                    realization_date = self.available_dates[realization_idx]
                    return_realization[realization_date] = daily_returns[selection_date]
        
        # 计算净值曲线
        nav = 1.0
        nav_series = [{'date': dates[0], 'nav': nav}]
        
        holdings = set()
        trade_details = []  # 交易详情记录（时间坐标轴可视化）
        
        # v3.4 性能优化：预先构建价格缓存，避免循环内重复过滤DataFrame
        if self._price_cache is None:
            if progress_callback:
                progress_callback(82, '正在构建价格缓存...')
            self._price_cache = {}
            if self.factor_df is not None:
                for _, row in self.factor_df[['date', 'asset', 'close']].iterrows():
                    key = (row['date'], row['asset'])
                    self._price_cache[key] = row['close']
        
        # 计算循环总数（用于进度回调）
        total_iterations = len(dates) - 1
        
        for i, date in enumerate(dates[:-1]):
            # v3.4 进度回调：80% -> 90%，每处理10%更新一次
            if progress_callback and total_iterations > 0:
                progress_percent = int(80 + (i / total_iterations) * 10)
                if i % max(1, total_iterations // 10) == 0 or i == total_iterations - 1:
                    progress_callback(progress_percent, f'正在计算净值... ({i+1}/{total_iterations})')
            
            if date not in daily_returns.index:
                continue
            
            # 当日选股
            current_selected = set(
                selected_in_range[selected_in_range['date'] == date]['asset'].tolist()
            )
            
            # 换仓成本
            if holdings and current_selected:
                to_sell = holdings - current_selected
                to_buy = current_selected - holdings
                
                # 记录卖出交易详情
                for code in to_sell:
                    stock_name = self._get_stock_name(code)
                    sell_price = self._get_stock_price(code, date)
                    trade_details.append({
                        'trade_id': f"trade_{date}_{code}_sell",
                        'trade_date': date,
                        'trade_time': '14:00',
                        'code': code,
                        'name': stock_name,
                        'action': 'sell',
                        'quantity': 100,
                        'price': sell_price,
                        'amount': round(sell_price * 100, 2),
                        'nav_point_index': i,
                        'strategy': '多因子打分',
                        'reason': '换仓卖出'
                    })
                
                # 记录买入交易详情
                for code in to_buy:
                    stock_name = self._get_stock_name(code)
                    buy_price = self._get_stock_price(code, date)
                    trade_details.append({
                        'trade_id': f"trade_{date}_{code}_buy",
                        'trade_date': date,
                        'trade_time': '10:00',
                        'code': code,
                        'name': stock_name,
                        'action': 'buy',
                        'quantity': 100,
                        'price': buy_price,
                        'amount': round(buy_price * 100, 2),
                        'nav_point_index': i,
                        'strategy': '多因子打分',
                        'reason': '换仓买入'
                    })
                
                turnover_ratio = (len(to_sell) + len(to_buy)) / top_n
                trade_cost = turnover_ratio * cost * nav
                nav -= trade_cost
            
            holdings = current_selected
            
            # 计算收益（只在收益实现日更新 NAV）
            # T日选股 -> T+x日收益实现
            if date in return_realization:
                avg_return = return_realization[date]
                if avg_return is not None and not pd.isna(avg_return):
                    nav *= (1 + avg_return - slippage)
            
            next_date = dates[i + 1] if i + 1 < len(dates) else date
            nav_series.append({'date': next_date, 'nav': round(nav, 4)})
        
        if progress_callback:
            progress_callback(90, '正在计算统计指标...')
        
        # ========== 计算回测指标 ==========
        
        returns = []
        for i in range(1, len(nav_series)):
            if nav_series[i-1]['nav'] > 0:
                r = nav_series[i]['nav'] / nav_series[i-1]['nav'] - 1
                returns.append(r)
        
        if not returns:
            return {
                'success': True,
                'nav_series': nav_series,
                'metrics': {},
                'message': '回测完成，但无有效收益数据'
            }
        
        # 年化收益
        total_days = len(nav_series)
        annual_return = (nav - 1) * (252 / total_days) if total_days > 0 else 0
        
        # 夏普比率
        avg_daily_return = np.mean(returns)
        std_daily_return = np.std(returns)
        sharpe = avg_daily_return / std_daily_return * np.sqrt(252) if std_daily_return > 0 else 0
        
        # 最大回撤
        peak = max(n['nav'] for n in nav_series)
        trough = min(n['nav'] for n in nav_series)
        max_drawdown = (trough - peak) / peak if peak > 0 else 0
        
        # 胜率
        positive_days = sum(1 for r in returns if r > 0)
        win_rate = positive_days / len(returns) if returns else 0
        
        # 最新选股明细
        latest_date = dates[-1]
        latest_selections = selected_in_range[
            selected_in_range['date'] == latest_date
        ].sort_values('rank')
        
        selections = []
        for _, row in latest_selections.iterrows():
            asset = row['asset']
            selections.append({
                'code': asset,
                'name': self._get_stock_name(asset),
                'rank': int(row['rank']),
                'total_score': round(row['total_score'], 2)
            })
        
        if progress_callback:
            progress_callback(100, '向量化回测完成')
        
        print(f"[向量化回测] 完成，年化收益: {annual_return*100:.2f}%，夏普: {sharpe:.2f}")
        
        return {
            'success': True,
            'nav_series': nav_series,
            'trade_details': trade_details,  # 新增：交易详情（用于时间坐标轴可视化）
            'metrics': {
                'annual_return': round(annual_return * 100, 2),
                'sharpe_ratio': round(sharpe, 2),
                'max_drawdown': round(max_drawdown * 100, 2),
                'win_rate': round(win_rate * 100, 2),
                'total_days': total_days,
                'final_nav': round(nav, 4),
                'total_trades': len(trade_details),  # 新增：总交易次数
                'buy_count': sum(1 for t in trade_details if t['action'] == 'buy'),
                'sell_count': sum(1 for t in trade_details if t['action'] == 'sell')
            },
            'selections': selections,
            'params': {
                'start_date': start_date,
                'end_date': end_date,
                'weights': weights,
                'top_n': top_n,
                'cost': cost,
                'slippage': slippage,
                'normalize_method': normalize_method,
                'vectorized': True
            }
        }


def load_factor_ic_data() -> Dict:
    """
    加载各因子的 IC/ICIR 数据
    
    Returns:
        因子 IC 数据字典
    """
    result = {}
    
    # IC 结果文件列表
    ic_files = {
        'rsi': 'factor_analysis_result.json',
        'kdj_j': 'kdj_j_analysis_result.json',
        'bollinger_pb': 'bollinger_pb_analysis_result.json',
        'volume_ratio': 'volume_ratio_analysis_result.json',
        'return_3d': 'return_3d_analysis_result.json',
        'turnover_surge': 'turnover_surge_analysis_result.json'
    }
    
    for factor_name, filename in ic_files.items():
        filepath = ROOT_DIR / filename
        if filepath.exists():
            try:
                with open(filepath, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                
                ic_metrics = data.get('ic_metrics', {})
                layered_result = data.get('layered_result', {})
                summary = layered_result.get('summary', {})
                
                result[factor_name] = {
                    'ic_mean': ic_metrics.get('ic_mean', 0),
                    'icir': ic_metrics.get('icir', 0),
                    'significance': ic_metrics.get('significance', ''),
                    'positive_ratio': ic_metrics.get('positive_ratio', 0),
                    'summary': ic_metrics.get('summary', ''),
                    't_stat': ic_metrics.get('t_stat', 0),
                    'n_days': ic_metrics.get('n_days', 0),
                    'n_assets': ic_metrics.get('n_assets', 0),
                    # 新增：多空收益数据
                    'long_short_return': summary.get('long_short_annual_return', 0),
                    'long_short_sharpe': summary.get('long_short_sharpe', 0),
                    'monotonicity_passed': summary.get('monotonicity_passed', False)
                }
            except Exception as e:
                print(f"加载 {factor_name} IC数据失败: {e}")
    
    return result


def calculate_smart_weights(
    ic_data: Dict = None,
    icir_weight: float = 0.5,
    ic_mean_weight: float = 0.3,
    long_short_weight: float = 0.2
) -> Tuple[Dict, Dict]:
    """
    计算智能权重（简便接口）
    
    Args:
        ic_data: 因子IC数据（可选，默认自动加载）
        icir_weight: ICIR权重（默认50%）
        ic_mean_weight: IC均值权重（默认30%）
        long_short_weight: 多空收益权重（默认20%）
        
    Returns:
        tuple: (weights_dict, quality_scores_dict)
    """
    if ic_data is None:
        ic_data = load_factor_ic_data()
    
    generator = get_smart_weight_generator()
    weights, raw_scores, factor_quality = generator.calculate_smart_weights(
        icir_weight=icir_weight,
        ic_mean_weight=ic_mean_weight,
        long_short_weight=long_short_weight
    )
    
    return weights, factor_quality


# 创建全局引擎实例（懒加载）
_engine_instance = None

# ========== v3.6 数据预加载缓存 ==========
# 全局缓存，避免每次回测重新加载 15s 数据
# v3.9 修复：周期键缓存，避免硬编码 forward_return_1d
ENGINE_CACHE = {}  # key: return_col, value: engine
CACHE_LOADED_SET = set()  # 已加载数据的周期集合

def get_engine() -> ScoringEngine:
    """获取全局引擎实例（单例，默认 T+1）"""
    global _engine_instance
    if _engine_instance is None:
        _engine_instance = ScoringEngine()
    return _engine_instance

def get_cached_engine(return_col: str = 'forward_return_1d', use_shared_cache: bool = False) -> ScoringEngine:
    """获取缓存的引擎实例（数据已预加载，支持多周期和共享缓存）
    
    v3.9 多周期修复（云舟实施）：
    - 支持周期键缓存：ENGINE_CACHE[return_col] = engine
    - 避免 T+3/T+5 使用硬编码的 T+1 引擎
    - 节省约 25 分钟（14.3% 提升）
    
    v3.10 引擎数据共享优化（云柏方案）：
    - use_shared_cache=True：使用共享因子数据（推荐用于多周期并行）
    - 内存节省：约720MB
    
    Args:
        return_col: 收益字段名（默认 forward_return_1d，支持 forward_return_3d/5d）
        use_shared_cache: 是否使用共享缓存（默认 False，仅在多周期并行时启用）
        
    Returns:
        ScoringEngine: 已加载数据的引擎实例（对应周期）
    """
    global ENGINE_CACHE, CACHE_LOADED_SET
    
    # 使用共享缓存键（避免周期键重复）
    cache_key = f"{return_col}_shared" if use_shared_cache else return_col
    
    # 周期键缓存：避免硬编码 forward_return_1d
    if cache_key not in ENGINE_CACHE:
        ENGINE_CACHE[cache_key] = ScoringEngine(return_col=return_col, use_shared_cache=use_shared_cache)
        logger.info(f"[缓存引擎] 创建新引擎实例（周期={return_col}, 共享缓存={use_shared_cache}）")
    
    # 确保数据已加载
    if cache_key not in CACHE_LOADED_SET:
        ENGINE_CACHE[cache_key]._ensure_data_loaded()
        CACHE_LOADED_SET.add(cache_key)
        logger.info(f"[缓存引擎] 数据预加载完成（周期={return_col}, 日期数={len(ENGINE_CACHE[cache_key].available_dates)}）")
    
    return ENGINE_CACHE[cache_key]

def preload_engine_data():
    """预加载引擎数据（供 Flask 启动时调用）
    
    v3.9 多周期修复：
    - 支持多周期预加载（T+1/T+3/T+5）
    - 在 Flask 应用启动时加载多个周期数据
    - 避免首次 API 调用时的长时间等待
    """
    global ENGINE_CACHE, CACHE_LOADED_SET
    
    # 默认预加载 T+1 周期
    default_return_col = 'forward_return_1d'
    
    if default_return_col not in CACHE_LOADED_SET:
        logger.info(f"[预加载] 开始预加载引擎数据（周期={default_return_col}）...")
        engine = get_cached_engine(return_col=default_return_col)
        logger.info(f"[预加载] 数据预加载完成，可用日期: {len(engine.available_dates)} 天")
    
    # 可选：预加载其他周期（T+3/T+5）
    # for return_col in ['forward_return_3d', 'forward_return_5d']:
    #     if return_col not in CACHE_LOADED_SET:
    #         logger.info(f"[预加载] 预加载周期 {return_col}...")
    #         get_cached_engine(return_col=return_col)


if __name__ == '__main__':
    # 测试引擎
    engine = get_engine()
    
    print(f"可用日期: {engine.get_available_dates()[:5]} ... {engine.get_available_dates()[-5:]}")
    print(f"最新日期: {engine.get_latest_date()}")
    
    # 测试计算得分
    result = engine.calculate_scores(
        date=engine.get_latest_date(),
        weights=engine.DEFAULT_WEIGHTS,
        top_n=10
    )
    
    if result['success']:
        print(f"\nTop 10 选股结果 ({result['date']}):")
        for i, stock in enumerate(result['selections'], 1):
            print(f"{i}. {stock['code']} - {stock['name']}: {stock['total_score']:.2f}")
    else:
        print(f"计算失败: {result['error']}")