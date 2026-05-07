"""
阶段B Pipeline入口模块

执行阶段B技术指标挖掘完整流程：
1. 加载OHLCV数据
2. 计算各类技术指标
3. 转换为因子格式
4. IC筛选
5. 因子去重
6. 输出结果
"""

import numpy as np
import pandas as pd
from typing import Dict, List, Optional, Tuple, Union
import json
import os
from datetime import datetime
import gzip
import warnings
import sys

# 添加项目根目录到路径
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from .trend_indicators import generate_trend_indicators
from .volatility_indicators import generate_volatility_indicators
from .momentum_indicators import generate_momentum_indicators
from .volume_indicators import generate_volume_indicators

# 尝试导入阶段A的去重和筛选组件
try:
    from stage_a.ic_filter import ICFilter
    from stage_a.deduplicator import FactorDeduplicator
    HAS_STAGE_A = True
except ImportError:
    HAS_STAGE_A = False
    print("[警告] 无法导入阶段A组件，IC筛选和去重功能将不可用")

warnings.filterwarnings('ignore')


class OHLCVDataLoader:
    """
    OHLCV数据加载器
    
    从cache目录加载价格数据，支持多种数据源
    """
    
    def __init__(self, cache_dir: Optional[str] = None):
        """
        初始化数据加载器
        
        Args:
            cache_dir: 缓存目录路径
        """
        self.cache_dir = cache_dir or os.path.join(PROJECT_ROOT, 'cache')
    
    def load_real_ohlcv_data(
        self,
        factor_data_path: Optional[str] = None,
        return_data_path: Optional[str] = None,
        max_assets: Optional[int] = None
    ) -> Dict[str, pd.DataFrame]:
        """
        从cache/factor_data加载真实OHLCV数据
        
        Args:
            factor_data_path: factor_data.json.gz路径（可选）
            return_data_path: return_data.json.gz路径（可选）
            max_assets: 最大加载资产数（用于测试，可选）
            
        Returns:
            股票OHLCV数据字典 {股票代码: DataFrame}
        """
        # 默认路径
        if factor_data_path is None:
            factor_data_path = os.path.join(self.cache_dir, 'factor_data', 'factor_data.json.gz')
        if return_data_path is None:
            return_data_path = os.path.join(self.cache_dir, 'factor_data', 'return_data.json.gz')
        
        print(f"[数据加载] 从真实数据加载: {factor_data_path}")
        
        # 加载factor_data
        if not os.path.exists(factor_data_path):
            raise FileNotFoundError(f"因子数据文件不存在: {factor_data_path}")
        
        with gzip.open(factor_data_path, 'rt') as f:
            factor_data = json.load(f)
        
        meta = factor_data.get('meta', {})
        data = factor_data.get('data', [])
        
        print(f"[数据加载] 元数据: {meta.get('n_days', 0)}天, {meta.get('n_assets', 0)}只资产")
        print(f"[数据加载] 数据记录数: {len(data)}")
        
        # 转换为DataFrame
        df = pd.DataFrame(data)
        
        # 限制资产数量（用于测试）
        if max_assets is not None:
            unique_assets = df['asset'].unique()[:max_assets]
            df = df[df['asset'].isin(unique_assets)]
            print(f"[数据加载] 限制加载资产数: {max_assets}")
        
        # 按资产分组，转换为 {stock_code: DataFrame}
        result = {}
        for asset, group in df.groupby('asset'):
            # 按日期排序
            group = group.sort_values('date').reset_index(drop=True)
            
            # 创建OHLCV DataFrame
            stock_df = pd.DataFrame({
                'date': pd.to_datetime(group['date']),
                'open': group['open'].values,
                'high': group['high'].values,
                'low': group['low'].values,
                'close': group['close'].values,
                'volume': 0  # 真实数据暂无volume字段
            })
            
            # 添加已有的技术指标
            if 'rsi_6' in group.columns:
                stock_df['rsi_6'] = group['rsi_6'].values
            if 'volume_ratio_5' in group.columns:
                stock_df['volume_ratio_5'] = group['volume_ratio_5'].values
            
            result[asset] = stock_df
        
        print(f"[数据加载] 成功加载 {len(result)} 只股票的真实OHLCV数据")
        
        return result
    
    def load_real_return_data(
        self,
        return_data_path: Optional[str] = None,
        max_assets: Optional[int] = None
    ) -> pd.DataFrame:
        """
        从cache/factor_data加载真实收益率数据
        
        Args:
            return_data_path: return_data.json.gz路径（可选）
            max_assets: 最大加载资产数（可选）
            
        Returns:
            收益率DataFrame
        """
        if return_data_path is None:
            return_data_path = os.path.join(self.cache_dir, 'factor_data', 'return_data.json.gz')
        
        if not os.path.exists(return_data_path):
            raise FileNotFoundError(f"收益数据文件不存在: {return_data_path}")
        
        print(f"[数据加载] 从真实数据加载收益: {return_data_path}")
        
        with gzip.open(return_data_path, 'rt') as f:
            return_data = json.load(f)
        
        data = return_data.get('data', [])
        df = pd.DataFrame(data)
        
        # 限制资产数量
        if max_assets is not None:
            unique_assets = df['asset'].unique()[:max_assets]
            df = df[df['asset'].isin(unique_assets)]
        
        print(f"[数据加载] 加载 {len(df)} 条收益数据记录")
        
        return df
        
    def load_from_factor_data(self) -> pd.DataFrame:
        """
        从因子数据缓存中提取价格信息
        
        Returns:
            包含OHLCV数据的DataFrame
        """
        factor_data_dir = os.path.join(self.cache_dir, 'factor_data')
        
        if not os.path.exists(factor_data_dir):
            raise FileNotFoundError(f"因子数据目录不存在: {factor_data_dir}")
        
        # 加载所有批次文件
        all_data = []
        batch_files = [f for f in os.listdir(factor_data_dir) if f.startswith('batch_') and f.endswith('.json.gz')]
        
        for batch_file in sorted(batch_files):
            filepath = os.path.join(factor_data_dir, batch_file)
            with gzip.open(filepath, 'rt') as f:
                batch_data = json.load(f)
            
            # 提取return_data中的价格信息
            if 'return_data' in batch_data:
                for item in batch_data['return_data']:
                    all_data.append({
                        'date': item['date'],
                        'asset': item['asset'],
                        'forward_return': item['forward_return']
                    })
        
        if not all_data:
            raise ValueError("无法从因子数据中提取有效数据")
        
        df = pd.DataFrame(all_data)
        print(f"[数据加载] 从因子缓存加载 {len(df)} 条记录")
        
        return df
    
    def load_mock_ohlcv(
        self,
        n_days: int = 500,
        n_stocks: int = 100,
        start_date: str = '2024-01-01'
    ) -> Dict[str, pd.DataFrame]:
        """
        生成模拟OHLCV数据（用于测试）
        
        Args:
            n_days: 天数
            n_stocks: 股票数
            start_date: 开始日期
            
        Returns:
            股票OHLCV数据字典 {股票代码: DataFrame}
        """
        dates = pd.date_range(start_date, periods=n_days, freq='B')  # 工作日
        
        result = {}
        for i in range(n_stocks):
            stock_code = f"{i + 1:06d}"
            
            # 基础价格
            base_price = 10 + np.random.random() * 50
            
            # 生成价格序列
            returns = np.random.randn(n_days) * 0.02  # 2%日波动
            prices = base_price * np.exp(np.cumsum(returns))
            
            # 生成OHLCV
            high = prices * (1 + np.abs(np.random.randn(n_days)) * 0.01)
            low = prices * (1 - np.abs(np.random.randn(n_days)) * 0.01)
            open_price = prices * (1 + np.random.randn(n_days) * 0.005)
            close = prices
            volume = np.random.randint(1000000, 10000000, n_days)
            
            df = pd.DataFrame({
                'date': dates,
                'open': open_price,
                'high': high,
                'low': low,
                'close': close,
                'volume': volume
            })
            
            result[stock_code] = df
        
        print(f"[数据加载] 生成模拟OHLCV数据: {n_stocks}只股票, {n_days}天")
        
        return result
    
    def load_real_ohlcv_from_api(self, stock_codes: List[str]) -> Dict[str, pd.DataFrame]:
        """
        从API加载真实OHLCV数据
        
        Args:
            stock_codes: 股票代码列表
            
        Returns:
            股票OHLCV数据字典
        """
        try:
            from real_data_loader import RealDataLoader
        except ImportError:
            print("[警告] 无法导入RealDataLoader，请确保项目路径正确")
            return {}
        
        loader = RealDataLoader()
        result = {}
        
        for code in stock_codes[:100]:  # 限制数量
            try:
                df = loader.get_stock_kline(code, days=500)
                if df is not None and len(df) > 0:
                    result[code] = df
            except Exception as e:
                print(f"[警告] 加载股票 {code} 数据失败: {e}")
        
        print(f"[数据加载] 从API加载 {len(result)} 只股票OHLCV数据")
        
        return result


class IndicatorGenerator:
    """
    技术指标批量生成器
    
    核心组件：将OHLCV数据转换为技术指标因子
    """
    
    # 指标分类配置
    INDICATOR_CATEGORIES = {
        'trend': {
            'function': generate_trend_indicators,
            'required_fields': ['high', 'low', 'close']
        },
        'volatility': {
            'function': generate_volatility_indicators,
            'required_fields': ['high', 'low', 'close']
        },
        'momentum': {
            'function': generate_momentum_indicators,
            'required_fields': ['high', 'low', 'close']
        },
        'volume': {
            'function': generate_volume_indicators,
            'required_fields': ['high', 'low', 'close', 'volume']
        }
    }
    
    def __init__(self, config: Optional[Dict] = None):
        """
        初始化指标生成器
        
        Args:
            config: 配置字典
        """
        self.config = config or {}
        
    def generate_for_stock(
        self,
        stock_data: pd.DataFrame,
        categories: Optional[List[str]] = None
    ) -> Dict[str, np.ndarray]:
        """
        为单只股票生成所有技术指标
        
        Args:
            stock_data: 股票OHLCV数据DataFrame
            categories: 要生成的指标类别列表
            
        Returns:
            指标字典 {指标名: 值数组}
        """
        categories = categories or list(self.INDICATOR_CATEGORIES.keys())
        
        all_indicators = {}
        
        for category in categories:
            if category not in self.INDICATOR_CATEGORIES:
                print(f"[警告] 未知的指标类别: {category}")
                continue
            
            cat_config = self.INDICATOR_CATEGORIES[category]
            func = cat_config['function']
            required = cat_config['required_fields']
            
            # 检查必要字段
            missing = [f for f in required if f not in stock_data.columns]
            if missing:
                print(f"[警告] 类别 {category} 缺少字段: {missing}")
                continue
            
            # 获取数据
            kwargs = {f: stock_data[f].values for f in required}
            
            # 生成指标
            try:
                indicators = func(**kwargs)
                all_indicators.update(indicators)
            except Exception as e:
                print(f"[警告] 生成 {category} 类指标失败: {e}")
        
        return all_indicators
    
    def generate_all(
        self,
        stock_data_dict: Dict[str, pd.DataFrame],
        categories: Optional[List[str]] = None
    ) -> pd.DataFrame:
        """
        为所有股票批量生成技术指标
        
        Args:
            stock_data_dict: 股票数据字典 {股票代码: DataFrame}
            categories: 要生成的指标类别
            
        Returns:
            指标DataFrame (date, asset, 各指标列)
        """
        all_records = []
        
        for stock_code, stock_df in stock_data_dict.items():
            indicators = self.generate_for_stock(stock_df, categories)
            
            # 构建记录
            for i, date in enumerate(stock_df['date']):
                record = {
                    'date': date.strftime('%Y-%m-%d') if hasattr(date, 'strftime') else str(date),
                    'asset': stock_code
                }
                
                # 添加指标值
                for indicator_name, values in indicators.items():
                    if i < len(values):
                        record[indicator_name] = values[i]
                
                all_records.append(record)
        
        df = pd.DataFrame(all_records)
        
        # 统计
        indicator_cols = [c for c in df.columns if c not in ['date', 'asset']]
        print(f"[指标生成] 生成 {len(indicator_cols)} 个技术指标")
        print(f"[指标生成] 覆盖 {len(stock_data_dict)} 只股票, {len(df)} 条记录")
        
        return df


class StageBPipeline:
    """
    阶段B流水线
    
    执行流程：
    1. 加载OHLCV数据
    2. 生成技术指标
    3. 格式化为因子数据
    4. IC筛选（可选）
    5. 去重（可选）
    6. 输出结果
    """
    
    DEFAULT_CONFIG = {
        'use_mock_data': True,  # 默认使用模拟数据
        'n_days': 500,
        'n_stocks': 100,
        'start_date': '2024-01-01',
        'categories': ['trend', 'volatility', 'momentum', 'volume'],
        'ic_threshold': 0.03,
        'ir_threshold': 0.5,
        'tstat_threshold': 2.0,
        'correlation_threshold': 0.8,
        'min_records': 100,
        'keep_strategy': 'highest_ic',
        'verbose': True
    }
    
    def __init__(
        self,
        config: Optional[Dict] = None,
        output_dir: Optional[str] = None
    ):
        """
        初始化Pipeline
        
        Args:
            config: 配置字典
            output_dir: 输出目录
        """
        self.config = config or self.DEFAULT_CONFIG.copy()
        self.output_dir = output_dir or os.path.join(
            PROJECT_ROOT, 'versions', 'factor_mining', 'output'
        )
        
        # 初始化组件
        self.data_loader = OHLCVDataLoader()
        self.indicator_generator = IndicatorGenerator()
        
        # 初始化筛选和去重组件（如果可用）
        if HAS_STAGE_A:
            self.ic_filter = ICFilter(
                ic_threshold=self.config['ic_threshold'],
                ir_threshold=self.config['ir_threshold'],
                tstat_threshold=self.config['tstat_threshold'],
                min_records=self.config['min_records']
            )
            self.deduplicator = FactorDeduplicator(
                correlation_threshold=self.config['correlation_threshold'],
                keep_strategy=self.config['keep_strategy']
            )
        else:
            self.ic_filter = None
            self.deduplicator = None
        
        # 结果存储
        self.results = {
            'indicators': None,
            'filtered': None,
            'deduplicated': None,
            'factor_summary': {}
        }
    
    def load_ohlcv_data(self, max_assets: Optional[int] = None) -> Dict[str, pd.DataFrame]:
        """
        加载OHLCV数据
        
        Args:
            max_assets: 最大加载资产数（用于测试）
            
        Returns:
            股票数据字典
        """
        if self.config['use_mock_data']:
            print("[数据加载] 使用模拟数据...")
            return self.data_loader.load_mock_ohlcv(
                n_days=self.config['n_days'],
                n_stocks=self.config['n_stocks'],
                start_date=self.config['start_date']
            )
        else:
            # 尝试加载真实数据，使用 n_stocks 限制资产数
            print("[数据加载] 使用真实数据...")
            # 使用配置中的 n_stocks 或传入的 max_assets
            limit_assets = self.config.get('n_stocks') if self.config.get('n_stocks') < 500 else max_assets
            try:
                return self.data_loader.load_real_ohlcv_data(max_assets=limit_assets)
            except Exception as e:
                print(f"[警告] 加载真实数据失败: {e}")
                print("[数据加载] 回退使用模拟数据...")
                return self.data_loader.load_mock_ohlcv(
                    n_days=self.config['n_days'],
                    n_stocks=self.config['n_stocks'],
                    start_date=self.config['start_date']
                )
    
    def load_return_data(self, max_assets: Optional[int] = None) -> pd.DataFrame:
        """
        加载收益率数据
        
        Args:
            max_assets: 最大加载资产数
            
        Returns:
            收益率DataFrame
        """
        if self.config['use_mock_data']:
            return None  # 模拟数据模式返回None，由generate_forward_returns生成
        else:
            try:
                return self.data_loader.load_real_return_data(max_assets=max_assets)
            except Exception as e:
                print(f"[警告] 加载收益数据失败: {e}")
                return None
    
    def generate_indicators(
        self,
        stock_data: Dict[str, pd.DataFrame]
    ) -> pd.DataFrame:
        """
        生成技术指标
        
        Args:
            stock_data: 股票数据字典
            
        Returns:
            指标DataFrame
        """
        return self.indicator_generator.generate_all(
            stock_data,
            categories=self.config['categories']
        )
    
    def format_as_factors(self, indicators_df: pd.DataFrame) -> Dict[str, pd.Series]:
        """
        将指标格式化为因子数据
        
        Args:
            indicators_df: 指标DataFrame
            
        Returns:
            因子数据字典 {因子名: Series}
        """
        factor_cols = [c for c in indicators_df.columns if c not in ['date', 'asset']]
        
        factors = {}
        for col in factor_cols:
            # 创建MultiIndex Series
            factor_series = indicators_df.set_index(['date', 'asset'])[col]
            factors[col] = factor_series
        
        print(f"[格式化] 转换 {len(factors)} 个因子")
        
        return factors
    
    def generate_forward_returns(
        self,
        stock_data: Dict[str, pd.DataFrame],
        forward_days: int = 3
    ) -> pd.DataFrame:
        """
        生成未来收益数据（用于IC计算）
        
        Args:
            stock_data: 股票数据字典
            forward_days: 预测天数
            
        Returns:
            收益DataFrame
        """
        returns_records = []
        
        for stock_code, df in stock_data.items():
            close = df['close'].values
            dates = df['date'].values
            
            for i in range(len(df) - forward_days):
                if close[i + forward_days] > 0 and close[i] > 0:
                    forward_return = (close[i + forward_days] / close[i]) - 1
                    
                    returns_records.append({
                        'date': dates[i],
                        'asset': stock_code,
                        'forward_return': forward_return
                    })
        
        return pd.DataFrame(returns_records)
    
    def calculate_ic(
        self,
        factors: Dict[str, pd.Series],
        returns: pd.DataFrame
    ) -> Dict[str, Dict]:
        """
        计算因子IC
        
        Args:
            factors: 因子数据字典
            returns: 收益DataFrame
            
        Returns:
            IC统计字典 {因子名: {ic_mean, ic_std, ic_ir, t_stat}}
        """
        # 确保日期列格式一致
        returns_df = returns.copy()
        if 'date' in returns_df.columns:
            # 统一转换为字符串格式
            returns_df['date'] = returns_df['date'].astype(str).str[:10]
        if 'asset' in returns_df.columns:
            returns_df['asset'] = returns_df['asset'].astype(str)
        
        # 处理收益列名兼容性：支持 forward_return 和 forward_return_1d
        return_col = None
        for col in ['forward_return', 'forward_return_1d', 'forward_return_1']:
            if col in returns_df.columns:
                return_col = col
                break
        
        if return_col is None:
            print(f"[错误] 收益数据缺少收益列")
            print(f"[错误] 收益数据列: {returns_df.columns.tolist()}")
            return {}
        
        if return_col != 'forward_return':
            returns_df['forward_return'] = returns_df[return_col]
        
        try:
            returns_series = returns_df.set_index(['date', 'asset'])['forward_return']
        except KeyError as e:
            print(f"[错误] 收益数据缺少必要列: {e}")
            print(f"[错误] 收益数据列: {returns_df.columns.tolist()}")
            return {}
        
        print(f"[IC计算] 开始计算 {len(factors)} 个因子IC")
        print(f"[IC计算] 收益数据: {len(returns_df)} 条记录, 列: {returns_df.columns.tolist()}")
        if len(returns_df) > 0:
            print(f"[IC计算] 收益数据日期范围: {returns_df['date'].min()} ~ {returns_df['date'].max()}")
            print(f"[IC计算] 收益数据资产数: {returns_df['asset'].nunique()}")
        print(f"[IC计算] min_records配置: {self.config.get('min_records', 'N/A')}")
        
        ic_stats = {}
        
        for factor_name, factor_series in factors.items():
            # 添加调试：检查因子索引
            if len(ic_stats) == 0:  # 只打印第一个因子的调试信息
                print(f"[IC计算调试] 第一个因子 {factor_name}:")
                print(f"  因子数据点数: {len(factor_series)}")
                if len(factor_series) > 0:
                    idx = factor_series.index
                    print(f"  因子索引类型: {type(idx)}")
                    if hasattr(idx, 'levels'):
                        print(f"  因子索引levels: {idx.names}")
                        dates_in_factor = idx.get_level_values('date').unique() if 'date' in idx.names else []
                        print(f"  因子日期范围: {dates_in_factor[:3].tolist()}...{dates_in_factor[-3:].tolist() if len(dates_in_factor) > 3 else ''}")
            
            # 合并数据
            combined = pd.DataFrame({
                'factor': factor_series,
                'return': returns_series
            }).dropna()
            
            if len(ic_stats) == 0:  # 只打印第一个因子
                print(f"  合并后数据点数: {len(combined)}")
            
            if len(combined) < self.config['min_records']:
                continue
            
            # 计算每日IC
            dates = combined.index.get_level_values('date').unique()
            daily_ics = []
            
            for date in dates:
                day_data = combined.loc[date]
                if len(day_data) > 1:
                    ic = day_data['factor'].corr(day_data['return'], method='spearman')
                    if not np.isnan(ic):
                        daily_ics.append(ic)
            
            if len(daily_ics) >= 10:
                ic_mean = np.mean(daily_ics)
                ic_std = np.std(daily_ics)
                ic_ir = ic_mean / ic_std if ic_std > 0 else 0
                t_stat = ic_mean * np.sqrt(len(daily_ics)) / ic_std if ic_std > 0 else 0
                
                ic_stats[factor_name] = {
                    'ic_mean': ic_mean,
                    'ic_std': ic_std,
                    'ic_ir': ic_ir,
                    't_stat': t_stat,
                    'n_days': len(daily_ics)
                }
        
        print(f"[IC计算] 完成 {len(ic_stats)} 个因子IC计算")
        
        return ic_stats
    
    def filter_factors(
        self,
        factors: Dict[str, pd.Series],
        ic_stats: Dict[str, Dict]
    ) -> Dict[str, pd.Series]:
        """
        筛选因子
        
        Args:
            factors: 因子数据字典
            ic_stats: IC统计字典
            
        Returns:
            筛选后的因子字典
        """
        if self.ic_filter is not None:
            # 使用阶段A的筛选器
            filtered_factors = {}
            for name, stats in ic_stats.items():
                if self._passes_thresholds(stats):
                    filtered_factors[name] = factors[name]
        else:
            # 手动筛选
            filtered_factors = {}
            for name, stats in ic_stats.items():
                if self._passes_thresholds(stats):
                    filtered_factors[name] = factors[name]
        
        print(f"[筛选] 保留 {len(filtered_factors)} 个因子")
        
        return filtered_factors
    
    def _passes_thresholds(self, stats: Dict) -> bool:
        """检查IC是否通过阈值"""
        return (
            abs(stats['ic_mean']) >= self.config['ic_threshold'] and
            abs(stats['ic_ir']) >= self.config['ir_threshold'] and
            abs(stats['t_stat']) >= self.config['tstat_threshold']
        )
    
    def deduplicate_factors(
        self,
        factors: Dict[str, pd.Series]
    ) -> Dict[str, pd.Series]:
        """
        去重因子
        
        Args:
            factors: 因子数据字典
            
        Returns:
            去重后的因子字典
        """
        if self.deduplicator is not None and len(factors) > 0:
            return self.deduplicator.deduplicate(factors)
        else:
            print("[提示] 去重功能不可用或无需去重")
            return factors
    
    def save_results(self, output_path: Optional[str] = None):
        """
        保存结果
        
        Args:
            output_path: 输出路径
        """
        output_path = output_path or self.output_dir
        
        if not os.path.exists(output_path):
            os.makedirs(output_path)
        
        # 保存因子摘要
        summary_path = os.path.join(output_path, 'stage_b_factor_summary.json')
        
        summary = {
            'timestamp': datetime.now().isoformat(),
            'config': self.config,
            'n_indicators': len(self.results.get('factor_summary', {})),
            'factor_stats': self.results.get('factor_summary', {})
        }
        
        with open(summary_path, 'w') as f:
            json.dump(summary, f, indent=2, default=str)
        
        print(f"[保存] 结果已保存到: {output_path}")
    
    def run(
        self,
        stock_data: Optional[Dict[str, pd.DataFrame]] = None,
        save_output: bool = True
    ) -> Dict:
        """
        执行完整流程
        
        Args:
            stock_data: 可选的股票数据（如不提供则自动加载）
            save_output: 是否保存输出
            
        Returns:
            结果字典
        """
        print("=" * 60)
        print("阶段B：技术指标挖掘")
        print("=" * 60)
        
        # 1. 加载数据
        print("\n[步骤1] 加载OHLCV数据...")
        if stock_data is None:
            stock_data = self.load_ohlcv_data()
        
        # 2. 生成指标
        print("\n[步骤2] 生成技术指标...")
        indicators_df = self.generate_indicators(stock_data)
        self.results['indicators'] = indicators_df
        
        # 3. 格式化为因子
        print("\n[步骤3] 格式化因子数据...")
        factors = self.format_as_factors(indicators_df)
        
        # 4. 加载或生成未来收益
        print("\n[步骤4] 加载/生成未来收益...")
        loaded_assets = set(stock_data.keys())  # 获取已加载的资产列表
        if not self.config['use_mock_data']:
            # 真实数据模式：尝试加载真实收益数据
            returns = self.load_return_data()
            if returns is None or len(returns) == 0:
                print("[提示] 真实收益数据不可用，从价格数据计算...")
                returns = self.generate_forward_returns(stock_data)
            else:
                # 过滤收益数据，只保留已加载资产的记录
                returns['asset'] = returns['asset'].astype(str)
                returns = returns[returns['asset'].isin(loaded_assets)]
                print(f"[数据加载] 使用真实收益数据: {len(returns)} 条记录 (匹配 {returns['asset'].nunique()} 只资产)")
                if len(returns) == 0:
                    print("[警告] 收益数据与OHLCV资产不匹配，从价格数据计算...")
                    returns = self.generate_forward_returns(stock_data)
        else:
            # 模拟数据模式：从价格数据计算
            returns = self.generate_forward_returns(stock_data)
        
        # 5. 计算IC
        print("\n[步骤5] 计算因子IC...")
        if returns is None or len(returns) == 0:
            print("[警告] 收益数据为空，跳过IC计算")
            ic_stats = {}
        else:
            ic_stats = self.calculate_ic(factors, returns)
        self.results['factor_summary'] = ic_stats
        
        # 6. 筛选因子
        print("\n[步骤6] IC筛选...")
        filtered_factors = self.filter_factors(factors, ic_stats)
        self.results['filtered'] = filtered_factors
        
        # 7. 去重
        print("\n[步骤7] 因子去重...")
        deduplicated_factors = self.deduplicate_factors(filtered_factors)
        self.results['deduplicated'] = deduplicated_factors
        
        # 8. 保存结果
        if save_output:
            print("\n[步骤8] 保存结果...")
            self.save_results()
        
        # 总结
        print("\n" + "=" * 60)
        print("执行完成!")
        print(f"  - 生成指标: {len(factors)} 个")
        print(f"  - IC筛选保留: {len(filtered_factors)} 个")
        print(f"  - 去重后保留: {len(deduplicated_factors)} 个")
        
        # 打印Top因子
        if ic_stats:
            sorted_stats = sorted(ic_stats.items(), key=lambda x: abs(x[1]['ic_mean']), reverse=True)
            print("\nTop 5 因子 (按IC绝对值):")
            for i, (name, stats) in enumerate(sorted_stats[:5]):
                print(f"  {i + 1}. {name}: IC={stats['ic_mean']:.4f}, IR={stats['ic_ir']:.3f}")
        
        print("=" * 60)
        
        return self.results


def main():
    """主入口函数"""
    import argparse
    
    parser = argparse.ArgumentParser(description='阶段B技术指标挖掘')
    parser.add_argument('--mock', action='store_true', help='使用模拟数据')
    parser.add_argument('--days', type=int, default=500, help='数据天数')
    parser.add_argument('--stocks', type=int, default=100, help='股票数量')
    parser.add_argument('--ic-threshold', type=float, default=0.03, help='IC阈值')
    parser.add_argument('--output', type=str, default=None, help='输出目录')
    
    args = parser.parse_args()
    
    config = {
        'use_mock_data': args.mock,
        'n_days': args.days,
        'n_stocks': args.stocks,
        'ic_threshold': args.ic_threshold
    }
    
    pipeline = StageBPipeline(config=config, output_dir=args.output)
    results = pipeline.run(save_output=True)
    
    return results


if __name__ == '__main__':
    main()