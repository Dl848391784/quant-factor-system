"""
因子筛选模块

功能:
1. 加载所有因子 IC 结果 + 回测结果
2. 判断无效因子（阈值标准）
3. 识别高相关组并筛选（保留 ICIR 最高的）
4. 输出筛选结果供综合因子计算使用

阈值标准（业界惯例):
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

版本历史:
    v1.4 (2026-06-03): FACTOR_NAME_TO_COL_MAP 补全16个因子（解决筛选遗漏问题）
    v1.5 (2026-06-10): 修复小样本因子筛选标准不匹配问题
        - p_value 小样本豁免：valid_days < 30 时跳过 p_value 检查（tail_price_slope 案例）
        - 反向因子识别：|ic_mean| 不足但回测强劲（夏普>1.5, 单调性>0.5）时豁免 ic_mean 阈值
        - load_all_factor_results 新增 sample_stats 提取（含 valid_days）
"""

import json
import logging
import re  # 修复：移至模块顶层（PEP 8 规范）
from pathlib import Path

import pandas as pd
from comprehensive_factor.common.logger_config import get_logger


# 默认路径
DEFAULT_IC_RESULT_DIR = Path(__file__).parent.parent.parent / "factor_ic" / "result"
DEFAULT_BACKTEST_RESULT_DIR = Path(__file__).parent.parent.parent / "backtest" / "result"


# 默认阈值（业界惯例）
# v2.6: 修复高相关剔除显示格式：当ICIR相等时使用 '=' 而非 '<'
# v2.7: 修复显示精度：使用 .3f 避免 0.32<0.32 视觉矛盾
DEFAULT_THRESHOLDS = {
    "ic_mean_abs_min": 0.03,  # |IC均值| 最小值（经济显著性）
    "p_value_max": 0.05,  # p-value 最大值（统计显著性）
    "icir_abs_min": 0.15,  # |ICIR| 最小值（稳定性，0.15≈IC均值/IC标准差>0.03/0.2）
    "monotonicity_corr_abs_min": 0.4,  # |单调性相关性| 最小值（0.4为一般单调）
    "long_short_return_min": 0.03,  # 多空年化收益最小值（3%，扣除成本后仍正收益）
    "high_corr_threshold": 0.7,  # 高相关性阈值
    "min_sample_days": 30,  # v1.6: 最小样本天数（统计学大样本近似门槛，ICIR统计可靠性）
}


# 因子名到数据列名的映射（v1.2 → v1.3 扩展）
# 说明：factor_list 是因子逻辑名（如 'rsi'），factor_cols 是缓存数据列名（如 'rsi_6'）
# 注意：列名必须与 factor_ic_data.json.gz 中的实际列名一致
# 可用因子列（2026-06-02）：rsi_6, volume_ratio_5, turnover_rate, bollinger_pb, kdj_j, turnover_surge,
#                           amplitude, price_position, tail_price_position, tail_price_slope, tail_price_volume_intensity
#                           return_5d, momentum_strength（v1.37 2026-06-05）
#                           industry_momentum_5d, industry_turnover_trend, industry_amplitude_trend（v1.42 2026-06-12）
FACTOR_NAME_TO_COL_MAP = {
    # 基础因子（内置列名带后缀）
    "rsi": "rsi_6",
    "volume_ratio": "volume_ratio_5",
    # 扩展因子（列名不带后缀）
    "kdj_j": "kdj_j",
    "bollinger_pb": "bollinger_pb",
    "turnover_surge": "turnover_surge",
    "amplitude": "amplitude",
    "price_position": "price_position",
    "overnight_ret": "overnight_ret",
    # 动量因子（v1.37 2026-06-05）
    "return_5d": "return_5d",
    "momentum_strength": "momentum_strength",
    # 尾盘因子（v1.3 2026-06-02）
    "tail_price_position": "tail_price_position",
    "tail_price_slope": "tail_price_slope",
    "tail_price_volume_intensity": "tail_price_volume_intensity",
    "tail_volume_acceleration": "tail_volume_acceleration",
    "tail_volume_shrink": "tail_volume_shrink",
    # 方向性因子（v1.41 2026-06-11，止跌信号+趋势维度补充）
    "volume_price_strength": "volume_price_strength",
    "positive_day_ratio_5": "positive_day_ratio_5",
    "ma5_deviation": "ma5_deviation",
    "near_high_ratio_5": "near_high_ratio_5",
    # 差分因子（v1.40 2026-06-11）——数据源已有列，可直接读取
    "tail_price_position_delta": "tail_price_position_delta",
    "tail_volume_shrink_delta": "tail_volume_shrink_delta",
    # 行业方向性因子（v1.42 2026-06-12，行业层面趋势维度补充）
    "industry_momentum_5d": "industry_momentum_5d",
    "industry_turnover_trend": "industry_turnover_trend",
    "industry_amplitude_trend": "industry_amplitude_trend",
    # 其他因子
    "intraday_intensity": "intraday_intensity",
}


def load_all_factor_results(
    ic_result_dir: Path | None = None,
    backtest_result_dir: Path | None = None,
    return_period: str = "1d",
    logger: logging.Logger | None = None,
) -> dict[str, dict]:
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

    # 正则模式：ic_<因子名>_<收益周期>_analysis_result.json
    # 例：ic_rsi_1d_analysis_result.json → rsi
    # 例：ic_volume_ratio_1d_analysis_result.json → volume_ratio
    ic_pattern = re.compile(rf"^ic_(.+?)_{return_period}_analysis_result$")

    for ic_file in ic_result_dir.glob(f"ic_*_{return_period}_analysis_result.json"):
        # 修复：使用正则提取因子名，而非多次 replace
        match = ic_pattern.match(ic_file.stem)
        if match:
            factor_name = match.group(1)
        else:
            # 修复：正则不匹配时跳过文件，而非使用可能有问题的回退逻辑
            logger.warning(
                "IC文件名格式非标准，跳过: %s（期望格式: ic_<因子名>_%s_analysis_result.json）",
                ic_file.name,
                return_period,
            )
            continue  # 跳过非标准文件

        # 修复：添加异常处理，单文件损坏不影响整体加载
        try:
            with open(ic_file, encoding="utf-8") as f:
                ic_data = json.load(f)

            all_factors[factor_name] = {
                "ic_metrics": ic_data.get("ic_metrics", {}),
                "sample_stats": ic_data.get("sample_stats", {}),  # v1.5: 新增 sample_stats（含 valid_days）
                "ic_file": str(ic_file),
            }
            logger.debug("加载 IC 结果: %s", factor_name)
        except (OSError, json.JSONDecodeError, UnicodeDecodeError) as e:
            # JSON 格式错误、编码错误、磁盘问题
            logger.error("IC文件加载失败，跳过: %s，错误类型: %s，错误信息: %s", ic_file.name, type(e).__name__, str(e))
            continue  # 跳过损坏文件，继续加载其他文件

    # 加载回测结果
    logger.info("加载回测结果: %s", backtest_result_dir)
    # 正则模式：<因子名>_layered_backtest.json
    backtest_pattern = re.compile(r"^(.+?)_layered_backtest$")

    for backtest_file in backtest_result_dir.glob("*_layered_backtest.json"):
        # 修复：使用正则提取因子名
        match = backtest_pattern.match(backtest_file.stem)
        if match:
            factor_name = match.group(1)
        else:
            # 修复：正则不匹配时跳过文件
            logger.warning(
                "回测文件名格式非标准，跳过: %s（期望格式: <因子名>_layered_backtest.json）", backtest_file.name
            )
            continue  # 跳过非标准文件

        # 修复：添加异常处理
        try:
            with open(backtest_file, encoding="utf-8") as f:
                backtest_data = json.load(f)

            if factor_name in all_factors:
                all_factors[factor_name]["backtest"] = backtest_data
            else:
                all_factors[factor_name] = {"backtest": backtest_data, "ic_metrics": {}}
            logger.debug("加载回测结果: %s", factor_name)
        except (OSError, json.JSONDecodeError, UnicodeDecodeError) as e:
            logger.error(
                "回测文件加载失败，跳过: %s，错误类型: %s，错误信息: %s", backtest_file.name, type(e).__name__, str(e)
            )
            continue

    logger.info("加载因子数据: %d 个因子", len(all_factors))

    return all_factors


def validate_factor(
    factor_name: str, factor_data: dict, thresholds: dict | None = None, logger: logging.Logger | None = None
) -> tuple[bool, list[str]]:
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
    ic_metrics = factor_data.get("ic_metrics", {})
    ic_mean = ic_metrics.get("ic_mean", None)
    sample_stats = factor_data.get("sample_stats", {})
    valid_days = sample_stats.get("valid_days", None)
    backtest = factor_data.get("backtest", {})
    long_short = backtest.get("long_short", {})
    monotonicity = backtest.get("monotonicity", {})
    ls_sharpe = long_short.get("long_short_sharpe", None)
    mono_corr = monotonicity.get("correlation", None)
    min_sample_days = thresholds.get("min_sample_days", 30)

    # 0. 样本量检查（v1.6: 短样本因子统计指标不可靠，需特殊处理）
    # 统计原理：样本量 < 30 时，IC均值/ICIR/p_value均不可靠
    # 短样本因子的ICIR可能因偶然高相关而被赋予过大权重
    is_short_sample = valid_days is not None and valid_days < min_sample_days
    # v1.6: 短样本回测强劲豁免——回测夏普>3.0且单调性>0.6时，短样本因子仍可能有预测能力
    # 条件：|夏普|>3.0（远超阈值）+ |单调性|>0.6（较强）+ |ic_mean|>=0.005（不至于太弱）
    is_short_sample_exempt = (
        is_short_sample
        and ls_sharpe is not None
        and abs(ls_sharpe) > 3.0
        and mono_corr is not None
        and abs(mono_corr) > 0.6
        and ic_mean is not None
        and abs(ic_mean) >= 0.005
    )

    # 修复：关键指标缺失时标记为无效，并记录日志
    if ic_mean is None:
        reasons.append("ic_mean 缺失（数据不完整）")
        logger.debug("因子 %s: ic_mean 缺失", factor_name)
    elif abs(ic_mean) < thresholds["ic_mean_abs_min"]:
        # v1.5→v1.6: 反向因子豁免扩展——降低ic_mean门槛至0.005，新增ICIR豁免
        # v1.5: |ic_mean| >= 0.01 + 夏普 > 1.5 + 单调性 > 0.5
        # v1.6: |ic_mean| >= 0.005（覆盖tail_volume_shrink: ic_mean=0.006）+ 夏普 > 1.5 + 单调性 > 0.5
        is_reverse_factor_candidate = (
            abs(ic_mean) >= 0.005
            and ls_sharpe is not None
            and abs(ls_sharpe) > 1.5
            and mono_corr is not None
            and abs(mono_corr) > 0.5
        )
        if is_reverse_factor_candidate:
            logger.info(
                "因子 %s: |ic_mean|=%.3f<%.3f 但回测强劲(夏普=%.2f,单调性=%.2f)，反向因子豁免",
                factor_name,
                abs(ic_mean),
                thresholds["ic_mean_abs_min"],
                ls_sharpe,
                mono_corr,
            )
        else:
            reasons.append(f"|ic_mean|={abs(ic_mean):.3f}<{thresholds['ic_mean_abs_min']}")
            logger.debug("因子 %s: |ic_mean|=%.3f 不达标", factor_name, abs(ic_mean))

    # 2. p-value 检查（可选，缺失时跳过）
    p_value = ic_metrics.get("p_value", None)
    # v1.5: 小样本豁免——valid_days < 30 时 p_value 不可靠，跳过检查
    # 统计原理：样本量 < 30 时，即使强信号也难以达到 p < 0.05
    # 阈值来源：统计学最小样本量惯例（30 为大样本近似门槛）
    MIN_SAMPLE_SIZE_FOR_PVALUE = 30
    if p_value is not None and p_value > thresholds["p_value_max"]:
        if valid_days is not None and valid_days < MIN_SAMPLE_SIZE_FOR_PVALUE:
            logger.info(
                "因子 %s: p_value=%.3f>%.2f 但有效天数=%d<%d，小样本豁免p_value检查",
                factor_name,
                p_value,
                thresholds["p_value_max"],
                valid_days,
                MIN_SAMPLE_SIZE_FOR_PVALUE,
            )
        else:
            reasons.append(f"p_value={p_value:.3f}>{thresholds['p_value_max']}")

    # 3. ICIR 检查
    icir = ic_metrics.get("icir", None)

    # 修复：关键指标缺失时标记为无效，并记录日志
    if icir is None:
        reasons.append("icir 缺失（数据不完整）")
        logger.debug("因子 %s: icir 缺失", factor_name)
    elif abs(icir) < thresholds["icir_abs_min"]:
        # v1.6: ICIR反向因子豁免——回测指标强劲时|icir|不足不应剔除
        # 条件同ic_mean豁免：|夏普|>1.5 + |单调性|>0.5 + |ic_mean|>=0.005
        # 理由：ICIR低但回测好=非线性关系/尾部效应，线性IC低估因子价值
        is_icir_exempt = (
            ls_sharpe is not None
            and abs(ls_sharpe) > 1.5
            and mono_corr is not None
            and abs(mono_corr) > 0.5
            and ic_mean is not None
            and abs(ic_mean) >= 0.005
        )
        if is_icir_exempt:
            logger.info(
                "因子 %s: |icir|=%.3f<%.3f 但回测强劲(夏普=%.2f,单调性=%.2f)，反向因子ICIR豁免",
                factor_name,
                abs(icir),
                thresholds["icir_abs_min"],
                ls_sharpe,
                mono_corr,
            )
        else:
            reasons.append(f"|icir|={abs(icir):.3f}<{thresholds['icir_abs_min']}")
            logger.debug("因子 %s: |icir|=%.3f 不达标", factor_name, abs(icir))

    # 4. 单调性检查（可选）
    # v1.6: backtest/monotonicity 已在顶部提取，不再重复
    if mono_corr is not None and abs(mono_corr) < thresholds["monotonicity_corr_abs_min"]:
        reasons.append(f"|monotonicity_corr|={abs(mono_corr):.2f}<{thresholds['monotonicity_corr_abs_min']}")

    # 5. 多空收益检查（可选）
    # v1.6: long_short 已在顶部提取
    ls_return = long_short.get("long_short_return_annual", None)
    if ls_return is not None and ls_return < thresholds["long_short_return_min"]:
        reasons.append(f"long_short_return={ls_return * 100:.1f}%<{thresholds['long_short_return_min'] * 100:.0f}%")

    # 6. 短样本警告（v1.6: 不剔除但标记，ICIR权重惩罚在下游处理）
    # 短样本因子不被剔除（可能仍有预测力），但需要标记以在ICIR加权时惩罚
    if is_short_sample and not is_short_sample_exempt:
        # 非豁免短样本因子：标记但不剔除（reasons不含此项）
        logger.warning(
            "因子 %s: 有效天数=%d<%d（短样本），ICIR权重将被惩罚(×sqrt(%d/%d))",
            factor_name,
            valid_days,
            min_sample_days,
            valid_days,
            min_sample_days,
        )

    is_valid = len(reasons) == 0

    return is_valid, reasons


def filter_invalid_factors(
    all_factors: dict[str, dict], thresholds: dict | None = None, logger: logging.Logger | None = None
) -> dict[str, dict]:
    """筛选无效因子

    v1.6: 新增 short_sample_factors 标记（短样本因子不剔除但标记，供ICIR权重惩罚使用）

    Args:
        all_factors: 所有因子数据
        thresholds: 阈值配置
        logger: 日志对象

    Returns:
        {'valid': {...}, 'invalid': {factor_name: reasons}, 'short_sample_factors': {factor_name: valid_days}}
    """
    if logger is None:
        logger = get_logger(__name__)

    if thresholds is None:
        thresholds = DEFAULT_THRESHOLDS

    valid_factors = {}
    invalid_factors = {}
    short_sample_factors = {}  # v1.6: 短样本因子标记
    min_sample_days = thresholds.get("min_sample_days", 30)
    # v1.7: 极短样本硬门槛——valid_days < 15 的因子直接剔除
    # 统计学依据：15天以下ICIR的t检验 p-value > 0.3，不具任何预测意义
    MIN_ABSOLUTE_SAMPLE_DAYS = 15

    for factor_name, factor_data in all_factors.items():
        # 修复：传入 logger 参数，以便 validate_factor 记录日志
        is_valid, reasons = validate_factor(factor_name, factor_data, thresholds, logger)

        # v1.7: 极短样本硬门槛检查（优先于validate_factor结果）
        sample_stats = factor_data.get("sample_stats", {})
        valid_days = sample_stats.get("valid_days", None)
        if valid_days is not None and valid_days < MIN_ABSOLUTE_SAMPLE_DAYS:
            is_valid = False
            reasons = [f"极短样本: valid_days={valid_days}<{MIN_ABSOLUTE_SAMPLE_DAYS}(ICIR统计不显著)"]
            logger.warning("极短样本剔除: %s, valid_days=%d (< %d)", factor_name, valid_days, MIN_ABSOLUTE_SAMPLE_DAYS)

        if is_valid:
            valid_factors[factor_name] = factor_data
            # v1.6: 标记短样本因子（有效天数 < min_sample_days）
            if valid_days is not None and valid_days < min_sample_days:
                short_sample_factors[factor_name] = valid_days
            logger.debug("有效因子: %s", factor_name)
        else:
            invalid_factors[factor_name] = reasons
            logger.warning("无效因子: %s, 原因: %s", factor_name, "; ".join(reasons))

    logger.info(
        "筛选结果: 有效 %d, 无效 %d, 短样本 %d", len(valid_factors), len(invalid_factors), len(short_sample_factors)
    )

    return {"valid": valid_factors, "invalid": invalid_factors, "short_sample_factors": short_sample_factors}


def identify_high_corr_groups(
    valid_factors: dict[str, dict],
    corr_matrix: pd.DataFrame,
    threshold: float | None = None,
    logger: logging.Logger | None = None,
) -> tuple[list[list[str]], list[tuple[str, str, float]]]:
    """识别高相关因子组

    v2.5 (2026-05-28): 返回 (groups, high_corr_pairs)，保存相关系数值供下游使用

    使用 Union-Find（并查集）算法识别高相关因子组。
    正确处理跨组合并（A-B, B-C, C-D 应合并为一个大组）。

    Args:
        valid_factors: 有效因子数据
        corr_matrix: 相关性矩阵
        threshold: 高相关性阈值
        logger: 日志对象

    Returns:
        (高相关因子组列表, 高相关因子对列表)
        groups: [['rsi', 'bollinger_pb', 'kdj_j'], ['volume_ratio', 'turnover_surge']]
        high_corr_pairs: [('rsi', 'bollinger_pb', 0.85), ...]

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
        threshold = DEFAULT_THRESHOLDS["high_corr_threshold"]

    factor_names = list(valid_factors.keys())

    if len(factor_names) == 0:
        return []

    # 修复：入口校验因子名与相关性矩阵索引的匹配性
    missing_in_index = [name for name in factor_names if name not in corr_matrix.index]
    missing_in_columns = [name for name in factor_names if name not in corr_matrix.columns]

    if missing_in_index or missing_in_columns:
        logger.warning(
            "因子名与相关性矩阵索引不匹配: 缺失于 index=%s, 缺失于 columns=%s，将跳过这些因子",
            missing_in_index[:5] if len(missing_in_index) > 5 else missing_in_index,
            missing_in_columns[:5] if len(missing_in_columns) > 5 else missing_in_columns,
        )
        # 过滤掉不在矩阵中的因子
        factor_names = [name for name in factor_names if name in corr_matrix.index and name in corr_matrix.columns]

        if len(factor_names) == 0:
            logger.error("所有因子都不在相关性矩阵中，返回空组")
            return [], []  # v2.5: 返回 tuple

    # Union-Find 数据结构
    parent = {name: name for name in factor_names}  # 每个因子初始指向自己

    # 修复：使用迭代实现 find，避免大规模因子库栈溢出
    def find(x: str) -> str:
        """查找根节点（迭代实现 + 路径压缩）"""
        # 迭代查找根节点
        root = x
        while parent[root] != root:
            root = parent[root]

        # 路径压缩：将路径上所有节点直接指向根
        current = x
        while parent[current] != root:
            next_node = parent[current]
            parent[current] = root
            current = next_node

        return root

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
    groups_dict: dict[str, list[str]] = {}
    for name in factor_names:
        root = find(name)
        if root not in groups_dict:
            groups_dict[root] = []
        groups_dict[root].append(name)

    # 只返回有多个因子的组（高相关组）
    groups = [group for group in groups_dict.values() if len(group) > 1]

    logger.info("高相关因子组: %d 组（共 %d 对高相关）", len(groups), len(high_corr_pairs))

    # v2.5: 返回 (groups, high_corr_pairs)，保存相关系数值
    return groups, high_corr_pairs


def select_best_from_groups(
    high_corr_groups: list[list[str]],
    high_corr_pairs: list[tuple[str, str, float]],
    valid_factors: dict[str, dict],
    logger: logging.Logger | None = None,
) -> tuple[list[str], dict[str, str]]:
    """从高相关组中选择最优因子

    v2.5 (2026-05-28): 新增 high_corr_pairs 参数，在剔除原因中包含具体相关系数

    保留规则：组内保留 |ICIR| 最高的因子

    Args:
        high_corr_groups: 高相关因子组
        high_corr_pairs: 高相关因子对列表（含相关系数）
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

    # v2.5: 构建相关系数查找表 {(factor_a, factor_b): corr_value}
    corr_lookup: dict[tuple[str, str], float] = {}
    for fa, fb, corr in high_corr_pairs:
        corr_lookup[(fa, fb)] = corr
        corr_lookup[(fb, fa)] = corr  # 双向查找

    # 修复：使用 set 替代 list，避免 O(n²) 复杂度
    # list.remove() + in 检查 都是 O(n)，嵌套循环总体 O(n²)
    # set.discard() + in 检查 都是 O(1)，总体 O(n)
    selected_factors_set = set(valid_factors.keys())  # 初始为所有有效因子
    dropped_factors = {}

    for group in high_corr_groups:
        # 计算组内每个因子的 |ICIR|
        icir_values = {}
        missing_icir_factors = []  # 修复：记录 icir 缺失的因子

        for factor_name in group:
            ic_metrics = valid_factors.get(factor_name, {}).get("ic_metrics", {})
            icir = ic_metrics.get("icir", None)  # 修复：不默认为 0

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
            logger.warning("高相关组 %s 所有因子 icir 缺失，无法比较，保留第一个: %s", group, best_factor)
            # 丢弃其他因子
            for factor_name in group:
                if factor_name != best_factor and factor_name in selected_factors_set:
                    # 修复：使用 discard 替代 remove（O(1) vs O(n)）
                    selected_factors_set.discard(factor_name)
                    # v2.5: 包含相关系数
                    corr_val = corr_lookup.get((factor_name, best_factor))
                    corr_str = f"corr={corr_val:.2f}" if corr_val is not None else ""
                    dropped_factors[factor_name] = f"与{best_factor}高相关({corr_str}), icir缺失无法比较"
        else:
            # 找出 ICIR 最高的因子（只比较有 icir 的因子）
            best_factor = max(valid_icir_values.keys(), key=lambda k: valid_icir_values[k])

            # 丢弃其他因子（包括 icir 缺失的因子）
            for factor_name in group:
                if factor_name != best_factor:
                    # 修复：使用 in + discard（O(1) vs O(n)）
                    if factor_name in selected_factors_set:
                        selected_factors_set.discard(factor_name)

                        # v2.5: 获取相关系数
                        corr_val = corr_lookup.get((factor_name, best_factor))
                        corr_str = f"corr={corr_val:.2f}" if corr_val is not None else ""

                        # 修复：区分 icir 缺失和 ICIR 较低
                        if factor_name in missing_icir_factors:
                            dropped_factors[factor_name] = (
                                f"与{best_factor}高相关({corr_str}), icir缺失({best_factor}|ICIR|={valid_icir_values[best_factor]:.2f})"
                            )
                        else:
                            # v2.6: 修复问题4 - 当 ICIR 相等时显示 '=' 而非 '<'
                            # v2.7: 修复显示精度 - 使用 .3f 避免 0.32<0.32 视觉矛盾
                            icir_val = icir_values[factor_name]
                            best_icir_val = valid_icir_values[best_factor]
                            # 使用阈值容差判断相等（避免浮点精度问题）
                            icir_cmp = "=" if abs(icir_val - best_icir_val) < 0.001 else "<"
                            dropped_factors[factor_name] = (
                                f"与{best_factor}高相关({corr_str}), |ICIR|={icir_val:.3f}{icir_cmp}{best_icir_val:.3f}"
                            )

                        logger.info("丢弃高相关因子: %s（保留 %s，ICIR 更高）", factor_name, best_factor)

    # 修复：返回 list 格式（兼容调用方）
    return list(selected_factors_set), dropped_factors


def select_factors(
    ic_result_dir: Path | None = None,
    backtest_result_dir: Path | None = None,
    corr_matrix: pd.DataFrame | None = None,
    thresholds: dict | None = None,
    logger: logging.Logger | None = None,
) -> dict:
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

    # 修复：入口统一处理 thresholds 为 None 的情况
    if thresholds is None:
        thresholds = DEFAULT_THRESHOLDS

    logger.info("=" * 40)
    logger.info("因子筛选流程")
    logger.info("=" * 40)

    # Step 1: 加载因子数据
    all_factors = load_all_factor_results(
        ic_result_dir=ic_result_dir, backtest_result_dir=backtest_result_dir, logger=logger
    )

    # Step 2: 筛选无效因子
    filter_result = filter_invalid_factors(all_factors=all_factors, thresholds=thresholds, logger=logger)

    valid_factors = filter_result["valid"]
    invalid_factors = filter_result["invalid"]
    short_sample_factors = filter_result.get("short_sample_factors", {})  # v1.6

    # Step 3: 识别高相关组（需要相关性矩阵）
    high_corr_groups = []
    high_corr_dropped = {}

    # 修复：添加筛选完整性标记
    selection_complete = True  # 筛选是否完整（corr_matrix 存在时完整）
    selection_warnings = []  # 筛选过程中的警告

    # v2.5: high_corr_pairs 保存相关系数值
    high_corr_pairs: list[tuple[str, str, float]] = []

    if corr_matrix is not None and len(valid_factors) > 0:
        # v2.5: identify_high_corr_groups 现在返回 (groups, pairs)
        high_corr_groups, high_corr_pairs = identify_high_corr_groups(
            valid_factors=valid_factors,
            corr_matrix=corr_matrix,
            threshold=thresholds["high_corr_threshold"],  # 修复：入口已处理 None，直接使用
            logger=logger,
        )

        # Step 4: 选择最优因子
        # v2.5: 传入 high_corr_pairs，在原因中包含相关系数
        selected_factors, high_corr_dropped = select_best_from_groups(
            high_corr_groups=high_corr_groups,
            high_corr_pairs=high_corr_pairs,
            valid_factors=valid_factors,
            logger=logger,
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
        "selected": selected_factors,
        "factor_cols": factor_cols,  # 新增：数据列名映射结果
        "unmapped_factors": unmapped_factors,  # 新增：未映射的因子列表
        "valid_count": len(valid_factors),
        "total_count": len(all_factors),
        "invalid": invalid_factors,
        "high_corr_dropped": high_corr_dropped,
        "high_corr_groups": high_corr_groups,
        "thresholds": thresholds or DEFAULT_THRESHOLDS,
        "selection_reason": f"从{len(all_factors)}个因子中筛选{len(selected_factors)}个",
        # 修复：新增筛选完整性标记
        "selection_complete": selection_complete,  # True=完整筛选，False=跳过高相关筛选
        "selection_warnings": selection_warnings,  # 筛选过程中的警告列表
        # v1.6: 短样本因子标记（供ICIR权重惩罚使用）
        "short_sample_factors": short_sample_factors,  # {factor_name: valid_days}
    }

    logger.info("筛选完成: 选中 %d 个因子", len(selected_factors))
    logger.info("选中因子: %s", selected_factors)
    logger.info("对应列名: %s", factor_cols)

    return result
