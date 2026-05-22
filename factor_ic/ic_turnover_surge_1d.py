#!/usr/bin/env python3
"""
换手率突增因子 IC 计算器（重构版） - 1日收益周期

遵循 PROJECT.md 公共模块强制复用规范：
- 主流程使用 run_complex_factor_ic()（禁止手写三模式分支）
- 数据加载使用 load_factor_return_data(additional_factor_files)（禁止手写 gzip/json 加载）
- 仅实现因子特有计算逻辑（换手率突增公式）

代码量：~100行（仅换手率计算），而非 ~300行手写主流程。

因子定义：
- 换手率突增 = 当日换手率 / 过去5日换手率均值

筛选条件：
- 换手率突增 > 1（当日换手率高于近期均值）
- 当日涨跌幅 > 0（上涨）
- 不满足条件的股票因子值设为 NaN

作者: 云瑶
重构日期: 2026-05-21
修订日期: 2026-05-23（中间变量规范 + 除零防护 + 异常检测顺序修正）
原版作者: 云舟
原版日期: 2026-05-08
"""

import sys
from pathlib import Path

# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent.parent))

import pandas as pd
import numpy as np

# 导入公共模块主入口（遵循 PROJECT.md 强制复用规范）
from factor_ic.common.factor_ic_runner import run_complex_factor_ic
from factor_ic.common.data_loader import DEFAULT_CACHE_DIR
from factor_ic.common.logger_config import get_logger

logger = get_logger(__name__)

# ============================================================================
# 参数统一管理
# ============================================================================
DEFAULT_MIN_STOCKS = 10
DEFAULT_SURGE_WINDOW = 5  # 换手率均值计算窗口

# 模块级常量（避免除零阈值）
EPSILON = 1e-10


# ============================================================================
# 换手率突增计算函数（因子特有逻辑）
# ============================================================================

def calculate_turnover_surge(
    factor_df: pd.DataFrame,
    surge_window: int = DEFAULT_SURGE_WINDOW
) -> pd.DataFrame:
    """
    计算换手率突增因子（因子特有逻辑）
    
    参数:
        factor_df: 包含 turnover_rate, close 列的 DataFrame【必需】
        surge_window: 换手率均值计算窗口
    
    返回:
        添加了 turnover_surge 列的 DataFrame
    
    规范:
        - 函数入口必须先 .copy()，避免修改原始数据（MODULE.md DataFrame参数副本规范）
        - 使用局部变量存储中间结果，避免污染输出 DataFrame（中间变量规范）
        - 异常检测而非静默修正（MODULE.md 异常检测规范）
        - 异常检测顺序：先检测数据质量异常，再应用业务筛选条件
    
    流程:
        1. 计算换手率均值（局部变量）
        2. 计算换手率突增（除零防护）
        3. 检测异常负值（数据质量问题）
        4. 计算涨跌幅（局部变量）
        5. 应用业务筛选条件（surge > 1, return > 0）
        6. 写入最终因子列
    """
    # 函数入口必须先 copy，避免副作用
    factor_df = factor_df.copy()
    
    # ========== Step 1: 计算换手率均值（局部变量）==========
    # avg_turnover: 过去 surge_window 日换手率均值（不含当日）
    # 因子定义：换手率突增 = 当日换手率 / 过去几日换手率均值
    # "过去几日"不含当日，否则当日换手率同时出现在分子和分母，因子值被稀释
    #
    # 数据量要求：shift(1) 后再做 rolling(surge_window, min_periods=surge_window)
    # 需要至少 surge_window + 1 天的历史数据才能得到第一个有效均值
    # 例如：surge_window=5 时，需要第6个交易日才能得到第一个有效 avg_turnover
    avg_turnover = factor_df.groupby('asset')['turnover_rate'].transform(
        lambda x: x.shift(1).rolling(surge_window, min_periods=surge_window).mean()
    )
    
    # ========== Step 2: 检测 avg_turnover 异常值（先检测再处理）==========
    # avg_turnover = 0 表示过去 surge_window 天完全无交易（合法但无意义）
    # avg_turnover 接近零会导致 turnover_surge 爆炸式放大，需检测并标记为 NaN
    # 注意：不能使用 clip 静默修正，因为 turnover_rate=0 是合法值
    # 遵循 MODULE.md 异常检测规范：先检测异常，再应用业务逻辑
    zero_avg_mask = (avg_turnover.notna()) & (avg_turnover.abs() < EPSILON)
    zero_avg_count = zero_avg_mask.sum()
    if zero_avg_count > 0:
        logger.warning(f"检测到 {zero_avg_count} 个 avg_turnover 接近零，已标记为 np.nan")
    
    # 标记异常位置为 NaN，而非 clip 静默修正
    safe_avg_turnover = avg_turnover.where(~zero_avg_mask, np.nan)
    turnover_surge = factor_df['turnover_rate'] / safe_avg_turnover
    
    # ========== Step 3: 异常检测（先于筛选条件）==========
    # turnover_surge 理论上恒 >= 0（turnover_rate >= 0, avg_turnover >= 0）
    # 若出现负值，说明数据异常，需检测并记录
    # 注意：必须在筛选条件之前检测，否则 surge > 1 会排除 surge < 0 的情况
    abnormal_mask = turnover_surge < 0
    abnormal_count = abnormal_mask.sum()
    if abnormal_count > 0:
        logger.warning(f"检测到 {abnormal_count} 个异常换手率突增（负值），已标记为 np.nan")
        turnover_surge = turnover_surge.where(~abnormal_mask, np.nan)
    
    # ========== Step 4: 计算涨跌幅（局部变量）==========
    # 获取前一日收盘价
    prev_close = factor_df.groupby('asset')['close'].transform(
        lambda x: x.shift(1)
    )
    
    # 异常检测：prev_close <= EPSILON（股价不应为零或负值）
    # 区分两种情况：
    # 1. prev_close = NaN：首个交易日无前一日数据（正常缺失，不参与计算）
    # 2. prev_close <= EPSILON：数据异常（股价不应为零），需检测并记录
    abnormal_prev_close_mask = (prev_close.notna()) & (prev_close <= EPSILON)
    abnormal_prev_close_count = abnormal_prev_close_mask.sum()
    if abnormal_prev_close_count > 0:
        logger.warning(f"检测到 {abnormal_prev_close_count} 个异常前收盘价（≤ {EPSILON}），已标记为 np.nan")
    
    # 计算涨跌幅：仅对有效数据（notna 且 > EPSILON）计算，其余保持 NaN
    # 使用 mask 排除异常，而非 clip 静默修正（遵循 MODULE.md 异常排除时机规范）
    safe_prev_close = prev_close.mask(prev_close.isna() | (prev_close <= EPSILON))
    # 分子分母统一使用 safe_prev_close，语义更清晰
    daily_return = (factor_df['close'] - safe_prev_close) / safe_prev_close
    
    # ========== Step 5: 应用业务筛选条件 ==========
    # 条件1: turnover_surge > 1（换手率高于近期均值）
    # 条件2: daily_return > 0（当日上涨）
    # 注意：异常负值已在 Step 3 处理，此处筛选不影响异常检测
    condition = (
        (turnover_surge > 1) &
        (daily_return > 0)
    )
    
    # 不满足条件的股票因子值设为 NaN
    turnover_surge = turnover_surge.where(condition, np.nan)
    
    # ========== Step 6: 写入最终因子列 ==========
    # 只写入 turnover_surge，中间变量（avg_turnover, daily_return）不保留
    factor_df['turnover_surge'] = turnover_surge
    
    return factor_df


# ============================================================================
# CLI 入口
# ============================================================================

def main():
    """CLI 主入口"""
    import argparse
    
    parser = argparse.ArgumentParser(description='换手率突增 IC 计算器')
    parser.add_argument('--force-full', action='store_true', help='强制全量计算')
    parser.add_argument('--surge-window', type=int, default=DEFAULT_SURGE_WINDOW, help='换手率均值计算窗口')
    parser.add_argument('--min-stocks', type=int, default=DEFAULT_MIN_STOCKS, help='最小股票数')
    
    args = parser.parse_args()
    
    # 使用公共模块主入口（遵循 PROJECT.md 强制复用规范）
    result = run_complex_factor_ic(
        factor_name='turnover_surge',
        factor_col='turnover_surge',
        factor_cols=['close'],  # turnover_rate 通过 additional_factor_files 加载
        custom_factor_calculation=calculate_turnover_surge,
        custom_factor_calculation_params={'surge_window': args.surge_window},
        additional_factor_files={
            'turnover_rate': DEFAULT_CACHE_DIR / 'turnover_rate_data.json.gz'
        },
        min_stocks=args.min_stocks,
        force_full=args.force_full,
        _logger=logger
    )
    
    # 使用 .get() 防御性访问结果
    ic_metrics = result.get('ic_metrics', {})
    logger.info("=" * 60)
    logger.info("结果摘要:")
    logger.info(f"因子名称: {result.get('factor_name', 'unknown')}")
    logger.info(f"更新模式: {result.get('update_mode', 'unknown')}")
    logger.info(f"IC 均值: {ic_metrics.get('ic_mean', 0):.4f}")
    logger.info(f"ICIR: {ic_metrics.get('icir', 0):.2f}")
    logger.info("=" * 60)
    
    return result


if __name__ == '__main__':
    try:
        main()
    except RuntimeError:
        logger.exception("计算失败")  # 使用 .exception() 保留完整堆栈
        sys.exit(1)
    except Exception:
        logger.exception("未预期的错误")  # 使用 .exception() 保留完整堆栈
        sys.exit(1)