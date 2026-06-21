#!/usr/bin/env python3
"""
换手率衰减因子分层回测脚本

因子定义：
- turnover_decay_rate: turnover_rate / mean(turnover_rate, 5d)
- 含义: 当日换手率相对近期均值比值
- v2.35: P5-补充因子（确认信号角色，企稳信号二阶维度）
- 因子已在 factor_generator 预计算，factor_calculator=None

遵循 backtest/MODULE.md M5(ClassVar薄声明)/M6(Sequence)/M8(factor_cli_main入口)
"""

from backtest.common.factor_cli import LayerConfigBase, factor_cli_main


class TurnoverDecayRateLayerConfig(LayerConfigBase):
    """换手率衰减因子分层回测配置"""

    factor_name: str = "turnover_decay_rate"
    layer_names: tuple[str, ...] = (
        "L1_0-20",
        "L2_20-40",
        "L3_40-60",
        "L4_60-80",
        "L5_80-100",
    )


if __name__ == "__main__":
    factor_cli_main(config_cls=TurnoverDecayRateLayerConfig, factor_calculator=None)
