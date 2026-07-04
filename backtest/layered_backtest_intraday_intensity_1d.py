#!/usr/bin/env python3
"""
日内价格强度因子分层回测脚本

因子定义：
- 公式: intraday_intensity = (Close - Open) / (High - Low)
- 含义: 日内价格强度，反映当日涨幅/跌幅占振幅的比例
- 值范围: -1 到 1（High=Low 时设为 NaN）

因子元数据派生机制（基类 LayerConfigBase）：
- factor_col_resolved: 从 factor_col ClassVar 派生，默认=factor_name
- factor_direction: 从 ic_source IC 文件加载，ic_mean < 0 为 negative
- n_layers: 由 len(layer_names) 派生
- layer_names_dict: 优先使用 layer_descriptions，否则回退 layer_names

分层说明（反向因子，ic_mean < 0）：
- 做多低值组（日内强度小，下跌日）
- 做空高值组（日内强度大，上涨日）
- 理论：反转效应，下跌日次日反弹概率更高
"""

import sys
from collections.abc import Sequence
from pathlib import Path
from typing import ClassVar


# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from backtest.common.factor_cli import factor_cli_main
from backtest.common.layered_backtest_runner import LayerConfigBase

# 导入因子计算函数（复杂因子需自定义计算）
from factor_ic.ic_intraday_intensity_1d import calculate_intraday_intensity


class IntradayIntensityLayerConfig(LayerConfigBase):
    """日内价格强度因子分层配置

    薄声明：因子元数据集中在 ClassVar，逻辑完全下沉基类。

    特点：
    - 因子类型：复杂因子（需从 open/close/high/low 计算）
    - 因子方向：反向因子（ic_mean < 0），做多低值组
    - layer_names 纯标签（用于目录/列名），layer_descriptions 含中文（用于日志）
    """

    factor_name: ClassVar[str] = "intraday_intensity_1d"
    factor_col: ClassVar[str] = "intraday_intensity"  # 计算后的因子列名
    # ic_source 指定纯文件名，基类自动补充 FACTOR_IC_RESULT 目录（pipeline 感知）
    # factor_name='intraday_intensity_1d' 会导致基类默认拼接出双 _1d，故需显式指定文件名
    ic_source: ClassVar[str] = "ic_intraday_intensity_1d_analysis_result.json"

    # 5 层分层
    layer_names: ClassVar[Sequence[str]] = ("lowest", "lower", "normal", "higher", "highest")

    layer_descriptions: ClassVar[Sequence[str]] = (
        "极低层(日内强度极低，强势下跌)",
        "偏低层(日内强度偏低，下跌)",
        "正常层(日内强度适中，震荡)",
        "偏高层(日内强度偏高，上涨)",
        "极高层(日内强度极高，强势上涨)",
    )


if __name__ == "__main__":
    # 传入因子计算函数（复杂因子需要）
    factor_cli_main(IntradayIntensityLayerConfig, factor_calculator=calculate_intraday_intensity)
