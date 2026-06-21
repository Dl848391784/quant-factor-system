#!/usr/bin/env python3
"""
换手率衰减因子分层回测脚本

因子定义：
- turnover_decay_rate: turnover_rate / turnover_rate_ma5
- 含义: <1=换手率下降（卖盘参与度下降）
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


class TurnoverDecayRateLayerConfig(LayerConfigBase):
    """换手率衰减因子分层配置

    薄声明：仅定义因子名称与分层命名，逻辑完全下沉基类。
    """

    factor_name: ClassVar[str] = "turnover_decay_rate"

    layer_names: ClassVar[Sequence[str]] = (
        "lowest",
        "lower",
        "normal",
        "higher",
        "highest",
    )

    layer_descriptions: ClassVar[Sequence[str]] = (
        "极低层(换手率大幅下降)",
        "偏低层(换手率轻微下降)",
        "正常层(换手率稳定)",
        "偏高层(换手率轻微上升)",
        "极高层(换手率明显上升)",
    )


if __name__ == "__main__":
    factor_cli_main(config_cls=TurnoverDecayRateLayerConfig, factor_calculator=None)
