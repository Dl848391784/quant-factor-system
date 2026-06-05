#!/usr/bin/env python3
"""
因子分析数据汇总报告生成脚本

功能：
1. 读取单因子 IC 分析结果
2. 读取单因子分层回测结果
3. 计算因子相关性矩阵
4. 读取综合因子四种权重回测结果
5. 生成完整的汇总报告表格

使用方法：
    python summary/generate_factor_summary_report.py [--date YYYY-MM-DD] [--output report.txt]

参数：
    --date: 指定日期（默认当天）
    --output: 指定输出文件路径（默认 summary/result/factor_summary_report_YYYY-MM-DD.txt）
    --full-correlation: 强制计算所有因子之间的相关性（可能较慢）

版本历史：
    v1.0: 基础版本（使用 print）
    v1.1: 2026-05-28 迁移到 logging 模块，遵循 PROJECT.md 日志规范
    v1.2: 2026-05-28 修复 logger 传递缺失、函数签名不一致、删除硬编码结论
    v1.3: 2026-05-28 深度审查：删除未使用参数、补充返回类型注解、创建流程文档和pytest测试
    v1.4: 2026-05-28 第三轮深度审查：异常处理补全、重复代码重构、边界保护、避免重复读取文件
    v1.5: 2026-05-28 第四轮深度审查：魔法数字提取为常量、类型注解精确化、函数拆分重构
    v1.6: 2026-05-28 第五轮深度审查：修复10个问题（因子名清洗、单位转换注释、异常精确化、采样偏差警告、剔除原因推断、数据加载保护、对比展示逻辑、文件写入异常、窗口参数读取、总耗时日志）
    v1.9: 2026-06-02 新增数据完整性检查功能：在报告开头检查各数据源是否更新至 T-1
    v2.0: 2026-06-02 新增因子定义列展示
    v2.1: 2026-06-02 架构改进：因子定义迁移至 factor_definitions.py 统一模块
    v2.2: 2026-06-03 新增权重选择和股票选股结果展示（第七、八部分）
    v2.3: 2026-06-04 修复字段名同步：total_stocks → stocks_on_date（对齐 stock_selector v1.7）
    v2.4: 2026-06-04 因子值详情改为全部显示，移除截断逻辑
    v2.5: 2026-06-05 修复权重显示矛盾：weights 字典键是因子列名而非因子名，添加 FACTOR_NAME_TO_COL_MAP 映射表
    v2.6: 2026-06-05 修复9项问题：权重来源说明、日期不一致、高相关剔除边界、数据天数异常、overnight_ret方向异常、因子名统一、高相关对展示、权重标签区分、ICIR相等显示格式
    v2.7: 2026-06-05 修复第八节 factor_values 列名显示问题（volume_ratio_5 → volume_ratio）
    v2.8: 2026-06-05 修复高相关剔除显示精度（.2f → .3f），添加评分逻辑说明
    v2.9: 2026-06-05 修复评分说明字段名错误（normalized_scores → metric_scores）
"""

__version__ = "2.9"
__author__ = "factor_ic_analyzer"

# 标准库导入
import argparse
import gzip
import json
import logging
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path


# 项目根目录（用于 sys.path 和路径常量）
PROJECT_ROOT = Path(__file__).parent.parent.resolve()

# 添加项目根目录到 sys.path（支持根目录模块导入）
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# 第三方库导入
import pandas as pd  # noqa: E402

# 项目模块导入
from factor_definitions import FACTOR_DEFINITIONS  # noqa: E402


# 数据路径配置
DATA_PATHS = {
    "ic_result": "factor_ic/result",
    "backtest_result": "backtest/result",
    "comprehensive_result": "comprehensive_factor/result",
    "factor_data": "data_fetchers/result",
    "weight_selection": "comprehensive_factor/result/weight_selection_result.json",
    "stock_selection": "comprehensive_factor/result/stock_selection_result.json",
}

# 数据完整性检查配置
DATA_CHECK_SOURCES = {
    "factor_ic_data": {
        "path": "data_fetchers/result/factor_ic_data.json.gz",
        "description": "主数据源(行情+因子+收益)",
        "date_field": "dates",  # 从顶层 dates 数组获取最新日期
        "format": "line_json",  # 每行一个 JSON 对象，dates 在第一行顶层
        "is_gzip": True,
    },
    "factor_data": {
        "path": "data_fetchers/result/factor_data.json.gz",
        "description": "基础因子数据",
        "date_field": "meta.date_range.end",  # 从 meta.date_range.end 获取最新日期
        "format": "full_json",  # 完整 JSON 对象
        "is_gzip": True,
    },
    "turnover_data": {
        "path": "data_fetchers/result/turnover_rate_data.json.gz",
        "description": "换手率数据",
        "date_field": "meta.date_range.end",  # 从 meta.date_range.end 获取最新日期
        "format": "full_json",  # 完整 JSON 对象
        "is_gzip": True,
    },
}

# 因子列名映射（数据列名 → 因子逻辑名）
FACTOR_COL_TO_NAME_MAP = {
    "rsi_6": "rsi",
    "volume_ratio_5": "volume_ratio",
    "kdj_j": "kdj_j",
    "bollinger_pb": "bollinger_pb",
    "turnover_surge": "turnover_surge",
    "amplitude": "amplitude",
    "price_position": "price_position",
    "return_3d": "return_3d",
    "return_5d": "return_5d",
    "overnight_ret": "overnight_ret",
}

# v2.5: 因子名到列名映射（用于权重查找，weights 字典使用列名作为键）
# 来源：comprehensive_factor/common/factor_selector.py FACTOR_NAME_TO_COL_MAP
FACTOR_NAME_TO_COL_MAP = {
    # 基础因子（内置列名带后缀）
    "rsi": "rsi_6",
    "volume_ratio": "volume_ratio_5",
    # 扩展因子（列名不带后缀）
    "kdj_j": "kdj_j",
    "bollinger_pb": "bollinger_pb",
    "turnover_surge": "turnover_surge",
    "amplitude": "amplitude",
    "price_position": "price_position",
    "overnight_ret": "overnight_ret",
    "return_3d": "return_3d",
    "return_5d": "return_5d",
    "momentum_strength": "momentum_strength",
    # 尾盘因子
    "tail_price_position": "tail_price_position",
    "tail_price_slope": "tail_price_slope",
    "tail_price_volume_intensity": "tail_price_volume_intensity",
    "tail_volume_acceleration": "tail_volume_acceleration",
    "tail_volume_shrink": "tail_volume_shrink",
    # 其他因子
    "intraday_intensity": "intraday_intensity",
}

# v2.7: 列名到因子名反向映射（用于第八节 factor_values 展示）
COL_TO_FACTOR_NAME_MAP = {v: k for k, v in FACTOR_NAME_TO_COL_MAP.items()}

# 相关性阈值常量
CORR_THRESHOLD_HIGH = 0.7  # 高相关阈值
CORR_THRESHOLD_MEDIUM = 0.5  # 中等相关阈值
CORR_MAX = 1.0  # 最大相关性

# 因子筛选阈值常量
ICIR_THRESHOLD = 0.15  # ICIR 筛选阈值
RETURN_THRESHOLD = 3.0  # 多空年化收益阈值（%）

# 因子定义信息从 factor_definitions 模块导入（v2.1 架构改进）

# 相关性计算采样常量
MAX_STOCKS_SAMPLE = 100  # 相关性计算采样股票数量

# 数据单位说明
# 原始数据中 long_short_return_annual 为小数形式（如 0.15 表示 15%）
# 转换公式：百分比 = 小数 * 100
RETURN_DATA_IS_DECIMAL = True  # 标记原始数据格式，若上游变更需修改此处


def setup_logger(name: str = "generate_factor_summary_report") -> logging.Logger:
    """配置日志记录器

    Args:
        name: 日志记录器名称

    Returns:
        配置好的 Logger 对象
    """
    logger = logging.getLogger(name)

    if not logger.handlers:
        # 日志文件路径
        log_dir = PROJECT_ROOT / "summary" / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)

        log_file = log_dir / f"generate_factor_summary_report_{datetime.now().strftime('%Y-%m-%d')}.log"

        # 文件处理器
        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setLevel(logging.DEBUG)

        # 控制台处理器
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.INFO)

        # 日志格式
        formatter = logging.Formatter("%(asctime)s | %(levelname)-8s | %(name)s | %(message)s")
        file_handler.setFormatter(formatter)
        console_handler.setFormatter(formatter)

        logger.addHandler(file_handler)
        logger.addHandler(console_handler)
        logger.setLevel(logging.DEBUG)

    return logger


def get_date_str(date: str | None = None) -> str:
    """获取日期字符串

    Args:
        date: 指定日期字符串

    Returns:
        日期字符串（YYYY-MM-DD 格式）
    """
    if date:
        return date
    return datetime.now().strftime("%Y-%m-%d")


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

            if config.get("is_gzip"):
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
                        # meta.date_range.end 通常在文件开头部分
                        content = f.read(5000)  # 读取足够获取 meta 的内容
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
    # 正则：匹配 date_range 块中的 end 字段
    pattern = r'"end"\s*:\s*"(\d{4}-\d{2}-\d{2})"'
    match = re.search(pattern, content)
    if match:
        return match.group(1)

    # 对于顶层 dates 数组，匹配最后一个日期
    # 正则：匹配 dates 数组末尾的日期
    pattern_dates = r'"dates"\s*:\s*\[[^\]]*"(\d{4}-\d{2}-\d{2})"\s*\]'
    match_dates = re.search(pattern_dates, content)
    if match_dates:
        return match_dates.group(1)

    return None


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


def load_json_file(path: Path, logger: logging.Logger) -> dict | None:
    """加载 JSON 文件

    Args:
        path: JSON 文件路径
        logger: 日志记录器

    Returns:
        JSON 数据字典，或 None（文件不存在或解析失败）
    """
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        logger.debug(f"文件不存在: {path}")
        return None
    except json.JSONDecodeError as e:
        logger.warning(f"JSON 解析错误: {path}, 位置 {e.pos}, 原因: {e.msg}")
        return None
    except (PermissionError, IsADirectoryError, OSError) as e:
        logger.warning(f"文件读取错误: {path}, 类型 {type(e).__name__}, 原因: {e}")
        return None


def load_ic_results(logger: logging.Logger) -> list[dict]:
    """加载所有单因子 IC 分析结果

    Args:
        logger: 日志记录器

    Returns:
        IC 结果列表，按 ICIR 降序排序
    """
    ic_dir = PROJECT_ROOT / DATA_PATHS["ic_result"]
    results = []

    file_count = 0
    for file in ic_dir.glob("ic_*_analysis_result.json"):
        data = load_json_file(file, logger)
        if data:
            factor_name = data.get("factor_name", "")
            # 只移除末尾的 _1d 后缀（避免误删中间的 _1d）
            if factor_name.endswith("_1d"):
                factor_name = factor_name[:-3]
            ic_metrics = data.get("ic_metrics", {})
            sample_stats = data.get("sample_stats", {})

            results.append(
                {
                    "factor_name": factor_name,
                    "ic_mean": ic_metrics.get("ic_mean", 0),
                    "icir": ic_metrics.get("icir", 0),
                    "ic_std": ic_metrics.get("ic_std", 0),
                    "valid_days": sample_stats.get("valid_days", 0),
                }
            )
            file_count += 1

    # 按 ICIR 降序排序
    results.sort(key=lambda x: x["icir"], reverse=True)
    logger.info(f"加载 IC 结果: {file_count} 个因子")
    return results


def load_backtest_results(logger: logging.Logger) -> list[dict]:
    """加载所有单因子分层回测结果

    Args:
        logger: 日志记录器

    Returns:
        回测结果列表
    """
    backtest_dir = PROJECT_ROOT / DATA_PATHS["backtest_result"]
    results = []

    file_count = 0
    for file in backtest_dir.glob("*_layered_backtest.json"):
        data = load_json_file(file, logger)
        if data:
            factor_name = file.stem.replace("_layered_backtest", "")
            # v2.6: 问题7修复 - 统一因子名，移除末尾 _1d 后缀
            if factor_name.endswith("_1d"):
                factor_name = factor_name[:-3]
            long_short = data.get("long_short", {})
            monotonicity = data.get("monotonicity", {})

            # 单调性质量判定
            quality = monotonicity.get("quality", "unknown")
            quality_symbol = get_monotonicity_symbol(quality)

            results.append(
                {
                    "factor_name": factor_name,
                    "long_short_return_annual": convert_return_to_percentage(
                        long_short.get("long_short_return_annual", 0)
                    ),
                    "long_short_sharpe": long_short.get("long_short_sharpe", 0),
                    "monotonicity_correlation": monotonicity.get("correlation", 0),
                    "monotonicity_quality": quality,
                    "monotonicity_symbol": quality_symbol,
                }
            )
            file_count += 1

    logger.info(f"加载回测结果: {file_count} 个因子")
    return results


def calculate_factor_correlation(logger: logging.Logger, force_full: bool = False) -> pd.DataFrame | None:
    """计算所有因子之间的相关性矩阵

    尝试从综合因子结果文件中读取相关性数据。
    如果 force_full=True 或综合因子结果中没有相关性数据，则从因子数据文件中实时计算。

    Args:
        logger: 日志记录器
        force_full: 是否强制计算所有因子之间的相关性（忽略缓存）

    Returns:
        因子相关性矩阵 DataFrame，或 None
    """
    # 如果不强制全量计算，优先从综合因子结果文件读取
    if not force_full:
        comp_file = PROJECT_ROOT / DATA_PATHS["comprehensive_result"] / "composite_icir_weight_1d.json"
        data = load_json_file(comp_file, logger)

        if data and "meta" in data:
            meta = data["meta"]
            if "correlation_matrix" in meta:
                # 从 JSON 转换为 DataFrame
                corr_dict = meta["correlation_matrix"]
                corr_df = pd.DataFrame(corr_dict)

                # 确保对角线为1（数值精度问题）
                for col in corr_df.columns:
                    corr_df.loc[col, col] = 1.0

                # 映射数据列名到因子逻辑名（遵循 FACTOR_COL_TO_NAME_MAP）
                # 解决 volume_ratio_5 vs volume_ratio 命名不一致问题
                factor_names = [FACTOR_COL_TO_NAME_MAP.get(c, c) for c in corr_df.columns]
                corr_df.index = factor_names
                corr_df.columns = factor_names

                logger.info("从综合因子结果文件读取相关性数据（仅选中因子）")
                return corr_df

    # 如果综合因子结果中没有相关性数据，尝试从原始数据计算
    factor_data_path = PROJECT_ROOT / DATA_PATHS["factor_data"] / "factor_ic_data.json.gz"

    if not factor_data_path.exists():
        logger.warning("因子数据文件不存在，无法计算相关性")
        return None

    logger.info("从因子数据文件计算相关性（可能较慢）...")
    start_time = time.time()

    # 采样说明：使用头部截断采样（取文件前100只股票）
    # 注意：文件排列顺序可能有规律性偏差（如按市值排序），可能影响相关性计算结果
    # 如需更准确结果，应使用随机采样或完整数据集
    logger.warning("使用头部截断采样（前%d只股票），可能存在规律性偏差", MAX_STOCKS_SAMPLE)

    try:
        # 数据文件结构：每行一个股票，data 数组包含所有日期数据
        # 因子列在 data[i] 中
        factor_cols = list(FACTOR_COL_TO_NAME_MAP.keys())

        # 使用更节省内存的方法：逐行读取
        with gzip.open(factor_data_path, "rt", encoding="utf-8") as f:
            # 从 data 数组中提取因子值
            data_list = []
            stock_count = 0
            max_stocks = MAX_STOCKS_SAMPLE  # 相关性计算采样股票数量

            for line in f:
                if stock_count >= max_stocks:
                    break

                try:
                    stock_data = json.loads(line)
                    data_array = stock_data.get("data", [])

                    for day_data in data_array:
                        # 只提取因子列
                        factor_row = {}
                        for col in factor_cols:
                            if col in day_data:
                                val = day_data[col]
                                # 排除 NaN（JSON 中 NaN 会被解析为 None 或特殊值）
                                if val is not None and isinstance(val, (int, float)):
                                    factor_row[col] = val

                        if factor_row and len(factor_row) > 1:  # 至少需要 2 个因子值
                            data_list.append(factor_row)

                    stock_count += 1
                except json.JSONDecodeError:
                    continue

            if not data_list:
                logger.warning("因子数据文件无有效数据")
                return None

            # 转换为 DataFrame
            factor_df = pd.DataFrame(data_list)

            # 计算相关性
            corr_matrix = factor_df.corr()

            # 重命名
            factor_names = [FACTOR_COL_TO_NAME_MAP.get(c, c) for c in corr_matrix.columns]
            corr_df = corr_matrix.copy()
            corr_df.index = factor_names
            corr_df.columns = factor_names

            elapsed = time.time() - start_time
            logger.info(f"因子相关性计算完成，耗时: {elapsed:.2f}秒（采样{stock_count}只股票，{len(data_list)}条记录）")

            return corr_df

    # 显式列出可预期的异常类型（不捕获 KeyboardInterrupt、SystemExit 等）
    except (OSError, gzip.BadGzipFile) as e:
        logger.error("文件读取错误: %s: %s", type(e).__name__, e)
        return None
    except json.JSONDecodeError as e:
        logger.error("JSON 解析错误: 位置 %d, 原因: %s", e.pos, e.msg)
        return None
    except pd.errors.EmptyDataError as e:
        logger.error("数据为空: %s", e)
        return None
    except ValueError as e:
        logger.error("数据格式错误: %s", e)
        return None


def load_composite_results(logger: logging.Logger) -> list[dict]:
    """加载综合因子四种权重回测结果

    Args:
        logger: 日志记录器

    Returns:
        综合因子回测结果列表
    """
    comp_dir = PROJECT_ROOT / DATA_PATHS["comprehensive_result"]
    results = []

    weight_methods = ["ic_weight", "icir_weight", "rolling_icir_weight", "equal_weight"]
    file_count = 0

    for method in weight_methods:
        file = comp_dir / f"composite_{method}_1d.json"
        data = load_json_file(file, logger)
        if data:
            meta = data.get("meta", {})
            backtest = data.get("backtest_result", {})
            long_short = backtest.get("long_short", {})
            monotonicity = backtest.get("monotonicity", {})
            weights = meta.get("weights", {})

            # 格式化权重字符串
            if method == "rolling_icir_weight":
                # 从 meta.weight_meta 读取实际窗口参数（而非硬编码）
                weight_meta = meta.get("weight_meta", {})
                rolling_window = weight_meta.get("window", 60)  # 默认60日
                weight_str = f"动态权重({rolling_window}日)"
            else:
                weight_str = format_weights(weights)

            # 单调性质量判定
            quality = monotonicity.get("quality", "unknown")
            quality_symbol = get_monotonicity_symbol(quality)

            results.append(
                {
                    "weight_method": method,
                    "weight_method_display": get_weight_method_display(method),
                    "long_short_return_annual": convert_return_to_percentage(
                        long_short.get("long_short_return_annual", 0)
                    ),
                    "long_short_sharpe": long_short.get("long_short_sharpe", 0),
                    "monotonicity_correlation": monotonicity.get("correlation", 0),
                    "monotonicity_quality": quality,
                    "monotonicity_symbol": quality_symbol,
                    "weight_str": weight_str,
                    "factor_list": meta.get("factor_list", []),
                    "weights": weights,
                    "selection_result": meta.get("selection_result"),  # v1.7: 筛选详细结果
                }
            )
            file_count += 1

    logger.info(f"加载综合因子结果: {file_count} 种权重方法")
    return results


def load_weight_selection_result(logger: logging.Logger) -> dict | None:
    """加载权重选择结果

    v2.2 (2026-06-03): 新增权重选择结果加载

    Args:
        logger: 日志记录器

    Returns:
        权重选择结果字典，结构：
        {
            "best_selection": {"method": str, "composite_score": float, ...},
            "all_methods": [...],
            "scoring_metrics": [...],
            ...
        }
        或 None（文件不存在）
    """
    weight_file = PROJECT_ROOT / DATA_PATHS["weight_selection"]

    if not weight_file.exists():
        logger.debug("权重选择结果文件不存在: %s", weight_file)
        return None

    data = load_json_file(weight_file, logger)
    if data:
        logger.info(
            "加载权重选择结果: 最优方法=%s, 综合得分=%.4f",
            data.get("best_selection", {}).get("method", "N/A"),
            data.get("best_selection", {}).get("composite_score", 0),
        )
    return data


def load_stock_selection_result(logger: logging.Logger) -> dict | None:
    """加载股票选股结果

    v2.2 (2026-06-03): 新增股票选股结果加载

    Args:
        logger: 日志记录器

    Returns:
        股票选股结果字典，结构：
        {
            "meta": {"selection_date": str, "weight_method": str, "top_n": int, ...},
            "top_stocks": [{"rank": int, "code": str, "composite_value": float, ...}],
            ...
        }
        或 None（文件不存在）
    """
    stock_file = PROJECT_ROOT / DATA_PATHS["stock_selection"]

    if not stock_file.exists():
        logger.debug("股票选股结果文件不存在: %s", stock_file)
        return None

    data = load_json_file(stock_file, logger)
    if data:
        meta = data.get("meta", {})
        logger.info(
            "加载股票选股结果: 选股日期=%s, Top N=%d, 最优权重=%s",
            meta.get("selection_date", "N/A"),
            meta.get("top_n", 0),
            meta.get("weight_method", "N/A"),
        )
    return data


def get_monotonicity_symbol(quality: str) -> str:
    """获取单调性质量符号

    Args:
        quality: 单调性质量值（good/moderate/poor/unknown）

    Returns:
        单调性质量符号
    """
    symbols = {
        "good": "✓良好",
        "moderate": "△一般",
        "poor": "✗较差",
        "unknown": "?未知",
    }
    return symbols.get(quality, "?未知")


def get_weight_method_display(method: str) -> str:
    """获取权重方法显示名称

    Args:
        method: 权重方法名

    Returns:
        权重方法显示名称
    """
    displays = {
        "ic_weight": "IC加权",
        "icir_weight": "ICIR加权",
        "rolling_icir_weight": "Rolling ICIR加权",
        "equal_weight": "等权",
    }
    return displays.get(method, method)


def format_weights(weights: dict) -> str:
    """格式化权重字符串

    Args:
        weights: 权重字典（因子名 → 权重值）

    Returns:
        格式化的权重字符串（如 "ts:60%, bp:40%")

    v2.6: 添加 tail_price_position/tail_price_volume_intensity 缩写区分（问题9修复）
    """
    factor_abbr = {
        "turnover_surge": "ts",
        "bollinger_pb": "bp",
        "volume_ratio": "vr",
        "rsi": "rsi",
        "kdj_j": "kdj",
        "tail_price_position": "tp_pos",  # v2.6: 区分 tail_price 系因子
        "tail_price_volume_intensity": "tp_vol",  # v2.6: 区分 tail_price 系因子
        "tail_price_slope": "tp_slp",
        "tail_volume_acceleration": "tv_acc",
        "tail_volume_shrink": "tv_shr",
        "momentum_strength": "mom",
        "amplitude": "amp",
        "overnight_ret": "on_ret",
        "return_3d": "r3d",
        "return_5d": "r5d",
        "intraday_intensity": "in_int",
        "price_position": "pp",
        "past_return_1d": "pr1d",
    }

    parts = []
    for factor, weight in weights.items():
        abbr = factor_abbr.get(factor, factor[:3])
        parts.append(f"{abbr}:{weight * 100:.0f}%")

    return ", ".join(parts)


def format_percentage(value: float, decimals: int = 2) -> str:
    """格式化百分比

    Args:
        value: 数值（已转换为百分比，如 15.5 表示 15.5%）
        decimals: 小数位数

    Returns:
        格式化的百分比字符串
    """
    return f"{value:.{decimals}f}%"


def convert_return_to_percentage(decimal_value: float) -> float:
    """将小数形式的收益率转换为百分比

    原始数据中 long_short_return_annual 为小数形式（如 0.15 表示 15%）。
    此函数统一转换逻辑，避免多处重复 * 100。

    Args:
        decimal_value: 小数形式的收益率（如 0.15）

    Returns:
        百分比形式的收益率（如 15.0）

    Note:
        若上游数据格式变更（已经是百分比），需修改 RETURN_DATA_IS_DECIMAL 常量
    """
    if RETURN_DATA_IS_DECIMAL:
        return decimal_value * 100
    return decimal_value  # 数据已是百分比，直接返回


def format_float(value: float, decimals: int = 4) -> str:
    """格式化浮点数

    Args:
        value: 数值
        decimals: 小数位数

    Returns:
        格式化的浮点数字符串
    """
    return f"{value:.{decimals}f}"


def _extract_corr_pairs(
    corr_matrix: pd.DataFrame, factor_names: list[str], min_threshold: float, max_threshold: float
) -> list[tuple[str, str, float]]:
    """提取指定阈值范围内的因子相关性对

    Args:
        corr_matrix: 相关性矩阵
        factor_names: 因子名列表
        min_threshold: 最小阈值（|corr| > min_threshold）
        max_threshold: 最大阈值（|corr| <= max_threshold）

    Returns:
        因子对列表 [(factor1, factor2, corr_value), ...]
    """
    pairs = []
    for i, row_name in enumerate(factor_names):
        for j, col_name in enumerate(factor_names):
            if i < j:
                val = abs(corr_matrix.loc[row_name, col_name])
                if min_threshold < val <= max_threshold:
                    pairs.append((row_name, col_name, val))
    return pairs


def generate_correlation_section(
    corr_matrix: pd.DataFrame | None, ic_results: list[dict], selection_result: dict | None = None
) -> list[str]:
    """生成因子相关性部分

    v1.8 (2026-05-28): 新增 selection_result 参数（预留），添加选中因子说明

    Args:
        corr_matrix: 因子相关性矩阵（仅选中因子，可为 None）
        ic_results: IC 结果列表（用于排序因子名）
        selection_result: 筛选详细结果（预留，暂不使用）

    Returns:
        报告文本行列表
    """
    lines = []

    if corr_matrix is None:
        lines.append("")
        lines.append("三、因子相关性矩阵")
        lines.append("-" * 70)
        lines.append("因子相关性数据不可用（需要因子数据文件）")
        lines.append("-" * 70)
        return lines

    # 获取因子名（按 ICIR 排序）
    factor_names = [r["factor_name"] for r in ic_results if r["factor_name"] in corr_matrix.index]

    lines.append("")
    lines.append("三、因子相关性矩阵")
    lines.append("-" * 70)

    # 说明：此矩阵仅显示选中因子
    if factor_names:
        lines.append(f"（选中因子相关性矩阵，共 {len(factor_names)} 个因子）")

    # 表头
    header = f"{'因子':<12}"
    for name in factor_names:
        header += f"{name[:8]:>10}"
    lines.append(header)
    lines.append("-" * 70)

    # 矩阵内容
    for row_name in factor_names:
        row = f"{row_name:<12}"
        for col_name in factor_names:
            val = corr_matrix.loc[row_name, col_name]
            row += f"{format_float(val, 2):>10}"
        lines.append(row)

    lines.append("-" * 70)

    # v2.6: 问题8修复 - 展示剔除的高相关因子对
    if selection_result:
        high_corr_dropped = selection_result.get("high_corr_dropped", {})
        if high_corr_dropped:
            lines.append("")
            lines.append("【剔除的高相关因子对】")
            lines.append("以下因子因与选中因子高相关而被剔除：")
            for factor_name, reason in high_corr_dropped.items():
                # 解析剔除原因，提取相关系数
                lines.append(f"  - {factor_name}: {reason}")
            lines.append("-" * 70)

    # 选中因子之间的高相关因子对
    high_corr_pairs = _extract_corr_pairs(corr_matrix, factor_names, CORR_THRESHOLD_HIGH, CORR_MAX)

    if high_corr_pairs:
        lines.append(f"选中因子中高相关因子对（|corr| > {CORR_THRESHOLD_HIGH:.1f}，建议剔除其中一个）：")
        for pair in high_corr_pairs:
            lines.append(f"  - {pair[0]} vs {pair[1]}: {format_float(pair[2], 2)}")
    else:
        lines.append(f"选中因子中无高相关因子对（所有因子相关性 < {CORR_THRESHOLD_HIGH:.1f}）")

    # 中等相关因子对
    med_corr_pairs = _extract_corr_pairs(corr_matrix, factor_names, CORR_THRESHOLD_MEDIUM, CORR_THRESHOLD_HIGH)

    if med_corr_pairs:
        lines.append("")
        lines.append(f"选中因子中中等相关因子对（{CORR_THRESHOLD_MEDIUM:.1f} < |corr| <= {CORR_THRESHOLD_HIGH:.1f}）：")
        for pair in med_corr_pairs:
            lines.append(f"  - {pair[0]} vs {pair[1]}: {format_float(pair[2], 2)}")

    lines.append("-" * 70)

    return lines


def get_factor_selection_info(
    composite_results: list[dict], ic_results: list[dict], backtest_results: list[dict], logger: logging.Logger
) -> str:
    """获取因子筛选信息

    v1.7 (2026-05-28): 优先读取 selection_result 中的真实筛选原因，
                       解决"原因未知"问题（需要 composite_runner.py v2.9 配合）

    Args:
        composite_results: 综合因子回测结果列表
        ic_results: IC 结果列表
        backtest_results: 回测结果列表
        logger: 日志记录器

    Returns:
        因子筛选信息文本
    """
    if not composite_results:
        return "未找到综合因子结果"

    lines = []
    lines.append("auto_select 模式结果:")

    # 直接使用传入的 composite_results 数据（已在 load_composite_results 加载）
    selected_factors = []
    weights = {}
    selection_result = None  # v1.7: 筛选详细结果

    for item in composite_results:
        if item["weight_method"] == "icir_weight":
            selected_factors = item.get("factor_list", [])
            weights = item.get("weights", {})
            # v1.7: 读取 selection_result（composite_runner.py v2.9 新增）
            selection_result = item.get("selection_result")

            factor_info = []
            for f in selected_factors:
                # v2.5: weights 字典键是因子列名（如 volume_ratio_5），需先转换
                factor_col = FACTOR_NAME_TO_COL_MAP.get(f, f)
                weight = weights.get(factor_col, 0)
                ic_item = next((r for r in ic_results if r["factor_name"] == f), None)
                if ic_item:
                    factor_info.append(f"{f}(ICIR={ic_item['icir']:.2f},权重={weight * 100:.1f}%)")
                else:
                    factor_info.append(f"{f}(权重={weight * 100:.1f}%)")

            lines.append(f"  - 选中因子: {', '.join(factor_info)}")
            lines.append("  - 注：权重来自ICIR加权方法")  # v2.6: 问题1修复 - 说明权重来源
            break

    # v1.8: 显示筛选阈值
    if selection_result:
        thresholds = selection_result.get("thresholds", {})
        if thresholds:
            high_corr_threshold = thresholds.get("high_corr_threshold", 0.7)
            lines.append(f"  - 高相关阈值: {high_corr_threshold:.1f}")

    # v1.7: 优先使用 selection_result 中的真实原因
    all_factors = [r["factor_name"] for r in ic_results]
    excluded_factors = [f for f in all_factors if f not in selected_factors]

    if excluded_factors:
        excluded_info = []

        # 构建剔除原因字典（从 selection_result 获取真实原因）
        exclude_reasons: dict[str, str] = {}

        if selection_result:
            # 从 invalid 字段获取无效因子原因
            invalid = selection_result.get("invalid", {})
            for factor_name, reasons in invalid.items():
                exclude_reasons[factor_name] = "; ".join(reasons) if isinstance(reasons, list) else str(reasons)

            # 从 high_corr_dropped 字段获取高相关剔除原因
            high_corr_dropped = selection_result.get("high_corr_dropped", {})
            for factor_name, reason in high_corr_dropped.items():
                exclude_reasons[factor_name] = str(reason)

            logger.debug("从 selection_result 读取真实筛选原因: %d 条", len(exclude_reasons))

        # 对每个剔除因子查找原因
        for f in excluded_factors:
            if f in exclude_reasons:
                # 使用真实原因
                reason = exclude_reasons[f]
                logger.debug("因子 %s 剔除原因: %s", f, reason)
            else:
                # 回退推断逻辑（兼容旧版本输出文件）
                ic_item = next((r for r in ic_results if r["factor_name"] == f), None)
                bt_item = next((r for r in backtest_results if r["factor_name"] == f), None)

                reason = ""
                if ic_item and ic_item["icir"] < ICIR_THRESHOLD:
                    reason = f"ICIR<{ICIR_THRESHOLD}"
                if bt_item and bt_item["long_short_return_annual"] < RETURN_THRESHOLD:
                    reason += (", " if reason else "") + f"多空收益<{RETURN_THRESHOLD}%"

                if not reason:
                    reason = "原因未知（selection_result 未记录）"
                    logger.warning("因子 %s 剔除原因未知，建议重新执行综合因子脚本", f)

            excluded_info.append(f"{f}({reason})")

        lines.append(f"  - 剔除因子: {', '.join(excluded_info)}")

    lines.append("-" * 70)
    lines.append(f"筛选后因子列表: {selected_factors}")

    return "\n".join(lines)


def merge_factor_data(ic_results: list[dict], backtest_results: list[dict]) -> list[dict]:
    """合并 IC 和回测数据

    Args:
        ic_results: IC 结果列表
        backtest_results: 回测结果列表

    Returns:
        合并后的数据列表
    """
    merged = []

    for ic_item in ic_results:
        factor_name = ic_item["factor_name"]
        backtest_item = next((b for b in backtest_results if b["factor_name"] == factor_name), {})
        merged.append({**ic_item, **backtest_item})

    return merged


def _generate_ic_section(ic_results: list[dict]) -> list[str]:
    """生成单因子 IC 数据汇总部分

    v2.0 (2026-06-02): 新增因子定义列展示
    v2.1 (2026-06-02): 调整列宽以完整展示定义

    Args:
        ic_results: IC 结果列表

    Returns:
        报告文本行列表
    """
    lines = []
    lines.append("")
    lines.append("一、单因子 IC 数据汇总")
    lines.append("-" * 120)
    lines.append(f"{'因子':<20} {'定义':<50} {'IC均值':>8} {'ICIR':>6} {'IC标准差':>8} {'有效天数':>6}")
    lines.append("-" * 120)

    for item in ic_results:
        factor_name = item["factor_name"]
        # 获取因子定义（如果无定义则显示空）
        factor_def = FACTOR_DEFINITIONS.get(factor_name, "")
        # 截断定义以适应表格宽度（最多50字符）
        if len(factor_def) > 50:
            factor_def = factor_def[:47] + "..."

        lines.append(
            f"{factor_name:<20} "
            f"{factor_def:<50} "
            f"{format_float(item['ic_mean']):>8} "
            f"{format_float(item['icir']):>6} "
            f"{format_float(item['ic_std']):>8} "
            f"{item['valid_days']:>6}"
        )

    lines.append("-" * 120)
    ic_order = ", ".join([f"{r['factor_name']}({r['icir']:.2f})" for r in ic_results[:5]])
    lines.append(f"IC排序(ICIR降序): {ic_order}")

    # v2.6: 问题5修复 - 异常数据说明
    lines.append("")
    lines.append("【异常数据说明】")
    # 检查 tail_volume_shrink 有效天数异常
    tvs_item = next((r for r in ic_results if r["factor_name"] == "tail_volume_shrink"), None)
    if tvs_item and tvs_item["valid_days"] < 14:
        lines.append(f"tail_volume_shrink 有效天数={tvs_item['valid_days']}天（其他尾盘因子均为14天），数据可能缺失")
    # v2.6: 问题6修复 - overnight_ret 方向异常说明
    or_item = next((r for r in ic_results if r["factor_name"] == "overnight_ret"), None)
    if or_item and or_item["ic_mean"] > 0:
        other_ic_means = [r["ic_mean"] for r in ic_results if r["factor_name"] != "overnight_ret" and r["ic_mean"] is not None]
        if other_ic_means and all(ic < 0 for ic in other_ic_means[:5]):  # 检查前5个因子IC方向
            lines.append(f"overnight_ret IC均值={or_item['ic_mean']:.4f}为正（其他因子均为负），方向异常")

    return lines


def _generate_backtest_section(ic_results: list[dict], backtest_results: list[dict]) -> list[str]:
    """生成单因子分层回测数据汇总部分

    Args:
        ic_results: IC 结果列表（用于排序）
        backtest_results: 回测结果列表

    Returns:
        报告文本行列表
    """
    lines = []
    lines.append("")
    lines.append("二、单因子分层回测数据汇总")
    lines.append("-" * 70)
    lines.append(f"{'因子':<18} {'多空年化收益':>12} {'夏普比率':>8} {'单调性系数':>10} {'单调性质量':>10}")
    lines.append("-" * 70)

    # 按 IC 结果顺序排序回测结果
    factor_order_map = {r["factor_name"]: i for i, r in enumerate(ic_results)}
    backtest_sorted = sorted(backtest_results, key=lambda x: factor_order_map.get(x["factor_name"], 999))

    for item in backtest_sorted:
        lines.append(
            f"{item['factor_name']:<18} "
            f"{format_percentage(item['long_short_return_annual']):>12} "
            f"{format_float(item['long_short_sharpe'], 2):>8} "
            f"{format_float(item['monotonicity_correlation']):>10} "
            f"{item['monotonicity_symbol']:>10}"
        )

    lines.append("-" * 70)

    return lines


def _generate_composite_section(composite_results: list[dict]) -> list[str]:
    """生成综合因子四种权重回测数据汇总部分

    Args:
        composite_results: 综合因子回测结果列表

    Returns:
        报告文本行列表
    """
    lines = []
    lines.append("")
    lines.append("五、综合因子四种权重回测数据汇总")
    lines.append("-" * 70)
    lines.append(
        f"{'权重方法':<20} {'多空年化收益':>12} {'夏普比率':>8} {'单调性系数':>10} {'单调性质量':>10} {'因子权重':<20}"
    )
    lines.append("-" * 70)

    for item in composite_results:
        lines.append(
            f"{item['weight_method_display']:<20} "
            f"{format_percentage(item['long_short_return_annual']):>12} "
            f"{format_float(item['long_short_sharpe'], 2):>8} "
            f"{format_float(item['monotonicity_correlation']):>10} "
            f"{item['monotonicity_symbol']:>10} "
            f"{item['weight_str']:<20}"
        )

    lines.append("-" * 70)

    return lines


def _generate_weight_selection_section(weight_result: dict | None) -> list[str]:
    """生成权重选择结果展示部分

    v2.2 (2026-06-03): 新增权重选择结果展示

    Args:
        weight_result: 权重选择结果字典（可为 None）

    Returns:
        报告文本行列表
    """
    lines = []
    lines.append("")
    lines.append("七、权重选择结果")
    lines.append("-" * 70)

    if weight_result is None:
        lines.append("权重选择结果文件不存在，请先运行 weight_selector.py")
        lines.append("-" * 70)
        return lines

    best_selection = weight_result.get("best_selection", {})
    all_methods = weight_result.get("all_methods", [])

    # 最优方法信息
    best_method = best_selection.get("method", "N/A")
    best_score = best_selection.get("composite_score", 0)

    lines.append(f"最优权重方法: {get_weight_method_display(best_method)}")
    lines.append(f"综合得分: {format_float(best_score, 4)}")
    lines.append(f"计算日期: {weight_result.get('meta', {}).get('created_at', 'N/A')[:10]}")  # v2.6: 问题3修复 - 明确为计算日期

    # v2.7: 问题2修复 - 添加评分维度说明
    ranking = weight_result.get("ranking", [])
    if ranking:
        # 检查是否存在 ICIR加权优于IC加权但选了IC加权的情况
        ic_rank = next((r for r in ranking if r["method"] == "ic_weight"), None)
        icir_rank = next((r for r in ranking if r["method"] == "icir_weight"), None)
        if ic_rank and icir_rank:
            # 比较 ICIR加权与 IC加权的核心指标
            # v2.9: 修复字段名错误 normalized_scores → metric_scores
            ic_return = ic_rank.get("metric_scores", {}).get("long_short_return_annual", 0)
            icir_return = icir_rank.get("metric_scores", {}).get("long_short_return_annual", 0)
            ic_sharpe = ic_rank.get("metric_scores", {}).get("long_short_sharpe", 0)
            icir_sharpe = icir_rank.get("metric_scores", {}).get("long_short_sharpe", 0)
            ic_monotonicity = ic_rank.get("metric_scores", {}).get("monotonicity_abs", 0)
            icir_monotonicity = icir_rank.get("metric_scores", {}).get("monotonicity_abs", 0)

            # 如果 ICIR加权核心指标更好但排名低于 IC加权，说明换手率拖累
            if (icir_return >= ic_return and icir_sharpe >= ic_sharpe and icir_monotonicity >= ic_monotonicity):
                ic_turnover_long = ic_rank.get("metric_scores", {}).get("turnover_long_avg", 0)
                icir_turnover_long = icir_rank.get("metric_scores", {}).get("turnover_long_avg", 0)
                lines.append("")
                lines.append("【评分说明】")
                lines.append(f"ICIR加权在收益/夏普/单调性指标优于IC加权，但换手率逆向指标归一化得分较低")
                lines.append(f"  - IC加权换手率得分: {ic_turnover_long:.3f}")
                lines.append(f"  - ICIR加权换手率得分: {icir_turnover_long:.3f}")
                lines.append(f"  - 注：换手率越高越差（逆向指标），归一化后得分越低")

    lines.append("")

    # 各方法排名表格
    if all_methods:
        lines.append("【各权重方法排名】")
        lines.append(f"{'排名':>4} {'权重方法':<20} {'综合得分':>10}")
        lines.append("-" * 70)

        for i, item in enumerate(all_methods, 1):
            method_display = get_weight_method_display(item.get("method", "N/A"))
            score = item.get("composite_score", 0)
            lines.append(f"{i:>4} {method_display:<20} {format_float(score, 4):>10}")

        lines.append("-" * 70)

    # 评分指标说明
    scoring_metrics = weight_result.get("scoring_metrics", [])
    if scoring_metrics:
        lines.append("")
        lines.append("【评分指标】")
        lines.append(f"共 {len(scoring_metrics)} 个指标，Min-Max归一化后等权加权")
        lines.append("指标列表: " + ", ".join(scoring_metrics))

    lines.append("-" * 70)

    return lines


def _generate_stock_selection_section(stock_result: dict | None) -> list[str]:
    """生成股票选股结果展示部分

    v2.2 (2026-06-03): 新增股票选股结果展示

    Args:
        stock_result: 股票选股结果字典（可为 None）

    Returns:
        报告文本行列表
    """
    lines = []
    lines.append("")
    lines.append("八、股票选股结果")
    lines.append("-" * 70)

    if stock_result is None:
        lines.append("股票选股结果文件不存在，请先运行 stock_selector.py")
        lines.append("-" * 70)
        return lines

    meta = stock_result.get("meta", {})
    top_stocks = stock_result.get("top_stocks", [])

    # 元信息展示
    lines.append(f"选股日期: {meta.get('selection_date', 'N/A')}（使用T-1数据）")  # v2.6: 问题3修复 - 明确为使用数据的日期
    lines.append(f"最优权重方法: {get_weight_method_display(meta.get('weight_method', 'N/A'))}")
    lines.append(f"权重综合得分: {format_float(meta.get('composite_score', 0), 4)}")
    lines.append(
        f"因子方向: {meta.get('factor_direction', 'N/A')}（{'反向' if meta.get('factor_direction') == 'negative' else '正向'}）"
    )
    lines.append(f"选出股票数: {meta.get('top_n', 0)} 只（共 {meta.get('stocks_on_date', 0)} 只股票）")
    lines.append("")

    # Top N 股票表格
    if top_stocks:
        lines.append(f"【Top {len(top_stocks)} 股票】")
        lines.append(f"{'排名':>4} {'股票代码':<10} {'综合因子值':>12} {'因子值详情':<40}")
        lines.append("-" * 70)

        for item in top_stocks:
            rank = item.get("rank", 0)
            code = item.get("code", "N/A")
            composite_value = item.get("composite_value", 0)

            # 因子值详情（全部显示）
            factor_values = item.get("factor_values", {})
            factor_str = ""
            if factor_values:
                parts = []
                for k, v in factor_values.items():
                    if v is not None:
                        # v2.7: 问题3修复 - 列名转换为因子名（volume_ratio_5 → volume_ratio）
                        factor_name = COL_TO_FACTOR_NAME_MAP.get(k, k)
                        parts.append(f"{factor_name}={format_float(v, 2)}")
                factor_str = ", ".join(parts)  # 显示全部因子值
            else:
                factor_str = "无因子值"

            lines.append(f"{rank:>4} {code:<10} {format_float(composite_value, 3):>12} {factor_str}")

        lines.append("-" * 70)

    # 权重配置信息
    weight_config = stock_result.get("weight_config", {})
    if weight_config:
        lines.append("")
        lines.append("【权重配置】")
        lines.append(f"权重方法: {get_weight_method_display(weight_config.get('method', 'N/A'))}")
        if weight_config.get("method") == "rolling_icir_weight":
            lines.append(f"滚动窗口: {weight_config.get('window', 'N/A')} 日")
        factor_list = weight_config.get("factor_list", [])
        if factor_list:
            lines.append(f"因子列表: {', '.join(factor_list)}")

    lines.append("-" * 70)

    return lines


def _generate_comparison_section(factor_data: list[dict], composite_results: list[dict]) -> list[str]:
    """生成综合因子与单因子对比部分

    展示四种权重方法的回测指标和选中单因子的回测指标，只做收集展示不做选择。

    Args:
        factor_data: 合并后的因子数据列表
        composite_results: 综合因子回测结果列表

    Returns:
        报告文本行列表
    """
    lines = []
    lines.append("")
    lines.append("六、综合因子与单因子对比")
    lines.append("-" * 70)

    # 边界保护：空列表时跳过对比
    if not composite_results:
        lines.append("综合因子数据不足，无法生成对比表")
        lines.append("-" * 70)
        return lines

    # ========================================
    # 第一部分：综合因子四种权重方法回测数据
    # ========================================
    lines.append("")
    lines.append("【综合因子四种权重方法回测数据】")
    lines.append("-" * 70)
    lines.append(f"{'权重方法':<20} {'多空年化收益':>12} {'夏普比率':>8} {'单调性系数':>10} {'单调性质量':>10}")
    lines.append("-" * 70)

    for item in composite_results:
        lines.append(
            f"{item['weight_method_display']:<20} "
            f"{format_percentage(item['long_short_return_annual']):>12} "
            f"{format_float(item['long_short_sharpe'], 2):>8} "
            f"{format_float(item['monotonicity_correlation']):>10} "
            f"{item['monotonicity_symbol']:>10}"
        )

    lines.append("-" * 70)

    # ========================================
    # 第二部分：选中单因子回测数据
    # ========================================
    lines.append("")
    lines.append("【选中单因子回测数据】")
    lines.append("-" * 70)

    # 从 composite_results 中获取选中的因子列表（使用 icir_weight 方法的 factor_list）
    selected_factors = []
    for item in composite_results:
        if item["weight_method"] == "icir_weight":
            selected_factors = item.get("factor_list", [])
            break

    if not selected_factors:
        lines.append("未找到选中因子列表")
        lines.append("-" * 70)
        return lines

    if not factor_data:
        lines.append("单因子数据不足，无法展示选中因子")
        lines.append("-" * 70)
        return lines

    # 表头
    lines.append(
        f"{'因子名':<18} {'多空年化收益':>12} {'夏普比率':>8} {'单调性系数':>10} {'单调性质量':>10} {'权重':>8}"
    )
    lines.append("注：权重来自ICIR加权方法")  # v2.6: 问题1修复 - 说明权重来源
    lines.append("-" * 70)

    # 展示选中的单因子
    for factor_name in selected_factors:
        factor_item = next((f for f in factor_data if f["factor_name"] == factor_name), None)
        if factor_item:
            # 获取权重（从 composite_results 中）
            # v2.5: weights 字典键是因子列名（如 volume_ratio_5），需先转换
            weight_item = next((c for c in composite_results if c["weight_method"] == "icir_weight"), None)
            factor_col = FACTOR_NAME_TO_COL_MAP.get(factor_name, factor_name)
            weight = weight_item.get("weights", {}).get(factor_col, 0) if weight_item else 0

            lines.append(
                f"{factor_name:<18} "
                f"{format_percentage(factor_item.get('long_short_return_annual', 0)):>12} "
                f"{format_float(factor_item.get('long_short_sharpe', 0), 2):>8} "
                f"{format_float(factor_item.get('monotonicity_correlation', 0)):>10} "
                f"{factor_item.get('monotonicity_symbol', ''):>10} "
                f"{weight * 100:>6.1f}%"  # 权重百分比，右对齐宽度6
            )
        else:
            lines.append(f"{factor_name:<18} 数据缺失")

    lines.append("-" * 70)

    return lines


def generate_report(date: str, logger: logging.Logger, force_full_correlation: bool = False) -> str:
    """生成完整的汇总报告

    v2.2 (2026-06-03): 新增权重选择和股票选股结果展示

    Args:
        date: 日期字符串
        logger: 日志记录器
        force_full_correlation: 是否强制全量计算因子相关性

    Returns:
        汇总报告文本
    """
    lines = []

    # v1.9: 首先进行数据完整性检查
    logger.info("执行数据完整性检查...")
    data_results = check_data_freshness(date, logger)
    derived_results = check_derived_data_freshness(date, logger)

    # 加载所有数据
    logger.info("加载 IC 结果...")
    ic_results = load_ic_results(logger)

    logger.info("加载回测结果...")
    backtest_results = load_backtest_results(logger)

    logger.info("加载综合因子结果...")
    composite_results = load_composite_results(logger)

    # v2.2: 加载权重选择和股票选股结果
    logger.info("加载权重选择结果...")
    weight_result = load_weight_selection_result(logger)

    logger.info("加载股票选股结果...")
    stock_result = load_stock_selection_result(logger)

    # 数据加载失败保护：关键数据为空时抛出明确错误
    if not ic_results:
        logger.error("IC 结果数据为空，无法生成报告")
        raise ValueError("IC 结果数据为空，请检查 factor_ic/result 目录是否有数据文件")
    if not backtest_results:
        logger.error("回测结果数据为空，无法生成报告")
        raise ValueError("回测结果数据为空，请检查 backtest/result 目录是否有数据文件")

    logger.info(
        "数据加载完成: IC结果 %d 个, 回测结果 %d 个, 综合因子 %d 种权重方法",
        len(ic_results),
        len(backtest_results),
        len(composite_results),
    )
    corr_matrix = calculate_factor_correlation(logger, force_full=force_full_correlation)

    # 合并 IC 和回测数据
    factor_data = merge_factor_data(ic_results, backtest_results)

    # 报告标题
    lines.append("=" * 70)
    lines.append(f"                    因子分析数据汇总报告 ({date})")
    lines.append("=" * 70)

    # v1.9: 第零部分：数据完整性检查（新增）
    lines.extend(_generate_data_check_section(data_results, derived_results))

    # 第一部分：单因子 IC 数据汇总
    lines.extend(_generate_ic_section(ic_results))

    # 第二部分：单因子分层回测数据汇总
    lines.extend(_generate_backtest_section(ic_results, backtest_results))

    # 第三部分：因子相关性矩阵
    # v1.8: 从 composite_results 提取 selection_result
    selection_result = None
    if composite_results:
        for item in composite_results:
            if item.get("weight_method") == "icir_weight":
                selection_result = item.get("selection_result")
                break
    lines.extend(generate_correlation_section(corr_matrix, ic_results, selection_result))

    # 第四部分：因子筛选结果
    lines.append("")
    lines.append("四、因子筛选结果")
    lines.append("-" * 70)
    selection_info = get_factor_selection_info(composite_results, ic_results, backtest_results, logger)
    lines.append(selection_info)

    # 第五部分：综合因子四种权重回测数据汇总
    lines.extend(_generate_composite_section(composite_results))

    # 第六部分：综合因子 vs 单因子对比
    lines.extend(_generate_comparison_section(factor_data, composite_results))

    # v2.2: 第七部分：权重选择结果（新增）
    lines.extend(_generate_weight_selection_section(weight_result))

    # v2.2: 第八部分：股票选股结果（新增）
    lines.extend(_generate_stock_selection_section(stock_result))

    return "\n".join(lines)


def main():
    """主函数"""
    # 初始化日志记录器
    logger = setup_logger("generate_factor_summary_report")

    # 记录开始时间（用于计算总耗时）
    start_time = time.time()
    logger.info(f"开始生成汇总报告 (版本 {__version__})")

    parser = argparse.ArgumentParser(description="生成因子分析数据汇总报告")
    parser.add_argument("--date", type=str, help="指定日期 (YYYY-MM-DD)，默认当天")
    parser.add_argument(
        "--output", type=str, help="输出文件路径，默认 summary/result/factor_summary_report_YYYY-MM-DD.txt"
    )
    parser.add_argument("--full-correlation", action="store_true", help="强制计算所有因子之间的相关性（可能较慢）")

    args = parser.parse_args()

    date = get_date_str(args.date)
    report = generate_report(date, logger, force_full_correlation=args.full_correlation)

    # 默认输出到 summary/result/ 目录
    if args.output:
        output_path = Path(args.output)
    else:
        result_dir = PROJECT_ROOT / "summary" / "result"
        result_dir.mkdir(parents=True, exist_ok=True)
        output_path = result_dir / f"factor_summary_report_{date}.txt"

    # 文件写入异常处理
    try:
        output_path.write_text(report, encoding="utf-8")
        logger.info(f"报告已保存到: {output_path}")
    except OSError as e:
        logger.error("文件写入失败: %s, 原因: %s", output_path, e)
        sys.exit(1)

    # 记录总耗时
    elapsed = time.time() - start_time
    logger.info(f"报告生成完成，总耗时: {elapsed:.2f}秒")


if __name__ == "__main__":
    main()
