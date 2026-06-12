#!/usr/bin/env python3
"""
行业5日动量因子分层回测脚本

因子定义：
- 公式: industry_momentum_5d = 按(行业,日期)分组 → mean(past_return_1d) → 5日滚动均值
- 含义: 行业整体5日趋势方向，方向性因子
- 实测结论: 行业层面IC=+0.026（正值），方向性信号存在于行业而非个股

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
from data_fetchers.factor_calculator import calculate_industry_momentum_5d


class IndustryMomentum5dLayerConfig(LayerConfigBase):
    """行业5日动量因子分层配置

    薄声明：仅定义因子名称与分层命名，逻辑完全下沉基类。
    """

    factor_name: ClassVar[str] = "industry_momentum_5d"

    layer_names: ClassVar[Sequence[str]] = ("lowest", "lower", "normal", "higher", "highest")

    layer_descriptions: ClassVar[Sequence[str]] = (
        "极低层(行业动量最弱)",
        "偏低层(行业动量较弱)",
        "正常层(行业动量适中)",
        "偏高层(行业动量较强)",
        "极高层(行业动量最强)",
    )


if __name__ == "__main__":
    factor_cli_main(
        config_cls=IndustryMomentum5dLayerConfig,
        factor_calculator=calculate_industry_momentum_5d,
    )
