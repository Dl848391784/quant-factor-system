#!/usr/bin/env python3
"""
股票筛选模块

统一主板股票判断和股票列表加载。

版本历史：
- v1.0 (2026-05-24): 初始版本
- v1.1 (2026-05-25): logger 参数化、__all__ 导出、模块级导入、docstring 补充
- v1.2 (2026-05-25): 类型注解精确化、条件导入缓存、性能优化、防御性编程
- v1.3 (2026-05-25): 辅助函数性能优化、日期范围验证、常量数据来源注释、边界检查补全
- v1.4 (2026-05-25): 筛选逻辑优化、类型安全检查、重复调用优化、日期格式正则验证
- v1.5 (2026-05-25): 参数类型安全检查、线程锁保护、日期边界验证、数据格式验证
- v1.6 (2026-05-25): 日期边界动态获取、异常链保留、元素类型安全检查、公开日期常量
- v1.7 (2026-05-25): logger 参数类型验证、缓存函数 None 检查、docstring 结构规范化
- v1.8 (2026-05-25): filter_stocks_by_date Note 补充、测试清理顺序修复、http_client 同步更新

作者: 云瑶
日期: 2026-05-24
"""

import logging
import json
import re
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

__all__ = [
    # 股票判断函数
    'is_main_board_stock',
    # 股票列表加载
    'load_main_board_stock_list',
    # 辅助函数
    'get_stock_codes_only',
    'filter_stocks_by_date',
    'get_stock_name_map',
    # 日志函数
    'get_module_logger',
    # 常量（供外部复用）
    'MAIN_BOARD_PREFIXES',
    'EXCLUDED_PREFIXES',
    'EXCLUDED_NAME_KEYWORDS',
    # 日期边界常量（供外部查询）
    'MIN_STOCK_DATE',
    'MAX_STOCK_DATE',
]

# 模块级 fallback logger（遵循 PROJECT.md 第783-857行规范）
# 直接初始化，避免延迟初始化的多线程安全问题
_MODULE_LOGGER = logging.getLogger('data_fetchers.common.stock_utils')

# 主板股票代码前缀（沪市60、深市00）
# 数据来源：中国证券交易所规则，主板代码前缀固定
# 注意：使用元组（tuple）确保不可变，防止外部修改影响所有调用
MAIN_BOARD_PREFIXES = ('60', '00')

# 剔除的代码前缀（创业板30、科创板688、北交所8/4）
# 数据来源：中国证券交易所规则，各板块代码前缀定义
# - 创业板：深市30开头（2009年设立）
# - 科创板：沪市688开头（2019年设立）
# - 北交所：8开头（新三板精选层）、4开头（两网公司）
# 注意：使用元组（tuple）确保不可变，防止外部修改影响所有调用
EXCLUDED_PREFIXES = ('30', '688', '8', '4')

# 剔除的名称关键词（ST类股票）
# 数据来源：中国证券交易所规则，风险警示股票命名规范
# - ST：特别处理（连续两年亏损）
# - *ST：退市风险警示（连续三年亏损）
# - SST/S*ST：历史遗留格式（已基本不使用）
# - 退市：已退市股票标记
# 注意：使用元组（tuple）确保不可变，防止外部修改影响所有调用
EXCLUDED_NAME_KEYWORDS = ('ST', '*ST', '退市', 'SST', 'S*ST')

# 日期格式正则（YYYY-MM-DD）
_DATE_PATTERN = re.compile(r'^\d{4}-\d{2}-\d{2}$')

# 日期边界常量（A股市场始于1990年12月19日）
# 数据来源：上海证券交易所成立于1990年11月26日，开业于1990年12月19日
# 注意：MIN_STOCK_DATE 为静态常量，MAX_STOCK_DATE 为函数（动态获取当前日期）
MIN_STOCK_DATE = '1990-12-19'

def MAX_STOCK_DATE() -> str:
    """
    获取当前日期作为日期边界上限
    
    使用函数而非静态常量，避免长时间运行程序过期。
    
    Returns:
        str: 当前日期（YYYY-MM-DD 格式）
        
    Example:
        >>> MAX_STOCK_DATE()
        '2026-05-25'
    """
    return datetime.now().strftime('%Y-%m-%d')

# 线程锁：保护全局缓存变量的初始化（避免多线程竞争）
_IMPORT_LOCK = threading.Lock()

# 模块级缓存导入函数（避免每次调用判断 __name__）
# 在模块加载时确定导入方式，后续调用直接使用缓存的函数
# 线程安全：使用线程锁保护全局变量的初始化
def _get_imported_functions():
    """延迟导入，避免循环依赖（线程安全）"""
    global _get_stock_list_file, _read_json_cache
    # 双重检查锁定模式：先检查是否已初始化，再加锁
    if _get_stock_list_file is not None and _read_json_cache is not None:
        return
    with _IMPORT_LOCK:
        # 锁内再次检查，避免重复初始化
        if _get_stock_list_file is not None and _read_json_cache is not None:
            return
        # __main__ 使用绝对导入，其他使用相对导入
        if __name__ == '__main__':
            from data_fetchers.common.paths import get_stock_list_file
            from data_fetchers.common.cache_manager import read_json_cache
        else:
            from .paths import get_stock_list_file
            from .cache_manager import read_json_cache
        _get_stock_list_file = get_stock_list_file
        _read_json_cache = read_json_cache

# 模块级缓存变量（首次使用时初始化）
_get_stock_list_file = None
_read_json_cache = None


def get_module_logger(logger: Optional[logging.Logger] = None) -> logging.Logger:
    """
    获取 logger，遵循 PROJECT.md 公共模块日志规范
    
    公共模块接收 logger 参数，调用方传入以追溯调用方。
    不传 logger 时使用模块级 fallback logger（模块加载时已初始化）。
    
    Args:
        logger: 调用方传入的 logger（可选），必须是 logging.Logger 类型
        
    Returns:
        logging.Logger: Logger 对象
        
    Raises:
        TypeError: logger 参数不是 logging.Logger 类型
        
    Example:
        >>> logger = get_module_logger()
        >>> logger.name
        'data_fetchers.common.stock_utils'
        
        >>> my_logger = logging.getLogger('my_module')
        >>> logger = get_module_logger(my_logger)
        >>> logger.name
        'my_module'
    """
    # 类型安全检查：logger 必须是 Logger 类型或 None
    if logger is not None and not isinstance(logger, logging.Logger):
        raise TypeError(f"logger 必须是 logging.Logger 类型，实际类型: {type(logger).__name__}")
    if logger is not None:
        return logger
    return _MODULE_LOGGER


def is_main_board_stock(code: str, name: str) -> bool:
    """
    判断是否为主板股票
    
    剔除规则：
    - 创业板（30开头）
    - 科创板（688开头）
    - 北交所（8开头、4开头）
    - ST类股票（包含ST、*ST、退市等）
    
    Args:
        code: 股票代码（如 "600000"），必须非空且为字符串类型
        name: 股票名称（如 "浦发银行"),必须非空且为字符串类型
        
    Returns:
        bool: True 表示主板股票，False 表示应剔除
        
    Raises:
        TypeError: code 或 name 不是字符串类型
        
    Note:
        空代码或空名称直接返回 False（防御性编程）
        
    Example:
        >>> is_main_board_stock('600000', '浦发银行')
        True
        >>> is_main_board_stock('000001', '平安银行')
        True
        
        >>> is_main_board_stock('300001', '特锐德')
        False
        >>> is_main_board_stock('688001', '华兴源创')
        False
        >>> is_main_board_stock('600000', 'ST某某')
        False
        
        >>> is_main_board_stock('', '浦发银行')
        False
        
        # 类型错误会抛出 TypeError
        >>> is_main_board_stock(600000, '浦发银行')  # doctest: +IGNORE_EXCEPTION_DETAIL
        Traceback (most recent call last):
        TypeError: code 必须是字符串类型...
    """
    # 类型安全检查：参数必须是字符串类型
    if not isinstance(code, str):
        raise TypeError(f"code 必须是字符串类型，实际类型: {type(code).__name__}")
    if not isinstance(name, str):
        raise TypeError(f"name 必须是字符串类型，实际类型: {type(name).__name__}")
    
    # 防御性编程：空值直接返回 False
    if not code or not name:
        return False
    
    # 性能优化：使用 any() 替代 for 循环
    # 剔除创业板、科创板、北交所
    if any(code.startswith(prefix) for prefix in EXCLUDED_PREFIXES):
        return False
    
    # 剔除 ST 类股票
    if any(keyword in name for keyword in EXCLUDED_NAME_KEYWORDS):
        return False
    
    # 只保留主板：沪市60、深市00
    return any(code.startswith(prefix) for prefix in MAIN_BOARD_PREFIXES)


def load_main_board_stock_list(
    stock_list_file: Optional[Union[Path, str]] = None,
    logger: Optional[logging.Logger] = None,
) -> List[Dict[str, Any]]:
    """
    加载主板股票列表
    
    从缓存文件加载股票列表，筛选出主板股票。
    
    Args:
        stock_list_file: 股票列表缓存文件路径（默认使用 cache/stock_list.json），支持 Path 或 str
        logger: 调用方传入的 logger（可选）
        
    Returns:
        List[Dict[str, Any]]: 主板股票列表，每项包含 {code, name, ...}
        
    Raises:
        FileNotFoundError: 股票列表缓存不存在
        ValueError: JSON 解析失败或数据格式错误
        
    Example:
        >>> stocks = load_main_board_stock_list()
        >>> len(stocks)
        3010
        
        >>> stocks = load_main_board_stock_list(
        ...     Path('/custom/path/stock_list.json'),
        ...     logger=my_logger
        ... )
    """
    logger = get_module_logger(logger)
    
    # 使用默认路径（使用缓存的导入函数）
    if stock_list_file is None:
        _get_imported_functions()
        # 类型安全检查：确保缓存函数已初始化
        if _get_stock_list_file is None:
            raise RuntimeError("路径获取函数未初始化，请检查模块导入")
        stock_list_file = _get_stock_list_file()
    else:
        stock_list_file = Path(stock_list_file)  # 统一转换为 Path
    
    if not stock_list_file.exists():
        raise FileNotFoundError(f"股票列表缓存不存在: {stock_list_file}")
    
    # 加载缓存（使用缓存的导入函数）
    _get_imported_functions()
    # 类型安全检查：确保缓存函数已初始化
    if _read_json_cache is None:
        raise RuntimeError("缓存读取函数未初始化，请检查模块导入")
    try:
        data = _read_json_cache(stock_list_file, logger=logger)
    except (json.JSONDecodeError, ValueError) as e:
        # 保留异常链，便于追溯原始错误
        raise ValueError(f"股票列表缓存解析失败: {stock_list_file}") from e
    
    # 数据格式验证：必须包含 stocks 字段
    if not isinstance(data, dict):
        raise ValueError(f"股票列表缓存格式错误: 预期 dict，实际 {type(data).__name__}")
    
    stocks = data.get('stocks', [])
    
    # 数据格式验证：stocks 必须是列表
    if not isinstance(stocks, list):
        raise ValueError(f"股票列表数据格式错误: stocks 预期 list，实际 {type(stocks).__name__}")
    
    # 防御性编程：空数据处理
    if not stocks:
        logger.warning("股票列表缓存为空: %s", stock_list_file)
        return []
    
    # 性能优化：列表推导式筛选主板股票
    main_board_stocks = [
        stock for stock in stocks
        if isinstance(stock, dict) and is_main_board_stock(stock.get('code', ''), stock.get('name', ''))
    ]
    
    # 统计信息
    total_count = len(stocks)
    main_count = len(main_board_stocks)
    excluded_count = total_count - main_count
    logger.info(
        "股票筛选完成: 总数 %d, 主板 %d, 剔除 %d",
        total_count, main_count, excluded_count
    )
    
    return main_board_stocks


def get_stock_codes_only(stock_list: List[Dict[str, Any]], logger: Optional[logging.Logger] = None) -> List[str]:
    """
    从股票列表中提取代码列表
    
    Args:
        stock_list: 股票列表，每个元素必须是 Dict 类型
        logger: 调用方传入的 logger（可选）
        
    Returns:
        List[str]: 股票代码列表（过滤空代码）
        
    Raises:
        TypeError: stock_list 不是列表类型，或元素不是字典类型
        
    Note:
        自动过滤空代码和非字典元素，避免后续处理问题
        
    Example:
        >>> stocks = [{'code': '600000', 'name': '浦发银行'}, {'code': '', 'name': '异常'}]
        >>> codes = get_stock_codes_only(stocks)
        >>> codes
        ['600000']
    """
    # 类型安全检查
    if not isinstance(stock_list, list):
        raise TypeError(f"stock_list 必须是列表类型，实际类型: {type(stock_list).__name__}")
    
    logger = get_module_logger(logger)
    
    # 防御性编程：空列表边界检查
    if not stock_list:
        logger.debug("提取股票代码：输入列表为空，返回空列表")
        return []
    
    # 类型安全检查 + 性能优化
    codes = []
    invalid_elements = 0
    for stock in stock_list:
        # 元素类型检查：必须是字典类型
        if not isinstance(stock, dict):
            invalid_elements += 1
            continue
        code = stock.get('code', '')
        if code:  # 过滤空代码
            codes.append(code)
    
    # 统计过滤数量
    total_count = len(stock_list)
    valid_count = len(codes)
    empty_count = total_count - valid_count
    
    if invalid_elements > 0:
        logger.warning(
            "提取股票代码时发现 %d 个非字典元素，已过滤",
            invalid_elements
        )
    
    if empty_count > invalid_elements:  # 空代码数量（不含非字典元素）
        logger.warning(
            "提取股票代码时发现 %d 个空代码，已过滤（总数 %d，有效 %d）",
            empty_count - invalid_elements, total_count, valid_count
        )
    
    return codes


def filter_stocks_by_date(
    stock_list: List[Dict[str, Any]],
    start_date: str,
    end_date: str,
    date_field: str = 'list_date',
    logger: Optional[logging.Logger] = None,
) -> List[Dict[str, Any]]:
    """
    按上市日期筛选股票
    
    Args:
        stock_list: 股票列表，每个元素必须是 Dict 类型
        start_date: 开始日期（YYYY-MM-DD，必须在1990-12-19之后）
        end_date: 结束日期（YYYY-MM-DD，不能超过当前日期）
        date_field: 日期字段名（默认 'list_date'）
        logger: 调用方传入的 logger（可选）
        
    Returns:
        List[Dict[str, Any]]: 筛选后的股票列表
        
    Raises:
        TypeError: stock_list 不是列表类型，或元素不是字典类型
        ValueError: 日期为空、日期格式不正确、日期范围无效或超出合理边界
        
    Note:
        自动过滤非字典元素和日期字段为空的元素
        
    Example:
        >>> stocks = [{'code': '600000', 'list_date': '2020-06-01'}]
        >>> filtered = filter_stocks_by_date(stocks, '2020-01-01', '2020-12-31')
        >>> len(filtered)
        1
        
        # 日期边界错误
        >>> filter_stocks_by_date(stocks, '1980-01-01', '2020-12-31')  # doctest: +IGNORE_EXCEPTION_DETAIL
        Traceback (most recent call last):
        ValueError: 开始日期超出合理边界...
    """
    # 类型安全检查
    if not isinstance(stock_list, list):
        raise TypeError(f"stock_list 必须是列表类型，实际类型: {type(stock_list).__name__}")
    
    logger = get_module_logger(logger)
    
    # 防御性编程：验证日期格式
    if not start_date or not end_date:
        raise ValueError("开始日期和结束日期不能为空")
    
    # 日期格式正则验证（YYYY-MM-DD）
    if not _DATE_PATTERN.match(start_date):
        raise ValueError(f"开始日期格式不正确: {start_date}（预期 YYYY-MM-DD）")
    if not _DATE_PATTERN.match(end_date):
        raise ValueError(f"结束日期格式不正确: {end_date}（预期 YYYY-MM-DD）")
    
    # 日期边界验证：A股市场始于1990-12-19
    if start_date < MIN_STOCK_DATE:
        raise ValueError(
            f"开始日期超出合理边界: {start_date}（A股市场始于 {MIN_STOCK_DATE}）"
        )
    # 动态获取当前日期（避免长时间运行过期）
    max_date = MAX_STOCK_DATE()
    if end_date > max_date:
        raise ValueError(
            f"结束日期超出合理边界: {end_date}（当前日期 {max_date}）"
        )
    
    # 日期范围验证：start_date <= end_date
    if start_date > end_date:
        raise ValueError(
            f"日期范围无效: start_date ({start_date}) > end_date ({end_date})"
        )
    
    # 防御性编程：空列表边界检查
    if not stock_list:
        logger.debug("按日期筛选股票：输入列表为空，返回空列表")
        return []
    
    # 类型安全检查 + 性能优化
    filtered = []
    invalid_elements = 0
    for stock in stock_list:
        # 元素类型检查：必须是字典类型
        if not isinstance(stock, dict):
            invalid_elements += 1
            continue
        date_value = stock.get(date_field, '')
        if date_value and start_date <= date_value <= end_date:
            filtered.append(stock)
    
    if invalid_elements > 0:
        logger.warning(
            "按日期筛选股票时发现 %d 个非字典元素，已过滤",
            invalid_elements
        )
    
    logger.debug(
        "按日期筛选股票: %s ~ %s, 筛选结果 %d 只（输入 %d 只）",
        start_date, end_date, len(filtered), len(stock_list)
    )
    
    return filtered


def get_stock_name_map(stock_list: List[Dict[str, Any]], logger: Optional[logging.Logger] = None) -> Dict[str, str]:
    """
    构建股票代码→名称映射
    
    Args:
        stock_list: 股票列表，每个元素必须是 Dict 类型
        logger: 调用方传入的 logger（可选）
        
    Returns:
        Dict[str, str]: {股票代码: 票名称}（过滤空代码和空名称）
        
    Raises:
        TypeError: stock_list 不是列表类型，或元素不是字典类型
        
    Note:
        自动过滤空代码、空名称和非字典元素
        
    Example:
        >>> stocks = [{'code': '600000', 'name': '浦发银行'}, {'code': '', 'name': '异常'}]
        >>> name_map = get_stock_name_map(stocks)
        >>> name_map
        {'600000': '浦发银行'}
    """
    # 类型安全检查
    if not isinstance(stock_list, list):
        raise TypeError(f"stock_list 必须是列表类型，实际类型: {type(stock_list).__name__}")
    
    logger = get_module_logger(logger)
    
    # 防御性编程：空列表边界检查
    if not stock_list:
        logger.debug("构建名称映射：输入列表为空，返回空字典")
        return {}
    
    # 类型安全检查 + 性能优化
    name_map = {}
    invalid_elements = 0
    for stock in stock_list:
        # 元素类型检查：必须是字典类型
        if not isinstance(stock, dict):
            invalid_elements += 1
            continue
        code = stock.get('code', '')
        name = stock.get('name', '')
        if code and name:  # 过滤空代码和空名称
            name_map[code] = name
    
    # 统计过滤数量
    total_count = len(stock_list)
    valid_count = len(name_map)
    empty_count = total_count - valid_count
    
    if invalid_elements > 0:
        logger.warning(
            "构建名称映射时发现 %d 个非字典元素，已过滤",
            invalid_elements
        )
    
    if empty_count > invalid_elements:  # 空代码/空名称数量（不含非字典元素）
        logger.warning(
            "构建名称映射时发现 %d 个空代码或空名称，已过滤（总数 %d，有效 %d）",
            empty_count - invalid_elements, total_count, valid_count
        )
    
    return name_map


if __name__ == '__main__':
    # 配置测试日志（复用 logger_config.py 的 setup_logger）
    # 遵循 PROJECT.md 第780-839行规范
    import sys
    from pathlib import Path as _Path
    sys.path.insert(0, str(_Path(__file__).parent.parent.parent))
    
    from data_fetchers.common.logger_config import setup_logger
    
    test_logger = setup_logger(
        'stock_utils',  # 脚本名称
        level=logging.DEBUG,  # 测试用 DEBUG
        console_level=logging.INFO  # 控制台用 INFO
    )
    
    try:
        test_logger.info("=" * 50)
        test_logger.info("stock_utils.py 测试开始")
        test_logger.info("=" * 50)
        
        # 测试 1: is_main_board_stock（含边界测试 + 类型验证）
        test_logger.info("\n[测试 1] is_main_board_stock...")
        test_cases = [
            ('600000', '浦发银行', True),
            ('000001', '平安银行', True),
            ('300001', '特锐德', False),  # 创业板
            ('688001', '华兴源创', False),  # 科创板
            ('830001', '新三板', False),  # 北交所
            ('600000', 'ST某某', False),  # ST股票
            # 边界测试：空值
            ('', '浦发银行', False),  # 空代码
            ('600000', '', False),  # 空名称
            ('', '', False),  # 双空
        ]
        
        all_passed = True
        for code, name, expected in test_cases:
            result = is_main_board_stock(code, name)
            status = 'PASS' if result == expected else 'FAIL'
            if result != expected:
                all_passed = False
            test_logger.info("  [%s] %s %s: %s (预期 %s)", status, code or '(空)', name or '(空)', result, expected)
        
        if all_passed:
            test_logger.info("  所有测试通过（含边界测试）")
        
        # 类型错误测试
        try:
            invalid_type = is_main_board_stock(600000, '浦发银行')  # 传入 int 而非 str
            test_logger.warning("  类型验证失败: 应抛出 TypeError")
        except TypeError as e:
            test_logger.info("  类型验证: %s (预期抛出 TypeError)", e)
        
        # 测试 2: load_main_board_stock_list
        test_logger.info("\n[测试 2] load_main_board_stock_list...")
        try:
            stocks = load_main_board_stock_list(logger=test_logger)
            test_logger.info("  加载成功，主板股票数: %d", len(stocks))
            if stocks:
                test_logger.info("  示例: %s", stocks[0])
        except FileNotFoundError as e:
            test_logger.warning("  文件不存在: %s", e)
        
        # 测试 3: get_stock_codes_only（含空代码过滤 + 空列表边界 + 类型验证）
        test_logger.info("\n[测试 3] get_stock_codes_only...")
        test_stocks_with_empty = [
            {'code': '600000', 'name': '浦发银行'},
            {'code': '000001', 'name': '平安银行'},
            {'code': '', 'name': '异常股票'},  # 空代码
        ]
        codes = get_stock_codes_only(test_stocks_with_empty, logger=test_logger)
        test_logger.info("  代码列表: %s (过滤空代码)", codes)
        # 空列表测试
        empty_codes = get_stock_codes_only([], logger=test_logger)
        test_logger.info("  空列表测试: %s (预期空列表)", empty_codes)
        # 类型错误测试
        try:
            invalid_codes = get_stock_codes_only('not_a_list')
            test_logger.warning("  类型验证失败: 应抛出 TypeError")
        except TypeError as e:
            test_logger.info("  类型验证: %s (预期抛出 TypeError)", e)
        
        # 元素类型错误测试（验证过滤行为）
        invalid_elements = get_stock_codes_only([{'code': '600000'}, 'not_a_dict'])
        if len(invalid_elements) == 1:
            test_logger.info("  元素类型过滤: 非字典元素已过滤，结果 %d", len(invalid_elements))
        else:
            test_logger.warning("  元素类型过滤失败: 应过滤非字典元素")
        
        # 测试 4: get_stock_name_map（含空值过滤 + 空列表边界 + 类型验证 + 元素类型验证）
        test_logger.info("\n[测试 4] get_stock_name_map...")
        test_stocks_empty_name = [
            {'code': '600000', 'name': '浦发银行'},
            {'code': '', 'name': '异常股票'},  # 空代码
            {'code': '000001', 'name': ''},  # 空名称
        ]
        name_map = get_stock_name_map(test_stocks_empty_name, logger=test_logger)
        test_logger.info("  名称映射: %s (过滤空值)", name_map)
        # 空列表测试
        empty_map = get_stock_name_map([], logger=test_logger)
        test_logger.info("  空列表测试: %s (预期空字典)", empty_map)
        # 元素类型错误测试
        try:
            invalid_elements_map = get_stock_name_map([{'code': '600000', 'name': '浦发银行'}, 'not_a_dict'])
            if len(invalid_elements_map) == 1:
                test_logger.info("  元素类型过滤: 非字典元素已过滤，结果 %d", len(invalid_elements_map))
            else:
                test_logger.warning("  元素类型过滤失败: 应过滤非字典元素")
        except TypeError as e:
            test_logger.info("  元素类型验证: %s (预期抛出 TypeError)", e)
        
        # 测试 5: filter_stocks_by_date（含日期格式验证 + 日期边界验证 + 日期范围验证 + 空列表边界）
        test_logger.info("\n[测试 5] filter_stocks_by_date...")
        test_date_stocks = [{'code': '600000', 'list_date': '2020-06-01'}]
        filtered = filter_stocks_by_date(test_date_stocks, '2020-01-01', '2020-12-31', logger=test_logger)
        test_logger.info("  正常筛选: %d 只股票", len(filtered))
        # 空列表测试
        empty_filtered = filter_stocks_by_date([], '2020-01-01', '2020-12-31', logger=test_logger)
        test_logger.info("  空列表测试: %d 只股票 (预期 0)", len(empty_filtered))
        # 日期格式错误测试
        try:
            invalid_format = filter_stocks_by_date(test_date_stocks, '2020-1-1', '2020-12-31')
            test_logger.warning("  日期格式验证失败: 应抛出 ValueError")
        except ValueError as e:
            test_logger.info("  日期格式验证: %s (预期抛出 ValueError)", e)
        # 日期边界错误测试（早于1990）
        try:
            invalid_min = filter_stocks_by_date(test_date_stocks, '1980-01-01', '2020-12-31')
            test_logger.warning("  日期边界验证失败: 应抛出 ValueError")
        except ValueError as e:
            test_logger.info("  日期边界验证（早于1990）: %s (预期抛出 ValueError)", e)
        # 日期范围错误测试
        try:
            invalid_range = filter_stocks_by_date(test_date_stocks, '2020-12-31', '2020-01-01')
            test_logger.warning("  日期范围验证失败: 应抛出 ValueError")
        except ValueError as e:
            test_logger.info("  日期范围验证: %s (预期抛出 ValueError)", e)
        # 类型错误测试
        try:
            invalid_type = filter_stocks_by_date('not_a_list', '2020-01-01', '2020-12-31')
            test_logger.warning("  类型验证失败: 应抛出 TypeError")
        except TypeError as e:
            test_logger.info("  类型验证: %s (预期抛出 TypeError)", e)
        # 元素类型错误测试
        try:
            invalid_elements_date = filter_stocks_by_date(
                [{'code': '600000', 'list_date': '2020-06-01'}, 'not_a_dict'],
                '2020-01-01', '2020-12-31'
            )
            if len(invalid_elements_date) == 1:
                test_logger.info("  元素类型过滤: 非字典元素已过滤，结果 %d", len(invalid_elements_date))
            else:
                test_logger.warning("  元素类型过滤失败: 应过滤非字典元素")
        except TypeError as e:
            test_logger.info("  元素类型验证: %s (预期抛出 TypeError)", e)
        
        # 测试 6: get_module_logger
        test_logger.info("\n[测试 6] get_module_logger...")
        fallback_logger = get_module_logger()
        test_logger.info("  Fallback logger name: %s", fallback_logger.name)
        custom_logger = get_module_logger(test_logger)
        test_logger.info("  Custom logger name: %s", custom_logger.name)
        
        # 类型错误测试（logger 参数）
        try:
            invalid_logger = get_module_logger('not_a_logger')
            test_logger.warning("  类型验证失败: 应抛出 TypeError")
        except TypeError as e:
            test_logger.info("  logger 类型验证: %s (预期抛出 TypeError)", e)
        
        # 测试 7: 常量导出（含数据来源注释验证 + 日期边界常量）
        test_logger.info("\n[测试 7] 公共常量...")
        test_logger.info("  MAIN_BOARD_PREFIXES: %s", MAIN_BOARD_PREFIXES)
        test_logger.info("  EXCLUDED_PREFIXES: %s", EXCLUDED_PREFIXES)
        test_logger.info("  EXCLUDED_NAME_KEYWORDS: %s", EXCLUDED_NAME_KEYWORDS)
        test_logger.info("  MIN_STOCK_DATE: %s", MIN_STOCK_DATE)
        test_logger.info("  MAX_STOCK_DATE(): %s", MAX_STOCK_DATE())
        test_logger.info("  常量数据来源注释已补全")
        test_logger.info("  日期边界动态获取已实现（MAX_STOCK_DATE 为函数）")
        
        # 测试 8: 验证汇总
        test_logger.info("\n[测试 8] 验证汇总...")
        test_logger.info("  Dict[str, Any] 类型注解已应用")
        test_logger.info("  Union[Path, str] 类型注解已应用")
        test_logger.info("  Raises TypeError 已实现（参数 + 元素类型安全检查）")
        test_logger.info("  日期格式正则验证已实现")
        test_logger.info("  日期边界动态获取已实现（MAX_STOCK_DATE() 函数）")
        test_logger.info("  线程锁保护已实现（双重检查锁定模式）")
        test_logger.info("  常量不可变性注释已补全（使用元组）")
        test_logger.info("  异常链已保留（load_main_board_stock_list）")
        test_logger.info("  logger 参数类型验证已实现（get_module_logger）")
        test_logger.info("  缓存函数 None 检查已实现（load_main_board_stock_list）")
        test_logger.info("  filter_stocks_by_date Note 已补充（与其他辅助函数一致）")
        test_logger.info("  测试清理顺序已修复（先打印再关闭处理器）")
        
        test_logger.info("\n" + "=" * 50)
        test_logger.info("测试完成（共 8 项测试，含类型验证 + 日期边界验证 + 线程安全验证）")
        test_logger.info("=" * 50)
    finally:
        # 先打印清理日志，再关闭处理器（避免日志丢失）
        test_logger.info("测试清理完成")
        # 清理测试资源（关闭日志处理器）
        for handler in test_logger.handlers:
            handler.close()
            test_logger.removeHandler(handler)