#!/usr/bin/env python3
"""
尾盘位置差分因子分层回测脚本

遵循 PROJECT.md 分层回测脚本规范（薄声明模式）：
- 仅定义配置类，逻辑完全下沉基类 LayerConfigBase
- 因子方向从 IC 文件派生（factor_direction 由基类自动派生）
- layer_descriptions 使用 percentile 相对语义（禁止固定阈值数字）
- 必须传入 factor_calculator 参数（复杂因子分层回测，遵循 Pitfall #5）
- 遵循 H5: IC方向不预判，因子方向由 IC 文件派生
- 遵循 Pitfall #31: 显式声明 ic_source
- 遵循 Pitfall #32: layer_descriptions 使用 percentile 相对语义
- 遵循 Pitfall #33: layer_names 必须为5层

因子定义：
- tail_price_position_delta = tail_price_position(T) - tail_price_position(T-1)
- 含义：尾盘从最低价回升 = 买盘开始进场；继续走低 = 卖方主导
- 有效天数约17天（尾盘数据只有18天有效样本）

作者: 云瑶
创建日期: 2026-06-11
版本历史:
  v1.0 (2026-06-11): 初始版本，复用 factor_calculator.calculate_tail_price_position_delta
"""

import sys
from collections.abc import Sequence
from pathlib import Path
from typing import ClassVar


# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent.parent))

# 导入因子计算函数（遵循 MODULE.md 约束 #3：从 factor_calculator 复用）
from backtest.common.factor_cli import factor_cli_main  # noqa: E402
from backtest.common.layered_backtest_runner import LayerConfigBase  # noqa: E402
from data_fetchers.factor_calculator import calculate_tail_price_position_delta  # noqa: E402


class TailPricePositionDeltaLayerConfig(LayerConfigBase):
    """尾盘位置差分因子分层回测配置（薄声明模式）

    因子含义：
    - delta > 0：尾盘位置回升（从低点转向高点）= 买盘进场信号
    - delta < 0：尾盘位置下降（从高点转向低点）= 卖方主导信号
    - delta ≈ 0：尾盘位置不变
    """

    factor_name: ClassVar[str] = "tail_price_position_delta"
    ic_source: ClassVar[str] = (
        "ic_tail_price_position_delta_1d_analysis_result.json"  # 纯文件名，基类补充 pipeline 感知目录
    )
    layer_names: ClassVar[Sequence[str]] = (
        "lowest",
        "lower",
        "normal",
        "higher",
        "highest",
    )
    layer_descriptions: ClassVar[Sequence[str]] = (
        "极低层(尾盘位置大幅下降，卖方主导加剧)",
        "偏低层(尾盘位置略有下降)",
        "正常层(尾盘位置基本不变)",
        "偏高层(尾盘位置略有回升)",
        "极高层(尾盘位置大幅回升，买盘进场信号)",
    )


if __name__ == "__main__":
    # 复杂因子：必须传入 factor_calculator（遵循 Pitfall #5 + factor-development skill Pattern 5）
    factor_cli_main(
        TailPricePositionDeltaLayerConfig,
        factor_calculator=calculate_tail_price_position_delta,
    )
