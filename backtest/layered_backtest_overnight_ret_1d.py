#!/usr/bin/env python3
"""
隔夜收益率因子分层回测脚本

使用公共入口 run_layered_backtest，遵循 PROJECT.md 公共模块强制复用规范。

分层方法：
- 百分位分层（n_layers=5，每层20%）
- Layer 1: 0-20%分位（最低值）
- Layer 2: 20-40%分位（偏低值）
- Layer 3: 40-60%分位（正常值）
- Layer 4: 60-80%分位（偏高值）
- Layer 5: 80-100%分位（最高值）

因子方向：
- 正向因子（IC 均值 = 0.0212 > 0）
- 高值层做多，低值层做空

作者: 云瑶
创建日期: 2026-05-28
"""

# 标准库
import sys
from pathlib import Path
from functools import partial
from dataclasses import field
from typing import List, Dict as TypingDict

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

EPSILON = 1e-10  # 避免除零阈值


# ============================================================================
# 分层配置
# ============================================================================

class OvernightRetLayerConfig(LayerConfigBase):
    """隔夜收益率分层配置
    
    百分位分层设计（n_layers=5）：
    - Layer 1: 0-20%分位（极低层，隔夜跌幅最大）→ 做空（正向因子）
    - Layer 2: 20-40%分位（偏低层）→ 做空（正向因子）
    - Layer 3: 40-60%分位（正常层）→ 不参与多空
    - Layer 4: 60-80%分位（偏高层）→ 做多（正向因子）
    - Layer 5: 80-100%分位（极高层，隔夜涨幅最大）→ 做多（正向因子）
    
    因子方向：正向因子（IC 均值 = 0.0212 > 0）
    - 高隔夜收益率 → 高未来收益 → 做多
    - 低隔夜收益率 → 低未来收益 → 做空
    
    多空组合：
    - 做多：Layer 4、Layer 5（高值层）
    - 做空：Layer 1、Layer 2（低值层）
    """
    
    # 百分位分层参数（强制）
    n_layers: int = 5
    
    # 分层命名（业务描述，不含阈值）
    layer_names: TypingDict[str, str] = field(default_factory=lambda: {
        '1': '极低层(0-20%分位)',
        '2': '偏低层(20-40%分位)',
        '3': '正常层(40-60%分位)',
        '4': '偏高层(60-80%分位)',
        '5': '极高层(80-100%分位)'
    })
    
    # 因子方向和多空组合（覆盖基类默认值）
    factor_direction: str = 'positive'  # 正向因子
    long_layers: List[int] = field(default_factory=lambda: [4, 5])  # 高值层做多
    short_layers: List[int] = field(default_factory=lambda: [1, 2])  # 低值层做空
    
    # 通用参数（继承基类默认值）
    # trade_cost_rate: float = 0.003  # 交易成本率 0.3%
    # min_stocks_per_layer: int = 10  # 每层最小股票数


# ============================================================================
# 因子计算函数
# ============================================================================

def calculate_overnight_return(
    factor_df: pd.DataFrame,
    log_handler = logger
) -> pd.DataFrame:
    """计算隔夜收益率因子
    
    公式: overnight_ret = (今日开盘价 - 昨日收盘价) / 昨日收盘价
    
    Args:
        factor_df: 包含 open, close 列的 DataFrame
            - 必须包含 'asset', 'date', 'open', 'close' 列
        log_handler: 日志记录器（由调用方传入）
    
    Returns:
        DataFrame，新增 'overnight_ret' 列
        
    Note:
        - 第一天数据为 NaN（无昨日收盘价）
        - 除零防护：prev_close < EPSILON 时设为 NaN
        - 按资产分组计算（每只股票独立）
        
    Example:
        >>> factor_df = pd.DataFrame({
        >>>     'asset': ['A', 'A', 'B', 'B'],
        >>>     'date': ['2026-05-01', '2026-05-02', '2026-05-01', '2026-05-02'],
        >>>     'open': [10.0, 10.5, 20.0, 21.0],
        >>>     'close': [10.2, 10.8, 20.5, 21.5]
        >>> })
        >>> result_df = calculate_overnight_return(factor_df)
        >>> print(result_df['overnight_ret'])
        >>> # asset A: NaN, 0.0294
        >>> # asset B: NaN, 0.0244
    """
    # 遵循 MODULE.md 约束：函数入口先 copy()
    df = factor_df.copy()
    
    # 入口日志：记录数据规模
    unique_assets = df['asset'].nunique()
    log_handler.info(
        f"隔夜收益率计算启动 "
        f"[输入数据={len(df)}行/{unique_assets}只股票]"
    )
    
    # 按资产分组计算（每只股票独立）
    prev_close = df.groupby('asset')['close'].shift(1)
    
    # 计算隔夜收益率
    df['overnight_ret'] = (df['open'] - prev_close) / prev_close
    
    # 除零防护：prev_close 极小或为 0 时设为 NaN
    abnormal_mask = prev_close < EPSILON
    if abnormal_mask.any():
        abnormal_count = abnormal_mask.sum()
        log_handler.warning(
            f"发现 {abnormal_count} 个异常收盘价（< {EPSILON}），"
            f"隔夜收益率已设为 NaN"
        )
        df.loc[abnormal_mask, 'overnight_ret'] = np.nan
    
    # 因子数据范围校验
    valid_values = df['overnight_ret'].dropna()
    if len(valid_values) == 0:
        log_handler.error("overnight_ret 全为 NaN，无法进入回测流程")
        raise ValueError(
            "overnight_ret 因子全为 NaN，请检查输入数据是否包含 open、close 列"
        )
    
    ret_min = valid_values.min()
    ret_max = valid_values.max()
    ret_mean = valid_values.mean()
    ret_std = valid_values.std()
    
    log_handler.info(
        f"overnight_ret 因子范围: {ret_min:.4f} ~ {ret_max:.4f} "
        f"(均值={ret_mean:.4f}, 标准差={ret_std:.4f})"
    )
    
    # 统计计算结果
    valid_count = df['overnight_ret'].notna().sum()
    total_count = len(df)
    log_handler.info(
        f"隔夜收益率计算完成 "
        f"[有效值: {valid_count}/{total_count} ({valid_count/total_count:.2%})]"
    )
    
    return df


# ============================================================================
# CLI 入口
# ============================================================================

def main():
    import argparse
    
    parser = argparse.ArgumentParser(description='隔夜收益率分层回测')
    parser.add_argument(
        '--data_source',
        type=str,
        default=str(DEFAULT_DATA_SOURCE),
        help='数据源文件路径'
    )
    parser.add_argument('--output_dir', type=str, default=None)
    parser.add_argument('--quiet', action='store_true')
    
    args = parser.parse_args()
    
    try:
        # 使用 functools.partial 替代闭包
        factor_calc = partial(
            calculate_overnight_return,
            log_handler=logger
        )
        
        # 调用公共入口（显式传递因子方向参数，避免继承问题）
        result = run_layered_backtest(
            factor_name='overnight_ret',
            factor_col='overnight_ret',
            config=OvernightRetLayerConfig(
                factor_direction='positive',  # 显式传递正向因子
                long_layers=[4, 5],            # 显式传递高值层做多
                short_layers=[1, 2]            # 显式传递低值层做空
            ),
            factor_calculator=factor_calc,
            required_factor_cols=['open', 'close'],
            data_source=args.data_source,
            output_dir=args.output_dir,
            verbose=not args.quiet,
            logger=logger
        )
        
        # 验证回测结果
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
            logger.info(f"年化收益: {long_short.get('long_short_return_annual', 0):.2%}")
            logger.info(f"夏普比率: {long_short.get('long_short_sharpe', 0):.2f}")
            logger.info(f"最大回撤: {long_short.get('max_drawdown', 0):.2%}")
        
        # 单调性指标
        monotonicity = result.get('monotonicity', {})
        if monotonicity:
            logger.info(f"单调性系数: {monotonicity.get('correlation', 0):.4f}")
            logger.info(f"单调性质量: {monotonicity.get('quality', 'unknown')}")
        
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