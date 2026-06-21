#!/usr/bin/env python3
"""interaction_turnover 因子分层回测脚本

因子定义:
- interaction_turnover = -z_cs(return_3d) × z_cs(turnover_rate)
- 含义: 弱势 × 高换手 = 反弹型信号; 强势 × 高换手 = 高位风险
- 期望 IC: +0.016（design.md feat_interaction_factors §3 实证）

分层模式: percentile 5层（每层约20%）。
设计依据: designs/feat_interaction_factors.md（条件因子方向方案 B）
"""

from collections.abc import Sequence
from typing import ClassVar

from backtest.common.factor_cli import factor_cli_main
from backtest.common.layered_backtest_runner import LayerConfigBase
from data_fetchers.factor_calculator import calculate_interaction_turnover


class InteractionTurnoverLayerConfig(LayerConfigBase):
    """interaction_turnover 交互因子分层配置（条件因子方向方案 B）"""

    factor_name: ClassVar[str] = "interaction_turnover"

    layer_names: ClassVar[Sequence[str]] = ("lowest", "lower", "normal", "higher", "highest")

    layer_descriptions: ClassVar[Sequence[str]] = (
        "极低层(强势×高换手 高位风险型)",
        "偏低层",
        "正常层",
        "偏高层",
        "极高层(弱势×高换手 反弹型)",
    )


if __name__ == "__main__":
    factor_cli_main(config_cls=InteractionTurnoverLayerConfig, factor_calculator=calculate_interaction_turnover)
