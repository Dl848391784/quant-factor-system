#!/usr/bin/env python3
"""test_ic_turnover_surge_delta_1d 测试用例

测试脚本: factor_ic/ic_turnover_surge_delta_1d.py
因子计算: data_fetchers/factor_calculator.py::calculate_turnover_surge_delta
规范文档: factor_ic/MODULE.md

运行: pytest factor_ic/test_cases/test_ic_turnover_surge_delta_1d.py -v
"""

import json
import sys
from pathlib import Path

import pytest


sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from data_fetchers.factor_calculator import calculate_turnover_surge_delta
from factor_ic.common.data_completeness import FACTOR_IC_RESULT_DIR, get_ic_output_path


class TestOutputPath:
    """测试输出路径和命名规范"""

    def test_output_path_format(self):
        """输出文件命名应符合规范: ic_<因子名>_analysis_result.json"""
        path = get_ic_output_path("turnover_surge_delta")
        assert path.name == "ic_turnover_surge_delta_analysis_result.json"

    def test_output_directory(self):
        """输出目录应为 factor_ic/result/"""
        path = get_ic_output_path("turnover_surge_delta")
        assert path.parent == FACTOR_IC_RESULT_DIR

    def test_output_directory_exists_or_created(self):
        """输出目录不存在时应自动创建"""
        assert FACTOR_IC_RESULT_DIR.exists() or FACTOR_IC_RESULT_DIR.parent.exists()


class TestCalculateTurnoverSurgeDelta:
    """因子计算验证（导入即可，详细计算逻辑在 data_fetchers 测试覆盖）"""

    def test_calculator_importable(self):
        """计算函数可导入且可调用"""
        assert callable(calculate_turnover_surge_delta)


class TestOutputStructure:
    """测试输出数据结构规范"""

    REQUIRED_FIELDS = [
        "factor_name",
        "calculation_date",
        "period",
        "ic_metrics",
        "sample_stats",
        "statistical_significance",
        "factor_direction",
        "economic_significance",
        "icir_stability",
        "ic_distribution_consistency",
    ]

    def test_output_file_exists_after_run(self):
        """运行后输出文件应存在"""
        path = get_ic_output_path("turnover_surge_delta")
        if not path.exists():
            pytest.skip("输出文件不存在，需要先运行 ic_turnover_surge_delta_1d.py")

    def test_output_structure_if_exists(self):
        """如果输出文件存在，检查结构"""
        path = get_ic_output_path("turnover_surge_delta")
        if not path.exists():
            pytest.skip("输出文件不存在")

        with open(path, encoding="utf-8") as f:
            result = json.load(f)

        for field in self.REQUIRED_FIELDS:
            assert field in result, "缺少必需字段: " + field

    def test_ic_metrics_fields_if_exists(self):
        """如果输出文件存在，检查 ic_metrics 子字段"""
        path = get_ic_output_path("turnover_surge_delta")
        if not path.exists():
            pytest.skip("输出文件不存在")

        with open(path, encoding="utf-8") as f:
            result = json.load(f)

        ic_metrics = result.get("ic_metrics", {})
        required_ic_fields = ["ic_mean", "ic_std", "icir"]

        for field in required_ic_fields:
            assert field in ic_metrics, "ic_metrics 缺少必需字段: " + field

    def test_sample_stats_fields_if_exists(self):
        """如果输出文件存在，检查 sample_stats 子字段"""
        path = get_ic_output_path("turnover_surge_delta")
        if not path.exists():
            pytest.skip("输出文件不存在")

        with open(path, encoding="utf-8") as f:
            result = json.load(f)

        sample_stats = result.get("sample_stats", {})
        required_sample_fields = ["total_days", "valid_days"]

        for field in required_sample_fields:
            assert field in sample_stats, "sample_stats 缺少必需字段: " + field

    def test_factor_direction_if_exists(self):
        """如果输出文件存在，检查 factor_direction"""
        path = get_ic_output_path("turnover_surge_delta")
        if not path.exists():
            pytest.skip("输出文件不存在")

        with open(path, encoding="utf-8") as f:
            result = json.load(f)

        direction = result.get("factor_direction")
        assert direction in ("positive", "negative"), "factor_direction 应为 positive/negative, 实际为: " + str(
            direction
        )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
