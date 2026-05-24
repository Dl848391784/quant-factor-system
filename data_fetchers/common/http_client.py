#!/usr/bin/env python3
"""
HTTP 客户端模块

统一 HTTP Session 创建和请求头配置。

作者: 云瑶
日期: 2026-05-24
"""

import logging
import requests
from requests.adapters import HTTPAdapter
from typing import Dict, Optional
from urllib3.util.retry import Retry

logger = logging.getLogger(__name__)


# 默认东财 API 请求头
DEFAULT_EASTMONEY_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Referer": "https://quote.eastmoney.com/",
    "Accept": "*/*",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Connection": "keep-alive",
}

# 新浪 API 请求头
DEFAULT_SINA_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Referer": "http://vip.stock.finance.sina.com.cn/",
    "Accept": "*/*",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}


def create_retry_session(
    headers: Optional[Dict[str, str]] = None,
    total_retries: int = 3,
    backoff_factor: float = 1.0,
    pool_connections: int = 10,
    pool_maxsize: int = 10,
) -> requests.Session:
    """
    创建带重试机制的 HTTP Session
    
    Args:
        headers: 自定义请求头（默认使用东财请求头）
        total_retries: 总重试次数（默认 3）
        backoff_factor: 退避因子（默认 1.0）
        pool_connections: 连接池大小（默认 10）
        pool_maxsize: 最大连接数（默认 10）
        
    Returns:
        requests.Session: 配置好的 Session
    """
    session = requests.Session()
    
    # 设置请求头
    if headers is None:
        headers = DEFAULT_EASTMONEY_HEADERS
    session.headers.update(headers)
    
    # 创建重试策略
    try:
        retry_strategy = Retry(
            total=total_retries,
            backoff_factor=backoff_factor,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["GET"],
        )
    except TypeError:
        # urllib3 < 2.0 使用 method_whitelist
        retry_strategy = Retry(
            total=total_retries,
            backoff_factor=backoff_factor,
            status_forcelist=[429, 500, 502, 503, 504],
            method_whitelist=["GET"],
        )
    
    # 配置适配器
    adapter = HTTPAdapter(
        max_retries=retry_strategy,
        pool_connections=pool_connections,
        pool_maxsize=pool_maxsize,
    )
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    
    logger.debug(f"创建 HTTP Session: retries={total_retries}, pool={pool_connections}")
    return session


def create_eastmoney_session() -> requests.Session:
    """
    创建东财 API Session（使用默认配置）
    
    Returns:
        requests.Session: 配置好的 Session
    """
    return create_retry_session(headers=DEFAULT_EASTMONEY_HEADERS)


def create_sina_session() -> requests.Session:
    """
    创建新浪 API Session
    
    Returns:
        requests.Session: 配置好的 Session
    """
    return create_retry_session(headers=DEFAULT_SINA_HEADERS)


def request_with_retry(
    session: requests.Session,
    url: str,
    params: Optional[Dict] = None,
    timeout: int = 30,
    max_attempts: int = 3,
    delay: float = 1.0,
) -> Dict:
    """
    带手动重试的请求（用于 API 可能返回非 HTTP 错误的情况）
    
    Args:
        session: HTTP Session
        url: 请求 URL
        params: 请求参数
        timeout: 超时时间（秒）
        max_attempts: 最大尝试次数
        delay: 重试延迟（秒）
        
    Returns:
        Dict: 响应 JSON 数据
        
    Raises:
        RuntimeError: 所有尝试失败
    """
    last_error: Exception | None = None
    
    for attempt in range(max_attempts):
        try:
            response = session.get(url, params=params, timeout=timeout)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            last_error = e
            if attempt < max_attempts - 1:
                wait_time = delay + attempt * delay
                logger.warning(f"请求失败 (尝试 {attempt + 1}/{max_attempts}): {e}, 等待 {wait_time}秒...")
                import time
                time.sleep(wait_time)
    
    raise RuntimeError(f"请求失败: {url}, 错误: {last_error}")


if __name__ == '__main__':
    # 测试 Session 创建
    print("创建东财 Session...")
    session = create_eastmoney_session()
    print(f"Session headers: {session.headers.get('User-Agent')}")
    
    print("\n创建新浪 Session...")
    sina_session = create_sina_session()
    print(f"Session headers: {sina_session.headers.get('Referer')}")
    
    print("\n测试自定义 Session...")
    custom_headers = {"X-Custom": "test"}
    custom_session = create_retry_session(headers=custom_headers)
    print(f"Custom header: {custom_session.headers.get('X-Custom')}")
    
    print("\n测试完成")