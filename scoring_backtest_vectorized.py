#!/usr/bin/env python3
"""
向量化打分选股回测模块

核心优化：
1. 使用 df.groupby('date')[factor].rank(pct=True) 向量化计算得分
2. 使用 df.groupby('date').apply() 批量选股
3. 避免逐日循环，提升性能 10x+

作者: 云舟
日期: 2026-04-12
"""

import json
import gzip
import gc
import numpy as np
import pandas as pd
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional, Tuple, Callable


BASE_DIR = Path(__file__).parent
CACHE_DIR = BASE_DIR / 'cache/factor_data'


class VectorizedScoringBacktest:
    """
    向量化打分选股回测引擎
    
    优化策略：
    1. 预加载所有缓存数据到内存（启动时一次性加载）
    2. 使用 pandas groupby 向量化计算得分（避免逐日循环）
    3. 使用 pandas rank(pct=True) 快速标准化
    4. 批量计算收益，减少内存峰值
    """
    
    # 反向因子列表（打分时需要反转）
    # 修复：根据IC分析结果，只有换手率突增是反向因子（IC=-0.0492）
    REVERSE_FACTORS = ['turnover_surge']
    
    # 因子字段映射
    FACTOR_COLUMNS = {
        'rsi': 'rsi_6',
        'kdj_j': 'kdj_j',
        'bollinger_pb': 'bollinger_pb',
        'volume_ratio': 'volume_ratio_5',
        'turnover_surge': 'turnover_surge',
        'return_3d': 'return_3d'
    }
    
    def __init__(self, preload: bool = True):
        """
        初始化
        
        Args:
            preload: 是否预加载缓存数据（默认 True）
        """
        self._factor_df = None
        self._return_df = None
        self._stock_info = None
        self._available_dates = []
        self._stock_name_map = {}
        
        if preload:
            self._preload_cache()
    
    def _preload_cache(self):
        """
        预加载缓存数据到内存
        
        启动时一次性加载所有缓存，避免每次回测时重复读取
        """
        print("\n[向量化回测] 预加载缓存数据...")
        start_time = datetime.now()
        
        # 1. 加载因子数据
        self._load_factor_data()
        
        # 2. 加载收益数据
        self._load_return_data()
        
        # 3. 加载股票信息
        self._load_stock_info()
        
        # 4. 整合数据
        self._merge_data()
        
        elapsed = (datetime.now() - start_time).total_seconds()
        print(f"[向量化回测] 预加载完成，耗时 {elapsed:.1f} 秒")
        print(f"  数据量: {len(self._factor_df):,} 条")
        print(f"  日期范围: {self._available_dates[0]} ~ {self._available_dates[-1]}")
        print(f"  交易日数: {len(self._available_dates)}")
    
    def _load_factor_data(self):
        """加载因子数据"""
        factor_path = CACHE_DIR / 'factor_data.json.gz'
        
        if not factor_path.exists():
            raise FileNotFoundError("因子数据缓存不存在")
        
        print("  [加载] factor_data.json.gz...")
        
        with gzip.open(factor_path, 'rt', encoding='utf-8') as f:
            data = json.load(f)
        
        records = data.get('data', [])
        del data
        gc.collect()
        
        self._factor_df = pd.DataFrame(records)
        del records
        gc.collect()
        
        # 确保日期为字符串
        self._factor_df['date'] = self._factor_df['date'].astype(str)
        
        # 获取可用日期
        self._available_dates = sorted(self._factor_df['date'].unique())
        
        print(f"  [完成] 因子数据: {len(self._factor_df):,} 条")
    
    def _load_return_data(self):
        """加载收益数据"""
        return_path = CACHE_DIR / 'return_data.json.gz'
        
        if not return_path.exists():
            print("  [警告] 收益数据不存在，将使用 close 价格计算")
            return
        
        print("  [加载] return_data.json.gz...")
        
        with gzip.open(return_path, 'rt', encoding='utf-8') as f:
            data = json.load(f)
        
        records = data.get('data', [])
        del data
        gc.collect()
        
        self._return_df = pd.DataFrame(records)
        del records
        gc.collect()
        
        self._return_df['date'] = self._return_df['date'].astype(str)
        
        print(f"  [完成] 收益数据: {len(self._return_df):,} 条")
    
    def _load_stock_info(self):
        """加载股票信息"""
        stock_path = BASE_DIR / 'cache/stock_list.json'
        
        if stock_path.exists():
            with open(stock_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            stocks = data.get('stocks', [])
            self._stock_info = stocks
            self._stock_name_map = {s['code']: s['name'] for s in stocks}
            
            print(f"  [完成] 股票信息: {len(stocks):,} 只")
    
    def _merge_data(self):
        """整合数据源"""
        # 合并收益数据
        if self._return_df is not None:
            # 只保留需要的列
            return_cols = ['date', 'asset', 'forward_return_1d']
            self._factor_df = self._factor_df.merge(
                self._return_df[return_cols],
                on=['date', 'asset'],
                how='left'
            )
            
            # 释放收益数据
            del self._return_df
            self._return_df = None
            gc.collect()
        
        # 计算换手率突增因子（如果需要）
        if 'turnover_rate' in self._factor_df.columns:
            print("  [计算] 换手率突增因子...")
            
            self._factor_df = self._factor_df.sort_values(['asset', 'date'])
            
            # 计算5日滚动均值
            turnover_ma5 = self._factor_df.groupby('asset')['turnover_rate'].transform(
                lambda x: x.rolling(window=5, min_periods=1).mean()
            )
            
            # 换手率突增
            self._factor_df['turnover_surge'] = self._factor_df['turnover_rate'] / turnover_ma5
            self._factor_df['turnover_surge'] = self._factor_df['turnover_surge'].clip(upper=10)
        
        # 计算3日涨幅因子（如果需要）
        if 'return_3d' not in self._factor_df.columns and 'close' in self._factor_df.columns:
            print("  [计算] 3日涨幅因子...")
            
            self._factor_df = self._factor_df.sort_values(['asset', 'date'])
            
            # 计算3日涨幅（百分比）
            close_series = self._factor_df.groupby('asset')['close']
            self._factor_df['return_3d'] = close_series.transform(
                lambda x: (x / x.shift(3) - 1) * 100
            )
        
        gc.collect()
    
    def get_available_dates(self) -> List[str]:
        """获取可用日期列表"""
        return self._available_dates
    
    def calculate_scores_vectorized(
        self,
        weights: Dict[str, float],
        normalize_method: str = 'quantile',
        score_function: str = 'sigmoid',
        k_value: float = 10,
        top_n: int = 10
    ) -> pd.DataFrame:
        """
        向量化计算所有日期的综合得分
        
        使用 pandas groupby.rank(pct=True) 向量化计算
        避免逐日循环，性能提升 10x+
        
        v3.5 修复：
        - 添加 score_function 和 k_value 参数支持
        - 修复 Decimal 类型不兼容问题
        
        Args:
            weights: 因子权重字典
            normalize_method: 标准化方法 ('quantile', 'minmax', 'zscore')
            score_function: 打分函数 ('sigmoid', 'linear')
            k_value: Sigmoid k 参数（陡峭度）
            top_n: 每日选股数量
            
        Returns:
            DataFrame: date, asset, total_score, factor_scores
        """
        if self._factor_df is None:
            raise ValueError("数据未加载")
        
        print("\n[向量化得分] 开始计算...")
        
        # 总权重归一化
        total_weight = sum(weights.values())
        if total_weight == 0:
            raise ValueError("权重总和为0")
        
        norm_weights = {k: v / total_weight for k, v in weights.items()}
        
        # v3.5 修复：导入 Decimal 用于类型转换
        from decimal import Decimal
        
        # 1. 向量化标准化各因子
        score_df = self._factor_df[['date', 'asset', 'close']].copy()
        
        for factor_name, factor_col in self.FACTOR_COLUMNS.items():
            weight = norm_weights.get(factor_name, 0)
            
            if weight == 0 or factor_col not in self._factor_df.columns:
                continue
            
            # 获取原始值
            raw_values = self._factor_df[factor_col]
            
            # v3.5 修复：先将 Decimal 类型转换为 float
            if raw_values.dtype == object:
                if any(isinstance(v, Decimal) for v in raw_values.dropna()):
                    raw_values = raw_values.apply(lambda x: float(x) if isinstance(x, Decimal) else x)
            
            # 向量化标准化（按日期分组）
            if normalize_method == 'quantile':
                # 使用 groupby.rank(pct=True) 向量化计算
                norm_values = raw_values.groupby(self._factor_df['date']).rank(pct=True)
            elif normalize_method == 'minmax':
                # v3.5 修复：minmax 标准化，使用 float 类型
                date_groups = raw_values.groupby(self._factor_df['date'])
                min_vals = date_groups.transform('min').astype(float)
                max_vals = date_groups.transform('max').astype(float)
                range_vals = max_vals - min_vals
                range_vals = range_vals.replace(0, 1.0)  # 避免除零
                norm_values = (raw_values.astype(float) - min_vals) / range_vals
            elif normalize_method == 'zscore':
                # v3.5 修复：zscore 标准化，使用 float 类型
                date_groups = raw_values.groupby(self._factor_df['date'])
                mean_vals = date_groups.transform('mean').astype(float)
                std_vals = date_groups.transform('std').astype(float)
                std_vals = std_vals.replace(0, 1.0)  # 避免除零
                z = (raw_values.astype(float) - mean_vals) / std_vals
                norm_values = 1 / (1 + np.exp(-z))  # sigmoid 映射到 0-1
            else:
                # 默认使用 quantile
                norm_values = raw_values.groupby(self._factor_df['date']).rank(pct=True)
            
            # 反向因子反转
            if factor_name in self.REVERSE_FACTORS:
                norm_values = 1 - norm_values
            
            # v3.5 修复：实际应用 score_function 和 k_value
            # 打分（向量化）
            if score_function == 'sigmoid':
                # 向量化 sigmoid 计算
                score_values = 1 / (1 + np.exp(-k_value * (norm_values - 0.5)))
            else:
                # linear 打分：直接使用标准化值
                score_values = norm_values
            
            # 加权得分
            score_df[f'{factor_name}_score'] = score_values * weight * 100
        
        # 2. 计算综合得分
        score_cols = [c for c in score_df.columns if c.endswith('_score')]
        
        if not score_cols:
            raise ValueError("无有效因子得分列")
        
        # 向量化求和
        score_df['total_score'] = score_df[score_cols].sum(axis=1, skipna=True)
        
        # 3. 填充缺失值为 0
        score_df['total_score'] = score_df['total_score'].fillna(0)
        
        print(f"[向量化得分] 完成，共 {len(score_df):,} 条记录")
        
        return score_df
    
    def select_top_n_vectorized(
        self,
        score_df: pd.DataFrame,
        top_n: int = 10
    ) -> pd.DataFrame:
        """
        向量化选出每日 Top N 股票
        
        使用 groupby.apply 批量选股
        
        Args:
            score_df: 得分数据
            top_n: 选股数量
            
        Returns:
            DataFrame: date, asset, total_score, rank
        """
        print(f"\n[向量化选股] 每日选 Top {top_n}...")
        
        # 按日期分组，取 Top N
        def get_top_n(group):
            # 按得分排序，取 Top N
            top = group.nlargest(top_n, 'total_score')
            return top
        
        # 向量化选股
        # pandas 3.0 兼容性修复：使用 reset_index(level='date') 恢复分组列
        selected_df = score_df.groupby('date', group_keys=True).apply(get_top_n, include_groups=False).reset_index(level='date')
        
        # 添加排名
        selected_df['rank'] = selected_df.groupby('date')['total_score'].rank(
            ascending=False, method='first'
        ).astype(int)
        
        print(f"[向量化选股] 完成，共选出 {len(selected_df):,} 条记录")
        
        return selected_df
    
    def run_backtest_vectorized(
        self,
        start_date: str,
        end_date: str,
        weights: Dict[str, float],
        top_n: int = 10,
        cost: float = 0.002,
        slippage: float = 0.001,
        normalize_method: str = 'quantile',
        score_function: str = 'sigmoid',
        k_value: float = 10,
        progress_callback: Callable = None
    ) -> Dict:
        """
        向量化回测
        
        核心优化：
        1. 向量化计算所有日期的得分（一次性）
        2. 向量化选出每日 Top N（批量）
        3. 向量化计算每日收益（批量）
        
        v3.5 修复：添加 score_function 和 k_value 参数支持
        
        Args:
            start_date: 开始日期
            end_date: 结束日期
            weights: 因子权重
            top_n: 选股数量
            cost: 交易成本
            slippage: 滑点
            normalize_method: 标准化方法 ('quantile', 'minmax', 'zscore')
            score_function: 打分函数 ('sigmoid', 'linear')
            k_value: Sigmoid k 参数（陡峭度）
            progress_callback: 进度回调
            
        Returns:
            回测结果字典
        """
        print(f"\n{'='*60}")
        print(f"向量化打分选股回测")
        print(f"{'='*60}")
        print(f"日期范围: {start_date} ~ {end_date}")
        print(f"选股数量: Top {top_n}")
        print(f"交易成本: {cost * 100:.1f}%")
        print(f"打分函数: {score_function} (k={k_value})")
        
        if progress_callback:
            progress_callback(5, '正在向量化计算得分...')
        
        # 1. 向量化计算得分（v3.5 修复：传递 score_function 和 k_value）
        score_df = self.calculate_scores_vectorized(
            weights=weights,
            normalize_method=normalize_method,
            score_function=score_function,
            k_value=k_value,
            top_n=top_n
        )
        
        if progress_callback:
            progress_callback(20, '正在向量化选股...')
        
        # 2. 向量化选股
        selected_df = self.select_top_n_vectorized(score_df, top_n)
        
        if progress_callback:
            progress_callback(40, '正在计算收益...')
        
        # 3. 筛选日期范围
        dates_in_range = [d for d in self._available_dates if start_date <= d <= end_date]
        
        if not dates_in_range:
            return {
                'success': False,
                'error': f'日期范围 {start_date} ~ {end_date} 无数据'
            }
        
        # 筛选范围内的选股结果
        selected_in_range = selected_df[selected_df['date'].isin(dates_in_range)].copy()
        
        if progress_callback:
            progress_callback(50, '正在计算净值曲线...')
        
        # 4. 合并收益数据
        # 获取选股的下一日收益
        selected_with_return = selected_in_range.copy()
        
        # 创建日期映射（T -> T+1 收益）
        date_to_next = {}
        for i, date in enumerate(self._available_dates[:-1]):
            date_to_next[date] = self._available_dates[i + 1]
        
        # 添加下一日日期
        selected_with_return['next_date'] = selected_with_return['date'].map(date_to_next)
        
        # 合收益数据
        if 'forward_return_1d' in self._factor_df.columns:
            # 使用预先合并的收益数据
            return_data = self._factor_df[['date', 'asset', 'forward_return_1d']].copy()
            
            # 将选股日期映射到收益日期（下一日）
            selected_with_return['return_date'] = selected_with_return['next_date']
            
            # 合并收益
            selected_with_return = selected_with_return.merge(
                return_data.rename(columns={'date': 'return_date'}),
                on=['return_date', 'asset'],
                how='left'
            )
        
        if progress_callback:
            progress_callback(70, '正在计算回测指标...')
        
        # 5. 计算净值曲线（向量化）
        # 按日期分组，计算每日平均收益
        daily_returns = selected_with_return.groupby('date')['forward_return_1d'].mean()
        
        # 去除 NaN
        daily_returns = daily_returns.dropna()
        
        # 确保日期有序
        daily_returns = daily_returns.sort_index()
        
        # 计算净值
        nav = 1.0
        nav_series = []
        
        # 初始净值
        first_date = dates_in_range[0]
        nav_series.append({'date': first_date, 'nav': nav})
        
        # 计算换仓成本（简化：假设每日全部换仓）
        holdings = set()
        prev_selected = set()
        
        for i, date in enumerate(dates_in_range[:-1]):
            if date not in daily_returns.index:
                continue
            
            # 当日选股
            current_selected = set(
                selected_in_range[selected_in_range['date'] == date]['asset'].tolist()
            )
            
            # 换仓成本
            if prev_selected and current_selected:
                to_sell = prev_selected - current_selected
                to_buy = current_selected - prev_selected
                turnover_ratio = (len(to_sell) + len(to_buy)) / top_n
                trade_cost = turnover_ratio * cost * nav
                nav -= trade_cost
            
            # 更新持仓
            prev_selected = current_selected
            
            # 计算收益
            avg_return = daily_returns.get(date, 0)
            
            if avg_return is not None and not np.isnan(avg_return):
                nav *= (1 + avg_return - slippage)
            
            next_date = dates_in_range[i + 1] if i + 1 < len(dates_in_range) else date
            nav_series.append({'date': next_date, 'nav': round(nav, 4)})
        
        if progress_callback:
            progress_callback(90, '正在计算统计指标...')
        
        # 6. 计算回测指标
        returns = []
        for i in range(1, len(nav_series)):
            if nav_series[i-1]['nav'] > 0:
                r = nav_series[i]['nav'] / nav_series[i-1]['nav'] - 1
                returns.append(r)
        
        if not returns:
            return {
                'success': True,
                'nav_series': nav_series,
                'metrics': {},
                'message': '回测完成，但无有效收益数据'
            }
        
        # 年化收益
        total_days = len(nav_series)
        annual_return = (nav - 1) * (252 / total_days) if total_days > 0 else 0
        
        # 夏普比率
        avg_daily_return = np.mean(returns)
        std_daily_return = np.std(returns)
        sharpe = avg_daily_return / std_daily_return * np.sqrt(252) if std_daily_return > 0 else 0
        
        # 最大回撤
        peak_values = [n['nav'] for n in nav_series]
        peak = max(peak_values)
        trough = min(peak_values)
        max_drawdown = (trough - peak) / peak if peak > 0 else 0
        
        # 胜率
        positive_days = sum(1 for r in returns if r > 0)
        win_rate = positive_days / len(returns) if returns else 0
        
        # 7. 选股明细（最近一日）
        latest_date = dates_in_range[-1]
        latest_selections = selected_in_range[
            selected_in_range['date'] == latest_date
        ].sort_values('rank')
        
        selections = []
        for _, row in latest_selections.iterrows():
            asset = row['asset']
            selections.append({
                'code': asset,
                'name': self._stock_name_map.get(asset, asset),
                'rank': int(row['rank']),
                'total_score': round(row['total_score'], 2)
            })
        
        if progress_callback:
            progress_callback(100, '回测完成')
        
        print(f"\n{'='*60}")
        print(f"回测结果")
        print(f"{'='*60}")
        print(f"年化收益: {annual_return * 100:.2f}%")
        print(f"夏普比率: {sharpe:.2f}")
        print(f"最大回撤: {max_drawdown * 100:.2f}%")
        print(f"胜率: {win_rate * 100:.1f}%")
        print(f"最终净值: {nav:.4f}")
        
        return {
            'success': True,
            'nav_series': nav_series,
            'metrics': {
                'annual_return': round(annual_return * 100, 2),
                'sharpe_ratio': round(sharpe, 2),
                'max_drawdown': round(max_drawdown * 100, 2),
                'win_rate': round(win_rate * 100, 2),
                'total_days': total_days,
                'final_nav': round(nav, 4)
            },
            'selections': selections,
            'params': {
                'start_date': start_date,
                'end_date': end_date,
                'weights': weights,
                'top_n': top_n,
                'cost': cost,
                'slippage': slippage,
                'normalize_method': normalize_method,
                'score_function': score_function,
                'k_value': k_value,
                'vectorized': True
            }
        }
    
    def get_stock_detail(self, code: str, date: str = None) -> Dict:
        """获取股票详情"""
        if date is None:
            date = self._available_dates[-1]
        
        stock_data = self._factor_df[
            (self._factor_df['date'] == date) &
            (self._factor_df['asset'] == code)
        ]
        
        if len(stock_data) == 0:
            return {'success': False, 'error': f'股票 {code} 在 {date} 无数据'}
        
        row = stock_data.iloc[0]
        
        factors = []
        for factor_name, factor_col in self.FACTOR_COLUMNS.items():
            if factor_col in self._factor_df.columns:
                raw = row.get(factor_col)
                if raw is not None:
                    direction = '反向' if factor_name in self.REVERSE_FACTORS else '正向'
                    factors.append({
                        'factor_id': factor_name,
                        'raw': round(raw, 2) if isinstance(raw, float) else raw,
                        'direction': direction
                    })
        
        return {
            'success': True,
            'code': code,
            'name': self._stock_name_map.get(code, code),
            'date': date,
            'factors': factors,
            'close': round(row.get('close', 0), 2)
        }


# 全局实例（预加载）
_vectorized_engine = None

def get_vectorized_engine() -> VectorizedScoringBacktest:
    """获取全局向量化引擎实例（预加载）"""
    global _vectorized_engine
    if _vectorized_engine is None:
        _vectorized_engine = VectorizedScoringBacktest(preload=True)
    return _vectorized_engine


def run_vectorized_backtest(
    start_date: str,
    end_date: str,
    weights: Dict[str, float],
    top_n: int = 10,
    cost: float = 0.002,
    slippage: float = 0.001,
    normalize_method: str = 'quantile',
    score_function: str = 'sigmoid',
    k_value: float = 10,
    progress_callback: Callable = None
) -> Dict:
    """
    运行向量化回测（便捷接口）
    
    v3.5 修复：添加 score_function 和 k_value 参数支持
    
    Args:
        start_date: 开始日期
        end_date: 结束日期
        weights: 因子权重
        top_n: 选股数量
        cost: 交易成本
        slippage: 滑点
        normalize_method: 标准化方法
        score_function: 打分函数 ('sigmoid', 'linear')
        k_value: Sigmoid k 参数
        progress_callback: 进度回调
        
    Returns:
        回测结果字典
    """
    engine = get_vectorized_engine()
    
    return engine.run_backtest_vectorized(
        start_date=start_date,
        end_date=end_date,
        weights=weights,
        top_n=top_n,
        cost=cost,
        slippage=slippage,
        normalize_method=normalize_method,
        score_function=score_function,
        k_value=k_value,
        progress_callback=progress_callback
    )


if __name__ == '__main__':
    """测试向量化回测"""
    
    # 默认权重
    weights = {
        'rsi': 17,
        'kdj_j': 14,
        'bollinger_pb': 17,
        'volume_ratio': 14,
        'turnover_surge': 14,
        'return_3d': 12
    }
    
    # 获取引擎
    engine = get_vectorized_engine()
    
    # 获取可用日期
    dates = engine.get_available_dates()
    
    if not dates:
        print("无可用数据")
    else:
        # 运行回测（近250日）
        start_date = dates[-250] if len(dates) >= 250 else dates[0]
        end_date = dates[-1]
        
        result = engine.run_backtest_vectorized(
            start_date=start_date,
            end_date=end_date,
            weights=weights,
            top_n=10
        )
        
        if result['success']:
            print(f"\n最终净值: {result['metrics']['final_nav']}")
            print(f"年化收益: {result['metrics']['annual_return']}%")
            print(f"夏普比率: {result['metrics']['sharpe_ratio']}")
            
            print(f"\n最近一日选股:")
            for s in result['selections'][:10]:
                print(f"  {s['rank']}. {s['code']} - {s['name']}: {s['total_score']}")