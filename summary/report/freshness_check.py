"""数据新鲜度检查。

从 generate_factor_summary_report.py 迁移（v3.8 拆分重构）。
检查各数据源是否更新至 T-1，生成报告第零部分。
"""

import gzip
import json
import logging
from datetime import datetime, timedelta

import pandas as pd
from summary.report.constants import (
    DATA_CHECK_SOURCES,
    DATA_FRESHNESS_HEAD_CHARS,
    DATA_PATHS,
    PROJECT_ROOT,
)


def get_expected_t_minus_1(date: str) -> str:
    """获取期望的 T-1 日期（前一天）

    注意：这是简单的前一天计算，不考虑交易日历。
    如果 T-1 是非交易日（如周末），数据文件可能不会更新，
    检查结果会显示异常，但这是预期行为。

    Args:
        date: 当前日期字符串（YYYY-MM-DD）

    Returns:
        T-1 日期字符串
    """
    current_date = datetime.strptime(date, "%Y-%m-%d")
    t_minus_1 = current_date - timedelta(days=1)
    return t_minus_1.strftime("%Y-%m-%d")


def get_expected_t_minus_2(date: str) -> str:
    """获取期望的 T-2 日期（前两天）

    IC 分析结果需要次日收益数据，因此最新可计算日期是 T-2。

    Args:
        date: 当前日期字符串（YYYY-MM-DD）

    Returns:
        T-2 日期字符串
    """
    current_date = datetime.strptime(date, "%Y-%m-%d")
    t_minus_2 = current_date - timedelta(days=2)
    return t_minus_2.strftime("%Y-%m-%d")


def _get_nested_field(data: dict, field_path: str) -> str | None:
    """从嵌套字典中获取字段值

    Args:
        data: JSON 数据字典
        field_path: 字段路径（如 'meta.date_range.end'）

    Returns:
        字段值，或 None
    """
    parts = field_path.split(".")
    value = data
    for part in parts:
        if isinstance(value, dict):
            value = value.get(part)
        else:
            return None
    return value if isinstance(value, str) else None


def _extract_date_from_json_content(content: str, date_field: str) -> str | None:
    """从 JSON 内容字符串中提取日期字段（避免完整解析）

    对于大文件，使用正则匹配避免解析整个 JSON 对象。

    Args:
        content: JSON 内容字符串
        date_field: 字段路径（如 'meta.date_range.end'）

    Returns:
        日期字符串，或 None
    """
    import re

    # 对于 meta.date_range.end，匹配 "end": "YYYY-MM-DD"
    pattern = r'"end"\s*:\s*"(\d{4}-\d{2}-\d{2})"'
    match = re.search(pattern, content)
    if match:
        return match.group(1)

    # 对于顶层 dates 数组，匹配最后一个日期
    pattern_dates = r'"dates"\s*:\s*\[[^\]]*"(\d{4}-\d{2}-\d{2})"\s*\]'
    match_dates = re.search(pattern_dates, content)
    if match_dates:
        return match_dates.group(1)

    return None


def check_data_freshness(date: str, logger: logging.Logger) -> list[dict]:
    """检查各数据源的新鲜度（最新日期是否为 T-1）

    v1.9 (2026-06-02): 新增数据完整性检查功能

    Args:
        date: 当前日期字符串
        logger: 日志记录器

    Returns:
        检查结果列表，每项包含：
        - source: 数据源名称
        - description: 数据源描述
        - expected_date: 期望的 T-1 日期
        - actual_date: 实际最新日期
        - status: 状态（ok/warning/error）
        - status_symbol: 状态符号
    """
    expected_t_minus_1 = get_expected_t_minus_1(date)
    results = []

    for source_name, config in DATA_CHECK_SOURCES.items():
        file_path = PROJECT_ROOT / config["path"]

        result = {
            "source": source_name,
            "description": config["description"],
            "expected_date": expected_t_minus_1,
            "actual_date": "unknown",
            "status": "error",
            "status_symbol": "✗缺失",
        }

        if not file_path.exists():
            logger.warning("数据文件不存在: %s", config["path"])
            results.append(result)
            continue

        try:
            file_format = config.get("format", "line_json")
            date_field = config.get("date_field", "dates")

            if source_name == "factor_ic_data":
                # Parquet 列式存储：从 metadata 读 dates（~0ms）
                import pyarrow.parquet as pq

                schema = pq.read_schema(file_path)
                meta = schema.metadata or {}
                if b"dates" in meta:
                    dates = json.loads(meta[b"dates"])
                    if dates:
                        result["actual_date"] = dates[-1]
                else:
                    df_dates = pd.read_parquet(file_path, columns=["date"])
                    dates_list = sorted(df_dates["date"].astype(str).unique())
                    if dates_list:
                        result["actual_date"] = dates_list[-1]
                    del df_dates
            elif config.get("is_gzip"):
                with gzip.open(file_path, "rt", encoding="utf-8") as f:
                    if file_format == "line_json":
                        # 每行一个 JSON 对象，只读第一行获取顶层 dates
                        first_line = f.readline()
                        if first_line:
                            data = json.loads(first_line)
                            dates = data.get("dates", [])
                            if dates:
                                result["actual_date"] = dates[-1]
                    elif file_format == "full_json":
                        # 完整 JSON 对象（可能很大），只读取头部部分用正则匹配
                        # meta.date_range.end / 顶层 dates 通常在文件开头部分
                        content = f.read(DATA_FRESHNESS_HEAD_CHARS)
                        actual_date = _extract_date_from_json_content(content, date_field)
                        if actual_date:
                            result["actual_date"] = actual_date
            else:
                # 非压缩文件
                data = json.loads(file_path.read_text(encoding="utf-8"))
                actual_date = _get_nested_field(data, date_field)
                if actual_date:
                    result["actual_date"] = actual_date

            # 判断状态
            if result["actual_date"] == expected_t_minus_1:
                result["status"] = "ok"
                result["status_symbol"] = "✓正常"
            elif result["actual_date"] == "unknown":
                result["status"] = "error"
                result["status_symbol"] = "✗无日期"
            else:
                # 日期不匹配，可能是非交易日或数据延迟
                result["status"] = "warning"
                result["status_symbol"] = "△延迟"
                logger.warning(
                    "数据源 %s 最新日期 %s 不等于期望日期 %s（可能非交易日）",
                    source_name,
                    result["actual_date"],
                    expected_t_minus_1,
                )

        except (gzip.BadGzipFile, json.JSONDecodeError, OSError) as e:
            logger.error("读取数据文件失败: %s: %s", config["path"], e)
            result["status"] = "error"
            result["status_symbol"] = "✗读取失败"

        results.append(result)

    return results


def check_derived_data_freshness(date: str, logger: logging.Logger) -> list[dict]:
    """检查衍生数据（IC 结果、回测结果）的新鲜度

    衍生数据由上游数据生成，检查文件是否存在及其数量。

    Args:
        date: 当前日期字符串
        logger: 日志记录器

    Returns:
        检查结果列表
    """
    expected_t_minus_1 = get_expected_t_minus_1(date)
    expected_t_minus_2 = get_expected_t_minus_2(date)  # IC 结果需要 T-2（次日收益）
    results = []

    # 检查 IC 结果文件（期望 T-2）
    ic_dir = PROJECT_ROOT / DATA_PATHS["ic_result"]
    ic_files = list(ic_dir.glob("ic_*_analysis_result.json"))

    ic_result = {
        "source": "ic_results",
        "description": "IC分析结果",
        "expected_date": expected_t_minus_2,  # T-2：因次日收益数据延迟
        "actual_date": "unknown",
        "file_count": len(ic_files),
        "status": "error",
        "status_symbol": "✗缺失",
    }

    if ic_files:
        # 从第一个 IC 结果文件获取最新日期
        try:
            data = json.loads(ic_files[0].read_text(encoding="utf-8"))
            # 数据结构已变更：dates/ic_values 分离，不再使用 ic_series
            dates = data.get("dates", [])
            if dates:
                ic_result["actual_date"] = dates[-1]
                # 判断 T-2 是否为周末（周六/周日），周末不检查延迟
                t_minus_2_date = datetime.strptime(expected_t_minus_2, "%Y-%m-%d")
                is_weekend = t_minus_2_date.weekday() >= 5  # 5=周六, 6=周日

                if is_weekend:
                    # 周末不检查日期，只显示文件数量
                    ic_result["status"] = "ok"
                    ic_result["status_symbol"] = f"✓正常({len(ic_files)}因子)"
                elif ic_result["actual_date"] == expected_t_minus_2:
                    ic_result["status"] = "ok"
                    ic_result["status_symbol"] = f"✓正常({len(ic_files)}因子)"
                else:
                    ic_result["status"] = "warning"
                    ic_result["status_symbol"] = f"△延迟({len(ic_files)}因子)"
        except (json.JSONDecodeError, OSError) as e:
            logger.error("读取 IC 结果文件失败: %s", e)
            ic_result["status_symbol"] = "✗读取失败"

    results.append(ic_result)

    # 检查回测结果文件
    backtest_dir = PROJECT_ROOT / DATA_PATHS["backtest_result"]
    backtest_files = list(backtest_dir.glob("*_layered_backtest.json"))

    backtest_result = {
        "source": "backtest_results",
        "description": "分层回测结果",
        "expected_date": expected_t_minus_1,
        "actual_date": "-",
        "file_count": len(backtest_files),
        "status": "error" if not backtest_files else "ok",
        "status_symbol": "✗缺失" if not backtest_files else f"✓正常({len(backtest_files)}因子)",
    }

    results.append(backtest_result)

    # 检查综合因子结果文件
    comp_dir = PROJECT_ROOT / DATA_PATHS["comprehensive_result"]
    comp_files = list(comp_dir.glob("composite_*_1d.json"))

    comp_result = {
        "source": "composite_results",
        "description": "综合因子结果",
        "expected_date": expected_t_minus_1,
        "actual_date": "-",
        "file_count": len(comp_files),
        "status": "error" if not comp_files else "ok",
        "status_symbol": "✗缺失" if not comp_files else f"✓正常({len(comp_files)}权重)",
    }

    results.append(comp_result)

    return results


def _generate_data_check_section(data_results: list[dict], derived_results: list[dict]) -> list[str]:
    """生成数据完整性检查部分

    Args:
        data_results: 基础数据检查结果
        derived_results: 衍生数据检查结果

    Returns:
        报告文本行列表
    """
    lines = []
    lines.append("")
    lines.append("零、数据完整性检查")
    lines.append("-" * 70)

    # 期望日期说明
    expected_date = data_results[0]["expected_date"] if data_results else "unknown"
    lines.append(f"期望数据日期: {expected_date} (T-1)")
    lines.append("")

    # 基础数据检查表
    lines.append("【基础数据源】")
    lines.append(f"{'数据源':<20} {'描述':<24} {'最新日期':>12} {'状态':>10}")
    lines.append("-" * 70)

    for item in data_results:
        lines.append(
            f"{item['source']:<20} {item['description']:<24} {item['actual_date']:>12} {item['status_symbol']:>10}"
        )

    lines.append("-" * 70)
    lines.append("")

    # 衍生数据检查表
    lines.append("【衍生数据】")
    lines.append(f"{'数据源':<20} {'描述':<24} {'文件数量':>10} {'状态':>10}")
    lines.append("-" * 70)

    for item in derived_results:
        file_count_str = str(item.get("file_count", 0))
        lines.append(f"{item['source']:<20} {item['description']:<24} {file_count_str:>10} {item['status_symbol']:>10}")

    lines.append("-" * 70)

    # 汇总状态
    all_ok = all(r["status"] == "ok" for r in data_results + derived_results)
    any_error = any(r["status"] == "error" for r in data_results + derived_results)

    if all_ok:
        lines.append("")
        lines.append("汇总: ✓ 所有数据源已更新至 T-1")
    elif any_error:
        lines.append("")
        lines.append("汇总: ✗ 存在数据缺失或读取失败，请检查上游脚本执行情况")
    else:
        lines.append("")
        lines.append("汇总: △ 存在数据延迟（可能为非交易日），请确认是否需要补数据")

    lines.append("")

    return lines
