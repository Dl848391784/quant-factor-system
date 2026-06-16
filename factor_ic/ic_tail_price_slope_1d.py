#!/usr/bin/env python3
"""
尾盘价格趋势斜率因子 IC 计算器 - 使用公共模块主入口

遵循 PROJECT.md 公共模块强制复用规范：
- 主流程使用 run_complex_factor_ic()(禁止手写三模式分支)
- 因子计算逻辑独立实现(calculate_tail_price_slope)

因子定义:
- 尾盘趋势斜率 = 线性回归斜率 / 均价(百分比形式)
- 公式: 对 prices 数组(13根5分钟K线收盘价)做线性回归
  - X = np.arange(13)  # 时间索引: 0, 1, 2, ..., 12
  - Y = np.array(prices)
  - slope, intercept = np.polyfit(X, Y, 1)
  - factor_value = slope / np.mean(prices)

含义:
- tail_price_slope > 0:尾盘价格上涨趋势
- tail_price_slope < 0:尾盘价格下跌趋势
- |tail_price_slope| 越大:趋势越强劲

归一化处理:
- 使用百分比斜率(slope / mean_price)
- 消除高价股和低价股的量纲差异
- 与 forward_return(百分比形式)可比

边界处理:
- prices 数组长度不足 13 时设为 NaN(数据不完整)
- mean_price 接近零时设为 NaN(除零防护)
- prices 包含 NaN/None 时返回 NaN(数据污染)

数据依赖:
- tail_trading_data.json.gz(尾盘5分钟K线数据)
- factor_ic_data.json.gz(主数据源,含 forward_return_1d)

作者: 云瑶
创建日期: 2026-06-02
版本历史:
  v1.0 (2026-06-02): 初始版本,实现尾盘价格趋势斜率因子 IC 计算
  v1.1 (2026-06-02): Round 1 优化 - 导入分组注释、main()返回值、版本历史完善
  v1.2 (2026-06-02): Round 2 优化 - 内部函数类型注解、未使用变量清理、docstring Example 完善
  v1.3 (2026-06-02): Round 3 优化 - 线性回归异常捕获精细化(LinAlgError/ValueError)
  v1.4 (2026-06-08): Round 4 优化 - FactorCalcError自定义异常、启动参数日志、结果摘要合并、__main__异常处理
"""

# 标准库导入
import argparse
import gzip
import json
import sys

# 第三方库导入
import numpy as np
import pandas as pd

# 添加项目路径
# 本地模块导入
from paths import DATA_FETCHERS_RESULT  # 遵循 PROJECT.md H7 规则

from factor_ic.common.cli_helpers import DEFAULT_MIN_STOCKS
from factor_ic.common.exceptions import DataSchemaError, FactorCalcError
from factor_ic.common.factor_ic_runner import run_factor_ic
from factor_ic.common.factor_spec import FactorSpec, register_factor
from factor_ic.common.factor_summary_logger import log_factor_summary
from factor_ic.common.logger_config import get_logger


logger = get_logger(__name__)

# ============================================================================
# 自定义异常类
# ============================================================================
EPSILON = 1e-10  # 避免除零阈值

# 尾盘数据路径(遵循 PROJECT.md H7 规则:使用 paths.py 单一来源)
TAIL_TRADING_DATA_PATH = DATA_FETCHERS_RESULT / "tail_trading_data.json.gz"


# ============================================================================
# 辅助函数:加载尾盘数据
# ============================================================================


def load_tail_trading_data() -> pd.DataFrame:
    """
    加载尾盘数据

    Returns:
        DataFrame,包含 date, asset, prices 列

    Raises:
        FileNotFoundError: 尾盘数据文件不存在
        ValueError: 尾盘数据格式错误
    """
    if not TAIL_TRADING_DATA_PATH.exists():
        raise FileNotFoundError(f"尾盘数据文件不存在: {TAIL_TRADING_DATA_PATH}")

    with gzip.open(TAIL_TRADING_DATA_PATH, "rt", encoding="utf-8") as f:
        data = json.load(f)

    if "data" not in data:
        raise ValueError("尾盘数据格式错误:缺少 'data' 字段")

    df = pd.DataFrame(data["data"])

    logger.info("尾盘数据加载完成: %d 条记录", len(df))
    return df


# ============================================================================
# 因子计算函数
# ============================================================================


def calculate_tail_price_slope(factor_df: pd.DataFrame) -> pd.DataFrame:
    """
        计算尾盘价格趋势斜率因子

        公式:
        - 线性回归:对 prices 数组做回归,得到 slope
        - 百分比斜率:factor_value = slope / mean_price

        Args:
            factor_df: 包含 date, asset 列的 DataFrame
                - 'date': 交易日期
                - 'asset': 资产代码

        Returns:
            DataFrame,新增 'tail_price_slope' 列

        Note:
            - 遵循 MODULE.md 约束 #4:函数入口先 copy()
            - 需要合并尾盘数据(tail_trading_data.json.gz)
            - 除零防护:|mean_price| < EPSILON 时设为 NaN
            - 数据完整性:prices 数组长度不足 13 时设为 NaN

        Example:
            >>> # 正常场景:通过公共模块调用(推荐)
            >>> from factor_ic.common.factor_ic_runner import run_factor_ic
    from factor_ic.common.factor_spec import FactorSpec, register_factor
            >>> result = run_factor_ic(
            spec=SPEC,
            min_stocks=args.min_stocks,
            force_full=args.force_full,
            logger=logger,
        )
            >>> # 异常场景:尾盘数据文件不存在(返回全 NaN 因子值,不中断计算)
            >>> # 系统自动 fallback,日志记录 FileNotFoundError
    """
    # 遵循 MODULE.md 约束 #4:函数入口先 copy()
    factor_df = factor_df.copy()

    # 加载尾盘数据
    # 设计意图:文件不存在时返回全 NaN(fallback),而非抛出异常中断计算
    # 原因:尾盘数据可能因上游 fetch_tail_trading.py 未运行而缺失,
    #       但因子 IC 计算不应因此中断,应记录日志并返回空因子值
    try:
        tail_df = load_tail_trading_data()
    except FileNotFoundError as e:
        logger.error("尾盘数据文件不存在,返回全 NaN: %s", e)
        factor_df["tail_price_slope"] = np.nan
        return factor_df

    # 确保日期格式一致
    factor_df["date"] = pd.to_datetime(factor_df["date"]).dt.strftime("%Y-%m-%d")
    tail_df["date"] = pd.to_datetime(tail_df["date"]).dt.strftime("%Y-%m-%d")

    # 合并尾盘数据(按 date, asset)
    merged_df = factor_df.merge(tail_df[["date", "asset", "prices"]], on=["date", "asset"], how="left")

    logger.info("尾盘数据合并完成: %d / %d 条匹配", merged_df["prices"].notna().sum(), len(factor_df))

    # 计算尾盘价格趋势斜率
    # prices 是列表或 NaN(合并后未匹配的记录)
    def calc_slope(prices: list) -> float:
        """
        计算百分比斜率

        Args:
            prices: 13根5分钟K线收盘价列表

        Returns:
            百分比斜率(slope / mean_price),异常时返回 np.nan
        """
        # 处理 NaN/None(合并后未匹配的记录)
        # 注意:pd.isna() 对列表报 ValueError,先检查类型
        if not isinstance(prices, list):
            return np.nan
        if len(prices) < 13:
            logger.debug("prices 数组长度不足 13: %d", len(prices))
            return np.nan

        # 转换为 numpy 数组
        Y = np.array(prices)

        # 检查数据污染(包含 NaN/None)
        if np.any(np.isnan(Y)):
            logger.debug("prices 包含 NaN 值")
            return np.nan

        # 时间索引
        X = np.arange(13)

        # 线性回归
        # numpy.polyfit 失败时抛出 np.linalg.LinAlgError(如数据全相同)
        try:
            slope, _ = np.polyfit(X, Y, 1)  # intercept 不需要
        except np.linalg.LinAlgError as e:
            logger.warning("线性回归计算失败(LinAlgError): %s", e)
            return np.nan
        except ValueError as e:
            # 数据维度错误等
            logger.warning("线性回归参数错误: %s", e)
            return np.nan

        # 计算均价
        mean_price = np.mean(Y)

        # 除零防护
        if abs(mean_price) < EPSILON:
            logger.debug("均价接近零: %.10f", mean_price)
            return np.nan

        # 百分比斜率
        factor_value = slope / mean_price
        return factor_value

    merged_df["tail_price_slope"] = merged_df["prices"].apply(calc_slope)

    # 统计有效因子数量
    valid_count = merged_df["tail_price_slope"].notna().sum()
    total_count = len(merged_df)
    logger.info(
        "尾盘价格趋势斜率因子计算完成: %d / %d 有效 (%.1f%%)",
        valid_count,
        total_count,
        100 * valid_count / total_count if total_count > 0 else 0,
    )

    # 返回只包含原列 + 因子列的 DataFrame
    result_cols = list(factor_df.columns) + ["tail_price_slope"]
    return merged_df[result_cols]


# ============================================================================
# CLI 入口
# ============================================================================


# ============================================================================
# FactorSpec 声明式注册（遵循 factor_cols_literal_constant_design.md §4.1）
# ============================================================================

# 声明计算所需的输入列（供 FactorSpec 自动派生 required_columns，遵循 factor_spec_required_cols_and_sys_path_design.md §3.1）
calculate_tail_price_slope.required_cols = ["date", "asset"]

SPEC = register_factor(
    FactorSpec(
        factor_name="tail_price_slope",
        factor_col="tail_price_slope",
        calculation=calculate_tail_price_slope,
    )
)


def main():
    """CLI 主入口"""
    parser = argparse.ArgumentParser(description="尾盘价格趋势斜率因子 IC 计算器")
    parser.add_argument("--force-full", action="store_true", help="强制全量计算")
    parser.add_argument("--min-stocks", type=int, default=DEFAULT_MIN_STOCKS, help="最小股票数")

    args = parser.parse_args()

    # 启动横幅由公共模块 factor_ic_runner 统一打印（含 min_stocks/force_full）
    # 使用公共模块主入口(遵循 PROJECT.md 强制复用规范)
    result = run_factor_ic(
        spec=SPEC,
        min_stocks=args.min_stocks,
        force_full=args.force_full,
        logger=logger,
    )

    # 防御性检查: result 为 None 时抛出业务异常(遵循 PROJECT.md 异常处理规范)
    if result is None:
        raise FactorCalcError("run_factor_ic 返回 None,数据加载或计算可能失败")

    # 包裹 log_factor_summary：摘要层失败 → sys.exit(3) 显式辅助层失败信号
    # （PROJECT.md H12 R17）。因子计算 result 已成功生成，主结果产物可用，下游
    # backtest/comprehensive/summary 可正常消费；仅旁路日志摘要失败时返回 exit 3，
    # 与业务失败（exit 1）和 import-time 注册失败（exit 2）严格区分。
    try:
        log_factor_summary(result, "尾盘价格趋势斜率因子", logger)
    except Exception:
        logger.exception(
            "log_factor_summary 摘要输出阶段失败（因子计算 result 已成功生成；"
            "故障源 = 摘要日志层而非 run_factor_ic 业务路径）"
        )
        sys.exit(3)  # H12 R17：辅助层失败专用退出码

    # 确认结果处理完成后才输出"计算完成"日志
    logger.info("尾盘价格趋势斜率因子IC计算完成")

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
        logger.error("因子计算业务异常: %s", e)
        sys.exit(5)  # H12 R19: 因子计算失败 → 检查计算代码
    except Exception as e:
        logger.exception("未预期异常: %s", e)
        sys.exit(1)
