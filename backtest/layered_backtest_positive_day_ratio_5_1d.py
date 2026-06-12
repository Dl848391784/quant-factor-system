#!/usr/bin/env python3
"""
5日阳线占比因子分层回测脚本

因子定义：
- positive_day_ratio_5 = 近5日阳线天数 / 5
- 含义：近期上涨频率，高值=持续上涨，低值=持续下跌
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
from data_fetchers.factor_calculator import calculate_positive_day_ratio_5


class PositiveDayRatio5LayerConfig(LayerConfigBase):
    """5日阳线占比因子分层配置（薄声明）"""

    factor_name: ClassVar[str] = "positive_day_ratio_5"

    layer_names: ClassVar[Sequence[str]] = (
        "lowest",
        "lower",
        "normal",
        "higher",
        "highest",
    )

    layer_descriptions: ClassVar[Sequence[str]] = (
        "极低层(近5日持续下跌)",
        "偏低层(近5日多数下跌)",
        "正常层(涨跌各半)",
        "偏高层(近5日多数上涨)",
        "极高层(近5日持续上涨)",
    )


if __name__ == "__main__":
    factor_cli_main(
        config_cls=PositiveDayRatio5LayerConfig,
        factor_calculator=calculate_positive_day_ratio_5,
    )
