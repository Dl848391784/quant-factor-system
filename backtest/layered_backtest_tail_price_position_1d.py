#!/usr/bin/env python3
"""
尾盘价格位置因子分层回测脚本

因子定义：
- 尾盘价格位置 = (收盘价 - 尾盘最低价) / (尾盘最高价 - 尾盘最低价)
- 收盘价 = prices[-1]（尾盘最后一根K线收盘价，即15:00收盘价）
- 含义：收盘价在尾盘价格区间的相对位置，理论范围 [0, 1]

分层模式：percentile 5层（每层约20%）

因子元数据派生机制（基类 LayerConfigBase）：
- factor_direction: 从 ic_source IC 文件加载，ic_mean = -0.0613 为 negative
- n_layers: 由 len(layer_names) 派生
- long_layers/short_layers: 由 n_layers 和 factor_direction 派生

数据依赖：
- factor_ic_data.json.gz（主数据源，已预计算尾盘因子列）

设计说明（2026-06-04）：
- 尾盘因子在 factor_generator.py 中已预计算并写入统一数据源
- 分层回测不传递 factor_calculator 参数，直接读取数据源中的预计算因子列
- 历史问题：传递 factor_calculator 会重复添加因子列，导致列名重复、reindex 失败

作者: 云瑶
创建日期: 2026-06-02
版本历史:
  v1.0 (2026-06-02): 初始版本，实现尾盘价格位置因子分层回测
  v1.1 (2026-06-02): 优化 - 创建流程文档、测试文件 test_layered_backtest_tail_price_position_1d.py（8个测试用例）
  v1.2 (2026-06-02): 优化 - 测试补充至13个（新增ic_source_resolved/factor_col_resolved/layer_names_dict/默认参数验证）
  v1.3 (2026-06-04): Bug修复 - 移除 factor_calculator 参数，避免重复列名导致的 reindex 错误
"""

import sys
from collections.abc import Sequence
from pathlib import Path
from typing import ClassVar


# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent.parent))

# 本地模块导入
from backtest.common.factor_cli import factor_cli_main
from backtest.common.layered_backtest_runner import LayerConfigBase


class TailPricePositionLayerConfig(LayerConfigBase):
    """尾盘价格位置因子分层配置

    薄声明：仅定义因子名称与分层命名，逻辑完全下沉基类。
    """

    factor_name: ClassVar[str] = "tail_price_position"

    layer_names: ClassVar[Sequence[str]] = ("lowest", "lower", "normal", "higher", "highest")

    layer_descriptions: ClassVar[Sequence[str]] = (
        "极低层(价格位置≈0，收盘在区间底部)",
        "偏低层(价格位置偏低)",
        "正常层(价格位置适中≈0.5)",
        "偏高层(价格位置偏高)",
        "极高层(价格位置≈1，收盘在区间顶部)",
    )


if __name__ == "__main__":
    # 尾盘因子是预计算因子，已在 factor_ic_data.json.gz 中
    # 不传递 factor_calculator，直接使用数据源中的因子列
    factor_cli_main(config_cls=TailPricePositionLayerConfig)
