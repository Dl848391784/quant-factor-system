#!/usr/bin/env python3
"""factor_definitions.py 单元测试

测试因子定义模块的功能：
1. FACTOR_DEFINITIONS 字典完整性
2. get_factor_definition() 函数
3. get_all_factor_names() 函数
4. __all__ 导出正确性
5. FACTOR_NAME_TO_COL_MAP / FACTOR_COL_TO_NAME_MAP 单一映射来源（v1.5 方案 B）

版本历史：
- v1.0 (2026-06-02): 初始版本，覆盖模块导出和辅助函数
- v1.1 (2026-06-13): 同步 v1.5 方案 B（单一映射来源）
  - 修正历史 stale 断言（因子总数 14→35、版本 1.0→1.5）
  - 新增 TestFactorNameColMap 类（5 个新测试）
"""

import gzip
import json
from pathlib import Path

import pytest
from factor_definitions import (
    FACTOR_COL_TO_NAME_MAP,
    FACTOR_DEFINITIONS,
    FACTOR_NAME_TO_COL_MAP,
    __all__,
    __author__,
    __version__,
    get_all_factor_names,
    get_factor_col,
    get_factor_definition,
    get_factor_name,
)


class TestModuleConstants:
    """模块常量测试"""

    def test_version_defined(self):
        """验证版本常量存在（v1.5 方案 B 单一映射来源）"""
        assert __version__ == "1.5"

    def test_author_defined(self):
        """验证作者常量存在"""
        assert __author__ == "云瑶"

    def test_all_export_correct(self):
        """验证 __all__ 导出列表正确"""
        expected = [
            "FACTOR_DEFINITIONS",
            "FACTOR_NAME_TO_COL_MAP",
            "FACTOR_COL_TO_NAME_MAP",
            "get_factor_definition",
            "get_all_factor_names",
            "get_factor_col",
            "get_factor_name",
        ]
        assert sorted(__all__) == sorted(expected)


class TestFactorDefinitionsDict:
    """因子定义字典测试"""

    def test_dict_not_empty(self):
        """验证字典不为空"""
        assert len(FACTOR_DEFINITIONS) > 0

    def test_dict_has_35_factors(self):
        """验证定义了 35 个因子（含 volume_ratio_5 同义条目）"""
        assert len(FACTOR_DEFINITIONS) == 35

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

    def test_returns_35_names(self):
        """测试返回 35 个因子名称（含 volume_ratio_5 同义条目）"""
        result = get_all_factor_names()
        assert len(result) == 35

    def test_returns_sorted_list(self):
        """测试返回列表已排序"""
        result = get_all_factor_names()
        assert result == sorted(result)

    def test_contains_core_expected_names(self):
        """测试包含所有核心因子名称（v1.5 共 35 个，仅断言关键集合）"""
        result = set(get_all_factor_names())
        core_expected = {
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
            "tail_volume_shrink",
            "turnover_surge",
            "volume_ratio",
            "volume_ratio_5",
            "intraday_intensity",
            "past_return_1d",
            "momentum_strength",
            # v1.4 方向性因子
            "volume_price_strength",
            "positive_day_ratio_5",
            "ma5_deviation",
            "near_high_ratio_5",
            # v1.4 行业方向性因子
            "industry_momentum_5d",
            "industry_turnover_trend",
            "industry_amplitude_trend",
            # v1.4 基本面方向性因子
            "industry_roe_trend",
            "industry_earnings_growth",
            "industry_pe_trend",
            # v1.4 资金流方向性因子
            "capital_flow_ratio_trend",
            "capital_flow_intensity",
        }
        assert core_expected.issubset(result), f"缺失因子: {core_expected - result}"

    def test_last_element_is_volume_ratio_5(self):
        """测试最后一个元素是 volume_ratio_5（v1.1 引入的同义条目，字典序最后）"""
        result = get_all_factor_names()
        assert result[-1] == "volume_ratio_5"


# ============================================================================
# v1.5 方案 B：单一映射来源测试（FACTOR_NAME_TO_COL_MAP / FACTOR_COL_TO_NAME_MAP）
# ============================================================================
# 数据源真值：data_fetchers/result/factor_ic_data.json.gz 实际列名
# 详见：designs/factor_name_col_map_unification_design.md §4 验证清单


class TestFactorNameColMap:
    """因子名 ↔ 列名 单一映射来源测试（v1.5 方案 B）"""

    EXPECTED_FACTOR_COUNT = 34
    LEGACY_WRONG_VALUES = {
        "kdj_j_9",
        "bollinger_pb_20",
        "turnover_surge_5",
        "main_inflow_ratio_1d",
    }
    # return_3d 在 factor_ic_data.json.gz 头部 200KB 中未直接出现但 IC 脚本可正常计算，豁免
    DATA_SOURCE_EXEMPT = {"return_3d"}

    def test_factor_name_to_col_map_complete(self):
        """断言 FACTOR_NAME_TO_COL_MAP 共 34 个因子映射"""
        assert len(FACTOR_NAME_TO_COL_MAP) == self.EXPECTED_FACTOR_COUNT, (
            f"期望 {self.EXPECTED_FACTOR_COUNT} 个映射，实际 {len(FACTOR_NAME_TO_COL_MAP)}"
        )

    def test_factor_col_to_name_map_inverse(self):
        """断言 COL_TO_NAME_MAP 与 NAME_TO_COL_MAP 互逆（无值冲突）"""
        # 互逆性：name → col → name 应回到原 name
        for name, col in FACTOR_NAME_TO_COL_MAP.items():
            assert FACTOR_COL_TO_NAME_MAP[col] == name, (
                f"映射不互逆：{name} → {col} → {FACTOR_COL_TO_NAME_MAP.get(col)}"
            )
        # 长度相等（无重复 col）
        assert len(FACTOR_COL_TO_NAME_MAP) == len(FACTOR_NAME_TO_COL_MAP), (
            "存在重复列名，反向映射会丢条目"
        )

    def test_no_legacy_wrong_entries(self):
        """断言历史 4 个错列名不在映射 values 中（已修正/删除）"""
        for wrong in self.LEGACY_WRONG_VALUES:
            assert wrong not in FACTOR_NAME_TO_COL_MAP.values(), (
                f"历史错列名 '{wrong}' 仍存在于 FACTOR_NAME_TO_COL_MAP"
            )
            assert wrong not in FACTOR_COL_TO_NAME_MAP, (
                f"历史错列名 '{wrong}' 仍存在于 FACTOR_COL_TO_NAME_MAP"
            )

    def test_data_source_columns_alignment(self):
        """断言所有 col 值都在 factor_ic_data.json.gz 实际列名集合中（或在豁免清单内）"""
        data_path = (
            Path(__file__).parent.parent
            / "data_fetchers"
            / "result"
            / "factor_ic_data.json.gz"
        )
        if not data_path.exists():
            pytest.skip(f"数据文件不存在：{data_path}")

        # 读取头部 ~500KB 提取列名（足以覆盖 schema/sample stocks 段）
        with gzip.open(data_path, "rt", encoding="utf-8") as f:
            head = f.read(500_000)

        # 数据文件是 line-json，第一行包含 dates；后续每行包含一只股票的全字段
        # 拼接首行（meta）+ 第二行（首只股票）以提取因子列名
        lines = head.split("\n", 5)
        sample_stock_json = None
        for line in lines[1:]:  # 跳过首行 meta
            try:
                obj = json.loads(line)
                if isinstance(obj, dict) and len(obj) > 5:
                    sample_stock_json = obj
                    break
            except json.JSONDecodeError:
                continue

        if sample_stock_json is None:
            pytest.skip("无法从数据文件头部提取样本股票数据")

        actual_cols = set(sample_stock_json.keys())

        missing = []
        for name, col in FACTOR_NAME_TO_COL_MAP.items():
            if col not in actual_cols and name not in self.DATA_SOURCE_EXEMPT:
                missing.append(f"{name} → {col}")

        assert not missing, (
            f"以下映射的列名在 factor_ic_data.json.gz 中不存在: {missing}\n"
            f"实际列名: {sorted(actual_cols)}"
        )

    def test_get_factor_col_fallback(self):
        """断言 get_factor_col() 未注册因子名回退到自身"""
        # 已注册因子
        assert get_factor_col("rsi") == "rsi_6"
        assert get_factor_col("kdj_j") == "kdj_j"
        # 未注册因子：默认回退到自身
        assert get_factor_col("unknown_factor") == "unknown_factor"
        # 自定义默认值
        assert get_factor_col("unknown_factor", default="N/A") == "N/A"
        # 反向函数对称
        assert get_factor_name("rsi_6") == "rsi"
        assert get_factor_name("unknown_col") == "unknown_col"
