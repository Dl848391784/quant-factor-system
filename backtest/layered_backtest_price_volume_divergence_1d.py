#!/usr/bin/env python3
"""
价跌量缩背离因子分层回测脚本

因子定义：
- price_volume_divergence: -price_ret_5d * max(0, 1 - vol_ratio)
- 含义: 价跌+缩量=背离止跌信号
- v2.35: P5 新增因子（确认信号角色，design.md §2.5）
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


class PriceVolumeDivergenceLayerConfig(LayerConfigBase):
    """价跌量缩背离因子分层配置

    薄声明：仅定义因子名称与分层命名，逻辑完全下沉基类。
    """

    factor_name: ClassVar[str] = "price_volume_divergence"

    layer_names: ClassVar[Sequence[str]] = (
        "lowest",
        "lower",
        "normal",
        "higher",
        "highest",
    )

    layer_descriptions: ClassVar[Sequence[str]] = (
        "极低层(无背离信号)",
        "偏低层(弱背离)",
        "正常层(背离适中)",
        "偏高层(较强背离)",
        "极高层(强背离信号)",
    )


if __name__ == "__main__":
    factor_cli_main(config_cls=PriceVolumeDivergenceLayerConfig, factor_calculator=None)
