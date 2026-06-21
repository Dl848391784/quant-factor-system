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
v1.11 (2026-06-01): 新增隔夜收益率因子
  - 添加 `calculate_overnight_return()` 函数
  - 添加 `_COL_OPEN`、`_COL_OVERNIGHT_RET` 常量
  - 公式：overnight_ret = (今日开盘价 - 昨日收盘价) / 昨日收盘价
  - 边界处理：第一天无昨日收盘价 → NaN
v1.12 (2026-06-01): 新增 DataFrame 级 RSI 包装函数
  - 添加 `calculate_rsi_df()` 函数（封装 `calculate_rsi`，输入/输出均为 DataFrame）
  - 引入 `_per_asset_transform` 重构 RSI 多资产分组计算（避免 OOM，详见 PR f3711f3d）
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

# stdlib import：用于在文件末尾、9 段子模块 re-import 全部成功后注册加载诊断
# 锚点（详见文件末尾 _MODULE_LOGGER 定义）。需置于文件顶部以满足 ruff E402。
import logging

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
)

# 注：以下 5 个内部 helper 不再经门面层 re-export（R6，2026-06-16）——
#   `_MODULE_LOGGER`、`_calculate_delta`、`_per_asset_transform`、
#   `_calculate_ewm_with_initial`、`_wilder_smoothing_rsi`、`get_module_logger`
# 子模块（basic / momentum / delta / volume_price / industry / industry_financial /
# fund_flow / intraday / tail）均直接 ``from ._common import ...`` 取用，避免外部
# 通过 ``from data_fetchers.factor_calculator import _MODULE_LOGGER`` 等路径访问
# 私有符号导致的封装边界泄漏。``__init__.py`` 仍从 ``_common`` 直接重导出
# 测试/外部依赖的半公开 helper（``_per_asset_transform`` /
# ``_calculate_ewm_with_initial`` / ``get_module_logger`` 等），路径不变。
# R2 (2026-06-16): _add_industry_column 已迁出至 _industry_helpers.py，
# 此处保留 re-import 维持 ``from ._legacy import *`` 通配兼容。
from ._industry_helpers import _add_industry_column  # noqa: F401

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
# 子模块 fund_flow re-import（PR-4b：资金流 2 个因子已搬到 .fund_flow，
# 含 parquet I/O）
# ============================================================================
from .fund_flow import (  # noqa: F401
    calculate_capital_flow_intensity,
    calculate_capital_flow_ratio_trend,
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
# 子模块 industry_financial re-import（PR-4b：行业基本面 3 个因子已搬到
# .industry_financial，含 parquet I/O）
# ============================================================================
from .industry_financial import (  # noqa: F401
    calculate_industry_earnings_growth,
    calculate_industry_pe_trend,
    calculate_industry_roe_trend,
)

# ============================================================================
# 子模块 intraday re-import（B1：日内强度族因子从 factor_generator.py 迁出）
# ============================================================================
from .intraday import (  # noqa: F401
    calculate_intraday_intensity,
)

# ============================================================================
# 子模块 momentum re-import（PR-2c：动量族因子已搬到 .momentum，本文件 re-export
# 维持 `from ._legacy import *` 通配兼容 + __all__ 中名称仍有效）
# ============================================================================
from .momentum import (  # noqa: F401
    calculate_amplitude,
    calculate_downside_deceleration,  # v2.35: P5-补充 下跌减速
    calculate_interaction_amp_compression,  # v2.36: 交互因子族 (design.md feat_interaction_factors)
    calculate_interaction_amplitude,  # v2.36: 交互因子族 (design.md feat_interaction_factors)
    calculate_interaction_turnover,  # v2.36: 交互因子族 (design.md feat_interaction_factors)
    calculate_lower_shadow_ratio,  # v2.35: P5 下影线比
    calculate_ma5_slope,  # v2.35: P5 MA5斜率
    calculate_momentum_strength,
    calculate_overnight_return,
    calculate_past_return_1d,
    calculate_price_position,
    calculate_return_3d,
    calculate_return_5d,
    calculate_return_acceleration_5d,  # v2.35: P5-补充 收益率加速度
    calculate_rsi_slope_3d,  # v2.35: P5 RSI斜率
)

# 子模块 tail re-import（B4：尾盘 5 分钟 K 线族因子从 factor_generator.py 迁出）
# ============================================================================
from .tail import (  # noqa: F401
    calculate_tail_factors,
)

# ============================================================================
# 子模块 volume_price re-import（PR-3：量价合成族 4 个因子已搬到 .volume_price）
# ============================================================================
from .volume_price import (  # noqa: F401
    calculate_amplitude_compression,  # v2.35: P5-补充 振幅收敛
    calculate_ma5_deviation,
    calculate_near_high_ratio_5,
    calculate_positive_day_ratio_5,
    calculate_price_volume_divergence,  # v2.35: P5 价跌量缩背离
    calculate_range_compression,  # v2.35: P5-补充 价格区间收敛
    calculate_turnover_decay_rate,  # v2.35: P5-补充 换手率衰减
    calculate_volume_decay_rate,  # v2.35: P5-补充 量能衰减
    calculate_volume_price_strength,
    calculate_volume_shrink_rate,  # v2.35: P5 缩量率
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
    "calculate_intraday_intensity",  # B1 新增：日内强度因子（从 factor_generator 迁入）
    "calculate_tail_factors",  # B4 新增：尾盘因子族编排（从 factor_generator 迁入）
    "calculate_rsi_slope_3d",  # v2.35: P5 RSI 3日斜率
    "calculate_ma5_slope",  # v2.35: P5 MA5 3日斜率
    "calculate_lower_shadow_ratio",  # v2.35: P5 下影线比
    "calculate_volume_shrink_rate",  # v2.35: P5 缩量率
    "calculate_price_volume_divergence",  # v2.35: P5 价跌量缩背离
    # v2.35: P5-补充——二阶导数企稳信号因子（3维度6因子）
    "calculate_return_acceleration_5d",  # v2.35: P5-补充 收益率加速度
    "calculate_downside_deceleration",  # v2.35: P5-补充 下跌减速
    "calculate_amplitude_compression",  # v2.35: P5-补充 振幅收敛
    "calculate_range_compression",  # v2.35: P5-补充 价格区间收敛
    "calculate_volume_decay_rate",  # v2.35: P5-补充 量能衰减
    "calculate_turnover_decay_rate",  # v2.35: P5-补充 换手率衰减
    # v2.36: 交互因子族 —— 条件因子方向方案 B（design.md feat_interaction_factors）
    "calculate_interaction_amplitude",  # v2.36: weakness × amplitude_z
    "calculate_interaction_turnover",  # v2.36: weakness × turnover_rate_z
    "calculate_interaction_amp_compression",  # v2.36: weakness × amplitude_compression_z
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
# 加载诊断锚点（R5）
# ============================================================================
# 9 段子模块 re-import 全部成功执行后才会到达此处；任一子模块抛 ImportError
# 都会在该 debug 行之前冒泡到调用方，留下"加载到了哪一段"的可追溯线索。
#
# 使用 module-local logger（而非从 `_common` re-export `_MODULE_LOGGER`），既避免
# 封装边界泄漏（R6：`_MODULE_LOGGER` 不在 `__all__` 中且以 `_` 开头，``from
# data_fetchers.factor_calculator import *`` 不会带出），又为加载成功提供
# debug 级诊断锚点。% 惰性格式化（PROJECT.md 硬规则 #13），子模块清单与上方
# 9 段 import 注释顺序保持一致。
_MODULE_LOGGER = logging.getLogger(__name__)
_MODULE_LOGGER.debug(
    "factor_calculator legacy facade loaded, submodules: %s",
    "basic / delta / fund_flow / industry / industry_financial / intraday / momentum / tail / volume_price",
)
