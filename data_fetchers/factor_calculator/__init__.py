"""data_fetchers.factor_calculator 包：统一因子计算函数库。

历史背景
========
原为单文件 ``factor_calculator.py``（v1.0 - v1.17，2779 行）。
v2.0 (2026-06-15) 启动包化拆分（详见 ``designs/factor_calculator_split_design.md``）：
将单文件按业务域拆为 8 个子模块（_common / basic / momentum / delta /
volume_price / industry / industry_financial / fund_flow），通过本
``__init__.py`` 重导出，保证 80+ 处外部 ``from data_fetchers.factor_calculator
import ...`` 路径零修改。

PR-3 阶段（当前，2026-06-15）
==============================
- ``_common.py``：模块级常量 + fallback logger + ``get_module_logger`` + 4 个
  半公开 helper—— PR-2a 完成；PR-2c 新增 5 个动量族常量
- ``basic.py``：7 个基础技术指标因子—— PR-2b 完成
- ``momentum.py``：7 个价格 / 动量族因子—— PR-2c 完成
- **``delta.py``：4 个止跌信号差分族因子（``calculate_amplitude_delta`` /
  ``calculate_turnover_surge_delta`` / ``calculate_tail_price_position_delta`` /
  ``calculate_tail_volume_shrink_delta``）—— PR-3 新增**
- **``volume_price.py``：4 个量价合成族因子（``calculate_volume_price_strength`` /
  ``calculate_positive_day_ratio_5`` / ``calculate_ma5_deviation`` /
  ``calculate_near_high_ratio_5``）—— PR-3 新增**
- ``_legacy.py``：剩余 8 个 ``calculate_*`` 函数（PR-4 行业聚合族继续搬）；
  顶部以 ``from .basic`` / ``.momentum`` / ``.delta`` / ``.volume_price`` 4 段
  re-import 维持向后兼容
- 本 ``__init__.py`` 从 ``_common`` 直接重导出半公开 helper + 9 公共常量；
  从 ``_legacy`` ``import *`` 透出全量 ``calculate_*`` 函数（含已搬到子模块
  的函数，借由 _legacy re-import 路径透出，保持 ``__all__`` 单一来源）

兼容性契约（design.md §7.3）
==========================
本 ``__init__.py`` 必须重导出：
- 30 个公共因子函数（见 ``__all__``，``_legacy.py`` 持单一定义入口）
- 9 个公共常量别名（``DEFAULT_RSI_PERIOD`` 等，被 ``ic_kdj_j`` 等脚本 import）
- 5 个半公开 helper（``_per_asset_transform``、``_calculate_ewm_with_initial``、
  ``_calculate_delta``、``_wilder_smoothing_rsi``、``get_module_logger``）
"""

# ruff: noqa: F401, F403
# PR-2a：从 _common 直接重导出半公开 helper + 9 公共常量别名（避免经 _legacy 中转）
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

# 重导出全量公共因子函数（仍由 _legacy.py 持有，PR-2b 起逐步搬出至子模块；
# basic 子模块的 7 个函数借由 _legacy 顶部 `from .basic import (...)` 透出）
from ._legacy import *  # noqa: F401, F403

# 同步 __all__（从 _legacy 复用，保持 grep 命中等价）
from ._legacy import __all__ as __all__
