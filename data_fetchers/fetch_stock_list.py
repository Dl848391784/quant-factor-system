#!/usr/bin/env python3
"""
股票列表缓存模块

从新浪财经 API 获取主板股票列表，剔除创业板、科创板、北交所和ST股票，
生成缓存文件供后续因子分析使用。

主板股票定义：
- 沪市主板：60 开头
- 深市主板：00 开头

剔除：创业板(30)、科创板(688)、北交所(8/4开头)、ST股票

版本历史：
- v1.0 (2026-04-02): 初始版本
- v2.0 (2026-05-27): 公共模块规范化
  - 输出目录迁移：cache → result（遵循 MODULE.md 约束 2）
  - 日志规范化：复用 logger_config.py（遵循 PROJECT.md 第561-700行）
  - CLI 日志规范化：print → logger（遵循 PROJECT.md 第780-839行）
  - 类型注解补全 + __all__ 导出（遵循 MODULE.md 约束 53）
  - 版本号常量提取（遵循 MODULE.md 约束 16）
  - datetime.now() 统一调用（遵循 MODULE.md 约束 17）
  - Path 对象迁移 + 公共模块复用（遵循 MODULE.md 约束 62）

- v2.1 (2026-05-27 06:30): 第二轮优化
  - requests 导入移至顶部（遵循 MODULE.md 约束 51）
  - 原子写入捕获所有异常（遵循 MODULE.md 约束 55）
  - 公共函数返回类型注解补全（遵循 MODULE.md 约束 76）
  - validate_cache logger 参数化（遵循 PROJECT.md 日志参数规范）
  - set 类型注解完整化 `set[str]`

- v2.2 (2026-05-27 06:45): 第三轮优化
  - 导入顺序修正：requests 移至标准库之后（遵循 PEP 8）
  - ensure_cache_dir/ensure_result_dir 调用时传递 logger 参数（遵循约束 33）

- v2.3 (2026-05-27 07:00): 第四轮优化
  - load_cache 异常捕获扩大：JSONDecodeError → Exception（遵循约束 55）
  - 潜在风险覆盖：PermissionError、IsADirectoryError、OSError 等

- v2.4 (2026-05-27 07:30): 第五轮深度修复
  - 参数名遮蔽修复：logger → logger_arg（统一4个函数签名）
  - session 资源泄漏修复：使用 with 语句确保释放
  - load_cache 添加 logger_arg 参数：save_cache 调用时传递 logger
  - ST 股票误判修复：substring → 前缀匹配（避免 '东ST' 正常股票被误判）
  - 修复原因：代码bug（4项）+ 规范缺失（MODULE.md 新增约束77/78/79）

- v2.5 (2026-05-27 08:00): 第六轮深度修复
  - 重试逻辑修复：最后一次重试失败时直接 raise（删除无效 continue）
  - validate_cache 参数修复：删除冗余 logger_arg 参数
  - _write_json_file 临时文件修复：使用 tempfile.NamedTemporaryFile 避免并发冲突
  - 增量更新 name 字段修复：同步更新已存在股票的最新名称
  - data 变量类型守卫：添加 None 检查，确保类型安全
  - 修复原因：代码bug（5项）+ 规范缺失（MODULE.md 新增约束80/81/82）

- v2.6 (2026-05-27 08:30): 第七轮深度修复
  - _write_json_file 参数名修复：logger → logger_arg（遵循 PROJECT.md 日志参数规范）
  - validate_cache ST 检查修复：使用前缀匹配（与 is_valid_main_board_stock 逻辑一致）
  - is_valid_main_board_stock ST 顺序修复：先剔除 S 开头，再剔除 *ST 和 ST
  - 重试逻辑简化：删除 success 变量，循环内直接控制流（最后一次重试失败 raise）
  - 修复原因：代码bug（4项）+ 规范缺失（MODULE.md 新增约束83/84）

- v2.7 (2026-05-27 09:00): 第八轮深度修复
  - data 类型守卫增强：添加 assert isinstance(data, list) 确保类型安全
  - existing_stock_map 注释说明：明确引用修改预期行为，避免误解
  - removed_codes 截断：限制最多50个，添加 removed_codes_truncated 字段避免 JSON 膨胀
  - result 初始化补全：添加 updated_count: 0 避免字段缺失
  - CLI 日志补全：添加 updated_count 输出（仅当有更新时显示）
  - 修复原因：代码bug（5项）+ 规范缺失（MODULE.md 新增约束85/86）

- v2.8 (2026-05-27 09:30): 第九轮深度修复
  - ST 前缀提取为模块级常量：ST_PREFIXES 便于维护（遵循 MODULE.md 约束 16）
  - fetch_stocks_from_sina doctest 修复：改为合法格式 len(stocks) > 2500
  - get_cached_stock_codes doctest 修复：改为合法格式 len(codes) > 2500
  - 修复原因：代码bug（3项）

- v2.9 (2026-05-27 16:15): 公共模块规范化
  - 使用 write_json_cache 替换手写原子写入（遵循 MODULE.md 约束 4）
  - 删除冗余函数 _write_json_file（减少45行代码）
  - 删除冗余导入 tempfile（遵循 PEP 8 导入规范）
  - 创建流程文档 docs/fetch_stock_list_flow.md（遵循 MODULE.md 约束 8）
  - 创建 pytest 测试文件 test_cases/test_fetch_stock_list.py（遵循 PROJECT.md 编码规范）
  - 修复原因：规范遗漏（约束 #4 未执行、约束 #8 未执行、测试文件缺失）

- v2.10 (2026-05-27 17:00): 代码质量修复
  - save_cache 退市股票过滤逻辑修复：使用 removed_codes_full 而非截断后的 removed_codes
  - validate_cache ST 检查逻辑修复：引用 ST_PREFIXES 常量而非硬编码字符串
  - is_valid_main_board_stock ST 检查顺序修复：先检查 *ST 和 ST，最后检查纯 S 开头
  - fetch_stocks_from_sina 重试逻辑修复：非最后一次失败分支添加显式 continue
  - 修复原因：代码bug（4项）导致数据与统计不一致、常量引用不同步、控制流意图不清晰

- v2.11 (2026-05-27 17:30): 类型系统规范化
  - load_cache 返回类型校验：添加 isinstance 检查，确保返回 dict 类型（遵循 MODULE.md 约束 87）
  - ST_PREFIXES 改为具名常量：ST_PREFIX_STAR、ST_PREFIX_ST、ST_PREFIX_S，避免键名拼写错误
  - refresh_stock_cache 返回类型统一：总是返回字典而非 raise，调用方无需 try/except（遵循 MODULE.md 约束 88）
  - typing 模块统一改为内置泛型：Dict→dict、List→list、Optional[X]→X | None、Tuple→tuple（Python 3.9+）
  - 修复原因：代码bug（1项）+ 规范缺失（MODULE.md 新增约束87/88）+ 类型注解风格不一致

- v2.12 (2026-05-27 18:00): CLI与注释规范化
  - CLI 入口退出码修复：删除无效 try/except，检查 result['success'] 后 sys.exit(0/1)（遵循 MODULE.md 约束 89）
  - is_valid_main_board_stock 注释修正：说明顺序约束是 ST 必须在 S 之前，而非误导性的 "*ST 避免 S*ST"
  - validate_cache ST 检查修复：对 S 开头补充排除 ST 和 *ST，与 is_valid_main_board_stock 严格一致
  - save_cache 引用修改说明补充：添加前提警告，说明 existing_stocks 不可被 deepcopy（遵循 MODULE.md 约束 90）
  - 修复原因：死代码清理（1项）+ 注释误导（1项）+ 逻辑不一致（1项）+ 引用修改隐患（1项）

- v2.13 (2026-05-27 18:30): 返回数据完整性修复
  - refresh_stock_cache 验证失败数据填充：在 raise 前填充 cache_data 统计数据，避免 except 块返回空数据（遵循 MODULE.md 约束 91）
  - removed_codes_truncated 字段添加：result 返回字典中新增截断标识，让调用方感知数据完整性
  - validate_cache 格式检查注释补全：说明抽查范围局限性，删除冗余 enumerate 变量 i
  - 修复原因：验证失败返回空数据（1项）+ 返回数据截断无提示（1项）+ 冗余变量（1项）

- v2.14 (2026-05-27 12:30): 输出目录规范化
  - 输出文件统一到 result 目录（遵循 MODULE.md 约束 2）
  - 删除 cache 目录输出（违反规范）
  - 合并 CACHE_FILE 和 RESULT_FILE 为 OUTPUT_FILE
  - 删除 ensure_cache_dir 函数（不再需要）
  - 删除 get_cache_dir 导入（不再需要）
  - 修复原因：违反 MODULE.md 约束 2（输出到 result 目录）

作者: 云瑶
日期: 2026-04-02
"""

import json
import logging
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import requests  # 新浪财经 API HTTP 请求（第三方库，遵循 PEP 8）

# 公共模块导入
from data_fetchers.common import (
    get_module_logs_dir,
    get_module_result_dir,
    setup_logger,
    write_json_cache,
)
from data_fetchers.common.http_client import create_sina_session


__all__ = [
    "refresh_stock_cache",
    "load_cache",
    "get_cached_stock_codes",
    "is_valid_main_board_stock",
    "determine_market",
]


# ============================================================
# 配置常量
# ============================================================

# 输出版本（遵循 MODULE.md 约束 16）
_OUTPUT_VERSION = "2.14"

# 新浪财经 API 端点
SINA_API_URL = "http://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/Market_Center.getHQNodeData"

# API 请求配置
API_TIMEOUT = 30  # 超时时间（秒）
API_RETRIES = 3  # 重试次数
API_DELAY = 0.5  # 请求间隔（秒）

# 完整性验证阈值
MIN_TOTAL_STOCKS = 2500  # 最低股票数量
WARN_TOTAL_STOCKS = 2800  # 警告阈值
EXPECTED_SH_MIN = 1500  # 沪市主板最低预期
EXPECTED_SZ_MIN = 1200  # 深市主板最低预期

# ST 股票前缀常量（遵循 MODULE.md 约束 16：常量提取）
# 使用具名常量而非 dict，避免键名拼写错误在运行时才报 KeyError
# 检查顺序为 *ST → ST → S_PREFIX，确保逻辑清晰
ST_PREFIX_STAR = "*ST"  # *ST 退市风险警示（包括 S*ST）
ST_PREFIX_ST = "ST"  # ST 风险警示（包括 SST）
ST_PREFIX_S = "S"  # S 开头股票（排除 ST 和 *ST 的纯 S 开头历史特殊处理）


# ============================================================
# 日志配置（复用公共模块）
# ============================================================

# 获取脚本名（不含 .py）
_SCRIPT_NAME = Path(__file__).stem

# 日志文件路径（遵循 PROJECT.md 第621-668行规范）
_LOGS_DIR = get_module_logs_dir()

# 输出文件路径（遵循 MODULE.md 约束 2：输出到 result 目录）
_RESULT_DIR = get_module_result_dir()
OUTPUT_FILE = _RESULT_DIR / "stock_list.json"


def _get_logger() -> logging.Logger:
    """
    获取日志记录器（复用公共模块）

    Returns:
        配置好的 Logger 对象
    """
    return setup_logger(_SCRIPT_NAME, logs_dir=_LOGS_DIR)


# 模块级 logger（仅在模块内部使用）
logger = _get_logger()


# ============================================================
# 股票筛选逻辑
# ============================================================


def is_valid_main_board_stock(code: str, name: str) -> bool:
    """
    判断是否为有效的主板股票

    Args:
        code: 股票代码（如 "600000"）
        name: 股票名称（如 "浦发银行"）

    Returns:
        True: 有效主板股票，应保留
        False: 应剔除

    Example:
        >>> is_valid_main_board_stock("600000", "浦发银行")
        True
        >>> is_valid_main_board_stock("300001", "特锐德")
        False  # 创业板
    """
    # 剔除规则 - 先判断剔除条件

    # 1. 创业板（30开头）
    if code.startswith("30"):
        return False

    # 2. 科创板（688开头）
    if code.startswith("688"):
        return False

    # 3. 北交所（8开头、4开头）
    if code.startswith("8") or code.startswith("4"):
        return False

    # 4. ST类股票（前缀匹配，遵循 MODULE.md 约束 79）
    # ST 股票命名规则（按优先级检查）：
    # 顺序约束：ST 和 *ST 必须在纯 S 检查之前，否则 "ST某某"会被 S_PREFIX 先匹配
    # *ST 和 ST 之间顺序无强制要求（*ST 不以 ST 开头，互不干扰）
    name_upper = name.upper()

    # 剔除 *ST（退市风险警示，包括 S*ST）
    if name_upper.startswith(ST_PREFIX_STAR):  # '*ST'
        return False

    # 剔除 ST（风险警示，包括 SST）
    # 顺序：必须在 S_PREFIX 之前检查，否则 "ST某某"会被 S_PREFIX 误匹配
    if name_upper.startswith(ST_PREFIX_ST):  # 'ST'
        return False

    # 剔除纯 S 开头（排除 ST 和 *ST 前缀后的剩余股票）
    # 顺序：必须在 ST 和 *ST 之后，确保 "ST某某"和"SST某某"已被正确归类
    # 此时检查的是不含 ST/*ST 前缀的纯 S 开头历史特殊处理股票
    if name_upper.startswith(ST_PREFIX_S):  # 'S'
        return False

    # 5. 退市股票
    if "退市" in name:
        return False

    # 保留规则 - 判断是否为主板

    # 沪市主板（60开头）
    if code.startswith("60"):
        return True

    # 深市主板（00开头，含003）
    return code.startswith("00")  # noqa: SIM103

    # 其他情况剔除
    return False


def determine_market(code: str) -> str:
    """
    判断股票所属市场

    Args:
        code: 股票代码

    Returns:
        'sh': 沪市, 'sz': 深市, 'unknown': 未知

    Example:
        >>> determine_market("600000")
        'sh'
        >>> determine_market("000001")
        'sz'
    """
    if code.startswith("60"):
        return "sh"
    elif code.startswith("00"):
        return "sz"
    else:
        return "unknown"


# ============================================================
# API 数据获取
# ============================================================


def fetch_stocks_from_sina(logger_arg: logging.Logger | None = None) -> tuple[list[dict[str, Any]], int]:
    """
    从新浪财经 API 获取股票列表（分页获取所有数据）

    Args:
        logger_arg: 日志记录器（可选，默认使用模块级 logger）

    Returns:
        Tuple[List[Dict], int]: (股票信息列表, API请求页数)
        股票信息格式：[{'code': str, 'name': str, 'market': str}, ...]

    Raises:
        RuntimeError: API 获取失败

    Example:
        >>> stocks, pages = fetch_stocks_from_sina()
        >>> len(stocks) > 2500  # 主板股票数量检查
        True
    """
    # 遵循 PROJECT.md 日志参数规范：使用 logger_arg 避免遮蔽模块级 logger
    _logger = logger_arg or logger

    _logger.info("从新浪财经 API 获取主板股票...")

    all_stocks: list[dict[str, Any]] = []

    # 新浪API节点说明：
    # sh_a - 沪市A股
    # sz_a - 深市A股
    nodes = [
        {"node": "sh_a", "desc": "沪市A股"},
        {"node": "sz_a", "desc": "深市A股"},
    ]

    total_pages = 0
    page_size = 80  # 每页获取80条，这是需求文档建议的值

    # 使用 with 语句确保 Session 资源释放（遵循 Python 最佳实践）
    with create_sina_session(logger=_logger) as session:
        for node_info in nodes:
            _logger.info("  获取 %s...", node_info["desc"])

            page = 1
            node_stocks_count = 0

            while True:
                # 新浪API参数（分页获取）
                params = {
                    "page": page,
                    "num": page_size,
                    "node": node_info["node"],
                    "sort": "symbol",
                    "asc": 1,
                    "_s_r_a": "page",
                }

                data: list[dict[str, Any]] | None = None

                # 重试逻辑：成功则 break，失败则最后一次重试 raise（遵循 MODULE.md 约束 84）
                for attempt in range(API_RETRIES):
                    try:
                        # 重试时添加延迟
                        if attempt > 0:
                            delay = API_DELAY * (attempt + 1) * 2
                            _logger.info("    重试 %s/%s，等待 %.1f秒...", attempt, API_RETRIES, delay)
                            time.sleep(delay)

                        response = session.get(SINA_API_URL, params=params, timeout=API_TIMEOUT)
                        response.raise_for_status()

                        # 解析 JSON 响应
                        data = response.json()
                        # 成功则跳出循环
                        break

                    except requests.exceptions.Timeout:
                        _logger.warning("    ! 请求超时 (第 %s 页)", page)
                        # 最后一次重试失败则 raise，否则继续下一次重试
                        if attempt == API_RETRIES - 1:
                            raise RuntimeError(f"请求超时，已重试 {API_RETRIES} 次") from None
                        # 非最后一次失败，显式 continue 进入下一次重试
                        continue

                    except requests.exceptions.RequestException as e:
                        _logger.warning("    ! 请求失败: %s (第 %s 页)", e, page)
                        # 最后一次重试失败则 raise，否则继续下一次重试
                        if attempt == API_RETRIES - 1:
                            raise RuntimeError(f"请求失败: {e}，已重试 {API_RETRIES} 次") from e
                        # 非最后一次失败，显式 continue 进入下一次重试
                        continue

                    except json.JSONDecodeError as e:
                        _logger.warning("    ! JSON解析失败: %s (第 %s 页)", e, page)
                        # 最后一次重试失败则 raise，否则继续下一次重试
                        if attempt == API_RETRIES - 1:
                            raise RuntimeError(f"JSON解析失败: {e}，已重试 {API_RETRIES} 次") from e
                        # 非最后一次失败，显式 continue 进入下一次重试
                        continue

                # 类型守卫：确保 data 为有效列表（遵循 MODULE.md 约束 82）
                # 如果所有重试都失败，会进入 except 块并 raise，不会执行到这里
                # 如果成功，会 break 跳出循环，data 为有效值
                if data is None:
                    raise RuntimeError(f"API 返回 None，{node_info['desc']} 第 {page} 页数据异常")

                # 检查返回数据
                if not isinstance(data, list) or len(data) == 0:
                    # 返回空数据，表示已获取完毕
                    _logger.info("    第 %s 页返回空数据，%s 获取完成", page, node_info["desc"])
                    break

                # 处理本页数据
                page_added = 0
                for item in data:
                    code = item.get("code", "")
                    name = item.get("name", "")

                    # 筛选有效主板股票
                    if is_valid_main_board_stock(code, name):
                        market = determine_market(code)
                        all_stocks.append({"code": code, "name": name, "market": market})
                        page_added += 1

                node_stocks_count += page_added
                total_pages += 1
                _logger.info("    第 %s 页: 获取 %s 条，新增主板 %s 只", page, len(data), page_added)

                # 如果返回数据少于页面大小，说明已到最后一页
                if len(data) < page_size:
                    _logger.info("    最后一页，%s 获取完成", node_info["desc"])
                    break

                page += 1

                # 页间延迟，避免请求过快
                time.sleep(0.1)

            _logger.info("    ✓ %s 共获取 %s 只主板股票", node_info["desc"], node_stocks_count)

            # 节点间延迟
            time.sleep(API_DELAY)

    # 去重（session 已关闭，不需要资源）
    seen: set[str] = set()
    unique_stocks: list[dict[str, Any]] = []
    for s in all_stocks:
        if s["code"] not in seen:
            seen.add(s["code"])
            unique_stocks.append(s)

    # 按代码排序
    unique_stocks.sort(key=lambda x: x["code"])

    if len(unique_stocks) == 0:
        raise RuntimeError("API获取失败，未获取到任何主板股票")

    _logger.info("  ✓ 共获取 %s 只主板股票（去重后）", len(unique_stocks))

    return unique_stocks, total_pages


# ============================================================
# 数据完整性验证
# ============================================================


def validate_cache(cache_data: dict[str, Any]) -> dict[str, Any]:
    """
    验证缓存数据完整性

    Args:
        cache_data: 缓存数据字典

    Returns:
        验证结果字典：
        {
            'passed': bool,
            'warnings': list[str],
            'errors': list[str],
            'stats': dict[str, int]
        }

    Example:
        >>> result = validate_cache(cache_data)
        >>> result["passed"]
        True
    """
    result: dict[str, Any] = {"passed": True, "warnings": [], "errors": [], "stats": {}}

    stocks = cache_data.get("stocks", [])

    # 1. 数量检查
    total = len(stocks)
    result["stats"]["total"] = total

    if total < WARN_TOTAL_STOCKS:
        result["warnings"].append(f"股票总数偏低: {total}，预期 {WARN_TOTAL_STOCKS}+")

    if total < MIN_TOTAL_STOCKS:
        result["errors"].append(f"股票总数异常: {total}，预期 {MIN_TOTAL_STOCKS}+")
        result["passed"] = False

    # 2. ST股票混入检查（复用 is_valid_main_board_stock 的 ST 检查逻辑）
    # 直接调用 is_valid_main_board_stock，若返回 False 且原因是 ST 前缀，则为 ST 混入
    # 这样保证 validate_cache 与 is_valid_main_board_stock 的 ST 检查逻辑严格一致
    st_stocks = []
    for s in stocks:
        # 使用 is_valid_main_board_stock 判断是否应被过滤
        # 若返回 False，检查是否因 ST 前缀而非其他原因（创业板、科创板等）
        if not is_valid_main_board_stock(s["code"], s["name"]):
            name_upper = s["name"].upper()
            # 只检查 ST 前缀匹配（排除创业板、科创板、北交所、退市等其他原因）
            # 顺序与 is_valid_main_board_stock 一致：*ST → ST → S
            is_st_prefix = (
                name_upper.startswith(ST_PREFIX_STAR)  # *ST
                or name_upper.startswith(ST_PREFIX_ST)  # ST（不含 *ST）
                or (
                    name_upper.startswith(ST_PREFIX_S)  # 纯 S 开头（排除 ST 和 *ST）
                    and not name_upper.startswith(ST_PREFIX_ST)
                    and not name_upper.startswith(ST_PREFIX_STAR)
                )
            )
            if is_st_prefix:
                st_stocks.append(s)

    if st_stocks:
        result["errors"].append(f"发现ST股票混入: {[s['code'] for s in st_stocks[:5]]}")
        result["passed"] = False

    # 3. 创业板混入检查
    gem_stocks = [s for s in stocks if s["code"].startswith("30")]
    if gem_stocks:
        result["errors"].append(f"发现创业板股票混入: {[s['code'] for s in gem_stocks[:5]]}")
        result["passed"] = False

    # 4. 科创板混入检查
    star_stocks = [s for s in stocks if s["code"].startswith("688")]
    if star_stocks:
        result["errors"].append(f"发现科创板股票混入: {[s['code'] for s in star_stocks[:5]]}")
        result["passed"] = False

    # 5. 北交所混入检查
    bjb_stocks = [s for s in stocks if s["code"].startswith("8") or s["code"].startswith("4")]
    if bjb_stocks:
        result["errors"].append(f"发现北交所股票混入: {[s['code'] for s in bjb_stocks[:5]]}")
        result["passed"] = False

    # 6. 市场分布检查
    sh_count = len([s for s in stocks if s["market"] == "sh"])
    sz_count = len([s for s in stocks if s["market"] == "sz"])

    result["stats"]["sh_count"] = sh_count
    result["stats"]["sz_count"] = sz_count

    if sh_count < EXPECTED_SH_MIN:
        result["warnings"].append(f"沪市主板数量偏低: {sh_count}，预期 {EXPECTED_SH_MIN}+")

    if sz_count < EXPECTED_SZ_MIN:
        result["warnings"].append(f"深市主板数量偏低: {sz_count}，预期 {EXPECTED_SZ_MIN}+")

    # 7. 数据格式检查
    # 抽查范围：仅检查前10条数据，存在盲区（第11条及之后可能缺少必需字段）
    # 局限性说明：数据量大时无法全覆盖，但该检查旨在快速发现常见格式问题
    # 若需要全覆盖检查，应改为完整迭代并记录所有缺失字段的股票代码
    required_fields = ["code", "name", "market"]
    for stock in stocks[:10]:  # 抽查前10条
        for field in required_fields:
            if field not in stock:
                result["errors"].append(f"股票数据格式错误，缺少字段 '{field}'")
                result["passed"] = False
                break

    return result


# ============================================================
# 缓存文件操作
# ============================================================


def ensure_result_dir(logger_arg: logging.Logger | None = None) -> None:
    """确保结果目录存在"""
    _logger = logger_arg or logger
    _RESULT_DIR.mkdir(parents=True, exist_ok=True)
    _logger.info("确保结果目录存在: %s", _RESULT_DIR)


def save_cache(
    new_stocks: list[dict[str, Any]], api_pages: int, logger_arg: logging.Logger | None = None
) -> dict[str, Any]:
    """
    增量更新股票列表到持久化文件

    新增：API有但文件没有 → 添加
    删除：文件有但API没有 → 删除（退市/ST）
    保留：两边都有 → 保留

    Args:
        new_stocks: 从 API 获取的新股票列表
        api_pages: API 请求页数
        logger_arg: 日志记录器（可选，遵循 PROJECT.md 日志参数规范）

    Returns:
        缓存数据字典，包含统计信息

    Example:
        >>> cache_data = save_cache(stocks, api_pages)
        >>> cache_data["meta"]["total_count"]
        3000+
    """
    # 遵循 PROJECT.md 日志参数规范：使用 logger_arg 避免遮蔽模块级 logger
    _logger = logger_arg or logger

    ensure_result_dir(_logger)

    # 遵循 MODULE.md 约束 17：datetime.now() 只调用一次
    now = datetime.now()
    today = now.strftime("%Y-%m-%d")
    timestamp = now.isoformat()

    # 加载现有数据（传递 logger 参数，遵循 MODULE.md 约束 33）
    existing_data = load_cache(logger_arg=_logger)
    existing_stocks = existing_data.get("stocks", []) if existing_data else []

    _logger.info("  现有股票: %s 只", len(existing_stocks))
    _logger.info("  API股票: %s 只", len(new_stocks))

    # 构建代码集合用于快速查找
    api_stock_codes = set(s["code"] for s in new_stocks)
    existing_stock_codes = set(s["code"] for s in existing_stocks)

    # 找出新增的股票（API有但文件没有）
    added_stocks: list[dict[str, Any]] = []
    for stock in new_stocks:
        if stock["code"] not in existing_stock_codes:
            added_stocks.append(
                {"code": stock["code"], "name": stock["name"], "market": stock["market"], "added_at": today}
            )

    added_count = len(added_stocks)

    # 找出删除的股票（文件有但API没有 → 退市/ST）
    removed_codes_full = list(existing_stock_codes - api_stock_codes)
    removed_count = len(removed_codes_full)
    # 截断 removed_codes 避免 JSON 文件过大（遵循 MODULE.md 约束 86）
    removed_codes = removed_codes_full[:50]
    removed_codes_truncated = removed_count > 50

    # 更新已存在股票的 name 字段（遵循 MODULE.md 约束 81）
    # 注意：existing_stock_map 中的字典是 existing_stocks 的引用
    # 修改 existing_stock['name'] 会直接更新 existing_stocks 中的对象
    # 这是预期的行为，避免不必要的复制开销
    #
    # ⚠️ 关键前提：existing_stocks 中的 dict 对象在此代码块之前不可被 copy.deepcopy 或其他方式复制
    # 若被复制，引用修改会静默失效：updated_count 计数正确但 all_stocks 中的数据不会更新
    # （遵循 MODULE.md 约束 90：引用修改依赖说明）
    updated_count = 0
    existing_stock_map = {s["code"]: s for s in existing_stocks}
    new_stock_map = {s["code"]: s for s in new_stocks}

    for code, existing_stock in existing_stock_map.items():
        if code in new_stock_map:
            new_stock = new_stock_map[code]
            if existing_stock.get("name") != new_stock.get("name"):
                existing_stock["name"] = new_stock["name"]
                updated_count += 1

    # 只保留API中存在的股票（删除退市/ST）
    # 使用完整的 removed_codes_full 过滤，而非截断后的 removed_codes
    # 避免 removed_codes 截断导致部分退市股票仍留在数据中
    all_stocks = [s for s in existing_stocks if s["code"] not in removed_codes_full]

    # 添加新增股票
    all_stocks.extend(added_stocks)

    # 按代码排序
    all_stocks.sort(key=lambda x: x["code"])

    # 统计
    sh_count = len([s for s in all_stocks if s["market"] == "sh"])
    sz_count = len([s for s in all_stocks if s["market"] == "sz"])

    # 构建缓存数据（股票列表保留在 cache 目录）
    cache_data: dict[str, Any] = {
        "meta": {
            "last_updated": timestamp,
            "source": "sina_api",
            "total_count": len(all_stocks),
            "sh_count": sh_count,
            "sz_count": sz_count,
            "added_count": added_count,
            "removed_count": removed_count,
            "updated_count": updated_count,
            "removed_codes": removed_codes,
            "removed_codes_truncated": removed_codes_truncated,
            "existing_count": len(existing_stocks),
            "api_pages": api_pages,
            "version": _OUTPUT_VERSION,
        },
        "stocks": all_stocks,
        "codes": [s["code"] for s in all_stocks],
    }

    # 写入缓存文件（cache 目录，使用公共模块原子写入）
    write_json_cache(OUTPUT_FILE, cache_data, json_indent=2, logger=_logger)

    _logger.info("结果文件已保存: %s", OUTPUT_FILE)

    return cache_data


def load_cache(logger_arg: logging.Logger | None = None) -> dict[str, Any] | None:
    """
    加载缓存文件

    Args:
        logger_arg: 日志记录器（可选，遵循 PROJECT.md 日志参数规范）

    Returns:
        缓存数据字典，如果不存在则返回 None

    Example:
        >>> cache_data = load_cache()
        >>> if cache_data:
        ...     print(cache_data["meta"]["total_count"])
    """
    # 遵循 PROJECT.md 日志参数规范：使用 logger_arg 避免遮蔽模块级 logger
    _logger = logger_arg or logger

    if not OUTPUT_FILE.exists():
        return None

    try:
        with open(OUTPUT_FILE, encoding="utf-8") as f:
            data = json.load(f)

        # 类型校验：确保返回的是 dict 类型（遵循 MODULE.md 约束 87）
        # 若缓存文件被写入了非 dict 类型（如列表），后续调用方用 .get() 会抛出 AttributeError
        if not isinstance(data, dict):
            _logger.warning("缓存文件内容类型异常: 期望 dict，实际 %s", type(data).__name__)
            return None

        return data
    except Exception as e:
        # 捕获所有异常（遵循 MODULE.md 约束 55）
        # 包括：json.JSONDecodeError、PermissionError、IsADirectoryError、OSError 等
        _logger.error("加载缓存失败: [%s]: %s", type(e).__name__, e)
        return None


def get_cached_stock_codes() -> list[str]:
    """
    获取缓存的股票代码列表

    Returns:
        股票代码列表，如果缓存不存在或无效则返回空列表

    Example:
        >>> codes = get_cached_stock_codes()
        >>> len(codes) > 2500  # 主板股票数量检查
        True
    """
    cache_data = load_cache()
    if cache_data and "codes" in cache_data:
        return cache_data["codes"]
    return []


# ============================================================
# 主函数
# ============================================================


def refresh_stock_cache(logger_arg: logging.Logger | None = None) -> dict[str, Any]:
    """
    增量更新股票列表持久化文件

    这是主入口函数，从新浪API获取主板股票列表，
    新增：API有但文件没有 → 添加
    删除：文件有但API没有 → 删除（退市/ST）
    保留：两边都有 → 保留

    Args:
        logger_arg: 日志记录器（可选，遵循 PROJECT.md 日志参数规范）

    Returns:
        {
            "success": True/False,
            "total_count": int,
            "added_count": int,
            "removed_count": int,
            "removed_codes": list[str],
            "existing_count": int,
            "sh_count": int,
            "sz_count": int,
            "message": str,
            "cache_file": str,
            "result_file": str,
            "warnings": list[str]
        }

    Note:
        函数总是返回字典，失败时 success=False。调用方无需 try/except。

    Example:
        >>> result = refresh_stock_cache()
        >>> result["success"]
        True
    """
    # 遵循 PROJECT.md 日志参数规范：使用 logger_arg 避免遮蔽模块级 logger
    _logger = logger_arg or logger

    _logger.info("开始增量更新股票列表")
    start_time = time.time()

    result: dict[str, Any] = {
        "success": False,
        "total_count": 0,
        "added_count": 0,
        "removed_count": 0,
        "updated_count": 0,
        "removed_codes": [],
        "removed_codes_truncated": False,
        "existing_count": 0,
        "sh_count": 0,
        "sz_count": 0,
        "message": "",
        "output_file": str(OUTPUT_FILE),
        "warnings": [],
    }

    try:
        # Step 1: 从 API 获取数据
        stocks, api_pages = fetch_stocks_from_sina(_logger)

        # Step 2: 增量更新持久化文件
        cache_data = save_cache(stocks, api_pages, _logger)

        # Step 3: 验证完整性
        validation = validate_cache(cache_data)

        if not validation["passed"]:
            error_msg = "; ".join(validation["errors"])
            # 验证失败时，先填充已知数据再 raise（遵循 MODULE.md 约束 91）
            # 这样 except 块捕获后 result 中已有统计数据，调用方可获知实际写入数量
            added_count = cache_data["meta"].get("added_count", 0)
            removed_count = cache_data["meta"].get("removed_count", 0)
            updated_count = cache_data["meta"].get("updated_count", 0)
            removed_codes = cache_data["meta"].get("removed_codes", [])
            removed_codes_truncated = cache_data["meta"].get("removed_codes_truncated", False)
            existing_count = cache_data["meta"].get("existing_count", 0)

            result["total_count"] = len(cache_data.get("stocks", []))
            result["added_count"] = added_count
            result["removed_count"] = removed_count
            result["updated_count"] = updated_count
            result["removed_codes"] = removed_codes
            result["removed_codes_truncated"] = removed_codes_truncated
            result["existing_count"] = existing_count
            result["sh_count"] = len([s for s in cache_data.get("stocks", []) if s.get("market") == "sh"])
            result["sz_count"] = len([s for s in cache_data.get("stocks", []) if s.get("market") == "sz"])

            raise RuntimeError(f"数据验证失败: {error_msg}")

        # 收集警告
        if validation["warnings"]:
            for warning in validation["warnings"]:
                _logger.warning("  ⚠️ %s", warning)
            result["warnings"] = validation["warnings"]

        # Step 4: 返回结果
        elapsed_time = time.time() - start_time

        added_count = cache_data["meta"].get("added_count", 0)
        removed_count = cache_data["meta"].get("removed_count", 0)
        updated_count = cache_data["meta"].get("updated_count", 0)
        removed_codes = cache_data["meta"].get("removed_codes", [])
        removed_codes_truncated = cache_data["meta"].get("removed_codes_truncated", False)
        existing_count = cache_data["meta"].get("existing_count", 0)

        result["success"] = True
        result["total_count"] = validation["stats"]["total"]
        result["added_count"] = added_count
        result["removed_count"] = removed_count
        result["updated_count"] = updated_count
        result["removed_codes"] = removed_codes
        result["removed_codes_truncated"] = removed_codes_truncated
        result["existing_count"] = existing_count
        result["sh_count"] = validation["stats"]["sh_count"]
        result["sz_count"] = validation["stats"]["sz_count"]

        _logger.info("验证通过，写入持久化文件")
        _logger.info("增量更新完成，耗时 %.1f 秒", elapsed_time)
        _logger.info("  新增 %s 只股票", added_count)
        if updated_count > 0:
            _logger.info("  更新 %s 只股票名称", updated_count)
        if removed_count > 0:
            _logger.info(
                "  删除 %s 只股票（退市/ST）: %s%s",
                removed_count,
                ", ".join(removed_codes[:10]),
                "..." if removed_count > 10 else "",
            )
        _logger.info("  总数: %s", result["total_count"])
        _logger.info("  沪市主板: %s", result["sh_count"])
        _logger.info("  深市主板: %s", result["sz_count"])

        # 构建消息
        msg_parts = [f"新增 {added_count} 只"]
        if updated_count > 0:
            msg_parts.append(f"更新 {updated_count} 只名称")
        if removed_count > 0:
            msg_parts.append(f"删除 {removed_count} 只（退市/ST）")
        msg_parts.append(f"共 {result['total_count']} 只（沪{result['sh_count']}+深{result['sz_count']}）")
        result["message"] = f"成功增量更新，{', '.join(msg_parts)}，耗时 {elapsed_time:.1f} 秒"

        return result

    except Exception as e:
        elapsed_time = time.time() - start_time
        error_msg = f"增量更新股票列表失败: [{type(e).__name__}]: {e}"
        _logger.error(error_msg)
        result["success"] = False
        result["message"] = error_msg
        # 总是返回字典，而非 raise（遵循 MODULE.md 约束 88）
        # 调用方只需检查 result['success'] 即可，无需 try/except
        return result


# ============================================================
# CLI 入口
# ============================================================

if __name__ == "__main__":
    import sys

    # 使用公共模块 logger
    cli_logger = _get_logger()

    cli_logger.info("=" * 60)
    cli_logger.info("股票列表增量更新工具")
    cli_logger.info("=" * 60)

    # refresh_stock_cache 总是返回字典（v2.11），不再抛出异常
    # 调用方通过检查 result['success'] 判断成功与否
    result = refresh_stock_cache(cli_logger)

    cli_logger.info("=" * 60)
    cli_logger.info("更新结果")
    cli_logger.info("=" * 60)
    cli_logger.info("  状态: %s", "成功 ✓" if result["success"] else "失败 ✗")
    cli_logger.info("  新增: %s 只", result["added_count"])
    if result.get("updated_count", 0) > 0:
        cli_logger.info("  更新名称: %s 只", result["updated_count"])
    if result["removed_count"] > 0:
        cli_logger.info("  删除: %s 只（退市/ST）", result["removed_count"])
        removed_display = ", ".join(result["removed_codes"][:10])
        if result["removed_count"] > 10:
            removed_display += f"... 等共{result['removed_count']}只"
        cli_logger.info("    删除代码: %s", removed_display)
    cli_logger.info("  现有: %s 只", result["existing_count"])
    cli_logger.info("  总数: %s", result["total_count"])
    cli_logger.info("  沪市主板: %s", result["sh_count"])
    cli_logger.info("  深市主板: %s", result["sz_count"])
    cli_logger.info("  输出文件: %s", result["output_file"])
    cli_logger.info("  消息: %s", result["message"])

    if result["warnings"]:
        cli_logger.warning("警告:")
        for warning in result["warnings"]:
            cli_logger.warning("  ⚠️ %s", warning)

    cli_logger.info("=" * 60)

    # 根据 success 决定退出码（遵循 MODULE.md 约束 89）
    # 失败时 exit(1)，让 shell 脚本能感知失败
    sys.exit(0 if result["success"] else 1)
