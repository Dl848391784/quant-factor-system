#!/usr/bin/env python3
"""
IC结果构建公共模块 - factor_ic 公共模块

功能：
1. 将 ic_calculator 返回值转换为符合 MODULE.md 规范的完整 JSON 结构
2. 计算 rolling_ic_mean（20日窗口，min_periods=10）
3. 构建 sample_stats（口径范围说明）
4. 构建 factor_stats、summary 等字段

作者: 云瑶
日期: 2026-05-22
"""

import pandas as pd
import numpy as np
from datetime import datetime
from typing import Dict, List, Any, Optional, Tuple
from pathlib import Path

# 导入类型转换函数
from .convert_types import convert_to_native_types
from .logger_config import get_logger
logger = get_logger(__name__)


def build_ic_result(
    ic_result: Dict,
    raw_metadata: Dict,
    factor_name: str,
    return_period: str = '1d',
    data_source: str = '',
    factor_col: str = '',
    update_mode: str = 'full'
) -> Dict:
    """
    构建 IC 分析完整结果（符合 MODULE.md 输出结构统一性规范）
    
    参数:
        ic_result: calculate_ic_with_direction_verification 返回值
            - 必须包含: ic_series, ic_mean, ic_std, icir, p_value,
              statistical_significance, factor_direction, economic_significance,
              icir_stability, ic_distribution_consistency, positive_ratio, n_days
        raw_metadata: load_factor_return_data 返回的原始数据元信息
            - 必须包含: period_start, period_end, total_days, avg_stocks_per_day
        factor_name: 因子名称（如 'rsi_1d', 'volume_ratio_1d'）
        return_period: 收益周期（如 '1d'）
        data_source: 数据来源路径
        factor_col: 因子列名
        update_mode: 更新模式（'full', 'incremental', 'skip', 'failed'）
    
    返回:
        符合 MODULE.md 规范的完整 JSON 结构字典
    
    规范:
        所有字段必须符合 MODULE.md "输出结构统一性规范"
        顶层字段顺序: factor_name, calculation_date, period, ic_metrics, sample_stats,
        statistical_significance, factor_direction, economic_significance, icir_stability,
        ic_distribution_consistency, dates, ic_values, rolling_ic_mean, positive_ratio,
        n_assets, summary, factor_stats, update_mode
    """
    # ========== 提取 ic_result 数据 ==========
    ic_series = ic_result['ic_series']
    ic_mean = ic_result['ic_mean']
    ic_std = ic_result['ic_std']
    icir = ic_result['icir']
    positive_ratio = ic_result['positive_ratio']
    n_days = ic_result['n_days']
    
    # 五维度判断（直接使用公共模块返回）
    statistical_significance = ic_result['statistical_significance']
    factor_direction_judgment = ic_result['factor_direction']
    economic_significance = ic_result['economic_significance']
    icir_stability = ic_result['icir_stability']
    ic_distribution_consistency = ic_result['ic_distribution_consistency']
    
    # ========== 构建日期范围 ==========
    dates_from_series = [str(d) for d in ic_series.index]
    period_start = dates_from_series[0] if dates_from_series else raw_metadata.get('period_start', '')
    period_end = dates_from_series[-1] if dates_from_series else raw_metadata.get('period_end', '')
    
    # ========== 构建 period ==========
    period = {
        'start': period_start,
        'end': period_end,
        'description': 'IC计算覆盖日期范围'
    }
    
    # ========== 构建 ic_metrics ==========
    ic_metrics = {
        'ic_mean': round(float(ic_mean), 6),
        'ic_std': round(float(ic_std), 6),
        'icir': round(float(icir), 4),
        'p_value': statistical_significance['p_value'],
        'p_value_display': statistical_significance['p_value_display']
    }
    
    # ========== 构建 sample_stats ==========
    # 口径说明：avg_stocks_period 描述过滤后的统计范围
    # 注意：avg_stocks_per_day 来自 raw_metadata（data_loader 已计算）
    sample_stats = {
        'total_days': raw_metadata['total_days'],  # 原始缓存日期数（dropna 前）
        'valid_days': n_days,                      # 实际计算出 IC 的天数
        'avg_stocks_per_day': raw_metadata.get('avg_stocks_per_day', 0),  # 使用 raw_metadata 值
        'avg_stocks_period': {
            'start': period_start,
            'end': period_end,
            'description': '过滤后每日平均股票数（dropna 后）'
        }
    }
    
    # ========== 构建 IC 时间序列 ==========
    dates = [str(d) for d in ic_series.index]
    ic_values = [round(float(v), 6) for v in ic_series.values]
    
    # 计算 rolling_ic_mean（20日窗口，min_periods=10）— 复用公共函数
    rolling_ic_mean = build_rolling_ic_mean(ic_series)
    
    # ========== 构建 n_assets ==========
    # 从 ic_series 无法直接获取，需要外部传入或使用 raw_metadata
    n_assets = raw_metadata.get('avg_stocks_per_day', 0)
    
    # ========== 构建 summary ==========
    summary = {
        'ic_performance': _format_ic_performance(ic_mean, icir),
        'statistical_significance': statistical_significance['conclusion'],
        'factor_direction': factor_direction_judgment['conclusion'],
        'economic_significance': economic_significance['conclusion'],
        'recommendation': _format_recommendation(
            statistical_significance['is_significant'],
            economic_significance['is_economically_significant'],
            icir_stability['is_stable']
        )
    }
    
    # ========== 构建 factor_stats ==========
    factor_stats = {
        'factor_name': factor_name,
        'return_period': return_period,
        'data_source': data_source,
        'total_days': raw_metadata['total_days'],
        'valid_days': n_days
    }
    
    # ========== 组装完整结果 ==========
    result = {
        'factor_name': factor_name,
        'calculation_date': datetime.now().isoformat(),
        'period': period,
        'ic_metrics': ic_metrics,
        'sample_stats': sample_stats,
        'statistical_significance': statistical_significance,
        'factor_direction': factor_direction_judgment,
        'economic_significance': economic_significance,
        'icir_stability': icir_stability,
        'ic_distribution_consistency': ic_distribution_consistency,
        'dates': dates,
        'ic_values': ic_values,
        'rolling_ic_mean': rolling_ic_mean,
        'positive_ratio': positive_ratio,
        'n_assets': n_assets,
        'summary': summary,
        'factor_stats': factor_stats,
        'update_mode': update_mode,
        'factor_col': factor_col  # 额外字段，用于追踪
    }
    
    # 类型转换（确保 JSON 兼容）
    result = convert_to_native_types(result)
    
    return result


def build_sample_stats(
    raw_metadata: Dict,
    n_days: int,
    factor_df: pd.DataFrame,
    period_start: str,
    period_end: str,
    avg_stocks_description: str = '过滤后每日平均股票数（dropna 后）'
) -> Dict:
    """
    构建样本统计字段
    
    参数:
        raw_metadata: 原始数据元信息
        n_days: 有效 IC 天数
        factor_df: 过滤后因子数据 DataFrame
        period_start: 覆盖起始日期
        period_end: 覆盖结束日期
        avg_stocks_description: 口径范围说明
    
    返回:
        sample_stats 字典
    """
    avg_stocks_per_day = int(factor_df.groupby('date').size().mean())
    
    return {
        'total_days': raw_metadata['total_days'],
        'valid_days': n_days,
        'avg_stocks_per_day': avg_stocks_per_day,
        'avg_stocks_period': {
            'start': period_start,
            'end': period_end,
            'description': avg_stocks_description
        }
    }


def build_rolling_ic_mean(
    ic_series: pd.Series,
    window: int = 20,
    min_periods: int = 10
) -> List[Optional[float]]:
    """
    计算滚动 IC 均值
    
    参数:
        ic_series: IC 时间序列（pandas Series，index 为日期）
        window: 滚动窗口（默认 20 日）
        min_periods: 最小有效数据点数（默认 10）
    
    返回:
        滚动均值列表（NaN → None）
    
    规范:
        前 min_periods-1 个时间点为 None（数据不足）
    """
    rolling_mean = ic_series.rolling(window=window, min_periods=min_periods).mean()
    return [round(float(v), 6) if pd.notna(v) else None for v in rolling_mean.values]


def build_error_result(
    factor_name: str,
    error_msg: str,
    return_period: str = '1d',
    data_source: str = ''
) -> Dict:
    """
    构建错误情况下的默认结果（符合 MODULE.md 输出结构统一性规范）
    
    参数:
        factor_name: 因子名称
        error_msg: 错误消息
        return_period: 收益周期
        data_source: 数据来源
    
    返回:
        包含所有必需字段（默认值）的完整结构
    """
    return {
        'success': False,
        'error': error_msg,
        'factor_name': factor_name,
        'calculation_date': datetime.now().strftime('%Y-%m-%d'),
        'period': {
            'start': '',
            'end': '',
            'description': f'数据加载失败: {error_msg}'
        },
        'ic_metrics': {
            'ic_mean': None,
            'ic_std': None,
            'icir': None,
            'p_value': None,
            'p_value_display': 'N/A'
        },
        'sample_stats': {
            'total_days': 0,
            'valid_days': 0,
            'avg_stocks_per_day': 0,
            'avg_stocks_period': {
                'start': '',
                'end': '',
                'description': '数据加载失败'
            }
        },
        'statistical_significance': {
            't_stat': None,
            'p_value': None,
            'p_value_display': 'N/A',
            'nw_lag': None,
            'nw_lag_method': 'N/A',
            'is_significant': False,
            'conclusion': f'数据加载失败，无法进行统计检验: {error_msg}'
        },
        'factor_direction': {
            'ic_mean': None,
            'ic_mean_sign': 'unknown',
            'direction_usage': '无法确定',
            'conclusion': '数据加载失败，无法判断因子方向'
        },
        'economic_significance': {
            'abs_ic_mean': None,
            'threshold_used': {'weak': 0.03, 'strong': 0.05},
            'level': 'none',
            'is_economically_significant': False,
            'conclusion': '数据加载失败，无法判断经济显著性'
        },
        'icir_stability': {
            'icir': None,
            'threshold_used': {'excellent': 2.0, 'good': 1.0},
            'level': 'none',
            'is_stable': False,
            'conclusion': '数据加载失败，无法判断ICIR稳定性'
        },
        'ic_distribution_consistency': {
            'positive_ratio': None,
            'ic_mean_sign': 'unknown',
            'is_consistent': False,
            'consistency_type': 'unknown',
            'distribution_hint': 'N/A',
            'conclusion': '数据加载失败，无法判断IC分布一致性'
        },
        'dates': [],
        'ic_values': [],
        'rolling_ic_mean': [],
        'positive_ratio': None,
        'n_assets': 0,
        'summary': {
            'ic_performance': '数据加载失败',
            'statistical_significance': '无法检验',
            'factor_direction': '无法判断',
            'economic_significance': '无法判断',
            'recommendation': f'检查数据源完整性: {error_msg}'
        },
        'factor_stats': {
            'factor_name': factor_name,
            'return_period': return_period,
            'data_source': data_source,
            'total_days': 0,
            'valid_days': 0
        },
        'update_mode': 'failed'
    }


def _format_ic_performance(ic_mean: float, icir: float) -> str:
    """格式化 IC 表现描述"""
    if abs(ic_mean) >= 0.05:
        level = '强'
    elif abs(ic_mean) >= 0.03:
        level = '中'
    else:
        level = '弱'
    
    if icir >= 2.0:
        stability = '优秀'
    elif icir >= 1.0:
        stability = '良好'
    else:
        stability = '一般'
    
    return f'IC均值={ic_mean:.4f}（{level}），ICIR={icir:.2f}（{stability}）'


def _format_recommendation(
    is_significant: bool,
    is_economically_significant: bool,
    is_stable: bool
) -> str:
    """格式化推荐建议"""
    if is_significant and is_economically_significant and is_stable:
        return '因子有效，可用于后续分层回测和组合构建'
    elif is_significant and is_economically_significant:
        return '因子统计显著、经济显著，但稳定性一般，建议观察更长周期'
    elif is_significant:
        return '因子统计显著，但经济显著性不足，可用于辅助筛选'
    else:
        return '因子统计不显著，建议检查因子计算逻辑或数据质量'


# ========== 输出路径辅助函数 ==========

def get_ic_output_path(factor_name: str, return_period: str = '1d') -> Path:
    """
    获取 IC 结果输出路径
    
    参数:
        factor_name: 因子名称（如 'rsi', 'volume_ratio'）
        return_period: 收益周期（如 '1d'）
    
    返回:
        输出文件路径（Path 对象）
    
    规范:
        输出路径: factor_ic/result/ic_<factor_name>_<return_period>_analysis_result.json
    """
    result_dir = Path(__file__).parent.parent / 'result'
    result_dir.mkdir(parents=True, exist_ok=True)
    
    output_filename = f"ic_{factor_name}_{return_period}_analysis_result.json"
    return result_dir / output_filename


def save_ic_result(result: Dict, output_path: Optional[Path] = None) -> Path:
    """
    保存 IC 结果到 JSON 文件
    
    参数:
        result: IC 结果字典
        output_path: 输出路径（可选，默认自动生成）
    
    返回:
        实际保存路径
    
    规范:
        输出前进行字段完整性校验
    """
    import json
    
    if output_path is None:
        # 从 result 中提取因子信息生成路径
        factor_name = result.get('factor_name', 'unknown')
        return_period = result.get('factor_stats', {}).get('return_period', '1d')
        # 只处理后缀 _1d，避免误处理因子名中间的 _1d（如 my_1d_factor_1d → my_1d_factor）
        factor_name_clean = factor_name[:-3] if factor_name.endswith('_1d') else factor_name
        output_path = get_ic_output_path(factor_name_clean, return_period)
    
    # 确保目录存在
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    # 保存（统一转换，添加异常处理）
    try:
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(convert_to_native_types(result), f, indent=2, ensure_ascii=False)
        logger.info(f"  ✓ 结果已保存: {output_path}")
    except PermissionError as e:
        logger.error(f"保存失败（权限错误）: {output_path} - {e}")
        raise
    except OSError as e:
        logger.error(f"保存失败（磁盘满/路径错误）: {output_path} - {e}")
        raise
    return output_path