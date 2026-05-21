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
- isinstance 多类型检查禁止合并：必须显式分开处理（如 np.bool_ 和 bool），因为：
  * bool 是 int 的子类，若合并为 isinstance(obj, (np.bool_, bool))，
    在分支顺序变化时（如有人在 bool 之前添加 int 检查）会被误判
  * 显式分开处理：意图清晰，防止分支顺序变化导致的隐蔽 bug

容器类型处理（2026-05-22）：
- dict: 递归转换值
- list: 递归转换元素
- tuple: 递归转换元素并返回 tuple（numpy 操作如 np.where 返回 tuple）
- np.ndarray/pd.Series: 转为 list 后递归处理
- pd.DataFrame: 转为 list of dicts（每行一个 dict，to_dict('records'))

pandas 缺失值处理（2026-05-22）：
- pd.NaT: 缺失时间，转为 None（使用 `obj is pd.NaT` 检查单例，必须在 pd.Timestamp 之前检查）
- pd.NA: 扩展类型缺失值，转为 None（使用 `obj is pd.NA` 检查单例）
- np.NaN/nan: numpy 浮点 NaN，转为 None（在 np.floating 分支处理）
- 检查顺序：pd.NaT/pd.NA → pd.Timestamp（某些版本 NaTType 继承 Timestamp，防止误判）
- 单例检查规范：必须用 `is` 判断，禁止 `isinstance(obj, type(singleton))`：
  * isinstance 依赖私有内部类（如 pandas.core.arrays.masked.NAType），跨版本不稳定
  * 单例对象用 `is` 即可完全覆盖，isinstance 检查是冗余的

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
    # 显式分开处理：防止分支顺序变化导致误判，意图清晰
    elif isinstance(obj, np.bool_):
        # numpy 布尔类型
        return bool(obj)
    elif isinstance(obj, bool):
        # Python 布尔类型（必须在 integer 之前，因为 bool 是 int 的子类）
        return obj
    
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
        # Series.tolist() 对扩展类型（如 Int64 dtype）可能残留 pd.NA：
        # - pd.Series([1, pd.NA], dtype='Int64').tolist() → [1, pd.NA]（非 None）
        # - 后续递归调用 convert_to_native_types 会处理 pd.NA
        # - 依赖关系：此分支 → obj is pd.NA 分支（勿删除）
        return convert_to_native_types(obj.tolist())
    
    elif isinstance(obj, pd.DataFrame):
        # DataFrame 转为 list of dicts（每行一个 dict）
        return convert_to_native_types(obj.to_dict('records'))
    
    # pandas 缺失值检查必须在 pd.Timestamp 之前（某些版本 NaTType 继承 Timestamp）
    elif obj is pd.NaT:
        # pandas 缺失时间，转为 None（单例检查）
        return None
    
    elif obj is pd.NA:
        # pandas 扩展类型缺失值（pd.NA 是单例对象，用 is 检查）
        return None
    
    elif isinstance(obj, pd.Timestamp):
        # pandas 时间戳转字符串（pd.NaT 已在前面处理）
        return str(obj)
    
    elif isinstance(obj, float):
        # 处理 Python float 的 NaN
        if np.isnan(obj):
            return None
        return obj
    
    else:
        return obj


if __name__ == '__main__':
    # 简单测试
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