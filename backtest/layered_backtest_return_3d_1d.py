#!/usr/bin/env python3
"""
3日收益因子分层回测脚本

因子定义：
- 含义: 过去3日累计涨跌幅

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
from data_fetchers.factor_calculator import calculate_return_3d


@dataclass
class Return3dLayerConfig(LayerConfigBase):
    """3日收益因子分层配置"""
    
    factor_name: ClassVar[str] = 'return_3d'
    
    layer_names: Dict[str, str] = field(default_factory=lambda: {
        '1': '极低层(3日跌幅最大)',
        '2': '偏低层(3日小幅下跌)',
        '3': '正常层(3日变化不大)',
        '4': '偏高层(3日小幅上涨)',
        '5': '极高层(3日涨幅最大)'
    })


if __name__ == '__main__':
    factor_cli_main(
        config_cls=Return3dLayerConfig,
        factor_calculator=calculate_return_3d
    )