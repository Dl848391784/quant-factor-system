#!/usr/bin/env python3
"""
个股资金流数据拉取脚本

从 akshare (东方财富) 拉取所有股票的个股资金流数据，缓存为 JSON。
因子计算所需字段：主力净流入净额、主力净流入净占比 等。

数据源: akshare stock_individual_fund_flow（东方财富-个股资金流）
输出路径: data_fetchers/result/fund_flow_data.json.gz（遵循 MODULE.md 约束 #2）

版本历史:
- v1.0 (2026-06-12): 初始版本
  - akshare stock_individual_fund_flow 数据源（东方财富个股资金流）
  - 增量拉取：仅拉取缓存中缺失的股票
  - 提取关键字段：main_inflow_amount, main_inflow_ratio, super_large_inflow等
  - 每只股票约120个交易日数据（API限制）
  - 原子性写入缓存

约束合规:
- 输出到 result 目录（MODULE.md 约束 #2）
- 版本号提取为常量（MODULE.md 约束 #16）
- __main__ 使用 setup_logger（MODULE.md 约束）
- 大对象显式 del 释放（MODULE.md 约束 #88→R16）
"""

import gc
import gzip
import json
import logging
import sys
import time
from datetime import datetime as dt_cls
from typing import Any

import akshare as ak
import pandas as pd


# 公共模块导入（遵循 MODULE.md 约束 #4）
try:
    from data_fetchers.common import (
        get_module_result_dir,
        load_main_board_stock_list,
        setup_logger,
        write_gzip_cache,
    )
except ImportError:
    from common import (
        get_module_result_dir,
        load_main_board_stock_list,
        setup_logger,
        write_gzip_cache,
    )

# 版本号常量（MODULE.md 约束 #16）
# v1.1: meta 新增 completed_codes/failed_codes，fetched_at 改为写入时即时戳
_OUTPUT_VERSION = "1.1"

# 注：fetched_at 时间戳在 main() Step 5 构建 meta 时即时调用 dt_cls.now()，
# 不使用模块级常量，避免长时拉取（数小时）时时间戳与实际写入时间偏差过大。

logger = logging.getLogger(__name__)

# 使用公共模块路径函数
RESULT_DIR = get_module_result_dir()
CACHE_FILE = RESULT_DIR / "fund_flow_data.json.gz"

# 拉取速率控制
_FETCH_DELAY = 0.3  # 每只股票拉取间隔（秒）
_BATCH_LOG_INTERVAL = 50  # 每拉取50只股票输出一次进度日志

# 东方财富资金流关键字段映射
# 中文名 → 英文逻辑名（因子计算函数使用）
_FUND_FLOW_FIELD_MAP: dict[str, str] = {
    "主力净流入-净额": "main_inflow_amount",
    "主力净流入-净占比": "main_inflow_ratio",
    "超大单净流入-净额": "super_large_inflow_amount",
    "超大单净流入-净占比": "super_large_inflow_ratio",
    "大单净流入-净额": "large_inflow_amount",
    "大单净流入-净占比": "large_inflow_ratio",
}


def _get_market_prefix(code: str) -> str:
    """根据股票代码判断市场前缀

    Args:
        code: 6位股票代码（如 '000001', '600000'）

    Returns:
        'sz' (深圳) 或 'sh' (上海)
        - 0/3开头 → sz
        - 6开头 → sh
        - 8/4开头 → bj (北交所，本项目不涉及)
    """
    if code.startswith(("0", "3")):
        return "sz"
    elif code.startswith("6"):
        return "sh"
    else:
        return "bj"


def fetch_fund_flow_data_for_stock(
    symbol: str,
    logger_arg: logging.Logger | None = None,
) -> list[dict[str, Any]]:
    """拉取单只股票的资金流数据（东方财富数据源）

    Args:
        symbol: 股票代码（如 '000001'），6位纯数字
        logger_arg: 调用方传入的 logger（可选）

    Returns:
        资金流数据记录列表，每项包含 {asset, date, main_inflow_amount, main_inflow_ratio, ...}
        拉取失败返回空列表
    """
    _logger = logger_arg or logger
    market = _get_market_prefix(symbol)

    try:
        df = ak.stock_individual_fund_flow(stock=symbol, market=market)
    except Exception as e:
        _logger.warning("拉取 %s 资金流数据失败: %s (%s)", symbol, str(e)[:80], type(e).__name__)
        return []

    if df.empty:
        _logger.debug("  %s 资金流数据为空", symbol)
        return []

    records: list[dict[str, Any]] = []
    for _, row in df.iterrows():
        record: dict[str, Any] = {"asset": symbol}

        # 解析日期
        date_raw = row.get("日期", None)
        if date_raw is None:
            continue
        record["date"] = str(date_raw)

        # 提取关键字段（直接映射，数值已是 float64）
        for cn_name, en_name in _FUND_FLOW_FIELD_MAP.items():
            raw_val = row.get(cn_name, None)
            if raw_val is None or (isinstance(raw_val, float) and pd.isna(raw_val)):
                record[en_name] = None
            else:
                record[en_name] = float(raw_val)

        # 成交额（用于 intensity = main_inflow / total_volume）
        # 东方财富接口不直接返回成交额，但可以通过净额反推：
        # main_inflow_ratio = main_inflow_amount / total_volume * 100
        # → total_volume = main_inflow_amount / (main_ratio / 100)
        # 仅当 main_amount > 0 且 main_ratio > 0 时反推有效：
        # - main_amount < 0（净流出）→ 反推得负成交额，无意义
        # - main_ratio == 0 → 不可除
        # - main_ratio < 0 → 反推得负成交额，无意义
        # 统一置为 None 让下游显式处理缺失。
        main_amount = record.get("main_inflow_amount")
        main_ratio = record.get("main_inflow_ratio")
        if main_amount is not None and main_amount > 0 and main_ratio is not None and main_ratio > 0:
            record["total_volume"] = main_amount / (main_ratio / 100.0)
        else:
            record["total_volume"] = None

        records.append(record)

    return records


def load_cache(logger_arg: logging.Logger | None = None) -> dict[str, Any]:
    """加载已有的资金流数据缓存

    Returns:
        缓存数据字典，包含 meta 和 data 键。缓存不存在返回空结构。
    """
    _logger = logger_arg or logger
    if not CACHE_FILE.exists():
        _logger.info("资金流数据缓存不存在，将全新拉取")
        return {"meta": {"completed_codes": []}, "data": []}

    try:
        with gzip.open(CACHE_FILE, "rt") as f:
            data = json.load(f)
        _logger.info("加载资金流数据缓存: %d 条记录", len(data.get("data", [])))
        return data
    except Exception as e:
        _logger.warning("加载缓存失败: %s (%s)，将全新拉取", str(e)[:80], type(e).__name__)
        return {"meta": {"completed_codes": []}, "data": []}


def get_cached_stock_codes(cache_data: dict[str, Any]) -> set[str]:
    """从缓存数据中提取已完整拉取成功的股票代码集合

    优先使用 meta.completed_codes（v1.1+ 写入的"完整拉取成功"白名单），
    避免上次拉取中途失败的股票被永久跳过。

    旧缓存（无 completed_codes）退回从 data 推断，保持向后兼容。
    """
    meta = cache_data.get("meta") or {}
    completed = meta.get("completed_codes")
    if isinstance(completed, list):
        return {str(c) for c in completed if c}
    # 兼容路径：旧缓存仍按 data 推断（首次升级后会自动迁移）
    return {r.get("asset", "") for r in cache_data.get("data", []) if r.get("asset")}


def main(logger_arg: logging.Logger | None = None) -> int:
    """主函数：拉取所有股票资金流数据并保存缓存

    Returns:
        0=成功, 1=失败
    """
    _logger = logger_arg or logger
    _logger.info("=== 资金流数据拉取开始 (v%s) ===", _OUTPUT_VERSION)

    # Step 1: 加载缓存
    cache_data = load_cache(logger_arg=_logger)
    cached_codes = get_cached_stock_codes(cache_data)
    _logger.info("缓存已有 %d 只股票数据", len(cached_codes))

    # Step 2: 加载股票列表
    try:
        stock_list = load_main_board_stock_list(logger=_logger)
    except Exception as e:
        _logger.error("加载股票列表失败: %s", e)
        return 1

    # 提取6位股票代码
    all_codes: list[str] = []
    for stock in stock_list:
        code = str(stock.get("code", "")).zfill(6)
        if len(code) == 6 and code.isdigit():
            all_codes.append(code)

    _logger.info("需拉取 %d 只股票（缓存已有 %d）", len(all_codes), len(cached_codes))

    # Step 3: 增量拉取（仅拉取缓存中缺失的）
    new_records: list[dict[str, Any]] = []
    skipped = 0
    failed = 0
    failed_codes: list[str] = []  # 问题 #6：记录失败的具体股票代码
    new_completed_codes: list[str] = []  # 问题 #1：本轮完整拉取成功的股票代码
    processed = 0  # 问题 #2：独立的"已处理"计数器（不含 skipped）

    for code in all_codes:
        if code in cached_codes:
            skipped += 1
            continue

        processed += 1
        # 进度日志：用 processed 而非全局下标，避免大量跳过时长期不触发
        if processed > 0 and processed % _BATCH_LOG_INTERVAL == 0:
            _logger.info(
                "拉取进度: 已处理=%d (新增=%d, 失败=%d, 跳过=%d, 总计=%d)",
                processed,
                len(new_completed_codes),
                failed,
                skipped,
                len(all_codes),
            )

        records = fetch_fund_flow_data_for_stock(code, logger_arg=_logger)
        if records:
            new_records.extend(records)
            new_completed_codes.append(code)
        else:
            failed += 1
            failed_codes.append(code)

        # 速率控制
        time.sleep(_FETCH_DELAY)

    # 失败股票清单：日志输出前若干个 + meta 全量记录
    if failed_codes:
        preview = ", ".join(failed_codes[:20])
        suffix = " ..." if len(failed_codes) > 20 else ""
        _logger.warning("失败股票 %d 只: %s%s", len(failed_codes), preview, suffix)

    _logger.info(
        "拉取完成: 新增 %d 条记录, 失败 %d 只股票, 跳过 %d",
        len(new_records),
        failed,
        skipped,
    )

    # Step 4: 合并数据
    all_data = cache_data.get("data", []) + new_records

    # 累积"已完整拉取成功"白名单：cached_codes 已由 get_cached_stock_codes 统一处理
    # （优先 meta.completed_codes，旧缓存兼容退回 data 推断），直接复用，不再重复推断
    completed_set = set(cached_codes)
    completed_set.update(new_completed_codes)

    # Step 5: 构建元数据（fetched_at 在此处即时取，避免长时拉取与写入时间偏差过大——问题 #5）
    fetched_at = dt_cls.now().strftime("%Y-%m-%d %H:%M:%S")
    meta: dict[str, Any] = {
        "version": _OUTPUT_VERSION,
        "fetched_at": fetched_at,
        "stock_count": len({r.get("asset", "") for r in all_data}),
        "record_count": len(all_data),
        "fields": list(_FUND_FLOW_FIELD_MAP.values()) + ["total_volume"],
        "source": "akshare_stock_individual_fund_flow",
        "note": "每只股票约120交易日数据（API限制），日期范围约5个月",
        # 问题 #1：完整拉取成功的股票代码白名单（替代"data 中存在即跳过"的脆弱判断）
        "completed_codes": sorted(completed_set),
        # 问题 #6：本轮失败股票代码（下次运行时不在 completed_codes 中会自动重试）
        "failed_codes_last_run": sorted(failed_codes),
    }

    # Step 6: 写入缓存（问题 #8：捕获写入异常，失败时返回 1）
    output_data = {"meta": meta, "data": all_data}
    try:
        write_gzip_cache(CACHE_FILE, output_data, ensure_dir=True, logger=_logger)
    except Exception as e:
        _logger.exception(
            "写入缓存失败: %s (%s)，路径=%s",
            str(e)[:120],
            type(e).__name__,
            CACHE_FILE,
        )
        # 问题 #7 在异常路径也释放：避免错误返回前长时间持有大对象引用
        del new_records, cache_data, all_data, output_data, meta
        gc.collect()
        return 1

    # 问题 #7：写入后同时释放 output_data 与 meta，确保 all_data 引用计数归零
    del new_records, cache_data, all_data, output_data, meta
    gc.collect()

    _logger.info("=== 资金流数据拉取完成 ===")
    return 0


if __name__ == "__main__":
    cli_logger = setup_logger("fetch_fund_flow.cli")
    sys.exit(main(logger_arg=cli_logger))
