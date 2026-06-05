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
from pathlib import Path

import numpy as np
import pandas as pd


# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent.parent))

# 导入公共模块主入口（遵循 PROJECT.md 强制复用规范）
from factor_ic.common.factor_ic_runner import run_complex_factor_ic
from factor_ic.common.logger_config import get_logger


logger = get_logger(__name__)

# ============================================================================
# 参数统一管理
# ============================================================================
DEFAULT_MIN_STOCKS = 10


# ============================================================================
# 因子计算函数
# ============================================================================

def calculate_intraday_intensity(
    factor_df: pd.DataFrame,
    logger_arg: logging.Logger | None = None,
    skip_validation: bool = False
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
        >>> df = pd.DataFrame({
        ...     'date': ['2026-01-01'],
        ...     'asset': ['000001'],
        ...     'open': [10.0],
        ...     'close': [10.5],
        ...     'high': [11.0],
        ...     'low': [9.5]
        ... })
        >>> result = calculate_intraday_intensity(df, skip_validation=True)
        >>> result['intraday_intensity'].iloc[0]
        0.25
    """
    # logger 参数命名遵循 MODULE.md 约束 77（避免遮蔽模块级 logger）
    _logger = logger_arg or logger

    # 1. 数据校验（遵循 MODULE.md v3.16 新因子数据校验规范）
    required_cols = ['open', 'close', 'high', 'low']
    missing_cols = [col for col in required_cols if col not in factor_df.columns]
    if missing_cols:
        raise ValueError(
            f"数据校验失败：缺失必需列 {missing_cols}\n"
            f"实际列: {list(factor_df.columns)}\n"
            f"请检查数据源是否包含所需列"
        )

    # 2. DataFrame 参数先 copy()（遵循 MODULE.md 约束 4）
    factor_df = factor_df.copy()

    # 3. 有效数据量校验（可通过 skip_validation 跳过）
    if not skip_validation:
        valid_rows = factor_df[required_cols].dropna().shape[0]
        if valid_rows < 100:
            raise ValueError(
                f"数据校验失败：有效数据量不足\n"
                f"期望 ≥ 100 行，实际 {valid_rows} 行\n"
                f"请检查数据源质量"
            )
        _logger.info(f"开始计算日内强度因子，有效数据行数: {valid_rows}")
    else:
        valid_rows = factor_df[required_cols].dropna().shape[0]

    # 4. 计算振幅（分母）
    amplitude = factor_df['high'] - factor_df['low']

    # 5. 计算日内强度
    intraday_intensity = (factor_df['close'] - factor_df['open']) / amplitude

    # 6. 除零保护：振幅为 0 时设为 NaN
    zero_amplitude_mask = amplitude == 0
    zero_amplitude_count = int(zero_amplitude_mask.sum())  # type: ignore[union-attr]
    if zero_amplitude_count > 0:
        _logger.warning(
            f"发现 {zero_amplitude_count} 条振幅为零的记录（High=Low），"
            f"已设为 NaN"
        )

    intraday_intensity = intraday_intensity.where(amplitude > 0, np.nan)

    # 7. 添加因子列
    factor_df['intraday_intensity'] = intraday_intensity

    # 8. 统计计算结果
    valid_factor_count = factor_df['intraday_intensity'].notna().sum()
    _logger.info(
        f"日内强度因子计算完成，"
        f"有效因子值 {valid_factor_count} 条"
    )

    return factor_df


# ============================================================================
# CLI 入口
# ============================================================================

def main():
    """CLI 主入口"""
    parser = argparse.ArgumentParser(description='日内价格强度因子 IC 计算器')
    parser.add_argument('--force-full', action='store_true', help='强制全量计算')
    parser.add_argument('--min-stocks', type=int, default=DEFAULT_MIN_STOCKS, help='最小股票数')

    args = parser.parse_args()

    # 使用公共模块主入口（遵循 PROJECT.md 强制复用规范）
    # 注意：run_complex_factor_ic 需要 factor_cols 和 custom_factor_calculation
    result = run_complex_factor_ic(
        factor_name='intraday_intensity',
        factor_col='intraday_intensity',
        factor_cols=['open', 'close', 'high', 'low'],
        custom_factor_calculation=calculate_intraday_intensity,
        min_stocks=args.min_stocks,
        force_full=args.force_full,
        _logger=logger
    )

    # 保底处理：公共模块异常返回 None 时直接退出
    if result is None:
        logger.error("run_complex_factor_ic 返回 None")
        sys.exit(1)

    # 使用 .get() + or {} 防御性访问结果
    ic_metrics = result.get('ic_metrics') or {}
    sample_stats = result.get('sample_stats') or {}
    period = result.get('period') or {}
    ic_distribution = result.get('ic_distribution_consistency') or {}

    logger.info("=" * 60)
    logger.info("结果摘要")
    logger.info("=" * 60)
    logger.info(f"因子名称: {result.get('factor_name', 'unknown')}")
    logger.info(f"更新模式: {result.get('update_mode', 'unknown')}")
    logger.info(f"日期范围: {period.get('start', 'N/A')} ~ {period.get('end', 'N/A')}")
    logger.info(f"有效天数: {sample_stats.get('valid_days', 0)} 天")
    logger.info("--- IC指标 ---")

    ic_mean = ic_metrics.get('ic_mean')
    if ic_mean is not None:
        logger.info(f"IC 均值: {ic_mean:.4f}")
    else:
        logger.info("IC 均值: N/A（本次计算结果为空，请检查数据源）")

    ic_std = ic_metrics.get('ic_std')
    if ic_std is not None:
        logger.info(f"IC 标准差: {ic_std:.4f}")
    else:
        logger.info("IC 标准差: N/A（数据不足或全为相同值）")

    icir = ic_metrics.get('icir')
    if icir is not None:
        logger.info(f"ICIR: {icir:.2f}")
    else:
        logger.info("ICIR: N/A（IC 标准差为 0 或数据不足）")

    positive_ratio = ic_distribution.get('positive_ratio')
    if positive_ratio is not None:
        logger.info(f"IC>0 占比: {positive_ratio:.2%}")
    else:
        logger.info("IC>0 占比: N/A（字段名错误或数据缺失）")

    # 异常状态整体感知日志
    has_warning = False
    if ic_mean is None:
        logger.warning("本次IC计算结果为空，请检查数据源或参数配置")
        has_warning = True
    elif ic_std is None:
        logger.warning("IC标准差无法计算（数据不足或全为相同值），请检查因子数据分布")
        has_warning = True
    elif icir is None:
        logger.warning("ICIR无法计算（IC标准差为0或数据不足），请检查因子数据分布")
        has_warning = True

    if positive_ratio is None:
        logger.warning("IC>0占比无法获取（字段名错误或数据缺失），请检查公共模块输出结构")
        has_warning = True

    if has_warning:
        logger.info("日内强度因子IC计算完成（存在异常，请关注上方警告）")
    else:
        logger.info("日内强度因子IC计算完成")

    return result


if __name__ == '__main__':
    try:
        main()
    except Exception:
        # 未预期异常，使用 exception()（自动打印完整堆栈）
        logger.exception("未预期的错误")
        sys.exit(1)
