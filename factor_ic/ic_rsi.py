#!/usr/bin/env python3
"""
RSI(6) 真实数据 IC 计算器

获取主板股票真实行情数据，计算 RSI(6) 因子的反向排名 Rank IC。

依赖: pip install akshare

作者: 云舟
日期: 2026-04-01
"""

import sys
from pathlib import Path

# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent.parent))

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from typing import Tuple, Optional, List
import json
import importlib.util

# 动态加载 reverse_rank_ic 模块
module_path = Path(__file__).resolve().parent.parent / 'reverse_rank_ic.py'
spec = importlib.util.spec_from_file_location("reverse_rank_ic", str(module_path))
reverse_rank_ic_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(reverse_rank_ic_module)
reverse_rank_ic = reverse_rank_ic_module.reverse_rank_ic

# 导入真实数据加载器
from common.real_data_loader import RealDataLoader

# 导入数据完整性检查模块
from common.data_completeness import check_data_completeness, get_ic_output_path


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
        'factor_name': 'rsi',
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
    output_file: str = None,
    force_full: bool = False
) -> dict:
    """
    获取真实数据并计算 RSI IC
    
    参数:
        n_days: 交易日数量（默认约一年250个交易日）
        max_stocks: 最大股票数量
        output_file: 输出文件路径
        force_full: 强制全量计算（跳过增量判断）
    
    返回:
        IC 数据字典
        
    异常:
        如果数据获取失败，抛出 RuntimeError
    """
    if output_file is None:
        output_file = get_ic_output_path('rsi')
    
    # 增量判断（除非强制全量）
    if not force_full:
        mode, missing_dates, info = check_data_completeness('rsi')
        
        if mode == 'skip':
            print("\n数据完备，无需更新")
            # 读取现有缓存返回
            try:
                with open(output_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception as e:
                print(f"读取缓存失败: {e}，将执行全量计算")
                mode = 'full'
        
        if mode == 'incremental':
            return _generate_rsi_ic_incremental(
                missing_dates=missing_dates,
                output_file=output_file,
                info=info
            )
    
    # 全量计算逻辑
    print("="*60)
    print("RSI(6) 真实数据 IC 计算器（akshare）- 全量计算")
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
    output_file.parent.mkdir(parents=True, exist_ok=True)
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(ic_data, f, ensure_ascii=False, indent=2)
    
    print("\n" + "="*60)
    print("完成！")
    print("="*60)
    
    return ic_data


def _generate_rsi_ic_incremental(
    missing_dates: list,
    output_file: Path,
    info: dict
) -> dict:
    """
    增量计算 RSI IC
    
    只加载缺失日期的数据，计算 IC，合并到现有缓存
    
    参数:
        missing_dates: 需要计算的日期列表
        output_file: 输出文件路径
        info: 增量判断返回的信息
    
    返回:
        合并后的 IC 数据字典
    """
    print("="*60)
    print("RSI(6) 真实数据 IC 计算器 - 增量计算")
    print("="*60)
    print(f"缺失日期数: {len(missing_dates)}")
    print(f"日期范围: {missing_dates[0]} ~ {missing_dates[-1]}")
    
    # 加载现有 IC 缓存
    existing_ic_data = None
    if output_file.exists():
        try:
            with open(output_file, 'r', encoding='utf-8') as f:
                existing_ic_data = json.load(f)
            print(f"已加载现有 IC 缓存: {len(existing_ic_data.get('dates', []))} 天")
        except Exception as e:
            print(f"读取现有缓存失败: {e}")
            existing_ic_data = None
    
    # 从缓存加载缺失日期的数据
    print("\n[1/3] 从缓存加载缺失日期数据...")
    loader = RealDataLoader(enable_cache=True)
    
    try:
        # 加载全量数据，然后筛选缺失日期
        factor_df, return_df = loader.load_data_from_cache()
        
        if factor_df is None or return_df is None:
            print("缓存数据加载失败，将执行全量计算")
            return generate_rsi_ic_data(force_full=True)
        
        # 筛选缺失日期的数据
        missing_dates_set = set(missing_dates)
        factor_df = factor_df[factor_df['date'].astype(str).isin(missing_dates_set)]
        return_df = return_df[return_df['date'].astype(str).isin(missing_dates_set)]
        
        print(f"  - 筛选后因子数据: {len(factor_df)} 行")
        print(f"  - 筛选后收益数据: {len(return_df)} 行")
        print(f"  - 交易日数: {factor_df['date'].nunique()}")
        
        if factor_df['date'].nunique() == 0:
            print("无缺失日期数据，跳过计算")
            if existing_ic_data:
                return existing_ic_data
            return {}
            
    except Exception as e:
        print(f"增量数据加载失败: {e}，将执行全量计算")
        return generate_rsi_ic_data(force_full=True)
    
    # 计算 IC
    print("\n[2/3] 计算缺失日期的 IC...")
    new_ic_data = calculate_daily_ic_series(factor_df, return_df)
    print(f"  - 新增 IC 天数: {len(new_ic_data['dates'])}")
    print(f"  - IC 均值: {new_ic_data['ic_mean']:.4f}")
    
    # 合并 IC 数据
    print("\n[3/3] 合并 IC 数据...")
    if existing_ic_data:
        merged_data = _merge_ic_data(existing_ic_data, new_ic_data)
    else:
        merged_data = new_ic_data
    
    # 保存合并后的数据
    print(f"\n保存数据到: {output_file}")
    output_file.parent.mkdir(parents=True, exist_ok=True)
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(merged_data, f, ensure_ascii=False, indent=2)
    
    print(f"合并后总天数: {len(merged_data['dates'])}")
    print("="*60)
    print("增量计算完成！")
    print("="*60)
    
    return merged_data


def _merge_ic_data(existing: dict, new: dict) -> dict:
    """
    合并 IC 数据
    
    将新的 IC 数据合并到现有数据中，保持日期顺序
    
    参数:
        existing: 现有 IC 数据
        new: 新计算的 IC 数据
        
    返回:
        合并后的 IC 数据
    """
    import pandas as pd
    
    # 构建现有数据的 DataFrame
    existing_df = pd.DataFrame({
        'date': existing['dates'],
        'ic': existing['ic_values'],
        'rolling_mean': existing['rolling_ic_mean']
    })
    
    # 构建新数据的 DataFrame
    new_df = pd.DataFrame({
        'date': new['dates'],
        'ic': new['ic_values'],
        'rolling_mean': new['rolling_ic_mean']
    })
    
    # 合并并按日期排序
    merged_df = pd.concat([existing_df, new_df], ignore_index=True)
    merged_df['date'] = pd.to_datetime(merged_df['date'])
    merged_df = merged_df.sort_values('date').reset_index(drop=True)
    
    # 重新计算滚动均值（20日）
    merged_df['rolling_mean'] = merged_df['ic'].rolling(window=20, min_periods=1).mean()
    
    # 重新计算统计指标
    ic_series = merged_df['ic']
    ic_mean = ic_series.mean()
    ic_std = ic_series.std()
    icir = ic_mean / ic_std if ic_std != 0 else 0
    positive_ratio = (ic_series > 0).mean()
    
    # t 统计量
    n_days = len(ic_series)
    t_stat = ic_mean / ic_std * np.sqrt(n_days) if ic_std != 0 else 0
    
    # 显著性判断
    if abs(t_stat) > 2.576:
        significance = "***"
    elif abs(t_stat) > 1.96:
        significance = "**"
    elif abs(t_stat) > 1.645:
        significance = "*"
    else:
        significance = ""
    
    # 构建合并后的数据
    merged_data = {
        'factor_name': 'rsi',
        'dates': [str(d.date()) for d in merged_df['date']],
        'ic_values': [round(v, 6) for v in merged_df['ic']],
        'rolling_ic_mean': [round(v, 6) for v in merged_df['rolling_mean']],
        'ic_mean': round(ic_mean, 6),
        'ic_std': round(ic_std, 6),
        'icir': round(icir, 4),
        'positive_ratio': round(positive_ratio, 4),
        't_stat': round(t_stat, 4),
        'significance': significance,
        'n_days': n_days,
        'n_assets': existing.get('n_assets', new.get('n_assets', 0)),
        'summary': f"IC均值={ic_mean:.4f}, ICIR={icir:.2f}, 正比例={positive_ratio:.1%}"
    }
    
    return merged_data


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
        output_file = Path(__file__).parent.parent / 'cache' / 'factor_ic' / 'rsi_ic.json'
    
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