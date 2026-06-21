#!/usr/bin/env python3
"""
振幅收敛因子分层回测脚本

因子定义：
- amplitude_compression: 5日均振幅 / 10日均振幅
- 含义: 振幅收敛——<1=波动收敛（企稳信号）
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


class AmplitudeCompressionLayerConfig(LayerConfigBase):
    """振幅收敛因子分层配置

    薄声明：仅定义因子名称与分层命名，逻辑完全下沉基类。
    """

    factor_name: ClassVar[str] = "amplitude_compression"

    layer_names: ClassVar[Sequence[str]] = (
        "lowest",
        "lower",
        "normal",
        "higher",
        "highest",
    )

    layer_descriptions: ClassVar[Sequence[str]] = (
        "振幅发散最大",
        "振幅发散较小",
        "振幅适中",
        "振幅收敛较小",
        "振幅收敛最大",
    )


if __name__ == "__main__":
    factor_cli_main(config_cls=AmplitudeCompressionLayerConfig, factor_calculator=None)
