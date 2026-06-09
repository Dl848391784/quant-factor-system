#!/usr/bin/env python3
"""
RSI因子分层回测脚本

因子定义：
- 含义: 相对强弱指数

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
from data_fetchers.factor_calculator import calculate_rsi_df


class RsiLayerConfig(LayerConfigBase):
    """RSI因子分层配置

    薄声明：仅定义因子名称与分层命名，逻辑完全下沉基类。
    """

    factor_name: ClassVar[str] = "rsi"

    layer_names: ClassVar[Sequence[str]] = (
        "oversold",
        "low",
        "normal",
        "high",
        "overbought",
    )

    layer_descriptions: ClassVar[Sequence[str]] = (
        "极低层(RSI极低)",
        "偏低层(RSI偏低)",
        "正常层(RSI适中)",
        "偏高层(RSI偏高)",
        "极高层(RSI极高)",
    )


if __name__ == "__main__":
    factor_cli_main(config_cls=RsiLayerConfig, factor_calculator=calculate_rsi_df)
