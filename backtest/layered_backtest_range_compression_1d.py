#!/usr/bin/env python3
"""
价格区间收敛因子分层回测脚本

因子定义：
- range_compression: (rolling_high_5d - rolling_low_5d) / (rolling_high_10d - rolling_low_10d)
- 含义: 近5日价格区间/近10日价格区间，<1=区间收敛=企稳信号
- v2.35: P5-补充 二阶导数企稳信号因子（波动收敛维度，design.md §2）
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


class RangeCompressionLayerConfig(LayerConfigBase):
    """价格区间收敛因子分层配置

    薄声明：仅定义因子名称与分层命名，逻辑完全下沉基类。
    """

    factor_name: ClassVar[str] = "range_compression"

    layer_names: ClassVar[Sequence[str]] = (
        "lowest",
        "lower",
        "normal",
        "higher",
        "highest",
    )

    layer_descriptions: ClassVar[Sequence[str]] = (
        "极低层(区间收敛最强)",
        "偏低层(区间收敛)",
        "正常层(区间适中)",
        "偏高层(区间扩大)",
        "极高层(区间急剧扩大)",
    )


if __name__ == "__main__":
    factor_cli_main(config_cls=RangeCompressionLayerConfig, factor_calculator=None)
