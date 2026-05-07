#!/usr/bin/env python3
"""
RSI(6) 真实数据 IC 计算器

获取主板股票真实行情数据，计算 RSI(6) 因子的反向排名 Rank IC。

依赖: pip install akshare

作者: 云舟
日期: 2026-04-01
"""

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from typing import Tuple, Optional, List
import json
from pathlib import Path

# 导入模块
import sys
import importlib.util

# 动态加载 reverse_rank_ic 模块
module_path = Path(__file__).resolve().parent.parent / 'reverse_rank_ic.py'
spec = importlib.util.spec_from_file_location("reverse_rank_ic", str(module_path))
reverse_rank_ic_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(reverse_rank_ic_module)
reverse_rank_ic = reverse_rank_ic_module.reverse_rank_ic

# 导入真实数据加载器
from real_data_loader import RealDataLoader


def calculate_daily_ic_series(
    factor_df: pd.DataFrame,
    return_df: pd.DataFrame
) -> dict:
    """
    计算每日的 IC 时间序列
    
    参数:
        factor_df: 因子数据
        return_df: 收益数据
    
    返回:
        dict: {
            'dates': [...],
            'ic_values': [...],
            'ic_mean': float,
            'ic_std': float,
            'icir': float,
            'positive_ratio': float,
            'rolling_ic_mean': [...],  # 滚动均值
        }
    """
    # 使用反向排名 IC 计算
    result = reverse_rank_ic(
        factor_df=factor_df,
        return_df=return_df,
        factor_col='rsi_6',
        return_col='forward_return',
        date_col='date',
        asset_col='asset',
        min_stocks=10
    )
    
    ic_series = result['ic_series']
    
    # 转换为 JSON 友好格式
    dates = [str(d) for d in ic_series.index]
    ic_values = [round(v, 6) for v in ic_series.values]
    
    # 计算 20 日滚动均值
    rolling_mean = ic_series.rolling(window=20, min_periods=1).mean()
    rolling_ic_mean = [round(v, 6) for v in rolling_mean.values]
    
    return {
        'dates': dates,
        'ic_values': ic_values,
        'rolling_ic_mean': rolling_ic_mean,
        'ic_mean': round(result['ic_mean'], 6),
        'ic_std': round(result['ic_std'], 6),
        'icir': round(result['icir'], 4),
        'positive_ratio': round(result['positive_ratio'], 4),
        't_stat': result['t_stat'],
        'significance': result['significance'],
        'n_days': len(dates),
        'n_assets': factor_df['asset'].nunique(),
        'summary': result['summary']
    }


def generate_rsi_ic_data(
    n_days: int = 250,
    max_stocks: int = 500,
    output_file: str = None
) -> dict:
    """
    获取真实数据并计算 RSI IC
    
    参数:
        n_days: 交易日数量（默认约一年250个交易日）
        max_stocks: 最大股票数量
        output_file: 输出文件路径
    
    返回:
        IC 数据字典
        
    异常:
        如果数据获取失败，抛出 RuntimeError
    """
    if output_file is None:
        output_file = Path(__file__).parent / 'rsi_ic_data.json'
    
    print("="*60)
    print("RSI(6) 真实数据 IC 计算器（akshare）")
    print("="*60)
    
    # 加载真实数据
    print("\n[1/3] 加载真实 A股数据...")
    loader = RealDataLoader()
    
    try:
        factor_df, return_df = loader.load_data(
            n_days=n_days,
            max_stocks=max_stocks
        )
        
        # 检查数据量是否足够计算 IC
        if factor_df['asset'].nunique() < 10:
            raise ValueError(
                f"\n"
                "="*60 + "\n"
                f"股票数量不足以计算有效的 IC\n"
                f"当前: {factor_df['asset'].nunique()} < 10\n"
                "="*60 + "\n"
                "请尝试:\n"
                "  1. 增加 max_stocks 参数\n"
                "  2. 检查网络连接\n"
                "="*60
            )
            
    except Exception as e:
        # 直接抛出异常，不使用 mock 数据
        raise RuntimeError(
            f"\n"
            "="*60 + "\n"
            f"数据加载失败: {e}\n"
            "="*60 + "\n"
            "请检查:\n"
            "  1. akshare 是否安装: pip install akshare\n"
            "  2. 网络连接是否正常\n"
            "  3. akshare 版本是否最新: pip install --upgrade akshare\n"
            "\n"
            "如果安装缓慢，可使用国内镜像:\n"
            "  pip install akshare -i https://pypi.tuna.tsinghua.edu.cn/simple\n"
            "="*60
        )
    
    print(f"  - 因子数据: {len(factor_df)} 行")
    print(f"  - 收益数据: {len(return_df)} 行")
    print(f"  - 交易日数: {factor_df['date'].nunique()}")
    print(f"  - 股票数量: {factor_df['asset'].nunique()}")
    
    # 计算 IC
    print("\n[2/3] 计算每日 IC...")
    ic_data = calculate_daily_ic_series(factor_df, return_df)
    print(f"  - IC 均值: {ic_data['ic_mean']:.4f}")
    print(f"  - ICIR: {ic_data['icir']:.2f}")
    print(f"  - 正比例: {ic_data['positive_ratio']:.1%}")
    
    # 保存数据
    print(f"\n[3/3] 保存数据到: {output_file}")
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(ic_data, f, ensure_ascii=False, indent=2)
    
    print("\n" + "="*60)
    print("完成！")
    print("="*60)
    
    return ic_data


def generate_rsi_ic_data_with_progress(
    n_days: int = 250,
    max_stocks: int = 500,
    output_file: str = None,
    progress_callback=None
) -> dict:
    """
    获取真实数据并计算 RSI IC（带进度回调）
    
    参数:
        n_days: 交易日数量
        max_stocks: 最大股票数量
        output_file: 输出文件路径
        progress_callback: 进度回调函数(current_batch, total_batches, stocks_fetched, success_count, fail_count, message)
    
    返回:
        IC 数据字典
    """
    if output_file is None:
        output_file = Path(__file__).parent / 'rsi_ic_data.json'
    
    loader = RealDataLoader()
    
    try:
        # 使用带进度的加载方法（批次信息由 load_data_with_progress 内部管理）
        factor_df, return_df, stats = loader.load_data_with_progress(
            n_days=n_days,
            max_stocks=max_stocks,
            progress_callback=progress_callback
        )
        
        # 检查数据量
        if factor_df['asset'].nunique() < 10:
            raise ValueError(f"股票数量不足: {factor_df['asset'].nunique()} < 10")
            
    except Exception as e:
        if progress_callback:
            progress_callback(0, 0, 0, 0, 0, f'错误: {str(e)}')
        raise
    
    # 计算 IC（使用实际统计数据）
    success_count = stats.get('success', 0)
    fail_count = stats.get('fail', 0)
    total_stocks = stats.get('total', 0)
    
    if progress_callback:
        progress_callback(
            1, 1, total_stocks, success_count, fail_count, '计算 IC...'
        )
    
    ic_data = calculate_daily_ic_series(factor_df, return_df)
    
    # 保存
    if progress_callback:
        progress_callback(
            1, 1, total_stocks, success_count, fail_count, '保存数据...'
        )
    
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(ic_data, f, ensure_ascii=False, indent=2)
    
    return ic_data


if __name__ == '__main__':
    # 默认计算近一年数据（约250个交易日）
    generate_rsi_ic_data(n_days=250, max_stocks=100)