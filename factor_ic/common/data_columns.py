#!/usr/bin/env python3
"""
因子数据列名常量与 schema 校验

提供标准列组常量（JOIN_KEYS / OHLC / OHLCV / PRICE_VOLUME），
消除 34 个 ic 脚本中 factor_cols 字面量排序漂移和拼写风险。
同时提供 validate_required_columns() 运行时校验函数，
在数据加载后、IC 计算前检测列缺失并抛出 DataSchemaError。

设计意图（遵循 factor_cols_literal_constant_design.md §3.4）：
- 只抽象 2+ 脚本共用的列组，单脚本特有组合直接在 FactorSpec 写 tuple
- 列组内按字母序排列，消除排序漂移
- JOIN_KEYS 作为固定前缀，required_columns = JOIN_KEYS + (...)

作者: 云瑶
创建日期: 2026-06-15
版本历史:
  v1.0 (2026-06-15): 落地标准列组常量 + validate_required_columns
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from factor_ic.common.exceptions import DataSchemaError


# ============================================================================
# 标准列组常量（按字母序排列，消除排序漂移）
# ============================================================================

# 索引列（每个因子必须包含，作为 DataFrame 的 join key）
JOIN_KEYS: tuple[str, ...] = ("date", "asset")

# 行情列组
OHLC: tuple[str, ...] = ("close", "high", "low", "open")
OHLCV: tuple[str, ...] = ("close", "high", "low", "open", "volume")
PRICE_VOLUME: tuple[str, ...] = ("close", "turnover_rate", "volume")


# ============================================================================
# 运行时 schema 校验
# ============================================================================


def validate_required_columns(
    factor_name: str,
    required_columns: tuple[str, ...] | list[str],
    available_columns: list[str] | tuple[str, ...],
) -> None:
    """校验因子声明的 required_columns 是否在可用列中。

    Args:
        factor_name: 因子名称（用于错误信息上下文）
        required_columns: FactorSpec 声明的必需列
        available_columns: 数据源实际可用列（DataFrame.columns 或 columns.json）

    Raises:
        DataSchemaError: 缺失列时抛出，含因子名 + 缺失列 + 可用列
    """
    available_set = set(available_columns)
    missing = [col for col in required_columns if col not in available_set]
    if missing:
        raise DataSchemaError(
            factor_name=factor_name,
            missing=missing,
            available=list(available_columns),
        )


# ============================================================================
# 消费者 schema 查询（读 factor_ic_data_columns.json）
# ============================================================================

_DEFAULT_COLUMNS_PATH = Path(__file__).parent.parent.parent / "data_fetchers" / "result" / "factor_ic_data_columns.json"

_CACHED_COLUMNS: dict[str, Any] | None = None


def load_available_columns(columns_path: Path | None = None) -> dict[str, list[str]]:
    """从 factor_ic_data_columns.json 加载列名清单（模块级缓存，只读一次）。

    Args:
        columns_path: 列名清单文件路径（默认 data_fetchers/result/factor_ic_data_columns.json）

    Returns:
        {"base_cols": [...], "extended_factor_cols": [...], "return_cols": [...], "all_cols": [...]}

    Note:
        - 文件不存在时返回空 dict（降级，不阻塞主流程；validate 仍由 data_loader KeyError 兜底）
        - 模块级缓存：首次调用读文件，后续调用直接返回（遵循 design §4.2 方案 B）
    """
    global _CACHED_COLUMNS
    if _CACHED_COLUMNS is not None:
        return _CACHED_COLUMNS

    path = columns_path or _DEFAULT_COLUMNS_PATH
    logger = logging.getLogger(__name__)

    if not path.exists():
        logger.warning("列名清单不存在: %s（降级: 跳过 schema 预校验）", path)
        _CACHED_COLUMNS = {}
        return {}

    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        _CACHED_COLUMNS = data
        return data
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("列名清单读取失败: %s, 原因: %s（降级: 跳过 schema 预校验）", path, e)
        _CACHED_COLUMNS = {}
        return {}
