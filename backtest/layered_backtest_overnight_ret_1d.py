#!/usr/bin/env python3
"""
隔夜收益率因子分层回测脚本

使用 factor_cli_main 公共入口，脚本压缩至 ~30 行。

因子定义：
- 公式: overnight_ret = (今日开盘 - 昨日收盘) / 昨日收盘
- 含义: 隔夜涨跌幅（非交易时段价格变化）
- 理论范围: [-0.1, 0.1]（A股涨跌幅限制）
- 实测范围: [-0.67, 0.11]（含新股/复牌等极端情况）

IC 分析结果（2026-05-28，factor_ic/result/ic_overnight_ret_1d_analysis_result.json）：
- IC 均值: 0.021187（正相关）
- ICIR: 0.2106
- p 值: 7.87e-07（统计显著）
- 因子方向: 正向因子（分层回测做多高值组）

策略逻辑：
- 高值层做多（Layer4-5）
- 低值层做空（Layer1-2）

分层说明（percentile 模式，5层）：
- Layer1: 0-20%分位（极低，隔夜跌幅最大）
- Layer2: 20-40%分位（偏低）
- Layer3: 40-60%分位（正常）
- Layer4: 60-80%分位（偏高）
- Layer5: 80-100%分位（极高，隔夜涨幅最大）

作者: 云瑶
创建日期: 2026-05-28
版本历史:
  v2.0 (2026-06-01): 使用 factor_cli_main 公共入口
  v2.1 (2026-06-01): 修正 factor_direction 为 'positive'（遵循 IC 分析结果）
  v2.2 (2026-06-01): 修正 layer_names 语义描述（移除误导性固定阈值），补充实测范围
  v2.3 (2026-06-01): 简化类 docstring（移除与模块 docstring 重复的 IC 分析结果）
  v2.4 (2026-06-01): 补充 pytest 测试文件（修复测试覆盖缺失）
"""

import sys
from pathlib import Path
from dataclasses import dataclass, field
from typing import Dict, Literal

if __name__ == '__main__':
    sys.path.insert(0, str(Path(__file__).parent.parent))

from backtest.common.layered_backtest_runner import LayerConfigBase
from backtest.common.factor_cli import factor_cli_main
from data_fetchers.factor_calculator import calculate_overnight_return


@dataclass
class OvernightRetLayerConfig(LayerConfigBase):
    """隔夜收益因子分层配置（正向因子）
    
    多空组合由基类 _derive_long_short() 自动派生：
    - 多头: Layer4-5（隔夜涨幅大）
    - 空头: Layer1-2（隔夜跌幅大）
    """
    
    layer_names: Dict[str, str] = field(default_factory=lambda: {
        '1': '极低层(隔夜跌幅最大)',
        '2': '偏低层(隔夜小幅下跌)',
        '3': '正常层(隔夜变化不大)',
        '4': '偏高层(隔夜小幅上涨)',
        '5': '极高层(隔夜涨幅最大)'
    })
    
    factor_direction: Literal['positive', 'negative'] = 'positive'  # IC 均值 0.021187 > 0


if __name__ == '__main__':
    factor_cli_main(
        factor_name='overnight_ret',
        config_cls=OvernightRetLayerConfig,
        factor_calculator=calculate_overnight_return,
        description='隔夜收益率因子分层回测'
    )