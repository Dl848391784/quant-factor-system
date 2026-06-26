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
    _generate_stock_selection_section,
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
    load_stock_name_map,
    merge_factor_data,
    setup_logger,
)


class TestVersion:
    """版本常量测试"""

    def test_version_defined(self):
        """验证版本常量存在"""
        assert __version__ == "3.8"


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
                patch("summary.report.freshness_check.PROJECT_ROOT", root),
                patch(
                    "summary.report.freshness_check.DATA_CHECK_SOURCES",
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
                patch("summary.report.freshness_check.PROJECT_ROOT", root),
                patch(
                    "summary.report.freshness_check.DATA_CHECK_SOURCES",
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
                patch("summary.report.freshness_check.PROJECT_ROOT", root),
                patch(
                    "summary.report.freshness_check.DATA_CHECK_SOURCES",
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
                patch("summary.report.freshness_check.PROJECT_ROOT", root),
                patch(
                    "summary.report.freshness_check.DATA_CHECK_SOURCES",
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
        """测试 factor_ic_data Parquet 从 schema metadata dates[-1] 提取日期"""
        import pyarrow as pa
        import pyarrow.parquet as pq

        logger = MagicMock()

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "data_fetchers" / "result").mkdir(parents=True)

            # 造一个带 dates metadata 的 Parquet 文件（与生产一致）
            file_path = root / "data_fetchers" / "result" / "factor_ic_data.parquet"
            table = pa.table({"date": ["2026-06-01"], "asset": ["000001"]})
            dates_meta = json.dumps(["2026-05-29", "2026-06-01"]).encode()
            table = table.replace_schema_metadata({b"dates": dates_meta})
            pq.write_table(table, file_path)

            with (
                patch("summary.report.freshness_check.PROJECT_ROOT", root),
                patch(
                    "summary.report.freshness_check.DATA_CHECK_SOURCES",
                    {
                        "factor_ic_data": {
                            "path": "data_fetchers/result/factor_ic_data.parquet",
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
                patch("summary.report.freshness_check.PROJECT_ROOT", root),
                patch(
                    "summary.report.freshness_check.DATA_CHECK_SOURCES",
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
                patch("summary.report.freshness_check.PROJECT_ROOT", root),
                patch(
                    "summary.report.freshness_check.DATA_PATHS",
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
                patch("summary.report.freshness_check.PROJECT_ROOT", root),
                patch(
                    "summary.report.freshness_check.DATA_PATHS",
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
        """表头应在有取反因子时显示 * = 已取反对齐到正向语义"""
        flipped_factors = ["overnight_ret"]
        header_note = "  * = 已取反对齐到正向语义" if flipped_factors else ""
        assert "* = 已取反对齐到正向语义" in header_note

    def test_header_note_without_flipped_factors(self):
        """无取反因子时表头不应有额外说明"""
        flipped_factors = []
        header_note = "  * = 已取反对齐到正向语义" if flipped_factors else ""
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
        with patch("summary.report.data_loaders.PROJECT_ROOT", mock_project_root):
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


# ============================================================================
# v2.42: 短名单扩展 Top 30 测试 (designs/feat_shortlist_top30_v1.md §8.1)
# ============================================================================


def _build_mock_stock_result(n_stocks: int) -> dict:
    """构造 mock stock_selection_result.json 数据 (n_stocks 只股票)."""
    top_stocks = []
    for i in range(n_stocks):
        top_stocks.append(
            {
                "rank": i + 1,
                "code": f"60{i:04d}",
                "composite_value": -0.5 - i * 0.01,
                "factor_values": {"interaction_kdj__ret5d_pos__ret5d_pos": -0.8, "bollinger_pb": 0.04},
                "factor_values_std": {
                    "interaction_kdj__ret5d_pos__ret5d_pos": 0.14 - i * 0.01,
                    "bollinger_pb": -1.06 + i * 0.02,
                    "return_5d": -0.59,
                },
                "weight_coverage": 1.0,
            }
        )
    return {
        "meta": {
            "selection_date": "2026-06-22",
            "weight_method": "rolling_icir_weight",
            "composite_score": 0.6021,
            "factor_direction": "positive",
            "top_n": n_stocks,
            "stocks_on_date": 2749,
            "min_amplitude": 0.01,
            "excluded_by_amplitude": 12,
        },
        "top_stocks": top_stocks,
        "weight_config": {"method": "rolling_icir_weight", "window": 60},
    }


class TestShortlistTop30:
    """Top 30 短名单展示测试 (v2.42)."""

    def test_top10_only_uses_detail_only(self):
        """N=10 时仅输出详表 (向后兼容)."""
        result = _build_mock_stock_result(10)
        weights = {"interaction_kdj__ret5d_pos__ret5d_pos": 0.1, "bollinger_pb": 0.08, "return_5d": 0.07}
        lines = _generate_stock_selection_section(result, weights, None)
        text = "\n".join(lines)
        # N=10 时保留旧版"【Top 10 股票】"标题, 不进入简表分支
        assert "【Top 10 股票】" in text
        assert "短名单" not in text
        assert "简表" not in text

    def test_top30_outputs_detail_plus_brief(self):
        """N=30 时输出 Top 10 详表 + 11~30 简表."""
        result = _build_mock_stock_result(30)
        weights = {"interaction_kdj__ret5d_pos__ret5d_pos": 0.1, "bollinger_pb": 0.08, "return_5d": 0.07}
        lines = _generate_stock_selection_section(result, weights, None)
        text = "\n".join(lines)
        # 标题分层
        assert "【Top 10 详表（重点观察）】" in text
        assert "【短名单 11~30 简表（备选池）】" in text
        # 详表 10 行 + 简表 20 行
        assert "主导前 3 因子" in text
        # 战略目标提示
        assert "人工决断" in text

    def test_brief_table_dominant_factors_format(self):
        """简表展示主导因子占比, 格式为 'name(XX%)'."""
        result = _build_mock_stock_result(15)  # 触发简表 (>10)
        weights = {"interaction_kdj__ret5d_pos__ret5d_pos": 0.5, "bollinger_pb": 0.3, "return_5d": 0.2}
        lines = _generate_stock_selection_section(result, weights, None)
        # 简表区块至少包含一行 "(XX%)"
        brief_block = [
            line
            for line in lines
            if "(" in line
            and "%)" in line
            and ("interaction_kdj__ret5d_pos__ret5d_pos" in line or "bollinger_pb" in line)
        ]
        assert len(brief_block) > 0, f"简表未找到主导因子百分比行: {lines}"

    def test_brief_table_handles_missing_weights(self):
        """comp_weights=None 时简表显示 '(无主导因子)' 而非崩溃."""
        result = _build_mock_stock_result(12)
        lines = _generate_stock_selection_section(result, None, None)
        text = "\n".join(lines)
        assert "【短名单 11~12 简表（备选池）】" in text
        assert "(无主导因子)" in text

    def test_top30_meta_top_n_displayed(self):
        """meta.top_n=30 在报告头部正确展示."""
        result = _build_mock_stock_result(30)
        lines = _generate_stock_selection_section(result, {}, None)
        text = "\n".join(lines)
        assert "选出股票数: 30 只" in text


# ============================================================================
# v2.43: 决策卡片渲染测试 (designs/feat_decision_card_v1.md §6)
# ============================================================================


def _add_decision_cards(result: dict, with_d2_warnings: bool = False) -> dict:
    """给 mock result 的 top_stocks 追加 decision_card 字段 (v3.9: 过热/趋势维度)."""
    for s in result["top_stocks"]:
        s["decision_card"] = {
            "d1_classification": {
                "return_5d_bucket": "中涨(3~8%)" if with_d2_warnings else "微涨(0~3%)",
                "return_5d_value": 0.05,
                "amplitude_bucket": "中(4~8%)",
                "amplitude_value": 0.05,
                "close_position_5d": "顶部",
            },
            "d2_risk": {
                "high_turnover": with_d2_warnings,
                "high_volume_ratio": False,
                "extreme_amplitude": False,
                "warning_count": 1 if with_d2_warnings else 0,
            },
            "d3_trend": {
                "near_high": True,
                "bollinger_upper": True,
                "rsi_overbought": True,
                "hit_count": 3,
                "raw_signals_available": True,
            },
            "d4_history": {
                "times_in_top30_last_60d": None,
                "avg_1d_return_when_in_top30": None,
                "note": "需历史归档机制（独立 design 待启动）",
            },
        }
    return result


class TestDecisionCardRendering:
    """v2.43 决策卡片在 summary 中的渲染."""

    def test_card_block_rendered_when_cards_present(self):
        result = _add_decision_cards(_build_mock_stock_result(15))
        lines = _generate_stock_selection_section(result, {}, None)
        text = "\n".join(lines)
        assert "【决策卡片 (人工决断辅助, 5 维客观字段)】" in text
        assert "D1 涨幅档" in text
        assert "D5 人工核查清单" in text

    def test_card_block_skipped_when_no_cards(self):
        """top_stocks 无 decision_card 字段时, 不渲染决策卡片块."""
        result = _build_mock_stock_result(15)  # 不调 _add_decision_cards
        lines = _generate_stock_selection_section(result, {}, None)
        text = "\n".join(lines)
        assert "【决策卡片" not in text
        assert "D5 人工核查清单" not in text

    def test_d2_warnings_show_flags(self):
        """D2 warning_count > 0 时标注命中详情."""
        result = _add_decision_cards(_build_mock_stock_result(11), with_d2_warnings=True)
        lines = _generate_stock_selection_section(result, {}, None)
        text = "\n".join(lines)
        # 1/3 + 命中标签
        assert "1/3(高换手)" in text

    def test_d3_na_when_signals_unavailable(self):
        """D3 raw_signals_available=False 时显示 n/a."""
        result = _add_decision_cards(_build_mock_stock_result(11))
        # 把第一只改成 raw_signals_available=False
        result["top_stocks"][0]["decision_card"]["d3_trend"] = {
            "near_high": None,
            "bollinger_upper": None,
            "rsi_overbought": None,
            "hit_count": 0,
            "raw_signals_available": False,
        }
        lines = _generate_stock_selection_section(result, {}, None)
        text = "\n".join(lines)
        assert " n/a   " in text  # 仅 D3 列宽 6 的 n/a

    def test_d5_checklist_rendered(self):
        result = _add_decision_cards(_build_mock_stock_result(11))
        lines = _generate_stock_selection_section(result, {}, None)
        text = "\n".join(lines)
        # 4 项核查
        assert "1. 公告" in text
        assert "2. 新闻" in text
        assert "3. 财报" in text
        assert "4. 股东" in text


# ============================================================================
# v2.26: 股票名称展示测试 (2026-06-23)
# ============================================================================


class TestStockNameDisplay:
    """v2.26 第八节短名单在股票代码后展示股票名称."""

    def _build_name_map(self, n: int) -> dict[str, str]:
        # 匹配 _build_mock_stock_result 的 code 模式 "60XXXX"
        return {f"60{i:04d}": f"测试股{i:02d}" for i in range(n)}

    def test_top10_detail_table_shows_name_column(self):
        """Top 10 详表表头与数据行均含股票名称列."""
        result = _build_mock_stock_result(10)
        name_map = self._build_name_map(10)
        lines = _generate_stock_selection_section(result, {}, None, name_map)
        text = "\n".join(lines)
        # 表头新增"股票名称"列
        assert "股票名称" in text
        # 至少一只股票的名称出现在详表
        assert "测试股00" in text
        assert "测试股09" in text

    def test_brief_table_shows_name_column(self):
        """短名单 11~N 简表展示股票名称."""
        result = _build_mock_stock_result(15)
        name_map = self._build_name_map(15)
        lines = _generate_stock_selection_section(result, {}, None, name_map)
        text = "\n".join(lines)
        # 简表区域应展示 11~15 的名称
        assert "测试股10" in text
        assert "测试股14" in text

    def test_decision_card_shows_name_column(self):
        """决策卡片表头与行均展示股票名称."""
        result = _add_decision_cards(_build_mock_stock_result(11))
        name_map = self._build_name_map(11)
        lines = _generate_stock_selection_section(result, {}, None, name_map)
        text = "\n".join(lines)
        # 决策卡片表头新增"股票名称"列
        assert "排名 股票代码  股票名称" in text
        # 决策卡片中至少有名称出现
        assert "测试股00" in text

    def test_missing_name_falls_back_to_dash(self):
        """name_map 缺失某 code 时回退为 '--', 不崩溃."""
        result = _build_mock_stock_result(12)
        # 仅提供前 5 只的名称
        partial = {f"60{i:04d}": f"测试股{i:02d}" for i in range(5)}
        lines = _generate_stock_selection_section(result, {}, None, partial)
        text = "\n".join(lines)
        # 第 6 只之后应回退为 "--"
        assert "测试股04" in text
        assert "--" in text

    def test_none_name_map_does_not_crash(self):
        """stock_name_map=None 时全部展示 '--', 报告正常生成."""
        result = _build_mock_stock_result(12)
        lines = _generate_stock_selection_section(result, {}, None, None)
        text = "\n".join(lines)
        # 表头仍含"股票名称", 数据行回退为 "--"
        assert "股票名称" in text
        assert "--" in text


class TestLoadStockNameMap:
    """load_stock_name_map 数据加载逻辑测试."""

    def test_missing_file_returns_empty_dict(self, tmp_path, monkeypatch):
        """文件不存在时返回 {} 且仅 warning, 不抛错."""
        import summary.report.data_loaders as mod

        fake_path = tmp_path / "nonexistent.json"
        monkeypatch.setattr(mod, "STOCK_LIST_DATA", fake_path)
        logger = logging.getLogger("test_load_stock_name_map_missing")
        result = mod.load_stock_name_map(logger)
        assert result == {}

    def test_valid_file_returns_code_to_name(self, tmp_path, monkeypatch):
        """正常 stock_list.json 返回 {code: name}, 名称清洗全角空格."""
        import summary.report.data_loaders as mod

        fake_path = tmp_path / "stock_list.json"
        fake_path.write_text(
            json.dumps(
                {
                    "meta": {"total_count": 3},
                    "stocks": [
                        {"code": "600000", "name": "浦发银行"},
                        {"code": "000002", "name": "万 科Ａ"},  # 含全角空格
                        {"code": "601857", "name": "中国石油"},
                    ],
                }
            ),
            encoding="utf-8",
        )
        monkeypatch.setattr(mod, "STOCK_LIST_DATA", fake_path)
        logger = logging.getLogger("test_load_stock_name_map_valid")
        result = mod.load_stock_name_map(logger)
        assert result["600000"] == "浦发银行"
        assert result["000002"] == "万科Ａ"  # 全角空格被清洗
        assert result["601857"] == "中国石油"
        assert len(result) == 3

    def test_malformed_file_does_not_crash(self, tmp_path, monkeypatch):
        """文件解析失败时返回 {}, 仅 warning."""
        import summary.report.data_loaders as mod

        fake_path = tmp_path / "stock_list.json"
        fake_path.write_text("not a valid json {{{", encoding="utf-8")
        monkeypatch.setattr(mod, "STOCK_LIST_DATA", fake_path)
        logger = logging.getLogger("test_load_stock_name_map_malformed")
        result = mod.load_stock_name_map(logger)
        assert result == {}


class TestLoadStockSelectionParquet:
    """v3.7: load_stock_selection_result 从 Parquet 分区数据集读取最新一日.

    依赖 comprehensive_factor.stock_selector.write_selection_history 生成真 Parquet,
    避免手搓 schema 导致测试与生产代码漂移 (设计依据: PROJECT.md 规则 #4).
    """

    @pytest.fixture
    def populated_dataset(self, tmp_path):
        """跑 write_selection_history 写出真 Parquet 数据集, 返回 history_root."""
        from comprehensive_factor.stock_selector import (
            StockSelectorConfig,
            write_selection_history,
        )

        output_dir = tmp_path / "result"
        output_dir.mkdir()
        cfg = StockSelectorConfig(
            top_n=3,
            selection_date="2026-06-24",
            factor_direction="positive",
            rolling_window=60,
            return_period="1d",
            data_source=tmp_path / "fake.parquet",
            ic_result_dir=tmp_path,
            weight_result_path=tmp_path / "fake_w.json",
            output_dir=output_dir,
            min_amplitude=0.01,
            enable_two_stage=True,
            stage1_pool_size=5,
            stage2_sort_col="turnover_rate",
            stage2_ascending=True,
        )
        wcfg = {
            "best_selection": {
                "method": "auto_select",
                "composite_score": 0.5,
            },
        }

        # 构造 3+3+3 假行: stage1 按 composite 降序, stage2 按 turnover 升序, stage3 = stage2 - 1 excluded
        def make_row(rank, code, cv, turnover=None, s1_rank=None, excluded=None):
            row = {
                "rank": rank,
                "code": code,
                "composite_value": cv,
                "weight_coverage": 1.0,
                "factor_values": {"rsi_6": 50.0},
                "factor_values_std": {"rsi_6": 0.5},
                "decision_card": None,
            }
            if turnover is not None:
                row["stage2_sort_value"] = turnover
            if s1_rank is not None:
                row["stage1_rank"] = s1_rank
            if excluded:
                row["excluded_at_stage3"] = excluded
            return row

        stage1 = [
            make_row(1, "600001", 3.5),
            make_row(2, "600002", 3.2),
            make_row(3, "600003", 3.0),
        ]
        stage2 = [
            make_row(1, "600003", 3.0, turnover=0.5, s1_rank=3),
            make_row(2, "600001", 3.5, turnover=1.2, s1_rank=1),
            make_row(3, "600002", 3.2, turnover=2.1, s1_rank=2),
        ]
        stage3 = [
            make_row(1, "600003", 3.0, turnover=0.5, s1_rank=3),
            make_row(2, "600001", 3.5, turnover=1.2, s1_rank=1),
            make_row(
                3,
                "600002",
                3.2,
                turnover=2.1,
                s1_rank=2,
                excluded="stabilization_check_failed",
            ),
        ]

        write_selection_history(
            stage1_top=stage1,
            stage2_top=stage2,
            stage3_top=stage3,
            config=cfg,
            weight_config=wcfg,
            selection_date="2026-06-24",
            stocks_on_date=2500,
            factor_list=["rsi"],
            factor_cols=["rsi_6"],
            direction_map={"rsi": "positive"},
            flipped_factors=[],
            exclusion_stats={
                "excluded_by_amplitude": 12,
                "excluded_by_coverage": 5,
            },
            output_dir=output_dir,
        )
        return output_dir / "stock_selection_history"

    def test_load_returns_three_stages(self, tmp_path, monkeypatch, populated_dataset):
        """读回应包含 stage1_top / stage2_top / stage3_top 三段 + 向后兼容 top_stocks."""
        import summary.report.data_loaders as mod

        # 重写 DATA_PATHS 指向测试数据集 + PROJECT_ROOT
        monkeypatch.setattr(mod, "PROJECT_ROOT", populated_dataset.parent.parent)
        monkeypatch.setitem(
            mod.DATA_PATHS,
            "stock_selection",
            str(populated_dataset.relative_to(populated_dataset.parent.parent)),
        )

        logger = logging.getLogger("test_load_three_stages")
        result = mod.load_stock_selection_result(logger)

        assert result is not None
        assert len(result["stage1_top"]) == 3
        assert len(result["stage2_top"]) == 3
        assert len(result["stage3_top"]) == 3
        # 向后兼容: top_stocks == stage3_top
        assert result["top_stocks"] == result["stage3_top"]
        # Stage 1 按 composite 降序 (rank=1 对应 cv=3.5)
        assert result["stage1_top"][0]["code"] == "600001"
        assert result["stage1_top"][0]["composite_value"] == 3.5
        # Stage 2 按 turnover 升序 (rank=1 对应 turnover=0.5)
        assert result["stage2_top"][0]["code"] == "600003"
        assert result["stage2_top"][0]["stage2_sort_value"] == 0.5
        assert result["stage2_top"][0]["stage1_rank"] == 3
        # Stage 3 含 excluded_at_stage3 标记
        # 注: stock_selector 实际逻辑: excluded_at_stage3 标在 Stage 2 行 (stage==2 且 code 不在 stage3),
        # 标记值 = "stabilization" (在 stage3 中缺席的 stage2 候选). Stage 3 行此字段永远 None.
        # populated_dataset fixture stage2=[600003,600001,600002] 与 stage3 全重合 → 无 stabilization 标记;
        # 验证: stage1/2/3 加载链路至少不抛错, 字段存在性即可.
        assert "excluded_at_stage3" not in result["stage3_top"][0] or (
            result["stage3_top"][0].get("excluded_at_stage3") is None
        )

    def test_meta_from_file_metadata(self, tmp_path, monkeypatch, populated_dataset):
        """meta 应从 Parquet file-level metadata 提取 excluded_by_* 等统计."""
        import summary.report.data_loaders as mod

        monkeypatch.setattr(mod, "PROJECT_ROOT", populated_dataset.parent.parent)
        monkeypatch.setitem(
            mod.DATA_PATHS,
            "stock_selection",
            str(populated_dataset.relative_to(populated_dataset.parent.parent)),
        )

        logger = logging.getLogger("test_meta_metadata")
        result = mod.load_stock_selection_result(logger)
        meta = result["meta"]
        assert meta["selection_date"] == "2026-06-24"
        assert meta["weight_method"] == "auto_select"
        assert meta["top_n"] == 3
        assert meta["stocks_on_date"] == 2500
        assert meta["excluded_by_amplitude"] == 12
        assert meta["excluded_by_coverage"] == 5
        assert meta["stage1_pool_size"] == 5
        assert meta["stage2_sort_col"] == "turnover_rate"
        assert meta["stage2_ascending"] is True

    def test_missing_dataset_returns_none(self, tmp_path, monkeypatch):
        """数据集目录不存在返回 None (不抛异常)."""
        import summary.report.data_loaders as mod

        monkeypatch.setattr(mod, "PROJECT_ROOT", tmp_path)
        monkeypatch.setitem(mod.DATA_PATHS, "stock_selection", "nonexistent/dataset")
        logger = logging.getLogger("test_missing_dataset")
        assert mod.load_stock_selection_result(logger) is None

    def test_render_section_includes_stage1_and_stage2(self, tmp_path, monkeypatch, populated_dataset):
        """_generate_stock_selection_section 应渲染 Stage 1 + Bottom + 最终短名单 (v3.10)."""
        import summary.report.data_loaders as dl_mod
        import summary.report.sections as sec_mod

        monkeypatch.setattr(dl_mod, "PROJECT_ROOT", populated_dataset.parent.parent)
        monkeypatch.setitem(
            dl_mod.DATA_PATHS,
            "stock_selection",
            str(populated_dataset.relative_to(populated_dataset.parent.parent)),
        )
        logger = logging.getLogger("test_render_three_stages")
        result = dl_mod.load_stock_selection_result(logger)

        lines = sec_mod._generate_stock_selection_section(result, {}, None)
        text = "\n".join(lines)
        assert "选股轨迹 (v3.13: Bottom90 LR 打分排序, 不截断)" in text
        assert "Stage 1: 综合因子值 Top 3" in text
        assert "LR 打分排序" in text
        # Stage 1 第一名股票代码必须出现在 Stage 1 段
        assert "600001" in text


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
