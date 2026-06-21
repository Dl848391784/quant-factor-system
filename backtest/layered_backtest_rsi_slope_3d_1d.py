#!/usr/bin/env python3
"""
RSI 3日斜率因子分层回测脚本

因子定义：
- rsi_slope_3d: RSI(6)当前值 - RSI(6)3日前值
- 含义: RSI拐头=卖压减弱
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


class RsiSlope3dLayerConfig(LayerConfigBase):
    """RSI 3日斜率因子分层配置

    薄声明：仅定义因子名称与分层命名，逻辑完全下沉基类。
    """

    factor_name: ClassVar[str] = "rsi_slope_3d"

    layer_names: ClassVar[Sequence[str]] = (
        "lowest",
        "lower",
        "normal",
        "higher",
        "highest",
    )

    layer_descriptions: ClassVar[Sequence[str]] = (
        "极低层(RSI急跌)",
        "偏低层(RSI缓跌)",
        "正常层(RSI走平)",
        "偏高层(RSI缓升)",
        "极高层(RSI急升)",
    )


if __name__ == "__main__":
    factor_cli_main(config_cls=RsiSlope3dLayerConfig, factor_calculator=None)
