#!/usr/bin/env python3
"""
尾盘量能加速度因子 IC 计算器 - 使用公共模块主入口

遵循 PROJECT.md 公共模块强制复用规范：
- 主流程使用 run_complex_factor_ic()（禁止手写三模式分支）
- 因子计算逻辑独立实现（calculate_tail_volume_acceleration）

因子定义：
- 前半段: 14:00-14:30（含14:00不含14:30）→ volumes[0:6]（6根K线）
- 后半段: 14:30-15:00（不含14:30含15:00）→ volumes[7:13]（6根K线）
- 量能加速度 = 后半段成交量总和 / 前半段成交量总和
- factor_value = sum(volumes[7:13]) / sum(volumes[0:6])

含义：
- factor_value > 1：后半段成交量更大，尾盘加速交易
- factor_value = 1：前后段成交量相等，平稳交易
- factor_value < 1：前半段成交量更大，尾盘减速交易

边界处理：
- volumes 数组长度不足 13 时设为 NaN（数据不完整）
- volumes 包含 NaN/None 时返回 NaN（数据污染）
- 前半段成交量总和为 0 时设为 NaN（除零防护）

数据依赖：
- tail_trading_data.json.gz（尾盘5分钟K线数据，含 volumes 数组）
- factor_ic_data.json.gz（主数据源）

作者: 云瑶
创建日期: 2026-06-02
版本历史:
  v1.0 (2026-06-02): 初始版本，实现尾盘量能加速度因子 IC 计算
  v1.1 (2026-06-02): Round 1 优化 - 导入分组注释、版本历史完善、main()返回值
  v1.2 (2026-06-02): Round 2 优化 - 内部函数类型注解完善（list | np.ndarray）
"""

# 标准库导入
import argparse
import gzip
import json
import sys
from pathlib import Path

# 第三方库导入
import numpy as np
import pandas as pd


# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent.parent))

# 本地模块导入
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


def _calc_volume_acceleration(volumes: list | np.ndarray) -> float:
    """
    计算量能加速度（后半段/前半段）- 内部函数

    前半段: volumes[0:6] → 14:00, 14:05, 14:10, 14:15, 14:20, 14:25
    后半段: volumes[7:13] → 14:35, 14:40, 14:45, 14:50, 14:55, 15:00
    注意: 14:30（索引6）不属于任何一段

    Args:
        volumes: 成交量列表（13个元素）

    Returns:
        量能加速度值，或 NaN（数据异常时）

    Example:
        >>> _calc_volume_acceleration([10, 20, 30, 40, 50, 60, 70, 80, 90, 100, 110, 120, 130])
        3.0  # (630/210)
    """
    # 处理 NaN/None（合并后未匹配的记录）
    # 注意：pd.isna() 对列表报 ValueError，先检查类型
    if not isinstance(volumes, list):
        return np.nan
    if len(volumes) < 13:
        return np.nan
    # 检查是否包含 NaN/None
    if any(v is None or (isinstance(v, float) and np.isnan(v)) for v in volumes):
        return np.nan

    # 前半段成交量总和（索引 0-5）
    front_volume = sum(volumes[0:6])
    # 后半段成交量总和（索引 7-12）
    back_volume = sum(volumes[7:13])

    # 除零防护
    if front_volume < EPSILON:
        return np.nan

    return back_volume / front_volume


def calculate_tail_volume_acceleration(factor_df: pd.DataFrame) -> pd.DataFrame:
    """
    计算尾盘量能加速度因子

    公式:
    - 前半段成交量总和 = sum(volumes[0:6])  # 14:00-14:25
    - 后半段成交量总和 = sum(volumes[7:13])  # 14:35-15:00
    - 量能加速度 = 后半段 / 前半段

    Args:
        factor_df: 包含 date, asset 列的 DataFrame
            - 'date': 交易日期
            - 'asset': 资产代码

    Returns:
        DataFrame，新增 'tail_volume_acceleration' 列

    Note:
        - 遵循 MODULE.md 约束 #4：函数入口先 copy()
        - 需要合并尾盘数据（tail_trading_data.json.gz）
        - 除零防护：前半段成交量总和 < EPSILON 时设为 NaN
        - 数据完整性：volumes 数组长度不足 13 时设为 NaN

    Example:
        >>> # 通过公共模块调用（推荐）
        >>> from factor_ic.common.factor_ic_runner import run_complex_factor_ic
        >>> result = run_complex_factor_ic(
        ...     factor_name="tail_volume_acceleration",
        ...     factor_col="tail_volume_acceleration",
        ...     factor_cols=["date", "asset"],
        ...     custom_factor_calculation=calculate_tail_volume_acceleration,
        ... )
    """
    # 遵循 MODULE.md 约束 #4：函数入口先 copy()
    factor_df = factor_df.copy()

    # 加载尾盘数据
    try:
        tail_df = load_tail_trading_data()
    except FileNotFoundError as e:
        logger.error("尾盘数据文件不存在，返回全 NaN: %s", e)
        factor_df["tail_volume_acceleration"] = np.nan
        return factor_df

    # 确保日期格式一致
    factor_df["date"] = pd.to_datetime(factor_df["date"]).dt.strftime("%Y-%m-%d")
    tail_df["date"] = pd.to_datetime(tail_df["date"]).dt.strftime("%Y-%m-%d")

    # 合并尾盘数据（按 date, asset）
    merged_df = factor_df.merge(tail_df[["date", "asset", "volumes"]], on=["date", "asset"], how="left")

    n_matched = merged_df["volumes"].notna().sum() if "volumes" in merged_df.columns else 0
    logger.info(
        "尾盘数据合并完成: %d / %d 条匹配",
        n_matched,
        len(factor_df),
    )

    # 计算量能加速度
    merged_df["tail_volume_acceleration"] = merged_df["volumes"].apply(_calc_volume_acceleration)

    # 统计有效因子数量
    valid_count = merged_df["tail_volume_acceleration"].notna().sum()
    total_count = len(merged_df)
    logger.info(
        "尾盘量能加速度因子计算完成: %d / %d 有效 (%.1f%%)",
        valid_count,
        total_count,
        100 * valid_count / total_count if total_count > 0 else 0,
    )

    # 返回只包含原列 + 因子列的 DataFrame
    result_cols = list(factor_df.columns) + ["tail_volume_acceleration"]
    return merged_df[result_cols]


# ============================================================================
# CLI 入口
# ============================================================================


def main():
    """CLI 主入口"""
    parser = argparse.ArgumentParser(description="尾盘量能加速度因子 IC 计算器")
    parser.add_argument("--force-full", action="store_true", help="强制全量计算")
    parser.add_argument("--min-stocks", type=int, default=DEFAULT_MIN_STOCKS, help="最小股票数")

    args = parser.parse_args()

    # 使用公共模块主入口（遵循 PROJECT.md 强制复用规范）
    result = run_complex_factor_ic(
        factor_name="tail_volume_acceleration",
        factor_col="tail_volume_acceleration",
        factor_cols=["date", "asset"],  # 不需要 volume，只需 date/asset 匹配尾盘数据
        custom_factor_calculation=calculate_tail_volume_acceleration,
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
