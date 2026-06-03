#!/usr/bin/env python3
"""
滚动ICIR加权综合因子分层回测脚本

功能:
- 加载 RSI + Volume_Ratio 因子（低相关性组合）
- 滚动ICIR加权（每日动态计算权重，窗口=60日）
- 调用 backtest 分层回测

规范:
- 遵循 PROJECT.md 公共模块强制复用规范
- 命名遵循 MODULE.md: composite_<加权方式>_<收益周期>.py

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
    
    因子组合：
    - rsi_6: RSI 因子
    - volume_ratio_5: 量比因子
    
    加权逻辑：
    - 每日计算滚动窗口内的 ICIR（动态）
    - weight_i_t = |rolling_icir_i_t| / sum(|rolling_icir_j_t|)
    - 适应因子有效性随时间变化
    
    滚动窗口参数（继承父类 rolling_window）：
    - rolling_window=60（约3个月交易日，捕捉季度周期性）
    - min_periods=20（window//3，数据不足时回退等权）
    
    选择依据（rolling_window=60）：
    - 1个季度≈60个交易日，符合财报披露周期
    - ICIR稳定性检验：60日窗口的ICIR波动较小（vs 20日/30日）
    - 业界惯例：IC衰减检验常用60日窗口
    
    异常处理（weight_engine.py 实现）：
    - weight_sum=0时：回退等权（1/n_factors）
    - rolling_std=0时：ICIR为NaN，权重为NaN，最终回退等权
    
    综合因子方向：反向因子（因子值越大，未来收益越低）
    """

    # 滚动窗口参数（继承父类的 factor_list, factor_cols, rolling_window）
    min_periods: int = 20  # 显式定义，与实现一致（max(1, window // 3)）

    # 分层参数
    n_layers: int = 5
    factor_direction: str = 'negative'
    long_layers: list[int] = field(default_factory=lambda: [1, 2])
    short_layers: list[int] = field(default_factory=lambda: [4, 5])
    trade_cost_rate: float = 0.003
    min_stocks_per_layer: int = 10

    def __post_init__(self):
        """滚动加权参数校验
        
        规范：
        - min_periods <= rolling_window（窗口内至少需要min_periods个数据）
        - min_periods >= 1（避免空窗口）
        - factor_list/factor_cols 由父类 validate() 校验
        """
        # 滚动参数校验
        if self.min_periods > self.rolling_window:
            logger.error(
                f"滚动窗口参数校验失败: min_periods ({self.min_periods}) > rolling_window ({self.rolling_window})"
            )
            raise ValueError(
                f"min_periods ({self.min_periods}) 必须小于等于 rolling_window ({self.rolling_window})"
            )
        if self.min_periods < 1:
            logger.error(
                f"滚动窗口参数校验失败: min_periods ({self.min_periods}) < 1"
            )
            raise ValueError("min_periods 必须大于等于 1")


# ============================================================================
# CLI 入口
# ============================================================================

# 创建默认配置实例用于CLI参数（异常捕获 + 日志）
try:
    _default_config = RollingICIRWeightLayerConfig()
except Exception as e:
    logger.error(f"RollingICIRWeightLayerConfig 实例化失败 [{type(e).__name__}]: {e}")
    raise

# 创建 CLI 入口（异常捕获 + 日志）
try:
    main = create_cli_entrypoint(
        weight_method='rolling_icir_weight',
        config_class=RollingICIRWeightLayerConfig,  # v2.8: config_class 移至 factor_list 前面
        factor_list=_default_config.factor_list,
        factor_cols=_default_config.factor_cols,
        return_period='1d',
        data_source=str(DEFAULT_DATA_SOURCE)
    )
except Exception as e:
    logger.error(f"create_cli_entrypoint 构建失败 [{type(e).__name__}]: {e}")
    raise

if __name__ == '__main__':
    # 启动节点日志：输出关键配置信息
    logger.info("=" * 60)
    logger.info("滚动ICIR加权综合因子分层回测启动")
    logger.info("=" * 60)
    logger.info("权重方法: rolling_icir_weight")
    logger.info(f"因子列表: {_default_config.factor_list}")
    logger.info(f"因子列名: {_default_config.factor_cols}")
    logger.info("收益周期: 1d")
    logger.info(f"数据源: {DEFAULT_DATA_SOURCE}")
    logger.info(f"滚动窗口: {_default_config.rolling_window}")
    logger.info(f"最小周期: {_default_config.min_periods}")

    # 运行入口（异常兜底 + 日志）
    try:
        main()
    except Exception as e:
        logger.error(f"滚动ICIR加权综合因子回测执行失败 [{type(e).__name__}]: {e}")
        sys.exit(1)
