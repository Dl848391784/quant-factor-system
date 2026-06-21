#!/usr/bin/env python3
"""interaction_amplitude 因子分层回测脚本

因子定义:
- interaction_amplitude = -z_cs(return_3d) × z_cs(amplitude)
- 含义: 弱势(跌得多) × 高振幅 = 反弹型信号; 强势 × 高振幅 = 高位风险
- 期望 IC: +0.020（design.md feat_interaction_factors §3 实证）

分层模式: percentile 5层（每层约20%）。
- 选高值(highest) = 反弹/平稳型 → 期望 layer_5 收益最高
- 选低值(lowest) = 阴跌/高位风险型 → 期望 layer_1 收益最低
- 与现有 IC<0 因子方向相反（design.md §2.1 决策矩阵）

注: 因子元数据派生机制（factor_direction / n_layers / long_short_layers）
为基类 LayerConfigBase 通用职责，详见基类 docstring。

设计依据: designs/feat_interaction_factors.md（条件因子方向方案 B）
"""

from collections.abc import Sequence
from typing import ClassVar

from backtest.common.factor_cli import factor_cli_main
from backtest.common.layered_backtest_runner import LayerConfigBase
from data_fetchers.factor_calculator import calculate_interaction_amplitude


class InteractionAmplitudeLayerConfig(LayerConfigBase):
    """interaction_amplitude 交互因子分层配置（条件因子方向方案 B）"""

    factor_name: ClassVar[str] = "interaction_amplitude"

    layer_names: ClassVar[Sequence[str]] = ("lowest", "lower", "normal", "higher", "highest")

    layer_descriptions: ClassVar[Sequence[str]] = (
        "极低层(强势×高振幅 高位风险型)",
        "偏低层",
        "正常层",
        "偏高层",
        "极高层(弱势×高振幅 反弹型)",
    )


if __name__ == "__main__":
    factor_cli_main(config_cls=InteractionAmplitudeLayerConfig, factor_calculator=calculate_interaction_amplitude)
