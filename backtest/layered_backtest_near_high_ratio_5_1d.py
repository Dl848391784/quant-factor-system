#!/usr/bin/env python3
"""
5日近高比率因子分层回测脚本

因子定义：
- near_high_ratio_5 = close / max(high_5d)
- 含义：当前价距5日最高价的接近程度，1=触及最高价，低值=远离最高价
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
from data_fetchers.factor_calculator import calculate_near_high_ratio_5


class NearHighRatio5LayerConfig(LayerConfigBase):
    """5日近高比率因子分层配置（薄声明）"""

    factor_name: ClassVar[str] = "near_high_ratio_5"

    layer_names: ClassVar[Sequence[str]] = (
        "lowest",
        "lower",
        "normal",
        "higher",
        "highest",
    )

    layer_descriptions: ClassVar[Sequence[str]] = (
        "极低层(远低于5日最高价)",
        "偏低层(略低于5日最高价)",
        "正常层(中等接近度)",
        "偏高层(接近5日最高价)",
        "极高层(触及或超越5日最高价)",
    )


if __name__ == "__main__":
    factor_cli_main(
        config_cls=NearHighRatio5LayerConfig,
        factor_calculator=calculate_near_high_ratio_5,
    )
