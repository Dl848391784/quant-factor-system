#!/usr/bin/env python3
"""
量比因子 IC 计算器 - 使用公共模块主入口

遵循 PROJECT.md 公共模块强制复用规范：
- 主流程使用 run_simple_factor_ic()（禁止手写三模式分支）
- 无需自定义因子计算（量比因子 volume_ratio_5 已在缓存中）

代码量：~165行（CLI 入口 + 结果摘要 + 异常处理），因子计算使用公共模块 run_simple_factor_ic。

因子定义：
- volume_ratio_5 = 当日成交量 / 过去5日平均成交量
- 含义：量比（成交量相对强度）
  - > 1 → 成交量放大（高于历史平均）
  - < 1 → 成交量萎缩（低于历史平均）
  - = 1 → 成交量正常

边界处理：
- 过去5日成交量不足时设为 NaN
- 成交量为 0 时设为 NaN

作者: 云瑶
创建日期: 2026-05-08
重构日期: 2026-05-23（v2：使用 run_simple_factor_ic）
版本历史:
  v1.0 (2026-05-08): 初始版本，独立实现量比因子 IC 计算（253行）
  v2.0 (2026-05-23): 重构，使用 run_simple_factor_ic 公共模块（代码量降至~60行）
  v2.1 (2026-06-01):
    - argparse 导入移至文件顶部（遵循 PEP 8）
    - 删除启动日志（公共模块已有等效日志）
    - 删除历史遗留注释（"问题2修复"、"问题3修复"）
    - 删除重复的 ic_metrics 赋值（第74行冗余）
    - 新增 result 为 None 保底处理
    - 新增 ic_distribution_consistency 字段读取（对齐 MODULE.md 第56行）
    - positive_ratio 取值位置修正（从 ic_distribution 取而非 result）
    - N/A 日志信息补充原因（ic_std/icir/positive_ratio）
    - 异常告警层级补充（ic_mean/ic_std/icir/positive_ratio warning）
    - 完成日志移至结果摘要后（语义更清晰）
    - 异常处理简化（删除 RuntimeError 分支）
    - 代码量注释更新（~165行，反映实际行数）
  v2.2 (2026-06-08):
    - 新增启动参数日志（便于追溯 CLI 入参）
    - 新增自定义异常类 FactorCalcError（区分业务失败与非预期 RuntimeError）
    - 补全四字段 warning（ic_mean/ic_std/icir/positive_ratio 为 None 时告警）
    - 结果摘要合并为单条日志输出
    - 修正注释原子性表述（删除"并发场景下日志原子性"误导性描述）
    - 保底处理改为抛出 FactorCalcError（遵循异常处理规范）
"""

import argparse
import sys

# 添加项目路径
# 导入公共模块主入口（遵循 PROJECT.md 强制复用规范）
from factor_ic.common.cli_helpers import DEFAULT_MIN_STOCKS
from factor_ic.common.data_columns import JOIN_KEYS
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
        factor_name="volume_ratio",
        factor_col="volume_ratio_5",
        required_columns=JOIN_KEYS + ("volume_ratio_5",),
    )
)
# ============================================================================
# CLI 入口
# ============================================================================


def main():
    """CLI 主入口"""
    parser = argparse.ArgumentParser(description="量比因子 IC 计算器")
    parser.add_argument("--force-full", action="store_true", help="强制全量计算")
    parser.add_argument("--min-stocks", type=int, default=DEFAULT_MIN_STOCKS, help="最小股票数")

    args = parser.parse_args()

    # 启动横幅由公共模块 factor_ic_runner 统一打印（含 min_stocks/force_full）
    # 使用 FactorSpec 驱动入口（遵循 factor_cols_literal_constant_design.md §4.1）
    # 注意：run_factor_ic 通过 SPEC 声明所需列，公共模块自动加载
    result = run_factor_ic(
        spec=SPEC,
        min_stocks=args.min_stocks,
        force_full=args.force_full,
        logger=logger,
    )

    # 防御性检查：result 为 None 时抛出业务异常（遵循 PROJECT.md 异常处理规范）
    if result is None:
        raise FactorCalcError("run_factor_ic 返回 None，数据加载或计算可能失败")

    # 包裹 log_factor_summary：摘要层失败 → sys.exit(3) 显式辅助层失败信号
    # （PROJECT.md H12 R17）。因子计算 result 已成功生成，主结果产物可用，下游
    # backtest/comprehensive/summary 可正常消费；仅旁路日志摘要失败时返回 exit 3，
    # 与业务失败（exit 1）和 import-time 注册失败（exit 2）严格区分。
    try:
        log_factor_summary(result, "量比因子", logger)
    except Exception:
        logger.exception(
            "log_factor_summary 摘要输出阶段失败（因子计算 result 已成功生成；"
            "故障源 = 摘要日志层而非 run_factor_ic 业务路径）"
        )
        sys.exit(3)  # H12 R17：辅助层失败专用退出码

    # 确认结果处理完成后才输出"计算完成"日志（避免中途失败造成误导）
    logger.info("量比因子IC计算完成")

    return result


if __name__ == "__main__":
    try:
        main()
    except DataSchemaError as e:
        # 数据 Schema 校验失败（公共模块 validate_required_columns 抛出）：
        # H12 R18 → exit 4 与因子计算失败（exit 5）严格区分。
        # MODULE.md M22：业务异常用 logger.error 不打堆栈。
        logger.error("数据 Schema 校验失败 (factor=%s): %s", e.factor_name, e)
        sys.exit(4)  # H12 R18: schema 失败 → 检查上游数据
    except FactorCalcError as e:
        # 已知业务异常，使用 error()（不打印完整堆栈，但保留错误内容）
        logger.error("量比因子IC计算失败: %s", e)
        sys.exit(5)  # H12 R19: 因子计算失败 → 检查计算代码
    except Exception:
        # 未预期异常（含非预期 RuntimeError），使用 exception()（自动打印完整堆栈）
        logger.exception("未预期的错误")
        sys.exit(1)
