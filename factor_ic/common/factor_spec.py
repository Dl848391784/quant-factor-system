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

required_columns 自动派生（v1.1, 遵循 factor_spec_required_cols_and_sys_path_design.md §3.1 方案 3-A）：
- required_columns 为 None 且 calculation 拥有 .required_cols 属性 → 自动派生
- 派生公式：JOIN_KEYS + tuple(c for c in calculation.required_cols if c not in JOIN_KEYS)
- 双声明一致性校验：若 required_columns 与 calculation.required_cols 都提供，
  派生结果必须与显式声明一致（防漂移）

作者: 云瑶
创建日期: 2026-06-15
版本历史:
  v1.0 (2026-06-15): 落地 FactorSpec + register_factor + FACTOR_REGISTRY
  v1.1 (2026-06-16): required_columns 改为可选 + __post_init__ 自动派生 + 双声明一致性校验
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from factor_ic.common.data_columns import JOIN_KEYS


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
            - 简单因子(calculation=None): 必须显式声明
            - 复杂因子(calculation 有 .required_cols 属性): 可省略, 自动派生
            - 复杂因子若同时显式声明: 校验与 calculation.required_cols 推导结果一致
        calculation: 因子计算函数(None = 简单因子, 直接从缓存读取)
        calc_params_fn: 从 CLI args 提取计算参数的函数 → dict
        extra_log_params_fn: 从 CLI args 提取启动横幅扩展参数的函数 → dict
    """

    factor_name: str
    factor_col: str
    required_columns: tuple[str, ...] | None = None
    calculation: Callable | None = None
    calc_params_fn: Callable | None = None
    extra_log_params_fn: Callable | None = None

    def __post_init__(self) -> None:
        """L1.5 实例化期：required_columns 自动派生（方案 3-A）。

        派生策略：
        - required_columns is None 且 calculation 有 .required_cols → 自动派生
        - required_columns is None 且 calculation 无 .required_cols → ValueError
        - required_columns 显式声明 + calculation 有 .required_cols → 一致性校验
        - required_columns 显式声明 + calculation 无 .required_cols → 不变
        """
        calc_cols = getattr(self.calculation, "required_cols", None) if self.calculation else None

        if self.required_columns is None:
            # 必须能自动派生
            if calc_cols is None:
                raise ValueError(
                    f"FactorSpec({self.factor_name}) required_columns 未提供，"
                    f"且 calculation={self.calculation!r} 未声明 .required_cols 属性，无法自动派生"
                )
            derived = JOIN_KEYS + tuple(c for c in calc_cols if c not in JOIN_KEYS)
            # frozen dataclass 通过 object.__setattr__ 绕过冻结
            object.__setattr__(self, "required_columns", derived)
        elif calc_cols is not None:
            # 双声明 → 校验一致性
            expected = JOIN_KEYS + tuple(c for c in calc_cols if c not in JOIN_KEYS)
            if tuple(self.required_columns) != expected:
                raise ValueError(
                    f"FactorSpec({self.factor_name}) required_columns 与 calculation.required_cols 不一致：\n"
                    f"  显式声明: {tuple(self.required_columns)}\n"
                    f"  从 calculation 派生: {expected}\n"
                    f"  请删除 required_columns 参数（自动派生）或同步两侧声明"
                )


# ============================================================================
# 注册表
# ============================================================================

FACTOR_REGISTRY: dict[str, FactorSpec] = {}


# ============================================================================
# 注册失败专用异常（issue 4：附 factor_name 上下文供扫描层聚合错误）
# ============================================================================


class SpecRegistrationError(ValueError):
    """register_factor 注册失败专用异常。

    继承 ValueError 保证向后兼容（旧 `except (ValueError, TypeError)` 仍可 catch），
    携带 factor_name 上下文供扫描层（如 test_factor_spec_consistency.py / importlib
    批量扫描）从异常对象直接定位故障因子，无需再依赖日志 grep。

    设计要点（design v1.0 §4.1）：
    - 单一类型：register_factor 对外只抛 SpecRegistrationError，调用方 except 范围
      可从原 `(ValueError, TypeError)` 收窄为单一具名异常（issue 1）；
    - 异常聚合：__init__ 把 factor_name 拼进消息，str(e) 自带因子名前缀；
    - 向后兼容：继承 ValueError 而非 Exception，存量 16 文件未迁移期间旧 except
      仍可 catch，扩散过程零中断（详见 design v1.0 §3.1）。

    Attributes:
        factor_name: 注册失败的因子名（程序可访问的结构化字段）
    """

    def __init__(self, factor_name: str, message: str) -> None:
        self.factor_name = factor_name
        super().__init__(f"FactorSpec({factor_name}) 注册失败: {message}")


def register_factor(spec: FactorSpec) -> FactorSpec:
    """注册因子规格到全局注册表，并执行 L2 校验。

    Args:
        spec: FactorSpec 实例

    Returns:
        传入的 spec（便于模块级声明: SPEC = register_factor(FactorSpec(...))）

    Raises:
        SpecRegistrationError: L2 校验失败 / 注册期任何异常（含 factor_name 上下文）。
            继承自 ValueError，旧 `except ValueError` / `except (ValueError, TypeError)`
            仍可 catch，向后兼容。
    """
    try:
        _validate_spec(spec)
    except ValueError as e:
        # _validate_spec 抛 ValueError → 包装为 SpecRegistrationError 附 factor_name
        # （raise from e 保留原始 traceback，遵循 H6 异常链规则）
        raise SpecRegistrationError(spec.factor_name, str(e)) from e
    except Exception as e:
        # 防御 L2 校验流程中任何意外异常（AttributeError/RuntimeError/...），
        # 把 issue 1 描述的"绕过捕获块静默向上传播"路径堵死：所有路径都包装为
        # SpecRegistrationError，调用方一个 except 即可全覆盖。
        raise SpecRegistrationError(spec.factor_name, f"意外错误 ({type(e).__name__}): {e}") from e

    FACTOR_REGISTRY[spec.factor_name] = spec
    return spec


def _validate_spec(spec: FactorSpec) -> None:
    """L2 注册期校验：格式 + 语义规则。"""
    # 1. required_columns 非空（__post_init__ 后必非 None）
    if not spec.required_columns:
        raise ValueError(f"FactorSpec({spec.factor_name}) required_columns 不能为空")

    # 2. required_columns 无重复
    if len(set(spec.required_columns)) != len(spec.required_columns):
        raise ValueError(f"FactorSpec({spec.factor_name}) required_columns 含重复列: {spec.required_columns}")

    # 3. 全小写字母 + 数字 + 下划线 + 点(允许 rsi_6 / return_5d / forward_return_1d 等)
    for col in spec.required_columns:
        if not all(c.islower() or c.isdigit() or c == "_" or c == "." for c in col):
            raise ValueError(
                f"FactorSpec({spec.factor_name}) required_columns 列名 '{col}' 含非小写字母/数字/下划线/点字符"
            )

    # 4. factor_col 在 required_columns 中（仅简单因子；复杂因子有 calculation 时 factor_col 是计算产出，非输入依赖）
    if spec.calculation is None and spec.factor_col not in spec.required_columns:
        raise ValueError(
            f"FactorSpec({spec.factor_name}) factor_col='{spec.factor_col}' 不在 required_columns {spec.required_columns} 中"
        )

    # 5. 不可覆盖注册
    if spec.factor_name in FACTOR_REGISTRY:
        raise ValueError(f"FactorSpec factor_name='{spec.factor_name}' 已注册，不允许覆盖")
