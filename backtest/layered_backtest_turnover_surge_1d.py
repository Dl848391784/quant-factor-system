#!/usr/bin/env python3
"""
换手率突增因子分层回测脚本

使用公共入口 run_layered_backtest，代码量从 ~510 行降至 ~180 行。

规范:
- 遵循 PROJECT.md 公共模块强制复用规范
- 命名遵循 MODULE.md: layered_backtest_<因子名>_<收益周期>.py

作者: 云瑶
创建日期: 2026-05-23
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
from factor_ic.common.data_loader import DEFAULT_CACHE_DIR

logger = get_logger(__name__)

DEFAULT_SURGE_WINDOW = 5
EPSILON = 1e-10


@dataclass
class TurnoverSurgeLayerConfig(LayerConfigBase):
    """换手率突增分层配置"""
    
    layer_thresholds: List[float] = field(default_factory=lambda: [0, 0.5, 1.0, 2.0, 5.0, 500.0])
    
    layer_names: TypingDict[str, str] = field(default_factory=lambda: {
        '1': '极低层(surge<0.5)',
        '2': '偏低层(0.5≤surge<1)',
        '3': '正常层(1≤surge<2)',
        '4': '偏高层(2≤surge<5)',
        '5': '突增层(surge≥5)'
    })
    
    factor_direction: str = 'negative'
    long_layers: List[int] = field(default_factory=lambda: [1, 2])
    short_layers: List[int] = field(default_factory=lambda: [4, 5])
    
    layer_threshold_desc: TypingDict[str, str] = field(default_factory=lambda: {
        '1': 'surge < 0.5 (换手率远低于均值)',
        '2': '0.5 ≤ surge < 1 (换手率偏低)',
        '3': '1 ≤ surge < 2 (换手率接近均值)',
        '4': '2 ≤ surge < 5 (换手率偏高)',
        '5': 'surge ≥ 5 (换手率突增)'
    })


def calculate_turnover_surge(
    factor_df: pd.DataFrame,
    surge_window: int = DEFAULT_SURGE_WINDOW
) -> pd.DataFrame:
    """计算换手率突增因子"""
    df = factor_df.copy()
    df = df.sort_values(['asset', 'date'])
    
    avg_turnover = df.groupby('asset')['turnover_rate'].transform(
        lambda x: x.shift(1).rolling(surge_window, min_periods=surge_window).mean()
    )
    
    zero_avg_mask = (avg_turnover.notna()) & (avg_turnover.abs() < EPSILON)
    if zero_avg_mask.sum() > 0:
        logger.warning(
            "avg_turnover 接近零的记录数: %d (%.2f%%)，标记为 NaN",
            zero_avg_mask.sum(), zero_avg_mask.sum() / len(df) * 100
        )
    
    safe_avg = avg_turnover.where(~zero_avg_mask, np.nan)
    df['turnover_surge'] = df['turnover_rate'] / safe_avg
    
    negative_mask = df['turnover_surge'] < 0
    if negative_mask.sum() > 0:
        logger.warning(
            "turnover_surge 负值记录数: %d (%.2f%%)，标记为 NaN",
            negative_mask.sum(), negative_mask.sum() / len(df) * 100
        )
        df.loc[negative_mask, 'turnover_surge'] = np.nan
    
    return df


def main():
    import argparse
    parser = argparse.ArgumentParser(description='换手率突增分层回测')
    parser.add_argument('--output_dir', type=str, default=None)
    parser.add_argument('--quiet', action='store_true')
    parser.add_argument('--surge-window', type=int, default=DEFAULT_SURGE_WINDOW)
    args = parser.parse_args()
    
    try:
        def factor_calc(df):
            return calculate_turnover_surge(df, surge_window=args.surge_window)
        
        result = run_layered_backtest(
            factor_name='turnover_surge',
            factor_col='turnover_surge',
            config=TurnoverSurgeLayerConfig(),
            factor_calculator=factor_calc,
            additional_data_files={'turnover_rate': str(DEFAULT_CACHE_DIR / 'turnover_rate_data.json.gz')},
            required_factor_cols=['turnover_rate', 'close'],
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