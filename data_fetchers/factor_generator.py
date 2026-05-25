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
- v1.2 (2026-05-25): 清理冗余导入/常量 + os 导入规范化 + 数据验证补全 + CLI 参数补全 + 运行耗时统计
- v1.3 (2026-05-25): 常量命名私有化（DEFAULT_CACHE_DIR → _DEFAULT_CACHE_DIR）+ 导入顺序 PEP 8 合规化（argparse 为 CLI 入口特有导入，保留函数内导入）
- v1.4 (2026-05-25): 流程文档创建 + 测试用例创建 + output_cols 注释补全（索引含义）+ valid_records_percent 字段补全
- v1.5 (2026-05-25): 条件导入合并简化（移除 __main__ 重复 sys.path.insert）+ 异常处理精确化（OSError 涵盖 PermissionError）+ metadata 字段注释补全
- v1.6 (2026-05-25): JSONDecodeError 内存优化（提取 lineno/colno/msg）+ CLI 入口返回退出码 + __main__ 测试补全 valid_records_percent + 条件导入合并简化（CLI 入口块）
- v1.7 (2026-05-25): docstring RuntimeError 补全 + main() 返回类型注解（-> int）
- v1.8 (2026-05-25): gzip.BadGzipFile 异常处理补全（gzip 文件损坏）
- v1.9 (2026-05-25): 冗余导入清理（移除条件导入块的 _Path）
- v1.10 (2026-05-25): 导入冗余清理（合并 gzip 导入、移除 main() 函数内冗余 logging 导入）
- v1.11 (2026-05-25): Bug修复（条件导入合并到顶部、__main__循环导入修复、PermissionError重复捕获简化、temp_path后缀处理修复）
- v1.12 (2026-05-25): Bug修复（output_cols注释修正OHLCV顺序、dates排序补充注释、total_records除零保护、版本历史移除硬编码行号、argparse版本描述修正、logger换行符修复）

作者: 云瑶
"""
import gzip
import json
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional, Union

import pandas as pd

# ============================================================================
# 条件导入：__main__ 时添加 sys.path + 绝对导入，其他时候使用相对导入
# 注意：sys.path.insert 是必要的，因为脚本需要能够直接运行
# 遵循 stock_utils.py 的条件导入模式
if __name__ == '__main__':
    import sys
    project_root = Path(__file__).parent.parent
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))
    from factor_ic.ic_bollinger_pb_1d import calculate_bollinger_pb
    from factor_ic.ic_kdj_j_1d import calculate_kdj_j
    from factor_ic.ic_turnover_surge_1d import calculate_turnover_surge
    from data_fetchers.common.logger_config import setup_logger
else:
    from factor_ic.ic_bollinger_pb_1d import calculate_bollinger_pb
    from factor_ic.ic_kdj_j_1d import calculate_kdj_j
    from factor_ic.ic_turnover_surge_1d import calculate_turnover_surge
    from .common.logger_config import setup_logger

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
# 默认路径配置（私有常量）
# ============================================================================

_DEFAULT_CACHE_DIR = Path(__file__).parent.parent / 'cache' / 'factor_data'


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
        Dict[str, Any]: 元数据字典（包含生成时间、因子列表、运行耗时等）
        
    Raises:
        FileNotFoundError: 输入数据文件不存在
        json.JSONDecodeError: JSON 解析失败
        ValueError: 数据格式不正确（缺少 'data' 字段）、JSON 解析失败位置信息、或 gzip 文件损坏
        KeyError: 必需字段不存在
        RuntimeError: 文件系统错误（磁盘/权限/IO）或未知保存错误
        
    Note:
        - 输出到 cache/factor_data/factor_data_extended.json.gz
        - 复用 factor_ic 计算函数（遵循强制复用规范）
        - 公共模块接收 logger 参数，日志可追溯调用方
        - 运行耗时统计方便性能分析
        
    Example:
        >>> from data_fetchers.factor_generator import generate_all_factors
        >>> metadata = generate_all_factors()
        >>> metadata['factor_columns']
        ['bollinger_pb', 'kdj_j', 'turnover_surge']
        >>> metadata['elapsed_seconds']
        120.5
    """
    start_time = datetime.now()
    logger = get_module_logger(logger)
    
    # 默认路径
    factor_data_path = Path(factor_data_path) if factor_data_path else _DEFAULT_CACHE_DIR / 'factor_data.json.gz'
    turnover_data_path = Path(turnover_data_path) if turnover_data_path else _DEFAULT_CACHE_DIR / 'turnover_rate_data.json.gz'
    output_path = Path(output_path) if output_path else _DEFAULT_CACHE_DIR / 'factor_data_extended.json.gz'
    
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
    except gzip.BadGzipFile as e:
        raise ValueError(f"gzip 文件损坏: {factor_data_path}") from e
    except json.JSONDecodeError as e:
        # JSONDecodeError 内存优化：提取关键信息，避免 e.doc 内存翻倍
        logger.error(
            "JSON 解析失败\n"
            "文件路径: %s\n"
            "错误位置: 行 %d, 列 %d\n"
            "错误信息: %s",
            factor_data_path, e.lineno, e.colno, e.msg
        )
        raise ValueError(f"JSON解析失败: {factor_data_path}, 位置 {e.pos}") from e
    
    # 数据验证：检查 'data' 字段存在
    if 'data' not in base_data:
        raise ValueError(f"基础因子数据缺少 'data' 字段: {factor_data_path}")
    
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
    except gzip.BadGzipFile as e:
        raise ValueError(f"gzip 文件损坏: {turnover_data_path}") from e
    except json.JSONDecodeError as e:
        # JSONDecodeError 内存优化：提取关键信息，避免 e.doc 内存翻倍
        logger.error(
            "JSON 解析失败\n"
            "文件路径: %s\n"
            "错误位置: 行 %d, 列 %d\n"
            "错误信息: %s",
            turnover_data_path, e.lineno, e.colno, e.msg
        )
        raise ValueError(f"JSON解析失败: {turnover_data_path}, 位置 {e.pos}") from e
    
    # 数据验证：检查 'data' 字段存在
    if 'data' not in turnover_data:
        raise ValueError(f"换手率数据缺少 'data' 字段: {turnover_data_path}")
    
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
    
    # 检查换手率缺失情况
    turnover_missing = factor_df['turnover_rate'].isna().sum()
    if turnover_missing > 0:
        logger.warning("  换手率缺失记录数: %d (%.2f%%)", turnover_missing, turnover_missing / len(factor_df) * 100)
    
    logger.info("  合并后记录数: %d", len(factor_df))
    
    # ========== Step 3: 计算 bollinger_pb ==========
    logger.info("Step 3: 计算布林带 %B 因子...")
    
    factor_df = calculate_bollinger_pb(factor_df)
    
    bollinger_valid = factor_df['bollinger_pb'].notna().sum()
    logger.info("  有效 bollinger_pb: %d (%.2f%%)", bollinger_valid, bollinger_valid / len(factor_df) * 100)
    
    # ========== Step 4: 计算 kdj_j ==========
    logger.info("Step 4: 计算 KDJ_J 因子...")
    
    factor_df = calculate_kdj_j(factor_df)
    
    kdj_valid = factor_df['kdj_j'].notna().sum()
    logger.info("  有效 kdj_j: %d (%.2f%%)", kdj_valid, kdj_valid / len(factor_df) * 100)
    
    # ========== Step 5: 计算 turnover_surge ==========
    logger.info("Step 5: 计算换手率突增因子...")
    
    factor_df = calculate_turnover_surge(factor_df)
    
    surge_valid = factor_df['turnover_surge'].notna().sum()
    logger.info("  有效 turnover_surge: %d (%.2f%%)", surge_valid, surge_valid / len(factor_df) * 100)
    
    # ========== Step 6: 格式化输出 ==========
    logger.info("Step 6: 格式化输出...")
    
    factor_df['date'] = factor_df['date'].dt.strftime('%Y-%m-%d')
    
    # 保留所有因子列（顺序：date/asset + 行情数据 + 基础因子 + 扩展因子）
    # output_cols[0:2]  = date, asset（索引字段）
    # output_cols[2:6]  = open, close, high, low（行情数据，非标准 OHLCV 顺序）
    # output_cols[6:8]  = rsi_6, volume_ratio_5（基础因子，来自输入）
    # output_cols[8:]   = bollinger_pb, kdj_j, turnover_surge（扩展因子，本次计算）
    output_cols = [
        'date', 'asset', 'open', 'close', 'high', 'low',
        'rsi_6', 'volume_ratio_5',
        'bollinger_pb', 'kdj_j', 'turnover_surge'
    ]
    
    # 检查列是否存在
    missing_cols = [col for col in output_cols if col not in factor_df.columns]
    if missing_cols:
        raise KeyError(f"输出列不存在: {missing_cols}")
    
    output_df = factor_df[output_cols].copy()
    
    # ========== Step 7: 保存输出 ==========
    logger.info("Step 7: 保存输出...")
    
    # dates 字段：字符串排序对 YYYY-MM-DD 格式正确（字典序与日期序一致）
    output_data = {
        'dates': sorted(factor_df['date'].unique().tolist()),
        'data': output_df.to_dict('records')
    }
    
    # 使用临时文件 + os.replace 原子写入（遵循 PROJECT.md 文件写入规范）
    temp_path = output_path.parent / (output_path.name + '.tmp')
    try:
        with gzip.open(temp_path, 'wt') as f:
            json.dump(output_data, f)
        os.replace(temp_path, output_path)
    except OSError as e:
        # 文件系统错误（磁盘/权限/IO，PermissionError 是 OSError 子类）
        if temp_path.exists():
            temp_path.unlink()
        raise RuntimeError(f"文件系统错误: {output_path}, {type(e).__name__}: {e}") from e
    except Exception as e:
        # 未知错误（兜底）
        if temp_path.exists():
            temp_path.unlink()
        raise RuntimeError(f"未知错误保存失败: {output_path}") from e
    
    logger.info("  输出路径: %s", output_path)
    logger.info("  输出记录数: %d", len(output_df))
    
    # 计算运行耗时
    end_time = datetime.now()
    elapsed_seconds = (end_time - start_time).total_seconds()
    
# ========== Step 8: 返回元数据 ==========
    # metadata 字段说明：
    # - generated_at: 生成时间（格式 YYYY-MM-DD HH:MM:SS）
    # - elapsed_seconds: 运行耗时（秒，精度 .2f）
    # - total_records: 输出总记录数
    # - valid_records: 各因子有效记录数（绝对值）
    # - valid_records_percent: 各因子有效记录百分比（与日志输出一致，便于质量评估）
    # - factor_columns: 扩展因子列名（不含基础列和基础因子）
    # - input_sources: 输入数据源路径
    # - output_path: 输出文件路径
    total_records = len(output_df)
    
    # 除零保护：空数据时百分比返回 0.0
    def calc_pct(valid_count):
        return round(valid_count / total_records * 100, 2) if total_records > 0 else 0.0
    
    metadata = {
        'generated_at': end_time.strftime('%Y-%m-%d %H:%M:%S'),
        'elapsed_seconds': round(elapsed_seconds, 2),
        'total_records': total_records,
        'valid_records': {
            'bollinger_pb': bollinger_valid,
            'kdj_j': kdj_valid,
            'turnover_surge': surge_valid,
        },
        'valid_records_percent': {
            'bollinger_pb': calc_pct(bollinger_valid),
            'kdj_j': calc_pct(kdj_valid),
            'turnover_surge': calc_pct(surge_valid),
        },
        'factor_columns': output_cols[8:],  # 扩展因子列（不含基础列和基础因子）
        'input_sources': {
            'factor_data': str(factor_data_path),
            'turnover_data': str(turnover_data_path)
        },
        'output_path': str(output_path)
    }
    
    logger.info("=" * 40)
    logger.info("因子生成完成")
    logger.info("生成时间: %s", metadata['generated_at'])
    logger.info("运行耗时: %.2f 秒", metadata['elapsed_seconds'])
    logger.info("因子列: %s", metadata['factor_columns'])
    logger.info("=" * 40)
    
    return metadata


# ============================================================================
# CLI 入口
# ============================================================================

def main() -> int:
    """CLI 主入口"""
    import argparse
    
    parser = argparse.ArgumentParser(description='统一因子生成模块')
    parser.add_argument('--factor_data', type=str, default=None, help='基础因子数据路径')
    parser.add_argument('--turnover_data', type=str, default=None, help='换手率数据路径')
    parser.add_argument('--output', type=str, default=None, help='输出路径')
    parser.add_argument('--quiet', action='store_true', help='静默模式（只输出 ERROR 级别日志）')
    
    args = parser.parse_args()
    
    # 设置日志级别
    log_level = logging.ERROR if args.quiet else logging.INFO
    logger = setup_logger('factor_generator', level=log_level)
    
    # 参数路径转换
    factor_data_path = Path(args.factor_data) if args.factor_data else None
    turnover_data_path = Path(args.turnover_data) if args.turnover_data else None
    output_path = Path(args.output) if args.output else None
    
    try:
        metadata = generate_all_factors(
            factor_data_path=factor_data_path,
            turnover_data_path=turnover_data_path,
            output_path=output_path,
            logger=logger
        )
        logger.info("执行成功，退出码: 0")
        return 0
    except Exception as e:
        logger.error("执行失败: %s", str(e))
        return 1
    finally:
        # 清理 logger 处理器
        for handler in list(logger.handlers):
            handler.close()
            logger.removeHandler(handler)


# ============================================================================
# __main__ 测试
# ============================================================================

if __name__ == '__main__':
    # 测试模式：使用真实数据进行验证
    # 注意：setup_logger 已在顶部条件导入块导入，sys.path 已处理
    
    # 设置测试 logger（遵循 PROJECT.md 第780-839行规范，使用真实模块名）
    test_logger = setup_logger('data_fetchers.factor_generator', level=logging.INFO)
    
    test_logger.info("=" * 40)
    test_logger.info("factor_generator.py 自测试")
    test_logger.info("=" * 40)
    
    try:
        # 测试 1: 函数定义验证（直接使用已定义的函数，避免循环导入）
        test_logger.info("\n[测试 1] 函数定义验证...")
        test_logger.info("  generate_all_factors 已定义")
        test_logger.info("  get_module_logger 已定义")
        
        # 测试 2: get_module_logger 验证
        test_logger.info("\n[测试 2] get_module_logger 验证...")
        module_logger = get_module_logger()
        test_logger.info("  模块 logger 名称: %s", module_logger.name)
        assert module_logger.name == 'data_fetchers.factor_generator', "logger 名称不正确"
        test_logger.info("  logger 名称验证通过")
        
        # 测试 3: generate_all_factors 验证（使用真实数据）
        test_logger.info("\n[测试 3] generate_all_factors 验证...")
        test_logger.info("  使用真实数据进行测试...")
        
        metadata = generate_all_factors(logger=test_logger)
        
        # 验证返回字段
        test_logger.info("\n[测试 4] 返回字段验证...")
        required_fields = [
            'generated_at', 'elapsed_seconds', 'total_records',
            'valid_records', 'valid_records_percent', 'factor_columns',
            'input_sources', 'output_path'
        ]
        for field in required_fields:
            assert field in metadata, f"缺少必需字段: {field}"
            test_logger.info("  字段 %s 存在: %s", field, metadata[field])
        
        # 验证因子列
        test_logger.info("\n[测试 5] 因子列验证...")
        expected_factors = ['bollinger_pb', 'kdj_j', 'turnover_surge']
        assert metadata['factor_columns'] == expected_factors, "因子列不正确"
        test_logger.info("  因子列验证通过: %s", metadata['factor_columns'])
        
        # 验证有效记录数
        test_logger.info("\n[测试 6] 有效记录数验证...")
        for factor, count in metadata['valid_records'].items():
            test_logger.info("  %s 有效记录数: %d", factor, count)
            assert count > 0, f"{factor} 有效记录数为 0"
        
        test_logger.info("\n" + "=" * 40)
        test_logger.info("所有测试通过")
        test_logger.info("运行耗时: %.2f 秒", metadata['elapsed_seconds'])
        test_logger.info("=" * 40)
        
    except Exception as e:
        test_logger.error("测试失败: %s", str(e))
        raise
    finally:
        # 清理测试 logger 处理器
        for handler in list(test_logger.handlers):
            handler.close()
            test_logger.removeHandler(handler)