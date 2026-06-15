#!/usr/bin/env python3
"""FactorSpec 注册与校验单元测试

覆盖：
- FactorSpec 基本属性
- register_factor() L2 校验(5 条规则)
- FACTOR_REGISTRY 注册表行为
- _fn 字段(None / 有效 Callable)

作者: 云瑶
创建日期: 2026-06-15
"""

from __future__ import annotations

import pytest

from factor_ic.common.data_columns import JOIN_KEYS
from factor_ic.common.factor_spec import (
    FACTOR_REGISTRY,
    FactorSpec,
    register_factor,
)


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture(autouse=True)
def _clean_registry():
    """每个测试前后清理注册表，避免测试间污染。"""
    saved = dict(FACTOR_REGISTRY)
    FACTOR_REGISTRY.clear()
    yield
    FACTOR_REGISTRY.clear()
    FACTOR_REGISTRY.update(saved)


def _make_spec(**overrides):
    """构建最小合法 FactorSpec。"""
    defaults = {
        "factor_name": "test_factor",
        "factor_col": "test_col",
        "required_columns": ("date", "asset", "test_col"),
    }
    defaults.update(overrides)
    return FactorSpec(**defaults)


# ============================================================================
# FactorSpec 基本属性
# ============================================================================


class TestFactorSpecBasic:
    """FactorSpec 属性测试。"""

    def test_frozen(self):
        spec = _make_spec()
        with pytest.raises(AttributeError):
            spec.factor_name = "changed"  # type: ignore[misc]

    def test_default_none_fields(self):
        spec = _make_spec()
        assert spec.calculation is None
        assert spec.calc_params_fn is None
        assert spec.extra_log_params_fn is None

    def test_with_callable_fields(self):
        spec = FactorSpec(
            factor_name="kdj_j",
            factor_col="kdj_j",
            required_columns=("date", "asset", "close", "high", "low", "kdj_j"),
            calculation=lambda df: df,
            calc_params_fn=lambda args: {"n": args.n},
            extra_log_params_fn=lambda args: {"n": args.n},
        )
        assert spec.calculation is not None
        assert spec.calc_params_fn is not None


# ============================================================================
# register_factor L2 校验
# ============================================================================


class TestRegisterFactorValidation:
    """register_factor() 5 条校验规则。"""

    def test_empty_required_columns_raises(self):
        """规则 1: required_columns 非空。"""
        with pytest.raises(ValueError, match="不能为空"):
            register_factor(_make_spec(required_columns=()))

    def test_duplicate_columns_raises(self):
        """规则 2: required_columns 无重复。"""
        with pytest.raises(ValueError, match="重复列"):
            register_factor(_make_spec(required_columns=("date", "asset", "date")))

    def test_uppercase_column_raises(self):
        """规则 3: 全小写 + 下划线 + 点。"""
        with pytest.raises(ValueError, match="非小写"):
            register_factor(_make_spec(required_columns=("date", "asset", "CLOSE")))

    def test_factor_col_not_in_required_raises(self):
        """规则 4: factor_col 在 required_columns 中。"""
        with pytest.raises(ValueError, match="不在 required_columns"):
            register_factor(
                FactorSpec(
                    factor_name="test",
                    factor_col="missing_col",
                    required_columns=("date", "asset", "other_col"),
                )
            )

    def test_duplicate_registration_raises(self):
        """规则 5: 不可覆盖注册。"""
        register_factor(_make_spec(factor_name="unique_factor"))
        with pytest.raises(ValueError, match="已注册"):
            register_factor(_make_spec(factor_name="unique_factor"))

    def test_valid_spec_registers(self):
        """合法 spec 成功注册。"""
        spec = register_factor(_make_spec(factor_name="good_factor"))
        assert "good_factor" in FACTOR_REGISTRY
        assert FACTOR_REGISTRY["good_factor"] is spec

    def test_returns_same_spec(self):
        """返回值是传入的同一个 spec（便于模块级声明）。"""
        spec = _make_spec()
        result = register_factor(spec)
        assert result is spec

    def test_dot_in_column_name_allowed(self):
        """点号在列名中允许(如未来可能出现的嵌套字段)。"""
        register_factor(
            _make_spec(
                factor_name="dot_factor",
                factor_col="nested.field",
                required_columns=("date", "asset", "nested.field"),
            )
        )
        assert "dot_factor" in FACTOR_REGISTRY

    def test_underscore_in_column_name_allowed(self):
        """下划线在列名中允许(如 tail_price_position)。"""
        register_factor(
            _make_spec(
                factor_name="underscore_factor",
                factor_col="tail_price_position",
                required_columns=("date", "asset", "tail_price_position"),
            )
        )
        assert "underscore_factor" in FACTOR_REGISTRY


# ============================================================================
# 使用 JOIN_KEYS 组合
# ============================================================================


class TestJoinKeysComposition:
    """required_columns = JOIN_KEYS + (...) 组合模式。"""

    def test_join_keys_plus_single(self):
        spec = register_factor(
            FactorSpec(
                factor_name="amplitude_delta",
                factor_col="amplitude_delta",
                required_columns=JOIN_KEYS + ("amplitude", "amplitude_delta"),
            )
        )
        assert "amplitude_delta" in FACTOR_REGISTRY
        assert spec.required_columns == ("date", "asset", "amplitude", "amplitude_delta")

    def test_join_keys_guarantees_date_first(self):
        """JOIN_KEYS 保证 date 在最前。"""
        assert JOIN_KEYS[0] == "date"
        assert JOIN_KEYS[1] == "asset"
