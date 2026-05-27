#!/usr/bin/env python3
"""
DataFrame 工具模块

提供 DataFrame 验证和数据处理工具函数。

遵循 PROJECT.md 规范：
- 使用 Python 标准库 logging 模块
- 公共模块函数接收 logger 参数

作者: 云瑶
创建日期: 2026-05-27
"""

import pandas as pd
from typing import Any


def validate_dataframe_columns(
    df: pd.DataFrame,
    required_cols: list[str],
    df_name: str
) -> None:
    """
    验证 DataFrame 是否包含必需列
    
    Args:
        df: DataFrame 对象
        required_cols: 必需列名列表
        df_name: DataFrame 名称（用于错误消息）
    
    Raises:
        ValueError: DataFrame 缺少必需列
    """
    missing_cols = [col for col in required_cols if col not in df.columns]
    if missing_cols:
        raise ValueError(f"{df_name} 缺少必需列: {missing_cols}")


# 模块级常量
__all__ = ['validate_dataframe_columns']