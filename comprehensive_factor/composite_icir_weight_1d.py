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
    run_composite_backtest,
    create_cli_entrypoint,
    CompositeLayerConfig
)
from comprehensive_factor.common.logger_config import get_logger
from comprehensive_factor.common.data_loader import DEFAULT_CACHE_DIR

logger = get_logger(__name__)


# ============================================================================
# Config 定义
# ============================================================================

@dataclass
class ICIRWeightLayerConfig(CompositeLayerConfig):
    """ICIR加权综合因子配置
    
    因子组合：
    - rsi_6: RSI 因子（ICIR ≈ -0.45）
    - volume_ratio_5: 量比因子（ICIR ≈ -1.97）
    
    加权逻辑：
    - |ICIR| 越高权重越大
    - volume_ratio 权重 ≈ 1.97 / (1.97 + 0.45) ≈ 0.81
    - rsi 权重 ≈ 0.45 / (1.97 + 0.45) ≈ 0.19
    
    综合因子方向：反向因子
    """
    
    # 因子组合
    factor_list: List[str] = field(default_factory=lambda: ['rsi', 'volume_ratio'])
    factor_cols: List[str] = field(default_factory=lambda: ['rsi_6', 'volume_ratio_5'])
    
    # 分层参数
    n_layers: int = 5
    factor_direction: str = 'negative'
    long_layers: List[int] = field(default_factory=lambda: [1, 2])
    short_layers: List[int] = field(default_factory=lambda: [4, 5])
    trade_cost_rate: float = 0.003
    min_stocks_per_layer: int = 10


# ============================================================================
# CLI 入口
# ============================================================================

main = create_cli_entrypoint(
    weight_method='icir_weight',
    factor_list=['rsi', 'volume_ratio'],
    factor_cols=['rsi_6', 'volume_ratio_5'],
    config_class=ICIRWeightLayerConfig,
    return_period='1d',
    cache_dir=str(DEFAULT_CACHE_DIR)
)

if __name__ == '__main__':
    main()