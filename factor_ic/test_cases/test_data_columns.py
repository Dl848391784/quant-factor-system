#!/usr/bin/env python3
"""data_columns 模块单元测试

覆盖：
- 标准列组常量(JOIN_KEYS / OHLC / OHLCV / PRICE_VOLUME)格式
- validate_required_columns() 正常/缺失/空可用列
- DataSchemaError 属性与消息格式

作者: 云瑶
创建日期: 2026-06-15
"""

from __future__ import annotations

import json

import pytest

from factor_ic.common.data_columns import (
    JOIN_KEYS,
    OHLC,
    OHLCV,
    PRICE_VOLUME,
    validate_required_columns,
)
from factor_ic.common.exceptions import DataSchemaError


# ============================================================================
# 标准列组常量
# ============================================================================


class TestColumnConstants:
    """标准列组常量格式校验。"""

    def test_join_keys_contains_date_asset(self):
        assert JOIN_KEYS == ("date", "asset")

    def test_ohlc_alphabetical(self):
        assert OHLC == ("close", "high", "low", "open")

    def test_ohlcv_alphabetical(self):
        assert OHLCV == ("close", "high", "low", "open", "volume")

    def test_price_volume_alphabetical(self):
        assert PRICE_VOLUME == ("close", "turnover_rate", "volume")

    def test_all_constants_are_tuples(self):
        for const in (JOIN_KEYS, OHLC, OHLCV, PRICE_VOLUME):
            assert isinstance(const, tuple)

    def test_no_overlap_between_ohlcv_and_price_volume(self):
        """OHLCV 和 PRICE_VOLUME 有 close 重叠，但整体不同。"""
        assert OHLCV != PRICE_VOLUME


# ============================================================================
# validate_required_columns
# ============================================================================


class TestValidateRequiredColumns:
    """validate_required_columns() 校验。"""

    def test_all_present_no_error(self):
        """全部列存在时不抛异常。"""
        validate_required_columns(
            factor_name="test",
            required_columns=("date", "asset", "close"),
            available_columns=["date", "asset", "close", "high", "low"],
        )

    def test_missing_single_column_raises(self):
        """缺失 1 列时抛 DataSchemaError。"""
        with pytest.raises(DataSchemaError) as exc_info:
            validate_required_columns(
                factor_name="test_factor",
                required_columns=("date", "asset", "amplitude"),
                available_columns=["date", "asset", "close"],
            )
        err = exc_info.value
        assert err.factor_name == "test_factor"
        assert err.missing_columns == ["amplitude"]
        assert "close" in err.available_columns

    def test_missing_multiple_columns_raises(self):
        """缺失多列时全部报告。"""
        with pytest.raises(DataSchemaError) as exc_info:
            validate_required_columns(
                factor_name="test_factor",
                required_columns=("date", "asset", "amplitude", "rsi_6"),
                available_columns=["date", "asset"],
            )
        err = exc_info.value
        assert set(err.missing_columns) == {"amplitude", "rsi_6"}

    def test_empty_available_raises(self):
        """可用列为空时，所有 required 都算缺失。"""
        with pytest.raises(DataSchemaError) as exc_info:
            validate_required_columns(
                factor_name="test",
                required_columns=("date", "asset"),
                available_columns=[],
            )
        assert exc_info.value.missing_columns == ["date", "asset"]

    def test_error_message_contains_factor_name(self):
        """错误消息含因子名上下文。"""
        with pytest.raises(DataSchemaError, match="amplitude_delta"):
            validate_required_columns(
                factor_name="amplitude_delta",
                required_columns=("date", "asset", "amplitude"),
                available_columns=["date", "asset"],
            )

    def test_error_message_truncates_available(self):
        """可用列超过 20 个时消息截断。"""
        many_cols = [f"col_{i}" for i in range(50)]
        with pytest.raises(DataSchemaError) as exc_info:
            validate_required_columns(
                factor_name="test",
                required_columns=("missing_col",),
                available_columns=many_cols,
            )
        msg = str(exc_info.value)
        # 消息中含 "前20" 字样
        assert "前20" in msg

    def test_accepts_list_required_columns(self):
        """required_columns 支持 list 输入。"""
        validate_required_columns(
            factor_name="test",
            required_columns=["date", "asset"],
            available_columns=["date", "asset", "close"],
        )

    def test_tuple_available_columns(self):
        """available_columns 支持 tuple 输入。"""
        validate_required_columns(
            factor_name="test",
            required_columns=("date", "asset"),
            available_columns=("date", "asset", "close"),
        )


# ============================================================================
# load_available_columns
# ============================================================================


class TestLoadAvailableColumns:
    """load_available_columns() schema 查询测试。"""

    def test_load_from_real_file(self, tmp_path):
        """从临时 JSON 文件加载列名清单。"""
        from factor_ic.common.data_columns import load_available_columns

        # 写临时文件
        manifest = {
            "base_cols": ["date", "asset"],
            "extended_factor_cols": ["amplitude"],
            "return_cols": ["forward_return_1d"],
            "all_cols": ["date", "asset", "amplitude", "forward_return_1d"],
            "generated_at": "2026-06-15 12:00:00",
        }
        manifest_path = tmp_path / "factor_ic_data_columns.json"
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

        # 清缓存
        import factor_ic.common.data_columns as _mod
        _mod._CACHED_COLUMNS = None

        result = load_available_columns(columns_path=manifest_path)
        assert result["base_cols"] == ["date", "asset"]
        assert "amplitude" in result["extended_factor_cols"]

        # 清缓存
        _mod._CACHED_COLUMNS = None

    def test_missing_file_returns_empty(self, tmp_path):
        """文件不存在时返回空 dict。"""
        import factor_ic.common.data_columns as _mod
        from factor_ic.common.data_columns import load_available_columns
        _mod._CACHED_COLUMNS = None

        result = load_available_columns(columns_path=tmp_path / "nonexistent.json")
        assert result == {}

        _mod._CACHED_COLUMNS = None

    def test_caches_result(self, tmp_path):
        """第二次调用直接返回缓存。"""
        from factor_ic.common.data_columns import load_available_columns

        manifest = {"all_cols": ["date"], "generated_at": "2026-06-15"}
        manifest_path = tmp_path / "factor_ic_data_columns.json"
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

        import factor_ic.common.data_columns as _mod
        _mod._CACHED_COLUMNS = None

        r1 = load_available_columns(columns_path=manifest_path)
        r2 = load_available_columns(columns_path=manifest_path)
        assert r1 is r2  # 同一对象 = 缓存命中

        _mod._CACHED_COLUMNS = None
