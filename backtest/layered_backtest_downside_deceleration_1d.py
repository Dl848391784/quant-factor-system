#!/usr/bin/env python3
"""
下跌减速因子分层回测

遵循 PROJECT.md 回测脚本规范：
- 使用 LayeredBacktestConfig（ClassVar 薄声明，遵循 M5）
- 预计算因子: factor_calculator=None（遵循 M6 Sequence）
- 入口使用 factor_cli_main()（遵循 M8）

因子定义：
- downside_deceleration = max(0, return_5d(t) - return_5d(t-5)) 仅当前期下跌
- 含义: 下跌股票跌幅收窄幅度
- 遵循 H5: IC方向不预判，由数据决定

v2.35: P5-补充 二阶导数企稳信号因子
"""

import sys

from backtest.common.backtest_cli import factor_cli_main
from backtest.common.layered_backtest_config import LayeredBacktestConfig


class DownsideDecelerationBacktest(LayeredBacktestConfig):
    """下跌减速因子分层回测配置（遵循 M5 ClassVar 薄声明）"""

    factor_name: str = "downside_deceleration"
    factor_col: str = "downside_deceleration"
    period: str = "1d"
    factor_calculator = None  # 预计算因子，直接从 factor_ic_data.json.gz 读取

    # 分层标签（遵循 M6 Sequence）
    layer_labels: tuple[str, ...] = (
        "极低层(减速最小)",
        "偏低层(减速较小)",
        "正常层(减速适中)",
        "偏高层(减速较大)",
        "极高层(减速最大)",
    )


def main() -> None:
    factor_cli_main(DownsideDecelerationBacktest)


if __name__ == "__main__":
    main()
