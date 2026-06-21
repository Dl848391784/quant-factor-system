#!/usr/bin/env python3
"""
量能衰减因子分层回测脚本

因子定义：
- volume_decay_rate: volume_ma5 / volume_ma10
- 含义: <1=量能衰减（卖盘参与度下降）
- v2.35: P5-补充 新增因子（确认信号角色，二阶导数企稳信号）
- 因子已在 factor_generator 预计算，factor_calculator=None

分层模式：percentile 5层（每层约20%）

因子元数据派生机制（基类 LayerConfigBase）：
- factor_direction: 从 ic_source IC 文件加载，ic_mean < 0 为 negative
- n_layers: 由 len(layer_names) 派生
- long_layers/short_layers: 由 n_layers 和 factor_direction 派生
"""

from collections.abc import Sequence
from typing import ClassVar

from backtest.common.factor_cli import factor_cli_main
from backtest.common.layered_backtest_runner import LayerConfigBase


class VolumeDecayRateLayerConfig(LayerConfigBase):
    """量能衰减因子分层配置

    薄声明：仅定义因子名称与分层命名，逻辑完全下沉基类。
    """

    factor_name: ClassVar[str] = "volume_decay_rate"

    layer_names: ClassVar[Sequence[str]] = (
        "lowest",
        "lower",
        "normal",
        "higher",
        "highest",
    )

    layer_descriptions: ClassVar[Sequence[str]] = (
        "极低层(量能大幅衰减)",
        "偏低层(量能轻微衰减)",
        "正常层(量能稳定)",
        "偏高层(量能轻微放大)",
        "极高层(量能明显放大)",
    )


if __name__ == "__main__":
    factor_cli_main(config_cls=VolumeDecayRateLayerConfig, factor_calculator=None)
