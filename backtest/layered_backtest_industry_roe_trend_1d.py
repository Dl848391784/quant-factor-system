#!/usr/bin/env python3
"""
行业ROE趋势因子分层回测脚本

因子定义：
- industry_roe_trend = 行业ΔROE赋个股（方向性因子，实测IC=+0.0325）
- 含义：行业基本面盈利能力趋势，正向因子
- 分层排序：因子值越大 → 第1层（做多），越小 → 第5层（做空）

边界处理：
- industry 未知 → 赋 '其他' 行业
- ROE 数据缺失 → ΔROE 为 NaN
- 季度财务数据前推填充对齐日频

因子元数据派生机制（基类 LayerConfigBase）：
- factor_direction: 从 ic_source IC 文件加载，ic_mean < 0 为 negative
- n_layers: 由 len(layer_names) 派生
- long_layers/short_layers: 由 n_layers 和 factor_direction 派生
"""

from collections.abc import Sequence
from typing import ClassVar

from backtest.common.factor_cli import factor_cli_main
from backtest.common.layered_backtest_runner import LayerConfigBase
from data_fetchers.factor_calculator import calculate_industry_roe_trend


class IndustryRoeTrendLayerConfig(LayerConfigBase):
    """行业ROE趋势因子分层配置

    薄声明：仅定义因子名称与分层命名，逻辑完全下沉基类。
    """

    factor_name: ClassVar[str] = "industry_roe_trend"

    layer_names: ClassVar[Sequence[str]] = ("lowest", "lower", "normal", "higher", "highest")

    layer_descriptions: ClassVar[Sequence[str]] = (
        "极低层(行业ROE趋势最弱)",
        "偏低层(行业ROE趋势较弱)",
        "正常层(行业ROE趋势适中)",
        "偏高层(行业ROE趋势较强)",
        "极高层(行业ROE趋势最强)",
    )


if __name__ == "__main__":
    factor_cli_main(
            config_cls=IndustryRoeTrendLayerConfig,
            factor_calculator=calculate_industry_roe_trend,
        )
