#!/usr/bin/env python3
"""
尾盘量价强度因子 IC 计算器 - 使用公共模块主入口

遵循 PROJECT.md 公共模块强制复用规范：
- 主流程使用 run_complex_factor_ic()（禁止手写三模式分支）
- 因子计算逻辑独立实现（calculate_tail_price_volume_intensity）

因子定义：
- 尾盘涨跌幅 = (prices[-1] - prices[0]) / prices[0]
- 尾盘量比 = sum(volumes) / volume（尾盘成交量 / 全天成交量）
- 尾盘量价强度 = 尾盘涨跌幅 × 尾盘量比

含义：
- 正值 → 尾盘上涨且成交量放大（资金流入）
- 负值 → 尾盘下跌且成交量放大（资金流出）
- 绝对值大 → 尾盘量价异动显著

边界处理：
- prices[0] 接近零时设为 NaN（除零防护）
- volume 接近零时设为 NaN（除零防护）
- volumes 数组长度不足 13 时设为 NaN（数据不完整）

数据依赖：
- tail_trading_data.json.gz（尾盘5分钟K线数据）
- factor_ic_data.json.gz（主数据源，含全天成交量 volume）

作者: 云瑶
创建日期: 2026-06-02
版本历史:
  v1.0 (2026-06-02): 初始版本，实现尾盘量价强度因子 IC 计算
  v1.1 (2026-06-02): 优化 - 流程文档创建、lint修复、路径导入规范化、类型注解、异常处理注释
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

from factor_ic.common.cli_helpers import DEFAULT_MIN_STOCKS
from factor_ic.common.exceptions import FactorCalcError
from factor_ic.common.factor_ic_runner import run_complex_factor_ic
from factor_ic.common.logger_config import get_logger


logger = get_logger(__name__)
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


def calculate_tail_price_volume_intensity(factor_df: pd.DataFrame) -> pd.DataFrame:
    """
    计算尾盘量价强度因子

    公式:
    - 尾盘涨跌幅 = (prices[-1] - prices[0]) / prices[0]
    - 尾盘量比 = sum(volumes) / volume
    - 尾盘量价强度 = 尾盘涨跌幅 × 尾盘量比

    Args:
        factor_df: 包含 date, asset, volume 列的 DataFrame
            - 'date': 交易日期
            - 'asset': 资产代码
            - 'volume': 全天成交量

    Returns:
        DataFrame，新增 'tail_price_volume_intensity' 列

    Note:
        - 遵循 MODULE.md 约束 #4：函数入口先 copy()
        - 需要合并尾盘数据（tail_trading_data.json.gz）
        - 除零防护：|prices[0]| < EPSILON 或 |volume| < EPSILON 时设为 NaN
        - 数据完整性：volumes 数组长度不足 13 时设为 NaN

    Example:
        >>> # 通过公共模块调用（推荐）
        >>> from factor_ic.common.factor_ic_runner import run_complex_factor_ic
        >>> result = run_complex_factor_ic(
        ...     factor_name="tail_price_volume_intensity",
        ...     factor_col="tail_price_volume_intensity",
        ...     factor_cols=["date", "asset", "volume"],
        ...     custom_factor_calculation=calculate_tail_price_volume_intensity,
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
        factor_df["tail_price_volume_intensity"] = np.nan
        return factor_df

    # 确保日期格式一致
    factor_df["date"] = pd.to_datetime(factor_df["date"]).dt.strftime("%Y-%m-%d")
    tail_df["date"] = pd.to_datetime(tail_df["date"]).dt.strftime("%Y-%m-%d")

    # 合并尾盘数据（按 date, asset）
    merged_df = factor_df.merge(tail_df[["date", "asset", "prices", "volumes"]], on=["date", "asset"], how="left")

    logger.info("尾盘数据合并完成: %d / %d 条匹配", merged_df["prices"].notna().sum(), len(factor_df))

    # 计算尾盘涨跌幅
    # prices 是列表或 NaN（合并后未匹配的记录）
    def calc_price_change(prices):
        # 处理 NaN/None（合并后未匹配的记录）
        # 注意：pd.isna() 对列表报 ValueError，先检查类型
        if not isinstance(prices, list):
            return np.nan
        if len(prices) < 13:
            return np.nan
        first_price = prices[0]
        last_price = prices[-1]
        if abs(first_price) < EPSILON:
            return np.nan
        return (last_price - first_price) / first_price

    merged_df["tail_price_change"] = merged_df["prices"].apply(calc_price_change)

    # 计算尾盘量比
    def calc_volume_ratio(volumes, total_volume):
        # 处理 NaN/None（合并后未匹配的记录）
        if not isinstance(volumes, list):
            return np.nan
        if len(volumes) < 13:
            return np.nan
        if total_volume is None or pd.isna(total_volume) or abs(total_volume) < EPSILON:
            return np.nan
        tail_volume = sum(volumes)
        return tail_volume / total_volume

    # 需要逐行处理（volumes 是列表，volume 是数值）
    merged_df["tail_volume_ratio"] = merged_df.apply(
        lambda row: calc_volume_ratio(row["volumes"], row["volume"]), axis=1
    )

    # 计算尾盘量价强度
    merged_df["tail_price_volume_intensity"] = merged_df["tail_price_change"] * merged_df["tail_volume_ratio"]

    # 统计有效因子数量
    valid_count = merged_df["tail_price_volume_intensity"].notna().sum()
    total_count = len(merged_df)
    logger.info(
        "尾盘量价强度因子计算完成: %d / %d 有效 (%.1f%%)",
        valid_count,
        total_count,
        100 * valid_count / total_count if total_count > 0 else 0,
    )

    # 返回只包含原列 + 因子列的 DataFrame（防止列名重复）
    result_cols = [c for c in factor_df.columns if c != "tail_price_volume_intensity"] + ["tail_price_volume_intensity"]
    return merged_df[result_cols]


# ============================================================================
# CLI 入口
# ============================================================================


def main():
    """CLI 主入口"""
    parser = argparse.ArgumentParser(description="尾盘量价强度因子 IC 计算器")
    parser.add_argument("--force-full", action="store_true", help="强制全量计算")
    parser.add_argument("--min-stocks", type=int, default=DEFAULT_MIN_STOCKS, help="最小股票数")

    args = parser.parse_args()

    # 启动参数日志（便于追溯本次运行配置）
    logger.info(
        "启动尾盘量价强度因子IC计算: min_stocks=%s, force_full=%s",
        args.min_stocks,
        args.force_full,
    )

    # 使用公共模块主入口（遵循 PROJECT.md 强制复用规范）
    result = run_complex_factor_ic(
        factor_name="tail_price_volume_intensity",
        factor_col="tail_price_volume_intensity",
        factor_cols=["date", "asset", "volume"],
        custom_factor_calculation=calculate_tail_price_volume_intensity,
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
    positive_ratio_str = f"{positive_ratio:.2%}" if positive_ratio is not None else "N/A"
    avg_stocks_str = f"{avg_stocks:.1f}" if avg_stocks is not None else "N/A"
    total_days_str = str(total_days) if total_days is not None else "N/A"
    date_range_str = f"{start_date} ~ {end_date}" if start_date and end_date else "N/A"

    summary_lines = [
        "=" * 60,
        "结果摘要",
        "=" * 60,
        f"因子名称: {result.get('factor_name', 'unknown')}",
        f"更新模式: {result.get('update_mode', 'unknown')}",
        f"日期范围: {date_range_str}",
        f"总交易日数: {total_days_str}",
        f"平均股票数: {avg_stocks_str}",
        "--- IC指标 ---",
        f"IC 均值: {ic_mean_str}",
        f"IC 标准差: {ic_std_str}",
        f"ICIR: {icir_str}",
        f"正比例: {positive_ratio_str}",
    ]
    logger.info("\n%s", "\n".join(summary_lines))

    # ic_mean 为 None 时额外输出 warning，便于告警系统捕获异常运行
    if ic_mean is None:
        logger.warning("本次计算 IC 均值为空，请检查数据源")

    # 确认结果处理完成后才输出"计算完成"日志（避免中途失败造成误导）
    logger.info("尾盘量价强度因子IC计算完成")

    return result


if __name__ == "__main__":
    try:
        main()
    except FactorCalcError:
        logger.exception("尾盘量价强度因子IC计算失败")
        sys.exit(1)
    except Exception:
        logger.exception("未预期的错误")
        sys.exit(1)
