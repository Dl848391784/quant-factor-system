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
- v1.17 (2026-05-26): 七项安全与文档修复：
    1. append_to_cache 消除 TOCTOU 竞态（移除 path.exists 检查，直接捕获 FileNotFoundError）
    2. _read_cache_impl stat() FileNotFoundError 保留异常链（添加 from e）
    3. get_cache_file_info 增加 error 字段区分"文件不存在"和"无权限"
    4. _read_cache_impl 异常捕获顺序添加注释说明（FileNotFoundError 必须在 OSError 之前）
    5. append_to_cache docstring 补充 TypeError 说明
    6. 测试代码 open() 添加 encoding='utf-8'（避免 Windows GBK 问题）
    7. cache_exists Example 改为推荐直接调用 read_cache（避免 TOCTOU 竞态）
- v1.18 (2026-05-26): 七项健壮性与文档修复：
    1. _write_cache_impl 消除 ensure_dir=False TOCTOU 竞态（删除前置检查，通过 errno.ENOENT 识别目录不存在）
    2. _write_cache_impl 异常捕获分组（TypeError 在前，文件系统异常子类在前父类在后）
    3. get_cache_file_info Returns 补充完整字段说明（path/exists/size_mb/modified_time/error）
    4. read_gzip_cache/read_json_cache/write_gzip_cache/write_json_cache Raises 补全所有异常类型
    5. append_to_cache 入口添加 new_data 类型校验（严格执行类型契约）
    6. _read_cache_impl JSONDecodeError 通过 e.pos==0 检测文件截断，提供精确错误信息
    7. 测试代码 finally 添加 test_dir.rmdir() 清理空目录
- v1.19 (2026-05-27): 五项架构重构：
    1. 新增 _atomic_write contextmanager 封装原子写入临时文件生命周期
    2. _write_cache_impl 使用 contextmanager，临时文件清理统一在 finally 块（消除四块重复）
    3. _read_cache_impl 合并两段 try 块，FileNotFoundError 只捕获一次（覆盖 stat 和 open）
    4. _read_cache_impl 移除 e.pos==0 分支（存在误判），统一按普通 JSON 格式错误处理
    5. delete_cache 移除 except Exception 兜底（Path.unlink 只抛 OSError，意外异常应自然传播）
- v1.20 (2026-05-27): 四项语义精确化修复：
    1. _atomic_write 使用布尔标志 replaced 替代 temp_path=None（语义更清晰）
    2. _write_cache_impl ENOENT 错误信息改为"目标路径不存在或临时文件丢失"（避免错误定位）
    3. read_gzip_cache/read_json_cache/read_cache Raises 移除"文件内容为空/被截断"过时描述
    4. write_gzip_cache/write_json_cache/write_cache Raises 补充 FileNotFoundError（目录不存在场景）
- v1.21 (2026-05-27): 四项日志与文档修复：
    1. _write_cache_impl ENOENT 日志改为 % 格式 + error 级别（统一风格）
    2. _atomic_write Raises 补充 os.replace 异常来源（跨文件系统等）
    3. append_to_cache Raises 补充 FileNotFoundError（极端场景）
    4. 版本历史 v1.18~v1.20 移除多余 | 字符（统一 - 格式）

作者: 云瑶
日期: 2026-05-24
"""

import errno
import gzip
import json
import logging
import os
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, Generator, List, Optional, Union

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



@contextmanager
def _atomic_write(path: Path) -> Generator[Path, None, None]:
    """
    原子写入临时文件上下文管理器
    
    创建临时文件，正常退出时原子替换目标文件，异常退出时清理临时文件。
    
    Args:
        path: 目标文件路径
        
    Yields:
        Path: 临时文件路径（用于写入）
        
    Raises:
        OSError: mkstemp 目录不存在（errno.ENOENT）或 os.replace 失败（跨文件系统等）
        PermissionError: 无权限写入
        
    Example:
        with _atomic_write(target_path) as temp_path:
            # 写入临时文件
            with open(temp_path, 'w') as f:
                f.write(content)
            # 正常退出时自动原子替换
    """
    # 生成唯一临时文件路径（线程安全）
    # 使用 path.name.split('.')[0] 取干净基础名
    base_name = path.name.split('.')[0]
    fd, temp_path_str = tempfile.mkstemp(
        suffix='.tmp',
        prefix=base_name + '_',
        dir=path.parent
    )
    os.close(fd)  # 关闭文件描述符，后续使用 Path
    temp_path = Path(temp_path_str)
    
    replaced = False  # 布尔标志标记替换状态
    try:
        yield temp_path
        # 正常退出：原子替换目标文件
        os.replace(temp_path, path)
        replaced = True  # 替换成功，标记已完成
    finally:
        # 异常退出或替换失败：清理临时文件
        if not replaced:
            try:
                temp_path.unlink(missing_ok=True)
            except OSError:
                pass  # 清理失败不影响原始异常传播


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
    file_type = "gzip JSON" if use_gzip else "JSON"
    
    # 统一 try 块：stat()、空文件检查、大文件警告、json.load() 全部纳入
    # FileNotFoundError 只捕获一次，同时覆盖 stat() 和 open() 两个场景
    try:
        file_size = path.stat().st_size
        
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
        
        # 读取文件内容
        if use_gzip:
            with gzip.open(path, 'rt', encoding='utf-8') as f:
                data = json.load(f)
        else:
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
        
        logger.debug("成功读取缓存: %s", path)
        return data
        
    # FileNotFoundError 是 OSError 子类，必须放在 OSError 之前
    except FileNotFoundError as e:
        # 覆盖 stat() 和 open() 两种场景
        raise FileNotFoundError(f"缓存文件不存在: {path}") from e
    except json.JSONDecodeError as e:
        # 遵循 references/backtest-module-optimization-patterns.md Section 1.2
        # 避免传递完整 JSON 文档字符串导致内存翻倍
        # 移除 e.pos == 0 分支（存在误判），统一按普通 JSON 格式错误处理
        logger.error(
            "%s 文件内容解析失败\n"
            "文件路径: %s\n"
            "错误位置: 行 %d, 列 %d\n"
            "错误信息: %s\n"
            "提示: 若文件非 JSON 格式，请检查文件类型是否正确",
            file_type, path, e.lineno, e.colno, e.msg
        )
        raise ValueError(f"{file_type}文件内容解析失败: {path}, 行 {e.lineno} 列 {e.colno}") from e
    except BadGzipFile as e:
        # 仅 use_gzip=True 时可触发
        logger.error("gzip 文件损坏: %s", path)
        raise ValueError(f"gzip 文件损坏: {path}") from e
    except PermissionError as e:
        logger.error("文件权限错误: %s, errno=%d", path, e.errno)
        raise PermissionError(f"无权限读取缓存文件: {path}") from e
    except OSError as e:
        logger.error("文件系统错误: %s", path)
        raise OSError(f"读取缓存失败（文件系统错误）: {path}") from e
    except Exception as e:
        # 未知错误兜底（多步骤操作可能抛出意外异常）
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
    
    # 使用 _atomic_write contextmanager 管理临时文件生命周期
    # 正常退出时原子替换，异常退出时自动清理临时文件
    try:
        with _atomic_write(path) as temp_path:
            # 写入临时文件
            if use_gzip:
                with gzip.open(temp_path, 'wt', encoding='utf-8', compresslevel=compresslevel) as f:
                    json.dump(data, f, ensure_ascii=False, indent=json_indent, separators=separators, sort_keys=json_sort_keys)
            else:
                with open(temp_path, 'w', encoding='utf-8') as f:
                    json.dump(data, f, ensure_ascii=False, indent=json_indent, separators=separators, sort_keys=json_sort_keys)
        
        logger.debug("成功写入缓存（原子操作）: %s", path)
        
    # === 数据类型异常 ===
    except TypeError as e:
        # json.dump 遇到不可序列化数据时抛出 TypeError
        logger.error(
            "数据包含不可序列化类型\n"
            "文件路径: %s\n"
            "错误信息: %s",
            path, str(e)
        )
        raise TypeError(f"缓存数据包含不可序列化类型: {path}, {e}") from e
    # === 文件系统异常（子类在前，父类在后）===
    except PermissionError as e:
        logger.error("文件权限错误: %s, errno=%d", path, e.errno)
        raise PermissionError(f"无权限写入缓存文件: {path}") from e
    except OSError as e:
        # 通过 errno 区分不同的 OSError 场景
        if e.errno == errno.ENOENT:
            # 目录不存在或临时文件丢失
            logger.error("目标路径不存在或临时文件丢失: %s, errno=%d", path, e.errno)
            raise FileNotFoundError(f"写入缓存失败，路径不存在: {path}") from e
        else:
            # 其他 OSError：磁盘空间不足、文件被占用等
            logger.error("文件系统错误: %s, errno=%d", path, e.errno)
            raise OSError(f"写入缓存失败（磁盘空间不足或文件系统错误）: {path}") from e
    except Exception as e:
        # 未知错误兜底（多步骤操作可能抛出意外异常）
        logger.exception("写入缓存失败（未知错误）: %s", path)
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
        ValueError: JSON 解析失败（格式错误或 gzip 文件损坏）
        PermissionError: 无权限读取文件
        OSError: 文件系统错误
        RuntimeError: 未知错误
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
        TypeError: 数据类型错误（非 dict）或数据包含不可序列化类型
        FileNotFoundError: 目标目录不存在（ensure_dir=False 时）
        PermissionError: 无权限写入文件
        OSError: 文件写入失败（磁盘空间不足或文件系统错误）
        RuntimeError: 未知错误
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
        ValueError: JSON 解析失败（格式错误）
        PermissionError: 无权限读取文件
        OSError: 文件系统错误
        RuntimeError: 未知错误
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
        TypeError: 数据类型错误（非 dict）或数据包含不可序列化类型
        FileNotFoundError: 目标目录不存在（ensure_dir=False 时）
        PermissionError: 无权限写入文件
        OSError: 文件写入失败（磁盘空间不足或文件系统错误）
        RuntimeError: 未知错误
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
        new_data: 要追加的数据列表（必须是 list 类型）
        key: 数据存储的 key（默认 'data'）
        logger: 调用方传入的 logger（可选）
        
    Returns:
        int: 追加后的总数据量
        
    Raises:
        TypeError: new_data 类型错误（非 list）或数据包含不可序列化类型
        FileNotFoundError: 极端场景下路径丢失（如临时文件被外部删除）
        ValueError: JSON 解析失败（文件存在但损坏）
        PermissionError: 无权限读取或写入文件
        OSError: 磁盘空间不足或文件系统错误
        RuntimeError: 未知错误
    """
    # 严格执行类型契约：new_data 必须是 list
    if not isinstance(new_data, list):
        raise TypeError(
            f"new_data 参数类型错误: 预期 list，实际 {type(new_data).__name__}\n"
            f"文件路径: {path}"
        )
    
    path = Path(path)  # 统一转换为 Path
    logger = get_module_logger(logger)
    use_gzip = _is_gzip_file(path)  # 使用统一判断函数
    
    # 消除 TOCTOU 竞态：直接调用 _read_cache_impl，捕获 FileNotFoundError 作为"文件不存在"信号
    # 不再提前检查 path.exists()，避免检查-读取间隙文件被删除
    existing: Dict[str, Any] = {}
    existing_data: List[Any] = []
    
    try:
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
    except FileNotFoundError:
        # 文件不存在，初始化为空（正常情况，不记录 warning）
        logger.debug("缓存文件不存在，将创建新缓存: %s", path)
        existing = {}
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
        Dict[str, Any]: 文件信息字典，包含以下字段：
        - path (str): 文件路径
        - exists (bool): 文件是否存在（True/False）
        - size_mb (float): 文件大小（MB），不存在时为 0
        - modified_time (float|None): 最后修改时间戳，不存在时为 None
        - error (str|None): 错误状态，None 表示正常，'permission_denied' 表示无权限
    """
    path = Path(path)  # 统一转换为 Path
    logger = get_module_logger(logger)
    
    # 消除双重检查 TOCTOU 竞态：直接调用 stat()，通过异常判断是否存在
    # 增加 'error' 字段区分"文件不存在"和"文件存在但无权限"
    info = {
        'path': str(path),
        'exists': False,
        'size_mb': 0,
        'modified_time': None,
        'error': None,  # None=正常，'permission_denied'=无权限
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
        # 设置 error 字段，使调用方可以区分"文件不存在"和"无权限"
        info['error'] = 'permission_denied'
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
        ValueError: JSON 解析失败（格式错误或 gzip 文件损坏）
        PermissionError: 无权限读取文件
        OSError: 文件系统错误
        RuntimeError: 未知错误
        
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
        TypeError: 数据类型错误（非 dict）或数据包含不可序列化类型
        FileNotFoundError: 目标目录不存在（ensure_dir=False 时）
        PermissionError: 无权限写入文件
        OSError: 文件写入失败（磁盘空间不足或文件系统错误）
        RuntimeError: 未知错误
        
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
        # 推荐模式：直接调用 read_cache，捕获 FileNotFoundError
        # 避免 TOCTOU 竞态：cache_exists 和 read_cache 之间文件可能被删除
        try:
            data = read_cache('data.json.gz')
        except FileNotFoundError:
            # 文件不存在时的处理逻辑
            data = {}
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
    # 注意：不保留 except Exception 兜底
    # Path.unlink() 只会抛 OSError 及其子类，意外异常应自然向上传播

