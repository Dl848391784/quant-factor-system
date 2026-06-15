"""data_fetchers.factor_calculator 包：统一因子计算函数库。

历史背景
========
原为单文件 ``factor_calculator.py``（v1.0 - v1.17，2779 行）。
v2.0 (2026-06-15) 启动包化拆分（详见 ``designs/factor_calculator_split_design.md``）：
将单文件按业务域拆为 8 个子模块（_common / basic / momentum / delta /
volume_price / industry / industry_financial / fund_flow），通过本
``__init__.py`` 重导出，保证 80+ 处外部 ``from data_fetchers.factor_calculator
import ...`` 路径零修改。

PR-1 阶段（当前）
================
- 包骨架已就位：``factor_calculator/`` 目录 + ``__init__.py``
- 旧实现整体重命名为 ``_legacy.py``（git mv，保留 blame 历史）
- 所有公共 API 与半公开 helper 通过 ``from ._legacy import *`` 转发
- 后续 PR-2 ~ PR-4 渐进把函数从 ``_legacy.py`` 搬到对应子模块；
  每搬一个就在本文件把 ``from ._legacy import xxx`` 改为 ``from .basic import xxx``
- PR-5 删除空的 ``_legacy.py``

兼容性契约（design.md §7.3）
==========================
本 ``__init__.py`` 必须重导出：
- 30 个公共因子函数（见 ``__all__``）
- 9 个公共常量别名（``DEFAULT_RSI_PERIOD`` 等，被 ``ic_kdj_j`` 等脚本 import）
- 5 个半公开 helper（``_per_asset_transform``、``_calculate_ewm_with_initial``、
  ``_calculate_delta``、``_wilder_smoothing_rsi``、``get_module_logger``）
"""

# ruff: noqa: F401, F403
# 重导出全量公共 + 半公开 API，"unused import" 是预期行为
from ._legacy import *  # 公共 API（受 _legacy.py 的 __all__ 约束）

# 同步 __all__（从 _legacy 复用，保持 grep 命中等价）
from ._legacy import __all__ as __all__

# 显式重导出半公开 helper（不在 _legacy.py 的 __all__ 里，需单独 import 才能让
# `from data_fetchers.factor_calculator import _per_asset_transform` 工作）
from ._legacy import (
    _calculate_delta,
    _calculate_ewm_with_initial,
    _per_asset_transform,
    _wilder_smoothing_rsi,
    get_module_logger,
)
