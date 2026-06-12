#!/usr/bin/env python3
"""
MA5偏离度因子分层回测脚本

因子定义：
- ma5_deviation = (close - MA5) / MA5
- 含义：股价偏离5日均线程度，正值=高于均线，负值=低于均线
- 预计算因子，需传入 factor_calculator

遵循 MODULE.md 薄声明规范：
- Config 类仅声明 ClassVar 元数据，逻辑完全下沉基类
- factor_direction 由 IC 文件自动派生（遵循 M15）
- layer_descriptions 使用 percentile 相对语义（遵循 Pitfall #32）

作者: 云瑶
创建日期: 2026-06-12
"""

from collections.abc import Sequence
from typing import ClassVar

from backtest.common.factor_cli import factor_cli_main
from backtest.common.layered_backtest_runner import LayerConfigBase
from data_fetchers.factor_calculator import calculate_ma5_deviation


class MA5DeviationLayerConfig(LayerConfigBase):
    """MA5偏离度因子分层配置（薄声明）"""

    factor_name: ClassVar[str] = "ma5_deviation"

    layer_names: ClassVar[Sequence[str]] = (
        "lowest",
        "lower",
        "normal",
        "higher",
        "highest",
    )

    layer_descriptions: ClassVar[Sequence[str]] = (
        "极低层(远低于均线，深度超卖)",
        "偏低层(略低于均线)",
        "正常层(接近均线)",
        "偏高层(略高于均线)",
        "极高层(远高于均线，深度超买)",
    )


if __name__ == "__main__":
    factor_cli_main(
        config_cls=MA5DeviationLayerConfig,
        factor_calculator=calculate_ma5_deviation,
    )
