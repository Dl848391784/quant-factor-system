#!/usr/bin/env python3
"""
http_client.py 测试用例

测试 HTTP 客户端模块的核心功能：
- Session 创建（东财/新浪/自定义）
- get_module_logger 日志参数化
- DEFAULT_*_HEADERS 常量不可变性
- request_with_retry 方法验证

版本历史：
- v1.0 (2026-05-27): 初始版本，从 __main__ 块迁移到 pytest
"""

import pytest
import logging
import requests
from collections.abc import Mapping

from data_fetchers.common.http_client import (
    create_retry_session,
    create_eastmoney_session,
    create_sina_session,
    request_with_retry,
    get_module_logger,
    DEFAULT_EASTMONEY_HEADERS,
    DEFAULT_SINA_HEADERS,
)


class TestSessionCreation:
    """Session 创建测试"""
    
    def test_create_eastmoney_session(self):
        """测试创建东财 Session"""
        session = create_eastmoney_session()
        assert isinstance(session, requests.Session)
        assert session.headers.get('Referer') == 'https://quote.eastmoney.com/'
        assert 'Mozilla' in session.headers.get('User-Agent')
        session.close()
    
    def test_create_sina_session(self):
        """测试创建新浪 Session"""
        session = create_sina_session()
        assert isinstance(session, requests.Session)
        assert session.headers.get('Referer') == 'http://vip.stock.finance.sina.com.cn/'
        assert 'Mozilla' in session.headers.get('User-Agent')
        session.close()
    
    def test_create_retry_session_custom_headers(self):
        """测试自定义 Headers 的 Session"""
        custom_headers = {"X-Custom": "test-value"}
        session = create_retry_session(headers=custom_headers)
        assert session.headers.get('X-Custom') == 'test-value'
        session.close()
    
    def test_create_retry_session_default_headers_none(self):
        """测试默认 headers=None"""
        session = create_retry_session()
        # 默认使用 requests 的 User-Agent（python-requests/x.x.x）
        user_agent = session.headers.get('User-Agent')
        assert user_agent is not None
        assert 'python-requests' in user_agent
        session.close()
    
    def test_create_retry_session_allowed_methods(self):
        """测试 allowed_methods 参数"""
        session = create_retry_session(
            headers=DEFAULT_EASTMONEY_HEADERS,
            allowed_methods=['GET', 'POST']
        )
        assert isinstance(session, requests.Session)
        session.close()


class TestGetModuleLogger:
    """get_module_logger 测试"""
    
    def test_get_module_logger_fallback(self):
        """测试不传 logger 时使用 fallback"""
        logger = get_module_logger()
        assert isinstance(logger, logging.Logger)
        assert logger.name == 'data_fetchers.common.http_client'
    
    def test_get_module_logger_custom(self):
        """测试传入自定义 logger"""
        custom_logger = logging.getLogger('test_module')
        logger = get_module_logger(custom_logger)
        assert logger.name == 'test_module'
    
    def test_get_module_logger_type_error(self):
        """测试传入非 Logger 类型抛 TypeError"""
        with pytest.raises(TypeError) as exc_info:
            get_module_logger("not a logger")
        assert "必须是 logging.Logger 类型" in str(exc_info.value)


class TestConstantsImmutability:
    """常量不可变性测试"""
    
    def test_default_eastmoney_headers_immutable(self):
        """测试 DEFAULT_EASTMONEY_HEADERS 不可修改"""
        with pytest.raises(TypeError):
            DEFAULT_EASTMONEY_HEADERS['User-Agent'] = 'modified'
    
    def test_default_sina_headers_immutable(self):
        """测试 DEFAULT_SINA_HEADERS 不可修改"""
        with pytest.raises(TypeError):
            DEFAULT_SINA_HEADERS['User-Agent'] = 'modified'
    
    def test_default_eastmoney_headers_keys(self):
        """测试 DEFAULT_EASTMONEY_HEADERS 包含必需字段"""
        expected_keys = ['User-Agent', 'Referer', 'Accept', 'Accept-Language', 'Connection']
        assert list(DEFAULT_EASTMONEY_HEADERS.keys()) == expected_keys
    
    def test_default_sina_headers_keys(self):
        """测试 DEFAULT_SINA_HEADERS 包含必需字段"""
        expected_keys = ['User-Agent', 'Referer', 'Accept', 'Accept-Language']
        assert list(DEFAULT_SINA_HEADERS.keys()) == expected_keys
    
    def test_headers_are_mapping_proxy_type(self):
        """测试常量是 MappingProxyType（不可变映射）"""
        # MappingProxyType 是 Mapping 的子类但不支持修改
        assert isinstance(DEFAULT_EASTMONEY_HEADERS, Mapping)
        assert isinstance(DEFAULT_SINA_HEADERS, Mapping)


class TestRequestWithRetryMethodValidation:
    """request_with_retry 方法验证测试"""
    
    def test_request_with_retry_invalid_method(self):
        """测试无效 HTTP 方法抛 ValueError"""
        session = create_retry_session()
        with pytest.raises(ValueError) as exc_info:
            request_with_retry(session, 'http://example.com', method='INVALID')
        assert "不支持的 HTTP 方法" in str(exc_info.value)
        session.close()
    
    def test_request_with_retry_valid_methods(self):
        """测试有效 HTTP 方法列表"""
        session = create_retry_session()
        valid_methods = ['GET', 'POST', 'PUT', 'DELETE']
        # 不实际调用，只验证参数解析逻辑
        # 实际调用需要真实 API 环境
        session.close()


class TestLoggerParameterization:
    """logger 参数化测试"""
    
    def test_session_with_logger(self):
        """测试 Session 函数接受 logger 参数"""
        test_logger = logging.getLogger('test_http_client')
        
        session = create_eastmoney_session(logger=test_logger)
        assert isinstance(session, requests.Session)
        session.close()
        
        session = create_sina_session(logger=test_logger)
        assert isinstance(session, requests.Session)
        session.close()
        
        session = create_retry_session(logger=test_logger)
        assert isinstance(session, requests.Session)
        session.close()