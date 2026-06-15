"""data_fetchers.factor_calculator 包：统一因子计算函数库。

历史背景
========
原为单文件 ``factor_calculator.py``（v1.0 - v1.17，2779 行）。
v2.0 (2026-06-15) 启动包化拆分（详见 ``designs/factor_calculator_split_design.md``）：
将单文件按业务域拆为 8 个子模块（_common / basic / momentum / delta /
volume_price / industry / industry_financial / fund_flow），通过本
``__init__.py`` 重导出，保证 80+ 处外部 ``from data_fetchers.factor_calculator
import ...`` 路径零修改。

PR-2a 阶段（当前，2026-06-15）
==============================
- 模块级常量 + fallback logger + ``get_module_logger`` 已搬入 ``_common.py``
- 4 个半公开 helper（``_wilder_smoothing_rsi`` / ``_per_asset_transform`` /
  ``_calculate_ewm_with_initial`` / ``_calculate_delta``）已搬入 ``_common.py``
- ``_legacy.py`` 在顶部以 ``from ._common import (...)`` 引入这些符号，
  其余 22 个 ``calculate_*`` 公共因子函数仍在 ``_legacy.py``（PR-2b/2c 起搬）
- 本 ``__init__.py`` 直接从 ``_common`` 重导出半公开 helper + 9 个公共常量别名，
  避免 ``_common → _legacy → __init__`` 的迂回链
- PR-5 删除空的 ``_legacy.py``

兼容性契约（design.md §7.3）
==========================
本 ``__init__.py`` 必须重导出：
- 30 个公共因子函数（见 ``__all__``，仍由 ``_legacy.py`` 提供）
- 9 个公共常量别名（``DEFAULT_RSI_PERIOD`` 等，被 ``ic_kdj_j`` 等脚本 import）
- 5 个半公开 helper（``_per_asset_transform``、``_calculate_ewm_with_initial``、
  ``_calculate_delta``、``_wilder_smoothing_rsi``、``get_module_logger``）
"""

# ruff: noqa: F401, F403
# 重导出全量公共因子函数（仍由 _legacy.py 持有，PR-2b 起逐步搬出）
# 显式重导出半公开 helper（不在 __all__ 里，需单独 import 才能让
# ``from data_fetchers.factor_calculator import _per_asset_transform`` 工作）
# PR-2a：直接从 _common 重导出，避免经 _legacy 中转
# 公共常量别名（被 ic_kdj_j 等下游脚本 import，PR-2a 起从 _common 直接重导出）
from ._common import (
    DEFAULT_BOLLINGER_K,
    DEFAULT_BOLLINGER_N,
    DEFAULT_FORWARD_RETURN_SHIFT,
    DEFAULT_KDJ_M1,
    DEFAULT_KDJ_M2,
    DEFAULT_KDJ_N,
    DEFAULT_RSI_PERIOD,
    DEFAULT_SURGE_WINDOW,
    DEFAULT_VOLUME_RATIO_WINDOW,
    _calculate_delta,
    _calculate_ewm_with_initial,
    _per_asset_transform,
    _wilder_smoothing_rsi,
    get_module_logger,
)
from ._legacy import *  # noqa: F401, F403

# 同步 __all__（从 _legacy 复用，保持 grep 命中等价）
from ._legacy import __all__ as __all__
