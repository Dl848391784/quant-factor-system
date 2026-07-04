#!/usr/bin/env python3
"""
内存监控工具模块

提供进程内存使用监控功能，用于大数据处理场景下的内存预警和日志记录。

遵循 PROJECT.md 规范：
- 使用 Python 标准库 logging 模块
- 公共模块函数接收 logger 参数

作者: 云瑶
创建日期: 2026-05-27
"""

import sys


def get_memory_usage_mb() -> float:
    """
    获取当前进程真实RSS内存（MB）- 从 /proc/self/status

    Returns:
        float: RSS内存大小（MB），Linux下从/proc/self/status读取，
               其他系统使用resource.getrusage()，Windows返回0.0

    Note:
        - Linux: 读取VmRSS字段（实际物理内存使用）
        - macOS/Unix: 使用ru_maxrss（最大RSS值，可能不准确）
          macOS下ru_maxrss单位是bytes，需除以1024*1024
          Linux下ru_maxrss单位是KB，需除以1024
        - Windows: 返回0.0（不支持）
    """
    try:
        with open("/proc/self/status") as f:
            for line in f:
                if line.startswith("VmRSS:"):
                    return int(line.split()[1]) / 1024  # kB -> MB
    except Exception:
        pass
    try:
        import resource

        maxrss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        # macOS: ru_maxrss 单位是 bytes；Linux: 单位是 KB
        if sys.platform == "darwin":
            return maxrss / (1024 * 1024)  # bytes -> MB
        else:
            return maxrss / 1024  # KB -> MB
    except Exception:
        return 0.0  # Windows 或其他不支持的环境


def get_memory_info_str() -> str:
    """
    获取详细内存信息字符串

    Returns:
        str: 格式化的内存信息，如 "RSS=700.5MB, VM=900.0MB"

    Note:
        - Linux: 同时读取VmRSS和VmSize
        - 其他系统: 仅返回RSS信息
    """
    try:
        with open("/proc/self/status") as f:
            vmrss = vmsize = None
            for line in f:
                if line.startswith("VmRSS:"):
                    vmrss = int(line.split()[1]) / 1024
                elif line.startswith("VmSize:"):
                    vmsize = int(line.split()[1]) / 1024
            if vmrss is not None:
                return f"RSS={vmrss:.1f}MB" + (f", VM={vmsize:.1f}MB" if vmsize is not None else "")
    except Exception:
        pass
    return f"RSS={get_memory_usage_mb():.1f}MB"


# 模块级常量
__all__ = ["get_memory_usage_mb", "get_memory_info_str"]
