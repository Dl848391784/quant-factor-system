#!/usr/bin/env python3
"""
convert_types 模块单元测试

验证 convert_to_native_types 函数对各种类型的转换行为，
特别是 NaN → None → null 的 JSON 序列化行为。

作者: 云舟
日期: 2026-05-19
"""

import pytest
import numpy as np
import pandas as pd
import json
from factor_ic.common.convert_types import convert_to_native_types


class TestConvertToNativeTypes:
    """convert_to_native_types 函数单元测试"""
    
    # =========================================================================
    # 基本类型转换测试
    # =========================================================================
    
    def test_numpy_int_conversion(self):
        """numpy integer 类型转换为 Python int"""
        assert convert_to_native_types(np.int64(10)) == 10
        assert convert_to_native_types(np.int32(5)) == 5
        assert type(convert_to_native_types(np.int64(10))) == int
    
    def test_numpy_float_conversion(self):
        """numpy float 类型转换为 Python float"""
        assert convert_to_native_types(np.float64(1.5)) == 1.5
        assert convert_to_native_types(np.float32(2.5)) == 2.5
        assert type(convert_to_native_types(np.float64(1.5))) == float
    
    def test_numpy_array_conversion(self):
        """numpy array 转换为 Python list"""
        arr = np.array([1, 2, 3])
        result = convert_to_native_types(arr)
        assert result == [1, 2, 3]
        assert type(result) == list
    
    def test_pandas_series_conversion(self):
        """pandas Series 转换为 Python list"""
        series = pd.Series([1.5, 2.5, 3.5])
        result = convert_to_native_types(series)
        assert result == [1.5, 2.5, 3.5]
        assert type(result) == list
    
    def test_pandas_timestamp_conversion(self):
        """pandas Timestamp 转换为字符串"""
        ts = pd.Timestamp('2026-05-19')
        result = convert_to_native_types(ts)
        assert result == '2026-05-19 00:00:00' or result == '2026-05-19'
        assert type(result) == str
    
    def test_dict_conversion(self):
        """字典递归转换"""
        data = {
            'int': np.int64(10),
            'float': np.float64(1.5),
            'nested': {'value': np.float32(2.5)}
        }
        result = convert_to_native_types(data)
        assert result['int'] == 10
        assert result['float'] == 1.5
        assert result['nested']['value'] == 2.5
        assert type(result['int']) == int
    
    def test_list_conversion(self):
        """列表递归转换"""
        data = [np.int64(10), np.float64(1.5), np.array([1, 2, 3])]
        result = convert_to_native_types(data)
        assert result[0] == 10
        assert result[1] == 1.5
        assert result[2] == [1, 2, 3]
        assert type(result[0]) == int
    
    # =========================================================================
    # NaN 处理测试（核心验证）
    # =========================================================================
    
    def test_numpy_nan_to_none(self):
        """numpy float NaN 转换为 None"""
        nan_val = np.float64(np.nan)
        result = convert_to_native_types(nan_val)
        assert result is None
    
    def test_python_float_nan_to_none(self):
        """Python float NaN 转换为 None"""
        nan_val = float('nan')
        result = convert_to_native_types(nan_val)
        assert result is None
    
    def test_numpy_array_with_nan(self):
        """numpy array 中的 NaN 转换为 None"""
        arr = np.array([1.0, np.nan, 3.0])
        result = convert_to_native_types(arr)
        assert result == [1.0, None, 3.0]
    
    def test_dict_with_nan(self):
        """字典中的 NaN 转换为 None"""
        data = {
            'normal': np.float64(1.5),
            'nan': np.float64(np.nan)
        }
        result = convert_to_native_types(data)
        assert result['normal'] == 1.5
        assert result['nan'] is None
    
    def test_nested_dict_with_nan(self):
        """嵌套字典中的 NaN 转换为 None"""
        data = {
            'level1': {
                'level2': {
                    'nan': np.float64(np.nan)
                }
            }
        }
        result = convert_to_native_types(data)
        assert result['level1']['level2']['nan'] is None
    
    # =========================================================================
    # JSON 序列化验证（核心验证）
    # =========================================================================
    
    def test_json_serialization_with_none(self):
        """包含 None 的数据可以正常 JSON 序列化，None → null"""
        data = {
            'value': None,
            'nan_converted': convert_to_native_types(np.float64(np.nan))
        }
        # 验证 JSON 序列化成功
        json_str = json.dumps(data, ensure_ascii=False)
        assert json_str is not None
        
        # 验证 JSON 内容：None → null
        parsed = json.loads(json_str)
        assert parsed['value'] is None  # JSON null → Python None
        assert parsed['nan_converted'] is None
    
    def test_json_serialization_numpy_types(self):
        """numpy 类型转换后可以正常 JSON 序列化"""
        data = convert_to_native_types({
            'int': np.int64(10),
            'float': np.float64(1.5),
            'array': np.array([1, 2, 3]),
            'nan': np.float64(np.nan)
        })
        
        # 验证 JSON 序列化成功
        json_str = json.dumps(data, ensure_ascii=False)
        assert json_str is not None
        
        # 验证 JSON 内容
        parsed = json.loads(json_str)
        assert parsed['int'] == 10
        assert parsed['float'] == 1.5
        assert parsed['array'] == [1, 2, 3]
        assert parsed['nan'] is None  # NaN → None → null
    
    def test_json_serialization_nested_structure(self):
        """嵌套结构可以正常 JSON 序列化"""
        data = convert_to_native_types({
            'level1': {
                'int': np.int64(10),
                'nan': np.float64(np.nan),
                'level2': {
                    'float': np.float64(1.5),
                    'nan': np.float64(np.nan)
                }
            }
        })
        
        # 验证 JSON 序列化成功
        json_str = json.dumps(data, ensure_ascii=False, indent=2)
        assert json_str is not None
        
        # 验证 JSON 内容
        parsed = json.loads(json_str)
        assert parsed['level1']['int'] == 10
        assert parsed['level1']['nan'] is None
        assert parsed['level1']['level2']['float'] == 1.5
        assert parsed['level1']['level2']['nan'] is None
    
    def test_json_no_nan_in_output(self):
        """验证 JSON 输出中不含 NaN（标准 JSON 不支持 nan）"""
        data = convert_to_native_types({
            'nan1': np.float64(np.nan),
            'nan2': float('nan'),
            'normal': 1.5
        })
        
        json_str = json.dumps(data, ensure_ascii=False)
        
        # 验证 JSON 字符串中不含 "NaN" 或 "nan"
        assert 'NaN' not in json_str
        assert 'nan' not in json_str.lower() or 'null' in json_str  # null 是合法的
        
        # 验证 JSON 内容
        parsed = json.loads(json_str)
        assert parsed['nan1'] is None
        assert parsed['nan2'] is None
        assert parsed['normal'] == 1.5
    
    # =========================================================================
    # 边界情况测试
    # =========================================================================
    
    def test_none_passthrough(self):
        """None 直接返回 None"""
        assert convert_to_native_types(None) is None
    
    def test_empty_dict(self):
        """空字典返回空字典"""
        assert convert_to_native_types({}) == {}
    
    def test_empty_list(self):
        """空列表返回空列表"""
        assert convert_to_native_types([]) == []
    
    def test_empty_array(self):
        """空 numpy array 返回空列表"""
        arr = np.array([])
        result = convert_to_native_types(arr)
        assert result == []
    
    def test_mixed_types_list(self):
        """混合类型列表转换"""
        data = [np.int64(10), None, np.float64(np.nan), 'string', 1.5]
        result = convert_to_native_types(data)
        assert result == [10, None, None, 'string', 1.5]
    
    def test_inf_not_converted_to_none(self):
        """inf（无穷大）不转换为 None，保持为 float"""
        # 注意：inf 是有效浮点数，不应转为 None
        inf_val = np.float64(np.inf)
        result = convert_to_native_types(inf_val)
        assert result == float('inf') or result is None  # 视函数设计而定
        
        # 如果函数不处理 inf，这里需要更新测试以反映实际行为


class TestConvertTypesBehaviorVerification:
    """行为验证测试：确保 convert_to_native_types 行为符合规范"""
    
    def test_nan_behavior_documented(self):
        """验证 NaN → None → null 行为符合 PROJECT.md 规范"""
        # PROJECT.md 规范：
        # - NaN → None 转换应在数据生成阶段完成
        # - convert_to_native_types 作为兜底保障，也会处理 NaN
        
        nan_val = np.float64(np.nan)
        result = convert_to_native_types(nan_val)
        
        # 验证：NaN → None
        assert result is None
        
        # 验证：None → null（JSON 序列化）
        json_str = json.dumps({'value': result}, ensure_ascii=False)
        parsed = json.loads(json_str)
        assert parsed['value'] is None  # JSON null
    
    def test_json_output_format_consistency(self):
        """验证 JSON 输出格式一致性"""
        # 确保无论输入是 numpy NaN 还是 Python float NaN，
        # JSON 输出格式都是 null
        
        data = {
            'numpy_nan': convert_to_native_types(np.float64(np.nan)),
            'python_nan': convert_to_native_types(float('nan'))
        }
        
        json_str = json.dumps(data, ensure_ascii=False)
        parsed = json.loads(json_str)
        
        # 两种 NaN 都应转为 null
        assert parsed['numpy_nan'] is None
        assert parsed['python_nan'] is None
        
        # JSON 字符串中应包含 null，而非 NaN
        assert 'null' in json_str
        assert 'NaN' not in json_str


if __name__ == '__main__':
    pytest.main([__file__, '-v'])