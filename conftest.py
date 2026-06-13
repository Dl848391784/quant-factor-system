"""项目级 pytest conftest：测试期间抑制模块日志的 console 输出。

模块 logger_config.py 注册了 StreamHandler(INFO)，pytest 运行时每条
logger.info() 都会打印到 stdout，导致大量日志字符涌入前台，干扰
测试结果阅读。

解决方案：session 级 fixture 将所有模块 logger 的 console handler
临时提升为 WARNING（仅错误/警告输出到前台），session 结束后恢复。
INFO/DEBUG 日志仍写入各模块 logs/ 文件（FileHandler 不受影响），
不丢失调试信息。
"""

import logging

import pytest


@pytest.fixture(scope="session", autouse=True)
def suppress_console_logging():
    """将所有已注册 logger 的 StreamHandler 级别临时提升为 WARNING。

    autouse=True + scope=session → 全局生效，无需手动标记测试。
    恢复逻辑在 teardown 执行，保证不影响正常开发时的日志输出。
    """
    # 记录原始级别，用于 teardown 恢复
    original_levels: dict[str, int] = {}

    # 遍历所有已注册的 logger（包括 root 和命名 logger）
    for name in logging.root.manager.loggerDict:
        logger = logging.getLogger(name)
        for handler in logger.handlers:
            if isinstance(handler, logging.StreamHandler) and not isinstance(handler, logging.FileHandler):
                original_levels[f"{name}:{id(handler)}"] = handler.level
                handler.setLevel(logging.WARNING)

    # 也处理 root logger
    for handler in logging.root.handlers:
        if isinstance(handler, logging.StreamHandler) and not isinstance(handler, logging.FileHandler):
            original_levels[f"root:{id(handler)}"] = handler.level
            handler.setLevel(logging.WARNING)

    yield  # 测试运行期间保持 WARNING 级别

    # teardown: 恢复原始级别
    for name in logging.root.manager.loggerDict:
        logger = logging.getLogger(name)
        for handler in logger.handlers:
            key = f"{name}:{id(handler)}"
            if (
                key in original_levels
                and isinstance(handler, logging.StreamHandler)
                and not isinstance(handler, logging.FileHandler)
            ):
                handler.setLevel(original_levels[key])

    for handler in logging.root.handlers:
        key = f"root:{id(handler)}"
        if (
            key in original_levels
            and isinstance(handler, logging.StreamHandler)
            and not isinstance(handler, logging.FileHandler)
        ):
            handler.setLevel(original_levels[key])
