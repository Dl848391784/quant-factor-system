#!/usr/bin/env python3
"""
因子定义统一管理模块

提供因子名称、计算公式、业务含义的单一数据源。
新增因子时只需在此模块添加定义，所有依赖模块自动同步。

遵循 PROJECT.md 规范：
- 使用 Python 标准库 logging 模块
- 公共模块函数接收 logger 参数
- 版本历史记录

版本历史：
- v1.0 (2026-06-02): 初始版本，整合 14 个因子定义
  - 从 summary/generate_factor_summary_report.py 迁移硬编码定义
  - 提供 get_factor_definition() 和 get_all_factor_names() 辅助函数
  - 新增单元测试 tests/test_factor_definitions.py
- v1.1 (2026-06-03): 补充缺失因子定义
  - 新增 intraday_intensity（日内价格强度）
  - 新增 volume_ratio_5（量比5日，与 volume_ratio 同义）
- v1.2 (2026-06-03): 新增尾盘缩量程度因子
  - 新增 tail_volume_shrink（尾盘缩量程度）
- v1.3 (2026-06-05): 补充 past_return_1d 定义
  - 新增 past_return_1d（过去1日涨幅，与 forward_return_1d 对称）
- v1.4 (2026-06-12): 新增8个方向性因子定义
  - 行业方向性因子3个：industry_momentum_5d, industry_turnover_trend, industry_amplitude_trend
  - 基本面方向性因子3个：industry_roe_trend, industry_earnings_growth, industry_pe_trend
  - 资金流方向性因子2个：capital_flow_ratio_trend, capital_flow_intensity
- v1.5 (2026-06-13): 新增 name↔col 单一映射来源（方案 B）
  - 新增 FACTOR_NAME_TO_COL_MAP（34 项，权威=factor_ic_data.json.gz 实际列名）
  - 新增 FACTOR_COL_TO_NAME_MAP（自动反向推导）
  - 新增 get_factor_col() / get_factor_name() 辅助函数
  - 修正历史 4 个错列名：kdj_j_9→kdj_j、bollinger_pb_20→bollinger_pb、
    turnover_surge_5→turnover_surge；删除死条目 main_inflow_ratio_1d
  - 详见 designs/factor_name_col_map_unification_design.md

作者: 云瑶
创建日期: 2026-06-02
"""

# ============================================================================
# 标准库导入
# ============================================================================

# ============================================================================
# 第三方库导入
# ============================================================================

# ============================================================================
# 类型导入
# ============================================================================

# ============================================================================
# 模块导出（遵循 MODULE.md 约束 60：不含私有名称）
# ============================================================================
__all__ = [
    "FACTOR_DEFINITIONS",
    "FACTOR_NAME_TO_COL_MAP",
    "FACTOR_COL_TO_NAME_MAP",
    "get_factor_definition",
    "get_all_factor_names",
    "get_factor_col",
    "get_factor_name",
]

# ============================================================================
# 版本常量
# ============================================================================
__version__ = "1.5"
__author__ = "云瑶"

# ============================================================================
# 因子定义字典
# ============================================================================
# 因子定义字典：因子逻辑名 → 定义信息
# 格式："因子名(参数): 计算公式/业务含义"
# 数据来源：
#   - 基础因子：data_fetchers/factor_calculator.py docstring
#   - 尾盘因子：factor_ic/ic_tail_*_1d.py 脚本说明

FACTOR_DEFINITIONS: dict[str, str] = {
    # -------------------------------------------------------------------------
    # 基础因子（来自 factor_calculator.py）
    # -------------------------------------------------------------------------
    "rsi": "RSI(6日): 相对强弱指标, 公式: RSI=100-100/(1+RS)",
    "volume_ratio": "量比(5日): 当日成交量/过去5日成交量均值",
    "volume_ratio_5": "量比(5日): 当日成交量/过去5日成交量均值",
    "kdj_j": "KDJ J值: J=3K-2D, K/D为RSV(9日)的平滑值",
    "bollinger_pb": "布林带%B: 收盘价在布林带中位置, %B=(close-lower)/(upper-lower)",
    "turnover_surge": "换手率突增(5日): 当日换手率/过去5日换手率均值",
    "amplitude": "振幅: (high-low)/close, 当日价格波动强度",
    "price_position": "价格位置: (close-low)/(high-low), 收盘价在振幅中位置",
    "intraday_intensity": "日内价格强度: (close-open)/(high-low), 收盘价在振幅中的相对位置",
    "return_3d": "3日累计涨幅: close[t]/close[t-3]-1",
    "return_5d": "5日累计涨幅: close[t]/close[t-5]-1",
    "past_return_1d": "过去1日涨幅: close[t]/close[t-1]-1, 与forward_return_1d对称",
    "overnight_ret": "隔夜收益: (今日开盘-昨日收盘)/昨日收盘",
    "momentum_strength": "动量强度: return_5d/std(return_1d,5日), 5日涨幅/5日波动率",
    # -------------------------------------------------------------------------
    # 尾盘因子（来自 factor_ic/ic_tail_*_1d.py）
    # -------------------------------------------------------------------------
    "tail_price_position": "尾盘价格位置: (收盘-尾盘最低)/(尾盘最高-尾盘最低)",
    "tail_price_slope": "尾盘趋势斜率: 线性回归斜率/均价(百分比)",
    "tail_price_volume_intensity": "尾盘量价强度: 尾盘涨跌幅×尾盘量比",
    "tail_volume_acceleration": "尾盘量能加速度: 后半段成交量/前半段成交量",
    "tail_volume_shrink": "尾盘缩量程度: 尾盘成交量总和/全天成交量(14:00-15:00)",
    # -------------------------------------------------------------------------
    # 方向性因子（Directional Factors，v1.14 2026-06-11）
    # 遵循 H5: IC方向不预判。实测IC均为负（A股均值回归效应压倒趋势延续）
    # -------------------------------------------------------------------------
    "volume_price_strength": "量价齐升强度: (close-open)/open × turnover_surge, 上涨+放量=强势",
    "positive_day_ratio_5": "近5日阳线比例: count(close>prev_close,5日)/5, 持续上涨=上升趋势",
    "ma5_deviation": "5日均线偏离度: (close-MA5)/MA5, 在均线之上=多头区域",
    "near_high_ratio_5": "近5日高低位置: (close-min(close,5))/(max(close,5)-min(close,5)), 接近高点=强势",
    # -------------------------------------------------------------------------
    # 差分因子（止跌信号维度，来自 factor_calculator.py v1.13）
    # -------------------------------------------------------------------------
    "amplitude_delta": "振幅差分: amplitude(T)-amplitude(T-1), 止跌放量信号",
    "turnover_surge_delta": "换手突增差分: turnover_surge(T)-turnover_surge(T-1), 关注回升信号",
    "tail_price_position_delta": "尾盘位置差分: tail_price_position(T)-tail_price_position(T-1), 买盘进场信号",
    "tail_volume_shrink_delta": "尾盘缩量差分: tail_volume_shrink(T)-tail_volume_shrink(T-1), 资金介入信号",
    # -------------------------------------------------------------------------
    # 行业方向性因子（Industry Directional Factors, v1.42 2026-06-12）
    # 行业层面趋势维度补充，实测IC正负由数据决定
    # -------------------------------------------------------------------------
    "industry_momentum_5d": "行业5日动量: 按(行业,日期)分组→mean(past_return_1d)→5日滚动均值, 方向性因子IC=+0.026",
    "industry_turnover_trend": "行业换手趋势: 按(行业,日期)分组→mean(turnover_surge)→5日滚动均值的变化量, 方向性因子IC=+0.023",
    "industry_amplitude_trend": "行业振幅趋势: 按(行业,日期)分组→mean(amplitude)→5日滚动均值的变化量, 方向性因子IC=+0.024",
    # -------------------------------------------------------------------------
    # 基本面方向性因子（Fundamental Directional Factors, v1.43 2026-06-12）
    # 行业基本面盈利趋势维度补充，季度数据前推填充对齐日频
    # -------------------------------------------------------------------------
    "industry_roe_trend": "行业ROE趋势: 行业ΔROE赋个股(ROE当前季度-ROE上季度), 方向性因子IC=+0.0325",
    "industry_earnings_growth": "行业盈利增长: 行业净利润增长率赋个股(年化YOY→行业均值), 方向性因子IC=+0.0255",
    "industry_pe_trend": "行业PE趋势: 行业ΔPE赋个股(PE当前季度-PE上季度, PE=close/annualized_eps), 负向因子IC=-0.015",
    # -------------------------------------------------------------------------
    # 资金流方向性因子（Capital Flow Directional Factors, v1.44 2026-06-12）
    # 行业资金流向趋势维度补充，覆盖率约26%(120交易日API限制)
    # -------------------------------------------------------------------------
    "capital_flow_ratio_trend": "资金流占比趋势: 行业Δ主力净流入占比赋个股(主力净流入/总成交额→行业均值→5日变化), 方向性因子IC=+0.0278",
    "capital_flow_intensity": "资金流强度: 行业|主力流入额|/总成交额赋个股(绝对额占比→行业均值), 方向性因子IC=+0.024, 覆盖26%",
}

# ============================================================================
# 辅助函数
# ============================================================================


def get_factor_definition(factor_name: str, default: str = "") -> str:
    """获取单个因子定义

    Args:
        factor_name: 因子逻辑名（如 'rsi', 'volume_ratio'）
        default: 未找到时的默认值（默认为空字符串）

    Returns:
        因子定义字符串

    Example:
        >>> from factor_definitions import get_factor_definition
        >>> get_factor_definition("rsi")
        'RSI(6日): 相对强弱指标, 公式: RSI=100-100/(1+RS)'
        >>> get_factor_definition("unknown_factor", "未知因子")
        '未知因子'
    """
    return FACTOR_DEFINITIONS.get(factor_name, default)


def get_all_factor_names() -> list[str]:
    """获取所有已定义的因子名称列表

    Returns:
        因子名称列表（按字典序排序）

    Example:
        >>> from factor_definitions import get_all_factor_names
        >>> names = get_all_factor_names()
        >>> "rsi" in names
        True
        >>> len(names)  # 当前定义了 17 个因子
        17
    """
    return sorted(FACTOR_DEFINITIONS.keys())


# ============================================================================
# 因子名 ↔ 数据列名 映射（v1.5 单一来源，方案 B）
# ============================================================================
# 权威来源：data_fetchers/result/factor_ic_data.json.gz 实际列名
# 历史教训（已修正）：
#   - kdj_j_9 → kdj_j（数据源不带 _9 后缀）
#   - bollinger_pb_20 → bollinger_pb（数据源不带 _20 后缀）
#   - turnover_surge_5 → turnover_surge（数据源不带 _5 后缀）
#   - main_inflow_ratio_1d 已删除（数据源中根本不存在该列）
# 仅 2 个因子的数据列名带后缀：rsi_6、volume_ratio_5
# 详见：designs/factor_name_col_map_unification_design.md §2.2

FACTOR_NAME_TO_COL_MAP: dict[str, str] = {
    # -------------------------------------------------------------------------
    # 基础因子（数据源带后缀的仅 2 个）
    # -------------------------------------------------------------------------
    "rsi": "rsi_6",
    "volume_ratio": "volume_ratio_5",
    # -------------------------------------------------------------------------
    # 基础因子（name == col，不带后缀）
    # -------------------------------------------------------------------------
    "kdj_j": "kdj_j",
    "bollinger_pb": "bollinger_pb",
    "turnover_surge": "turnover_surge",
    "amplitude": "amplitude",
    "price_position": "price_position",
    "intraday_intensity": "intraday_intensity",
    "return_3d": "return_3d",
    "return_5d": "return_5d",
    "past_return_1d": "past_return_1d",
    "overnight_ret": "overnight_ret",
    "momentum_strength": "momentum_strength",
    # -------------------------------------------------------------------------
    # 尾盘因子
    # -------------------------------------------------------------------------
    "tail_price_position": "tail_price_position",
    "tail_price_slope": "tail_price_slope",
    "tail_price_volume_intensity": "tail_price_volume_intensity",
    "tail_volume_acceleration": "tail_volume_acceleration",
    "tail_volume_shrink": "tail_volume_shrink",
    # -------------------------------------------------------------------------
    # 方向性因子（止跌信号 + 趋势维度）
    # -------------------------------------------------------------------------
    "volume_price_strength": "volume_price_strength",
    "positive_day_ratio_5": "positive_day_ratio_5",
    "ma5_deviation": "ma5_deviation",
    "near_high_ratio_5": "near_high_ratio_5",
    # -------------------------------------------------------------------------
    # 差分因子（止跌信号维度）
    # -------------------------------------------------------------------------
    "amplitude_delta": "amplitude_delta",
    "turnover_surge_delta": "turnover_surge_delta",
    "tail_price_position_delta": "tail_price_position_delta",
    "tail_volume_shrink_delta": "tail_volume_shrink_delta",
    # -------------------------------------------------------------------------
    # 行业方向性因子
    # -------------------------------------------------------------------------
    "industry_momentum_5d": "industry_momentum_5d",
    "industry_turnover_trend": "industry_turnover_trend",
    "industry_amplitude_trend": "industry_amplitude_trend",
    # -------------------------------------------------------------------------
    # 基本面方向性因子
    # -------------------------------------------------------------------------
    "industry_roe_trend": "industry_roe_trend",
    "industry_earnings_growth": "industry_earnings_growth",
    "industry_pe_trend": "industry_pe_trend",
    # -------------------------------------------------------------------------
    # 资金流方向性因子
    # -------------------------------------------------------------------------
    "capital_flow_ratio_trend": "capital_flow_ratio_trend",
    "capital_flow_intensity": "capital_flow_intensity",
}

# 反向映射：列名 → 因子名（自动推导，避免手工同步漂移）
FACTOR_COL_TO_NAME_MAP: dict[str, str] = {v: k for k, v in FACTOR_NAME_TO_COL_MAP.items()}


def get_factor_col(factor_name: str, default: str | None = None) -> str:
    """因子名 → 数据列名

    Args:
        factor_name: 因子逻辑名（如 'rsi', 'volume_ratio'）
        default: 未注册时的默认值；None 表示回退到 factor_name 本身

    Returns:
        数据列名（如 'rsi_6'），未注册时回退到 factor_name 本身

    Example:
        >>> get_factor_col("rsi")
        'rsi_6'
        >>> get_factor_col("kdj_j")
        'kdj_j'
        >>> get_factor_col("unknown_factor")  # 回退到自身
        'unknown_factor'
    """
    return FACTOR_NAME_TO_COL_MAP.get(factor_name, default if default is not None else factor_name)


def get_factor_name(col: str, default: str | None = None) -> str:
    """数据列名 → 因子逻辑名

    Args:
        col: 数据列名（如 'rsi_6', 'volume_ratio_5'）
        default: 未注册时的默认值；None 表示回退到 col 本身

    Returns:
        因子逻辑名（如 'rsi'），未注册时回退到 col 本身

    Example:
        >>> get_factor_name("rsi_6")
        'rsi'
        >>> get_factor_name("kdj_j")
        'kdj_j'
        >>> get_factor_name("unknown_col")  # 回退到自身
        'unknown_col'
    """
    return FACTOR_COL_TO_NAME_MAP.get(col, default if default is not None else col)
