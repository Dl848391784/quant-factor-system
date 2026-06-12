#!/usr/bin/env python3
"""
量价齐升强度因子分层回测脚本

因子定义：
- 公式: volume_price_strength = (close - open) / open × turnover_surge
- 含义: 上涨+放量=强势信号，量价协同程度

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
from data_fetchers.factor_calculator import calculate_volume_price_strength


class VolumePriceStrengthLayerConfig(LayerConfigBase):
    """量价齐升强度因子分层配置

    薄声明：仅定义因子名称与分层命名，逻辑完全下沉基类。
    """

    factor_name: ClassVar[str] = "volume_price_strength"

    layer_names: ClassVar[Sequence[str]] = ("lowest", "lower", "normal", "higher", "highest")

    layer_descriptions: ClassVar[Sequence[str]] = (
        "极低层(量价齐升最弱)",
        "偏低层(量价齐升偏弱)",
        "正常层(量价齐升适中)",
        "偏高层(量价齐升偏强)",
        "极高层(量价齐升最强)",
    )


if __name__ == "__main__":
    factor_cli_main(config_cls=VolumePriceStrengthLayerConfig, factor_calculator=calculate_volume_price_strength)
