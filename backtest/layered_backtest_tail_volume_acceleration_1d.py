#!/usr/bin/env python3
"""
尾盘量能加速度因子分层回测脚本

因子定义：
- 前半段成交量总和 = sum(volumes[0:6])  # 14:00-14:25
- 后半段成交量总和 = sum(volumes[7:13])  # 14:35-15:00
- 量能加速度 = 后半段 / 前半段

分层模式：percentile 5层（每层约20%）

因子元数据派生机制（基类 LayerConfigBase）：
- factor_direction: 从 ic_source IC 文件加载，ic_mean = -0.0148 < 0 → negative
- n_layers: 由 len(layer_names) 派生 → 5
- long_layers/short_layers: 由 n_layers 和 factor_direction 派生

数据依赖：
- factor_ic_data.json.gz（主数据源）
- tail_trading_data.json.gz（尾盘5分钟K线数据）

作者: 云瑶
创建日期: 2026-06-02
版本历史:
  v1.0 (2026-06-02): 初始版本，实现尾盘量能加速度因子分层回测
  v1.1 (2026-06-02): Round 1 优化 - 导入分组注释、版本历史完善
  v1.2 (2026-06-02): Round 2 优化 - ClassVar 类型注解确认（Sequence[str]）
  v1.3 (2026-06-02): Round 3 优化 - 边界处理下沉基类确认（薄声明模式无额外代码）
  v1.4 (2026-06-02): Round 4 优化 - Spec Compliance 确认（对照 tail_price_slope 脚本合规）
  v1.5 (2026-06-02): Round 5 优化 - ClassVar/边界处理双确认（薄声明模式完整）
  v1.6 (2026-06-02): Round 6 优化 - 流程文档版本同步
"""

# 标准库导入
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import ClassVar


# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent.parent))

# 本地模块导入
from backtest.common.factor_cli import factor_cli_main
from backtest.common.layered_backtest_runner import LayerConfigBase
from factor_ic.ic_tail_volume_acceleration_1d import calculate_tail_volume_acceleration


class TailVolumeAccelerationLayerConfig(LayerConfigBase):
    """尾盘量能加速度因子分层配置

    薄声明：仅定义因子名称与分层命名，逻辑完全下沉基类。
    """

    factor_name: ClassVar[str] = "tail_volume_acceleration"

    layer_names: ClassVar[Sequence[str]] = (
        "lowest",
        "lower",
        "normal",
        "higher",
        "highest",
    )

    layer_descriptions: ClassVar[Sequence[str]] = (
        "极低层(量能减速最明显，后半段成交量远小于前半段)",
        "偏低层(量能减速较明显)",
        "正常层(量能加速度适中)",
        "偏高层(量能加速较明显)",
        "极高层(量能加速最明显，后半段成交量远大于前半段)",
    )


if __name__ == "__main__":
    factor_cli_main(
        config_cls=TailVolumeAccelerationLayerConfig,
        factor_calculator=calculate_tail_volume_acceleration,
    )
