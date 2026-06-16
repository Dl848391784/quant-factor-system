#!/usr/bin/env python3
"""
资金流占比趋势因子 IC 计算器 - 使用公共模块主入口

遵循 PROJECT.md 公共模块强制复用规范：
- 主流程使用 run_factor_ic()（禁止手写三模式分支）
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
  v1.0.0 (2026-06-12): 初始版本，复用 factor_calculator.calculate_capital_flow_ratio_trend
  v1.1.0 (2026-06-15): 强化结果校验、差异化 warning 提示、启动日志带版本号、摘要逐行输出
  v1.2.0 (2026-06-15): 补 ic_metrics 类型守卫、valid_days 缺失语义化、耗时记录、保留 FactorCalcError 异常链堆栈
  v1.3.0 (2026-06-15): _safe_dict 提到模块级纯函数、补 NaN/Inf 守卫、异常告警分级（ERROR vs CRITICAL）
  v1.4.0 (2026-06-15): _safe_dict/_format_finite/DEFAULT_MIN_STOCKS 抽取至 factor_ic.common.cli_helpers，
                       公共 API 命名去下划线前缀（safe_dict/format_finite），消除跨脚本重复实现
  v1.5.0 (2026-06-15): warning 判定改用 is_finite_value 谓词（解耦表示层 "N/A" 字符串）；
                       positive_ratio 加 [0,1] 量纲范围校验；FactorCalcError 迁至 factor_ic.common.exceptions
  v1.6.0 (2026-06-15): 6项修复：①logger.exception→logger.error+exc_info=True消除语义重复；
                       ②四重校验简化为None+assert（信任公共模块契约）（已由 v1.7.0 ①替换为 if-not-raise）；
                       ③required_columns移除因子输出列capital_flow_ratio_trend；
                       ④start_time移至parse_args前覆盖参数解析；
                       ⑤valid_days改用is_finite_value判定+warning替代"N/A"fallback；
                       ⑥辅助字段加存在性日志区分"字段不存在"与"值为None"（已由 v1.8.0 删除前置 debug 块）
  v1.7.0 (2026-06-16): 6项防御性修复：①三处 assert 替换为 if-not-raise FactorCalcError，
                       避免 -O 模式下契约校验静默失效；②变量 ic_distribution 重命名为
                       ic_distribution_consistency 与字段名/日志名统一；③去除 positive_ratio
                       注释中的硬编码行号 ic_calculator:722，改为契约语义描述；④__main__
                       的 ERROR/CRITICAL 日志补充 factor_name 上下文方便排查；⑤valid_days
                       无效时仅保留 warning，避免与 info 重复输出 N/A；⑥版本历史行格式
                       与 __version__ 三段式语义化版本对齐（vX.Y.Z）
  v1.8.0 (2026-06-16): 5项修复：①docstring run_complex_factor_ic→run_factor_ic 与实际调用对齐；
                       ②/③删除三处前置 if-key-not-in-result debug 块（safe_dict None 路径已静默
                       fallback，前置 debug 与之职责重叠）+ 消除 _has_ic_dist_key 一次性中间变量；
                       ④positive_ratio 量纲越界引入 positive_ratio_range_warned 标志，去除结尾
                       'IC>0 占比无效' 与上方'超出 [0,1] 范围'的双重告警；⑤ic_*/positive_ratio
                       warning 判定块前移到原始值赋值之后、format_finite 之前，附"原始值不再
                       修改"维护约束注释，避免 info 与 warning 跨越多行后值不一致；⑥变量
                       _positive_ratio_range_warned 去下划线前缀（前缀仅留给"临时/单次"局部变量
                       如 _valid_days，状态标志用普通命名以视觉区分用途）
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
from factor_ic.common.factor_ic_runner import run_factor_ic  # noqa: E402
from factor_ic.common.factor_spec import FactorSpec, register_factor  # noqa: E402
from factor_ic.common.logger_config import get_logger  # noqa: E402


logger = get_logger(__name__)

__version__ = "1.8.0"

# ============================================================================
# FactorSpec 声明式注册（遵循 factor_cols_literal_constant_design.md §4.1）
# required_columns: JOIN_KEYS（本因子有 calculation，factor_col 是计算产出而非输入依赖，
# L2 校验已豁免有 calculation 的因子，无需将 factor_col 列入 required_columns）
# ============================================================================

SPEC = register_factor(
    FactorSpec(
        factor_name="capital_flow_ratio_trend",
        factor_col="capital_flow_ratio_trend",
        calculation=calculate_capital_flow_ratio_trend,
        extra_log_params_fn=lambda _a: {"version": __version__},
    )
)


def main():
    """CLI 主入口

    Raises:
        FactorCalcError: 数据加载失败或计算结果结构不完整。
            调用方（CLI 或上层 pipeline）必须自行捕获处理。
    """
    start_time = time.monotonic()
    parser = argparse.ArgumentParser(description="资金流占比趋势因子 IC 计算器")
    parser.add_argument("--force-full", action="store_true", help="强制全量计算")
    parser.add_argument("--min-stocks", type=int, default=DEFAULT_MIN_STOCKS, help="最小股票数")
    args = parser.parse_args()
    # 启动横幅由公共模块 factor_ic_runner 统一打印（含 min_stocks/force_full + extra_log_params）
    # 使用 FactorSpec 驱动入口（遵循 factor_cols_literal_constant_design.md §4.1）
    # 注: 本因子原始数据从外部资金流文件加载（见 factor_calculator._load_fund_flow_data），
    # 缓存中仅需 date/asset 作匹配键（data_loader 会自动去重）。
    result = run_factor_ic(
        spec=SPEC,
        min_stocks=args.min_stocks,
        force_full=args.force_full,
        _logger=logger,
    )

    # 结果校验：显式 if-not-raise FactorCalcError（不用 assert，因为 Python 以 -O
    # 优化模式运行时 assert 语句会被整体跳过，导致类型/结构异常无法被捕获并直接向
    # 下游传播——本因子作为 pipeline 节点必须在所有运行模式下保持契约校验。
    # 公共模块 run_factor_ic 契约保证返回 dict 且含 ic_metrics，但跨版本/跨实现时
    # 仍需边界守卫（depend-on-contract 而非 trust-blindly）。
    if result is None:
        raise FactorCalcError("run_factor_ic 返回 None，数据加载或计算可能失败")
    if not isinstance(result, dict):
        raise FactorCalcError(f"run_factor_ic 返回类型异常: 期望 dict，实际 {type(result).__name__}")
    if "ic_metrics" not in result:
        raise FactorCalcError(f"run_factor_ic 返回结构不完整: 缺少 'ic_metrics' 字段，实际键={list(result.keys())}")
    if not isinstance(result["ic_metrics"], dict):
        raise FactorCalcError(
            f"run_factor_ic 返回结构异常: 'ic_metrics' 期望 dict，实际 {type(result['ic_metrics']).__name__}"
        )
    ic_metrics: dict = result["ic_metrics"]

    # 辅助字段（sample_stats/period/ic_distribution_consistency）允许缺失或为 None，软 fallback 为空 dict。
    # 调用 factor_ic.common.cli_helpers.safe_dict 公共 API，便于跨脚本复用与独立单测。
    # 日志职责：safe_dict 已覆盖结构异常告警——
    #   - 字段缺失（key not in result）→ result.get() 返回 None → safe_dict 静默返回 {}，
    #     业务上"键不存在"与"值为 None"等价（都意味着公共模块未输出该辅助字段），无需区分日志路径；
    #   - 字段值为非 None 非 dict（结构异常）→ safe_dict 用 field_name 定位并打 warning。
    # 因此本处不再前置 `if key not in result: logger.debug(...)`：前置 debug 块与 safe_dict
    # 在"None / 缺失"场景会形成两条职责重叠的日志记录（debug + 静默 / debug + warning），
    # 且 _has_<x>_key 这类布尔中间变量仅供单次 if 判断使用，徒增阅读噪声。
    sample_stats = safe_dict(result.get("sample_stats"), field_name="sample_stats", logger=logger)
    period = safe_dict(result.get("period"), field_name="period", logger=logger)
    ic_distribution_consistency = safe_dict(
        result.get("ic_distribution_consistency"),
        field_name="ic_distribution_consistency",
        logger=logger,
    )

    ic_mean = ic_metrics.get("ic_mean")
    ic_std = ic_metrics.get("ic_std")
    icir = ic_metrics.get("icir")
    positive_ratio = ic_distribution_consistency.get("positive_ratio")

    # positive_ratio 量纲约定（契约语义：factor_ic.common.ic_calculator 内部以
    # `positive_ratio = positive_count / n` 形式定义，n 为有效 IC 截面数）：
    # 必须为 [0, 1] 之间的小数。此处作防御性范围校验：若公共模块契约变更
    # （误返回 0–100 整数百分比），`.2%` 格式化结果会变成 "5230.00%" 等明显错误值
    # 且无任何告警。落在 [0, 1] 之外时降级为 None，让下方 format_finite/is_finite_value
    # 链触发统一的"无效"warning，避免静默错误。
    # 注：故意不引用源码行号，行号会随代码演进失效成为误导性硬编码文档；契约是
    # "比例=正向计数/总数 ∈ [0,1]"，这一语义稳定，行号不稳定。
    # 量纲越界标志：用于结尾 warning 块去重。量纲越界时本块已打过一条针对性 warning
    # （描述"超出 [0, 1] 范围"），若结尾 warning 块再触发"IC>0 占比无效"则形成两条
    # 描述同一事件的 warning 且语义互相掩盖。
    # 命名说明：函数内局部状态标志，无下划线前缀（_xxx 在本项目仅用于"临时/单次判定后
    # 即丢弃"的局部变量，如 _valid_days；状态标志跨多处读写，应使用普通命名以与
    # "临时变量"在视觉上区分开）。
    positive_ratio_range_warned = False
    if is_finite_value(positive_ratio) and not (0.0 <= positive_ratio <= 1.0):
        logger.warning(
            "positive_ratio=%s 超出预期范围 [0, 1]，可能是公共模块返回量纲变更（应为 0–1 小数）；本次摘要按 'N/A' 处理",
            positive_ratio,
        )
        positive_ratio = None
        positive_ratio_range_warned = True

    # ========================================================================
    # 字段级差异化 warning 集中判定（紧跟原始值赋值之后、format_finite 之前）
    # ========================================================================
    # 设计要点（修复用户报告 #4）：warning 判定基于原始值（ic_mean / ic_std / icir /
    # positive_ratio），必须与原始值赋值物理相邻，避免与下方摘要 info 块跨越多行后
    # 出现"info 输出修改前的值、warning 判定修改后的值"的静默不一致。
    #
    # ⚠️ 维护约束：本块之后到 format_finite 调用之间，禁止再修改这四个原始值变量。
    # 唯一已知的例外是上方 positive_ratio 量纲越界 → None 的赋值（已在 warning 前完成
    # 并设置 positive_ratio_range_warned 标志，故本块的 positive_ratio 判定基于"已修正"
    # 的值，与去重标志配合避免重复告警）。
    #
    # 用 is_finite_value 谓词基于原始值判定（None/NaN/±Inf/非数/bool 均视为无效），
    # 避免 warning 依赖 format_finite 的字符串 fallback（"N/A"）—— 若公共模块表示层
    # 字符串改动，业务告警不会失效。
    if not is_finite_value(ic_mean):
        logger.warning("本次计算 IC 均值无效（None/NaN/Inf）：因子-收益对齐后样本不足或全部 NaN，请检查数据源覆盖范围")
    if not is_finite_value(ic_std):
        logger.warning("IC 标准差无效（None/NaN/Inf）：因子值方差为零（全部相同）或截面样本不足，请检查因子计算逻辑")
    if not is_finite_value(icir):
        logger.warning("ICIR 无效（None/NaN/Inf）：IC 标准差为零导致除零，或 IC 序列长度不足，请检查回测窗口")
    if not is_finite_value(positive_ratio) and not positive_ratio_range_warned:
        # 仅当 positive_ratio 因"非量纲越界"原因（None/NaN/Inf/字段缺失）变成 None 时
        # 才触发本通用 warning；量纲越界场景已在上方打过更精确的 warning，此处跳过避免重复。
        logger.warning(
            "IC>0 占比无效（None/NaN/Inf）：公共模块未输出 ic_distribution_consistency 字段或值非有限，请核对模块版本"
        )

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
    logger.info("因子名称: %s", result.get("factor_name", "unknown"))
    logger.info("更新模式: %s", result.get("update_mode", "unknown"))
    logger.info("日期范围: %s ~ %s", period.get("start", "N/A"), period.get("end", "N/A"))
    # valid_days 使用 is_finite_value 判定，与其他字段保持一致的语义化缺失检测，
    # 避免字符串 fallback "N/A" 使缺失检测形同虚设。
    # 输出策略二选一（不重复输出）：
    # - 无效时：仅打 warning，附带 "无效"原因，不再重复输出 N/A info 行（避免结构化
    #   日志系统中两条描述同一字段的记录污染告警）。
    # - 有效时：仅打 info "有效天数: <值> 天"，正常摘要行。
    _valid_days = sample_stats.get("valid_days")
    if not is_finite_value(_valid_days):
        logger.warning("有效天数缺失或无效（None/NaN/Inf）：摘要中略过该字段，请检查 sample_stats 数据完整性")
    else:
        logger.info("有效天数: %s 天", format_finite(_valid_days, ".0f"))
    logger.info("--- IC指标 ---")
    logger.info("IC 均值: %s", ic_mean_str)
    logger.info("IC 标准差: %s", ic_std_str)
    logger.info("ICIR: %s", icir_str)
    logger.info("IC>0 占比: %s", positive_ratio_str)

    elapsed = time.monotonic() - start_time
    logger.info("资金流占比趋势因子IC计算完成: elapsed=%.2fs", elapsed)
    return result


if __name__ == "__main__":
    try:
        main()
    except FactorCalcError:
        # 业务预期异常（数据缺失/结构异常）：用 logger.error + exc_info=True 保留 cause 链
        # （__cause__ / __context__）但级别 ERROR，便于运维监控按场景配置告警阈值，
        # 与下方 CRITICAL 的程序 bug 噪声等级区分。
        # 日志附带 factor_name + version：运维从聚合日志能直接定位是哪个因子、哪个版本失败，
        # 避免在多因子 pipeline 并发跑时出现"某个因子挂了但不知道是哪个"的盲区。
        logger.error(  # noqa: G201
            "因子IC计算失败（业务异常）: factor_name=%s, version=%s",
            SPEC.factor_name,
            __version__,
            exc_info=True,
        )
        sys.exit(1)
    except Exception:
        # 未预期异常（程序 bug / 外部依赖崩溃）：用 logger.critical 升级告警级别。
        # 注：未与 FactorCalcError 合并，因二者告警分级不同（ERROR vs CRITICAL）。
        # 同样附带 factor_name + version 上下文，便于线上排查。
        logger.critical(
            "因子IC计算遇到未预期错误: factor_name=%s, version=%s",
            SPEC.factor_name,
            __version__,
            exc_info=True,
        )
        sys.exit(1)
