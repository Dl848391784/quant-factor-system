#!/usr/bin/env python3
"""
CLI 辅助公共模块 - 因子 IC 入口脚本通用工具

为 30+ 个 factor_ic/ic_*.py 入口脚本提供统一的：
- 公共模块返回结构归一化（safe_dict）
- 数值有效性谓词（is_finite_value）
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
  v1.1 (2026-06-15): 新增 is_finite_value 谓词，让业务层 warning 判定与
                     表示层 format_finite 解耦
"""

from __future__ import annotations

import logging
import math
from typing import Any, TypeGuard


__version__ = "1.1.0"


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
                "返回字段 '%s' 期望 dict|None，实际 %s，已 fallback 为空字典",
                field_name,
                type(data).__name__,
            )
        return {}
    return data


def is_finite_value(value: Any) -> TypeGuard[float]:
    """判断值是否为合法有限数值（None/NaN/±Inf/非数/bool 均视为无效）。

    用于因子 IC 入口脚本在格式化前后的业务判定（如 warning 触发条件，
    或量纲范围校验），与 format_finite() 的内部判定逻辑完全等价，但暴露
    为独立 TypeGuard 谓词以避免业务层依赖"格式化结果 == 'N/A'"这种
    表示层耦合：若 format_finite 的 fallback 字符串改动，warning 不会失效。

    返回值标注 TypeGuard[float] 让调用点的类型检查器（mypy/pyright）能
    自动收窄分支内的 value 类型为 float，使 `value <= 1.0` 等数值比较合法。
    （int 实例同样满足 `isinstance(x, (int, float))` 并能与 float 安全比较，
    标注为 float 是 numerics 谓词的常见简化做法。）

    Args:
        value: 待判定的值

    Returns:
        True: value 是合法的有限 int/float（含 0、负数、极小值）
        False: value 是 None / NaN / ±Inf / 非数值类型 / bool

    Examples:
        >>> is_finite_value(0.0)
        True
        >>> is_finite_value(None)
        False
        >>> is_finite_value(float("nan"))
        False
        >>> is_finite_value(float("inf"))
        False
        >>> is_finite_value("0.5")
        False
        >>> is_finite_value(True)
        False
    """
    if value is None:
        return False
    # bool 是 int 子类，单独排除（业务上不应被当作数值）
    if isinstance(value, bool):
        return False
    if not isinstance(value, (int, float)):
        return False
    return math.isfinite(value)


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
    # 复用 is_finite_value 谓词，避免判定逻辑双重维护。
    if not is_finite_value(value):
        return "N/A"
    return format(value, fmt)


__all__ = [
    "DEFAULT_MIN_STOCKS",
    "safe_dict",
    "format_finite",
]
