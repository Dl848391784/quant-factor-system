#!/usr/bin/env python3
"""
换手率突增因子分层回测脚本

因子定义：
- 含义: 换手率相对历史均值的突增幅度

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
from data_fetchers.factor_calculator import calculate_turnover_surge


class TurnoverSurgeLayerConfig(LayerConfigBase):
    """换手率突增因子分层配置
    
    薄声明：仅定义因子名称与分层命名，逻辑完全下沉基类。
    """
    
    factor_name: ClassVar[str] = 'turnover_surge'
    
    layer_names: ClassVar[Sequence[str]] = (
        '极低层(换手率无突增)',
        '偏低层(换手率小幅突增)',
        '正常层(换手率中等突增)',
        '偏高层(换手率大幅突增)',
        '极高层(换手率极端突增)',
    )


if __name__ == '__main__':
    factor_cli_main(
        config_cls=TurnoverSurgeLayerConfig,
        factor_calculator=calculate_turnover_surge
    )