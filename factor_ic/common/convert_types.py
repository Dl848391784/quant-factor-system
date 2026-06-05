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

容器类型处理（2026-05-23）：
- dict: 递归转换键和值（键也需转换，如 np.int64 键）
- list: 递归转换元素
- tuple: 递归转换元素并返回 tuple（numpy 操作如 np.where 返回 tuple）
- np.ndarray/pd.Series: 转为 list 后递归处理
- pd.DataFrame: 转为 list of dicts（每行一个 dict，to_dict('records')）

pandas 缺失值处理（2026-05-23）：
- pd.NaT: 缺失时间，转为 None（单例检查）
- pd.NA: 扩展类型缺失值，转为 None（单例检查）
- np.NaN/nan: numpy 浮点 NaN/Inf，转为 None
- Python float NaN/Inf: 转为 None
- 单例检查规范（2026-05-23更新）：
  * 单例检查（pd.NaT/pd.NA）必须放在所有 isinstance 检查之前
  * 必须用 `is` 判断，禁止 `isinstance(obj, type(singleton))`
  * isinstance 依赖类型继承，而 pd.NaT 在某些 pandas 版本继承 pd.Timestamp
  * 单例检查不依赖类型继承，跨版本稳定

NaN/Inf 检查规范（2026-05-23）：
- numpy 浮点类型：使用 `np.isnan(obj) or np.isinf(obj)`
- Python float 类型：使用 `math.isnan(obj) or math.isinf(obj)`
- NaN 和 Inf 都转为 None（JSON 不支持 Inf）
- 禁止混用：语义不准确，增加不必要的依赖

作者: 云舟
日期: 2026-05-10
最后修改: 2026-05-23（修复单例检查顺序、dict键转换、Inf检查遗漏）
"""

import math
from typing import Any

import numpy as np
import pandas as pd

from .logger_config import get_logger


logger = get_logger(__name__)


def convert_to_native_types(obj: Any) -> Any:
    """
    递归转换 numpy/pandas 类型为 Python 厬生类型
    
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
    # None 直接返回
    if obj is None:
        return None

    # 单例检查：必须在所有 isinstance 检查之前
    # 单例对象用 `is` 判断，不依赖类型继承，跨版本稳定
    if obj is pd.NaT:
        # pandas 缺失时间，转为 None
        return None

    if obj is pd.NA:
        # pandas 扩展类型缺失值，转为 None
        return None

    # 容器类型：递归处理
    if isinstance(obj, dict):
        # 字典的键和值都需要转换（键可能是 numpy 类型）
        return {convert_to_native_types(k): convert_to_native_types(v) for k, v in obj.items()}

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
        # 处理 NaN 和 Inf
        if np.isnan(obj) or np.isinf(obj):
            return None
        return float(obj)

    elif isinstance(obj, np.ndarray):
        # ndarray.tolist() 对 object dtype 不做元素转换，必须递归处理
        # 例如：np.array([np.int64(1), np.float64(2.5)], dtype=object).tolist()
        #       返回 [np.int64(1), np.float64(2.5)]，而非 [1, 2.5]
        # 因此必须递归调用 convert_to_native_types 处理每个元素
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

    elif isinstance(obj, pd.Timestamp):
        # pandas 时间戳转字符串（pd.NaT 已在前面单例检查处理）
        return str(obj)

    elif isinstance(obj, float):
        # 处理 Python float 的 NaN 和 Inf
        if math.isnan(obj) or math.isinf(obj):
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
    logger.info("转换结果:")
    logger.info(f"  int: {result['int']} (type: {type(result['int']).__name__})")
    logger.info(f"  float: {result['float']} (type: {type(result['float']).__name__})")
    logger.info(f"  nan: {result['nan']} (应为 None)")
    logger.info(f"  array: {result['array']}")
    logger.info(f"  nested.value: {result['nested']['value']}")

    # 测试 JSON 序列化
    import json
    json_str = json.dumps(result, ensure_ascii=False)
    logger.info(f"\nJSON 序列化成功: {len(json_str)} chars")
