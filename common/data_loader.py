"""
数据加载模块
支持真实数据和模拟数据
"""

import numpy as np
import pandas as pd
from datetime import datetime, timedelta
from typing import Dict, Optional, Tuple


class DataLoader:
    """数据加载器 - 支持真实数据和模拟数据"""
    
    def __init__(self, use_real_data: bool = False):
        """
        初始化数据加载器
        
        Args:
            use_real_data: 是否使用真实数据（当前支持模拟数据）
        """
        self.use_real_data = use_real_data
        self.stock_pool = None
        self.factor_data = None
        self.return_data = None
        
    def load_simulated_data(
        self,
        num_stocks: int = 100,
        num_days: int = 750,
        start_date: str = '2021-04-01'
    ) -> Tuple[pd.DataFrame, pd.DataFrame]:
        """
        加载模拟数据
        
        Args:
            num_stocks: 股票数量
            num_days: 交易日数量
            start_date: 起始日期
            
        Returns:
            (因子数据DataFrame, 收益数据DataFrame)
        """
        np.random.seed(42)  # 固定随机种子，保证可复现
        
        # 生成交易日序列
        start = pd.to_datetime(start_date)
        dates = pd.bdate_range(start=start, periods=num_days)  # 工作日
        
        # 生成股票代码
        stocks = [f'SZ{str(i).zfill(6)}' for i in range(1, num_stocks + 1)]
        
        # 创建 MultiIndex (日期, 股票代码)
        index = pd.MultiIndex.from_product(
            [dates, stocks],
            names=['date', 'stock']
        )
        
        # ===== 生成因子数据 =====
        
        # 因子1: RSI(6) < 30 (布尔因子)
        # 模拟RSI值 (0-100范围)
        rsi_values = np.random.uniform(0, 100, len(index))
        # 约15%的股票处于超卖状态
        rsi_factor = (rsi_values < 30).astype(int)
        
        # 因子2: 量比 > 1.5 (布尔因子)
        # 模拟量比 (0.5-3.0范围，均值约1.0)
        volume_ratio = np.random.lognormal(mean=0, sigma=0.5, size=len(index))
        # 约20%的股票量比>1.5
        volume_factor = (volume_ratio > 1.5).astype(int)
        
        # 添加一定的因子与收益的相关性
        # 基础收益率（随机）
        base_returns = np.random.normal(loc=0, scale=0.03, size=len(index))
        
        # RSI超卖因子有轻微的正向预测能力（反转效应）
        # IC约0.03-0.05
        rsi_alpha = 0.004  # 超卖股票平均超额收益
        returns_rsi_effect = rsi_factor * np.random.normal(rsi_alpha, 0.02, len(index))
        
        # 量比因子有轻微的负向预测能力（放量可能见顶）
        # IC约-0.02到-0.04
        volume_alpha = -0.003  # 高量比股票平均负超额收益
        returns_volume_effect = volume_factor * np.random.normal(volume_alpha, 0.015, len(index))
        
        # 最终收益率
        returns = base_returns + returns_rsi_effect + returns_volume_effect
        
        # 创建因子数据DataFrame
        factor_df = pd.DataFrame({
            'rsi_oversold': rsi_factor,
            'volume_ratio_high': volume_factor,
            'rsi_value': rsi_values,  # 原始RSI值，用于参考
            'volume_ratio': volume_ratio  # 原始量比值，用于参考
        }, index=index)
        
        # 创建收益数据DataFrame
        # 使用未来5日收益率（forward return）
        return_df = pd.DataFrame({
            'return_5d': returns  # 这里简化处理，实际应该是未来5日收益
        }, index=index)
        
        self.stock_pool = stocks
        self.factor_data = factor_df
        self.return_data = return_df
        
        print(f"✓ 模拟数据已加载:")
        print(f"  - 股票数量: {num_stocks}")
        print(f"  - 交易日数: {num_days}")
        print(f"  - 日期范围: {dates[0].strftime('%Y-%m-%d')} ~ {dates[-1].strftime('%Y-%m-%d')}")
        print(f"  - 因子: RSI超卖因子, 量比因子")
        
        return factor_df, return_df
    
    def get_factor_series(self, date: datetime, factor_name: str) -> pd.Series:
        """
        获取某日某因子的所有股票值
        
        Args:
            date: 日期
            factor_name: 因子名称
            
        Returns:
            Series, index为股票代码, value为因子值
        """
        if self.factor_data is None:
            raise ValueError("请先加载数据")
            
        return self.factor_data.xs(date, level='date')[factor_name]
    
    def get_return_series(self, date: datetime, return_col: str = 'return_5d') -> pd.Series:
        """
        获取某日所有股票的未来收益率
        
        Args:
            date: 日期
            return_col: 收益率列名
            
        Returns:
            Series, index为股票代码, value为收益率
        """
        if self.return_data is None:
            raise ValueError("请先加载数据")
            
        return self.return_data.xs(date, level='date')[return_col]
    
    def get_all_dates(self) -> pd.DatetimeIndex:
        """获取所有交易日"""
        if self.factor_data is None:
            raise ValueError("请先加载数据")
        return self.factor_data.index.get_level_values('date').unique()