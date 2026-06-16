#!/usr/bin/env python3
"""
日内价格强度因子 IC 计算器 - 使用公共模块主入口

遵循 PROJECT.md 公共模块强制复用规范：
- 主流程使用 run_complex_factor_ic()（禁止手写三模式分支）
- 因子计算使用自定义函数 calculate_intraday_intensity()

代码量：~80行（因子计算 + CLI 入口），主流程使用公共模块。

因子定义：
- intraday_intensity = (Close - Open) / (High - Low)
- 含义：日内价格强度
  - 值范围：-1 到 1
  - 正值（阳线）：收盘价高于开盘价，值越大表示涨幅占振幅比例越大
  - 负值（阴线）：收盘价低于开盘价，值越小表示跌幅占振幅比例越大
  - = 0：收盘价等于开盘价（十字星）
  - 边界：High = Low 时分母为 0，设为 NaN

边界处理：
- High == Low 时设为 NaN（除零保护）
- 遵循 MODULE.md 约束 4：DataFrame 参数先 copy()
- 遵循 MODULE.md 约束 10：使用 np.nan 替代 pd.NA

作者: 云瑶
创建日期: 2026-06-02
版本历史:
  v1.0 (2026-06-02): 初始版本，使用 run_complex_factor_ic 公共模块
"""

import argparse
import logging
import sys

import numpy as np
import pandas as pd

# 添加项目路径
# 导入公共模块主入口（遵循 PROJECT.md 强制复用规范）
from factor_ic.common.cli_helpers import DEFAULT_MIN_STOCKS
from factor_ic.common.exceptions import DataSchemaError, FactorCalcError
from factor_ic.common.factor_ic_runner import run_factor_ic
from factor_ic.common.factor_spec import FactorSpec, register_factor
from factor_ic.common.logger_config import get_logger


logger = get_logger(__name__)
# ============================================================================
# 因子计算函数
# ============================================================================


def calculate_intraday_intensity(
    factor_df: pd.DataFrame, logger_arg: logging.Logger | None = None, skip_validation: bool = False
) -> pd.DataFrame:
    """计算日内价格强度因子

    公式: intraday_intensity = (Close - Open) / (High - Low)

    Args:
        factor_df: 包含 open/close/high/low 列的 DataFrame
        logger_arg: 调用方传入的 logger（遵循 MODULE.md 日志传递规范）
        skip_validation: 跳过数据量校验（用于单元测试）

    Returns:
        添加了 intraday_intensity 列的 DataFrame

    Raises:
        ValueError: 数据校验失败（缺失必需列或数据量不足）

    Note:
        - 遵循 MODULE.md 约束 4：DataFrame 参数先 copy()
        - 遵循 MODULE.md 约束 10：使用 np.nan 替代 pd.NA
        - High == Low 时设为 NaN（除零保护）

    Example:
        >>> import pandas as pd
        >>> df = pd.DataFrame(
        ...     {
        ...         "date": ["2026-01-01"],
        ...         "asset": ["000001"],
        ...         "open": [10.0],
        ...         "close": [10.5],
        ...         "high": [11.0],
        ...         "low": [9.5],
        ...     }
        ... )
        >>> result = calculate_intraday_intensity(df, skip_validation=True)
        >>> result["intraday_intensity"].iloc[0]
        0.25
    """
    # 局部 logger 命名为 _logger，避免与模块级 logger 同名遮蔽
    # （遵循 AGENTS.md 规则 #14：禁止用同名变量"伪装"作用域隔离）
    _logger = logger_arg or logger

    # 1. 数据校验（遵循 MODULE.md v3.16 新因子数据校验规范）
    required_cols = ["open", "close", "high", "low"]
    missing_cols = [col for col in required_cols if col not in factor_df.columns]
    if missing_cols:
        raise ValueError(
            f"数据校验失败：缺失必需列 {missing_cols}\n实际列: {list(factor_df.columns)}\n请检查数据源是否包含所需列"
        )

    # 2. DataFrame 参数先 copy()（遵循 MODULE.md 约束 4）
    factor_df = factor_df.copy()

    # 3. 有效数据量校验（可通过 skip_validation 跳过，但入参规模仍需记录）
    valid_rows = factor_df[required_cols].dropna().shape[0]
    if not skip_validation:
        if valid_rows < 100:
            raise ValueError(f"数据校验失败：有效数据量不足\n期望 ≥ 100 行，实际 {valid_rows} 行\n请检查数据源质量")
        _logger.info("开始计算日内强度因子，有效数据行数: %s", valid_rows)
    else:
        # skip_validation=True 主要用于单元测试，仍记录一条 debug 级日志便于排查
        _logger.debug("开始计算日内强度因子（skip_validation=True），有效数据行数: %s", valid_rows)

    # 4. 计算振幅（分母）
    amplitude = factor_df["high"] - factor_df["low"]

    # 5. 除零/异常保护：振幅 ≤ 0 时分母置 NaN，避免中间产生 inf
    #    （遵循 AGENTS.md 规则 #14：不允许"先算 inf 再覆盖"的二次处理歧义；
    #    统计 mask 与替换 mask 必须共用同一份，防止负振幅等数据异常时计数与
    #    实际替换数不匹配）
    zero_or_negative_mask = amplitude <= 0
    invalid_amplitude_count = int(zero_or_negative_mask.sum())  # type: ignore[union-attr]
    if invalid_amplitude_count > 0:
        _logger.warning("发现 %s 条振幅 ≤ 0 的记录（含 High=Low 与异常负振幅），已设为 NaN", invalid_amplitude_count)

    # 6. 用 NaN 替换无效分母后再除：分母为 NaN 时结果直接为 NaN，无 inf 中间值
    safe_amplitude = amplitude.where(~zero_or_negative_mask, np.nan)
    intraday_intensity = (factor_df["close"] - factor_df["open"]) / safe_amplitude

    # 7. 添加因子列
    factor_df["intraday_intensity"] = intraday_intensity

    # 8. 统计计算结果
    valid_factor_count = factor_df["intraday_intensity"].notna().sum()
    _logger.info("日内强度因子计算完成，有效因子值 %s 条", valid_factor_count)

    return factor_df


# 因子计算所需列（供 backtest/common/factor_cli.py 透传给 load_factor_return_data 使用）
# 缺失此属性会导致 required_factor_cols=None → 列过滤白名单仅含 [date, asset]
# → calculator 找不到 OHLC 触发"数据校验失败：缺失必需列"。
# 同模式：data_fetchers/factor_calculator.py::calculate_amplitude.required_cols
calculate_intraday_intensity.required_cols = ["open", "close", "high", "low"]  # type: ignore[attr-defined]


# ============================================================================
# CLI 入口
# ============================================================================


# ============================================================================
# FactorSpec 声明式注册（遵循 factor_cols_literal_constant_design.md §4.1）
# ============================================================================

SPEC = register_factor(
    FactorSpec(
        factor_name="intraday_intensity",
        factor_col="intraday_intensity",
        calculation=calculate_intraday_intensity,
    )
)


def main():
    """CLI 主入口"""
    parser = argparse.ArgumentParser(description="日内价格强度因子 IC 计算器")
    parser.add_argument("--force-full", action="store_true", help="强制全量计算")
    parser.add_argument("--min-stocks", type=int, default=DEFAULT_MIN_STOCKS, help="最小股票数")

    args = parser.parse_args()

    # 启动横幅由公共模块 factor_ic_runner 统一打印（含 min_stocks/force_full）

    # 使用 FactorSpec 驱动入口（遵循 factor_cols_literal_constant_design.md §4.1）
    # 注意：run_complex_factor_ic 需要 factor_cols 和 custom_factor_calculation
    result = run_factor_ic(
        spec=SPEC,
        min_stocks=args.min_stocks,
        force_full=args.force_full,
        logger=logger,
    )

    # run_factor_ic 在 factor_ic_runner.py 中所有路径都显式 return result 或
    # build_error_result(...)（始终为 dict），不存在返回 None 的代码路径。
    # 因此此处的 `if result is None` 守卫属于永不触发的死代码（违反
    # AGENTS.md 规则 #14），已删除。若未来 callee 行为变化可由调用方在
    # 解构字段时通过 .get(...) 防御。

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

    # 格式化各字段（None 时显示 N/A）
    ic_mean_str = f"{ic_mean:.4f}" if ic_mean is not None else "N/A"
    ic_std_str = f"{ic_std:.4f}" if ic_std is not None else "N/A"
    icir_str = f"{icir:.2f}" if icir is not None else "N/A"
    positive_ratio_str = f"{positive_ratio:.2%}" if positive_ratio is not None else "N/A"

    summary_lines = [
        "=" * 60,
        "结果摘要",
        "=" * 60,
        f"因子名称: {result.get('factor_name', 'unknown')}",
        f"更新模式: {result.get('update_mode', 'unknown')}",
        f"日期范围: {period.get('start', 'N/A')} ~ {period.get('end', 'N/A')}",
        f"有效天数: {sample_stats.get('valid_days', 0)} 天",
        "--- IC指标 ---",
        f"IC 均值: {ic_mean_str}",
        f"IC 标准差: {ic_std_str}",
        f"ICIR: {icir_str}",
        f"IC>0 占比: {positive_ratio_str}",
    ]
    logger.info("\n%s", "\n".join(summary_lines))

    # ic_mean 为 None 时额外输出 warning，便于告警系统捕获异常运行
    if ic_mean is None:
        logger.warning("本次计算 IC 均值为空，请检查数据源")

    # 确认结果处理完成后才输出"计算完成"日志（避免中途失败造成误导）
    logger.info("日内强度因子IC计算完成")

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
        logger.error("日内强度因子IC计算失败: %s", e)
        sys.exit(5)  # H12 R19: 因子计算失败 → 检查计算代码
    except Exception:
        # 未预期异常，使用 exception()（自动打印完整堆栈）
        logger.exception("未预期的错误")
        sys.exit(1)
