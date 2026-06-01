#!/usr/bin/env python3
"""
换手率突增因子分层回测脚本

因子定义：
- 含义: 换手率相对历史均值的突增幅度

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
from data_fetchers.factor_calculator import calculate_turnover_surge


@dataclass
class TurnoverSurgeLayerConfig(LayerConfigBase):
    """换手率突增因子分层配置"""
    
    factor_name: ClassVar[str] = 'turnover_surge'
    
    layer_names: Dict[str, str] = field(default_factory=lambda: {
        '1': '极低层(换手率无突增)',
        '2': '偏低层(换手率小幅突增)',
        '3': '正常层(换手率中等突增)',
        '4': '偏高层(换手率大幅突增)',
        '5': '极高层(换手率极端突增)'
    })


if __name__ == '__main__':
    factor_cli_main(
        config_cls=TurnoverSurgeLayerConfig,
        factor_calculator=calculate_turnover_surge
    )