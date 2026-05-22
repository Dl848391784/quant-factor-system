#!/usr/bin/env python3
"""
数据完整性检查模块

提供因子IC缓存数据完整性检查功能：
- check_data_completeness: 检查数据完整性，返回处理模式
- check_incremental_update: 检查是否可增量更新

日期处理规范（2026-05-23）：
- 所有日期统一转换为字符串（str(d)），防止 datetime/int 类型导致 TypeError
- 日期格式统一截断为 YYYY-MM-DD（去除时间部分）
- 先截断格式，再去重排序（防止截断后产生重复）
- 统一使用 _normalize_dates 公共函数，确保逻辑一致性

作者: 云舟
日期: 2026-05-07
最后修改: 2026-05-23（修复日期处理、语义模糊、类型不一致）
"""

from pathlib import Path
from typing import Tuple, List, Optional, Dict, Any
import gzip
import json
import gc

from .logger_config import get_logger


# 默认路径配置
BASE_DIR = Path(__file__).resolve().parent.parent.parent
CACHE_DIR = BASE_DIR / 'cache'
FACTOR_IC_DIR = CACHE_DIR / 'factor_ic'
FACTOR_DATA_DIR = CACHE_DIR / 'factor_data'
FACTOR_IC_RESULT_DIR = BASE_DIR / 'factor_ic' / 'result'  # 规范输出目录


def _normalize_dates(dates: List[Any]) -> List[str]:
    """
    日期标准化公共函数
    
    处理步骤（顺序重要）：
    1. 强制转换为字符串（str(d)），防止 datetime/int 类型导致 TypeError
    2. 截断时间部分（"2026-04-03 00:00:00" → "2026-04-03"）
    3. 去重（防止截断后产生重复）
    4. 排序（确保最新日期在末尾）
    
    Args:
        dates: 原始日期列表（可以是 str/datetime/int 等类型）
        
    Returns:
        标准化后的日期列表（List[str]，格式 YYYY-MM-DD，已去重排序）
    
    示例:
        >>> _normalize_dates(['2026-04-03', '2026-04-03 00:00:00', datetime.date(2026, 4, 5)])
        ['2026-04-03', '2026-04-05']
    """
    if not dates:
        return []
    
    # 1. 强制转换为字符串
    str_dates = [str(d) for d in dates]
    
    # 2. 截断时间部分
    normalized = []
    for d in str_dates:
        if ' ' in d:
            normalized.append(d.split()[0])
        else:
            normalized.append(d)
    
    # 3. 去重 + 4. 排序
    return sorted(set(normalized))


def get_ic_output_path(factor_name: str) -> Path:
    """
    获取因子IC输出文件路径
    
    参数:
        factor_name: 因子名称（如 'rsi_1d', 'kdj_j_3d' 等）
    
    返回:
        Path: 输出文件路径，格式为 ic_<因子名>_analysis_result.json
    
    规范:
        目录: factor_ic/result/
        命名: ic_<因子名>_analysis_result.json
    """
    FACTOR_IC_RESULT_DIR.mkdir(parents=True, exist_ok=True)
    return FACTOR_IC_RESULT_DIR / f'ic_{factor_name}_analysis_result.json'


def get_factor_data_dates(logger=None) -> Tuple[List[str], Optional[str]]:
    """
    获取 factor_data.json.gz 的日期列表和最新日期
    
    Args:
        logger: 日志记录器（由调用方传入，默认使用模块 logger）
    
    Returns:
        (日期列表, 最新日期)
        日期格式: "YYYY-MM-DD"
    """
    if logger is None:
        logger = get_logger(__name__)
    
    factor_path = FACTOR_DATA_DIR / 'factor_data.json.gz'
    
    if not factor_path.exists():
        return [], None
    
    try:
        with gzip.open(factor_path, 'rt', encoding='utf-8') as f:
            data = json.load(f)
        
        meta = data.get('meta', {})
        dates = meta.get('dates', [])
        
        if not dates:
            # 从数据记录中提取日期
            dates = [r['date'] for r in data.get('data', []) if r.get('date') is not None]
        
        # 使用公共函数标准化日期（去重、排序、截断）
        dates = _normalize_dates(dates)
        
        latest_date = dates[-1] if dates else None
        
        del data
        gc.collect()
        
        return dates, latest_date
    except Exception as e:
        logger.warning(f"读取 factor_data 失败: {e}")
        return [], None


def _extract_dates_from_cache(data: Dict[str, Any]) -> Tuple[List[str], Optional[str]]:
    """
    从缓存数据中提取日期列表和最新日期（公共函数）
    
    统一处理顶层 dates 和 ic_series.dates 格式，确保逻辑一致性
    
    Args:
        data: 缓存 JSON 数据（已加载）
        
    Returns:
        (dates, latest_date)
        - dates: 日期列表，格式统一为 YYYY-MM-DD（已去重排序）
        - latest_date: 最新日期字符串或 None
    """
    # 优先读取顶层 dates 字段
    dates = data.get('dates', [])
    
    if not dates:
        # 兼容旧格式：ic_series.dates
        ic_series = data.get('ic_series', {})
        dates = ic_series.get('dates', [])
    
    if not dates:
        return [], None
    
    # 使用公共函数标准化日期（去重、排序、截断）
    dates = _normalize_dates(dates)
    
    latest_date = dates[-1] if dates else None
    return dates, latest_date


def get_cache_latest_date(factor_name: str, logger=None) -> Optional[str]:
    """
    获取因子IC缓存的最新日期
    
    Args:
        factor_name: 因子名称 (如 'rsi_1d', 'kdj_j_3d')
        logger: 日志记录器（由调用方传入，默认使用模块 logger）
        
    Returns:
        最新日期字符串 (YYYY-MM-DD) 或 None（文件不存在或读取失败）
    """
    if logger is None:
        logger = get_logger(__name__)
    
    cache_file = FACTOR_IC_RESULT_DIR / f'ic_{factor_name}_analysis_result.json'
    
    if not cache_file.exists():
        return None
    
    try:
        with open(cache_file, 'r', encoding='utf-8') as f:
            result = json.load(f)
        
        # 使用公共函数提取日期，确保逻辑一致性
        dates, latest_date = _extract_dates_from_cache(result)
        
        return latest_date
    except Exception as e:
        logger.warning(f"读取缓存失败 {factor_name}: {e}")
        return None


def check_data_completeness(
    factor_name: str,
    logger=None
) -> Tuple[str, List[str], Dict[str, Any]]:
    """
    检查因子IC数据的完整性
    
    Args:
        factor_name: 因子名称 (如 'kdj_j', 'bollinger_pb')
        logger: 日志记录器（由调用方传入，默认使用模块 logger）
        
    Returns:
        (mode, missing_dates, info)
        
        mode: 处理模式
            - 'full': 需要全量计算（缓存不存在）
            - 'incremental': 可增量更新（有缺失日期）
            - 'skip': 无需更新（数据已最新）
            
        missing_dates: 待计算日期列表（语义因 mode 而异）
            - 'full' 模式: 全部日期（需要全量计算）
            - 'incremental' 模式: 缺失日期（增量补充）
            - 'skip' 模式: 空列表
            - 注意：调用方应先判断 mode，再决定如何使用 missing_dates
            
        info: 额外信息字典
            - cache_file: 缓存文件路径
            - cache_exists: 缓存文件是否存在（基于文件存在性检查）
            - cache_latest_date: 缓存最新日期（读取成功时）
            - source_latest_date: 数据源最新日期
            - total_dates: 数据源总天数
            - missing_count: 待计算天数
            
    示例:
        >>> mode, missing, info = check_data_completeness('kdj_j')
        >>> print(f"模式: {mode}, 待计算天数: {len(missing)}")
    """
    if logger is None:
        logger = get_logger(__name__)
    
    cache_file = FACTOR_IC_RESULT_DIR / f'ic_{factor_name}_analysis_result.json'
    
    # 初始化信息
    info: Dict[str, Any] = {
        'cache_file': str(cache_file),
        'cache_exists': cache_file.exists(),  # 基于文件存在性检查
        'cache_latest_date': None,
        'source_latest_date': None,
        'total_dates': 0,
        'missing_count': 0
    }
    
    # 检查数据源
    all_dates, source_latest = get_factor_data_dates(logger=logger)
    info['source_latest_date'] = source_latest
    info['total_dates'] = len(all_dates)
    
    if not all_dates:
        # 数据源不可用
        return 'skip', [], info
    
    # 检查缓存最新日期
    cache_latest = get_cache_latest_date(factor_name, logger=logger)
    info['cache_latest_date'] = cache_latest
    
    # 注意：cache_latest 为 None 可能是文件不存在或读取失败
    # cache_exists 已通过文件存在性检查确定
    
    if not info['cache_exists']:
        # 缓存文件不存在，需要全量计算
        # missing_dates = all_dates（语义：全部需要计算，而非"缺失"）
        missing_dates = all_dates
        info['missing_count'] = len(missing_dates)
        return 'full', missing_dates, info
    
    if cache_latest is None:
        # 文件存在但读取失败，需要全量计算
        missing_dates = all_dates
        info['missing_count'] = len(missing_dates)
        return 'full', missing_dates, info
    
    # 计算缺失日期（大于缓存最新日期）
    missing_dates = [d for d in all_dates if d > cache_latest]
    info['missing_count'] = len(missing_dates)
    
    if len(missing_dates) > 0:
        # 有缺失日期，可增量更新
        return 'incremental', missing_dates, info
    else:
        # 数据已最新
        return 'skip', [], info


def check_incremental_update(
    factor_name: str
) -> Tuple[bool, List[str]]:
    """
    检查因子是否可以增量更新
    
    这是 check_data_completeness 的简化版本，
    只返回是否可增量更新和缺失日期列表。
    
    Args:
        factor_name: 因子名称
        
    Returns:
        (can_incremental, missing_dates)
        
        can_incremental: 是否可以增量更新
            - True: 缓存存在且有缺失日期（mode == 'incremental')
            - False: 无缓存、读取失败或数据已最新
            
        missing_dates: 缺失日期列表（仅在 can_incremental=True 时有意义）
            
    示例:
        >>> can_inc, missing = check_incremental_update('kdj_j')
        >>> if can_inc:
        ...     print(f"可增量更新，缺失天数: {len(missing)}")
    """
    mode, missing_dates, info = check_data_completeness(factor_name)
    
    can_incremental = (mode == 'incremental')
    
    return can_incremental, missing_dates


# ============================================================
# 便捷函数
# ============================================================

def get_cache_info(factor_name: str, logger=None) -> Dict[str, Any]:
    """
    获取因子IC缓存的信息摘要
    
    Args:
        factor_name: 因子名称 (如 'rsi_1d', 'kdj_j_3d')
        logger: 日志记录器（由调用方传入，默认使用模块 logger）
        
    Returns:
        信息字典
        - ic_metrics: IC指标字典（统一为空 dict，调用方判断 bool(ic_metrics)）
    """
    if logger is None:
        logger = get_logger(__name__)
    
    cache_file = FACTOR_IC_RESULT_DIR / f'ic_{factor_name}_analysis_result.json'
    
    info = {
        'factor_name': factor_name,
        'cache_file': str(cache_file),
        'exists': cache_file.exists(),
        'file_size_mb': 0,
        'ic_metrics': {},  # 统一初始值为空 dict
        'n_days': 0,
        'latest_date': None
    }
    
    if not cache_file.exists():
        return info
    
    try:
        # 文件大小
        info['file_size_mb'] = round(cache_file.stat().st_size / 1024 / 1024, 2)
        
        with open(cache_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        # IC指标（统一返回 dict，不存在时为空 dict）
        info['ic_metrics'] = data.get('ic_metrics') or {}
        
        # 使用公共函数提取日期，确保逻辑一致性
        dates, latest_date = _extract_dates_from_cache(data)
        info['n_days'] = len(dates)
        info['latest_date'] = latest_date
        
    except Exception as e:
        info['error'] = str(e)
    
    return info


if __name__ == '__main__':
    """测试"""
    # 创建 logger（__main__ 测试场景）
    logger = get_logger(__name__)
    
    logger.info("=" * 60)
    logger.info("数据完整性检查模块测试")
    logger.info("=" * 60)
    
    # 测试几个因子
    test_factors = ['kdj_j', 'bollinger_pb', 'turnover_surge', 'rsi', 'volume_ratio']
    
    for factor in test_factors:
        logger.info(f"【{factor}】")
        mode, missing, info = check_data_completeness(factor, logger=logger)
        logger.info(f"模式: {mode}")
        logger.info(f"缓存存在: {info['cache_exists']}")
        logger.info(f"缓存最新日期: {info['cache_latest_date'] or '无'}")
        logger.info(f"数据源最新日期: {info['source_latest_date'] or '无'}")
        logger.info(f"待计算天数: {info['missing_count']}")
        if missing:
            logger.info(f"待计算日期范围: {missing[0]} ~ {missing[-1]}")