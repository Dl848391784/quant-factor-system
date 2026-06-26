"""格式化工具函数。

从 generate_factor_summary_report.py 迁移（v3.8 拆分重构）。
包含日期、权重、百分比、浮点数等格式化函数。
"""

from datetime import datetime

from summary.report.constants import (
    COL_TO_FACTOR_NAME_MAP,
    RETURN_DATA_IS_DECIMAL,
    _get_factor_abbr,
)


def get_date_str(date: str | None = None) -> str:
    """获取日期字符串

    Args:
        date: 指定日期字符串

    Returns:
        日期字符串（YYYY-MM-DD 格式）
    """
    if date:
        return date
    return datetime.now().strftime("%Y-%m-%d")


def get_monotonicity_symbol(quality: str) -> str:
    """获取单调性质量符号

    Args:
        quality: 单调性质量值（good/moderate/poor/unknown）

    Returns:
        单调性质量符号
    """
    symbols = {
        "good": "✓良好",
        "moderate": "△一般",
        "poor": "✗较差",
        "unknown": "?未知",
    }
    return symbols.get(quality, "?未知")


def get_weight_method_display(method: str) -> str:
    """获取权重方法显示名称

    Args:
        method: 权重方法名

    Returns:
        权重方法显示名称
    """
    displays = {
        "ic_weight": "IC加权",
        "icir_weight": "ICIR加权",
        "rolling_icir_weight": "Rolling ICIR加权",
        "equal_weight": "等权",
    }
    return displays.get(method, method)


def format_weights(weights: dict) -> str:
    """格式化权重字符串

    Args:
        weights: 权重字典（因子名或列名 → 权重值）

    Returns:
        格式化的权重字符串（如 "ts:60%, bp:40%")

    v2.22: 缩写表提取为模块级 FACTOR_ABBR + _get_factor_abbr；
           键归一化（列名→因子名）解决 vol/vr 不一致；
           权重 <0.5% 显示1位小数避免截断为 0%
    v2.23: 权重统一 :.1f 精度，与 Section 4/6 的 :.1f 保持一致
    """
    parts = []
    for factor, weight in weights.items():
        # v2.22: 归一化键——列名(如 volume_ratio_5)→因子名(如 volume_ratio)
        factor_name = COL_TO_FACTOR_NAME_MAP.get(factor, factor) or factor
        abbr = _get_factor_abbr(factor_name)
        pct = weight * 100
        # v2.23: 统一 1 位小数，与 Section 4/6 权重显示精度一致
        parts.append(f"{abbr}:{pct:.1f}%")

    return ", ".join(parts)


def format_percentage(value: float, decimals: int = 2) -> str:
    """格式化百分比

    Args:
        value: 数值（已转换为百分比，如 15.5 表示 15.5%）
        decimals: 小数位数

    Returns:
        格式化的百分比字符串
    """
    return f"{value:.{decimals}f}%"


def convert_return_to_percentage(decimal_value: float) -> float:
    """将小数形式的收益率转换为百分比

    原始数据中 long_short_return_annual 为小数形式（如 0.15 表示 15%）。
    此函数统一转换逻辑，避免多处重复 * 100。

    Args:
        decimal_value: 小数形式的收益率（如 0.15）

    Returns:
        百分比形式的收益率（如 15.0）

    Note:
        若上游数据格式变更（已经是百分比），需修改 RETURN_DATA_IS_DECIMAL 常量
    """
    if RETURN_DATA_IS_DECIMAL:
        return decimal_value * 100
    return decimal_value  # 数据已是百分比，直接返回


def format_float(value: float, decimals: int = 4) -> str:
    """格式化浮点数

    Args:
        value: 数值
        decimals: 小数位数

    Returns:
        格式化的浮点数字符串
    """
    return f"{value:.{decimals}f}"
