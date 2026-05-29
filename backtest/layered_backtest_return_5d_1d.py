#!/usr/bin/env python3
"""
5日累计涨幅因子分层回测脚本

使用公共入口 run_layered_backtest。

规范:
- 遵循 PROJECT.md 公共模块强制复用规范
- 命名遵循 MODULE.md: layered_backtest_<因子名>_<收益周期>.py

因子说明:
- 公式: Return_5d = close[t] / close[t-5] - 1
- 含义: 过去5日累计涨跌幅
- 范围: [-∞, +∞)，A股日涨跌幅±10%，5日累计约±50%
  - 正值 → 上涨
  - 负值 → 下跌

IC 分析结果:
- IC 均值: -0.0337（负相关）
- ICIR: 0.21
- t 统计量: -5.51（统计显著）
- 因子方向: negative
- 有效天数: 509
- 经济显著性: moderate（|IC均值|≥0.03）

分层回测结果:
- 多空组合年化收益: 2.76%
- 夏普比率: 0.25
- 单调性: -0.1391 (moderate)
- **未通过筛选标准**：单调性和多空收益不达标

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
from data_fetchers.factor_calculator import calculate_return_5d

logger = get_logger(__name__)


@dataclass
class Return5dLayerConfig(LayerConfigBase):
    """5日累计涨幅因子分层配置
    
    分层说明（percentile 模式，5层，每层20%）:
    - Layer1: 涨幅最低 0-20%（近期下跌最多）
    - Layer2: 涨幅较低 20-40%
    - Layer3: 涨幅中位 40-60%
    - Layer4: 涨幅较高 60-80%
    - Layer5: 涨幅最高 80-100%（近期上涨最多）
    
    因子方向（根据 IC 结果确定）:
    - IC 均值 -0.0337（负相关）
    - 高涨幅 → 低收益（动量反转效应）
    - 低涨幅层做多，高涨幅层做空
    """
    
    layer_names: TypingDict[str, str] = field(default_factory=lambda: {
        '1': '低涨幅层(近期下跌)',
        '2': '偏低涨幅层',
        '3': '中涨幅层',
        '4': '偏高涨幅层',
        '5': '高涨幅层(近期上涨)'
    })
    
    factor_direction: str = 'negative'  # 待 IC 结果确认
    long_layers: List[int] = field(default_factory=lambda: [1, 2])  # 低涨幅层做多
    short_layers: List[int] = field(default_factory=lambda: [4, 5])  # 高涨幅层做空


def main():
    """分层回测主入口"""
    import argparse
    parser = argparse.ArgumentParser(description='5日累计涨幅因子分层回测')
    parser.add_argument('--data_source', type=str, default=None,
                        help='数据源文件路径')
    parser.add_argument('--output_dir', type=str, default=None,
                        help='输出目录路径')
    parser.add_argument('--quiet', action='store_true',
                        help='静默模式')
    args = parser.parse_args()
    
    try:
        result = run_layered_backtest(
            factor_name='return_5d',
            factor_col='return_5d',
            config=Return5dLayerConfig(),
            factor_calculator=calculate_return_5d,
            required_factor_cols=['close', 'asset', 'date'],
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