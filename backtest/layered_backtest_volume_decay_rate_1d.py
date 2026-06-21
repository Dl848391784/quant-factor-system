#!/usr/bin/env python3
"""
量能衰减因子分层回测

遵循 PROJECT.md 回测脚本规范：
- 使用 LayeredBacktestConfig（ClassVar 薄声明，遵循 M5）
- 预计算因子: factor_calculator=None（遵循 M6 Sequence）
- 入口使用 factor_cli_main()（遵循 M8）

因子定义：
- volume_decay_rate = 5日均量 / 10日均量
- 含义: 量能衰减，<1=卖盘衰竭
- 遵循 H5: IC方向不预判，由数据决定

v2.35: P5-补充 二阶导数企稳信号因子
"""

import sys

from backtest.common.backtest_cli import factor_cli_main
from backtest.common.layered_backtest_config import LayeredBacktestConfig


class VolumeDecayRateBacktest(LayeredBacktestConfig):
    """量能衰减因子分层回测配置（遵循 M5 ClassVar 薄声明）"""

    factor_name: str = "volume_decay_rate"
    factor_col: str = "volume_decay_rate"
    period: str = "1d"
    factor_calculator = None  # 预计算因子，直接从 factor_ic_data.json.gz 读取

    # 分层标签（遵循 M6 Sequence）
    layer_labels: tuple[str, ...] = (
        "极低层(量能放大最大)",
        "偏低层(量能放大较小)",
        "正常层(量比适中)",
        "偏高层(量能衰减较小)",
        "极高层(量能衰减最大)",
    )


def main() -> None:
    factor_cli_main(VolumeDecayRateBacktest)


if __name__ == "__main__":
    main()
