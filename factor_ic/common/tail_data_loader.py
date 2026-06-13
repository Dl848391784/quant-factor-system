#!/usr/bin/env python3
"""
尾盘数据加载公共模块

遵循 PROJECT.md H1 规则：factor_ic 模块公共复用模块
遵循 PROJECT.md H7 规则：使用 paths.py 单一来源

提供尾盘数据加载功能，供 factor_ic 模块内复用。

作者: 云瑶
创建日期: 2026-06-02
"""

import gzip
import json

import pandas as pd
from paths import DATA_FETCHERS_RESULT  # 遵循 PROJECT.md H7 规则

from factor_ic.common.logger_config import get_logger


logger = get_logger(__name__)

# 尾盘数据路径（遵循 PROJECT.md H7 规则：使用 paths.py 单一来源）
TAIL_TRADING_DATA_PATH = DATA_FETCHERS_RESULT / "tail_trading_data.json.gz"


def load_tail_trading_data() -> pd.DataFrame:
    """
    加载尾盘数据

    Returns:
        DataFrame，包含 date, asset, prices, volumes, tail_high, tail_low 列

    Raises:
        FileNotFoundError: 尾盘数据文件不存在
        ValueError: 尾盘数据格式错误

    Note:
        - 数据来源：data_fetchers/fetch_tail_trading.py 输出
        - 数据格式：gzip 压缩 JSON，含 meta 和 data 字段
        - 数据范围：14:00-15:00 的 13 根 5 分钟 K 线

    Example:
        >>> from factor_ic.common.tail_data_loader import load_tail_trading_data
        >>> df = load_tail_trading_data()
        >>> print(df.columns.tolist())
        ['date', 'asset', 'prices', 'volumes', 'tail_high', 'tail_low']
    """
    if not TAIL_TRADING_DATA_PATH.exists():
        raise FileNotFoundError(f"尾盘数据文件不存在: {TAIL_TRADING_DATA_PATH}")

    with gzip.open(TAIL_TRADING_DATA_PATH, "rt", encoding="utf-8") as f:
        try:
            data = json.load(f)
        except (gzip.BadGzipFile, json.JSONDecodeError, OSError) as e:
            raise ValueError(f"尾盘数据文件损坏或格式错误 [{TAIL_TRADING_DATA_PATH}]: {e}") from e

    if "data" not in data:
        raise ValueError("尾盘数据格式错误：缺少 'data' 字段")

    df = pd.DataFrame(data["data"])

    # 列校验：确保必需列齐全，schema 变更时立即暴露而非延迟到下游
    required_columns = ["date", "asset", "prices", "volumes", "tail_high", "tail_low"]
    missing_columns = [col for col in required_columns if col not in df.columns]
    if missing_columns:
        raise ValueError(
            f"尾盘数据缺少必需列: {missing_columns}，实际列: {df.columns.tolist()} [{TAIL_TRADING_DATA_PATH}]"
        )

    logger.info("尾盘数据加载完成: %d 条记录", len(df))
    return df
