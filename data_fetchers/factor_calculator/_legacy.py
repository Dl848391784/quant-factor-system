#!/usr/bin/env python3
"""
因子计算模块 - 统一因子计算逻辑

整合所有因子计算函数，提供单一数据源：
- RSI（Wilder 标准）
- Volume Ratio（量比）
- Bollinger %B（布林带）
- KDJ J（随机指标）
- Turnover Surge（换手率突增）

遵循 PROJECT.md 规范：
- 使用 Python 标准库 logging 模块
- 公共模块函数接收 logger 参数
- 函数入口必须先 .copy()，避免修改原始数据

版本历史：
- v1.0 (2026-05-27): 初始版本
  - 导入分组规范化（标准库/第三方库/类型导入）
  - logger 参数化（使用 logger_arg 命名）
  - __all__ 修复（移除私有函数）
  - docstring Example 补全（6个公共函数）
  - 流程文档创建 docs/factor_calculator_flow.md
  - 测试文件创建 test_cases/test_factor_calculator.py
- v1.1 (2026-05-27): 第二轮深度优化
  - 版本历史添加（参考 cache_manager.py）
  - 常量命名私有化 DEFAULT_* → _DEFAULT_*
  - __all__ 移到导入后位置（遵循 cache_manager.py 规范）
- v1.2 (2026-05-27): 第三轮深度优化
  - 内部函数 `_calculate_ewm_with_initial` docstring 补全（Args/Returns/Note）
  - 新增私有常量 `_DEFAULT_VOLUME_RATIO_WINDOW`、`_DEFAULT_FORWARD_RETURN_SHIFT`
  - 消除硬编码默认值（window=5、shift=1）
- v1.3 (2026-05-27): 第四轮深度优化
  - 提取输入列名常量（`_COL_CLOSE`、`_COL_DATE`、`_COL_ASSET`、`_COL_HIGH`、`_COL_LOW`、`_COL_TURNOVER_RATE`）
  - 提取输出列名常量（`_COL_BOLLINGER_PB`、`_COL_KDJ_J`、`_COL_TURNOVER_SURGE`）
  - 提取魔法数字常量（`_RSI_NEUTRAL_VALUE`、`_RSI_MAX_VALUE`、`_BOLLINGER_NEUTRAL_VALUE`、`_KD_NEUTRAL_VALUE`）
  - 提取业务阈值常量（`_TURNOVER_SURGE_THRESHOLD`、`_DAILY_RETURN_THRESHOLD`）
  - 消除所有硬编码字符串和魔法数字
- v1.4 (2026-05-27): 第五轮深度优化（8个问题修复）
  - 问题1（已不存在）：if _logger: 无效判断在当前代码中不存在
  - 问题2：删除 calculate_rsi 末尾 fillna，保留前 period 天 NaN 让调用方自行处理
  - 问题3：calculate_rsi/volume_ratio/forward_return 三个 Series 函数入口添加 .copy()
  - 问题4：_calculate_ewm_with_initial 删除 ignore_index=True，保留原始索引
  - 问题5：EPSILON → _EPSILON 私有化并从 __all__ 移除
  - 问题6：calculate_bollinger_pb safe_band_width 计算改用 where+clip（mask 对 NaN 无效）
  - 问题7：calculate_bollinger_pb 异常处理顺序调整（先 abnormal 后 narrow）
  - 问题8：calculate_turnover_surge 业务筛选日志改为 debug 级别（非异常统计）
- v1.5 (2026-05-27): 删除换手率突增筛选条件
  - 移除 `_TURNOVER_SURGE_THRESHOLD` 和 `_DAILY_RETURN_THRESHOLD` 常量
  - 移除涨跌幅计算和业务筛选逻辑（surge>1 且 return>0）
  - 所有有效计算的因子值均保留，不再筛选
- v1.6 (2026-05-29): 新增全天价格位置因子
  - 添加 `calculate_price_position()` 函数
  - 添加 `_COL_PRICE_POSITION` 和 `_DEFAULT_PRICE_POSITION_EPSILON` 常量
  - 边界处理：振幅为零时设为 0.5（中位）
v1.7 (2026-05-29): 新增振幅因子
  - 添加 `calculate_amplitude()` 函数
  - 添加 `_COL_AMPLITUDE` 和 `_DEFAULT_AMPLITUDE_EPSILON` 常量
  - 边界处理：close=0 时设为 NaN（无效数据）
v1.8 (2026-05-29): 新增3日累计涨幅因子
  - 添加 `calculate_return_3d()` 函数
  - 添加 `_COL_RETURN_3D` 和 `_DEFAULT_RETURN_3D_WINDOW` 常量
  - 边界处理：前3日数据设为 NaN（历史不足）
v1.9 (2026-05-29): 新增5日累计涨幅因子
  - 添加 `calculate_return_5d()` 函数
  - 添加 `_COL_RETURN_5D` 和 `_DEFAULT_RETURN_5D_WINDOW` 常量
  - 边界处理：前5日数据设为 NaN（历史不足）
v1.10 (2026-06-05): 新增动量强度因子
  - 添加 `calculate_momentum_strength()` 函数
  - 添加 `_COL_MOMENTUM_STRENGTH` 和 `_DEFAULT_MOMENTUM_STRENGTH_WINDOW` 常量
  - 公式：momentum_strength = return_5d / std(return_1d, 5日)
  - 边界处理：std=0 → NaN（除零保护），前5日 → NaN（rolling window 不足）
v1.13 (2026-06-11): 新增止跌信号差分因子（4个）
  - 添加 `_calculate_delta()` 通用差分辅助函数
  - 添加 `calculate_amplitude_delta()` 振幅差分因子
  - 添加 `calculate_turnover_surge_delta()` 换手突增差分因子
  - 添加 `calculate_tail_price_position_delta()` 尾盘位置差分因子
  - 添加 `calculate_tail_volume_shrink_delta()` 尾盘缩量差分因子
  - 添加4个输出列名常量（_COL_*_DELTA）
  - 遵循 H5: IC方向不预判，由数据决定

作者: 云瑶
创建日期: 2026-05-27
"""

# ============================================================================
# 标准库导入
# ============================================================================
import logging
from pathlib import Path

# ============================================================================
# 类型导入
# ============================================================================
# ============================================================================
# 第三方库导入
# ============================================================================
import pandas as pd

# ============================================================================
# 包内底座 import（PR-2a：常量、logger、半公开 helper 已抽至 _common）
# ============================================================================
# ============================================================================
# _add_industry_column helper：PR-4a 后已搬到 _common.py（行业类因子共享 helper）；
# 本文件中仍保留的 5 个 industry/fund_flow 函数通过下方 import 继续使用。
# ============================================================================
from ._common import (  # noqa: F401  允许此模块 re-export 这些符号
    _BOLLINGER_NEUTRAL_VALUE,
    _COL_AMPLITUDE,
    _COL_AMPLITUDE_DELTA,
    _COL_ASSET,
    _COL_BOLLINGER_PB,
    _COL_CLOSE,
    _COL_DATE,
    _COL_HIGH,
    _COL_INDUSTRY_AMPLITUDE_TREND,
    _COL_INDUSTRY_EARNINGS_GROWTH,
    _COL_INDUSTRY_MOMENTUM_5D,
    _COL_INDUSTRY_PE_TREND,
    _COL_INDUSTRY_ROE_TREND,
    _COL_INDUSTRY_TURNOVER_TREND,
    _COL_KDJ_J,
    _COL_LOW,
    _COL_MA5_DEVIATION,
    _COL_NEAR_HIGH_RATIO_5,
    _COL_OPEN,
    _COL_PAST_RETURN_1D,
    _COL_POSITIVE_DAY_RATIO_5,
    _COL_PRICE_POSITION,
    _COL_RETURN_3D,
    _COL_RETURN_5D,
    _COL_TAIL_PRICE_POSITION_DELTA,
    _COL_TAIL_VOLUME_SHRINK_DELTA,
    _COL_TURNOVER_RATE,
    _COL_TURNOVER_SURGE,
    _COL_TURNOVER_SURGE_DELTA,
    _COL_VOLUME_PRICE_STRENGTH,
    _DEFAULT_AMPLITUDE_EPSILON,
    _DEFAULT_AMPLITUDE_TREND_DENOMINATOR_MIN,
    _DEFAULT_BOLLINGER_K,
    _DEFAULT_BOLLINGER_N,
    _DEFAULT_FORWARD_RETURN_SHIFT,
    _DEFAULT_INDUSTRY_WINDOW,
    _DEFAULT_KDJ_M1,
    _DEFAULT_KDJ_M2,
    _DEFAULT_KDJ_N,
    _DEFAULT_MIN_INDUSTRY_STOCKS,
    _DEFAULT_PAST_RETURN_1D_WINDOW,
    _DEFAULT_PRICE_POSITION_EPSILON,
    _DEFAULT_RETURN_3D_WINDOW,
    _DEFAULT_RETURN_5D_WINDOW,
    _DEFAULT_RSI_PERIOD,
    _DEFAULT_SURGE_WINDOW,
    _DEFAULT_TREND_DENOMINATOR_MIN,
    _DEFAULT_VOLUME_RATIO_WINDOW,
    _EPSILON,
    _KD_NEUTRAL_VALUE,
    _MODULE_LOGGER,
    _RSI_MAX_VALUE,
    _RSI_NEUTRAL_VALUE,
    DEFAULT_BOLLINGER_K,
    DEFAULT_BOLLINGER_N,
    DEFAULT_FORWARD_RETURN_SHIFT,
    DEFAULT_KDJ_M1,
    DEFAULT_KDJ_M2,
    DEFAULT_KDJ_N,
    DEFAULT_RSI_PERIOD,
    DEFAULT_SURGE_WINDOW,
    DEFAULT_VOLUME_RATIO_WINDOW,
    _add_industry_column,  # noqa: F401
    _calculate_delta,
    _calculate_ewm_with_initial,
    _per_asset_transform,
    _wilder_smoothing_rsi,
    get_module_logger,
)

# ============================================================================
# 子模块 basic re-import（PR-2b：basic 因子已搬到 .basic，本文件 re-export 维持
# `from ._legacy import *` 通配兼容 + __all__ 中 7 个 calculate_* 名称仍有效）
# ============================================================================
from .basic import (  # noqa: F401
    calculate_bollinger_pb,
    calculate_forward_return,
    calculate_kdj_j,
    calculate_rsi,
    calculate_rsi_df,
    calculate_turnover_surge,
    calculate_volume_ratio,
)

# ============================================================================
# 子模块 delta re-import（PR-3：止跌信号差分族 4 个因子已搬到 .delta）
# ============================================================================
from .delta import (  # noqa: F401
    calculate_amplitude_delta,
    calculate_tail_price_position_delta,
    calculate_tail_volume_shrink_delta,
    calculate_turnover_surge_delta,
)

# ============================================================================
# 子模块 industry re-import（PR-4a：行业聚合 3 个因子已搬到 .industry）
# ============================================================================
from .industry import (  # noqa: F401
    calculate_industry_amplitude_trend,
    calculate_industry_momentum_5d,
    calculate_industry_turnover_trend,
)

# ============================================================================
# 子模块 momentum re-import（PR-2c：动量族因子已搬到 .momentum，本文件 re-export
# 维持 `from ._legacy import *` 通配兼容 + __all__ 中名称仍有效）
# ============================================================================
from .momentum import (  # noqa: F401
    calculate_amplitude,
    calculate_momentum_strength,
    calculate_overnight_return,
    calculate_past_return_1d,
    calculate_price_position,
    calculate_return_3d,
    calculate_return_5d,
)

# ============================================================================
# 子模块 volume_price re-import（PR-3：量价合成族 4 个因子已搬到 .volume_price）
# ============================================================================
from .volume_price import (  # noqa: F401
    calculate_ma5_deviation,
    calculate_near_high_ratio_5,
    calculate_positive_day_ratio_5,
    calculate_volume_price_strength,
)


# ============================================================================
# 模块导出（遵循 MODULE.md 约束 60：不含私有名称）
# ============================================================================
__all__ = [
    "calculate_rsi",
    "calculate_volume_ratio",
    "calculate_forward_return",
    "calculate_bollinger_pb",
    "calculate_kdj_j",
    "calculate_turnover_surge",
    "calculate_price_position",  # v1.6 新增
    "calculate_amplitude",  # v1.7 新增
    "calculate_past_return_1d",  # v1.10 新增
    "calculate_return_3d",  # v1.8 新增
    "calculate_return_5d",  # v1.9 新增
    "calculate_momentum_strength",  # v1.10 新增
    "calculate_overnight_return",  # v1.11 新增
    "calculate_rsi_df",  # v1.12 新增
    "calculate_amplitude_delta",  # v1.13 新增
    "calculate_turnover_surge_delta",  # v1.13 新增
    "calculate_tail_price_position_delta",  # v1.13 新增
    "calculate_tail_volume_shrink_delta",  # v1.13 新增
    "calculate_volume_price_strength",  # v1.14 新增：量价齐升因子
    "calculate_positive_day_ratio_5",  # v1.14 新增：5日阳线比例因子
    "calculate_ma5_deviation",  # v1.14 新增：5日均线偏离度因子
    "calculate_near_high_ratio_5",  # v1.14 新增：近5日高低位置因子
    "calculate_industry_momentum_5d",  # v1.15 新增：行业5日动量因子
    "calculate_industry_turnover_trend",  # v1.15 新增：行业换手率趋势因子
    "calculate_industry_amplitude_trend",  # v1.15 新增：行业振幅趋势因子
    "calculate_industry_roe_trend",  # v1.16 新增：行业ROE趋势因子
    "calculate_industry_earnings_growth",  # v1.16 新增：行业盈利增长因子
    "calculate_industry_pe_trend",  # v1.16 新增：行业PE趋势因子
    "calculate_capital_flow_ratio_trend",  # v1.17 新增：资金流占比趋势因子（方案C）
    "calculate_capital_flow_intensity",  # v1.17 新增：资金流强度因子（方案C）
    # 公共常量别名（向下兼容 ic_kdj_j 等脚本的导入）
    "DEFAULT_RSI_PERIOD",
    "DEFAULT_BOLLINGER_N",
    "DEFAULT_BOLLINGER_K",
    "DEFAULT_KDJ_N",
    "DEFAULT_KDJ_M1",
    "DEFAULT_KDJ_M2",
    "DEFAULT_SURGE_WINDOW",
    "DEFAULT_VOLUME_RATIO_WINDOW",
    "DEFAULT_FORWARD_RETURN_SHIFT",
]

# ============================================================================
# 模块级常量、fallback logger 与 get_module_logger 已迁移至 _common（PR-2a，design.md §5.1）
# 本文件通过顶部 `from ._common import (...)` re-bind，原定义已删除
# ============================================================================


# ============================================================================
# RSI 计算（Wilder 标准）
# 半公开 helper `_wilder_smoothing_rsi` 已迁移至 _common（PR-2a）
# ============================================================================


# (PR-2b) calculate_rsi: 已迁移至 .basic 子模块（design.md §5.2）；
# 由本文件顶部 `from .basic import calculate_rsi` 维持向后兼容。


# ============================================================================
# Volume Ratio 计算（量比）
# ============================================================================


# (PR-2b) calculate_volume_ratio: 已迁移至 .basic 子模块（design.md §5.2）；
# 由本文件顶部 `from .basic import calculate_volume_ratio` 维持向后兼容。


# ============================================================================
# Forward Return 计算（前瞻收益）
# ============================================================================


# (PR-2b) calculate_forward_return: 已迁移至 .basic 子模块（design.md §5.2）；
# 由本文件顶部 `from .basic import calculate_forward_return` 维持向后兼容。


# ============================================================================
# 通用工具：按 asset 分组的低内存 transform 替代
# 半公开 helper `_per_asset_transform` 已迁移至 _common（PR-2a）
# ============================================================================


# ============================================================================
# Bollinger %B 计算（布林带）
# ============================================================================


# (PR-2b) calculate_bollinger_pb: 已迁移至 .basic 子模块（design.md §5.2）；
# 由本文件顶部 `from .basic import calculate_bollinger_pb` 维持向后兼容。


# ============================================================================
# KDJ J 计算（随机指标）
# 半公开 helper `_calculate_ewm_with_initial` 已迁移至 _common（PR-2a）
# ============================================================================


# (PR-2b) calculate_kdj_j: 已迁移至 .basic 子模块（design.md §5.2）；
# 由本文件顶部 `from .basic import calculate_kdj_j` 维持向后兼容。


# ============================================================================
# Turnover Surge 计算（换手率突增）
# ============================================================================


# (PR-2b) calculate_turnover_surge: 已迁移至 .basic 子模块（design.md §5.2）；
# 由本文件顶部 `from .basic import calculate_turnover_surge` 维持向后兼容。


# ============================================================================
# 全天价格位置因子
# ============================================================================


# (PR-2c) calculate_price_position: 已迁移至 .momentum 子模块（design.md §5.3）；
# 由本文件顶部 `from .momentum import calculate_price_position` 维持向后兼容。


# ============================================================================
# 振幅因子计算
# ============================================================================


# (PR-2c) calculate_amplitude: 已迁移至 .momentum 子模块（design.md §5.3）；
# 由本文件顶部 `from .momentum import calculate_amplitude` 维持向后兼容。


# 振幅因子所需输入列（供调用方读取，避免硬编码耦合）
# pyright: ignore[reportFunctionMemberAccess]


# ============================================================================
# 1日涨幅因子计算
# ============================================================================


# (PR-2c) calculate_past_return_1d: 已迁移至 .momentum 子模块（design.md §5.3）；
# 由本文件顶部 `from .momentum import calculate_past_return_1d` 维持向后兼容。


# ============================================================================
# 3日累计涨幅因子计算
# ============================================================================


# (PR-2c) calculate_return_3d: 已迁移至 .momentum 子模块（design.md §5.3）；
# 由本文件顶部 `from .momentum import calculate_return_3d` 维持向后兼容。


# ============================================================================
# 5日累计涨幅因子计算
# ============================================================================


# (PR-2c) calculate_return_5d: 已迁移至 .momentum 子模块（design.md §5.3）；
# 由本文件顶部 `from .momentum import calculate_return_5d` 维持向后兼容。


# ============================================================================
# 因子所需输入列（供调用方读取，避免硬编码耦合）
# ============================================================================

# 已添加：calculate_amplitude.required_cols = ['close', 'high', 'low']


# (PR-2c) calculate_momentum_strength: 已迁移至 .momentum 子模块（design.md §5.3）；
# 由本文件顶部 `from .momentum import calculate_momentum_strength` 维持向后兼容。


# (PR-2c) calculate_overnight_return: 已迁移至 .momentum 子模块（design.md §5.3）；
# 由本文件顶部 `from .momentum import calculate_overnight_return` 维持向后兼容。


# ============================================================================
# RSI DataFrame 版本（用于分层回测）
# ============================================================================


# (PR-2b) calculate_rsi_df: 已迁移至 .basic 子模块（design.md §5.2）；
# 由本文件顶部 `from .basic import calculate_rsi_df` 维持向后兼容。


# ============================================================================
# 止跌信号差分因子（Reversal Delta Factors）
# v1.13 (2026-06-11): 新增4个差分因子
#   - amplitude_delta: 振幅变化（止跌放量信号）
#   - turnover_surge_delta: 换手突增变化（关注回升信号）
#   - tail_price_position_delta: 尾盘位置变化（买盘进场信号）
#   - tail_volume_shrink_delta: 尾盘缩量变化（资金介入信号）
#
# 通用计算模式：base_col(T) - base_col(T-1)，按asset分组shift(1)
# 遵循 H5: 因子方向不预判，IC方向由数据决定
# 半公开 helper `_calculate_delta` 已迁移至 _common（PR-2a）
# ============================================================================


# (PR-3) calculate_amplitude_delta: 已迁移至 .delta / .volume_price 子模块（design.md §5.4-5.5）；
# 由本文件顶部 `from .delta import calculate_amplitude_delta` 维持向后兼容。


# (PR-3) calculate_turnover_surge_delta: 已迁移至 .delta / .volume_price 子模块（design.md §5.4-5.5）；
# 由本文件顶部 `from .delta import calculate_turnover_surge_delta` 维持向后兼容。


# (PR-3) calculate_tail_price_position_delta: 已迁移至 .delta / .volume_price 子模块（design.md §5.4-5.5）；
# 由本文件顶部 `from .delta import calculate_tail_price_position_delta` 维持向后兼容。


# (PR-3) calculate_tail_volume_shrink_delta: 已迁移至 .delta / .volume_price 子模块（design.md §5.4-5.5）；
# 由本文件顶部 `from .delta import calculate_tail_volume_shrink_delta` 维持向后兼容。


# ============================================================================
# 方向性因子（Directional Factors）
# v1.14 (2026-06-11): 新增4个方向性因子
#   - volume_price_strength: 量价齐升强度（上涨+放量=强势）
#   - positive_day_ratio_5: 近5日阳线比例（趋势连续性）
#   - ma5_deviation: 5日均线偏离度（趋势位置）
#   - near_high_ratio_5: 近5日高低位置（相对强弱）
#
# 设计目的：与现有均值回归因子（IC负向偏好弱势股）形成维度互补
# 遵循 H5: IC方向不预判，由数据决定
# ============================================================================


# (PR-3) calculate_volume_price_strength: 已迁移至 .delta / .volume_price 子模块（design.md §5.4-5.5）；
# 由本文件顶部 `from .volume_price import calculate_volume_price_strength` 维持向后兼容。


# (PR-3) calculate_positive_day_ratio_5: 已迁移至 .delta / .volume_price 子模块（design.md §5.4-5.5）；
# 由本文件顶部 `from .volume_price import calculate_positive_day_ratio_5` 维持向后兼容。


# (PR-3) calculate_ma5_deviation: 已迁移至 .delta / .volume_price 子模块（design.md §5.4-5.5）；
# 由本文件顶部 `from .volume_price import calculate_ma5_deviation` 维持向后兼容。


# (PR-3) calculate_near_high_ratio_5: 已迁移至 .delta / .volume_price 子模块（design.md §5.4-5.5）；
# 由本文件顶部 `from .volume_price import calculate_near_high_ratio_5` 维持向后兼容。


# ============================================================================
# 行业级别方向性因子（Pattern 14: Industry-Level Directional Factor）
# ============================================================================
#
# 核心认知：方向性信号在行业层面而非个股层面。
# 因子值 = 行业聚合值赋给该行业每只个股（同行业股票因子值相同）。
# 遵循 H5：IC方向不预判，即使IC为负仍有维度互补价值。
# 比率型因子分母保护：遵循 Pitfall #47（clip下限避免极端值）。
# ============================================================================


# (PR-4a) _add_industry_column: 已迁移至 ._common 模块（被多个 industry/fund_flow 函数共享）；
# 由本文件顶部 `from ._common import _add_industry_column` 维持向后兼容。


# (PR-4a) calculate_industry_momentum_5d: 已迁移至 .industry 子模块（design.md §5.6）；
# 由本文件顶部 `from .industry import calculate_industry_momentum_5d` 维持向后兼容。


# (PR-4a) calculate_industry_turnover_trend: 已迁移至 .industry 子模块（design.md §5.6）；
# 由本文件顶部 `from .industry import calculate_industry_turnover_trend` 维持向后兼容。


# (PR-4a) calculate_industry_amplitude_trend: 已迁移至 .industry 子模块（design.md §5.6）；
# 由本文件顶部 `from .industry import calculate_industry_amplitude_trend` 维持向后兼容。


# ============================================================================
# 行业基本面动量因子（Pattern 14 + 基本面维度，v1.16 2026-06-12）
# 数据来源: financial_data.json.gz（akshare stock_financial_abstract_ths）
# 季度数据 → merge_asof 前推填充对齐日频 → 行业聚合赋个股
# ============================================================================

# 行业财务因子列名常量已迁移至 _common（PR-2a，design.md §5.1）：
#   _COL_INDUSTRY_ROE_TREND / _COL_INDUSTRY_EARNINGS_GROWTH / _COL_INDUSTRY_PE_TREND

# 财务数据缓存路径（遵循 paths.py 单一来源）
_FINANCIAL_DATA_PATH: str | None = None  # 默认 None，调用时从 paths.py 获取

# PE 比率型因子分母保护（遵循 Pitfall #47）
_PE_DENOMINATOR_MIN = 0.01  # EPS 年化值 clip 下限


def _get_financial_data_path(logger_arg: logging.Logger | None = None) -> Path:
    """获取财务数据缓存路径（遵循 paths.py 单一来源）

    Returns:
        财务数据缓存文件路径
    """
    global _FINANCIAL_DATA_PATH
    if _FINANCIAL_DATA_PATH is not None:
        return Path(_FINANCIAL_DATA_PATH)
    try:
        from data_fetchers.common import get_module_result_dir
    except ImportError:
        from common import get_module_result_dir
    result_dir = get_module_result_dir()
    _FINANCIAL_DATA_PATH = str(result_dir / "financial_data.json.gz")
    return Path(_FINANCIAL_DATA_PATH)


def _load_financial_data(
    financial_data_path: Path | str | None = None,
    logger_arg: logging.Logger | None = None,
) -> pd.DataFrame:
    """加载财务数据缓存，返回 DataFrame（asset, report_date, roe, eps, ...）

    Args:
        financial_data_path: 财务数据缓存路径（None 时使用默认路径）
        logger_arg: 调用方传入的 logger（可选）

    Returns:
        财务数据 DataFrame，包含 asset, report_date, roe, basic_eps, annualized_eps 等列

    Raises:
        FileNotFoundError: 缓存文件不存在
        RuntimeError: 缓存数据为空或格式错误
    """
    _logger = get_module_logger(logger_arg)

    path = Path(financial_data_path) if financial_data_path else _get_financial_data_path(logger_arg)
    if not path.exists():
        raise FileNotFoundError(f"财务数据缓存不存在: {path}，请先运行 fetch_financial.py")

    import gzip
    import json

    with gzip.open(path, "rt") as f:
        raw_data = json.load(f)

    data_list = raw_data.get("data", [])
    if not data_list:
        raise RuntimeError(f"财务数据缓存为空: {path}")

    df = pd.DataFrame(data_list)

    # 确保关键列存在
    required_cols = ["asset", "report_date"]
    missing = [c for c in required_cols if c not in df.columns]
    if missing:
        raise RuntimeError(f"财务数据缺少必需列: {missing}")

    # 显式释放 JSON 原始数据（遵循 R16）
    del raw_data, data_list
    import gc

    gc.collect()

    _logger.info("加载财务数据: %d 条记录, %d 只股票", len(df), len(set(df["asset"])))
    return df


def _merge_asof_financial(
    factor_df: pd.DataFrame,
    financial_df: pd.DataFrame,
    value_col: str,
    output_col: str,
    logger_arg: logging.Logger | None = None,
) -> pd.Series:
    """前推填充对齐季度财务数据到日频（merge_asof 模式）

    Args:
        factor_df: 日频因子 DataFrame（含 date, asset 列）
        financial_df: 季度财务 DataFrame（含 asset, report_date, value_col 列）
        value_col: 财务数据中的值列名（如 'roe', 'basic_eps'）
        output_col: 输出到 factor_df 的列名（如 'roe_daily', 'eps_daily'）
        logger_arg: logger（可选）

    Returns:
        与 factor_df 行数对齐的 Series，前推填充的财务值

    Note: 使用 pd.merge_asof(direction='backward') 实现 point-forward fill
    """
    _logger = get_module_logger(logger_arg)

    # 准备合并所需的数据
    fin_subset = financial_df[["asset", "report_date", value_col]].copy()
    fin_subset = fin_subset.rename(columns={"report_date": "date"})
    fin_subset["date"] = pd.to_datetime(fin_subset["date"])

    # 确保 factor_df 的 date 列是 datetime 类型
    daily_dates = pd.to_datetime(factor_df[_COL_DATE])

    # merge_asof: 交易日取最近已发布的财报数据（前推填充）
    merged = pd.merge_asof(
        factor_df[[_COL_ASSET]].assign(date=daily_dates).sort_values("date"),
        fin_subset.sort_values("date"),
        by=_COL_ASSET,
        on="date",
        direction="backward",  # Point-forward: 取最近已发布的财报
    )

    return merged[value_col].rename(output_col)


def calculate_industry_roe_trend(
    factor_df: pd.DataFrame,
    *,
    financial_data_path: str | Path | None = None,
    logger_arg: logging.Logger | None = None,
) -> pd.DataFrame:
    """计算行业ROE趋势因子（行业ΔROE赋个股）

    公式:
      1. 加载季度财务数据 → ROE per (asset, report_date)
      2. Point-forward fill → 对齐日频 (merge_asof direction='backward')
      3. ΔROE = ROE(current_quarter) - ROE(previous_quarter)（按 asset 分组 shift）
      4. groupby(industry, date) → mean(ΔROE) → 赋给同行业每只个股

    含义:
      - 高正值: 行业盈利能力改善（ROE上升趋势）
      - 高负值: 行业盈利能力恶化（ROE下降趋势）
      - 近零值: 行业盈利能力稳定

    边界处理:
      - industry 未知 → 赋 '其他'
      - 财务数据缺失 → ΔROE 为 NaN（自然排除）
      - ROE 前推填充: 首日无前值 → NaN（不做填充）
      - ΔROE = NaN → 行业均值自动跳过（pandas mean NaN-safe）

    遵循 H5: IC方向不预判
    预期: 行业基本面改善 → IC正向（偏好盈利改善的行业）

    required_cols: ["date", "asset"]
    """
    _logger = get_module_logger(logger_arg)

    df = factor_df.copy()

    # Step 1: 加载财务数据
    _logger.info("  Step 1: 加载季度财务数据...")
    financial_df = _load_financial_data(financial_data_path, logger_arg)

    # Step 2: 前推填充对齐日频
    _logger.info("  Step 2: 前推填充ROE对齐日频...")
    roe_daily = _merge_asof_financial(df, financial_df, "roe", "roe_daily", logger_arg)
    # ⚠️ 类型修复: 同花顺 API 返回的 roe 可能是 Decimal 类型，必须转为 float
    df["roe_daily"] = pd.to_numeric(roe_daily, errors="coerce")

    # Step 3: 计算 ΔROE = ROE(current_quarter) - ROE(previous_quarter)
    _logger.info("  Step 3: 计算ΔROE（季度间变化）...")
    df = df.sort_values([_COL_ASSET, _COL_DATE])
    prev_roe = df.groupby(_COL_ASSET)["roe_daily"].shift(1)
    df["delta_roe"] = df["roe_daily"] - prev_roe
    # 首日无前值 → NaN（自然排除，不做填充）

    # Step 4: 添加 industry 列
    _logger.info("  Step 4: 添加行业分类列...")
    df = _add_industry_column(df, _logger)

    # Step 5: 行业聚合赋个股
    _logger.info("  Step 5: 行业ΔROE赋给个股...")
    industry_delta_roe = df.groupby(["industry", _COL_DATE])["delta_roe"].mean().reset_index()
    trend_map = industry_delta_roe.set_index(["industry", _COL_DATE])["delta_roe"]

    df[_COL_INDUSTRY_ROE_TREND] = df.set_index(["industry", _COL_DATE]).index.map(
        lambda idx: trend_map.get(idx, float("nan"))
    )

    # 删除中间列
    df = df.drop(columns=["roe_daily", "delta_roe"])

    valid_count = int(df[_COL_INDUSTRY_ROE_TREND].notna().sum())
    _logger.info(
        "  有效 %s: %d (%.2f%%)",
        _COL_INDUSTRY_ROE_TREND,
        valid_count,
        valid_count / len(df) * 100 if len(df) > 0 else 0,
    )

    return df


calculate_industry_roe_trend.required_cols = ["date", "asset"]  # type: ignore[attr-defined]


def calculate_industry_earnings_growth(
    factor_df: pd.DataFrame,
    *,
    financial_data_path: str | Path | None = None,
    logger_arg: logging.Logger | None = None,
) -> pd.DataFrame:
    """计算行业盈利增长因子（行业净利润增长率赋个股）

    公式:
      1. 加载季度财务数据 → net_profit_growth_yoy per (asset, report_date)
      2. Point-forward fill → 对齐日频 (merge_asof direction='backward')
      3. groupby(industry, date) → mean(net_profit_growth_yoy) → 赋给同行业每只个股

    含义:
      - 高正值: 行业盈利高增长（净利润同比增速大）
      - 高负值: 行业盈利下滑（净利润同比增速为负）
      - 近零值: 行业盈利平稳

    边界处理:
      - industry 未知 → 赋 '其他'
      - 财务数据缺失 → NaN（自然排除）
      - 银行/金融股净利润增长率可能为 NaN（会计差异，正常现象）

    遵循 H5: IC方向不预判

    required_cols: ["date", "asset"]
    """
    _logger = get_module_logger(logger_arg)

    df = factor_df.copy()

    # Step 1: 加载财务数据
    _logger.info("  Step 1: 加载季度财务数据...")
    financial_df = _load_financial_data(financial_data_path, logger_arg)

    # Step 2: 前推填充对齐日频
    _logger.info("  Step 2: 前推填充净利润增长率对齐日频...")
    growth_daily = _merge_asof_financial(df, financial_df, "net_profit_growth_yoy", "growth_daily", logger_arg)
    # ⚠️ 类型修复: 同花顺 API 返回的 net_profit_growth_yoy 可能是 Decimal 类型，必须转为 float
    df["growth_daily"] = pd.to_numeric(growth_daily, errors="coerce")

    # Step 3: 添加 industry 列
    _logger.info("  Step 3: 添加行业分类列...")
    df = _add_industry_column(df, _logger)

    # Step 4: 行业聚合赋个股
    _logger.info("  Step 4: 行业净利润增长率赋给个股...")
    industry_growth = df.groupby(["industry", _COL_DATE])["growth_daily"].mean().reset_index()
    trend_map = industry_growth.set_index(["industry", _COL_DATE])["growth_daily"]

    df[_COL_INDUSTRY_EARNINGS_GROWTH] = df.set_index(["industry", _COL_DATE]).index.map(
        lambda idx: trend_map.get(idx, float("nan"))
    )

    # 删除中间列
    df = df.drop(columns=["growth_daily"])

    valid_count = int(df[_COL_INDUSTRY_EARNINGS_GROWTH].notna().sum())
    _logger.info(
        "  有效 %s: %d (%.2f%%)",
        _COL_INDUSTRY_EARNINGS_GROWTH,
        valid_count,
        valid_count / len(df) * 100 if len(df) > 0 else 0,
    )

    return df


calculate_industry_earnings_growth.required_cols = ["date", "asset"]  # type: ignore[attr-defined]


def calculate_industry_pe_trend(
    factor_df: pd.DataFrame,
    *,
    financial_data_path: str | Path | None = None,
    logger_arg: logging.Logger | None = None,
) -> pd.DataFrame:
    """计算行业PE趋势因子（行业ΔPE赋个股）

    公式:
      1. 加载季度财务数据 → annualized_eps per (asset, report_date)
      2. Point-forward fill → 对齐日频 (merge_asof direction='backward')
      3. PE = close / annualized_eps（分母 clip 保护，遵循 Pitfall #47）
      4. ΔPE = PE(current_quarter) - PE(previous_quarter)（按 asset 分组 shift）
      5. groupby(industry, date) → mean(ΔPE) → 赋给同行业每只个股

    含义:
      - 高正值: 行业估值上升（PE上升趋势，市场给予更高估值）
      - 高负值: 行业估值下降（PE下降趋势，市场降低估值）
      - 近零值: 行业估值稳定

    边界处理:
      - industry 未知 → 赋 '其他'
      - annualized_eps 缺失 → PE = NaN
      - annualized_eps 极小 → clip(lower=0.01) 保护（遵循 Pitfall #47）
      - annualized_eps ≤ 0 → PE = NaN（亏损公司 PE 无意义）
      - PE 首日无前值 → ΔPE = NaN

    ⚠️ 比率型因子: 分母 annualized_eps 可能趋近零 → clip(lower=0.01) 保护
    ⚠️ 亏损公司（eps≤0）PE为负，趋势仍有意义但需特殊处理

    遵循 H5: IC方向不预判

    required_cols: ["date", "asset", "close"]
    """
    _logger = get_module_logger(logger_arg)

    df = factor_df.copy()

    # Step 1: 加载财务数据
    _logger.info("  Step 1: 加载季度财务数据...")
    financial_df = _load_financial_data(financial_data_path, logger_arg)

    # Step 2: 前推填充对齐日频
    _logger.info("  Step 2: 前推填充年化EPS对齐日频...")
    eps_daily = _merge_asof_financial(df, financial_df, "annualized_eps", "eps_daily", logger_arg)
    # ⚠️ 类型修复: 同花顺 API 返回的 annualized_eps 可能是 Decimal 类型
    # Decimal 除 float 会报 TypeError，必须先转为 float
    df["eps_daily"] = pd.to_numeric(eps_daily, errors="coerce")

    # Step 3: 计算 PE = close / annualized_eps
    _logger.info("  Step 3: 计算PE（比率型因子，分母clip保护）...")
    eps_safe = df["eps_daily"].clip(lower=_PE_DENOMINATOR_MIN)
    df["pe_daily"] = df[_COL_CLOSE] / eps_safe
    # annualized_eps ≤ 0（亏损公司）→ PE = NaN（负PE趋势意义存疑，排除）
    df.loc[df["eps_daily"] <= 0, "pe_daily"] = float("nan")
    # annualized_eps 原值为 NaN → PE = NaN
    df.loc[df["eps_daily"].isna(), "pe_daily"] = float("nan")

    # Step 4: 计算 ΔPE = PE(current) - PE(previous)
    _logger.info("  Step 4: 计算ΔPE（季度间变化）...")
    df = df.sort_values([_COL_ASSET, _COL_DATE])
    prev_pe = df.groupby(_COL_ASSET)["pe_daily"].shift(1)
    df["delta_pe"] = df["pe_daily"] - prev_pe

    # Step 5: 添加 industry 列
    _logger.info("  Step 5: 添加行业分类列...")
    df = _add_industry_column(df, _logger)

    # Step 6: 行业聚合赋个股
    _logger.info("  Step 6: 行业ΔPE赋给个股...")
    industry_delta_pe = df.groupby(["industry", _COL_DATE])["delta_pe"].mean().reset_index()
    trend_map = industry_delta_pe.set_index(["industry", _COL_DATE])["delta_pe"]

    df[_COL_INDUSTRY_PE_TREND] = df.set_index(["industry", _COL_DATE]).index.map(
        lambda idx: trend_map.get(idx, float("nan"))
    )

    # 删除中间列
    df = df.drop(columns=["eps_daily", "pe_daily", "delta_pe"])

    valid_count = int(df[_COL_INDUSTRY_PE_TREND].notna().sum())
    _logger.info(
        "  有效 %s: %d (%.2f%%)",
        _COL_INDUSTRY_PE_TREND,
        valid_count,
        valid_count / len(df) * 100 if len(df) > 0 else 0,
    )

    return df


calculate_industry_pe_trend.required_cols = ["date", "asset", "close"]  # type: ignore[attr-defined]


# ============================================================================
# 资金流因子（方案C，v1.17 2026-06-12）
# 数据来源: fund_flow_data.json.gz（akshare stock_individual_fund_flow）
# 每只股票约120交易日数据（API限制），日频数据直接可用无需前推填充
# ============================================================================

# 新增列名常量
_COL_CAPITAL_FLOW_RATIO_TREND = "capital_flow_ratio_trend"
_COL_CAPITAL_FLOW_INTENSITY = "capital_flow_intensity"

# 资金流数据缓存路径
_FUND_FLOW_DATA_PATH: str | None = None


def _get_fund_flow_data_path(logger_arg: logging.Logger | None = None) -> Path:
    """获取资金流数据缓存路径（遵循 paths.py 单一来源）"""
    global _FUND_FLOW_DATA_PATH
    if _FUND_FLOW_DATA_PATH is not None:
        return Path(_FUND_FLOW_DATA_PATH)
    try:
        from data_fetchers.common import get_module_result_dir
    except ImportError:
        from common import get_module_result_dir
    result_dir = get_module_result_dir()
    _FUND_FLOW_DATA_PATH = str(result_dir / "fund_flow_data.json.gz")
    return Path(_FUND_FLOW_DATA_PATH)


def _load_fund_flow_data(
    fund_flow_path: Path | str | None = None,
    logger_arg: logging.Logger | None = None,
) -> pd.DataFrame:
    """加载资金流数据缓存，返回 DataFrame

    Args:
        fund_flow_path: 资金流数据缓存路径（None 时使用默认路径）
        logger_arg: 调用方传入的 logger（可选）

    Returns:
        资金流 DataFrame，包含 asset, date, main_inflow_ratio, main_inflow_amount, total_volume 等列

    Raises:
        FileNotFoundError: 缓存文件不存在
        RuntimeError: 缓存数据为空或格式错误
    """
    _logger = get_module_logger(logger_arg)

    path = Path(fund_flow_path) if fund_flow_path else _get_fund_flow_data_path(logger_arg)
    if not path.exists():
        raise FileNotFoundError(f"资金流数据缓存不存在: {path}，请先运行 fetch_fund_flow.py")

    import gzip
    import json

    # 检测文件是否为 gzip 格式（支持 plain JSON 和 gzip 两种）
    is_gzip = True
    try:
        with gzip.open(path, "rt") as f:
            raw_data = json.load(f)
    except gzip.BadGzipFile:
        # plain JSON 格式（兼容早期写入版本）
        is_gzip = False
        with open(path) as f:
            raw_data = json.load(f)

    data_list = raw_data.get("data", [])
    if not data_list:
        raise RuntimeError(f"资金流数据缓存为空: {path}")

    df = pd.DataFrame(data_list)

    required_cols = ["asset", "date"]
    missing = [c for c in required_cols if c not in df.columns]
    if missing:
        raise RuntimeError(f"资金流数据缺少必需列: {missing}")

    del raw_data, data_list
    import gc

    gc.collect()

    _logger.info("加载资金流数据: %d 条记录, %d 只股票", len(df), len(set(df["asset"])))
    return df


def _merge_fund_flow_daily(
    factor_df: pd.DataFrame,
    fund_flow_df: pd.DataFrame,
    value_col: str,
    output_col: str,
    logger_arg: logging.Logger | None = None,
) -> pd.Series:
    """合并日频资金流数据到因子 DataFrame

    Args:
        factor_df: 日频因子 DataFrame（含 date, asset 列）
        fund_flow_df: 资金流 DataFrame（含 asset, date, value_col 列）
        value_col: 资金流数据中的值列名
        output_col: 输出列名
        logger_arg: logger（可选）

    Returns:
        与 factor_df 行数对齐的 Series
    """
    _logger = get_module_logger(logger_arg)

    # 日期格式对齐
    ff_subset = fund_flow_df[["asset", "date", value_col]].copy()
    ff_subset["date"] = ff_subset["date"].astype(str)

    # 精确匹配（资金流数据是日频，无需 merge_asof）
    merged = factor_df[[_COL_DATE, _COL_ASSET]].copy()
    merged[_COL_DATE] = merged[_COL_DATE].astype(str)

    result = merged.merge(
        ff_subset,
        left_on=[_COL_DATE, _COL_ASSET],
        right_on=["date", "asset"],
        how="left",
    )[value_col].rename(output_col)

    return result


def calculate_capital_flow_ratio_trend(
    factor_df: pd.DataFrame,
    *,
    fund_flow_path: str | Path | None = None,
    logger_arg: logging.Logger | None = None,
) -> pd.DataFrame:
    """计算资金流占比趋势因子（行业主力净流入占比Δ赋个股）

    公式:
      1. 加载资金流数据 → main_inflow_ratio per (asset, date)
      2. 精确匹配日频数据到 factor_df（资金流数据已是日频，无需前推填充）
      3. Δratio = main_inflow_ratio(current) - main_inflow_ratio(previous)（按 asset 分组 shift(1)）
      4. groupby(industry, date) → mean(Δratio) → 赋给同行业每只个股

    含义:
      - 高正值: 行业主力资金持续流入（净流入占比上升）
      - 高负值: 行业主力资金持续流出（净流入占比下降）
      - 近零值: 行业资金流向稳定

    边界处理:
      - industry 未知 → 赋 '其他'
      - 资金流数据缺失 → Δratio 为 NaN
      - 资金流数据约120交易日（API限制），超过此范围的日期 → NaN
      - Δratio 首日无前值 → NaN

    ⚠️ 数据覆盖限制: 每只股票约120交易日，早期日期必然缺失

    遵循 H5: IC方向不预判

    required_cols: ["date", "asset"]
    """
    _logger = get_module_logger(logger_arg)

    df = factor_df.copy()

    # Step 1: 加载资金流数据
    _logger.info("  Step 1: 加载资金流数据...")
    fund_flow_df = _load_fund_flow_data(fund_flow_path, logger_arg)

    # Step 2: 合并日频资金流数据
    _logger.info("  Step 2: 合并主力净流入占比到因子数据...")
    ratio_daily = _merge_fund_flow_daily(df, fund_flow_df, "main_inflow_ratio", "ratio_daily", logger_arg)
    df["ratio_daily"] = ratio_daily.values if len(ratio_daily) == len(df) else [float("nan")] * len(df)

    # Step 3: 计算 Δratio = ratio(current) - ratio(previous)
    _logger.info("  Step 3: 计算Δ主力净流入占比...")
    df = df.sort_values([_COL_ASSET, _COL_DATE])
    prev_ratio = df.groupby(_COL_ASSET)["ratio_daily"].shift(1)
    df["delta_ratio"] = df["ratio_daily"] - prev_ratio

    # Step 4: 添加 industry 列
    _logger.info("  Step 4: 添加行业分类列...")
    df = _add_industry_column(df, _logger)

    # Step 5: 行业聚合赋个股
    _logger.info("  Step 5: 行业Δ主力净流入占比赋给个股...")
    industry_delta_ratio = df.groupby(["industry", _COL_DATE])["delta_ratio"].mean().reset_index()
    trend_map = industry_delta_ratio.set_index(["industry", _COL_DATE])["delta_ratio"]

    df[_COL_CAPITAL_FLOW_RATIO_TREND] = df.set_index(["industry", _COL_DATE]).index.map(
        lambda idx: trend_map.get(idx, float("nan"))
    )

    # 删除中间列
    df = df.drop(columns=["ratio_daily", "delta_ratio"])

    valid_count = int(df[_COL_CAPITAL_FLOW_RATIO_TREND].notna().sum())
    _logger.info(
        "  有效 %s: %d (%.2f%%)",
        _COL_CAPITAL_FLOW_RATIO_TREND,
        valid_count,
        valid_count / len(df) * 100 if len(df) > 0 else 0,
    )

    return df


calculate_capital_flow_ratio_trend.required_cols = ["date", "asset"]  # type: ignore[attr-defined]


def calculate_capital_flow_intensity(
    factor_df: pd.DataFrame,
    *,
    fund_flow_path: str | Path | None = None,
    logger_arg: logging.Logger | None = None,
) -> pd.DataFrame:
    """计算资金流强度因子（行业主力流入绝对额占比赋个股）

    公式:
      1. 加载资金流数据 → main_inflow_amount, total_volume per (asset, date)
      2. intensity = |main_inflow_amount| / total_volume（主力流入占成交额的绝对比例）
      3. 精确匹配日频数据到 factor_df
      4. groupby(industry, date) → mean(intensity) → 赋给同行业每只个股

    含义:
      - 高值: 行业主力资金活跃度高（主力参与成交的比例大）
      - 低值: 行业主力资金活跃度低（散户主导，主力参与少）
      - 0值: 行业无主力资金流入流出

    边界处理:
      - industry 未知 → 赋 '其他'
      - total_volume = 0 或 NaN → intensity = NaN（除零保护）
      - 资金流数据约120交易日（API限制），超过此范围 → NaN

    ⚠️ 数据覆盖限制: 同 capital_flow_ratio_trend
    ⚠️ 比率型因子: 分母 total_volume 可能为零 → NaN 处理

    遵循 H5: IC方向不预判

    required_cols: ["date", "asset"]
    """
    _logger = get_module_logger(logger_arg)

    df = factor_df.copy()

    # Step 1: 加载资金流数据
    _logger.info("  Step 1: 加载资金流数据...")
    fund_flow_df = _load_fund_flow_data(fund_flow_path, logger_arg)

    # Step 2: 计算 intensity = |main_inflow_amount| / total_volume
    _logger.info("  Step 2: 计算资金流强度...")
    # 先合并 main_inflow_amount 和 total_volume
    amount_daily = _merge_fund_flow_daily(df, fund_flow_df, "main_inflow_amount", "amount_daily", logger_arg)
    volume_daily = _merge_fund_flow_daily(df, fund_flow_df, "total_volume", "volume_daily", logger_arg)
    df["amount_daily"] = amount_daily.values if len(amount_daily) == len(df) else [float("nan")] * len(df)
    df["volume_daily"] = volume_daily.values if len(volume_daily) == len(df) else [float("nan")] * len(df)

    # intensity = |main_inflow_amount| / total_volume
    df["intensity"] = df["amount_daily"].abs() / df["volume_daily"]
    # total_volume = 0 或 NaN → intensity = NaN
    df.loc[df["volume_daily"] == 0, "intensity"] = float("nan")
    df.loc[df["volume_daily"].isna(), "intensity"] = float("nan")
    df.loc[df["amount_daily"].isna(), "intensity"] = float("nan")

    # Step 3: 添加 industry 列
    _logger.info("  Step 3: 添加行业分类列...")
    df = _add_industry_column(df, _logger)

    # Step 4: 行业聚合赋个股
    _logger.info("  Step 4: 行业资金流强度赋给个股...")
    industry_intensity = df.groupby(["industry", _COL_DATE])["intensity"].mean().reset_index()
    trend_map = industry_intensity.set_index(["industry", _COL_DATE])["intensity"]

    df[_COL_CAPITAL_FLOW_INTENSITY] = df.set_index(["industry", _COL_DATE]).index.map(
        lambda idx: trend_map.get(idx, float("nan"))
    )

    # 删除中间列
    df = df.drop(columns=["amount_daily", "volume_daily", "intensity"])

    valid_count = int(df[_COL_CAPITAL_FLOW_INTENSITY].notna().sum())
    _logger.info(
        "  有效 %s: %d (%.2f%%)",
        _COL_CAPITAL_FLOW_INTENSITY,
        valid_count,
        valid_count / len(df) * 100 if len(df) > 0 else 0,
    )

    return df


calculate_capital_flow_intensity.required_cols = ["date", "asset"]  # type: ignore[attr-defined]
