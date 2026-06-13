#!/usr/bin/env python3
"""
资金流强度因子分层回测脚本

因子定义:
- capital_flow_intensity = 行业主力流入绝对额占比赋个股(|main_inflow_amount|/total_volume)
  (方向性因子, 实测IC=+0.0243)
- 含义: 行业主力资金活跃度, 正向因子
- 分层排序: 因子值越大 → 第1层(做多), 越小 → 第5层(做空)

⚠️ 数据覆盖限制: 每只股票约120交易日(API限制),超过此范围 → NaN
- 因子覆盖率约26%(仅近6个月有数据)
- total_volume = 0 或 NaN → intensity = NaN (除零保护)

作者: 云瑶
创建日期: 2026-06-12
版本历史:
  v1.0 (2026-06-12): 初始版本, 复用 factor_calculator.calculate_capital_flow_intensity
"""

from collections.abc import Sequence
from typing import ClassVar

from backtest.common.factor_cli import factor_cli_main
from backtest.common.layered_backtest_runner import LayerConfigBase
from data_fetchers.factor_calculator import calculate_capital_flow_intensity


class CapitalFlowIntensityLayerConfig(LayerConfigBase):
    """资金流强度因子分层配置"""

    factor_name: ClassVar[str] = "capital_flow_intensity"
    layer_names: ClassVar[Sequence[str]] = ("lowest", "lower", "normal", "higher", "highest")
    layer_descriptions: ClassVar[Sequence[str]] = (
        "极低层(资金流强度最低)",
        "偏低层(资金流强度较弱)",
        "正常层(资金流强度适中)",
        "偏高层(资金流强度较强)",
        "极高层(资金流强度最强)",
    )


if __name__ == "__main__":
    factor_cli_main(
        config_cls=CapitalFlowIntensityLayerConfig,
        factor_calculator=calculate_capital_flow_intensity,
    )