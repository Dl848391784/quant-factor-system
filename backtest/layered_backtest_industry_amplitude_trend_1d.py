#!/usr/bin/env python3
"""
行业振幅趋势因子分层回测脚本

因子定义：
- 公式: industry_amplitude_trend = amplitude_avg(t) / amplitude_avg(t-1) - 1
- 含义: 行业振幅变化趋势，方向性因子
- 遵循 H5: IC方向不预判，由数据决定

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
from data_fetchers.factor_calculator import calculate_industry_amplitude_trend


class IndustryAmplitudeTrendLayerConfig(LayerConfigBase):
    """行业振幅趋势因子分层配置

    薄声明：仅定义因子名称与分层命名，逻辑完全下沉基类。
    """

    factor_name: ClassVar[str] = "industry_amplitude_trend"

    layer_names: ClassVar[Sequence[str]] = ("lowest", "lower", "normal", "higher", "highest")

    layer_descriptions: ClassVar[Sequence[str]] = (
        "极低层(行业振幅趋势最弱)",
        "偏低层(行业振幅趋势较弱)",
        "正常层(行业振幅趋势适中)",
        "偏高层(行业振幅趋势较强)",
        "极高层(行业振幅趋势最强)",
    )


if __name__ == "__main__":
    factor_cli_main(
        config_cls=IndustryAmplitudeTrendLayerConfig,
        factor_calculator=calculate_industry_amplitude_trend,
    )
