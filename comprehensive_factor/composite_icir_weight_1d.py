#!/usr/bin/env python3
"""
ICIR加权综合因子分层回测脚本

功能:
- 加载 RSI + Volume_Ratio 因子（低相关性组合）
- ICIR加权（权重 = |ICIR| / sum(|ICIR|)）
- 调用 backtest 分层回测

规范:
- 遵循 PROJECT.md 公共模块强制复用规范
- 命名遵循 MODULE.md: composite_<加权方式>_<收益周期>.py
- 遵循 MODULE.md CLI入口最小导入规范：只导入实际使用的函数
- 遵循 MODULE.md Config默认值单一数据源规范：CLI入口参数从Config读取

ICIR数据来源（factor_ic/result/*.json）:
- RSI: ic_mean=-0.037, ICIR=0.2519（2024-03-27~2026-05-14，545天）
- Volume_Ratio: ic_mean=-0.031, ICIR=0.3058（同上）

加权权重（动态计算，由 weight_engine.py ICIRWeightMethod 实现）:
- Volume_Ratio: |ICIR|/sum(|ICIR|) = 0.3058/0.5577 ≈ 0.55
- RSI: |ICIR|/sum(|ICIR|) = 0.2519/0.5577 ≈ 0.45

作者: 云瑶
创建日期: 2026-05-24
"""

import sys
from pathlib import Path
from dataclasses import dataclass, field
from typing import List

# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from comprehensive_factor.common.composite_runner import (
    create_cli_entrypoint,
    CompositeLayerConfig
)
from comprehensive_factor.common.data_loader import DEFAULT_CACHE_DIR


# ============================================================================
# Config 定义
# ============================================================================

@dataclass
class ICIRWeightLayerConfig(CompositeLayerConfig):
    """ICIR加权综合因子配置
    
    继承 CompositeLayerConfig，因子组合参数已在父类定义：
    - factor_list: ['rsi', 'volume_ratio']
    - factor_cols: ['rsi_6', 'volume_ratio_5']
    
    分层参数：
    - n_layers: 5（percentile分层）
    - factor_direction: 'negative'（反向因子）
    
    ICIR加权权重由 weight_engine.py ICIRWeightMethod 从 ic_results 动态计算，
    公式：weight_i = |ICIR_i| / sum(|ICIR_j|)
    
    实际ICIR值（见 factor_ic/result/*.json）：
    - RSI: ICIR=0.2519
    - Volume_Ratio: ICIR=0.3058
    """
    
    # 分层参数（覆盖父类默认值，因子组合参数继承父类）
    n_layers: int = 5
    factor_direction: str = 'negative'
    long_layers: List[int] = field(default_factory=lambda: [1, 2])
    short_layers: List[int] = field(default_factory=lambda: [4, 5])
    trade_cost_rate: float = 0.003
    min_stocks_per_layer: int = 10


# ============================================================================
# CLI 入口
# ============================================================================

# 从 Config 类读取默认值，单一数据源（遵循 MODULE.md 规范）
_default_config = ICIRWeightLayerConfig()

main = create_cli_entrypoint(
    weight_method='icir_weight',
    factor_list=_default_config.factor_list,
    factor_cols=_default_config.factor_cols,
    config_class=ICIRWeightLayerConfig,
    return_period='1d',
    cache_dir=str(DEFAULT_CACHE_DIR)
)

if __name__ == '__main__':
    main()