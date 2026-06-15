#!/usr/bin/env python3
"""
factor_ic.common.cli_helpers 单元测试

测试覆盖：
- safe_dict: None / dict / 非 dict 类型 / 带 logger 与不带 logger 两种调用
- format_finite: None / NaN / ±Inf / 非数 / bool / 合法数值（含 0、负数、百分比）
- DEFAULT_MIN_STOCKS: 与 factor_ic_runner 同名参数默认值一致性
"""

import logging
from unittest.mock import MagicMock

import pytest

from factor_ic.common.cli_helpers import (
    DEFAULT_MIN_STOCKS,
    format_finite,
    safe_dict,
)


# ========== safe_dict ==========


class TestSafeDict:
    def test_none_returns_empty_dict(self):
        assert safe_dict(None) == {}

    def test_dict_returns_unchanged(self):
        data = {"a": 1, "b": [1, 2]}
        assert safe_dict(data) == data
        # 同一引用（不复制）
        assert safe_dict(data) is data

    def test_empty_dict_returns_empty(self):
        # 合法 falsy 值不被误替换
        assert safe_dict({}) == {}

    def test_list_falls_back_to_empty(self):
        assert safe_dict([1, 2, 3]) == {}

    def test_string_falls_back_to_empty(self):
        assert safe_dict("not a dict") == {}

    def test_int_falls_back_to_empty(self):
        assert safe_dict(42) == {}

    def test_logger_warning_on_invalid_type(self):
        logger = MagicMock(spec=logging.Logger)
        result = safe_dict([1, 2], field_name="my_field", logger=logger)
        assert result == {}
        logger.warning.assert_called_once()
        msg = logger.warning.call_args[0][0]
        assert "my_field" in msg
        assert "list" in msg

    def test_logger_silent_on_none(self):
        # None 是合法情况，不应产生 warning
        logger = MagicMock(spec=logging.Logger)
        safe_dict(None, field_name="x", logger=logger)
        logger.warning.assert_not_called()

    def test_logger_silent_on_dict(self):
        logger = MagicMock(spec=logging.Logger)
        safe_dict({"k": "v"}, field_name="x", logger=logger)
        logger.warning.assert_not_called()

    def test_no_logger_silent_fallback(self):
        # logger=None 时静默 fallback，不抛异常
        result = safe_dict([1, 2], field_name="x")
        assert result == {}


# ========== format_finite ==========


class TestFormatFinite:
    def test_none_returns_na(self):
        assert format_finite(None, ".4f") == "N/A"

    def test_nan_returns_na(self):
        assert format_finite(float("nan"), ".4f") == "N/A"

    def test_positive_inf_returns_na(self):
        assert format_finite(float("inf"), ".4f") == "N/A"

    def test_negative_inf_returns_na(self):
        assert format_finite(float("-inf"), ".4f") == "N/A"

    def test_string_returns_na(self):
        assert format_finite("0.5", ".4f") == "N/A"

    def test_list_returns_na(self):
        assert format_finite([1, 2], ".4f") == "N/A"

    def test_bool_true_returns_na(self):
        # bool 是 int 子类但格式化无业务意义
        assert format_finite(True, ".4f") == "N/A"

    def test_bool_false_returns_na(self):
        assert format_finite(False, ".4f") == "N/A"

    def test_zero_float_formatted(self):
        # 合法 falsy 值不被当作"无效"
        assert format_finite(0.0, ".4f") == "0.0000"

    def test_zero_int_formatted(self):
        assert format_finite(0, ".4f") == "0.0000"

    def test_positive_float_formatted(self):
        assert format_finite(1.2345, ".2f") == "1.23"

    def test_negative_float_formatted(self):
        assert format_finite(-0.5678, ".4f") == "-0.5678"

    def test_percent_format(self):
        assert format_finite(-0.05, ".2%") == "-5.00%"

    def test_int_with_float_format(self):
        assert format_finite(42, ".2f") == "42.00"

    def test_very_small_float(self):
        # 接近 0 但非 0
        result = format_finite(1e-10, ".4f")
        assert result == "0.0000"

    def test_large_finite_float(self):
        # 大数仍然 finite
        assert format_finite(1e6, ".0f") == "1000000"


# ========== DEFAULT_MIN_STOCKS ==========


class TestDefaultMinStocks:
    def test_value_is_10(self):
        assert DEFAULT_MIN_STOCKS == 10

    def test_type_is_int(self):
        assert isinstance(DEFAULT_MIN_STOCKS, int)
        assert not isinstance(DEFAULT_MIN_STOCKS, bool)  # 防止 bool 子类污染

    def test_consistent_with_runner_default(self):
        """与 factor_ic_runner.run_factor_ic_analysis 的 min_stocks 默认值一致

        防止跨模块默认值漂移导致行为不一致。
        """
        import inspect

        from factor_ic.common.factor_ic_runner import run_factor_ic_analysis

        sig = inspect.signature(run_factor_ic_analysis)
        runner_default = sig.parameters["min_stocks"].default
        assert runner_default == DEFAULT_MIN_STOCKS, (
            f"DEFAULT_MIN_STOCKS={DEFAULT_MIN_STOCKS} 与 "
            f"run_factor_ic_analysis(min_stocks={runner_default}) 不一致"
        )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
