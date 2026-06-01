#!/usr/bin/env python3
"""
RSI因子分层回测脚本

因子定义：
- 含义: 相对强弱指数

策略逻辑：
- 反向因子：低值层做多，高值层做空
- 正向因子：高值层做多，低值层做空

分层模式：percentile 4层（每层约25%）

作者: 云瑶
"""

from dataclasses import dataclass, field
from typing import Dict, ClassVar

from backtest.common.layered_backtest_runner import LayerConfigBase
from backtest.common.factor_cli import factor_cli_main
from data_fetchers.factor_calculator import calculate_rsi_df


@dataclass
class RsiLayerConfig(LayerConfigBase):
    """RSI因子分层配置"""
    
    factor_name: ClassVar[str] = 'rsi'
    
    layer_names: Dict[str, str] = field(default_factory=lambda: {
        '1': '超卖层(RSI<30)',
        '2': '偏低层(RSI 30-40)',
        '3': '中性层(RSI 40-60)',
        '4': '偏高层(RSI 60-70)'
    })


if __name__ == '__main__':
    factor_cli_main(
        config_cls=RsiLayerConfig,
        factor_calculator=calculate_rsi_df
    )