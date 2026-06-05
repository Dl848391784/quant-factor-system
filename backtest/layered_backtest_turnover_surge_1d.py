#!/usr/bin/env python3
"""
换手率突增因子分层回测脚本

因子定义：
- 公式: turnover_surge = 当日换手率 / 过去N日平均换手率
- 含义: 换手率相对历史均值的突增幅度
- 理论范围: ≥ 0（无上界）

因子元数据派生机制（基类 LayerConfigBase）：
- factor_col_resolved: 从 factor_col ClassVar 派生，默认=factor_name
- factor_direction: 从 ic_source IC 文件加载，ic_mean < 0 为 negative
- n_layers: 由 len(layer_names) 派生
- layer_names_dict: 优先使用 layer_descriptions，否则回退 layer_names
"""

from collections.abc import Sequence
from typing import ClassVar

from backtest.common.factor_cli import factor_cli_main
from backtest.common.layered_backtest_runner import LayerConfigBase
from data_fetchers.factor_calculator import calculate_turnover_surge


class TurnoverSurgeLayerConfig(LayerConfigBase):
    """换手率突增因子分层配置
    
    薄声明：因子元数据集中在 ClassVar，逻辑完全下沉基类。
    
    特点：
    - turnover_surge 需实时计算（factor_calculator）
    - layer_names 纯标签（用于目录/列名），layer_descriptions 含中文（用于日志）
    """

    factor_name: ClassVar[str] = 'turnover_surge'

    layer_names: ClassVar[Sequence[str]] = (
        'lowest',
        'lower',
        'normal',
        'higher',
        'highest'
    )

    layer_descriptions: ClassVar[Sequence[str]] = (
        '极低层(换手率无突增)',
        '偏低层(换手率小幅突增)',
        '正常层(换手率中等突增)',
        '偏高层(换手率大幅突增)',
        '极高层(换手率极端突增)'
    )


if __name__ == '__main__':
    factor_cli_main(TurnoverSurgeLayerConfig, calculate_turnover_surge)
