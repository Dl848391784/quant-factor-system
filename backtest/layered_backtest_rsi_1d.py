#!/usr/bin/env python3
"""
RSI 因子分层回测脚本

使用公共入口 run_layered_backtest。

规范:
- 遵循 PROJECT.md 公共模块强制复用规范
- 命名遵循 MODULE.md: layered_backtest_<因子名>_<收益周期>.py

作者: 云瑶
重构日期: 2026-05-23（使用公共入口）
"""

import sys
import pandas as pd
from pathlib import Path
from dataclasses import dataclass, field
from functools import partial
from typing import List, Dict as TypingDict, Any

sys.path.insert(0, str(Path(__file__).parent.parent))

from backtest.common.layered_backtest_runner import (
    run_layered_backtest,
    LayerConfigBase
)
from backtest.common.logger_config import get_logger

logger = get_logger(__name__)

DEFAULT_N = 6
# EPSILON 用于判断 avg_loss 是否接近零（避免 division by zero 或极小值）
# RSI 理论范围 [0, 100]，avg_loss 为价格变动绝对值，量级约价格*0.01~0.05
# 1e-10 作为零值阈值，相对 avg_loss 量级极小（约 1e-8 倍），判断合理
EPSILON = 1e-10


def _calc_delta(series: pd.Series) -> pd.Series:
    """计算价格变化（groupby transform 专用，显式传参避免闭包）
    
    Args:
        series: 单资产的收盘价序列
    
    Returns:
        价格变化序列（第一天为 NaN）
    
    Note:
        - diff() 计算与前一天的差值
        - 第一天无前值，结果为 NaN
    """
    return series.diff()


def _calc_ewm_mean(series: pd.Series, alpha: float) -> pd.Series:
    """计算 Wilder 平滑均值（groupby transform 专用，显式传参避免闭包）
    
    Args:
        series: 单资产的序列（gain 或 loss）
        alpha: EWM 平滑系数，标准 RSI 使用 alpha=1/n
    
    Returns:
        Wilder 平滑均值序列（第一天为 NaN，之后累积计算）
    
    Note:
        - Wilder (1978) 使用 EWM 平滑而非 SMA
        - EWM 累积计算：avg_t = alpha * val_t + (1-alpha) * avg_{t-1}
        - 第一天使用当天的 gain/loss 作为初始值
        - 相比 SMA，EWM 对近期数据更敏感，更符合 RSI 标准
    """
    return series.ewm(alpha=alpha, adjust=False).mean()


@dataclass
class RSILayerConfig(LayerConfigBase):
    """RSI 分层配置"""
    
    layer_thresholds: List[float] = field(default_factory=lambda: [0, 30, 50, 70, 100])
    
    layer_names: TypingDict[str, str] = field(default_factory=lambda: {
        '1': '超卖层(RSI<30)',
        '2': '偏弱层(30≤RSI<50)',
        '3': '偏强层(50≤RSI<70)',
        '4': '超买层(RSI≥70)'
    })
    
    factor_direction: str = 'negative'
    long_layers: List[int] = field(default_factory=lambda: [1, 2])
    short_layers: List[int] = field(default_factory=lambda: [3, 4])
    
    # ========== 策略说明（均值回归）==========
    # RSI 经典均值回归策略：
    # - RSI < 30（超卖）→ 价格可能反弹，做多（Layer1）
    # - RSI > 70（超买）→ 价格可能回落，做空（Layer4）
    # 
    # Layer2/Layer3 扩展说明：
    # - Layer2（30≤RSI<50，偏弱）→ 偏离中性偏弱，可能反弹，做多
    # - Layer3（50≤RSI<70，偏强）→ 偏离中性偏强，可能回落，做空
    # 
    # factor_direction='negative' 意味着：
    # - 低 RSI（超卖/偏弱）→ 做多（long_layers=[1,2]）
    # - 高 RSI（超买/偏强）→ 做空（short_layers=[3,4]）
    # 
    # 注意：这是均值回归策略，而非趋势跟随策略。
    # 趋势跟随策略会在 RSI 50~70（上涨趋势延续）时做多，
    # 但均值回归策略认为偏离中性后可能回归，故做空。
    # 若需趋势跟随策略，请调整 factor_direction='positive'。
    
    # layer_threshold_desc 与 thresholds 对应（4层）
    # 格式遵循 MODULE.md 第451行规范：完整区间 [lower, upper)，必须包含下界
    # 最大边界使用 ≥，说明越界值处理
    #
    # runner 分层逻辑说明（fixed_threshold 模式）：
    # - 低于最小阈值（RSI<0）→ 归入 Layer1（边界处理）
    # - 边界内循环归层：
    #   - Layer1: [0, 30) 区间（0 ≤ RSI < 30）
    #   - Layer2: [30, 50) 区间（30 ≤ RSI < 50）
    #   - Layer3: [50, 70) 区间（50 ≤ RSI < 70）
    #   - Layer4: [70, 100] 区间（最后一层右闭：70 ≤ RSI ≤ 100）
    # - 高于最大阈值（RSI>100）→ 归入 Layer4（边界处理）
    #
    # 关键边界点说明：
    # - RSI=30 → 归入 Layer2（runner 使用 [30,50) 区间，左闭右开）
    # - RSI=70 → 归入 Layer4（runner 最后一层右闭：[70,100]）
    # - 与 layer_names 描述一致，不存在"碰巧正确"问题
    layer_threshold_desc: TypingDict[str, str] = field(default_factory=lambda: {
        '1': 'RSI < 30 (含越界值<0，超卖层，做多)',   # 含越界值 RSI < 0
        '2': '30 ≤ RSI < 50 (偏弱层，做多)',
        '3': '50 ≤ RSI < 70 (偏强层，做空)',
        '4': 'RSI ≥ 70 (含边界70，含越界值>100，超买层，做空)'  # 含越界值 RSI > 100
    })
    
    # 配置元数据：记录默认 RSI 窗口（CLI 可通过 --rsi-n 覆盖）
    rsi_n: int = DEFAULT_N


def calculate_rsi(
    factor_df: pd.DataFrame,
    n: int = DEFAULT_N,
    log_handler: Any = None
) -> pd.DataFrame:
    """计算 RSI 因子
    
    Args:
        factor_df: 包含 close 列的 DataFrame
        n: 滚动窗口期，默认 6
        log_handler: 日志对象（可选，避免遮蔽模块级 logger）
    
    Returns:
        包含 rsi 列的 DataFrame
    
    Note:
        - 前 n 天 RSI 为 NaN（rolling 计算 NaN）
        - RSI = 100 - 100 / (1 + RS)
        - RS = avg_gain / avg_loss
        - RSI 理论范围 [0, 100]，实际数据可能因计算误差越界
        - avg_loss 接近零时，RS → ∞，RSI → 100
    """
    df = factor_df.copy()
    df = df.sort_values(['asset', 'date'])
    
    # 使用独立函数替代 lambda 闭包（遵循 MODULE.md 第789行规范）
    calc_avg = partial(_calc_ewm_mean, alpha=1/n)  # Wilder 平滑：alpha=1/n
    
    # 计算价格变化（直接使用独立函数）
    df['delta'] = df.groupby('asset')['close'].transform(_calc_delta)
    
    # 分离上涨和下跌（使用 Series.where）
    df['gain'] = df['delta'].where(df['delta'] > 0, 0)
    df['loss'] = df['delta'].where(df['delta'] < 0, 0).abs()
    
    # 计算平均上涨和下跌
    df['avg_gain'] = df.groupby('asset')['gain'].transform(calc_avg)
    df['avg_loss'] = df.groupby('asset')['loss'].transform(calc_avg)
    
    # ========== 边界处理：avg_loss 接近零时 ==========
    # avg_loss 接近零时的 RSI 计算（遵循 Wilder 1978 标准）
    # 
    # 边界情况分类：
    # 1. avg_loss > EPSILON 且 avg_gain > 0: 正常计算 RS，RSI ∈ [0, 100]
    # 2. avg_loss > EPSILON 且 avg_gain = 0: RS = 0，RSI = 0（超卖）
    # 3. avg_loss = 0 且 avg_gain > 0: RS → ∞，RSI = 100（超买）
    # 4. avg_loss = 0 且 avg_gain = 0: 无涨无跌，RSI = 50（中性）
    #    - 场景：连续多天价格不变（delta=0）
    #    - gain=0 且 loss=0，导致 avg_gain=0 且 avg_loss=0
    #    - 此时 RSI 应为 50（无涨无跌），而非 100（超买）
    #
    # delta=0 归属说明：
    # - delta=0（价格不变）时，gain=0 且 loss=0
    # - 这是正确的处理：既不是上涨也不是下跌
    # - 但连续多天 delta=0 会累积导致 avg_gain=0 且 avg_loss=0
    
    zero_loss_mask = (df['avg_loss'].notna()) & (df['avg_loss'].abs() < EPSILON)
    zero_gain_mask = (df['avg_gain'].notna()) & (df['avg_gain'].abs() < EPSILON)
    
    # 同时接近零：avg_gain=0 且 avg_loss=0 → RSI=50
    both_zero_mask = zero_loss_mask & zero_gain_mask
    if both_zero_mask.sum() > 0 and log_handler:
        log_handler.info(
            "avg_gain=avg_loss=0 的记录数: %d (%.2f%%)，RSI 设为 50（无涨无跌）",
            both_zero_mask.sum(), both_zero_mask.sum() / len(df) * 100
        )
    
    # 只有 avg_loss 接近零（avg_gain > 0）: RSI=100（超买）
    only_zero_loss_mask = zero_loss_mask & ~zero_gain_mask
    if only_zero_loss_mask.sum() > 0 and log_handler:
        log_handler.warning(
            "avg_loss 接近零但 avg_gain>0 的记录数: %d (%.2f%%)，RSI 设为 100（超买）",
            only_zero_loss_mask.sum(), only_zero_loss_mask.sum() / len(df) * 100
        )
    
    # 计算 RS 和 RSI
    # avg_loss > EPSILON: 正常计算 RS
    # avg_loss <= EPSILON: RS = inf（当 avg_gain > 0）或 0（当 avg_gain = 0）
    df['rs'] = df['avg_gain'] / df['avg_loss'].where(
        df['avg_loss'] > EPSILON,
        EPSILON  # 避免 division by zero，但会被后续 mask 覆盖
    )
    df['rsi'] = 100 - (100 / (1 + df['rs']))
    
    # 边界处理覆盖
    # avg_loss=0 且 avg_gain>0 → RSI=100（超买）
    df.loc[only_zero_loss_mask, 'rsi'] = 100
    # avg_loss=0 且 avg_gain=0 → RSI=50（中性）
    df.loc[both_zero_mask, 'rsi'] = 50
    
    # ========== 因子值统计（正常业务场景记录）==========
    # RSI < 0: 计算误差导致越界，归入 Layer 1（runner 边界处理）
    # RSI > 100: 计算误差导致越界，归入 Layer 4（runner 边界处理）
    below_min_mask = (df['rsi'].notna()) & (df['rsi'] < 0)
    if below_min_mask.sum() > 0 and log_handler:
        log_handler.info(
            "RSI 越界统计: RSI<0 的记录数: %d (%.2f%%)，将归入 Layer1（超卖层）",
            below_min_mask.sum(), below_min_mask.sum() / len(df) * 100
        )
    
    above_max_mask = (df['rsi'].notna()) & (df['rsi'] > 100)
    if above_max_mask.sum() > 0 and log_handler:
        log_handler.info(
            "RSI 越界统计: RSI>100 的记录数: %d (%.2f%%)，将归入 Layer4（超买层）",
            above_max_mask.sum(), above_max_mask.sum() / len(df) * 100
        )
    
    # 因子数据范围校验（遵循 MODULE.md 第505行规范）
    # 全 NaN 防御：检查是否有有效数据
    rsi_values = df['rsi'].dropna()
    if len(rsi_values) == 0:
        if log_handler:
            log_handler.warning("RSI 全部为 NaN，无法计算范围")
        # 全 NaN 时提前返回，避免输出误导性的 "0.00 ~ 0.00" 日志
        return df
    
    rsi_min = rsi_values.min()
    rsi_max = rsi_values.max()
    
    if log_handler:
        log_handler.info("RSI 因子范围: %.2f ~ %.2f", rsi_min, rsi_max)
    
    return df


def main():
    import argparse
    parser = argparse.ArgumentParser(description='RSI 分层回测')
    parser.add_argument('--cache_dir', type=str, default=None,
                        help='缓存目录路径')
    parser.add_argument('--output_dir', type=str, default=None,
                        help='输出目录路径')
    parser.add_argument('--quiet', action='store_true',
                        help='静默模式')
    parser.add_argument('--rsi-n', type=int, default=DEFAULT_N,
                        help=f'RSI 计算窗口，默认 {DEFAULT_N}')
    args = parser.parse_args()
    
    try:
        # 使用 functools.partial 替代闭包，显式传参避免隐式捕获
        # 透传 log_handler 参数（遵循 bollinger_pb 模式）
        factor_calc = partial(
            calculate_rsi,
            n=args.rsi_n,
            log_handler=logger
        )
        
        result = run_layered_backtest(
            factor_name='rsi',
            factor_col='rsi',
            config=RSILayerConfig(),
            factor_calculator=factor_calc,
            required_factor_cols=['close'],
            cache_dir=args.cache_dir,
            output_dir=args.output_dir,
            verbose=not args.quiet,
            logger=logger  # 符合 MODULE.md 第382行规范：参数名统一为 logger
        )
        
        if result['meta']['n_days_total'] == 0:
            logger.error("回测无有效数据，退出码 1")
            sys.exit(1)
        logger.info("回测完成，退出码 0")
        sys.exit(0)
        
    except FileNotFoundError as e:
        logger.error("数据文件不存在: %s", e)
        sys.exit(2)
    except KeyError as e:
        logger.error("数据字段缺失: %s", e)
        sys.exit(3)
    except ValueError as e:
        logger.error("数据值异常: %s", e)
        sys.exit(4)
    except Exception as e:
        logger.exception("回测执行异常: %s", e)
        sys.exit(5)


if __name__ == '__main__':
    main()