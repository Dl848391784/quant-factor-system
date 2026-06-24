#!/usr/bin/env python3
"""interaction_amp_compression__ret3d_neg 因子分层回测脚本 (v2.48, 2026-06-24)

因子定义 (ReLU 切半轴, 纯数学命名):
- interaction_amp_compression__ret3d_neg = min(z_cs(return_3d), 0) × z_cs(amplitude_compression)

分层模式: percentile 5层 (每层约20%).
factor_direction 由 _load_ic_meta 从 factor_ic/result/ 自动派生,
long_layers / short_layers 配置只描述"哪些 Layer 做多/做空",
禁止注释中加叙事标签 (反弹/超跌/见顶 等), 遵循 backtest/MODULE.md v2.5 M17.

设计依据:
- designs/feat_factor_definition_destigmatization_v1.md v1.2
- 承接 v2.48 重构: 旧 9 单边公式 → 27 ReLU 变体, 方向由 IC 数据驱动
"""

from collections.abc import Sequence
from typing import ClassVar

from backtest.common.factor_cli import factor_cli_main
from backtest.common.layered_backtest_runner import LayerConfigBase
from data_fetchers.factor_calculator import calculate_interaction_amp_compression__ret3d_neg


class InteractionAmpCompressionRet3dNegLayerConfig(LayerConfigBase):
    """interaction_amp_compression__ret3d_neg 分层配置

    因子方向: 由基类 _load_ic_meta 从 IC 文件自动派生 (M15)
    Layer 行为 (与 factor_direction 联动):
    - factor_direction='negative' 时: long=[1,2], short=[3,4]
    - factor_direction='positive' 时: long=[4,5], short=[1,2]
    """

    factor_name: ClassVar[str] = "interaction_amp_compression__ret3d_neg"

    layer_names: ClassVar[Sequence[str]] = ("lowest", "lower", "normal", "higher", "highest")

    layer_descriptions: ClassVar[Sequence[str]] = (
        "极低层 (factor 值最低 20%)",
        "偏低层",
        "正常层",
        "偏高层",
        "极高层 (factor 值最高 20%)",
    )


if __name__ == "__main__":
    factor_cli_main(
        config_cls=InteractionAmpCompressionRet3dNegLayerConfig,
        factor_calculator=calculate_interaction_amp_compression__ret3d_neg,
    )
