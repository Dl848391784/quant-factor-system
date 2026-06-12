#!/usr/bin/env python3
"""
近5日高低位置因子分层回测脚本

因子定义：
- 公式: near_high_ratio_5 = (close - min(close,5日)) / (max(close,5日) - min(close,5日))
- 含义: 收盘价在近5日价格区间中的相对位置，越高越接近5日高点

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
from data_fetchers.factor_calculator import calculate_near_high_ratio_5


class NearHighRatio5LayerConfig(LayerConfigBase):
    """近5日高低位置因子分层配置

    薄声明：仅定义因子名称与分层命名，逻辑完全下沉基类。
    """

    factor_name: ClassVar[str] = "near_high_ratio_5"

    layer_names: ClassVar[Sequence[str]] = ("lowest", "lower", "normal", "higher", "highest")

    layer_descriptions: ClassVar[Sequence[str]] = (
        "极低层(接近5日低点)",
        "偏低层(偏低位置)",
        "正常层(中间位置)",
        "偏高层(偏高位置)",
        "极高层(接近5日高点)",
    )


if __name__ == "__main__":
    factor_cli_main(config_cls=NearHighRatio5LayerConfig, factor_calculator=calculate_near_high_ratio_5)
