#!/usr/bin/env python3
"""
缓存管理模块

统一 gzip + JSON 缓存的读写操作。

作者: 云瑶
日期: 2026-05-24
"""

import gzip
import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

__all__ = [
    # 日志函数
    'get_module_logger',
    # 缓存读写函数
    'read_gzip_cache',
    'write_gzip_cache',
    'read_json_cache',
    'write_json_cache',
    'append_to_cache',
    'get_cache_file_info',
]

# 模块级 fallback logger（遵循 PROJECT.md 第783-857行规范）
_MODULE_LOGGER = None


def get_module_logger(logger: Optional[logging.Logger] = None) -> logging.Logger:
    """
    获取 logger，遵循 PROJECT.md 公共模块日志规范
    
    公共模块接收 logger 参数，调用方传入以追溯调用方。
    不传 logger 时使用模块级 fallback logger。
    
    Args:
        logger: 调用方传入的 logger（可选）
        
    Returns:
        Logger 对象
    """
    if logger is not None:
        return logger
    if _MODULE_LOGGER is None:
        _MODULE_LOGGER = logging.getLogger('data_fetchers.common.cache_manager')
    return _MODULE_LOGGER


def _is_gzip_file(path: Path) -> bool:
    """
    判断是否为 gzip 文件
    
    Args:
        path: 文件路径
        
    Returns:
        bool: 是否为 gzip 文件（后缀为 .gz）
    """
    return path.suffix == '.gz'


def _read_cache_impl(
    path: Path,
    use_gzip: bool,
    logger: logging.Logger
) -> Dict[str, Any]:
    """
    读取缓存的公共实现
    
    Args:
        path: 文件路径（已转换为 Path）
        use_gzip: 是否使用 gzip 解压
        logger: Logger 对象
        
    Returns:
        Dict: JSON 数据
        
    Raises:
        FileNotFoundError: 文件不存在
        ValueError: JSON 解析失败
    """
    if not path.exists():
        raise FileNotFoundError(f"缓存文件不存在: {path}")
    
    try:
        if use_gzip:
            with gzip.open(path, 'rt', encoding='utf-8') as f:
                data = json.load(f)
        else:
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
        logger.debug("成功读取缓存: %s", path)
        return data
    except json.JSONDecodeError as e:
        # 遵循 references/backtest-module-optimization-patterns.md Section 1.2
        # 避免传递完整 JSON 文档字符串导致内存翻倍
        logger.error(
            "JSON 解析失败\n"
            "文件路径: %s\n"
            "错误位置: 行 %d, 列 %d\n"
            "错误信息: %s",
            path, e.lineno, e.colno, e.msg
        )
        raise ValueError(f"JSON解析失败: {path}, 位置 {e.pos}") from e
    except Exception as e:
        logger.exception("读取缓存失败: %s", path)
        raise


def _write_cache_impl(
    path: Path,
    data: Dict[str, Any],
    use_gzip: bool,
    ensure_dir: bool,
    logger: logging.Logger
) -> None:
    """
    写入缓存的公共实现
    
    Args:
        path: 文件路径（已转换为 Path）
        data: 要写入的数据
        use_gzip: 是否使用 gzip 压缩
        ensure_dir: 是否自动创建目录
        logger: Logger 对象
        
    Raises:
        OSError: 文件写入失败
    """
    if ensure_dir:
        path.parent.mkdir(parents=True, exist_ok=True)
    
    try:
        if use_gzip:
            with gzip.open(path, 'wt', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, separators=(',', ':'))
        else:
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, separators=(',', ':'))
        logger.debug("成功写入缓存: %s", path)
    except Exception as e:
        logger.exception("写入缓存失败: %s", path)
        raise


def read_gzip_cache(
    path: Union[Path, str],
    logger: Optional[logging.Logger] = None
) -> Dict[str, Any]:
    """
    读取 gzip 压缩的 JSON 缓存
    
    Args:
        path: 缓存文件路径（.json.gz），支持 Path 或 str
        logger: 调用方传入的 logger（可选）
        
    Returns:
        Dict: 解压后的 JSON 数据
        
    Raises:
        FileNotFoundError: 文件不存在
        ValueError: JSON 解析失败（避免内存翻倍）
    """
    return _read_cache_impl(Path(path), use_gzip=True, logger=get_module_logger(logger))


def write_gzip_cache(
    path: Union[Path, str],
    data: Dict[str, Any],
    ensure_dir: bool = True,
    logger: Optional[logging.Logger] = None
) -> None:
    """
    写入 gzip 压缩的 JSON 缓存
    
    Args:
        path: 缓存文件路径（.json.gz），支持 Path 或 str
        data: 要写入的数据
        ensure_dir: 是否自动创建目录（默认 True）
        logger: 调用方传入的 logger（可选）
        
    Raises:
        OSError: 文件写入失败
    """
    _write_cache_impl(Path(path), data, use_gzip=True, ensure_dir=ensure_dir, logger=get_module_logger(logger))


def read_json_cache(
    path: Union[Path, str],
    logger: Optional[logging.Logger] = None
) -> Dict[str, Any]:
    """
    读取普通 JSON 缓存（非压缩）
    
    Args:
        path: 缓存文件路径（.json），支持 Path 或 str
        logger: 调用方传入的 logger（可选）
        
    Returns:
        Dict: JSON 数据
        
    Raises:
        FileNotFoundError: 文件不存在
        ValueError: JSON 解析失败（避免内存翻倍）
    """
    return _read_cache_impl(Path(path), use_gzip=False, logger=get_module_logger(logger))


def write_json_cache(
    path: Union[Path, str],
    data: Dict[str, Any],
    ensure_dir: bool = True,
    logger: Optional[logging.Logger] = None
) -> None:
    """
    写入普通 JSON 缓存（非压缩）
    
    Args:
        path: 缓存文件路径（.json），支持 Path 或 str
        data: 要写入的数据
        ensure_dir: 是否自动创建目录（默认 True）
        logger: 调用方传入的 logger（可选）
        
    Raises:
        OSError: 文件写入失败
    """
    _write_cache_impl(Path(path), data, use_gzip=False, ensure_dir=ensure_dir, logger=get_module_logger(logger))


def append_to_cache(
    path: Union[Path, str],
    new_data: List[Any],
    key: str = 'data',
    logger: Optional[logging.Logger] = None
) -> int:
    """
    增量追加数据到缓存
    
    读取现有缓存，追加新数据到指定 key 的列表中，重新写入。
    
    Args:
        path: 缓存文件路径，支持 Path 或 str
        new_data: 要追加的数据列表
        key: 数据存储的 key（默认 'data'）
        logger: 调用方传入的 logger（可选）
        
    Returns:
        int: 追加后的总数据量
    """
    path = Path(path)  # 统一转换为 Path
    logger = get_module_logger(logger)
    use_gzip = _is_gzip_file(path)  # 使用统一判断函数
    
    # 读取现有缓存
    existing: Dict[str, Any] = {}
    if path.exists():
        existing = _read_cache_impl(path, use_gzip, logger)
        existing_data = existing.get(key, [])
        
        # 防御性编程：验证数据类型
        if not isinstance(existing_data, list):
            logger.warning(
                "缓存数据结构异常: key '%s' 不是 list 类型\n"
                "实际类型: %s\n"
                "文件路径: %s\n"
                "使用空列表作为 fallback",
                key, type(existing_data).__name__, path
            )
            existing_data = []
    else:
        existing_data = []
    
    # 合并数据
    merged_data = existing_data + new_data
    total_count = len(merged_data)
    
    # 构建新缓存结构
    result = {key: merged_data}
    
    # 保留其他字段（如 dates）
    if path.exists():
        for k, v in existing.items():
            if k != key:
                result[k] = v
    
    # 写入缓存
    _write_cache_impl(path, result, use_gzip, ensure_dir=True, logger=logger)
    
    logger.info(
        "缓存追加完成: %s\n"
        "原有 %d 条\n"
        "新增 %d 条\n"
        "总计 %d 条",
        path, len(existing_data), len(new_data), total_count
    )
    return total_count


def get_cache_file_info(
    path: Union[Path, str],
    logger: Optional[logging.Logger] = None
) -> Dict[str, Any]:
    """
    获取缓存文件信息
    
    Args:
        path: 缓存文件路径，支持 Path 或 str
        logger: 调用方传入的 logger（可选）
        
    Returns:
        Dict: 文件信息（存在、大小、修改时间等）
    """
    path = Path(path)  # 统一转换为 Path
    logger = get_module_logger(logger)
    
    info = {
        'path': str(path),
        'exists': path.exists(),
        'size_mb': 0,
        'modified_time': None,
    }
    
    if path.exists():
        stat = path.stat()
        info['size_mb'] = stat.st_size / (1024 * 1024)
        info['modified_time'] = stat.st_mtime
        logger.debug("获取缓存文件信息: %s, 大小 %.4f MB", path, info['size_mb'])
    else:
        logger.warning("缓存文件不存在: %s", path)
    
    return info


if __name__ == '__main__':
    # 测试缓存读写（遵循 PROJECT.md 日志规范）
    
    # 配置测试日志
    logging.basicConfig(
        level=logging.DEBUG,
        format='%(asctime)s | %(levelname)-8s | %(name)s | %(message)s'
    )
    test_logger = logging.getLogger('test.cache_manager')
    
    # 测试路径直接定义
    test_dir = Path(__file__).parent.parent.parent / 'cache' / 'test'
    test_dir.mkdir(parents=True, exist_ok=True)
    test_path = test_dir / 'test_cache.json.gz'
    
    test_data = {'test': [1, 2, 3], 'dates': ['2024-01-01']}
    
    print("写入测试缓存...")
    write_gzip_cache(test_path, test_data, logger=test_logger)
    
    print("读取测试缓存...")
    loaded = read_gzip_cache(test_path, logger=test_logger)
    print(f"读取结果: {loaded}")
    
    print("获取缓存信息...")
    info = get_cache_file_info(test_path, logger=test_logger)
    print(f"文件信息: {info}")
    
    # 测试 append_to_cache
    print("\n测试 append_to_cache...")
    test_append_path = test_dir / 'test_append.json'
    append_to_cache(test_append_path, [1, 2], key='data', logger=test_logger)
    append_to_cache(test_append_path, [3, 4], key='data', logger=test_logger)
    append_result = read_json_cache(test_append_path, logger=test_logger)
    print(f"追加结果: {append_result}")
    
    # 测试错误场景
    print("\n测试错误场景...")
    try:
        read_gzip_cache(test_dir / 'not_exist.json.gz', logger=test_logger)
    except FileNotFoundError as e:
        print(f"捕获预期异常 FileNotFoundError: {e}")
    
    # 测试防御性编程（数据结构异常）
    print("\n测试防御性编程...")
    test_invalid_path = test_dir / 'test_invalid.json'
    write_json_cache(test_invalid_path, {'data': {'nested': 'dict'}}, logger=test_logger)
    append_to_cache(test_invalid_path, [5, 6], key='data', logger=test_logger)
    invalid_result = read_json_cache(test_invalid_path, logger=test_logger)
    print(f"异常数据修复结果: {invalid_result}")
    
    # 清理测试文件
    test_path.unlink()
    test_append_path.unlink()
    test_invalid_path.unlink()
    print("\n测试完成，已清理测试文件")