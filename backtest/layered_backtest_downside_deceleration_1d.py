#!/usr/bin/env python3
"""
下跌减速因子分层回测脚本

因子定义（第一性原理推导，公理4推论——企稳=二阶导数）：
- downside_deceleration: max(0, return_5d(t) - return_5d(t-5)) 仅当 return_5d(t-5)<0
- 物理含义: 下跌股票的跌幅收窄幅度（更纯粹的企稳信号）
- v2.35: P5-补充 二阶导数企稳信号因子（价格加速度维度，design.md §1）
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


class DownsideDecelerationLayerConfig(LayerConfigBase):
    """下跌减速因子分层配置

    薄声明：仅定义因子名称与分层命名，逻辑完全下沉基类。
    """

    factor_name: ClassVar[str] = "downside_deceleration"

    layer_names: ClassVar[Sequence[str]] = (
        "lowest",
        "lower",
        "normal",
        "higher",
        "highest",
    )

    layer_descriptions: ClassVar[Sequence[str]] = (
        "极低层(跌幅仍在扩大)",
        "偏低层(跌幅微收)",
        "正常层(减速适中)",
        "偏高层(跌幅明显收窄)",
        "极高层(跌幅急收或转正)",
    )


if __name__ == "__main__":
    factor_cli_main(config_cls=DownsideDecelerationLayerConfig, factor_calculator=None)
