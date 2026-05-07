#!/usr/bin/env python3
"""
IP 频率限制中间件
作者: 云舟
功能: 实现基于 IP 的请求频率限制，防止暴力破解

策略:
    - 同一 IP 1 分钟内最多 10 次登录请求
    - 超过限制返回 429 Too Many Requests
    - 使用内存缓存（字典）记录 IP 访问次数
"""

import time
from collections import defaultdict
from datetime import datetime, timedelta
from functools import wraps
from typing import Dict, List, Optional, Tuple

# ========== 配置 ==========

# IP 频率限制参数
RATE_LIMIT_MAX_REQUESTS = 10  # 最大请求次数
RATE_LIMIT_WINDOW_SECONDS = 60  # 时间窗口（秒）

# 内存缓存：记录每个 IP 的请求时间列表
# 格式: {ip_address: [timestamp1, timestamp2, ...]}
ip_request_counts: Dict[str, List[float]] = defaultdict(list)


# ========== 核心函数 ==========

def check_rate_limit(ip_address: str) -> Tuple[bool, Optional[str]]:
    """
    检查 IP 是否超过频率限制
    
    Args:
        ip_address: IP 地址
        
    Returns:
        (是否允许请求, 错误消息)
        如果允许，返回 (True, None)
        如果拒绝，返回 (False, 错误消息)
    """
    now = time.time()
    
    # 清理过期记录（超过时间窗口的请求）
    ip_request_counts[ip_address] = [
        t for t in ip_request_counts[ip_address]
        if now - t < RATE_LIMIT_WINDOW_SECONDS
    ]
    
    # 检查是否超限
    request_count = len(ip_request_counts[ip_address])
    
    if request_count >= RATE_LIMIT_MAX_REQUESTS:
        # 计算需要等待的时间
        oldest_request = min(ip_request_counts[ip_address])
        wait_seconds = int(RATE_LIMIT_WINDOW_SECONDS - (now - oldest_request))
        
        return False, f'请求过于频繁，请等待 {wait_seconds} 秒后重试'
    
    # 记录此次请求
    ip_request_counts[ip_address].append(now)
    
    return True, None


def get_request_count(ip_address: str) -> int:
    """
    获取 IP 当前时间窗口内的请求次数
    
    Args:
        ip_address: IP 地址
        
    Returns:
        当前请求次数
    """
    now = time.time()
    
    # 清理过期记录
    ip_request_counts[ip_address] = [
        t for t in ip_request_counts[ip_address]
        if now - t < RATE_LIMIT_WINDOW_SECONDS
    ]
    
    return len(ip_request_counts[ip_address])


def clear_rate_limit(ip_address: str) -> bool:
    """
    清除 IP 的频率限制记录
    
    Args:
        ip_address: IP 地址
        
    Returns:
        True 如果成功清除
    """
    if ip_address in ip_request_counts:
        del ip_request_counts[ip_address]
        return True
    return False


# ========== Flask 装饰器 ==========

def rate_limit_decorator(f):
    """
    Flask 路由装饰器：自动检查 IP 频率限制
    
    用法:
        @app.route('/api/auth/login', methods=['POST'])
        @rate_limit_decorator
        def api_auth_login():
            ...
    
    如果超过限制，返回:
        {
            'success': False,
            'error': '请求过于频繁，请等待 X 秒后重试',
            'code': 429
        }
    """
    @wraps(f)
    def wrapped(*args, **kwargs):
        # 获取 IP 地址（从 Flask request 对象）
        from flask import request, jsonify
        
        ip_address = request.remote_addr
        
        # 检查频率限制
        allowed, error_msg = check_rate_limit(ip_address)
        
        if not allowed:
            return jsonify({
                'success': False,
                'error': error_msg,
                'code': 429
            }), 429
        
        # 继续执行原函数
        return f(*args, **kwargs)
    
    return wrapped


# ========== 统计函数 ==========

def get_rate_limit_stats() -> Dict:
    """
    获取频率限制统计信息
    
    Returns:
        统计信息 dict
    """
    now = time.time()
    
    # 清理所有过期记录
    for ip in list(ip_request_counts.keys()):
        ip_request_counts[ip] = [
            t for t in ip_request_counts[ip]
            if now - t < RATE_LIMIT_WINDOW_SECONDS
        ]
        
        # 如果清空后为空，删除该 IP 记录
        if not ip_request_counts[ip]:
            del ip_request_counts[ip]
    
    return {
        'active_ips': len(ip_request_counts),
        'total_requests': sum(len(v) for v in ip_request_counts.values()),
        'window_seconds': RATE_LIMIT_WINDOW_SECONDS,
        'max_requests': RATE_LIMIT_MAX_REQUESTS
    }


# ========== 定期清理 ==========

def cleanup_expired_records():
    """
    清理所有过期的频率限制记录
    （建议定期调用，比如每分钟）
    """
    now = time.time()
    
    for ip in list(ip_request_counts.keys()):
        ip_request_counts[ip] = [
            t for t in ip_request_counts[ip]
            if now - t < RATE_LIMIT_WINDOW_SECONDS
        ]
        
        if not ip_request_counts[ip]:
            del ip_request_counts[ip]
    
    print(f"[频率限制] 已清理过期记录，当前活跃 IP 数: {len(ip_request_counts)}")


if __name__ == '__main__':
    # 测试频率限制
    print("测试 IP 频率限制...")
    
    test_ip = "127.0.0.1"
    
    # 模拟 15 次请求
    for i in range(15):
        allowed, error_msg = check_rate_limit(test_ip)
        count = get_request_count(test_ip)
        
        if allowed:
            print(f"  请求 {i+1}: ✅ 允许 (当前次数: {count})")
        else:
            print(f"  请求 {i+1}: ❌ 拒绝 - {error_msg}")
    
    # 查看统计
    stats = get_rate_limit_stats()
    print(f"\n统计信息: {stats}")
    
    # 清除限制
    clear_rate_limit(test_ip)
    print(f"\n清除限制后，请求次数: {get_request_count(test_ip)}")