#!/usr/bin/env python3
"""
动量强度因子分层回测脚本

因子定义：
- 公式: momentum_strength = return_5d / std(return_1d, 5日)
- 含义: 衡量5日累计涨幅相对于日收益率波动率的比率
  - 高值 → 持续上涨趋势（动量强，波动小）
  - 低值 → 震荡或下跌（动量弱，波动大）

分层模式：percentile 5层（每层约20%）

因子元数据派生机制（基类 LayerConfigBase）：
- factor_direction: 从 ic_source IC 文件加载，ic_mean < 0 为 negative
- n_layers: 由 len(layer_names) 派生
- long_layers/short_layers: 由 n_layers 和 factor_direction 派生

作者: 云瑶
创建日期: 2026-06-05
版本历史:
  v1.0 (2026-06-05): 初始版本，薄声明 + factor_cli_main 入口
  v1.1 (2026-06-05): 优化规范合规性：
    1. 添加导入分组注释规范化（本地模块分隔）
    2. 添加模块级 __version__ 常量
    3. 添加 __main__ try/except 块（RuntimeError + Exception 双分支）
    4. 统一引号风格为单引号（与参考模板一致）
"""

from collections.abc import Sequence
from typing import ClassVar

# ============================================================================
# 本地模块导入
# ============================================================================
from backtest.common.factor_cli import factor_cli_main
from backtest.common.layered_backtest_runner import LayerConfigBase
from data_fetchers.factor_calculator import calculate_momentum_strength


# ============================================================================
# 模块级常量
# ============================================================================

__version__ = "1.1"


class MomentumStrengthLayerConfig(LayerConfigBase):
    """动量强度因子分层配置

    薄声明：仅定义因子名称与分层命名，逻辑完全下沉基类。
    """

    factor_name: ClassVar[str] = "momentum_strength"

    layer_names: ClassVar[Sequence[str]] = ("lowest", "lower", "normal", "higher", "highest")

    layer_descriptions: ClassVar[Sequence[str]] = (
        "极低层(动量最弱)",
        "偏低层(动量较弱)",
        "正常层(动量适中)",
        "偏高层(动量较强)",
        "极高层(动量最强)",
    )


if __name__ == "__main__":
    import sys

    from backtest.common.logger_config import get_logger

    _logger = get_logger(__name__)

    try:
        factor_cli_main(config_cls=MomentumStrengthLayerConfig, factor_calculator=calculate_momentum_strength)
    except RuntimeError as e:
        # 已知业务异常，使用 error()（不打印完整堆栈）
        _logger.error(f"动量强度因子分层回测失败: {e}")
        sys.exit(1)
    except Exception:
        # 未预期异常，使用 exception()（自动打印完整堆栈）
        _logger.exception("未预期的错误")
        sys.exit(1)
