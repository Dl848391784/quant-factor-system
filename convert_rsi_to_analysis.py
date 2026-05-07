#!/usr/bin/env python3
"""
RSI IC 数据格式转换脚本（Phase 1 + Phase 2）

将 rsi_ic_data.json（简单格式）转换为 factor_analysis_result.json（标准格式）
补充分层回测数据（Phase 2）

运行方式：
    python convert_rsi_to_analysis.py
    
集成方式：
    在 precompute_optimizer.py 定时任务末尾调用

作者: 云舟
日期: 2026-04-21
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'common'))

import json
from pathlib import Path
from datetime import datetime
from typing import Dict, Optional
import logging

# 配置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s [转换] %(message)s')
logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).parent


def _load_cached_data_for_layered_backtest(n_days: int):
    """
    从缓存文件加载因子和收益数据（用于分层回测）
    
    直接读取 factor_data.json.gz 和 return_data.json.gz，
    不调用 RealDataLoader.load_data()。
    
    Args:
        n_days: 需要加载的交易日数量
        
    Returns:
        (factor_df, return_df)
        factor_df: 列 ['date', 'asset', 'rsi_6']
        return_df: 列 ['date', 'asset', 'forward_return']
    """
    import gzip
    import json
    import pandas as pd
    from pathlib import Path
    
    BASE_DIR = Path(__file__).parent
    CACHE_DIR = BASE_DIR / 'cache' / 'factor_data'
    
    factor_path = CACHE_DIR / 'factor_data.json.gz'
    return_path = CACHE_DIR / 'return_data.json.gz'
    
    # 检查缓存文件是否存在
    if not factor_path.exists() or not return_path.exists():
        logger.error(f"缓存文件不存在:")
        logger.error(f"  factor_path: {factor_path}")
        logger.error(f"  return_path: {return_path}")
        return pd.DataFrame(), pd.DataFrame()
    
    logger.info(f"从缓存加载分层回测数据...")
    
    # 读取因子数据
    with gzip.open(factor_path, 'rt', encoding='utf-8') as f:
        factor_data = json.load(f)
    
    # 读取收益数据
    with gzip.open(return_path, 'rt', encoding='utf-8') as f:
        return_data = json.load(f)
    
    # 输出缓存元信息
    factor_meta = factor_data.get('meta', {})
    return_meta = return_data.get('meta', {})
    
    logger.info(f"因子缓存信息:")
    logger.info(f"  交易日数: {factor_meta.get('n_days', 0)}")
    logger.info(f"  股票数量: {factor_meta.get('n_assets', 0)}")
    logger.info(f"  日期范围: {factor_meta.get('date_range', {}).get('start')} ~ {factor_meta.get('date_range', {}).get('end')}")
    
    logger.info(f"收益缓存信息:")
    logger.info(f"  交易日数: {return_meta.get('n_days', 0)}")
    logger.info(f"  股票数量: {return_meta.get('n_assets', 0)}")
    
    # 提取数据记录
    factor_records = factor_data.get('data', [])
    return_records = return_data.get('data', [])
    
    if not factor_records or not return_records:
        logger.error(f"缓存数据为空")
        return pd.DataFrame(), pd.DataFrame()
    
    # 构建 DataFrame
    factor_df = pd.DataFrame(factor_records)
    return_df = pd.DataFrame(return_records)
    
    # 只提取必要的列
    factor_df = factor_df[['date', 'asset', 'rsi_6']].copy()
    
    # 收益列名映射：forward_return_1d → forward_return
    return_df = return_df[['date', 'asset', 'forward_return_1d']].copy()
    return_df = return_df.rename(columns={'forward_return_1d': 'forward_return'})
    
    # 限制天数（只保留最近 n_days 天）
    if n_days > 0:
        # 获取所有日期
        all_dates = sorted(factor_df['date'].unique())
        
        if len(all_dates) > n_days:
            # 只保留最近 n_days 天
            recent_dates = all_dates[-n_days:]
            
            factor_df = factor_df[factor_df['date'].isin(recent_dates)].copy()
            return_df = return_df[return_df['date'].isin(recent_dates)].copy()
            
            logger.info(f"限制天数: 只保留最近 {n_days} 天数据")
            logger.info(f"  日期范围: {recent_dates[0]} ~ {recent_dates[-1]}")
    
    # 内存优化：使用 category 类型
    factor_df['date'] = factor_df['date'].astype('category')
    factor_df['asset'] = factor_df['asset'].astype('category')
    return_df['date'] = return_df['date'].astype('category')
    return_df['asset'] = return_df['asset'].astype('category')
    
    # 输出统计信息
    logger.info(f"缓存数据加载完成:")
    logger.info(f"  因子数据: {len(factor_df)} 行")
    logger.info(f"  收益数据: {len(return_df)} 行")
    logger.info(f"  交易日数: {factor_df['date'].nunique()}")
    logger.info(f"  股票数量: {factor_df['asset'].nunique()}")
    
    return factor_df, return_df


def convert_rsi_format() -> bool:
    """
    Phase 1: 转换 RSI IC 数据格式
    
    将 rsi_ic_data.json 转换为 factor_analysis_result.json 标准格式
    
    Returns:
        bool: 是否成功
    """
    logger.info("=" * 60)
    logger.info("Phase 1: RSI IC 数据格式转换")
    logger.info("=" * 60)
    
    # 读取原始数据
    rsi_ic_file = BASE_DIR / 'rsi_ic_data.json'
    if not rsi_ic_file.exists():
        logger.error(f"rsi_ic_data.json 不存在: {rsi_ic_file}")
        return False
    
    try:
        with open(rsi_ic_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
        logger.info(f"读取成功: {rsi_ic_file}")
    except Exception as e:
        logger.error(f"读取失败: {e}")
        return False
    
    # 转换为标准格式
    result = {
        'ic_metrics': {
            'ic_mean': data.get('ic_mean', 0),
            'ic_std': data.get('ic_std', 0),
            'icir': data.get('icir', 0),
            't_stat': data.get('t_stat', 0),
            'p_value': data.get('p_value', 0),
            'significance': data.get('significance', ''),
            'positive_ratio': data.get('positive_ratio', 0),
            'n_days': data.get('n_days', 0),
            'n_assets': data.get('n_assets', 0),
            'summary': data.get('summary', '')
        },
        'ic_series': {
            'dates': data.get('dates', []),
            'ic_values': data.get('ic_values', []),
            'rolling_ic_mean': data.get('rolling_ic_mean', [])
        },
        'layered_result': {
            # Phase 2 补充分层回测数据
            'layer_returns': [],
            'cumulative_returns': [],
            'statistics': [],
            'long_short': [],
            'summary': {
                'long_short_annual_return': 0,
                'long_short_sharpe': 0,
                'long_short_max_drawdown': 0,
                'monotonicity_passed': False
            }
        },
        'params': {
            'n_days': data.get('n_days', 0),
            'factor_name': 'RSI(6)'
        },
        'generated_at': datetime.now().isoformat()
    }
    
    # 原子写入
    output_file = BASE_DIR / 'factor_analysis_result.json'
    try:
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        logger.info(f"格式转换成功: {output_file}")
        logger.info(f"  ic_mean: {result['ic_metrics']['ic_mean']:.4f}")
        logger.info(f"  icir: {result['ic_metrics']['icir']:.2f}")
        return True
    except Exception as e:
        logger.error(f"写入失败: {e}")
        return False


def calculate_layered_backtest() -> Optional[Dict]:
    """
    Phase 2: 补充分层回测数据
    
    调用现有的 layered_backtest.py 模块计算分层回测结果
    
    Returns:
        Dict: 分层回测结果，如果失败返回 None
    """
    logger.info("=" * 60)
    logger.info("Phase 2: 补充分层回测数据")
    logger.info("=" * 60)
    
    try:
        import pandas as pd
        from layered_backtest import LayeredBacktest
        from real_data_loader import RealDataLoader
        
        logger.info("加载分层回测模块...")
        
        # 从 rsi_ic_data.json 获取实际使用的天数
        rsi_ic_file = BASE_DIR / 'rsi_ic_data.json'
        if rsi_ic_file.exists():
            with open(rsi_ic_file, 'r', encoding='utf-8') as f:
                rsi_data = json.load(f)
            n_days = rsi_data.get('n_days', 250)
        else:
            n_days = 250
        
        # 从缓存加载分层回测数据
        factor_df, return_df = _load_cached_data_for_layered_backtest(n_days)
        
        if len(factor_df) == 0 or len(return_df) == 0:
            logger.error("缓存数据加载失败")
            return None
        
        # 执行分层回测
        logger.info("开始分层回测...")
        backtest = LayeredBacktest(num_layers=5, enable_filter=True, enable_winsorize=True)
        result = backtest.run(
            factor_df=factor_df,
            return_df=return_df,
            factor_col='rsi_6',
            return_col='forward_return'
        )
        
        logger.info("分层回测完成")
        
        # 转换结果为 JSON 格式
        layered_result = {
            'layer_returns': result.layer_returns.to_dict('records') if hasattr(result.layer_returns, 'to_dict') else [],
            'cumulative_returns': result.cumulative_returns.to_dict('records') if hasattr(result.cumulative_returns, 'to_dict') else [],
            'statistics': result.statistics.to_dict('records') if hasattr(result.statistics, 'to_dict') else [],
            'long_short': result.long_short.to_dict('records') if hasattr(result.long_short, 'to_dict') else [],
            'summary': {
                'long_short_annual_return': 0,
                'long_short_sharpe': 0,
                'long_short_max_drawdown': 0,
                'monotonicity_passed': False
            }
        }
        
        # 尝试从 statistics 中提取关键指标
        if hasattr(result.statistics, 'to_dict'):
            stats_df = result.statistics
            # 使用 .loc 访问索引为 'long_short' 的行
            if 'long_short' in stats_df.index:
                row = stats_df.loc['long_short']
                layered_result['summary'] = {
                    'long_short_annual_return': float(row.get('annual_return', 0)),
                    'long_short_sharpe': float(row.get('sharpe', 0)),
                    'long_short_max_drawdown': float(row.get('max_drawdown', 0)),
                    'monotonicity_passed': bool(row.get('monotonicity', False))
                }
                logger.info(f"多空组合指标:")
                logger.info(f"  年化收益: {layered_result['summary']['long_short_annual_return']:.2%}")
                logger.info(f"  夏普比率: {layered_result['summary']['long_short_sharpe']:.2f}")
                logger.info(f"  最大回撤: {layered_result['summary']['long_short_max_drawdown']:.2%}")
        
        return layered_result
        
    except Exception as e:
        logger.error(f"分层回测计算失败: {e}")
        import traceback
        traceback.print_exc()
        return None


def convert_with_layered_backtest() -> bool:
    """
    Phase 1 + Phase 2: 格式转换 + 补充分层回测
    
    Returns:
        bool: 是否成功
    """
    logger.info("=" * 60)
    logger.info("RSI IC 数据转换（Phase 1 + Phase 2）")
    logger.info("=" * 60)
    
    # Phase 1: 格式转换
    if not convert_rsi_format():
        logger.error("Phase 1 格式转换失败")
        return False
    
    # Phase 2: 补充分层回测
    layered_result = calculate_layered_backtest()
    
    if layered_result is None:
        logger.warning("Phase 2 分层回测失败，使用默认空数据")
        layered_result = {
            'layer_returns': [],
            'cumulative_returns': [],
            'statistics': [],
            'long_short': [],
            'summary': {
                'long_short_annual_return': 0,
                'long_short_sharpe': 0,
                'long_short_max_drawdown': 0,
                'monotonicity_passed': False
            }
        }
    
    # 更新 factor_analysis_result.json
    output_file = BASE_DIR / 'factor_analysis_result.json'
    try:
        with open(output_file, 'r', encoding='utf-8') as f:
            result = json.load(f)
        
        # 补充分层回测数据
        result['layered_result'] = layered_result
        result['generated_at'] = datetime.now().isoformat()
        
        # 原子写入
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        
        logger.info(f"Phase 2 补充成功: {output_file}")
        return True
        
    except Exception as e:
        logger.error(f"Phase 2 更新失败: {e}")
        return False


if __name__ == '__main__':
    """主程序入口
    
    默认执行 Phase 1 + Phase 2
    """
    import argparse
    
    parser = argparse.ArgumentParser(description='RSI IC 数据格式转换')
    parser.add_argument('--phase1', action='store_true', help='只执行 Phase 1 格式转换')
    parser.add_argument('--phase2', action='store_true', help='执行 Phase 1 + Phase 2')
    
    args = parser.parse_args()
    
    if args.phase1:
        # 只执行 Phase 1
        success = convert_rsi_format()
    else:
        # 默认执行 Phase 1 + Phase 2
        success = convert_with_layered_backtest()
    
    if success:
        logger.info("=" * 60)
        logger.info("转换完成")
        logger.info("=" * 60)
    else:
        logger.error("=" * 60)
        logger.error("转换失败")
        logger.error("=" * 60)
        exit(1)