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
from typing import List, Dict as TypingDict

sys.path.insert(0, str(Path(__file__).parent.parent))

from backtest.common.layered_backtest_runner import (
    run_layered_backtest,
    LayerConfigBase
)
from backtest.common.logger_config import get_logger

logger = get_logger(__name__)

DEFAULT_N = 20


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
    
    layer_threshold_desc: TypingDict[str, str] = field(default_factory=lambda: {
        '1': 'PB < 0.5 (价格低于下轨)',
        '2': '0.5 ≤ PB < 0.8 (接近下轨，偏弱)',
        '3': '0.8 ≤ PB < 1.0 (中轨偏下)',
        '4': '1.0 ≤ PB < 1.2 (中轨偏上，偏强)',
        '5': 'PB ≥ 1.2 (接近或高于上轨)'
    })
    
    bollinger_n: int = DEFAULT_N


def calculate_bollinger_pb(
    factor_df: pd.DataFrame,
    n: int = DEFAULT_N
) -> pd.DataFrame:
    """计算 BOLLINGER_PB 因子"""
    df = factor_df.copy()
    df = df.sort_values(['asset', 'date'])
    
    # 计算均线和标准差
    df['ma_n'] = df.groupby('asset')['close'].transform(
        lambda x: x.rolling(window=n, min_periods=n).mean()
    )
    df['std_n'] = df.groupby('asset')['close'].transform(
        lambda x: x.rolling(window=n, min_periods=n).std()
    )
    
    # 计算布林带上下轨
    df['upper'] = df['ma_n'] + 2 * df['std_n']
    df['lower'] = df['ma_n'] - 2 * df['std_n']
    
    # 计算 %B (Position in Band)
    # %B = (Close - Lower) / (Upper - Lower)
    band_width = df['upper'] - df['lower']
    
    # 使用 Series.where 替代 np.where（避免 ndarray 丢失 index）
    df['bollinger_pb'] = ((df['close'] - df['lower']) / band_width).where(
        band_width > 0,
        0.5  # 带宽为0时的默认值（价格在中轨）
    )
    
    # 因子数据范围校验（遵循 MODULE.md 第505行规范）
    pb_min = df['bollinger_pb'].min()
    pb_max = df['bollinger_pb'].max()
    logger.info("bollinger_pb 因子范围: %.2f ~ %.2f", pb_min, pb_max)
    
    return df


def main():
    import argparse
    parser = argparse.ArgumentParser(description='BOLLINGER_PB 分层回测')
    parser.add_argument('--cache_dir', type=str, default=None,
                        help='缓存目录路径')
    parser.add_argument('--output_dir', type=str, default=None)
    parser.add_argument('--quiet', action='store_true')
    parser.add_argument('--bollinger-n', type=int, default=DEFAULT_N)
    args = parser.parse_args()
    
    try:
        # 使用 functools.partial 替代闭包，显式传参避免隐式捕获
        factor_calc = partial(calculate_bollinger_pb, n=args.bollinger_n)
        
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