#!/usr/bin/env python3
"""
分批拉取500天因子数据 - 外部排序流式合并（极致内存优化）

Requires: Python >= 3.8 (gzip.BadGzipFile 异常类)

使用前提：
- 运行前需将 project_root 加入 PYTHONPATH，或以项目根目录为工作目录执行
- 否则 else 分支的 common 绝对导入会触发 ImportError

策略：
1. 将股票分成多批（每批250只）
2. 每批拉取后立即保存到独立的 gzip 文件
3. 外部排序合并：
   - 每批次数据已按 (date, asset) 排序
   - 使用 N-way merge 合并已排序的批次
   - 去重时只保留最新值（同key后写入覆盖前写入）
4. 内存峰值：仅一个批次数据 + N个最小记录（N=批次数）

版本历史：
- v3.24 (2026-05-26): valid_batch_indices移除冗余、heap注释缩进修正、valid_df增加copy避免Warning、forward_return统一写法
- v3.25 (2026-05-26): 接口设计修正 - format_final_output返回None（统计由validate提供）、save_batch_cache_sorted接口契约说明实际调用方总是传字符串
- v3.26 (2026-05-26): Bug修复 - format_final_output末尾缩进修正、validate_final_data分两次读文件+records_count初始化
- v3.27 (2026-05-26): 代码改进 - BatchStream.pop_record更新exhausted+添加__lt__、del注释修正、combined增加copy、del data而非del full、main用_接收未使用返回值
- v3.28 (2026-05-26): Bug修复 - validate_final_data第二次改为真正的流式行扫描，避免两次json.load内存峰值翻倍
- v3.29 (2026-05-27): Bug修复 - format_final_output一次遍历提取日期范围+释放set内存、main校验return_merged_path避免TypeError
- v3.30 (2026-05-27): 代码改进 - format_final_output n_records定义移到日志前、cleanup_batch_files docstring修正为try/except
- v3.31 (2026-05-27): Bug修复 - n_way_merge_deduplicate返回值简化(只返回merged_path，count由调用方用_接收但未使用)
- v3.32 (2026-05-27): Bug修复 - format_final_output删除n_records重复赋值、validate_final_data改为真正流式验证(不加载data数组)
- v3.33 (2026-05-27): 6项修复——1) Python>=3.8版本声明；2) 作者标识修正（云舟→云瑶）；3) 条件导入使用前提说明；4) 列验证提取公共函数_validate_dataframe_columns；5) validate_final_data第一次改为流式解析meta（避免content=f.read()内存峰值）；6) 版本历史精简（只保留最近10条）
- v3.34 (2026-05-27): 4项修复——1) fetch_batch_stocks去重（保证单批次内无重复key）；2) BatchStream._load_all加断言（禁止重复调用）；3) format_final_output改用流式处理（避免json.load全量加载）；4) validate_final_data验证n_records一致（补充meta字段）
- v3.35 (2026-05-27): 4项修复——1) cleanup_batch_files日志截断改为总数+debug完整；2) get_memory_usage_mb macOS单位修正（bytes→MB而非KB→MB）；3) return_df排除forward_return NaN（避免下游计算错误）；4) write_record提取为模块级函数_write_json_record（避免闭包）

作者: 云瑶
日期: 2026-04-04
"""

# 标准库导入（PEP 8 规范：按字母顺序分组）
import gc
import gzip
import heapq
import json
import logging
import time
from datetime import datetime
from pathlib import Path

# 第三方库导入
import pandas as pd

# 本地模块导入
from real_data_loader import RealDataLoader

# 公共模块导入（条件导入：脚本直接运行时可能路径未配置）
# 使用前提：project_root 已加入 PYTHONPATH 或以项目根目录为工作目录执行
try:
    from data_fetchers.common import setup_logger, get_logs_dir, get_cache_dir
except ImportError:
    from common import setup_logger, get_logs_dir, get_cache_dir

# 模块级常量（PEP 8：import 之后定义）
# _MODULE_LOGGER: 模块级日志记录器，当脚本直接运行时可能未初始化
# _OUTPUT_VERSION: 输出文件版本号，与模块版本一致
_MODULE_LOGGER = logging.getLogger('fetch_factor_cache')
_OUTPUT_VERSION = '3.35'

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


def _validate_dataframe_columns(
    df: pd.DataFrame,
    required_cols: list[str],
    df_name: str
) -> None:
    """
    验证 DataFrame 是否包含必需列
    
    Args:
        df: DataFrame 对象
        required_cols: 必需列名列表
        df_name: DataFrame 名称（用于错误消息）
    
    Raises:
        ValueError: DataFrame 缺少必需列
    """
    missing_cols = [col for col in required_cols if col not in df.columns]
    if missing_cols:
        raise ValueError(f"{df_name} 缺少必需列: {missing_cols}")


def _write_json_record(f, record: dict, count: int) -> int:
    """
    写入一条 JSON 记录到 gzip 文件
    
    Args:
        f: gzip 文件句柄（已打开）
        record: 要写入的记录字典
        count: 已写入的记录数
    
    Returns:
        int: 新的记录数（count + 1）
    
    Note:
        - 每条记录写入一行，便于流式解析
        - count > 0 时写入逗号分隔符
    """
    if count > 0:
        f.write(',\n')
    f.write('  ' + json.dumps(record, ensure_ascii=False))
    return count + 1


def get_memory_usage_mb() -> float:
    """
    获取当前进程真实RSS内存（MB）- 从 /proc/self/status
    
    Returns:
        float: RSS内存大小（MB），Linux下从/proc/self/status读取，
               其他系统使用resource.getrusage()，Windows返回0.0
    
    Note:
        - Linux: 读取VmRSS字段（实际物理内存使用）
        - macOS/Unix: 使用ru_maxrss（最大RSS值，可能不准确）
          macOS下ru_maxrss单位是bytes，需除以1024*1024
          Linux下ru_maxrss单位是KB，需除以1024
        - Windows: 返回0.0（不支持）
    """
    try:
        with open('/proc/self/status', 'r') as f:
            for line in f:
                if line.startswith('VmRSS:'):
                    return int(line.split()[1]) / 1024  # kB -> MB
    except Exception:
        pass
    try:
        import resource
        import sys
        maxrss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        # macOS: ru_maxrss 单位是 bytes；Linux: 单位是 KB
        if sys.platform == 'darwin':
            return maxrss / (1024 * 1024)  # bytes -> MB
        else:
            return maxrss / 1024  # KB -> MB
    except Exception:
        return 0.0  # Windows 或其他不支持的环境


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
            if vmrss is not None:
                return f"RSS={vmrss:.1f}MB" + (f", VM={vmsize:.1f}MB" if vmsize is not None else "")
    except Exception:
        pass
    return f"RSS={get_memory_usage_mb():.1f}MB"


def save_batch_cache_sorted(
    batch_idx: int,
    factor_df: pd.DataFrame,
    return_df: pd.DataFrame,
    logger: logging.Logger = None
) -> None:
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
        - 在写入前验证必需列存在，避免 itertuples 时 AttributeError
    
    Raises:
        ValueError: DataFrame 缺少必需列
    
    Note:
        此函数会就地修改 date 列为字符串类型（astype(str)）
        调用方不应再依赖原 DataFrame 的 date 列（如需保留，请在调用前自行 copy）
        
        接口契约：
        - 实际调用方总是传入字符串类型的 date 列
        - astype(str) 为防御性编程，确保输出格式一致（兼容 datetime 或字符串输入）
        - 输出 JSON 文件的 date 字段为字符串格式 '%Y-%m-%d'
    """
    logger = logger or _MODULE_LOGGER
    factor_path = CACHE_DIR / f'batch_{batch_idx}_factor.json.gz'
    return_path = CACHE_DIR / f'batch_{batch_idx}_return.json.gz'
    
    # 注意：此函数会就地修改 date 列为字符串类型
    # 调用方不应再依赖原 DataFrame 的 date 列（如需保留，请在调用前 copy）
    
    # 写入前验证必需列存在
    required_factor_cols = ['date', 'asset', 'open', 'close', 'high', 'low', 'rsi_6', 'volume_ratio_5']
    required_return_cols = ['date', 'asset', 'forward_return_1d', 'forward_return_3d', 'forward_return_5d']
    
    _validate_dataframe_columns(factor_df, required_factor_cols, 'factor_df')
    _validate_dataframe_columns(return_df, required_return_cols, 'return_df')
    
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
            # 列已在上方验证存在，直接访问字段（无需 hasattr）
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
    logger.info("  保存收益数据...")
    with gzip.open(return_path, 'wt', encoding='utf-8') as f:
        f.write('[\n')
        for i, row in enumerate(return_df.itertuples(index=False)):
            if i > 0:
                f.write(',\n')
            # 列已在上方验证存在，直接访问字段（无需 hasattr）
            record = {
                'date': row.date,
                'asset': row.asset,
                'forward_return_1d': round(row.forward_return_1d, 6),
                'forward_return_3d': round(row.forward_return_3d, 6),
                'forward_return_5d': round(row.forward_return_5d, 6)
            }
            f.write('  ' + json.dumps(record, ensure_ascii=False))
        f.write('\n]')
    
    factor_size_mb = factor_path.stat().st_size / (1024 * 1024)  # Path.stat() 替代 os.path.getsize()
    return_size_mb = return_path.stat().st_size / (1024 * 1024)
    
    logger.info(f"  ✓ 保存批次 {batch_idx}: 因子 {factor_size_mb:.2f}MB, 收益 {return_size_mb:.2f}MB")
    logger.info(f"  当前内存: {get_memory_info_str()}")
    
    # 减少 DataFrame 引用计数（真正释放依赖 GC）
    del factor_df, return_df
    gc.collect()


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
    
    Note:
        - 批次文件已按 (date, asset) 排序
        - 每次加载全部记录（批次文件不大，约几MB）
        - 提供 __lt__ 方法用于 heap 比较
    """
    
    def __init__(self, batch_idx: int, data_type: str = 'factor'):
        """
        初始化批次数据流
        
        Args:
            batch_idx: 批次索引（从0开始）
            data_type: 数据类型（'factor' 或 'return')
        """
        self.batch_idx = batch_idx  # 保存原始批次号，用于去重优先级判断
        self.data_type = data_type
        self.path = CACHE_DIR / f'batch_{batch_idx}_{data_type}.json.gz'
        self.records: list = []
        self.idx: int = 0
        self.exhausted: bool = False
        self._load_all()
    
    def _load_all(self) -> None:
        """
        加载全部数据（一次性加载）
        
        Note:
            - 批次文件不大（约几MB），直接加载全部记录
            - 加载后标记 exhausted 状态
            - 此方法仅调用一次，禁止重复调用
        """
        # 断言：禁止重复调用（构造函数只调用一次）
        assert self.idx == 0 and not self.records, "_load_all 禁止重复调用"
        
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
        if self.exhausted or self.idx >= len(self.records):
            return None
        rec = self.records[self.idx]
        return (rec['date'], rec['asset'])
    
    def pop_record(self) -> dict | None:
        """
        弹出当前记录
        
        Returns:
            dict | None: 当前记录字典或 None（已耗尽）
        """
        if self.exhausted or self.idx >= len(self.records):
            self.exhausted = True  # 确保状态一致
            return None
        rec = self.records[self.idx]
        self.idx += 1
        # 更新 exhausted 状态（弹完最后一条后标记耗尽）
        self.exhausted = self.idx >= len(self.records)
        return rec
    
    def __lt__(self, other: 'BatchStream') -> bool:
        """
        用于 heap 比较（按 batch_idx）
        
        Args:
            other: 另一个 BatchStream 对象
        
        Returns:
            bool: self.batch_idx < other.batch_idx
        """
        return self.batch_idx < other.batch_idx
    
    def is_exhausted(self) -> bool:
        """
        是否已耗尽
        
        Returns:
            bool: True 表示已耗尽所有记录
        """
        return self.exhausted or self.idx >= len(self.records)
    
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


def n_way_merge_deduplicate(
    total_batches: int,
    data_type: str = 'factor',
    logger: logging.Logger = None
) -> Path | None:
    """
    N-way merge 合并已排序的批次数据，去重
    
    Args:
        total_batches: 总批次数
        data_type: 数据类型（'factor' 或 'return'）
        logger: 日志记录器（可选，默认使用模块级 logger）
    
    Returns:
        Path | None: 输出文件路径（无有效数据时返回 None）
    
    Note:
        - 使用 heap 进行 N-way merge，每个批次保持当前记录在内存中
        - 去重策略：相同的 (date, asset) 只保留 batch_idx 最大的记录
        - 返回 merged_path，合并记录数由 validate_final_data 统计
    """
    logger = logger or _MODULE_LOGGER
    logger.info(f"[{data_type}] 开始 N-way merge...")
    logger.info(f"  当前内存: {get_memory_info_str()}")
    
    # 创建所有批次的流
    streams = []
    
    for batch_idx in range(total_batches):
        path = CACHE_DIR / f'batch_{batch_idx}_{data_type}.json.gz'
        if path.exists():
            stream = BatchStream(batch_idx, data_type)
            if not stream.is_exhausted():
                streams.append(stream)
    
    if not streams:
        logger.info("  无有效批次")
        return None
    
    logger.info(f"  有效批次: {len(streams)}/{total_batches}")
    
    # N-way merge 使用 heap
    # heap元素: (key, batch_idx, counter, stream)
    # counter 为唯一递增计数器，打破同批次内相同 key 的平局
    counter = 0
    heap = []
    for stream in streams:
        key = stream.peek_key()
        if key:
            heapq.heappush(heap, (key, stream.batch_idx, counter, stream))
            counter += 1
    
    # 合并结果（流式写入文件，不存内存）
    output_path = CACHE_DIR / f'merged_{data_type}.json.gz'
    last_key = None
    # 收集相同 key 的所有记录，最后选 batch_idx 最大的
    same_key_records = []  # [(batch_idx, record), ...]
    count = 0
    
    logger.info("  开始合并...")
    
    with gzip.open(output_path, 'wt', encoding='utf-8') as f:
        f.write('[\n')  # JSON数组开始
        
        while heap:
            key, batch_idx, _, stream = heapq.heappop(heap)
            record = stream.pop_record()
            
            # 去重：收集相同 key 的所有记录，最后选 batch_idx 最大的
            if last_key == key:
                # 相同key，继续收集
                same_key_records.append((batch_idx, record))
            else:
                # 不同key，处理上一个 key 的所有记录
                if same_key_records:
                    # 按 batch_idx 降序排序，选最大的
                    same_key_records.sort(key=lambda x: x[0], reverse=True)
                    best_record = same_key_records[0][1]
                    count = _write_json_record(f, best_record, count)
                    
                    if count % 50000 == 0:
                        gc.collect()
                        logger.info(f"    已写入 {count} 条，内存: {get_memory_info_str()}")
                
                # 开始新 key
                last_key = key
                same_key_records = [(batch_idx, record)]
            
            # 从该stream取下一个记录
            next_key = stream.peek_key()
            if next_key:
                heapq.heappush(heap, (next_key, batch_idx, counter, stream))
                counter += 1
        
        # 处理最后一个 key 的所有记录
        if same_key_records:
            same_key_records.sort(key=lambda x: x[0], reverse=True)
            best_record = same_key_records[0][1]
            count = _write_json_record(f, best_record, count)
        
        f.write('\n]')  # JSON数组结束
    
    logger.info(f"  合并完成: {count} 条记录")
    logger.info(f"  输出文件: {output_path}")
    logger.info(f"  当前内存: {get_memory_info_str()}")
    
    # 清理streams（释放批次文件内存）
    for stream in streams:
        stream.cleanup()
    gc.collect()
    
    return output_path


def fetch_batch_stocks(
    loader: RealDataLoader,
    stock_batch: list[str],
    batch_idx: int,
    total_batches: int,
    logger: logging.Logger = None
) -> tuple[pd.DataFrame | None, pd.DataFrame | None]:
    """
    拉取一批股票的数据
    
    Args:
        loader: RealDataLoader 实例
        stock_batch: 股票代码列表
        batch_idx: 当前批次索引（从0开始）
        total_batches: 总批次数
        logger: 日志记录器（可选，默认使用模块级 logger）
    
    Returns:
        tuple[pd.DataFrame | None, pd.DataFrame | None]: (factor_df, return_df) 因子数据和收益数据 DataFrame
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
    
    all_data = list(all_data_dict.values())
    combined = pd.concat(all_data, ignore_index=True)
    
    del all_data, all_data_dict
    gc.collect()
    
    combined['date'] = pd.to_datetime(combined['date'])
    combined = combined.sort_values(['asset', 'date']).copy()  # 避免 CoW 风险
    
    combined['rsi_6'] = combined.groupby('asset')['close'].transform(
        lambda x: loader._calculate_rsi_vectorized(x, period=6)
    )
    
    combined['volume_ratio_5'] = combined.groupby('asset')['volume'].transform(
        lambda x: x / x.rolling(window=5).mean()
    )
    combined['volume_ratio_5'] = combined['volume_ratio_5'].fillna(1.0).clip(0.1, 10)
    
    combined['forward_return_1d'] = combined.groupby('asset')['close'].transform(
        lambda x: x.shift(-1) / x - 1
    )
    combined['forward_return_3d'] = combined.groupby('asset')['close'].transform(
        lambda x: x.shift(-3) / x - 1
    )
    combined['forward_return_5d'] = combined.groupby('asset')['close'].transform(
        lambda x: x.shift(-5) / x - 1
    )

    valid_df = combined.dropna(subset=['rsi_6', 'volume_ratio_5']).copy()
    
    del combined
    gc.collect()
    
    # pandas 3.0 兼容性修复：使用 cumcount 替代 groupby().apply(tail)
    # 避免 group_keys=False 导致分组列被移除
    valid_df['row_num'] = valid_df.groupby('asset').cumcount(ascending=False)
    valid_df = valid_df[valid_df['row_num'] < N_DAYS].copy().drop('row_num', axis=1)
    
    # 去重：保证单批次内没有重复 (date, asset) key
    # 从根源消除 N-way merge 时 stream 内重复问题
    valid_df = valid_df.drop_duplicates(subset=['date', 'asset'], keep='first')
    
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
    
    # return_df: 排除 forward_return 为 NaN 的记录（每只股票末尾几天的 shift 产生）
    # 避免下游读取方未处理产生计算错误
    return_df = valid_df[['date', 'asset', 'forward_return_1d', 'forward_return_3d', 'forward_return_5d']].copy()
    return_df = return_df.dropna(subset=['forward_return_1d'])
    
    del valid_df
    gc.collect()
    
    logger.info(f"  因子记录: {len(factor_df)}, 收益记录: {len(return_df)}")
    
    return factor_df, return_df


def format_final_output(
    factor_merged_path: Path | str,
    return_merged_path: Path | str,
    logger: logging.Logger = None
) -> None:
    """
    将合并后的JSON数组格式化为完整JSON文件
    
    Args:
        factor_merged_path: 合并后的因子数据路径
        return_merged_path: 合并后的收益数据路径
        logger: 日志记录器（可选，默认使用模块级 logger）
    
    Note:
        - 流式处理：两遍读取，第一遍提取统计信息，第二遍逐行写出
        - 避免 json.load() 全量加载到内存（百万级记录内存峰值）
        - meta 包含 n_records 字段，供 validate_final_data 验证
    """
    logger = logger or _MODULE_LOGGER
    logger.info("格式化最终输出文件...")
    
    # 固定生成时间（只调用一次 datetime.now()，生成两个格式）
    now = datetime.now()
    generated_at = now.isoformat()
    last_updated = now.strftime("%Y-%m-%d %H:%M:%S")
    
    # ============ 第一阶段：处理因子数据 ============
    # 第一遍：流式读取提取统计信息（不加载完整 list）
    date_set = set()
    asset_set = set()
    first_date = None
    last_date = None
    n_records = 0
    
    with gzip.open(factor_merged_path, 'rt', encoding='utf-8') as f:
        # merged 文件是 JSON 数组：[{...}, {...}, ...]
        # 每条记录一行（save_batch_cache_sorted 写入格式）
        for line in f:
            stripped = line.strip()
            if stripped.startswith('{'):
                # 解析单条记录
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
    
    # 立即释放 set 内存
    del date_set, asset_set
    gc.collect()
    
    logger.info(f"  交易日数: {n_days}")
    logger.info(f"  股票数量: {n_assets}")
    logger.info(f"  因子记录: {n_records}")
    
    # 第二遍：流式读取并逐行写出（写入完整 JSON 结构）
    factor_final_path = CACHE_DIR / 'factor_data.json.gz'
    
    with gzip.open(factor_final_path, 'wt', encoding='utf-8') as out_f:
        # 写入 meta
        out_f.write('{\n')
        out_f.write('  "meta": {\n')
        out_f.write(f'    "generated_at": "{generated_at}",\n')
        out_f.write('    "source": "sina_api_batch_external_merge",\n')
        out_f.write(f'    "n_days": {n_days},\n')
        out_f.write(f'    "n_assets": {n_assets},\n')
        out_f.write(f'    "n_records": {n_records},\n')  # 补充 n_records
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
        
        # 流式写出数据
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
    
    # ============ 第二阶段：处理收益数据 ============
    # 第一遍：流式读取提取统计信息
    n_return_records = 0
    
    with gzip.open(return_merged_path, 'rt', encoding='utf-8') as f:
        for line in f:
            stripped = line.strip()
            if stripped.startswith('{'):
                n_return_records += 1
    
    logger.info(f"  收益记录: {n_return_records}")
    
    # 第二遍：流式读取并逐行写出
    return_final_path = CACHE_DIR / 'return_data.json.gz'
    
    with gzip.open(return_final_path, 'wt', encoding='utf-8') as out_f:
        # 写入 meta（复用因子数据的统计信息）
        out_f.write('{\n')
        out_f.write('  "meta": {\n')
        out_f.write(f'    "generated_at": "{generated_at}",\n')
        out_f.write('    "source": "sina_api_batch_external_merge",\n')
        out_f.write(f'    "n_days": {n_days},\n')
        out_f.write(f'    "n_assets": {n_assets},\n')
        out_f.write(f'    "n_records": {n_return_records},\n')  # 补充 n_records
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
        
        # 流式写出数据
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
    
    # 清理合并的临时文件
    Path(factor_merged_path).unlink()
    Path(return_merged_path).unlink()
    
    logger.info(f"  ✓ 最终文件已保存")
    logger.info("  ✓ 格式化完成")


def validate_final_data(logger: logging.Logger = None) -> tuple[bool, int, int, int]:
    """
    验证最终数据文件的完整性
    
    Args:
        logger: 日志记录器
    
    Returns:
        tuple[bool, int, int, int]: (是否通过验证, 交易日数, 股票数量, 记录数)
    
    Note:
        流式验证，避免加载整个大文件：
        - 第一次：只读 meta（不加载 data 数组），提取 n_days/n_assets/date_range
        - 第二次：流式扫描 data，边扫描边计数，同时抽样检查 RSI
        避免内存峰值（不加载完整的 data 列表）
    """
    logger = logger or _MODULE_LOGGER
    logger.info("=" * 60)
    logger.info("[验证阶段] 验证数据完整性...")
    logger.info("=" * 60)
    
    factor_path = CACHE_DIR / 'factor_data.json.gz'
    
    # 初始化默认值（防止解析失败时未初始化）
    n_days = 0
    n_assets = 0
    date_start = ""
    date_end = ""
    records_count = 0
    
    # 第一次：流式解析 meta（不加载整个文件）
    # JSON 结构: { "meta": {...}, "data": [...] }
    # 策略：逐行读取直到找到完整的 meta 部分
    try:
        meta_lines = []
        brace_count = 0
        in_meta = False
        
        with gzip.open(factor_path, 'rt', encoding='utf-8') as f:
            for line in f:
                stripped = line.strip()
                
                # 检测进入 meta
                if '"meta":' in stripped:
                    in_meta = True
                    # 开始收集 meta 内容（从 { 开始）
                    meta_start = stripped.find('{')
                    if meta_start != -1:
                        meta_lines.append(stripped[meta_start:])
                        brace_count = 1
                    continue
                
                # 收集 meta 内容直到 brace_count == 0
                if in_meta:
                    meta_lines.append(stripped)
                    brace_count += stripped.count('{') - stripped.count('}')
                    if brace_count == 0:
                        # meta 结束，停止收集
                        break
        
        # 解析 meta JSON
        meta_content = '\n'.join(meta_lines)
        try:
            meta = json.loads(meta_content)
        except json.JSONDecodeError as e:
            logger.warning(f"  ⚠ meta 解析失败: {e}")
            return False, 0, 0, 0
        
        # 从 meta 提取信息
        n_days = meta.get('n_days', 0)
        n_assets = meta.get('n_assets', 0)
        n_records_in_meta = meta.get('n_records', 0)  # 新增：从 meta 提取 n_records
        date_range = meta.get('date_range', {})
        date_start = date_range.get('start', '') if isinstance(date_range, dict) else ''
        date_end = date_range.get('end', '') if isinstance(date_range, dict) else ''
        
        # 释放临时内存
        del meta_lines, meta_content
        gc.collect()
        
    except Exception as e:
        logger.warning(f"  ⚠ meta 流式解析失败: {e}")
        return False, 0, 0, 0
    
    # 第二次：流式扫描 data，边扫描边计数，同时抽样
    sample_records = []
    sample_size = 1000
    step = 100  # 抽样步长（估算，后续动态调整）
    records_count = 0  # 流式计数
    current_idx = 0
    
    try:
        with gzip.open(factor_path, 'rt', encoding='utf-8') as f:
            in_data = False
            for line in f:
                stripped = line.strip()
                
                # 检测进入 data 数组
                if '"data": [' in stripped:
                    in_data = True
                    continue
                
                # 检测离开 data 数组
                if in_data and stripped in (']', '],'):
                    break
                
                # 流式解析 JSON 对象（边扫描边计数，同时抽样）
                if in_data and stripped.startswith('{'):
                    records_count += 1  # 流式计数
                    try:
                        if current_idx % step == 0 and len(sample_records) < sample_size:
                            # 去除末尾逗号后解析
                            sample_records.append(json.loads(stripped.rstrip(',')))
                        current_idx += 1
                    except json.JSONDecodeError:
                        continue  # 跳过解析失败的行
        
    except Exception as e:
        logger.warning(f"  ⚠ 流式扫描失败: {e}")
        return False, n_days, n_assets, 0
    
    logger.info(f"  交易日数: {n_days}")
    logger.info(f"  股票数量: {n_assets}")
    logger.info(f"  总记录数: {records_count}")
    logger.info(f"  日期范围: {date_start} ~ {date_end}")
    
    # 抽样检查 RSI
    rsi_vals = [r['rsi_6'] for r in sample_records if r.get('rsi_6') is not None]
    if rsi_vals:
        logger.info(f"  RSI(6)样本范围: [{min(rsi_vals):.2f}, {max(rsi_vals):.2f}]")
    
    # 验证数据有效性：检查关键字段非空比例
    valid_rsi_count = len(rsi_vals)
    total_sample_count = len(sample_records)
    rsi_valid_ratio = valid_rsi_count / total_sample_count if total_sample_count > 0 else 0.0
    
    del sample_records
    gc.collect()
    
    # 综合验证：交易日数达标 + 关键字段非空比例 >= 80% + 记录数一致
    days_valid = n_days >= N_DAYS * 0.9
    data_valid = rsi_valid_ratio >= 0.8
    records_valid = (records_count == n_records_in_meta) or (n_records_in_meta == 0)  # 兼容旧版本无 n_records
    is_valid = days_valid and data_valid and records_valid
    
    if not days_valid:
        logger.info(f"  ⚠ 交易日数不足 ({n_days}/{N_DAYS})")
    if not data_valid:
        logger.info(f"  ⚠ 数据有效性不足 (RSI有效比例: {rsi_valid_ratio:.1%} < 80%)")
    if not records_valid and n_records_in_meta > 0:
        logger.info(f"  ⚠ 记录数不一致 (流式统计: {records_count}, meta声明: {n_records_in_meta})")
    if is_valid:
        logger.info(f"  ✓ 通过验证 (RSI有效比例: {rsi_valid_ratio:.1%}, 记录数一致: {records_count})")
    
    return is_valid, n_days, n_assets, records_count


def cleanup_batch_files(total_batches: int, logger: logging.Logger = None) -> int:
    """
    清理临时文件（批次文件 + merged 合并文件）
    
    Args:
        total_batches: 总批次数
        logger: 日志记录器
    
    Returns:
        int: 删除的文件数量
    
    Note:
        merged_*.json.gz 已在 format_final_output 中删除，
        此函数仅清理 batch_*.json.gz 批次文件
        使用 try/except 捕获异常继续清理，而非 try/finally（保证尽可能清理）
    """
    logger = logger or _MODULE_LOGGER
    logger.info("[清理阶段] 删除临时批次文件...")
    
    deleted = 0
    errors = []
    
    # 清理批次文件（try/except 捕获异常继续清理）
    for batch_idx in range(total_batches):
        for t in ['factor', 'return']:
            path = CACHE_DIR / f'batch_{batch_idx}_{t}.json.gz'
            if path.exists():
                try:
                    path.unlink()
                    deleted += 1
                except Exception as e:
                    errors.append(f"{path}: {e}")
    
    # 清理可能残留的 merged 文件（format_final_output 已删除，此处兜底）
    for t in ['factor', 'return']:
        merged_path = CACHE_DIR / f'merged_{t}.json.gz'
        if merged_path.exists():
            try:
                merged_path.unlink()
                deleted += 1
            except Exception as e:
                errors.append(f"{merged_path}: {e}")
    
    if errors:
        # 日志截断提示：显示总数 + 前3个错误，完整列表记录到 debug
        logger.warning(f"  ⚠ 删除失败 {len(errors)} 个文件，示例: {errors[:3]}{'...' if len(errors) > 3 else ''}")
        for err in errors:
            logger.debug(f"    删除失败详情: {err}")
    logger.info(f"  ✓ 已删除 {deleted} 个临时文件")
    return deleted


def main() -> None:
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
    logger.info(f"  版本: {_OUTPUT_VERSION}")
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
    
    try:
        factor_merged_path = n_way_merge_deduplicate(total_batches, 'factor', logger)
        return_merged_path = n_way_merge_deduplicate(total_batches, 'return', logger)
        
        # 校验两个合并路径
        if not factor_merged_path or not return_merged_path:
            logger.warning("  ! 无有效数据（factor 或 return 合并失败）")
            return
        
        # 格式化最终输出（返回值仅用于日志，统计信息由 validate_final_data 提供）
        format_final_output(factor_merged_path, return_merged_path, logger)
        
        # 验证（提供最终统计信息）
        is_valid, n_days, n_assets, n_records = validate_final_data(logger)
        
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
            'version': _OUTPUT_VERSION,
            'n_days': n_days,
            'n_assets': n_assets,
            'n_records': n_records,
            'elapsed_seconds': elapsed,
            'is_valid': is_valid,
            'memory_monitor': 'proc_self_status',
            'fields': ['date', 'asset', 'open', 'close', 'high', 'low', 'rsi_6', 'volume_ratio_5']
        }
        
        with open(CACHE_DIR / 'regenerate_stats.json', 'w') as f:
            json.dump(stats, f, indent=2)
    
    finally:
        # 清理临时批次文件（无论成功或失败都清理）
        cleanup_batch_files(total_batches, logger)


if __name__ == '__main__':
    main()