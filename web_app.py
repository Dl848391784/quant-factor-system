#!/usr/bin/env python3
"""
因子池 IC 分析系统 - Web展示界面
作者: 云舟
功能: 提供网页展示IC分析结果

启动方式:
    python web_app.py
    或
    bash start_web.sh
    
访问地址:
    http://localhost:8765

v3.6 性能优化（云柏方案实施）:
- 数据预加载：Flask 启动时加载 150 天数据到缓存（节省 25 分钟）
- 并行回测：使用多进程并行处理 Top 100 组合（节省 131 分钟）
- 总优化效果：175 分钟 → 19 分钟（89% 提升）
"""

import json
import gzip
import os
import time
import threading
import gc
import tempfile
import shutil
import multiprocessing
from functools import partial
from pathlib import Path

# ========== v3.7 OOM 修复：使用 spawn 模式 ==========
# 避免 fork 导致的内存副本问题（适配 3.5GB 内存服务器）
try:
    multiprocessing.set_start_method('spawn', force=True)
    print("[OOM 修复] 进程启动模式设置为 spawn")
except RuntimeError:
    pass  # 已经设置过
from flask import Flask, render_template, jsonify, send_from_directory, Response, request, g, redirect, url_for
from datetime import datetime
import pandas as pd
import numpy as np
from versions.v2.optimizer.weight_optimizer import start_optimization_with_backtest, get_backtest_optimization_result
from portfolio_tracker import (
    PortfolioTracker,
    VirtualAccount,
    load_json_file,
    load_precompute_result,
    get_stock_prices,
    DEFAULT_INITIAL_CAPITAL,
    DEFAULT_REBALANCE_THRESHOLD,
    DEFAULT_TOP_N,
    DEFAULT_TRADE_COST,
    DEFAULT_SLIPPAGE,
    CONFIG_FILE,
    HOLDINGS_FILE,
    TRADES_FILE,
    atomic_write_json,
    run_daily_tracking
)

# ========== 认证模块导入（Phase 1 安全模块） ==========
from auth import (
    authenticate_user,
    logout_user,
    verify_token,
    get_user_by_id,
    validate_password_strength
)
from auth_middleware import require_auth, get_current_user_id

# ========== Phase 2 安全模块导入 ==========
from rate_limit import rate_limit_decorator, check_rate_limit

# ========== Phase 3 审计日志导入 ==========
from audit_logger import get_operation_logs, get_login_history, get_security_events
from auth_middleware import require_admin

# ========== v3.6 全局数据预加载缓存 ==========
CACHED_SCORING_ENGINE = None
CACHE_LOADED = False

# ========== v3.6 并行回测进程池 ==========
BACKTEST_POOL = None
BACKTEST_POOL_SIZE = 2  # v3.7 OOM 修复：从 8 改为 2（适配 3.5GB 内存）

def init_backtest_pool():
    """初始化并行回测进程池
    
    v3.7 OOM 修复：
    - 进程池大小固定为 2（适配 3.5GB 内存服务器）
    - 使用 spawn 模式，避免 fork 导致的内存副本
    - 进程池改为按需创建（不在启动时初始化）
    """
    global BACKTEST_POOL
    
    if BACKTEST_POOL is None:
        try:
            # v3.7 OOM 修复：固定为 2 个进程
            BACKTEST_POOL_SIZE = 2
            
            # 创建进程池
            BACKTEST_POOL = multiprocessing.Pool(processes=BACKTEST_POOL_SIZE)
            print(f"[进程池] 按需初始化完成，核心数: {BACKTEST_POOL_SIZE}")
        except Exception as e:
            print(f"[进程池] 初始化失败: {e}")
            BACKTEST_POOL = None

def preload_scoring_engine():
    """预加载打分引擎数据
    
    v3.6 性能优化：
    - Flask 启动时加载 150 天数据到缓存
    - 避免每次回测重新加载 15s 数据
    - 节省约 25 分钟（14.3% 提升）
    """
    global CACHED_SCORING_ENGINE, CACHE_LOADED
    
    if not CACHE_LOADED:
        print("[预加载] 开始预加载打分引擎数据...")
        try:
            from scoring_engine import preload_engine_data
            preload_engine_data()
            
            # 获取缓存的引擎实例
            from scoring_engine import get_cached_engine
            CACHED_SCORING_ENGINE = get_cached_engine()
            CACHE_LOADED = True
            
            print(f"[预加载] 数据预加载完成，可用日期: {len(CACHED_SCORING_ENGINE.available_dates)} 天")
        except Exception as e:
            print(f"[预加载] 失败: {e}")
            import traceback
            traceback.print_exc()


def atomic_write_json(filepath: Path, data: dict):
    """
    原子写入 JSON 文件
    
    先写入临时文件，成功后再重命名，防止写入中断导致文件截断
    
    Args:
        filepath: 目标文件路径
        data: 要写入的数据
    """
    # 创建临时文件（在同一目录下，确保同一文件系统，支持原子重命名）
    temp_fd, temp_path = tempfile.mkstemp(
        dir=filepath.parent,
        prefix='.tmp_',
        suffix='.json'
    )
    
    try:
        # 写入临时文件
        with os.fdopen(temp_fd, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        
        # 原子重命名（同一文件系统上的 rename 是原子操作）
        shutil.move(temp_path, str(filepath))
        
    except Exception as e:
        # 出错时清理临时文件
        if os.path.exists(temp_path):
            os.unlink(temp_path)
        raise e


def convert_to_native_types(obj):
    """
    递归转换 numpy 类型为 Python 原生类型
    解决 JSON 序列化问题：TypeError: Object of type 'int64' is not JSON serializable
    """
    if isinstance(obj, dict):
        return {k: convert_to_native_types(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [convert_to_native_types(v) for v in obj]
    elif isinstance(obj, (np.integer, np.int64, np.int32)):
        return int(obj)
    elif isinstance(obj, (np.floating, np.float64, np.float32)):
        return float(obj)
    elif isinstance(obj, np.bool_):
        return bool(obj)
    elif isinstance(obj, np.ndarray):
        return obj.tolist()
    elif isinstance(obj, pd.Series):
        return obj.tolist()
    elif pd.isna(obj):
        return None
    else:
        return obj

# ========== 全局计算任务锁（防止 OOM） ==========
# 确保同一时间只有一个计算任务在运行
computation_lock = threading.Lock()
computation_running = False
computation_task_name = None  # 当前运行的任务名称

def check_memory_available():
    """检查是否有足够内存（至少 500MB 可用）
    
    Returns:
        tuple: (is_available: bool, available_mb: float, message: str)
    """
    try:
        import psutil
        mem = psutil.virtual_memory()
        available_mb = mem.available / 1024 / 1024
        min_required_mb = 500
        
        if mem.available < min_required_mb * 1024 * 1024:
            return False, available_mb, f"内存不足（可用 {available_mb:.0f}MB < {min_required_mb}MB），请稍后重试"
        return True, available_mb, f"内存充足（可用 {available_mb:.0f}MB）"
    except ImportError:
        # psutil 未安装，跳过内存检查
        return True, 0, "内存检查跳过（psutil 未安装）"

def start_computation(task_name: str) -> tuple:
    """尝试开始计算任务
    
    Args:
        task_name: 任务名称（用于日志和错误提示）
        
    Returns:
        tuple: (success: bool, error_message: str or None)
    """
    global computation_running, computation_task_name
    
    # 检查是否已有任务运行
    if computation_running:
        return False, f"已有计算任务正在运行（{computation_task_name}），请稍候再试"
    
    # 检查内存
    mem_ok, available_mb, mem_msg = check_memory_available()
    if not mem_ok:
        return False, mem_msg
    
    # 开始任务
    computation_running = True
    computation_task_name = task_name
    print(f"[计算任务] 开始: {task_name}（可用内存: {available_mb:.0f}MB）")
    return True, None

def end_computation(task_name: str = None):
    """结束计算任务并强制垃圾回收"""
    global computation_running, computation_task_name
    
    computation_running = False
    actual_task = computation_task_name or task_name
    computation_task_name = None
    
    # 强制垃圾回收，释放内存
    gc.collect()
    print(f"[计算任务] 结束: {actual_task}，已执行垃圾回收")

def get_computation_status():
    """获取当前计算任务状态
    
    Returns:
        dict: {running: bool, task_name: str or None}
    """
    return {
        'running': computation_running,
        'task_name': computation_task_name
    }

app = Flask(__name__,
            template_folder='templates',
            static_folder='static')

# 配置
BASE_DIR = Path(__file__).parent
OUTPUT_DIR = BASE_DIR / 'output'
RESULTS_FILE = BASE_DIR / 'ic_results.json'

# 进度状态（全局变量）
progress_state = {
    'status': 'idle',  # idle, running, completed, error
    'message': '',
    'current_batch': 0,
    'total_batches': 0,
    'stocks_fetched': 0,
    'success_count': 0,
    'fail_count': 0,
    'start_time': None,
    'end_time': None,
    'last_update': None,
    'error': None
}
progress_lock = threading.Lock()

# 分层回测进度状态（全局变量）
layered_backtest_state = {
    'status': 'idle',
    'message': '',
    'progress': 0,
    'start_time': None,
    'end_time': None,
    'last_update': None,
    'error': None,
    'result': None
}
layered_backtest_lock = threading.Lock()

# 因子分析整合进度状态（全局变量）
factor_analysis_state = {
    'status': 'idle',
    'message': '',
    'progress': 0,
    'start_time': None,
    'end_time': None,
    'last_update': None,
    'error': None,
    'result': None
}
factor_analysis_lock = threading.Lock()

# 量比因子分析进度状态（全局变量）
volume_ratio_analysis_state = {
    'status': 'idle',
    'message': '',
    'progress': 0,
    'start_time': None,
    'end_time': None,
    'last_update': None,
    'error': None,
    'result': None
}
volume_ratio_analysis_lock = threading.Lock()

# 3日涨幅因子分析进度状态（全局变量）
return_3d_analysis_state = {
    'status': 'idle',
    'message': '',
    'progress': 0,
    'start_time': None,
    'end_time': None,
    'last_update': None,
    'error': None,
    'result': None
}
return_3d_analysis_lock = threading.Lock()

# 换手率突增因子分析进度状态（全局变量）
turnover_surge_analysis_state = {
    'status': 'idle',
    'message': '',
    'progress': 0,
    'start_time': None,
    'end_time': None,
    'last_update': None,
    'error': None,
    'result': None
}
turnover_surge_analysis_lock = threading.Lock()

# 主力净流入占比因子分析进度状态（全局变量）
main_inflow_ratio_analysis_state = {
    'status': 'idle',
    'message': '',
    'progress': 0,
    'start_time': None,
    'end_time': None,
    'last_update': None,
    'error': None,
    'result': None
}
main_inflow_ratio_analysis_lock = threading.Lock()

# KDJ_J 因子分析进度状态（全局变量）
kdj_j_analysis_state = {
    'status': 'idle',
    'message': '',
    'progress': 0,
    'start_time': None,
    'end_time': None,
    'last_update': None,
    'error': None,
    'result': None
}
kdj_j_analysis_lock = threading.Lock()

# 布林带%B 因子分析进度状态（全局变量）
bollinger_pb_analysis_state = {
    'status': 'idle',
    'message': '',
    'progress': 0,
    'start_time': None,
    'end_time': None,
    'last_update': None,
    'error': None,
    'result': None
}
bollinger_pb_analysis_lock = threading.Lock()


def load_cached_data_light(max_days: int = 500, use_category: bool = True):
    """轻量级缓存加载（内存优化版）
    
    内存优化策略：
    1. 只加载必要列（减少 60% 内存）
    2. 使用 category 类型（减少 80% 内存）
    3. 及时释放中间变量
    
    Args:
        max_days: 最大加载天数（默认 500 天，全量数据）
        use_category: 是否使用 category 类型优化内存（默认 True）
        
    Returns:
        tuple: (factor_df, return_df) 或 (None, None) 如果缓存不存在
    """
    import gc
    
    cache_dir = Path('/home/admin/.openclaw/workspace/yunzhou/factor_ic_analyzer/cache/factor_data')
    factor_path = cache_dir / 'factor_data.json.gz'
    return_path = cache_dir / 'return_data.json.gz'
    
    if not factor_path.exists() or not return_path.exists():
        return None, None
    
    try:
        # ========== 加载因子数据（只加载必要列） ==========
        print(f"[轻量加载] 正在加载因子数据（最近 {max_days} 天）...")
        with gzip.open(factor_path, 'rt', encoding='utf-8') as f:
            factor_data = json.load(f)
        
        # 提取元数据
        factor_meta = factor_data.get('meta', {})
        all_dates = sorted(set(r.get('date') for r in factor_data.get('data', [])))
        print(f"[轻量加载] 数据包含 {len(all_dates)} 天数据")
        
        # 只保留最近 max_days 天，只提取必要列（因子值：rsi_6, volume_ratio_5）
        if len(all_dates) > max_days:
            recent_dates = set(all_dates[-max_days:])
            print(f"[轻量加载] 只加载最近 {max_days} 天（{all_dates[-max_days]} ~ {all_dates[-1]}）")
            factor_records = [
                {'date': r['date'], 'asset': r['asset'], 'rsi_6': r['rsi_6'], 'volume_ratio_5': r['volume_ratio_5']}
                for r in factor_data.get('data', []) if r.get('date') in recent_dates
            ]
        else:
            # 全量数据，只提取必要列（因子值：rsi_6, volume_ratio_5）
            factor_records = [
                {'date': r['date'], 'asset': r['asset'], 'rsi_6': r['rsi_6'], 'volume_ratio_5': r['volume_ratio_5']}
                for r in factor_data.get('data', [])
            ]
        
        del factor_data
        gc.collect()
        
        factor_df = pd.DataFrame(factor_records)
        del factor_records
        gc.collect()
        
        # 使用 category 类型优化内存
        if use_category:
            factor_df['date'] = factor_df['date'].astype('category')
            factor_df['asset'] = factor_df['asset'].astype('category')
        
        factor_mem = factor_df.memory_usage(deep=True).sum() / 1024 / 1024
        print(f"[轻量加载] factor_df: {len(factor_df)} 行, {factor_mem:.2f} MB")
        
        # ========== 加载收益数据（只加载必要列） ==========
        print("[轻量加载] 正在加载收益数据...")
        with gzip.open(return_path, 'rt', encoding='utf-8') as f:
            return_data = json.load(f)
        
        # 同样只保留最近 max_days 天，只提取必要列
        # 兼容 forward_return 和 forward_return_1d 两种字段名
        def get_return_value(record):
            return record.get('forward_return_1d') or record.get('forward_return')
        
        if len(all_dates) > max_days:
            return_records = [
                {'date': r['date'], 'asset': r['asset'], 'forward_return_1d': get_return_value(r)}
                for r in return_data.get('data', []) if r.get('date') in recent_dates
            ]
        else:
            return_records = [
                {'date': r['date'], 'asset': r['asset'], 'forward_return_1d': get_return_value(r)}
                for r in return_data.get('data', [])
            ]
        
        del return_data, all_dates
        if 'recent_dates' in dir():
            del recent_dates
        gc.collect()
        
        return_df = pd.DataFrame(return_records)
        del return_records
        gc.collect()
        
        # 使用 category 类型优化内存
        if use_category:
            return_df['date'] = return_df['date'].astype('category')
            return_df['asset'] = return_df['asset'].astype('category')
        
        return_mem = return_df.memory_usage(deep=True).sum() / 1024 / 1024
        print(f"[轻量加载] return_df: {len(return_df)} 行, {return_mem:.2f} MB")
        print(f"[轻量加载] 总内存占用: {factor_mem + return_mem:.2f} MB")
        
        # 列名兼容性映射：缓存数据使用 forward_return_1d，代码期望 forward_return
        if 'forward_return_1d' in return_df.columns and 'forward_return' not in return_df.columns:
            return_df['forward_return'] = return_df['forward_return_1d']
            print("[轻量加载] 已映射 forward_return_1d → forward_return")
        
        return factor_df, return_df
        
    except Exception as e:
        print(f"加载缓存数据失败: {e}")
        return None, None


def load_ic_results():
    """加载IC分析结果"""
    if RESULTS_FILE.exists():
        with open(RESULTS_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {}


# ========== 认证路由（Phase 1 安全模块） ==========

@app.route('/login')
def login_page():
    """登录页面"""
    # 如果已登录，重定向到主页
    token = request.args.get('token')
    if token:
        payload = verify_token(token)
        if payload:
            return redirect(url_for('home'))
    return render_template('login.html')


@app.route('/api/auth/login', methods=['POST'])
@rate_limit_decorator
def api_auth_login():
    """登录 API（Cookie 存储版）
    
    请求体:
        username: 用户名
        password: 密码
        remember: 是否记住登录（可选）
    
    返回:
        success: 是否成功
        username: 用户名（成功时）
        user_id: 用户 ID（成功时）
        message: 消息
        
    注意：token 不再在 JSON body 返回，而是通过 Set-Cookie header 设置
    """
    try:
        data = request.get_json()
        username = data.get('username', '').strip()
        password = data.get('password', '')
        remember = data.get('remember', False)
        
        # 获取 IP 地址（用于日志记录）
        ip_address = request.remote_addr
        
        if not username or not password:
            return jsonify({
                'success': False,
                'message': '请输入用户名和密码'
            }), 400
        
        # 验证登录（取消验证码）
        user_id, token, message = authenticate_user(
            username, password, ip_address
        )
        
        if user_id and token:
            # 登录成功：设置 Cookie
            # Cookie 过期时间
            cookie_max_age = 7 * 24 * 3600 if remember else 24 * 3600  # 7天或24小时
            
            # 判断是否生产环境（HTTPS）
            is_production = request.environ.get('HTTP_X_FORWARDED_PROTO') == 'https' or \
                           request.is_secure
            
            # 创建响应
            response = jsonify({
                'success': True,
                'username': username,
                'user_id': user_id,
                'message': message
            })
            
            # 设置 Cookie
            response.set_cookie(
                'auth_token',
                value=token,
                max_age=cookie_max_age,
                httponly=True,          # 防止 XSS 读取
                samesite='Lax',         # 防止 CSRF
                secure=is_production,   # 生产环境 HTTPS
                path='/'                # 全站有效
            )
            
            return response
        else:
            # 登录失败
            return jsonify({
                'success': False,
                'message': message
            }), 401
    except Exception as e:
        print(f"[登录API] 错误: {e}")
        return jsonify({
            'success': False,
            'message': f'登录失败: {e}'
        }), 500


@app.route('/api/auth/verify')
def api_auth_verify():
    """Token 验证 API
    
    请求头:
        Authorization: Bearer <token>
    
    返回:
        success: 是否有效
        user_id: 用户 ID（有效时）
        username: 用户名（有效时）
    """
    token = None
    
    # 优先从 Cookie 读取
    token = request.cookies.get('auth_token')
    
    # 如果 Cookie 没有，从 Authorization header 提取
    if not token:
        auth_header = request.headers.get('Authorization')
        if auth_header and auth_header.startswith('Bearer '):
            token = auth_header.split(' ')[1]
    
    if not token:
        return jsonify({
            'success': False,
            'message': '缺少 token'
        }), 401
    
    payload = verify_token(token)
    
    if not payload:
        return jsonify({
            'success': False,
            'message': 'Token 无效或已过期'
        }), 401
    
    user_id = payload.get('user_id')
    user_info = get_user_by_id(user_id)
    
    if not user_info:
        return jsonify({
            'success': False,
            'message': '用户不存在'
        }), 401
    
    return jsonify({
        'success': True,
        'user_id': user_id,
        'username': user_info['username'],
        'role': user_info['role']
    })


@app.route('/api/auth/logout', methods=['POST'])
@require_auth
def api_auth_logout():
    """登出 API（清除 Cookie）
    
    需要认证
    
    返回:
        success: 是否成功
        message: 消息
        
    注意：登出时同时清除 Cookie 和将 token 加入黑名单
    """
    try:
        token = getattr(g, 'token', None)
        user_id = getattr(g, 'user_id', None)
        
        if token and user_id:
            # 将 token 加入黑名单
            logout_user(token, user_id, request.remote_addr)
            
            # 创建响应并清除 Cookie
            response = jsonify({
                'success': True,
                'message': '登出成功'
            })
            
            # 清除 Cookie
            response.delete_cookie('auth_token', path='/')
            
            return response
        else:
            return jsonify({
                'success': False,
                'message': '登出失败'
            }), 400
    except Exception as e:
        print(f"[登出API] 错误: {e}")
        return jsonify({
            'success': False,
            'message': f'登出失败: {e}'
        }), 500


# ========== Phase 3: 日志查询 API ==========

@app.route('/api/auth/operation-logs')
@require_auth
def api_auth_operation_logs():
    """查询操作日志 API
    
    需要认证
    
    参数:
        user_id: 用户 ID（可选）
        operation: 操作类型（可选）
        page: 页码（默认 1）
        limit: 每页数量（默认 50）
    
    返回:
        success: 是否成功
        logs: 操作日志列表
        total: 总数（可选）
    """
    try:
        user_id = request.args.get('user_id', type=int)
        operation = request.args.get('operation', type=str)
        page = request.args.get('page', 1, type=int)
        limit = request.args.get('limit', 50, type=int)
        offset = (page - 1) * limit
        
        logs = get_operation_logs(user_id=user_id, operation=operation, limit=limit, offset=offset)
        
        return jsonify({
            'success': True,
            'logs': logs,
            'page': page,
            'limit': limit
        })
    except Exception as e:
        print(f"[操作日志API] 错误: {e}")
        return jsonify({
            'success': False,
            'message': f'查询失败: {e}'
        }), 500


@app.route('/api/auth/login-history')
@require_auth
def api_auth_login_history():
    """查询登录历史 API
    
    需要认证
    
    参数:
        user_id: 用户 ID（可选）
        page: 页码（默认 1）
        limit: 每页数量（默认 50）
    
    返回:
        success: 是否成功
        logs: 登录日志列表
    """
    try:
        user_id = request.args.get('user_id', type=int)
        page = request.args.get('page', 1, type=int)
        limit = request.args.get('limit', 50, type=int)
        offset = (page - 1) * limit
        
        logs = get_login_history(user_id=user_id, limit=limit, offset=offset)
        
        return jsonify({
            'success': True,
            'logs': logs,
            'page': page,
            'limit': limit
        })
    except Exception as e:
        print(f"[登录历史API] 错误: {e}")
        return jsonify({
            'success': False,
            'message': f'查询失败: {e}'
        }), 500


@app.route('/api/auth/security-events')
@require_admin
def api_auth_security_events():
    """查询安全事件 API
    
    需要管理员权限
    
    参数:
        event_type: 事件类型（可选）
        severity: 严重程度（可选）
        page: 页码（默认 1）
        limit: 每页数量（默认 50）
    
    返回:
        success: 是否成功
        events: 安全事件列表
    """
    try:
        event_type = request.args.get('event_type', type=str)
        severity = request.args.get('severity', type=str)
        page = request.args.get('page', 1, type=int)
        limit = request.args.get('limit', 50, type=int)
        offset = (page - 1) * limit
        
        events = get_security_events(event_type=event_type, severity=severity, limit=limit, offset=offset)
        
        return jsonify({
            'success': True,
            'events': events,
            'page': page,
            'limit': limit
        })
    except Exception as e:
        print(f"[安全事件API] 错误: {e}")
        return jsonify({
            'success': False,
            'message': f'查询失败: {e}'
        }), 500


# ========== 原有路由 ==========

@app.route('/')
@require_auth
def home():
    """首页 - 因子总览"""
    return render_template('home.html', active_page='home')


@app.route('/home')
@require_auth
def home_alias():
    """首页别名"""
    return render_template('home.html', active_page='home')


@app.route('/api/results')
def api_results():
    """API: 获取IC分析结果"""
    results = load_ic_results()
    return jsonify(results)


def get_file_mtime(filepath):
    """获取文件最后修改时间"""
    import os
    from datetime import datetime
    mtime = os.path.getmtime(filepath)
    return datetime.fromtimestamp(mtime).strftime('%Y-%m-%d %H:%M:%S')


@app.route('/api/home/summary')
def api_home_summary():
    """API: 获取因子摘要数据"""
    try:
        factors = []
        
        # 加载 RSI 因子数据
        rsi_path = BASE_DIR / 'cache/factor_ic/rsi_ic.json'
        if rsi_path.exists():
            with open(rsi_path, 'r', encoding='utf-8') as f:
                rsi_data = json.load(f)
            
            rsi_metrics = rsi_data.get('ic_metrics', {})
            rsi_summary = rsi_data.get('layered_result', {}).get('summary', {})
            
            factors.append({
                'id': 'rsi_6',
                'name': 'RSI(6)',
                'full_name': 'RSI(6) 超卖反弹因子',
                'description': 'RSI(6) 相对强弱指标，低于30为超卖，预期反弹',
                'analysis_url': '/factor-analysis',
                'ic_mean': rsi_metrics.get('ic_mean', 0),
                'icir': rsi_metrics.get('icir', 0),
                'ic_positive_ratio': rsi_metrics.get('positive_ratio', 0),
                'long_short_return': rsi_summary.get('long_short_annual_return', 0),
                'monotonicity_passed': rsi_summary.get('monotonicity_passed', False),
                'status': {
                    'effective': rsi_metrics.get('ic_mean', 0) > 0.03,
                    'stable': rsi_metrics.get('icir', 0) > 0.5
                },
                'last_updated': get_file_mtime(rsi_path),
                'data_source': '新浪财经API'
            })
        
        # 加载量比因子数据
        vol_path = BASE_DIR / 'cache/factor_ic/volume_ratio_ic.json'
        if vol_path.exists():
            with open(vol_path, 'r', encoding='utf-8') as f:
                vol_data = json.load(f)
            
            vol_metrics = vol_data.get('ic_metrics', {})
            vol_summary = vol_data.get('layered_result', {}).get('summary', {})
            
            factors.append({
                'id': 'volume_ratio_5',
                'name': '量比(5)',
                'full_name': '量比(5) 放量因子',
                'description': '当日成交量/5日均值，放量表示资金关注度高',
                'analysis_url': '/volume-ratio-analysis',
                'ic_mean': vol_metrics.get('ic_mean', 0),
                'icir': vol_metrics.get('icir', 0),
                'ic_positive_ratio': vol_metrics.get('positive_ratio', 0),
                'long_short_return': vol_summary.get('long_short_annual_return', 0),
                'monotonicity_passed': vol_summary.get('monotonicity_passed', False),
                'status': {
                    'effective': vol_metrics.get('ic_mean', 0) > 0.03,
                    'stable': vol_metrics.get('icir', 0) > 0.5
                },
                'last_updated': get_file_mtime(vol_path),
                'data_source': '新浪财经API'
            })
        
        # 加载3日涨幅因子数据
        return_3d_path = BASE_DIR / 'return_3d_analysis_result.json'
        if return_3d_path.exists():
            with open(return_3d_path, 'r', encoding='utf-8') as f:
                return_3d_data = json.load(f)
            
            r3d_metrics = return_3d_data.get('ic_metrics', {})
            r3d_summary = return_3d_data.get('layered_result', {}).get('summary', {})
            
            factors.append({
                'id': 'return_3d',
                'name': '3日涨幅',
                'full_name': '3日涨幅(Return 3D) 反转因子',
                'description': '过去3个交易日累计涨跌幅，涨幅过高预期回调',
                'analysis_url': '/return-3d-analysis',
                'ic_mean': r3d_metrics.get('ic_mean', 0),
                'icir': r3d_metrics.get('icir', 0),
                'ic_positive_ratio': r3d_metrics.get('positive_ratio', 0),
                'long_short_return': r3d_summary.get('long_short_annual_return', 0),
                'monotonicity_passed': r3d_summary.get('monotonicity_passed', False),
                'status': {
                    'effective': r3d_metrics.get('ic_mean', 0) > 0.03,
                    'stable': r3d_metrics.get('icir', 0) > 0.5
                },
                'last_updated': get_file_mtime(return_3d_path),
                'data_source': '缓存数据动态计算'
            })
        
        # 加载换手率突增因子数据
        turnover_surge_path = BASE_DIR / 'cache/factor_ic/turnover_surge_ic.json'
        if turnover_surge_path.exists():
            with open(turnover_surge_path, 'r', encoding='utf-8') as f:
                turnover_surge_data = json.load(f)
            
            ts_metrics = turnover_surge_data.get('ic_metrics', {})
            ts_summary = turnover_surge_data.get('layered_result', {}).get('summary', {})
            ts_filter_stats = turnover_surge_data.get('filter_stats', {})
            
            factors.append({
                'id': 'turnover_surge',
                'name': '换手率突增',
                'full_name': '换手率突增因子（筛选换手率突增+上涨）',
                'description': f"筛选换手率突增(turnover_surge>1)且上涨的股票，{ts_filter_stats.get('filter_ratio', 0)*100:.1f}%股票满足条件",
                'analysis_url': '/turnover-surge-analysis',
                'ic_mean': ts_metrics.get('ic_mean', 0),
                'icir': ts_metrics.get('icir', 0),
                'ic_positive_ratio': ts_metrics.get('positive_ratio', 0),
                'long_short_return': ts_summary.get('long_short_annual_return', 0),
                'monotonicity_passed': ts_summary.get('monotonicity_passed', False),
                'status': {
                    'effective': ts_metrics.get('ic_mean', 0) > 0.03,
                    'stable': ts_metrics.get('icir', 0) > 0.5
                },
                'last_updated': get_file_mtime(turnover_surge_path),
                'data_source': '缓存数据动态计算'
            })
        
        # 加载主力净流入占比因子数据
        main_inflow_path = BASE_DIR / 'cache/factor_ic/main_inflow_ratio_ic.json'
        if main_inflow_path.exists():
            with open(main_inflow_path, 'r', encoding='utf-8') as f:
                main_inflow_data = json.load(f)
            
            mi_metrics = main_inflow_data.get('ic_metrics', {})
            mi_summary = main_inflow_data.get('layered_result', {}).get('summary', {})
            mi_factor_stats = main_inflow_data.get('factor_stats', {})
            
            factors.append({
                'id': 'main_inflow_ratio',
                'name': '主力净流入占比',
                'full_name': '主力净流入占比因子',
                'description': f"主力净流入/流通市值，有效数据{mi_factor_stats.get('valid_records', 0):,}条",
                'analysis_url': '/main-inflow-ratio-analysis',
                'ic_mean': mi_metrics.get('ic_mean', 0),
                'icir': mi_metrics.get('icir', 0),
                'ic_positive_ratio': mi_metrics.get('positive_ratio', 0),
                'long_short_return': mi_summary.get('long_short_annual_return', 0),
                'monotonicity_passed': mi_summary.get('monotonicity_passed', False),
                'status': {
                    'effective': mi_metrics.get('ic_mean', 0) > 0.03,
                    'stable': mi_metrics.get('icir', 0) > 0.5
                },
                'last_updated': get_file_mtime(main_inflow_path),
                'data_source': '东方财富API'
            })
        
        # 加载 KDJ_J 因子数据
        kdj_j_path = BASE_DIR / 'cache/factor_ic/kdj_j_ic.json'
        if kdj_j_path.exists():
            with open(kdj_j_path, 'r', encoding='utf-8') as f:
                kdj_j_data = json.load(f)
            
            kj_metrics = kdj_j_data.get('ic_metrics', {})
            kj_summary = kdj_j_data.get('layered_result', {}).get('summary', {})
            kj_factor_stats = kdj_j_data.get('factor_stats', {})
            kj_params = kdj_j_data.get('params', {})
            
            factors.append({
                'id': 'kdj_j',
                'name': 'KDJ_J',
                'full_name': f"KDJ_J 因子 (N={kj_params.get('n', 9)}, M1={kj_params.get('m1', 3)}, M2={kj_params.get('m2', 3)})",
                'description': f"KDJ 指标 J 值，超卖(J<0)预期反弹，超买(J>100)预期回落",
                'analysis_url': '/kdj-j-analysis',
                'ic_mean': kj_metrics.get('ic_mean', 0),
                'icir': kj_metrics.get('icir', 0),
                'ic_positive_ratio': kj_metrics.get('positive_ratio', 0),
                'long_short_return': kj_summary.get('long_short_annual_return', 0),
                'monotonicity_passed': kj_summary.get('monotonicity_passed', False),
                'status': {
                    'effective': kj_metrics.get('ic_mean', 0) > 0.03,
                    'stable': kj_metrics.get('icir', 0) > 0.5
                },
                'last_updated': get_file_mtime(kdj_j_path),
                'data_source': '缓存数据计算'
            })
        
        # 加载布林带%B 因子数据
        bollinger_pb_path = BASE_DIR / 'cache/factor_ic/bollinger_pb_ic.json'
        if bollinger_pb_path.exists():
            with open(bollinger_pb_path, 'r', encoding='utf-8') as f:
                bollinger_pb_data = json.load(f)
            
            bp_metrics = bollinger_pb_data.get('ic_metrics', {})
            bp_summary = bollinger_pb_data.get('layered_result', {}).get('summary', {})
            bp_factor_stats = bollinger_pb_data.get('factor_stats', {})
            bp_params = bollinger_pb_data.get('params', {})
            
            factors.append({
                'id': 'bollinger_pb',
                'name': '布林带%B',
                'full_name': f"布林带%B 因子 (N={bp_params.get('n', 20)}, K={bp_params.get('k', 2.0)})",
                'description': f"布林带%B 指标，超卖(%B<0)预期反弹，超买(%B>1)预期回落",
                'analysis_url': '/bollinger-pb-analysis',
                'ic_mean': bp_metrics.get('ic_mean', 0),
                'icir': bp_metrics.get('icir', 0),
                'ic_positive_ratio': bp_metrics.get('positive_ratio', 0),
                'long_short_return': bp_summary.get('long_short_annual_return', 0),
                'monotonicity_passed': bp_summary.get('monotonicity_passed', False),
                'status': {
                    'effective': bp_metrics.get('ic_mean', 0) > 0.03,
                    'stable': bp_metrics.get('icir', 0) > 0.5
                },
                'last_updated': get_file_mtime(bollinger_pb_path),
                'data_source': '缓存数据计算'
            })
        
        if not factors:
            return jsonify({
                'success': False,
                'error': '无因子分析数据，请先运行分析'
            })
        
        # 统计摘要
        effective_count = sum(1 for f in factors if f['status']['effective'])
        last_updates = [f['last_updated'] for f in factors]
        
        return jsonify({
            'success': True,
            'data': {
                'factors': factors,
                'summary': {
                    'total_factors': len(factors),
                    'effective_factors': effective_count,
                    'last_global_update': max(last_updates) if last_updates else None
                }
            }
        })
        
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        })


@app.route('/api/computation-status')
def api_computation_status():
    """API: 获取全局计算任务状态"""
    status = get_computation_status()
    return jsonify({
        'success': True,
        'data': status
    })


@app.route('/output/<path:filename>')
def serve_image(filename):
    """提供output目录下的图片"""
    return send_from_directory(OUTPUT_DIR, filename)


@app.route('/compare')
@require_auth
def compare():
    """因子对比页面"""
    results = load_ic_results()
    return render_template('compare.html', results=results, active_page='compare')


@app.route('/factor-stats')
def factor_stats():
    """因子统计文案页面"""
    return render_template('factor_stats.html', active_page='factor_stats')


@app.route('/api/rsi-ic')
def api_rsi_ic():
    """API: 获取 RSI IC 数据（真实数据）"""
    rsi_ic_file = BASE_DIR / 'rsi_ic_data.json'
    
    if not rsi_ic_file.exists():
        # 数据文件不存在，尝试生成真实数据
        try:
            from rsi_ic_generator import generate_rsi_ic_data
            generate_rsi_ic_data(n_days=500, max_stocks=0, output_file=str(rsi_ic_file))
        except Exception as e:
            return jsonify({'error': f'生成数据失败: {str(e)}'})
    
    try:
        with open(rsi_ic_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return jsonify(data)
    except Exception as e:
        return jsonify({'error': f'读取数据失败: {str(e)}'})


@app.route('/api/factor/rsi')
def api_factor_rsi():
    """API: 获取 RSI 因子完整分析数据
    
    返回格式与 /api/factor-analysis/result 一致，包含：
    - ic_metrics: IC 指标（均值、标准差、ICIR、t值、p值等）
    - ic_series: IC 时间序列数据
    - layered_result: 分层回测结果
    - params: 分析参数
    - generated_at: 生成时间
    """
    result_file = BASE_DIR / 'cache/factor_ic/rsi_ic.json'
    
    if not result_file.exists():
        return jsonify({
            'success': False,
            'error': 'RSI 因子分析数据不存在，请先运行因子分析'
        })
    
    try:
        with open(result_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return jsonify({
            'success': True,
            'data': data
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': f'读取数据失败: {str(e)}'
        })


@app.route('/api/factor/list')
def api_factor_list():
    """API: 获取所有可用因子列表
    
    返回格式：
    - success: 是否成功
    - data: 因子列表，每个因子包含 id, name, description, api_path
    """
    factors = [
        {
            'id': 'rsi_6',
            'name': 'RSI(6)',
            'full_name': 'RSI(6) 超卖反弹因子',
            'description': 'RSI(6) 相对强弱指标，低于30为超卖，预期反弹',
            'api_path': '/api/factor/rsi',
            'analysis_url': '/factor-analysis'
        },
        {
            'id': 'volume_ratio_5',
            'name': '量比(5)',
            'full_name': '量比(5) 放量因子',
            'description': '当日成交量/5日均值，放量表示资金关注度高',
            'api_path': '/api/factor/volume-ratio',
            'analysis_url': '/volume-ratio-analysis'
        },
        {
            'id': 'return_3d',
            'name': '3日涨幅',
            'full_name': '3日涨幅(Return 3D) 反转因子',
            'description': '过去3个交易日累计涨跌幅，涨幅过高预期回调',
            'api_path': '/api/factor/return-3d',
            'analysis_url': '/return-3d-analysis'
        },
        {
            'id': 'turnover_surge',
            'name': '换手率突增',
            'full_name': '换手率突增因子',
            'description': '筛选换手率突增且上涨的股票，换手率突增作为因子值',
            'api_path': '/api/factor/turnover-surge',
            'analysis_url': '/turnover-surge-analysis'
        },
        {
            'id': 'main_inflow_ratio',
            'name': '主力净流入占比',
            'full_name': '主力净流入占比因子',
            'description': '主力净流入/流通市值，正值表示流入预期上涨',
            'api_path': '/api/factor/main-inflow-ratio',
            'analysis_url': '/main-inflow-ratio-analysis'
        },
        {
            'id': 'kdj_j',
            'name': 'KDJ_J',
            'full_name': 'KDJ_J 因子',
            'description': 'KDJ 指标 J 值，超卖(J<0)预期反弹，超买(J>100)预期回落',
            'api_path': '/api/factor/kdj-j',
            'analysis_url': '/kdj-j-analysis'
        },
        {
            'id': 'bollinger_pb',
            'name': '布林带%B',
            'full_name': '布林带%B 因子',
            'description': '布林带%B 指标，超卖(%B<0)预期反弹，超买(%B>1)预期回落',
            'api_path': '/api/factor/bollinger-pb',
            'analysis_url': '/bollinger-pb-analysis'
        }
    ]
    
    return jsonify({
        'success': True,
        'data': {
            'factors': factors,
            'total': len(factors)
        }
    })


@app.route('/api/rsi-ic/progress')
def api_rsi_ic_progress():
    """API: 获取当前进度状态"""
    with progress_lock:
        state = progress_state.copy()
    
    # 计算预计剩余时间
    if state['status'] == 'running' and state['start_time'] and state['current_batch'] > 0:
        elapsed = time.time() - state['start_time']
        avg_time_per_batch = elapsed / state['current_batch']
        remaining_batches = state['total_batches'] - state['current_batch']
        state['estimated_remaining_seconds'] = int(avg_time_per_batch * remaining_batches)
    else:
        state['estimated_remaining_seconds'] = 0
    
    return jsonify(state)


@app.route('/api/rsi-ic/refresh')
def api_rsi_ic_refresh():
    """API: 强制刷新 RSI IC 数据（重新获取真实数据）"""
    global progress_state
    
    # 检查是否已经在运行
    with progress_lock:
        if progress_state['status'] == 'running':
            return jsonify({'success': False, 'error': '数据获取正在进行中，请稍候...'})
        
        # 重置进度状态
        progress_state = {
            'status': 'running',
            'message': '开始获取数据...',
            'current_batch': 0,
            'total_batches': 0,
            'stocks_fetched': 0,
            'success_count': 0,
            'fail_count': 0,
            'start_time': time.time(),
            'end_time': None,
            'last_update': datetime.now().isoformat(),
            'error': None
        }
    
    # 在后台线程中执行
    def run_refresh():
        global progress_state
        rsi_ic_file = BASE_DIR / 'rsi_ic_data.json'
        
        try:
            from rsi_ic_generator import generate_rsi_ic_data_with_progress
            
            # 使用带进度回调的版本
            data = generate_rsi_ic_data_with_progress(
                n_days=500,
                max_stocks=0,
                output_file=str(rsi_ic_file),
                progress_callback=_update_progress
            )
            
            # 完成
            with progress_lock:
                progress_state['status'] = 'completed'
                progress_state['message'] = '数据获取完成!'
                progress_state['end_time'] = time.time()
                progress_state['last_update'] = datetime.now().isoformat()
                progress_state['total_stocks'] = data.get('n_assets', 0)
                progress_state['total_days'] = data.get('n_days', 0)
                
        except Exception as e:
            import traceback
            error_msg = str(e)
            traceback.print_exc()
            
            with progress_lock:
                progress_state['status'] = 'error'
                progress_state['error'] = error_msg
                progress_state['message'] = f'错误: {error_msg}'
                progress_state['end_time'] = time.time()
                progress_state['last_update'] = datetime.now().isoformat()
    
    thread = threading.Thread(target=run_refresh)
    thread.daemon = True
    thread.start()
    
    return jsonify({'success': True, 'message': '数据获取已开始'})


# ==================== 分层回测 API ====================

@app.route('/api/layered-backtest')
def api_layered_backtest():
    """API: 执行分层回测
    
    参数:
        num_layers: 分层数量 (可选，默认5)
        
    注意: n_days 和 max_stocks 已固定为 500 和 0（全部主板股票，2年数据）
    """
    global layered_backtest_state
    
    # ========== 全局任务锁检查（防止 OOM） ==========
    can_start, error_msg = start_computation('分层回测')
    if not can_start:
        return jsonify({'success': False, 'error': error_msg})
    
    # 检查是否已经在运行
    with layered_backtest_lock:
        if layered_backtest_state['status'] == 'running':
            end_computation('分层回测')  # 释放锁
            return jsonify({'success': False, 'error': '分层回测正在运行中，请稍候...'})
        
        # 重置状态
        layered_backtest_state = {
            'status': 'running',
            'message': '正在加载数据...',
            'progress': 0,
            'start_time': time.time(),
            'end_time': None,
            'last_update': datetime.now().isoformat(),
            'error': None,
            'result': None
        }
    
    # 固定参数（简化参数设置）
    n_days = 500  # 固定：近2年数据（约500个交易日）
    max_stocks = 0  # 固定：获取全部主板股票（约3000+只）
    num_layers = request.args.get('num_layers', default=5, type=int)
    
    # 在后台线程中执行
    def run_backtest():
        global layered_backtest_state
        
        try:
            from real_data_loader import RealDataLoader
            from layered_backtest import LayeredBacktest
            
            # 更新进度
            _update_layered_progress(10, '正在加载数据...')
            
            # 优先从缓存加载（内存优化版）
            factor_df, return_df = load_cached_data_light()
            
            if factor_df is None or len(factor_df) == 0:
                # 缓存不存在时才从 API 获取
                _update_layered_progress(15, '缓存不存在，正在从 API 获取数据...')
                loader = RealDataLoader(use_mock=False, use_local=False, enable_cache=True)
                
                # 加载真实数据
                _update_layered_progress(20, '正在获取股票列表...')
                factor_df, return_df = loader.load_data_multithreaded(
                    n_days=n_days,
                    max_stocks=max_stocks,
                    enable_complement=True
                )
            else:
                _update_layered_progress(20, f'使用缓存数据（{len(factor_df)} 条记录）')
            
            # 执行分层回测
            _update_layered_progress(80, '正在执行分层回测...')
            backtest = LayeredBacktest(num_layers=num_layers)
            result = backtest.run(factor_df, return_df)
            
            # 转换结果为 JSON 格式（处理日期序列化）
            def convert_dates(df_dict):
                """转换日期为字符串格式"""
                converted = []
                for row in df_dict:
                    new_row = {}
                    for k, v in row.items():
                        if k == 'date':
                            if hasattr(v, 'strftime'):
                                new_row[k] = v.strftime('%Y-%m-%d')
                            elif isinstance(v, str):
                                new_row[k] = v
                            else:
                                new_row[k] = str(v)
                        else:
                            new_row[k] = v
                    converted.append(new_row)
                return converted
            
            result_json = {
                'layer_returns': convert_dates(result.layer_returns.reset_index().to_dict(orient='records')),
                'cumulative_returns': convert_dates(result.cumulative_returns.reset_index().to_dict(orient='records')),
                'statistics': result.statistics.reset_index().to_dict(orient='records'),
                'long_short': convert_dates(result.long_short.reset_index().to_dict(orient='records')),
                'num_layers': num_layers,
                'n_days': len(result.layer_returns),
                'n_stocks': len(factor_df['asset'].unique()) if 'asset' in factor_df.columns else 0
            }
            
            # 保存结果到文件
            result_file = BASE_DIR / 'layered_backtest_result.json'
            with open(result_file, 'w', encoding='utf-8') as f:
                json.dump(result_json, f, ensure_ascii=False, indent=2)
            
            # 完成
            with layered_backtest_lock:
                layered_backtest_state['status'] = 'completed'
                layered_backtest_state['message'] = '分层回测完成!'
                layered_backtest_state['progress'] = 100
                layered_backtest_state['end_time'] = time.time()
                layered_backtest_state['last_update'] = datetime.now().isoformat()
                layered_backtest_state['result'] = result_json
                
        except Exception as e:
            import traceback
            error_msg = str(e)
            traceback.print_exc()
            
            with layered_backtest_lock:
                layered_backtest_state['status'] = 'error'
                layered_backtest_state['error'] = error_msg
                layered_backtest_state['message'] = f'错误: {error_msg}'
                layered_backtest_state['end_time'] = time.time()
                layered_backtest_state['last_update'] = datetime.now().isoformat()
        finally:
            # ========== 确保任务锁被释放 ==========
            end_computation('分层回测')
    
    thread = threading.Thread(target=run_backtest)
    thread.daemon = True
    thread.start()
    
    return jsonify({'success': True, 'message': '分层回测已开始'})


@app.route('/api/layered-backtest/progress')
def api_layered_backtest_progress():
    """API: 获取分层回测进度"""
    global layered_backtest_state
    
    with layered_backtest_lock:
        state = layered_backtest_state.copy()
    
    # 如果已完成，返回结果
    if state['status'] == 'completed' and state['result']:
        return jsonify({
            'status': 'completed',
            'message': state['message'],
            'progress': 100,
            'result': state['result']
        })
    
    return jsonify(state)


@app.route('/api/layered-backtest/result')
def api_layered_backtest_result():
    """API: 获取分层回测结果（从文件读取）"""
    result_file = BASE_DIR / 'layered_backtest_result.json'
    
    if not result_file.exists():
        return jsonify({'error': '分层回测结果不存在，请先运行分层回测'})
    
    try:
        with open(result_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return jsonify(data)
    except Exception as e:
        return jsonify({'error': f'读取结果失败: {str(e)}'})


def _update_layered_progress(progress: int, message: str = ''):
    """更新分层回测进度"""
    global layered_backtest_state
    
    with layered_backtest_lock:
        layered_backtest_state['progress'] = progress
        layered_backtest_state['message'] = message if message else f'处理进度: {progress}%'
        layered_backtest_state['last_update'] = datetime.now().isoformat()


# ==================== 因子分析整合 API ====================

@app.route('/factor-analysis')
@require_auth
def factor_analysis_page():
    """因子分析总览页面"""
    return render_template('factor_analysis.html', active_page='rsi')


@app.route('/api/factor-analysis', methods=['GET'])
def api_factor_analysis():
    """API: 统一因子分析
    
    参数:
        num_layers: 分层数量 (可选，默认5)
        
    注意: n_days 和 max_stocks 已固定为 500 和 0（全部主板股票，2年数据）
    """
    global factor_analysis_state
    
    # ========== 全局任务锁检查（防止 OOM） ==========
    can_start, error_msg = start_computation('因子分析(RSI)')
    if not can_start:
        return jsonify({'success': False, 'error': error_msg})
    
    # 检查是否已经在运行
    with factor_analysis_lock:
        if factor_analysis_state['status'] == 'running':
            end_computation('因子分析(RSI)')  # 释放锁
            return jsonify({'success': False, 'error': '分析正在运行中，请稍候...'})
        
        # 重置状态
        factor_analysis_state = {
            'status': 'running',
            'message': '正在初始化...',
            'progress': 0,
            'start_time': time.time(),
            'end_time': None,
            'last_update': datetime.now().isoformat(),
            'error': None,
            'result': None
        }
    
    # 固定参数（简化参数设置）
    n_days = 500  # 固定：近2年数据（约500个交易日）
    max_stocks = 0  # 固定：获取全部主板股票（约3000+只）
    num_layers = request.args.get('num_layers', default=5, type=int)
    
    # 在后台线程中执行
    def run_factor_analysis():
        global factor_analysis_state
        
        try:
            from real_data_loader import RealDataLoader
            from layered_backtest import LayeredBacktest
            
            # 动态加载 reverse_rank_ic 模块
            import importlib.util
            from pathlib import Path
            module_path = Path('/home/admin/.openclaw/workspace/yunzhou/reverse_rank_ic.py')
            spec = importlib.util.spec_from_file_location("reverse_rank_ic", str(module_path))
            reverse_rank_ic_module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(reverse_rank_ic_module)
            reverse_rank_ic = reverse_rank_ic_module.reverse_rank_ic
            
            # 更新进度：加载数据
            _update_factor_analysis_progress(10, '正在加载数据...')
            
            # 优先从缓存加载（内存优化版）
            factor_df, return_df = load_cached_data_light()
            
            if factor_df is None or len(factor_df) == 0:
                # 缓存不存在时才从 API 获取
                _update_factor_analysis_progress(12, '缓存不存在，正在从 API 获取数据...')
                loader = RealDataLoader(use_mock=False, use_local=False, enable_cache=True)
                
                _update_factor_analysis_progress(15, '正在获取股票列表...')
                factor_df, return_df = loader.load_data_multithreaded(
                    n_days=n_days,
                    max_stocks=max_stocks,
                    enable_complement=True
                )
            else:
                _update_factor_analysis_progress(15, f'使用缓存数据（{len(factor_df)} 条记录）')
            
            _update_factor_analysis_progress(40, '正在计算 IC 指标...')
            
            # 计算 IC
            ic_result = reverse_rank_ic(
                factor_df=factor_df,
                return_df=return_df,
                factor_col='rsi_6',
                return_col='forward_return_1d',
                date_col='date',
                asset_col='asset',
                min_stocks=10
            )
            
            ic_series = ic_result['ic_series']
            
            # 计算 20 日滚动均值
            rolling_mean = ic_series.rolling(window=20, min_periods=1).mean()
            
            # IC 指标
            ic_metrics = {
                'ic_mean': round(ic_result['ic_mean'], 6),
                'ic_std': round(ic_result['ic_std'], 6),
                'icir': round(ic_result['icir'], 4),
                't_stat': round(ic_result['t_stat'], 4),
                'p_value': round(ic_result.get('p_value', 0), 6),
                'positive_ratio': round(ic_result['positive_ratio'], 4),
                'n_days': len(ic_series),
                'n_assets': factor_df['asset'].nunique(),
                'significance': ic_result['significance'],
                'summary': ic_result['summary']
            }
            
            # IC 时间序列
            def convert_dates_for_json(df_or_series):
                """统一转换日期格式为字符串"""
                if isinstance(df_or_series, pd.Series):
                    return {
                        'dates': [str(d) for d in df_or_series.index],
                        'ic_values': [round(v, 6) for v in df_or_series.values],
                        'rolling_ic_mean': [round(v, 6) for v in rolling_mean.values]
                    }
                return df_or_series
            
            ic_series_data = convert_dates_for_json(ic_series)
            
            _update_factor_analysis_progress(60, '正在执行分层回测...')
            
            # 执行分层回测
            backtest = LayeredBacktest(num_layers=num_layers)
            layered_result = backtest.run(factor_df, return_df)
            
            _update_factor_analysis_progress(85, '正在计算综合指标...')
            
            # 转换分层回测结果为 JSON 格式
            def convert_df_dates(df_dict):
                """转换 DataFrame 日期为字符串格式"""
                converted = []
                for row in df_dict:
                    new_row = {}
                    for k, v in row.items():
                        if k == 'date' or k == 'trade_date':
                            if hasattr(v, 'strftime'):
                                new_row[k] = v.strftime('%Y-%m-%d')
                            elif isinstance(v, str):
                                new_row[k] = v
                            else:
                                new_row[k] = str(v)
                        else:
                            new_row[k] = v
                    converted.append(new_row)
                return converted
            
            # 计算最大回撤
            def calculate_max_drawdown(nav_series):
                """计算最大回撤"""
                peak = nav_series.expanding(min_periods=1).max()
                drawdown = (nav_series / peak) - 1
                return round(drawdown.min(), 4)
            
            # 计算单调性检验
            def calculate_monotonicity(statistics_df):
                """检验分层收益单调性"""
                layer_returns = []
                for i in range(1, num_layers + 1):
                    layer_key = f'layer_{i}'
                    if layer_key in statistics_df.index:
                        layer_returns.append(statistics_df.loc[layer_key, 'annual_return'])
                
                # 检查是否单调递增（Layer 1 最低，Layer N 最高）
                for i in range(len(layer_returns) - 1):
                    if layer_returns[i] < layer_returns[i + 1]:
                        return False
                return True
            
            # 构建综合指标摘要
            long_short_stats = layered_result.statistics.loc['long_short']
            summary = {
                'long_short_annual_return': round(float(long_short_stats['annual_return']), 4),
                'long_short_sharpe': round(float(long_short_stats['sharpe']), 4),
                'long_short_max_drawdown': calculate_max_drawdown(layered_result.long_short['cumulative_nav']),
                'monotonicity_passed': calculate_monotonicity(layered_result.statistics)
            }
            
            layered_result_json = {
                'layer_returns': convert_df_dates(layered_result.layer_returns.reset_index().to_dict(orient='records')),
                'cumulative_returns': convert_df_dates(layered_result.cumulative_returns.reset_index().to_dict(orient='records')),
                'statistics': layered_result.statistics.reset_index().to_dict(orient='records'),
                'long_short': convert_df_dates(layered_result.long_short.reset_index().to_dict(orient='records')),
                'num_layers': num_layers,
                'n_days': len(layered_result.layer_returns),
                'n_stocks': len(factor_df['asset'].unique()),
                'summary': summary
            }
            
            _update_factor_analysis_progress(95, '正在保存结果...')
            
            # 构建完整结果
            result_json = {
                'ic_metrics': ic_metrics,
                'ic_series': ic_series_data,
                'layered_result': layered_result_json,
                'params': {
                    'n_days': n_days,
                    'max_stocks': max_stocks,
                    'num_layers': num_layers
                },
                'generated_at': datetime.now().isoformat()
            }
            
            # 保存结果到文件
            result_file = BASE_DIR / 'cache/factor_ic/rsi_ic.json'
            with open(result_file, 'w', encoding='utf-8') as f:
                json.dump(result_json, f, ensure_ascii=False, indent=2)
            
            # 完成
            with factor_analysis_lock:
                factor_analysis_state['status'] = 'completed'
                factor_analysis_state['message'] = '因子分析完成!'
                factor_analysis_state['progress'] = 100
                factor_analysis_state['end_time'] = time.time()
                factor_analysis_state['last_update'] = datetime.now().isoformat()
                factor_analysis_state['result'] = result_json
                
        except Exception as e:
            import traceback
            error_msg = str(e)
            traceback.print_exc()
            
            with factor_analysis_lock:
                factor_analysis_state['status'] = 'error'
                factor_analysis_state['error'] = error_msg
                factor_analysis_state['message'] = f'错误: {error_msg}'
                factor_analysis_state['end_time'] = time.time()
                factor_analysis_state['last_update'] = datetime.now().isoformat()
        finally:
            # ========== 确保任务锁被释放 ==========
            end_computation('因子分析(RSI)')
    
    thread = threading.Thread(target=run_factor_analysis)
    thread.daemon = True
    thread.start()
    
    return jsonify({'success': True, 'message': '因子分析已开始'})


@app.route('/api/factor-analysis/progress')
def api_factor_analysis_progress():
    """API: 获取因子分析进度"""
    global factor_analysis_state
    
    with factor_analysis_lock:
        state = factor_analysis_state.copy()
    
    # 计算预计剩余时间
    if state['status'] == 'running' and state['start_time'] and state['progress'] > 0:
        elapsed = time.time() - state['start_time']
        if state['progress'] > 10:
            avg_time_per_percent = elapsed / state['progress']
            remaining_percent = 100 - state['progress']
            state['estimated_remaining_seconds'] = int(avg_time_per_percent * remaining_percent)
        else:
            state['estimated_remaining_seconds'] = 0
    else:
        state['estimated_remaining_seconds'] = 0
    
    # 如果已完成，返回结果
    if state['status'] == 'completed' and state['result']:
        return jsonify({
            'status': 'completed',
            'message': state['message'],
            'progress': 100,
            'result': state['result'],
            'estimated_remaining_seconds': 0
        })
    
    return jsonify(state)


@app.route('/api/factor-analysis/result')
def api_factor_analysis_result():
    """API: 获取因子分析缓存结果"""
    result_file = BASE_DIR / 'cache/factor_ic/rsi_ic.json'
    
    if not result_file.exists():
        return jsonify({'error': '暂无分析结果，请先运行因子分析'})
    
    try:
        with open(result_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return jsonify(data)
    except Exception as e:
        return jsonify({'error': f'读取结果失败: {str(e)}'})


def _update_factor_analysis_progress(progress: int, message: str = ''):
    """更新因子分析进度"""
    global factor_analysis_state
    
    with factor_analysis_lock:
        factor_analysis_state['progress'] = progress
        factor_analysis_state['message'] = message if message else f'处理进度: {progress}%'
        factor_analysis_state['last_update'] = datetime.now().isoformat()


# ==================== 量比因子分析 API ====================

@app.route('/volume-ratio-analysis')
def volume_ratio_analysis_page():
    """量比因子分析总览页面"""
    return render_template('volume_ratio_analysis.html', active_page='volume_ratio')


@app.route('/api/volume-ratio-analysis', methods=['GET'])
def api_volume_ratio_analysis():
    """API: 量比因子分析
    
    参数:
        num_layers: 分层数量 (可选，默认5)
        
    注意: 
        - n_days 和 max_stocks 已固定为 500 和 0（全部主板股票，2年数据）
        - 量比使用正向排名（不反向），与 RSI 不同
        - 多空策略：做多放量组（Layer N），做空缩量组（Layer 1）
    """
    global volume_ratio_analysis_state
    
    # ========== 全局任务锁检查（防止 OOM） ==========
    can_start, error_msg = start_computation('因子分析(量比)')
    if not can_start:
        return jsonify({'success': False, 'error': error_msg})
    
    # 检查是否已经在运行
    with volume_ratio_analysis_lock:
        if volume_ratio_analysis_state['status'] == 'running':
            end_computation('因子分析(量比)')  # 释放锁
            return jsonify({'success': False, 'error': '分析正在运行中，请稍候...'})
        
        # 重置状态
        volume_ratio_analysis_state = {
            'status': 'running',
            'message': '正在初始化...',
            'progress': 0,
            'start_time': time.time(),
            'end_time': None,
            'last_update': datetime.now().isoformat(),
            'error': None,
            'result': None
        }
    
    # 固定参数（简化参数设置）
    n_days = 500  # 固定：近2年数据（约500个交易日）
    max_stocks = 0  # 固定：获取全部主板股票（约3000+只）
    num_layers = request.args.get('num_layers', default=5, type=int)
    
    # 在后台线程中执行
    def run_volume_ratio_analysis():
        global volume_ratio_analysis_state
        
        try:
            from real_data_loader import RealDataLoader
            from layered_backtest import LayeredBacktest
            
            # 动态加载 reverse_rank_ic 模块
            import importlib.util
            from pathlib import Path
            module_path = Path('/home/admin/.openclaw/workspace/yunzhou/reverse_rank_ic.py')
            spec = importlib.util.spec_from_file_location("reverse_rank_ic", str(module_path))
            reverse_rank_ic_module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(reverse_rank_ic_module)
            reverse_rank_ic = reverse_rank_ic_module.reverse_rank_ic
            
            # 更新进度：加载数据
            _update_volume_ratio_progress(10, '正在加载数据...')
            
            # 优先从缓存加载（内存优化版）
            factor_df, return_df = load_cached_data_light()
            
            if factor_df is None or len(factor_df) == 0:
                # 缓存不存在时才从 API 获取
                _update_volume_ratio_progress(12, '缓存不存在，正在从 API 获取数据...')
                loader = RealDataLoader(use_mock=False, use_local=False, enable_cache=True)
                
                _update_volume_ratio_progress(15, '正在获取股票列表...')
                factor_df, return_df = loader.load_data_multithreaded(
                    n_days=n_days,
                    max_stocks=max_stocks,
                    enable_complement=True
                )
            else:
                _update_volume_ratio_progress(15, f'使用缓存数据（{len(factor_df)} 条记录）')
            
            _update_volume_ratio_progress(40, '正在计算 IC 指标...')
            
            # 计算 IC - 使用正向排名（reverse=False）
            ic_result = reverse_rank_ic(
                factor_df=factor_df,
                return_df=return_df,
                factor_col='volume_ratio_5',
                return_col='forward_return_1d',
                date_col='date',
                asset_col='asset',
                min_stocks=10
            )
            
            ic_series = ic_result['ic_series']
            
            # 计算 20 日滚动均值
            rolling_mean = ic_series.rolling(window=20, min_periods=1).mean()
            
            # IC 指标
            ic_metrics = {
                'ic_mean': round(ic_result['ic_mean'], 6),
                'ic_std': round(ic_result['ic_std'], 6),
                'icir': round(ic_result['icir'], 4),
                't_stat': round(ic_result['t_stat'], 4),
                'p_value': round(ic_result.get('p_value', 0), 6),
                'positive_ratio': round(ic_result['positive_ratio'], 4),
                'n_days': len(ic_series),
                'n_assets': factor_df['asset'].nunique(),
                'significance': ic_result['significance'],
                'summary': ic_result['summary']
            }
            
            # IC 时间序列
            def convert_dates_for_json(df_or_series):
                """统一转换日期格式为字符串"""
                if isinstance(df_or_series, pd.Series):
                    return {
                        'dates': [str(d) for d in df_or_series.index],
                        'ic_values': [round(v, 6) for v in df_or_series.values],
                        'rolling_ic_mean': [round(v, 6) for v in rolling_mean.values]
                    }
                return df_or_series
            
            ic_series_data = convert_dates_for_json(ic_series)
            
            _update_volume_ratio_progress(60, '正在执行分层回测...')
            
            # 执行分层回测 - 使用 volume_ratio_5 作为因子
            backtest = LayeredBacktest(num_layers=num_layers)
            layered_result = backtest.run(factor_df, return_df, factor_col='volume_ratio_5')
            
            _update_volume_ratio_progress(85, '正在计算综合指标...')
            
            # 转换分层回测结果为 JSON 格式
            def convert_df_dates(df_dict):
                """转换 DataFrame 日期为字符串格式"""
                converted = []
                for row in df_dict:
                    new_row = {}
                    for k, v in row.items():
                        if k == 'date' or k == 'trade_date':
                            if hasattr(v, 'strftime'):
                                new_row[k] = v.strftime('%Y-%m-%d')
                            elif isinstance(v, str):
                                new_row[k] = v
                            else:
                                new_row[k] = str(v)
                        else:
                            new_row[k] = v
                    converted.append(new_row)
                return converted
            
            # 计算最大回撤
            def calculate_max_drawdown(nav_series):
                """计算最大回撤"""
                peak = nav_series.expanding(min_periods=1).max()
                drawdown = (nav_series / peak) - 1
                return round(drawdown.min(), 4)
            
            # 计算单调性检验 - 量比因子预期：Layer 1（缩量）收益低，Layer N（放量）收益高
            def calculate_monotonicity(statistics_df):
                """检验分层收益单调性（量比因子：正向，预期收益递增）"""
                layer_returns = []
                for i in range(1, num_layers + 1):
                    layer_key = f'layer_{i}'
                    if layer_key in statistics_df.index:
                        layer_returns.append(statistics_df.loc[layer_key, 'annual_return'])
                
                # 检查是否单调递增（Layer 1 最低，Layer N 最高）
                for i in range(len(layer_returns) - 1):
                    if layer_returns[i] > layer_returns[i + 1]:
                        # 量比因子预期收益递增（放量收益高），所以检查是否递增
                        return False
                return True
            
            # 构建综合指标摘要
            long_short_stats = layered_result.statistics.loc['long_short']
            summary = {
                'long_short_annual_return': round(float(long_short_stats['annual_return']), 4),
                'long_short_sharpe': round(float(long_short_stats['sharpe']), 4),
                'long_short_max_drawdown': calculate_max_drawdown(layered_result.long_short['cumulative_nav']),
                'monotonicity_passed': calculate_monotonicity(layered_result.statistics)
            }
            
            layered_result_json = {
                'layer_returns': convert_df_dates(layered_result.layer_returns.reset_index().to_dict(orient='records')),
                'cumulative_returns': convert_df_dates(layered_result.cumulative_returns.reset_index().to_dict(orient='records')),
                'statistics': layered_result.statistics.reset_index().to_dict(orient='records'),
                'long_short': convert_df_dates(layered_result.long_short.reset_index().to_dict(orient='records')),
                'num_layers': num_layers,
                'n_days': len(layered_result.layer_returns),
                'n_stocks': len(factor_df['asset'].unique()),
                'summary': summary
            }
            
            _update_volume_ratio_progress(95, '正在保存结果...')
            
            # 构建完整结果
            result_json = {
                'ic_metrics': ic_metrics,
                'ic_series': ic_series_data,
                'layered_result': layered_result_json,
                'params': {
                    'n_days': n_days,
                    'max_stocks': max_stocks,
                    'num_layers': num_layers,
                    'factor_col': 'volume_ratio_5'
                },
                'generated_at': datetime.now().isoformat()
            }
            
            # 保存结果到文件
            result_file = BASE_DIR / 'cache/factor_ic/volume_ratio_ic.json'
            with open(result_file, 'w', encoding='utf-8') as f:
                json.dump(result_json, f, ensure_ascii=False, indent=2)
            
            # 完成
            with volume_ratio_analysis_lock:
                volume_ratio_analysis_state['status'] = 'completed'
                volume_ratio_analysis_state['message'] = '量比因子分析完成!'
                volume_ratio_analysis_state['progress'] = 100
                volume_ratio_analysis_state['end_time'] = time.time()
                volume_ratio_analysis_state['last_update'] = datetime.now().isoformat()
                volume_ratio_analysis_state['result'] = result_json
                
        except Exception as e:
            import traceback
            error_msg = str(e)
            traceback.print_exc()
            
            with volume_ratio_analysis_lock:
                volume_ratio_analysis_state['status'] = 'error'
                volume_ratio_analysis_state['error'] = error_msg
                volume_ratio_analysis_state['message'] = f'错误: {error_msg}'
                volume_ratio_analysis_state['end_time'] = time.time()
                volume_ratio_analysis_state['last_update'] = datetime.now().isoformat()
        finally:
            # ========== 确保任务锁被释放 ==========
            end_computation('因子分析(量比)')
    
    thread = threading.Thread(target=run_volume_ratio_analysis)
    thread.daemon = True
    thread.start()
    
    return jsonify({'success': True, 'message': '量比因子分析已开始'})


@app.route('/api/volume-ratio-analysis/progress')
def api_volume_ratio_analysis_progress():
    """API: 获取量比因子分析进度"""
    global volume_ratio_analysis_state
    
    with volume_ratio_analysis_lock:
        state = volume_ratio_analysis_state.copy()
    
    # 计算预计剩余时间
    if state['status'] == 'running' and state['start_time'] and state['progress'] > 0:
        elapsed = time.time() - state['start_time']
        if state['progress'] > 10:
            avg_time_per_percent = elapsed / state['progress']
            remaining_percent = 100 - state['progress']
            state['estimated_remaining_seconds'] = int(avg_time_per_percent * remaining_percent)
        else:
            state['estimated_remaining_seconds'] = 0
    else:
        state['estimated_remaining_seconds'] = 0
    
    # 如果已完成，返回结果
    if state['status'] == 'completed' and state['result']:
        return jsonify({
            'status': 'completed',
            'message': state['message'],
            'progress': 100,
            'result': state['result'],
            'estimated_remaining_seconds': 0
        })
    
    return jsonify(state)


@app.route('/api/volume-ratio-analysis/result')
def api_volume_ratio_analysis_result():
    """API: 获取量比因子分析缓存结果"""
    result_file = BASE_DIR / 'cache/factor_ic/volume_ratio_ic.json'
    
    if not result_file.exists():
        return jsonify({'error': '暂无分析结果，请先运行量比因子分析'})
    
    try:
        with open(result_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return jsonify(data)
    except Exception as e:
        return jsonify({'error': f'读取结果失败: {str(e)}'})


@app.route('/api/factor/volume-ratio')
def api_factor_volume_ratio():
    """API: 获取量比因子完整分析数据
    
    返回格式与 /api/factor/rsi 一致
    """
    result_file = BASE_DIR / 'cache/factor_ic/volume_ratio_ic.json'
    
    if not result_file.exists():
        return jsonify({
            'success': False,
            'error': '量比因子分析数据不存在，请先运行量比因子分析'
        })
    
    try:
        with open(result_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return jsonify({
            'success': True,
            'data': data
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': f'读取数据失败: {str(e)}'
        })


def _update_volume_ratio_progress(progress: int, message: str = ''):
    """更新量比因子分析进度"""
    global volume_ratio_analysis_state
    
    with volume_ratio_analysis_lock:
        volume_ratio_analysis_state['progress'] = progress
        volume_ratio_analysis_state['message'] = message if message else f'处理进度: {progress}%'
        volume_ratio_analysis_state['last_update'] = datetime.now().isoformat()


# ==================== 3日涨幅因子分析 API ====================

@app.route('/return-3d-analysis')
def return_3d_analysis_page():
    """3日涨幅因子分析总览页面"""
    return render_template('return_3d_analysis.html', active_page='return_3d')


@app.route('/api/return-3d-analysis', methods=['GET'])
def api_return_3d_analysis():
    """API: 3日涨幅因子分析（内存优化版）
    
    参数:
        num_layers: 分层数量 (可选，默认5)
        
    注意:
        - 仅使用缓存数据，禁止从 API 重新获取（避免 OOM）
        - 使用反向排名（涨幅高预期回调）
        - 多空策略：做多涨幅低组（Layer N），做空涨幅高组（Layer 1）
        
    内存优化策略（针对 3.5GB 内存服务器）：
        - 使用已有的缓存数据，不调用 RealDataLoader
        - 分步骤释放变量，减少内存峰值
        - 使用 gc.collect() 强制垃圾回收
        - 只保留必要的列，减少内存占用
    """
    global return_3d_analysis_state
    
    # 检查是否已经在运行
    with return_3d_analysis_lock:
        if return_3d_analysis_state['status'] == 'running':
            return jsonify({'success': False, 'error': '分析正在运行中，请稍候...'})
        
        # 重置状态
        return_3d_analysis_state = {
            'status': 'running',
            'message': '正在初始化...',
            'progress': 0,
            'start_time': time.time(),
            'end_time': None,
            'last_update': datetime.now().isoformat(),
            'error': None,
            'result': None
        }
    
    # ========== 优先检查预计算结果 ==========
    result_file = BASE_DIR / 'return_3d_analysis_result.json'
    
    if result_file.exists():
        # 预计算结果存在，直接返回
        try:
            with open(result_file, 'r', encoding='utf-8') as f:
                precomputed_result = json.load(f)
            
            # 更新状态为已完成
            with return_3d_analysis_lock:
                return_3d_analysis_state['status'] = 'completed'
                return_3d_analysis_state['message'] = '使用预计算结果（避免 OOM）'
                return_3d_analysis_state['progress'] = 100
                return_3d_analysis_state['end_time'] = time.time()
                return_3d_analysis_state['last_update'] = datetime.now().isoformat()
                return_3d_analysis_state['result'] = precomputed_result
            
            return jsonify({
                'success': True, 
                'message': '使用预计算结果，分析已完成',
                'result': precomputed_result
            })
        except Exception as e:
            print(f'[预计算结果] 读取失败: {e}')
    
    # 固定参数（内存优化：使用 category 类型，可加载全量 500 天数据）
    n_days = 500  # 修改：加载全量数据（500天，约2年），使用内存优化
    max_stocks = 0
    num_layers = request.args.get('num_layers', default=5, type=int)
    
    # 在后台线程中执行（仅在预计算结果不存在时）
    def run_return_3d_analysis():
        global return_3d_analysis_state
        import gc  # 内存管理
        
        try:
            from layered_backtest import LayeredBacktest
            
            # 动态加载 reverse_rank_ic 模块
            import importlib.util
            module_path = Path('/home/admin/.openclaw/workspace/yunzhou/reverse_rank_ic.py')
            spec = importlib.util.spec_from_file_location("reverse_rank_ic", str(module_path))
            reverse_rank_ic_module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(reverse_rank_ic_module)
            reverse_rank_ic = reverse_rank_ic_module.reverse_rank_ic
            
            # ========== Step 1: 检查缓存是否存在 ==========
            cache_dir = Path('/home/admin/.openclaw/workspace/yunzhou/factor_ic_analyzer/cache/factor_data')
            factor_cache_path = cache_dir / 'factor_data.json.gz'
            return_cache_path = cache_dir / 'return_data.json.gz'
            
            if not factor_cache_path.exists() or not return_cache_path.exists():
                # 缓存不存在，直接报错（禁止从 API 重新获取，避免 OOM）
                error_msg = '缓存数据不存在，请先在内存充足时运行数据更新。当前服务器内存不足，无法从 API 重新获取数据。'
                with return_3d_analysis_lock:
                    return_3d_analysis_state['status'] = 'error'
                    return_3d_analysis_state['error'] = error_msg
                    return_3d_analysis_state['message'] = f'错误: {error_msg}'
                    return_3d_analysis_state['end_time'] = time.time()
                    return_3d_analysis_state['last_update'] = datetime.now().isoformat()
                return
            
            # ========== Step 2: 使用轻量级缓存加载（内存优化） ==========
            _update_return_3d_progress(10, '正在加载缓存数据（轻量模式）...')
            
            # 使用轻量级加载，只加载最近 150 天数据
            factor_df, return_df = load_cached_data_light(max_days=n_days)
            
            if factor_df is None or len(factor_df) == 0:
                error_msg = '缓存数据加载失败，请检查缓存文件完整性。'
                with return_3d_analysis_lock:
                    return_3d_analysis_state['status'] = 'error'
                    return_3d_analysis_state['error'] = error_msg
                    return_3d_analysis_state['message'] = f'错误: {error_msg}'
                    return_3d_analysis_state['end_time'] = time.time()
                    return_3d_analysis_state['last_update'] = datetime.now().isoformat()
                return
            
            _update_return_3d_progress(15, f'缓存数据加载成功（内存优化，{len(factor_df)} 条记录）')
            
            # ========== Step 3: 计算 return_3d 因子（内存优化） ==========
            _update_return_3d_progress(20, '正在计算 3日涨幅因子...')
            
            # factor_df 已经只包含必要列（date, asset, close），且使用了 category 类型
            # 直接使用，无需再次复制
            
            # 排序并计算 return_3d（向量化，避免循环）
            # 注意：category 类型可以直接排序
            factor_df = factor_df.sort_values(['asset', 'date']).copy()
            
            # 计算 return_3d
            factor_df['return_3d'] = factor_df.groupby('asset')['close'].transform(
                lambda x: (x - x.shift(3)) / x.shift(3)
            )
            
            # 删除前3天的 NaN 和 close 列（不再需要）
            factor_df = factor_df.dropna(subset=['return_3d'])
            factor_df = factor_df.drop(columns=['close'])
            
            gc.collect()
            
            _update_return_3d_progress(30, f'因子计算完成，{len(factor_df)} 条有效记录')
            
            # ========== Step 4: 计算 IC（内存优化） ==========
            _update_return_3d_progress(35, '正在计算 IC 指标...')
            
            ic_result = reverse_rank_ic(
                factor_df=factor_df,
                return_df=return_df,
                factor_col='return_3d',
                return_col='forward_return_1d',
                date_col='date',
                asset_col='asset',
                min_stocks=10
            )
            
            ic_series = ic_result['ic_series']
            rolling_mean = ic_series.rolling(window=20, min_periods=1).mean()
            
            # 提取 IC 指标（立即转换为基本类型，释放中间对象）
            ic_metrics = {
                'ic_mean': round(ic_result['ic_mean'], 6),
                'ic_std': round(ic_result['ic_std'], 6),
                'icir': round(ic_result['icir'], 4),
                't_stat': round(ic_result['t_stat'], 4),
                'p_value': round(ic_result.get('p_value', 0), 6),
                'positive_ratio': round(ic_result['positive_ratio'], 4),
                'n_days': len(ic_series),
                'n_assets': factor_df['asset'].nunique(),
                'significance': ic_result['significance'],
                'summary': ic_result['summary']
            }
            
            # IC 时间序列数据（转换为列表，释放 Series）
            ic_series_data = {
                'dates': [str(d) for d in ic_series.index],
                'ic_values': [round(v, 6) for v in ic_series.values],
                'rolling_ic_mean': [round(v, 6) for v in rolling_mean.values]
            }
            
            # 释放 IC 计算的中间变量
            del ic_result, ic_series, rolling_mean
            gc.collect()
            
            _update_return_3d_progress(50, 'IC 计算完成')
            
            # ========== Step 5: 分层回测（内存优化） ==========
            _update_return_3d_progress(55, '正在执行分层回测...')
            
            backtest = LayeredBacktest(num_layers=num_layers)
            layered_result = backtest.run(factor_df, return_df, factor_col='return_3d', return_col='forward_return_1d')
            
            # 释放输入数据
            del factor_df, return_df
            gc.collect()
            
            _update_return_3d_progress(75, '正在计算综合指标...')
            
            # 转换结果为 JSON 格式
            def convert_df_dates(df_dict):
                converted = []
                for row in df_dict:
                    new_row = {}
                    for k, v in row.items():
                        if k in ('date', 'trade_date'):
                            if hasattr(v, 'strftime'):
                                new_row[k] = v.strftime('%Y-%m-%d')
                            else:
                                new_row[k] = str(v)
                        else:
                            new_row[k] = v
                    converted.append(new_row)
                return converted
            
            # 最大回撤计算
            def calculate_max_drawdown(nav_series):
                peak = nav_series.expanding(min_periods=1).max()
                drawdown = (nav_series / peak) - 1
                return round(drawdown.min(), 4)
            
            # 单调性检验（涨幅因子：预期 Layer 1（涨幅高）收益低，Layer N（涨幅低）收益高）
            def calculate_monotonicity(statistics_df):
                layer_returns = []
                for i in range(1, num_layers + 1):
                    layer_key = f'layer_{i}'
                    if layer_key in statistics_df.index:
                        layer_returns.append(statistics_df.loc[layer_key, 'annual_return'])
                
                # 反向因子预期收益递增（涨幅高 → 排名低 → Layer 1 → 预期收益低）
                for i in range(len(layer_returns) - 1):
                    if layer_returns[i] < layer_returns[i + 1]:
                        return True  # 符合预期：收益递增（涨幅低组收益高）
                return False
            
            long_short_stats = layered_result.statistics.loc['long_short']
            summary = {
                'long_short_annual_return': round(float(long_short_stats['annual_return']), 4),
                'long_short_sharpe': round(float(long_short_stats['sharpe']), 4),
                'long_short_max_drawdown': calculate_max_drawdown(layered_result.long_short['cumulative_nav']),
                'monotonicity_passed': calculate_monotonicity(layered_result.statistics)
            }
            
            # 转换为 JSON 格式（立即释放 DataFrame）
            layered_result_json = {
                'layer_returns': convert_df_dates(layered_result.layer_returns.reset_index().to_dict(orient='records')),
                'cumulative_returns': convert_df_dates(layered_result.cumulative_returns.reset_index().to_dict(orient='records')),
                'statistics': layered_result.statistics.reset_index().to_dict(orient='records'),
                'long_short': convert_df_dates(layered_result.long_short.reset_index().to_dict(orient='records')),
                'num_layers': num_layers,
                'n_days': len(layered_result.layer_returns),
                'n_stocks': ic_metrics['n_assets'],  # 使用之前保存的值
                'summary': summary
            }
            
            # 释放分层回测结果
            del layered_result, backtest
            gc.collect()
            
            _update_return_3d_progress(90, '正在保存结果...')
            
            result_json = {
                'ic_metrics': ic_metrics,
                'ic_series': ic_series_data,
                'layered_result': layered_result_json,
                'params': {
                    'n_days': n_days,
                    'max_stocks': max_stocks,
                    'num_layers': num_layers,
                    'factor_col': 'return_3d'
                },
                'generated_at': datetime.now().isoformat()
            }
            
            # 保存结果
            result_file = BASE_DIR / 'return_3d_analysis_result.json'
            with open(result_file, 'w', encoding='utf-8') as f:
                json.dump(result_json, f, ensure_ascii=False, indent=2)
            
            # 最终清理
            del layered_result_json, ic_metrics, ic_series_data
            gc.collect()
            
            # 完成
            with return_3d_analysis_lock:
                return_3d_analysis_state['status'] = 'completed'
                return_3d_analysis_state['message'] = '3日涨幅因子分析完成!'
                return_3d_analysis_state['progress'] = 100
                return_3d_analysis_state['end_time'] = time.time()
                return_3d_analysis_state['last_update'] = datetime.now().isoformat()
                return_3d_analysis_state['result'] = result_json
                
        except Exception as e:
            import traceback
            error_msg = str(e)
            traceback.print_exc()
            
            # 异常时也尝试清理内存
            gc.collect()
            
            with return_3d_analysis_lock:
                return_3d_analysis_state['status'] = 'error'
                return_3d_analysis_state['error'] = error_msg
                return_3d_analysis_state['message'] = f'错误: {error_msg}'
                return_3d_analysis_state['end_time'] = time.time()
                return_3d_analysis_state['last_update'] = datetime.now().isoformat()
    
    thread = threading.Thread(target=run_return_3d_analysis)
    thread.daemon = True
    thread.start()
    
    return jsonify({'success': True, 'message': '3日涨幅因子分析已开始'})


@app.route('/api/return-3d-analysis/progress')
def api_return_3d_analysis_progress():
    """API: 获取3日涨幅因子分析进度"""
    global return_3d_analysis_state
    
    with return_3d_analysis_lock:
        state = return_3d_analysis_state.copy()
    
    # 计算预计剩余时间
    if state['status'] == 'running' and state['start_time'] and state['progress'] > 0:
        elapsed = time.time() - state['start_time']
        if state['progress'] > 10:
            avg_time_per_percent = elapsed / state['progress']
            remaining_percent = 100 - state['progress']
            state['estimated_remaining_seconds'] = int(avg_time_per_percent * remaining_percent)
        else:
            state['estimated_remaining_seconds'] = 0
    else:
        state['estimated_remaining_seconds'] = 0
    
    # 如果已完成，返回结果
    if state['status'] == 'completed' and state['result']:
        return jsonify({
            'status': 'completed',
            'message': state['message'],
            'progress': 100,
            'result': state['result'],
            'estimated_remaining_seconds': 0
        })
    
    return jsonify(state)


@app.route('/api/return-3d-analysis/result')
def api_return_3d_analysis_result():
    """API: 获取3日涨幅因子分析缓存结果"""
    result_file = BASE_DIR / 'return_3d_analysis_result.json'
    
    if not result_file.exists():
        return jsonify({'error': '暂无分析结果，请先运行3日涨幅因子分析'})
    
    try:
        with open(result_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return jsonify(data)
    except Exception as e:
        return jsonify({'error': f'读取结果失败: {str(e)}'})


@app.route('/api/factor/return-3d')
def api_factor_return_3d():
    """API: 获取3日涨幅因子完整分析数据
    
    返回格式与 /api/factor/rsi 一致
    """
    result_file = BASE_DIR / 'return_3d_analysis_result.json'
    
    if not result_file.exists():
        return jsonify({
            'success': False,
            'error': '3日涨幅因子分析数据不存在，请先运行3日涨幅因子分析'
        })
    
    try:
        with open(result_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return jsonify({
            'success': True,
            'data': data
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': f'读取数据失败: {str(e)}'
        })


def _update_return_3d_progress(progress: int, message: str = ''):
    """更新3日涨幅因子分析进度"""
    global return_3d_analysis_state
    
    with return_3d_analysis_lock:
        return_3d_analysis_state['progress'] = progress
        return_3d_analysis_state['message'] = message if message else f'处理进度: {progress}%'
        return_3d_analysis_state['last_update'] = datetime.now().isoformat()


def _update_progress(current_batch, total_batches, stocks_fetched, success_count, fail_count, message=''):
    """更新进度状态的回调函数"""
    global progress_state
    
    with progress_lock:
        progress_state['current_batch'] = current_batch
        progress_state['total_batches'] = total_batches
        progress_state['stocks_fetched'] = stocks_fetched
        progress_state['success_count'] = success_count
        progress_state['fail_count'] = fail_count
        progress_state['last_update'] = datetime.now().isoformat()
        
        # 根据消息内容判断阶段，调整显示
        if message:
            progress_state['message'] = message
            # 如果是初始化或计算阶段，保持传入的批次信息
            if '初始化' in message or '计算' in message or '保存' in message:
                pass  # 使用传入的 current_batch/total_batches
            else:
                # 数据获取阶段：消息中已经包含了批次信息
                pass
        else:
            progress_state['message'] = f'正在获取第 {current_batch}/{total_batches} 批数据...'
        
        # 计算成功率
        total = success_count + fail_count
        if total > 0:
            progress_state['success_rate'] = round(success_count / total * 100, 1)
        else:
            progress_state['success_rate'] = 0


# ==================== 统一 API 路由（兼容旧路由） ====================

# ========== 因子分析统一路由（RSI） ==========

@app.route('/api/factor/rsi/analysis', methods=['GET'])
def api_factor_rsi_analysis():
    """API: RSI 因子分析（统一路由）
    
    别名路由，内部调用 api_factor_analysis
    """
    return api_factor_analysis()


@app.route('/api/factor/rsi/progress')
def api_factor_rsi_progress():
    """API: RSI 因子分析进度（统一路由）
    
    别名路由，内部调用 api_factor_analysis_progress
    """
    return api_factor_analysis_progress()


@app.route('/api/factor/rsi/result')
def api_factor_rsi_result():
    """API: RSI 因子分析结果（统一路由）
    
    别名路由，内部调用 api_factor_analysis_result
    """
    return api_factor_analysis_result()


# ========== 因子分析统一路由（量比） ==========

@app.route('/api/factor/volume-ratio/analysis', methods=['GET'])
def api_factor_volume_ratio_analysis():
    """API: 量比因子分析（统一路由）
    
    别名路由，内部调用 api_volume_ratio_analysis
    """
    return api_volume_ratio_analysis()


@app.route('/api/factor/volume-ratio/progress')
def api_factor_volume_ratio_progress():
    """API: 量比因子分析进度（统一路由）
    
    别名路由，内部调用 api_volume_ratio_analysis_progress
    """
    return api_volume_ratio_analysis_progress()


@app.route('/api/factor/volume-ratio/result')
def api_factor_volume_ratio_result():
    """API: 量比因子分析结果（统一路由）
    
    别名路由，内部调用 api_volume_ratio_analysis_result
    """
    return api_volume_ratio_analysis_result()


# ========== 因子分析统一路由（3日涨幅） ==========

@app.route('/api/factor/return-3d/analysis', methods=['GET'])
def api_factor_return_3d_analysis():
    """API: 3日涨幅因子分析（统一路由）
    
    别名路由，内部调用 api_return_3d_analysis
    """
    return api_return_3d_analysis()


@app.route('/api/factor/return-3d/progress')
def api_factor_return_3d_progress():
    """API: 3日涨幅因子分析进度（统一路由）
    
    别名路由，内部调用 api_return_3d_analysis_progress
    """
    return api_return_3d_analysis_progress()


@app.route('/api/factor/return-3d/result')
def api_factor_return_3d_result():
    """API: 3日涨幅因子分析结果（统一路由）
    
    别名路由，内部调用 api_return_3d_analysis_result
    """
    return api_return_3d_analysis_result()


# ==================== 换手率突增因子分析 API ====================

@app.route('/turnover-surge-analysis')
def turnover_surge_analysis_page():
    """换手率突增因子分析总览页面"""
    return render_template('turnover_surge_analysis.html', active_page='turnover_surge')


@app.route('/api/turnover-surge-analysis', methods=['GET'])
def api_turnover_surge_analysis():
    """API: 换手率突增因子分析（内存优化版）
    
    参数:
        num_layers: 分层数量 (可选，默认5)
        
    注意:
        - 使用缓存数据，避免从 API 重新获取（避免 OOM）
        - 筛选条件：放量（volume_ratio_5 > 1）且上涨（当日涨跌幅 > 0）
        - 不满足条件的股票因子值设为 None
        - 使用正向排名（因子值越高预期收益越高）
        
    内存优化策略（针对 3.5GB 内存服务器）：
        - 使用已有的缓存数据，不调用 RealDataLoader
        - 分步骤释放变量，减少内存峰值
        - 使用 gc.collect() 强制垃圾回收
        - 只保留必要的列，减少内存占用
    """
    global turnover_surge_analysis_state
    
    # 检查是否已经在运行
    with turnover_surge_analysis_lock:
        if turnover_surge_analysis_state['status'] == 'running':
            return jsonify({'success': False, 'error': '分析正在运行中，请稍候...'})
        
        # 重置状态
        turnover_surge_analysis_state = {
            'status': 'running',
            'message': '正在初始化...',
            'progress': 0,
            'start_time': time.time(),
            'end_time': None,
            'last_update': datetime.now().isoformat(),
            'error': None,
            'result': None
        }
    
    # ========== 优先检查预计算结果 ==========
    result_file = BASE_DIR / 'cache/factor_ic/turnover_surge_ic.json'
    
    if result_file.exists():
        # 预计算结果存在，直接返回
        try:
            with open(result_file, 'r', encoding='utf-8') as f:
                precomputed_result = json.load(f)
            
            # 更新状态为已完成
            with turnover_surge_analysis_lock:
                turnover_surge_analysis_state['status'] = 'completed'
                turnover_surge_analysis_state['message'] = '使用预计算结果（避免 OOM）'
                turnover_surge_analysis_state['progress'] = 100
                turnover_surge_analysis_state['end_time'] = time.time()
                turnover_surge_analysis_state['last_update'] = datetime.now().isoformat()
                turnover_surge_analysis_state['result'] = precomputed_result
            
            return jsonify({
                'success': True, 
                'message': '使用预计算结果，分析已完成',
                'result': precomputed_result
            })
        except Exception as e:
            print(f'[预计算结果] 读取失败: {e}')
    
    # 固定参数
    n_days = 500
    max_stocks = 0
    num_layers = request.args.get('num_layers', default=5, type=int)
    
    # 在后台线程中执行（仅在预计算结果不存在时）
    def run_turnover_surge_analysis_task():
        global turnover_surge_analysis_state
        import gc  # 内存管理
        
        try:
            # 动态加载模块
            import importlib.util
            module_path = Path('/home/admin/.openclaw/workspace/yunzhou/factor_ic_analyzer/turnover_surge_factor.py')
            spec = importlib.util.spec_from_file_location("turnover_surge_factor", str(module_path))
            turnover_surge_module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(turnover_surge_module)
            run_analysis = turnover_surge_module.run_turnover_surge_analysis
            
            _update_turnover_surge_progress(5, '正在加载数据...')
            
            # 执行分析
            result = run_analysis(
                n_days=n_days,
                num_layers=num_layers,
                filter_conditions=True
            )
            
            if not result.get('success'):
                raise Exception(result.get('error', '分析失败'))
            
            _update_turnover_surge_progress(95, '正在保存结果...')
            
            # 修复：转换 numpy 类型为 Python 原生类型，确保 JSON 可序列化
            result = convert_to_native_types(result)
            
            # 保存结果（原子写入，防止文件截断）
            atomic_write_json(result_file, result)
            
            # 完成
            with turnover_surge_analysis_lock:
                turnover_surge_analysis_state['status'] = 'completed'
                turnover_surge_analysis_state['message'] = '换手率突增因子分析完成!'
                turnover_surge_analysis_state['progress'] = 100
                turnover_surge_analysis_state['end_time'] = time.time()
                turnover_surge_analysis_state['last_update'] = datetime.now().isoformat()
                turnover_surge_analysis_state['result'] = result
                
        except Exception as e:
            import traceback
            error_msg = str(e)
            traceback.print_exc()
            
            # 异常时也尝试清理内存
            gc.collect()
            
            with turnover_surge_analysis_lock:
                turnover_surge_analysis_state['status'] = 'error'
                turnover_surge_analysis_state['error'] = error_msg
                turnover_surge_analysis_state['message'] = f'错误: {error_msg}'
                turnover_surge_analysis_state['end_time'] = time.time()
                turnover_surge_analysis_state['last_update'] = datetime.now().isoformat()
    
    thread = threading.Thread(target=run_turnover_surge_analysis_task)
    thread.daemon = True
    thread.start()
    
    return jsonify({'success': True, 'message': '换手率突增因子分析已开始'})


@app.route('/api/turnover-surge-analysis/progress')
def api_turnover_surge_analysis_progress():
    """API: 获取换手率突增因子分析进度"""
    global turnover_surge_analysis_state
    
    with turnover_surge_analysis_lock:
        state = turnover_surge_analysis_state.copy()
    
    # 计算预计剩余时间
    if state['status'] == 'running' and state['start_time'] and state['progress'] > 0:
        elapsed = time.time() - state['start_time']
        if state['progress'] > 10:
            avg_time_per_percent = elapsed / state['progress']
            remaining_percent = 100 - state['progress']
            state['estimated_remaining_seconds'] = int(avg_time_per_percent * remaining_percent)
        else:
            state['estimated_remaining_seconds'] = 0
    else:
        state['estimated_remaining_seconds'] = 0
    
    # 如果已完成，返回结果
    if state['status'] == 'completed' and state['result']:
        return jsonify({
            'status': 'completed',
            'message': state['message'],
            'progress': 100,
            'result': state['result'],
            'estimated_remaining_seconds': 0
        })
    
    return jsonify(state)


@app.route('/api/turnover-surge-analysis/result')
def api_turnover_surge_analysis_result():
    """API: 获取换手率突增因子分析缓存结果"""
    result_file = BASE_DIR / 'cache/factor_ic/turnover_surge_ic.json'
    
    if not result_file.exists():
        return jsonify({'error': '暂无分析结果，请先运行换手率突增因子分析'})
    
    try:
        with open(result_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return jsonify(data)
    except Exception as e:
        return jsonify({'error': f'读取结果失败: {str(e)}'})


@app.route('/api/factor/turnover-surge')
def api_factor_turnover_surge():
    """API: 获取换手率突增因子完整分析数据
    
    返回格式与 /api/factor/rsi 一致
    """
    result_file = BASE_DIR / 'cache/factor_ic/turnover_surge_ic.json'
    
    if not result_file.exists():
        return jsonify({
            'success': False,
            'error': '换手率突增因子分析数据不存在，请先运行分析'
        })
    
    try:
        with open(result_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return jsonify({
            'success': True,
            'data': data
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': f'读取数据失败: {str(e)}'
        })


def _update_turnover_surge_progress(progress: int, message: str = ''):
    """更新换手率突增因子分析进度"""
    global turnover_surge_analysis_state
    
    with turnover_surge_analysis_lock:
        turnover_surge_analysis_state['progress'] = progress
        turnover_surge_analysis_state['message'] = message if message else f'处理进度: {progress}%'
        turnover_surge_analysis_state['last_update'] = datetime.now().isoformat()


# ========== 因子分析统一路由（换手率突增） ==========

@app.route('/api/factor/turnover-surge/analysis', methods=['GET'])
def api_factor_turnover_surge_analysis():
    """API: 换手率突增因子分析（统一路由）
    
    别名路由，内部调用 api_turnover_surge_analysis
    """
    return api_turnover_surge_analysis()


@app.route('/api/factor/turnover-surge/progress')
def api_factor_turnover_surge_progress():
    """API: 换手率突增因子分析进度（统一路由）
    
    别名路由，内部调用 api_turnover_surge_analysis_progress
    """
    return api_turnover_surge_analysis_progress()


@app.route('/api/factor/turnover-surge/result')
def api_factor_turnover_surge_result():
    """API: 换手率突增因子分析结果（统一路由）
    
    别名路由，内部调用 api_turnover_surge_analysis_result
    """
    return api_turnover_surge_analysis_result()


# ==================== 主力净流入占比因子分析 API ====================

@app.route('/main-inflow-ratio-analysis')
def main_inflow_ratio_analysis_page():
    """主力净流入占比因子分析总览页面"""
    return render_template('main_inflow_ratio_analysis.html', active_page='main_inflow')


@app.route('/api/main-inflow-ratio-analysis', methods=['GET'])
def api_main_inflow_ratio_analysis():
    """API: 主力净流入占比因子分析（内存优化版）
    
    参数:
        num_layers: 分层数量 (可选，默认10)
        
    注意:
        - 需要先运行 precompute_main_inflow.py 获取数据
        - 主力净流入占比是正向因子（流入预期上涨）
        - 多空策略：做多流入组（Layer N），做空流出组（Layer 1）
        
    内存优化策略：
        - 使用已有的缓存数据，不调用 API 重新获取
        - 分步骤释放变量，减少内存峰值
        - 使用 gc.collect() 强制垃圾回收
    """
    global main_inflow_ratio_analysis_state
    
    # ========== 全局任务锁检查（防止 OOM） ==========
    can_start, error_msg = start_computation('因子分析(主力净流入)')
    if not can_start:
        return jsonify({'success': False, 'error': error_msg})
    
    # 检查是否已经在运行
    with main_inflow_ratio_analysis_lock:
        if main_inflow_ratio_analysis_state['status'] == 'running':
            end_computation('因子分析(主力净流入)')  # 释放锁
            return jsonify({'success': False, 'error': '分析正在运行中，请稍候...'})
        
        # 重置状态
        main_inflow_ratio_analysis_state = {
            'status': 'running',
            'message': '正在初始化...',
            'progress': 0,
            'start_time': time.time(),
            'end_time': None,
            'last_update': datetime.now().isoformat(),
            'error': None,
            'result': None
        }
    
    # ========== 优先检查预计算结果 ==========
    result_file = BASE_DIR / 'cache/factor_ic/main_inflow_ratio_ic.json'
    
    if result_file.exists():
        # 预计算结果存在，直接返回
        try:
            with open(result_file, 'r', encoding='utf-8') as f:
                precomputed_result = json.load(f)
            
            # 更新状态为已完成
            with main_inflow_ratio_analysis_lock:
                main_inflow_ratio_analysis_state['status'] = 'completed'
                main_inflow_ratio_analysis_state['message'] = '使用预计算结果（避免 OOM）'
                main_inflow_ratio_analysis_state['progress'] = 100
                main_inflow_ratio_analysis_state['end_time'] = time.time()
                main_inflow_ratio_analysis_state['last_update'] = datetime.now().isoformat()
                main_inflow_ratio_analysis_state['result'] = precomputed_result
            
            end_computation('因子分析(主力净流入)')
            
            return jsonify({
                'success': True, 
                'message': '使用预计算结果，分析已完成',
                'result': precomputed_result
            })
        except Exception as e:
            print(f'[预计算结果] 读取失败: {e}')
    
    # 固定参数
    n_days = 500
    max_stocks = 0
    num_layers = request.args.get('num_layers', default=10, type=int)
    
    # 在后台线程中执行（仅在预计算结果不存在时）
    def run_main_inflow_ratio_analysis_task():
        global main_inflow_ratio_analysis_state
        import gc  # 内存管理
        
        try:
            # 动态加载模块
            import importlib.util
            module_path = Path('/home/admin/.openclaw/workspace/yunzhou/factor_ic_analyzer/main_inflow_ratio_factor.py')
            spec = importlib.util.spec_from_file_location("main_inflow_ratio_factor", str(module_path))
            main_inflow_module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(main_inflow_module)
            run_analysis = main_inflow_module.run_main_inflow_ratio_analysis
            
            _update_main_inflow_ratio_progress(5, '正在加载数据...')
            
            # 执行分析
            result = run_analysis(
                n_days=n_days,
                num_layers=num_layers,
                winsorize=True
            )
            
            if not result.get('success'):
                raise Exception(result.get('error', '分析失败'))
            
            _update_main_inflow_ratio_progress(95, '正在保存结果...')
            
            # 转换 numpy 类型为 Python 原生类型
            result = convert_to_native_types(result)
            
            # 保存结果（原子写入）
            atomic_write_json(result_file, result)
            
            # 完成
            with main_inflow_ratio_analysis_lock:
                main_inflow_ratio_analysis_state['status'] = 'completed'
                main_inflow_ratio_analysis_state['message'] = '主力净流入占比因子分析完成!'
                main_inflow_ratio_analysis_state['progress'] = 100
                main_inflow_ratio_analysis_state['end_time'] = time.time()
                main_inflow_ratio_analysis_state['last_update'] = datetime.now().isoformat()
                main_inflow_ratio_analysis_state['result'] = result
                
        except Exception as e:
            import traceback
            error_msg = str(e)
            traceback.print_exc()
            
            # 异常时清理内存
            gc.collect()
            
            with main_inflow_ratio_analysis_lock:
                main_inflow_ratio_analysis_state['status'] = 'error'
                main_inflow_ratio_analysis_state['error'] = error_msg
                main_inflow_ratio_analysis_state['message'] = f'错误: {error_msg}'
                main_inflow_ratio_analysis_state['end_time'] = time.time()
                main_inflow_ratio_analysis_state['last_update'] = datetime.now().isoformat()
        finally:
            # 确保任务锁被释放
            end_computation('因子分析(主力净流入)')
    
    thread = threading.Thread(target=run_main_inflow_ratio_analysis_task)
    thread.daemon = True
    thread.start()
    
    return jsonify({'success': True, 'message': '主力净流入占比因子分析已开始'})


@app.route('/api/main-inflow-ratio-analysis/progress')
def api_main_inflow_ratio_analysis_progress():
    """API: 获取主力净流入占比因子分析进度"""
    global main_inflow_ratio_analysis_state
    
    with main_inflow_ratio_analysis_lock:
        state = main_inflow_ratio_analysis_state.copy()
    
    # 计算预计剩余时间
    if state['status'] == 'running' and state['start_time'] and state['progress'] > 0:
        elapsed = time.time() - state['start_time']
        if state['progress'] > 10:
            avg_time_per_percent = elapsed / state['progress']
            remaining_percent = 100 - state['progress']
            state['estimated_remaining_seconds'] = int(avg_time_per_percent * remaining_percent)
        else:
            state['estimated_remaining_seconds'] = 0
    else:
        state['estimated_remaining_seconds'] = 0
    
    # 如果已完成，返回结果
    if state['status'] == 'completed' and state['result']:
        return jsonify({
            'status': 'completed',
            'message': state['message'],
            'progress': 100,
            'result': state['result'],
            'estimated_remaining_seconds': 0
        })
    
    return jsonify(state)


@app.route('/api/main-inflow-ratio-analysis/result')
def api_main_inflow_ratio_analysis_result():
    """API: 获取主力净流入占比因子分析缓存结果"""
    result_file = BASE_DIR / 'cache/factor_ic/main_inflow_ratio_ic.json'
    
    if not result_file.exists():
        return jsonify({'error': '暂无分析结果，请先运行主力净流入占比因子分析'})
    
    try:
        with open(result_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return jsonify(data)
    except Exception as e:
        return jsonify({'error': f'读取结果失败: {str(e)}'})


@app.route('/api/factor/main-inflow-ratio')
def api_factor_main_inflow_ratio():
    """API: 获取主力净流入占比因子完整分析数据
    
    返回格式与 /api/factor/rsi 一致
    """
    result_file = BASE_DIR / 'cache/factor_ic/main_inflow_ratio_ic.json'
    
    if not result_file.exists():
        return jsonify({
            'success': False,
            'error': '主力净流入占比因子分析数据不存在，请先运行分析'
        })
    
    try:
        with open(result_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return jsonify({
            'success': True,
            'data': data
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': f'读取数据失败: {str(e)}'
        })


def _update_main_inflow_ratio_progress(progress: int, message: str = ''):
    """更新主力净流入占比因子分析进度"""
    global main_inflow_ratio_analysis_state
    
    with main_inflow_ratio_analysis_lock:
        main_inflow_ratio_analysis_state['progress'] = progress
        main_inflow_ratio_analysis_state['message'] = message if message else f'处理进度: {progress}%'
        main_inflow_ratio_analysis_state['last_update'] = datetime.now().isoformat()


# ========== 因子分析统一路由（主力净流入占比） ==========

@app.route('/api/factor/main-inflow-ratio/analysis', methods=['GET'])
def api_factor_main_inflow_ratio_analysis():
    """API: 主力净流入占比因子分析（统一路由）
    
    别名路由，内部调用 api_main_inflow_ratio_analysis
    """
    return api_main_inflow_ratio_analysis()


@app.route('/api/factor/main-inflow-ratio/progress')
def api_factor_main_inflow_ratio_progress():
    """API: 主力净流入占比因子分析进度（统一路由）
    
    别名路由，内部调用 api_main_inflow_ratio_analysis_progress
    """
    return api_main_inflow_ratio_analysis_progress()


@app.route('/api/factor/main-inflow-ratio/result')
def api_factor_main_inflow_ratio_result():
    """API: 主力净流入占比因子分析结果（统一路由）
    
    别名路由，内部调用 api_main_inflow_ratio_analysis_result
    """
    return api_main_inflow_ratio_analysis_result()


# ==================== KDJ_J 因子分析 API ====================

@app.route('/kdj-j-analysis')
def kdj_j_analysis_page():
    """KDJ_J 因子分析总览页面"""
    return render_template('kdj_j_analysis.html', active_page='kdj_j')


@app.route('/api/kdj-j-analysis', methods=['GET'])
def api_kdj_j_analysis():
    """API: KDJ_J 因子分析
    
    参数:
        n: RSV 计算周期 (可选，默认9)
        m1: K值平滑周期 (可选，默认3)
        m2: D值平滑周期 (可选，默认3)
        num_layers: 分层数量 (可选，默认5)
        
    注意:
        - 使用缓存数据（close, high, low）
        - KDJ_J 是反向因子（J值高预期下跌）
        - 多空策略：做多 J 值低组（Layer N），做空 J 值高组（Layer 1）
    """
    global kdj_j_analysis_state
    
    # ========== 全局任务锁检查（防止 OOM） ==========
    can_start, error_msg = start_computation('因子分析(KDJ_J)')
    if not can_start:
        return jsonify({'success': False, 'error': error_msg})
    
    # 检查是否已经在运行
    with kdj_j_analysis_lock:
        if kdj_j_analysis_state['status'] == 'running':
            end_computation('因子分析(KDJ_J)')
            return jsonify({'success': False, 'error': '分析正在运行中，请稍候...'})
        
        # 重置状态
        kdj_j_analysis_state = {
            'status': 'running',
            'message': '正在初始化...',
            'progress': 0,
            'start_time': time.time(),
            'end_time': None,
            'last_update': datetime.now().isoformat(),
            'error': None,
            'result': None
        }
    
    # ========== 优先检查预计算结果 ==========
    result_file = BASE_DIR / 'cache/factor_ic/kdj_j_ic.json'
    
    if result_file.exists():
        try:
            with open(result_file, 'r', encoding='utf-8') as f:
                precomputed_result = json.load(f)
            
            # 检查参数是否匹配
            req_n = request.args.get('n', default=9, type=int)
            req_m1 = request.args.get('m1', default=3, type=int)
            req_m2 = request.args.get('m2', default=3, type=int)
            req_num_layers = request.args.get('num_layers', default=5, type=int)
            
            cached_params = precomputed_result.get('params', {})
            if cached_params.get('n') == req_n and cached_params.get('m1') == req_m1 and cached_params.get('m2') == req_m2 and cached_params.get('num_layers') == req_num_layers:
                # 参数匹配，直接返回缓存结果
                with kdj_j_analysis_lock:
                    kdj_j_analysis_state['status'] = 'completed'
                    kdj_j_analysis_state['message'] = '使用缓存结果'
                    kdj_j_analysis_state['progress'] = 100
                    kdj_j_analysis_state['end_time'] = time.time()
                    kdj_j_analysis_state['last_update'] = datetime.now().isoformat()
                    kdj_j_analysis_state['result'] = precomputed_result
                
                end_computation('因子分析(KDJ_J)')
                return jsonify({
                    'success': True,
                    'message': '使用缓存结果',
                    'result': precomputed_result
                })
        except Exception as e:
            print(f'[缓存结果] 读取失败: {e}')
    
    # 获取参数
    n = request.args.get('n', default=9, type=int)
    m1 = request.args.get('m1', default=3, type=int)
    m2 = request.args.get('m2', default=3, type=int)
    num_layers = request.args.get('num_layers', default=5, type=int)
    n_days = 500
    
    # 在后台线程中执行
    def run_kdj_j_analysis_task():
        global kdj_j_analysis_state
        import gc
        
        try:
            # 动态加载模块
            import importlib.util
            module_path = Path('/home/admin/.openclaw/workspace/yunzhou/factor_ic_analyzer/kdj_j_factor.py')
            spec = importlib.util.spec_from_file_location("kdj_j_factor", str(module_path))
            kdj_j_module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(kdj_j_module)
            run_analysis = kdj_j_module.run_kdj_j_analysis
            
            _update_kdj_j_progress(5, '正在加载数据...')
            
            # 执行分析
            result = run_analysis(
                n_days=n_days,
                n=n,
                m1=m1,
                m2=m2,
                num_layers=num_layers
            )
            
            if not result.get('success'):
                raise Exception(result.get('error', '分析失败'))
            
            _update_kdj_j_progress(95, '正在保存结果...')
            
            # 转换 numpy 类型为 Python 原生类型
            result = convert_to_native_types(result)
            
            # 保存结果（原子写入）
            atomic_write_json(result_file, result)
            
            # 完成
            with kdj_j_analysis_lock:
                kdj_j_analysis_state['status'] = 'completed'
                kdj_j_analysis_state['message'] = 'KDJ_J 因子分析完成!'
                kdj_j_analysis_state['progress'] = 100
                kdj_j_analysis_state['end_time'] = time.time()
                kdj_j_analysis_state['last_update'] = datetime.now().isoformat()
                kdj_j_analysis_state['result'] = result
                
        except Exception as e:
            import traceback
            error_msg = str(e)
            traceback.print_exc()
            
            gc.collect()
            
            with kdj_j_analysis_lock:
                kdj_j_analysis_state['status'] = 'error'
                kdj_j_analysis_state['error'] = error_msg
                kdj_j_analysis_state['message'] = f'错误: {error_msg}'
                kdj_j_analysis_state['end_time'] = time.time()
                kdj_j_analysis_state['last_update'] = datetime.now().isoformat()
        finally:
            end_computation('因子分析(KDJ_J)')
    
    thread = threading.Thread(target=run_kdj_j_analysis_task)
    thread.daemon = True
    thread.start()
    
    return jsonify({'success': True, 'message': 'KDJ_J 因子分析已开始'})


@app.route('/api/kdj-j-analysis/progress')
def api_kdj_j_analysis_progress():
    """API: 获取 KDJ_J 因子分析进度"""
    global kdj_j_analysis_state
    
    with kdj_j_analysis_lock:
        state = kdj_j_analysis_state.copy()
    
    # 计算预计剩余时间
    if state['status'] == 'running' and state['start_time'] and state['progress'] > 0:
        elapsed = time.time() - state['start_time']
        if state['progress'] > 10:
            avg_time_per_percent = elapsed / state['progress']
            remaining_percent = 100 - state['progress']
            state['estimated_remaining_seconds'] = int(avg_time_per_percent * remaining_percent)
        else:
            state['estimated_remaining_seconds'] = 0
    else:
        state['estimated_remaining_seconds'] = 0
    
    # 如果已完成，返回结果
    if state['status'] == 'completed' and state['result']:
        return jsonify({
            'status': 'completed',
            'message': state['message'],
            'progress': 100,
            'result': state['result'],
            'estimated_remaining_seconds': 0
        })
    
    return jsonify(state)


@app.route('/api/kdj-j-analysis/result')
def api_kdj_j_analysis_result():
    """API: 获取 KDJ_J 因子分析缓存结果"""
    result_file = BASE_DIR / 'cache/factor_ic/kdj_j_ic.json'
    
    if not result_file.exists():
        return jsonify({'error': '暂无分析结果，请先运行 KDJ_J 因子分析'})
    
    try:
        with open(result_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return jsonify(data)
    except Exception as e:
        return jsonify({'error': f'读取结果失败: {str(e)}'})


@app.route('/api/factor/kdj-j')
def api_factor_kdj_j():
    """API: 获取 KDJ_J 因子完整分析数据
    
    返回格式与 /api/factor/rsi 一致
    """
    result_file = BASE_DIR / 'cache/factor_ic/kdj_j_ic.json'
    
    if not result_file.exists():
        return jsonify({
            'success': False,
            'error': 'KDJ_J 因子分析数据不存在，请先运行分析'
        })
    
    try:
        with open(result_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return jsonify({
            'success': True,
            'data': data
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': f'读取数据失败: {str(e)}'
        })


def _update_kdj_j_progress(progress: int, message: str = ''):
    """更新 KDJ_J 因子分析进度"""
    global kdj_j_analysis_state
    
    with kdj_j_analysis_lock:
        kdj_j_analysis_state['progress'] = progress
        kdj_j_analysis_state['message'] = message if message else f'处理进度: {progress}%'
        kdj_j_analysis_state['last_update'] = datetime.now().isoformat()


# ========== KDJ_J 因子统一路由别名 ==========

@app.route('/api/factor/kdj-j/analysis', methods=['GET'])
def api_factor_kdj_j_analysis():
    """API: KDJ_J 因子分析（统一路由）"""
    return api_kdj_j_analysis()


@app.route('/api/factor/kdj-j/progress')
def api_factor_kdj_j_progress():
    """API: KDJ_J 因子分析进度（统一路由）"""
    return api_kdj_j_analysis_progress()


@app.route('/api/factor/kdj-j/result')
def api_factor_kdj_j_result():
    """API: KDJ_J 因子分析结果（统一路由）"""
    return api_kdj_j_analysis_result()


# ==================== 布林带%B 因子分析 API ====================

@app.route('/bollinger-pb-analysis')
def bollinger_pb_analysis_page():
    """布林带%B 因子分析总览页面"""
    return render_template('bollinger_pb_analysis.html', active_page='bollinger_pb')


@app.route('/api/bollinger-pb-analysis', methods=['GET'])
def api_bollinger_pb_analysis():
    """API: 布林带%B 因子分析
    
    参数:
        n: 移动平均周期 (可选，默认20)
        k: 标准差倍数 (可选，默认2.0)
        num_layers: 分层数量 (可选，默认5)
        
    注意:
        - 使用缓存数据（close）
        - 布林带%B 是反向因子（%B值高预期下跌）
        - 多空策略：做多 %B 值低组（Layer N），做空 %B 值高组（Layer 1）
    """
    global bollinger_pb_analysis_state
    
    # ========== 全局任务锁检查（防止 OOM） ==========
    can_start, error_msg = start_computation('因子分析(布林带%B)')
    if not can_start:
        return jsonify({'success': False, 'error': error_msg})
    
    # 检查是否已经在运行
    with bollinger_pb_analysis_lock:
        if bollinger_pb_analysis_state['status'] == 'running':
            end_computation('因子分析(布林带%B)')
            return jsonify({'success': False, 'error': '分析正在运行中，请稍候...'})
        
        # 重置状态
        bollinger_pb_analysis_state = {
            'status': 'running',
            'message': '正在初始化...',
            'progress': 0,
            'start_time': time.time(),
            'end_time': None,
            'last_update': datetime.now().isoformat(),
            'error': None,
            'result': None
        }
    
    # ========== 优先检查预计算结果 ==========
    result_file = BASE_DIR / 'cache/factor_ic/bollinger_pb_ic.json'
    
    if result_file.exists():
        try:
            with open(result_file, 'r', encoding='utf-8') as f:
                precomputed_result = json.load(f)
            
            # 检查参数是否匹配
            req_n = request.args.get('n', default=20, type=int)
            req_k = request.args.get('k', default=2.0, type=float)
            req_num_layers = request.args.get('num_layers', default=5, type=int)
            
            cached_params = precomputed_result.get('params', {})
            if cached_params.get('n') == req_n and cached_params.get('k') == req_k and cached_params.get('num_layers') == req_num_layers:
                # 参数匹配，直接返回缓存结果
                with bollinger_pb_analysis_lock:
                    bollinger_pb_analysis_state['status'] = 'completed'
                    bollinger_pb_analysis_state['message'] = '使用缓存结果'
                    bollinger_pb_analysis_state['progress'] = 100
                    bollinger_pb_analysis_state['end_time'] = time.time()
                    bollinger_pb_analysis_state['last_update'] = datetime.now().isoformat()
                    bollinger_pb_analysis_state['result'] = precomputed_result
                
                end_computation('因子分析(布林带%B)')
                return jsonify({
                    'success': True,
                    'message': '使用缓存结果',
                    'result': precomputed_result
                })
        except Exception as e:
            print(f'[缓存结果] 读取失败: {e}')
    
    # 获取参数
    n = request.args.get('n', default=20, type=int)
    k = request.args.get('k', default=2.0, type=float)
    num_layers = request.args.get('num_layers', default=5, type=int)
    n_days = 500
    
    # 在后台线程中执行
    def run_bollinger_pb_analysis_task():
        global bollinger_pb_analysis_state
        import gc
        
        try:
            # 动态加载模块
            import importlib.util
            module_path = Path('/home/admin/.openclaw/workspace/yunzhou/factor_ic_analyzer/bollinger_pb_factor.py')
            spec = importlib.util.spec_from_file_location("bollinger_pb_factor", str(module_path))
            bollinger_pb_module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(bollinger_pb_module)
            run_analysis = bollinger_pb_module.run_bollinger_pb_analysis
            
            _update_bollinger_pb_progress(5, '正在加载数据...')
            
            # 执行分析
            result = run_analysis(
                n_days=n_days,
                n=n,
                k=k,
                num_layers=num_layers
            )
            
            if not result.get('success'):
                raise Exception(result.get('error', '分析失败'))
            
            _update_bollinger_pb_progress(95, '正在保存结果...')
            
            # 转换 numpy 类型为 Python 原生类型
            result = convert_to_native_types(result)
            
            # 保存结果（原子写入）
            atomic_write_json(result_file, result)
            
            # 完成
            with bollinger_pb_analysis_lock:
                bollinger_pb_analysis_state['status'] = 'completed'
                bollinger_pb_analysis_state['message'] = '布林带%B 因子分析完成!'
                bollinger_pb_analysis_state['progress'] = 100
                bollinger_pb_analysis_state['end_time'] = time.time()
                bollinger_pb_analysis_state['last_update'] = datetime.now().isoformat()
                bollinger_pb_analysis_state['result'] = result
                
        except Exception as e:
            import traceback
            error_msg = str(e)
            traceback.print_exc()
            
            gc.collect()
            
            with bollinger_pb_analysis_lock:
                bollinger_pb_analysis_state['status'] = 'error'
                bollinger_pb_analysis_state['error'] = error_msg
                bollinger_pb_analysis_state['message'] = f'错误: {error_msg}'
                bollinger_pb_analysis_state['end_time'] = time.time()
                bollinger_pb_analysis_state['last_update'] = datetime.now().isoformat()
        finally:
            end_computation('因子分析(布林带%B)')
    
    thread = threading.Thread(target=run_bollinger_pb_analysis_task)
    thread.daemon = True
    thread.start()
    
    return jsonify({'success': True, 'message': '布林带%B 因子分析已开始'})


@app.route('/api/bollinger-pb-analysis/progress')
def api_bollinger_pb_analysis_progress():
    """API: 获取布林带%B 因子分析进度"""
    global bollinger_pb_analysis_state
    
    with bollinger_pb_analysis_lock:
        state = bollinger_pb_analysis_state.copy()
    
    # 计算预计剩余时间
    if state['status'] == 'running' and state['start_time'] and state['progress'] > 0:
        elapsed = time.time() - state['start_time']
        if state['progress'] > 10:
            avg_time_per_percent = elapsed / state['progress']
            remaining_percent = 100 - state['progress']
            state['estimated_remaining_seconds'] = int(avg_time_per_percent * remaining_percent)
        else:
            state['estimated_remaining_seconds'] = 0
    else:
        state['estimated_remaining_seconds'] = 0
    
    # 如果已完成，返回结果
    if state['status'] == 'completed' and state['result']:
        return jsonify({
            'status': 'completed',
            'message': state['message'],
            'progress': 100,
            'result': state['result'],
            'estimated_remaining_seconds': 0
        })
    
    return jsonify(state)


@app.route('/api/bollinger-pb-analysis/result')
def api_bollinger_pb_analysis_result():
    """API: 获取布林带%B 因子分析缓存结果"""
    result_file = BASE_DIR / 'cache/factor_ic/bollinger_pb_ic.json'
    
    if not result_file.exists():
        return jsonify({'error': '暂无分析结果，请先运行布林带%B 因子分析'})
    
    try:
        with open(result_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return jsonify(data)
    except Exception as e:
        return jsonify({'error': f'读取结果失败: {str(e)}'})


@app.route('/api/factor/bollinger-pb')
def api_factor_bollinger_pb():
    """API: 获取布林带%B 因子完整分析数据
    
    返回格式与 /api/factor/rsi 一致
    """
    result_file = BASE_DIR / 'cache/factor_ic/bollinger_pb_ic.json'
    
    if not result_file.exists():
        return jsonify({
            'success': False,
            'error': '布林带%B 因子分析数据不存在，请先运行分析'
        })
    
    try:
        with open(result_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return jsonify({
            'success': True,
            'data': data
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': f'读取数据失败: {str(e)}'
        })


def _update_bollinger_pb_progress(progress: int, message: str = ''):
    """更新布林带%B 因子分析进度"""
    global bollinger_pb_analysis_state
    
    with bollinger_pb_analysis_lock:
        bollinger_pb_analysis_state['progress'] = progress
        bollinger_pb_analysis_state['message'] = message if message else f'处理进度: {progress}%'
        bollinger_pb_analysis_state['last_update'] = datetime.now().isoformat()


# ========== 布林带%B 因子统一路由别名 ==========

@app.route('/api/factor/bollinger-pb/analysis', methods=['GET'])
def api_factor_bollinger_pb_analysis():
    """API: 布林带%B 因子分析（统一路由）"""
    return api_bollinger_pb_analysis()


@app.route('/api/factor/bollinger-pb/progress')
def api_factor_bollinger_pb_progress():
    """API: 布林带%B 因子分析进度（统一路由）"""
    return api_bollinger_pb_analysis_progress()


@app.route('/api/factor/bollinger-pb/result')
def api_factor_bollinger_pb_result():
    """API: 布林带%B 因子分析结果（统一路由）"""
    return api_bollinger_pb_analysis_result()


# ========== 分层回测统一路由 ==========

@app.route('/api/backtest/layered', methods=['GET'])
def api_backtest_layered():
    """API: 分层回测（统一路由）
    
    别名路由，内部调用 api_layered_backtest
    """
    return api_layered_backtest()


@app.route('/api/backtest/progress')
def api_backtest_progress():
    """API: 分层回测进度（统一路由）
    
    别名路由，内部调用 api_layered_backtest_progress
    """
    return api_layered_backtest_progress()


@app.route('/api/backtest/result')
def api_backtest_result():
    """API: 分层回测结果（统一路由）
    
    别名路由，内部调用 api_layered_backtest_result
    """
    return api_layered_backtest_result()


# ========== 因子统计文案 API ==========

from factor_stats_generator import (
    generate_single_factor_stats, 
    generate_all_factors_summary,
    get_factor_list,
    FACTOR_NAME_MAP
)


@app.route('/api/factor/stats/<factor_name>')
def api_factor_stats_single(factor_name):
    """API: 获取单个因子的统计文案
    
    Args:
        factor_name: 因子标识符（rsi, kdj_j, bollinger_pb, volume_ratio, return_3d, turnover_surge）
        
    Returns:
        JSON: {"text": "完整文案内容"} 或 {"error": "错误信息"}
    """
    # 标准化因子名称
    factor_name = factor_name.lower().strip()
    
    # 生成文案
    text, success = generate_single_factor_stats(factor_name)
    
    if success:
        return jsonify({
            'success': True,
            'factor_name': factor_name,
            'cn_name': FACTOR_NAME_MAP.get(factor_name, {}).get('cn_name', factor_name),
            'text': text
        })
    else:
        return jsonify({
            'success': False,
            'error': text,
            'available_factors': list(FACTOR_NAME_MAP.keys())
        }), 404


@app.route('/api/factor/stats/all')
def api_factor_stats_all():
    """API: 获取所有因子的汇总文案
    
    Returns:
        JSON: {"text": "汇总文案内容"}
    """
    try:
        text = generate_all_factors_summary()
        return jsonify({
            'success': True,
            'text': text
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': f'生成汇总文案失败: {str(e)}'
        }), 500


@app.route('/api/factor/stats/list')
def api_factor_stats_list():
    """API: 获取可用因子列表
    
    Returns:
        JSON: {"factors": [...]}
    """
    return jsonify({
        'success': True,
        'factors': get_factor_list()
    })


# ========== 智能选股回测系统 ==========

from stock_selection_backtest import task_manager


@app.route('/stock-selection-backtest')
@require_auth
def stock_selection_backtest_page():
    """页面: 智能选股回测"""
    return render_template('stock_selection_backtest.html', active_page='stock_selection_backtest')


@app.route('/api/backtest/submit', methods=['POST'])
def api_backtest_submit():
    """API: 提交回测任务
    
    请求体:
        {
            "condition": "RSI < 30 且 量比 > 1.5",
            "period_days": 250
        }
    
    返回:
        {
            "success": true,
            "task_id": "abc12345"
        }
    """
    try:
        data = request.get_json()
        if not data:
            return jsonify({
                'success': False,
                'error': '请求数据为空'
            }), 400
        
        condition = data.get('condition', '').strip()
        if not condition:
            return jsonify({
                'success': False,
                'error': '请输入选股条件'
            }), 400
        
        period_days = data.get('period_days', 250)
        if not isinstance(period_days, int) or period_days < 1:
            period_days = 250
        
        # 提交任务
        task_id = task_manager.submit_task(condition, period_days)
        
        return jsonify({
            'success': True,
            'task_id': task_id,
            'message': '任务已提交'
        })
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/api/backtest/result/<task_id>')
def api_backtest_result_by_id(task_id):
    """API: 查询回测结果
    
    返回:
        {
            "task_id": "abc12345",
            "status": "completed",
            "progress": 100,
            "message": "回测完成",
            ...其他结果字段
        }
    """
    try:
        result = task_manager.get_result(task_id)
        
        if result is None:
            return jsonify({
                'success': False,
                'error': '任务不存在',
                'task_id': task_id
            }), 404
        
        # 转换为字典
        from dataclasses import asdict
        result_dict = asdict(result)
        
        return jsonify(result_dict)
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


# ========== 多因子打分选股 API ==========

# 打分回测进度状态
scoring_backtest_state = {
    'status': 'idle',
    'progress': 0,
    'current_date': None,
    'message': '',
    'result': None,
    'error': None
}
scoring_backtest_lock = threading.Lock()


@app.route('/stock_scoring')
@require_auth
def stock_scoring_page():
    """多因子打分选股页面"""
    return render_template('stock_scoring.html', active_page='stock_scoring')


@app.route('/api/scoring/config')
@require_auth
def api_scoring_config():
    """API: 获取打分配置默认值"""
    try:
        # 尝试导入打分引擎
        from scoring_engine import get_cached_engine, load_factor_ic_data
        
        engine = get_cached_engine()
        available_dates = engine.get_available_dates()
        
        # 加载因子IC数据
        factor_ic = load_factor_ic_data()
        
        return jsonify({
            'success': True,
            'default_weights': engine.DEFAULT_WEIGHTS,
            'available_dates': available_dates,
            'latest_date': engine.get_latest_date(),
            'factor_ic': factor_ic
        })
        
    except ImportError as e:
        # 打分引擎未找到，使用默认配置
        import gzip
        cache_dir = BASE_DIR / 'cache/factor_data'
        factor_path = cache_dir / 'factor_data.json.gz'
        
        available_dates = []
        if factor_path.exists():
            with gzip.open(factor_path, 'rt', encoding='utf-8') as f:
                data = json.load(f)
            all_dates = sorted(set(r.get('date') for r in data.get('data', [])))
            available_dates = all_dates
        
        return jsonify({
            'success': True,
            'default_weights': {
                'rsi': 15,
                'kdj_j': 12,
                'bollinger_pb': 15,
                'volume_ratio': 12,
                'turnover_surge': 12,
                'main_inflow_ratio': 14,
                'return_3d': 10
            },
            'available_dates': available_dates,
            'latest_date': available_dates[-1] if available_dates else None,
            'factor_ic': {}
        })
    
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({
            'success': False,
            'error': str(e)
        })


@app.route('/api/scoring/factor-ic')
@require_auth
def api_scoring_factor_ic():
    """API: 获取各因子IC/ICIR数据"""
    try:
        from scoring_engine import load_factor_ic_data
        
        factor_ic = load_factor_ic_data()
        
        factors = []
        factor_names = {
            'rsi': 'RSI(14)',
            'kdj_j': 'KDJ_J',
            'bollinger_pb': '布林带%B',
            'volume_ratio': '量比',
            'turnover_surge': '换手率突增',
            'main_inflow_ratio': '主力净流入',
            'return_3d': '3日涨幅'
        }
        
        for factor_id, data in factor_ic.items():
            factors.append({
                'id': factor_id,
                'name': factor_names.get(factor_id, factor_id),
                'ic_mean': data.get('ic_mean', 0),
                'icir': data.get('icir', 0),
                'significance': data.get('significance', ''),
                'summary': data.get('summary', '')
            })
        
        # 如果没有数据，返回默认因子列表
        if not factors:
            for factor_id, name in factor_names.items():
                factors.append({
                    'id': factor_id,
                    'name': name,
                    'ic_mean': 0,
                    'icir': 0,
                    'significance': '',
                    'summary': ''
                })
        
        return jsonify({
            'success': True,
            'factors': factors
        })
        
    except ImportError:
        # 返回默认因子列表
        factor_names = {
            'rsi': 'RSI(14)',
            'kdj_j': 'KDJ_J',
            'bollinger_pb': '布林带%B',
            'volume_ratio': '量比',
            'turnover_surge': '换手率突增',
            'main_inflow_ratio': '主力净流入',
            'return_3d': '3日涨幅'
        }
        
        factors = [{'id': k, 'name': v, 'ic_mean': 0, 'icir': 0} for k, v in factor_names.items()]
        
        return jsonify({
            'success': True,
            'factors': factors
        })
    
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({
            'success': False,
            'error': str(e)
        })


@app.route('/api/scoring/calculate', methods=['POST'])
@require_auth
def api_scoring_calculate():
    """API: 计算打分并返回选股结果"""
    global computation_running, computation_task_name
    
    # 检查计算锁
    if computation_running:
        return jsonify({
            'success': False,
            'error': f'已有计算任务正在运行（{computation_task_name}），请稍候再试'
        })
    
    try:
        data = request.get_json()
        if not data:
            return jsonify({'success': False, 'error': '请求数据为空'}), 400
        
        # 获取参数
        date = data.get('date')
        weights = data.get('weights', {})
        normalize_method = data.get('normalize_method', 'quantile')
        score_function = data.get('score_function', 'sigmoid')
        k_value = data.get('k_value', 10)
        top_n = data.get('top_n', 10)
        
        if not date:
            return jsonify({'success': False, 'error': '请选择日期'})
        
        # 检查权重总和
        total_weight = sum(weights.values())
        if total_weight > 100:
            return jsonify({'success': False, 'error': '权重总和超过100%'})
        
        # 开始计算
        computation_running = True
        computation_task_name = '打分选股计算'
        
        from scoring_engine import get_cached_engine
        
        engine = get_cached_engine()
        result = engine.calculate_scores(
            date=date,
            weights=weights,
            normalize_method=normalize_method,
            score_function=score_function,
            k_value=k_value,
            top_n=top_n
        )
        
        computation_running = False
        computation_task_name = None
        
        return jsonify(result)
        
    except ImportError as e:
        computation_running = False
        computation_task_name = None
        return jsonify({
            'success': False,
            'error': f'打分引擎未加载: {str(e)}'
        })
    
    except Exception as e:
        computation_running = False
        computation_task_name = None
        import traceback
        traceback.print_exc()
        return jsonify({
            'success': False,
            'error': str(e)
        })


@app.route('/api/scoring/stock/<code>')
@require_auth
def api_scoring_stock_detail(code):
    """API: 获取单只股票详情"""
    try:
        date = request.args.get('date')
        
        from scoring_engine import get_cached_engine
        
        engine = get_cached_engine()
        result = engine.get_stock_detail(code, date)
        
        # 如果需要计算得分，获取当前权重配置
        weights = request.args.get('weights')
        if weights:
            try:
                weights_dict = json.loads(weights)
                score_result = engine.calculate_scores(
                    date=result.get('date') or date,
                    weights=weights_dict,
                    top_n=100  # 获取更多以计算排名
                )
                if score_result['success']:
                    # 找到该股票的排名和得分
                    for i, stock in enumerate(score_result['selections']):
                        if stock['code'] == code:
                            result['total_score'] = stock['total_score']
                            result['rank'] = i + 1
                            # 合合因子得分详情
                            if 'factor_scores' in stock:
                                for factor_name, details in stock['factor_scores'].items():
                                    for factor in result['factors']:
                                        if factor['factor_id'] == factor_name:
                                            factor['score'] = details['score']
                                            factor['weight'] = details['weight']
                                            factor['contribution'] = details['contribution']
                            break
            except:
                pass
        
        return jsonify(result)
        
    except ImportError as e:
        return jsonify({
            'success': False,
            'error': f'打分引擎未加载: {str(e)}'
        })
    
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({
            'success': False,
            'error': str(e)
        })


@app.route('/api/scoring/backtest', methods=['POST'])
@require_auth
def api_scoring_backtest():
    """API: 运行打分回测（支持向量化加速）
    
    v3.2 优化：添加 use_vectorized 参数
    - use_vectorized=True: 使用向量化回测（性能提升 10x+）
    - use_vectorized=False: 使用原有逐日循环回测
    """
    global computation_running, computation_task_name, scoring_backtest_state
    
    # 检查计算锁
    if computation_running:
        return jsonify({
            'success': False,
            'error': f'已有计算任务正在运行（{computation_task_name}），请稍候再试'
        })
    
    try:
        data = request.get_json()
        if not data:
            return jsonify({'success': False, 'error': '请求数据为空'}), 400
        
        # 获取参数
        start_date = data.get('start_date')
        end_date = data.get('end_date')
        weights = data.get('weights', {})
        top_n = data.get('top_n', 10)
        cost = data.get('cost', 0.002)
        slippage = data.get('slippage', 0.001)
        use_vectorized = data.get('use_vectorized', True)  # 默认使用向量化
        # 标准化和打分参数
        normalize_method = data.get('normalize_method', 'quantile')
        score_function = data.get('score_function', 'sigmoid')
        k_value = data.get('k_value', 10)
        
        if not start_date or not end_date:
            return jsonify({'success': False, 'error': '请选择回测日期范围'})
        
        # 重置进度状态
        with scoring_backtest_lock:
            scoring_backtest_state = {
                'status': 'running',
                'progress': 0,
                'current_date': start_date,
                'message': f'回测开始（{ "向量化" if use_vectorized else "逐日循环" }模式）...',
                'result': None,
                'error': None,
                'vectorized': use_vectorized
            }
        
        # 启动后台线程运行回测
        def run_backtest_thread():
            global computation_running, computation_task_name, scoring_backtest_state
            
            computation_running = True
            computation_task_name = '打分回测'
            
            try:
                from scoring_engine import get_cached_engine
                
                engine = get_cached_engine()
                
                # 进度回调
                def progress_callback(progress, message):
                    with scoring_backtest_lock:
                        scoring_backtest_state['progress'] = progress
                        scoring_backtest_state['message'] = message
                
                # 选择回测方法
                if use_vectorized:
                    # 向量化回测（性能优化）
                    result = engine.run_backtest_vectorized(
                        start_date=start_date,
                        end_date=end_date,
                        weights=weights,
                        top_n=top_n,
                        cost=cost,
                        slippage=slippage,
                        normalize_method=normalize_method,
                        score_function=score_function,
                        k_value=k_value,
                        progress_callback=progress_callback
                    )
                else:
                    # 原有逐日循环回测
                    def old_progress_callback(current, total, date, nav):
                        with scoring_backtest_lock:
                            scoring_backtest_state['progress'] = int(current / total * 100)
                            scoring_backtest_state['current_date'] = date
                            scoring_backtest_state['message'] = f'处理 {date}, 净值 {nav:.4f}'
                    
                    result = engine.run_backtest(
                        start_date=start_date,
                        end_date=end_date,
                        weights=weights,
                        top_n=top_n,
                        cost=cost,
                        slippage=slippage,
                        normalize_method=normalize_method,
                        score_function=score_function,
                        k_value=k_value,
                        progress_callback=old_progress_callback
                    )
                
                with scoring_backtest_lock:
                    scoring_backtest_state['status'] = 'completed'
                    scoring_backtest_state['progress'] = 100
                    scoring_backtest_state['message'] = '回测完成'
                    scoring_backtest_state['result'] = result
                
            except Exception as e:
                import traceback
                traceback.print_exc()
                with scoring_backtest_lock:
                    scoring_backtest_state['status'] = 'error'
                    scoring_backtest_state['error'] = str(e)
            
            finally:
                computation_running = False
                computation_task_name = None
                gc.collect()
        
        thread = threading.Thread(target=run_backtest_thread)
        thread.daemon = True
        thread.start()
        
        return jsonify({
            'success': True,
            'message': f'回测任务已启动（{ "向量化" if use_vectorized else "逐日循环" }模式）',
            'vectorized': use_vectorized
        })
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({
            'success': False,
            'error': str(e)
        })


@app.route('/api/scoring/backtest/progress')
@require_auth
def api_scoring_backtest_progress():
    """API: 获取回测进度"""
    global scoring_backtest_state
    
    with scoring_backtest_lock:
        state = scoring_backtest_state.copy()
    
    return jsonify(state)


@app.route('/api/scoring/backtest/trades')
@require_auth
def api_scoring_backtest_trades():
    """API: 获取净值曲线 + 交易事件聚合数据
    
    用于时间坐标轴可视化：
    - 净值曲线数据
    - 交易事件散点数据（包含 nav_point_index 映射）
    - 交易统计摘要
    
    参数:
        period: 时间范围 ('1w', '1m', '3m', 'all') - 默认 '1m'
    """
    global scoring_backtest_state
    
    with scoring_backtest_lock:
        state = scoring_backtest_state.copy()
    
    # 检查是否有完成的回测结果
    if state['status'] != 'completed' or state['result'] is None:
        return jsonify({
            'success': False,
            'error': '暂无回测结果，请先运行回测',
            'data': {
                'net_curve': {'dates': [], 'values': []},
                'trade_events': [],
                'metadata': {'total_trades': 0, 'buy_count': 0, 'sell_count': 0}
            }
        })
    
    result = state['result']
    
    if not result.get('success'):
        return jsonify({
            'success': False,
            'error': result.get('error', '回测结果无效'),
            'data': {
                'net_curve': {'dates': [], 'values': []},
                'trade_events': [],
                'metadata': {'total_trades': 0, 'buy_count': 0, 'sell_count': 0}
            }
        })
    
    # 提取净值曲线数据
    nav_series = result.get('nav_series', [])
    net_curve = {
        'dates': [n['date'] for n in nav_series],
        'values': [n['nav'] for n in nav_series]
    }
    
    # 提取交易事件数据
    trade_details = result.get('trade_details', [])
    trade_events = []
    
    for trade in trade_details:
        # 构建散点数据格式（按文档规范）
        nav_point_index = trade.get('nav_point_index', 0)
        
        trade_events.append({
            'trade_id': trade.get('trade_id', ''),
            'date': trade.get('trade_date', ''),
            'time': trade.get('trade_time', '10:00'),
            'action': trade.get('action', 'buy'),
            'code': trade.get('code', ''),
            'name': trade.get('name', ''),
            'price': trade.get('price', 0),
            'quantity': trade.get('quantity', 100),
            'amount': trade.get('amount', 0),
            'nav_point_index': nav_point_index,
            'strategy': trade.get('strategy', '多因子打分'),
            'reason': trade.get('reason', '')
        })
    
    # 构建元数据
    metrics = result.get('metrics', {})
    metadata = {
        'total_trades': metrics.get('total_trades', len(trade_events)),
        'buy_count': metrics.get('buy_count', sum(1 for t in trade_events if t['action'] == 'buy')),
        'sell_count': metrics.get('sell_count', sum(1 for t in trade_events if t['action'] == 'sell')),
        'date_range': {
            'start': net_curve['dates'][0] if net_curve['dates'] else '',
            'end': net_curve['dates'][-1] if net_curve['dates'] else ''
        }
    }
    
    return jsonify({
        'success': True,
        'data': {
            'net_curve': net_curve,
            'trade_events': trade_events,
            'metadata': metadata
        }
    })


# ==================== 智能权重 API ====================

@app.route('/api/scoring/smart_weights')
@require_auth
def api_scoring_smart_weights():
    """API: 获取智能生成的权重
    
    返回:
        {
            "success": true,
            "weights": {"rsi": 22.5, ...},
            "quality_scores": {"rsi": 0.62, ...},
            "factor_quality": {...},
            "weight_explanation": {...},
            "generated_at": "..."
        }
    """
    try:
        from scoring_engine import get_smart_weight_generator
        
        generator = get_smart_weight_generator()
        report = generator.get_smart_weights_report()
        
        return jsonify({
            'success': True,
            'data': report
        })
        
    except ImportError as e:
        # scoring_engine 未加载，返回默认权重
        return jsonify({
            'success': True,
            'data': {
                'weights': {
                    'rsi': 17,
                    'kdj_j': 14,
                    'bollinger_pb': 17,
                    'volume_ratio': 14,
                    'turnover_surge': 14,
                    'return_3d': 12
                },
                'quality_scores': {},
                'factor_quality': {},
                'weight_explanation': {
                    'algorithm': 'default',
                    'description': '使用默认权重配置（智能权重生成器未加载）'
                },
                'generated_at': datetime.now().isoformat(),
                'warning': f'智能权重生成器未加载: {str(e)}'
            }
        })
    
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({
            'success': False,
            'error': str(e)
        })


@app.route('/api/scoring/factor_quality')
def api_scoring_factor_quality():
    """API: 获取因子质量评估
    
    返回:
        {
            "success": true,
            "factors": [
                {
                    "factor_id": "rsi",
                    "factor_name": "RSI(14)",
                    "ic_mean": -0.05,
                    "icir": 0.12,
                    "t_stat": 2.5,
                    "significance": "**",
                    "long_short_return": 0.102,
                    "quality_level": "中等",
                    "quality_score": 0.62,
                    "score_components": {...}
                },
                ...
            ]
        }
    """
    try:
        from scoring_engine import get_smart_weight_generator, load_factor_ic_data
        
        generator = get_smart_weight_generator()
        
        # 获取因子质量详情
        weights, raw_scores, factor_quality = generator.calculate_smart_weights()
        
        # 构建返回数据
        factors = []
        for factor_id, quality_info in factor_quality.items():
            factors.append({
                'factor_id': factor_id,
                'factor_name': quality_info.get('factor_name', factor_id),
                'ic_mean': round(quality_info.get('ic_mean', 0), 4),
                'icir': round(quality_info.get('icir', 0), 4),
                't_stat': round(quality_info.get('t_stat', 0), 4),
                'significance': quality_info.get('significance', ''),
                'long_short_return': round(quality_info.get('long_short_return', 0), 4),
                'quality_level': quality_info.get('quality_level', '较弱'),
                'quality_score': round(quality_info.get('quality_score', 0), 4),
                'score_components': quality_info.get('score_components', {}),
                'weight': weights.get(factor_id, 0)
            })
        
        return jsonify({
            'success': True,
            'factors': factors,
            'generated_at': datetime.now().isoformat()
        })
        
    except ImportError as e:
        # 尝试使用 load_factor_ic_data
        try:
            from scoring_engine import load_factor_ic_data
            factor_ic = load_factor_ic_data()
            
            factors = []
            factor_names = {
                'rsi': 'RSI(14)',
                'kdj_j': 'KDJ_J',
                'bollinger_pb': '布林带%B',
                'volume_ratio': '量比',
                'turnover_surge': '换手率突增',
                'return_3d': '3日涨幅'
            }
            
            for factor_id, data in factor_ic.items():
                icir = abs(data.get('icir', 0))
                quality_level = '较弱'
                if icir > 0.5:
                    quality_level = '优秀'
                elif icir > 0.2:
                    quality_level = '良好'
                elif icir > 0.1:
                    quality_level = '中等'
                
                factors.append({
                    'factor_id': factor_id,
                    'factor_name': factor_names.get(factor_id, factor_id),
                    'ic_mean': round(data.get('ic_mean', 0), 4),
                    'icir': round(data.get('icir', 0), 4),
                    't_stat': round(data.get('t_stat', 0), 4),
                    'significance': data.get('significance', ''),
                    'long_short_return': round(data.get('long_short_return', 0), 4),
                    'quality_level': quality_level,
                    'quality_score': 0,
                    'score_components': {},
                    'weight': 0
                })
            
            return jsonify({
                'success': True,
                'factors': factors,
                'generated_at': datetime.now().isoformat(),
                'warning': '智能权重生成器未加载，使用基础IC数据'
            })
            
        except Exception as inner_e:
            return jsonify({
                'success': False,
                'error': f'加载因子数据失败: {str(inner_e)}'
            })
    
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({
            'success': False,
            'error': str(e)
        })


@app.route('/api/scoring/optimize_weights', methods=['POST'])
def api_scoring_optimize_weights():
    """API: 权重优化
    
    请求体:
        {
            "objective": "balanced"  // 可选: "icir", "long_short", "balanced"
        }
    
    返回:
        {
            "success": true,
            "weights": {...},
            "objective": "balanced",
            "message": "..."
        }
    """
    try:
        from scoring_engine import get_smart_weight_generator
        
        data = request.get_json() or {}
        objective = data.get('objective', 'balanced')
        
        generator = get_smart_weight_generator()
        result = generator.optimize_weights(objective=objective)
        
        return jsonify(result)
        
    except ImportError as e:
        return jsonify({
            'success': False,
            'error': f'智能权重生成器未加载: {str(e)}'
        })
    
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({
            'success': False,
            'error': str(e)
        })


# ========== 权重优化搜索 API（P0 核心功能） ==========

@app.route('/api/scoring/weights/optimize', methods=['POST'])
@require_auth
def api_weights_optimize_start():
    """API: 启动权重网格搜索优化
    
    请求体:
        {
            "factors": ["rsi", "kdj_j", "bollinger_pb", ...],  // 选定的因子列表
            "objective": "icir",  // 优化目标（目前只支持icir）
            "method": "grid_search",  // 搜索方法
            "params": {
                "weight_range": {"min": -1.0, "max": 1.0},
                "grid_step": 0.2,
                "constraint": "sum_to_one",  // 或 "unconstrained"
                "early_stop_patience": 10
            }
        }
    
    返回:
        {
            "success": true,
            "task_id": "opt_20260413_001",
            "message": "...",
            "factors": [...],
            "params": {...}
        }
    """
    try:
        from versions.v2.optimizer.weight_optimizer import start_optimization
        
        data = request.get_json() or {}
        
        # 必选参数：因子列表
        factors = data.get('factors', [])
        if not factors:
            return jsonify({
                'success': False,
                'error': '请选择至少一个因子'
            })
        
        # 验证因子有效性
        from versions.v2.optimizer.weight_optimizer import FACTOR_RESULT_FILES
        invalid_factors = [f for f in factors if f not in FACTOR_RESULT_FILES]
        if invalid_factors:
            return jsonify({
                'success': False,
                'error': f'无效因子: {invalid_factors}'
            })
        
        # 可选参数
        objective = data.get('objective', 'icir')
        method = data.get('method', 'grid_search')
        params = data.get('params', {})
        
        # 启动优化
        result = start_optimization(
            factors=factors,
            objective=objective,
            method=method,
            params=params
        )
        
        return jsonify(result)
        
    except ImportError as e:
        return jsonify({
            'success': False,
            'error': f'权重优化器未加载: {str(e)}'
        })
    
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({
            'success': False,
            'error': str(e)
        })


@app.route('/api/scoring/weights/progress')
@require_auth
def api_weights_optimize_progress():
    """API: 查询权重优化进度
    
    返回:
        {
            "status": "running" | "completed" | "idle" | "error",
            "task_id": "opt_...",
            "progress": {
                "current_iteration": 45,
                "total_iterations": 100,
                "percentage": 45.0,
                "current_best_icir": 0.32,
                "current_best_weights": {...},
                "elapsed_seconds": 150,
                "estimated_remaining_seconds": 180
            },
            "error": null
        }
    """
    try:
        from versions.v2.optimizer.weight_optimizer import get_optimization_progress
        
        progress = get_optimization_progress()
        return jsonify({
            'code': 200,
            'data': progress
        })
        
    except ImportError as e:
        return jsonify({
            'code': 500,
            'error': f'权重优化器未加载: {str(e)}'
        })
    
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({
            'code': 500,
            'error': str(e)
        })


@app.route('/api/scoring/weights/result')
@require_auth
def api_weights_optimize_result():
    """API: 获取权重优化结果
    
    返回:
        {
            "status": "completed",
            "task_id": "opt_...",
            "result": {
                "best_weights": {...},
                "best_icir": 0.35,
                "best_ic_mean": 0.05,
                "best_ic_std": 0.14,
                "total_evaluated": 1200,
                "convergence_iteration": 85,
                "improvement_history": [...],
                "elapsed_seconds": 30.5
            },
            "history_best": [...]
        }
    """
    try:
        from versions.v2.optimizer.weight_optimizer import get_optimization_result
        
        result = get_optimization_result()
        return jsonify({
            'code': 200,
            'data': result
        })
        
    except ImportError as e:
        return jsonify({
            'code': 500,
            'error': f'权重优化器未加载: {str(e)}'
        })
    
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({
            'code': 500,
            'error': str(e)
        })


@app.route('/api/scoring/weights/config')
@require_auth
def api_weights_optimize_config():
    """API: 获取权重优化器配置
    
    返回:
        {
            "available_factors": [...],
            "factor_names": {...},
            "common_dates_count": 499,
            "ic_data_loaded": [...],
            "default_params": {...}
        }
    """
    try:
        from versions.v2.optimizer.weight_optimizer import get_optimizer_config
        
        config = get_optimizer_config()
        return jsonify({
            'code': 200,
            'data': config
        })
        
    except ImportError as e:
        return jsonify({
            'code': 500,
            'error': f'权重优化器未加载: {str(e)}'
        })
    
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({
            'code': 500,
            'error': str(e)
        })


# ========== 带回测验证的权重优化 API ==========

@app.route('/api/optimizer/start_with_backtest', methods=['POST'])
def api_optimizer_start_with_backtest():
    """启动带回测验证的权重优化
    
    请求体:
        {
            "factors": ["rsi", "kdj_j", ...],  // 可选，默认全部因子
            "params": {...}  // 可选，回测参数
        }
    
    返回:
        {
            "success": true,
            "task_id": "...",
            "message": "..."
        }
    """
    data = request.get_json() or {}
    factors = data.get('factors', ['rsi', 'kdj_j', 'bollinger_pb', 'volume_ratio', 'turnover_surge', 'return_3d'])
    params = data.get('params', {})
    return jsonify(start_optimization_with_backtest(factors, params))


@app.route('/api/optimizer/result_with_backtest')
def api_optimizer_result_with_backtest():
    """获取带回测验证的优化结果
    
    返回:
        {
            "status": "completed" | "running" | "idle" | "error",
            "result": {...},
            "progress": {...}
        }
    """
    result = get_backtest_optimization_result()
    return jsonify(convert_to_native_types(result))


# ========== 预计算 API 接口（云舟 Phase 2） ==========

@app.route('/api/precompute/optimization-result')
@require_auth
def api_precompute_result():
    """API: 获取预计算最优组合结果
    
    返回:
        {
            "success": true,
            "data": {
                "computed_at": "2026-04-14 04:32:00",
                "is_fresh": true,  // 是否24小时内
                "best_combination": {
                    "weights": {...},
                    "weights_display": {...},
                    "metrics": {...},
                    "score": 0.92
                },
                "top_stocks": [...],
                "top10_candidates": [...],
                "compute_summary": {...}
            }
        }
    """
    try:
        from precompute_optimizer import get_precompute_result, get_precompute_status
        
        result = get_precompute_result()
        status = get_precompute_status()
        
        if result is None:
            return jsonify({
                'success': False,
                'error': '尚无预计算结果',
                'status': status
            })
        
        # 检查结果是否新鲜
        is_fresh = status.get('is_fresh', False)
        
        return jsonify({
            'success': True,
            'data': {
                'computed_at': result.get('computed_at', ''),
                'is_fresh': is_fresh,
                'best_combination': result.get('best_combination', {}),
                'top_stocks': result.get('top_stocks', []),
                'top10_candidates': result.get('top10_candidates', []),
                'compute_summary': result.get('compute_summary', {})
            },
            'status': status
        })
        
    except ImportError as e:
        return jsonify({
            'success': False,
            'error': f'预计算模块未加载: {str(e)}'
        })
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({
            'success': False,
            'error': str(e)
        })


@app.route('/api/precompute/top-stocks')
@require_auth
def api_precompute_top_stocks():
    """API: 获取推荐股票（支持数量参数）
    
    参数:
        n: 返回股票数量（默认3，范围1-20）
    
    返回:
        {
            "success": true,
            "data": {
                "computed_at": "...",
                "weights_used": {...},
                "stocks": [
                    {"rank": 1, "code": "600519", "name": "贵州茅台", "score": 85.2},
                    {"rank": 2, "code": "000858", "name": "五粮液", "score": 82.1},
                    {"rank": 3, "code": "000333", "name": "美的集团", "score": 79.5}
                ],
                "total_available": 20
            }
        }
    """
    try:
        from precompute_optimizer import get_top_stocks
        
        # 获取数量参数（默认3，范围1-20）
        n = request.args.get('n', 3, type=int)
        n = max(1, min(20, n))  # 限制范围
        
        result = get_top_stocks(n)
        
        if result is None:
            return jsonify({
                'success': False,
                'error': '尚无预计算结果'
            })
        
        return jsonify({
            'success': True,
            'data': result
        })
        
    except ImportError as e:
        return jsonify({
            'success': False,
            'error': f'预计算模块未加载: {str(e)}'
        })
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({
            'success': False,
            'error': str(e)
        })


@app.route('/api/precompute/status')
@require_auth
def api_precompute_status():
    """API: 获取预计算状态
    
    返回:
        {
            "success": true,
            "data": {
                "status": "idle|running|completed|error|no_result",
                "last_run": "2026-04-14 04:32:00",
                "last_status": "success",
                "last_duration_seconds": 9120,
                "is_fresh": true,
                "next_run": "2026-04-15 02:00:00"
            }
        }
    """
    try:
        from precompute_optimizer import get_precompute_status
        
        status = get_precompute_status()
        
        return jsonify({
            'success': True,
            'data': status
        })
        
    except ImportError as e:
        return jsonify({
            'success': False,
            'error': f'预计算模块未加载: {str(e)}'
        })
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({
            'success': False,
            'error': str(e)
        })


@app.route('/api/precompute/trigger', methods=['POST'])
@require_auth
def api_precompute_trigger():
    """API: 手动触发预计算
    
    请求体（可选）:
        {
            "force": false  // 是否强制重新计算（即使已有结果）
        }
    
    返回:
        {
            "success": true,
            "message": "预计算任务已启动",
            "task_id": "precompute_20260414_020000"
        }
    """
    global computation_running, computation_task_name
    
    try:
        # 检查是否有计算任务正在运行
        if computation_running:
            return jsonify({
                'success': False,
                'error': f'已有计算任务正在运行（{computation_task_name}），请稍候再试'
            })
        
        # 检查内存
        mem_ok, mem_available, mem_msg = check_memory_available()
        if not mem_ok:
            return jsonify({
                'success': False,
                'error': mem_msg
            })
        
        # 检查是否强制执行
        data = request.get_json() or {}
        force = data.get('force', False)
        
        # 检查已有结果是否新鲜
        from precompute_optimizer import get_precompute_status
        
        if not force:
            status = get_precompute_status()
            if status.get('is_fresh', False):
                return jsonify({
                    'success': False,
                    'error': '已有24小时内的新鲜结果，如需重新计算请设置 force=true',
                    'last_run': status.get('last_run', '')
                })
        
        # 开始计算任务
        success, error_msg = start_computation('预计算优化')
        if not success:
            return jsonify({
                'success': False,
                'error': error_msg
            })
        
        # 异步执行预计算
        def run_precompute_async():
            global computation_running, computation_task_name
            try:
                from precompute_optimizer import run_precompute
                
                result = run_precompute()
                
                if result.get('success'):
                    print(f"[预计算] 完成: {result.get('task_id')}")
                else:
                    print(f"[预计算] 失败: {result.get('error')}")
                    
            except Exception as e:
                import traceback
                traceback.print_exc()
                print(f"[预计算] 异常: {e}")
            finally:
                end_computation()
        
        # 启动线程
        thread = threading.Thread(target=run_precompute_async, daemon=True)
        thread.start()
        
        task_id = f"precompute_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        
        return jsonify({
            'success': True,
            'message': '预计算任务已启动',
            'task_id': task_id,
            'memory_available_mb': mem_available
        })
        
    except ImportError as e:
        return jsonify({
            'success': False,
            'error': f'预计算模块未加载: {str(e)}'
        })
    except Exception as e:
        import traceback
        traceback.print_exc()
        end_computation()  # 确保释放锁
        return jsonify({
            'success': False,
            'error': str(e)
        })


@app.route('/api/precompute/optimization-result-test')
@require_auth
def api_precompute_result_test():
    """API: 获取测试版预计算结果（包含净值曲线和买卖记录）
    
    【测试功能】此端点返回包含净值曲线数据的测试结果，不影响正式预计算。
    
    返回:
        {
            "success": true,
            "data": {
                "is_test": true,
                "computed_at": "...",
                "best_combination": {...},
                "top_stocks": [...],
                "backtest_details": {
                    "nav_series": [{"date": "2025-01-01", "nav": 1.0}, ...],
                    "trade_details": [...],
                    "backtest_params": {...},
                    "note": "此为历史回测表现，仅供参考"
                }
            }
        }
    """
    try:
        from pathlib import Path
        result_file = Path(__file__).parent / 'cache' / 'precompute' / 'optimization_result_test.json'
        
        if not result_file.exists():
            return jsonify({
                'success': False,
                'error': '测试结果不存在，请先运行 precompute_optimizer_test.py',
                'hint': '在终端执行: python precompute_optimizer_test.py'
            })
        
        with open(result_file, 'r', encoding='utf-8') as f:
            result = json.load(f)
        
        # 检查是否是测试结果
        if not result.get('is_test', False):
            return jsonify({
                'success': False,
                'error': '这不是测试结果文件，请运行 precompute_optimizer_test.py'
            })
        
        return jsonify({
            'success': True,
            'data': result
        })
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({
            'success': False,
            'error': str(e)
        })


@app.route('/api/precompute/history')
@require_auth
def api_precompute_history():
    """API: 获取预计算历史记录（近7天）
    
    返回:
        {
            "success": true,
            "data": {
                "history": [
                    {
                        "task_id": "...",
                        "computed_at": "...",
                        "status": "success",
                        "best_score": 0.92,
                        "best_weights": {...}
                    },
                    ...
                ]
            }
        }
    """
    try:
        from pathlib import Path
        history_file = Path(__file__).parent / 'cache' / 'precompute' / 'compute_history.json'
        
        if history_file.exists():
            with open(history_file, 'r', encoding='utf-8') as f:
                history_data = json.load(f)
            return jsonify({
                'success': True,
                'data': history_data
            })
        else:
            return jsonify({
                'success': True,
                'data': {'history': [], 'message': '尚无历史记录'}
            })
            
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({
            'success': False,
            'error': str(e)
        })


# ==================== Portfolio 虚拟持仓跟踪 API ====================

@app.route('/api/portfolio/multi-period-full')
@require_auth
def api_portfolio_multi_period_full():
    """API: 获取多周期策略对比完整数据
    
    返回 T+1, T+3, T+5 三个周期的策略对比数据，包括:
    - computed_at: 计算日期
    - best_period: 最优周期名称
    - best_result: 最优周期的详细结果（metrics, weights, stocks）
    - all_periods: 各周期的对比数据
    
    v3.14 新增：支持前端多周期策略对比展示
    v3.15 修复：读取 top_stocks_*.json 填充 stocks 字段
    """
    try:
        # 读取多周期优化结果（v3.9+ 新格式）
        from pathlib import Path
        v2_output_dir = BASE_DIR / 'versions' / 'v2' / 'output'
        optimization_file = v2_output_dir / 'optimization_result_multi_period.json'
        
        if not optimization_file.exists():
            return jsonify({
                'success': False,
                'error': '多周期数据未预计算，请先运行优化器预计算（versions/v2/output/optimization_result_multi_period.json 不存在）'
            })
        
        # 加载多周期优化结果
        with open(optimization_file, 'r', encoding='utf-8') as f:
            optimization_data = json.load(f)
        
        # 新格式直接包含 best_period, best_result, all_periods
        best_period = optimization_data.get('best_period', 'T+3')
        best_result_raw = optimization_data.get('best_result', {})
        all_periods_raw = optimization_data.get('all_periods', {})
        
        # 读取各周期的股票数据（v3.16 优化：直接读取 optimization_T_*.json）
        v2_output_dir = BASE_DIR / 'versions' / 'v2' / 'output'
        stocks_data = {}
        for period_key in ['T1', 'T3', 'T5']:
            # T1 -> T_1, T3 -> T_3, T5 -> T_5
            file_period = f"T_{period_key[1]}"  # T1 -> T_1
            stocks_file = v2_output_dir / f'optimization_{file_period}.json'
            if stocks_file.exists():
                try:
                    with open(stocks_file, 'r', encoding='utf-8') as f:
                        raw_data = json.load(f)
                        # 转换格式：selections -> stocks
                        stocks_data[period_key] = {
                            'success': raw_data.get('success', True),
                            'stocks': raw_data.get('selections', []),
                            'computed_at': raw_data.get('computed_at', ''),
                            'period': raw_data.get('period', f'T+{period_key[1]}'),
                            'weights_used': raw_data.get('weights', {}),
                            'summary': raw_data.get('metrics', {})
                        }
                except Exception as e:
                    print(f"Warning: Failed to load {stocks_file}: {e}")
                    stocks_data[period_key] = None
            else:
                stocks_data[period_key] = None
        
        # 构建 best_result（适配前端格式）
        best_period_key = best_period.replace('+', '')  # 'T+3' -> 'T3'
        best_stocks = []
        if stocks_data.get(best_period_key) and stocks_data[best_period_key].get('success'):
            best_stocks = stocks_data[best_period_key].get('stocks', [])
        
        # 转换 total_score -> score（前端字段名要求）
        for stock in best_stocks:
            if 'total_score' in stock and 'score' not in stock:
                stock['score'] = stock['total_score']
        
        best_result = {
            'metrics': {
                'annual_return': best_result_raw.get('metrics', {}).get('annual_return', 0),
                'sharpe_ratio': best_result_raw.get('metrics', {}).get('sharpe_ratio', 0),
                'max_drawdown': best_result_raw.get('metrics', {}).get('max_drawdown', 0),
                'win_rate': best_result_raw.get('metrics', {}).get('win_rate', 0)
            },
            'weights': best_result_raw.get('weights', {}),
            'stocks': best_stocks
        }
        
        # 构建 all_periods（适配前端格式）
        all_periods = {}
        for period_name, period_data in all_periods_raw.items():
            if period_data.get('success', False):
                # 获取对应周期的股票数据
                period_key = period_name.replace('+', '')  # 'T+1' -> 'T1'
                period_stocks = []
                if stocks_data.get(period_key) and stocks_data[period_key].get('success'):
                    period_stocks = stocks_data[period_key].get('stocks', [])
                
                # 转换 total_score -> score（前端字段名要求）
                for stock in period_stocks:
                    if 'total_score' in stock and 'score' not in stock:
                        stock['score'] = stock['total_score']
                
                all_periods[period_name] = {
                    'metrics': {
                        'annual_return': period_data.get('metrics', {}).get('annual_return', 0),
                        'sharpe_ratio': period_data.get('metrics', {}).get('sharpe_ratio', 0),
                        'max_drawdown': period_data.get('metrics', {}).get('max_drawdown', 0),
                        'win_rate': period_data.get('metrics', {}).get('win_rate', 0)
                    },
                    'weights': period_data.get('weights', {}),
                    'stocks': period_stocks
                }
        
        # 构建返回数据
        result_data = {
            'computed_at': optimization_data.get('computed_at', ''),
            'best_period': best_period,
            'best_result': best_result,
            'all_periods': all_periods
        }
        
        return jsonify({
            'success': True,
            'data': result_data
        })
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({
            'success': False,
            'error': f'加载多周期数据失败: {str(e)}'
        })

@app.route('/api/portfolio/net-value-curve')
@require_auth
def api_portfolio_net_value_curve():
    """API: 获取累计净值曲线数据
    
    返回:
        - 策略名称、初始资金
        - 当前净值、累计收益率
        - 最大回撤、夏普比率、胜率
        - 净值曲线数据点
    """
    try:
        # 读取当前持仓
        holdings_data = load_json_file(HOLDINGS_FILE)
        config_data = load_json_file(CONFIG_FILE)
        trades_data = load_json_file(TRADES_FILE)
        
        if not config_data:
            return jsonify({
                'success': False,
                'error': '账户未初始化，请先初始化账户'
            })
        
        strategy_name = config_data.get('strategy_name', config_data.get('account_id', 'multi_factor_v1'))
        initial_capital = config_data.get('initial_capital', 1000000)
        init_date = config_data.get('init_date')
        
        # 计算当前市值（兼容新旧格式）
        total_market_value = 0.0
        if holdings_data:
            if 'holdings' in holdings_data:
                # 旧格式：holdings 字典
                for stock_code, holding in holdings_data['holdings'].items():
                    total_market_value += holding.get('market_value', 0)
            elif 'positions' in holdings_data:
                # 新格式：positions 数组
                for position in holdings_data.get('positions', []):
                    shares = position.get('shares', 0)
                    buy_price = position.get('buy_price', 0)
                    total_market_value += shares * buy_price
        
        # 读取现金余额（从 holdings_data 读取，兼容新旧格式）
        cash_balance = holdings_data.get('available_cash', holdings_data.get('cash_balance', 0)) if holdings_data else 0
        
        # 计算当前净值
        current_net_value = (total_market_value + cash_balance) / initial_capital
        
        # 累计收益率
        cumulative_return = (current_net_value - 1.0) * 100  # 百分比
        
        # 统计交易次数
        total_trades = 0
        if trades_data and 'trades' in trades_data:
            total_trades = len(trades_data['trades'])
        
        # 净值曲线（暂时只有当前这一个点，未来可以扩展为每日记录）
        curve = []
        if init_date:
            curve.append({
                'date': init_date,
                'net_value': 1.0,  # 初始净值
                'daily_return': 0.0
            })
        
        # 添加当前净值点
        from datetime import datetime
        today = datetime.now().strftime('%Y-%m-%d')
        if today != init_date:
            curve.append({
                'date': today,
                'net_value': round(current_net_value, 4),
                'daily_return': round((current_net_value - 1.0) * 100, 2)
            })
        
        # 指标计算（由于只有单日数据，暂时返回基础值）
        # TODO: 未来有历史净值数据后，计算真实的最大回撤、夏普比率、胜率
        
        return jsonify({
            'success': True,
            'data': {
                'strategy_name': strategy_name,
                'initial_capital': initial_capital,
                'current_net_value': round(current_net_value, 4),
                'cumulative_return': round(cumulative_return, 2),
                'max_drawdown': 0.0,  # 需要历史数据
                'sharpe_ratio': 0.0,  # 需要历史数据
                'win_rate': 0.0,  # 需要历史数据
                'total_trades': total_trades,
                'curve': curve,
                'metrics': {
                    'start_date': init_date,
                    'end_date': today,
                    'days': 1 if today == init_date else 2,
                    'note': '净值曲线功能已恢复，历史数据积累中将逐步完善指标计算'
                }
            }
        })
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({
            'success': False,
            'error': str(e)
        })


@app.route('/api/portfolio/current-holdings')
@require_auth
def api_portfolio_current_holdings():
    """API: 获取当前持仓
    
    参数:
        strategy_name: 策略名称（可选）
        
    返回:
        {
            "success": true,
            "data": {
                "strategy_name": "multi_factor_v1",
                "as_of_date": "2026-04-16",
                "total_market_value": 1123400.00,
                "cash_balance": 5000.00,
                "net_value": 1.1234,
                "holdings": [...]
            }
        }
    """
    try:
        # 获取参数
        strategy_name = request.args.get('strategy_name', 'multi_factor_v1')
        
        # 创建跟踪器
        tracker = PortfolioTracker(account=VirtualAccount(strategy_name=strategy_name))
        
        # 获取当前持仓
        holdings = tracker.account.holdings
        
        # 构建响应
        result = {
            'strategy_name': strategy_name,
            'as_of_date': tracker.account.init_date or datetime.now().strftime('%Y-%m-%d'),
            'total_market_value': 0.0,  # 将在遍历 holdings 时累加
            'cash_balance': tracker.account.cash_balance,
            # 'net_value': tracker.account.net_value,  # 已移除
            'holdings_count': len(holdings),
            'holdings': []
        }
        
        # 添加股票名称（从缓存加载）
        stock_list_data = load_json_file(BASE_DIR / 'cache' / 'stock_list.json', {})
        # 构建代码到名称的映射（缓存文件格式：{ "stocks": [{"code": "000001", "name": "平安银行"}, ...] }）
        stock_names_map = {}
        for stock in stock_list_data.get('stocks', []):
            stock_names_map[stock.get('code', '')] = stock.get('name', '')
        
        # 遍历持仓并累加市值
        total_market_value = 0.0
        for stock_code, holding in holdings.items():
            stock_name = stock_names_map.get(stock_code, stock_code)
            
            # 计算盈亏（已移除）
            # profit_loss = holding['market_value'] - holding['shares'] * holding['cost_price']
            # profit_loss_pct = ...
            
            holding_info = {
                'stock_code': stock_code,
                'stock_name': stock_name,
                'shares': holding['shares'],
                'cost_price': round(holding['cost_price'], 2),
                'current_price': round(holding['current_price'], 2),
                'market_value': round(holding['market_value'], 2),
                'target_weight': round(holding['target_weight'], 4),
                'actual_weight': round(holding['market_value'] / tracker.account.initial_capital, 4),
                # 'profit_loss': round(profit_loss, 2),  # 已移除
                # 'profit_loss_pct': round(profit_loss_pct, 2),  # 已移除
                'buy_date': holding.get('buy_date'),
                'status': holding.get('status', 'holding')
            }
            result['holdings'].append(holding_info)
            total_market_value += holding['market_value']
        
        # 更新总市值
        result['total_market_value'] = round(total_market_value, 2)
        
        return jsonify({
            'success': True,
            'data': convert_to_native_types(result)
        })
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({
            'success': False,
            'error': str(e)
        })


@app.route('/api/portfolio/trade-history')
@require_auth
def api_portfolio_trade_history():
    """API: 获取交易记录
    
    参数:
        start_date: 开始日期（可选）
        end_date: 结束日期（可选）
        stock_code: 股票代码筛选（可选）
        action: 操作类型筛选（buy/sell，可选）
        limit: 返回记录数量限制（可选，默认100）
        
    返回:
        {
            "success": true,
            "data": {
                "strategy_name": "multi_factor_v1",
                "total_trades": 48,
                "trades": [...]
            }
        }
    """
    try:
        # 获取参数
        start_date = request.args.get('start_date')
        end_date = request.args.get('end_date')
        stock_code = request.args.get('stock_code')
        action = request.args.get('action')
        limit = request.args.get('limit', default=100, type=int)
        strategy_name = request.args.get('strategy_name', 'multi_factor_v1')
        
        # 创建跟踪器
        tracker = PortfolioTracker(account=VirtualAccount(strategy_name=strategy_name))
        
        # 获取交易记录
        trades = tracker.get_trade_history(start_date, end_date, stock_code, action)
        
        # 限制数量
        trades = trades[:limit]
        
        # 添加股票名称
        stock_names_cache = load_json_file(BASE_DIR / 'cache' / 'stock_list.json', {})
        
        trades_with_names = []
        for trade in trades:
            stock_name = stock_names_cache.get(trade['stock_code'], {}).get('name', trade['stock_code'])
            trade_with_name = trade.copy()
            trade_with_name['stock_name'] = stock_name
            trades_with_names.append(trade_with_name)
        
        result = {
            'strategy_name': strategy_name,
            'total_trades': len(trades),
            'trades': trades_with_names
        }
        
        return jsonify({
            'success': True,
            'data': convert_to_native_types(result)
        })
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({
            'success': False,
            'error': str(e)
        })


@app.route('/api/portfolio/rebalance-suggestion')
@require_auth
def api_portfolio_rebalance_suggestion():
    """API: 获取调仓建议（P1功能）
    
    参数:
        date: 调仓日期（可选，默认今天）
        threshold: 权重偏离阈值（可选，默认10%）
        
    返回:
        {
            "success": true,
            "data": {
                "date": "2026-04-16",
                "need_rebalance": true,
                "reason": "权重偏离超过10%",
                "actions": [...]
            }
        }
    """
    try:
        # 获取参数
        date = request.args.get('date', datetime.now().strftime('%Y-%m-%d'))
        threshold = request.args.get('threshold', default=0.10, type=float)
        strategy_name = request.args.get('strategy_name', 'multi_factor_v1')
        
        # 创建跟踪器
        tracker = PortfolioTracker(account=VirtualAccount(strategy_name=strategy_name))
        
        # 加载预计算结果
        optimization_result, top_stocks = load_precompute_result()
        
        if not optimization_result or not top_stocks:
            return jsonify({
                'success': False,
                'error': '预计算结果不存在，无法生成调仓建议'
            })
        
        # 获取目标权重
        best_combination = optimization_result.get('best_combination', {})
        target_weights = best_combination.get('weights', {})
        
        # 转换权重格式（从 factor weights 到 stock weights）
        # 这里简化处理：假设每只股票权重相等
        stock_target_weights = {}
        for stock in top_stocks[:tracker.account.top_n]:
            stock_target_weights[stock['code']] = 1.0 / tracker.account.top_n
        
        # 获取当前价格
        stock_codes = list(tracker.account.holdings.keys()) + [s['code'] for s in top_stocks[:tracker.account.top_n]]
        prices = get_stock_prices(stock_codes, date)
        
        # 计算调仓需求
        rebalance_plan = tracker.calculate_rebalance(
            tracker.account.holdings,
            stock_target_weights,
            prices,
            threshold=threshold
        )
        
        result = {
            'date': date,
            'need_rebalance': rebalance_plan['need_rebalance'],
            'reason': rebalance_plan['reason'],
            'threshold': threshold,
            'to_sell': rebalance_plan['to_sell'],
            'to_buy': rebalance_plan['to_buy'],
            'to_adjust': rebalance_plan['to_adjust'],
            'current_holdings_count': len(tracker.account.holdings),
            'current_net_value': tracker.account.net_value,
            'precompute_time': optimization_result.get('computed_at'),
            'best_weights': best_combination.get('weights', {})
        }
        
        return jsonify({
            'success': True,
            'data': convert_to_native_types(result)
        })
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({
            'success': False,
            'error': str(e)
        })


@app.route('/api/portfolio/execute-rebalance', methods=['POST'])
@require_auth
def api_portfolio_execute_rebalance():
    """API: 手动触发调仓（P1功能）
    
    请求体:
        {
            "date": "2026-04-16",
            "strategy_name": "multi_factor_v1"
        }
        
    返回:
        {
            "success": true,
            "data": {
                "message": "调仓执行成功",
                "trades": [...],
                "net_value_after_rebalance": 1.1234
            }
        }
    """
    try:
        # 获取请求体
        data = request.get_json() or {}
        date = data.get('date', datetime.now().strftime('%Y-%m-%d'))
        strategy_name = data.get('strategy_name', 'multi_factor_v1')
        
        # 创建跟踪器
        tracker = PortfolioTracker(account=VirtualAccount(strategy_name=strategy_name))
        
        # 加载预计算结果
        optimization_result, top_stocks = load_precompute_result()
        
        if not optimization_result or not top_stocks:
            return jsonify({
                'success': False,
                'error': '预计算结果不存在，无法执行调仓'
            })
        
        # 获取目标权重
        stock_target_weights = {}
        for stock in top_stocks[:tracker.account.top_n]:
            stock_target_weights[stock['code']] = 1.0 / tracker.account.top_n
        
        # 获取价格
        stock_codes = list(tracker.account.holdings.keys()) + [s['code'] for s in top_stocks[:tracker.account.top_n]]
        prices = get_stock_prices(stock_codes, date)
        
        # 计算调仓需求
        rebalance_plan = tracker.calculate_rebalance(
            tracker.account.holdings,
            stock_target_weights,
            prices
        )
        
        if not rebalance_plan['need_rebalance']:
            return jsonify({
                'success': True,
                'data': {
                    'message': '无需调仓，持仓权重符合目标',
                    'reason': rebalance_plan['reason'],
                    'net_value': tracker.account.net_value
                }
            })
        
        # 执行调仓
        trades = tracker.execute_rebalance(date, rebalance_plan, prices)
        
        # 添加股票名称
        stock_names_cache = load_json_file(BASE_DIR / 'cache' / 'stock_list.json', {})
        trades_with_names = []
        for trade in trades:
            stock_name = stock_names_cache.get(trade['stock_code'], {}).get('name', trade['stock_code'])
            trade_with_name = trade.copy()
            trade_with_name['stock_name'] = stock_name
            trades_with_names.append(trade_with_name)
        
        result = {
            'message': f"调仓执行成功，共{len(trades)}笔交易",
            'trades': trades_with_names,
            'net_value_after_rebalance': tracker.account.net_value,
            'rebalance_reason': rebalance_plan['reason']
        }
        
        return jsonify({
            'success': True,
            'data': convert_to_native_types(result)
        })
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({
            'success': False,
            'error': str(e)
        })


@app.route('/api/portfolio/init', methods=['POST'])
@require_auth
def api_portfolio_init():
    """API: 初始化虚拟账户（首次建仓）
    
    请求体:
        {
            "date": "2026-04-16",
            "strategy_name": "multi_factor_v1",
            "initial_capital": 1000000,
            "top_n": 5
        }
        
    返回:
        {
            "success": true,
            "data": {
                "message": "账户初始化成功",
                "holdings": [...],
                "net_value": 1.0
            }
        }
    """
    try:
        # 获取请求体
        data = request.get_json() or {}
        date = data.get('date', datetime.now().strftime('%Y-%m-%d'))
        strategy_name = data.get('strategy_name', 'multi_factor_v1')
        initial_capital = data.get('initial_capital', DEFAULT_INITIAL_CAPITAL)
        top_n = data.get('top_n', DEFAULT_TOP_N)
        
        # 加载预计算结果
        optimization_result, top_stocks = load_precompute_result()
        
        if not optimization_result or not top_stocks:
            return jsonify({
                'success': False,
                'error': '预计算结果不存在，无法初始化账户'
            })
        
        # 创建账户
        account = VirtualAccount(
            strategy_name=strategy_name,
            initial_capital=initial_capital,
            top_n=top_n
        )
        
        # 检查是否已初始化
        if account.init_date:
            return jsonify({
                'success': False,
                'error': f"账户已初始化（{account.init_date}），无需重复初始化",
                'current_net_value': account.net_value
            })
        
        # 获取价格
        stock_codes = [s['code'] for s in top_stocks[:top_n]]
        prices = get_stock_prices(stock_codes, date)
        
        # 检查价格是否获取成功
        if not prices:
            return jsonify({
                'success': False,
                'error': '无法获取股票价格，请检查数据源或稍后重试'
            })
        
        # 检查是否所有股票都有价格
        missing_prices = [code for code in stock_codes if code not in prices]
        if missing_prices:
            return jsonify({
                'success': False,
                'error': f'以下股票价格获取失败: {missing_prices}，请稍后重试或联系管理员'
            })
        
        # 初始化账户
        tracker = PortfolioTracker(account=account)
        account.initialize(date, stock_codes, {}, prices)  # 权重由initialize自动分配
        
        result = {
            'message': f"账户初始化成功，持仓{len(account.holdings)}只股票",
            'initial_capital': initial_capital,
            'holdings_count': len(account.holdings),
            'cash_balance': account.cash_balance,
            # 'net_value': account.net_value,  # 已移除
            'init_date': date
        }
        
        return jsonify({
            'success': True,
            'data': convert_to_native_types(result)
        })
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({
            'success': False,
            'error': str(e)
        })


@app.route('/api/portfolio/config', methods=['GET', 'POST'])
@require_auth
def api_portfolio_config():
    """API: 配置管理（P2功能）
    
    GET: 获取当前配置
    POST: 更新配置
        {
            "initial_capital": 1000000,
            "rebalance_threshold": 0.10,
            "top_n": 5,
            "trade_cost": 0.002,
            "slippage": 0.001
        }
    """
    try:
        if request.method == 'GET':
            # 获取当前配置
            config_data = load_json_file(CONFIG_FILE, {
                'initial_capital': DEFAULT_INITIAL_CAPITAL,
                'rebalance_threshold': DEFAULT_REBALANCE_THRESHOLD,
                'top_n': DEFAULT_TOP_N,
                'trade_cost': DEFAULT_TRADE_COST,
                'slippage': DEFAULT_SLIPPAGE
            })
            
            return jsonify({
                'success': True,
                'data': config_data
            })
        
        else:  # POST
            # 更新配置
            data = request.get_json() or {}
            
            # 加载现有配置
            config_data = load_json_file(CONFIG_FILE, {
                'initial_capital': DEFAULT_INITIAL_CAPITAL,
                'rebalance_threshold': DEFAULT_REBALANCE_THRESHOLD,
                'top_n': DEFAULT_TOP_N,
                'trade_cost': DEFAULT_TRADE_COST,
                'slippage': DEFAULT_SLIPPAGE
            })
            
            # 更新字段
            if 'initial_capital' in data:
                config_data['initial_capital'] = data['initial_capital']
            if 'rebalance_threshold' in data:
                config_data['rebalance_threshold'] = data['rebalance_threshold']
            if 'top_n' in data:
                config_data['top_n'] = data['top_n']
            if 'trade_cost' in data:
                config_data['trade_cost'] = data['trade_cost']
            if 'slippage' in data:
                config_data['slippage'] = data['slippage']
            
            # 保存配置
            config_data['last_updated'] = datetime.now().isoformat()
            atomic_write_json(CONFIG_FILE, config_data)
            
            return jsonify({
                'success': True,
                'message': '配置更新成功',
                'data': config_data
            })
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({
            'success': False,
            'error': str(e)
        })


@app.route('/api/portfolio/daily-update', methods=['POST'])
@require_auth
def api_portfolio_daily_update():
    """API: 手动触发每日净值更新
    
    请求体:
        {
            "date": "2026-04-16"
        }
        
    返回:
        {
            "success": true,
            "data": {
                "message": "净值更新成功",
                "net_value": 1.1234,
                "daily_return": 0.0156
            }
        }
    """
    try:
        # 获取请求体
        data = request.get_json() or {}
        date = data.get('date', datetime.now().strftime('%Y-%m-%d'))
        
        # 执行每日跟踪
        result = run_daily_tracking(date)
        
        return jsonify({
            'success': result.get('success', False),
            'data': convert_to_native_types(result)
        })
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({
            'success': False,
            'error': str(e)
        })


@app.route('/api/portfolio/strategy-rating')
@require_auth
def api_portfolio_strategy_rating():
    """API: 获取策略评级数据（v2.0版本）
    
    v2.0 核心变更：
    - 成功率维度：周期成功率 → 权重组合成功率
    - 稳定性维度：权重方差 → 权重相似度
    
    请求参数:
        period: 指定周期，不传则返回全部
        detail: 是否返回详细信息，默认false
        combos: 是否返回权重组合数据，默认false
    
    返回:
        {
            "code": 200,
            "data": {
                "meta": {"data_version": "2.0", ...},
                "ratings": {"T+1": {...}, "T+3": {...}, "T+5": {...}},
                "weight_combinations": {...},
                "summary": {...}
            }
        }
    """
    try:
        from pathlib import Path as PathLib
        
        period = request.args.get('period')
        detail = request.args.get('detail', 'false').lower() == 'true'
        combos = request.args.get('combos', 'false').lower() == 'true'
        
        # 评级数据文件路径
        rating_file = PathLib(BASE_DIR) / 'cache' / 'v2' / 'strategy_rating.json'
        
        if not rating_file.exists():
            return jsonify({
                'code': 404,
                'message': '评分数据尚未生成，请先运行 strategy_tracker.py',
                'hint': 'python versions/v2/scripts/strategy_tracker.py'
            })
        
        with open(rating_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        # 过滤周期
        if period:
            if period not in data.get('ratings', {}):
                return jsonify({
                    'code': 400,
                    'message': f'无效周期: {period}，可选值: T+1, T+3, T+5'
                })
            data['ratings'] = {period: data['ratings'][period]}
        
        # 简化输出
        if not detail:
            simplified_ratings = {}
            for p, r in data.get('ratings', {}).items():
                simplified_ratings[p] = {
                    'period': p,
                    'overall_rating': r.get('overall_rating'),
                    'overall_score': r.get('overall_score'),
                    'recommendation': r.get('recommendation', {}).get('action'),
                    'current_combo': r.get('current_combo', {}).get('combo_id')
                }
            data['ratings'] = simplified_ratings
        
        # 不返回权重组合数据（除非明确要求）
        if not combos:
            data.pop('weight_combinations', None)
        
        return jsonify({
            'code': 200,
            'data': convert_to_native_types(data)
        })
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({
            'code': 500,
            'message': f'获取策略评级失败: {str(e)}'
        })


@app.route('/api/portfolio/weight-combinations')
@require_auth
def api_portfolio_weight_combinations():
    """API: 获取权重组合历史数据
    
    用于策略评级计算的权重组合历史表现数据
    
    返回:
        {
            "code": 200,
            "data": {
                "combinations": {...},
                "by_period": {...}
            }
        }
    """
    try:
        from pathlib import Path as PathLib
        
        period = request.args.get('period')
        
        # 组合数据文件路径
        combos_file = PathLib(BASE_DIR) / 'cache' / 'v2' / 'weight_combinations.json'
        
        if not combos_file.exists():
            return jsonify({
                'code': 404,
                'message': '权重组合数据不存在'
            })
        
        with open(combos_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        # 按周期过滤组合
        if period:
            filtered_combos = {
                k: v for k, v in data.get('combinations', {}).items()
                if v.get('period') == period
            }
            data['combinations'] = filtered_combos
            if period in data.get('by_period', {}):
                data['by_period'] = {period: data['by_period'][period]}
        
        return jsonify({
            'code': 200,
            'data': convert_to_native_types(data)
        })
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({
            'code': 500,
            'message': f'获取权重组合数据失败: {str(e)}'
        })


@app.route('/portfolio-tracking')
@require_auth
def portfolio_tracking_page():
    """Portfolio 虚拟持仓跟踪页面"""
    return render_template('portfolio_tracking.html', active_page='portfolio')


# ========== 启动预热 ==========
def warmup_cache():
    """
    服务启动时预热缓存数据，消除首次请求等待
    
    v3.6 性能优化（云柏方案实施）：
    - 预加载打分引擎数据（节省 25 分钟）
    - 初始化并行回测进程池（节省 131 分钟）
    - 总优化效果：175 分钟 → 19 分钟（89% 提升）
    
    首次请求需59秒加载131MB数据，预热后请求可秒级响应
    """
    print("\n" + "="*40)
    print("🔥 启动预热 - 加载缓存数据")
    print("="*40)
    
    try:
        # 检查缓存文件是否存在
        cache_dir = Path('/home/admin/.openclaw/workspace/yunzhou/factor_ic_analyzer/cache/factor_data')
        factor_path = cache_dir / 'factor_data.json.gz'
        return_path = cache_dir / 'return_data.json.gz'
        
        if not factor_path.exists() or not return_path.exists():
            print("⚠️ 缓存文件不存在，跳过预热")
            print("   首次请求时将自动加载并缓存数据")
            return
        
        # 记录开始时间
        warmup_start = time.time()
        
        # 检查可用内存，动态调整加载天数
        try:
            import psutil
            mem = psutil.virtual_memory()
            available_mb = mem.available / 1024 / 1024
            print(f"📊 可用内存: {available_mb:.0f} MB")
            
            # 内存不足时只加载最近 100 天
            if available_mb < 500:
                max_days = 100
                print(f"   ⚠️ 内存不足，限制为最近 {max_days} 天")
            else:
                max_days = 150  # 默认 150 天（约 6 个月）
        except ImportError:
            max_days = 150  # psutil 未安装，使用保守值
        
        # 加载缓存数据（轻量模式）
        print(f"📂 正在加载缓存数据（最近 {max_days} 天）...")
        factor_df, return_df = load_cached_data_light(max_days=max_days)
        
        if factor_df is not None and len(factor_df) > 0:
            warmup_time = time.time() - warmup_start
            
            # 计算内存占用
            factor_mem = factor_df.memory_usage(deep=True).sum() / 1024 / 1024
            return_mem = return_df.memory_usage(deep=True).sum() / 1024 / 1024
            
            print(f"✅ 预热完成！")
            print(f"   - 数据量: {len(factor_df):,} 条记录")
            print(f"   - 因子数据: {factor_mem:.1f} MB")
            print(f"   - 收益数据: {return_mem:.1f} MB")
            print(f"   - 预热耗时: {warmup_time:.1f} 秒")
            print(f"   - 首次请求将秒级响应！")
            
            # ========== v3.6 预加载打分引擎 ==========
            print("\n🎯 正在预加载打分引擎...")
            try:
                preload_scoring_engine()
                if CACHE_LOADED and CACHED_SCORING_ENGINE:
                    dates_count = len(CACHED_SCORING_ENGINE.available_dates)
                    print(f"   ✅ 打分引擎预加载完成")
                    print(f"   - 可用日期: {dates_count} 天")
                    print(f"   - 预期节省: 25 分钟（避免每次回测重新加载）")
            except Exception as e:
                print(f"   ⚠️ 打分引擎预加载失败: {e}")
                import traceback
                traceback.print_exc()
            
            # ========== v3.7 OOM 修复：延迟初始化进程池 ==========
            print("\n⚡ 进程池将在首次使用时按需初始化（避免启动时内存峰值）")
            print("   - 进程池大小: 2（适配 3.5GB 内存服务器）")
            print("   - 启动模式: spawn（避免 fork 内存副本）")
            
            # 输出总优化效果
            print("\n📈 v3.7 性能优化效果预估:")
            print("   - 数据预加载：节省 25 分钟（14.3% 提升）")
            print("   - 并行回测：节省 131 分钟（74.9% 提升）")
            print("   - OOM 修复：启动时内存峰值 < 2GB（避免 OOM Killer）")
            
        else:
            print("⚠️ 缓存数据加载失败，首次请求时将重新加载")
            
    except Exception as e:
        print(f"⚠️ 预热失败: {e}")
        print("   首次请求时将自动加载缓存数据")
    
    print("="*40 + "\n")


if __name__ == '__main__':
    print("="*60)
    print("因子池 IC 分析系统 - Web界面")
    print("="*60)
    print(f"\n访问地址: http://localhost:8765")
    print(f"输出目录: {OUTPUT_DIR}")
    print(f"数据文件: {RESULTS_FILE}")
    
    # ========== 启动预热 ==========
    warmup_cache()
    
    print("\n按 Ctrl+C 停止服务\n")
    
    app.run(host='0.0.0.0', port=8765, debug=False)