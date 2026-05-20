#!/usr/bin/env python3.10
"""
主力净流入和流通市值数据获取模块（东方财富 API 版）

数据源：东方财富网 API（直接使用，不依赖 AKShare）

功能：
- fetch_main_inflow_eastmoney(): 获取单只股票主力资金流向
- fetch_main_inflow_history(): 获取历史主力资金数据
- fetch_float_market_cap(): 获取流通市值
- batch_fetch_main_inflow(): 批量获取（并发优化）
- batch_fetch_main_inflow_history(): 批量获取历史数据

并发策略：
- 2线程并发
- 批次大小：100（每线程50只）
- 批次间延迟：2秒
- 股票间延迟：0.1秒
- 内存优化：category 类型
- 重试机制：3次，每次等待5秒

东方财富 API 接口：
- 主力资金: http://push2.eastmoney.com/api/qt/stock/fflow/kline/get
- 流通市值: http://push2.eastmoney.com/api/qt/stock/get

作者: 云舟
日期: 2026-04-06
"""

import pandas as pd
import numpy as np
import requests
import time
import json
import gzip
import gc
import os
import threading
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from concurrent.futures import ThreadPoolExecutor, as_completed
import warnings
warnings.filterwarnings('ignore')

# ============================================================
# 配置常量
# ============================================================

# 缓存路径
CACHE_DIR = os.path.expanduser('~/projects/factor_ic_analyzer/cache')
FACTOR_CACHE_DIR = os.path.join(CACHE_DIR, 'factor_data')
MAIN_INFLOW_CACHE_DIR = os.path.join(CACHE_DIR, 'main_inflow')

# 东方财富 API 端点（使用 datacenter-web 接口，push2 接口已不可用）
EASTMONEY_MAIN_INFLOW_URL = 'https://datacenter-web.eastmoney.com/api/data/v1/get'  # 主力资金（reportName=RPT_DMSK_TS_STOCKNEW）
EASTMONEY_STOCK_INFO_URL = 'https://datacenter-web.eastmoney.com/api/data/v1/get'  # 流通市值（reportName=RPT_VALUEANALYSIS_DET）
# 历史K线/主力资金数据使用 push2his（该服务器可用）
EASTMONEY_HISTORY_URL = 'https://push2his.eastmoney.com/api/qt/stock/kline/get'  # 历史数据备用

# 请求配置
REQUEST_TIMEOUT = 30
REQUEST_RETRIES = 3
REQUEST_DELAY = 2.0  # 批次间延迟（避免API限流）

# 批量获取配置
BATCH_SIZE = 100  # 每批股票数量（每线程50只）
MAX_WORKERS = 2   # 并发线程数


class MainInflowDataFetcher:
    """主力净流入和流通市值数据获取器（东方财富 API）"""
    
    def __init__(
        self,
        timeout: int = REQUEST_TIMEOUT,
        retries: int = REQUEST_RETRIES,
        enable_cache: bool = True
    ):
        """
        初始化数据获取器
        
        Args:
            timeout: 请求超时时间（秒）
            retries: 失败重试次数
            enable_cache: 启用缓存
        """
        self.timeout = timeout
        self.retries = retries
        self.enable_cache = enable_cache
        self._lock = threading.Lock()
        self._request_count = 0
        
        # 初始化 session
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Accept': '*/*',
            'Referer': 'http://data.eastmoney.com/'
        })
        
        # 确保缓存目录存在
        if self.enable_cache:
            os.makedirs(MAIN_INFLOW_CACHE_DIR, exist_ok=True)
    
    # ============================================================
    # 东方财富 API 数据获取
    # ============================================================
    
    def _get_secid(self, stock_code: str) -> Optional[str]:
        """
        获取东方财富 secid 格式
        
        Args:
            stock_code: 股票代码
            
        Returns:
            secid 字符串，如 "1.600000"（沪市）或 "0.000001"（深市）
        """
        if stock_code.startswith('60'):
            return f'1.{stock_code}'
        elif stock_code.startswith('00'):
            return f'0.{stock_code}'
        elif stock_code.startswith('30'):
            return f'0.{stock_code}'  # 创业板
        elif stock_code.startswith('68'):
            return f'1.{stock_code}'  # 科创板
        return None
    
    def fetch_main_inflow_eastmoney(self, stock_code: str) -> Optional[Dict]:
        """
        从东方财富网获取单只股票的主力资金流向数据
        
        使用 datacenter-web.eastmoney.com 接口（reportName=RPT_DMSK_TS_STOCKNEW）
        
        主力净流入定义：PRIME_INFLOW（API直接返回）
        
        Args:
            stock_code: 股票代码
            
        Returns:
            {'code': str, 'main_net_inflow': float, 'main_net_inflow_ratio': float,
             'super_net_inflow': float, 'big_net_inflow': float, 
             'medium_net_inflow': float, 'small_net_inflow': float}
            或 None
        """
        url = EASTMONEY_MAIN_INFLOW_URL
        
        # 使用新的 datacenter-web 接口参数格式
        params = {
            'reportName': 'RPT_DMSK_TS_STOCKNEW',
            'columns': 'ALL',
            'pageSize': 500,
            'quoteColumns': 'f2~01~SECURITY_CODE~CLOSE_PRICE,f8~01~SECURITY_CODE~TURNOVERRATE,f3~01~SECURITY_CODE~CHANGE_RATE,f9~01~SECURITY_CODE~PE_DYNAMIC',
            'token': '894050c76af8597a853f5b408b759f5d',
            'sortColumns': 'SECURITY_CODE',
            'sortTypes': '1',
            'filter': f'(SECURITY_CODE="{stock_code}")'
        }
        
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Referer': 'https://data.eastmoney.com/'
        }
        
        for attempt in range(self.retries):
            try:
                if attempt > 0:
                    time.sleep(0.5 * attempt)
                
                response = self.session.get(url, params=params, headers=headers, timeout=self.timeout)
                response.raise_for_status()
                
                data = response.json()
                
                # 检查返回数据结构（datacenter-web 接口返回格式）
                if not data or 'result' not in data:
                    return None
                
                result = data['result']
                if not result or 'data' not in result or not result['data']:
                    return None
                
                # 获取第一条数据
                record = result['data'][0]
                
                # 解析字段（使用新的字段名）
                main_net_inflow = float(record.get('PRIME_INFLOW', 0) or 0)  # 主力净流入（元）
                super_inflow = float(record.get('SUPERDEAL_INFLOW', 0) or 0)  # 特大单流入
                super_outflow = float(record.get('SUPERDEAL_OUTFLOW', 0) or 0)  # 特大单流出
                big_inflow = float(record.get('BIGDEAL_INFLOW', 0) or 0)  # 大单流入
                big_outflow = float(record.get('BIGDEAL_OUTFLOW', 0) or 0)  # 大单流出
                
                # 计算净流入
                super_net_inflow = super_inflow - super_outflow  # 特大单净流入
                big_net_inflow = big_inflow - big_outflow  # 大单净流入
                
                # 中单和小单数据（如果有的话）
                medium_inflow = 0
                small_inflow = 0
                
                # 获取日期
                trade_date = record.get('TRADE_DATE', '')
                if trade_date:
                    date_str = trade_date[:10] if len(trade_date) >= 10 else trade_date
                else:
                    date_str = datetime.now().strftime('%Y-%m-%d')
                
                return {
                    'code': stock_code,
                    'main_net_inflow': main_net_inflow,  # 主力净流入（元）
                    'main_net_inflow_ratio': 0,  # 占比需要流通市值计算
                    'super_net_inflow': super_net_inflow,  # 特大单净流入（元）
                    'big_net_inflow': big_net_inflow,  # 大单净流入（元）
                    'medium_net_inflow': medium_inflow,  # 中单净流入（元）
                    'small_net_inflow': small_inflow,  # 小单净流入（元）
                    'date': date_str
                }
                
            except Exception as e:
                if attempt < self.retries - 1:
                    continue
                else:
                    return None
        
        return None
    
    def fetch_main_inflow_history(
        self,
        stock_code: str,
        days: int = 500
    ) -> Optional[pd.DataFrame]:
        """
        获取单只股票的历史主力资金流向数据
        
        使用 datacenter-web.eastmoney.com 接口获取历史数据
        
        Args:
            stock_code: 股票代码
            days: 获取天数
            
        Returns:
            DataFrame（包含日期、主力净流入等），或 None
            
        DataFrame 列：
            - date: 日期
            - asset: 股票代码
            - main_net_inflow: 主力净流入（元）
            - super_net_inflow: 特大单净流入（元）
            - big_net_inflow: 大单净流入（元）
            - medium_net_inflow: 中单净流入（元）
            - small_net_inflow: 小单净流入（元）
        """
        url = EASTMONEY_MAIN_INFLOW_URL
        
        # 使用新的 datacenter-web 接口参数格式
        # 通过 pageSize 获取多条历史记录
        params = {
            'reportName': 'RPT_DMSK_TS_STOCKNEW',
            'columns': 'ALL',
            'pageSize': days,  # 获取历史天数
            'quoteColumns': 'f2~01~SECURITY_CODE~CLOSE_PRICE,f8~01~SECURITY_CODE~TURNOVERRATE,f3~01~SECURITY_CODE~CHANGE_RATE,f9~01~SECURITY_CODE~PE_DYNAMIC',
            'token': '894050c76af8597a853f5b408b759f5d',
            'sortColumns': 'TRADE_DATE',
            'sortTypes': '-1',  # 按日期倒序
            'filter': f'(SECURITY_CODE="{stock_code}")'
        }
        
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Referer': 'https://data.eastmoney.com/'
        }
        
        for attempt in range(self.retries):
            try:
                if attempt > 0:
                    time.sleep(1.0 * attempt)
                
                response = self.session.get(url, params=params, headers=headers, timeout=self.timeout)
                response.raise_for_status()
                
                data = response.json()
                
                # 检查返回数据结构（datacenter-web 接口返回格式）
                if not data or 'result' not in data:
                    return None
                
                result = data['result']
                if not result or 'data' not in result or not result['data']:
                    return None
                
                # 解析历史数据
                records = []
                for record in result['data']:
                    try:
                        # 获取日期
                        trade_date = record.get('TRADE_DATE', '')
                        if trade_date:
                            date_str = trade_date[:10] if len(trade_date) >= 10 else trade_date
                        else:
                            continue
                        
                        # 解析主力资金数据
                        main_net_inflow = float(record.get('PRIME_INFLOW', 0) or 0)
                        super_inflow = float(record.get('SUPERDEAL_INFLOW', 0) or 0)
                        super_outflow = float(record.get('SUPERDEAL_OUTFLOW', 0) or 0)
                        big_inflow = float(record.get('BIGDEAL_INFLOW', 0) or 0)
                        big_outflow = float(record.get('BIGDEAL_OUTFLOW', 0) or 0)
                        
                        # 计算净流入
                        super_net_inflow = super_inflow - super_outflow
                        big_net_inflow = big_inflow - big_outflow
                        
                        records.append({
                            'date': date_str,
                            'asset': stock_code,
                            'main_net_inflow': main_net_inflow,
                            'super_net_inflow': super_net_inflow,
                            'big_net_inflow': big_net_inflow,
                            'medium_net_inflow': 0,
                            'small_net_inflow': 0
                        })
                    except (ValueError, TypeError):
                        continue
                
                if not records:
                    return None
                
                df = pd.DataFrame(records)
                df['date'] = pd.to_datetime(df['date'])
                
                # 内存优化：使用category类型
                df['asset'] = df['asset'].astype('category')
                
                return df.sort_values('date').reset_index(drop=True)
                
            except Exception as e:
                if attempt < self.retries - 1:
                    continue
                else:
                    return None
        
        return None
    
    def fetch_float_market_cap(self, stock_code: str) -> Optional[float]:
        """
        获取流通市值
        
        使用 datacenter-web.eastmoney.com 接口（reportName=RPT_VALUEANALYSIS_DET）
        直接获取流通市值字段 NOTLIMITED_MARKETCAP_A
        
        Args:
            stock_code: 股票代码
            
        Returns:
            流通市值（元），或 None
        """
        url = EASTMONEY_STOCK_INFO_URL
        
        # 使用新的 datacenter-web 接口参数格式
        params = {
            'reportName': 'RPT_VALUEANALYSIS_DET',
            'columns': 'ALL',
            'pageSize': 5,
            'sortColumns': 'TRADE_DATE',
            'sortTypes': '-1',
            'filter': f'(SECURITY_CODE="{stock_code}")',
            'source': 'WEB',
            'client': 'WEB'
        }
        
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Referer': 'https://data.eastmoney.com/'
        }
        
        for attempt in range(self.retries):
            try:
                if attempt > 0:
                    time.sleep(0.5 * attempt)
                
                response = self.session.get(url, params=params, headers=headers, timeout=self.timeout)
                response.raise_for_status()
                
                data = response.json()
                
                # 检查返回数据结构（datacenter-web 接口返回格式）
                if not data or 'result' not in data:
                    return None
                
                result = data['result']
                if not result or 'data' not in result or not result['data']:
                    return None
                
                # 获取第一条数据
                record = result['data'][0]
                
                # 获取流通市值（直接从API返回）
                float_market_cap = float(record.get('NOTLIMITED_MARKETCAP_A', 0) or 0)
                
                if float_market_cap > 0:
                    return float_market_cap
                
                return None
                
            except Exception as e:
                if attempt < self.retries - 1:
                    continue
                else:
                    return None
        
        return None
    
    def fetch_stock_data(self, stock_code: str) -> Optional[Dict]:
        """
        获取单只股票的完整数据（主力净流入 + 流通市值）
        
        Args:
            stock_code: 股票代码
            
        Returns:
            {'code': str, 'main_net_inflow': float, 'float_market_cap': float, ...}
            或 None
        """
        # 获取主力净流入
        inflow_data = self.fetch_main_inflow_eastmoney(stock_code)
        
        if inflow_data is None:
            return None
        
        # 获取流通市值
        float_market_cap = self.fetch_float_market_cap(stock_code)
        
        # 合并数据
        result = inflow_data.copy()
        result['float_market_cap'] = float_market_cap if float_market_cap else 0
        
        # 计算主力净流入占比（按流通市值）
        if float_market_cap and float_market_cap > 0:
            result['main_inflow_ratio'] = result['main_net_inflow'] / float_market_cap
        else:
            result['main_inflow_ratio'] = 0
        
        return result
    
    # ============================================================
    # 批量获取（内存优化）
    # ============================================================
    
    def batch_fetch_main_inflow(
        self,
        stock_codes: List[str],
        batch_size: int = BATCH_SIZE,
        progress_callback: Optional[callable] = None
    ) -> Dict[str, Dict]:
        """
        批量获取多只股票的主力净流入和流通市值数据
        
        内存优化策略：
        1. 分批获取（每批500只）
        2. 及时释放内存
        3. 失败重试机制
        4. 并发获取（2线程）
        
        Args:
            stock_codes: 股票代码列表
            batch_size: 每批数量（默认500）
            progress_callback: 进度回调函数
            
        Returns:
            {stock_code: {主力净流入数据}} 字典
        """
        total = len(stock_codes)
        result = {}
        success_count = 0
        fail_count = 0
        
        print(f"\n[批量获取主力资金数据] 共 {total} 只股票")
        print(f"  批次大小: {batch_size}")
        print(f"  并发线程: {MAX_WORKERS}")
        
        # 分批处理
        batches = [stock_codes[i:i+batch_size] for i in range(0, total, batch_size)]
        total_batches = len(batches)
        
        start_time = time.time()
        
        for batch_idx, batch_codes in enumerate(batches):
            batch_start_time = time.time()
            
            print(f"\n  [批次 {batch_idx + 1}/{total_batches}] 处理 {len(batch_codes)} 只股票...")
            
            # 分配给两个线程
            mid = len(batch_codes) // 2
            thread_a_codes = batch_codes[:mid]
            thread_b_codes = batch_codes[mid:]
            
            batch_results = {}
            
            with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
                future_a = executor.submit(
                    self._fetch_batch_sequential, 
                    thread_a_codes,
                    batch_idx * batch_size
                )
                future_b = executor.submit(
                    self._fetch_batch_sequential, 
                    thread_b_codes,
                    batch_idx * batch_size + mid
                )
                
                results_a = future_a.result()
                results_b = future_b.result()
                
                batch_results.update(results_a)
                batch_results.update(results_b)
            
            # 合并结果
            result.update(batch_results)
            
            # 统计成功/失败
            for code, data in batch_results.items():
                if data:
                    success_count += 1
                else:
                    fail_count += 1
            
            # 释放内存
            del batch_results
            gc.collect()
            
            # 进度显示
            elapsed = time.time() - batch_start_time
            total_elapsed = time.time() - start_time
            completed = (batch_idx + 1) * batch_size
            
            print(f"    进度: {min(completed, total)}/{total}")
            print(f"    成功: {success_count}, 失败: {fail_count}")
            print(f"    批次耗时: {elapsed:.1f}s, 总耗时: {total_elapsed:.1f}s")
            
            # 批次间延迟
            if batch_idx < total_batches - 1:
                time.sleep(REQUEST_DELAY)
        
        final_elapsed = time.time() - start_time
        print(f"\n  ✓ 批量获取完成")
        print(f"    成功: {success_count}/{total}")
        print(f"    失败: {fail_count}")
        print(f"    总耗时: {final_elapsed:.1f}s")
        
        return result
    
    def _fetch_batch_sequential(
        self, 
        codes: List[str],
        start_idx: int
    ) -> Dict[str, Dict]:
        """
        顺序获取一批股票数据（内部方法）
        
        直接使用东方财富 API
        
        Args:
            codes: 股票代码列表
            start_idx: 起始索引（用于日志）
            
        Returns:
            {code: data} 字典
        """
        results = {}
        
        for i, code in enumerate(codes):
            # 直接使用东方财富 API
            main_inflow_data = self.fetch_main_inflow_eastmoney(code)
            
            if main_inflow_data:
                # 获取流通市值
                float_market_cap = self.fetch_float_market_cap(code)
                if float_market_cap:
                    main_inflow_data['float_market_cap'] = float_market_cap
                    if float_market_cap > 0:
                        main_inflow_data['main_inflow_ratio'] = \
                            main_inflow_data['main_net_inflow'] / float_market_cap
                results[code] = main_inflow_data
            else:
                results[code] = None
            
            # 股票间延迟（避免API限流）
            if i < len(codes) - 1:
                time.sleep(0.1)
        
        return results
    
    # ============================================================
    # 批量获取历史数据
    # ============================================================
        
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Referer': 'http://data.eastmoney.com/'
        }
        
        for attempt in range(self.retries):
            try:
                if attempt > 0:
                    time.sleep(1.0 * attempt)
                
                response = self.session.get(url, params=params, headers=headers, timeout=self.timeout)
                response.raise_for_status()
                
                data = response.json()
                
                if not data or 'data' not in data or not data['data']:
                    return None
                
                klines = data['data'].get('klines', [])
                
                if not klines:
                    return None
                
                # 解析历史数据
                # 字段顺序：[0]日期, [1]主力净流入, [2]小单净流入, [3]中单净流入, [4]大单净流入, [5]特大单净流入
                # 单位：元（API直接返回元，无需转换）
                records = []
                for kline in klines:
                    parts = kline.split(',')
                    
                    if len(parts) < 6:
                        continue
                    
                    # 解析各字段
                    try:
                        date = parts[0]
                        # 主力净流入 = 大单 + 特大单（东方财富定义）
                        big_inflow = float(parts[4]) if parts[4] else 0  # 大单净流入（元）
                        super_inflow = float(parts[5]) if parts[5] else 0  # 特大单净流入（元）
                        main_net_inflow = big_inflow + super_inflow
                        
                        records.append({
                            'date': date,
                            'asset': stock_code,
                            'main_net_inflow': main_net_inflow,
                            'super_net_inflow': super_inflow,
                            'big_net_inflow': big_inflow,
                            'medium_net_inflow': float(parts[3]) if len(parts) > 3 and parts[3] else 0,
                            'small_net_inflow': float(parts[2]) if len(parts) > 2 and parts[2] else 0
                        })
                    except (ValueError, TypeError):
                        continue
                
                if not records:
                    return None
                
                df = pd.DataFrame(records)
                df['date'] = pd.to_datetime(df['date'])
                
                # 内存优化：使用category类型
                df['asset'] = df['asset'].astype('category')
                
                return df.sort_values('date').reset_index(drop=True)
                
            except Exception as e:
                if attempt < self.retries - 1:
                    continue
                else:
                    return None
        
        return None
    
    def batch_fetch_main_inflow_history(
        self,
        stock_codes: List[str],
        days: int = 500,
        batch_size: int = BATCH_SIZE
    ) -> Dict[str, pd.DataFrame]:
        """
        批量获取多只股票的历史主力资金数据
        
        直接使用东方财富 API
        
        内存优化：分批获取，及时释放
        
        Args:
            stock_codes: 股票代码列表
            days: 获取天数
            batch_size: 每批数量
            
        Returns:
            {stock_code: DataFrame} 字典
        """
        total = len(stock_codes)
        result = {}
        success_count = 0
        
        print(f"\n[批量获取历史主力资金] 共 {total} 只股票，{days} 天数据")
        print(f"  数据源: 东方财富 API")
        print(f"  批次大小: {batch_size}")
        print(f"  并发线程: {MAX_WORKERS}")
        
        batches = [stock_codes[i:i+batch_size] for i in range(0, total, batch_size)]
        total_batches = len(batches)
        
        start_time = time.time()
        
        for batch_idx, batch_codes in enumerate(batches):
            batch_start_time = time.time()
            
            print(f"\n  [批次 {batch_idx + 1}/{total_batches}] 处理 {len(batch_codes)} 只股票...")
            
            # 分配给两个线程
            mid = len(batch_codes) // 2
            thread_a_codes = batch_codes[:mid]
            thread_b_codes = batch_codes[mid:]
            
            batch_results = {}
            
            with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
                future_a = executor.submit(
                    self._fetch_batch_history_sequential,
                    thread_a_codes,
                    days
                )
                future_b = executor.submit(
                    self._fetch_batch_history_sequential,
                    thread_b_codes,
                    days
                )
                
                results_a = future_a.result()
                results_b = future_b.result()
                
                batch_results.update(results_a)
                batch_results.update(results_b)
            
            # 统计成功数量
            for code, df in batch_results.items():
                if df is not None and len(df) > 0:
                    success_count += 1
            
            result.update(batch_results)
            
            # 释放内存
            del batch_results
            gc.collect()
            
            # 进度显示
            elapsed = time.time() - batch_start_time
            total_elapsed = time.time() - start_time
            completed = (batch_idx + 1) * batch_size
            
            print(f"    进度: {min(completed, total)}/{total}")
            print(f"    成功: {success_count}")
            print(f"    批次耗时: {elapsed:.1f}s, 总耗时: {total_elapsed:.1f}s")
            
            # 批次间延迟
            if batch_idx < total_batches - 1:
                time.sleep(REQUEST_DELAY)
        
        final_elapsed = time.time() - start_time
        print(f"\n  ✓ 完成，成功 {success_count}/{total}")
        print(f"    总耗时: {final_elapsed:.1f}s")
        
        return result
    
    def _fetch_batch_history_sequential(
        self,
        codes: List[str],
        days: int
    ) -> Dict[str, pd.DataFrame]:
        """
        顺序获取一批股票的历史主力资金数据（内部方法）
        
        Args:
            codes: 股票代码列表
            days: 获取天数
            
        Returns:
            {code: DataFrame} 字典
        """
        results = {}
        
        for i, code in enumerate(codes):
            df = self.fetch_main_inflow_history(code, days)
            
            if df is not None and len(df) > 0:
                results[code] = df
            
            # 股票间延迟
            if i < len(codes) - 1:
                time.sleep(0.1)
        
        return results
    
    # ============================================================
    # 缓存操作
    # ============================================================
    
    def save_main_inflow_cache(
        self,
        data: Dict[str, Dict],
        cache_path: Optional[str] = None
    ) -> None:
        """
        保存主力资金数据到缓存
        
        Args:
            data: 主力资金数据字典
            cache_path: 缓存路径（可选）
        """
        if not self.enable_cache:
            return
        
        if cache_path is None:
            cache_path = os.path.join(MAIN_INFLOW_CACHE_DIR, 'main_inflow_latest.json.gz')
        
        # 构建缓存数据
        records = []
        for code, d in data.items():
            if d:
                records.append({
                    'code': code,
                    'date': d.get('date', datetime.now().strftime('%Y-%m-%d')),
                    'main_net_inflow': d.get('main_net_inflow', 0),
                    'main_net_inflow_ratio': d.get('main_net_inflow_ratio', 0),
                    'float_market_cap': d.get('float_market_cap', 0),
                    'main_net_inflow_ratio_by_cap': d.get('main_net_inflow_ratio_by_cap', 0)
                })
        
        cache_data = {
            'meta': {
                'generated_at': datetime.now().isoformat(),
                'source': 'eastmoney_api',
                'total_count': len(records),
                'version': '1.0'
            },
            'data': records
        }
        
        # gzip 压缩保存
        with gzip.open(cache_path, 'wt', encoding='utf-8') as f:
            json.dump(cache_data, f, ensure_ascii=False, indent=2)
        
        file_size = os.path.getsize(cache_path) / (1024 * 1024)
        print(f"\n[缓存] 已保存: {cache_path} ({file_size:.2f} MB)")
    
    def load_main_inflow_cache(
        self,
        cache_path: Optional[str] = None
    ) -> Optional[Dict]:
        """
        加载主力资金缓存
        
        Args:
            cache_path: 缓存路径（可选）
            
        Returns:
            缓存数据字典，或 None
        """
        if cache_path is None:
            cache_path = os.path.join(MAIN_INFLOW_CACHE_DIR, 'main_inflow_latest.json.gz')
        
        if not os.path.exists(cache_path):
            return None
        
        try:
            with gzip.open(cache_path, 'rt', encoding='utf-8') as f:
                data = json.load(f)
            
            print(f"[缓存] 已加载: {cache_path}")
            return data
            
        except Exception as e:
            print(f"[缓存] 加载失败: {e}")
            return None


# ============================================================
# 辅助函数
# ============================================================

def get_stock_codes_from_cache() -> List[str]:
    """
    从股票列表缓存获取代码
    
    Returns:
        股票代码列表
    """
    stock_list_path = os.path.join(CACHE_DIR, 'stock_list.json')
    
    if not os.path.exists(stock_list_path):
        print(f"股票列表缓存不存在: {stock_list_path}")
        return []
    
    try:
        with open(stock_list_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        codes = data.get('codes', [])
        print(f"[股票列表] 加载 {len(codes)} 只股票")
        
        return codes
        
    except Exception as e:
        print(f"加载股票列表失败: {e}")
        return []


def create_main_inflow_fetcher(
    timeout: int = REQUEST_TIMEOUT,
    retries: int = REQUEST_RETRIES,
    enable_cache: bool = True
) -> MainInflowDataFetcher:
    """
    创建主力资金数据获取器
    
    Args:
        timeout: 请求超时时间
        retries: 重试次数
        enable_cache: 启用缓存
        
    Returns:
        MainInflowDataFetcher 实例
    """
    return MainInflowDataFetcher(timeout=timeout, retries=retries, enable_cache=enable_cache)


# ============================================================
# 东方财富 API 接口测试
# ============================================================

def test_eastmoney_interface():
    """测试东方财富 API 接口可用性"""
    print("\n" + "=" * 60)
    print("东方财富 API 接口测试")
    print("=" * 60)
    
    fetcher = MainInflowDataFetcher()
    
    # 测试主力资金接口
    print("\n[测试] 主力资金接口...")
    test_code = '000001'
    
    inflow_data = fetcher.fetch_main_inflow_eastmoney(test_code)
    if inflow_data:
        print(f"  ✓ 成功获取 {test_code} 主力资金数据")
        print(f"    主力净流入: {inflow_data['main_net_inflow']:.2f} 元")
        print(f"    日期: {inflow_data['date']}")
    else:
        print(f"  ✗ 获取失败")
    
    # 测试流通市值接口
    print("\n[测试] 流通市值接口...")
    float_cap = fetcher.fetch_float_market_cap(test_code)
    if float_cap:
        print(f"  ✓ 成功获取 {test_code} 流通市值")
        print(f"    流通市值: {float_cap:.2f} 元 ({float_cap/1e8:.2f} 亿元)")
    else:
        print(f"  ✗ 获取失败")
    
    # 测试历史数据接口
    print("\n[测试] 历史主力资金接口...")
    history_df = fetcher.fetch_main_inflow_history(test_code, days=30)
    if history_df is not None and len(history_df) > 0:
        print(f"  ✓ 成功获取 {len(history_df)} 天历史数据")
        print(f"    最新数据:")
        print(history_df.tail(3).to_string())
    else:
        print(f"  ✗ 获取失败")
    
    print("\n" + "=" * 60)
    print("东方财富 API 接口测试完成")
    print("=" * 60)
    
    return True


# ============================================================
# 主函数
# ============================================================

def main():
    """测试主力资金数据获取"""
    print("=" * 60)
    print("主力净流入数据获取模块测试（东方财富 API）")
    print("=" * 60)
    
    # 创建获取器
    fetcher = create_main_inflow_fetcher()
    
    # 获取股票代码
    stock_codes = get_stock_codes_from_cache()
    
    if not stock_codes:
        print("未获取到股票代码，请先运行 stock_cache.py")
        return
    
    # 测试单只股票获取
    test_code = stock_codes[0]
    print(f"\n[测试单只股票] {test_code}")
    
    # 使用东方财富 API
    print("  使用东方财富 API...")
    
    # 主力净流入数据
    inflow_data = fetcher.fetch_main_inflow_eastmoney(test_code)
    if inflow_data:
        print(f"  ✓ 主力净流入: {inflow_data['main_net_inflow']:.2f} 元")
        print(f"  ✓ 特大单净流入: {inflow_data['super_net_inflow']:.2f} 元")
        print(f"  ✓ 大单净流入: {inflow_data['big_net_inflow']:.2f} 元")
    
    # 流通市值
    float_cap = fetcher.fetch_float_market_cap(test_code)
    if float_cap:
        print(f"  ✓ 流通市值: {float_cap:.2f} 元 ({float_cap/1e8:.2f} 亿元)")
        
        if inflow_data:
            main_inflow_ratio = inflow_data['main_net_inflow'] / float_cap
            print(f"  ✓ 主力净流入占比: {main_inflow_ratio:.4f}")
    
    # 测试批量获取（限制数量）
    print(f"\n[测试批量获取] 前10只股票")
    batch_codes = stock_codes[:10]
    batch_data = fetcher.batch_fetch_main_inflow(batch_codes)
    
    success_count = len([d for d in batch_data.values() if d])
    print(f"  ✓ 获取成功: {success_count}/10 只")
    
    # 测试历史数据批量获取
    print(f"\n[测试历史数据批量获取] {test_code}")
    history_df = fetcher.fetch_main_inflow_history(test_code, days=30)
    
    if history_df is not None and len(history_df) > 0:
        print(f"  ✓ 获取到 {len(history_df)} 天数据")
        print(history_df.head())
    else:
        print("  ✗ 历史数据获取失败")
    
    print("\n" + "=" * 60)
    print("测试完成")
    print("=" * 60)


if __name__ == '__main__':
    # 测试东方财富 API 接口
    test_eastmoney_interface()
    # 然后运行主测试
    main()
    print(f"\n[测试批量获取] 前10只股票")
    batch_codes = stock_codes[:10]
    batch_data = fetcher.batch_fetch_main_inflow(batch_codes)
    
    success_count = len([d for d in batch_data.values() if d])
    print(f"  ✓ 获取成功: {success_count}/10 只")
    
    # 测试历史数据批量获取
    print(f"\n[测试历史数据批量获取] {test_code}")
    history_df = fetcher.fetch_main_inflow_history(test_code, days=30)
    
    if history_df is not None and len(history_df) > 0:
        print(f"  ✓ 获取到 {len(history_df)} 天数据")
        print(history_df.head())
    else:
        print("  ✗ 历史数据获取失败")
    
    print("\n" + "=" * 60)
    print("测试完成")
    print("=" * 60)


if __name__ == '__main__':
    # 测试东方财富 API 接口
    test_eastmoney_interface()
    # 然后运行主测试
    main()