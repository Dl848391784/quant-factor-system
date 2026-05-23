"""
因子数据加载模块

功能:
1. 从 cache/factor_data/ 加载因子原始值
2. 从 factor_ic/result/ 加载 IC 统计结果
3. 从 factor_ic/result/ 加载 IC 每日序列（用于滚动ICIR）
4. 合并多个因子数据到统一 DataFrame

设计参考:
- factor_ic/common/data_loader.py
- backtest/common/data_loader.py

作者: 云瑶
创建日期: 2026-05-24
"""

import gzip
import json
import logging
import pandas as pd
import numpy as np
from pathlib import Path
from typing import Dict, List, Optional, Tuple


# 默认路径
DEFAULT_CACHE_DIR = Path(__file__).parent.parent.parent / 'cache' / 'factor_data'
DEFAULT_IC_RESULT_DIR = Path(__file__).parent.parent.parent / 'factor_ic' / 'result'


def load_factor_values(
    factor_cols: List[str],
    cache_dir: Optional[Path] = None,
    logger: Optional[logging.Logger] = None
) -> pd.DataFrame:
    """从缓存加载因子原始值
    
    Args:
        factor_cols: 因子列名列表（如 ['rsi_6', 'volume_ratio_5']）
        cache_dir: 缓存目录路径
        logger: 日志对象
    
    Returns:
        包含 date, asset, 因子列的 DataFrame
    """
    if logger is None:
        from comprehensive_factor.common.logger_config import get_logger
        logger = get_logger(__name__)
    
    if cache_dir is None:
        cache_dir = DEFAULT_CACHE_DIR
    
    cache_dir = Path(cache_dir)
    
    # 加载主因子数据
    factor_path = cache_dir / 'factor_data.json.gz'
    logger.info("加载因子数据: %s", factor_path)
    
    if not factor_path.exists():
        raise FileNotFoundError(f"因子数据缓存文件不存在: {factor_path}")
    
    with gzip.open(factor_path, 'rt', encoding='utf-8') as f:
        factor_data = json.load(f)
    
    if 'data' not in factor_data:
        raise KeyError(f"因子数据 JSON 结构缺失 'data' 字段: {factor_path}")
    
    factor_df = pd.DataFrame(factor_data['data'])
    
    # 校验因子列存在
    required_cols = ['date', 'asset'] + factor_cols
    for col in required_cols:
        if col not in factor_df.columns:
            raise ValueError(f"因子数据中缺少 {col} 列")
    
    logger.info("因子数据: %d 条记录", len(factor_df))
    
    return factor_df[['date', 'asset'] + factor_cols].copy()


def load_ic_results(
    factor_names: List[str],
    ic_result_dir: Optional[Path] = None,
    return_period: str = '1d',
    logger: Optional[logging.Logger] = None
) -> Dict[str, Dict]:
    """从 factor_ic/result/ 加载 IC 统计结果
    
    Args:
        factor_names: 因子名称列表（如 ['rsi', 'volume_ratio']）
        ic_result_dir: IC结果目录路径
        return_period: 收益周期（如 '1d'）
        logger: 日志对象
    
    Returns:
        Dict[因子名, IC统计结果]
        {
            'rsi': {'ic_mean': -0.032, 'icir': -0.45, 'ic_std': 0.07, ...},
            'volume_ratio': {'ic_mean': -0.058, 'icir': -1.97, ...}
        }
    """
    if logger is None:
        from comprehensive_factor.common.logger_config import get_logger
        logger = get_logger(__name__)
    
    if ic_result_dir is None:
        ic_result_dir = DEFAULT_IC_RESULT_DIR
    
    ic_result_dir = Path(ic_result_dir)
    
    ic_results = {}
    
    for factor_name in factor_names:
        # IC结果文件命名: ic_<因子名>_<收益周期>_analysis_result.json
        ic_file = ic_result_dir / f'ic_{factor_name}_{return_period}_analysis_result.json'
        
        if not ic_file.exists():
            logger.warning("IC结果文件不存在: %s，跳过该因子", ic_file)
            continue
        
        logger.info("加载 IC 结果: %s", ic_file)
        
        with open(ic_file, 'r', encoding='utf-8') as f:
            ic_data = json.load(f)
        
        # 提取 ic_metrics 字段（IC统计结果）
        if 'ic_metrics' in ic_data:
            ic_results[factor_name] = ic_data['ic_metrics']
        elif 'summary' in ic_data:
            ic_results[factor_name] = ic_data['summary']
        else:
            logger.warning("IC结果文件缺失 'ic_metrics' 字段: %s", ic_file)
            ic_results[factor_name] = {}
    
    if not ic_results:
        raise ValueError(f"未找到任何 IC 结果文件，路径: {ic_result_dir}")
    
    logger.info("加载 IC 结果: %d 个因子", len(ic_results))
    
    return ic_results


def load_ic_daily(
    factor_names: List[str],
    ic_result_dir: Optional[Path] = None,
    return_period: str = '1d',
    logger: Optional[logging.Logger] = None
) -> Dict[str, pd.DataFrame]:
    """从 factor_ic/result/ 加载 IC 每日序列
    
    从现有的 IC 分析结果文件中提取 ic_values 和 dates 字段，
    用于滚动ICIR加权计算。
    
    Args:
        factor_names: 因子名称列表
        ic_result_dir: IC结果目录路径
        return_period: 收益周期
        logger: 日志对象
    
    Returns:
        Dict[因子名, IC每日DataFrame]
        {
            'rsi': DataFrame(columns=['date', 'ic', 'ic_sign', ...]),
            'volume_ratio': DataFrame(...)
        }
    """
    if logger is None:
        from comprehensive_factor.common.logger_config import get_logger
        logger = get_logger(__name__)
    
    if ic_result_dir is None:
        ic_result_dir = DEFAULT_IC_RESULT_DIR
    
    ic_result_dir = Path(ic_result_dir)
    
    ic_daily_data = {}
    
    for factor_name in factor_names:
        # IC结果文件命名: ic_<因子名>_<收益周期>_analysis_result.json
        ic_file = ic_result_dir / f'ic_{factor_name}_{return_period}_analysis_result.json'
        
        if not ic_file.exists():
            logger.warning("IC结果文件不存在: %s，跳过该因子", ic_file)
            continue
        
        logger.info("加载 IC 每日序列: %s", ic_file)
        
        with open(ic_file, 'r', encoding='utf-8') as f:
            ic_data = json.load(f)
        
        # 提取 ic_values 和 dates/valid_dates 字段
        if 'ic_values' not in ic_data:
            logger.warning("IC结果文件缺失 'ic_values' 字段: %s", ic_file)
            continue
        
        # 使用 valid_dates（有效日期）或 dates
        dates = ic_data.get('valid_dates', ic_data.get('dates', []))
        ic_values = ic_data.get('ic_values', [])
        
        if len(dates) != len(ic_values):
            logger.warning(
                "日期与IC值数量不一致: dates=%d, ic_values=%d, 文件: %s",
                len(dates), len(ic_values), ic_file
            )
            # 使用较短的那个
            min_len = min(len(dates), len(ic_values))
            dates = dates[:min_len]
            ic_values = ic_values[:min_len]
        
        # 构建 DataFrame
        daily_df = pd.DataFrame({
            'date': dates,
            'ic': ic_values,
            'ic_sign': [1 if v > 0 else -1 if v < 0 else 0 for v in ic_values]
        })
        
        ic_daily_data[factor_name] = daily_df
    
    if not ic_daily_data:
        raise ValueError(f"未找到任何 IC 每日数据，路径: {ic_result_dir}")
    
    logger.info("加载 IC 每日序列: %d 个因子", len(ic_daily_data))
    
    return ic_daily_data


def standardize_factors(
    factor_df: pd.DataFrame,
    factor_cols: List[str],
    logger: Optional[logging.Logger] = None
) -> pd.DataFrame:
    """截面标准化因子值
    
    每日对每个因子做截面标准化（减均值除标准差）。
    
    Args:
        factor_df: 因子 DataFrame（包含 date, asset, 因子列）
        factor_cols: 需标准化的因子列名
        logger: 日志对象
    
    Returns:
        标准化后的 DataFrame（新增标准化因子列，命名: <因子列>_std）
    """
    if logger is None:
        from comprehensive_factor.common.logger_config import get_logger
        logger = get_logger(__name__)
    
    factor_df = factor_df.copy()
    
    for col in factor_cols:
        std_col = f'{col}_std'
        
        # 每日截面标准化
        factor_df[std_col] = factor_df.groupby('date')[col].transform(
            lambda x: (x - x.mean()) / x.std() if x.std() > 0 else 0
        )
        
        # NaN 处理：原因子值为 NaN 时标准化后仍为 NaN
        factor_df.loc[factor_df[col].isna(), std_col] = np.nan
    
    logger.info("因子标准化完成: %d 个因子", len(factor_cols))
    
    return factor_df


def calc_factor_correlation(
    factor_df: pd.DataFrame,
    factor_cols: List[str],
    logger: Optional[logging.Logger] = None
) -> pd.DataFrame:
    """计算因子相关性矩阵
    
    Args:
        factor_df: 因子 DataFrame
        factor_cols: 因子列名
        logger: 日志对象
    
    Returns:
        相关性矩阵 DataFrame
    """
    if logger is None:
        from comprehensive_factor.common.logger_config import get_logger
        logger = get_logger(__name__)
    
    # 使用标准化后的因子计算相关性（更稳定）
    std_cols = [f'{col}_std' for col in factor_cols]
    
    corr_matrix = factor_df[std_cols].corr()
    
    # 还原原始列名作为索引
    corr_matrix.index = factor_cols
    corr_matrix.columns = factor_cols
    
    logger.info("因子相关性矩阵计算完成")
    
    return corr_matrix