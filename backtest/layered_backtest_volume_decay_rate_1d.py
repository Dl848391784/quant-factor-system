#!/usr/bin/env python3
"""
量能衰减因子分层回测脚本

因子定义：
- volume_decay_rate: 5日均量 / 10日均量
- 含义: 量能衰减——<1=卖盘衰竭（企稳信号）
- v2.35: P5-补充 二阶导数企稳信号因子（design.md §1, §5）
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
        "量能放大最大",
        "量能放大较小",
        "量比适中",
        "量能衰减较小",
        "量能衰减最大",
    )


if __name__ == "__main__":
    factor_cli_main(config_cls=VolumeDecayRateLayerConfig, factor_calculator=None)
