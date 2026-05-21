#!/usr/bin/env python3
"""
数据完整性检查模块

提供因子IC缓存数据完整性检查功能：
- check_data_completeness: 检查数据完整性，返回处理模式
- check_incremental_update: 检查是否可增量更新

作者: 云舟
日期: 2026-05-07
"""

from pathlib import Path
from typing import Tuple, List, Optional, Dict, Any
import gzip
import json
import gc


# 默认路径配置
BASE_DIR = Path(__file__).resolve().parent.parent.parent
CACHE_DIR = BASE_DIR / 'cache'
FACTOR_IC_DIR = CACHE_DIR / 'factor_ic'
FACTOR_DATA_DIR = CACHE_DIR / 'factor_data'
FACTOR_IC_RESULT_DIR = BASE_DIR / 'factor_ic' / 'result'  # 规范输出目录


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


def get_factor_data_dates() -> Tuple[List[str], Optional[str]]:
    """
    获取 factor_data.json.gz 的日期列表和最新日期
    
    Returns:
        (日期列表, 最新日期)
        日期格式: "YYYY-MM-DD"
    """
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
            # 使用 str() 强制转换，防止 datetime/int 等非字符串类型导致 sorted() TypeError
            dates = sorted(set(str(r['date']) for r in data.get('data', []) if r.get('date') is not None))
        
        latest_date = dates[-1] if dates else None
        
        del data
        gc.collect()
        
        return dates, latest_date
    except Exception as e:
        print(f"[警告] 读取 factor_data 失败: {e}")
        return [], None


def get_cache_latest_date(factor_name: str) -> Optional[str]:
    """
    获取因子IC缓存的最新日期
    
    Args:
        factor_name: 因子名称 (如 'rsi_1d', 'kdj_j_3d')
        
    Returns:
        最新日期字符串 (YYYY-MM-DD) 或 None
    """
    cache_file = FACTOR_IC_RESULT_DIR / f'ic_{factor_name}_analysis_result.json'
    
    if not cache_file.exists():
        return None
    
    try:
        with open(cache_file, 'r', encoding='utf-8') as f:
            result = json.load(f)
        
        # dates 字段在顶层
        dates = result.get('dates', [])
        
        if not dates:
            # 兼容旧格式：ic_series.dates
            ic_series = result.get('ic_series', {})
            dates = ic_series.get('dates', [])
        
        if not dates:
            return None
        
        # 格式可能是 "2026-04-03 00:00:00" 或 "2026-04-03"
        latest = dates[-1]
        if ' ' in latest:
            latest = latest.split()[0]
        
        return latest
    except Exception as e:
        print(f"[警告] 读取缓存失败 {factor_name}: {e}")
        return None


def check_data_completeness(
    factor_name: str
) -> Tuple[str, List[str], Dict[str, Any]]:
    """
    检查因子IC数据的完整性
    
    Args:
        factor_name: 因子名称 (如 'kdj_j', 'bollinger_pb')
        
    Returns:
        (mode, missing_dates, info)
        
        mode: 处理模式
            - 'full': 需要全量计算（缓存不存在）
            - 'incremental': 可增量更新（有缺失日期）
            - 'skip': 无需更新（数据已最新）
            
        missing_dates: 缺失日期列表
        
        info: 额外信息字典
            - cache_file: 缓存文件路径
            - cache_exists: 缓存是否存在
            - cache_latest_date: 缓存最新日期
            - source_latest_date: 数据源最新日期
            - total_dates: 数据源总天数
            - missing_count: 缺失天数
            
    示例:
        >>> mode, missing, info = check_data_completeness('kdj_j')
        >>> print(f"模式: {mode}, 缺失天数: {len(missing)}")
    """
    # 初始化信息
    info: Dict[str, Any] = {
        'cache_file': str(FACTOR_IC_RESULT_DIR / f'ic_{factor_name}_analysis_result.json'),
        'cache_exists': False,
        'cache_latest_date': None,
        'source_latest_date': None,
        'total_dates': 0,
        'missing_count': 0
    }
    
    # 检查数据源
    all_dates, source_latest = get_factor_data_dates()
    info['source_latest_date'] = source_latest
    info['total_dates'] = len(all_dates)
    
    if not all_dates:
        # 数据源不可用
        return 'skip', [], info
    
    # 检查缓存是否存在
    cache_latest = get_cache_latest_date(factor_name)
    info['cache_latest_date'] = cache_latest
    info['cache_exists'] = cache_latest is not None
    
    if cache_latest is None:
        # 缓存不存在，需要全量计算
        # 返回所有日期，让调用方决定计算范围
        missing_dates = all_dates
        info['missing_count'] = len(missing_dates)
        return 'full', missing_dates, info
    
    # 计算缺失日期
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
            - True: 有缓存且存在缺失日期
            - False: 无缓存或数据已最新
            
        missing_dates: 缺失日期列表
            
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

def get_cache_info(factor_name: str) -> Dict[str, Any]:
    """
    获取因子IC缓存的信息摘要
    
    Args:
        factor_name: 因子名称 (如 'rsi_1d', 'kdj_j_3d')
        
    Returns:
        信息字典
    """
    cache_file = FACTOR_IC_RESULT_DIR / f'ic_{factor_name}_analysis_result.json'
    
    info = {
        'factor_name': factor_name,
        'cache_file': str(cache_file),
        'exists': cache_file.exists(),
        'file_size_mb': 0,
        'ic_metrics': None,
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
        
        # IC指标
        info['ic_metrics'] = data.get('ic_metrics', {})
        
        # 天数和最新日期
        ic_series = data.get('ic_series', {})
        dates = ic_series.get('dates', [])
        info['n_days'] = len(dates)
        info['latest_date'] = dates[-1] if dates else None
        
    except Exception as e:
        info['error'] = str(e)
    
    return info


if __name__ == '__main__':
    """测试"""
    print("=" * 60)
    print("数据完整性检查模块测试")
    print("=" * 60)
    
    # 测试几个因子
    test_factors = ['kdj_j', 'bollinger_pb', 'turnover_surge', 'rsi', 'volume_ratio']
    
    for factor in test_factors:
        print(f"\n【{factor}】")
        mode, missing, info = check_data_completeness(factor)
        print(f"  模式: {mode}")
        print(f"  缓存存在: {info['cache_exists']}")
        print(f"  缓存最新日期: {info['cache_latest_date'] or '无'}")
        print(f"  数据源最新日期: {info['source_latest_date'] or '无'}")
        print(f"  缺失天数: {info['missing_count']}")
        if missing:
            print(f"  缺失日期范围: {missing[0]} ~ {missing[-1]}")