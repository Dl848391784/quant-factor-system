#!/usr/bin/env python3
"""
因子IC计算主入口模板 - factor_ic 公共模块

功能：
1. 统一主入口逻辑（模式判断 → 分支调用 → 输出）
2. 封装全量/增量/跳过三种模式
3. 简化新增因子脚本的开发成本

作者: 云瑶
日期: 2026-05-22
"""

import json
import pandas as pd
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional, Callable, Any

# 导入日志
from .logger_config import get_logger
logger = get_logger(__name__)

# 导入数据加载
from .data_loader import load_factor_return_data, get_factor_cache_path, get_return_cache_path

# 导入 IC 计算
from .ic_calculator import calculate_ic_with_direction_verification, calculate_ic_statistics

# 导入结果构建
from .ic_result_builder import build_ic_result, build_error_result, save_ic_result, get_ic_output_path

# 导入增量引擎
from .incremental_engine import incremental_update_ic, should_use_incremental

# 导入类型转换
from .convert_types import convert_to_native_types


def run_factor_ic_analysis(
    factor_name: str,
    factor_col: str,
    return_period: str = '1d',
    return_col: str = 'forward_return_1d',
    factor_cols: Optional[List[str]] = None,
    min_stocks: int = 10,
    force_full: bool = False,
    output_path: Optional[Path] = None,
    factor_cache_path: Optional[Path] = None,
    return_cache_path: Optional[Path] = None,
    additional_factor_files: Optional[Dict[str, Path]] = None,
    custom_factor_calculation: Optional[Callable] = None,
    custom_factor_calculation_params: Optional[Dict] = None,
    logger=None
) -> Dict:
    """
    因子 IC 分析统一主入口
    
    参数:
        factor_name: 因子名称（如 'rsi', 'volume_ratio'）
        factor_col: 主因子列名（如 'rsi_6', 'volume_ratio_5'）
        return_period: 收益周期（如 '1d'）
        return_col: 收益列名（缓存中）
        factor_cols: 需加载的因子列列表（默认 = [factor_col]）
        min_stocks: 最小股票数阈值
        force_full: 是否强制全量计算
        output_path: 输出文件路径（默认自动生成）
        factor_cache_path: 因子缓存路径（默认自动检测）
        return_cache_path: 收益缓存路径（默认自动检测）
        additional_factor_files: 额外因子文件（如换手率数据）
        custom_factor_calculation: 自定义因子计算函数（可选）
            - 用于需要预处理因子值的场景（如 KDJ 计算）
            - 函数签名: (factor_df: pd.DataFrame) -> pd.DataFrame
        custom_factor_calculation_params: 自定义因子计算参数
    
    返回:
        IC 分析结果字典（符合 MODULE.md 输出结构统一性规范）
    
    流程:
        1. 判断模式（全量/增量/跳过）
        2. 加载数据
        3. 执行计算（全量用 calculate_ic_with_direction_verification，增量用 incremental_update_ic）
        4. 构建输出
        5. 保存结果
    
    示例:
        # RSI 因子（直接用缓存列）
        result = run_factor_ic_analysis(
            factor_name='rsi',
            factor_col='rsi_6'
        )
        
        # KDJ 因子（需要自定义计算）
        def calculate_kdj_j(factor_df):
            # ... KDJ 计算逻辑 ...
            return factor_df
        
        result = run_factor_ic_analysis(
            factor_name='kdj_j',
            factor_col='kdj_j',
            factor_cols=['close', 'high', 'low'],
            custom_factor_calculation=calculate_kdj_j
        )
    """
    # logger fallback 初始化（使用模块级已导入的 get_logger）
    if logger is None:
        logger = get_logger(__name__)
    
    logger.info("=" * 60)
    logger.info(f"因子 IC 分析: {factor_name}_{return_period}")
    logger.info("=" * 60)
    
    # ========== 确定路径 ==========
    if output_path is None:
        output_path = get_ic_output_path(factor_name, return_period)
    
    if factor_cache_path is None:
        factor_cache_path = get_factor_cache_path()
    
    if return_cache_path is None:
        return_cache_path = get_return_cache_path()
    
    if factor_cols is None:
        factor_cols = [factor_col]
    
    data_source = str(factor_cache_path)
    
    # ========== 判断模式 ==========
    logger.info("[模式判断] 判断更新模式...")
    
    # 先尝试加载数据（用于判断模式）
    try:
        factor_df, return_df, raw_metadata = load_factor_return_data(
            factor_cols=factor_cols,
            return_col=return_col,
            factor_cache_path=factor_cache_path,
            return_cache_path=return_cache_path,
            additional_factor_files=additional_factor_files,
            logger=logger
        )
    except FileNotFoundError as e:
        # 缓存不存在：返回错误结构
        logger.error(f"数据加载失败: {e}")
        return build_error_result(
            factor_name=f'{factor_name}_{return_period}',
            error_msg=str(e),
            return_period=return_period,
            data_source=data_source
        )
    except Exception as e:
        # 其他异常：返回错误结构
        logger.error(f"数据加载异常: {e}")
        return build_error_result(
            factor_name=f'{factor_name}_{return_period}',
            error_msg=str(e),
            return_period=return_period,
            data_source=data_source
        )
    
    # 判断模式
    use_incremental = should_use_incremental(output_path, factor_df, force_full)
    
    # ========== 执行计算 ==========
    if use_incremental:
        # 增量模式
        logger.info("[执行模式] 增量更新...")
        
        result = incremental_update_ic(
            output_path=output_path,
            factor_df_full=factor_df,
            return_df_full=return_df,
            raw_metadata=raw_metadata,
            factor_name=f'{factor_name}_{return_period}',
            factor_col=factor_col,
            return_col=return_col,
            min_stocks=min_stocks
        )
        
        # 增量结果需要补充五维度判断
        if result.get('update_mode') != 'need_full':
            # 使用 calculate_ic_with_direction_verification 补充五维度判断
            
            # 检查长度一致性（防止数据不一致）
            if len(result.get('ic_values', [])) != len(result.get('dates', [])):
                logger.warning(
                    f"增量数据长度不一致: ic_values={len(result.get('ic_values', []))}, "
                    f"dates={len(result.get('dates', []))}"
                )
                # 返回原始结果，不补充五维度
                return result
            
            # 构造 IC 序列（dates 作为索引）
            ic_series = pd.Series(
                result['ic_values'],
                index=result['dates']
            )
            
            # 过滤 None 得到有效 IC
            valid_ic = ic_series[ic_series.notna()]
            valid_dates = valid_ic.index.tolist()
            
            if len(valid_ic) > 0:
                # 调用统计计算（五维度判断）
                stats_result = calculate_ic_statistics(valid_ic)
                
                # 补充五维度判断字段（使用 .get() 鷻加默认值防止 KeyError）
                result['statistical_significance'] = stats_result.get('statistical_significance', {})
                result['factor_direction'] = stats_result.get('factor_direction', {})
                result['economic_significance'] = stats_result.get('economic_significance', {})
                result['icir_stability'] = stats_result.get('icir_stability', {})
                result['ic_distribution_consistency'] = stats_result.get('ic_distribution_consistency', {})
                result['summary'] = stats_result.get('summary', '无')
                
                # 更新统计量（基于有效 IC，使用 .get() 防止 KeyError）
                result['ic_mean'] = stats_result.get('ic_mean', 0.0)
                result['ic_std'] = stats_result.get('ic_std', 0.0)
                result['icir'] = stats_result.get('icir', 0.0)
                result['p_value'] = stats_result.get('p_value', 1.0)
                result['t_stat'] = stats_result.get('t_stat', 0.0)
                result['positive_ratio'] = stats_result.get('positive_ratio', 0.0)
                result['n_days'] = stats_result.get('n_days', 0)
                
                # 更新有效数据（保持一致性）
                result['valid_dates'] = valid_dates
                result['valid_ic_values'] = valid_ic.tolist()
                
                # 记录日志（使用 .get() 防止 KeyError）
                logger.info(
                    f"五维度补充完成: 有效天数={len(valid_ic)}, "
                    f"IC均值={stats_result.get('ic_mean', 0.0):.4f}, "
                    f"ICIR={stats_result.get('icir', 0.0):.2f}"
                )
                
                # 更新缓存
                with open(output_path, 'w', encoding='utf-8') as f:
                    json.dump(convert_to_native_types(result), f, ensure_ascii=False, indent=2)
        
        return result
    
    else:
        # 全量模式
        logger.info("[执行模式] 全量计算...")
        
        # 自定义因子计算（如有）
        if custom_factor_calculation is not None:
            logger.info("[因子预处理] 执行自定义因子计算...")
            params = custom_factor_calculation_params or {}
            factor_df = custom_factor_calculation(factor_df, **params)
            logger.info(f"处理后数据: {len(factor_df)} 行")
        
        # 计算 IC（五维度判断）
        logger.info("[IC 计算] 计算 IC（含五维度判断）...")
        
        try:
            ic_result = calculate_ic_with_direction_verification(
                factor_df=factor_df,
                return_df=return_df,
                factor_col=factor_col,
                return_col=return_col,
                date_col='date',
                asset_col='asset',
                min_stocks=min_stocks,
                logger=logger
            )
            
            logger.info(f"IC 均值: {ic_result['ic_mean']:.4f}")
            logger.info(f"ICIR: {ic_result['icir']:.2f}")
            logger.info(f"t 统计量: {ic_result['statistical_significance']['t_stat']:.2f}")
            
        except Exception as e:
            logger.error(f"IC 计算失败: {e}")
            return build_error_result(
                factor_name=f'{factor_name}_{return_period}',
                error_msg=f'IC 计算失败: {e}',
                return_period=return_period,
                data_source=data_source
            )
        
        # 构建完整结果
        logger.info("[结果构建] 构建完整输出结构...")
        
        result = build_ic_result(
            ic_result=ic_result,
            raw_metadata=raw_metadata,
            factor_name=f'{factor_name}_{return_period}',
            return_period=return_period,
            data_source=data_source,
            factor_col=factor_col,
            update_mode='full'
        )
        
        # 保存
        save_ic_result(result, output_path)
        
        logger.info("=" * 60)
        logger.info(f"完成！共计算 {result['sample_stats']['valid_days']} 天有效 IC")
        logger.info("=" * 60)
        
        return result


# ========== 快捷函数 ==========

def run_simple_factor_ic(
    factor_name: str,
    factor_col: str,
    **kwargs
) -> Dict:
    """
    快捷函数：简单因子 IC 分析
    
    适用于直接使用缓存列的因子（如 RSI、量比）
    
    参数:
        factor_name: 因子名称
        factor_col: 因子列名
        **kwargs: 其他参数（传递给 run_factor_ic_analysis）
    
    示例:
        result = run_simple_factor_ic('rsi', 'rsi_6')
        result = run_simple_factor_ic('volume_ratio', 'volume_ratio_5')
    """
    return run_factor_ic_analysis(
        factor_name=factor_name,
        factor_col=factor_col,
        factor_cols=[factor_col],
        **kwargs
    )


def run_complex_factor_ic(
    factor_name: str,
    factor_col: str,
    factor_cols: List[str],
    custom_factor_calculation: Callable,
    **kwargs
) -> Dict:
    """
    快捷函数：复杂因子 IC 分析
    
    适用于需要预处理的因子（如 KDJ、布林带）
    
    参数:
        factor_name: 因子名称
        factor_col: 最终因子列名
        factor_cols: 需加载的原始因子列
        custom_factor_calculation: 自定义因子计算函数
        **kwargs: 其他参数
    
    示例:
        def calculate_kdj_j(factor_df):
            # KDJ 计算逻辑
            ...
            return factor_df
        
        result = run_complex_factor_ic(
            factor_name='kdj_j',
            factor_col='kdj_j',
            factor_cols=['close', 'high', 'low'],
            custom_factor_calculation=calculate_kdj_j
        )
    """
    return run_factor_ic_analysis(
        factor_name=factor_name,
        factor_col=factor_col,
        factor_cols=factor_cols,
        custom_factor_calculation=custom_factor_calculation,
        **kwargs
    )


# ========== CLI 支持 ==========

def main():
    """
    CLI 主入口
    
    用法:
        python -m factor_ic.common.factor_ic_runner --factor rsi --col rsi_6
    """
    import argparse
    
    parser = argparse.ArgumentParser(description='因子 IC 分析')
    parser.add_argument('--factor', required=True, help='因子名称')
    parser.add_argument('--col', required=True, help='因子列名')
    parser.add_argument('--period', default='1d', help='收益周期')
    parser.add_argument('--min-stocks', type=int, default=10, help='最小股票数')
    parser.add_argument('--force-full', action='store_true', help='强制全量计算')
    
    args = parser.parse_args()
    
    result = run_simple_factor_ic(
        factor_name=args.factor,
        factor_col=args.col,
        return_period=args.period,
        min_stocks=args.min_stocks,
        force_full=args.force_full
    )
    
    logger.info(f"结果: {result.get('update_mode', 'unknown')}")


if __name__ == '__main__':
    main()