"""
日志配置模块

遵循 PROJECT.md 日志规范，统一格式和路径。

使用方法：
    from common.logging_setup import get_logger
    logger = get_logger(__name__)

规范摘要：
    - 日志目录: <模块>/logs/
    - 日志文件: <脚本名>_YYYY-MM-DD.log
    - 日志格式: %(asctime)s | %(levelname)-8s | %(name)s | %(message)s
    - 日志级别: INFO（生产）/ DEBUG（开发）
"""

import logging
from pathlib import Path
from datetime import datetime


def get_logger(name: str, level: int = logging.INFO) -> logging.Logger:
    """
    获取配置好的日志记录器

    参数:
        name: Logger 名称（通常使用 __name__）
        level: 日志级别（默认 INFO）

    返回:
        配置好的 Logger 对象

    规范:
        - 日志目录: 调用方模块目录/logs/
        - 日志文件: <模块名>_YYYY-MM-DD.log
        - 日志格式: %(asctime)s | %(levelname)-8s | %(name)s | %(message)s

    示例:
        >>> logger = get_logger(__name__)
        >>> logger.info("处理完成")
        >>> # 输出: 2026-06-01 16:30:45 | INFO     | factor_ic.ic_rsi_1d | 处理完成
    """
    # 获取调用方所在目录（推断模块目录）
    # name 格式如 "factor_ic.ic_rsi_1d" 或 "data_fetchers.fetch_stock_list"
    module_name = name.split('.')[0] if '.' in name else name
    
    # 日志目录：项目根目录下各模块的 logs/
    project_root = Path(__file__).parent.parent
    logs_dir = project_root / module_name / 'logs'
    logs_dir.mkdir(parents=True, exist_ok=True)
    
    # 日志文件名：<模块名>_YYYY-MM-DD.log
    today = datetime.now().strftime('%Y-%m-%d')
    log_file = logs_dir / f"{module_name}_{today}.log"
    
    # 创建 Logger
    logger = logging.getLogger(name)
    logger.setLevel(level)
    
    # 防止重复添加 Handler
    if logger.handlers:
        return logger
    
    # 文件 Handler
    file_handler = logging.FileHandler(
        log_file,
        mode='a',  # 追加模式
        encoding='utf-8'
    )
    file_handler.setLevel(level)
    
    # 控制台 Handler
    console_handler = logging.StreamHandler()
    console_handler.setLevel(level)
    
    # Formatter
    formatter = logging.Formatter(
        '%(asctime)s | %(levelname)-8s | %(name)s | %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    file_handler.setFormatter(formatter)
    console_handler.setFormatter(formatter)
    
    # 添加 Handler
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)
    
    return logger


def setup_logger(script_name: str, script_dir: Path | None = None) -> logging.Logger:
    """
    配置脚本级日志记录器（兼容旧代码）

    参数:
        script_name: 脚本名称（不含 .py 后缀）
        script_dir: 脚本所在目录（默认自动推断）

    返回:
        配置好的 Logger 对象

    示例:
        >>> logger = setup_logger('ic_rsi_1d')
        >>> logger.info("IC 计算完成")
    """
    if script_dir is None:
        script_dir = Path.cwd()
    
    logs_dir = script_dir / 'logs'
    logs_dir.mkdir(parents=True, exist_ok=True)
    
    today = datetime.now().strftime('%Y-%m-%d')
    log_file = logs_dir / f"{script_name}_{today}.log"
    
    logger = logging.getLogger(script_name)
    logger.setLevel(logging.INFO)
    
    if logger.handlers:
        return logger
    
    file_handler = logging.FileHandler(log_file, mode='a', encoding='utf-8')
    file_handler.setLevel(logging.INFO)
    
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    
    formatter = logging.Formatter(
        '%(asctime)s | %(levelname)-8s | %(name)s | %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    file_handler.setFormatter(formatter)
    console_handler.setFormatter(formatter)
    
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)
    
    return logger