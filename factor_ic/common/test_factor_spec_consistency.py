#!/usr/bin/env python3
"""FactorSpec 集成一致性测试（§5.3）。

遍历当前已注册的 ic 脚本，验证：
1. 复杂因子（calculation 非空）若有 .required_cols：FactorSpec.required_columns 与
   calculation.required_cols 推导结果一致（防止双声明漂移）
2. calculator 模块中被任何 FactorSpec 引用的函数必须有 .required_cols 属性
   （未来漂移防御，遵循 §6 R5）

注意：本测试通过 importlib 加载 factor_ic.ic_*.py 触发 SPEC 注册，因此一次性
完成全量校验。

作者: 云瑶
创建日期: 2026-06-16
"""

from __future__ import annotations

import importlib
import pkgutil

import pytest

import factor_ic
from factor_ic.common.data_columns import JOIN_KEYS
from factor_ic.common.factor_spec import FACTOR_REGISTRY


def _load_all_factor_specs() -> None:
    """触发所有 factor_ic.ic_*.py 的模块级 SPEC = register_factor(...)。"""
    for mod in pkgutil.iter_modules(factor_ic.__path__):
        if mod.name.startswith("ic_"):
            importlib.import_module(f"factor_ic.{mod.name}")


@pytest.fixture(scope="module", autouse=True)
def _ensure_all_specs_loaded():
    _load_all_factor_specs()
    yield


def test_all_complex_factors_dual_declaration_consistent():
    """所有复杂因子若同时显式声明 required_columns，必须与 calculation.required_cols 推导一致。

    本测试是漂移防御：未来若有 PR 误改 required_columns 或 calculation.required_cols
    其中一侧而忘记同步另一侧，会被拦截。
    """
    inconsistencies: list[str] = []
    for name, spec in FACTOR_REGISTRY.items():
        calc = spec.calculation
        if calc is None:
            continue  # 简单因子跳过
        calc_cols = getattr(calc, "required_cols", None)
        if calc_cols is None:
            continue  # 未声明 .required_cols 的本地 calc 跳过（R3.2 后此分支应为空）
        expected = JOIN_KEYS + tuple(c for c in calc_cols if c not in JOIN_KEYS)
        if tuple(spec.required_columns) != expected:
            inconsistencies.append(f"  - {name}: required_columns={spec.required_columns} vs derived={expected}")
    assert not inconsistencies, "FactorSpec 双声明漂移:\n" + "\n".join(inconsistencies)


def test_all_complex_factor_calculations_have_required_cols():
    """R3.2 完成后，所有 ic 脚本引用的 calculation 函数必须声明 .required_cols。

    注意：本测试在 R3.2 完成前会出现 known failures（6 个脚本本地 calc 未补属性）。
    R3.2 完成后应全绿。

    标记 xfail 而非 skip：R3.2 落地后期望转 PASS，未补会持续提醒。
    """
    missing: list[str] = []
    for name, spec in FACTOR_REGISTRY.items():
        calc = spec.calculation
        if calc is None:
            continue
        if not hasattr(calc, "required_cols"):
            missing.append(f"  - {name}: calculation={calc.__module__}.{calc.__name__}")
    if missing:
        pytest.xfail("R3.2 未完成的 calc.required_cols 缺失:\n" + "\n".join(missing))
