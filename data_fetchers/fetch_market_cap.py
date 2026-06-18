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

import json
import logging
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd


# 路径与日志（双导入兼容：脚本直跑 vs 包导入，遵循 fetch_turnover.py:177-183 模式）
try:
    from data_fetchers.common.logger_config import setup_logger
    from data_fetchers.common.paths import (
        get_market_cap_data_file,
        get_module_logs_dir,
        get_module_result_dir,
        get_stock_list_file,
    )
except ImportError:
    from common.logger_config import setup_logger  # type: ignore[no-redef]
    from common.paths import (  # type: ignore[no-redef]
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
FACTOR_DATA_FILE = RESULT_DIR / "factor_data.json.gz"

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
    """单股市值数据拉取（详见 design.md §3.2 F3 / §5.3）。"""
    raise NotImplementedError("C2c 实现")


def fetch_batch(
    symbols: list[str],
    batch_idx: int,
    total_batches: int,
    target_date_range: tuple[str, str],
    max_workers: int = MAX_WORKERS,
    logger_arg: logging.Logger | None = None,
) -> tuple[pd.DataFrame | None, int, int]:
    """批量拉取一组股票（详见 design.md §3.2 F4 / §5.2）。"""
    raise NotImplementedError("C2c 实现")


def save_batch_cache(
    batch_idx: int,
    df: pd.DataFrame,
    result_dir: Path | None = None,
    logger_arg: logging.Logger | None = None,
) -> Path:
    """落盘单批次缓存（详见 design.md §3.1 F5）。"""
    raise NotImplementedError("C2d 实现")


def merge_and_emit_final(
    total_batches: int,
    target_date_range: tuple[str, str],
    total_success: int,
    total_fail: int,
    elapsed_seconds: float,
    result_dir: Path | None = None,
    logger_arg: logging.Logger | None = None,
) -> int:
    """合并所有批次并写最终输出（详见 design.md §3.1 F6 / §4.3）。"""
    raise NotImplementedError("C2d 实现")


def validate_final_data(
    output_file: Path | None = None,
    logger_arg: logging.Logger | None = None,
) -> tuple[bool, int, int, int]:
    """验证最终输出（详见 design.md §3.1 F9）。"""
    raise NotImplementedError("C2d 实现")


def main(
    target_date_range: tuple[str, str] | None = None,
    logger_arg: logging.Logger | None = None,
) -> int:
    """顶层编排（详见 design.md §3.1 F1 / §5.1）。"""
    raise NotImplementedError("C2d 实现")


if __name__ == "__main__":
    sys.exit(main())
