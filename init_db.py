#!/usr/bin/env python3
"""
数据库初始化脚本
作者: 云舟
功能: 创建用户认证相关的数据库表
"""

import sqlite3
import os
from pathlib import Path
from datetime import datetime

# 数据库路径
BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / 'data'
DB_FILE = DATA_DIR / 'users.db'


def init_database():
    """初始化数据库和表结构"""
    
    # 确保 data 目录存在
    DATA_DIR.mkdir(exist_ok=True)
    
    # 连接数据库
    conn = sqlite3.connect(str(DB_FILE))
    cursor = conn.cursor()
    
    print(f"[数据库初始化] 开始创建表结构...")
    
    # 1. 创建 users 表
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username VARCHAR(20) UNIQUE NOT NULL,
            email VARCHAR(100) UNIQUE NOT NULL,
            password_hash VARCHAR(100) NOT NULL,
            role VARCHAR(10) DEFAULT 'user',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_login_at TIMESTAMP,
            login_failed_count INTEGER DEFAULT 0,
            locked_until TIMESTAMP
        )
    ''')
    print("  ✅ users 表创建成功")
    
    # 2. 创建 login_logs 表
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS login_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            username VARCHAR(20),
            ip_address VARCHAR(50),
            success BOOLEAN,
            reason VARCHAR(100),
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    ''')
    print("  ✅ login_logs 表创建成功")
    
    # 3. 创建 operation_logs 表
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS operation_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            operation VARCHAR(50) NOT NULL,
            details TEXT,
            ip_address VARCHAR(50),
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    ''')
    print("  ✅ operation_logs 表创建成功")
    
    # 4. 创建 jwt_blacklist 表（用于登出和并发登录控制）
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS jwt_blacklist (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            token_hash VARCHAR(100) UNIQUE NOT NULL,
            user_id INTEGER NOT NULL,
            reason VARCHAR(50),
            expires_at TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    ''')
    print("  ✅ jwt_blacklist 表创建成功")
    
    # 5. 创建 login_attempts 表（Phase 2: 登录失败追踪）
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS login_attempts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            username VARCHAR(20),
            ip_address VARCHAR(50),
            attempt_count INTEGER DEFAULT 0,
            locked_until TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    ''')
    print("  ✅ login_attempts 表创建成功")
    
    # 6. 创建 ip_rate_limit 表（Phase 2: IP 频率限制）
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS ip_rate_limit (
            ip_address VARCHAR(50) PRIMARY KEY,
            request_count INTEGER DEFAULT 0,
            first_request_time TIMESTAMP,
            last_request_time TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    print("  ✅ ip_rate_limit 表创建成功")
    
    # 7. 创建 security_events 表（Phase 3: 安全事件告警）
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS security_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_type TEXT NOT NULL,
            user_id INTEGER,
            ip_address TEXT,
            details TEXT,
            severity TEXT DEFAULT 'medium',
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    ''')
    print("  ✅ security_events 表创建成功")
    
    # 创建索引
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_users_username ON users(username)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_users_email ON users(email)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_login_logs_user_id ON login_logs(user_id)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_login_logs_timestamp ON login_logs(timestamp)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_operation_logs_user_id ON operation_logs(user_id)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_operation_logs_timestamp ON operation_logs(timestamp)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_jwt_blacklist_token_hash ON jwt_blacklist(token_hash)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_jwt_blacklist_expires_at ON jwt_blacklist(expires_at)')
    # Phase 2 索引
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_login_attempts_user_id ON login_attempts(user_id)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_login_attempts_ip_address ON login_attempts(ip_address)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_login_attempts_locked_until ON login_attempts(locked_until)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_ip_rate_limit_ip_address ON ip_rate_limit(ip_address)')
    print("  ✅ Phase 2 索引创建成功")
    
    # Phase 3 索引
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_security_events_event_type ON security_events(event_type)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_security_events_user_id ON security_events(user_id)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_security_events_timestamp ON security_events(timestamp)')
    print("  ✅ Phase 3 索引创建成功")
    
    # 提交事务
    conn.commit()
    conn.close()
    
    print(f"\n[数据库初始化] 完成！数据库文件: {DB_FILE}")
    return True


if __name__ == '__main__':
    init_database()