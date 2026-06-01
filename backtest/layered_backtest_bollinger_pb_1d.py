#!/usr/bin/env python3
"""
布林带 %B 因子分层回测脚本

使用 factor_cli_main 公共入口，薄封装仅声明因子特异配置。

因子定义：
- 公式: %B = (Close - Lower) / (Upper - Lower)
- 含义: 收盘价在布林带中的相对位置
- 范围: (-∞, +∞)，>1 超买，<0 超卖

IC 分析结果：
- IC 均值: 负相关（高位回落）
- 高 %B → 低未来收益

策略逻辑：
- 低 %B 层做多（超卖反弹）
- 高 %B 层做空（超买回落）

作者: 云瑶
创建日期: 2026-05-23
版本历史:
  v2.0 (2026-06-01): 使用 factor_cli_main 公共入口
  v3.0 (2026-06-01): 采用完整更新模式，从 IC 结果派生配置
"""

from dataclasses import dataclass, field
from typing import Dict, ClassVar, Any, Callable
from functools import partial
import argparse

from backtest.common.layered_backtest_runner import LayerConfigBase
from backtest.common.factor_cli import factor_cli_main
from data_fetchers.factor_calculator import calculate_bollinger_pb

DEFAULT_N = 20


@dataclass
class BollingerPBLayerConfig(LayerConfigBase):
    """布林带 PB 因子分层配置
    
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
    factor_name: ClassVar[str] = 'bollinger_pb'
    ic_source: ClassVar[str] = 'factor_ic/result/ic_bollinger_pb_1d_analysis_result.json'
    
    # === 分层配置 ===
    layer_names: Dict[str, str] = field(default_factory=lambda: {
        '1': '超卖层(PB<0.5)',
        '2': '偏弱层(0.5≤PB<0.8)',
        '3': '正常层(0.8≤PB<1.2)',
        '4': '偏强层(1.2≤PB<1.5)',
        '5': '超买层(PB≥1.5)'
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
        self.factor_direction = ic_meta.get('direction', 'negative')
        
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


def add_bollinger_args(parser: argparse.ArgumentParser) -> None:
    """添加自定义 CLI 参数"""
    parser.add_argument('--bollinger-n', type=int, default=DEFAULT_N,
                        help=f'布林带计算窗口，默认 {DEFAULT_N}')


def setup_bollinger_calculator(args: argparse.Namespace, calc) -> Callable:
    """包装 factor_calculator"""
    return partial(calc, n=args.bollinger_n)


if __name__ == '__main__':
    factor_cli_main(
        config_cls=BollingerPBLayerConfig,
        factor_calculator=calculate_bollinger_pb,
        add_cli_args=add_bollinger_args,
        setup_calculator=setup_bollinger_calculator
    )