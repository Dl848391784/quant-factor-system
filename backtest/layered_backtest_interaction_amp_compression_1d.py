#!/usr/bin/env python3
"""interaction_amp_compression 因子分层回测脚本

因子定义:
- interaction_amp_compression = -z_cs(return_3d) × z_cs(amplitude_compression)
- 含义: 弱势 × 振幅收敛 = 企稳信号; 强势 × 振幅收敛 = 趋势衰竭
- 期望 IC: +0.008（design.md feat_interaction_factors §3 实证，弱信号但维度独立）

分层模式: percentile 5层（每层约20%）。
设计依据: designs/feat_interaction_factors.md（条件因子方向方案 B）
"""

from collections.abc import Sequence
from typing import ClassVar

from backtest.common.factor_cli import factor_cli_main
from backtest.common.layered_backtest_runner import LayerConfigBase
from data_fetchers.factor_calculator import calculate_interaction_amp_compression


class InteractionAmpCompressionLayerConfig(LayerConfigBase):
    """interaction_amp_compression 交互因子分层配置（条件因子方向方案 B）"""

    factor_name: ClassVar[str] = "interaction_amp_compression"

    layer_names: ClassVar[Sequence[str]] = ("lowest", "lower", "normal", "higher", "highest")

    layer_descriptions: ClassVar[Sequence[str]] = (
        "极低层(强势×振幅收敛 趋势衰竭型)",
        "偏低层",
        "正常层",
        "偏高层",
        "极高层(弱势×振幅收敛 企稳型)",
    )


if __name__ == "__main__":
    factor_cli_main(
        config_cls=InteractionAmpCompressionLayerConfig,
        factor_calculator=calculate_interaction_amp_compression,
    )
