#!/usr/bin/env python3
"""
尾盘价格趋势斜率因子分层回测脚本

因子定义：
- 线性回归：对 prices 数组（13根5分钟K线收盘价）做回归
- 百分比斜率：factor_value = slope / mean_price

分层模式：percentile 5层（每层约20%）

因子元数据派生机制（基类 LayerConfigBase）：
- factor_direction: 从 ic_source IC 文件加载，ic_mean < 0 为 negative
- n_layers: 由 len(layer_names) 派生
- long_layers/short_layers: 由 n_layers 和 factor_direction 派生

数据依赖：
- factor_ic_data.json.gz（主数据源）
- tail_trading_data.json.gz（尾盘5分钟K线数据）

作者: 云瑶
创建日期: 2026-06-02
版本历史:
  v1.0 (2026-06-02): 初始版本，实现尾盘价格趋势斜率因子分层回测
"""

import sys
from collections.abc import Sequence
from pathlib import Path
from typing import ClassVar


# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from backtest.common.factor_cli import factor_cli_main
from backtest.common.layered_backtest_runner import LayerConfigBase
from factor_ic.ic_tail_price_slope_1d import calculate_tail_price_slope


class TailPriceSlopeLayerConfig(LayerConfigBase):
    """尾盘价格趋势斜率因子分层配置

    薄声明：仅定义因子名称与分层命名，逻辑完全下沉基类。
    """

    factor_name: ClassVar[str] = "tail_price_slope"

    layer_names: ClassVar[Sequence[str]] = ("lowest", "lower", "normal", "higher", "highest")

    layer_descriptions: ClassVar[Sequence[str]] = (
        "极低层(趋势斜率最小，下跌趋势最明显)",
        "偏低层(趋势斜率较小，下跌趋势较明显)",
        "正常层(趋势斜率适中)",
        "偏高层(趋势斜率较大，上涨趋势较明显)",
        "极高层(趋势斜率最大，上涨趋势最明显)",
    )


if __name__ == "__main__":
    factor_cli_main(
        config_cls=TailPriceSlopeLayerConfig,
        factor_calculator=calculate_tail_price_slope
    )
