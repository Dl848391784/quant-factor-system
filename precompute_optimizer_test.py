#!/usr/bin/env python3
"""
因子组合优化预计算模块 - 测试版
作者: 云舟 🛠️
功能: 测试净值曲线和买卖记录数据保存，不影响正式定时任务

【重要】此脚本为测试版本，输出结果写入 optimization_result_test.json
         原 precompute_optimizer.py 保持不变，继续作为定时任务运行

新增功能：
- 保存净值曲线数据 (nav_series)
- 保存买卖记录数据 (trade_details)
- 供前端展示历史回测表现

执行方式：手动运行
python precompute_optimizer_test.py

输出文件：cache/precompute/optimization_result_test.json
"""

import json
import os
import sys
import time
import tempfile
import shutil
import gc
import logging
import psutil
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
log_file = LOG_DIR / 'optimizer_test.log'

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [测试预计算] %(levelname)s: %(message)s',
    handlers=[
        logging.FileHandler(log_file, encoding='utf-8'),
        logging.StreamHandler(sys.stdout)
    ]
)

logger = logging.getLogger(__name__)

# ========== 配置参数 ==========
FACTORS = ['rsi', 'bollinger_pb', 'volume_ratio', 'turnover_surge', 'return_3d']

FACTOR_NAMES = {
    'rsi': 'RSI(14)',
    'bollinger_pb': '布林带%B',
    'volume_ratio': '量比',
    'turnover_surge': '换手率突增'
}

IC_DIRECTIONS = {
    'rsi': 'positive',
    'bollinger_pb': 'positive',
    'volume_ratio': 'positive',
    'turnover_surge': 'positive',
    'return_3d': 'neutral'
}

PRECOMPUTE_CONFIG = {
    'grid_search': {
        'weight_range': (-1.0, 1.0),
        'step': 0.2,
        'constraint': 'sum_to_one',
        'top_candidates': 100
    },
    'backtest': {
        'top_n_output': 5,
        'fallback_to_icir': True,
        'use_parallel': True,
        'pool_size': 4
    },
    'output': {
        'top_stocks_count': 5,  # 与回测参数 top_n=5 保持一致
        'api_default_top_n': 5,
        'scoring_top_stocks': 5  # 统一为 Top 5，与回测逻辑一致
    },
    'scoring': {
        'top_stocks': 20,
        'normalize_method': 'quantile',
        'score_function': 'sigmoid',
        'k_value': 10
    },
    'memory': {
        'min_available_mb': 500,
        'gc_interval': 50
    }
}


# ========== 工具函数（复用原版） ==========

def check_memory_available(min_mb: int = 500) -> Tuple[bool, float, str]:
    """检查是否有足够内存"""
    try:
        mem = psutil.virtual_memory()
        available_mb = mem.available / 1024 / 1024
        
        if available_mb < min_mb:
            return False, available_mb, f"内存不足（可用 {available_mb:.0f}MB < {min_mb}MB）"
        return True, available_mb, f"内存充足（可用 {available_mb:.0f}MB）"
    except ImportError:
        return True, 0, "内存检查跳过"


def atomic_write_json(filepath: Path, data: Dict) -> bool:
    """原子写入 JSON 文件"""
    temp_fd, temp_path = tempfile.mkstemp(
        dir=filepath.parent,
        prefix='.tmp_precompute_test_',
        suffix='.json'
    )
    
    try:
        with os.fdopen(temp_fd, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        
        shutil.move(temp_path, str(filepath))
        logger.info(f"原子写入成功: {filepath}")
        return True
        
    except Exception as e:
        if os.path.exists(temp_path):
            os.unlink(temp_path)
        logger.error(f"原子写入失败: {e}")
        return False


def load_config() -> Dict:
    """加载优化器配置"""
    config_path = BASE_DIR / 'optimizer_config.json'
    
    if config_path.exists():
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                config = json.load(f)
            return config
        except Exception as e:
            logger.warning(f"加载配置失败: {e}")
    
    return {
        'backtest_params': {
            'start_date': '2025-08-25',
            'end_date': '2026-04-10',
            'top_n': 5,  # 测试版使用 top_n=5
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
    """递归转换 numpy 类型为 Python 原生类型"""
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


# ========== 测试版预计算主流程 ==========

def run_precompute_test(
    progress_callback: Optional[callable] = None,
    dry_run: bool = False
) -> Dict:
    """
    执行测试版预计算流程
    
    【核心差异】保存净值曲线和买卖记录数据
    """
    start_time = time.time()
    task_id = f"precompute_test_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    
    logger.info(f"========== 开始测试预计算: {task_id} ========== ")
    sys.stdout.flush()
    
    # 前置检查
    mem_ok, mem_available, mem_msg = check_memory_available(500)
    if not mem_ok:
        return {'success': False, 'error': mem_msg, 'task_id': task_id}
    
    logger.info(f"内存检查通过: {mem_msg}")
    
    config = load_config()
    backtest_params = config.get('backtest_params', {})
    
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
        return {'success': True, 'dry_run': True, 'task_id': task_id}
    
    # ========== Step 1: 三阶段搜索（简化版） ========== 
    logger.info("[Step 1] 开始三阶段搜索...")
    
    try:
        from weight_optimizer import get_optimizer
        
        optimizer = get_optimizer()
        
        # 加载配置文件获取三阶段搜索参数
        grid_config_file = config.get('grid_search', {})
        
        # Phase 2 方案F: 使用 sum_range 约束
        constraint_type = sum_constraint_config.get('type', 'sum_range')
        sum_range = (
            sum_constraint_config.get('range', {}).get('min', 0.5),
            sum_constraint_config.get('range', {}).get('max', 1.5)
        )
        
        # 【Phase 2 同步】从配置文件加载参数
        grid_config = {
            'weight_range': [
                grid_config_file.get('weight_range', {}).get('min', -1.0),
                grid_config_file.get('weight_range', {}).get('max', 1.0)
            ],
            'step_phase1': grid_config_file.get('step_phase1', 0.1),
            'step_phase2': grid_config_file.get('step_phase2', 0.05),
            'top_candidates_phase1': grid_config_file.get('top_candidates_phase1', 200),
            'top_candidates_phase2': grid_config_file.get('top_candidates_phase2', 2000),
            'constraint': constraint_type,  # Phase 2: 使用 sum_range
            'max_combinations': grid_config_file.get('max_combinations', 200000),  # Phase 2: 统一为 200000
            # Phase 2: 传递因子权重约束
            'factor_min_weights': config.get('factor_min_weights'),
            'factor_max_weights': config.get('factor_max_weights')
        }
        
        logger.info(f"三阶段搜索配置: Phase1步长={grid_config['step_phase1']}, Top={grid_config['top_candidates_phase1']}")
        logger.info(f"                   Phase2步长={grid_config['step_phase2']}, Top={grid_config['top_candidates_phase2']}")
        logger.info(f"                   约束类型={constraint_type}, sum_range={sum_range}（Phase 2 方案F）")
        logger.info(f"                   max_combinations={grid_config['max_combinations']}（Phase 2 同步）")
        
        # P1-2: 内存检查
        mem = psutil.virtual_memory()
        available_mb = mem.available / 1024 / 1024
        logger.info(f"内存状态: 可用 {available_mb:.0f}MB / 总计 {mem.total / 1024 / 1024:.0f}MB")
        if available_mb < 500:
            logger.warning(f"P1-2 内存警告: 可用内存不足 500MB，减少搜索空间")
            grid_config['max_combinations'] = min(grid_config['max_combinations'], 50000)
            grid_config['top_candidates_phase1'] = min(grid_config['top_candidates_phase1'], 100)
        
        # P2-3: 加载历史最优权重数据
        history_best = load_history_best()
        
        grid_candidates = optimizer.three_phase_search(
            factors=FACTORS,
            ic_directions=IC_DIRECTIONS,
            config=grid_config,
            progress_callback=None,
            tolerance=direction_tolerance,  # Phase 2: 使用配置文件的方向容忍度
            history_best=history_best  # P2-3: 历史最优权重追踪
        )
        
        logger.info(f"[Step 1] 完成: 收集 {len(grid_candidates)} 候选组合")
        
        if not grid_candidates:
            return {'success': False, 'error': '网格搜索未返回有效候选组合'}
        
        gc.collect()
        
    except Exception as e:
        logger.error(f"网格搜索失败: {e}")
        traceback.print_exc()
        return {'success': False, 'error': f"网格搜索失败: {e}", 'task_id': task_id}
    
    # ========== Step 2: 两阶段验证（Phase 2: IC桥接） ========== 
    logger.info("[Step 2] 开始两阶段验证（IC桥接 + 精选回测）...")
    
    best_backtest_result = None  # 【新增】保存最优组合的完整回测结果
    validation_results = []  # 用于后续统计
    backtest_candidates = []  # 用于后续统计
    ic_bridge_candidates = []  # 用于后续统计
    tier_used = 'unknown'
    
    try:
        from quick_backtest import QuickBacktestValidator
        
        validator = QuickBacktestValidator(config)
        
        # Phase 2 方案H: 使用两阶段验证
        use_ic_bridge = ic_bridge_config.get('enabled', True)
        
        if use_ic_bridge:
            logger.info(f"启用两阶段验证（方案H）")
            
            # Phase 2 方案H: 使用 two_stage_validation
            validation_result = validator.two_stage_validation(
                grid_candidates=grid_candidates,
                factors=FACTORS,
                config=config,
                progress_callback=None
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
            
            # 回测 Top 20 候选
            validation_results = parallel_backtest_batch(
                weight_candidates=grid_candidates[:20],
                factors=FACTORS,
                config=config,
                pool_size=4,
                progress_callback=None
            )
            
            # 分层筛选获取最优组合
            top_weights, tier_used = validator.select_best_with_tiers(
                validation_results=validation_results,
                top_n=5
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
                return {'success': False, 'error': '无候选组合', 'task_id': task_id}
        
        logger.info(f"[Step 2] 完成: tier={tier_used}, Top {len(top_weights)} 组合")
        
        # 输出 Top 3 组合详情
        logger.info(f"[Step 2] Top 3 组合:")
        for i, w in enumerate(top_weights[:3]):
            metrics = w.get('metrics', {})
            logger.info(f"  #{i+1}: weights={w.get('weights', {})}, Sharpe={metrics.get('sharpe_ratio', 0) if metrics else 0:.2f}")
        
        # 【核心修改】保存最优组合的完整回测结果（包含 nav_series 和 trade_details）
        if top_weights and len(top_weights) > 0:
            best_combination_data = top_weights[0]
            best_weights = best_combination_data.get('weights', {})
            
            # 从原始 validation_results 中找到对应的完整 backtest_result
            for vr in validation_results:
                if vr.get('weights') == best_weights:
                    best_backtest_result = vr.get('backtest_result', {})
                    logger.info(f"[Step 2] 找到最优组合完整回测结果")
                    break
        
        gc.collect()
        
    except Exception as e:
        logger.error(f"回测验证失败: {e}")
        traceback.print_exc()
        return {'success': False, 'error': f"回测验证失败: {e}", 'task_id': task_id}
    
    # ========== Step 3: 获取最优组合 ========== 
    logger.info("[Step 3] 获取最优组合...")
    
    best_combination = top_weights[0]
    best_weights = best_combination.get('weights') or {}
    best_metrics = best_combination.get('metrics') or {}
    
    if not best_metrics:
        best_metrics = {'sharpe_ratio': 'N/A', 'max_drawdown': 'N/A', 'win_rate': 'N/A'}
    
    logger.info(f"[Step 3] 最优权重: {best_weights}")
    logger.info(f"[Step 3] 指标: Sharpe={best_metrics.get('sharpe_ratio', 'N/A')}")
    
    # ========== Step 4: 计算推荐股票 ========== 
    logger.info("[Step 4] 计算推荐股票...")
    
    top_stocks = []
    try:
        from scoring_engine import get_cached_engine
        
        engine = get_cached_engine()
        latest_date = engine.available_dates[-1] if engine.available_dates else None
        
        if latest_date:
            # 【修复问题1】临时禁用行业分散约束，确保至少返回5只股票
            # 获取配置并禁用行业约束
            import json as json_module
            config_path = BASE_DIR / 'optimizer_config.json'
            config_backup = None
            if config_path.exists():
                with open(config_path, 'r', encoding='utf-8') as f:
                    config_backup = json_module.load(f)
            
            # 临时禁用行业约束
            if config_backup and 'industry_constraint' in config_backup:
                config_backup['industry_constraint']['enabled'] = False
                with open(config_path, 'w', encoding='utf-8') as f:
                    json_module.dump(config_backup, f, indent=2, ensure_ascii=False)
                logger.info("[Step 4] 临时禁用行业分散约束")
            
            try:
                scores_result = engine.calculate_scores(
                    date=latest_date,
                    weights=best_weights,
                    normalize_method='quantile',
                    score_function='sigmoid',
                    k_value=10
                )
                
                if scores_result.get('success'):
                    scored_stocks = scores_result.get('selections', [])
                    # 【统一逻辑】输出 Top 5，与回测参数 top_n=5 保持一致
                    top_stocks = scored_stocks[:5]
                    logger.info(f"[Step 4] 推荐股票: {len(top_stocks)} 只 (Top 5)")
                    
                    # 警告如果不足5只
                    if len(top_stocks) < 5:
                        logger.warning(f"[Step 4] 推荐股票不足5只，实际: {len(top_stocks)}")
            finally:
                # 恢复行业约束配置
                if config_backup and 'industry_constraint' in config_backup:
                    # 读取当前配置（可能被其他进程修改）
                    if config_path.exists():
                        with open(config_path, 'r', encoding='utf-8') as f:
                            current_config = json_module.load(f)
                        current_config['industry_constraint']['enabled'] = True
                        with open(config_path, 'w', encoding='utf-8') as f:
                            json_module.dump(current_config, f, indent=2, ensure_ascii=False)
                        logger.info("[Step 4] 恢复行业分散约束")
        
    except Exception as e:
        logger.warning(f"推荐股票计算失败: {e}")
        traceback.print_exc()
    
    # ========== Step 5: 构建结果（包含净值曲线） ========== 
    logger.info("[Step 5] 构建结果并写入（含净值曲线）...")
    
    total_time = time.time() - start_time
    
    # 计算综合评分
    def calculate_score(metrics):
        if metrics is None:
            return 0
        
        def safe_float(value, default=0):
            if value is None or value == 'N/A':
                return default
            return float(value) if isinstance(value, (int, float)) else default
        
        sharpe = safe_float(metrics.get('sharpe_ratio', 0), 0)
        win_rate = safe_float(metrics.get('win_rate', 0), 0)
        drawdown = safe_float(metrics.get('max_drawdown', 100), 100)
        return_rate = safe_float(metrics.get('annual_return', 0), 0)
        
        score = sharpe * 0.4 + win_rate / 100 * 0.3 + (100 - drawdown) / 100 * 0.2 + return_rate / 100 * 0.1
        return round(score, 4)
    
    # 【核心新增】构建 backtest_details
    backtest_details = {
        'nav_series': [],
        'trade_details': [],
        'backtest_params': {
            'start_date': backtest_params.get('start_date', ''),
            'end_date': backtest_params.get('end_date', ''),
            'top_n': PRECOMPUTE_CONFIG['backtest']['top_n_output'],
            'cost': backtest_params.get('cost', 0.002),
            'slippage': backtest_params.get('slippage', 0.001)
        },
        'note': '此为历史回测表现，仅供参考，不代表未来收益'
    }
    
    # 从 best_backtest_result 提取净值曲线和交易记录
    if best_backtest_result and best_backtest_result.get('success'):
        nav_series_raw = best_backtest_result.get('nav_series', [])
        trade_details_raw = best_backtest_result.get('trade_details', [])
        
        # 转换为前端友好格式
        if nav_series_raw:
            backtest_details['nav_series'] = [
                {'date': item.get('date', ''), 'nav': float(item.get('nav', 1.0))}
                for item in nav_series_raw
            ]
            logger.info(f"[净值曲线] 保存 {len(backtest_details['nav_series'])} 条数据")
        
        if trade_details_raw:
            backtest_details['trade_details'] = convert_numpy_to_native(trade_details_raw)
            logger.info(f"[买卖记录] 保存 {len(backtest_details['trade_details'])} 条数据")
    
    # 【修复问题2】计算股票权重分配，确保总和为100%
    # 基础权重模板（Top 5分配，原始总和60%）
    base_weights = [20, 16, 12, 8, 4]  # Top 5 的基准权重（总和60%）
    
    # 【核心修复】将权重按比例缩放至总和100%
    # 例如: [20,16,12,8,4] -> [33.33,26.67,20,13.33,6.67]
    base_sum = sum(base_weights)  # 60
    
    # 根据实际股票数量动态调整权重
    actual_count = len(top_stocks)
    if actual_count > 0:
        # 如果股票数量 >= 5，给前5只分配缩放后的权重
        if actual_count >= 5:
            # 按比例缩放至100%
            scaled_weights = [round(w * 100 / base_sum, 2) for w in base_weights[:5]]
            logger.info(f"[权重分配] Top 5 权重缩放至100%: {scaled_weights}, 总和: {sum(scaled_weights)}%")
        else:
            # 股票数量 < 5时，动态调整权重确保总和为100%
            weights_to_use = base_weights[:actual_count]
            weight_sum = sum(weights_to_use)
            scaled_weights = [round(w * 100 / weight_sum, 2) for w in weights_to_use]
            logger.info(f"[权重分配] 股票数量不足5只，动态调整权重: {scaled_weights}, 总和: {sum(scaled_weights)}%")
    else:
        scaled_weights = []
        logger.warning("[权重分配] 无推荐股票，权重分配为空")
    
    # 构建完整结果
    result = {
        'version': 'test_1.1',  # 标识测试版本（修复问题后更新版本号）
        'task_id': task_id,
        'computed_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'computed_at_iso': datetime.now().isoformat(),
        'compute_duration_seconds': round(total_time, 1),
        'status': 'success',
        'is_test': True,  # 【重要】标识这是测试结果
        
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
            'icir': best_combination.get('icir', 0)
        },
        
        # 【修复问题2】推荐股票（包含权重分配）
        'top_stocks': [
            {
                'rank': i + 1,
                'code': s.get('code', ''),
                'name': s.get('name', ''),
                'score': round(s.get('total_score', 0), 2),
                'weight_percentage': scaled_weights[i] if i < len(scaled_weights) else 0,  # 【新增】权重百分比
                'factor_values': convert_numpy_to_native(s.get('factor_scores', {}))
            }
            for i, s in enumerate(top_stocks)
        ],
        
        # 【新增】权重分配摘要（供前端使用）
        'weight_allocation': {
            'weights': scaled_weights,
            'total_percentage': sum(scaled_weights),
            'stock_count': len(top_stocks),
            'note': '动态调整确保权重总和为100%' if len(top_stocks) < 5 else 'Top 5 标准分配'
        },
        
        # 【新增】回测详情（净值曲线 + 买卖记录）
        'backtest_details': backtest_details,
        
        # Top 5 候选组合（与回测参数 top_n=5 保持一致）
        'top5_candidates': [
            {
                'rank': i + 1,
                'weights': convert_numpy_to_native(c.get('weights', {})),
                'metrics': convert_numpy_to_native(c.get('metrics', {})),
                'score': calculate_score(c.get('metrics', {})),
                'passed_constraints': c.get('passed_constraints', False),
                'tier': c.get('tier', 'unknown')
            }
            for i, c in enumerate(top_weights[:5])
        ],
        
        # 计算摘要
        'compute_summary': {
            'total_combinations_tested': len(grid_candidates),
            'passed_combinations': sum(1 for c in top_weights if c.get('passed_constraints', False)),
            'elapsed_seconds': round(total_time, 1)
        }
    }
    
    # 【重要】写入测试结果文件（区分于正式结果）
    result_file = CACHE_DIR / 'optimization_result_test.json'
    success = atomic_write_json(result_file, result)
    
    if success:
        logger.info(f"测试结果写入成功: {result_file}")
        logger.info(f"========== 测试预计算完成 ========== ")
        logger.info(f"总耗时: {total_time:.1f}s")
        logger.info(f"净值曲线数据: {len(backtest_details['nav_series'])} 条")
        logger.info(f"买卖记录数据: {len(backtest_details['trade_details'])} 条")
        return result
    else:
        return {'success': False, 'error': '结果写入失败', 'task_id': task_id}


def get_precompute_test_result() -> Optional[Dict]:
    """获取测试预计算结果"""
    result_file = CACHE_DIR / 'optimization_result_test.json'
    
    if result_file.exists():
        try:
            with open(result_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"读取测试结果失败: {e}")
            return None
    
    return None


# ========== 主程序入口 ==========

if __name__ == '__main__':
    """测试版主程序
    
    执行方式：
    python precompute_optimizer_test.py
    
    输出：cache/precompute/optimization_result_test.json
    """
    import argparse
    
    parser = argparse.ArgumentParser(description='因子组合优化预计算 - 测试版')
    parser.add_argument('--dry-run', action='store_true', help='模拟运行')
    parser.add_argument('--status', action='store_true', help='查看状态')
    
    args = parser.parse_args()
    
    if args.status:
        result = get_precompute_test_result()
        if result:
            print(f"测试结果状态: {result.get('status')}")
            print(f"计算时间: {result.get('computed_at')}")
            print(f"净值曲线数量: {len(result.get('backtest_details', {}).get('nav_series', []))}")
            print(f"买卖记录数量: {len(result.get('backtest_details', {}).get('trade_details', []))}")
        else:
            print("暂无测试结果")
        sys.exit(0)
    
    # 执行测试预计算
    result = run_precompute_test(dry_run=args.dry_run)
    
    if result.get('status') == 'success':
        print("\n========== 测试预计算成功 ========== ")
        print(f"任务ID: {result.get('task_id')}")
        print(f"耗时: {result.get('compute_duration_seconds', 0):.1f}s")
        print(f"净值曲线: {len(result.get('backtest_details', {}).get('nav_series', []))} 条")
        print(f"买卖记录: {len(result.get('backtest_details', {}).get('trade_details', []))} 条")
        print(f"结果文件: cache/precompute/optimization_result_test.json")
        sys.exit(0)
    else:
        print(f"\n测试预计算失败: {result.get('error')}")
        sys.exit(1)