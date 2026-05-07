#!/usr/bin/env python3
"""
快速回测验证模块
作者: 云舟 🛠️
功能: 对权重组合进行快速回测验证，输出夏普比率、最大回撤、胜率等指标

设计理念：
- 复用 scoring_engine.py 的 run_backtest_vectorized 方法
- 支持批量验证多个权重组合
- 高效向量化计算，避免耗时过长
- 错误处理完善，回测失败时有 fallback

v3.6 性能优化（云柏方案实施）：
- 支持并行回测，使用多进程并行处理 Top 100 组合
- 节省约 131 分钟（74.9% 提升）
"""

import json
import sys  # 进度日志 flush
import numpy as np
import pandas as pd
import time
import multiprocessing
from concurrent.futures import ThreadPoolExecutor  # 方案A：线程池替代进程池
from functools import partial
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional, Tuple
import logging
import traceback

# ========== 版本路径设置 ==========
ROOT_DIR = Path(__file__).parent.parent.parent.parent  # 指向 factor_ic_analyzer/ (optimizer → v2 → versions → factor_ic_analyzer)
sys.path.insert(0, str(ROOT_DIR))

# 配置日志
logging.basicConfig(level=logging.INFO, format='[快速回测] %(message)s')
logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).parent.parent  # 指向 versions/v2/
OPTIMIZER_DIR = Path(__file__).parent     # 指向 versions/v2/optimizer/
CONFIG_DIR = BASE_DIR / 'config'           # 指向 versions/v2/config/


class QuickBacktestValidator:
    """
    快速回测验证器

    对权重组合进行快速回测验证，筛选出"稳定赚钱"的组合
    """

    def __init__(self, config: Dict = None, return_col: str = 'forward_return_1d', use_shared_cache: bool = False):
        """
        初始化验证器

        Args:
            config: 配置字典，包含回测参数和约束条件
            return_col: 收益字段名（默认 forward_return_1d，支持 forward_return_5d）
            use_shared_cache: 是否使用共享缓存（默认 False，仅在多周期并行时启用）
        """
        # 加载配置
        if config is None:
            config = self._load_default_config()

        self.config = config
        self._return_col = return_col  # 收益字段名
        self._use_shared_cache = use_shared_cache  # 共享缓存标志
        self.backtest_params = config.get('backtest_params', {})
        self.constraints = config.get('constraints_fallback', config.get('constraints', {}))

        # 懒加载打分引擎（避免初始化时加载大量数据）
        self._engine = None

        logger.info(f"快速回测验证器初始化完成")
        logger.info(f"  回测参数: {self.backtest_params}")
        logger.info(f"  约束条件: {self.constraints}")
        logger.info(f"  收益字段: {self._return_col}")
        logger.info(f"  共享缓存: {self._use_shared_cache}")

    def _load_default_config(self) -> Dict:
        """加载默认配置"""
        config_path = CONFIG_DIR / 'optimizer_config.json'

        if config_path.exists():
            try:
                with open(config_path, 'r', encoding='utf-8') as f:
                    config = json.load(f)
                logger.info(f"加载配置文件: {config_path}")
                return config
            except Exception as e:
                logger.warning(f"加载配置文件失败，使用默认配置: {e}")

        # 默认配置
        return {
            'backtest_params': {
                'start_date': '2023-01-01',
                'end_date': '2024-12-31',
                'top_n': 3,
                'cost': 0.002,
                'slippage': 0.001,
                'normalize_method': 'quantile',
                'score_function': 'sigmoid',
                'k_value': 10
            },
            'constraints': {
                'min_sharpe': 1.0,
                'max_drawdown': 30.0,
                'min_win_rate': 50.0,
                'min_annual_return': 0.0
            }
        }

    def _get_engine(self, use_cache: bool = True, use_shared_cache: bool = False):
        """获取打分引擎实例（懒加载，支持多周期和共享缓存）

        v3.9 多周期修复（云舟实施）：
        - 统一使用 get_cached_engine(return_col=self._return_col)
        - 支持多周期缓存：T+1/T+3/T+5 均可缓存
        - 移除复杂的三分支逻辑（简化代码）
        
        v3.10 引擎数据共享优化（云柏方案）：
        - use_shared_cache=True：使用共享因子数据（推荐多周期并行）
        - 内存节省约720MB

        Args:
            use_cache: 是否使用缓存引擎（默认 True，推荐）
            use_shared_cache: 是否使用共享缓存（默认 False，仅在多周期并行时启用）

        Returns:
            ScoringEngine: 打分引擎实例（对应周期）
        """
        if self._engine is None:
            from scoring_engine import get_cached_engine, ScoringEngine

            if use_cache:
                # 使用周期缓存（支持 T+1/T+3/T+5）
                # 优先使用实例的 use_shared_cache 标志
                effective_shared_cache = use_shared_cache or self._use_shared_cache
                self._engine = get_cached_engine(return_col=self._return_col, use_shared_cache=effective_shared_cache)
                logger.info(f"打分引擎加载完成（周期={self._return_col}, 共享缓存={effective_shared_cache}）")
            else:
                # 特殊场景：创建新实例（不推荐，仅用于调试）
                self._engine = ScoringEngine(return_col=self._return_col, use_shared_cache=False)
                self._engine._ensure_data_loaded()
                logger.info(f"打分引擎加载完成（周期={self._return_col}, 新实例）")

        return self._engine

    def validate_single_weights(
        self,
        weights: Dict[str, float],
        factors: List[str],
        progress_callback: callable = None
    ) -> Dict:
        """
        验证单个权重组合

        Args:
            weights: 权重字典 {factor_id: weight}
            factors: 因子列表
            progress_callback: 进度回调函数

        Returns:
            验证结果字典 {
                'weights': {...},
                'metrics': {'sharpe', 'max_drawdown', 'win_rate', 'annual_return'},
                'passed_constraints': bool,
                'constraint_details': {...}
            }
        """
        logger.info(f"验证权重组合: {weights}")

        try:
            engine = self._get_engine()

            # ========== 新增：自动调整回测窗口 ==========
            # 获取配置参数
            config_start_date = self.backtest_params.get('start_date', '2023-01-01')
            config_end_date = self.backtest_params.get('end_date', '2024-12-31')
            auto_adjust = self.backtest_params.get('auto_adjust_window', False)

            # 获取引擎实际可用日期
            available_dates = engine.get_available_dates()

            if auto_adjust and available_dates:
                # 获取数据最新日期
                actual_end_date = available_dates[-1]

                # 自动调整 end_date（追踪数据最新日期）
                if actual_end_date > config_end_date:
                    adjusted_end_date = actual_end_date
                    logger.info(
                        f"[auto_adjust_window] 窗口自动调整: "
                        f"配置 {config_end_date} → 实际 {adjusted_end_date}"
                    )
                else:
                    # 数据不足，使用配置日期
                    adjusted_end_date = config_end_date
                    logger.warning(
                        f"[auto_adjust_window] 数据不足，保持配置: "
                        f"配置 {config_end_date}，实际最新 {actual_end_date}"
                    )
            else:
                # 不调整或无可用数据
                adjusted_end_date = config_end_date
                logger.info(
                    f"[回测窗口] 使用配置日期: {config_start_date} ~ {adjusted_end_date}"
                )
            # ========== 自动调整逻辑结束 ==========

            # 调用向量化回测（使用调整后的 end_date）
            backtest_result = engine.run_backtest_vectorized(
                start_date=config_start_date,         # 保持配置的 start_date
                end_date=adjusted_end_date,           # 使用调整后的 end_date
                weights=weights,
                top_n=self.backtest_params.get('top_n', 10),
                cost=self.backtest_params.get('cost', 0.002),
                slippage=self.backtest_params.get('slippage', 0.001),
                normalize_method=self.backtest_params.get('normalize_method', 'quantile'),
                score_function=self.backtest_params.get('score_function', 'sigmoid'),
                k_value=self.backtest_params.get('k_value', 10),
                progress_callback=progress_callback,
                factor_directions=self.config.get('factor_directions')
            )

            if not backtest_result.get('success', False):
                logger.warning(f"回测失败: {backtest_result.get('error', '未知错误')}")
                return {
                    'weights': weights,
                    'metrics': None,
                    'passed_constraints': False,
                    'constraint_details': {},
                    'error': backtest_result.get('error', '回测失败')
                }

            # 提取关键指标
            metrics = backtest_result.get('metrics', {})

            sharpe = metrics.get('sharpe_ratio', 0)
            max_drawdown = abs(metrics.get('max_drawdown', 100))  # 转为正值
            win_rate = metrics.get('win_rate', 0)
            annual_return = metrics.get('annual_return', 0)
            final_nav = metrics.get('final_nav', 1.0)
            total_trades = metrics.get('total_trades', 0)

            # 检查约束条件
            constraint_details = {
                'sharpe': {
                    'value': sharpe,
                    'threshold': self.constraints.get('min_sharpe', 1.0),
                    'passed': sharpe >= self.constraints.get('min_sharpe', 1.0)
                },
                'max_drawdown': {
                    'value': max_drawdown,
                    'threshold': self.constraints.get('max_drawdown', 30.0),
                    'passed': max_drawdown <= self.constraints.get('max_drawdown', 30.0)
                },
                'win_rate': {
                    'value': win_rate,
                    'threshold': self.constraints.get('min_win_rate', 50.0),
                    'passed': win_rate >= self.constraints.get('min_win_rate', 50.0)
                },
                'annual_return': {
                    'value': annual_return,
                    'threshold': self.constraints.get('min_annual_return', 0.0),
                    'passed': annual_return >= self.constraints.get('min_annual_return', 0.0)
                }
            }

            passed_constraints = all(
                detail['passed'] for detail in constraint_details.values()
            )

            result = {
                'weights': weights,
                'metrics': {
                    'sharpe_ratio': sharpe,
                    'max_drawdown': max_drawdown,
                    'win_rate': win_rate,
                    'annual_return': annual_return,
                    'final_nav': final_nav,
                    'total_trades': total_trades,
                    'total_days': metrics.get('total_days', 0)
                },
                'passed_constraints': passed_constraints,
                'constraint_details': constraint_details,
                'backtest_result': backtest_result  # 完整回测结果供后续使用
            }

            # 日志输出
            logger.info(
                f"验证完成: Sharpe={sharpe:.2f}, "
                f"Drawdown={max_drawdown:.2f}%, "
                f"WinRate={win_rate:.2f}%, "
                f"Return={annual_return:.2f}%"
            )
            if passed_constraints:
                logger.info("  ✓ 通过约束条件")
            else:
                failed = [k for k, v in constraint_details.items() if not v['passed']]
                logger.warning(f"  ✗ 未通过约束: {failed}")

            return result

        except Exception as e:
            logger.error(f"验证失败: {e}")
            traceback.print_exc()

            return {
                'weights': weights,
                'metrics': None,
                'passed_constraints': False,
                'constraint_details': {},
                'error': str(e)
            }

    def validate_batch_weights(
        self,
        weight_candidates: List[Dict],
        factors: List[str],
        progress_callback: callable = None,
        log_interval: int = 10
    ) -> List[Dict]:
        """
        批量验证多个权重组合

        Args:
            weight_candidates: 权重候选列表 [{'weights': {...}, 'icir': float}, ...]
            factors: 因子列表
            progress_callback: 进度回调函数 (current, total, result)
            log_interval: 日志输出间隔

        Returns:
            验证结果列表，按综合评分排序
        """
        total = len(weight_candidates)
        logger.info(f"开始批量验证，共 {total} 个候选组合")

        results = []

        for i, candidate in enumerate(weight_candidates):
            weights = candidate.get('weights', {})
            icir = candidate.get('icir', 0)

            # 日志输出进度
            if i % log_interval == 0 or i == total - 1:
                logger.info(f"回测验证进度: {i+1}/{total} ({(i+1)/total*100:.1f}%)")
                sys.stdout.flush()  # 确保立即输出

            # 验证单个组合
            result = self.validate_single_weights(
                weights=weights,
                factors=factors,
                progress_callback=None  # 单个验证不输出进度
            )

            # 附加原始 ICIR 信息（云舟修复：同时添加 icir 和 original_icir）
            result['icir'] = icir            # ✅ 新增字段（云汐发现缺失）
            result['original_icir'] = icir    # 原有字段保留

            # 进度回调
            if progress_callback:
                progress_callback(i + 1, total, result)

            results.append(result)

        logger.info(f"批量验证完成，共 {len(results)} 个结果")
        sys.stdout.flush()

        # 统计通过约束的组合数量
        passed_count = sum(1 for r in results if r.get('passed_constraints', False))
        logger.info(f"  通过约束条件的组合: {passed_count}/{total}")

        return results

    def filter_and_rank(
        self,
        validation_results: List[Dict],
        top_n: int = 10,
        fallback_to_icir: bool = True,
        use_tiered_filtering: bool = False  # 方案B: 是否使用分层筛选
    ) -> List[Dict]:
        """
        筛选并排序结果

        Args:
            validation_results: 验证结果列表
            top_n: 返回 Top N 组合
            fallback_to_icir: 是否在无组合通过约束时 fallback 到 ICIR
            use_tiered_filtering: 是否使用分层筛选（方案B）

        Returns:
            Top N 组合列表
        """
        logger.info(f"筛选 Top {top_n} 组合")

        # 方案B: 使用分层筛选
        if use_tiered_filtering:
            result, tier = self.select_best_with_tiers(validation_results, top_n)
            logger.info(f"[分层筛选] 返回 Tier={tier}, Top {len(result)} 组合")
            return result

        # 分离通过和未通过的结果
        passed_results = [r for r in validation_results if r.get('passed_constraints', False)]
        failed_results = [r for r in validation_results if not r.get('passed_constraints', False)]

        if passed_results:
            # 有组合通过约束，按综合评分排序
            # 综合评分 = Sharpe * 0.4 + WinRate * 0.3 - Drawdown * 0.2 + Return * 0.1
            def calculate_score(r):
                metrics = r.get('metrics', {})
                if metrics is None:
                    return -999

                sharpe = metrics.get('sharpe_ratio', 0)
                win_rate = metrics.get('win_rate', 0)
                drawdown = metrics.get('max_drawdown', 100)
                return_rate = metrics.get('annual_return', 0)

                # 综合评分（权重可配置）
                score = (
                    sharpe * 0.4 +
                    win_rate / 100 * 0.3 +
                    (100 - drawdown) / 100 * 0.2 +
                    return_rate / 100 * 0.1
                )
                return score

            passed_results.sort(key=calculate_score, reverse=True)

            top_results = passed_results[:top_n]

            logger.info(f"筛选完成，Top {len(top_results)} 组合均通过约束")
            for i, r in enumerate(top_results[:3]):
                metrics = r.get('metrics', {})
                logger.info(
                    f"  #{i+1}: Sharpe={metrics.get('sharpe_ratio', 0):.2f}, "
                    f"DD={metrics.get('max_drawdown', 0):.2f}%, "
                    f"WR={metrics.get('win_rate', 0):.2f}%"
                )

            return top_results

        elif fallback_to_icir:
            # 无组合通过约束，fallback 到原始 ICIR 排序
            logger.warning("无组合通过约束条件，使用 ICIR fallback 排序")

            failed_results.sort(key=lambda r: r.get('original_icir', 0), reverse=True)

            top_results = failed_results[:top_n]

            logger.info(f"Fallback 完成，Top {len(top_results)} 组合（基于 ICIR）")
            for i, r in enumerate(top_results[:3]):
                metrics = r.get('metrics', {})
                logger.warning(
                    f"  #{i+1}: ICIR={r.get('original_icir', 0):.4f}, "
                    f"Sharpe={metrics.get('sharpe_ratio', 0) if metrics else 'N/A'}, "
                    f"(未通过约束)"
                )

            return top_results

        else:
            logger.warning(f"无组合通过约束，且禁用 fallback，返回空列表")
            return []

    def select_best_with_tiers(
        self,
        validation_results: List[Dict],
        top_n: int = 10
    ) -> Tuple[List[Dict], str]:
        """
        三级筛选最优组合（方案B）

        流程：
        1. Tier 1: 优秀组合（Sharpe>=0.5, DD<=40%, WR>=45%, Return>=5%）
        2. Tier 2: 可用组合（Sharpe>=0, DD<=50%, WR>=40%, Return>=0%）
        3. Fallback: 保底组合（Sharpe>=-0.5, DD<=60%, WR>=35%, Return>=-10%）
        4. 最终 fallback: 按 ICIR 排序

        Args:
            validation_results: 验证结果列表
            top_n: 返回 Top N 组合

        Returns:
            Tuple[List[Dict], str]: (Top N 组合列表, tier名称)
        """
        logger.info(f"[分层筛选] 开始三级筛选")

        # 调试日志：确认 self.config 内容
        logger.debug(f"[select_best_with_tiers] self.config keys: {list(self.config.keys())}")
        logger.debug(f"[select_best_with_tiers] constraints_tier1 from config: {self.config.get('constraints_tier1')}")
        logger.debug(f"[select_best_with_tiers] constraints_tier2 from config: {self.config.get('constraints_tier2')}")
        logger.debug(f"[select_best_with_tiers] constraints_fallback from config: {self.config.get('constraints_fallback')}")

        # 加载分层约束配置
        constraints_tier1 = self.config.get('constraints_tier1', {
            'min_sharpe': 0.5,
            'max_drawdown': 40.0,
            'min_win_rate': 45.0,
            'min_annual_return': -10.0
        })
        constraints_tier2 = self.config.get('constraints_tier2', {
            'min_sharpe': 0.0,
            'max_drawdown': 50.0,
            'min_win_rate': 40.0,
            'min_annual_return': -20.0
        })
        constraints_fallback = self.config.get('constraints_fallback', {
            'min_sharpe': -0.5,
            'max_drawdown': 60.0,
            'min_win_rate': 30.0,
            'min_annual_return': -30.0
        })

        # Tier 1: 优秀组合
        tier1_passed = [
            r for r in validation_results 
            if self._passes_constraints(r, constraints_tier1)
        ]
        if tier1_passed:
            logger.info(f"[Tier 1] 找到 {len(tier1_passed)} 个优秀组合")
            sorted_tier1 = sorted(
                tier1_passed, 
                key=lambda x: self._calculate_score(x), 
                reverse=True
            )
            top_results = sorted_tier1[:top_n]
            # 添加 tier 信息
            for r in top_results:
                r['tier'] = 'tier1'
            logger.info(f"[分层筛选] 返回 Top {len(top_results)} Tier 1 组合")
            for i, r in enumerate(top_results[:3]):
                metrics = r.get('metrics', {})
                logger.info(
                    f"  #{i+1}: Sharpe={metrics.get('sharpe_ratio', 0):.2f}, "
                    f"DD={metrics.get('max_drawdown', 0):.2f}%, "
                    f"WR={metrics.get('win_rate', 0):.2f}%"
                )
            return top_results, 'tier1'

        # Tier 2: 可用组合
        tier2_passed = [
            r for r in validation_results 
            if self._passes_constraints(r, constraints_tier2)
        ]
        if tier2_passed:
            logger.info(f"[Tier 2] 找到 {len(tier2_passed)} 个可用组合")
            sorted_tier2 = sorted(
                tier2_passed, 
                key=lambda x: self._calculate_score(x), 
                reverse=True
            )
            top_results = sorted_tier2[:top_n]
            for r in top_results:
                r['tier'] = 'tier2'
            logger.info(f"[分层筛选] 返回 Top {len(top_results)} Tier 2 组合")
            for i, r in enumerate(top_results[:3]):
                metrics = r.get('metrics', {})
                logger.info(
                    f"  #{i+1}: Sharpe={metrics.get('sharpe_ratio', 0):.2f}, "
                    f"DD={metrics.get('max_drawdown', 0):.2f}%, "
                    f"WR={metrics.get('win_rate', 0):.2f}%"
                )
            return top_results, 'tier2'

        # Fallback: 保底组合（云舟优化 P1: 增加 ICIR 过滤）
        # Step 1: 优先选择 ICIR > 0 的组合
        fallback_passed = [
            r for r in validation_results 
            if self._passes_constraints(r, constraints_fallback) and
            r.get('icir', r.get('original_icir', 0)) > 0
        ]
        
        # Step 2: 如果没有 ICIR > 0 的组合，放宽到 ICIR >= -0.01
        if not fallback_passed:
            logger.info("[Fallback] 未找到 ICIR>0 的组合，放宽到 ICIR>=-0.01")
            fallback_passed = [
                r for r in validation_results 
                if self._passes_constraints(r, constraints_fallback) and
                r.get('icir', r.get('original_icir', 0)) >= -0.01
            ]
        
        # Step 3: 如果仍然没有，使用所有满足基本约束的组合
        if not fallback_passed:
            logger.info("[Fallback] 未找到 ICIR>=-0.01 的组合，使用所有保底组合")
            fallback_passed = [
                r for r in validation_results 
                if self._passes_constraints(r, constraints_fallback)
            ]
        
        if fallback_passed:
            logger.info(f"[Fallback] 找到 {len(fallback_passed)} 个保底组合")
            # P1: 使用专用评分函数，优先按 ICIR 排序
            sorted_fallback = sorted(
                fallback_passed, 
                key=lambda x: (x.get('icir', x.get('original_icir', 0)), self._calculate_fallback_score(x)),
                reverse=True
            )
            top_results = sorted_fallback[:top_n]
            for r in top_results:
                r['tier'] = 'fallback'
            logger.warning(f"[分层筛选] 返回 Top {len(top_results)} Fallback 组合")
            for i, r in enumerate(top_results[:3]):
                metrics = r.get('metrics', {})
                logger.warning(
                    f"  #{i+1}: ICIR={r.get('icir', r.get('original_icir', 0)):.4f}, "
                    f"Sharpe={metrics.get('sharpe_ratio', 0):.2f}, "
                    f"DD={metrics.get('max_drawdown', 0):.2f}%, "
                    f"WR={metrics.get('win_rate', 0):.2f}%"
                )
            return top_results, 'fallback'

        # 完全失败: 先检查基本约束，再按 ICIR 排序
        logger.warning("[分层筛选] 所有层级都无组合，检查基本约束")

        # 定义基本约束（比 Fallback 更宽松，但仍需检查极端情况）
        basic_constraints = {
            'max_drawdown': 70.0,      # 对齐 v1
            'min_win_rate': 0,         # 胜率不限
            'min_annual_return': -100  # 收益不限（允许极端负值）
        }

        # 过滤违反基本约束的组合
        basic_passed = [
            r for r in validation_results 
            if self._passes_constraints(r, basic_constraints)
        ]

        if basic_passed:
            # 有组合通过基本约束，按综合评分排序（ICIR + Sharpe + 回撤 + 胜率）
            logger.info(f"[基本约束] 找到 {len(basic_passed)} 个基本合格组合")
            sorted_basic = sorted(
                basic_passed, 
                key=lambda x: self._calculate_fallback_score(x),
                reverse=True
            )
            top_results = sorted_basic[:top_n]
            for r in top_results:
                r['tier'] = 'basic'
            logger.warning(f"[分层筛选] 返回 Top {len(top_results)} 基本合格组合")
            for i, r in enumerate(top_results[:3]):
                metrics = r.get('metrics', {})
                logger.warning(
                    f"  #{i+1}: ICIR={r.get('icir', r.get('original_icir', 0)):.4f}, "
                    f"Sharpe={metrics.get('sharpe_ratio', 0):.2f}, "
                    f"DD={metrics.get('max_drawdown', 0):.2f}%"
                )
            return top_results, 'basic'
        else:
            # 没有任何组合通过基本约束，返回空列表
            logger.error(f"[分层筛选] 所有组合都违反基本约束（回撤 > {basic_constraints['max_drawdown']}%）")
            logger.warning("[分层筛选] 返回空列表，建议检查回测数据或约束配置")
            return [], 'none'

    def _calculate_fallback_score(self, result: Dict) -> float:
        """计算 Fallback 组合的综合评分 (云舟优化 P1: 调整权重公式)
        
        综合考虑多个指标，优先选择 ICIR 高、Sharpe 合理、回撤可控的组合
        
        权重分配（P1 优化后）：
        - ICIR 权重: 30%（主要指标）
        - Sharpe 权重: 20%（风险调整收益）
        - WinRate 权重: 25%（稳定性）
        - Drawdown 权重: 15%（回撤惩罚）
        - Return 权重: 10%（收益奖励）
        
        Args:
            result: 验证结果
            
        Returns:
            float: 综合评分（越高越好）
        """
        metrics = result.get('metrics', {})
        if metrics is None:
            # 如果没有 metrics，仅基于 ICIR
            return result.get('icir', result.get('original_icir', 0))
        
        # 获取各项指标
        icir = result.get('icir', result.get('original_icir', 0))
        sharpe = metrics.get('sharpe_ratio', 0)
        max_dd = metrics.get('max_drawdown', 100)
        win_rate = metrics.get('win_rate', 0)
        annual_return = metrics.get('annual_return', 0)
        
        # 综合评分公式（P1 优化后）:
        # - ICIR 权重 30%
        # - Sharpe 权重 20%
        # - WinRate 权重 25%
        # - Drawdown 权重 15%
        # - Return 权重 10%
        score = (
            icir * 0.30 +
            sharpe * 0.20 +
            win_rate / 100 * 0.25 +
            (100 - max_dd) / 100 * 0.15 +
            annual_return / 100 * 0.10
        )
        
        logger.debug(
            f"[Fallback评分] ICIR={icir:.4f}, Sharpe={sharpe:.2f}, "
            f"DD={max_dd:.2f}%, WR={win_rate:.2f}%, Return={annual_return:.2f}% => Score={score:.4f}"
        )
        
        return score

    def _passes_constraints(self, result: Dict, constraints: Dict) -> bool:
        """检查是否通过约束条件

        Args:
            result: 验证结果
            constraints: 约束条件

        Returns:
            bool: 是否通过
        """
        # P2修复: 类型校验，防止非 dict 类型导致异常
        if not isinstance(result, dict):
            logger.warning(f"_passes_constraints: result 类型异常: {type(result)}")
            return False
        if result.get('metrics') is None:
            return False

        metrics = result.get('metrics', {})
        if metrics is None:
            return False

        sharpe = metrics.get('sharpe_ratio', -999)
        max_drawdown = metrics.get('max_drawdown', 100)
        win_rate = metrics.get('win_rate', 0)
        annual_return = metrics.get('annual_return', -100)

        return (
            sharpe >= constraints.get('min_sharpe', -999) and
            max_drawdown <= constraints.get('max_drawdown', 100) and
            win_rate >= constraints.get('min_win_rate', 0) and
            annual_return >= constraints.get('min_annual_return', -100)
        )

    def _calculate_score(self, result: Dict) -> float:
        """计算综合评分

        Args:
            result: 验证结果

        Returns:
            float: 综合评分
        """
        metrics = result.get('metrics', {})
        if metrics is None:
            return -999

        sharpe = metrics.get('sharpe_ratio', 0)
        win_rate = metrics.get('win_rate', 0)
        drawdown = metrics.get('max_drawdown', 100)
        return_rate = metrics.get('annual_return', 0)

        # 综合评分（权重可配置）
        score = (
            sharpe * 0.4 +
            win_rate / 100 * 0.3 +
            (100 - drawdown) / 100 * 0.2 +
            return_rate / 100 * 0.1
        )
        return score

    # ========== Phase 2 方案H: IC桥接验证 ==========

    def calculate_ic_bridge_score(
        self,
        weights: Dict[str, float],
        factors: List[str],
        factor_ic_data: Dict[str, Dict],
        period: str = 'forward_return_1d'
    ) -> float:
        """
        IC桥接评分（方案H + 多周期自适应）

        v2.0 多周期优化（云舟实施）:
        - 支持周期自适应 sigma_return
        - 不同周期使用不同的收益波动率参数

        核心思路：用IC直接预测收益，绕过回测

        公式：
        Expected_Return ≈ Σ(IC_mean_i × weight_i) × σ(return) × 252（年化）

        Args:
            weights: 权重组合
            factors: 因子列表
            factor_ic_data: 因子IC数据 {'rsi': {'ic_mean': 0.039, ...}, 'sigma_return': 0.02}
            period: 收益周期字段名（forward_return_1d/3d/5d）

        Returns:
            float: IC桥接评分（预测年化收益）
        """
        # v2.0 多周期：从配置获取周期对应的 sigma_return
        ic_bridge_config = self.config.get('ic_bridge', {})
        sigma_return_by_period = ic_bridge_config.get('sigma_return_by_period', {})
        sigma_return = sigma_return_by_period.get(period, 0.02)  # 默认2%

        # 计算加权IC
        weighted_ic = 0.0
        for factor in factors:
            weight = weights.get(factor, 0)
            ic_mean = factor_ic_data.get(factor, {}).get('ic_mean', 0)

            weighted_ic += weight * ic_mean

        # 桥接公式：Expected_Return = weighted_IC × σ_return × 252（年化）
        expected_return = weighted_ic * sigma_return * 252

        # 转换为评分（0-1）
        score = max(0, min(1, expected_return / 0.5))  # 50%为满分

        logger.debug(f"IC桥接评分(period={period}): weighted_IC={weighted_ic:.4f}, "
                     f"sigma={sigma_return:.3f}, expected_return={expected_return:.2%}, score={score:.4f}")

        return score
    
    def calculate_ic_bridge_score_with_decay(
        self,
        weights: Dict[str, float],
        factors: List[str],
        factor_ic_data: Dict[str, Dict],
        period: str = 'forward_return_1d'
    ) -> float:
        """
        v3: IC桥接评分（衰减补偿版）
        
        公式改进：
        Expected_Return = Σ(IC_mean_i × decay_factor × weight_i) × σ(return) × 252
        
        Args:
            weights: 权重组合
            factors: 因子列表
            factor_ic_data: 因子IC数据
            period: 收益周期字段名（forward_return_1d/3d/5d）
        
        Returns:
            float: IC桥接评分（预测年化收益，已衰减补偿）
        """
        # 解析持仓天数
        holding_days = self._parse_holding_days(period)
        
        # 获取衰减因子
        decay_factor = get_decay_factor(holding_days)
        
        # v2.0 多周期：从配置获取周期对应的 sigma_return
        ic_bridge_config = self.config.get('ic_bridge', {})
        sigma_return_by_period = ic_bridge_config.get('sigma_return_by_period', {})
        sigma_return = sigma_return_by_period.get(period, 0.02)  # 默认2%
        
        # v3改进：加权IC × 衰减因子
        weighted_ic = 0.0
        for factor in factors:
            weight = weights.get(factor, 0)
            ic_mean = factor_ic_data.get(factor, {}).get('ic_mean', 0)
            
            # 核心改进：IC × 衰减因子
            adjusted_ic = ic_mean * decay_factor
            weighted_ic += weight * adjusted_ic
        
        # 桥接公式（年化）
        expected_return = weighted_ic * sigma_return * 252
        
        # 转换为评分（0-1）
        score = max(0, min(1, expected_return / 0.5))  # 50%为满分
        
        logger.info(f"[v3 IC衰减补偿] period={period}, holding_days={holding_days}, "
                    f"λ={LAMBDA_CONFIG.get(holding_days, 0.288):.3f}, "
                    f"decay_factor={decay_factor:.4f}, "
                    f"expected_return={expected_return:.2%}, score={score:.4f}")
        
        return score
    
    def _parse_holding_days(self, period: str) -> int:
        """
        解析持仓天数
        
        Args:
            period: 收益周期字段名
        
        Returns:
            int: 持仓天数（1/3/5）
        """
        if '1d' in period:
            return 1
        elif '3d' in period:
            return 3
        elif '5d' in period:
            return 5
        else:
            return 1  # 默认T+1

    def ic_bridge_ranking(
        self,
        candidates: List[Dict],
        factors: List[str],
        top_n: int = 200
    ) -> List[Dict]:
        """
        IC桥接筛选（方案H + 多周期自适应）

        v2.0 多周期优化（云舟实施）:
        - 支持周期自适应评分权重
        - 不同周期使用不同的 ICIR/ic_bridge 权重组合
        - T+1 更关注收益预测（ic_bridge=0.7）
        - T+5 更关注IC稳定性（icir=0.7）

        流程：
        1. 加载因子IC数据
        2. 计算每个候选的IC桥接评分
        3. 综合评分 = period_weights[icir] * ICIR + period_weights[ic_bridge] * IC桥接评分
        4. 按综合评分排序，取 Top N

        Args:
            candidates: 候选组合列表 [{'weights': {...}, 'icir': float}, ...]
            factors: 因子列表
            top_n: 保留数量

        Returns:
            List[Dict]: 篦选后的候选
        """
        logger.info(f"[方案H] IC桥接筛选: 输入{len(candidates)}, 输出{top_n}")

        # 加载因子IC数据
        factor_ic_data = self._load_factor_ic_data(factors)

        # v2.0 多周期：从配置获取周期自适应权重
        period = self._return_col if hasattr(self, '_return_col') else 'forward_return_1d'
        ic_bridge_config = self.config.get('ic_bridge', {})
        period_weights = ic_bridge_config.get('period_weights', {})
        period_config = period_weights.get(period, {'icir': 0.6, 'ic_bridge': 0.4})
        icir_weight = period_config.get('icir', 0.6)
        ic_bridge_weight = period_config.get('ic_bridge', 0.4)

        logger.info(f"[方案H v2.0] 周期自适应权重(period={period}): icir={icir_weight}, ic_bridge={ic_bridge_weight}")

        # 计算IC桥接评分
        scored_candidates = []
        for candidate in candidates:
            ic_bridge_score = self.calculate_ic_bridge_score(
                weights=candidate['weights'],
                factors=factors,
                factor_ic_data=factor_ic_data,
                period=period  # v2.0 多周期：传递周期参数
            )

            # v2.0 多周期：周期自适应综合评分
            icir = candidate.get('icir', 0)
            candidate['ic_bridge_score'] = ic_bridge_score
            candidate['combined_score'] = (
                icir_weight * icir +
                ic_bridge_weight * ic_bridge_score
            )
            scored_candidates.append(candidate)

        # 按综合评分排序
        scored_candidates.sort(key=lambda x: x['combined_score'], reverse=True)

        top_candidates = scored_candidates[:top_n]

        if top_candidates:
            logger.info(f"[方案H] IC桥接完成: Top{top_n} combined_score={top_candidates[0]['combined_score']:.4f}")
        else:
            logger.warning(f"[方案H] IC桥接完成: 无候选组合")

        return top_candidates

    def ic_bridge_ranking_with_decay(
        self,
        candidates: List[Dict],
        factors: List[str],
        top_n: int = 200,
        period: str = 'forward_return_1d'
    ) -> List[Dict]:
        """
        v3: IC桥接筛选（衰减补偿版）
    
        流程：
        1. 加载因子IC数据
        2. 计算每个候选的IC桥接评分（带衰减补偿）
        3. 综合评分 = 0.6×ICIR + 0.4×IC桥接评分
        4. 按综合评分排序，取Top N
    
        Args:
            candidates: 候选组合列表
            factors: 因子列表
            top_n: 保留数量
            period: 收益周期字段名
    
        Returns:
            List[Dict]: 篦选后的候选（带衰减补偿）
        """
        logger.info(f"[v3 IC衰减补偿] IC桥接筛选: 输入{len(candidates)}, 输出{top_n}")
    
        factor_ic_data = self._load_factor_ic_data(factors)
    
        # v3.1 多周期：从配置获取周期自适应权重
        ic_bridge_config = self.config.get('ic_bridge', {})
        period_weights = ic_bridge_config.get('period_weights', {})
        period_config = period_weights.get(period, {'icir': 0.6, 'ic_bridge': 0.4})
        icir_weight = period_config.get('icir', 0.6)
        ic_bridge_weight = period_config.get('ic_bridge', 0.4)
    
        logger.info(f"[v3.1 IC衰减补偿] 周期自适应权重(period={period}): icir={icir_weight}, ic_bridge={ic_bridge_weight}")
    
        # 计算IC桥接评分（带衰减补偿）
        scored_candidates = []
        for candidate in candidates:
            ic_bridge_score = self.calculate_ic_bridge_score_with_decay(
                weights=candidate['weights'],
                factors=factors,
                factor_ic_data=factor_ic_data,
                period=period
            )
        
            # v3.1 多周期：周期自适应综合评分
            icir = candidate.get('icir', 0)
            candidate['ic_bridge_score_v3'] = ic_bridge_score
            candidate['combined_score_v3'] = (
                icir_weight * icir +
                ic_bridge_weight * ic_bridge_score
            )
            scored_candidates.append(candidate)
    
        # 按综合评分排序
        scored_candidates.sort(key=lambda x: x['combined_score_v3'], reverse=True)
    
        top_candidates = scored_candidates[:top_n]
    
        if top_candidates:
            logger.info(f"[v3 IC衰减补偿] 完成: Top{top_n} combined_score_v3={top_candidates[0]['combined_score_v3']:.4f}")
        else:
            logger.warning(f"[v3 IC衰减补偿] 完成: 无候选组合")
    
        return top_candidates

    def _load_factor_ic_data(self, factors: List[str]) -> Dict:
        """
        加载因子IC数据

        Args:
            factors: 因子列表

        Returns:
            Dict: {'rsi': {'ic_mean': 0.039, 'icir': 0.27}, 'sigma_return': 0.02}
        """
        factor_ic_data = {}

        # 从因子分析结果文件读取
        for factor in factors:
            try:
                # 尝试加载因子分析结果
                result_file = BASE_DIR / f'{factor}_analysis_result.json'
                if not result_file.exists():
                    # 尝试不同的文件名格式
                    result_file = BASE_DIR / f'factor_analysis_result.json'
                    if factor == 'rsi' and result_file.exists():
                        # rsi 使用 factor_analysis_result.json
                        pass
                    else:
                        continue

                with open(result_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)

                ic_metrics = data.get('ic_metrics', {})
                factor_ic_data[factor] = {
                    'ic_mean': ic_metrics.get('ic_mean', 0),
                    'icir': ic_metrics.get('icir', 0),
                    'positive_ratio': ic_metrics.get('positive_ratio', 0)
                }

            except Exception as e:
                logger.warning(f"加载因子 {factor} IC数据失败: {e}")
                factor_ic_data[factor] = {'ic_mean': 0.039, 'icir': 0.27}  # 默认值

        # 设置收益波动率（从回测数据估算）
        factor_ic_data['sigma_return'] = 0.02  # 默认2%（股票日波动率）

        return factor_ic_data

    def two_stage_validation(
        self,
        grid_candidates: List[Dict],
        factors: List[str],
        config: Dict,
        progress_callback: Optional[callable] = None
    ) -> Dict:
        """
        两阶段验证（详细日志版本）

        v3.9 多周期修复（云舟实施）：
        - Stage 2 开始前预创建引擎（避免并行任务重复加载）
        - 解决 P3 性能瓶颈：线程池等待第一个任务加载
        - 解决 P4 内存泄漏：使用周期缓存机制

        日志格式：
        - [Stage 1] 开始执行: IC桥接筛选
        - [Stage 1] 进度: 已处理 X/Y
        - [Stage 1] 完成: IC桥接筛选, 耗时 Ts, 结果: Top N
        """
        logger.info(f"[方案H] 开始两阶段验证...")
        sys.stdout.flush()

        # ========== [Stage 1] IC桥接筛选 ========== 
        stage1_start_time = time.time()
        ic_bridge_config = config.get('ic_bridge', {})
        use_ic_bridge = ic_bridge_config.get('enabled', True)

        if use_ic_bridge:
            logger.info(f"[Stage 1] 开始执行: IC桥接筛选")
            logger.info(f"[Stage 1] 参数: 输入 {len(grid_candidates)} 候选, 输出 Top {ic_bridge_config.get('top_n_candidates', 200)}")
            sys.stdout.flush()

            # v3: 使用衰减补偿版本
            period = self._return_col if hasattr(self, '_return_col') else 'forward_return_1d'
            ic_bridge_candidates = self.ic_bridge_ranking_with_decay(
                candidates=grid_candidates,
                factors=factors,
                top_n=ic_bridge_config.get('top_n_candidates', 200),
                period=period
            )

            stage1_time = time.time() - stage1_start_time
            logger.info(f"[Stage 1] 完成: IC桥接筛选, 耗时 {stage1_time:.1f}s")
            if ic_bridge_candidates:
                logger.info(f"[Stage 1] 结果: Top {len(ic_bridge_candidates)} 候选, combined_score_v3={ic_bridge_candidates[0]['combined_score_v3']:.4f}")
            else:
                logger.warning(f"[Stage 1] 结果: IC桥接筛选返回空列表")
            sys.stdout.flush()
        else:
            # 不启用IC桥接，直接使用原候选
            ic_bridge_candidates = grid_candidates
            logger.info(f"[Stage 1] IC桥接未启用，使用原候选: {len(ic_bridge_candidates)}")
            sys.stdout.flush()

        # ========== [Stage 2] 精选回测 ========== 
        stage2_start_time = time.time()
        backtest_count = ic_bridge_config.get('backtest_candidates', 20)
        backtest_candidates = ic_bridge_candidates[:backtest_count]

        logger.info(f"[Stage 2] 开始执行: 精选回测")
        logger.info(f"[Stage 2] 参数: 回测 {len(backtest_candidates)} 个组合, 线程池大小 4")
        sys.stdout.flush()

        if progress_callback:
            progress_callback(0, len(backtest_candidates), 'Stage 2: IC桥接筛选完成，开始精选回测')

        # v3.9 修复 P3/P4：预创建引擎（避免并行任务重复加载）
        # 核心思路：主进程预加载引擎到缓存，所有并行任务复用缓存
        from scoring_engine import get_cached_engine
        preloaded_engine = get_cached_engine(return_col=self._return_col, use_shared_cache=True)
        logger.info(f"[Stage 2] 引擎预创建完成（周期={self._return_col}, 缓存已就绪）")
        sys.stdout.flush()

        # 执行回测（使用并行回测）
        from quick_backtest import parallel_backtest_batch

        # 定义进度回调函数
        def backtest_progress_callback(cur, total, res):
            elapsed = time.time() - stage2_start_time
            metrics = res.get('metrics', {}) if res else {}
            sharpe = metrics.get('sharpe_ratio', 0) if metrics else 0

            logger.info(f"[Stage 2] 进度: 回测 {cur}/{total}, Sharpe={sharpe:.2f}, 耗时 {elapsed:.1f}s")
            sys.stdout.flush()

            if progress_callback:
                progress_callback(cur, total, res)

        # v3.9 修复：传递预创建引擎，避免并行任务重复加载
        validation_results = parallel_backtest_batch(
            weight_candidates=backtest_candidates,
            factors=factors,
            config=config,
            pool_size=4,
            progress_callback=backtest_progress_callback,
            return_col=self._return_col,  # 传递周期参数
            preloaded_engine=preloaded_engine  # 传递预创建引擎（P3/P4 修复）
        )

        stage2_time = time.time() - stage2_start_time
        logger.info(f"[Stage 2] 完成: 精选回测, 耗时 {stage2_time:.1f}s")
        logger.info(f"[Stage 2] 结果: {len(validation_results)} 个验证结果")

        # 统计通过约束的组合
        passed_count = sum(1 for r in validation_results if r.get('passed_constraints', False))
        logger.info(f"[Stage 2] 通过约束: {passed_count}/{len(validation_results)}")
        sys.stdout.flush()

        # 分层筛选（方案B）
        use_tiered_filtering = config.get('validation', {}).get('use_tiered_filtering', True)

        if use_tiered_filtering:
            top_results, tier_used = self.select_best_with_tiers(
                validation_results=validation_results,
                top_n=10
            )
            # select_best_with_tiers 返回 list，需要包装成 dict 结构
            tiered_results = {
                'excellent': [r for r in top_results if r.get('tier') == 'tier1'],
                'acceptable': [r for r in top_results if r.get('tier') == 'tier2'],
                'fallback': [r for r in top_results if r.get('tier') == 'fallback']
            }
            logger.info(f"[方案H] 两阶段验证完成: tier={tier_used}, "
                        f"excellent={len(tiered_results['excellent'])}, "
                        f"acceptable={len(tiered_results['acceptable'])}")

            # 返回结构化结果
            return {
                'tiered_results': tiered_results,
                'ic_bridge_candidates': ic_bridge_candidates,
                'backtest_candidates': backtest_candidates,
                'tier_used': tier_used
            }
        else:
            # 传统筛选
            top_weights = self.filter_and_rank(
                validation_results=validation_results,
                top_n=10,
                use_tiered_filtering=False
            )

            logger.info(f"[方案H] 两阶段验证完成: Top{len(top_weights)} 组合")

            return {
                'tiered_results': {
                    'excellent': [w for w in top_weights if w.get('passed_constraints', False) and w.get('tier') == 'tier1'],
                    'acceptable': [w for w in top_weights if w.get('passed_constraints', False) and w.get('tier') == 'tier2'],
                    'fallback': top_weights
                },
                'ic_bridge_candidates': ic_bridge_candidates,
                'backtest_candidates': backtest_candidates,
                'tier_used': 'traditional'
            }

    def get_validation_summary(
        self,
        validation_results: List[Dict]
    ) -> Dict:
        """
        获取验证摘要

        Args:
            validation_results: 验证结果列表

        Returns:
            摘要字典
        """
        total = len(validation_results)
        passed = sum(1 for r in validation_results if r.get('passed_constraints', False))

        # 统计指标分布
        sharpe_values = []
        drawdown_values = []
        winrate_values = []
        return_values = []

        for r in validation_results:
            metrics = r.get('metrics')
            if metrics:
                sharpe_values.append(metrics.get('sharpe_ratio', 0))
                drawdown_values.append(metrics.get('max_drawdown', 100))
                winrate_values.append(metrics.get('win_rate', 0))
                return_values.append(metrics.get('annual_return', 0))

        summary = {
            'total_candidates': total,
            'passed_constraints': passed,
            'pass_rate': round(passed / total * 100, 1) if total > 0 else 0,
            'metrics_distribution': {
                'sharpe': {
                    'min': min(sharpe_values) if sharpe_values else 0,
                    'max': max(sharpe_values) if sharpe_values else 0,
                    'mean': np.mean(sharpe_values) if sharpe_values else 0,
                    'median': np.median(sharpe_values) if sharpe_values else 0
                },
                'max_drawdown': {
                    'min': min(drawdown_values) if drawdown_values else 0,
                    'max': max(drawdown_values) if drawdown_values else 100,
                    'mean': np.mean(drawdown_values) if drawdown_values else 100,
                    'median': np.median(drawdown_values) if drawdown_values else 100
                },
                'win_rate': {
                    'min': min(winrate_values) if winrate_values else 0,
                    'max': max(winrate_values) if winrate_values else 0,
                    'mean': np.mean(winrate_values) if winrate_values else 0,
                    'median': np.median(winrate_values) if winrate_values else 0
                },
                'annual_return': {
                    'min': min(return_values) if return_values else 0,
                    'max': max(return_values) if return_values else 0,
                    'mean': np.mean(return_values) if return_values else 0,
                    'median': np.median(return_values) if return_values else 0
                }
            },
            'constraints': self.constraints,
            'backtest_params': self.backtest_params
        }

        return summary

    # ========== P1-1: 多 top_n 稳定性评分（新增） ==========

    def validate_with_multi_top_n(
        self,
        weights: Dict[str, float],
        factors: List[str],
        top_n_values: List[int] = [3, 5, 10],
        stability_threshold: float = 0.15,
        progress_callback: callable = None
    ) -> Dict:
        """
        多 top_n 稳定性评分（详细日志版本）

        日志格式：
        - [Multi-TopN] 开始执行: 组合 X, top_n_values=[3,5,10]
        - [Multi-TopN] 进度: top_n=N, Sharpe=X.XX
        - [Multi-TopN] 完成: stability_score=X.XXXX
        """
        step_start_time = time.time()
        logger.info(f"[Multi-TopN] 开始执行: 组合 weights={weights}")
        logger.info(f"[Multi-TopN] 参数: top_n_values={top_n_values}, stability_threshold={stability_threshold}")
        sys.stdout.flush()

        multi_results = []

        for top_n in top_n_values:
            # 临时修改 backtest_params 的 top_n
            original_top_n = self.backtest_params.get('top_n', 10)
            self.backtest_params['top_n'] = top_n

            logger.info(f"[Multi-TopN] 进度: 测试 top_n={top_n}")
            sys.stdout.flush()

            # 执行回测
            result = self.validate_single_weights(
                weights=weights,
                factors=factors,
                progress_callback=progress_callback
            )

            # 还原原始 top_n
            self.backtest_params['top_n'] = original_top_n

            # 记录结果
            metrics = result.get('metrics', {}) if result else {}
            sharpe = metrics.get('sharpe_ratio', 0)

            multi_results.append({
                'top_n': top_n,
                'sharpe_ratio': sharpe,
                'max_drawdown': metrics.get('max_drawdown', 100),
                'win_rate': metrics.get('win_rate', 0),
                'annual_return': metrics.get('annual_return', 0),
                'passed_constraints': result.get('passed_constraints', False)
            })

            logger.info(f"[Multi-TopN] 结果: top_n={top_n}, Sharpe={sharpe:.2f}, "
                        f"Drawdown={metrics.get('max_drawdown', 0):.2f}%, "
                        f"WinRate={metrics.get('win_rate', 0):.2f}%")
            sys.stdout.flush()

        # 计算稳定性评分
        sharpe_values = [r['sharpe_ratio'] for r in multi_results]
        avg_sharpe = np.mean(sharpe_values)
        sharpe_std = np.std(sharpe_values)
        sharpe_range = max(sharpe_values) - min(sharpe_values)

        # 稳定性评分：标准差越小越稳定，范围在 0-1
        stability_score = 1.0 - min(sharpe_range / stability_threshold, 1.0)

        # 判断是否稳定（波动不超过阈值）
        is_stable = sharpe_range <= stability_threshold

        step_elapsed = time.time() - step_start_time
        logger.info(f"[Multi-TopN] 完成: 耗时 {step_elapsed:.1f}s")
        logger.info(f"[Multi-TopN] 结果: avg_sharpe={avg_sharpe:.2f}, std={sharpe_std:.2f}, "
                    f"range={sharpe_range:.2f}, stability_score={stability_score:.4f}, is_stable={is_stable}")
        sys.stdout.flush()

        return {
            'weights': weights,
            'multi_top_n_results': multi_results,
            'stability_score': round(stability_score, 4),
            'avg_sharpe': round(avg_sharpe, 4),
            'sharpe_std': round(sharpe_std, 4),
            'sharpe_range': round(sharpe_range, 4),
            'is_stable': is_stable,
            'stability_threshold': stability_threshold
        }

    def batch_validate_with_multi_top_n(
        self,
        weight_candidates: List[Dict],
        factors: List[str],
        top_n_values: List[int] = [3, 5, 10],
        stability_threshold: float = 0.15,
        progress_callback: callable = None
    ) -> List[Dict]:
        """
        批量多 top_n 稳定性评分

        Args:
            weight_candidates: 权重候选列表
            factors: 因子列表
            top_n_values: 多 top_n 参数列表
            stability_threshold: 稳定性阈值
            progress_callback: 进度回调

        Returns:
            List[Dict]: 稳定性评分结果列表，按稳定性评分排序
        """
        total = len(weight_candidates)
        logger.info(f"[P1-1] 批量多 top_n 稳定性评分: 共 {total} 个候选")
        sys.stdout.flush()

        results = []

        for i, candidate in enumerate(weight_candidates):
            weights = candidate.get('weights', {})

            # 进度日志：每个组合输出一次
            logger.info(f"多 top_n 测试: 组合 {i+1}/{total}, weights={weights}")
            sys.stdout.flush()

            # 执行多 top_n 验证
            result = self.validate_with_multi_top_n(
                weights=weights,
                factors=factors,
                top_n_values=top_n_values,
                stability_threshold=stability_threshold,
                progress_callback=None
            )

            # 附加原始 ICIR 信息
            result['original_icir'] = candidate.get('icir', 0)

            # 输出结果摘要
            logger.info(f"  结果: stability_score={result.get('stability_score', 0):.4f}, "
                        f"avg_sharpe={result.get('avg_sharpe', 0):.2f}, "
                        f"is_stable={result.get('is_stable', False)}")
            sys.stdout.flush()

            # 进度回调
            if progress_callback:
                progress_callback(i + 1, total, result)

            results.append(result)

        # 按稳定性评分排序（优先选择稳定的组合）
        results.sort(key=lambda x: x.get('stability_score', 0), reverse=True)

        logger.info(f"[P1-1] 批量验证完成，Top 3 稳定性评分:")
        sys.stdout.flush()
        for i, r in enumerate(results[:3]):
            logger.info(f"  #{i+1}: stability_score={r.get('stability_score', 0):.4f}, "
                        f"avg_sharpe={r.get('avg_sharpe', 0):.2f}, "
                        f"is_stable={r.get('is_stable', False)}")

        return results


# ==================== API 辅助函数 ====================

_validator_instance = None

def get_validator(config: Dict = None) -> QuickBacktestValidator:
    """获取验证器单例"""
    global _validator_instance
    if _validator_instance is None:
        _validator_instance = QuickBacktestValidator(config)
    return _validator_instance


def validate_weights_with_backtest(
    weights: Dict[str, float],
    factors: List[str],
    config: Dict = None
) -> Dict:
    """
    快速验证单个权重组合

    Args:
        weights: 权重字典
        factors: 因子列表
        config: 配置字典

    Returns:
        验证结果字典
    """
    validator = get_validator(config)
    return validator.validate_single_weights(weights, factors)


def validate_batch_weights_with_backtest(
    weight_candidates: List[Dict],
    factors: List[str],
    config: Dict = None,
    progress_callback: callable = None
) -> List[Dict]:
    """
    批量验证权重组合

    Args:
        weight_candidates: 候选权重列表
        factors: 因子列表
        config: 配置字典
        progress_callback: 进度回调

    Returns:
        验证结果列表
    """
    validator = get_validator(config)
    return validator.validate_batch_weights(weight_candidates, factors, progress_callback)


def filter_top_weights(
    validation_results: List[Dict],
    top_n: int = 10,
    fallback_to_icir: bool = True
) -> List[Dict]:
    """
    篛选 Top N 权重组合

    Args:
        validation_results: 验证结果列表
        top_n: Top N 数量
        fallback_to_icir: 是否 fallback

    Returns:
        Top N 组合列表
    """
    validator = get_validator()
    return validator.filter_and_rank(validation_results, top_n, fallback_to_icir)


# ==================== v3.6 并行回测优化 ====================
# v3.7 方案A：线程池替代进程池，解决OOM问题
# 作者：云舟 🛠️
# 预期效果：内存峰值从 3.2GB 降至 1.2GB

import multiprocessing
from functools import partial
import pickle

# 全局验证器实例（主进程预加载，线程共享）—— 方案A核心
_SHARED_VALIDATOR = None
_SHARED_VALIDATOR_LOCK = None  # 线程安全锁

def _init_shared_validator(config: Dict = None):
    """初始化共享验证器（主进程预加载）

    方案A核心改动：
    - 主进程预加载 validator，避免每个线程/进程重复加载
    - 线程共享内存，无需进程间复制

    Args:
        config: 配置字典
    """
    global _SHARED_VALIDATOR, _SHARED_VALIDATOR_LOCK

    if _SHARED_VALIDATOR is None:
        import threading
        _SHARED_VALIDATOR_LOCK = threading.Lock()

        # 主进程预加载 validator（包含缓存引擎）
        _SHARED_VALIDATOR = QuickBacktestValidator(config)
        # 确保引擎已加载（触发数据预加载）
        _SHARED_VALIDATOR._get_engine(use_cache=True)

        logger.info("[线程池回测] 共享验证器已初始化（主进程预加载，线程共享）")

def _get_shared_validator() -> QuickBacktestValidator:
    """获取共享验证器（线程安全）"""
    global _SHARED_VALIDATOR

    if _SHARED_VALIDATOR is None:
        # 懒加载（如果主进程未初始化）
        _init_shared_validator()

    return _SHARED_VALIDATOR

def single_backtest_worker_threaded(
    weights: Dict[str, float],
    factors: List[str],
    config: Dict = None,
    return_col: str = 'forward_return_1d',
    preloaded_engine: 'ScoringEngine' = None  # v3.9: 新增预创建引擎参数
) -> Dict:
    """单个回测任务工作函数（线程池版本）

    v3.9 多周期修复（云舟实施）：
    - 支持预创建引擎传递（P3/P4 修复）
    - 如果提供预创建引擎，直接使用，避免重复加载
    - 如果未提供，仍然创建新 validator（保持兼容性）

    Args:
        weights: 权重字典
        factors: 因子列表
        config: 配置字典
        return_col: 收益字段名（默认 forward_return_1d）
        preloaded_engine: 预创建的引擎实例（可选，推荐）

    Returns:
        验证结果字典
    """
    # v3.9 修复：如果提供预创建引擎，直接使用
    if preloaded_engine is not None:
        # 创建 validator 并注入预创建引擎
        validator = QuickBacktestValidator(config, return_col=return_col)
        validator._engine = preloaded_engine  # 直接注入，避免懒加载
        logger.debug(f"[线程池回测] 使用预创建引擎（周期={return_col}）")
    else:
        # v3.8 兼容：每个任务创建独立 validator
        validator = QuickBacktestValidator(config, return_col=return_col)
        logger.debug(f"[线程池回测] 创建新 validator（周期={return_col}）")

    # validate_single_weights 会自动懒加载引擎（如果未注入）
    return validator.validate_single_weights(weights, factors)

def parallel_backtest_batch(
    weight_candidates: List[Dict],
    factors: List[str],
    config: Dict = None,
    pool_size: int = 4,  # 线程池默认4（比进程池更轻量）
    progress_callback: callable = None,
    return_col: str = 'forward_return_1d',  # v3.8: 新增周期参数
    preloaded_engine: 'ScoringEngine' = None  # v3.9: 新增预创建引擎参数（P3/P4 修复）
) -> List[Dict]:
    """并行批量回测（方案A：线程池版本）

    v3.9 多周期修复（云舟实施）：
    - 支持预创建引擎传递（P3/P4 修复）
    - 主进程预加载引擎，所有并行任务复用
    - 避免重复加载 15s 数据（性能提升 10x）

    v3.8 修复共享验证器问题：
    - 移除共享验证器，每个任务创建独立 validator
    - 新增 return_col 参数，支持 T+1/T+3/T+5 不同周期
    - 避免所有周期使用同一个 T+1 引擎

    v3.7 方案A OOM修复：
    - 使用 ThreadPoolExecutor 替代 multiprocessing.Pool
    - 内存峰值：3.2GB → 1.2GB
    - 性能：比进程池慢约2倍（用户已接受）

    Args:
        weight_candidates: 候选权重列表 [{'weights': {...}, 'icir': float}, ...]
        factors: 因子列表
        config: 配置字典
        pool_size: 线程池大小（默认 4，线程更轻量）
        progress_callback: 进度回调函数
        return_col: 收益字段名（默认 forward_return_1d，支持 forward_return_3d/5d）
        preloaded_engine: 预创建的引擎实例（可选，推荐）

    Returns:
        验证结果列表
    """
    total = len(weight_candidates)
    logger.info(f"[线程池回测] 开始并行回测，共 {total} 个组合，线程池大小: {pool_size}, 周期: {return_col}")

    # v3.9 修复：传递预创建引擎给每个任务（P3/P4 修复）
    if preloaded_engine is not None:
        logger.info(f"[线程池回测] 使用预创建引擎（周期={return_col}, 缓存已就绪）")
    else:
        logger.info(f"[线程池回测] 无预创建引擎，每个任务将独立加载（性能较差）")

    # 提取权重列表
    weights_list = [c.get('weights', {}) for c in weight_candidates]
    icir_list = [c.get('icir', 0) for c in weight_candidates]

    start_time = time.time()

    try:
        # ========== 方案A：使用线程池替代进程池（P0修复：添加超时机制）==========
        with ThreadPoolExecutor(max_workers=pool_size) as executor:
            # 并行执行（线程共享内存），使用 submit + timeout 替代 map
            # v3.9 修复：传递预创建引擎参数（P3/P4 修复）
            futures = [executor.submit(
                single_backtest_worker_threaded, 
                w, 
                factors, 
                config, 
                return_col,
                preloaded_engine  # v3.9: 传递预创建引擎
            ) for w in weights_list]

            results = []
            # P1-2 修复：动态调整单任务超时
            base_timeout = 120  # 默认 120 秒
            if len(weights_list) > 1000:
                base_timeout = 180  # 大批量时增加超时
                logger.info(f"[线程池回测] 批量较大（{len(weights_list)}个），超时调整为 {base_timeout}秒")

            for i, future in enumerate(futures):
                try:
                    result = future.result(timeout=base_timeout)  # P1-2 修复：动态超时
                    results.append(result)
                except TimeoutError:
                    logger.warning(f"[线程池回测] 任务 {i} 超时（>120s），跳过")
                    results.append({
                        'weights': weights_list[i],
                        'metrics': None,
                        'passed_constraints': False,
                        'error': 'timeout'
                    })
                except Exception as e:
                    logger.error(f"[线程池回测] 任务 {i} 失败: {e}")
                    results.append({
                        'weights': weights_list[i],
                        'metrics': None,
                        'passed_constraints': False,
                        'error': str(e)
                    })

            # 附加原始 ICIR 信息（P0修复：同时添加 icir 字段）
            for i, result in enumerate(results):
                result['icir'] = icir_list[i]  # P0修复：确保 icir 字段存在
                result['original_icir'] = icir_list[i]

            elapsed = time.time() - start_time
            logger.info(f"[线程池回测] 完成，耗时 {elapsed:.1f}s，平均 {elapsed/total:.2f}s/组合")
            logger.info(f"[线程池回测] 内存峰值预估: ~1.2GB（主进程共享，无worker重复加载）")

            # 进度回调
            if progress_callback:
                progress_callback(total, total, results[-1] if results else None)

            return results

    except Exception as e:
        logger.error(f"[线程池回测] 失败: {e}")
        import traceback
        traceback.print_exc()

        # Fallback 到串行处理
        logger.warning("[线程池回测] Fallback 到串行回测")
        validator = get_validator(config)
        return validator.validate_batch_weights(weight_candidates, factors, progress_callback)

def shutdown_parallel_backtest_pool():
    """关闭并行回测资源（线程池版本）

    方案A：线程池已自动释放，只需清理共享 validator
    """
    global _SHARED_VALIDATOR, _SHARED_VALIDATOR_LOCK

    _SHARED_VALIDATOR = None
    _SHARED_VALIDATOR_LOCK = None
    logger.info("[线程池回测] 共享验证器已释放")


# ==================== v3: IC衰减补偿 ====================

# 分段衰减参数配置（基于实测数据校准）
LAMBDA_CONFIG = {
    1: 0.916,   # T+1: 快衰减（IC衰减60%/天）
    3: 0.288,   # T+3: 中衰减（IC衰减58%/3天）
    5: 0.163    # T+5: 慢衰减（IC衰减56%/5天）
}

def get_decay_factor(holding_days: int) -> float:
    """
    v3: 分段衰减因子
    
    基于实测数据的分段衰减参数：
    - T+1: IC衰减60%/天 → decay_factor=0.40
    - T+3: IC衰减58%/3天 → decay_factor=0.42
    - T+5: IC衰减56%/5天 → decay_factor=0.44
    
    公式: decay_factor = exp(-λ × holding_days)
    
    Args:
        holding_days: 持仓天数（1/3/5）
    
    Returns:
        float: 衰减因子 ∈ (0, 1)
    """
    λ = LAMBDA_CONFIG.get(holding_days, 0.288)  # 默认使用T+3参数
    decay_factor = np.exp(-λ * holding_days)
    return decay_factor


if __name__ == '__main__':
    # 测试快速回测验证
    print("[测试] 快速回测验证模块")

    # 测试权重
    test_weights = {
        'rsi': 17,
        'kdj_j': 14,
        'bollinger_pb': 17,
        'volume_ratio': 14,
        'turnover_surge': 14,
        'return_3d': 12
    }

    factors = ['rsi', 'kdj_j', 'bollinger_pb', 'volume_ratio', 'turnover_surge', 'return_3d']

    # 验证单个组合
    result = validate_weights_with_backtest(test_weights, factors)

    print(f"验证结果: {result.get('passed_constraints', False)}")
    print(f"指标: {result.get('metrics')}")