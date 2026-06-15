#!/usr/bin/env python3
"""
FactorSpec 声明式注册

替代 34 个 ic 脚本中 factor_cols / factor_name / factor_col /
custom_factor_calculation / custom_factor_calculation_params /
extra_log_params 的分散字面量，统一为 frozen dataclass 声明。

三层防御：
- L1 编译期: mypy 类型检查 FactorSpec 字段
- L2 注册期: register_factor() 校验格式(非空/无重复/全小写/factor_col 在 required_columns 中)
- L3 运行时: validate_required_columns() 校验数据源列(DataSchemaError)

设计意图（遵循 factor_cols_literal_constant_design.md §3.1）：
- frozen dataclass 保证不可变
- _fn 后缀的 Callable 字段用于从 CLI args 提取参数，避免 dataclass 内含 args 引用
- FACTOR_REGISTRY 注册表提供全局查询能力

作者: 云瑶
创建日期: 2026-06-15
版本历史:
  v1.0 (2026-06-15): 落地 FactorSpec + register_factor + FACTOR_REGISTRY
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass


# ============================================================================
# FactorSpec dataclass
# ============================================================================


@dataclass(frozen=True)
class FactorSpec:
    """因子声明式注册规格。

    Attributes:
        factor_name: 因子名称(如 "amplitude_delta")
        factor_col: 因子列名(如 "amplitude_delta", 即 DataFrame 中的列名)
        required_columns: 需加载的原始因子列(含索引列 date/asset, 替代旧 factor_cols 参数)
        calculation: 因子计算函数(None = 简单因子, 直接从缓存读取)
        calc_params_fn: 从 CLI args 提取计算参数的函数 → dict
        extra_log_params_fn: 从 CLI args 提取启动横幅扩展参数的函数 → dict
    """

    factor_name: str
    factor_col: str
    required_columns: tuple[str, ...]
    calculation: Callable | None = None
    calc_params_fn: Callable | None = None
    extra_log_params_fn: Callable | None = None


# ============================================================================
# 注册表
# ============================================================================

FACTOR_REGISTRY: dict[str, FactorSpec] = {}


def register_factor(spec: FactorSpec) -> FactorSpec:
    """注册因子规格到全局注册表，并执行 L2 校验。

    Args:
        spec: FactorSpec 实例

    Returns:
        传入的 spec（便于模块级声明: SPEC = register_factor(FactorSpec(...))）

    Raises:
        ValueError: 校验失败
    """
    _validate_spec(spec)
    FACTOR_REGISTRY[spec.factor_name] = spec
    return spec


def _validate_spec(spec: FactorSpec) -> None:
    """L2 注册期校验：格式 + 语义规则。"""
    # 1. required_columns 非空
    if not spec.required_columns:
        raise ValueError(f"FactorSpec({spec.factor_name}) required_columns 不能为空")

    # 2. required_columns 无重复
    if len(set(spec.required_columns)) != len(spec.required_columns):
        raise ValueError(f"FactorSpec({spec.factor_name}) required_columns 含重复列: {spec.required_columns}")

    # 3. 全小写 + 下划线 + 点(允许 tail_price_position 等)
    for col in spec.required_columns:
        if not all(c.islower() or c == "_" or c == "." for c in col):
            raise ValueError(f"FactorSpec({spec.factor_name}) required_columns 列名 '{col}' 含非小写/下划线/点字符")

    # 4. factor_col 在 required_columns 中
    if spec.factor_col not in spec.required_columns:
        raise ValueError(
            f"FactorSpec({spec.factor_name}) factor_col='{spec.factor_col}' 不在 required_columns {spec.required_columns} 中"
        )

    # 5. 不可覆盖注册
    if spec.factor_name in FACTOR_REGISTRY:
        raise ValueError(f"FactorSpec factor_name='{spec.factor_name}' 已注册，不允许覆盖")
