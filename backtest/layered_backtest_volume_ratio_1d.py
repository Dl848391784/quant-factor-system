#!/usr/bin/env python3
"""
量比因子分层回测脚本

使用公共入口 run_layered_backtest，代码量从 ~370 行降至 ~80 行。

因子定义：
- 量比(volume_ratio) = 当日成交量 / 过去N日平均成交量
- 本脚本使用 volume_ratio_5（5日平均成交量基准）
- 量比<1: 成交量低于均值（缩量）
- 量比>1: 成交量高于均值（放量）

数据来源：
- 缓存数据：DEFAULT_CACHE_DIR/factor_data.json.gz（默认为项目根目录/cache/factor_data）
- 因子列：volume_ratio_5（已预计算）
- 注：可通过 --cache_dir 参数指定其他缓存目录

输出：
- 分层回测结果：backtest/result/volume_ratio_layered_backtest.json
- 每日收益数据：backtest/result/volume_ratio_layered_backtest_daily.json.gz
- 注：可通过 --output_dir 参数指定其他输出目录

CLI 参数：
- --cache_dir: 缓存目录路径（默认：None，使用 DEFAULT_CACHE_DIR）
- --output_dir: 输出目录路径（默认：None，使用 backtest/result）
- --quiet: 静默模式（默认：False）

规范:
- 遵循 PROJECT.md 公共模块强制复用规范
- 命名遵循 MODULE.md: layered_backtest_<因子名>_<收益周期>.py

作者: 云瑶
创建日期: 2026-05-23
重构日期: 2026-05-23（使用公共入口）
"""

# 标准库
import sys
from pathlib import Path
from dataclasses import dataclass, field
from typing import List, Dict as TypingDict

# 本地模块
sys.path.insert(0, str(Path(__file__).parent.parent))

from backtest.common.layered_backtest_runner import (
    run_layered_backtest,
    LayerConfigBase,
    create_cli_entrypoint
)
from backtest.common.logger_config import get_logger

logger = get_logger(__name__)


@dataclass
class VolumeRatioLayerConfig(LayerConfigBase):
    """量比分层配置
    
    因子方向说明（基于IC测试结果）：
    - IC均值 = -0.029（负相关，显著）
    - 高量比 → 未来收益倾向于更低（放量可能预示见顶）
    - 低量比 → 未来收益倾向于更高（缩量可能预示反弹）
    - factor_direction='negative' 意味着：低量比做多，高量比做空
    
    策略逻辑：
    - Layer1/Layer2（缩量）→ 做多（量比<1，成交量低于均值）
    - Layer4/Layer5（放量）→ 做空（量比>1.5，成交量高于均值）
    - Layer3（正常）→ 不参与（量比接近均值，方向不明确）
    
    策略类型说明（必须明确）：
    - 这是均值回归策略，而非趋势跟随策略
    - 低量比做多基于"缩量可能预示反弹"的均值回归逻辑
    - 高量比做空基于"放量可能预示见顶"的均值回归逻辑
    - 若需趋势跟随策略（放量做多），请调整 factor_direction='positive'
    
    实际数据特征（基于全量统计）：
    - 数据范围：[0.1, 4.97]，无负值和零值
    - 均值：1.01（接近基准）
    - 中位数：0.94（小于1，说明大部分数据在缩量区间）
    - Layer1数据占比：1.39%（ratio<0.5）
    - Layer5数据占比：2.23%（ratio>2）
    
    阈值边界依赖说明（runner 实现）：
    - fixed_threshold 模式：[thresholds[i], thresholds[i+1]) 归入 Layer (i+1)
    - 最大边界使用 ≥，包括越界值（如量比>5）
    - 最小边界以下归入 Layer1（如量比<0，防御性设计）
    - 注：实际数据无负值和越界值，阈值设计为防御性预留
    """
    
    layer_thresholds: List[float] = field(default_factory=lambda: [0, 0.5, 1.0, 1.5, 2.0, 5.0])
    
    layer_names: TypingDict[str, str] = field(default_factory=lambda: {
        '1': '极缩量层(ratio<0.5，含越界值<0)',
        '2': '缩量层(0.5≤ratio<1)',
        '3': '正常层(1≤ratio<1.5)',
        '4': '放量层(1.5≤ratio<2)',
        '5': '极放量层(ratio≥2，含越界值>5)'
    })
    
    factor_direction: str = 'negative'
    long_layers: List[int] = field(default_factory=lambda: [1, 2])
    short_layers: List[int] = field(default_factory=lambda: [4, 5])
    
    # layer_threshold_desc 与 thresholds 对应（5层）
    # 格式遵循 MODULE.md 第451行规范：完整区间 [lower, upper)，必须包含下界
    # 最大边界使用 ≥，说明越界值处理
    #
    # runner 分层逻辑说明（fixed_threshold 模式）：
    # - 低于最小阈值（ratio<0）→ 归入 Layer1（边界处理）
    # - 边界内循环归层：
    #   - Layer1: [0, 0.5) 区间（0 ≤ ratio < 0.5）
    #   - Layer2: [0.5, 1.0) 区间（0.5 ≤ ratio < 1.0）
    #   - Layer3: [1.0, 1.5) 区间（1.0 ≤ ratio < 1.5）
    #   - Layer4: [1.5, 2.0) 区间（1.5 ≤ ratio < 2.0）
    #   - Layer5: [2.0, 5.0] 区间（最后一层右闭：2.0 ≤ ratio ≤ 5.0）
    # - 高于最大阈值（ratio>5.0）→ 归入 Layer5（边界处理）
    #
    layer_threshold_desc: TypingDict[str, str] = field(default_factory=lambda: {
        '1': 'ratio < 0.5 (含越界值<0，极缩量，做多)',
        '2': '0.5 ≤ ratio < 1.0 (缩量，做多)',
        '3': '1.0 ≤ ratio < 1.5 (正常，不参与)',
        '4': '1.5 ≤ ratio < 2.0 (放量，做空)',
        '5': 'ratio ≥ 2.0 (含边界2.0，含越界值>5，极放量，做空)'
    })


main = create_cli_entrypoint(
    factor_name='volume_ratio',
    factor_col='volume_ratio_5',
    config_class=VolumeRatioLayerConfig
)

if __name__ == '__main__':
    main()