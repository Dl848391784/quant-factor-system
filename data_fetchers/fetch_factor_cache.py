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

作者: 云瑶
日期: 2026-04-04
"""

# 标准库导入（PEP 8 规范：按字母顺序分组）
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
    from data_fetchers.data_loader import RealDataLoader
    from data_fetchers.factor_calculator import calculate_forward_return, calculate_rsi, calculate_volume_ratio
except ImportError:
    from data_loader import RealDataLoader
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
RESULT_DIR = get_module_result_dir()
RESULT_DIR.mkdir(parents=True, exist_ok=True)


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

        # data_loader._fetch_stock_batch_parallel 期望 [{'code': str, 'name': str}, ...] 格式
        # 需要将字符串转换为字典格式
        thread_a_stocks = [{"code": s, "name": ""} for s in sub_stocks[: len(sub_stocks) // 2]]
        thread_b_stocks = [{"code": s, "name": ""} for s in sub_stocks[len(sub_stocks) // 2 :]]

        logger.info(f"  [子批次 {sub_idx + 1}/{num_sub_batches}] 拉取 {sub_start + 1}-{sub_end}...")
        logger.info(f"    当前内存: {get_memory_info_str()}")

        sub_results = loader._fetch_stock_batch_parallel(thread_a_stocks, thread_b_stocks, FETCH_DAYS, None)

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
            logger.warning(
                f"  ⚠ 内存超阈值 ({mem_mb:.1f}MB > {MEMORY_THRESHOLD_MB}MB)，暂停 {MEMORY_PAUSE_SECONDS}s..."
            )
            gc.collect()
            time.sleep(MEMORY_PAUSE_SECONDS)

        if sub_idx < num_sub_batches - 1:
            time.sleep(2)

    batch_elapsed = time.time() - batch_start_time
    logger.info(
        f"  ✓ 批次 {batch_idx + 1} 拉取完成: 成功 {success_count}, 失败 {fail_count}, 耗时 {batch_elapsed:.1f}s"
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
    combined = combined.sort_values(["asset", "date"]).copy()  # 避免 CoW 风险

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

    logger.info(f"  因子记录: {len(factor_df)}, 收益记录: {len(return_df)}")

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

    # 初始化默认值
    n_days = 0
    n_assets = 0
    n_records_in_meta = 0
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

                # ========== META 解析阶段 ==========
                # 检测进入 meta
                if '"meta":' in stripped and not in_meta and not in_data:
                    in_meta = True
                    meta_start = stripped.find("{")
                    if meta_start != -1:
                        meta_lines.append(stripped[meta_start:])
                        brace_count = 1
                    continue

                # 收集 meta 内容直到 brace_count == 0
                if in_meta:
                    meta_lines.append(stripped)
                    brace_count += stripped.count("{") - stripped.count("}")
                    if brace_count == 0:
                        # meta 结束，解析并提取信息
                        # 去掉最后一行的尾部逗号（meta 后面有逗号因为还有 data 字段）
                        if meta_lines and meta_lines[-1].endswith(","):
                            meta_lines[-1] = meta_lines[-1].rstrip(",")
                        meta_content = "\n".join(meta_lines)
                        try:
                            meta = json.loads(meta_content)
                            n_days = meta.get("n_days", 0)
                            n_assets = meta.get("n_assets", 0)
                            n_records_in_meta = meta.get("n_records", 0)
                            date_range = meta.get("date_range", {})
                            date_start = date_range.get("start", "") if isinstance(date_range, dict) else ""
                            date_end = date_range.get("end", "") if isinstance(date_range, dict) else ""
                        except json.JSONDecodeError as e:
                            logger.warning(f"  ⚠ meta 解析失败: {e}")
                        # 释放 meta 解析临时内存
                        del meta_lines, meta_content
                        meta_lines = []  # 重置以避免后续引用问题
                        gc.collect()
                        in_meta = False
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
                        try:
                            sample_records.append(json.loads(stripped.rstrip(",")))
                        except json.JSONDecodeError:
                            pass  # 抽样解析失败不影响计数

    except Exception as e:
        logger.warning(f"  ⚠ 文件扫描失败: {e}")
        return False, 0, 0, 0

    logger.info(f"  交易日数: {n_days}")
    logger.info(f"  股票数量: {n_assets}")
    logger.info(f"  总记录数: {records_count}")
    logger.info(f"  日期范围: {date_start} ~ {date_end}")

    # 抽样检查 RSI
    rsi_vals = [r["rsi_6"] for r in sample_records if r.get("rsi_6") is not None]
    if rsi_vals:
        logger.info(f"  RSI(6)样本范围: [{min(rsi_vals):.2f}, {max(rsi_vals):.2f}]")

    # 验证数据有效性
    valid_rsi_count = len(rsi_vals)
    total_sample_count = len(sample_records)
    rsi_valid_ratio = valid_rsi_count / total_sample_count if total_sample_count > 0 else 0.0

    del sample_records
    gc.collect()

    # 综合验证
    days_valid = n_days >= N_DAYS * 0.9
    data_valid = rsi_valid_ratio >= 0.8
    records_valid = (records_count == n_records_in_meta) or (n_records_in_meta == 0)
    is_valid = days_valid and data_valid and records_valid

    if not days_valid:
        logger.warning(f"  ⚠ 交易日数不足 ({n_days}/{N_DAYS})")
    if not data_valid:
        logger.warning(f"  ⚠ 数据有效性不足 (RSI有效比例: {rsi_valid_ratio:.1%} < 80%)")
    if not records_valid and n_records_in_meta > 0:
        logger.warning(f"  ⚠ 记录数不一致 (流式统计: {records_count}, meta声明: {n_records_in_meta})")
    if is_valid:
        logger.info(f"  ✓ 通过验证 (RSI有效比例: {rsi_valid_ratio:.1%}, 记录数一致: {records_count})")

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

    loader = RealDataLoader(use_local=False, retries=3)

    logger.info("[获取股票列表]...")

    # 从 result/stock_list.json 读取股票列表（遵循 MODULE.md 约束 2）
    stock_list_file = get_stock_list_file()
    stock_data = read_json_cache(stock_list_file, logger=logger)

    if stock_data is None:
        logger.warning(f"  ! 股票列表文件不存在: {stock_list_file}")
        return False

    # 提取股票代码列表
    stock_list = stock_data.get("codes", [])

    if not stock_list:
        logger.warning("  ! 股票列表为空")
        return False

    total_stocks = len(stock_list)
    logger.info(f"  ✓ 从缓存获取到 {total_stocks} 只主板股票")

    batches = [stock_list[i : i + BATCH_SIZE] for i in range(0, total_stocks, BATCH_SIZE)]
    total_batches = len(batches)

    logger.info(f"[分批策略] 总批次: {total_batches}")

    successful = 0

    for batch_idx, stock_batch in enumerate(batches):
        mem_mb = get_memory_usage_mb()
        logger.info(f"  当前内存: {get_memory_info_str()}")

        if mem_mb > MEMORY_THRESHOLD_MB:
            logger.warning(
                f"  ⚠ 内存超阈值 ({mem_mb:.1f}MB > {MEMORY_THRESHOLD_MB}MB)，暂停 {MEMORY_PAUSE_SECONDS}s..."
            )
            gc.collect()
            time.sleep(MEMORY_PAUSE_SECONDS)
            mem_mb = get_memory_usage_mb()
            logger.info(f"  GC后内存: {get_memory_info_str()}")

        factor_df, return_df = fetch_batch_stocks(loader, stock_batch, batch_idx, total_batches, logger)

        if factor_df is not None and return_df is not None and len(factor_df) > 0:
            save_batch_cache_sorted(batch_idx, factor_df, return_df, logger_arg=logger)
            successful += 1
            # 显式释放 DataFrame 内存（save_batch_cache_sorted 不负责释放）
            del factor_df, return_df
            gc.collect()
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

        # 验证（提供最终统计信息）
        is_valid, n_days, n_assets, n_records = validate_final_data(logger)

        elapsed = time.time() - global_start

        logger.info("=" * 70)
        logger.info("全部完成!")
        logger.info("=" * 70)
        logger.info(f"  结束时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        logger.info(f"  总耗时: {elapsed:.1f}s ({elapsed / 60:.1f}min)")
        logger.info(f"  数据验证: {'通过' if is_valid else '警告'}")
        logger.info(f"  最终内存: {get_memory_info_str()}")

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
