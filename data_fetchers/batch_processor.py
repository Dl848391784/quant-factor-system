#!/usr/bin/env python3
"""
批次处理模块 - 批次保存、N-way合并、最终格式化

整合批次处理逻辑：
- BatchStream 类：批次数据流式读取
- save_batch_cache_sorted：批次保存
- n_way_merge_deduplicate：N-way合并
- format_final_output：最终格式化
- cleanup_batch_files：清理临时文件

遵循 PROJECT.md 规范：
- 使用 Python 标准库 logging 模块
- 公共模块函数接收 logger 参数

版本历史：
- v1.0 (2026-05-27): 初始版本，创建 BatchStream 类、save_batch_cache_sorted、
    n_way_merge_deduplicate、format_final_output、cleanup_batch_files

作者: 云瑶
创建日期: 2026-05-27
"""

import gc
import gzip
import heapq
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

# 本地模块导入
from data_fetchers.common.paths import get_module_result_dir
from data_fetchers.common.memory_utils import get_memory_info_str
from data_fetchers.common.dataframe_utils import validate_dataframe_columns

# ============================================================================
# 模块级常量
# ============================================================================
RESULT_DIR = get_module_result_dir()
_OUTPUT_VERSION = '2.14'

# ============================================================================
# 辅助函数
# ============================================================================

def _write_json_record(f: Any, record: dict, count: int) -> int:
    """
    流式写入单条 JSON 记录
    
    Args:
        f: gzip 文件对象
        record: 记录字典
        count: 当前计数
    
    Returns:
        int: 更新后的计数
    """
    if count > 0:
        f.write(',\n')
    f.write('  ' + json.dumps(record, ensure_ascii=False))
    return count + 1


# ============================================================================
# BatchStream 类：批次数据流式读取器
# ============================================================================

class BatchStream:
    """
    批次数据流式读取器
    
    用于 N-way merge 时逐条读取批次数据，避免一次性加载所有批次
    
    Attributes:
        batch_idx: 原始批次索引（从0开始）
        data_type: 数据类型（'factor' 或 'return')
        path: 批次文件路径（Path 对象）
        records: 当前加载的记录列表
        idx: 当前记录索引
        exhausted: 是否已耗尽
    """
    
    def __init__(self, batch_idx: int, data_type: str = 'factor', result_dir: Path = None):
        """
        初始化批次数据流
        
        Args:
            batch_idx: 批次索引（从0开始）
            data_type: 数据类型（'factor' 或 'return')
            result_dir: 结果目录（可选，默认使用模块级 RESULT_DIR）
        """
        self.batch_idx = batch_idx
        self.data_type = data_type
        self._result_dir = result_dir or RESULT_DIR
        self.path = self._result_dir / f'batch_{batch_idx}_{data_type}.json.gz'
        self.records: list = []
        self.idx: int = 0
        self.exhausted: bool = False
        self._load_all()
    
    def _load_all(self) -> None:
        """
        加载全部数据（一次性加载）
        
        Note:
            批次文件不大（约几MB），直接加载全部记录
        """
        if not self.path.exists():
            self.exhausted = True
            return
        
        with gzip.open(self.path, 'rt', encoding='utf-8') as f:
            self.records = json.load(f)
        
        self.idx = 0
        self.exhausted = len(self.records) == 0
    
    def peek_key(self) -> tuple[str, str] | None:
        """获取当前记录的 key (date, asset)"""
        if self.exhausted or self.idx >= len(self.records):
            return None
        rec = self.records[self.idx]
        return (rec['date'], rec['asset'])
    
    def pop_record(self) -> dict | None:
        """弹出当前记录"""
        if self.exhausted or self.idx >= len(self.records):
            self.exhausted = True
            return None
        rec = self.records[self.idx]
        self.idx += 1
        self.exhausted = self.idx >= len(self.records)
        return rec
    
    def __lt__(self, other: 'BatchStream') -> bool:
        """用于 heap 比较（按 batch_idx）"""
        return self.batch_idx < other.batch_idx
    
    def is_exhausted(self) -> bool:
        """是否已耗尽"""
        return self.exhausted or self.idx >= len(self.records)
    
    def cleanup(self) -> None:
        """清理资源"""
        self.records = []
        self.exhausted = True
        gc.collect()


# ============================================================================
# 批次保存
# ============================================================================

def save_batch_cache_sorted(
    batch_idx: int,
    factor_df: pd.DataFrame,
    return_df: pd.DataFrame,
    result_dir: Path = None,
    logger_arg: logging.Logger = None
) -> None:
    """
    保存单批次数据到临时文件（预先排序，流式写入）
    
    Args:
        batch_idx: 批次索引（从0开始）
        factor_df: 因子数据DataFrame，包含 date/asset/open/close/high/low/rsi_6/volume_ratio_5
        return_df: 收益数据DataFrame，包含 date/asset/forward_return_1d/3d/5d
        result_dir: 结果目录（可选）
        logger_arg: 日志记录器（遵循 MODULE.md 约束 77）
    """
    _logger = logger_arg or logging.getLogger(__name__)
    _result_dir = result_dir or RESULT_DIR
    
    factor_path = _result_dir / f'batch_{batch_idx}_factor.json.gz'
    return_path = _result_dir / f'batch_{batch_idx}_return.json.gz'
    
    # 写入前验证必需列
    required_factor_cols = ['date', 'asset', 'open', 'close', 'high', 'low', 'rsi_6', 'volume_ratio_5']
    required_return_cols = ['date', 'asset', 'forward_return_1d', 'forward_return_3d', 'forward_return_5d']
    
    validate_dataframe_columns(factor_df, required_factor_cols, 'factor_df')
    validate_dataframe_columns(return_df, required_return_cols, 'return_df')
    
    # 格式化并排序
    factor_df['date'] = factor_df['date'].astype(str)
    return_df['date'] = return_df['date'].astype(str)
    
    factor_df = factor_df.sort_values(['date', 'asset']).reset_index(drop=True)
    return_df = return_df.sort_values(['date', 'asset']).reset_index(drop=True)
    
    # 流式写入因子数据
    _logger.info("  保存因子数据...")
    with gzip.open(factor_path, 'wt', encoding='utf-8') as f:
        f.write('[\n')
        for i, row in enumerate(factor_df.itertuples(index=False)):
            if i > 0:
                f.write(',\n')
            record = {
                'date': row.date,
                'asset': row.asset,
                'open': round(row.open, 2),
                'close': round(row.close, 2),
                'high': round(row.high, 2),
                'low': round(row.low, 2),
                'rsi_6': round(row.rsi_6, 2),
                'volume_ratio_5': round(row.volume_ratio_5, 2)
            }
            f.write('  ' + json.dumps(record, ensure_ascii=False))
        f.write('\n]')
    
    # 流式写入收益数据
    _logger.info("  保存收益数据...")
    with gzip.open(return_path, 'wt', encoding='utf-8') as f:
        f.write('[\n')
        for i, row in enumerate(return_df.itertuples(index=False)):
            if i > 0:
                f.write(',\n')
            record = {
                'date': row.date,
                'asset': row.asset,
                'forward_return_1d': round(row.forward_return_1d, 6),
                'forward_return_3d': round(row.forward_return_3d, 6),
                'forward_return_5d': round(row.forward_return_5d, 6)
            }
            f.write('  ' + json.dumps(record, ensure_ascii=False))
        f.write('\n]')
    
    factor_size_mb = factor_path.stat().st_size / (1024 * 1024)
    return_size_mb = return_path.stat().st_size / (1024 * 1024)
    
    _logger.info(f"  ✓ 保存批次 {batch_idx}: 因子 {factor_size_mb:.2f}MB, 收益 {return_size_mb:.2f}MB")
    _logger.info(f"  当前内存: {get_memory_info_str()}")
    
    del factor_df, return_df
    gc.collect()


# ============================================================================
# N-way 合并
# ============================================================================

def n_way_merge_deduplicate(
    total_batches: int,
    data_type: str = 'factor',
    result_dir: Path = None,
    logger_arg: logging.Logger = None
) -> Path | None:
    """
    N-way merge 合并已排序的批次数据，去重
    
    Args:
        total_batches: 总批次数
        data_type: 数据类型（'factor' 或 'return'）
        result_dir: 结果目录（可选）
        logger_arg: 日志记录器（遵循 MODULE.md 约束 77）
    
    Returns:
        Path | None: 输出文件路径（无有效数据时返回 None）
    """
    _logger = logger_arg or logging.getLogger(__name__)
    _result_dir = result_dir or RESULT_DIR
    
    _logger.info(f"[{data_type}] 开始 N-way merge...")
    _logger.info(f"  当前内存: {get_memory_info_str()}")
    
    # 创建所有批次的流
    streams = []
    for batch_idx in range(total_batches):
        path = _result_dir / f'batch_{batch_idx}_{data_type}.json.gz'
        if path.exists():
            stream = BatchStream(batch_idx, data_type, result_dir=_result_dir)
            if not stream.is_exhausted():
                streams.append(stream)
    
    if not streams:
        _logger.info("  无有效批次")
        return None
    
    _logger.info(f"  有效批次: {len(streams)}/{total_batches}")
    
    # N-way merge 使用 heap
    counter = 0
    heap = []
    for stream in streams:
        key = stream.peek_key()
        if key:
            heapq.heappush(heap, (key, stream.batch_idx, counter, stream))
            counter += 1
    
    # 合并结果（流式写入文件）
    output_path = _result_dir / f'merged_{data_type}.json.gz'
    last_key = None
    same_key_records = []
    count = 0
    
    _logger.info("  开始合并...")
    
    with gzip.open(output_path, 'wt', encoding='utf-8') as f:
        f.write('[\n')
        
        while heap:
            key, batch_idx, _, stream = heapq.heappop(heap)
            record = stream.pop_record()
            
            if last_key == key:
                same_key_records.append((batch_idx, record))
            else:
                if same_key_records:
                    same_key_records.sort(key=lambda x: x[0], reverse=True)
                    best_record = same_key_records[0][1]
                    count = _write_json_record(f, best_record, count)
                    
                    if count % 50000 == 0:
                        gc.collect()
                        _logger.info(f"    已写入 {count} 条，内存: {get_memory_info_str()}")
                
                last_key = key
                same_key_records = [(batch_idx, record)]
            
            next_key = stream.peek_key()
            if next_key:
                heapq.heappush(heap, (next_key, batch_idx, counter, stream))
                counter += 1
        
        if same_key_records:
            same_key_records.sort(key=lambda x: x[0], reverse=True)
            best_record = same_key_records[0][1]
            count = _write_json_record(f, best_record, count)
        
        f.write('\n]')
    
    _logger.info(f"  合并完成: {count} 条记录")
    _logger.info(f"  输出文件: {output_path}")
    _logger.info(f"  当前内存: {get_memory_info_str()}")
    
    for stream in streams:
        stream.cleanup()
    gc.collect()
    
    return output_path


# ============================================================================
# 最终格式化
# ============================================================================

def format_final_output(
    factor_merged_path: Path | str,
    return_merged_path: Path | str,
    result_dir: Path = None,
    logger: logging.Logger = None
) -> None:
    """
    将合并后的JSON数组格式化为完整JSON文件
    
    Args:
        factor_merged_path: 合并后的因子数据路径
        return_merged_path: 合并后的收益数据路径
        result_dir: 结果目录（可选）
        logger: 日志记录器
    """
    logger = logger or logging.getLogger(__name__)
    _result_dir = result_dir or RESULT_DIR
    
    logger.info("格式化最终输出文件...")
    
    now = datetime.now()
    generated_at = now.isoformat()
    last_updated = now.strftime("%Y-%m-%d %H:%M:%S")
    
    # 处理因子数据
    date_set = set()
    asset_set = set()
    first_date = None
    last_date = None
    n_records = 0
    
    with gzip.open(factor_merged_path, 'rt', encoding='utf-8') as f:
        for line in f:
            stripped = line.strip()
            if stripped.startswith('{'):
                try:
                    rec = json.loads(stripped.rstrip(','))
                    date = rec['date']
                    asset = rec['asset']
                    date_set.add(date)
                    asset_set.add(asset)
                    if first_date is None or date < first_date:
                        first_date = date
                    if last_date is None or date > last_date:
                        last_date = date
                    n_records += 1
                except json.JSONDecodeError:
                    continue
    
    date_start = first_date
    date_end = last_date
    n_days = len(date_set)
    n_assets = len(asset_set)
    
    del date_set, asset_set
    gc.collect()
    
    logger.info(f"  交易日数: {n_days}")
    logger.info(f"  股票数量: {n_assets}")
    logger.info(f"  因子记录: {n_records}")
    
    # 写入因子文件
    factor_final_path = _result_dir / 'factor_data.json.gz'
    
    with gzip.open(factor_final_path, 'wt', encoding='utf-8') as out_f:
        out_f.write('{\n')
        out_f.write('  "meta": {\n')
        out_f.write(f'    "generated_at": "{generated_at}",\n')
        out_f.write('    "source": "sina_api_batch_external_merge",\n')
        out_f.write(f'    "n_days": {n_days},\n')
        out_f.write(f'    "n_assets": {n_assets},\n')
        out_f.write(f'    "n_records": {n_records},\n')
        out_f.write('    "date_range": {\n')
        out_f.write(f'      "start": "{date_start}",\n')
        out_f.write(f'      "end": "{date_end}"\n')
        out_f.write('    },\n')
        out_f.write(f'    "last_updated": "{last_updated}",\n')
        out_f.write(f'    "version": "{_OUTPUT_VERSION}",\n')
        out_f.write('    "fields": ["date", "asset", "open", "close", "high", "low", "rsi_6", "volume_ratio_5"],\n')
        out_f.write('    "format_note": "每条记录单行写入，便于流式解析"\n')
        out_f.write('  },\n')
        out_f.write('  "data": [\n')
        
        with gzip.open(factor_merged_path, 'rt', encoding='utf-8') as in_f:
            is_first = True
            for line in in_f:
                stripped = line.strip()
                if stripped.startswith('{'):
                    if not is_first:
                        out_f.write(',\n')
                    out_f.write('    ' + stripped.rstrip(','))
                    is_first = False
        
        out_f.write('\n  ]\n')
        out_f.write('}\n')
    
    factor_size_mb = factor_final_path.stat().st_size / (1024 * 1024)
    logger.info(f"    因子文件: {factor_final_path} ({factor_size_mb:.2f} MB)")
    
    # 处理收益数据
    n_return_records = 0
    with gzip.open(return_merged_path, 'rt', encoding='utf-8') as f:
        for line in f:
            stripped = line.strip()
            if stripped.startswith('{'):
                n_return_records += 1
    
    logger.info(f"  收益记录: {n_return_records}")
    
    return_final_path = _result_dir / 'return_data.json.gz'
    
    with gzip.open(return_final_path, 'wt', encoding='utf-8') as out_f:
        out_f.write('{\n')
        out_f.write('  "meta": {\n')
        out_f.write(f'    "generated_at": "{generated_at}",\n')
        out_f.write('    "source": "sina_api_batch_external_merge",\n')
        out_f.write(f'    "n_days": {n_days},\n')
        out_f.write(f'    "n_assets": {n_assets},\n')
        out_f.write(f'    "n_records": {n_return_records},\n')
        out_f.write('    "date_range": {\n')
        out_f.write(f'      "start": "{date_start}",\n')
        out_f.write(f'      "end": "{date_end}"\n')
        out_f.write('    },\n')
        out_f.write(f'    "last_updated": "{last_updated}",\n')
        out_f.write(f'    "version": "{_OUTPUT_VERSION}",\n')
        out_f.write('    "fields": ["date", "asset", "forward_return_1d", "forward_return_3d", "forward_return_5d"],\n')
        out_f.write('    "note": "3日和5日收益最后几天会有NaN"\n')
        out_f.write('  },\n')
        out_f.write('  "data": [\n')
        
        with gzip.open(return_merged_path, 'rt', encoding='utf-8') as in_f:
            is_first = True
            for line in in_f:
                stripped = line.strip()
                if stripped.startswith('{'):
                    if not is_first:
                        out_f.write(',\n')
                    out_f.write('    ' + stripped.rstrip(','))
                    is_first = False
        
        out_f.write('\n  ]\n')
        out_f.write('}\n')
    
    return_size_mb = return_final_path.stat().st_size / (1024 * 1024)
    logger.info(f"    收益文件: {return_final_path} ({return_size_mb:.2f} MB)")
    
    # 清理临时文件
    Path(factor_merged_path).unlink()
    Path(return_merged_path).unlink()
    
    logger.info(f"  ✓ 最终文件已保存")
    logger.info("  ✓ 格式化完成")


# ============================================================================
# 清理临时文件
# ============================================================================

def cleanup_batch_files(
    total_batches: int,
    result_dir: Path = None,
    logger: logging.Logger = None
) -> int:
    """
    清理临时文件（批次文件 + merged 合并文件）
    
    Args:
        total_batches: 总批次数
        result_dir: 结果目录（可选）
        logger: 日志记录器
    
    Returns:
        int: 删除的文件数量
    """
    logger = logger or logging.getLogger(__name__)
    _result_dir = result_dir or RESULT_DIR
    
    logger.info("[清理阶段] 删除临时批次文件...")
    
    deleted = 0
    errors = []
    
    for batch_idx in range(total_batches):
        for t in ['factor', 'return']:
            path = _result_dir / f'batch_{batch_idx}_{t}.json.gz'
            if path.exists():
                try:
                    path.unlink()
                    deleted += 1
                except Exception as e:
                    errors.append(f"{path}: {e}")
    
    for t in ['factor', 'return']:
        merged_path = _result_dir / f'merged_{t}.json.gz'
        if merged_path.exists():
            try:
                merged_path.unlink()
                deleted += 1
            except Exception as e:
                errors.append(f"{merged_path}: {e}")
    
    if errors:
        logger.warning(f"  ⚠ 删除失败 {len(errors)} 个文件")
    logger.info(f"  ✓ 已删除 {deleted} 个临时文件")
    return deleted


# ============================================================================
# 模块导出
# ============================================================================
__all__ = [
    'BatchStream',
    'save_batch_cache_sorted',
    'n_way_merge_deduplicate',
    'format_final_output',
    'cleanup_batch_files',
]