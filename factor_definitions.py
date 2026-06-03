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
    "get_factor_definition",
    "get_all_factor_names",
]

# ============================================================================
# 版本常量
# ============================================================================
__version__ = "1.0"
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
    "overnight_ret": "隔夜收益: (今日开盘-昨日收盘)/昨日收盘",
    # -------------------------------------------------------------------------
    # 尾盘因子（来自 factor_ic/ic_tail_*_1d.py）
    # -------------------------------------------------------------------------
    "tail_price_position": "尾盘价格位置: (收盘-尾盘最低)/(尾盘最高-尾盘最低)",
    "tail_price_slope": "尾盘趋势斜率: 线性回归斜率/均价(百分比)",
    "tail_price_volume_intensity": "尾盘量价强度: 尾盘涨跌幅×尾盘量比",
    "tail_volume_acceleration": "尾盘量能加速度: 后半段成交量/前半段成交量",
    "tail_volume_shrink": "尾盘缩量程度: 尾盘成交量总和/全天成交量(14:00-15:00)",
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
