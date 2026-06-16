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
  v1.3 (2026-06-02): Round 3 优化 - 边界处理防御性编程确认（isinstance替代pd.isna，无宽泛Exception）
  v1.4 (2026-06-02): Round 4 优化 - main()添加返回值（对照 ic_tail_price_slope_1d.py）
  v1.5 (2026-06-02): Round 5 优化 - docstring Example 完善（添加异常场景说明）
  v1.6 (2026-06-02): Round 6 优化 - 内部函数添加 debug 日志（对照 ic_tail_price_slope_1d.py）
"""

# 标准库导入
import argparse
import sys

# 第三方库导入
import numpy as np
import pandas as pd

# 添加项目路径
# 本地模块导入
from factor_ic.common.cli_helpers import DEFAULT_MIN_STOCKS
from factor_ic.common.exceptions import DataSchemaError, FactorCalcError
from factor_ic.common.factor_ic_runner import run_factor_ic
from factor_ic.common.factor_spec import FactorSpec, register_factor
from factor_ic.common.logger_config import get_logger
from factor_ic.common.tail_data_loader import load_tail_trading_data  # 公共模块复用


logger = get_logger(__name__)
EPSILON = 1e-10  # 避免除零阈值


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
        logger.debug("volumes 数组长度不足 13: %d", len(volumes))
        return np.nan
    # 检查是否包含 NaN/None
    if any(v is None or (isinstance(v, float) and np.isnan(v)) for v in volumes):
        logger.debug("volumes 包含 NaN/None 值")
        return np.nan

    # 前半段成交量总和（索引 0-5）
    front_volume = sum(volumes[0:6])
    # 后半段成交量总和（索引 7-12）
    back_volume = sum(volumes[7:13])

    # 除零防护
    if front_volume < EPSILON:
        logger.debug("前半段成交量接近零: %.10f", front_volume)
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
                >>> # 正常场景：通过公共模块调用（推荐）
                >>> from factor_ic.common.factor_ic_runner import run_factor_ic
    from factor_ic.common.factor_spec import FactorSpec, register_factor
                >>> result = run_factor_ic(
            spec=SPEC,
            min_stocks=args.min_stocks,
            force_full=args.force_full,
            logger=logger,
        )
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

    # 返回只包含原列 + 因子列的 DataFrame（防止列名重复）
    result_cols = [c for c in factor_df.columns if c != "tail_volume_acceleration"] + ["tail_volume_acceleration"]
    return merged_df[result_cols]


# ============================================================================
# CLI 入口
# ============================================================================


# ============================================================================
# FactorSpec 声明式注册（遵循 factor_cols_literal_constant_design.md §4.1）
# ============================================================================

# 声明计算所需的输入列（供 FactorSpec 自动派生 required_columns，遵循 factor_spec_required_cols_and_sys_path_design.md §3.1）
calculate_tail_volume_acceleration.required_cols = ["date", "asset"]

SPEC = register_factor(
    FactorSpec(
        factor_name="tail_volume_acceleration",
        factor_col="tail_volume_acceleration",
        calculation=calculate_tail_volume_acceleration,
    )
)


def main():
    """CLI 主入口"""
    parser = argparse.ArgumentParser(description="尾盘量能加速度因子 IC 计算器")
    parser.add_argument("--force-full", action="store_true", help="强制全量计算")
    parser.add_argument("--min-stocks", type=int, default=DEFAULT_MIN_STOCKS, help="最小股票数")

    args = parser.parse_args()

    # 启动横幅由公共模块 factor_ic_runner 统一打印（含 min_stocks/force_full）
    # 使用 FactorSpec 驱动入口（遵循 factor_cols_literal_constant_design.md §4.1）
    result = run_factor_ic(
        spec=SPEC,
        min_stocks=args.min_stocks,
        force_full=args.force_full,
        logger=logger,
    )

    # 防御性检查：result 为 None 时抛出异常（遵循 PROJECT.md 异常处理规范）
    if result is None:
        raise FactorCalcError("run_factor_ic 返回 None，数据加载或计算可能失败")

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
    logger.info("\n%s", "\n".join(summary_lines))

    # ic_mean 为 None 时额外输出 warning，便于告警系统捕获异常运行
    if ic_mean is None:
        logger.warning("本次计算 IC 均值为空，请检查数据源")

    return result


if __name__ == "__main__":
    try:
        main()
    except DataSchemaError as e:
        # 数据 Schema 校验失败（公共模块 validate_required_columns 抛出）：
        # H12 R18 → exit 4 与因子计算失败（exit 5）严格区分。
        # MODULE.md M22：业务异常用 logger.error 不打堆栈。
        logger.error("数据 Schema 校验失败 (factor=%s): %s", e.factor_name, e)
        sys.exit(4)  # H12 R18: schema 失败 → 检查上游数据
    except FactorCalcError as e:
        # 已知业务异常，使用 error()（不打印完整堆栈，但保留错误内容）
        logger.error("尾盘量能加速度因子IC计算失败: %s", e)
        sys.exit(5)  # H12 R19: 因子计算失败 → 检查计算代码
    except Exception:
        # 未预期异常，使用 exception()（自动打印完整堆栈）
        logger.exception("未预期的错误")
        sys.exit(1)
