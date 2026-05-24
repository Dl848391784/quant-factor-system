#!/usr/bin/env python3
"""
统一因子生成模块

职责：生成所有因子数据到缓存，提供单一数据源

遵循 PROJECT.md 规范：
- 输出到 cache/factor_data/
- 复用公共模块计算函数（遵循强制复用规范）
- 公共模块接收 logger 参数（遵循 PROJECT.md 公共模块日志规范）

版本历史：
- v1.0 (2026-05-24): 初始版本，支持 bollinger_pb、kdj_j、turnover_surge 因子
- v1.1 (2026-05-25): logger 参数化 + __all__ 导出 + 类型注解精确化 + 异常处理补全

作者: 云瑶
"""
import json
import gzip
import logging
import pandas as pd
import numpy as np
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Union, Any

# ============================================================================
# 模块级 fallback logger（遵循 PROJECT.md 公共模块日志规范）
# ============================================================================
_MODULE_LOGGER = logging.getLogger('data_fetchers.factor_generator')

# ============================================================================
# 公共 API 导出
# ============================================================================
__all__ = [
    'generate_all_factors',
    'get_module_logger',
]

# ============================================================================
# 参数统一管理
# ============================================================================

DEFAULT_N_BOLLINGER = 20     # 布林带移动平均周期
DEFAULT_K_BOLLINGER = 2.0    # 布林带标差倍数
DEFAULT_N_KDJ = 9            # KDJ RSV计算周期
DEFAULT_M1_KDJ = 3           # KDJ K值平滑周期
DEFAULT_M2_KDJ = 3           # KDJ D值平滑周期
DEFAULT_SURGE_WINDOW = 5     # 换手率突增均值计算窗口

EPSILON = 1e-10              # 避免除零阈值

DEFAULT_CACHE_DIR = Path(__file__).parent.parent / 'cache' / 'factor_data'


# ============================================================================
# logger 获取函数（遵循 PROJECT.md 公共模块日志规范）
# ============================================================================

def get_module_logger(logger: Optional[logging.Logger] = None) -> logging.Logger:
    """
    获取模块 logger
    
    Args:
        logger: 调用方传入的 logger（可选）
        
    Returns:
        logging.Logger: 模块 logger
        
    Raises:
        TypeError: logger 参数不是 logging.Logger 类型
        
    Note:
        - 如果 logger 为 None，返回模块级 fallback logger
        - 公共模块接收 logger 参数，日志可追溯调用方
        
    Example:
        >>> logger = get_module_logger()
        >>> logger.name
        'data_fetchers.factor_generator'
        >>> custom_logger = get_module_logger(logging.getLogger('my_app'))
        >>> custom_logger.name
        'my_app'
    """
    if logger is None:
        return _MODULE_LOGGER
    if not isinstance(logger, logging.Logger):
        raise TypeError(
            f"logger 必须是 logging.Logger 类型，实际类型: {type(logger).__name__}"
        )
    return logger


# ============================================================================
# 统一因子生成入口
# ============================================================================

def generate_all_factors(
    factor_data_path: Optional[Union[Path, str]] = None,
    turnover_data_path: Optional[Union[Path, str]] = None,
    output_path: Optional[Union[Path, str]] = None,
    logger: Optional[logging.Logger] = None
) -> Dict[str, Any]:
    """
    生成所有因子数据
    
    Args:
        factor_data_path: 基础因子数据路径（默认 factor_data.json.gz）
        turnover_data_path: 换手率数据路径（默认 turnover_rate_data.json.gz）
        output_path: 输出路径（默认 factor_data_extended.json.gz）
        logger: 调用方传入的 logger（可选）
        
    Returns:
        Dict[str, Any]: 元数据字典（包含生成时间、因子列表等）
        
    Raises:
        FileNotFoundError: 输入数据文件不存在
        json.JSONDecodeError: JSON 解析失败
        ValueError: 数据格式不正确
        
    Note:
        - 输出到 cache/factor_data/factor_data_extended.json.gz
        - 复用 factor_ic 计算函数（遵循强制复用规范）
        - 公共模块接收 logger 参数，日志可追溯调用方
        
    Example:
        >>> from data_fetchers.factor_generator import generate_all_factors
        >>> metadata = generate_all_factors()
        >>> metadata['factor_columns']
        ['bollinger_pb', 'kdj_j', 'turnover_surge']
    """
    logger = get_module_logger(logger)
    
    # 导入因子计算函数（遵循模块边界规范）
    from factor_ic.ic_kdj_j_1d import calculate_kdj_j
    from factor_ic.ic_bollinger_pb_1d import calculate_bollinger_pb
    from factor_ic.ic_turnover_surge_1d import calculate_turnover_surge
    
    # 默认路径
    factor_data_path = Path(factor_data_path) if factor_data_path else DEFAULT_CACHE_DIR / 'factor_data.json.gz'
    turnover_data_path = Path(turnover_data_path) if turnover_data_path else DEFAULT_CACHE_DIR / 'turnover_rate_data.json.gz'
    output_path = Path(output_path) if output_path else DEFAULT_CACHE_DIR / 'factor_data_extended.json.gz'
    
    logger.info("=" * 40)
    logger.info("统一因子生成模块")
    logger.info("=" * 40)
    
    # ========== Step 1: 加载基础因子数据 ==========
    logger.info("Step 1: 加载基础因子数据...")
    
    try:
        with gzip.open(factor_data_path, 'rt') as f:
            base_data = json.load(f)
    except FileNotFoundError:
        raise FileNotFoundError(f"基础因子数据文件不存在: {factor_data_path}")
    except json.JSONDecodeError as e:
        raise ValueError(f"基础因子数据 JSON 解析失败: {factor_data_path}") from e
    
    factor_df = pd.DataFrame(base_data['data'])
    factor_df['date'] = pd.to_datetime(factor_df['date'])
    
    logger.info("  基础数据记录数: %d", len(factor_df))
    logger.info("  基础因子列: rsi_6, volume_ratio_5")
    
    # ========== Step 2: 加载换手率数据 ==========
    logger.info("Step 2: 加载换手率数据...")
    
    try:
        with gzip.open(turnover_data_path, 'rt') as f:
            turnover_data = json.load(f)
    except FileNotFoundError:
        raise FileNotFoundError(f"换手率数据文件不存在: {turnover_data_path}")
    except json.JSONDecodeError as e:
        raise ValueError(f"换手率数据 JSON 解析失败: {turnover_data_path}") from e
    
    turnover_df = pd.DataFrame(turnover_data['data'])
    # 使用 format='mixed' 处理不同日期格式（有的带时间，有的不带）
    turnover_df['date'] = pd.to_datetime(turnover_df['date'], format='mixed')
    
    logger.info("  换手率数据记录数: %d", len(turnover_df))
    
    # 合并换手率
    factor_df = factor_df.merge(
        turnover_df[['date', 'asset', 'turnover_rate']],
        on=['date', 'asset'],
        how='left'
    )
    
    logger.info("  合并后记录数: %d", len(factor_df))
    
    # ========== Step 3: 计算 bollinger_pb ==========
    logger.info("Step 3: 计算布林带 %B 因子...")
    
    factor_df = calculate_bollinger_pb(factor_df)
    
    valid_count = factor_df['bollinger_pb'].notna().sum()
    logger.info("  有效 bollinger_pb: %d", valid_count)
    
    # ========== Step 4: 计算 kdj_j ==========
    logger.info("Step 4: 计算 KDJ_J 因子...")
    
    factor_df = calculate_kdj_j(factor_df)
    
    valid_count = factor_df['kdj_j'].notna().sum()
    logger.info("  有效 kdj_j: %d", valid_count)
    
    # ========== Step 5: 计算 turnover_surge ==========
    logger.info("Step 5: 计算换手率突增因子...")
    
    factor_df = calculate_turnover_surge(factor_df)
    
    valid_count = factor_df['turnover_surge'].notna().sum()
    logger.info("  有效 turnover_surge: %d", valid_count)
    
    # ========== Step 6: 格式化输出 ==========
    logger.info("Step 6: 格式化输出...")
    
    factor_df['date'] = factor_df['date'].dt.strftime('%Y-%m-%d')
    
    # 保留所有因子列
    output_cols = [
        'date', 'asset', 'open', 'close', 'high', 'low',
        'rsi_6', 'volume_ratio_5',
        'bollinger_pb', 'kdj_j', 'turnover_surge'
    ]
    
    output_df = factor_df[output_cols].copy()
    
    # ========== Step 7: 保存输出 ==========
    logger.info("Step 7: 保存输出...")
    
    output_data = {
        'dates': sorted(factor_df['date'].unique().tolist()),
        'data': output_df.to_dict('records')
    }
    
    # 使用临时文件 + os.replace 原子写入（遵循 PROJECT.md 文件写入规范）
    import os
    temp_path = output_path.with_suffix('.tmp')
    try:
        with gzip.open(temp_path, 'wt') as f:
            json.dump(output_data, f)
        os.replace(temp_path, output_path)
    except Exception as e:
        # 失败时清理临时文件
        if temp_path.exists():
            temp_path.unlink()
        raise RuntimeError(f"保存输出文件失败: {output_path}") from e
    
    logger.info("  输出路径: %s", output_path)
    logger.info("  输出记录数: %d", len(output_df))
    
    # ========== Step 8: 返回元数据 ==========
    metadata = {
        'generated_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'total_records': len(output_df),
        'factor_columns': output_cols[6:],  # 因子列（不含基础列）
        'input_sources': {
            'factor_data': str(factor_data_path),
            'turnover_data': str(turnover_data_path)
        },
        'output_path': str(output_path)
    }
    
    logger.info("=" * 40)
    logger.info("因子生成完成")
    logger.info("生成时间: %s", metadata['generated_at'])
    logger.info("因子列: %s", metadata['factor_columns'])
    logger.info("=" * 40)
    
    return metadata


# ============================================================================
# CLI 入口
# ============================================================================

# 条件导入：__main__ 时添加 sys.path + 绝对导入，其他时候使用相对导入
# 注意：sys.path.insert 是必要的，因为脚本需要能够直接运行
# 遵循 stock_utils.py 的条件导入模式
if __name__ == '__main__':
    import sys
    from pathlib import Path
    project_root = Path(__file__).parent.parent
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))
    from data_fetchers.common.logger_config import setup_logger
else:
    from .common.logger_config import setup_logger


def main():
    """CLI 主入口"""
    import argparse
    import logging
    
    parser = argparse.ArgumentParser(description='统一因子生成模块')
    parser.add_argument('--output', type=str, default=None, help='输出路径')
    parser.add_argument('--quiet', action='store_true', help='静默模式（只输出 ERROR 级别日志）')
    
    args = parser.parse_args()
    
    # 设置日志级别
    log_level = logging.ERROR if args.quiet else logging.INFO
    logger = setup_logger('factor_generator', level=log_level)
    
    output_path = Path(args.output) if args.output else None
    
    try:
        metadata = generate_all_factors(
            output_path=output_path,
            logger=logger
        )
        return metadata
    finally:
        # 清理 logger 处理器
        for handler in list(logger.handlers):
            handler.close()
            logger.removeHandler(handler)


# ============================================================================
# __main__ 测试
# ============================================================================

if __name__ == '__main__':
    main()