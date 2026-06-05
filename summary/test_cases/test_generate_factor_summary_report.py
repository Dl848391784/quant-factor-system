#!/usr/bin/env python3
"""
generate_factor_summary_report.py 测试用例

测试范围：
- 输入验证：数据文件存在性、数据格式正确性
- 输出验证：报告格式正确性、字段完整性
- 边界条件：无数据情况、部分数据缺失
- 异常处理：文件读取失败、JSON 解析错误
- 数据完整性检查：新鲜度检查、日期校验（v1.9 新增）

运行方法：
    pytest summary/test_cases/test_generate_factor_summary_report.py -v

版本历史：
    v1.0: 基础测试用例
    v1.1 (2026-06-02): 新增数据完整性检查测试用例（9个）
"""

import gzip
import json
import logging
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# 导入被测试模块
from summary.generate_factor_summary_report import (
    __version__,
    _extract_date_from_json_content,
    _generate_data_check_section,
    _get_nested_field,
    check_data_freshness,
    check_derived_data_freshness,
    format_float,
    format_percentage,
    format_weights,
    get_date_str,
    get_expected_t_minus_1,
    get_monotonicity_symbol,
    get_weight_method_display,
    load_json_file,
    merge_factor_data,
    setup_logger,
)


class TestVersion:
    """版本常量测试"""

    def test_version_defined(self):
        """验证版本常量存在"""
        assert __version__ == "2.9"


class TestHelperFunctions:
    """辅助函数测试"""

    def test_get_date_str_with_input(self):
        """测试指定日期"""
        result = get_date_str("2026-05-28")
        assert result == "2026-05-28"

    def test_get_date_str_without_input(self):
        """测试默认日期（当天）"""
        from datetime import datetime

        expected = datetime.now().strftime("%Y-%m-%d")
        result = get_date_str()
        assert result == expected

    def test_get_expected_t_minus_1(self):
        """测试 T-1 日期计算"""
        # 2026-06-02 的前一天是 2026-06-01
        result = get_expected_t_minus_1("2026-06-02")
        assert result == "2026-06-01"

        # 跨月测试：2026-06-01 的前一天是 2026-05-31
        result = get_expected_t_minus_1("2026-06-01")
        assert result == "2026-05-31"

    def test_get_monotonicity_symbol_good(self):
        """测试良好单调性符号"""
        assert get_monotonicity_symbol("good") == "✓良好"

    def test_get_monotonicity_symbol_moderate(self):
        """测试一般单调性符号"""
        assert get_monotonicity_symbol("moderate") == "△一般"

    def test_get_monotonicity_symbol_poor(self):
        """测试较差单调性符号"""
        assert get_monotonicity_symbol("poor") == "✗较差"

    def test_get_monotonicity_symbol_unknown(self):
        """测试未知单调性符号"""
        assert get_monotonicity_symbol("unknown") == "?未知"

    def test_get_monotonicity_symbol_invalid(self):
        """测试无效输入的默认返回"""
        assert get_monotonicity_symbol("invalid") == "?未知"

    def test_get_weight_method_display_ic_weight(self):
        """测试 IC 加权显示名"""
        assert get_weight_method_display("ic_weight") == "IC加权"

    def test_get_weight_method_display_icir_weight(self):
        """测试 ICIR 加权显示名"""
        assert get_weight_method_display("icir_weight") == "ICIR加权"

    def test_get_weight_method_display_rolling_icir_weight(self):
        """测试 Rolling ICIR 加权显示名"""
        assert get_weight_method_display("rolling_icir_weight") == "Rolling ICIR加权"

    def test_get_weight_method_display_equal_weight(self):
        """测试等权显示名"""
        assert get_weight_method_display("equal_weight") == "等权"

    def test_get_weight_method_display_invalid(self):
        """测试无效输入返回原值"""
        assert get_weight_method_display("invalid") == "invalid"

    def test_format_weights(self):
        """测试权重格式化"""
        weights = {"turnover_surge": 0.6, "bollinger_pb": 0.4}
        result = format_weights(weights)
        assert "ts:60%" in result
        assert "bp:40%" in result

    def test_format_percentage_default(self):
        """测试百分比格式化（默认精度）"""
        result = format_percentage(15.555)
        assert result == "15.55%"  # Python 使用银行家舍入法

    def test_format_percentage_custom_decimals(self):
        """测试百分比格式化（自定义精度）"""
        result = format_percentage(15.555, decimals=1)
        assert result == "15.6%"

    def test_format_float_default(self):
        """测试浮点数格式化（默认精度）"""
        result = format_float(0.12345)
        assert result == "0.1235"

    def test_format_float_custom_decimals(self):
        """测试浮点数格式化（自定义精度）"""
        result = format_float(0.12345, decimals=2)
        assert result == "0.12"


class TestNestedFieldExtraction:
    """嵌套字段提取测试（v1.9 新增）"""

    def test_get_nested_field_single_level(self):
        """测试单层字段提取"""
        data = {"dates": ["2026-05-30", "2026-05-31"]}
        result = _get_nested_field(data, "dates")
        # dates 是列表，不是字符串，返回 None
        assert result is None

    def test_get_nested_field_two_levels(self):
        """测试两层嵌套字段提取"""
        data = {"meta": {"date_range": {"end": "2026-05-31"}}}
        result = _get_nested_field(data, "meta.date_range.end")
        assert result == "2026-05-31"

    def test_get_nested_field_missing_key(self):
        """测试缺失字段"""
        data = {"meta": {}}
        result = _get_nested_field(data, "meta.date_range.end")
        assert result is None

    def test_get_nested_field_non_dict_value(self):
        """测试中间值为非字典"""
        data = {"meta": "string_value"}
        result = _get_nested_field(data, "meta.date_range.end")
        assert result is None

    def test_extract_date_from_json_content_end_field(self):
        """测试从 JSON 内容提取 end 字段"""
        content = '{"meta": {"date_range": {"start": "2026-05-01", "end": "2026-05-31"}}}'
        result = _extract_date_from_json_content(content, "meta.date_range.end")
        assert result == "2026-05-31"

    def test_extract_date_from_json_content_no_match(self):
        """测试无匹配日期"""
        content = '{"other": "data"}'
        result = _extract_date_from_json_content(content, "meta.date_range.end")
        assert result is None


class TestDataFreshnessCheck:
    """数据新鲜度检查测试（v1.9 新增）"""

    def test_check_data_freshness_file_missing(self):
        """测试文件不存在时返回 error 状态"""
        logger = MagicMock()

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            with (
                patch("summary.generate_factor_summary_report.PROJECT_ROOT", root),
                patch(
                    "summary.generate_factor_summary_report.DATA_CHECK_SOURCES",
                    {
                        "test_source": {
                            "path": "nonexistent/file.json.gz",
                            "description": "测试数据",
                            "date_field": "dates",
                            "format": "line_json",
                            "is_gzip": True,
                        }
                    },
                ),
            ):
                results = check_data_freshness("2026-06-02", logger)

                assert len(results) == 1
                assert results[0]["status"] == "error"
                assert results[0]["status_symbol"] == "✗缺失"

    def test_check_data_freshness_line_json_date_match(self):
        """测试 line_json 格式日期匹配"""
        logger = MagicMock()

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "data_fetchers" / "result").mkdir(parents=True)

            # 创建测试数据（line_json 格式）
            test_data = {"dates": ["2026-05-30", "2026-05-31", "2026-06-01"]}
            file_path = root / "data_fetchers" / "result" / "test_data.json.gz"
            with gzip.open(file_path, "wt", encoding="utf-8") as f:
                f.write(json.dumps(test_data) + "\n")

            with (
                patch("summary.generate_factor_summary_report.PROJECT_ROOT", root),
                patch(
                    "summary.generate_factor_summary_report.DATA_CHECK_SOURCES",
                    {
                        "test_source": {
                            "path": "data_fetchers/result/test_data.json.gz",
                            "description": "测试数据",
                            "date_field": "dates",
                            "format": "line_json",
                            "is_gzip": True,
                        }
                    },
                ),
            ):
                # 期望日期为 2026-06-01（T-1）
                results = check_data_freshness("2026-06-02", logger)

                assert len(results) == 1
                assert results[0]["actual_date"] == "2026-06-01"
                assert results[0]["status"] == "ok"
                assert results[0]["status_symbol"] == "✓正常"

    def test_check_data_freshness_date_mismatch(self):
        """测试日期不匹配时返回 warning 状态"""
        logger = MagicMock()

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "data_fetchers" / "result").mkdir(parents=True)

            # 创建测试数据（日期为 2026-05-30，早于期望的 2026-06-01）
            test_data = {"dates": ["2026-05-28", "2026-05-29", "2026-05-30"]}
            file_path = root / "data_fetchers" / "result" / "test_data.json.gz"
            with gzip.open(file_path, "wt", encoding="utf-8") as f:
                f.write(json.dumps(test_data) + "\n")

            with (
                patch("summary.generate_factor_summary_report.PROJECT_ROOT", root),
                patch(
                    "summary.generate_factor_summary_report.DATA_CHECK_SOURCES",
                    {
                        "test_source": {
                            "path": "data_fetchers/result/test_data.json.gz",
                            "description": "测试数据",
                            "date_field": "dates",
                            "format": "line_json",
                            "is_gzip": True,
                        }
                    },
                ),
            ):
                results = check_data_freshness("2026-06-02", logger)

                assert len(results) == 1
                assert results[0]["actual_date"] == "2026-05-30"
                assert results[0]["status"] == "warning"
                assert results[0]["status_symbol"] == "△延迟"

    def test_check_data_freshness_full_json_format(self):
        """测试 full_json 格式日期提取"""
        logger = MagicMock()

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "data_fetchers" / "result").mkdir(parents=True)

            # 创建测试数据（full_json 格式）
            test_data = {"meta": {"date_range": {"start": "2026-05-01", "end": "2026-06-01"}}}
            file_path = root / "data_fetchers" / "result" / "test_data.json.gz"
            with gzip.open(file_path, "wt", encoding="utf-8") as f:
                f.write(json.dumps(test_data))

            with (
                patch("summary.generate_factor_summary_report.PROJECT_ROOT", root),
                patch(
                    "summary.generate_factor_summary_report.DATA_CHECK_SOURCES",
                    {
                        "test_source": {
                            "path": "data_fetchers/result/test_data.json.gz",
                            "description": "测试数据",
                            "date_field": "meta.date_range.end",
                            "format": "full_json",
                            "is_gzip": True,
                        }
                    },
                ),
            ):
                results = check_data_freshness("2026-06-02", logger)

                assert len(results) == 1
                assert results[0]["actual_date"] == "2026-06-01"
                assert results[0]["status"] == "ok"


class TestDerivedDataFreshnessCheck:
    """衍生数据新鲜度检查测试（v1.9 新增）"""

    def test_check_derived_data_freshness_empty(self):
        """测试衍生数据为空"""
        logger = MagicMock()

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "factor_ic" / "result").mkdir(parents=True)
            (root / "backtest" / "result").mkdir(parents=True)
            (root / "comprehensive_factor" / "result").mkdir(parents=True)

            with (
                patch("summary.generate_factor_summary_report.PROJECT_ROOT", root),
                patch(
                    "summary.generate_factor_summary_report.DATA_PATHS",
                    {
                        "ic_result": "factor_ic/result",
                        "backtest_result": "backtest/result",
                        "comprehensive_result": "comprehensive_factor/result",
                    },
                ),
            ):
                results = check_derived_data_freshness("2026-06-02", logger)

                assert len(results) == 3
                # IC 结果为空
                assert results[0]["source"] == "ic_results"
                assert results[0]["status"] == "error"
                # 回测结果为空
                assert results[1]["source"] == "backtest_results"
                assert results[1]["status"] == "error"
                # 综合因子结果为空
                assert results[2]["source"] == "composite_results"
                assert results[2]["status"] == "error"

    def test_check_derived_data_freshness_with_files(self):
        """测试衍生数据存在"""
        logger = MagicMock()

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "factor_ic" / "result").mkdir(parents=True)
            (root / "backtest" / "result").mkdir(parents=True)
            (root / "comprehensive_factor" / "result").mkdir(parents=True)

            # 创建 IC 结果文件（使用顶层 dates 数组格式）
            ic_data = {"dates": ["2026-06-01"], "ic_values": []}
            ic_file = root / "factor_ic" / "result" / "ic_test_1d_analysis_result.json"
            ic_file.write_text(json.dumps(ic_data))

            # 创建回测结果文件
            bt_file = root / "backtest" / "result" / "test_layered_backtest.json"
            bt_file.write_text("{}")

            # 创建综合因子结果文件
            comp_file = root / "comprehensive_factor" / "result" / "composite_icir_weight_1d.json"
            comp_file.write_text("{}")

            with (
                patch("summary.generate_factor_summary_report.PROJECT_ROOT", root),
                patch(
                    "summary.generate_factor_summary_report.DATA_PATHS",
                    {
                        "ic_result": "factor_ic/result",
                        "backtest_result": "backtest/result",
                        "comprehensive_result": "comprehensive_factor/result",
                    },
                ),
            ):
                results = check_derived_data_freshness("2026-06-02", logger)

                assert len(results) == 3
                # IC 结果存在且日期匹配
                assert results[0]["source"] == "ic_results"
                assert results[0]["actual_date"] == "2026-06-01"
                assert results[0]["status"] == "ok"
                # 回测结果存在
                assert results[1]["source"] == "backtest_results"
                assert results[1]["status"] == "ok"
                # 综合因子结果存在
                assert results[2]["source"] == "composite_results"
                assert results[2]["status"] == "ok"


class TestDataCheckSectionGeneration:
    """数据检查报告生成测试（v1.9 新增）"""

    def test_generate_data_check_section_all_ok(self):
        """测试所有数据正常"""
        data_results = [
            {
                "source": "test1",
                "description": "测试数据1",
                "expected_date": "2026-06-01",
                "actual_date": "2026-06-01",
                "status": "ok",
                "status_symbol": "✓正常",
            },
        ]
        derived_results = [
            {
                "source": "ic_results",
                "description": "IC结果",
                "expected_date": "2026-06-01",
                "actual_date": "-",
                "file_count": 5,
                "status": "ok",
                "status_symbol": "✓正常(5因子)",
            },
        ]

        lines = _generate_data_check_section(data_results, derived_results)

        assert "零、数据完整性检查" in "".join(lines)
        assert "期望数据日期: 2026-06-01 (T-1)" in "".join(lines)
        assert "汇总: ✓ 所有数据源已更新至 T-1" in "".join(lines)

    def test_generate_data_check_section_with_errors(self):
        """测试存在错误"""
        data_results = [
            {
                "source": "test1",
                "description": "测试数据1",
                "expected_date": "2026-06-01",
                "actual_date": "unknown",
                "status": "error",
                "status_symbol": "✗缺失",
            },
        ]
        derived_results = [
            {
                "source": "ic_results",
                "description": "IC结果",
                "expected_date": "2026-06-01",
                "actual_date": "-",
                "file_count": 0,
                "status": "error",
                "status_symbol": "✗缺失",
            },
        ]

        lines = _generate_data_check_section(data_results, derived_results)

        assert "汇总: ✗ 存在数据缺失或读取失败" in "".join(lines)

    def test_generate_data_check_section_with_warnings(self):
        """测试存在警告"""
        data_results = [
            {
                "source": "test1",
                "description": "测试数据1",
                "expected_date": "2026-06-01",
                "actual_date": "2026-05-30",
                "status": "warning",
                "status_symbol": "△延迟",
            },
        ]
        derived_results = [
            {
                "source": "ic_results",
                "description": "IC结果",
                "expected_date": "2026-06-01",
                "actual_date": "-",
                "file_count": 5,
                "status": "ok",
                "status_symbol": "✓正常(5因子)",
            },
        ]

        lines = _generate_data_check_section(data_results, derived_results)

        assert "汇总: △ 存在数据延迟" in "".join(lines)


class TestLoadJsonFile:
    """JSON 文件加载测试"""

    def test_load_json_file_success(self):
        """测试成功加载 JSON 文件"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump({"test": "data"}, f)
            f.flush()
            path = Path(f.name)

        logger = MagicMock()
        result = load_json_file(path, logger)

        assert result == {"test": "data"}
        path.unlink()

    def test_load_json_file_not_found(self):
        """测试文件不存在"""
        logger = MagicMock()
        result = load_json_file(Path("/nonexistent/file.json"), logger)

        assert result is None
        logger.debug.assert_called_once()

    def test_load_json_file_decode_error(self):
        """测试 JSON 解析错误"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            f.write("{invalid json}")
            f.flush()
            path = Path(f.name)

        logger = MagicMock()
        result = load_json_file(path, logger)

        assert result is None
        logger.warning.assert_called_once()
        path.unlink()


class TestMergeFactorData:
    """数据合并测试"""

    def test_merge_factor_data_success(self):
        """测试成功合并 IC 和回测数据"""
        ic_results = [
            {"factor_name": "rsi", "ic_mean": -0.045, "icir": 0.51},
            {"factor_name": "volume_ratio", "ic_mean": -0.019, "icir": 0.31},
        ]
        backtest_results = [
            {"factor_name": "rsi", "long_short_return_annual": 5.0},
            {"factor_name": "volume_ratio", "long_short_return_annual": 3.0},
        ]

        result = merge_factor_data(ic_results, backtest_results)

        assert len(result) == 2
        assert result[0]["factor_name"] == "rsi"
        assert result[0]["ic_mean"] == -0.045
        assert result[0]["long_short_return_annual"] == 5.0

    def test_merge_factor_data_missing_backtest(self):
        """测试回测数据缺失"""
        ic_results = [
            {"factor_name": "rsi", "ic_mean": -0.045},
        ]
        backtest_results = []  # 无回测数据

        result = merge_factor_data(ic_results, backtest_results)

        assert len(result) == 1
        assert result[0]["factor_name"] == "rsi"
        assert result[0]["ic_mean"] == -0.045
        # 无回测数据时，合并空字典


class TestSetupLogger:
    """日志配置测试"""

    def test_setup_logger_creates_logger(self):
        """测试创建 logger"""
        logger = setup_logger("test_logger")

        assert logger is not None
        assert logger.name == "test_logger"
        assert logger.level == logging.DEBUG


class TestReportStructure:
    """报告结构测试（需要 mock 数据文件）"""

    @pytest.fixture
    def mock_project_root(self):
        """创建临时项目目录结构"""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)

            # 创建目录结构
            (root / "factor_ic" / "result").mkdir(parents=True)
            (root / "backtest" / "result").mkdir(parents=True)
            (root / "comprehensive_factor" / "result").mkdir(parents=True)
            (root / "summary" / "result").mkdir(parents=True)
            (root / "summary" / "logs").mkdir(parents=True)
            (root / "data_fetchers" / "result").mkdir(parents=True)

            # 创建模拟 IC 结果
            ic_data = {
                "factor_name": "rsi_1d",
                "ic_metrics": {"ic_mean": -0.045, "icir": 0.51, "ic_std": 0.089},
                "sample_stats": {"valid_days": 498},
                "ic_series": [{"date": "2026-06-01"}],
            }
            with open(root / "factor_ic" / "result" / "ic_rsi_1d_analysis_result.json", "w") as f:
                json.dump(ic_data, f)

            # 创建模拟回测结果
            backtest_data = {
                "long_short": {"long_short_return_annual": 0.05, "long_short_sharpe": 0.5},
                "monotonicity": {"correlation": -0.3, "quality": "good"},
            }
            with open(root / "backtest" / "result" / "rsi_layered_backtest.json", "w") as f:
                json.dump(backtest_data, f)

            # 创建模拟综合因子结果
            comp_data = {
                "meta": {"weights": {"rsi": 1.0}, "factor_list": ["rsi"]},
                "backtest_result": {
                    "long_short": {"long_short_return_annual": 0.04, "long_short_sharpe": 0.4},
                    "monotonicity": {"correlation": -0.2, "quality": "moderate"},
                },
            }
            with open(root / "comprehensive_factor" / "result" / "composite_icir_weight_1d.json", "w") as f:
                json.dump(comp_data, f)

            yield root

    def test_report_generated(self, mock_project_root):
        """测试报告生成（mock 环境）"""
        # 此测试需要 patch PROJECT_ROOT
        with patch("summary.generate_factor_summary_report.PROJECT_ROOT", mock_project_root):
            from summary.generate_factor_summary_report import load_backtest_results, load_ic_results

            logger = setup_logger("test")

            ic_results = load_ic_results(logger)
            assert len(ic_results) >= 1
            assert ic_results[0]["factor_name"] == "rsi"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
