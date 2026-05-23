#!/usr/bin/env python3
"""
KDJ_J 因子分层回测脚本

使用公共入口 run_layered_backtest，代码量从 ~500 行降至 ~200 行。

规范:
- 遵循 PROJECT.md 公共模块强制复用规范
- 命名遵循 MODULE.md: layered_backtest_<因子名>_<收益周期>.py

作者: 云瑶
创建日期: 2026-05-23
重构日期: 2026-05-23（使用公共入口）
"""

import sys
import pandas as pd
from pathlib import Path
from dataclasses import dataclass, field
from typing import List, Dict as TypingDict

sys.path.insert(0, str(Path(__file__).parent.parent))

from backtest.common.layered_backtest_runner import (
    run_layered_backtest,
    LayerConfigBase
)
from backtest.common.logger_config import get_logger

logger = get_logger(__name__)

DEFAULT_N = 9
DEFAULT_M1 = 3
DEFAULT_M2 = 3


@dataclass
class KDJJLayerConfig(LayerConfigBase):
    """KDJ_J 分层配置"""
    
    layer_thresholds: List[float] = field(default_factory=lambda: [-30, 0, 20, 80, 100, 130])
    
    layer_names: TypingDict[str, str] = field(default_factory=lambda: {
        '1': '超卖层(J<-30)',
        '2': '偏空层(-30≤J<0)',
        '3': '中性层(0≤J<20)',
        '4': '偏多层(20≤J<80)',
        '5': '超买层(J≥80)'
    })
    
    factor_direction: str = 'negative'
    long_layers: List[int] = field(default_factory=lambda: [1, 2])
    short_layers: List[int] = field(default_factory=lambda: [4, 5])
    
    layer_threshold_desc: TypingDict[str, str] = field(default_factory=lambda: {
        '1': 'J < -30 (超卖层)',
        '2': '-30 ≤ J < 0 (偏空层)',
        '3': '0 ≤ J < 20 (中性层)',
        '4': '20 ≤ J < 80 (偏多层)',
        '5': 'J ≥ 80 (超买层)'
    })
    
    kdj_n: int = DEFAULT_N
    kdj_m1: int = DEFAULT_M1
    kdj_m2: int = DEFAULT_M2


def _calc_ewm_with_initial(
    series: pd.Series,
    alpha: float,
    initial_value: float = 50.0
) -> pd.Series:
    """计算 EWM，填充 NaN 为初始值
    
    Args:
        series: 输入序列（可能包含 NaN）
        alpha: EWM alpha 参数（alpha = 1/period，权重衰减半衰期约为 period）
        initial_value: 初始值，默认 50（KDJ 的 K 和 D 初始值）
    
    Returns:
        EWM 计算结果
    """
    filled = series.fillna(initial_value)
    result = filled.ewm(alpha=alpha, adjust=False).mean()
    return result  # type: ignore


def calculate_kdj_j(
    factor_df: pd.DataFrame,
    n: int = DEFAULT_N,
    m1: int = DEFAULT_M1,
    m2: int = DEFAULT_M2
) -> pd.DataFrame:
    """计算 KDJ_J 因子
    
    Args:
        factor_df: 包含 close, high, low 列的 DataFrame
        n: RSV 计算周期，默认 9
        m1: K 值平滑周期，默认 3
        m2: D 值平滑周期，默认 3
    
    Returns:
        包含 kdj_j 列的 DataFrame
    """
    df = factor_df.copy()
    df = df.sort_values(['asset', 'date'])
    
    # 计算 RSV（未成熟随机值）
    df['low_n'] = df.groupby('asset')['low'].transform(
        lambda x: x.rolling(window=n, min_periods=n).min()
    )
    df['high_n'] = df.groupby('asset')['high'].transform(
        lambda x: x.rolling(window=n, min_periods=n).max()
    )
    
    # 使用 Series 方法，避免 np.where 导致 index 丢失（遵循 memory numpy/pandas 规范）
    range_val = df['high_n'] - df['low_n']
    safe_range = range_val.where(range_val > 0, 1.0)  # 避免 division by zero
    df['rsv'] = ((df['close'] - df['low_n']) / safe_range * 100).where(range_val > 0, 50.0)
    
    # 计算 K（alpha = 1/m1，使得权重衰减半衰期约为 m1）
    alpha_k = 1.0 / m1
    df['k'] = df.groupby('asset')['rsv'].transform(
        lambda s: _calc_ewm_with_initial(s, alpha_k)
    )
    
    # 计算 D（alpha = 1/m2，使得权重衰减半衰期约为 m2）
    alpha_d = 1.0 / m2
    df['d'] = df.groupby('asset')['k'].transform(
        lambda s: _calc_ewm_with_initial(s, alpha_d)
    )
    
    # 计算 J
    df['kdj_j'] = 3 * df['k'] - 2 * df['d']
    
    return df


def main():
    import argparse
    parser = argparse.ArgumentParser(description='KDJ_J 分层回测')
    parser.add_argument('--cache_dir', type=str, default=None,
                        help='缓存目录路径')
    parser.add_argument('--output_dir', type=str, default=None)
    parser.add_argument('--quiet', action='store_true')
    parser.add_argument('--kdj-n', type=int, default=DEFAULT_N,
                        help=f'KDJ N 参数，默认 {DEFAULT_N}')
    parser.add_argument('--kdj-m1', type=int, default=DEFAULT_M1,
                        help=f'KDJ M1 参数，默认 {DEFAULT_M1}')
    parser.add_argument('--kdj-m2', type=int, default=DEFAULT_M2,
                        help=f'KDJ M2 参数，默认 {DEFAULT_M2}')
    args = parser.parse_args()
    
    try:
        def factor_calc(df):
            return calculate_kdj_j(df, n=args.kdj_n, m1=args.kdj_m1, m2=args.kdj_m2)
        
        result = run_layered_backtest(
            factor_name='kdj_j',
            factor_col='kdj_j',
            config=KDJJLayerConfig(),
            factor_calculator=factor_calc,
            required_factor_cols=['close', 'high', 'low'],
            cache_dir=args.cache_dir,
            output_dir=args.output_dir,
            verbose=not args.quiet,
            logger=logger
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
        logger.error("数据结构错误: %s", e)
        sys.exit(3)
    except ValueError as e:
        logger.error("参数错误: %s", e)
        sys.exit(4)
    except Exception as e:
        logger.exception("回测执行异常: %s", e)
        sys.exit(5)


if __name__ == '__main__':
    main()