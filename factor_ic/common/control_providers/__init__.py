"""控制变量提供器（design.md §4.1 注册表）。

注册表驱动：
    from factor_ic.common.control_providers import build_providers
    providers = build_providers(["industry", "log_market_cap"])

新增 Provider 步骤：
    1. 在本目录新建 <name>.py 实现 ControlProvider 协议
    2. 在 PROVIDER_REGISTRY 注册 (name → 工厂)
    3. 不需要改任何调用方代码

参考: designs/feat_neutralization_framework.md §4.1
"""

from __future__ import annotations

from collections.abc import Callable

from .base import ControlProvider
from .industry import IndustryProvider


# Provider 工厂注册表：name → 无参工厂函数
# Provider 暂用无参构造（统一接口），需要参数时由 build_providers 显式分发或
# 升级为 (name, kwargs) 形式（design.md §4.1 演进路径）。
PROVIDER_REGISTRY: dict[str, Callable[[], ControlProvider]] = {
    "industry": IndustryProvider,
}


def build_providers(specs: list[str]) -> list[ControlProvider]:
    """根据 spec 字符串列表构造 Provider 实例。

    参数:
        specs: 形如 ["industry"] 或 ["industry", "log_market_cap"] 的列表
            空列表表示不做中性化（裸 IC）。

    返回:
        Provider 实例列表，顺序与 specs 一致。

    异常:
        KeyError: spec 名不在 PROVIDER_REGISTRY（错误消息含可选 key 列表）
        ValueError: specs 含重复 name（多控制变量需名字唯一）
    """
    if len(set(specs)) != len(specs):
        dups = [s for s in specs if specs.count(s) > 1]
        raise ValueError(f"build_providers: specs 含重复 name {set(dups)}; specs={specs}")

    providers: list[ControlProvider] = []
    for spec in specs:
        if spec not in PROVIDER_REGISTRY:
            raise KeyError(
                f"build_providers: 未注册的 control provider '{spec}'; 已注册: {sorted(PROVIDER_REGISTRY.keys())}"
            )
        providers.append(PROVIDER_REGISTRY[spec]())
    return providers


__all__ = [
    "PROVIDER_REGISTRY",
    "ControlProvider",
    "IndustryProvider",
    "build_providers",
]
