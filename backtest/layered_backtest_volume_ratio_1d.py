#!/usr/bin/env python3
"""
量比因子分层回测脚本

因子定义：
- 含义: 成交量相对历史均值的比率

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


@dataclass
class VolumeRatioLayerConfig(LayerConfigBase):
    """量比因子分层配置"""
    
    factor_name: ClassVar[str] = 'volume_ratio'
    
    layer_names: Dict[str, str] = field(default_factory=lambda: {
        '1': '极低层(量比极低)',
        '2': '偏低层(量比偏低)',
        '3': '正常层(量比适中)',
        '4': '偏高层(量比偏高)',
        '5': '极高层(量比极高)'
    })


if __name__ == '__main__':
    factor_cli_main(
        config_cls=VolumeRatioLayerConfig
    )