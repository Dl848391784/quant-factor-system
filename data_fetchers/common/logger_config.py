#!/usr/bin/env python3
"""
日志配置模块

遵循 PROJECT.md 第780-839行规范：
- 日志目录：脚本当前目录/logs/
- 日志文件：<脚本名>_YYYY-MM-DD.log
- 日志格式：%(asctime)s | %(levelname)-8s | %(name)s | %(message)s
- 日志级别：INFO（生产）/ DEBUG（开发）

作者: 云瑶
日期: 2026-05-24
"""

import logging
from datetime import datetime
from pathlib import Path


__all__ = ['setup_logger']


def setup_logger(
    script_name: str,
    logs_dir: Path | None = None,
    level: int = logging.INFO,
    console_level: int = logging.INFO
) -> logging.Logger:
    """
    配置日志记录器
    
    遵循 PROJECT.md 第780-839行规范。
    
    Args:
        script_name: 脚本名称（不含 .py 后缀）
        logs_dir: 日志目录（默认：脚本当前目录/logs/）
        level: 文件日志级别（默认：INFO）
        console_level: 控制台日志级别（默认：INFO）
        
    Returns:
        配置好的 Logger 对象
        
    Example:
        # 生产环境
        logger = setup_logger('ic_rsi_1d')
        logger.info("开始计算 IC...")
        
        # 开发环境（DEBUG 级别）
        logger = setup_logger('ic_rsi_1d', level=logging.DEBUG)
        logger.debug("详细调试信息...")
        
        # 自定义日志目录
        logger = setup_logger('ic_rsi_1d', logs_dir=Path('/custom/logs'))
    """
    # 日志目录（默认：脚本所在目录/logs/）
    if logs_dir is None:
        logs_dir = Path(__file__).parent.parent / 'logs'
    logs_dir.mkdir(parents=True, exist_ok=True)  # 自动创建

    # 日志文件名
    today = datetime.now().strftime('%Y-%m-%d')
    log_file = logs_dir / f"{script_name}_{today}.log"

    # 创建 Logger
    logger = logging.getLogger(script_name)
    logger.setLevel(level)

    # 防止重复添加 Handler（多次调用时）
    if logger.handlers:
        return logger

    # 文件 Handler
    file_handler = logging.FileHandler(
        log_file,
        mode='a',  # 追加模式，同一天的日志合并到同一文件
        encoding='utf-8'
    )
    file_handler.setLevel(level)

    # 控制台 Handler（可选，便于开发调试）
    console_handler = logging.StreamHandler()
    console_handler.setLevel(console_level)

    # Formatter（遵循 PROJECT.md 规范）
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
