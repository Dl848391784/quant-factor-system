#!/usr/bin/env python3
"""
尾盘缩量程度因子分层回测脚本

因子定义：
- 尾盘成交量总和 = sum(volumes[0:13])  # 14:00-15:00 全部13根K线成交量
- 全天成交量 = volume（主数据源）
- 缩量程度 = 尾盘成交量总和 / 全天成交量

分层模式：percentile 5层（每层约20%）

因子元数据派生机制（基类 LayerConfigBase）：
- factor_direction: 从 ic_source IC 文件加载，ic_mean = -0.0047 < 0 → negative
- n_layers: 由 len(layer_names) 派生 → 5
- long_layers/short_layers: 由 n_layers 和 factor_direction 派生

数据依赖：
- factor_ic_data.json.gz（主数据源）
- tail_trading_data.json.gz（尾盘5分钟K线数据）

作者: 云瑶
创建日期: 2026-06-03
版本历史:
  v1.0 (2026-06-03): 初始版本，实现尾盘缩量程度因子分层回测
  v1.1 (2026-06-03): Round 1 优化 - 导入分组注释完善
  v1.2 (2026-06-03): Round 2 优化 - 版本历史完善（对照模板）
  v1.3 (2026-06-03): Round 3 优化 - ClassVar 类型注解确认（Sequence[str]）
  v1.4 (2026-06-03): Round 4 优化 - 边界处理下沉基类确认（薄声明模式无额外代码）
  v1.5 (2026-06-03): Round 5 优化 - Spec Compliance 确认（对照 tail_volume_acceleration 脚本合规）
"""

# ============================================================================
# 标准库导入
# ============================================================================
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import ClassVar

# ============================================================================
# 本地模块导入
# ============================================================================
sys.path.insert(0, str(Path(__file__).parent.parent))

from backtest.common.factor_cli import factor_cli_main
from backtest.common.layered_backtest_runner import LayerConfigBase
from factor_ic.ic_tail_volume_shrink_1d import calculate_tail_volume_shrink


class TailVolumeShrinkLayerConfig(LayerConfigBase):
    """尾盘缩量程度因子分层配置

    薄声明：仅定义因子名称与分层命名，逻辑完全下沉基类。

    因子含义：
    - factor_value < 1：尾盘成交量占比小于全天，数值越小表示尾盘缩量越明显
    - factor_value 接近 1：尾盘成交量接近全天成交量（异常情况）
    - 通常范围：A股尾盘成交量占比约 10%-30%
    """

    factor_name: ClassVar[str] = "tail_volume_shrink"

    layer_names: ClassVar[Sequence[str]] = (
        "lowest",
        "lower",
        "normal",
        "higher",
        "highest",
    )

    layer_descriptions: ClassVar[Sequence[str]] = (
        "极低层(缩量最明显，尾盘成交量占比极低)",
        "偏低层(缩量较明显)",
        "正常层(尾盘成交量占比适中)",
        "偏高层(缩量不明显)",
        "极高层(尾盘成交量占比高，接近或超过全天)",
    )


if __name__ == "__main__":
    factor_cli_main(
        config_cls=TailVolumeShrinkLayerConfig,
        factor_calculator=calculate_tail_volume_shrink,
    )