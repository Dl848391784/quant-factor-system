#!/usr/bin/env python3
"""interaction_bollinger 因子分层回测脚本

因子定义: -z_cs(ret5d) × z_cs(bollinger_pb)
设计依据: designs/feat_interaction_factors_batch2.md
"""

from collections.abc import Sequence
from typing import ClassVar

from backtest.common.factor_cli import factor_cli_main
from backtest.common.layered_backtest_runner import LayerConfigBase
from data_fetchers.factor_calculator import calculate_interaction_bollinger


class InteractionBollingerLayerConfig(LayerConfigBase):
    factor_name: ClassVar[str] = "interaction_bollinger"
    layer_names: ClassVar[Sequence[str]] = ("lowest", "lower", "normal", "higher", "highest")
    layer_descriptions: ClassVar[Sequence[str]] = (
        "极低层",
        "偏低层",
        "正常层",
        "偏高层",
        "极高层(反弹型)",
    )


if __name__ == "__main__":
    factor_cli_main(config_cls=InteractionBollingerLayerConfig, factor_calculator=calculate_interaction_bollinger)
