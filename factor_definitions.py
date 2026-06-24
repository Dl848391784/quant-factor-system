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
- v1.6 (2026-06-20): 新增因子经济维度分类
  - 新增 FACTOR_CATEGORIES（34 项因子 → 8 维度映射）
  - 新增 CATEGORY_DIMENSIONS（维度列表）
  - 分类依据: 因子计算逻辑的经济含义（非统计相关性）
  - 8 维度: momentum/price_position/volume/tail_behavior/volatility/overnight/capital_flow/industry
  - 用途: factor_selector 维度内去重，避免跨维度误淘汰
  - 详见 designs/factor_classification_design.md

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
    "FACTOR_CATEGORIES",
    "FACTOR_FAMILIES",  # v2.40: 经济同源族（粗粒度，用于族级权重 cap）
    "CATEGORY_DIMENSIONS",
    "get_factor_definition",
    "get_all_factor_names",
    "get_factor_col",
    "get_factor_name",
]

# ============================================================================
# 版本常量
# ============================================================================
__version__ = "1.6"
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
    # v2.35: P5 补齐信息维度——趋势变化/量价背离因子
    "rsi_slope_3d": "RSI 3日斜率: RSI(6)的3日变化量, 正值=动量向上拐头",
    "ma5_slope": "MA5 3日斜率: 5日均线3日变化率, 正值=中期趋势向上",
    "lower_shadow_ratio": "下影线比: 下影线长度/全日振幅, 值大=低位有承接",
    "volume_shrink_rate": "缩量率: 当日成交量/5日均量, <1=缩量(卖盘衰竭)",
    "price_volume_divergence": "价跌量缩背离: -price_ret_5d * max(0, 1-vol_ratio), 正值=止跌信号",
    # v2.35: P5-补充——二阶导数企稳信号因子
    "return_acceleration_5d": "5日收益率加速度: return_5d(t) - return_5d(t-5), 正值=跌幅收窄",
    "downside_deceleration": "下跌减速: max(0, return_5d(t) - return_5d(t-5)) 当前期下跌, 正值=企稳",
    "amplitude_compression": "振幅收敛: 5日均振幅/10日均振幅, <1=波动收敛",
    "range_compression": "价格区间收敛: 5日价格区间/10日价格区间, <1=波动收敛",
    "volume_decay_rate": "量能衰减: 5日均量/10日均量, <1=量能衰减",
    "turnover_decay_rate": "换手率衰减: 当日换手率/5日平均换手率, <1=换手率下降",
    # v2.48 (designs/feat_factor_definition_destigmatization_v1.md v1.2): 交互因子族 27 变体
    # 第一性原理: ReLU 切半轴产生独立信号（pos/neg/abs 数学独立, ReLU 非线性破坏 affine 对称）。
    # 旧 v2.36/v2.37 公式 = -z(ret)×z(factor) 单边 weakness 预设方向; v2.48 改三 ReLU 变体,
    # 由 IC 闸口数据驱动淘汰, 不预设方向（AGENTS.md 数据驱动原则）。
    "interaction_amplitude__ret3d_pos": "max(z_cs(return_3d), 0) × z_cs(amplitude), 涨段启用(ReLU+)",
    "interaction_amplitude__ret3d_neg": "min(z_cs(return_3d), 0) × z_cs(amplitude), 跌段启用(ReLU-)",
    "interaction_amplitude__ret3d_abs": "|z_cs(return_3d)| × z_cs(amplitude), 按动幅启用(|ReLU|)",
    "interaction_turnover__ret3d_pos": "max(z_cs(return_3d), 0) × z_cs(turnover_rate), 涨段启用(ReLU+)",
    "interaction_turnover__ret3d_neg": "min(z_cs(return_3d), 0) × z_cs(turnover_rate), 跌段启用(ReLU-)",
    "interaction_turnover__ret3d_abs": "|z_cs(return_3d)| × z_cs(turnover_rate), 按动幅启用(|ReLU|)",
    "interaction_amp_compression__ret3d_pos": "max(z_cs(return_3d), 0) × z_cs(amplitude_compression), 涨段启用(ReLU+)",
    "interaction_amp_compression__ret3d_neg": "min(z_cs(return_3d), 0) × z_cs(amplitude_compression), 跌段启用(ReLU-)",
    "interaction_amp_compression__ret3d_abs": "|z_cs(return_3d)| × z_cs(amplitude_compression), 按动幅启用(|ReLU|)",
    "interaction_near_high__ret3d_pos": "max(z_cs(return_3d), 0) × z_cs(near_high_ratio_5), 涨段启用(ReLU+)",
    "interaction_near_high__ret3d_neg": "min(z_cs(return_3d), 0) × z_cs(near_high_ratio_5), 跌段启用(ReLU-)",
    "interaction_near_high__ret3d_abs": "|z_cs(return_3d)| × z_cs(near_high_ratio_5), 按动幅启用(|ReLU|)",
    "interaction_intraday__ret1d_pos": "max(z_cs(return_1d), 0) × z_cs(intraday_intensity), 涨段启用(ReLU+)",
    "interaction_intraday__ret1d_neg": "min(z_cs(return_1d), 0) × z_cs(intraday_intensity), 跌段启用(ReLU-)",
    "interaction_intraday__ret1d_abs": "|z_cs(return_1d)| × z_cs(intraday_intensity), 按动幅启用(|ReLU|)",
    "interaction_ma5_dev__ret3d_pos": "max(z_cs(return_3d), 0) × z_cs(ma5_deviation), 涨段启用(ReLU+)",
    "interaction_ma5_dev__ret3d_neg": "min(z_cs(return_3d), 0) × z_cs(ma5_deviation), 跌段启用(ReLU-)",
    "interaction_ma5_dev__ret3d_abs": "|z_cs(return_3d)| × z_cs(ma5_deviation), 按动幅启用(|ReLU|)",
    "interaction_price_pos__ret1d_pos": "max(z_cs(return_1d), 0) × z_cs(price_position), 涨段启用(ReLU+)",
    "interaction_price_pos__ret1d_neg": "min(z_cs(return_1d), 0) × z_cs(price_position), 跌段启用(ReLU-)",
    "interaction_price_pos__ret1d_abs": "|z_cs(return_1d)| × z_cs(price_position), 按动幅启用(|ReLU|)",
    "interaction_kdj__ret5d_pos": "max(z_cs(return_5d), 0) × z_cs(kdj_j), 涨段启用(ReLU+)",
    "interaction_kdj__ret5d_neg": "min(z_cs(return_5d), 0) × z_cs(kdj_j), 跌段启用(ReLU-)",
    "interaction_kdj__ret5d_abs": "|z_cs(return_5d)| × z_cs(kdj_j), 按动幅启用(|ReLU|)",
    "interaction_bollinger__ret5d_pos": "max(z_cs(return_5d), 0) × z_cs(bollinger_pb), 涨段启用(ReLU+)",
    "interaction_bollinger__ret5d_neg": "min(z_cs(return_5d), 0) × z_cs(bollinger_pb), 跌段启用(ReLU-)",
    "interaction_bollinger__ret5d_abs": "|z_cs(return_5d)| × z_cs(bollinger_pb), 按动幅启用(|ReLU|)",
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
    # v2.35: P5 新增因子（列名=因子名，无后缀）
    "rsi_slope_3d": "rsi_slope_3d",
    "ma5_slope": "ma5_slope",
    "lower_shadow_ratio": "lower_shadow_ratio",
    "volume_shrink_rate": "volume_shrink_rate",
    "price_volume_divergence": "price_volume_divergence",
    # v2.35: P5-补充
    "return_acceleration_5d": "return_acceleration_5d",
    "downside_deceleration": "downside_deceleration",
    "amplitude_compression": "amplitude_compression",
    "range_compression": "range_compression",
    "volume_decay_rate": "volume_decay_rate",
    "turnover_decay_rate": "turnover_decay_rate",
    # v2.36: 交互因子族 —— 条件因子方向方案 B
    "interaction_amplitude__ret3d_pos": "interaction_amplitude__ret3d_pos",
    "interaction_amplitude__ret3d_neg": "interaction_amplitude__ret3d_neg",
    "interaction_amplitude__ret3d_abs": "interaction_amplitude__ret3d_abs",
    "interaction_turnover__ret3d_pos": "interaction_turnover__ret3d_pos",
    "interaction_turnover__ret3d_neg": "interaction_turnover__ret3d_neg",
    "interaction_turnover__ret3d_abs": "interaction_turnover__ret3d_abs",
    "interaction_amp_compression__ret3d_pos": "interaction_amp_compression__ret3d_pos",
    "interaction_amp_compression__ret3d_neg": "interaction_amp_compression__ret3d_neg",
    "interaction_amp_compression__ret3d_abs": "interaction_amp_compression__ret3d_abs",
    "interaction_near_high__ret3d_pos": "interaction_near_high__ret3d_pos",
    "interaction_near_high__ret3d_neg": "interaction_near_high__ret3d_neg",
    "interaction_near_high__ret3d_abs": "interaction_near_high__ret3d_abs",
    "interaction_intraday__ret1d_pos": "interaction_intraday__ret1d_pos",
    "interaction_intraday__ret1d_neg": "interaction_intraday__ret1d_neg",
    "interaction_intraday__ret1d_abs": "interaction_intraday__ret1d_abs",
    "interaction_ma5_dev__ret3d_pos": "interaction_ma5_dev__ret3d_pos",
    "interaction_ma5_dev__ret3d_neg": "interaction_ma5_dev__ret3d_neg",
    "interaction_ma5_dev__ret3d_abs": "interaction_ma5_dev__ret3d_abs",
    "interaction_price_pos__ret1d_pos": "interaction_price_pos__ret1d_pos",
    "interaction_price_pos__ret1d_neg": "interaction_price_pos__ret1d_neg",
    "interaction_price_pos__ret1d_abs": "interaction_price_pos__ret1d_abs",
    "interaction_kdj__ret5d_pos": "interaction_kdj__ret5d_pos",
    "interaction_kdj__ret5d_neg": "interaction_kdj__ret5d_neg",
    "interaction_kdj__ret5d_abs": "interaction_kdj__ret5d_abs",
    "interaction_bollinger__ret5d_pos": "interaction_bollinger__ret5d_pos",
    "interaction_bollinger__ret5d_neg": "interaction_bollinger__ret5d_neg",
    "interaction_bollinger__ret5d_abs": "interaction_bollinger__ret5d_abs",
}

# 反向映射：列名 → 因子名（自动推导，避免手工同步漂移）
FACTOR_COL_TO_NAME_MAP: dict[str, str] = {v: k for k, v in FACTOR_NAME_TO_COL_MAP.items()}


# ============================================================================
# 因子经济维度分类（v1.6, 2026-06-20）
# ============================================================================
# 定义来源: 2026-06-20 因子多样性讨论，参考 AQR 4 类风格 + MSCI FaCS 5 类
# 分类依据: 因子计算逻辑的经济含义，不是统计相关性
# 用途: factor_selector.py 的 identify_high_corr_groups 维度内去重
#   - 同维度因子对, |corr|>0.7 → 合并去重（维度内冗余）
#   - 跨维度因子对, |corr|>0.9 → 合并去重（极端高相关兜底）
#   - 跨维度因子对, 0.7<|corr|≤0.9 → 保留（经济含义不同）
# 详见: designs/factor_classification_design.md

FACTOR_CATEGORIES: dict[str, str] = {
    # 动量/趋势 (9): 基于历史收益方向预测未来
    "momentum_strength": "momentum",
    "return_3d": "momentum",
    "return_5d": "momentum",
    "rsi": "momentum",
    "kdj_j": "momentum",
    "ma5_deviation": "momentum",
    "near_high_ratio_5": "momentum",
    "past_return_1d": "momentum",
    "positive_day_ratio_5": "momentum",
    # 价格位置 (4): 收盘价在当日/布林带/尾盘区间中的相对位置
    "price_position": "price_position",
    "bollinger_pb": "price_position",
    "tail_price_position": "price_position",
    "tail_price_position_delta": "price_position",
    # 量能 (5): 成交量/换手率维度的强度信号
    "volume_ratio": "volume",
    "turnover_surge": "volume",
    "turnover_surge_delta": "volume",
    "volume_price_strength": "volume",
    "intraday_intensity": "volume",
    # 尾盘行为 (5): 14:00-15:00 尾盘时段的量价特征
    "tail_price_slope": "tail_behavior",
    "tail_price_volume_intensity": "tail_behavior",
    "tail_volume_acceleration": "tail_behavior",
    "tail_volume_shrink": "tail_behavior",
    "tail_volume_shrink_delta": "tail_behavior",
    # 波动率 (2): 当日价格波动幅度
    "amplitude": "volatility",
    "amplitude_delta": "volatility",
    # 隔夜跳空 (1): 隔夜时段收益
    "overnight_ret": "overnight",
    # 资金流 (2): 主力资金流向趋势
    "capital_flow_ratio_trend": "capital_flow",
    "capital_flow_intensity": "capital_flow",
    # 行业 (6): 行业层面的动量/换手/振幅/基本面趋势
    "industry_momentum_5d": "industry",
    "industry_turnover_trend": "industry",
    "industry_amplitude_trend": "industry",
    "industry_roe_trend": "industry",
    "industry_earnings_growth": "industry",
    "industry_pe_trend": "industry",
    # v2.35: P5 补齐信息维度——趋势变化/量价背离因子
    "rsi_slope_3d": "momentum",  # RSI变化率，动量维度
    "ma5_slope": "momentum",  # 均线斜率，趋势维度
    "lower_shadow_ratio": "price_position",  # K线形态，价格位置维度
    "volume_shrink_rate": "volume",  # 缩量信号，量能维度
    "price_volume_divergence": "volume",  # 量价背离，量能维度
    # v2.35: P5-补充——二阶导数企稳信号因子维度归属
    "return_acceleration_5d": "momentum",  # 收益率加速度，价格动量维度
    "downside_deceleration": "momentum",  # 下跌减速，价格动量维度
    "amplitude_compression": "volatility",  # 振幅收敛，波动率维度
    "range_compression": "volatility",  # 价格区间收敛，波动率维度
    "volume_decay_rate": "volume",  # 量能衰减，量能维度
    "turnover_decay_rate": "volume",  # 换手率衰减，量能维度
    # v2.48: 27 交互变体, category 沿用 base factor 旧映射
    "interaction_amplitude__ret3d_pos": "momentum_x_volatility",
    "interaction_amplitude__ret3d_neg": "momentum_x_volatility",
    "interaction_amplitude__ret3d_abs": "momentum_x_volatility",
    "interaction_turnover__ret3d_pos": "momentum_x_volume",
    "interaction_turnover__ret3d_neg": "momentum_x_volume",
    "interaction_turnover__ret3d_abs": "momentum_x_volume",
    "interaction_amp_compression__ret3d_pos": "momentum_x_volatility",
    "interaction_amp_compression__ret3d_neg": "momentum_x_volatility",
    "interaction_amp_compression__ret3d_abs": "momentum_x_volatility",
    "interaction_near_high__ret3d_pos": "momentum_x_price_position",
    "interaction_near_high__ret3d_neg": "momentum_x_price_position",
    "interaction_near_high__ret3d_abs": "momentum_x_price_position",
    "interaction_intraday__ret1d_pos": "momentum_x_volume",
    "interaction_intraday__ret1d_neg": "momentum_x_volume",
    "interaction_intraday__ret1d_abs": "momentum_x_volume",
    "interaction_ma5_dev__ret3d_pos": "momentum_x_momentum",
    "interaction_ma5_dev__ret3d_neg": "momentum_x_momentum",
    "interaction_ma5_dev__ret3d_abs": "momentum_x_momentum",
    "interaction_price_pos__ret1d_pos": "momentum_x_price_position",
    "interaction_price_pos__ret1d_neg": "momentum_x_price_position",
    "interaction_price_pos__ret1d_abs": "momentum_x_price_position",
    "interaction_kdj__ret5d_pos": "momentum_x_momentum",
    "interaction_kdj__ret5d_neg": "momentum_x_momentum",
    "interaction_kdj__ret5d_abs": "momentum_x_momentum",
    "interaction_bollinger__ret5d_pos": "momentum_x_price_position",
    "interaction_bollinger__ret5d_neg": "momentum_x_price_position",
    "interaction_bollinger__ret5d_abs": "momentum_x_price_position",
}


# ============================================================================
# v2.40: 经济同源族（粗粒度分类，用于族级权重上限）
#
# 与 FACTOR_CATEGORIES 的区别:
#   - FACTOR_CATEGORIES (8 维度): 细粒度分类，用于维度感知去重 + 维度权重再分配
#   - FACTOR_FAMILIES (~8 族):   粗粒度经济同源聚合，用于族级权重 cap (30%)
#
# 设计动机 (designs/feat_family_weight_cap_and_liquidity_filter.md §3.1):
#   v2.39 验证后发现"振幅信号族" amplitude_compression (volatility) +
#   interaction_amp_compression (momentum_x_volatility) = 38.75% 权重，
#   绕过维度权重再分配（被标为两个不同维度）。
#
# 经济同源原则:
#   interaction_amp_compression 原始信号 = weakness × amplitude_compression_z
#   → 与 amplitude_compression 同源，应归入 amplitude_family
#
# 与 FACTOR_CATEGORIES 解耦:
#   族粒度由"信号原料"决定，不严格遵循维度命名空间。
#   维度命名空间可能因 weight_engine 维度再分配考虑分裂，但族粒度不分。
# ============================================================================
FACTOR_FAMILIES: dict[str, str] = {
    # === 振幅族 ===
    "amplitude": "amplitude_family",
    "amplitude_delta": "amplitude_family",
    "amplitude_compression": "amplitude_family",
    "range_compression": "amplitude_family",
    # amplitude_family 中的 v2.48 交互变体
    "interaction_amplitude__ret3d_pos": "amplitude_family",
    "interaction_amplitude__ret3d_neg": "amplitude_family",
    "interaction_amplitude__ret3d_abs": "amplitude_family",
    "interaction_amp_compression__ret3d_pos": "amplitude_family",
    "interaction_amp_compression__ret3d_neg": "amplitude_family",
    "interaction_amp_compression__ret3d_abs": "amplitude_family",
    # === 量能族（成交量 / 换手率） ===
    "volume_ratio": "volume_family",
    "volume_decay_rate": "volume_family",
    "volume_shrink_rate": "volume_family",
    "volume_price_strength": "volume_family",
    "price_volume_divergence": "volume_family",
    "turnover_surge": "volume_family",
    "turnover_surge_delta": "volume_family",
    "turnover_decay_rate": "volume_family",
    # volume_family 中的 v2.48 交互变体
    "interaction_turnover__ret3d_pos": "volume_family",
    "interaction_turnover__ret3d_neg": "volume_family",
    "interaction_turnover__ret3d_abs": "volume_family",
    "interaction_intraday__ret1d_pos": "volume_family",
    "interaction_intraday__ret1d_neg": "volume_family",
    "interaction_intraday__ret1d_abs": "volume_family",
    "intraday_intensity": "volume_family",
    # === 价格位置族 ===
    "price_position": "price_family",
    "bollinger_pb": "price_family",
    "tail_price_position": "price_family",
    "tail_price_position_delta": "price_family",
    # price_family 中的 v2.48 交互变体
    "interaction_near_high__ret3d_pos": "price_family",
    "interaction_near_high__ret3d_neg": "price_family",
    "interaction_near_high__ret3d_abs": "price_family",
    "interaction_price_pos__ret1d_pos": "price_family",
    "interaction_price_pos__ret1d_neg": "price_family",
    "interaction_price_pos__ret1d_abs": "price_family",
    "interaction_bollinger__ret5d_pos": "price_family",
    "interaction_bollinger__ret5d_neg": "price_family",
    "interaction_bollinger__ret5d_abs": "price_family",
    # === 动量族 ===
    "momentum_strength": "momentum_family",
    "return_3d": "momentum_family",
    "return_5d": "momentum_family",
    "rsi": "momentum_family",
    "kdj_j": "momentum_family",
    "ma5_deviation": "momentum_family",
    "ma5_slope": "momentum_family",
    "rsi_slope_3d": "momentum_family",
    "near_high_ratio_5": "momentum_family",
    "past_return_1d": "momentum_family",
    "positive_day_ratio_5": "momentum_family",
    "return_acceleration_5d": "momentum_family",
    "downside_deceleration": "momentum_family",
    # momentum_family 中的 v2.48 交互变体
    "interaction_ma5_dev__ret3d_pos": "momentum_family",
    "interaction_ma5_dev__ret3d_neg": "momentum_family",
    "interaction_ma5_dev__ret3d_abs": "momentum_family",
    "interaction_kdj__ret5d_pos": "momentum_family",
    "interaction_kdj__ret5d_neg": "momentum_family",
    "interaction_kdj__ret5d_abs": "momentum_family",
    # === 尾盘行为族 ===
    "tail_price_slope": "tail_family",
    "tail_price_volume_intensity": "tail_family",
    "tail_volume_acceleration": "tail_family",
    "tail_volume_shrink": "tail_family",
    "tail_volume_shrink_delta": "tail_family",
    # === 隔夜族 ===
    "overnight_ret": "overnight_family",
    # === 资金流族 ===
    "capital_flow_ratio_trend": "capital_flow_family",
    "capital_flow_intensity": "capital_flow_family",
    # === 行业族 ===
    "industry_momentum_5d": "industry_family",
    "industry_turnover_trend": "industry_family",
    "industry_amplitude_trend": "industry_family",
    "industry_roe_trend": "industry_family",
    "industry_earnings_growth": "industry_family",
    "industry_pe_trend": "industry_family",
    # === 其他/未归类（独立族，不被族 cap 主导） ===
    "lower_shadow_ratio": "uncategorized_family",
}

# 维度列表（用于遍历，顺序无特殊含义）
CATEGORY_DIMENSIONS: list[str] = [
    "momentum",
    "price_position",
    "volume",
    "tail_behavior",
    "volatility",
    "overnight",
    "capital_flow",
    "industry",
    # v2.36: 交互因子复合维度
    "momentum_x_volatility",
    "momentum_x_volume",
    "momentum_x_price_position",
    "momentum_x_momentum",
]

# ============================================================================
# v2.35: P6 角色化权重体系——因子角色定义
# 遵循 designs/strategy_systemic_overhaul.md §2.6 决策点1/4
#
# 三角色体系（公理2: 反转需确认信号，非纯反转赌注）:
#   primary      → 主信号: 反转触发, ICIR+维度权重加权
#   confirmation → 确认信号: 趋势变化/量价背离确认, 固定权重各5%
#   filter       → 过滤器: 基本面恶化硬过滤（批次8在stock_selector执行）
#
# 角色是因子固有属性（类似维度分类），与 FACTOR_CATEGORIES 同级。
# 默认所有因子为 primary；P5 新增5个趋势变化/量价背离因子为 confirmation。
# ============================================================================
FACTOR_ROLES: dict[str, str] = {
    # --- 主信号（反转触发）---
    # 所有现有因子默认为 primary（34个）
    **{
        name: "primary"
        for name in FACTOR_CATEGORIES
        if name
        not in {
            "rsi_slope_3d",
            "ma5_slope",
            "lower_shadow_ratio",
            "volume_shrink_rate",
            "price_volume_divergence",
            # v2.35: P5-补充6个二阶导数因子
            "return_acceleration_5d",
            "downside_deceleration",
            "amplitude_compression",
            "range_compression",
            "volume_decay_rate",
            "turnover_decay_rate",
            # v2.48: 27 交互变体 (pos/neg/abs ReLU 切半轴, designs/feat_factor_definition_destigmatization_v1.md v1.2)
            "interaction_amplitude__ret3d_pos",
            "interaction_amplitude__ret3d_neg",
            "interaction_amplitude__ret3d_abs",
            "interaction_turnover__ret3d_pos",
            "interaction_turnover__ret3d_neg",
            "interaction_turnover__ret3d_abs",
            "interaction_amp_compression__ret3d_pos",
            "interaction_amp_compression__ret3d_neg",
            "interaction_amp_compression__ret3d_abs",
            "interaction_near_high__ret3d_pos",
            "interaction_near_high__ret3d_neg",
            "interaction_near_high__ret3d_abs",
            "interaction_intraday__ret1d_pos",
            "interaction_intraday__ret1d_neg",
            "interaction_intraday__ret1d_abs",
            "interaction_ma5_dev__ret3d_pos",
            "interaction_ma5_dev__ret3d_neg",
            "interaction_ma5_dev__ret3d_abs",
            "interaction_price_pos__ret1d_pos",
            "interaction_price_pos__ret1d_neg",
            "interaction_price_pos__ret1d_abs",
            "interaction_kdj__ret5d_pos",
            "interaction_kdj__ret5d_neg",
            "interaction_kdj__ret5d_abs",
            "interaction_bollinger__ret5d_pos",
            "interaction_bollinger__ret5d_neg",
            "interaction_bollinger__ret5d_abs",
        }
    },
    # --- 确认信号（趋势变化/量价背离/二阶导数企稳）---
    # v2.35: P5 新增5个 + P5-补充6个因子，IC可能低于0.03门槛，用固定权重避免ICIR加权给0权重
    "rsi_slope_3d": "confirmation",
    "ma5_slope": "confirmation",
    "lower_shadow_ratio": "confirmation",
    "volume_shrink_rate": "confirmation",
    "price_volume_divergence": "confirmation",
    # v2.35: P5-补充——二阶导数企稳信号因子
    "return_acceleration_5d": "confirmation",
    "downside_deceleration": "confirmation",
    "amplitude_compression": "confirmation",
    "range_compression": "confirmation",
    "volume_decay_rate": "confirmation",
    "turnover_decay_rate": "confirmation",
    # v2.48: 27 交互变体统一默认 confirmation, 由 F2 IC 闸口数据驱动决定后续升级 primary
    # (旧 v2.37 区分 confirmation/primary 基于 IC 强度, 新变体 IC 尚未跑出, 全部走 confirmation)
    "interaction_amplitude__ret3d_pos": "confirmation",
    "interaction_amplitude__ret3d_neg": "confirmation",
    "interaction_amplitude__ret3d_abs": "confirmation",
    "interaction_turnover__ret3d_pos": "confirmation",
    "interaction_turnover__ret3d_neg": "confirmation",
    "interaction_turnover__ret3d_abs": "confirmation",
    "interaction_amp_compression__ret3d_pos": "confirmation",
    "interaction_amp_compression__ret3d_neg": "confirmation",
    "interaction_amp_compression__ret3d_abs": "confirmation",
    "interaction_near_high__ret3d_pos": "confirmation",
    "interaction_near_high__ret3d_neg": "confirmation",
    "interaction_near_high__ret3d_abs": "confirmation",
    "interaction_intraday__ret1d_pos": "confirmation",
    "interaction_intraday__ret1d_neg": "confirmation",
    "interaction_intraday__ret1d_abs": "confirmation",
    "interaction_ma5_dev__ret3d_pos": "confirmation",
    "interaction_ma5_dev__ret3d_neg": "confirmation",
    "interaction_ma5_dev__ret3d_abs": "confirmation",
    "interaction_price_pos__ret1d_pos": "confirmation",
    "interaction_price_pos__ret1d_neg": "confirmation",
    "interaction_price_pos__ret1d_abs": "confirmation",
    "interaction_kdj__ret5d_pos": "confirmation",
    "interaction_kdj__ret5d_neg": "confirmation",
    "interaction_kdj__ret5d_abs": "confirmation",
    "interaction_bollinger__ret5d_pos": "confirmation",
    "interaction_bollinger__ret5d_neg": "confirmation",
    "interaction_bollinger__ret5d_abs": "confirmation",
    # --- 过滤器（基本面恶化，硬过滤）---
    # 第一性原理: master_l1_l6_roadmap.md §2.3
    # 阈值依据: 5 日累计 -10% = 券商风控经验, A 股 ST 警示线邻近
    # 注意: 该因子值由 stock_selector 实时从 return_5d 派生, 非 factor_generator 计算
    "cum_return_5d_breakdown": "filter",
}

# 角色列表（用于遍历）
FACTOR_ROLE_TYPES: list[str] = ["primary", "confirmation", "filter"]

# 确认信号固定权重（design.md §2.6 决策点2: 方案B 主信号75%+确认信号25%）
CONFIRMATION_WEIGHT_PER_FACTOR = 0.05  # 每个确认因子5%（5个共25%）
PRIMARY_WEIGHT_TOTAL = 0.75  # 主信号共75%


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
