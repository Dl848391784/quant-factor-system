#!/usr/bin/env python3
"""
data_fetchers 公共模块

提供数据拉取脚本的公共功能：
- paths: 路径管理
- cache_manager: 缓存读写
- http_client: HTTP 客户端（需要 requests）
- stock_utils: 股票筛选

使用方式：
    from data_fetchers.common import paths, cache_manager, stock_utils
    
    # 获取路径
    cache_dir = paths.get_cache_dir()
    
    # 读取缓存
    data = cache_manager.read_gzip_cache(cache_dir / 'factor_data/data.json.gz')
    
    # 加载主板股票列表
    stocks = stock_utils.load_main_board_stock_list()

作者: 云瑶
日期: 2026-05-24
"""

from .paths import (
    get_project_root,
    get_stock_list_file,
    get_logs_dir,
    get_module_logs_dir,
    get_module_result_dir,
    Paths,
    paths,
)

from .logger_config import setup_logger
from .cache_manager import (
    get_module_logger,
    read_cache,
    write_cache,
    read_gzip_cache,
    write_gzip_cache,
    read_json_cache,
    write_json_cache,
    append_to_cache,
    get_cache_file_info,
    cache_exists,
    delete_cache,
)

from .stock_utils import (
    get_module_logger,
    is_main_board_stock,
    load_main_board_stock_list,
    get_stock_codes_only,
    filter_stocks_by_date,
    get_stock_name_map,
    MAIN_BOARD_PREFIXES,
    EXCLUDED_PREFIXES,
    EXCLUDED_NAME_KEYWORDS,
    MIN_STOCK_DATE,
    MAX_STOCK_DATE,
)

from .memory_utils import (
    get_memory_usage_mb,
    get_memory_info_str,
)

from .dataframe_utils import (
    validate_dataframe_columns,
)

# http_client 需要 requests 模块，可选导入
try:
    from .http_client import (
        get_module_logger as http_get_module_logger,
        create_retry_session,
        create_eastmoney_session,
        create_sina_session,
        request_with_retry,
        DEFAULT_EASTMONEY_HEADERS,
        DEFAULT_SINA_HEADERS,
    )
    _HTTP_CLIENT_AVAILABLE = True
except ImportError:
    _HTTP_CLIENT_AVAILABLE = False
    # 定义占位函数，避免导入报错
    def http_get_module_logger(*args, **kwargs):
        raise ImportError("http_client 需要 requests 模块，请安装: pip install requests")
    def create_retry_session(*args, **kwargs):
        raise ImportError("http_client 需要 requests 模块，请安装: pip install requests")
    def create_eastmoney_session(*args, **kwargs):
        raise ImportError("http_client 需要 requests 模块，请安装: pip install requests")
    def create_sina_session(*args, **kwargs):
        raise ImportError("http_client 需要 requests 模块，请安装: pip install requests")
    def request_with_retry(*args, **kwargs):
        raise ImportError("http_client 需要 requests 模块，请安装: pip install requests")
    DEFAULT_EASTMONEY_HEADERS = {}
    DEFAULT_SINA_HEADERS = {}


__all__ = [
    # paths
    'get_project_root',
    'get_stock_list_file',
    'get_logs_dir',
    'get_module_logs_dir',
    'get_module_result_dir',
    'Paths',
    'paths',
    # logger_config
    'setup_logger',
    # cache_manager
    'get_module_logger',
    'read_cache',
    'write_cache',
    'read_gzip_cache',
    'write_gzip_cache',
    'read_json_cache',
    'write_json_cache',
    'append_to_cache',
    'get_cache_file_info',
    'cache_exists',
    'delete_cache',
    # http_client (注：get_module_logger 从 cache_manager 导入，http_get_module_logger 为内部别名)
    'create_retry_session',
    'create_eastmoney_session',
    'create_sina_session',
    'request_with_retry',
    'DEFAULT_EASTMONEY_HEADERS',
    'DEFAULT_SINA_HEADERS',
    # stock_utils
    'is_main_board_stock',
    'load_main_board_stock_list',
    'get_stock_codes_only',
    'filter_stocks_by_date',
    'get_stock_name_map',
    'MAIN_BOARD_PREFIXES',
    'EXCLUDED_PREFIXES',
    'EXCLUDED_NAME_KEYWORDS',
    'MIN_STOCK_DATE',
    'MAX_STOCK_DATE',
    # memory_utils
    'get_memory_usage_mb',
    'get_memory_info_str',
    # dataframe_utils
    'validate_dataframe_columns',
]