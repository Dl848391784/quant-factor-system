#!/usr/bin/env python3
"""
换手率突增因子计算模块（内存优化版）

因子定义：
- 换手率突增 = 当日换手率 / 过去5日换手率均值
- 使用真实换手率数据（turnover_rate），来自 baostock

筛选条件（重要）：
- 只对"换手率突增且上涨"的股票计算因子值
- 换手率突增：turnover_surge > 1（当日换手率高于近期均值）
- 上涨：当日涨跌幅 > 0
- 不满足条件的股票因子值设为 None

内存优化策略：
1. 使用轻量级数据加载（load_cached_data_light）
2. 使用 category 类型优化内存
3. 分批处理大数据
4. 及时释放中间变量（gc.collect）
5. 参考分层回测的内存优化实现

作者: 云舟
日期: 2026-04-08
"""

import pandas as pd
import numpy as np
from pathlib import Path
import gzip
import json
import gc
import time
from typing import Tuple, Optional, Dict
import warnings
warnings.filterwarnings('ignore')


# 内存优化配置
MEMORY_THRESHOLD_MB = 900  # 内存阈值（MB）- 缓存数据约700MB，留200MB缓冲
MEMORY_PAUSE_SECONDS = 15  # 内存超阈值时暂停时间
STREAM_LOAD_BATCH_SIZE = 50000  # 流式加载批次大小


def get_memory_usage_mb() -> float:
    """获取当前进程真实RSS内存（MB）"""
    try:
        with open('/proc/self/status', 'r') as f:
            for line in f:
                if line.startswith('VmRSS:'):
                    return int(line.split()[1]) / 1024  # kB -> MB
    except Exception:
        pass
    return 0.0


def get_memory_info_str() -> str:
    """获取内存信息字符串"""
    mem_mb = get_memory_usage_mb()
    return f"RSS={mem_mb:.1f}MB"


def check_memory_threshold():
    """检查内存阈值，超过时暂停并清理"""
    mem_mb = get_memory_usage_mb()
    if mem_mb > MEMORY_THRESHOLD_MB:
        print(f'  ⚠ 内存超阈值 ({mem_mb:.1f}MB > {MEMORY_THRESHOLD_MB}MB)，暂停 {MEMORY_PAUSE_SECONDS}s...')
        gc.collect()
        time.sleep(MEMORY_PAUSE_SECONDS)
        mem_mb = get_memory_usage_mb()
        print(f'  GC后内存: {mem_mb:.1f}MB')
    return mem_mb


def convert_to_native_types(obj):
    """
    递归转换 numpy 类型为 Python 原生类型
    解决 JSON 序列化问题：TypeError: Object of type 'int64' is not JSON serializable
    """
    if isinstance(obj, dict):
        return {k: convert_to_native_types(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [convert_to_native_types(v) for v in obj]
    elif isinstance(obj, (np.integer, np.int64, np.int32)):
        return int(obj)
    elif isinstance(obj, (np.floating, np.float64, np.float32)):
        return float(obj)
    elif isinstance(obj, np.ndarray):
        return obj.tolist()
    elif isinstance(obj, pd.Series):
        return obj.tolist()
    elif pd.isna(obj):
        return None
    else:
        return obj


# 缓存路径
CACHE_DIR = Path('/home/admin/.openclaw/workspace/yunzhou/factor_ic_analyzer/cache/factor_data')


def load_turnover_rate_data(
    max_days: int = 500,
    use_category: bool = True
) -> Optional[pd.DataFrame]:
    """
    加载换手率数据（内存优化版）
    
    从 turnover_rate_data.json.gz 加载真实换手率数据
    
    内存优化策略：
    1. 分批处理，避免一次性创建大列表
    2. 内存监控，超过阈值时暂停
    3. 及时释放中间变量
    
    Args:
        max_days: 最大加载天数（默认 500，设置为 0 或负数表示加载全部）
        use_category: 是否使用 category 类型（默认 True）
        
    Returns:
        DataFrame: date, asset, turnover_rate
    """
    turnover_path = CACHE_DIR / 'turnover_rate_data.json.gz'
    
    if not turnover_path.exists():
        print(f"  ✗ 换手率数据文件不存在: {turnover_path}")
        return None
    
    try:
        print(f"[加载换手率] 从 turnover_rate_data.json.gz 加载...")
        print(f"  当前内存: {get_memory_info_str()}")
        check_memory_threshold()
        
        with gzip.open(turnover_path, 'rt', encoding='utf-8') as f:
            turnover_data = json.load(f)
        
        # 提取所有日期
        all_dates = sorted(set(r.get('date') for r in turnover_data.get('data', [])))
        print(f"  换手率数据包含 {len(all_dates)} 天, {turnover_data.get('meta', {}).get('n_assets', 0)} 只股票")
        
        # 只保留最近 max_days 天（max_days <= 0 表示加载全部）
        if max_days > 0 and len(all_dates) > max_days:
            recent_dates = set(all_dates[-max_days:])
            print(f"  只加载最近 {max_days} 天")
            
            # 分批提取数据，避免一次性创建大列表
            turnover_records = []
            batch_count = 0
            for r in turnover_data.get('data', []):
                if r.get('date') in recent_dates:
                    turnover_records.append({
                        'date': r['date'],
                        'asset': r['asset'],
                        'turnover_rate': r.get('turnover_rate')
                    })
                    batch_count += 1
                    if batch_count % STREAM_LOAD_BATCH_SIZE == 0:
                        gc.collect()
                        check_memory_threshold()
        else:
            # 分批提取全部数据
            turnover_records = []
            batch_count = 0
            for r in turnover_data.get('data', []):
                turnover_records.append({
                    'date': r['date'],
                    'asset': r['asset'],
                    'turnover_rate': r.get('turnover_rate')
                })
                batch_count += 1
                if batch_count % STREAM_LOAD_BATCH_SIZE == 0:
                    gc.collect()
                    check_memory_threshold()
        
        del turnover_data, all_dates
        if 'recent_dates' in dir():
            del recent_dates
        gc.collect()
        check_memory_threshold()
        
        # 构建 DataFrame
        turnover_df = pd.DataFrame(turnover_records)
        del turnover_records
        gc.collect()
        
        if use_category:
            turnover_df['date'] = turnover_df['date'].astype('category')
            turnover_df['asset'] = turnover_df['asset'].astype('category')
        
        turnover_df['turnover_rate'] = pd.to_numeric(turnover_df['turnover_rate'], errors='coerce')
        
        # 过滤无效值
        turnover_df = turnover_df.dropna(subset=['turnover_rate'])
        
        turnover_mem = turnover_df.memory_usage(deep=True).sum() / 1024 / 1024
        print(f"  turnover_df: {len(turnover_df)} 行, {turnover_mem:.2f} MB")
        print(f"  当前内存: {get_memory_info_str()}")
        
        return turnover_df
        
    except Exception as e:
        print(f"  ✗ 加载换手率数据失败: {e}")
        import traceback
        traceback.print_exc()
        return None


def load_data_for_turnover_surge(
    max_days: int = 500,
    use_category: bool = True
) -> Tuple[Optional[pd.DataFrame], Optional[pd.DataFrame]]:
    """
    加载换手率突增因子所需数据（内存优化版 v2）
    
    需要的数据：
    - turnover_rate: 真实换手率（来自 baostock）
    - close: 收盘价（用于计算当日涨跌幅）
    - forward_return_1d: 未来收益（用于IC计算）
    
    内存优化策略：
    1. 分批处理，避免一次性创建大列表
    2. 内存监控，超过阈值时暂停
    3. 及时释放中间变量
    
    Args:
        max_days: 最大加载天数（默认 500）
        use_category: 是否使用 category 类型（默认 True）
        
    Returns:
        (factor_df, return_df) 或 (None, None)
    """
    print(f"\n{'='*60}")
    print("[换手率突增] 加载数据（内存优化模式 v2）")
    print(f"  内存阈值: {MEMORY_THRESHOLD_MB} MB")
    print(f"{'='*60}")
    print(f"  当前内存: {get_memory_info_str()}")
    
    factor_path = CACHE_DIR / 'factor_data.json.gz'
    return_path = CACHE_DIR / 'return_data.json.gz'
    turnover_path = CACHE_DIR / 'turnover_rate_data.json.gz'
    
    if not factor_path.exists() or not return_path.exists() or not turnover_path.exists():
        print("  ✗ 缓存文件不存在")
        return None, None
    
    try:
        # ========== Step 1: 加载换手率数据 ==========
        print(f"[Step 1] 加载换手率数据...")
        check_memory_threshold()
        
        turnover_df = load_turnover_rate_data(max_days=max_days, use_category=use_category)
        
        if turnover_df is None or turnover_df.empty:
            print("  ✗ 换手率数据加载失败")
            return None, None
        
        print(f"  当前内存: {get_memory_info_str()}")
        
        # 获取换手率数据的日期集合
        if use_category:
            turnover_dates = set(str(d) for d in turnover_df['date'].unique())
        else:
            turnover_dates = set(str(d) for d in turnover_df['date'].unique())
        
        # ========== Step 2: 加载收盘价数据 ==========
        print(f"[Step 2] 加载收盘价数据...")
        check_memory_threshold()
        
        with gzip.open(factor_path, 'rt', encoding='utf-8') as f:
            factor_data = json.load(f)
        
        # 提取所有日期
        all_dates = sorted(set(r.get('date') for r in factor_data.get('data', [])))
        print(f"  收盘价数据包含 {len(all_dates)} 天")
        
        # 只保留与换手率数据匹配的日期
        if len(all_dates) > max_days:
            recent_dates = set(all_dates[-max_days:]) & turnover_dates
            print(f"  只加载最近 {max_days} 天且与换手率数据匹配的日期")
        else:
            recent_dates = turnover_dates
        
        # 分批提取数据
        close_records = []
        batch_count = 0
        for r in factor_data.get('data', []):
            if r.get('date') in recent_dates:
                close_records.append({
                    'date': r['date'],
                    'asset': r['asset'],
                    'close': r.get('close')
                })
                batch_count += 1
                if batch_count % STREAM_LOAD_BATCH_SIZE == 0:
                    gc.collect()
                    check_memory_threshold()
        
        del factor_data, all_dates
        if 'recent_dates' in dir():
            del recent_dates
        gc.collect()
        check_memory_threshold()
        
        # 构建 DataFrame
        close_df = pd.DataFrame(close_records)
        del close_records
        gc.collect()
        
        if use_category:
            close_df['date'] = close_df['date'].astype('category')
            close_df['asset'] = close_df['asset'].astype('category')
        
        close_df['close'] = pd.to_numeric(close_df['close'], errors='coerce')
        
        close_mem = close_df.memory_usage(deep=True).sum() / 1024 / 1024
        print(f"  close_df: {len(close_df)} 行, {close_mem:.2f} MB")
        print(f"  当前内存: {get_memory_info_str()}")
        
        # ========== Step 3: 合并换手率和收盘价 ==========
        print(f"[Step 3] 合并换手率和收盘价数据...")
        check_memory_threshold()
        
        # 统一 date 类型进行合并
        if turnover_df['date'].dtype.name == 'category':
            turnover_df['date'] = turnover_df['date'].astype(str)
        if close_df['date'].dtype.name == 'category':
            close_df['date'] = close_df['date'].astype(str)
        if turnover_df['asset'].dtype.name == 'category':
            turnover_df['asset'] = turnover_df['asset'].astype(str)
        if close_df['asset'].dtype.name == 'category':
            close_df['asset'] = close_df['asset'].astype(str)
        
        factor_df = pd.merge(
            turnover_df,
            close_df,
            on=['date', 'asset'],
            how='inner'
        )
        
        del turnover_df, close_df
        gc.collect()
        
        if use_category:
            factor_df['date'] = factor_df['date'].astype('category')
            factor_df['asset'] = factor_df['asset'].astype('category')
        
        factor_mem = factor_df.memory_usage(deep=True).sum() / 1024 / 1024
        print(f"  factor_df (合并后): {len(factor_df)} 行, {factor_mem:.2f} MB")
        print(f"  当前内存: {get_memory_info_str()}")
        
        # ========== Step 4: 加载收益数据 ==========
        print(f"[Step 4] 加载收益数据...")
        check_memory_threshold()
        
        with gzip.open(return_path, 'rt', encoding='utf-8') as f:
            return_data = json.load(f)
        
        # 提取收益数据
        if len(factor_df) > 0:
            # 获取因子数据的日期集合
            if use_category:
                factor_dates = set(str(d) for d in factor_df['date'].unique())
            else:
                factor_dates = set(str(d) for d in factor_df['date'].unique())
            
            # 分批提取数据
            return_records = []
            batch_count = 0
            for r in return_data.get('data', []):
                if r.get('date') in factor_dates:
                    return_records.append({
                        'date': r['date'],
                        'asset': r['asset'],
                        'forward_return_1d': r.get('forward_return_1d', r.get('forward_return'))
                    })
                    batch_count += 1
                    if batch_count % STREAM_LOAD_BATCH_SIZE == 0:
                        gc.collect()
                        check_memory_threshold()
        else:
            return_records = []
        
        del return_data
        gc.collect()
        check_memory_threshold()
        
        return_df = pd.DataFrame(return_records)
        del return_records
        gc.collect()
        
        if use_category:
            return_df['date'] = return_df['date'].astype('category')
            return_df['asset'] = return_df['asset'].astype('category')
        
        return_df['forward_return_1d'] = pd.to_numeric(return_df['forward_return_1d'], errors='coerce')
        
        # 兼容性映射
        if 'forward_return_1d' in return_df.columns and 'forward_return' not in return_df.columns:
            return_df['forward_return'] = return_df['forward_return_1d']
        
        return_mem = return_df.memory_usage(deep=True).sum() / 1024 / 1024
        print(f"  return_df: {len(return_df)} 行, {return_mem:.2f} MB")
        print(f"  总内存占用: {factor_mem + return_mem:.2f} MB")
        print(f"  当前内存: {get_memory_info_str()}")
        
        return factor_df, return_df
        
    except Exception as e:
        print(f"  ✗ 加载失败: {e}")
        import traceback
        traceback.print_exc()
        return None, None


def calculate_turnover_surge_ratio(
    df: pd.DataFrame,
    window: int = 5
) -> pd.DataFrame:
    """
    计算换手率突增因子
    
    因子定义：
    turnover_surge = 当日换手率 / 过去N日换手率均值
    
    Args:
        df: 包含 date, asset, turnover_rate 的 DataFrame
        window: 移动平均窗口（默认 5 日）
        
    Returns:
        添加 turnover_ma 和 turnover_surge 列的 DataFrame
    """
    print(f"\n{'='*60}")
    print("[因子计算] 计算换手率突增因子")
    print(f"{'='*60}")
    print(f"  窗口: {window} 日")
    
    if df.empty:
        print("  ✗ 数据为空")
        df['turnover_ma'] = None
        df['turnover_surge'] = None
        return df
    
    # 确保 date 列为字符串类型（便于排序）
    if df['date'].dtype.name == 'category':
        df['date_str'] = df['date'].astype(str)
    else:
        df['date_str'] = df['date'].astype(str)
    
    # 按股票分组排序
    df = df.sort_values(['asset', 'date_str']).copy()
    
    # 计算过去 N 日换手率均值（滚动计算）
    print(f"[Step 1] 计算过去 {window} 日换手率均值...")
    df['turnover_ma'] = df.groupby('asset')['turnover_rate'].transform(
        lambda x: x.rolling(window=window, min_periods=window).mean()
    )
    
    # 计算换手率突增因子
    print(f"[Step 2] 计算换手率突增因子...")
    df['turnover_surge'] = df['turnover_rate'] / df['turnover_ma']
    
    # 释放临时列
    df = df.drop(columns=['date_str'])
    
    # 统计
    valid_count = df['turnover_surge'].notna().sum()
    print(f"  有效因子记录数: {valid_count:,}")
    
    if valid_count > 0:
        valid_values = df['turnover_surge'].dropna()
        print(f"  因子范围: [{valid_values.min():.2f}, {valid_values.max():.2f}]")
        print(f"  因子均值: {valid_values.mean():.2f}")
    
    return df


def calculate_turnover_surge_factor(
    factor_df: pd.DataFrame,
    filter_conditions: bool = True
) -> Tuple[pd.DataFrame, Dict]:
    """
    计算换手率突增因子（带筛选条件）
    
    因子定义：
    - 换手率突增 = 当日换手率 / 过去5日换手率均值
    
    筛选条件（如果 filter_conditions=True）：
    - 换手率突增：turnover_surge > 1（当日换手率高于近期均值）
    - 上涨：当日涨跌幅 > 0
    - 不满足条件的股票因子值设为 None
    
    Args:
        factor_df: 包含 date, asset, close, turnover_rate 的 DataFrame
        filter_conditions: 是否应用筛选条件（默认 True）
        
    Returns:
        (处理后的 factor_df, 筛选统计)
    """
    print(f"\n{'='*60}")
    print("[因子计算] 计算换手率突增因子（真实换手率版）")
    print(f"{'='*60}")
    print(f"  筛选条件: {'启用' if filter_conditions else '禁用'}")
    
    filter_stats = {
        'total_records': len(factor_df),
        'turnover_surge_count': 0,
        'price_up_count': 0,
        'both_conditions_count': 0,
        'filtered_count': 0,
        'filter_ratio': 0.0
    }
    
    if factor_df.empty:
        print("  ✗ 数据为空")
        return factor_df, filter_stats
    
    # ========== Step 1: 计算换手率突增因子 ==========
    factor_df = calculate_turnover_surge_ratio(factor_df, window=5)
    
    # ========== Step 2: 计算当日涨跌幅 ==========
    print(f"[Step 2] 计算当日涨跌幅...")
    
    # 确保 category 类型可以正确排序
    if factor_df['date'].dtype.name == 'category':
        factor_df['date_str'] = factor_df['date'].astype(str)
    else:
        factor_df['date_str'] = factor_df['date'].astype(str)
    
    # 按股票分组排序
    factor_df = factor_df.sort_values(['asset', 'date_str']).copy()
    
    # 计算当日涨跌幅（使用 groupby + transform，向量化计算）
    factor_df['pct_change'] = factor_df.groupby('asset')['close'].transform(
        lambda x: x.pct_change()
    )
    
    # 释放临时列
    factor_df = factor_df.drop(columns=['date_str'])
    
    # ========== Step 3: 应用筛选条件 ==========
    if filter_conditions:
        print(f"[Step 3] 应用筛选条件...")
        
        # 筛选条件
        turnover_surge_cond = factor_df['turnover_surge'] > 1  # 换手率突增
        price_up = factor_df['pct_change'] > 0  # 上涨
        
        # 统计
        filter_stats['turnover_surge_count'] = turnover_surge_cond.sum()
        filter_stats['price_up_count'] = price_up.sum()
        
        # 同时满足两个条件
        both_conditions = turnover_surge_cond & price_up
        filter_stats['both_conditions_count'] = both_conditions.sum()
        
        # 对不满足条件的因子值设为 None
        factor_df.loc[~both_conditions, 'turnover_surge'] = None
        
        # 统计有效因子值数量
        valid_count = factor_df['turnover_surge'].notna().sum()
        filter_stats['filtered_count'] = valid_count
        filter_stats['filter_ratio'] = valid_count / len(factor_df) if len(factor_df) > 0 else 0
        
        print(f"  总记录数:           {filter_stats['total_records']:,}")
        print(f"  换手率突增记录数:   {filter_stats['turnover_surge_count']:,} ({filter_stats['turnover_surge_count']/filter_stats['total_records']*100:.1f}%)")
        print(f"  上涨记录数:         {filter_stats['price_up_count']:,} ({filter_stats['price_up_count']/filter_stats['total_records']*100:.1f}%)")
        print(f"  换手率突增+上涨:    {filter_stats['both_conditions_count']:,} ({filter_stats['filter_ratio']*100:.1f}%)")
        print(f"  有效因子记录数:     {valid_count:,}")
        
    else:
        # 不筛选，保留所有因子值
        filter_stats['filtered_count'] = len(factor_df)
        filter_stats['filter_ratio'] = 1.0
        print(f"  总记录数: {len(factor_df):,}")
    
    # ========== Step 4: 极端值处理 ==========
    print(f"[Step 4] 极端值处理...")
    
    # 对有效值进行极端值裁剪（范围 [0.5, 10]）
    if factor_df['turnover_surge'].notna().any():
        # 只对非空值进行裁剪
        mask = factor_df['turnover_surge'].notna()
        factor_df.loc[mask, 'turnover_surge'] = factor_df.loc[mask, 'turnover_surge'].clip(0.5, 10)
        
        # 输出统计
        valid_values = factor_df.loc[mask, 'turnover_surge']
        print(f"  因子范围（裁剪后）: [{valid_values.min():.2f}, {valid_values.max():.2f}]")
        print(f"  因子均值: {valid_values.mean():.2f}")
    
    # 强制垃圾回收
    gc.collect()
    
    print(f"[完成] 因子计算完成")
    
    # 修复：转换 filter_stats 中的 numpy 类型为 Python 原生类型
    filter_stats = convert_to_native_types(filter_stats)
    
    return factor_df, filter_stats


def calculate_turnover_surge_ic(
    factor_df: pd.DataFrame,
    return_df: pd.DataFrame,
    factor_col: str = 'turnover_surge',
    return_col: str = 'forward_return'
) -> Dict:
    """
    计算换手率突增因子的 Rank IC
    
    注意：只对有因子值的股票计算 IC（不满足筛选条件的股票已被剔除）
    
    Args:
        factor_df: 包含 date, asset, turnover_surge 的 DataFrame
        return_df: 包含 date, asset, forward_return 的 DataFrame
        factor_col: 因子列名
        return_col: 收益列名
        
    Returns:
        IC 计算结果字典
    """
    print(f"\n{'='*60}")
    print("[IC计算] 计算换手率突增因子 Rank IC")
    print(f"{'='*60}")
    
    # 动态加载 reverse_rank_ic 模块
    import importlib.util
    module_path = Path('/home/admin/.openclaw/workspace/yunzhou/reverse_rank_ic.py')
    spec = importlib.util.spec_from_file_location("reverse_rank_ic", str(module_path))
    reverse_rank_ic_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(reverse_rank_ic_module)
    reverse_rank_ic = reverse_rank_ic_module.reverse_rank_ic
    
    # 合并数据（只保留有因子值的记录）
    factor_cols = ['date', 'asset', factor_col]
    return_cols = ['date', 'asset', return_col]
    
    # 准备合并数据
    factor_data = factor_df[factor_cols].dropna(subset=[factor_col]).copy()
    return_data = return_df[return_cols].copy()
    
    # 修复：统一 date 列类型，解决 category 与 datetime64 不匹配问题
    if factor_data['date'].dtype.name == 'category':
        factor_data['date'] = factor_data['date'].astype('datetime64[ns]')
    if return_data['date'].dtype.name == 'category':
        return_data['date'] = return_data['date'].astype('datetime64[ns]')
    
    merged = pd.merge(
        factor_data,
        return_data,
        on=['date', 'asset'],
        how='inner'
    )
    
    # 释放中间变量
    del factor_data, return_data
    gc.collect()
    
    print(f"  合并后记录数: {len(merged):,}")
    
    if merged.empty:
        print("  ✗ 合并后数据为空")
        return {
            'ic_series': None,
            'ic_mean': 0,
            'ic_std': 0,
            'icir': 0,
            't_stat': 0,
            'p_value': 1,
            'positive_ratio': 0,
            'n_days': 0,
            'n_assets': 0,
            'summary': '数据不足，无法计算IC'
        }
    
    # 计算 IC（使用正向排名，不反向）
    # 换手率突增因子：值越高预期收益越高（正向因子）
    try:
        # 自定义 IC 计算逻辑（不使用反向排名）
        ic_results = []
        
        # 确保 date 列格式一致
        if merged['date'].dtype.name == 'category':
            merged['date'] = merged['date'].astype(str)
        
        for date, group in merged.groupby('date'):
            if len(group) < 10:
                continue
            
            # 检查因子值是否全相同
            if group[factor_col].nunique() == 1:
                continue
            
            # 检查收益值是否全相同
            if group[return_col].nunique() == 1:
                continue
            
            # 横截面排名（正向：因子值越高排名越高）
            factor_rank = group[factor_col].rank(pct=True, ascending=True, method='average')
            return_rank = group[return_col].rank(pct=True, ascending=True, method='average')
            
            # Spearman 相关系数
            ic_value = factor_rank.corr(return_rank, method='spearman')
            
            if pd.notna(ic_value):
                ic_results.append({'date': date, 'ic': ic_value})
        
        if not ic_results:
            print("  ✗ 无法计算 IC")
            return {
                'ic_series': None,
                'ic_mean': 0,
                'ic_std': 0,
                'icir': 0,
                't_stat': 0,
                'p_value': 1,
                'positive_ratio': 0,
                'n_days': 0,
                'n_assets': merged['asset'].nunique(),
                'summary': '无法计算IC'
            }
        
        ic_df = pd.DataFrame(ic_results)
        ic_series = ic_df.set_index('date')['ic']
        
        # 计算统计量
        ic_mean = ic_series.mean()
        ic_std = ic_series.std()
        icir = ic_mean / ic_std if ic_std > 0 else 0
        positive_ratio = (ic_series > 0).mean()
        
        # t 统计量
        import math
        n = len(ic_series)
        t_stat = ic_mean / (ic_std / math.sqrt(n)) if ic_std > 0 else 0
        
        # p 值（双尾检验）
        from scipy import stats
        p_value = 2 * (1 - stats.t.cdf(abs(t_stat), df=n-1)) if n > 1 else 1
        
        # 显著性标注
        abs_t = abs(t_stat)
        if abs_t > 3.29:
            significance = '***'
        elif abs_t > 2.58:
            significance = '**'
        elif abs_t > 1.96:
            significance = '*'
        else:
            significance = ''
        
        # 生成摘要
        if ic_mean > 0.03:
            effectiveness = "因子有效"
        elif ic_mean < -0.03:
            effectiveness = "因子反向有效"
        else:
            effectiveness = "因子预测能力较弱"
        
        summary = f"IC均值={ic_mean:.4f}, ICIR={icir:.2f}, 正比例={positive_ratio:.1%}, {effectiveness}"
        
        print(f"  IC 均值: {ic_mean:.4f}")
        print(f"  IC 标准差: {ic_std:.4f}")
        print(f"  ICIR: {icir:.2f}")
        print(f"  t 统计量: {t_stat:.4f}{significance}")
        print(f"  正 IC 比例: {positive_ratio:.1%}")
        
        return {
            'ic_series': ic_series,
            'ic_mean': ic_mean,
            'ic_std': ic_std,
            'icir': icir,
            't_stat': round(t_stat, 4),
            'p_value': round(p_value, 6),
            'positive_ratio': positive_ratio,
            'n_days': n,
            'n_assets': merged['asset'].nunique(),
            'significance': significance,
            'summary': summary
        }
        
    except Exception as e:
        print(f"  ✗ IC 计算失败: {e}")
        import traceback
        traceback.print_exc()
        return {
            'ic_series': None,
            'ic_mean': 0,
            'ic_std': 0,
            'icir': 0,
            't_stat': 0,
            'p_value': 1,
            'positive_ratio': 0,
            'n_days': 0,
            'n_assets': 0,
            'summary': f'IC计算失败: {str(e)}'
        }


def run_turnover_surge_analysis(
    n_days: int = 500,
    num_layers: int = 5,
    filter_conditions: bool = True
) -> Dict:
    """
    执行完整的换手率突增因子分析（内存优化版 v2）
    
    因子定义：
    - 换手率突增 = 当日换手率 / 过去5日换手率均值
    - 使用真实换手率数据（turnover_rate），来自 baostock
    
    筛选条件：
    - 换手率突增 > 1（当日换手率高于近期均值）
    - 当日涨跌幅 > 0（上涨）
    
    内存优化策略：
    1. 分批处理，避免一次性创建大列表
    2. 内存监控，超过阈值时暂停
    3. 及时释放中间变量
    4. 分阶段保存结果
    
    步骤：
    1. 加载数据（内存优化）
    2. 计算因子（带筛选条件）
    3. 计算 IC
    4. 执行分层回测
    5. 返回完整结果
    
    Args:
        n_days: 交易日数量
        num_layers: 分层数量
        filter_conditions: 是否应用筛选条件
        
    Returns:
        完整分析结果字典
    """
    from datetime import datetime
    from layered_backtest import LayeredBacktest
    
    print(f"\n{'='*80}")
    print("换手率突增因子分析（内存优化版 v2）")
    print("使用真实换手率数据计算")
    print(f"  内存阈值: {MEMORY_THRESHOLD_MB} MB")
    print(f"{'='*80}")
    print(f"  开始时间: {datetime.now().isoformat()}")
    print(f"  初始内存: {get_memory_info_str()}")
    
    initial_mem = get_memory_usage_mb()
    
    # ========== Step 1: 加载数据 ==========
    check_memory_threshold()
    factor_df, return_df = load_data_for_turnover_surge(max_days=n_days)
    
    if factor_df is None or return_df is None:
        return {
            'success': False,
            'error': '数据加载失败'
        }
    
    current_mem = get_memory_usage_mb()
    print(f"  数据加载后内存: {current_mem:.1f} MB (增加 {current_mem - initial_mem:.1f} MB)")
    
    # ========== Step 2: 计算因子 ==========
    print(f"\n[Step 2] 计算因子...")
    check_memory_threshold()
    factor_df, filter_stats = calculate_turnover_surge_factor(factor_df, filter_conditions)
    
    current_mem = get_memory_usage_mb()
    print(f"  因子计算后内存: {current_mem:.1f} MB")
    
    # ========== Step 3: 计算 IC ==========
    print(f"\n[Step 3] 计算 IC...")
    check_memory_threshold()
    ic_result = calculate_turnover_surge_ic(factor_df, return_df)
    
    current_mem = get_memory_usage_mb()
    print(f"  IC计算后内存: {current_mem:.1f} MB")
    
    # ========== Step 4: 分层回测 ==========
    print(f"\n[Step 4] 分层回测...")
    check_memory_threshold()
    
    # 准备分层回测数据
    backtest_factor_df = factor_df[['date', 'asset', 'turnover_surge']].copy()
    backtest_return_df = return_df[['date', 'asset', 'forward_return']].copy()
    
    # 释放原始数据
    del factor_df, return_df
    gc.collect()
    
    # 执行分层回测
    try:
        backtest = LayeredBacktest(num_layers=num_layers)
        layered_result = backtest.run(
            backtest_factor_df, 
            backtest_return_df, 
            factor_col='turnover_surge',
            return_col='forward_return'
        )
    except Exception as e:
        print(f"  ✗ 分层回测失败: {e}")
        import traceback
        traceback.print_exc()
        layered_result = None
    
    del backtest_factor_df, backtest_return_df
    gc.collect()
    
    current_mem = get_memory_usage_mb()
    print(f"  分层回测后内存: {current_mem:.1f} MB")
    
    # ========== Step 5: 构建结果 ==========
    print(f"\n[Step 5] 整理分析结果...")
    check_memory_threshold()
    
    # IC 指标
    ic_metrics = {
        'ic_mean': ic_result.get('ic_mean', 0),
        'ic_std': ic_result.get('ic_std', 0),
        'icir': ic_result.get('icir', 0),
        't_stat': ic_result.get('t_stat', 0),
        'p_value': ic_result.get('p_value', 1),
        'positive_ratio': ic_result.get('positive_ratio', 0),
        'n_days': ic_result.get('n_days', 0),
        'n_assets': ic_result.get('n_assets', 0),
        'significance': ic_result.get('significance', ''),
        'summary': ic_result.get('summary', '')
    }
    
    # IC 时间序列
    ic_series = ic_result.get('ic_series')
    if ic_series is not None:
        rolling_mean = ic_series.rolling(window=20, min_periods=1).mean()
        ic_series_data = {
            'dates': [str(d.date()) if hasattr(d, 'date') else str(d).split()[0] for d in ic_series.index],
            'ic_values': [round(v, 6) for v in ic_series.values],
            'rolling_ic_mean': [round(v, 6) for v in rolling_mean.values]
        }
        del ic_series, rolling_mean
    else:
        ic_series_data = {
            'dates': [],
            'ic_values': [],
            'rolling_ic_mean': []
        }
    
    del ic_result
    gc.collect()
    
    # 分层回测结果
    if layered_result is not None:
        # 转换函数
        def convert_df_dates(df_dict):
            converted = []
            for row in df_dict:
                new_row = {}
                for k, v in row.items():
                    if k in ('date', 'trade_date'):
                        if hasattr(v, 'strftime'):
                            new_row[k] = v.strftime('%Y-%m-%d')
                        else:
                            new_row[k] = str(v)
                    else:
                        new_row[k] = v
                converted.append(new_row)
            return converted
        
        # 最大回撤
        def calculate_max_drawdown(nav_series):
            peak = nav_series.expanding(min_periods=1).max()
            drawdown = (nav_series / peak) - 1
            return round(drawdown.min(), 4)
        
        # 单调性检验（换手率突增因子：预期 Layer 1 收益低，Layer N 收益高）
        def calculate_monotonicity(statistics_df):
            layer_returns = []
            for i in range(1, num_layers + 1):
                layer_key = f'layer_{i}'
                if layer_key in statistics_df.index:
                    layer_returns.append(statistics_df.loc[layer_key, 'annual_return'])
            
            for i in range(len(layer_returns) - 1):
                if layer_returns[i] > layer_returns[i + 1]:
                    return False
            return True
        
        long_short_stats = layered_result.statistics.loc['long_short']
        summary = {
            'long_short_annual_return': round(float(long_short_stats['annual_return']), 4),
            'long_short_sharpe': round(float(long_short_stats['sharpe']), 4),
            'long_short_max_drawdown': calculate_max_drawdown(layered_result.long_short['cumulative_nav']),
            'monotonicity_passed': calculate_monotonicity(layered_result.statistics)
        }
        
        layered_result_json = {
            'layer_returns': convert_df_dates(layered_result.layer_returns.reset_index().to_dict(orient='records')),
            'cumulative_returns': convert_df_dates(layered_result.cumulative_returns.reset_index().to_dict(orient='records')),
            'statistics': layered_result.statistics.reset_index().to_dict(orient='records'),
            'long_short': convert_df_dates(layered_result.long_short.reset_index().to_dict(orient='records')),
            'num_layers': num_layers,
            'n_days': len(layered_result.layer_returns),
            'n_stocks': ic_metrics['n_assets'],
            'summary': summary
        }
        
        del layered_result
    else:
        layered_result_json = {
            'layer_returns': [],
            'cumulative_returns': [],
            'statistics': [],
            'long_short': [],
            'num_layers': num_layers,
            'n_days': 0,
            'n_stocks': 0,
            'summary': {
                'long_short_annual_return': 0,
                'long_short_sharpe': 0,
                'long_short_max_drawdown': 0,
                'monotonicity_passed': False
            }
        }
    
    gc.collect()
    
    # 构建完整结果
    result = {
        'success': True,
        'ic_metrics': ic_metrics,
        'ic_series': ic_series_data,
        'layered_result': layered_result_json,
        'filter_stats': filter_stats,
        'params': {
            'n_days': n_days,
            'max_stocks': 0,
            'num_layers': num_layers,
            'factor_col': 'turnover_surge',
            'filter_conditions': filter_conditions
        },
        'generated_at': datetime.now().isoformat()
    }
    
    # 修复：转换结果中的所有 numpy 类型为 Python 原生类型，确保 JSON 可序列化
    result = convert_to_native_types(result)
    
    final_mem = get_memory_usage_mb()
    print(f"  最终内存: {final_mem:.1f} MB (峰值增量: {final_mem - initial_mem:.1f} MB)")
    print(f"  完成时间: {datetime.now().isoformat()}")
    print(f"{'='*80}")
    
    return result


if __name__ == '__main__':
    """测试换手率突增因子分析"""
    result = run_turnover_surge_analysis(n_days=500, num_layers=5)
    
    if result.get('success'):
        print("\n测试成功！")
        print(f"IC均值: {result['ic_metrics']['ic_mean']:.4f}")
        print(f"ICIR: {result['ic_metrics']['icir']:.2f}")
        print(f"多空收益: {result['layered_result']['summary']['long_short_annual_return']:.2%}")
    else:
        print(f"\n测试失败: {result.get('error')}")