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
    v2.18: 2026-06-13 单一映射来源（方案 B）
        - 删除本地 FACTOR_COL_TO_NAME_MAP / FACTOR_NAME_TO_COL_MAP / COL_TO_FACTOR_NAME_MAP
        - 改为从 factor_definitions 导入（FACTOR_NAME_TO_COL_MAP / FACTOR_COL_TO_NAME_MAP）
        - 行为变化：相关性矩阵因子覆盖从 10 个扩为 34 个（含尾盘/方向性/差分/行业/资金流）
        - 详见 designs/factor_name_col_map_unification_design.md §3.5
    v2.6: 2026-06-05 修复9项问题：权重来源说明、日期不一致、高相关剔除边界、数据天数异常、overnight_ret方向异常、因子名统一、高相关对展示、权重标签区分、ICIR相等显示格式
    v2.7: 2026-06-05 修复第八节 factor_values 列名显示问题（volume_ratio_5 → volume_ratio）
    v2.8: 2026-06-05 修复高相关剔除显示精度（.2f → .3f），添加评分逻辑说明
    v2.9: 2026-06-05 修复评分说明字段名错误（normalized_scores → metric_scores）
    v2.10: 2026-06-05 Rolling ICIR加权展示最后一日具体权重
    v2.11: 2026-06-11 修复综合因子权重数据源：从 _last_day_weights 读取真实权重而非 get_weights() 等权回退
    v2.12: 2026-06-11 增加覆盖率列
    v2.13: 2026-06-11 区分"缺失(NaN)"和"真实≈0"（tail_price_volume_intensity 原始值=0 是真实数据而非缺失）
    v2.14: 2026-06-11 因子值详情改为显示标准化值(z-score)而非原始值——原始值极端误导（如 momentum_strength=-9.08→z=-2.65）
    v2.15: 2026-06-11 正向因子取反后z-score加*标记+表头说明，消除解读歧义（overnight_ret=-3.00是取反后值≠原始z-score）
    v2.16: 2026-06-11 权重展示修复——最优方法为Rolling ICIR时展示真实last_day_weights而非静态ICIR权重；tail_price_position从18.4%(静态)→8.3%(Rolling最新日)；权重来源说明动态化
    v2.17: 2026-06-11 评分说明重构——展示所有4种方法的9维度完整评分明细而非只对比IC vs ICIR；最优方法(Rolling ICIR)换手率低分给出解释
    v2.18: 2026-06-11 选股结果展示振幅过滤信息（排除振幅<1%%的一字板涨停股）；top_n 从 3 改为 10
    v2.19: 2026-06-17 修复 factor_ic_data 新鲜度检查误报：主数据源为完整 JSON 对象，读取 gzip 头部解析顶层 dates[-1]
    v2.20: 2026-06-17 基础数据源检查纳入 tail_trading_data，展示尾盘5分钟K线数据新鲜度
    v2.21: 2026-06-19 修复6项报告问题：
           - Fix1: Rolling ICIR last_day_weights 权重查找增加因子名回退（volume_ratio 0%→6.5%）
           - Fix2: overnight_ret 异常说明"其他因子均为负"→"其他主要因子均为负"
           - Fix3: Section 6 综合因子收益说明动态编号，避免跳号
           - Fix4: load_backtest_results 剥离 _1d 后缀（intraday_intensity_1d→intraday_intensity）
           - Fix5: overnight_ret 回测夏普/单调性精度格式化（15位小数→2位）
           - Fix6: z-score 列移除"≈0(真实)"标签，统一显示"0.00"
    v2.26: 2026-06-23 第八节"股票选股结果"在股票代码后新增"股票名称"列
           - 新增 load_stock_name_map() 从 paths.STOCK_LIST_DATA 加载 code→name 映射
           - Top 10 详表、短名单 11~N 简表、决策卡片三处表格统一展示名称
           - 名称缺失时回退"--"，文件缺失/解析失败仅 warning 不阻塞主报告
"""

__version__ = "3.7"  # v3.7 (2026-06-24): 读 Parquet 分区数据集 + 渲染 Stage 1/2/3 三段轨迹
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
from comprehensive_factor.decision_card import CHECKLIST_D5  # noqa: E402
from factor_definitions import (  # noqa: E402
    FACTOR_CATEGORIES,
    FACTOR_COL_TO_NAME_MAP,
    FACTOR_DEFINITIONS,
    FACTOR_NAME_TO_COL_MAP,
)
from paths import STOCK_LIST_DATA  # noqa: E402


# v2.7→v2.18: 列名到因子名反向映射 alias（向后兼容）
# v2.18 (2026-06-13): 删除本地 FACTOR_NAME_TO_COL_MAP / FACTOR_COL_TO_NAME_MAP / COL_TO_FACTOR_NAME_MAP
#                    改为从 factor_definitions 导入（单一映射来源，方案 B）
#                    详见 designs/factor_name_col_map_unification_design.md §3.5
COL_TO_FACTOR_NAME_MAP = FACTOR_COL_TO_NAME_MAP

# v2.22: 因子缩写表（模块级常量，format_weights 和 generate_correlation_section 共用）
FACTOR_ABBR = {
    "turnover_surge": "ts",
    "bollinger_pb": "bp",
    "volume_ratio": "vr",
    "rsi": "rsi",
    "kdj_j": "kdj",
    "tail_price_position": "tp_pos",
    "tail_price_volume_intensity": "tp_vol",
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
    "tail_price_position_delta": "tp_pos_d",
    "tail_volume_shrink_delta": "tv_shr_d",
    "volume_price_strength": "vps_str",
    "positive_day_ratio_5": "pdr5d",
    "ma5_deviation": "m5_dev",
    "near_high_ratio_5": "nrhr5d",
}


def _get_factor_abbr(factor_name: str) -> str:
    """获取因子缩写，未命中时取前3字符

    v2.22: 从 format_weights 提取为模块级函数，供 generate_correlation_section 复用
    """
    return FACTOR_ABBR.get(factor_name, factor_name[:3])


# 数据路径配置
DATA_PATHS = {
    "ic_result": "factor_ic/result",
    "backtest_result": "backtest/result",
    "comprehensive_result": "comprehensive_factor/result",
    "factor_data": "data_fetchers/result",
    "weight_selection": "comprehensive_factor/result/weight_selection_result.json",
    "stock_selection": "comprehensive_factor/result/stock_selection_history",
}

DATA_FRESHNESS_HEAD_CHARS = 65536  # 覆盖完整顶层 dates 数组，避免解析 factor_ic_data 全量大文件

# 数据完整性检查配置
DATA_CHECK_SOURCES = {
    "factor_ic_data": {
        "path": "data_fetchers/result/factor_ic_data.parquet",
        "description": "主数据源(行情+因子+收益)",
        "date_field": "dates",  # Parquet metadata 优先读取，fallback 读 JSON.gz 顶层 dates
        "format": "full_json",  # Parquet 优先（L4），JSON.gz fallback
        "is_gzip": True,  # fallback 用 gzip 读取 JSON.gz
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
    "tail_trading_data": {
        "path": "data_fetchers/result/tail_trading_data.json.gz",
        "description": "尾盘5分钟K线数据",
        "date_field": "meta.date_range.end",  # 从 meta.date_range.end 获取最新日期
        "format": "full_json",  # 完整 JSON 对象
        "is_gzip": True,
    },
    "market_cap_data": {
        "path": "data_fetchers/result/market_cap_data.json.gz",
        "description": "市值数据(市值中性化用)",
        "date_field": "meta.date_range.end",  # 从 meta.date_range.end 获取最新日期
        "format": "full_json",  # 完整 JSON 对象
        "is_gzip": True,
    },
}

# v2.18: 本地 FACTOR_COL_TO_NAME_MAP / FACTOR_NAME_TO_COL_MAP / COL_TO_FACTOR_NAME_MAP
#        已删除，改为从 factor_definitions 导入（单一映射来源，方案 B）
#        - 历史本地 FACTOR_COL_TO_NAME_MAP 仅 10 条，迁移后扩为 34 条（含尾盘/方向性/差分/行业/资金流因子）
#        - line 746 list(FACTOR_COL_TO_NAME_MAP.keys()) 因子列集合从 10 → 34（预期变化：相关性矩阵覆盖更全）
#        - 详见 designs/factor_name_col_map_unification_design.md §3.5

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
        logger.debug("文件不存在: %s", path)
        return None
    except json.JSONDecodeError as e:
        logger.warning("JSON 解析错误: %s, 位置 %s, 原因: %s", path, e.pos, e.msg)
        return None
    except (PermissionError, IsADirectoryError, OSError) as e:
        logger.warning("文件读取错误: %s, 类型 %s, 原因: %s", path, type(e).__name__, e)
        return None


def _select_neutral_payload(data: dict) -> tuple[dict, str]:
    """选择 summary 使用的中性化 payload（P4: 仅读 ic_neutralized）。

    返回 (payload, method)。method 用于汇总报告"中性化方式"列：
        - enabled=True 且 controls_used 非空：按注册顺序拼接，如 "industry+log_market_cap"
        - enabled=False：显示 "skipped"（具体原因在 skipped_reason 中）
        - 无 ic_neutralized 字段：显示 "-"（需重跑因子）
    """
    neutralized = data.get("ic_neutralized")
    if isinstance(neutralized, dict) and neutralized:
        if neutralized.get("enabled") is not True:
            return neutralized, "skipped"
        controls_used = neutralized.get("controls_used") or []
        method = "+".join(str(control) for control in controls_used) if controls_used else "neutralized"
        return neutralized, method

    return {}, "-"


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

            # P3 中性化字段：新字段优先，旧字段兜底（design.md §10.2 P3.3）
            # 只读取摘要列需要的字段：enabled / decay_rate / decay_level / controls_used
            neutral, neutral_method = _select_neutral_payload(data)

            results.append(
                {
                    "factor_name": factor_name,
                    "ic_mean": ic_metrics.get("ic_mean", 0),
                    "icir": ic_metrics.get("icir", 0),
                    "ic_std": ic_metrics.get("ic_std", 0),
                    "valid_days": sample_stats.get("valid_days", 0),
                    "neutral_enabled": neutral.get("enabled", False),
                    "neutral_decay_rate": neutral.get("decay_rate"),  # None 时摘要列显示 '-'
                    "neutral_decay_level": neutral.get("decay_level", "undefined"),
                    "neutral_method": neutral_method,
                }
            )
            file_count += 1

    # 按 ICIR 降序排序
    results.sort(key=lambda x: x["icir"], reverse=True)
    logger.info("加载 IC 结果: %s 个因子", file_count)
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
            # v2.11: 修复 past_return_1d 被错误剥离为 past_return 的问题
            # 根因：从文件 stem 剥离 _1d 会误删因子名中的 _1d（如 past_return_1d）
            # 修复：优先从 JSON 数据读取 factor_name，回退时才从文件 stem 提取
            # 注意：部分回测文件 factor_name 在 meta 子对象中（如 past_return_1d_layered_backtest.json）
            factor_name_from_json = data.get("factor_name", "") or data.get("meta", {}).get("factor_name", "")
            if factor_name_from_json:
                factor_name = factor_name_from_json
                # v2.21: 与 load_ic_results 保持一致——剥离 return_period 后缀 _1d
                # 但需避免误剥 past_return_1d（其因子名本身含 _1d）
                # 策略：剥离后检查 FACTOR_DEFINITIONS，仅当剥离结果在定义表中才剥离
                if factor_name.endswith("_1d"):
                    stripped = factor_name[:-3]
                    if stripped in FACTOR_DEFINITIONS:
                        factor_name = stripped
            else:
                # 回退：从文件 stem 提取（兼容无 factor_name 字段的旧文件）
                factor_name = file.stem.replace("_layered_backtest", "")
                # 旧文件中 stem 可能包含数据周期后缀 _1d，需剥离
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

    logger.info("加载回测结果: %s 个因子", file_count)
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
    factor_data_path = PROJECT_ROOT / DATA_PATHS["factor_data"] / "factor_ic_data.parquet"

    if not factor_data_path.exists():
        logger.warning("因子数据文件不存在，无法计算相关性")
        return None

    logger.info("从 Parquet 读取因子数据计算相关性（列投影）...")
    start_time = time.time()

    factor_cols = list(FACTOR_COL_TO_NAME_MAP.keys())
    read_cols = ["date", "asset"] + factor_cols
    corr_df_raw = pd.read_parquet(factor_data_path, columns=read_cols)

    # 采样：取前 MAX_STOCKS_SAMPLE 只股票
    unique_assets = corr_df_raw["asset"].unique()
    sampled_assets = unique_assets[:MAX_STOCKS_SAMPLE]
    corr_df_raw = corr_df_raw[corr_df_raw["asset"].isin(sampled_assets)]

    # 提取因子列
    available_factor_cols = [c for c in factor_cols if c in corr_df_raw.columns]
    factor_df = corr_df_raw[["date", "asset"] + available_factor_cols].copy()
    del corr_df_raw

    # 计算相关性
    corr_matrix = factor_df[available_factor_cols].corr()

    # 重命名
    factor_names = [FACTOR_COL_TO_NAME_MAP.get(c, c) for c in corr_matrix.columns]
    corr_df = corr_matrix.copy()
    corr_df.index = factor_names
    corr_df.columns = factor_names

    elapsed = time.time() - start_time
    logger.info(
        "因子相关性计算完成(Parquet)，耗时: %.2f秒（采样%s只股票）",
        elapsed,
        len(sampled_assets),
    )

    return corr_df


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
                # v2.10: 读取最后一日权重并展示
                last_day_weights = weight_meta.get("last_day_weights", {})
                if last_day_weights:
                    weight_str = format_weights(last_day_weights) + f" (最新,{rolling_window}日滚动)"
                else:
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
                    "weight_meta": meta.get("weight_meta", {}),  # v2.18: Rolling ICIR 动态权重元信息
                    "selection_result": meta.get("selection_result"),  # v1.7: 筛选详细结果
                    "direction_map": data.get("config", {}).get("direction_map", {}),  # v2.12: 方向映射
                    "flipped_factors": data.get("config", {}).get("flipped_factors", []),  # v2.12: 取反因子
                }
            )
            file_count += 1

    logger.info("加载综合因子结果: %s 种权重方法", file_count)
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
    """加载股票选股结果 (v3.7: 从 Parquet 分区数据集读取最新一日).

    v3.7 (2026-06-24): 数据源切换 JSON → Parquet 分区数据集.
    路径: comprehensive_factor/result/stock_selection_history/selection_date=YYYY-MM-DD/part-0.parquet
    每天分区含 Stage 1/2/3 Top N 行 (默认 ~90 行); 取最新 selection_date 分区,
    按 stage 拆为三段, 渲染段可分别展示 (设计依据: designs/feat_stock_selection_history_parquet.md §3).

    v2.2 (2026-06-03): 新增股票选股结果加载

    Args:
        logger: 日志记录器

    Returns:
        股票选股结果字典 (向后兼容旧 schema + 新增 stage1/2 段):
        {
            "meta": {"selection_date": str, "weight_method": str, "top_n": int,
                     "min_amplitude": float, "excluded_by_amplitude": int,
                     "stocks_on_date": int, "direction_map": dict,
                     "flipped_factors": list, ...},
            "top_stocks": [{"rank": int, "code": str, "composite_value": float,
                            "factor_values": dict, "factor_values_std": dict,
                            "decision_card": dict | None, ...}, ...],   # Stage 3 短名单
            "stage1_top": [{...}],   # 新增 v3.7: Stage 1 composite 降序 Top N
            "stage2_top": [{...}],   # 新增 v3.7: Stage 2 turnover 升序 Top N
            "weight_config": {...},
        }
        或 None (数据集不存在 / 空).
    """
    import contextlib
    import json as _json

    import pyarrow.compute as pc
    import pyarrow.dataset as pads
    import pyarrow.parquet as pq

    history_root = PROJECT_ROOT / DATA_PATHS["stock_selection"]

    if not history_root.exists():
        logger.debug("股票选股 Parquet 数据集不存在: %s", history_root)
        return None

    try:
        dataset = pads.dataset(str(history_root), partitioning="hive")
    except Exception:
        logger.exception("读取股票选股 Parquet 数据集失败: %s", history_root)
        return None

    # 取最新 selection_date 分区
    dates_table = dataset.to_table(columns=["selection_date"])
    if dates_table.num_rows == 0:
        logger.warning("股票选股 Parquet 数据集为空: %s", history_root)
        return None

    dates = dates_table.column("selection_date").to_pylist()
    latest_date = max(dates)

    df = dataset.to_table(filter=pc.field("selection_date") == latest_date).to_pandas()
    if df.empty:
        logger.warning("最新分区 %s 无行", latest_date)
        return None

    # 找该日 part-0.parquet 用于读 file-level metadata
    partition_dir = history_root / f"selection_date={latest_date}"
    part_files = sorted(partition_dir.glob("*.parquet"))
    file_meta_raw: dict[bytes, bytes] = {}
    if part_files:
        try:
            pq_meta = pq.read_metadata(str(part_files[0]))
            if pq_meta.metadata:
                file_meta_raw = dict(pq_meta.metadata)
        except Exception:
            logger.exception("读 Parquet file-level metadata 失败: %s", part_files[0])

    def _meta_str(key: str, default: str = "") -> str:
        v = file_meta_raw.get(key.encode())
        return v.decode() if v else default

    def _meta_int(key: str, default: int = 0) -> int:
        s = _meta_str(key)
        try:
            return int(s) if s else default
        except (ValueError, TypeError):
            return default

    def _meta_float(key: str, default: float = 0.0) -> float:
        s = _meta_str(key)
        try:
            return float(s) if s else default
        except (ValueError, TypeError):
            return default

    def _meta_json(key: str, default):
        s = _meta_str(key)
        if not s:
            return default
        try:
            return _json.loads(s)
        except (ValueError, TypeError):
            return default

    # 行 → 渲染兼容字典 (旧 schema "top_stocks" 项的结构)
    def _row_to_stock_dict(row: pd.Series) -> dict:
        out: dict = {
            "rank": int(row["rank"]),
            "code": str(row["code"]),
            "composite_value": (float(row["composite_value"]) if pd.notna(row["composite_value"]) else None),
        }
        if pd.notna(row.get("weight_coverage")):
            out["weight_coverage"] = float(row["weight_coverage"])
        if pd.notna(row.get("stage1_rank")):
            out["stage1_rank"] = int(row["stage1_rank"])
        if pd.notna(row.get("stage2_sort_value")):
            out["stage2_sort_value"] = float(row["stage2_sort_value"])
        if pd.notna(row.get("excluded_at_stage3")) and row["excluded_at_stage3"]:
            out["excluded_at_stage3"] = str(row["excluded_at_stage3"])
        # 嵌套 JSON 串解析回 dict
        fv = row.get("factor_values_json")
        if isinstance(fv, str) and fv:
            with contextlib.suppress(ValueError, TypeError):
                out["factor_values"] = _json.loads(fv)
        fvs = row.get("factor_values_std_json")
        if isinstance(fvs, str) and fvs:
            with contextlib.suppress(ValueError, TypeError):
                out["factor_values_std"] = _json.loads(fvs)
        dc = row.get("decision_card_json")
        if isinstance(dc, str) and dc:
            with contextlib.suppress(ValueError, TypeError):
                out["decision_card"] = _json.loads(dc)
        return out

    df_sorted = df.sort_values(["stage", "rank"])
    stage1_rows = df_sorted[df_sorted["stage"] == 1]
    stage2_rows = df_sorted[df_sorted["stage"] == 2]
    stage3_rows = df_sorted[df_sorted["stage"] == 3]
    # v3.8: Stage 1 Bottom 30 (stage=4)
    stage1_bottom_rows = df_sorted[df_sorted["stage"] == 4]

    stage1_top = [_row_to_stock_dict(r) for _, r in stage1_rows.iterrows()]
    stage2_top = [_row_to_stock_dict(r) for _, r in stage2_rows.iterrows()]
    stage3_top = [_row_to_stock_dict(r) for _, r in stage3_rows.iterrows()]
    stage1_bottom = [_row_to_stock_dict(r) for _, r in stage1_bottom_rows.iterrows()]

    # meta 重建: 从 stage3 首行 (若空则 stage1) + file metadata
    ref_row = (
        stage3_rows.iloc[0]
        if not stage3_rows.empty
        else (stage1_rows.iloc[0] if not stage1_rows.empty else df_sorted.iloc[0])
    )
    direction_map = {}
    dm_raw = ref_row.get("direction_map_json")
    if isinstance(dm_raw, str) and dm_raw:
        with contextlib.suppress(ValueError, TypeError):
            direction_map = _json.loads(dm_raw)
    flipped_factors: list = []
    ff_raw = ref_row.get("flipped_factors_json")
    if isinstance(ff_raw, str) and ff_raw:
        with contextlib.suppress(ValueError, TypeError):
            flipped_factors = _json.loads(ff_raw)

    meta = {
        "selection_date": str(latest_date),
        "weight_method": str(ref_row["weight_method"]),
        "factor_direction": str(ref_row["factor_direction"]),
        "top_n": int(ref_row["top_n"]),
        "composite_score": float(ref_row["composite_score"]) if pd.notna(ref_row.get("composite_score")) else 0.0,
        "direction_map": direction_map,
        "flipped_factors": flipped_factors,
        "stocks_on_date": _meta_int("stocks_on_date"),
        "min_amplitude": _meta_float("min_amplitude"),
        "min_weight_coverage": _meta_float("min_weight_coverage"),
        "excluded_by_amplitude": _meta_int("excluded_by_amplitude"),
        "excluded_by_coverage": _meta_int("excluded_by_coverage"),
        "excluded_by_liquidity": _meta_int("excluded_by_liquidity"),
        "excluded_by_confirmation": _meta_int("excluded_by_confirmation"),
        "excluded_by_overheat": _meta_int("excluded_by_overheat"),  # v3.9
        "excluded_by_filter": _meta_json("excluded_by_filter", {}),
        "stage1_pool_size": int(ref_row["stage1_pool_size"]) if pd.notna(ref_row.get("stage1_pool_size")) else None,
        "stage2_sort_col": str(ref_row["stage2_sort_col"]) if pd.notna(ref_row.get("stage2_sort_col")) else None,
        "stage2_ascending": bool(ref_row["stage2_ascending"]) if pd.notna(ref_row.get("stage2_ascending")) else None,
        "valid_stocks": len(stage3_top),
    }

    weight_config = {
        "method": meta["weight_method"],
        "factor_list": _meta_json("factor_list_json", []),
        "factor_cols": _meta_json("factor_cols_json", []),
    }

    result = {
        "meta": meta,
        "top_stocks": stage3_top,  # 向后兼容: 默认仍指 Stage 3 短名单
        "stage1_top": stage1_top,
        "stage2_top": stage2_top,
        "stage3_top": stage3_top,
        "stage1_bottom": stage1_bottom,  # v3.8: Bottom 30
        "weight_config": weight_config,
    }

    logger.info(
        "加载股票选股结果 (Parquet): 选股日期=%s, Top N=%d, 最优权重=%s, "
        "Stage1=%d/Stage2=%d/Stage3=%d, 振幅阈值=%.2f%%, 振幅排除=%d只",
        meta["selection_date"],
        meta["top_n"],
        meta["weight_method"],
        len(stage1_top),
        len(stage2_top),
        len(stage3_top),
        meta["min_amplitude"] * 100,
        meta["excluded_by_amplitude"],
    )
    return result


def load_stock_name_map(logger: logging.Logger) -> dict[str, str]:
    """加载股票代码 → 股票名称映射

    v2.26 (2026-06-23): 新增——summary 第八节"股票选股结果"在股票代码后展示名称。

    数据源：paths.STOCK_LIST_DATA (data_fetchers/result/stock_list.json)
            由 fetch_stock_list.py 维护，结构 {"stocks": [{"code", "name", ...}, ...]}。

    Args:
        logger: 日志记录器

    Returns:
        {code: name} 字典。文件不存在或解析失败时返回空 dict（降级为不展示名称，
        而非抛错——名称仅是展示辅助，不应阻塞主报告生成）。
    """
    stock_file = STOCK_LIST_DATA
    if not stock_file.exists():
        logger.warning("股票列表文件不存在: %s（短名单将不展示股票名称）", stock_file)
        return {}

    try:
        data = load_json_file(stock_file, logger)
    except Exception as e:
        logger.warning("加载股票列表失败: %s（短名单将不展示股票名称）", e)
        return {}

    if not data:
        return {}

    stocks = data.get("stocks", [])
    name_map: dict[str, str] = {}
    for s in stocks:
        code = s.get("code")
        name = s.get("name")
        if code and name:
            # 清洗名称内的全角空格（如 "万 科Ａ" → "万科Ａ"），便于对齐表格列宽
            name_map[str(code)] = str(name).replace(" ", "").replace("\u3000", "")
    logger.info("加载股票名称映射: %d 只", len(name_map))
    return name_map


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
        weights: 权重字典（因子名或列名 → 权重值）

    Returns:
        格式化的权重字符串（如 "ts:60%, bp:40%")

    v2.6: 添加 tail_price_position/tail_price_volume_intensity 缩写区分（问题9修复）
    v2.22: 缩写表提取为模块级 FACTOR_ABBR + _get_factor_abbr；
           键归一化（列名→因子名）解决 vol/vr 不一致；
           权重 <0.5% 显示1位小数避免截断为 0%
    v2.23: 权重统一 :.1f 精度，与 Section 4/6 的 :.1f 保持一致，
           避免 vr:6% vs 6.5% 跨节显示差异
    """
    parts = []
    for factor, weight in weights.items():
        # v2.22: 归一化键——列名(如 volume_ratio_5)→因子名(如 volume_ratio)
        factor_name = COL_TO_FACTOR_NAME_MAP.get(factor, factor) or factor
        abbr = _get_factor_abbr(factor_name)
        pct = weight * 100
        # v2.23: 统一 1 位小数，与 Section 4/6 权重显示精度一致
        parts.append(f"{abbr}:{pct:.1f}%")

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
        # v2.22: 用因子缩写替代 name[:8]，避免 tail_pri ×3 无法区分
        abbr = _get_factor_abbr(name)
        header += f"{abbr:>10}"
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

    # v2.24: 缩写对照表——行名用全名、列名用缩写，需输出对照表供读者查阅
    if factor_names:
        abbr_pairs = [(name, _get_factor_abbr(name)) for name in factor_names]
        # 只在有缩写差异时才输出（避免全名=缩写时多余）
        diff_pairs = [(n, a) for n, a in abbr_pairs if n != a]
        if diff_pairs:
            lines.append("【缩写对照表】")
            for name, abbr in diff_pairs:
                lines.append(f"  {abbr:<10} = {name}")

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
    # v2.23 (2026-06-20): 维度感知展示——跨维度高相关标注"保留"，同维度才标"建议检查"
    high_corr_pairs = _extract_corr_pairs(corr_matrix, factor_names, CORR_THRESHOLD_HIGH, CORR_MAX)

    if high_corr_pairs:
        # 按维度分类: 跨维度保留 vs 同维度（应已被筛选去重）
        cross_dim_pairs: list[tuple[str, str, float]] = []
        same_dim_pairs: list[tuple[str, str, float]] = []
        for pair in high_corr_pairs:
            cat_i = FACTOR_CATEGORIES.get(pair[0])
            cat_j = FACTOR_CATEGORIES.get(pair[1])
            if cat_i and cat_j and cat_i != cat_j:
                cross_dim_pairs.append(pair)
            else:
                same_dim_pairs.append(pair)

        if cross_dim_pairs:
            lines.append(f"选中因子中跨维度高相关因子对（|corr| > {CORR_THRESHOLD_HIGH:.1f}，维度不同→保留，不去重）：")
            for pair in cross_dim_pairs:
                cat_i = FACTOR_CATEGORIES.get(pair[0], "?")
                cat_j = FACTOR_CATEGORIES.get(pair[1], "?")
                lines.append(f"  - {pair[0]}[{cat_i}] vs {pair[1]}[{cat_j}]: {format_float(pair[2], 2)}")

        if same_dim_pairs:
            lines.append(f"选中因子中同维度高相关因子对（|corr| > {CORR_THRESHOLD_HIGH:.1f}，建议检查筛选逻辑）：")
            for pair in same_dim_pairs:
                cat_i = FACTOR_CATEGORIES.get(pair[0], "?")
                lines.append(f"  - {pair[0]}[{cat_i}] vs {pair[1]}[{cat_i}]: {format_float(pair[2], 2)}")

        if not cross_dim_pairs and not same_dim_pairs:
            lines.append(f"选中因子中无高相关因子对（所有因子相关性 < {CORR_THRESHOLD_HIGH:.1f}）")
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


def _format_exempt_note(factor_name: str, exempted_factors_map: dict[str, list[dict]], is_selected: bool) -> str:
    """格式化豁免标注文本

    Args:
        factor_name: 因子名
        exempted_factors_map: {factor_name: [exempt_detail, ...]}
        is_selected: True=入选因子, False=被剔除因子

    Returns:
        豁免标注字符串（无豁免记录时返回空字符串）

    入选因子（豁免成功）:
        ",豁免:|ic_mean|=0.017<0.03,回测强劲(夏普=5.54>1.5,单调性=0.53>0.5)"
    被剔除因子（豁免失败）:
        "未满足豁免: 夏普=1.43<1.5"
    """
    details = exempted_factors_map.get(factor_name)
    if not details:
        return ""

    if is_selected:
        # 入选因子: 只展示豁免成功的记录
        success_details = [d for d in details if d["exempted"]]
        if not success_details:
            return ""
        parts = []
        for d in success_details:
            parts.append(f"|{d['trigger']}|={d['actual']:.3f}<{d['threshold']:.3f},{d['detail']}")
        return f",豁免:{';'.join(parts)}"
    else:
        # 被剔除因子: 展示豁免失败的记录
        fail_details = [d for d in details if not d["exempted"]]
        if not fail_details:
            return ""
        # v2.25: 去重——ic_mean 和 icir 两个条件可能触发相同的豁免失败说明
        parts = list(dict.fromkeys(d["detail"] for d in fail_details))
        return ";".join(parts)


def get_factor_selection_info(
    composite_results: list[dict],
    ic_results: list[dict],
    backtest_results: list[dict],
    logger: logging.Logger,
    best_weight_method: str = "icir_weight",
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
    weight_source_note = ""  # v2.16: 权重来源说明
    exempted_factors_map: dict[str, list[dict]] = {}  # v2.23: 豁免详情（从 selection_result 提取）

    # v2.16: 根据最优权重方法选择权重数据源
    #   之前硬编码取 icir_weight 的静态权重 → Rolling ICIR 为最优时展示静态权重 → 严重误导
    #   例：tail_price_position ICIR=0.80 → 静态权重18.4%，但 Rolling ICIR 最新日=8.3%（短样本NaN回退1/n）
    #   修复：优先取最优方法的权重，Rolling ICIR 取 last_day_weights，其他方法取 meta.weights
    best_method_item = next(
        (item for item in composite_results if item.get("weight_method") == best_weight_method), None
    )

    if best_method_item:
        # 从最优方法获取权重和因子列表
        selection_result_item = best_method_item.get("selection_result")
        if selection_result_item and selection_result_item.get("selected"):
            selected_factors = selection_result_item["selected"]
        else:
            selected_factors = best_method_item.get("factor_list", [])

        if best_weight_method == "rolling_icir_weight":
            # v2.16: Rolling ICIR 使用 last_day_weights（真实最后一日动态权重）
            weight_meta = best_method_item.get("weight_meta", {})
            last_day_weights = weight_meta.get("last_day_weights", {})
            if last_day_weights:
                weights = last_day_weights
                rolling_window = weight_meta.get("window", 60)
                weight_source_note = f"权重来自Rolling ICIR加权最新日({rolling_window}日滚动窗口)"
            else:
                weights = best_method_item.get("weights", {})
                weight_source_note = "权重来自Rolling ICIR加权(动态权重未保存,回退等权)"
        else:
            weights = best_method_item.get("weights", {})
            weight_source_note = f"权重来自{get_weight_method_display(best_weight_method)}"

        selection_result = selection_result_item
        # v2.23: 提取豁免详情
        if selection_result_item:
            exempted_factors_map = selection_result_item.get("exempted_factors", {})

        factor_info = []
        for f in selected_factors:
            factor_col = FACTOR_NAME_TO_COL_MAP.get(f, f)
            # v2.21: last_day_weights 键可能是因子名而非列名（如 volume_ratio vs volume_ratio_5），
            # 先查列名，再回退因子名，避免权重查找返回 0
            weight = weights.get(factor_col, weights.get(f, 0))
            ic_item = next((r for r in ic_results if r["factor_name"] == f), None)
            # v2.23: 追加豁免标注
            exempt_note = _format_exempt_note(f, exempted_factors_map, is_selected=True)
            if ic_item:
                factor_info.append(f"{f}(ICIR={ic_item['icir']:.2f},权重={weight * 100:.1f}%{exempt_note})")
            else:
                factor_info.append(f"{f}(权重={weight * 100:.1f}%{exempt_note})")

        lines.append(f"  - 选中因子: {', '.join(factor_info)}")
        lines.append(f"  - 注：{weight_source_note}")  # v2.16: 动态权重来源说明
    else:
        # 回退：最优方法无结果时仍取 icir_weight（兼容旧版）
        for item in composite_results:
            if item["weight_method"] == "icir_weight":
                selection_result_item = item.get("selection_result")
                if selection_result_item and selection_result_item.get("selected"):
                    selected_factors = selection_result_item["selected"]
                else:
                    selected_factors = item.get("factor_list", [])
                weights = item.get("weights", {})
                selection_result = selection_result_item
                # v2.23: 提取豁免详情
                if selection_result_item:
                    exempted_factors_map = selection_result_item.get("exempted_factors", {})

                factor_info = []
                for f in selected_factors:
                    factor_col = FACTOR_NAME_TO_COL_MAP.get(f, f)
                    weight = weights.get(factor_col, 0)
                    ic_item = next((r for r in ic_results if r["factor_name"] == f), None)
                    # v2.23: 追加豁免标注
                    exempt_note = _format_exempt_note(f, exempted_factors_map, is_selected=True)
                    if ic_item:
                        factor_info.append(f"{f}(ICIR={ic_item['icir']:.2f},权重={weight * 100:.1f}%{exempt_note})")
                    else:
                        factor_info.append(f"{f}(权重={weight * 100:.1f}%{exempt_note})")

                lines.append(f"  - 选中因子: {', '.join(factor_info)}")
                lines.append("  - 注：权重来自ICIR加权方法(最优方法结果缺失,回退)")
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

    if excluded_factors:
        excluded_info = []

        # 对每个剔除因子查找原因
        for f in excluded_factors:
            if f in exclude_reasons:
                reason = exclude_reasons[f]
                logger.debug("因子 %s 剔除原因: %s", f, reason)
            else:
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

            # v2.23: 追加豁免失败说明
            exempt_note = _format_exempt_note(f, exempted_factors_map, is_selected=False)
            if exempt_note:
                reason += f"; {exempt_note}"

            excluded_info.append(f"{f}({reason})")

        # v2.22: 剔除因子拆多行显示，避免单行超长截断
        lines.append("  - 剔除因子:")
        for info in excluded_info:
            lines.append(f"    · {info}")

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


def _format_neutral_cell(ic_item: dict) -> str:
    """格式化"中性化敏感"列文本（design.md §6 / R18b）。

    显示规则：
    - enabled=False / decay_rate=None: '-' （未启用或被排除清单跳过）
    - decay_level='high' (≥30%): 'XX% ⚠' （alpha 主要来自行业 beta）
    - decay_level='low' / 'inverse' / 'undefined': 'XX%'

    Args:
        ic_item: load_ic_results 返回的单条记录, 含
            neutral_enabled / neutral_decay_rate / neutral_decay_level

    Returns:
        固定 ≤10 字符宽度的显示字符串（已含右侧高亮符号 ⚠ if any）
    """
    enabled = ic_item.get("neutral_enabled", False)
    decay_rate = ic_item.get("neutral_decay_rate")
    if not enabled or decay_rate is None:
        return "-"
    pct = f"{decay_rate * 100:.0f}%"
    level = ic_item.get("neutral_decay_level", "undefined")
    if level == "high":
        return f"{pct} ⚠"
    return pct


def _generate_neutralization_notes(ic_results: list[dict]) -> list[str]:
    """生成中性化敏感列的说明文本

    v2.24 (2026-06-20): 新增

    解释两类异常：
    1. 空值（-）：区分"未启用中性化"和"被排除清单跳过"
    2. 极端负值（|decay_rate| > 1.0，即>100%衰减）：中性化后IC方向反转

    Args:
        ic_results: IC 结果列表

    Returns:
        说明文本列表（为空则不输出说明段）
    """
    notes = []
    # 统计空值原因
    null_disabled = []  # 未启用
    null_excluded = []  # 被排除清单跳过
    extreme_negative = []  # 极端负值（方向反转）

    for item in ic_results:
        name = item.get("factor_name", "?")
        enabled = item.get("neutral_enabled", False)
        decay_rate = item.get("neutral_decay_rate")

        if not enabled or decay_rate is None:
            if not enabled:
                null_disabled.append(name)
            else:
                null_excluded.append(name)
        elif decay_rate < -1.0:
            # decay_rate < -1.0 表示中性化后IC方向反转且幅度超过原始IC
            extreme_negative.append((name, decay_rate))

    if null_disabled:
        notes.append(
            f"  '-': 中性化未启用或被排除清单跳过 — {', '.join(null_disabled[:5])}"
            + ("..." if len(null_disabled) > 5 else "")
        )

    if null_excluded:
        notes.append(
            f"  '-': 中性化已启用但 decay_rate 缺失（可能因有效天数不足无法计算） — {', '.join(null_excluded[:5])}"
            + ("..." if len(null_excluded) > 5 else "")
        )

    if extreme_negative:
        notes.append("  极端负值（<-100%）：中性化后IC方向反转，alpha可能来自行业beta而非个股alpha")
        for name, rate in extreme_negative:
            notes.append(f"    - {name}: {rate * 100:.0f}%")

    return notes


def _generate_ic_section(ic_results: list[dict], backtest_results: list[dict] | None = None) -> list[str]:
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
    lines.append("-" * 150)
    lines.append(
        f"{'因子':<20} {'定义':<50} {'IC均值':>8} {'ICIR':>6} "
        f"{'IC标准差':>8} {'有效天数':>6} {'中性化敏感':>10} {'中性化方式':>14}"
    )
    lines.append("-" * 150)

    for item in ic_results:
        factor_name = item["factor_name"]
        # 获取因子定义（如果无定义则显示空）
        factor_def = FACTOR_DEFINITIONS.get(factor_name, "")
        # 截断定义以适应表格宽度（最多50字符）
        if len(factor_def) > 50:
            factor_def = factor_def[:47] + "..."

        # 中性化敏感度列（design.md §6 / R18b）
        # - enabled=False: '-' (未启用或被排除清单跳过)
        # - decay_rate=None: '-'
        # - high (≥30%): 'XX% ⚠' 高亮 (alpha 主要来自行业 beta)
        # - low/inverse/undefined: 'XX%'
        neutral_cell = _format_neutral_cell(item)
        neutral_method = item.get("neutral_method", "-")

        lines.append(
            f"{factor_name:<20} "
            f"{factor_def:<50} "
            f"{format_float(item['ic_mean']):>8} "
            f"{format_float(item['icir']):>6} "
            f"{format_float(item['ic_std']):>8} "
            f"{item['valid_days']:>6} "
            f"{neutral_cell:>10} "
            f"{neutral_method:>14}"
        )

    lines.append("-" * 150)
    ic_order = ", ".join([f"{r['factor_name']}({r['icir']:.2f})" for r in ic_results[:5]])
    lines.append(f"IC排序(ICIR降序): {ic_order}")

    # v2.6: 问题5修复 - 异常数据说明
    lines.append("")
    lines.append("【异常数据说明】")

    # v2.11: 短样本因子警告——有效天数 < 30 的因子年化收益不可信
    MIN_RELIABLE_DAYS = 30
    short_sample_factors = [r for r in ic_results if r["valid_days"] < MIN_RELIABLE_DAYS]
    if short_sample_factors:
        lines.append(f"⚠ 短样本因子警告（有效天数<{MIN_RELIABLE_DAYS}天，年化收益不可信）:")
        for item in short_sample_factors:
            lines.append(
                f"  - {item['factor_name']}: 有效天数={item['valid_days']}天，年化收益由极少交易日推算，极不稳定"
            )
        lines.append("  说明：年化收益 = (1+总收益)^(252/N) - 1，N很小时收益率被极端放大")

    # 检查 tail_volume_shrink 有效天数异常
    tvs_item = next((r for r in ic_results if r["factor_name"] == "tail_volume_shrink"), None)
    if tvs_item and tvs_item["valid_days"] < 14:
        lines.append(f"tail_volume_shrink 有效天数={tvs_item['valid_days']}天（其他尾盘因子均为14天），数据可能缺失")

    # v2.11: overnight_ret 方向异常深度分析（问题3修复）
    or_item = next((r for r in ic_results if r["factor_name"] == "overnight_ret"), None)
    if or_item and or_item["ic_mean"] > 0:
        other_ic_means = [
            r["ic_mean"] for r in ic_results if r["factor_name"] != "overnight_ret" and r["ic_mean"] is not None
        ]
        if other_ic_means and all(ic < 0 for ic in other_ic_means[:5]):  # 检查前5个因子IC方向
            # 查找 overnight_ret 的回测数据
            bt_or = next((b for b in (backtest_results or []) if b["factor_name"] == "overnight_ret"), None)
            # v2.21: 格式化精度，避免15位小数
            or_sharpe = format_float(bt_or["long_short_sharpe"], 2) if bt_or else "N/A"
            or_mono = format_float(bt_or["monotonicity_correlation"], 2) if bt_or else "N/A"
            lines.append(f"overnight_ret IC均值={or_item['ic_mean']:.4f}为正（其他主要因子均为负），方向异常")
            lines.append("  深度分析：IC方向为正表示隔夜收益大的股票次日收益也大（正向预测），")
            lines.append("           与多数因子（IC为负=因子值大的股票次日收益小）方向相反。")
            lines.append(f"           回测夏普={or_sharpe}, 单调性={or_mono}——可能是有效的反向因子。")
            lines.append("           v2.47: 反向因子标准化值取反对齐到正向语义（综合因子值越大→预期收益越高）。")

    # v2.24: 中性化敏感列说明——极端值和空值解释
    neutral_notes = _generate_neutralization_notes(ic_results)
    if neutral_notes:
        lines.append("")
        lines.append("【中性化敏感列说明】")
        for note in neutral_notes:
            lines.append(note)

    return lines


def _generate_backtest_section(ic_results: list[dict], backtest_results: list[dict]) -> list[str]:
    """生成单因子分层回测数据汇总部分

    v2.24 (2026-06-20): 短样本因子追加⚠标记

    Args:
        ic_results: IC 结果列表（用于排序 + valid_days 短样本标记）
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

    # v2.24: 构建 valid_days 映射，用于短样本标记
    valid_days_map = {r["factor_name"]: r.get("valid_days", 999) for r in ic_results}
    MIN_RELIABLE_DAYS = 30

    # 按 IC 结果顺序排序回测结果
    factor_order_map = {r["factor_name"]: i for i, r in enumerate(ic_results)}
    backtest_sorted = sorted(backtest_results, key=lambda x: factor_order_map.get(x["factor_name"], 999))

    for item in backtest_sorted:
        factor_name = item["factor_name"]
        # v2.24: 短样本因子追加⚠标记
        days = valid_days_map.get(factor_name, 999)
        mark = " ⚠短样本" if days < MIN_RELIABLE_DAYS else ""
        lines.append(
            f"{factor_name:<18} "
            f"{format_percentage(item['long_short_return_annual']):>12} "
            f"{format_float(item['long_short_sharpe'], 2):>8} "
            f"{format_float(item['monotonicity_correlation']):>10} "
            f"{item['monotonicity_symbol']:>10}{mark}"
        )

    lines.append("-" * 70)

    # v2.24: 短样本标记说明
    short_sample_in_table = [name for name, days in valid_days_map.items() if days < MIN_RELIABLE_DAYS]
    if short_sample_in_table:
        lines.append("⚠ 短样本标记: 年化收益由极少交易日推算，极不稳定（有效天数<30天）")

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

    # v2.12: 方向处理说明——overnight_ret 取反使用
    # 从第一个 composite_result 的 config 中读取 flipped_factors
    flipped_factors = []
    if composite_results:
        first_item = composite_results[0]
        flipped_factors = first_item.get("flipped_factors", [])

    if flipped_factors:
        lines.append("")
        lines.append("【方向处理说明】")
        lines.append(f"  反向因子（IC均值<0）标准化值已取反，对齐到正向语义：{flipped_factors}")
        for f in flipped_factors:
            lines.append(f"  - {f}: IC均值<0(反向因子)，综合因子计算时标准化值取反，做多因子值小的股票")
        lines.append("  说明：v2.47 综合因子方向=positive（正向），所有因子对齐后值大=好信号（高 composite=选中）")

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
    lines.append(
        f"计算日期: {weight_result.get('meta', {}).get('created_at', 'N/A')[:10]}"
    )  # v2.6: 问题3修复 - 明确为计算日期

    # v2.7→v2.17: 评分说明重构——展示所有方法的完整评分明细，而非只对比IC vs ICIR
    #   旧逻辑：最优方法为Rolling ICIR时，评分说明只对比IC和ICIR的换手率 → 逻辑跳跃
    #   新逻辑：展示所有方法的各维度归一化得分表，让读者一目了然
    ranking = weight_result.get("ranking", [])
    metric_configs = weight_result.get("metric_configs", {})

    if ranking and metric_configs:
        lines.append("")
        lines.append("【评分明细】")
        lines.append("各方法各维度归一化得分（Min-Max归一化，逆向指标已反转）")
        # v2.24: 说明 Min-Max 归一化的放大效应
        lines.append("  注: Min-Max归一化将原始值映射到[0,1]，方法间微小差异可能被放大为较大得分差距")
        lines.append("       请结合括号内原始值判断实际差异，归一化得分仅反映相对排名")

        # 构建维度展示名称映射
        metric_display_names = {
            "long_short_return_annual": "多空年化收益",
            "long_short_sharpe": "多空夏普比率",
            "long_return_annual": "多头年化收益",
            "long_sharpe": "多头夏普比率",
            "monotonicity_abs": "单调性",
            "long_short_net_daily": "成本后日收益",
            "turnover_long_avg": "多头换手率(逆向)",
            "turnover_short_avg": "空头换手率(逆向)",
            "max_drawdown": "最大回撤(逆向)",
        }

        # 确定展示维度（按 metric_configs 的顺序）
        display_metrics = list(metric_configs.keys())
        # v2.17: 对每个维度添加方向说明
        metric_with_direction = []
        for m in display_metrics:
            direction = metric_configs[m].get("direction", "higher_better")
            display_name = metric_display_names.get(m, m)
            if direction == "lower_better":
                metric_with_direction.append(f"{display_name}↓")
            else:
                metric_with_direction.append(f"{display_name}")

        # 每个方法生成一行评分明细
        for item in sorted(ranking, key=lambda x: x.get("composite_score", 0), reverse=True):
            method_display = get_weight_method_display(item.get("method", "N/A"))
            composite_score = item.get("composite_score", 0)
            metric_scores = item.get("metric_scores", {})
            is_best = item.get("method") == best_method

            # 格式化各维度得分
            score_parts = []
            for m in display_metrics:
                score = metric_scores.get(m, 0)
                score_parts.append(f"{score:.2f}")

            best_marker = " ★最优" if is_best else ""
            lines.append(f"  {method_display:<20} 综合={composite_score:.4f}{best_marker}")
            # v2.17: 展示各维度得分明细
            for i, m in enumerate(display_metrics):
                score = metric_scores.get(m, 0)
                raw = item.get("raw_values", {}).get(m, None)
                direction = metric_configs[m].get("direction", "higher_better")
                display_name = metric_display_names.get(m, m)
                # v2.24: 成本后日收益值极小(~0.003)，4位小数不足以区分方法间差异，提升到6位
                raw_decimals = 6 if m == "long_short_net_daily" else 4
                raw_str = f"(原始值={raw:.{raw_decimals}f})" if raw is not None else ""
                best_star = " ★" if is_best and score >= 0.9 else ""
                lines.append(f"    - {display_name}: {score:.3f} {raw_str}{best_star}")

        # v2.17: 最优方法突出说明
        best_rank = next((r for r in ranking if r.get("method") == best_method), None)
        if best_rank and best_method == "rolling_icir_weight":
            best_ms = best_rank.get("metric_scores", {})
            best_rv = best_rank.get("raw_values", {})
            # Rolling ICIR 换手率得分较低时给出说明
            turnover_long = best_ms.get("turnover_long_avg", 0)
            turnover_short = best_ms.get("turnover_short_avg", 0)
            if turnover_long < 0.5 or turnover_short < 0.5:
                lines.append("")
                lines.append("  ★ Rolling ICIR加权换手率得分较低但综合得分最高：")
                # v2.24: 动态列举得分≥0.9的维度，避免硬编码错误（单调性0.6≠接近1.0）
                high_score_dims = []
                for m_key, m_score in best_ms.items():
                    if m_key in ("turnover_long_avg", "turnover_short_avg"):
                        continue  # 换手率已单独说明
                    if m_score >= 0.9:
                        high_score_dims.append(metric_display_names.get(m_key, m_key))
                high_score_str = "/".join(high_score_dims) if high_score_dims else "多数维度"
                lines.append(
                    f"    {high_score_str}得分接近1.0，换手率得分({turnover_long:.2f}/{turnover_short:.2f})虽低"
                )
                lines.append("    但9维度等权加权后综合得分仍最高，换手率惩罚不足以抵消其他维度优势")
                lines.append(
                    f"    原始多头换手率={best_rv.get('turnover_long_avg', 0):.4f}, 空头换手率={best_rv.get('turnover_short_avg', 0):.4f}"
                )

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


def _detect_duplicate_zscores(top_stocks: list[dict], min_duplicates: int = 3) -> list[str]:
    """检测 Top N 股票中同一因子 z-score 完全相同的情况

    v2.24 (2026-06-20): 新增

    相同 z-score 的原因：
    1. 原始值相同（如 tail_price_position=0.0=收盘最低价）→ z-score 相同（数学正确）
    2. Winsorize ±3σ 截断 → z=±3.00 多次出现

    Args:
        top_stocks: 选中的股票列表
        min_duplicates: 最少重复次数才报告（默认3次）

    Returns:
        说明文本列表，每项描述一个因子的重复情况
    """
    from collections import Counter

    # 收集每个因子的 z-score
    factor_zscores: dict[str, list[float]] = {}
    for stock in top_stocks:
        factor_values_std = stock.get("factor_values_std", {})
        for col, z_score in factor_values_std.items():
            if z_score is not None:
                factor_zscores.setdefault(col, []).append(round(z_score, 4))

    notes = []
    for col, scores in factor_zscores.items():
        score_counts = Counter(scores)
        for score, count in score_counts.items():
            if count >= min_duplicates:
                # 判断是否为截断值
                is_clipped = abs(score) >= 2.99
                reason = (
                    "Winsorize ±3σ 截断（多只股票极端值被截断为同一值）"
                    if is_clipped
                    else "原始值相同（如尾盘因子=0.0=收盘最低价，不同股票原始值一致→z-score一致）"
                )
                notes.append(f"{col}: z-score={score:.2f} 出现{count}次 — {reason}")

    return notes


def _compute_factor_concentration(
    top_stocks: list[dict],
    comp_weights: dict[str, float],
    *,
    concentration_threshold: float = 0.5,
    relative_ratio_threshold: float = 2.0,
) -> list[dict]:
    """检测 Top N 股票中因子贡献集中度过高的因子。

    双重检测条件（满足任一即报警）：
    1. 绝对集中度：因子平均绝对贡献占综合因子平均绝对值 > concentration_threshold（50%）
       → 表面多因子综合实际近乎单因子选股
    2. 相对集中度：实际贡献占比 / 名义权重 > relative_ratio_threshold（2.0x）
       → 因子实际影响力远超名义权重，z-score 极端化导致权重失真

    典型场景：tail_price_position 原始值=0.0（收盘=尾盘最低价）导致
    z-score≈-2.45，名义权重 19.8% 但实际贡献占比 41%（2.07x）。

    Args:
        top_stocks: 选中的股票列表，每项含 factor_values_std 和 composite_value
        comp_weights: {factor_col: weight} 权重字典
        concentration_threshold: 绝对贡献占比阈值，默认 0.5（50%）
        relative_ratio_threshold: 相对贡献倍数阈值，默认 2.0

    Returns:
        集中度异常因子列表（按集中度降序），每项含 factor_name /
        factor_col / weight / avg_abs_contribution / concentration_ratio /
        relative_ratio
    """
    if not top_stocks or not comp_weights:
        return []

    avg_abs_composite = sum(abs(s.get("composite_value", 0)) for s in top_stocks) / len(top_stocks)
    if avg_abs_composite < 1e-9:
        return []

    anomalies = []
    for factor_col, weight in comp_weights.items():
        abs_contributions = []
        for stock in top_stocks:
            std_val = stock.get("factor_values_std", {}).get(factor_col)
            if std_val is not None:
                abs_contributions.append(abs(weight * std_val))
        if not abs_contributions:
            continue
        avg_abs_contribution = sum(abs_contributions) / len(abs_contributions)
        concentration = avg_abs_contribution / avg_abs_composite
        relative_ratio = concentration / weight if weight > 1e-9 else float("inf")
        if concentration >= concentration_threshold or relative_ratio >= relative_ratio_threshold:
            anomalies.append(
                {
                    "factor_name": COL_TO_FACTOR_NAME_MAP.get(factor_col, factor_col),
                    "factor_col": factor_col,
                    "weight": weight,
                    "avg_abs_contribution": avg_abs_contribution,
                    "concentration_ratio": concentration,
                    "relative_ratio": relative_ratio,
                }
            )

    return sorted(anomalies, key=lambda x: x["concentration_ratio"], reverse=True)


def _generate_lr_training_status() -> list[str]:
    """v3.10: 读取 lr_training_data 状态, 展示训练数据积累进度.

    展示内容:
    - 训练数据天数 / 目标 90 天
    - forward_return_1d 已补写比例
    - 各 weight_method 的天数分布
    - 如果 ≥90 天, 尝试运行 calibrate_lr_filter 并展示 OOS AUC
    """
    import pyarrow.dataset as ds

    logger = setup_logger()
    lines: list[str] = []
    lr_dir = PROJECT_ROOT / "comprehensive_factor" / "result" / "lr_training_data"
    if not lr_dir.exists():
        lines.append("【LR 训练数据状态】")
        lines.append("  训练数据: 尚未积累 (lr_training_data 目录不存在)")
        lines.append("  过滤状态: 未启用 (需积累 90 天)")
        return lines

    # 读取所有分区
    try:
        dataset = ds.dataset(lr_dir, partitioning="hive")
        df = dataset.to_table(columns=["forward_return_1d", "selection_date", "weight_method"]).to_pandas()
    except Exception:
        lines.append("【LR 训练数据状态】")
        lines.append("  训练数据: 读取失败")
        return lines

    if df.empty:
        lines.append("【LR 训练数据状态】")
        lines.append("  训练数据: 空")
        return lines

    lines.append("【LR 训练数据状态 (v3.10)】")

    # 按 weight_method 统计
    for wm in sorted(df["weight_method"].unique()):
        wm_df = df[df["weight_method"] == wm]
        n_days = wm_df["selection_date"].nunique()
        n_rows = len(wm_df)
        n_with_ret = wm_df["forward_return_1d"].notna().sum()
        pct_ret = n_with_ret / n_rows * 100 if n_rows > 0 else 0

        status = "✓ 可训练" if n_days >= 90 else f"积累中 ({n_days}/90 天)"
        lines.append(f"  {wm}: {n_days} 天, {n_rows} 行, T+1 已补写 {pct_ret:.0f}% [{status}]")

    # 总体状态
    total_days = df.groupby("weight_method")["selection_date"].nunique().max()
    if total_days >= 90:
        lines.append("  过滤状态: ✓ 可启用 (set enable_overheat_filter=True)")
        # 尝试训练并展示 OOS AUC
        try:
            from comprehensive_factor.stock_selector import StockSelectorConfig, calibrate_lr_filter

            config = StockSelectorConfig()
            for wm in sorted(df["weight_method"].unique()):
                model, scaler, features, auc = calibrate_lr_filter(
                    lr_dir,
                    weight_method=wm,
                    top_n=config.top_n,
                    n_features=config.lr_top_features,
                    train_window=config.lr_train_window,
                    min_oos_auc=config.lr_min_oos_auc,
                    min_training_days=config.lr_min_training_days,
                    filter_quantile=config.lr_filter_quantile,
                    logger=logger,
                )
                if model is not None:
                    lines.append(f"  {wm} OOS AUC: {auc:.3f} ✓ (≥{config.lr_min_oos_auc}, {len(features)} 特征)")
                else:
                    lines.append(f"  {wm} OOS AUC: {auc:.3f} ✗ (< {config.lr_min_oos_auc}, 跳过过滤)")
        except Exception as e:
            lines.append(f"  (LR 训练验证失败: {e})")
    else:
        remaining = 90 - total_days
        lines.append(f"  过滤状态: 未启用 (还需 {remaining} 天)")

    return lines


def _generate_stock_selection_section(
    stock_result: dict | None,
    comp_weights: dict[str, float] | None = None,
    data_freshness: list[dict] | None = None,
    stock_name_map: dict[str, str] | None = None,
) -> list[str]:
    """生成股票选股结果展示部分

    v2.2 (2026-06-03): 新增股票选股结果展示
    v2.24 (2026-06-20): 新增 data_freshness 参数，动态标注选股数据日期
    v2.26 (2026-06-23): 新增 stock_name_map 参数，在股票代码后展示股票名称

    Args:
        stock_result: 股票选股结果字典（可为 None）
        comp_weights: 综合因子权重字典
        data_freshness: 数据完整性检查结果（来自 check_data_freshness）
        stock_name_map: {code: name} 映射（来自 load_stock_name_map）；
                        None 或缺失键时回退为"--"，不展示名称

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
    # v2.24: 动态标注数据日期——对比 expected_date(T-1) 与 actual_date 判断数据延迟
    selection_date = meta.get("selection_date", "N/A")
    data_date_note = "（使用T-1数据）"  # 默认标注
    if data_freshness:
        main_source = next((s for s in data_freshness if "factor_ic_data" in s.get("source", "")), None)
        if main_source:
            expected_date = main_source.get("expected_date", "")
            actual_date = main_source.get("actual_date", "")
            if expected_date and actual_date and actual_date != expected_date:
                data_date_note = f"（数据滞后，截至{actual_date}，T-1应为{expected_date}）"
            elif actual_date and actual_date == expected_date:
                data_date_note = "（使用T-1数据）"
    lines.append(f"选股日期: {selection_date}{data_date_note}")
    lines.append(f"最优权重方法: {get_weight_method_display(meta.get('weight_method', 'N/A'))}")
    lines.append(f"权重综合得分: {format_float(meta.get('composite_score', 0), 4)}")
    lines.append(
        f"因子方向: {meta.get('factor_direction', 'N/A')}（{'反向' if meta.get('factor_direction') == 'negative' else '正向'}）"
    )
    lines.append(f"选出股票数: {meta.get('top_n', 0)} 只（共 {meta.get('stocks_on_date', 0)} 只股票）")

    # v2.18: 振幅过滤信息展示
    min_amplitude = meta.get("min_amplitude", 0)
    excluded_by_amplitude = meta.get("excluded_by_amplitude", 0)
    if min_amplitude > 0:
        lines.append(
            f"振幅过滤: 排除 {excluded_by_amplitude} 只股票（振幅 < {min_amplitude * 100:.2f}%，不可交易的一字板涨停股）"
        )

    # v2.22: 覆盖率过滤信息展示
    excluded_by_coverage = meta.get("excluded_by_coverage", 0)
    min_weight_coverage = meta.get("min_weight_coverage", 0)
    if min_weight_coverage > 0:
        lines.append(
            f"覆盖率过滤: 排除 {excluded_by_coverage} 只股票（覆盖率 < {min_weight_coverage * 100:.0f}%，缺失高权重因子导致综合因子值不可信）"
        )

    # v2.12 / v2.47: 方向处理说明——展示取反因子（v2.47 含义反转：现在是 IC<0 因子被翻到正向）
    flipped_factors = meta.get("flipped_factors", [])
    if flipped_factors:
        lines.append("")
        lines.append("【方向处理说明】")
        lines.append(f"  反向因子标准化值已取反，对齐到正向语义：{flipped_factors}")
        for f in flipped_factors:
            lines.append(
                f"  - {f}: IC均值<0(反向因子)，综合因子计算时标准化值取反（做多因子值小的股票做空因子值大的股票）"
            )
        lines.append("  说明：v2.47 选股方向=positive（正向），因子值越大 → 综合因子越大 → 被选为Top股票")

    lines.append("")

    # === v3.10: Bottom90 选股轨迹展示 ===
    # v3.10: LR 过滤需积累 90 天训练数据, 当前冷启动阶段不过滤.
    # 展示: Stage 1 (composite 降序 Top 30, 候选池记录) + Bottom90 原始 + 最终短名单.
    stage1_top = stock_result.get("stage1_top", []) or []
    stage1_bottom = stock_result.get("stage1_bottom", []) or []

    # v3.10: LR 训练数据状态展示
    lr_status_lines = _generate_lr_training_status()
    if lr_status_lines:
        lines.extend(lr_status_lines)
        lines.append("")

    if stage1_top or stage1_bottom:
        excluded_by_overheat = meta.get("excluded_by_overheat", 0)
        filter_status = (
            f"LR 过滤排除 {excluded_by_overheat} 只" if excluded_by_overheat else "LR 过滤未启用 (积累训练数据中)"
        )
        lines.append("【选股轨迹 (v3.10: Bottom90 LR 过滤)】")
        lines.append(f"  Stage 1: 综合因子值降序取 Top {meta.get('stage1_pool_size', 200)} 作为候选池 (基础设施)")
        lines.append(
            f"  Bottom90: 综合因子值升序取最低 {meta.get('top_n', 0) * 3} → {filter_status} → Top {meta.get('top_n', 0)} 最终短名单"
        )
        lines.append("  说明: 最终短名单按综合因子值升序(composite 最低=弱势股端), LR 模型预测 T+1 跌概率最高的排除.")
        lines.append("")

        # Stage 1 简表: composite 降序 Top 30 (弱势股端, 仅供记录)
        if stage1_top:
            lines.append(f"【Stage 1: 综合因子值 Top {len(stage1_top)} (composite 降序, 弱势股端)】")
            lines.append(f"{'排名':>4} {'股票代码':<10} {'股票名称':<8} {'综合因子值':>12}")
            lines.append("-" * 50)
            for item in stage1_top:
                rank = item.get("rank", 0)
                code = item.get("code", "N/A")
                name = (stock_name_map or {}).get(code, "--")
                cv = item.get("composite_value", 0)
                lines.append(f"{rank:>4} {code:<10} {name:<8} {format_float(cv, 3):>12}")
            lines.append("-" * 50)
            lines.append("")

        # Bottom90 原始简表 (LR 过滤前)
        if stage1_bottom:
            excluded_by_overheat = meta.get("excluded_by_overheat", 0)
            overheat_note = f" (LR 过滤排除 {excluded_by_overheat} 只)" if excluded_by_overheat else ""
            lines.append(
                f"【Bottom {len(stage1_bottom)}: 综合因子值最低 (composite 升序, 弱势股端, LR 过滤前{overheat_note})】"
            )
            lines.append(f"{'排名':>4} {'股票代码':<10} {'股票名称':<8} {'综合因子值':>12}")
            lines.append("-" * 50)
            for item in stage1_bottom:
                rank = item.get("rank", 0)
                code = item.get("code", "N/A")
                name = (stock_name_map or {}).get(code, "--")
                cv = item.get("composite_value", 0)
                lines.append(f"{rank:>4} {code:<10} {name:<8} {format_float(cv, 3):>12}")
            lines.append("-" * 50)
            lines.append("")

        lines.append(f"【最终短名单 Top {meta.get('top_n', 0)} (Bottom90 LR 过滤后)】")
        lines.append("")

    # Top N 股票表格 (v3.9: 即 Bottom30 过热过滤后短名单)
    # v2.42 (designs/feat_shortlist_top30_v1.md §2.2): 拆分 Top 10 详表 + 11~N 简表
    #   - Top 1~10: 详表, 展示全部因子 z-score (保留 v2.14 信息密度)
    #   - Top 11~N: 简表, 展示主导前 3 因子贡献占比 (避免 30 行 × 15 因子冗长)
    if top_stocks:
        DETAIL_LIMIT = 10  # v2.42: Top 10 详表边界
        detail_stocks = top_stocks[:DETAIL_LIMIT]
        brief_stocks = top_stocks[DETAIL_LIMIT:]

        # === Top 1~10 详表 ===
        detail_title = (
            f"【Top {len(detail_stocks)} 详表（重点观察）】" if brief_stocks else f"【Top {len(detail_stocks)} 股票】"
        )
        lines.append(detail_title)
        # v2.12: 增加覆盖率列
        # v2.14: 因子值详情改为显示标准化值(z-score)，而非原始值
        # v2.15 / v2.47: 反向因子取反后z-score加*标记，消除解读歧义
        header_note = "  * = 已取反对齐到正向语义" if flipped_factors else ""
        lines.append(
            f"{'排名':>4} {'股票代码':<10} {'股票名称':<8} {'综合因子值':>12} {'覆盖率':>6} {'因子标准化值(z-score)':<40}{header_note}"
        )
        lines.append("-" * 70)

        for item in detail_stocks:
            rank = item.get("rank", 0)
            code = item.get("code", "N/A")
            # v2.26: 股票名称从 stock_name_map 查找，缺失时回退"--"（不阻塞主报告）
            name = (stock_name_map or {}).get(code, "--")
            composite_value = item.get("composite_value", 0)
            weight_coverage = item.get("weight_coverage", 1.0)  # v2.12: 因子覆盖率

            # 因子值详情（全部显示）
            # v2.13: 区分"缺失(NaN)"和"真实≈0"——tail_price_volume_intensity等因子原始值为0是真实数据而非缺失
            # v2.14: 显示标准化值（z-score）而非原始值——原始值极端误导（如 momentum_strength=-9.08→z=-2.65）
            #   综合因子排名由标准化值驱动，原始值仅作参考
            factor_values = item.get("factor_values", {})
            factor_values_std = item.get("factor_values_std", {})  # v1.3b: 标准化值
            factor_str = ""
            if factor_values_std:
                # 优先显示标准化值（z-score），更准确反映排名驱动因素
                parts = []
                # v2.15: flipped_factors 集合用于标记取反因子
                flipped_set = set(flipped_factors) if flipped_factors else set()
                for k, v_std in factor_values_std.items():
                    factor_name = COL_TO_FACTOR_NAME_MAP.get(k, k)
                    # v2.15: 取反因子名后加*标记，消除解读歧义（z-score已取反≠原始z-score）
                    display_name = f"{factor_name}*" if factor_name in flipped_set else factor_name
                    if v_std is None:
                        # v2.21: z-score 缺失统一显示"缺失(NaN)"，不再区分原始值是否≈0
                        parts.append(f"{display_name}=缺失(NaN)")
                    elif abs(v_std) < 0.001:
                        # v2.21: z-score≈0 统一显示"0.00"，不再区分原始值是否≈0
                        parts.append(f"{display_name}=0.00")
                    else:
                        # 正常标准化值（z-score），保留2位小数
                        # Winsorize ±3σ 截断后范围 [-3.00, 3.00]
                        # v2.15: 取反因子用 display_name 带*标记
                        parts.append(f"{display_name}={format_float(v_std, 2)}")
                factor_str = ", ".join(parts)  # 显示全部因子标准化值
            elif factor_values:
                # 回退：无标准化值时显示原始值（兼容旧版 JSON）
                parts = []
                for k, v in factor_values.items():
                    factor_name = COL_TO_FACTOR_NAME_MAP.get(k, k)
                    if v is None:
                        parts.append(f"{factor_name}=缺失(NaN)")
                    elif abs(v) < 0.001:
                        # v2.21: 统一显示"0.00"，不再使用"≈0(真实)"标签
                        parts.append(f"{factor_name}=0.00")
                    else:
                        parts.append(f"{factor_name}={format_float(v, 2)}")
                factor_str = ", ".join(parts)
            else:
                factor_str = "无因子值"

            coverage_str = f"{weight_coverage * 100:.0f}%" if weight_coverage < 1 else "100%"
            lines.append(
                f"{rank:>4} {code:<10} {name:<8} {format_float(composite_value, 3):>12} {coverage_str:>6} {factor_str}"
            )

        lines.append("-" * 70)

        # === Top 11~N 简表 (v2.42: designs/feat_shortlist_top30_v1.md §2.2) ===
        # 主导前 3 因子: 按 |w × z| 贡献占比排序, 展示备选池信号来源
        if brief_stocks:
            lines.append("")
            lines.append(f"【短名单 11~{len(top_stocks)} 简表（备选池）】")
            lines.append(
                f"{'排名':>4} {'股票代码':<10} {'股票名称':<8} {'综合因子值':>12} {'覆盖率':>6} {'主导前 3 因子（贡献占比）':<40}"
            )
            lines.append("-" * 70)
            flipped_set = set(flipped_factors) if flipped_factors else set()
            for item in brief_stocks:
                rank = item.get("rank", 0)
                code = item.get("code", "N/A")
                # v2.26: 短名单简表展示股票名称
                name = (stock_name_map or {}).get(code, "--")
                composite_value = item.get("composite_value", 0)
                weight_coverage = item.get("weight_coverage", 1.0)
                factor_values_std = item.get("factor_values_std", {}) or {}

                # 计算主导前 3 因子: 按 |w × z| 占总贡献的比例
                dominant_str = "(无主导因子)"
                if comp_weights and factor_values_std:
                    contributions = {}
                    for col, w in comp_weights.items():
                        # comp_weights 用列名做 key, factor_values_std 也是列名 (v1.4)
                        z = factor_values_std.get(col)
                        if z is None or w is None:
                            continue
                        contributions[col] = abs(float(w) * float(z))
                    total = sum(contributions.values())
                    if total > 0:
                        ratios = sorted(
                            ((c, v / total) for c, v in contributions.items()),
                            key=lambda kv: -kv[1],
                        )[:3]
                        parts = []
                        for col, ratio in ratios:
                            factor_name = COL_TO_FACTOR_NAME_MAP.get(col, col)
                            display = f"{factor_name}*" if factor_name in flipped_set else factor_name
                            parts.append(f"{display}({ratio * 100:.0f}%)")
                        dominant_str = ", ".join(parts)

                coverage_str = f"{weight_coverage * 100:.0f}%" if weight_coverage < 1 else "100%"
                lines.append(
                    f"{rank:>4} {code:<10} {name:<8} {format_float(composite_value, 3):>12} {coverage_str:>6} {dominant_str}"
                )
            lines.append("-" * 70)
            lines.append(
                f"说明: Top 1~10 为 composite 极值区（高信号 + 高波动）, Top 11~{len(top_stocks)} 为短名单备选池。"
            )
            lines.append("最终持仓 3~5 只由人工决断（参考 PROJECT.md 战略目标：量化辅助 + 人工决断）。")

            # v2.43: 决策卡片块 (designs/feat_decision_card_v1.md)
            # 5 维客观字段叠加在短名单上, 辅助人工决断 3~5 只持仓
            has_card = any(s.get("decision_card") for s in top_stocks)
            if has_card:
                lines.append("")
                lines.append("【决策卡片 (人工决断辅助, 5 维客观字段)】")
                lines.append(
                    "  排名 股票代码  股票名称   D1 涨幅档/振幅档/区间位置          | D2 过热 | D3 趋势 | D4 历史"
                )
                lines.append("-" * 120)
                for s in top_stocks:
                    card = s.get("decision_card")
                    if not card:
                        continue
                    d1 = card.get("d1_classification", {})
                    d2 = card.get("d2_risk", {})
                    d3 = card.get("d3_trend", {})
                    d4 = card.get("d4_history", {})

                    d1_str = (
                        f"{d1.get('return_5d_bucket', 'n/a')} / "
                        f"{d1.get('amplitude_bucket', 'n/a')} / "
                        f"{d1.get('close_position_5d', 'n/a')}"
                    )
                    # D2 过热风险 (0~3), 命中详情标注
                    d2_flags = []
                    if d2.get("high_turnover"):
                        d2_flags.append("高换手")
                    if d2.get("high_volume_ratio"):
                        d2_flags.append("放量")
                    if d2.get("extreme_amplitude"):
                        d2_flags.append("极端振幅")
                    d2_str = f"{d2.get('warning_count', 0)}/3"
                    if d2_flags:
                        d2_str += f"({','.join(d2_flags)})"

                    # D3 趋势确认 (0~3), raw_signals_available=False 显示 n/a
                    d3_str = "n/a" if not d3.get("raw_signals_available", False) else f"{d3.get('hit_count', 0)}/3"

                    # D4 历史 — 本期 null
                    times = d4.get("times_in_top30_last_60d")
                    d4_str = "n/a" if times is None else f"{times}次"

                    lines.append(
                        f"  {s['rank']:>3} {s['code']:<8} {(stock_name_map or {}).get(s['code'], '--'):<8} {d1_str:<34}  | {d2_str:<14} | {d3_str:<6} | {d4_str}"
                    )
                lines.append("-" * 120)
                lines.append("说明:")
                lines.append("  D1 客观分类: 纯阈值分桶（涨幅/振幅/收盘价在近 5 日区间位置）, 不带叙事词。")
                lines.append("  D2 过热风险: 高换手(截面70%+) / 放量(volume_ratio_5>1.5) / 极端振幅(<1% 或 >12%)。")
                lines.append("  D3 趋势确认: 近高比例(>0.95) + 布林上轨(>1.0) + RSI超买(>70), 0~3 个命中。")
                lines.append("  D4 历史画像: 本期为 n/a (需历史归档机制, 独立 design 待启动)。")
                lines.append("")
                lines.append("【D5 人工核查清单 (固定模板, 适用每只候选股票)】")
                for i, item in enumerate(CHECKLIST_D5, 1):
                    lines.append(f"  {i}. {item}")

        # v2.19: 因子贡献集中度检测
        if comp_weights:
            concentration_anomalies = _compute_factor_concentration(top_stocks, comp_weights)
            if concentration_anomalies:
                lines.append("")
                lines.append("⚠ 因子贡献集中度警告:")
                for a in concentration_anomalies:
                    lines.append(
                        f"  - {a['factor_name']}: 名义权重={a['weight']:.1%}，"
                        f"实际贡献占比={a['concentration_ratio']:.1%}"
                        f"（{a['relative_ratio']:.1f}x名义权重）"
                    )
                lines.append(
                    "    说明: 该因子的实际贡献远超名义权重，"
                    "可能原因: 因子原始值集中在边界(如0.0)导致z-score极端化，"
                    "有效分散化不足"
                )

        # v2.24: 相同 z-score 检测——多只股票同一因子 z-score 完全相同
        # 原因：原始值相同（如尾盘因子=0.0=收盘最低价）→ z-score 相同（数学正确）
        # 或 Winsorize ±3σ 截断（z=-3.00 或 z=3.00 多次出现）
        dup_notes = _detect_duplicate_zscores(top_stocks)
        if dup_notes:
            lines.append("")
            lines.append("ℹ 相同z-score说明:")
            for note in dup_notes:
                lines.append(f"  - {note}")

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


def _detect_weight_rank_anomalies(
    selected_factors: list[str],
    factor_data: list[dict],
    comp_weights: dict[str, float],
    *,
    rank_drop_threshold: int | None = None,
) -> list[dict]:
    """检测 Rolling ICIR 权重排名与全样本 ICIR 排名显著不一致的因子。

    仅对 Rolling ICIR 加权有意义：全样本 ICIR 高但权重极低，
    说明该因子近 60 日 IC 表现急剧恶化（滚动 ICIR 动态降权）。
    rank_drop = weight_rank - icir_rank（正值表示权重排名低于 ICIR 排名）。

    Args:
        selected_factors: 选中因子名列表
        factor_data: 合并后的因子数据（含 icir 字段）
        comp_weights: {factor_col: weight} 权重字典
        rank_drop_threshold: 排名下降位数阈值，None 时按 max(2, N//3) 自适应

    Returns:
        异常因子列表，每项含 factor_name / icir / icir_rank /
        weight / weight_rank / rank_drop
    """
    n = len(selected_factors)
    if n < 3:
        return []

    if rank_drop_threshold is None:
        rank_drop_threshold = max(2, n // 4)

    # 收集每个因子的 ICIR 和权重
    factor_stats = []
    for factor_name in selected_factors:
        factor_item = next((f for f in factor_data if f["factor_name"] == factor_name), None)
        if not factor_item:
            continue
        icir = factor_item.get("icir", 0)
        factor_col = FACTOR_NAME_TO_COL_MAP.get(factor_name, factor_name)
        # v2.21: last_day_weights 键可能是因子名而非列名，先查列名再回退因子名
        weight = comp_weights.get(factor_col, comp_weights.get(factor_name, 0))
        factor_stats.append(
            {
                "factor_name": factor_name,
                "icir": icir,
                "weight": weight,
            }
        )

    if len(factor_stats) < 3:
        return []

    # 按 |ICIR| 降序排名（rank 1 = 最强 ICIR）
    by_icir = sorted(factor_stats, key=lambda x: abs(x["icir"]), reverse=True)
    for i, item in enumerate(by_icir):
        item["icir_rank"] = i + 1

    # 按权重降序排名（rank 1 = 最高权重）
    by_weight = sorted(factor_stats, key=lambda x: x["weight"], reverse=True)
    for i, item in enumerate(by_weight):
        item["weight_rank"] = i + 1

    # 检测排名下降（权重排名远低于 ICIR 排名）
    anomalies = []
    for item in factor_stats:
        rank_drop = item["weight_rank"] - item["icir_rank"]
        if rank_drop >= rank_drop_threshold:
            item["rank_drop"] = rank_drop
            anomalies.append(item)

    return anomalies


def _generate_comparison_section(
    factor_data: list[dict], composite_results: list[dict], best_weight_method: str = "icir_weight"
) -> list[str]:
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

    # v2.16: 从最优方法获取选中因子列表和权重
    # 优先使用 selection_result.selected（反映实际筛选结果），回退到 factor_list
    selected_factors = []
    comp_weights = {}  # v2.16: 当前最优方法的权重字典

    best_item = next((item for item in composite_results if item.get("weight_method") == best_weight_method), None)

    if best_item:
        sel_res = best_item.get("selection_result")
        if sel_res and sel_res.get("selected"):
            selected_factors = sel_res["selected"]
        else:
            selected_factors = best_item.get("factor_list", [])

        # v2.16: Rolling ICIR 使用 last_day_weights，其他方法使用 meta.weights
        if best_weight_method == "rolling_icir_weight":
            weight_meta = best_item.get("weight_meta", {})
            last_day_weights = weight_meta.get("last_day_weights", {})
            comp_weights = last_day_weights if last_day_weights else best_item.get("weights", {})
        else:
            comp_weights = best_item.get("weights", {})
    else:
        # 回退：取 icir_weight
        for item in composite_results:
            if item["weight_method"] == "icir_weight":
                sel_res = item.get("selection_result")
                if sel_res and sel_res.get("selected"):
                    selected_factors = sel_res["selected"]
                else:
                    selected_factors = item.get("factor_list", [])
                comp_weights = item.get("weights", {})
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
    # v2.16: 权重来源说明——根据最优方法动态生成
    if best_weight_method == "rolling_icir_weight":
        lines.append("注：权重来自Rolling ICIR加权最新日（动态权重，每日变化）")
    else:
        lines.append(f"注：权重来自{get_weight_method_display(best_weight_method)}")
    lines.append("-" * 70)

    # 展示选中的单因子
    for factor_name in selected_factors:
        factor_item = next((f for f in factor_data if f["factor_name"] == factor_name), None)
        if factor_item:
            # v2.16: 从最优方法的权重获取（而非硬编码 icir_weight）
            factor_col = FACTOR_NAME_TO_COL_MAP.get(factor_name, factor_name)
            # v2.21: last_day_weights 键可能是因子名而非列名，先查列名再回退因子名
            weight = comp_weights.get(
                factor_col, comp_weights.get(factor_name, 0)
            )  # v2.16: comp_weights 已根据最优方法确定

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

    # v2.18: Rolling ICIR 权重排名 vs 全样本 ICIR 排名异常检测
    if best_weight_method == "rolling_icir_weight" and selected_factors and comp_weights:
        anomalies = _detect_weight_rank_anomalies(selected_factors, factor_data, comp_weights)
        if anomalies:
            lines.append("")
            lines.append("⚠ Rolling ICIR 权重异常因子说明:")
            n_total = len(selected_factors)
            for a in anomalies:
                lines.append(
                    f"  - {a['factor_name']}: 全样本ICIR={a['icir']:.4f}"
                    f"(排名{a['icir_rank']}/{n_total}) → 权重={a['weight']:.1%}"
                    f"(排名{a['weight_rank']}/{n_total})"
                )
                lines.append(f"    权重排名显著低于ICIR排名(下降{a['rank_drop']}位)，表明该因子近60日IC表现急剧恶化")
            lines.append("    说明: Rolling ICIR使用60日滚动窗口动态加权，全样本ICIR高但近期失效的因子会被自动降权")

    # v2.11→v2.13: 综合因子收益低于单因子时的完整分析说明
    # 检查选中因子是否存在短样本因子（有效天数差异导致年化收益不可比）
    short_sample_selected = [
        f for f in factor_data if f["factor_name"] in selected_factors and f.get("valid_days", 999) < 30
    ]

    # v2.13: 综合收益低于所有入选单因子时（不仅是短样本），增加方向抵消分析
    composite_best_return = (
        max(c.get("long_short_return_annual", 0) for c in composite_results) if composite_results else 0
    )
    selected_long_returns = [
        f.get("long_short_return_annual", 0)
        for f in factor_data
        if f["factor_name"] in selected_factors and f.get("valid_days", 999) >= 30
    ]
    min_long_return = min(selected_long_returns) if selected_long_returns else 0

    if short_sample_selected or (composite_best_return < min_long_return and min_long_return > 0):
        lines.append("")
        lines.append("⚠ 综合因子收益低于短样本单因子分析:")

        # v2.21: 动态编号，避免条件不满足时编号跳过
        note_idx = 1

        if short_sample_selected:
            short_names = [f["factor_name"] for f in short_sample_selected]
            short_days = [str(f.get("valid_days", "N/A")) for f in short_sample_selected]
            long_names = [
                f["factor_name"]
                for f in factor_data
                if f["factor_name"] in selected_factors and f.get("valid_days", 999) >= 30
            ]
            long_days = [
                str(f.get("valid_days", "N/A"))
                for f in factor_data
                if f["factor_name"] in selected_factors and f.get("valid_days", 999) >= 30
            ]
            lines.append(
                f"  {note_idx}. 数据覆盖差异: 短样本因子({','.join(short_names)})仅{','.join(short_days)}天，年化收益极端放大"
            )
            lines.append(f"     长样本因子({','.join(long_names)})有{','.join(long_days)}天数据，收益更可靠")
            lines.append("     综合因子覆盖全周期，短样本因子仅少数日期有数据，其余日期由其他因子主导")
            note_idx += 1

        if composite_best_return < min_long_return and min_long_return > 0:
            lines.append(
                f"  {note_idx}. 方向抵消效应: 综合因子最优年化={composite_best_return:.1f}%，低于长样本单因子最低={min_long_return:.1f}%"
            )
            # v2.24: 不硬编码 overnight_ret，用实际 flipped_factors
            flipped_in_selected = []
            if composite_results:
                flipped_in_selected = [
                    f for f in (composite_results[0].get("flipped_factors", [])) if f in selected_factors
                ]
            if flipped_in_selected:
                lines.append(
                    f"     原因分析：反向因子({','.join(flipped_in_selected)})取反后与正向因子方向统一，但因子间相关性导致"
                )
            else:
                lines.append("     原因分析：因子间相关性导致部分信号重叠抵消")
            lines.append("     部分信号重叠抵消。综合因子年化低于最优单因子是正常的——组合分散降低了极端收益")
            lines.append("     同时也降低了极端风险（夏普比率可能更优）")
            note_idx += 1

        # v2.13→v2.24: overnight_ret方向处理说明——仅在overnight_ret入选时输出
        flipped_factors = []
        if composite_results:
            flipped_factors = composite_results[0].get("flipped_factors", [])
        # v2.24: 只在 overnight_ret 实际入选时才讨论其方向处理
        if flipped_factors and "overnight_ret" in selected_factors:
            lines.append(f"  {note_idx}. overnight_ret方向处理: 已取反标准化值({flipped_factors})，无二次反向风险")
            lines.append("     取反逻辑：IC均值>0 → 标准化值取反 → 与负向因子方向统一 → 做空因子值大的股票")
            note_idx += 1
        # overnight_ret 未入选时不输出方向处理说明（讨论不存在的场景无意义）

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

    # v2.26: 加载股票名称映射（短名单展示用）
    stock_name_map = load_stock_name_map(logger)

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
    lines.extend(_generate_ic_section(ic_results, backtest_results))

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

    # v2.16: 确定最优权重方法（从 weight_result 或 composite_results 推断）
    best_weight_method = "icir_weight"  # 默认回退
    if weight_result and weight_result.get("best_selection"):
        best_weight_method = weight_result["best_selection"].get("method", "icir_weight")

    # 第四部分：因子筛选结果
    lines.append("")
    lines.append("四、因子筛选结果")
    lines.append("-" * 70)
    selection_info = get_factor_selection_info(
        composite_results, ic_results, backtest_results, logger, best_weight_method
    )
    lines.append(selection_info)

    # 第五部分：综合因子四种权重回测数据汇总
    lines.extend(_generate_composite_section(composite_results))

    # 第六部分：综合因子 vs 单因子对比
    lines.extend(_generate_comparison_section(factor_data, composite_results, best_weight_method))

    # v2.2: 第七部分：权重选择结果（新增）
    lines.extend(_generate_weight_selection_section(weight_result))

    # v2.2: 第八部分：股票选股结果（新增）
    # v2.19: 提取 comp_weights 传入选股 section，用于因子贡献集中度检测
    stock_comp_weights: dict[str, float] = {}
    best_item = next(
        (item for item in composite_results if item.get("weight_method") == best_weight_method),
        None,
    )
    if best_item:
        if best_weight_method == "rolling_icir_weight":
            weight_meta = best_item.get("weight_meta", {})
            last_day_weights = weight_meta.get("last_day_weights", {})
            stock_comp_weights = last_day_weights if last_day_weights else best_item.get("weights", {})
        else:
            stock_comp_weights = best_item.get("weights", {})

    lines.extend(_generate_stock_selection_section(stock_result, stock_comp_weights, data_results, stock_name_map))

    return "\n".join(lines)


def main():
    """主函数"""
    # 初始化日志记录器
    logger = setup_logger("generate_factor_summary_report")

    # 记录开始时间（用于计算总耗时）
    start_time = time.time()
    logger.info("开始生成汇总报告 (版本 %s)", __version__)

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
        logger.info("报告已保存到: %s", output_path)
    except OSError as e:
        logger.error("文件写入失败: %s, 原因: %s", output_path, e)
        sys.exit(1)

    # 记录总耗时
    elapsed = time.time() - start_time
    logger.info("报告生成完成，总耗时: %.2f秒", elapsed)


if __name__ == "__main__":
    main()
