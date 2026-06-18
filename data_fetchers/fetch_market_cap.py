#!/usr/bin/env python3
"""
市值/估值面板数据拉取脚本（akshare ak.stock_value_em）

为市值中性化（ln(circ_market_cap) 截面回归残差法）提供数据基础。
本脚本仅做"采集 + 落盘 + 验证"，中性化逻辑在下游模块。

输出路径：data_fetchers/result/market_cap_data.json.gz（遵循 AGENTS.md 规则 #2）
设计文档：designs/feat_market_cap_data_fetcher.md
稳定性：[experimental] 2026-06-18

版本历史:
- v1.0 (2026-06-18): 初始版本（design.md 通过审核后实现）
  - 决策码 A2-B2-C1-D1-E1-F2（详见 design.md §1.3）
  - 12 字段输出（详见 design.md §6.2）
  - 简化批处理（无需 N-way merge，详见 design.md §4.3）
  - 失败率 ≤ 5% 触发退出码 1（详见 design.md §8.3）

输出列：
  date, asset, total_market_cap, circ_market_cap,
  total_shares, circ_shares, pe_ttm, pe_lyr, pb, peg, pcf_ttm, ps_ttm

退出码（遵循 AGENTS.md 规则 #6）:
  0 = 成功
  1 = 运行时错误（采集失败率 > 5% / 验证失败 / 上游 factor_data 缺失）
  2 = 配置或导入错误
"""

from __future__ import annotations

import gzip
import json
import logging
import random
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

import akshare as ak
import pandas as pd


# 路径与日志（双导入兼容：脚本直跑 vs 包导入，遵循 fetch_turnover.py:177-183 模式）
try:
    from data_fetchers.common.logger_config import setup_logger
    from data_fetchers.common.paths import (
        get_factor_data_backup_file,
        get_market_cap_data_file,
        get_module_logs_dir,
        get_module_result_dir,
        get_stock_list_file,
    )
except ImportError:
    from common.logger_config import setup_logger  # type: ignore[no-redef]
    from common.paths import (  # type: ignore[no-redef]
        get_factor_data_backup_file,
        get_market_cap_data_file,
        get_module_logs_dir,
        get_module_result_dir,
        get_stock_list_file,
    )

# ============================================================
# 配置常量（详见 design.md §1.3 + §8.3 + §8.4）
# ============================================================

# 输出 schema 版本（变更字段集时递增）
_OUTPUT_VERSION = "1.0"
_OUTPUT_SOURCE = "akshare_stock_value_em"

# 固定时间戳（避免长时间运行中跨日，与 fetch_turnover.py:150-152 一致）
_NOW = datetime.now()
_NOW_ISO = _NOW.isoformat()

# ST 股票前缀（与 fetch_turnover.py:163 共用同一约定）
ST_PREFIXES: tuple[str, ...] = ("*ST", "ST", "S")

# 批处理配置（决策 F2 / A2 / E1）
BATCH_SIZE = 250
MAX_WORKERS = 4
MAX_RETRIES = 3

# 节流配置（design.md §8.4）
REQUEST_INTERVAL = 0.1  # 单股成功后 sleep（秒）
RETRY_BACKOFF_BASE = 1.0  # 重试退避基数（秒）

# 失败率阈值（design.md §8.3）
TOTAL_FAIL_RATE_THRESHOLD = 0.05  # 总体失败率上限
MIN_STOCK_COVERAGE = 0.95  # V5: 股票覆盖率下限
MIN_KEY_FIELD_NON_NULL_RATE = 0.99  # V6: circ_market_cap 非空率下限

# 字段映射（design.md §6.2 + §6.4）
_FIELD_MAPPING: dict[str, str] = {
    "数据日期": "date",
    "总市值": "total_market_cap",
    "流通市值": "circ_market_cap",
    "总股本": "total_shares",
    "流通股本": "circ_shares",
    "PE(TTM)": "pe_ttm",
    "PE(静)": "pe_lyr",
    "市净率": "pb",
    "PEG值": "peg",
    "市现率": "pcf_ttm",
    "市销率": "ps_ttm",
}
_DROPPED_FIELDS: tuple[str, ...] = ("当日收盘价", "当日涨跌幅")
_OUTPUT_COLUMNS: tuple[str, ...] = (
    "date",
    "asset",
    "total_market_cap",
    "circ_market_cap",
    "total_shares",
    "circ_shares",
    "pe_ttm",
    "pe_lyr",
    "pb",
    "peg",
    "pcf_ttm",
    "ps_ttm",
)

_FIELD_UNITS: dict[str, str] = {
    "total_market_cap": "yuan",
    "circ_market_cap": "yuan",
    "total_shares": "share",
    "circ_shares": "share",
    "pe_ttm": "ratio",
    "pe_lyr": "ratio",
    "pb": "ratio",
    "peg": "ratio",
    "pcf_ttm": "ratio",
    "ps_ttm": "ratio",
}

# 公开 API（遵循 MODULE.md __all__ 约定）
__all__ = [
    "load_target_assets",
    "fetch_one_stock",
    "fetch_batch",
    "save_batch_cache",
    "merge_and_emit_final",
    "validate_final_data",
    "main",
]

# ============================================================
# 输出路径（遵循 AGENTS.md 规则 #2）
# ============================================================
RESULT_DIR = get_module_result_dir()
OUTPUT_FILE = get_market_cap_data_file()
STOCK_LIST_FILE = get_stock_list_file()
FACTOR_DATA_FILE = get_factor_data_backup_file()

# ============================================================
# 日志配置（遵循 AGENTS.md 规则 #9）
# ============================================================
_SCRIPT_NAME = Path(__file__).stem
_LOGS_DIR = get_module_logs_dir()


def _get_logger() -> logging.Logger:
    """获取日志记录器（复用公共模块 setup_logger）"""
    return setup_logger(_SCRIPT_NAME, logs_dir=_LOGS_DIR)


# 模块级 logger（写入 data_fetchers/logs/）
logger = _get_logger()


# ============================================================
# 函数 stub（C2b/C2c/C2d 中陆续实现）
# ============================================================


def load_target_assets(
    stock_list_file: Path | None = None,
    logger_arg: logging.Logger | None = None,
) -> list[str]:
    """加载目标股票代码列表（详见 design.md §3.2 F2）。

    读取 stock_list.json 的 ``codes`` 字段，过滤 ST 前缀（``*ST/ST/S``）。

    Args:
        stock_list_file: stock_list.json 路径，None 时使用 STOCK_LIST_FILE。
        logger_arg: 日志记录器，None 时使用模块级 logger。

    Returns:
        股票代码列表（6 位字符串），按原序保留。

    Raises:
        FileNotFoundError: stock_list.json 不存在。
        KeyError: ``codes`` 字段缺失（结构异常）。
    """
    log = logger_arg if logger_arg is not None else logger
    target_file = stock_list_file if stock_list_file is not None else STOCK_LIST_FILE

    if not target_file.exists():
        raise FileNotFoundError(f"stock_list 文件不存在: {target_file}（请先运行 fetch_factor_cache.py）")

    with target_file.open("r", encoding="utf-8") as f:
        payload = json.load(f)

    if "codes" not in payload:
        raise KeyError(f"stock_list.json 缺少 'codes' 字段，实际键: {sorted(payload.keys())}")

    raw_codes = payload["codes"]
    if not isinstance(raw_codes, list):
        raise TypeError(f"stock_list.json 'codes' 字段应为 list，实际为 {type(raw_codes).__name__}")

    # 过滤 ST 股票（基于 stocks 字段中的 name 前缀，遵循 fetch_turnover.py:163 约定）
    stocks_meta = {item["code"]: item.get("name", "") for item in payload.get("stocks", [])}
    filtered: list[str] = []
    skipped_st = 0
    for code in raw_codes:
        name = stocks_meta.get(code, "")
        if any(name.startswith(prefix) for prefix in ST_PREFIXES):
            skipped_st += 1
            continue
        filtered.append(code)

    log.info(
        "加载股票列表完成: 总数=%d, 过滤ST=%d, 目标=%d",
        len(raw_codes),
        skipped_st,
        len(filtered),
    )
    return filtered


def _normalize_fields(df_raw: pd.DataFrame, symbol: str) -> pd.DataFrame:
    """归一化 ak.stock_value_em 返回结果（详见 design.md §6.4）。

    将 13 列中文字段映射为 11 列英文字段，并附加 ``asset`` 列。
    丢弃 ``当日收盘价 / 当日涨跌幅``（与因子用途无关，详见 design.md §6.3）。

    Args:
        df_raw: ``ak.stock_value_em`` 返回的原始 DataFrame（13 列）。
        symbol: 6 位股票代码（用于填充 asset 列）。

    Returns:
        12 列 DataFrame：``date, asset, total_market_cap, ..., ps_ttm``。

    Raises:
        ValueError: 必要字段（数据日期/总市值/流通市值）缺失。
    """
    if df_raw is None or df_raw.empty:
        # 空 DataFrame 返回 12 列空结构（避免下游 concat 报错）
        return pd.DataFrame(columns=list(_OUTPUT_COLUMNS))

    # 必要字段检查
    required_zh = ["数据日期", "总市值", "流通市值"]
    missing = [c for c in required_zh if c not in df_raw.columns]
    if missing:
        raise ValueError(f"symbol={symbol} 缺少必要字段 {missing}，实际列: {list(df_raw.columns)}")

    # 中→英重命名（字典 in-place 不修改原 df）
    df = df_raw.rename(columns=_FIELD_MAPPING).copy()

    # 丢弃冗余字段（design.md §6.3 决策）
    df = df.drop(columns=[c for c in _DROPPED_FIELDS if c in df.columns])

    # 日期归一化为 ISO 字符串（YYYY-MM-DD）
    df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")

    # 附加 asset 列
    df["asset"] = symbol

    # 列顺序对齐 _OUTPUT_COLUMNS；缺列补 NaN（防御 akshare 偶发字段缺失）
    for col in _OUTPUT_COLUMNS:
        if col not in df.columns:
            df[col] = pd.NA

    return df[list(_OUTPUT_COLUMNS)].reset_index(drop=True)


def _clip_to_target_range(df: pd.DataFrame, target_date_range: tuple[str, str]) -> pd.DataFrame:
    """裁剪到目标区间（详见 design.md §4.2 Stage 4→5）。

    保留 ``start <= date <= end`` 的行。空 DataFrame 直接返回。

    Args:
        df: 已归一化的 12 列 DataFrame（含 ``date`` 列，ISO 字符串）。
        target_date_range: ``(start_iso, end_iso)``，闭区间。

    Returns:
        裁剪后的 DataFrame，索引重置。
    """
    if df is None or df.empty:
        return df if df is not None else pd.DataFrame(columns=list(_OUTPUT_COLUMNS))

    start, end = target_date_range
    if start > end:
        raise ValueError(f"target_date_range 起止逆序: start={start} > end={end}")

    mask = (df["date"] >= start) & (df["date"] <= end)
    return df.loc[mask].reset_index(drop=True)


def fetch_one_stock(
    symbol: str,
    target_date_range: tuple[str, str],
    max_retries: int = MAX_RETRIES,
    logger_arg: logging.Logger | None = None,
) -> pd.DataFrame | None:
    """单股市值数据拉取（详见 design.md §3.2 F3 / §5.3）。

    流程:
        1. 调用 ``ak.stock_value_em(symbol=...)`` 获取 13 列原始 DataFrame
        2. ``_normalize_fields`` → 12 列英文
        3. ``_clip_to_target_range`` 裁剪到目标区间
        4. 失败时指数退避重试（默认 3 次）

    Args:
        symbol: 6 位股票代码。
        target_date_range: ``(start_iso, end_iso)`` 闭区间。
        max_retries: 最大重试次数（含首次调用，遵循 design.md §8.4）。
        logger_arg: 日志记录器。

    Returns:
        归一化 + 裁剪后的 12 列 DataFrame；所有重试均失败时返回 None。
    """
    log = logger_arg if logger_arg is not None else logger

    last_exc: Exception | None = None
    for attempt in range(max_retries):
        try:
            df_raw = ak.stock_value_em(symbol=symbol)
            df_norm = _normalize_fields(df_raw, symbol=symbol)
            df_clipped = _clip_to_target_range(df_norm, target_date_range)
            if attempt > 0:
                log.info("symbol=%s 重试成功（第 %d 次尝试）", symbol, attempt + 1)
            time.sleep(REQUEST_INTERVAL)
            return df_clipped
        except ValueError:
            # 数据契约错误（缺列 / 区间逆序）— 重试无意义，直接上抛（design.md §8.2 / U-F3-6）
            raise
        except Exception as exc:  # noqa: BLE001 — 网络/解析异常种类多样，统一捕获 + 重试
            last_exc = exc
            if attempt < max_retries - 1:
                # 指数退避 + 抖动（design.md §8.4）
                delay = RETRY_BACKOFF_BASE * (2**attempt)
                jitter = random.uniform(0, 0.1 * delay)
                log.warning(
                    "symbol=%s 第 %d 次失败: %s，%.2fs 后重试",
                    symbol,
                    attempt + 1,
                    exc,
                    delay + jitter,
                )
                time.sleep(delay + jitter)
            else:
                log.error(
                    "symbol=%s 重试 %d 次后仍失败，跳过: %s",
                    symbol,
                    max_retries,
                    exc,
                )

    # 全部重试耗尽（决策 E1：skip + warning，不抛异常）
    if last_exc is not None:
        log.warning("symbol=%s 最终放弃（%s）", symbol, type(last_exc).__name__)
    return None


def fetch_batch(
    symbols: list[str],
    batch_idx: int,
    total_batches: int,
    target_date_range: tuple[str, str],
    max_workers: int = MAX_WORKERS,
    logger_arg: logging.Logger | None = None,
) -> tuple[pd.DataFrame | None, int, int]:
    """批量拉取一组股票（详见 design.md §3.2 F4 / §5.2）。

    使用 ``ThreadPoolExecutor`` 并发调用 ``fetch_one_stock``，按 symbol 收集结果。
    单批失败率超过 50% 视为批次失败（返回 None），由调用方决定是否中止。

    Args:
        symbols: 本批 symbol 列表（≤ BATCH_SIZE）。
        batch_idx: 批次索引（1-based，用于日志）。
        total_batches: 总批次数。
        target_date_range: 目标日期区间。
        max_workers: 并发线程数（决策 F2）。
        logger_arg: 日志记录器。

    Returns:
        ``(df_or_None, success_count, fail_count)``：
            - 成功结果合并后的 DataFrame（任一行返回非空即合入）；
            - 单批失败率 > 50% 时 df 设为 None（触发批次中止信号）。
    """
    log = logger_arg if logger_arg is not None else logger
    n = len(symbols)
    if n == 0:
        return pd.DataFrame(columns=list(_OUTPUT_COLUMNS)), 0, 0

    log.info(
        "批次 %d/%d 开始: %d 只股票（max_workers=%d）",
        batch_idx,
        total_batches,
        n,
        max_workers,
    )

    success_dfs: list[pd.DataFrame] = []
    success_cnt = 0
    fail_cnt = 0

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_symbol = {
            executor.submit(fetch_one_stock, sym, target_date_range, MAX_RETRIES, log): sym for sym in symbols
        }
        for future in as_completed(future_to_symbol):
            sym = future_to_symbol[future]
            try:
                df = future.result()
            except Exception as exc:  # noqa: BLE001
                log.error("symbol=%s future 异常: %s", sym, exc)
                fail_cnt += 1
                continue

            if df is None or df.empty:
                fail_cnt += 1
            else:
                success_dfs.append(df)
                success_cnt += 1

    fail_rate = fail_cnt / n if n > 0 else 0.0
    log.info(
        "批次 %d/%d 完成: 成功=%d, 失败=%d, 失败率=%.2f%%",
        batch_idx,
        total_batches,
        success_cnt,
        fail_cnt,
        fail_rate * 100,
    )

    # 单批失败率 > 50% 触发批次失败信号（design.md §8.3）
    if fail_rate > 0.5:
        log.error(
            "批次 %d 失败率 %.2f%% > 50%%，标记批次失败",
            batch_idx,
            fail_rate * 100,
        )
        return None, success_cnt, fail_cnt

    if not success_dfs:
        return pd.DataFrame(columns=list(_OUTPUT_COLUMNS)), success_cnt, fail_cnt

    merged = pd.concat(success_dfs, ignore_index=True)
    return merged, success_cnt, fail_cnt


def _read_factor_data_date_range(
    factor_data_file: Path | None = None,
    logger_arg: logging.Logger | None = None,
) -> tuple[str, str]:
    """读取 factor_data.json.gz 的 ``meta.date_range`` 作为目标日期区间。

    Args:
        factor_data_file: factor_data.json.gz 路径，None 时使用 FACTOR_DATA_FILE。
        logger_arg: 日志记录器。

    Returns:
        ``(start_iso, end_iso)``，闭区间。

    Raises:
        FileNotFoundError: factor_data.json.gz 不存在（上游未跑 fetch_factor_cache）。
        KeyError: meta.date_range 字段缺失。
    """
    log = logger_arg if logger_arg is not None else logger
    target = factor_data_file if factor_data_file is not None else FACTOR_DATA_FILE

    if not target.exists():
        raise FileNotFoundError(f"factor_data 文件不存在: {target}（请先运行 fetch_factor_cache.py）")

    with gzip.open(target, "rt", encoding="utf-8") as f:
        payload = json.load(f)

    meta = payload.get("meta", {})
    date_range = meta.get("date_range")
    if not date_range or "start" not in date_range or "end" not in date_range:
        raise KeyError(f"factor_data.json.gz meta.date_range 字段缺失或不完整，实际: {date_range}")

    start, end = date_range["start"], date_range["end"]
    log.info("从 factor_data 读取目标区间: [%s, %s]", start, end)
    return start, end


def save_batch_cache(
    batch_idx: int,
    df: pd.DataFrame,
    result_dir: Path | None = None,
    logger_arg: logging.Logger | None = None,
) -> Path:
    """落盘单批次缓存（详见 design.md §3.1 F5）。

    用 tempfile + Path.replace 实现原子写（避免半文件污染下游合并阶段，
    模板见 fetch_turnover.py:798-806）。

    Args:
        batch_idx: 批次索引（1-based），用作文件名 ``market_cap_batch_<idx>.json.gz``。
        df: 12 列归一化后 DataFrame；若空则不落盘，返回空路径。
        result_dir: 输出目录，None 时使用 RESULT_DIR。
        logger_arg: 日志记录器。

    Returns:
        缓存文件路径；df 为空时返回 ``Path('')``。
    """
    log = logger_arg if logger_arg is not None else logger
    target_dir = result_dir if result_dir is not None else RESULT_DIR
    target_dir.mkdir(parents=True, exist_ok=True)

    if df is None or df.empty:
        log.warning("批次 %d 为空，跳过落盘", batch_idx)
        return Path("")

    cache_file = target_dir / f"market_cap_batch_{batch_idx:04d}.json.gz"

    payload = {
        "batch_idx": batch_idx,
        "n_rows": len(df),
        "n_assets": int(df["asset"].nunique()),
        "data": df.to_dict(orient="records"),
    }

    # 原子写（tempfile + Path.replace，遵循 AGENTS.md 规则 #2）
    with tempfile.NamedTemporaryFile(suffix=".json.gz", dir=target_dir, delete=False) as temp_f:
        temp_path = Path(temp_f.name)
        with gzip.open(temp_f, "wt", encoding="utf-8") as gz_f:
            json.dump(payload, gz_f, ensure_ascii=False)

    temp_path.replace(cache_file)
    log.info(
        "批次 %d 缓存落盘: %s (rows=%d, assets=%d)",
        batch_idx,
        cache_file.name,
        len(df),
        payload["n_assets"],
    )
    return cache_file


def merge_and_emit_final(
    total_batches: int,
    target_date_range: tuple[str, str],
    total_success: int,
    total_fail: int,
    elapsed_seconds: float,
    result_dir: Path | None = None,
    logger_arg: logging.Logger | None = None,
) -> int:
    """合并所有批次并写最终输出（详见 design.md §3.1 F6 / §4.3）。

    流程:
        1. glob ``market_cap_batch_*.json.gz`` → 读取所有 data 行
        2. concat → 按 (date, asset) 去重（保留第一条）
        3. 计算 meta（n_days / n_assets / n_records / coverage_rate）
        4. 原子写 ``market_cap_data.json.gz``
        5. 清理临时批次缓存

    Args:
        total_batches: 总批次数（用于日志）。
        target_date_range: 目标日期区间 ``(start, end)``。
        total_success / total_fail: 单股成功/失败计数。
        elapsed_seconds: 全流程耗时（秒）。
        result_dir: 输出目录，None 时使用 RESULT_DIR。
        logger_arg: 日志记录器。

    Returns:
        合并后总记录数（行数）；若无任何批次缓存返回 0。
    """
    log = logger_arg if logger_arg is not None else logger
    target_dir = result_dir if result_dir is not None else RESULT_DIR

    batch_files = sorted(target_dir.glob("market_cap_batch_*.json.gz"))
    if not batch_files:
        log.error("未找到任何批次缓存文件，无法合并")
        return 0

    log.info("开始合并 %d 个批次缓存", len(batch_files))

    all_records: list[dict] = []
    for bf in batch_files:
        with gzip.open(bf, "rt", encoding="utf-8") as f:
            payload = json.load(f)
        all_records.extend(payload.get("data", []))

    if not all_records:
        log.error("所有批次缓存均为空数据")
        return 0

    df = pd.DataFrame(all_records)
    raw_count = len(df)

    # 去重 (date, asset)：保留第一条
    df = df.drop_duplicates(subset=["date", "asset"], keep="first").reset_index(drop=True)
    dedup_count = len(df)
    if raw_count > dedup_count:
        log.warning("去重 %d → %d 行（去掉 %d 重复）", raw_count, dedup_count, raw_count - dedup_count)

    # 列顺序对齐
    df = df[list(_OUTPUT_COLUMNS)]

    # ----------------- meta 计算 -----------------
    n_records = len(df)
    n_assets = int(df["asset"].nunique())
    n_days = int(df["date"].nunique())
    actual_start = str(df["date"].min())
    actual_end = str(df["date"].max())

    # 关键字段非空率（V6: circ_market_cap）
    circ_non_null = float(df["circ_market_cap"].notna().mean()) if n_records else 0.0

    meta = {
        "version": _OUTPUT_VERSION,
        "source": _OUTPUT_SOURCE,
        "generated_at": _NOW_ISO,
        "n_days": n_days,
        "n_assets": n_assets,
        "n_records": n_records,
        "date_range": {
            "start": actual_start,
            "end": actual_end,
            "target_start": target_date_range[0],
            "target_end": target_date_range[1],
        },
        "fetch_stats": {
            "total_success": total_success,
            "total_fail": total_fail,
            "fail_rate": round(total_fail / (total_success + total_fail), 4)
            if (total_success + total_fail) > 0
            else 0.0,
            "elapsed_seconds": round(elapsed_seconds, 2),
            "total_batches": total_batches,
        },
        "field_units": _FIELD_UNITS,
        "circ_market_cap_non_null_rate": round(circ_non_null, 4),
    }

    payload = {
        "meta": meta,
        "data": df.to_dict(orient="records"),
    }

    # 原子写最终文件
    target_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(suffix=".json.gz", dir=target_dir, delete=False) as temp_f:
        temp_path = Path(temp_f.name)
        with gzip.open(temp_f, "wt", encoding="utf-8") as gz_f:
            json.dump(payload, gz_f, ensure_ascii=False)
    temp_path.replace(OUTPUT_FILE)

    log.info(
        "最终输出落盘: %s (n_records=%d, n_days=%d, n_assets=%d, circ_non_null=%.2f%%)",
        OUTPUT_FILE.name,
        n_records,
        n_days,
        n_assets,
        circ_non_null * 100,
    )

    # 清理批次缓存
    for bf in batch_files:
        try:
            bf.unlink()
        except OSError as exc:
            log.warning("清理批次缓存失败 %s: %s", bf.name, exc)
    log.info("已清理 %d 个批次缓存文件", len(batch_files))

    return n_records


def validate_final_data(
    output_file: Path | None = None,
    logger_arg: logging.Logger | None = None,
) -> tuple[bool, int, int, int]:
    """验证最终输出（详见 design.md §3.1 F9 / §10）。

    校验项:
        - V1 文件存在且可读
        - V2 必备 keys: meta + data
        - V3 12 列字段齐全（_OUTPUT_COLUMNS）
        - V4 (date, asset) 唯一
        - V5 股票覆盖率 >= 95%（按 stock_list 计）
        - V6 circ_market_cap 非空率 >= 99%
        - V7 数值字段类型与单位（仅做范围/类型 sanity check）

    Args:
        output_file: 待校验文件，None 时使用 OUTPUT_FILE。
        logger_arg: 日志记录器。

    Returns:
        ``(ok, n_records, n_assets, n_days)``：
            - ok: 是否通过全部校验；
            - 后三项为最终数据集统计（便于上游打日志）。
    """
    log = logger_arg if logger_arg is not None else logger
    target = output_file if output_file is not None else OUTPUT_FILE

    # V1 文件存在
    if not target.exists():
        log.error("[V1] 输出文件不存在: %s", target)
        return False, 0, 0, 0

    try:
        with gzip.open(target, "rt", encoding="utf-8") as f:
            payload = json.load(f)
    except Exception as exc:
        log.error("[V1] 文件读取/解析失败: %s", exc)
        return False, 0, 0, 0

    # V2 顶层 keys
    if "meta" not in payload or "data" not in payload:
        log.error("[V2] 缺少 meta/data 字段，实际: %s", sorted(payload.keys()))
        return False, 0, 0, 0

    data = payload["data"]
    meta = payload["meta"]
    n_records = len(data)
    if n_records == 0:
        log.error("[V2] data 为空")
        return False, 0, 0, 0

    df = pd.DataFrame(data)

    # V3 字段齐全
    missing_cols = [c for c in _OUTPUT_COLUMNS if c not in df.columns]
    if missing_cols:
        log.error("[V3] 缺少字段: %s", missing_cols)
        return False, n_records, 0, 0

    n_assets = int(df["asset"].nunique())
    n_days = int(df["date"].nunique())

    # V4 (date, asset) 唯一
    dup_count = int(df.duplicated(subset=["date", "asset"]).sum())
    if dup_count > 0:
        log.error("[V4] 存在 %d 行 (date, asset) 重复", dup_count)
        return False, n_records, n_assets, n_days

    # V5 股票覆盖率（容忍未运行 fetch_factor_cache 的场景：跳过 V5 但日志提示）
    try:
        target_codes = load_target_assets(logger_arg=log)
        coverage = n_assets / len(target_codes) if target_codes else 0.0
        if coverage < MIN_STOCK_COVERAGE:
            log.error(
                "[V5] 股票覆盖率 %.2f%% < 阈值 %.2f%%",
                coverage * 100,
                MIN_STOCK_COVERAGE * 100,
            )
            return False, n_records, n_assets, n_days
        log.info("[V5] 股票覆盖率: %.2f%% (%d / %d)", coverage * 100, n_assets, len(target_codes))
    except FileNotFoundError:
        log.warning("[V5] stock_list.json 不存在，跳过覆盖率校验")

    # V6 circ_market_cap 非空率
    circ_non_null = float(df["circ_market_cap"].notna().mean())
    if circ_non_null < MIN_KEY_FIELD_NON_NULL_RATE:
        log.error(
            "[V6] circ_market_cap 非空率 %.2f%% < 阈值 %.2f%%",
            circ_non_null * 100,
            MIN_KEY_FIELD_NON_NULL_RATE * 100,
        )
        return False, n_records, n_assets, n_days

    # V7 数值字段 sanity check：市值应为正
    numeric_cols = ["total_market_cap", "circ_market_cap", "total_shares", "circ_shares"]
    for col in numeric_cols:
        if col not in df.columns:
            continue
        # 允许 NaN，仅检查非 NaN 值
        non_null = df[col].dropna()
        if len(non_null) > 0 and (non_null <= 0).any():
            n_bad = int((non_null <= 0).sum())
            log.error("[V7] 字段 %s 出现 <= 0 值 %d 次（应为正）", col, n_bad)
            return False, n_records, n_assets, n_days

    # meta 一致性（report_only，不影响通过）
    meta_n_records = meta.get("n_records")
    if meta_n_records != n_records:
        log.warning(
            "meta.n_records=%s 与实际 data 行数 %d 不一致（已修正使用实际值）",
            meta_n_records,
            n_records,
        )

    log.info(
        "[OK] 验证通过: n_records=%d, n_assets=%d, n_days=%d, circ_non_null=%.2f%%",
        n_records,
        n_assets,
        n_days,
        circ_non_null * 100,
    )
    return True, n_records, n_assets, n_days


def main(
    target_date_range: tuple[str, str] | None = None,
    logger_arg: logging.Logger | None = None,
) -> int:
    """顶层编排（详见 design.md §3.1 F1 / §5.1）。

    流程:
        1. 读取目标区间（None 时从 factor_data.json.gz meta.date_range 推断）
        2. 加载目标股票（load_target_assets，过滤 ST）
        3. 切批：BATCH_SIZE=250 切片
        4. 每批 fetch_batch → save_batch_cache
        5. 全部完成后 merge_and_emit_final
        6. validate_final_data 校验
        7. 总失败率 > 5% 或 V1-V7 失败 → 返回 1

    Args:
        target_date_range: ``(start, end)`` 闭区间；None 时自动推断。
        logger_arg: 日志记录器。

    Returns:
        退出码（遵循 AGENTS.md 规则 #6）：
            0 = 成功
            1 = 运行时错误（失败率/校验失败/上游缺失）
            2 = 配置或导入错误（已被外层 try/except 捕获）
    """
    log = logger_arg if logger_arg is not None else logger
    log.info("=" * 70)
    log.info("fetch_market_cap.py v%s 启动", _OUTPUT_VERSION)
    log.info("=" * 70)

    start_time = time.time()

    # 1. 推断目标区间
    try:
        if target_date_range is None:
            target_date_range = _read_factor_data_date_range(logger_arg=log)
        log.info("目标日期区间: [%s, %s]", target_date_range[0], target_date_range[1])
    except (FileNotFoundError, KeyError) as exc:
        log.error("读取目标日期区间失败: %s", exc)
        return 1

    # 2. 加载目标股票
    try:
        symbols = load_target_assets(logger_arg=log)
    except (FileNotFoundError, KeyError, TypeError) as exc:
        log.error("加载股票列表失败: %s", exc)
        return 1

    if not symbols:
        log.error("目标股票列表为空")
        return 1

    # 3. 切批
    n = len(symbols)
    batches = [symbols[i : i + BATCH_SIZE] for i in range(0, n, BATCH_SIZE)]
    total_batches = len(batches)
    log.info(
        "共 %d 只股票，切分为 %d 批（BATCH_SIZE=%d，max_workers=%d）",
        n,
        total_batches,
        BATCH_SIZE,
        MAX_WORKERS,
    )

    # 4. 逐批拉取 + 落盘
    total_success = 0
    total_fail = 0
    failed_batches = 0
    for idx, batch_symbols in enumerate(batches, start=1):
        df, succ, fail = fetch_batch(
            batch_symbols,
            batch_idx=idx,
            total_batches=total_batches,
            target_date_range=target_date_range,
            max_workers=MAX_WORKERS,
            logger_arg=log,
        )
        total_success += succ
        total_fail += fail

        if df is None:
            failed_batches += 1
            log.error("批次 %d 失败率超 50%%，已记录但继续后续批次", idx)
            continue

        if df.empty:
            log.warning("批次 %d 无成功记录，跳过落盘", idx)
            continue

        save_batch_cache(idx, df, logger_arg=log)

    elapsed = time.time() - start_time
    log.info(
        "全部批次完成: 总耗时=%.2fs, 成功=%d, 失败=%d, 失败批次=%d",
        elapsed,
        total_success,
        total_fail,
        failed_batches,
    )

    # 5. 合并 + 落盘
    n_records = merge_and_emit_final(
        total_batches=total_batches,
        target_date_range=target_date_range,
        total_success=total_success,
        total_fail=total_fail,
        elapsed_seconds=elapsed,
        logger_arg=log,
    )
    if n_records == 0:
        log.error("合并阶段无任何记录，终止")
        return 1

    # 6. 校验
    ok, n_rec, n_assets, n_days = validate_final_data(logger_arg=log)
    if not ok:
        log.error("最终数据校验失败")
        return 1

    # 7. 总失败率检查（单点决策：所有批次完成后整体阈值 5%）
    total_attempts = total_success + total_fail
    overall_fail_rate = total_fail / total_attempts if total_attempts > 0 else 0.0
    if overall_fail_rate > TOTAL_FAIL_RATE_THRESHOLD:
        log.error(
            "总失败率 %.2f%% > 阈值 %.2f%%，标记为运行时错误",
            overall_fail_rate * 100,
            TOTAL_FAIL_RATE_THRESHOLD * 100,
        )
        return 1

    log.info("=" * 70)
    log.info(
        "✓ 全部完成: n_records=%d, n_assets=%d, n_days=%d, 总失败率=%.2f%%, 耗时=%.2fs",
        n_rec,
        n_assets,
        n_days,
        overall_fail_rate * 100,
        elapsed,
    )
    log.info("=" * 70)
    return 0


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="抓取 A 股日频市值数据 → market_cap_data.json.gz",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--start",
        default=None,
        help="起始日期 (YYYY-MM-DD)；不传则从 factor_data.json.gz 读取",
    )
    parser.add_argument(
        "--end",
        default=None,
        help="结束日期 (YYYY-MM-DD)；不传则从 factor_data.json.gz 读取",
    )
    args = parser.parse_args()

    cli_range: tuple[str, str] | None = None
    if args.start and args.end:
        cli_range = (args.start, args.end)
    elif args.start or args.end:
        parser.error("--start 与 --end 必须同时提供")

    sys.exit(main(target_date_range=cli_range))
