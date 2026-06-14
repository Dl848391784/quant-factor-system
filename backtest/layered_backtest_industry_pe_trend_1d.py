#!/usr/bin/env python3
"""
行业PE趋势因子分层回测脚本

因子定义:
- industry_pe_trend = 行业ΔPE赋个股（方向性因子，实测IC=-0.0148）
- 含义: 行业估值趋势变化, 负向因子(IC为负)
- ⚠️ 方向注意: IC为负值, 需反向排序: 因子值越小 → 第1层(做多), 越大 → 第5层(做空)
- PE = close / annualized_eps (分母clip保护, 遵循 Pitfall #47)

边界处理:
- industry 未知 → 赋 '其他' 行业
- eps ≤ 0 → PE = NaN (分母保护)
- 季度财务数据前推填充对齐日频

作者: 云瑶
创建日期: 2026-06-12
版本历史:
  v1.0 (2026-06-12): 初始版本, 复用 factor_calculator.calculate_industry_pe_trend
"""

from collections.abc import Sequence
from typing import ClassVar

from backtest.common.factor_cli import factor_cli_main
from backtest.common.layered_backtest_runner import LayerConfigBase
from data_fetchers.factor_calculator import calculate_industry_pe_trend


class IndustryPeTrendLayerConfig(LayerConfigBase):
    """行业PE趋势因子分层配置"""

    factor_name: ClassVar[str] = "industry_pe_trend"
    layer_names: ClassVar[Sequence[str]] = ("lowest", "lower", "normal", "higher", "highest")
    layer_descriptions: ClassVar[Sequence[str]] = (
        "极低层(PE趋势最弱/估值下降)",
        "偏低层(PE趋势较弱)",
        "正常层(PE趋势适中)",
        "偏高层(PE趋势较强/估值上升)",
        "极高层(PE趋势最强/估值大幅上升)",
    )


if __name__ == "__main__":
    factor_cli_main(
        config_cls=IndustryPeTrendLayerConfig,
        factor_calculator=calculate_industry_pe_trend,
    )
