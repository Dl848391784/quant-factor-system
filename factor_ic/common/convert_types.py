#!/usr/bin/env python3
"""
类型转换模块

将 numpy/pandas 类型转换为 Python 原生类型，
确保 JSON 序列化正常工作。

类型检查规范（2026-05-22）：
- np.integer 是所有 numpy 整数类型的抽象基类，无需显式列举子类
- np.floating 是所有 numpy 浮点类型的抽象基类，无需显式列举子类
- 显式列举子类（如 np.int64/np.int32）是冗余的，且会造成误解
- bool 检查必须在 integer 之前（Python bool 是 int 的子类，防止误判）

容器类型处理（2026-05-22）：
- dict: 递归转换值
- list: 递归转换元素
- tuple: 递归转换元素并返回 tuple（numpy 操作如 np.where 返回 tuple）
- np.ndarray/pd.Series: 转为 list 后递归处理

作者: 云舟
日期: 2026-05-10
"""

import numpy as np
import pandas as pd
from typing import Any


def convert_to_native_types(obj: Any) -> Any:
    """
    递归转换 numpy/pandas 类型为 Python 原生类型
    
    解决 JSON 序列化时 numpy 类型无法直接序列化的问题。
    
    Args:
        obj: 要转换的对象（可以是 dict, list, numpy 类型等）
        
    Returns:
        转换后的 Python 原生类型对象
        
    示例:
        >>> import numpy as np
        >>> convert_to_native_types({'value': np.float64(1.5)})
        {'value': 1.5}
        >>> convert_to_native_types([np.int64(10), np.float32(2.5)])
        [10, 2.5]
    """
    if obj is None:
        return None
    
    if isinstance(obj, dict):
        return {k: convert_to_native_types(v) for k, v in obj.items()}
    
    elif isinstance(obj, list):
        return [convert_to_native_types(v) for v in obj]
    
    elif isinstance(obj, tuple):
        # tuple 递归转换（numpy 操作如 np.where 返回 tuple）
        return tuple(convert_to_native_types(v) for v in obj)
    
    # bool 检查必须在 integer 之前（Python bool 是 int 的子类）
    elif isinstance(obj, (np.bool_, bool)):
        # np.bool_: numpy 布尔类型，bool: Python 布尔类型
        return bool(obj)
    
    elif isinstance(obj, np.integer):
        # np.integer 是所有 numpy 整数类型的抽象基类（int64/int32/int16/int8/uint64等）
        return int(obj)
    
    elif isinstance(obj, np.floating):
        # np.floating 是所有 numpy 浮点类型的抽象基类（float64/float32/float16）
        # 处理 NaN
        if np.isnan(obj):
            return None
        return float(obj)
    
    elif isinstance(obj, np.ndarray):
        return convert_to_native_types(obj.tolist())
    
    elif isinstance(obj, pd.Series):
        return convert_to_native_types(obj.tolist())
    
    elif isinstance(obj, pd.Timestamp):
        return str(obj)
    
    elif isinstance(obj, float):
        # 处理 Python float 的 NaN
        if np.isnan(obj):
            return None
        return obj
    
    else:
        return obj


if __name__ == '__main__':
    """简单测试"""
    # 测试字典
    test_dict = {
        'int': np.int64(10),
        'float': np.float64(1.5),
        'nan': np.float64(np.nan),
        'array': np.array([1, 2, 3]),
        'nested': {
            'value': np.float32(2.5)
        }
    }
    
    result = convert_to_native_types(test_dict)
    print("转换结果:")
    print(f"  int: {result['int']} (type: {type(result['int']).__name__})")
    print(f"  float: {result['float']} (type: {type(result['float']).__name__})")
    print(f"  nan: {result['nan']} (应为 None)")
    print(f"  array: {result['array']}")
    print(f"  nested.value: {result['nested']['value']}")
    
    # 测试 JSON 序列化
    import json
    json_str = json.dumps(result, ensure_ascii=False)
    print(f"\nJSON 序列化成功: {len(json_str)} chars")