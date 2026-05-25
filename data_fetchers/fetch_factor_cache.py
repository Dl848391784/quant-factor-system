#!/usr/bin/env python3
"""
分批拉取500天因子数据 - 外部排序流式合并（极致内存优化）

策略：
1. 将股票分成多批（每批250只）
2. 每批拉取后立即保存到独立的 gzip 文件
3. 外部排序合并：
   - 每批次数据已按 (date, asset) 排序
   - 使用 N-way merge 合并已排序的批次
   - 去重时只保留最新值（同key后写入覆盖前写入）
4. 内存峰值：仅一个批次数据 + N个最小记录（N=批次数）

版本历史：
- v3.4_with_ohlc (2026-04-09): 新增 open/high/low 字段，支持选股回测计算一字涨停、封死涨停等指标
- v3.5 (2026-05-26): 版本历史格式规范化、sys.path移除、公共模块导入、docstring补充、流程文档+测试用例创建
- v3.6 (2026-05-26): print → logger 迁移完成（74处全量替换）、logger参数化（6个核心函数）、main函数日志初始化
- v3.7 (2026-05-26): 导入顺序PEP8规范化、BatchStream类docstring补充、类型注解完善、路径配置使用公共模块

作者: 云舟
日期: 2026-04-04
"""

# 标准库导入（PEP 8 规范：按字母顺序分组）
import gc
import gzip
import heapq
import json
import logging
import os
import sys
import time
from datetime import datetime
from pathlib import Path

# 第三方库导入
import pandas as pd

# 本地模块导入
from real_data_loader import RealDataLoader

# 公共模块导入（条件导入：脚本直接运行时可能路径未配置）
try:
    from data_fetchers.common import setup_logger, get_logs_dir, get_cache_dir
except ImportError:
    from common import setup_logger, get_logs_dir, get_cache_dir

# ============================================================================
# 模块级 fallback logger（遵循 PROJECT.md 公共模块日志规范）
# ============================================================================
_MODULE_LOGGER = logging.getLogger('data_fetchers.fetch_factor_cache')

# ============================================================================
# 配置常量（遵循 MODULE.md 约束 #2：cache 为数据源原始缓存）
# ============================================================================
N_DAYS = 500  # 目标交易日数
BATCH_SIZE = 250  # 每批股票数量（从400降低到250，减少单批峰值）
FETCH_DAYS = int(N_DAYS * 1.5) + 30  # 实际拉取天数
MEMORY_THRESHOLD_MB = 900  # 内存警告阈值（MB）- 缓存加载后约700MB
MEMORY_PAUSE_SECONDS = 15  # 内存超阈值时的暂停时间

# 路径配置（使用公共模块路径函数）
CACHE_DIR = get_cache_dir() / 'factor_data'
CACHE_DIR.mkdir(parents=True, exist_ok=True)


def get_memory_usage_mb() -> float:
    """
    获取当前进程真实RSS内存（MB）- 从 /proc/self/status
    
    Returns:
        float: RSS内存大小（MB），Linux下从/proc/self/status读取，
               其他系统使用resource.getrusage()
    
    Note:
        - Linux: 读取VmRSS字段（实际物理内存使用）
        - 其他系统: 使用ru_maxrss（最大RSS值，可能不准确）
    """
    try:
        with open('/proc/self/status', 'r') as f:
            for line in f:
                if line.startswith('VmRSS:'):
                    return int(line.split()[1]) / 1024  # kB -> MB
    except Exception:
        pass
    import resource
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024


def get_memory_info_str() -> str:
    """
    获取详细内存信息字符串
    
    Returns:
        str: 格式化的内存信息，如 "RSS=700.5MB, VM=900.0MB"
    
    Note:
        - Linux: 同时读取VmRSS和VmSize
        - 其他系统: 仅返回RSS信息
    """
    try:
        with open('/proc/self/status', 'r') as f:
            vmrss = vmsize = None
            for line in f:
                if line.startswith('VmRSS:'):
                    vmrss = int(line.split()[1]) / 1024
                elif line.startswith('VmSize:'):
                    vmsize = int(line.split()[1]) / 1024
            if vmrss:
                return f"RSS={vmrss:.1f}MB" + (f", VM={vmsize:.1f}MB" if vmsize else "")
    except Exception:
        pass
    return f"RSS={get_memory_usage_mb():.1f}MB"


def save_batch_cache_sorted(batch_idx: int, factor_df, return_df, logger: logging.Logger = None) -> None:
    """
    保存单批次数据到临时文件（预先排序，流式写入）
    
    Args:
        batch_idx: 批次索引（从0开始）
        factor_df: 因子数据DataFrame，包含 date/asset/open/close/high/low/rsi_6/volume_ratio_5
        return_df: 收益数据DataFrame，包含 date/asset/forward_return_1d/3d/5d
        logger: 日志记录器（可选，默认使用模块级 logger）
    
    Side Effects:
        - 创建 batch_{batch_idx}_factor.json.gz 和 batch_{batch_idx}_return.json.gz
        - 释放 factor_df 和 return_df 内存
    
    Note:
        - 数据按 (date, asset) 排序，便于后续 N-way merge
        - 使用流式写入避免 to_dict('records') 内存峰值
    """
    logger = logger or _MODULE_LOGGER
    factor_path = os.path.join(CACHE_DIR, f'batch_{batch_idx}_factor.json.gz')
    return_path = os.path.join(CACHE_DIR, f'batch_{batch_idx}_return.json.gz')
    
    # 格式化并排序（按 date, asset）
    factor_df['date'] = factor_df['date'].astype(str)
    return_df['date'] = return_df['date'].astype(str)
    
    factor_df = factor_df.sort_values(['date', 'asset']).reset_index(drop=True)
    return_df = return_df.sort_values(['date', 'asset']).reset_index(drop=True)
    
    # 流式写入因子数据（避免 to_dict('records') 内存峰值）
    logger.info("  保存因子数据...")
    with gzip.open(factor_path, 'wt', encoding='utf-8') as f:
        f.write('[\n')
        for i, row in enumerate(factor_df.itertuples(index=False)):
            if i > 0:
                f.write(',\n')
            record = {
                'date': row.date,
                'asset': row.asset,
                'open': round(row.open, 2) if hasattr(row, 'open') else None,
                'close': round(row.close, 2) if hasattr(row, 'close') else None,
                'high': round(row.high, 2) if hasattr(row, 'high') else None,
                'low': round(row.low, 2) if hasattr(row, 'low') else None,
                'rsi_6': round(row.rsi_6, 2) if hasattr(row, 'rsi_6') else None,
                'volume_ratio_5': round(row.volume_ratio_5, 2) if hasattr(row, 'volume_ratio_5') else None
            }
            f.write('  ' + json.dumps(record, ensure_ascii=False))
        f.write('\n]')
    
    # 流式写入收益数据
    logger.info("  保存收益数据...")
    with gzip.open(return_path, 'wt', encoding='utf-8') as f:
        f.write('[\n')
        for i, row in enumerate(return_df.itertuples(index=False)):
            if i > 0:
                f.write(',\n')
            record = {
                'date': row.date,
                'asset': row.asset,
                'forward_return_1d': round(row.forward_return_1d, 6) if hasattr(row, 'forward_return_1d') else None,
                'forward_return_3d': round(row.forward_return_3d, 6) if hasattr(row, 'forward_return_3d') else None,
                'forward_return_5d': round(row.forward_return_5d, 6) if hasattr(row, 'forward_return_5d') else None
            }
            f.write('  ' + json.dumps(record, ensure_ascii=False))
        f.write('\n]')
    
    factor_size_mb = os.path.getsize(factor_path) / (1024 * 1024)
    return_size_mb = os.path.getsize(return_path) / (1024 * 1024)
    
    logger.info(f"  ✓ 保存批次 {batch_idx}: 因子 {factor_size_mb:.2f}MB, 收益 {return_size_mb:.2f}MB")
    logger.info(f"  当前内存: {get_memory_info_str()}")
    
    # 立即释放 DataFrame 内存
    del factor_df, return_df
    gc.collect()


class BatchStream:
    """
    批次数据流式读取器
    
    用于 N-way merge 时逐条读取批次数据，避免一次性加载所有批次
    
    Attributes:
        path: 批次文件路径（Path 对象）
        records: 当前加载的记录列表
        idx: 当前记录索引
        exhausted: 是否已耗尽
    
    Note:
        - 批次文件已按 (date, asset) 排序
        - 每次加载全部记录（批次文件不大，约几MB）
    """
    
    def __init__(self, batch_idx: int, data_type: str = 'factor'):
        """
        初始化批次数据流
        
        Args:
            batch_idx: 批次索引（从0开始）
            data_type: 数据类型（'factor' 或 'return'）
        """
        self.path = CACHE_DIR / f'batch_{batch_idx}_{data_type}.json.gz'
        self.records: list = []
        self.idx: int = 0
        self.exhausted: bool = False
        self._load_next_chunk()
    
    def _load_next_chunk(self) -> None:
        """
        加载下一个数据块
        
        Note:
            - 批次文件不大（约几MB），直接加载全部记录
            - 加载后标记 exhausted 状态
        """
        if self.exhausted:
            return
        
        if not self.path.exists():
            self.exhausted = True
            return
        
        # 加载全部记录（批次文件不大）
        with gzip.open(self.path, 'rt', encoding='utf-8') as f:
            self.records = json.load(f)
        
        self.idx = 0
        self.exhausted = len(self.records) == 0
    
    def peek_key(self) -> tuple[str, str] | None:
        """
        获取当前记录的 key (date, asset)
        
        Returns:
            tuple[str, str] | None: (date, asset) 或 None（已耗尽）
        """
        if self.idx >= len(self.records):
            return None
        rec = self.records[self.idx]
        return (rec['date'], rec['asset'])
    
    def pop_record(self) -> dict | None:
        """
        弹出当前记录
        
        Returns:
            dict | None: 当前记录字典或 None（已耗尽）
        """
        if self.idx >= len(self.records):
            return None
        rec = self.records[self.idx]
        self.idx += 1
        return rec
    
    def is_exhausted(self) -> bool:
        """
        是否已耗尽
        
        Returns:
            bool: True 表示已耗尽所有记录
        """
        return self.exhausted and self.idx >= len(self.records)
    
    def cleanup(self) -> None:
        """
        清理资源
        
        Note:
            - 释放 records 内存
            - 标记 exhausted 状态
        """
        self.records = []
        self.exhausted = True
        gc.collect()


def n_way_merge_deduplicate(total_batches: int, data_type: str = 'factor', logger: logging.Logger = None) -> tuple:
    """
    N-way merge 合并已排序的批次数据，去重
    
    Args:
        total_batches: 总批次数
        data_type: 数据类型（'factor' 或 'return'）
        logger: 日志记录器（可选，默认使用模块级 logger）
    
    Returns:
        tuple: (output_path, count) 输出文件路径和记录数
    
    Note:
        - 使用 heap 进行N-way merge，每个批次只保持当前记录在内存中
        - 去重策略：相同的 (date, asset) 只保留最后一次出现的值
    """
    logger = logger or _MODULE_LOGGER
    logger.info(f"[{data_type}] 开始 N-way merge...")
    logger.info(f"  当前内存: {get_memory_info_str()}")
    
    # 创建所有批次的流
    streams = []
    valid_batch_indices = []
    
    for batch_idx in range(total_batches):
        path = os.path.join(CACHE_DIR, f'batch_{batch_idx}_{data_type}.json.gz')
        if os.path.exists(path):
            stream = BatchStream(batch_idx, data_type)
            if not stream.is_exhausted():
                streams.append(stream)
                valid_batch_indices.append(batch_idx)
    
    if not streams:
        logger.info("  无有效批次")
        return ('', 0)
    
    logger.info(f"  有效批次数: {len(streams)}")
    
    # N-way merge 使用 heap
    # heap元素: (key, batch_idx, stream)
    heap = []
    for i, stream in enumerate(streams):
        key = stream.peek_key()
        if key:
            heapq.heappush(heap, (key, i, stream))
    
    # 合并结果（暂时存内存，流式写入文件）
    output_path = os.path.join(CACHE_DIR, f'merged_{data_type}.json.gz')
    merged_records = []
    last_key = None
    last_record = None
    count = 0
    
    logger.info("  开始合并...")
    
    with gzip.open(output_path, 'wt', encoding='utf-8') as f:
        f.write('[\n')  # JSON数组开始
        
        while heap:
            key, stream_idx, stream = heapq.heappop(heap)
            record = stream.pop_record()
            
            # 去重：相同key时，后写入覆盖前写入
            # 由于批次已排序，我们用"相同key替换"策略
            if last_key == key:
                # 相同key，替换为新值（批次顺序即为优先级）
                last_record = record
            else:
                # 不同key，写入上一个记录
                if last_record is not None:
                    if count > 0:
                        f.write(',\n')
                    f.write('  ' + json.dumps(last_record, ensure_ascii=False))
                    count += 1
                    
                    if count % 50000 == 0:
                        gc.collect()
                        logger.info(f"    已写入 {count} 条，内存: {get_memory_info_str()}")
                
                last_key = key
                last_record = record
            
            # 从该stream取下一个记录
            next_key = stream.peek_key()
            if next_key:
                heapq.heappush(heap, (next_key, stream_idx, stream))
        
        # 写入最后一条记录
        if last_record is not None:
            if count > 0:
                f.write(',\n')
            f.write('  ' + json.dumps(last_record, ensure_ascii=False))
            count += 1
        
        f.write('\n]')  # JSON数组结束
    
    logger.info(f"  合并完成: {count} 条记录")
    logger.info(f"  输出文件: {output_path}")
    logger.info(f"  当前内存: {get_memory_info_str()}")
    
    # 清理streams
    for stream in streams:
        stream.cleanup()
    streams = []
    gc.collect()
    
    return output_path, count


def fetch_batch_stocks(loader, stock_batch: list, batch_idx: int, total_batches: int, logger: logging.Logger = None) -> tuple:
    """
    拉取一批股票的数据
    
    Args:
        loader: RealDataLoader 实例
        stock_batch: 股票代码列表
        batch_idx: 当前批次索引（从0开始）
        total_batches: 总批次数
        logger: 日志记录器（可选，默认使用模块级 logger）
    
    Returns:
        tuple: (factor_df, return_df) 因子数据和收益数据 DataFrame
    """
    logger = logger or _MODULE_LOGGER
    logger.info("=" * 60)
    logger.info(f"[批次 {batch_idx + 1}/{total_batches}] 开始拉取...")
    logger.info(f"  股票数量: {len(stock_batch)}")
    logger.info(f"  当前内存: {get_memory_info_str()}")
    logger.info("=" * 60)
    
    batch_start_time = time.time()
    
    all_data_dict = {}
    success_count = 0
    fail_count = 0
    
    sub_batch_size = 35  # 子批次大小（从50降低到35）
    num_sub_batches = (len(stock_batch) + sub_batch_size - 1) // sub_batch_size
    
    for sub_idx in range(num_sub_batches):
        sub_start = sub_idx * sub_batch_size
        sub_end = min(sub_start + sub_batch_size, len(stock_batch))
        sub_stocks = stock_batch[sub_start:sub_end]
        
        thread_a_stocks = sub_stocks[:len(sub_stocks) // 2]
        thread_b_stocks = sub_stocks[len(sub_stocks) // 2:]
        
        logger.info(f"  [子批次 {sub_idx + 1}/{num_sub_batches}] 拉取 {sub_start + 1}-{sub_end}...")
        logger.info(f"    当前内存: {get_memory_info_str()}")
        
        sub_results = loader._fetch_stock_batch_parallel(
            thread_a_stocks,
            thread_b_stocks,
            FETCH_DAYS,
            None
        )
        
        for code, df in sub_results:
            if df is not None and len(df) >= 15:
                all_data_dict[code] = df
                success_count += 1
            else:
                fail_count += 1
        
        # 每个子批次后强制垃圾回收
        gc.collect()
        
        # 内存监控：超过阈值时暂停
        mem_mb = get_memory_usage_mb()
        if mem_mb > MEMORY_THRESHOLD_MB:
            logger.warning(f"  ⚠ 内存超阈值 ({mem_mb:.1f}MB > {MEMORY_THRESHOLD_MB}MB)，暂停 {MEMORY_PAUSE_SECONDS}s...")
            gc.collect()
            time.sleep(MEMORY_PAUSE_SECONDS)
        
        if sub_idx < num_sub_batches - 1:
            time.sleep(2)
    
    batch_elapsed = time.time() - batch_start_time
    logger.info(f"  ✓ 批次 {batch_idx + 1} 拉取完成: 成功 {success_count}, 失败 {fail_count}, 耗时 {batch_elapsed:.1f}s")
    
    if not all_data_dict:
        logger.warning("  ! 无有效数据")
        return None, None
    
    logger.info("  正在计算因子...")
    
    import pandas as pd
    
    all_data = list(all_data_dict.values())
    combined = pd.concat(all_data, ignore_index=True)
    
    del all_data, all_data_dict
    gc.collect()
    
    combined['date'] = pd.to_datetime(combined['date'])
    combined = combined.sort_values(['asset', 'date'])
    
    combined['rsi_6'] = combined.groupby('asset')['close'].transform(
        lambda x: loader._calculate_rsi_vectorized(x, period=6)
    )
    
    combined['volume_ratio_5'] = combined.groupby('asset')['volume'].transform(
        lambda x: x / x.rolling(window=5).mean()
    )
    combined['volume_ratio_5'] = combined['volume_ratio_5'].fillna(1.0).clip(0.1, 10)
    
    combined['forward_return_1d'] = combined.groupby('asset')['close'].transform(
        lambda x: x.pct_change().shift(-1)
    )
    combined['forward_return_3d'] = combined.groupby('asset')['close'].transform(
        lambda x: x.shift(-3) / x - 1
    )
    combined['forward_return_5d'] = combined.groupby('asset')['close'].transform(
        lambda x: x.shift(-5) / x - 1
    )

    valid_df = combined.dropna(subset=['rsi_6', 'volume_ratio_5'])
    
    del combined
    gc.collect()
    
    # pandas 3.0 兼容性修复：使用 cumcount 替代 groupby().apply(tail)
    # 避免 group_keys=False 导致分组列被移除
    valid_df['row_num'] = valid_df.groupby('asset').cumcount(ascending=False)
    valid_df = valid_df[valid_df['row_num'] < N_DAYS].drop('row_num', axis=1)
    
    valid_df['date'] = valid_df['date'].dt.strftime('%Y-%m-%d')
    valid_df['open'] = valid_df['open'].round(2)
    valid_df['close'] = valid_df['close'].round(2)
    valid_df['high'] = valid_df['high'].round(2)
    valid_df['low'] = valid_df['low'].round(2)
    valid_df['rsi_6'] = valid_df['rsi_6'].round(2)
    valid_df['volume_ratio_5'] = valid_df['volume_ratio_5'].round(2)
    valid_df['forward_return_1d'] = valid_df['forward_return_1d'].round(6)
    valid_df['forward_return_3d'] = valid_df['forward_return_3d'].round(6)
    valid_df['forward_return_5d'] = valid_df['forward_return_5d'].round(6)

    # 包含 open/high/low 用于选股回测计算一字涨停、封死涨停等
    factor_df = valid_df[['date', 'asset', 'open', 'close', 'high', 'low', 'rsi_6', 'volume_ratio_5']].copy()
    return_df = valid_df[['date', 'asset', 'forward_return_1d', 'forward_return_3d', 'forward_return_5d']].copy()
    
    del valid_df
    gc.collect()
    
    logger.info(f"  因子记录: {len(factor_df)}, 收益记录: {len(return_df)}")
    
    return factor_df, return_df


def format_final_output(factor_merged_path, return_merged_path, logger: logging.Logger = None):
    """
    将合并后的JSON数组格式化为完整JSON文件
    
    Args:
        factor_merged_path: 合并后的因子数据路径
        return_merged_path: 合并后的收益数据路径
        logger: 日志记录器（可选，默认使用模块级 logger）
    
    Returns:
        tuple: (factor_final_path, return_final_path, dates_list, assets_list)
    """
    logger = logger or _MODULE_LOGGER
    logger.info("格式化最终输出文件...")
    
    # 读取合并后的数据获取元信息
    with gzip.open(factor_merged_path, 'rt', encoding='utf-8') as f:
        factor_records = json.load(f)
    
    with gzip.open(return_merged_path, 'rt', encoding='utf-8') as f:
        return_records = json.load(f)
    
    # 提取日期和资产
    dates_list = sorted(set(r['date'] for r in factor_records))
    assets_list = sorted(set(r['asset'] for r in factor_records))
    
    logger.info(f"  交易日数: {len(dates_list)}")
    logger.info(f"  股票数量: {len(assets_list)}")
    logger.info(f"  因子记录: {len(factor_records)}")
    logger.info(f"  收益记录: {len(return_records)}")
    
    # 写入最终格式化的文件
    factor_final_path = os.path.join(CACHE_DIR, 'factor_data.json.gz')
    return_final_path = os.path.join(CACHE_DIR, 'return_data.json.gz')
    
    # 因子数据
    with gzip.open(factor_final_path, 'wt', encoding='utf-8') as f:
        f.write('{\n')
        f.write('  "meta": {\n')
        f.write(f'    "generated_at": "{datetime.now().isoformat()}",\n')
        f.write('    "source": "sina_api_batch_external_merge",\n')
        f.write(f'    "n_days": {len(dates_list)},\n')
        f.write(f'    "n_assets": {len(assets_list)},\n')
        f.write('    "date_range": {\n')
        f.write(f'      "start": "{dates_list[0]}",\n')
        f.write(f'      "end": "{dates_list[-1]}"\n')
        f.write('    },\n')
        f.write(f'    "last_updated": "{datetime.now().strftime("%Y-%m-%d %H:%M:%S")}",\n')
        f.write('    "version": "3.4_with_ohlc",\n')
        f.write('    "fields": ["date", "asset", "open", "close", "high", "low", "rsi_6", "volume_ratio_5"]\n')
        f.write('  },\n')
        f.write('  "data": [\n')
        
        for i, rec in enumerate(factor_records):
            if i > 0:
                f.write(',\n')
            f.write('    ' + json.dumps(rec, ensure_ascii=False))
        
        f.write('\n  ]\n')
        f.write('}\n')
    
    # 收益数据
    with gzip.open(return_final_path, 'wt', encoding='utf-8') as f:
        f.write('{\n')
        f.write('  "meta": {\n')
        f.write(f'    "generated_at": "{datetime.now().isoformat()}",\n')
        f.write('    "source": "sina_api_batch_external_merge",\n')
        f.write(f'    "n_days": {len(dates_list)},\n')
        f.write(f'    "n_assets": {len(assets_list)},\n')
        f.write('    "date_range": {\n')
        f.write(f'      "start": "{dates_list[0]}",\n')
        f.write(f'      "end": "{dates_list[-1]}"\n')
        f.write('    },\n')
        f.write(f'    "last_updated": "{datetime.now().strftime("%Y-%m-%d %H:%M:%S")}",\n')
        f.write('    "version": "3.4_with_ohlc",\n')
        f.write('    "fields": ["date", "asset", "forward_return_1d", "forward_return_3d", "forward_return_5d"],\n')
        f.write('    "note": "3日和5日收益最后几天会有NaN"\n')
        f.write('  },\n')
        f.write('  "data": [\n')
        
        for i, rec in enumerate(return_records):
            if i > 0:
                f.write(',\n')
            f.write('    ' + json.dumps(rec, ensure_ascii=False))
        
        f.write('\n  ]\n')
        f.write('}\n')
    
    # 清理合并的临时文件和内存
    del factor_records, return_records
    gc.collect()
    
    os.remove(factor_merged_path)
    os.remove(return_merged_path)
    
    factor_size_mb = os.path.getsize(factor_final_path) / (1024 * 1024)
    return_size_mb = os.path.getsize(return_final_path) / (1024 * 1024)
    
    logger.info(f"  ✓ 最终文件已保存:")
    logger.info(f"    因子: {factor_final_path} ({factor_size_mb:.2f} MB)")
    logger.info(f"    收益: {return_final_path} ({return_size_mb:.2f} MB)")
    
    return len(dates_list), len(assets_list), len(factor_records) if 'factor_records' in dir() else 0


def validate_final_data(logger: logging.Logger = None) -> bool:
    """
    验证最终数据完整性
    
    Args:
        logger: 日志记录器（可选，默认使用模块级 logger）
    
    Returns:
        bool: 数据是否有效（交易日数 >= N_DAYS）
    """
    logger = logger or _MODULE_LOGGER
    logger.info("=" * 60)
    logger.info("[验证阶段] 验证数据完整性...")
    logger.info("=" * 60)
    
    factor_path = os.path.join(CACHE_DIR, 'factor_data.json.gz')
    
    with gzip.open(factor_path, 'rt', encoding='utf-8') as f:
        data = json.load(f)
    
    meta = data['meta']
    n_days = meta['n_days']
    n_assets = meta['n_assets']
    n_records = len(data['data'])
    
    logger.info(f"  交易日数: {n_days}")
    logger.info(f"  股票数量: {n_assets}")
    logger.info(f"  总记录数: {n_records}")
    logger.info(f"  日期范围: {meta['date_range']['start']} ~ {meta['date_range']['end']}")
    
    # 抽样检查
    sample = data['data'][:1000]
    rsi_vals = [r['rsi_6'] for r in sample if r.get('rsi_6') is not None]
    if rsi_vals:
        logger.info(f"  RSI(6)样本范围: [{min(rsi_vals):.2f}, {max(rsi_vals):.2f}]")
    
    del data, sample
    gc.collect()
    
    is_valid = n_days >= N_DAYS * 0.9
    logger.info(f"  {'✓ 通过' if is_valid else '⚠ 交易日数不足'}")
    
    return is_valid, n_days, n_assets, n_records


def cleanup_batch_files(total_batches: int, logger: logging.Logger = None) -> int:
    """
    清理临时批次文件
    
    Args:
        total_batches: 总批次数
        logger: 日志记录器（可选，默认使用模块级 logger）
    
    Returns:
        int: 删除的文件数量
    """
    logger = logger or _MODULE_LOGGER
    logger.info("[清理阶段] 删除临时批次文件...")
    
    deleted = 0
    for batch_idx in range(total_batches):
        for t in ['factor', 'return']:
            path = os.path.join(CACHE_DIR, f'batch_{batch_idx}_{t}.json.gz')
            if os.path.exists(path):
                os.remove(path)
                deleted += 1
    
    logger.info(f"  ✓ 已删除 {deleted} 个临时文件")
    return deleted


def main():
    """
    主函数 - 分批拉取N天因子数据
    
    流程：
    1. 初始化 RealDataLoader
    2. 获取主板股票列表
    3. 分批拉取数据（每批BATCH_SIZE只股票）
    4. N-way merge 合并批次数据
    5. 格式化输出最终文件
    6. 验证数据完整性
    7. 清理临时文件
    """
    # 初始化 logger（遵循 PROJECT.md 日志规范：输出到 logs 目录）
    log_dir = get_logs_dir()
    logger = setup_logger('fetch_factor_cache', logs_dir=log_dir)
    
    logger.info("=" * 70)
    logger.info(f"分批拉取 {N_DAYS} 天因子数据 (外部排序版本)")
    logger.info("=" * 70)
    logger.info(f"  版本: 3.6")
    logger.info(f"  目标交易日数: {N_DAYS}")
    logger.info(f"  每批股票数量: {BATCH_SIZE}")
    logger.info(f"  内存阈值: {MEMORY_THRESHOLD_MB} MB")
    logger.info(f"  开始时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info(f"  初始内存: {get_memory_info_str()}")
    
    global_start = time.time()
    
    loader = RealDataLoader(enable_cache=True, use_mock=False, use_local=False, retries=3)
    
    logger.info("[获取股票列表]...")
    stock_list = loader.get_main_board_stocks(max_stocks=0)
    
    if not stock_list:
        logger.warning("  ! 未获取到股票列表")
        return
    
    total_stocks = len(stock_list)
    logger.info(f"  ✓ 获取到 {total_stocks} 只主板股票")
    
    batches = [stock_list[i:i+BATCH_SIZE] for i in range(0, total_stocks, BATCH_SIZE)]
    total_batches = len(batches)
    
    logger.info(f"[分批策略] 总批次: {total_batches}")
    
    successful = 0
    
    for batch_idx, stock_batch in enumerate(batches):
        mem_mb = get_memory_usage_mb()
        logger.info(f"  当前内存: {get_memory_info_str()}")
        
        if mem_mb > MEMORY_THRESHOLD_MB:
            logger.warning(f"  ⚠ 内存超阈值 ({mem_mb:.1f}MB > {MEMORY_THRESHOLD_MB}MB)，暂停 {MEMORY_PAUSE_SECONDS}s...")
            gc.collect()
            time.sleep(MEMORY_PAUSE_SECONDS)
            mem_mb = get_memory_usage_mb()
            logger.info(f"  GC后内存: {get_memory_info_str()}")
        
        factor_df, return_df = fetch_batch_stocks(loader, stock_batch, batch_idx, total_batches, logger)
        
        if factor_df is not None and len(factor_df) > 0:
            save_batch_cache_sorted(batch_idx, factor_df, return_df, logger)
            successful += 1
            # save_batch_cache_sorted 已释放 factor_df, return_df
        else:
            logger.warning(f"  ⚠ 批次 {batch_idx + 1} 失败")
            if factor_df is not None:
                del factor_df
            if return_df is not None:
                del return_df
        
        # 批次间强制垃圾回收
        gc.collect()
        logger.info(f"  批次完成后内存: {get_memory_info_str()}")
        time.sleep(5)  # 批次间休息时间增加
    
    logger.info("=" * 70)
    logger.info(f"拉取完成: 成功 {successful}/{total_batches} 批次")
    logger.info("=" * 70)
    
    # N-way merge 合并
    logger.info("[合并阶段] N-way merge 外部排序...")
    
    factor_merged_path, factor_count = n_way_merge_deduplicate(total_batches, 'factor', logger)
    return_merged_path, return_count = n_way_merge_deduplicate(total_batches, 'return', logger)
    
    if not factor_merged_path:
        logger.warning("  ! 无有效数据")
        return
    
    # 格式化最终输出
    n_days, n_assets, n_records = format_final_output(factor_merged_path, return_merged_path, logger)
    
    # 验证
    is_valid, actual_days, actual_assets, actual_records = validate_final_data(logger)
    
    # 清理
    cleanup_batch_files(total_batches, logger)
    
    elapsed = time.time() - global_start
    
    logger.info("=" * 70)
    logger.info("全部完成!")
    logger.info("=" * 70)
    logger.info(f"  结束时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info(f"  总耗时: {elapsed:.1f}s ({elapsed/60:.1f}min)")
    logger.info(f"  数据验证: {'通过' if is_valid else '警告'}")
    logger.info(f"  最终内存: {get_memory_info_str()}")
    
    # 保存统计
    stats = {
        'version': '3.4_with_ohlc',
        'n_days': actual_days,
        'n_assets': actual_assets,
        'n_records': actual_records,
        'elapsed_seconds': elapsed,
        'is_valid': is_valid,
        'memory_monitor': 'proc_self_status',
        'fields': ['date', 'asset', 'open', 'close', 'high', 'low', 'rsi_6', 'volume_ratio_5']
    }
    
    with open(os.path.join(CACHE_DIR, 'regenerate_stats.json'), 'w') as f:
        json.dump(stats, f, indent=2)


if __name__ == '__main__':
    main()