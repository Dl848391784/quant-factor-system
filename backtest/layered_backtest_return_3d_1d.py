#!/usr/bin/env python3
"""
3日收益因子分层回测脚本

因子定义：
- 含义: 过去3日累计涨跌幅

策略逻辑：
- 反向因子：低值层做多，高值层做空
- 正向因子：高值层做多，低值层做空

分层模式：percentile 5层（每层约20%）

因子元数据派生机制（基类 LayerConfigBase）：
- factor_direction: 从 ic_source IC 文件加载，ic_mean < 0 为 negative
- n_layers: 由 len(layer_names) 派生
- long_layers/short_layers: 由 n_layers 和 factor_direction 派生
"""

from typing import ClassVar, Sequence

from backtest.common.layered_backtest_runner import LayerConfigBase
from backtest.common.factor_cli import factor_cli_main
from data_fetchers.factor_calculator import calculate_return_3d


class Return3dLayerConfig(LayerConfigBase):
    """3日收益因子分层配置
    
    薄声明：仅定义因子名称与分层命名，逻辑完全下沉基类。
    """
    
    factor_name: ClassVar[str] = 'return_3d'
    
    layer_names: ClassVar[Sequence[str]] = (
        '极低层(3日跌幅最大)',
        '偏低层(3日小幅下跌)',
        '正常层(3日变化不大)',
        '偏高层(3日小幅上涨)',
        '极高层(3日涨幅最大)',
    )


if __name__ == '__main__':
    factor_cli_main(
        config_cls=Return3dLayerConfig,
        factor_calculator=calculate_return_3d
    )