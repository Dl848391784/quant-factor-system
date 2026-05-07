"""
阶段A真实数据加载器

从cache目录读取真实因子数据
"""

import gzip
import json
import pandas as pd
from typing import Dict, Tuple, Optional, List
import os
import logging

logger = logging.getLogger(__name__)

CACHE_BASE = "/home/admin/.openclaw/workspace/yunzhou/factor_ic_analyzer/cache"


class RealFactorLoader:
    """真实因子数据加载器"""
    
    FACTOR_FILES = {
        'rsi_6': 'factor_data/factor_data.json.gz',
        'volume_ratio_5': 'factor_data/factor_data.json.gz',
        'kdj_j': 'kdj_j/kdj_j_history.json.gz',
        'bollinger_pb': 'bollinger_pb/bollinger_pb_history.json.gz',
        'turnover_rate': 'factor_data/turnover_rate_data.json.gz',
    }
    
    RETURN_FILE = 'factor_data/return_data.json.gz'
    
    def __init__(self, cache_base: str = CACHE_BASE):
        """
        初始化加载器
        
        Args:
            cache_base: cache目录基础路径
        """
        self.cache_base = cache_base
        self._loaded_data: Dict[str, pd.DataFrame] = {}
        self._meta_info: Dict[str, Dict] = {}
        
    def load_gz_json(self, filepath: str) -> Dict:
        """
        加载gzip压缩的JSON文件
        
        Args:
            filepath: 相对于cache_base的路径
            
        Returns:
            JSON数据字典
        """
        full_path = os.path.join(self.cache_base, filepath)
        
        if not os.path.exists(full_path):
            raise FileNotFoundError(f"数据文件不存在: {full_path}")
        
        with gzip.open(full_path, 'rt', encoding='utf-8') as f:
            return json.load(f)
    
    def load_factor_data(self, factor_name: str) -> pd.DataFrame:
        """
        加载单个因子数据
        
        Args:
            factor_name: 因子名称
            
        Returns:
            DataFrame with columns: date, asset, value
        """
        if factor_name in self._loaded_data:
            return self._loaded_data[factor_name]
        
        filepath = self.FACTOR_FILES.get(factor_name)
        if not filepath:
            raise ValueError(f"未知的因子: {factor_name}")
        
        raw_data = self.load_gz_json(filepath)
        
        # 保存元信息
        if 'meta' in raw_data:
            self._meta_info[factor_name] = raw_data['meta']
        
        # 直接从data列表构建DataFrame（避免records临时list）
        data_list = raw_data['data']
        dates = []
        assets = []
        values = []
        for item in data_list:
            value = item.get(factor_name)
            if value is not None:
                dates.append(item['date'])
                assets.append(item['asset'])
                values.append(value)
        
        # 直接构建DataFrame，使用float32
        df = pd.DataFrame({
            'date': pd.to_datetime(dates),
            'asset': assets,
            'value': pd.array(values, dtype='float32')
        })
        
        # 不缓存，避免内存堆积
        # self._loaded_data[factor_name] = df
        
        # 释放raw_data
        del raw_data, data_list, dates, assets, values
        
        # 打印加载信息
        if len(df) > 0:
            unique_dates = df['date'].nunique()
            unique_assets = df['asset'].nunique()
            logger.info(f"[数据加载] 真实因子 {factor_name}: {unique_assets}只股票, {unique_dates}天")
        
        return df
    
    def load_returns(self, return_type: str = 'forward_return_1d') -> pd.DataFrame:
        """
        加载收益率数据
        
        Args:
            return_type: 收益率类型
            
        Returns:
            DataFrame with columns: date, asset, return
        """
        raw_data = self.load_gz_json(self.RETURN_FILE)
        
        # 保存元信息
        if 'meta' in raw_data:
            self._meta_info['returns'] = raw_data['meta']
        
        records = []
        for item in raw_data['data']:
            value = item.get(return_type)
            if value is not None:
                records.append({
                    'date': item['date'],
                    'asset': item['asset'],
                    'return': value
                })
        
        df = pd.DataFrame(records)
        if len(df) > 0:
            df['date'] = pd.to_datetime(df['date'])
        
        return df
    
    def get_factor_meta(self, factor_name: str) -> Optional[Dict]:
        """获取因子元信息"""
        return self._meta_info.get(factor_name)
    
    def prepare_panel_data(
        self,
        factor_names: Optional[List[str]] = None,
        return_type: str = 'forward_return_1d',
        align_dates: bool = True,
        verbose: bool = True,
        max_assets: Optional[int] = None
    ) -> Tuple[Dict[str, pd.Series], pd.Series]:
        """
        准备面板数据供阶段A使用
        
        Args:
            factor_names: 要加载的因子列表，默认5因子
            return_type: 收益率类型
            align_dates: 是否对齐日期（取交集）
            verbose: 是否打印详细信息
            max_assets: 最大资产数限制（避免OOM）
            
        Returns:
            factor_data: Dict[因子名, pd.Series] - 因子值序列 (date, asset) -> value
            returns: pd.Series - 收益率序列 (date, asset) -> return
        """
        if factor_names is None:
            factor_names = ['rsi_6', 'volume_ratio_5', 'kdj_j', 'bollinger_pb', 'turnover_rate']
        
        # 加载所有因子
        factor_dfs = {}
        for name in factor_names:
            try:
                factor_dfs[name] = self.load_factor_data(name)
            except Exception as e:
                logger.warning(f"跳过因子 {name}: {e}")
        
        # 加载收益率
        returns_df = self.load_returns(return_type)
        
        if verbose:
            print(f"[真实数据] 加载完成:")
            print(f"  - 因子数: {len(factor_dfs)}")
            print(f"  - 因子列表: {list(factor_dfs.keys())}")
        
        # 构建Series，直接设置MultiIndex（避免pivot/stack的内存峰值）
        factor_data = {}
        for name, df in factor_dfs.items():
            if len(df) == 0:
                continue
            # 直接设置MultiIndex，不做pivot/stack
            series = df.set_index(['date', 'asset'])['value']
            # 转为float32节省内存
            series = series.astype('float32')
            factor_data[name] = series
            # 释放df内存
            del df
        
        # 收益率同样处理
        if len(returns_df) > 0:
            returns = returns_df.set_index(['date', 'asset'])['return'].astype('float32')
        else:
            returns = pd.Series(dtype='float32')
        
        # 释放中间变量
        del factor_dfs, returns_df
        
        # 对齐索引
        if align_dates and len(factor_data) > 0 and len(returns) > 0:
            common_index = None
            for s in factor_data.values():
                if common_index is None:
                    common_index = s.index
                else:
                    common_index = common_index.intersection(s.index)
            common_index = common_index.intersection(returns.index)
            
            factor_data = {k: v.loc[common_index] for k, v in factor_data.items()}
            returns = returns.loc[common_index]
            
            if verbose:
                print(f"  - 对齐后样本数: {len(returns)}")
                # 显示日期范围
                dates = common_index.get_level_values('date').unique()
                if len(dates) > 0:
                    print(f"  - 日期范围: {dates.min().strftime('%Y-%m-%d')} ~ {dates.max().strftime('%Y-%m-%d')}")
        
        return factor_data, returns


# 快速测试函数
def test_real_factor_loader():
    """测试真实数据加载"""
    loader = RealFactorLoader()
    
    # 测试单个因子
    print("测试单个因子加载...")
    df = loader.load_factor_data('rsi_6')
    print(f"RSI_6: {len(df)}条记录")
    
    # 测试完整面板数据
    print("\n测试面板数据准备...")
    factor_data, returns = loader.prepare_panel_data(verbose=True)
    
    print(f"\n因子数据:")
    for name, series in factor_data.items():
        print(f"  {name}: {len(series)}样本")
    
    print(f"\n收益率: {len(returns)}样本")
    
    return factor_data, returns


if __name__ == '__main__':
    test_real_factor_loader()