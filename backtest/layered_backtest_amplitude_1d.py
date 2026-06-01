#!/usr/bin/env python3
"""
振幅因子分层回测脚本

因子定义：
- 含义: 过去N日价格波动幅度

分层模式：percentile 5层（每层约20%）

因子元数据派生机制（基类 LayerConfigBase）：
- factor_direction: 从 ic_source IC 文件加载，ic_mean < 0 为 negative
- n_layers: 由 len(layer_names) 派生
- long_layers/short_layers: 由 n_layers 和 factor_direction 派生
"""

from typing import ClassVar, Sequence

from backtest.common.layered_backtest_runner import LayerConfigBase
from backtest.common.factor_cli import factor_cli_main
from data_fetchers.factor_calculator import calculate_amplitude


class AmplitudeLayerConfig(LayerConfigBase):
    """振幅因子分层配置
    
    薄声明：仅定义因子名称与分层命名，逻辑完全下沉基类。
    """
    
    factor_name: ClassVar[str] = 'amplitude'
    
    layer_names: ClassVar[Sequence[str]] = (
        'lowest', 'lower', 'normal', 'higher', 'highest'
    )
    
    layer_descriptions: ClassVar[Sequence[str]] = (
        '极低层(振幅最小)',
        '偏低层(振幅较小)',
        '正常层(振幅适中)',
        '偏高层(振幅较大)',
        '极高层(振幅最大)',
    )


if __name__ == '__main__':
    factor_cli_main(
        config_cls=AmplitudeLayerConfig,
        factor_calculator=calculate_amplitude
    )