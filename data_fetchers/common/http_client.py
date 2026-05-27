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
- v1.8 (2026-05-27): 防御性编程增强（4个问题）：
    1. urllib3 版本检测：抽取 _create_retry_strategy()，用版本号判断而非异常消息字符串匹配
    2. 常量防御一致：_DEFAULT_ALLOWED_METHODS 改为不可变 tuple，与其他常量风格一致
    3. 返回类型精确：定义 JsonValue 类型别名，替代过于宽泛的 Any
    4. 生命周期管理：新增 retry_session/eastmoney_session/sina_session 上下文管理器
- v1.9 (2026-05-27): 扩展性与429处理（2个问题）：
    1. 数据源注册表：新增 _SOURCE_CONFIGS 注册表和 create_session(source) 统一入口
    2. 429 Retry-After：request_with_retry 处理 429 状态码时读取 Retry-After 头
- v1.10 (2026-05-27): 命名冲突修复（2个问题）：
    1. session(...) 与变量名 session 冲突：重命名为 source_session(...)
    2. docstring Example 变量名冲突：as session 改为 as sess
- v1.11 (2026-05-27): 异常处理与防御性修复（3个问题）：
    1. 429 last_error 未赋值：最后一次失败由循环后统一 RuntimeError 处理
    2. fallback 版本号误导：改为 '0.0.0' 确保走旧版本分支
    3. 上下文管理器 UnboundLocalError：sess 变量名统一 + try 前赋值
- v1.12 (2026-05-27): 429处理与文档修复（4个问题）：
    1. 429无Retry-After：补充else分支使用线性退避，确保等待逻辑不跳过
    2. Raises文档不符：HTTPError 补充"仅限非429"，RuntimeError 补充"含429限流重试耗尽"
    3. __all__缩进不一致：Session上下文管理器注释对齐（2空格→4空格）
    4. 类型注解保留：response初始化非死代码，是防御性代码（Pyright需要）
- v1.13 (2026-05-27): 条件判断风格统一（2个问题）：
    1. retry_after判断不一致：改为 `is not None` 与上方统一，避免空字符串边界歧义
    2. len()冗余条件：`response_text and len(...) > 0` 简化为 `response_text`
- v1.14 (2026-05-27): 三项日志精确化修复：
    1. request_with_retry Timeout 日志补充异常描述（与 ConnectionError 风格一致）
    2. request_with_retry 最后一次失败（Timeout/ConnectionError/Exception）补充 warning 日志
    3. create_session 添加 debug 日志记录数据源名称（与 create_retry_session 形成完整链路）

作者: 云瑶
日期: 2026-05-24
"""

import contextlib
import json
import logging
import time
import types
from collections.abc import Mapping
from typing import Dict, Optional, Any, Union, Tuple, List, Iterator

import requests
import urllib3
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# JSON 反序列化结果类型别名（用于 request_with_retry 返回类型）
JsonValue = Union[Dict[str, Any], List[Any], str, int, float, bool, None]

__all__ = [
    # Session 创建函数（手动管理生命周期）
    'create_retry_session',
    'create_session',  # 统一入口（注册表驱动）
    'create_eastmoney_session',  # 保留向后兼容
    'create_sina_session',  # 保留向后兼容
    # Session 上下文管理器（自动管理生命周期，推荐使用）
    'retry_session',
    'source_session',  # 统一入口上下文管理器（避免与变量名 session 冲突）
    'eastmoney_session',
    'sina_session',
    # 请求函数
    'request_with_retry',
    # 日志函数
    'get_module_logger',
    # 请求头常量（供外部复用）
    'DEFAULT_EASTMONEY_HEADERS',
    'DEFAULT_SINA_HEADERS',
    # 数据源注册（供外部查询可用数据源）
    'get_available_sources',
    # 类型别名（供外部类型注解使用）
    'JsonValue',
]

# 模块级 fallback logger（遵循 PROJECT.md 公共模块日志规范）
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

# 默认允许重试的 HTTP 方法（不可变 tuple，防御性风格）
_DEFAULT_ALLOWED_METHODS: Tuple[str, ...] = ("GET",)

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

# 数据源配置注册表（新增数据源只需在此处添加一行）
# key: 数据源名称（用于 create_session(source) 参数）
# value: 默认请求头 MappingProxyType
_SOURCE_CONFIGS: Dict[str, Mapping[str, str]] = {
    'eastmoney': DEFAULT_EASTMONEY_HEADERS,
    'sina': DEFAULT_SINA_HEADERS,
}


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


def _create_retry_strategy(
    retry_params: Dict[str, Any],
    allowed_methods: List[str],
) -> Retry:
    """
    创建 urllib3 Retry 策略（根据版本自动选择参数名）
    
    urllib3 >= 2.0 使用 allowed_methods 参数
    urllib3 < 2.0 使用 method_whitelist 参数
    
    Args:
        retry_params: Retry 公共参数（total, backoff_factor, status_forcelist）
        allowed_methods: 允许重试的 HTTP 方法列表
        
    Returns:
        Retry: 配置好的重试策略
        
    Example:
        >>> retry_params = {'total': 3, 'backoff_factor': 1.0, 'status_forcelist': [429, 500]}
        >>> strategy = _create_retry_strategy(retry_params, ['GET'])
    """
    # 直接检测 urllib3 版本号，避免异常消息字符串匹配的不确定性
    # urllib3.__version__ 是公开属性，Pyright 静态分析不认可但运行时有效
    # fallback='0.0.0' 仅用于极端异常场景，确保走旧版本分支（method_whitelist）
    version_str = getattr(urllib3, '__version__', '0.0.0')
    major_version = int(version_str.split('.')[0])
    
    if major_version >= 2:
        # urllib3 >= 2.0 使用 allowed_methods
        return Retry(**retry_params, allowed_methods=allowed_methods)
    else:
        # urllib3 < 2.0 使用 method_whitelist（Pyright 不认可但旧版本存在）
        return Retry(**retry_params, **{'method_whitelist': allowed_methods})  # pyright: ignore[reportCallIssue]


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
    
    # 允许重试的 HTTP 方法（tuple 转 list）
    if allowed_methods is None:
        allowed_methods = list(_DEFAULT_ALLOWED_METHODS)
    
    # 创建重试策略（使用版本检测而非异常消息字符串匹配）
    retry_params = {
        'total': total_retries,
        'backoff_factor': backoff_factor,
        'status_forcelist': _DEFAULT_RETRY_STATUS_CODES,
    }
    retry_strategy = _create_retry_strategy(retry_params, allowed_methods)
    
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


def get_available_sources() -> List[str]:
    """
    获取可用的数据源列表
    
    Returns:
        List[str]: 数据源名称列表
        
    Example:
        >>> get_available_sources()
        ['eastmoney', 'sina']
    """
    return list(_SOURCE_CONFIGS.keys())


def create_session(
    source: str,
    total_retries: int = _DEFAULT_TOTAL_RETRIES,
    backoff_factor: float = _DEFAULT_BACKOFF_FACTOR,
    pool_connections: int = _DEFAULT_POOL_CONNECTIONS,
    pool_maxsize: int = _DEFAULT_POOL_MAXSIZE,
    allowed_methods: Optional[List[str]] = None,
    logger: Optional[logging.Logger] = None,
) -> requests.Session:
    """
    创建数据源 Session（注册表驱动，统一入口）
    
    新增数据源只需在 _SOURCE_CONFIGS 注册表添加一行，
    无需新增函数，避免模块随数据源数量线性膨胀。
    
    Args:
        source: 数据源名称（eastmoney/sina，可通过 get_available_sources() 查询）
        total_retries: 总重试次数（默认 3）
        backoff_factor: 退避因子（默认 1.0）
        pool_connections: 连接池大小（默认 10）
        pool_maxsize: 最大连接数（默认 10）
        allowed_methods: 允许重试的 HTTP 方法（默认 ["GET"]）
        logger: 调用方传入的 logger（可选）
        
    Returns:
        requests.Session: 配置好的 Session
        
    Raises:
        ValueError: 数据源不存在
        
    Example:
        # 查询可用数据源
        >>> get_available_sources()
        ['eastmoney', 'sina']
        
        # 创建东财 Session
        >>> session = create_session('eastmoney', logger=my_logger)
        
        # 创建新浪 Session
        >>> session = create_session('sina', total_retries=5)
    """
    if source not in _SOURCE_CONFIGS:
        available = get_available_sources()
        raise ValueError(f"数据源不存在: {source}，可用: {available}")
    
    headers = _SOURCE_CONFIGS[source]
    logger = get_module_logger(logger)
    logger.debug("创建数据源 Session: source=%s", source)
    
    return create_retry_session(
        headers=headers,
        total_retries=total_retries,
        backoff_factor=backoff_factor,
        pool_connections=pool_connections,
        pool_maxsize=pool_maxsize,
        allowed_methods=allowed_methods,
        logger=logger,
    )


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
) -> JsonValue:
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
        JsonValue: JSON 反序列化结果（dict/list/str/int/float/bool/None）
        
    Raises:
        RuntimeError: 所有尝试失败（含 429 限流重试耗尽），保留原始异常链
        requests.HTTPError: HTTP 状态码错误（仅限非 429 错误）
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
        response: Optional[requests.Response] = None  # 类型注解 + 防御性初始化
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
            
            response.raise_for_status()
            return response.json()
        except requests.HTTPError as e:
            # HTTP 状态码错误
            # 429 状态码（限流）特殊处理：读取 Retry-After 头后重试
            last_error = e  # 记录错误，最后一次失败由循环后统一处理
            status_code = response.status_code if response else None
            
            if status_code == 429 and attempt < max_attempts - 1:
                # 读取 Retry-After 头（服务器要求的最短等待时间）
                retry_after = response.headers.get('Retry-After') if response else None
                
                # 计算 wait_time：有 Retry-After 用其值，否则回退线性退避
                if retry_after is not None:
                    # Retry-After 可能是秒数（数字）或日期（RFC 2822）
                    # 简化处理：只解析数字格式，非数字格式回退到线性退避
                    try:
                        wait_time = float(retry_after)
                    except ValueError:
                        # 非数字格式（如日期），回退到线性退避
                        wait_time = _calc_wait_time(attempt, delay)
                else:
                    # 无 Retry-After 头，使用线性退避
                    wait_time = _calc_wait_time(attempt, delay)
                
                logger.warning(
                    "请求被限流 (429) (尝试 %d/%d)\n"
                    "URL: %s\n"
                    "方法: %s\n"
                    "Retry-After: %s\n"
                    "等待 %.1f秒后重试...",
                    attempt + 1, max_attempts, url, method, retry_after if retry_after is not None else 'N/A', wait_time
                )
                time.sleep(wait_time)
                continue  # 继续下一次尝试
            
            # 非 429 直接抛出；429 最后一次失败由循环后统一处理
            if status_code != 429:
                logger.error("HTTP 错误: %s\nURL: %s\n方法: %s\n状态码: %s", 
                             e, url, method, status_code if status_code else 'N/A')
                raise
        except requests.Timeout as e:
            last_error = e
            if attempt < max_attempts - 1:
                wait_time = _calc_wait_time(attempt, delay)
                logger.warning(
                    "请求超时 (尝试 %d/%d): %s\n"
                    "URL: %s\n"
                    "方法: %s\n"
                    "等待 %.1f秒后重试...",
                    attempt + 1, max_attempts, e, url, method, wait_time
                )
                time.sleep(wait_time)
            else:
                # 最后一次失败记录详细日志（循环后统一 error 丢失"第几次尝试"上下文）
                logger.warning(
                    "请求超时（最后一次尝试 %d/%d）: %s\n"
                    "URL: %s\n"
                    "方法: %s",
                    attempt + 1, max_attempts, e, url, method
                )
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
            else:
                # 最后一次失败记录详细日志（循环后统一 error 丢失"第几次尝试"上下文）
                logger.warning(
                    "连接错误（最后一次尝试 %d/%d）: %s\n"
                    "URL: %s\n"
                    "方法: %s",
                    attempt + 1, max_attempts, e, url, method
                )
        except (json.JSONDecodeError, requests.exceptions.JSONDecodeError) as e:
            # JSON 解析失败，记录详细信息
            # 使用 getattr 安全访问 response.text，避免 streaming 模式问题
            response_text = getattr(response, 'text', None)
            preview = response_text[:200] if response_text else 'N/A'
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
            else:
                # 最后一次失败记录详细日志（循环后统一 error 丢失"第几次尝试"上下文）
                logger.warning(
                    "请求失败（最后一次尝试 %d/%d）: %s\n"
                    "URL: %s\n"
                    "方法: %s",
                    attempt + 1, max_attempts, e, url, method
                )
    
    # 所有尝试失败，统一记录 error 日志
    logger.error("请求最终失败: %s\n方法: %s\n最后错误: %s", url, method, last_error)
    raise RuntimeError(f"请求失败: {url}, 方法: {method}") from last_error


@contextlib.contextmanager
def retry_session(
    headers: Optional[Mapping[str, str]] = None,
    total_retries: int = _DEFAULT_TOTAL_RETRIES,
    backoff_factor: float = _DEFAULT_BACKOFF_FACTOR,
    pool_connections: int = _DEFAULT_POOL_CONNECTIONS,
    pool_maxsize: int = _DEFAULT_POOL_MAXSIZE,
    allowed_methods: Optional[List[str]] = None,
    logger: Optional[logging.Logger] = None,
) -> Iterator[requests.Session]:
    """
    带自动资源清理的 HTTP Session 上下文管理器
    
    推荐用于长期运行的服务或频繁创建 Session 的场景，
    避免忘记调用 session.close() 导致连接泄漏。
    
    Args:
        headers: 自定义请求头（默认 None）
        total_retries: 总重试次数（默认 3）
        backoff_factor: 退避因子（默认 1.0）
        pool_connections: 连接池大小（默认 10）
        pool_maxsize: 最大连接数（默认 10）
        allowed_methods: 允许重试的 HTTP 方法（默认 ["GET"]）
        logger: 调用方传入的 logger（可选）
        
    Yields:
        requests.Session: 配置好的 Session（自动关闭）
        
    Example:
        >>> with retry_session(headers=DEFAULT_EASTMONEY_HEADERS) as sess:
        >>>     response = sess.get('https://api.eastmoney.com/...')
        >>> # sess 自动关闭，无需手动调用 sess.close()
    """
    sess = create_retry_session(
        headers=headers,
        total_retries=total_retries,
        backoff_factor=backoff_factor,
        pool_connections=pool_connections,
        pool_maxsize=pool_maxsize,
        allowed_methods=allowed_methods,
        logger=logger,
    )
    try:
        yield sess
    finally:
        sess.close()


@contextlib.contextmanager
def eastmoney_session(
    logger: Optional[logging.Logger] = None
) -> Iterator[requests.Session]:
    """
    东财 API Session 上下文管理器（自动资源清理）
    
    Args:
        logger: 调用方传入的 logger（可选）
        
    Yields:
        requests.Session: 配置好的东财 Session（自动关闭）
        
    Example:
        >>> with eastmoney_session(logger=my_logger) as sess:
        >>>     response = sess.get('https://api.eastmoney.com/...')
        >>> # sess 自动关闭
    """
    sess = create_eastmoney_session(logger=logger)
    try:
        yield sess
    finally:
        sess.close()


@contextlib.contextmanager
def sina_session(
    logger: Optional[logging.Logger] = None
) -> Iterator[requests.Session]:
    """
    新浪 API Session 上下文管理器（自动资源清理）
    
    Args:
        logger: 调用方传入的 logger（可选）
        
    Yields:
        requests.Session: 配置好的新浪 Session（自动关闭）
        
    Example:
        >>> with sina_session(logger=my_logger) as sess:
        >>>     response = sess.get('http://vip.stock.finance.sina.com.cn/...')
        >>> # sess 自动关闭
    """
    sess = create_sina_session(logger=logger)
    try:
        yield sess
    finally:
        sess.close()


@contextlib.contextmanager
def source_session(
    source: str,
    total_retries: int = _DEFAULT_TOTAL_RETRIES,
    backoff_factor: float = _DEFAULT_BACKOFF_FACTOR,
    pool_connections: int = _DEFAULT_POOL_CONNECTIONS,
    pool_maxsize: int = _DEFAULT_POOL_MAXSIZE,
    allowed_methods: Optional[List[str]] = None,
    logger: Optional[logging.Logger] = None,
) -> Iterator[requests.Session]:
    """
    数据源 Session 上下文管理器（注册表驱动，自动资源清理）
    
    Args:
        source: 数据源名称（eastmoney/sina）
        total_retries: 总重试次数（默认 3）
        backoff_factor: 退避因子（默认 1.0）
        pool_connections: 连接池大小（默认 10）
        pool_maxsize: 最大连接数（默认 10）
        allowed_methods: 允许重试的 HTTP 方法（默认 ["GET"]）
        logger: 调用方传入的 logger（可选）
        
    Yields:
        requests.Session: 配置好的 Session（自动关闭）
        
    Raises:
        ValueError: 数据源不存在
        
    Example:
        >>> with source_session('eastmoney', logger=my_logger) as sess:
        >>>     response = sess.get('https://api.eastmoney.com/...')
        >>> # sess 自动关闭
    """
    sess = create_session(
        source=source,
        total_retries=total_retries,
        backoff_factor=backoff_factor,
        pool_connections=pool_connections,
        pool_maxsize=pool_maxsize,
        allowed_methods=allowed_methods,
        logger=logger,
    )
    try:
        yield sess
    finally:
        sess.close()


