#!/usr/bin/env python3
"""
CLI 辅助公共模块 - 因子 IC 入口脚本通用工具

为 30+ 个 factor_ic/ic_*.py 入口脚本提供统一的：
- 公共模块返回结构归一化（safe_dict）
- 数值格式化（含 NaN/Inf 守卫，format_finite）
- 默认参数常量（DEFAULT_MIN_STOCKS）

设计原则（遵循 PROJECT.md 第783-857行 公共模块日志传递规范）：
- 不独立创建 logger，由调用方传入
- 函数签名：def public_function(..., logger=None)
- 调用方传入：safe_dict(data, field_name='xxx', logger=logger)

使用示例：
    from factor_ic.common.cli_helpers import (
        DEFAULT_MIN_STOCKS,
        format_finite,
        safe_dict,
    )

    sample_stats = safe_dict(result.get("sample_stats"),
                             field_name="sample_stats",
                             logger=logger)
    ic_mean_str = format_finite(ic_metrics.get("ic_mean"), ".4f")

作者: 云瑶
创建日期: 2026-06-15
版本历史:
  v1.0 (2026-06-15): 从 ic_capital_flow_ratio_trend_1d.py 抽取，公开 API
"""

from __future__ import annotations

import logging
import math
from typing import Any


__version__ = "1.0.0"


# ========== 常量 ==========

# 默认最小股票数阈值，与 factor_ic.common.factor_ic_runner.run_factor_ic_analysis
# 的同名参数默认值一致（=10）。所有因子 IC 入口脚本 CLI --min-stocks 默认值
# 应统一引用此常量，避免各脚本硬编码导致行为漂移。
DEFAULT_MIN_STOCKS: int = 10


# ========== 函数 ==========


def safe_dict(
    data: Any,
    *,
    field_name: str = "<unknown>",
    logger: logging.Logger | None = None,
) -> dict:
    """将任意值安全归一化为 dict。

    用于因子 IC 入口脚本处理 run_factor_ic_analysis 返回的辅助字段
    （sample_stats / period / ic_distribution_consistency 等）：

    - None → 空 dict（字段缺失，正常情况）
    - dict → 原样返回
    - 其他类型 → 空 dict + warning（结构异常但不致命）

    模块级纯函数：依赖通过参数显式声明，便于独立单测与跨脚本复用。

    Args:
        data: 待归一化的值（通常来自 result.get(key)）
        field_name: 用于 warning 日志的字段名标识
        logger: 调用方传入的 logger；为 None 时静默 fallback（不记录 warning）。
            遵循 PROJECT.md 第783-857行 公共模块日志传递规范

    Returns:
        dict（可能为空），保证调用方可安全 .get()

    Examples:
        >>> safe_dict(None)
        {}
        >>> safe_dict({"a": 1})
        {'a': 1}
        >>> safe_dict([1, 2])  # 静默 fallback（无 logger）
        {}
    """
    if data is None:
        return {}
    if not isinstance(data, dict):
        if logger is not None:
            logger.warning(
                f"返回字段 '{field_name}' 期望 dict|None，"
                f"实际 {type(data).__name__}，已 fallback 为空字典"
            )
        return {}
    return data


def format_finite(value: Any, fmt: str) -> str:
    """格式化数值，非有限值（None/NaN/Inf/非数/bool）统一返回 'N/A'。

    用于因子 IC 入口脚本的摘要日志：避免 float('nan') / float('inf')
    静默以 'nan' / 'inf' 字面量流入摘要日志和下游消费者。

    边界处理：
    - None → 'N/A'
    - 非数值类型（str/list/...）→ 'N/A'
    - bool（int 子类，但格式化无业务意义）→ 'N/A'
    - NaN / +Inf / -Inf → 'N/A'
    - 合法数值（含 0、负数、极小值）→ 按 fmt 格式化

    Args:
        value: 待格式化的值
        fmt: 格式说明（如 '.4f', '.2%', '.2f'）

    Returns:
        格式化字符串或 'N/A'

    Examples:
        >>> format_finite(0.1234, ".4f")
        '0.1234'
        >>> format_finite(0.0, ".4f")
        '0.0000'
        >>> format_finite(float("nan"), ".4f")
        'N/A'
        >>> format_finite(float("inf"), ".4f")
        'N/A'
        >>> format_finite(None, ".4f")
        'N/A'
        >>> format_finite("0.5", ".4f")
        'N/A'
        >>> format_finite(True, ".4f")
        'N/A'
        >>> format_finite(-0.05, ".2%")
        '-5.00%'
    """
    if value is None:
        return "N/A"
    # bool 是 int 子类，单独排除（格式化 True/False 无业务意义）
    if isinstance(value, bool):
        return "N/A"
    if not isinstance(value, (int, float)):
        return "N/A"
    if not math.isfinite(value):
        return "N/A"
    return format(value, fmt)


__all__ = [
    "DEFAULT_MIN_STOCKS",
    "safe_dict",
    "format_finite",
]
