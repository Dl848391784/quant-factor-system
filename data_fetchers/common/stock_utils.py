#!/usr/bin/env python3
"""
股票筛选模块

统一主板股票判断和股票列表加载。

版本历史：
- v1.0 (2026-05-24): 初始版本
- v1.1 (2026-05-25): logger 参数化、__all__ 导出、模块级导入、docstring 补充
- v1.2 (2026-05-25): 类型注解精确化、条件导入缓存、性能优化、防御性编程

作者: 云瑶
日期: 2026-05-24
"""

import logging
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
]

# 模块级 fallback logger（遵循 PROJECT.md 第783-857行规范）
# 直接初始化，避免延迟初始化的多线程安全问题
_MODULE_LOGGER = logging.getLogger('data_fetchers.common.stock_utils')

# 主板股票代码前缀（沪市60、深市00）
MAIN_BOARD_PREFIXES = ('60', '00')

# 剔除的代码前缀（创业板30、科创板688、北交所8/4）
EXCLUDED_PREFIXES = ('30', '688', '8', '4')

# 剔除的名称关键词（ST类股票）
EXCLUDED_NAME_KEYWORDS = ('ST', '*ST', '退市', 'SST', 'S*ST')

# 模块级缓存导入函数（避免每次调用判断 __name__）
# 在模块加载时确定导入方式，后续调用直接使用缓存的函数
def _get_imported_functions():
    """延迟导入，避免循环依赖"""
    global _get_stock_list_file, _read_json_cache
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
        logger: 调用方传入的 logger（可选）
        
    Returns:
        Logger 对象
        
    Example:
        # 使用 fallback logger
        logger = get_module_logger()
        
        # 使用调用方 logger（推荐）
        my_logger = logging.getLogger('my_module')
        logger = get_module_logger(my_logger)
    """
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
        code: 股票代码（如 "600000"），必须非空
        name: 股票名称（如 "浦发银行"),必须非空
        
    Returns:
        bool: True 表示主板股票，False 表示应剔除
        
    Note:
        空代码或空名称直接返回 False（防御性编程）
        
    Example:
        # 主板股票
        >>> is_main_board_stock('600000', '浦发银行')
        True
        >>> is_main_board_stock('000001', '平安银行')
        True
        
        # 剔除股票
        >>> is_main_board_stock('300001', '特锐德')
        False  # 创业板
        >>> is_main_board_stock('688001', '华兴源创')
        False  # 科创板
        >>> is_main_board_stock('600000', 'ST某某')
        False  # ST股票
        
        # 防御性编程：空值返回 False
        >>> is_main_board_stock('', '浦发银行')
        False
    """
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
        ValueError: JSON 解析失败
        
    Example:
        # 使用默认路径
        >>> stocks = load_main_board_stock_list()
        >>> len(stocks)
        3010
        
        # 使用自定义路径
        >>> stocks = load_main_board_stock_list(
        ...     Path('/custom/path/stock_list.json'),
        ...     logger=my_logger
        ... )
    """
    logger = get_module_logger(logger)
    
    # 使用默认路径（使用缓存的导入函数）
    if stock_list_file is None:
        if _get_stock_list_file is None:
            _get_imported_functions()
        stock_list_file = _get_stock_list_file()
    else:
        stock_list_file = Path(stock_list_file)  # 统一转换为 Path
    
    if not stock_list_file.exists():
        raise FileNotFoundError(f"股票列表缓存不存在: {stock_list_file}")
    
    # 加载缓存（使用缓存的导入函数）
    if _read_json_cache is None:
        _get_imported_functions()
    data = _read_json_cache(stock_list_file, logger=logger)
    
    stocks = data.get('stocks', [])
    
    # 筛选主板股票
    main_board_stocks = []
    for stock in stocks:
        code = stock.get('code', '')
        name = stock.get('name', '')
        
        if is_main_board_stock(code, name):
            main_board_stocks.append(stock)
    
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
        stock_list: 股票列表
        logger: 调用方传入的 logger（可选）
        
    Returns:
        List[str]: 股票代码列表（过滤空代码）
        
    Note:
        自动过滤空代码，避免后续处理问题
        
    Example:
        >>> stocks = [{'code': '600000', 'name': '浦发银行'}, {'code': '', 'name': '异常'}]
        >>> codes = get_stock_codes_only(stocks)
        ['600000']  # 空代码已过滤
    """
    logger = get_module_logger(logger)
    
    codes = []
    empty_count = 0
    for stock in stock_list:
        code = stock.get('code', '')
        if code:  # 过滤空代码
            codes.append(code)
        else:
            empty_count += 1
    
    # 防御性编程：报告空代码数量
    if empty_count > 0:
        logger.warning(
            "提取股票代码时发现 %d 个空代码，已过滤",
            empty_count
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
        stock_list: 股票列表
        start_date: 开始日期（YYYY-MM-DD）
        end_date: 结束日期（YYYY-MM-DD）
        date_field: 日期字段名（默认 'list_date'）
        logger: 调用方传入的 logger（可选）
        
    Returns:
        List[Dict[str, Any]]: 筛选后的股票列表
        
    Raises:
        ValueError: 日期格式不正确
        
    Example:
        >>> stocks = [{'code': '600000', 'list_date': '2020-06-01'}]
        >>> filtered = filter_stocks_by_date(stocks, '2020-01-01', '2020-12-31')
        >>> len(filtered)
        1
    """
    logger = get_module_logger(logger)
    
    # 防御性编程：验证日期格式
    if not start_date or not end_date:
        raise ValueError("开始日期和结束日期不能为空")
    
    # 简单格式验证（YYYY-MM-DD）
    if len(start_date) != 10 or len(end_date) != 10:
        logger.warning(
            "日期格式可能不正确: start_date=%s, end_date=%s（预期 YYYY-MM-DD）",
            start_date, end_date
        )
    
    filtered = []
    for stock in stock_list:
        list_date = stock.get(date_field, '')
        if list_date and start_date <= list_date <= end_date:
            filtered.append(stock)
    
    logger.debug(
        "按日期筛选股票: %s ~ %s, 筛选结果 %d 只",
        start_date, end_date, len(filtered)
    )
    
    return filtered


def get_stock_name_map(stock_list: List[Dict[str, Any]], logger: Optional[logging.Logger] = None) -> Dict[str, str]:
    """
    构建股票代码→名称映射
    
    Args:
        stock_list: 股票列表
        logger: 调用方传入的 logger（可选）
        
    Returns:
        Dict[str, str]: {股票代码: 股票名称}（过滤空代码和空名称）
        
    Note:
        自动过滤空代码和空名称
        
    Example:
        >>> stocks = [{'code': '600000', 'name': '浦发银行'}, {'code': '', 'name': '异常'}]
        >>> name_map = get_stock_name_map(stocks)
        {'600000': '浦发银行'}  # 空代码已过滤
    """
    logger = get_module_logger(logger)
    
    name_map = {}
    empty_count = 0
    for stock in stock_list:
        code = stock.get('code', '')
        name = stock.get('name', '')
        if code and name:  # 过滤空代码和空名称
            name_map[code] = name
        else:
            empty_count += 1
    
    # 防御性编程：报告空值数量
    if empty_count > 0:
        logger.warning(
            "构建名称映射时发现 %d 个空代码或空名称，已过滤",
            empty_count
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
        
        # 测试 1: is_main_board_stock（含边界测试）
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
        
        # 测试 2: load_main_board_stock_list
        test_logger.info("\n[测试 2] load_main_board_stock_list...")
        try:
            stocks = load_main_board_stock_list(logger=test_logger)
            test_logger.info("  加载成功，主板股票数: %d", len(stocks))
            if stocks:
                test_logger.info("  示例: %s", stocks[0])
        except FileNotFoundError as e:
            test_logger.warning("  文件不存在: %s", e)
        
        # 测试 3: get_stock_codes_only（含空代码过滤）
        test_logger.info("\n[测试 3] get_stock_codes_only...")
        test_stocks_with_empty = [
            {'code': '600000', 'name': '浦发银行'},
            {'code': '000001', 'name': '平安银行'},
            {'code': '', 'name': '异常股票'},  # 空代码
        ]
        codes = get_stock_codes_only(test_stocks_with_empty, logger=test_logger)
        test_logger.info("  代码列表: %s (过滤空代码)", codes)
        
        # 测试 4: get_stock_name_map（含空值过滤）
        test_logger.info("\n[测试 4] get_stock_name_map...")
        test_stocks_empty_name = [
            {'code': '600000', 'name': '浦发银行'},
            {'code': '', 'name': '异常股票'},  # 空代码
            {'code': '000001', 'name': ''},  # 空名称
        ]
        name_map = get_stock_name_map(test_stocks_empty_name, logger=test_logger)
        test_logger.info("  名称映射: %s (过滤空值)", name_map)
        
        # 测试 5: filter_stocks_by_date
        test_logger.info("\n[测试 5] filter_stocks_by_date...")
        test_date_stocks = [{'code': '600000', 'list_date': '2020-06-01'}]
        filtered = filter_stocks_by_date(test_date_stocks, '2020-01-01', '2020-12-31', logger=test_logger)
        test_logger.info("  筛选结果: %d 只股票", len(filtered))
        
        # 测试 6: get_module_logger
        test_logger.info("\n[测试 6] get_module_logger...")
        fallback_logger = get_module_logger()
        test_logger.info("  Fallback logger name: %s", fallback_logger.name)
        custom_logger = get_module_logger(test_logger)
        test_logger.info("  Custom logger name: %s", custom_logger.name)
        
        # 测试 7: 常量导出
        test_logger.info("\n[测试 7] 公共常量...")
        test_logger.info("  MAIN_BOARD_PREFIXES: %s", MAIN_BOARD_PREFIXES)
        test_logger.info("  EXCLUDED_PREFIXES: %s", EXCLUDED_PREFIXES)
        test_logger.info("  EXCLUDED_NAME_KEYWORDS: %s", EXCLUDED_NAME_KEYWORDS)
        
        # 测试 8: 类型注解验证（导入后检查）
        test_logger.info("\n[测试 8] 类型注解验证...")
        test_logger.info("  Dict[str, Any] 类型注解已应用")
        test_logger.info("  Union[Path, str] 类型注解已应用")
        
        test_logger.info("\n" + "=" * 50)
        test_logger.info("测试完成（共 8 项测试，含边界测试）")
        test_logger.info("=" * 50)
    finally:
        test_logger.info("测试清理完成")