#!/usr/bin/env python3
"""
3日收益因子分层回测脚本

因子定义：
- 含义: 过去3日累计涨跌幅

分层模式：percentile 5层（每层约20%）

因子元数据派生机制（基类 LayerConfigBase）：
- factor_col_resolved: 从 factor_col ClassVar 派生，默认=factor_name
- factor_direction: 从 ic_source IC 文件加载，ic_mean < 0 为 negative
- n_layers: 由 len(layer_names) 派生
- layer_names_dict: 优先使用 layer_descriptions，否则回退 layer_names
"""

from collections.abc import Sequence
from typing import ClassVar

from backtest.common.factor_cli import factor_cli_main
from backtest.common.layered_backtest_runner import LayerConfigBase
from data_fetchers.factor_calculator import calculate_return_3d


class Return3dLayerConfig(LayerConfigBase):
    """3日收益因子分层配置

    薄声明：因子元数据集中在 ClassVar，逻辑完全下沉基类。
    """

    factor_name: ClassVar[str] = "return_3d"

    layer_names: ClassVar[Sequence[str]] = ("lowest", "lower", "normal", "higher", "highest")

    layer_descriptions: ClassVar[Sequence[str]] = (
        "极低层(3日跌幅最大)",
        "偏低层(3日小幅下跌)",
        "正常层(3日变化不大)",
        "偏高层(3日小幅上涨)",
        "极高层(3日涨幅最大)",
    )


if __name__ == "__main__":
    factor_cli_main(Return3dLayerConfig, calculate_return_3d)
