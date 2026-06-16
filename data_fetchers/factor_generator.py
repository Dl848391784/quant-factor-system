#!/usr/bin/env python3
"""
统一因子生成模块

职责：生成所有因子数据到缓存，提供单一数据源

Requires: Python >= 3.8 (gzip.BadGzipFile 异常类)

使用前提：
- 包内导入优先（from .common / .factor_calculator）
- 脚本直接运行时（python data_fetchers/factor_generator.py）走 except ImportError 分支，
  自动注入 project_root 到 sys.path 后改用绝对导入，无需手动设置 PYTHONPATH

遵循 PROJECT.md 规范：
- 输出到 data_fetchers/result/
- 复用公共模块计算函数（遵循强制复用规范）
- 公共模块接收 logger 参数（遵循 PROJECT.md 公共模块日志规范）

版本历史：见 git log。

作者: 云瑶
"""

import argparse
import gzip
import json
import logging
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd


# ============================================================================
# 条件导入：包内导入优先；脚本直接运行时（无父包）回退到绝对导入 + sys.path 注入
# 单一来源：避免 if/else 重复列举导入符号（约束 #3 复用 factor_calculator）
# ============================================================================
try:
    from .common.logger_config import setup_logger
    from .factor_calculator import (
        calculate_amplitude,
        calculate_amplitude_delta,
        calculate_bollinger_pb,
        calculate_capital_flow_intensity,
        calculate_capital_flow_ratio_trend,
        calculate_industry_amplitude_trend,
        calculate_industry_earnings_growth,
        calculate_industry_momentum_5d,
        calculate_industry_pe_trend,
        calculate_industry_roe_trend,
        calculate_industry_turnover_trend,
        calculate_intraday_intensity,
        calculate_kdj_j,
        calculate_ma5_deviation,
        calculate_momentum_strength,
        calculate_near_high_ratio_5,
        calculate_overnight_return,
        calculate_past_return_1d,
        calculate_positive_day_ratio_5,
        calculate_price_position,
        calculate_return_5d,
        calculate_tail_factors,
        calculate_tail_price_position_delta,
        calculate_tail_volume_shrink_delta,
        calculate_turnover_surge,
        calculate_turnover_surge_delta,
        calculate_volume_price_strength,
    )
except ImportError:
    # 脚本直接运行（无父包上下文）：将项目根注入 sys.path 后改用绝对导入
    project_root = Path(__file__).parent.parent
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))
    from data_fetchers.common.logger_config import setup_logger
    from data_fetchers.factor_calculator import (
        calculate_amplitude,
        calculate_amplitude_delta,
        calculate_bollinger_pb,
        calculate_capital_flow_intensity,
        calculate_capital_flow_ratio_trend,
        calculate_industry_amplitude_trend,
        calculate_industry_earnings_growth,
        calculate_industry_momentum_5d,
        calculate_industry_pe_trend,
        calculate_industry_roe_trend,
        calculate_industry_turnover_trend,
        calculate_intraday_intensity,
        calculate_kdj_j,
        calculate_ma5_deviation,
        calculate_momentum_strength,
        calculate_near_high_ratio_5,
        calculate_overnight_return,
        calculate_past_return_1d,
        calculate_positive_day_ratio_5,
        calculate_price_position,
        calculate_return_5d,
        calculate_tail_factors,
        calculate_tail_price_position_delta,
        calculate_tail_volume_shrink_delta,
        calculate_turnover_surge,
        calculate_turnover_surge_delta,
        calculate_volume_price_strength,
    )

# ============================================================================
# 模块级 fallback logger（遵循 PROJECT.md 公共模块日志规范）
# ============================================================================
_MODULE_LOGGER = logging.getLogger("data_fetchers.factor_generator")

# ============================================================================
# 公共 API 导出
# ============================================================================
__all__ = [
    "generate_all_factors",
    "get_module_logger",
]

# ============================================================================
# 默认路径配置（私有常量）
# ============================================================================

# 输入输出数据路径（result 目录：统一数据源，遵循 PROJECT.md 跨模块数据路径规范）
# 数据由 fetch_factor_cache.py 和 fetch_turnover.py 输出到 result 目录，本模块从该目录读取并输出
# parent=data_fetchers/, 路径为 data_fetchers/result/
# 注：输入输出路径相同，若未来需分离可再拆分常量
_DEFAULT_RESULT_DIR = Path(__file__).parent / "result"

# 扩展因子列名（元组防止意外修改）
# v1.33 新增尾盘因子：tail_price_position, tail_price_slope, tail_price_volume_intensity
# v1.34 新增隔夜收益率因子：overnight_ret（跳空幅度）
# v1.35 新增尾盘量能加速度因子：tail_volume_acceleration（后半段/前半段成交量比）
# v1.37 新增动量强度因子：momentum_strength（5日涨幅/5日波动率）
_EXTENDED_FACTOR_COLS: tuple[str, ...] = (
    "past_return_1d",  # 当日涨跌幅（遵循 PROJECT.md 规则：因子计算在 data_fetchers 完成）
    "bollinger_pb",
    "kdj_j",
    "turnover_surge",
    "amplitude",
    "price_position",
    "return_5d",  # v1.37 新增：5日累计涨幅（momentum_strength 的前置依赖）
    "momentum_strength",  # v1.37 新增：动量强度因子
    "overnight_ret",
    "intraday_intensity",
    "tail_price_position",
    "tail_price_slope",
    "tail_price_volume_intensity",
    "tail_volume_acceleration",
    "tail_volume_shrink",
    "amplitude_delta",  # v1.40 新增：振幅差分因子
    "turnover_surge_delta",  # v1.40 新增：换手突增差分因子
    "tail_price_position_delta",  # v1.40 新增：尾盘位置差分因子
    "tail_volume_shrink_delta",  # v1.40 新增：尾盘缩量差分因子
    "volume_price_strength",  # v1.41 新增：量价齐升因子
    "positive_day_ratio_5",  # v1.41 新增：5日阳线比例因子
    "ma5_deviation",  # v1.41 新增：5日均线偏离度因子
    "near_high_ratio_5",  # v1.41 新增：近5日高低位置因子
    "industry_momentum_5d",  # v1.42 新增：行业5日动量因子
    "industry_turnover_trend",  # v1.42 新增：行业换手率趋势因子
    "industry_amplitude_trend",  # v1.42 新增：行业振幅趋势因子
    "industry_roe_trend",  # v1.43 新增：行业ROE趋势因子（方案B）
    "industry_earnings_growth",  # v1.43 新增：行业盈利增长因子（方案B）
    "industry_pe_trend",  # v1.43 新增：行业PE趋势因子（方案B）
    "capital_flow_ratio_trend",  # v1.44 新增：资金流占比趋势因子（方案C）
    "capital_flow_intensity",  # v1.44 新增：资金流强度因子（方案C）
)

# 收益数据列名（元组防止意外修改）
_RETURN_COLS: tuple[str, ...] = ("forward_return_1d", "forward_return_3d", "forward_return_5d")

# 基础列名（元组防止意外修改）
# 包含：索引字段 + 行情数据 + 基础因子 + 换手率（从换手率数据合并）+ 成交量（尾盘量比计算需要）
_BASE_COLS: tuple[str, ...] = (
    "date",
    "asset",
    "open",
    "close",
    "high",
    "low",
    "rsi_6",
    "volume_ratio_5",
    "turnover_rate",
    "volume",
)

# 输出列名：基础列 + 扩展因子 + 收益数据（元组防止意外修改）
# 组成：_BASE_COLS(10) + _EXTENDED_FACTOR_COLS(15) + _RETURN_COLS(3)
_OUTPUT_COLS: tuple[str, ...] = _BASE_COLS + _EXTENDED_FACTOR_COLS + _RETURN_COLS


# ============================================================================
# 模块级私有辅助函数
# ============================================================================


def _calc_pct(count: int, total: int) -> float:
    """
    计算百分比（除零保护）

    Args:
        count: 记录数（分子，如有效记录数、缺失记录数等），支持 int 或兼容类型
        total: 总记录数（分母），支持 int 或兼容类型

    Returns:
        float: 百分比（0.0-100.0），空数据时返回 0.0

    Example:
        >>> _calc_pct(80, 100)  # 有效记录百分比
        80.0
        >>> _calc_pct(20, 100)  # 缺失记录百分比
        20.0
        >>> _calc_pct(50, 0)  # 空数据，返回 0.0
        0.0

    Note:
        - 通用百分比计算函数，可用于有效记录、缺失记录等场景
        - 参数语义由调用方决定（count 是分子，total 是分母）
        - 类型注解为 int，但实际接受 int、numpy.int64、float 等兼容类型
        - Python 运行时不强制类型检查，注解仅为静态分析提供参考
    """
    if total <= 0:
        return 0.0
    return round(count / total * 100, 2)


# ============================================================================
# logger 获取函数（遵循 PROJECT.md 公共模块日志规范）
# ============================================================================


def get_module_logger(logger: logging.Logger | None = None) -> logging.Logger:
    """
    获取模块 logger

    Args:
        logger: 调用方传入的 logger（可选）

    Returns:
        logging.Logger: 模块 logger

    Raises:
        TypeError: logger 参数不是 logging.Logger 类型

    Note:
        - 如果 logger 为 None，返回模块级 fallback logger
        - 公共模块接收 logger 参数，日志可追溯调用方

    Example:
        >>> logger = get_module_logger()
        >>> logger.name
        'data_fetchers.factor_generator'
        >>> custom_logger = get_module_logger(logging.getLogger("my_app"))
        >>> custom_logger.name
        'my_app'
    """
    if logger is None:
        return _MODULE_LOGGER
    if not isinstance(logger, logging.Logger):
        raise TypeError(f"logger 必须是 logging.Logger 类型，实际类型: {type(logger).__name__}")
    return logger


# ============================================================================
# 统一因子生成入口
# ============================================================================


def generate_all_factors(
    factor_data_path: Path | str | None = None,
    turnover_data_path: Path | str | None = None,
    return_data_path: Path | str | None = None,
    output_path: Path | str | None = None,
    logger: logging.Logger | None = None,
) -> dict[str, Any]:
    """
    生成所有因子数据（含收益数据）

    Args:
        factor_data_path: 基础因子数据路径（默认 factor_data.json.gz）
        turnover_data_path: 换手率数据路径（默认 turnover_rate_data.json.gz）
        return_data_path: 收益数据路径（默认 return_data.json.gz）
        output_path: 输出路径（默认 factor_ic_data.json.gz）
        logger: 调用方传入的 logger（可选）

    Returns:
        Dict[str, Any]: 元数据字典（包含生成时间、因子列表、运行耗时等）

    Raises:
        FileNotFoundError: 输入数据文件不存在
        ValueError: 数据格式不正确（缺少 'data' 字段）、JSON 解析失败、gzip 文件损坏
        KeyError: 必需字段不存在（输出列不存在）
        RuntimeError: 文件系统错误（磁盘/权限/IO）或未知保存错误

    Note:
        - 输出到 data_fetchers/result/factor_ic_data.json.gz
        - 复用 factor_calculator 计算函数（遵循强制复用规范）
        - 公共模块接收 logger 参数，日志可追溯调用方
        - 运行耗时统计方便性能分析
        - 空数据场景：所有百分比计算均有除零保护，返回 0.0
        - JSONDecodeError 已内部捕获并转换为 ValueError，调用方不会收到 JSONDecodeError

    Example:
        # 以下为示例用法，非实际运行（generate_all_factors 需要输入数据文件）
        >>> from data_fetchers.factor_generator import generate_all_factors
        >>> metadata = generate_all_factors()  # 需要 data_fetchers/result/*.json.gz
        >>> metadata["factor_columns"]  # 返回列表副本，防止外部修改
        ['bollinger_pb', 'kdj_j', 'turnover_surge']
        >>> isinstance(metadata["elapsed_seconds"], float)
        True
    """
    start_time = datetime.now()
    logger = get_module_logger(logger)

    # 默认路径
    factor_data_path = Path(factor_data_path) if factor_data_path else _DEFAULT_RESULT_DIR / "factor_data.json.gz"
    turnover_data_path = (
        Path(turnover_data_path) if turnover_data_path else _DEFAULT_RESULT_DIR / "turnover_rate_data.json.gz"
    )
    return_data_path = Path(return_data_path) if return_data_path else _DEFAULT_RESULT_DIR / "return_data.json.gz"
    output_path = Path(output_path) if output_path else _DEFAULT_RESULT_DIR / "factor_ic_data.json.gz"

    logger.info("=" * 40)
    logger.info("统一因子生成模块")
    logger.info("=" * 40)

    # ========== Step 1: 加载基础因子数据 ==========
    logger.info("Step 1: 加载基础因子数据...")

    try:
        with gzip.open(factor_data_path, "rt", encoding="utf-8") as f:
            base_data = json.load(f)
    except FileNotFoundError:
        raise FileNotFoundError(f"基础因子数据文件不存在: {factor_data_path}") from None
    except gzip.BadGzipFile as e:
        logger.error("gzip 文件损坏: %s, 原因: %s", factor_data_path, str(e))
        raise ValueError(f"gzip 文件损坏: {factor_data_path}") from e
    except json.JSONDecodeError as e:
        # JSONDecodeError 内存优化：提取关键信息，避免 e.doc 内存翻倍
        # 将行列信息合并到异常消息，由调用方统一决定是否记录日志
        raise ValueError(f"JSON解析失败: {factor_data_path}, 行 {e.lineno}, 列 {e.colno}, 信息: {e.msg}") from e

    # 数据验证：检查 'data' 字段存在
    if "data" not in base_data:
        raise ValueError(f"基础因子数据缺少 'data' 字段: {factor_data_path}")

    factor_df = pd.DataFrame(base_data["data"])
    factor_df["date"] = pd.to_datetime(factor_df["date"])

    # 显式释放 base_data 内存（JSON 加载的大对象）
    del base_data

    logger.info("  基础数据记录数: %d", len(factor_df))
    logger.info("  基础因子列: rsi_6, volume_ratio_5")

    # ========== Step 2: 加载换手率数据 ==========
    logger.info("Step 2: 加载换手率数据...")

    try:
        with gzip.open(turnover_data_path, "rt", encoding="utf-8") as f:
            turnover_data = json.load(f)
    except FileNotFoundError:
        raise FileNotFoundError(f"换手率数据文件不存在: {turnover_data_path}") from None
    except gzip.BadGzipFile as e:
        logger.error("gzip 文件损坏: %s, 原因: %s", turnover_data_path, str(e))
        raise ValueError(f"gzip 文件损坏: {turnover_data_path}") from e
    except json.JSONDecodeError as e:
        # JSONDecodeError 内存优化：提取关键信息，避免 e.doc 内存翻倍
        # 将行列信息合并到异常消息，由调用方统一决定是否记录日志
        raise ValueError(f"JSON解析失败: {turnover_data_path}, 行 {e.lineno}, 列 {e.colno}, 信息: {e.msg}") from e

    # 数据验证：检查 'data' 字段存在
    if "data" not in turnover_data:
        raise ValueError(f"换手率数据缺少 'data' 字段: {turnover_data_path}")

    turnover_df = pd.DataFrame(turnover_data["data"])
    # 使用 format='mixed' 处理不同日期格式（有的带时间，有的不带）
    turnover_df["date"] = pd.to_datetime(turnover_df["date"], format="mixed")

    # 显式释放 turnover_data 内存（JSON 加载的大对象）
    del turnover_data

    logger.info("  换手率数据记录数: %d", len(turnover_df))

    # 合并换手率
    factor_df = factor_df.merge(turnover_df[["date", "asset", "turnover_rate"]], on=["date", "asset"], how="left")

    # 显式释放 turnover_df 内存（merge 完成后不再需要）
    del turnover_df

    # 检查换手率缺失情况
    turnover_missing = int(factor_df["turnover_rate"].isna().sum())
    if turnover_missing > 0:
        logger.warning("  换手率缺失记录数: %d (%.2f%%)", turnover_missing, _calc_pct(turnover_missing, len(factor_df)))

    logger.info("  合并后记录数: %d", len(factor_df))

    # ========== Step 3: 加载收益数据 ==========
    logger.info("Step 3: 加载收益数据...")

    try:
        with gzip.open(return_data_path, "rt", encoding="utf-8") as f:
            return_data = json.load(f)
    except FileNotFoundError:
        raise FileNotFoundError(f"收益数据文件不存在: {return_data_path}") from None
    except gzip.BadGzipFile as e:
        logger.error("gzip 文件损坏: %s, 原因: %s", return_data_path, str(e))
        raise ValueError(f"gzip 文件损坏: {return_data_path}") from e
    except json.JSONDecodeError as e:
        # JSONDecodeError 内存优化：提取关键信息，避免 e.doc 内存翻倍
        # 将行列信息合并到异常消息，由调用方统一决定是否记录日志
        raise ValueError(f"JSON解析失败: {return_data_path}, 行 {e.lineno}, 列 {e.colno}, 信息: {e.msg}") from e

    # 数据验证：检查 'data' 字段存在
    if "data" not in return_data:
        raise ValueError(f"收益数据缺少 'data' 字段: {return_data_path}")

    return_df = pd.DataFrame(return_data["data"])
    return_df["date"] = pd.to_datetime(return_df["date"], format="mixed")

    # 显式释放 return_data 内存（JSON 加载的大对象）
    del return_data

    logger.info("  收益数据记录数: %d", len(return_df))

    # 合并收益数据
    factor_df = factor_df.merge(return_df[["date", "asset"] + list(_RETURN_COLS)], on=["date", "asset"], how="left")

    # 显式释放 return_df 内存（merge 完成后不再需要）
    del return_df

    # 检查收益数据缺失情况
    for col in _RETURN_COLS:
        return_missing = int(factor_df[col].isna().sum())
        if return_missing > 0:
            logger.warning(
                "  %s 缺失记录数: %d (%.2f%%)", col, return_missing, _calc_pct(return_missing, len(factor_df))
            )

    logger.info("  合并收益后记录数: %d", len(factor_df))

    # ========== Step 3.5: 计算 past_return_1d（当日涨跌幅） ==========
    logger.info("Step 3.5: 计算当日涨跌幅因子...")

    factor_df = calculate_past_return_1d(factor_df, logger_arg=logger)

    past_return_valid = int(factor_df["past_return_1d"].notna().sum())
    logger.info("  有效 past_return_1d: %d (%.2f%%)", past_return_valid, _calc_pct(past_return_valid, len(factor_df)))

    # ========== Step 4: 计算 bollinger_pb ==========
    logger.info("Step 4: 计算布林带 %B 因子...")

    factor_df = calculate_bollinger_pb(factor_df, logger_arg=logger)

    bollinger_valid = int(factor_df["bollinger_pb"].notna().sum())
    logger.info("  有效 bollinger_pb: %d (%.2f%%)", bollinger_valid, _calc_pct(bollinger_valid, len(factor_df)))

    # ========== Step 5: 计算 kdj_j ==========
    logger.info("Step 5: 计算 KDJ_J 因子...")

    factor_df = calculate_kdj_j(factor_df, logger_arg=logger)

    kdj_valid = int(factor_df["kdj_j"].notna().sum())
    logger.info("  有效 kdj_j: %d (%.2f%%)", kdj_valid, _calc_pct(kdj_valid, len(factor_df)))

    # ========== Step 6: 计算 turnover_surge ==========
    logger.info("Step 6: 计算换手率突增因子...")

    factor_df = calculate_turnover_surge(factor_df, logger_arg=logger)

    surge_valid = int(factor_df["turnover_surge"].notna().sum())
    logger.info("  有效 turnover_surge: %d (%.2f%%)", surge_valid, _calc_pct(surge_valid, len(factor_df)))

    # ========== Step 7: 计算 amplitude ==========
    logger.info("Step 7: 计算振幅因子...")

    factor_df = calculate_amplitude(factor_df, logger_arg=logger)

    amplitude_valid = int(factor_df["amplitude"].notna().sum())
    logger.info("  有效 amplitude: %d (%.2f%%)", amplitude_valid, _calc_pct(amplitude_valid, len(factor_df)))

    # ========== Step 8: 计算 price_position ==========
    logger.info("Step 8: 计算价格位置因子...")

    factor_df = calculate_price_position(factor_df, logger_arg=logger)

    position_valid = int(factor_df["price_position"].notna().sum())
    logger.info("  有效 price_position: %d (%.2f%%)", position_valid, _calc_pct(position_valid, len(factor_df)))

    # ========== Step 8.5: 计算 return_5d（5日累计涨幅） ==========
    logger.info("Step 8.5: 计算5日累计涨幅因子...")

    factor_df = calculate_return_5d(factor_df, logger_arg=logger)

    return_5d_valid = int(factor_df["return_5d"].notna().sum())
    logger.info("  有效 return_5d: %d (%.2f%%)", return_5d_valid, _calc_pct(return_5d_valid, len(factor_df)))

    # ========== Step 8.6: 计算 momentum_strength（动量强度） ==========
    logger.info("Step 8.6: 计算动量强度因子...")

    factor_df = calculate_momentum_strength(factor_df, logger_arg=logger)

    momentum_valid = int(factor_df["momentum_strength"].notna().sum())
    logger.info("  有效 momentum_strength: %d (%.2f%%)", momentum_valid, _calc_pct(momentum_valid, len(factor_df)))

    # ========== Step 9: 计算 overnight_ret（隔夜收益率/跳空幅度） ==========
    logger.info("Step 9: 计算隔夜收益率因子（跳空幅度）...")

    factor_df = calculate_overnight_return(factor_df, logger_arg=logger)

    overnight_valid = int(factor_df["overnight_ret"].notna().sum())
    logger.info("  有效 overnight_ret: %d (%.2f%%)", overnight_valid, _calc_pct(overnight_valid, len(factor_df)))

    # ========== Step 10: 计算 intraday_intensity（日内价格强度） ==========
    logger.info("Step 10: 计算日内价格强度因子...")

    factor_df = calculate_intraday_intensity(factor_df, logger_arg=logger)

    intraday_valid = int(factor_df["intraday_intensity"].notna().sum())
    logger.info("  有效 intraday_intensity: %d (%.2f%%)", intraday_valid, _calc_pct(intraday_valid, len(factor_df)))

    # ========== Step 11: 计算尾盘因子 ==========
    logger.info("Step 11: 计算尾盘因子...")

    factor_df = calculate_tail_factors(factor_df, logger_arg=logger)

    tail_position_valid = int(factor_df["tail_price_position"].notna().sum())
    tail_slope_valid = int(factor_df["tail_price_slope"].notna().sum())
    tail_intensity_valid = int(factor_df["tail_price_volume_intensity"].notna().sum())
    tail_acceleration_valid = int(factor_df["tail_volume_acceleration"].notna().sum())
    tail_shrink_valid = int(factor_df["tail_volume_shrink"].notna().sum())
    logger.info(
        "  有效 tail_price_position: %d (%.2f%%)", tail_position_valid, _calc_pct(tail_position_valid, len(factor_df))
    )
    logger.info("  有效 tail_price_slope: %d (%.2f%%)", tail_slope_valid, _calc_pct(tail_slope_valid, len(factor_df)))
    logger.info(
        "  有效 tail_price_volume_intensity: %d (%.2f%%)",
        tail_intensity_valid,
        _calc_pct(tail_intensity_valid, len(factor_df)),
    )
    logger.info(
        "  有效 tail_volume_acceleration: %d (%.2f%%)",
        tail_acceleration_valid,
        _calc_pct(tail_acceleration_valid, len(factor_df)),
    )
    logger.info(
        "  有效 tail_volume_shrink: %d (%.2f%%)", tail_shrink_valid, _calc_pct(tail_shrink_valid, len(factor_df))
    )

    # ========== Step 11.5: 计算止跌信号差分因子（Reversal Delta Factors） ==========
    # v1.40 新增：差分因子依赖原始因子（必须在原始因子计算之后）
    # 遵循 H5: 因子方向不预判，IC方向由数据决定
    logger.info("Step 11.5: 计算止跌信号差分因子...")

    # 振幅差分因子：amplitude(T) - amplitude(T-1)
    factor_df = calculate_amplitude_delta(factor_df, logger_arg=logger)
    amplitude_delta_valid = int(factor_df["amplitude_delta"].notna().sum())
    logger.info(
        "  有效 amplitude_delta: %d (%.2f%%)",
        amplitude_delta_valid,
        _calc_pct(amplitude_delta_valid, len(factor_df)),
    )

    # 换手突增差分因子：turnover_surge(T) - turnover_surge(T-1)
    factor_df = calculate_turnover_surge_delta(factor_df, logger_arg=logger)
    turnover_surge_delta_valid = int(factor_df["turnover_surge_delta"].notna().sum())
    logger.info(
        "  有效 turnover_surge_delta: %d (%.2f%%)",
        turnover_surge_delta_valid,
        _calc_pct(turnover_surge_delta_valid, len(factor_df)),
    )

    # 尾盘位置差分因子：tail_price_position(T) - tail_price_position(T-1)
    factor_df = calculate_tail_price_position_delta(factor_df, logger_arg=logger)
    tail_position_delta_valid = int(factor_df["tail_price_position_delta"].notna().sum())
    logger.info(
        "  有效 tail_price_position_delta: %d (%.2f%%)",
        tail_position_delta_valid,
        _calc_pct(tail_position_delta_valid, len(factor_df)),
    )

    # 尾盘缩量差分因子：tail_volume_shrink(T) - tail_volume_shrink(T-1)
    factor_df = calculate_tail_volume_shrink_delta(factor_df, logger_arg=logger)
    tail_shrink_delta_valid = int(factor_df["tail_volume_shrink_delta"].notna().sum())
    logger.info(
        "  有效 tail_volume_shrink_delta: %d (%.2f%%)",
        tail_shrink_delta_valid,
        _calc_pct(tail_shrink_delta_valid, len(factor_df)),
    )

    # ========== Step 11.6: 计算方向性因子（Directional Factors） ==========
    logger.info("Step 11.6: 计算方向性因子...")

    # 量价齐升强度因子
    factor_df = calculate_volume_price_strength(factor_df, logger_arg=logger)
    volume_price_strength_valid = int(factor_df["volume_price_strength"].notna().sum())

    # 近5日阳线比例因子
    factor_df = calculate_positive_day_ratio_5(factor_df, logger_arg=logger)
    positive_day_ratio_5_valid = int(factor_df["positive_day_ratio_5"].notna().sum())

    # 5日均线偏离度因子
    factor_df = calculate_ma5_deviation(factor_df, logger_arg=logger)
    ma5_deviation_valid = int(factor_df["ma5_deviation"].notna().sum())

    # 近5日高低位置因子
    factor_df = calculate_near_high_ratio_5(factor_df, logger_arg=logger)
    near_high_ratio_5_valid = int(factor_df["near_high_ratio_5"].notna().sum())

    # ========== Step 11.7: 计算行业级别方向性因子（Industry-Level Directional Factors） ==========
    logger.info("Step 11.7: 计算行业级别方向性因子...")
    # Note: 行业因子需要 industry 列做分组聚合。统一添加一次 industry 列，3个因子函数共用。
    # industry 列不属于 _OUTPUT_COLS，Step 12 输出时自动排除。

    # 行业5日动量因子
    factor_df = calculate_industry_momentum_5d(factor_df, logger_arg=logger)
    industry_momentum_5d_valid = int(factor_df["industry_momentum_5d"].notna().sum())

    # 行业换手率趋势因子
    factor_df = calculate_industry_turnover_trend(factor_df, logger_arg=logger)
    industry_turnover_trend_valid = int(factor_df["industry_turnover_trend"].notna().sum())

    # 行业振幅趋势因子
    factor_df = calculate_industry_amplitude_trend(factor_df, logger_arg=logger)
    industry_amplitude_trend_valid = int(factor_df["industry_amplitude_trend"].notna().sum())

    # ========== Step 11.8: 计算行业基本面动量因子（方案B：Industry-Level Fundamental Momentum） ==========
    logger.info("Step 11.8: 计算行业基本面动量因子...")
    # Note: 基本面因子函数内部会添加 industry 列（与方案A相同逻辑），用于行业聚合赋个股。
    # 数据来源: financial_data.json.gz（季度财务数据，merge_asof 前推填充对齐日频）

    # 行业ROE趋势因子（行业ΔROE赋个股）
    factor_df = calculate_industry_roe_trend(factor_df, logger_arg=logger)
    industry_roe_trend_valid = int(factor_df["industry_roe_trend"].notna().sum())

    # 行业盈利增长因子（行业净利润增长率赋个股）
    factor_df = calculate_industry_earnings_growth(factor_df, logger_arg=logger)
    industry_earnings_growth_valid = int(factor_df["industry_earnings_growth"].notna().sum())

    # 行业PE趋势因子（行业ΔPE赋个股）
    factor_df = calculate_industry_pe_trend(factor_df, logger_arg=logger)
    industry_pe_trend_valid = int(factor_df["industry_pe_trend"].notna().sum())

    # ========== Step 11.9: 计算资金流因子（方案C：Capital Flow Factors） ==========
    logger.info("Step 11.9: 计算资金流因子...")
    # Note: 资金流因子函数内部会添加 industry 列（与方案A/B相同逻辑）
    # 数据来源: fund_flow_data.json.gz（约120交易日日频数据，精确匹配无需前推填充）
    # ⚠️ 数据覆盖限制: 每只股票约120交易日（API限制），超过此范围的日期 → NaN

    # 资金流占比趋势因子（行业Δ主力净流入占比赋个股）
    factor_df = calculate_capital_flow_ratio_trend(factor_df, logger_arg=logger)
    capital_flow_ratio_trend_valid = int(factor_df["capital_flow_ratio_trend"].notna().sum())

    # 资金流强度因子（行业主力流入绝对额占比赋个股）
    factor_df = calculate_capital_flow_intensity(factor_df, logger_arg=logger)
    capital_flow_intensity_valid = int(factor_df["capital_flow_intensity"].notna().sum())

    # 删除 industry 临时列（不属于 _OUTPUT_COLS，不应出现在最终输出中）
    # Note: 方案A/B/C的因子函数都会添加 industry 列，统一在此删除
    if "industry" in factor_df.columns:
        factor_df = factor_df.drop(columns=["industry"])

    # ========== Step 12: 格式化输出 ==========
    logger.info("Step 12: 格式化输出...")

    # date 列可能在 Step 11 已转换为字符串，需检查类型
    if pd.api.types.is_datetime64_any_dtype(factor_df["date"]):
        factor_df["date"] = factor_df["date"].dt.strftime("%Y-%m-%d")

    # 检查列是否存在（直接使用模块级常量 _OUTPUT_COLS）
    missing_cols = [col for col in _OUTPUT_COLS if col not in factor_df.columns]
    if missing_cols:
        raise KeyError(f"输出列不存在: {missing_cols}，请检查因子计算函数的输出列名是否与 _EXTENDED_FACTOR_COLS 一致")

    output_df = factor_df[list(_OUTPUT_COLS)].copy()  # 元组转列表，pandas 列选择需要列表

    # 显式释放 factor_df 内存（可能包含中间列，比 output_df 更多）
    del factor_df

    # ========== Step 13: 保存输出 ==========
    logger.info("Step 13: 保存输出...")

    # dates 字段：字符串排序对 YYYY-MM-DD 格式正确（字典序与日期序一致）
    # 从 output_df 取 dates，数据来源更清晰
    dates_list = sorted(output_df["date"].unique().tolist())

    total_records = len(output_df)

    # 确保父目录存在（职责分离：mkdir 单独处理，异常信息更精确）
    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        logger.error("创建输出目录失败: %s, 原因: %s (%s)", output_path.parent, type(e).__name__, str(e))
        raise RuntimeError(f"创建输出目录失败: {output_path.parent}, {type(e).__name__}: {e}") from e

    # 使用临时文件 + os.replace 原子写入（遵循 PROJECT.md 文件写入规范）
    # ⚠️ 内存优化: 流式写入 JSON，避免 output_df.to_dict("records") 一次性创建4GB+字典
    # 旧方法: json.dump({"dates": ..., "data": output_df.to_dict("records")}, f) → OOM
    # 新方法: 分批写入 {"dates": ..., "data": [row1, row2, ...]} → 内存峰值仅每批行数
    _BATCH_WRITE_SIZE = 50000  # 每批写入5万行，峰值约 50000 × 44列 × 100B ≈ 200MB
    temp_path = output_path.parent / (output_path.name + ".tmp")
    try:
        with gzip.open(temp_path, "wt", encoding="utf-8") as f:
            # 写入 JSON 头部
            f.write('{"dates": ')
            json.dump(dates_list, f, ensure_ascii=False)
            f.write(', "data": [')

            # ⚠️ NaN→null 处理：json.dump 默认把 float NaN 输出为 "NaN"（非法JSON值）
            # Python json 模块的 JSONEncoder/iterencode 对嵌套 dict 中的 NaN 无法拦截
            # pandas to_dict('records') 把 NaN 输出为 float('nan')，不是 None
            # 唯一可靠方案: 在 to_dict 后遍历每条记录，NaN → None → json 输出为 null
            def _nan_to_null(obj):
                if isinstance(obj, float) and obj != obj:  # NaN (NaN != NaN)
                    return None
                if isinstance(obj, float) and (obj == float("inf") or obj == float("-inf")):
                    return None
                if isinstance(obj, dict):
                    return {k: _nan_to_null(v) for k, v in obj.items()}
                if isinstance(obj, list):
                    return [_nan_to_null(item) for item in obj]
                return obj

            # 分批写入数据行（避免一次性 to_dict("records") 导致 OOM）
            # ⚠️ 关键: 逐条输出每个记录，而不是 json.dump(batch_records)（输出整个数组）
            # 因为 json.dump(batch_records) 会把每批输出为 [...]，逗号连接后变成 [[batch1], [batch2], ...]
            # 正确格式应该是 [record1, record2, ...]，不能嵌套
            total_rows = len(output_df)
            first_record = True
            for batch_start in range(0, total_rows, _BATCH_WRITE_SIZE):
                batch_end = min(batch_start + _BATCH_WRITE_SIZE, total_rows)
                batch_df = output_df.iloc[batch_start:batch_end]
                batch_records = batch_df.to_dict("records")
                # NaN→null 转换（确保 JSON 严格合规）
                batch_records = _nan_to_null(batch_records)
                # 逐条输出每个记录，逗号 + 换行分隔
                for record in batch_records:
                    if not first_record:
                        f.write(",\n")
                    json.dump(record, f, ensure_ascii=False)
                    first_record = False
                # 显式释放批次数据
                del batch_df, batch_records

            # 写入 JSON 尾部
            f.write("]}")

        os.replace(temp_path, output_path)
    except OSError as e:
        # 文件系统错误（磁盘/权限/IO，PermissionError 是 OSError 子类）
        logger.error("文件系统错误保存失败: %s, 原因: %s (%s)", output_path, type(e).__name__, str(e))
        temp_path.unlink(missing_ok=True)  # 原子操作，消除 TOCTOU 竞争窗口
        raise RuntimeError(f"文件系统错误: {output_path}, {type(e).__name__}: {e}") from e
    except Exception as e:
        # 未知错误（兜底）
        logger.error("未知错误保存失败: %s, 原因: %s (%s)", output_path, type(e).__name__, str(e))
        temp_path.unlink(missing_ok=True)  # 原子操作，消除 TOCTOU 竞争窗口
        raise RuntimeError(f"未知错误保存失败: {output_path}, {type(e).__name__}: {e}") from e

    logger.info("  输出路径: %s", output_path)
    logger.info("  输出记录数: %d", total_records)

    # 计算运行耗时
    end_time = datetime.now()
    elapsed_seconds = (end_time - start_time).total_seconds()

    # ========== Step 14: 返回元数据 ==========
    # metadata 字段说明：
    # - generated_at: 生成时间（格式 YYYY-MM-DD HH:MM:SS）
    # - elapsed_seconds: 运行耗时（秒，精度 .2f）
    # - total_records: 输出总记录数
    # - valid_records: 各因子有效记录数（绝对值）
    # - valid_records_percent: 各因子有效记录百分比（与日志输出一致，便于质量评估）
    # - factor_columns: 扩展因子列名（不含基础列和基础因子）
    # - return_columns: 收益数据列名
    # - input_sources: 输入数据源路径
    # - output_path: 输出文件路径

    metadata = {
        "generated_at": end_time.strftime("%Y-%m-%d %H:%M:%S"),
        "elapsed_seconds": round(elapsed_seconds, 2),
        "total_records": total_records,
        "valid_records": {
            "bollinger_pb": bollinger_valid,
            "kdj_j": kdj_valid,
            "turnover_surge": surge_valid,
            "amplitude": amplitude_valid,
            "price_position": position_valid,
            "past_return_1d": past_return_valid,
            "overnight_ret": overnight_valid,
            "return_5d": return_5d_valid,
            "momentum_strength": momentum_valid,
            "intraday_intensity": intraday_valid,
            "tail_price_position": tail_position_valid,
            "tail_price_slope": tail_slope_valid,
            "tail_price_volume_intensity": tail_intensity_valid,
            "tail_volume_acceleration": tail_acceleration_valid,
            "tail_volume_shrink": tail_shrink_valid,
            "amplitude_delta": amplitude_delta_valid,  # v1.40 新增
            "turnover_surge_delta": turnover_surge_delta_valid,  # v1.40 新增
            "tail_price_position_delta": tail_position_delta_valid,  # v1.40 新增
            "tail_volume_shrink_delta": tail_shrink_delta_valid,  # v1.40 新增
            "volume_price_strength": volume_price_strength_valid,  # v1.41 新增
            "positive_day_ratio_5": positive_day_ratio_5_valid,  # v1.41 新增
            "ma5_deviation": ma5_deviation_valid,  # v1.41 新增
            "near_high_ratio_5": near_high_ratio_5_valid,  # v1.41 新增
            "industry_momentum_5d": industry_momentum_5d_valid,  # v1.42 新增
            "industry_turnover_trend": industry_turnover_trend_valid,  # v1.42 新增
            "industry_amplitude_trend": industry_amplitude_trend_valid,  # v1.42 新增
            "industry_roe_trend": industry_roe_trend_valid,  # v1.43 新增（方案B）
            "industry_earnings_growth": industry_earnings_growth_valid,  # v1.43 新增（方案B）
            "industry_pe_trend": industry_pe_trend_valid,  # v1.43 新增（方案B）
            "capital_flow_ratio_trend": capital_flow_ratio_trend_valid,  # v1.44 新增（方案C）
            "capital_flow_intensity": capital_flow_intensity_valid,  # v1.44 新增（方案C）
        },
        "valid_records_percent": {
            "bollinger_pb": _calc_pct(bollinger_valid, total_records),
            "kdj_j": _calc_pct(kdj_valid, total_records),
            "turnover_surge": _calc_pct(surge_valid, total_records),
            "amplitude": _calc_pct(amplitude_valid, total_records),
            "price_position": _calc_pct(position_valid, total_records),
            "past_return_1d": _calc_pct(past_return_valid, total_records),
            "overnight_ret": _calc_pct(overnight_valid, total_records),
            "return_5d": _calc_pct(return_5d_valid, total_records),
            "momentum_strength": _calc_pct(momentum_valid, total_records),
            "intraday_intensity": _calc_pct(intraday_valid, total_records),
            "tail_price_position": _calc_pct(tail_position_valid, total_records),
            "tail_price_slope": _calc_pct(tail_slope_valid, total_records),
            "tail_price_volume_intensity": _calc_pct(tail_intensity_valid, total_records),
            "tail_volume_acceleration": _calc_pct(tail_acceleration_valid, total_records),
            "tail_volume_shrink": _calc_pct(tail_shrink_valid, total_records),
            "amplitude_delta": _calc_pct(amplitude_delta_valid, total_records),  # v1.40 新增
            "turnover_surge_delta": _calc_pct(turnover_surge_delta_valid, total_records),  # v1.40 新增
            "tail_price_position_delta": _calc_pct(tail_position_delta_valid, total_records),  # v1.40 新增
            "tail_volume_shrink_delta": _calc_pct(tail_shrink_delta_valid, total_records),  # v1.40 新增
            "volume_price_strength": _calc_pct(volume_price_strength_valid, total_records),  # v1.41 新增
            "positive_day_ratio_5": _calc_pct(positive_day_ratio_5_valid, total_records),  # v1.41 新增
            "ma5_deviation": _calc_pct(ma5_deviation_valid, total_records),  # v1.41 新增
            "near_high_ratio_5": _calc_pct(near_high_ratio_5_valid, total_records),  # v1.41 新增
            "industry_momentum_5d": _calc_pct(industry_momentum_5d_valid, total_records),  # v1.42 新增
            "industry_turnover_trend": _calc_pct(industry_turnover_trend_valid, total_records),  # v1.42 新增
            "industry_amplitude_trend": _calc_pct(industry_amplitude_trend_valid, total_records),  # v1.42 新增
            "industry_roe_trend": _calc_pct(industry_roe_trend_valid, total_records),  # v1.43 新增（方案B）
            "industry_earnings_growth": _calc_pct(industry_earnings_growth_valid, total_records),  # v1.43 新增（方案B）
            "industry_pe_trend": _calc_pct(industry_pe_trend_valid, total_records),  # v1.43 新增（方案B）
            "capital_flow_ratio_trend": _calc_pct(capital_flow_ratio_trend_valid, total_records),  # v1.44 新增（方案C）
            "capital_flow_intensity": _calc_pct(capital_flow_intensity_valid, total_records),  # v1.44 新增（方案C）
        },
        "factor_columns": list(_EXTENDED_FACTOR_COLS),  # 扩展因子列（返回副本，防止外部修改）
        "return_columns": list(_RETURN_COLS),  # 收益数据列（返回副本，防止外部修改）
        "input_sources": {
            "factor_data": str(factor_data_path),
            "turnover_data": str(turnover_data_path),
            "return_data": str(return_data_path),
        },
        "output_path": str(output_path),
    }

    logger.info("=" * 40)
    logger.info("因子生成完成")
    logger.info("生成时间: %s", metadata["generated_at"])
    logger.info("运行耗时: %.2f 秒", metadata["elapsed_seconds"])
    logger.info("因子列: %s", metadata["factor_columns"])
    logger.info("=" * 40)

    # ========== Step 15: 写出列名清单（消费者 schema 查询） ==========
    # 遵循 factor_cols_literal_constant_design.md §3.5：
    # 将 _OUTPUT_COLS 结构化输出为独立 JSON 文件，供 factor_ic 模块
    # 校验 required_columns 是否与数据源对齐（M4 合规：读数据产物 ≠ import 模块）
    columns_path = output_path.parent / "factor_ic_data_columns.json"
    try:
        columns_manifest = {
            "base_cols": list(_BASE_COLS),
            "extended_factor_cols": list(_EXTENDED_FACTOR_COLS),
            "return_cols": list(_RETURN_COLS),
            "all_cols": list(_OUTPUT_COLS),
            "generated_at": metadata["generated_at"],
        }
        with open(columns_path, "w", encoding="utf-8") as f:
            json.dump(columns_manifest, f, ensure_ascii=False, indent=2)
        logger.info("列名清单已保存: %s", columns_path)
    except OSError as e:
        # 列名清单写入失败不应阻塞主流程（降级为 warn）
        logger.warning("列名清单保存失败: %s, 原因: %s", columns_path, e)

    return metadata


# ============================================================================
# CLI 入口
# ============================================================================


def main() -> int:
    """CLI 主入口"""
    parser = argparse.ArgumentParser(description="统一因子生成模块（含收益数据）")
    parser.add_argument("--factor_data", type=str, default=None, help="基础因子数据路径")
    parser.add_argument("--turnover_data", type=str, default=None, help="换手率数据路径")
    parser.add_argument("--return_data", type=str, default=None, help="收益数据路径")
    parser.add_argument("--output", type=str, default=None, help="输出路径")
    parser.add_argument("--quiet", action="store_true", help="静默模式（只输出 ERROR 级别日志）")

    args = parser.parse_args()

    # 设置日志级别
    log_level = logging.ERROR if args.quiet else logging.INFO
    logger = setup_logger("factor_generator", level=log_level)

    # 参数路径转换
    factor_data_path = Path(args.factor_data) if args.factor_data else None
    turnover_data_path = Path(args.turnover_data) if args.turnover_data else None
    return_data_path = Path(args.return_data) if args.return_data else None
    output_path = Path(args.output) if args.output else None

    try:
        metadata = generate_all_factors(
            factor_data_path=factor_data_path,
            turnover_data_path=turnover_data_path,
            return_data_path=return_data_path,
            output_path=output_path,
            logger=logger,
        )
        # CLI 入口执行摘要（关键元数据）
        logger.info(
            "执行摘要: 总记录数=%d, 耗时=%.2f秒, 输出路径=%s",
            metadata["total_records"],
            metadata["elapsed_seconds"],
            metadata["output_path"],
        )
        logger.info("执行成功，退出码: 0")
        return 0
    except Exception as e:
        # data_fetchers MODULE.md R10: 类型名 + logger.exception 自动附堆栈
        logger.exception("执行失败 [%s]", type(e).__name__)
        return 1


# ============================================================================
# __main__ CLI 入口
# ============================================================================

if __name__ == "__main__":
    # CLI 入口：调用 main() 函数，测试代码已移至 test_cases/test_factor_generator.py
    # 注意：sys 已在顶部条件块导入，无需重复导入
    sys.exit(main())
