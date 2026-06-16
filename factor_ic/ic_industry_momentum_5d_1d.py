#!/usr/bin/env python3
"""
行业5日动量因子 IC 计算器 - 使用公共模块主入口

遵循 PROJECT.md 公共模块强制复用规范：
- 主流程使用 run_factor_ic()（FactorSpec 驱动统一入口，已替代 run_simple/run_complex；
  详见 factor_ic/MODULE.md：禁止继续使用 run_complex_factor_ic，全部脚本已迁移）
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
from factor_ic.common.exceptions import DataSchemaError, FactorCalcError, SummaryLogError
from factor_ic.common.factor_ic_runner import run_factor_ic
from factor_ic.common.factor_spec import FactorSpec, SpecRegistrationError, register_factor
from factor_ic.common.factor_summary_logger import log_factor_summary
from factor_ic.common.logger_config import get_logger


logger = get_logger(__name__)

# ============================================================================
# FactorSpec 声明式注册（遵循 factor_cols_literal_constant_design.md §4.1）
# ============================================================================

_FACTOR_NAME = "industry_momentum_5d"

try:
    SPEC = register_factor(
        FactorSpec(
            factor_name=_FACTOR_NAME,
            factor_col=_FACTOR_NAME,
            calculation=calculate_industry_momentum_5d,
        )
    )
except SpecRegistrationError as e:
    # 模块顶层注册失败兜底：
    # - register_factor 抛 SpecRegistrationError（重复注册、列名非法等 ValueError 与
    #   dataclass 构造期 TypeError 由公共包装层统一为 SpecRegistrationError）。
    # - logger.critical 显式带 factor=%s 字段（issue 2）：异常对象内虽含 factor_name
    #   上下文，但格式串本身原先无 factor 字段，日志聚合按字段查询会漏掉本行；
    #   显式落盘 factor=%s 后，grep "factor=industry_momentum_5d.*注册失败" 可直接命中。
    # - 退出策略：logger.critical + raise，不 sys.exit（test_factor_spec_consistency.py
    #   通过 importlib.import_module 扫描所有 ic_*.py 触发 SPEC 注册，sys.exit 会杀
    #   pytest 宿主；raise 让调用方决定行为）。
    # - 向上传播的异常类型（供调用方文档参考，issue 2）：
    #     SpecRegistrationError(ValueError) —— 即调用方既可 except SpecRegistrationError
    #     精确捕获，也可 except ValueError 宽口径捕获。__main__ 块的 except Exception
    #     兜底分支会落盘 logger.exception 完整堆栈。
    # - 截断策略：str(e)[:200] 直接内联到 logger 实参，格式串中固定追加
    #   "(truncated to <=200 chars)" 显式告知阅读者本字段可能被截断；完整异常对象由
    #   下方 raise 携带 traceback 向上传播。
    logger.critical(
        "FactorSpec 注册失败: factor=%s 错误: %s (truncated to <=200 chars)",
        _FACTOR_NAME,
        str(e)[:200],
    )
    raise


def parse_args() -> argparse.Namespace:
    """CLI 参数解析（R20 拆分：与 main 编排逻辑解耦，便于 main(args) 单元测试调用）。"""
    parser = argparse.ArgumentParser(description="行业5日动量因子 IC 计算器")
    parser.add_argument("--force-full", action="store_true", help="强制全量计算")
    parser.add_argument("--min-stocks", type=int, default=DEFAULT_MIN_STOCKS, help="最小股票数")
    return parser.parse_args()


def main(args: argparse.Namespace) -> dict:
    """流程编排：抛异常但不退出（R20：禁 sys.exit，退出码由 __main__ 块统一处理）。

    raises:
        DataSchemaError: 数据列契约不匹配（→ __main__ 退出码 4，R18）
        FactorCalcError: 因子计算内部失败（→ __main__ 退出码 5，R19）
        SummaryLogError: 摘要日志层失败（→ __main__ 退出码 3，R17；result 已生成）
    """
    # 启动横幅由公共模块 factor_ic_runner 统一打印（含 min_stocks/force_full）。
    # 本地启动参数日志（issue 5：消除"启动上下文唯一记录点在公共模块"的可观测性盲区）：
    # 公共模块横幅若被日志级别过滤、或公共模块实现回归不再打印参数，本模块原本将无任何
    # 启动上下文落盘。此处冗余但低成本：模块自身 logger 输出一行 INFO，
    # 把实际生效的 min_stocks / force_full 锁定到本模块日志文件，与公共横幅互补。
    # 格式说明：min_stocks=%s 与 force_full=%s 全部使用 %s（issue 4）：
    # - argparse type=int 在 CLI 路径会做类型转换，但单元测试可直接构造 argparse.Namespace
    #   传入非 int（如 None / "10" 字符串）触发 main(args)，%d 在此场景下会抛 TypeError；
    # - %s 安全降级为 str()，与本文件其他字段（factor=%s force_full=%s）以及公共模块
    #   factor_ic_runner.py 启动行 "入口参数: min_stocks=%s, force_full=%s" 完全一致，
    #   保持项目内日志检索语法统一（grep "force_full=True" 跨模块同时命中）。
    logger.info(
        "启动 run_factor_ic: factor=%s min_stocks=%s force_full=%s",
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

    # 输出 IC 摘要（公共模块）
    # run_factor_ic 失败路径走 build_error_result（返回 dict）或抛 DataSchemaError，
    # 永不返回 None；冗余的 result is None 兜底掩盖真实错误来源（违反 dead-code skill
    # 模式 E：防御 is None 兜底面对永不返回 None 的函数），已彻底移除。
    #
    # try/except 防御性兜底（issue 1 立场统一）：
    # log_factor_summary 当前实现按设计意图不抛异常，但 SummaryLogError 作为防御层
    # 需在未来契约被回归打破时立即定位故障。except 中先 logger.warning 落盘原始异常
    # 类型（type(e).__name__）以分辨摘要层内部故障类别（KeyError vs IOError vs disk
    # full），再 raise SummaryLogError 让 __main__ 走 exit 3 分支。
    #
    # 错误来源区分（按异常类型映射退出码，详见 __main__ 块）：
    # - SummaryLogError → exit 3（主结果产物可用，仅 sidecar 待修）
    # - DataSchemaError → exit 4 / FactorCalcError → exit 5 / Exception → exit 1
    # main() 不再 sys.exit：保证 main 可被 pytest 直接调用（不杀宿主进程）。
    # raise ... from e 保留原始异常 traceback（H6 异常链铁律）。
    try:
        log_factor_summary(result, "行业5日动量因子", logger)
    except Exception as e:
        # 落盘原始异常类型，避免 SummaryLogError 包装后调用方无法区分摘要层内部故障。
        logger.warning(
            "log_factor_summary 摘要输出失败，原始异常类型: %s",
            type(e).__name__,
        )
        raise SummaryLogError(
            "log_factor_summary 摘要输出阶段失败（因子计算 result 已成功生成；"
            "故障源 = 摘要日志层而非 run_factor_ic 业务路径）"
        ) from e

    return result


if __name__ == "__main__":
    # ⚠️ 契约耦合提示（issue 3）：
    # 本 except 链精确对应 run_factor_ic / log_factor_summary 当前的异常契约。
    # 若公共模块（factor_ic_runner / factor_summary_logger / exceptions）新增或调整
    # 异常类型 —— 例如 run_factor_ic 未来引入 DataLoadError / IncrementalSyncError ——
    # 必须同步更新本捕获链（新增对应 except 分支 + 退出码映射），否则新异常会落入
    # 通用 except Exception 兜底分支以 exit 1 上报，导致退出码语义失准（业务失败被
    # 误判为程序 bug，调度器告警分流路径错误）。
    # 对应规范：PROJECT.md 跨模块数据契约同步条款（修改公共模块异常契约时需同步消费方）。
    # 退出码映射统一约束：本块 exit 1/3/4/5 与下表保持一致，未来若新增异常 → 新增退出码档。
    #
    # 异常分支顺序依据：
    # - DataSchemaError(Exception) / FactorCalcError(Exception) / SummaryLogError(Exception)
    #   均直接继承 Exception，三者是【平级关系，无父子继承】；捕获顺序在异常匹配上等价。
    # - 当前顺序为可读性约定（按错误来源远近排序：schema 失败发生在数据加载阶段（最早），
    #   因子计算失败发生在加载之后，摘要日志失败发生在主流程末尾）。
    # - 通用 Exception 必须放最后，作为非业务异常的兜底（程序 bug → CRITICAL 告警语义）。
    # 退出码档（PROJECT.md H12 R17/R18/R19）：
    # - exit 4 (R18) → 上游数据 / 列契约排查路径（DataSchemaError）
    # - exit 5 (R19) → 因子计算代码 / 边界条件排查路径（FactorCalcError）
    # - exit 3 (R17) → 主结果可用仅 sidecar 待修，调度器降级告警（SummaryLogError）
    # - exit 1     → 未预期错误兜底（CRITICAL 立即响应）
    # 日志方法分类（issue 5：DataSchemaError / FactorCalcError 改用 logger.exception）：
    # - 业务异常子类（DataSchemaError / FactorCalcError / SummaryLogError）：
    #   原方案为 logger.error 并在注释中以"堆栈是噪音"为由排除堆栈。但实际上：
    #   * 这些异常通过 raise ... from e 形成异常链（H6 异常链铁律 + PROJECT.md 规则 #10），
    #     仅 logger.error("...: %s", e) 只输出最外层 __str__，丢失 __cause__ 链上的
    #     原始异常（典型场景：FactorCalcError 包装 KeyError，运维只看到"因子计算失败"
    #     看不到根因列名）。
    #   * H12 R17/R18/R19 退出码档把这三类异常定级为"业务失败立即响应"，与
    #     CRITICAL 级别可观测性诉求一致 → 必须保留完整异常链 traceback。
    #   * PROJECT.md 规则 #13 禁止 exc_info=True，因此使用 logger.exception 自动
    #     附加堆栈与异常链，是唯一合规方案。
    # - 未预期 Exception：logger.exception（保持不变，定位 bug 必需）。
    try:
        main(parse_args())
    except DataSchemaError as e:
        # message 字段独立可读 + logger.exception 自动附加堆栈与异常链。
        logger.exception("行业5日动量因子IC计算失败 (数据列依赖不匹配): %s", e)
        sys.exit(4)  # H12 R18: schema 失败 → 检查上游数据
    except FactorCalcError as e:
        logger.exception("行业5日动量因子IC计算失败: %s", e)
        sys.exit(5)  # H12 R19: 因子计算失败 → 检查计算代码
    except SummaryLogError as e:
        # 不用 logger.exception：原始异常类型已由 main() 内 logger.warning 单独落盘，
        # SummaryLogError.__str__ 自带定位信息，再附加堆栈会与 warning 重复记录同一次失败。
        logger.error("摘要日志层失败（主结果产物已生成，可用）: %s", e)
        sys.exit(3)  # H12 R17: 辅助层失败专用退出码
    except Exception:
        logger.exception("未预期的错误")
        sys.exit(1)
