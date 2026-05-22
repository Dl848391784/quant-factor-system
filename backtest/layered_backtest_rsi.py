"""
RSI 因子分层回测入口脚本

功能:
1. 加载 RSI 因子数据
2. 配置 RSI 分层参数
3. 调用通用分层回测引擎
4. 输出结果到 cache/backtest/

规范:
- 命名遵循 MODULE.md: layered_backtest_<因子名>.py
- 日志遵循 PROJECT.md: 使用 logging 模块
- 数据加载使用缓存，不截断

作者: 云瑶
创建日期: 2026-05-11
修订日期: 2026-05-22（重命名 + 日志规范化）
"""

import os
import json
import gzip
import pandas as pd
from datetime import datetime
from typing import Dict, Optional

# 导入公共日志模块（遵循 PROJECT.md 日志规范）
from factor_ic.common.logger_config import get_logger

logger = get_logger(__name__)

# 导入公共类型转换模块（遵循 PROJECT.md 强制复用规范）
from factor_ic.common.convert_types import convert_to_native_types

from backtest.common.layered_backtest import LayeredBacktestEngine


class RSILayerConfig:
    """RSI分层配置"""
    
    # 固定阈值分层（推荐）
    LAYER_THRESHOLDS = [0, 20, 40, 60, 80, 100]
    
    # 分层命名
    LAYER_NAMES = {
        1: '超卖层',
        2: '弱势层', 
        3: '中性层',
        4: '强势层',
        5: '超买层'
    }
    
    # 因子方向（重要：RSI是反向因子）
    FACTOR_DIRECTION = 'negative'  # 反向因子
    
    # 多空组合（反向因子：买超卖、卖超买）
    LONG_LAYERS = [1, 2]   # 多头：超卖+弱势（预期收益高）
    SHORT_LAYERS = [4, 5]  # 空头：强势+超买（预期收益低）
    
    # RSI阈值说明（边界值明确归属规则）
    # 边界值归属原则：边界值归入下一层（向上进位）
    LAYER_THRESHOLD_DESC = {
        1: 'RSI < 20 (超卖)',
        2: '20 ≤ RSI < 40 (含边界20)',
        3: '40 ≤ RSI < 60 (含边界40)',
        4: '60 ≤ RSI < 80 (含边界60)',
        5: 'RSI ≥ 80 (含边界80)'
    }
    
    # 交易成本
    TRADE_COST_RATE = 0.003  # 单边千分之三
    
    # 最小股票数
    MIN_STOCKS_PER_LAYER = 10


def load_data_from_cache(
    cache_dir: Optional[str] = None
) -> tuple:
    """
    从缓存加载因子和收益数据
    
    参数:
        cache_dir: 缓存目录，默认 cache/factor_data/
    
    返回:
        (factor_df, return_df)
    
    规范:
        加载缓存全部日期数据，不截断
    """
    if cache_dir is None:
        cache_dir = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            'cache', 'factor_data'
        )
    
    # 加载因子数据
    factor_path = os.path.join(cache_dir, 'factor_data.json.gz')
    logger.info("加载因子数据: %s", factor_path)
    
    with gzip.open(factor_path, 'rt', encoding='utf-8') as f:
        factor_data = json.load(f)
    
    factor_df = pd.DataFrame(factor_data['data'])
    logger.info("因子数据: %d 条记录", len(factor_df))
    logger.debug("因子列: %s", list(factor_df.columns))
    
    # 加载收益数据
    return_path = os.path.join(cache_dir, 'return_data.json.gz')
    logger.info("加载收益数据: %s", return_path)
    
    with gzip.open(return_path, 'rt', encoding='utf-8') as f:
        return_data = json.load(f)
    
    return_df = pd.DataFrame(return_data['data'])
    logger.info("收益数据: %d 条记录", len(return_df))
    logger.debug("收益列: %s", list(return_df.columns))
    
    # 使用缓存全部日期（不截断）
    
    return factor_df, return_df


def run_rsi_layered_backtest(
    output_dir: str = None,
    verbose: bool = True
) -> Dict:
    """
    RSI分层回测入口函数
    
    参数:
        output_dir: 输出目录，默认 cache/backtest/
        verbose: 是否打印详细日志
    
    返回:
        回测结果字典
    
    规范:
        使用缓存全部日期数据，不截断
    """
    logger.info("=" * 40)
    logger.info("RSI 分层回测")
    logger.info("=" * 40)
    
    # 配置
    config = RSILayerConfig()
    
    if verbose:
        logger.info("配置信息:")
        logger.info("  分层阈值: %s", config.LAYER_THRESHOLDS)
        logger.info("  因子方向: %s", config.FACTOR_DIRECTION)
        logger.info("  多头组合: Layer %s", config.LONG_LAYERS)
        logger.info("  空头组合: Layer %s", config.SHORT_LAYERS)
        logger.info("  最小股票数: %d", config.MIN_STOCKS_PER_LAYER)
        logger.info("  交易成本率: %.2f%%", config.TRADE_COST_RATE * 100)
    
    # 加载数据
    factor_df, return_df = load_data_from_cache()
    
    # 检查数据
    if 'rsi_6' not in factor_df.columns:
        raise ValueError("因子数据中缺少 rsi_6 列")
    
    if 'forward_return_1d' not in return_df.columns:
        raise ValueError("收益数据中缺少 forward_return_1d 列")
    
    # 打印数据统计
    if verbose:
        logger.info("数据统计:")
        logger.info("  日期范围: %s ~ %s", factor_df['date'].min(), factor_df['date'].max())
        logger.info("  股票数量: %d", factor_df['asset'].nunique())
        logger.info("  RSI 范围: %.2f ~ %.2f", factor_df['rsi_6'].min(), factor_df['rsi_6'].max())
        logger.info("  RSI 均值: %.2f", factor_df['rsi_6'].mean())
        logger.info("  收益范围: %.4f ~ %.4f", return_df['forward_return_1d'].min(), return_df['forward_return_1d'].max())
    
    # 创建回测引擎
    logger.info("创建回测引擎...")
    engine = LayeredBacktestEngine(
        factor_df=factor_df,
        return_df=return_df,
        factor_col='rsi_6',
        return_col='forward_return_1d',
        date_col='date',
        asset_col='asset'
    )
    
    # 执行回测
    logger.info("执行分层回测...")
    
    result = engine.run(
        layer_method='fixed_threshold',
        thresholds=config.LAYER_THRESHOLDS,
        factor_direction=config.FACTOR_DIRECTION,
        long_layers=config.LONG_LAYERS,
        short_layers=config.SHORT_LAYERS,
        min_stocks_per_layer=config.MIN_STOCKS_PER_LAYER,
        trade_cost_rate=config.TRADE_COST_RATE
    )
    
    # 添加RSI特定信息
    result['meta']['factor_name'] = 'rsi_6'
    result['meta']['layer_names'] = config.LAYER_NAMES
    result['meta']['layer_thresholds_desc'] = config.LAYER_THRESHOLD_DESC
    
    # 生成报告
    report = engine.generate_report(result)
    logger.info(report)
    
    # 输出RSI特有信息
    logger.info("=" * 40)
    logger.info("RSI 分层说明")
    logger.info("=" * 40)
    for layer_id, desc in config.LAYER_THRESHOLD_DESC.items():
        name = config.LAYER_NAMES.get(layer_id, f'Layer{layer_id}')
        logger.info("  Layer%d (%s): %s", layer_id, name, desc)
    
    # 保存结果
    if output_dir is None:
        output_dir = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            'cache', 'backtest'
        )
    
    os.makedirs(output_dir, exist_ok=True)
    
    # 保存完整结果
    output_file = os.path.join(output_dir, 'rsi_layered_backtest.json')
    
    # 准备输出数据（不包含daily_records以减少文件大小）
    output_data = {
        'meta': result['meta'],
        'layer_stats': result['layer_stats'],
        'long_short': result['long_short'],
        'monotonicity': result['monotonicity'],
        'trading_cost_analysis': result['trading_cost_analysis'],
        'config': {
            'layer_thresholds': config.LAYER_THRESHOLDS,
            'layer_names': config.LAYER_NAMES,
            'factor_direction': config.FACTOR_DIRECTION,
            'long_layers': config.LONG_LAYERS,
            'short_layers': config.SHORT_LAYERS,
            'trade_cost_rate': config.TRADE_COST_RATE,
            'min_stocks_per_layer': config.MIN_STOCKS_PER_LAYER
        },
        'created_at': datetime.now().isoformat()
    }
    
    # 使用公共模块转换 numpy/pandas 类型（遵循 PROJECT.md 强制复用规范）
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(convert_to_native_types(output_data), f, indent=2, ensure_ascii=False)
    
    logger.info("结果已保存: %s", output_file)
    
    # 保存每日明细（压缩）
    daily_file = os.path.join(output_dir, 'rsi_layered_backtest_daily.json.gz')
    daily_data = {
        'meta': {
            'n_days': len(set(r['date'] for r in result['daily_records'])),
            'columns': ['date', 'layer', 'n_stocks', 'return', 'turnover']
        },
        'data': result['daily_records']
    }
    
    with gzip.open(daily_file, 'wt', encoding='utf-8') as f:
        json.dump(convert_to_native_types(daily_data), f, indent=2, ensure_ascii=False)
    
    logger.info("每日明细已保存: %s", daily_file)
    
    return result


def main():
    """命令行入口"""
    import argparse
    
    parser = argparse.ArgumentParser(description='RSI分层回测')
    parser.add_argument('--output_dir', type=str, default=None, help='输出目录')
    parser.add_argument('--quiet', action='store_true', help='安静模式')
    
    args = parser.parse_args()
    
    result = run_rsi_layered_backtest(
        output_dir=args.output_dir,
        verbose=not args.quiet
    )
    
    return result


if __name__ == '__main__':
    main()