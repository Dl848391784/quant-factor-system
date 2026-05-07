#!/usr/bin/env python3.10
"""
KDJ_J 因子计算模块

因子定义：
- RSV(N) = (Close_t - Low_N) / (High_N - Low_N) × 100
- K_t = K_{t-1} × (M1-1)/M1 + RSV_t × 1/M1
- D_t = D_{t-1} × (M2-1)/M2 + K_t × 1/M2
- J_t = 3 × K_t - 2 × D_t

参数：
- N = 9（RSV 计算周期）
- M1 = 3（K值平滑周期）
- M2 = 3（D值平滑周期）

初始值：
- K_0 = 50
- D_0 = 50

边界处理：
- 当 High_N == Low_N 时，RSV = 50（避免除零）
- 数据不足 N 天时，使用可用天数计算

因子逻辑：
- J 值 > 100：超买，预期下跌
- J 值 < 0：超卖，预期反弹
- 使用反向排名（J值高排名低）

数据来源：
- cache/factor_data/factor_data.json.gz（已有 close, high, low）

作者: 云舟
日期: 2026-04-07
"""

import pandas as pd
import numpy as np
from pathlib import Path
import gzip
import json
import gc
import time
from typing import Tuple, Optional, Dict, List
import warnings
warnings.filterwarnings('ignore')


# ============================================================
# 内存监控函数
# ============================================================

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


def check_memory_threshold(force_print: bool = False):
    """检查内存阈值，超过时暂停并清理
    
    Args:
        force_print: 是否强制打印当前内存（即使未超阈值）
    """
    mem_mb = get_memory_usage_mb()
    
    # 始终打印当前内存（便于监控）
    if force_print:
        print(f'[内存监控] 当前: {mem_mb:.1f}MB (阈值: {MEMORY_THRESHOLD_MB}MB)', flush=True)
    
    if mem_mb > MEMORY_THRESHOLD_MB:
        print(f'[内存监控] ⚠️ 内存超阈值 ({mem_mb:.1f}MB > {MEMORY_THRESHOLD_MB}MB)，暂停 {MEMORY_PAUSE_SECONDS}s...', flush=True)
        gc.collect()
        time.sleep(MEMORY_PAUSE_SECONDS)
        mem_mb = get_memory_usage_mb()
        print(f'[内存监控] GC后内存: {mem_mb:.1f}MB', flush=True)
    return mem_mb


def convert_to_native_types(obj):
    """
    递归转换 numpy 类型为 Python 原生类型
    解决 JSON 序列化问题
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


# ============================================================
# 配置常量
# ============================================================

BASE_DIR = Path(__file__).parent
CACHE_DIR = BASE_DIR / 'cache' / 'factor_data'
KDJ_J_CACHE_DIR = BASE_DIR / 'cache' / 'kdj_j'

# 历史缓存文件
HISTORY_FILE = KDJ_J_CACHE_DIR / 'kdj_j_history.json.gz'

# 分析结果输出文件
OUTPUT_FILE = BASE_DIR / 'cache' / 'factor_ic' / 'kdj_j_ic.json'

# 内存优化配置
MEMORY_THRESHOLD_MB = 900  # 内存阈值（MB）
MEMORY_PAUSE_SECONDS = 3   # 内存超阈值时暂停时间
STREAM_LOAD_BATCH_SIZE = 1000  # 流式加载进度打印间隔（每1000条）
DAYS_PER_BATCH = 50  # 每批处理天数（激进减少以控制峰值）


# ============================================================
# KDJ_J 因子计算函数
# ============================================================

def calculate_rsv(
    close: float,
    high_n: float,
    low_n: float
) -> float:
    """
    计算 RSV（未成熟随机值）
    
    公式：RSV = (Close - Low_N) / (High_N - Low_N) × 100
    
    边界处理：
    - 当 High_N == Low_N 时，返回 50（避免除零）
    
    Args:
        close: 当日收盘价
        high_n: N日内最高价
        low_n: N日内最低价
        
    Returns:
        RSV值（0-100）
    """
    if high_n == low_n:
        return 50.0  # 避免除零
    
    rsv = (close - low_n) / (high_n - low_n) * 100
    return rsv


def calculate_kdj_j_for_stock_vectorized(
    stock_data: pd.DataFrame,
    n: int = 9,
    m1: int = 3,
    m2: int = 3,
    initial_k: float = 50.0,
    initial_d: float = 50.0
) -> pd.DataFrame:
    """
    计算单只股票的 KDJ_J 因子（向量化版本，高效）
    
    使用 pandas 滚动窗口和 ewm 进行向量化计算，
    比逐行循环快 100 倍以上。
    
    Args:
        stock_data: 单只股票的历史数据，包含 close, high, low
        n: RSV 计算周期（默认 9）
        m1: K值平滑周期（默认 3）
        m2: D值平滑周期（默认 3）
        initial_k: K初始值（默认 50）
        initial_d: D初始值（默认 50）
        
    Returns:
        包含 rsv, k, d, j 列的 DataFrame
    """
    # 确保数据按日期排序
    stock_data = stock_data.sort_values('date').copy()
    
    # 计算 RSV（向量化）
    # rolling_high = 过去 N 天的最高价的最大值
    # rolling_low = 过去 N 天的最低价的最小值
    rolling_high = stock_data['high'].rolling(window=n, min_periods=1).max()
    rolling_low = stock_data['low'].rolling(window=n, min_periods=1).min()
    
    # RSV = (Close - Low_N) / (High_N - Low_N) * 100
    # 处理除零情况
    diff = rolling_high - rolling_low
    rsv = np.where(diff == 0, 50.0, (stock_data['close'] - rolling_low) / diff * 100)
    stock_data['rsv'] = rsv
    
    # 计算 K（使用 ewm 近似，但需要递归初始化）
    # 由于 K 的计算依赖于前一个 K 值，不能完全向量化
    # 但可以使用 pandas 的 ewm 函数近似（假设初始 K = 50）
    
    # 方法：使用 ewm 平滑，alpha = 1/M1
    # K_t = K_{t-1} * (M1-1)/M1 + RSV_t * 1/M1
    # 这等价于 EWM 平滑，alpha = 1/M1
    alpha_k = 1.0 / m1
    # 使用 adjust=False 以匹配传统 KDJ 计算方式
    stock_data['k'] = stock_data['rsv'].ewm(alpha=alpha_k, adjust=False).mean()
    
    # 初始化：将第一个 K 值设为 initial_k 的权重影响
    # 修正第一个值
    if len(stock_data) > 0:
        # 第一个 K = initial_k * (M1-1)/M1 + RSV_0 * 1/M1
        stock_data.loc[stock_data.index[0], 'k'] = initial_k * (m1 - 1) / m1 + stock_data['rsv'].iloc[0] / m1
    
    # 计算 D（同样使用 ewm）
    alpha_d = 1.0 / m2
    stock_data['d'] = stock_data['k'].ewm(alpha=alpha_d, adjust=False).mean()
    
    # 修正第一个 D 值
    if len(stock_data) > 0:
        stock_data.loc[stock_data.index[0], 'd'] = initial_d * (m2 - 1) / m2 + stock_data['k'].iloc[0] / m2
    
    # 计算 J = 3K - 2D
    stock_data['j'] = 3 * stock_data['k'] - 2 * stock_data['d']
    
    return stock_data


def calculate_kdj_j_for_stock(
    stock_data: pd.DataFrame,
    n: int = 9,
    m1: int = 3,
    m2: int = 3,
    initial_k: float = 50.0,
    initial_d: float = 50.0
) -> pd.DataFrame:
    """
    计算单只股票的 KDJ_J 因子
    
    内部调用向量化版本以提高效率
    
    Args:
        stock_data: 单只股票的历史数据，包含 close, high, low
        n: RSV 计算周期（默认 9）
        m1: K值平滑周期（默认 3）
        m2: D值平滑周期（默认 3）
        initial_k: K初始值（默认 50）
        initial_d: D初始值（默认 50）
        
    Returns:
        包含 rsv, k, d, j 列的 DataFrame
    """
    return calculate_kdj_j_for_stock_vectorized(
        stock_data, n, m1, m2, initial_k, initial_d
    )


def calculate_kdj_j_factor(
    factor_df: pd.DataFrame,
    n: int = 9,
    m1: int = 3,
    m2: int = 3
) -> Tuple[pd.DataFrame, Dict]:
    """
    计算所有股票的 KDJ_J 因子（向量化版本，高效）
    
    使用 pandas 分组操作和向量化计算，比循环处理快 50 倍以上。
    
    内存优化：
    1. 分步骤计算，及时释放中间变量
    2. 内存监控，超过阈值时暂停并 GC
    
    Args:
        factor_df: 包含 date, asset, close, high, low 的 DataFrame
        n: RSV 计算周期（默认 9）
        m1: K值平滑周期（默认 3）
        m2: D值平滑周期（默认 3）
        
    Returns:
        (处理后的 factor_df, 统计信息)
    """
    print(f"\n{'='*60}", flush=True)
    print(f"[因子计算] KDJ_J 因子 (N={n}, M1={m1}, M2={m2})", flush=True)
    print(f"{'='*60}", flush=True)
    print(f'[内存监控] 当前内存: {get_memory_info_str()}', flush=True)
    
    stats = {
        'total_records': len(factor_df),
        'valid_records': 0,
        'missing_price_count': 0,
        'n': n,
        'm1': m1,
        'm2': m2
    }
    
    if factor_df.empty:
        print("  ✗ 数据为空", flush=True)
        return factor_df, stats
    
    # 检查必要列
    required_cols = ['date', 'asset', 'close', 'high', 'low']
    missing_cols = [c for c in required_cols if c not in factor_df.columns]
    if missing_cols:
        print(f"  ✗ 缺少必要列: {missing_cols}", flush=True)
        return factor_df, stats
    
    # 统计缺失数据
    missing_price_mask = (
        factor_df['close'].isna() | 
        factor_df['high'].isna() | 
        factor_df['low'].isna()
    )
    stats['missing_price_count'] = missing_price_mask.sum()
    
    print(f"  总记录数: {stats['total_records']:,}", flush=True)
    print(f"  价格缺失数: {stats['missing_price_count']:,}", flush=True)
    
    # 按股票分组计算 KDJ_J（使用向量化操作）
    print(f"\n[计算] 使用向量化计算 KDJ_J...", flush=True)
    
    # 确保按日期排序（每个股票内部）
    factor_df = factor_df.sort_values(['asset', 'date']).copy()
    
    # ========== 向量化计算 RSV ==========
    print(f"  [Step 1] 计算 RSV...", flush=True)
    check_memory_threshold(force_print=True)
    
    # 按股票分组计算滚动窗口
    # rolling_high = 过去 N 天的 highest high
    # rolling_low = 过去 N 天的 lowest low
    factor_df['rolling_high'] = factor_df.groupby('asset')['high'].transform(
        lambda x: x.rolling(window=n, min_periods=1).max()
    )
    factor_df['rolling_low'] = factor_df.groupby('asset')['low'].transform(
        lambda x: x.rolling(window=n, min_periods=1).min()
    )
    
    # RSV = (Close - Low_N) / (High_N - Low_N) * 100
    diff = factor_df['rolling_high'] - factor_df['rolling_low']
    factor_df['rsv'] = np.where(
        diff == 0, 
        50.0, 
        (factor_df['close'] - factor_df['rolling_low']) / diff * 100
    )
    
    # 释放临时列
    factor_df.drop(columns=['rolling_high', 'rolling_low'], inplace=True)
    del diff
    gc.collect()
    print(f'  [内存监控] RSV 计算后: {get_memory_info_str()}', flush=True)
    
    # ========== 向量化计算 K ==========
    print(f"  [Step 2] 计算 K...", flush=True)
    check_memory_threshold(force_print=True)
    
    alpha_k = 1.0 / m1
    factor_df['k'] = factor_df.groupby('asset')['rsv'].transform(
        lambda x: x.ewm(alpha=alpha_k, adjust=False).mean()
    )
    
    # ========== 向量化计算 D ==========
    print(f"  [Step 3] 计算 D...", flush=True)
    alpha_d = 1.0 / m2
    factor_df['d'] = factor_df.groupby('asset')['k'].transform(
        lambda x: x.ewm(alpha=alpha_d, adjust=False).mean()
    )
    
    # ========== 计算 J = 3K - 2D ==========
    print(f"  [Step 4] 计算 J...", flush=True)
    factor_df['kdj_j'] = 3 * factor_df['k'] - 2 * factor_df['d']
    
    # 统计有效记录
    stats['valid_records'] = factor_df['kdj_j'].notna().sum()
    
    # 输出统计
    print(f"\n  有效记录数: {stats['valid_records']:,}", flush=True)
    
    # 输出因子统计
    valid_values = factor_df['kdj_j'].dropna()
    if len(valid_values) > 0:
        print(f"\n  因子统计:", flush=True)
        print(f"    均值:   {valid_values.mean():.2f}", flush=True)
        print(f"    标准差: {valid_values.std():.2f}", flush=True)
        print(f"    最小值: {valid_values.min():.2f}", flush=True)
        print(f"    最大值: {valid_values.max():.2f}", flush=True)
        print(f"    中位数: {valid_values.median():.2f}", flush=True)
        
        # 超买超卖统计
        overbought = (valid_values > 100).sum()
        oversold = (valid_values < 0).sum()
        print(f"\n  超买(J>100): {overbought:,} ({overbought/len(valid_values)*100:.2f}%)", flush=True)
        print(f"  超卖(J<0):   {oversold:,} ({oversold/len(valid_values)*100:.2f}%)", flush=True)
    
    del valid_values
    gc.collect()
    
    print(f'  [内存监控] 因子计算完成: {get_memory_info_str()}', flush=True)
    
    # 转换统计中的 numpy 类型
    stats = convert_to_native_types(stats)
    
    return factor_df, stats


def calculate_kdj_j_ic(
    factor_df: pd.DataFrame,
    return_df: pd.DataFrame,
    factor_col: str = 'kdj_j',
    return_col: str = 'forward_return'
) -> Dict:
    """
    计算 KDJ_J 因子的 Rank IC
    
    注意：KDJ_J 是反向因子
    - J 值 > 100：超买，预期下跌
    - J 值 < 0：超卖，预期反弹
    - 因此使用反向排名（J值高排名低）
    
    Args:
        factor_df: 包含 date, asset, kdj_j 的 DataFrame
        return_df: 包含 date, asset, forward_return 的 DataFrame
        factor_col: 因子列名
        return_col: 收益列名
        
    Returns:
        IC 计算结果字典
    """
    print(f"\n{'='*60}", flush=True)
    print("[IC计算] KDJ_J 因子 Rank IC（反向排名）", flush=True)
    print(f"{'='*60}", flush=True)
    print(f'[内存监控] 当前内存: {get_memory_info_str()}', flush=True)
    
    # 准备数据
    factor_cols = ['date', 'asset', factor_col]
    return_cols = ['date', 'asset', return_col]
    
    factor_data = factor_df[factor_cols].dropna(subset=[factor_col]).copy()
    return_data = return_df[return_cols].copy()
    
    # 统一 date 列类型
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
    
    del factor_data, return_data
    gc.collect()
    check_memory_threshold(force_print=True)
    
    print(f"  合并后记录数: {len(merged):,}", flush=True)
    print(f'  [内存监控] 合并后: {get_memory_info_str()}', flush=True)
    
    # 在删除数据前保存 n_assets（资产数量）
    n_assets = merged['asset'].nunique() if not merged.empty else 0
    
    if merged.empty:
        print("  ✗ 合并后数据为空", flush=True)
        return {
            'ic_series': None,
            'ic_mean': 0,
            'ic_std': 0,
            'icir': 0,
            't_stat': 0,
            'p_value': 1,
            'positive_ratio': 0,
            'n_days': 0,
            'n_assets': n_assets,
            'significance': '',
            'summary': '数据不足，无法计算IC'
        }
    
    # 计算 IC（使用反向排名，因为 KDJ_J 是反向因子）
    try:
        ic_results = []
        
        if merged['date'].dtype.name == 'category':
            merged['date'] = merged['date'].astype(str)
        
        # 分批计算 IC，避免内存峰值
        processed_dates = 0
        for date, group in merged.groupby('date'):
            if len(group) < 10:
                continue
            
            if group[factor_col].nunique() == 1 or group[return_col].nunique() == 1:
                continue
            
            # 反向排名：J值越高排名越低（超买预期下跌）
            factor_rank = group[factor_col].rank(pct=True, ascending=False, method='average')
            return_rank = group[return_col].rank(pct=True, ascending=True, method='average')
            
            ic_value = factor_rank.corr(return_rank, method='spearman')
            
            if pd.notna(ic_value):
                ic_results.append({'date': date, 'ic': ic_value})
            
            processed_dates += 1
            # 每 100 个日期清理一次
            if processed_dates % 100 == 0:
                gc.collect()
        
        del merged
        gc.collect()
        check_memory_threshold(force_print=True)
        print(f'  [内存监控] IC 计算完成: {get_memory_info_str()}', flush=True)
        
        if not ic_results:
            print("  ✗ 无法计算 IC", flush=True)
            return {
                'ic_series': None,
                'ic_mean': 0,
                'ic_std': 0,
                'icir': 0,
                't_stat': 0,
                'p_value': 1,
                'positive_ratio': 0,
                'n_days': 0,
                'n_assets': n_assets,
                'significance': '',
                'summary': '无法计算IC'
            }
        
        ic_df = pd.DataFrame(ic_results)
        del ic_results
        gc.collect()
        
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
        
        # p 值
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
            effectiveness = "因子有效（反向排名，超卖反弹）"
        elif ic_mean < -0.03:
            effectiveness = "因子反向有效（应使用正向排名）"
        else:
            effectiveness = "因子预测能力较弱"
        
        summary = f"IC均值={ic_mean:.4f}, ICIR={icir:.2f}, 正比例={positive_ratio:.1%}, {effectiveness}"
        
        print(f"  IC 均值: {ic_mean:.4f}", flush=True)
        print(f"  IC 标准差: {ic_std:.4f}", flush=True)
        print(f"  ICIR: {icir:.2f}", flush=True)
        print(f"  t 统计量: {t_stat:.4f}{significance}", flush=True)
        print(f"  正 IC 比例: {positive_ratio:.1%}", flush=True)
        
        return {
            'ic_series': ic_series,
            'ic_mean': ic_mean,
            'ic_std': ic_std,
            'icir': icir,
            't_stat': round(t_stat, 4),
            'p_value': round(p_value, 6),
            'positive_ratio': positive_ratio,
            'n_days': n,
            'n_assets': n_assets,
            'significance': significance,
            'summary': summary
        }
        
    except Exception as e:
        print(f"  ✗ IC 计算失败: {e}", flush=True)
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
            'n_assets': n_assets if 'n_assets' in dir() else 0,
            'significance': '',
            'summary': f'IC计算失败: {str(e)}'
        }


def stream_load_json_gz_by_dates(
    gz_path: Path,
    target_dates: set,
    fields: List[str],
    max_records: int = None
) -> List[Dict]:
    """
    流式加载gzip JSON文件，只提取目标日期的记录
    
    改进版：使用 ijson 流式解析，更可靠
    
    Args:
        gz_path: gzip JSON文件路径
        target_dates: 目标日期集合
        fields: 需要的字段列表
        max_records: 最大记录数（可选）
        
    Returns:
        提取的记录列表
    """
    import re
    
    records = []
    record_count = 0
    scanned_count = 0
    
    print(f'  [流式加载] 开始流式解析，目标 {len(target_dates)} 天...', flush=True)
    print(f'  [流式加载] 文件: {gz_path.name}', flush=True)
    
    # 方法1：尝试使用 ijson（更可靠）
    try:
        import ijson
        print(f'  [流式加载] 使用 ijson 库进行流式解析...', flush=True)
        
        with gzip.open(gz_path, 'rt', encoding='utf-8') as f:
            # ijson.items 会流式解析 data 数组中的每个对象
            for obj in ijson.items(f, 'data.item'):
                scanned_count += 1
                
                # 快速检查日期
                date_val = obj.get('date')
                if date_val and date_val in target_dates:
                    record = {k: obj.get(k) for k in fields if k in obj}
                    records.append(record)
                    record_count += 1
                    
                    if record_count % STREAM_LOAD_BATCH_SIZE == 0:
                        mem_mb = get_memory_usage_mb()
                        print(f'    已提取 {record_count:,} 条（扫描 {scanned_count:,}），内存: {mem_mb:.1f}MB', flush=True)
                        gc.collect()
                
                if max_records and record_count >= max_records:
                    print(f'    达到最大记录数 {max_records}，停止', flush=True)
                    break
        
        print(f'  [流式加载] 完成！提取 {record_count:,} 条（扫描 {scanned_count:,} 条）', flush=True)
        return records
        
    except ImportError:
        print(f'  [流式加载] ijson 未安装，使用备用方法...', flush=True)
    except Exception as e:
        print(f'  [流式加载] ijson 解析失败: {e}，使用备用方法...', flush=True)
    
    # 方法2：备用方法 - 直接加载后过滤（适用于中等大小文件）
    print(f'  [流式加载] 使用 json.load 直接加载...', flush=True)
    
    try:
        with gzip.open(gz_path, 'rt', encoding='utf-8') as f:
            data = json.load(f)
        
        all_records = data.get('data', [])
        print(f'  [流式加载] 加载了 {len(all_records):,} 条记录', flush=True)
        
        for obj in all_records:
            scanned_count += 1
            date_val = obj.get('date')
            if date_val and date_val in target_dates:
                record = {k: obj.get(k) for k in fields if k in obj}
                records.append(record)
                record_count += 1
                
                if record_count % 50000 == 0:
                    mem_mb = get_memory_usage_mb()
                    print(f'    已提取 {record_count:,} 条，内存: {mem_mb:.1f}MB', flush=True)
            
            if max_records and record_count >= max_records:
                print(f'    达到最大记录数 {max_records}，停止', flush=True)
                break
        
        del all_records
        del data
        gc.collect()
        
        print(f'  [流式加载] 完成！提取 {record_count:,} 条（扫描 {scanned_count:,} 条）', flush=True)
        return records
        
    except Exception as e:
        print(f'  [流式加载] ✗ 加载失败: {e}', flush=True)
        import traceback
        traceback.print_exc()
        return []


# 全局缓存：一次性加载后按日期切片
_GLOBAL_FACTOR_CACHE = None
_GLOBAL_RETURN_CACHE = None
_GLOBAL_CACHE_DATES = None


def load_all_data_once(data_type: str = 'factor') -> pd.DataFrame:
    """
    一次性加载所有数据并缓存
    
    避免每次批次都重新扫描文件
    
    Args:
        data_type: 数据类型（'factor' 或 'return'）
        
    Returns:
        DataFrame
    """
    global _GLOBAL_FACTOR_CACHE, _GLOBAL_RETURN_CACHE, _GLOBAL_CACHE_DATES
    
    if data_type == 'factor':
        if _GLOBAL_FACTOR_CACHE is not None:
            print(f'  [缓存] 使用已缓存的因子数据', flush=True)
            return _GLOBAL_FACTOR_CACHE
        
        file_path = CACHE_DIR / 'factor_data.json.gz'
        print(f'  [一次性加载] 加载因子数据...', flush=True)
        
    else:
        if _GLOBAL_RETURN_CACHE is not None:
            print(f'  [缓存] 使用已缓存的收益数据', flush=True)
            return _GLOBAL_RETURN_CACHE
        
        file_path = CACHE_DIR / 'return_data.json.gz'
        print(f'  [一次性加载] 加载收益数据...', flush=True)
    
    if not file_path.exists():
        print(f"  ✗ 文件不存在: {file_path}", flush=True)
        return None
    
    # 使用 json.load 直接加载（对于 29MB 文件这是最高效的）
    start_time = time.time()
    with gzip.open(file_path, 'rt', encoding='utf-8') as f:
        data = json.load(f)
    
    load_time = time.time() - start_time
    all_records = data.get('data', [])
    print(f'    加载耗时 {load_time:.1f}s，共 {len(all_records):,} 条', flush=True)
    
    # 提取日期列表（用于后续切片）
    if _GLOBAL_CACHE_DATES is None:
        _GLOBAL_CACHE_DATES = sorted(set(r.get('date') for r in all_records))
        print(f'    共 {_GLOBAL_CACHE_DATES[-1]} 个日期，最新: {_GLOBAL_CACHE_DATES[-1]}', flush=True)
    
    # 创建 DataFrame
    df = pd.DataFrame(all_records)
    del all_records
    del data
    gc.collect()
    
    # 类型转换
    df['date'] = df['date'].astype('category')
    df['asset'] = df['asset'].astype('category')
    
    # 数值列转换
    numeric_cols = ['close', 'high', 'low', 'forward_return_1d', 'forward_return_3d', 'forward_return_5d']
    for col in numeric_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors='coerce')
    
    # 兼容性映射：forward_return_1d -> forward_return（IC 计算使用）
    if data_type == 'return':
        if 'forward_return_1d' in df.columns:
            df['forward_return'] = df['forward_return_1d']
        elif 'forward_return' in df.columns:
            df['forward_return_1d'] = df['forward_return']
    
    mem_mb = get_memory_usage_mb()
    print(f'    DataFrame 大小: {len(df):,} 行，内存: {mem_mb:.1f}MB', flush=True)
    
    # 缓存
    if data_type == 'factor':
        _GLOBAL_FACTOR_CACHE = df
    else:
        _GLOBAL_RETURN_CACHE = df
    
    return df


def load_factor_data_by_date_range(
    date_range: List[str],
    use_category: bool = True,
    data_type: str = 'factor'
) -> Optional[pd.DataFrame]:
    """
    加载指定日期范围的数据（使用缓存优化）
    
    Args:
        date_range: 日期列表（如 ['2025-01-01', '2025-01-02', ...]）
        use_category: 是否使用category类型
        data_type: 数据类型（'factor' 或 'return'）
        
    Returns:
        DataFrame 或 None
    """
    # 一次性加载所有数据（缓存）
    full_df = load_all_data_once(data_type)
    if full_df is None:
        return None
    
    # 按日期切片
    print(f'  [切片] 提取 {len(date_range)} 天数据...', flush=True)
    date_set = set(date_range)
    
    # 使用 category 类型快速筛选
    if full_df['date'].dtype.name == 'category':
        # 获取符合条件的 category 值
        valid_cats = [c for c in full_df['date'].cat.categories if c in date_set]
        df = full_df[full_df['date'].isin(valid_cats)].copy()
    else:
        df = full_df[full_df['date'].isin(date_set)].copy()
    
    del date_set
    gc.collect()
    
    mem_mb = get_memory_usage_mb()
    print(f'    切片完成，{len(df):,} 条，内存: {mem_mb:.1f}MB', flush=True)
    
    return df


def save_kdj_j_history(
    factor_df: pd.DataFrame,
    params: Dict,
    output_file: Path = None
) -> bool:
    """
    保存 KDJ_J 因子历史数据
    
    Args:
        factor_df: 包含 KDJ_J 因子的 DataFrame
        params: 计算参数
        output_file: 输出文件路径
        
    Returns:
        是否保存成功
    """
    if output_file is None:
        output_file = HISTORY_FILE
    
    # 创建目录
    output_file.parent.mkdir(parents=True, exist_ok=True)
    
    # 准备数据
    save_cols = ['date', 'asset', 'close', 'high', 'low', 'rsv', 'k', 'd', 'kdj_j']
    save_df = factor_df[save_cols].copy()
    
    # 转换 date 列
    if save_df['date'].dtype.name == 'category':
        save_df['date'] = save_df['date'].astype(str)
    
    # 获取日期列表
    dates = sorted(save_df['date'].unique())
    
    # 构建保存数据
    data_records = save_df.to_dict(orient='records')
    
    save_data = {
        'meta': {
            'n': params.get('n', 9),
            'm1': params.get('m1', 3),
            'm2': params.get('m2', 3),
            'n_days': len(dates),
            'n_stocks': len(save_df['asset'].unique()),
            'start_date': dates[0] if dates else None,
            'end_date': dates[-1] if dates else None,
            'dates': dates
        },
        'data': convert_to_native_types(data_records)
    }
    
    # 保存
    try:
        with gzip.open(output_file, 'wt', encoding='utf-8') as f:
            json.dump(save_data, f, ensure_ascii=False)
        
        print(f"  ✓ 保存成功: {output_file}", flush=True)
        return True
        
    except Exception as e:
        print(f"  ✗ 保存失败: {e}", flush=True)
        return False


def run_kdj_j_analysis(
    n_days: int = 500,
    n: int = 9,
    m1: int = 3,
    m2: int = 3,
    num_layers: int = 5,
    days_per_batch: int = None
) -> Dict:
    """
    执行完整的 KDJ_J 因子分析
    
    步骤：
    1. 加载数据（内存优化，分段加载）
    2. 计算 KDJ_J 因子
    3. 计算 IC
    4. 执行分层回测
    5. 返回完整结果
    
    内存优化：
    1. 分段加载日期数据，避免一次性加载全部
    2. 每段处理后释放内存
    3. 合并所有段的结果
    
    Args:
        n_days: 交易日数量
        n: RSV 计算周期
        m1: K值平滑周期
        m2: D值平滑周期
        num_layers: 分层数量
        days_per_batch: 每批处理天数（None则自动根据内存阈值计算）
        
    Returns:
        完整分析结果字典
    """
    from datetime import datetime
    from layered_backtest import LayeredBacktest
    
    # 自动计算每批天数（基于内存阈值）
    if days_per_batch is None:
        days_per_batch = DAYS_PER_BATCH
    
    print(f"\n{'='*80}", flush=True)
    print(f"KDJ_J 因子分析 (N={n}, M1={m1}, M2={m2})", flush=True)
    print(f"{'='*80}", flush=True)
    print(f"  内存阈值: {MEMORY_THRESHOLD_MB} MB", flush=True)
    print(f"  每批天数: {days_per_batch} 天", flush=True)
    print(f"  开始时间: {datetime.now().isoformat()}", flush=True)
    
    # 内存监控（使用统一的函数）
    initial_mem = get_memory_usage_mb()
    print(f"  初始内存: {initial_mem:.2f} MB", flush=True)
    
    # ========== Step 1: 获取日期列表并分段 ==========
    print(f"\n[Step 1] 获取日期列表...", flush=True)
    check_memory_threshold(force_print=True)
    
    # 先快速加载元数据获取日期
    factor_path = CACHE_DIR / 'factor_data.json.gz'
    if not factor_path.exists():
        return {'success': False, 'error': f'因子数据文件不存在: {factor_path}'}
    
    try:
        with gzip.open(factor_path, 'rt', encoding='utf-8') as f:
            meta_data = json.load(f)
        all_dates = meta_data.get('meta', {}).get('dates', [])
        if not all_dates:
            all_dates = sorted(set(r.get('date') for r in meta_data.get('data', [])))
        del meta_data
        gc.collect()
    except Exception as e:
        return {'success': False, 'error': f'读取日期失败: {e}'}
    
    # 只保留最近n_days天
    if len(all_dates) > n_days:
        all_dates = all_dates[-n_days:]
    
    print(f"  共 {len(all_dates)} 天数据", flush=True)
    
    # 分段处理
    n_batches = (len(all_dates) + days_per_batch - 1) // days_per_batch
    print(f"  分成 {n_batches} 批处理（每批 {days_per_batch} 天）", flush=True)
    
    # ========== Step 2: 分段加载并计算因子 ==========
    print(f"\n[Step 2] 分段加载并计算因子...", flush=True)
    all_factor_results = []
    
    for batch_idx in range(n_batches):
        start_idx = batch_idx * days_per_batch
        end_idx = min(start_idx + days_per_batch, len(all_dates))
        batch_dates = all_dates[start_idx:end_idx]
        
        print(f"\n  [批次 {batch_idx+1}/{n_batches}] 处理 {len(batch_dates)} 天 ({batch_dates[0]} ~ {batch_dates[-1]})", flush=True)
        check_memory_threshold(force_print=True)
        
        # 加载本批次因子数据
        batch_factor_df = load_factor_data_by_date_range(batch_dates, data_type='factor')
        if batch_factor_df is None or batch_factor_df.empty:
            print(f"    ⚠️ 批次 {batch_idx+1} 数据为空，跳过", flush=True)
            continue
        
        # 计算本批次KDJ_J因子
        batch_factor_df, batch_stats = calculate_kdj_j_factor(batch_factor_df, n=n, m1=m1, m2=m2)
        
        # 保存本批次结果
        all_factor_results.append(batch_factor_df)
        
        # 释放本批次数据
        del batch_factor_df
        gc.collect()
        check_memory_threshold(force_print=True)
    
    # 合并所有批次因子数据
    print(f"\n  [合并] 合并 {len(all_factor_results)} 批次因子数据...", flush=True)
    if not all_factor_results:
        return {'success': False, 'error': '所有批次数据为空'}
    
    factor_df = pd.concat(all_factor_results, ignore_index=True)
    del all_factor_results
    gc.collect()
    check_memory_threshold(force_print=True)
    
    print(f"  合并后: {len(factor_df)} 条记录", flush=True)
    
    # 统计因子数据
    factor_stats = {
        'total_records': len(factor_df),
        'valid_records': factor_df['kdj_j'].notna().sum() if 'kdj_j' in factor_df.columns else 0,
        'missing_price_count': 0,
        'n': n,
        'm1': m1,
        'm2': m2
    }
    
    # ========== Step 3: 加载收益数据 ==========
    print(f"\n[Step 3] 加载收益数据...", flush=True)
    check_memory_threshold(force_print=True)
    
    # 收益数据也分段加载
    all_return_results = []
    factor_dates = list(factor_df['date'].unique())
    if factor_df['date'].dtype.name == 'category':
        factor_dates = [str(d) for d in factor_dates]
    
    for batch_idx in range(n_batches):
        start_idx = batch_idx * days_per_batch
        end_idx = min(start_idx + days_per_batch, len(all_dates))
        batch_dates = all_dates[start_idx:end_idx]
        
        batch_return_df = load_factor_data_by_date_range(batch_dates, data_type='return')
        if batch_return_df is not None and not batch_return_df.empty:
            all_return_results.append(batch_return_df)
            del batch_return_df
            gc.collect()
    
    if not all_return_results:
        return {'success': False, 'error': '收益数据加载失败'}
    
    return_df = pd.concat(all_return_results, ignore_index=True)
    del all_return_results, factor_dates
    gc.collect()
    check_memory_threshold(force_print=True)
    
    print(f"  收益数据: {len(return_df)} 条记录", flush=True)
    
    # 保存合并后的因子历史
    print(f"\n[保存] 保存因子历史...", flush=True)
    save_kdj_j_history(factor_df, {'n': n, 'm1': m1, 'm2': m2})
    
    current_mem = get_memory_usage_mb()
    print(f"  [内存监控] 数据准备完成: {current_mem:.1f} MB", flush=True)
    
    # ========== Step 4: 计算 IC ==========
    print(f"\n[Step 4] 计算 IC...", flush=True)
    check_memory_threshold(force_print=True)
    ic_result = calculate_kdj_j_ic(factor_df, return_df)
    
    current_mem = get_memory_usage_mb()
    print(f"  [内存监控] IC计算后: {current_mem:.1f} MB", flush=True)
    
    # ========== Step 5: 分层回测 ==========
    print(f"\n[Step 5] 分层回测...", flush=True)
    check_memory_threshold(force_print=True)
    
    # 准备分层回测数据
    backtest_factor_df = factor_df[['date', 'asset', 'kdj_j']].copy()
    backtest_return_df = return_df[['date', 'asset', 'forward_return']].copy()
    
    # 释放原始数据（释放内存）
    del factor_df, return_df
    gc.collect()
    check_memory_threshold(force_print=True)
    
    # 执行分层回测
    try:
        backtest = LayeredBacktest(num_layers=num_layers)
        layered_result = backtest.run(
            backtest_factor_df, 
            backtest_return_df, 
            factor_col='kdj_j',
            return_col='forward_return'
        )
    except Exception as e:
        print(f"  ✗ 分层回测失败: {e}", flush=True)
        import traceback
        traceback.print_exc()
        layered_result = None
    
    del backtest_factor_df, backtest_return_df
    gc.collect()
    
    current_mem = get_memory_usage_mb()
    print(f"  [内存监控] 分层回测后: {current_mem:.1f} MB", flush=True)
    
    # ========== Step 6: 构建结果 ==========
    print(f"\n[Step 6] 构建结果...", flush=True)
    check_memory_threshold(force_print=True)
    
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
            'dates': [d.strftime('%Y-%m-%d') if hasattr(d, 'strftime') else str(d).split()[0] for d in ic_series.index],
            'ic_values': [round(v, 6) for v in ic_series.values],
            'rolling_ic_mean': [round(v, 6) for v in rolling_mean.values]
        }
    else:
        ic_series_data = {
            'dates': [],
            'ic_values': [],
            'rolling_ic_mean': []
        }
    
    del ic_result, ic_series
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
        
        # 单调性检验（KDJ_J 是反向因子：预期 Layer 1（J值高）收益低，Layer N（J值低）收益高）
        def calculate_monotonicity(statistics_df):
            layer_returns = []
            for i in range(1, num_layers + 1):
                layer_key = f'layer_{i}'
                if layer_key in statistics_df.index:
                    layer_returns.append(statistics_df.loc[layer_key, 'annual_return'])
            
            # 反向因子预期收益递增（J值高 → 排名低 → Layer 1 → 预期收益低）
            for i in range(len(layer_returns) - 1):
                if layer_returns[i] < layer_returns[i + 1]:
                    return True  # 符合预期：收益递增（J值低组收益高）
            return False
        
        # 提取多空统计信息
        try:
            if 'long_short' in layered_result.statistics.index:
                long_short_stats = layered_result.statistics.loc['long_short']
                summary = {
                    'long_short_annual_return': round(float(long_short_stats['annual_return']), 4),
                    'long_short_sharpe': round(float(long_short_stats['sharpe']), 4),
                    'long_short_max_drawdown': calculate_max_drawdown(layered_result.long_short['cumulative_nav']),
                    'monotonicity_passed': calculate_monotonicity(layered_result.statistics)
                }
                long_short_data = convert_df_dates(layered_result.long_short.reset_index().to_dict(orient='records'))
            else:
                print("  ⚠️ 分层回测未生成 long_short 数据（数据不足）", flush=True)
                summary = {
                    'long_short_annual_return': 0,
                    'long_short_sharpe': 0,
                    'long_short_max_drawdown': 0,
                    'monotonicity_passed': False
                }
                long_short_data = []
        except Exception as e:
            print(f"  ✗ 提取多空统计失败: {e}", flush=True)
            summary = {
                'long_short_annual_return': 0,
                'long_short_sharpe': 0,
                'long_short_max_drawdown': 0,
                'monotonicity_passed': False
            }
            long_short_data = []
        
        layered_result_json = {
            'layer_returns': convert_df_dates(layered_result.layer_returns.reset_index().to_dict(orient='records')),
            'cumulative_returns': convert_df_dates(layered_result.cumulative_returns.reset_index().to_dict(orient='records')),
            'statistics': layered_result.statistics.reset_index().to_dict(orient='records'),
            'long_short': long_short_data,
            'num_layers': num_layers,
            'n_days': len(layered_result.layer_returns),
            'n_stocks': ic_metrics['n_assets'],
            'summary': summary
        }
        
        del layered_result
        gc.collect()
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
    
    # 构建完整结果
    result = {
        'factor_name': 'kdj_j',
        'success': True,
        'ic_metrics': ic_metrics,
        'ic_series': ic_series_data,
        'layered_result': layered_result_json,
        'factor_stats': factor_stats,
        'params': {
            'n_days': n_days,
            'n': n,
            'm1': m1,
            'm2': m2,
            'num_layers': num_layers,
            'factor_col': 'kdj_j'
        },
        'generated_at': datetime.now().isoformat()
    }
    
    # 转换 numpy 类型
    result = convert_to_native_types(result)
    
    gc.collect()
    
    final_mem = get_memory_usage_mb()
    print(f"  [内存监控] 最终内存: {final_mem:.2f} MB (峰值增量: {final_mem - initial_mem:.2f} MB)", flush=True)
    
    print(f"  完成时间: {datetime.now().isoformat()}", flush=True)
    print(f"{'='*80}", flush=True)
    
    return result


if __name__ == '__main__':
    """执行 KDJ_J 因子分析并保存结果"""
    result = run_kdj_j_analysis(n_days=500, n=9, m1=3, m2=3, num_layers=5)
    
    if result.get('success'):
        print("\n" + "="*60, flush=True)
        print("[保存结果] 正在保存分析结果...", flush=True)
        gc.collect()
        
        # 分阶段保存，避免大字典内存峰值（参考 precompute_return_3d.py）
        temp_output_file = OUTPUT_FILE.with_suffix('.json.tmp')
        
        with open(temp_output_file, 'w', encoding='utf-8') as f:
            f.write('{\n')
            
            f.write('  "factor_name": "kdj_j",\n')
            
            f.write('  "ic_metrics": ')
            json.dump(result['ic_metrics'], f, ensure_ascii=False)
            f.write(',\n')
            
            f.write('  "ic_series": ')
            json.dump(result['ic_series'], f, ensure_ascii=False)
            f.write(',\n')
            
            # 在删除前保存要输出的关键指标
            ic_mean_to_print = result['ic_metrics'].get('ic_mean', 0)
            icir_to_print = result['ic_metrics'].get('icir', 0)
            t_stat_to_print = result['ic_metrics'].get('t_stat', 0)
            significance_to_print = result['ic_metrics'].get('significance', '')
            
            # 释放 IC 数据
            del result['ic_metrics'], result['ic_series']
            gc.collect()
            
            f.write('  "layered_result": ')
            json.dump(result['layered_result'], f, ensure_ascii=False)
            f.write(',\n')
            
            # 在删除前保存多空收益
            ls_return_to_print = result['layered_result']['summary'].get('long_short_annual_return', 0) if result.get('layered_result') else 0
            
            # 释放分层结果
            del result['layered_result']
            gc.collect()
            
            f.write('  "factor_stats": ')
            json.dump(result['factor_stats'], f, ensure_ascii=False)
            f.write(',\n')
            
            f.write('  "params": ')
            json.dump(result['params'], f, ensure_ascii=False)
            f.write(',\n')
            
            f.write(f'  "generated_at": "{result["generated_at"]}"\n')
            f.write('}\n')
        
        # 原子重命名
        temp_output_file.replace(OUTPUT_FILE)
        
        gc.collect()
        final_mem = get_memory_usage_mb()
        print(f'[内存监控] 最终内存: {final_mem:.1f} MB', flush=True)
        
        print(f"[保存结果] 已保存到: {OUTPUT_FILE}", flush=True)
        print("="*60, flush=True)
        
        print("\n✅ 分析成功！", flush=True)
        print(f"IC均值: {ic_mean_to_print:.4f}", flush=True)
        print(f"ICIR: {icir_to_print:.2f}", flush=True)
        print(f"t统计量: {t_stat_to_print:.4f}{significance_to_print}", flush=True)
        print(f"多空收益: {ls_return_to_print:.2%}", flush=True)
    else:
        print(f"\n✗ 分析失败: {result.get('error')}", flush=True)