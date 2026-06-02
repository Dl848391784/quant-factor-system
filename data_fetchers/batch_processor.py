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
- v1.1 (2026-05-27): 第二轮优化
    - BatchStream 类添加 Example/Raises 章节
    - `_write_json_record` 类型注解 Any → TextIO
- v1.2 (2026-05-27): 第三轮深度优化
    - 函数签名类型注解完整化（`Path | None`、`logging.Logger | None`）
    - `self.records` 类型注解 `list` → `list[dict]`
    - `format_final_output` 入口处统一转换为 Path
    - `except json.JSONDecodeError` 添加 debug 日志
- v1.3 (2026-05-27): 第四轮深度优化
    - 新增模块级常量 `_DATA_TYPES`（避免硬编码）
    - `_write_json_record` 添加 Example 章节
    - 删除冗余赋值 `date_start/date_end`（直接使用 `first_date/last_date`）
    - `cleanup_batch_files` 使用 `_DATA_TYPES` 常量
- v1.4 (2026-05-27): 第五轮 Bug 修复
    - `format_final_output` 收益文件 meta 使用独立统计值（return_n_days/return_n_assets/return_first_date/return_last_date），不再复用因子文件统计值
    - `format_final_output` 添加 try/except/finally 异常处理：写收益文件失败时清理残缺文件，finally 确保临时文件清理
- v1.5 (2026-05-27): 第六轮 Bug 修复与重构
    - `save_batch_cache_sorted` 使用 `_write_json_record` 辅助函数，消除内联重复代码
    - `save_batch_cache_sorted` 删除无效的 `del factor_df, return_df` 语句，添加注释说明调用方需自行管理内存
    - `format_final_output` 重构为单次遍历：统计 meta 时同步缓存行内容到列表，写出时直接遍历缓存，消除二次 IO 性能损耗
    - `cleanup_batch_files` 日志输出具体失败详情（errors 列表内容），而非仅数量
    - `__all__` 移至模块顶部（import 之后），符合 PEP8 惯例且与 dataframe_utils.py 风格一致
- v1.6 (2026-05-27): 第七轮 Bug 修复与健壮性改进
    - BatchStream 新增 `load_error` 属性：文件损坏/不存在/读取失败时记录错误信息，调用方可检查并记录日志
    - `n_way_merge_deduplicate` 检查 `load_error` 并记录 warning 日志，区分"损坏跳过"和"正常空批次"
    - `format_final_output` finally 块删除临时文件失败时记录 warning 日志（而非静默 pass），确保问题可追溯
    - `format_final_output` 重构异常处理：因子和收益文件写出统一放入 try 块，失败时清理两个残缺文件，确保输出一致性

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
from typing import TextIO

import pandas as pd

# 本地模块导入
from data_fetchers.common.paths import get_module_result_dir
from data_fetchers.common.memory_utils import get_memory_info_str
from data_fetchers.common.dataframe_utils import validate_dataframe_columns

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

# ============================================================================
# 模块级常量
# ============================================================================
RESULT_DIR = get_module_result_dir()
_OUTPUT_VERSION = '2.14'
_DATA_TYPES = ('factor', 'return')  # 数据类型列表（避免硬编码）

# ============================================================================
# 辅助函数
# ============================================================================

def _write_json_record(f: TextIO, record: dict, count: int) -> int:
    """
    流式写入单条 JSON 记录
    
    Args:
        f: gzip 文件对象（TextIO）
        record: 记录字典
        count: 当前计数
    
    Returns:
        int: 更新后的计数
    
    Example:
        >>> import gzip
        >>> from io import StringIO
        >>> # 模拟 gzip 文件写入
        >>> f = StringIO()
        >>> count = _write_json_record(f, {'date': '2026-05-27', 'asset': '000001'}, 0)
        >>> print(count)  # 1
        >>> count = _write_json_record(f, {'date': '2026-05-27', 'asset': '000002'}, 1)
        >>> print(count)  # 2（第二条记录前有逗号分隔）
    
    Note:
        内部函数，不导出到 __all__
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
    
    Example:
        >>> from data_fetchers.batch_processor import BatchStream
        >>> # 假设存在批次文件 result/batch_0_factor.json.gz
        >>> stream = BatchStream(0, 'factor')
        >>> key = stream.peek_key()  # 返回 ('2026-05-27', '000001')
        >>> record = stream.pop_record()  # 弹出第一条记录
        >>> print(stream.is_exhausted())  # False（还有记录）
        >>> stream.cleanup()  # 清理资源
    
    Raises:
        json.JSONDecodeError: 批次文件 JSON 解析失败
    """
    
    def __init__(self, batch_idx: int, data_type: str = 'factor', result_dir: Path | None = None):
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
        self.records: list[dict] = []
        self.idx: int = 0
        self.exhausted: bool = False
        self.load_error: str | None = None  # 加载错误信息（供调用方检查）
        self._load_all()
    
    def _load_all(self) -> None:
        """
        加载全部数据（一次性加载）
        
        Note:
            批次文件不大（约几MB），直接加载全部记录
            文件损坏时设置 exhausted=True、load_error=错误信息，跳过该批次，不中断整个流程
        """
        if not self.path.exists():
            self.exhausted = True
            self.load_error = "文件不存在"
            return
        
        try:
            with gzip.open(self.path, 'rt', encoding='utf-8') as f:
                self.records = json.load(f)
        except json.JSONDecodeError as e:
            # 文件损坏：跳过该批次，不中断整个流程
            self.records = []
            self.exhausted = True
            self.load_error = f"JSON解析失败: [{type(e).__name__}]: {e}"
            return
        except Exception as e:
            # 其他异常（如 gzip 解压失败）
            self.records = []
            self.exhausted = True
            self.load_error = f"读取失败: [{type(e).__name__}]: {e}"
            return
        
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
    result_dir: Path | None = None,
    logger_arg: logging.Logger | None = None
) -> None:
    """
    保存单批次数据到临时文件（预先排序，流式写入）
    
    Args:
        batch_idx: 批次索引（从0开始）
        factor_df: 因子数据DataFrame，包含 date/asset/open/close/high/low/rsi_6/volume_ratio_5/volume
        return_df: 收益数据DataFrame，包含 date/asset/forward_return_1d/3d/5d
        result_dir: 结果目录（可选）
        logger_arg: 日志记录器（遵循 MODULE.md 约束 77）
    
    Note:
        使用流式写入避免内存峰值，自动验证必需列存在
    
    Example:
        >>> import pandas as pd
        >>> from data_fetchers.batch_processor import save_batch_cache_sorted
        >>> factor_df = pd.DataFrame({
        ...     'date': ['2026-05-27', '2026-05-27'],
        ...     'asset': ['000001', '000002'],
        ...     'open': [10.0, 20.0],
        ...     'close': [10.5, 20.5],
        ...     'high': [11.0, 21.0],
        ...     'low': [9.5, 19.5],
        ...     'rsi_6': [50.0, 60.0],
        ...     'volume_ratio_5': [1.0, 1.5]
        ... })
        >>> return_df = pd.DataFrame({
        ...     'date': ['2026-05-27', '2026-05-27'],
        ...     'asset': ['000001', '000002'],
        ...     'forward_return_1d': [0.01, 0.02],
        ...     'forward_return_3d': [0.03, 0.06],
        ...     'forward_return_5d': [0.05, 0.10]
        ... })
        >>> save_batch_cache_sorted(0, factor_df, return_df)  # 保存到 result/batch_0_factor.json.gz
    
    Raises:
        ValueError: factor_df 或 return_df 缺少必需列（由 validate_dataframe_columns 抛出）
    """
    _logger = logger_arg or logging.getLogger(__name__)
    _result_dir = result_dir or RESULT_DIR
    
    factor_path = _result_dir / f'batch_{batch_idx}_factor.json.gz'
    return_path = _result_dir / f'batch_{batch_idx}_return.json.gz'
    
    # 写入前验证必需列
    required_factor_cols = ['date', 'asset', 'open', 'close', 'high', 'low', 'rsi_6', 'volume_ratio_5', 'volume']
    required_return_cols = ['date', 'asset', 'forward_return_1d', 'forward_return_3d', 'forward_return_5d']
    
    validate_dataframe_columns(factor_df, required_factor_cols, 'factor_df')
    validate_dataframe_columns(return_df, required_return_cols, 'return_df')
    
    # 格式化并排序
    factor_df['date'] = factor_df['date'].astype(str)
    return_df['date'] = return_df['date'].astype(str)
    
    factor_df = factor_df.sort_values(['date', 'asset']).reset_index(drop=True)
    return_df = return_df.sort_values(['date', 'asset']).reset_index(drop=True)
    
    # 流式写入因子数据（使用 _write_json_record 辅助函数）
    _logger.info("  保存因子数据...")
    count = 0
    with gzip.open(factor_path, 'wt', encoding='utf-8') as f:
        f.write('[\n')
        for row in factor_df.itertuples(index=False):
            record = {
                'date': row.date,
                'asset': row.asset,
                'open': round(row.open, 2),
                'close': round(row.close, 2),
                'high': round(row.high, 2),
                'low': round(row.low, 2),
                'rsi_6': round(row.rsi_6, 2),
                'volume_ratio_5': round(row.volume_ratio_5, 2),
                'volume': int(row.volume)
            }
            count = _write_json_record(f, record, count)
        f.write('\n]')
    
    # 流式写入收益数据（使用 _write_json_record 辅助函数）
    _logger.info("  保存收益数据...")
    count = 0
    with gzip.open(return_path, 'wt', encoding='utf-8') as f:
        f.write('[\n')
        for row in return_df.itertuples(index=False):
            record = {
                'date': row.date,
                'asset': row.asset,
                'forward_return_1d': round(row.forward_return_1d, 6),
                'forward_return_3d': round(row.forward_return_3d, 6),
                'forward_return_5d': round(row.forward_return_5d, 6)
            }
            count = _write_json_record(f, record, count)
        f.write('\n]')
    
    factor_size_mb = factor_path.stat().st_size / (1024 * 1024)
    return_size_mb = return_path.stat().st_size / (1024 * 1024)
    
    _logger.info(f"  ✓ 保存批次 {batch_idx}: 因子 {factor_size_mb:.2f}MB, 收益 {return_size_mb:.2f}MB")
    _logger.info(f"  当前内存: {get_memory_info_str()}")
    # Note: 调用方若需释放大 DataFrame 应在自己的作用域中管理，此处不再做无效 del


# ============================================================================
# N-way 合并
# ============================================================================

def n_way_merge_deduplicate(
    total_batches: int,
    data_type: str = 'factor',
    result_dir: Path | None = None,
    logger_arg: logging.Logger | None = None
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
    
    Note:
        使用 heapq 实现 N-way merge，相同 key 按 batch_idx 降序选择最新数据
    
    Example:
        >>> from data_fetchers.batch_processor import n_way_merge_deduplicate
        >>> # 假设已保存 3 个批次：batch_0_factor.json.gz, batch_1_factor.json.gz, batch_2_factor.json.gz
        >>> merged_path = n_way_merge_deduplicate(3, 'factor')
        >>> print(merged_path)  # PosixPath('result/merged_factor.json.gz')
    
    Raises:
        json.JSONDecodeError: 批次文件 JSON 解析失败
    """
    _logger = logger_arg or logging.getLogger(__name__)
    _result_dir = result_dir or RESULT_DIR
    
    _logger.info(f"[{data_type}] 开始 N-way merge...")
    _logger.info(f"  当前内存: {get_memory_info_str()}")
    
    # 创建所有批次的流
    streams = []
    load_errors = []  # 收集加载错误信息
    for batch_idx in range(total_batches):
        path = _result_dir / f'batch_{batch_idx}_{data_type}.json.gz'
        if path.exists():
            stream = BatchStream(batch_idx, data_type, result_dir=_result_dir)
            if stream.load_error:
                # 批次加载失败，记录日志并跳过
                load_errors.append(f"batch_{batch_idx}_{data_type}: {stream.load_error}")
            elif not stream.is_exhausted():
                streams.append(stream)
    
    if load_errors:
        _logger.warning(f"  ⚠ {len(load_errors)} 个批次加载失败: {load_errors}")
    
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
    result_dir: Path | None = None,
    output_version: str | None = None,
    logger_arg: logging.Logger | None = None
) -> None:
    """
    将合并后的JSON数组格式化为完整JSON文件
    
    Args:
        factor_merged_path: 合并后的因子数据路径
        return_merged_path: 合并后的收益数据路径
        result_dir: 结果目录（可选）
        output_version: 输出版本号（可选，默认使用模块级 _OUTPUT_VERSION）
        logger_arg: 日志记录器（遵循 MODULE.md 约束 77）
    
    Note:
        输出文件格式：{meta: {...}, data: [...]}
        自动计算 meta 信息（n_days, n_assets, date_range）
    
    Example:
        >>> from pathlib import Path
        >>> from data_fetchers.batch_processor import format_final_output
        >>> # 假设已合并生成 merged_factor.json.gz 和 merged_return.json.gz
        >>> format_final_output(
        ...     Path('result/merged_factor.json.gz'),
        ...     Path('result/merged_return.json.gz'),
        ...     output_version='3.36'
        ... )  # 输出 factor_data.json.gz 和 return_data.json.gz
    
    Raises:
        FileNotFoundError: merged 文件不存在
        json.JSONDecodeError: merged 文件 JSON 解析失败
    """
    _logger = logger_arg or logging.getLogger(__name__)
    _result_dir = result_dir or RESULT_DIR
    _version = output_version or _OUTPUT_VERSION  # 使用传入版本号或默认版本号
    
    # 统一转换为 Path（遵循 MODULE.md 参数类型约定）
    factor_merged_path = Path(factor_merged_path)
    return_merged_path = Path(return_merged_path)
    
    _logger.info("格式化最终输出文件...")
    
    now = datetime.now()
    generated_at = now.isoformat()
    last_updated = now.strftime("%Y-%m-%d %H:%M:%S")
    
    # 处理因子数据：单次遍历，缓存行内容（避免二次 IO）
    date_set = set()
    asset_set = set()
    first_date = None
    last_date = None
    n_records = 0
    factor_lines: list[str] = []  # 缓存有效行
    
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
                    factor_lines.append(stripped.rstrip(','))
                except json.JSONDecodeError as e:
                    _logger.debug(f"跳过无效JSON行: {stripped[:50]}... ({e})")
                    continue
    
    n_days = len(date_set)
    n_assets = len(asset_set)
    
    del date_set, asset_set
    gc.collect()
    
    _logger.info(f"  交易日数: {n_days}")
    _logger.info(f"  股票数量: {n_assets}")
    _logger.info(f"  因子记录: {n_records}")
    
    # 处理收益数据：单次遍历，缓存行内容（与因子数据逻辑对称）
    return_date_set = set()
    return_asset_set = set()
    return_first_date = None
    return_last_date = None
    n_return_records = 0
    return_lines: list[str] = []  # 缓存有效行
    
    with gzip.open(return_merged_path, 'rt', encoding='utf-8') as f:
        for line in f:
            stripped = line.strip()
            if stripped.startswith('{'):
                try:
                    rec = json.loads(stripped.rstrip(','))
                    date = rec['date']
                    asset = rec['asset']
                    return_date_set.add(date)
                    return_asset_set.add(asset)
                    if return_first_date is None or date < return_first_date:
                        return_first_date = date
                    if return_last_date is None or date > return_last_date:
                        return_last_date = date
                    n_return_records += 1
                    return_lines.append(stripped.rstrip(','))
                except json.JSONDecodeError as e:
                    _logger.debug(f"跳过无效JSON行: {stripped[:50]}... ({e})")
                    continue
    
    return_n_days = len(return_date_set)
    return_n_assets = len(return_asset_set)
    
    del return_date_set, return_asset_set
    gc.collect()
    
    _logger.info(f"  收益交易日数: {return_n_days}")
    _logger.info(f"  收益股票数量: {return_n_assets}")
    _logger.info(f"  收益记录: {n_return_records}")
    
    # 写出两个最终文件（统一异常处理，确保一致性）
    factor_final_path = _result_dir / 'factor_data.json.gz'
    return_final_path = _result_dir / 'return_data.json.gz'
    
    try:
        # 写入因子文件
        with gzip.open(factor_final_path, 'wt', encoding='utf-8') as out_f:
            out_f.write('{\n')
            out_f.write('  "meta": {\n')
            out_f.write(f'    "generated_at": "{generated_at}",\n')
            out_f.write('    "source": "sina_api_batch_external_merge",\n')
            out_f.write(f'    "n_days": {n_days},\n')
            out_f.write(f'    "n_assets": {n_assets},\n')
            out_f.write(f'    "n_records": {n_records},\n')
            out_f.write('    "date_range": {\n')
            out_f.write(f'      "start": "{first_date}",\n')
            out_f.write(f'      "end": "{last_date}"\n')
            out_f.write('    },\n')
            out_f.write(f'    "last_updated": "{last_updated}",\n')
            out_f.write(f'    "version": "{_version}",\n')
            out_f.write('    "fields": ["date", "asset", "open", "close", "high", "low", "rsi_6", "volume_ratio_5"],\n')
            out_f.write('    "format_note": "每条记录单行写入，便于流式解析"\n')
            out_f.write('  },\n')
            out_f.write('  "data": [\n')
            
            for i, line_content in enumerate(factor_lines):
                if i > 0:
                    out_f.write(',\n')
                out_f.write('    ' + line_content)
            
            out_f.write('\n  ]\n')
            out_f.write('}\n')
        
        factor_size_mb = factor_final_path.stat().st_size / (1024 * 1024)
        _logger.info(f"    因子文件: {factor_final_path} ({factor_size_mb:.2f} MB)")
        
        del factor_lines  # 释放缓存
        gc.collect()
        
        # 写入收益文件
        with gzip.open(return_final_path, 'wt', encoding='utf-8') as out_f:
            out_f.write('{\n')
            out_f.write('  "meta": {\n')
            out_f.write(f'    "generated_at": "{generated_at}",\n')
            out_f.write('    "source": "sina_api_batch_external_merge",\n')
            out_f.write(f'    "n_days": {return_n_days},\n')  # 使用收益数据的统计值
            out_f.write(f'    "n_assets": {return_n_assets},\n')  # 使用收益数据的统计值
            out_f.write(f'    "n_records": {n_return_records},\n')
            out_f.write('    "date_range": {\n')
            out_f.write(f'      "start": "{return_first_date}",\n')  # 使用收益数据的统计值
            out_f.write(f'      "end": "{return_last_date}"\n')  # 使用收益数据的统计值
            out_f.write('    },\n')
            out_f.write(f'    "last_updated": "{last_updated}",\n')
            out_f.write(f'    "version": "{_version}",\n')
            out_f.write('    "fields": ["date", "asset", "forward_return_1d", "forward_return_3d", "forward_return_5d"],\n')
            out_f.write('    "note": "3日和5日收益最后几天会有NaN"\n')
            out_f.write('  },\n')
            out_f.write('  "data": [\n')
            
            for i, line_content in enumerate(return_lines):
                if i > 0:
                    out_f.write(',\n')
                out_f.write('    ' + line_content)
            
            out_f.write('\n  ]\n')
            out_f.write('}\n')
        
        return_size_mb = return_final_path.stat().st_size / (1024 * 1024)
        _logger.info(f"    收益文件: {return_final_path} ({return_size_mb:.2f} MB)")
        
        _logger.info(f"  ✓ 最终文件已保存")
        _logger.info("  ✓ 格式化完成")
    
    except Exception as e:
        # 写文件失败：清理所有残缺文件（因子和收益），确保一致性
        _logger.error(f"  ✗ 写文件失败: [{type(e).__name__}]: {e}")
        for final_path in [factor_final_path, return_final_path]:
            if final_path.exists():
                try:
                    final_path.unlink()
                    _logger.info(f"  已清理残缺文件: {final_path}")
                except Exception as cleanup_err:
                    _logger.warning(f"  清理残缺文件失败 {final_path}: {cleanup_err}")
        raise  # 重新抛出异常让调用方感知
    
    finally:
        # 确保临时文件清理（无论成功或失败）
        if factor_merged_path.exists():
            try:
                factor_merged_path.unlink()
            except Exception as e:
                _logger.warning(f"  清理临时文件失败 {factor_merged_path}: [{type(e).__name__}]: {e}")
        if return_merged_path.exists():
            try:
                return_merged_path.unlink()
            except Exception as e:
                _logger.warning(f"  清理临时文件失败 {return_merged_path}: [{type(e).__name__}]: {e}")


# ============================================================================
# 清理临时文件
# ============================================================================

def cleanup_batch_files(
    total_batches: int,
    result_dir: Path | None = None,
    logger_arg: logging.Logger | None = None
) -> int:
    """
    清理临时文件（批次文件 + merged 合并文件）
    
    Args:
        total_batches: 总批次数
        result_dir: 结果目录（可选）
        logger_arg: 日志记录器（遵循 MODULE.md 约束 77）
    
    Returns:
        int: 删除的文件数量
    
    Note:
        删除 batch_*_*.json.gz 和 merged_*.json.gz 临时文件
    
    Example:
        >>> from data_fetchers.batch_processor import cleanup_batch_files
        >>> deleted = cleanup_batch_files(3)  # 清理 3 个批次的所有临时文件
        >>> print(deleted)  # 删除的文件数量（如 8 = 3*2 + 2）
    
    Raises:
        无（删除失败仅记录 warning 日志，不影响返回值）
    """
    _logger = logger_arg or logging.getLogger(__name__)
    _result_dir = result_dir or RESULT_DIR
    
    _logger.info("[清理阶段] 删除临时批次文件...")
    
    deleted = 0
    errors = []
    
    for batch_idx in range(total_batches):
        for data_type in _DATA_TYPES:
            path = _result_dir / f'batch_{batch_idx}_{data_type}.json.gz'
            if path.exists():
                try:
                    path.unlink()
                    deleted += 1
                except Exception as e:
                    errors.append(f"{path}: [{type(e).__name__}]: {e}")
    
    for data_type in _DATA_TYPES:
        merged_path = _result_dir / f'merged_{data_type}.json.gz'
        if merged_path.exists():
            try:
                merged_path.unlink()
                deleted += 1
            except Exception as e:
                errors.append(f"{merged_path}: [{type(e).__name__}]: {e}")
    
    if errors:
        _logger.warning(f"  ⚠ 删除失败 {len(errors)} 个文件: {errors}")
    _logger.info(f"  ✓ 已删除 {deleted} 个临时文件")
    return deleted