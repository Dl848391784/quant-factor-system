#!/usr/bin/env python3
"""
隔夜收益率因子 IC 计算器 - 1日收益周期

使用公共模块主入口 run_complex_factor_ic，代码量约 60 行。

功能：
1. 从缓存数据计算隔夜收益率因子的 IC
2. 隔夜收益率定义：overnight_ret = (今日开盘价 - 昨日收盘价) / 昨日收盘价
3. 支持全量计算、增量更新和跳过三种模式
4. 五维度独立判断（统计显著性、因子方向、经济显著性、ICIR稳定性、IC分布一致性）

实现方式：
- 使用 run_complex_factor_ic() 公共模块主入口
- 自定义因子计算函数 calculate_overnight_return

遵循 PROJECT.md 公共模块强制复用规范：
- 主流程使用 run_complex_factor_ic()（禁止手写三模式分支）
- 仅实现因子特有计算逻辑

作者: 云瑶
创建日期: 2026-05-28
"""

import sys
from pathlib import Path

# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent.parent))

import pandas as pd
import numpy as np

# 导入公共模块主入口（遵循 PROJECT.md 强制复用规范）
from factor_ic.common.factor_ic_runner import run_complex_factor_ic
from factor_ic.common.logger_config import get_logger

logger = get_logger(__name__)

# ============================================================================
# 参数统一管理
# ============================================================================
DEFAULT_MIN_STOCKS = 10
EPSILON = 1e-10  # 避免除零阈值


# ============================================================================
# 因子计算函数
# ============================================================================

def calculate_overnight_return(factor_df, logger_arg=None):
    """
    计算隔夜收益率因子
    
    公式: overnight_ret = (今日开盘价 - 昨日收盘价) / 昨日收盘价
    
    Args:
        factor_df: 包含 open, close 列的 DataFrame
            - 必须包含 'asset', 'date', 'open', 'close' 列
        logger_arg: 日志记录器（由调用方传入）
    
    Returns:
        DataFrame，新增 'overnight_ret' 列
        
    Note:
        - 遵循 MODULE.md 约束 #4：函数入口先 copy()
        - 第一天数据为 NaN（无昨日收盘价）
        - 除零防护：prev_close < EPSILON 时设为 NaN
        - 按资产分组计算（每只股票独立）
        
    Example:
        >>> # 正常调用
        >>> result = run_complex_factor_ic(
        >>>     factor_name='overnight_ret',
        >>>     factor_col='overnight_ret',
        >>>     factor_cols=['open', 'close'],
        >>>     custom_factor_calculation=calculate_overnight_return
        >>> )
        >>> 
        >>> # 独立调用（用于测试）
        >>> factor_df = pd.DataFrame({
        >>>     'asset': ['A', 'A', 'B', 'B'],
        >>>     'date': ['2026-05-01', '2026-05-02', '2026-05-01', '2026-05-02'],
        >>>     'open': [10.0, 10.5, 20.0, 21.0],
        >>>     'close': [10.2, 10.8, 20.5, 21.5]
        >>> })
        >>> result_df = calculate_overnight_return(factor_df)
        >>> print(result_df['overnight_ret'])
        >>> # asset A: NaN, 0.0294 (第一天NaN，第二天=(10.5-10.2)/10.2)
        >>> # asset B: NaN, 0.0244 (第一天NaN，第二天=(21.0-20.5)/20.5)
    """
    # 遵循 MODULE.md 约束 #4：函数入口先 copy()
    factor_df = factor_df.copy()
    
    # 获取 logger（遵循 PROJECT.md 公共模块日志规范）
    logger = logger_arg if logger_arg is not None else get_logger('factor_ic.ic_overnight_ret_1d')
    
    # 按资产分组计算（每只股票独立）
    # 计算公式：overnight_ret = (open - close.shift(1)) / close.shift(1)
    prev_close = factor_df.groupby('asset')['close'].shift(1)
    
    # 计算隔夜收益率
    factor_df['overnight_ret'] = (factor_df['open'] - prev_close) / prev_close
    
    # 除零防护：prev_close 极小或为 0 时设为 NaN
    abnormal_mask = prev_close < EPSILON
    if abnormal_mask.any():
        abnormal_count = abnormal_mask.sum()
        logger.warning(
            f"发现 {abnormal_count} 个异常收盘价（< {EPSILON}），"
            f"隔夜收益率已设为 NaN"
        )
        factor_df.loc[abnormal_mask, 'overnight_ret'] = np.nan
    
    # 统计计算结果
    valid_count = factor_df['overnight_ret'].notna().sum()
    total_count = len(factor_df)
    logger.info(
        f"隔夜收益率计算完成\n"
        f"有效值: {valid_count} / {total_count} ({valid_count/total_count:.2%})"
    )
    
    return factor_df


# ============================================================================
# CLI 入口
# ============================================================================

def main():
    """CLI 主入口"""
    import argparse
    
    parser = argparse.ArgumentParser(description='隔夜收益率因子 IC 计算器')
    parser.add_argument('--force-full', action='store_true', help='强制全量计算')
    parser.add_argument('--min-stocks', type=int, default=DEFAULT_MIN_STOCKS, help='最小股票数')
    
    args = parser.parse_args()
    
    # 启动节点日志
    logger.info(
        f"隔夜收益率因子 IC 计算启动 "
        f"[min_stocks={args.min_stocks}, force_full={args.force_full}]"
    )
    
    # 使用公共模块主入口（遵循 PROJECT.md 强制复用规范）
    result = run_complex_factor_ic(
        factor_name='overnight_ret',
        factor_col='overnight_ret',
        factor_cols=['open', 'close'],
        custom_factor_calculation=calculate_overnight_return,
        min_stocks=args.min_stocks,
        force_full=args.force_full,
        _logger=logger
    )
    
    # 使用 .get() 防御性访问结果
    ic_metrics = result.get('ic_metrics', {})
    sample_stats = result.get('sample_stats', {})
    period = result.get('period', {})
    
    logger.info("=" * 60)
    logger.info("结果摘要")
    logger.info("=" * 60)
    logger.info(f"因子名称: {result.get('factor_name', 'unknown')}")
    logger.info(f"更新模式: {result.get('update_mode', 'unknown')}")
    logger.info(f"日期范围: {period.get('start', 'N/A')} ~ {period.get('end', 'N/A')}")
    logger.info(f"有效天数: {sample_stats.get('valid_days', 0)} 天")
    logger.info(f"IC 均值: {ic_metrics.get('ic_mean', 0):.4f}")
    logger.info(f"IC 标准差: {ic_metrics.get('ic_std', 0):.4f}")
    logger.info(f"ICIR: {ic_metrics.get('icir', 0):.2f}")
    logger.info(f"IC>0 占比: {result.get('positive_ratio', 0):.2%}")
    
    return result


if __name__ == '__main__':
    try:
        main()
    except RuntimeError:
        logger.exception("隔夜收益率因子 IC 计算失败")
        sys.exit(1)
    except Exception:
        logger.exception("隔夜收益率因子 IC 计算失败（未预期错误）")
        sys.exit(1)