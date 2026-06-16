#!/usr/bin/env python3
"""
行业振幅趋势因子 IC 计算器 - 使用公共模块主入口

遵循 PROJECT.md 公共模块强制复用规范：
- 主流程使用 run_factor_ic()（FactorSpec 驱动入口，禁止手写三模式分支；
  factor_ic_runner.py L433 推荐入口，替代 run_simple_factor_ic / run_complex_factor_ic）
- 因子计算逻辑复用 data_fetchers.factor_calculator（遵循 MODULE.md 约束 #3）

因子定义：
- industry_amplitude_trend = amplitude_avg(t) / amplitude_avg(t-1) - 1
- 含义：行业振幅变化趋势，方向性因子
- 遵循 H5: IC方向不预判，由数据决定

边界处理：
- industry 未知 → 赋 '其他'
- amplitude_avg(t-1) 极小 → clip(lower=0.001) 避免极端比值（遵循 Pitfall #47）

作者: 云瑶
创建日期: 2026-06-12
版本历史:
  v1.0 (2026-06-12): 初始版本，复用 factor_calculator.calculate_industry_amplitude_trend
"""

import argparse
import sys

from data_fetchers.factor_calculator import calculate_industry_amplitude_trend
from factor_ic.common.cli_helpers import DEFAULT_MIN_STOCKS
from factor_ic.common.exceptions import DataSchemaError, FactorCalcError
from factor_ic.common.factor_ic_runner import run_factor_ic
from factor_ic.common.factor_spec import FactorSpec, register_factor
from factor_ic.common.factor_summary_logger import log_factor_summary
from factor_ic.common.logger_config import get_logger


logger = get_logger(__name__)

# ============================================================================
# FactorSpec 声明式注册（遵循 factor_cols_literal_constant_design.md §4.1）
# ============================================================================

SPEC = register_factor(
    FactorSpec(
        factor_name="industry_amplitude_trend",
        factor_col="industry_amplitude_trend",
        # required_columns 缺省说明（遵循 factor_spec.py v1.1 §3.1 方案 3-A）：
        # 1. FactorSpec.required_columns 为可选字段（factor_spec.py L63: tuple[str, ...] | None = None）。
        # 2. 缺省时由 __post_init__ 自动派生：读取 calculation.required_cols 属性
        #    （factor_spec.py L72；本因子已验证 calculate_industry_amplitude_trend.required_cols
        #    = ['date', 'asset', 'amplitude']）。
        # 3. 因此本处省略 required_columns 是合规的，等价于显式声明
        #    required_columns=JOIN_KEYS + ("amplitude",)；产出列 industry_amplitude_trend
        #    不属于输入依赖（factor_spec.py L98-102: 有 calculation 时 factor_col 是计算产出）。
        calculation=calculate_industry_amplitude_trend,
    )
)


def main():
    """CLI 主入口"""
    parser = argparse.ArgumentParser(description="行业振幅趋势因子 IC 计算器")
    parser.add_argument("--force-full", action="store_true", help="强制全量计算")
    parser.add_argument("--min-stocks", type=int, default=DEFAULT_MIN_STOCKS, help="最小股票数")
    args = parser.parse_args()

    # 启动横幅由公共模块 factor_ic_runner 统一打印（含 min_stocks/force_full）
    # 本地启动参数日志：补充模块日志流可追溯入参（与公共横幅互补）
    # 布尔格式说明：force_full=%s 沿用 Python bool 默认字符串化（True/False），
    # 与公共模块 factor_ic_runner.py:137 的 "入口参数: min_stocks=%s, force_full=%s"
    # 完全一致，保持项目内布尔日志检索语法统一（grep "force_full=True" 可同时
    # 命中本模块与公共模块）。此处不切换为 yes/no 或 1/0 风格是有意为之。
    logger.info(
        "启动 run_factor_ic: factor=%s min_stocks=%d force_full=%s",
        SPEC.factor_name,
        args.min_stocks,
        args.force_full,
    )
    result = run_factor_ic(
        spec=SPEC,
        min_stocks=args.min_stocks,
        force_full=args.force_full,
        _logger=logger,
    )

    # debug 级中间状态日志：debug 模式下对 result 关键字段做细粒度追踪，
    # 不污染生产 INFO 日志（生产摘要由 log_factor_summary 唯一输出）。
    # 关键字段选取理由：
    #   - factor_name / update_mode：定位本次运行身份
    #   - period.start ~ period.end：确认数据窗口
    #   - sample_stats.valid_days：判断是否走了 build_error_result 兜底（valid_days=0）
    #   - ic_metrics.ic_mean / icir：核心 IC 指标，便于排查异常返回结构
    # 防御性守卫：虽然 run_factor_ic 返回类型注解为 dict[str, Any]
    # （factor_ic_runner.py L442），但 debug 字段提取与"返回必为 dict"假设解耦——
    # 若上游契约被破坏（返回 None 或非 dict），此处不抛 AttributeError 干扰失败路径，
    # 而是降级为单条 warning，把后续 log_factor_summary / 异常处理留给主流程。
    if isinstance(result, dict):
        ic_metrics = result.get("ic_metrics") or {}
        sample_stats = result.get("sample_stats") or {}
        period = result.get("period") or {}
        logger.debug(
            "run_factor_ic 返回: factor=%s update_mode=%s period=%s~%s valid_days=%s ic_mean=%s icir=%s",
            result.get("factor_name"),
            result.get("update_mode"),
            period.get("start"),
            period.get("end"),
            sample_stats.get("valid_days"),
            ic_metrics.get("ic_mean"),
            ic_metrics.get("icir"),
        )
    else:
        logger.warning(
            "run_factor_ic 返回非 dict 类型 (type=%s)，跳过 debug 字段追踪",
            type(result).__name__,
        )
    # 包裹 log_factor_summary：摘要层失败 → sys.exit(3) 显式辅助层失败信号
    # （PROJECT.md H12 R17）。因子计算 result 已成功生成，主结果产物可用，下游
    # backtest/comprehensive/summary 可正常消费；仅旁路日志摘要失败时返回 exit 3，
    # 与业务失败（exit 1）和 import-time 注册失败（exit 2）严格区分。
    try:
        log_factor_summary(result, "行业振幅趋势因子", logger)
    except Exception:
        logger.exception(
            "log_factor_summary 摘要输出阶段失败（因子计算 result 已成功生成；"
            "故障源 = 摘要日志层而非 run_factor_ic 业务路径）"
        )
        sys.exit(3)  # H12 R17：辅助层失败专用退出码

    return result


if __name__ == "__main__":
    # 异常分支顺序依据（exceptions.py L27/L46 已确认）：
    # - DataSchemaError(Exception) 与 FactorCalcError(Exception) 均直接继承 Exception，
    #   两者是【平级关系，无父子继承】（exceptions.py L60 注释也明确"与 FactorCalcError 并列"）。
    # - 因此 DataSchemaError ↔ FactorCalcError 的捕获顺序在异常匹配上等价，无主次之分。
    # - 当前先 DataSchemaError 后 FactorCalcError 的顺序仅为可读性约定（按错误来源远近排序：
    #   schema 失败发生在数据加载阶段（最早），因子计算失败发生在加载之后），
    #   未来调整顺序不会改变捕获语义。
    # - 通用 Exception 必须放最后，作为非业务异常的兜底（程序 bug → CRITICAL 告警语义）。
    try:
        main()
    except DataSchemaError as e:
        # run_factor_ic 文档（factor_ic_runner.py L460-461）声明 required_columns 与
        # 数据源列不匹配时抛 DataSchemaError；单独捕获以保留 schema 失败的明确语义，
        # 避免落入通用 Exception 分支后丢失"列依赖不匹配"这一关键上下文。
        logger.error("行业振幅趋势因子IC计算失败 (数据列依赖不匹配): %s", e)
        sys.exit(1)
    except FactorCalcError as e:
        logger.error("行业振幅趋势因子IC计算失败: %s", e)
        sys.exit(1)
    except Exception:
        logger.exception("未预期的错误")
        sys.exit(1)
