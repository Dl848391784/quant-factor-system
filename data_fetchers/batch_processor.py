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
- v1.7 (2026-06-15): 第八轮 Bug 修复
    - `n_way_merge_deduplicate` 抽取 `_emit_record` 辅助函数：循环内 + 循环后最终写出统一应用 `count % 50000` 进度日志和 gc 触发，消除最终记录漏掉进度日志的边界条件
    - `n_way_merge_deduplicate` 删除 `path.exists()` 前置过滤，由 BatchStream._load_all 的 `load_error="文件不存在"` 分支统一处理，消除调用方与类的重复检查
    - `_scan_merged_file` 改为先 `json.loads(stripped)`、失败再 `json.loads(stripped[:-1])` 两段式解析，避免对字段值末尾的逗号字符做错误剥离
    - `format_final_output` except 块用 `factor_written`/`return_written` 标志位精准识别"已成功写出"与"写到一半失败"，仅清理失败/未写完的文件，避免误删有效输出
    - `save_batch_cache_sorted` 删除 `factor_df.copy()`/`return_df.copy()`，改用 `.assign(date=...).sort_values(...).reset_index(...)` 链式调用避免双倍内存峰值
    - `_write_final_file` date_range null 处理消除 `"null"` 字符串中间变量，直接用 `is not None` 判断生成 JSON 字符串，避免 `first_date == "null"` 字符串歧义
- v1.8 (2026-06-15): 第九轮 Bug 修复
    - `_emit_record` 进度日志判断改为 `count > 0 and count % 50000 == 0`，防御 count=0 误触发
    - 新增模块级常量 `_LOAD_ERROR_FILE_NOT_FOUND`：`BatchStream._load_all` 文件不存在时使用，`n_way_merge_deduplicate` 区分"业务正常缺失批次"与"实际加载错误"，仅后者记录 warning
    - `n_way_merge_deduplicate` 在 load_error/空批次分支补充调用 `stream.cleanup()`，与正常 stream 末尾清理风格一致
    - 新增 `_iter_merged_records` 流式生成器 + `_scan_and_write_final` 函数，将"扫描 merged 文件 + 写出最终文件"合并为单次遍历，`format_final_output` 改为先处理因子并落盘释放，再处理收益，避免两份 lines 同时驻留内存
    - `format_final_output` except 块反转为原子清理：因子+收益是配套数据契约，任一失败都清理两个最终输出文件，避免下游读到单边数据
    - `cleanup_batch_files` Example 注释更新：说明 merged 文件通常已在 `format_final_output` 中清理，本函数仅作兜底
- v1.9 (2026-06-15): 第十轮 Bug 修复（死代码清理 + 性能优化 + 日志/注释精修）
    - 删除孤儿函数 `_write_final_file` 和 `_scan_merged_file`（自 v1.8 重构为 `_scan_and_write_final` 后已无生产调用方），同步迁移测试到新代码路径
    - 新增轻量生成器 `_iter_merged_lines`：仅做行过滤+逗号剥离不解析 dict，`_scan_and_write_final` 第二遍写出 data 数组改用此生成器避免重复 JSON 解析
    - `_iter_merged_records` 补全返回类型注解 `Generator[tuple[str, dict], None, None]`，顶部 import 增补 `Generator`
    - `format_final_output` 调用 `_scan_and_write_final` 前后各加 info 日志说明"两遍扫描-写出"的取舍，便于性能问题追溯
    - `format_final_output` except 块清理日志级别 info → warning，与异常上下文语气一致
    - `n_way_merge_deduplicate` 删除"正常但空批次"的冗余 `stream.cleanup()` else 分支（cleanup 对空列表是空操作），改为注释说明
    - `BatchStream._load_all` 末尾 `self.exhausted = len(self.records) == 0` 加注释明确"空文件是正常情况"
    - `save_batch_cache_sorted` Example docstring 的 factor_df 补充 `volume` 字段（required_factor_cols 包含但示例缺失会导致 doctest 失败）
    - `_scan_and_write_final` Note 章节明确"两遍 IO 取舍"：用 2x 文件 IO 换 0 份 lines 内存峰值

作者: 云瑶
创建日期: 2026-05-27
"""

import gc
import gzip
import heapq
import json
import logging
from collections.abc import Generator
from datetime import datetime
from pathlib import Path
from typing import TextIO

import pandas as pd

from data_fetchers.common.dataframe_utils import validate_dataframe_columns
from data_fetchers.common.memory_utils import get_memory_info_str

# 本地模块导入
from data_fetchers.common.paths import get_module_result_dir


# ============================================================================
# 模块导出
# ============================================================================
__all__ = [
    "BatchStream",
    "save_batch_cache_sorted",
    "n_way_merge_deduplicate",
    "format_final_output",
    "cleanup_batch_files",
]

# ============================================================================
# 模块级常量
# ============================================================================
RESULT_DIR = get_module_result_dir()
_OUTPUT_VERSION = "2.14"
_DATA_TYPES = ("factor", "return")  # 数据类型列表（避免硬编码）

# load_error 标识常量：用于调用方区分"批次正常缺失"与"实际加载错误"
# 文件不存在 → 业务正常（某批次未产生数据），调用方应静默跳过
# JSON解析失败/读取失败 → 实际错误，调用方应记录 warning
_LOAD_ERROR_FILE_NOT_FOUND = "文件不存在"

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
        >>> count = _write_json_record(f, {"date": "2026-05-27", "asset": "000001"}, 0)
        >>> print(count)  # 1
        >>> count = _write_json_record(f, {"date": "2026-05-27", "asset": "000002"}, 1)
        >>> print(count)  # 2（第二条记录前有逗号分隔）

    Note:
        内部函数，不导出到 __all__
    """
    if count > 0:
        f.write(",\n")
    f.write("  " + json.dumps(record, ensure_ascii=False))
    return count + 1


def _iter_merged_lines(merged_path: Path) -> Generator[str, None, None]:
    """轻量流式迭代合并文件的有效 JSON 行（不解析为 dict）。

    Args:
        merged_path: 合并文件路径

    Yields:
        str: 已剥离行末逗号的有效 JSON 行内容（保证可被 json.loads 解析）

    Note:
        内部生成器，不导出到 __all__
        相比 `_iter_merged_records`：仅做行过滤+逗号剥离，不解析 dict、不查 KeyError，
        用于"已确认有效（第一遍扫描通过）"的二次重读，避免重复解析浪费 CPU。

        过滤规则：
        - 行首不是 "{" 的跳过（数组括号、空行等）
        - 行末有逗号则剥离（merged 文件数组分隔符 ",\n"）

        注意：本生成器不做 JSON 完整性校验，调用方需保证文件已通过 `_iter_merged_records`
        预扫描（如 `_scan_and_write_final` 第一遍统计 meta 的过程）。
    """
    with gzip.open(merged_path, "rt", encoding="utf-8") as f:
        for line in f:
            stripped = line.strip()
            if not stripped.startswith("{"):
                continue
            if stripped.endswith(","):
                yield stripped[:-1]
            else:
                yield stripped


def _iter_merged_records(merged_path: Path, logger: logging.Logger) -> Generator[tuple[str, dict], None, None]:
    """流式迭代合并文件的 (line_content, parsed_dict) 对。

    Args:
        merged_path: 合并文件路径
        logger: 日志记录器

    Yields:
        tuple[str, dict]: (line_content, 解析后的记录字典)

    Note:
        内部生成器，不导出到 __all__
        两段式 JSON 解析，避免 rstrip(",") 误剥离字段值末尾逗号。
        若仅需 line_content 不需 dict，请使用更轻量的 `_iter_merged_lines`。
    """
    with gzip.open(merged_path, "rt", encoding="utf-8") as f:
        for line in f:
            stripped = line.strip()
            if not stripped.startswith("{"):
                continue
            # 两段式解析：先尝试原样，失败再剥离行末逗号
            try:
                rec = json.loads(stripped)
                line_content = stripped
            except json.JSONDecodeError:
                if stripped.endswith(","):
                    try:
                        rec = json.loads(stripped[:-1])
                        line_content = stripped[:-1]
                    except json.JSONDecodeError as e:
                        logger.debug("跳过无效JSON行: %s... (%s)", stripped[:50], e)
                        continue
                else:
                    logger.debug("跳过无效JSON行: %s...", stripped[:50])
                    continue
            try:
                _ = rec["date"]
                _ = rec["asset"]
            except KeyError as e:
                logger.debug("跳过缺少必需字段的记录: %s... (%s)", stripped[:50], e)
                continue
            yield line_content, rec


def _scan_and_write_final(
    merged_path: Path,
    output_path: Path,
    meta_template: dict,
    logger: logging.Logger,
) -> tuple[float, dict]:
    """流式扫描 merged 文件并直接写出最终文件，避免 lines 全量驻留内存。

    Args:
        merged_path: 合并文件路径
        output_path: 最终输出文件路径
        meta_template: meta 字典模板（不含 n_days/n_assets/n_records/first_date/last_date，
                       这些由本函数扫描后填充）
        logger: 日志记录器

    Returns:
        tuple: (size_mb, stats_dict) 文件大小 MB + 扫描统计信息字典
               stats_dict 包含 n_days/n_assets/n_records/first_date/last_date

    Note:
        内部函数，不导出到 __all__
        相比"先 _scan_merged_file 全量缓存 + 再 _write_final_file 写出"的两阶段实现，
        本函数将扫描与写出合并为单次写出（仅一份 lines 不驻留内存），但代价是对 merged
        文件做两遍 IO：

          - 第一遍 `_iter_merged_records` 解析每行为 dict，统计 meta（date/asset 唯一集、
            n_records、first/last_date）。
          - 第二遍 `_iter_merged_lines` **仅做行过滤+逗号剥离**，不解析 dict、不查 KeyError，
            因为有效性已在第一遍由 `_iter_merged_records` 保证。

        取舍：用 2x 文件 IO 换 0 份 lines 内存峰值。merged 文件已 gzip 压缩，IO 开销可接受；
        换来的内存收益在大盘场景（数百万记录）显著。性能问题排查请关注两次 IO 的耗时差异。
    """
    # 第一遍：扫描 meta 统计
    date_set: set = set()
    asset_set: set = set()
    first_date: str | None = None
    last_date: str | None = None
    n_records = 0
    for _line_content, rec in _iter_merged_records(merged_path, logger):
        date = rec["date"]
        asset = rec["asset"]
        date_set.add(date)
        asset_set.add(asset)
        if first_date is None or date < first_date:
            first_date = date
        if last_date is None or date > last_date:
            last_date = date
        n_records += 1

    n_days = len(date_set)
    n_assets = len(asset_set)
    # 释放 set 内存（asset_set 在大盘可能数千只）
    del date_set
    del asset_set

    # 组装最终 meta（扫描结果 + 调用方提供的固定字段）
    meta = dict(meta_template)
    meta.update(
        {
            "n_days": n_days,
            "n_assets": n_assets,
            "n_records": n_records,
            "first_date": first_date,
            "last_date": last_date,
        }
    )

    # 第二遍：流式写出 meta + data
    # 处理 date_range null（直接用 is not None 判断，避免 first_date 真实值恰好是 "null" 时的字符串歧义）
    start_json = json.dumps(first_date) if first_date is not None else "null"
    end_json = json.dumps(last_date) if last_date is not None else "null"

    extra_key = meta.get("extra_key")
    extra_value = meta.get("extra_value")
    has_extra = extra_key and extra_value is not None

    with gzip.open(output_path, "wt", encoding="utf-8") as out_f:
        out_f.write("{\n")
        out_f.write('  "meta": {\n')
        out_f.write(f'    "generated_at": "{meta["generated_at"]}",\n')
        out_f.write(f'    "source": "{meta["source"]}",\n')
        out_f.write(f'    "n_days": {meta["n_days"]},\n')
        out_f.write(f'    "n_assets": {meta["n_assets"]},\n')
        out_f.write(f'    "n_records": {meta["n_records"]},\n')
        out_f.write('    "date_range": {\n')
        out_f.write(f'      "start": {start_json},\n')
        out_f.write(f'      "end": {end_json}\n')
        out_f.write("    },\n")
        out_f.write(f'    "last_updated": "{meta["last_updated"]}",\n')
        out_f.write(f'    "version": "{meta["version"]}",\n')
        fields_json = json.dumps(meta["fields"])
        out_f.write(f'    "fields": {fields_json}{"," if has_extra else ""}\n')
        if has_extra:
            extra_json = json.dumps(extra_value)
            out_f.write(f'    "{extra_key}": {extra_json}\n')
        out_f.write("  },\n")
        out_f.write('  "data": [\n')

        # 流式写出 data 数组（第二遍 IO：用轻量 _iter_merged_lines，不再解析 dict）
        first_record = True
        for line_content in _iter_merged_lines(merged_path):
            if first_record:
                first_record = False
            else:
                out_f.write(",\n")
            out_f.write("    " + line_content)

        out_f.write("\n  ]\n")
        out_f.write("}\n")

    size_mb = output_path.stat().st_size / (1024 * 1024)
    stats = {
        "n_days": n_days,
        "n_assets": n_assets,
        "n_records": n_records,
        "first_date": first_date,
        "last_date": last_date,
    }
    return size_mb, stats


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
        >>> stream = BatchStream(0, "factor")
        >>> key = stream.peek_key()  # 返回 ('2026-05-27', '000001')
        >>> record = stream.pop_record()  # 弹出第一条记录
        >>> print(stream.is_exhausted())  # False（还有记录）
        >>> stream.cleanup()  # 清理资源

    Raises:
        json.JSONDecodeError: 批次文件 JSON 解析失败
    """

    def __init__(self, batch_idx: int, data_type: str = "factor", result_dir: Path | None = None):
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
        self.path = self._result_dir / f"batch_{batch_idx}_{data_type}.json.gz"
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
            self.load_error = _LOAD_ERROR_FILE_NOT_FOUND
            return

        try:
            with gzip.open(self.path, "rt", encoding="utf-8") as f:
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
        # 空文件是正常情况（该批次抓取期间无符合条件的数据），不视为错误：
        # exhausted=True 让 peek_key/pop_record 立即返回 None，调用方自然过滤掉
        self.exhausted = len(self.records) == 0

    def peek_key(self) -> tuple[str, str] | None:
        """获取当前记录的 key (date, asset)"""
        if self.exhausted or self.idx >= len(self.records):
            return None
        rec = self.records[self.idx]
        return (rec["date"], rec["asset"])

    def pop_record(self) -> dict | None:
        """弹出当前记录"""
        if self.exhausted or self.idx >= len(self.records):
            self.exhausted = True
            return None
        rec = self.records[self.idx]
        self.idx += 1
        self.exhausted = self.idx >= len(self.records)
        return rec

    def __lt__(self, other: "BatchStream") -> bool:
        """用于 heap 比较（按 batch_idx）"""
        return self.batch_idx < other.batch_idx

    def is_exhausted(self) -> bool:
        """是否已耗尽"""
        return self.exhausted or self.idx >= len(self.records)

    def cleanup(self) -> None:
        """清理资源（仅清空列表，不调用 gc.collect，在 merge 末尾统一调用）"""
        self.records = []
        self.exhausted = True


# ============================================================================
# 批次保存
# ============================================================================


def save_batch_cache_sorted(
    batch_idx: int,
    factor_df: pd.DataFrame,
    return_df: pd.DataFrame,
    result_dir: Path | None = None,
    logger_arg: logging.Logger | None = None,
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
        >>> factor_df = pd.DataFrame(
        ...     {
        ...         "date": ["2026-05-27", "2026-05-27"],
        ...         "asset": ["000001", "000002"],
        ...         "open": [10.0, 20.0],
        ...         "close": [10.5, 20.5],
        ...         "high": [11.0, 21.0],
        ...         "low": [9.5, 19.5],
        ...         "rsi_6": [50.0, 60.0],
        ...         "volume_ratio_5": [1.0, 1.5],
        ...         "volume": [1000000, 2000000],
        ...     }
        ... )
        >>> return_df = pd.DataFrame(
        ...     {
        ...         "date": ["2026-05-27", "2026-05-27"],
        ...         "asset": ["000001", "000002"],
        ...         "forward_return_1d": [0.01, 0.02],
        ...         "forward_return_3d": [0.03, 0.06],
        ...         "forward_return_5d": [0.05, 0.10],
        ...     }
        ... )
        >>> save_batch_cache_sorted(0, factor_df, return_df)  # 保存到 result/batch_0_factor.json.gz

    Raises:
        ValueError: factor_df 或 return_df 缺少必需列（由 validate_dataframe_columns 抛出）
    """
    _logger = logger_arg or logging.getLogger(__name__)
    _result_dir = result_dir or RESULT_DIR

    factor_path = _result_dir / f"batch_{batch_idx}_factor.json.gz"
    return_path = _result_dir / f"batch_{batch_idx}_return.json.gz"

    # 写入前验证必需列
    required_factor_cols = ["date", "asset", "open", "close", "high", "low", "rsi_6", "volume_ratio_5", "volume"]
    required_return_cols = ["date", "asset", "forward_return_1d", "forward_return_3d", "forward_return_5d"]

    validate_dataframe_columns(factor_df, required_factor_cols, "factor_df")
    validate_dataframe_columns(return_df, required_return_cols, "return_df")

    # 格式化并排序：用 .assign() 转 date 列 + sort_values + reset_index 链式调用
    # 链式调用本就返回新 DataFrame，避免 .copy() 造成的双倍内存峰值
    factor_df = (
        factor_df.assign(date=factor_df["date"].astype(str)).sort_values(["date", "asset"]).reset_index(drop=True)
    )
    return_df = (
        return_df.assign(date=return_df["date"].astype(str)).sort_values(["date", "asset"]).reset_index(drop=True)
    )

    # 流式写入因子数据（使用 _write_json_record 辅助函数）
    _logger.info("  保存因子数据...")
    count = 0
    with gzip.open(factor_path, "wt", encoding="utf-8") as f:
        f.write("[\n")
        for row in factor_df.itertuples(index=False):
            record = {
                "date": row.date,
                "asset": row.asset,
                "open": round(row.open, 2),
                "close": round(row.close, 2),
                "high": round(row.high, 2),
                "low": round(row.low, 2),
                "rsi_6": round(row.rsi_6, 2),
                "volume_ratio_5": round(row.volume_ratio_5, 2),
                "volume": int(row.volume),
            }
            count = _write_json_record(f, record, count)
        f.write("\n]")

    # 流式写入收益数据（使用 _write_json_record 辅助函数）
    _logger.info("  保存收益数据...")
    count = 0
    with gzip.open(return_path, "wt", encoding="utf-8") as f:
        f.write("[\n")
        for row in return_df.itertuples(index=False):
            record = {
                "date": row.date,
                "asset": row.asset,
                "forward_return_1d": round(row.forward_return_1d, 6),
                "forward_return_3d": round(row.forward_return_3d, 6),
                "forward_return_5d": round(row.forward_return_5d, 6),
            }
            count = _write_json_record(f, record, count)
        f.write("\n]")

    factor_size_mb = factor_path.stat().st_size / (1024 * 1024)
    return_size_mb = return_path.stat().st_size / (1024 * 1024)

    _logger.info("  ✓ 保存批次 %s: 因子 %.2fMB, 收益 %.2fMB", batch_idx, factor_size_mb, return_size_mb)
    _logger.info("  当前内存: %s", get_memory_info_str())
    # Note: 调用方若需释放大 DataFrame 应在自己的作用域中管理，此处不再做无效 del


def _emit_record(
    f: TextIO,
    same_key_records: list[tuple[int, dict]],
    count: int,
    logger: logging.Logger | None = None,
) -> int:
    """从相同 key 的候选记录中选取最新批次写出，含进度日志和 gc 触发。

    Args:
        f: gzip 文件对象（TextIO）
        same_key_records: 相同 key 的 (batch_idx, record) 列表
        count: 当前已写出的记录数
        logger: 日志记录器

    Returns:
        int: 更新后的 count

    Note:
        内部函数，不导出到 __all__
    """
    if not same_key_records:
        return count
    same_key_records.sort(key=lambda x: x[0], reverse=True)
    best_record = same_key_records[0][1]
    count = _write_json_record(f, best_record, count)

    # 防御性判断：count > 0 避免未来重构破坏不变量时 count=0 误触发
    # （当前 _write_json_record 必 +1，count 进入此分支时 >=1，但显式判断更稳健）
    if count > 0 and count % 50000 == 0:
        _logger = logger or logging.getLogger(__name__)
        gc.collect()
        _logger.info("    已写入 %s 条，内存: %s", count, get_memory_info_str())

    return count


# ============================================================================
# N-way 合并
# ============================================================================


def n_way_merge_deduplicate(
    total_batches: int,
    data_type: str = "factor",
    result_dir: Path | None = None,
    logger_arg: logging.Logger | None = None,
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
        >>> merged_path = n_way_merge_deduplicate(3, "factor")
        >>> print(merged_path)  # PosixPath('result/merged_factor.json.gz')

    Raises:
        json.JSONDecodeError: 批次文件 JSON 解析失败
    """
    _logger = logger_arg or logging.getLogger(__name__)
    _result_dir = result_dir or RESULT_DIR

    _logger.info("[%s] 开始 N-way merge...", data_type)
    _logger.info("  当前内存: %s", get_memory_info_str())

    # 创建所有批次的流（不预先检查 path.exists()，由 BatchStream._load_all 统一处理）
    # 区分两类 load_error：
    #   - 文件不存在 → 业务正常（该批次无数据），静默跳过
    #   - JSON解析/读取失败 → 实际错误，记录 warning 供后续排查
    streams = []
    load_errors = []  # 仅收集真实加载错误，不含"文件不存在"
    for batch_idx in range(total_batches):
        stream = BatchStream(batch_idx, data_type, result_dir=_result_dir)
        if stream.load_error:
            if stream.load_error != _LOAD_ERROR_FILE_NOT_FOUND:
                # 真实加载错误：记录 warning
                load_errors.append(f"batch_{batch_idx}_{data_type}: {stream.load_error}")
            # 文件不存在：静默跳过（业务正常）
            stream.cleanup()  # 与正常 stream 末尾 cleanup 风格一致
        elif not stream.is_exhausted():
            streams.append(stream)
        # 注：空批次（无 load_error 但 records 为空）已被 BatchStream._load_all 标记为
        # exhausted=True，is_exhausted() 检查返回 True 故不进入 streams；其 records 已是
        # 空列表，无需 cleanup（cleanup 仅清理 records 列表，对空列表是空操作）。

    if load_errors:
        _logger.warning("  ⚠ %s 个批次加载失败: %s", len(load_errors), load_errors)

    if not streams:
        _logger.info("  无有效批次")
        return None

    _logger.info("  有效批次: %s/%s", len(streams), total_batches)

    # N-way merge 使用 heap
    counter = 0
    heap = []
    for stream in streams:
        key = stream.peek_key()
        if key:
            heapq.heappush(heap, (key, stream.batch_idx, counter, stream))
            counter += 1

    # 合并结果（流式写入文件）
    output_path = _result_dir / f"merged_{data_type}.json.gz"
    last_key = None
    same_key_records = []
    count = 0

    _logger.info("  开始合并...")

    with gzip.open(output_path, "wt", encoding="utf-8") as f:
        f.write("[\n")

        while heap:
            key, batch_idx, _, stream = heapq.heappop(heap)
            record = stream.pop_record()

            if last_key == key:
                same_key_records.append((batch_idx, record))
            else:
                # 写出上一组同 key 候选（含进度日志 + gc）
                count = _emit_record(f, same_key_records, count, _logger)

                last_key = key
                same_key_records = [(batch_idx, record)]

            next_key = stream.peek_key()
            if next_key:
                heapq.heappush(heap, (next_key, batch_idx, counter, stream))
                counter += 1

        # 循环结束后补写最后一组（同样走 _emit_record，进度日志/gc 时机统一）
        count = _emit_record(f, same_key_records, count, _logger)

        f.write("\n]")

    _logger.info("  合并完成: %s 条 → %s, 内存: %s", count, output_path, get_memory_info_str())

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
    logger_arg: logging.Logger | None = None,
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
        ...     Path("result/merged_factor.json.gz"), Path("result/merged_return.json.gz"), output_version="3.36"
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

    _logger.info("格式化最终输出文件: 因子=%s, 收益=%s", factor_merged_path, return_merged_path)

    now = datetime.now()
    generated_at = now.isoformat()
    last_updated = now.strftime("%Y-%m-%d %H:%M:%S")

    factor_final_path = _result_dir / "factor_data.json.gz"
    return_final_path = _result_dir / "return_data.json.gz"

    # meta 模板（n_days/n_assets/n_records/first_date/last_date 由 _scan_and_write_final 扫描后填充）
    factor_meta_template = {
        "generated_at": generated_at,
        "source": "sina_api_batch_external_merge",
        "last_updated": last_updated,
        "version": _version,
        "fields": ["date", "asset", "open", "close", "high", "low", "rsi_6", "volume_ratio_5", "volume"],
        "extra_key": "format_note",
        "extra_value": "每条记录单行写入，便于流式解析",
    }
    return_meta_template = {
        "generated_at": generated_at,
        "source": "sina_api_batch_external_merge",
        "last_updated": last_updated,
        "version": _version,
        "fields": ["date", "asset", "forward_return_1d", "forward_return_3d", "forward_return_5d"],
        "extra_key": "note",
        "extra_value": "3日和5日收益最后几天会有NaN",
    }

    try:
        # 因子：扫描 + 写出合并为单次写出（_scan_and_write_final 内部对 merged 文件做两遍 IO）
        # 取舍：用 2x merged 文件 IO 换 0 份 lines 内存峰值，性能排查可关注此处耗时
        _logger.info("  [因子] 开始两遍扫描-写出（meta 第一遍解析 dict，data 第二遍仅过滤行）")
        factor_size_mb, factor_stats = _scan_and_write_final(
            factor_merged_path, factor_final_path, factor_meta_template, _logger
        )
        _logger.info("  [因子] 两遍扫描-写出完成")
        _logger.info(
            "  因子统计: %s日 × %s只, %s条记录",
            factor_stats["n_days"],
            factor_stats["n_assets"],
            factor_stats["n_records"],
        )
        _logger.info("    因子文件: %s (%.2f MB)", factor_final_path, factor_size_mb)
        gc.collect()  # 释放因子扫描期间的临时对象，再开始处理收益

        # 收益：因子已落盘，此时仅持有收益的扫描数据，内存峰值大幅降低
        _logger.info("  [收益] 开始两遍扫描-写出")
        return_size_mb, return_stats = _scan_and_write_final(
            return_merged_path, return_final_path, return_meta_template, _logger
        )
        _logger.info("  [收益] 两遍扫描-写出完成")
        _logger.info(
            "  收益统计: %s日 × %s只, %s条记录",
            return_stats["n_days"],
            return_stats["n_assets"],
            return_stats["n_records"],
        )
        _logger.info("    收益文件: %s (%.2f MB)", return_final_path, return_size_mb)

        _logger.info("  ✓ 格式化完成")

    except Exception as e:
        # 原子清理：因子+收益必须配套使用，任一失败都清理两个最终文件，避免下游读到不一致数据
        # （此处反转了 v1.7 的"保留已成功因子"决策——业务侧因子和收益是配套数据契约，
        #   单独的因子文件对下游 factor_generator 无意义）
        _logger.error("  ✗ 写文件失败: [%s]: %s", type(e).__name__, e)
        for final_path in (factor_final_path, return_final_path):
            if final_path.exists():
                try:
                    final_path.unlink()
                    _logger.warning("  已清理输出文件（保持原子性）: %s", final_path)
                except Exception as cleanup_err:
                    _logger.warning(
                        "  清理输出文件失败 %s: [%s]: %s",
                        final_path,
                        type(cleanup_err).__name__,
                        cleanup_err,
                    )
        raise  # 重新抛出异常让调用方感知

    finally:
        # 确保临时文件清理（无论成功或失败）
        if factor_merged_path.exists():
            try:
                factor_merged_path.unlink()
            except Exception as e:
                _logger.warning("  清理临时文件失败 %s: [%s]: %s", factor_merged_path, type(e).__name__, e)
        if return_merged_path.exists():
            try:
                return_merged_path.unlink()
            except Exception as e:
                _logger.warning("  清理临时文件失败 %s: [%s]: %s", return_merged_path, type(e).__name__, e)


# ============================================================================
# 清理临时文件
# ============================================================================


def cleanup_batch_files(
    total_batches: int, result_dir: Path | None = None, logger_arg: logging.Logger | None = None
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
        merged_*.json.gz 通常已在 `format_final_output` 的 finally 块中清理，
        本函数仅作兜底。已存在性检查，重复删除安全。

    Example:
        >>> from data_fetchers.batch_processor import cleanup_batch_files
        >>> deleted = cleanup_batch_files(3)  # 清理 3 个批次的所有临时文件
        >>> # 通常 deleted = 6 (= 3 batch × 2 type)，因为 merged 文件已在 format_final_output 清理
        >>> # 若 format_final_output 未运行或异常退出，deleted 最多 = 6 + 2 = 8

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
            path = _result_dir / f"batch_{batch_idx}_{data_type}.json.gz"
            if path.exists():
                try:
                    path.unlink()
                    deleted += 1
                except Exception as e:
                    errors.append(f"{path}: [{type(e).__name__}]: {e}")

    for data_type in _DATA_TYPES:
        merged_path = _result_dir / f"merged_{data_type}.json.gz"
        if merged_path.exists():
            try:
                merged_path.unlink()
                deleted += 1
            except Exception as e:
                errors.append(f"{merged_path}: [{type(e).__name__}]: {e}")

    if errors:
        _logger.warning("  ⚠ 删除失败 %s 个文件: %s", len(errors), errors)
    _logger.info("  ✓ 已删除 %s 个临时文件", deleted)
    return deleted
