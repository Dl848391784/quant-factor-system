#!/usr/bin/env python3
"""
量比因子分层回测脚本

因子定义：
- 公式: volume_ratio_5 = 当日成交量 / 过去5日平均成交量
- 含义: 成交量相对历史均值的比率
- 理论范围: ≥ 0（无上界）

策略逻辑（反向因子）：
- 低值层做多（缩量组）
- 高值层做空（放量组）

分层模式：percentile 5层（每层20%）

因子元数据派生机制（基类 LayerConfigBase）：
- factor_direction: 从 ic_source IC 文件加载，ic_mean < 0 为 negative
- n_layers: 由 len(layer_names) 派生
- long_layers/short_layers: 由 n_layers 和 factor_direction 派生
"""

from typing import ClassVar, Sequence

from backtest.common.layered_backtest_runner import LayerConfigBase
from backtest.common.factor_cli import factor_cli_main


class VolumeRatioLayerConfig(LayerConfigBase):
    """量比因子分层配置
    
    薄声明：仅定义因子名称与分层命名，逻辑完全下沉基类。
    
    特点：
    - volume_ratio_5 已在数据源中预计算，无需 factor_calculator
    - 反向因子：做多缩量组，做空放量组
    """
    
    factor_name: ClassVar[str] = 'volume_ratio'
    
    layer_names: ClassVar[Sequence[str]] = (
        '极低层(量比极低)',
        '偏低层(量比偏低)',
        '正常层(量比适中)',
        '偏高层(量比偏高)',
        '极高层(量比极高)'
    )


if __name__ == '__main__':
    # 预计算因子：无需 factor_calculator
    # 数据源列名: volume_ratio_5（与 factor_name 不同）
    factor_cli_main(
        config_cls=VolumeRatioLayerConfig,
        factor_col='volume_ratio_5',
        required_factor_cols=['volume_ratio_5']
    )