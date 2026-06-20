#!/usr/bin/env python3
"""
资金流占比趋势因子分层回测脚本

因子定义:
- capital_flow_ratio_trend = 行业Δ主力净流入占比赋个股（方向性因子,实测IC=+0.0278）
- 含义: 行业资金流向趋势变化, 正向因子
- 分层排序: 因子值越大 → 第1层(做多), 越小 → 第5层(做空)

⚠️ 数据覆盖限制: 每只股票约120交易日(API限制),超过此范围 → NaN
- 因子覆盖率约26%(仅近6个月有数据)

作者: 云瑶
创建日期: 2026-06-12
版本历史:
  v1.0 (2026-06-12): 初始版本, 复用 factor_calculator.calculate_capital_flow_ratio_trend
"""

from collections.abc import Sequence
from typing import ClassVar

from backtest.common.factor_cli import factor_cli_main
from backtest.common.layered_backtest_runner import LayerConfigBase
from data_fetchers.factor_calculator import calculate_capital_flow_ratio_trend


class CapitalFlowRatioTrendLayerConfig(LayerConfigBase):
    """资金流占比趋势因子分层配置"""

    factor_name: ClassVar[str] = "capital_flow_ratio_trend"
    layer_names: ClassVar[Sequence[str]] = ("lowest", "lower", "normal", "higher", "highest")
    layer_descriptions: ClassVar[Sequence[str]] = (
        "极低层(资金流占比趋势最弱)",
        "偏低层(资金流占比趋势较弱)",
        "正常层(资金流占比趋势适中)",
        "偏高层(资金流占比趋势较强)",
        "极高层(资金流占比趋势最强)",
    )


if __name__ == "__main__":
    factor_cli_main(
        config_cls=CapitalFlowRatioTrendLayerConfig,
        factor_calculator=calculate_capital_flow_ratio_trend,
    )
