#!/usr/bin/env python3
"""
振幅因子分层回测脚本

因子定义：
- 含义: 过去N日价格波动幅度

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
from data_fetchers.factor_calculator import calculate_amplitude


@dataclass
class AmplitudeLayerConfig(LayerConfigBase):
    """振幅因子分层配置"""
    
    factor_name: ClassVar[str] = 'amplitude'
    
    layer_names: Dict[str, str] = field(default_factory=lambda: {
        '1': '极低层(振幅最小)',
        '2': '偏低层(振幅较小)',
        '3': '正常层(振幅适中)',
        '4': '偏高层(振幅较大)',
        '5': '极高层(振幅最大)'
    })


if __name__ == '__main__':
    factor_cli_main(
        config_cls=AmplitudeLayerConfig,
        factor_calculator=calculate_amplitude
    )