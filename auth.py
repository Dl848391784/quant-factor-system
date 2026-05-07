#!/usr/bin/env python3
"""
认证核心模块
作者: 云舟
功能: 提供密码加密、JWT 生成验证、用户管理等功能

依赖:
    - bcrypt: 密码加密
    - PyJWT: JWT 生成和验证
    - sqlite3: 用户数据存储
"""

import os
import sqlite3
import datetime
import hashlib
from pathlib import Path
from typing import Optional, Dict, Tuple

import bcrypt
import jwt
from dateutil import parser

# ========== Phase 3: 审计日志导入 ==========
from audit_logger import log_operation, log_security_event

# ========== 配置 ==========

# 数据库路径
BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / 'data'
DB_FILE = DATA_DIR / 'users.db'

# JWT 配置（从环境变量读取，如果没有则使用默认值）
JWT_SECRET_KEY = os.environ.get('JWT_SECRET_KEY', 'yunzhou_quant_secret_key_2026_04_17_change_in_production')
JWT_EXPIRATION = int(os.environ.get('JWT_EXPIRATION', 86400))  # 24小时
JWT_EXPIRATION_REMEMBER = int(os.environ.get('JWT_EXPIRATION_REMEMBER', 604800))  # 7天

# bcrypt 配置
BCRYPT_COST_FACTOR = int(os.environ.get('BCRYPT_COST_FACTOR', 12))


# ========== 密码加密 ==========

def hash_password(password: str) -> str:
    """
    使用 bcrypt 加密密码
    
    Args:
        password: 明文密码
        
    Returns:
        加密后的密码哈希（包含 salt）
    """
    # bcrypt 自动生成 salt 并包含在哈希中
    salt = bcrypt.gensalt(rounds=BCRYPT_COST_FACTOR)
    hashed = bcrypt.hashpw(password.encode('utf-8'), salt)
    return hashed.decode('utf-8')


def verify_password(password: str, password_hash: str) -> bool:
    """
    验证密码是否匹配
    
    Args:
        password: 明文密码
        password_hash: bcrypt 加密的密码哈希
        
    Returns:
        True 如果密码匹配，False 否则
    """
    try:
        return bcrypt.checkpw(password.encode('utf-8'), password_hash.encode('utf-8'))
    except Exception:
        return False


# ========== JWT 管理 ==========

def generate_token(user_id: int, remember: bool = False) -> str:
    """
    生成 JWT token
    
    Args:
        user_id: 用户 ID
        remember: 是否记住登录（延长过期时间）
        
    Returns:
        JWT token 字符串
    """
    # 计算过期时间
    expiration_seconds = JWT_EXPIRATION_REMEMBER if remember else JWT_EXPIRATION
    expires_at = datetime.datetime.utcnow() + datetime.timedelta(seconds=expiration_seconds)
    
    # 构建 payload
    payload = {
        'user_id': user_id,
        'exp': expires_at,
        'iat': datetime.datetime.utcnow(),
        'type': 'access'
    }
    
    # 生成 token
    token = jwt.encode(payload, JWT_SECRET_KEY, algorithm='HS256')
    # PyJWT 1.6.1 返回 bytes，需要转 str
    if isinstance(token, bytes):
        token = token.decode('utf-8')
    return token


def verify_token(token: str) -> Optional[Dict]:
    """
    验证 JWT token
    
    Args:
        token: JWT token 字符串
        
    Returns:
        如果验证成功，返回 payload dict
        如果验证失败，返回 None
    """
    try:
        # 验证 token
        payload = jwt.decode(token, JWT_SECRET_KEY, algorithms=['HS256'])
        
        # 检查是否在黑名单中
        if is_token_blacklisted(token):
            return None
        
        return payload
    except jwt.ExpiredSignatureError:
        # Token 已过期
        return None
    except jwt.InvalidTokenError:
        # Token 无效
        return None


def get_token_hash(token: str) -> str:
    """
    获取 token 的哈希值（用于黑名单查询）
    
    Args:
        token: JWT token 字符串
        
    Returns:
        Token 的 SHA256 哈希值
    """
    return hashlib.sha256(token.encode('utf-8')).hexdigest()


# ========== Token 黑名单 ==========

def add_token_to_blacklist(token: str, user_id: int, reason: str = 'logout') -> bool:
    """
    将 token 加入黑名单（用于登出和并发登录控制）
    
    Args:
        token: JWT token
        user_id: 用户 ID
        reason: 加入黑名单的原因
        
    Returns:
        True 如果成功加入，False 否则
    """
    try:
        conn = sqlite3.connect(str(DB_FILE))
        cursor = conn.cursor()
        
        # 获取 token 的过期时间
        payload = jwt.decode(token, JWT_SECRET_KEY, algorithms=['HS256'], options={'verify_exp': False})
        expires_at = datetime.datetime.fromtimestamp(payload['exp'])
        
        # 插入黑名单记录
        token_hash = get_token_hash(token)
        cursor.execute('''
            INSERT OR IGNORE INTO jwt_blacklist (token_hash, user_id, reason, expires_at)
            VALUES (?, ?, ?, ?)
        ''', (token_hash, user_id, reason, expires_at))
        
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        print(f"[黑名单] 添加失败: {e}")
        return False


def is_token_blacklisted(token: str) -> bool:
    """
    检查 token 是否在黑名单中
    
    Args:
        token: JWT token
        
    Returns:
        True 如果在黑名单中，False 否则
    """
    try:
        conn = sqlite3.connect(str(DB_FILE))
        cursor = conn.cursor()
        
        token_hash = get_token_hash(token)
        cursor.execute('''
            SELECT COUNT(*) FROM jwt_blacklist 
            WHERE token_hash = ? AND expires_at > ?
        ''', (token_hash, datetime.datetime.utcnow()))
        
        count = cursor.fetchone()[0]
        conn.close()
        
        return count > 0
    except Exception:
        return False


def cleanup_expired_tokens():
    """
    清理已过期的 token 黑名单记录
    """
    try:
        conn = sqlite3.connect(str(DB_FILE))
        cursor = conn.cursor()
        
        cursor.execute('DELETE FROM jwt_blacklist WHERE expires_at < ?', (datetime.datetime.utcnow(),))
        
        conn.commit()
        conn.close()
        print("[黑名单] 已清理过期 token")
    except Exception as e:
        print(f"[黑名单] 清理失败: {e}")


# ========== 用户管理 ==========

def create_user(username: str, password: str, email: str, role: str = 'user') -> Tuple[bool, str]:
    """
    创建新用户
    
    Args:
        username: 用户名
        password: 明文密码
        email: 邮箱
        role: 用户角色（'user' 或 'admin'）
        
    Returns:
        (成功与否, 消息)
    """
    try:
        # 验证输入
        if not username or len(username) < 3 or len(username) > 20:
            return False, '用户名长度必须在 3-20 个字符之间'
        
        if not password or len(password) < 8:
            return False, '密码长度必须至少 8 个字符'
        
        if not email or '@' not in email:
            return False, '邮箱格式不正确'
        
        # 加密密码
        password_hash = hash_password(password)
        
        # 插入数据库
        conn = sqlite3.connect(str(DB_FILE))
        cursor = conn.cursor()
        
        cursor.execute('''
            INSERT INTO users (username, email, password_hash, role)
            VALUES (?, ?, ?, ?)
        ''', (username, email, password_hash, role))
        
        conn.commit()
        conn.close()
        
        return True, f'用户 {username} 创建成功'
    except sqlite3.IntegrityError as e:
        if 'username' in str(e):
            return False, '用户名已存在'
        elif 'email' in str(e):
            return False, '邮箱已存在'
        else:
            return False, f'创建失败: {e}'
    except Exception as e:
        return False, f'创建失败: {e}'


def authenticate_user(username: str, password: str, ip_address: str = '') -> Tuple[Optional[int], Optional[str], str]:
    """
    用户登录验证
    
    Args:
        username: 用户名
        password: 明文密码
        ip_address: IP 地址（用于日志记录）
        
    Returns:
        (user_id, token, 消息)
        如果验证失败，user_id 和 token 为 None
    """
    try:
        conn = sqlite3.connect(str(DB_FILE))
        cursor = conn.cursor()
        
        # 查询用户
        cursor.execute('''
            SELECT id, password_hash, role, locked_until, login_failed_count
            FROM users WHERE username = ?
        ''', (username,))
        
        user = cursor.fetchone()
        
        if not user:
            conn.close()
            return None, None, '用户不存在'
        
        user_id, password_hash, role, locked_until, login_failed_count = user
        
        # 检查账户是否被锁定
        if locked_until and datetime.datetime.now() < parser.parse(locked_until):
            conn.close()
            return None, None, '账户已被锁定，请稍后再试'
        
        # 验证密码
        if verify_password(password, password_hash):
            # 登录成功
            # 更新登录时间
            cursor.execute('''
                UPDATE users 
                SET last_login_at = ?, login_failed_count = 0, locked_until = NULL
                WHERE id = ?
            ''', (datetime.datetime.now(), user_id))
            
            # 记录登录日志
            cursor.execute('''
                INSERT INTO login_logs (user_id, username, ip_address, success, reason)
                VALUES (?, ?, ?, ?, ?)
            ''', (user_id, username, ip_address, True, '登录成功'))
            
            # 生成 token
            token = generate_token(user_id)
            
            conn.commit()
            conn.close()
            
            # 记录登录成功操作日志
            log_operation(user_id, 'login_success', '登录成功', ip_address)
            
            return user_id, token, '登录成功'
        else:
            # 登录失败
            login_failed_count += 1
            
            # 如果失败次数超过 5 次，锁定账户 15 分钟
            if login_failed_count >= 5:
                locked_until = datetime.datetime.now() + datetime.timedelta(minutes=15)
                cursor.execute('''
                    UPDATE users 
                    SET login_failed_count = ?, locked_until = ?
                    WHERE id = ?
                ''', (login_failed_count, locked_until, user_id))
                
                # 记录登录日志（Phase 2: 增加 IP 地址）
                cursor.execute('''
                    INSERT INTO login_logs (user_id, username, ip_address, success, reason)
                    VALUES (?, ?, ?, ?, ?)
                ''', (user_id, username, ip_address, False, f'账户锁定（失败{login_failed_count}次）'))
                
                conn.commit()
                conn.close()
                
                # Phase 3: 记录账户锁定事件
                log_operation(user_id, 'login_failed', f'失败{login_failed_count}次锁定', ip_address)
                log_security_event('account_locked', user_id=user_id, ip_address=ip_address, 
                                   severity='high', details=f'连续登录失败{login_failed_count}次')
                
                return None, None, '密码错误次数过多，账户已锁定 15 分钟'
            else:
                # 更新失败次数
                cursor.execute('''
                    UPDATE users 
                    SET login_failed_count = ?
                    WHERE id = ?
                ''', (login_failed_count, user_id))
                
                # 记录登录日志（Phase 2: 增加 IP 地址）
                cursor.execute('''
                    INSERT INTO login_logs (user_id, username, ip_address, success, reason)
                    VALUES (?, ?, ?, ?, ?)
                ''', (user_id, username, ip_address, False, f'密码错误（第{login_failed_count}次）'))
                
                conn.commit()
                conn.close()
                
                # Phase 3: 记录登录失败操作日志
                log_operation(user_id, 'login_failed', f'密码错误第{login_failed_count}次', ip_address)
                
                return None, None, f'密码错误（剩余尝试次数: {5 - login_failed_count}）'
    except Exception as e:
        print(f"[登录验证] 错误: {e}")
        return None, None, f'登录失败: {e}'


def get_user_by_id(user_id: int) -> Optional[Dict]:
    """
    根据 ID 获取用户信息
    
    Args:
        user_id: 用户 ID
        
    Returns:
        用户信息 dict，如果不存在返回 None
    """
    try:
        conn = sqlite3.connect(str(DB_FILE))
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT id, username, email, role, created_at, last_login_at
            FROM users WHERE id = ?
        ''', (user_id,))
        
        user = cursor.fetchone()
        conn.close()
        
        if user:
            return {
                'id': user[0],
                'username': user[1],
                'email': user[2],
                'role': user[3],
                'created_at': user[4],
                'last_login_at': user[5]
            }
        else:
            return None
    except Exception as e:
        print(f"[获取用户] 错误: {e}")
        return None


def logout_user(token: str, user_id: int, ip_address: str = '') -> bool:
    """
    用户登出（将 token 加入黑名单）
    
    Args:
        token: JWT token
        user_id: 用户 ID
        ip_address: IP 地址（可选，用于日志记录）
        
    Returns:
        True 如果成功，False 否则
    """
    result = add_token_to_blacklist(token, user_id, reason='logout')
    
    # Phase 3: 记录登出操作日志
    if result:
        log_operation(user_id, 'logout', '用户登出', ip_address)
    
    return result


# ========== 辅助函数 ==========

def validate_password_strength(password: str) -> Tuple[bool, str]:
    """
    验证密码强度
    
    要求:
        - 长度 8-32 字符
        - 包含大写字母
        - 包含小写字母
        - 包含数字
    
    Args:
        password: 明文密码
        
    Returns:
        (是否符合要求, 描述信息)
    """
    if len(password) < 8:
        return False, '密码长度至少 8 个字符'
    
    if len(password) > 32:
        return False, '密码长度最多 32 个字符'
    
    has_upper = any(c.isupper() for c in password)
    has_lower = any(c.islower() for c in password)
    has_digit = any(c.isdigit() for c in password)
    
    if not has_upper:
        return False, '密码必须包含大写字母'
    
    if not has_lower:
        return False, '密码必须包含小写字母'
    
    if not has_digit:
        return False, '密码必须包含数字'
    
    return True, '密码强度符合要求'


if __name__ == '__main__':
    # 测试密码加密
    print("测试密码加密...")
    password = "TestPassword123"
    hashed = hash_password(password)
    print(f"  原密码: {password}")
    print(f"  哈希值: {hashed}")
    print(f"  验证: {verify_password(password, hashed)}")
    
    # 测试 JWT
    print("\n测试 JWT...")
    token = generate_token(1)
    print(f"  Token: {token}")
    payload = verify_token(token)
    print(f"  Payload: {payload}")
    
    # 测试用户创建
    print("\n测试用户创建...")
    success, msg = create_user('testuser', 'TestPassword123', 'test@example.com')
    print(f"  结果: {msg}")