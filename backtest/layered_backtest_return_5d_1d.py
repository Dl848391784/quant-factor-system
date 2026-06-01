#!/usr/bin/env python3
"""
5日累计涨幅因子分层回测脚本

因子定义：
- 公式: return_5d = close[t] / close[t-5] - 1
- 含义: 过去5日累计涨跌幅
- 理论范围: [-0.5, 0.5]（A股日涨跌幅±10%）

策略逻辑（反向因子）：
- 低值层做多（涨幅小或下跌）
- 高值层做空（涨幅大）

分层模式：percentile 5层（每层20%）

作者: 云瑶
创建日期: 2026-05-29
"""

from dataclasses import dataclass, field
from typing import Dict, ClassVar

from backtest.common.layered_backtest_runner import LayerConfigBase
from backtest.common.factor_cli import factor_cli_main
from data_fetchers.factor_calculator import calculate_return_5d


@dataclass
class Return5dLayerConfig(LayerConfigBase):
    """5日收益因子分层配置"""
    
    factor_name: ClassVar[str] = 'return_5d'
    
    layer_names: Dict[str, str] = field(default_factory=lambda: {
        '1': '极低层(5日涨幅最小)',
        '2': '偏低层(5日小幅下跌)',
        '3': '正常层(5日变化不大)',
        '4': '偏高层(5日小幅上涨)',
        '5': '极高层(5日涨幅最大)'
    })


if __name__ == '__main__':
    factor_cli_main(
        config_cls=Return5dLayerConfig,
        factor_calculator=calculate_return_5d
    )