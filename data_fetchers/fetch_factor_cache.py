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
- v4.0 (2026-05-27): 重构 - 删除内联代码，复用 batch_processor.py 模块
  - 导入 BatchStream, save_batch_cache_sorted, n_way_merge_deduplicate, format_final_output, cleanup_batch_files
  - 导入 get_memory_usage_mb, get_memory_info_str 从 common.memory_utils
  - 仅保留独有逻辑: fetch_batch_stocks, validate_final_data, main

修复编号索引（issue #N 在代码注释中引用，编号全局唯一不重复，跨版本可追溯）:
  v1.1 (2026-06-15): #1~#8（meta 解析两阶段、cumcount 排序、mkdir 副作用、total_batches 初值、
                              内存暂停 continue、子批次日志降级、del 后清理对称）
  v1.2 (2026-06-15): #1（meta 解析重写为状态机收敛点）、#2（meta 归零块对称释放）、
                     #3（format_final_output 后输出文件存在性兜底）、#9（末批 sleep 条件化，
                     原标 #4 与 v1.1 mkdir 冲突，统一改 #9）、#5（successful==0 快速失败）
  v1.3 (2026-06-15): #1（meta 阶段 B 守卫块注释完善）、#2（末批 sleep 注释加版本前缀）、
                     #3（validate_final_data 入口前置文件存在性检查）、
                     #10（内存超阈值 warning 加 [子批次 N/M] 编号，原标 #4 与 v1.1 mkdir 冲突，统一改 #10）
  v1.4 (2026-06-15): #11（issue #4 编号冲突彻底消除：v1.2 末批 sleep 改 #9、v1.3 内存超阈值 warning 改 #10、
                          建立本索引）、
                     #12（meta 阶段 A brace_count<0 异常分支拦截，避免状态机锁死）、
                     #13（n_records_in_meta 初值改 None，区分"meta 字段缺失"与"meta 解析失败"）
  v1.5 (2026-06-15): #14（缺失输出文件错误日志改打印路径+状态而非布尔值）、
                     #15（meta 归零块 fall-through 取代 continue，处理 meta+data 同行紧凑格式）、
                     #16（fetch_batch_stocks combined 排序加 kind="mergesort"，与 valid_df 一致）、
                     #17（内存超阈值暂停后二次检测，仍超限跳过当前批次防 OOM）、
                     #18（validate_final_data 增加 MIN_SAMPLE_COUNT=100 最小样本量下限）

作者: 云瑶
日期: 2026-04-04
"""

# 标准库导入（PEP 8 规范：按字母顺序分组）
import contextlib
import gc
import gzip
import json
import logging
import time
from datetime import datetime

# 第三方库导入
import pandas as pd


# 本地模块导入
try:
    from data_fetchers.data_loader import MIN_VALID_ROWS, RealDataLoader
    from data_fetchers.factor_calculator import calculate_forward_return, calculate_rsi, calculate_volume_ratio
except ImportError:
    from data_loader import MIN_VALID_ROWS, RealDataLoader
    from factor_calculator import calculate_forward_return, calculate_rsi, calculate_volume_ratio

# 公共模块导入（条件导入：脚本直接运行时可能路径未配置）
# 使用前提：project_root 已加入 PYTHONPATH 或以项目根目录为工作目录执行
try:
    from data_fetchers.batch_processor import (
        cleanup_batch_files,
        format_final_output,
        n_way_merge_deduplicate,
        save_batch_cache_sorted,
    )
    from data_fetchers.common import (
        get_logs_dir,
        get_module_result_dir,
        get_stock_list_file,
        read_json_cache,
        setup_logger,
    )
    from data_fetchers.common.memory_utils import get_memory_info_str, get_memory_usage_mb
except ImportError:
    from batch_processor import (
        cleanup_batch_files,
        format_final_output,
        n_way_merge_deduplicate,
        save_batch_cache_sorted,
    )
    from common import get_logs_dir, get_module_result_dir, get_stock_list_file, read_json_cache, setup_logger
    from common.memory_utils import get_memory_info_str, get_memory_usage_mb

# 模块级常量（PEP 8：import 之后定义）
# _MODULE_LOGGER: 模块级日志记录器，当脚本直接运行时可能未初始化
# _OUTPUT_VERSION: 输出文件版本号，与模块版本一致
_MODULE_LOGGER = logging.getLogger("fetch_factor_cache")
_OUTPUT_VERSION = "4.0"

# ============================================================================
# 配置常量（遵循 MODULE.md 约束 #2：输出到 result 目录）
# ============================================================================
N_DAYS = 500  # 目标交易日数
BATCH_SIZE = 250  # 每批股票数量（从400降低到250，减少单批峰值）
FETCH_DAYS = int(N_DAYS * 1.5) + 30  # 实际拉取天数
MEMORY_THRESHOLD_MB = 900  # 内存警告阈值（MB）- 缓存加载后约700MB
MEMORY_PAUSE_SECONDS = 15  # 内存超阈值时的暂停时间

# 输出路径（遵循 MODULE.md 约束 #2：输出到 result 目录）
# 使用公共模块路径函数，避免硬编码路径（遵循 MODULE.md 约束 62）
# 修复 issue #4: 仅在 import 阶段计算路径，不在模块顶层执行 mkdir，
#   避免被其他模块 import 时产生意外的目录创建副作用；
#   mkdir 已下沉到 main() 首次使用 RESULT_DIR 之前调用。
RESULT_DIR = get_module_result_dir()


def fetch_batch_stocks(
    loader: RealDataLoader,
    stock_batch: list[str],
    batch_idx: int,
    total_batches: int,
    logger: logging.Logger | None = None,
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
    logger.info("[批次 %s/%s] 开始拉取...", batch_idx + 1, total_batches)
    logger.info("  股票数量: %s", len(stock_batch))
    logger.info("  当前内存: %s", get_memory_info_str())
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

        # data_loader._fetch_stock_batch_parallel 期望 [{'code': str, 'name': str}, ...] 格式
        # 内部已封装二等分线程分配，调用方只需传入完整列表
        sub_stocks_dicts = [{"code": s, "name": ""} for s in sub_stocks]

        logger.debug("  [子批次 %s/%s] 拉取 %s-%s...", sub_idx + 1, num_sub_batches, sub_start + 1, sub_end)
        logger.debug("    当前内存: %s", get_memory_info_str())

        sub_results = loader._fetch_stock_batch_parallel(sub_stocks_dicts, FETCH_DAYS, None)

        for code, df in sub_results:
            if df is not None and len(df) >= MIN_VALID_ROWS:
                all_data_dict[code] = df
                success_count += 1
            else:
                fail_count += 1

        # 每个子批次后强制垃圾回收
        gc.collect()

        # 内存监控：超过阈值时暂停
        # 修复 issue #6: 暂停后 continue 跳过本次固定 sleep(2)，避免双重等待累积
        # 修复 issue #10（v1.3）: warning 日志补充子批次编号，使内存压力下进度仍可追踪
        #   注：原 v1.3 注释引用 issue #4 与 v1.1 mkdir 副作用修复编号冲突，
        #   v1.4 issue #11 统一改 issue #10，编号索引见文件头 docstring。
        mem_mb = get_memory_usage_mb()
        if mem_mb > MEMORY_THRESHOLD_MB:
            logger.warning(
                "  ⚠ [子批次 %s/%s] 内存超阈值 (%.1fMB > %sMB)，暂停 %ss...",
                sub_idx + 1,
                num_sub_batches,
                mem_mb,
                MEMORY_THRESHOLD_MB,
                MEMORY_PAUSE_SECONDS,
            )
            gc.collect()
            time.sleep(MEMORY_PAUSE_SECONDS)
            continue

        if sub_idx < num_sub_batches - 1:
            time.sleep(2)

    batch_elapsed = time.time() - batch_start_time
    logger.info(
        "  ✓ 批次 %s 拉取完成: 成功 %s, 失败 %s, 耗时 %.1fs",
        batch_idx + 1,
        success_count,
        fail_count,
        batch_elapsed,
    )

    if not all_data_dict:
        logger.warning("  ! 无有效数据")
        return None, None

    logger.info("  正在计算因子...")

    all_data = list(all_data_dict.values())
    combined = pd.concat(all_data, ignore_index=True)

    del all_data, all_data_dict
    gc.collect()

    combined["date"] = pd.to_datetime(combined["date"])
    # 修复 issue #16（v1.5）: 显式 kind="mergesort" 保证稳定排序。
    #   原 sort_values 默认 quicksort 在相同 (asset, date) 多行时顺序不确定，
    #   后续 cumcount(ascending=False) 截取 N_DAYS 行的结果在不同运行间不一致。
    #   与下方 valid_df.sort_values(..., kind="mergesort") 保持一致。
    combined = combined.sort_values(["asset", "date"], kind="mergesort").copy()  # 避免 CoW 风险

    combined["rsi_6"] = combined.groupby("asset")["close"].transform(lambda x: calculate_rsi(x, period=6))

    combined["volume_ratio_5"] = combined.groupby("asset")["volume"].transform(
        lambda x: calculate_volume_ratio(x, window=5)
    )
    # 不填充 NaN，保留窗口期不足和数据异常的真实情况
    # 下游 valid_df.dropna(subset=['rsi_6', 'volume_ratio_5']) 会自然过滤
    combined["volume_ratio_5"] = combined["volume_ratio_5"].clip(0.1, 10)

    combined["forward_return_1d"] = combined.groupby("asset")["close"].transform(
        lambda x: calculate_forward_return(x, shift=1)
    )
    combined["forward_return_3d"] = combined.groupby("asset")["close"].transform(
        lambda x: calculate_forward_return(x, shift=3)
    )
    combined["forward_return_5d"] = combined.groupby("asset")["close"].transform(
        lambda x: calculate_forward_return(x, shift=5)
    )

    valid_df = combined.dropna(subset=["rsi_6", "volume_ratio_5"]).copy()

    del combined
    gc.collect()

    # pandas 3.0 兼容性修复：使用 cumcount 替代 groupby().apply(tail)
    # 避免 group_keys=False 导致分组列被移除
    # 修复 issue #3: cumcount 前显式按 ["asset", "date"] 升序，
    #   保证 cumcount(ascending=False) 与日期降序严格对应，避免乱序插入导致截取不稳定
    valid_df = valid_df.sort_values(["asset", "date"], kind="mergesort").reset_index(drop=True)
    valid_df["row_num"] = valid_df.groupby("asset").cumcount(ascending=False)
    valid_df = valid_df[valid_df["row_num"] < N_DAYS].copy().drop("row_num", axis=1)

    # 去重：保证单批次内没有重复 (date, asset) key
    # 从根源消除 N-way merge 时 stream 内重复问题
    valid_df = valid_df.drop_duplicates(subset=["date", "asset"], keep="first")

    valid_df["date"] = valid_df["date"].dt.strftime("%Y-%m-%d")
    valid_df["open"] = valid_df["open"].round(2)
    valid_df["close"] = valid_df["close"].round(2)
    valid_df["high"] = valid_df["high"].round(2)
    valid_df["low"] = valid_df["low"].round(2)
    valid_df["rsi_6"] = valid_df["rsi_6"].round(2)
    valid_df["volume_ratio_5"] = valid_df["volume_ratio_5"].round(2)
    valid_df["forward_return_1d"] = valid_df["forward_return_1d"].round(6)
    valid_df["forward_return_3d"] = valid_df["forward_return_3d"].round(6)
    valid_df["forward_return_5d"] = valid_df["forward_return_5d"].round(6)

    # 包含 open/high/low 用于选股回测计算一字涨停、封死涨停等
    # 包含 volume 用于尾盘量比计算（尾盘量价强度因子需要）
    factor_df = valid_df[["date", "asset", "open", "close", "high", "low", "rsi_6", "volume_ratio_5", "volume"]].copy()

    # return_df: 排除 forward_return 为 NaN 的记录（每只股票末尾几天的 shift 产生）
    # 避免下游读取方未处理产生计算错误
    return_df = valid_df[["date", "asset", "forward_return_1d", "forward_return_3d", "forward_return_5d"]].copy()
    return_df = return_df.dropna(subset=["forward_return_1d"])

    del valid_df
    gc.collect()

    logger.info("  因子记录: %s, 收益记录: %s", len(factor_df), len(return_df))

    return factor_df, return_df


def validate_final_data(logger: logging.Logger | None = None) -> tuple[bool, int, int, int]:
    """
    验证最终数据文件的完整性

    Args:
        logger: 日志记录器

    Returns:
        tuple[bool, int, int, int]: (是否通过验证, 交易日数, 股票数量, 记录数)

    Note:
        单次流式扫描，同时提取 meta 信息和抽样 data：
        - 避免两次 IO 的性能损耗和竞态窗口
        - 使用状态机解析 JSON 结构（meta/data 分段）
        - 抽样检查 RSI 字段有效性
    """
    logger = logger or _MODULE_LOGGER
    logger.info("=" * 60)
    logger.info("[验证阶段] 验证数据完整性...")
    logger.info("=" * 60)

    factor_path = RESULT_DIR / "factor_data.json.gz"

    # 修复 issue #3（v1.3）: 前置文件存在性检查。
    #   gzip.open 在文件不存在时抛 FileNotFoundError，会被外层 except 兜底为
    #   "⚠ 文件扫描失败"的 warning，但缺少路径信息且严重程度偏低。
    #   验证文件根本不存在属于"严重错误"而非"扫描中途 IO 失败"，应用 logger.error
    #   打印含完整路径的明确信息，与 IO 读取失败两类错误区分处理。
    if not factor_path.exists():
        logger.error("  ✗ 验证失败：最终输出文件不存在 path=%s", factor_path)
        return False, 0, 0, 0

    # 初始化默认值
    # 修复 issue #13（v1.4）: n_records_in_meta 初值改 None，区分两种语义不同的场景：
    #   (a) meta 中确实未提供 n_records 字段（合理豁免，None）；
    #   (b) meta 解析失败导致变量保持初始值（应当告警，None 触发明确警告分支）。
    #   原初值 0 与"meta 未提供该字段"语义重叠（旧 records_valid = ... or n_records_in_meta == 0），
    #   meta 解析失败时会静默通过记录数校验。改为 None 后 records_valid 走
    #   `n_records_in_meta is None or records_count == n_records_in_meta`，同时下方
    #   `not records_valid and n_records_in_meta > 0` 判断也无需改动（None 不触发该分支）。
    n_days = 0
    n_assets = 0
    n_records_in_meta: int | None = None
    date_start = ""
    date_end = ""
    records_count = 0

    # 抽样参数
    sample_records = []
    sample_size = 1000
    step = 100

    # 解析状态
    in_meta = False
    in_data = False
    meta_lines = []
    brace_count = 0

    try:
        with gzip.open(factor_path, "rt", encoding="utf-8") as f:
            for line in f:
                stripped = line.strip()

                # ========== META 解析阶段（两阶段状态机）==========
                # 修复 issue #1: 重写为清晰的两阶段单分支结构，消除原 if/elif/独立-if 三段并存的歧义控制流。
                #   阶段 A: 检测到 '"meta":' 时进入 in_meta，截取子串并计算初始 brace_count；
                #           若立即归零（单行完整 meta）则同步解析重置；否则 continue 等下一行。
                #   阶段 B: in_meta 状态下后续行统一累计 brace_count，归零时解析重置。
                #   两条路径都收敛到同一段"解析+重置"逻辑，单行/多行对称且 fall-through 无歧义。
                # 修复 issue #2: 同步在重置块内 del meta_lines 并重新赋空列表，与 sample_records
                #   的 del 释放原则一致；移除"list 占用可忽略"的不准确注释。

                # 阶段 A: 进入 meta
                if not in_meta and not in_data and '"meta":' in stripped:
                    meta_start = stripped.find("{")
                    if meta_start == -1:
                        # 没有 { 起始（异常情况）：跳过本行，等下一行可能的 {
                        continue
                    sub = stripped[meta_start:]
                    meta_lines.append(sub)
                    brace_count = sub.count("{") - sub.count("}")
                    in_meta = True
                    # 修复 issue #12（v1.4）: brace_count < 0 异常分支拦截
                    #   场景：当前行截取子串中 } 多于 {（如格式异常的 JSON 片段或截断输入）。
                    #   原代码仅判断 > 0 与隐含的 == 0，负数会 fall-through 到阶段 B，
                    #   后续每行被 elif in_meta 捕获并继续累计负数 brace_count，永远无法归零，
                    #   整个文件剩余内容被当 meta 消费而跳过 DATA 阶段，records_count=0，
                    #   验证返回 False 但日志没有任何针对"brace_count 为负"的警告（静默失败）。
                    #   修复：检测到负数立即 logger.warning 并重置状态机，确保后续 DATA 阶段仍可推进。
                    if brace_count < 0:
                        logger.warning(
                            "  ⚠ meta 起始行 brace_count<0 (=%s)，输入格式异常，重置状态机跳过本行",
                            brace_count,
                        )
                        in_meta = False
                        meta_lines = []
                        brace_count = 0
                        continue
                    if brace_count > 0:
                        # 多行 meta：等后续行累计
                        continue
                    # brace_count == 0：单行完整 meta，fall-through 到下方阶段 B 的归零块统一处理
                # 阶段 B: 已在 meta 内，累计后续行
                elif in_meta:
                    meta_lines.append(stripped)
                    brace_count += stripped.count("{") - stripped.count("}")

                # 归零处理（阶段 A 单行 meta 与阶段 B 多行 meta 共用收敛点）
                if in_meta and brace_count == 0:
                    # meta 结束，解析并提取信息
                    # 去掉最后一行的尾部逗号（meta 后面有逗号因为还有 data 字段）
                    if meta_lines and meta_lines[-1].endswith(","):
                        meta_lines[-1] = meta_lines[-1].rstrip(",")
                    meta_content = "\n".join(meta_lines)
                    try:
                        meta = json.loads(meta_content)
                        n_days = meta.get("n_days", 0)
                        n_assets = meta.get("n_assets", 0)
                        # 修复 issue #13（v1.4）: 直接 .get(key) 不传默认值，meta 中无字段时返回 None，
                        #   与下方 records_valid 判断 `n_records_in_meta is None` 语义一致。
                        n_records_in_meta = meta.get("n_records")
                        date_range = meta.get("date_range", {})
                        date_start = date_range.get("start", "") if isinstance(date_range, dict) else ""
                        date_end = date_range.get("end", "") if isinstance(date_range, dict) else ""
                    except json.JSONDecodeError as e:
                        logger.warning("  ⚠ meta 解析失败: %s", e)
                        # 修复 issue #13（v1.4）: meta 解析失败时显式保持 n_records_in_meta = None，
                        #   使下游 records_valid 判断不会因初值 0 静默通过记录数校验。
                        n_records_in_meta = None
                    # 释放 meta 解析临时内存（与 sample_records 的 del 释放原则保持一致）
                    del meta_content
                    del meta_lines
                    meta_lines = []
                    gc.collect()
                    in_meta = False
                    # 修复 issue #15（v1.5）: 归零块末尾不再 continue，改为 fall-through。
                    #   原 continue 跳过本行剩余处理，但若归零行尾部还包含 `"data": [`
                    #   子串（合法 JSON 中 meta 与 data 同行的紧凑格式），DATA 阶段进入
                    #   检测会被跳过，状态机永远停留 in_meta=False / in_data=False 初始态，
                    #   后续所有 data 记录被当普通行忽略。fall-through 后由下方守卫块
                    #   `if in_meta: continue` 自动豁免（此处 in_meta 已设 False，不拦截），
                    #   控制流自然进入 DATA 进入检测 `if '"data": [' in stripped`。
                if in_meta:
                    # 修复 issue #1（v1.3）: 守卫块**必要**，非冗余。
                    #   阶段 B 累计行（elif in_meta）若 brace_count > 0 未归零，
                    #   缺少此 continue 会 fall-through 到下方 DATA 解析阶段的
                    #   `if '"data": [' in stripped` 检测——若 meta 内某字段值或
                    #   嵌套结构中合法包含字符串 `"data": [`（例如 fields 字段值
                    #   含此子串），会误触发 in_data=True 污染状态机。
                    #   本块拦截所有"in_meta=True 且本行未归零"的多行累计路径，
                    #   保证 meta/data 阶段严格隔离。
                    continue

                # ========== DATA 解析阶段 ==========
                # 检测进入 data 数组
                if '"data": [' in stripped and not in_data:
                    in_data = True
                    continue

                # 检测离开 data 数组
                if in_data and stripped in ("]", "],"):
                    break

                # 流式解析 data 记录
                if in_data and stripped.startswith("{"):
                    records_count += 1
                    # 抽样：基于 records_count（已修复问题4：无论解析是否成功都计入）
                    if records_count % step == 0 and len(sample_records) < sample_size:
                        with contextlib.suppress(json.JSONDecodeError):
                            sample_records.append(json.loads(stripped.rstrip(",")))  # noqa: SIM105

    except Exception as e:
        # 修复 issue #3（v1.3）: 区分文件不存在（前置已拦截）与 IO/解析失败两类错误。
        #   到达此处说明文件存在但读取/解析中途异常，仍用 warning 级别并附带路径与异常类型。
        logger.warning("  ⚠ 文件扫描失败: path=%s, [%s]: %s", factor_path, type(e).__name__, e)
        return False, 0, 0, 0

    logger.info("  交易日数: %s", n_days)
    logger.info("  股票数量: %s", n_assets)
    logger.info("  总记录数: %s", records_count)
    logger.info("  日期范围: %s ~ %s", date_start, date_end)

    # 抽样检查 RSI
    rsi_vals = [r["rsi_6"] for r in sample_records if r.get("rsi_6") is not None]
    if rsi_vals:
        logger.info("  RSI(6)样本范围: [%.2f, %.2f]", min(rsi_vals), max(rsi_vals))

    # 验证数据有效性
    valid_rsi_count = len(rsi_vals)
    total_sample_count = len(sample_records)
    rsi_valid_ratio = valid_rsi_count / total_sample_count if total_sample_count > 0 else 0.0

    del sample_records
    gc.collect()

    # 综合验证
    # 修复 issue #13（v1.4）: records_valid 改为 `is None` 判断，区分"meta 字段缺失/解析失败"
    #   （n_records_in_meta is None，豁免一致性校验）与"meta 声明记录数与流式统计不一致"
    #   （n_records_in_meta 为整数且与 records_count 不等，触发 warning）。
    # 修复 issue #18（v1.5）: 增加最小有效样本量检查。
    #   原 data_valid = rsi_valid_ratio >= 0.8 在 total_sample_count 远小于 1000 时
    #   仍以同一比例阈值判定，小样本下 80% 的统计意义不足（如 5 条样本中 4 条有效=80%
    #   即过线）。增加 MIN_SAMPLE_COUNT=100 下限：低于下限强制 data_valid=False 并
    #   记录 warning，避免小数据集误判通过。
    MIN_SAMPLE_COUNT = 100  # 最小有效样本量下限（统计上 80% 比例需 ≥100 样本支撑）
    days_valid = n_days >= N_DAYS * 0.9
    sample_size_sufficient = total_sample_count >= MIN_SAMPLE_COUNT
    data_valid = sample_size_sufficient and rsi_valid_ratio >= 0.8
    records_valid = n_records_in_meta is None or records_count == n_records_in_meta
    is_valid = days_valid and data_valid and records_valid

    if not days_valid:
        logger.warning("  ⚠ 交易日数不足 (%s/%s)", n_days, N_DAYS)
    if not sample_size_sufficient:
        logger.warning(
            "  ⚠ 抽样样本量不足 (%s < %s)，统计意义不足，data_valid 强制置 False",
            total_sample_count,
            MIN_SAMPLE_COUNT,
        )
    elif not data_valid:
        logger.warning("  ⚠ 数据有效性不足 (RSI有效比例: %.1f%% < 80%%)", rsi_valid_ratio * 100)
    if not records_valid and n_records_in_meta is not None and n_records_in_meta > 0:
        logger.warning("  ⚠ 记录数不一致 (流式统计: %s, meta声明: %s)", records_count, n_records_in_meta)
    if is_valid:
        logger.info("  ✓ 通过验证 (RSI有效比例: %.1f%%, 记录数一致: %s)", rsi_valid_ratio * 100, records_count)

    return is_valid, n_days, n_assets, records_count


def main() -> bool:
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
    logger = setup_logger("fetch_factor_cache", logs_dir=log_dir)

    # 修复 issue #4: 在首次使用 RESULT_DIR 之前确保目录存在（替代被移除的模块级 mkdir）
    RESULT_DIR.mkdir(parents=True, exist_ok=True)

    # 修复 issue #5: 顶部初始化 total_batches，避免 finally 块在 batches 计算前抛异常时
    #   触发 UnboundLocalError；cleanup_batch_files 在 total_batches == 0 时无文件可清理。
    total_batches = 0

    logger.info("=" * 70)
    logger.info("分批拉取 %s 天因子数据 (外部排序版本)", N_DAYS)
    logger.info("=" * 70)
    logger.info("  版本: %s", _OUTPUT_VERSION)
    logger.info("  目标交易日数: %s", N_DAYS)
    logger.info("  每批股票数量: %s", BATCH_SIZE)
    logger.info("  内存阈值: %s MB", MEMORY_THRESHOLD_MB)
    logger.info("  开始时间: %s", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    logger.info("  初始内存: %s", get_memory_info_str())

    global_start = time.time()

    loader = RealDataLoader(use_local=False, retries=3)

    logger.info("[获取股票列表]...")

    # 从 result/stock_list.json 读取股票列表（遵循 MODULE.md 约束 2）
    stock_list_file = get_stock_list_file()
    stock_data = read_json_cache(stock_list_file, logger=logger)

    if stock_data is None:
        logger.warning("  ! 股票列表文件不存在: %s", stock_list_file)
        return False

    # 提取股票代码列表
    stock_list = stock_data.get("codes", [])

    if not stock_list:
        logger.warning("  ! 股票列表为空")
        return False

    total_stocks = len(stock_list)
    logger.info("  ✓ 从缓存获取到 %s 只主板股票", total_stocks)

    batches = [stock_list[i : i + BATCH_SIZE] for i in range(0, total_stocks, BATCH_SIZE)]
    total_batches = len(batches)

    logger.info("[分批策略] 总批次: %s", total_batches)

    successful = 0

    for batch_idx, stock_batch in enumerate(batches):
        mem_mb = get_memory_usage_mb()
        logger.info("  当前内存: %s", get_memory_info_str())

        if mem_mb > MEMORY_THRESHOLD_MB:
            logger.warning(
                "  ⚠ 内存超阈值 (%.1fMB > %sMB)，暂停 %ss...",
                mem_mb,
                MEMORY_THRESHOLD_MB,
                MEMORY_PAUSE_SECONDS,
            )
            gc.collect()
            time.sleep(MEMORY_PAUSE_SECONDS)
            mem_mb = get_memory_usage_mb()
            logger.info("  GC后内存: %s", get_memory_info_str())
            # 修复 issue #17（v1.5）: 暂停后二次阈值检测，防止持续超限累积无上限等待。
            #   原代码暂停 15s 后无条件继续，若进程驻留内存高于阈值（如全局缓存膨胀、
            #   外部依赖泄漏），每批次都会触发 15s 暂停 + 5s 批次间 sleep，
            #   N 个批次共计 (15+5)*N 秒空转。二次检测：仍超限则记录 logger.error 并
            #   跳过当前批次（continue），不进入 fetch_batch_stocks，避免 OOM 风险叠加。
            if mem_mb > MEMORY_THRESHOLD_MB:
                logger.error(
                    "  ✗ GC 后内存仍超阈值 (%.1fMB > %sMB)，跳过批次 %s/%s 防止 OOM",
                    mem_mb,
                    MEMORY_THRESHOLD_MB,
                    batch_idx + 1,
                    total_batches,
                )
                continue

        factor_df, return_df = fetch_batch_stocks(loader, stock_batch, batch_idx, total_batches, logger)

        if factor_df is not None and return_df is not None and len(factor_df) > 0:
            save_batch_cache_sorted(batch_idx, factor_df, return_df, logger_arg=logger)
            successful += 1
            # 显式释放 DataFrame 内存（save_batch_cache_sorted 不负责释放）
            del factor_df, return_df
            gc.collect()
        else:
            logger.warning("  ⚠ 批次 %s 失败", batch_idx + 1)
            if factor_df is not None:
                del factor_df
            if return_df is not None:
                del return_df

        # 批次间强制垃圾回收
        gc.collect()
        logger.info("  批次完成后内存: %s", get_memory_info_str())
        # 修复 issue #9（v1.2）: 末批跳过 sleep，避免无意义等待；
        #   与子批次循环 `if sub_idx < num_sub_batches - 1: time.sleep(2)` 处理一致。
        #   注：原 v1.2 注释引用 issue #4 与 v1.1 mkdir 副作用修复编号冲突，
        #   v1.4 issue #11 统一改 issue #9，编号索引见文件头 docstring。
        if batch_idx < total_batches - 1:
            time.sleep(5)  # 批次间休息时间增加

    logger.info("=" * 70)
    logger.info("拉取完成: 成功 %s/%s 批次", successful, total_batches)
    logger.info("=" * 70)

    # 修复 issue #5: 无任何批次成功时立即快速失败，避免无意义进入 N-way merge
    if successful == 0:
        logger.error("  ✗ 无任何批次成功（successful=0/%s），中止合并阶段", total_batches)
        return False

    # N-way merge 合并
    logger.info("[合并阶段] N-way merge 外部排序...")

    try:
        factor_merged_path = n_way_merge_deduplicate(total_batches, "factor", logger_arg=logger)
        return_merged_path = n_way_merge_deduplicate(total_batches, "return", logger_arg=logger)

        # 校验两个合并路径
        if not factor_merged_path or not return_merged_path:
            logger.warning("  ! 无有效数据（factor 或 return 合并失败）")
            return False

        # 格式化最终输出（传入版本号）
        format_final_output(
            factor_merged_path,
            return_merged_path,
            result_dir=RESULT_DIR,
            output_version=_OUTPUT_VERSION,
            logger_arg=logger,
        )

        # 修复 issue #3: format_final_output 当前签名返回 None（失败靠 raise 传递），
        #   但仍需对最终输出文件做存在性兜底校验——若内部异常被吞、I/O 错误未覆盖、
        #   或上游契约变更导致静默失败，validate_final_data 会对旧文件/不完整文件返回
        #   误判 is_valid=True。提前返回避免误报。
        factor_final_path = RESULT_DIR / "factor_data.json.gz"
        return_final_path = RESULT_DIR / "return_data.json.gz"
        # 修复 issue #14（v1.5）: 缺失文件错误日志改打印路径与状态而非布尔值。
        #   原日志 `factor=%s` 传 `factor_final_path.exists()`（bool），导致显示
        #   `factor=True/False` 无法定位具体缺失路径。改为按路径+状态字符串打印，
        #   便于定位（运维场景常见：路径前缀错配、磁盘只读、上游契约变更）。
        factor_exists = factor_final_path.exists()
        return_exists = return_final_path.exists()
        if not factor_exists or not return_exists:
            logger.error(
                "  ✗ 格式化最终输出失败：缺少输出文件 factor=%s [%s], return=%s [%s]",
                factor_final_path,
                "存在" if factor_exists else "缺失",
                return_final_path,
                "存在" if return_exists else "缺失",
            )
            return False

        # 验证（提供最终统计信息）
        is_valid, n_days, n_assets, n_records = validate_final_data(logger)

        elapsed = time.time() - global_start

        logger.info("=" * 70)
        logger.info("全部完成!")
        logger.info("=" * 70)
        logger.info("  结束时间: %s", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        logger.info("  总耗时: %.1fs (%.1fmin)", elapsed, elapsed / 60)
        logger.info("  数据验证: %s", "通过" if is_valid else "警告")
        logger.info("  最终内存: %s", get_memory_info_str())

        # 保存统计
        stats = {
            "version": _OUTPUT_VERSION,
            "n_days": n_days,
            "n_assets": n_assets,
            "n_records": n_records,
            "elapsed_seconds": elapsed,
            "is_valid": is_valid,
            "memory_monitor": "proc_self_status",
            "fields": ["date", "asset", "open", "close", "high", "low", "rsi_6", "volume_ratio_5", "volume"],
        }

        with open(RESULT_DIR / "regenerate_stats.json", "w") as f:
            json.dump(stats, f, indent=2)

        # 返回成功状态（遵循 PROJECT.md 编码规范：脚本必须有退出码）
        logger.info("执行完成，退出码: 0")
        return True

    except Exception as e:
        logger.exception("执行失败: %s", e)
        logger.info("执行失败，退出码: 1")
        return False

    finally:
        # 清理临时批次文件（无论成功或失败都清理）
        cleanup_batch_files(total_batches, result_dir=RESULT_DIR, logger_arg=logger)


if __name__ == "__main__":
    import sys

    success = main()
    sys.exit(0 if success else 1)
