#!/usr/bin/env python3
"""
换手率突增差分因子分层回测脚本

因子定义：
- turnover_surge_delta = turnover_surge(T) - turnover_surge(T-1)
- 含义：换手率偏离程度的变化量，正值=偏离加剧，负值=偏离收敛
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
from data_fetchers.factor_calculator import calculate_turnover_surge_delta


class TurnoverSurgeDeltaLayerConfig(LayerConfigBase):
    """换手率突增差分因子分层配置（薄声明）"""

    factor_name: ClassVar[str] = "turnover_surge_delta"

    layer_names: ClassVar[Sequence[str]] = (
        "lowest",
        "lower",
        "normal",
        "higher",
        "highest",
    )

    layer_descriptions: ClassVar[Sequence[str]] = (
        "极低层(换手率偏离大幅收敛)",
        "偏低层(换手率偏离略有收敛)",
        "正常层(换手率偏离变化接近零)",
        "偏高层(换手率偏离略有扩大)",
        "极高层(换手率偏离大幅扩大)",
    )


if __name__ == "__main__":
    factor_cli_main(
        config_cls=TurnoverSurgeDeltaLayerConfig,
        factor_calculator=calculate_turnover_surge_delta,
    )
