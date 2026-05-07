#!/usr/bin/env python3
"""
RSI(6) 分层回测模块 - 性能优化版

核心优化：
1. 向量化分层：使用 groupby + rank 替代逐日期循环
2. 向量化收益计算：使用 groupby + mean 替代逐层循环
3. 减少内存拷贝：避免不必要的 copy 操作
4. 详细进度日志：帮助定位性能瓶颈
5. 动态过滤异常股票：在分层前过滤停牌、ST、涨停、跌停

作者: 云舟
日期: 2026-04-02
更新: 2026-04-03 - 添加动态过滤异常股票功能
"""

import pandas as pd
import numpy as np
from typing import Dict, Tuple, Optional
from dataclasses import dataclass
from scipy import stats
import warnings
import time
import os
import json
import gzip
warnings.filterwarnings('ignore')


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
    lower = np.quantile(factor_values, lower_quantile)
    upper = np.quantile(factor_values, upper_quantile)
    
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
    """分层回测核心类 - 性能优化版"""
    
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
        执行分层回测
        
        Args:
            factor_df: 因子数据，列: ['date', 'asset', factor_col]
            return_df: 收益数据，列: ['date', 'asset', return_col]
            factor_col: 因子列名
            return_col: 收益列名
            
        Returns:
            LayeredResult: 分层回测结果
        """
        start_time = time.time()
        
        print(f"\n{'='*60}")
        print(f"开始分层回测分析（性能优化版）")
        print(f"{'='*60}")
        print(f"  分层数量: {self.num_layers}")
        print(f"  因子列: {factor_col}")
        print(f"  收益列: {return_col}")
        print(f"  动态过滤: {'启用' if self.enable_filter else '禁用'}")
        print(f"  去极值: {'启用' if self.enable_winsorize else '禁用'}")
        
        # 合并因子和收益数据
        print(f"\n[步骤1] 合并因子和收益数据...")
        merged = pd.merge(
            factor_df, 
            return_df, 
            on=['date', 'asset'], 
            how='inner'
        )
        print(f"  合并后数据量: {len(merged)} 条")
        print(f"  唯一日期数: {merged['date'].nunique()}")
        print(f"  唯一股票数: {merged['asset'].nunique()}")
        
        # 动态过滤异常股票
        filter_stats = None
        if self.enable_filter:
            print(f"\n[步骤2] 动态过滤异常股票...")
            merged, filter_stats = filter_abnormal_stocks(
                merged, factor_col, return_col
            )
            print(f"  过滤后数据量: {len(merged)} 条")
            
            if len(merged) == 0:
                print("  ! 过滤后数据为空，无法执行分层回测")
                return LayeredResult(
                    layer_returns=pd.DataFrame(),
                    cumulative_returns=pd.DataFrame(),
                    statistics=pd.DataFrame(),
                    long_short=pd.DataFrame(),
                    filter_stats=filter_stats
                )
        
        # 去极值处理（逐日进行）
        winsorize_stats = None
        step_num = 3 if self.enable_filter else 2
        
        if self.enable_winsorize:
            print(f"\n[步骤{step_num}] 对每日因子值进行去极值处理...")
            
            # 对每一天的因子值独立进行去极值（向量化操作）
            merged[f'{factor_col}_winsorized'] = merged.groupby('date')[factor_col].transform(
                lambda x: winsorize_factor(x.values)[0]
            )
            
            # 统计去极值信息
            winsorize_stats_list = []
            for date, group in merged.groupby('date'):
                original_values = group[factor_col].values
                _, stats = winsorize_factor(original_values)
                stats['date'] = date
                stats['n_stocks'] = len(group)
                winsorize_stats_list.append(stats)
            
            winsorize_stats_df = pd.DataFrame(winsorize_stats_list)
            
            # 输出去极值统计信息
            total_truncated = winsorize_stats_df['total_truncated'].sum()
            avg_truncated = winsorize_stats_df['total_truncated'].mean()
            print(f"\n{'='*60}")
            print("【去极值统计信息】")
            print(f"{'='*60}")
            print(f"  总截断股票数: {total_truncated:,}")
            print(f"  日均截断股票数: {avg_truncated:.1f}")
            print(f"  日均截断比例: {avg_truncated / winsorize_stats_df['n_stocks'].mean() * 100:.2f}%")
            print(f"  因子下界范围: [{winsorize_stats_df['lower_bound'].min():.2f}, {winsorize_stats_df['lower_bound'].max():.2f}]")
            print(f"  因子上界范围: [{winsorize_stats_df['upper_bound'].min():.2f}, {winsorize_stats_df['upper_bound'].max():.2f}]")
            print(f"{'='*60}")
            
            winsorize_stats = winsorize_stats_df
            
            # 使用去极值后的因子值进行分层
            factor_col_for_layer = f'{factor_col}_winsorized'
        else:
            factor_col_for_layer = factor_col
        
        # 计算各层每日收益（优化版）
        layer_step_num = step_num + 1 if self.enable_winsorize else step_num
        print(f"\n[步骤{layer_step_num}] 计算各层收益（向量化）...")
        layer_returns = self.calculate_layer_returns_vectorized(
            merged, 
            factor_col_for_layer, 
            return_col
        )
        
        print(f"  分层计算完成，共 {len(layer_returns)} 个交易日")
        
        # 计算累计净值
        cum_step_num = layer_step_num + 1
        print(f"\n[步骤{cum_step_num}] 计算累计净值...")
        cumulative_returns = self.calculate_cumulative_returns(layer_returns)
        
        # 计算多空组合
        ls_step_num = cum_step_num + 1
        print(f"[步骤{ls_step_num}] 计算多空组合...")
        long_short = self.calculate_long_short(layer_returns)
        
        # 计算统计指标
        stats_step_num = ls_step_num + 1
        print(f"[步骤{stats_step_num}] 计算统计指标...")
        statistics = self.calculate_statistics(layer_returns, long_short)
        
        # 打印统计摘要
        self._print_statistics_summary(statistics)
        
        elapsed = time.time() - start_time
        print(f"\n⏱️ 总耗时: {elapsed:.2f} 秒")
        
        return LayeredResult(
            layer_returns=layer_returns,
            cumulative_returns=cumulative_returns,
            statistics=statistics,
            long_short=long_short,
            filter_stats=filter_stats
        )
    
    def calculate_layer_returns_vectorized(
        self,
        merged_df: pd.DataFrame,
        factor_col: str,
        return_col: str
    ) -> pd.DataFrame:
        """
        向量化计算各层每日收益（性能优化版）
        
        优化策略:
        1. 使用 rank + 整除 进行全局分层，避免逐日期循环
        2. 使用 groupby + mean 进行向量化收益计算
        3. 减少内存拷贝
        
        Args:
            merged_df: 合并后的数据
            factor_col: 因子列名
            return_col: 收益列名
            
        Returns:
            DataFrame, 索引为 date, 列为 layer_1 ~ layer_{num_layers}
        """
        print(f"\n[步骤2] 计算各层收益（向量化）...")
        step_start = time.time()
        
        # 去除缺失值
        valid_mask = merged_df[factor_col].notna() & merged_df[return_col].notna()
        df = merged_df[valid_mask].copy()
        print(f"  有效数据: {len(df)} 条")
        
        # 按日期分组，计算每只股票的因子排名百分比
        print(f"  计算因子排名...")
        df['factor_rank'] = df.groupby('date')[factor_col].rank(pct=True, method='average')
        
        # 根据排名百分比分配层级
        # Layer 1 = RSI 最高（排名百分位 0.8-1.0）→ 最超买
        # Layer N = RSI 最低（排名百分位 0-0.2）→ 最超卖
        df['layer'] = np.ceil(df['factor_rank'] * self.num_layers)
        df['layer'] = df['layer'].clip(1, self.num_layers).astype(int)
        
        # 反转层级：让 Layer 1 = RSI最高，Layer N = RSI最低
        df['layer'] = self.num_layers - df['layer'] + 1
        
        print(f"  分层完成")
        
        # 向量化计算各层每日收益
        print(f"  计算各层平均收益...")
        layer_returns = df.groupby(['date', 'layer'])[return_col].mean().unstack(fill_value=0)
        
        # 重命名列
        layer_returns.columns = [f'layer_{col}' for col in layer_returns.columns]
        
        # 确保所有层都有
        for i in range(1, self.num_layers + 1):
            col_name = f'layer_{i}'
            if col_name not in layer_returns.columns:
                layer_returns[col_name] = 0.0
        
        # 排序列
        layer_returns = layer_returns[[f'layer_{i}' for i in range(1, self.num_layers + 1)]]
        
        step_elapsed = time.time() - step_start
        print(f"  向量化计算耗时: {step_elapsed:.2f} 秒")
        
        return layer_returns
    
    def calculate_layer_returns(
        self,
        merged_df: pd.DataFrame,
        factor_col: str,
        return_col: str
    ) -> pd.DataFrame:
        """
        计算各层每日等权平均收益（原版方法，保留兼容性）
        
        注意：此方法已废弃，请使用 calculate_layer_returns_vectorized
        """
        return self.calculate_layer_returns_vectorized(merged_df, factor_col, return_col)
    
    def calculate_cumulative_returns(
        self, 
        layer_returns: pd.DataFrame
    ) -> pd.DataFrame:
        """
        计算各层累计净值
        
        公式:
            cumulative_nav[t] = cumulative_nav[t-1] * (1 + return[t])
            初始净值 = 1.0
        """
        cumulative_nav = (1 + layer_returns).cumprod()
        return cumulative_nav
    
    def calculate_long_short(
        self, 
        layer_returns: pd.DataFrame
    ) -> pd.DataFrame:
        """
        计算多空组合收益和净值
        
        多空组合 = Layer {num_layers} (最超卖) - Layer 1 (最超买)
        """
        daily_return = layer_returns[f'layer_{self.num_layers}'] - layer_returns['layer_1']
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
        """计算年化收益率"""
        cumulative_return = (1 + daily_returns).prod() - 1
        n_days = len(daily_returns)
        if n_days == 0:
            return 0.0
        return (1 + cumulative_return) ** (trading_days / n_days) - 1
    
    def calculate_t_stat(
        self, 
        daily_returns: pd.Series
    ) -> Tuple[float, float]:
        """计算t统计量和p值"""
        n = len(daily_returns)
        if n < 2:
            return (0.0, 1.0)
        
        mean_return = daily_returns.mean()
        std_return = daily_returns.std(ddof=1)
        
        if std_return == 0 or np.isnan(std_return):
            return (0.0, 1.0)
        
        t_stat = mean_return / (std_return / np.sqrt(n))
        p_value = 2 * (1 - stats.t.cdf(abs(t_stat), df=n-1))
        
        return (t_stat, p_value)
    
    def calculate_sharpe_ratio(
        self, 
        daily_returns: pd.Series, 
        trading_days: int = 250
    ) -> float:
        """计算夏普比率"""
        annual_return = self.calculate_annual_return(daily_returns, trading_days)
        daily_std = daily_returns.std(ddof=1)
        annual_std = daily_std * np.sqrt(trading_days)
        
        if annual_std == 0 or np.isnan(annual_std):
            return 0.0
        return annual_return / annual_std
    
    def calculate_statistics(
        self,
        layer_returns: pd.DataFrame,
        long_short: pd.DataFrame
    ) -> pd.DataFrame:
        """计算各层及多空组合的统计指标"""
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
        
        layer_names = {
            'long_short': '多空组合'
        }
        for i in range(1, self.num_layers + 1):
            if i == 1:
                layer_names[f'layer_{i}'] = f'Layer {i} (最超买)'
            elif i == self.num_layers:
                layer_names[f'layer_{i}'] = f'Layer {i} (最超卖)'
            else:
                layer_names[f'layer_{i}'] = f'Layer {i}'
        
        for layer, row in statistics.iterrows():
            layer_name = layer_names.get(layer, layer)
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
        
        is_monotonic = all(layer_annual_returns[i] <= layer_annual_returns[i+1] 
                          for i in range(len(layer_annual_returns)-1))
        
        if is_monotonic:
            print("✓ 单调性检验: 通过（收益从 Layer 1 到 Layer N 递增）")
        else:
            print("✗ 单调性检验: 未通过（收益存在波动）")
        
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
    """性能测试"""
    print("="*60)
    print("分层回测模块性能测试")
    print("="*60)
    
    # 导入真实数据加载器
    from real_data_loader import RealDataLoader
    
    loader = RealDataLoader(use_mock=False, use_local=False, enable_cache=True)
    
    print("\n正在从新浪财经API获取真实数据...")
    factor_df, return_df = loader.load_data(
        n_days=250,
        max_stocks=0,
        enable_complement=True
    )
    
    print("\n开始执行分层回测...")
    result = run_layered_backtest(
        factor_df, 
        return_df, 
        num_layers=5,
        factor_col='rsi_6',
        return_col='forward_return',
        enable_filter=True  # 启用动态过滤
    )
    
    print("\n" + "="*60)
    print("测试完成！")
    print("="*60)