#!/usr/bin/env python3
"""
RSI(6) 分层回测模块

核心功能:
- 每日按 RSI(6) 值分5层（每层20%股票）
- 第1层：RSI最高（最超买）→ 预期下跌 → 做空
- 第5层：RSI最低（最超卖）→ 预期反弹 → 做多
- 计算各层等权组合收益
- 多空组合 = Layer 5 - Layer 1（做多超卖反弹 + 做空超买回落）
- 计算统计指标：年化收益、t-stat、夏普比率等

分层逻辑说明（反向分层 - 适配动量效应）：
- A股存在动量效应：RSI高的股票倾向于继续上涨
- 反向分层让 Layer 1 = RSI最高，Layer 5 = RSI最低
- 多空策略：做多 Layer 5（超卖反弹）+ 做空 Layer 1（超买回落）
- 这样可以捕捉均值回归机会

动态过滤异常股票（2026-04-03 新增）：
- 在分层前动态过滤停牌、ST、涨停、跌停股票
- 使用交易状态缓存获取状态信息
- 确保因子数据完整性，支持多因子复用

作者: 云舟
日期: 2026-04-02
更新: 2026-04-03 - 添加动态过滤异常股票功能
"""

import pandas as pd
import numpy as np
from typing import Dict, Tuple, Optional, List
from dataclasses import dataclass
from scipy import stats
import warnings
import os
import json
import gzip
import gc
warnings.filterwarnings('ignore')


def winsorize_factor(
    factor_values: np.ndarray,
    lower_quantile: float = 0.025,
    upper_quantile: float = 0.975
) -> Tuple[np.ndarray, dict]:
    """
    分位数法去极值
    
    Args:
        factor_values: 每日所有股票的因子值数组
        lower_quantile: 下分位数（默认 2.5%）
        upper_quantile: 上分位数（默认 97.5%）
        
    Returns:
        (去极值后的因子值, 统计信息字典)
    """
    # 处理空数组或无效输入
    if len(factor_values) == 0:
        return factor_values, {
            'lower_bound': 0,
            'upper_bound': 0,
            'n_lower_truncated': 0,
            'n_upper_truncated': 0,
            'total_truncated': 0
        }
    
    # 过滤 NaN 值
    valid_values = factor_values[~np.isnan(factor_values)]
    
    if len(valid_values) == 0:
        return factor_values, {
            'lower_bound': 0,
            'upper_bound': 0,
            'n_lower_truncated': 0,
            'n_upper_truncated': 0,
            'total_truncated': 0
        }
    
    lower = np.quantile(valid_values, lower_quantile)
    upper = np.quantile(valid_values, upper_quantile)
    
    winsorized = np.clip(factor_values, lower, upper)
    
    # 统计被截断的股票数量
    n_lower = np.sum(factor_values < lower)
    n_upper = np.sum(factor_values > upper)
    
    stats = {
        'lower_bound': lower,
        'upper_bound': upper,
        'n_lower_truncated': n_lower,
        'n_upper_truncated': n_upper,
        'total_truncated': n_lower + n_upper
    }
    
    return winsorized, stats


# 缓存路径（与 real_data_loader.py 保持一致）
CACHE_DIR = os.path.expanduser('~/.openclaw/workspace/yunzhou/factor_ic_analyzer/cache')
FACTOR_CACHE_DIR = os.path.join(CACHE_DIR, 'factor_data')


def _get_status_cache_path() -> str:
    """获取交易状态缓存路径"""
    return os.path.join(FACTOR_CACHE_DIR, 'stock_status.json.gz')


def _get_stock_list_cache_path() -> str:
    """获取股票列表缓存路径"""
    return os.path.join(CACHE_DIR, 'stock_list.json')


def _load_cache_gzip(cache_path: str) -> Optional[dict]:
    """加载 gzip 压缩的缓存文件"""
    if not os.path.exists(cache_path):
        return None
    try:
        with gzip.open(cache_path, 'rt', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return None


def _load_stock_names() -> Dict[str, str]:
    """加载股票名称映射"""
    stock_list_cache_path = _get_stock_list_cache_path()
    if os.path.exists(stock_list_cache_path):
        try:
            with open(stock_list_cache_path, 'r', encoding='utf-8') as f:
                stock_cache = json.load(f)
            stocks_list = stock_cache.get('stocks', [])
            return {s['code']: s['name'] for s in stocks_list}
        except Exception:
            return {}
    return {}


def filter_abnormal_stocks(
    merged_df: pd.DataFrame,
    factor_col: str = 'rsi_6',
    return_col: str = 'forward_return',
    status_cache: Optional[dict] = None,
    code_to_name: Optional[Dict[str, str]] = None
) -> Tuple[pd.DataFrame, dict]:
    """
    动态过滤异常股票（用于分层回测）
    
    过滤条件：
    1. 当日停牌：成交量 = 0 或缺失
    2. 当日ST：股票名称含 "ST"
    3. 当日涨停：收盘价 >= 涨停价 × 0.998
    4. 当日跌停：收盘价 <= 跌停价 × 1.002
    
    Args:
        merged_df: 合并后的因子和收益数据
        factor_col: 因子列名
        return_col: 收益列名
        status_cache: 交易状态缓存（可选，自动加载）
        code_to_name: 股票名称映射（可选，自动加载）
        
    Returns:
        (filtered_df, filter_stats)
    """
    print(f"\n[动态过滤异常股票] 开始处理...")
    
    # 加载状态缓存
    if status_cache is None:
        status_cache_path = _get_status_cache_path()
        status_cache = _load_cache_gzip(status_cache_path)
    
    if status_cache is None:
        print(f"  ⚠ 交易状态缓存不存在，跳过动态过滤")
        return merged_df, {'total_removed': 0}
    
    # 加载股票名称映射
    if code_to_name is None:
        code_to_name = _load_stock_names()
    
    # 从状态缓存构建 DataFrame
    status_records = status_cache.get('data', [])
    if not status_records:
        print(f"  ⚠ 状态缓存数据为空，跳过动态过滤")
        return merged_df, {'total_removed': 0}
    
    status_df = pd.DataFrame(status_records)
    
    # 修复：统一 date 列类型，解决 category 与 datetime64 不匹配问题
    if merged_df['date'].dtype.name == 'category':
        merged_df['date'] = merged_df['date'].astype('datetime64[ns]')
    if status_df['date'].dtype.name == 'category':
        status_df['date'] = status_df['date'].astype('datetime64[ns]')
    
    # 合并状态信息
    merged_with_status = pd.merge(
        merged_df,
        status_df,
        on=['date', 'asset'],
        how='left'
    )
    
    # 过滤统计
    filter_stats = {
        'suspended': 0,
        'st_stocks': 0,
        'limit_up': 0,
        'limit_down': 0,
        'total_removed': 0
    }
    
    original_count = len(merged_with_status)
    
    # 1. 过滤停牌股票（成交量 = 0 或缺失）
    suspended_mask = (
        merged_with_status['volume'].isna() | 
        (merged_with_status['volume'] == 0)
    )
    filter_stats['suspended'] = suspended_mask.sum()
    merged_with_status = merged_with_status[~suspended_mask]
    
    # 2. 过滤 ST 股票
    if code_to_name:
        st_codes = set()
        for code in merged_with_status['asset'].unique():
            name = code_to_name.get(code, '')
            if 'ST' in name.upper():
                st_codes.add(code)
        if st_codes:
            st_mask = merged_with_status['asset'].isin(st_codes)
            filter_stats['st_stocks'] = st_mask.sum()
            merged_with_status = merged_with_status[~st_mask]
    
    # 3. 过滤涨停股票
    if 'limit_up_price' in merged_with_status.columns:
        limit_up_mask = (
            merged_with_status['close'] >= 
            merged_with_status['limit_up_price'] * 0.998
        )
        filter_stats['limit_up'] = limit_up_mask.sum()
        merged_with_status = merged_with_status[~limit_up_mask]
    
    # 4. 过滤跌停股票
    if 'limit_down_price' in merged_with_status.columns:
        limit_down_mask = (
            merged_with_status['close'] <= 
            merged_with_status['limit_down_price'] * 1.002
        )
        filter_stats['limit_down'] = limit_down_mask.sum()
        merged_with_status = merged_with_status[~limit_down_mask]
    
    filter_stats['total_removed'] = original_count - len(merged_with_status)
    
    # 输出过滤统计
    print(f"\n{'='*60}")
    print("【分层回测动态过滤统计】")
    print(f"{'='*60}")
    print(f"  原始记录数:     {original_count:,}")
    print(f"  过滤记录数:     {filter_stats['total_removed']:,}")
    print(f"  剩余记录数:     {len(merged_with_status):,}")
    print(f"  过滤比例:       {filter_stats['total_removed']/original_count*100:.2f}%")
    print(f"")
    print(f"  过滤明细:")
    print(f"    停牌股票:     {filter_stats['suspended']:,} 条")
    print(f"    ST股票:       {filter_stats['st_stocks']:,} 条")
    print(f"    涨停股票:     {filter_stats['limit_up']:,} 条")
    print(f"    跌停股票:     {filter_stats['limit_down']:,} 条")
    print(f"{'='*60}")
    
    # 只保留需要的列
    result_cols = ['date', 'asset', factor_col, return_col]
    filtered_df = merged_with_status[result_cols].copy()
    
    return filtered_df, filter_stats


@dataclass
class LayeredResult:
    """分层回测结果"""
    layer_returns: pd.DataFrame  # 各层每日收益
    cumulative_returns: pd.DataFrame  # 各层累计净值
    statistics: pd.DataFrame  # 统计指标
    long_short: pd.DataFrame  # 多空组合
    ic_series: Optional[pd.Series] = None  # IC时间序列（可选）
    filter_stats: Optional[dict] = None  # 过滤统计（新增）


class LayeredBacktest:
    """分层回测核心类"""
    
    def __init__(self, num_layers: int = 5, enable_filter: bool = True, enable_winsorize: bool = True):
        """
        初始化分层回测
        
        Args:
            num_layers: 分层数量（默认5层）
            enable_filter: 是否启用动态过滤异常股票（默认True）
            enable_winsorize: 是否启用去极值处理（默认True）
        """
        if num_layers < 2:
            raise ValueError("分层数量必须 >= 2")
        self.num_layers = num_layers
        self.enable_filter = enable_filter
        self.enable_winsorize = enable_winsorize
    
    def run(
        self,
        factor_df: pd.DataFrame,
        return_df: pd.DataFrame,
        factor_col: str = 'rsi_6',
        return_col: str = 'forward_return'
    ) -> LayeredResult:
        """
        执行分层回测（内存优化版本）
        
        内存优化策略：
        1. 按日期分批处理，不一次性 merge 全部数据
        2. 每批计算完后立即释放中间变量
        3. 使用 gc.collect() 强制回收内存
        
        Args:
            factor_df: 因子数据，列: ['date', 'asset', factor_col]
            return_df: 收益数据，列: ['date', 'asset', return_col]
            factor_col: 因子列名
            return_col: 收益列名
            
        Returns:
            LayeredResult: 分层回测结果
        """
        print(f"\n{'='*60}")
        print(f"开始分层回测分析（内存优化模式）")
        print(f"{'='*60}")
        print(f"  分层数量: {self.num_layers}")
        print(f"  因子列: {factor_col}")
        print(f"  动态过滤: {'启用' if self.enable_filter else '禁用'}")
        print(f"  去极值: {'启用' if self.enable_winsorize else '禁用'}")
        print(f"  收益列: {return_col}")
        
        # 预处理：只保留必要的列，减少内存占用
        factor_cols = ['date', 'asset', factor_col]
        return_cols = ['date', 'asset', return_col]
        
        factor_df_small = factor_df[factor_cols].copy()
        return_df_small = return_df[return_cols].copy()
        
        # 确保日期格式一致
        factor_df_small['date'] = pd.to_datetime(factor_df_small['date'])
        return_df_small['date'] = pd.to_datetime(return_df_small['date'])
        
        # 获取所有唯一日期（排序后）
        all_dates = sorted(factor_df_small['date'].unique())
        total_dates = len(all_dates)
        print(f"  总交易日数: {total_dates}")
        print(f"  因子数据量: {len(factor_df_small):,} 条")
        print(f"  收益数据量: {len(return_df_small):,} 条")
        
        # 加载交易状态缓存（用于动态过滤）
        status_cache = None
        code_to_name = None
        if self.enable_filter:
            print(f"\n[步骤] 加载交易状态缓存...")
            status_cache_path = _get_status_cache_path()
            status_cache = _load_cache_gzip(status_cache_path)
            code_to_name = _load_stock_names()
            if status_cache is None:
                print(f"  ⚠ 交易状态缓存不存在，跳过动态过滤")
                self.enable_filter = False
            else:
                print(f"  ✓ 交易状态缓存已加载")
        
        # 分批处理：按日期分批
        # 批次大小：每次处理多少天的数据
        batch_size = 20  # 每批处理20天
        results = []
        filter_stats_total = {
            'suspended': 0,
            'st_stocks': 0,
            'limit_up': 0,
            'limit_down': 0,
            'total_removed': 0
        }
        winsorize_stats_list = []
        
        print(f"\n[分批处理] 每批 {batch_size} 个交易日...")
        
        for batch_start in range(0, total_dates, batch_size):
            batch_end = min(batch_start + batch_size, total_dates)
            batch_dates = all_dates[batch_start:batch_end]
            
            # 筛选当前批次的因子数据
            batch_factor = factor_df_small[
                factor_df_small['date'].isin(batch_dates)
            ].copy()
            
            # 筛选当前批次的收益数据
            batch_return = return_df_small[
                return_df_small['date'].isin(batch_dates)
            ].copy()
            
            # 修复：统一 date 列类型，解决 category 与 datetime64 不匹配问题
            # 在 merge 前确保 date 列都是 datetime64[ns] 类型
            if batch_factor['date'].dtype.name == 'category':
                batch_factor['date'] = batch_factor['date'].astype('datetime64[ns]')
            if batch_return['date'].dtype.name == 'category':
                batch_return['date'] = batch_return['date'].astype('datetime64[ns]')
            
            # 合并当前批次
            batch_merged = pd.merge(
                batch_factor,
                batch_return,
                on=['date', 'asset'],
                how='inner'
            )
            
            # 立即释放批次因子和收益数据
            del batch_factor, batch_return
            gc.collect()
            
            if len(batch_merged) == 0:
                continue
            
            # 动态过滤异常股票
            if self.enable_filter and status_cache is not None:
                batch_merged, batch_filter_stats = self._filter_batch(
                    batch_merged, 
                    factor_col, 
                    return_col,
                    status_cache,
                    code_to_name
                )
                # 累加过滤统计
                for key in filter_stats_total:
                    filter_stats_total[key] += batch_filter_stats.get(key, 0)
            
            if len(batch_merged) == 0:
                del batch_merged
                gc.collect()
                continue
            
            # 去极值处理
            factor_col_for_layer = factor_col
            if self.enable_winsorize:
                batch_merged, batch_winsorize_stats = self._winsorize_batch(
                    batch_merged, 
                    factor_col
                )
                winsorize_stats_list.extend(batch_winsorize_stats)
                factor_col_for_layer = f'{factor_col}_winsorized'
            
            # 计算当前批次的分层收益
            batch_results = self._calculate_batch_layer_returns(
                batch_merged,
                factor_col_for_layer,
                return_col
            )
            results.extend(batch_results)
            
            # 立即释放当前批次数据
            del batch_merged, batch_results
            gc.collect()
            
            # 进度显示
            processed = batch_end
            if processed % 100 == 0 or processed == total_dates:
                print(f"  进度: {processed}/{total_dates} ({processed/total_dates*100:.1f}%)")
        
        # 释放预处理的缓存数据
        del factor_df_small, return_df_small
        if self.enable_filter:
            del status_cache, code_to_name
        gc.collect()
        
        # 输出过滤统计
        if self.enable_filter and filter_stats_total['total_removed'] > 0:
            print(f"\n{'='*60}")
            print("【分层回测动态过滤统计】")
            print(f"{'='*60}")
            print(f"  过滤记录数:     {filter_stats_total['total_removed']:,}")
            print(f"  过滤明细:")
            print(f"    停牌股票:     {filter_stats_total['suspended']:,} 条")
            print(f"    ST股票:       {filter_stats_total['st_stocks']:,} 条")
            print(f"    涨停股票:     {filter_stats_total['limit_up']:,} 条")
            print(f"    跌停股票:     {filter_stats_total['limit_down']:,} 条")
            print(f"{'='*60}")
        
        # 输出去极值统计
        if self.enable_winsorize and winsorize_stats_list:
            winsorize_stats_df = pd.DataFrame(winsorize_stats_list)
            total_truncated = winsorize_stats_df['total_truncated'].sum()
            avg_truncated = winsorize_stats_df['total_truncated'].mean()
            print(f"\n{'='*60}")
            print("【去极值统计信息】")
            print(f"{'='*60}")
            print(f"  总截断股票数: {total_truncated:,}")
            print(f"  日均截断股票数: {avg_truncated:.1f}")
            if len(winsorize_stats_df) > 0 and winsorize_stats_df['n_stocks'].mean() > 0:
                print(f"  日均截断比例: {avg_truncated / winsorize_stats_df['n_stocks'].mean() * 100:.2f}%")
            print(f"{'='*60}")
        
        # 汇总结果
        if not results:
            print("  ! 无有效数据，无法执行分层回测")
            return LayeredResult(
                layer_returns=pd.DataFrame(),
                cumulative_returns=pd.DataFrame(),
                statistics=pd.DataFrame(),
                long_short=pd.DataFrame(),
                filter_stats=filter_stats_total
            )
        
        # 转换为 DataFrame
        layer_returns = pd.DataFrame(results)
        layer_returns['date'] = pd.to_datetime(layer_returns['date'])
        layer_returns = layer_returns.set_index('date').sort_index()
        
        print(f"  计算完成，共 {len(layer_returns)} 个交易日")
        
        # 释放 results 列表
        del results
        gc.collect()
        
        # 计算累计净值
        cumulative_returns = self.calculate_cumulative_returns(layer_returns)
        
        # 计算多空组合
        long_short = self.calculate_long_short(layer_returns)
        
        # 计算统计指标
        statistics = self.calculate_statistics(layer_returns, long_short)
        
        # 打印统计摘要
        self._print_statistics_summary(statistics)
        
        return LayeredResult(
            layer_returns=layer_returns,
            cumulative_returns=cumulative_returns,
            statistics=statistics,
            long_short=long_short,
            filter_stats=filter_stats_total
        )
    
    def _filter_batch(
        self,
        batch_merged: pd.DataFrame,
        factor_col: str,
        return_col: str,
        status_cache: dict,
        code_to_name: Dict[str, str]
    ) -> Tuple[pd.DataFrame, dict]:
        """
        对单个批次进行动态过滤
        
        Args:
            batch_merged: 当前批次合并数据
            factor_col: 因子列名
            return_col: 收益列名
            status_cache: 交易状态缓存
            code_to_name: 股票名称映射
            
        Returns:
            (filtered_df, filter_stats)
        """
        # 从状态缓存构建 DataFrame
        status_records = status_cache.get('data', [])
        if not status_records:
            return batch_merged, {'total_removed': 0}
        
        status_df = pd.DataFrame(status_records)
        
        # 确保日期格式一致
        if 'date' in status_df.columns:
            status_df['date'] = pd.to_datetime(status_df['date'])
        
        # 修复：统一 date 列类型，解决 category 与 datetime64 不匹配问题
        if batch_merged['date'].dtype.name == 'category':
            batch_merged['date'] = batch_merged['date'].astype('datetime64[ns]')
        
        # 只筛选当前批次的日期
        batch_dates = batch_merged['date'].unique()
        status_df_batch = status_df[status_df['date'].isin(batch_dates)].copy()
        
        # 释放完整状态数据
        del status_df
        gc.collect()
        
        if len(status_df_batch) == 0:
            return batch_merged, {'total_removed': 0}
        
        # 合并状态信息
        merged_with_status = pd.merge(
            batch_merged,
            status_df_batch,
            on=['date', 'asset'],
            how='left'
        )
        
        # 立即释放
        del status_df_batch
        gc.collect()
        
        filter_stats = {
            'suspended': 0,
            'st_stocks': 0,
            'limit_up': 0,
            'limit_down': 0,
            'total_removed': 0
        }
        
        original_count = len(merged_with_status)
        
        # 1. 过滤停牌股票（成交量 = 0 或缺失）
        suspended_mask = (
            merged_with_status['volume'].isna() | 
            (merged_with_status['volume'] == 0)
        )
        filter_stats['suspended'] = suspended_mask.sum()
        merged_with_status = merged_with_status[~suspended_mask]
        
        # 2. 过滤 ST 股票
        if code_to_name:
            st_codes = set()
            for code in merged_with_status['asset'].unique():
                name = code_to_name.get(code, '')
                if 'ST' in name.upper():
                    st_codes.add(code)
            if st_codes:
                st_mask = merged_with_status['asset'].isin(st_codes)
                filter_stats['st_stocks'] = st_mask.sum()
                merged_with_status = merged_with_status[~st_mask]
        
        # 3. 过滤涨停股票
        if 'limit_up_price' in merged_with_status.columns:
            limit_up_mask = (
                merged_with_status['close'] >= 
                merged_with_status['limit_up_price'] * 0.998
            )
            filter_stats['limit_up'] = limit_up_mask.sum()
            merged_with_status = merged_with_status[~limit_up_mask]
        
        # 4. 过滤跌停股票
        if 'limit_down_price' in merged_with_status.columns:
            limit_down_mask = (
                merged_with_status['close'] <= 
                merged_with_status['limit_down_price'] * 1.002
            )
            filter_stats['limit_down'] = limit_down_mask.sum()
            merged_with_status = merged_with_status[~limit_down_mask]
        
        filter_stats['total_removed'] = original_count - len(merged_with_status)
        
        # 只保留需要的列
        result_cols = ['date', 'asset', factor_col, return_col]
        filtered_df = merged_with_status[result_cols].copy()
        
        # 释放
        del merged_with_status
        gc.collect()
        
        return filtered_df, filter_stats
    
    def _winsorize_batch(
        self,
        batch_merged: pd.DataFrame,
        factor_col: str
    ) -> Tuple[pd.DataFrame, List[dict]]:
        """
        对单个批次进行去极值处理
        
        Args:
            batch_merged: 当前批次合并数据
            factor_col: 因子列名
            
        Returns:
            (processed_df, winsorize_stats_list)
        """
        # 确保 factor_col 是数值类型
        if batch_merged[factor_col].dtype.name == 'category':
            batch_merged[factor_col] = batch_merged[factor_col].astype(float)
        
        # 对每一天的因子值独立进行去极值
        winsorize_stats_list = []
        
        # 按日期分组处理
        for date, group in batch_merged.groupby('date'):
            original_values = np.asarray(group[factor_col], dtype=float)
            winsorized_values, stats = winsorize_factor(original_values)
            stats['date'] = date
            stats['n_stocks'] = len(group)
            winsorize_stats_list.append(stats)
            
            # 更新去极值后的值
            batch_merged.loc[group.index, f'{factor_col}_winsorized'] = winsorized_values
        
        return batch_merged, winsorize_stats_list
    
    def _calculate_batch_layer_returns(
        self,
        batch_merged: pd.DataFrame,
        factor_col: str,
        return_col: str
    ) -> List[dict]:
        """
        计算单个批次的分层收益
        
        Args:
            batch_merged: 当前批次合并数据
            factor_col: 因子列名
            return_col: 收益列名
            
        Returns:
            分层收益结果列表
        """
        results = []
        
        # 确保 factor_col 是数值类型
        if batch_merged[factor_col].dtype.name == 'category':
            batch_merged[factor_col] = batch_merged[factor_col].astype(float)
        
        # 按日期分组
        for date, group in batch_merged.groupby('date'):
            if len(group) < self.num_layers * 5:
                continue
            
            # 获取因子值（去除缺失值）
            valid_data = group.dropna(subset=[factor_col, return_col])
            
            if len(valid_data) < self.num_layers * 3:
                continue
            
            # 分层
            layer_labels = self.get_layer_assignment(valid_data[factor_col])
            
            if layer_labels.isna().all():
                continue
            
            # 将分层结果加入数据
            valid_data = valid_data.copy()
            valid_data['layer'] = layer_labels
            
            # 计算各层等权平均收益
            layer_returns = {}
            for layer_num in range(1, self.num_layers + 1):
                layer_data = valid_data[valid_data['layer'] == layer_num]
                if len(layer_data) > 0:
                    layer_returns[f'layer_{layer_num}'] = layer_data[return_col].mean()
                else:
                    layer_returns[f'layer_{layer_num}'] = 0.0
            
            layer_returns['date'] = date
            results.append(layer_returns)
        
        return results
    
    def get_layer_assignment(self, daily_factors: pd.Series) -> pd.Series:
        """
        获取分层结果
        
        分层规则（反向分层 - 针对动量效应优化）:
        - 第1层: RSI 值最高的 20% 股票 (最超买) → 预期下跌
        - 第2层: RSI 值次高的 20% 股票
        - 第3层: RSI 值中等的 20% 股票
        - 第4层: RSI 值次低的 20% 股票
        - 第5层: RSI 值最低的 20% 股票 (最超卖) → 预期反弹
        
        多空组合: Layer 5 - Layer 1 (做多超卖反弹，做空超买回落)
        
        Args:
            daily_factors: 单日的因子值序列
            
        Returns:
            分层标签 (1-num_layers)
        """
        # 使用 qcut 进行等频分层
        # labels=False 返回分位数索引（0到num_layers-1）
        # duplicates='drop' 处理重复值
        try:
            layer_indices = pd.qcut(
                daily_factors, 
                q=self.num_layers, 
                labels=False, 
                duplicates='drop'
            )
            # 反向分层：RSI高 → Layer 1，RSI低 → Layer N
            # 这样多空策略 (Layer N - Layer 1) 做多超卖反弹
            return self.num_layers - layer_indices
        except ValueError:
            # 如果无法分层（如所有值相同），返回 None
            return pd.Series(index=daily_factors.index, dtype=float)
    
    def calculate_layer_returns(
        self,
        merged_df: pd.DataFrame,
        factor_col: str,
        return_col: str
    ) -> pd.DataFrame:
        """
        计算各层每日等权平均收益
        
        步骤:
        1. 按日期分组
        2. 对每个交易日:
           a. 获取当日所有股票的 RSI(6) 值
           b. 使用 qcut 分为5层
           c. 计算各层等权平均收益
        
        Args:
            merged_df: 合并后的数据，包含 date, asset, factor_col, return_col
            factor_col: 因子列名
            return_col: 收益列名
            
        Returns:
            DataFrame, 索引为 date, 列为 layer_1 ~ layer_{num_layers}
        """
        results = []
        
        # 确保 factor_col 是数值类型（category 类型需要转换）
        if merged_df[factor_col].dtype.name == 'category':
            merged_df[factor_col] = merged_df[factor_col].astype(float)
        
        # 按日期分组（使用 date 列，不依赖索引）
        # 注意：如果 date 是 category 类型，groupby 可能会失败
        date_col_for_groupby = 'date'
        if merged_df[date_col_for_groupby].dtype.name == 'category':
            # category 类型可以用于 groupby，但需要确保正确
            merged_df[date_col_for_groupby] = merged_df[date_col_for_groupby].astype(str)
        
        grouped = merged_df.groupby(date_col_for_groupby)
        total_dates = len(grouped)
        
        print(f"\n[分层计算] 处理 {total_dates} 个交易日...")
        
        for i, (date, group) in enumerate(grouped, 1):
            if len(group) < self.num_layers * 5:
                # 股票数量太少，跳过
                continue
            
            # 获取因子值（去除缺失值）
            valid_data = group.dropna(subset=[factor_col, return_col])
            
            if len(valid_data) < self.num_layers * 3:
                continue
            
            # 分层
            layer_labels = self.get_layer_assignment(valid_data[factor_col])
            
            if layer_labels.isna().all():
                continue
            
            # 将分层结果加入数据
            valid_data = valid_data.copy()
            valid_data['layer'] = layer_labels
            
            # 计算各层等权平均收益
            layer_returns = {}
            for layer_num in range(1, self.num_layers + 1):
                layer_data = valid_data[valid_data['layer'] == layer_num]
                if len(layer_data) > 0:
                    layer_returns[f'layer_{layer_num}'] = layer_data[return_col].mean()
                else:
                    layer_returns[f'layer_{layer_num}'] = 0.0
            
            layer_returns['date'] = date
            results.append(layer_returns)
            
            # 进度显示
            if i % 50 == 0 or i == total_dates:
                print(f"  进度: {i}/{total_dates} ({i/total_dates*100:.1f}%)")
        
        # 转换为 DataFrame
        df = pd.DataFrame(results)
        df['date'] = pd.to_datetime(df['date'])
        df = df.set_index('date').sort_index()
        
        return df
    
    def calculate_cumulative_returns(
        self, 
        layer_returns: pd.DataFrame
    ) -> pd.DataFrame:
        """
        计算各层累计净值
        
        公式:
            cumulative_nav[t] = cumulative_nav[t-1] * (1 + return[t])
            初始净值 = 1.0
        
        Args:
            layer_returns: 各层每日收益
            
        Returns:
            DataFrame, 索引为 date, 列为 layer_1 ~ layer_{num_layers}
        """
        # 累计净值 = (1 + r1) * (1 + r2) * ... * (1 + rn)
        cumulative_nav = (1 + layer_returns).cumprod()
        
        return cumulative_nav
    
    def calculate_long_short(
        self, 
        layer_returns: pd.DataFrame
    ) -> pd.DataFrame:
        """
        计算多空组合收益和净值
        
        多空组合 = Layer {num_layers} (最超卖) - Layer 1 (最超买)
        做多超卖反弹股 + 做空超买回落股
        
        Args:
            layer_returns: 各层每日收益
            
        Returns:
            DataFrame, 列: daily_return, cumulative_nav
        """
        # Layer N (超卖反弹) - Layer 1 (超买回落)
        daily_return = layer_returns[f'layer_{self.num_layers}'] - layer_returns['layer_1']
        
        # 累计净值
        cumulative_nav = (1 + daily_return).cumprod()
        
        return pd.DataFrame({
            'daily_return': daily_return,
            'cumulative_nav': cumulative_nav
        })
    
    def calculate_annual_return(
        self, 
        daily_returns: pd.Series, 
        trading_days: int = 250
    ) -> float:
        """
        计算年化收益率
        
        公式:
            annual_return = prod(1 + r)^(250/n) - 1
        
        Args:
            daily_returns: 日收益率序列
            trading_days: 年交易日数（默认250）
            
        Returns:
            年化收益率
        """
        # 计算累计收益
        cumulative_return = (1 + daily_returns).prod() - 1
        
        # 年化
        n_days = len(daily_returns)
        if n_days == 0:
            return 0.0
        
        annual_return = (1 + cumulative_return) ** (trading_days / n_days) - 1
        
        return annual_return
    
    def calculate_t_stat(
        self, 
        daily_returns: pd.Series
    ) -> Tuple[float, float]:
        """
        计算t统计量和p值
        
        假设检验:
            H0: 平均收益 = 0
            H1: 平均收益 ≠ 0
        
        公式:
            t = mean(r) / (std(r) / sqrt(n))
        
        Args:
            daily_returns: 日收益率序列
            
        Returns:
            (t_stat, p_value)
        """
        n = len(daily_returns)
        if n < 2:
            return (0.0, 1.0)
        
        mean_return = daily_returns.mean()
        std_return = daily_returns.std(ddof=1)
        
        if std_return == 0 or np.isnan(std_return):
            return (0.0, 1.0)
        
        t_stat = mean_return / (std_return / np.sqrt(n))
        
        # 双尾检验 p 值
        p_value = 2 * (1 - stats.t.cdf(abs(t_stat), df=n-1))
        
        return (t_stat, p_value)
    
    def calculate_sharpe_ratio(
        self, 
        daily_returns: pd.Series, 
        trading_days: int = 250
    ) -> float:
        """
        计算夏普比率
        
        公式:
            Sharpe = R_annual / σ_annual
            其中 σ_annual = σ_daily * √250
        
        Args:
            daily_returns: 日收益率序列
            trading_days: 年交易日数（默认250）
            
        Returns:
            夏普比率
        """
        # 年化收益
        annual_return = self.calculate_annual_return(daily_returns, trading_days)
        
        # 年化标准差
        daily_std = daily_returns.std(ddof=1)
        annual_std = daily_std * np.sqrt(trading_days)
        
        if annual_std == 0 or np.isnan(annual_std):
            return 0.0
        
        sharpe = annual_return / annual_std
        
        return sharpe
    
    def calculate_statistics(
        self,
        layer_returns: pd.DataFrame,
        long_short: pd.DataFrame
    ) -> pd.DataFrame:
        """
        计算各层及多空组合的统计指标
        
        指标:
            - annual_return: 年化收益率
            - t_stat: t统计量
            - p_value: p值
            - std: 日收益标准差
            - sharpe: 夏普比率
        
        Args:
            layer_returns: 各层每日收益
            long_short: 多空组合收益
            
        Returns:
            DataFrame, 索引为 layer_1 ~ layer_{num_layers}, long_short
        """
        stats_data = []
        
        # 各层统计
        for layer_num in range(1, self.num_layers + 1):
            layer_name = f'layer_{layer_num}'
            daily_returns = layer_returns[layer_name]
            
            annual_return = self.calculate_annual_return(daily_returns)
            t_stat, p_value = self.calculate_t_stat(daily_returns)
            std = daily_returns.std(ddof=1)
            sharpe = self.calculate_sharpe_ratio(daily_returns)
            
            stats_data.append({
                'layer': layer_name,
                'annual_return': annual_return,
                't_stat': t_stat,
                'p_value': p_value,
                'std': std,
                'sharpe': sharpe
            })
        
        # 多空组合统计
        ls_returns = long_short['daily_return']
        annual_return = self.calculate_annual_return(ls_returns)
        t_stat, p_value = self.calculate_t_stat(ls_returns)
        std = ls_returns.std(ddof=1)
        sharpe = self.calculate_sharpe_ratio(ls_returns)
        
        stats_data.append({
            'layer': 'long_short',
            'annual_return': annual_return,
            't_stat': t_stat,
            'p_value': p_value,
            'std': std,
            'sharpe': sharpe
        })
        
        return pd.DataFrame(stats_data).set_index('layer')
    
    def _print_statistics_summary(self, statistics: pd.DataFrame) -> None:
        """打印统计摘要"""
        print(f"\n{'='*80}")
        print("分层回测统计结果")
        print(f"{'='*80}")
        print(f"{'分层':<18} {'年化收益':<12} {'t统计量':<12} {'p值':<12} {'标准差':<12} {'夏普比率':<12}")
        print("-" * 80)
        
        for layer, row in statistics.iterrows():
            layer_name = {
                'layer_1': 'Layer 1 (最超买)',
                'layer_2': 'Layer 2',
                'layer_3': 'Layer 3',
                'layer_4': 'Layer 4',
                'layer_5': 'Layer 5 (最超卖)',
                'layer_6': 'Layer 6',
                'layer_7': 'Layer 7',
                'layer_8': 'Layer 8',
                'layer_9': 'Layer 9',
                'layer_10': 'Layer 10 (最超卖)',
                'long_short': '多空组合'
            }.get(layer, layer)
            
            ann_ret = f"{row['annual_return']*100:.2f}%"
            t_stat = f"{row['t_stat']:.4f}"
            p_val = f"{row['p_value']:.4f}"
            std = f"{row['std']*100:.4f}%"
            sharpe = f"{row['sharpe']:.4f}"
            
            print(f"{layer_name:<18} {ann_ret:<12} {t_stat:<12} {p_val:<12} {std:<12} {sharpe:<12}")
        
        print("=" * 80)
        
        # 检查单调性
        layer_annual_returns = []
        for i in range(1, self.num_layers + 1):
            layer_annual_returns.append(statistics.loc[f'layer_{i}', 'annual_return'])
        
        # 检查是否单调递增（Layer 1 最低，Layer N 最高）
        is_monotonic = all(layer_annual_returns[i] <= layer_annual_returns[i+1] 
                          for i in range(len(layer_annual_returns)-1))
        
        if is_monotonic:
            print("✓ 单调性检验: 通过（收益从 Layer 1 到 Layer N 递增）")
        else:
            print("✗ 单调性检验: 未通过（收益存在波动）")
        
        # 检查多空收益是否为正
        ls_return = statistics.loc['long_short', 'annual_return']
        if ls_return > 0:
            print(f"✓ 多空收益: {ls_return*100:.2f}% > 0，因子有效性验证通过")
        else:
            print(f"✗ 多空收益: {ls_return*100:.2f}% <= 0，因子有效性存疑")
        
        print("=" * 80)


def run_layered_backtest(
    factor_df: pd.DataFrame,
    return_df: pd.DataFrame,
    num_layers: int = 5,
    factor_col: str = 'rsi_6',
    return_col: str = 'forward_return',
    enable_filter: bool = True,
    enable_winsorize: bool = True
) -> LayeredResult:
    """
    执行分层回测（便捷函数）
    
    Args:
        factor_df: 因子数据
        return_df: 收益数据
        num_layers: 分层数量
        factor_col: 因子列名
        return_col: 收益列名
        enable_filter: 是否启用动态过滤异常股票（默认True）
        enable_winsorize: 是否启用去极值处理（默认True）
        
    Returns:
        LayeredResult: 分层回测结果
    """
    backtest = LayeredBacktest(
        num_layers=num_layers, 
        enable_filter=enable_filter,
        enable_winsorize=enable_winsorize
    )
    return backtest.run(factor_df, return_df, factor_col, return_col)


if __name__ == '__main__':
    """
    分层回测模块测试（使用真实数据）
    
    数据来源：新浪财经API
    股票范围：A股主板（沪市60开头、深市00开头）
    剔除：创业板(30)、科创板(688)、北交所、ST股票
    """
    print("="*60)
    print("分层回测模块测试 - 使用真实数据")
    print("="*60)
    
    # 导入真实数据加载器
    from real_data_loader import RealDataLoader
    
    # 创建数据加载器（使用真实数据，禁用模拟数据）
    loader = RealDataLoader(
        use_mock=False,      # 禁用模拟数据
        use_local=False,     # 使用API获取
        enable_cache=True    # 启用缓存
    )
    
    # 加载真实数据
    print("\n正在从新浪财经API获取真实数据...")
    print("预计耗时：5-15分钟（取决于网络状况）")
    
    factor_df, return_df = loader.load_data(
        n_days=250,          # 获取250个交易日数据
        max_stocks=0,        # 0表示获取全部主板股票（约3000+只）
        enable_complement=True
    )
    
    # 运行分层回测
    print("\n开始执行分层回测...")
    result = run_layered_backtest(
        factor_df, 
        return_df, 
        num_layers=5,
        factor_col='rsi_6',
        return_col='forward_return'
    )
    
    print("\n" + "="*60)
    print("测试完成！")
    print("="*60)
    print(f"各层收益数据: {result.layer_returns.shape}")
    print(f"累计净值数据: {result.cumulative_returns.shape}")
    print(f"统计指标数据: {result.statistics.shape}")
    print(f"多空组合数据: {result.long_short.shape}")
    
    # 输出关键指标
    print("\n" + "="*60)
    print("关键指标摘要")
    print("="*60)
    print(f"Layer 1 (最超买) 年化收益: {result.statistics.loc['layer_1', 'annual_return']*100:.2f}%")
    print(f"Layer 5 (最超卖) 年化收益: {result.statistics.loc['layer_5', 'annual_return']*100:.2f}%")
    print(f"多空组合年化收益: {result.statistics.loc['long_short', 'annual_return']*100:.2f}%")
    print(f"多空组合夏普比率: {result.statistics.loc['long_short', 'sharpe']:.4f}")