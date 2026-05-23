#!/usr/bin/env python3
"""
BOLLINGER_PB 因子分层回测脚本

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

DEFAULT_N = 20
# EPSILON 用于判断 band_width 是否接近零（避免 division by zero 或极小值）
# %B 典型范围 0.0 ~ 2.0，band_width 为价格标准差*2，量级约价格*0.02~0.1
# 1e-10 作为零值阈值，相对 band_width 量级极小（约 1e-8 倍），判断合理
EPSILON = 1e-10


def _calc_rolling(series: pd.Series, window: int, method: str = 'mean') -> pd.Series:
    """计算滚动统计量（groupby transform 专用，显式传参避免闭包）
    
    Args:
        series: 单资产的收盘价序列
        window: 滚动窗口期
        method: 统计方法，'mean' 或 'std'
    
    Returns:
        滚动统计量序列（前 window-1 天为 NaN）
    
    Note:
        - min_periods=window 确保只有足够历史数据时才计算
        - 前 window-1 天为 NaN，无法计算有效统计量
        - 例如 window=20，需要至少 20 天数据才能产生第一个有效结果
        - std 默认使用样本标准差（ddof=1，除以 n-1），布林带标准定义使用总体标准差（ddof=0）
        - 对于 window=20，两者差异约 sqrt(20/19) ≈ 2.6%，不影响分层方向
    """
    rolling_obj = series.rolling(window=window, min_periods=window)
    if method == 'mean':
        return rolling_obj.mean()
    elif method == 'std':
        return rolling_obj.std()  # 默认 ddof=1（样本标准差）
    else:
        raise ValueError(f"method 必须是 'mean' 或 'std', 当前值: '{method}'")


@dataclass
class BollingerPBLayerConfig(LayerConfigBase):
    """BOLLINGER_PB 分层配置"""
    
    layer_thresholds: List[float] = field(default_factory=lambda: [0, 0.5, 0.8, 1.0, 1.2, 2.0])
    
    layer_names: TypingDict[str, str] = field(default_factory=lambda: {
        '1': '超卖层(PB<0.5)',
        '2': '偏弱层(0.5≤PB<0.8)',
        '3': '中性层(0.8≤PB<1.0)',
        '4': '偏强层(1.0≤PB<1.2)',
        '5': '超买层(PB≥1.2)'
    })
    
    factor_direction: str = 'negative'
    long_layers: List[int] = field(default_factory=lambda: [1, 2])
    short_layers: List[int] = field(default_factory=lambda: [4, 5])
    
    # layer_threshold_desc 与 thresholds 对应（5层）
    # 格式遵循 MODULE.md 第451行规范：完整区间 [lower, upper)，必须包含下界
    # 最大边界使用 ≥，说明越界值处理
    layer_threshold_desc: TypingDict[str, str] = field(default_factory=lambda: {
        '1': 'PB < 0.5 (含越界值<0，价格远低于下轨，超卖层，做多)',   # 含越界值 PB < 0
        '2': '0.5 ≤ PB < 0.8 (接近下轨，偏弱层，做多)',
        '3': '0.8 ≤ PB < 1.0 (中轨偏下，中性层，不参与多空)',
        '4': '1.0 ≤ PB < 1.2 (中轨偏上，偏强层，做空)',
        '5': 'PB ≥ 1.2 (含边界1.2，含越界值>2，价格远高于上轨，超买层，做空)'  # 含越界值 PB > 2
    })
    
    # 配置元数据：记录默认布林带窗口（CLI 可通过 --bollinger-n 覆盖）
    bollinger_n: int = DEFAULT_N


def calculate_bollinger_pb(
    factor_df: pd.DataFrame,
    n: int = DEFAULT_N,
    log_handler: Any = None
) -> pd.DataFrame:
    """计算 BOLLINGER_PB 因子
    
    Args:
        factor_df: 包含 close 列的 DataFrame
        n: 滚动窗口期，默认 20
        log_handler: 日志对象（可选，避免遮蔽模块级 logger）
    
    Returns:
        包含 bollinger_pb 列的 DataFrame
    
    Note:
        - 前 n-1 天 bollinger_pb 为 NaN（rolling 计算 NaN）
        - %B = (Close - Lower) / (Upper - Lower)
        - %B < 0: 价格低于下轨
        - %B = 0.5: 价格在中轨
        - %B > 1: 价格高于上轨
    """
    df = factor_df.copy()
    df = df.sort_values(['asset', 'date'])
    
    # 使用独立函数替代 lambda 闭包（遵循 MODULE.md 第789行规范）
    calc_mean = partial(_calc_rolling, window=n, method='mean')
    calc_std = partial(_calc_rolling, window=n, method='std')
    
    # 计算均线和标准差
    df['ma_n'] = df.groupby('asset')['close'].transform(calc_mean)
    df['std_n'] = df.groupby('asset')['close'].transform(calc_std)
    
    # 计算布林带上下轨
    df['upper'] = df['ma_n'] + 2 * df['std_n']
    df['lower'] = df['ma_n'] - 2 * df['std_n']
    
    # 计算 %B (Position in Band)
    # %B = (Close - Lower) / (Upper - Lower)
    band_width = df['upper'] - df['lower']
    
    # 边界处理：band_width 接近零时使用默认值 0.5（价格在中轨）
    # 使用 EPSILON 判断避免浮点精度问题（如 1e-15 导致 %B 极端值）
    zero_band_mask = (band_width.notna()) & (band_width.abs() < EPSILON)
    if zero_band_mask.sum() > 0 and log_handler:
        log_handler.warning(
            "band_width 接近零的记录数: %d (%.2f%%)，使用默认值 0.5",
            zero_band_mask.sum(), zero_band_mask.sum() / len(df) * 100
        )
    
    # 使用 Series.where 替代 np.where（避免 ndarray 丢失 index）
    # band_width > EPSILON: 正常计算 %B
    # band_width <= EPSILON: 使用默认值 0.5（价格在中轨）
    df['bollinger_pb'] = ((df['close'] - df['lower']) / band_width).where(
        band_width > EPSILON,
        0.5  # 带宽接近零时的默认值（价格在中轨）
    )
    
    # ========== 因子值统计（正常业务场景记录）==========
    # %B < 0: 价格低于下轨（超卖），归入 Layer 1（runner 边界处理）
    # %B > 2: 价格远高于上轨（超买），归入 Layer 5（runner 边界处理）
    # 这些是正常业务场景，不需要过滤，但记录统计信息供分析
    negative_mask = (df['bollinger_pb'].notna()) & (df['bollinger_pb'] < 0)
    if negative_mask.sum() > 0 and log_handler:
        log_handler.info(
            "bollinger_pb 越界统计: %B<0 的记录数: %d (%.2f%%)，将归入 Layer1（超卖层）",
            negative_mask.sum(), negative_mask.sum() / len(df) * 100
        )
    
    above_max_mask = (df['bollinger_pb'].notna()) & (df['bollinger_pb'] > 2)
    if above_max_mask.sum() > 0 and log_handler:
        log_handler.info(
            "bollinger_pb 越界统计: %B>2 的记录数: %d (%.2f%%)，将归入 Layer5（超买层）",
            above_max_mask.sum(), above_max_mask.sum() / len(df) * 100
        )
    
    # 因子数据范围校验（遵循 MODULE.md 第505行规范）
    # 全 NaN 防御：检查是否有有效数据
    pb_values = df['bollinger_pb'].dropna()
    if len(pb_values) == 0:
        if log_handler:
            log_handler.warning("bollinger_pb 全部为 NaN，无法计算范围")
        # 全 NaN 时提前返回，避免输出误导性的 "0.00 ~ 0.00" 日志
        return df
    
    pb_min = pb_values.min()
    pb_max = pb_values.max()
    
    if log_handler:
        log_handler.info("bollinger_pb 因子范围: %.2f ~ %.2f", pb_min, pb_max)
    
    return df


def main():
    import argparse
    parser = argparse.ArgumentParser(description='BOLLINGER_PB 分层回测')
    parser.add_argument('--cache_dir', type=str, default=None,
                        help='缓存目录路径')
    parser.add_argument('--output_dir', type=str, default=None,
                        help='输出目录路径')
    parser.add_argument('--quiet', action='store_true',
                        help='静默模式')
    parser.add_argument('--bollinger-n', type=int, default=DEFAULT_N,
                        help=f'布林带计算窗口，默认 {DEFAULT_N}')
    args = parser.parse_args()
    
    try:
        # 使用 functools.partial 替代闭包，显式传参避免隐式捕获
        # 透传 log_handler 参数（遵循 turnover_surge 模式）
        factor_calc = partial(
            calculate_bollinger_pb,
            n=args.bollinger_n,
            log_handler=logger
        )
        
        result = run_layered_backtest(
            factor_name='bollinger_pb',
            factor_col='bollinger_pb',
            config=BollingerPBLayerConfig(),
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