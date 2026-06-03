"""
类型转换模块

复用 backtest/common/convert_types.py 的设计，
将 numpy/pandas 类型转换为 Python 原生类型，
确保 JSON 序列化兼容。

作者: 云瑶
创建日期: 2026-05-24
"""

from datetime import date, datetime

import numpy as np
import pandas as pd


def convert_to_native_types(obj):
    """递归转换 numpy/pandas 类型为 Python 原生类型
    
    Args:
        obj: 待转换对象（dict, list, numpy类型, pandas类型等）
    
    Returns:
        转换后的 Python 原生类型对象
    """
    if obj is None:
        return None

    # numpy 整数/浮点数
    if isinstance(obj, (np.integer, np.int64, np.int32, np.int16, np.int8)):
        return int(obj)
    if isinstance(obj, (np.floating, np.float64, np.float32, np.float16)):
        return float(obj)

    # numpy bool
    if isinstance(obj, np.bool_):
        return bool(obj)

    # numpy 数组
    if isinstance(obj, np.ndarray):
        return [convert_to_native_types(item) for item in obj.tolist()]

    # pandas Series/DataFrame
    if isinstance(obj, pd.Series):
        return [convert_to_native_types(item) for item in obj.tolist()]
    if isinstance(obj, pd.DataFrame):
        return obj.applymap(convert_to_native_types).to_dict(orient='records')

    # datetime/date
    if isinstance(obj, datetime):
        return obj.isoformat()
    if isinstance(obj, date):
        return obj.isoformat()
    if isinstance(obj, pd.Timestamp):
        return obj.isoformat()

    # dict（递归处理）
    if isinstance(obj, dict):
        return {k: convert_to_native_types(v) for k, v in obj.items()}

    # list/tuple（递归处理）
    if isinstance(obj, (list, tuple)):
        return [convert_to_native_types(item) for item in obj]

    # 其他类型直接返回
    return obj
