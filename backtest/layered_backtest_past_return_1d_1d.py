#!/usr/bin/env python3
"""
过去1日收益因子分层回测脚本

因子定义：
- 含义: 过去1日涨跌幅（相对于昨日收盘价）

命名说明：
- past_return_1d = 过去1日收益（历史因子，与 forward_return_1d 对称）

分层模式：percentile 5层（每层约20%）

因子元数据派生机制（基类 LayerConfigBase）：
- factor_col_resolved: 从 factor_col ClassVar 洒生，默认=factor_name
- factor_direction: 从 ic_source IC 文件加载，ic_mean < 0 为 negative
- n_layers: 由 len(layer_names) 洒生
- layer_names_dict: 优先使用 layer_descriptions，否则回退 layer_names

版本历史：
- v1.0 (2026-06-04): 初始版本
- v1.1 (2026-06-04): 移除 factor_calculator 参数（遵循数据层架构原则，因子已预计算）
"""

from collections.abc import Sequence
from typing import ClassVar

from backtest.common.factor_cli import factor_cli_main
from backtest.common.layered_backtest_runner import LayerConfigBase


class PastReturn1dLayerConfig(LayerConfigBase):
    """过去1日收益因子分层配置

    薄声明：因子元数据集中在 ClassVar，逻辑完全下沉基类。
    """

    factor_name: ClassVar[str] = "past_return_1d"

    layer_names: ClassVar[Sequence[str]] = ("lowest", "lower", "normal", "higher", "highest")

    layer_descriptions: ClassVar[Sequence[str]] = (
        "极低层(当日跌幅最大)",
        "偏低层(当日小幅下跌)",
        "正常层(当日变化不大)",
        "偏高层(当日小幅上涨)",
        "极高层(当日涨幅最大)",
    )


if __name__ == "__main__":
    # 预计算因子不传 factor_calculator（遵循 data-layer-architecture-principle.md Section 5）
    factor_cli_main(PastReturn1dLayerConfig)
