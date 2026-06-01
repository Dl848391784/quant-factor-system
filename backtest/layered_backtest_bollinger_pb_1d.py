#!/usr/bin/env python3
"""
布林带位置因子分层回测脚本

因子定义：
- 含义: 价格在布林带中的相对位置

因子元数据派生机制（基类 LayerConfigBase）：
- factor_direction: 从 ic_source IC 文件加载，ic_mean < 0 为 negative
- n_layers: 由 len(layer_names) 派生
- layer_names_dict: 优先使用 layer_descriptions，否则回退 layer_names
"""

from typing import ClassVar, Sequence

from backtest.common.layered_backtest_runner import LayerConfigBase
from backtest.common.factor_cli import factor_cli_main
from data_fetchers.factor_calculator import calculate_bollinger_pb


class BollingerPbLayerConfig(LayerConfigBase):
    """布林带位置因子分层配置
    
    薄声明：因子元数据集中在 ClassVar，逻辑完全下沉基类。
    """
    
    factor_name: ClassVar[str] = 'bollinger_pb'
    
    layer_names: ClassVar[Sequence[str]] = (
        'lowest',
        'lower',
        'normal',
        'higher',
        'highest'
    )
    
    layer_descriptions: ClassVar[Sequence[str]] = (
        '极低层(接近下轨)',
        '偏低层(低于中轨)',
        '正常层(在中轨附近)',
        '偏高层(高于中轨)',
        '极高层(接近上轨)'
    )


if __name__ == '__main__':
    factor_cli_main(BollingerPbLayerConfig, calculate_bollinger_pb)