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
版本历史:
  v3.0 (2026-06-01): 采用完整更新模式，从 IC 结果派生配置
"""

from dataclasses import dataclass, field
from typing import Dict, ClassVar, Any

from backtest.common.layered_backtest_runner import LayerConfigBase
from backtest.common.factor_cli import factor_cli_main
from data_fetchers.factor_calculator import calculate_overnight_return


@dataclass
class OvernightRetLayerConfig(LayerConfigBase):
    """隔夜收益因子分层配置
    
    因子元数据：
    - factor_name: 因子名称（单一来源）
    - ic_source: IC 分析结果 JSON 路径（单一来源，按需懒加载）
    
    分层配置：
    - layer_names: 分层命名（业务语义描述）
    - n_layers: 由 len(layer_names) 派生（避免双重声明）
    - factor_direction: 由 ic_meta['direction'] 派生（避免双重声明）
    
    多空组合由基类按 factor_direction 自动派生。
    """
    
    # === 因子元数据（单一来源） ===
    factor_name: ClassVar[str] = 'overnight_ret'
    ic_source: ClassVar[str] = 'factor_ic/result/ic_overnight_ret_1d_analysis_result.json'
    
    # === 分层配置 ===
    layer_names: Dict[str, str] = field(default_factory=lambda: {
        '1': '极低层(隔夜跌幅最大)',
        '2': '偏低层(隔夜小幅下跌)',
        '3': '正常层(隔夜变化不大)',
        '4': '偏高层(隔夜小幅上涨)',
        '5': '极高层(隔夜涨幅最大)'
    })
    
    def __post_init__(self):
        """初始化后处理：校验并派生配置
        
        校验：
        - layer_names 长度 >= 2
        
        派生：
        - n_layers: 由 len(layer_names) 派生
        - factor_direction: 由 ic_meta['direction'] 派生（按需懒加载）
        - long_layers/short_layers: 由基类 _derive_long_short() 派生
        """
        # 校验 layer_names 长度
        n = len(self.layer_names)
        if n < 2:
            raise ValueError(f"layer_names 至少需要 2 层，当前: {n}")
        
        # 派生 n_layers（删除冗余声明）
        self.n_layers = n
        
        # 派生 factor_direction（从 ic_meta 按需加载）
        ic_meta = self._load_ic_meta()
        self.factor_direction = ic_meta.get('direction', 'positive')
        
        # 调用基类派生多空组合
        super().__post_init__()
    
    def _load_ic_meta(self) -> Dict[str, Any]:
        """按需懒加载 IC 分析结果
        
        从 ic_source JSON 文件读取，避免硬编码数值漂移。
        
        返回：
            IC 元数据字典（含 direction、ic_mean、icir 等）
        
        注意：
            IC 结果文件可能没有 'direction' 字段，需从 ic_mean 符号派生。
        """
        import json
        from pathlib import Path
        
        # 项目根目录
        project_root = Path(__file__).parent.parent
        ic_file = project_root / self.ic_source
        
        if not ic_file.exists():
            raise FileNotFoundError(
                f"IC 分析结果文件不存在: {ic_file}\n"
                f"请先运行对应的 IC 分析脚本生成结果"
            )
        
        with open(ic_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        # 提取 IC 元数据
        ic_metrics = data.get('ic_metrics', {})
        if not ic_metrics:
            # 旧格式：顶层字段
            ic_metrics = data
        
        # 派生 direction（若缺失则从 ic_mean 符号推断）
        direction = data.get('direction')
        if direction is None:
            ic_mean = ic_metrics.get('ic_mean', 0)
            direction = 'negative' if ic_mean < 0 else 'positive'
        
        return {
            'direction': direction,
            'ic_mean': ic_metrics.get('ic_mean'),
            'icir': ic_metrics.get('icir'),
            'p_value': ic_metrics.get('p_value'),
        }


if __name__ == '__main__':
    factor_cli_main(
        config_cls=OvernightRetLayerConfig,
        factor_calculator=calculate_overnight_return
    )