"""
日志配置公共模块

遵循 PROJECT.md 第380-500行日志规范：
- 日志框架：Python logging 模块
- 日志级别：DEBUG/INFO/WARNING/ERROR/CRITICAL
- 日志路径：脚本当前目录下 logs/ 子目录
- 文件命名：<脚本名>_YYYY-MM-DD.log
- 日志格式：%(asctime)s | %(levelname)-8s | %(name)s | %(message)s

公共模块日志传递规范（PROJECT.md 第783-857行）：
- 公共模块不独立创建 logger，由调用方传入
- 公共函数签名：def public_function(..., logger=None)
- 调用方传入：data = load_data_from_cache(cache_path, logger=logger)

使用方式：
    # 因子脚本（独立使用）
    from factor_ic.common.logger_config import get_logger

    logger = get_logger(__name__)
    logger.info("数据加载完成")

    # 公共模块（接收调用方 logger）
    def load_data_from_cache(cache_path, logger=None):
        if logger is None:
            logger = get_logger(__name__)  # fallback
        logger.info("数据加载完成")
        return data

作者: 云瑶
更新历史：
- v2.1 (2026-06-05): 修复 __main__ 模式下日志文件名问题，使用 inspect 从调用栈获取实际脚本名
- v2.0 (2026-06-04): 重写自动文件输出，废弃 log_file 参数
- v1.0 (2026-05-24): 初始版本
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
        log_dir: 日志目录（默认为 factor_ic/logs/）

    返回:
        配置好的 Logger 对象

    使用示例:
        logger = get_logger(__name__)
        logger.info("IC 计算完成，有效天数: 514")
    """
    logger = logging.getLogger(name)

    # 防止重复配置（logger 可能已被其他模块配置）
    if logger.handlers:
        return logger

    # 日志目录：factor_ic/logs/<pipeline_alias>/
    if log_dir is None:
        # logger_config.py 位于 factor_ic/common/
        # log_dir 应为 factor_ic/logs/<alias>/
        import os

        alias = os.environ.get("PIPELINE_ALIAS", "default")
        log_dir = Path(__file__).parent.parent / "logs" / alias

    log_dir.mkdir(exist_ok=True)

    # 日志文件命名：<脚本名>_YYYY-MM-DD.log
    # 当 name == "__main__" 时，从调用栈获取实际文件名（遵循 PROJECT.md 第 436 行规范）
    # 否则从 name 中提取模块名（如 factor_ic.common.data_loader → data_loader）
    if name == "__main__":
        # 获取调用方文件路径
        caller_frame = inspect.currentframe()
        if caller_frame is not None and caller_frame.f_back is not None:
            caller_file = caller_frame.f_back.f_code.co_filename
            module_name = Path(caller_file).stem  # 文件名不含扩展名
        else:
            module_name = "unknown"  # 无法获取调用方时使用 fallback
    else:
        module_name = name.split(".")[-1]
    date_str = datetime.now().strftime("%Y-%m-%d")
    log_file = log_dir / f"{module_name}_{date_str}.log"

    # 日志格式：%(asctime)s | %(levelname)-8s | %(name)s | %(message)s
    formatter = logging.Formatter("%(asctime)s | %(levelname)-8s | %(name)s | %(message)s", datefmt="%Y-%m-%d %H:%M:%S")

    # 控制台处理器（INFO 及以上）
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(formatter)

    # 文件处理器（DEBUG 及以上，持久化）
    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(formatter)

    # 配置 logger
    logger.setLevel(logging.DEBUG)  # logger 级别设为最低，由 handler 控制输出
    logger.addHandler(console_handler)
    logger.addHandler(file_handler)

    return logger


def set_log_level(level: str):
    """
    动态调整日志级别

    参数:
        level: 日志级别字符串（'DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'）

    使用示例:
        set_log_level('DEBUG')  # 开发阶段查看所有细节
        set_log_level('WARNING')  # 生产环境减少日志量
    """
    level_map = {
        "DEBUG": logging.DEBUG,
        "INFO": logging.INFO,
        "WARNING": logging.WARNING,
        "ERROR": logging.ERROR,
        "CRITICAL": logging.CRITICAL,
    }

    if level not in level_map:
        raise ValueError(f"无效日志级别: {level}\n合法值: {list(level_map.keys())}")

    # 获取根 logger 并设置级别
    root_logger = logging.getLogger()
    root_logger.setLevel(level_map[level])

    # 同步调整所有 handler 级别
    for handler in root_logger.handlers:
        if isinstance(handler, logging.StreamHandler) and not isinstance(handler, logging.FileHandler):
            # 控制台 handler 级别与 logger 级别一致
            handler.setLevel(level_map[level])


# 模块级常量（便于代码引用）
LOG_DIR = Path(__file__).parent.parent / "logs"
LOG_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
