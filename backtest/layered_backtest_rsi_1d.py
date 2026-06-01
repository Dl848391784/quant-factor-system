#!/usr/bin/env python3
"""
RSI因子分层回测脚本

因子定义：
- 含义: 相对强弱指数

分层模式：percentile

因子元数据派生机制（基类 LayerConfigBase）：
- factor_direction: 从 ic_source IC 文件加载，ic_mean < 0 为 negative
- n_layers: 由 len(layer_names) 派生
- long_layers/short_layers: 由 n_layers 和 factor_direction 派生
"""

from typing import ClassVar, Sequence

from backtest.common.layered_backtest_runner import LayerConfigBase
from backtest.common.factor_cli import factor_cli_main
from data_fetchers.factor_calculator import calculate_rsi_df


class RsiLayerConfig(LayerConfigBase):
    """RSI因子分层配置
    
    薄声明：仅定义因子名称与分层命名，逻辑完全下沉基类。
    """
    
    factor_name: ClassVar[str] = 'rsi'
    
    layer_names: ClassVar[Sequence[str]] = (
        'oversold',
        'low',
        'normal',
        'high',
    )
    
    layer_descriptions: ClassVar[Sequence[str]] = (
        '超卖层(RSI<30)',
        '偏低层(RSI 30-40)',
        '中性层(RSI 40-60)',
        '偏高层(RSI 60-70)',
    )


if __name__ == '__main__':
    factor_cli_main(
        config_cls=RsiLayerConfig,
        factor_calculator=calculate_rsi_df
    )