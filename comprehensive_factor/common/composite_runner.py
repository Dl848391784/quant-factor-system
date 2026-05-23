"""
综合因子公共入口模块

功能:
1. 加载因子数据和IC结果
2. 标准化因子值
3. 计算综合因子（调用 weight_engine）
4. 调用 backtest 分层回测（复用 run_layered_backtest）
5. 保存结果

设计参考:
- factor_ic/common/factor_ic_runner.py
- backtest/common/layered_backtest_runner.py

作者: 云瑶
创建日期: 2026-05-24
"""

import os
import sys
import json
import gzip
import logging
import pandas as pd
import numpy as np
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional, List, Callable
from dataclasses import dataclass, field

# 导入公共模块
from comprehensive_factor.common.logger_config import get_logger
from comprehensive_factor.common.convert_types import convert_to_native_types
from comprehensive_factor.common.factor_loader import (
    load_factor_values,
    load_ic_results,
    load_ic_daily,
    standardize_factors,
    calc_factor_correlation
)
from comprehensive_factor.common.weight_engine import WeightEngine

# 导入 backtest 公共模块（跨模块调用，但通过函数接口）
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from backtest.common.layered_backtest import LayeredBacktestEngine
from backtest.common.layered_backtest_runner import LayerConfigBase, load_factor_return_data
from backtest.common.convert_types import convert_to_native_types as backtest_convert


# ============================================================================
# Config 基类
# ============================================================================

@dataclass
class CompositeLayerConfig(LayerConfigBase):
    """综合因子分层配置
    
    综合因子默认为反向因子（低值预期高收益），
    因为低相关性组合中流动性因子（缩量）+ 技术指标（超卖）都指向反向逻辑。
    
    扩展参数：
    - factor_list: 因子名称列表
    - factor_cols: 因子列名列表
    - rolling_window: 滚动ICIR窗口
    """
    
    # 因子组合参数
    factor_list: List[str] = field(default_factory=lambda: ['rsi', 'volume_ratio'])
    factor_cols: List[str] = field(default_factory=lambda: ['rsi_6', 'volume_ratio_5'])
    rolling_window: int = 60
    
    def validate(self) -> None:
        """校验配置完整性"""
        super().validate()  # 调用父类校验
        
        if not self.factor_list:
            raise ValueError("factor_list 不能为空")
        
        if not self.factor_cols:
            raise ValueError("factor_cols 不能为空")
        
        if len(self.factor_list) != len(self.factor_cols):
            raise ValueError(
                f"factor_list ({len(self.factor_list)}) 与 factor_cols ({len(self.factor_cols)}) 数量不一致"
            )


# ============================================================================
# 公共入口函数
# ============================================================================

def run_composite_backtest(
    weight_method: str,
    factor_list: List[str],
    factor_cols: List[str],
    config: CompositeLayerConfig,
    return_period: str = '1d',
    cache_dir: Optional[str] = None,
    ic_result_dir: Optional[str] = None,
    output_dir: Optional[str] = None,
    verbose: bool = True,
    logger: Optional[logging.Logger] = None
) -> Dict:
    """综合因子分层回测公共入口
    
    Args:
        weight_method: 加权方式（equal_weight/icir_weight/ic_weight/rolling_icir_weight）
        factor_list: 因子名称列表（用于加载IC结果）
        factor_cols: 因子列名列表（用于加载因子值）
        config: 分层配置对象
        return_period: 收益周期
        cache_dir: 缓存目录
        ic_result_dir: IC结果目录
        output_dir: 输出目录
        verbose: 是否打印详细信息
        logger: 日志对象
    
    Returns:
        回测结果字典
    """
    if logger is None:
        logger = get_logger(__name__)
    
    # 校验配置
    config.validate()
    
    logger.info("=" * 40)
    logger.info("综合因子分层回测 [%s]", weight_method)
    logger.info("=" * 40)
    
    if verbose:
        logger.info("配置信息:")
        logger.info("  加权方式: %s", weight_method)
        logger.info("  因子列表: %s", factor_list)
        logger.info("  因子方向: %s", config.factor_direction)
        logger.info("  分层数量: %d (percentile)", config.n_layers)
        logger.info("  多头组合: Layer %s", config.long_layers)
        logger.info("  空头组合: Layer %s", config.short_layers)
    
    # 1. 加载因子数据
    logger.info("加载因子数据...")
    factor_df = load_factor_values(
        factor_cols=factor_cols,
        cache_dir=cache_dir,
        logger=logger
    )
    
    # 2. 加载 IC 结果
    logger.info("加载 IC 结果...")
    ic_results = load_ic_results(
        factor_names=factor_list,
        ic_result_dir=ic_result_dir,
        return_period=return_period,
        logger=logger
    )
    
    # 3. 加载 IC 每日数据（滚动ICIR需要）
    ic_daily_data = None
    if weight_method == 'rolling_icir_weight':
        logger.info("加载 IC 每日数据...")
        ic_daily_data = load_ic_daily(
            factor_names=factor_list,
            ic_result_dir=ic_result_dir,
            return_period=return_period,
            logger=logger
        )
    
    # 4. 标准化因子
    logger.info("标准化因子值...")
    factor_df = standardize_factors(factor_df, factor_cols, logger)
    
    # 5. 计算因子相关性
    logger.info("计算因子相关性...")
    corr_matrix = calc_factor_correlation(factor_df, factor_cols, logger)
    
    # 检查高相关性因子
    high_corr_pairs = []
    for i in range(len(factor_cols)):
        for j in range(i + 1, len(factor_cols)):
            corr_val = corr_matrix.loc[factor_cols[i], factor_cols[j]]
            if abs(corr_val) > 0.7:
                high_corr_pairs.append((factor_cols[i], factor_cols[j], corr_val))
                logger.warning(
                    "高相关因子警告: %s vs %s, corr=%.2f，建议只选其一",
                    factor_cols[i], factor_cols[j], corr_val
                )
    
    # 6. 计算综合因子
    logger.info("计算综合因子 [%s]...", weight_method)
    weight_engine = WeightEngine(
        weight_method=weight_method,
        window=config.rolling_window,
        logger=logger
    )
    
    composite_factor = weight_engine.calculate(
        factor_df=factor_df,
        factor_cols=factor_cols,
        ic_results=ic_results,
        ic_daily_data=ic_daily_data
    )
    
    # 添加综合因子到 factor_df
    factor_df['composite_factor'] = composite_factor
    
    # 7. 获取权重
    weights = weight_engine.get_weights(factor_cols, ic_results)
    
    if verbose:
        logger.info("因子权重:")
        for col, w in weights.items():
            logger.info("  %s: %.4f", col, w)
        
        logger.info("数据统计:")
        logger.info("  日期范围: %s ~ %s", factor_df['date'].min(), factor_df['date'].max())
        logger.info("  股票数量: %d", factor_df['asset'].nunique())
        valid_composite = factor_df['composite_factor'].dropna()
        if len(valid_composite) > 0:
            logger.info("  综合因子范围: %.2f ~ %.2f", valid_composite.min(), valid_composite.max())
    
    # 8. 调用 backtest 分层回测
    logger.info("调用 backtest 分层回测...")
    
    # 加载收益数据
    _, return_df = load_factor_return_data(
        cache_dir=cache_dir,
        logger=logger
    )
    
    # 创建回测引擎（直接传入已计算的综合因子）
    logger.info("创建回测引擎...")
    engine = LayeredBacktestEngine(
        factor_df=factor_df,
        return_df=return_df,
        factor_col='composite_factor',
        return_col='forward_return_1d',
        date_col='date',
        asset_col='asset'
    )
    
    # 执行分层回测
    logger.info("执行分层回测...")
    result = engine.run(
        layer_method='percentile',
        n_layers=config.n_layers,
        factor_direction=config.factor_direction,
        long_layers=config.long_layers,
        short_layers=config.short_layers,
        min_stocks_per_layer=config.min_stocks_per_layer,
        trade_cost_rate=config.trade_cost_rate
    )
    
    # 添加元信息
    result['meta']['factor_name'] = f'{weight_method}_composite'
    
    # 生成报告
    report = engine.generate_report(result)
    logger.info(report)
    
    # 9. 保存综合因子结果
    if output_dir is None:
        project_root = Path(__file__).parent.parent.parent
        output_dir = project_root / 'comprehensive_factor' / 'result'
    
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    
    output_file = Path(output_dir) / f'composite_{weight_method}_{return_period}.json'
    
    # 构建输出数据
    output_data = {
        'meta': {
            'weight_method': weight_method,
            'return_period': return_period,
            'factor_list': factor_list,
            'factor_cols': factor_cols,
            'weights': weights,
            'ic_results': {
                name: {
                    'ic_mean': ic_results.get(name, {}).get('ic_mean'),
                    'icir': ic_results.get(name, {}).get('icir'),
                    'ic_std': ic_results.get(name, {}).get('ic_std')
                }
                for name in factor_list
            },
            'correlation_matrix': backtest_convert(corr_matrix.to_dict()),
            'high_corr_pairs': [
                {'factor_a': pair[0], 'factor_b': pair[1], 'corr': pair[2]}
                for pair in high_corr_pairs
            ],
            'n_factors': len(factor_cols),
            'n_days': result.get('meta', {}).get('n_days_total', 0)
        },
        'backtest_result': {
            'meta': result.get('meta', {}),
            'layer_stats': result.get('layer_stats', []),
            'long_short': result.get('long_short', {}),
            'monotonicity': result.get('monotonicity', {}),
            'trading_cost_analysis': result.get('trading_cost_analysis', {})
        },
        'config': {
            'n_layers': config.n_layers,
            'factor_direction': config.factor_direction,
            'long_layers': config.long_layers,
            'short_layers': config.short_layers,
            'trade_cost_rate': config.trade_cost_rate,
            'min_stocks_per_layer': config.min_stocks_per_layer,
            'rolling_window': config.rolling_window
        },
        'created_at': datetime.now().isoformat()
    }
    
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(backtest_convert(output_data), f, indent=2, ensure_ascii=False)
    
    logger.info("综合因子结果已保存: %s", output_file)
    
    # 10. 保存综合因子每日明细
    daily_output = {
        'meta': {
            'weight_method': weight_method,
            'columns': ['date', 'asset', 'composite_factor'] + factor_cols
        },
        'data': backtest_convert(
            factor_df[['date', 'asset', 'composite_factor'] + factor_cols].to_dict('records')
        )
    }
    
    daily_file = Path(output_dir) / f'composite_{weight_method}_{return_period}_daily.json.gz'
    
    with gzip.open(daily_file, 'wt', encoding='utf-8') as f:
        json.dump(daily_output, f, indent=2, ensure_ascii=False)
    
    logger.info("综合因子每日明细已保存: %s", daily_file)
    
    return output_data


# ============================================================================
# CLI 入口工厂函数
# ============================================================================

def create_cli_entrypoint(
    weight_method: str,
    factor_list: List[str],
    factor_cols: List[str],
    config_class: type,
    return_period: str = '1d',
    cache_dir: Optional[str] = None,
    ic_result_dir: Optional[str] = None
) -> Callable[[], None]:
    """创建 CLI 入口函数
    
    Args:
        weight_method: 加权方式
        factor_list: 因子名称列表
        factor_cols: 因子列名列表
        config_class: Config 类
        return_period: 收益周期
        cache_dir: 缓存目录
        ic_result_dir: IC结果目录
    
    Returns:
        CLI 入口函数
    """
    def main():
        import argparse
        
        parser = argparse.ArgumentParser(description=f'综合因子分层回测 [{weight_method}]')
        parser.add_argument('--cache_dir', type=str, default=cache_dir,
                            help='缓存目录路径')
        parser.add_argument('--ic_result_dir', type=str, default=ic_result_dir,
                            help='IC结果目录路径')
        parser.add_argument('--output_dir', type=str, default=None)
        parser.add_argument('--quiet', action='store_true')
        
        args = parser.parse_args()
        
        logger = get_logger(__name__)
        
        try:
            result = run_composite_backtest(
                weight_method=weight_method,
                factor_list=factor_list,
                factor_cols=factor_cols,
                config=config_class(),
                return_period=return_period,
                cache_dir=args.cache_dir,
                ic_result_dir=args.ic_result_dir,
                output_dir=args.output_dir,
                verbose=not args.quiet,
                logger=logger
            )
            
            # 打印关键结果
            ls_stats = result.get('backtest_result', {}).get('long_short', {})
            logger.info("=" * 40)
            logger.info("综合因子回测结果")
            logger.info("=" * 40)
            logger.info("多空年化收益: %.2f%%", ls_stats.get('long_short_return_annual', 0) * 100)
            logger.info("多空夏普比率: %.2f", ls_stats.get('long_short_sharpe', 0))
            logger.info("回测完成，退出码 0")
            
        except Exception as e:
            logger.error("回测执行异常: %s", e)
            raise
    
    return main