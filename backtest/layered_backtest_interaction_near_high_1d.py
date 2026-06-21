#!/usr/bin/env python3
"""interaction_near_high 因子分层回测脚本

因子定义: -z_cs(ret3d) × z_cs(near_high_ratio_5)
设计依据: designs/feat_interaction_factors_batch2.md
"""

from collections.abc import Sequence
from typing import ClassVar

from backtest.common.factor_cli import factor_cli_main
from backtest.common.layered_backtest_runner import LayerConfigBase
from data_fetchers.factor_calculator import calculate_interaction_near_high


class InteractionNearHighLayerConfig(LayerConfigBase):
    factor_name: ClassVar[str] = "interaction_near_high"
    layer_names: ClassVar[Sequence[str]] = ("lowest", "lower", "normal", "higher", "highest")
    layer_descriptions: ClassVar[Sequence[str]] = (
        "极低层",
        "偏低层",
        "正常层",
        "偏高层",
        "极高层(反弹型)",
    )


if __name__ == "__main__":
    factor_cli_main(config_cls=InteractionNearHighLayerConfig, factor_calculator=calculate_interaction_near_high)
