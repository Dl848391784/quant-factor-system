#!/usr/bin/env python3
"""
振幅收敛因子分层回测脚本

因子定义：
- amplitude_compression: mean(amplitude, 5d) / mean(amplitude, 10d)
- 含义: 近期波动幅度相对历史变化
- v2.35: P5-补充因子（确认信号角色，企稳信号二阶维度）
- 因子已在 factor_generator 预计算，factor_calculator=None

遵循 backtest/MODULE.md M5(ClassVar薄声明)/M6(Sequence)/M8(factor_cli_main入口)
"""

from backtest.common.factor_cli import LayerConfigBase, factor_cli_main


class AmplitudeCompressionLayerConfig(LayerConfigBase):
    """振幅收敛因子分层回测配置"""

    factor_name: str = "amplitude_compression"
    layer_names: tuple[str, ...] = (
        "L1_0-20",
        "L2_20-40",
        "L3_40-60",
        "L4_60-80",
        "L5_80-100",
    )


if __name__ == "__main__":
    factor_cli_main(config_cls=AmplitudeCompressionLayerConfig, factor_calculator=None)
