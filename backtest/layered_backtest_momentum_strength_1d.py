#!/usr/bin/env python3
"""
动量强度因子分层回测脚本

因子定义：
- 公式: momentum_strength = return_5d / std(return_1d, 5日)
- 含义: 衡量5日累计涨幅相对于日收益率波动率的比率
  - 高值 → 持续上涨趋势（动量强，波动小）
  - 低值 → 震荡或下跌（动量弱，波动大）

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
from data_fetchers.factor_calculator import calculate_momentum_strength


class MomentumStrengthLayerConfig(LayerConfigBase):
    """动量强度因子分层配置

    薄声明：仅定义因子名称与分层命名，逻辑完全下沉基类。
    """

    factor_name: ClassVar[str] = "momentum_strength"

    layer_names: ClassVar[Sequence[str]] = ("lowest", "lower", "normal", "higher", "highest")

    layer_descriptions: ClassVar[Sequence[str]] = (
        "极低层(动量最弱)",
        "偏低层(动量较弱)",
        "正常层(动量适中)",
        "偏高层(动量较强)",
        "极高层(动量最强)",
    )


if __name__ == "__main__":
    factor_cli_main(
        config_cls=MomentumStrengthLayerConfig,
        factor_calculator=calculate_momentum_strength,
    )
