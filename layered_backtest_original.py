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

作者: 云舟
日期: 2026-04-02
更新: 2026-04-02 - 修复分层方向，适配动量效应
"""

import pandas as pd
import numpy as np
from typing import Dict, Tuple, Optional
from dataclasses import dataclass
from scipy import stats
import warnings
warnings.filterwarnings('ignore')


@dataclass
class LayeredResult:
    """分层回测结果"""
    layer_returns: pd.DataFrame  # 各层每日收益
    cumulative_returns: pd.DataFrame  # 各层累计净值
    statistics: pd.DataFrame  # 统计指标
    long_short: pd.DataFrame  # 多空组合
    ic_series: Optional[pd.Series] = None  # IC时间序列（可选）


class LayeredBacktest:
    """分层回测核心类"""
    
    def __init__(self, num_layers: int = 5):
        """
        初始化分层回测
        
        Args:
            num_layers: 分层数量（默认5层）
        """
        if num_layers < 2:
            raise ValueError("分层数量必须 >= 2")
        self.num_layers = num_layers
    
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
        print(f"\n{'='*60}")
        print(f"开始分层回测分析")
        print(f"{'='*60}")
        print(f"  分层数量: {self.num_layers}")
        print(f"  因子列: {factor_col}")
        print(f"  收益列: {return_col}")
        
        # 合并因子和收益数据
        merged = pd.merge(
            factor_df, 
            return_df, 
            on=['date', 'asset'], 
            how='inner'
        )
        
        print(f"  合并后数据量: {len(merged)} 条")
        
        # 计算各层每日收益
        layer_returns = self.calculate_layer_returns(
            merged, 
            factor_col, 
            return_col
        )
        
        print(f"  计算完成，共 {len(layer_returns)} 个交易日")
        
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
            long_short=long_short
        )
    
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
        
        # 按日期分组
        grouped = merged_df.groupby('date')
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
    return_col: str = 'forward_return'
) -> LayeredResult:
    """
    执行分层回测（便捷函数）
    
    Args:
        factor_df: 因子数据
        return_df: 收益数据
        num_layers: 分层数量
        factor_col: 因子列名
        return_col: 收益列名
        
    Returns:
        LayeredResult: 分层回测结果
    """
    backtest = LayeredBacktest(num_layers=num_layers)
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