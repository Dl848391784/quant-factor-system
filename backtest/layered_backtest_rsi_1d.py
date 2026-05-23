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
import numpy as np
import pandas as pd
from pathlib import Path
from dataclasses import dataclass, field
from typing import List, Dict as TypingDict

sys.path.insert(0, str(Path(__file__).parent.parent))

from backtest.common.layered_backtest_runner import (
    run_layered_backtest,
    LayerConfigBase
)
from factor_ic.common.logger_config import get_logger

logger = get_logger(__name__)

DEFAULT_N = 6


@dataclass
class RSILayerConfig(LayerConfigBase):
    """RSI 分层配置"""
    
    layer_thresholds: List[float] = field(default_factory=lambda: [0, 30, 50, 70, 100])
    
    layer_names: TypingDict[str, str] = field(default_factory=lambda: {
        '1': '超卖层(RSI<30)',
        '2': '偏空层(30≤RSI<50)',
        '3': '偏多层(50≤RSI<70)',
        '4': '超买层(RSI≥70)'
    })
    
    factor_direction: str = 'negative'
    long_layers: List[int] = field(default_factory=lambda: [1, 2])
    short_layers: List[int] = field(default_factory=lambda: [3, 4])
    
    layer_threshold_desc: TypingDict[str, str] = field(default_factory=lambda: {
        '1': 'RSI < 30 (超卖)',
        '2': '30 ≤ RSI < 50 (偏空)',
        '3': '50 ≤ RSI < 70 (偏多)',
        '4': 'RSI ≥ 70 (超买)'
    })
    
    rsi_n: int = DEFAULT_N


def calculate_rsi(
    factor_df: pd.DataFrame,
    n: int = DEFAULT_N
) -> pd.DataFrame:
    """计算 RSI 因子"""
    df = factor_df.copy()
    df = df.sort_values(['asset', 'date'])
    
    # 计算价格变化
    df['delta'] = df.groupby('asset')['close'].transform(lambda x: x.diff())
    
    # 分离上涨和下跌
    df['gain'] = df['delta'].where(df['delta'] > 0, 0)
    df['loss'] = df['delta'].where(df['delta'] < 0, 0).abs()
    
    # 计算平均上涨和下跌
    df['avg_gain'] = df.groupby('asset')['gain'].transform(
        lambda x: x.rolling(window=n, min_periods=n).mean()
    )
    df['avg_loss'] = df.groupby('asset')['loss'].transform(
        lambda x: x.rolling(window=n, min_periods=n).mean()
    )
    
    # 计算 RS 和 RSI
    df['rs'] = df['avg_gain'] / df['avg_loss'].replace(0, np.inf)
    df['rsi'] = 100 - (100 / (1 + df['rs']))
    
    return df


def main():
    import argparse
    parser = argparse.ArgumentParser(description='RSI 分层回测')
    parser.add_argument('--output_dir', type=str, default=None)
    parser.add_argument('--quiet', action='store_true')
    parser.add_argument('--rsi-n', type=int, default=DEFAULT_N)
    args = parser.parse_args()
    
    try:
        def factor_calc(df):
            return calculate_rsi(df, n=args.rsi_n)
        
        result = run_layered_backtest(
            factor_name='rsi',
            factor_col='rsi',
            config=RSILayerConfig(),
            factor_calculator=factor_calc,
            required_factor_cols=['close'],
            output_dir=args.output_dir,
            verbose=not args.quiet,
            _logger=logger
        )
        
        if result['meta']['n_days_total'] == 0:
            logger.error("回测无有效数据，退出码 1")
            sys.exit(1)
        logger.info("回测完成，退出码 0")
        sys.exit(0)
        
    except FileNotFoundError as e:
        logger.error("数据文件不存在: %s", e)
        sys.exit(2)
    except Exception as e:
        logger.exception("回测执行异常: %s", e)
        sys.exit(5)


if __name__ == '__main__':
    main()