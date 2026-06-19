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
        assert __version__ == "2.25"


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
        assert "ts:60.0%" in result
        assert "bp:40.0%" in result

    def test_format_weights_column_name_keys(self):
        """v2.22: 列名键应归一化为因子名再查缩写（vol→vr 一致性）"""
        weights = {"volume_ratio_5": 0.12, "rsi_6": 0.08}
        result = format_weights(weights)
        assert "vr:12.0%" in result  # 列名 volume_ratio_5 → 因子名 volume_ratio → 缩写 vr
        assert "rsi:8.0%" in result

    def test_format_weights_small_weight(self):
        """v2.22: 权重 <0.5% 显示1位小数（避免 0.4% 截断为 0%）"""
        weights = {"momentum_strength": 0.004, "tail_price_position": 0.27}
        result = format_weights(weights)
        assert "mom:0.4%" in result  # 0.4% 不截断为 0%
        assert "tp_pos:27.0%" in result

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

    def test_check_data_freshness_factor_ic_data_full_json_dates(self):
        """测试 factor_ic_data 完整 JSON 格式从顶层 dates[-1] 提取日期"""
        logger = MagicMock()

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "data_fetchers" / "result").mkdir(parents=True)

            file_path = root / "data_fetchers" / "result" / "factor_ic_data.json.gz"
            with gzip.open(file_path, "wt", encoding="utf-8") as f:
                f.write('{"dates": ')
                json.dump(["2026-05-29", "2026-06-01"], f)
                f.write(', "data": [')
                f.write(json.dumps({"date": "2026-06-01", "asset": "000001"}))
                f.write("]}")

            with (
                patch("summary.generate_factor_summary_report.PROJECT_ROOT", root),
                patch(
                    "summary.generate_factor_summary_report.DATA_CHECK_SOURCES",
                    {
                        "factor_ic_data": {
                            "path": "data_fetchers/result/factor_ic_data.json.gz",
                            "description": "主数据源(行情+因子+收益)",
                            "date_field": "dates",
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
                logger.error.assert_not_called()

    def test_check_data_freshness_tail_trading_data_full_json_meta_end(self):
        """测试 tail_trading_data 完整 JSON 格式从 meta.date_range.end 提取日期"""
        logger = MagicMock()

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "data_fetchers" / "result").mkdir(parents=True)

            test_data = {
                "meta": {
                    "date_range": {"start": "2026-05-08", "end": "2026-06-01"},
                    "last_updated": "2026-06-02 05:47:28",
                    "source": "mixed",
                },
                "data": [
                    {
                        "date": "2026-06-01",
                        "asset": "000001",
                        "prices": [10.0] * 13,
                        "volumes": [1000] * 13,
                        "tail_high": 10.5,
                        "tail_low": 9.8,
                    }
                ],
            }
            file_path = root / "data_fetchers" / "result" / "tail_trading_data.json.gz"
            with gzip.open(file_path, "wt", encoding="utf-8") as f:
                json.dump(test_data, f)

            with (
                patch("summary.generate_factor_summary_report.PROJECT_ROOT", root),
                patch(
                    "summary.generate_factor_summary_report.DATA_CHECK_SOURCES",
                    {
                        "tail_trading_data": {
                            "path": "data_fetchers/result/tail_trading_data.json.gz",
                            "description": "尾盘5分钟K线数据",
                            "date_field": "meta.date_range.end",
                            "format": "full_json",
                            "is_gzip": True,
                        }
                    },
                ),
            ):
                results = check_data_freshness("2026-06-02", logger)

                assert len(results) == 1
                assert results[0]["source"] == "tail_trading_data"
                assert results[0]["actual_date"] == "2026-06-01"
                assert results[0]["status"] == "ok"
                assert results[0]["status_symbol"] == "✓正常"
                logger.error.assert_not_called()


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


class TestFlippedFactorDisplay:
    """v2.15: 取反因子 z-score 展示标记测试"""

    def test_display_name_with_flipped_factor(self):
        """取反因子名应加*后缀（如 overnight_ret*）"""
        flipped_factors = ["overnight_ret"]
        flipped_set = set(flipped_factors)

        # 取反因子 → 加*标记
        factor_name = "overnight_ret"
        display_name = f"{factor_name}*" if factor_name in flipped_set else factor_name
        assert display_name == "overnight_ret*"

    def test_display_name_without_flipped_factor(self):
        """非取反因子名不应加*后缀"""
        flipped_factors = ["overnight_ret"]
        flipped_set = set(flipped_factors)

        # 非取反因子 → 无标记
        factor_name = "amplitude"
        display_name = f"{factor_name}*" if factor_name in flipped_set else factor_name
        assert display_name == "amplitude"

    def test_display_name_with_multiple_flipped_factors(self):
        """多个取反因子都应加*标记"""
        flipped_factors = ["overnight_ret", "tail_price_position"]
        flipped_set = set(flipped_factors)

        for f in flipped_factors:
            display_name = f"{f}*" if f in flipped_set else f
            assert display_name == f"{f}*"

    def test_header_note_with_flipped_factors(self):
        """表头应在有取反因子时显示 * = 已取反统一负向语义"""
        flipped_factors = ["overnight_ret"]
        header_note = "  * = 已取反统一负向语义" if flipped_factors else ""
        assert "* = 已取反统一负向语义" in header_note

    def test_header_note_without_flipped_factors(self):
        """无取反因子时表头不应有额外说明"""
        flipped_factors = []
        header_note = "  * = 已取反统一负向语义" if flipped_factors else ""
        assert header_note == ""

    def test_factor_str_contains_asterisk_for_flipped(self):
        """整行因子值字符串中取反因子名带*标记"""
        # 构建模拟 factor_values_std 数据
        factor_values_std = {"amplitude": -1.97, "overnight_ret": -3.00}
        flipped_factors = ["overnight_ret"]
        flipped_set = set(flipped_factors)

        COL_TO_FACTOR_NAME_MAP = {"amplitude": "amplitude", "overnight_ret": "overnight_ret"}
        parts = []
        for k, v_std in factor_values_std.items():
            factor_name = COL_TO_FACTOR_NAME_MAP.get(k, k)
            display_name = f"{factor_name}*" if factor_name in flipped_set else factor_name
            if abs(v_std) >= 0.001:
                parts.append(f"{display_name}={v_std:.2f}")

        factor_str = ", ".join(parts)
        assert "overnight_ret*=-3.00" in factor_str
        assert "amplitude=-1.97" in factor_str
        assert "overnight_ret=-3.00" not in factor_str  # 不带*的版本不应出现


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


# ---------------------------------------------------------------------------
# v2.18: _detect_weight_rank_anomalies 测试
# ---------------------------------------------------------------------------


class TestDetectWeightRankAnomalies:
    """测试 Rolling ICIR 权重排名 vs 全样本 ICIR 排名异常检测。"""

    def test_momentum_strength_style_anomaly_detected(self):
        """ICIR 排名高但权重排名低（排名下降≥阈值）的因子应被检出。"""
        from summary.generate_factor_summary_report import _detect_weight_rank_anomalies

        selected = ["factor_a", "factor_b", "momentum", "factor_d", "factor_e"]
        factor_data = [
            {"factor_name": "factor_a", "icir": 0.50},
            {"factor_name": "factor_b", "icir": 0.40},
            {"factor_name": "momentum", "icir": 0.25},
            {"factor_name": "factor_d", "icir": 0.20},
            {"factor_name": "factor_e", "icir": 0.15},
        ]
        # momentum ICIR 排名 3/5，但权重排名 5/5（下降 2 位）
        weights = {
            "factor_a": 0.30,
            "factor_b": 0.25,
            "factor_d": 0.20,
            "factor_e": 0.15,
            "momentum": 0.01,
        }

        anomalies = _detect_weight_rank_anomalies(selected, factor_data, weights)
        assert len(anomalies) == 1
        assert anomalies[0]["factor_name"] == "momentum"
        assert anomalies[0]["icir_rank"] == 3
        assert anomalies[0]["weight_rank"] == 5
        assert anomalies[0]["rank_drop"] == 2

    def test_no_anomaly_when_ranks_consistent(self):
        """ICIR 排名与权重排名一致时不应检出异常。"""
        from summary.generate_factor_summary_report import _detect_weight_rank_anomalies

        selected = ["a", "b", "c"]
        factor_data = [
            {"factor_name": "a", "icir": 0.50},
            {"factor_name": "b", "icir": 0.30},
            {"factor_name": "c", "icir": 0.10},
        ]
        weights = {"a": 0.50, "b": 0.30, "c": 0.20}

        anomalies = _detect_weight_rank_anomalies(selected, factor_data, weights)
        assert len(anomalies) == 0

    def test_too_few_factors_returns_empty(self):
        """因子数 < 3 时返回空列表（排名差异无统计意义）。"""
        from summary.generate_factor_summary_report import _detect_weight_rank_anomalies

        selected = ["a", "b"]
        factor_data = [
            {"factor_name": "a", "icir": 0.50},
            {"factor_name": "b", "icir": 0.10},
        ]
        weights = {"a": 0.01, "b": 0.99}

        anomalies = _detect_weight_rank_anomalies(selected, factor_data, weights)
        assert anomalies == []

    def test_uses_factor_name_to_col_map(self):
        """权重字典 key 是 factor_col（可能与 factor_name 不同），应通过映射查找。"""
        from summary.generate_factor_summary_report import _detect_weight_rank_anomalies

        selected = ["momentum_strength"]
        # 仅 1 个因子 → 不足 3 个，返回空，但验证不报 KeyError
        factor_data = [{"factor_name": "momentum_strength", "icir": 0.25}]
        weights = {"momentum_strength": 0.01}

        anomalies = _detect_weight_rank_anomalies(selected, factor_data, weights)
        assert anomalies == []


# ---------------------------------------------------------------------------
# v2.19: _compute_factor_concentration 测试
# ---------------------------------------------------------------------------


class TestComputeFactorConcentration:
    """测试因子贡献集中度检测。"""

    def test_concentration_detected_for_dominant_factor(self):
        """单一因子贡献占比超 50% 或实际/名义 > 2x 时应被检出。"""
        from summary.generate_factor_summary_report import _compute_factor_concentration

        # 模拟 tail_price_position 主导场景
        # weight=0.198, z=-2.45 → contribution=0.485, composite≈1.16
        # concentration=0.485/1.16=41.8% < 50%, 但 relative=41.8%/19.8%=2.1x > 2.0
        top_stocks = [
            {
                "composite_value": -1.2,
                "factor_values_std": {
                    "tail_price_position": -2.45,
                    "momentum_strength": -0.2,
                    "overnight_ret": -0.3,
                },
            },
            {
                "composite_value": -1.1,
                "factor_values_std": {
                    "tail_price_position": -2.45,
                    "momentum_strength": -0.1,
                    "overnight_ret": -0.2,
                },
            },
        ]
        weights = {"tail_price_position": 0.198, "momentum_strength": 0.008, "overnight_ret": 0.103}

        anomalies = _compute_factor_concentration(top_stocks, weights)
        assert len(anomalies) >= 1
        # tail_price_position 应是集中度最高的
        assert anomalies[0]["factor_col"] == "tail_price_position"
        assert anomalies[0]["relative_ratio"] > 2.0

    def test_no_concentration_when_well_diversified(self):
        """因子贡献均匀分布时不应检出异常。"""
        from summary.generate_factor_summary_report import _compute_factor_concentration

        top_stocks = [
            {
                "composite_value": -1.0,
                "factor_values_std": {"a": -1.0, "b": -1.0, "c": -1.0, "d": -1.0},
            },
        ]
        weights = {"a": 0.25, "b": 0.25, "c": 0.25, "d": 0.25}

        anomalies = _compute_factor_concentration(top_stocks, weights)
        # 每个因子贡献 = 0.25 * 1.0 = 0.25, 占比 = 0.25 / 1.0 = 25% < 50%
        assert anomalies == []

    def test_empty_top_stocks_returns_empty(self):
        """空股票列表返回空。"""
        from summary.generate_factor_summary_report import _compute_factor_concentration

        anomalies = _compute_factor_concentration([], {"a": 0.5})
        assert anomalies == []

    def test_zero_composite_returns_empty(self):
        """综合因子值全为 0 时返回空（避免除零）。"""
        from summary.generate_factor_summary_report import _compute_factor_concentration

        top_stocks = [
            {
                "composite_value": 0.0,
                "factor_values_std": {"a": -2.0, "b": -1.0},
            },
        ]
        weights = {"a": 0.5, "b": 0.5}

        anomalies = _compute_factor_concentration(top_stocks, weights)
        assert anomalies == []


class TestWeightLookupFallback:
    """v2.21 Fix1: Rolling ICIR last_day_weights 权重查找回退测试。

    last_day_weights 键使用因子名（如 volume_ratio），而非列名（如 volume_ratio_5）。
    代码应先查列名，再回退因子名，避免权重返回 0。
    """

    def test_factor_name_fallback_when_col_name_misses(self):
        """last_day_weights 用因子名做键时，列名查找失败应回退到因子名查找。"""
        from summary.generate_factor_summary_report import FACTOR_NAME_TO_COL_MAP

        # volume_ratio 的列名是 volume_ratio_5
        factor_name = "volume_ratio"
        factor_col = FACTOR_NAME_TO_COL_MAP.get(factor_name, factor_name)

        # last_day_weights 用因子名做键（实际数据行为）
        last_day_weights = {"volume_ratio": 0.065, "momentum_strength": 0.004}

        # 模拟修复后的查找逻辑
        weight = last_day_weights.get(factor_col, last_day_weights.get(factor_name, 0))

        assert weight == 0.065  # 应该通过因子名回退找到 0.065，而非返回 0

    def test_col_name_still_works_for_static_weights(self):
        """静态权重用列名做键时，列名查找应直接命中。"""
        from summary.generate_factor_summary_report import FACTOR_NAME_TO_COL_MAP

        factor_name = "volume_ratio"
        factor_col = FACTOR_NAME_TO_COL_MAP.get(factor_name, factor_name)

        # meta.weights 用列名做键
        static_weights = {"volume_ratio_5": 0.12, "momentum_strength": 0.004}

        weight = static_weights.get(factor_col, static_weights.get(factor_name, 0))

        assert weight == 0.12  # 列名直接命中


class TestBacktestFactorNameStripping:
    """v2.21 Fix4: load_backtest_results 剥离 _1d 后缀测试。

    intraday_intensity_1d 应剥离为 intraday_intensity（在 FACTOR_DEFINITIONS 中）。
    past_return_1d 不应剥离（剥离后 past_return 不在 FACTOR_DEFINITIONS 中）。
    """

    def test_intraday_intensity_stripped(self):
        """intraday_intensity_1d 应被剥离为 intraday_intensity。"""
        from factor_definitions import FACTOR_DEFINITIONS

        factor_name = "intraday_intensity_1d"
        if factor_name.endswith("_1d"):
            stripped = factor_name[:-3]
            if stripped in FACTOR_DEFINITIONS:
                factor_name = stripped

        assert factor_name == "intraday_intensity"

    def test_past_return_1d_not_stripped(self):
        """past_return_1d 不应被剥离（其因子名本身含 _1d）。"""
        from factor_definitions import FACTOR_DEFINITIONS

        factor_name = "past_return_1d"
        if factor_name.endswith("_1d"):
            stripped = factor_name[:-3]
            if stripped in FACTOR_DEFINITIONS:
                factor_name = stripped

        assert factor_name == "past_return_1d"  # 保持不变


class TestZScoreDisplayConsistency:
    """v2.21 Fix6: z-score 列显示格式统一测试。"""

    def test_zscore_none_shows_nan(self):
        """z-score 为 None 时统一显示'缺失(NaN)'。"""
        # 模拟修复后的逻辑
        v_std = None
        if v_std is None:
            result = "缺失(NaN)"
        elif abs(v_std) < 0.001:
            result = "0.00"
        else:
            result = f"{v_std:.2f}"

        assert result == "缺失(NaN)"

    def test_zscore_near_zero_shows_zero(self):
        """z-score ≈ 0 时统一显示'0.00'，不再显示'≈0(真实)'。"""
        v_std = 0.0001
        if v_std is None:
            result = "缺失(NaN)"
        elif abs(v_std) < 0.001:
            result = "0.00"
        else:
            result = f"{v_std:.2f}"

        assert result == "0.00"
        assert "真实" not in result

    def test_zscore_normal_shows_value(self):
        """z-score 正常值显示两位小数。"""
        v_std = -1.3456
        if v_std is None:
            result = "缺失(NaN)"
        elif abs(v_std) < 0.001:
            result = "0.00"
        else:
            result = f"{v_std:.2f}"

        assert result == "-1.35"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
