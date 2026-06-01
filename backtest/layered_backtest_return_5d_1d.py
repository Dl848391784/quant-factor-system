#!/usr/bin/env python3
"""
5日累计涨幅因子分层回测脚本

使用 factor_cli_main 公共入口，薄封装仅声明因子特异配置。

因子定义：
- 公式: return_5d = close[t] / close[t-5] - 1
- 含义: 过去5日累计涨跌幅
- 理论范围: [-0.5, 0.5]（A股日涨跌幅±10%）

策略逻辑（反向因子）：
- 低值层做多（Layer1-2，涨幅小或下跌）
- 高值层做空（Layer4-5，涨幅大）

分层模式：
- percentile 分层（MODULE.md 强制规范，由公共模块硬编码）
- 5 层（每层 20%）

作者: 云瑶
创建日期: 2026-05-29
"""

from dataclasses import dataclass, field
from typing import Dict, Literal, ClassVar, Any

from backtest.common.layered_backtest_runner import LayerConfigBase
from backtest.common.factor_cli import factor_cli_main
from data_fetchers.factor_calculator import calculate_return_5d


@dataclass
class Return5dLayerConfig(LayerConfigBase):
    """5日收益因子分层配置
    
    因子元数据：
    - factor_name: 因子名称（单一来源）
    - ic_meta: IC 分析结果（单一来源）
    
    分层配置：
    - n_layers: 分层数量（显式声明，避免隐式耦合）
    - layer_names: 分层命名（业务语义描述）
    - factor_direction: 因子方向（由 ic_meta.ic_mean < 0 决定）
    
    多空组合由基类按 factor_direction 自动派生。
    """
    
    # === 因子元数据（单一来源） ===
    factor_name: ClassVar[str] = 'return_5d'
    
    ic_meta: ClassVar[Dict[str, Any]] = {
        'date': '2026-05-29',
        'source': 'factor_ic/result/ic_return_5d_1d_analysis_result.json',
        'ic_mean': -0.0591,  # 负相关（动量反转）
        'icir': 0.2106,
        'p_value': 7.87e-07,
        'direction': 'negative',  # ic_mean < 0
    }
    
    # === 分层配置 ===
    n_layers: int = 5  # 显式声明层数，避免与 layer_names 隐式耦合
    
    layer_names: Dict[str, str] = field(default_factory=lambda: {
        '1': '极低层(5日涨幅最小)',
        '2': '偏低层(5日小幅下跌)',
        '3': '正常层(5日变化不大)',
        '4': '偏高层(5日小幅上涨)',
        '5': '极高层(5日涨幅最大)'
    })
    
    factor_direction: Literal['positive', 'negative'] = 'negative'  # 由 ic_meta 决定


if __name__ == '__main__':
    factor_cli_main(
        factor_name=Return5dLayerConfig.factor_name,
        config_cls=Return5dLayerConfig,
        factor_calculator=calculate_return_5d,
        description=f'{Return5dLayerConfig.factor_name} 因子分层回测'
    )
