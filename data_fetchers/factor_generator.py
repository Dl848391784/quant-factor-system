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
- v1.12 (2026-05-25): Bug修复（output_cols注释修正OHLCV顺序、dates排序补充注释、total_records除零保护、版本历史移除硬编码行号、argparse版本描述修正）+ MODULE.md日志换行符规范补充（错误日志允许多行格式化）
- v1.13 (2026-05-25): Bug修复（缩进错误修正Step8注释、numpy.int64类型转换JSON兼容、__main__块改为CLI入口调用main()、测试代码移至test_cases/test_factor_generator.py）
- v1.14 (2026-05-25): Bug修复（除零保护统一使用_calc_pct模块级函数、_EXTENDED_FACTOR_COLS常量替代硬编码切片、docstring补充空数据异常声明、turnover_missing显式int转换）
- v1.15 (2026-05-25): Bug修复（docstring移除JSONDecodeError声明、temp_path.unlink改用missing_ok=True消除TOCTOU竞争窗口）
- v1.16 (2026-05-25): 代码结构优化（_BASE_COLS+_OUTPUT_COLS常量统一output_cols引用关系、__main__块移除sys重复导入、_calc_pct函数语义修正为通用百分比计算）
- v1.17 (2026-05-25): Bug修复（output_path父目录不存在时创建、dates字段从output_df取数据来源更清晰、docstring示例值改为范围说明）
- v1.18 (2026-05-25): Bug修复（版本历史描述修正v1.12日志换行符为规范补充而非修复、_EXTENDED_FACTOR_COLS返回副本防止外部修改）
- v1.19 (2026-05-25): 代码结构优化（常量改为元组防止意外修改、docstring示例补充注释说明返回列表副本、factor_df显式释放内存）
- v1.20 (2026-05-25): 代码结构优化（mkdir移入try块统一异常处理、_OUTPUT_COLS注释移到常量定义处、_calc_pct docstring补充示例、main()异常日志增加类型名）
- v1.21 (2026-05-25): Bug修复（docstring Example格式修正：注释放在>>>行、返回值行无注释、增加isinstance示例）
- v1.22 (2026-05-25): 代码结构优化（清理output_cols冗余别名、mkdir和temp_path职责分离、base_data/turnover_data内存释放、missing_cols错误信息改进）
- v1.23 (2026-05-26): 代码结构优化（tuple类型注解改为tuple[str, ...]更精确表达字符串元组）
- v1.24 (2026-05-26): Bug修复+代码结构优化（turnover_df内存释放、docstring Example标记非运行示例、元组转列表pandas兼容）

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

# 扩展因子列名（元组防止意外修改）
_EXTENDED_FACTOR_COLS: tuple[str, ...] = ('bollinger_pb', 'kdj_j', 'turnover_surge')

# 基础列名（元组防止意外修改）
_BASE_COLS: tuple[str, ...] = ('date', 'asset', 'open', 'close', 'high', 'low', 'rsi_6', 'volume_ratio_5')

# 输出列名（基础列 + 扩展因子，元组防止意外修改）
# 结构说明：
# _OUTPUT_COLS[0:2]  = date, asset（索引字段）
# _OUTPUT_COLS[2:6]  = open, close, high, low（行情数据，非标准 OHLCV 顺序）
# _OUTPUT_COLS[6:8]  = rsi_6, volume_ratio_5（基础因子，来自输入）
# _OUTPUT_COLS[8:]   = bollinger_pb, kdj_j, turnover_surge（扩展因子，本次计算）
_OUTPUT_COLS: tuple[str, ...] = _BASE_COLS + _EXTENDED_FACTOR_COLS


# ============================================================================
# 模块级私有辅助函数
# ============================================================================

def _calc_pct(count: int, total: int) -> float:
    """
    计算百分比（除零保护）
    
    Args:
        count: 记录数（分子，如有效记录数、缺失记录数等）
        total: 总记录数（分母）
        
    Returns:
        float: 百分比（0.0-100.0），空数据时返回 0.0
        
    Example:
        >>> _calc_pct(80, 100)  # 有效记录百分比
        80.0
        >>> _calc_pct(20, 100)  # 缺失记录百分比
        20.0
        >>> _calc_pct(50, 0)    # 空数据，返回 0.0
        0.0
        
    Note:
        - 通用百分比计算函数，可用于有效记录、缺失记录等场景
        - 参数语义由调用方决定（count 是分子，total 是分母）
    """
    if total <= 0:
        return 0.0
    return round(count / total * 100, 2)


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
        ValueError: 数据格式不正确（缺少 'data' 字段）、JSON 解析失败、gzip 文件损坏、或输入数据为空
        KeyError: 必需字段不存在
        RuntimeError: 文件系统错误（磁盘/权限/IO）或未知保存错误
        
    Note:
        - 输出到 cache/factor_data/factor_data_extended.json.gz
        - 复用 factor_ic 计算函数（遵循强制复用规范）
        - 公共模块接收 logger 参数，日志可追溯调用方
        - 运行耗时统计方便性能分析
        - 空数据场景：所有百分比计算均有除零保护，返回 0.0
        - JSONDecodeError 已内部捕获并转换为 ValueError，调用方不会收到 JSONDecodeError
        
    Example:
        # 以下为示例用法，非实际运行（generate_all_factors 需要输入数据文件）
        >>> from data_fetchers.factor_generator import generate_all_factors
        >>> metadata = generate_all_factors()  # 需要 cache/factor_data/*.json.gz
        >>> metadata['factor_columns']  # 返回列表副本，防止外部修改
        ['bollinger_pb', 'kdj_j', 'turnover_surge']
        >>> isinstance(metadata['elapsed_seconds'], float)
        True
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
    
    # 显式释放 base_data 内存（JSON 加载的大对象）
    del base_data
    
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
    
    # 显式释放 turnover_data 内存（JSON 加载的大对象）
    del turnover_data
    
    logger.info("  换手率数据记录数: %d", len(turnover_df))
    
    # 合并换手率
    factor_df = factor_df.merge(
        turnover_df[['date', 'asset', 'turnover_rate']],
        on=['date', 'asset'],
        how='left'
    )
    
    # 显式释放 turnover_df 内存（merge 完成后不再需要）
    del turnover_df
    
    # 检查换手率缺失情况
    turnover_missing = int(factor_df['turnover_rate'].isna().sum())
    if turnover_missing > 0:
        logger.warning("  换手率缺失记录数: %d (%.2f%%)", turnover_missing, _calc_pct(turnover_missing, len(factor_df)))
    
    logger.info("  合并后记录数: %d", len(factor_df))
    
    # ========== Step 3: 计算 bollinger_pb ==========
    logger.info("Step 3: 计算布林带 %B 因子...")
    
    factor_df = calculate_bollinger_pb(factor_df)
    
    bollinger_valid = int(factor_df['bollinger_pb'].notna().sum())
    logger.info("  有效 bollinger_pb: %d (%.2f%%)", bollinger_valid, _calc_pct(bollinger_valid, len(factor_df)))
    
    # ========== Step 4: 计算 kdj_j ==========
    logger.info("Step 4: 计算 KDJ_J 因子...")
    
    factor_df = calculate_kdj_j(factor_df)
    
    kdj_valid = int(factor_df['kdj_j'].notna().sum())
    logger.info("  有效 kdj_j: %d (%.2f%%)", kdj_valid, _calc_pct(kdj_valid, len(factor_df)))
    
    # ========== Step 5: 计算 turnover_surge ==========
    logger.info("Step 5: 计算换手率突增因子...")
    
    factor_df = calculate_turnover_surge(factor_df)
    
    surge_valid = int(factor_df['turnover_surge'].notna().sum())
    logger.info("  有效 turnover_surge: %d (%.2f%%)", surge_valid, _calc_pct(surge_valid, len(factor_df)))
    
    # ========== Step 6: 格式化输出 ==========
    logger.info("Step 6: 格式化输出...")
    
    factor_df['date'] = factor_df['date'].dt.strftime('%Y-%m-%d')
    
    # 检查列是否存在（直接使用模块级常量 _OUTPUT_COLS）
    missing_cols = [col for col in _OUTPUT_COLS if col not in factor_df.columns]
    if missing_cols:
        raise KeyError(
            f"输出列不存在: {missing_cols}，"
            f"请检查因子计算函数的输出列名是否与 _EXTENDED_FACTOR_COLS 一致"
        )
    
    output_df = factor_df[list(_OUTPUT_COLS)].copy()  # 元组转列表，pandas 列选择需要列表
    
    # 显式释放 factor_df 内存（可能包含中间列，比 output_df 更多）
    del factor_df
    
    # ========== Step 7: 保存输出 ==========
    logger.info("Step 7: 保存输出...")
    
    # dates 字段：字符串排序对 YYYY-MM-DD 格式正确（字典序与日期序一致）
    # 从 output_df 取 dates，数据来源更清晰
    output_data = {
        'dates': sorted(output_df['date'].unique().tolist()),
        'data': output_df.to_dict('records')
    }
    
    # 确保父目录存在（职责分离：mkdir 单独处理，异常信息更精确）
    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        raise RuntimeError(f"创建输出目录失败: {output_path.parent}, {type(e).__name__}: {e}") from e
    
    # 使用临时文件 + os.replace 原子写入（遵循 PROJECT.md 文件写入规范）
    temp_path = output_path.parent / (output_path.name + '.tmp')
    try:
        with gzip.open(temp_path, 'wt') as f:
            json.dump(output_data, f)
        os.replace(temp_path, output_path)
    except OSError as e:
        # 文件系统错误（磁盘/权限/IO，PermissionError 是 OSError 子类）
        temp_path.unlink(missing_ok=True)  # 原子操作，消除 TOCTOU 竞争窗口
        raise RuntimeError(f"文件系统错误: {output_path}, {type(e).__name__}: {e}") from e
    except Exception as e:
        # 未知错误（兜底）
        temp_path.unlink(missing_ok=True)  # 原子操作，消除 TOCTOU 竞争窗口
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
            'bollinger_pb': _calc_pct(bollinger_valid, total_records),
            'kdj_j': _calc_pct(kdj_valid, total_records),
            'turnover_surge': _calc_pct(surge_valid, total_records),
        },
        'factor_columns': list(_EXTENDED_FACTOR_COLS),  # 扩展因子列（返回副本，防止外部修改）
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
        logger.error("执行失败 [%s]: %s", type(e).__name__, str(e))
        return 1
    finally:
        # 清理 logger 处理器
        for handler in list(logger.handlers):
            handler.close()
            logger.removeHandler(handler)


# ============================================================================
# __main__ CLI 入口
# ============================================================================

if __name__ == '__main__':
    # CLI 入口：调用 main() 函数，测试代码已移至 test_cases/test_factor_generator.py
    # 注意：sys 已在顶部条件块导入，无需重复导入
    sys.exit(main())