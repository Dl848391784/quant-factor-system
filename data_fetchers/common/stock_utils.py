#!/usr/bin/env python3
"""
股票筛选模块

统一主板股票判断和股票列表加载。

作者: 云瑶
日期: 2026-05-24
"""

import logging
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


# 主板股票代码前缀
MAIN_BOARD_PREFIXES = ('60', '00')  # 沪市60、深市00

# 剔除的代码前缀
EXCLUDED_PREFIXES = ('30', '688', '8', '4')  # 创业板、科创板、北交所

# 剔除的名称关键词
EXCLUDED_NAME_KEYWORDS = ('ST', '*ST', '退市', 'SST', 'S*ST')


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
        name: 股票名称（如 "浦发银行"）
        
    Returns:
        bool: True 表示主板股票，False 表示应剔除
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
    verbose: bool = False,
) -> List[Dict]:
    """
    加载主板股票列表
    
    从缓存文件加载股票列表，筛选出主板股票。
    
    Args:
        stock_list_file: 股票列表缓存文件路径（默认使用 cache/stock_list.json）
        verbose: 是否打印详细信息
        
    Returns:
        List[Dict]: 主板股票列表，每项包含 {code, name, ...}
        
    Raises:
        FileNotFoundError: 股票列表缓存不存在
    """
    # 使用默认路径
    if stock_list_file is None:
        from .paths import get_stock_list_file
        stock_list_file = get_stock_list_file()
    
    if not stock_list_file.exists():
        raise FileNotFoundError(f"股票列表缓存不存在: {stock_list_file}")
    
    # 加载缓存
    from .cache_manager import read_json_cache
    data = read_json_cache(stock_list_file)
    
    stocks = data.get('stocks', [])
    
    # 筛选主板股票
    main_board_stocks = []
    for stock in stocks:
        code = stock.get('code', '')
        name = stock.get('name', '')
        
        if is_main_board_stock(code, name):
            main_board_stocks.append(stock)
    
    if verbose:
        total_count = len(stocks)
        main_count = len(main_board_stocks)
        excluded_count = total_count - main_count
        logger.info(f"股票筛选完成: 总数 {total_count}, 主板 {main_count}, 剔除 {excluded_count}")
    
    return main_board_stocks


def get_stock_codes_only(stock_list: List[Dict]) -> List[str]:
    """
    从股票列表中提取代码列表
    
    Args:
        stock_list: 股票列表
        
    Returns:
        List[str]: 股票代码列表
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
        date_field: 日期字段名
        
    Returns:
        List[Dict]: 筛选后的股票列表
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
        stock_list: 节股票列表
        
    Returns:
        Dict[str, str]: {股票代码: 股票名称}
    """
    return {stock.get('code', ''): stock.get('name', '') for stock in stock_list}


if __name__ == '__main__':
    # 测试股票筛选
    print("测试 is_main_board_stock:")
    test_cases = [
        ('600000', '浦发银行', True),
        ('000001', '平安银行', True),
        ('300001', '特锐德', False),  # 创业板
        ('688001', '华兴源创', False),  # 科创板
        ('830001', '新三板', False),  # 北交所
        ('600000', 'ST某某', False),  # ST股票
    ]
    
    for code, name, expected in test_cases:
        result = is_main_board_stock(code, name)
        status = '✓' if result == expected else '✗'
        print(f"  {status} {code} {name}: {result} (预期 {expected})")
    
    print("\n测试 load_main_board_stock_list:")
    try:
        stocks = load_main_board_stock_list(verbose=True)
        print(f"  加载成功，主板股票数: {len(stocks)}")
        if stocks:
            print(f"  示例: {stocks[0]}")
    except FileNotFoundError as e:
        print(f"  文件不存在: {e}")
    
    print("\n测试 get_stock_name_map:")
    test_stocks = [{'code': '600000', 'name': '浦发银行'}, {'code': '000001', 'name': '平安银行'}]
    name_map = get_stock_name_map(test_stocks)
    print(f"  名称映射: {name_map}")
    
    print("\n测试完成")