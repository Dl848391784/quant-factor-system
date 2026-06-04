#!/usr/bin/env python3
"""
量比因子分层回测脚本

因子定义：
- 公式: volume_ratio_5 = 当日成交量 / 过去5日平均成交量
- 含义: 成交量相对历史均值的比率
- 理论范围: ≥ 0（无上界）

因子元数据派生机制（基类 LayerConfigBase）：
- factor_col_resolved: 从 factor_col ClassVar 派生，默认=factor_name
- factor_direction: 从 ic_source IC 文件加载，ic_mean < 0 为 negative
- n_layers: 由 len(layer_names) 派生
- layer_names_dict: 优先使用 layer_descriptions，否则回退 layer_names
"""

from typing import ClassVar, Sequence

from backtest.common.layered_backtest_runner import LayerConfigBase
from backtest.common.factor_cli import factor_cli_main


class VolumeRatioLayerConfig(LayerConfigBase):
    """量比因子分层配置
    
    薄声明：因子元数据集中在 ClassVar，逻辑完全下沉基类。
    
    特点：
    - factor_name=volume_ratio（IC 文件命名对应）
    - factor_col=volume_ratio_5（数据源列名，预计算因子）
    - layer_names 纯标签（用于目录/列名），layer_descriptions 含中文（用于日志）
    """
    
    factor_name: ClassVar[str] = 'volume_ratio'
    factor_col: ClassVar[str] = 'volume_ratio_5'
    ic_source: ClassVar[str] = 'factor_ic/result/ic_volume_ratio_1d_analysis_result.json'  # IC文件路径覆盖
    
    layer_names: ClassVar[Sequence[str]] = (
        'lowest',
        'lower',
        'normal',
        'higher',
        'highest'
    )
    
    layer_descriptions: ClassVar[Sequence[str]] = (
        '极低层(量比极低)',
        '偏低层(量比偏低)',
        '正常层(量比适中)',
        '偏高层(量比偏高)',
        '极高层(量比极高)'
    )


if __name__ == '__main__':
    factor_cli_main(VolumeRatioLayerConfig)