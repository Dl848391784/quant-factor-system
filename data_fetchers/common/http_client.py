#!/usr/bin/env python3
"""
HTTP 客户端模块

统一 HTTP Session 创建和请求头配置。

版本历史：
- v1.0 (2026-05-24): 初始版本，创建 create_retry_session、create_eastmoney_session、create_sina_session
- v1.1 (2026-05-25): 新增 request_with_retry，logger 参数化，异常处理精确化
- v1.2 (2026-05-25): 新增 get_module_logger，__all__ 导出，docstring Example 补充
- v1.3 (2026-05-25): 模块级常量补全，请求头数据来源注释，返回类型修复
- v1.4 (2026-05-25): 安全性修复（MappingProxyType 不可变常量、缩小异常捕获范围、安全访问 response.text）
- v1.5 (2026-05-25): get_module_logger 类型验证同步（与 stock_utils.py 保持一致）
- v1.6 (2026-05-27): 测试规范迁移：
    1. 导入顺序修复（PEP 8：标准库 → 第三方库，typing 移到 requests 之前）
    2. 删除 __main__ 测试代码，迁移到 pytest 测试文件 test_http_client.py（16 个测试用例）
- v1.7 (2026-05-27): 重试机制修复（4个问题）：
    1. 双重重试叠加：create_retry_session 与 request_with_retry 互斥警告，docstring 明确用法
    2. 退避时间计算：抽取 _calc_wait_time() 函数，修正线性递增逻辑（attempt=0→1×delay）
    3. 死代码清理：删除 if response is None 检查（requests 永不返回 None）
    4. 重复日志修复：删除三处 else 子句，最终失败统一由循环后 logger.error 记录

作者: 云瑶
日期: 2026-05-24
"""

import json
import logging
import time
import types
from collections.abc import Mapping
from typing import Dict, Optional, Any, Union, Tuple, List

import requests
from requests.adapters import HTTPAdapter
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
# 使用 MappingProxyType 包装，防止外部修改影响所有调用
_EASTMONEY_HEADERS_DICT = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Referer": "https://quote.eastmoney.com/",
    "Accept": "*/*",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Connection": "keep-alive",
}
DEFAULT_EASTMONEY_HEADERS = types.MappingProxyType(_EASTMONEY_HEADERS_DICT)

# 新浪 API 请求头（数据来源：浏览器开发者工具抓包，2026-05-24）
# 用途：模拟浏览器访问新浪财经 API，避免被拦截
# 注意：User-Agent 中的 Chrome 版本号（120.0.0.0）需要定期更新（建议每季度检查）
# 使用 MappingProxyType 包装，防止外部修改影响所有调用
_SINA_HEADERS_DICT = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Referer": "http://vip.stock.finance.sina.com.cn/",
    "Accept": "*/*",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}
DEFAULT_SINA_HEADERS = types.MappingProxyType(_SINA_HEADERS_DICT)


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
        'data_fetchers.common.http_client'
        
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


def create_retry_session(
    headers: Optional[Mapping[str, str]] = None,
    total_retries: int = _DEFAULT_TOTAL_RETRIES,
    backoff_factor: float = _DEFAULT_BACKOFF_FACTOR,
    pool_connections: int = _DEFAULT_POOL_CONNECTIONS,
    pool_maxsize: int = _DEFAULT_POOL_MAXSIZE,
    allowed_methods: Optional[List[str]] = None,
    logger: Optional[logging.Logger] = None,
) -> requests.Session:
    """
    创建带重试机制的 HTTP Session（urllib3 层自动重试）
    
    ⚠️ 互斥警告：此函数与 request_with_retry() 互斥，二选一使用：
    
    方案 A（推荐用于标准 HTTP 错误）：
        session = create_retry_session(total_retries=3)
        response = session.get(url)  # urllib3 自动重试 3 次
    
    方案 B（用于需解析响应内容判断重试的场景）：
        session = create_retry_session(total_retries=0)  # 禁用 urllib3 重试
        data = request_with_retry(session, url, max_attempts=3)  # 应用层重试
    
    错误用法（双重重试叠加）：
        session = create_retry_session(total_retries=3)
        data = request_with_retry(session, url, max_attempts=3)
        # 最坏情况：3×(1+3)=12 次请求，行为不透明
    
    Args:
        headers: 自定义请求头（默认 None，支持 Dict 或 MappingProxyType）
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
    
    # urllib3 版本兼容处理：只捕获 allowed_methods 参数错误
    # 其他参数错误（如拼写错误）正常抛出，避免隐藏真正的 bug
    retry_strategy = None
    try:
        # urllib3 >= 2.0 使用 allowed_methods
        retry_strategy = Retry(**retry_params, allowed_methods=allowed_methods)
    except TypeError as e:
        # 检查是否是 allowed_methods 参数错误（urllib3 版本不兼容）
        if 'allowed_methods' in str(e) or 'got an unexpected keyword argument' in str(e):
            # urllib3 < 2.0 使用 method_whitelist
            retry_strategy = Retry(**retry_params, method_whitelist=allowed_methods)
            logger.debug("urllib3 版本兼容: 使用 method_whitelist 参数")
        else:
            # 其他 TypeError 正常抛出（如参数拼写错误）
            raise
    
    if retry_strategy is None:
        raise RuntimeError("创建 Retry 策略失败")
    
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


def _calc_wait_time(attempt: int, delay: float) -> float:
    """
    计算线性递增退避等待时间
    
    Args:
        attempt: 当前尝试次数（从 0 开始）
        delay: 基础延迟（秒）
        
    Returns:
        等待时间（秒）
        
    Example:
        >>> _calc_wait_time(0, 1.0)  # 第 1 次失败后等待 1 秒
        1.0
        >>> _calc_wait_time(1, 1.0)  # 第 2 次失败后等待 2 秒
        2.0
        >>> _calc_wait_time(2, 1.0)  # 第 3 次失败后等待 3 秒
        3.0
    """
    return (attempt + 1) * delay


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
    带手动重试的请求（应用层重试，用于需解析响应内容判断重试的场景）
    
    ⚠️ 互斥警告：此函数与 create_retry_session(total_retries>0) 互斥。
    若 session 已配置 urllib3 重试，叠加此函数会导致双重重试。
    正确用法：create_retry_session(total_retries=0) 禁用 urllib3 重试后使用此函数。
    
    退避策略：线性递增（attempt=0 等待 1×delay，attempt=1 等待 2×delay...）
    与 urllib3 Retry 的指数退避（backoff_factor × 2^attempt）不同。
    线性退避适合快速恢复的临时故障，指数退避适合服务器压力场景。
    
    Args:
        session: HTTP Session（应使用 create_retry_session(total_retries=0) 创建）
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
        # 应用层重试（需解析响应内容）
        session = create_retry_session(total_retries=0)  # 禁用 urllib3 重试
        data = request_with_retry(
            session,
            'https://api.eastmoney.com/...',
            params={'code': '000001'},
            max_attempts=3,
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
        response: Optional[requests.Response] = None
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
            
            # requests 总是返回 Response 对象，不会返回 None（此处仅类型注解需要）
            response.raise_for_status()
            return response.json()
        except requests.HTTPError as e:
            # HTTP 状态码错误，通常不需要重试
            logger.error("HTTP 错误: %s\nURL: %s\n方法: %s\n状态码: %s", 
                         e, url, method, response.status_code if response else 'N/A')
            raise  # 直接抛出，不重试
        except requests.Timeout as e:
            last_error = e
            if attempt < max_attempts - 1:
                wait_time = _calc_wait_time(attempt, delay)
                logger.warning(
                    "请求超时 (尝试 %d/%d)\n"
                    "URL: %s\n"
                    "方法: %s\n"
                    "等待 %.1f秒后重试...",
                    attempt + 1, max_attempts, url, method, wait_time
                )
                time.sleep(wait_time)
        except requests.ConnectionError as e:
            last_error = e
            if attempt < max_attempts - 1:
                wait_time = _calc_wait_time(attempt, delay)
                logger.warning(
                    "连接错误 (尝试 %d/%d): %s\n"
                    "URL: %s\n"
                    "方法: %s\n"
                    "等待 %.1f秒后重试...",
                    attempt + 1, max_attempts, e, url, method, wait_time
                )
                time.sleep(wait_time)
        except (json.JSONDecodeError, requests.exceptions.JSONDecodeError) as e:
            # JSON 解析失败，记录详细信息
            # 使用 getattr 安全访问 response.text，避免 streaming 模式问题
            response_text = getattr(response, 'text', None)
            preview = response_text[:200] if response_text and len(response_text) > 0 else 'N/A'
            logger.error(
                "JSON 解析失败\n"
                "URL: %s\n"
                "方法: %s\n"
                "响应内容前200字符: %s\n"
                "错误类型: %s",
                url, method, preview, type(e).__name__
            )
            raise  # 直接抛出，不重试
        except Exception as e:
            # 其他未知错误
            last_error = e
            if attempt < max_attempts - 1:
                wait_time = _calc_wait_time(attempt, delay)
                logger.warning(
                    "请求失败 (尝试 %d/%d): %s\n"
                    "URL: %s\n"
                    "方法: %s\n"
                    "等待 %.1f秒后重试...",
                    attempt + 1, max_attempts, e, url, method, wait_time
                )
                time.sleep(wait_time)
    
    # 所有尝试失败，统一记录 error 日志
    logger.error("请求最终失败: %s\n方法: %s\n最后错误: %s", url, method, last_error)
    raise RuntimeError(f"请求失败: {url}, 方法: {method}") from last_error


