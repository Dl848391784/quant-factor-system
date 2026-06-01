#!/usr/bin/env python3
"""
5日累计涨幅因子分层回测脚本

因子定义：
- 公式: return_5d = close[t] / close[t-5] - 1
- 含义: 过去5日累计涨跌幅
- 理论范围: [-0.5, 0.5]（A股日涨跌幅±10%）

分层模式：percentile 5层（每层20%）

因子元数据派生机制（基类 LayerConfigBase）：
- factor_direction: 从 ic_source IC 文件加载，ic_mean < 0 为 negative
- n_layers: 由 len(layer_names) 派生
- long_layers/short_layers: 由 n_layers 和 factor_direction 派生
"""

from typing import ClassVar, Sequence

from backtest.common.layered_backtest_runner import LayerConfigBase
from backtest.common.factor_cli import factor_cli_main
from data_fetchers.factor_calculator import calculate_return_5d


class Return5dLayerConfig(LayerConfigBase):
    """5日收益因子分层配置
    
    薄声明：仅定义因子名称与分层命名，逻辑完全下沉基类。
    """
    
    factor_name: ClassVar[str] = 'return_5d'
    # ic_source: ClassVar[str] = 'factor_ic/result/ic_return_5d_1d_analysis_result.json'
    #   可选显式声明以暴露派生路径；未声明时基类按 factor_name 拼接默认路径
    
    layer_names: ClassVar[Sequence[str]] = (
        '极低层(5日涨幅最小)',
        '偏低层(5日小幅下跌)',
        '正常层(5日变化不大)',
        '偏高层(5日小幅上涨)',
        '极高层(5日涨幅最大)'
    )


if __name__ == '__main__':
    factor_cli_main(
        config_cls=Return5dLayerConfig,
        factor_calculator=calculate_return_5d
    )