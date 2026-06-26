"""
日志配置公共模块

遵循 PROJECT.md 日志规范：
- 日志框架：Python logging 模块
- 日志级别：DEBUG/INFO/WARNING/ERROR/CRITICAL
- 日志路径：脚本当前目录下 logs/ 子目录
- 文件命名：<脚本名>_YYYY-MM-DD.log
- 日志格式：%(asctime)s | %(levelname)-8s | %(name)s | %(message)s

使用方式：
    from stock_selector.common.logger_config import get_logger

    logger = get_logger(__name__)
    logger.info("数据加载完成")
"""

import inspect
import logging
from datetime import datetime
from pathlib import Path


def get_logger(name: str, log_dir: Path | None = None) -> logging.Logger:
    """
    获取配置好的 logger

    参数:
        name: logger 名称（通常使用 __name__）
        log_dir: 日志目录（默认为 stock_selector/logs/）

    返回:
        配置好的 Logger 对象
    """
    logger = logging.getLogger(name)

    # 防止重复配置
    if logger.handlers:
        return logger

    # 日志目录：stock_selector/logs/<pipeline_alias>/
    if log_dir is None:
        import os

        alias = os.environ.get("PIPELINE_ALIAS", "default")
        log_dir = Path(__file__).parent.parent / "logs" / alias

    log_dir.mkdir(exist_ok=True)

    # 日志文件命名：<脚本名>_YYYY-MM-DD.log
    if name == "__main__":
        caller_frame = inspect.currentframe()
        if caller_frame is not None and caller_frame.f_back is not None:
            caller_file = caller_frame.f_back.f_code.co_filename
            module_name = Path(caller_file).stem
        else:
            module_name = "unknown"
    else:
        module_name = name.split(".")[-1]
    date_str = datetime.now().strftime("%Y-%m-%d")
    log_file = log_dir / f"{module_name}_{date_str}.log"

    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(formatter)

    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(formatter)

    logger.setLevel(logging.DEBUG)
    logger.addHandler(console_handler)
    logger.addHandler(file_handler)

    return logger


def set_log_level(level: str):
    """动态调整日志级别"""
    level_map = {
        "DEBUG": logging.DEBUG,
        "INFO": logging.INFO,
        "WARNING": logging.WARNING,
        "ERROR": logging.ERROR,
        "CRITICAL": logging.CRITICAL,
    }

    if level not in level_map:
        raise ValueError(f"无效日志级别: {level}\n合法值: {list(level_map.keys())}")

    root_logger = logging.getLogger()
    root_logger.setLevel(level_map[level])

    for handler in root_logger.handlers:
        if isinstance(handler, logging.StreamHandler) and not isinstance(handler, logging.FileHandler):
            handler.setLevel(level_map[level])


LOG_DIR = Path(__file__).parent.parent / "logs"
LOG_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
