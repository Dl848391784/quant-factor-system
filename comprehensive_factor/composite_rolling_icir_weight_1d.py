#!/usr/bin/env python3
"""
滚动ICIR加权综合因子分层回测脚本

功能:
- 自动筛选因子（基于ICIR和相关性）
- 滚动ICIR加权（每日动态计算权重，窗口=60日）
- 调用 backtest 分层回测

规范:
- 遵循 PROJECT.md 公共模块强制复用规范
- 命名遵循 MODULE.md: composite_<加权方式>_<收益周期>.py

v2.12 (2026-06-10):
- 删除硬编码 factor_list=['rsi','volume_ratio']，改为 auto_select 筛选决定因子列表
- 默认启用 auto_select，无需手动传 --auto_select 参数

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
class RollingICIRWeightLayerConfig(CompositeLayerConfig):
    """滚动ICIR加权综合因子配置

    v2.12: factor_list/factor_cols 由 auto_select 筛选决定（默认 None）

    加权逻辑：
    - 每日计算滚动窗口内的 ICIR（动态）
    - weight_i_t = |rolling_icir_i_t| / sum(|rolling_icir_j_t|)
    - 适应因子有效性随时间变化

    滚动窗口参数：
    - rolling_window=60（约3个月交易日，捕捉季度周期性）
    - min_periods=20（window//3，数据不足时回退等权）

    综合因子方向：反向因子（因子值越大，未来收益越低）
    """

    # 滚动窗口参数
    min_periods: int = 20  # 显式定义，与实现一致（max(1, window // 3)）

    # 分层参数
    n_layers: int = 5
    factor_direction: str = "negative"
    long_layers: list[int] = field(default_factory=lambda: [1, 2])
    short_layers: list[int] = field(default_factory=lambda: [4, 5])
    trade_cost_rate: float = 0.003
    min_stocks_per_layer: int = 10

    def __post_init__(self):
        """滚动加权参数校验

        规范：
        - min_periods <= rolling_window（窗口内至少需要min_periods个数据）
        - min_periods >= 1（避免空窗口）
        - factor_list/factor_cols 允许 None（由 auto_select 筛选决定）
        """
        # 滚动参数校验
        if self.min_periods > self.rolling_window:
            logger.error(
                "滚动窗口参数校验失败: min_periods (%s) > rolling_window (%s)",
                self.min_periods,
                self.rolling_window,
            )
            raise ValueError(f"min_periods ({self.min_periods}) 必须小于等于 rolling_window ({self.rolling_window})")
        if self.min_periods < 1:
            logger.error("滚动窗口参数校验失败: min_periods (%s) < 1", self.min_periods)
            raise ValueError("min_periods 必须大于等于 1")


# ============================================================================
# CLI 入口
# ============================================================================

# v2.12: 不传 factor_list/factor_cols（默认 None），由 auto_select 筛选决定
main = create_cli_entrypoint(
    weight_method="rolling_icir_weight",
    config_class=RollingICIRWeightLayerConfig,
    return_period="1d",
    data_source=str(DEFAULT_DATA_SOURCE),
)

if __name__ == "__main__":
    # 启动节点日志
    logger.info("=" * 60)
    logger.info("滚动ICIR加权综合因子分层回测启动")
    logger.info("=" * 60)
    logger.info("权重方法: rolling_icir_weight")
    logger.info("因子列表: 由 auto_select 筛选决定")
    logger.info("收益周期: 1d")
    logger.info("数据源: %s", DEFAULT_DATA_SOURCE)
    logger.info("滚动窗口: %s", RollingICIRWeightLayerConfig.rolling_window)
    logger.info("最小周期: %s", RollingICIRWeightLayerConfig.min_periods)

    # 运行入口
    try:
        main()
    except Exception as e:
        logger.error("滚动ICIR加权综合因子回测执行失败 [%s]: %s", type(e).__name__, e)
        sys.exit(1)
