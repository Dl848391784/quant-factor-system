#!/usr/bin/env python3
"""
振幅因子分层回测脚本

因子定义：
- 含义: 过去N日价格波动幅度

分层模式：percentile 5层（每层约20%）

注：因子元数据派生机制（factor_direction / n_layers / long_short_layers）
为基类 LayerConfigBase 通用职责，详见基类 docstring。
"""

from collections.abc import Sequence
from typing import ClassVar

from backtest.common.factor_cli import factor_cli_main
from backtest.common.layered_backtest_runner import LayerConfigBase
from data_fetchers.factor_calculator import calculate_amplitude


class AmplitudeLayerConfig(LayerConfigBase):
    """振幅因子分层配置

    瘦声明（minimal declaration）：仅定义因子名称与分层命名，逻辑完全下沉基类。
    """

    factor_name: ClassVar[str] = "amplitude"

    layer_names: ClassVar[Sequence[str]] = ("lowest", "lower", "normal", "higher", "highest")

    layer_descriptions: ClassVar[Sequence[str]] = (
        "极低层(振幅最小)",
        "偏低层(振幅较小)",
        "正常层(振幅适中)",
        "偏高层(振幅较大)",
        "极高层(振幅最大)",
    )


if __name__ == "__main__":
    factor_cli_main(config_cls=AmplitudeLayerConfig, factor_calculator=calculate_amplitude)
