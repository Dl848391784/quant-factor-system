#!/usr/bin/env python3
"""
行业盈利增长因子分层回测脚本

因子定义:
- industry_earnings_growth = 行业净利润增长率赋个股（方向性因子，实测IC=+0.0255）
- 含义: 行业基本面盈利增长趋势, 正向因子
- 分层排序: 因子值越大 → 第1层(做多), 越小 → 第5层(做空)

边界处理:
- industry 未知 → 赋 '其他' 行业
- 净利润增长率缺失 → 因子值 NaN
- 季度财务数据前推填充对齐日频

作者: 云瑶
创建日期: 2026-06-12
版本历史:
  v1.0 (2026-06-12): 初始版本, 复用 factor_calculator.calculate_industry_earnings_growth
"""

from collections.abc import Sequence
from typing import ClassVar

from backtest.common.factor_cli import factor_cli_main
from backtest.common.layered_backtest_runner import LayerConfigBase
from data_fetchers.factor_calculator import calculate_industry_earnings_growth


class IndustryEarningsGrowthLayerConfig(LayerConfigBase):
    """行业盈利增长因子分层配置"""

    factor_name: ClassVar[str] = "industry_earnings_growth"
    layer_names: ClassVar[Sequence[str]] = ("lowest", "lower", "normal", "higher", "highest")
    layer_descriptions: ClassVar[Sequence[str]] = (
        "极低层(盈利增长最弱)",
        "偏低层(盈利增长较弱)",
        "正常层(盈利增长适中)",
        "偏高层(盈利增长较强)",
        "极高层(盈利增长最强)",
    )


if __name__ == "__main__":
    factor_cli_main(
        config_cls=IndustryEarningsGrowthLayerConfig,
        factor_calculator=calculate_industry_earnings_growth,
    )
