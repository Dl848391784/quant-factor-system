#!/usr/bin/env python3
"""
价格位置因子分层回测脚本

使用公共入口 run_layered_backtest。

规范:
- 遵循 PROJECT.md 公共模块强制复用规范
- 命名遵循 MODULE.md: layered_backtest_<因子名>_<收益周期>.py

因子说明:
- 公式: Price Position = (Close - Low) / (High - Low)
- 含义: 收盘价在全天振幅中的相对位置
- 范围: [0, 1]
  - 0 = 收盘价等于最低价（全天最低收盘）
  - 1 = 收盘价等于最高价（全天最高收盘）
  - 0.5 = 收盘价在振幅中位

IC 分析结果:
- IC 均值: -0.0131（负相关）
- ICIR: 0.10
- 因子方向: negative（低价格位置 → 未来收益更高）

策略逻辑:
- 低价格位置（收盘接近最低价）→ 可能反弹，做多
- 高价格位置（收盘接近最高价）→ 可能回落，做空

作者: 云瑶
创建日期: 2026-05-29
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
    LayerConfigBase
)
from backtest.common.logger_config import get_logger
from data_fetchers.factor_calculator import calculate_price_position

logger = get_logger(__name__)


@dataclass
class PricePositionLayerConfig(LayerConfigBase):
    """价格位置因子分层配置
    
    分层说明（percentile 模式，5层，每层20%）:
    - Layer1: 价格位置最低 0-20%（收盘接近最低价）→ 做多
    - Layer2: 价格位置较低 20-40% → 做多
    - Layer3: 价格位置中位 40-60% → 中性
    - Layer4: 价格位置较高 60-80% → 做空
    - Layer5: 价格位置最高 80-100%（收盘接近最高价）→ 做空
    
    因子方向（negative）:
    - 价格位置越低 → 未来收益越高
    - Layer1/Layer2 做多，Layer4/Layer5 做空
    """
    
    layer_names: TypingDict[str, str] = field(default_factory=lambda: {
        '1': '低位层(收盘近最低)',
        '2': '偏低位层',
        '3': '中位层',
        '4': '偏高位层',
        '5': '高位层(收盘近最高)'
    })
    
    factor_direction: str = 'negative'
    long_layers: List[int] = field(default_factory=lambda: [1, 2])
    short_layers: List[int] = field(default_factory=lambda: [4, 5])


def main():
    """分层回测主入口"""
    import argparse
    parser = argparse.ArgumentParser(description='价格位置因子分层回测')
    parser.add_argument('--data_source', type=str, default=None,
                        help='数据源文件路径')
    parser.add_argument('--output_dir', type=str, default=None,
                        help='输出目录路径')
    parser.add_argument('--quiet', action='store_true',
                        help='静默模式')
    args = parser.parse_args()
    
    try:
        result = run_layered_backtest(
            factor_name='price_position',
            factor_col='price_position',
            config=PricePositionLayerConfig(),
            factor_calculator=calculate_price_position,
            required_factor_cols=['close', 'high', 'low'],
            data_source=args.data_source,
            output_dir=args.output_dir,
            verbose=not args.quiet,
            logger=logger
        )
        
        if result['meta']['n_days_total'] == 0:
            logger.error("回测无有效数据，程序终止")
            sys.exit(1)
        
        # 结果摘要日志
        logger.info("=" * 60)
        logger.info("回测结果摘要")
        logger.info("=" * 60)
        logger.info(f"因子名称: {result['meta']['factor_name']}")
        logger.info(f"回测周期: {result['meta']['n_days_total']} 天")
        
        # 各分层收益
        layer_returns = result.get('layer_returns', {})
        for layer_name, ret in layer_returns.items():
            logger.info(f"Layer {layer_name} 累计收益: {ret:.4f}")
        
        # 多空组合收益
        long_short = result.get('long_short', {})
        if long_short:
            logger.info(f"多空组合累计收益: {long_short.get('cumulative_return', 0):.4f}")
            logger.info(f"夏普比率: {long_short.get('sharpe_ratio', 0):.2f}")
            logger.info(f"最大回撤: {long_short.get('max_drawdown', 0):.2%}")
        
        logger.info("回测完成")
        sys.exit(0)
        
    except FileNotFoundError:
        logger.exception("数据文件不存在")
        sys.exit(2)
    except KeyError:
        logger.exception("数据字段缺失")
        sys.exit(3)
    except ValueError:
        logger.exception("数据值异常")
        sys.exit(4)
    except Exception:
        logger.exception("回测执行异常")
        sys.exit(5)


if __name__ == '__main__':
    main()