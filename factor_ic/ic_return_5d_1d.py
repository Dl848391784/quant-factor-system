#!/usr/bin/env python3
"""
5日累计涨幅因子 IC 计算器 - 使用公共模块主入口

遵循 PROJECT.md 公共模块强制复用规范：
- 主流程使用 run_complex_factor_ic()（禁止手写三模式分支）
- 因子计算逻辑复用 data_fetchers.factor_calculator（遵循 MODULE.md 约束 #3）

代码量：~191行（CLI 入口 + 结果摘要 + 异常处理），因子计算使用公共模块 run_complex_factor_ic。

因子定义：
- Return_5d = close[t] / close[t-5] - 1
- 含义：过去5日累计涨跌幅
  - 正值 → 上涨
  - 负值 → 下跌
  - 范围：理论 [-∞, +∞)，A股日涨跌幅±10%，5日累计约±50%

边界处理：
- 前5日数据设为 NaN（历史数据不足）
- close[t-5] = 0 时设为 NaN（无效数据）

作者: 云瑶
创建日期: 2026-05-29
版本历史:
  v1.0 (2026-05-29): 初始版本，复用 factor_calculator.calculate_return_5d
  v1.1 (2026-05-31):
    - 新增 ic_distribution_consistency 字段读取，对齐 MODULE.md 第56行定义
    - 防御性 None 处理（.get() + or {}）
    - 删除未使用导入（无额外依赖）
    - 异常处理改进（RuntimeError vs Exception 分开）
  v1.2 (2026-05-31):
    - 创建流程文档（ic_return_5d_1d_flow.md）
    - 创建测试用例（test_ic_return_5d_1d.py）
    - MODULE.md 版本同步（新增 v3.14）
  v1.3 (2026-05-31):
    - argparse 导入位置修正（移至文件顶部，遵循 PEP 8）
    - 版本历史完善（详细说明变更内容）
    - 异常处理一致性（RuntimeError logger.error, Exception logger.exception）
  v1.4 (2026-05-31):
    - 删除 main() 内重复的 argparse 导入（已移至文件顶部）
    - RuntimeError 改为 logger.error + sys.exit(1)（可预期业务失败语义更清晰）
    - icir 为 None 时补充 logger.warning（与 ic_mean 一致）
    - ic_distribution_consistency 字段注释修正（对齐 MODULE.md 定义）
  v1.5 (2026-05-31):
    - 删除启动日志（公共模块已有等效日志，避免重复）
    - ic_std 为 None 时补充 warning（根因在 ic_std，不应只在 icir 层告警）
    - positive_ratio 为 None 时补充 warning（静默忽略风险）
    - 代码量注释更新（~75行，反映实际行数）
  v1.6 (2026-05-31):
    - positive_ratio warning 改为独立 if 语句（解决 elif 链可达性缺陷）
    - v1.1 版本历史描述修正（字段来源对齐 MODULE.md 定义）
  v1.7 (2026-05-31):
    - 代码量注释更新（~100行，反映实际行数），删除 "#" 前缀
  v1.8 (2026-06-08):
    - 新增自定义异常类 FactorCalcError（区分业务失败与非预期 RuntimeError）
    - result 为 None 时改为抛出 FactorCalcError（避免直接 sys.exit 杀掉进程）
    - 新增启动参数日志（便于追溯 CLI 入参）
    - 结果摘要合并为单条日志输出
    - elif 链改为独立 if 语句（四字段均独立告警）
    - __main__ 块新增 FactorCalcError 分支
    - 代码量注释更新（~191行，反映实际行数）
"""

import argparse
import sys
from pathlib import Path


# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent.parent))

# 导入公共模块主入口（遵循 PROJECT.md 强制复用规范）
# 从 factor_calculator 导入因子计算函数（遵循 MODULE.md 约束 #3）
from data_fetchers.factor_calculator import calculate_return_5d
from factor_ic.common.cli_helpers import DEFAULT_MIN_STOCKS
from factor_ic.common.exceptions import FactorCalcError
from factor_ic.common.factor_ic_runner import run_complex_factor_ic
from factor_ic.common.factor_summary_logger import log_factor_summary
from factor_ic.common.logger_config import get_logger


logger = get_logger(__name__)

# ============================================================================
# 自定义异常类
# ============================================================================
# ============================================================================
# CLI 入口
# ============================================================================


def main():
    """CLI 主入口"""
    parser = argparse.ArgumentParser(description="5日累计涨幅因子 IC 计算器")
    parser.add_argument("--force-full", action="store_true", help="强制全量计算")
    parser.add_argument("--min-stocks", type=int, default=DEFAULT_MIN_STOCKS, help="最小股票数")

    args = parser.parse_args()

    # 启动参数日志（便于追溯本次运行配置）
    logger.info(
        "启动5日累计涨幅因子IC计算: min_stocks=%s, force_full=%s",
        args.min_stocks,
        args.force_full,
    )

    # 使用公共模块主入口（遵循 PROJECT.md 强制复用规范）
    result = run_complex_factor_ic(
        factor_name="return_5d",
        factor_col="return_5d",
        factor_cols=["close", "asset", "date"],  # 需要三列进行计算
        custom_factor_calculation=calculate_return_5d,
        # return_5d 无额外参数（公共模块默认 params=None，内部会转为 {}）
        min_stocks=args.min_stocks,
        force_full=args.force_full,
        _logger=logger,
    )

    # 防御性检查：result 为 None 时抛出业务异常（遵循 PROJECT.md 异常处理规范）
    if result is None:
        raise FactorCalcError("run_complex_factor_ic 返回 None，数据加载或计算可能失败")

    # 输出 IC 摘要 + None 状态整合告警（公共模块,M3.1）
    log_factor_summary(result, "5日累计涨幅因子", logger)

    # 确认结果处理完成后才输出"计算完成"日志
    logger.info("5日累计涨幅因子IC计算完成")

    return result


if __name__ == "__main__":
    try:
        main()
    except FactorCalcError as e:
        # 已知业务异常，使用 error()（不打印完整堆栈，但保留错误内容）
        logger.error("5日累计涨幅因子IC计算失败: %s", e)
        sys.exit(1)
    except Exception:
        # 未预期异常（含非预期 RuntimeError），使用 exception()（自动打印完整堆栈）
        logger.exception("未预期的错误")
        sys.exit(1)
