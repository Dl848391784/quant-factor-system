#!/usr/bin/env python3
"""
5日均线偏离度因子分层回测脚本

因子定义：
- 公式: ma5_deviation = (close - MA5) / MA5
- 含义: 收盘价相对5日均线偏离程度，在均线之上=多头区域

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
from data_fetchers.factor_calculator import calculate_ma5_deviation


class Ma5DeviationLayerConfig(LayerConfigBase):
    """5日均线偏离度因子分层配置

    薄声明：仅定义因子名称与分层命名，逻辑完全下沉基类。
    """

    factor_name: ClassVar[str] = "ma5_deviation"

    layer_names: ClassVar[Sequence[str]] = ("lowest", "lower", "normal", "higher", "highest")

    layer_descriptions: ClassVar[Sequence[str]] = (
        "极低层(偏离度极低，远低于均线)",
        "偏低层(偏离度偏低，略低于均线)",
        "正常层(偏离度适中，接近均线)",
        "偏高层(偏离度偏高，略高于均线)",
        "极高层(偏离度极高，远高于均线)",
    )


if __name__ == "__main__":
    factor_cli_main(config_cls=Ma5DeviationLayerConfig, factor_calculator=calculate_ma5_deviation)
