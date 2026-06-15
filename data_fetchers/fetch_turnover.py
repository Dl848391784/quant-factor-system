#!/usr/bin/env python3
"""
换手率数据拉取脚本

包含两个数据源：
1. 东财千股千评 API（fetch_turnover_rate_eastmoney）- 实时数据
2. baostock 数据源（fetch_turnover_rate_baostock）- 历史数据

输出路径：data_fetchers/result/turnover_rate_data.json.gz（遵循 MODULE.md 约束 #2）

版本历史:
- v1.2 (2026-04-08): 初始版本
- v2.0 (2026-05-27 10:00): 第一轮基础优化
  - 导入顺序 PEP 8 规范化：标准库 → 第三方库 → 本地模块
  - 版本号提取为常量：_OUTPUT_VERSION
  - datetime.now() 统一调用：模块级固定时间戳
  - 修复原因：代码bug（3项）
- v2.1 (2026-05-27 10:30): 第二轮深度优化
  - logger 参数化：所有公共函数添加 logger_arg 参数（遵循 MODULE.md 约束 77）
  - tempfile 使用：save_cache 使用 tempfile.NamedTemporaryFile（遵循 MODULE.md 约束 80）
  - session 资源管理：fetch_turnover_rate_eastmoney 使用 with 语句（遵循 MODULE.md 约束 78）
  - ST 检测前缀匹配：startswith(prefix) 避免 substring 匹配（遵循 MODULE.md 约束 79）
  - print → logger 迁移：52处全部迁移为 logger.info/debug/error/warning
  - load_cache/save_cache logger 参数传递：调用方传递 _logger
  - 修复原因：代码bug（6项）
- v2.2 (2026-05-27 11:00): 第三轮补充优化
  - ST_PREFIXES 常量提取：模块级常量便于维护（遵循 MODULE.md 约束 16）
  - load_stock_list ST 检测修复：前缀匹配 + 逻辑修正（break + continue）
  - __all__ 导出列表：添加公共函数导出列表（遵循 MODULE.md 约束 53）
  - __main__ logger 设置：logging.basicConfig + cli_logger → v2.18 已替换为 setup_logger
  - CLI 参数简化：--baostock 替代 --source 选择
  - 修复原因：代码bug + 规范补充（5项）
- v2.3 (2026-05-27 11:30): 第四轮补充优化
  - get_cached_turnover_codes 函数：创建公共函数（__all__ 中已声明）
  - 类型注解完整性：set[str] 返回类型 + logger_arg 参数
  - 函数文档字符串：添加 Args/Returns/Example 说明
  - 修复原因：规范补充（1项）
- v2.4 (2026-05-27 12:00): 第五轮深度修复
  - fetch_turnover_rate_baostock 时间统计修复：单独维护 processed_count/skipped_count（遵循 MODULE.md 约束 87）
  - merge_records 空数据处理修复：new_records=[] 时保留 existing_data 的 meta（遵循 MODULE.md 约束 88）
  - merge_records source 保留：保留原始 source 避免 'mixed' 强制覆盖
  - merge_records logger 参数：添加 logger_arg 参数 + 调用方传递
  - 修复原因：代码bug（3项）
- v2.5 (2026-05-27 12:30): 第六轮深度修复
  - ST_PREFIXES 元组优化：改为元组直接传给 startswith（遵循 MODULE.md 约束 89）
  - ST_PREFIXES 优先级语义：*ST 排在最前（退市风险优先检测）
  - total_pages=0 边界处理：添加警告日志（遵循 MODULE.md 约束 90）
  - fetch_stock_history_baostock 返回类型：实际与标注一致（无问题）
  - _NOW 模块级时间戳偏差：end_date 使用 datetime.now()（遵循 MODULE.md 约束 91）
  - 修复原因：代码bug（4项）
- v2.6 (2026-05-27 13:00): 第七轮深度修复
  - get_cached_turnover_codes 文档示例：改为 isinstance(codes, set) → True（确定结果）
  - load_cache _logger 赋值：统一为 logger_arg or logger（遵循 MODULE.md 约束 77）
  - 修复原因：代码bug（2项）
- v2.7 (2026-05-27 13:30): 第八轮深度修复
  - fetch_turnover_rate_baostock 时间估算逻辑：remaining 基于实际待处理数（遵循 MODULE.md 约束 92）
  - merge_records source 参数：添加 source 参数 + 调用方传入数据源（遵循 MODULE.md 约束 93）
  - merge_records 数据源合并逻辑：existing_meta.source != source 时设为 'mixed'
  - 修复原因：代码bug（2项）
- v2.8 (2026-05-27 14:00): 第九轮深度修复
  - get_cached_turnover_codes doctest：已修复为 isinstance(codes, set)（Round 17）
  - save_cache _logger 初始化：统一为 logger_arg or logger（遵循 MODULE.md 约束 77）
  - fetch_turnover_rate_baostock 跳过日志粒度：基于 skipped_count % 100（遵循 MODULE.md 约束 94）
  - 修复原因：代码bug（2项）
- v2.9 (2026-05-27 14:30): 第十轮深度修复
  - fetch_turnover_rate_eastmoney total_pages=0：添加 break 提前退出（遵循 MODULE.md 约束 95）
  - INTERMEDIATE_SAVE_INTERVAL 常量：删除未使用的冗余常量
  - 修复原因：代码bug（2项）
- v2.10 (2026-05-27 15:00): 第十一轮深度修复
  - save_cache tempfile 修复：在同一个 with 块内直接传文件对象给 gzip.open（遵循 MODULE.md 约束 96）
  - 原逻辑：先关闭临时文件，再重新打开写入（多余步骤）
  - 新逻辑：传文件对象给 gzip.open，不关闭再开
  - 修复原因：代码bug（1项）
- v2.11 (2026-05-27 19:00): 第十二轮类型系统规范化
  - CLI 入口异常处理添加：try/except 包裹 main/fetch_turnover_rate_baostock，优雅退出而非 traceback（遵循 MODULE.md 约束 97）
  - load_cache 类型校验：添加 isinstance(data, dict) 检查，确保返回 dict 类型（遵循 MODULE.md 约束 87）
  - typing 模块统一改为内置泛型：Optional[X]→X|None、List[Dict]→list[dict[str, Any]]、Set[str]→set[str]
  - ST_PREFIXES 注释修正：说明元组内顺序不影响匹配结果，而非误导性的"优先级语义"
  - 修复原因：代码bug（4项）
- v2.12 (2026-05-27 20:00): 第十三轮 ST 过滤与时间戳修复
  - ST_PREFIXES 元组优化：改为 ('*ST', 'ST', 'S')，覆盖 S*ST 等历史特殊股票（遵循 MODULE.md 约束 99）
  - ST_PREFIXES 注释修正：删除误导性的"S*ST 以 '*' 开头"描述，改为"S 开头历史特殊股票"
  - fetch_turnover_rate_baostock 完成日志时间戳：改用 datetime.now() 实时获取（遵循 MODULE.md 约束 100）
  - merge_records generated_at 语义：有历史数据时保留原值（遵循 MODULE.md 约束 98）
  - 修复原因：代码bug（4项）
- v2.13 (2026-05-27 21:00): 第十四轮防御性编程修复
  - get_cached_turnover_codes 字段存在性检查：使用 .get() 防止 KeyError（遵循 MODULE.md 约束 101）
  - fetch_stock_history_baostock 死代码注释：标注兜底 return 理论上不可达
  - fetch_turnover_rate_eastmoney total_count 初始化：循环外初始化防止作用域外 NameError（遵循 MODULE.md 约束 102）
  - save_cache 原子性注释补充：说明临时文件同目录保证 replace 原子性（遵循 MODULE.md 约束 103）
  - 修复原因：代码bug + 防御性编程（4项）
- v2.14 (2026-05-27 22:00): 第十五轮一致性修复
  - get_existing_stocks 字段检查：与 get_cached_turnover_codes 保持一致（遵循 MODULE.md 约束 101）
  - merge_records 字段防御：使用 .get() 跳过缺少必需字段的损坏记录（遵循 MODULE.md 约束 104）
  - ST_PREFIXES 'S' 注释补充：说明中文股票名不会以英文字母开头
  - load_stock_list docstring 修复：补充完整的 Returns 标签结构
  - remaining_to_process 注释精确化：说明 processed_count 已含当前股票
  - 修复原因：代码一致性 + 文档完善（5项）
- v2.15 (2026-05-27 23:00): 第十六轮文档与类型修复
  - main 函数 Raises 声明：补充 RuntimeError 异常说明（遵循 MODULE.md 约束 105）
  - merge_records last_updated 实时获取：改用 datetime.now() 避免长时间运行偏差（遵循 MODULE.md 约束 106）
  - API_PARAMS 类型一致性：pageSize/pageNumber 改为整数（遵循 MODULE.md 约束 107）
  - 修复原因：文档完善 + 类型一致性（3项）
- v2.16 (2026-05-28): 第十七轮日志精确化
  - fetch_turnover_rate_eastmoney 最后一次重试失败日志：补充异常类型名（遵循日志规范）
  - fetch_stock_history_baostock 所有失败路径：补充 warning 日志记录股票代码、错误原因和重试次数
  - main 函数完成日志时间戳：改用 datetime.now() 实时获取（遵循 MODULE.md 约束 100）
  - fetch_turnover_rate_eastmoney 开头空行日志：删除无信息量的空字符串日志（反模式）
  - fetch_turnover_rate_baostock 三处空行日志：删除 Step 0/1/2 前的空字符串日志（反模式）
  - 修复原因：日志精确化（5项）
- v2.17 (2026-06-03): 第十八轮增量更新逻辑修复
  - 新增 get_stock_latest_dates 函数：返回 {股票代码: 最新日期} 字典
  - 修复跳过逻辑：检查缓存中该股票的最新日期是否达到 T-1，而非只检查股票是否存在
  - 修复原因：代码bug（跳过逻辑只检查股票存在，导致换手率数据停更）
  - 根因：缓存中所有股票从 2026-05-27 后未更新，因跳过逻辑不检查日期
- v2.18 (2026-06-10): 日志配置修复
  - 替换 logging.basicConfig → setup_logger（遵循 PROJECT.md 第780-839行规范）
  - 新增 _get_logger() 函数、_SCRIPT_NAME/_LOGS_DIR 常量
  - 模块级 logger 改用 _get_logger()，日志写入 data_fetchers/logs/ 目录
  - __main__ 入口改用 _get_logger() 替换 logging.getLogger('fetch_turnover.cli')
  - 导入增加 get_module_logs_dir + setup_logger
  - 修复原因：basicConfig 只输出到控制台，不写日志文件（违反 PROJECT.md 日志规范）

作者: 云舟
日期: 2026-04-08
"""

import argparse
import gzip
import json
import logging
import sys
import tempfile
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import requests


# ============================================================
# 配置常量（遵循 MODULE.md 约束 16）
# ============================================================

# 输出版本
_OUTPUT_VERSION = "2.18"

# 固定时间戳（遵循 MODULE.md 约束 17）
_NOW = datetime.now()
_NOW_ISO = _NOW.isoformat()
_NOW_STR = _NOW.strftime("%Y-%m-%d %H:%M:%S")

# ST 股票前缀列表（遵循 MODULE.md 约束 16：常量提取）
# ST 股票命名规则（前缀匹配）：
# - '*ST'：退市风险警示（*ST某某）
# - 'ST'：风险警示（ST某某、SST某某）
# - 'S'：S 开头的历史特殊股票（S*ST、SST 等都以 S 开头）
#   注意：A股中文股票名 upper() 后不以英文字母开头，
#   'S' 仅匹配历史特殊处理的英文前缀股票，不会误杀正常中文股票
#
# 顺序说明：使用元组直接传给 startswith，元组内顺序不影响匹配结果
ST_PREFIXES = ("*ST", "ST", "S")  # 使用元组，直接传给 startswith（遵循 MODULE.md 约束 89）

# 公共函数导出列表（遵循 MODULE.md 约束 53）
__all__ = [
    "load_cache",
    "save_cache",
    "get_cached_turnover_codes",
    "fetch_turnover_rate_eastmoney",
    "fetch_turnover_rate_baostock",
    "main",
]

# 输出路径（遵循 MODULE.md 约束 #2：输出到 result 目录）
# 使用公共模块路径函数，避免硬编码路径（遵循 MODULE.md 约束 62）
try:
    from data_fetchers.common.logger_config import setup_logger
    from data_fetchers.common.paths import get_module_logs_dir, get_module_result_dir, get_stock_list_file
except ImportError:
    # __main__ 模块使用绝对导入（遵循 PROJECT.md 导入规范）
    from common.logger_config import setup_logger
    from common.paths import get_module_logs_dir, get_module_result_dir, get_stock_list_file

RESULT_DIR = get_module_result_dir()
CACHE_FILE = RESULT_DIR / "turnover_rate_data.json.gz"

# 股票列表路径（遵循 MODULE.md 约束 2：使用 result 目录）
STOCK_LIST_FILE = get_stock_list_file()

# ============================================================
# 日志配置（遵循 PROJECT.md 第780-839行规范 + MODULE.md 日志目录规范）
# ============================================================
_SCRIPT_NAME = Path(__file__).stem
_LOGS_DIR = get_module_logs_dir()


def _get_logger() -> logging.Logger:
    """获取日志记录器（复用公共模块 setup_logger）"""
    return setup_logger(_SCRIPT_NAME, logs_dir=_LOGS_DIR)


# 模块级 logger（写入 data_fetchers/logs/ 目录）
logger = _get_logger()

# ============================================================
# 东财千股千评 API 版本
# ============================================================

EASTMONEY_API_URL = "https://datacenter-web.eastmoney.com/api/data/v1/get"

API_PARAMS = {
    "sortColumns": "SECURITY_CODE",
    "sortTypes": "1",
    "pageSize": 500,  # 整数类型，与循环中 pageNumber 赋值保持一致（遵循 MODULE.md 约束 107）
    "pageNumber": 1,  # 整数类型，循环中被 params["pageNumber"] = page 覆盖
    "reportName": "RPT_DMSK_TS_STOCKNEW",
    "quoteColumns": "f2~01~SECURITY_CODE~CLOSE_PRICE,f8~01~SECURITY_CODE~TURNOVERRATE,"
    "f3~01~SECURITY_CODE~CHANGE_RATE,f9~01~SECURITY_CODE~PE_DYNAMIC",
    "columns": "ALL",
    "filter": "",
    "token": "894050c76af8597a853f5b408b759f5d",
}

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Referer": "https://data.eastmoney.com/stockcomment/",
    "Accept": "*/*",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}


def is_main_board_stock(code: str, name: str) -> bool:
    """
    判断是否为主板股票

    Args:
        code: 股票代码
        name: 股票名称

    Returns:
        bool: 是否为主板股票

    Note:
        使用前缀匹配检测 ST 股票（遵循 MODULE.md 约束 79）
        避免 substring 匹配误判正常股票（如"东ST"）
    """
    # 1. 创业板、科创板、北交所剔除
    if code.startswith("30") or code.startswith("688") or code.startswith("8") or code.startswith("4"):
        return False

    # 2. ST 类股票剔除（前缀匹配，使用模块级常量 ST_PREFIXES）
    # 使用元组直接传给 startswith（遵循 MODULE.md 约束 89）
    name_upper = name.upper()
    if name_upper.startswith(ST_PREFIXES):
        return False

    # 3. 退市股票剔除
    if "退市" in name:
        return False

    # 4. 主板股票判断
    return code.startswith("60") or code.startswith("00")


def fetch_turnover_rate_eastmoney(logger_arg: logging.Logger | None = None) -> list[dict[str, Any]]:
    """
    从东财千股千评 API 拉取换手率数据

    Args:
        logger_arg: 日志 logger（遵循 MODULE.md 约束 77）

    Returns:
        换手率数据列表

    Note:
        使用 with 语句管理 session（遵循 MODULE.md 约束 78）
    """
    _logger = logger_arg or logger

    _logger.info("[API拉取] 从东财千股千评获取换手率数据...")

    all_records = []
    page = 1
    total_pages = 0
    total_count = 0  # 在循环外初始化，防止作用域外引用导致 NameError（遵循 MODULE.md 约束 102）
    retries = 3

    # 使用 with 语句确保 session 资源释放（遵循 MODULE.md 约束 78）
    with requests.Session() as session:
        session.headers.update(HEADERS)

        while True:
            params = API_PARAMS.copy()
            params["pageNumber"] = page

            for attempt in range(retries):
                try:
                    response = session.get(EASTMONEY_API_URL, params=params, timeout=30)
                    response.raise_for_status()
                    data_json = response.json()
                    break
                except Exception as e:
                    if attempt < retries - 1:
                        wait_time = 2 + attempt * 2
                        _logger.warning("  重试 %s/%s，等待 %s秒...", attempt + 1, retries, wait_time)
                        time.sleep(wait_time)
                    else:
                        _logger.error("  ✗ API请求失败 [%s]: %s", type(e).__name__, e)
                        # PROJECT.md H6 / data_fetchers MODULE.md: raise ... from e 保留异常链
                        raise RuntimeError(f"API请求失败 [{type(e).__name__}]: {e}") from e

            if page == 1:
                total_pages = data_json.get("result", {}).get("pages", 0)
                total_count = data_json.get("result", {}).get("count", 0)
                _logger.info("  总页数: %s, 总股票数: %s", total_pages, total_count)

                # 边界情况：pages=0 异常处理（遵循 MODULE.md 约束 90）
                if total_pages == 0:
                    _logger.warning("  ⚠ API返回 pages=0（异常情况），可能无数据或API异常，提前退出")
                    break  # 提前退出循环（遵循 MODULE.md 约束 95）

            result_data = data_json.get("result", {}).get("data", [])

            if not result_data:
                _logger.info("  第 %s 页返回空数据，获取完成", page)
                break

            page_added = 0
            for item in result_data:
                code = item.get("SECURITY_CODE", "")
                name = item.get("SECURITY_NAME_ABBR", "")
                trade_date = item.get("TRADE_DATE", "")
                turnover_rate = item.get("TURNOVERRATE")

                if is_main_board_stock(code, name) and turnover_rate is not None and turnover_rate != "-":
                    try:
                        turnover_rate_float = float(turnover_rate)
                        all_records.append(
                            {"date": trade_date, "asset": code, "turnover_rate": turnover_rate_float, "name": name}
                        )
                        page_added += 1
                    except (ValueError, TypeError):
                        pass

            _logger.info("  第 %s/%s 页: 获取 %s 条，新增主板 %s 只", page, total_pages, len(result_data), page_added)

            if page >= total_pages:
                break

            page += 1
            time.sleep(0.1)

    _logger.info("  ✓ 共获取 %s 条主板股票换手率数据", len(all_records))
    return all_records


# ============================================================
# baostock 版本
# ============================================================

DEFAULT_N_DAYS = 500
DEFAULT_DELAY = 0.1
DEFAULT_MAX_RETRIES = 3
# 重试配置
CONSECUTIVE_FAILURE_THRESHOLD = 5
CONSECUTIVE_FAILURE_PAUSE = 30

# ============================================================
# 内部函数
# ============================================================


def load_stock_list() -> list[dict[str, Any]]:
    """
    从缓存加载主板股票列表

    Returns:
        list[dict[str, Any]]: 主板股票列表

    Note:
        使用前缀匹配检测 ST 股票（遵循 MODULE.md 约束 79）
        避免 substring 匹配误判正常股票（如"东ST"）
    """
    if not STOCK_LIST_FILE.exists():
        raise FileNotFoundError(f"股票列表缓存不存在: {STOCK_LIST_FILE}")

    with open(STOCK_LIST_FILE, encoding="utf-8") as f:
        data = json.load(f)

    stocks = data.get("stocks", [])
    main_board_stocks = []
    for stock in stocks:
        code = stock.get("code", "")
        name = stock.get("name", "")

        # 使用 is_main_board_stock 函数统一过滤逻辑（避免内联重复）
        if is_main_board_stock(code, name):
            main_board_stocks.append(stock)

    return main_board_stocks


def fetch_turnover_rate_baostock(
    n_days: int = DEFAULT_N_DAYS, max_stocks: int = 0, full: bool = False, logger_arg: logging.Logger | None = None
) -> bool:
    """
    使用 baostock 拉取历史换手率数据

    Args:
        n_days: 历史天数
        max_stocks: 最大股票数（0为不限制）
        full: 是否全量拉取
        logger_arg: 日志 logger（遵循 MODULE.md 约束 77）

    Returns:
        是否成功

    Note:
        使用 try/finally 确保 baostock 登出
    """
    import baostock as bs

    _logger = logger_arg or logger

    _logger.info("=" * 70)
    _logger.info("[%s] 开始拉取历史换手率数据（baostock）", _NOW_STR)
    _logger.info("=" * 70)

    # 登录 baostock
    _logger.info("[Step 0] 登录 baostock...")
    lg = bs.login()
    if lg.error_code != "0":
        _logger.error("  ✗ 登录失败: %s", lg.error_msg)
        return False
    _logger.info("  ✓ 登录成功")

    try:
        # 加载股票列表
        _logger.info("[Step 1] 加载主板股票列表...")
        all_stocks = load_stock_list()
        _logger.info("  主板股票总数: %s", len(all_stocks))

        if max_stocks > 0:
            all_stocks = all_stocks[:max_stocks]
            _logger.info("  限制拉取数量: %s", max_stocks)

        # 加载现有缓存
        _logger.info("[Step 2] 加载现有缓存...")
        cache_data = load_cache(logger_arg=_logger) if not full else None
        existing_stocks = get_existing_stocks(cache_data)
        stock_latest_dates = get_stock_latest_dates(cache_data)
        _logger.info("  已有数据的股票数: %s", len(existing_stocks))

        # 计算日期范围
        # 使用 datetime.now() 避免长期运行偏差（遵循 MODULE.md 约束 91）
        end_date = datetime.now()  # 实时获取当前时间，避免 _NOW 偏差
        start_date = end_date - timedelta(days=n_days * 1.5)
        start_date_str = start_date.strftime("%Y-%m-%d")
        end_date_str = end_date.strftime("%Y-%m-%d")

        # 计算预期最新日期（T-1，即昨天）
        # 用于判断是否需要更新（遵循 MODULE.md 约束：增量更新需检查日期是否最新）
        expected_latest_date = (end_date - timedelta(days=1)).strftime("%Y-%m-%d")
        _logger.info("  预期最新日期(T-1): %s", expected_latest_date)

        _logger.info("[Step 3] 日期范围: %s ~ %s", start_date_str, end_date_str)

        # 串行拉取
        _logger.info("[Step 4] 开始串行拉取...")

        all_new_records = []
        success_count = 0
        failed_stocks = []
        consecutive_failures = 0
        skipped_count = 0  # 跳过的股票数量
        processed_count = 0  # 实际处理的股票数量（遵循 MODULE.md 约束 87）

        total = len(all_stocks)
        start_time = time.time()

        for idx, stock in enumerate(all_stocks, 1):
            code = stock["code"]
            name = stock["name"]

            # 跳过日期已更新的股票（检查最新日期是否达到 T-1）
            # 修复 v2.17：只检查股票存在会导致旧数据不更新
            if code in existing_stocks and not full:
                stock_latest_date = stock_latest_dates.get(code)
                if stock_latest_date and stock_latest_date >= expected_latest_date:
                    skipped_count += 1
                    if skipped_count % 100 == 0:  # 基于跳过计数，更直观（遵循 MODULE.md 约束 94）
                        _logger.info(
                            "  [%s/%s] 已跳过 %s 只（含 %s，最新日期 %s）...",
                            idx,
                            total,
                            skipped_count,
                            code,
                            stock_latest_date,
                        )
                    continue
                elif stock_latest_date:
                    _logger.debug(
                        "  [%s/%s] %s 需更新：缓存最新日期 %s < 预期 %s",
                        idx,
                        total,
                        code,
                        stock_latest_date,
                        expected_latest_date,
                    )

            # 实际处理股票统计（遵循 MODULE.md 约束 87）
            processed_count += 1

            elapsed = time.time() - start_time
            if processed_count > 1:
                avg_time = elapsed / processed_count  # 使用实际处理数量计算平均时间
                # 剩余待处理数 = 总数 - 已跳过 - 已处理（processed_count 已含当前股票）
                # 遵循 MODULE.md 约束 92
                remaining_to_process = total - skipped_count - processed_count
                remaining = remaining_to_process * avg_time  # 预估剩余时间
            else:
                remaining = 0

            _logger.info(
                "  [%s/%s] %s %-8s | 成功: %s 失败: %s 跳过: %s | 预计剩余: %s",
                idx,
                total,
                code,
                name,
                success_count,
                len(failed_stocks),
                skipped_count,
                format_time(remaining),
            )

            records, success = fetch_stock_history_baostock(code, start_date_str, end_date_str, logger_arg=_logger)

            if success and records is not None:
                all_new_records.extend(records)
                success_count += 1
                consecutive_failures = 0
            elif success:
                success_count += 1
                consecutive_failures = 0
            else:
                failed_stocks.append(code)
                consecutive_failures += 1

                if consecutive_failures >= CONSECUTIVE_FAILURE_THRESHOLD:
                    _logger.warning("  ⚠ 连续失败%s只，暂停%s秒...", consecutive_failures, CONSECUTIVE_FAILURE_PAUSE)
                    time.sleep(CONSECUTIVE_FAILURE_PAUSE)
                    consecutive_failures = 0

            if idx < total:
                time.sleep(DEFAULT_DELAY)

        # 合并并保存
        _logger.info("[Step 5] 合并数据并保存...")
        merged_data = merge_records(cache_data, all_new_records, source="baostock", logger_arg=_logger)
        save_cache(merged_data, logger_arg=_logger)

        total_time = time.time() - start_time
        meta = merged_data["meta"]

        _logger.info("=" * 70)
        _logger.info("[%s] 拉取完成", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        _logger.info("=" * 70)
        _logger.info("总股票数:   %s", total)
        _logger.info("跳过数:     %s", skipped_count)
        _logger.info("成功数:     %s", success_count)
        _logger.info("失败数:     %s", len(failed_stocks))
        _logger.info("日期范围:   %s ~ %s", meta["date_range"]["start"], meta["date_range"]["end"])
        _logger.info("交易日数:   %s", meta["n_days"])
        _logger.info("耗时:       %s", format_time(total_time))

        return len(failed_stocks) == 0

    finally:
        _logger.info("[清理] 登出 baostock...")
        bs.logout()
        _logger.info("  ✓ 已登出")


def get_baostock_code(stock_code: str) -> str:
    """根据股票代码转换为 baostock 格式"""
    if stock_code.startswith("6"):
        return f"sh.{stock_code}"
    else:
        return f"sz.{stock_code}"


def fetch_stock_history_baostock(
    stock_code: str,
    start_date: str,
    end_date: str,
    retries: int = DEFAULT_MAX_RETRIES,
    logger_arg: logging.Logger | None = None,
) -> tuple[list[dict[str, Any]] | None, bool]:
    """使用 baostock 拉取单只股票的历史换手率数据

    Args:
        stock_code: 股票代码
        start_date: 开始日期
        end_date: 结束日期
        retries: 最大重试次数
        logger_arg: 日志 logger（遵循 MODULE.md 约束 77）
    """
    import baostock as bs

    _logger = logger_arg or logger

    bs_code = get_baostock_code(stock_code)

    for attempt in range(retries):
        try:
            rs = bs.query_history_k_data_plus(
                bs_code, "date,code,turn", start_date=start_date, end_date=end_date, frequency="d", adjustflag="3"
            )

            if rs.error_code != "0":
                if attempt < retries - 1:
                    time.sleep(2**attempt)
                    continue
                # 最后一次重试失败，记录日志（使 failed_stocks 在日志中有对应失败原因可追溯）
                _logger.warning(
                    "[baostock] %s API错误 [%s]: %s（重试 %s 次后失败）",
                    stock_code,
                    rs.error_code,
                    rs.error_msg,
                    retries,
                )
                return (None, False)

            data_list = []
            while rs.next():
                data_list.append(rs.get_row_data())

            if not data_list:
                return ([], True)

            records = []
            for row in data_list:
                date_str = row[0]
                turn_str = row[2]
                try:
                    turnover_rate = float(turn_str)
                    records.append({"date": date_str, "asset": stock_code, "turnover_rate": turnover_rate})
                except (ValueError, TypeError):
                    continue

            return (records, True)

        except Exception as e:
            if attempt < retries - 1:
                wait_time = 2**attempt
                time.sleep(wait_time)
            else:
                # 最后一次重试失败，记录日志（使 failed_stocks 在日志中有对应失败原因可追溯）
                _logger.warning(
                    "[baostock] %s 异常 [%s]: %s（重试 %s 次后失败）", stock_code, type(e).__name__, e, retries
                )
                return (None, False)

    # 防御性兜底：理论上不可达（所有路径已在循环内 return）
    # 循环内所有 attempt 失败都已 return (None, False)，此行仅满足类型检查器
    return (None, False)


# ============================================================
# 公共函数
# ============================================================


def get_cached_turnover_codes(logger_arg: logging.Logger | None = None) -> set[str]:
    """
    获取缓存的换手率股票代码集合

    Args:
        logger_arg: 日志 logger（遵循 MODULE.md 约束 77）

    Returns:
        股票代码集合，如果缓存不存在或无效则返回空集合

    Example:
        >>> codes = get_cached_turnover_codes()
        >>> isinstance(codes, set)  # 类型检查（确定结果）
        True
    """
    _logger = logger_arg or logger

    cache_data = load_cache(logger_arg=_logger)
    if not cache_data:
        return set()

    data = cache_data.get("data", [])
    # 使用 .get() 防止缺少 'asset' 字段的记录导致 KeyError（遵循 MODULE.md 约束 101）
    return {record.get("asset") for record in data if record.get("asset")}


def load_cache(logger_arg: logging.Logger | None = None) -> dict[str, Any] | None:
    """
    加载现有缓存

    Args:
        logger_arg: 日志 logger（遵循 MODULE.md 约束 77）

    Returns:
        缓存数据，如果不存在或无效则返回 None
    """
    _logger = logger_arg or logger  # 统一使用模块级 logger（遵循 MODULE.md 约束 77）

    if not CACHE_FILE.exists():
        return None

    try:
        with gzip.open(CACHE_FILE, "rt", encoding="utf-8") as f:
            data = json.load(f)

        # 类型校验：确保返回 dict 类型（遵循 MODULE.md 约束 87）
        # 合法 JSON 但非 dict 类型（如 list）会导致调用方 AttributeError
        if not isinstance(data, dict):
            _logger.warning("[缓存] JSON 类型异常: 期望 dict，实际 %s", type(data).__name__)
            return None

        file_size = CACHE_FILE.stat().st_size
        size_mb = file_size / (1024 * 1024)
        _logger.info("[缓存] 已读取: %s (%.2f MB)", CACHE_FILE, size_mb)
        return data
    except Exception as e:
        _logger.warning("[缓存] 读取失败: [%s]: %s", type(e).__name__, e)
        return None


def get_existing_stocks(cache_data: dict[str, Any] | None) -> set[str]:
    """从缓存中获取已有数据的股票代码集合"""
    if not cache_data:
        return set()
    data = cache_data.get("data", [])
    # 使用 .get() 与 get_cached_turnover_codes 保持一致（遵循 MODULE.md 约束 101）
    return {record.get("asset") for record in data if record.get("asset")}


def get_stock_latest_dates(cache_data: dict[str, Any] | None) -> dict[str, str]:
    """
    从缓存中获取每只股票的最新日期

    Args:
        cache_data: 缓存数据字典

    Returns:
        dict[str, str]: {股票代码: 最新日期} 映射，日期格式为 'YYYY-MM-DD'

    Example:
        >>> cache = load_cache()
        >>> dates = get_stock_latest_dates(cache)
        >>> dates.get("000001")  # 返回 '2026-05-27' 或 None
    """
    if not cache_data:
        return {}

    data = cache_data.get("data", [])
    stock_dates: dict[str, str] = {}

    for record in data:
        asset = record.get("asset")
        date = record.get("date")
        if asset and date:
            # 日期可能带时间戳（如 '2026-05-27 00:00:00'），截取日期部分
            date_str = str(date).split()[0] if " " in str(date) else str(date)
            # 保留最新的日期
            if asset not in stock_dates or date_str > stock_dates[asset]:
                stock_dates[asset] = date_str

    return stock_dates


def save_cache(data: dict[str, Any], logger_arg: logging.Logger | None = None) -> None:
    """
    保存缓存文件

    Args:
        data: 缓存数据
        logger_arg: 日志 logger（遵循 MODULE.md 约束 77）

    Note:
        使用 tempfile.NamedTemporaryFile 避免并发冲突（遵循 MODULE.md 约束 80）
    """
    _logger = logger_arg or logger  # 统一使用模块级 logger（遵循 MODULE.md 约束 77）

    RESULT_DIR.mkdir(parents=True, exist_ok=True)

    # 使用 tempfile 避免并发冲突（遵循 MODULE.md 约束 80）
    # 原子性保证：临时文件在 RESULT_DIR 内创建，与目标文件同目录同文件系统，
    # Path.replace 在同文件系统内是原子操作（遵循 MODULE.md 约束 103）
    temp_path: Path | None = None
    try:
        # 创建临时文件并在同一个 with 块内写入（遵循 MODULE.md 约束 96）
        # 传文件对象给 gzip.open，不关闭再开
        with tempfile.NamedTemporaryFile(suffix=".json.gz", dir=RESULT_DIR, delete=False) as temp_f:
            temp_path = Path(temp_f.name)
            with gzip.open(temp_f, "wt", encoding="utf-8") as gz_f:
                json.dump(data, gz_f, ensure_ascii=False, indent=2)

        # with 块结束后文件已关闭，执行原子替换
        temp_path.replace(CACHE_FILE)

        file_size = CACHE_FILE.stat().st_size
        size_mb = file_size / (1024 * 1024)
        _logger.info("[缓存] 已保存: %s (%.2f MB)", CACHE_FILE, size_mb)

    except Exception as e:
        # 失败时清理临时文件
        if temp_path and temp_path.exists():
            temp_path.unlink()
        _logger.error("保存缓存失败: [%s]: %s", type(e).__name__, e)
        raise


def merge_records(
    existing_data: dict[str, Any] | None,
    new_records: list[dict[str, Any]],
    source: str = "eastmoney",  # 新增参数：调用方明确传入数据源（遵循 MODULE.md 约束 93）
    logger_arg: logging.Logger | None = None,
) -> dict[str, Any]:
    """
    合并现有数据和新数据

    Args:
        existing_data: 现有缓存数据
        new_records: 新记录列表
        source: 数据源名称（'eastmoney' 或 'baostock'，遵循 MODULE.md 约束 93）
        logger_arg: 日志 logger（遵循 MODULE.md 约束 77）

    Returns:
        合并后的数据

    Note:
        当 new_records 为空时保留 existing_data 的 meta（遵循 MODULE.md 约束 88）
        避免 generated_at、last_updated、source 被强制更新

        数据源合并逻辑（遵循 MODULE.md 约束 93）：
        - 若 existing_meta.source != source，则设为 'mixed'
        - 否则保留 source（单一数据源）
    """
    _logger = logger_arg or logger

    # 边界情况：new_records 为空（遵循 MODULE.md 约束 88）
    if not new_records:
        if existing_data:
            # 保留现有数据，不做任何更新
            _logger.info("[合并] new_records 为空，保留现有数据")
            return existing_data
        else:
            # 无数据，返回空结构
            _logger.warning("[合并] 无数据，返回空结构")
            return {
                "meta": {
                    "generated_at": _NOW_ISO,
                    "source": "empty",
                    "n_days": 0,
                    "n_assets": 0,
                    "date_range": {"start": None, "end": None},
                    "last_updated": _NOW_STR,
                    "version": _OUTPUT_VERSION,
                },
                "data": [],
            }

    # 正常合并流程
    existing_records = []
    existing_meta = None
    if existing_data:
        existing_records = existing_data.get("data", [])
        existing_meta = existing_data.get("meta")

    all_records = existing_records + new_records

    record_map = {}
    for record in all_records:
        # 使用 .get() 跳过缺少必需字段的损坏记录（遵循 MODULE.md 约束 104）
        date_val = record.get("date")
        asset_val = record.get("asset")
        if date_val and asset_val:
            # 归一化 date 格式：东财返回 "2026-06-01 00:00:00"，baostock 返回 "2026-06-01"
            # 与 get_stock_latest_dates 的处理保持一致
            normalized_date = str(date_val).split()[0]
            key = (normalized_date, asset_val)
            # 同时归一化 record 中的 date 字段，避免 unique_dates/date_range 混存两种格式
            record = {**record, "date": normalized_date}
            record_map[key] = record

    merged_records = list(record_map.values())
    merged_records.sort(key=lambda x: (x.get("date", ""), x.get("asset", "")))

    # 使用 .get() 与上方 record_map 构建保持一致
    unique_dates = sorted({r.get("date") for r in merged_records if r.get("date")})
    unique_assets = sorted({r.get("asset") for r in merged_records if r.get("asset")})

    # meta 更新策略（遵循 MODULE.md 约束 93）
    # 数据源合并逻辑：若 existing_meta.source != source，则设为 'mixed'
    final_source = source  # 默认使用新数据源（单一数据源）
    if existing_meta:
        existing_source = existing_meta.get("source", source)
        if existing_source != source:
            final_source = "mixed"  # 数据源混合

    # generated_at 语义：数据首次生成时间，有历史数据时保留原值
    generated_at = _NOW_ISO
    if existing_meta:
        generated_at = existing_meta.get("generated_at", _NOW_ISO)

    return {
        "meta": {
            "generated_at": generated_at,  # 保留首次生成时间（遵循 MODULE.md 约束 98）
            "source": final_source,  # 数据源合并逻辑（遵循 MODULE.md 约束 93）
            "n_days": len(unique_dates),
            "n_assets": len(unique_assets),
            "date_range": {
                "start": unique_dates[0] if unique_dates else None,
                "end": unique_dates[-1] if unique_dates else None,
            },
            "last_updated": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),  # 实时获取合并时间（遵循 MODULE.md 约束 106）
            "version": _OUTPUT_VERSION,
        },
        "data": merged_records,
    }


def format_time(seconds: float) -> str:
    """格式化时间为 HH:MM:SS"""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


# ============================================================
# 主函数
# ============================================================


def main(logger_arg: logging.Logger | None = None) -> bool:
    """
    主函数：东财版本

    Args:
        logger_arg: 日志 logger（遵循 MODULE.md 约束 77）

    Returns:
        是否成功

    Raises:
        RuntimeError: API请求重试全部失败时抛出（遵循 MODULE.md 约束 105）
    """
    _logger = logger_arg or logger

    _logger.info("=" * 60)
    _logger.info("[%s] 开始拉取换手率数据", _NOW_STR)
    _logger.info("=" * 60)
    _logger.info("数据源: 东财千股千评 API")
    _logger.info("股票范围: 主板股票（60/00开头，剔除创业板/科创板/北交所/ST）")
    _logger.info("缓存路径: %s", CACHE_FILE)

    # Step 1: 加载现有缓存
    existing_data = load_cache(logger_arg=_logger)

    # Step 2: 拉取新数据
    new_records = fetch_turnover_rate_eastmoney(logger_arg=_logger)

    if not new_records:
        _logger.error("❌ 未获取到任何数据")
        return False

    # Step 3: 合并去重
    merged_data = merge_records(existing_data, new_records, source="eastmoney", logger_arg=_logger)

    # Step 4: 保存缓存
    save_cache(merged_data, logger_arg=_logger)

    # 输出统计
    meta = merged_data["meta"]
    _logger.info("=" * 60)
    _logger.info("[%s] 换手率数据拉取完成", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    _logger.info("=" * 60)
    _logger.info("日期范围: %s ~ %s", meta["date_range"]["start"], meta["date_range"]["end"])
    _logger.info("交易日数: %s", meta["n_days"])
    _logger.info("股票数量: %s", meta["n_assets"])
    _logger.info("总记录数: %s", len(merged_data["data"]))

    return True


if __name__ == "__main__":
    # CLI 入口 logger 设置（使用 setup_logger 写入 data_fetchers/logs/ 目录）
    cli_logger = _get_logger()

    parser = argparse.ArgumentParser(description="换手率数据拉取")
    parser.add_argument("--baostock", action="store_true", help="使用 baostock 数据源")
    parser.add_argument("--full", action="store_true", help="全量拉取（不使用缓存）")
    parser.add_argument("--n-days", type=int, default=DEFAULT_N_DAYS, help="历史天数（baostock）")
    parser.add_argument("--max-stocks", type=int, default=0, help="最大股票数（baostock，0为不限制）")

    args = parser.parse_args()

    try:
        if args.baostock:
            success = fetch_turnover_rate_baostock(
                n_days=args.n_days, max_stocks=args.max_stocks, full=args.full, logger_arg=cli_logger
            )
        else:
            success = main(logger_arg=cli_logger)

        cli_logger.info("执行完成，退出码: %s", 0 if success else 1)
        sys.exit(0 if success else 1)
    except Exception as e:
        # data_fetchers MODULE.md R10: 类型名 + logger.exception 自动附堆栈
        cli_logger.exception("执行失败: [%s]", type(e).__name__)
        sys.exit(1)
