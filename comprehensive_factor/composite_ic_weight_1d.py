#!/usr/bin/env python3
"""
IC加权综合因子分层回测脚本

功能:
- 加载 RSI + Volume_Ratio 因子（低相关性组合）
- IC均值加权（权重 = |ic_mean| / sum(|ic_mean|)）
- 调用 backtest 分层回测

规范:
- 遵循 PROJECT.md 公共模块强制复用规范
- 命名遵循 MODULE.md: composite_<加权方式>_<收益周期>.py

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
from comprehensive_factor.common.data_loader import DEFAULT_DATA_SOURCE


# ============================================================================
# Config 定义
# ============================================================================

@dataclass
class ICWeightLayerConfig(CompositeLayerConfig):
    """IC均值加权综合因子配置
    
    因子组合：
    - rsi_6: RSI 因子（ic_mean = -0.037, |ic_mean| = 0.037）
    - volume_ratio_5: 量比因子（ic_mean = -0.031, |ic_mean| = 0.031）
    
    加权逻辑：
    - |ic_mean| 越高权重越大
    - 实际权重（来自 factor_ic/result/*.json，2024-03-27~2026-05-14，545天）：
      - rsi 权重 = 0.037 / (0.037 + 0.031) ≈ 0.55
      - volume_ratio 权重 = 0.031 / (0.037 + 0.031) ≈ 0.45
    
    对比ICIR加权：
    - IC加权忽略波动性（ic_std），仅基于均值绝对值
    - ICIR加权同时考虑均值和波动（|ic_mean| / ic_std）
    
    综合因子方向：反向因子（因子值越大，未来收益越低）
    """
    
    # 分层参数（继承父类的 factor_list, factor_cols）
    n_layers: int = 5
    factor_direction: str = 'negative'
    long_layers: List[int] = field(default_factory=lambda: [1, 2])
    short_layers: List[int] = field(default_factory=lambda: [4, 5])
    trade_cost_rate: float = 0.003
    min_stocks_per_layer: int = 10


# ============================================================================
# CLI 入口
# ============================================================================

# 创建默认配置实例用于CLI参数
_default_config = ICWeightLayerConfig()

main = create_cli_entrypoint(
    weight_method='ic_weight',
    factor_list=_default_config.factor_list,
    factor_cols=_default_config.factor_cols,
    config_class=ICWeightLayerConfig,
    return_period='1d',
    data_source=str(DEFAULT_DATA_SOURCE)
)

if __name__ == '__main__':
    main()