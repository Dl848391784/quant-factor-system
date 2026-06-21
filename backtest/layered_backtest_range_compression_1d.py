#!/usr/bin/env python3
"""
价格区间收敛因子分层回测脚本

因子定义：
- range_compression: (rolling_high_5d - rolling_low_5d) / (rolling_high_10d - rolling_low_10d)
- 含义: 近期价格波动范围相对历史的变化, <1=波动收敛(企稳)
- v2.35: P5-补充新增因子（企稳信号，design.md §2.5 二阶导数）
- 因子已在 factor_generator 预计算，无需自定义计算函数
"""

from __future__ import annotations

from backtest.common.factor_cli import factor_cli_main
from backtest.common.layer_config_base import LayerConfigBase
from backtest.common.stabilization_filter_config import StabilizationFilterConfig


class RangeCompressionConfig(LayerConfigBase):
    """价格区间收敛因子分层回测配置

    预计算因子: factor_calculator=None
    因子已在 factor_ic_data.json.gz 中
    """

    factor_col: str = "range_compression"
    factor_name: str = "价格区间收敛"
    factor_calculator: None = None  # 预计算因子，无需运行时计算

    # ── 分层参数 ──
    n_layers: int = 5
    layer_names: tuple[str, ...] = ("L1", "L2", "L3", "L4", "L5")

    # ── 稳定性筛选 ── (遵循 PROJECT.md M7)
    stabilization_filter: StabilizationFilterConfig = StabilizationFilterConfig()


def main():
    """脚本入口"""
    config = RangeCompressionConfig()
    factor_cli_main(config)


if __name__ == "__main__":
    main()
