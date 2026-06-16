#!/usr/bin/env python3
"""FactorSpec 单元测试（覆盖 v1.1 自动派生 + 双声明一致性校验）。

5 个 case（遵循 factor_spec_required_cols_and_sys_path_design.md §4.2 R3.1）：
- A: required_columns=None + calculation 有 .required_cols → 自动派生
- B: required_columns=None + calculation 无 .required_cols → ValueError
- C: 双声明且一致 → 通过
- D: 双声明且不一致 → ValueError
- E: 简单因子 required_columns 显式声明 → 不变（向后兼容）

集成一致性测试见 test_factor_spec_consistency.py。

作者: 云瑶
创建日期: 2026-06-16
"""

from __future__ import annotations

import pytest

from factor_ic.common.data_columns import JOIN_KEYS
from factor_ic.common.factor_spec import FACTOR_REGISTRY, FactorSpec, register_factor


@pytest.fixture(autouse=True)
def _clean_registry():
    """每个测试前后清空 FACTOR_REGISTRY，避免重复注册污染。"""
    saved = dict(FACTOR_REGISTRY)
    FACTOR_REGISTRY.clear()
    yield
    FACTOR_REGISTRY.clear()
    FACTOR_REGISTRY.update(saved)


def _make_calc(required_cols=None):
    """构造带 .required_cols 属性的伪 calculation 函数。"""

    def _calc(df, **kw):  # pragma: no cover - 测试不调用
        return df

    if required_cols is not None:
        _calc.required_cols = required_cols
    return _calc


# ---------------------------------------------------------------------------
# Case A: required_columns=None + calculation 有 .required_cols → 自动派生
# ---------------------------------------------------------------------------
def test_case_a_auto_derive_from_calculation():
    calc = _make_calc(required_cols=["close", "high", "low"])
    spec = FactorSpec(
        factor_name="kdj_j_test_a",
        factor_col="kdj_j",
        calculation=calc,
        # 不传 required_columns
    )
    assert spec.required_columns == JOIN_KEYS + ("close", "high", "low")


def test_case_a_calc_required_cols_already_contains_join_keys():
    """calculation.required_cols 含 JOIN_KEYS 时，派生不应重复。"""
    calc = _make_calc(required_cols=["date", "asset", "amplitude"])
    spec = FactorSpec(
        factor_name="industry_amp_trend_test",
        factor_col="industry_amplitude_trend",
        calculation=calc,
    )
    assert spec.required_columns == ("date", "asset", "amplitude")
    # 不应有重复 date/asset
    assert len(spec.required_columns) == len(set(spec.required_columns))


# ---------------------------------------------------------------------------
# Case B: required_columns=None + calculation 无 .required_cols → ValueError
# ---------------------------------------------------------------------------
def test_case_b_no_required_columns_no_calc_attr():
    calc = _make_calc(required_cols=None)  # 没有 .required_cols 属性
    with pytest.raises(ValueError, match=r"required_columns 未提供"):
        FactorSpec(
            factor_name="bad_test_b",
            factor_col="bad",
            calculation=calc,
        )


def test_case_b_no_required_columns_no_calculation():
    with pytest.raises(ValueError, match=r"required_columns 未提供"):
        FactorSpec(
            factor_name="bad_test_b2",
            factor_col="bad",
        )


# ---------------------------------------------------------------------------
# Case C: 双声明且一致 → 通过
# ---------------------------------------------------------------------------
def test_case_c_dual_declaration_consistent():
    calc = _make_calc(required_cols=["close", "high", "low"])
    spec = FactorSpec(
        factor_name="kdj_j_test_c",
        factor_col="kdj_j",
        required_columns=JOIN_KEYS + ("close", "high", "low"),
        calculation=calc,
    )
    assert spec.required_columns == JOIN_KEYS + ("close", "high", "low")


# ---------------------------------------------------------------------------
# Case D: 双声明且不一致 → ValueError
# ---------------------------------------------------------------------------
def test_case_d_dual_declaration_drift():
    calc = _make_calc(required_cols=["close", "high", "low"])
    with pytest.raises(ValueError, match=r"required_columns 与 calculation.required_cols 不一致"):
        FactorSpec(
            factor_name="bad_test_d",
            factor_col="kdj_j",
            # 漂移：少声明 low，且多声明产出列
            required_columns=JOIN_KEYS + ("close", "high", "kdj_j"),
            calculation=calc,
        )


def test_case_d_dual_declaration_drift_message_includes_both():
    """校验失败消息应同时包含两侧声明，便于排查。"""
    calc = _make_calc(required_cols=["amplitude"])
    with pytest.raises(ValueError) as exc_info:
        FactorSpec(
            factor_name="bad_test_d2",
            factor_col="industry_amplitude_trend",
            required_columns=JOIN_KEYS + ("amplitude", "industry_amplitude_trend"),
            calculation=calc,
        )
    msg = str(exc_info.value)
    assert "显式声明" in msg
    assert "派生" in msg


# ---------------------------------------------------------------------------
# Case E: 简单因子 required_columns 显式声明 → 不变（向后兼容）
# ---------------------------------------------------------------------------
def test_case_e_simple_factor_unchanged():
    """简单因子（无 calculation）保持显式声明 + factor_col ∈ required_columns 校验。"""
    spec = FactorSpec(
        factor_name="rsi_test_e",
        factor_col="rsi",
        required_columns=JOIN_KEYS + ("rsi",),
        calculation=None,
    )
    assert spec.required_columns == ("date", "asset", "rsi")
    register_factor(spec)
    assert "rsi_test_e" in FACTOR_REGISTRY


def test_case_e_simple_factor_factor_col_missing():
    """简单因子 factor_col 不在 required_columns → register_factor 报错。"""
    spec = FactorSpec(
        factor_name="rsi_test_e2",
        factor_col="rsi",
        required_columns=JOIN_KEYS + ("close",),  # 缺 rsi
        calculation=None,
    )
    with pytest.raises(ValueError, match=r"factor_col='rsi' 不在 required_columns"):
        register_factor(spec)


# ---------------------------------------------------------------------------
# 注册期既有校验回归测试
# ---------------------------------------------------------------------------
def test_register_factor_returns_same_spec():
    spec = FactorSpec(
        factor_name="reg_test_1",
        factor_col="x",
        required_columns=JOIN_KEYS + ("x",),
    )
    assert register_factor(spec) is spec


def test_register_factor_rejects_duplicate():
    spec = FactorSpec(factor_name="dup_test", factor_col="x", required_columns=JOIN_KEYS + ("x",))
    register_factor(spec)
    spec2 = FactorSpec(factor_name="dup_test", factor_col="x", required_columns=JOIN_KEYS + ("x",))
    with pytest.raises(ValueError, match=r"已注册"):
        register_factor(spec2)


def test_register_factor_rejects_duplicate_columns():
    """重复列由 _validate_spec（register 期）拦截。"""
    spec = FactorSpec(
        factor_name="dup_col_test",
        factor_col="x",
        required_columns=("date", "asset", "x", "x"),
    )
    with pytest.raises(ValueError, match=r"含重复列"):
        register_factor(spec)
