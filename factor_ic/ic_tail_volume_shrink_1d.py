#!/usr/bin/env python3
"""
尾盘缩量程度因子 IC 计算器 - 使用公共模块主入口

遵循 PROJECT.md 公共模块强制复用规范：
- 主流程使用 run_complex_factor_ic()（禁止手写三模式分支）
- 因子计算逻辑独立实现（calculate_tail_volume_shrink）

因子定义：
- 尾盘成交量总和 = sum(volumes[0:13])  # 14:00-15:00 全部13根K线成交量
- 全天成交量 = volume（主数据源）
- 缩量程度 = 尾盘成交量总和 / 全天成交量
- tail_volume_shrink = sum(volumes) / volume

含义：
- factor_value < 1：尾盘成交量占比小于全天，数值越小表示尾盘缩量越明显
- factor_value 接近 1：尾盘成交量接近全天成交量（异常情况）
- 通常范围：A股尾盘成交量占比约 10%-30%

边界处理：
- volumes 数组长度不足 13 时设为 NaN（数据不完整）
- volumes 包含 NaN/None 时返回 NaN（数据污染）
- 全天成交量 < EPSILON 时设为 NaN（除零防护）
- factor_value > 1 时设为 NaN（数据异常：尾盘成交量超过全天）

数据依赖：
- tail_trading_data.json.gz（尾盘5分钟K线数据，含 volumes 数组）
- factor_ic_data.json.gz（主数据源，含 volume 字段）

作者: 云瑶
创建日期: 2026-06-03
版本历史:
  v1.1 (2026-06-03): Round 1 优化 - 导入分组注释完善、版本历史规范
"""

# ============================================================================
# 标准库导入
# ============================================================================
import argparse
import gzip
import json
import sys
from pathlib import Path

# ============================================================================
# 第三方库导入
# ============================================================================
import numpy as np
import pandas as pd

# ============================================================================
# 本地模块导入
# ============================================================================
sys.path.insert(0, str(Path(__file__).parent.parent))

from paths import DATA_FETCHERS_RESULT  # 遵循 PROJECT.md H7 规则

from factor_ic.common.factor_ic_runner import run_complex_factor_ic
from factor_ic.common.logger_config import get_logger


logger = get_logger(__name__)

# ============================================================================
# 参数统一管理
# ============================================================================
DEFAULT_MIN_STOCKS = 10
EPSILON = 1e-10  # 避免除零阈值

# 尾盘数据路径（遵循 PROJECT.md H7 规则：使用 paths.py 单一来源）
TAIL_TRADING_DATA_PATH = DATA_FETCHERS_RESULT / "tail_trading_data.json.gz"


# ============================================================================
# 辅助函数：加载尾盘数据
# ============================================================================


def load_tail_trading_data() -> pd.DataFrame:
    """
    加载尾盘数据

    Returns:
        DataFrame，包含 date, asset, prices, volumes 列

    Raises:
        FileNotFoundError: 尾盘数据文件不存在
        ValueError: 尾盘数据格式错误
    """
    if not TAIL_TRADING_DATA_PATH.exists():
        raise FileNotFoundError(f"尾盘数据文件不存在: {TAIL_TRADING_DATA_PATH}")

    with gzip.open(TAIL_TRADING_DATA_PATH, "rt", encoding="utf-8") as f:
        data = json.load(f)

    if "data" not in data:
        raise ValueError("尾盘数据格式错误：缺少 'data' 字段")

    df = pd.DataFrame(data["data"])

    logger.info("尾盘数据加载完成: %d 条记录", len(df))
    return df


# ============================================================================
# 因子计算函数
# ============================================================================


def _calc_tail_volume_shrink(volumes: list | np.ndarray, daily_volume: float) -> float:
    """
    计算尾盘缩量程度（尾盘成交量总和 / 全天成交量）- 内部函数

    尾盘时间段: volumes[0:13] → 14:00-15:00 全部13根5分钟K线

    Args:
        volumes: 尾盘成交量列表（13个元素）
        daily_volume: 全天成交量

    Returns:
        缩量程度值，或 NaN（数据异常时）

    Example:
        >>> _calc_tail_volume_shrink([1000, 2000, 3000, ...共13个], 100000)
        0.13  # (sum(volumes)/daily_volume)
    """
    # 处理 volumes 类型
    if not isinstance(volumes, list):
        return np.nan
    if len(volumes) < 13:
        logger.debug("volumes 数组长度不足 13: %d", len(volumes))
        return np.nan
    # 检查是否包含 NaN/None
    if any(v is None or (isinstance(v, float) and np.isnan(v)) for v in volumes):
        logger.debug("volumes 包含 NaN/None 值")
        return np.nan

    # 处理 daily_volume
    if daily_volume is None or (isinstance(daily_volume, float) and np.isnan(daily_volume)):
        logger.debug("daily_volume 为 NaN/None")
        return np.nan
    if daily_volume < EPSILON:
        logger.debug("全天成交量接近零: %.10f", daily_volume)
        return np.nan

    # 计算尾盘成交量总和
    tail_volume_sum = sum(volumes)

    # 计算缩量程度
    shrink_ratio = tail_volume_sum / daily_volume

    # 异常检查：尾盘成交量超过全天成交量（数据异常）
    if shrink_ratio > 1.0:
        logger.debug("尾盘成交量超过全天成交量: %.4f > 1.0（数据异常）", shrink_ratio)
        return np.nan

    return shrink_ratio


def calculate_tail_volume_shrink(factor_df: pd.DataFrame) -> pd.DataFrame:
    """
    计算尾盘缩量程度因子

    公式:
    - 尾盘成交量总和 = sum(volumes[0:13])  # 14:00-15:00
    - 缩量程度 = 尾盘成交量总和 / 全天成交量

    Args:
        factor_df: 包含 date, asset, volume 列的 DataFrame
            - 'date': 交易日期
            - 'asset': 资产代码
            - 'volume': 全天成交量

    Returns:
        DataFrame，新增 'tail_volume_shrink' 列

    Note:
        - 遵循 MODULE.md 约束 #4：函数入口先 copy()
        - 需要合并尾盘数据（tail_trading_data.json.gz）
        - 除零防护：全天成交量 < EPSILON 时设为 NaN
        - 数据完整性：volumes 数组长度不足 13 时设为 NaN
        - 异常检查：缩量程度 > 1 时设为 NaN（数据异常）

    Example:
        >>> # 正常场景：通过公共模块调用（推荐）
        >>> from factor_ic.common.factor_ic_runner import run_complex_factor_ic
        >>> result = run_complex_factor_ic(
        ...     factor_name="tail_volume_shrink",
        ...     factor_col="tail_volume_shrink",
        ...     factor_cols=["date", "asset", "volume"],
        ...     custom_factor_calculation=calculate_tail_volume_shrink,
        ... )
        >>> # 异常场景：尾盘数据文件不存在（返回全 NaN 因子值，不中断计算）
        >>> # 系统自动 fallback，日志记录 FileNotFoundError
    """
    # 遵循 MODULE.md 约束 #4：函数入口先 copy()
    factor_df = factor_df.copy()

    # 加载尾盘数据
    try:
        tail_df = load_tail_trading_data()
    except FileNotFoundError as e:
        logger.error("尾盘数据文件不存在，返回全 NaN: %s", e)
        factor_df["tail_volume_shrink"] = np.nan
        return factor_df

    # 确保日期格式一致
    factor_df["date"] = pd.to_datetime(factor_df["date"]).dt.strftime("%Y-%m-%d")
    tail_df["date"] = pd.to_datetime(tail_df["date"]).dt.strftime("%Y-%m-%d")

    # 合并尾盘数据（按 date, asset）
    merged_df = factor_df.merge(
        tail_df[["date", "asset", "volumes"]], on=["date", "asset"], how="left"
    )

    n_matched = merged_df["volumes"].notna().sum() if "volumes" in merged_df.columns else 0
    logger.info(
        "尾盘数据合并完成: %d / %d 条匹配",
        n_matched,
        len(factor_df),
    )

    # 计算缩量程度（使用 apply 遍历每行）
    merged_df["tail_volume_shrink"] = merged_df.apply(
        lambda row: _calc_tail_volume_shrink(row["volumes"], row["volume"]),
        axis=1,
    )

    # 统计有效因子数量
    valid_count = merged_df["tail_volume_shrink"].notna().sum()
    total_count = len(merged_df)
    logger.info(
        "尾盘缩量程度因子计算完成: %d / %d 有效 (%.1f%%)",
        valid_count,
        total_count,
        100 * valid_count / total_count if total_count > 0 else 0,
    )

    # 返回只包含原列 + 因子列的 DataFrame
    result_cols = list(factor_df.columns) + ["tail_volume_shrink"]
    return merged_df[result_cols]


# ============================================================================
# CLI 入口
# ============================================================================


def main():
    """CLI 主入口"""
    parser = argparse.ArgumentParser(description="尾盘缩量程度因子 IC 计算器")
    parser.add_argument("--force-full", action="store_true", help="强制全量计算")
    parser.add_argument("--min-stocks", type=int, default=DEFAULT_MIN_STOCKS, help="最小股票数")

    args = parser.parse_args()

    # 使用公共模块主入口（遵循 PROJECT.md 强制复用规范）
    result = run_complex_factor_ic(
        factor_name="tail_volume_shrink",
        factor_col="tail_volume_shrink",
        factor_cols=["date", "asset", "volume"],  # 需要 volume 字段计算缩量程度
        custom_factor_calculation=calculate_tail_volume_shrink,
        min_stocks=args.min_stocks,
        force_full=args.force_full,
        _logger=logger,
    )

    # 保底处理：公共模块异常返回 None 时直接退出
    if result is None:
        logger.error("run_complex_factor_ic 返回 None")
        sys.exit(1)

    # 使用 .get() + or {} 防御性访问结果
    ic_metrics = result.get("ic_metrics") or {}
    sample_stats = result.get("sample_stats") or {}
    period = result.get("period") or {}
    ic_distribution = result.get("ic_distribution_consistency") or {}

    logger.info("=" * 40)
    logger.info("结果摘要")
    logger.info("=" * 40)

    # IC 指标
    ic_mean = ic_metrics.get("ic_mean")
    ic_std = ic_metrics.get("ic_std")
    icir = ic_metrics.get("icir")

    if ic_mean is not None:
        logger.info("  IC 均值: %.4f", ic_mean)
    else:
        logger.warning("  IC 均值: N/A（数据不足或计算异常）")

    if ic_std is not None:
        logger.info("  IC 标准差: %.4f", ic_std)
    else:
        logger.warning("  IC 标准差: N/A（IC 为常量或数据不足）")

    if icir is not None:
        logger.info("  ICIR: %.4f", icir)
    else:
        logger.warning("  ICIR: N/A（IC 标准差为 0 或数据不足）")

    # 正比例统计
    positive_ratio = ic_distribution.get("positive_ratio")
    if positive_ratio is not None:
        logger.info("  正比例: %.2f%%", positive_ratio * 100)
    else:
        logger.warning("  正比例: N/A（数据不足）")

    # 样本统计
    avg_stocks = sample_stats.get("avg_stocks_per_day")
    total_days = sample_stats.get("total_days")

    if avg_stocks is not None:
        logger.info("  平均股票数: %.1f", avg_stocks)

    if total_days is not None:
        logger.info("  总交易日数: %d", total_days)

    # 时间范围
    start_date = period.get("start")
    end_date = period.get("end")

    if start_date and end_date:
        logger.info("  日期范围: %s ~ %s", start_date, end_date)

    logger.info("=" * 40)
    logger.info("计算完成")
    logger.info("=" * 40)

    return result


if __name__ == "__main__":
    main()