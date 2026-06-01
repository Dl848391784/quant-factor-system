#!/usr/bin/env python3
"""
价格位置因子分层回测脚本

因子定义：
- 公式: price_position = (close - low_N) / (high_N - low_N)
- 含义: 价格在过去N日高低点中的相对位置
- 理论范围: [0, 1]

因子元数据派生机制（基类 LayerConfigBase）：
- factor_col_resolved: 从 factor_col ClassVar 派生，默认=factor_name
- factor_direction: 从 ic_source IC 文件加载，ic_mean < 0 为 negative
- n_layers: 由 len(layer_names) 派生
- layer_names_dict: 优先使用 layer_descriptions，否则回退 layer_names
"""

from typing import ClassVar, Sequence

from backtest.common.layered_backtest_runner import LayerConfigBase
from backtest.common.factor_cli import factor_cli_main
from data_fetchers.factor_calculator import calculate_price_position


class PricePositionLayerConfig(LayerConfigBase):
    """价格位置因子分层配置
    
    薄声明：因子元数据集中在 ClassVar，逻辑完全下沉基类。
    
    特点：
    - price_position 需实时计算（factor_calculator）
    - layer_names 纯标签（用于目录/列名），layer_descriptions 含中文（用于日志）
    """
    
    factor_name: ClassVar[str] = 'price_position'
    
    layer_names: ClassVar[Sequence[str]] = (
        'lowest',
        'lower',
        'normal',
        'higher',
        'highest'
    )
    
    layer_descriptions: ClassVar[Sequence[str]] = (
        '极低层(接近N日最低)',
        '偏低层(低于中位)',
        '正常层(在中位附近)',
        '偏高层(高于中位)',
        '极高层(接近N日最高)'
    )


if __name__ == '__main__':
    factor_cli_main(PricePositionLayerConfig, calculate_price_position)