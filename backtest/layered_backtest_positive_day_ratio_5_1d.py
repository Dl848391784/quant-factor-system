#!/usr/bin/env python3
"""
近5日阳线比例因子分层回测脚本

因子定义：
- 公式: positive_day_ratio_5 = count(close > prev_close, 最近5日) / 5
- 含义: 持续上涨天数占比，趋势连续性指标

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
from data_fetchers.factor_calculator import calculate_positive_day_ratio_5


class PositiveDayRatio5LayerConfig(LayerConfigBase):
    """近5日阳线比例因子分层配置

    薄声明：仅定义因子名称与分层命名，逻辑完全下沉基类。
    """

    factor_name: ClassVar[str] = "positive_day_ratio_5"

    layer_names: ClassVar[Sequence[str]] = ("lowest", "lower", "normal", "higher", "highest")

    layer_descriptions: ClassVar[Sequence[str]] = (
        "极低层(阳线比例极低)",
        "偏低层(阳线比例偏低)",
        "正常层(阳线比例适中)",
        "偏高层(阳线比例偏高)",
        "极高层(阳线比例极高)",
    )


if __name__ == "__main__":
    factor_cli_main(config_cls=PositiveDayRatio5LayerConfig, factor_calculator=calculate_positive_day_ratio_5)
