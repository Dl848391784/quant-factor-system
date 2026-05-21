"""
通用 IC 计算模块 - 支持五维度独立判断

遵循 PROJECT.md 规范：
1. 计算每日 IC（Spearman 秩相关）
2. 五维度独立判断：统计显著性、因子方向、经济显著性、ICIR稳定性、IC分布一致性
3. 输出独立的五维度判断结果，不合并为有效/无效结论

作者: 云瑶
日期: 2026-05-11
"""

import pandas as pd
import numpy as np
from scipy import stats
from typing import Dict, Optional, Tuple
import math

from .logger_config import get_logger


def calculate_ic_with_direction_verification(
    factor_df: pd.DataFrame,
    return_df: pd.DataFrame,
    factor_col: str,
    return_col: str = 'forward_return',
    date_col: str = 'date',
    asset_col: str = 'asset',
    min_stocks: int = 10,
    logger=None
) -> Dict:
    """
    计算因子 IC，五维度独立判断
    
    流程：
    1. 使用原始因子值计算每日 IC（Spearman 秩相关）
    2. 五维度独立判断：
       - 统计显著性（p_value, t_stat）
       - 因子方向（ic_mean 符号）
       - 经济显著性（|ic_mean| 大小）
       - ICIR稳定性（ICIR 大小）
       - IC分布一致性（positive_ratio 与 ic_mean_sign 匹配）
    3. 各维度独立输出，不合并为"有效/无效"结论
    
    **等价性说明（重要）：**
    本函数内部调用 calculate_single_day_ic 计算每日 IC（第157-159行）。
    增量计算必须直接调用 calculate_single_day_ic，确保与全量计算使用同一核心函数。
    修改本函数或 calculate_single_day_ic 时，必须同步更新单元测试验证等价性。
    遵循 PROJECT.md "全量/增量 IC 计算等价性规范"。
    
    参数:
    ---
    factor_df : DataFrame
        因子数据，包含 [date_col, asset_col, factor_col]
    return_df : DataFrame
        收益数据，包含 [date_col, asset_col, return_col]
    factor_col : str
        因子列名
    return_col : str
        收益列名，默认 'forward_return'
    date_col : str
        日期列名，默认 'date'
    asset_col : str
        资产列名，默认 'asset'
    min_stocks : int
        每日最少股票数，默认 10
    logger : Logger
        日志记录器（由调用方传入，默认使用模块 logger）
        
    返回:
    ---
    dict: {
        'ic_series': pd.Series,
        'ic_mean': float,
        'ic_std': float,
        'icir': float,
        'p_value': float,
        'p_value_display': str,
        't_stat': float,
        
        # 五维度判断（独立输出，不合并）
        'statistical_significance': {
            'p_value': float,
            'p_value_display': str,
            't_stat': float,
            'nw_lag': int,
            'nw_lag_method': str,
            'is_significant': bool,
            'conclusion': str
        },
        'factor_direction': {
            'ic_mean': float,
            'ic_mean_sign': 'negative' | 'positive' | 'zero',
            'direction_usage': str,
            'conclusion': str
        },
        'economic_significance': {
            'abs_ic_mean': float,
            'threshold_used': dict,
            'level': 'strong' | 'weak' | 'none',
            'is_economically_significant': bool,
            'conclusion': str
        },
        'icir_stability': {
            'icir': float,
            'threshold_used': dict,
            'level': 'excellent' | 'good' | 'usable' | 'none',
            'is_stable': bool,
            'conclusion': str
        },
        'ic_distribution_consistency': {
            'positive_ratio': float,
            'ic_mean_sign': str,
            'is_consistent': bool,
            'consistency_type': 'consistent' | 'balanced' | 'contradictory',
            'distribution_hint': str,
            'conclusion': str
        },
        
        'positive_ratio': float,
        'n_days': int,
        'summary': str
    }
    
    注意:
    ---
    方向判断仅描述 ic_mean 符号，不代表因子有效性。
    有效性判断请参考 statistical_significance、economic_significance、icir_stability。
    """
    if logger is None:
        logger = get_logger(__name__)
    
    # ========== 输入验证 ==========
    if factor_df.empty:
        raise ValueError("factor_df 不能为空")
    
    if return_df.empty:
        raise ValueError("return_df 不能为空")
    
    required_factor_cols = [date_col, asset_col, factor_col]
    required_return_cols = [date_col, asset_col, return_col]
    
    for col in required_factor_cols:
        if col not in factor_df.columns:
            raise KeyError(f"factor_df 缺少列: '{col}'")
    
    for col in required_return_cols:
        if col not in return_df.columns:
            raise KeyError(f"return_df 缺少列: '{col}'")
    
    # ========== 数据合并 ==========
    merged = pd.merge(
        factor_df[[date_col, asset_col, factor_col]],
        return_df[[date_col, asset_col, return_col]],
        on=[date_col, asset_col],
        how='inner'
    )
    
    if merged.empty:
        raise ValueError("factor_df 和 return_df 无法匹配")
    
    merged = merged.dropna(subset=[factor_col, return_col])
    
    if merged.empty:
        raise ValueError("合并后数据全部为缺失值")
    
    # ========== 按日期计算正向 IC ==========
    ic_list = []
    
    for date, daily_data in merged.groupby(date_col):
        ic_value = calculate_single_day_ic(
            daily_data, factor_col, return_col, min_stocks
        )
        if ic_value is not None:
            ic_list.append({'date': date, 'ic': ic_value})
    
    if not ic_list:
        raise ValueError(f"没有有效的交易日（每交易日股票数 < {min_stocks}）")
    
    ic_df = pd.DataFrame(ic_list)
    ic_series = ic_df.set_index('date')['ic']
    
    # 显式排序：确保 ic_series.index 按日期升序排列
    # 遵循 PROJECT.md 规范：ic_series.index 必须按日期排序
    # 原因：rolling 计算按位置顺序，若 index 乱序会导致 dates 与 rolling_ic_mean 对应错误
    # 注意：pandas groupby 默认 sort=True，但显式排序可消除隐式依赖风险
    ic_series = ic_series.sort_index()
    
    # ========== 计算统计量 ==========
    ic_mean = ic_series.mean()
    ic_std = ic_series.std()
    
    # ICIR 使用 |ic_mean| / ic_std，统一判断标准（反向因子也适用）
    # 注意：除零防护与 calculate_ic_statistics 保持一致（三元表达式）
    icir = abs(ic_mean) / ic_std if ic_std > 0 else 0.0
    
    n = len(ic_series)
    
    # Newey-West 调整的 t 统计量和 p 值（自动选择 lag）
    t_stat, p_value, nw_lag = _newey_west_t_stat(ic_series)
    
    # IC > 0 的比例
    positive_count = (ic_series > 0).sum()
    positive_ratio = positive_count / n
    
    # ========== 五维度判断（独立输出）==========
    # 维度1: 统计显著性
    statistical_significance = _assess_statistical_significance(
        p_value, t_stat, nw_lag, p_threshold=0.05, t_threshold=1.96
    )
    
    # 维度2: 方向判断（ic_mean符号）
    factor_direction = _assess_factor_direction(ic_mean)
    
    # 维度3: 经济显著性
    economic_significance = _assess_economic_significance(
        abs(ic_mean), weak_threshold=0.03, strong_threshold=0.05
    )
    
    # 维度4: ICIR 稳定性
    icir_stability = _assess_icir_stability(icir)
    
    # 维度5: IC 分布一致性
    ic_distribution_consistency = _assess_ic_distribution_consistency(
        positive_ratio, factor_direction['ic_mean_sign']
    )
    
    # ========== 生成摘要 ==========
    # p_value 格式化（避免 0.0 显示问题）
    p_value_str = _format_p_value(p_value)
    
    # summary 格式规范：positive_ratio 独立描述，不嵌入一致性判断文字
    # 一致性判断在 ic_distribution_consistency 中独立输出
    summary = (
        f"IC均值={ic_mean:.4f}, "
        f"ICIR={icir:.2f}, "
        f"p值={p_value_str}, "
        f"方向={factor_direction['ic_mean_sign']}, "
        f"统计显著={statistical_significance['is_significant']}, "
        f"经济显著={economic_significance['level']}, "
        f"ICIR稳定={icir_stability['level']}, "
        f"正比例={positive_ratio:.1%}（IC>0天数占比）"
    )
    
    return {
        'ic_series': ic_series,
        'ic_mean': ic_mean,
        'ic_std': ic_std,
        'icir': icir,
        'p_value': p_value,  # 保留原始值
        'p_value_display': p_value_str,  # 格式化显示值
        't_stat': round(t_stat, 4),
        
        # 五维度判断（独立输出）
        'statistical_significance': statistical_significance,
        'factor_direction': factor_direction,
        'economic_significance': economic_significance,
        'icir_stability': icir_stability,
        'ic_distribution_consistency': ic_distribution_consistency,
        
        'positive_ratio': positive_ratio,
        'n_days': n,
        'summary': summary
    }


def calculate_single_day_ic(
    daily_data: pd.DataFrame,
    factor_col: str,
    return_col: str = 'forward_return',
    min_stocks: int = 10,
    logger=None
) -> Optional[float]:
    """
    计算单日的 IC 值（核心算法函数）
    
    用于增量计算场景，确保与全量计算使用相同的核心算法和边界处理。
    
    **遵循 PROJECT.md 规范：**
    增量 IC 计算必须复用全量计算的核心函数，不能直接调用底层算法。
    
    参数:
        daily_data: 单日数据 DataFrame，包含因子值和收益值
        factor_col: 因子列名
        return_col: 收益列名，默认 'forward_return'
        min_stocks: 每日最少股票数，默认 10
        logger: 日志记录器（由调用方传入，默认使用模块 logger）
        
    返回:
        float: IC 值（可能为 0.0）
        None: 若股票数不足或其他原因无法计算
        
    边界处理:
        - 股票数 < min_stocks → 返回 None（跳过该日）
        - 因子值全相同 → 返回 0.0（相关性无法定义）
        - 收益值全相同 → 返回 0.0（相关性无法定义）
        - IC 为 NaN → 返回 0.0
    """
    if logger is None:
        logger = get_logger(__name__)
    
    # 股票数不足
    if len(daily_data) < min_stocks:
        return None
    
    # 因子值全相同（无法定义相关性）
    if daily_data[factor_col].nunique() == 1:
        return 0.0
    
    # 收益值全相同（无法定义相关性）
    if daily_data[return_col].nunique() == 1:
        return 0.0
    
    # 使用 Spearman 秩相关计算正向 IC（不反转）
    ic_value = daily_data[factor_col].corr(
        daily_data[return_col],
        method='spearman'
    )
    
    # NaN 处理
    if pd.isna(ic_value):
        return 0.0
    
    return ic_value


def _newey_west_t_stat(ic_series: pd.Series, lag: int = None) -> Tuple[float, float, int]:
    """
    Newey-West 调整的 t 统计量
    
    用于处理 IC 序列的自相关问题。IC 序列通常存在时间序列自相关，
    使用原始 OLS 标准误会导致 t 统计量偏高、p 值偏低，误判显著性。
    
    Newey-West 调整通过计算自协方差并加权，调整标准误，
    提供更稳健的显著性判断。
    
    公式:
        t = ic_mean / sqrt(NW_var / n)
        p = 2 * (1 - norm.cdf(|t|))  # 双尾检验
    
    Lag 选择依据（Newey & West, 1994）:
        lag = int(4 * (T/100)^(2/9))
        其中 T = len(ic_series) = 有效 IC 计算天数（valid_days）
        
        注意区分：
        - valid_days: 实际参与 IC 计算的交易日数（每交易日股票数 >= min_stocks）
        - total_days: 原始数据的天数范围（可能包含数据缺失、停牌等）
        
        对于日频 IC 数据：
        - T=100 天 → lag ≈ 4
        - T=500 天 → lag ≈ 5（覆盖约一周的自相关）
        - T=1000 天 → lag ≈ 6
        
        设置上下限：min_lag=1, max_lag=10
    
    参数:
        ic_series: 日 IC 序列
        lag: 滞后阶数，默认 None（自动计算）
             若指定则使用固定值，否则使用 NW(1994) 自动选择准则
        
    返回:
        Tuple[float, float, int] - (t_stat, p_value, lag_used)
        - t_stat: Newey-West 调整后的 t 统计量
        - p_value: 双尾检验 p 值
        - lag_used: 实际使用的 lag 值（int）
    """
    n = len(ic_series)
    ic_mean = ic_series.mean()
    
    # 自动计算 lag（Newey-West 1994 准则）
    if lag is None:
        # NW(1994): lag = int(4 * (T/100)^(2/9))
        lag = int(4 * (n / 100) ** (2/9))
        # 设置上下限
        lag = max(1, min(lag, 10))
    
    # 计算自协方差（Newey-West 公式：k=0 为方差，k>0 为对称自协方差）
    # 公式: nw_var = σ² + Σ_{k=1}^{L} 2·w_k·γ_k
    # 其中 γ_k 为 k阶自协方差，w_k = 1 - k/(L+1) 为 Bartlett 权重
    nw_var = np.var(ic_series, ddof=1)  # k=0: 样本方差
    
    for k in range(1, lag + 1):  # k>0: 对称自协方差
        cov_k = np.cov(ic_series[:-k].values, ic_series[k:].values)[0, 1]
        weight = 1 - k / (lag + 1)
        nw_var += 2 * weight * cov_k  # 注意乘以 2（对称性：γ_k = γ_{-k}）
    
    if nw_var <= 0:
        nw_var = np.var(ic_series, ddof=1)
    
    # 调整后的标准误
    nw_se = np.sqrt(nw_var / n)
    
    # t 统计量
    if nw_se == 0:
        t_stat = 0.0
    else:
        t_stat = ic_mean / nw_se
    
    # p 值 (双尾)
    p_value = 2 * (1 - stats.norm.cdf(abs(t_stat)))
    
    return t_stat, p_value, lag


def _assess_statistical_significance(
    p_value: float,
    t_stat: float,
    nw_lag: int,
    p_threshold: float = 0.05,
    t_threshold: float = 1.96
) -> Dict:
    """
    评估统计显著性
    
    注意：输入的 t_stat 应为 Newey-West 调整后的 t 统计量，
    而非原始 OLS t 统计量。Newey-West 调整考虑了 IC 序列的自相关。
    
    参数:
        p_value: Newey-West 调整后的 p 值
        t_stat: Newey-West 调整后的 t 统计量（用于输出，不用于判断）
        nw_lag: Newey-West 使用的滞后阶数
        p_threshold: p 值阈值，默认 0.05
        t_threshold: t 统计量阈值（仅用于输出参考，不用于判断）
        
    返回:
        dict: {
            'p_value': float,
            'p_value_display': str,
            't_stat': float,
            'nw_lag': int,
            'nw_lag_method': str,
            'is_significant': bool,
            'conclusion': str
        }
    
    设计说明:
        p_value 由 t_stat 通过标准正态分布双尾检验公式直接计算，
        因此 |t| > 1.96 与 p < 0.05 完全等价，无需同时检查两个条件。
        仅使用 p_value 判断，更直观且符合学术惯例。
    """
    # 仅使用 p_value 判断（与 |t| > 1.96 完全等价，简化无冗余）
    is_significant = bool(p_value < p_threshold)
    
    # p_value 格式化
    p_value_str = _format_p_value(p_value)
    
    if is_significant:
        conclusion = f"统计显著（p={p_value_str}<0.05）"
    else:
        conclusion = f"统计不显著（p={p_value_str}>=0.05）"
    
    return {
        'p_value': p_value,  # 保留原始值
        'p_value_display': p_value_str,  # 格式化显示值
        't_stat': round(t_stat, 4),
        'nw_lag': nw_lag,
        'nw_lag_method': 'Newey-West (1994): lag = int(4*(T/100)^(2/9))',
        'is_significant': is_significant,
        'conclusion': conclusion
    }


def _assess_factor_direction(ic_mean: float) -> Dict:
    """
    评估因子方向（ic_mean符号）
    
    注意：方向判断仅描述 ic_mean 符号，不代表因子有效性。
    有效性判断请参考 economic_significance。
    
    参数:
        ic_mean: IC 均值
        
    返回:
        dict: {
            'ic_mean': float,
            'ic_mean_sign': 'negative' | 'positive' | 'zero',
            'direction_usage': str,  # 如何在分层回测中使用
            'conclusion': str
        }
    """
    if ic_mean < -1e-6:  # 避免浮点精度问题
        sign = 'negative'
        direction_usage = '反向因子：分层回测时做多低值组、做空高值组'
        conclusion = f"因子方向为反向（ic_mean={ic_mean:.4f}<0），分层回测做多低值组"
    elif ic_mean > 1e-6:
        sign = 'positive'
        direction_usage = '正向因子：分层回测时做多高值组、做空低值组'
        conclusion = f"因子方向为正向（ic_mean={ic_mean:.4f}>0），分层回测做多高值组"
    else:
        sign = 'zero'
        direction_usage = '方向不明：分层回测不建议使用'
        conclusion = f"因子方向不明（ic_mean={ic_mean:.4f}≈0），不建议用于分层回测"
    
    return {
        'ic_mean': round(ic_mean, 6),
        'ic_mean_sign': sign,
        'direction_usage': direction_usage,
        'conclusion': conclusion
    }


def _assess_economic_significance(
    abs_ic_mean: float,
    weak_threshold: float = 0.03,
    strong_threshold: float = 0.05
) -> Dict:
    """
    评估经济显著性
    
    参数:
        abs_ic_mean: IC 均值绝对值
        weak_threshold: 弱显著性阈值，默认 0.03
        strong_threshold: 强显著性阈值，默认 0.05
        
    返回:
        dict: {
            'abs_ic_mean': float,
            'threshold_used': {'weak': float, 'strong': float},
            'level': 'strong' | 'weak' | 'none',
            'is_economically_significant': bool,
            'conclusion': str
        }
    """
    if abs_ic_mean >= strong_threshold:
        level = 'strong'
        conclusion = f"经济显著强（|ic_mean|={abs_ic_mean:.4f}>={strong_threshold}）"
    elif abs_ic_mean >= weak_threshold:
        level = 'weak'
        conclusion = f"经济显著弱（|ic_mean|={abs_ic_mean:.4f}>={weak_threshold}）"
    else:
        level = 'none'
        conclusion = f"经济不显著（|ic_mean|={abs_ic_mean:.4f}<{weak_threshold}）"
    
    return {
        'abs_ic_mean': round(abs_ic_mean, 6),
        'threshold_used': {'weak': weak_threshold, 'strong': strong_threshold},
        'level': level,
        'is_economically_significant': bool(level != 'none'),
        'conclusion': conclusion
    }


def _assess_icir_stability(
    icir: float,
    usable_threshold: float = 0.5,
    good_threshold: float = 1.0,
    excellent_threshold: float = 2.0
) -> Dict:
    """
    评估 ICIR 稳定性
    
    ICIR 衡量 IC 的稳定性（|ic_mean|/ic_std），业界标准：
    - ICIR >= 0.5: 可用
    - ICIR >= 1.0: 较好
    - ICIR >= 2.0: 很好
    
    参数:
        icir: ICIR 值（已使用绝对值计算）
        usable_threshold: 可用阈值，默认 0.5
        good_threshold: 较好阈值，默认 1.0
        excellent_threshold: 很好阈值，默认 2.0
        
    返回:
        dict: {
            'icir': float,
            'threshold_used': {'usable': float, 'good': float, 'excellent': float},
            'level': 'excellent' | 'good' | 'usable' | 'none',
            'is_stable': bool,
            'conclusion': str
        }
    """
    if icir >= excellent_threshold:
        level = 'excellent'
        conclusion = f"IC稳定性很好（ICIR={icir:.2f}>={excellent_threshold})"
    elif icir >= good_threshold:
        level = 'good'
        conclusion = f"IC稳定性较好（ICIR={icir:.2f}>={good_threshold})"
    elif icir >= usable_threshold:
        level = 'usable'
        conclusion = f"IC稳定性可用（ICIR={icir:.2f}>={usable_threshold})"
    else:
        level = 'none'
        conclusion = f"IC稳定性不足（ICIR={icir:.2f}<{usable_threshold})"
    
    return {
        'icir': round(icir, 4),
        'threshold_used': {
            'usable': usable_threshold,
            'good': good_threshold,
            'excellent': excellent_threshold
        },
        'level': level,
        'is_stable': bool(level != 'none'),
        'conclusion': conclusion
    }


def _assess_ic_distribution_consistency(positive_ratio: float, ic_mean_sign: str) -> Dict:
    """
    评估 IC 分布一致性
    
    用于诊断 IC 分布特征，检测偏度异常。
    
    参数:
        positive_ratio: IC>0 的天数占比
        ic_mean_sign: ic_mean 的符号（negative/positive/zero）
        
    返回:
        dict: {
            'positive_ratio': float,
            'ic_mean_sign': str,
            'is_consistent': bool,
            'consistency_type': 'consistent' | 'balanced' | 'contradictory',
            'distribution_hint': str,
            'conclusion': str
        }
    """
    negative_ratio = 1 - positive_ratio
    
    if ic_mean_sign == 'zero':
        return {
            'positive_ratio': round(positive_ratio, 4),
            'ic_mean_sign': 'zero',
            'is_consistent': True,
            'consistency_type': 'balanced',
            'distribution_hint': f'IC分布均衡（正{positive_ratio:.1%}，负{negative_ratio:.1%}）',
            'conclusion': 'IC均值接近零，分布均衡'
        }
    
    # 一致性判断（先判断 balanced，避免边界重叠被 A/B 覆盖）
    # 条件顺序：balanced → consistent → contradictory
    if abs(positive_ratio - 0.5) <= 0.011:  # 浮点容差，覆盖 [49%, 51%]
        is_consistent = True
        consistency_type = 'balanced'
        distribution_hint = f'IC分布均衡（正{positive_ratio:.1%}，负{negative_ratio:.1%}）'
        conclusion = '均衡：IC正负各半，均值由极值决定'
    elif positive_ratio < 0.5 and ic_mean_sign == 'negative':  # 严格 <，0.5 已被 balanced 覆盖
        is_consistent = True
        consistency_type = 'consistent'
        distribution_hint = f'IC分布偏向负值（{negative_ratio:.1%}天数IC<0）'
        conclusion = '一致：正比例<50%对应负方向，IC分布正常'
    elif positive_ratio > 0.5 and ic_mean_sign == 'positive':  # 严格 >，0.5 已被 balanced 覆盖
        is_consistent = True
        consistency_type = 'consistent'
        distribution_hint = f'IC分布偏向正值（{positive_ratio:.1%}天数IC>0）'
        conclusion = '一致：正比例>50%对应正方向，IC分布正常'
    elif positive_ratio < 0.49 and ic_mean_sign == 'positive':
        is_consistent = False
        consistency_type = 'contradictory'
        distribution_hint = f'IC分布异常：均值正但{negative_ratio:.1%}天数IC<0（少数大幅正值拉高均值）'
        conclusion = '矛盾：均值正但多数天负，存在大幅正值偏度，需检查异常交易日'
    elif positive_ratio > 0.51 and ic_mean_sign == 'negative':
        is_consistent = False
        consistency_type = 'contradictory'
        distribution_hint = f'IC分布异常：均值负但{positive_ratio:.1%}天数IC>0（少数大幅负值拉低均值）'
        conclusion = '矛盾：均值负但多数天正，存在大幅负值偏度，需检查异常交易日'
    else:
        # 其他边界情况（如 0.49-0.51 区间但非 balanced）
        is_consistent = True
        consistency_type = 'consistent'
        distribution_hint = f'IC分布偏向{ic_mean_sign}方向'
        conclusion = f'一致：分布与方向{ic_mean_sign}吻合'
    
    return {
        'positive_ratio': round(positive_ratio, 4),
        'ic_mean_sign': ic_mean_sign,
        'is_consistent': is_consistent,
        'consistency_type': consistency_type,
        'distribution_hint': distribution_hint,
        'conclusion': conclusion
    }





def _format_p_value(p_value: float) -> str:
    """
    格式化 p 值输出，避免 0.0 显示问题
    
    规范（PROJECT.md）：
    - p_value >= 0.001: 显示为小数，如 "0.0349"
    - p_value < 0.001: 显示为科学计数法，如 "1.78e-09"
    
    设计原则：
    - 不使用固定阈值截断（如 < 1e-6），避免丢失精度
    - 极小值直接显示科学计数法，保留实际精度
    - 既能体现统计显著性的实际强度，又不会显示 0.0
    
    参数:
        p_value: p 值
        
    返回:
        格式化后的 p 值字符串
    """
    if p_value < 0.001:
        return f"{p_value:.2e}"  # 科学计数法，保留精度
    else:
        return f"{p_value:.4f}"  # 小数格式


if __name__ == "__main__":
    # 简单测试
    import numpy as np
    
    # 创建 logger（__main__ 测试场景）
    logger = get_logger(__name__)
    
    np.random.seed(42)
    dates = pd.date_range('2025-01-01', periods=20, freq='D')
    assets = [f'00000{i}.SZ' for i in range(1, 11)]
    
    factor_rows = []
    return_rows = []
    
    for date in dates:
        for asset in assets:
            # RSI 随机生成
            rsi = np.random.uniform(20, 80)
            # 未来收益与 RSI 负相关（模拟反向因子）
            forward_return = -0.001 * rsi + np.random.normal(0, 0.02)
            
            factor_rows.append({
                'date': date,
                'asset': asset,
                'rsi_6': rsi
            })
            return_rows.append({
                'date': date,
                'asset': asset,
                'forward_return': forward_return
            })
    
    factor_df = pd.DataFrame(factor_rows)
    return_df = pd.DataFrame(return_rows)
    
    result = calculate_ic_with_direction_verification(
        factor_df, return_df, factor_col='rsi_6', logger=logger
    )
    
    logger.info("=" * 60)
    logger.info("因子方向验证 IC 分析")
    logger.info("=" * 60)
    logger.info(f"IC 均值:     {result['ic_mean']:.4f}")
    logger.info(f"IC 标准差:   {result['ic_std']:.4f}")
    logger.info(f"ICIR:        {result['icir']:.2f}")


def calculate_ic_statistics(ic_series: pd.Series, logger=None) -> Dict:
    """
    从 IC 序列计算统计指标（不重新计算 IC）
    
    用于增量更新场景：已有 IC 值，只需重新计算统计指标
    
    参数:
        ic_series: IC 值序列（pandas Series）
        logger: 日志记录器（由调用方传入，默认使用模块 logger）
        
    输入约束（重要）:
        1. 索引必须按日期升序排列，确保 rolling 计算顺序正确
        2. 索引顺序决定 rolling_ic_mean 输出顺序
        3. 输入长度与输出长度一致（不做额外过滤）
        4. 索引应为日期字符串或 datetime 对象
        
    返回:
        dict: {
            'ic_mean': float,
            'ic_std': float,
            'icir': float,
            'p_value': float,
            'p_value_display': str,
            't_stat': float,
            'statistical_significance': dict,
            'factor_direction': dict,
            'economic_significance': dict,
            'icir_stability': dict,
            'ic_distribution_consistency': dict,
            'positive_ratio': float,
            'n_days': int,
            'rolling_ic_mean': list,  # 长度与输入 ic_series 一致
            'summary': str
        }
        
    注意:
        rolling_ic_mean 输出顺序与 ic_series 索引顺序一致，
        调用方对齐时应保证索引顺序匹配。
    """
    if logger is None:
        logger = get_logger(__name__)
    
    # 复用 _calculate_ic_statistics 函数
    ic_mean = ic_series.mean()
    ic_std = ic_series.std()
    
    # 调用内部函数计算详细统计（自动选择 lag）
    t_stat, p_value, nw_lag = _newey_west_t_stat(ic_series)
    
    # ICIR 使用绝对值（PROJECT.md 规范）
    icir = abs(ic_mean) / ic_std if ic_std > 0 else 0
    
    n = len(ic_series)
    positive_count = (ic_series > 0).sum()
    positive_ratio = positive_count / n
    
    # 五维度判断
    statistical_significance = _assess_statistical_significance(
        p_value, t_stat, nw_lag, p_threshold=0.05, t_threshold=1.96
    )
    
    factor_direction = _assess_factor_direction(ic_mean)
    
    economic_significance = _assess_economic_significance(
        abs(ic_mean), weak_threshold=0.03, strong_threshold=0.05
    )
    
    # 维度4: ICIR 稳定性
    icir_stability = _assess_icir_stability(icir)
    
    # 维度5: IC 分布一致性
    ic_distribution_consistency = _assess_ic_distribution_consistency(
        positive_ratio, factor_direction['ic_mean_sign']
    )
    
    # 生成摘要
    # p_value 格式化
    p_value_str = _format_p_value(p_value)
    
    # 滚动 IC 均值（PROJECT.md 规范）
    # window=20（约一个月交易日），min_periods=10（至少半窗口数据）
    rolling_ic_mean = ic_series.rolling(window=20, min_periods=10).mean()
    # 转换为列表，NaN 转为 None（JSON 序列化）
    rolling_ic_mean_list = [
        round(v, 6) if pd.notna(v) else None 
        for v in rolling_ic_mean.tolist()
    ]
    
    # summary 格式规范：positive_ratio 独立描述，不嵌入一致性判断文字
    summary = (
        f"IC均值={ic_mean:.4f}, "
        f"ICIR={icir:.2f}, "
        f"p值={p_value_str}, "
        f"方向={factor_direction['ic_mean_sign']}, "
        f"统计显著={statistical_significance['is_significant']}, "
        f"经济显著={economic_significance['level']}, "
        f"ICIR稳定={icir_stability['level']}, "
        f"正比例={positive_ratio:.1%}（IC>0天数占比）"
    )
    
    return {
        'ic_mean': ic_mean,
        'ic_std': ic_std,
        'icir': icir,
        'p_value': p_value,  # 保留原始值
        'p_value_display': p_value_str,  # 格式化显示值
        't_stat': round(t_stat, 4),
        'statistical_significance': statistical_significance,
        'factor_direction': factor_direction,
        'economic_significance': economic_significance,
        'icir_stability': icir_stability,
        'ic_distribution_consistency': ic_distribution_consistency,
        'positive_ratio': positive_ratio,
        'n_days': n,
        'rolling_ic_mean': rolling_ic_mean_list,  # 滚动IC均值序列
        'summary': summary
    }


# ============================================================
# 行业中性化函数（PROJECT.md 规范）
# ============================================================

def industry_neutral_rank(
    factor_df: pd.DataFrame,
    factor_col: str,
    industry_col: str = 'industry',
    date_col: str = 'date',
    min_industry_stocks: int = 5
) -> pd.DataFrame:
    """
    截面内按行业分别排名
    
    参数:
        factor_df: 包含 date, asset, factor_value, industry 的 DataFrame
        factor_col: 因子值列名
        industry_col: 行业分类列名
        date_col: 日期列名
        min_industry_stocks: 每个行业最少股票数，低于此值的行业跳过
        
    返回:
        factor_df 增加 'industry_rank' 列（行业内百分位排名）
        
    规范:
        PROJECT.md 行业中性化处理 - 行业内排名方式
    """
    # 检查行业列是否存在
    if industry_col not in factor_df.columns:
        raise ValueError(
            f"因子数据缺少行业分类列 '{industry_col}'\n"
            f"当前列: {factor_df.columns.tolist()}\n"
            f"请先补充行业数据后再使用行业中性化"
        )
    
    # 创建行业内排名列
    factor_df = factor_df.copy()
    factor_df['industry_rank'] = float('nan')
    
    # 按日期和行业分组排名
    for date, day_data in factor_df.groupby(date_col):
        for industry, ind_data in day_data.groupby(industry_col):
            if len(ind_data) < min_industry_stocks:
                # 股票数不足，跳过该行业
                continue
            
            # 计算行业内百分位排名
            rank_pct = ind_data[factor_col].rank(pct=True)
            factor_df.loc[ind_data.index, 'industry_rank'] = rank_pct
    
    return factor_df


def industry_neutral_residual(
    factor_df: pd.DataFrame,
    factor_col: str,
    industry_col: str = 'industry',
    date_col: str = 'date',
    asset_col: str = 'asset',
    min_industry_stocks: int = 5
) -> pd.DataFrame:
    """
    截面回归去除行业效应
    
    参数:
        factor_df: 包含 date, asset, factor_value, industry 的 DataFrame
        factor_col: 因子值列名
        industry_col: 行业分类列名
        date_col: 日期列名
        asset_col: 资产列名
        min_industry_stocks: 每个行业最少股票数
        
    返回:
        DataFrame 包含 date, asset, neutral_factor 列（回归残差）
        
    规范:
        PROJECT.md 行业中性化处理 - 回归残差方式
    """
    from sklearn.linear_model import LinearRegression
    
    # 检查行业列是否存在
    if industry_col not in factor_df.columns:
        raise ValueError(
            f"因子数据缺少行业分类列 '{industry_col}'\n"
            f"当前列: {factor_df.columns.tolist()}\n"
            f"请先补充行业数据后再使用行业中性化"
        )
    
    results = []
    
    for date, day_data in factor_df.groupby(date_col):
        # 过滤股票数不足的行业
        valid_industries = day_data.groupby(industry_col).filter(
            lambda x: len(x) >= min_industry_stocks
        )
        
        if len(valid_industries) < min_industry_stocks:
            continue
        
        # 构建行业哑变量
        industry_dummies = pd.get_dummies(valid_industries[industry_col])
        
        # 回归
        model = LinearRegression()
        model.fit(industry_dummies, valid_industries[factor_col])
        
        # 残差即为中性化因子
        residual = valid_industries[factor_col] - model.predict(industry_dummies)
        
        # zip 返回二元组，用两个变量解包（idx 通过 enumerate 获取）
        for idx, (asset, res) in enumerate(zip(valid_industries[asset_col].values, residual)):
            results.append({
                date_col: date,
                asset_col: asset,
                'neutral_factor': round(res, 6)
            })
    
    return pd.DataFrame(results)