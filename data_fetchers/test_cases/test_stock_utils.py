#!/usr/bin/env python3
"""
stock_utils.py 测试用例

测试覆盖：
- is_main_board_stock: 主板判断 + 类型验证 + 边界测试
- load_main_board_stock_list: 加载 + 异常处理
- get_stock_codes_only: 提取代码 + 空值过滤 + 类型验证
- get_stock_name_map: 名称映射 + 空值过滤 + 类型验证
- filter_stocks_by_date: 日期筛选 + 格式验证 + 边界验证 + 类型验证
- get_module_logger: logger 参数化 + 类型验证
- 常量导出验证

作者: 云瑶
日期: 2026-05-27
"""

import logging
import pytest
from pathlib import Path
from typing import Any, Dict, List

import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from data_fetchers.common.stock_utils import (
    is_main_board_stock,
    load_main_board_stock_list,
    get_stock_codes_only,
    get_stock_name_map,
    filter_stocks_by_date,
    get_module_logger,
    MAIN_BOARD_PREFIXES,
    EXCLUDED_PREFIXES,
    EXCLUDED_NAME_KEYWORDS,
    MIN_STOCK_DATE,
    get_max_stock_date,
    MAX_STOCK_DATE,
)


class TestIsMainBoardStock:
    """测试 is_main_board_stock 函数"""

    @pytest.mark.parametrize("code,name,expected", [
        # 主板股票
        ('600000', '浦发银行', True),
        ('000001', '平安银行', True),
        # 创业板（剔除）
        ('300001', '特锐德', False),
        # 科创板（剔除）
        ('688001', '华兴源创', False),
        # 北交所（剔除）
        ('830001', '新三板', False),
        # ST股票（剔除）
        ('600000', 'ST某某', False),
        # 边界测试：空值
        ('', '浦发银行', False),
        ('600000', '', False),
        ('', '', False),
    ])
    def test_is_main_board_stock(self, code: str, name: str, expected: bool):
        """测试主板股票判断"""
        result = is_main_board_stock(code, name)
        assert result == expected

    def test_type_error_code_int(self):
        """测试 code 参数类型错误（传入 int）"""
        with pytest.raises(TypeError, match="code 必须是字符串类型"):
            is_main_board_stock(600000, '浦发银行')

    def test_type_error_name_int(self):
        """测试 name 参数类型错误（传入 int）"""
        with pytest.raises(TypeError, match="name 必须是字符串类型"):
            is_main_board_stock('600000', 12345)


class TestLoadMainBoardStockList:
    """测试 load_main_board_stock_list 函数"""

    def test_load_success(self, test_logger: logging.Logger, stock_list_exists: bool):
        """测试正常加载"""
        if not stock_list_exists:
            pytest.skip("股票列表缓存不存在")
        stocks = load_main_board_stock_list(logger=test_logger)
        assert isinstance(stocks, list)
        if stocks:
            assert isinstance(stocks[0], dict)
            assert 'code' in stocks[0]
            assert 'name' in stocks[0]

    def test_file_not_found(self, test_logger: logging.Logger):
        """测试文件不存在"""
        with pytest.raises(FileNotFoundError, match="股票列表缓存不存在"):
            load_main_board_stock_list(
                stock_list_file=Path('/nonexistent/path/stock_list.json'),
                logger=test_logger
            )


class TestGetStockCodesOnly:
    """测试 get_stock_codes_only 函数"""

    def test_extract_codes(self, test_logger: logging.Logger):
        """测试提取代码（过滤空代码）"""
        test_stocks = [
            {'code': '600000', 'name': '浦发银行'},
            {'code': '000001', 'name': '平安银行'},
            {'code': '', 'name': '异常股票'},
        ]
        codes = get_stock_codes_only(test_stocks, logger=test_logger)
        assert codes == ['600000', '000001']

    def test_empty_list(self, test_logger: logging.Logger):
        """测试空列表"""
        codes = get_stock_codes_only([], logger=test_logger)
        assert codes == []

    def test_type_error_not_list(self):
        """测试参数不是列表"""
        with pytest.raises(TypeError, match="stock_list 必须是列表类型"):
            get_stock_codes_only('not_a_list')

    def test_filter_non_dict_elements(self, test_logger: logging.Logger):
        """测试过滤非字典元素"""
        test_stocks = [{'code': '600000'}, 'not_a_dict']
        codes = get_stock_codes_only(test_stocks, logger=test_logger)
        assert codes == ['600000']


class TestGetStockNameMap:
    """测试 get_stock_name_map 函数"""

    def test_build_map(self, test_logger: logging.Logger):
        """测试构建名称映射（过滤空值）"""
        test_stocks = [
            {'code': '600000', 'name': '浦发银行'},
            {'code': '', 'name': '异常股票'},
            {'code': '000001', 'name': ''},
        ]
        name_map = get_stock_name_map(test_stocks, logger=test_logger)
        assert name_map == {'600000': '浦发银行'}

    def test_empty_list(self, test_logger: logging.Logger):
        """测试空列表"""
        name_map = get_stock_name_map([], logger=test_logger)
        assert name_map == {}

    def test_type_error_not_list(self):
        """测试参数不是列表"""
        with pytest.raises(TypeError, match="stock_list 必须是列表类型"):
            get_stock_name_map('not_a_list')

    def test_filter_non_dict_elements(self, test_logger: logging.Logger):
        """测试过滤非字典元素"""
        test_stocks = [{'code': '600000', 'name': '浦发银行'}, 'not_a_dict']
        name_map = get_stock_name_map(test_stocks, logger=test_logger)
        assert name_map == {'600000': '浦发银行'}


class TestFilterStocksByDate:
    """测试 filter_stocks_by_date 函数"""

    def test_filter_success(self, test_logger: logging.Logger):
        """测试正常筛选"""
        test_stocks = [{'code': '600000', 'list_date': '2020-06-01'}]
        filtered = filter_stocks_by_date(
            test_stocks, '2020-01-01', '2020-12-31', logger=test_logger
        )
        assert len(filtered) == 1

    def test_empty_list(self, test_logger: logging.Logger):
        """测试空列表"""
        filtered = filter_stocks_by_date([], '2020-01-01', '2020-12-31', logger=test_logger)
        assert filtered == []

    def test_invalid_date_format(self):
        """测试日期格式错误"""
        test_stocks = [{'code': '600000', 'list_date': '2020-06-01'}]
        with pytest.raises(ValueError, match="开始日期格式不正确"):
            filter_stocks_by_date(test_stocks, '2020-1-1', '2020-12-31')

    def test_invalid_date_boundary_before_1990(self):
        """测试日期边界错误（早于1990）"""
        test_stocks = [{'code': '600000', 'list_date': '2020-06-01'}]
        with pytest.raises(ValueError, match="开始日期超出合理边界"):
            filter_stocks_by_date(test_stocks, '1980-01-01', '2020-12-31')

    def test_invalid_date_range(self):
        """测试日期范围错误（start > end）"""
        test_stocks = [{'code': '600000', 'list_date': '2020-06-01'}]
        with pytest.raises(ValueError, match="日期范围无效"):
            filter_stocks_by_date(test_stocks, '2020-12-31', '2020-01-01')

    def test_type_error_not_list(self):
        """测试参数不是列表"""
        with pytest.raises(TypeError, match="stock_list 必须是列表类型"):
            filter_stocks_by_date('not_a_list', '2020-01-01', '2020-12-31')

    def test_filter_non_dict_elements(self, test_logger: logging.Logger):
        """测试过滤非字典元素"""
        test_stocks = [{'code': '600000', 'list_date': '2020-06-01'}, 'not_a_dict']
        filtered = filter_stocks_by_date(
            test_stocks, '2020-01-01', '2020-12-31', logger=test_logger
        )
        assert len(filtered) == 1

    def test_invalid_calendar_date(self):
        """测试日历非法日期（如2020-13-01）"""
        test_stocks = [{'code': '600000', 'list_date': '2020-06-01'}]
        with pytest.raises(ValueError, match="开始日期不是合法日期"):
            filter_stocks_by_date(test_stocks, '2020-13-01', '2020-12-31')


class TestGetModuleLogger:
    """测试 get_module_logger 函数"""

    def test_fallback_logger(self):
        """测试 fallback logger"""
        logger = get_module_logger()
        assert logger.name == 'data_fetchers.common.stock_utils'

    def test_custom_logger(self, test_logger: logging.Logger):
        """测试自定义 logger"""
        logger = get_module_logger(test_logger)
        assert logger == test_logger

    def test_type_error_not_logger(self):
        """测试参数不是 Logger 类型"""
        with pytest.raises(TypeError, match="logger 必须是 logging.Logger 类型"):
            get_module_logger('not_a_logger')


class TestConstants:
    """测试公共常量"""

    def test_main_board_prefixes(self):
        """测试主板前缀常量"""
        assert MAIN_BOARD_PREFIXES == ('60', '00')
        assert isinstance(MAIN_BOARD_PREFIXES, tuple)  # 不可变

    def test_excluded_prefixes(self):
        """测试剔除前缀常量（精简后：'8' 覆盖 '688'）"""
        assert EXCLUDED_PREFIXES == ('30', '8', '4')
        assert isinstance(EXCLUDED_PREFIXES, tuple)

    def test_excluded_name_keywords(self):
        """测试剔除名称关键词常量"""
        assert 'ST' in EXCLUDED_NAME_KEYWORDS
        assert isinstance(EXCLUDED_NAME_KEYWORDS, tuple)

    def test_min_stock_date(self):
        """测试最小日期常量"""
        assert MIN_STOCK_DATE == '1990-12-19'

    def test_get_max_stock_date(self):
        """测试动态获取最大日期"""
        max_date = get_max_stock_date()
        assert isinstance(max_date, str)
        # 格式验证
        import re
        assert re.match(r'^\d{4}-\d{2}-\d{2}$', max_date)

    def test_max_stock_date_alias(self):
        """测试 deprecated 别名（快照值）"""
        # MAX_STOCK_DATE 是模块加载时的快照值（字符串）
        assert isinstance(MAX_STOCK_DATE, str)
        # 格式验证
        import re
        assert re.match(r'^\d{4}-\d{2}-\d{2}$', MAX_STOCK_DATE)


# ============== pytest fixtures ==============

@pytest.fixture
def test_logger() -> logging.Logger:
    """测试 logger fixture"""
    return logging.getLogger('test_stock_utils')


@pytest.fixture
def stock_list_exists() -> bool:
    """检查股票列表缓存是否存在"""
    from data_fetchers.common.paths import get_stock_list_file
    return get_stock_list_file().exists()