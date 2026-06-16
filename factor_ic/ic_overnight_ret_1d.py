#!/usr/bin/env python3
"""
隔夜收益率因子 IC 计算器 - 使用公共模块主入口

遵循 PROJECT.md 公共模块强制复用规范：
- 主流程使用 run_complex_factor_ic()（禁止手写三模式分支）
- 因子计算逻辑独立实现（calculate_overnight_return）

代码量：~120行（CLI 入口 + 结果摘要 + 异常处理），因子计算约80行。

因子定义：
- overnight_ret = (今日开盘价 - 昨日收盘价) / 昨日收盘价
- 含义：隔夜涨跌幅（收盘到开盘的价格变化）
  - 正值 → 隔夜上涨（开盘高于昨收）
  - 负值 → 隔夜下跌（开盘低于昨收）
  - 范围：理论 [-∞, +∞)，A股日涨跌幅±10%

边界处理：
- 第一天数据设为 NaN（无昨日收盘价）
- 昨日收盘价 < EPSILON 时设为 NaN（除零防护）
- 按资产分组计算（每只股票独立）

作者: 云瑶
创建日期: 2026-05-28
版本历史:
  v1.0 (2026-05-28): 初始版本，实现隔夜收益率因子 IC 计算
  v1.1 (2026-05-31):
    - argparse 导入移至文件顶部（遵循 PEP 8）
    - 删除启动日志（公共模块已有等效日志）
    - 新增 result 为 None 保底处理
    - 防御性访问改为 .get() + or {}（处理键存在但值为 None）
    - 新增 ic_distribution_consistency 字段读取（对齐 MODULE.md 第56行）
    - ic_mean/ic_std/icir 为 None 时补充 warning
    - positive_ratio 为 None 时补充 warning（独立 if 语句）
    - 异常处理简化（删除冗余 RuntimeError 分支）
    - 代码量注释更新（反映实际行数）
  v1.2 (2026-05-31):
    - calculate_overnight_return 函数 logger 改为使用 __name__（避免硬编码）
    - 函数内 logger 变量改名为 log（避免遮蔽模块级 logger）
  v1.3 (2026-05-31):
    - 代码量注释更新（~100行 + ~70行，反映实际行数）
  v1.4 (2026-06-01):
    - calculate_overnight_return 函数签名修正（删除 logger_arg 参数）
      - 原因：公共模块调用 custom_factor_calculation(factor_df, **params) 不传 logger
      - 改为直接使用模块级 logger
    - Docstring 示例补充 factor_cols=['open', 'close', 'asset', 'date']
    - 除零防护逻辑完善：
      - 原逻辑 prev_close < EPSILON 漏检负数收盘价
      - 新逻辑：(prev_close.abs() < EPSILON) | (prev_close < 0)
      - 分别输出 warning（极小值 vs 负数，语义清晰）
    - valid_count/total_count 除零防护（空 DataFrame 场景）
    - factor_cols 补充 asset, date 列（groupby 和 shift 依赖）
    - N/A 日志信息补充原因（消除与 warning 信息断层）
    - 代码量注释更新（~120行 + ~80行，反映实际行数）
  v1.5 (2026-06-01):
    - mask 互斥条件修正（negative_mask = prev_close < 0 & ~near_zero_mask）
      - 原因：负数收盘价可能被重复处理两次
    - 删除无意义的 log = logger 赋值（直接使用模块级 logger）
    - icir N/A 原因注释修正（"IC 标准差为 0 或数据不足"）
    - factor_cols 顺序依赖注释确认（公共模块按列名取列，data_loader.py 第205-222行）
"""

import argparse
import sys

import numpy as np

# 添加项目路径
# 导入公共模块主入口（遵循 PROJECT.md 强制复用规范）
from factor_ic.common.cli_helpers import DEFAULT_MIN_STOCKS
from factor_ic.common.exceptions import DataSchemaError, FactorCalcError
from factor_ic.common.factor_ic_runner import run_factor_ic
from factor_ic.common.factor_spec import FactorSpec, register_factor
from factor_ic.common.logger_config import get_logger


logger = get_logger(__name__)
EPSILON = 1e-10  # 避免除零阈值


# ============================================================================
# 因子计算函数
# ============================================================================


def calculate_overnight_return(factor_df):
    """
        计算隔夜收益率因子

        公式: overnight_ret = (今日开盘价 - 昨日收盘价) / 昨日收盘价

        Args:
            factor_df: 包含 open, close, asset, date 列的 DataFrame
                - 'asset': 资产代码（用于分组）
                - 'date': 交易日期
                - 'open': 开盘价
                - 'close': 收盘价

        Returns:
            DataFrame，新增 'overnight_ret' 列

        Note:
            - 遵循 MODULE.md 约束 #4：函数入口先 copy()
            - 第一天数据为 NaN（无昨日收盘价）
            - 除零防护：|prev_close| < EPSILON 或 prev_close < 0 时设为 NaN
            - 按资产分组计算（每只股票独立）

        Example:
            >>> # 通过公共模块调用（推荐）
            >>> from factor_ic.common.factor_ic_runner import run_factor_ic
    from factor_ic.common.factor_spec import FactorSpec, register_factor
            >>> result = run_factor_ic(
            spec=SPEC,
            min_stocks=args.min_stocks,
            force_full=args.force_full,
            logger=logger,
        )
            >>> # 独立调用（用于测试，需确保数据包含 asset, date 列）
            >>> factor_df = pd.DataFrame(
            ...     {
            ...         "asset": ["A", "A", "B", "B"],
            ...         "date": ["2026-05-01", "2026-05-02", "2026-05-01", "2026-05-02"],
            ...         "open": [10.0, 10.5, 20.0, 21.0],
            ...         "close": [10.2, 10.8, 20.5, 21.5],
            ...     }
            ... )
            >>> result_df = calculate_overnight_return(factor_df)
            >>> print(result_df["overnight_ret"])
            >>> # asset A: NaN, 0.0294 (第一天NaN，第二天=(10.5-10.2)/10.2)
            >>> # asset B: NaN, 0.0244 (第一天NaN，第二天=(21.0-20.5)/20.5)
    """
    # 遵循 MODULE.md 约束 #4：函数入口先 copy()
    factor_df = factor_df.copy()

    # 按资产分组计算（每只股票独立）
    # 计算公式：overnight_ret = (open - close.shift(1)) / close.shift(1)
    prev_close = factor_df.groupby("asset")["close"].shift(1)

    # 计算隔夜收益率
    factor_df["overnight_ret"] = (factor_df["open"] - prev_close) / prev_close

    # 除零防护：检测极小值和负数收盘价（数据污染场景）
    # 条件 1: |prev_close| < EPSILON → 除零风险
    # 条件 2: prev_close < 0 → 数据污染（负数收盘价）
    # 注意：两个 mask 必须互斥，避免负数收盘价被重复处理
    near_zero_mask = prev_close.abs() < EPSILON
    negative_mask = (prev_close < 0) & ~near_zero_mask  # 排除已处理的极小值

    # 分别处理两种异常（语义清晰，日志可追溯）
    if near_zero_mask.any():
        near_zero_count = near_zero_mask.sum()
        logger.warning(
            "发现 %s 个极小收盘价（|close| < %s），存在除零风险，隔夜收益率已设为 NaN", near_zero_count, EPSILON
        )
        factor_df.loc[near_zero_mask, "overnight_ret"] = np.nan

    if negative_mask.any():
        negative_count = negative_mask.sum()
        logger.warning("发现 %s 个负数收盘价（close < 0），数据污染场景，隔夜收益率已设为 NaN", negative_count)
        factor_df.loc[negative_mask, "overnight_ret"] = np.nan

    # 统计计算结果
    valid_count = factor_df["overnight_ret"].notna().sum()
    total_count = len(factor_df)

    # 除零防护：空 DataFrame 时跳过比例计算
    if total_count == 0:
        logger.warning("传入空 DataFrame，隔夜收益率计算跳过")
        return factor_df

    logger.info(
        "隔夜收益率计算完成\n有效值: %s / %s (%.2f%%)",
        valid_count,
        total_count,
        valid_count / total_count * 100,
    )

    return factor_df


# ============================================================================
# CLI 入口
# ============================================================================


# ============================================================================
# FactorSpec 声明式注册（遵循 factor_cols_literal_constant_design.md §4.1）
# ============================================================================

# 声明计算所需的输入列（供 FactorSpec 自动派生 required_columns，遵循 factor_spec_required_cols_and_sys_path_design.md §3.1）
calculate_overnight_return.required_cols = ["date", "asset", "open", "close"]

SPEC = register_factor(
    FactorSpec(
        factor_name="overnight_ret",
        factor_col="overnight_ret",
        calculation=calculate_overnight_return,
    )
)


def main():
    """CLI 主入口"""
    parser = argparse.ArgumentParser(description="隔夜收益率因子 IC 计算器")
    parser.add_argument("--force-full", action="store_true", help="强制全量计算")
    parser.add_argument("--min-stocks", type=int, default=DEFAULT_MIN_STOCKS, help="最小股票数")

    args = parser.parse_args()

    # 启动横幅由公共模块 factor_ic_runner 统一打印（含 min_stocks/force_full）
    # 使用 FactorSpec 驱动入口（遵循 factor_cols_literal_constant_design.md §4.1）
    # 注意：factor_cols 必须包含 asset, date 列（groupby 和 shift 依赖）
    # 已确认：公共模块按列名取列（data_loader.py 第205-222行），顺序无关
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
    # 字段名 ic_distribution_consistency 来源于 MODULE.md 第56行输出结构
    # 语义：正比例与方向一致/矛盾判断（MODULE.md 第77行），非单纯分布统计
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
    logger.info("隔夜收益率因子IC计算完成")

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
        logger.error("隔夜收益率因子IC计算失败: %s", e)
        sys.exit(5)  # H12 R19: 因子计算失败 → 检查计算代码
    except Exception:
        # 未预期异常，使用 exception()（自动打印完整堆栈）
        logger.exception("未预期的错误")
        sys.exit(1)
