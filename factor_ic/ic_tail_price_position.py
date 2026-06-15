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
  v1.2 (2026-06-02): 优化 - 抽取独立函数(get_close_price/calc_price_position)、公共模块复用(tail_data_loader)、异常处理注释补充、测试补充至13个
"""

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd


# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent.parent))

# 导入公共模块主入口（遵循 PROJECT.md 强制复用规范）
from factor_ic.common.cli_helpers import DEFAULT_MIN_STOCKS
from factor_ic.common.exceptions import FactorCalcError
from factor_ic.common.factor_ic_runner import run_complex_factor_ic
from factor_ic.common.logger_config import get_logger
from factor_ic.common.tail_data_loader import load_tail_trading_data  # 公共模块复用


logger = get_logger(__name__)
EPSILON = 1e-10  # 避免除零阈值


# ============================================================================
# 因子计算函数
# ============================================================================


def get_close_price(prices: list | None) -> float:
    """
    获取尾盘收盘价（prices[-1])

    Args:
        prices: 尾盘价格列表（13根5分钟K线收盘价）

    Returns:
        尾盘收盘价，或 NaN（数据不完整时）

    Note:
        - prices 不是列表时返回 NaN
        - prices 长度不足 13 时返回 NaN（数据不完整）
    """
    if not isinstance(prices, list):
        return np.nan
    if len(prices) < 13:
        return np.nan
    return prices[-1]


def calc_price_position(
    close_price: float,
    tail_high: float,
    tail_low: float,
) -> float:
    """
    计算尾盘价格位置

    公式:
    - 尾盘价格位置 = (收盘价 - 尾盘最低价) / (尾盘最高价 - 尾盘最低价)

    Args:
        close_price: 尾盘收盘价
        tail_high: 尾盘最高价
        tail_low: 尾盘最低价

    Returns:
        尾盘价格位置，理论范围 [0, 1]，或 NaN（边界情况）

    Note:
        - 任一参数为 NaN 时返回 NaN
        - tail_high == tail_low 时返回 NaN（价格区间为零）
    """
    # 处理 NaN/None
    if pd.isna(close_price) or pd.isna(tail_high) or pd.isna(tail_low):
        return np.nan
    # 除零防护：价格区间为零
    price_range = tail_high - tail_low
    if abs(price_range) < EPSILON:
        return np.nan
    # 计算位置
    return (close_price - tail_low) / price_range


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
    # 原因：尾盘数据可能因上游 fetch_tail_trading.py 未运行而缺失，
    #       但因子 IC 计算不应因此中断，应记录日志并返回空因子值
    try:
        tail_df = load_tail_trading_data()
    except FileNotFoundError as e:
        logger.error("尾盘数据文件不存在，返回全 NaN: %s", e)
        factor_df["tail_price_position"] = np.nan
        return factor_df
    except ValueError as e:
        logger.error("尾盘数据格式错误，返回全 NaN: %s", e)
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

    # 计算收盘价（使用抽取的独立函数）
    merged_df["tail_close"] = merged_df["prices"].apply(get_close_price)

    # 计算尾盘价格位置（使用抽取的独立函数）
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

    # 返回只包含原列 + 因子列的 DataFrame（防止列名重复）
    result_cols = [c for c in factor_df.columns if c != "tail_price_position"] + ["tail_price_position"]
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

    # 启动参数日志（便于追溯本次运行配置）
    logger.info(f"启动尾盘价格位置因子IC计算: min_stocks={args.min_stocks}, force_full={args.force_full}")

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

    # 防御性检查：result 为 None 时抛出异常（遵循 PROJECT.md 异常处理规范）
    if result is None:
        raise FactorCalcError("run_complex_factor_ic 返回 None，数据加载或计算可能失败")

    # 使用 .get() + or {} 防御性访问结果（避免 None 导致格式化失败）
    ic_metrics = result.get("ic_metrics") or {}
    sample_stats = result.get("sample_stats") or {}
    period = result.get("period") or {}
    ic_distribution = result.get("ic_distribution_consistency") or {}

    # 构建结果摘要（单次输出保证并发场景下日志原子性）
    ic_mean = ic_metrics.get("ic_mean")
    ic_std = ic_metrics.get("ic_std")
    icir = ic_metrics.get("icir")
    positive_ratio = ic_distribution.get("positive_ratio")
    avg_stocks = sample_stats.get("avg_stocks_per_day")
    total_days = sample_stats.get("total_days")
    start_date = period.get("start")
    end_date = period.get("end")

    # 格式化各字段（None 时显示 N/A）
    ic_mean_str = f"{ic_mean:.4f}" if ic_mean is not None else "N/A"
    ic_std_str = f"{ic_std:.4f}" if ic_std is not None else "N/A"
    icir_str = f"{icir:.4f}" if icir is not None else "N/A"
    positive_ratio_str = f"{positive_ratio * 100:.2f}%" if positive_ratio is not None else "N/A"
    avg_stocks_str = f"{avg_stocks:.1f}" if avg_stocks is not None else "N/A"
    total_days_str = f"{total_days}" if total_days is not None else "N/A"
    date_range_str = f"{start_date} ~ {end_date}" if start_date and end_date else "N/A"

    summary_lines = [
        "=" * 40,
        "结果摘要",
        "=" * 40,
        f"因子名称: {result.get('factor_name', 'unknown')}",
        f"更新模式: {result.get('update_mode', 'unknown')}",
        f"  IC 均值: {ic_mean_str}",
        f"  IC 标准差: {ic_std_str}",
        f"  ICIR: {icir_str}",
        f"  正比例: {positive_ratio_str}",
        f"  平均股票数: {avg_stocks_str}",
        f"  总交易日数: {total_days_str}",
        f"  日期范围: {date_range_str}",
        "=" * 40,
        "计算完成",
        "=" * 40,
    ]
    logger.info("\n" + "\n".join(summary_lines))

    # ic_mean 为 None 时额外输出 warning，便于告警系统捕获异常运行
    if ic_mean is None:
        logger.warning("本次计算 IC 均值为空，请检查数据源")

    return result


if __name__ == "__main__":
    try:
        main()
    except FactorCalcError as e:
        # 已知业务异常，使用 error()（不打印完整堆栈，但保留错误内容）
        logger.error(f"尾盘价格位置因子IC计算失败: {e}")
        sys.exit(1)
    except Exception:
        # 未预期异常，使用 exception()（自动打印完整堆栈）
        logger.exception("未预期的错误")
        sys.exit(1)
