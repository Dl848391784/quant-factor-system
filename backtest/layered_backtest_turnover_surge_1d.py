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
import pandas as pd
from pathlib import Path
from dataclasses import dataclass, field
from typing import List, Dict as TypingDict, Any

sys.path.insert(0, str(Path(__file__).parent.parent))

from backtest.common.layered_backtest_runner import (
    run_layered_backtest,
    LayerConfigBase
)
from backtest.common.logger_config import get_logger
from backtest.common.data_loader import DEFAULT_CACHE_DIR

logger = get_logger(__name__)

DEFAULT_SURGE_WINDOW = 5
EPSILON = 1e-10


@dataclass
class TurnoverSurgeLayerConfig(LayerConfigBase):
    """换手率突增分层配置
    
    thresholds 设计说明：
    - 6个阈值点 [0, 0.5, 1.0, 2.0, 5.0, 500.0] 形成 5 层
    - Layer 划分：Layer1: [0, 0.5), Layer2: [0.5, 1), Layer3: [1, 2), Layer4: [2, 5), Layer5: [5, 500]
    - 边界处理：surge < 0 归 Layer 1（越界），surge > 500 归 Layer 5（越界）
    - 换手率突增因子为反向因子（高突增做空，低突增做多）
    """
    
    # thresholds 与 layer_names 对应（6个阈值点 → 5层）
    layer_thresholds: List[float] = field(default_factory=lambda: [0, 0.5, 1.0, 2.0, 5.0, 500.0])
    
    # layer_names 与 thresholds 对应（5层）：
    # - Layer 1: surge < 0.5（极低）→ 做多（反向因子）
    # - Layer 2: 0.5 ≤ surge < 1（偏低）→ 做多（反向因子）
    # - Layer 3: 1 ≤ surge < 2（正常）→ 不参与多空组合
    # - Layer 4: 2 ≤ surge < 5（偏高）→ 做空（反向因子）
    # - Layer 5: surge ≥ 5（突增）→ 做空（反向因子）
    layer_names: TypingDict[str, str] = field(default_factory=lambda: {
        '1': '极低层(surge<0.5)',
        '2': '偏低层(0.5≤surge<1)',
        '3': '正常层(1≤surge<2)',
        '4': '偏高层(2≤surge<5)',
        '5': '突增层(surge≥5)'
    })
    
    # 反向因子：高突增做空（异常），低突增做多（正常）
    factor_direction: str = 'negative'
    long_layers: List[int] = field(default_factory=lambda: [1, 2])   # 极低/偏低层做多
    short_layers: List[int] = field(default_factory=lambda: [4, 5])  # 偏高/突增层做空
    
    # layer_threshold_desc 与 thresholds 对应（5层）
    layer_threshold_desc: TypingDict[str, str] = field(default_factory=lambda: {
        '1': 'surge < 0.5 (换手率远低于均值，做多)',
        '2': '0.5 ≤ surge < 1 (换手率偏低，做多)',
        '3': '1 ≤ surge < 2 (换手率接近均值，不参与多空)',
        '4': '2 ≤ surge < 5 (换手率偏高，做空)',
        '5': 'surge ≥ 5 (含越界值>500，换手率突增，做空)'
    })


def calculate_turnover_surge(
    factor_df: pd.DataFrame,
    surge_window: int = DEFAULT_SURGE_WINDOW,
    log_handler: Any = None
) -> pd.DataFrame:
    """计算换手率突增因子
    
    Args:
        factor_df: 包含 turnover_rate, close 列的 DataFrame
        surge_window: 计算平均换手率的窗口期，默认 5
        log_handler: 日志对象（可选，避免遮蔽模块级 logger）
    
    Returns:
        包含 turnover_surge 列的 DataFrame
    """
    df = factor_df.copy()
    df = df.sort_values(['asset', 'date'])
    
    # 计算历史平均换手率（排除当日）
    avg_turnover = df.groupby('asset')['turnover_rate'].transform(
        lambda x: x.shift(1).rolling(surge_window, min_periods=surge_window).mean()
    )
    
    # 边界处理：avg_turnover 接近零时标记为 NaN（避免 division by zero 或极小值）
    zero_avg_mask = (avg_turnover.notna()) & (avg_turnover.abs() < EPSILON)
    if zero_avg_mask.sum() > 0 and log_handler:
        log_handler.warning(
            "avg_turnover 接近零的记录数: %d (%.2f%%)，标记为 NaN",
            zero_avg_mask.sum(), zero_avg_mask.sum() / len(df) * 100
        )
    
    safe_avg = avg_turnover.where(~zero_avg_mask, pd.NA)  # 用 pd.NA 替代 np.nan
    df['turnover_surge'] = df['turnover_rate'] / safe_avg
    
    # 边界处理：负值标记为 NaN（换手率突增应为正）
    negative_mask = df['turnover_surge'] < 0
    if negative_mask.sum() > 0 and log_handler:
        log_handler.warning(
            "turnover_surge 负值记录数: %d (%.2f%%)，标记为 NaN",
            negative_mask.sum(), negative_mask.sum() / len(df) * 100
        )
        df.loc[negative_mask, 'turnover_surge'] = pd.NA  # 用 pd.NA 替代 np.nan
    
    # 因子数据范围校验（遵循 MODULE.md 第505行规范）
    surge_min = df['turnover_surge'].min()
    surge_max = df['turnover_surge'].max()
    if log_handler:
        log_handler.info("turnover_surge 因子范围: %.2f ~ %.2f", surge_min, surge_max)
    
    return df


def main():
    import argparse
    parser = argparse.ArgumentParser(description='换手率突增分层回测')
    # argparse 参数命名说明：
    # - 命令行使用 --surge-window（连字符）
    # - Python 访问使用 args.surge_window（下划线，argparse 自动转换）
    # - 这是 argparse 标准行为，dest 参数可自定义内部名称
    parser.add_argument('--cache_dir', type=str, default=None,
                        help='缓存目录路径')
    parser.add_argument('--output_dir', type=str, default=None)
    parser.add_argument('--quiet', action='store_true')
    parser.add_argument('--surge-window', type=int, default=DEFAULT_SURGE_WINDOW,
                        help=f'换手率突增计算窗口，默认 {DEFAULT_SURGE_WINDOW}')
    args = parser.parse_args()
    
    try:
        def factor_calc(df):
            return calculate_turnover_surge(df, surge_window=args.surge_window, log_handler=logger)
        
        result = run_layered_backtest(
            factor_name='turnover_surge',
            factor_col='turnover_surge',
            config=TurnoverSurgeLayerConfig(),
            factor_calculator=factor_calc,
            additional_data_files={'turnover_rate': str(DEFAULT_CACHE_DIR / 'turnover_rate_data.json.gz')},
            required_factor_cols=['turnover_rate', 'close'],
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