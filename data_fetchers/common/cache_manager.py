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
    # 统一缓存 API
    'read_cache',
    'write_cache',
    # 缓存读写函数（gzip/json）
    'read_gzip_cache',
    'write_gzip_cache',
    'read_json_cache',
    'write_json_cache',
    'append_to_cache',
    'get_cache_file_info',
    # 辅助函数
    'cache_exists',
    'delete_cache',
]

# 模块级 fallback logger（遵循 PROJECT.md 第783-857行规范）
_MODULE_LOGGER = None

# 大文件阈值（MB）
_LARGE_FILE_THRESHOLD_MB = 100

# gzip 压缩级别（1-9，默认 6 平衡压缩率和速度）
_DEFAULT_GZIP_COMPRESSLEVEL = 6

# JSON 序列化选项
_JSON_COMPACT_SEPARATORS = (',', ':')  # 紧凑格式
_JSON_READABLE_INDENT = 2               # 可读格式缩进


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
    
    # 大文件监控
    file_size_mb = path.stat().st_size / (1024 * 1024)
    if file_size_mb > _LARGE_FILE_THRESHOLD_MB:
        logger.warning(
            "大缓存文件读取: %.2f MB\n"
            "文件路径: %s\n"
            "可能影响性能，建议检查数据量",
            file_size_mb, path
        )
    
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
    logger: logging.Logger,
    compresslevel: int = _DEFAULT_GZIP_COMPRESSLEVEL,
    json_indent: Optional[int] = None,
    json_sort_keys: bool = False
) -> None:
    """
    写入缓存的公共实现
    
    Args:
        path: 文件路径（已转换为 Path）
        data: 要写入的数据
        use_gzip: 是否使用 gzip 压缩
        ensure_dir: 是否自动创建目录
        logger: Logger 对象
        compresslevel: gzip 压缩级别（1-9，默认 6）
        json_indent: JSON 缩进（None=紧凑，数字=可读）
        json_sort_keys: 是否排序 JSON 键
        
    Raises:
        OSError: 文件写入失败
    """
    # 验证数据类型
    if not isinstance(data, dict):
        logger.warning(
            "缓存数据类型异常: 预期 dict，实际 %s\n"
            "文件路径: %s\n"
            "继续写入（JSON 支持非字典数据）",
            type(data).__name__, path
        )
    
    if ensure_dir:
        path.parent.mkdir(parents=True, exist_ok=True)
    
    # JSON 序列化参数
    if json_indent is None:
        separators = _JSON_COMPACT_SEPARATORS
    else:
        separators = None  # 使用默认分隔符
    
    try:
        if use_gzip:
            with gzip.open(path, 'wt', encoding='utf-8', compresslevel=compresslevel) as f:
                json.dump(data, f, ensure_ascii=False, indent=json_indent, separators=separators, sort_keys=json_sort_keys)
        else:
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=json_indent, separators=separators, sort_keys=json_sort_keys)
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
    logger: Optional[logging.Logger] = None,
    compresslevel: int = _DEFAULT_GZIP_COMPRESSLEVEL,
    json_indent: Optional[int] = None,
    json_sort_keys: bool = False
) -> None:
    """
    写入 gzip 压缩的 JSON 缓存
    
    Args:
        path: 缓存文件路径（.json.gz），支持 Path 或 str
        data: 要写入的数据
        ensure_dir: 是否自动创建目录（默认 True）
        logger: 调用方传入的 logger（可选）
        compresslevel: gzip 压缩级别（1-9，默认 6）
        json_indent: JSON 缩进（None=紧凑，数字=可读）
        json_sort_keys: 是否排序 JSON 键
        
    Raises:
        OSError: 文件写入失败
    """
    _write_cache_impl(
        Path(path), data, use_gzip=True, ensure_dir=ensure_dir, logger=get_module_logger(logger),
        compresslevel=compresslevel, json_indent=json_indent, json_sort_keys=json_sort_keys
    )


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
    logger: Optional[logging.Logger] = None,
    json_indent: Optional[int] = None,
    json_sort_keys: bool = False
) -> None:
    """
    写入普通 JSON 缓存（非压缩）
    
    Args:
        path: 缓存文件路径（.json），支持 Path 或 str
        data: 要写入的数据
        ensure_dir: 是否自动创建目录（默认 True）
        logger: 调用方传入的 logger（可选）
        json_indent: JSON 缩进（None=紧凑，数字=可读）
        json_sort_keys: 是否排序 JSON 键
        
    Raises:
        OSError: 文件写入失败
    """
    _write_cache_impl(
        Path(path), data, use_gzip=False, ensure_dir=ensure_dir, logger=get_module_logger(logger),
        json_indent=json_indent, json_sort_keys=json_sort_keys
    )


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


def read_cache(
    path: Union[Path, str],
    logger: Optional[logging.Logger] = None
) -> Dict[str, Any]:
    """
    读取缓存（自动判断 gzip/json）
    
    根据文件后缀自动判断是否为 gzip 文件，统一读取接口。
    
    Args:
        path: 缓存文件路径（.json 或 .json.gz），支持 Path 或 str
        logger: 调用方传入的 logger（可选）
        
    Returns:
        Dict: JSON 数据
        
    Raises:
        FileNotFoundError: 文件不存在
        ValueError: JSON 解析失败
        
    Example:
        # 统一接口，无需手动判断文件类型
        data = read_cache('data.json.gz')
        data = read_cache('data.json')
    """
    path = Path(path)
    use_gzip = _is_gzip_file(path)
    return _read_cache_impl(path, use_gzip, get_module_logger(logger))


def write_cache(
    path: Union[Path, str],
    data: Dict[str, Any],
    ensure_dir: bool = True,
    logger: Optional[logging.Logger] = None,
    compresslevel: int = _DEFAULT_GZIP_COMPRESSLEVEL,
    json_indent: Optional[int] = None,
    json_sort_keys: bool = False
) -> None:
    """
    写入缓存（自动判断 gzip/json）
    
    根据文件后缀自动判断是否为 gzip 文件，统一写入接口。
    
    Args:
        path: 缓存文件路径（.json 或 .json.gz），支持 Path 或 str
        data: 要写入的数据
        ensure_dir: 是否自动创建目录（默认 True）
        logger: 调用方传入的 logger（可选）
        compresslevel: gzip 压缩级别（1-9，默认 6）
        json_indent: JSON 缩进（None=紧凑，数字=可读）
        json_sort_keys: 是否排序 JSON 键
        
    Raises:
        OSError: 文件写入失败
        
    Example:
        # 统一接口，无需手动判断文件类型
        write_cache('data.json.gz', {'key': 'value'})
        write_cache('data.json', {'key': 'value'})
        
        # 可读格式
        write_cache('data.json', {'key': 'value'}, json_indent=2)
        
        # 排序键
        write_cache('data.json', {'key': 'value'}, json_sort_keys=True)
    """
    path = Path(path)
    use_gzip = _is_gzip_file(path)
    _write_cache_impl(
        path, data, use_gzip, ensure_dir=ensure_dir, logger=get_module_logger(logger),
        compresslevel=compresslevel, json_indent=json_indent, json_sort_keys=json_sort_keys
    )


def cache_exists(path: Union[Path, str]) -> bool:
    """
    检查缓存文件是否存在
    
    Args:
        path: 缓存文件路径，支持 Path 或 str
        
    Returns:
        bool: 文件是否存在
        
    Example:
        if cache_exists('data.json.gz'):
            data = read_cache('data.json.gz')
    """
    return Path(path).exists()


def delete_cache(
    path: Union[Path, str],
    logger: Optional[logging.Logger] = None
) -> bool:
    """
    删除缓存文件
    
    Args:
        path: 缓存文件路径，支持 Path 或 str
        logger: 调用方传入的 logger（可选）
        
    Returns:
        bool: 是否成功删除（文件不存在时返回 False）
        
    Example:
        if delete_cache('data.json.gz'):
            print("缓存已删除")
    """
    path = Path(path)
    logger = get_module_logger(logger)
    
    if not path.exists():
        logger.debug("缓存文件不存在，无需删除: %s", path)
        return False
    
    try:
        path.unlink()
        logger.info("缓存文件已删除: %s", path)
        return True
    except Exception as e:
        logger.exception("删除缓存文件失败: %s", path)
        raise


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
    
    # 测试统一 API
    print("\n测试统一缓存 API...")
    test_unified_path_gz = test_dir / 'test_unified.json.gz'
    test_unified_path_json = test_dir / 'test_unified.json'
    
    write_cache(test_unified_path_gz, {'gzip': True}, logger=test_logger)
    write_cache(test_unified_path_json, {'gzip': False}, logger=test_logger)
    
    gzip_data = read_cache(test_unified_path_gz, logger=test_logger)
    json_data = read_cache(test_unified_path_json, logger=test_logger)
    print(f"gzip 数据: {gzip_data}")
    print(f"json 数据: {json_data}")
    
    # 测试新增参数
    print("\n测试新增参数（压缩级别 + JSON 格式选项）...")
    test_options_path = test_dir / 'test_options.json.gz'
    test_readable_path = test_dir / 'test_readable.json'
    
    # 压缩级别测试（级别 1，最快）
    write_gzip_cache(test_options_path, {'compresslevel': 1}, compresslevel=1, logger=test_logger)
    print(f"压缩级别 1 写入成功")
    
    # 可读格式测试（indent=2）
    write_json_cache(test_readable_path, {'key1': 'value1', 'key2': 'value2'}, json_indent=2, json_sort_keys=True, logger=test_logger)
    print(f"可读格式写入成功")
    
    # 验证可读格式
    with open(test_readable_path, 'r') as f:
        readable_content = f.read()
    print(f"可读格式内容:\n{readable_content}")
    
    # 测试辅助函数
    print("\n测试辅助函数...")
    print(f"cache_exists(test_unified.json.gz): {cache_exists(test_unified_path_gz)}")
    print(f"cache_exists(not_exist.json): {cache_exists(test_dir / 'not_exist.json')}")
    
    print(f"delete_cache(test_unified.json.gz): {delete_cache(test_unified_path_gz, logger=test_logger)}")
    print(f"delete_cache(not_exist.json): {delete_cache(test_dir / 'not_exist.json', logger=test_logger)}")
    
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
    test_unified_path_json.unlink()
    test_options_path.unlink()
    test_readable_path.unlink()
    test_append_path.unlink()
    test_invalid_path.unlink()
    print("\n测试完成，已清理测试文件")