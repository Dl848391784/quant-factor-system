#!/usr/bin/env python3
"""
量比因子分层回测脚本

使用公共入口 run_layered_backtest，代码量从 ~370 行降至 ~80 行。

规范:
- 遵循 PROJECT.md 公共模块强制复用规范
- 命名遵循 MODULE.md: layered_backtest_<因子名>_<收益周期>.py

作者: 云瑶
创建日期: 2026-05-23
重构日期: 2026-05-23（使用公共入口）
"""

import sys
from pathlib import Path
from dataclasses import dataclass, field
from typing import List, Dict as TypingDict

sys.path.insert(0, str(Path(__file__).parent.parent))

from backtest.common.layered_backtest_runner import (
    run_layered_backtest,
    LayerConfigBase,
    create_cli_entrypoint
)
from factor_ic.common.logger_config import get_logger

logger = get_logger(__name__)


@dataclass
class VolumeRatioLayerConfig(LayerConfigBase):
    """量比分层配置"""
    
    layer_thresholds: List[float] = field(default_factory=lambda: [0, 0.5, 1.0, 1.5, 2.0, 5.0])
    
    layer_names: TypingDict[str, str] = field(default_factory=lambda: {
        '1': '极缩量层(ratio<0.5)',
        '2': '缩量层(0.5≤ratio<1)',
        '3': '正常层(1≤ratio<1.5)',
        '4': '放量层(1.5≤ratio<2)',
        '5': '极放量层(ratio≥2)'
    })
    
    factor_direction: str = 'negative'
    long_layers: List[int] = field(default_factory=lambda: [1, 2])
    short_layers: List[int] = field(default_factory=lambda: [4, 5])
    
    layer_threshold_desc: TypingDict[str, str] = field(default_factory=lambda: {
        '1': 'ratio < 0.5 (成交量远低于均值)',
        '2': '0.5 ≤ ratio < 1 (成交量低于均值)',
        '3': '1 ≤ ratio < 1.5 (成交量接近均值)',
        '4': '1.5 ≤ ratio < 2 (成交量偏高)',
        '5': 'ratio ≥ 2 (成交量极放量)'
    })


main = create_cli_entrypoint(
    factor_name='volume_ratio',
    factor_col='volume_ratio_5',
    config_class=VolumeRatioLayerConfig
)

if __name__ == '__main__':
    main()