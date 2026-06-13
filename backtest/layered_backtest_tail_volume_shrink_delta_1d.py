#!/usr/bin/env python3
"""
尾盘缩量差分因子分层回测脚本

遵循 PROJECT.md 分层回测脚本规范（薄声明模式）：
- 仅定义配置类，逻辑完全下沉基类 LayerConfigBase
- 因子方向从 IC 文件派生（factor_direction 由基类自动派生）
- layer_descriptions 使用 percentile 相对语义（禁止固定阈值数字）
- 必须传入 factor_calculator 参数（复杂因子分层回测，遵循 Pitfall #5）
- 遵循 H5: IC方向不预判,因子方向由 IC 文件派生
- 遵循 Pitfall #31: 显式声明 ic_source
- 遵循 Pitfall #32: layer_descriptions 使用 percentile 相对语义
- 遵循 Pitfall #33: layer_names 必须为5层

因子定义：
- tail_volume_shrink_delta = tail_volume_shrink(T) - tail_volume_shrink(T-1)
- 含义：尾盘从缩量转放量 = 资金开始介入; 继续缩量 = 冷清
- 有效天数约17天（尾盘数据只有18天有效样本）

作者: 云瑶
创建日期: 2026-06-11
版本历史:
  v1.0 (2026-06-11): 初始版本，复用 factor_calculator.calculate_tail_volume_shrink_delta
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
from data_fetchers.factor_calculator import calculate_tail_volume_shrink_delta  # noqa: E402


class TailVolumeShrinkDeltaLayerConfig(LayerConfigBase):
    """尾盘缩量差分因子分层回测配置（薄声明模式）

    因子含义：
    - delta > 0：缩量增加（尾盘比前一天更缩量）= 冷清加剧
    - delta < 0：缩量减少（尾盘从缩量转为放量）= 资金介入信号
    - delta ≈ 0：尾盘缩量程度基本不变
    """

    factor_name: ClassVar[str] = "tail_volume_shrink_delta"
    ic_source: ClassVar[str] = (
        "factor_ic/result/ic_tail_volume_shrink_delta_1d_analysis_result.json"  # Pitfall #31: 显式声明
    )
    layer_names: ClassVar[Sequence[str]] = (
        "lowest",
        "lower",
        "normal",
        "higher",
        "highest",
    )
    layer_descriptions: ClassVar[Sequence[str]] = (
        "极低层(缩量大幅减少，放量明显)",
        "偏低层(缩量略有减少)",
        "正常层(缩量程度基本不变)",
        "偏高层(缩量略有增加)",
        "极高层(缩量大幅增加，冷清加剧)",
    )


if __name__ == "__main__":
    # 复杂因子：必须传入 factor_calculator（遵循 Pitfall #5 + factor-development skill Pattern 5）
    factor_cli_main(
        TailVolumeShrinkDeltaLayerConfig,
        factor_calculator=calculate_tail_volume_shrink_delta,
    )
