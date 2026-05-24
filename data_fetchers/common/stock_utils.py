#!/usr/bin/env python3
"""
股票筛选模块

统一主板股票判断和股票列表加载。

版本历史：
- v1.0 (2026-05-24): 初始版本
- v1.1 (2026-05-25): logger 参数化、__all__ 导出、模块级导入、docstring 补充

作者: 云瑶
日期: 2026-05-24
"""

import logging
from pathlib import Path
from typing import Dict, List, Optional

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
        code: 股票代码（如 "600000"）
        name: 股票名称（如 "浦发银行")
        
    Returns:
        bool: True 表示主板股票，False 表示应剔除
        
    Example:
        # 主板股票
        is_main_board_stock('600000', '浦发银行')  # True
        is_main_board_stock('000001', '平安银行')  # True
        
        # 剔除股票
        is_main_board_stock('300001', '特锐德')    # False (创业板)
        is_main_board_stock('688001', '华兴源创')  # False (科创板)
        is_main_board_stock('600000', 'ST某某')    # False (ST股票)
    """
    # 剔除创业板、科创板、北交所
    for prefix in EXCLUDED_PREFIXES:
        if code.startswith(prefix):
            return False
    
    # 剔除 ST 类股票
    for keyword in EXCLUDED_NAME_KEYWORDS:
        if keyword in name:
            return False
    
    # 只保留主板：沪市60、深市00
    for prefix in MAIN_BOARD_PREFIXES:
        if code.startswith(prefix):
            return True
    
    return False


def load_main_board_stock_list(
    stock_list_file: Optional[Path] = None,
    logger: Optional[logging.Logger] = None,
) -> List[Dict]:
    """
    加载主板股票列表
    
    从缓存文件加载股票列表，筛选出主板股票。
    
    Args:
        stock_list_file: 股票列表缓存文件路径（默认使用 cache/stock_list.json）
        logger: 调用方传入的 logger（可选）
        
    Returns:
        List[Dict]: 主板股票列表，每项包含 {code, name, ...}
        
    Raises:
        FileNotFoundError: 股票列表缓存不存在
        
    Example:
        # 使用默认路径
        stocks = load_main_board_stock_list()
        
        # 使用自定义路径
        stocks = load_main_board_stock_list(
            Path('/custom/path/stock_list.json'),
            logger=my_logger
        )
    """
    logger = get_module_logger(logger)
    
    # 使用默认路径
    if stock_list_file is None:
        # 根据 __name__ 判断导入方式（__main__ 使用绝对导入，其他使用相对导入）
        if __name__ == '__main__':
            from data_fetchers.common.paths import get_stock_list_file
        else:
            from .paths import get_stock_list_file
        stock_list_file = get_stock_list_file()
    
    if not stock_list_file.exists():
        raise FileNotFoundError(f"股票列表缓存不存在: {stock_list_file}")
    
    # 加载缓存
    if __name__ == '__main__':
        from data_fetchers.common.cache_manager import read_json_cache
    else:
        from .cache_manager import read_json_cache
    data = read_json_cache(stock_list_file, logger=logger)
    
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


def get_stock_codes_only(stock_list: List[Dict]) -> List[str]:
    """
    从股票列表中提取代码列表
    
    Args:
        stock_list: 股票列表
        
    Returns:
        List[str]: 股票代码列表
        
    Example:
        stocks = [{'code': '600000', 'name': '浦发银行'}]
        codes = get_stock_codes_only(stocks)  # ['600000']
    """
    return [stock.get('code', '') for stock in stock_list]


def filter_stocks_by_date(
    stock_list: List[Dict],
    start_date: str,
    end_date: str,
    date_field: str = 'list_date',
) -> List[Dict]:
    """
    按上市日期筛选股票
    
    Args:
        stock_list: 股票列表
        start_date: 开始日期（YYYY-MM-DD）
        end_date: 结束日期（YYYY-MM-DD）
        date_field: 日期字段名（默认 'list_date'）
        
    Returns:
        List[Dict]: 筛选后的股票列表
        
    Example:
        stocks = [{'code': '600000', 'list_date': '2020-01-01'}]
        filtered = filter_stocks_by_date(stocks, '2020-01-01', '2020-12-31')
    """
    filtered = []
    for stock in stock_list:
        list_date = stock.get(date_field, '')
        if list_date:
            if start_date <= list_date <= end_date:
                filtered.append(stock)
    return filtered


def get_stock_name_map(stock_list: List[Dict]) -> Dict[str, str]:
    """
    构建股票代码→名称映射
    
    Args:
        stock_list: 股票列表
        
    Returns:
        Dict[str, str]: {股票代码: 股票名称}
        
    Example:
        stocks = [{'code': '600000', 'name': '浦发银行'}]
        name_map = get_stock_name_map(stocks)  # {'600000': '浦发银行'}
    """
    return {stock.get('code', ''): stock.get('name', '') for stock in stock_list}


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
        
        # 测试 1: is_main_board_stock
        test_logger.info("\n[测试 1] is_main_board_stock...")
        test_cases = [
            ('600000', '浦发银行', True),
            ('000001', '平安银行', True),
            ('300001', '特锐德', False),  # 创业板
            ('688001', '华兴源创', False),  # 科创板
            ('830001', '新三板', False),  # 北交所
            ('600000', 'ST某某', False),  # ST股票
        ]
        
        all_passed = True
        for code, name, expected in test_cases:
            result = is_main_board_stock(code, name)
            status = 'PASS' if result == expected else 'FAIL'
            if result != expected:
                all_passed = False
            test_logger.info("  [%s] %s %s: %s (预期 %s)", status, code, name, result, expected)
        
        if all_passed:
            test_logger.info("  所有测试通过")
        
        # 测试 2: load_main_board_stock_list
        test_logger.info("\n[测试 2] load_main_board_stock_list...")
        try:
            stocks = load_main_board_stock_list(logger=test_logger)
            test_logger.info("  加载成功，主板股票数: %d", len(stocks))
            if stocks:
                test_logger.info("  示例: %s", stocks[0])
        except FileNotFoundError as e:
            test_logger.warning("  文件不存在: %s", e)
        
        # 测试 3: get_stock_name_map
        test_logger.info("\n[测试 3] get_stock_name_map...")
        test_stocks = [{'code': '600000', 'name': '浦发银行'}, {'code': '000001', 'name': '平安银行'}]
        name_map = get_stock_name_map(test_stocks)
        test_logger.info("  名称映射: %s", name_map)
        
        # 测试 4: get_stock_codes_only
        test_logger.info("\n[测试 4] get_stock_codes_only...")
        codes = get_stock_codes_only(test_stocks)
        test_logger.info("  代码列表: %s", codes)
        
        # 测试 5: filter_stocks_by_date
        test_logger.info("\n[测试 5] filter_stocks_by_date...")
        test_date_stocks = [{'code': '600000', 'list_date': '2020-06-01'}]
        filtered = filter_stocks_by_date(test_date_stocks, '2020-01-01', '2020-12-31')
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
        
        test_logger.info("\n" + "=" * 50)
        test_logger.info("测试完成（共 7 项测试）")
        test_logger.info("=" * 50)
    finally:
        test_logger.info("测试清理完成")