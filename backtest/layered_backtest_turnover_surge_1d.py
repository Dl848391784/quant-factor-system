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

# 标准库
import sys
from pathlib import Path
from dataclasses import dataclass, field
from functools import partial
from typing import List, Dict as TypingDict, Any

# 第三方库
import numpy as np
import pandas as pd

# 本地模块
sys.path.insert(0, str(Path(__file__).parent.parent))

from backtest.common.layered_backtest_runner import (
    run_layered_backtest,
    LayerConfigBase
)
from backtest.common.logger_config import get_logger
from backtest.common.data_loader import DEFAULT_DATA_SOURCE

logger = get_logger(__name__)

DEFAULT_SURGE_WINDOW = 5
# EPSILON 用于判断 avg_turnover 是否接近零（避免 division by zero）
# 换手率典型范围 0.0 ~ 1.0，1e-10 作为零值阈值合理
EPSILON = 1e-10


def _calc_avg_turnover(series: pd.Series, window: int) -> pd.Series:
    """计算历史平均换手率（groupby transform 专用，显式传参避免闭包）
    
    Args:
        series: 单资产的换手率序列
        window: 滚动窗口期
    
    Returns:
        历史平均换手率序列（shift(1) 排除当日）
    
    Note:
        - 使用 shift(1) 排除当日换手率，避免未来数据泄露
        - min_periods=window 确保只有足够历史数据时才计算
        - 有效数据从第 window+1 行才开始：
          * 第 0 行 shift 产生 NaN
          * 第 1~window 行凑不够 window 个非 NaN
          * 第 window+1 行才有第一个有效结果
          * 例如 window=5，需要至少 6 行原始数据才能产生第一个有效结果
    """
    return series.shift(1).rolling(window, min_periods=window).mean()


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
    
    # 格式遵循 MODULE.md 第451行规范：完整区间 [lower, upper)，必须包含下界
    layer_threshold_desc: TypingDict[str, str] = field(default_factory=lambda: {
        '1': '0 ≤ surge < 0.5 (含越界值<0，换手率远低于均值，做多)',   # 含越界值 surge < 0
        '2': '0.5 ≤ surge < 1 (换手率偏低，做多)',
        '3': '1 ≤ surge < 2 (换手率接近均值，不参与多空)',
        '4': '2 ≤ surge < 5 (换手率偏高，做空)',
        '5': 'surge ≥ 5 (含边界5，含越界值>500，换手率突增，做空)'     # 含越界值 surge > 500
    })


def calculate_turnover_surge(
    factor_df: pd.DataFrame,
    surge_window: int = DEFAULT_SURGE_WINDOW,
    log_handler: Any = logger
) -> pd.DataFrame:
    """计算换手率突增因子
    
    Args:
        factor_df: 包含 turnover_rate, close 列的 DataFrame
        surge_window: 计算平均换手率的窗口期，默认 5
        log_handler: 日志对象（默认使用模块级 logger）
    
    Returns:
        包含 turnover_surge 列的 DataFrame
    
    Raises:
        ValueError: 当 turnover_surge 全为 NaN 时
    """
    df = factor_df.copy()
    df = df.sort_values(['asset', 'date'])
    
    # 入口日志：记录参数与数据规模
    unique_assets = df['asset'].nunique()
    log_handler.info(f"换手率突增计算启动 [surge_window={surge_window}, 输入数据={len(df)}行/{unique_assets}只股票]")
    
    # 计算历史平均换手率（用 partial 显式传参，避免 lambda 闭包）
    avg_turnover = df.groupby('asset')['turnover_rate'].transform(
        partial(_calc_avg_turnover, window=surge_window)
    )
    
    # 边界处理：avg_turnover 接近零时标记为 NaN（避免 division by zero 或极小值）
    zero_avg_mask = (avg_turnover.notna()) & (avg_turnover.abs() < EPSILON)
    if zero_avg_mask.sum() > 0:
        log_handler.warning(
            f"avg_turnover 接近零的记录数: {zero_avg_mask.sum()} ({zero_avg_mask.sum() / len(df) * 100:.2f}%)，标记为 NaN"
        )
    
    # 使用 np.nan 替代 pd.NA（float64 Series 更兼容）
    safe_avg = avg_turnover.where(~zero_avg_mask, np.nan)
    df['turnover_surge'] = df['turnover_rate'] / safe_avg
    
    # 边界处理：负值标记为 NaN（换手率突增应为正）
    negative_mask = df['turnover_surge'] < 0
    if negative_mask.sum() > 0:
        log_handler.warning(
            f"turnover_surge 负值记录数: {negative_mask.sum()} ({negative_mask.sum() / len(df) * 100:.2f}%)，标记为 NaN"
        )
        df.loc[negative_mask, 'turnover_surge'] = np.nan  # 使用 np.nan 替代 pd.LA
    
    # 因子数据范围校验（遵循 MODULE.md 第505行规范）
    # 全 NaN 防御：检查是否有有效数据
    surge_values = df['turnover_surge'].dropna()
    if len(surge_values) == 0:
        log_handler.error("turnover_surge 全为 NaN，无法进入回测流程")
        raise ValueError("turnover_surge 因子全为 NaN，请检查输入数据是否包含 turnover_rate 列")
    
    surge_min = surge_values.min()
    surge_max = surge_values.max()
    log_handler.info(f"turnover_surge 因子范围: {surge_min:.2f} ~ {surge_max:.2f}")
    
    return df


def main():
    import argparse
    
    parser = argparse.ArgumentParser(description='换手率突增分层回测')
    # argparse 参数命名说明：
    # - 命令行使用 --surge-window（连字符）
    # - Python 访问使用 args.surge_window（下划线，argparse 自动转换）
    # - 这是 argparse 标准行为，dest 参数可自定义内部名称
    parser.add_argument('--data_source', type=str, default=str(DEFAULT_DATA_SOURCE),
                        help='数据源文件路径')
    parser.add_argument('--output_dir', type=str, default=None)
    parser.add_argument('--quiet', action='store_true')
    parser.add_argument('--surge-window', type=int, default=DEFAULT_SURGE_WINDOW,
                        help=f'换手率突增计算窗口，默认 {DEFAULT_SURGE_WINDOW}')
    args = parser.parse_args()
    
    try:
        # 使用 functools.partial 替代闭包，显式传参避免捕获外部变量
        factor_calc = partial(
            calculate_turnover_surge,
            surge_window=args.surge_window,
            log_handler=logger
        )
        
        # 更新历史（2026-05-27）：v2.7 移除 additional_data_files 和 cache_dir
        # turnover_surge 因子已预计算在统一数据源中，但保留 factor_calculator 以支持自定义窗口
        result = run_layered_backtest(
            factor_name='turnover_surge',
            factor_col='turnover_surge',
            config=TurnoverSurgeLayerConfig(),
            factor_calculator=factor_calc,
            required_factor_cols=['turnover_rate', 'close'],
            data_source=args.data_source,
            output_dir=args.output_dir,
            verbose=not args.quiet,
            logger=logger
        )
        
        if result['meta']['n_days_total'] == 0:
            logger.error("回测无有效数据，程序终止")
            sys.exit(1)
        
        # 结果摘要日志（遵循分层回测脚本必须输出完整结果的规范）
        logger.info("=" * 60)
        logger.info("回测结果摘要")
        logger.info("=" * 60)
        logger.info(f"因子名称: {result['meta']['factor_name']}")
        logger.info(f"回测周期: {result['meta']['n_days_total']} 天")
        
        # 各分层收益
        layer_returns = result.get('layer_returns', {})
        for layer_name, ret in layer_returns.items():
            logger.info(f"Layer {layer_name} 累计收益: {ret:.4f}")
        
        # 多空组合收益
        long_short = result.get('long_short', {})
        if long_short:
            logger.info(f"多空组合累计收益: {long_short.get('cumulative_return', 0):.4f}")
            logger.info(f"夏普比率: {long_short.get('sharpe_ratio', 0):.2f}")
            logger.info(f"最大回撤: {long_short.get('max_drawdown', 0):.2%}")
        
        logger.info("回测完成")
        sys.exit(0)
        
    except FileNotFoundError:
        logger.exception("数据文件不存在")
        sys.exit(2)
    except KeyError:
        logger.exception("数据结构错误")
        sys.exit(3)
    except ValueError:
        logger.exception("参数错误")
        sys.exit(4)
    except Exception:
        logger.exception("回测执行异常")
        sys.exit(5)


if __name__ == '__main__':
    main()