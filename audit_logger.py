#!/usr/bin/env python3
"""
审计日志记录模块
作者: 云舟
功能: Phase 3 - 记录操作日志和安全事件

依赖:
    - sqlite3: 数据存储
    - datetime: 时间戳

数据库表:
    - operation_logs: 记录用户操作
    - security_events: 记录安全异常事件
"""

import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Optional

# ========== 配置 ==========

# 数据库路径
BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / 'data'
DB_FILE = DATA_DIR / 'users.db'


# ========== 操作日志记录 ==========

def log_operation(
    user_id: int,
    operation: str,
    details: Optional[str] = None,
    ip_address: Optional[str] = None
) -> bool:
    """
    记录用户操作日志
    
    Args:
        user_id: 用户 ID
        operation: 操作类型（如 'login_success', 'api_call', 'logout'）
        details: 操作详情（可选）
        ip_address: IP 地址（可选）
        
    Returns:
        True 如果记录成功，False 否则
    
    使用示例:
        # 登录成功
        log_operation(user_id, 'login_success', '登录成功', ip_address)
        
        # API 调用
        log_operation(user_id, 'api_call', 'GET /api/home', ip_address)
        
        # 登出
        log_operation(user_id, 'logout', '用户登出', ip_address)
    """
    try:
        conn = sqlite3.connect(str(DB_FILE))
        cursor = conn.cursor()
        
        cursor.execute('''
            INSERT INTO operation_logs (user_id, operation, details, ip_address, timestamp)
            VALUES (?, ?, ?, ?, ?)
        ''', (user_id, operation, details, ip_address, datetime.now().isoformat()))
        
        conn.commit()
        conn.close()
        
        return True
    except Exception as e:
        print(f"[操作日志] 记录失败: {e}")
        return False


# ========== 安全事件记录 ==========

def log_security_event(
    event_type: str,
    user_id: Optional[int] = None,
    ip_address: Optional[str] = None,
    details: Optional[str] = None,
    severity: str = 'medium'
) -> bool:
    """
    记录安全事件
    
    Args:
        event_type: 事件类型（如 'account_locked', 'ip_rate_limit_triggered'）
        user_id: 用户 ID（可选）
        ip_address: IP 地址（可选）
        details: 事件详情（可选）
        severity: 严重程度（'low', 'medium', 'high', 'critical'）
        
    Returns:
        True 如果记录成功，False 否则
    
    使用示例:
        # 账户锁定（高风险）
        log_security_event('account_locked', user_id=user_id, 
                          severity='high', details='连续登录失败5次')
        
        # IP 频率限制触发（中风险）
        log_security_event('ip_rate_limit_triggered', ip_address='127.0.0.1',
                          severity='medium', details='请求次数超过限制')
    """
    try:
        conn = sqlite3.connect(str(DB_FILE))
        cursor = conn.cursor()
        
        cursor.execute('''
            INSERT INTO security_events (event_type, user_id, ip_address, details, severity, timestamp)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (event_type, user_id, ip_address, details, severity, datetime.now().isoformat()))
        
        conn.commit()
        conn.close()
        
        return True
    except Exception as e:
        print(f"[安全事件] 记录失败: {e}")
        return False


# ========== 查询功能 ==========

def get_operation_logs(
    user_id: Optional[int] = None,
    operation: Optional[str] = None,
    limit: int = 50,
    offset: int = 0
) -> list:
    """
    查询操作日志
    
    Args:
        user_id: 用户 ID（可选，不指定则查询所有用户）
        operation: 操作类型（可选，不指定则查询所有操作）
        limit: 返回记录数量限制
        offset: 偏移量（用于分页）
        
    Returns:
        操作日志列表（字典格式）
    
    使用示例:
        # 查询某个用户的所有操作
        logs = get_operation_logs(user_id=1)
        
        # 查询所有登录成功的记录
        logs = get_operation_logs(operation='login_success')
    """
    try:
        conn = sqlite3.connect(str(DB_FILE))
        cursor = conn.cursor()
        
        # 构建查询条件
        conditions = []
        params = []
        
        if user_id:
            conditions.append('user_id = ?')
            params.append(user_id)
        
        if operation:
            conditions.append('operation = ?')
            params.append(operation)
        
        where_clause = 'WHERE ' + ' AND '.join(conditions) if conditions else ''
        
        # 执行查询
        cursor.execute(f'''
            SELECT id, user_id, operation, details, ip_address, timestamp
            FROM operation_logs
            {where_clause}
            ORDER BY timestamp DESC
            LIMIT ? OFFSET ?
        ''', params + [limit, offset])
        
        rows = cursor.fetchall()
        conn.close()
        
        # 转换为字典列表
        logs = []
        for row in rows:
            logs.append({
                'id': row[0],
                'user_id': row[1],
                'operation': row[2],
                'details': row[3],
                'ip_address': row[4],
                'timestamp': row[5]
            })
        
        return logs
    except Exception as e:
        print(f"[操作日志查询] 错误: {e}")
        return []


def get_login_history(
    user_id: Optional[int] = None,
    limit: int = 50,
    offset: int = 0
) -> list:
    """
    查询登录历史
    
    Args:
        user_id: 用户 ID（可选，不指定则查询所有用户）
        limit: 返回记录数量限制
        offset: 偏移量（用于分页）
        
    Returns:
        登录日志列表（字典格式）
    """
    try:
        conn = sqlite3.connect(str(DB_FILE))
        cursor = conn.cursor()
        
        where_clause = 'WHERE user_id = ?' if user_id else ''
        params = [user_id] if user_id else []
        
        cursor.execute(f'''
            SELECT id, user_id, username, ip_address, success, reason, timestamp
            FROM login_logs
            {where_clause}
            ORDER BY timestamp DESC
            LIMIT ? OFFSET ?
        ''', params + [limit, offset])
        
        rows = cursor.fetchall()
        conn.close()
        
        # 转换为字典列表
        logs = []
        for row in rows:
            logs.append({
                'id': row[0],
                'user_id': row[1],
                'username': row[2],
                'ip_address': row[3],
                'success': row[4],
                'reason': row[5],
                'timestamp': row[6]
            })
        
        return logs
    except Exception as e:
        print(f"[登录历史查询] 错误: {e}")
        return []


def get_security_events(
    event_type: Optional[str] = None,
    severity: Optional[str] = None,
    limit: int = 50,
    offset: int = 0
) -> list:
    """
    查询安全事件
    
    Args:
        event_type: 事件类型（可选）
        severity: 严重程度（可选）
        limit: 返回记录数量限制
        offset: 偏移量（用于分页）
        
    Returns:
        安全事件列表（字典格式）
    """
    try:
        conn = sqlite3.connect(str(DB_FILE))
        cursor = conn.cursor()
        
        # 构建查询条件
        conditions = []
        params = []
        
        if event_type:
            conditions.append('event_type = ?')
            params.append(event_type)
        
        if severity:
            conditions.append('severity = ?')
            params.append(severity)
        
        where_clause = 'WHERE ' + ' AND '.join(conditions) if conditions else ''
        
        # 执行查询
        cursor.execute(f'''
            SELECT id, event_type, user_id, ip_address, details, severity, timestamp
            FROM security_events
            {where_clause}
            ORDER BY timestamp DESC
            LIMIT ? OFFSET ?
        ''', params + [limit, offset])
        
        rows = cursor.fetchall()
        conn.close()
        
        # 转换为字典列表
        events = []
        for row in rows:
            events.append({
                'id': row[0],
                'event_type': row[1],
                'user_id': row[2],
                'ip_address': row[3],
                'details': row[4],
                'severity': row[5],
                'timestamp': row[6]
            })
        
        return events
    except Exception as e:
        print(f"[安全事件查询] 错误: {e}")
        return []


# ========== 统计功能 ==========

def get_operation_stats(user_id: Optional[int] = None) -> dict:
    """
    获取操作统计
    
    Args:
        user_id: 用户 ID（可选）
        
    Returns:
        统计数据字典
    """
    try:
        conn = sqlite3.connect(str(DB_FILE))
        cursor = conn.cursor()
        
        where_clause = 'WHERE user_id = ?' if user_id else ''
        params = [user_id] if user_id else []
        
        # 总操作次数
        cursor.execute(f'SELECT COUNT(*) FROM operation_logs {where_clause}', params)
        total_ops = cursor.fetchone()[0]
        
        # 操作类型分布
        cursor.execute(f'''
            SELECT operation, COUNT(*) as count
            FROM operation_logs
            {where_clause}
            GROUP BY operation
            ORDER BY count DESC
        ''', params)
        operation_dist = {row[0]: row[1] for row in cursor.fetchall()}
        
        conn.close()
        
        return {
            'total_operations': total_ops,
            'operation_distribution': operation_dist
        }
    except Exception as e:
        print(f"[操作统计] 错误: {e}")
        return {'total_operations': 0, 'operation_distribution': {}}


if __name__ == '__main__':
    print("审计日志模块已加载")
    print("可用函数:")
    print("  - log_operation(): 记录操作日志")
    print("  - log_security_event(): 记录安全事件")
    print("  - get_operation_logs(): 查询操作日志")
    print("  - get_login_history(): 查询登录历史")
    print("  - get_security_events(): 查询安全事件")
    print("  - get_operation_stats(): 获取操作统计")