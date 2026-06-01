#!/usr/bin/env python3
"""
隔夜收益率因子分层回测脚本

使用 factor_cli_main 公共入口，薄封装仅声明因子特异配置。

因子定义：
- 公式: overnight_ret = (今日开盘 - 昨日收盘) / 昨日收盘
- 含义: 隔夜涨跌幅（非交易时段价格变化）
- 理论范围: [-0.1, 0.1]（A股涨跌幅限制）
- 实测范围: [-0.67, 0.11]（含新股/复牌等极端情况）

策略逻辑（正向因子）：
- 高值层做多（Layer4-5，隔夜涨幅大）
- 低值层做空（Layer1-2，隔夜跌幅大）

分层模式：
- percentile 分层（MODULE.md 强制规范，由公共模块硬编码）
- 5 层（每层 20%）

作者: 云瑶
创建日期: 2026-05-28
"""

from dataclasses import dataclass, field
from typing import Dict, Literal, ClassVar, Any

from backtest.common.layered_backtest_runner import LayerConfigBase
from backtest.common.factor_cli import factor_cli_main
from data_fetchers.factor_calculator import calculate_overnight_return


@dataclass
class OvernightRetLayerConfig(LayerConfigBase):
    """隔夜收益因子分层配置
    
    因子元数据：
    - factor_name: 因子名称（单一来源）
    - ic_meta: IC 分析结果（单一来源）
    
    分层配置：
    - n_layers: 分层数量（显式声明，避免隐式耦合）
    - layer_names: 分层命名（业务语义描述）
    - factor_direction: 因子方向（由 ic_meta.ic_mean > 0 决定）
    
    多空组合由基类按 factor_direction 自动派生。
    """
    
    # === 因子元数据（单一来源） ===
    factor_name: ClassVar[str] = 'overnight_ret'
    
    ic_meta: ClassVar[Dict[str, Any]] = {
        'date': '2026-05-28',
        'source': 'factor_ic/result/ic_overnight_ret_1d_analysis_result.json',
        'ic_mean': 0.021187,
        'icir': 0.2106,
        'p_value': 7.87e-07,
        'direction': 'positive',  # ic_mean > 0
    }
    
    # === 分层配置 ===
    n_layers: int = 5  # 显式声明层数，避免与 layer_names 隐式耦合
    
    layer_names: Dict[str, str] = field(default_factory=lambda: {
        '1': '极低层(隔夜跌幅最大)',
        '2': '偏低层(隔夜小幅下跌)',
        '3': '正常层(隔夜变化不大)',
        '4': '偏高层(隔夜小幅上涨)',
        '5': '极高层(隔夜涨幅最大)'
    })
    
    factor_direction: Literal['positive', 'negative'] = 'positive'  # 由 ic_meta 决定


if __name__ == '__main__':
    factor_cli_main(
        factor_name=OvernightRetLayerConfig.factor_name,
        config_cls=OvernightRetLayerConfig,
        factor_calculator=calculate_overnight_return,
        description=f'{OvernightRetLayerConfig.factor_name} 因子分层回测'
    )