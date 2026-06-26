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
- long_return_annual < 3% → 无效（经济意义弱，只做多策略）

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
    v1.6 (2026-06-13): 单一映射来源（方案 B）
        - 删除本地 FACTOR_NAME_TO_COL_MAP 定义，改为从 factor_definitions 导入
        - 详见 designs/factor_name_col_map_unification_design.md
    v1.7 (2026-06-19): ICIR 比较容差修复
        - 容差从 0.001 收紧至 1e-9，避免相近 ICIR 误判为相等
        - 显示精度从 .3f 改为 .4f，确保差异可见（如 0.3199<0.3202）
    v1.8 (2026-06-20): 维度感知去重
    v1.9 (2026-06-20): 移除跨维度兜底合并——跨维度因子对一律不合并
        - identify_high_corr_groups 新增 factor_categories 参数
        - 同维度因子对用 threshold(0.7) 合并去重；跨维度因子对不合并（经济含义不同）
        - 新增 _compute_dimension_coverage 辅助函数
        - select_factors 输出新增 dimension_coverage 字段
        - 详见 designs/factor_classification_design.md
"""

import json
import logging
import re  # 修复：移至模块顶层（PEP 8 规范）
from pathlib import Path

import pandas as pd
from comprehensive_factor.common.logger_config import get_logger

# v1.6: 单一映射来源（方案 B）
# 调用方（composite_runner / run_pipeline 等）已将项目根加入 sys.path
from factor_definitions import FACTOR_CATEGORIES, FACTOR_NAME_TO_COL_MAP, FACTOR_ROLES

# 默认路径（pipeline 感知，从 paths.py 导入）
from paths import BACKTEST_RESULT, FACTOR_IC_RESULT  # noqa: E402


DEFAULT_IC_RESULT_DIR = FACTOR_IC_RESULT
DEFAULT_BACKTEST_RESULT_DIR = BACKTEST_RESULT


# 默认阈值（业界惯例）
# v2.6: 修复高相关剔除显示格式：当ICIR相等时使用 '=' 而非 '<'
# v2.7: 修复显示精度：使用 .3f 避免 0.32<0.32 视觉矛盾
# v2.35: P1 只做多对齐——long_short_return_min → long_return_min（多头年化）
# v2.35: P1 只做多对齐——min_sample_days 30→60（t检验: N=60时 t=ICIR×√60=1.16 边际显著）
# v2.35: P1 只做多对齐——新增 layer_1 硬约束（公理1: 只做多收益=L1收益，不可豁免）
DEFAULT_THRESHOLDS = {
    "ic_mean_abs_min": 0.03,  # |IC均值| 最小值（经济显著性）
    "p_value_max": 0.05,  # p-value 最大值（统计显著性）
    "icir_abs_min": 0.15,  # |ICIR| 最小值（稳定性，0.15≈IC均值/IC标准差>0.03/0.2）
    "monotonicity_corr_abs_min": 0.4,  # |单调性相关性| 最小值（0.4为一般单调）
    "long_return_min": 0.03,  # 多头年化收益最小值（3%，只做多策略经济意义门槛）
    "high_corr_threshold": 0.7,  # 同维度高相关性阈值
    "min_sample_days": 60,  # v2.35: 最小样本天数（t检验边际显著门槛，24天t=0.73不显著）
    "layer_1_return_min": 0.0,  # v2.35: L1年化收益下限（公理1: 只做多收益=L1，不可豁免）
    "layer_1_sharpe_min": 0.0,  # v2.35: L1夏普下限（L1正收益但不稳定不可用）
    # v2.45: 实验性硬门槛（design: factor_selector_positive_ic_only.md）
    # require_positive_ic=True 时，原始 ic_mean<0 的因子直接判定 invalid，不可豁免
    # 用途：动量风格 A/B 实验；默认 False，线上零影响
    # v2.48: 改回 False — True 时只保留 __neg 变体(IC>0, 下跌段激活)，
    #   导致 composite 选出的全是下跌股, 与"选暴涨后股票"的预期不符
    "require_positive_ic": False,
}


# v2.39: 交互因子族独立门槛体系（design.md feat_interaction_thresholds_v239.md §2.2）
# 第一性原理：交互因子 = -z_cs(weakness) × z_cs(X) 是乘法结构，统计特性与线性单调因子结构性不同：
#   - 池化 IC 等权稀释 → ic_mean 典型值 0.002~0.020（vs 线性 0.02~0.07）
#   - 早期 30 日 IC 噪声 ±0.15 + IC 衰减 → icir 典型 0.02~0.15（vs 线性 0.15~0.30）
#   - 乘法结构非单调，分层 U 形 → mono_corr 典型 0.30~0.50（vs 线性 0.50~0.80）
#   - ic_mean 小 → t 统计天然不显著 → p_value 跳过
#   - L1 = "强势×低 + 弱势×高" 双对角混合 → L1 必亏（数学必然），独立门槛容忍 L1 负
# long_return_min 反而更严（5% > 3%）：只做多策略能否赚钱的关键判据，不可放宽
# 详见 designs/feat_interaction_thresholds_v239.md §1.3（根因）§2.2（设计）§2.4（决策矩阵）
INTERACTION_THRESHOLDS = {
    "ic_mean_abs_min": 0.005,  # 池化 IC 稀释后, 三因子实测 0.002~0.008
    "p_value_max": 0.05,  # v2.39 修正: 保留 p_value 门槛（最强信号真实性判据, ic_mean 小时反而更重要）
    "icir_abs_min": 0.05,  # 早期噪声 + IC 衰减, 三因子实测 0.024~0.120
    "monotonicity_corr_abs_min": 0.30,  # 乘法非单调, 三因子实测 0.36~0.42
    "long_return_min": 0.05,  # 多头年化, 高于主 dict 3%（只做多关键判据, 三因子实测 10.1~11.6%）
    "high_corr_threshold": 0.7,  # 同主 dict（维度相关性是物理结构约束）
    "min_sample_days": 60,  # 同主 dict
    "layer_1_return_min": -0.28,  # v2.40: 7 因子分布 mean=-18.85% σ=4.55pp → mean-2σ≈-28%, 见 designs/feat_interaction_thresholds_v240.md
    "layer_1_sharpe_min": -1.50,  # L1 夏普容忍下限, 与 v2.38 设计一致
}


def _get_thresholds_for_factor(factor_name: str, base_thresholds: dict) -> tuple[dict, str]:
    """根据因子名前缀派发门槛 dict。

    交互因子族（factor_name.startswith("interaction_")）使用 INTERACTION_THRESHOLDS
    覆盖主 dict 的同名字段；其余因子使用 base_thresholds 不变。

    Args:
        factor_name: 因子名称（如 "rsi", "interaction_amplitude__ret3d_pos"）
        base_thresholds: 主门槛 dict（通常是 DEFAULT_THRESHOLDS）

    Returns:
        (merged_thresholds, source)
        - merged_thresholds: 派发后的门槛 dict
        - source: "interaction" 或 "default"，用于审计标识

    设计:
        - 用 merge 而非完全替换，避免 INTERACTION_THRESHOLDS 漏定义某字段导致 KeyError
        - 线性因子主 dict 零修改（方案 B 核心承诺）
        - 详见 designs/feat_interaction_thresholds_v239.md §3.2
    """
    if factor_name.startswith("interaction_"):
        merged = dict(base_thresholds)
        merged.update(INTERACTION_THRESHOLDS)
        return merged, "interaction"
    return base_thresholds, "default"


# v1.6: FACTOR_NAME_TO_COL_MAP 已从 factor_definitions 导入（单一映射来源）
# 历史本地定义已删除；如需扩展因子映射，请改 factor_definitions.py
# 详见：designs/factor_name_col_map_unification_design.md §3.2


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

            # v2.11: 回测文件名可能含 _1d 后缀（如 intraday_intensity_1d_layered_backtest.json），
            # 但 IC 文件名提取的因子名不含后缀（intraday_intensity），需要修正
            if factor_name not in all_factors and factor_name.endswith("_1d"):
                stripped = factor_name[:-3]
                if stripped in all_factors:
                    factor_name = stripped

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


def _build_exemption_fail_reason(sharpe: float | None, mono_corr: float | None, ic_mean: float | None) -> str:
    """构建豁免失败的原因说明

    Args:
        sharpe: 多空夏普比率
        mono_corr: 单调性相关系数
        ic_mean: IC均值

    Returns:
        失败原因字符串，指出哪个条件未满足
    """
    failed: list[str] = []
    if sharpe is None or abs(sharpe) <= 1.5:
        failed.append(f"夏普={sharpe:.2f}" if sharpe is not None else "夏普缺失")
    if mono_corr is None or abs(mono_corr) <= 0.5:
        failed.append(f"单调性={mono_corr:.2f}" if mono_corr is not None else "单调性缺失")
    if ic_mean is None or abs(ic_mean) < 0.005:
        failed.append(f"|ic_mean|={abs(ic_mean):.4f}" if ic_mean is not None else "ic_mean缺失")

    return f"未满足豁免: {'+'.join(failed)}"


def validate_factor(
    factor_name: str, factor_data: dict, thresholds: dict | None = None, logger: logging.Logger | None = None
) -> tuple[bool, list[str], list[dict]]:
    """判断因子是否有效

    Args:
        factor_name: 因子名称
        factor_data: 因子数据（ic_metrics + backtest）
        thresholds: 阈值配置

    Returns:
        (is_valid, reasons, exempt_details)
        - is_valid: True/False
        - reasons: 无效原因列表
        - exempt_details: 豁免详情列表，每个触发豁免检查的阈值一条记录
          [{"trigger": "ic_mean", "threshold": 0.03, "actual": 0.0168,
            "exempted": True/False,
            "conditions": {"sharpe": 5.54, "mono_corr": 0.53, "ic_mean_abs": 0.017},
            "detail": "回测强劲(夏普=5.54>1.5,单调性=0.53>0.5)"}, ...]
          无豁免触发时为空列表

    Note:
        - 关键指标缺失时标记为无效（不再静默通过）
        - 缺失指标包括：ic_mean、icir（静态权重计算必需）
        - 数据缺失的因子应被排除，而非误判为有效
    """
    if thresholds is None:
        thresholds = DEFAULT_THRESHOLDS

    if logger is None:
        logger = get_logger(__name__)

    # v2.39: 交互因子族独立门槛体系派发（design feat_interaction_thresholds_v239.md §3.2）
    # 线性因子（factor_name 不以 "interaction_" 开头）继续用 base_thresholds，零改动；
    # 交互因子用 INTERACTION_THRESHOLDS merge 覆盖同名字段
    thresholds, threshold_source = _get_thresholds_for_factor(factor_name, thresholds)

    reasons = []
    exempt_details: list[dict] = []

    # 1. IC 均值检查
    # v2.35: P6 角色化权重——确认信号因子 IC 门槛降至 0.01（design.md §2.6 决策点1）
    # v2.39: 交互因子族独立门槛 override confirmation 角色阈值
    #   confirmation 角色 0.01 是为线性确认因子标定的，交互因子族走 INTERACTION_THRESHOLDS 0.005
    factor_role = FACTOR_ROLES.get(factor_name, "primary")
    if threshold_source == "interaction":
        ic_threshold = thresholds["ic_mean_abs_min"]
    else:
        ic_threshold = 0.01 if factor_role == "confirmation" else thresholds["ic_mean_abs_min"]
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
    elif abs(ic_mean) < ic_threshold:
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
                ic_threshold,
                ls_sharpe,
                mono_corr,
            )
            exempt_details.append(
                {
                    "trigger": "ic_mean",
                    "threshold": ic_threshold,
                    "threshold_source": threshold_source,
                    "actual": abs(ic_mean),
                    "exempted": True,
                    "conditions": {
                        "sharpe": ls_sharpe,
                        "mono_corr": mono_corr,
                        "ic_mean_abs": abs(ic_mean),
                    },
                    "detail": f"回测强劲(夏普={abs(ls_sharpe):.2f}>1.5,单调性={abs(mono_corr):.2f}>0.5)",
                }
            )
        else:
            reasons.append(f"|ic_mean|={abs(ic_mean):.3f}<{ic_threshold}")
            logger.debug("因子 %s: |ic_mean|=%.3f 不达标", factor_name, abs(ic_mean))
            exempt_details.append(
                {
                    "trigger": "ic_mean",
                    "threshold": ic_threshold,
                    "threshold_source": threshold_source,
                    "actual": abs(ic_mean),
                    "exempted": False,
                    "conditions": {
                        "sharpe": ls_sharpe,
                        "mono_corr": mono_corr,
                        "ic_mean_abs": abs(ic_mean),
                    },
                    "detail": _build_exemption_fail_reason(ls_sharpe, mono_corr, ic_mean),
                }
            )

    # v2.45: 正 IC 硬门槛（require_positive_ic）
    # 设计：design factor_selector_positive_ic_only.md
    # 用途：动量风格 A/B 实验，排除反转族因子（原始 ic_mean<0）
    # 关键约束：硬门槛不可豁免——豁免会破坏"只用正向因子"的核心约束
    # 位置：IC 均值豁免逻辑之后，即使触发反向豁免也会被此门槛剔除
    # 默认 False（DEFAULT_THRESHOLDS）→ 线上 v2.44 行为零改动
    require_positive_ic = thresholds.get("require_positive_ic", False)
    if require_positive_ic and ic_mean is not None and ic_mean < 0:
        reasons.append(f"ic_mean={ic_mean:+.4f}<0（require_positive_ic=True）")
        logger.debug(
            "因子 %s: ic_mean=%+.4f<0, 被 require_positive_ic 过滤",
            factor_name,
            ic_mean,
        )

    # 2. p-value 检查（可选，缺失时跳过）
    p_value = ic_metrics.get("p_value", None)
    # v1.5: 小样本豁免——valid_days < 30 时 p_value 不可靠，跳过检查
    # 统计原理：样本量 < 30 时，即使强信号也难以达到 p < 0.05
    # 阈值来源：统计学最小样本量惯例（30 为大样本近似门槛）
    # v2.39: p_value_max=None 时跳过检查（交互因子族 design §2.2）
    MIN_SAMPLE_SIZE_FOR_PVALUE = 30
    p_value_max = thresholds.get("p_value_max")
    if p_value_max is not None and p_value is not None and p_value > p_value_max:
        if valid_days is not None and valid_days < MIN_SAMPLE_SIZE_FOR_PVALUE:
            logger.info(
                "因子 %s: p_value=%.3f>%.2f 但有效天数=%d<%d，小样本豁免p_value检查",
                factor_name,
                p_value,
                p_value_max,
                valid_days,
                MIN_SAMPLE_SIZE_FOR_PVALUE,
            )
        else:
            reasons.append(f"p_value={p_value:.3f}>{p_value_max}")

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
            exempt_details.append(
                {
                    "trigger": "icir",
                    "threshold": thresholds["icir_abs_min"],
                    "threshold_source": threshold_source,
                    "actual": abs(icir),
                    "exempted": True,
                    "conditions": {
                        "sharpe": ls_sharpe,
                        "mono_corr": mono_corr,
                        "ic_mean_abs": abs(ic_mean) if ic_mean is not None else None,
                    },
                    "detail": f"回测强劲(夏普={abs(ls_sharpe):.2f}>1.5,单调性={abs(mono_corr):.2f}>0.5)",
                }
            )
        else:
            reasons.append(f"|icir|={abs(icir):.3f}<{thresholds['icir_abs_min']}")
            logger.debug("因子 %s: |icir|=%.3f 不达标", factor_name, abs(icir))
            exempt_details.append(
                {
                    "trigger": "icir",
                    "threshold": thresholds["icir_abs_min"],
                    "threshold_source": threshold_source,
                    "actual": abs(icir),
                    "exempted": False,
                    "conditions": {
                        "sharpe": ls_sharpe,
                        "mono_corr": mono_corr,
                        "ic_mean_abs": abs(ic_mean) if ic_mean is not None else None,
                    },
                    "detail": _build_exemption_fail_reason(ls_sharpe, mono_corr, ic_mean),
                }
            )

    # 4. 单调性检查（可选）
    # v1.6: backtest/monotonicity 已在顶部提取，不再重复
    if mono_corr is not None and abs(mono_corr) < thresholds["monotonicity_corr_abs_min"]:
        reasons.append(f"|monotonicity_corr|={abs(mono_corr):.2f}<{thresholds['monotonicity_corr_abs_min']}")

    # 5. 多头收益检查（v2.35: P1 只做多对齐——原 long_short_return → long_return）
    # 公理1: 只做多策略不能做空，多空收益无意义，改用多头年化收益
    long_return = long_short.get("long_return_annual", None)
    if long_return is not None and long_return < thresholds["long_return_min"]:
        reasons.append(f"long_return={long_return * 100:.1f}%<{thresholds['long_return_min'] * 100:.0f}%")

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

    # 7. Layer1 绝对收益硬约束（v2.35: P1 只做多对齐）
    # 公理1: 只做多策略收益 = Layer1 买入层收益，L1<=0 的因子有害无益
    #
    # v2.39: 交互因子族走独立门槛（INTERACTION_THRESHOLDS）：
    #   - layer_1_return_min = -0.25（承认乘法结构 L1 必亏的数学必然）
    #   - layer_1_sharpe_min = -1.50（容忍 L1 夏普负值）
    #   设计依据：design.md feat_interaction_thresholds_v239.md §2.2
    # 线性因子继续走 DEFAULT_THRESHOLDS 的 0.0 硬约束（不变）
    # 历史：v2.38 Batch 1 的 L1 豁免分支（commit 4c845c0）已在 v2.39 删除——
    #       独立门槛体系下交互因子的 L1 阈值已下移到 -0.25，不再需要"豁免"逻辑
    layer_stats = backtest.get("layer_stats", {})
    layer_1 = layer_stats.get("layer_1", {})
    layer_1_annual = layer_1.get("annual_return", None)
    layer_1_sharpe = layer_1.get("sharpe_ratio", None)

    if layer_1_annual is not None and layer_1_annual <= thresholds["layer_1_return_min"]:
        reasons.append(
            f"layer_1_annual={layer_1_annual * 100:.1f}%<={thresholds['layer_1_return_min'] * 100:.0f}%（只做多硬约束）"
        )
        logger.info(
            "因子 %s: L1年化=%.2f%%<=%.0f%%，只做多策略有害，硬约束淘汰",
            factor_name,
            layer_1_annual * 100,
            thresholds["layer_1_return_min"] * 100,
        )
    if layer_1_sharpe is not None and layer_1_sharpe <= thresholds["layer_1_sharpe_min"]:
        reasons.append(f"layer_1_sharpe={layer_1_sharpe:.2f}<={thresholds['layer_1_sharpe_min']:.2f}（L1收益不稳定）")

    is_valid = len(reasons) == 0

    return is_valid, reasons, exempt_details


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
    exempted_factors: dict[str, list[dict]] = {}  # v2.10: 豁免详情（供报告展示）
    min_sample_days = thresholds.get("min_sample_days", 30)
    # v1.7: 极短样本硬门槛——valid_days < 15 的因子直接剔除
    # 统计学依据：15天以下ICIR的t检验 p-value > 0.3，不具任何预测意义
    MIN_ABSOLUTE_SAMPLE_DAYS = 15

    for factor_name, factor_data in all_factors.items():
        # 修复：传入 logger 参数，以便 validate_factor 记录日志
        is_valid, reasons, exempt_details = validate_factor(factor_name, factor_data, thresholds, logger)

        # v2.10: 收集豁免详情（无论入选或剔除，只要有豁免触发就记录）
        if exempt_details:
            exempted_factors[factor_name] = exempt_details

        # v1.7: 极短样本硬门槛检查（优先于validate_factor结果）
        sample_stats = factor_data.get("sample_stats", {})
        valid_days = sample_stats.get("valid_days", None)
        if valid_days is not None and valid_days < MIN_ABSOLUTE_SAMPLE_DAYS:
            is_valid = False
            reasons = [f"极短样本: valid_days={valid_days}<{MIN_ABSOLUTE_SAMPLE_DAYS}(ICIR统计不显著)"]
            logger.warning("极短样本剔除: %s, valid_days=%d (< %d)", factor_name, valid_days, MIN_ABSOLUTE_SAMPLE_DAYS)

        if is_valid:
            valid_factors[factor_name] = factor_data
            # v2.35: P6 角色化权重——标记因子角色（primary/confirmation/filter）
            valid_factors[factor_name]["role"] = FACTOR_ROLES.get(factor_name, "primary")
            # v1.6: 标记短样本因子（有效天数 < min_sample_days）
            if valid_days is not None and valid_days < min_sample_days:
                short_sample_factors[factor_name] = valid_days
            logger.debug("有效因子: %s", factor_name)
        else:
            invalid_factors[factor_name] = reasons
            logger.warning("无效因子: %s, 原因: %s", factor_name, "; ".join(reasons))

    logger.info(
        "筛选结果: 有效 %d, 无效 %d, 短样本 %d, 含豁免详情 %d",
        len(valid_factors),
        len(invalid_factors),
        len(short_sample_factors),
        len(exempted_factors),
    )

    return {
        "valid": valid_factors,
        "invalid": invalid_factors,
        "short_sample_factors": short_sample_factors,
        "exempted_factors": exempted_factors,
    }


def identify_high_corr_groups(
    valid_factors: dict[str, dict],
    corr_matrix: pd.DataFrame,
    threshold: float | None = None,
    factor_categories: dict[str, str] | None = None,
    logger: logging.Logger | None = None,
) -> tuple[list[list[str]], list[tuple[str, str, float]]]:
    """识别高相关因子组

    v2.5 (2026-05-28): 返回 (groups, high_corr_pairs)，保存相关系数值供下游使用
    v2.6 (2026-06-20): 维度感知——同维度因子对用 threshold(0.7) 合并去重，
        跨维度因子对不合并（经济含义不同，统计高相关 ≠ 经济冗余）
    v2.7 (2026-06-20): 移除跨维度兜底合并——跨维度 >0.9 的桥接会导致
        Union-Find 传递性消灭整个维度（如 rsi↔bollinger_pb 0.92 桥接
        导致 7 个 momentum 因子全部被 1 个 price_position 因子淘汰）

    使用 Union-Find（并查集）算法识别高相关因子组。
    正确处理跨组合并（A-B, B-C, C-D 应合并为一个大组）。

    Args:
        valid_factors: 有效因子数据
        corr_matrix: 相关性矩阵
        threshold: 同维度高相关性阈值（默认 0.7）
        factor_categories: 因子→维度映射（如 {"rsi": "momentum"}）。
            为 None 时退化为原始逻辑（所有因子对用同一阈值）
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
    # v2.7: 同维度 >threshold 合并；跨维度不合并（经济含义不同）
    high_corr_pairs = []
    cross_dimension_skipped: list[tuple[str, str, float, str, str]] = []
    for i, name_i in enumerate(factor_names):
        for j, name_j in enumerate(factor_names):
            if i < j and name_i in corr_matrix.index and name_j in corr_matrix.columns:
                corr_val = abs(corr_matrix.loc[name_i, name_j])
                if not pd.isna(corr_val) and corr_val > threshold:
                    # v2.7: 维度感知判断
                    cat_i = factor_categories.get(name_i) if factor_categories else None
                    cat_j = factor_categories.get(name_j) if factor_categories else None

                    if cat_i is not None and cat_j is not None and cat_i != cat_j:
                        # 跨维度：不合并（经济含义不同）
                        cross_dimension_skipped.append((name_i, name_j, corr_val, cat_i, cat_j))
                        logger.debug(
                            "跨维度保留: %s(%s) vs %s(%s), corr=%.2f (维度不同, 不去重)",
                            name_i,
                            cat_i,
                            name_j,
                            cat_j,
                            corr_val,
                        )
                    else:
                        # 同维度或无分类信息：正常合并
                        high_corr_pairs.append((name_i, name_j, corr_val))
                        union(name_i, name_j)
                        logger.debug("同维度高相关: %s vs %s, corr=%.2f", name_i, name_j, corr_val)

    if cross_dimension_skipped:
        logger.info(
            "维度感知: 跨维度保留 %d 对 (同维度阈值=%.2f, 跨维度不合并)",
            len(cross_dimension_skipped),
            threshold,
        )

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
    corr_matrix: pd.DataFrame | None = None,
    logger: logging.Logger | None = None,
) -> tuple[list[str], dict[str, str]]:
    """从高相关组中选择最优因子

    v2.5 (2026-05-28): 新增 high_corr_pairs 参数，在剔除原因中包含具体相关系数
    v2.9 (2026-06-20): 新增 corr_matrix 参数——Union-Find 传递性归组时，
        被淘汰因子和 best_factor 之间可能没有直接 >threshold 的配对，
        从 corr_matrix 查找实际相关系数补全显示

    保留规则：组内保留 |ICIR| 最高的因子

    Args:
        high_corr_groups: 高相关因子组
        high_corr_pairs: 高相关因子对列表（含相关系数）
        valid_factors: 有效因子数据
        corr_matrix: 因子相关性矩阵（用于查找间接归组因子对的实际 corr）
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
                    # v2.9: corr_lookup 找不到时从 corr_matrix 补全（传递性归组）
                    corr_val = corr_lookup.get((factor_name, best_factor))
                    if (
                        corr_val is None
                        and corr_matrix is not None
                        and factor_name in corr_matrix.index
                        and best_factor in corr_matrix.columns
                    ):
                        corr_val = abs(corr_matrix.loc[factor_name, best_factor])
                    corr_str = (
                        f"corr={corr_val:.2f}" if corr_val is not None and not pd.isna(corr_val) else "传递性归组"
                    )
                    dropped_factors[factor_name] = f"与{best_factor}高相关({corr_str}), icir缺失无法比较"
        else:
            # 找出 ICIR 最高的因子（只比较有 icir 的因子）
            best_factor = max(valid_icir_values.keys(), key=lambda k: valid_icir_values[k])

            # 丢弃其他因子（包括 icir 缺失的因子）
            for factor_name in group:
                # SIM102: 合并嵌套 if（in 检查保证 discard O(1) 安全）
                if factor_name != best_factor and factor_name in selected_factors_set:
                    selected_factors_set.discard(factor_name)

                    # v2.5: 获取相关系数
                    # v2.9: corr_lookup 找不到时从 corr_matrix 补全（传递性归组）
                    corr_val = corr_lookup.get((factor_name, best_factor))
                    if (
                        corr_val is None
                        and corr_matrix is not None
                        and factor_name in corr_matrix.index
                        and best_factor in corr_matrix.columns
                    ):
                        corr_val = abs(corr_matrix.loc[factor_name, best_factor])
                    corr_str = (
                        f"corr={corr_val:.2f}" if corr_val is not None and not pd.isna(corr_val) else "传递性归组"
                    )

                    # 修复：区分 icir 缺失和 ICIR 较低
                    if factor_name in missing_icir_factors:
                        dropped_factors[factor_name] = (
                            f"与{best_factor}高相关({corr_str}), icir缺失({best_factor}|ICIR|={valid_icir_values[best_factor]:.2f})"
                        )
                    else:
                        # v2.6: 修复问题4 - 当 ICIR 相等时显示 '=' 而非 '<'
                        # v2.7: 修复显示精度 - 使用 .3f 避免 0.32<0.32 视觉矛盾
                        # v2.8: 收紧容差至 1e-9 + 显示精度 .4f，
                        #        避免 0.3199 vs 0.3202 差值 0.0003 < 0.001 误判为相等
                        icir_val = icir_values[factor_name]
                        best_icir_val = valid_icir_values[best_factor]
                        # 仅浮点级相等才用 '='（容差 1e-9）
                        icir_cmp = "=" if abs(icir_val - best_icir_val) < 1e-9 else "<"
                        dropped_factors[factor_name] = (
                            f"与{best_factor}高相关({corr_str}), |ICIR|={icir_val:.4f}{icir_cmp}{best_icir_val:.4f}"
                        )

                    logger.info("丢弃高相关因子: %s（保留 %s，ICIR 更高）", factor_name, best_factor)

    # 修复：返回 list 格式（兼容调用方）
    return list(selected_factors_set), dropped_factors


def _compute_dimension_coverage(
    selected_factors: list[str],
    valid_factors: dict[str, dict],
) -> dict:
    """计算选中因子在各维度的覆盖情况

    Args:
        selected_factors: 选中因子列表
        valid_factors: 有效因子数据

    Returns:
        {
            "covered": ["momentum", "price_position", ...],
            "missing": ["volatility", ...],
            "selected_by_dimension": {"momentum": ["rsi", ...], ...},
        }
    """
    if not FACTOR_CATEGORIES:
        return {"covered": [], "missing": [], "selected_by_dimension": {}}

    selected_set = set(selected_factors)
    selected_by_dim: dict[str, list[str]] = {}
    valid_by_dim: dict[str, list[str]] = {}

    for factor_name, dim in FACTOR_CATEGORIES.items():
        if factor_name in valid_factors:
            valid_by_dim.setdefault(dim, []).append(factor_name)
        if factor_name in selected_set:
            selected_by_dim.setdefault(dim, []).append(factor_name)

    covered = sorted(selected_by_dim.keys())
    missing = sorted(set(valid_by_dim.keys()) - set(selected_by_dim.keys()))

    return {
        "covered": covered,
        "missing": missing,
        "selected_by_dimension": selected_by_dim,
    }


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
    3. 识别高相关组（v1.8: 维度感知——同维度 >0.7 去重, 跨维度 >0.9 去重）
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
    exempted_factors = filter_result.get("exempted_factors", {})  # v2.10: 豁免详情

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
        # v2.7: 传入维度分类，启用维度感知去重（同维度合并，跨维度不合并）
        high_corr_groups, high_corr_pairs = identify_high_corr_groups(
            valid_factors=valid_factors,
            corr_matrix=corr_matrix,
            threshold=thresholds["high_corr_threshold"],  # 修复：入口已处理 None，直接使用
            factor_categories=FACTOR_CATEGORIES,
            logger=logger,
        )

        # Step 4: 选择最优因子
        # v2.5: 传入 high_corr_pairs，在原因中包含相关系数
        # v2.9: 传入 corr_matrix，补全传递性归组因子对的实际 corr
        selected_factors, high_corr_dropped = select_best_from_groups(
            high_corr_groups=high_corr_groups,
            high_corr_pairs=high_corr_pairs,
            valid_factors=valid_factors,
            corr_matrix=corr_matrix,
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
        # v2.10: 豁免详情（供报告展示豁免成功/失败原因）
        "exempted_factors": exempted_factors,  # {factor_name: [exempt_detail, ...]}
        # v1.8: 维度覆盖统计（维度感知去重后的覆盖情况）
        "dimension_coverage": _compute_dimension_coverage(selected_factors, valid_factors),
    }

    logger.info("筛选完成: 选中 %d 个因子", len(selected_factors))
    logger.info("选中因子: %s", selected_factors)
    logger.info("对应列名: %s", factor_cols)

    return result
