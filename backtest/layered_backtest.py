"""
通用分层回测引擎

设计原则:
1. 不依赖特定因子，支持任意因子分层回测
2. 支持自定义分层数量和阈值
3. 支持正向因子和反向因子
4. 输出标准化结果，方便比较分析

作者: 云瑶
创建日期: 2026-05-19
修订日期: 2026-05-23（日志规范化 + 代码质量优化）
"""

import sys
from pathlib import Path

# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent.parent))

import pandas as pd
import numpy as np
from typing import Dict, List, Optional, Tuple, Any
import warnings

# 导入公共日志模块（遵循 PROJECT.md 强制复用规范）
from factor_ic.common.logger_config import get_logger

logger = get_logger(__name__)


class LayeredBacktestEngine:
    """
    通用分层回测引擎
    
    用法:
        engine = LayeredBacktestEngine(factor_df, return_df, factor_col='rsi_6')
        result = engine.run(
            layer_method='fixed_threshold',
            thresholds=[0, 20, 40, 60, 80, 100],
            factor_direction='negative',
            long_layers=[1, 2],
            short_layers=[4, 5]
        )
    """
    
    def __init__(
        self,
        factor_df: pd.DataFrame,
        return_df: pd.DataFrame,
        factor_col: str = 'factor_value',
        return_col: str = 'forward_return',
        date_col: str = 'date',
        asset_col: str = 'asset',
        volume_col: Optional[str] = None
    ):
        """
        初始化回测引擎
        
        参数:
            factor_df: 因子数据，必须包含 [date_col, asset_col, factor_col]
            return_df: 收益数据，必须包含 [date_col, asset_col, return_col]
            factor_col: 因子值列名
            return_col: 未来收益列名
            date_col: 日期列名
            asset_col: 资产代码列名
            volume_col: 成交量列名（用于停牌过滤，可选）
        """
        self.factor_col = factor_col
        self.return_col = return_col
        self.date_col = date_col
        self.asset_col = asset_col
        self.volume_col = volume_col
        
        # 合并数据
        self._merge_data(factor_df, return_df)
        
    def _merge_data(self, factor_df: pd.DataFrame, return_df: pd.DataFrame):
        """合并因子和收益数据"""
        # 选择需要的列
        factor_cols = [self.date_col, self.asset_col, self.factor_col]
        if self.volume_col and self.volume_col in factor_df.columns:
            factor_cols.append(self.volume_col)
        
        return_cols = [self.date_col, self.asset_col, self.return_col]
        
        factor_subset = factor_df[factor_cols].copy()
        return_subset = return_df[return_cols].copy()
        
        # 合并
        self.merged_df = pd.merge(
            factor_subset,
            return_subset,
            on=[self.date_col, self.asset_col],
            how='inner'
        )
        
        # 获取日期列表
        self.dates = sorted(self.merged_df[self.date_col].unique())
        
        # 内存优化
        self.merged_df[self.asset_col] = self.merged_df[self.asset_col].astype('category')
        if self.factor_col in self.merged_df.columns:
            self.merged_df[self.factor_col] = self.merged_df[self.factor_col].astype('float32')
        if self.return_col in self.merged_df.columns:
            self.merged_df[self.return_col] = self.merged_df[self.return_col].astype('float32')
    
    def run(
        self,
        layer_method: str = 'percentile',
        n_layers: int = 5,
        thresholds: Optional[List[float]] = None,
        factor_direction: str = 'positive',
        long_layers: Optional[List[int]] = None,
        short_layers: Optional[List[int]] = None,
        min_stocks_per_layer: int = 10,
        trade_cost_rate: float = 0.003
    ) -> Dict:
        """
        执行分层回测
        
        参数:
            layer_method: 分层方法
                - 'percentile': 百分位分层（每层20%）
                - 'fixed_threshold': 固定阈值分层（需指定thresholds）
            n_layers: 分层数量（仅percentile模式）
            thresholds: 固定阈值列表，如 [0, 20, 40, 60, 80, 100]
            factor_direction: 因子方向
                - 'positive': 正向因子，高值=高收益预期
                - 'negative': 反向因子，低值=高收益预期
            long_layers: 多头组合的层编号（从1开始）
            short_layers: 空头组合的层编号
            min_stocks_per_layer: 每层最少股票数
            trade_cost_rate: 单边交易成本率
        
        返回:
            回测结果字典
        """
        # ========== 参数校验 ==========
        # 校验 factor_direction
        valid_directions = ['positive', 'negative']
        if factor_direction not in valid_directions:
            raise ValueError(
                f"factor_direction 必须是 'positive' 或 'negative', 当前值: '{factor_direction}'"
            )
        
        # 校验 layer_method
        valid_methods = ['percentile', 'fixed_threshold']
        if layer_method not in valid_methods:
            raise ValueError(
                f"layer_method 必须是 'percentile' 或 'fixed_threshold', 当前值: '{layer_method}'"
            )
        
        # 校验 thresholds（fixed_threshold 模式）
        if layer_method == 'fixed_threshold':
            if thresholds is None or len(thresholds) < 2:
                raise ValueError(
                    f"fixed_threshold 模式需要 thresholds 参数，且至少包含2个阈值点"
                )
            # 校验阈值递增
            for i in range(len(thresholds) - 1):
                if thresholds[i] >= thresholds[i + 1]:
                    raise ValueError(
                        f"thresholds 必须严格递增，第{i}个阈值 {thresholds[i]} >= 第{i+1}个阈值 {thresholds[i+1]}"
                    )
        
        logger.info(f"开始分层回测: layer_method={layer_method}, factor_direction={factor_direction}")
        
        # 设置默认多空组合
        if long_layers is None:
            long_layers = [n_layers - 1, n_layers] if factor_direction == 'positive' else [1, 2]
        if short_layers is None:
            short_layers = [1, 2] if factor_direction == 'positive' else [n_layers - 1, n_layers]
        
        # 确定分层数量
        if layer_method == 'fixed_threshold' and thresholds:
            n_layers = len(thresholds) - 1
        
        # 每日处理
        daily_records = []
        prev_assignment = None
        
        for date in self.dates:
            # 获取当日数据
            day_data = self.merged_df[self.merged_df[self.date_col] == date].copy()
            
            # 停牌过滤
            if self.volume_col and self.volume_col in day_data.columns:
                day_data = day_data[day_data[self.volume_col] > 0]
            
            # 过滤因子为NaN的数据
            day_data = day_data[day_data[self.factor_col].notna()]
            
            if len(day_data) < min_stocks_per_layer:
                continue
            
            # 分层
            layer_assignment = self.get_layer_assignment(
                date,
                day_data[self.factor_col],
                layer_method,
                n_layers,
                thresholds
            )
            
            # 将分层结果直接赋值（layer_assignment index与day_data相同）
            day_data['_layer'] = layer_assignment
            
            # 计算各层收益
            layer_returns = self.calculate_layer_returns(
                date,
                day_data['_layer'],
                day_data[self.return_col],
                min_stocks_per_layer
            )
            
            # 计算换手率
            turnover_rates = self.calculate_turnover(
                prev_assignment,
                dict(zip(
                    day_data[self.asset_col].astype(str),  # 确保asset为字符串
                    day_data['_layer']
                ))
            )
            
            # 记录每日结果
            for layer_id in range(1, n_layers + 1):
                n_stocks = int((day_data['_layer'] == layer_id).sum())  # 转为int避免JSON序列化问题
                daily_records.append({
                    'date': date,
                    'layer': int(layer_id),  # 转为int
                    'n_stocks': n_stocks,
                    'return': layer_returns.get(layer_id, np.nan),
                    'turnover': float(turnover_rates.get(layer_id, 0.0))  # 转为float
                })
            
            prev_assignment = dict(zip(
                day_data[self.asset_col].astype(str),
                day_data['_layer']
            ))
        
        # 构建结果DataFrame
        daily_df = pd.DataFrame(daily_records)
        
        # 汇总统计
        result = self._aggregate_results(
            daily_df,
            n_layers,
            long_layers,
            short_layers,
            factor_direction,
            trade_cost_rate,
            layer_method,
            thresholds
        )
        
        return result
    
    def get_layer_assignment(
        self,
        date: str,
        factor_values: pd.Series,
        method: str,
        n_layers: int,
        thresholds: Optional[List[float]]
    ) -> pd.Series:
        """
        计算股票分层归属
        
        返回: Series(index=asset, value=layer_id)
        """
        if method == 'percentile':
            # 百分位分层
            ranks = factor_values.rank(pct=True)
            layer_assignment = np.ceil(ranks * n_layers).astype(int)
            # 处理边界（rank=1时为第n层）
            layer_assignment = layer_assignment.clip(1, n_layers)
        
        elif method == 'fixed_threshold' and thresholds:
            # 固定阈值分层（边界值归入下一层）
            layer_assignment = pd.Series(0, index=factor_values.index)
            
            for i in range(len(thresholds) - 1):
                lower = thresholds[i]
                upper = thresholds[i + 1]
                mask = (factor_values >= lower) & (factor_values < upper)
                layer_assignment[mask] = i + 1
            
            # 处理最大边界
            layer_assignment[factor_values >= thresholds[-1]] = n_layers
            # 处理最小边界（低于第一个阈值）
            layer_assignment[factor_values < thresholds[0]] = 1
        
        else:
            raise ValueError(f"Unknown layer method: {method}")
        
        return layer_assignment
    
    def calculate_layer_returns(
        self,
        date: str,
        layer_assignment: pd.Series,
        returns: pd.Series,
        min_stocks: int = 10
    ) -> Dict[int, float]:
        """
        计算各层收益（等权平均）
        
        参数:
            date: 日期
            layer_assignment: 分层归属
            returns: 收益序列
            min_stocks: 最少股票数
        
        返回:
            各层收益字典 {layer_id: return}
        """
        layer_returns = {}
        
        for layer_id in layer_assignment.unique():
            if pd.isna(layer_id) or layer_id == 0:
                continue
            
            layer_mask = layer_assignment == layer_id
            layer_returns_vals = returns[layer_mask]
            
            # 空层检查
            if len(layer_returns_vals) < min_stocks:
                layer_returns[int(layer_id)] = np.nan
                continue
            
            # 过滤NaN收益
            valid_returns = layer_returns_vals.dropna()
            
            if len(valid_returns) < min_stocks // 2:
                layer_returns[int(layer_id)] = np.nan
            else:
                layer_returns[int(layer_id)] = float(valid_returns.mean())  # 转为float
        
        return layer_returns
    
    def calculate_turnover(
        self,
        prev_assignment: Optional[Dict[str, int]],
        curr_assignment: Dict[str, int]
    ) -> Dict[int, float]:
        """
        计算换手率
        
        换手率 = 新入股票数 / 层股票总数
        """
        turnover_rates = {}
        
        if prev_assignment is None:
            return turnover_rates
        
        # 获取所有层
        all_layers = set(curr_assignment.values())
        
        for layer_id in all_layers:
            # 当前层股票
            curr_stocks = {s for s, l in curr_assignment.items() if l == layer_id}
            
            # 前一期该层股票
            prev_stocks = {s for s, l in prev_assignment.items() if l == layer_id}
            
            # 新入股票
            new_stocks = curr_stocks - prev_stocks
            
            # 换手率
            if len(curr_stocks) > 0:
                turnover_rates[int(layer_id)] = float(len(new_stocks) / len(curr_stocks))
            else:
                turnover_rates[int(layer_id)] = 0.0
        
        return turnover_rates
    
    def _aggregate_results(
        self,
        daily_df: pd.DataFrame,
        n_layers: int,
        long_layers: List[int],
        short_layers: List[int],
        factor_direction: str,
        trade_cost_rate: float,
        layer_method: str,
        thresholds: Optional[List[float]]
    ) -> Dict:
        """汇总统计结果"""
        
        # 各层统计
        layer_stats = {}
        for layer_id in range(1, n_layers + 1):
            layer_data = daily_df[daily_df['layer'] == layer_id]
            
            # 过滤NaN收益
            valid_returns = layer_data['return'].dropna()
            
            if len(valid_returns) == 0:
                layer_stats[f'layer_{layer_id}'] = {
                    'n_days': int(len(layer_data)),
                    'n_stocks_avg': 0,
                    'daily_return_mean': None,
                    'daily_return_std': None,
                    'cumulative_return': None,
                    'annual_return': None,
                    'annual_volatility': None,
                    'sharpe_ratio': None,
                    'max_drawdown': None,
                    'turnover_avg': None
                }
                continue
            
            daily_return_mean = valid_returns.mean()
            daily_return_std = valid_returns.std()
            
            # 累计收益
            cum_returns = (1 + valid_returns).cumprod() - 1
            cumulative_return = cum_returns.iloc[-1] if len(cum_returns) > 0 else 0
            
            # 年化收益和波动
            annual_return = daily_return_mean * 252
            annual_volatility = daily_return_std * np.sqrt(252)
            
            # 夏普比率
            sharpe_ratio = annual_return / annual_volatility if annual_volatility > 0 else np.nan
            
            # 最大回撤
            cum_series = (1 + valid_returns).cumprod()
            rolling_max = cum_series.expanding().max()
            drawdowns = (cum_series - rolling_max) / rolling_max
            max_drawdown = drawdowns.min()
            
            # 换手率
            turnover_data = layer_data['turnover'].dropna()
            turnover_avg = turnover_data.mean() if len(turnover_data) > 0 else 0
            
            layer_stats[f'layer_{layer_id}'] = {
                'n_days': int(len(layer_data)),  # 转 int 避免 JSON 序列化问题
                'n_stocks_avg': float(layer_data['n_stocks'].mean()),  # 转 float
                'daily_return_mean': float(daily_return_mean),
                'daily_return_std': float(daily_return_std),
                'cumulative_return': float(cumulative_return),
                'annual_return': float(annual_return),
                'annual_volatility': float(annual_volatility),
                'sharpe_ratio': float(sharpe_ratio) if not np.isnan(sharpe_ratio) else None,
                'max_drawdown': float(max_drawdown),
                'turnover_avg': float(turnover_avg)
            }
        
        # 多空组合统计（优化：用 groupby 替代 iterrows）
        # 构建筛选条件
        long_mask = daily_df['layer'].isin(long_layers) & daily_df['return'].notna()
        short_mask = daily_df['layer'].isin(short_layers) & daily_df['return'].notna()
        
        # 直接提取数据，避免逐行迭代
        long_returns = daily_df.loc[long_mask, 'return'].tolist()
        short_returns = daily_df.loc[short_mask, 'return'].tolist()
        long_turnovers = daily_df.loc[long_mask & daily_df['turnover'].notna(), 'turnover'].tolist()
        short_turnovers = daily_df.loc[short_mask & daily_df['turnover'].notna(), 'turnover'].tolist()
        
        # 计算多空组合收益（优化：用 groupby 替代循环）
        # 按 date 分组，计算每日多空收益
        def calc_daily_ls(group):
            long_rets = group[group['layer'].isin(long_layers)]['return'].dropna()
            short_rets = group[group['layer'].isin(short_layers)]['return'].dropna()
            if len(long_rets) > 0 and len(short_rets) > 0:
                return pd.Series({
                    'long_return': long_rets.mean(),
                    'short_return': short_rets.mean(),
                    'long_short_return': long_rets.mean() - short_rets.mean()
                })
            return pd.Series({
                'long_return': np.nan,
                'short_return': np.nan,
                'long_short_return': np.nan
            })
        
        # 应用 groupby，过滤 NaN 行
        long_short_df = daily_df.groupby('date').apply(calc_daily_ls).dropna()
        # 重置索引，保留 date 列
        if len(long_short_df) > 0:
            long_short_df = long_short_df.reset_index()
        
        # 多空组合统计
        long_short_stats = {}
        if len(long_short_df) > 0:
            ls_mean = long_short_df['long_short_return'].mean()
            ls_std = long_short_df['long_short_return'].std()
            ls_annual = ls_mean * 252
            ls_vol = ls_std * np.sqrt(252)
            
            long_short_stats = {
                'long_return_daily': float(long_short_df['long_return'].mean()),
                'long_return_annual': float(long_short_df['long_return'].mean() * 252),
                'short_return_daily': float(long_short_df['short_return'].mean()),
                'short_return_annual': float(long_short_df['short_return'].mean() * 252),
                'long_short_return_daily': float(ls_mean),
                'long_short_return_annual': float(ls_annual),
                'long_short_sharpe': float(ls_annual / ls_vol) if ls_vol > 0 else None,
                'long_short_volatility': float(ls_vol),
                'avg_turnover_long': float(np.mean(long_turnovers)) if long_turnovers else 0,
                'avg_turnover_short': float(np.mean(short_turnovers)) if short_turnovers else 0,
                'n_days': int(len(long_short_df))  # 转 int 避免 JSON 序列化问题
            }
        
        # 单调性检验
        monotonicity = self._calculate_monotonicity(layer_stats, n_layers, factor_direction)
        
        # 交易成本分析
        trading_cost_analysis = self._calculate_trading_costs(
            long_short_stats,
            trade_cost_rate
        )
        
        # 元数据
        meta = {
            'n_layers': n_layers,
            'factor_direction': factor_direction,
            'long_layers': long_layers,
            'short_layers': short_layers,
            # 简化 min 表达式：用 groupby 替代循环
            'min_stocks_per_layer': int(daily_df.groupby('layer')['n_stocks'].min().min()) if len(daily_df) > 0 else 0,
            'trade_cost_rate': trade_cost_rate,
            'layer_method': layer_method,
            'thresholds': thresholds,
            'n_days_total': int(len(daily_df['date'].unique())),  # 转 int 避免 JSON 序列化问题
            'n_assets_total': int(len(self.merged_df[self.asset_col].unique()))  # 转 int
        }
        
        return {
            'meta': meta,
            'layer_stats': layer_stats,
            'long_short': long_short_stats,
            'monotonicity': monotonicity,
            'trading_cost_analysis': trading_cost_analysis,
            'daily_records': daily_df.to_dict('records')
        }
    
    def _calculate_monotonicity(
        self,
        layer_stats: Dict,
        n_layers: int,
        factor_direction: str
    ) -> Dict:
        """
        计算分层单调性
        
        对于反向因子，期望 Layer1收益 > Layer2 > ... > Layer5
        单调性应为负值
        """
        layer_returns = []
        for i in range(1, n_layers + 1):
            ret = layer_stats.get(f'layer_{i}', {}).get('daily_return_mean')
            if not pd.isna(ret) and ret is not None:
                layer_returns.append(ret)
            else:
                layer_returns.append(np.nan)
        
        # 计算相关系数
        valid_idx = [i for i, r in enumerate(layer_returns) if not pd.isna(r)]
        if len(valid_idx) >= 2:
            layer_ids = np.array([i + 1 for i in valid_idx])
            returns = np.array([layer_returns[i] for i in valid_idx])
            
            correlation = np.corrcoef(layer_ids, returns)[0, 1]
            
            # 对于反向因子，期望负相关
            if factor_direction == 'negative':
                monotonic_quality = 'good' if correlation < -0.5 else ('moderate' if correlation < 0 else 'poor')
            else:
                monotonic_quality = 'good' if correlation > 0.5 else ('moderate' if correlation > 0 else 'poor')
            
            return {
                'correlation': float(correlation),
                'quality': monotonic_quality,
                'layer_returns': layer_returns
            }
        
        return {
            'correlation': None,
            'quality': 'insufficient_data',
            'layer_returns': layer_returns
        }
    
    def _calculate_trading_costs(
        self,
        long_short_stats: Dict,
        trade_cost_rate: float
    ) -> Dict:
        """计算交易成本"""
        if not long_short_stats:
            return {}
        
        long_turnover = long_short_stats.get('avg_turnover_long', 0)
        short_turnover = long_short_stats.get('avg_turnover_short', 0)
        
        long_daily_ret = long_short_stats.get('long_return_daily', 0)
        short_daily_ret = long_short_stats.get('short_return_daily', 0)
        
        # 多头交易成本（单边）
        long_daily_cost = long_turnover * trade_cost_rate
        
        # 空头交易成本（双边，因为做空需要借券）
        short_daily_cost = short_turnover * trade_cost_rate * 2
        
        return {
            'cost_rate': trade_cost_rate,
            'long_turnover': long_turnover,
            'short_turnover': short_turnover,
            'long_daily_cost': long_daily_cost,
            'short_daily_cost': short_daily_cost,
            'long_gross_daily_return': long_daily_ret,
            'long_net_daily_return': long_daily_ret - long_daily_cost,
            'short_gross_daily_return': short_daily_ret,
            'short_net_daily_return': short_daily_ret - short_daily_cost,
            'long_short_gross_daily': long_daily_ret - short_daily_ret,
            'long_short_net_daily': (long_daily_ret - long_daily_cost) - (short_daily_ret - short_daily_cost)
        }
    
    def generate_report(self, result: Dict) -> str:
        """生成文本报告"""
        lines = []
        lines.append("=" * 70)
        lines.append("分层回测报告")
        lines.append("=" * 70)
        lines.append("")
        
        # 元数据
        meta = result['meta']
        lines.append(f"分层数量: {meta['n_layers']}")
        lines.append(f"因子方向: {'反向因子' if meta['factor_direction'] == 'negative' else '正向因子'}")
        lines.append(f"多头组合: Layer {', '.join(map(str, meta['long_layers']))}")
        lines.append(f"空头组合: Layer {meta['short_layers']}")
        lines.append(f"回测天数: {meta['n_days_total']}")
        lines.append(f"股票数量: {meta['n_assets_total']}")
        lines.append("")
        
        # 分层收益统计
        lines.append("-" * 70)
        lines.append("一、分层收益统计")
        lines.append("-" * 70)
        lines.append(f"{'分层':<8} {'股票数':<10} {'日均收益':<12} {'年化收益':<12} {'夏普比':<10} {'换手率':<10}")
        lines.append("-" * 70)
        
        for layer_id in range(1, meta['n_layers'] + 1):
            stats = result['layer_stats'].get(f'layer_{layer_id}', {})
            if stats.get('n_stocks_avg', 0) == 0:
                continue
            
            n_stocks = stats.get('n_stocks_avg', 0)
            daily_ret = stats.get('daily_return_mean', 0) or 0
            annual_ret = stats.get('annual_return', 0) or 0
            sharpe = stats.get('sharpe_ratio')
            turnover = stats.get('turnover_avg', 0) or 0
            
            sharpe_str = f"{sharpe:.2f}" if sharpe is not None else "N/A"
            lines.append(f"Layer{layer_id:<3} {n_stocks:<10.0f} {daily_ret*100:>10.2f}% {annual_ret*100:>10.2f}% {sharpe_str:<10} {turnover*100:>8.1f}%")
        
        lines.append("-" * 70)
        lines.append("")
        
        # 多空组合表现
        lines.append("-" * 70)
        lines.append("二、多空组合表现")
        lines.append("-" * 70)
        
        ls_stats = result.get('long_short', {})
        if ls_stats:
            lines.append(f"多头日均收益: {ls_stats.get('long_return_daily', 0)*100:.4f}%")
            lines.append(f"多头年化收益: {ls_stats.get('long_return_annual', 0)*100:.2f}%")
            lines.append(f"空头日均收益: {ls_stats.get('short_return_daily', 0)*100:.4f}%")
            lines.append(f"空头年化收益: {ls_stats.get('short_return_annual', 0)*100:.2f}%")
            lines.append(f"多空日均收益: {ls_stats.get('long_short_return_daily', 0)*100:.4f}%")
            lines.append(f"多空年化收益: {ls_stats.get('long_short_return_annual', 0)*100:.2f}%")
            lines.append(f"多空夏普比率: {ls_stats.get('long_short_sharpe', 0):.2f}")
        
        lines.append("-" * 70)
        lines.append("")
        
        # 单调性
        lines.append("-" * 70)
        lines.append("三、单调性检验")
        lines.append("-" * 70)
        
        mono = result.get('monotonicity', {})
        corr = mono.get('correlation')
        if corr is not None:
            lines.append(f"分层单调性相关系数: {corr:.4f}")
            lines.append(f"单调性质量: {mono.get('quality', 'unknown')}")
            
            if meta['factor_direction'] == 'negative':
                if corr < -0.5:
                    lines.append("✓ 反向因子单调性良好（Layer1 > Layer5）")
                elif corr < 0:
                    lines.append("△ 反向因子单调性一般")
                else:
                    lines.append("✗ 反向因子单调性较差")
        
        lines.append("-" * 70)
        lines.append("")
        
        # 交易成本分析
        lines.append("-" * 70)
        lines.append("四、交易成本分析")
        lines.append("-" * 70)
        
        cost = result.get('trading_cost_analysis', {})
        if cost:
            lines.append(f"单边交易成本率: {cost['cost_rate']*100:.2f}%")
            lines.append(f"多头日均换手率: {cost['long_turnover']*100:.2f}%")
            lines.append(f"空头日均换手率: {cost['short_turnover']*100:.2f}%")
            lines.append(f"多头日均成本: {cost['long_daily_cost']*100:.4f}%")
            lines.append(f"空头日均成本: {cost['short_daily_cost']*100:.4f}%")
            lines.append(f"多空毛收益: {cost['long_short_gross_daily']*100:.4f}%")
            lines.append(f"多空净收益: {cost['long_short_net_daily']*100:.4f}%")
        
        lines.append("-" * 70)
        
        return "\n".join(lines)