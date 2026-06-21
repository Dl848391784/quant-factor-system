#!/usr/bin/env python3
"""
价格区间收敛因子分层回测

遵循 PROJECT.md 回测脚本规范：
- 使用 LayeredBacktestConfig（ClassVar 薄声明，遵循 M5）
- 预计算因子: factor_calculator=None（遵循 M6 Sequence）
- 入口使用 factor_cli_main()（遵循 M8）

因子定义：
- range_compression = 5日价格区间 / 10日价格区间
- 含义: 价格区间收敛，<1=波动收敛
- 遵循 H5: IC方向不预判，由数据决定

v2.35: P5-补充 二阶导数企稳信号因子
"""

import sys

from backtest.common.backtest_cli import factor_cli_main
from backtest.common.layered_backtest_config import LayeredBacktestConfig


class RangeCompressionBacktest(LayeredBacktestConfig):
    """价格区间收敛因子分层回测配置（遵循 M5 ClassVar 薄声明）"""

    factor_name: str = "range_compression"
    factor_col: str = "range_compression"
    period: str = "1d"
    factor_calculator = None  # 预计算因子，直接从 factor_ic_data.json.gz 读取

    # 分层标签（遵循 M6 Sequence）
    layer_labels: tuple[str, ...] = (
        "极低层(区间发散最大)",
        "偏低层(区间发散较小)",
        "正常层(区间适中)",
        "偏高层(区间收敛较小)",
        "极高层(区间收敛最大)",
    )


def main() -> None:
    factor_cli_main(RangeCompressionBacktest)


if __name__ == "__main__":
    main()
