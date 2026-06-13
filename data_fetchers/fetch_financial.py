#!/usr/bin/env python3
"""
财务指标数据拉取脚本

从 akshare (同花顺) 拉取所有股票的财务摘要数据，缓存为 JSON。
因子计算所需字段：净资产收益率、净利润同比增长率、基本每股收益 等。

数据源: akshare stock_financial_abstract_ths（同花顺财务摘要）
输出路径: data_fetchers/result/financial_data.json.gz（遵循 MODULE.md 约束 #2）

版本历史:
- v1.0 (2026-06-12): 初始版本
  - akshare stock_financial_abstract_ths 数据源（同花顺财务摘要）
  - 增量拉取：仅拉取缓存中缺失的股票
  - 提取关键字段：roe, diluted_roe, net_profit_growth_yoy, basic_eps, revenue_growth_yoy
  - 原子性写入缓存
- v1.0b (2026-06-12): 数据源切换
  - stock_financial_analysis_indicator (东财) → stock_financial_abstract_ths (同花顺)
  - 原因: 东财API返回 AttributeError('NoneType' object has no attribute 'find')
  - 同花顺数据源: 更稳定, 102-121行×22-25列, 含ROE/EPS/净利润增长率

约束合规:
- 输出到 result 目录（MODULE.md 约束 #2）
- 版本号提取为常量（MODULE.md 约束 #16）
- __main__ 使用 setup_logger（MODULE.md 约束）
- 大对象显式 del 释放（MODULE.md 约束 #88→R16）
"""

import datetime
import gc
import json
import logging
import sys
import time
from datetime import datetime as dt_cls
from pathlib import Path
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
_OUTPUT_VERSION = "1.0b"

# 模块级固定时间戳
_NOW = dt_cls.now()

logger = logging.getLogger(__name__)

# 使用公共模块路径函数
RESULT_DIR = get_module_result_dir()
CACHE_FILE = RESULT_DIR / "financial_data.json.gz"

# 同花顺财务摘要关键字段映射
# 中文名 → 英文逻辑名（因子计算函数使用）
_FINANCIAL_FIELD_MAP: dict[str, str] = {
    "净资产收益率": "roe",
    "净资产收益率-摊薄": "diluted_roe",
    "净利润同比增长率": "net_profit_growth_yoy",
    "营业总收入同比增长率": "revenue_growth_yoy",
    "基本每股收益": "basic_eps",
    "每股净资产": "book_value_per_share",
}

# 拉取速率控制
_FETCH_DELAY = 0.3  # 每只股票拉取间隔（秒）
_BATCH_LOG_INTERVAL = 50  # 每拉取50只股票输出一次进度日志

# 年化系数：季度 EPS → 年化 EPS
# Q1: ×4, Q2: ×2, Q3: ×4/3, Q4: ×1
_QUARTER_ANNUALIZE_FACTOR: dict[int, float] = {
    3: 4.0,
    6: 2.0,
    9: 4.0 / 3.0,
    12: 1.0,
}


def _parse_percentage(val: Any) -> float | None:
    """解析百分比字符串（如 '-4.21%' → -4.21）

    Args:
        val: 原始值（可能是百分比字符串、float、或 NaN/False/None）

    Returns:
        解析后的浮点数，无法解析返回 None
    """
    if val is None or val is False:
        return None
    if isinstance(val, float):
        if pd.isna(val):
            return None
        return val
    if isinstance(val, (int,)):
        return float(val)
    if isinstance(val, str):
        # 去掉百分号和空格
        s = val.strip().replace("%", "").replace("％", "")
        if s in ("", "-", "N/A", "nan", "NaN", "--"):
            return None
        try:
            return float(s)
        except ValueError:
            return None
    return None


def _parse_numeric_with_unit(val: Any) -> float | None:
    """解析带单位的数值（如 '426.33亿' → 426330000000.0, '2.0700' → 2.07）

    Args:
        val: 原始值（可能是带亿/万单位的字符串、float、或 NaN/False/None）

    Returns:
        解析后的浮点数（亿→×1e8, 万→×1e4, 无单位→原值），无法解析返回 None
    """
    if val is None or val is False:
        return None
    if isinstance(val, float):
        if pd.isna(val):
            return None
        return val
    if isinstance(val, (int,)):
        return float(val)
    if isinstance(val, str):
        s = val.strip()
        if s in ("", "-", "N/A", "nan", "NaN", "--"):
            return None
        # 处理亿/万单位
        multiplier = 1.0
        if "亿" in s:
            s = s.replace("亿", "")
            multiplier = 1e8
        elif "万" in s:
            s = s.replace("万", "")
            multiplier = 1e4
        s = s.replace("%", "").replace("％", "")
        try:
            return float(s) * multiplier
        except ValueError:
            return None
    return None


def _parse_report_date(report_date_raw: Any) -> str | None:
    """解析报告期日期，兼容 datetime.date 和字符串类型"""
    if report_date_raw is None:
        return None
    if isinstance(report_date_raw, datetime.date):
        return report_date_raw.strftime("%Y-%m-%d")
    if isinstance(report_date_raw, str):
        return report_date_raw
    try:
        return str(report_date_raw)
    except Exception:
        return None


def fetch_financial_data_for_stock(
    symbol: str,
    logger_arg: logging.Logger | None = None,
) -> list[dict[str, Any]]:
    """拉取单只股票的财务摘要数据（同花顺数据源）

    Args:
        symbol: 股票代码（如 '000001'），6位纯数字
        logger_arg: 调用方传入的 logger（可选）

    Returns:
        财务数据记录列表，每项包含 {asset, report_date, roe, eps, ...}
        拉取失败返回空列表
    """
    _logger = logger_arg or logger
    try:
        df = ak.stock_financial_abstract_ths(symbol=symbol)
    except Exception as e:
        _logger.warning("拉取 %s 财务数据失败: %s (%s)", symbol, str(e)[:80], type(e).__name__)
        return []

    if df.empty:
        _logger.debug(" %s 财务数据为空", symbol)
        return []

    records: list[dict[str, Any]] = []
    for _, row in df.iterrows():
        record: dict[str, Any] = {"asset": symbol}
        # 解析报告期日期
        report_date_raw = row.get("报告期", None)
        report_date_str = _parse_report_date(report_date_raw)
        if report_date_str is None:
            continue
        record["report_date"] = report_date_str

        # 提取关键字段（中文名 → 英文逻辑名）
        # 百分比字段: 净利润同比增长率, 营业总收入同比增长率, ROE
        for cn_name, en_name in _FINANCIAL_FIELD_MAP.items():
            if cn_name in ("净利润同比增长率", "营业总收入同比增长率", "净资产收益率", "净资产收益率-摊薄"):
                record[en_name] = _parse_percentage(row.get(cn_name, None))
            elif cn_name in ("基本每股收益",):
                record[en_name] = _parse_numeric_with_unit(row.get(cn_name, None))
            elif cn_name in ("每股净资产",):
                record[en_name] = _parse_numeric_with_unit(row.get(cn_name, None))
            else:
                raw_val = row.get(cn_name, None)
                if pd.isna(raw_val) if isinstance(raw_val, float) else raw_val is None:
                    record[en_name] = None
                else:
                    record[en_name] = float(raw_val)

        # 计算年化 EPS（用于 PE 计算）
        eps = record.get("basic_eps", None)
        if eps is not None and eps != 0:
            month = int(report_date_str.split("-")[1])
            factor = _QUARTER_ANNUALIZE_FACTOR.get(month, 1.0)
            record["annualized_eps"] = eps * factor
        else:
            record["annualized_eps"] = None

        records.append(record)

    return records


def load_cache(logger_arg: logging.Logger | None = None) -> dict[str, Any]:
    """加载已有的财务数据缓存

    Returns:
        缓存数据字典，包含 meta 和 data 键。缓存不存在返回空结构。
    """
    _logger = logger_arg or logger
    if not CACHE_FILE.exists():
        _logger.info("财务数据缓存不存在，将全新拉取")
        return {"meta": {}, "data": []}

    try:
        import gzip

        with gzip.open(CACHE_FILE, "rt") as f:
            data = json.load(f)
        _logger.info("加载财务数据缓存: %d 条记录", len(data.get("data", [])))
        return data
    except Exception as e:
        _logger.warning("加载缓存失败: %s (%s)，将全新拉取", str(e)[:80], type(e).__name__)
        return {"meta": {}, "data": []}


def get_cached_stock_codes(cache_data: dict[str, Any]) -> set[str]:
    """从缓存数据中提取已拉取的股票代码集合"""
    return {r.get("asset", "") for r in cache_data.get("data", []) if r.get("asset")}


def main(logger_arg: logging.Logger | None = None) -> int:
    """主函数：拉取所有股票财务数据并保存缓存

    Returns:
        0=成功, 1=失败
    """
    _logger = logger_arg or logger
    _logger.info("=== 财务数据拉取开始 (v%s) ===", _OUTPUT_VERSION)

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

    for i, code in enumerate(all_codes):
        if code in cached_codes:
            skipped += 1
            continue

        if i > 0 and i % _BATCH_LOG_INTERVAL == 0:
            _logger.info(
                "拉取进度: %d/%d (新增=%d, 失败=%d, 跳过=%d)",
                i, len(all_codes), len(new_records), failed, skipped,
            )

        records = fetch_financial_data_for_stock(code, logger_arg=_logger)
        if records:
            new_records.extend(records)
        else:
            failed += 1

        # 速率控制
        time.sleep(_FETCH_DELAY)

    _logger.info(
        "拉取完成: 新增 %d 条记录, 失败 %d 只股票, 跳过 %d",
        len(new_records), failed, skipped,
    )

    # Step 4: 合并数据
    all_data = cache_data.get("data", []) + new_records

    # Step 5: 构建元数据
    meta: dict[str, Any] = {
        "version": _OUTPUT_VERSION,
        "fetched_at": _NOW.strftime("%Y-%m-%d %H:%M:%S"),
        "stock_count": len(set(r.get("asset", "") for r in all_data)),
        "record_count": len(all_data),
        "fields": list(_FINANCIAL_FIELD_MAP.values()) + ["annualized_eps"],
        "source": "akshare_stock_financial_abstract_ths",
    }

    # Step 6: 写入缓存
    output_data = {"meta": meta, "data": all_data}
    write_gzip_cache(CACHE_FILE, output_data, ensure_dir=True, logger=_logger)

    # 显式释放大对象（遵循 R16）
    del new_records, cache_data, all_data
    gc.collect()

    _logger.info("=== 财务数据拉取完成 ===")
    return 0


if __name__ == "__main__":
    cli_logger = setup_logger("fetch_financial.cli")
    sys.exit(main(logger_arg=cli_logger))