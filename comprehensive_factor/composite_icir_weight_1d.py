#!/usr/bin/env python3
"""
ICIR加权综合因子分层回测脚本

功能:
- 自动筛选因子（基于ICIR和相关性）
- ICIR加权（ICIR绝对值越大权重越高）
- 调用 backtest 分层回测

规范:
- 遵循 PROJECT.md 公共模块强制复用规范
- 命名遵循 MODULE.md: composite_<加权方式>_<收益周期>.py

v2.12 (2026-06-10):
- 删除硬编码 factor_list=['rsi','volume_ratio']，改为 auto_select 筛选决定因子列表
- 默认启用 auto_select

作者: 云瑶
创建日期: 2026-05-24
"""

import sys
from dataclasses import dataclass, field
from pathlib import Path


# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from comprehensive_factor.common.composite_runner import CompositeLayerConfig, create_cli_entrypoint
from comprehensive_factor.common.data_loader import DEFAULT_DATA_SOURCE
from comprehensive_factor.common.logger_config import get_logger


logger = get_logger(__name__)


# ============================================================================
# Config 定义
# ============================================================================


@dataclass
class ICIRWeightLayerConfig(CompositeLayerConfig):
    """ICIR加权综合因子配置

    v2.12: factor_list/factor_cols 由 auto_select 筛选决定

    加权逻辑：
    - weight_i = |icir_i| / sum(|icir_j|)
    - ICIR绝对值越大权重越高，反映因子预测稳定性

    综合因子方向：正向因子（v2.47 对齐：因子值越大，未来收益越高）
    """

    n_layers: int = 5
    factor_direction: str = "positive"  # v2.47: 综合因子方向（对齐到正向语义，值大=好）
    long_layers: list[int] = field(default_factory=lambda: [4, 5])  # v2.47: 正向因子，Layer 4/5 = 高 composite = 多头
    short_layers: list[int] = field(default_factory=lambda: [1, 2])  # v2.47: Layer 1/2 = 低 composite = 空头
    trade_cost_rate: float = 0.003
    min_stocks_per_layer: int = 10


# ============================================================================
# CLI 入口
# ============================================================================

# v2.12: 不传 factor_list/factor_cols（默认 None），由 auto_select 筛选决定
main = create_cli_entrypoint(
    weight_method="icir_weight",
    config_class=ICIRWeightLayerConfig,
    return_period="1d",
    data_source=str(DEFAULT_DATA_SOURCE),
)

if __name__ == "__main__":
    logger.info("=" * 60)
    logger.info("ICIR加权综合因子分层回测启动")
    logger.info("=" * 60)
    logger.info("权重方法: icir_weight")
    logger.info("因子列表: 由 auto_select 筛选决定")
    logger.info("收益周期: 1d")

    try:
        main()
    except Exception:
        # M42: CLI 兜底用 logger.exception 自动附加堆栈
        logger.exception("ICIR加权综合因子回测执行失败")
        sys.exit(1)
