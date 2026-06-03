#!/usr/bin/env python3
"""
等权综合因子分层回测脚本

功能:
- 加载 RSI + Volume_Ratio 因子（低相关性组合）
- 等权组合（每个因子权重 = 1/n）
- 调用 backtest 分层回测

规范:
- 遵循 PROJECT.md 公共模块强制复用规范
- 命名遵循 MODULE.md: composite_<加权方式>_<收益周期>.py
- 遵循 MODULE.md CLI入口最小导入规范：只导入实际使用的函数
- 遵循 MODULE.md Config默认值单一数据源规范：CLI入口参数从Config读取

更新历史（2026-05-27）：
- v2.7: cache_dir 改为 data_source，读取统一数据源
- v2.8: 补充异常捕获日志和启动节点日志

作者: 云瑶
创建日期: 2026-05-24
"""

import sys
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import ClassVar


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
class EqualWeightLayerConfig(CompositeLayerConfig):
    """等权综合因子配置
    
    继承 CompositeLayerConfig，因子组合参数已在父类定义：
    - factor_list: ['rsi', 'volume_ratio']
    - factor_cols: ['rsi_6', 'volume_ratio_5']
    
    相关性：corr ≈ 0.30（低相关，适合组合）
    
    综合因子方向：反向因子（低值预期高收益）
    - 缩量（volume_ratio低）+ 超卖（rsi低） → 预期高收益
    """

    # === 因子元数据（必须声明，满足 LayerConfigBase 要求） ===
    factor_name: ClassVar[str] = 'equal_weight_composite'
    layer_names: ClassVar[Sequence[str]] = ('lowest', 'lower', 'normal', 'higher', 'highest')
    layer_descriptions: ClassVar[Sequence[str]] = (
        '极低层(综合因子值最小)',
        '偏低层(综合因子值偏小)',
        '正常层(综合因子值中等)',
        '偏高层(综合因子值偏大)',
        '极高层(综合因子值最大)'
    )

    # 分层参数（覆盖父类默认值，因子组合参数继承父类）
    n_layers: int = 5
    factor_direction: str = 'negative'
    long_layers: list[int] = field(default_factory=lambda: [1, 2])
    short_layers: list[int] = field(default_factory=lambda: [4, 5])
    trade_cost_rate: float = 0.003
    min_stocks_per_layer: int = 10


# ============================================================================
# CLI 入口
# ============================================================================

# 问题1修复：_default_config 实例化失败时捕获异常并记录日志
try:
    # 从 Config 类读取默认值，单一数据源（遵循 MODULE.md 规范）
    _default_config = EqualWeightLayerConfig()
except Exception:
    logger.exception("EqualWeightLayerConfig 实例化失败")
    raise

# 问题2修复：create_cli_entrypoint 调用失败时捕获异常并记录日志
try:
    main = create_cli_entrypoint(
        weight_method='equal_weight',
        config_class=EqualWeightLayerConfig,  # v2.8: config_class 移至 factor_list 前面
        factor_list=_default_config.factor_list,
        factor_cols=_default_config.factor_cols,
        return_period='1d',
        data_source=str(DEFAULT_DATA_SOURCE)
    )
except Exception:
    logger.exception("create_cli_entrypoint 构建CLI入口失败")
    raise

if __name__ == '__main__':
    # 问题4修复：脚本启动时输出关键配置日志
    logger.info("=" * 60 + " 等权综合因子分层回测启动 " + "=" * 60)
    logger.info("权重方法: equal_weight")
    logger.info(f"因子列表: {_default_config.factor_list}")
    logger.info(f"因子列: {_default_config.factor_cols}")
    logger.info("收益周期: 1d")
    logger.info(f"数据源: {DEFAULT_DATA_SOURCE}")
    logger.info(f"分层参数: n_layers={_default_config.n_layers}, factor_direction={_default_config.factor_direction}")
    logger.info(f"多空组合: long_layers={_default_config.long_layers}, short_layers={_default_config.short_layers}")

    # 问题3修复：main() 调用时捕获异常并记录日志
    try:
        main()
    except Exception:
        logger.exception("等权综合因子回测执行失败")
        sys.exit(1)
