"""
因子筛选模块

功能:
1. 加载所有因子 IC 结果 + 回测结果
2. 判断无效因子（阈值标准）
3. 识别高相关组并筛选（保留 ICIR 最高的）
4. 输出筛选结果供综合因子计算使用

阈值标准（业界惯例）:
- |ic_mean| < 0.03 → 无效（预测能力弱）
- p_value > 0.05 → 无效（统计不显著）
- |icir| < 0.2 → 无效（稳定性差）
- |monotonicity_corr| < 0.5 → 无效（分层不单调）
- long_short_return_annual < 5% → 无效（经济意义弱）

高相关组筛选:
- |corr| > 0.7 → 高相关组
- 组内保留 |ICIR| 最高的因子

作者: 云瑶
创建日期: 2026-05-24
"""

import json
import logging
import pandas as pd
import numpy as np
from pathlib import Path
from typing import Dict, List, Tuple, Optional

from comprehensive_factor.common.logger_config import get_logger


# 默认路径
DEFAULT_IC_RESULT_DIR = Path(__file__).parent.parent.parent / 'factor_ic' / 'result'
DEFAULT_BACKTEST_RESULT_DIR = Path(__file__).parent.parent.parent / 'backtest' / 'result'


# 默认阈值（业界惯例）
DEFAULT_THRESHOLDS = {
    'ic_mean_abs_min': 0.03,       # |IC均值| 最小值（经济显著性）
    'p_value_max': 0.05,           # p-value 最大值（统计显著性）
    'icir_abs_min': 0.15,          # |ICIR| 最小值（稳定性，0.15≈IC均值/IC标准差>0.03/0.2）
    'monotonicity_corr_abs_min': 0.4,  # |单调性相关性| 最小值（0.4为一般单调）
    'long_short_return_min': 0.03,     # 多空年化收益最小值（3%，扣除成本后仍正收益）
    'high_corr_threshold': 0.7     # 高相关性阈值
}


# 因子名到数据列名的映射（v1.1 新增）
# 说明：factor_list 是因子逻辑名（如 'rsi'），factor_cols 是缓存数据列名（如 'rsi_6'）
# 后续应从配置文件读取，此处为硬编码临时方案
FACTOR_NAME_TO_COL_MAP = {
    'rsi': 'rsi_6',
    'volume_ratio': 'volume_ratio_5',
    'kdj_j': 'kdj_j_9',
    'bollinger_pb': 'bollinger_pb_20',
    'turnover_surge': 'turnover_surge_5',
    'main_inflow_ratio': 'main_inflow_ratio_1d'
}


def load_all_factor_results(
    ic_result_dir: Optional[Path] = None,
    backtest_result_dir: Optional[Path] = None,
    return_period: str = '1d',
    logger: Optional[logging.Logger] = None
) -> Dict[str, Dict]:
    """加载所有因子的 IC 结果 + 回测结果
    
    Args:
        ic_result_dir: IC 结果目录
        backtest_result_dir: 回测结果目录
        return_period: 收益周期
        logger: 日志对象
    
    Returns:
        Dict[因子名, 因子数据]
        {
            'rsi': {
                'ic_metrics': {'ic_mean': -0.037, 'icir': 0.25, ...},
                'backtest': {'monotonicity': {'correlation': -0.46}, 'long_short': {...}}
            },
            'volume_ratio': {...}
        }
    
    Note:
        - 因子名解析使用正则提取，而非多次 replace（更可靠）
        - 文件名格式：ic_<因子名>_<收益周期>_analysis_result.json
    """
    if logger is None:
        logger = get_logger(__name__)
    
    if ic_result_dir is None:
        ic_result_dir = DEFAULT_IC_RESULT_DIR
    if backtest_result_dir is None:
        backtest_result_dir = DEFAULT_BACKTEST_RESULT_DIR
    
    ic_result_dir = Path(ic_result_dir)
    backtest_result_dir = Path(backtest_result_dir)
    
    all_factors = {}
    
    # 加载 IC 结果
    logger.info("加载 IC 结果: %s", ic_result_dir)
    import re  # 修复：使用正则提取因子名
    
    # 正则模式：ic_<因子名>_<收益周期>_analysis_result.json
    # 例：ic_rsi_1d_analysis_result.json → rsi
    # 例：ic_volume_ratio_1d_analysis_result.json → volume_ratio
    ic_pattern = re.compile(rf'^ic_(.+?)_{return_period}_analysis_result$')
    
    for ic_file in ic_result_dir.glob(f'ic_*_{return_period}_analysis_result.json'):
        # 修复：使用正则提取因子名，而非多次 replace
        match = ic_pattern.match(ic_file.stem)
        if match:
            factor_name = match.group(1)
        else:
            # 回退：使用原逻辑（兼容非标准文件名）
            factor_name = ic_file.stem.replace(f'ic_', '').replace(f'_analysis_result', '').replace(f'_{return_period}', '')
            logger.warning("IC文件名格式非标准: %s，因子名: %s", ic_file.name, factor_name)
        
        with open(ic_file, 'r', encoding='utf-8') as f:
            ic_data = json.load(f)
        
        all_factors[factor_name] = {
            'ic_metrics': ic_data.get('ic_metrics', {}),
            'ic_file': str(ic_file)
        }
        logger.debug("加载 IC 结果: %s", factor_name)
    
    # 加载回测结果
    logger.info("加载回测结果: %s", backtest_result_dir)
    # 正则模式：<因子名>_layered_backtest.json
    backtest_pattern = re.compile(r'^(.+?)_layered_backtest$')
    
    for backtest_file in backtest_result_dir.glob('*_layered_backtest.json'):
        # 修复：使用正则提取因子名
        match = backtest_pattern.match(backtest_file.stem)
        if match:
            factor_name = match.group(1)
        else:
            # 回退
            factor_name = backtest_file.stem.replace('_layered_backtest', '')
            logger.warning("回测文件名格式非标准: %s", backtest_file.name)
        
        with open(backtest_file, 'r', encoding='utf-8') as f:
            backtest_data = json.load(f)
        
        if factor_name in all_factors:
            all_factors[factor_name]['backtest'] = backtest_data
        else:
            all_factors[factor_name] = {
                'backtest': backtest_data,
                'ic_metrics': {}
            }
        logger.debug("加载回测结果: %s", factor_name)
    
    logger.info("加载因子数据: %d 个因子", len(all_factors))
    
    return all_factors


def validate_factor(
    factor_name: str,
    factor_data: Dict,
    thresholds: Optional[Dict] = None,
    logger: Optional[logging.Logger] = None
) -> Tuple[bool, List[str]]:
    """判断因子是否有效
    
    Args:
        factor_name: 因子名称
        factor_data: 因子数据（ic_metrics + backtest）
        thresholds: 阈值配置
    
    Returns:
        (is_valid, reasons)
        - is_valid: True/False
        - reasons: 无效原因列表
    
    Note:
        - 关键指标缺失时标记为无效（不再静默通过）
        - 缺失指标包括：ic_mean、icir（静态权重计算必需）
        - 数据缺失的因子应被排除，而非误判为有效
    """
    if thresholds is None:
        thresholds = DEFAULT_THRESHOLDS
    
    if logger is None:
        logger = get_logger(__name__)
    
    reasons = []
    
    # 1. IC 均值检查
    ic_metrics = factor_data.get('ic_metrics', {})
    ic_mean = ic_metrics.get('ic_mean', None)
    
    # 修复：关键指标缺失时标记为无效
    if ic_mean is None:
        reasons.append("ic_mean 缺失（数据不完整）")
    elif abs(ic_mean) < thresholds['ic_mean_abs_min']:
        reasons.append(f"|ic_mean|={abs(ic_mean):.3f}<{thresholds['ic_mean_abs_min']}")
    
    # 2. p-value 检查（可选，缺失时跳过）
    p_value = ic_metrics.get('p_value', None)
    if p_value is not None and p_value > thresholds['p_value_max']:
        reasons.append(f"p_value={p_value:.3f}>{thresholds['p_value_max']}")
    
    # 3. ICIR 检查
    icir = ic_metrics.get('icir', None)
    
    # 修复：关键指标缺失时标记为无效
    if icir is None:
        reasons.append("icir 缺失（数据不完整）")
    elif abs(icir) < thresholds['icir_abs_min']:
        reasons.append(f"|icir|={abs(icir):.3f}<{thresholds['icir_abs_min']}")
    
    # 4. 单调性检查（可选）
    backtest = factor_data.get('backtest', {})
    monotonicity = backtest.get('monotonicity', {})
    mono_corr = monotonicity.get('correlation', None)
    if mono_corr is not None and abs(mono_corr) < thresholds['monotonicity_corr_abs_min']:
        reasons.append(f"|monotonicity_corr|={abs(mono_corr):.2f}<{thresholds['monotonicity_corr_abs_min']}")
    
    # 5. 多空收益检查（可选）
    long_short = backtest.get('long_short', {})
    ls_return = long_short.get('long_short_return_annual', None)
    if ls_return is not None and ls_return < thresholds['long_short_return_min']:
        reasons.append(f"long_short_return={ls_return*100:.1f}%<{thresholds['long_short_return_min']*100:.0f}%")
    
    is_valid = len(reasons) == 0
    
    return is_valid, reasons


def filter_invalid_factors(
    all_factors: Dict[str, Dict],
    thresholds: Optional[Dict] = None,
    logger: Optional[logging.Logger] = None
) -> Dict[str, Dict]:
    """筛选无效因子
    
    Args:
        all_factors: 所有因子数据
        thresholds: 阈值配置
        logger: 日志对象
    
    Returns:
        {'valid': {...}, 'invalid': {factor_name: reasons}}
    """
    if logger is None:
        logger = get_logger(__name__)
    
    if thresholds is None:
        thresholds = DEFAULT_THRESHOLDS
    
    valid_factors = {}
    invalid_factors = {}
    
    for factor_name, factor_data in all_factors.items():
        is_valid, reasons = validate_factor(factor_name, factor_data, thresholds)
        
        if is_valid:
            valid_factors[factor_name] = factor_data
            logger.debug("有效因子: %s", factor_name)
        else:
            invalid_factors[factor_name] = reasons
            logger.warning("无效因子: %s, 原因: %s", factor_name, '; '.join(reasons))
    
    logger.info("筛选结果: 有效 %d, 无效 %d", len(valid_factors), len(invalid_factors))
    
    return {'valid': valid_factors, 'invalid': invalid_factors}


def identify_high_corr_groups(
    valid_factors: Dict[str, Dict],
    corr_matrix: pd.DataFrame,
    threshold: Optional[float] = None,
    logger: Optional[logging.Logger] = None
) -> List[List[str]]:
    """识别高相关因子组
    
    使用 Union-Find（并查集）算法识别高相关因子组。
    正确处理跨组合并（A-B, B-C, C-D 应合并为一个大组）。
    
    Args:
        valid_factors: 有效因子数据
        corr_matrix: 相关性矩阵
        threshold: 高相关性阈值
        logger: 日志对象
    
    Returns:
        高相关因子组列表
        [['rsi', 'bollinger_pb', 'kdj_j'], ['volume_ratio', 'turnover_surge']]
    
    Algorithm:
        使用 Union-Find 算法：
        1. 初始化每个因子为独立集合
        2. 遍历高相关pair，union 两个因子
        3. 最终按 root 分组输出
    
    Note:
        - 原算法遍历pair只合并到第一个找到的组，会漏掉跨组合并
        - Union-Find 保证所有高相关因子合并到同一连通分量
    """
    if logger is None:
        logger = get_logger(__name__)
    
    if threshold is None:
        threshold = DEFAULT_THRESHOLDS['high_corr_threshold']
    
    factor_names = list(valid_factors.keys())
    
    if len(factor_names) == 0:
        return []
    
    # Union-Find 数据结构
    parent = {name: name for name in factor_names}  # 每个因子初始指向自己
    
    def find(x: str) -> str:
        """查找根节点（带路径压缩）"""
        if parent[x] != x:
            parent[x] = find(parent[x])  # 路径压缩
        return parent[x]
    
    def union(x: str, y: str) -> None:
        """合并两个集合"""
        root_x = find(x)
        root_y = find(y)
        if root_x != root_y:
            parent[root_x] = root_y  # 合并
    
    # 构建相关性图，union 高相关因子
    high_corr_pairs = []
    for i, name_i in enumerate(factor_names):
        for j, name_j in enumerate(factor_names):
            if i < j and name_i in corr_matrix.index and name_j in corr_matrix.columns:
                corr_val = abs(corr_matrix.loc[name_i, name_j])
                if not pd.isna(corr_val) and corr_val > threshold:
                    high_corr_pairs.append((name_i, name_j, corr_val))
                    union(name_i, name_j)  # 合并高相关因子
                    logger.debug("高相关因子: %s vs %s, corr=%.2f", name_i, name_j, corr_val)
    
    # 按 root 分组
    groups_dict: Dict[str, List[str]] = {}
    for name in factor_names:
        root = find(name)
        if root not in groups_dict:
            groups_dict[root] = []
        groups_dict[root].append(name)
    
    # 只返回有多个因子的组（高相关组）
    groups = [group for group in groups_dict.values() if len(group) > 1]
    
    logger.info("高相关因子组: %d 组（共 %d 对高相关）", len(groups), len(high_corr_pairs))
    
    return groups


def select_best_from_groups(
    high_corr_groups: List[List[str]],
    valid_factors: Dict[str, Dict],
    logger: Optional[logging.Logger] = None
) -> Tuple[List[str], Dict[str, str]]:
    """从高相关组中选择最优因子
    
    保留规则：组内保留 |ICIR| 最高的因子
    
    Args:
        high_corr_groups: 高相关因子组
        valid_factors: 有效因子数据
        logger: 日志对象
    
    Returns:
        (selected_factors, dropped_factors_with_reason)
    
    Note:
        - icir 缺失时标记为无效（不再默认为 0）
        - 如果组内所有因子 icir 都缺失，保留第一个因子（无法比较）
    """
    if logger is None:
        logger = get_logger(__name__)
    
    selected_factors = list(valid_factors.keys())  # 初始为所有有效因子
    dropped_factors = {}
    
    for group in high_corr_groups:
        # 计算组内每个因子的 |ICIR|
        icir_values = {}
        missing_icir_factors = []  # 修复：记录 icir 缺失的因子
        
        for factor_name in group:
            ic_metrics = valid_factors.get(factor_name, {}).get('ic_metrics', {})
            icir = ic_metrics.get('icir', None)  # 修复：不默认为 0
            
            # 修复：icir 缺失时标记，而非默认为 0
            if icir is None:
                missing_icir_factors.append(factor_name)
                icir_values[factor_name] = None  # 明确标记缺失
            else:
                icir_values[factor_name] = abs(icir)
        
        # 修复：如果组内所有因子 icir 都缺失，保留第一个因子（无法比较）
        valid_icir_values = {k: v for k, v in icir_values.items() if v is not None}
        
        if not valid_icir_values:
            # 所有因子 icir 缺失，保留第一个
            best_factor = group[0]
            logger.warning(
                "高相关组 %s 所有因子 icir 缺失，无法比较，保留第一个: %s",
                group, best_factor
            )
            # 丢弃其他因子
            for factor_name in group:
                if factor_name != best_factor and factor_name in selected_factors:
                    selected_factors.remove(factor_name)
                    dropped_factors[factor_name] = f"与{best_factor}高相关，icir 缺失无法比较"
        else:
            # 找出 ICIR 最高的因子（只比较有 icir 的因子）
            best_factor = max(valid_icir_values.keys(), key=lambda k: valid_icir_values[k])
            
            # 丢弃其他因子（包括 icir 缺失的因子）
            for factor_name in group:
                if factor_name != best_factor:
                    if factor_name in selected_factors:
                        selected_factors.remove(factor_name)
                        
                        # 修复：区分 icir 缺失和 ICIR 较低
                        if factor_name in missing_icir_factors:
                            dropped_factors[factor_name] = (
                                f"与{best_factor}高相关，icir 缺失（{best_factor} |ICIR|={valid_icir_values[best_factor]:.2f}）"
                            )
                        else:
                            dropped_factors[factor_name] = (
                                f"与{best_factor}高相关，|ICIR|={icir_values[factor_name]:.2f}<{valid_icir_values[best_factor]:.2f}"
                            )
                        
                        logger.info("丢弃高相关因子: %s（保留 %s，ICIR 更高）", factor_name, best_factor)
    
    return selected_factors, dropped_factors


def select_factors(
    ic_result_dir: Optional[Path] = None,
    backtest_result_dir: Optional[Path] = None,
    corr_matrix: Optional[pd.DataFrame] = None,
    thresholds: Optional[Dict] = None,
    logger: Optional[logging.Logger] = None
) -> Dict:
    """完整筛选流程入口
    
    流程:
    1. 加载所有因子数据
    2. 筛选无效因子
    3. 识别高相关组
    4. 选择最优因子
    
    Args:
        ic_result_dir: IC 结果目录
        backtest_result_dir: 回测结果目录
        corr_matrix: 因子相关性矩阵（可选，如未提供需额外计算）
        thresholds: 阈值配置
        logger: 日志对象
    
    Returns:
        {
            'selected': ['volume_ratio', 'rsi'],
            'valid_count': 5,
            'invalid': {'kdj_j': ['|ic_mean|=0.01<0.03']},
            'high_corr_dropped': {'turnover_surge': '...'},
            'thresholds': {...},
            'selection_reason': '低相关性组合，ICIR加权最优'
        }
    """
    if logger is None:
        logger = get_logger(__name__)
    
    logger.info("=" * 40)
    logger.info("因子筛选流程")
    logger.info("=" * 40)
    
    # Step 1: 加载因子数据
    all_factors = load_all_factor_results(
        ic_result_dir=ic_result_dir,
        backtest_result_dir=backtest_result_dir,
        logger=logger
    )
    
    # Step 2: 筛选无效因子
    filter_result = filter_invalid_factors(
        all_factors=all_factors,
        thresholds=thresholds,
        logger=logger
    )
    
    valid_factors = filter_result['valid']
    invalid_factors = filter_result['invalid']
    
    # Step 3: 识别高相关组（需要相关性矩阵）
    high_corr_groups = []
    high_corr_dropped = {}
    
    # 修复：添加筛选完整性标记
    selection_complete = True  # 筛选是否完整（corr_matrix 存在时完整）
    selection_warnings = []    # 筛选过程中的警告
    
    if corr_matrix is not None and len(valid_factors) > 0:
        high_corr_groups = identify_high_corr_groups(
            valid_factors=valid_factors,
            corr_matrix=corr_matrix,
            threshold=thresholds.get('high_corr_threshold', 0.7) if thresholds else 0.7,
            logger=logger
        )
        
        # Step 4: 选择最优因子
        selected_factors, high_corr_dropped = select_best_from_groups(
            high_corr_groups=high_corr_groups,
            valid_factors=valid_factors,
            logger=logger
        )
    else:
        selected_factors = list(valid_factors.keys())
        selection_complete = False  # 修复：标记筛选不完整
        
        # 修复：详细记录跳过原因
        if corr_matrix is None:
            selection_warnings.append("缺少相关性矩阵，跳过高相关筛选")
            logger.warning("缺少相关性矩阵，跳过高相关筛选")
        if len(valid_factors) == 0:
            selection_warnings.append("无有效因子，跳过高相关筛选")
            logger.warning("无有效因子，跳过高相关筛选")
    
    # 构建输出
    # 映射因子逻辑名到数据列名
    factor_cols = []
    unmapped_factors = []
    for factor_name in selected_factors:
        if factor_name in FACTOR_NAME_TO_COL_MAP:
            factor_cols.append(FACTOR_NAME_TO_COL_MAP[factor_name])
        else:
            # 未找到映射，使用因子名作为列名（兼容处理）
            factor_cols.append(factor_name)
            unmapped_factors.append(factor_name)
            logger.warning("因子 '%s' 未找到列名映射，使用因子名作为列名", factor_name)
    
    result = {
        'selected': selected_factors,
        'factor_cols': factor_cols,  # 新增：数据列名映射结果
        'unmapped_factors': unmapped_factors,  # 新增：未映射的因子列表
        'valid_count': len(valid_factors),
        'total_count': len(all_factors),
        'invalid': invalid_factors,
        'high_corr_dropped': high_corr_dropped,
        'high_corr_groups': high_corr_groups,
        'thresholds': thresholds or DEFAULT_THRESHOLDS,
        'selection_reason': f"从{len(all_factors)}个因子中筛选{len(selected_factors)}个",
        # 修复：新增筛选完整性标记
        'selection_complete': selection_complete,  # True=完整筛选，False=跳过高相关筛选
        'selection_warnings': selection_warnings   # 筛选过程中的警告列表
    }
    
    logger.info("筛选完成: 选中 %d 个因子", len(selected_factors))
    logger.info("选中因子: %s", selected_factors)
    logger.info("对应列名: %s", factor_cols)
    
    return result