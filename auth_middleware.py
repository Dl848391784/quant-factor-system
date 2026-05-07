#!/usr/bin/env python3
"""
认证中间件模块
作者: 云舟
功能: 提供 Flask 路由的认证装饰器和辅助函数

使用方式:
    from auth_middleware import require_auth
    
    @app.route('/api/protected')
    @require_auth
    def protected_route():
        user_id = g.user_id
        username = g.username
        ...
"""

import functools
from flask import request, jsonify, g, redirect, url_for
from auth import verify_token, get_user_by_id

# ========== Phase 3: 审计日志导入 ==========
from audit_logger import log_operation


def require_auth(f):
    """
    认证装饰器 - 用于保护需要认证的路
    
    验证流程:
        1. 从请求头或参数中提取 token
        2. 验证 token
        3. 提取用户信息并注入到 Flask 上下文
        4. 如果验证失败，返回 401 错误
    
    使用方式:
        @app.route('/api/protected')
        @require_auth
        def protected_route():
            user_id = g.user_id  # 当前登录用户 ID
            username = g.username  # 当前登录用户名
            return jsonify({'message': 'success'})
    
    返回:
        - 如果认证成功：继续执行原函数
        - 如果认证失败：返回 JSON 错误响应（API）或重定向到登录页（页面）
    """
    @functools.wraps(f)
    def decorated_function(*args, **kwargs):
        # 1. 提取 token（Cookie 优先，兼容 Header）
        token = None
        
        # 方式1：从 Cookie 提取（浏览器请求）
        token = request.cookies.get('auth_token')
        
        # 方式2：如果 Cookie 无 token，从 Authorization header 提取（API 工具）
        if not token:
            auth_header = request.headers.get('Authorization')
            if auth_header and auth_header.startswith('Bearer '):
                token = auth_header.split(' ')[1]
        
        # 方式3：从参数提取（向后兼容）
        if not token:
            token = request.args.get('token')
        
        # 如果没有 token，返回未认证错误
        if not token:
            # 判断是 API 请求还是页面请求
            if request.path.startswith('/api/'):
                return jsonify({
                    'success': False,
                    'error': '未认证',
                    'message': '请先登录'
                }), 401
            else:
                # 页面请求，重定向到登录页
                return redirect(url_for('login_page'))
        
        # 2. 验证 token
        payload = verify_token(token)
        
        if not payload:
            # Token 无效或已过期
            if request.path.startswith('/api/'):
                return jsonify({
                    'success': False,
                    'error': 'token无效',
                    'message': 'Token 已过期或无效，请重新登录'
                }), 401
            else:
                return redirect(url_for('login_page'))
        
        # 3. 提取用户信息
        user_id = payload.get('user_id')
        user_info = get_user_by_id(user_id)
        
        if not user_info:
            # 用户不存在
            if request.path.startswith('/api/'):
                return jsonify({
                    'success': False,
                    'error': '用户不存在',
                    'message': '用户账户已被删除'
                }), 401
            else:
                return redirect(url_for('login_page'))
        
        # 4. 注入到 Flask 上下文
        g.user_id = user_id
        g.username = user_info['username']
        g.user_role = user_info['role']
        g.user_email = user_info['email']
        g.token = token
        
        # Phase 3: 记录 API 调用操作日志（仅 API 请求）
        if request.path.startswith('/api/'):
            api_details = f"{request.method} {request.path}"
            log_operation(user_id, 'api_call', api_details, request.remote_addr)
        
        # 5. 执行原函数
        return f(*args, **kwargs)
    
    return decorated_function


def require_admin(f):
    """
    管理员权限装饰器 - 用于保护需要管理员权限的路
    
    验证流程:
        1. 先验证用户是否登录（require_auth）
        2. 再验证用户是否为管理员
    
    使用方式:
        @app.route('/api/admin/config')
        @require_admin
        def admin_config():
            return jsonify({'message': '管理员操作'})
    
    返回:
        - 如果认证成功且为管理员：继续执行原函数
        - 如果认证失败：返回 401 错误
        - 如果不是管理员：返回 403 错误
    """
    @functools.wraps(f)
    @require_auth
    def decorated_function(*args, **kwargs):
        # 检查用户角色
        if g.user_role != 'admin':
            if request.path.startswith('/api/'):
                return jsonify({
                    'success': False,
                    'error': '权限不足',
                    'message': '此操作需要管理员权限'
                }), 403
            else:
                return jsonify({
                    'success': False,
                    'error': '权限不足',
                    'message': '此页面需要管理员权限'
                }), 403
        
        return f(*args, **kwargs)
    
    return decorated_function


def optional_auth(f):
    """
    可选认证装饰器 - 用户可选择登录或不登录
    
    如果有 token 且有效，注入用户信息
    如果没有 token 或无效，不报错，继续执行
    
    使用方式:
        @app.route('/api/public-data')
        @optional_auth
        def public_data():
            if hasattr(g, 'user_id'):
                # 已登录用户，返回个性化数据
                return jsonify({'data': 'personalized'})
            else:
                # 未登录用户，返回公共数据
                return jsonify({'data': 'public'})
    """
    @functools.wraps(f)
    def decorated_function(*args, **kwargs):
        # 提取 token（可选）
        token = None
        
        auth_header = request.headers.get('Authorization')
        if auth_header and auth_header.startswith('Bearer '):
            token = auth_header.split(' ')[1]
        
        if not token:
            token = request.args.get('token')
        
        # 如果有 token，验证
        if token:
            payload = verify_token(token)
            if payload:
                user_id = payload.get('user_id')
                user_info = get_user_by_id(user_id)
                
                if user_info:
                    g.user_id = user_id
                    g.username = user_info['username']
                    g.user_role = user_info['role']
                    g.user_email = user_info['email']
                    g.token = token
        
        # 无论是否认证，都继续执行
        return f(*args, **kwargs)
    
    return decorated_function


def get_current_user_id():
    """
    获取当前登录用户的 ID
    
    Returns:
        用户 ID，如果未登录返回 None
    """
    return getattr(g, 'user_id', None)


def get_current_username():
    """
    获取当前登录用户的用户名
    
    Returns:
        用户名，如果未登录返回 None
    """
    return getattr(g, 'username', None)


def get_current_user_role():
    """
    获取当前登录用户的角色
    
    Returns:
        用户角色，如果未登录返回 None
    """
    return getattr(g, 'user_role', None)


def is_user_logged_in():
    """
    检查用户是否已登录
    
    Returns:
        True 如果已登录，False 否则
    """
    return hasattr(g, 'user_id') and g.user_id is not None


def is_user_admin():
    """
    检查用户是否为管理员
    
    Returns:
        True 如果是管理员，False 否则
    """
    return hasattr(g, 'user_role') and g.user_role == 'admin'


if __name__ == '__main__':
    print("认证中间件模块已加载")
    print("可用装饰器:")
    print("  - require_auth: 强制认证")
    print("  - require_admin: 管理员权限")
    print("  - optional_auth: 可选认证")
    print("可用辅助函数:")
    print("  - get_current_user_id()")
    print("  - get_current_username()")
    print("  - get_current_user_role()")
    print("  - is_user_logged_in()")
    print("  - is_user_admin()")