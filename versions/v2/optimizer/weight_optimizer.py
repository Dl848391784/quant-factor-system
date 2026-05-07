#!/usr/bin/env python3
"""
权重优化搜索模块
作者: 云舟 🛠️
功能: 实现多因子权重网格搜索优化,寻找最优权重组合

P0 核心功能:
- 目标函数计算:基于6个因子IC数据计算组合ICIR
- 网格搜索算法:权重范围[-1,1],步长0.2
- 异步执行 + 早停机制(无改善10次终止)
- 记录历史最优解
"""

import json
import sys  # 进度日志 flush
import numpy as np
import pandas as pd
import threading
import time
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional, Tuple
import logging

# ========== 版本路径设置 ==========
ROOT_DIR = Path(__file__).parent.parent.parent.parent  # 指向 factor_ic_analyzer/ (optimizer → v2 → versions → factor_ic_analyzer)
sys.path.insert(0, str(ROOT_DIR))

# 配置日志
logging.basicConfig(level=logging.INFO, format='[权重优化] %(message)s')
logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).parent.parent  # 指向 versions/v2/
OPTIMIZER_DIR = Path(__file__).parent     # 指向 versions/v2/optimizer/
CONFIG_DIR = BASE_DIR / 'config'           # 指向 versions/v2/config/
DATA_CACHE_DIR = ROOT_DIR / 'cache'        # 指向 factor_ic_analyzer/cache/(共享数据)

# ==================== 全局优化状态 ====================
optimization_state = {
    'status': 'idle',  # idle, running, completed, error
    'task_id': None,
    'progress': {
        'current_iteration': 0,
        'total_iterations': 0,
        'percentage': 0,
        'current_best_icir': 0,
        'current_best_weights': {},
        'elapsed_seconds': 0,
        'estimated_remaining_seconds': 0
    },
    'result': None,
    'error': None,
    'start_time': None,
    'end_time': None,
    'history_best': []  # 历史最优解记录
}
optimization_lock = threading.Lock()

# 因子分析结果文件映射(剔除弱因子 KDJ_J)
FACTOR_RESULT_FILES = {
    'rsi': 'factor_analysis_result.json',
    'bollinger_pb': 'bollinger_pb_analysis_result.json',
    'volume_ratio': 'volume_ratio_analysis_result.json',
    'turnover_surge': 'turnover_surge_analysis_result.json',
    'return_3d': 'return_3d_analysis_result.json'  # 新增
}

# 因子名称映射
FACTOR_NAMES = {
    'rsi': 'RSI(14)',
    'bollinger_pb': '布林带%B',
    'volume_ratio': '量比',
    'turnover_surge': '换手率突增'
}

# ==================== v3: IC衰减补偿配置 ====================
# 分段衰减参数配置(基于实测数据)
LAMBDA_CONFIG = {
    1: 0.916,   # T+1: 快衰减(IC衰减60%/天)
    3: 0.288,   # T+3: 中衰减(IC衰减58%/3天)
    5: 0.163    # T+5: 慢衰减(IC衰减56%/5天)
}

def get_decay_factor(holding_days: int) -> float:
    """
    v3: 分段衰减因子

    基于实测数据的分段衰减参数:
    - T+1: IC衰减60%/天 → decay_factor=0.40
    - T+3: IC衰减58%/3天 → decay_factor=0.42
    - T+5: IC衰减56%/5天 → decay_factor=0.44

    公式: decay_factor = exp(-λ × holding_days)

    Args:
        holding_days: 持仓天数(1/3/5)

    Returns:
        float: 衰减因子 ∈ (0, 1)
    """
    λ = LAMBDA_CONFIG.get(holding_days, 0.288)  # 默认使用T+3参数
    decay_factor = np.exp(-λ * holding_days)
    return decay_factor

# 因子 IC 方向配置(动态计算版本)
# 'positive': ICIR>0,权重必须>=-tolerance(允许小范围反向)
# 'negative': ICIR<0,权重必须<=+tolerance(允许小范围正向)
# 'neutral': ICIR=0,无方向约束
#
# P2-修复: 动态方向判断
# - 根据因子的 ICIR 值动态决定方向
# - 解决 T+3/T+5 ICIR 为负但方向约束为 positive 的 Bug
#
# 保留 IC_DIRECTIONS 作为默认值(兼容旧代码)
IC_DIRECTIONS = {
    'rsi': 'positive',           # 默认值,实际使用时会动态计算
    'bollinger_pb': 'positive',  # 默认值,实际使用时会动态计算
    'volume_ratio': 'positive',  # 默认值,实际使用时会动态计算
    'turnover_surge': 'positive', # 默认值,实际使用时会动态计算
    'return_3d': 'neutral'        # 默认值,实际使用时会动态计算
}


def _fallback_compute_ic_directions_from_icir(ic_data: Dict, factors: List[str] = None) -> Dict[str, str]:
    """备用方向计算（仅当配置缺失时使用）
    
    ⚠️ 已废弃：不再在主流程中使用
    原因：循环依赖陷阱（ICIR为负 → 方向为negative → 权重为负）
    
    P2-修复(云汐根因分析):
    - T+3/T+5 周期下,因子 ICIR 可能为负
    - 如果 ICIR < 0,方向应为 negative
    - 如果 ICIR > 0,方向应为 positive
    - 如果 ICIR = 0,方向为 neutral(无约束)

    Args:
        ic_data: IC 数据字典 {factor_id: {'icir': float, ...}}
        factors: 因子列表(可选,默认使用 ic_data 的 keys)

    Returns:
        Dict[str, str]: {factor_id: 'positive' | 'negative' | 'neutral'}
    """
    if factors is None:
        factors = list(ic_data.keys()) if ic_data else []

    directions = {}
    for factor in factors:
        if factor not in ic_data:
            directions[factor] = 'neutral'
            continue

        icir = ic_data[factor].get('icir', 0)
        if icir is None:
            icir = 0

        if icir > 0:
            directions[factor] = 'positive'
        elif icir < 0:
            directions[factor] = 'negative'
        else:
            directions[factor] = 'neutral'

    return directions


class WeightOptimizer:
    """
    权重优化器

    实现网格搜索算法,寻找最优权重组合
    """

    def __init__(self, return_col: str = 'forward_return_1d', use_shared_cache: bool = False):
        """初始化优化器,加载因子IC数据(支持多周期)

        v3.12 多周期修复(云舟实施):
        - 添加 return_col 参数,支持 T+1/T+3/T+5
        - 动态计算 IC,避免硬编码 forward_return_1d
        
        v3.10 引擎数据共享优化(云柏方案):
        - use_shared_cache=True: 复用共享引擎的IC数据
        - 避免重复加载因子数据

        Args:
            return_col: 收益字段名(默认 forward_return_1d)
            use_shared_cache: 是否使用共享缓存(默认 False,仅在多周期并行时启用)
        """
        self._return_col = return_col
        self._use_shared_cache = use_shared_cache
        
        if use_shared_cache:
            # ========== v1 Revision 3 核心改进（云柏方案） ==========
            # 从共享缓存获取完整因子DataFrame（引用，不重新加载）
            from common.scoring_engine import SharedFactorDataCache
            
            # 确保缓存已加载
            if not SharedFactorDataCache.is_complete_factor_loaded():
                SharedFactorDataCache.preload_complete_factor_data()
            
            # 从缓存获取完整因子数据（引用）
            merged_df = SharedFactorDataCache.get_complete_factor_data()
            
            # 使用静态方法计算IC序列（基于共享数据）
            self.ic_data = WeightOptimizer._calculate_ic_from_shared_data_static(merged_df, return_col)
            self.common_dates = SharedFactorDataCache.get_available_dates_complete()
            
            logger.info("[优化器] 使用共享缓存，内存节省约700MB（周期=%s）" % return_col)
        else:
            # 原有逻辑（独立加载）
            self.ic_data = self._load_all_ic_series(return_col=return_col)
            self.common_dates = self._get_common_dates()

    
    @staticmethod
    def _calculate_ic_from_shared_data_static(merged_df: pd.DataFrame, return_col: str) -> Dict:
        """基于共享缓存数据计算IC序列（静态方法）
        
        v1 Revision 3 核心改进（云柏方案）：
        - 输入：共享缓存的完整因子DataFrame（引用）
        - 输出：IC序列数据（{factor_id: {dates, ic_values, icir}}）
        - 内存：不重新加载因子数据，只计算IC序列（轻量）
        
        Args:
            merged_df: 共享缓存的完整因子DataFrame
            return_col: 收益字段名（如 forward_return_1d）
            
        Returns:
            Dict: IC数据字典
        """
        from scipy.stats import spearmanr
        import numpy as np
        
        result = {}
        
        # 因子字段映射
        factor_columns = {
            'rsi': 'rsi_6',
            'bollinger_pb': 'bollinger_pb',
            'volume_ratio': 'volume_ratio_5',
            'turnover_surge': 'turnover_surge',
            'return_3d': 'return_3d'  # 使用 factor_data.json.gz 中的 return_3d
        }
        
        # 计算各因子IC
        for factor_id, col_name in factor_columns.items():
            if col_name not in merged_df.columns:
                logger.warning("[IC静态计算] 因子 %s 字段不存在，跳过" % factor_id)
                continue
            
            dates = sorted(merged_df['date'].unique())
            ic_values = []
            valid_dates = []
            
            for date in dates:
                day_data = merged_df[merged_df['date'] == date]
                valid_mask = day_data[col_name].notna() & day_data[return_col].notna()
                valid_data = day_data[valid_mask]
                
                if len(valid_data) < 10:
                    continue
                
                factor_series = valid_data.set_index('asset')[col_name]
                return_series = valid_data.set_index('asset')[return_col]
                
                try:
                    ic, p_value = spearmanr(factor_series.values, return_series.values)
                    if not pd.isna(ic):
                        ic_values.append(ic)
                        valid_dates.append(date)
                except:
                    continue
            
            # 计算IC指标
            if ic_values:
                ic_mean = np.mean(ic_values)
                ic_std = np.std(ic_values)
                icir = ic_mean / ic_std if ic_std > 0 else 0
                
                result[factor_id] = {
                    'dates': valid_dates,
                    'ic_values': ic_values,
                    'ic_mean': ic_mean,
                    'icir': icir,
                    'positive_ratio': sum(1 for ic in ic_values if ic > 0) / len(ic_values)
                }
                
                logger.info("[IC静态计算] 因子 %s: IC均值=%.4f, ICIR=%.4f" % (factor_id, ic_mean, icir))
        
        return result
    def calculate_factor_ic_correlation(self, factors: List[str]) -> Dict[str, float]:
        """
        P1-2: 计算因子 IC 相关性

        Args:
            factors: 因子列表

        Returns:
            Dict[str, float]: 因子对相关性 {f1_f2: correlation}
        """
        import numpy as np

        # 获取对齐后的 IC 值
        aligned_ic = {}
        for factor in factors:
            if factor in self.ic_data:
                ic_values = self.ic_data[factor].get('ic_values', [])
                if ic_values:
                    aligned_ic[factor] = ic_values

        if len(aligned_ic) < 2:
            return {}

        # 对齐长度
        min_len = min(len(v) for v in aligned_ic.values())
        for f in aligned_ic:
            aligned_ic[f] = aligned_ic[f][-min_len:]

        correlations = {}

        # 计算因子对的 IC 相关性
        factor_list = list(aligned_ic.keys())
        for i, f1 in enumerate(factor_list):
            for f2 in factor_list[i+1:]:
                ic1 = np.array(aligned_ic[f1])
                ic2 = np.array(aligned_ic[f2])

                # 计算 Pearson 相关性
                if len(ic1) > 0 and len(ic2) > 0:
                    correlation = np.corrcoef(ic1, ic2)[0, 1]
                    key = f"{f1}_{f2}"
                    correlations[key] = round(correlation, 4)
                    logger.info(f"P1-2: 因子相关性 {key} = {correlation:.4f}")

        return correlations

    def remove_correlated_factors(
        self,
        factors: List[str],
        threshold: float = 0.6,
        action: str = 'warn'
    ) -> List[str]:
        """
        P1-2: 剔除相关性过高的冗余因子

        Args:
            factors: 原始因子列表
            threshold: 相关性阈值(默认 0.6)
            action: 处理方式 ('warn' | 'remove')

        Returns:
            List[str]: 筛选后的因子列表
        """
        # 计算因子相关性
        correlations = self.calculate_factor_ic_correlation(factors)

        # 找出相关性超过阈值的因子对
        redundant_pairs = []
        for key, corr in correlations.items():
            if abs(corr) > threshold:
                redundant_pairs.append((key, corr))
                logger.warning(f"P1-2: 发现冗余因子对 {key}, 相关性={corr:.4f}")

        # 如果只是警告,返回原列表
        if action == 'warn':
            if redundant_pairs:
                logger.warning(f"P1-2: 发现 {len(redundant_pairs)} 个高相关性因子对,建议检查")
            return factors

        # 如果是剔除,根据 ICIR 决定保留哪个
        if action == 'remove':
            to_remove = set()
            for key, corr in redundant_pairs:
                parts = key.split('_')
                f1, f2 = parts[0], parts[1]

                # 比较 ICIR,保留 ICIR 更高的因子
                icir1 = self.ic_data.get(f1, {}).get('icir', 0)
                icir2 = self.ic_data.get(f2, {}).get('icir', 0)

                if icir1 >= icir2:
                    to_remove.add(f2)
                    logger.info(f"P1-2: 剔除因子 {f2}(ICIR={icir2:.4f} < {f1}={icir1:.4f}")
                else:
                    to_remove.add(f1)
                    logger.info(f"P1-2: 剔除因子 {f1}(ICIR={icir1:.4f} < {f2}={icir2:.4f}")

            filtered_factors = [f for f in factors if f not in to_remove]
            logger.info(f"P1-2: 因子筛选完成,原 {len(factors)} → 新 {len(filtered_factors)}")
            return filtered_factors

        return factors

    def apply_direction_constraints(
        self,
        weights: Dict[str, float],
        config: Dict
    ) -> Dict[str, float]:
        """
        应用方向约束(v2 改进)

        Args:
            weights: 权重字典
            config: 配置字典

        Returns:
            约束后的权重字典
        """
        direction_config = config.get('direction_constraints', {})

        if not direction_config.get('enabled', False):
            return weights

        strict_mode = direction_config.get('strict_mode', False)
        tolerance = direction_config.get('tolerance', 0.0)
        positive_factors = direction_config.get('positive_factors', [])
        negative_factors = direction_config.get('negative_factors', [])

        constrained_weights = weights.copy()

        for factor, weight in weights.items():
            if factor in positive_factors:
                # 正向因子:权重必须 >= -tolerance
                if weight < -tolerance:
                    if strict_mode:
                        constrained_weights[factor] = max(0.0, weight)
                    else:
                        constrained_weights[factor] = -tolerance
            elif factor in negative_factors:
                # 反向因子:权重必须 <= +tolerance
                if weight > tolerance:
                    if strict_mode:
                        constrained_weights[factor] = min(0.0, weight)
                    else:
                        constrained_weights[factor] = tolerance

        return constrained_weights

    def clean_data(
        self,
        df: pd.DataFrame,
        config: Dict
    ) -> pd.DataFrame:
        """
        数据清洗(v2 改进)

        Args:
            df: 原始数据
            config: 配置字典

        Returns:
            清洗后的数据
        """
        cleaning_config = config.get('data_cleaning', {})

        if not cleaning_config.get('enabled', False):
            return df

        df_clean = df.copy()

        # 1. 移除异常值
        if cleaning_config.get('remove_outliers', False):
            threshold = cleaning_config.get('outlier_threshold', 3.0)

            numeric_cols = df_clean.select_dtypes(include=[np.number]).columns

            for col in numeric_cols:
                mean = df_clean[col].mean()
                std = df_clean[col].std()

                # 标记异常值
                outlier_mask = (df_clean[col] > mean + threshold * std) | \
                              (df_clean[col] < mean - threshold * std)

                # 替换异常值为边界值
                df_clean.loc[outlier_mask, col] = np.clip(
                    df_clean.loc[outlier_mask, col],
                    mean - threshold * std,
                    mean + threshold * std
                )

        # 2. 填充缺失值
        fill_method = cleaning_config.get('fill_missing', 'forward_fill')

        if fill_method == 'forward_fill':
            df_clean = df_clean.fillna(method='ffill')
        elif fill_method == 'backward_fill':
            df_clean = df_clean.fillna(method='bfill')
        elif fill_method == 'mean':
            df_clean = df_clean.fillna(df_clean.mean())

        # 3. 检查数据覆盖率
        min_coverage = cleaning_config.get('min_data_coverage', 0.8)
        coverage = df_clean.notna().sum().min() / len(df_clean)

        if coverage < min_coverage:
            logger.warning(f"数据覆盖率 {coverage:.2%} 低于最小要求 {min_coverage:.2%}")

        return df_clean

    def _load_all_ic_series(self, return_col: str = 'forward_return_1d') -> Dict:
        """加载所有因子的IC序列数据(统一动态计算)

        v3.13 IC计算统一修复(云舟实施):
        - 所有周期(T+1/T+3/T+5)统一使用动态计算
        - 确保 ICIR 跨周期一致,避免最优周期选择偏差
        - 废弃 T+1 缓存加载(_load_ic_from_files)

        Args:
            return_col: 收益字段名(如 forward_return_1d/3d/5d)

        Returns:
            Dict: {factor_id: {'dates': [...], 'ic_values': [...], 'ic_mean': float, 'icir': float}}
        """
        logger.info(f"[统一IC计算] 动态计算 IC(周期={return_col})")
        return self._calculate_ic_dynamically(return_col)

    def _load_factor_data_complete(self) -> pd.DataFrame:
        """加载完整因子数据(包含所有因子字段)

        v3.14 IC计算统一修复(云舟实施):
        - 从 factor_data.json.gz 加载基础因子(rsi_6, volume_ratio_5)
        - 从 bollinger_pb_history.json.gz 加载布林带 %B 原始数据并合并
        - 从 turnover_rate_data.json.gz 加载换手率数据并计算 turnover_surge
        - 从 return_data.json.gz 加载 forward_return_1d/3d/5d
        - 合并所有因子数据

        Returns:
            pd.DataFrame: 包含所有因子字段的数据表
        """
        import gzip
        import pandas as pd

        # 1. 加载基础因子数据
        factor_filepath = DATA_CACHE_DIR / 'factor_data/factor_data.json.gz'
        with gzip.open(factor_filepath, 'rt', encoding='utf-8') as f:
            factor_data = json.load(f).get('data', [])
        factor_df = pd.DataFrame(factor_data)
        logger.info(f"[完整因子加载] 基础因子数据: {len(factor_df)} 条")

        # 2. 加载布林带 %B 原始因子数据并合并
        bollinger_filepath = ROOT_DIR / 'cache/bollinger_pb/bollinger_pb_history.json.gz'
        if bollinger_filepath.exists():
            with gzip.open(bollinger_filepath, 'rt', encoding='utf-8') as f:
                bollinger_data = json.load(f).get('data', [])
            bollinger_df = pd.DataFrame(bollinger_data)
            # 只保留需要的字段
            bollinger_df = bollinger_df[['date', 'asset', 'bollinger_pb']]
            # 合并到 factor_df
            factor_df = factor_df.merge(bollinger_df, on=['date', 'asset'], how='left')
            # 过滤掉 None 值
            factor_df['bollinger_pb'] = factor_df['bollinger_pb'].replace([None], np.nan)
            logger.info(f"[完整因子加载] 布林带 %B 数据已合并: 有效记录 {factor_df['bollinger_pb'].notna().sum()} 条")
        else:
            logger.warning(f"[完整因子加载] 布林带数据文件不存在: {bollinger_filepath}")

        # 3. 加载换手率数据并计算 turnover_surge = 当日换手率 / 5日均值
        turnover_filepath = DATA_CACHE_DIR / 'factor_data/turnover_rate_data.json.gz'
        if turnover_filepath.exists():
            with gzip.open(turnover_filepath, 'rt', encoding='utf-8') as f:
                turnover_data = json.load(f).get('data', [])
            turnover_df = pd.DataFrame(turnover_data)
            # 按 asset 和 date 排序
            turnover_df = turnover_df.sort_values(['asset', 'date'])
            # 计算 5日滚动均值
            turnover_df['turnover_rate_5d_mean'] = turnover_df.groupby('asset')['turnover_rate'].transform(
                lambda x: x.rolling(window=5, min_periods=1).mean()
            )
            # 计算 turnover_surge = 当日换手率 / 5日均值
            turnover_df['turnover_surge'] = turnover_df['turnover_rate'] / turnover_df['turnover_rate_5d_mean']
            # 处理除零情况
            turnover_df['turnover_surge'] = turnover_df['turnover_surge'].replace([np.inf, -np.inf], np.nan)
            # 只保留需要的字段
            turnover_df = turnover_df[['date', 'asset', 'turnover_surge']]
            # 合并到 factor_df
            factor_df = factor_df.merge(turnover_df, on=['date', 'asset'], how='left')
            logger.info(f"[完整因子加载] 换手率突增因子已计算: 有效记录 {factor_df['turnover_surge'].notna().sum()} 条")
        else:
            logger.warning(f"[完整因子加载] 换手率数据文件不存在: {turnover_filepath}")

        # 4. 加载收益率数据
        return_filepath = DATA_CACHE_DIR / 'factor_data/return_data.json.gz'
        with gzip.open(return_filepath, 'rt', encoding='utf-8') as f:
            return_data = json.load(f).get('data', [])
        return_df = pd.DataFrame(return_data)
        logger.info(f"[完整因子加载] 收益率数据: {len(return_df)} 条")

        # 5. 合并数据
        merged_df = factor_df.merge(
            return_df[['date', 'asset', 'forward_return_1d', 'forward_return_3d', 'forward_return_5d']],
            on=['date', 'asset'], how='inner'
        )
        logger.info(f"[完整因子加载] 合并后数据: {len(merged_df)} 条, 字段: {list(merged_df.columns)}")

        return merged_df

    def _load_ic_from_files(self) -> Dict:
        """从预生成的 JSON 文件加载 IC 数据(T+1 周期)

        ⚠️ v3.13 已废弃:不再使用缓存 IC,统一动态计算

        Returns:
            Dict: {factor_id: {'dates': [...], 'ic_values': [...], 'ic_mean': float, 'icir': float}}
        """
        result = {}

        for factor_id, filename in FACTOR_RESULT_FILES.items():
            filepath = BASE_DIR / filename
            if filepath.exists():
                try:
                    with open(filepath, 'r', encoding='utf-8') as f:
                        data = json.load(f)

                    ic_metrics = data.get('ic_metrics', {})
                    ic_series = data.get('ic_series', {})

                    dates = ic_series.get('dates', [])
                    ic_values = ic_series.get('ic_values', [])

                    result[factor_id] = {
                        'dates': dates,
                        'ic_values': ic_values,
                        'ic_mean': ic_metrics.get('ic_mean', 0),
                        'icir': ic_metrics.get('icir', 0),
                        'positive_ratio': ic_metrics.get('positive_ratio', 0)
                    }

                    logger.info(f"加载 {factor_id} IC数据: {len(dates)} 天")

                except Exception as e:
                    logger.error(f"加载 {factor_id} IC数据失败: {e}")

        return result

    def _calculate_ic_dynamically(self, return_col: str) -> Dict:
        """动态计算因子 IC（所有周期统一）
        
        v3.13 IC计算统一修复（云舟实施）:
        - 所有周期（T+1/T+3/T+5）统一使用动态计算
        - 调用 _load_factor_data_complete() 加载完整因子数据
        - 修复因子字段映射，删除 fallback 逻辑
        - 确保跨周期 ICIR 计算一致
        
        Args:
            return_col: 收益字段名（如 forward_return_1d/3d/5d）
            
        Returns:
            Dict: {factor_id: {'dates': [...], 'ic_values': [...], 'ic_mean': float, 'icir': float}}
        """
        import pandas as pd
        from scipy.stats import spearmanr
        
        result = {}
        
        # ========== v1 Revision 2 核心改进：从共享缓存获取数据 ==========
        if self._use_shared_cache:
            from common.scoring_engine import SharedFactorDataCache
            
            # 确保共享缓存已加载
            if not SharedFactorDataCache.is_complete_factor_loaded():
                SharedFactorDataCache.preload_complete_factor_data()
            
            # 从共享缓存获取完整因子DataFrame
            merged_df = SharedFactorDataCache.get_complete_factor_data()
            
            logger.info(f"[统一IC计算] 使用共享缓存数据：{len(merged_df)} 条（周期={return_col}）")
        
        else:
            # 原有逻辑（独立加载）
            merged_df = self._load_factor_data_complete()
            logger.info(f"[统一IC计算] 独立加载完整因子数据：{len(merged_df)} 条")
        
        if merged_df.empty:
            logger.error(f"[统一IC计算] 因子数据加载失败")
            return result
        
        # 检查收益字段是否存在
        if return_col not in merged_df.columns:
            logger.error(f"[统一IC计算] 缺少收益字段: {return_col}")
            return result
        
        # 因子字段映射（v3.14 修复：恢复 5 个因子）
        factor_columns = {
            'rsi': 'rsi_6',
            'bollinger_pb': 'bollinger_pb',
            'volume_ratio': 'volume_ratio_5',
            'turnover_surge': 'turnover_surge',
            'return_3d': 'return_3d'  # 使用 factor_data.json.gz 中的 return_3d
        }
        
        # 计算各因子 IC
        for factor_id, col_name in factor_columns.items():
            if col_name not in merged_df.columns:
                logger.warning(f"[统一IC计算] 因子 {factor_id} 缺少数据列: {col_name}")
                continue
            
            # 按日期计算 IC
            dates = sorted(merged_df['date'].unique())
            ic_values = []
            valid_dates = []
            
            for date in dates:
                day_data = merged_df[merged_df['date'] == date]
                
                # v3.14 修复：使用 asset 列对齐股票，而非 DataFrame 行索引
                # 过滤掉缺失值
                valid_mask = day_data[col_name].notna() & day_data[return_col].notna()
                valid_data = day_data[valid_mask]
                
                if len(valid_data) < 10:
                    continue
                
                # 使用 asset 列作为索引，确保股票对齐
                factor_series = valid_data.set_index('asset')[col_name]
                return_series = valid_data.set_index('asset')[return_col]
                
                # 计算 Spearman IC
                try:
                    ic, p_value = spearmanr(factor_series.values, return_series.values)
                    if not pd.isna(ic):
                        ic_values.append(ic)
                        valid_dates.append(date)
                except Exception:
                    continue
            
            # 计算 ICIR
            if len(ic_values) > 0:
                ic_mean = np.mean(ic_values)
                ic_std = np.std(ic_values)
                icir = ic_mean / (ic_std + 1e-10)
                positive_ratio = sum(1 for ic in ic_values if ic > 0) / len(ic_values)
                
                result[factor_id] = {
                    'dates': valid_dates,
                    'ic_values': ic_values,
                    'ic_mean': float(ic_mean),
                    'icir': float(icir),
                    'positive_ratio': float(positive_ratio)
                }
                logger.info(f"[统一IC计算] {factor_id} IC计算完成: {len(valid_dates)} 天, ICIR={icir:.4f}")
        
        return result

    def _get_common_dates(self) -> List[str]:
        """获取所有因子共有的日期

        Returns:
            List[str]: 共有日期列表
        """
        if not self.ic_data:
            return []

        # 获取第一个因子的日期作为基准
        first_factor = list(self.ic_data.keys())[0]
        base_dates = set(self.ic_data[first_factor]['dates'])

        # 与其他因子日期求交集
        for factor_id, data in self.ic_data.items():
            factor_dates = set(data['dates'])
            base_dates = base_dates.intersection(factor_dates)

        # 返回排序后的日期列表
        return sorted(list(base_dates))

    def _get_aligned_ic_values(self, factors: List[str]) -> Dict[str, np.ndarray]:
        """获取对齐后的IC值数组

        Args:
            factors: 选定的因子列表

        Returns:
            Dict[str, np.ndarray]: {factor_id: ic_array} 对齐后的IC值数组
        """
        aligned_ic = {}

        for factor_id in factors:
            if factor_id not in self.ic_data:
                continue

            data = self.ic_data[factor_id]
            dates = data['dates']
            ic_values = data['ic_values']

            # 创建日期到IC值的映射
            date_to_ic = {d: ic for d, ic in zip(dates, ic_values)}

            # 按共有日期顺序提取IC值
            aligned_ic[factor_id] = np.array([
                date_to_ic.get(d, 0) for d in self.common_dates
            ])

        return aligned_ic

    def calculate_combined_icir(
        self,
        weights: Dict[str, float],
        factors: List[str],
        icir_weight: float = 0.6,  # P2: ICIR 权重
        ic_mean_weight: float = 0.4,  # P2: IC_mean 权重
        ic_directions: Dict[str, str] = None  # P1-3: 因子方向配置
    ) -> Dict:
        """
        计算组合ICIR和综合得分(P2 改进 + P1-3 正向权重激励)

        公式:组合ICIR ≈ Σ(权重×IC) / sqrt(Σ(权重2×IC2))
        精确公式:组合ICIR = mean(combined_ic) / std(combined_ic)

        P2 改进:返回 composite_score = 0.6*ICIR + 0.4*IC_mean
        P1-3 改进:正向权重激励机制(正向因子权重 > 0 时加分)

        Args:
            weights: 因子权重字典 {factor_id: weight}
            factors: 选定的因子列表
            icir_weight: ICIR 权重(默认 0.6)
            ic_mean_weight: IC_mean 权重(默认 0.4)
            ic_directions: 因子方向配置(默认使用全局 IC_DIRECTIONS)

        Returns:
            Dict: {'icir': float, 'ic_mean': float, 'ic_std': float, 'composite_score': float, 'direction_bonus': float}
        """
        # 获取对齐后的IC值
        aligned_ic = self._get_aligned_ic_values(factors)

        if not aligned_ic or not self.common_dates:
            return {'icir': 0, 'ic_mean': 0, 'ic_std': 0, 'composite_score': 0, 'direction_bonus': 0}

        # 计算每日组合IC
        combined_ic_list = []

        for i, date in enumerate(self.common_dates):
            daily_ic = sum(
                weights.get(f, 0) * aligned_ic[f][i]
                for f in factors
                if f in aligned_ic
            )
            combined_ic_list.append(daily_ic)

        combined_ic = np.array(combined_ic_list)

        # 计算ICIR
        ic_mean = np.mean(combined_ic)
        ic_std = np.std(combined_ic)

        if ic_std > 0:
            icir = ic_mean / ic_std
        else:
            icir = 0

        # P1-3: 正向权重激励机制(云柏方案B:软约束)
        # 正向因子权重 > 0 时加分,鼓励正向使用正向因子
        # 方案A修复: 从配置读取方向，不再动态计算
        if ic_directions is None:
            # 优先从配置文件读取
            if hasattr(self, 'config') and self.config and 'factor_directions' in self.config:
                ic_directions = self.config['factor_directions']
            else:
                # 备用：使用默认 IC_DIRECTIONS
                ic_directions = IC_DIRECTIONS

        direction_bonus = 0.1 * sum(
            w for f, w in weights.items()
            if ic_directions.get(f, 'neutral') == 'positive' and w > 0
        )

        # P2: 计算综合得分(P1-3: 加入正向权重奖励)
        composite_score = icir_weight * icir + ic_mean_weight * ic_mean + direction_bonus

        return {
            'icir': icir,
            'ic_mean': ic_mean,
            'ic_std': ic_std,
            'composite_score': composite_score,
            'direction_bonus': direction_bonus  # P1-3: 记录正向权重奖励
        }

    def calculate_combined_icir_with_decay(
        self,
        weights: Dict[str, float],
        factors: List[str],
        holding_days: int = 1,
        icir_weight: float = 0.6,
        ic_mean_weight: float = 0.4
    ) -> Dict:
        """
        v3: 组合ICIR计算(衰减补偿版)

        公式改进:
        combined_ic = Σ(weight_i × IC_i × decay_factor)
        ICIR = mean(combined_ic) / std(combined_ic)

        Args:
            weights: 因子权重字典
            factors: 因子列表
            holding_days: 持仓天数(1/3/5)
            icir_weight: ICIR权重
            ic_mean_weight: IC_mean权重

        Returns:
            Dict: {'icir', 'ic_mean', 'ic_std', 'composite_score', 'decay_factor', 'holding_days'}
        """
        # 获取衰减因子
        decay_factor = get_decay_factor(holding_days)

        # 获取对齐后的IC值
        aligned_ic = self._get_aligned_ic_values(factors)

        if not aligned_ic or not self.common_dates:
            return {'icir': 0, 'ic_mean': 0, 'ic_std': 0, 'composite_score': 0, 'decay_factor': 0, 'holding_days': holding_days}

        # v3改进:每日组合IC × 衰减因子
        combined_ic_list = []

        for i, date in enumerate(self.common_dates):
            # 核心改进:每个因子IC × 衰减因子
            daily_ic = sum(
                weights.get(f, 0) * aligned_ic[f][i] * decay_factor
                for f in factors
                if f in aligned_ic
            )
            combined_ic_list.append(daily_ic)

        combined_ic = np.array(combined_ic_list)

        # 计算ICIR
        ic_mean = np.mean(combined_ic)
        ic_std = np.std(combined_ic)

        if ic_std > 0:
            icir = ic_mean / ic_std
        else:
            icir = 0

        # 计算综合得分
        composite_score = icir_weight * icir + ic_mean_weight * ic_mean

        return {
            'icir': icir,
            'ic_mean': ic_mean,
            'ic_std': ic_std,
            'composite_score': composite_score,
            'decay_factor': decay_factor,
            'holding_days': holding_days
        }

    def grid_search(
        self,
        factors: List[str],
        weight_range: Tuple[float, float] = (-1.0, 1.0),
        step: float = 0.2,
        constraint: str = 'sum_to_one',
        early_stop_patience: int = 10,
        progress_callback: Optional[callable] = None
    ) -> Dict:
        """
        网格搜索优化

        Args:
            factors: 选定的因子列表
            weight_range: 权重范围 (min, max)
            step: 网格步长
            constraint: 约束类型 ('sum_to_one', 'unconstrained')
            early_stop_patience: 早停耐心值(无改善次数)
            progress_callback: 进度回调函数

        Returns:
            Dict: {
                'best_weights': {...},
                'best_icir': float,
                'best_ic_mean': float,
                'best_ic_std': float,
                'total_evaluated': int,
                'convergence_iteration': int,
                'improvement_history': [...]
            }
        """
        logger.info(f"开始网格搜索: 因子={factors}, 范围={weight_range}, 步长={step}")

        # 生成权重网格
        weight_values = np.arange(weight_range[0], weight_range[1] + step, step)

        # 计算总组合数(考虑约束)
        n_factors = len(factors)

        # 粗略估算总组合数(实际会因约束减少)
        if constraint == 'sum_to_one':
            # 和约束下,实际组合数远小于全网格
            # 使用采样策略,按因子数递减
            if n_factors == 2:
                total_estimate = len(weight_values)  # 第二个因子由约束决定
            elif n_factors == 3:
                total_estimate = len(weight_values) ** 2  # 两个自由因子
            else:
                # 4+因子:采样搜索(不遍历全空间)
                total_estimate = min(10000, len(weight_values) ** (n_factors - 1))
        else:
            total_estimate = len(weight_values) ** n_factors

        logger.info(f"预估组合数: {total_estimate}")

        # 初始化
        best_icir = -float('inf')
        best_weights = {}
        best_ic_mean = 0
        best_ic_std = 0
        no_improve_count = 0
        improvement_history = []
        total_evaluated = 0

        # 网格搜索
        start_time = time.time()

        def evaluate_combination(weights_dict):
            """评估单个权重组合"""
            result = self.calculate_combined_icir(weights_dict, factors)
            return result['icir'], result['ic_mean'], result['ic_std']

        # 根据因子数量选择搜索策略
        if n_factors <= 3:
            # 小规模:完整网格搜索
            for combo in self._generate_weight_combinations(
                factors, weight_values, constraint, max_combinations=total_estimate
            ):
                total_evaluated += 1

                icir, ic_mean, ic_std = evaluate_combination(combo)

                if icir > best_icir:
                    best_icir = icir
                    best_weights = combo.copy()
                    best_ic_mean = ic_mean
                    best_ic_std = ic_std
                    no_improve_count = 0
                    improvement_history.append({
                        'iteration': total_evaluated,
                        'icir': icir,
                        'weights': combo.copy()
                    })
                    logger.info(f"新最优: ICIR={icir:.4f}, weights={combo}")
                else:
                    no_improve_count += 1

                # 进度回调
                if progress_callback and total_evaluated % 100 == 0:
                    elapsed = time.time() - start_time
                    progress_callback(
                        total_evaluated, total_estimate,
                        best_icir, best_weights,
                        elapsed
                    )

                # 早停检查
                if no_improve_count >= early_stop_patience and total_evaluated > 100:
                    logger.info(f"早停触发: 无改善 {no_improve_count} 次")
                    break

        else:
            # 大规模:采样搜索 + 局部精调
            # 第一阶段:粗网格采样
            sampled_count = 0
            sample_step = step * 2  # 粗网格步长加倍

            coarse_weights = np.arange(weight_range[0], weight_range[1] + sample_step, sample_step)

            for combo in self._generate_weight_combinations(
                factors, coarse_weights, constraint, max_combinations=5000
            ):
                sampled_count += 1
                total_evaluated += 1

                icir, ic_mean, ic_std = evaluate_combination(combo)

                if icir > best_icir:
                    best_icir = icir
                    best_weights = combo.copy()
                    best_ic_mean = ic_mean
                    best_ic_std = ic_std
                    no_improve_count = 0
                    improvement_history.append({
                        'iteration': total_evaluated,
                        'icir': icir,
                        'weights': combo.copy()
                    })

                if sampled_count >= 5000:
                    break

                # 进度回调
                if progress_callback and sampled_count % 200 == 0:
                    elapsed = time.time() - start_time
                    progress_callback(
                        sampled_count, 5000,
                        best_icir, best_weights,
                        elapsed
                    )

            # 第二阶段:在最优解附近精细搜索
            if best_weights:
                logger.info(f"粗搜索最优: ICIR={best_icir:.4f}, 开始精细搜索")

                fine_range = 0.4  # 精细范围
                fine_step = 0.1   # 精细步长

                for combo in self._generate_local_combinations(
                    best_weights, factors, fine_range, fine_step, constraint
                ):
                    total_evaluated += 1

                    icir, ic_mean, ic_std = evaluate_combination(combo)

                    if icir > best_icir:
                        best_icir = icir
                        best_weights = combo.copy()
                        best_ic_mean = ic_mean
                        best_ic_std = ic_std
                        improvement_history.append({
                            'iteration': total_evaluated,
                            'icir': icir,
                            'weights': combo.copy()
                        })
                        logger.info(f"精调最优: ICIR={icir:.4f}")

                    # 进度回调
                    if progress_callback and total_evaluated % 50 == 0:
                        elapsed = time.time() - start_time
                        progress_callback(
                            total_evaluated, total_estimate,
                            best_icir, best_weights,
                            elapsed
                    )

        elapsed_time = time.time() - start_time

        result = {
            'best_weights': best_weights,
            'best_icir': round(best_icir, 4),
            'best_ic_mean': round(best_ic_mean, 4),
            'best_ic_std': round(best_ic_std, 4),
            'total_evaluated': total_evaluated,
            'convergence_iteration': improvement_history[-1]['iteration'] if improvement_history else total_evaluated,
            'improvement_history': improvement_history[-10:],  # 只保留最近10次改进
            'elapsed_seconds': round(elapsed_time, 1),
            'factors': factors,
            'constraint': constraint,
            'method': 'grid_search'
        }

        logger.info(f"搜索完成: 最优ICIR={best_icir:.4f}, 耗时={elapsed_time:.1f}s")

        return result

    def _generate_weight_combinations(
        self,
        factors: List[str],
        weight_values: np.ndarray,
        constraint: str,
        max_combinations: int = 10000,
        sum_range: Tuple[float, float] = (0.5, 1.5),  # Phase 2 方案F: 权重和范围
        factor_min_weights: Dict[str, float] = None,  # P1: 因子权重下限
        factor_max_weights: Dict[str, float] = None   # P0-1: 因子权重上限(紧急修复)
    ):
        """
        生成权重组合

        Phase 2 改进(方案F):
        1. 支持 sum_to_one(原约束)
        2. 支持 sum_range(范围约束 [0.5, 1.5])
        3. 支持 none(无约束)

        P1 改进(因子权重下限):
        4. 支持 factor_min_weights(特定因子权重下限约束)

        P0-1 紧急修复(因子权重上限):
        5. 支持 factor_max_weights(特定因子权重上限约束)

        Args:
            factors: 因子列表
            weight_values: 权重值数组
            constraint: 约束类型 ('sum_to_one' | 'sum_range' | 'none')
            max_combinations: 最大组合数
            sum_range: 权重和范围(仅 sum_range 类型使用)
            factor_min_weights: 因子权重下限 {factor_id: min_weight}
            factor_max_weights: 因子权重上限 {factor_id: max_weight}(P0-1 新增)

        Yields:
            Dict: 权重组合字典
        """
        n_factors = len(factors)

        if constraint == 'none' or constraint == 'unconstrained':
            # 无约束:所有组合都生成
            # Phase 2 Bug修复:支持 'unconstrained' 类型
            count = 0
            for combo in self._recursive_combinations(factors, weight_values, {}):
                # P1: 验证因子权重下限约束
                if factor_min_weights:
                    valid = True
                    for factor, min_w in factor_min_weights.items():
                        if factor in combo and abs(combo.get(factor, 0)) < min_w:
                            valid = False
                            break
                    if not valid:
                        continue

                # P0-1 + P1-4: 验证因子权重上限约束(支持全局上限)
                if factor_max_weights:
                    valid = True
                    global_max = factor_max_weights.get('*', 0.4)  # P1-4: 全局上限默认 40%
                    for factor, weight in combo.items():
                        # 检查特定因子上限,若无则使用全局上限
                        factor_max = factor_max_weights.get(factor, global_max)
                        if factor in ['_comment', '_comment_p1_3', '_comment_p1_4', '_comment_global_max',
                                     '_comment_p2_1', '_comment_p0_2']:
                            continue  # 跳过注释字段
                        if abs(weight) > factor_max:
                            valid = False
                            break
                    if not valid:
                        continue

                yield combo
                count += 1
                if count >= max_combinations:
                    return

        elif constraint == 'sum_range':
            # Phase 2 方案F: 范围约束 sum(|w|) ∈ [min, max]
            count = 0
            for combo in self._recursive_combinations(factors, weight_values, {}):
                sum_abs = sum(abs(w) for w in combo.values())
                if sum_range[0] <= sum_abs <= sum_range[1]:
                    # P1: 验证因子权重下限约束
                    if factor_min_weights:
                        valid = True
                        for factor, min_w in factor_min_weights.items():
                            if factor in combo and abs(combo.get(factor, 0)) < min_w:
                                valid = False
                                break
                        if not valid:
                            continue

                    # P0-1 + P1-4: 验证因子权重上限约束(支持全局上限)
                    if factor_max_weights:
                        valid = True
                        global_max = factor_max_weights.get('*', 0.4)  # P1-4: 全局上限默认 40%
                        for factor, weight in combo.items():
                            # 检查特定因子上限,若无则使用全局上限
                            factor_max = factor_max_weights.get(factor, global_max)
                            if factor in ['_comment', '_comment_p1_3', '_comment_p1_4', '_comment_global_max',
                                         '_comment_p2_1', '_comment_p0_2']:
                                continue  # 跳过注释字段
                            if abs(weight) > factor_max:
                                valid = False
                                break
                        if not valid:
                            continue

                    yield combo
                    count += 1
                    if count >= max_combinations:
                        return

        elif constraint == 'sum_to_one':
            # 原约束:sum(|w|) = 1
            # 和为1约束:最后一个因子由其他因子决定
            if n_factors == 1:
                # 单因子:权重固定为1
                yield {factors[0]: 1.0}
                return

            # 递归生成组合
            count = 0
            for combo in self._recursive_combinations(
                factors[:-1], weight_values, {}
            ):
                # 计算最后一个因子权重
                last_weight = 1.0 - sum(combo.values())

                # 检查最后一个权重是否在范围内
                if weight_values[0] <= last_weight <= weight_values[-1]:
                    full_combo = combo.copy()
                    full_combo[factors[-1]] = round(last_weight, 2)

                    # P1: 验证因子权重下限约束
                    if factor_min_weights:
                        valid = True
                        for factor, min_w in factor_min_weights.items():
                            if factor in full_combo and abs(full_combo.get(factor, 0)) < min_w:
                                valid = False
                                break
                        if not valid:
                            continue

                    # P0-1 + P2-修复: 验证因子权重上限约束(支持全局上限)
                    if factor_max_weights:
                        valid = True
                        global_max = factor_max_weights.get('*', 0.4)  # P2-修复: 全局上限默认 40%
                        for factor, weight in full_combo.items():
                            # 跳过注释字段
                            if factor.startswith('_comment'):
                                continue
                            # 使用特定因子上限或全局上限
                            factor_max = factor_max_weights.get(factor, global_max)
                            if abs(weight) > factor_max:
                                valid = False
                                break
                        if not valid:
                            continue

                    yield full_combo
                    count += 1

                    if count >= max_combinations:
                        return

        else:
            # 未知的约束类型,使用 sum_to_one
            logger.warning(f"未知的约束类型: {constraint}, 使用 sum_to_one")
            yield from self._generate_weight_combinations(
                factors, weight_values, 'sum_to_one', max_combinations
            )

    def _generate_weight_combinations_with_direction(
        self,
        factors: List[str],
        weight_values: np.ndarray,
        constraint: str,
        ic_directions: Dict[str, str],
        max_combinations: int = 10000,
        tolerance: float = 0.0,  # Phase 2 方案E: 方向容忍度
        factor_min_weights: Dict[str, float] = None,  # P1: 因子权重下限
        factor_max_weights: Dict[str, float] = None   # P0-1: 因子权重上限(紧急修复)
    ):
        """
        带方向约束的权重组合生成(方案A + Phase 2方案E)

        Phase 2 改进:
        1. 添加 tolerance 参数,允许小范围反向(±0.2)
        2. 正向因子:weight >= -tolerance(允许小范围反向)
        3. 反向因子:weight <= +tolerance(允许小范围正向)

        P1 改进(因子权重下限):
        4. 支持 factor_min_weights(特定因子权重下限约束)

        P0-1 紧急修复(因子权重上限):
        5. 支持 factor_max_weights(特定因子权重上限约束)

        Args:
            factors: 因子列表
            weight_values: 权重值数组
            constraint: 约束类型
            ic_directions: Dict[str, str] - 因子IC方向
                'positive': IC>0,权重必须>=-tolerance
                'negative': IC<0,权重必须<=+tolerance
            max_combinations: 最大组合数
            tolerance: 方向容忍度(默认0,Phase 2可设为0.2)
            factor_min_weights: 因子权重下限 {factor_id: min_weight}
            factor_max_weights: 因子权重上限 {factor_id: max_weight}(P0-1 新增)

        Yields:
            Dict: 符合方向约束的权重组合字典
        """
        for combo in self._generate_weight_combinations(
            factors, weight_values, constraint, max_combinations,
            factor_min_weights=factor_min_weights, factor_max_weights=factor_max_weights
        ):
            valid = True
            for f in factors:
                direction = ic_directions.get(f, 'positive')
                weight = combo.get(f, 0)

                # 方向约束: 使用 tolerance 允许小范围反向
                if direction == 'positive':
                    # 正向因子:权重必须 >= -tolerance（允许小范围反向）
                    if weight < -tolerance - 1e-10:
                        valid = False
                        logger.debug(f"[约束] 正向因子 {f} 权重 {weight} < -tolerance={tolerance}，跳过")
                        break
                elif direction == 'negative':
                    # 反向因子:权重必须 <= +tolerance（允许小范围正向）
                    if weight > tolerance + 1e-10:
                        valid = False
                        logger.debug(f"[约束] 反向因子 {f} 权重 {weight} > +tolerance={tolerance}，跳过")
                        break
                # neutral: 无约束

            if valid:
                yield combo

    def _recursive_combinations(
        self,
        factors: List[str],
        weight_values: np.ndarray,
        current: Dict
    ):
        """递归生成权重组合"""
        if not factors:
            yield current.copy()
            return

        factor = factors[0]
        remaining = factors[1:]

        for w in weight_values:
            current[factor] = round(float(w), 2)
            yield from self._recursive_combinations(remaining, weight_values, current)

    def _generate_local_combinations(
        self,
        center_weights: Dict[str, float],
        factors: List[str],
        range_val: float,
        step: float,
        constraint: str
    ):
        """
        在最优解附近生成局部组合

        Args:
            center_weights: 中心权重
            factors: 因子列表
            range_val: 搜索范围
            step: 步长
            constraint: 约束类型
        """
        for combo in self._generate_weight_combinations(
            factors,
            np.arange(-range_val, range_val + step, step),
            constraint,
            max_combinations=2000
        ):
            # 将局部偏移应用到中心权重
            adjusted = {}
            for f in factors:
                adjusted[f] = round(center_weights.get(f, 0) + combo.get(f, 0), 2)

                # 确保在有效范围内 [-1, 1]
                adjusted[f] = max(-1.0, min(1.0, adjusted[f]))

            yield adjusted

    def grid_search_collect_top(
        self,
        factors: List[str],
        weight_range: Tuple[float, float] = (-1.0, 1.0),
        step: float = 0.2,
        constraint: str = 'sum_to_one',
        top_n: int = 100,
        progress_callback: Optional[callable] = None,
        use_direction_constraint: bool = True,  # 方案A: 是否使用方向约束
        ic_directions: Dict[str, str] = None,   # 方案A: IC方向配置
        tolerance: float = 0.0                  # Phase 2 方案E: 方向容忍度
    ) -> List[Dict]:
        """
        网格搜索收集 Top N 候选组合

        Phase 2 改进:
        1. 添加 tolerance 参数,放宽方向约束(±0.2)
        2. 正向因子允许 weight >= -tolerance

        Args:
            factors: 选定的因子列表
            weight_range: 权重范围 (min, max)
            step: 网格步长
            constraint: 约束类型
            top_n: 收集 Top N 候选
            progress_callback: 进度回调
            use_direction_constraint: 是否使用方向约束(方案A)
            ic_directions: IC方向配置,默认使用全局 IC_DIRECTIONS
            tolerance: 方向容忍度(默认0,Phase 2可设为0.2)

        Returns:
            List[Dict]: Top N 候选列表 [{'weights': {...}, 'icir': float}, ...]
        """
        logger.info(f"收集 Top {top_n} 候选: 因子={factors}, 范围={weight_range}, 步长={step}")
        if use_direction_constraint:
            logger.info(f"  方案A: 使用方向约束,tolerance={tolerance}(Phase 2)")

        # 方案A修复: 从配置读取方向，不再动态计算
        if ic_directions is None:
            # 优先从配置文件读取
            if hasattr(self, 'config') and self.config and 'factor_directions' in self.config:
                ic_directions = self.config['factor_directions']
                logger.info(f"[方向配置] 使用配置文件方向: {ic_directions}")
            else:
                # 备用：使用默认 IC_DIRECTIONS
                ic_directions = IC_DIRECTIONS
                logger.warning(f"[方向配置] 配置缺失，使用默认方向: {ic_directions}")

        # 生成权重网格
        weight_values = np.arange(weight_range[0], weight_range[1] + step, step)

        # 初始化候选列表(按 ICIR 排序)
        candidates = []  # [{'weights': {...}, 'icir': float, 'ic_mean': float}]

        start_time = time.time()
        total_evaluated = 0

        # 根据是否使用方向约束选择生成器
        if use_direction_constraint:
            generator = self._generate_weight_combinations_with_direction(
                factors, weight_values, constraint, ic_directions,
                max_combinations=10000, tolerance=tolerance
            )
        else:
            generator = self._generate_weight_combinations(
                factors, weight_values, constraint, max_combinations=10000
            )

        # 遍历所有组合
        for combo in generator:
            total_evaluated += 1

            # 计算 ICIR
            result = self.calculate_combined_icir(combo, factors)
            icir = result['icir']
            ic_mean = result['ic_mean']
            ic_std = result['ic_std']

            # 添加到候选列表
            candidates.append({
                'weights': combo.copy(),
                'icir': icir,
                'ic_mean': ic_mean,
                'ic_std': ic_std,
                'tolerance_applied': tolerance  # 记录使用的容忍度
            })

            # 进度回调
            if progress_callback and total_evaluated % 500 == 0:
                elapsed = time.time() - start_time
                best_icir = max(c['icir'] for c in candidates) if candidates else 0
                progress_callback(
                    int(total_evaluated / 10000 * 100), 100,
                    f'Phase 1: 搜索中 {total_evaluated}/~10000, ICIR={best_icir:.4f}, 耗时={elapsed:.1f}s',
                    phase='grid_search'
                )

        # 按 ICIR 排序,取 Top N
        candidates.sort(key=lambda x: x['icir'], reverse=True)
        top_candidates = candidates[:top_n]

        elapsed_time = time.time() - start_time
        logger.info(
            f"收集完成: 共 {total_evaluated} 组合, "
            f"Top {len(top_candidates)} ICIR 范围: "
            f"{top_candidates[-1]['icir']:.4f} ~ {top_candidates[0]['icir']:.4f}, "
            f"耗时 {elapsed_time:.1f}s"
        )

        return top_candidates

    def three_phase_search(
        self,
        factors: List[str],
        ic_directions: Dict[str, str] = None,
        config: Dict = None,
        progress_callback: Optional[callable] = None,
        tolerance: float = 0.0,  # Phase 2 方案E: 方向容忍度
        history_best: List[Dict] = None,  # P2-3: 历史最优权重列表
        return_col: str = 'forward_return_1d'  # v3.12 多周期修复: 周期参数
    ) -> List[Dict]:
        """
        三阶段搜索(详细日志版本)

        日志格式:
        - [Step] 开始执行: 步骤名称
        - [Step] 进度: 已处理 X/Y, 耗时 Ts
        - [Step] 完成: 步骤名称, 耗时 Ts, 结果: 关键指标
        """
        """
        三阶段搜索(方案C:扩大搜索范围 + Phase 2方案E + P2-3历史最优追踪 + v3.12多周期支持)

        Phase 2 改进:
        1. 添加 tolerance 参数,放宽方向约束(±0.2)
        2. 正向因子允许 weight >= -tolerance

        P2-3 改进:
        3. 添加历史最优作为搜索起点

        v3.12 多周期修复(云舟实施):
        4. 添加 return_col 参数,支持 T+1/T+3/T+5 周期优化

        流程:
        1. Phase 1: 粗网格搜索(步长0.2),收集 Top 200
        2. Phase 2: 在 Top 200 候选附近精细搜索(步长0.1)
        3. 输出 Top 500 最终候选

        Args:
            factors: 因子列表
            ic_directions: IC方向配置
            config: 搜索配置(来自 optimizer_config.json)
            progress_callback: 进度回调
            tolerance: 方向容忍度(默认0,Phase 2可设为0.2)
            history_best: 历史最优权重列表(P2-3)
            return_col: 收益字段名(默认 forward_return_1d,支持 forward_return_3d/5d)

        Returns:
            List[Dict]: Top 候选列表
        """
        # v3.12 多周期修复: 解析 holding_days
        import re
        match = re.search(r'(\d+)d$', return_col)
        holding_days = int(match.group(1)) if match else 1

        # v3.13 多周期差异化: 从配置读取周期特定权重范围
        period_specific_config = config.get('period_specific_config', {}) if config else {}
        period_config = period_specific_config.get(return_col, {})
        if period_config:
            # 应用周期特定配置
            period_weight_range = period_config.get('weight_range', {})
            if period_weight_range:
                # 覆盖默认 weight_range
                config['weight_range'] = [period_weight_range.get('min', -1.0), period_weight_range.get('max', 1.0)]
                logger.info(f"[v3.13 多周期差异化] 周期={return_col}, 权重范围={config['weight_range']}")

        # P1-2: 因子独立性检验
        correlation_config = config.get('factor_correlation_check', {}) if config else {}
        if correlation_config.get('enabled', False):
            threshold = correlation_config.get('threshold', 0.6)
            action = correlation_config.get('action', 'warn')

            logger.info(f"P1-2: 开始因子独立性检验,阈值={threshold},处理方式={action}")

            # 执行检验
            factors = self.remove_correlated_factors(factors, threshold, action)

            logger.info(f"P1-2: 因子检验完成,最终因子列表: {factors}")

        # 方案A修复: 从配置读取方向，不再动态计算
        if ic_directions is None:
            # 优先从配置文件读取
            if config and 'factor_directions' in config:
                ic_directions = config['factor_directions']
                logger.info(f"[方向配置] 使用配置文件方向: {ic_directions}")
            else:
                # 备用：使用默认 IC_DIRECTIONS
                ic_directions = IC_DIRECTIONS
                logger.warning(f"[方向配置] 配置缺失，使用默认方向: {ic_directions}")

        # 方向约束初始化：根据方向设置初始权重
        def initialize_weights_by_direction(factors_list: List[str], directions: Dict[str, str]) -> Dict[str, float]:
            """根据方向初始化权重"""
            initial_weights = {}
            for factor in factors_list:
                direction = directions.get(factor, 'neutral')
                if direction == 'positive':
                    initial_weights[factor] = 0.2  # 正向因子初始化为正
                elif direction == 'negative':
                    initial_weights[factor] = -0.2  # 反向因子初始化为负
                else:
                    initial_weights[factor] = 0.0  # 中性因子初始化为零
            
            # 归一化
            total = sum(abs(w) for w in initial_weights.values())
            if total > 0:
                for f in initial_weights:
                    initial_weights[f] = round(initial_weights[f] / total, 2)
            
            return initial_weights

        # 在 Phase 1 前调用
        initial_weights = initialize_weights_by_direction(factors, ic_directions)
        logger.info(f"[初始化] 方向约束初始权重: {initial_weights}")

        # 使用默认配置
        if config is None:
            config = {
                'weight_range': [-1.0, 1.0],
                'step_phase1': 0.1,      # P1-2: 精度提升
                'step_phase2': 0.05,     # P1-2: 精度提升
                'top_candidates_phase1': 200,
                'top_candidates_phase2': 500,
                'constraint': 'sum_to_one',
                'max_combinations': 150000,  # P1-2: 内存保护
                'factor_min_weights': None,  # P1: 因子权重下限
                'factor_max_weights': None   # P0-1: 因子权重上限
            }

        # P1: 获取因子权重下限配置
        factor_min_weights = config.get('factor_min_weights', None)

        # P0-1: 获取因子权重上限配置(紧急修复)
        factor_max_weights = config.get('factor_max_weights', None)

        logger.info(f"开始三阶段搜索: 因子={factors}")
        logger.info(f"  Phase 1: 粗网格(步长 {config['step_phase1']},P1-2 优化)")
        logger.info(f"  Phase 2: 精细搜索(步长 {config['step_phase2']},P1-2 优化)")
        logger.info(f"  方向容忍度: tolerance={tolerance}(Phase 2 方案E)")
        logger.info(f"  P1-2: 步长精度提升,搜索空间增加约 15-19 倍")
        if factor_min_weights:
            logger.info(f"  P1: 因子权重下限约束 {factor_min_weights}")
        if factor_max_weights:
            logger.info(f"  P0-1: 因子权重上限约束 {factor_max_weights}(紧急修复)")

        # P2-3: 历史最优权重追踪
        if history_best and len(history_best) > 0:
            logger.info(f"  P2-3: 历史最优权重追踪,加载 {len(history_best[-3:])} 个历史最优作为搜索起点")

        start_time = time.time()

        # ========== P2-3: 添加历史最优作为搜索起点 ==========
        history_candidates = []
        if history_best and len(history_best) > 0:
            for best in history_best[-3:]:  # 取最近 3 个历史最优
                best_weights = best.get('weights', {})
                best_icir = best.get('icir', 0)

                # 验证历史最优权重是否有效(包含所有因子)
                if all(f in best_weights for f in factors):
                    history_candidates.append({
                        'weights': best_weights,
                        'icir': best_icir,
                        'ic_mean': best.get('ic_mean', 0),
                        'ic_std': best.get('ic_std', 0),
                        'tolerance_applied': tolerance,
                        'is_history_best': True  # P2-3: 标记为历史最优
                    })
                    logger.info(f"  P2-3: 历史最优权重加入候选: icir={best_icir:.4f}")

        if progress_callback:
            progress_callback(0, 100, 'Phase 1: 粗网格搜索', phase='phase1')

        # ========== [Phase 1] 粗网格搜索 ==========
        phase1_start_time = time.time()
        logger.info(f"[Phase 1] 开始执行: 粗网格搜索(步长 {config['step_phase1']})")

        # P1-2: 步长变小后搜索空间增大,需要限制组合数
        max_combinations = config.get('max_combinations', 150000)
        logger.info(f"[Phase 1] 参数: weight_range={config['weight_range']}, max_combinations={max_combinations}")
        sys.stdout.flush()

        weight_values_phase1 = np.arange(
            config['weight_range'][0],
            config['weight_range'][1] + config['step_phase1'],
            config['step_phase1']
        )

        logger.info(f"[Phase 1] 生成权重网格: {len(weight_values_phase1)} 个权重值")
        sys.stdout.flush()

        candidates_phase1 = list(self._generate_weight_combinations_with_direction(
            factors, weight_values_phase1, config['constraint'], ic_directions,
            max_combinations=max_combinations, tolerance=tolerance,
            factor_min_weights=factor_min_weights, factor_max_weights=factor_max_weights  # P0-1: 添加上限约束
        ))

        phase1_gen_time = time.time() - phase1_start_time
        logger.info(f"[Phase 1] 权重组合生成完成: {len(candidates_phase1)} 个组合, 耗时 {phase1_gen_time:.1f}s")
        sys.stdout.flush()

        # 计算 ICIR 并排序
        logger.info(f"[Phase 1] 开始计算 ICIR...")
        sys.stdout.flush()

        scored_candidates = []
        for idx, combo in enumerate(candidates_phase1):
            # 方案 C: ICIR 使用原始 IC，不应用衰减
            result = self.calculate_combined_icir(combo, factors)
            scored_candidates.append({
                'weights': combo,
                'icir': result['icir'],
                'ic_mean': result['ic_mean'],
                'ic_std': result['ic_std'],
                'tolerance_applied': tolerance,
                'direction_bonus': result.get('direction_bonus', 0)  # P1-3: 正向权重奖励
            })

            # 进度日志:每 5000 个组合输出一次
            if (idx + 1) % 5000 == 0:
                elapsed = time.time() - phase1_start_time
                logger.info(f"[Phase 1] 进度: 已计算 ICIR {idx+1}/{len(candidates_phase1)}, 耗时 {elapsed:.1f}s")
                sys.stdout.flush()

        # P2-3: 将历史最优候选加入 scored_candidates
        if history_candidates:
            scored_candidates.extend(history_candidates)
            logger.info(f"  P2-3: 历史最优候选 {len(history_candidates)} 个已加入搜索池")
            sys.stdout.flush()

        scored_candidates.sort(key=lambda x: x['icir'], reverse=True)
        top_candidates_phase1 = scored_candidates[:config['top_candidates_phase1']]

        phase1_time = time.time() - phase1_start_time
        logger.info(f"[Phase 1] 完成: 粗网格搜索, 耗时 {phase1_time:.1f}s")
        logger.info(f"[Phase 1] 结果: 生成 {len(candidates_phase1)} 组合 -> Top {len(top_candidates_phase1)}")
        logger.info(f"[Phase 1] ICIR 范围: {top_candidates_phase1[-1]['icir']:.4f} ~ {top_candidates_phase1[0]['icir']:.4f}")
        sys.stdout.flush()

        # Phase 1 空列表保护
        if not top_candidates_phase1:
            logger.warning("[Phase 1] 失败: 未生成有效组合,请检查因子IC数据或约束配置")
            sys.stdout.flush()
            if progress_callback:
                progress_callback(100, 100, 'Phase 1 失败:未生成有效组合', phase='error')
            return []

        # 快速验证模式:跳过 Phase 2 精细搜索
        if config.get('skip_phase2', False):
            logger.info("[快速验证模式] 跳过 Phase 2 精细搜索,直接使用 Phase 1 结果")
            total_time = time.time() - start_time
            logger.info(f"[三阶段搜索] 完成总结(快速验证):")
            logger.info(f"  Phase 1 耗时: {phase1_time:.1f}s, 生成 {len(candidates_phase1)} -> Top {len(top_candidates_phase1)}")
            logger.info(f"  总耗时: {total_time:.1f}s")
            logger.info(f"  最终 Top ICIR: {top_candidates_phase1[0]['icir']:.4f}")
            sys.stdout.flush()
            if progress_callback:
                progress_callback(100, 100, '快速验证模式完成', phase='success')
            return top_candidates_phase1

        # ========== [Phase 2] 精细搜索 ==========
        if progress_callback:
            progress_callback(30, 100, 'Phase 2: 精细搜索', phase='phase2')

        phase2_start_time = time.time()
        logger.info(f"[Phase 2] 开始执行: 精细搜索(步长 {config['step_phase2']})")
        logger.info(f"[Phase 2] 参数: Top {len(top_candidates_phase1)} 候选, 偏移范围 ±0.3")
        sys.stdout.flush()

        refined_candidates = []
        processed_count = 0  # 进度计数

        for i, candidate in enumerate(top_candidates_phase1):
            # 进度日志:每处理 10 个候选输出一次
            if i % 10 == 0:
                elapsed = time.time() - phase2_start_time
                logger.info(f"[Phase 2] 进度: 候选 {i}/{len(top_candidates_phase1)}, 累计 {processed_count} 组合, 耗时 {elapsed:.1f}s")
                sys.stdout.flush()

            # 在候选附近 ±0.1 范围内精细搜索
            nearby_combos = self._generate_nearby_combinations(
                candidate['weights'], factors, config['step_phase2'], config['constraint'],
                ic_directions, tolerance,
                factor_min_weights,  # P2-修复: 传递下限约束
                factor_max_weights   # P0-1: 传递上限约束
            )

            for combo in nearby_combos:
                # 方案 C: ICIR 使用原始 IC，不应用衰减
                result = self.calculate_combined_icir(combo, factors)
                refined_candidates.append({
                    'weights': combo,
                    'icir': result['icir'],
                    'ic_mean': result['ic_mean'],
                    'ic_std': result['ic_std'],
                    'tolerance_applied': tolerance
                })
                processed_count += 1

                # 进度日志:每处理 1000 个组合输出一次
                if processed_count % 1000 == 0:
                    elapsed = time.time() - phase2_start_time
                    logger.info(f"[Phase 2] 进度: 已处理 {processed_count} 组合,候选 {i+1}/{len(top_candidates_phase1)}, 耗时 {elapsed:.1f}s")
                    sys.stdout.flush()

            # 进度回调
            if progress_callback and (i + 1) % 20 == 0:
                pct = 30 + int((i + 1) / len(top_candidates_phase1) * 60)
                progress_callback(pct, 100, f'Phase 2: 精细搜索 {i+1}/{len(top_candidates_phase1)}', phase='phase2')
                elapsed = time.time() - phase2_start_time
                logger.info(f"[Phase 2] 进度: 候选 {i+1}/{len(top_candidates_phase1)} 完成,累计 {processed_count} 组合, 耗时 {elapsed:.1f}s")
                sys.stdout.flush()

        phase2_time = time.time() - phase2_start_time
        logger.info(f"[Phase 2] 完成: 精细搜索, 耗时 {phase2_time:.1f}s")
        logger.info(f"[Phase 2] 结果: 生成 {len(refined_candidates)} 组合")
        sys.stdout.flush()

        # P0(紧急)- 双目标筛选
        logger.info(f"[Phase 2] 开始双目标筛选(ICIR + IC_mean)...")
        sys.stdout.flush()

        # 1. 按 ICIR 排序 Top 200(稳定性优先)
        candidates_icir = sorted(refined_candidates, key=lambda x: x['icir'], reverse=True)[:200]

        # 2. 按 IC_mean 排序 Top 200(收益优先)
        candidates_ic_mean = sorted(refined_candidates, key=lambda x: x['ic_mean'], reverse=True)[:200]

        # 3. 合并去重
        seen = {}
        for c in candidates_icir + candidates_ic_mean:
            key = tuple(sorted(c['weights'].items()))
            if key not in seen:
                seen[key] = c

        top_candidates_phase2 = list(seen.values())[:config['top_candidates_phase2']]

        logger.info(f"[Phase 2] 双目标筛选完成: ICIR Top 200 + IC_mean Top 200 -> 合并去重 {len(top_candidates_phase2)}")
        sys.stdout.flush()

        # Phase 2 Bug修复:空列表保护
        if not top_candidates_phase2:
            logger.warning("[Phase 2] 失败: 未生成有效组合")
            sys.stdout.flush()
            if progress_callback:
                progress_callback(100, 100, 'Phase 2 失败:未生成有效组合', phase='error')
            return []

        total_time = time.time() - start_time

        logger.info(f"[Phase 2] 最终结果: Top {len(top_candidates_phase2)} 候选")
        logger.info(f"[Phase 2] ICIR 范围: {top_candidates_phase2[-1]['icir']:.4f} ~ {top_candidates_phase2[0]['icir']:.4f}")
        sys.stdout.flush()

        # ========== [三阶段搜索] 总结 ==========
        logger.info(f"[三阶段搜索] 完成总结:")
        logger.info(f"  Phase 1 耗时: {phase1_time:.1f}s, 生成 {len(candidates_phase1)} -> Top {len(top_candidates_phase1)}")
        logger.info(f"  Phase 2 耗时: {phase2_time:.1f}s, 生成 {len(refined_candidates)} -> Top {len(top_candidates_phase2)}")
        logger.info(f"  总耗时: {total_time:.1f}s")
        logger.info(f"  最终 Top ICIR: {top_candidates_phase2[0]['icir']:.4f}")

        # P4: 候选池监控日志(改进 4)
        logger.info(f"[候选池监控] Phase 1 搜索完成:")
        logger.info(f"  - 总组合数: {len(candidates_phase1)}")
        logger.info(f"  - 有效候选数: {len(top_candidates_phase1)}")
        if len(candidates_phase1) > 0:
            logger.info(f"  - 候选利用率: {len(top_candidates_phase1) / len(candidates_phase1) * 100:.1f}%")

        logger.info(f"[候选池监控] Phase 2 搜索完成:")
        logger.info(f"  - 总组合数: {len(refined_candidates)}")
        logger.info(f"  - 有效候选数: {len(top_candidates_phase2)}")
        if len(refined_candidates) > 0:
            logger.info(f"  - 候选利用率: {len(top_candidates_phase2) / len(refined_candidates) * 100:.1f}%")

        sys.stdout.flush()

        if progress_callback:
            progress_callback(100, 100, '三阶段搜索完成', phase='complete')

        return top_candidates_phase2

    def _generate_nearby_combinations(
        self,
        center_weights: Dict[str, float],
        factors: List[str],
        step: float,
        constraint: str,
        ic_directions: Dict[str, str] = None,
        tolerance: float = 0.0,  # Phase 2 方案E: 方向容忍度
        factor_min_weights: Dict[str, float] = None,  # P2-修复: 因子权重下限
        factor_max_weights: Dict[str, float] = None  # P0-1: 因子权重上限
    ):
        """
        在中心权重附近生成组合

        Phase 2 改进:
        1. 添加 tolerance 参数,放宽方向约束

        P0-1 紧急修复:
        2. 添加 factor_max_weights 参数,约束因子权重上限

        P2-修复:
        3. 添加 factor_min_weights 参数,约束因子权重下限

        Args:
            center_weights: 中心权重
            factors: 因子列表
            step: 步长
            constraint: 约束类型
            ic_directions: IC方向配置
            tolerance: 方向容忍度
            factor_min_weights: 因子权重下限 {factor_id: min_weight}(P2-修复 新增)
            factor_max_weights: 因子权重上限 {factor_id: max_weight}(P0-1 新增)

        Yields:
            Dict: 附近的权重组合
        """
        # P1-2: 步长变小后,偏移范围可适当扩大
        # 步长 0.05 时,±0.3 范围内有 13 个偏移点
        # 云柏方案C：动态偏移范围，考虑权重上限约束
        base_offset_range = 0.3 if step <= 0.05 else 0.2

        # 根据每个因子的权重上限动态计算有效偏移范围
        effective_offset_range = base_offset_range
        if factor_max_weights:
            for f in factors:
                center = center_weights.get(f, 0)
                max_w = factor_max_weights.get(f, factor_max_weights.get('*', 0.4))
                # 计算该因子的最大允许偏移
                if center > 0:
                    allowed_offset = max_w - center  # 正向因子：向上偏移不能超过上限
                else:
                    allowed_offset = max_w + center  # 反向因子：向下偏移不能超过上限(abs)
                effective_offset_range = min(effective_offset_range, allowed_offset)

        # 确保偏移范围至少为 step（避免为0）
        effective_offset_range = max(effective_offset_range, step)

        offset_values = np.arange(-effective_offset_range, effective_offset_range + step, step)
        logger.info(f"[Phase 2 动态偏移] 基础范围={base_offset_range}, 有效范围={effective_offset_range}")

        # 方案A修复: 从配置读取方向，不再动态计算
        if ic_directions is None:
            # 优先从配置文件读取
            if hasattr(self, 'config') and self.config and 'factor_directions' in self.config:
                ic_directions = self.config['factor_directions']
                logger.info(f"[方向配置] 使用配置文件方向: {ic_directions}")
            else:
                # 备用：使用默认 IC_DIRECTIONS
                ic_directions = IC_DIRECTIONS
                logger.warning(f"[方向配置] 配置缺失，使用默认方向: {ic_directions}")

        # P1-2: 限制单候选附近组合数,防止内存溢出
        max_nearby = 10000 if step <= 0.05 else 5000
        count = 0

        # P2-修复: factor_min_weights Bug 修复
        # 问题:_generate_weight_combinations 中的 min_weights 检查是针对偏移值的
        #       偏移值=0 时 abs(0) < min_w 可能 True,导致正确组合被过滤
        # 修复:偏移值不受 factor_min_weights 约束,应在计算 adjusted 后检查最终权重
        # 所以这里不传递 factor_min_weights,在下面 adjusted 计算后检查
        for combo in self._generate_weight_combinations(
            factors, offset_values, 'unconstrained', max_combinations=max_nearby,
            factor_min_weights=None,  # P2-修复: 不传递,偏移值不受此约束
            factor_max_weights=None   # P2-修复: 同样,偏移值不受上限约束
        ):
            # P1-2: 内存保护
            if count >= max_nearby:
                break
            # 应用偏移到中心权重
            adjusted = {}
            for f in factors:
                adjusted[f] = round(center_weights.get(f, 0) + combo.get(f, 0), 2)
                # 确保在有效范围内 [-1, 1]
                adjusted[f] = max(-1.0, min(1.0, adjusted[f]))

            # P2-修复: 检查因子权重下限约束(最终权重,而非偏移值)
            if factor_min_weights:
                valid_min = True
                for factor, min_w in factor_min_weights.items():
                    if factor in adjusted and abs(adjusted.get(factor, 0)) < min_w:
                        valid_min = False
                        break
                if not valid_min:
                    continue

            # 方案A修复：强化方向约束（不再放宽）
            valid = True
            for f in factors:
                direction = ic_directions.get(f, 'positive')
                weight = adjusted.get(f, 0)

                # 方向约束: 使用 tolerance 允许小范围反向
                if direction == 'positive':
                    # 正向因子:权重必须 >= -tolerance（允许小范围反向）
                    if weight < -tolerance - 1e-10:
                        valid = False
                        logger.debug(f"[约束] 正向因子 {f} 权重 {weight} < -tolerance={tolerance}，跳过")
                        break
                elif direction == 'negative':
                    # 反向因子:权重必须 <= +tolerance（允许小范围正向）
                    if weight > tolerance + 1e-10:
                        valid = False
                        logger.debug(f"[约束] 反向因子 {f} 权重 {weight} > +tolerance={tolerance}，跳过")
                        break
                # neutral: 无约束

            # P0-1: 检查因子权重上限约束
            if valid and factor_max_weights:
                for factor, max_w in factor_max_weights.items():
                    if factor in adjusted and abs(adjusted.get(factor, 0)) > max_w:
                        valid = False
                        break

            if valid:
                # 检查和约束(如果需要)
                if constraint == 'sum_to_one':
                    total = sum(adjusted.values())
                    # 允许 ±0.1 的偏差
                    if abs(total - 1.0) <= 0.1:
                        # 调整最后一个因子使和为1
                        last_factor = factors[-1]
                        adjusted[last_factor] = round(1.0 - sum(adjusted[f] for f in factors[:-1]), 2)
                        count += 1
                        yield adjusted
                else:
                    count += 1
                    yield adjusted

    def grid_search_with_backtest(
        self,
        factors: List[str],
        weight_range: Tuple[float, float] = (-1.0, 1.0),
        step: float = 0.2,
        constraint: str = 'sum_to_one',
        top_candidates: int = 100,
        top_output: int = 10,
        backtest_config: Dict = None,
        progress_callback: Optional[callable] = None,
        fallback_to_icir: bool = True,
        use_parallel: bool = True,  # v3.6 新增:是否使用并行回测
        pool_size: int = 4  # v3.7 方案A:线程池默认4(比进程池更轻量)
    ) -> Dict:
        """
        网格搜索 + 回测验证

        v3.7 方案A(线程池)OOM修复:
        - 使用 ThreadPoolExecutor 替代 ProcessPoolExecutor
        - 内存峰值:3.2GB → 1.2GB
        - 性能:比进程池慢约2倍(用户已接受)
        - 线程池默认4个worker(比进程池更轻量)

        流程:
        1. 网格搜索收集 Top N 候选(基于 ICIR)
        2. 对每个候选进行回测验证(线程池并行)
        3. 应用约束条件筛选
        4. 输出 Top M 组合

        Args:
            factors: 因子列表
            weight_range: 权重范围
            step: 网格步长
            constraint: 约束类型
            top_candidates: 网格搜索收集候选数量
            top_output: 最终输出数量
            backtest_config: 回测配置
            progress_callback: 进度回调
            fallback_to_icir: 无组合通过约束时是否 fallback
            use_parallel: 是否使用并行回测(默认 True)
            pool_size: 线程池大小(默认 4)

        Returns:
            Dict: {
                'top_weights': [{'weights', 'metrics', 'passed'}],
                'grid_search_result': {...},
                'validation_result': {...},
                'summary': {...}
            }
        """
        logger.info(f"开始网格搜索+回测验证: 因子={factors}, 并行={use_parallel}")

        # 加载配置
        if backtest_config is None:
            try:
                config_path = CONFIG_DIR / 'optimizer_config.json'
                with open(config_path, 'r', encoding='utf-8') as f:
                    backtest_config = json.load(f)
            except Exception as e:
                logger.warning(f"加载配置失败,使用默认: {e}")
                backtest_config = {
                    'backtest_params': {
                        'start_date': '2023-01-01',
                        'end_date': '2024-12-31',
                        'top_n': 10,
                        'cost': 0.002,
                        'slippage': 0.001
                    },
                    'constraints': {
                        'min_sharpe': -1.0,
                        'max_drawdown': 90.0,
                        'min_win_rate': 30.0
                    }
                }

        start_time = time.time()

        # ========== Phase 1: 网格搜索收集候选 ==========
        logger.info("Phase 1: 网格搜索收集 Top 候选...")

        if progress_callback:
            progress_callback(0, 100, 'Phase 1: 网格搜索', phase='grid_search')

        grid_candidates = self.grid_search_collect_top(
            factors=factors,
            weight_range=weight_range,
            step=step,
            constraint=constraint,
            top_n=top_candidates,
            progress_callback=progress_callback
        )

        grid_time = time.time() - start_time
        logger.info(f"网格搜索完成,耗时 {grid_time:.1f}s,收集 {len(grid_candidates)} 候选")

        # ========== Phase 2: 回测验证 ==========
        logger.info(f"Phase 2: 回测验证候选组合({'并行' if use_parallel else '串行'}模式)...")

        if progress_callback:
            progress_callback(30, 100, f'Phase 2: 开始回测验证({"并行" if use_parallel else "串行"})', phase='backtest')

        # 导入快速回测验证模块
        try:
            from quick_backtest import QuickBacktestValidator, parallel_backtest_batch
            validator = QuickBacktestValidator(backtest_config)
        except ImportError as e:
            logger.error(f"导入 quick_backtest 模块失败: {e}")
            # Fallback: 直接返回 ICIR 最优组合
            return {
                'success': False,
                'error': f'导入 quick_backtest 失败: {e}',
                'top_weights': [{
                    'weights': grid_candidates[0]['weights'] if grid_candidates else {},
                    'icir': grid_candidates[0]['icir'] if grid_candidates else 0,
                    'metrics': None,
                    'passed_constraints': False,
                    'fallback_reason': '回测模块不可用'
                }] if grid_candidates else [],
                'grid_search_result': {
                    'total_candidates': len(grid_candidates),
                    'best_icir': grid_candidates[0]['icir'] if grid_candidates else 0,
                    'elapsed_seconds': grid_time
                }
            }

        # 批量验证(支持并行)
        def validation_progress(current, total, result):
            if progress_callback:
                progress_pct = 30 + int(current / total * 50)  # 30% -> 80%
                metrics = result.get('metrics', {}) if result else {}
                sharpe = metrics.get('sharpe_ratio', 'N/A') if metrics else 'N/A'
                progress_callback(
                    progress_pct, 100,
                    f'Phase 2: 验证 {current}/{total} (Sharpe={sharpe})',
                    phase='backtest'
                )

            # 日志输出每 10 个
            if current % 10 == 0:
                logger.info(f"验证进度: {current}/{total}")

        # v3.6 性能优化:选择并行或串行回测
        if use_parallel:
            # 使用并行回测
            validation_results = parallel_backtest_batch(
                weight_candidates=grid_candidates,
                factors=factors,
                config=backtest_config,
                pool_size=pool_size,
                progress_callback=validation_progress
            )
        else:
            # 使用串行回测
            validation_results = validator.validate_batch_weights(
                weight_candidates=grid_candidates,
                factors=factors,
                progress_callback=validation_progress,
                log_interval=10
            )

        backtest_time = time.time() - start_time - grid_time
        logger.info(f"回测验证完成,耗时 {backtest_time:.1f}s({'并行' if use_parallel else '串行'})")

        # ========== Phase 3: 篮选排序 ==========
        logger.info("Phase 3: 篮选 Top 组合...")

        if progress_callback:
            progress_callback(80, 100, 'Phase 3: 篮选排序', phase='filter')

        top_weights = validator.filter_and_rank(
            validation_results=validation_results,
            top_n=top_output,
            fallback_to_icir=fallback_to_icir
        )

        # 获取验证摘要
        validation_summary = validator.get_validation_summary(validation_results)

        total_time = time.time() - start_time

        # ========== 构建最终结果 ==========
        result = {
            'success': True,
            'top_weights': top_weights,
            'grid_search_result': {
                'total_candidates': len(grid_candidates),
                'best_icir': grid_candidates[0]['icir'] if grid_candidates else 0,
                'icir_range': {
                    'max': grid_candidates[0]['icir'] if grid_candidates else 0,
                    'min': grid_candidates[-1]['icir'] if grid_candidates else 0
                },
                'elapsed_seconds': round(grid_time, 1)
            },
            'validation_result': {
                'total_validated': len(validation_results),
                'passed_count': validation_summary['passed_constraints'],
                'pass_rate': validation_summary['pass_rate'],
                'metrics_distribution': validation_summary['metrics_distribution'],
                'elapsed_seconds': round(backtest_time, 1),
                'parallel_used': use_parallel,  # v3.6 新增
                'pool_size': pool_size if use_parallel else 1  # v3.6 新增
            },
            'summary': {
                'total_elapsed_seconds': round(total_time, 1),
                'factors': factors,
                'top_candidates': top_candidates,
                'top_output': top_output,
                'fallback_used': len(top_weights) > 0 and not top_weights[0].get('passed_constraints', False),
                'parallel_backtest': use_parallel  # v3.6 新增
            },
            'config': backtest_config
        }

        logger.info(f"网格搜索+回测验证完成,总耗时 {total_time:.1f}s")
        logger.info(f"  Top {len(top_weights)} 组合输出")
        if use_parallel:
            logger.info(f"  线程池回测(方案A):内存峰值 ~1.2GB,避免了OOM")

        if progress_callback:
            progress_callback(100, 100, '完成', phase='complete')

        return result


# ==================== 全局优化器实例 ====================
# v3.12 多周期修复(云舟实施):
# - 改为周期键缓存,避免所有周期共享同一个实例
# - 每个周期(T+1/T+3/T+5)独立优化器实例
_optimizer_cache = {}  # key: return_col, value: optimizer instance

def get_optimizer(return_col: str = 'forward_return_1d', use_shared_cache: bool = False) -> WeightOptimizer:
    """获取优化器实例(支持多周期和共享缓存)

    v3.12 多周期修复(云舟实施):
    - 支持周期键缓存:_optimizer_cache[return_col] = optimizer
    - T+1/T+3/T+5 各有独立的优化器实例
    - 避免 T+3/T+5 使用 T+1 的 IC 数据
    
    v3.10 引擎数据共享优化(云柏方案):
    - use_shared_cache=True: 使用共享引擎数据（推荐多周期并行）
    - 内存节省约720MB

    Args:
        return_col: 收益字段名(默认 forward_return_1d)
        use_shared_cache: 是否使用共享缓存(默认 False,仅在多周期并行时启用)

    Returns:
        WeightOptimizer: 对应周期的优化器实例
    """
    global _optimizer_cache

    # 使用共享缓存键（避免周期键重复）
    cache_key = f"{return_col}_shared" if use_shared_cache else return_col

    if cache_key not in _optimizer_cache:
        _optimizer_cache[cache_key] = WeightOptimizer(return_col=return_col, use_shared_cache=use_shared_cache)
        logger.info(f"[优化器缓存] 创建新实例(周期={return_col}, 共享缓存={use_shared_cache})")

    return _optimizer_cache[cache_key]


# ==================== API 辅助函数 ====================

def start_optimization(
    factors: List[str],
    objective: str = 'icir',
    method: str = 'grid_search',
    params: Dict = None
) -> Dict:
    """
    启动优化任务

    Args:
        factors: 选定的因子列表
        objective: 优化目标(目前只支持 'icir')
        method: 搜索方法
        params: 其他参数

    Returns:
        Dict: {'success': bool, 'task_id': str, 'message': str}
    """
    global optimization_state

    with optimization_lock:
        # 检查是否有正在运行的任务
        if optimization_state['status'] == 'running':
            return {
                'success': False,
                'error': '已有优化任务正在运行',
                'current_task': optimization_state['task_id']
            }

        # 生成任务ID
        task_id = f"opt_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

        # 初始化状态
        optimization_state = {
            'status': 'running',
            'task_id': task_id,
            'progress': {
                'current_iteration': 0,
                'total_iterations': 0,
                'percentage': 0,
                'current_best_icir': 0,
                'current_best_weights': {},
                'elapsed_seconds': 0,
                'estimated_remaining_seconds': 0
            },
            'result': None,
            'error': None,
            'start_time': datetime.now(),
            'end_time': None,
            'history_best': optimization_state.get('history_best', [])
        }

    # 解析参数
    if params is None:
        params = {}

    weight_range = params.get('weight_range', {'min': -1.0, 'max': 1.0})
    weight_min = weight_range.get('min', -1.0)
    weight_max = weight_range.get('max', 1.0)

    step = params.get('grid_step', 0.2)
    constraint = params.get('constraint', 'sum_to_one')
    early_stop = params.get('early_stop_patience', 10)

    # 启动异步优化线程
    def run_optimization():
        global optimization_state

        try:
            optimizer = get_optimizer()

            def progress_callback(current, total, best_icir, best_weights, elapsed):
                """更新进度"""
                with optimization_lock:
                    optimization_state['progress'] = {
                        'current_iteration': current,
                        'total_iterations': total,
                        'percentage': round(current / total * 100, 1) if total > 0 else 0,
                        'current_best_icir': round(best_icir, 4),
                        'current_best_weights': best_weights,
                        'elapsed_seconds': round(elapsed, 1),
                        'estimated_remaining_seconds': round(elapsed / current * (total - current), 1) if current > 0 else 0
                    }

            # 执行网格搜索
            result = optimizer.grid_search(
                factors=factors,
                weight_range=(weight_min, weight_max),
                step=step,
                constraint=constraint,
                early_stop_patience=early_stop,
                progress_callback=progress_callback
            )

            # 更新最终状态
            with optimization_lock:
                optimization_state['status'] = 'completed'
                optimization_state['result'] = result
                optimization_state['end_time'] = datetime.now()

                # 记录历史最优
                if result['best_icir'] > 0:
                    optimization_state['history_best'].append({
                        'task_id': task_id,
                        'icir': result['best_icir'],
                        'weights': result['best_weights'],
                        'factors': factors,
                        'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                    })

            logger.info(f"优化任务完成: {task_id}")

        except Exception as e:
            import traceback
            traceback.print_exc()

            with optimization_lock:
                optimization_state['status'] = 'error'
                optimization_state['error'] = str(e)
                optimization_state['end_time'] = datetime.now()

            logger.error(f"优化任务失败: {e}")

    # 启动线程
    thread = threading.Thread(target=run_optimization, daemon=True)
    thread.start()

    return {
        'success': True,
        'task_id': task_id,
        'message': f'优化任务已启动,共 {len(factors)} 个因子',
        'factors': factors,
        'params': {
            'weight_range': (weight_min, weight_max),
            'step': step,
            'constraint': constraint,
            'early_stop_patience': early_stop
        }
    }


def get_optimization_progress() -> Dict:
    """
    获取优化进度

    Returns:
        Dict: 进度信息
    """
    with optimization_lock:
        state = optimization_state.copy()

        # 计算耗时
        if state['start_time']:
            elapsed = (datetime.now() - state['start_time']).total_seconds()
            state['progress']['elapsed_seconds'] = round(elapsed, 1)

        return {
            'status': state['status'],
            'task_id': state['task_id'],
            'progress': state['progress'],
            'error': state['error']
        }


def get_optimization_result() -> Dict:
    """
    获取优化结果

    Returns:
        Dict: 优化结果
    """
    with optimization_lock:
        state = optimization_state.copy()

        return {
            'status': state['status'],
            'task_id': state['task_id'],
            'result': state['result'],
            'error': state['error'],
            'start_time': state['start_time'].strftime('%Y-%m-%d %H:%M:%S') if state['start_time'] else None,
            'end_time': state['end_time'].strftime('%Y-%m-%d %H:%M:%S') if state['end_time'] else None,
            'history_best': state.get('history_best', [])
        }


def get_optimizer_config() -> Dict:
    """
    获取优化器配置信息

    Returns:
        Dict: 配置信息
    """
    optimizer = get_optimizer()

    return {
        'available_factors': list(FACTOR_RESULT_FILES.keys()),
        'factor_names': FACTOR_NAMES,
        'common_dates_count': len(optimizer.common_dates),
        'ic_data_loaded': list(optimizer.ic_data.keys()),
        'default_params': {
            'weight_range': {'min': -1.0, 'max': 1.0},
            'grid_step': 0.2,
            'constraint': 'sum_to_one',
            'early_stop_patience': 10
        }
    }


def start_optimization_with_backtest(
    factors: List[str],
    params: Dict = None
) -> Dict:
    """
    启动带回测验证的优化任务

    流程:
    1. 网格搜索收集 Top 100 候选(基于 ICIR)
    2. 对每个候选进行回测验证
    3. 应用约束条件筛选:
       - 夏普比率 > 1.0
       - 最大回撤 < 30%
       - 胜率 > 50%
    4. 输出 Top 10 组合供用户选择

    Args:
        factors: 选定的因子列表
        params: 其他参数
            - weight_range: {'min': -1.0, 'max': 1.0}
            - grid_step: 0.2
            - constraint: 'sum_to_one'
            - top_candidates: 100 (网格搜索收集候选数量)
            - top_output: 10 (最终输出数量)
            - backtest_config: {...} (回测配置,可选)

    Returns:
        Dict: {'success': bool, 'task_id': str, 'message': str}
    """
    global optimization_state

    with optimization_lock:
        # 检查是否有正在运行的任务
        if optimization_state['status'] == 'running':
            return {
                'success': False,
                'error': '已有优化任务正在运行',
                'current_task': optimization_state['task_id']
            }

        # 生成任务ID
        task_id = f"opt_backtest_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

        # 初始化状态
        optimization_state = {
            'status': 'running',
            'task_id': task_id,
            'phase': 'grid_search',  # 新增:当前阶段
            'progress': {
                'phase': 'grid_search',
                'percentage': 0,
                'message': '准备开始网格搜索',
                'current_iteration': 0,
                'total_iterations': 0,
                'elapsed_seconds': 0
            },
            'result': None,
            'error': None,
            'start_time': datetime.now(),
            'end_time': None,
            'history_best': optimization_state.get('history_best', [])
        }

    # 解析参数
    if params is None:
        params = {}

    # 网格搜索参数
    weight_range = params.get('weight_range', {'min': -1.0, 'max': 1.0})
    weight_min = weight_range.get('min', -1.0)
    weight_max = weight_range.get('max', 1.0)

    step = params.get('grid_step', 0.2)
    constraint = params.get('constraint', 'sum_to_one')

    # 回测验证参数
    top_candidates = params.get('top_candidates', 100)
    top_output = params.get('top_output', 10)
    backtest_config = params.get('backtest_config', None)
    fallback_to_icir = params.get('fallback_to_icir', True)

    # 启动异步优化线程
    def run_optimization_with_backtest():
        global optimization_state

        try:
            optimizer = get_optimizer()

            # 进度回调
            def progress_callback(pct, total, msg, phase='unknown'):
                with optimization_lock:
                    elapsed = (datetime.now() - optimization_state['start_time']).total_seconds()
                    optimization_state['phase'] = phase
                    optimization_state['progress'] = {
                        'phase': phase,
                        'percentage': pct,
                        'message': msg,
                        'current_iteration': 0,
                        'total_iterations': total,
                        'elapsed_seconds': round(elapsed, 1)
                    }

            # 执行网格搜索 + 回测验证
            result = optimizer.grid_search_with_backtest(
                factors=factors,
                weight_range=(weight_min, weight_max),
                step=step,
                constraint=constraint,
                top_candidates=top_candidates,
                top_output=top_output,
                backtest_config=backtest_config,
                progress_callback=progress_callback,
                fallback_to_icir=fallback_to_icir
            )

            # 更新最终状态
            with optimization_lock:
                optimization_state['status'] = 'completed'
                optimization_state['result'] = result
                optimization_state['end_time'] = datetime.now()

                # 记录历史最优
                if result.get('success') and result.get('top_weights'):
                    best = result['top_weights'][0]
                    optimization_state['history_best'].append({
                        'task_id': task_id,
                        'weights': best.get('weights', {}),
                        'metrics': best.get('metrics', {}),
                        'passed_constraints': best.get('passed_constraints', False),
                        'icir': best.get('icir', 0),
                        'factors': factors,
                        'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                        'method': 'grid_search_with_backtest'
                    })

            logger.info(f"带回测验证的优化任务完成: {task_id}")

        except Exception as e:
            import traceback
            traceback.print_exc()

            with optimization_lock:
                optimization_state['status'] = 'error'
                optimization_state['error'] = str(e)
                optimization_state['end_time'] = datetime.now()

            logger.error(f"带回测验证的优化任务失败: {e}")

    # 启动线程
    thread = threading.Thread(target=run_optimization_with_backtest, daemon=True)
    thread.start()

    return {
        'success': True,
        'task_id': task_id,
        'message': f'带回测验证的优化任务已启动,共 {len(factors)} 个因子',
        'factors': factors,
        'params': {
            'weight_range': (weight_min, weight_max),
            'step': step,
            'constraint': constraint,
            'top_candidates': top_candidates,
            'top_output': top_output,
            'fallback_to_icir': fallback_to_icir
        }
    }


def get_backtest_optimization_progress() -> Dict:
    """
    获取带回测验证的优化进度

    Returns:
        Dict: 进度信息(包含当前阶段)
    """
    with optimization_lock:
        state = optimization_state.copy()

        # 计算耗时
        if state['start_time']:
            elapsed = (datetime.now() - state['start_time']).total_seconds()
            state['progress']['elapsed_seconds'] = round(elapsed, 1)

        return {
            'status': state['status'],
            'task_id': state['task_id'],
            'phase': state.get('phase', 'unknown'),
            'progress': state['progress'],
            'error': state['error']
        }


def get_backtest_optimization_result() -> Dict:
    """
    获取带回测验证的优化结果

    Returns:
        Dict: 优化结果(包含 Top 10 组合和验证详情)
    """
    with optimization_lock:
        state = optimization_state.copy()

        result = state.get('result') or {}  # 修复:确保 result 不是 None

        return {
            'status': state['status'],
            'task_id': state['task_id'],
            'progress': state.get('progress', {}),  # 添加 progress 字段
            'phase': state.get('phase', 'unknown'),  # 添加 phase 字段
            'result': result,
            'top_weights': result.get('top_weights', []),
            'grid_search_result': result.get('grid_search_result', {}),
            'validation_result': result.get('validation_result', {}),
            'summary': result.get('summary', {}),
            'error': state['error'],
            'start_time': state['start_time'].strftime('%Y-%m-%d %H:%M:%S') if state['start_time'] else None,
            'end_time': state['end_time'].strftime('%Y-%m-%d %H:%M:%S') if state['end_time'] else None,
            'history_best': state.get('history_best', [])
        }