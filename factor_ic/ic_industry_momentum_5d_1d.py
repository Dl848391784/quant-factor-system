#!/usr/bin/env python3
"""
行业5日动量因子 IC 计算器 - 使用公共模块主入口

遵循 PROJECT.md 公共模块强制复用规范：
- 主流程使用 run_factor_ic()（FactorSpec 驱动统一入口，已替代 run_simple/run_complex；
  详见 factor_ic/MODULE.md L551 / L572：禁止继续使用 run_complex_factor_ic，34 脚本已迁移）
- 因子计算逻辑复用 data_fetchers.factor_calculator（遵循 MODULE.md 约束 #3）

因子定义：
- industry_momentum_5d = 按(行业,日期)分组 → mean(past_return_1d) → 5日滚动均值
- 含义：行业整体5日趋势方向，方向性因子
- 遵循 H5: IC方向不预判，由数据决定
- 实测结论: 行业层面IC=+0.026（正值），方向性信号存在于行业而非个股

边界处理：
- industry 未知 → 赋 '其他' 行业
- 行业股票数 < 5 → 该日期该行业因子值 NaN
- past_return_1d 为 NaN → 行业均值自动跳过

作者: 云瑶
创建日期: 2026-06-12
版本历史:
  v1.0 (2026-06-12): 初始版本，复用 factor_calculator.calculate_industry_momentum_5d
"""

import argparse
import sys

from data_fetchers.factor_calculator import calculate_industry_momentum_5d
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

try:
    SPEC = register_factor(
        FactorSpec(
            factor_name="industry_momentum_5d",
            factor_col="industry_momentum_5d",
            calculation=calculate_industry_momentum_5d,
        )
    )
except (ValueError, TypeError) as e:
    # 模块顶层注册失败兜底（R17 同步迁移）：
    # - register_factor 抛 ValueError（factor_spec.py:117-119：重复注册、列名非法等）
    # - TypeError 防御 FactorSpec dataclass 构造期类型错误
    # - R17 改为 logger.critical + raise（详见 PROJECT.md H12 R16 修正版）：
    #   importlib.import_module 在 test_factor_spec_consistency.py 中扫描所有 ic_*.py
    #   触发 SPEC 注册，sys.exit 会杀掉 pytest 宿主；raise 让调用方决定行为。
    # 截断策略（消除中间变量 + 固定截断标记）：
    # - str(e)[:200] 直接内联到 logger 实参，不再走 err_msg 中间变量；
    # - 格式串中固定追加 "(truncated to <=200 chars)" 标记声明截断上限，
    #   显式告知阅读者本字段可能被截断，避免静默信息丢失；
    # - 完整异常对象由下方 raise 携带 traceback 向上传播（CLI 块 logger.exception 输出）。
    logger.critical(
        "FactorSpec 注册失败 (factor=industry_momentum_5d): %s (%s) (truncated to <=200 chars)",
        str(e)[:200],
        type(e).__name__,
    )
    raise


def main():
    """CLI 主入口"""
    parser = argparse.ArgumentParser(description="行业5日动量因子 IC 计算器")
    parser.add_argument("--force-full", action="store_true", help="强制全量计算")
    parser.add_argument("--min-stocks", type=int, default=DEFAULT_MIN_STOCKS, help="最小股票数")
    args = parser.parse_args()

    # 启动横幅由公共模块 factor_ic_runner 统一打印（含 min_stocks/force_full）。
    # 本地启动参数日志（issue 5：消除"启动上下文唯一记录点在公共模块"的可观测性盲区）：
    # 公共模块横幅若被日志级别过滤、或公共模块实现回归不再打印参数，本模块原本将无任何
    # 启动上下文落盘。此处冗余但低成本：模块自身 logger 输出一行 INFO，
    # 把实际生效的 min_stocks / force_full 锁定到本模块日志文件，与公共横幅互补。
    # 布尔格式说明：force_full=%s 沿用 Python bool 默认字符串化（True/False），
    # 与公共模块 factor_ic_runner.py 启动行 "入口参数: min_stocks=%s, force_full=%s"
    # 完全一致，保持项目内布尔日志检索语法统一（grep "force_full=True" 可同时
    # 命中本模块与公共模块），不切换为 yes/no 或 1/0 风格是有意为之
    # （对齐 ic_industry_amplitude_trend_1d.py 同位修复）。
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

    # 输出 IC 摘要（公共模块,M3.1）
    # 注：run_factor_ic 失败路径走 build_error_result（返回 dict）或抛 DataSchemaError，
    # 永不返回 None；冗余的 result is None 兜底掩盖真实错误来源（违反 dead-code skill
    # 模式 E：防御 is None 兜底面对永不返回 None 的函数），已彻底移除。
    # log_factor_summary 自身契约（factor_summary_logger.py L40-44）：不抛异常、不调用
    # sys.exit、不影响调用方控制流；其内部对 dict 字段为 None 的异常情况输出整合告警
    # （L83-92），无需调用方额外守卫业务语义。
    #
    # 错误来源区分（issue 4：契约依赖注释而非代码强制）：
    # 一旦摘要层未来回归并抛异常，__main__ 块的通用 except Exception 会输出
    # "未预期的错误"，此时无法分辨故障源是因子计算（main 中段）还是日志摘要（main 末段）。
    # 在此独立 try/except 包裹：
    # - 摘要层异常打印明确前缀 "log_factor_summary 摘要输出阶段失败"，便于一眼定位；
    # - 用 sys.exit(3) 显式标记辅助层失败（PROJECT.md H12 R17 退出码档）：
    #   * 因子计算 result 已成功生成，主结果产物（factor_ic/result/）可用，
    #     下游 backtest / comprehensive_factor / summary 可正常消费；
    #   * 仅旁路日志摘要输出失败 → exit 3 与业务失败（exit 1，主结果不可用）和
    #     import-time 注册失败（exit 2，代码不能加载）严格区分，调度器可据此降级告警；
    #   * 不静默吞异常（先前 issue：仅 logger 不 sys.exit → 进程 exit 0，
    #     调度器把"摘要层失败"误判为"完全成功"，告警丢失）。
    # - 同时输出完整 traceback（logger.exception）保留调试信息。
    try:
        log_factor_summary(result, "行业5日动量因子", logger)
    except Exception:
        logger.exception(
            "log_factor_summary 摘要输出阶段失败（因子计算 result 已成功生成；"
            "故障源 = 摘要日志层而非 run_factor_ic 业务路径）"
        )
        sys.exit(3)  # H12 R17：辅助层失败专用退出码，与 exit 1/2 严格区分


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
        logger.error("行业5日动量因子IC计算失败 (数据列依赖不匹配): %s", e)
        sys.exit(1)
    except FactorCalcError as e:
        logger.error("行业5日动量因子IC计算失败: %s", e)
        sys.exit(1)
    except Exception:
        logger.exception("未预期的错误")
        sys.exit(1)
