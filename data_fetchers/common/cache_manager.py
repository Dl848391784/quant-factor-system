#!/usr/bin/env python3
"""
缓存管理模块

统一 gzip + JSON 缓存的读写操作。

版本历史：
- v1.0 (2026-05-24): 初始版本
- v1.1 (2026-05-24): 接收 logger 参数，异常处理精确化
- v1.2 (2026-05-24): 公共函数重构，__all__ 导出
- v1.3 (2026-05-24): 统一缓存 API + 辅助函数
- v1.4 (2026-05-24): 压缩级别控制 + JSON 格式选项
- v1.5 (2026-05-24): 异常处理精确化（BadGzipFile、空文件处理）
- v1.6 (2026-05-24): 测试代码日志规范化
- v1.7 (2026-05-24): 创建 logger_config.py，复用 setup_logger
- v1.8 (2026-05-24): 修复 get_module_logger global 声明
- v1.9 (2026-05-24): 删除冗余导入（datetime）
- v1.10 (2026-05-24): 类型注解修复 + append_to_cache 冗余检查消除
- v1.11 (2026-05-25): 线程安全修复 + docstring 补充 + 测试清理健壮化
- v1.12 (2026-05-25): 原子写入修复 + 错误信息精确化
- v1.13 (2026-05-26): 四项安全修复：
    1. _is_gzip_file 语义精确化（检查 .json.gz 双后缀，排除 .csv.gz）
    2. 临时文件使用 tempfile.mkstemp 生成唯一路径，并发安全
    3. 临时文件清理消除 TOCTOU 竞态（missing_ok=True + try/except OSError）
    4. 类型契约严格执行（非 dict 数据抛 TypeError）
- v1.14 (2026-05-26): 四项代码质量修复：
    1. append_to_cache 删除硬编码行号，改为逻辑性描述
    2. delete_cache OSError 错误信息精确化（"文件被占用"而非"磁盘空间不足"）
    3. __main__ finally 清理列表补全 test_unified_path_gz + 幂等删除
    4. BadGzipFile except 添加触发条件注释（仅 use_gzip=True）
- v1.15 (2026-05-26): 四项健壮性修复：
    1. tempfile.mkstemp prefix 使用 path.name.split('.')[0] 取干净基础名
    2. TypeError 单独捕获（json.dump 不可序列化数据），保留精确错误
    3. _read_cache_impl 消除 TOCTOU 竞态（移除提前 exists 检查，FileNotFoundError 透传）
    4. get_cache_file_info 消除双重检查（直接 stat() + 异常判断存在性）
- v1.16 (2026-05-26): 三项健壮性修复：
    1. delete_cache 消除 TOCTOU 竞态（直接 unlink + FileNotFoundError 单独捕获）
    2. tempfile.mkstemp 纳入 try 块 + ensure_dir=False 目录检查
    3. 删除死代码 _JSON_READABLE_INDENT（从未被引用）

作者: 云瑶
日期: 2026-05-24
"""

import gzip
import json
import logging
import os
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

# gzip 异常类型（用于精确捕获 gzip 文件损坏）
BadGzipFile = gzip.BadGzipFile

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
# 直接初始化，避免延迟初始化的多线程安全问题
_MODULE_LOGGER = logging.getLogger('data_fetchers.common.cache_manager')

# 大文件阈值（MB）
_LARGE_FILE_THRESHOLD_MB = 100

# gzip 压缩级别（1-9，默认 6 平衡压缩率和速度）
_DEFAULT_GZIP_COMPRESSLEVEL = 6

# JSON 序列化选项
_JSON_COMPACT_SEPARATORS = (',', ':')  # 紧凑格式


def get_module_logger(logger: Optional[logging.Logger] = None) -> logging.Logger:
    """
    获取 logger，遵循 PROJECT.md 公共模块日志规范
    
    公共模块接收 logger 参数，调用方传入以追溯调用方。
    不传 logger 时使用模块级 fallback logger（模块加载时已初始化）。
    
    Args:
        logger: 调用方传入的 logger（可选）
        
    Returns:
        Logger 对象
    """
    if logger is not None:
        return logger
    return _MODULE_LOGGER


def _is_gzip_file(path: Path) -> bool:
    """
    判断是否为 gzip 压缩的 JSON 文件
    
    检查文件后缀是否为 .json.gz（双后缀）。
    注意：本函数仅适用于 .json.gz 文件，非 JSON 的 gzip 文件
    （如 .csv.gz、.gz）会被排除，避免误判。
    
    Args:
        path: 文件路径
        
    Returns:
        bool: 是否为 .json.gz 文件
    """
    suffixes = path.suffixes
    # 检查双后缀 ['.json', '.gz']
    return len(suffixes) >= 2 and suffixes[-2:] == ['.json', '.gz']


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
    # 消除 TOCTOU 竞态：直接尝试读取，捕获 FileNotFoundError 透传
    # 不再提前检查 path.exists()，避免检查-读取间隙文件被删除
    try:
        file_size = path.stat().st_size
    except FileNotFoundError:
        raise FileNotFoundError(f"缓存文件不存在: {path}")
    
    # 空文件处理（边界情况）
    if file_size == 0:
        logger.warning("缓存文件为空（大小为 0）: %s", path)
        return {}  # 空文件返回空字典
    
    # 大文件监控
    file_size_mb = file_size / (1024 * 1024)
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
    except FileNotFoundError as e:
        # 文件在 stat 后被删除，透传真实错误（TOCTOU 场景）
        raise FileNotFoundError(f"缓存文件不存在: {path}") from e
    except json.JSONDecodeError as e:
        # 遵循 references/backtest-module-optimization-patterns.md Section 1.2
        # 避免传递完整 JSON 文档字符串导致内存翻倍
        # 区分 gzip/json 文件，提供更精确的错误信息
        file_type = "gzip JSON" if use_gzip else "JSON"
        logger.error(
            "%s 文件内容解析失败\n"
            "文件路径: %s\n"
            "错误位置: 行 %d, 列 %d\n"
            "错误信息: %s\n"
            "提示: 若文件非 JSON 格式，请检查文件类型是否正确",
            file_type, path, e.lineno, e.colno, e.msg
        )
        raise ValueError(f"{file_type}文件内容解析失败: {path}, 位置 {e.pos}") from e
    except BadGzipFile as e:
        # 仅 use_gzip=True 时可触发（gzip.open 才会抛此异常）
        logger.error("gzip 文件损坏: %s", path)
        raise ValueError(f"gzip 文件损坏: {path}") from e
    except PermissionError as e:
        logger.error("文件权限错误: %s", path)
        raise PermissionError(f"无权限读取缓存文件: {path}") from e
    except OSError as e:
        logger.error("文件系统错误: %s", path)
        raise OSError(f"读取缓存失败（文件系统错误）: {path}") from e
    except Exception as e:
        logger.exception("读取缓存失败（未知错误）: %s", path)
        raise RuntimeError(f"读取缓存失败（未知错误）: {path}") from e


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
    写入缓存的公共实现（原子写入）
    
    使用临时文件写入，成功后原子替换目标文件。
    避免写入中途崩溃导致目标文件损坏。
    
    Args:
        path: 文件路径（已转换为 Path）
        data: 要写入的数据（必须是 dict）
        use_gzip: 是否使用 gzip 压缩
        ensure_dir: 是否自动创建目录
        logger: Logger 对象
        compresslevel: gzip 压缩级别（1-9，默认 6）
        json_indent: JSON 缩进（None=紧凑，数字=可读）
        json_sort_keys: 是否排序 JSON 键
        
    Raises:
        TypeError: 数据类型错误（非 dict）
        OSError: 文件写入失败
    """
    # 严格执行类型契约
    if not isinstance(data, dict):
        raise TypeError(
            f"缓存数据类型错误: 预期 dict，实际 {type(data).__name__}\n"
            f"文件路径: {path}"
        )
    
    if ensure_dir:
        path.parent.mkdir(parents=True, exist_ok=True)
    
    # JSON 序列化参数
    if json_indent is None:
        separators = _JSON_COMPACT_SEPARATORS
    else:
        separators = None  # 使用默认分隔符
    
    # 消除 tempfile.mkstemp 跳出 try 块的问题
    # ensure_dir=False 且目录不存在时，mkstemp 会抛出无上下文的 FileNotFoundError
    # 在 mkstemp 前显式检查目录存在性，提供明确错误信息
    if not ensure_dir and not path.parent.exists():
        raise FileNotFoundError(f"目标目录不存在且 ensure_dir=False: {path.parent}")
    
    # 临时文件路径初始化（用于 except 块清理）
    temp_path: Optional[Path] = None
    
    try:
        # 生成唯一临时文件路径（线程安全）
        # 使用 tempfile.mkstemp 确保多进程/线程并发写入时临时文件不冲突
        # 注意：path.stem 对 .json.gz 文件返回 'data.json'（含点号），不干净
        # 使用 path.name.split('.')[0] 取真正的基础名
        base_name = path.name.split('.')[0]
        fd, temp_path_str = tempfile.mkstemp(
            suffix='.tmp',
            prefix=base_name + '_',
            dir=path.parent
        )
        os.close(fd)  # 关闭文件描述符，后续使用 Path
        temp_path = Path(temp_path_str)
        
        # 写入临时文件
        if use_gzip:
            with gzip.open(temp_path, 'wt', encoding='utf-8', compresslevel=compresslevel) as f:
                json.dump(data, f, ensure_ascii=False, indent=json_indent, separators=separators, sort_keys=json_sort_keys)
        else:
            with open(temp_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=json_indent, separators=separators, sort_keys=json_sort_keys)
        
        # 原子替换目标文件（os.replace 是原子操作，同文件系统）
        os.replace(temp_path, path)
        logger.debug("成功写入缓存（原子操作）: %s", path)
        
    except PermissionError as e:
        logger.error("文件权限错误: %s", path)
        # 清理临时文件（消除 TOCTOU 竞态，防止清理失败掩盖原始异常）
        if temp_path:
            try:
                temp_path.unlink(missing_ok=True)
            except OSError:
                pass
        raise PermissionError(f"无权限写入缓存文件: {path}") from e
    except TypeError as e:
        # json.dump 遇到不可序列化数据时抛出 TypeError（如 datetime、自定义对象）
        logger.error(
            "数据包含不可序列化类型\n"
            "文件路径: %s\n"
            "错误信息: %s",
            path, str(e)
        )
        # 清理临时文件
        if temp_path:
            try:
                temp_path.unlink(missing_ok=True)
            except OSError:
                pass
        raise TypeError(f"缓存数据包含不可序列化类型: {path}, {e}") from e
    except OSError as e:
        logger.error("文件系统错误: %s", path)
        # 清理临时文件
        if temp_path:
            try:
                temp_path.unlink(missing_ok=True)
            except OSError:
                pass
        raise OSError(f"写入缓存失败（磁盘空间不足或文件系统错误）: {path}") from e
    except Exception as e:
        logger.exception("写入缓存失败（未知错误）: %s", path)
        # 清理临时文件
        if temp_path:
            try:
                temp_path.unlink(missing_ok=True)
            except OSError:
                pass
        raise RuntimeError(f"写入缓存失败（未知错误）: {path}") from e


def read_gzip_cache(
    path: Union[Path, str],
    logger: Optional[logging.Logger] = None
) -> Dict[str, Any]:
    """
    读取 gzip 压缩的 JSON 缓存
    
    注意：仅支持 .json.gz 后缀文件。其他 gzip 文件（如 .csv.gz）
    不会被识别，请使用相应的解析器。
    
    Args:
        path: 缓存文件路径（必须为 .json.gz 后缀），支持 Path 或 str
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
    
    注意：仅支持 .json.gz 后缀文件。
    
    线程安全：使用唯一临时文件名，支持多进程/线程并发写入。
    
    Args:
        path: 缓存文件路径（必须为 .json.gz 后缀），支持 Path 或 str
        data: 要写入的数据（必须是 dict）
        ensure_dir: 是否自动创建目录（默认 True）
        logger: 调用方传入的 logger（可选）
        compresslevel: gzip 压缩级别（1-9，默认 6）
        json_indent: JSON 缩进（None=紧凑，数字=可读）
        json_sort_keys: 是否排序 JSON 键
        
    Raises:
        TypeError: 数据类型错误（非 dict）
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
    
    线程安全：使用唯一临时文件名，支持多进程/线程并发写入。
    
    Args:
        path: 缓存文件路径（.json），支持 Path 或 str
        data: 要写入的数据（必须是 dict）
        ensure_dir: 是否自动创建目录（默认 True）
        logger: 调用方传入的 logger（可选）
        json_indent: JSON 缩进（None=紧凑，数字=可读）
        json_sort_keys: 是否排序 JSON 键
        
    Raises:
        TypeError: 数据类型错误（非 dict）
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
    文件不存在时创建新缓存。
    
    Args:
        path: 缓存文件路径，支持 Path 或 str
        new_data: 要追加的数据列表
        key: 数据存储的 key（默认 'data'）
        logger: 调用方传入的 logger（可选）
        
    Returns:
        int: 追加后的总数据量
        
    Raises:
        ValueError: JSON 解析失败（文件存在但损坏）
        PermissionError: 无权限读取或写入文件
        OSError: 磁盘空间不足或文件系统错误
        RuntimeError: 未知错误
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
    # existing 已在上方处理：文件不存在时初始化为 {}，遍历安全
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
    
    # 消除双重检查 TOCTOU 竞态：直接调用 stat()，通过异常判断是否存在
    info = {
        'path': str(path),
        'exists': False,
        'size_mb': 0,
        'modified_time': None,
    }
    
    try:
        stat = path.stat()
        info['exists'] = True
        info['size_mb'] = stat.st_size / (1024 * 1024)
        info['modified_time'] = stat.st_mtime
        logger.debug("获取缓存文件信息: %s, 大小 %.4f MB", path, info['size_mb'])
    except FileNotFoundError:
        logger.warning("缓存文件不存在: %s", path)
    except PermissionError:
        logger.warning("无权限获取缓存文件信息: %s", path)
    
    return info


def read_cache(
    path: Union[Path, str],
    logger: Optional[logging.Logger] = None
) -> Dict[str, Any]:
    """
    读取缓存（自动判断 gzip/json）
    
    根据文件后缀自动判断：
    - .json.gz：使用 gzip 解压
    - .json：普通 JSON 文件
    
    注意：gzip 文件必须是 .json.gz 双后缀。
    其他 gzip 文件（如 .csv.gz、.gz）不会被识别。
    
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
        data = read_cache('data.json.gz')  # gzip JSON
        data = read_cache('data.json')     # 普通 JSON
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
    
    根据文件后缀自动判断：
    - .json.gz：使用 gzip 压缩
    - .json：普通 JSON 文件
    
    注意：gzip 文件必须是 .json.gz 双后缀。
    
    线程安全：使用唯一临时文件名，支持多进程/线程并发写入。
    
    Args:
        path: 缓存文件路径（.json 或 .json.gz），支持 Path 或 str
        data: 要写入的数据（必须是 dict）
        ensure_dir: 是否自动创建目录（默认 True）
        logger: 调用方传入的 logger（可选）
        compresslevel: gzip 压缩级别（1-9，默认 6）
        json_indent: JSON 缩进（None=紧凑，数字=可读）
        json_sort_keys: 是否排序 JSON 键
        
    Raises:
        TypeError: 数据类型错误（非 dict）
        OSError: 文件写入失败
        
    Example:
        # 统一接口，无需手动判断文件类型
        write_cache('data.json.gz', {'key': 'value'})  # gzip JSON
        write_cache('data.json', {'key': 'value'})     # 普通 JSON
        
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
        bool: True 表示成功删除，False 表示文件不存在
        
    Example:
        # 删除成功
        if delete_cache('data.json.gz'):
            print("缓存已删除")
        
        # 文件不存在
        if not delete_cache('old_cache.json.gz'):
            print("文件不存在，无需删除")
    """
    path = Path(path)
    logger = get_module_logger(logger)
    
    # 消除 TOCTOU 竞态：直接 unlink()，不再提前检查 exists()
    # FileNotFoundError 单独捕获返回 False，避免被 OSError 吞掉
    try:
        path.unlink()
        logger.info("缓存文件已删除: %s", path)
        return True
    except FileNotFoundError:
        logger.debug("缓存文件不存在，无需删除: %s", path)
        return False
    except PermissionError as e:
        logger.error("文件权限错误: %s", path)
        raise PermissionError(f"无权限删除缓存文件: {path}") from e
    except OSError as e:
        logger.error("文件系统错误: %s", path)
        raise OSError(f"删除缓存失败（文件系统错误，如文件被占用）: {path}") from e
    except Exception as e:
        logger.exception("删除缓存失败（未知错误）: %s", path)
        raise RuntimeError(f"删除缓存失败（未知错误）: {path}") from e


if __name__ == '__main__':
    # 配置测试日志（复用 logger_config.py 的 setup_logger）
    # 遵循 PROJECT.md 第780-839行规范
    # __main__ 中需要添加项目根目录到 sys.path
    import sys
    from pathlib import Path as _Path
    sys.path.insert(0, str(_Path(__file__).parent.parent.parent))
    
    from data_fetchers.common.logger_config import setup_logger
    
    test_logger = setup_logger(
        'cache_manager',  # 脚本名称
        level=logging.DEBUG,  # 测试用 DEBUG
        console_level=logging.INFO  # 控制台用 INFO
    )
    
    # 测试路径直接定义
    test_dir = Path(__file__).parent.parent.parent / 'cache' / 'test'
    test_dir.mkdir(parents=True, exist_ok=True)
    
    # 定义所有测试文件路径（便于统一清理）
    test_path = test_dir / 'test_cache.json.gz'
    test_unified_path_gz = test_dir / 'test_unified.json.gz'
    test_unified_path_json = test_dir / 'test_unified.json'
    test_options_path = test_dir / 'test_options.json.gz'
    test_readable_path = test_dir / 'test_readable.json'
    test_append_path = test_dir / 'test_append.json'
    test_invalid_path = test_dir / 'test_invalid.json'
    
    # 使用 try/finally 确保测试文件清理（健壮性）
    try:
        test_data = {'test': [1, 2, 3], 'dates': ['2024-01-01']}
        
        test_logger.info("写入测试缓存...")
        write_gzip_cache(test_path, test_data, logger=test_logger)
        
        test_logger.info("读取测试缓存...")
        loaded = read_gzip_cache(test_path, logger=test_logger)
        test_logger.info("读取结果: %s", loaded)
        
        test_logger.info("获取缓存信息...")
        info = get_cache_file_info(test_path, logger=test_logger)
        test_logger.info("文件信息: %s", info)
        
        # 测试统一 API
        test_logger.info("测试统一缓存 API...")
        write_cache(test_unified_path_gz, {'gzip': True}, logger=test_logger)
        write_cache(test_unified_path_json, {'gzip': False}, logger=test_logger)
        
        gzip_data = read_cache(test_unified_path_gz, logger=test_logger)
        json_data = read_cache(test_unified_path_json, logger=test_logger)
        test_logger.info("gzip 数据: %s", gzip_data)
        test_logger.info("json 数据: %s", json_data)
        
        # 测试新增参数
        test_logger.info("测试新增参数（压缩级别 + JSON 格式选项）...")
        # 压缩级别测试（级别 1，最快）
        write_gzip_cache(test_options_path, {'compresslevel': 1}, compresslevel=1, logger=test_logger)
        test_logger.info("压缩级别 1 写入成功")
        
        # 可读格式测试（indent=2）
        write_json_cache(test_readable_path, {'key1': 'value1', 'key2': 'value2'}, json_indent=2, json_sort_keys=True, logger=test_logger)
        test_logger.info("可读格式写入成功")
        
        # 验证可读格式
        with open(test_readable_path, 'r') as f:
            readable_content = f.read()
        test_logger.info("可读格式内容:\n%s", readable_content)
        
        # 测试辅助函数
        test_logger.info("测试辅助函数...")
        test_logger.info("cache_exists(test_unified.json.gz): %s", cache_exists(test_unified_path_gz))
        test_logger.info("cache_exists(not_exist.json): %s", cache_exists(test_dir / 'not_exist.json'))
        
        test_logger.info("delete_cache(test_unified.json.gz): %s", delete_cache(test_unified_path_gz, logger=test_logger))
        test_logger.info("delete_cache(not_exist.json): %s", delete_cache(test_dir / 'not_exist.json', logger=test_logger))
        
        # 测试 append_to_cache
        test_logger.info("测试 append_to_cache...")
        append_to_cache(test_append_path, [1, 2], key='data', logger=test_logger)
        append_to_cache(test_append_path, [3, 4], key='data', logger=test_logger)
        append_result = read_json_cache(test_append_path, logger=test_logger)
        test_logger.info("追加结果: %s", append_result)
        
        # 测试错误场景
        test_logger.info("测试错误场景...")
        try:
            read_gzip_cache(test_dir / 'not_exist.json.gz', logger=test_logger)
        except FileNotFoundError as e:
            test_logger.info("捕获预期异常 FileNotFoundError: %s", e)
        
        # 测试防御性编程（数据结构异常）
        test_logger.info("测试防御性编程...")
        write_json_cache(test_invalid_path, {'data': {'nested': 'dict'}}, logger=test_logger)
        append_to_cache(test_invalid_path, [5, 6], key='data', logger=test_logger)
        invalid_result = read_json_cache(test_invalid_path, logger=test_logger)
        test_logger.info("异常数据修复结果: %s", invalid_result)
        
        test_logger.info("测试完成")
    finally:
        # 清理测试文件（finally 确保无论成功或失败都执行）
        # 使用 unlink(missing_ok=True) 保证幂等，避免重复删除报错
        for test_file in [test_path, test_unified_path_gz, test_unified_path_json,
                          test_options_path, test_readable_path, test_append_path, test_invalid_path]:
            try:
                test_file.unlink(missing_ok=True)
            except OSError:
                pass  # 忽略清理失败，不影响测试结果
        test_logger.info("已清理测试文件")