#!/usr/bin/env python3
"""
真实 A股数据加载器（分批并发版本 + 数据完整性校验）

支持多种数据源：
1. 新浪财经 API（网络）
2. 本地CSV文件
3. 模拟数据（测试用）

主板股票定义：
- 沪市主板：60 开头
- 深市主板：00 开头

剔除：创业板(30)、科创板(688)、北交所(8/4开头)、ST股票

分批并发策略（避免API限流）：
- 每批次启动2个线程并行
- 线程A处理前50只股票
- 线程B处理后50只股票
- 等前两线程完成后，再启动下一批
- 批次间添加2秒延迟
- 支持重试机制

目标：
- 获取所有主板股票（约3000+只）
- 沪市主板：60开头
- 深市主板：00开头
- 剔除：创业板(30)、科创板(688)、北交所、ST股票

数据完整性保障：
- 每日生成股票清单缓存
- 获取完成后完整性校验
- 自动补全缺失股票
- 最终验证输出统计

依赖: pip install requests pandas numpy

作者: 云舟
日期: 2026-04-01
"""

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from pathlib import Path
from typing import Tuple, Optional, List, Dict
from concurrent.futures import ThreadPoolExecutor, as_completed
import time
import warnings
import requests
import threading
import gzip
import json
import gc
import os
import random
import json
import gzip
warnings.filterwarnings('ignore')


class RealDataLoader:
    """真实 A股数据加载器（多线程版本）"""
    
    # 新浪财经 API 端点
    STOCK_LIST_URL = 'http://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/Market_Center.getHQNodeData'
    KLINE_URL = 'https://quotes.sina.cn/cn/api/json_v2.php/CN_MarketDataService.getKLineData'
    
    # 本地数据路径
    LOCAL_DATA_DIR = os.path.expanduser('~/projects/factor_ic_analyzer/data')
    # 缓存路径
    CACHE_DIR = os.path.expanduser('~/projects/factor_ic_analyzer/cache')
    # 因子数据缓存路径（按日期命名）
    FACTOR_CACHE_DIR = os.path.expanduser('~/projects/factor_ic_analyzer/cache/factor_data')
    
    def __init__(
        self, 
        timeout: int = 30, 
        max_workers: int = 2, 
        retries: int = 3,
        use_local: bool = False,
        use_mock: bool = False,
        enable_cache: bool = True
    ):
        """
        初始化数据加载器
        
        Args:
            timeout: 请求超时时间（秒）
            max_workers: 已废弃，现使用固定的分批并发策略
                         每批次2线程并行，每线程处理50只股票
            retries: 失败重试次数
            use_local: 使用本地CSV数据
            use_mock: 使用模拟数据（测试用）- ⚠️ 量化系统不应使用模拟数据
            enable_cache: 启用缓存
        """
        self.stock_list = None
        self.price_data = None
        self.timeout = timeout
        self.max_workers = max_workers
        self.retries = retries
        self.use_local = use_local
        self.use_mock = use_mock
        self.enable_cache = enable_cache
        self.session = requests.Session()
        self._lock = threading.Lock()
        self._request_count = 0
        
        # ⚠️ 警告：量化系统不应使用模拟数据
        if self.use_mock:
            print("⚠️ 警告：正在使用模拟数据！量化系统必须使用真实数据进行分析。")
            print("⚠️ 警告：模拟数据仅供测试使用，分析结果无实际意义。")
        
        # 确保缓存目录存在
        if self.enable_cache:
            if not os.path.exists(self.CACHE_DIR):
                os.makedirs(self.CACHE_DIR, exist_ok=True)
                print(f"[缓存] 创建缓存目录: {self.CACHE_DIR}")
            if not os.path.exists(self.FACTOR_CACHE_DIR):
                os.makedirs(self.FACTOR_CACHE_DIR, exist_ok=True)
                print(f"[缓存] 创建因子缓存目录: {self.FACTOR_CACHE_DIR}")
        
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Accept': '*/*',
            'Referer': 'http://finance.sina.com.cn/'
        })
        
    def get_main_board_stocks(self, max_stocks: int = 0) -> List[Dict]:
        """
        获取主板股票列表
        
        沪市主板：60开头
        深市主板：00开头
        
        剔除：创业板(30)、科创板(688)、北交所(8/4开头)、ST股票
        
        Args:
            max_stocks: 最大返回数量，0表示获取全部
            
        Returns:
            股票信息列表 [{'code': str, 'name': str}, ...]
        """
        if self.use_mock:
            return self._get_mock_stock_list(max_stocks)
        
        if self.use_local:
            return self._get_local_stock_list(max_stocks)
        
        return self._get_api_stock_list(max_stocks)
    
    def _get_mock_stock_list(self, max_stocks: int) -> List[Dict]:
        """生成模拟股票列表（仅主板）"""
        print("[获取股票列表] 生成模拟数据...")
        
        stocks = []
        # 沪市主板 60开头
        for i in range(1, min(500, max_stocks) if max_stocks > 0 else 500):
            code = f"60{i:04d}"
            stocks.append({'code': code, 'name': f'沪股{i}'})
        
        # 深市主板 00开头
        for i in range(1, min(500, max_stocks - len(stocks)) if max_stocks > 0 else 500):
            code = f"00{i:04d}"
            stocks.append({'code': code, 'name': f'深股{i}'})
        
        # 排除ST
        stocks = [s for s in stocks if 'ST' not in s['name']]
        
        if max_stocks > 0:
            stocks = stocks[:max_stocks]
        
        stocks.sort(key=lambda x: x['code'])
        print(f"  ✓ 生成 {len(stocks)} 只模拟主板股票")
        return stocks
    
    def _get_local_stock_list(self, max_stocks: int) -> List[Dict]:
        """从本地文件读取股票列表（仅主板）- 向量化优化版"""
        list_file = os.path.join(self.LOCAL_DATA_DIR, 'stock_list.csv')
        
        if not os.path.exists(list_file):
            raise RuntimeError(f"本地文件不存在: {list_file}。请检查数据目录或使用 API 获取。")
        
        df = pd.read_csv(list_file)
        
        # 向量化筛选主板股票（替代 iterrows）
        df['code'] = df['code'].astype(str)
        df['name'] = df['name'].astype(str)
        
        # 只保留主板：沪市60开头、深市00开头
        # 剔除：创业板30、科创板688、北交所8/4开头、ST股票
        main_board_mask = df['code'].str.startswith(('60', '00'))
        st_mask = ~df['name'].str.contains('ST', case=False, na=False)
        
        filtered_df = df[main_board_mask & st_mask]
        
        # 向量化构建结果列表
        stocks = filtered_df[['code', 'name']].to_dict('records')
        
        if max_stocks > 0:
            stocks = stocks[:max_stocks]
        
        print(f"  ✓ 从本地读取 {len(stocks)} 只主板股票")
        return stocks
    
    def _get_api_stock_list(self, max_stocks: int) -> List[Dict]:
        """从新浪财经API获取股票列表（分页获取所有数据）

        新浪API使用 getHQNodeData 接口，返回股票实时行情数据
        包含 code（代码）和 name（名称）字段

        注意：新浪API每页最多返回约80-100条数据，需要分页获取
        """
        print("[获取股票列表] 从新浪财经 API 获取主板股票...")

        # 新浪API请求头
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': '*/*',
            'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
            'Referer': 'http://finance.sina.com.cn/',
        }

        all_stocks = []

        # 新浪API节点说明：
        # hs_a - 沪深A股全部
        # sh_a - 沪市A股
        # sz_a - 深市A股
        nodes = [
            {'node': 'sh_a', 'desc': '沪市A股'},
            {'node': 'sz_a', 'desc': '深市A股'},
        ]

        page_size = 80  # 每页获取80条，与stock_cache.py保持一致

        try:
            for node_info in nodes:
                print(f"  获取 {node_info['desc']}...")

                page = 1
                node_stocks_count = 0

                # 分页获取，直到返回空数据
                while True:
                    # 新浪API参数（分页获取）
                    params = {
                        'page': page,
                        'num': page_size,
                        'node': node_info['node'],
                        'sort': 'symbol',
                        'asc': 1,
                        '_s_r_a': 'page'
                    }

                    success = False
                    data = None

                    for attempt in range(self.retries):
                        try:
                            # 添加随机延迟，避免被限流
                            if attempt > 0:
                                delay = 2 + attempt * 2
                                print(f"    重试 {attempt}/{self.retries}，等待 {delay}秒...")
                                time.sleep(delay)

                            response = self.session.get(
                                self.STOCK_LIST_URL,
                                params=params,
                                headers=headers,
                                timeout=self.timeout
                            )
                            response.raise_for_status()

                            # 新浪API返回JSON数组格式
                            data = response.json()
                            success = True
                            break

                        except Exception as e:
                            if attempt < self.retries - 1:
                                continue
                            else:
                                print(f"    ! 获取失败: {e}")

                    if not success:
                        raise RuntimeError(f"获取 {node_info['desc']} 第 {page} 页数据失败，已重试 {self.retries} 次")

                    # 检查返回数据
                    if not data or not isinstance(data, list) or len(data) == 0:
                        # 返回空数据，表示已获取完毕
                        print(f"    第 {page} 页返回空数据，{node_info['desc']} 获取完成")
                        break

                    # 处理本页数据
                    page_added = 0
                    for item in data:
                        # 新浪API字段：code(代码), name(名称)
                        # 注意：code 字段不带前缀，如 "600000"
                        code = item.get('code', '')
                        name = item.get('name', '')

                        # 只保留主板：沪市60开头、深市00开头
                        # 剔除：创业板30、科创板688、北交所8/4开头、ST股票
                        if code.startswith(('60', '00')):
                            if not any(x in name for x in ['ST', '退市', '*ST']):
                                all_stocks.append({'code': code, 'name': name})
                                page_added += 1

                    node_stocks_count += page_added
                    print(f"    第 {page} 页: 获取 {len(data)} 条，新增主板 {page_added} 只")

                    # 如果返回数据少于页面大小，说明已到最后一页
                    if len(data) < page_size:
                        print(f"    最后一页，{node_info['desc']} 获取完成")
                        break

                    page += 1

                    # 页间延迟，避免请求过快
                    time.sleep(0.1)

                print(f"    ✓ {node_info['desc']} 共获取 {node_stocks_count} 只主板股票")

                # 节点间延迟
                time.sleep(0.5)

            # 去重
            seen = set()
            unique_stocks = []
            for s in all_stocks:
                if s['code'] not in seen:
                    seen.add(s['code'])
                    unique_stocks.append(s)

            if max_stocks > 0:
                unique_stocks = unique_stocks[:max_stocks]

            unique_stocks.sort(key=lambda x: x['code'])

            if len(unique_stocks) == 0:
                raise RuntimeError("API获取失败，未获取到任何主板股票。请检查网络连接或稍后重试。")

            print(f"  ✓ 获取到 {len(unique_stocks)} 只主板非ST股票（去重后）")
            return unique_stocks

        except RuntimeError:
            raise
        except Exception as e:
            raise RuntimeError(f"API获取股票列表失败: {e}。请检查网络连接。")
    
    def _get_stock_list_cache_path(self) -> str:
        """获取股票清单缓存文件路径（与 stock_cache.py 统一）"""
        # 统一使用 cache/stock_list.json，与 stock_cache.py 保持一致
        return os.path.join(self.CACHE_DIR, 'stock_list.json')
    
    def _save_stock_list_cache(self, stock_list: List[Dict]) -> None:
        """保存股票清单到缓存文件（与 stock_cache.py 格式一致）"""
        if not self.enable_cache:
            return

        cache_path = self._get_stock_list_cache_path()
        now = datetime.now()
        today = now.strftime('%Y-%m-%d')

        # 统计市场分布
        sh_count = len([s for s in stock_list if s['code'].startswith('60')])
        sz_count = len([s for s in stock_list if s['code'].startswith('00')])

        # 使用与 stock_cache.py 一致的缓存格式
        cache_data = {
            'meta': {
                'generated_at': now.isoformat(),
                'source': 'sina_api',
                'total_count': len(stock_list),
                'sh_count': sh_count,
                'sz_count': sz_count,
                'version': '1.0'
            },
            'stocks': [
                {
                    'code': s['code'],
                    'name': s['name'],
                    'market': 'sh' if s['code'].startswith('60') else 'sz',
                    'updated_at': today
                }
                for s in stock_list
            ],
            'codes': [s['code'] for s in stock_list]
        }

        import json
        with open(cache_path, 'w', encoding='utf-8') as f:
            json.dump(cache_data, f, ensure_ascii=False, indent=2)

        print(f"[缓存] 股票清单已保存: {cache_path} ({len(stock_list)}只)")
    
    def _load_stock_list_cache(self) -> Optional[List[Dict]]:
        """从缓存加载股票清单（兼容 stock_cache.py 的缓存格式）"""
        if not self.enable_cache:
            return None

        cache_path = self._get_stock_list_cache_path()

        if not os.path.exists(cache_path):
            return None

        try:
            import json
            with open(cache_path, 'r', encoding='utf-8') as f:
                cache_data = json.load(f)

            # 兼容 stock_cache.py 生成的缓存格式
            # stock_cache.py 格式: {"meta": {...}, "stocks": [...], "codes": [...]}
            # 旧格式: {"date": "...", "count": ..., "stocks": [...], "created_at": "..."}

            stocks = cache_data.get('stocks', [])

            if not stocks:
                return None

            # 检查缓存日期（如果有的话）
            meta = cache_data.get('meta', {})
            generated_at = meta.get('generated_at', '')

            if generated_at:
                # 提取日期部分
                cache_date = generated_at.split('T')[0] if 'T' in generated_at else generated_at[:10]
                today = datetime.now().strftime('%Y-%m-%d')

                if cache_date != today:
                    print(f"[缓存] 缓存日期 {cache_date} 不是今天 {today}，将重新获取")
                    return None

            print(f"[缓存] 从缓存加载股票清单: {len(stocks)}只")
            return stocks

        except Exception as e:
            print(f"[缓存] 读取缓存失败: {e}")
            return None
    
    def _get_factor_cache_path(self) -> str:
        """获取因子数据缓存文件路径（固定文件名，支持增量更新）
        
        Returns:
            缓存文件完整路径：factor_data.json.gz
        """
        return os.path.join(self.FACTOR_CACHE_DIR, 'factor_data.json.gz')
    
    def _get_return_cache_path(self) -> str:
        """获取收益数据缓存文件路径（固定文件名，支持增量更新）
        
        Returns:
            缓存文件完整路径：return_data.json.gz
        """
        return os.path.join(self.FACTOR_CACHE_DIR, 'return_data.json.gz')
    
    def _get_status_cache_path(self) -> str:
        """获取股票交易状态缓存文件路径（用于动态过滤异常股票）
        
        保存每只股票每日的交易状态信息：
        - volume: 成交量（用于判断停牌）
        - close: 收盘价
        - prev_close: 前一日收盘价（用于计算涨跌停价）
        - limit_up_price: 涨停价
        - limit_down_price: 跌停价
        
        Returns:
            缓存文件完整路径：stock_status.json.gz
        """
        return os.path.join(self.FACTOR_CACHE_DIR, 'stock_status.json.gz')
    
    def _get_cache_date_range(self, cache_data: dict) -> Tuple[Optional[str], Optional[str]]:
        """获取缓存数据的日期范围
        
        Args:
            cache_data: 缓存数据字典
            
        Returns:
            (start_date, end_date) 或 (None, None)
        """
        if not cache_data:
            return None, None
        
        # 【修复】首先检查实际数据是否存在
        data = cache_data.get('data', [])
        if data:
            dates = sorted(set(d.get('date') for d in data if d.get('date')))
            if dates:
                return dates[0], dates[-1]
        
        # 只有在数据有效时才使用元数据（防止元数据与实际数据不一致）
        meta = cache_data.get('meta', {})
        date_range = meta.get('date_range', {})
        
        if date_range:
            # 验证元数据与实际数据一致性
            n_days = meta.get('n_days', 0)
            n_assets = meta.get('n_assets', 0)
            # 只有当元数据声称有数据，且实际数据也存在时才返回元数据中的日期范围
            if n_days > 0 and n_assets > 0 and len(data) > 0:
                return date_range.get('start'), date_range.get('end')
        
        return None, None
    
    def _merge_cache_data(
        self,
        existing_data: dict,
        new_factor_df: pd.DataFrame,
        new_return_df: pd.DataFrame
    ) -> Tuple[dict, dict]:
        """合并现有缓存数据和新数据
        
        Args:
            existing_data: 现有缓存数据（包含 factor 和 return）
            new_factor_df: 新因子数据
            new_return_df: 新收益数据
            
        Returns:
            (merged_factor_data, merged_return_data)
        """
        import json
        
        # 提取现有数据
        existing_factor_records = existing_data.get('factor', {}).get('data', [])
        existing_return_records = existing_data.get('return', {}).get('data', [])
        
        # 转换为 DataFrame
        existing_factor_df = pd.DataFrame(existing_factor_records) if existing_factor_records else pd.DataFrame()
        existing_return_df = pd.DataFrame(existing_return_records) if existing_return_records else pd.DataFrame()
        
        # 合并数据
        if len(existing_factor_df) > 0:
            combined_factor_df = pd.concat([existing_factor_df, new_factor_df], ignore_index=True)
        else:
            combined_factor_df = new_factor_df
        
        if len(existing_return_df) > 0:
            combined_return_df = pd.concat([existing_return_df, new_return_df], ignore_index=True)
        else:
            combined_return_df = new_return_df
        
        # 去重：同一股票同一日期只保留最新数据
        if len(combined_factor_df) > 0:
            combined_factor_df = combined_factor_df.drop_duplicates(
                subset=['date', 'asset'], 
                keep='last'
            ).sort_values(['date', 'asset']).reset_index(drop=True)
        
        if len(combined_return_df) > 0:
            combined_return_df = combined_return_df.drop_duplicates(
                subset=['date', 'asset'], 
                keep='last'
            ).sort_values(['date', 'asset']).reset_index(drop=True)
        
        # 构建结果
        dates_list = sorted(combined_factor_df['date'].unique()) if len(combined_factor_df) > 0 else []
        assets_list = list(combined_factor_df['asset'].unique()) if len(combined_factor_df) > 0 else []
        
        now = datetime.now()
        
        merged_factor_data = {
            'meta': {
                'generated_at': now.isoformat(),
                'source': 'sina_api',
                'n_days': len(dates_list),
                'n_assets': len(assets_list),
                'date_range': {
                    'start': dates_list[0] if dates_list else None,
                    'end': dates_list[-1] if dates_list else None
                },
                'last_updated': now.strftime('%Y-%m-%d %H:%M:%S'),
                'version': '3.1'  # 新增量比因子版本
            },
            'data': combined_factor_df.to_dict('records')
        }
        
        merged_return_data = {
            'meta': {
                'generated_at': now.isoformat(),
                'source': 'sina_api',
                'n_days': len(dates_list),
                'n_assets': len(assets_list),
                'date_range': {
                    'start': dates_list[0] if dates_list else None,
                    'end': dates_list[-1] if dates_list else None
                },
                'last_updated': now.strftime('%Y-%m-%d %H:%M:%S'),
                'version': '3.1'
            },
            'data': combined_return_df.to_dict('records')
        }
        
        return merged_factor_data, merged_return_data
    
    def _save_cache_gzip(self, cache_path: str, data: dict) -> None:
        """使用 gzip 压缩保存缓存文件
        
        Args:
            cache_path: 缓存文件路径
            data: 要保存的数据字典
        """
        try:
            # 【修复】验证数据完整性
            records = data.get('data', [])
            meta = data.get('meta', {})
            
            if len(records) == 0:
                print(f"[缓存] ✗ 警告：缓存数据为空，跳过保存！路径: {cache_path}")
                return
            
            # 验证 meta.n_days 与实际数据一致性
            actual_dates = set(r.get('date') for r in records if r.get('date'))
            meta_n_days = meta.get('n_days', 0)
            actual_n_days = len(actual_dates)
            
            if meta_n_days > 0 and meta_n_days != actual_n_days:
                print(f"[缓存] ⚠ 警告：元数据 n_days ({meta_n_days}) 与实际数据天数 ({actual_n_days}) 不一致，已自动修正")
                # 修正元数据
                meta['n_days'] = actual_n_days
            
            # gzip 压缩写入
            with gzip.open(cache_path, 'wt', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            
            # 显示文件大小
            file_size = os.path.getsize(cache_path)
            size_mb = file_size / (1024 * 1024)
            print(f"[缓存] 已保存压缩缓存: {cache_path} ({size_mb:.2f} MB)")
            
        except Exception as e:
            print(f"[缓存] 保存缓存失败: {e}")
    
    def _load_cache_gzip(self, cache_path: str) -> Optional[dict]:
        """使用 gzip 解压读取缓存文件
        
        Args:
            cache_path: 缓存文件路径
            
        Returns:
            解压后的数据字典，失败返回 None
        """
        if not os.path.exists(cache_path):
            return None
        
        try:
            # gzip 解压读取
            with gzip.open(cache_path, 'rt', encoding='utf-8') as f:
                data = json.load(f)
            
            file_size = os.path.getsize(cache_path)
            size_mb = file_size / (1024 * 1024)
            print(f"[缓存] 已读取压缩缓存: {cache_path} ({size_mb:.2f} MB)")
            
            return data
            
        except Exception as e:
            print(f"[缓存] 读取缓存失败: {e}")
            return None
    
    def validate_cache(
        self, 
        factor_data: dict, 
        return_data: dict, 
        n_days: int,
        expected_assets: int = 3000
    ) -> bool:
        """校验缓存数据有效性
        
        校验逻辑（云汐建议）：
        1. 检查数据条数 >= n_days
        2. 检查股票覆盖率 >= 90%
        3. 检查日期范围合理
        4. 检查无异常值
        
        Args:
            factor_data: 因子数据字典
            return_data: 收益数据字典
            n_days: 预期的交易日数量
            expected_assets: 预期的股票数量（默认3000）
            
        Returns:
            缓存是否有效
        """
        try:
            # 检查 meta 信息
            factor_meta = factor_data.get('meta', {})
            return_meta = return_data.get('meta', {})
            
            # 检查交易日数
            factor_n_days = factor_meta.get('n_days', 0)
            return_n_days = return_meta.get('n_days', 0)
            
            if factor_n_days < n_days or return_n_days < n_days:
                print(f"[校验] 交易日数不足: factor={factor_n_days}, return={return_n_days}, 需求={n_days}")
                return False
            
            # 检查股票数量（覆盖率 >= 90%）
            factor_n_assets = factor_meta.get('n_assets', 0)
            return_n_assets = return_meta.get('n_assets', 0)
            
            min_coverage = int(expected_assets * 0.9)
            
            if factor_n_assets < min_coverage or return_n_assets < min_coverage:
                print(f"[校验] 股票覆盖率不足: factor={factor_n_assets}, return={return_n_assets}, 最低要求={min_coverage}")
                return False
            
            # 检查数据完整性
            factor_records = factor_data.get('data', [])
            return_records = return_data.get('data', [])
            
            if len(factor_records) == 0 or len(return_records) == 0:
                print(f"[校验] 数据记录为空")
                return False
            
            # 检查日期范围
            factor_date_range = factor_meta.get('date_range', {})
            return_date_range = return_meta.get('date_range', {})
            
            if not factor_date_range or not return_date_range:
                print(f"[校验] 日期范围缺失")
                return False
            
            # 检查因子值范围（RSI 应在 0-100 之间）
            # 采样检查，避免遍历所有数据
            if len(factor_records) > 0:
                sample_size = min(1000, len(factor_records))
                rsi_values = [r.get('rsi_6', 50) for r in factor_records[:sample_size]]
                
                rsi_min = min(rsi_values)
                rsi_max = max(rsi_values)
                
                if rsi_min < 0 or rsi_max > 100:
                    print(f"[校验] 因子值异常: RSI范围 [{rsi_min:.2f}, {rsi_max:.2f}]")
                    return False
            else:
                print(f"[校验] 因子数据为空")
                return False
            
            # 检查收益率范围（通常在 -0.2 ~ 0.2 之间）
            if len(return_records) > 0:
                sample_size = min(1000, len(return_records))
                return_values = [r.get('forward_return', 0) for r in return_records[:sample_size]]
                
                return_min = min(return_values)
                return_max = max(return_values)
            
            # 极端异常值检查（单日涨跌幅超过 50% 极罕见）
                if return_min < -0.5 or return_max > 0.5:
                    print(f"[校验] 收益率异常: 范围 [{return_min:.4f}, {return_max:.4f}]")
                    return False
            else:
                print(f"[校验] 收益数据为空")
                return False
            
            # 所有检查通过
            print(f"[校验] ✓ 缓存数据有效")
            print(f"  交易日数: {factor_n_days}")
            print(f"  股票数量: {factor_n_assets}")
            print(f"  日期范围: {factor_date_range.get('start')} ~ {factor_date_range.get('end')}")
            if len(factor_records) > 0:
                print(f"  RSI范围: [{rsi_min:.2f}, {rsi_max:.2f}]")
            if len(return_records) > 0:
                print(f"  收益范围: [{return_min:.4f}, {return_max:.4f}]")
            
            return True
            
        except Exception as e:
            print(f"[校验] 缓存校验异常: {e}")
            return False
    
    def _verify_data_completeness(
        self, 
        expected_stocks: List[Dict], 
        fetched_data: Dict[str, pd.DataFrame]
    ) -> Tuple[set, set]:
        """
        验证数据完整性
        
        Args:
            expected_stocks: 预期获取的股票列表
            fetched_data: 实际获取到的数据 {股票代码: DataFrame}
            
        Returns:
            (缺失的股票代码集合, 成功获取的股票代码集合)
        """
        expected_codes = set(s['code'] for s in expected_stocks)
        fetched_codes = set(fetched_data.keys())
        
        missing_codes = expected_codes - fetched_codes
        success_codes = expected_codes & fetched_codes
        
        return missing_codes, success_codes
    
    def _complement_missing_stocks(
        self,
        missing_codes: set,
        stock_list: List[Dict],
        days: int,
        delay: float = 1.0
    ) -> Dict[str, pd.DataFrame]:
        """
        补全缺失的股票数据（逐个请求，避免API限流）
        
        Args:
            missing_codes: 缺失的股票代码集合
            stock_list: 完整股票列表（用于查找名称）
            days: 需要的交易日数
            delay: 请求间隔（秒）
            
        Returns:
            补全获取到的数据 {股票代码: DataFrame}
        """
        if not missing_codes:
            return {}
        
        # 构建代码到名称的映射
        code_to_name = {s['code']: s['name'] for s in stock_list}
        
        complemented_data = {}
        success_count = 0
        fail_count = 0
        
        print(f"\n[补全机制] 开始补全 {len(missing_codes)} 只缺失股票...")
        print(f"  策略: 逐个请求，间隔 {delay}秒")
        
        for i, code in enumerate(sorted(missing_codes), 1):
            name = code_to_name.get(code, '未知')
            
            for attempt in range(self.retries):
                try:
                    df = self.get_stock_history(code, days=days)
                    
                    if df is not None and len(df) >= 15:
                        complemented_data[code] = df
                        success_count += 1
                        print(f"  [{i}/{len(missing_codes)}] ✓ {code} ({name}) - 补全成功")
                    else:
                        if attempt < self.retries - 1:
                            time.sleep(delay * (attempt + 1))
                        else:
                            fail_count += 1
                            print(f"  [{i}/{len(missing_codes)}] ✗ {code} ({name}) - 数据不足")
                    break
                    
                except Exception as e:
                    if attempt < self.retries - 1:
                        time.sleep(delay * (attempt + 1))
                    else:
                        fail_count += 1
                        print(f"  [{i}/{len(missing_codes)}] ✗ {code} ({name}) - 错误: {e}")
            
            # 请求间隔，避免API限流
            if i < len(missing_codes):
                time.sleep(delay)
        
        print(f"\n[补全机制] 完成: 成功 {success_count}, 失败 {fail_count}")
        return complemented_data
    
    def _final_verification(
        self,
        expected_count: int,
        success_count: int,
        fail_count: int,
        still_missing: set = None
    ) -> None:
        """
        最终验证并输出统计信息
        
        Args:
            expected_count: 预期股票总数
            success_count: 成功获取数量
            fail_count: 失败数量
            still_missing: 仍然缺失的股票代码
        """
        total_attempted = success_count + fail_count
        success_rate = (success_count / expected_count * 100) if expected_count > 0 else 0
        
        print(f"\n{'='*60}")
        print("【最终验证结果】")
        print(f"{'='*60}")
        print(f"  预期股票总数: {expected_count}")
        print(f"  成功获取数量: {success_count}")
        print(f"  失败数量:     {fail_count}")
        print(f"  成功率:       {success_rate:.2f}%")
        
        if still_missing:
            print(f"\n  仍然缺失的股票 ({len(still_missing)}只):")
            if len(still_missing) <= 20:
                print(f"    {', '.join(sorted(still_missing))}")
            else:
                missing_list = sorted(still_missing)
                print(f"    {', '.join(missing_list[:10])} ... (共{len(still_missing)}只)")
        
        if success_rate >= 100:
            print(f"\n  ★ 数据完整性: 100% - 所有股票均已获取！")
        elif success_rate >= 99:
            print(f"\n  ◆ 数据完整性: {success_rate:.2f}% - 接近完整")
        else:
            print(f"\n  ○ 数据完整性: {success_rate:.2f}% - 存在缺失")
        
        print(f"{'='*60}")
    
    def get_stock_history(
        self, 
        stock_code: str, 
        days: int = 400
    ) -> Optional[pd.DataFrame]:
        """获取单只股票的历史行情"""
        if self.use_mock:
            return self._get_mock_stock_history(stock_code, days)
        
        if self.use_local:
            return self._get_local_stock_history(stock_code, days)
        
        return self._get_api_stock_history(stock_code, days)
    
    def _get_mock_stock_history(self, stock_code: str, days: int) -> pd.DataFrame:
        """生成模拟K线数据"""
        # 模拟价格走势
        base_price = random.uniform(10, 100)
        dates = pd.date_range(end=datetime.now(), periods=days, freq='B')  # 工作日
        
        prices = []
        current_price = base_price
        
        for i in range(days):
            # 随机涨跌
            change = random.uniform(-0.05, 0.05)
            current_price = current_price * (1 + change)
            
            high = current_price * random.uniform(1.0, 1.03)
            low = current_price * random.uniform(0.97, 1.0)
            open_price = current_price * random.uniform(0.98, 1.02)
            volume = random.uniform(100000, 5000000)
            
            prices.append({
                'date': dates[i],
                'open': round(open_price, 2),
                'high': round(high, 2),
                'low': round(low, 2),
                'close': round(current_price, 2),
                'volume': int(volume),
                'asset': stock_code
            })
        
        return pd.DataFrame(prices)
    
    def _get_local_stock_history(self, stock_code: str, days: int) -> Optional[pd.DataFrame]:
        """从本地文件读取K线数据"""
        data_file = os.path.join(self.LOCAL_DATA_DIR, f'{stock_code}.csv')
        
        if not os.path.exists(data_file):
            # 禁用模拟数据fallback，返回None让调用方处理
            return None
        
        df = pd.read_csv(data_file)
        df['date'] = pd.to_datetime(df['date'])
        df['asset'] = stock_code
        
        # 确保有必要的列
        required_cols = ['date', 'open', 'high', 'low', 'close', 'volume', 'asset']
        df = df[required_cols]
        
        return df.tail(days)
    
    def _get_api_stock_history(self, stock_code: str, days: int) -> Optional[pd.DataFrame]:
        """从新浪财经API获取K线数据
        
        ⚠️ 量化系统必须使用真实数据，绝不使用模拟数据
        获取失败时返回None，让调用方处理
        """
        try:
            # 新浪API股票代码格式：sh600000（沪市）或 sz000001（深市）
            if stock_code.startswith('60'):
                symbol = f'sh{stock_code}'
            elif stock_code.startswith('00'):
                symbol = f'sz{stock_code}'
            else:
                return None
            
            # 新浪K线API参数
            # scale=240 表示日线
            # datalen 获取的数据条数
            params = {
                'symbol': symbol,
                'scale': 240,  # 日线
                'datalen': days + 50  # 多获取一些，确保有足够交易日
            }
            
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Accept': '*/*',
                'Referer': 'http://finance.sina.com.cn/',
            }
            
            response = self.session.get(
                self.KLINE_URL, 
                params=params, 
                headers=headers,
                timeout=self.timeout
            )
            response.raise_for_status()
            
            data = response.json()
            
            # 禁用模拟数据fallback：API返回数据为空时返回None
            if not data or not isinstance(data, list):
                return None
            
            # 新浪API返回格式：
            # [{'day': '2026-04-01', 'open': '10.50', 'high': '10.80', 'low': '10.40', 'close': '10.75', 'volume': '1234567'}, ...]
            rows = []
            for item in data:
                try:
                    rows.append({
                        'date': item.get('day', ''),
                        'open': float(item.get('open', 0)),
                        'close': float(item.get('close', 0)),
                        'high': float(item.get('high', 0)),
                        'low': float(item.get('low', 0)),
                        'volume': float(item.get('volume', 0)),
                    })
                except (ValueError, TypeError):
                    continue
            
            # 禁用模拟数据fallback：数据不足时返回None
            if len(rows) < 15:
                return None
            
            df = pd.DataFrame(rows)
            df['date'] = pd.to_datetime(df['date'])
            df['asset'] = stock_code
            
            cols = ['date', 'open', 'high', 'low', 'close', 'volume', 'asset']
            df = df[cols].sort_values('date').reset_index(drop=True)
            
            return df.tail(days)
                
        except Exception:
            # 禁用模拟数据fallback：异常时返回None
            return None
    
    def _fetch_single_stock_with_retry(
        self, 
        stock_info: Dict, 
        days: int,
        delay: float = 0.05
    ) -> Tuple[str, Optional[pd.DataFrame]]:
        """带重试机制获取单只股票数据"""
        code = stock_info['code']
        
        with self._lock:
            self._request_count += 1
            request_id = self._request_count
        
        time.sleep(delay * (1 + (request_id % 20) * 0.005))
        
        for attempt in range(self.retries):
            try:
                df = self.get_stock_history(code, days=days)
                if df is not None and len(df) >= 15:
                    return (code, df)
                else:
                    if attempt < self.retries - 1:
                        time.sleep(0.3 * (attempt + 1))
            except Exception as e:
                if attempt < self.retries - 1:
                    time.sleep(0.5 * (attempt + 1))
        
        return (code, None)
    
    def _fetch_stock_batch(
        self, 
        stock_batch: List[Dict], 
        days: int,
        progress_callback: Optional[callable] = None
    ) -> List[Tuple[str, Optional[pd.DataFrame]]]:
        """获取一批股票的数据（串行获取，带延迟）"""
        results = []
        for i, stock_info in enumerate(stock_batch):
            result = self._fetch_single_stock_with_retry(stock_info, days, delay=0.1)
            results.append(result)
            if progress_callback:
                progress_callback(result[0], result[1] is not None)
        return results
    
    def _fetch_stock_batch_parallel(
        self, 
        stocks_for_thread_a: List[Dict], 
        stocks_for_thread_b: List[Dict],
        days: int,
        progress_callback: Optional[callable] = None
    ) -> List[Tuple[str, Optional[pd.DataFrame]]]:
        """
        使用2个线程并行获取股票数据
        线程A处理前半部分，线程B处理后半部分
        每线程处理数量由调用方控制（默认50只）
        """
        all_results = []
        
        with ThreadPoolExecutor(max_workers=2) as executor:
            future_a = executor.submit(
                self._fetch_stock_batch, 
                stocks_for_thread_a, 
                days, 
                progress_callback
            )
            future_b = executor.submit(
                self._fetch_stock_batch, 
                stocks_for_thread_b, 
                days, 
                progress_callback
            )
            
            # 等待两个线程都完成
            results_a = future_a.result()
            results_b = future_b.result()
            
            all_results.extend(results_a)
            all_results.extend(results_b)
        
        return all_results
    
    def load_data_multithreaded(
        self,
        n_days: int = 250,
        max_stocks: int = 0,
        batch_size: int = 50,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        enable_complement: bool = True
    ) -> Tuple[pd.DataFrame, pd.DataFrame]:
        """
        分批多线程加载真实数据（避免API限流 + 数据完整性保障 + 缓存优化）
        
        缓存策略（新增）：
        - 当天首次拉取后缓存到本地（gzip 压缩）
        - 后续计算直接读取缓存
        - 缓存文件按日期命名：factor_data_YYYYMMDD.json.gz
        - 缓存校验：数据条数、股票覆盖率、日期范围、异常值检查
        
        并发策略：
        - 每批次启动2个线程并行
        - 线程A处理前50只股票（默认）
        - 线程B处理后50只股票（默认）
        - 等前两线程完成后，再启动下一批
        - 批次间添加2秒延迟
        
        完整性保障：
        - 每日缓存股票清单
        - 获取完成后完整性校验
        - 自动补全缺失股票
        - 最终验证输出统计
        
        Args:
            n_days: 需要的交易日数量
            max_stocks: 最大股票数量（0表示获取全部主板股票，约3000+只）
            batch_size: 每个线程处理的股票数量（默认50，建议范围50-80）
            start_date: 开始日期
            end_date: 结束日期
            enable_complement: 是否启用补全机制（默认True）
            
        Returns:
            (factor_df, return_df)
        """
        if end_date is None:
            end_date = datetime.now().strftime('%Y-%m-%d')
        if start_date is None:
            start_date = (datetime.now() - timedelta(days=int(n_days * 1.5) + 30)).strftime('%Y-%m-%d')
        
        print(f"\n{'='*60}")
        print("开始加载真实数据（分批并发版本 + 完整性保障 + 缓存优化）")
        print(f"{'='*60}")
        print(f"  日期范围: {start_date} ~ {end_date}")
        print(f"  目标交易日数: {n_days}")
        print(f"  并发策略: 每批2线程，每线程{batch_size}只股票")
        print(f"  完整性保障: {'启用' if enable_complement else '禁用'}")
        print(f"  缓存策略: {'启用' if self.enable_cache else '禁用'}（gzip压缩）")
        if self.use_mock:
            print("  数据源: 模拟数据")
        elif self.use_local:
            print("  数据源: 本地文件")
        else:
            print("  数据源: 新浪财经API")
        
        # ========== Step 0: 增量缓存检查 ==========
        factor_cache_path = self._get_factor_cache_path()
        return_cache_path = self._get_return_cache_path()
        
        existing_cache = None
        cache_start_date = None
        cache_end_date = None
        need_fetch_start_date = None  # 需要拉取的起始日期
        
        if self.enable_cache and max_stocks == 0:
            print(f"\n[增量缓存检查] 检查现有缓存...")
            print(f"  因子缓存: {factor_cache_path}")
            print(f"  收益缓存: {return_cache_path}")
            
            if os.path.exists(factor_cache_path) and os.path.exists(return_cache_path):
                print(f"  ✓ 缓存文件存在")
                
                # 加载缓存
                factor_cache_data = self._load_cache_gzip(factor_cache_path)
                return_cache_data = self._load_cache_gzip(return_cache_path)
                
                if factor_cache_data and return_cache_data:
                    # 获取缓存日期范围
                    cache_start_date, cache_end_date = self._get_cache_date_range(factor_cache_data)
                    
                    if cache_start_date and cache_end_date:
                        print(f"  缓存日期范围: {cache_start_date} ~ {cache_end_date}")
                        
                        # 【修复】优先校验缓存数据是否满足交易日数要求
                        # 不再强制要求 cache_end_date >= today_str
                        # 只要缓存满足 n_days 要求且校验通过，就直接使用
                        factor_meta = factor_cache_data.get('meta', {})
                        cache_n_days = factor_meta.get('n_days', 0)
                        
                        today_str = datetime.now().strftime('%Y-%m-%d')
                        
                        # 判断缓存是否有效（满足交易日数要求）
                        if cache_n_days >= n_days:
                            # 缓存满足交易日数要求
                            print(f"  ✓ 缓存交易日数满足要求: {cache_n_days} >= {n_days}")
                            
                            # 校验缓存有效性
                            if self.validate_cache(factor_cache_data, return_cache_data, n_days):
                                print(f"\n[缓存] ✓ 使用缓存数据，跳过API拉取")
                                
                                # 如果缓存日期落后，提示用户
                                if cache_end_date < today_str:
                                    days_behind = (datetime.now() - datetime.strptime(cache_end_date, '%Y-%m-%d')).days
                                    print(f"  ⚠ 缓存数据落后 {days_behind} 天（{cache_end_date} vs {today_str}）")
                                    print(f"  如需最新数据，请手动触发全量更新")
                                
                                # 直接从缓存构建 DataFrame
                                factor_df = pd.DataFrame(factor_cache_data['data'])
                                return_df = pd.DataFrame(return_cache_data['data'])
                                
                                # 内存优化：转换为 category 类型
                                factor_df['date'] = factor_df['date'].astype('category')
                                factor_df['asset'] = factor_df['asset'].astype('category')
                                return_df['date'] = return_df['date'].astype('category')
                                return_df['asset'] = return_df['asset'].astype('category')
                                
                                # 输出统计信息
                                dates = sorted(factor_df['date'].unique())
                                assets = factor_df['asset'].unique()
                                print(f"\n{'='*60}")
                                print("数据加载完成（来自缓存）")
                                print(f"{'='*60}")
                                print(f"  交易日数: {len(dates)}")
                                print(f"  股票数量: {len(assets)}")
                                print(f"  总记录数: {len(factor_df)}")
                                print(f"  日期范围: {dates[0]} ~ {dates[-1]}")
                                print(f"  加载耗时: <5秒（缓存读取）")
                                print(f"{'='*60}")
                                
                                return factor_df, return_df
                            else:
                                print(f"  ✗ 缓存校验失败，将全量拉取")
                                cache_start_date = None
                                cache_end_date = None
                        else:
                            # 缓存交易日数不足，需要增量更新
                            print(f"  缓存交易日数不足: {cache_n_days} < {n_days}")
                            
                            # 检查是否可以增量更新
                            factor_records = factor_cache_data.get('data', [])
                            return_records = return_cache_data.get('data', [])
                            
                            if len(factor_records) > 0 and len(return_records) > 0:
                                print(f"  需要增量更新: {cache_end_date} -> {today_str}")
                                existing_cache = {
                                    'factor': factor_cache_data,
                                    'return': return_cache_data
                                }
                                # 计算增量起始日期（缓存结束日期的下一天）
                                need_fetch_start_date = cache_end_date
                            else:
                                print(f"  ✗ 缓存数据为空，将全量拉取")
                                cache_start_date = None
                                cache_end_date = None
                    else:
                        print(f"  ✗ 缓存日期范围无效，将全量拉取")
                else:
                    print(f"  ✗ 缓存读取失败，将全量拉取")
            else:
                print(f"  ✗ 缓存文件不存在，将全量拉取")
        
        # ========== Step 1: 获取股票清单 ==========
        stock_list = None
        
        # 尝试从缓存加载
        if self.enable_cache:
            stock_list = self._load_stock_list_cache()
        
        # 缓存不存在或不是今天，重新获取
        if stock_list is None:
            stock_list = self.get_main_board_stocks(max_stocks=max_stocks)
            # 保存到缓存
            if self.enable_cache and max_stocks == 0:
                self._save_stock_list_cache(stock_list)
        else:
            print(f"[缓存] 使用缓存中的股票清单")
        
        total_stocks = len(stock_list)
        
        if total_stocks == 0:
            raise RuntimeError("未获取到任何股票")
        
        # 按每批200只（2线程 x 100只）分批
        stocks_per_batch = batch_size * 2  # 每批200只
        num_batches = (total_stocks + stocks_per_batch - 1) // stocks_per_batch
        
        print(f"\n[获取行情数据] 分批并发获取...")
        print(f"  总股票数: {total_stocks}")
        
        # 增量更新：只拉取少量数据
        if need_fetch_start_date and existing_cache:
            # 增量模式：只拉取 15 天数据（足够计算 RSI）
            fetch_days = 15
            print(f"  增量拉取模式: 只拉取最近 {fetch_days} 天数据")
            print(f"  增量起始日期: {need_fetch_start_date}")
        else:
            # 全量拉取模式
            stocks_per_batch = batch_size * 2  # 每批200只
            num_batches = (total_stocks + stocks_per_batch - 1) // stocks_per_batch
            fetch_days = int(n_days * 1.5) + 30
            print(f"  全量拉取模式: 拉取 {fetch_days} 天数据")
            print(f"  每批数量: {stocks_per_batch}只（2线程 x {batch_size}只）")
            print(f"  总批次数: {num_batches}")
        
        stocks_per_batch = batch_size * 2
        num_batches = (total_stocks + stocks_per_batch - 1) // stocks_per_batch
        
        success_count = 0
        fail_count = 0
        failed_codes = []
        all_data_dict = {}  # 使用字典存储，便于完整性校验
        
        start_time = time.time()
        
        def progress_callback(code, success):
            nonlocal success_count, fail_count
            if success:
                success_count += 1
            else:
                fail_count += 1
                failed_codes.append(code)
        
        # ========== Step 2: 分批获取数据 ==========
        for batch_idx in range(num_batches):
            batch_start_idx = batch_idx * stocks_per_batch
            batch_end_idx = min(batch_start_idx + stocks_per_batch, total_stocks)
            
            # 分配给两个线程
            mid_idx = batch_start_idx + batch_size
            thread_a_stocks = stock_list[batch_start_idx:min(mid_idx, batch_end_idx)]
            thread_b_stocks = stock_list[min(mid_idx, batch_end_idx):batch_end_idx] if mid_idx < batch_end_idx else []
            
            batch_start_time = time.time()
            print(f"\n  [批次 {batch_idx + 1}/{num_batches}] "
                  f"股票 {batch_start_idx + 1}-{batch_end_idx} "
                  f"(线程A: {len(thread_a_stocks)}只, 线程B: {len(thread_b_stocks)}只)")
            
            # 执行本批次（2线程并行）
            batch_results = self._fetch_stock_batch_parallel(
                thread_a_stocks, 
                thread_b_stocks,
                fetch_days, 
                progress_callback
            )
            
            # 收集结果到字典
            for code, df in batch_results:
                if df is not None:
                    all_data_dict[code] = df
            
            batch_elapsed = time.time() - batch_start_time
            total_elapsed = time.time() - start_time
            completed = success_count + fail_count
            
            # 进度显示
            rate = completed / total_elapsed if total_elapsed > 0 else 0
            eta = (total_stocks - completed) / rate if rate > 0 else 0
            print(f"    进度: {completed}/{total_stocks} "
                  f"(成功: {success_count}, 失败: {fail_count}) "
                  f"[批次耗时: {batch_elapsed:.1f}s, 总耗时: {total_elapsed:.1f}s, ETA: {eta:.0f}s]")
            
            # 批次间延迟（最后一批不延迟）
            if batch_idx < num_batches - 1:
                delay = 2.0  # 2秒延迟，避免API限流
                print(f"    等待 {delay}秒 后开始下一批...")
                time.sleep(delay)
        
        elapsed_time = time.time() - start_time
        print(f"\n  ✓ 第一阶段获取完成，总耗时 {elapsed_time:.1f} 秒")
        print(f"  ✓ 成功: {success_count} 只，失败: {fail_count} 只")
        
        # ========== Step 3: 完整性校验 ==========
        print(f"\n[完整性校验] 检查数据完整性...")
        missing_codes, success_codes = self._verify_data_completeness(stock_list, all_data_dict)
        
        initial_missing_count = len(missing_codes)
        initial_success_count = len(success_codes)
        
        if initial_missing_count > 0:
            print(f"  发现缺失股票: {initial_missing_count} 只")
            if initial_missing_count <= 20:
                print(f"  缺失代码: {', '.join(sorted(missing_codes))}")
        else:
            print(f"  ✓ 数据完整，无缺失股票")
        
        # ========== Step 4: 补全机制 ==========
        complement_success = 0
        complement_fail = 0
        
        if enable_complement and initial_missing_count > 0:
            print(f"\n[补全机制] 开始补全 {initial_missing_count} 只缺失股票...")
            
            complement_data = self._complement_missing_stocks(
                missing_codes,
                stock_list,
                fetch_days,
                delay=1.5  # 补全时使用1.5秒间隔
            )
            
            # 合并补全的数据
            for code, df in complement_data.items():
                all_data_dict[code] = df
                complement_success += 1
            
            complement_fail = initial_missing_count - complement_success
            
            # ========== Step 5: 再次校验 ==========
            print(f"\n[二次校验] 验证补全结果...")
            final_missing, final_success = self._verify_data_completeness(stock_list, all_data_dict)
            
            final_success_count = len(final_success)
            final_fail_count = len(final_missing)
        else:
            final_missing = missing_codes
            final_success_count = initial_success_count
            final_fail_count = initial_missing_count
        
        # ========== Step 6: 最终验证输出 ==========
        self._final_verification(
            expected_count=total_stocks,
            success_count=len(all_data_dict),
            fail_count=final_fail_count,
            still_missing=final_missing if final_fail_count > 0 else None
        )
        
        if not all_data_dict:
            raise RuntimeError("无法获取任何股票数据")
        
        # 转换字典为列表
        all_data = list(all_data_dict.values())
        
        # ========== Step 7: 合并数据并计算因子（向量化优化版） ==========
        print(f"\n[数据处理] 合并并计算因子（向量化优化版）...")
        step_start = time.time()
        
        combined = pd.concat(all_data, ignore_index=True)
        print(f"  合并完成，总记录数: {len(combined)}")
        
        # 日期筛选
        if need_fetch_start_date and existing_cache:
            # 增量模式：只保留新增日期的数据（往前推 7 天用于 RSI 计算）
            incremental_start = pd.to_datetime(need_fetch_start_date) - timedelta(days=7)
            end_dt = pd.to_datetime(end_date)
            combined = combined[(combined['date'] >= incremental_start) & (combined['date'] <= end_dt)]
            print(f"  增量模式日期筛选: {incremental_start.strftime('%Y-%m-%d')} ~ {end_date}")
            print(f"  筛选后记录数: {len(combined)}")
        else:
            # 全量模式：使用原始日期范围
            start_dt = pd.to_datetime(start_date)
            end_dt = pd.to_datetime(end_date)
            combined = combined[(combined['date'] >= start_dt) & (combined['date'] <= end_dt)]
            print(f"  全量模式日期筛选: {start_date} ~ {end_date}")
            print(f"  筛选后记录数: {len(combined)}")
        
        # ========== Step 7.1: 计算涨跌停价（用于后续动态过滤） ==========
        # 新策略：缓存完整数据，不在此处剔除异常股票
        # 异常股票的过滤移至 IC 计算、分层回测阶段动态执行
        
        print(f"\n[数据状态预处理] 计算涨跌停价...")
        
        # 加载股票名称映射（用于后续判断 ST）
        code_to_name = {}
        stock_list_cache_path = self._get_stock_list_cache_path()
        if os.path.exists(stock_list_cache_path):
            try:
                with open(stock_list_cache_path, 'r', encoding='utf-8') as f:
                    stock_cache = json.load(f)
                stocks_list = stock_cache.get('stocks', [])
                code_to_name = {s['code']: s['name'] for s in stocks_list}
                print(f"  加载股票名称映射: {len(code_to_name)} 只股票")
            except Exception as e:
                print(f"  ⚠ 加载股票名称映射失败: {e}")
        
        # 按股票分组排序
        combined = combined.sort_values(['asset', 'date'])
        
        # 标准化日期格式（确保按天统计）
        combined['date'] = pd.to_datetime(combined['date']).dt.normalize()
        
        # 计算前一日收盘价
        combined['prev_close'] = combined.groupby('asset')['close'].shift(1)
        
        # 计算涨停价和跌停价
        combined['limit_up_price'] = combined['prev_close'] * 1.10
        combined['limit_down_price'] = combined['prev_close'] * 0.90
        
        # ========== Step 7.2: 保存交易状态缓存（用于后续动态过滤） ==========
        # 缓存每只股票每日的交易状态信息
        # 包含：volume, close, prev_close, limit_up_price, limit_down_price
        
        print(f"\n[状态缓存] 保存交易状态数据...")
        status_df = combined[['date', 'asset', 'volume', 'close', 'prev_close', 'limit_up_price', 'limit_down_price']].copy()
        
        # 格式化日期
        status_df['date'] = status_df['date'].dt.strftime('%Y-%m-%d')
        
        # 保存状态缓存
        if self.enable_cache and max_stocks == 0:
            status_cache_path = self._get_status_cache_path()
            
            if existing_cache and os.path.exists(status_cache_path):
                # 增量更新：合并现有状态数据和新状态数据
                existing_status = self._load_cache_gzip(status_cache_path)
                if existing_status:
                    existing_records = existing_status.get('data', [])
                    existing_status_df = pd.DataFrame(existing_records) if existing_records else pd.DataFrame()
                    
                    if len(existing_status_df) > 0:
                        combined_status_df = pd.concat([existing_status_df, status_df], ignore_index=True)
                        # 去重：同一股票同一日期只保留最新数据
                        combined_status_df = combined_status_df.drop_duplicates(
                            subset=['date', 'asset'], 
                            keep='last'
                        ).sort_values(['date', 'asset']).reset_index(drop=True)
                        status_df = combined_status_df
            
            dates_list = sorted(status_df['date'].unique())
            assets_list = list(status_df['asset'].unique())
            
            status_cache_data = {
                'meta': {
                    'generated_at': datetime.now().isoformat(),
                    'source': 'sina_api',
                    'n_days': len(dates_list),
                    'n_assets': len(assets_list),
                    'date_range': {
                        'start': dates_list[0] if dates_list else None,
                        'end': dates_list[-1] if dates_list else None
                    },
                    'last_updated': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                    'version': '1.0',
                    'description': '交易状态缓存，用于动态过滤异常股票'
                },
                'data': status_df.to_dict('records')
            }
            
            self._save_cache_gzip(status_cache_path, status_cache_data)
            print(f"  ✓ 状态缓存已保存: {status_cache_path}")
        
        # ========== Step 7.3: 保留完整数据（不再剔除异常股票） ==========
        # 新策略：缓存完整原始数据，异常股票在 IC 计算、分层回测时动态过滤
        
        print(f"\n[数据缓存策略] 保留完整数据，异常股票将在后续动态过滤")
        print(f"  当前数据量: {len(combined):,} 条")
        print(f"  包含所有股票（含停牌、ST、涨停、跌停）")
        
        # 注意：不再剔除异常股票，保留 prev_close, limit_up_price, limit_down_price
        # 这些列将在后续因子计算中被清理
        
        # 向量化计算因子（替代逐股票循环）
        # 1. 按股票分组排序
        combined = combined.sort_values(['asset', 'date'])
        
        # 2. 向量化计算 RSI（使用 groupby + transform）
        print(f"\n[因子计算] 计算 RSI(6)...")
        combined['rsi_6'] = combined.groupby('asset')['close'].transform(
            lambda x: self._calculate_rsi_vectorized(x, period=6)
        )
        
        # 2.1. 向量化计算量比(5)（当日成交量 / 过去5日平均成交量）
        print(f"  计算量比(5)...")
        combined['volume_ratio_5'] = combined.groupby('asset')['volume'].transform(
            lambda x: x / x.rolling(window=5).mean()
        )
        # 处理缺失值和极值
        combined['volume_ratio_5'] = combined['volume_ratio_5'].fillna(1.0)  # 缺失值填充为1（正常）
        combined['volume_ratio_5'] = combined['volume_ratio_5'].clip(0.1, 10)  # 裁剪到合理范围
        
        # 输出量比统计信息
        vr_min = combined['volume_ratio_5'].min()
        vr_max = combined['volume_ratio_5'].max()
        vr_mean = combined['volume_ratio_5'].mean()
        print(f"  量比范围: [{vr_min:.2f}, {vr_max:.2f}]")
        print(f"  量比均值: {vr_mean:.2f}")
        
        # 3. 向量化计算 forward_return
        print(f"  计算前瞻收益...")
        # 按股票分组计算收益率，然后 shift(-1) 得到前瞻收益
        combined['forward_return'] = combined.groupby('asset')['close'].transform(
            lambda x: x.pct_change().shift(-1)
        )
        
        # 4. 去除缺失值（因子或收益缺失）
        valid_df = combined.dropna(subset=['rsi_6', 'volume_ratio_5', 'forward_return'])
        print(f"  去除缺失值后记录数: {len(valid_df)}")
        
        # 5. 限制每只股票的数据范围
        if need_fetch_start_date and existing_cache:
            # 增量模式：只保留新增日期的数据（need_fetch_start_date 之后）
            print(f"  增量模式: 只保留 {need_fetch_start_date} 之后的数据...")
            new_date_threshold = pd.to_datetime(need_fetch_start_date)
            valid_df = valid_df[valid_df['date'] >= new_date_threshold]
            print(f"  增量数据记录数: {len(valid_df)}")
        else:
            # 全量模式：限制每只股票最多保留 n_days 条数据
            print(f"  全量模式: 限制每只股票最多 {n_days} 天数据...")
            # pandas 3.0 兼容性修复：使用 cumcount 替代 groupby().apply(tail)
            # 避免 group_keys=False 导致分组列被移除
            valid_df['row_num'] = valid_df.groupby('asset').cumcount(ascending=False)
            valid_df = valid_df[valid_df['row_num'] < n_days].drop('row_num', axis=1)
            print(f"  限制后记录数: {len(valid_df)}")
        
        # 6. 格式化输出（向量化）
        print(f"  格式化输出...")
        valid_df['date'] = valid_df['date'].dt.strftime('%Y-%m-%d')
        valid_df['open'] = valid_df['open'].round(2)
        valid_df['close'] = valid_df['close'].round(2)
        valid_df['high'] = valid_df['high'].round(2)
        valid_df['low'] = valid_df['low'].round(2)
        valid_df['rsi_6'] = valid_df['rsi_6'].round(2)
        valid_df['volume_ratio_5'] = valid_df['volume_ratio_5'].round(2)  # 新增量比格式化
        valid_df['forward_return'] = valid_df['forward_return'].round(6)
        
        # 7. 构建因子和收益 DataFrame（直接切片，无需循环）
        # 包含 open, close, high, low 用于后续选股回测系统计算 T+1 开盘涨幅、最高收益等指标
        factor_df = valid_df[['date', 'asset', 'open', 'close', 'high', 'low', 'rsi_6', 'volume_ratio_5']].copy()
        return_df = valid_df[['date', 'asset', 'forward_return']].copy()
        
        # 内存优化：释放中间变量
        del valid_df, combined
        import gc
        gc.collect()
        
        step_elapsed = time.time() - step_start
        print(f"  因子计算耗时: {step_elapsed:.2f} 秒")
        
        # ========== Step 8: 保存缓存（增量合并） ==========
        if self.enable_cache and max_stocks == 0:
            print(f"\n[缓存保存] 保存数据到缓存文件...")
            
            factor_cache_path = self._get_factor_cache_path()
            return_cache_path = self._get_return_cache_path()
            
            if existing_cache:
                # 增量更新：合并现有数据和新数据
                print(f"  增量更新模式: 合并现有数据和新数据")
                factor_cache_data, return_cache_data = self._merge_cache_data(
                    existing_cache,
                    factor_df,
                    return_df
                )
            else:
                # 全量拉取：直接构建缓存数据
                dates_list = sorted(factor_df['date'].unique())
                assets_list = list(factor_df['asset'].unique())
                
                factor_cache_data = {
                    'meta': {
                        'generated_at': datetime.now().isoformat(),
                        'source': 'sina_api',
                        'n_days': len(dates_list),
                        'n_assets': len(assets_list),
                        'date_range': {
                            'start': dates_list[0],
                            'end': dates_list[-1]
                        },
                        'last_updated': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                        'version': '3.1'
                    },
                    'data': factor_df.to_dict('records')
                }
                
                return_cache_data = {
                    'meta': {
                        'generated_at': datetime.now().isoformat(),
                        'source': 'sina_api',
                        'n_days': len(dates_list),
                        'n_assets': len(assets_list),
                        'date_range': {
                            'start': dates_list[0],
                            'end': dates_list[-1]
                        },
                        'last_updated': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                        'version': '3.1'
                    },
                    'data': return_df.to_dict('records')
                }
            
            # 显示合并/保存信息
            meta = factor_cache_data['meta']
            print(f"  日期范围: {meta['date_range']['start']} ~ {meta['date_range']['end']}")
            print(f"  交易日数: {meta['n_days']}, 股票数量: {meta['n_assets']}")
            
            # 使用 gzip 压缩保存
            self._save_cache_gzip(factor_cache_path, factor_cache_data)
            self._save_cache_gzip(return_cache_path, return_cache_data)
        
        dates = sorted(factor_df['date'].unique())
        assets = factor_df['asset'].unique()
        print(f"\n{'='*60}")
        print("数据加载完成")
        print(f"{'='*60}")
        print(f"  交易日数: {len(dates)}")
        print(f"  股票数量: {len(assets)}")
        print(f"  总记录数: {len(factor_df)}")
        print(f"  日期范围: {dates[0]} ~ {dates[-1]}")
        
        return factor_df, return_df
    
    def calculate_rsi(
        self, 
        close_prices: pd.Series, 
        period: int = 6
    ) -> pd.Series:
        """计算 RSI 指标"""
        return self._calculate_rsi_vectorized(close_prices, period)
    
    def _calculate_rsi_vectorized(
        self,
        close_prices: pd.Series,
        period: int = 6
    ) -> pd.Series:
        """
        向量化计算 RSI 指标
        
        使用 Wilder 标准（前 period 天 SMA 种子，之后 EWM 递推），
        避免 Python 循环，提升性能。
        
        边界处理（遵循 Wilder 1978 标准）：
        1. avg_loss=0 且 avg_gain>0 → RSI=100（超买）
        2. avg_loss=0 且 avg_gain=0 → RSI=50（中性）
        3. avg_loss>0 → 正常计算 RS
        
        注意：
        - avg_loss 接近零时，直接除法会产生 inf，需分场景处理
        - 使用 EPSILON 判断零值（相对 avg_loss 量级极小）
        - avg_loss 和 avg_gain 理论上非负，使用 .abs() 是防御性代码
        """
        EPSILON = 1e-10  # 零值阈值
        
        delta = close_prices.diff()
        gain = delta.where(delta > 0, 0)
        loss = (-delta).where(delta < 0, 0)
        
        # Wilder 标准 RSI 计算（前 period 天 SMA 种子，之后 EWM 递推）
        # pandas ewm(adjust=False) 从第一个观测值就开始计算，
        # 但 Wilder 标准要求前 n 天用 SMA 种子，之后才 EWM 递推
        
        def _wilder_smoothing(series: pd.Series, n: int) -> pd.Series:
            """Wilder 平滑（前 n 天 SMA 种子，之后 EWM 递推）"""
            # 前 n 天 SMA 种子
            sma_seed = series.iloc[:n].mean()
            
            # 从第 n 天开始 EWM 递推
            ewm_part = series.iloc[n:].ewm(alpha=1/n, adjust=False).mean()
            
            # 合并：前 n 天用 SMA 种子填充，之后用 EWM
            result = pd.Series(index=series.index, dtype=float)
            result.iloc[:n] = sma_seed
            result.iloc[n:] = ewm_part
            
            return result
        
        avg_gain = _wilder_smoothing(gain, period)
        avg_loss = _wilder_smoothing(loss, period)
        
        # 边界处理：avg_loss 接近零时
        # 防御性代码：使用 .abs() 防止数值误差产生负值
        zero_loss_mask = avg_loss.notna() & (avg_loss.abs() < EPSILON)
        zero_gain_mask = avg_gain.notna() & (avg_gain.abs() < EPSILON)
        
        # 同时为零：avg_gain=0 且 avg_loss=0 → RSI=50（中性）
        both_zero_mask = zero_loss_mask & zero_gain_mask
        
        # 只有 avg_loss 接近零（avg_gain>0）→ RSI=100（超买）
        only_zero_loss_mask = zero_loss_mask & ~zero_gain_mask
        
        # RS 计算（避免中间污染值）
        safe_avg_loss = avg_loss.where(avg_loss > EPSILON)
        rs = avg_gain / safe_avg_loss
        rsi_raw = 100 - (100 / (1 + rs))
        rsi = rsi_raw.where(rs.notna())
        
        # 边界处理覆盖（必须在 RS 计算后）
        rsi.loc[only_zero_loss_mask] = 100  # avg_loss=0, avg_gain>0 → 超买
        rsi.loc[both_zero_mask] = 50         # avg_loss=0, avg_gain=0 → 中性
        
        # 处理缺失值和边界值
        # 缺失值填充为中性值（遵循 MODULE.md 边界处理规范）
        rsi = rsi.fillna(50)
        # clip 确保范围在 0-100（计算误差可能导致越界）
        rsi = rsi.clip(0, 100)
        
        return rsi
    
    def _load_status_cache(self) -> Optional[dict]:
        """加载交易状态缓存"""
        status_cache_path = self._get_status_cache_path()
        if os.path.exists(status_cache_path):
            return self._load_cache_gzip(status_cache_path)
        return None
    
    def _load_stock_names(self) -> Dict[str, str]:
        """加载股票名称映射"""
        stock_list_cache_path = self._get_stock_list_cache_path()
        if os.path.exists(stock_list_cache_path):
            try:
                with open(stock_list_cache_path, 'r', encoding='utf-8') as f:
                    stock_cache = json.load(f)
                stocks_list = stock_cache.get('stocks', [])
                return {s['code']: s['name'] for s in stocks_list}
            except Exception:
                return {}
        return {}
    
    def filter_abnormal_stocks_dynamic(
        self,
        factor_df: pd.DataFrame,
        return_df: pd.DataFrame,
        factor_col: str = 'rsi_6',
        return_col: str = 'forward_return',
        status_cache: Optional[dict] = None,
        code_to_name: Optional[Dict[str, str]] = None
    ) -> Tuple[pd.DataFrame, pd.DataFrame, dict]:
        """
        动态过滤异常股票（用于 IC 计算、分层回测）
        
        过滤条件：
        1. 当日停牌：成交量 = 0 或缺失
        2. 当日ST：股票名称含 "ST"
        3. 当日涨停：收盘价 >= 涨停价 × 0.998
        4. 当日跌停：收盘价 <= 跌停价 × 1.002
        
        Args:
            factor_df: 因子数据
            return_df: 收益数据
            factor_col: 因子列名
            return_col: 收益列名
            status_cache: 交易状态缓存（可选，自动加载）
            code_to_name: 股票名称映射（可选，自动加载）
            
        Returns:
            (filtered_factor_df, filtered_return_df, filter_stats)
        """
        print(f"\n[动态过滤异常股票] 开始处理...")
        
        # 加载状态缓存
        if status_cache is None:
            status_cache = self._load_status_cache()
        
        if status_cache is None:
            print(f"  ⚠ 交易状态缓存不存在，跳过动态过滤")
            return factor_df, return_df, {'total_removed': 0}
        
        # 加载股票名称映射
        if code_to_name is None:
            code_to_name = self._load_stock_names()
        
        # 从状态缓存构建 DataFrame
        status_records = status_cache.get('data', [])
        if not status_records:
            print(f"  ⚠ 状态缓存数据为空，跳过动态过滤")
            return factor_df, return_df, {'total_removed': 0}
        
        status_df = pd.DataFrame(status_records)
        
        # 只保留状态缓存中需要的列，避免 close 列冲突
        status_cols = ['date', 'asset', 'volume', 'limit_up_price', 'limit_down_price']
        status_df = status_df[status_cols].copy() if all(c in status_df.columns for c in status_cols) else status_df
        
        # 合并因子和收益数据
        merged = pd.merge(factor_df, return_df, on=['date', 'asset'], how='inner')
        print(f"  合并后数据量: {len(merged)} 条")
        
        # 合并状态信息
        merged_with_status = pd.merge(
            merged,
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
        
        # 2. 过滤 ST 股票（向量化优化）
        if code_to_name:
            # 向量化构建 ST 标识
            merged_with_status['stock_name'] = merged_with_status['asset'].map(code_to_name)
            st_mask = merged_with_status['stock_name'].str.contains('ST', case=False, na=False)
            filter_stats['st_stocks'] = st_mask.sum()
            merged_with_status = merged_with_status[~st_mask]
            merged_with_status = merged_with_status.drop(columns=['stock_name'], errors='ignore')
        
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
        print("【动态过滤异常股票统计】")
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
        
        # 构建过滤后的因子和收益 DataFrame
        filtered_factor_df = merged_with_status[['date', 'asset', factor_col]].copy()
        filtered_return_df = merged_with_status[['date', 'asset', return_col]].copy()
        
        return filtered_factor_df, filtered_return_df, filter_stats
    
    @staticmethod
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
    
    def calculate_rank_ic(
        self,
        factor_df: pd.DataFrame,
        return_df: pd.DataFrame,
        factor_col: str = 'rsi_6',
        return_col: str = 'forward_return',
        enable_filter: bool = True,
        enable_winsorize: bool = True
    ) -> pd.DataFrame:
        """
        计算 Rank IC（支持动态过滤异常股票 + 去极值处理）
        
        Args:
            factor_df: 因子数据
            return_df: 收益数据
            factor_col: 因子列名
            return_col: 收益列名
            enable_filter: 是否启用动态过滤异常股票（默认True）
            enable_winsorize: 是否启用去极值处理（默认True）
            
        Returns:
            IC DataFrame
        """
        print(f"\n[计算 Rank IC] 基于 {factor_col} 因子...")
        print(f"  动态过滤: {'启用' if enable_filter else '禁用'}")
        print(f"  去极值: {'启用' if enable_winsorize else '禁用'}")
        
        # 动态过滤异常股票
        if enable_filter:
            factor_df, return_df, filter_stats = self.filter_abnormal_stocks_dynamic(
                factor_df, return_df, factor_col, return_col
            )
            if len(factor_df) == 0:
                print("  ! 过滤后数据为空，无法计算 IC")
                return pd.DataFrame()
        
        merged = pd.merge(factor_df, return_df, on=['date', 'asset'], how='inner')
        
        # 去极值处理（逐日进行）
        if enable_winsorize:
            print(f"\n[去极值处理] 对每日因子值进行分位数法去极值...")
            winsorize_stats_list = []
            
            # 对每一天的因子值独立进行去极值
            merged['factor_winsorized'] = merged.groupby('date')[factor_col].transform(
                lambda x: self.winsorize_factor(x.values)[0]
            )
            
            # 统计去极值信息
            for date, group in merged.groupby('date'):
                original_values = group[factor_col].values
                _, stats = self.winsorize_factor(original_values)
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
            
            # 使用去极值后的因子值计算 IC
            factor_col_for_ic = 'factor_winsorized'
        else:
            factor_col_for_ic = factor_col
        
        print(f"\n  计算每日 IC...")
        
        ic_results = []
        
        for date, group in merged.groupby('date'):
            if len(group) < 10:
                continue
            
            factor_ranks = group[factor_col_for_ic].rank()
            return_ranks = group[return_col].rank()
            
            ic = factor_ranks.corr(return_ranks, method='pearson')
            
            ic_results.append({
                'date': date,
                'ic': ic,
                'n_stocks': len(group)
            })
        
        ic_df = pd.DataFrame(ic_results)
        
        if len(ic_df) == 0:
            print("  ! 无法计算 IC，数据不足")
            return pd.DataFrame()
        
        mean_ic = ic_df['ic'].mean()
        std_ic = ic_df['ic'].std()
        icir = mean_ic / std_ic if std_ic > 0 else 0
        positive_ratio = (ic_df['ic'] > 0).mean()
        
        print(f"\n{'='*60}")
        print("RSI(6) Rank IC 统计（去极值后）")
        print(f"{'='*60}")
        print(f"  样本日期数: {len(ic_df)}")
        print(f"  平均 IC: {mean_ic:.4f}")
        print(f"  IC 标准差: {std_ic:.4f}")
        print(f"  ICIR: {icir:.4f}")
        print(f"  IC > 0 比例: {positive_ratio:.2%}")
        print(f"  IC 最大值: {ic_df['ic'].max():.4f}")
        print(f"  IC 最小值: {ic_df['ic'].min():.4f}")
        print(f"{'='*60}")
        
        return ic_df
    
    def load_data(
        self,
        n_days: int = 250,
        max_stocks: int = 0,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        enable_complement: bool = True
    ) -> Tuple[pd.DataFrame, pd.DataFrame]:
        """加载真实数据"""
        return self.load_data_multithreaded(
            n_days=n_days,
            max_stocks=max_stocks,
            start_date=start_date,
            end_date=end_date,
            enable_complement=enable_complement
        )
    
    def load_data_with_progress(
        self,
        n_days: int = 250,
        max_stocks: int = 100,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        progress_callback: Optional[callable] = None
    ) -> Tuple[pd.DataFrame, pd.DataFrame, dict]:
        """
        加载真实数据并实时更新进度
        
        Args:
            n_days: 交易日数量
            max_stocks: 最大股票数量
            start_date: 开始日期
            end_date: 结束日期
            progress_callback: 进度回调函数
                参数: (current_batch, total_batches, stocks_fetched, success_count, fail_count, message)
        
        Returns:
            (factor_df, return_df, stats_dict)
        """
        if end_date is None:
            end_date = datetime.now().strftime('%Y-%m-%d')
        if start_date is None:
            start_date = (datetime.now() - timedelta(days=int(n_days * 1.5) + 30)).strftime('%Y-%m-%d')
        
        # 获取股票列表
        if progress_callback:
            progress_callback(0, 1, 0, 0, 0, '获取股票列表...')
        
        stock_list = self.get_main_board_stocks(max_stocks=max_stocks)
        total_stocks = len(stock_list)
        
        if total_stocks == 0:
            raise RuntimeError("未获取到任何股票")
        
        # 计算批次（每批20只股票）
        batch_size = 20
        num_batches = (total_stocks + batch_size - 1) // batch_size
        
        fetch_days = int(n_days * 1.5) + 30
        
        success_count = 0
        fail_count = 0
        all_data_dict = {}
        
        start_time = time.time()
        
        # 分批获取数据（批次编号 1 到 num_batches）
        for batch_idx in range(num_batches):
            batch_start_idx = batch_idx * batch_size
            batch_end_idx = min(batch_start_idx + batch_size, total_stocks)
            batch_stocks = stock_list[batch_start_idx:batch_end_idx]
            
            if progress_callback:
                # 批次编号从1开始，total_batches 就是实际批次数量
                progress_callback(
                    batch_idx + 1, 
                    num_batches,
                    batch_start_idx,
                    success_count,
                    fail_count,
                    f'获取第 {batch_idx + 1}/{num_batches} 批数据...'
                )
            
            # 获取本批次数据
            batch_results = self._fetch_stock_batch(batch_stocks, fetch_days)
            
            for code, df in batch_results:
                if df is not None:
                    all_data_dict[code] = df
                    success_count += 1
                else:
                    fail_count += 1
            
            # 批次间延迟
            if batch_idx < num_batches - 1:
                time.sleep(0.5)
        
        # 数据获取完成，更新进度
        if progress_callback:
            progress_callback(
                num_batches, 
                num_batches,
                total_stocks,
                success_count,
                fail_count,
                '数据获取完成，正在处理...'
            )
        
        if not all_data_dict:
            raise RuntimeError("无法获取任何股票数据")
        
        # 合并数据
        all_data = list(all_data_dict.values())
        combined = pd.concat(all_data, ignore_index=True)
        
        # 日期筛选
        start_dt = pd.to_datetime(start_date)
        end_dt = pd.to_datetime(end_date)
        combined = combined[(combined['date'] >= start_dt) & (combined['date'] <= end_dt)]
        
        # 计算因子 - 使用 DataFrame 列表（替代逐行 append）
        factor_df_list = []
        return_df_list = []
        
        assets = combined['asset'].unique()
        
        for asset in assets:
            stock_df = combined[combined['asset'] == asset].copy()
            stock_df = stock_df.sort_values('date')
            
            stock_df['rsi_6'] = self.calculate_rsi(stock_df['close'], period=6)
            # 计算量比(5)
            stock_df['volume_ratio_5'] = stock_df['volume'] / stock_df['volume'].rolling(window=5).mean()
            stock_df['volume_ratio_5'] = stock_df['volume_ratio_5'].fillna(1.0)
            stock_df['volume_ratio_5'] = stock_df['volume_ratio_5'].clip(0.1, 10)
            stock_df['forward_return'] = stock_df['close'].pct_change().shift(-1)
            
            valid_df = stock_df.dropna(subset=['rsi_6', 'volume_ratio_5', 'forward_return'])
            
            if len(valid_df) > n_days:
                valid_df = valid_df.tail(n_days)
            
            # 向量化构建结果（替代 iterrows + append）
            valid_df['date_str'] = valid_df['date'].dt.strftime('%Y-%m-%d')
            valid_df['rsi_6_rounded'] = valid_df['rsi_6'].round(2)
            valid_df['volume_ratio_5_rounded'] = valid_df['volume_ratio_5'].round(2)
            valid_df['forward_return_rounded'] = valid_df['forward_return'].round(6)
            
            # 直接切片构建 DataFrame
            factor_chunk = valid_df[['date_str', 'asset', 'rsi_6_rounded', 'volume_ratio_5_rounded']].copy()
            factor_chunk.columns = ['date', 'asset', 'rsi_6', 'volume_ratio_5']
            
            return_chunk = valid_df[['date_str', 'asset', 'forward_return_rounded']].copy()
            return_chunk.columns = ['date', 'asset', 'forward_return']
            
            factor_df_list.append(factor_chunk)
            return_df_list.append(return_chunk)
        
        # 合并所有 DataFrame（替代逐行构建）
        factor_df = pd.concat(factor_df_list, ignore_index=True) if factor_df_list else pd.DataFrame()
        return_df = pd.concat(return_df_list, ignore_index=True) if return_df_list else pd.DataFrame()
        
        # 返回统计数据
        stats = {
            'success': success_count,
            'fail': fail_count,
            'total': total_stocks,
            'elapsed_time': time.time() - start_time,
            'num_batches': num_batches  # 添加实际批次数量
        }
        
        return factor_df, return_df, stats


def load_real_data(
    n_days: int = 250,
    max_stocks: int = 0,
    max_workers: int = 2,
    calculate_ic: bool = True,
    use_mock: bool = False,
    use_local: bool = False,
    enable_complement: bool = True
) -> Tuple[pd.DataFrame, pd.DataFrame, Optional[pd.DataFrame]]:
    """
    分批并发加载真实数据（避免API限流 + 数据完整性保障）
    
    并发策略：
    - 每批次2个线程并行
    - 每线程处理50只股票（默认）
    - 批次间串行执行，间隔2秒
    
    完整性保障：
    - 每日缓存股票清单
    - 获取完成后完整性校验
    - 自动补全缺失股票
    - 最终验证输出统计
    
    股票范围：
    - 沪市主板：60开头
    - 深市主板：00开头
    - 剔除：创业板(30)、科创板(688)、北交所、ST股票
    - 总数：约3000+只
    
    Args:
        n_days: 交易日数量
        max_stocks: 最大股票数量（0表示获取全部主板股票，约3000+只）
        max_workers: 已废弃，现使用固定分批策略
        calculate_ic: 是否计算 Rank IC
        use_mock: 使用模拟数据
        use_local: 使用本地数据
        enable_complement: 是否启用补全机制（默认True）
        
    Returns:
        (factor_df, return_df, ic_df)
    """
    loader = RealDataLoader(
        max_workers=max_workers,
        use_mock=use_mock,
        use_local=use_local
    )
    factor_df, return_df = loader.load_data(
        n_days=n_days, 
        max_stocks=max_stocks,
        enable_complement=enable_complement
    )
    
    ic_df = None
    if calculate_ic:
        ic_df = loader.calculate_rank_ic(factor_df, return_df)
    
    return factor_df, return_df, ic_df


def load_factor_light(
    factor_col: str = 'rsi_6',
    max_days: int = 500,
    use_category: bool = True
) -> Optional[pd.DataFrame]:
    """
    轻量级因子数据加载（只加载特定因子）
    
    内存优化策略：
    1. 只加载必要列（date, asset, factor_col）
    2. 使用 category 类型优化内存
    3. 支持限制天数
    
    Args:
        factor_col: 因子列名（如 'rsi_6', 'volume_ratio_5', 'return_3d'）
        max_days: 最大加载天数（默认 500）
        use_category: 是否使用 category 类型（默认 True）
        
    Returns:
        只包含指定因子的 DataFrame，或 None（缓存不存在）
    """
    import gc
    
    cache_dir = Path('/home/admin/projects/factor_ic_analyzer/cache/factor_data')
    factor_path = cache_dir / 'factor_data.json.gz'
    
    if not factor_path.exists():
        print(f"[轻量加载] 缓存文件不存在: {factor_path}")
        return None
    
    try:
        print(f"[轻量加载] 加载因子 {factor_col}（最近 {max_days} 天）...")
        
        with gzip.open(factor_path, 'rt', encoding='utf-8') as f:
            factor_data = json.load(f)
        
        # 提取所有日期
        all_dates = sorted(set(r.get('date') for r in factor_data.get('data', [])))
        
        # 只保留最近 max_days 天
        if len(all_dates) > max_days:
            recent_dates = set(all_dates[-max_days:])
            # 只提取必要列
            factor_records = [
                {'date': r['date'], 'asset': r['asset'], factor_col: r.get(factor_col)}
                for r in factor_data.get('data', []) if r.get('date') in recent_dates
            ]
        else:
            factor_records = [
                {'date': r['date'], 'asset': r['asset'], factor_col: r.get(factor_col)}
                for r in factor_data.get('data', [])
            ]
        
        # 释放中间变量
        del factor_data, all_dates
        if 'recent_dates' in dir():
            del recent_dates
        gc.collect()
        
        # 构建 DataFrame
        factor_df = pd.DataFrame(factor_records)
        del factor_records
        gc.collect()
        
        # 过滤无效数据
        factor_df = factor_df.dropna(subset=[factor_col])
        
        # 使用 category 类型优化内存
        if use_category:
            factor_df['date'] = factor_df['date'].astype('category')
            factor_df['asset'] = factor_df['asset'].astype('category')
        
        # 输出内存占用
        mem_mb = factor_df.memory_usage(deep=True).sum() / 1024 / 1024
        print(f"[轻量加载] factor_df: {len(factor_df)} 行, {mem_mb:.2f} MB")
        
        return factor_df
        
    except Exception as e:
        print(f"[轻量加载] 加载失败: {e}")
        return None


def load_return_light(
    max_days: int = 500,
    use_category: bool = True,
    return_col: str = 'forward_return_1d'
) -> Optional[pd.DataFrame]:
    """
    轻量级收益数据加载（只加载必要列）
    
    内存优化策略：
    1. 只加载必要列（date, asset, return_col）
    2. 使用 category 类型优化内存
    3. 支持限制天数
    
    Args:
        max_days: 最大加载天数（默认 500）
        use_category: 是否使用 category 类型（默认 True）
        return_col: 收益列名（默认 'forward_return_1d'）
        
    Returns:
        只包含必要列的 DataFrame，或 None（缓存不存在）
    """
    import gc
    
    cache_dir = Path('/home/admin/projects/factor_ic_analyzer/cache/factor_data')
    return_path = cache_dir / 'return_data.json.gz'
    
    if not return_path.exists():
        print(f"[轻量加载] 缓存文件不存在: {return_path}")
        return None
    
    try:
        print(f"[轻量加载] 加载收益数据（最近 {max_days} 天）...")
        
        with gzip.open(return_path, 'rt', encoding='utf-8') as f:
            return_data = json.load(f)
        
        # 提取所有日期（从因子数据缓存获取）
        factor_path = cache_dir / 'factor_data.json.gz'
        all_dates = []
        if factor_path.exists():
            with gzip.open(factor_path, 'rt', encoding='utf-8') as f:
                factor_data = json.load(f)
            all_dates = sorted(set(r.get('date') for r in factor_data.get('data', [])))
            del factor_data
        
        # 只保留最近 max_days 天
        if len(all_dates) > max_days:
            recent_dates = set(all_dates[-max_days:])
            return_records = [
                {'date': r['date'], 'asset': r['asset'], return_col: r.get(return_col)}
                for r in return_data.get('data', []) if r.get('date') in recent_dates
            ]
        else:
            return_records = [
                {'date': r['date'], 'asset': r['asset'], return_col: r.get(return_col)}
                for r in return_data.get('data', [])
            ]
        
        # 释放中间变量
        del return_data, all_dates
        if 'recent_dates' in dir():
            del recent_dates
        gc.collect()
        
        # 构建 DataFrame
        return_df = pd.DataFrame(return_records)
        del return_records
        gc.collect()
        
        # 过滤无效数据
        return_df = return_df.dropna(subset=[return_col])
        
        # 使用 category 类型优化内存
        if use_category:
            return_df['date'] = return_df['date'].astype('category')
            return_df['asset'] = return_df['asset'].astype('category')
        
        # 列名兼容性映射
        if return_col == 'forward_return_1d' and 'forward_return' not in return_df.columns:
            return_df['forward_return'] = return_df['forward_return_1d']
        
        # 输出内存占用
        mem_mb = return_df.memory_usage(deep=True).sum() / 1024 / 1024
        print(f"[轻量加载] return_df: {len(return_df)} 行, {mem_mb:.2f} MB")
        
        return return_df
        
    except Exception as e:
        print(f"[轻量加载] 加载失败: {e}")
        return None


def load_cached_data_combined_light(
    factor_col: str = 'rsi_6',
    max_days: int = 500,
    use_category: bool = True
) -> Tuple[Optional[pd.DataFrame], Optional[pd.DataFrame]]:
    """
    轻量级组合加载（因子 + 收益）
    
    内存优化策略：
    1. 分别轻量加载因子和收益
    2. 只加载必要列
    3. 使用 category 类型
    
    Args:
        factor_col: 因子列名（默认 'rsi_6'）
        max_days: 最大加载天数（默认 500）
        use_category: 是否使用 category 类型（默认 True）
        
    Returns:
        (factor_df, return_df) 或 (None, None)
    """
    import gc
    
    # 轻量加载因子
    factor_df = load_factor_light(factor_col, max_days, use_category)
    
    # 轻量加载收益
    return_df = load_return_light(max_days, use_category)
    
    if factor_df is None or return_df is None:
        return None, None
    
    # 输出总内存
    factor_mem = factor_df.memory_usage(deep=True).sum() / 1024 / 1024
    return_mem = return_df.memory_usage(deep=True).sum() / 1024 / 1024
    print(f"[轻量加载] 总内存: {factor_mem + return_mem:.2f} MB")
    
    return factor_df, return_df


if __name__ == '__main__':
    print("测试多线程真实数据加载器...")
    print("=" * 60)
    
    # 全量数据加载（保存缓存）
    factor_df, return_df, ic_df = load_real_data(
        n_days=250,
        max_stocks=0,  # 0表示全量获取
        max_workers=8,
        calculate_ic=True,
        use_mock=True
    )
    
    print("\n因子数据预览:")
    print(factor_df.head(10))
    
    print("\n收益数据预览:")
    print(return_df.head(10))
    
    if ic_df is not None:
        print("\nIC 数据预览:")
        print(ic_df.head(10))