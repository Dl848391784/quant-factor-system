"""汇总报告常量与配置。

从 generate_factor_summary_report.py 迁移（v3.8 拆分重构）。
包含路径配置、因子映射、阈值常量等共享定义。
"""

import logging
import sys
from datetime import datetime
from pathlib import Path


# 项目根目录（report/constants.py → summary/report/ → summary/ → 项目根）
PROJECT_ROOT = Path(__file__).parent.parent.parent.resolve()

# 添加项目根目录到 sys.path（支持根目录模块导入）
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from factor_definitions import (  # noqa: E402
    FACTOR_CATEGORIES,
    FACTOR_COL_TO_NAME_MAP,
    FACTOR_DEFINITIONS,
    FACTOR_NAME_TO_COL_MAP,
)
from paths import STOCK_LIST_DATA  # noqa: E402


# re-export 导入的名称，供子模块使用
__all__ = [
    "FACTOR_CATEGORIES",
    "FACTOR_COL_TO_NAME_MAP",
    "FACTOR_DEFINITIONS",
    "FACTOR_NAME_TO_COL_MAP",
    "STOCK_LIST_DATA",
]


# v2.18: 列名到因子名反向映射 alias（单一映射来源：factor_definitions）
COL_TO_FACTOR_NAME_MAP = FACTOR_COL_TO_NAME_MAP

# v2.22: 因子缩写表（format_weights 和 generate_correlation_section 共用）
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

# 相关性阈值常量
CORR_THRESHOLD_HIGH = 0.7  # 高相关阈值
CORR_THRESHOLD_MEDIUM = 0.5  # 中等相关阈值
CORR_MAX = 1.0  # 最大相关性

# 因子筛选阈值常量
ICIR_THRESHOLD = 0.15  # ICIR 筛选阈值
RETURN_THRESHOLD = 3.0  # 多空年化收益阈值（%）

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
