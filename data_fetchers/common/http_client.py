#!/usr/bin/env python3
"""
HTTP 客户端模块

统一 HTTP Session 创建和请求头配置。

版本历史：
- v1.0 (2026-05-24): 初始版本，创建 create_retry_session、create_eastmoney_session、create_sina_session
- v1.1 (2026-05-25): 新增 request_with_retry，logger 参数化，异常处理精确化
- v1.2 (2026-05-25): 新增 get_module_logger，__all__ 导出，docstring Example 补充
- v1.3 (2026-05-25): 模块级常量补全，请求头数据来源注释，返回类型修复

作者: 云瑶
日期: 2026-05-24
"""

import json
import logging
import time
import requests
from requests.adapters import HTTPAdapter
from typing import Dict, Optional, Any, Union, Tuple, List
from urllib3.util.retry import Retry

__all__ = [
    # Session 创建函数
    'create_retry_session',
    'create_eastmoney_session',
    'create_sina_session',
    # 请求函数
    'request_with_retry',
    # 日志函数
    'get_module_logger',
    # 请求头常量（供外部复用）
    'DEFAULT_EASTMONEY_HEADERS',
    'DEFAULT_SINA_HEADERS',
]

# 模块级 fallback logger（遵循 PROJECT.md 第783-857行规范）
# 直接初始化，避免延迟初始化的多线程安全问题
_MODULE_LOGGER = logging.getLogger('data_fetchers.common.http_client')

# 默认重试参数（模块私有常量）
_DEFAULT_TOTAL_RETRIES = 3
_DEFAULT_BACKOFF_FACTOR = 1.0
_DEFAULT_POOL_CONNECTIONS = 10
_DEFAULT_POOL_MAXSIZE = 10
_DEFAULT_TIMEOUT = 30
_DEFAULT_MAX_ATTEMPTS = 3
_DEFAULT_DELAY = 1.0

# 重试状态码列表（429=限流，500-504=服务器错误）
_DEFAULT_RETRY_STATUS_CODES = [429, 500, 502, 503, 504]

# 默认允许重试的 HTTP 方法
_DEFAULT_ALLOWED_METHODS = ["GET"]

# 默认东财 API 请求头（数据来源：浏览器开发者工具抓包，2026-05-24）
# 用途：模拟浏览器访问东财 API，避免被拦截
# 注意：User-Agent 中的 Chrome 版本号（120.0.0.0）需要定期更新（建议每季度检查）
DEFAULT_EASTMONEY_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Referer": "https://quote.eastmoney.com/",
    "Accept": "*/*",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Connection": "keep-alive",
}

# 新浪 API 请求头（数据来源：浏览器开发者工具抓包，2026-05-24）
# 用途：模拟浏览器访问新浪财经 API，避免被拦截
# 注意：User-Agent 中的 Chrome 版本号（120.0.0.0）需要定期更新（建议每季度检查）
DEFAULT_SINA_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Referer": "http://vip.stock.finance.sina.com.cn/",
    "Accept": "*/*",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}


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


def create_retry_session(
    headers: Optional[Dict[str, str]] = None,
    total_retries: int = _DEFAULT_TOTAL_RETRIES,
    backoff_factor: float = _DEFAULT_BACKOFF_FACTOR,
    pool_connections: int = _DEFAULT_POOL_CONNECTIONS,
    pool_maxsize: int = _DEFAULT_POOL_MAXSIZE,
    allowed_methods: Optional[List[str]] = None,
    logger: Optional[logging.Logger] = None,
) -> requests.Session:
    """
    创建带重试机制的 HTTP Session
    
    Args:
        headers: 自定义请求头（默认 None，使用 requests 默认 User-Agent）
        total_retries: 总重试次数（默认 3）
        backoff_factor: 退避因子（默认 1.0）
        pool_connections: 连接池大小（默认 10）
        pool_maxsize: 最大连接数（默认 10）
        allowed_methods: 允许重试的 HTTP 方法（默认 ["GET"]）
        logger: 调用方传入的 logger（可选）
        
    Returns:
        requests.Session: 配置好的 Session
        
    Raises:
        TypeError: urllib3 版本不兼容（极少见）
        
    Example:
        # 创建通用 Session（默认配置）
        session = create_retry_session()
        
        # 创建东财 Session（业务特定）
        session = create_retry_session(
            headers=DEFAULT_EASTMONEY_HEADERS,
            total_retries=5,
            logger=my_logger
        )
        
        # 创建新浪 Session（业务特定）
        session = create_retry_session(
            headers=DEFAULT_SINA_HEADERS,
            allowed_methods=['GET', 'POST'],
            logger=my_logger
        )
    """
    logger = get_module_logger(logger)
    session = requests.Session()
    
    # 设置请求头（默认 None，使用 requests 默认 User-Agent）
    if headers is not None:
        session.headers.update(headers)
    
    # 允许重试的 HTTP 方法
    if allowed_methods is None:
        allowed_methods = _DEFAULT_ALLOWED_METHODS
    
    # 创建重试策略
    # 公共参数（避免 try/except 内重复）
    retry_params = {
        'total': total_retries,
        'backoff_factor': backoff_factor,
        'status_forcelist': _DEFAULT_RETRY_STATUS_CODES,
    }
    try:
        # urllib3 >= 2.0 使用 allowed_methods
        retry_strategy = Retry(**retry_params, allowed_methods=allowed_methods)
    except TypeError:
        # urllib3 < 2.0 使用 method_whitelist
        retry_strategy = Retry(**retry_params, method_whitelist=allowed_methods)
    
    # 配置适配器
    adapter = HTTPAdapter(
        max_retries=retry_strategy,
        pool_connections=pool_connections,
        pool_maxsize=pool_maxsize,
    )
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    
    logger.debug("创建 HTTP Session: retries=%d, pool=%d, methods=%s", total_retries, pool_connections, allowed_methods)
    return session


def create_eastmoney_session(
    logger: Optional[logging.Logger] = None
) -> requests.Session:
    """
    创建东财 API Session（使用默认配置）
    
    Args:
        logger: 调用方传入的 logger（可选）
        
    Returns:
        requests.Session: 配置好的 Session
        
    Raises:
        TypeError: urllib3 版本不兼容（继承自 create_retry_session）
        
    Example:
        session = create_eastmoney_session(logger=my_logger)
        response = session.get('https://api.eastmoney.com/...')
    """
    return create_retry_session(headers=DEFAULT_EASTMONEY_HEADERS, logger=logger)


def create_sina_session(
    logger: Optional[logging.Logger] = None
) -> requests.Session:
    """
    创建新浪 API Session
    
    Args:
        logger: 调用方传入的 logger（可选）
        
    Returns:
        requests.Session: 配置好的 Session
        
    Raises:
        TypeError: urllib3 版本不兼容（继承自 create_retry_session）
        
    Example:
        session = create_sina_session(logger=my_logger)
        response = session.get('http://vip.stock.finance.sina.com.cn/...')
    """
    return create_retry_session(headers=DEFAULT_SINA_HEADERS, logger=logger)


def request_with_retry(
    session: requests.Session,
    url: str,
    method: str = 'GET',
    params: Optional[Dict[str, Any]] = None,
    data: Optional[Dict[str, Any]] = None,
    json_data: Optional[Dict[str, Any]] = None,
    timeout: Union[int, Tuple[int, int]] = _DEFAULT_TIMEOUT,
    max_attempts: int = _DEFAULT_MAX_ATTEMPTS,
    delay: float = _DEFAULT_DELAY,
    logger: Optional[logging.Logger] = None,
) -> Any:
    """
    带手动重试的请求（用于 API 可能返回非 HTTP 错误的情况）
    
    注意：此函数使用**线性递增退避策略**（delay + attempt * delay），
    与 urllib3 Retry 的指数退避（backoff_factor * 2^attempt）不同。
    线性退避适合快速恢复的临时故障，指数退避适合服务器压力场景。
    
    Args:
        session: HTTP Session
        url: 请求 URL
        method: HTTP 方法（GET/POST/PUT/DELETE，默认 GET）
        params: URL 查询参数（GET 请求）
        data: 表单数据（POST 请求）
        json_data: JSON 数据（POST 请求）
        timeout: 超时时间（秒），可为 int 或 (connect_timeout, read_timeout) 元组
        max_attempts: 最大尝试次数（默认 3）
        delay: 重试基础延迟（秒，默认 1.0，线性递增）
        logger: 调用方传入的 logger（可选）
        
    Returns:
        Any: 响应 JSON 数据（可能是 dict、list、str、int 等任意类型）
        
    Raises:
        RuntimeError: 所有尝试失败（保留原始异常链）
        requests.HTTPError: HTTP 状态码错误
        requests.Timeout: 请求超时
        requests.ConnectionError: 连接错误
        json.JSONDecodeError: JSON 解析失败
        
    Example:
        # GET 请求
        session = create_retry_session(headers=DEFAULT_EASTMONEY_HEADERS)
        data = request_with_retry(
            session,
            'https://api.eastmoney.com/...',
            params={'code': '000001'},
            logger=my_logger
        )
        
        # POST 请求
        data = request_with_retry(
            session,
            'https://api.example.com/submit',
            method='POST',
            json_data={'key': 'value'},
            logger=my_logger
        )
    """
    logger = get_module_logger(logger)
    last_error: Optional[Exception] = None
    
    # 验证 method 参数
    valid_methods = ['GET', 'POST', 'PUT', 'DELETE']
    if method.upper() not in valid_methods:
        raise ValueError(f"不支持的 HTTP 方法: {method}，支持: {valid_methods}")
    method = method.upper()
    
    for attempt in range(max_attempts):
        response = None  # 初始化变量，避免 except 中未绑定
        try:
            # 根据方法类型选择请求方式
            if method == 'GET':
                response = session.get(url, params=params, timeout=timeout)
            elif method == 'POST':
                response = session.post(url, data=data, json=json_data, timeout=timeout)
            elif method == 'PUT':
                response = session.put(url, data=data, json=json_data, timeout=timeout)
            elif method == 'DELETE':
                response = session.delete(url, timeout=timeout)
            else:
                raise ValueError(f"未实现的 HTTP 方法: {method}")
            
            # response 必定不为 None（requests 总是返回 Response 对象）
            if response is None:
                raise RuntimeError(f"请求返回 None: {url}, 方法: {method}")
            
            response.raise_for_status()
            return response.json()
        except requests.HTTPError as e:
            # HTTP 状态码错误，通常不需要重试
            logger.error("HTTP 错误: %s\nURL: %s\n方法: %s\n状态码: %s", 
                         e, url, method, response.status_code if response else 'N/A')
            raise  # 直接抛出，不重试
        except requests.Timeout as e:
            last_error = e
            wait_time = delay + attempt * delay  # 线性递增退避
            if attempt < max_attempts - 1:
                logger.warning(
                    "请求超时 (尝试 %d/%d)\n"
                    "URL: %s\n"
                    "方法: %s\n"
                    "等待 %.1f秒后重试...",
                    attempt + 1, max_attempts, url, method, wait_time
                )
                time.sleep(wait_time)
            else:
                # 最后一次失败，记录警告日志
                logger.warning(
                    "请求超时 (最终尝试 %d/%d)\n"
                    "URL: %s\n"
                    "方法: %s\n"
                    "错误: %s",
                    attempt + 1, max_attempts, url, method, e
                )
        except requests.ConnectionError as e:
            last_error = e
            wait_time = delay + attempt * delay  # 线性递增退避
            if attempt < max_attempts - 1:
                logger.warning(
                    "连接错误 (尝试 %d/%d): %s\n"
                    "URL: %s\n"
                    "方法: %s\n"
                    "等待 %.1f秒后重试...",
                    attempt + 1, max_attempts, e, url, method, wait_time
                )
                time.sleep(wait_time)
            else:
                # 最后一次失败，记录警告日志
                logger.warning(
                    "连接错误 (最终尝试 %d/%d)\n"
                    "URL: %s\n"
                    "方法: %s\n"
                    "错误: %s",
                    attempt + 1, max_attempts, url, method, e
                )
        except json.JSONDecodeError as e:
            # JSON 解析失败，记录详细信息
            logger.error(
                "JSON 解析失败\n"
                "URL: %s\n"
                "方法: %s\n"
                "响应内容前200字符: %s",
                url, method, response.text[:200] if response and response.text else 'N/A'
            )
            raise  # 直接抛出，不重试
        except Exception as e:
            # 其他未知错误
            last_error = e
            wait_time = delay + attempt * delay  # 线性递增退避
            if attempt < max_attempts - 1:
                logger.warning(
                    "请求失败 (尝试 %d/%d): %s\n"
                    "URL: %s\n"
                    "方法: %s\n"
                    "等待 %.1f秒后重试...",
                    attempt + 1, max_attempts, e, url, method, wait_time
                )
                time.sleep(wait_time)
            else:
                # 最后一次失败，记录警告日志
                logger.warning(
                    "请求失败 (最终尝试 %d/%d)\n"
                    "URL: %s\n"
                    "方法: %s\n"
                    "错误: %s",
                    attempt + 1, max_attempts, url, method, e
                )
    
    logger.error("请求最终失败: %s\n方法: %s\n最后错误: %s", url, method, last_error)
    raise RuntimeError(f"请求失败: {url}, 方法: {method}") from last_error


if __name__ == '__main__':
    # 配置测试日志（复用 logger_config.py 的 setup_logger）
    # 遵循 PROJECT.md 第780-839行规范
    import sys
    from pathlib import Path as _Path
    sys.path.insert(0, str(_Path(__file__).parent.parent.parent))
    
    from data_fetchers.common.logger_config import setup_logger
    
    test_logger = setup_logger(
        'http_client',  # 脚本名称
        level=logging.DEBUG,  # 测试用 DEBUG
        console_level=logging.INFO  # 控制台用 INFO
    )
    
    # 初始化变量（避免 finally 中未绑定）
    session = None
    sina_session = None
    custom_session = None
    post_session = None
    default_session = None
    
    try:
        test_logger.info("=" * 50)
        test_logger.info("http_client.py 测试开始")
        test_logger.info("=" * 50)
        
        # 测试 1: 创建东财 Session
        test_logger.info("\n[测试 1] 创建东财 Session...")
        session = create_eastmoney_session(logger=test_logger)
        test_logger.info("Session headers: %s", session.headers.get('User-Agent'))
        test_logger.info("Referer: %s", session.headers.get('Referer'))
        
        # 测试 2: 创建新浪 Session
        test_logger.info("\n[测试 2] 创建新浪 Session...")
        sina_session = create_sina_session(logger=test_logger)
        test_logger.info("Session headers: %s", sina_session.headers.get('Referer'))
        
        # 测试 3: 自定义 Session
        test_logger.info("\n[测试 3] 自定义 Session...")
        custom_headers = {"X-Custom": "test-value"}
        custom_session = create_retry_session(
            headers=custom_headers,
            total_retries=5,
            pool_connections=20,
            logger=test_logger
        )
        test_logger.info("Custom header: %s", custom_session.headers.get('X-Custom'))
        test_logger.info("Default User-Agent: %s", custom_session.headers.get('User-Agent'))
        
        # 测试 4: get_module_logger
        test_logger.info("\n[测试 4] get_module_logger...")
        fallback_logger = get_module_logger()
        test_logger.info("Fallback logger name: %s", fallback_logger.name)
        custom_logger = get_module_logger(test_logger)
        test_logger.info("Custom logger name: %s", custom_logger.name)
        
        # 测试 5: 默认常量
        test_logger.info("\n[测试 5] 默认常量...")
        test_logger.info("_DEFAULT_TOTAL_RETRIES: %d", _DEFAULT_TOTAL_RETRIES)
        test_logger.info("_DEFAULT_TIMEOUT: %d", _DEFAULT_TIMEOUT)
        test_logger.info("_DEFAULT_RETRY_STATUS_CODES: %s", _DEFAULT_RETRY_STATUS_CODES)
        test_logger.info("_DEFAULT_ALLOWED_METHODS: %s", _DEFAULT_ALLOWED_METHODS)
        test_logger.info("DEFAULT_EASTMONEY_HEADERS keys: %s", list(DEFAULT_EASTMONEY_HEADERS.keys()))
        
        # 测试 6: allowed_methods 参数
        test_logger.info("\n[测试 6] allowed_methods 参数...")
        post_session = create_retry_session(
            headers=DEFAULT_EASTMONEY_HEADERS,
            allowed_methods=['GET', 'POST'],
            logger=test_logger
        )
        test_logger.info("POST Session 创建成功（支持 GET/POST 重试）")
        
        # 测试 7: create_retry_session 默认 headers=None
        test_logger.info("\n[测试 7] create_retry_session 默认 headers=None...")
        default_session = create_retry_session(logger=test_logger)
        test_logger.info("Default User-Agent: %s", default_session.headers.get('User-Agent'))
        test_logger.info("（应为 python-requests/x.x.x，不再默认东财请求头）")
        
        # 测试 8: request_with_retry method 参数验证
        test_logger.info("\n[测试 8] request_with_retry method 参数验证...")
        # 验证 ValueError
        try:
            request_with_retry(session, 'http://example.com', method='INVALID')
        except ValueError as e:
            test_logger.info("正确抛出 ValueError: %s", e)
        
        test_logger.info("\n" + "=" * 50)
        test_logger.info("测试完成（共 8 项测试）")
        test_logger.info("=" * 50)
        
        # 注意：异常场景测试（HTTPError/Timeout/ConnectionError）需要真实 API 环境
        # 建议在集成测试中覆盖，__main__ 仅测试模块功能
    finally:
        # 关闭 Session 释放连接池（安全检查）
        for s in [session, sina_session, custom_session, post_session, default_session]:
            if s is not None:
                s.close()
        test_logger.info("已关闭 Session 连接")