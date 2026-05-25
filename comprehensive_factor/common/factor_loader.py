"""
因子数据加载模块

功能:
1. 从统一数据源 factor_ic_data.json.gz 加载因子原始值
2. 从 factor_ic/result/ 加载 IC 统计结果
3. 从 factor_ic/result/ 加载 IC 每日序列（用于滚动ICIR）
4. 合并多个因子数据到统一 DataFrame

更新历史（2026-05-27）：
- v2.7: 从统一数据源 factor_ic_data.json.gz 读取因子数据
- 移除 DEFAULT_CACHE_DIR（改为 DEFAULT_DATA_SOURCE）

设计参考:
- factor_ic/common/data_loader.py
- backtest/common/data_loader.py

作者: 云瑶
创建日期: 2026-05-24
"""

import gzip
import json
import logging
import pandas as pd
import numpy as np
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Union


# 统一数据源路径（遵循 PROJECT.md 跨模块数据路径规范）
DEFAULT_DATA_SOURCE = Path(__file__).parent.parent.parent / 'data_fetchers' / 'result' / 'factor_ic_data.json.gz'
DEFAULT_IC_RESULT_DIR = Path(__file__).parent.parent.parent / 'factor_ic' / 'result'


def load_factor_values(
    factor_cols: List[str],
    data_source: Optional[Union[str, Path]] = None,
    logger: Optional[logging.Logger] = None
) -> pd.DataFrame:
    """从统一数据源加载因子原始值
    
    Args:
        factor_cols: 因子列名列表（如 ['rsi_6', 'volume_ratio_5']）
        data_source: 数据源文件路径（可选，默认使用 DEFAULT_DATA_SOURCE）
        logger: 日志对象
    
    Returns:
        包含 date, asset, 因子列的 DataFrame
    
    更新历史（2026-05-27）：
        - v2.7: 从统一数据源 factor_ic_data.json.gz 读取
        - 移除 cache_dir 参数（改为 data_source）
    
    Note:
        - 校验 date、asset 列的数据类型（date 为 str，asset 为 str）
        - 类型不一致可能导致后续计算异常（如 groupby 失败）
    """
    if logger is None:
        from comprehensive_factor.common.logger_config import get_logger
        logger = get_logger(__name__)
    
    if data_source is None:
        data_source = DEFAULT_DATA_SOURCE
    
    data_source = Path(data_source)
    
    # 加载统一数据源
    logger.info("加载统一数据源: %s", data_source)
    
    if not data_source.exists():
        raise FileNotFoundError(
            f"统一数据源文件不存在: {data_source}\n"
            f"请先运行 data_fetchers/factor_generator.py 生成数据"
        )
    
    with gzip.open(data_source, 'rt', encoding='utf-8') as f:
        data = json.load(f)
    
    if 'data' not in data:
        raise KeyError(f"数据源 JSON 结构缺失 'data' 字段: {data_source}")
    
    full_df = pd.DataFrame(data['data'])
    
    # 校验必需列存在
    required_cols = ['date', 'asset'] + factor_cols
    for col in required_cols:
        if col not in full_df.columns:
            available_cols = [c for c in full_df.columns if c not in ['date', 'asset']]
            raise ValueError(
                f"数据源中缺少 '{col}' 列\n"
                f"可用因子列: {available_cols}"
            )
    
    # 校验 date、asset 列的数据类型
    if len(full_df) > 0:
        first_date = full_df['date'].iloc[0]
        first_asset = full_df['asset'].iloc[0]
        
        if not isinstance(first_date, str):
            raise TypeError(
                f"date 列数据类型应为 str，实际为 {type(first_date).__name__}\n"
                f"首行 date 值: {first_date}\n"
                "可能原因：\n"
                "  1. JSON 文件中 date 字段为数字而非字符串\n"
                "  2. 数据生成脚本类型转换异常\n"
                "建议：检查 factor_ic_data.json.gz 生成逻辑"
            )
        
        if not isinstance(first_asset, str):
            raise TypeError(
                f"asset 列数据类型应为 str，实际为 {type(first_asset).__name__}\n"
                f"首行 asset 值: {first_asset}\n"
                "可能原因：\n"
                "  1. JSON 文件中 asset 字段为数字而非字符串\n"
                "  2. 数据生成脚本类型转换异常\n"
                "建议：检查 factor_ic_data.json.gz 生成逻辑"
            )
    
    logger.info("因子数据: %d 条记录，类型校验通过", len(full_df))
    
    return full_df[['date', 'asset'] + factor_cols].copy()


def load_ic_results(
    factor_names: List[str],
    ic_result_dir: Optional[Path] = None,
    return_period: str = '1d',
    logger: Optional[logging.Logger] = None
) -> Tuple[Dict[str, Dict], List[str]]:
    """从 factor_ic/result/ 加载 IC 统计结果
    
    Args:
        factor_names: 因子名称列表（如 ['rsi', 'volume_ratio']）
        ic_result_dir: IC结果目录路径
        return_period: 收益周期（如 '1d'）
        logger: 日志对象
    
    Returns:
        Tuple[ic_results, missing_factors]
        - ic_results: Dict[因子名, IC统计结果]
          {
              'rsi': {'ic_mean': -0.032, 'icir': -0.45, 'ic_std': 0.07, ...},
              'volume_ratio': {'ic_mean': -0.058, 'icir': -1.97, ...}
          }
        - missing_factors: 缺失因子列表（调用方可据此判断）
    
    Note:
        - 返回缺失因子列表，避免调用方不知道哪些因子缺失
        - ic_metrics/summary 字段回退时验证必需字段（ic_mean/icir）
    """
    if logger is None:
        from comprehensive_factor.common.logger_config import get_logger
        logger = get_logger(__name__)
    
    if ic_result_dir is None:
        ic_result_dir = DEFAULT_IC_RESULT_DIR
    
    ic_result_dir = Path(ic_result_dir)
    
    ic_results = {}
    missing_factors = []  # 修复：记录缺失因子列表
    
    # 必需字段：用于静态权重计算
    REQUIRED_IC_FIELDS = ['ic_mean', 'icir']
    
    for factor_name in factor_names:
        # IC结果文件命名: ic_<因子名>_<收益周期>_analysis_result.json
        ic_file = ic_result_dir / f'ic_{factor_name}_{return_period}_analysis_result.json'
        
        if not ic_file.exists():
            logger.warning("IC结果文件不存在: %s，跳过该因子", ic_file)
            missing_factors.append(factor_name)
            continue
        
        logger.info("加载 IC 结果: %s", ic_file)
        
        with open(ic_file, 'r', encoding='utf-8') as f:
            ic_data = json.load(f)
        
        # 提取 ic_metrics 字段（IC统计结果）
        # 修复：字段回退时验证必需字段
        extracted_data = None
        field_source = None
        
        if 'ic_metrics' in ic_data:
            extracted_data = ic_data['ic_metrics']
            field_source = 'ic_metrics'
        elif 'summary' in ic_data:
            # summary 字段结构可能与 ic_metrics 不同
            # 验证必需字段存在性
            extracted_data = ic_data['summary']
            field_source = 'summary'
            
            # 检查必需字段是否存在
            missing_fields = [f for f in REQUIRED_IC_FIELDS if f not in extracted_data]
            if missing_fields:
                logger.warning(
                    "IC结果文件 '%s' 字段缺失必需字段: %s，文件: %s",
                    field_source, missing_fields, ic_file
                )
        
        if extracted_data is None:
            logger.warning(
                "IC结果文件缺失 'ic_metrics' 和 'summary' 字段: %s",
                ic_file
            )
            missing_factors.append(factor_name)
            continue
        
        # 修复：验证必需字段（ic_mean, icir）存在性
        missing_required = [f for f in REQUIRED_IC_FIELDS if f not in extracted_data]
        if missing_required:
            logger.warning(
                "因子 %s IC 结果缺失必需字段: %s（来源: %s），文件: %s",
                factor_name, missing_required, field_source, ic_file
            )
            # 不跳过该因子，但记录警告（下游使用时会回退等权）
        
        ic_results[factor_name] = extracted_data
    
    # 修复：返回缺失因子列表信息
    if missing_factors:
        logger.warning(
            "部分因子 IC 结果缺失: %s，共 %d 个",
            missing_factors, len(missing_factors)
        )
    
    if not ic_results:
        raise ValueError(
            f"未找到任何 IC 结果文件，路径: {ic_result_dir}\n"
            f"缺失因子: {missing_factors}"
        )
    
    logger.info("加载 IC 结果: %d 个因子（缺失 %d 个）", len(ic_results), len(missing_factors))
    
    return ic_results, missing_factors


def load_ic_daily(
    factor_names: List[str],
    ic_result_dir: Optional[Path] = None,
    return_period: str = '1d',
    logger: Optional[logging.Logger] = None
) -> Dict[str, pd.DataFrame]:
    """从 factor_ic/result/ 加载 IC 每日序列
    
    从现有的 IC 分析结果文件中提取 ic_values 和 dates 字段，
    用于滚动ICIR加权计算。
    
    Args:
        factor_names: 因子名称列表
        ic_result_dir: IC结果目录路径
        return_period: 收益周期
        logger: 日志对象
    
    Returns:
        Dict[因子名, IC每日DataFrame]
        {
            'rsi': DataFrame(columns=['date', 'ic']),
            'volume_ratio': DataFrame(...)
        }
    
    Note:
        - ic_sign 列已移除（死代码，未在后续计算中使用）
        - 日期与IC值数量不一致时抛出错误（不再静默截断）
    """
    if logger is None:
        from comprehensive_factor.common.logger_config import get_logger
        logger = get_logger(__name__)
    
    if ic_result_dir is None:
        ic_result_dir = DEFAULT_IC_RESULT_DIR
    
    ic_result_dir = Path(ic_result_dir)
    
    ic_daily_data = {}
    missing_factors = []  # 修复：记录缺失因子列表
    
    for factor_name in factor_names:
        # IC结果文件命名: ic_<因子名>_<收益周期>_analysis_result.json
        ic_file = ic_result_dir / f'ic_{factor_name}_{return_period}_analysis_result.json'
        
        if not ic_file.exists():
            logger.warning("IC结果文件不存在: %s，跳过该因子", ic_file)
            missing_factors.append(factor_name)
            continue
        
        logger.info("加载 IC 每日序列: %s", ic_file)
        
        with open(ic_file, 'r', encoding='utf-8') as f:
            ic_data = json.load(f)
        
        # 提取 ic_values 和 dates/valid_dates 字段
        if 'ic_values' not in ic_data:
            logger.warning("IC结果文件缺失 'ic_values' 字段: %s", ic_file)
            missing_factors.append(factor_name)
            continue
        
        # 使用 valid_dates（有效日期）或 dates
        dates = ic_data.get('valid_dates', ic_data.get('dates', []))
        ic_values = ic_data.get('ic_values', [])
        
        # 修复：日期与IC值数量不一致时抛出错误（不再静默截断）
        # 原代码截断可能导致错位数据对齐到错误日期，产生错误的滚动ICIR
        if len(dates) != len(ic_values):
            raise ValueError(
                f"日期与IC值数量不一致: dates={len(dates)}, ic_values={len(ic_values)}\n"
                f"文件: {ic_file}\n"
                "可能原因：\n"
                "  1. IC 计算过程中部分日期缺失数据\n"
                "  2. JSON 文件写入异常\n"
                "  3. valid_dates 与 ic_values 字段对齐问题\n"
                "建议：重新运行 IC 分析脚本生成完整的 IC 结果文件"
            )
        
        # 修复：防御性处理 ic_values 中可能的 None 值
        # 原代码 v > 0 时 v 可能是 None，导致 TypeError
        # 同时移除 ic_sign 列（死代码，未在后续计算中使用）
        ic_values_cleaned = [v if v is not None else np.nan for v in ic_values]
        
        # 构建 DataFrame（移除 ic_sign 列）
        daily_df = pd.DataFrame({
            'date': dates,
            'ic': ic_values_cleaned
        })
        
        ic_daily_data[factor_name] = daily_df
    
    # 修复：返回缺失因子列表信息
    if missing_factors:
        logger.warning(
            "部分因子 IC 每日数据缺失: %s，共 %d 个",
            missing_factors, len(missing_factors)
        )
    
    if not ic_daily_data:
        raise ValueError(
            f"未找到任何 IC 每日数据，路径: {ic_result_dir}\n"
            f"缺失因子: {missing_factors}"
        )
    
    logger.info("加载 IC 每日序列: %d 个因子（缺失 %d 个）", len(ic_daily_data), len(missing_factors))
    
    return ic_daily_data


def standardize_factors(
    factor_df: pd.DataFrame,
    factor_cols: List[str],
    logger: Optional[logging.Logger] = None
) -> pd.DataFrame:
    """截面标准化因子值
    
    每日对每个因子做截面标准化（减均值除标准差）。
    
    Args:
        factor_df: 因子 DataFrame（包含 date, asset, 因子列）
        factor_cols: 需标准化的因子列名
        logger: 日志对象
    
    Returns:
        标准化后的 DataFrame（新增标准化因子列，命名: <因子列>_std）
    
    接口约定（MODULE.md 规范）：
        - 输入列名：原始因子列名（如 'rsi_6', 'volume_ratio_5'）
        - 输出列名：新增 '_std' 后缀（如 'rsi_6_std', 'volume_ratio_5_std'）
        - WeightEngine.calculate() 接收原始列名，内部自动转换为 _std 列
    
    NaN 处理规范：
        1. 原始 NaN 保持 NaN（不参与标准化计算）
        2. 单只股票有有效值时，标准化结果为 NaN（样本标准差无法计算）
        3. 有效值数量 <=1 时记录警告日志
    """
    if logger is None:
        from comprehensive_factor.common.logger_config import get_logger
        logger = get_logger(__name__)
    
    factor_df = factor_df.copy()
    
    for col in factor_cols:
        std_col = f'{col}_std'
        
        # 修复：使用显式计算替代 lambda，避免条件判断与 NaN 处理冲突
        # 计算每日截面均值和标准差
        daily_stats = factor_df.groupby('date')[col].agg(['mean', 'std', 'count'])
        
        # 检查有效值数量不足的情况（count <= 1 的日期）
        low_count_mask = daily_stats['count'] <= 1
        # type: ignore[reportArgumentType] — pandas Index 是可迭代对象，LSP 类型推断不准确
        low_count_dates = list(daily_stats.index[low_count_mask])  # type: ignore
        if low_count_dates:
            logger.warning(
                "因子 %s 在 %d 个日期有效值数量 <=1，标准化结果将为 NaN: %s",
                col, len(low_count_dates), low_count_dates[:5]  # 只显示前5个
            )
        
        # 使用 transform 计算标准化值（保持索引对齐）
        # 注意：x.std(ddof=1) 单样本时返回 NaN，是正确行为
        factor_df[std_col] = factor_df.groupby('date')[col].transform(
            lambda x: (x - x.mean()) / x.std() if x.std() > 0 else np.nan
        )
        
        # NaN 处理：原因子值为 NaN 时标准化后仍为 NaN
        # 使用 fillna 保持原本 NaN 的位置，而非 .loc 后置还原
        factor_df.loc[factor_df[col].isna(), std_col] = np.nan
    
    logger.info("因子标准化完成: %d 个因子", len(factor_cols))
    
    return factor_df


def calc_factor_correlation(
    factor_df: pd.DataFrame,
    factor_cols: List[str],
    logger: Optional[logging.Logger] = None
) -> pd.DataFrame:
    """计算因子相关性矩阵
    
    Args:
        factor_df: 因子 DataFrame（必须包含标准化因子列 *_std）
        factor_cols: 因子列名（原始列名，会自动转换为 _std 列）
        logger: 日志对象
    
    Returns:
        相关性矩阵 DataFrame
    
    Precondition:
        factor_df 必须包含 *_std 列（由 standardize_factors 生成）
        如果 _std 列不存在，抛出 ValueError
    
    接口约定（MODULE.md 规范）：
        - 输入列名：原始因子列名（与 WeightEngine.calculate() 一致）
        - 内部转换：std_cols = [f'{col}_std' for col in factor_cols]
        - 调用方必须在调用此函数前先调用 standardize_factors()
    """
    if logger is None:
        from comprehensive_factor.common.logger_config import get_logger
        logger = get_logger(__name__)
    
    # 使用标准化后的因子计算相关性（更稳定）
    std_cols = [f'{col}_std' for col in factor_cols]
    
    # 修复：前置校验 _std 列存在性
    for std_col in std_cols:
        if std_col not in factor_df.columns:
            raise ValueError(
                f"factor_df 缺少标准化因子列 '{std_col}'，当前列: {list(factor_df.columns)}\n"
                "可能原因：\n"
                "  1. 调用方未先调用 standardize_factors()\n"
                "  2. standardize_factors 参数 factor_cols 与 calc_factor_correlation 不一致\n"
                "  3. factor_df 数据被意外修改或过滤\n"
                "调用顺序：load_factor_values → standardize_factors → calc_factor_correlation"
            )
    
    corr_matrix = factor_df[std_cols].corr()
    
    # 还原原始列名作为索引
    corr_matrix.index = factor_cols
    corr_matrix.columns = factor_cols
    
    logger.info("因子相关性矩阵计算完成")
    
    return corr_matrix