#!/usr/bin/env python3
"""
资金流占比趋势因子 IC 计算器 - 使用公共模块主入口

遵循 PROJECT.md 公共模块强制复用规范：
- 主流程使用 run_complex_factor_ic()（禁止手写三模式分支）
- 因子计算逻辑复用 data_fetchers.factor_calculator（遵循 MODULE.md 约束 #3）

因子定义：
- capital_flow_ratio_trend = 行业Δ主力净流入占比赋个股（主力净流入占比日间变化量，行业聚合赋给同行业每只股票）
- 含义：行业资金流向趋势变化，方向性因子
- 遵循 H5: IC方向不预判，由数据决定

⚠️ 数据覆盖限制: 每只股票约120交易日（API限制），超过此范围的日期 → NaN
- 因子覆盖率约26%（仅近6个月有数据）

边界处理：
- industry 未知 → 赋 '其他' 行业
- 资金流数据缺失 → Δratio 为 NaN
- Δratio 首日无前值 → NaN

异常契约：
- main() 直接抛出 FactorCalcError（数据/计算失败）；调用方负责捕获。
  CLI 入口 __main__ 块统一捕获并 sys.exit(1)。

作者: 云瑶
创建日期: 2026-06-12
版本历史:
  v1.0 (2026-06-12): 初始版本，复用 factor_calculator.calculate_capital_flow_ratio_trend
  v1.1 (2026-06-15): 强化结果校验、差异化 warning 提示、启动日志带版本号、摘要逐行输出
  v1.2 (2026-06-15): 补 ic_metrics 类型守卫、valid_days 缺失语义化、耗时记录、保留 FactorCalcError 异常链堆栈
  v1.3 (2026-06-15): _safe_dict 提到模块级纯函数、补 NaN/Inf 守卫、异常告警分级（ERROR vs CRITICAL）
  v1.4 (2026-06-15): _safe_dict/_format_finite/DEFAULT_MIN_STOCKS 抽取至 factor_ic.common.cli_helpers，
                     公共 API 命名去下划线前缀（safe_dict/format_finite），消除跨脚本重复实现
  v1.5 (2026-06-15): warning 判定改用 is_finite_value 谓词（解耦表示层 "N/A" 字符串）；
                     positive_ratio 加 [0,1] 量纲范围校验；FactorCalcError 迁至 factor_ic.common.exceptions
"""

import argparse
import sys
import time
from pathlib import Path


sys.path.insert(0, str(Path(__file__).parent.parent))  # noqa: E402

from data_fetchers.factor_calculator import calculate_capital_flow_ratio_trend  # noqa: E402
from factor_ic.common.cli_helpers import (  # noqa: E402
    DEFAULT_MIN_STOCKS,
    format_finite,
    is_finite_value,
    safe_dict,
)
from factor_ic.common.exceptions import FactorCalcError  # noqa: E402
from factor_ic.common.factor_ic_runner import run_complex_factor_ic  # noqa: E402
from factor_ic.common.logger_config import get_logger  # noqa: E402


logger = get_logger(__name__)

__version__ = "1.5.0"


def main():
    """CLI 主入口

    Raises:
        FactorCalcError: 数据加载失败或计算结果结构不完整。
            调用方（CLI 或上层 pipeline）必须自行捕获处理。
    """
    parser = argparse.ArgumentParser(description="资金流占比趋势因子 IC 计算器")
    parser.add_argument("--force-full", action="store_true", help="强制全量计算")
    parser.add_argument("--min-stocks", type=int, default=DEFAULT_MIN_STOCKS, help="最小股票数")
    args = parser.parse_args()

    start_time = time.monotonic()
    logger.info(
        f"启动资金流占比趋势因子IC计算 v{__version__}: min_stocks={args.min_stocks}, force_full={args.force_full}"
    )

    # 注: factor_cols 在公共模块语义为"需从缓存加载的原始因子列"。
    # 本因子原始数据从外部资金流文件加载（见 factor_calculator._load_fund_flow_data），
    # 缓存中仅需 date/asset 作匹配键，因此传 ["date", "asset"]（data_loader 会自动去重）。
    # TODO: 公共模块 API 重命名（factor_cols → load_cols）作为独立任务跨 8 个调用点统一处理。
    result = run_complex_factor_ic(
        factor_name="capital_flow_ratio_trend",
        factor_col="capital_flow_ratio_trend",
        factor_cols=["date", "asset"],
        custom_factor_calculation=calculate_capital_flow_ratio_trend,
        min_stocks=args.min_stocks,
        force_full=args.force_full,
        _logger=logger,
    )

    # 强化结果校验：覆盖 None / 非 dict / 缺关键字段 / 关键字段类型异常 四种失败场景，
    # 避免后续 .get() 链静默掩盖真实错误或在非 dict 值上抛 AttributeError。
    if result is None:
        raise FactorCalcError("run_complex_factor_ic 返回 None，数据加载或计算可能失败")
    if not isinstance(result, dict):
        raise FactorCalcError(f"run_complex_factor_ic 返回类型异常: 期望 dict，实际 {type(result).__name__}")
    if "ic_metrics" not in result:
        raise FactorCalcError(
            f"run_complex_factor_ic 返回结构不完整: 缺少 'ic_metrics' 字段，实际键={list(result.keys())}"
        )
    # ic_metrics 是关键字段，类型必须严格 dict（含禁止 None），任何偏差立即抛错
    _ic_metrics_value = result["ic_metrics"]
    if not isinstance(_ic_metrics_value, dict):
        raise FactorCalcError(
            f"run_complex_factor_ic 返回结构异常: 'ic_metrics' 期望 dict，实际 {type(_ic_metrics_value).__name__}"
        )
    ic_metrics: dict = _ic_metrics_value

    # 辅助字段（sample_stats/period/ic_distribution）允许缺失或为 None，软 fallback 为空 dict。
    # 调用 factor_ic.common.cli_helpers.safe_dict 公共 API，便于跨脚本复用与独立单测。
    sample_stats = safe_dict(result.get("sample_stats"), field_name="sample_stats", logger=logger)
    period = safe_dict(result.get("period"), field_name="period", logger=logger)
    ic_distribution = safe_dict(
        result.get("ic_distribution_consistency"),
        field_name="ic_distribution_consistency",
        logger=logger,
    )

    ic_mean = ic_metrics.get("ic_mean")
    ic_std = ic_metrics.get("ic_std")
    icir = ic_metrics.get("icir")
    positive_ratio = ic_distribution.get("positive_ratio")

    # positive_ratio 量纲约定（来源: factor_ic.common.ic_calculator:722
    # `positive_ratio = positive_count / n`）：必须为 [0, 1] 之间的小数。
    # 此处作防御性范围校验：若公共模块契约变更（误返回 0–100 整数百分比），
    # `.2%` 格式化结果会变成 "5230.00%" 等明显错误值且无任何告警。
    # 落在 [0, 1] 之外时降级为 None，让下方 format_finite/is_finite_value 链
    # 触发统一的"无效"warning，避免静默错误。
    if is_finite_value(positive_ratio) and not (0.0 <= positive_ratio <= 1.0):
        logger.warning(
            f"positive_ratio={positive_ratio} 超出预期范围 [0, 1]，"
            "可能是公共模块返回量纲变更（应为 0–1 小数）；本次摘要按 'N/A' 处理"
        )
        positive_ratio = None

    # 格式化前用 format_finite 统一守卫 None / NaN / Inf：
    # 公共模块在样本不足或除零时可能返回 float('nan')/float('inf')，
    # 直接 f-string 会输出 'nan'/'inf' 字面量污染摘要日志和下游消费者。
    ic_mean_str = format_finite(ic_mean, ".4f")
    ic_std_str = format_finite(ic_std, ".4f")
    icir_str = format_finite(icir, ".2f")
    positive_ratio_str = format_finite(positive_ratio, ".2%")

    # 摘要逐行输出，避免单条多行字符串在结构化日志系统中造成字段污染。
    logger.info("=" * 60)
    logger.info("结果摘要")
    logger.info("=" * 60)
    logger.info(f"因子名称: {result.get('factor_name', 'unknown')}")
    logger.info(f"更新模式: {result.get('update_mode', 'unknown')}")
    logger.info(f"日期范围: {period.get('start', 'N/A')} ~ {period.get('end', 'N/A')}")
    logger.info(f"有效天数: {sample_stats.get('valid_days', 'N/A')} 天")
    logger.info("--- IC指标 ---")
    logger.info(f"IC 均值: {ic_mean_str}")
    logger.info(f"IC 标准差: {ic_std_str}")
    logger.info(f"ICIR: {icir_str}")
    logger.info(f"IC>0 占比: {positive_ratio_str}")

    # 字段级差异化提示，提升运维可观测性。
    # 用 is_finite_value 谓词基于原始值判定（None/NaN/±Inf/非数/bool 均视为无效），
    # 避免 warning 依赖 format_finite 的字符串 fallback（"N/A"）—— 若公共模块表示层
    # 字符串改动，业务告警不会失效。
    if not is_finite_value(ic_mean):
        logger.warning("本次计算 IC 均值无效（None/NaN/Inf）：因子-收益对齐后样本不足或全部 NaN，请检查数据源覆盖范围")
    if not is_finite_value(ic_std):
        logger.warning("IC 标准差无效（None/NaN/Inf）：因子值方差为零（全部相同）或截面样本不足，请检查因子计算逻辑")
    if not is_finite_value(icir):
        logger.warning("ICIR 无效（None/NaN/Inf）：IC 标准差为零导致除零，或 IC 序列长度不足，请检查回测窗口")
    if not is_finite_value(positive_ratio):
        logger.warning(
            "IC>0 占比无效（None/NaN/Inf 或量纲越界）：公共模块未输出 ic_distribution_consistency 字段、"
            "值非有限，或返回值不在预期 [0, 1] 范围内（详见上文 positive_ratio 范围校验日志），请核对模块版本"
        )

    elapsed = time.monotonic() - start_time
    logger.info(f"资金流占比趋势因子IC计算完成: elapsed={elapsed:.2f}s")
    return result


if __name__ == "__main__":
    try:
        main()
    except FactorCalcError:
        # 业务预期异常（数据缺失/结构异常）：用 logger.error + exc_info=True 保留 cause 链
        # （__cause__ / __context__）但级别 ERROR，便于运维监控按场景配置告警阈值，
        # 与下方 CRITICAL 的程序 bug 噪声等级区分。
        logger.error("资金流占比趋势因子IC计算失败（业务异常）", exc_info=True)
        sys.exit(1)
    except Exception:
        # 未预期异常（程序 bug / 外部依赖崩溃）：用 logger.critical 升级告警级别。
        # 注：未与 FactorCalcError 合并，因二者告警分级不同（ERROR vs CRITICAL）。
        logger.critical("资金流占比趋势因子IC计算遇到未预期错误", exc_info=True)
        sys.exit(1)
