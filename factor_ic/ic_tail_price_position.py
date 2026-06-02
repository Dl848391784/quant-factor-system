#!/usr/bin/env python3
"""
尾盘价格位置因子 IC 计算器 - 使用公共模块主入口

遵循 PROJECT.md 公共模块强制复用规范：
- 主流程使用 run_complex_factor_ic()（禁止手写三模式分支）
- 因子计算逻辑独立实现（calculate_tail_price_position）

因子定义：
- 尾盘价格位置 = (收盘价 - 尾盘最低价) / (尾盘最高价 - 尾盘最低价)
- 收盘价 = prices[-1]（尾盘最后一根K线收盘价，即15:00收盘价）
- 尾盘最高价 = tail_high（14:00-15:00期间的最高价）
- 尾盘最低价 = tail_low（14:00-15:00期间的最低价）

含义：
- 值 = 0 → 收盘价等于尾盘最低价（尾盘弱势，收盘在区间底部）
- 值 = 1 → 收盘价等于尾盘最高价（尾盘强势，收盘在区间顶部）
- 值 = 0.5 → 收盘价在尾盘价格区间中间
- 值 > 0.5 → 收盘偏向高位（尾盘向上收敛）
- 值 < 0.5 → 收盘偏向低位（尾盘向下收敛）

边界处理：
- 尾盘最高价等于尾盘最低价时设为 NaN（价格区间为零，无位置意义）
- prices 数组长度不足 13 时设为 NaN（数据不完整）
- tail_high/tail_low 缺失时设为 NaN

数据依赖：
- tail_trading_data.json.gz（尾盘5分钟K线数据，含 tail_high, tail_low）
- factor_ic_data.json.gz（主数据源）

作者: 云瑶
创建日期: 2026-06-02
版本历史:
  v1.0 (2026-06-02): 初始版本，实现尾盘价格位置因子 IC 计算
  v1.1 (2026-06-02): 优化 - 流程文档创建、lint修复、测试文件创建（5个测试用例）
"""

import argparse
import gzip
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd


# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent.parent))

# 导入公共模块主入口（遵循 PROJECT.md 强制复用规范）
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
        DataFrame，包含 date, asset, prices, volumes, tail_high, tail_low 列

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


def calculate_tail_price_position(factor_df: pd.DataFrame) -> pd.DataFrame:
    """
    计算尾盘价格位置因子

    公式:
    - 收盘价 = prices[-1]（尾盘最后一根K线收盘价）
    - 尾盘价格位置 = (收盘价 - tail_low) / (tail_high - tail_low)

    Args:
        factor_df: 包含 date, asset 列的 DataFrame
            - 'date': 交易日期
            - 'asset': 资产代码

    Returns:
        DataFrame，新增 'tail_price_position' 列

    Note:
        - 遵循 MODULE.md 约束 #4：函数入口先 copy()
        - 需要合并尾盘数据（tail_trading_data.json.gz）
        - 除零防护：tail_high == tail_low 时设为 NaN
        - 数据完整性：prices 数组长度不足 13 时设为 NaN
        - 理论范围：[0, 1]

    Example:
        >>> # 通过公共模块调用（推荐）
        >>> from factor_ic.common.factor_ic_runner import run_complex_factor_ic
        >>> result = run_complex_factor_ic(
        ...     factor_name="tail_price_position",
        ...     factor_col="tail_price_position",
        ...     factor_cols=["date", "asset"],
        ...     custom_factor_calculation=calculate_tail_price_position,
        ... )
    """
    # 遵循 MODULE.md 约束 #4：函数入口先 copy()
    factor_df = factor_df.copy()

    # 加载尾盘数据
    # 设计意图：文件不存在时返回全 NaN（fallback），而非抛出异常中断计算
    try:
        tail_df = load_tail_trading_data()
    except FileNotFoundError as e:
        logger.error("尾盘数据文件不存在，返回全 NaN: %s", e)
        factor_df["tail_price_position"] = np.nan
        return factor_df

    # 确保日期格式一致
    factor_df["date"] = pd.to_datetime(factor_df["date"]).dt.strftime("%Y-%m-%d")
    tail_df["date"] = pd.to_datetime(tail_df["date"]).dt.strftime("%Y-%m-%d")

    # 合并尾盘数据（按 date, asset）
    merged_df = factor_df.merge(
        tail_df[["date", "asset", "prices", "tail_high", "tail_low"]],
        on=["date", "asset"],
        how="left",
    )

    logger.info(
        "尾盘数据合并完成: %d / %d 条匹配",
        merged_df["prices"].notna().sum(),
        len(factor_df),
    )

    # 计算收盘价（prices[-1])
    def get_close_price(prices):
        if not isinstance(prices, list):
            return np.nan
        if len(prices) < 13:
            return np.nan
        return prices[-1]

    merged_df["tail_close"] = merged_df["prices"].apply(get_close_price)

    # 计算尾盘价格位置
    def calc_price_position(close_price, tail_high, tail_low):
        # 处理 NaN/None
        if pd.isna(close_price) or pd.isna(tail_high) or pd.isna(tail_low):
            return np.nan
        # 除零防护：价格区间为零
        price_range = tail_high - tail_low
        if abs(price_range) < EPSILON:
            return np.nan
        # 计算位置
        return (close_price - tail_low) / price_range

    merged_df["tail_price_position"] = merged_df.apply(
        lambda row: calc_price_position(row["tail_close"], row["tail_high"], row["tail_low"]),
        axis=1,
    )

    # 统计有效因子数量
    valid_count = merged_df["tail_price_position"].notna().sum()
    total_count = len(merged_df)
    logger.info(
        "尾盘价格位置因子计算完成: %d / %d 有效 (%.1f%%)",
        valid_count,
        total_count,
        100 * valid_count / total_count if total_count > 0 else 0,
    )

    # 返回只包含原列 + 因子列的 DataFrame
    result_cols = list(factor_df.columns) + ["tail_price_position"]
    return merged_df[result_cols]


# ============================================================================
# CLI 入口
# ============================================================================


def main():
    """CLI 主入口"""
    parser = argparse.ArgumentParser(description="尾盘价格位置因子 IC 计算器")
    parser.add_argument("--force-full", action="store_true", help="强制全量计算")
    parser.add_argument("--min-stocks", type=int, default=DEFAULT_MIN_STOCKS, help="最小股票数")

    args = parser.parse_args()

    # 使用公共模块主入口（遵循 PROJECT.md 强制复用规范）
    result = run_complex_factor_ic(
        factor_name="tail_price_position",
        factor_col="tail_price_position",
        factor_cols=["date", "asset"],  # 不需要 volume
        custom_factor_calculation=calculate_tail_price_position,
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


if __name__ == "__main__":
    main()
