"""factor_calculator 包通用底座（_common）。

集中存放：
- 模块级私有常量（`_COL_*`、`_DEFAULT_*`、`_EPSILON`、基准值常量）
- 公共常量别名（`DEFAULT_*`，被 `factor_ic` 多个脚本直接 import）
- 模块 logger 与 ``get_module_logger`` 半公开 helper
- 4 个跨子模块复用的纯计算 helper：
  ``_wilder_smoothing_rsi`` / ``_per_asset_transform`` /
  ``_calculate_ewm_with_initial`` / ``_calculate_delta``

约束（design.md §5.1）：
- ``__all__ = []``：本模块**不导出公共 API**；外部需要的半公开符号统一由
  ``data_fetchers/factor_calculator/__init__.py`` 显式 re-export。
- 仅依赖标准库 + numpy + pandas + logging（依赖图根节点，不得反向依赖任何兄弟子模块）。
- 内容与原 ``factor_calculator.py``（已重命名为 ``_legacy.py``）逐字对齐，禁止重写公式或调整边界处理（设计 §3.2 N1）。
- ``_add_industry_column`` 已于 R2（2026-06-16）迁出至 ``_industry_helpers.py``，
  以保持本模块作为依赖图根节点的纯净度（不反向依赖 ``fetch_industry``）。

历史：
- v1.20 (2026-06-15) PR-2a：从 ``_legacy.py`` 行 100-234 / 267-313 / 470-525 /
  618-651 / 1452-1503 抽取至本模块，``_legacy.py`` 改为 ``from ._common import *`` 兼容。
- v1.21 (2026-06-16) R2：``_add_industry_column`` 迁出至 ``_industry_helpers.py``
  （消除 §5.1 反向依赖违规：``_common.py`` 不再依赖 ``data_fetchers.fetch_industry``）；
  同步修复：``_per_asset_transform`` 增加排序契约硬校验（同 asset 不连续即抛 ValueError）；
  ``_calculate_ewm_with_initial`` 哨兵索引由 ``-1`` 改为不可碰撞的字符串
  ``"__ewm_initial_sentinel__"``；``_wilder_smoothing_rsi`` 在递推链首次因前值
  NaN 中断时记录 debug 日志；``_calculate_delta`` 行顺序契约写入 docstring，
  日志级别由 INFO 降为 DEBUG（避免高频批量调用刷屏）；
  ``_DEFAULT_PRICE_POSITION_EPSILON`` / ``_DEFAULT_AMPLITUDE_EPSILON`` 改为引用
  ``_EPSILON`` 消除重复字面量。
- v1.22 (2026-06-16) R3：本模块自身可观测性与契约修复（不改公式语义）：
  ``_per_asset_transform`` 增加 ``_validate_sort`` 参数，大批量场景可跳过
  ``np.unique`` 的 O(n log n) 排序校验；``_calculate_ewm_with_initial`` 的字符串
  哨兵索引方案改为"先重置为 RangeIndex 再 concat"，彻底规避业务索引（datetime /
  int / 复合）与字符串混合的 dtype 退化与潜在 TypeError；
  ``_wilder_smoothing_rsi`` 收集所有递推链中断索引，循环结束后一次性输出 debug
  （仅 1 条日志，但完整暴露多段空洞）；``_calculate_delta`` Example 注释加日期标签
  （``d3(0.05) - d2(0.03) = 0.02``）明确时序差分语义；迁出说明与 EPSILON 命名
  注释改写为"包内私有 helper / 同包兄弟模块按 PEP 8 包内访问"语义，消除
  "调用方应使用包级路径"与实际架构（包内访问私有符号合规）的歧义。
- v1.23 (2026-06-16) R4：本模块自身 8 项可观测性 / 契约 / 防御修复：
  ``_wilder_smoothing_rsi`` 入口加 ``n <= 0`` 防御抛 ValueError；中断索引收集
  策略由"全部位置"改为"段起点"（中断后每个后续位置都触发"前值 NaN"分支会让
  日志列表 = O(n) 自身刷屏，改为只记录 NaN 段起点）；
  ``_per_asset_transform`` 加 fn 返回长度断言（带 asset 标识替代 numpy 形状广播
  错误的不可读信息），``_validate_sort=False`` 路径增加 debug 日志记录"已跳过校验
  + 调用方负责"；
  ``_calculate_ewm_with_initial`` 哨兵 dtype 由 ``series_reset.dtype`` 改为固定
  ``np.float64``（避免上游 series 含 NaN 时 dtype 退化为 object/Float64 导致
  ewm 走异常分支），并补 ``.copy()`` 注释说明"切片解耦必要操作 / 禁止删除"；
  模块级 logger 由硬编码 ``"data_fetchers.factor_calculator"`` 改为
  ``logging.getLogger(__name__)``，按 Python 日志命名约定使用模块全限定名
  以支持按层级精确过滤；末尾迁出说明注释由 15 行精简为 3 行（架构规范属
  design.md / MODULE.md 内容，不应承载于代码注释）。
- v1.24 (2026-06-16) R5：本模块自身 8 项可观测性 / 契约 / 防御修复：
  ``_wilder_smoothing_rsi`` 删除 ``in_reported_break = False`` 重置死代码
  （Wilder 标准下链不可恢复，``else`` 分支永不进入，重置永不触发——违反
  PROJECT.md 规则 #14 同源原则）；``_per_asset_transform`` 把 ``boundaries``
  扩展上移到 ``_validate_sort`` 分支前，让两路日志与主循环共用一份扩展数据，
  消除 ``len(boundaries)+1`` / ``len(boundaries)-1`` 双重读法歧义，并在循环
  结束后补正常路径函数级 debug 日志（与 ``_validate_sort=False`` 路径对称）；
  ``_calculate_ewm_with_initial`` 早返回改 ``return series.copy()`` 保证副作用
  隔离，``result_series.index = series.index`` 改 ``set_axis(series.index)``
  使用 pandas 官方推荐的链式 / 函数式 Index 替换 API；``_calculate_delta``
  日志百分比表达式显式加括号 ``(valid_count / max(total_count, 1)) * 100``
  防止后续误改成整除 / 调括号时静默走错；模块 docstring 删除 v1.21 中"修正
  ``get_module_logger`` 文档示例的函数名"过时备注（当前示例已与签名一致）；
  ``_DEFAULT_PRICE_POSITION_EPSILON`` / ``_DEFAULT_AMPLITUDE_EPSILON`` 注释由
  6 行精简为 1 行语义别名说明，设计理由迁至 design.md（与 v1.23 末尾迁出
  说明精简原则一致，不在代码注释中承载架构规范）。
"""

from __future__ import annotations

import logging
from collections.abc import Callable  # noqa: F401  used in stringified type hints (PEP 563)

import numpy as np
import pandas as pd


# 本模块不导出公共 API：通过包级 __init__.py 显式 re-export 半公开符号
__all__: list[str] = []


# ============================================================================
# 数值阈值与因子计算基准值（私有常量，非公共 API）
# ============================================================================

_EPSILON = 1e-10  # 避免除零阈值

# 因子计算基准值
_RSI_NEUTRAL_VALUE = 50.0  # RSI 中性值（avg_loss=0 且 avg_gain=0 时）
_RSI_MAX_VALUE = 100  # RSI 最大值（超买）
_BOLLINGER_NEUTRAL_VALUE = 0.5  # 布林带 %B 中性值（带宽过窄时）
_KD_NEUTRAL_VALUE = 50.0  # K/D 值中性初始值


# ============================================================================
# 输入列名常量（DataFrame 列名）
# ============================================================================

_COL_CLOSE = "close"
_COL_DATE = "date"
_COL_ASSET = "asset"
_COL_HIGH = "high"
_COL_LOW = "low"
_COL_TURNOVER_RATE = "turnover_rate"


# ============================================================================
# 输出列名常量（因子输出列名）
# ============================================================================

_COL_BOLLINGER_PB = "bollinger_pb"
_COL_KDJ_J = "kdj_j"
_COL_TURNOVER_SURGE = "turnover_surge"
_COL_PRICE_POSITION = "price_position"
_COL_AMPLITUDE = "amplitude"
_COL_PAST_RETURN_1D = "past_return_1d"
_COL_RETURN_3D = "return_3d"
_COL_RETURN_5D = "return_5d"
_COL_AMPLITUDE_DELTA = "amplitude_delta"
_COL_TURNOVER_SURGE_DELTA = "turnover_surge_delta"
_COL_TAIL_PRICE_POSITION_DELTA = "tail_price_position_delta"
_COL_TAIL_VOLUME_SHRINK_DELTA = "tail_volume_shrink_delta"
_COL_VOLUME_PRICE_STRENGTH = "volume_price_strength"
_COL_POSITIVE_DAY_RATIO_5 = "positive_day_ratio_5"
_COL_MA5_DEVIATION = "ma5_deviation"
_COL_NEAR_HIGH_RATIO_5 = "near_high_ratio_5"
_COL_INDUSTRY_MOMENTUM_5D = "industry_momentum_5d"
_COL_INDUSTRY_TURNOVER_TREND = "industry_turnover_trend"
_COL_INDUSTRY_AMPLITUDE_TREND = "industry_amplitude_trend"
_COL_INDUSTRY_ROE_TREND = "industry_roe_trend"  # v1.16 新增：行业ROE趋势因子
_COL_INDUSTRY_EARNINGS_GROWTH = "industry_earnings_growth"  # v1.16 新增：行业盈利增长因子
_COL_INDUSTRY_PE_TREND = "industry_pe_trend"  # v1.16 新增：行业PE趋势因子

# 动量族（PR-2c）
_COL_OPEN = "open"
_COL_OVERNIGHT_RET = "overnight_ret"
_COL_MOMENTUM_STRENGTH = "momentum_strength"

# 资金流族（PR-4b）
_COL_CAPITAL_FLOW_RATIO_TREND = "capital_flow_ratio_trend"
_COL_CAPITAL_FLOW_INTENSITY = "capital_flow_intensity"

# 交互因子族（v2.36, 2026-06-22）—— 条件因子方向方案 B（design.md feat_interaction_factors）
# weakness × factor_z, 捕捉"弱势子样本中因子方向翻转"的条件效应，见 skill
# factor-development ref conditional-ic-analysis.md
_COL_INTERACTION_AMPLITUDE = "interaction_amplitude"
_COL_INTERACTION_TURNOVER = "interaction_turnover"
_COL_INTERACTION_AMP_COMPRESSION = "interaction_amp_compression"

# 交互因子默认参数
_DEFAULT_INTERACTION_CLIP_SIGMA = 3.0  # 截面 z-score clip 到 ±3σ 防极端值
_DEFAULT_INTERACTION_STD_MIN = 1e-10  # 截面 std 防除零下限


# ============================================================================
# 行业因子默认参数（私有常量）
# ============================================================================

_DEFAULT_INDUSTRY_WINDOW = 5  # 行业5日动量窗口
_DEFAULT_MIN_INDUSTRY_STOCKS = 5  # 行业最少股票数阈值
_DEFAULT_TREND_DENOMINATOR_MIN = 0.001  # 比率型因子分母下限
_DEFAULT_AMPLITUDE_TREND_DENOMINATOR_MIN = 0.01  # 振幅趋势分母下限


# ============================================================================
# 默认参数（私有常量，遵循 cache_manager.py 规范）
# ============================================================================

_DEFAULT_RSI_PERIOD = 6
_DEFAULT_BOLLINGER_N = 20
_DEFAULT_BOLLINGER_K = 2.0
_DEFAULT_KDJ_N = 9
_DEFAULT_KDJ_M1 = 3
_DEFAULT_KDJ_M2 = 3
_DEFAULT_SURGE_WINDOW = 5
_DEFAULT_VOLUME_RATIO_WINDOW = 5
_DEFAULT_FORWARD_RETURN_SHIFT = 1
# 语义别名：``_DEFAULT_*_EPSILON`` 引用 ``_EPSILON``，供 momentum.py 按业务族语义直读。设计理由见 design.md。
_DEFAULT_PRICE_POSITION_EPSILON = _EPSILON
_DEFAULT_AMPLITUDE_EPSILON = _EPSILON
_DEFAULT_PAST_RETURN_1D_WINDOW = 1  # 1日涨幅窗口
_DEFAULT_RETURN_3D_WINDOW = 3  # 3日累计涨幅窗口
_DEFAULT_RETURN_5D_WINDOW = 5  # 5日累计涨幅窗口
_DEFAULT_MOMENTUM_STRENGTH_WINDOW = 5  # 5日滚动窗口（动量强度日收益标准差窗口）
_MOMENTUM_STRENGTH_STD_MIN = 0.01  # 日收益率标准差下限（防止均匀涨跌时比值爆炸）


# ============================================================================
# 公共常量别名（向下兼容 ic_kdj_j / ic_rsi 等脚本的导入；写入 __all__ via __init__.py）
# ============================================================================

DEFAULT_RSI_PERIOD = _DEFAULT_RSI_PERIOD
DEFAULT_BOLLINGER_N = _DEFAULT_BOLLINGER_N
DEFAULT_BOLLINGER_K = _DEFAULT_BOLLINGER_K
DEFAULT_KDJ_N = _DEFAULT_KDJ_N
DEFAULT_KDJ_M1 = _DEFAULT_KDJ_M1
DEFAULT_KDJ_M2 = _DEFAULT_KDJ_M2
DEFAULT_SURGE_WINDOW = _DEFAULT_SURGE_WINDOW
DEFAULT_VOLUME_RATIO_WINDOW = _DEFAULT_VOLUME_RATIO_WINDOW
DEFAULT_FORWARD_RETURN_SHIFT = _DEFAULT_FORWARD_RETURN_SHIFT


# ============================================================================
# 模块级 fallback logger（遵循 PROJECT.md 公共模块日志规范）
# ============================================================================

# 模块级 fallback logger 使用 ``__name__``（即 ``data_fetchers.factor_calculator._common``），
# 比硬编码上层包名 ``data_fetchers.factor_calculator`` 更精确：调用方按 logger 名层级
# 过滤时（如 ``logging.getLogger("data_fetchers.factor_calculator._common").setLevel(WARNING)``）
# 可独立调节本模块日志级别。子 logger 自动继承父级 handler，不破坏既有外部配置。
_MODULE_LOGGER = logging.getLogger(__name__)


def get_module_logger(logger_arg: logging.Logger | None = None) -> logging.Logger:
    """
    获取 logger，遵循 PROJECT.md 公共模块日志规范

    公共模块接收 logger 参数，调用方传入以追溯调用方。
    不传 logger 时使用模块级 fallback logger（模块加载时已初始化）。

    Args:
        logger_arg: 调用方传入的 logger（可选）

    Returns:
        Logger 对象

    Example:
        >>> # 调用方传入 logger
        >>> from data_fetchers.common.logger_config import setup_logger
        >>> logger = setup_logger("factor_generator")
        >>> result = _calculate_delta(df, "amplitude", "amplitude_delta", logger_arg=logger)

        >>> # 不传 logger，使用模块级 fallback
        >>> result = _calculate_delta(df, "amplitude", "amplitude_delta")
    """
    if logger_arg is not None:
        return logger_arg
    return _MODULE_LOGGER


# ============================================================================
# RSI Wilder 平滑（半公开私有 helper）
# ============================================================================


def _wilder_smoothing_rsi(series: pd.Series, n: int) -> pd.Series:
    """Wilder 平滑：前 n-1 天 NaN，第 n 天 SMA 种子，第 n+1 天起 EWM 递推

    Args:
        series: 单资产的序列（gain 或 loss）
        n: 窗口期（必须为正整数）

    Returns:
        Wilder 平滑均值序列

    Raises:
        ValueError: ``n <= 0`` 时（alpha = 1/n 会除零或得到负值，``series.iloc[:n]``
            在 n=0 时返回空序列使 seed=NaN，整体行为不可预期）。

    Note:
        Wilder (1978) 标准实现：
        1. 前 n-1 天为 NaN（数据不足以计算 SMA）
        2. 第 n 天（索引 n-1）使用 SMA 值作为 EWM 种子
           - SMA = series.iloc[:n].mean()
        3. 第 n+1 天及之后使用 EWM 递推
           - 公式：avg_t = alpha * val_t + (1-alpha) * avg_{t-1}
           - alpha = 1/n
           - NaN 传播：若当天输入为 NaN，结果也为 NaN

        与 pandas ewm(adjust=False) 的差异：
        - pandas ewm(adjust=False) 从第 1 个观测值就开始计算
        - Wilder 标准要求前 n-1 天为 NaN，第 n 天用 SMA
    """
    # 入参校验：n 必须为正整数。
    # n=0 会触发 ZeroDivisionError，n<0 会让 alpha 变负彻底污染递推结果，
    # 早抛 ValueError 比让"前 n-1 天 NaN + alpha 异常"两个错误叠加后再爆更可读。
    if n <= 0:
        raise ValueError(f"_wilder_smoothing_rsi: 窗口期 n 必须为正整数，实际传入 {n}")

    alpha = 1.0 / n

    # 初始化全 NaN 序列
    result = pd.Series(float("nan"), index=series.index, dtype=float)

    # 防御性检查：序列长度不足
    if len(series) < n:
        return result

    # 第 n 天（索引 n-1）：SMA 种子
    seed = series.iloc[:n].mean()
    if pd.isna(seed):  # 防御：前 n 天全为 NaN 时无法计算种子
        return result
    result.iloc[n - 1] = seed

    # 第 n+1 天起（索引 n 到 len-1）：EWM 递推
    # 边界行为：若 result.iloc[i-1] 已为 NaN（例如外部把已计算结果某段置 NaN
    # 或 SMA 种子位之后又出现 NaN 输入），递推链将不可恢复地全部 NaN。
    # 这是 Wilder 标准 NaN 传播语义（不在此处兜底）。
    # 可观测性：仅记录每段"前值 NaN 导致链断"的**起点**（``in_reported_break``
    # 由 False→True 的瞬间）。
    # 关键区分：当前输入 NaN（``pd.isna(series.iloc[i])``）属"数据传播"，**不**
    # 改变 ``in_reported_break``——若紧接着的下一轮再因 prev=NaN 触发链断，仍
    # 应记录为新段起点。这是早期版本（R3 / R4 早期）漏报的根因。
    # Wilder 标准下链一旦断裂则不可恢复（``else`` 分支需 prev 非 NaN，链断后
    # ``prev`` 永远为 NaN，``else`` 分支永远进不来），因此实际只会记录 1 段；
    # 不重置 ``in_reported_break``，避免 PROJECT.md 规则 #14 死代码（永不触发
    # 的"链恢复"防御分支）。
    nan_break_starts: list[int] = []
    in_reported_break = False  # 当前是否处于"已报告的链断段"中
    for i in range(n, len(series)):
        prev = result.iloc[i - 1]
        if pd.isna(series.iloc[i]):  # 当天值为 NaN：传播 NaN（不改 in_reported_break）
            result.iloc[i] = float("nan")
        elif pd.isna(prev):  # 前值 NaN：递推链中断，从此全 NaN
            result.iloc[i] = float("nan")
            if not in_reported_break:
                nan_break_starts.append(i)
                in_reported_break = True
        else:
            result.iloc[i] = alpha * series.iloc[i] + (1 - alpha) * prev

    if nan_break_starts:
        _MODULE_LOGGER.debug(
            "_wilder_smoothing_rsi: 递推链共发生 %d 段中断（前值 NaN），段起点索引 = %s；"
            "每段起点之后值均为 NaN（Wilder 标准 NaN 传播语义）",
            len(nan_break_starts),
            nan_break_starts,
        )

    return result


# ============================================================================
# 通用工具：按 asset 分组的低内存 transform 替代
# ============================================================================


def _per_asset_transform(
    asset_arr: np.ndarray,
    value_arr: np.ndarray,
    fn: Callable[[pd.Series], pd.Series],
    *,
    _validate_sort: bool = True,
) -> np.ndarray:
    """按 asset 分组对单列数值序列应用 fn，返回回填的 ndarray。

    替代 ``df.groupby(asset, group_keys=False)[col].transform(fn)``。
    pandas 的 ``groupby.transform`` 在大规模数据 (>1M 行 × >1k group) 上会因
    内部索引重建产生 4 GB+ 内存峰值并触发 OOM（详见 backtest/MODULE.md M54）。

    本 helper 假设 ``asset_arr`` 已**按 asset 排序**（同 asset 行连续），
    用 numpy 边界切片逐 asset 调 ``fn``，回填到预分配 ndarray。

    Args:
        asset_arr: asset 列 ndarray（必须已按 asset 排序）
        value_arr: 数值列 ndarray
        fn: 接收单 asset 的 ``pd.Series``，返回同长度 ``pd.Series``
        _validate_sort: 是否做"排序契约"硬校验（默认 True）。
            校验依赖 ``np.unique(asset_arr)``，时间复杂度 O(n log n)，
            在 >1M 行场景下会**抵消** ``transform → 切片`` 的内存优化目的
            （内存仍是 O(n)，但额外 CPU 排序成本不可忽略）。
            调用方若已能保证传入数据严格按 asset 排序（例如上游刚做过
            ``df.sort_values("asset")`` 或预排序的物化缓存），可显式传
            ``_validate_sort=False`` 跳过校验。
            **下划线前缀 + keyword-only**：标识"性能逃生舱"非常规接口，
            误用代价高（fn 看到的不是完整 asset 切片但不报错），
            慎用——默认开启校验更安全。

    Returns:
        回填后的 float64 ndarray（NaN 为缺失），长度与输入一致

    Raises:
        ValueError: asset_arr 与 value_arr 长度不一致；或
            ``_validate_sort=True`` 且 asset_arr 未按 asset 排序
            （同一 asset 在数组中不连续 → 切片段数与唯一 asset 数不等）

    实现说明:
        - 单 asset 切片足够小，``fn`` 内部的 rolling/ewm/diff 操作内存友好
        - 预分配 ndarray 避免 transform 的中间索引膨胀
        - 内存增量约 ``len * 8B``（一份 float64），而非 transform 的几 GB

    Example:
        >>> import numpy as np, pandas as pd
        >>> assets = np.array(["A", "A", "A", "B", "B"])
        >>> values = np.array([1.0, 2.0, 3.0, 10.0, 20.0])
        >>> result = _per_asset_transform(assets, values, lambda s: s.cumsum())
        >>> result.tolist()
        [1.0, 3.0, 6.0, 10.0, 30.0]
    """
    n_rows = len(asset_arr)
    if len(value_arr) != n_rows:
        raise ValueError(f"asset_arr 与 value_arr 长度不一致: {n_rows} vs {len(value_arr)}")
    if n_rows == 0:
        return np.array([], dtype=np.float64)

    # 找 asset 边界并立即扩展（同 asset 行连续，asset 变化处即新组起点）。
    # 扩展后 ``boundaries`` 形如 ``[0, b1, b2, ..., n_rows]``，``len-1`` 即段数。
    # 上移到 ``_validate_sort`` 分支之前：让两个分支与后续主循环都共用同一份
    # 已扩展数据，``len(boundaries) - 1`` 在全函数表达"段数"语义一致，避免
    # 旧实现中 ``len(boundaries) + 1``（分支内、未扩展）/ ``len(boundaries) - 1``
    # （主循环内、已扩展）的双重读法（R5 #2）。
    boundaries = np.flatnonzero(asset_arr[1:] != asset_arr[:-1]) + 1
    boundaries = np.concatenate([[0], boundaries, [n_rows]])
    n_assets = len(boundaries) - 1

    if _validate_sort:
        # 排序契约校验：扩展后 ``n_assets`` 即段数；若调用方未按 asset 排序
        # （同一 asset 被切成多段），``n_assets > n_unique_assets``。
        # 静默错误代价高（fn 看到的不是完整 asset 切片），用 ValueError 显式抛出，
        # 比 docstring "必须已按 asset 排序" 的口头约束可靠（PROJECT.md 规则 #5 同源）。
        # 性能注记：``np.unique`` 是 O(n log n)，>1M 行场景调用方可显式传
        # ``_validate_sort=False`` 跳过（详见 Args._validate_sort）。
        n_unique_assets = len(np.unique(asset_arr))
        if n_assets != n_unique_assets:
            raise ValueError(
                f"_per_asset_transform: asset_arr 未按 asset 排序，"
                f"切片得到 {n_assets} 段但只有 {n_unique_assets} 个唯一 asset，"
                f"调用方需先按 asset 排序后再传入"
            )
    else:
        # 跳过校验路径：仅记录 debug 日志，明确告知调用方"已承担排序正确性责任"。
        # 不做任何降级校验（任何"看似贴心"的兜底都会让 _validate_sort=False
        # 的语义变成"也许会校验"，违反 PROJECT.md 规则 #14 死代码同源原则）。
        # 仍可通过 logger 名层级过滤定位"哪个调用方传了 False"。
        _MODULE_LOGGER.debug(
            "_per_asset_transform: 已跳过排序契约校验（_validate_sort=False），"
            "调用方需自行保证 asset_arr 严格按 asset 排序，"
            "n_rows=%d, n_assets=%d",
            n_rows,
            n_assets,
        )

    out = np.full(n_rows, np.nan, dtype=np.float64)
    for i in range(n_assets):
        start, end = boundaries[i], boundaries[i + 1]
        slice_series = pd.Series(value_arr[start:end])
        result_series = fn(slice_series)
        # 长度契约校验：fn 内部若做 dropna / reindex / 自定义聚合，可能返回长度不一致的
        # Series。若直接 ``out[start:end] = result_series.to_numpy(...)``，numpy 会因
        # 形状不匹配抛 ValueError，但消息形如 ``could not broadcast input array from
        # shape (X,) into shape (Y,)``，缺少 asset 标识，调试代价高。
        # 主动断言并附带 ``asset_arr[start]`` 标识，便于上游定位是哪个 asset 的 fn 走错。
        if len(result_series) != end - start:
            raise ValueError(
                f"_per_asset_transform: fn 返回长度与切片不一致，"
                f"asset={asset_arr[start]!r}, expected={end - start}, "
                f"got={len(result_series)}（请检查 fn 是否做了 dropna / 聚合）"
            )
        out[start:end] = result_series.to_numpy(dtype=np.float64)

    # 正常执行路径函数级 debug：与 ``_validate_sort=False`` 路径对称，让大批量
    # 调用（factor_generator 一次跑数十个因子）能从日志判断该函数是否被执行
    # 及处理了多少 asset。日志级别 DEBUG，不冲生产 INFO 流量（R5 #7）。
    _MODULE_LOGGER.debug(
        "_per_asset_transform: 完成，n_rows=%d, n_assets=%d, validate_sort=%s",
        n_rows,
        n_assets,
        _validate_sort,
    )
    return out


# ============================================================================
# 截面 z-score helper（交互因子族复用）
# ============================================================================


def _cross_section_zscore(
    value: pd.Series,
    dates: pd.Series,
    *,
    clip_sigma: float = _DEFAULT_INTERACTION_CLIP_SIGMA,
    std_min: float = _DEFAULT_INTERACTION_STD_MIN,
) -> pd.Series:
    """按日期截面计算 z-score，并 clip 到 ±clip_sigma。

    用于交互因子族（design.md feat_interaction_factors §4.1）：把同一交易日内
    的因子值标准化为零均值单位方差的 z-score，再做乘法叠加。

    Args:
        value: 待标准化的因子值 Series（NaN 直接传播，不参与均值/方差计算）
        dates: 与 ``value`` 等长的日期 Series（截面分组键）
        clip_sigma: 截尾门限，默认 ±3σ（``_DEFAULT_INTERACTION_CLIP_SIGMA``）
        std_min: 截面 std 防除零下限，默认 1e-10（``_DEFAULT_INTERACTION_STD_MIN``）

    Returns:
        与输入同长同 index 的 Series：``(value - cs_mean) / (cs_std + std_min)``
        再 clip 到 ``[-clip_sigma, +clip_sigma]``。

    边界处理:
        - 单日截面全 NaN → 该日所有输出 NaN
        - 截面 std=0（同日所有值相等）→ 加 ``std_min`` 防除零，结果接近 0
        - NaN 行透传 NaN，不污染其它行

    Note:
        ``ddof=0`` 与现有 ic_preprocessing 的截面 z-score 风格一致。

        实现选择 numpy 边界切片而非 pandas groupby.transform：
        - 后者在 >1M 行 × ~500 group 场景下因内部索引重建产生 GB 级临时对象
          （见 backtest/MODULE.md M54 / `_per_asset_transform` docstring）
        - 前者只持有 ``2 × float64 ndarray``（sort 索引 + 输出，约 12MB+12MB）
        - 设计依据: ``designs/fix_factor_generator_step14_oom.md`` §4
    """
    if len(value) != len(dates):
        raise ValueError(f"value/dates 长度不一致: {len(value)} vs {len(dates)}")

    n = len(value)
    if n == 0:
        return pd.Series([], dtype=np.float64, index=value.index)

    # 1. 提取 numpy 视图（不复制底层 buffer）
    val_arr = value.to_numpy(dtype=np.float64, copy=False)
    date_arr = dates.to_numpy(copy=False)

    # 2. 按 date 稳定排序（argsort 返回索引，原数组不变）
    sort_idx = np.argsort(date_arr, kind="stable")
    val_sorted = val_arr[sort_idx]
    date_sorted = date_arr[sort_idx]

    # 3. 找 date 边界（同 date 行连续，date 变化处即新组起点）
    #    扩展后 ``boundaries`` 形如 ``[0, b1, b2, ..., n]``，``len-1`` 即段数
    boundaries = np.flatnonzero(date_sorted[1:] != date_sorted[:-1]) + 1
    boundaries = np.concatenate([[0], boundaries, [n]])

    # 4. 逐 date 切片做 z-score 计算（numpy 向量化，nanmean/nanstd 跳过 NaN）
    out_sorted = np.full(n, np.nan, dtype=np.float64)
    with np.errstate(invalid="ignore"):  # 全 NaN 截面会触发 'Mean of empty slice' 警告，吞掉
        import warnings

        with warnings.catch_warnings():
            warnings.simplefilter("ignore", category=RuntimeWarning)
            for i in range(len(boundaries) - 1):
                start, end = boundaries[i], boundaries[i + 1]
                seg = val_sorted[start:end]
                mu = np.nanmean(seg)
                sigma = np.nanstd(seg, ddof=0)
                # 单日全 NaN → mu/sigma 都是 NaN → 输出保持 NaN
                # 单日 std=0 → 加 std_min 防除零，结果 (seg - mu)/std_min ≈ 0
                out_sorted[start:end] = (seg - mu) / (sigma + std_min)

    # 5. clip 到 ±clip_sigma（in-place，省一次分配）
    np.clip(out_sorted, -clip_sigma, clip_sigma, out=out_sorted)

    # 6. 恢复原顺序（sort_idx[i] 是排序后第 i 个元素的原位置）
    out = np.empty(n, dtype=np.float64)
    out[sort_idx] = out_sorted

    return pd.Series(out, index=value.index)


# ============================================================================
# EWM 递推 helper（KDJ 子模块复用，半公开私有）
# ============================================================================


def _calculate_ewm_with_initial(series: pd.Series, alpha: float, initial_value: float) -> pd.Series:
    """计算 EWM 递推值（正确处理 NaN 前缀版本）

    公共函数：统一处理 K 值和 D 值的 EWM 递推计算

    Args:
        series: 输入序列（RSV 或 K 值）
        alpha: EWM 衰减因子（1/m，m 为平滑周期）
        initial_value: 初始值（K/D 使用 50.0 作为中性值）

    Returns:
        EWM 递推结果序列（保留输入 ``series`` 的原始索引与索引类型）

    Note:
        - 在第一个有效值前插入虚拟 ``initial_value`` 作为 EWM 种子
        - 使用 ``ewm(adjust=False, ignore_na=True)`` 确保正确传播 NaN
        - 恢复原始 NaN 位置，避免虚拟初始值污染结果

    实现细节（索引类型隔离）:
        ``pd.concat([单元素串, series])`` 在 series 索引为 datetime / int / 多级
        等非字符串类型时，会与字符串哨兵索引混合得到 ``object`` dtype Index，
        在某些 pandas 版本上还可能触发 TypeError 或对齐异常。
        实现选择**先把两段都重置为 RangeIndex 再 concat**：concat 不再依赖
        业务索引，``ewm`` 沿位置滚动；最后 ``iloc[1:]`` 切掉哨兵位、用
        ``set_axis(series.index)`` 把原始 ``series.index`` 函数式赋回。彻底
        规避混合索引类型问题。
    """
    if len(series) == 0 or series.isna().all():
        # 副作用隔离（R5 #5）：所有路径都返回独立副本，调用方修改返回值
        # 不会回写上游数据。docstring "保留输入 series 的原始索引与索引类型"
        # 不允许 caller 与 callee 共享对象底层。
        return series.copy()

    # 在第一个有效值前插入虚拟 initial_value。索引类型隔离：先把 series 重置为
    # RangeIndex，再与单元素 RangeIndex 哨兵串拼接，concat 全程使用同质整型索引。
    # 业务索引（datetime / int / 复合）在最终 ``result_series.index = series.index``
    # 这一步原样恢复，对调用方完全透明。
    series_reset = series.reset_index(drop=True)
    # 哨兵 dtype 固定为 ``np.float64``，不继承 ``series_reset.dtype``：
    # 当上游 series 含 NaN 时其 dtype 可能是 ``object`` 或 ``Float64``（pandas
    # nullable float），此时让哨兵继承会让 ``ewm`` 走 nullable 分支或 object 路径，
    # 数值行为与传统 float64 路径不一致（部分 pandas 版本 nullable+ewm 还会触发
    # ``TypeError: float() argument must be a string or real number``）。
    # 业务上 K/D 中性值 50.0 与 RSI gain/loss 都是普通 float64 语义，固化更安全。
    sentinel = pd.Series([initial_value], dtype=np.float64)
    series_with_initial = pd.concat([sentinel, series_reset], ignore_index=True)

    result_with_initial = series_with_initial.ewm(alpha=alpha, adjust=False, ignore_na=True).mean()

    # 取除虚拟初始值外的结果（iloc[1:] 跳过位置 0 的哨兵种子）。
    # ``.copy()`` 必须保留：紧接着对 ``result_series`` 重新赋索引、又用
    # ``.where`` 重新生成结果。``iloc[1:]`` 返回的是 ``result_with_initial`` 的
    # 视图，直接对视图改 ``.index`` 会触发 pandas chained-assignment 行为
    # （部分版本抛 SettingWithCopyWarning，部分版本静默改不到目标），并且未来
    # ``result_with_initial`` 仍持有底层数组引用会造成误共享。维护时**禁止删除**
    # 此 ``.copy()``——它不是冗余而是切片解耦的必要操作。
    result_series = result_with_initial.iloc[1:].copy()
    # 用 ``set_axis`` 替代属性赋值 ``result_series.index = series.index``：
    # ``set_axis`` 是 pandas 官方推荐的链式 / 函数式 Index 替换 API，不依赖属性
    # 赋值副作用，跨 pandas 版本（含 2.x / 3.x）行为更稳定（R5 #3）。
    result_series = result_series.set_axis(series.index)

    # 恢复原始 NaN 位置
    result_series = result_series.where(series.notna(), float("nan"))

    return result_series


# ============================================================================
# 通用差分 helper（delta 子模块复用，半公开私有）
# 遵循 H5: 因子方向不预判，IC方向由数据决定
# ============================================================================


def _calculate_delta(
    factor_df: pd.DataFrame,
    base_col: str,
    delta_col: str,
    logger_arg: logging.Logger | None = None,
) -> pd.DataFrame:
    """通用差分计算：base_col(T) - base_col(T-1)，按asset分组shift

    参数:
        factor_df: 含 date, asset, base_col 的 DataFrame
        base_col: 原始因子列名（如 'amplitude'）
        delta_col: 差分因子列名（如 'amplitude_delta'）
        logger_arg: 可选 logger

    返回:
        factor_df 新增 delta_col 列。
        **行顺序契约**：返回 DataFrame 已按 ``[asset, date]`` 升序排序，与输入行顺序
        可能不同；调用方若依赖原始顺序需自行 ``reindex`` 或保存原索引后还原。

    边界处理:
        - 第一日无前值 → NaN（自然排除，不做填充）
        - 原始因子为 NaN → delta 也为 NaN（传播而非填充）
        - 按asset分组shift(1)，不跨股票

    Example:
        >>> df = pd.DataFrame({"asset": ["A", "A", "A"], "date": ["d1", "d2", "d3"], "amplitude": [0.04, 0.03, 0.05]})
        >>> result = _calculate_delta(df, "amplitude", "amplitude_delta")
        >>> pd.isna(result["amplitude_delta"].iloc[0])  # 第一日无前值
        True
        >>> result["amplitude_delta"].iloc[2]  # d3(0.05) - d2(0.03) = 0.02（时序差分，按 [asset,date] 排序后取前一行）
        0.02
    """
    _logger = get_module_logger(logger_arg)

    df = factor_df.copy()  # M11: DataFrame参数先copy
    df = df.sort_values([_COL_ASSET, _COL_DATE])

    # 按asset分组，获取前一日值
    prev_value = df.groupby(_COL_ASSET)[base_col].shift(1)

    # 差分计算：NaN传播（base_col或prev_value为NaN → delta为NaN）
    df[delta_col] = df[base_col] - prev_value

    valid_count = int(df[delta_col].notna().sum())
    total_count = len(df)
    # 高频批量调用场景下（factor_generator 一次跑数十个因子），INFO 日志会刷屏。
    # 降为 DEBUG：调试期可通过日志级别开关查看，生产期保持安静。
    # 显式括号（R5 #4）：``(valid_count / max(total_count, 1)) * 100`` 与 Python 默认
    # 优先级一致，但显式分组防止后续误改成整数除法 / 调括号时静默走错路径。
    _logger.debug(
        "差分因子 %s: 有效=%d (%.2f%%), base_col=%s",
        delta_col,
        valid_count,
        (valid_count / max(total_count, 1)) * 100,
        base_col,
    )

    return df


# ``_add_industry_column`` 已于 R2 (2026-06-16) 迁出至 ``_industry_helpers.py``
# （消除 §5.1 反向依赖：``_common.py`` 不再依赖 ``data_fetchers.fetch_industry``）。
# 包内调用：``from ._industry_helpers import _add_industry_column``。架构规范见 design.md。
