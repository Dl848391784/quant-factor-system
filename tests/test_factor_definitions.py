#!/usr/bin/env python3
"""factor_definitions.py 单元测试

测试因子定义模块的功能：
1. FACTOR_DEFINITIONS 字典完整性
2. get_factor_definition() 函数
3. get_all_factor_names() 函数
4. __all__ 导出正确性

版本历史：
- v1.0 (2026-06-02): 初始版本，覆盖模块导出和辅助函数
"""

import pytest
from factor_definitions import (
    FACTOR_DEFINITIONS,
    __all__,
    __author__,
    __version__,
    get_all_factor_names,
    get_factor_definition,
)


class TestModuleConstants:
    """模块常量测试"""

    def test_version_defined(self):
        """验证版本常量存在"""
        assert __version__ == "1.0"

    def test_author_defined(self):
        """验证作者常量存在"""
        assert __author__ == "云瑶"

    def test_all_export_correct(self):
        """验证 __all__ 导出列表正确"""
        expected = [
            "FACTOR_DEFINITIONS",
            "get_factor_definition",
            "get_all_factor_names",
        ]
        assert sorted(__all__) == sorted(expected)


class TestFactorDefinitionsDict:
    """因子定义字典测试"""

    def test_dict_not_empty(self):
        """验证字典不为空"""
        assert len(FACTOR_DEFINITIONS) > 0

    def test_dict_has_14_factors(self):
        """验证定义了 14 个因子"""
        assert len(FACTOR_DEFINITIONS) == 14

    def test_basic_factors_present(self):
        """验证基础因子存在"""
        basic_factors = [
            "rsi",
            "volume_ratio",
            "kdj_j",
            "bollinger_pb",
            "turnover_surge",
            "amplitude",
            "price_position",
            "return_3d",
            "return_5d",
            "overnight_ret",
        ]
        for factor in basic_factors:
            assert factor in FACTOR_DEFINITIONS
            assert len(FACTOR_DEFINITIONS[factor]) > 0

    def test_tail_factors_present(self):
        """验证尾盘因子存在"""
        tail_factors = [
            "tail_price_position",
            "tail_price_slope",
            "tail_price_volume_intensity",
            "tail_volume_acceleration",
        ]
        for factor in tail_factors:
            assert factor in FACTOR_DEFINITIONS
            assert len(FACTOR_DEFINITIONS[factor]) > 0

    def test_definitions_not_empty_strings(self):
        """验证所有定义不是空字符串"""
        for factor, definition in FACTOR_DEFINITIONS.items():
            assert definition != "", f"因子 {factor} 定义为空字符串"

    def test_definitions_contain_formula_or_meaning(self):
        """验证定义包含公式或含义"""
        # 每个定义至少 10 字符（因子名 + 基本描述）
        for factor, definition in FACTOR_DEFINITIONS.items():
            assert len(definition) >= 10, f"因子 {factor} 定义过短: {definition}"


class TestGetFactorDefinition:
    """get_factor_definition() 函数测试"""

    def test_get_existing_factor(self):
        """测试获取存在的因子定义"""
        result = get_factor_definition("rsi")
        assert result == "RSI(6日): 相对强弱指标, 公式: RSI=100-100/(1+RS)"

    def test_get_another_existing_factor(self):
        """测试获取另一个存在的因子定义"""
        result = get_factor_definition("amplitude")
        assert "振幅" in result
        assert "(high-low)/close" in result

    def test_get_nonexistent_factor_default_empty(self):
        """测试获取不存在的因子（默认返回空字符串）"""
        result = get_factor_definition("nonexistent_factor")
        assert result == ""

    def test_get_nonexistent_factor_custom_default(self):
        """测试获取不存在的因子（自定义默认值）"""
        result = get_factor_definition("unknown", default="未知因子")
        assert result == "未知因子"

    def test_get_with_empty_default_param(self):
        """测试显式传入空默认值"""
        result = get_factor_definition("rsi", default="")
        assert result == "RSI(6日): 相对强弱指标, 公式: RSI=100-100/(1+RS)"

    def test_get_returns_string_type(self):
        """测试返回值类型为字符串"""
        result = get_factor_definition("rsi")
        assert isinstance(result, str)


class TestGetAllFactorNames:
    """get_all_factor_names() 函数测试"""

    def test_returns_list(self):
        """测试返回值类型为列表"""
        result = get_all_factor_names()
        assert isinstance(result, list)

    def test_returns_14_names(self):
        """测试返回 14 个因子名称"""
        result = get_all_factor_names()
        assert len(result) == 14

    def test_returns_sorted_list(self):
        """测试返回列表已排序"""
        result = get_all_factor_names()
        assert result == sorted(result)

    def test_contains_all_expected_names(self):
        """测试包含所有预期因子名称"""
        result = get_all_factor_names()
        expected = [
            "amplitude",
            "bollinger_pb",
            "kdj_j",
            "overnight_ret",
            "price_position",
            "return_3d",
            "return_5d",
            "rsi",
            "tail_price_position",
            "tail_price_slope",
            "tail_price_volume_intensity",
            "tail_volume_acceleration",
            "turnover_surge",
            "volume_ratio",
        ]
        assert result == expected

    def test_first_element_is_amplitude(self):
        """测试第一个元素是 amplitude（字典序）"""
        result = get_all_factor_names()
        assert result[0] == "amplitude"

    def test_last_element_is_volume_ratio(self):
        """测试最后一个元素是 volume_ratio（字典序）"""
        result = get_all_factor_names()
        assert result[-1] == "volume_ratio"
