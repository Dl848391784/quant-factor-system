#!/usr/bin/env python3
"""
价格位置因子分层回测脚本

因子定义：
- 含义: 价格在过去N日高低点中的相对位置

策略逻辑：
- 反向因子：低值层做多，高值层做空
- 正向因子：高值层做多，低值层做空

分层模式：percentile 5层（每层约20%）

作者: 云瑶
"""

from dataclasses import dataclass, field
from typing import Dict, ClassVar

from backtest.common.layered_backtest_runner import LayerConfigBase
from backtest.common.factor_cli import factor_cli_main
from data_fetchers.factor_calculator import calculate_price_position


@dataclass
class PricePositionLayerConfig(LayerConfigBase):
    """价格位置因子分层配置"""
    
    factor_name: ClassVar[str] = 'price_position'
    
    layer_names: Dict[str, str] = field(default_factory=lambda: {
        '1': '极低层(接近N日最低)',
        '2': '偏低层(低于中位)',
        '3': '正常层(在中位附近)',
        '4': '偏高层(高于中位)',
        '5': '极高层(接近N日最高)'
    })


if __name__ == '__main__':
    factor_cli_main(
        config_cls=PricePositionLayerConfig,
        factor_calculator=calculate_price_position
    )