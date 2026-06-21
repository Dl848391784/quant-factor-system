#!/usr/bin/env python3
"""
下影线比因子分层回测脚本

因子定义：
- lower_shadow_ratio: max(0, min(open, close) - low) / (high - low)
- 含义: 下影线长=低位承接
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


class LowerShadowRatioLayerConfig(LayerConfigBase):
    """下影线比因子分层配置

    薄声明：仅定义因子名称与分层命名，逻辑完全下沉基类。
    """

    factor_name: ClassVar[str] = "lower_shadow_ratio"

    layer_names: ClassVar[Sequence[str]] = (
        "lowest",
        "lower",
        "normal",
        "higher",
        "highest",
    )

    layer_descriptions: ClassVar[Sequence[str]] = (
        "极低层(无下影线)",
        "偏低层(下影线短)",
        "正常层(下影线适中)",
        "偏高层(下影线较长)",
        "极高层(下影线极长)",
    )


if __name__ == "__main__":
    factor_cli_main(config_cls=LowerShadowRatioLayerConfig, factor_calculator=None)
