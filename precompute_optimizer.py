#!/usr/bin/env python3
"""
因子组合优化预计算模块
作者: 云舟 🛠️
功能: 定时预计算最优因子组合，输出年化收益率最高的策略

设计原则：
- 零侵入：不修改现有核心逻辑（scoring_engine、weight_optimizer）
- 全复用：直接调用现有模块
- 内存友好：考虑服务器 3.5GB 内存限制
- 原子写入：确保结果文件完整性

流程：
1. 加载因子IC数据
2. 网格搜索收集 Top 100 候选组合
3. 回测验证筛选
4. 使用最优组合计算推荐股票（top 20）
5. 原子写入结果到 JSON 文件

执行时间：凌晨 02:00
预计耗时：2.5 小时
"""

import json
import os
import sys
import time
import tempfile
import shutil
import gc
import logging
import psutil  # P1-2: 内存监控
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
import traceback

# ========== 配置日志 ==========
BASE_DIR = Path(__file__).parent
CACHE_DIR = BASE_DIR / 'cache' / 'precompute'
LOG_DIR = BASE_DIR / 'logs'

# 确保目录存在
CACHE_DIR.mkdir(parents=True, exist_ok=True)
LOG_DIR.mkdir(parents=True, exist_ok=True)

# 配置日志
log_file = LOG_DIR / 'optimizer.log'
error_log_file = LOG_DIR / 'optimizer_error.log'

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [预计算] %(levelname)s: %(message)s',
    handlers=[
        logging.FileHandler(log_file, encoding='utf-8'),
        logging.StreamHandler(sys.stdout)
    ]
)

# 错误日志单独处理
error_logger = logging.getLogger('optimizer_error')
error_logger.addHandler(logging.FileHandler(error_log_file, encoding='utf-8'))
error_logger.setLevel(logging.ERROR)

logger = logging.getLogger(__name__)


# ========== 配置参数 ==========
# 5 个因子列表（Phase 3: 加回 return_3d）
# Phase 1: 方案D - 剔除 IC 不显著的因子
# Phase 3: P0-1 - 加回 return_3d（ICIR=0.19，扩大搜索空间×8）
FACTORS = ['rsi', 'bollinger_pb', 'volume_ratio', 'turnover_surge', 'return_3d']

# 因子名称映射（用于展示）
FACTOR_NAMES = {
    'rsi': 'RSI(14)',
    'bollinger_pb': '布林带%B',
    'volume_ratio': '量比',
    'turnover_surge': '换手率突增'
}

# 因子 IC 方向配置（Phase 2: 方案A + 方案E修复）
# 'positive': IC>0，权重必须>=-tolerance（允许小范围反向）
# 'negative': IC<0，权重必须<=+tolerance（允许小范围正向）
# 'neutral': IC方向不确定，无方向约束
# Phase 2修复: turnover_surge 的 ICIR 为正向（+0.27），修正为 positive
# Phase 3 P0-1: 加回 return_3d，方向为 neutral（无约束）
IC_DIRECTIONS = {
    'rsi': 'positive',           # IC=0.0394 > 0
    'bollinger_pb': 'positive',  # IC=0.0407 > 0
    'volume_ratio': 'positive',  # IC=0.0294 > 0
    'turnover_surge': 'positive', # Phase 2修复: ICIR=+0.27 > 0
    'return_3d': 'neutral'       # Phase 3 P0-1: ICIR=0.19，方向neutral无约束
}

# 预计算配置
PRECOMPUTE_CONFIG = {
    'grid_search': {
        'weight_range': (-1.0, 1.0),
        'step': 0.2,
        'constraint': 'sum_to_one',
        'top_candidates': 100  # 网格搜索收集候选数
    },
    'backtest': {
        'top_n_output': 5,  # 回测验证参数：持仓数量（用于评估权重组合）P3: Top 5 选股
        'fallback_to_icir': True,
        'use_parallel': True,  # 使用并行回测（线程池）
        'pool_size': 4  # 线程池大小
    },
    'output': {  # P0-1: 输出参数配置（新增）
        'top_stocks_count': 10,  # API 返回推荐股票数量（固定10只）
        'api_default_top_n': 3,  # API 默认返回数量
        'scoring_top_stocks': 20  # 打分候选池大小（内部使用）
    },
    'scoring': {
        'top_stocks': 20,  # 计算推荐股票 Top 20（内部候选池，API 按需取用）
        'normalize_method': 'quantile',
        'score_function': 'sigmoid',
        'k_value': 10
    },
    'memory': {
        'min_available_mb': 500,  # 最小可用内存
        'gc_interval': 50  # 每 50 次计算后执行 GC
    }
}


# ========== 工具函数 ==========

def get_industry_distribution_from_stocks(stocks: List) -> Dict:
    """
    获取股票列表的行业分布（改进 1）
    
    Args:
        stocks: 股票列表（包含 code 字段）
        
    Returns:
        Dict: {行业名称: 数量}
    """
    try:
        from fetch_stock_industry import get_industry_distribution
        
        codes = [s.get('code', '') for s in stocks if s.get('code')]
        return get_industry_distribution(codes)
        
    except ImportError:
        # fetch_stock_industry 模块不存在，返回空统计
        logger.warning("[行业分布] fetch_stock_industry 模块不存在")
        return {}
    
    except Exception as e:
        logger.warning(f"[行业分布] 获取行业分布失败: {e}")
        return {}


def detect_actual_data_range(
    start_date_config: str,
    end_date_config: str
) -> Tuple[str, str, int, Dict]:
    """
    检测实际可用的数据范围（改进 2）
    
    Args:
        start_date_config: 配置的起始日期
        end_date_config: 配置的结束日期
        
    Returns:
        Tuple: (实际起始日期, 实际结束日期, 实际天数, 详细信息字典)
    """
    try:
        from scoring_engine import get_cached_engine
        
        engine = get_cached_engine()
        available_dates = engine.get_available_dates()
        
        if not available_dates:
            logger.warning("[回测窗口] 无可用数据")
            return start_date_config, end_date_config, 0, {
                'config_start': start_date_config,
                'config_end': end_date_config,
                'actual_start': None,
                'actual_end': None,
                'actual_days': 0,
                'warning': '无可用数据'
            }
        
        # 实际数据范围
        actual_start = min(available_dates)
        actual_end = max(available_dates)
        
        # 计算实际天数（在配置窗口内）
        actual_days = len([d for d in available_dates 
                           if d >= start_date_config and d <= end_date_config])
        
        # 配置窗口与实际数据的对比
        config_end_dt = datetime.strptime(end_date_config, '%Y-%m-%d')
        actual_end_dt = datetime.strptime(actual_end, '%Y-%m-%d')
        
        # 如果实际数据不足，自动截断
        adjusted_end = end_date_config
        if actual_end_dt < config_end_dt:
            logger.warning(f"[回测窗口] 数据不足: 配置 {end_date_config}, 实际只有 {actual_end}")
            adjusted_end = actual_end
        
        # 计算配置天数（理论上）
        config_start_dt = datetime.strptime(start_date_config, '%Y-%m-%d')
        config_days = (config_end_dt - config_start_dt).days + 1
        
        # 记录详细信息
        window_info = {
            'config_start': start_date_config,
            'config_end': end_date_config,
            'config_days': config_days,
            'actual_start': actual_start,
            'actual_end': actual_end,
            'actual_days': actual_days,
            'adjusted_end': adjusted_end,
            'auto_adjusted': adjusted_end != end_date_config
        }
        
        logger.info(f"[回测窗口] 配置: {start_date_config} ~ {end_date_config} ({config_days} 天)")
        logger.info(f"[回测窗口] 实际: {actual_start} ~ {actual_end} ({actual_days} 天)")
        if window_info['auto_adjusted']:
            logger.info(f"[回测窗口] 已自动截断至 {adjusted_end}")
        
        return start_date_config, adjusted_end, actual_days, window_info
        
    except Exception as e:
        logger.error(f"[回测窗口] 检测失败: {e}")
        return start_date_config, end_date_config, 0, {
            'config_start': start_date_config,
            'config_end': end_date_config,
            'error': str(e)
        }


def detect_market_environment_simple() -> Dict:
    """
    P1-1: 简化版市场环境判断
    
    使用因子 IC 波动率作为市场波动率的代理
    
    Returns:
        Dict: {'market_type': 'trend'|'oscillation'|'neutral', 'reason': str}
    """
    try:
        from weight_optimizer import get_optimizer
        import numpy as np
        
        optimizer = get_optimizer()
        
        # 计算 rsi 因子的 IC 波动率作为代理
        rsi_ic = optimizer.ic_data.get('rsi', {}).get('ic_values', [])
        
        if len(rsi_ic) < 20:
            return {'market_type': 'neutral', 'reason': '数据不足'}
        
        # 近 20 日 IC 波动率
        recent_volatility = np.std(rsi_ic[-20:])
        
        # 历史平均 IC 波动率（使用 60 日）
        historical_volatility = np.std(rsi_ic[-60:]) if len(rsi_ic) >= 60 else np.std(rsi_ic)
        
        # 波动率比值
        volatility_ratio = recent_volatility / historical_volatility if historical_volatility > 0 else 1.0
        
        # 判定市场类型
        if volatility_ratio > 1.5:
            return {'market_type': 'trend', 'reason': f'波动率比值={volatility_ratio:.2f}>1.5'}
        elif volatility_ratio < 0.8:
            return {'market_type': 'oscillation', 'reason': f'波动率比值={volatility_ratio:.2f}<0.8'}
        else:
            return {'market_type': 'neutral', 'reason': f'波动率比值={volatility_ratio:.2f}正常'}
    
    except Exception as e:
        logger.warning(f"P1-1: 市场环境判断失败: {e}")
        return {'market_type': 'neutral', 'reason': f'判断失败: {e}'}


def check_memory_available(min_mb: int = 500) -> Tuple[bool, float, str]:
    """
    检查是否有足够内存
    
    Args:
        min_mb: 最小可用内存（MB）
        
    Returns:
        Tuple: (is_available, available_mb, message)
    """
    try:
        import psutil
        mem = psutil.virtual_memory()
        available_mb = mem.available / 1024 / 1024
        
        if available_mb < min_mb:
            return False, available_mb, f"内存不足（可用 {available_mb:.0f}MB < {min_mb}MB）"
        return True, available_mb, f"内存充足（可用 {available_mb:.0f}MB）"
    except ImportError:
        logger.warning("psutil 未安装，跳过内存检查")
        return True, 0, "内存检查跳过（psutil 未安装）"


def atomic_write_json(filepath: Path, data: Dict) -> bool:
    """
    原子写入 JSON 文件
    
    流程：
    1. 写入临时文件
    2. 成功后重命名（原子操作）
    
    Args:
        filepath: 目标文件路径
        data: 要写入的数据
        
    Returns:
        bool: 是否成功
    """
    # 创建临时文件
    temp_fd, temp_path = tempfile.mkstemp(
        dir=filepath.parent,
        prefix='.tmp_precompute_',
        suffix='.json'
    )
    
    try:
        # 写入临时文件
        with os.fdopen(temp_fd, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        
        # 原子重命名
        shutil.move(temp_path, str(filepath))
        logger.info(f"原子写入成功: {filepath}")
        return True
        
    except Exception as e:
        # 清理临时文件
        if os.path.exists(temp_path):
            os.unlink(temp_path)
        logger.error(f"原子写入失败: {e}")
        return False


def load_history_best() -> List[Dict]:
    """
    加载历史最优权重数据（P2-3）
    
    Returns:
        List[Dict]: 历史最优权重列表 [{'weights': {...}, 'icir': float, ...}, ...]
    """
    history_file = CACHE_DIR / 'compute_history.json'
    
    if history_file.exists():
        try:
            with open(history_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            history = data.get('history', [])
            
            # 转换为历史最优格式
            history_best = []
            for record in history[-7:]:  # 取最近 7 天的记录
                history_best.append({
                    'weights': record.get('best_weights', {}),
                    'icir': record.get('best_icir', 0) if 'best_icir' in record else record.get('score', 0),
                    'task_id': record.get('task_id', ''),
                    'timestamp': record.get('computed_at', '')
                })
            
            logger.info(f"P2-3: 加载历史最优权重 {len(history_best)} 条")
            return history_best
            
        except Exception as e:
            logger.warning(f"P2-3: 加载历史最优失败: {e}")
    
    return []


def load_config() -> Dict:
    """
    加载优化器配置
    
    Returns:
        Dict: 配置字典
    """
    config_path = BASE_DIR / 'optimizer_config.json'
    
    if config_path.exists():
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                config = json.load(f)
            logger.info(f"加载配置文件: {config_path}")
            return config
        except Exception as e:
            logger.warning(f"加载配置失败，使用默认配置: {e}")
    
    # 返回默认配置
    return {
        'backtest_params': {
            'start_date': '2025-08-25',
            'end_date': '2026-04-10',
            'top_n': 3,
            'cost': 0.002,
            'slippage': 0.001
        },
        'constraints': {
            'min_sharpe': 1.0,
            'max_drawdown': 30.0,
            'min_win_rate': 50.0,
            'min_annual_return': 0.0
        }
    }


def convert_numpy_to_native(obj) -> any:
    """
    递归转换 numpy 类型为 Python 原生类型
    
    Args:
        obj: 待转换对象
        
    Returns:
        转换后的对象
    """
    import numpy as np
    
    if isinstance(obj, dict):
        return {k: convert_numpy_to_native(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [convert_numpy_to_native(v) for v in obj]
    elif isinstance(obj, (np.integer, np.int64, np.int32)):
        return int(obj)
    elif isinstance(obj, (np.floating, np.float64, np.float32)):
        return float(obj)
    elif isinstance(obj, np.bool_):
        return bool(obj)
    elif isinstance(obj, np.ndarray):
        return obj.tolist()
    else:
        return obj


# ========== 预计算主流程 ==========

def run_precompute(
    progress_callback: Optional[callable] = None,
    dry_run: bool = False
) -> Dict:
    """
    执行预计算流程（详细日志版本）
    
    日志格式：
    - [Step X] 开始执行: 步骤名称
    - [Step X] 进度: 已处理 X/Y
    - [Step X] 完成: 步骤名称, 耗时 Ts, 结果: 关键指标
    """
    start_time = time.time()
    task_id = f"precompute_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    
    # 初始化时间变量（确保异常处理时可用）
    step0_time = 0.0
    grid_time = 0.0
    step2_time = 0.0
    step4_time = 0.0
    step5_time = 0.0
    
    logger.info(f"========== 开始预计算任务: {task_id}（Phase 2） ========== ")
    sys.stdout.flush()
    
    # ========== [Step 0] 前置检查 ========== 
    step0_start_time = time.time()
    logger.info(f"[Step 0] 开始执行: 前置检查")
    sys.stdout.flush()
    
    if progress_callback:
        progress_callback(0, 100, '前置检查')
    
    # 内存检查
    mem_ok, mem_available, mem_msg = check_memory_available(
        PRECOMPUTE_CONFIG['memory']['min_available_mb']
    )
    if not mem_ok:
        error_logger.error(f"内存检查失败: {mem_msg}")
        return {
            'success': False,
            'error': mem_msg,
            'task_id': task_id,
            'elapsed_seconds': 0
        }
    
    logger.info(f"[Step 0] 内存检查通过: {mem_msg}")
    sys.stdout.flush()
    
    # 加载配置
    config = load_config()
    logger.info(f"[Step 0] 配置加载完成")
    sys.stdout.flush()
    
    # ========== 改进 2: 回测窗口动态检测 ========== 
    backtest_params = config.get('backtest_params', {})
    start_date = backtest_params.get('start_date', '2025-08-25')
    end_date = backtest_params.get('end_date', '2026-04-15')
    
    # 检测实际数据范围
    actual_start, actual_end, actual_days, backtest_window_info = detect_actual_data_range(
        start_date, end_date
    )
    
    # 更新回测参数（使用实际可用范围）
    backtest_params['start_date'] = actual_start
    backtest_params['end_date'] = actual_end
    backtest_params['actual_days'] = actual_days  # 改进 2: 记录实际天数
    config['backtest_params'] = backtest_params
    
    logger.info(f"[Step 0] 回测窗口检测完成: 实际 {actual_days} 天")
    sys.stdout.flush()
    
    step0_time = time.time() - step0_start_time
    logger.info(f"[Step 0] 完成: 前置检查, 耗时 {step0_time:.1f}s")
    sys.stdout.flush()
    
    # ========== Phase 2: 加载新增配置 ==========
    direction_tolerance = config.get('direction_tolerance', 0.2)  # 方案E
    sum_constraint_config = config.get('sum_constraint', {'type': 'sum_range', 'range': {'min': 0.5, 'max': 1.5}})  # 方案F
    ic_bridge_config = config.get('ic_bridge', {'enabled': True, 'backtest_candidates': 20})  # 方案H
    
    logger.info(f"[Phase 2] 配置加载:")
    logger.info(f"  方向容忍度 tolerance={direction_tolerance}（方案E）")
    logger.info(f"  和约束类型 sum_constraint={sum_constraint_config.get('type')}（方案F）")
    logger.info(f"  IC桥接启用 ic_bridge={ic_bridge_config.get('enabled')}（方案H）")
    
    if dry_run:
        logger.info("[模拟运行] 跳过实际计算")
        return {
            'success': True,
            'dry_run': True,
            'task_id': task_id,
            'message': '模拟运行完成',
            'phase2_config': {
                'direction_tolerance': direction_tolerance,
                'sum_constraint_type': sum_constraint_config.get('type'),
                'ic_bridge_enabled': ic_bridge_config.get('enabled')
            }
        }
    
    # ========== [Step 1] 三阶段搜索 ========== 
    step1_start_time = time.time()
    logger.info(f"[Step 1] 开始执行: 三阶段搜索（收集 Top 500 候选）")
    sys.stdout.flush()
    
    if progress_callback:
        progress_callback(5, 100, 'Step 1: 三阶段搜索')
    
    try:
        from weight_optimizer import WeightOptimizer, get_optimizer
        
        optimizer = get_optimizer()
        
        # 加载配置文件获取三阶段搜索参数
        grid_config = config.get('grid_search', {})
        
        # Phase 2 方案F: 使用 sum_range 约束
        constraint_type = sum_constraint_config.get('type', 'sum_range')
        sum_range = (
            sum_constraint_config.get('range', {}).get('min', 0.5),
            sum_constraint_config.get('range', {}).get('max', 1.5)
        )
        
        three_phase_config = {
            'weight_range': [
                grid_config.get('weight_range', {}).get('min', -1.0),
                grid_config.get('weight_range', {}).get('max', 1.0)
            ],
            'step_phase1': grid_config.get('step_phase1', 0.1),   # P1-2: 默认值调整
            'step_phase2': grid_config.get('step_phase2', 0.05),  # P1-2: 默认值调整
            'top_candidates_phase1': grid_config.get('top_candidates_phase1', 200),
            'top_candidates_phase2': grid_config.get('top_candidates_phase2', 2000),
            'constraint': constraint_type,  # Phase 2: 使用 sum_range
            'max_combinations': grid_config.get('max_combinations', 150000),  # P1-2: 内存保护
            # P1-3: 传递因子权重约束
            'factor_min_weights': config.get('factor_min_weights'),
            'factor_max_weights': config.get('factor_max_weights')
        }
        
        logger.info(f"三阶段搜索配置: Phase1步长={three_phase_config['step_phase1']}, Top={three_phase_config['top_candidates_phase1']}")
        logger.info(f"                   Phase2步长={three_phase_config['step_phase2']}, Top={three_phase_config['top_candidates_phase2']}")
        logger.info(f"                   约束类型={constraint_type}, sum_range={sum_range}（Phase 2 方案F）")
        logger.info(f"                   max_combinations={three_phase_config['max_combinations']}（P1-2 内存保护）")
        
        # P1-2: 内存检查
        mem = psutil.virtual_memory()
        available_mb = mem.available / 1024 / 1024
        logger.info(f"内存状态: 可用 {available_mb:.0f}MB / 总计 {mem.total / 1024 / 1024:.0f}MB")
        if available_mb < 500:
            logger.warning(f"P1-2 内存警告: 可用内存不足 500MB，减少搜索空间")
            three_phase_config['max_combinations'] = min(
                three_phase_config['max_combinations'], 50000
            )
            three_phase_config['top_candidates_phase1'] = min(
                three_phase_config['top_candidates_phase1'], 100
            )
        
        # 进度回调包装
        def three_phase_progress(pct, total, msg, phase='grid_search'):
            if progress_callback:
                progress_callback(5 + pct * 0.3, 100, f'Step 1: {msg}')
        
        # P2-3: 加载历史最优权重数据
        history_best = load_history_best()
        
        # Phase 2 方案E: 使用 tolerance 参数
        grid_candidates = optimizer.three_phase_search(
            factors=FACTORS,
            ic_directions=IC_DIRECTIONS,
            config=three_phase_config,
            progress_callback=three_phase_progress,
            tolerance=direction_tolerance,  # Phase 2: 放宽方向约束
            history_best=history_best  # P2-3: 历史最优权重追踪
        )
        
        grid_time = time.time() - step1_start_time
        logger.info(f"[Step 1] 完成: 三阶段搜索, 耗时 {grid_time:.1f}s")
        logger.info(f"[Step 1] 结果: 收集 {len(grid_candidates)} 候选组合")
        logger.info(f"[Step 1] 方向约束: tolerance={direction_tolerance}（Phase 2 方案E）")
        sys.stdout.flush()
        
        # P1-1: 空列表保护
        if not grid_candidates:
            error_logger.error("网格搜索未返回有效候选组合")
            return {
                'success': False,
                'error': '网格搜索未返回有效候选组合',
                'task_id': task_id,
                'elapsed_seconds': time.time() - start_time
            }
        
        # 内存清理
        gc.collect()
        
    except Exception as e:
        error_logger.error(f"网格搜索失败: {e}")
        traceback.print_exc()
        return {
            'success': False,
            'error': f"网格搜索失败: {e}",
            'task_id': task_id,
            'elapsed_seconds': time.time() - start_time
        }
    
    # ========== [Step 2] 两阶段验证 ========== 
    step2_start_time = time.time()
    logger.info(f"[Step 2] 开始执行: 两阶段验证（IC桥接 + 精选回测）")
    sys.stdout.flush()
    
    if progress_callback:
        progress_callback(35, 100, 'Step 2: 开始两阶段验证')
    
    try:
        from quick_backtest import QuickBacktestValidator
        
        validator = QuickBacktestValidator(config)
        
        # Phase 2 方案H: 使用两阶段验证
        use_ic_bridge = ic_bridge_config.get('enabled', True)
        
        if use_ic_bridge:
            logger.info(f"启用两阶段验证（方案H）")
            
            # 进度回调包装
            def validation_progress(current, total, result):
                if progress_callback:
                    pct = 35 + (current / total) * 0.5
                    metrics = result.get('metrics', {}) if result else {}
                    sharpe = metrics.get('sharpe_ratio', 'N/A') if metrics else 'N/A'
                    progress_callback(pct, 100, f'Step 2: 验证 {current}/{total}')
            
            # Phase 2 方案H: 使用 two_stage_validation
            validation_result = validator.two_stage_validation(
                grid_candidates=grid_candidates,
                factors=FACTORS,
                config=config,
                progress_callback=validation_progress
            )
            
            tiered_results = validation_result.get('tiered_results', {})
            tier_used = validation_result.get('tier_used', 'unknown')
            ic_bridge_candidates = validation_result.get('ic_bridge_candidates', [])
            backtest_candidates = validation_result.get('backtest_candidates', [])
            
            logger.info(f"两阶段验证完成: tier={tier_used}, IC桥接{len(ic_bridge_candidates)}, 回测{len(backtest_candidates)}")
            
            # 从 tiered_results 中获取 top_weights
            if tiered_results.get('excellent'):
                top_weights = tiered_results['excellent']
                logger.info(f"  优秀组合: {len(top_weights)}")
            elif tiered_results.get('acceptable'):
                top_weights = tiered_results['acceptable']
                logger.info(f"  可用组合: {len(top_weights)}")
            else:
                top_weights = tiered_results.get('fallback', [])
                logger.warning(f"  Fallback组合: {len(top_weights)}")
            
            validation_results = backtest_candidates  # 用于后续统计
        
        else:
            # 不启用IC桥接，使用传统回测流程
            logger.info("IC桥接未启用，使用传统回测流程")
            
            from quick_backtest import parallel_backtest_batch
            
            # 进度回调包装
            def backtest_progress(current, total, result):
                if progress_callback:
                    pct = 35 + (current / total) * 0.5
                    metrics = result.get('metrics', {}) if result else {}
                    sharpe = metrics.get('sharpe_ratio', 'N/A') if metrics else 'N/A'
                    progress_callback(pct, 100, f'Step 2: 验证 {current}/{total}')
            
            # 使用并行回测（线程池方案A，内存友好）
            validation_results = parallel_backtest_batch(
                weight_candidates=grid_candidates[:100],  # 传统流程只取100
                factors=FACTORS,
                config=config,
                pool_size=PRECOMPUTE_CONFIG['backtest']['pool_size'],
                progress_callback=backtest_progress
            )
            
            # 方案B: 分层筛选
            top_weights, tier_used = validator.select_best_with_tiers(
                validation_results=validation_results,
                top_n=PRECOMPUTE_CONFIG['backtest']['top_n_output']
            )
            
            logger.info(f"传统回测完成: tier={tier_used}, Top {len(top_weights)} 组合")
        
        # ========== P1修复: Step 2 后 fallback 机制 ==========
        if not top_weights or len(top_weights) == 0:
            if grid_candidates and len(grid_candidates) > 0:
                # 使用 ICIR 最高的组合作为 fallback
                best_candidate = max(grid_candidates, key=lambda x: x.get('icir', 0))
                top_weights = [{
                    'weights': best_candidate.get('weights', {}),
                    'icir': best_candidate.get('icir', 0),
                    'metrics': None,
                    'passed_constraints': False,
                    'tier': 'icir_fallback'
                }]
                logger.warning(f"[Step 2] 无通过约束组合，使用 ICIR Top1 作为 fallback，ICIR={best_candidate.get('icir', 0):.4f}")
            else:
                logger.error(f"[Step 2] 无任何候选组合，任务失败")
                return {'success': False, 'error': '无候选组合'}
        
        step2_time = time.time() - step2_start_time
        logger.info(f"[Step 2] 完成: 两阶段验证, 耗时 {step2_time:.1f}s")
        logger.info(f"[Step 2] 结果: tier={tier_used}, Top {len(top_weights)} 组合")
        
        # 输出 Top 3 组合详情
        logger.info(f"[Step 2] Top 3 组合:")
        for i, w in enumerate(top_weights[:3]):
            metrics = w.get('metrics', {})
            logger.info(f"  #{i+1}: weights={w.get('weights', {})}, Sharpe={metrics.get('sharpe_ratio', 0) if metrics else 0:.2f}")
        sys.stdout.flush()
        
        # ========== [P1-1] 多 top_n 稳定性测试 ========== 
        step_p1_start_time = time.time()
        multi_top_n_config = config.get('multi_top_n_validation', {})
        if multi_top_n_config.get('enabled', False) and len(top_weights) > 0:
            logger.info(f"[P1-1] 开始执行: 多 top_n 稳定性测试")
            # 先定义变量，再引用
            top_n_values = multi_top_n_config.get('top_n_values', [3, 5, 10])
            stability_threshold = multi_top_n_config.get('stability_threshold', 0.15)
            logger.info(f"[P1-1] 参数: top_n_values={top_n_values}, stability_threshold={stability_threshold}")
            sys.stdout.flush()
            
            # 对 Top 5 组合执行多 top_n 验证
            try:
                stability_results = validator.batch_validate_with_multi_top_n(
                    weight_candidates=top_weights[:5],
                    factors=FACTORS,
                    top_n_values=top_n_values,
                    stability_threshold=stability_threshold,
                    progress_callback=None
                )
                
                # P2-1: 日志追踪数据结构
                logger.debug(f"stability_results 类型: {type(stability_results)}, 长度: {len(stability_results) if stability_results else 0}")
                # 更新 top_weights 的 stability_score
                for i, result in enumerate(stability_results):
                    if i < len(top_weights):
                        if isinstance(result, dict):
                            top_weights[i]['stability_score'] = result.get('stability_score', 0)
                            top_weights[i]['multi_top_n_results'] = result.get('multi_top_n_results', [])
                            top_weights[i]['avg_sharpe'] = result.get('avg_sharpe', 0)
                            top_weights[i]['is_stable'] = result.get('is_stable', False)
                        else:
                            logger.warning(f"stability_results[{i}] 类型异常: {type(result)}")
                
                step_p1_time = time.time() - step_p1_start_time
                logger.info(f"[P1-1] 完成: 多 top_n 稳定性测试, 耗时 {step_p1_time:.1f}s")
                logger.info(f"[P1-1] Top 1: stability_score={top_weights[0].get('stability_score', 0):.4f}, "
                            f"avg_sharpe={top_weights[0].get('avg_sharpe', 0):.2f}, "
                            f"is_stable={top_weights[0].get('is_stable', False)}")
                sys.stdout.flush()
                
            except Exception as e:
                logger.warning(f"P1-1: 多 top_n 稳定性测试失败: {e}")
                # 继续流程，不影响主结果
        
        # 内存清理
        gc.collect()
        
    except Exception as e:
        error_logger.error(f"回测验证失败: {e}")
        traceback.print_exc()
        return {
            'success': False,
            'error': f"回测验证失败: {e}",
            'task_id': task_id,
            'elapsed_seconds': time.time() - start_time,
            'grid_candidates_count': len(grid_candidates)
        }
    
    # ========== [Step 3] 获取最优组合 ========== 
    step3_start_time = time.time()
    logger.info(f"[Step 3] 开始执行: 获取最优组合")
    sys.stdout.flush()
    
    if not top_weights:
        error_logger.error("[Step 3] 失败: 无有效组合通过筛选")
        return {
            'success': False,
            'error': '无有效组合通过筛选',
            'task_id': task_id,
            'elapsed_seconds': time.time() - start_time
        }
    
    best_combination = top_weights[0]
    best_weights = best_combination.get('weights') or {}
    best_metrics = best_combination.get('metrics') or {}
    
    # 空值保护：当所有组合 Sharpe 为负导致约束全部失败时，best_metrics 可能为空
    if not best_metrics:
        logger.warning("[Step 3] 警告: best_metrics 为空，使用默认指标")
        best_metrics = {'sharpe_ratio': 'N/A', 'max_drawdown': 'N/A', 'win_rate': 'N/A'}
    
    step3_time = time.time() - step3_start_time
    logger.info(f"[Step 3] 完成: 获取最优组合, 耗时 {step3_time:.1f}s")
    logger.info(f"[Step 3] 结果: weights={best_weights}")
    logger.info(f"[Step 3] 指标: sharpe={best_metrics.get('sharpe_ratio', 'N/A')}, "
                f"drawdown={best_metrics.get('max_drawdown', 'N/A')}%, "
                f"win_rate={best_metrics.get('win_rate', 'N/A')}%")
    
    # 检查 turnover_surge 权重（Phase 2 验证）
    turnover_weight = best_weights.get('turnover_surge', 0)
    logger.info(f"[Step 3] Phase 2 验证: turnover_surge 权重={turnover_weight}（目标≥{-direction_tolerance}）")
    sys.stdout.flush()
    
    # ========== [Step 4] 计算推荐股票 ========== 
    step4_start_time = time.time()
    logger.info(f"[Step 4] 开始执行: 计算推荐股票 Top 20")
    sys.stdout.flush()
    
    if progress_callback:
        progress_callback(85, 100, 'Step 4: 计算推荐股票')
    
    top_stocks = []
    try:
        from scoring_engine import get_cached_engine
        
        engine = get_cached_engine()
        
        # 使用最优权重计算股票得分
        # 获取最近一个交易日的数据
        latest_date = engine.available_dates[-1] if engine.available_dates else None
        
        if latest_date:
            scores_result = engine.calculate_scores(
                date=latest_date,
                weights=best_weights,
                normalize_method=PRECOMPUTE_CONFIG['scoring']['normalize_method'],
                score_function=PRECOMPUTE_CONFIG['scoring']['score_function'],
                k_value=PRECOMPUTE_CONFIG['scoring']['k_value']
            )
            
            if scores_result.get('success'):
                scored_stocks = scores_result.get('selections', [])
                
                # 取 Top 20（API 按需返回 1-20）
                top_stocks = scored_stocks[:PRECOMPUTE_CONFIG['scoring']['top_stocks']]
                
                logger.info(f"推荐股票计算完成: {len(top_stocks)} 只股票")
        
        step4_time = time.time() - step4_start_time
        logger.info(f"[Step 4] 完成: 计算推荐股票, 耗时 {step4_time:.1f}s")
        logger.info(f"[Step 4] 结果: 推荐股票 {len(top_stocks)} 只")
        
        # 输出 Top 5 股票
        logger.info(f"[Step 4] Top 5 股票:")
        for i, s in enumerate(top_stocks[:5]):
            logger.info(f"  #{i+1}: {s.get('code')} {s.get('name')} (得分: {s.get('total_score', 0):.2f})")
        sys.stdout.flush()
        
    except Exception as e:
        error_logger.error(f"推荐股票计算失败: {e}")
        traceback.print_exc()
        # 继续流程，top_stocks 留空
        step4_time = time.time() - step4_start_time  # 确保变量定义
        logger.info(f"[Step 4] 失败: 计算推荐股票, 耗时 {step4_time:.1f}s")
        sys.stdout.flush()
    
    # ========== [Step 5] 构建结果并写入 ========== 
    step5_start_time = time.time()
    logger.info(f"[Step 5] 开始执行: 构建结果并原子写入")
    sys.stdout.flush()
    
    if progress_callback:
        progress_callback(95, 100, 'Step 5: 写入结果')
    
    # 定义结果文件路径（在引用前赋值）
    result_file = CACHE_DIR / 'optimization_result.json'
    
    step5_time = time.time() - step5_start_time
    total_time = time.time() - start_time
    
    logger.info(f"[Step 5] 完成: 构建结果并写入, 耗时 {step5_time:.1f}s")
    logger.info(f"[Step 5] 结果文件: {result_file}")
    sys.stdout.flush()
    
    # 计算综合评分
    def calculate_score(metrics):
        if metrics is None:
            return 0
        
        # 处理 N/A 或 None 值
        def safe_float(value, default=0):
            if value is None or value == 'N/A' or not isinstance(value, (int, float)):
                return default
            return float(value)
        
        sharpe = safe_float(metrics.get('sharpe_ratio', 0), 0)
        win_rate = safe_float(metrics.get('win_rate', 0), 0)
        drawdown = safe_float(metrics.get('max_drawdown', 100), 100)
        return_rate = safe_float(metrics.get('annual_return', 0), 0)
        
        # 综合评分（权重可配置）
        score = (
            sharpe * 0.4 +
            win_rate / 100 * 0.3 +
            (100 - drawdown) / 100 * 0.2 +
            return_rate / 100 * 0.1
        )
        return round(score, 4)
    
    # 构建结果
    result = {
        'version': '2.0',  # Phase 2 版本
        'task_id': task_id,
        'computed_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'computed_at_iso': datetime.now().isoformat(),
        'compute_duration_seconds': round(total_time, 1),
        'status': 'success',
        
        # 最优组合
        'best_combination': {
            'weights': best_weights,
            'weights_display': {
                FACTOR_NAMES.get(k, k): f"{v*100:.0f}%" if v > 0 else f"{v*100:.0f}% (反向)"
                for k, v in best_weights.items()
            },
            'metrics': convert_numpy_to_native(best_metrics),
            'score': calculate_score(best_metrics),
            'passed_constraints': best_combination.get('passed_constraints', False),
            'tier': best_combination.get('tier', 'unknown'),
            'icir': best_combination.get('icir', 0),
            'ic_bridge_score': best_combination.get('ic_bridge_score', None),
            'tolerance_applied': direction_tolerance,  # Phase 2
            'direction_valid': turnover_weight >= -direction_tolerance,  # Phase 2 验证
            # P0-2: 回测参数校验（新增）
            'backtest_validation_note': f"此权重基于 top_n={PRECOMPUTE_CONFIG['backtest']['top_n_output']} 回测验证（持仓{PRECOMPUTE_CONFIG['backtest']['top_n_output']}只股票）",
            'backtest_top_n': PRECOMPUTE_CONFIG['backtest']['top_n_output']
        },
        
        # 推荐股票（Top 20，API 按需取用）
        'top_stocks': [
            {
                'rank': i + 1,
                'code': s.get('code', ''),
                'name': s.get('name', ''),
                'score': round(s.get('total_score', 0), 2),
                'factor_values': convert_numpy_to_native(s.get('factor_scores', {}))
            }
            for i, s in enumerate(top_stocks)
        ],
        
        # Top 20 候选组合（供参考）—— P1-2: 扩展记录更多候选
        'top20_candidates': [
            {
                'rank': i + 1,
                'weights': convert_numpy_to_native(c.get('weights', {})),
                'metrics': convert_numpy_to_native(c.get('metrics', {})),
                'score': calculate_score(c.get('metrics', {})),
                'passed_constraints': c.get('passed_constraints', False),
                'tier': c.get('tier', 'unknown'),
                'ic_bridge_score': c.get('ic_bridge_score', None),
                'stability_score': c.get('stability_score', None),  # P1-1: 稳定性评分（如果有）
                'multi_top_n_results': c.get('multi_top_n_results', None)  # P1-1: 多 top_n 结果（如果有）
            }
            for i, c in enumerate(top_weights[:20])  # P1-2: 扩展到 Top 20
        ],
        
        # P1-2: 权重变化追踪（新增）
        'weights_tracking': {
            'top1_weights': convert_numpy_to_native(top_weights[0].get('weights', {})) if top_weights else {},
            'top2_weights': convert_numpy_to_native(top_weights[1].get('weights', {})) if len(top_weights) > 1 else {},
            'top3_weights': convert_numpy_to_native(top_weights[2].get('weights', {})) if len(top_weights) > 2 else {},
            'weights_variation_note': "记录 Top 3 权重组合，用于分析权重稳定性",
            'candidates_count': len(top_weights)
        },
        
        # 计算摘要
        'compute_summary': {
            'total_combinations_tested': len(grid_candidates),
            'backtest_combinations': len(backtest_candidates) if 'backtest_candidates' in dir() else len(validation_results) if 'validation_results' in dir() else 0,
            'passed_combinations': sum(1 for c in top_weights if c.get('passed_constraints', False)),
            'grid_search_time_seconds': round(grid_time, 1),
            'backtest_time_seconds': round(backtest_time, 1) if 'backtest_time' in dir() else 0,
            'stock_scoring_time_seconds': round(stock_time, 1) if 'stock_time' in dir() else 0,
            'memory_available_mb': mem_available
        },
        
        # Phase 2 配置记录
        'phase2_config': {
            'direction_tolerance': direction_tolerance,
            'sum_constraint_type': sum_constraint_config.get('type', 'sum_range'),
            'sum_range': sum_range,
            'ic_bridge_enabled': ic_bridge_config.get('enabled', True),
            'ic_bridge_top_n': ic_bridge_config.get('top_n_candidates', 200),
            'ic_bridge_backtest_n': ic_bridge_config.get('backtest_candidates', 20)
        },
        
        # 配置信息
        'config': PRECOMPUTE_CONFIG
    }
    
    # 原子写入结果文件
    success = atomic_write_json(result_file, result)
    
    if success:
        logger.info(f"结果写入成功: {result_file}")
    else:
        error_logger.error("结果写入失败")
        return {
            'success': False,
            'error': '结果写入失败',
            'task_id': task_id,
            'elapsed_seconds': total_time
        }
    
    # 写入推荐股票单独文件（简化版，供快速读取）
    top_stocks_file = CACHE_DIR / 'top_stocks.json'
    top_stocks_data = {
        'computed_at': result['computed_at'],
        'weights_used': best_weights,
        # 改进 1: 行业分布统计
        'industry_distribution': get_industry_distribution_from_stocks(top_stocks),
        # 改进 2: 回测窗口信息
        'backtest_window': backtest_window_info if 'backtest_window_info' in dir() else {
            'config_start': start_date if 'start_date' in dir() else '',
            'config_end': end_date if 'end_date' in dir() else '',
            'actual_days': actual_days if 'actual_days' in dir() else 0,
            '_comment': '改进 2: 实际回测窗口动态检测'
        },
        'stocks': result['top_stocks']
    }
    atomic_write_json(top_stocks_file, top_stocks_data)
    
    # 更新历史记录
    history_file = CACHE_DIR / 'compute_history.json'
    update_history(history_file, result)
    
    # ========== [预计算] 最终总结 ========== 
    logger.info(f"========== 预计算完成: {task_id} ========== ")
    logger.info(f"[总结] 各步骤耗时:")
    logger.info(f"  Step 0 前置检查: {step0_time:.1f}s")
    logger.info(f"  Step 1 三阶段搜索: {grid_time:.1f}s")
    logger.info(f"  Step 2 两阶段验证: {step2_time:.1f}s")
    logger.info(f"  Step 3 获取最优组合: {step3_time:.1f}s")
    logger.info(f"  Step 4 计算推荐股票: {step4_time:.1f}s")
    logger.info(f"  Step 5 写入结果: {step5_time:.1f}s")
    logger.info(f"[总结] 总耗时: {total_time:.1f}s")
    logger.info(f"[总结] 最终结果: Top ICIR={best_metrics.get('sharpe_ratio', 'N/A')}, "
                f"年化收益={best_metrics.get('annual_return', 'N/A')}")
    sys.stdout.flush()
    
    return result


def update_history(history_file: Path, result: Dict) -> bool:
    """
    更新历史计算记录（保留近 7 天）
    
    Args:
        history_file: 历史文件路径
        result: 当前计算结果
        
    Returns:
        bool: 是否成功
    """
    try:
        # 加载现有历史
        history = []
        if history_file.exists():
            with open(history_file, 'r', encoding='utf-8') as f:
                history = json.load(f).get('history', [])
        
        # 添加新记录（简化版）
        new_record = {
            'task_id': result['task_id'],
            'computed_at': result['computed_at'],
            'status': result['status'],
            'best_score': result['best_combination'].get('score', 0),
            'best_weights': result['best_combination'].get('weights', {}),
            'elapsed_seconds': result['compute_duration_seconds']
        }
        history.append(new_record)
        
        # 保留近 7 天（最多 7 条记录）
        history = history[-7:]
        
        # 写入
        history_data = {
            'version': '1.0',
            'updated_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'history': history
        }
        
        return atomic_write_json(history_file, history_data)
        
    except Exception as e:
        logger.warning(f"更新历史记录失败: {e}")
        return False


def get_precompute_status() -> Dict:
    """
    获取预计算状态
    
    Returns:
        Dict: 状态信息
    """
    result_file = CACHE_DIR / 'optimization_result.json'
    
    # 检查是否有结果文件
    if result_file.exists():
        try:
            with open(result_file, 'r', encoding='utf-8') as f:
                result = json.load(f)
            
            # 检查结果是否新鲜（24 小时内）
            # Python 3.6 兼容：替代 datetime.fromisoformat()
            iso_str = result.get('computed_at_iso', result.get('computed_at', ''))
            computed_at = None
            if iso_str:
                try:
                    if 'T' in iso_str:
                        # 处理 ISO 格式，可能包含微秒
                        iso_str = iso_str.replace('Z', '')
                        if '.' in iso_str:
                            computed_at = datetime.strptime(iso_str, '%Y-%m-%dT%H:%M:%S.%f')
                        else:
                            computed_at = datetime.strptime(iso_str, '%Y-%m-%dT%H:%M:%S')
                    else:
                        computed_at = datetime.strptime(iso_str, '%Y-%m-%d %H:%M:%S')
                except ValueError:
                    computed_at = None
            is_fresh = computed_at and (datetime.now() - computed_at).total_seconds() < 24 * 3600
            
            return {
                'status': 'completed',
                'last_run': result.get('computed_at', ''),
                'last_task_id': result.get('task_id', ''),
                'last_status': result.get('status', ''),
                'last_duration_seconds': result.get('compute_duration_seconds', 0),
                'is_fresh': is_fresh,
                'next_run': get_next_run_time()
            }
            
        except Exception as e:
            logger.error(f"读取状态失败: {e}")
            return {
                'status': 'error',
                'error': str(e)
            }
    
    else:
        return {
            'status': 'no_result',
            'message': '尚无预计算结果',
            'next_run': get_next_run_time()
        }


def get_next_run_time() -> str:
    """
    获取下次运行时间（凌晨 02:00）
    
    Returns:
        str: 下次运行时间字符串
    """
    now = datetime.now()
    next_run = now.replace(hour=2, minute=0, second=0, microsecond=0)
    
    # 如果当前时间已过今天 02:00，则下次运行是明天
    if now >= next_run:
        next_run += timedelta(days=1)
    
    return next_run.strftime('%Y-%m-%d %H:%M:%S')


def get_precompute_result(period: str = 'T1') -> Optional[Dict]:
    """
    获取v2优化结果（v3.16 优化：直接读取 optimization_T_*.json）
    
    Args:
        period: 周期类型，支持 T1/T3/T5（默认T1）
        
    Returns:
        Dict: 优化结果，如果不存在返回 None
    """
    # 验证period参数
    if period not in ['T1', 'T3', 'T5']:
        logger.warning(f"不支持的周期类型: {period}，使用默认值 T1")
        period = 'T1'
    
    # v2优化结果路径（直接读取 optimization_T_*.json）
    v2_output_dir = BASE_DIR / 'versions' / 'v2' / 'output'
    
    # 转换周期格式：T1 -> T_1, T3 -> T_3, T5 -> T_5
    file_period = f"T_{period[1]}"  # T1 -> T_1
    optimization_file = v2_output_dir / f'optimization_{file_period}.json'
    
    if not optimization_file.exists():
        logger.error(f"v2优化结果不存在: {optimization_file}")
        return None
    
    try:
        with open(optimization_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        # 转换为兼容格式（从 selections 字段读取股票列表）
        result = {
            'computed_at': data.get('computed_at', ''),
            'computed_at_iso': data.get('computed_at', ''),  # 使用同一字段
            'period': data.get('period', f'T+{period[1]}'),
            'date': data.get('date', ''),
            'best_combination': {
                'weights': data.get('weights', {}),
                'weights_display': data.get('weights', {}),
                'metrics': data.get('metrics', {}),
                'score': data.get('metrics', {}).get('sharpe_ratio', 0)
            },
            'top_stocks': data.get('selections', []),  # 关键修改：selections -> top_stocks
            'compute_summary': {
                'total_stocks': len(data.get('selections', [])),
                'period': data.get('period', f'T+{period[1]}')
            }
        }
        
        return result
        
    except Exception as e:
        logger.error(f"读取v2优化结果失败: {e}")
        return None


def get_top_stocks(n: int = 3) -> Optional[Dict]:
    """
    获取推荐股票（支持数量参数）
    
    Args:
        n: 返回股票数量（1-20）
        
    Returns:
        Dict: 推荐股票数据
    """
    if n < 1 or n > 20:
        n = 3  # 默认值
    
    result_file = CACHE_DIR / 'optimization_result.json'
    
    if result_file.exists():
        try:
            with open(result_file, 'r', encoding='utf-8') as f:
                result = json.load(f)
            
            top_stocks = result.get('top_stocks', [])
            
            return {
                'computed_at': result.get('computed_at', ''),
                'weights_used': result.get('best_combination', {}).get('weights', {}),
                'stocks': top_stocks[:n],
                'total_available': len(top_stocks)
            }
            
        except Exception as e:
            logger.error(f"读取推荐股票失败: {e}")
            return None
    
    return None


# ========== 主程序入口 ==========

if __name__ == '__main__':
    """主程序入口
    
    执行预计算流程，适合 systemd 定时任务调用
    """
    import argparse
    
    parser = argparse.ArgumentParser(description='因子组合优化预计算')
    parser.add_argument('--dry-run', action='store_true', help='模拟运行，不实际计算')
    parser.add_argument('--status', action='store_true', help='只查看状态，不执行计算')
    parser.add_argument('--verbose', '-v', action='store_true', help='详细日志')
    
    args = parser.parse_args()
    
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    
    if args.status:
        # 只查看状态
        status = get_precompute_status()
        print(json.dumps(status, ensure_ascii=False, indent=2))
        sys.exit(0)
    
    # 执行预计算
    result = run_precompute(dry_run=args.dry_run)
    
    # 输出结果摘要
    if result.get('status') == 'success':
        print("\n========== 预计算成功 ========== ")
        print(f"任务ID: {result.get('task_id')}")
        print(f"耗时: {result.get('compute_duration_seconds', 0):.1f}s")
        
        best = result.get('best_combination', {})
        print(f"\n最优组合:")
        print(f"  权重: {best.get('weights', {})}")
        print(f"  评分: {best.get('score', 0):.4f}")
        
        metrics = best.get('metrics', {})
        if metrics:
            print(f"  夏普: {metrics.get('sharpe_ratio', 'N/A')}")
            print(f"  回撤: {metrics.get('max_drawdown', 'N/A')}%")
            print(f"  胜率: {metrics.get('win_rate', 'N/A')}%")
        
        top_stocks = result.get('top_stocks', [])
        print(f"\n推荐股票 (Top {len(top_stocks)}):")
        for i, stock in enumerate(top_stocks[:5]):
            print(f"  #{i+1}: {stock.get('code')} {stock.get('name')} (得分: {stock.get('score', 0):.2f})")
        
        sys.exit(0)
    else:
        print("\n========== 预计算失败 ========== ")
        print(f"错误: {result.get('error', '执行失败')}")
        sys.exit(1)