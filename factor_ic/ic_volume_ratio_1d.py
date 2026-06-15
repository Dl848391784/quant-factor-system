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
from pathlib import Path


# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent.parent))

# 导入公共模块主入口（遵循 PROJECT.md 强制复用规范）
from factor_ic.common.cli_helpers import DEFAULT_MIN_STOCKS
from factor_ic.common.exceptions import FactorCalcError
from factor_ic.common.factor_ic_runner import run_simple_factor_ic
from factor_ic.common.factor_summary_logger import log_factor_summary
from factor_ic.common.logger_config import get_logger


logger = get_logger(__name__)
# ============================================================================
# CLI 入口
# ============================================================================


def main():
    """CLI 主入口"""
    parser = argparse.ArgumentParser(description="量比因子 IC 计算器")
    parser.add_argument("--force-full", action="store_true", help="强制全量计算")
    parser.add_argument("--min-stocks", type=int, default=DEFAULT_MIN_STOCKS, help="最小股票数")

    args = parser.parse_args()

    # 启动参数日志（便于追溯本次运行配置）
    logger.info(
        "启动量比因子IC计算: min_stocks=%s, force_full=%s",
        args.min_stocks,
        args.force_full,
    )

    # 使用公共模块主入口（遵循 PROJECT.md 强制复用规范）
    # 注意：run_simple_factor_ic 只需 factor_col，公共模块自动加载该列
    result = run_simple_factor_ic(
        factor_name="volume_ratio",
        factor_col="volume_ratio_5",
        min_stocks=args.min_stocks,
        force_full=args.force_full,
        _logger=logger,
    )

    # 防御性检查：result 为 None 时抛出业务异常（遵循 PROJECT.md 异常处理规范）
    if result is None:
        raise FactorCalcError("run_simple_factor_ic 返回 None，数据加载或计算可能失败")

    # 输出 IC 摘要 + None 状态整合告警（公共模块,M3.1）
    log_factor_summary(result, "量比因子", logger)

    # 确认结果处理完成后才输出"计算完成"日志（避免中途失败造成误导）
    logger.info("量比因子IC计算完成")

    return result


if __name__ == "__main__":
    try:
        main()
    except FactorCalcError as e:
        # 已知业务异常，使用 error()（不打印完整堆栈，但保留错误内容）
        logger.error("量比因子IC计算失败: %s", e)
        sys.exit(1)
    except Exception:
        # 未预期异常（含非预期 RuntimeError），使用 exception()（自动打印完整堆栈）
        logger.exception("未预期的错误")
        sys.exit(1)
