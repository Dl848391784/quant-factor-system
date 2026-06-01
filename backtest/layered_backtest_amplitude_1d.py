#!/usr/bin/env python3
"""
振幅因子分层回测脚本

使用 factor_cli_main 公共入口，薄封装仅声明因子特异配置。

因子定义：
- 公式: Amplitude = (High - Low) / Close
- 含义: 当日振幅相对于收盘价的比率，反映价格波动强度
- 范围: [0, +∞)，值越大波动越剧烈

IC 分析结果（2026-05-29）：
- IC 均值: -0.0591（负相关）
- ICIR: -0.51
- 高振幅 → 低收益

策略逻辑：
- 低振幅层做多（Layer1-2）
- 高振幅层做空（Layer4-5）

分层说明（percentile 模式，5层）：
- Layer1: 振幅最低 0-20%（波动平稳）
- Layer2: 振幅较低 20-40%
- Layer3: 振幅中位 40-60%
- Layer4: 振幅较高 60-80%
- Layer5: 振幅最高 80-100%（波动剧烈）

作者: 云瑶
创建日期: 2026-05-29
版本历史:
  v2.0 (2026-06-01): 使用 factor_cli_main 公共入口
  v3.0 (2026-06-01): 采用完整更新模式，从 IC 结果派生配置
"""

from dataclasses import dataclass, field
from typing import Dict, ClassVar, Any

from backtest.common.layered_backtest_runner import LayerConfigBase
from backtest.common.factor_cli import factor_cli_main
from data_fetchers.factor_calculator import calculate_amplitude


@dataclass
class AmplitudeLayerConfig(LayerConfigBase):
    """振幅因子分层配置
    
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
    factor_name: ClassVar[str] = 'amplitude'
    ic_source: ClassVar[str] = 'factor_ic/result/ic_amplitude_1d_analysis_result.json'
    
    # === 分层配置 ===
    layer_names: Dict[str, str] = field(default_factory=lambda: {
        '1': '低振幅层(波动平稳)',
        '2': '偏低振幅层',
        '3': '中振幅层',
        '4': '偏高振幅层',
        '5': '高振幅层(波动剧烈)'
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


if __name__ == '__main__':
    factor_cli_main(
        config_cls=AmplitudeLayerConfig,
        factor_calculator=calculate_amplitude
    )