#!/usr/bin/env python3
"""
振幅差分因子分层回测脚本

因子定义：
- amplitude_delta = amplitude(T) - amplitude(T-1)
- 含义：当日振幅较前日的变化量，正值=波动扩大，负值=波动收敛
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
from data_fetchers.factor_calculator import calculate_amplitude_delta


class AmplitudeDeltaLayerConfig(LayerConfigBase):
    """振幅差分因子分层配置（薄声明）"""

    factor_name: ClassVar[str] = "amplitude_delta"

    layer_names: ClassVar[Sequence[str]] = (
        "lowest",
        "lower",
        "normal",
        "higher",
        "highest",
    )

    layer_descriptions: ClassVar[Sequence[str]] = (
        "极低层(振幅大幅收敛，波动性下降)",
        "偏低层(振幅略有收敛)",
        "正常层(振幅变化接近零)",
        "偏高层(振幅略有扩大)",
        "极高层(振幅大幅扩大，波动性上升)",
    )


if __name__ == "__main__":
    factor_cli_main(
        config_cls=AmplitudeDeltaLayerConfig,
        factor_calculator=calculate_amplitude_delta,
    )
